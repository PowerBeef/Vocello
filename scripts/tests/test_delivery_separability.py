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
        for offset, preset in enumerate(("alpha", "beta")):
            for seed in range(2):
                extras = {
                    f"feature_{index}": float(index + seed + 3 * offset) for index in range(10)
                }
                records.append(record(preset, seed, float(offset), 1.0 + offset, **extras))
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

    def test_cells_naming_the_same_request_are_collapsed_and_reported(self):
        # `neutral` forces its intensity to nil, so neutral.normal and
        # neutral.strong carry identical instruction text and produce identical
        # audio at a fixed seed. Scoring both guarantees mutual confusion for a
        # reason that has nothing to do with delivery.
        base = cohort({"alpha": (0.0, 0.0), "beta": (9.0, 9.0)})
        alias = [dict(entry, intensity="strong") for entry in base if entry["preset"] == "alpha"]
        verdict = evaluate_separability(base + alias, label_mode="cell")
        self.assertIn("aliasedCells", verdict["metrics"])
        self.assertEqual(verdict["metrics"]["aliasedCells"], {"alpha.strong": "alpha.normal"})
        self.assertEqual(verdict["metrics"]["cellCount"], 2)

    def test_a_single_coincidental_match_is_not_treated_as_an_alias(self):
        # One shared seed agreeing is not evidence two cells are the same
        # request; only agreement across seeds is.
        records = [
            record("alpha", 1, 0.0, 0.0), record("beta", 1, 0.0, 0.0),
            record("alpha", 2, 1.0, 1.0), record("beta", 2, 5.0, 5.0),
            record("alpha", 3, 1.2, 1.1), record("beta", 3, 5.2, 5.1),
        ]
        verdict = evaluate_separability(records, label_mode="cell")
        self.assertNotIn("aliasedCells", verdict["metrics"])

    def test_a_constant_feature_cannot_manufacture_separation(self):
        # intensity_factor is the profile's own scaling constant echoed into the
        # gate metrics; a constant that tracks the label would read as signal.
        records = cohort({"alpha": (0.0, 0.0), "beta": (9.0, 9.0)})
        for entry in records:
            entry["features"]["intensity_factor"] = 1.0 if entry["preset"] == "alpha" else 1.15
            entry["features"]["always_the_same"] = 7.0
        verdict = evaluate_separability(records)
        self.assertNotIn("intensity_factor", verdict["metrics"]["features"])
        self.assertNotIn("always_the_same", verdict["metrics"]["features"])

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

    def test_sidecar_rows_prefer_the_real_seed(self):
        # Since the bench echoes engine provenance, rows carry the actual run
        # seed. The generationID fallback degenerates fold grouping and is
        # kept only for pre-provenance sidecars.
        rows = [
            {
                "delivery": "angry.strong",
                "generationID": "gen-1",
                "seed": 9320,
                "deliveryGate": {
                    "preset": "angry", "intensity": "strong",
                    "metrics": {"arousal_score": 2.0},
                },
            },
        ]
        self.assertEqual(records_from_sidecar(rows)[0]["seed"], 9320)

    def test_chance_floor_is_computed_never_hand_stated(self):
        verdict = evaluate_separability(cohort({"alpha": (0.0, 0.0), "beta": (12.0, 12.0)}))
        self.assertEqual(verdict["metrics"]["chanceFloor"], 0.5)
        # A cleanly recognised cell clears chance on the interval, not just
        # the point estimate.
        self.assertTrue(all(entry["aboveChance"] for entry in verdict["cells"].values()))
        self.assertFalse(any(entry["belowChance"] for entry in verdict["cells"].values()))

    def test_below_chance_requires_the_whole_interval_under_the_floor(self):
        # 1 of 18 against a 0.100 floor was the retired DP-10 misreading: the
        # Wilson interval [~0.01, ~0.26] contains the floor, so the criterion
        # must refuse the "below chance" claim.
        from delivery_separability import _wilson_bounds

        low, high = _wilson_bounds(1, 18)
        self.assertLess(low, 0.100)
        self.assertGreater(high, 0.100)
        # 0 of 40 against a 0.5 floor genuinely is below chance.
        low_zero, high_zero = _wilson_bounds(0, 40)
        self.assertLess(high_zero, 0.5)

    def test_permutation_null_separates_signal_from_noise(self):
        separable = evaluate_separability(
            cohort({"alpha": (0.0, 0.0), "beta": (12.0, 12.0)}), null_iterations=30
        )
        permutation = separable["metrics"]["permutation"]
        self.assertEqual(permutation["iterations"], 30)
        self.assertLess(permutation["pValueUAR"], 0.05)
        self.assertGreater(permutation["nullMeanUAR"], 0.2)
        self.assertLess(permutation["nullMeanUAR"], 0.8)

        # Label-uninformative data: swap the labels on odd seeds so each
        # labeled cell mixes both true clusters. The observed UAR collapses
        # and the permutation p-value must refuse significance.
        shuffled = cohort({"alpha": (0.0, 0.0), "beta": (12.0, 12.0)})
        for entry in shuffled:
            if int(entry["seed"]) % 2 == 1:
                entry["preset"] = "beta" if entry["preset"] == "alpha" else "alpha"
        noise = evaluate_separability(shuffled, null_iterations=30)
        self.assertGreater(noise["metrics"]["permutation"]["pValueUAR"], 0.2)

    def test_permutation_null_is_deterministic(self):
        records = cohort({"alpha": (0.0, 0.0), "beta": (4.0, 4.0)}, jitter=0.4)
        first = evaluate_separability(records, null_iterations=20)
        second = evaluate_separability(records, null_iterations=20)
        self.assertEqual(first["metrics"]["permutation"], second["metrics"]["permutation"])

    def test_unique_per_take_seeds_are_reported_as_degenerate_folds(self):
        # The historic sidecar fallback used per-take generation IDs as the
        # fold key, silently voiding the seed-grouped CV guarantee. That must
        # now be loud.
        records = []
        for index, preset in enumerate(("alpha", "beta")):
            for seed in range(8):
                records.append(
                    record(preset, f"unique-{preset}-{seed}", 12.0 * index, 12.0 * index)
                )
        verdict = evaluate_separability(records)
        self.assertIn("separability_degenerate_folds", verdict["flags"])
        self.assertEqual(verdict["metrics"]["foldGrouping"], "leave-one-take-out")

        grouped = evaluate_separability(cohort({"alpha": (0.0, 0.0), "beta": (12.0, 12.0)}))
        self.assertEqual(grouped["metrics"]["foldGrouping"], "seed-grouped")
        self.assertNotIn("separability_degenerate_folds", grouped["flags"])

    def test_designation_defaults_exploratory_and_rejects_unknown(self):
        records = cohort({"alpha": (0.0, 0.0), "beta": (12.0, 12.0)})
        self.assertEqual(evaluate_separability(records)["designation"], "exploratory")
        confirmed = evaluate_separability(records, designation="confirmatory")
        self.assertEqual(confirmed["designation"], "confirmatory")
        with self.assertRaises(ValueError):
            evaluate_separability(records, designation="canonical")


