#!/usr/bin/env python3
"""Statistics goldens of the audio-QC qualification engine (audit sections 5.4 and 5.5)."""

from __future__ import annotations

import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.qc_qualification import correlation, resampling, stats, thresholds  # noqa: E402
from lib.qc_qualification.pcm import SeededStream  # noqa: E402

# The audit's section 5.4 table: minimum independent units for a one-sided 95%
# Clopper-Pearson bound <= target with k errors, and the two-sided Wilson k = 0 column.
AUDIT_TABLE = {
    0.20: ((14, 22, 30, 50), 16),
    0.10: ((29, 46, 61, 103), 35),
    0.05: ((59, 93, 124, 208), 73),
    0.02: ((149, 236, 313, 523), 189),
    0.01: ((299, 473, 628, 1049), 381),
}


class ClopperPearsonTests(unittest.TestCase):
    def test_the_audit_sample_size_table_holds(self) -> None:
        for target, (clopper, wilson) in AUDIT_TABLE.items():
            for errors, units in zip((0, 1, 2, 5), clopper):
                self.assertEqual(stats.minimum_units(target, errors), units, (target, errors))
                self.assertLessEqual(stats.cp_upper(errors, units), target)
                self.assertGreater(stats.cp_upper(errors, units - 1), target)
            self.assertEqual(stats.minimum_units(target, 0, method="wilson"), wilson, target)

    def test_named_operating_points(self) -> None:
        # 299 clean clips with 0 alarms give FAR <= 1%; 298 do not.
        self.assertLessEqual(stats.cp_upper(0, 299), 0.01)
        self.assertGreater(stats.cp_upper(0, 298), 0.01)
        # 29 positives with 0 misses give detection >= 0.90; 28 do not.
        self.assertGreaterEqual(stats.cp_lower(29, 29), 0.90)
        self.assertLess(stats.cp_lower(28, 28), 0.90)
        # 124 per language with 2 alarms keep FAR <= 5%.
        self.assertLessEqual(stats.cp_upper(2, 124), 0.05)
        self.assertGreater(stats.cp_upper(2, 123), 0.05)
        # 1,240 pooled N2 negatives support FAR <= 1% with up to 6 alarms.
        self.assertLessEqual(stats.cp_upper(6, 1240), 0.01)
        # The warn floor: 0 of 60 bounds FAR at 0.0487 (CP) and 0.0602 (legacy Wilson).
        self.assertAlmostEqual(stats.cp_upper(0, 60), 1 - 0.05 ** (1 / 60), places=12)
        self.assertAlmostEqual(stats.wilson_upper(0, 60), 0.060172, places=6)
        self.assertAlmostEqual(stats.wilson_upper(0, 30), 0.113513, places=6)

    def test_bounds_match_closed_forms_and_symmetry(self) -> None:
        # One event in ten: the 95% one-sided upper bound solves (1-p)^10 + 10p(1-p)^9 = 0.05.
        upper = stats.cp_upper(1, 10)
        self.assertAlmostEqual((1 - upper) ** 10 + 10 * upper * (1 - upper) ** 9, 0.05, places=12)
        self.assertAlmostEqual(upper, 0.3941633, places=6)
        for events, units in ((0, 7), (1, 10), (3, 40), (17, 60), (60, 60)):
            self.assertAlmostEqual(stats.cp_lower(units - events, units), 1 - stats.cp_upper(events, units),
                                   places=12)
            self.assertLessEqual(stats.cp_lower(events, units), events / units)
            self.assertGreaterEqual(stats.cp_upper(events, units), events / units)

    def test_bonferroni_raises_the_per_language_floor_to_104(self) -> None:
        confidence = stats.bonferroni_confidence(0.95, 10)
        self.assertAlmostEqual(confidence, 0.995)
        self.assertEqual(stats.minimum_units(0.05, 0, confidence), 104)

    def test_invalid_counts_are_refused(self) -> None:
        for events, units in ((-1, 5), (6, 5), (0, 0)):
            with self.assertRaises(ValueError):
                stats.cp_upper(events, units)
        with self.assertRaises(TypeError):
            stats.cp_upper(True, 5)
        with self.assertRaises(ValueError):
            stats.minimum_units(0.05, 0, method="normal")

    def test_operating_point_counts_alarms_misses_and_abstentions(self) -> None:
        negatives = [0.1, 0.2, 0.9, None, 0.3]
        positives = [0.95, 0.4, 0.8, None]
        point = stats.operating_point(negatives, positives, 0.5)
        self.assertEqual((point["far"]["events"], point["far"]["units"]), (1, 4))
        self.assertEqual((point["tpr"]["events"], point["tpr"]["units"]), (2, 3))
        self.assertEqual((point["frr"]["events"], point["frr"]["units"]), (1, 3))
        self.assertEqual((point["cleanAbstention"]["events"], point["cleanAbstention"]["units"]), (1, 5))
        below = stats.operating_point([0.9, 0.8], [0.1, 0.7], 0.5, direction="below")
        self.assertEqual(below["far"]["events"], 0)
        self.assertEqual(below["tpr"]["events"], 1)
        rate = stats.Rate(0, 60)
        self.assertTrue(stats.meets(rate, maximum=0.05))
        self.assertFalse(stats.meets(stats.Rate(0, 58), maximum=0.05))
        self.assertTrue(stats.meets(stats.Rate(29, 29), minimum=0.90))


