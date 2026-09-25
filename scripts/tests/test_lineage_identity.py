"""The per-kind lineage identity behind new benchmark comparison keys (audit #22, #23, #34)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from lib import lineage_identity as lineage  # noqa: E402


PROJECT = """\
name: Fixture
options:
  deploymentTarget:
    macOS: "26.0"
settings:
  base:
    SWIFT_TREAT_WARNINGS_AS_ERRORS: YES
    MARKETING_VERSION: "3.0.0"
    CURRENT_PROJECT_VERSION: "24"
packages:
  MLXSwift:
    exactVersion: "0.31.6"
schemes:
  VocelloMacUI:
    build:
      targets:
        App: all
        AppUITests: [test]
    test:
      # The observer-effect switch.
      preferredScreenCaptureFormat: screenshots
      targets:
      - AppUITests
  Other:
    build:
      targets:
        Unrelated: all
targets:
  App:
    type: application
    sources:
      - path: Sources
    settings:
      base:
        SWIFT_VERSION: "6"
    dependencies:
      - target: Core
      - package: MLXSwift
        product: MLX
  AppUITests:
    type: bundle.ui-testing
    dependencies:
      - target: App
  Core:
    type: framework.static
    settings:
      base:
        OTHER_SWIFT_FLAGS: "$(inherited)"
  Unrelated:
    type: tool
    settings:
      base:
        SWIFT_VERSION: "6"
