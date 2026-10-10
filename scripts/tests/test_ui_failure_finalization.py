"""Exercise UI evidence/EXIT behavior with callbacks; no native tools or phone."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import signal
import shlex
import subprocess
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts/ui_test.sh"
HELPER = ROOT / "scripts/lib/ui_finalization.sh"


def function(name: str) -> str:
    # Load the producer's function only; sourcing the runner would execute UI.
    match = re.search(rf"^{name}\(\) \{{\n.*?^\}}$", RUNNER.read_text(), re.M | re.S)
    assert match, name
    return match.group(0)


class UIFinalizationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="ui evidence with spaces ")
        self.addCleanup(temporary.cleanup)
        self.out = Path(temporary.name)

    def run_fixture(self, *, code=65, cleanup=0, crash=0, summary=0,
                    attachment=0, signal=None, missing_log=False, finalized=0):
        if not missing_log:
            (self.out / "xcodebuild.log").write_text(
                "Test Suite 'All tests' started at 2026-10-10 00:00:00.000.\n"
                "Test Case '-[StudioTests testCancel]' failed (0.100 seconds)\n"
                "Test Suite 'All tests' failed at 2026-10-10 00:00:00.000.\n"
                "\t Executed 1 test, with 1 failure (0 unexpected) in 0.1 (0.1) seconds\n")
        (self.out / "result.xcresult").mkdir()
        script = f'''
set -euo pipefail
source {shlex.quote(str(HELPER))}
ROOT_DIR={shlex.quote(str(ROOT))}
out={shlex.quote(str(self.out))}
result="$out/result.xcresult"
step_ledger="$out/ledger"
platform=macos
run_finalized={finalized}
candidate_collection_needed=0
candidate_collection_attempted=0
ui_test_attempted=1
mac_crash_delta_attempted=0
attachments_attempted=0
warn() {{ :; }}
required_step_run() {{ shift 2; "$@"; }}
check_mac_crash_delta() {{ echo crash >>"$out/order"; return {crash}; }}
cleanup_macos_run() {{ echo cleanup >>"$out/order"; exit {cleanup}; }}
export_attachments() {{ echo attachments >>"$out/order"; return {attachment}; }}
required_steps_finalize() {{ echo finalize >>"$out/order"; return 1; }}
write_run_metadata() {{ printf '%s %s\\n' "$1" "$3" >"$out/metadata"; }}
{function("write_test_summary")}
{function("collect_ui_evidence")}
{function("cleanup_ui_run")}
'''
        if summary:
            script += f'write_test_summary() {{ return {summary}; }}\n'
        script += "trap cleanup_ui_run EXIT\ntrap 'exit 143' TERM\ntrap 'exit 130' INT\n"
        script += f"kill -{signal} $$\n" if signal else f"exit {code}\n"
        result = subprocess.run(["bash", "-c", script], text=True, capture_output=True,
                                env=os.environ, timeout=10)
        receipt = json.loads((self.out / "ui-finalization.json").read_text())
        return result, receipt

    def test_product_failure_keeps_native_exit_and_failed_test(self):
        result, receipt = self.run_fixture()
        self.assertEqual(result.returncode, 65, result.stderr)
        self.assertEqual(receipt["status"], "passed")
        tests = json.loads((self.out / "test-results.json").read_text())["tests"]
        self.assertEqual(tests[0]["verdict"], "failed")
        self.assertEqual((self.out / "metadata").read_text(), "failed 65\n")
        self.assertEqual((self.out / "order").read_text().splitlines(),
                         ["crash", "attachments", "cleanup", "finalize"])

    def test_collection_failure_cannot_convert_native_success_to_pass(self):
        result, receipt = self.run_fixture(code=0, attachment=7)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(receipt["status"], "failed")
        self.assertIn({"step": "attachments", "exitCode": 7}, receipt["steps"])
        self.assertEqual((self.out / "metadata").read_text(), "failed 1\n")

    def test_cleanup_exit_does_not_mask_product_failure_or_skip_metadata(self):
        result, receipt = self.run_fixture(cleanup=88, crash=3, summary=2)
        self.assertEqual(result.returncode, 65)
        self.assertEqual(receipt["status"], "failed")
        self.assertIn({"step": "cleanup", "exitCode": 88}, receipt["steps"])
        self.assertTrue((self.out / "metadata").exists())

    def test_missing_log_is_collection_failure(self):
        result, receipt = self.run_fixture(code=0, missing_log=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn({"step": "test-summary", "exitCode": 2}, receipt["steps"])
        self.assertFalse((self.out / "test-results.json").exists())

    def test_term_and_int_preserve_signal_exit_while_collecting(self):
        for signal, code in (("TERM", 143), ("INT", 130)):
            with self.subTest(signal=signal):
                if (self.out / "result.xcresult").exists():
                    (self.out / "result.xcresult").rmdir()
                result, receipt = self.run_fixture(signal=signal, cleanup=4)
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertEqual(receipt["status"], "failed")
                self.assertEqual((self.out / "metadata").read_text(), f"failed {code}\n")

    def test_cleanup_failure_invalidates_provisional_pass(self):
        result, receipt = self.run_fixture(code=0, cleanup=8, finalized=1)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(receipt["status"], "failed")
        self.assertEqual((self.out / "metadata").read_text(), "failed 1\n")

    def test_attachment_export_has_bounded_group_cleanup(self):
        body = function("export_attachments")
        program = body.split("<<'PY'", 1)[1].split("\n", 1)[1].split("\nPY\n", 1)[0]
        process = mock.Mock(pid=123)
        process.wait.side_effect = [subprocess.TimeoutExpired("export", 60),
                                    subprocess.TimeoutExpired("export", 2), 0]
        with mock.patch("subprocess.Popen", return_value=process) as launch, \
                mock.patch("os.killpg") as kill, \
                mock.patch("signal.signal"), \
                mock.patch("sys.argv", ["export", "result with spaces", "attachments with spaces"]):
            with self.assertRaises(SystemExit) as exit_status:
                exec(compile(program, str(RUNNER), "exec"), {})
        self.assertEqual(exit_status.exception.code, 124)
        self.assertTrue(launch.call_args.kwargs["start_new_session"])
        self.assertEqual(kill.call_args_list, [mock.call(123, signal.SIGTERM),
                                             mock.call(123, signal.SIGKILL)])
        self.assertEqual(process.wait.call_args_list,
                         [mock.call(timeout=60), mock.call(timeout=2), mock.call()])

    def assert_process_retired(self, pid):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            result = subprocess.run(["ps", "-p", str(pid), "-o", "stat="],
                                    text=True, capture_output=True)
            if result.returncode or result.stdout.strip().startswith("Z"):
                return
            time.sleep(0.02)
        self.fail(f"owned fake descendant {pid} survived collection")

    def test_collector_timeout_retires_term_ignoring_descendants(self):
        script = f'''set -euo pipefail
source {shlex.quote(str(HELPER))}
out={shlex.quote(str(self.out))}
QVOICE_UI_COLLECTION_TIMEOUT_SECONDS=0.2
stuck() {{
  bash -c 'trap "" TERM; echo "$$" > "$1"; while :; do sleep 1; done' bash "$out/child-pid" &
  wait
}}
ui_finalization_step stuck stuck
printf '%s\\n' "$ui_finalization_last_status" >"$out/status"
'''
        result = subprocess.run(["bash", "-c", script], text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.out / "status").read_text(), "124\n")
        self.assert_process_retired(int((self.out / "child-pid").read_text()))

    def test_collector_retires_descendant_after_callback_exits(self):
        script = f'''set -euo pipefail
source {shlex.quote(str(HELPER))}
out={shlex.quote(str(self.out))}
leftover() {{
  bash -c 'trap "" TERM; echo "$$" > "$1"; while :; do sleep 1; done' bash "$out/child-pid" &
  while [[ ! -f "$out/child-pid" ]]; do sleep 0.01; done
}}
ui_finalization_step leftover leftover
printf '%s\\n' "$ui_finalization_last_status" >"$out/status"
'''
        result = subprocess.run(["bash", "-c", script], text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.out / "status").read_text(), "125\n")
        self.assert_process_retired(int((self.out / "child-pid").read_text()))

    def test_export_interruption_retires_separate_process_group(self):
        program = function("export_attachments").split("<<'PY'", 1)[1].split("\n", 1)[1].split("\nPY\n", 1)[0]
        binaries = self.out / "bin"
        binaries.mkdir()
        executable = binaries / "xcrun"
        executable.write_text('#!/usr/bin/env bash\ntrap "" TERM\necho "$$" > "$QVOICE_FAKE_EXPORT_PID"\nwhile :; do sleep 1; done\n')
        executable.chmod(0o755)
        env = dict(os.environ, PATH=f"{binaries}{os.pathsep}{os.environ['PATH']}",
                   QVOICE_FAKE_EXPORT_PID=str(self.out / "exporter-pid"))
        for sig in (signal.SIGTERM, signal.SIGINT):
            with self.subTest(signal=sig):
                (self.out / "exporter-pid").unlink(missing_ok=True)
                process = subprocess.Popen([os.sys.executable, "-c", program, "result", "attachments"], env=env)
                try:
                    deadline = time.monotonic() + 3
                    while not (self.out / "exporter-pid").exists():
                        self.assertLess(time.monotonic(), deadline)
                        time.sleep(0.01)
                    descendant = int((self.out / "exporter-pid").read_text())
                    process.send_signal(sig)
                    self.assertEqual(process.wait(timeout=8), 128 + sig)
                    self.assert_process_retired(descendant)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()

    def test_real_required_step_keeps_single_export_and_caller_state(self):
        contract = self.out / "contract.json"
        contract.write_text(json.dumps({"schemaVersion": 1, "faultInjection": {
            "enableEnvironmentVariable": "QWENVOICE_TEST_ORCHESTRATION_FAULTS",
            "stepEnvironmentVariable": "QWENVOICE_TEST_FAIL_REQUIRED_STEP"}, "workflows": {
                "fixture-ui": {"producer": "scripts/ui_test.sh", "requiredSteps": ["xcuitest"], "optionalSteps": []}}}))
        script = f'''set -euo pipefail
ROOT_DIR={shlex.quote(str(ROOT))}
source "$ROOT_DIR/scripts/lib/required_steps.sh"
source {shlex.quote(str(HELPER))}
out={shlex.quote(str(self.out))}
result="$out/result.xcresult"
mkdir "$result"
step_ledger="$out/required-steps.json"
QVOICE_ORCHESTRATION_CONTRACT={shlex.quote(str(contract))}
platform=macos
candidate_collection_needed=0
candidate_collection_attempted=0
ui_test_attempted=1
mac_crash_delta_attempted=1
attachments_attempted=0
attachments_status=0
warn() {{ :; }}
note() {{ :; }}
write_test_summary() {{ return 0; }}
cleanup_macos_run() {{ return 0; }}
export_attachments() {{ echo export >>"$out/export-count"; mkdir "$out/attachments"; }}
{function("run_xcodebuild")}
{function("collect_ui_evidence")}
required_steps_init "$step_ledger" fixture-ui fixture-run
required_step_run "$step_ledger" xcuitest run_xcodebuild bash -c 'echo "Testing started"'
[[ "$attachments_attempted" == 1 && "$attachments_status" == 0 ]]
ui_finalize_collections
required_steps_finalize "$step_ledger"
'''
        result = subprocess.run(["bash", "-c", script], text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.out / "export-count").read_text(), "export\n")

    def test_parent_signal_during_collection_preserves_signal_and_retires_export(self):
        binaries = self.out / "bin"
        binaries.mkdir()
        executable = binaries / "xcrun"
        executable.write_text('#!/usr/bin/env bash\ntrap "" TERM\necho "$$" > "$QVOICE_FAKE_EXPORT_PID"\nwhile :; do sleep 1; done\n')
        executable.chmod(0o755)
        sleeper = binaries / "sleep"
        sleeper.write_text('#!/usr/bin/env bash\nif [[ "$1" == 300 ]]; then echo "$$" > "$QVOICE_FAKE_WATCHDOG_PID"; fi\nexec /bin/sleep "$@"\n')
        sleeper.chmod(0o755)
        (self.out / "result.xcresult").mkdir()
        env = dict(os.environ, PATH=f"{binaries}{os.pathsep}{os.environ['PATH']}",
                   QVOICE_FAKE_EXPORT_PID=str(self.out / "exporter-pid"),
                   QVOICE_FAKE_WATCHDOG_PID=str(self.out / "watchdog-pid"))
        for sig in (signal.SIGTERM, signal.SIGINT):
            with self.subTest(signal=sig):
                (self.out / "exporter-pid").unlink(missing_ok=True)
                script = f'''set -euo pipefail
source {shlex.quote(str(HELPER))}
out={shlex.quote(str(self.out))}
result="$out/result.xcresult"
warn() {{ :; }}
{function("export_attachments")}
trap 'exit 143' TERM
trap 'exit 130' INT
ui_finalization_step attachments export_attachments
'''
                process = subprocess.Popen(["bash", "-c", script], env=env,
                                           text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    deadline = time.monotonic() + 3
                    while not (self.out / "exporter-pid").exists():
                        self.assertLess(time.monotonic(), deadline)
                        time.sleep(0.01)
                    descendant = int((self.out / "exporter-pid").read_text())
                    process.send_signal(sig)
                    stdout, stderr = process.communicate(timeout=10)
                    self.assertEqual(process.returncode, 128 + sig, stdout + stderr)
                    self.assert_process_retired(descendant)
                    self.assert_process_retired(int((self.out / "watchdog-pid").read_text()))
                    self.assertIn(f"attachments\t{128 + sig}", (self.out / "ui-finalization.tsv").read_text())
                    # The completed shell must leave neither watchdog nor its
                    # sleeps holding the captured stdout/stderr pipes open.
                    self.assertFalse(list(self.out.glob(".ui-collection-timeout-*")))
                finally:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=8)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()

    def test_immediate_collector_signal_finishes_cleanup_and_receipt(self):
        for sig, code in (("TERM", 143), ("INT", 130)):
            with self.subTest(signal=sig):
                (self.out / "ui-finalization.tsv").unlink(missing_ok=True)
                script = f'''set -euo pipefail
source {shlex.quote(str(HELPER))}
out={shlex.quote(str(self.out))}
platform=macos
interrupt_parent() {{ kill -{sig} "$$"; }}
collect_ui_evidence() {{
  ui_finalization_step summary interrupt_parent
  ui_finalization_step attachments true
}}
cleanup_macos_run() {{ echo cleanup >>"$out/order-{sig}"; }}
finish() {{
  local original=$?
  trap - EXIT
  trap '' INT TERM
  set +e
  ui_finalize_collections
  exit "$original"
}}
trap finish EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
ui_finalize_collections
'''
                result = subprocess.run(["bash", "-c", script], text=True,
                                        capture_output=True, timeout=12)
                self.assertEqual(result.returncode, code, result.stderr)
                receipt = json.loads((self.out / "ui-finalization.json").read_text())
                self.assertEqual(receipt["status"], "failed")
                names = [step["step"] for step in receipt["steps"]]
                self.assertEqual(names, ["summary", "attachments", "cleanup", "interruption"])
                self.assertEqual((self.out / f"order-{sig}").read_text(), "cleanup\n")

    def test_native_failure_precedes_signal_during_attachment_export(self):
        script = f'''set -euo pipefail
source {shlex.quote(str(HELPER))}
out={shlex.quote(str(self.out))}
platform=macos
result="$out/result.xcresult"
step_ledger="$out/ledger"
run_finalized=0
candidate_collection_needed=0
candidate_collection_attempted=0
ui_test_attempted=1
mac_crash_delta_attempted=1
attachments_attempted=0
warn() {{ :; }}
note() {{ :; }}
write_test_summary() {{ return 0; }}
export_attachments() {{ kill -TERM "$$"; }}
cleanup_macos_run() {{ echo cleanup >>"$out/order"; }}
required_steps_finalize() {{ return 1; }}
write_run_metadata() {{ printf '%s %s\\n' "$1" "$3" >"$out/metadata"; }}
{function("run_xcodebuild")}
{function("collect_ui_evidence")}
{function("cleanup_ui_run")}
trap cleanup_ui_run EXIT
trap 'exit 143' TERM
run_xcodebuild bash -c 'exit 65'
'''
        result = subprocess.run(["bash", "-c", script], text=True,
                                capture_output=True, timeout=12)
        self.assertEqual(result.returncode, 65, result.stderr)
        self.assertEqual((self.out / "metadata").read_text(), "failed 65\n")
        self.assertEqual((self.out / "order").read_text(), "cleanup\n")
        receipt = json.loads((self.out / "ui-finalization.json").read_text())
        self.assertEqual(receipt["status"], "failed")
        self.assertIn({"step": "attachments", "exitCode": 143}, receipt["steps"])

    def test_successful_finalization_is_idempotent(self):
        script = f'''
set -euo pipefail
source {shlex.quote(str(HELPER))}
out={shlex.quote(str(self.out))}
platform=macos
collect_ui_evidence() {{ ui_finalization_step summary true; }}
cleanup_macos_run() {{ echo cleanup >>"$out/order"; }}
ui_finalize_collections
ui_finalize_collections
'''
        result = subprocess.run(["bash", "-c", script], text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.out / "order").read_text(), "cleanup\n")
        self.assertEqual(json.loads((self.out / "ui-finalization.json").read_text())["status"], "passed")


if __name__ == "__main__":
    unittest.main()
