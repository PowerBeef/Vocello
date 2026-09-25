#!/usr/bin/env python3
"""Fixtures for the CP-2 within-take marking peak checker (fail-closed).

The checker asserts, per successful take, that no sample at or after the
`before_marking` boundary exceeds that take's pre-marking peak beyond
tolerance, and that the marking boundaries exist at all (they are captured
only when marking actually executes, so a knob-disabled run fails)."""

from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "check_marking_peak_equality", ROOT / "scripts/check_marking_peak_equality.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def sidecar_rows(pre_peaks, mark_peaks, boundaries=True):
    """Synthesize a sampler sidecar: pre-marking samples, the marking
    boundaries, then samples inside/after the marking interval."""
    rows, t = [], 1_000
    for v in pre_peaks:
        rows.append({"kind": "sample", "capturedUptimeNS": t, "physFootprintMB": v})
        t += 500
    if boundaries:
        rows.append({"kind": "boundary", "boundary": "before_marking",
                     "capturedUptimeNS": t, "physFootprintMB": pre_peaks[-1]})
        t += 100
    for v in mark_peaks:
        rows.append({"kind": "sample", "capturedUptimeNS": t, "physFootprintMB": v})
        t += 500
    if boundaries:
        rows.append({"kind": "boundary", "boundary": "after_marking",
                     "capturedUptimeNS": t, "physFootprintMB": mark_peaks[-1]})
    return rows