class ResamplingTests(unittest.TestCase):
    def test_families_travel_together(self) -> None:
        units = [("a", True)] * 10 + [("b", False)] * 10
        clustered = resampling.cluster_bootstrap_rate(units, resamples=500, seed=3)
        self.assertEqual((clustered["families"], clustered["units"], clustered["events"]), (2, 20, 10))
        self.assertEqual(clustered["rate"], 0.5)
        # Two families: every resample is 0, 0.5 or 1, so the interval spans all of it.
        self.assertEqual((clustered["lower"], clustered["upper"]), (0.0, 1.0))
        independent = [(f"unit-{index}", flag) for index, (_, flag) in enumerate(units)]
        spread = resampling.cluster_bootstrap_rate(independent, resamples=500, seed=3)
        self.assertGreater(spread["lower"], 0.0)
        self.assertLess(spread["upper"], 1.0)

    def test_bootstrap_is_deterministic_and_seeded(self) -> None:
        units = [(f"f{index % 7}", index % 3 == 0) for index in range(40)]
        first = resampling.cluster_bootstrap_rate(units, seed=11)
        self.assertEqual(first, resampling.cluster_bootstrap_rate(units, seed=11))
        self.assertEqual(first["resamples"], 2000)
        self.assertLessEqual(first["lower"], first["rate"])
        self.assertGreaterEqual(first["upper"], first["rate"])

    def test_digest_sharing_families_merge_transitively(self) -> None:
        mapping = resampling.merge_families_by_digest([
            ("d1", "a"), ("d2", "b"), ("d2", "c"), ("d3", "c"), ("d3", "a"), ("d4", "e"),
        ])
        self.assertEqual(mapping, {"a": "a", "b": "a", "c": "a", "e": "e"})
        self.assertEqual(resampling.family_level_events([("a", False), ("a", True), ("b", False)]), (1, 2))


