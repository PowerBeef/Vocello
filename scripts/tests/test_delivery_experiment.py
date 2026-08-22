#!/usr/bin/env python3
"""Contract tests for the operator-local delivery experiment planner."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from delivery_experiment import (  # noqa: E402
    DEFAULT_CONTRACT,
    DEFAULT_CORPUS,
    EXPECTED_PRESETS,
    ExperimentError,
    PRODUCT_CONTRACT,
    build_plan,
    compile_instruction,
    digest,
    script_for_condition,
    seed_plan,
    validate_contract,
    validate_corpus,
)


class DeliveryExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads(DEFAULT_CONTRACT.read_text(encoding="utf-8"))
        cls.corpus = json.loads(DEFAULT_CORPUS.read_text(encoding="utf-8"))
        cls.product = json.loads(PRODUCT_CONTRACT.read_text(encoding="utf-8"))

    def test_checked_in_contract_and_corpus_validate(self) -> None:
        self.assertEqual(validate_contract(self.contract), self.contract)
        self.assertEqual(validate_corpus(self.corpus, self.product), self.corpus)

    def test_prompt_arms_are_cumulative_and_digest_bound(self) -> None:
        acoustic = compile_instruction(
            self.contract, "happy", "acoustic-only", "english"
        )
        emotion = compile_instruction(
            self.contract, "happy", "emotion-acoustic", "english"
        )
        scene = compile_instruction(
            self.contract, "happy", "emotion-acoustic-scene", "english"
        )
        constrained = compile_instruction(
            self.contract, "happy", "emotion-acoustic-scene-constraint", "english"
        )
        self.assertIn(acoustic["text"], emotion["text"])
        self.assertIn(emotion["text"], scene["text"])
        self.assertIn(scene["text"], constrained["text"])
        self.assertEqual(len(constrained["sha256"]), 64)
        self.assertNotEqual(acoustic["sha256"], constrained["sha256"])

    def test_current_arm_requires_runtime_production_copy(self) -> None:
        with self.assertRaisesRegex(ExperimentError, "production instruction"):
            compile_instruction(self.contract, "happy", "current", "english")
        result = compile_instruction(
            self.contract, "happy", "current", "english",
            production_instruction="  Current   production copy. ",
        )
        self.assertEqual(result["text"], "Current production copy.")

    def test_contradictory_candidate_fails_closed(self) -> None:
        changed = copy.deepcopy(self.contract)
        changed["presets"]["happy"]["instructionLanguages"]["english"]["scene"] = (
            "Sound deeply sorrowful."
        )
        with self.assertRaisesRegex(ExperimentError, "prohibited contradictory"):
            compile_instruction(
                changed, "happy", "emotion-acoustic-scene", "english"
            )

    def test_promotion_and_external_model_boundaries_fail_closed(self) -> None:
        changed = copy.deepcopy(self.contract)
        changed["promotionGuardrails"]["maximumAbsoluteWEROrCERRegression"] = 0.02
        with self.assertRaisesRegex(ExperimentError, "promotion guardrails"):
            validate_contract(changed)
        changed = copy.deepcopy(self.contract)
        changed["externalModelPolicy"]["required"].pop()
        with self.assertRaisesRegex(ExperimentError, "external model adoption"):
            validate_contract(changed)
        changed = copy.deepcopy(self.contract)
        changed["status"] = "production"
        with self.assertRaisesRegex(ExperimentError, "experimental-only"):
            validate_contract(changed)

    def test_corpus_mapping_and_translation_groups_cannot_silently_drift(self) -> None:
        changed = copy.deepcopy(self.corpus)
        changed["nativeSpeakerLanguages"]["aiden"] = "Chinese"
        with self.assertRaisesRegex(ExperimentError, "mapping drifted"):
            validate_corpus(changed, self.product)
        changed = copy.deepcopy(self.corpus)
        changed["crossLanguageSentinels"].pop()
        with self.assertRaisesRegex(ExperimentError, "sentinels"):
            validate_corpus(changed, self.product)
        changed = copy.deepcopy(self.corpus)
        changed["seedPartitions"]["confirmation"] = dict(
            changed["seedPartitions"]["development"]
        )
        with self.assertRaisesRegex(ExperimentError, "seed partitions overlap"):
            validate_corpus(changed, self.product)

    def test_split_scripts_have_distinct_identity_and_bytes(self) -> None:
        scripts = [
            script_for_condition(
                self.contract, self.corpus, language="English", preset="happy",
                split=split, length="medium", condition="congruent",
            )
            for split in ("calibration", "development", "confirmation")
        ]
        self.assertEqual(len({row["scriptID"] for row in scripts}), 3)
        self.assertEqual(len({row["translationGroup"] for row in scripts}), 3)
        self.assertEqual(len({row["sha256"] for row in scripts}), 3)

    def test_plan_is_complete_deterministic_and_source_bound(self) -> None:
        production = {preset: f"Production {preset}." for preset in EXPECTED_PRESETS}
        first = build_plan(
            self.contract, self.corpus, self.product,
            split="development", arm="current", instruction_language="english",
            variant="speed", sampling_combination="official-official", seeds=[32000011],
            production_instructions=production,
        )
        second = build_plan(
            self.contract, self.corpus, self.product,
            split="development", arm="current", instruction_language="english",
            variant="speed", sampling_combination="official-official", seeds=[32000011],
            production_instructions=production,
        )
        self.assertEqual(first, second)
        self.assertEqual(len(first["rows"]), 13 * 8 * 3 * 3)
        sentinels = {
            (row["speakerID"], row["outputLanguage"])
            for row in first["rows"]
            if row["coverageRole"] == "cross-language-sentinel"
        }
        self.assertEqual(sentinels, {
            ("aiden", "Chinese"), ("vivian", "English"),
            ("ono_anna", "English"), ("sohee", "English"),
        })
        body = dict(first)
        stored = body.pop("planDigest")
        self.assertEqual(stored, digest(body))

    def test_seed_identity_cannot_leak_across_holdout_partitions(self) -> None:
        production = {preset: f"Production {preset}." for preset in EXPECTED_PRESETS}
        with self.assertRaisesRegex(ExperimentError, "development seeds"):
            build_plan(
                self.contract, self.corpus, self.product,
                split="development", arm="current", instruction_language="english",
                variant="speed", sampling_combination="official-official",
                seeds=[33000001], production_instructions=production,
            )

    def test_seed_plan_clamps_and_marks_underpowered_result_inconclusive(self) -> None:
        strong = seed_plan(1.5)
        weak = seed_plan(0.2)
        self.assertEqual(strong["selectedSeeds"], 8)
        self.assertEqual(weak["selectedSeeds"], 20)
        self.assertFalse(weak["adequatelyPoweredWithinCap"])
        self.assertEqual(weak["outcomeIfCapReached"], "inconclusive")


if __name__ == "__main__":
    unittest.main()
