#!/usr/bin/env python3
"""Tests for the delivery candidate promotion decision."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from delivery_promotion_decision import DecisionError, PRESETS, decide  # noqa: E402
import copy
import hashlib


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
    def automated_fixture(self):
        payload = passing_fixture()
        payload['schemaVersion'] = 2
        del payload['listenerAuthority']
        payload['automatedAuthority'] = {
            **{key: 'a' * 64 for key in ('protocolSHA256', 'holdoutManifestSHA256', 'evaluationSourceSHA256')},
            **{key: True for key in ('holdoutOpenedOnce', 'metricFrozenBeforeHoldout', 'blindExtraction',
                                    'completePlannedCoverage', 'independentReferenceQualification')},
            'metricID': 'fixture-acoustic-target-identification',
        }
        for row in payload['pairedIdentification']:
            row['independentJudges'] = [
                {'family': family, 'modelSHA256': hashlib.sha256(family.encode()).hexdigest(),
                 'evidenceSHA256': hashlib.sha256(f'{family}-{row["pairID"]}'.encode()).hexdigest(),
                 'orderReversalConsistent': True,
                 **{key: row[key] for key in ('candidateCorrect', 'baselineCorrect')}}
                for family in ('fixture-one', 'fixture-two')]
        for row, paired in zip(payload['instructedVersusNeutral2AFC'], payload['pairedIdentification']):
            row.update(pairID=paired['pairID'], orderReversalConsistent=True)
        return payload

    def test_automated_qualification_is_scoped_without_listener_authority(self):
        result = decide(self.automated_fixture())
        self.assertEqual(result['verdict'], 'qualifies')
        self.assertFalse(result['humanListeningRequired'])
        self.assertFalse(result['publicationAuthorized'])
        self.assertEqual(result['claimScope'], 'measured-automatic-metric-improvement')
        self.assertNotIn('listenerIdentificationImprovement', result)

    def test_automated_review_rejects_missing_drifted_biased_or_dependent_evidence(self):
        original = self.automated_fixture()
        for key in original['automatedAuthority']:
            payload = copy.deepcopy(original)
            del payload['automatedAuthority'][key]
            with self.assertRaises(DecisionError):
                decide(payload)
        for field, value in (('modelSHA256', 'missing'), ('evidenceSHA256', None),
                             ('orderReversalConsistent', False), ('candidateCorrect', False),
                             ('family', 'fixture-one')):
            payload = copy.deepcopy(original)
            payload['pairedIdentification'][0]['independentJudges'][1][field] = value
            with self.assertRaises(DecisionError):
                decide(payload)
        for key, value in (('newHardAudioQCFailures', 1), ('werCERAbsoluteDelta', .011),
                           ('medianSpeakerSimilarityDelta', -.021), ('relativeUTMOSDelta', -.101)):
            payload = copy.deepcopy(original)
            payload['automaticGuardrails'][key] = value
            self.assertEqual(decide(payload)['verdict'], 'does-not-qualify')
        payload = copy.deepcopy(original)
        payload['instructedVersusNeutral2AFC'][1] = payload['instructedVersusNeutral2AFC'][0]
        with self.assertRaisesRegex(DecisionError, 'unique planned pairs'):
            decide(payload)

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
