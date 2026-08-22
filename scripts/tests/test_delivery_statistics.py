#!/usr/bin/env python3
"""Unit tests for scripts/delivery_statistics.py.

Every routine is checked against a value computed by hand or a property that
must hold regardless of implementation, so a subtle formula error cannot hide
behind plausible-looking output.
"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from delivery_statistics import (
    benjamini_hochberg,
    bootstrap_ci,
    cohens_dz,
    holm_bonferroni,
    paired_bootstrap_delta,
    paired_report,
    required_pairs,
    wilcoxon_signed_rank,
    wilson_interval,
)


class WilcoxonTests(unittest.TestCase):
    def test_exact_statistic_and_p_for_a_hand_checked_sample(self):
        # Ranks of |d| are 1..6; the single negative difference (-1) takes
        # rank 1, so W- = 1 and the statistic is 1.
        result = wilcoxon_signed_rank([2.0, 3.0, 4.0, 5.0, 6.0, -1.0])
        self.assertEqual(result["n"], 6)
        self.assertEqual(result["statistic"], 1.0)
        self.assertEqual(result["method"], "exact")
        # Two-sided exact p for W=1, n=6: 2 * (2/64).
        self.assertAlmostEqual(result["pValue"], 2 * 2 / 64, places=6)

    def test_zero_differences_are_discarded(self):
        result = wilcoxon_signed_rank([0.0, 0.0, 3.0, 4.0, 5.0])
        self.assertEqual(result["n"], 3)

    def test_all_ties_report_no_p_value_rather_than_a_false_one(self):
        result = wilcoxon_signed_rank([0.0, 0.0, 0.0])
        self.assertIsNone(result["pValue"])
        self.assertEqual(result["method"], "undefined")

    def test_tied_magnitudes_fall_back_to_the_corrected_normal_approximation(self):
        result = wilcoxon_signed_rank([2.0, 2.0, 2.0, -2.0, 3.0, 4.0])
        self.assertEqual(result["method"], "normal-approximation")
        self.assertIsNotNone(result["pValue"])

    def test_a_consistent_shift_is_significant_and_noise_is_not(self):
        shifted = wilcoxon_signed_rank([1.1, 1.2, 0.9, 1.3, 1.0, 1.4, 1.2, 0.8])
        self.assertLess(shifted["pValue"], 0.05)
        noise = wilcoxon_signed_rank([1.0, -1.1, 0.9, -0.8, 1.2, -1.3, 0.7, -0.6])
        self.assertGreater(noise["pValue"], 0.05)


class EffectSizeTests(unittest.TestCase):
    def test_cohens_dz_is_mean_over_standard_deviation(self):
        values = [1.0, 2.0, 3.0, 4.0]
        expected = 2.5 / math.sqrt(sum((v - 2.5) ** 2 for v in values) / 3)
        self.assertAlmostEqual(cohens_dz(values), expected, places=9)

    def test_constant_or_single_sample_has_no_defined_effect_size(self):
        self.assertIsNone(cohens_dz([2.0, 2.0, 2.0]))
        self.assertIsNone(cohens_dz([1.0]))

    def test_required_pairs_grows_as_the_effect_shrinks(self):
        large = required_pairs(0.8)
        medium = required_pairs(0.5)
        small = required_pairs(0.2)
        self.assertLess(large, medium)
        self.assertLess(medium, small)
        # Sanity against the standard table: d_z = 0.5 needs about 34 pairs.
        self.assertTrue(30 <= medium <= 40, medium)


class IntervalTests(unittest.TestCase):
    def test_bootstrap_interval_brackets_the_mean_and_is_deterministic(self):
        sample = [1.0, 1.2, 0.8, 1.4, 0.9, 1.1, 1.3, 0.7, 1.0, 1.2]
        first = bootstrap_ci(sample, resamples=2000)
        second = bootstrap_ci(sample, resamples=2000)
        self.assertEqual(first, second)
        self.assertLess(first["lower"], first["mean"])
        self.assertGreater(first["upper"], first["mean"])

    def test_wilson_interval_stays_inside_zero_to_one_at_the_extremes(self):
        perfect = wilson_interval(10, 10)
        self.assertLessEqual(perfect["upper"], 1.0)
        self.assertLess(perfect["lower"], 1.0)
        empty = wilson_interval(0, 10)
        self.assertGreaterEqual(empty["lower"], 0.0)
        self.assertGreater(empty["upper"], 0.0)

    def test_wilson_interval_narrows_as_trials_grow(self):
        few = wilson_interval(8, 10)
        many = wilson_interval(80, 100)
        self.assertLess(many["upper"] - many["lower"], few["upper"] - few["lower"])


class MultipleComparisonTests(unittest.TestCase):
    def test_adjusted_values_are_monotone_and_never_shrink_a_p_value(self):
        p_values = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205]
        results = benjamini_hochberg(p_values, false_discovery_rate=0.10)
        adjusted = [entry["adjusted"] for entry in results]
        self.assertEqual(adjusted, sorted(adjusted))
        for raw, entry in zip(p_values, results):
            self.assertGreaterEqual(entry["adjusted"], raw)

    def test_correction_rejects_a_finding_that_survives_uncorrected(self):
        # One real effect and one borderline hit among 38 nulls. At the usual
        # uncorrected 0.05 the borderline p=0.04 reads as a discovery; across a
        # 40-feature sweep it is what you expect from chance alone, and BH says
        # so. This is the failure mode a wide delivery sweep hits every run.
        p_values = [0.001, 0.04] + [0.5] * 38
        results = benjamini_hochberg(p_values, false_discovery_rate=0.10)
        self.assertTrue(results[0]["significant"])
        self.assertLess(p_values[1], 0.05)
        self.assertFalse(results[1]["significant"])
        self.assertFalse(any(entry["significant"] for entry in results[2:]))

    def test_a_field_of_consistent_small_p_values_is_not_over_corrected(self):
        # BH controls the false-discovery rate, not the family-wise error rate.
        # When most tests genuinely show an effect it must keep them, otherwise
        # a real across-the-board improvement would be discarded.
        results = benjamini_hochberg([0.001] + [0.04] * 39, false_discovery_rate=0.10)
        self.assertTrue(all(entry["significant"] for entry in results))

    def test_missing_p_values_are_passed_through_untouched(self):
        results = benjamini_hochberg([0.01, None, 0.5])
        self.assertIsNone(results[1]["adjusted"])
        self.assertFalse(results[1]["significant"])

    def test_holm_stops_the_family_after_the_first_failed_hypothesis(self):
        results = holm_bonferroni([0.001, 0.03, 0.031, None], alpha=0.05)
        self.assertTrue(results[0]["significant"])
        self.assertFalse(results[1]["significant"])
        self.assertFalse(results[2]["significant"])
        self.assertIsNone(results[3]["adjusted"])

    def test_holm_rejects_invalid_p_values(self):
        with self.assertRaises(ValueError):
            holm_bonferroni([0.01, 1.2])


class PairedReportTests(unittest.TestCase):
    def test_report_carries_significance_effect_interval_and_win_rate(self):
        instructed = [12.0, 13.0, 11.5, 12.5, 13.5, 12.2, 12.8, 13.1]
        neutral = [10.0, 10.5, 10.2, 10.1, 10.4, 10.3, 10.2, 10.6]
        report = paired_report(instructed, neutral, label="pitch_shift_semitones")
        self.assertEqual(report["label"], "pitch_shift_semitones")
        self.assertEqual(report["n"], 8)
        self.assertGreater(report["cohensDz"], 1.0)
        self.assertLess(report["wilcoxon"]["pValue"], 0.05)
        self.assertEqual(report["winRate"]["rate"], 1.0)
        self.assertGreater(report["confidenceInterval"]["lower"], 0.0)

    def test_mismatched_pair_lengths_fail_closed(self):
        with self.assertRaises(ValueError):
            paired_report([1.0, 2.0], [1.0])

    def test_paired_bootstrap_preserves_pairs_and_is_reproducible(self):
        candidate = [1, 1, 1, 0, 1, 1, 0, 1]
        baseline = [0, 0, 1, 0, 0, 1, 0, 0]
        first = paired_bootstrap_delta(candidate, baseline, resamples=2000)
        second = paired_bootstrap_delta(candidate, baseline, resamples=2000)
        self.assertEqual(first, second)
        self.assertGreater(first["meanDifference"], 0)
        self.assertGreaterEqual(first["upper"], first["meanDifference"])


if __name__ == "__main__":
    unittest.main()
