#!/usr/bin/env python3
"""Unit tests for scripts/separability_listening_check.py."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from separability_listening_check import (
    IDENTITY_CONTROL_MAX_RATING,
    evaluate_listening,
    spearman,
)


def key(entries):
    """entries: (id, bucket, distance) -> pair manifest rows."""
    return [
        {"id": pair_id, "bucket": bucket, "a": f"{pair_id}_a", "b": f"{pair_id}_b",
         "distance": distance}
        for pair_id, bucket, distance in entries
    ]


CLEAN_KEY = key([
    ("p01", "close", 0.9), ("p02", "close", 1.0), ("p03", "close", 1.1),
    ("p04", "mid", 2.2), ("p05", "mid", 2.4), ("p06", "mid", 2.6),
    ("p07", "far", 3.6), ("p08", "far", 3.9), ("p09", "far", 4.2),
    ("c01", "identity", 0.0),
])


class SpearmanTests(unittest.TestCase):
    def test_perfect_agreement_and_perfect_inversion(self):
        self.assertAlmostEqual(spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)
        self.assertAlmostEqual(spearman([1, 2, 3, 4], [40, 30, 20, 10]), -1.0)

    def test_ties_share_average_rank(self):
        self.assertIsNotNone(spearman([1, 1, 2, 3], [5, 5, 6, 7]))

    def test_undefined_for_tiny_or_constant_input(self):
        self.assertIsNone(spearman([1, 2], [1, 2]))
        self.assertIsNone(spearman([1, 1, 1], [1, 2, 3]))


class ListeningCheckTests(unittest.TestCase):
    def test_an_ear_that_tracks_the_metric_makes_it_trustworthy(self):
        ratings = {"p01": 1, "p02": 1, "p03": 2, "p04": 2, "p05": 3,
                   "p06": 3, "p07": 4, "p08": 4, "p09": 4, "c01": 1}
        report = evaluate_listening(CLEAN_KEY, ratings)
        self.assertEqual(report["verdict"], "metric_tracks_perception")
        self.assertTrue(report["trustworthy"])
        self.assertGreater(report["spearman"], 0.8)
        self.assertTrue(report["bucketsOrderedCorrectly"])

    def test_an_ear_that_contradicts_the_metric_withholds_trust(self):
        # The listener hears the "clearly distinct" pairs as identical and the
        # "interchangeable" ones as different emotions: the metric is measuring
        # something, but not what a listener hears.
        ratings = {"p01": 4, "p02": 4, "p03": 4, "p04": 3, "p05": 2,
                   "p06": 2, "p07": 1, "p08": 1, "p09": 1, "c01": 1}
        report = evaluate_listening(CLEAN_KEY, ratings)
        self.assertEqual(report["verdict"], "metric_does_not_track_perception")
        self.assertFalse(report["trustworthy"])
        self.assertLess(report["spearman"], 0)

    def test_ordering_can_be_right_while_the_absolute_scale_is_wrong(self):
        # The observed real session: buckets order correctly and the
        # correlation clears the point-estimate bar, but pairs the metric calls
        # interchangeable are plainly audible. Ranking is usable; a distance
        # threshold is not, so a preset must not be condemned on one.
        ratings = {"p01": 3, "p02": 3, "p03": 3, "p04": 3, "p05": 3,
                   "p06": 4, "p07": 4, "p08": 4, "p09": 4, "c01": 1}
        report = evaluate_listening(CLEAN_KEY, ratings)
        self.assertEqual(report["verdict"], "metric_ranks_but_is_not_calibrated")
        self.assertTrue(report["usableForRanking"])
        self.assertFalse(report["trustworthy"])
        self.assertTrue(report["absoluteScaleMiscalibrated"])
        self.assertEqual(report["closeBucketHeardAsDifferent"], "3/3")

    def test_a_wide_confidence_interval_withholds_full_trust(self):
        # A point estimate over the bar carried by an interval that nearly
        # touches zero is not evidence the metric can arbitrate anything.
        small_key = key([
            ("p01", "close", 0.9), ("p02", "close", 1.0),
            ("p03", "mid", 2.2), ("p04", "mid", 2.4),
            ("p05", "far", 3.6), ("p06", "far", 4.2),
        ])
        ratings = {"p01": 1, "p02": 2, "p03": 1, "p04": 3, "p05": 3, "p06": 4}
        report = evaluate_listening(small_key, ratings)
        self.assertIsNotNone(report["spearmanInterval"])
        self.assertLess(report["spearmanInterval"][0], 0.3)
        self.assertFalse(report["trustworthy"])

    def test_a_failed_identity_control_discards_the_session(self):
        # Rating the identical recording as clearly different means the session
        # was guessing; a good correlation elsewhere cannot rescue it.
        ratings = {"p01": 1, "p02": 1, "p03": 2, "p04": 2, "p05": 3,
                   "p06": 3, "p07": 4, "p08": 4, "p09": 4, "c01": 4}
        report = evaluate_listening(CLEAN_KEY, ratings)
        self.assertEqual(report["verdict"], "session_unusable")
        self.assertFalse(report["trustworthy"])
        self.assertEqual(report["identityControls"]["failed"], ["c01"])

    def test_identity_control_tolerates_a_very_similar_rating(self):
        ratings = {"p01": 1, "p02": 1, "p03": 2, "p04": 2, "p05": 3,
                   "p06": 3, "p07": 4, "p08": 4, "p09": 4,
                   "c01": IDENTITY_CONTROL_MAX_RATING}
        report = evaluate_listening(CLEAN_KEY, ratings)
        self.assertEqual(report["identityControls"]["failed"], [])

    def test_identity_controls_are_excluded_from_the_correlation(self):
        ratings = {"p01": 1, "p02": 1, "p03": 2, "p04": 2, "p05": 3,
                   "p06": 3, "p07": 4, "p08": 4, "p09": 4, "c01": 1}
        report = evaluate_listening(CLEAN_KEY, ratings)
        self.assertEqual(report["ratedPairs"], 9)

    def test_missing_and_unknown_pair_ids_are_reported(self):
        report = evaluate_listening(CLEAN_KEY, {"p01": 1, "nonexistent": 3})
        self.assertIn("p09", report["missingRatings"])
        self.assertEqual(report["unknownPairIDs"], ["nonexistent"])

    def test_largest_disagreements_name_the_pairs_to_go_listen_to(self):
        ratings = {"p01": 4, "p02": 1, "p03": 1, "p04": 2, "p05": 3,
                   "p06": 3, "p07": 4, "p08": 4, "p09": 1, "c01": 1}
        report = evaluate_listening(CLEAN_KEY, ratings)
        flagged = {item["pair"] for item in report["largestDisagreements"]}
        # p01 is the closest pair heard as a different emotion; p09 the furthest
        # heard as identical. Both belong at the top of the list.
        self.assertIn("p01", flagged)
        self.assertIn("p09", flagged)


if __name__ == "__main__":
    unittest.main()
