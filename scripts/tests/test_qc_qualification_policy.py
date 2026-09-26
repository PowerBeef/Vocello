#!/usr/bin/env python3
"""The audio-QC qualification policy (A1-A10, decision 5) and its validator."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import audio_qc_qualification  # noqa: E402
from lib.qc_qualification import policy  # noqa: E402


class PolicyTests(unittest.TestCase):
    committed: dict

    @classmethod
    def setUpClass(cls) -> None:
        cls.committed = policy.load_policy()

    def mutated(self, change) -> list[str]:
        value = copy.deepcopy(self.committed)
        change(value)
        return policy.validate_policy(value)

    def test_the_committed_policy_is_valid_and_adopted(self) -> None:
        self.assertEqual(policy.validate_policy(self.committed), [])
        self.assertEqual(self.committed["status"], "adopted")
        self.assertEqual([entry["id"] for entry in self.committed["additions"]], [f"A{n}" for n in range(1, 11)])
        fail = self.committed["operatingPoints"]["fail"]
        self.assertEqual((fail["farPooledMax"], fail["farPerLanguageMax"], fail["farPopulation"]), (0.01, 0.05, "N2"))
        self.assertEqual(fail["minimumUnits"]["n2Negatives"], 1240)
        self.assertEqual(fail["minimumUnits"]["n2NegativesPerLanguage"], 124)
        warn = self.committed["operatingPoints"]["warn"]["minimumUnits"]
        self.assertEqual((warn["calibration"], warn["good"], warn["bad"]), (60, 60, 60))
        lane = self.committed["operatingPoints"]["evidenceLaneFail"]
        self.assertEqual((lane["farPooledMax"], lane["farPerLanguageMax"]), (0.02, 0.10))

    def test_the_authority_rules_stay_verbatim(self) -> None:
        errors = self.mutated(lambda value: value["authorityRules"].update(automaticMetricsMayScreenOnly=False))
        self.assertTrue(any("automaticMetricsMayScreenOnly" in error for error in errors))
        errors = self.mutated(lambda value: value["authorityRules"].update(requiresIndependentHumanLabels=True))
        self.assertTrue(any("requiresIndependentHumanLabels" in error for error in errors))
        self.assertTrue(self.mutated(lambda value: value["authorityRules"]["text"].pop()))

    def test_additions_must_be_complete_and_ordered(self) -> None:
        self.assertTrue(self.mutated(lambda value: value["additions"].pop(4)))
        self.assertTrue(self.mutated(lambda value: value["additions"].reverse()))
        self.assertTrue(self.mutated(lambda value: value["additions"][2].update(rule="")))

    def test_fail_must_be_stricter_than_warn(self) -> None:
        errors = self.mutated(lambda value: value["operatingPoints"]["fail"].update(farPooledMax=0.2))
        self.assertTrue(any(error.startswith("A8") for error in errors))
        errors = self.mutated(lambda value: value["operatingPoints"]["fail"].update(tprSevereMin=0.6))
        self.assertTrue(any(error.startswith("A8") for error in errors))
        errors = self.mutated(lambda value: value["operatingPoints"]["evidenceLaneFail"].update(farPooledMax=0.005))
        self.assertTrue(any(error.startswith("A8") for error in errors))

    def test_floors_that_cannot_meet_their_bound_are_refused(self) -> None:
        errors = self.mutated(
            lambda value: value["operatingPoints"]["fail"]["minimumUnits"].update(n2NegativesPerLanguage=50))
        # A simultaneous ten-language claim at 5% needs 104 per language, not the 95% table's 59.
        self.assertTrue(any("per-language N2" in error and "needs 104" in error for error in errors), errors)
        errors = self.mutated(lambda value: value["operatingPoints"]["warn"]["minimumUnits"].update(good=20))
        self.assertTrue(any("warn pooled" in error for error in errors), errors)
        errors = self.mutated(
            lambda value: value["operatingPoints"]["fail"]["minimumUnits"].update(positivesPerCell=20))
        self.assertTrue(any("severe positives" in error for error in errors), errors)
        errors = self.mutated(lambda value: value["operatingPoints"]["fail"]["minimumUnits"].update(n2Negatives=600))
        self.assertTrue(any("fewer than the per-language floors" in error for error in errors), errors)

    def test_per_language_floors_hold_at_the_bonferroni_confidence(self) -> None:
        points = self.committed["operatingPoints"]
        self.assertEqual(points["fail"]["perLanguageConfidence"], 0.995)
        self.assertEqual(points["evidenceLaneFail"]["perLanguageConfidence"], 0.995)
        self.assertAlmostEqual(points["warn"]["perLanguageConfidence"], 1 - 0.05 / 3, places=6)
        # 29 per language bound FAR at 0.167 at 99.5%, above the 10% evidence-lane bound; 51 is the floor.
        errors = self.mutated(lambda value: value["operatingPoints"]["evidenceLaneFail"]["minimumUnits"].update(
            n2Negatives=290, n2NegativesPerLanguage=29))
        self.assertTrue(any("evidenceLaneFail per-language N2" in error and "needs 51" in error
                            for error in errors), errors)
        self.assertEqual(points["evidenceLaneFail"]["minimumUnits"]["n2NegativesPerLanguage"], 51)
        errors = self.mutated(lambda value: value["operatingPoints"]["fail"].update(perLanguageConfidence=0.95))
        self.assertTrue(any("perLanguageConfidence" in error for error in errors), errors)
        errors = self.mutated(lambda value: value["operatingPoints"]["fail"].update(n3FlagRateScope="per-language"))
        self.assertTrue(any("n3FlagRateScope" in error for error in errors), errors)
        errors = self.mutated(lambda value: value["operatingPoints"]["fail"]["minimumUnits"].update(languages=9))
        self.assertTrue(any("covers 9 languages" in error for error in errors), errors)

    def test_the_sample_size_table_is_recomputed(self) -> None:
        errors = self.mutated(lambda value: value["statistics"]["sampleSizeTable"][4]["clopperPearson"].update({"0": 300}))
        self.assertTrue(any("needs 299 units, not 300" in error for error in errors), errors)
        errors = self.mutated(lambda value: value["statistics"]["multiplicity"].update(
            zeroErrorUnitsPerLanguageAtFivePercent=59))
        self.assertTrue(any("needs 104 units" in error for error in errors), errors)

    def test_evidence_lane_bar_never_decides_a_product_verdict(self) -> None:
        errors = self.mutated(lambda value: value["operatingPoints"]["evidenceLaneFail"].update(productAffecting=True))
        self.assertTrue(any("evidence lanes only" in error for error in errors))
        errors = self.mutated(lambda value: value["operatingPoints"]["fail"].update(farPopulation="N1"))
        self.assertTrue(any("A2" in error for error in errors))

    def test_the_verdict_vocabulary_is_the_composer_s(self) -> None:
        errors = self.mutated(lambda value: value["verdicts"].update(
            precedence=["fail", "abstain", "unavailable", "warn", "uncalibrated", "pass"]))
        self.assertTrue(any("precedence" in error for error in errors))
        errors = self.mutated(lambda value: value["laneGatingSets"]["clone-lane"].update(classes=["E", "F"]))
        self.assertTrue(any("laneGatingSets" in error for error in errors))
        errors = self.mutated(lambda value: value["thresholdDerivation"].update(tprOptimized=True))
        self.assertTrue(any("tprOptimized" in error for error in errors))
        errors = self.mutated(lambda value: value["operatingPoints"].update(shadow={"blocks": True, "countsAsPass": False}))
        self.assertTrue(any("shadow" in error for error in errors))

    def test_the_command_passes_the_committed_file_and_refuses_a_broken_one(self) -> None:
        with redirect_stdout(StringIO()) as output:
            self.assertEqual(audio_qc_qualification.main(["validate-policy"]), 0)
        self.assertIn("PASS", output.getvalue())
        with tempfile.TemporaryDirectory() as directory:
            broken = Path(directory) / "policy.json"
            value = copy.deepcopy(self.committed)
            value["additions"].pop()
            broken.write_text(json.dumps(value), encoding="utf-8")
            with redirect_stderr(StringIO()) as errors:
                self.assertEqual(audio_qc_qualification.main(["validate-policy", "--policy", str(broken)]), 1)
            self.assertIn("A1 through A10", errors.getvalue())
            unreadable = Path(directory) / "missing.json"
            with redirect_stderr(StringIO()):
                self.assertEqual(audio_qc_qualification.main(["validate-policy", "--policy", str(unreadable)]), 1)


if __name__ == "__main__":
    unittest.main()
