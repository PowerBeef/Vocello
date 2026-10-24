"""Deterministic refusal/collection tests; never launch Xcode or a device."""
from __future__ import annotations

import base64
import json
from pathlib import Path
import plistlib
import sys
import tempfile
import unittest
import unittest.mock
import xml.etree.ElementTree as ET
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import ios_candidate_acceptance as candidate


class CandidateAcceptanceTests(unittest.TestCase):
    def identity(self):
        return {"marketingVersion": "3.0.0", "buildNumber": "24",
                "bundleIdentifier": candidate.BUNDLE_ID,
                "evidenceClass": "preinstalled-candidate-black-box"}

    def app_inventory(self):
        return {"result": {"apps": [{"bundleIdentifier": candidate.BUNDLE_ID,
                  "version": "3.0.0", "bundleVersion": "24", "builtByDeveloper": False,
                  "privatePath": "/private/personal/app"}]}}

    def configuration(self):
        return {candidate.TARGET: {"IsUITestBundle": True,
                    "TestBundlePath": "__TESTROOT__/runner/PlugIns/test.xctest",
                    "TestHostPath": "__TESTROOT__/runner",
                    "DependentProductPaths": [f"__TESTROOT__/{candidate.TARGET}-Runner.app"],
                    "UITargetAppEnvironmentVariables": {"QWENVOICE_DEBUG": "1"},
                    "EnvironmentVariables": {"QVOICE_IOS_SMOKE_RUN_ID": "wrong"},
                    "RetryTestsOnFailure": True},
                "__xctestrun_metadata__": {"FormatVersion": 1}}

    def test_exact_candidate_origin_identity_and_redaction(self):
        value = candidate.installed_identity(self.app_inventory(), self.identity())
        self.assertEqual(value["buildNumber"], "24")
        self.assertNotIn("private", json.dumps(value))

    def test_development_unknown_origin_or_wrong_identity_refused(self):
        for key, value in [("builtByDeveloper", True), ("builtByDeveloper", None),
                           ("version", "2.4.0"), ("bundleVersion", "23"),
                           ("bundleVersion", 24), ("bundleIdentifier", "other")]:
            with self.subTest(key=key, value=value):
                apps = self.app_inventory()
                apps["result"]["apps"][0][key] = value
                with self.assertRaises(ValueError):
                    candidate.installed_identity(apps, self.identity())

    def test_origin_is_read_from_the_field_coredevice_reports(self):
        # The row `devicectl device info apps` (Xcode 27.1) printed for the development build that
        # was still installed on 2026-10-24, its private path left out.
        row = {"appClip": False, "builtByDeveloper": True, "bundleIdentifier": candidate.BUNDLE_ID,
               "bundleVersion": "24", "containerAccessible": True, "defaultApp": False, "hidden": False,
               "internalApp": False, "name": "Vocello", "removable": True, "version": "3.0.0"}
        with self.assertRaisesRegex(ValueError, "development installation"):
            candidate.installed_identity({"result": {"apps": [row]}}, self.identity())
        self.assertEqual(candidate.installed_identity({"result": {"apps": [{**row, "builtByDeveloper": False}]}},
                                                      self.identity())["builtByDeveloper"], False)
        # A field CoreDevice does not report proves nothing: the origin stays unknown.
        legacy = {key: value for key, value in row.items() if key != "builtByDeveloper"}
        with self.assertRaisesRegex(ValueError, "unknown application origin"):
            candidate.installed_identity({"result": {"apps": [{**legacy, "isBuiltByDeveloper": False}]}},
                                         self.identity())

    def test_absent_or_duplicate_candidate_fails(self):
        for apps in ({}, {"result": {"apps": []}},
                     {"result": {"apps": self.app_inventory()["result"]["apps"] * 2}}):
            with self.assertRaises(ValueError):
                candidate.installed_identity(apps, self.identity())

    def test_runner_uses_destination_artifacts_without_diagnostics_or_retry(self):
        value = candidate.runner_configuration(self.configuration(),
                    {"CFBundleIdentifier": candidate.RUNNER_ID}, self.identity())
        target = value[candidate.TARGET]
        self.assertIs(target["UseDestinationArtifacts"], True)
        self.assertEqual(target["UITargetAppBundleIdentifier"], candidate.BUNDLE_ID)
        for field in ("TestHostPath", "TestBundlePath", "UITargetAppPath", "DependentProductPaths", "RetryTestsOnFailure"):
            self.assertNotIn(field, target)
        self.assertEqual(target["UITargetAppEnvironmentVariables"], {})
        self.assertEqual(target["UITargetAppCommandLineArguments"], [])
        self.assertEqual(json.loads(base64.b64decode(target["EnvironmentVariables"]["VOCELLO_CANDIDATE_IDENTITY"])), self.identity())
        self.assertEqual(target["OnlyTestIdentifiers"], [candidate.TEST.split("/", 1)[1]])
        self.assertEqual(plistlib.loads(plistlib.dumps(value)), value)

    def test_scenarios_select_only_their_journeys(self):
        rows = {name: tests for name, tests in candidate.SCENARIOS.items() if name != "all"}
        self.assertEqual(candidate.SCENARIOS["all"], [test for tests in rows.values() for test in tests])
        self.assertEqual(len(set(candidate.SCENARIOS["all"])), len(candidate.SCENARIOS["all"]))
        for name, tests in candidate.SCENARIOS.items():
            value = candidate.runner_configuration(self.configuration(),
                        {"CFBundleIdentifier": candidate.RUNNER_ID}, self.identity(), name)
            self.assertEqual(value[candidate.TARGET]["OnlyTestIdentifiers"],
                             [test.split("/", 1)[1] for test in tests])
            self.assertTrue(all(test.startswith(candidate.TARGET + "/") for test in tests))

    def test_target_app_dependency_or_wrong_runner_cannot_be_installed(self):
        for changes in ({"UITargetAppPath": "__TESTROOT__/Vocello.app"},
                        {"UITargetAppBundleIdentifier": candidate.BUNDLE_ID},
                        {"DependentProductPaths": ["__TESTROOT__/Vocello.app"]},
                        {"IsUITestBundle": False}):
            payload = self.configuration()
            payload[candidate.TARGET].update(changes)
            with self.assertRaises(ValueError):
                candidate.runner_configuration(payload, {"CFBundleIdentifier": candidate.RUNNER_ID}, self.identity())
        with self.assertRaises(ValueError):
            candidate.runner_configuration(self.configuration(), {"CFBundleIdentifier": candidate.BUNDLE_ID}, self.identity())
        payload = self.configuration()
        payload["VocelloiOSUITests"] = {}
        with self.assertRaises(ValueError):
            candidate.runner_configuration(payload, {"CFBundleIdentifier": candidate.RUNNER_ID}, self.identity())

    def test_command_bound_release_validation_is_not_optional(self):
        with patch.object(candidate.release_evidence, "validate", side_effect=ValueError("untrusted")) as validate:
            with self.assertRaises(ValueError):
                candidate.candidate_identity(Path("untrusted"))
            validate.assert_called_once()

    def test_source_mismatch_or_dirty_tree_refused(self):
        evidence = {"release": {"platform": "ios", "commitSHA": "a" * 40}}
        not_descendant = unittest.mock.Mock(returncode=1)
        for outputs, ancestor in ((["a" * 40, " M tracked.swift"], None),
                                  (["b" * 40, ""], not_descendant),
                                  (["b" * 40, "", "Tests/x.swift\0Sources/iOS/y.swift\0"], unittest.mock.Mock(returncode=0))):
            with patch.object(candidate.release_evidence, "validate", return_value=evidence), \
                 patch.object(candidate.subprocess, "check_output", side_effect=outputs), \
                 patch.object(candidate.subprocess, "run", return_value=ancestor):
                with self.assertRaises(ValueError):
                    candidate.candidate_identity(Path("fixture"))

    def test_runner_may_descend_from_the_candidate_by_tests_only(self):
        ancestor = unittest.mock.Mock(returncode=0)
        self.assertEqual(candidate.runner_relation("a" * 40, "a" * 40, ROOT), "exact")
        changed = "Tests/VocelloiOSUITests/x.swift\0scripts/y.py\0config/roadmap.json\0docs/a b.md\0"
        with patch.object(candidate.subprocess, "run", return_value=ancestor) as run, \
             patch.object(candidate.subprocess, "check_output", return_value=changed) as diff:
            self.assertEqual(candidate.runner_relation("a" * 40, "b" * 40, ROOT), "test-only-descendant")
        self.assertEqual(run.call_args.args[0], ["git", "merge-base", "--is-ancestor", "a" * 40, "b" * 40])
        self.assertEqual(diff.call_args.args[0],
                         ["git", "diff", "--no-renames", "--name-only", "-z", "a" * 40, "b" * 40])
        for product in ("Sources/iOS/RootView.swift", "Packages/VocelloQwen3Core/Package.swift", "project.yml",
                        "QwenVoice.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved",
                        "Sources/iOS/Caf\u00e9 View.swift"):
            with self.subTest(product=product), \
                 patch.object(candidate.subprocess, "run", return_value=ancestor), \
                 patch.object(candidate.subprocess, "check_output", return_value=changed + product + "\0"), \
                 self.assertRaises(ValueError):
                candidate.runner_relation("a" * 40, "b" * 40, ROOT)
        with patch.object(candidate.subprocess, "run", return_value=unittest.mock.Mock(returncode=1)), \
             self.assertRaises(ValueError):
            candidate.runner_relation("a" * 40, "b" * 40, ROOT)
        with patch.object(candidate.subprocess, "run", return_value=ancestor), \
             patch.object(candidate.subprocess, "check_output",
                          side_effect=candidate.subprocess.CalledProcessError(128, "git")), \
             self.assertRaises(candidate.subprocess.SubprocessError):
            candidate.runner_relation("a" * 40, "b" * 40, ROOT)

    def test_journey_names_match_the_swift_sources(self):
        sources = {path.stem: path.read_text() for path in (ROOT / "Tests/VocelloiOSUITests").glob("VocelloiOSCandidate*.swift")}
        for test in candidate.SCENARIOS["all"]:
            suite, method = test.split("/")[1:]
            with self.subTest(test=test):
                self.assertIn(f"func {method}()", sources[suite])

    def test_post_test_replacement_is_rejected(self):
        candidate.installed_identity(self.app_inventory(), self.identity())
        after = self.app_inventory()
        after["result"]["apps"][0]["builtByDeveloper"] = True
        with self.assertRaises(ValueError):
            candidate.installed_identity(after, self.identity())

    def test_result_requires_one_pass_and_exact_collected_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            attachments = Path(temp)
            suite, test = candidate.TEST.split("/")[1:]
            summary = {"tests": [{"suite": suite, "test": test, "verdict": "passed"}]}
            with self.assertRaises(ValueError):
                candidate.validate_results(summary, attachments, self.identity())
            (attachments / "identity.json").write_text(json.dumps(self.identity()))
            self.assertEqual(candidate.validate_results(summary, attachments, self.identity())["status"], "passed")
            for tests in ([], summary["tests"] * 2, [{"suite": suite, "test": "other", "verdict": "passed"}],
                          [{"suite": suite, "test": test, "verdict": "failed"}]):
                with self.assertRaises(ValueError):
                    candidate.validate_results({"tests": tests}, attachments, self.identity())
            journeys = [dict(zip(("suite", "test"), row.split("/")[1:]), verdict="passed")
                        for row in candidate.SCENARIOS["all"]]
            result = candidate.validate_results({"tests": journeys}, attachments, self.identity(), "all")
            self.assertEqual(result["testCount"], len(candidate.SCENARIOS["all"]))
            with self.assertRaises(ValueError):
                candidate.validate_results({"tests": journeys[1:]}, attachments, self.identity(), "all")
            with self.assertRaises(ValueError):
                candidate.validate_results({"tests": journeys}, attachments, self.identity(), "modes")
            mismatched = self.identity() | {"buildNumber": "25"}
            with self.assertRaises(ValueError):
                candidate.validate_results(summary, attachments, mismatched)

    def test_crash_delta_keeps_unknown_reports_non_green(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            before, after = root / "before", root / "after"
            before.mkdir()
            (after / "raw").mkdir(parents=True)
            (before / "hashes.json").write_text("[]")
            report = after / "raw/report.ips"
            report.write_text('{"unknown": "system report"}')
            (after / "hashes.json").write_text(json.dumps([candidate.digest(report)]))
            result = candidate.crash_delta(before, after, root / "delta.json")
            self.assertEqual(result["status"], "requires-review")
            self.assertEqual(result["newReportCount"], 1)
            self.assertNotIn(str(root), json.dumps(result))
            report.write_text("corrupted after collection")
            with self.assertRaises(ValueError):
                candidate.crash_delta(before, after, root / "another.json")

    def test_generated_scheme_builds_only_runner(self):
        scheme = ET.parse(ROOT / "QwenVoice.xcodeproj/xcshareddata/xcschemes/VocelloiOSCandidateUI.xcscheme")
        references = scheme.findall(".//BuildActionEntries//BuildableReference")
        self.assertEqual([r.attrib["BlueprintName"] for r in references], [candidate.TARGET])
        self.assertEqual(scheme.find("TestAction").attrib["buildConfiguration"], "Release")


if __name__ == "__main__":
    unittest.main()
