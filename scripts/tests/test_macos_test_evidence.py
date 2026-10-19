"""Exercise native lane evidence with fake commands; never build or run XCTest.

The shipped functions run from the sourced scripts/macos_test.sh (scripts/tests/shell_stubs.py).
"""
from __future__ import annotations

import json
import shlex
import sys
import unittest

from shell_stubs import LaneShell

COMPLETE = """Test Suite 'Selected tests' started at now.
Test Case '-[ExampleTests testExample]' passed (0.001 seconds).
Test Suite 'Selected tests' passed at now.
 Executed 1 test, with 0 failures (0 unexpected) in 0.001 seconds
"""


class MacTestEvidenceTests(unittest.TestCase):
    def test_runtime_capture_separates_diagnostics_and_preserves_exit(self):
        shell = LaneShell(self, "macos_test.sh")
        log = shell.path / "runtime streams" / "runtime.log"
        log.parent.mkdir()
        command = [sys.executable, "-c",
                   "import sys; sys.stdout.write(\"Test Case '-[A testOne]' \"); sys.stdout.flush(); "
                   "sys.stderr.write('warning: package diagnostic\\n'); sys.stderr.flush(); "
                   "sys.stdout.write('passed (0.001 seconds).\\n'); sys.exit(42)"]
        result = shell.run(f"run_runtime_test_command {shlex.quote(str(log))} {shlex.join(command)}\n")
        self.assertEqual(result.returncode, 42)
        self.assertEqual(log.read_text(), "Test Case '-[A testOne]' passed (0.001 seconds).\n")
        self.assertEqual((log.parent / "runtime.stderr.log").read_text(), "warning: package diagnostic\n")

    def run_core(self, log_text, native_status=0):
        shell = LaneShell(self, "macos_test.sh")
        root = shell.path / "core evidence"
        (root / "tests").mkdir(parents=True)
        fixture = root / "fixture.log"
        if log_text is not None:
            fixture.write_text(log_text)
        body = f"""QVOICE_ARTIFACTS_MACOS={shlex.quote(str(root))}
qv_stub build_mac_test_bundles
run_mac_test_bundle() {{
  if [[ -f {shlex.quote(str(fixture))} ]]; then cp {shlex.quote(str(fixture))} "$2"; fi
  return {native_status}
}}
cmd_core_test --only ExampleTests
"""
        result = shell.run(body)
        verdict = (root / "tests/core-test.verdict.txt").read_text()
        summary = root / "tests/core-test.test-results.json"
        return result.returncode, verdict, json.loads(summary.read_text()) if summary.exists() else None

    def test_complete_pass(self):
        code, verdict, summary = self.run_core(COMPLETE)
        self.assertEqual(code, 0)
        self.assertIn("core=0\ncore_summary=0", verdict)
        self.assertTrue(summary["complete"])

    def test_native_pass_with_partial_evidence_fails_collection(self):
        code, verdict, summary = self.run_core("Test Case '-[ExampleTests testExample]' passed (0.001 seconds).\n")
        self.assertEqual(code, 3)
        self.assertIn("core=0\ncore_summary=3", verdict)
        self.assertFalse(summary["complete"])

    def test_missing_evidence_is_not_success(self):
        code, verdict, summary = self.run_core(None)
        self.assertEqual(code, 2)
        self.assertIn("core_summary=2", verdict)
        self.assertIsNone(summary)

    def test_collection_failure_does_not_replace_native_failure_or_interruption(self):
        for native_status in (42, 130, 143):
            with self.subTest(native_status=native_status):
                code, verdict, _ = self.run_core("incomplete diagnostic", native_status)
                self.assertEqual(code, native_status)
                self.assertIn(f"core={native_status}\ncore_summary=3", verdict)


FAILED = COMPLETE.replace("passed (0.001", "failed (0.001").replace(
    "'Selected tests' passed", "'Selected tests' failed").replace("0 failures", "1 failure")


class CoreTestRepeatTests(unittest.TestCase):
    """`core-test --repeat N` builds once and stops at the first failing iteration."""

    def run_repeat(self, repeat: str, fail_on: int | None) -> tuple[int, str, int, list[list[str]], str]:
        shell = LaneShell(self, "macos_test.sh")
        root = shell.path / "repeat evidence"
        (root / "tests").mkdir(parents=True)
        count = shell.path / "iterations"
        passing, failing = shell.path / "pass.log", shell.path / "fail.log"
        passing.write_text(COMPLETE)
        failing.write_text(FAILED)
        body = f"""QVOICE_ARTIFACTS_MACOS={shlex.quote(str(root))}
qv_stub build_mac_test_bundles
run_mac_test_bundle() {{
  local n=$(( $(cat {shlex.quote(str(count))} 2>/dev/null || echo 0) + 1 ))
  echo "$n" > {shlex.quote(str(count))}
  if [[ "$n" == "{fail_on or 0}" ]]; then cp {shlex.quote(str(failing))} "$2"; return 1; fi
  cp {shlex.quote(str(passing))} "$2"
}}
cmd_core_test --only ExampleTests --repeat {shlex.quote(repeat)}
"""
        result = shell.run(body)
        verdict_path = root / "tests/core-test.verdict.txt"
        verdict = verdict_path.read_text() if verdict_path.exists() else ""
        runs = int(count.read_text()) if count.exists() else 0
        return result.returncode, verdict, runs, shell.calls_to("build_mac_test_bundles"), result.stderr

    def test_every_iteration_passing_runs_all_of_them_after_one_build(self) -> None:
        code, verdict, runs, builds, stderr = self.run_repeat("4", None)
        self.assertEqual((code, runs, len(builds)), (0, 4, 1), stderr)
        self.assertIn("core=0\ncore_summary=0\nrepeat=4\niterations=4\n", verdict)
        self.assertIn("core-test PASS (4 of 4 iterations)", stderr)

    def test_the_first_failure_stops_the_run_and_keeps_its_log(self) -> None:
        code, verdict, runs, _builds, stderr = self.run_repeat("10", 3)
        self.assertEqual((code, runs), (1, 3), stderr)
        self.assertIn("core=1\ncore_summary=0\nrepeat=10\niterations=3\n", verdict)
        self.assertIn("core-test FAIL on iteration 3 of 10", stderr)

    def test_a_single_run_keeps_the_original_verdict(self) -> None:
        code, verdict, runs, _builds, stderr = self.run_repeat("1", None)
        self.assertEqual((code, runs), (0, 1), stderr)
        self.assertEqual(verdict, "build=0\ncore=0\ncore_summary=0\n")

    def test_a_count_that_is_not_positive_is_refused_before_building(self) -> None:
        for repeat in ("0", "-2", "many", "10000"):
            with self.subTest(repeat=repeat):
                code, _verdict, runs, builds, stderr = self.run_repeat(repeat, None)
                self.assertNotEqual(code, 0)
                self.assertEqual((runs, builds), (0, []))
                self.assertIn("--repeat must be a count", stderr)


if __name__ == "__main__":
    unittest.main()
