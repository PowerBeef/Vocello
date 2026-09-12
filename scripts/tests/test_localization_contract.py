#!/usr/bin/env python3
"""Tests for String Catalog and unlocalized-literal governance."""

from __future__ import annotations

import json
import copy
import plistlib
import re
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
      - path: Sources/iOS/InfoPlist.xcstrings
        buildPhase: resources
  VocelloCoreTests:
    type: bundle.unit-test
"""


def valid_catalog() -> dict[str, object]:
    strings: dict[str, object] = {}
    for key in localization_contract.REQUIRED_KEYS:
        if key in localization_contract.REQUIRED_PLURAL_KEYS:
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
            "localizations": {"en": english, "fr": copy.deepcopy(english)},
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
        purposes = {"NSMicrophoneUsageDescription": "Record locally.",
                    "NSSpeechRecognitionUsageDescription": "Transcribe locally."}
        (self.root / "Sources/iOS/Info.plist").write_bytes(plistlib.dumps(purposes))
        (self.root / "Sources/iOS/InfoPlist.xcstrings").write_text(json.dumps({
            "sourceLanguage": "en", "version": "1.0",
            "strings": {key: {"localizations": {
                locale: {"stringUnit": {"state": "translated", "value": value}}
                for locale in ("en", "fr")}} for key, value in purposes.items()}}))
        presentation = "\n".join(
            f'let key_{index} = String(localized: "{key}")'
            for index, key in enumerate(sorted(localization_contract.REQUIRED_KEYS))
        )
        (self.root / localization_contract.PRESENTATION_SOURCE).write_text(
            presentation + "\n", encoding="utf-8"
        )
        (self.root / localization_contract.INTERFACE_DEFAULTS_SOURCE).write_text("// fixture\n", encoding="utf-8")
        (self.root / localization_contract.COMMERCE_SOURCE).parent.mkdir(parents=True, exist_ok=True)
        (self.root / localization_contract.COMMERCE_SOURCE).write_text("// fixture\n", encoding="utf-8")
        expected_sources = {
            "Sources/iOS/IOSGenerationModeViews.swift": (
                "IOSAppLanguage.shared.presentation.installModel\n"
                "IOSAppLanguage.shared.presentation.longFormPlanningFailed\n"
                "IOSAppLanguage.shared.presentation.cloningConsentRequired\n"
                "IOSAppLanguage.shared.presentation.referenceAudioRequired\n"
            ),
            "Sources/iOS/Studio/StudioGenerationCoordinator.swift": (
                "IOSAppLanguage.shared.presentation.cancellationCouldNotFinish\n"
            ),
            "Sources/iOS/IOSSettingsViews.swift": "IOSAppLanguage.shared.presentation.status(.ready)\n",
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

    def test_process_locale_formatting_is_rejected(self) -> None:
        bad = self.root / "Sources/iOS/Bad.swift"
        bad.write_text(
            'let text = String.localizedStringWithFormat("%lld items", 0)\n', encoding="utf-8")
        with self.assertRaises(localization_contract.ContractError) as raised:
            localization_contract.validate(self.root)
        self.assertIn("process locale", str(raised.exception))
        bad.unlink()
        self.assertEqual(localization_contract.validate(self.root), 1)

    def test_partial_new_locale_cannot_ship(self) -> None:
        catalog = valid_catalog()
        entry = next(iter(catalog["strings"].values()))
        entry["localizations"]["de"] = copy.deepcopy(entry["localizations"]["en"])
        (self.root / localization_contract.CATALOG).write_text(json.dumps(catalog))
        with self.assertRaisesRegex(localization_contract.ContractError, "missing required localization de"):
            localization_contract.validate(self.root)

    def test_unknown_ui_locale_is_rejected(self) -> None:
        entry = next(iter(valid_catalog()["strings"].values()))
        entry["localizations"]["chinese"] = copy.deepcopy(entry["localizations"]["en"])
        with self.assertRaisesRegex(localization_contract.ContractError, "unsupported UI locales"):
            localization_contract._validate_translations(entry, "fixture")

    def test_new_locale_requires_permission_translations_too(self) -> None:
        catalog = valid_catalog()
        for entry in catalog["strings"].values():
            entry["localizations"]["de"] = copy.deepcopy(entry["localizations"]["en"])
        (self.root / localization_contract.CATALOG).write_text(json.dumps(catalog))
        with self.assertRaisesRegex(localization_contract.ContractError, "missing required localization de"):
            localization_contract.validate(self.root)

    def test_french_translation_cannot_disappear_or_lose_its_reviewed_value(self) -> None:
        for payload in (None, {}, {"stringUnit": {"state": "new", "value": "Prêt"}},
                        {"stringUnit": {"state": "translated", "value": ""}},
                        {"variations": []}):
            with self.subTest(payload=payload):
                catalog = valid_catalog()
                catalog["strings"]["vocello.status.ready"]["localizations"]["fr"] = payload
                (self.root / localization_contract.CATALOG).write_text(json.dumps(catalog))
                with self.assertRaises(localization_contract.ContractError):
                    localization_contract.validate(self.root)

    def test_argument_order_can_change_but_types_positions_and_counts_cannot(self) -> None:
        for french, accepted in (
            ("%2$@ : %1$lld", True),
            ("%1$lld : %2$@", True),
            ("%1$@ : %2$lld", False),
            ("%1$lld", False),
            ("%1$lld %2$@ %2$@", False),
            ("%3$lld %2$@", False),
        ):
            with self.subTest(french=french):
                entry = {"localizations": {locale: {"stringUnit": {
                    "state": "translated", "value": value}}
                    for locale, value in (("en", "%lld %@"), ("fr", french))}}
                if accepted:
                    localization_contract._validate_translations(entry, "fixture")
                else:
                    with self.assertRaisesRegex(localization_contract.ContractError, "format arguments"):
                        localization_contract._validate_translations(entry, "fixture")

    def test_french_plural_requires_both_forms_and_matching_arguments(self) -> None:
        for change in ("missing", "type", "flat"):
            catalog = valid_catalog()
            entry = catalog["strings"]["vocello.models.ready_count"]
            if change == "missing":
                del entry["localizations"]["fr"]["variations"]["plural"]["other"]
            elif change == "type":
                entry["localizations"]["fr"]["variations"]["plural"]["one"]["stringUnit"]["value"] = "%@ modèle"
            else:
                entry["localizations"]["fr"] = {"stringUnit": {"state": "translated", "value": "%lld modèles"}}
            with self.subTest(change=change), self.assertRaises(localization_contract.ContractError):
                localization_contract._validate_translations(entry, "fixture")

    def test_typed_interface_default_must_match_catalog_english(self) -> None:
        catalog_path = self.root / localization_contract.CATALOG
        catalog = json.loads(catalog_path.read_text())
        catalog["strings"]["vocello.ui.fixture"] = {
            "comment": "fixture", "extractionState": "manual",
            "localizations": {locale: {"stringUnit": {"state": "translated", "value": "Fixture"}} for locale in ("en", "fr")},
        }
        catalog_path.write_text(json.dumps(catalog))
        source = self.root / localization_contract.INTERFACE_DEFAULTS_SOURCE
        source.write_text('let x = String(localized: "vocello.ui.fixture", defaultValue: "Fixture")\n')
        localization_contract.validate(self.root)
        source.write_text('let x = String(localized: "vocello.ui.fixture", defaultValue: "Drifted")\n')
        with self.assertRaisesRegex(localization_contract.ContractError, "differs from the catalog"):
            localization_contract.validate(self.root)
        source.write_text("// no binding\n")
        with self.assertRaisesRegex(localization_contract.ContractError, "do not match the catalog"):
            localization_contract.validate(self.root)
        source.write_text('let x = String(localized: "vocello.ui.fixture", defaultValue: "Fixture")\n')
        commerce = self.root / localization_contract.COMMERCE_SOURCE
        commerce.write_text('let y = String(localized: "vocello.commerce.missing")\n')
        with self.assertRaisesRegex(localization_contract.ContractError, "not in the catalog"):
            localization_contract.validate(self.root)

    def test_permission_translation_preserves_source_and_is_bundled(self) -> None:
        path = self.root / "Sources/iOS/InfoPlist.xcstrings"
        catalog = json.loads(path.read_text())
        catalog["strings"]["NSMicrophoneUsageDescription"]["localizations"]["en"]["stringUnit"]["value"] = "Different claim"
        path.write_text(json.dumps(catalog))
        with self.assertRaisesRegex(localization_contract.ContractError, "purpose string"):
            localization_contract.validate(self.root)

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

    def test_recovery_export_plural_cannot_be_replaced_with_uninflected_text(self) -> None:
        catalog = valid_catalog()
        catalog["strings"]["vocello.history.recovery_export_failure"]["localizations"]["en"] = {
            "stringUnit": {"state": "translated", "value": "%lld files failed"}
        }
        (self.root / localization_contract.CATALOG).write_text(json.dumps(catalog), encoding="utf-8")
        with self.assertRaisesRegex(localization_contract.ContractError, "plural one"):
            localization_contract.validate(self.root)

    def test_additional_plural_keys_validate_categories_and_reject_malformed_payloads(self) -> None:
        for plural in (
            {"one": {"stringUnit": {"state": "translated", "value": "one"}},
             "other": {"stringUnit": {"state": "translated", "value": "many"}}},
            [], {"one": None}, {"one": {"stringUnit": []}},
            {"one": {"stringUnit": {"value": ""}}},
        ):
            with self.subTest(plural=plural):
                catalog = valid_catalog()
                catalog["strings"]["vocello.fixture.count"] = {
                    "comment": "Fixture count", "extractionState": "manual",
                    "localizations": {locale: {"variations": {"plural": plural}}
                                      for locale in ("en", "fr")},
                }
                (self.root / localization_contract.CATALOG).write_text(json.dumps(catalog), encoding="utf-8")
                if isinstance(plural, dict) and "other" in plural:
                    self.assertEqual(localization_contract.validate(self.root), 1)
                else:
                    with self.assertRaises(localization_contract.ContractError):
                        localization_contract.validate(self.root)

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