if __name__ == "__main__":
    unittest.main()


class FdrTests(unittest.TestCase):
    """DP-18 (audit R4): per-cell above-chance claims are a family of tests."""

    def test_benjamini_hochberg_matches_hand_computation(self):
        from delivery_separability import benjamini_hochberg
        # Classic worked example: p = [0.01, 0.02, 0.03, 0.04] at m=4 gives
        # q = [0.04, 0.04, 0.04, 0.04]; a lone large p stays its own q.
        self.assertEqual(benjamini_hochberg([0.01, 0.02, 0.03, 0.04]), [0.04, 0.04, 0.04, 0.04])
        q = benjamini_hochberg([0.001, 0.8])
        self.assertAlmostEqual(q[0], 0.002)
        self.assertAlmostEqual(q[1], 0.8)
        self.assertEqual(benjamini_hochberg([]), [])

    def test_exact_binomial_tail_is_exact(self):
        from delivery_separability import _binomial_at_least_p
        # P(X >= 1 | n=2, p=0.5) = 0.75; P(X >= 0) = 1; empty trials fail safe.
        self.assertAlmostEqual(_binomial_at_least_p(1, 2, 0.5), 0.75)
        self.assertAlmostEqual(_binomial_at_least_p(0, 2, 0.5), 1.0)
        self.assertEqual(_binomial_at_least_p(1, 0, 0.5), 1.0)

    def test_verdict_carries_q_values_and_fdr_flags(self):
        verdict = evaluate_separability(
            cohort({"alpha": (0.0, 0.0), "beta": (12.0, 12.0), "gamma": (24.0, 24.0)})
        )
        for cell, stats in verdict["cells"].items():
            self.assertIn("aboveChanceP", stats, cell)
            self.assertIn("aboveChanceQ", stats, cell)
            self.assertIn("aboveChanceFdr05", stats, cell)
            # Perfectly separated cells at 8 seeds vs a 1/3 floor survive FDR.
            self.assertTrue(stats["aboveChanceFdr05"], (cell, stats))
            self.assertLessEqual(stats["aboveChanceP"], stats["aboveChanceQ"] + 1e-9)

    def test_chance_level_cells_do_not_survive_fdr(self):
        # Features are deterministic pseudo-noise uncorrelated with the label:
        # whatever the discriminant memorizes in train folds cannot transfer,
        # so held-out recall sits at chance and no cell may clear FDR.
        import math as _math
        records = []
        for index, preset in enumerate(("alpha", "beta")):
            for seed in range(8):
                noise_a = _math.sin(12.9898 * (seed * 2 + index) + 78.233)
                noise_b = _math.sin(39.3468 * (seed * 2 + index) + 11.135)
                records.append(record(preset, seed, noise_a, noise_b))
        verdict = evaluate_separability(records)
        survivors = [
            cell for cell, stats in verdict["cells"].items()
            if stats.get("aboveChanceFdr05")
        ]
        self.assertEqual(survivors, [], verdict["cells"])
