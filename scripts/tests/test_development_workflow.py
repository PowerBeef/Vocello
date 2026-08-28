#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
from pathlib import Path
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
            ["env", "QVOICE_GATES=quick", "./scripts/check_project_inputs.sh"],
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


if __name__ == "__main__":
    unittest.main()
