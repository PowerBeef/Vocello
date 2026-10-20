#!/usr/bin/env python3
from __future__ import annotations

import json
import hashlib
import importlib.util
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import tempfile
import time
import unittest

from shell_stubs import ui_lane_sandbox

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "scripts" / "required_step_ledger.py"
CONTRACT = ROOT / "config" / "orchestration-contract.json"
LIBRARY = ROOT / "scripts" / "lib" / "required_steps.sh"
SPEC = importlib.util.spec_from_file_location("required_step_ledger", TOOL)
assert SPEC and SPEC.loader
ledger_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ledger_module)


class RequiredStepLedgerTests(unittest.TestCase):

    def test_operator_setting_lanes_are_explicit_and_ledger_bound(self) -> None:
        contract = json.loads(CONTRACT.read_text())
        for workflow in ("ui-ios-screen-protection", "ui-ios-take-variation"):
            with self.subTest(workflow=workflow):
                lane = contract["workflows"][workflow]
                self.assertEqual(lane["producer"], "scripts/ui_test.sh")
                self.assertIn("xcuitest", lane["requiredSteps"])
                self.assertIn("crash-delta", lane["requiredSteps"])

    @staticmethod
    def write_source_identity(path: Path) -> None:
        payload = {
            "schemaVersion": 1,
            "capturedAtUTC": "2026-07-14T12:00:00Z",
            "gitCommit": "a" * 40,
            "treeDirty": False,
        }
        canonical = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
        payload["identityDigest"] = hashlib.sha256(canonical).hexdigest()
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


    @staticmethod
    def write_fixture_contract(path: Path) -> None:
        """A synthetic workflow with optional steps for tool-semantics tests.

        Tool-semantics tests own their fixture instead of borrowing a real
        production lane, so contract workflow changes never break them.
        """
        payload = {
            "schemaVersion": 1,
            "faultInjection": {
                "enableEnvironmentVariable": "QWENVOICE_TEST_ORCHESTRATION_FAULTS",
                "stepEnvironmentVariable": "QWENVOICE_TEST_FAIL_REQUIRED_STEP",
            },
            "workflows": {
                "fixture-optional-lane": {
                    "producer": "scripts/tests/test_required_step_ledger.py",
                    "requiredSteps": ["source-provenance", "primary-run", "crash-delta"],
                    "optionalSteps": ["result-retention"],
                }
            },
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def run_tool_with(
        self, contract: Path, *arguments: str, check: bool = False
    ) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            ["python3", str(TOOL), "--contract", str(contract), *arguments],
            text=True,
            capture_output=True,
            check=False,
        )
        if check and completed.returncode != 0:
            self.fail(completed.stdout + completed.stderr)
        return completed

    def run_tool(self, *arguments: str, check: bool = False) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            ["python3", str(TOOL), "--contract", str(CONTRACT), *arguments],
            text=True,
            capture_output=True,
            check=False,
        )
        if check and completed.returncode != 0:
            self.fail(completed.stdout + completed.stderr)
        return completed

    def test_contract_is_valid(self) -> None:
        completed = self.run_tool("validate-contract", check=True)
        self.assertIn("Orchestration contract: PASS", completed.stdout)

    def test_ios_control_audit_workflow_is_complete(self) -> None:
        workflow = json.loads(CONTRACT.read_text(encoding="utf-8"))["workflows"][
            "ui-ios-control-audit"
        ]
        self.assertEqual(workflow["producer"], "scripts/ui_test.sh")
        self.assertEqual(
            workflow["requiredSteps"],
            [
                "source-provenance",
                "control-inventory",
                "control-plan",
                "control-plan-encoding",
                "crash-baseline",
                "xcuitest",
                "control-observation-collection",
                "control-audit-composition",
                "crash-delta",
            ],
        )
        self.assertEqual(
            workflow["optionalSteps"],
            ["control-audit-device-correlation", "result-retention"],
        )

    def test_an_explicit_retention_pin_is_written_before_the_lane_runs_anything(self) -> None:
        # The real scripts/ui_test.sh in a sandbox (scripts/tests/shell_stubs.py). Its first
        # step, the provenance snapshot, is a stand-in that notes whether the pin already
        # exists and then fails, so the lane stops before Xcode.
        snapshot = (
            'if compgen -G "$QV_SANDBOX/build/*/macos/*/retention-pin.json" >/dev/null; then\n'
            "  qv_record pin-present\n"
            "fi\n"
            "exit 1\n"
        )
        for retain in (True, False):
            with self.subTest(retain=retain):
                sandbox = ui_lane_sandbox(self)
                (sandbox.root / "QwenVoice.xcodeproj").mkdir()
                sandbox.helper("scripts/publish_benchmark_history.py", snapshot)
                sandbox.executable("scripts/clean_build_caches.sh")
                arguments = ["macos", "smoke", "--scenario", "layout"] + (["--retain-result"] if retain else [])
                completed = sandbox.run_script(*arguments)
                self.assertEqual(completed.returncode, 1)
                self.assertIn("could not capture pre-run source provenance", completed.stderr)
                [run] = [path.parent for path in sandbox.build.rglob("run.json")]
                self.assertEqual(json.loads((run / "run.json").read_text(encoding="utf-8"))["status"], "failed")
                pin = run / "retention-pin.json"
                if retain:
                    self.assertEqual(json.loads(pin.read_text(encoding="utf-8")),
                                     {"schemaVersion": 1, "pinned": True, "reason": "explicit-ui-campaign-retention"})
                    self.assertIn("pin-present", sandbox.names())
                else:
                    self.assertFalse(pin.exists())
                    self.assertNotIn("pin-present", sandbox.names())
                # A run that stopped early never reached Xcode and never pruned results.
                for later in ("xcb_run", "xcodebuild", "scripts/clean_build_caches.sh"):
                    self.assertNotIn(later, sandbox.names())

    def test_workflow_producers_bind_every_declared_step_and_finalize_before_release_evidence(self) -> None:
        # Shell producers are checked where their behaviour can be: the macOS gates and
        # release readiness run in test_macos_gate.py, the iPhone gates in
        # test_profile_capture_contract.py (IOSGateTests), and the UI lanes, which need
        # a device or the app's UI to run, by scripts/repo_invariants.sh.
        shell_producers = {"scripts/macos_test.sh", "scripts/ios_device.sh", "scripts/ui_test.sh"}
        workflows = json.loads(CONTRACT.read_text(encoding="utf-8"))["workflows"]
        for workflow_id, workflow in workflows.items():
            producer = workflow["producer"]
            if producer in shell_producers:
                continue
            steps = workflow["requiredSteps"] + workflow.get("optionalSteps", [])
            with self.subTest(workflow=workflow_id, producer=producer):
                self.assertTrue(producer.endswith(".yml"), f"{producer} is a producer no test covers")
                text = (ROOT / producer).read_text(encoding="utf-8")
                self.assertIn("required_step_ledger.py init", text)
                self.assertIn("required_step_ledger.py finalize", text)
                for step in steps:
                    self.assertRegex(text, rf"--step\s+{re.escape(step)}\b")
                self.assertRegex(
                    text,
                    r"required_step_ledger\.py finalize[\s\S]{0,900}release_evidence\.py create",
                    "release evidence can be created before managed required-step finalization",
                )

    def test_every_declared_required_step_is_failure_injected(self) -> None:
        # CI-15: this matrix is quadratic in each lane's steps, so it drives the
        # ledger functions in-process; the subprocess tests above and below cover
        # the command-line plumbing once.
        workflows = json.loads(CONTRACT.read_text(encoding="utf-8"))["workflows"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for workflow_id, workflow in workflows.items():
                for failed_step in workflow["requiredSteps"]:
                    with self.subTest(workflow=workflow_id, step=failed_step):
                        ledger = root / f"{workflow_id}-{failed_step}.json"
                        identity = None
                        if workflow.get("sourceIdentityRequired"):
                            identity = root / f"{workflow_id}-source.json"
                            self.write_source_identity(identity)
                        ledger_module.initialize(ledger, CONTRACT, workflow_id, "fixture", identity)
                        for step in workflow["requiredSteps"]:
                            ledger_module.record(ledger, step, 19 if step == failed_step else 0)
                        for step in workflow.get("optionalSteps", []):
                            ledger_module.record(ledger, step, 0)
                        self.assertFalse(ledger_module.finalize(ledger))
                        payload = json.loads(ledger.read_text(encoding="utf-8"))
                        self.assertEqual(payload["status"], "failed")
                        self.assertIn(failed_step, payload["failedRequiredSteps"])

    def test_missing_interrupted_step_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "ledger.json"
            self.run_tool(
                "init", "--ledger", str(ledger), "--workflow", "macos-release-readiness",
                "--run-id", "interrupted", check=True,
            )
            self.run_tool(
                "record", "--ledger", str(ledger), "--step", "project-inputs",
                "--exit-code", "0", check=True,
            )
            completed = self.run_tool("finalize", "--ledger", str(ledger))
            self.assertNotEqual(completed.returncode, 0)
            payload = json.loads(ledger.read_text(encoding="utf-8"))
            self.assertIn("app-build", payload["missingRequiredSteps"])
            self.assertNotEqual(payload["status"], "passed")

    def test_optional_failure_cannot_change_required_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "ledger.json"
            fixture = Path(directory) / "contract.json"
            self.write_fixture_contract(fixture)
            workflow = "fixture-optional-lane"
            contract = json.loads(fixture.read_text(encoding="utf-8"))["workflows"][workflow]
            self.run_tool_with(
                fixture,
                "init", "--ledger", str(ledger), "--workflow", workflow,
                "--run-id", "optional", check=True,
            )
            for step in contract["requiredSteps"]:
                self.run_tool_with(
                    fixture,
                    "record", "--ledger", str(ledger), "--step", step,
                    "--exit-code", "0", check=True,
                )
            self.run_tool_with(
                fixture,
                "record", "--ledger", str(ledger), "--step", "result-retention",
                "--exit-code", "23", check=True,
            )
            self.run_tool_with(fixture, "finalize", "--ledger", str(ledger), check=True)
            payload = json.loads(ledger.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "passed")
            self.assertEqual(payload["results"]["result-retention"]["status"], "failed")

    def test_duplicate_and_stale_ledger_writes_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "ledger.json"
            init = (
                "init", "--ledger", str(ledger), "--workflow", "macos-release-readiness",
                "--run-id", "stale",
            )
            self.run_tool(*init, check=True)
            self.assertNotEqual(self.run_tool(*init).returncode, 0)
            record = (
                "record", "--ledger", str(ledger), "--step", "project-inputs",
                "--exit-code", "0",
            )
            self.run_tool(*record, check=True)
            self.assertNotEqual(self.run_tool(*record).returncode, 0)

    def test_shell_fault_injection_requires_explicit_test_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / "ledger.json"
            # Quoted: a clone path may contain spaces.
            quoted = shlex.quote(str(ledger))
            script = f"""
set -euo pipefail
ROOT_DIR={shlex.quote(str(ROOT))}
. {shlex.quote(str(LIBRARY))}
required_steps_init {quoted} fixture-optional-lane fixture
for step in source-provenance primary-run crash-delta; do
  required_step_run {quoted} "$step" true || true
done
required_step_run {quoted} result-retention true || true
required_steps_finalize {quoted}
"""
            fixture = root / "contract.json"
            self.write_fixture_contract(fixture)
            environment = os.environ.copy()
            environment.update({
                "QWENVOICE_TEST_ORCHESTRATION_FAULTS": "1",
                "QWENVOICE_TEST_FAIL_REQUIRED_STEP": "fixture-optional-lane:primary-run",
                "QVOICE_ORCHESTRATION_CONTRACT": str(fixture),
            })
            completed = subprocess.run(
                ["bash", "-c", script], text=True, capture_output=True,
                env=environment, check=False,
            )
            self.assertNotEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            payload = json.loads(ledger.read_text(encoding="utf-8"))
            self.assertEqual(payload["results"]["primary-run"]["exitCode"], 97)
            self.assertEqual(payload["results"]["result-retention"]["status"], "passed")
            self.assertEqual(payload["status"], "failed")

    def test_managed_timeout_records_failure_and_cannot_finalize_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "ledger.json"
            fixture = Path(directory) / "contract.json"
            self.write_fixture_contract(fixture)
            self.run_tool_with(
                fixture,
                "init", "--ledger", str(ledger), "--workflow", "fixture-optional-lane",
                "--run-id", "timeout", check=True,
            )
            completed = self.run_tool_with(
                fixture,
                "run", "--ledger", str(ledger), "--step", "source-provenance",
                "--timeout-seconds", "1", "--", "python3", "-c", "import time; time.sleep(30)",
            )
            self.assertEqual(completed.returncode, 124, completed.stdout + completed.stderr)
            payload = json.loads(ledger.read_text(encoding="utf-8"))
            self.assertEqual(payload["results"]["source-provenance"]["status"], "failed")
            manifest = json.loads((ledger.parent / "steps/source-provenance.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["outcome"], "timeout")
            self.assertNotEqual(self.run_tool("finalize", "--ledger", str(ledger)).returncode, 0)

    def test_release_steps_reject_arbitrary_successful_commands_before_launch(self) -> None:
        workflows = json.loads(CONTRACT.read_text(encoding="utf-8"))["workflows"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for workflow_id in ("release-macos-candidate", "release-ios-candidate"):
                identity = root / f"{workflow_id}-source.json"
                self.write_source_identity(identity)
                for step in workflows[workflow_id]["requiredSteps"]:
                    with self.subTest(workflow=workflow_id, step=step):
                        ledger = root / f"{workflow_id}-{step}.json"
                        self.run_tool(
                            "init", "--ledger", str(ledger), "--workflow", workflow_id,
                            "--run-id", "reject-arbitrary-command", "--source-identity", str(identity),
                            check=True,
                        )
                        completed = self.run_tool(
                            "run", "--ledger", str(ledger), "--step", step,
                            "--timeout-seconds", "5", "--", "true",
                        )
                        self.assertNotEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                        self.assertIn("does not match the contract template", completed.stderr)
                        payload = json.loads(ledger.read_text(encoding="utf-8"))
                        self.assertEqual(payload["results"], {})
                        self.assertFalse((ledger.parent / f"steps/{step}.json").exists())

    def test_release_step_templates_bind_their_literal_commands(self) -> None:
        contract = ledger_module.validated_contract(CONTRACT)
        ios = contract["workflows"]["release-ios-candidate"]
        self.assertEqual(
            ledger_module.bind_command(
                ios,
                "platform-readiness",
                [
                    "bash", "-euo", "pipefail", "-c",
                    "scripts/macos_test.sh gate && ./scripts/build_foundation_targets.sh ios",
                ],
            )["commandTemplateID"],
            "ios-platform-readiness-v1",
        )
        ipa_verification = [
            "python3", "scripts/verify_ios_release_artifacts.py",
            "--archive", "build/dist/ios/Vocello.xcarchive",
            "--export-dir", "build/dist/ios/export",
            "--expected-team-id-env", "QWENVOICE_DEVELOPMENT_TEAM",
            "--output", "build/dist/ios/ios-release-artifact-verification.json",
        ]
        self.assertIsNotNone(ledger_module.bind_command(ios, "ipa-verification", ipa_verification))

        macos = contract["workflows"]["release-macos-candidate"]
        self.assertIsNotNone(ledger_module.bind_command(
            macos, "release-build", ["./scripts/release.sh", "--preflight", "none"]
        ))
        self.assertIsNotNone(ledger_module.bind_command(
            macos, "release-build",
            ["./scripts/release.sh", "--preflight", "none", "--output-name", "Vocello candidate"],
        ))
        self.assertIsNotNone(ledger_module.bind_command(
            macos, "artifact-verification", [
                "./scripts/verify_packaged_dmg.sh",
                "build/dist/macos/Vocello candidate.dmg",
                "build/dist/macos/release-metadata.txt",
            ]
        ))

    def test_declared_outputs_are_hashed_and_missing_outputs_fail_the_step(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract = root / "orchestration.json"
            identity = root / "source.json"
            self.write_source_identity(identity)
            python = "from pathlib import Path; p=Path('build/dist/ios/summary.json'); p.parent.mkdir(parents=True, exist_ok=True); p.write_text('verified')"
            contract.write_text(json.dumps({
                "schemaVersion": 1,
                "faultInjection": {
                    "enableEnvironmentVariable": "FIXTURE_FAULTS",
                    "stepEnvironmentVariable": "FIXTURE_STEP",
                },
                "workflows": {
                    "release-output-fixture": {
                        "producer": "project.yml",
                        "sourceIdentityRequired": True,
                        "requiredSteps": ["verify"],
                        "commandTemplates": {
                            "verify": [
                                {
                                    "id": "write-output-v1",
                                    "argv": ["python3", "-c", python],
                                    "outputs": ["build/dist/ios/summary.json"],
                                },
                                {
                                    "id": "missing-output-v1",
                                    "argv": ["/usr/bin/true"],
                                    "outputs": ["build/dist/ios/summary.json"],
                                },
                            ],
                        },
                    },
                },
            }, indent=2), encoding="utf-8")

            def invoke(*arguments: str) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    ["python3", str(TOOL), "--contract", str(contract), *arguments],
                    text=True, capture_output=True, check=False,
                )

            successful_root = root / "successful"
            successful_root.mkdir()
            ledger = successful_root / "ledger.json"
            initialized = invoke(
                "init", "--ledger", str(ledger), "--workflow", "release-output-fixture",
                "--run-id", "output", "--source-identity", str(identity),
            )
            self.assertEqual(initialized.returncode, 0, initialized.stdout + initialized.stderr)
            completed = invoke(
                "run", "--ledger", str(ledger), "--step", "verify", "--timeout-seconds", "5",
                "--cwd", str(successful_root), "--", "python3", "-c", python,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            manifest = json.loads((ledger.parent / "steps/verify.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["outputs"][0]["path"], "build/dist/ios/summary.json")
            self.assertEqual(manifest["outputs"][0]["sha256"], hashlib.sha256(b"verified").hexdigest())

            missing_root = root / "missing"
            missing_root.mkdir()
            missing_ledger = missing_root / "ledger.json"
            initialized = invoke(
                "init", "--ledger", str(missing_ledger), "--workflow", "release-output-fixture",
                "--run-id", "missing", "--source-identity", str(identity),
            )
            self.assertEqual(initialized.returncode, 0, initialized.stdout + initialized.stderr)
            completed = invoke(
                "run", "--ledger", str(missing_ledger), "--step", "verify", "--timeout-seconds", "5",
                "--cwd", str(missing_root), "--", "/usr/bin/true",
            )
            self.assertEqual(completed.returncode, 125, completed.stdout + completed.stderr)
            self.assertIn("declared managed-step output is missing", completed.stderr)
            payload = json.loads(missing_ledger.read_text(encoding="utf-8"))
            self.assertEqual(payload["results"]["verify"]["status"], "failed")

    def test_sigterm_records_terminated_step_and_cannot_finalize_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "ledger.json"
            fixture = Path(directory) / "contract.json"
            self.write_fixture_contract(fixture)
            self.run_tool_with(
                fixture,
                "init", "--ledger", str(ledger), "--workflow", "fixture-optional-lane",
                "--run-id", "sigterm", check=True,
            )
            process = subprocess.Popen(
                [
                    "python3", str(TOOL), "--contract", str(fixture), "run",
                    "--ledger", str(ledger), "--step", "source-provenance",
                    "--timeout-seconds", "30", "--", "python3", "-c", "import time; time.sleep(30)",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            time.sleep(0.4)
            process.send_signal(signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 143, stdout + stderr)
            manifest = json.loads((ledger.parent / "steps/source-provenance.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["outcome"], "terminated")
            self.assertEqual(manifest["terminatingSignal"], "SIGTERM")
            self.assertNotEqual(self.run_tool("finalize", "--ledger", str(ledger)).returncode, 0)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
