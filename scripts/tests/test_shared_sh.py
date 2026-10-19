#!/usr/bin/env python3
"""The shared shell helpers the lane scripts source (scripts/lib/shared.sh), exercised by sourcing them."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
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

    def test_qc_python_is_the_selected_interpreter_and_needs_numpy(self) -> None:
        """BKL-17: QC v2 runs under the selected Python, and one without numpy fails the lane up front."""
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("the test interpreter has no numpy")
        environment = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "VOCELLO_PYTHON": sys.executable}
        completed = run_helper('require_qc_python; printf "%s" "$QC_PYTHON"', env=environment)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, os.path.abspath(sys.executable))
        # The macOS UI benchmark's checker and the played-audio analysis use the same interpreter.
        completed = run_helper('require_numpy_python; printf "%s" "$NUMPY_PYTHON"', env=environment)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, os.path.abspath(sys.executable))

        with tempfile.TemporaryDirectory() as temporary:
            # The same interpreter without site-packages: a valid Python that cannot import numpy.
            bare = Path(temporary) / "python3"
            bare.write_text(f'#!/bin/sh\nexec "{sys.executable}" -S "$@"\n', encoding="utf-8")
            bare.chmod(0o755)
            completed = run_helper('require_qc_python; echo "reached"', env={**environment, "VOCELLO_PYTHON": str(bare)})
        self.assertEqual(completed.returncode, 1)
        self.assertIn("cannot import numpy", completed.stderr)
        self.assertNotIn("reached", completed.stdout)

    def test_failed_publication_preserves_evidence_and_prints_the_repair(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "no-such-run"
            completed = run_helper('record_benchmark_history "$1"', str(missing))
        self.assertEqual(completed.returncode, 1)
        self.assertIn("evidence is preserved in", completed.stderr)
        self.assertIn("benchmark_history.py record --artifact-dir", completed.stderr)


class DeadlineTests(unittest.TestCase):
    """run_with_deadline: a hung lane command is stopped and reported, a finished one keeps its status."""

    def run_deadline(self, snippet: str) -> tuple[subprocess.CompletedProcess, str, float]:
        import time
        with tempfile.TemporaryDirectory() as temporary:
            log = Path(temporary) / "core.log"
            log.write_text("")
            environment = {**os.environ, "QVOICE_DEADLINE_SAMPLE_SECONDS": "1"}
            started = time.monotonic()
            completed = run_helper(snippet, str(log), env=environment)
            return completed, log.read_text(), time.monotonic() - started

    def test_a_command_past_its_deadline_is_stopped_with_124(self) -> None:
        completed, log, elapsed = self.run_deadline('run_with_deadline 2 "$1" sleep 60')
        self.assertEqual(completed.returncode, 124, completed.stderr)
        self.assertIn("TIMEOUT: sleep exceeded its 2s deadline", log)
        self.assertLess(elapsed, 30)

    def test_a_shell_function_tree_is_stopped_too(self) -> None:
        completed, log, elapsed = self.run_deadline(
            'hang() { sleep 60; }; run_with_deadline 2 "$1" hang')
        self.assertEqual(completed.returncode, 124, completed.stderr)
        self.assertIn("TIMEOUT: hang", log)
        self.assertLess(elapsed, 30)

    def test_a_finished_command_keeps_its_status(self) -> None:
        self.assertEqual(self.run_deadline('run_with_deadline 5 "$1" true')[0].returncode, 0)
        self.assertEqual(self.run_deadline('run_with_deadline 5 "$1" sh -c "exit 7"')[0].returncode, 7)

    def test_a_zero_deadline_runs_without_one(self) -> None:
        completed, log, _ = self.run_deadline('run_with_deadline 0 "$1" sh -c "exit 3"')
        self.assertEqual(completed.returncode, 3)
        self.assertNotIn("TIMEOUT", log)


if __name__ == "__main__":
    unittest.main()
