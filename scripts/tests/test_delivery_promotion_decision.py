#!/usr/bin/env python3
"""Tests for the delivery candidate promotion decision."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from delivery_promotion_decision import DecisionError, PRESETS, decide  # noqa: E402


def passing_fixture() -> dict:
    paired = []
    for preset_index, preset in enumerate(PRESETS):
        for index in range(40):
            paired.append({
                "pairID": f"{preset}-{index}", "preset": preset,
                "speakerID": f"speaker-{index % 4}",
                "scriptID": f"script-{index % 4}",
                "baselineCorrect": 0 if index < 20 else 1,
                "candidateCorrect": 1 if index < 32 else 0,
            })
    two_afc = [
        {"preset": preset, "correct": index < 36}
        for preset in PRESETS for index in range(40)
    ]
    return {
        "schemaVersion": 1, "candidateFamily": "fixture",
        "pairedIdentification": paired,
        "instructedVersusNeutral2AFC": two_afc,
        "automaticGuardrails": {
            "newHardAudioQCFailures": 0, "werCERAbsoluteDelta": 0.0,
            "medianSpeakerSimilarityDelta": 0.0, "relativeUTMOSDelta": 0.0,
        },
        "runtimeInvariants": {
            "memoryQualified": True, "cancellationValid": True,
            "seedIdentityValid": True, "instructionReceiptsValid": True,
        },
        "listenerAuthority": {
            "independentListenerCount": 3,
            "allOutputLanguagesFluentlyCovered": True,
            "holdoutOpenedOnce": True,
        },
    }


class DeliveryPromotionDecisionTests(unittest.TestCase):
    def test_complete_candidate_qualifies(self) -> None:
        report = decide(passing_fixture())
        self.assertEqual(report["verdict"], "qualifies")
        self.assertGreater(report["listenerIdentificationImprovement"]["lower"], 0)
        self.assertTrue(report["speakerBalance"]["distributed"])

    def test_automatic_regression_rejects(self) -> None:
        fixture = passing_fixture()
        fixture["automaticGuardrails"]["relativeUTMOSDelta"] = -0.11
        report = decide(fixture)
        self.assertEqual(report["verdict"], "does-not-qualify")
        self.assertIn("automatic-guardrail:relativeUTMOSDelta", report["failures"])

    def test_single_speaker_gain_rejects_as_concentrated(self) -> None:
        fixture = passing_fixture()
        for row in fixture["pairedIdentification"]:
            if row["speakerID"] != "speaker-0":
                row["candidateCorrect"] = row["baselineCorrect"]
        report = decide(fixture)
        self.assertIn("improvement-not-distributed-across-speakers", report["failures"])

    def test_duplicate_pair_identity_fails_closed(self) -> None:
        fixture = passing_fixture()
        fixture["pairedIdentification"][1]["pairID"] = fixture["pairedIdentification"][0]["pairID"]
        with self.assertRaisesRegex(DecisionError, "pair IDs"):
            decide(fixture)


if __name__ == "__main__":
    unittest.main()
