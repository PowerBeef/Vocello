#!/usr/bin/env python3
"""Unit tests for scripts/check_delivery_instructions.py.

The behavioural checks run on synthetic presets so they keep testing the rule
rather than today's shipped copy; one integration test asserts the real
repository passes its own gate.
"""
import hashlib
import json
import os
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from check_delivery_instructions import (  # noqa: E402
    ContractError,
    axis_direction,
    effective_append_decisions,
    find_findings,
    finding_key,
    load_presets,
    main,
    repeated_intensifier,
    validate_versioned_instructions,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
TOKENS = ["clear", "clearly", "diction", "clarity"]


def preset(normal, strong):
    return {"normal": normal, "strong": strong}


def findings_for(presets, expectations=None, preset_wide=True):
    return find_findings(presets, TOKENS, expectations or {}, preset_wide)


def checks(findings, name):
    return [f for f in findings if f["check"] == name]


class AppendParityTests(unittest.TestCase):
    def test_tiers_that_ship_different_boilerplate_are_an_error(self):
        # The live defect: one tier asks for clarity so it suppresses the
        # append, the other does not, and the pair differs by 76 characters
        # that say nothing about intensity.
        presets = {"happy": preset("keep it clear and bright", "bright and loud")}
        found = checks(findings_for(presets, preset_wide=False), "diction-append-parity")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["severity"], "error")
        self.assertEqual(found[0]["preset"], "happy")

    def test_preset_wide_resolution_removes_the_asymmetry(self):
        presets = {"happy": preset("keep it clear and bright", "bright and loud")}
        self.assertEqual(checks(findings_for(presets, preset_wide=True),
                                "diction-append-parity"), [])

    def test_tiers_that_agree_are_never_flagged(self):
        for tiers in (preset("clear and bright", "clearly brighter"),
                      preset("bright", "brighter")):
            self.assertEqual(
                checks(findings_for({"happy": tiers}, preset_wide=False),
                       "diction-append-parity"),
                [],
            )

    def test_one_clarity_tier_suppresses_the_whole_preset(self):
        decisions = effective_append_decisions(
            preset("clear words", "loud words"), TOKENS, preset_wide=True
        )
        self.assertEqual(decisions, {"normal": False, "strong": False})


class IntensifierTests(unittest.TestCase):
    def test_repetition_is_flagged(self):
        for text in ("very very happy", "very, very deep", "really really fast"):
            self.assertIsNotNone(repeated_intensifier(text), text)

    def test_a_single_intensifier_is_fine(self):
        # Upstream's own examples are "Very happy." and "very angry and
        # disappointed", so one intensifier must not fail the build.
        for text in ("very happy", "say it in a very angry tone"):
            self.assertIsNone(repeated_intensifier(text), text)

    def test_repetition_surfaces_as_an_error_with_its_tier(self):
        found = checks(findings_for({"happy": preset("bright", "very very bright")}),
                       "repeated-intensifier")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["severity"], "error")
        self.assertEqual(found[0]["tier"], "strong")


class AxisDirectionTests(unittest.TestCase):
    def test_multi_word_phrases_only_so_stray_words_do_not_register(self):
        self.assertIsNone(axis_direction("wide swings between low and high", "pitch"))

    def test_a_stated_direction_is_read(self):
        self.assertEqual(axis_direction("heated raised pitch", "pitch"), 1)
        self.assertEqual(axis_direction("a lower clipped tone", "pitch"), -1)

    def test_a_self_conflicting_string_states_nothing(self):
        self.assertIsNone(axis_direction("lower pitch then raised pitch", "pitch"))


class TierInversionTests(unittest.TestCase):
    def test_an_inverted_axis_is_reported_for_acknowledgement(self):
        presets = {"angry": preset("a lower clipped tone", "heated raised pitch")}
        found = checks(findings_for(presets), "tier-direction-inversion")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["severity"], "acknowledged")
        self.assertEqual(found[0]["axis"], "pitch")

    def test_a_silent_tier_is_not_an_inversion(self):
        # Escalating one axis while saying nothing about it at the other tier is
        # ordinary copy, not a contradiction.
        presets = {"calm": preset("low settled pitch", "softly grounded")}
        self.assertEqual(checks(findings_for(presets), "tier-direction-inversion"), [])

    def test_agreeing_tiers_are_not_an_inversion(self):
        presets = {"happy": preset("lifted pitch", "higher pitch")}
        self.assertEqual(checks(findings_for(presets), "tier-direction-inversion"), [])


