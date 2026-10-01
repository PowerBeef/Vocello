#!/usr/bin/env python3
"""Unit tests for scripts/lib/basic_stats.py.

Every routine is checked against a value computed by hand or a property that
must hold regardless of implementation, so a subtle formula error cannot hide
behind plausible-looking output.
"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.basic_stats import (
    bootstrap_ci,
    cohens_dz,
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


if __name__ == "__main__":
    unittest.main()
