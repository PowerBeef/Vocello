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
                mock.patch("sys.argv", ["export", "result with spaces", "attachments with spaces"]):
            with self.assertRaises(SystemExit) as exit_status:
                exec(compile(program, str(RUNNER), "exec"), {})
        self.assertEqual(exit_status.exception.code, 124)
        self.assertTrue(launch.call_args.kwargs["start_new_session"])
        self.assertEqual(kill.call_args_list, [mock.call(123, signal.SIGTERM),
                                             mock.call(123, signal.SIGKILL)])
        self.assertEqual(process.wait.call_args_list,
                         [mock.call(timeout=60), mock.call(timeout=2), mock.call()])

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
