#!/usr/bin/env python3
"""The shared shell helpers the lane scripts source (scripts/lib/shared.sh), exercised by sourcing them."""

from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "scripts/lib/shared.sh"


def run_helper(snippet: str, *arguments: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", f'. "{LIB}"; {snippet}', "helper", *arguments],
        capture_output=True, text=True, check=False, env=env, cwd=ROOT,
    )


class BenchmarkLabelTests(unittest.TestCase):
    def test_opaque_identifiers_are_accepted(self) -> None:
        for label in ("", "a", "lang-check-v1", "av14.mac_benchmark-1", "x" * 96):
            with self.subTest(label=label):
                self.assertEqual(run_helper('validate_benchmark_label "$1"', label).returncode, 0, label)

    def test_free_text_and_path_shaped_labels_are_rejected(self) -> None:
        for label in ("x" * 97, "-lead", ".lead", "a b", "../x", "x/y", "run:1", "emoji✓"):
            with self.subTest(label=label):
                completed = run_helper('validate_benchmark_label "$1"', label)
                self.assertEqual(completed.returncode, 1, label)
                self.assertIn("--label", completed.stderr)


class HelperTests(unittest.TestCase):
    def test_nonce_is_eight_hex_characters(self) -> None:
        completed = run_helper("benchmark_nonce")
        self.assertEqual(completed.returncode, 0)
        self.assertRegex(completed.stdout.strip(), r"^[0-9a-f]{8}$")

    def test_die_and_fail_exit_one_with_their_prefixes(self) -> None:
        die = run_helper('die "boom"')
        self.assertEqual(die.returncode, 1)
        self.assertIn("[error]", die.stderr)
        self.assertIn("boom", die.stderr)
        fail = run_helper('fail "boom"')
        self.assertEqual(fail.returncode, 1)
        self.assertTrue(fail.stderr.startswith("Error: boom"))

    def test_matrix_read_requires_the_matrix_path(self) -> None:
        completed = run_helper('unset MATRIX_PATH; matrix_read macOS/app/bundleIdentifier')
        self.assertEqual(completed.returncode, 1)
        self.assertIn("MATRIX_PATH is unset", completed.stderr)
        completed = run_helper(
            f'MATRIX_PATH="{ROOT}/config/apple-platform-capability-matrix.json" matrix_read macOS/app/bundleIdentifier'
        )
        self.assertEqual(completed.returncode, 0)
        self.assertTrue(completed.stdout.strip())

    def test_failed_publication_preserves_evidence_and_prints_the_repair(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "no-such-run"
            completed = run_helper('record_benchmark_history "$1"', str(missing))
        self.assertEqual(completed.returncode, 1)
        self.assertIn("evidence is preserved in", completed.stderr)
        self.assertIn("benchmark_history.py record --artifact-dir", completed.stderr)


if __name__ == "__main__":
    unittest.main()