class ExpectationConflictTests(unittest.TestCase):
    EXPECTED_UP = {"angry": {"pitch_shift_semitones": {"direction": 1, "tier": "required"}}}

    def test_copy_contradicting_its_expectation_is_reported(self):
        presets = {"angry": preset("a lower clipped tone", "heated raised pitch")}
        found = checks(findings_for(presets, self.EXPECTED_UP), "expectation-conflict")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["tier"], "normal")
        self.assertIn("does not presume which", found[0]["detail"])

    def test_agreement_is_silent(self):
        presets = {"angry": preset("raised pitch", "higher pitch")}
        self.assertEqual(checks(findings_for(presets, self.EXPECTED_UP),
                                "expectation-conflict"), [])

    def test_a_preset_with_no_expectation_is_never_conflicted(self):
        presets = {"dramatic": preset("a lower clipped tone", "lower pitch")}
        self.assertEqual(checks(findings_for(presets, self.EXPECTED_UP),
                                "expectation-conflict"), [])


SWIFT_FIXTURE = '''
public static let neutralPresetInstruction =
    "Speak in an even, level tone."

public static let all: [EmotionPreset] = [
    EmotionPreset(
        id: "neutral",
        label: "Neutral",
        instructions: [
            .normal: EmotionPreset.neutralPresetInstruction,
            .strong: EmotionPreset.neutralPresetInstruction,
        ]
    ),
    EmotionPreset(
        id: "happy",
        label: "Happy",
        instructions: [
            .normal: "Speak happily, with a \\"bright\\" tone.",
            .strong: "Speak joyfully and loudly.",
        ]
    ),
]
'''


class ParsingTests(unittest.TestCase):
    def _root_with(self, preset_source):
        root = pathlib.Path(tempfile.mkdtemp())
        target = root / "Sources" / "QwenVoiceCore"
        target.mkdir(parents=True)
        (target / "EmotionPreset.swift").write_text(preset_source, encoding="utf-8")
        return root

    def test_named_constants_and_escapes_resolve(self):
        presets = load_presets(self._root_with(SWIFT_FIXTURE))
        self.assertEqual(sorted(presets), ["happy", "neutral"])
        self.assertEqual(presets["neutral"]["strong"], "Speak in an even, level tone.")
        self.assertEqual(presets["happy"]["normal"],
                         'Speak happily, with a "bright" tone.')

    def test_an_unresolvable_constant_is_an_error(self):
        source = SWIFT_FIXTURE.replace(
            ".normal: EmotionPreset.neutralPresetInstruction",
            ".normal: EmotionPreset.missingConstant",
        )
        with self.assertRaises(ContractError):
            load_presets(self._root_with(source))

    def test_parsing_nothing_fails_rather_than_passing_vacuously(self):
        with self.assertRaises(ContractError):
            load_presets(self._root_with("// no presets here\n"))

    def test_a_missing_source_is_an_error(self):
        with self.assertRaises(ContractError):
            load_presets(pathlib.Path(tempfile.mkdtemp()))


class KeyTests(unittest.TestCase):
    def test_keys_include_every_dimension_that_distinguishes_a_finding(self):
        base = {"check": "expectation-conflict", "preset": "angry",
                "tier": "normal", "axis": "pitch"}
        self.assertEqual(finding_key(base), "expectation-conflict/angry/normal/pitch")
        self.assertEqual(
            finding_key({"check": "diction-append-parity", "preset": "happy"}),
            "diction-append-parity/happy",
        )


