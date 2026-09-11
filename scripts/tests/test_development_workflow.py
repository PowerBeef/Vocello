#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import io
import subprocess
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("development_workflow", ROOT / "scripts/development_workflow.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def commands(plan: dict) -> list[str]:
    return [" ".join(command) for command in plan["commands"]]


class CheckPlanTests(unittest.TestCase):
    def test_prose_only_change_runs_no_native_lane(self) -> None:
        plan = MODULE.check_plan(["docs/reference/cli.md", "README.md"])
        joined = commands(plan)
        self.assertFalse(any("macos_test.sh" in c or "build_foundation_targets" in c for c in joined))
        self.assertIn("git diff --check", joined)
        self.assertTrue(any("check_project_inputs.sh --local" in c for c in joined))

    def test_ios_source_change_runs_macos_tests_and_ios_compile(self) -> None:
        plan = MODULE.check_plan(["Sources/iOS/IOSStudioCanvas.swift"])
        joined = commands(plan)
        self.assertIn("scripts/macos_test.sh test", joined)
        self.assertTrue(any("build_foundation_targets.sh ios --incremental" in c for c in joined))

    def test_macos_only_source_change_skips_ios_compile(self) -> None:
        plan = MODULE.check_plan(["Sources/Views/SidebarView.swift"])
        joined = commands(plan)
        self.assertIn("scripts/macos_test.sh test", joined)
        self.assertFalse(any("build_foundation_targets" in c for c in joined))

    def test_changed_test_file_alone_selects_its_classes(self) -> None:
        test_file = next(ROOT.glob("Tests/VocelloCoreTests/*Tests.swift")).relative_to(ROOT).as_posix()
        plan = MODULE.check_plan([test_file])
        selected = [c for c in commands(plan) if "core-test --only" in c]
        self.assertEqual(len(selected), 1, commands(plan))
        self.assertNotIn("scripts/macos_test.sh test", commands(plan))

    def test_project_change_regenerates_first_and_website_change_checks_site(self) -> None:
        plan = MODULE.check_plan(["project.yml", "website/src/App.tsx"])
        joined = commands(plan)
        self.assertEqual(joined[0], "./scripts/regenerate_project.sh --fast")
        self.assertIn("npm --prefix website run check", joined)

    def test_check_never_schedules_ui_device_or_release_lanes(self) -> None:
        plan = MODULE.check_plan(["Sources/iOS/A.swift", "scripts/ui_test.sh", "scripts/release.sh", "website/x.ts"])
        for command in commands(plan):
            self.assertNotIn("ui_test.sh", command.split()[0])
            self.assertNotIn("ios_device.sh", command)
            self.assertNotIn("release.sh", command.split()[0])


class PythonSelectionTests(unittest.TestCase):
    def test_real_tooling_dependency_selection_reaches_consumers(self) -> None:
        selection = MODULE.python_test_selection(["scripts/analyze_prosody.py"])
        self.assertEqual(selection["mode"], "selected")
        self.assertIn("scripts/tests/test_analyze_prosody.py", selection["tests"])
        self.assertIn("scripts/tests/test_delivery_temporal_features.py", selection["tests"])

    def test_unknown_input_and_shared_tooling_fall_back_to_the_full_suite(self) -> None:
        self.assertEqual(MODULE.python_test_selection(["scripts/tests/nonexistent_helper.py"])["mode"], "full")
        self.assertEqual(MODULE.python_test_selection(["scripts/lib/build_paths.sh"])["mode"], "full")

    def test_no_tooling_input_selects_nothing(self) -> None:
        selection = MODULE.python_test_selection(["Sources/iOS/A.swift"])
        self.assertEqual(selection["mode"], "none")
        self.assertEqual(MODULE.python_test_commands(selection), [])


class CommandRunnerTests(unittest.TestCase):
    def test_failed_command_never_continues(self) -> None:
        calls: list[list[str]] = []

        def fake_run(command, **kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(command, 1 if len(calls) == 1 else 0)

        with mock.patch.object(MODULE.subprocess, "run", side_effect=fake_run):
            with self.assertRaises(MODULE.WorkflowError):
                MODULE.run_commands([["false"], ["true"]])
        self.assertEqual(calls, [["false"]])

    def test_retired_subcommands_route_to_check(self) -> None:
        with mock.patch.object(MODULE, "check_plan", return_value={"changedPaths": [], "lanes": {}, "commands": []}) as plan, \
             mock.patch.object(MODULE, "run_commands") as run:
            self.assertEqual(MODULE.main(["checkpoint"]), 0)
            plan.assert_called_once()
            run.assert_called_once_with([])

    def test_dry_run_prints_the_plan_without_running(self) -> None:
        buffer = io.StringIO()
        with mock.patch.object(MODULE, "run_commands") as run, redirect_stdout(buffer):
            self.assertEqual(MODULE.main(["check", "--dry-run", "--paths", "docs/reference/cli.md"]), 0)
        run.assert_not_called()
        self.assertIn("git diff --check", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
