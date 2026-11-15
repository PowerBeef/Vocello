"""Exercise native lane evidence with fake commands; never build or run XCTest.

The shipped functions run from the sourced scripts/macos_test.sh (scripts/tests/shell_stubs.py).
"""
from __future__ import annotations

import json
import os
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


def runtime_log(*cases: tuple[str, str]) -> str:
    """A `swift test` log of Qwen3RuntimeTests holding the given (test, verdict) cases."""
    lines = ["Test Suite 'Selected tests' started at now."]
    lines += [
        f"Test Case '-[Qwen3RuntimeTests.{test}]' {verdict} (0.001 seconds)." for test, verdict in cases
    ]
    skipped = sum(1 for _, verdict in cases if verdict == "skipped")
    failed = sum(1 for _, verdict in cases if verdict == "failed")
    lines.append(f"Test Suite 'Selected tests' {'failed' if failed else 'passed'} at now.")
    lines.append(
        f"\t Executed {len(cases)} tests, with "
        + (f"{skipped} tests skipped and " if skipped else "")
        + f"{failed} failures (0 unexpected) in 0.010 seconds"
    )
    return "\n".join(lines) + "\n"


PARITY = ("AudioSealParityTests testWholeBufferParityAgainstReferenceFixtures",
          "AudioSealParityTests testWindowedPathMatchesWholeBufferExactly")
# The synthetic-weight tests of the same class always run; they are not parity evidence.
SYNTHETIC = ("AudioSealParityTests testStreamableConvPaddingPreservesFrameArithmetic", "passed")


class WatermarkParityOutcomeTests(unittest.TestCase):
    """audit T13: the test lane says whether the reference-fixture watermark parity
    tests ran or skipped, from the runtime log it already has."""

    def outcome(self, log_text: str | None, fixtures: str | None = None) -> str:
        shell = LaneShell(self, "macos_test.sh")
        log = shell.path / "runtime.log"
        if log_text is not None:
            log.write_text(log_text, encoding="utf-8")
        environment = {"QWENVOICE_AUDIOSEAL_FIXTURES": fixtures} if fixtures is not None else {}
        completed = shell.run(f"audioseal_parity_outcome {shlex.quote(str(log))}\n", env=environment)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return completed.stdout.strip()

    def test_the_outcome_names_what_the_parity_tests_did(self) -> None:
        skipped = runtime_log(SYNTHETIC, *((test, "skipped") for test in PARITY))
        self.assertEqual(
            self.outcome(skipped), "skipped (2 of 2 tests: QWENVOICE_AUDIOSEAL_FIXTURES is unset)")
        # A path that holds no fixtures skips them too; the path itself is never printed.
        with_path = self.outcome(skipped, fixtures="/fixture-root/audioseal")
        self.assertEqual(
            with_path,
            "skipped (2 of 2 tests: the QWENVOICE_AUDIOSEAL_FIXTURES directory holds no parity fixtures)",
        )
        self.assertNotIn("/fixture-root", with_path)
        ran = runtime_log(SYNTHETIC, *((test, "passed") for test in PARITY))
        self.assertEqual(
            self.outcome(ran, fixtures="/fixture-root/audioseal"), "ran (2 tests against the reference fixtures)")
        # A parity test that ran and failed still ran; the runtime status carries the failure.
        failed = runtime_log((PARITY[0], "failed"), (PARITY[1], "passed"))
        self.assertEqual(self.outcome(failed, fixtures="/x"), "ran (2 tests against the reference fixtures)")
        # The synthetic tests alone, an empty log and a missing log are no parity run.
        for log_text in (runtime_log(SYNTHETIC), "", None):
            with self.subTest(log=log_text):
                self.assertEqual(self.outcome(log_text), "not run (the runtime tests never reached them)")

    def run_lane(self, runtime_text: str) -> tuple[int, str, str]:
        """The real `cmd_test` over stand-in bundles and a `swift` that prints `runtime_text`."""
        shell = LaneShell(self, "macos_test.sh")
        root = shell.path / "evidence"
        core = shell.path / "core.log"
        core.write_text(COMPLETE, encoding="utf-8")
        runtime = shell.path / "runtime-fixture.log"
        runtime.write_text(runtime_text, encoding="utf-8")
        products = shell.path / "swiftpm-bin"
        shell.tool(
            "swift",
            'case "$*" in\n'
            '  *--show-bin-path*) echo "$QV_SANDBOX/swiftpm-bin" ;;\n'
            f'  test\\ *) cat {shlex.quote(str(runtime))} ;;\n'
            "esac\nexit 0",
        )
        body = f"""QVOICE_ARTIFACTS_MACOS={shlex.quote(str(root))}
mkdir -p "$QVOICE_XCODE_MACOS_DERIVED/Build/Products/Release/mlx-swift_Cmlx.bundle" {shlex.quote(str(products))}
qv_stub build_mac_test_bundles
run_mac_test_bundle() {{ cp {shlex.quote(str(core))} "$2"; }}
qv_stub acquire_native_lock
qv_stub release_native_lock
qv_stub ensure_swiftpm_scratch_location
qv_stub assert_macho_arm64_only
qv_stub write_build_provenance
cmd_test
"""
        completed = shell.run(body)
        [verdict] = list((root / "tests").glob("mac-test-*/verdict.txt"))
        return completed.returncode, verdict.read_text(encoding="utf-8"), completed.stderr

    def test_the_lanes_verdict_carries_the_outcome_and_never_depends_on_it(self) -> None:
        code, verdict, stderr = self.run_lane(runtime_log(SYNTHETIC, *((test, "skipped") for test in PARITY)))
        self.assertEqual(code, 0, stderr)
        self.assertIn("runtime=0\n", verdict)
        self.assertIn(
            "audioseal_parity=skipped (2 of 2 tests: QWENVOICE_AUDIOSEAL_FIXTURES is unset)\n", verdict)
        # The verdict is printed, so the summary on screen says it too.
        self.assertIn("audioseal_parity=skipped", stderr)
        self.assertIn("test verdict: PASS", stderr)
        code, verdict, stderr = self.run_lane(runtime_log(SYNTHETIC, *((test, "passed") for test in PARITY)))
        self.assertEqual(code, 0, stderr)
        self.assertIn("audioseal_parity=ran (2 tests against the reference fixtures)\n", verdict)