class LocalizedInstructionContractTests(unittest.TestCase):
    ENGLISH = "Sound fiercely angry and frustrated."
    MANDARIN = "语气要强烈愤怒。"

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temporary.name)
        source = self.root / "Sources/QwenVoiceCore/EmotionPreset.swift"
        source.parent.mkdir(parents=True)
        source.write_text(
            f'''public static let angryBilingualV3English = "{self.ENGLISH}"
public static let angryBilingualV3Mandarin = "{self.MANDARIN}"
''',
            encoding="utf-8",
        )
        resources = self.root / "Sources/Resources"
        resources.mkdir(parents=True)
        (resources / "qwenvoice_contract.json").write_text(json.dumps({
            "speakers": {"Built-in": ["aiden", "vivian"]},
            "speakerMetadata": {
                "aiden": {"nativeLanguage": "English"},
                "vivian": {"nativeLanguage": "Chinese"},
            },
        }), encoding="utf-8")
        scripts = self.root / "scripts/tests"
        scripts.mkdir(parents=True)
        (self.root / "scripts/angry_bilingual_safety_matrix.py").touch()
        (scripts / "test_angry_bilingual_safety_matrix.py").touch()
        self.presets = {"angry": {"normal": self.ENGLISH, "strong": "Strong angry."}}
        self.contract = {
            "canonicalInstructionDigests": {
                "angry.normal": self.digest(self.ENGLISH),
                "angry.strong": self.digest("Strong angry."),
            },
            "localizedInstructionVariants": [{
                "version": "angry-bilingual-v3",
                "cellID": "angry.normal",
                "languages": [
                    {"id": "english", "sourceConstant": "angryBilingualV3English",
                     "digest": self.digest(self.ENGLISH)},
                    {"id": "mandarin", "sourceConstant": "angryBilingualV3Mandarin",
                     "digest": self.digest(self.MANDARIN)},
                ],
                "routing": {
                    "mode": "custom",
                    "requiresNativeLanguage": "Chinese",
                    "requiresOutputLanguage": "chinese",
                    "speakerMetadataSource": "Sources/Resources/qwenvoice_contract.json",
                    "fallbackLanguage": "english",
                    "customTextBehavior": "verbatim",
                },
            }],
            "safetyMatrix": {
                "runner": "scripts/angry_bilingual_safety_matrix.py",
                "tests": "scripts/tests/test_angry_bilingual_safety_matrix.py",
                "fixedSeeds": [32060826, 32060827, 32060828, 32060829],
                "requiredTakeCount": 36,
                "authority": "hard-failure-and-routing-safety-only",
            },
        }

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def digest(value):
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def validate(self, contract=None):
        return validate_versioned_instructions(
            self.root, contract or self.contract, self.presets
        )

    def test_valid_exact_variant_and_dual_match_contract_pass(self):
        self.assertEqual(self.validate(), {"canonicalCells": 2, "localizedVariants": 1})

    def test_missing_translation_fails(self):
        contract = json.loads(json.dumps(self.contract))
        contract["localizedInstructionVariants"][0]["languages"].pop()
        with self.assertRaisesRegex(ContractError, "missing translation"):
            self.validate(contract)

    def test_unsupported_or_duplicate_language_fails(self):
        contract = json.loads(json.dumps(self.contract))
        contract["localizedInstructionVariants"][0]["languages"][1]["id"] = "cantonese"
        with self.assertRaisesRegex(ContractError, "unsupported instruction language"):
            self.validate(contract)
        contract = json.loads(json.dumps(self.contract))
        contract["localizedInstructionVariants"][0]["languages"][1]["id"] = "english"
        with self.assertRaisesRegex(ContractError, "duplicate or malformed"):
            self.validate(contract)

    def test_duplicate_variant_and_digest_drift_fail(self):
        contract = json.loads(json.dumps(self.contract))
        contract["localizedInstructionVariants"].append(
            contract["localizedInstructionVariants"][0]
        )
        with self.assertRaisesRegex(ContractError, "duplicate localized"):
            self.validate(contract)
        contract = json.loads(json.dumps(self.contract))
        contract["canonicalInstructionDigests"]["angry.strong"] = "0" * 64
        with self.assertRaisesRegex(ContractError, "digest drift"):
            self.validate(contract)

    def test_unregistered_speaker_metadata_fails(self):
        speaker_path = self.root / "Sources/Resources/qwenvoice_contract.json"
        payload = json.loads(speaker_path.read_text(encoding="utf-8"))
        payload["speakerMetadata"].pop("vivian")
        speaker_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "unique metadata"):
            self.validate()


class RepositoryTests(unittest.TestCase):
    def test_the_shipped_repository_passes_its_own_gate(self):
        self.assertEqual(main(["--root", str(REPO_ROOT)]), 0)


if __name__ == "__main__":
    unittest.main()
