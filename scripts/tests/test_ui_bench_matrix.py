"""Declared UI benchmark matrices and the spread-driven reallocation (audit #30)."""

from __future__ import annotations

import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from lib import ui_bench_matrix as matrix  # noqa: E402

TOOL = ROOT / "scripts" / "ui_bench_allocation.py"


def synthetic_record(run_id: str, spread: dict[str, float], take_seconds: float = 10.0) -> dict:
    """A ui-generation record whose warm cells spread by the given log-RTF step."""
    takes = []
    for cell in matrix.expected_cells(list(matrix.MODES), list(matrix.LENGTHS), 3):
        mode, length, state_repetition = cell.split("/")
        state, repetition = state_repetition.split("#")
        step = spread.get(f"{mode}/{length}", 0.01)
        rtf = 0.6 * math.exp(step * (int(repetition) - 1))
        takes.append({
            "cell": cell, "warmState": state,
            "metrics": {"rtf": rtf, "submitToCompletedMS": take_seconds * 1000.0, "audioSeconds": 5.0},
        })
    return {
        "run": {"id": run_id, "kind": "ui-generation", "platform": "macos", "rtfDefinition": "wall/audio"},
        "hardware": {"profileID": "mac-mini-m6-16gb"},
        "takes": takes,
    }


class DeclaredMatrixTests(unittest.TestCase):
    def test_the_canonical_matrix_is_the_29_take_matrix(self) -> None:
        config = matrix.load_config()
        warm, allocation = matrix.version_matrix(config, config["canonicalVersion"])
        cells = matrix.expected_cells(list(matrix.MODES), list(matrix.LENGTHS), warm, allocation)
        self.assertEqual(len(cells), 29)
        self.assertTrue(matrix.is_canonical(list(matrix.MODES), list(matrix.LENGTHS), 3, {}, config))
        self.assertFalse(matrix.is_canonical(["custom"], list(matrix.LENGTHS), 3, {}, config))

    def test_a_reallocated_version_is_never_canonical(self) -> None:
        config = matrix.load_config()
        warm, allocation = matrix.version_matrix(config, "proposal-5-3-2")
        cells = matrix.expected_cells(list(matrix.MODES), list(matrix.LENGTHS), warm, allocation)
        self.assertEqual(len(cells), 32)
        self.assertEqual(cells[:7], [
            "custom/medium/cold#0", *(f"custom/short/warm#{index}" for index in range(5)), "custom/medium/warm#0",
        ])
        self.assertFalse(matrix.is_canonical(list(matrix.MODES), list(matrix.LENGTHS), warm, allocation, config))

    def test_allocations_round_trip_and_refuse_malformed_entries(self) -> None:
        allocation = {"clone/long": 2, "custom/short": 5}
        text = matrix.format_allocation(allocation)
        self.assertEqual(text, "custom/short=5,clone/long=2")
        self.assertEqual(matrix.parse_allocation(text), allocation)
        self.assertEqual(matrix.parse_allocation(""), {})
        for bad in ("custom/short", "custom/short=0", "custom/tiny=3", "custom/short=2,custom/short=3"):
            with self.subTest(entry=bad), self.assertRaises(matrix.MatrixError):
                matrix.parse_allocation(bad)

    def test_the_contract_keeps_one_canonical_version(self) -> None:
        config = json.loads(matrix.CONFIG_PATH.read_text(encoding="utf-8"))
        config["versions"]["proposal-5-3-2"]["status"] = "canonical"
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "matrix.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaises(matrix.MatrixError):
                matrix.load_config(path)


class DerivationTests(unittest.TestCase):
    def test_noisy_cells_get_the_takes_quiet_cells_give_up(self) -> None:
        noisy = {f"{mode}/short": 0.05 for mode in matrix.MODES}
        records = [synthetic_record(f"run-{index}", noisy) for index in range(3)]
        version = matrix.derive(records)
        allocation = version["warmAllocation"]
        for mode in matrix.MODES:
            self.assertGreater(allocation[f"{mode}/short"], 3)
            self.assertEqual(allocation[f"{mode}/long"], matrix.MINIMUM_REPETITIONS)
        # Under the canonical matrix's own budget: equal take costs keep 27 warm takes.
        self.assertLessEqual(sum(allocation.values()), 27)
        self.assertEqual(version["takeCount"], sum(allocation.values()) + 2)
        self.assertEqual(version["derivedFrom"], ["run-0", "run-1", "run-2"])
        # The take after a cold take never counts toward a cell's spread.
        self.assertEqual(version["derivationInputs"]["custom/short"]["degreesOfFreedom"], 3)

    def test_derivation_refuses_mixed_hosts_and_missing_cells(self) -> None:
        other = synthetic_record("run-b", {})
        other["hardware"]["profileID"] = "mac-mini-m2-8gb"
        with self.assertRaises(matrix.MatrixError):
            matrix.derive([synthetic_record("run-a", {}), other])
        sparse = synthetic_record("run-c", {})
        sparse["takes"] = [take for take in sparse["takes"] if not take["cell"].startswith("clone/long")]
        with self.assertRaises(matrix.MatrixError):
            matrix.derive([sparse])

    def test_the_cli_writes_a_derived_version_the_contract_accepts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "matrix.json"
            config.write_text(matrix.CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")
            paths = []
            for index in range(2):
                path = root / f"run-{index}.json"
                path.write_text(json.dumps(synthetic_record(f"run-{index}", {"design/short": 0.08})), encoding="utf-8")
                paths.append(str(path))
            result = subprocess.run(
                [sys.executable, str(TOOL), "--config", str(config), "derive", *paths, "--write", "spread-m6"],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            loaded = matrix.load_config(config)
            self.assertEqual(loaded["canonicalVersion"], "uniform-v1")
            self.assertEqual(loaded["versions"]["spread-m6"]["status"], "derived")
            resolved = subprocess.run(
                [sys.executable, str(TOOL), "--config", str(config), "resolve", "--version", "spread-m6"],
                capture_output=True, text=True, check=True,
            ).stdout.strip()
            self.assertEqual(matrix.parse_allocation(resolved), loaded["versions"]["spread-m6"]["warmAllocation"])
            refused = subprocess.run(
                [sys.executable, str(TOOL), "--config", str(config), "derive", *paths, "--write", "uniform-v1"],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(refused.returncode, 1)


if __name__ == "__main__":
    unittest.main()