"""


def subset_hash(text: str) -> str:
    return lineage.project_subset_hash(text, "VocelloMacUI", ())


class LineagePathTests(unittest.TestCase):
    def test_every_listed_file_exists_and_every_kind_is_fully_described(self) -> None:
        # A rename must not silently drop a file from a kind's harness provenance.
        for key, paths in lineage.LINEAGE_PATHS.items():
            for path in paths:
                self.assertTrue((ROOT / path).is_file(), f"{key}: {path} is missing")
        self.assertEqual(set(lineage.LINEAGE_MEASUREMENT_VERSIONS), set(lineage.LINEAGE_PATHS))
        self.assertEqual(set(lineage.LINEAGE_PROJECT_SCOPES), set(lineage.LINEAGE_PATHS))
        self.assertTrue(all(version >= 1 for version in lineage.LINEAGE_MEASUREMENT_VERSIONS.values()))

    def test_ui_lists_name_their_base_test_case_and_never_the_ceilings(self) -> None:
        mac_perf = lineage.LINEAGE_PATHS[("ui-perf", "macos")]
        ios_perf = lineage.LINEAGE_PATHS[("ui-perf", "ios")]
        mac_ui = lineage.LINEAGE_PATHS[("ui-generation", "macos")]
        self.assertIn("Tests/VocelloMacUITests/VocelloMacUITestCase.swift", mac_perf)
        self.assertIn("Tests/VocelloiOSUITests/VocelloiOSUITestCase.swift", ios_perf)
        self.assertIn("Tests/VocelloMacUITests/VocelloMacUITestCase.swift", mac_ui)
        self.assertIn("scripts/benchmark_memory.py", mac_ui)
        for paths in lineage.LINEAGE_PATHS.values():
            self.assertNotIn("config/ui-perf-thresholds.json", paths)
            self.assertNotIn("config/ui-perf-thresholds-ios.json", paths)

    def test_content_hash_matches_the_legacy_construction(self) -> None:
        import benchmark_history

        paths = list(lineage.LINEAGE_PATHS[("ui-perf", "macos")])
        self.assertEqual(
            lineage.content_hash(paths, benchmark_history.read_repository_file),
            benchmark_history.hash_existing_files(ROOT / path for path in paths),
        )
        self.assertEqual(lineage.content_hash(["missing/file"], lambda _: None), lineage.NOT_APPLICABLE)

    def test_lineage_inputs_stamp_the_contract_and_measurement_versions(self) -> None:
        files = {"project.yml": PROJECT.encode("utf-8")}
        stamped = lineage.lineage_inputs("ui-generation", "macos", files.get)
        self.assertEqual(stamped["lineageContractVersion"], lineage.LINEAGE_CONTRACT_VERSION)
        self.assertEqual(
            stamped["lineageMeasurementVersion"],
            lineage.LINEAGE_MEASUREMENT_VERSIONS[("ui-generation", "macos")],
        )
        self.assertEqual(stamped["lineageProjectHash"], subset_hash(PROJECT))
        prosody = lineage.lineage_inputs("prosody-calibration", "macos", files.get)
        self.assertEqual(prosody["lineageProjectHash"], lineage.NOT_APPLICABLE)
        self.assertIsNone(lineage.lineage_inputs("prosody-calibration", "ios", files.get))


class ProjectSubsetTests(unittest.TestCase):
    def test_the_scheme_targets_close_over_target_dependencies(self) -> None:
        entries = lineage.yaml_lines(PROJECT)
        self.assertEqual(lineage.project_targets(entries, "VocelloMacUI", ()), ["App", "AppUITests", "Core"])
        self.assertEqual(lineage.project_targets(entries, None, ("Unrelated",)), ["Unrelated"])

    def test_labels_membership_links_pins_and_other_targets_never_move_the_hash(self) -> None:
        baseline = subset_hash(PROJECT)
        harmless = {
            "a comment": ("      # The observer-effect switch.\n", "      # Reworded.\n"),
            "the version labels": ('MARKETING_VERSION: "3.0.0"', 'MARKETING_VERSION: "3.1.0"'),
            "the build number": ('CURRENT_PROJECT_VERSION: "24"', 'CURRENT_PROJECT_VERSION: "25"'),
            "a package pin": ('exactVersion: "0.31.6"', 'exactVersion: "0.32.0"'),
            "file membership": ("      - path: Sources\n", "      - path: Sources\n      - path: Extra\n"),
            "a product link": ("        product: MLX\n", "        product: MLXRandom\n"),
            "an unbuilt target": ('  Unrelated:\n    type: tool\n    settings:\n      base:\n        SWIFT_VERSION: "6"',
                                  '  Unrelated:\n    type: tool\n    settings:\n      base:\n        SWIFT_VERSION: "5"'),
        }
        for name, (old, new) in harmless.items():
            with self.subTest(change=name):
                self.assertEqual(PROJECT.count(old), 1)
                self.assertEqual(subset_hash(PROJECT.replace(old, new)), baseline)

    def test_scheme_and_build_setting_changes_move_the_hash(self) -> None:
        baseline = subset_hash(PROJECT)
        significant = {
            "the screen-capture format": ("preferredScreenCaptureFormat: screenshots",
                                          "preferredScreenCaptureFormat: screenRecording"),
            "an app setting": ('        SWIFT_VERSION: "6"\n    dependencies:\n      - target: Core',
                               '        SWIFT_VERSION: "5"\n    dependencies:\n      - target: Core'),
            "a dependency's setting": ('OTHER_SWIFT_FLAGS: "$(inherited)"', 'OTHER_SWIFT_FLAGS: "-Ounchecked"'),
            "a global setting": ("SWIFT_TREAT_WARNINGS_AS_ERRORS: YES", "SWIFT_TREAT_WARNINGS_AS_ERRORS: NO"),
            "the deployment target": ('    macOS: "26.0"', '    macOS: "27.0"'),
        }
        for name, (old, new) in significant.items():
            with self.subTest(change=name):
                self.assertEqual(PROJECT.count(old), 1)
                self.assertNotEqual(subset_hash(PROJECT.replace(old, new)), baseline)
        self.assertEqual(lineage.project_subset_hash(None, "VocelloMacUI", ()), lineage.NOT_APPLICABLE)

    def test_the_real_project_names_each_lane_scheme_and_its_targets(self) -> None:
        entries = lineage.yaml_lines((ROOT / "project.yml").read_text(encoding="utf-8"))
        mac = lineage.project_targets(entries, "VocelloMacUI", ())
        self.assertTrue({"QwenVoice", "VocelloMacUITests", "QwenVoiceCore"} <= set(mac))
        ios = lineage.project_targets(entries, "VocelloiOSUI", ())
        self.assertTrue({"VocelloiOS", "VocelloiOSUITests", "QwenVoiceCore"} <= set(ios))
        cli = lineage.project_targets(entries, None, ("VocelloCLI",))
        self.assertTrue({"VocelloCLI", "QwenVoiceCore"} <= set(cli))


class TopologyTests(unittest.TestCase):
    def test_topology_is_the_sorted_layer_union(self) -> None:
        xpc = [{"layers": ["engine", "engine-service", "app", "merged"]}, {"layers": ["engine", "app"]}]
        self.assertEqual(lineage.topology(xpc), ["app", "engine", "engine-service", "merged"])
        self.assertEqual(lineage.topology([{"layers": ["engine", "app", "merged"]}]), ["app", "engine", "merged"])
        self.assertEqual(lineage.topology([{"cell": "ui-perf/idle"}, "not-a-take"]), [])


if __name__ == "__main__":
    unittest.main()
