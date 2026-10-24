#!/usr/bin/env python3

from __future__ import annotations

import datetime
import importlib.util
import io
import json
import re
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from shell_stubs import SANDBOX_BUILD_PATHS, ScriptSandbox

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
                                  "docs/reference/native-engineering.md", ".claude/skills/vocello-ios-validation/SKILL.md"])
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
        with mock.patch.object(MODULE, "project_generation_status", return_value={"needsRegeneration": True}):
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

        The real scripts/build_ui_test_bundles.sh runs from a sandbox
        (scripts/tests/shell_stubs.py) whose build_cache.sh records every
        `xcb_run` instead of compiling; Xcode and scripts/ui_test.sh are recorded
        stand-ins too.
        """
        expected = {
            "macos": {"VocelloMacUI": "platform=macOS,arch=arm64"},
            "ios": {"VocelloiOSUI": "generic/platform=iOS", "VocelloiOSCandidateUI": "generic/platform=iOS"},
        }
        expected["all"] = {**expected["macos"], **expected["ios"]}
        for mode, schemes in expected.items():
            for gate in ((), ("--gate",)):
                with self.subTest(mode=mode, gate=gate):
                    sandbox = ScriptSandbox(self, "scripts/build_ui_test_bundles.sh", {
                        "scripts/lib/shared.sh": None,
                        "scripts/lib/build_paths.sh": SANDBOX_BUILD_PATHS,
                        "scripts/lib/build_cache.sh": (
                            'xcb_run() { qv_record xcb_run "$@"; echo "SwiftCompile normal arm64 Fixture.swift"; }\n'
                            "QVOICE_OWNED_DEV_SETTINGS=(QVOICE_OWNED_SWIFT_OPTIMIZATION=-Onone)\n"
                            "qv_stub ensure_project_regenerated\nqv_stub ensure_spm_resolved\n"
                            "qv_stub require_ios_xcode_platform\n"
                        ),
                    })
                    sandbox.executable("scripts/ui_test.sh")
                    completed = sandbox.run_script(mode, *gate)
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                    builds = sandbox.calls_to("xcb_run")
                    # Every Xcode invocation is a compile that stops: no test action runs anything.
                    self.assertEqual({build[0] for build in builds}, {"build-for-testing"})
                    for build in builds:
                        self.assertFalse({"test", "test-without-building"} & set(build), build)
                    self.assertEqual({build[build.index("-scheme") + 1]: build[build.index("-destination") + 1]
                                      for build in builds}, schemes)
                    self.assertTrue(all("Simulator" not in argument for build in builds for argument in build))
                    names = set(sandbox.names())
                    self.assertFalse({"scripts/ui_test.sh", "xcodebuild", "xcrun", "devicectl"} & names, names)

    def test_lineage_path_changes_are_named_unless_the_identity_changes_too(self) -> None:
        """A harness change on a kind's path list is only separated by a reviewed version bump."""
        driver = "Tests/VocelloMacUITests/VocelloMacBenchmarkUITests.swift"
        self.assertEqual(MODULE.check_plan([driver, "README.md"])["lineageReviewPaths"], [driver])
        self.assertEqual(MODULE.check_plan([driver, MODULE.LINEAGE_IDENTITY])["lineageReviewPaths"], [])
        self.assertEqual(MODULE.check_plan(["Sources/Views/SidebarView.swift"])["lineageReviewPaths"], [])

    def test_every_non_swift_swift_lane_input_schedules_a_macos_test(self) -> None:
        """W-06: a non-Swift input routed to the swift lane once scheduled no macOS test at all."""
        classify = MODULE._load("scripts/ci/classify_changes.py")
        candidates = {*classify.BUILD_CONFIGS, *classify.SWIFT_PARITY_FIXTURES, *classify.MACOS_LANE_SCRIPTS,
                      *classify.python_import_closure(classify.MACOS_LANE_SCRIPTS), *classify.WORKFLOW_INPUTS,
                      "project.yml", "QwenVoice.xcodeproj/project.pbxproj", "Sources/Resources/qwenvoice_contract.json",
                      ".github/actions/native-toolchain/action.yml"}
        candidates.update(path.relative_to(ROOT).as_posix() for top in ("config", "scripts", "Tests")
                          for path in (ROOT / top).rglob("*") if path.is_file() and "__pycache__" not in path.parts)
        inputs = sorted(path for path in candidates if not path.endswith(".swift") and classify.classify([path])["swift"])
        # The classifier's own tables reach every kind: records, fixtures, lane scripts, build configs.
        for expected in ("config/test-quarantine.json", "scripts/tests/fixtures/language_normalization.json",
                         "scripts/lib/xctest_summary.py", "scripts/lib/build_paths.sh", "config/toolchain.json",
                         "scripts/macos_test.sh", "scripts/build.sh"):
            self.assertIn(expected, inputs)
        with mock.patch.object(MODULE, "project_generation_status", return_value=None), \
                mock.patch.object(MODULE, "lint_commands", return_value=[]):
            for path in inputs:
                with self.subTest(path=path):
                    native = [c for c in commands(MODULE.check_plan([path])) if c.startswith("scripts/macos_test.sh ")]
                    self.assertTrue(native, path)
                    self.assertFalse(any(" tsan" in c for c in native), native)

    def test_a_data_input_runs_the_test_classes_that_read_it(self) -> None:
        def plan(*paths: str) -> list[str]:
            with mock.patch.object(MODULE, "project_generation_status", return_value=None):
                return [c for c in commands(MODULE.check_plan(list(paths))) if c.startswith("scripts/macos_test.sh ")]

        self.assertEqual(plan("config/ios-memory-budget-policy.json"),
                         ["scripts/macos_test.sh core-test --only StartupReliabilityDiagnosticsV2Tests"])
        self.assertEqual(plan("scripts/tests/fixtures/language_normalization.json"),
                         ["scripts/macos_test.sh core-test --only WordErrorRateTests"])
        # No focused runner: a reader without a test class (the quarantine helper) or
        # the owned runtime package's tests; lane scripts and build configs run it all.
        for path in ("config/test-quarantine.json", "config/audio-qc-stage0-observations.json",
                     "scripts/macos_test.sh", "scripts/lib/xctest_summary.py", "config/toolchain.json"):
            with self.subTest(path=path):
                self.assertEqual(plan(path), ["scripts/macos_test.sh test"])
        # Beside a changed test class, the data readers join one focused run.
        test_file = "Tests/VocelloCoreTests/WordErrorRateTests.swift"
        mixed = plan(test_file, "config/ios-memory-budget-policy.json")
        self.assertEqual(mixed, ["scripts/macos_test.sh core-test --only StartupReliabilityDiagnosticsV2Tests,WordErrorRateTests"])

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
    def test_agent_configuration_selects_agent_hook_tests_even_when_added_or_deleted(self) -> None:
        for path in (".claude/settings.json", ".claude/skills/vocello-ios-validation/SKILL.md",
                     ".claude/agents/vocello-xcresult-triage.md", ".claude/rules/native.md",
                     "docs/reference/tooling-and-evidence.md", ".claude/removed.yaml",
                     ".codex/hooks.json", ".agents/skills/ios-lane/SKILL.md"):
            with self.subTest(path=path):
                selection = MODULE.python_test_selection([path])
                self.assertEqual(selection["mode"], "selected")
                self.assertEqual(selection["tests"], ["scripts/tests/test_agent_hooks.py"])

    def test_real_tooling_dependency_selection_reaches_consumers(self) -> None:
        selection = MODULE.python_test_selection(["scripts/analyze_prosody.py"])
        self.assertEqual(selection["mode"], "selected")
        self.assertIn("scripts/tests/test_analyze_prosody.py", selection["tests"])
        self.assertIn("scripts/tests/test_prosody_quality_gate.py", selection["tests"])

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
        for path in ("scripts/lib/build_paths.sh", "scripts/tests/conftest.py", "pytest.ini"):
            with self.subTest(path=path):
                self.assertEqual(MODULE.python_test_selection([path])["mode"], "full")

    def assert_selects(self, path: str, *, at_most: int, includes: tuple[str, ...]) -> list[str]:
        selection = MODULE.python_test_selection([path])
        self.assertEqual(selection["mode"], "selected", selection)
        tests = selection["tests"]
        self.assertLessEqual(len(tests), at_most, tests)
        for module in includes:
            self.assertIn(f"scripts/tests/{module}", tests)
        return tests

    def test_ordinary_inputs_select_the_tests_that_read_them(self) -> None:
        """W-02: generic stems as search words once selected 118-120 of 126 modules for each of these."""
        cases = {
            "config/roadmap.json": (10, ("test_roadmap.py",)),
            "scripts/roadmap.py": (10, ("test_roadmap.py",)),
            "scripts/macos_test.sh": (12, ("test_macos_test_evidence.py", "test_profile_capture_contract.py",
                                           "test_macos_gate.py")),
            "scripts/ui_test.sh": (20, ("test_ui_failure_finalization.py", "test_required_step_ledger.py",
                                        "test_check_ios_smoke_acceptance.py", "test_long_form_project_summary.py")),
            "project.yml": (20, ("test_project_generation.py", "test_lineage_identity.py")),
        }
        for path, (at_most, includes) in cases.items():
            with self.subTest(path=path):
                self.assert_selects(path, at_most=at_most, includes=includes)

    def test_a_qc_module_selects_the_qc_tests_that_import_it(self) -> None:
        importing = {path.relative_to(ROOT).as_posix() for path in ROOT.glob("scripts/tests/test_*.py")
                     if re.search(r"^\s*from qc[ .]", path.read_text(encoding="utf-8"), re.MULTILINE)}
        self.assertIn("scripts/tests/test_qc_evidence.py", importing)
        tests = self.assert_selects("scripts/qc/evidence.py", at_most=40, includes=("test_qc_evidence.py",))
        self.assertLessEqual(importing, set(tests))
        self.assertNotIn("scripts/tests/test_roadmap.py", tests)

    def test_routing_changes_run_both_routing_suites_and_the_selector_consumers(self) -> None:
        for path in MODULE.ROUTING_SOURCES:
            with self.subTest(path=path):
                tests = self.assert_selects(path, at_most=10, includes=("test_workflow_diagnostics.py",))
                self.assertLessEqual(set(MODULE.ROUTING_TESTS), set(tests))

    def test_a_changed_test_module_selects_itself_not_the_tests_that_name_it(self) -> None:
        self.assertEqual(MODULE.python_test_selection(["scripts/tests/test_roadmap.py"])["tests"],
                         ["scripts/tests/test_roadmap.py"])

    def test_name_matching_is_one_step_deep_unless_nothing_names_the_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative, text in {
                "config/data.json": "{}",
                "config/indirect.json": "{}",
                "config/orphan.json": "{}",
                "scripts/reader.py": 'PATHS = ("config/data.json", "config/indirect.json")\n',
                "scripts/tests/test_reader.py": 'SCRIPT = "scripts/reader.py"\n',
                "scripts/tests/test_data.py": 'DATA = ROOT / "config" / "data.json"\n',
                "scripts/tests/test_other.py": 'NAMES = ("my-data.json", "data.jsonl", "data_json")\n',
            }.items():
                (root / relative).parent.mkdir(parents=True, exist_ok=True)
                (root / relative).write_text(text, encoding="utf-8")

            def tests(path: str) -> list[str]:
                return MODULE.python_test_selection([path], root=root)["tests"]

            # A test that reads the input runs; the tests of another reader do not.
            self.assertEqual(tests("config/data.json"), ["scripts/tests/test_data.py"])
            # Only when no test names it does the script that reads it stand in.
            self.assertEqual(tests("config/indirect.json"), ["scripts/tests/test_reader.py"])
            self.assertEqual(MODULE.python_test_selection(["config/orphan.json"], root=root)["mode"], "full")

    def test_instruction_changes_do_not_select_python(self) -> None:
        for path in ("CLAUDE.md", "website/CLAUDE.md", "docs/reference/development-workflow.md"):
            with self.subTest(path=path):
                self.assertEqual(MODULE.python_test_selection([path])["mode"], "none")

    def test_no_tooling_input_selects_nothing(self) -> None:
        selection = MODULE.python_test_selection(["Sources/iOS/A.swift"])
        self.assertEqual(selection["mode"], "none")
        self.assertEqual(MODULE.python_test_commands(selection), [])


