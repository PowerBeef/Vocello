"""Exercise native lane evidence with fake commands; never build or run XCTest."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "scripts/macos_test.sh").read_text()
COMPLETE = """Test Suite 'Selected tests' started at now.
Test Case '-[ExampleTests testExample]' passed (0.001 seconds).
Test Suite 'Selected tests' passed at now.
 Executed 1 test, with 0 failures (0 unexpected) in 0.001 seconds
"""


def function(name):
    start = SOURCE.index(f"{name}() {{\n")
    return SOURCE[start:SOURCE.index("\n}\n", start) + 3]


class MacTestEvidenceTests(unittest.TestCase):
    def test_runtime_capture_separates_diagnostics_and_preserves_exit(self):
        with tempfile.TemporaryDirectory(prefix="runtime streams ") as temporary:
            root = Path(temporary)
            log = root / "runtime.log"
            command = [sys.executable, "-c",
                       "import sys; sys.stdout.write(\"Test Case '-[A testOne]' \"); sys.stdout.flush(); "
                       "sys.stderr.write('warning: package diagnostic\\n'); sys.stderr.flush(); "
                       "sys.stdout.write('passed (0.001 seconds).\\n'); sys.exit(42)"]
            result = subprocess.run(["bash", "-c", function("run_runtime_test_command")
                                     + "\nrun_runtime_test_command " + shlex.quote(str(log))
                                     + " " + shlex.join(command)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 42)
            self.assertEqual(log.read_text(), "Test Case '-[A testOne]' passed (0.001 seconds).\n")
            self.assertEqual((root / "runtime.stderr.log").read_text(), "warning: package diagnostic\n")

    def run_core(self, log_text, native_status=0):
        with tempfile.TemporaryDirectory(prefix="core evidence ") as temporary:
            root = Path(temporary)
            (root / "tests").mkdir()
            fixture = root / "fixture.log"
            if log_text is not None:
                fixture.write_text(log_text)
            script = f"""set -euo pipefail
SCRIPT_DIR={shlex.quote(str(ROOT / 'scripts'))}
QVOICE_ARTIFACTS_MACOS={shlex.quote(str(root))}
note() {{ :; }}
warn() {{ echo "$*" >&2; }}
build_mac_test_bundles() {{ return 0; }}
run_mac_test_bundle() {{
  if [[ -f {shlex.quote(str(fixture))} ]]; then cp {shlex.quote(str(fixture))} "$2"; fi
  return {native_status}
}}
{function('write_mac_test_summary')}
{function('cmd_core_test')}
cmd_core_test --only ExampleTests
"""
            env = dict(os.environ)
            env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env["PATH"]
            result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env)
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
