#!/usr/bin/env python3
"""Tests for String Catalog and unlocalized-literal governance."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import localization_contract  # noqa: E402


VALID_PROJECT = """\
settings:
  base:
    LOCALIZATION_PREFERS_STRING_CATALOGS: YES
    STRING_CATALOG_GENERATE_SYMBOLS: YES
    SWIFT_EMIT_LOC_STRINGS: YES
targets:
  VocelloCLI:
    type: tool
  QwenVoiceEngineService:
    type: xpc-service
  VocelloiOS:
    type: application
    sources:
      - path: Sources/Resources/Localizable.xcstrings
        buildPhase: resources
  VocelloCoreTests:
    type: bundle.unit-test
"""


def valid_catalog() -> dict[str, object]:
    strings: dict[str, object] = {}
    for key in localization_contract.REQUIRED_KEYS:
        if key == "vocello.models.ready_count":
            english: dict[str, object] = {
                "variations": {
                    "plural": {
                        "one": {"stringUnit": {"state": "translated", "value": "%lld model ready"}},
                        "other": {"stringUnit": {"state": "translated", "value": "%lld models ready"}},
                    }
                }
            }
        else:
            english = {"stringUnit": {"state": "translated", "value": key}}
        strings[key] = {
            "comment": f"Translator context for {key}",
            "extractionState": "manual",
            "localizations": {"en": english},
        }
    return {"sourceLanguage": "en", "strings": strings, "version": "1.0"}


class LocalizationContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "Sources/Resources").mkdir(parents=True)
        (self.root / "Sources/SharedSupport/Services").mkdir(parents=True)
        (self.root / "Sources/iOS/Studio").mkdir(parents=True)
        (self.root / "Sources/iOSSupport/Services").mkdir(parents=True)
        (self.root / "Sources/Views").mkdir(parents=True)
        (self.root / "Tests/VocelloiOSUITests").mkdir(parents=True)
        (self.root / "Tests/VocelloMacUITests").mkdir(parents=True)
        (self.root / "config").mkdir(parents=True)

        (self.root / "project.yml").write_text(VALID_PROJECT, encoding="utf-8")
        (self.root / localization_contract.CATALOG).write_text(
            json.dumps(valid_catalog()), encoding="utf-8"
        )
        presentation = "\n".join(
            f'let key_{index} = String(localized: "{key}")'
            for index, key in enumerate(sorted(localization_contract.REQUIRED_KEYS))
        )
        (self.root / localization_contract.PRESENTATION_SOURCE).write_text(
            presentation + "\n", encoding="utf-8"
        )
        expected_sources = {
            "Sources/iOS/IOSGenerationModeViews.swift": (
                "VocelloPresentationText.installModel\n"
                "VocelloPresentationText.longFormPlanningFailed\n"
                "VocelloPresentationText.cloningConsentRequired\n"
                "VocelloPresentationText.referenceAudioRequired\n"
            ),
            "Sources/iOS/Studio/StudioGenerationCoordinator.swift": (
                "VocelloPresentationText.cancellationCouldNotFinish\n"
            ),
            "Sources/iOS/IOSSettingsViews.swift": "VocelloPresentationText.status(.ready)\n",
            "Sources/iOSSupport/Services/IOSModelProgressPresentation.swift": (
                "VocelloPresentationText.status(.checkingDownloadedFiles)\n"
                "VocelloPresentationText.status(.makingModelAvailableOffline)\n"
            ),
        }
        for relative, source in expected_sources.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding="utf-8")
        (self.root / localization_contract.UI_TEST_SOURCE).write_text(
            "UICTContentSizeCategoryAccessibilityXXXL\n"
            "-NSDoubleLocalizedStrings\n"
            "-NSShowNonLocalizedStrings\n"
            "Pseudo-AX-XXXL\n",
            encoding="utf-8",
        )
        (self.root / localization_contract.MAC_UI_TEST_SOURCE).write_text(
            "-NSDoubleLocalizedStrings\n-NSShowNonLocalizedStrings\n",
            encoding="utf-8",
        )
        self.literal_source = self.root / "Sources/iOS/ExampleView.swift"
        self.literal_source.write_text('Text("Existing literal")\n', encoding="utf-8")
        localization_contract.write_snapshot(self.root, localization_contract.BASELINE)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_valid_contract_passes(self) -> None:
        self.assertEqual(localization_contract.validate(self.root), 1)

    def test_missing_setting_catalog_or_resource_fails(self) -> None:
        cases = (
            ("setting", "    SWIFT_EMIT_LOC_STRINGS: YES\n", ""),
            ("resource", "      - path: Sources/Resources/Localizable.xcstrings\n", ""),
        )
        for label, old, new in cases:
            with self.subTest(label=label):
                project = self.root / "project.yml"
                original = project.read_text(encoding="utf-8")
                project.write_text(original.replace(old, new), encoding="utf-8")
                with self.assertRaises(localization_contract.ContractError):
                    localization_contract.validate(self.root)
                project.write_text(original, encoding="utf-8")

        (self.root / localization_contract.CATALOG).unlink()
        with self.assertRaisesRegex(localization_contract.ContractError, "missing"):
            localization_contract.validate(self.root)

    def test_manual_context_english_value_and_plural_categories_are_required(self) -> None:
        catalog_path = self.root / localization_contract.CATALOG
        for label, mutate, message in (
            (
                "comment",
                lambda value: value["strings"]["vocello.status.ready"].update({"comment": ""}),
                "translator context",
            ),
            (
                "english",
                lambda value: value["strings"]["vocello.status.ready"]["localizations"].pop("en"),
                "English localization",
            ),
            (
                "plural",
                lambda value: value["strings"]["vocello.models.ready_count"]["localizations"]["en"]
                ["variations"]["plural"].pop("other"),
                "plural other",
            ),
        ):
            with self.subTest(label=label):
                value = valid_catalog()
                mutate(value)
                catalog_path.write_text(json.dumps(value), encoding="utf-8")
                with self.assertRaisesRegex(localization_contract.ContractError, message):
                    localization_contract.validate(self.root)
        catalog_path.write_text(json.dumps(valid_catalog()), encoding="utf-8")

    def test_new_literal_is_rejected_but_baseline_removal_is_allowed(self) -> None:
        self.literal_source.write_text(
            'Text("Existing literal")\nButton("New literal") {}\n', encoding="utf-8"
        )
        with self.assertRaisesRegex(localization_contract.ContractError, "new direct"):
            localization_contract.validate(self.root)

        self.literal_source.write_text("", encoding="utf-8")
        self.assertEqual(localization_contract.validate(self.root), 0)

    def test_typed_localized_string_is_not_classified_as_a_direct_literal(self) -> None:
        self.literal_source.write_text(
            'let value = String(localized: "vocello.new.key")\nText(value)\n',
            encoding="utf-8",
        )
        self.assertEqual(localization_contract.validate(self.root), 0)

    def test_pseudo_localization_arguments_are_required(self) -> None:
        path = self.root / localization_contract.UI_TEST_SOURCE
        path.write_text(
            path.read_text(encoding="utf-8").replace("-NSDoubleLocalizedStrings", ""),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(localization_contract.ContractError, "NSDouble"):
            localization_contract.validate(self.root)

        path.write_text(
            "UICTContentSizeCategoryAccessibilityXXXL\n"
            "-NSDoubleLocalizedStrings\n"
            "-NSShowNonLocalizedStrings\n"
            "Pseudo-AX-XXXL\n",
            encoding="utf-8",
        )
        mac_path = self.root / localization_contract.MAC_UI_TEST_SOURCE
        mac_path.write_text("-NSShowNonLocalizedStrings\n", encoding="utf-8")
        with self.assertRaisesRegex(localization_contract.ContractError, "macOS"):
            localization_contract.validate(self.root)

    def test_baseline_rejects_absolute_paths_and_duplicate_identity(self) -> None:
        baseline_path = self.root / localization_contract.BASELINE
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        baseline["records"][0]["path"] = "/private/source.swift"
        baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
        with self.assertRaisesRegex(localization_contract.ContractError, "repository-relative"):
            localization_contract.validate(self.root)


if __name__ == "__main__":
    unittest.main()