class GateCrashDeltaTests(unittest.TestCase):
    """audit step 45: the gate's crash delta holds hang and spin reports too."""

    def test_a_new_hang_report_fails_the_gates_crash_delta(self) -> None:
        shell = LaneShell(self, "macos_test.sh")
        reports = shell.home / "Library/Logs/DiagnosticReports"
        reports.mkdir(parents=True)
        system = shell.path / "system-reports"
        system.mkdir()
        gate = shell.path / "gate"
        gate.mkdir()
        marker = gate / ".crash-marker"
        marker.write_text("", encoding="utf-8")
        armed_at = 1_800_000_000
        os.utime(marker, (armed_at, armed_at))
        # A report from before the run never counts.
        earlier = reports / "Vocello-2026-11-01-090000.ips"
        earlier.write_text("stand-in crash report", encoding="utf-8")
        os.utime(earlier, (armed_at - 60, armed_at - 60))
        body = (
            "qv_stub cmd_crashes\nstatus=0\n"
            f"gate_crash_delta {shlex.quote(str(gate))} {shlex.quote(str(marker))} || status=$?\n"
            'echo "status=$status"\n'
        )
        environment = {"QVOICE_CRASH_DELTA_SETTLE_SECONDS": "0", "QVOICE_SYSTEM_DIAGNOSTIC_REPORTS": str(system)}
        completed = shell.run(body, env=environment)
        self.assertIn("status=0", completed.stdout, completed.stderr)
        self.assertFalse((gate / "new-crashes.txt").exists())
        hang = system / "Vocello_2026-11-15-101502_host.hang"
        hang.write_text("stand-in hang report", encoding="utf-8")
        os.utime(hang, (armed_at + 10, armed_at + 10))
        completed = shell.run(body, env=environment)
        self.assertIn("status=1", completed.stdout, completed.stderr)
        self.assertEqual((gate / "new-crashes.txt").read_text(encoding="utf-8"), f"{hang}\n")


if __name__ == "__main__":
    unittest.main()
