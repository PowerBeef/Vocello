#!/usr/bin/env python3
"""Deterministic tests for the layered delivery evaluator."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from delivery_evaluator import (  # noqa: E402
    EvaluatorError,
    calibrate,
    compose_layers,
    evaluate,
    validate_challenger_layer,
    validate_model,
)


def manifest_digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def labeled_dataset() -> dict:
    rows = []
    index = 0
    for speaker_offset, speaker in ((0.0, "aiden"), (0.1, "vivian"), (-0.1, "sohee")):
        scripts = tuple(f"s{value}" for value in range(1, 9))
        for script_index, script in enumerate(scripts):
            index += 1
            valence = (-0.9, -0.6, -0.3, -0.1, 0.1, 0.3, 0.6, 0.9)[script_index]
            arousal = (0.8, 0.5, 0.2, 0.1, -0.1, -0.2, -0.5, -0.8)[script_index]
            dominance = valence * 0.5 + speaker_offset
            rows.append({
                "generationID": f"g{index}",
                "speakerID": speaker,
                "scriptID": script,
                "features": {
                    "pitchDelta": arousal + speaker_offset,
                    "rateDelta": arousal * 0.7,
                    "tensionDelta": dominance,
                    "brightnessDelta": valence,
                },
                "labels": {
                    "valence": valence,
                    "arousal": arousal,
                    "dominance": dominance,
                },
            })
    return {
        "schemaVersion": 1,
        "manifestDigest": manifest_digest("training"),
        "featureNames": ["pitchDelta", "rateDelta", "tensionDelta", "brightnessDelta"],
        "rows": rows,
        "labelProvenance": {
            "kind": "blinded-independent-listener-median",
            "sourceSplit": "calibration",
            "targetLabelsVisibleToListeners": False,
            "listenerCount": 3,
            "responseDigests": [manifest_digest(value) for value in ("r1", "r2", "r3")],
            "fluentLanguageCoverage": {"English": 3},
            "agreement": {
                dimension: {"pairCount": 3, "meanPairwiseCCC": 0.9}
                for dimension in ("valence", "arousal", "dominance")
            },
            "qualificationFailures": [],
            "calibrationQualified": True,
        },
    }


class DeliveryEvaluatorTests(unittest.TestCase):
    def test_calibration_is_grouped_digest_bound_and_reproducible(self) -> None:
        first = calibrate(labeled_dataset())
        second = calibrate(labeled_dataset())
        self.assertEqual(first, second)
        self.assertEqual(first["outerGroups"], ["aiden", "sohee", "vivian"])
        self.assertEqual(first["innerGroups"], [
            "s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8",
        ])
        for dimension in ("valence", "arousal", "dominance"):
            validation = first["dimensions"][dimension]["validation"]
            self.assertEqual(validation["grouping"], "outer-speaker-inner-script")
            self.assertEqual(len(validation["folds"]), 3)
        self.assertEqual(validate_model(first), first)

    def test_model_tampering_fails_closed(self) -> None:
        model = calibrate(labeled_dataset())
        changed = copy.deepcopy(model)
        changed["dimensions"]["valence"]["intercept"] += 0.1
        with self.assertRaisesRegex(EvaluatorError, "digest mismatch"):
            validate_model(changed)

    def test_requested_target_or_unqualified_labels_cannot_train_model(self) -> None:
        changed = labeled_dataset()
        changed["labelProvenance"]["kind"] = "requested-preset-targets"
        with self.assertRaisesRegex(EvaluatorError, "blinded independent listeners"):
            calibrate(changed)
        changed = labeled_dataset()
        changed["labelProvenance"]["calibrationQualified"] = False
        changed["labelProvenance"]["qualificationFailures"] = ["low-agreement"]
        with self.assertRaisesRegex(EvaluatorError, "not calibration-qualified"):
            calibrate(changed)

    def test_claimed_provenance_cannot_bypass_group_or_agreement_minimums(self) -> None:
        changed = labeled_dataset()
        changed["rows"] = changed["rows"][:12]
        with self.assertRaisesRegex(EvaluatorError, "at least 20"):
            calibrate(changed)
        changed = labeled_dataset()
        changed["labelProvenance"]["agreement"]["valence"]["pairCount"] = 2
        with self.assertRaisesRegex(EvaluatorError, "pair coverage"):
            calibrate(changed)

    def test_evaluation_reports_dimensions_and_abstains_on_extrapolation(self) -> None:
        model = calibrate(labeled_dataset())
        payload = labeled_dataset()
        payload["manifestDigest"] = manifest_digest("holdout")
        payload["rows"] = [copy.deepcopy(payload["rows"][0])]
        payload["rows"][0].pop("labels")
        payload["rows"][0]["generationID"] = "holdout-normal"
        normal = evaluate(payload, model)
        self.assertEqual(normal["rows"][0]["generationID"], "holdout-normal")
        self.assertIn("valence", normal["rows"][0]["dimensions"])

        payload["rows"][0]["generationID"] = "holdout-ood"
        payload["rows"][0]["features"]["brightnessDelta"] = 100.0
        outlier = evaluate(payload, model)["rows"][0]
        self.assertGreater(outlier["maximumAbsoluteFeatureZ"], 3.0)
        self.assertTrue(outlier["dimensions"]["valence"]["abstained"])
        self.assertIn(
            "feature-extrapolation",
            outlier["dimensions"]["valence"]["abstainReasons"],
        )

    def test_layer_composition_preserves_missing_and_disagreement(self) -> None:
        acoustic = {"schemaVersion": 1, "rows": [{"generationID": "g1", "passed": True}]}
        ser = {
            "schemaVersion": 1,
            "rows": [{"generationID": "g1", "topEmotion": "happy", "abstained": False}],
        }
        dimensional = {
            "schemaVersion": 1,
            "rows": [{
                "generationID": "g1",
                "dimensions": {"valence": {"value": -0.5, "abstained": False}},
            }],
        }
        report = compose_layers({"acoustic": acoustic, "ser": ser}, dimensional)
        self.assertEqual(report["rowCount"], 1)
        self.assertEqual(report["disagreementCount"], 1)
        self.assertIn("asr", report["missingAdvisoryLayers"])
        self.assertIn(
            "ser-happy-vs-negative-valence", report["rows"][0]["disagreements"]
        )

    def test_layer_composition_rejects_cross_run_identity(self) -> None:
        acoustic = {"schemaVersion": 1, "rows": [{"generationID": "g1"}]}
        ser = {"schemaVersion": 1, "rows": [{"generationID": "other"}]}
        with self.assertRaisesRegex(EvaluatorError, "cross-run identities"):
            compose_layers({"acoustic": acoustic, "ser": ser}, None)

    def test_challenger_requires_licensed_better_calibrated_offline_model(self) -> None:
        challenger = {
            "schemaVersion": 1,
            "modelProvenance": {
                "modelID": "fixture/challenger",
                "sourceRevision": "a" * 40,
                "weightsSHA256": "b" * 64,
                "license": "Apache-2.0",
                "commercialUseCompatible": True,
                "trainingDataDeclaration": "fixture-declared-corpus",
                "labelMapDigest": "c" * 64,
                "baselineHoldoutCalibrationError": 0.4,
                "challengerHoldoutCalibrationError": 0.3,
                "peakRSSBytes": 1_000_000,
                "eightGigabyteHostCompatible": True,
                "offlineAfterAcquisition": True,
                "sequentialMemoryReleased": True,
            },
            "rows": [{"generationID": "g1", "valence": 0.25}],
        }
        self.assertEqual(validate_challenger_layer(challenger), challenger)
        acoustic = {"schemaVersion": 1, "rows": [{"generationID": "g1"}]}
        composed = compose_layers({"acoustic": acoustic, "challenger": challenger}, None)
        self.assertEqual(
            composed["challengerProvenance"]["weightsSHA256"], "b" * 64
        )

        incompatible = copy.deepcopy(challenger)
        incompatible["modelProvenance"]["commercialUseCompatible"] = False
        with self.assertRaisesRegex(EvaluatorError, "commercially compatible"):
            validate_challenger_layer(incompatible)

        worse = copy.deepcopy(challenger)
        worse["modelProvenance"]["challengerHoldoutCalibrationError"] = 0.5
        with self.assertRaisesRegex(EvaluatorError, "does not improve"):
            validate_challenger_layer(worse)


if __name__ == "__main__":
    unittest.main()
