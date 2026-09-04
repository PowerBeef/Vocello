#!/usr/bin/env python3
from __future__ import annotations

import json
import hashlib
import importlib.util
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "scripts" / "required_step_ledger.py"
CONTRACT = ROOT / "config" / "orchestration-contract.json"
LIBRARY = ROOT / "scripts" / "lib" / "required_steps.sh"
UI_RUNNER = ROOT / "scripts" / "ui_test.sh"
SPEC = importlib.util.spec_from_file_location("required_step_ledger", TOOL)
assert SPEC and SPEC.loader
ledger_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ledger_module)


class RequiredStepLedgerTests(unittest.TestCase):
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

    def test_ui_runner_explicit_retention_pin_precedes_execution(self) -> None:
        text = UI_RUNNER.read_text(encoding="utf-8")
        parse = text.index("--retain-result) retain_result=1")
        pin = text.index('>"$out/retention-pin.json"')
        xcode = text.index('required_step_run "$step_ledger" xcuitest')
        prune = text.index('--prune-ui-results --ui-keep 1')
        self.assertLess(parse, pin)
        self.assertLess(pin, xcode)
        self.assertLess(xcode, prune)
        self.assertIn('"pinned":true', text)

    def test_producers_bind_every_declared_step_and_finalize_before_pass(self) -> None:
        workflows = json.loads(CONTRACT.read_text(encoding="utf-8"))["workflows"]
        for workflow_id, workflow in workflows.items():
            producer = workflow["producer"]
            steps = workflow["requiredSteps"] + workflow.get("optionalSteps", [])
            with self.subTest(workflow=workflow_id, producer=producer):
                text = (ROOT / producer).read_text(encoding="utf-8")
                if producer.endswith(".yml"):
                    self.assertIn("required_step_ledger.py init", text)
                    self.assertIn("required_step_ledger.py finalize", text)
                    for step in steps:
                        self.assertRegex(text, rf"--step\s+{re.escape(step)}\b")
                    self.assertRegex(
                        text,
                        r"required_step_ledger\.py finalize[\s\S]{0,900}release_evidence\.py create",
                        "release evidence can be created before managed required-step finalization",
                    )
                else:
                    self.assertIn("required_steps_init", text)
                    self.assertIn("required_steps_finalize", text)
                    for step in steps:
                        self.assertRegex(
                            text,
                            rf"required_step_(?:run|record)[\s\S]{{0,100}}\b{re.escape(step)}\b",
                            f"{producer} does not bind declared step {step}",
                        )
                    pass_markers = [
                        marker for marker in (
                            "GATE: PASS", "RELEASE READINESS: PASS", 'note "$platform $lane PASS'
                        ) if marker in text
                    ]
                    self.assertTrue(pass_markers)
                    for marker in pass_markers:
                        self.assertRegex(
                            text,
                            rf"required_steps_finalize[\s\S]{{0,1400}}{re.escape(marker)}",
                            f"{producer} can announce {marker!r} without a nearby finalizer",
                        )

    def test_every_declared_required_step_is_failure_injected(self) -> None:
        workflows = json.loads(CONTRACT.read_text(encoding="utf-8"))["workflows"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for workflow_id, workflow in workflows.items():
                for failed_step in workflow["requiredSteps"]:
                    with self.subTest(workflow=workflow_id, step=failed_step):
                        ledger = root / f"{workflow_id}-{failed_step}.json"
                        init = ["init", "--ledger", str(ledger), "--workflow", workflow_id, "--run-id", "fixture"]
                        if workflow.get("sourceIdentityRequired"):
                            identity = root / f"{workflow_id}-source.json"
                            self.write_source_identity(identity)
                            init.extend(["--source-identity", str(identity)])
                        self.run_tool(*init, check=True)
                        for step in workflow["requiredSteps"]:
                            self.run_tool(
                                "record", "--ledger", str(ledger), "--step", step,
                                "--exit-code", "19" if step == failed_step else "0", check=True,
                            )
                        for step in workflow.get("optionalSteps", []):
                            self.run_tool(
                                "record", "--ledger", str(ledger), "--step", step,
                                "--exit-code", "0", check=True,
                            )
                        completed = self.run_tool("finalize", "--ledger", str(ledger))
                        self.assertNotEqual(completed.returncode, 0)
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
            script = f"""
set -euo pipefail
ROOT_DIR={ROOT!s}
. {LIBRARY!s}
required_steps_init {ledger!s} fixture-optional-lane fixture
for step in source-provenance primary-run crash-delta; do
  required_step_run {ledger!s} "$step" true || true
done
required_step_run {ledger!s} result-retention true || true
required_steps_finalize {ledger!s}
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

    def test_release_workflow_commands_match_the_checked_in_templates(self) -> None:
        contract = ledger_module.validated_contract(CONTRACT)
        release_workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        ios = contract["workflows"]["release-ios-candidate"]
        command_bodies: dict[str, str] = {}
        for step in ("platform-readiness", "archive", "archive-verification", "ipa-export"):
            match = re.search(
                rf"--step {re.escape(step)} \\\n\s*--timeout-seconds \d+ -- bash -euo pipefail -c '([\s\S]*?)'\n",
                release_workflow,
            )
            self.assertIsNotNone(match, f"release workflow command body is missing for {step}")
            # The workflow embeds the body in a single-quoted YAML run-script, so a
            # literal quote inside it is spelled with the POSIX '\'' splice. The
            # runner's shell collapses that before the ledger ever sees the argv;
            # emulate the same collapse so this test binds what CI actually binds.
            body = match.group(1).replace("'\\''", "'")
            command_bodies[step] = body
            binding = ledger_module.bind_command(
                ios, step, ["bash", "-euo", "pipefail", "-c", body]
            )
            self.assertIsNotNone(binding)
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
        # The archive override must stay per-target: IOS_PROFILE_UUID carries a
        # build-setting macro that only the app target resolves (defined in the
        # runner-temp xcconfig the signing-import step writes), because a plain
        # global PROVISIONING_PROFILE_SPECIFIER makes every SPM/framework target
        # abort with "does not support provisioning profiles".
        self.assertIn(
            "echo 'IOS_PROFILE_UUID=$(QVOICE_PROFILE_$(TARGET_NAME))'", release_workflow
        )
        self.assertIn("QVOICE_PROFILE_VocelloiOS = %s", release_workflow)
        self.assertIn('echo "XCODE_XCCONFIG_FILE=$XCONF"', release_workflow)
        self.assertIn("CODE_SIGN_STYLE=Manual", command_bodies["archive"])
        self.assertIn('CODE_SIGN_IDENTITY="Apple Distribution"', command_bodies["archive"])
        self.assertIn('PROVISIONING_PROFILE_SPECIFIER="$IOS_PROFILE_UUID"', command_bodies["archive"])

        ipa_verification = [
            "python3", "scripts/verify_ios_release_artifacts.py",
            "--archive", "build/dist/ios/Vocello.xcarchive",
            "--export-dir", "build/dist/ios/export",
            "--expected-team-id-env", "QWENVOICE_DEVELOPMENT_TEAM",
            "--output", "build/dist/ios/ios-release-artifact-verification.json",
        ]
        self.assertIsNotNone(ledger_module.bind_command(ios, "ipa-verification", ipa_verification))
        verification_region = re.search(
            r"--step ipa-verification[\s\S]{0,700}?python3 scripts/verify_ios_release_artifacts\.py"
            r"[\s\S]{0,700}?--output build/dist/ios/ios-release-artifact-verification\.json",
            release_workflow,
        )
        self.assertIsNotNone(verification_region, "iOS artifact verification argv drifted from its template")

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