class PrimaryPlanStatusTests(unittest.TestCase):
    ROADMAP = {
        "primaryPlan": "rel",
        "focusLock": {"plan": "rel", "decided": "2026-10-12", "decision": "release first", "maxInFlight": 2},
        "items": [
            {"id": "R-1", "plan": "rel", "status": "planned", "due": "2026-10-20"},
            {"id": "R-2", "plan": "rel", "status": "planned", "due": "2026-10-16"},
            {"id": "R-3", "plan": "rel", "status": "planned", "due": "2026-10-10", "blockedBy": ["R-1"]},
            {"id": "R-4", "plan": "rel", "status": "in-flight"},
            {"id": "R-5", "plan": "rel", "status": "planned", "blockedBy": ["OLD-1"]},
            {"id": "X-1", "plan": "other", "status": "parked"},
        ],
    }

    TODAY = datetime.date(2026, 10, 12)

    def test_status_lists_unblocked_work_by_due_date_and_flags_overdue_items(self) -> None:
        lines = MODULE.primary_plan_lines(self.ROADMAP, {"OLD-1"}, self.TODAY)
        self.assertEqual(lines[0], "primaryPlan: rel — 5 open, 4 unblocked")
        self.assertEqual(lines[1], "focusLock: since 2026-10-12; live work only in rel, at most 2 in flight")
        self.assertEqual(lines[2], "next: R-4 (in-flight), R-2 (planned, due 2026-10-16), "
                                   "R-1 (planned, due 2026-10-20), R-5 (planned)")
        self.assertTrue(lines[3].startswith("overdue: R-3 "))

    def test_status_without_a_focus_lock_or_due_dates_stays_short(self) -> None:
        roadmap = {"primaryPlan": "rel", "items": [{"id": "R-1", "plan": "rel", "status": "planned"}]}
        self.assertEqual(MODULE.primary_plan_lines(roadmap, set(), self.TODAY),
                         ["primaryPlan: rel — 1 open, 1 unblocked", "next: R-1 (planned)"])

    def test_due_dates_follow_the_validator_parsing_and_never_crash_status(self) -> None:
        roadmap = {"primaryPlan": "rel", "items": [
            {"id": "R-1", "plan": "rel", "status": "planned", "due": 20261010},
            {"id": "R-2", "plan": "rel", "status": "planned", "due": "next week"},
        ]}
        lines = MODULE.primary_plan_lines(roadmap, set(), self.TODAY)
        self.assertEqual(lines[1], "next: R-1 (planned, due 2026-10-10), R-2 (planned)")
        self.assertTrue(lines[2].startswith("overdue: R-1 "))

    def test_an_unreadable_roadmap_reports_instead_of_raising(self) -> None:
        roadmap = mock.Mock(RoadmapError=RuntimeError)
        roadmap.load.side_effect = ValueError("Expecting value: line 1 column 1 (char 0)")
        output = io.StringIO()
        with mock.patch.object(MODULE, "_load", return_value=roadmap), \
                mock.patch.object(MODULE, "changed_paths", return_value=[]), \
                mock.patch.object(MODULE, "lanes_for", return_value={}), redirect_stdout(output):
            MODULE.print_status()
        self.assertIn("primaryPlan: unreadable config/roadmap.json", output.getvalue())

    def test_a_tag_checkout_reports_a_detached_head(self) -> None:
        # The release lane runs the suite on a tag checkout, where HEAD names no branch.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            git = ["git", "-C", directory, "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
            subprocess.run([*git, "init", "--quiet"], check=True)
            subprocess.run([*git, "commit", "--quiet", "--allow-empty", "--no-gpg-sign", "-m", "c"], check=True)
            subprocess.run([*git, "checkout", "--quiet", "--detach"], check=True)
            output = io.StringIO()
            with mock.patch.object(MODULE, "ROOT", root), \
                    mock.patch.object(MODULE, "changed_paths", return_value=[]), \
                    mock.patch.object(MODULE, "lanes_for", return_value={}), redirect_stdout(output):
                MODULE.print_status()
        self.assertIn("branch: detached HEAD\n", output.getvalue())


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

    def test_pytest_uses_running_interpreter_and_missing_dependencies_stop_before_execution(self) -> None:
        import sys
        self.assertEqual(MODULE.PYTEST[0], sys.executable)
        diagnostics = mock.Mock()
        diagnostics.python_dependency_problems.return_value = ["missing pytest"]
        with mock.patch.object(MODULE, "_load", return_value=diagnostics), \
                mock.patch.object(MODULE.subprocess, "run") as run:
            with self.assertRaisesRegex(MODULE.WorkflowError, "VOCELLO_PYTHON"):
                MODULE.run_commands([MODULE.PYTEST])
            run.assert_not_called()

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
        # Every lint gate the contracts job runs, so `dev.sh ci` fails where push CI would.
        workflow = (MODULE.ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        gates = re.findall(r"run: (python3 scripts/lint_baseline\.py \w+)$", workflow, re.MULTILINE)
        self.assertEqual(sorted(gates), ["python3 scripts/lint_baseline.py " + tool
                                         for tool in ("pyright", "ruff", "shellcheck", "swiftlint")])
        for gate in gates:
            self.assertIn(gate, joined)
        # The gate compile reuses the arenas the deterministic builds warmed, so it follows them.
        self.assertGreater(joined.index("./scripts/build_ui_test_bundles.sh all --gate"),
                           joined.index("./scripts/build_foundation_targets.sh ios --incremental"))
        self.assertNotIn("checkpoint", " ".join(joined))

    def test_paths_scope_the_gate_the_python_selection_and_the_whitespace_check(self) -> None:
        # `check --paths` plans for the given paths only: the contract gate and the Python
        # selection it runs read $QVOICE_CHANGED_PATHS, and `git diff --check` takes the paths.
        environment = {k: v for k, v in MODULE.os.environ.items() if k not in (MODULE.SINCE_ENV, MODULE.PATHS_ENV)}
        with mock.patch.dict(MODULE.os.environ, environment, clear=True), \
                mock.patch.object(MODULE, "run_commands") as run, redirect_stderr(io.StringIO()):
            self.assertEqual(MODULE.main(["check", "--paths", "README.md", "docs/reference/cli.md"]), 0)
            self.assertEqual(MODULE.os.environ[MODULE.PATHS_ENV], "README.md\ndocs/reference/cli.md")
            self.assertEqual(MODULE.changed_paths(), ["README.md", "docs/reference/cli.md"])
        [commands] = run.call_args.args
        self.assertEqual(commands[0], ["git", "diff", "--check", "--", "README.md", "docs/reference/cli.md"])
        self.assertIn(["./scripts/check_project_inputs.sh", "--local"], commands)
        # Without --paths the whole tree is checked, as before.
        self.assertEqual(MODULE.lint_commands(["README.md"])[0], ["git", "diff", "--check"])
        # A deleted or mistyped path stays in the pathspec: `git diff --check --` alone checks everything.
        self.assertEqual(MODULE.lint_commands(["gone/deleted.md"], scoped=True)[0],
                         ["git", "diff", "--check", "--", "gone/deleted.md"])
        # ./ and absolute spellings inside the checkout plan as repository-relative paths.
        self.assertEqual(MODULE.normalized_path("./README.md"), "README.md")
        self.assertEqual(MODULE.normalized_path(str(MODULE.ROOT / "docs/reference/cli.md")), "docs/reference/cli.md")

    def test_since_adds_committed_paths_and_reaches_child_selection(self) -> None:
        # A batch verified after its commits: the tree is clean, but `--since`
        # still plans for what the unpushed commits changed.
        responses = {
            ("diff", "--name-only", "-z"): b"",
            ("diff", "--cached", "--name-only", "-z"): b"",
            ("ls-files", "--others", "--exclude-standard", "-z"): b"",
            ("diff", "--name-only", "-z", "base...HEAD"): b"Sources/iOS/A.swift\0scripts/roadmap.py\0",
        }
        environment = {k: v for k, v in MODULE.os.environ.items() if k not in (MODULE.SINCE_ENV, MODULE.PATHS_ENV)}
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
        with mock.patch.object(MODULE, "run_commands") as run, redirect_stdout(buffer), \
                mock.patch.dict(MODULE.os.environ):
            self.assertEqual(MODULE.main(["check", "--dry-run", "--paths", "docs/reference/cli.md"]), 0)
        run.assert_not_called()
        self.assertIn("git diff --check", buffer.getvalue())
        self.assertIn("lanes: none", buffer.getvalue())

    def test_json_dry_run_is_the_exact_executable_plan(self) -> None:
        buffer = io.StringIO()
        expected = MODULE.check_plan(["docs/reference/cli.md"], scoped=True)
        with mock.patch.object(MODULE, "run_commands") as run, redirect_stdout(buffer), \
                mock.patch.dict(MODULE.os.environ):
            self.assertEqual(MODULE.main(["check", "--dry-run", "--json", "--paths", "docs/reference/cli.md"]), 0)
        run.assert_not_called()
        self.assertEqual(json.loads(buffer.getvalue()), expected)

    def test_json_requires_dry_run(self) -> None:
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            MODULE.main(["check", "--json"])
        self.assertEqual(error.exception.code, 2)

    def test_test_repeat_passes_the_count_to_the_focused_core_test(self) -> None:
        with mock.patch.object(MODULE, "run_commands") as run:
            self.assertEqual(MODULE.main(["test", "--only", "ATests/testOne", "--repeat", "25"]), 0)
        run.assert_called_once_with(
            [["scripts/macos_test.sh", "core-test", "--only", "ATests/testOne", "--repeat", "25"]])
        with mock.patch.object(MODULE, "run_commands") as run:
            self.assertEqual(MODULE.main(["test", "--only", "ATests"]), 0)
        run.assert_called_once_with([["scripts/macos_test.sh", "core-test", "--only", "ATests"]])

    def test_test_repeat_without_a_focused_selection_is_refused(self) -> None:
        with mock.patch.object(MODULE, "run_commands") as run, redirect_stderr(io.StringIO()), \
                self.assertRaises(SystemExit) as error:
            MODULE.main(["test", "--repeat", "5"])
        self.assertEqual(error.exception.code, 2)
        run.assert_not_called()

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
