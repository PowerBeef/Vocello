#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import io
import subprocess
import unittest
from contextlib import redirect_stderr, redirect_stdout
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
        plan = MODULE.check_plan(["docs/reference/cli.md", "README.md", "CLAUDE.md",
                                  ".claude/rules/native.md", ".claude/skills/ios-lane/SKILL.md"])
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

    def test_ui_test_sources_compile_their_bundles(self) -> None:
        """The local check compiles the bundles its dirty tree can break, in their lanes' arenas."""
        for changed, expected in [
            ("Tests/VocelloMacUITests/VocelloMacUITestCase.swift", "macos"),
            ("Tests/VocelloiOSUITests/VocelloiOSSmokeUITests.swift", "ios"),
            ("Tests/UIAutomationSupport/VocelloUIAutomationSupport.swift", "all"),
        ]:
            with self.subTest(changed=changed):
                joined = commands(MODULE.check_plan([changed]))
                self.assertIn(f"./scripts/build_ui_test_bundles.sh {expected}", joined)

    def test_xcuitest_only_changes_skip_the_deterministic_suites(self) -> None:
        """PA-06: no macOS test bundle compiles the XCUITest sources, so only their bundle compiles."""
        mac = commands(MODULE.check_plan(["Tests/VocelloMacUITests/VocelloMacUITestCase.swift"]))
        self.assertIn("./scripts/build_ui_test_bundles.sh macos", mac)
        self.assertFalse(any("macos_test.sh" in c or "build_foundation_targets" in c for c in mac), mac)
        ios = commands(MODULE.check_plan(["Tests/VocelloiOSUITests/VocelloiOSSmokeUITests.swift"]))
        self.assertIn("./scripts/build_ui_test_bundles.sh ios", ios)
        self.assertFalse(any("macos_test.sh" in c for c in ios), ios)
        # Beside a changed test class, a UI-test file never widens core-test to the whole lane.
        test_file = next(ROOT.glob("Tests/VocelloCoreTests/*Tests.swift")).relative_to(ROOT).as_posix()
        mixed = commands(MODULE.check_plan([test_file, "Tests/VocelloMacUITests/VocelloMacUITestCase.swift"]))
        self.assertTrue(any("core-test --only" in c for c in mixed), mixed)
        self.assertNotIn("scripts/macos_test.sh test", mixed)

    def test_a_clean_tree_routes_no_lane(self) -> None:
        plan = MODULE.check_plan([])
        self.assertFalse(any(plan["lanes"].values()), plan["lanes"])
        joined = commands(plan)
        for lane_command in ("macos_test.sh", "build_foundation_targets", "npm --prefix website", "build_ui_test_bundles"):
            self.assertFalse(any(lane_command in c for c in joined), joined)

    def test_ordinary_source_change_does_not_compile_ui_bundles(self) -> None:
        joined = commands(MODULE.check_plan(["Sources/ContentView.swift"]))
        self.assertFalse(any("build_ui_test_bundles" in c for c in joined))

    def test_compiling_a_ui_bundle_is_never_running_one(self) -> None:
        """`build-for-testing` builds and stops; nothing here may execute a lane.

        Asserted against the code, not the comments: the header explains at
        length what this script deliberately does not do, and naming a thing in
        prose is not invoking it.
        """
        script = (ROOT / "scripts/build_ui_test_bundles.sh").read_text(encoding="utf-8")
        code = "\n".join(
            line for line in script.splitlines() if not line.lstrip().startswith("#")
        )
        self.assertIn("build-for-testing", code)
        for forbidden in ("test-without-building", "ui_test.sh", "Simulator", "xcodebuild test"):
            self.assertNotIn(forbidden, code, f"{forbidden!r} must not be invoked here")

    def test_lineage_path_changes_are_named_unless_the_identity_changes_too(self) -> None:
        """A harness change on a kind's path list is only separated by a reviewed version bump."""
        driver = "Tests/VocelloMacUITests/VocelloMacBenchmarkUITests.swift"
        self.assertEqual(MODULE.check_plan([driver, "README.md"])["lineageReviewPaths"], [driver])
        self.assertEqual(MODULE.check_plan([driver, MODULE.LINEAGE_IDENTITY])["lineageReviewPaths"], [])
        self.assertEqual(MODULE.check_plan(["Sources/Views/SidebarView.swift"])["lineageReviewPaths"], [])

    def test_check_never_schedules_ui_device_or_release_lanes(self) -> None:
        plan = MODULE.check_plan(["Sources/iOS/A.swift", "scripts/ui_test.sh", "scripts/release.sh", "website/x.ts"])
        for command in commands(plan):
            self.assertNotIn("ui_test.sh", command.split()[0])
            self.assertNotIn("ios_device.sh", command)
            self.assertNotIn("release.sh", command.split()[0])


