"""Host inventory and finished-run triage stay read-only and fail closed."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("workflow_diagnostics", ROOT / "scripts/workflow_diagnostics.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
WORKFLOW_SPEC = importlib.util.spec_from_file_location("development_workflow", ROOT / "scripts/development_workflow.py")
assert WORKFLOW_SPEC and WORKFLOW_SPEC.loader
WORKFLOW = importlib.util.module_from_spec(WORKFLOW_SPEC)
WORKFLOW_SPEC.loader.exec_module(WORKFLOW)


class TriageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="vocello retained run ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def write(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
        return path

    def run_metadata(self, status="passed", code=0):
        self.write("run.json", {"runID": "run-1", "status": status, "exitCode": code, "finishedAt": "2026-10-10T00:00:00Z"})

    def ledger(self, states=None, status="passed"):
        states = states or {"xcuitest": 0, "diagnostics": 0, "restore-state": 0}
        results = {step: {"status": "passed" if code == 0 else "failed", "exitCode": code}
                   for step, code in states.items() if code is not None}
        self.write("required-steps.json", {"runID": "run-1", "status": status, "completedAt": "finished",
                   "expectedSteps": [{"id": step, "required": True} for step in states], "results": results})

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}

    def test_complete_recorded_pass_is_readonly(self):
        self.run_metadata()
        self.ledger()
        self.write("diagnostics/manifest.json", {"status": "passed"})
        before = self.snapshot()
        with mock.patch.object(MODULE.subprocess, "run", side_effect=AssertionError("no subprocesses in triage")):
            report = MODULE.triage(self.root)
        self.assertEqual(report["verdict"], "PASS")
        self.assertTrue(report["readOnly"])
        self.assertIn("diagnostics/manifest.json", report["artifacts"])
        self.assertEqual(before, self.snapshot())

    def test_passed_test_cases_do_not_prove_run_completion(self):
        self.write("test-results.json", {"tests": [{"test": "example", "verdict": "passed"}], "consistent": True})
        self.assertEqual(MODULE.triage(self.root)["verdict"], "incomplete")
        self.run_metadata()
        self.assertEqual(MODULE.triage(self.root)["verdict"], "incomplete")

    def test_product_failure_names_the_test_without_copying_private_failure_text(self):
        self.run_metadata("failed", 1)
        self.ledger({"xcuitest": 1})
        self.write("test-results.json", {"tests": [{"suite": "StudioTests", "test": "testCancel", "verdict": "failed",
                                                   "failureText": "private prompt content"}]})
        report = MODULE.triage(self.root)
        self.assertEqual(report["verdict"], "product-failure")
        self.assertEqual(report["failedTests"][0]["test"], "testCancel")
        self.assertNotIn("private prompt content", json.dumps(report))

    def classification(self, filename, status):
        self.write("xcodebuild.log", "retained automation failure log")
        self.write("xcresult-test-summary.json", {"totalTestCount": 0})
        self.write(filename, {"runID": "run-1", "status": status,
                   "xcodebuildLogSHA256": hashlib.sha256((self.root / "xcodebuild.log").read_bytes()).hexdigest(),
                   "xcresultSummarySHA256": hashlib.sha256((self.root / "xcresult-test-summary.json").read_bytes()).hexdigest()})

    def test_bound_infrastructure_classification_preserves_failure(self):
        self.run_metadata("failed", 1)
        self.ledger({"xcuitest": 1})
        self.classification("xcui-bootstrap-classification.json", "infrastructure_bootstrap_failure")
        report = MODULE.triage(self.root)
        self.assertEqual(report["verdict"], "infrastructure-failure")
        self.assertEqual(report["failedSteps"][0]["step"], "xcuitest")
        self.assertEqual(report["recordedStatus"], "failed")

    def test_stale_infrastructure_classification_cannot_override_failure(self):
        self.run_metadata("failed", 1)
        self.ledger({"xcuitest": 1})
        self.classification("xcui-bootstrap-classification.json", "infrastructure_bootstrap_failure")
        self.write("xcodebuild.log", "changed log")
        report = MODULE.triage(self.root)
        self.assertEqual(report["verdict"], "failure-unclassified")
        self.assertTrue(any("unbound" in issue for issue in report["issues"]))

    def test_external_notification_and_signal_interruptions_are_distinct(self):
        self.run_metadata("failed", 1)
        self.ledger({"xcuitest": 1})
        self.classification("xcui-external-interruption-classification.json", "infrastructure_external_interruption")
        self.assertEqual(MODULE.triage(self.root)["verdict"], "external-interruption")
        (self.root / "xcui-external-interruption-classification.json").unlink()
        self.run_metadata("failed", 143)
        self.assertEqual(MODULE.triage(self.root)["verdict"], "interrupted")

    def test_restoration_failure_and_missing_restoration_block_pass(self):
        for code in (1, None):
            with self.subTest(code=code):
                self.run_metadata()
                self.ledger({"xcuitest": 0, "restore-state": code})
                report = MODULE.triage(self.root)
                self.assertEqual(report["verdict"], "restoration-gap")

    def test_missing_required_diagnostics_block_pass(self):
        self.run_metadata()
        self.ledger({"xcuitest": 0, "diagnostics": None})
        report = MODULE.triage(self.root)
        self.assertEqual(report["verdict"], "incomplete")
        self.assertEqual(report["missingRequiredSteps"], ["diagnostics"])

    def test_nonterminal_or_contradictory_metadata_blocks_pass(self):
        self.ledger()
        for metadata in ({"status": "running", "exitCode": None}, {"status": "passed", "exitCode": None},
                         {"status": "passed", "exitCode": 0, "finishedAt": None}):
            with self.subTest(metadata=metadata):
                self.write("run.json", metadata)
                self.assertEqual(MODULE.triage(self.root)["verdict"], "incomplete")

    def test_native_test_verdicts_and_inconclusive_gate_are_preserved(self):
        self.write("verdict.txt", "test_build=0\ncore=0\nruntime=0\n")
        self.assertEqual(MODULE.triage(self.root)["verdict"], "PASS")
        self.write("verdict.txt", "test_build=1\ncore=1\nruntime=0\n")
        report = MODULE.triage(self.root)
        self.assertEqual(report["verdict"], "failure-unclassified")
        self.assertEqual({row["step"] for row in report["failedSteps"]}, {"test_build", "core"})
        self.write("verdict.txt", "GATE: INCONCLUSIVE\n")
        self.assertEqual(MODULE.triage(self.root)["verdict"], "inconclusive")

    def test_diagnosed_failure_with_zero_exit_code_remains_product_failure(self):
        self.run_metadata("diagnosedFailure", 0)
        self.ledger()
        self.assertEqual(MODULE.triage(self.root)["verdict"], "product-failure")

    def test_malformed_evidence_blocks_pass(self):
        self.run_metadata()
        self.ledger()
        self.write("test-results.json", "{partial")
        self.assertEqual(MODULE.triage(self.root)["verdict"], "incomplete")
        self.write("test-results.json", {"tests": [], "consistent": False})
        self.assertEqual(MODULE.triage(self.root)["verdict"], "incomplete")

    def test_malformed_run_and_ledger_field_types_do_not_crash_or_pass(self):
        self.ledger()
        for metadata in ({"status": [], "exitCode": []}, {"status": "passed", "exitCode": False, "finishedAt": "now"}):
            with self.subTest(metadata=metadata):
                self.write("run.json", metadata)
                self.assertEqual(MODULE.triage(self.root)["verdict"], "incomplete")
        self.run_metadata()
        self.write("required-steps.json", {"status": "passed", "expectedSteps": [{"id": "test", "required": True}],
                   "results": {"test": {"status": {}, "exitCode": 0}}})
        self.assertEqual(MODULE.triage(self.root)["verdict"], "incomplete")

    def test_crash_collection_failure_is_not_invented_as_a_product_crash(self):
        self.run_metadata("failed", 1)
        self.ledger({"crash-delta": 1})
        self.write("new-crashes.txt", "crash marker was never armed")
        report = MODULE.triage(self.root)
        self.assertEqual(report["verdict"], "failure-unclassified")
        self.assertIn("new-crashes.txt", report["evidence"])

    def test_step_manifest_missing_or_digest_drift_blocks_pass(self):
        self.run_metadata()
        self.ledger()
        path = self.root / "required-steps.json"
        data = json.loads(path.read_text())
        data["results"]["xcuitest"].update({"manifest": "steps/xcuitest.json", "manifestSHA256": "0" * 64})
        self.write("required-steps.json", data)
        self.assertEqual(MODULE.triage(self.root)["verdict"], "incomplete")
        self.write("steps/xcuitest.json", {"outcome": "completed"})
        self.assertEqual(MODULE.triage(self.root)["verdict"], "incomplete")

    def test_missing_directory_is_an_error(self):
        with self.assertRaises(ValueError):
            MODULE.triage(self.root / "missing")


class DoctorTests(unittest.TestCase):
    def test_inventory_uses_only_readonly_probes_and_does_not_claim_active_hooks(self):
        with tempfile.TemporaryDirectory(prefix="vocello doctor ") as directory:
            root = Path(directory)
            (root / ".codex").mkdir()
            (root / ".codex/hooks.json").write_text("{}")
            calls = []
            def fake_run(command, **kwargs):
                calls.append(command)
                self.assertTrue(set(command[1:]) <= {"--version", "version", "--help"})
                self.assertLessEqual(kwargs["timeout"], 5)
                return subprocess.CompletedProcess(command, 0, "1.2.3\n", "")
            with mock.patch.object(MODULE.shutil, "which", side_effect=lambda tool: None if tool == "xcode-select" else f"/tools/{tool}"), \
                    mock.patch.object(MODULE.subprocess, "run", side_effect=fake_run), \
                    mock.patch.object(MODULE.Path, "home", return_value=root):
                report = MODULE.doctor(root)
            self.assertTrue(report["readOnly"])
            self.assertTrue(report["codex"]["hooksConfigured"])
            self.assertEqual(report["codex"]["hookActivation"], "unconfirmed")
            self.assertIn("session-only", report["codex"]["mcpAvailability"])
            self.assertEqual(sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()), [".codex/hooks.json"])
            self.assertTrue(calls)

    def test_missing_optional_tools_are_reported_without_installing(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(MODULE.shutil, "which", return_value=None), \
                mock.patch.object(MODULE.Path, "home", return_value=Path(directory)), \
                mock.patch.object(MODULE.subprocess, "run", side_effect=AssertionError("nothing to probe")):
            report = MODULE.doctor(Path(directory))
        self.assertFalse(report["tools"]["codex"]["available"])
        self.assertFalse(report["xcode"]["available"])
        self.assertFalse(report["codex"]["hooksConfigured"])

    def test_doctor_and_triage_route_without_workflow_execution(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(WORKFLOW, "run_commands") as run:
            for command in (["doctor", "--json"], ["triage", directory, "--json"]):
                with mock.patch.object(WORKFLOW, "_load", return_value=MODULE), \
                        mock.patch.object(MODULE, "doctor", return_value={"readOnly": True}), redirect_stdout(io.StringIO()) as stream:
                    self.assertEqual(WORKFLOW.main(command), 0)
                    self.assertTrue(json.loads(stream.getvalue())["readOnly"])
            run.assert_not_called()
