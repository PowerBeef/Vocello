#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "development_workflow", ROOT / "scripts/development_workflow.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class DevelopmentWorkflowTests(unittest.TestCase):
    def test_project_change_uses_fast_regeneration_and_checkpoint_gate(self) -> None:
        impact = {
            "classes": ["repository-validation-surface"],
            "mergeRequiredEvidence": ["project-inputs"],
        }
        with mock.patch.object(MODULE, "evidence_impact", return_value=impact):
            plan = MODULE.workflow_plan(["project.yml"])
        self.assertIn(
            ["./scripts/regenerate_project.sh", "--fast"], plan["focusedCommands"]
        )
        self.assertIn(
            ["./scripts/check_project_inputs.sh", "--local"],
            plan["checkpointCommands"],
        )

    def test_adjacent_python_tests_are_selected_without_full_discovery(self) -> None:
        selected = MODULE.adjacent_python_tests(["scripts/tree_fingerprint.py"])
        self.assertEqual(selected, ["scripts/tests/test_tree_fingerprint.py"])

    def test_changed_swift_tests_become_one_xctest_selection(self) -> None:
        impact = {
            "classes": ["repository-validation-surface"],
            "mergeRequiredEvidence": ["macos-deterministic-tests"],
        }
        relative = "Tests/VocelloiOSLogicTests/IOSReferenceTranscriptionReviewStateTests.swift"
        with mock.patch.object(MODULE, "evidence_impact", return_value=impact):
            plan = MODULE.workflow_plan([relative])
        focused = [command for command in plan["focusedCommands"] if "core-test" in command]
        self.assertEqual(len(focused), 1)
        self.assertIn("IOSReferenceTranscriptionReviewStateTests", focused[0][-1])

    def test_checkpoint_is_evidence_driven_and_never_schedules_xcuitest(self) -> None:
        impact = {
            "classes": ["platform-ui"],
            "mergeRequiredEvidence": [
                "project-inputs",
                "macos-deterministic-tests",
                "ios-device-sdk-compile",
            ],
        }
        with mock.patch.object(MODULE, "evidence_impact", return_value=impact):
            plan = MODULE.workflow_plan(["Sources/iOS/Example.swift"])
        rendered = [MODULE._display(command) for command in plan["checkpointCommands"]]
        self.assertTrue(any("macos_test.sh test" in command for command in rendered))
        self.assertTrue(any("build_foundation_targets.sh ios --incremental" in command for command in rendered))
        self.assertFalse(any("ui_test.sh" in command for command in rendered))

    def test_website_changes_add_website_check_once(self) -> None:
        impact = {
            "classes": ["website"],
            "mergeRequiredEvidence": ["documentation-contract"],
        }
        with mock.patch.object(MODULE, "evidence_impact", return_value=impact):
            plan = MODULE.workflow_plan(["website/src/App.tsx"])
        self.assertEqual(
            plan["checkpointCommands"].count(
                ["npm", "--prefix", "website", "run", "check"]
            ),
            1,
        )

    def test_real_documentation_and_roadmap_plans_do_not_build_native_code(self):
        for path in ("docs/development-progress.md", "config/roadmap.json", "website/PRODUCT.md",
                     "Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/README.md"):
            with self.subTest(path=path):
                plan = MODULE.workflow_plan([path])
                self.assertEqual(plan["localVerification"], "documentation")
                self.assertEqual(plan["localNativeEvidence"], [])
                self.assertIn(["python3", "scripts/documentation_contract.py", "validate"], plan["checkpointCommands"])

    def test_real_native_platform_and_tooling_routes(self):
        mac = MODULE.workflow_plan(["Sources/ViewModels/VoiceDesignCoordinator.swift"])
        ios = MODULE.workflow_plan(["Sources/iOS/IOSStudioCanvas.swift"])
        shared = MODULE.workflow_plan(["Sources/QwenVoiceCore/MLXTTSEngine.swift"])
        tooling = MODULE.workflow_plan(["scripts/analyze_prosody.py"])
        self.assertNotIn("ios-device-sdk-compile", mac["localNativeEvidence"])
        self.assertIn("macos-app-build", mac["localNativeEvidence"])
        self.assertIn("ios-device-sdk-compile", ios["localNativeEvidence"])
        self.assertIn("macos-deterministic-tests", ios["localNativeEvidence"])
        self.assertIn("ios-device-sdk-compile", shared["localNativeEvidence"])
        self.assertEqual(tooling["localNativeEvidence"], [])
        self.assertTrue(tooling["mergeRequiredEvidence"])  # local != promotion/CI

    def test_mixed_docs_and_runtime_cannot_take_documentation_shortcut(self):
        plan = MODULE.workflow_plan(["docs/development-progress.md", "Sources/QwenVoiceCore/MLXTTSEngine.swift"])
        self.assertEqual(plan["localVerification"], "affected")
        self.assertIn("ios-device-sdk-compile", plan["localNativeEvidence"])

    def test_full_checkpoint_cannot_select_local_gate(self):
        plan = MODULE.workflow_plan(["docs/development-progress.md"], full=True)
        self.assertIn(["env", "-u", "QVOICE_GATES", "./scripts/check_project_inputs.sh"], plan["checkpointCommands"])
        self.assertNotIn(["./scripts/check_project_inputs.sh", "--local"], plan["checkpointCommands"])
        self.assertIn("macos-deterministic-tests", plan["localNativeEvidence"])

    def test_full_checkpoint_removes_inherited_quick_mode(self):
        command = MODULE.workflow_plan(["docs/development-progress.md"], full=True)["checkpointCommands"][2]
        result = subprocess.run([*command[:-1], "sh", "-c", 'test -z "${QVOICE_GATES:-}"'],
                                env={**os.environ, "QVOICE_GATES": "quick"}, check=False)
        self.assertEqual(result.returncode, 0)

    def test_reviewed_package_prose_stays_non_native_in_mixed_tooling_change(self):
        plan = MODULE.workflow_plan(["Packages/VocelloQwen3Core/README.md", "scripts/analyze_prosody.py"])
        self.assertEqual(plan["localNativeEvidence"], [])

    def test_routing_changes_select_full_python_discovery(self):
        selection = MODULE.python_test_selection(["config/evidence-impact.json"])
        self.assertEqual(selection["mode"], "full")
        # One test root since 2026-09-11: full mode is a single discovery over scripts/tests.
        self.assertEqual(len(MODULE.python_test_commands(selection)), 1)

    def test_reverse_dependency_selection_and_unknown_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts/tests").mkdir(parents=True)
            files = {
                "scripts/leaf.py": "VALUE = 1\n",
                "scripts/consumer.py": "import leaf\n",
                "scripts/tests/test_consumer.py": "import consumer\n",
                "scripts/tests/test_other.py": "import independent\n",
                "config/fixture.json": "{}\n",
                "scripts/unmapped.py": "VALUE = 1\n",
            }
            for path, text in files.items():
                (root / path).parent.mkdir(parents=True, exist_ok=True)
                (root / path).write_text(text)
            selected = MODULE.python_test_selection(["scripts/leaf.py"], root=root)
            self.assertEqual(selected["tests"], ["scripts/tests/test_consumer.py"])
            for path in ("scripts/unmapped.py", "config/fixture.json", "scripts/deleted.py"):
                self.assertEqual(MODULE.python_test_selection([path], root=root)["mode"], "full")
            self.assertEqual(MODULE.python_test_selection(["scripts/tests/test_other.py"], root=root)["tests"], ["scripts/tests/test_other.py"])

    def test_local_selection_is_rejected_in_ci(self):
        with mock.patch.dict(os.environ, {"CI": "true"}):
            self.assertEqual(MODULE.main(["python-tests"]), 1)
            self.assertEqual(MODULE.main(["checkpoint"]), 1)

    def test_failed_command_never_continues(self):
        with mock.patch.object(MODULE.subprocess, "run", return_value=mock.Mock(returncode=1)) as run:
            with self.assertRaises(MODULE.WorkflowError):
                MODULE.run_commands([["false"], ["true"]])
            self.assertEqual(run.call_count, 1)

    def test_optional_assists_absence_is_not_a_prerequisite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            MODULE.validate_optional_assists(root)
            (root / ".xcodebuildmcp").mkdir()
            path = root / ".xcodebuildmcp/config.yaml"
            path.write_text("deviceId: private-identifier\n")
            with self.assertRaises(MODULE.WorkflowError):
                MODULE.validate_optional_assists(root)

    def test_source_membership_overrides_stale_macos_only_classification(self):
        project = "targets:\n  App:\n    platform: iOS\n    sources:\n      - path: Sources/Views\n"
        roots = MODULE.ios_source_roots(project)
        self.assertTrue(MODULE.is_ios_source("Sources/Views/New.swift", roots))
        self.assertFalse(MODULE.is_ios_source("Sources/ViewModels/New.swift", roots))
        self.assertTrue(MODULE.is_ios_source("Sources/Views/New.swift", MODULE.ios_source_roots("unknown layout")))

    def test_edit_during_checkpoint_never_creates_pass_marker(self):
        import sys
        sys.path.insert(0, str(ROOT / "scripts"))
        plan = {"checkpointCommands": [["refresh"], ["validate"], ["gate"]]}
        with mock.patch.object(MODULE, "changed_paths", return_value=["docs/test.md"]), \
             mock.patch.object(MODULE, "workflow_plan", return_value=plan), \
             mock.patch.object(MODULE, "run_commands"), \
             mock.patch("tree_fingerprint.checkpoint_fingerprint", side_effect=["old", "edited"]), \
             mock.patch.object(MODULE, "record_commit_gate_pass") as record:
            self.assertEqual(MODULE.main(["checkpoint"]), 1)
            record.assert_not_called()

    def test_parent_gate_runs_shared_contracts_once_and_standalone_still_checks_them(self):
        parent = (ROOT / "scripts/check_project_inputs.sh").read_text()
        child = (ROOT / "scripts/check_test_workflows.sh").read_text()
        self.assertIn('"$SCRIPT_DIR/check_test_workflows.sh" --project-inputs', parent)
        for script in ("build_output_policy.py", "documentation_contract.py", "vendor_runtime_contract.py"):
            self.assertEqual(parent.count(f'python3 "$SCRIPT_DIR/{script}"'), 1)
            self.assertIn(f'[[ "$PARENT_VALIDATED" == 1 ]] || python3 scripts/{script}', child)
        self.assertNotIn("for required_policy_surface in", child)
        self.assertIn("scripts/check_project_inputs.sh --surfaces-only", child)
        self.assertNotIn("XCODE_MCP_CONFIG=", parent)

    def test_real_tooling_dependency_selection_reaches_consumers(self):
        selection = MODULE.python_test_selection(["scripts/analyze_prosody.py"])
        self.assertEqual(selection["mode"], "selected")
        self.assertIn("scripts/tests/test_analyze_prosody.py", selection["tests"])
        self.assertIn("scripts/tests/test_delivery_temporal_features.py", selection["tests"])

    def test_json_cannot_masquerade_as_prose(self):
        plan = MODULE.workflow_plan(["docs/unregistered.json"])
        self.assertEqual(plan["localVerification"], "affected")

    def test_parent_dispatch_works_with_macos_bash_nounset_in_both_modes(self):
        source = (ROOT / "scripts/check_project_inputs.sh").read_text()
        dispatch = source[source.index('if [[ "$LOCAL_MODE" == 1 ]]; then'):]
        with tempfile.TemporaryDirectory() as directory:
            child = Path(directory) / "check_test_workflows.sh"
            child.write_text('#!/bin/bash\nprintf "%s\\n" "$@"\n')
            child.chmod(0o755)
            for mode, expected in (("0", False), ("1", True)):
                result = subprocess.run(["/bin/bash", "-euc", dispatch], capture_output=True, text=True,
                                        env={**os.environ, "SCRIPT_DIR": directory, "LOCAL_MODE": mode})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("--project-inputs", result.stdout)
                self.assertEqual("--local" in result.stdout, expected)


if __name__ == "__main__":
    unittest.main()
