#!/usr/bin/env python3
"""Unit tests for scripts/delivery_separability.py.

The verdict consumes already-computed paired feature vectors, so these tests
need no audio: they build synthetic feature matrices with known geometry and
assert the classifier reports it honestly.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from delivery_separability import (
    ANALYSIS_FAILURE_FLAGS,
    SEPARABILITY_ALGORITHM_VERSION,
    evaluate_separability,
    records_from_sidecar,
)
from prosody_profile import builtin_profile


def record(preset, seed, first, second, intensity="normal", **extra):
    features = {"feature_a": first, "feature_b": second}
    features.update(extra)
    return {"preset": preset, "intensity": intensity, "seed": str(seed), "features": features}


def cohort(offsets, seeds=8, jitter=0.05):
    """Two features per cell, centred at the given offsets with tiny wobble."""
    records = []
    for preset, (centre_a, centre_b) in offsets.items():
        for seed in range(seeds):
            wobble = jitter * ((seed % 3) - 1)
            records.append(record(preset, seed, centre_a + wobble, centre_b - wobble))
    return records


class SeparabilityTests(unittest.TestCase):
    def test_well_separated_cells_are_recognised(self):
        verdict = evaluate_separability(cohort({"alpha": (0.0, 0.0), "beta": (12.0, 12.0)}))
        self.assertTrue(verdict["passed"], verdict["reason"])
        self.assertEqual(verdict["metrics"]["uar"], 1.0)
        self.assertEqual(verdict["algorithmVersion"], SEPARABILITY_ALGORITHM_VERSION)

    def test_overlapping_cells_are_flagged_not_silently_passed(self):
        # Two presets requesting different deliveries that land in the same
        # acoustic place: each may satisfy its own direction check while being
        # mutually indistinguishable, which is the failure this gate exists for.
        verdict = evaluate_separability(
            cohort({"alpha": (0.0, 0.0), "beta": (0.02, 0.02)}, jitter=1.0)
        )
        self.assertFalse(verdict["passed"])
        self.assertTrue(
            any(flag.startswith("separability_confusion_") for flag in verdict["flags"]),
            verdict["flags"],
        )
        self.assertNotIn("separability_underpowered", verdict["flags"])

    def test_underpowered_fit_is_refused_rather_than_reported(self):
        # More features than the pooled covariance has degrees of freedom: the
        # ridge would still return a number, and that number would be read as a
        # product finding. Refuse instead.
        records = []
        for preset in ("alpha", "beta"):
            for seed in range(2):
                extras = {f"feature_{index}": float(index + seed) for index in range(10)}
                records.append(record(preset, seed, 0.0, 1.0, **extras))
        verdict = evaluate_separability(records)
        self.assertFalse(verdict["passed"])
        self.assertEqual(verdict["flags"], ["separability_underpowered"])
        self.assertIn("separability_underpowered", ANALYSIS_FAILURE_FLAGS)
        self.assertGreater(verdict["metrics"]["minimumTakesForFit"], verdict["metrics"]["takeCount"])

    def test_single_cell_or_single_seed_cannot_be_scored(self):
        one_cell = evaluate_separability(cohort({"alpha": (0.0, 0.0)}))
        self.assertEqual(one_cell["flags"], ["insufficient_cells"])
        one_seed = evaluate_separability([
            record("alpha", 1, 0.0, 0.0), record("beta", 1, 5.0, 5.0),
        ])
        self.assertEqual(one_seed["flags"], ["insufficient_seeds"])

    def test_features_missing_from_any_take_are_dropped_not_imputed(self):
        # Analyzer-v2 rows carry no voice-quality block. Substituting zeros
        # would manufacture separation the audio does not contain.
        records = cohort({"alpha": (0.0, 0.0), "beta": (9.0, 9.0)})
        for index, entry in enumerate(records):
            if index % 2 == 0:
                entry["features"]["voice_only_on_some"] = 1.0
        verdict = evaluate_separability(records)
        self.assertNotIn("voice_only_on_some", verdict["metrics"]["features"])
        self.assertEqual(verdict["metrics"]["featureCount"], 2)

    def test_intensity_collapse_is_detected(self):
        # Normal tier spreads the presets apart; strong tier piles them together.
        offsets = {
            "alpha": (0.0, 0.0), "beta": (10.0, 0.0), "gamma": (0.0, 10.0),
        }
        records = cohort(offsets)
        for entry in records:
            entry["intensity"] = "normal"
        collapsed = cohort({"alpha": (30.0, 30.0), "beta": (30.2, 30.1), "gamma": (30.1, 30.2)})
        for entry in collapsed:
            entry["intensity"] = "strong"
            entry["seed"] = f"s{entry['seed']}"
        verdict = evaluate_separability(records + collapsed, label_mode="cell")
        self.assertIn("separability_intensity_collapse", verdict["flags"])
        self.assertLess(
            verdict["metrics"]["strongMeanPairDistance"],
            verdict["metrics"]["normalMeanPairDistance"],
        )

    def test_preset_label_mode_pools_intensities(self):
        records = cohort({"alpha": (0.0, 0.0), "beta": (9.0, 9.0)})
        for index, entry in enumerate(records):
            entry["intensity"] = "strong" if index % 2 else "normal"
        pooled = evaluate_separability(records, label_mode="preset")
        self.assertEqual(pooled["metrics"]["cellCount"], 2)
        self.assertEqual(sorted(pooled["cells"]), ["alpha", "beta"])

    def test_verdict_is_deterministic(self):
        records = cohort({"alpha": (0.0, 0.0), "beta": (4.0, 4.0)}, jitter=0.4)
        first = evaluate_separability(records, builtin_profile())
        second = evaluate_separability(records, builtin_profile())
        self.assertEqual(first, second)

    def test_sidecar_rows_become_records(self):
        rows = [
            {
                "delivery": "angry.strong",
                "generationID": "gen-1",
                "deliveryGate": {
                    "preset": "angry", "intensity": "strong",
                    "metrics": {"arousal_score": 2.0, "pitch_shift_semitones": 3.0},
                },
            },
            {"delivery": "happy.normal", "generationID": "gen-2", "deliveryGate": {}},
        ]
        records = records_from_sidecar(rows)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["preset"], "angry")
        self.assertEqual(records[0]["intensity"], "strong")
        self.assertEqual(records[0]["seed"], "gen-1")


if __name__ == "__main__":
    unittest.main()