class MarkingPeakEqualityTests(unittest.TestCase):
    def run_checker(self, takes, *extra: str, mlx_peaks=None,
                    engine_rows_file: str | None = None) -> int:
        """`mlx_peaks` maps a take index to its (before, after) marking MLX
        peaks, written as that take's engine row beside the sidecars; a take
        it omits gets an unchanged peak, and `mlx_peaks={}` writes no rows.
        `engine_rows_file` replaces generations.jsonl verbatim ("" omits it)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            engine = root / "runtime" / "diagnostics" / "engine"
            engine.mkdir(parents=True)
            record_takes = []
            engine_rows = []
            for i, (cell, rows) in enumerate(takes):
                gid = f"FIXTURE-{i}"
                (engine / f"samples-{gid}.jsonl").write_text(
                    "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
                record_takes.append(
                    {"cell": cell, "generationID": gid, "status": "success"})
                if mlx_peaks is None or i in mlx_peaks:
                    before, after = (mlx_peaks or {}).get(i, (2200.0, 2200.0))
                    engine_rows.append({"generationID": gid, "mlxMemoryByStage": {
                        "before_marking": {"activeMB": 900.0, "cacheMB": 0.0, "peakMB": before},
                        "after_marking": {"activeMB": 900.0, "cacheMB": 0.0, "peakMB": after},
                    }})
            contents = engine_rows_file if engine_rows_file is not None else "".join(
                json.dumps(r) + "\n" for r in engine_rows)
            if contents:
                (engine / "generations.jsonl").write_text(contents, encoding="utf-8")
            manifest = root / "benchmark-evidence.json"
            manifest.write_text(
                json.dumps({"historyRecord": {"takes": record_takes}}),
                encoding="utf-8")
            return MODULE.main([str(manifest), *extra])

    def test_marking_below_take_peak_passes(self) -> None:
        rows = sidecar_rows(pre_peaks=[400, 858, 420], mark_peaks=[430, 438])
        self.assertEqual(self.run_checker([("custom/speed/medium/cold#0", rows)]), 0)

    def test_marking_within_floor_tolerance_passes(self) -> None:
        rows = sidecar_rows(pre_peaks=[500], mark_peaks=[540])  # +40 < 48 floor
        self.assertEqual(self.run_checker([("design/warm#1", rows)]), 0)

    def test_marking_raising_take_peak_fails_closed(self) -> None:
        # The cache-stacking signature: marking lands on the still-resident
        # generation working set and adds hundreds of MB.
        rows = sidecar_rows(pre_peaks=[400, 858], mark_peaks=[1290])
        self.assertEqual(self.run_checker([("custom/cold#0", rows)]), 1)

    def test_exact_mlx_peak_catches_a_spike_the_samples_miss(self) -> None:
        # A brief marking spike that no tick landed on passes the sampled check,
        # but MLX's cumulative peak rose across the marking pass (audit #67).
        rows = sidecar_rows(pre_peaks=[400, 858], mark_peaks=[430])
        self.assertEqual(self.run_checker([("custom/cold#0", rows)]), 0)
        self.assertEqual(
            self.run_checker([("custom/cold#0", rows)], mlx_peaks={0: (2200.0, 2400.0)}), 1)
        # An unchanged peak, or one page of rounding, passes.
        self.assertEqual(
            self.run_checker([("custom/cold#0", rows)], mlx_peaks={0: (2200.0, 2200.015625)}), 0)

    def test_exact_mlx_check_fails_closed_when_marking_ran_without_its_snapshots(self) -> None:
        # The sidecar shows the marking pass ran, so the current-source lane
        # must carry the engine row and both MLX marking snapshots.
        rows = sidecar_rows(pre_peaks=[400, 858], mark_peaks=[430])
        take = [("custom/cold#0", rows)]
        no_snapshots = json.dumps({"generationID": "FIXTURE-0", "mlxMemoryByStage": {
            "after_stream": {"activeMB": 900.0, "cacheMB": 0.0, "peakMB": 2200.0}}}) + "\n"
        no_stages = json.dumps({"generationID": "FIXTURE-0"}) + "\n"
        cases = {
            "missing generations.jsonl": {"mlx_peaks": {}},
            "no row for the take": {"engine_rows_file": no_stages.replace("FIXTURE-0", "OTHER")},
            "row without MLX stages": {"engine_rows_file": no_stages},
            "row without marking snapshots": {"engine_rows_file": no_snapshots},
            "unparseable row": {"engine_rows_file": "{not json\n" + no_snapshots},
        }
        for label, options in cases.items():
            with self.subTest(label=label):
                self.assertEqual(self.run_checker(take, **options), 1)
        # Only an explicit legacy replay reports the check as unavailable.
        self.assertEqual(
            self.run_checker(take, "--allow-legacy-evidence", mlx_peaks={}), 0)
        self.assertEqual(
            self.run_checker(take, "--allow-legacy-evidence",
                             engine_rows_file=no_snapshots), 0)

    def test_missing_boundaries_fail_closed(self) -> None:
        # QWENVOICE_MARKING=off: the seam captures no boundaries, so an
        # unmarked run can never publish as marking evidence.
        rows = sidecar_rows(pre_peaks=[400, 858], mark_peaks=[420], boundaries=False)
        self.assertEqual(self.run_checker([("custom/cold#0", rows)]), 1)

    def test_missing_sidecar_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = pathlib.Path(tmp) / "benchmark-evidence.json"
            manifest.write_text(json.dumps({"historyRecord": {"takes": [
                {"cell": "clone/cold#0", "generationID": "GONE", "status": "success"}
            ]}}), encoding="utf-8")
            self.assertEqual(MODULE.main([str(manifest)]), 1)

    def test_one_bad_take_fails_the_run(self) -> None:
        good = sidecar_rows(pre_peaks=[800], mark_peaks=[810])
        bad = sidecar_rows(pre_peaks=[479], mark_peaks=[900])
        self.assertEqual(
            self.run_checker([("custom/warm#1", good), ("design/warm#1", bad)]), 1)

    def test_empty_record_fails_closed(self) -> None:
        self.assertEqual(self.run_checker([]), 1)

    def test_checker_is_clean_under_resource_warning_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            engine = root / "runtime" / "diagnostics" / "engine"
            engine.mkdir(parents=True)
            generation_id = "WARNING-STRICT"
            rows = sidecar_rows(pre_peaks=[800], mark_peaks=[810])
            (engine / f"samples-{generation_id}.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
            )
            snapshot = {"activeMB": 900.0, "cacheMB": 0.0, "peakMB": 2200.0}
            (engine / "generations.jsonl").write_text(
                json.dumps({"generationID": generation_id, "mlxMemoryByStage": {
                    "before_marking": snapshot, "after_marking": snapshot,
                }}) + "\n",
                encoding="utf-8",
            )
            manifest = root / "benchmark-evidence.json"
            manifest.write_text(
                json.dumps(
                    {
                        "historyRecord": {
                            "takes": [
                                {
                                    "cell": "custom/warm#warning-strict",
                                    "generationID": generation_id,
                                    "status": "success",
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    "-W",
                    "error::ResourceWarning",
                    str(ROOT / "scripts/check_marking_peak_equality.py"),
                    str(manifest),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertNotIn("ResourceWarning", completed.stderr)


if __name__ == "__main__":
    unittest.main()