class LintTests(unittest.TestCase):
    """SwiftLint is pinned like shellcheck and never skipped silently (PA-06)."""

    def lint(self, *, installed: bool, version: str | None = None) -> tuple[list[str], str]:
        swift = "Sources/ContentView.swift"
        stderr = io.StringIO()
        with mock.patch.object(MODULE, "_which", side_effect=lambda name: installed if name == "swiftlint" else True), \
                mock.patch.object(MODULE, "_installed_version", return_value=version), redirect_stderr(stderr):
            joined = [" ".join(command) for command in MODULE.lint_commands([swift])]
        return joined, stderr.getvalue()

    def test_a_missing_swiftlint_is_reported(self) -> None:
        joined, stderr = self.lint(installed=False)
        self.assertFalse(any(c.startswith("swiftlint") for c in joined), joined)
        self.assertIn("swiftlint is not on PATH", stderr)
        self.assertIn("install_pinned_tools.sh swiftlint", stderr)

    def test_only_a_swiftlint_other_than_the_pin_is_named(self) -> None:
        pinned = MODULE._pinned_version("swiftlint")
        self.assertRegex(pinned or "", r"^\d+\.\d+\.\d+$")
        joined, stderr = self.lint(installed=True, version=pinned)
        self.assertTrue(any(c.startswith("swiftlint lint") for c in joined), joined)
        self.assertEqual(stderr, "")
        _, stderr = self.lint(installed=True, version="0.0.1")
        self.assertIn(f"swiftlint 0.0.1 is not the pinned {pinned}", stderr)


