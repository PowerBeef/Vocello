#!/usr/bin/env python3
"""Deterministic tests for the compact perceptual delivery evaluator v2."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from delivery_evaluator import EvaluatorError, digest  # noqa: E402
from delivery_evaluator_v2 import (  # noqa: E402
    BLOCK_AXES,
    attach_compact_features,
    calibrate_v2,
    compare_untouched_holdout,
    evaluate_v2,
    load_v2_dataset,
    score_untouched_holdout,
    validate_v2_contract,
)


PRESETS = ("neutral", "happy", "sad", "angry", "fearful", "surprised", "calm", "whisper")
TARGETS = {
    "neutral": (0.0, 0.0, 0.0), "happy": (0.8, 0.6, 0.3),
    "sad": (-0.7, -0.5, -0.4), "angry": (-0.7, 0.8, 0.7),
    "fearful": (-0.7, 0.7, -0.7), "surprised": (0.2, 0.9, 0.0),
    "calm": (0.3, -0.8, 0.1), "whisper": (0.0, -0.6, -0.4),
}


def fixture_dataset() -> dict:
    rows = []
    for index in range(96):
        preset = PRESETS[index % len(PRESETS)]
        valence, arousal, dominance = TARGETS[preset]
        wobble = ((index // 8) % 3 - 1) * 0.03
        rows.append({
            "generationID": f"generation-{index}",
            "speakerID": f"speaker-{index % 6}",
            "scriptID": f"script-{(index // 8) % 4}",
            "scriptTranslationGroup": f"translation-{(index // 8) % 4}",
            "seed": 41000000 + index,
            "outputLanguage": ("English", "Chinese", "Japanese")[index % 3],
            "preset": preset,
            "features": {
                "pitch": arousal + wobble,
                "energy": dominance + wobble,
                "brightness": valence + wobble,
                "pause": -arousal + wobble,
            },
            "temporalDeltaV1": {
                "derivedContours": {
                    "rise": arousal + 0.5 * valence + wobble,
                    "release": -dominance + wobble,
                }
            },
            "labels": {
                "valence": valence + wobble,
                "arousal": arousal + wobble,
                "dominance": dominance + wobble,
            },
            "targetPreference": 0.8 if (index // 8) % 2 == 0 else 0.2,
        })
    return {
        "schemaVersion": 2,
        "manifestDigest": hashlib.sha256(b"v2-fixture").hexdigest(),
        "rows": rows,
        "labelProvenance": {
            "kind": "blinded-independent-listener-perceptual-v2",
            "sourceSplit": "calibration",
            "targetLabelsVisibleToDimensionalListeners": False,
            "calibrationQualified": True,
            "qualificationFailures": [],
        },
    }


class DeliveryEvaluatorV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dataset = fixture_dataset()
        cls.model = calibrate_v2(cls.dataset)

    def test_feature_extraction_cannot_consume_requested_labels(self) -> None:
        features, _rows = load_v2_dataset(self.dataset, require_labels=True)
        self.assertFalse(any("preset" in feature.lower() for feature in features))
        self.assertFalse(any("label" in feature.lower() for feature in features))

    def test_ridge_is_preserved_and_all_block_axes_are_fold_local(self) -> None:
        self.assertEqual(self.model["baseline"], "ridge-v1")
        self.assertEqual(self.model["adoptedDimensionalModel"], "ridge-v1")
        validation = self.model["dimensionalModels"]["elastic-net-v2"]["valence"]["validation"]
        self.assertEqual(set(validation["axes"]), set(BLOCK_AXES))
        self.assertTrue(validation["foldLocalReduction"])
        self.assertTrue(all(
            fold["heldOutGroupCount"] >= 1
            for axis in validation["axes"].values() for fold in axis["folds"]
        ))
        self.assertTrue(all(
            head["validation"]["foldLocalReduction"]
            and set(head["validation"]["axes"]) == set(BLOCK_AXES)
            for head in self.model["pairwiseHeads"].values()
            if head["status"] == "calibrated"
        ))

    def test_evaluation_emits_conformal_ood_and_typed_contradiction(self) -> None:
        angry = next(row for row in self.dataset["rows"] if row["preset"] == "angry")
        row = copy.deepcopy(angry)
        row["generationID"] = "contradiction"
        row["preset"] = "happy"
        row.pop("labels")
        row.pop("targetPreference")
        payload = {
            "schemaVersion": 2,
            "manifestDigest": hashlib.sha256(b"evaluation").hexdigest(),
            "rows": [row],
        }
        result = evaluate_v2(payload, self.model)
        report = result["rows"][0]
        self.assertIn("interval90", report["dimensions"]["valence"])
        self.assertIn("happy-negative-valence", report["contradictions"])
        self.assertIn("typed-contradiction", report["abstainReasons"])

    def test_pairwise_head_uses_its_preset_local_training_transform(self) -> None:
        row = copy.deepcopy(next(row for row in self.dataset["rows"] if row["preset"] == "happy"))
        row["generationID"] = "pairwise-transform"
        row.pop("labels")
        row.pop("targetPreference")
        payload = {
            "schemaVersion": 2,
            "manifestDigest": hashlib.sha256(b"pairwise-transform").hexdigest(),
            "rows": [row],
        }
        report = evaluate_v2(payload, self.model)["rows"][0]
        head = self.model["pairwiseHeads"]["happy"]
        features, normalized = load_v2_dataset(payload, require_labels=False)
        values = normalized[0]["features"]
        score = head["intercept"]
        for feature in features:
            standardized = (
                values[feature] - head["featureMeans"][feature]
            ) / head["featureScales"][feature]
            score += standardized * head["coefficients"][feature]
        expected = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, score))))
        self.assertAlmostEqual(
            report["pairwise"]["targetAlignedProbability"], expected, places=12
        )

    def test_challenger_needs_untouched_nonregressing_gain(self) -> None:
        baseline = {
            "overallCalibrationError": 0.4,
            "dimensions": {"valence": 0.4, "arousal": 0.4, "dominance": 0.4},
            "presets": {preset: 0.4 for preset in PRESETS},
            "speakers": {f"speaker-{index}": 0.4 for index in range(6)},
            "scriptGroups": {f"translation-{index}": 0.4 for index in range(4)},
        }
        challenger = copy.deepcopy(baseline)
        challenger["overallCalibrationError"] = 0.3
        challenger["dimensions"] = {name: 0.3 for name in ("valence", "arousal", "dominance")}
        challenger["presets"] = {preset: 0.3 for preset in PRESETS}
        challenger["speakers"] = {name: 0.3 for name in baseline["speakers"]}
        challenger["scriptGroups"] = {name: 0.3 for name in baseline["scriptGroups"]}
        score_report = {
            "schemaVersion": 2,
            "kind": "delivery-evaluator-v2-untouched-holdout-scores",
            "designation": "untouched-confirmation",
            "promotionAuthority": False,
            "preselectedChallenger": "elastic-net-v2",
            "models": {"ridge-v1": baseline, "elastic-net-v2": challenger},
        }
        score_report["scoreDigest"] = digest(score_report)
        result = compare_untouched_holdout(score_report)
        self.assertTrue(result["challengerAdvances"])
        challenger["dimensions"]["valence"] = 0.5
        score_report["models"]["elastic-net-v2"] = challenger
        score_report["scoreDigest"] = digest({
            key: value for key, value in score_report.items() if key != "scoreDigest"
        })
        result = compare_untouched_holdout(score_report)
        self.assertFalse(result["challengerAdvances"])
        self.assertIn("vad-valence", result["regressions"])
        with self.assertRaisesRegex(EvaluatorError, "untouched"):
            compare_untouched_holdout({
                "designation": "development", "baseline": baseline, "challenger": challenger,
            })

    def test_blind_compact_attachment_and_holdout_scoring(self) -> None:
        cascade = {
            "schemaVersion": 1,
            "kind": "local-delivery-cascade",
            "inputManifestDigest": "a" * 64,
            "rows": [{
                "generationID": row["generationID"],
                "alwaysLayers": {"compactRepresentation": {
                    "schemaVersion": 1,
                    "kind": "compact-instructed-minus-neutral-delta",
                    "adapterID": "distilhubert",
                    "weightsSHA256": "b" * 64,
                    "featureVector": {"embedding.000": row["features"]["pitch"]},
                }},
            } for row in self.dataset["rows"]],
        }
        attached = attach_compact_features(self.dataset, cascade)
        features, _rows = load_v2_dataset(attached, require_labels=True)
        self.assertIn("compact.embedding.000", features)
        self.assertEqual(
            [row["labels"] for row in attached["rows"]],
            [row["labels"] for row in self.dataset["rows"]],
        )
        model = calibrate_v2(attached)
        self.assertIsNone(model["preselectedChallenger"])
        model["preselectedChallenger"] = "elastic-net-v2"
        model["challengerAdoptionStatus"] = "preselected-awaiting-untouched-human-holdout"
        model["modelDigest"] = digest({
            key: value for key, value in model.items() if key != "modelDigest"
        })
        holdout = copy.deepcopy(attached)
        holdout["labelProvenance"]["sourceSplit"] = "confirmation"
        holdout["manifestDigest"] = hashlib.sha256(b"untouched-holdout").hexdigest()
        scores = score_untouched_holdout(holdout, model)
        self.assertEqual(set(scores["models"]), {"ridge-v1", "elastic-net-v2"})
        self.assertEqual(set(scores["models"]["ridge-v1"]), {
            "overallCalibrationError", "dimensions", "presets", "speakers", "scriptGroups",
        })

    def test_holdout_cannot_open_without_calibration_preselection(self) -> None:
        holdout = copy.deepcopy(self.dataset)
        holdout["labelProvenance"]["sourceSplit"] = "confirmation"
        with self.assertRaisesRegex(EvaluatorError, "no calibration-selected challenger"):
            score_untouched_holdout(holdout, self.model)

    def test_compact_attachment_rejects_cross_run_coverage(self) -> None:
        with self.assertRaisesRegex(EvaluatorError, "coverage"):
            attach_compact_features(self.dataset, {
                "schemaVersion": 1, "kind": "local-delivery-cascade", "rows": [],
            })

    def test_contract_preserves_research_and_human_authority_boundaries(self) -> None:
        root = Path(__file__).resolve().parents[2]
        contract = json.loads(
            (root / "config/delivery-evaluator-v2-contract.json").read_text(encoding="utf-8")
        )
        self.assertIs(validate_v2_contract(contract), contract)
        adopted = copy.deepcopy(contract)
        adopted["compactAdapters"]["adopted"] = ["sensevoice-small-q8"]
        with self.assertRaisesRegex(EvaluatorError, "no compact model"):
            validate_v2_contract(adopted)
        authority = copy.deepcopy(contract)
        authority["promotion"]["automaticLayersMayPromoteSemanticDelivery"] = True
        with self.assertRaisesRegex(EvaluatorError, "cannot gain"):
            validate_v2_contract(authority)


if __name__ == "__main__":
    unittest.main()