class CorrelationTests(unittest.TestCase):
    def test_table_phi_and_conditional_rates(self) -> None:
        first = [True, True, True, False, False, False, False, False]
        second = [True, True, False, True, False, False, False, False]
        audit = correlation.failure_correlation(first, second, judges=("whisper", "parakeet"))
        self.assertEqual(audit["table"], {"bothFailed": 2, "onlyFirstFailed": 1, "onlySecondFailed": 1,
                                          "neitherFailed": 4})
        self.assertAlmostEqual(audit["phi"], (2 * 4 - 1 * 1) / math.sqrt(3 * 5 * 3 * 5), places=6)
        self.assertAlmostEqual(audit["conditionalFailureRate"]["parakeet|whisperFailed"], 2 / 3, places=6)
        self.assertAlmostEqual(audit["conditionalFailureRate"]["parakeet|whisperPassed"], 1 / 5, places=6)
        self.assertEqual(audit["jointFailure"]["events"], 2)
        self.assertAlmostEqual(audit["jointFailureIfIndependent"], (3 / 8) * (3 / 8), places=6)
        self.assertAlmostEqual(audit["jointFailureLift"], (2 / 8) / (9 / 64), places=6)

    def test_identical_and_independent_judges(self) -> None:
        flags = [index % 4 == 0 for index in range(40)]
        self.assertAlmostEqual(correlation.failure_correlation(flags, flags)["phi"], 1.0)
        first = [index % 2 == 0 for index in range(40)]
        second = [(index // 2) % 2 == 0 for index in range(40)]
        self.assertAlmostEqual(correlation.failure_correlation(first, second)["phi"], 0.0)
        never = [False] * 10
        self.assertIsNone(correlation.failure_correlation(never, flags[:10])["phi"])

    def test_family_bootstrap_of_phi_is_deterministic(self) -> None:
        stream = SeededStream(5, "phi-test")
        first = list(stream.uniform(120) < 0.2)
        second = [flag if index % 3 else not flag for index, flag in enumerate(first)]
        families = [f"f{index // 4}" for index in range(120)]
        audit = correlation.failure_correlation(first, second, families=families, resamples=400, seed=9)
        again = correlation.failure_correlation(first, second, families=families, resamples=400, seed=9)
        self.assertEqual(audit, again)
        interval = audit["phiClusterBootstrap"]
        self.assertEqual(interval["families"], 30)
        self.assertLessEqual(interval["lower"], audit["phi"])
        self.assertGreaterEqual(interval["upper"], audit["phi"])
        with self.assertRaises(ValueError):
            correlation.failure_correlation([True], [True, False])


class ThresholdTests(unittest.TestCase):
    def plan(self, **overrides) -> thresholds.PreRegistration:
        base = dict(detector="fastqc.clicks@8", rule="split-conformal", alpha=0.01, direction="above",
                    split_salt="salt-1", strata=(("cjk", "CER languages score differently"),))
        base.update(overrides)
        return thresholds.PreRegistration(**base)

    def test_conformal_rank_and_threshold(self) -> None:
        self.assertEqual(thresholds.conformal_rank(99, 0.01), 99)
        self.assertIsNone(thresholds.conformal_rank(98, 0.01))
        scores = [float(value) for value in range(1, 100)]
        above = thresholds.conformal_threshold(scores, 0.01)
        self.assertEqual((above["threshold"], above["rank"], above["status"]), (99.0, 99, "derived"))
        self.assertEqual(thresholds.conformal_threshold(scores[:-1], 0.01)["status"], "insufficient-negatives")
        self.assertEqual(thresholds.conformal_threshold(scores, 0.10)["threshold"], 90.0)
        self.assertEqual(thresholds.conformal_threshold(scores, 0.10, "below")["threshold"], 10.0)

    def test_conformal_threshold_bounds_the_false_alarm_rate(self) -> None:
        exceed = total = 0
        for trial in range(200):
            stream = SeededStream(trial, "conformal-check")
            calibration = list(stream.normal(99))
            fresh = stream.normal(500)
            threshold = thresholds.conformal_threshold(calibration, 0.05)["threshold"]
            exceed += int((fresh > threshold).sum())
            total += fresh.size
        self.assertLessEqual(exceed / total, 0.05 + 0.005)

    def test_derivation_requires_the_committed_plan(self) -> None:
        plan = self.plan()
        with self.assertRaises(thresholds.PreRegistrationError):
            thresholds.derive_threshold(plan, "0" * 64, [1.0] * 120)
        derived = thresholds.derive_threshold(plan, plan.digest(), [float(v) for v in range(120)])
        self.assertEqual(derived["plan"], plan.digest())
        self.assertEqual(derived["threshold"], 119.0)
        self.assertNotEqual(plan.digest(), self.plan(alpha=0.02).digest())

    def test_plans_refuse_undeclared_choices(self) -> None:
        for overrides in ({"detector": "clicks"}, {"rule": "youden"}, {"alpha": 0.0}, {"direction": "both"},
                          {"split_salt": ""}, {"strata": (("cjk", ""),)}, {"grid": (1.0,)},
                          {"rule": "learn-then-test"}):
            with self.assertRaises(thresholds.PreRegistrationError, msg=str(overrides)):
                self.plan(**overrides)

    def test_family_split_is_deterministic_and_disjoint(self) -> None:
        plan = self.plan()
        families = [f"family-{index}" for index in range(200)] * 2
        split = thresholds.split_families(families, plan)
        self.assertEqual(split, thresholds.split_families(list(reversed(families)), plan))
        self.assertEqual(len(split), 200)
        calibration = sum(1 for side in split.values() if side == "calibration")
        self.assertTrue(70 < calibration < 130)
        other = thresholds.split_families(families, self.plan(split_salt="salt-2"))
        self.assertNotEqual(split, other)

    def test_learn_then_test_keeps_the_last_rejected_setting(self) -> None:
        plan = self.plan(rule="learn-then-test", grid=(3.0, 2.0, 1.0), alpha=0.05)
        alarms = {3.0: [False] * 120, 2.0: [True] * 1 + [False] * 119, 1.0: [True] * 12 + [False] * 108}
        result = thresholds.learn_then_test(plan, plan.digest(), alarms)
        self.assertEqual(result["selected"], 2.0)
        self.assertEqual([step["rejected"] for step in result["steps"]], [True, True, False])
        stopped = thresholds.learn_then_test(plan, plan.digest(), {3.0: [True] * 20 + [False] * 100,
                                                                    2.0: [False] * 120, 1.0: [False] * 120})
        self.assertIsNone(stopped["selected"])
        self.assertEqual(len(stopped["steps"]), 1)

    def test_confirmation_runs_once(self) -> None:
        plan = self.plan()
        ledger = thresholds.ConfirmationLedger()
        outcome = ledger.confirm(plan, plan.digest(), 0.5, [False] * 300,
                                 {"T1-pcm": [True] * 60, "T2-codec": [True] * 59 + [False]},
                                 maximum_far=0.01, minimum_tpr=0.90)
        self.assertEqual(outcome["status"], "qualified")
        self.assertEqual(outcome["mechanismsMeeting"], ["T1-pcm", "T2-codec"])
        with self.assertRaises(thresholds.PreRegistrationError):
            ledger.confirm(plan, plan.digest(), 0.5, [False] * 300, {"T1-pcm": [True] * 60},
                           maximum_far=0.01, minimum_tpr=0.90)
        refused = thresholds.ConfirmationLedger().confirm(
            plan, plan.digest(), 0.5, [True] * 5 + [False] * 295, {"T1-pcm": [True] * 60},
            maximum_far=0.01, minimum_tpr=0.90)
        self.assertEqual(refused["status"], "refused")
        self.assertEqual(refused["reasons"], ["far-bound-not-met", "cross-mechanism-detection-not-met"])


if __name__ == "__main__":
    unittest.main()