class PythonSelectionTests(unittest.TestCase):
    def test_claude_configuration_selects_agent_hook_tests(self) -> None:
        for path in (".claude/settings.json", ".claude/skills/ios-lane/SKILL.md", ".claude/agents/xcresult-triage.md",
                     ".claude/rules/native.md"):
            with self.subTest(path=path):
                selection = MODULE.python_test_selection([path])
                self.assertEqual(selection["mode"], "selected")
                self.assertIn("scripts/tests/test_agent_hooks.py", selection["tests"])

    def test_real_tooling_dependency_selection_reaches_consumers(self) -> None:
        selection = MODULE.python_test_selection(["scripts/analyze_prosody.py"])
        self.assertEqual(selection["mode"], "selected")
        self.assertIn("scripts/tests/test_analyze_prosody.py", selection["tests"])
        self.assertIn("scripts/tests/test_delivery_temporal_features.py", selection["tests"])

    def test_benchmark_contracts_select_the_registry_tests(self) -> None:
        for path in ("benchmarks/schema-v3.json", "benchmarks/hardware-profiles.json"):
            with self.subTest(path=path):
                selection = MODULE.python_test_selection([path])
                self.assertEqual(selection["mode"], "selected")
                self.assertIn("scripts/tests/test_benchmark_history.py", selection["tests"])
        # Published records are evidence, not tooling inputs.
        self.assertEqual(
            MODULE.python_test_selection(["benchmarks/runs/ui-generation/x.json"])["mode"], "none"
        )

    def test_unknown_input_and_shared_tooling_fall_back_to_the_full_suite(self) -> None:
        self.assertEqual(MODULE.python_test_selection(["scripts/tests/nonexistent_helper.py"])["mode"], "full")
        self.assertEqual(MODULE.python_test_selection(["scripts/lib/build_paths.sh"])["mode"], "full")

    def test_instruction_changes_do_not_select_python(self) -> None:
        for path in ("CLAUDE.md", "website/CLAUDE.md", "docs/reference/development-workflow.md"):
            with self.subTest(path=path):
                self.assertEqual(MODULE.python_test_selection([path])["mode"], "none")

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

    def test_ci_commands_mirror_the_push_workflow(self) -> None:
        joined = [" ".join(command) for command in MODULE.CI_COMMANDS]
        for expected in (
            "python3 scripts/supply_chain_contract.py --installed website",
            "./scripts/check_project_inputs.sh",
            "scripts/macos_test.sh test",
            "scripts/macos_test.sh tsan",
            "./scripts/build_foundation_targets.sh ios --incremental",
            "./scripts/build_ui_test_bundles.sh all --gate",
        ):
            self.assertIn(expected, joined)
        # The gate compile reuses the arenas the deterministic builds warmed, so it follows them.
        self.assertGreater(joined.index("./scripts/build_ui_test_bundles.sh all --gate"),
                           joined.index("./scripts/build_foundation_targets.sh ios --incremental"))
        self.assertNotIn("checkpoint", " ".join(joined))

    def test_since_adds_committed_paths_and_reaches_child_selection(self) -> None:
        # A batch verified after its commits: the tree is clean, but `--since`
        # still plans for what the unpushed commits changed.
        responses = {
            ("diff", "--name-only", "-z"): b"",
            ("diff", "--cached", "--name-only", "-z"): b"",
            ("ls-files", "--others", "--exclude-standard", "-z"): b"",
            ("diff", "--name-only", "-z", "base...HEAD"): b"Sources/iOS/A.swift\0scripts/roadmap.py\0",
        }
        environment = {k: v for k, v in MODULE.os.environ.items() if k != MODULE.SINCE_ENV}
        with mock.patch.object(MODULE, "_git", side_effect=lambda *args: responses[args]), \
                mock.patch.dict(MODULE.os.environ, environment, clear=True):
            self.assertEqual(MODULE.changed_paths(), [])
            self.assertEqual(MODULE.changed_paths("base"), ["Sources/iOS/A.swift", "scripts/roadmap.py"])
            with mock.patch.dict(MODULE.os.environ, {MODULE.SINCE_ENV: "base"}):
                self.assertEqual(MODULE.changed_paths(), ["Sources/iOS/A.swift", "scripts/roadmap.py"])
        plan = MODULE.check_plan(["Sources/iOS/A.swift", "Sources/iOS/Deleted.swift"])
        privacy = [c for c in plan["commands"] if "privacy_scan.py" in " ".join(c)]
        self.assertTrue(all("Sources/iOS/Deleted.swift" not in c for c in privacy))

    def test_dry_run_prints_the_plan_without_running(self) -> None:
        buffer = io.StringIO()
        with mock.patch.object(MODULE, "run_commands") as run, redirect_stdout(buffer):
            self.assertEqual(MODULE.main(["check", "--dry-run", "--paths", "docs/reference/cli.md"]), 0)
        run.assert_not_called()
        self.assertIn("git diff --check", buffer.getvalue())
        self.assertIn("lanes: none", buffer.getvalue())

    def test_a_clean_tree_dry_run_plans_no_lane_and_points_at_since(self) -> None:
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(MODULE, "changed_paths", return_value=[]), \
                redirect_stdout(stdout), redirect_stderr(stderr):
            self.assertEqual(MODULE.main(["check", "--dry-run"]), 0)
        self.assertIn("Changed paths: 0; lanes: none", stdout.getvalue())
        self.assertIn("--since origin/main", stderr.getvalue())

    def test_an_empty_since_range_says_so_instead_of_suggesting_since(self) -> None:
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(MODULE, "_git", return_value=b""), \
                mock.patch.object(MODULE, "changed_paths", return_value=[]), \
                mock.patch.dict(MODULE.os.environ), redirect_stdout(stdout), redirect_stderr(stderr):
            self.assertEqual(MODULE.main(["check", "--dry-run", "--since", "HEAD"]), 0)
        self.assertIn("Changed paths: 0; lanes: none", stdout.getvalue())
        self.assertIn("nothing committed since HEAD", stderr.getvalue())
        self.assertNotIn("--since origin/main", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
