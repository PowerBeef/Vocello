#!/usr/bin/env python3
"""Statistics goldens of the audio-QC qualification engine (audit sections 5.4 and 5.5)."""

from __future__ import annotations

import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.qc_qualification import correlation, policy, resampling, stats, thresholds  # noqa: E402
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

    def test_operating_point_counts_families_alarms_misses_and_abstentions(self) -> None:
        negatives = [("n1", 0.1), ("n2", 0.2), ("n3", 0.9), ("n4", None), ("n5", 0.3)]
        positives = [("p1", 0.95), ("p2", 0.4), ("p3", 0.8), ("p4", None)]
        point = stats.operating_point(negatives, positives, 0.5)
        self.assertEqual(point["unit"], "source-family")
        self.assertEqual((point["far"]["events"], point["far"]["units"]), (1, 4))
        # An abstention on a positive is a miss: abstaining is not detecting.
        self.assertEqual((point["tpr"]["events"], point["tpr"]["units"]), (2, 4))
        self.assertEqual((point["frr"]["events"], point["frr"]["units"]), (2, 4))
        self.assertEqual((point["cleanAbstention"]["events"], point["cleanAbstention"]["units"]), (1, 5))
        self.assertEqual((point["positiveAbstention"]["events"], point["positiveAbstention"]["units"]), (1, 4))
        below = stats.operating_point([("a", 0.9), ("b", 0.8)], [("c", 0.1), ("d", 0.7)], 0.5, direction="below")
        self.assertEqual(below["far"]["events"], 0)
        self.assertEqual(below["tpr"]["events"], 1)
        rate = stats.Rate(0, 60)
        self.assertTrue(stats.meets(rate, maximum=0.05))
        self.assertFalse(stats.meets(stats.Rate(0, 58), maximum=0.05))
        self.assertTrue(stats.meets(stats.Rate(29, 29), minimum=0.90))

    def test_rates_count_families_not_clips(self) -> None:
        # Ten clips of one family alarming once is one false-alarm family, not one in ten clips.
        negatives = [("f1", 0.9)] + [("f1", 0.1)] * 9 + [(f"g{index}", 0.1) for index in range(9)]
        point = stats.operating_point(negatives, [("p", 0.9), ("p", 0.2), ("q", 0.9)], 0.5)
        self.assertEqual((point["far"]["events"], point["far"]["units"], point["negativeClips"]), (1, 10, 19))
        # A positive family is detected only when every one of its clips is.
        self.assertEqual((point["tpr"]["events"], point["tpr"]["units"]), (1, 2))
        self.assertEqual(stats.family_rate([("a", False), ("a", True), ("b", False)]).as_dict()["events"], 1)


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
        families = ["f0", "f0", "f1", "f2", "f3", "f4", "f5", "f6"]
        audit = correlation.failure_correlation(first, second, families=families, judges=("whisper", "parakeet"))
        self.assertEqual(audit["table"], {"bothFailed": 2, "onlyFirstFailed": 1, "onlySecondFailed": 1,
                                          "neitherFailed": 4})
        self.assertAlmostEqual(audit["phi"], (2 * 4 - 1 * 1) / math.sqrt(3 * 5 * 3 * 5), places=6)
        self.assertAlmostEqual(audit["conditionalFailureRate"]["parakeet|whisperFailed"], 2 / 3, places=6)
        self.assertAlmostEqual(audit["conditionalFailureRate"]["parakeet|whisperPassed"], 1 / 5, places=6)
        # The two joint failures share family f0: one joint-failure family of seven.
        self.assertEqual((audit["jointFailure"]["events"], audit["jointFailure"]["units"]), (1, 7))
        self.assertEqual(audit["jointFailure"]["unit"], "source-family")
        self.assertAlmostEqual(audit["jointFailurePerUnit"]["rate"], 2 / 8, places=6)
        self.assertAlmostEqual(audit["jointFailurePerUnit"]["ifIndependent"], (3 / 8) * (3 / 8), places=6)
        self.assertAlmostEqual(audit["jointFailurePerUnit"]["lift"], (2 / 8) / (9 / 64), places=6)

    def test_identical_and_independent_judges(self) -> None:
        def audit(first, second):
            return correlation.failure_correlation(first, second, families=[f"f{i}" for i in range(len(first))])
        flags = [index % 4 == 0 for index in range(40)]
        self.assertAlmostEqual(audit(flags, flags)["phi"], 1.0)
        first = [index % 2 == 0 for index in range(40)]
        second = [(index // 2) % 2 == 0 for index in range(40)]
        self.assertAlmostEqual(audit(first, second)["phi"], 0.0)
        never = [False] * 10
        self.assertIsNone(audit(never, flags[:10])["phi"])

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
            correlation.failure_correlation([True], [True, False], families=["a"])
        with self.assertRaises(ValueError):
            correlation.failure_correlation([True], [True], families=["a", "b"])


OPERATING_POINTS = policy.load_policy()["operatingPoints"]
FAIL_POINT = OPERATING_POINTS["fail"]
LANGUAGES = ("de", "en", "es", "fr", "it", "ja", "ko", "pt", "ru", "zh")


def units(prefix: str, count: int, *, alarms: int = 0, abstain: int = 0, languages=LANGUAGES,
          alarm: bool = False) -> list:
    """`count` families per language, one clip each; the first `alarms` alarm, the next `abstain` abstain."""
    made = []
    for language in languages:
        for index in range(count):
            value = (not alarm) if index < alarms else (None if index < alarms + abstain else alarm)
            made.append(thresholds.ScoredUnit(f"{prefix}-{language}-{index}", language, f"spk-{language}-{index % 7}",
                                              f"script-{language}-{index}", value))
    return made


class ThresholdTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.store = thresholds.PreRegistrationStore(self.root / "plans")

    def tearDown(self) -> None:
        self.directory.cleanup()

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

    def test_derivation_reads_the_committed_plan(self) -> None:
        plan = self.plan()
        negatives = [(f"f{value}", float(value)) for value in range(120)]
        # A plan the caller only holds in memory is refused.
        with self.assertRaises(thresholds.PreRegistrationError):
            thresholds.derive_threshold(plan, self.store, negatives)
        self.store.commit(plan)
        derived = thresholds.derive_threshold(plan, self.store, negatives)
        self.assertEqual(derived["plan"], plan.digest())
        self.assertEqual(derived["threshold"], 119.0)
        self.assertNotEqual(plan.digest(), self.plan(alpha=0.02).digest())
        # A committed file that no longer holds the plan is refused.
        self.store.path(plan.digest()).write_text(json.dumps({**plan.as_dict(), "alpha": 0.5}), encoding="utf-8")
        with self.assertRaises(thresholds.PreRegistrationError):
            thresholds.derive_threshold(plan, self.store, negatives)

    def test_derivation_takes_one_score_per_family(self) -> None:
        plan = self.plan(alpha=0.10)
        self.store.commit(plan)
        # 99 families; family f0 has a second, louder clip: its worst clip is its score.
        negatives = [(f"f{value}", float(value)) for value in range(99)] + [("f0", 500.0)]
        derived = thresholds.derive_threshold(plan, self.store, negatives)
        self.assertEqual((derived["calibrationUnits"], derived["calibrationClips"]), (99, 100))
        self.assertEqual(derived["threshold"], 90.0)

    def test_the_repository_store_requires_a_git_commit(self) -> None:
        root = self.root / "repo"
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        store = thresholds.PreRegistrationStore(root / "config" / "plans", git_root=root)
        plan = self.plan()
        path = store.commit(plan)
        with self.assertRaises(thresholds.PreRegistrationError):
            store.require(plan)
        subprocess.run(["git", "-C", str(root), "add", str(path)], check=True)
        with self.assertRaises(thresholds.PreRegistrationError):
            store.require(plan)
        subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                        "-c", "commit.gpgsign=false", "commit", "-q", "--no-verify", "-m", "plan"], check=True)
        self.assertEqual(store.require(plan)["detector"], "fastqc.clicks@8")
        path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
        with self.assertRaises(thresholds.PreRegistrationError):
            store.require(plan)

    def test_plans_refuse_undeclared_choices(self) -> None:
        for overrides in ({"detector": "clicks"}, {"rule": "youden"}, {"alpha": 0.0}, {"direction": "both"},
                          {"split_salt": ""}, {"strata": (("cjk", ""),)}, {"grid": (1.0,)},
                          {"rule": "learn-then-test"}):
            with self.assertRaises(thresholds.PreRegistrationError, msg=str(overrides)):
                self.plan(**overrides)

    def test_split_is_disjoint_by_family_speaker_and_script(self) -> None:
        plan = self.plan()
        triples = [(f"family-{index}", f"speaker-{index % 40}", f"script-{index % 60}") for index in range(200)]
        split = thresholds.split_families(triples * 2, plan)
        self.assertEqual(split, thresholds.split_families(list(reversed(triples)), plan))
        self.assertEqual(len(split), 200)
        for position in (1, 2):
            sides: dict[str, set] = {}
            for triple in triples:
                sides.setdefault(triple[position], set()).add(split[triple[0]])
            self.assertTrue(all(len(value) == 1 for value in sides.values()), position)
        calibration = sum(1 for side in split.values() if side == "calibration")
        self.assertTrue(0 < calibration < 200)
        # Everything chained through one speaker is one component: it cannot be split.
        with self.assertRaises(thresholds.PreRegistrationError):
            thresholds.split_families([(f"f{index}", "same", f"s{index}") for index in range(10)], plan)

    def test_learn_then_test_keeps_the_last_rejected_setting(self) -> None:
        plan = self.plan(rule="learn-then-test", grid=(3.0, 2.0, 1.0), alpha=0.05)
        self.store.commit(plan)

        def flags(alarmed: int) -> list:
            return [(f"f{index}", index < alarmed) for index in range(120)]
        alarms = {3.0: flags(0), 2.0: flags(1), 1.0: flags(12)}
        result = thresholds.learn_then_test(plan, self.store, alarms)
        self.assertEqual(result["selected"], 2.0)
        self.assertEqual([step["rejected"] for step in result["steps"]], [True, True, False])
        stopped = thresholds.learn_then_test(plan, self.store, {3.0: flags(20), 2.0: flags(0), 1.0: flags(0)})
        self.assertIsNone(stopped["selected"])
        self.assertEqual(len(stopped["steps"]), 1)
        # Clips of one family count once: 12 alarms in one family is one alarmed unit of 120.
        grouped = [("f0", True)] * 12 + [(f"f{index}", False) for index in range(1, 120)]
        self.assertEqual(thresholds.learn_then_test(plan, self.store, {3.0: grouped, 2.0: grouped,
                                                                        1.0: grouped})["steps"][0]["alarms"], 1)

    def cohort(self, **overrides) -> dict:
        cohort = dict(
            operating_point=FAIL_POINT, confidence=0.95,
            n2_negatives=units("n2", 130),
            n3_negatives=units("n3", 60),
            positives={"T1-pcm": {"clicks/severe": units("p1s", 6, alarm=True),
                                  "clicks/moderate": units("p1m", 6, alarm=True)},
                       "T2-codec": {"severe": units("p2s", 6, alarm=True),
                                    "moderate": units("p2m", 6, alarm=True)}},
            shams={"T1-pcm": units("s1", 30), "T2-codec": units("s2", 30)},
        )
        cohort.update(overrides)
        return cohort

    def test_confirmation_runs_once_and_persists(self) -> None:
        plan = self.plan()
        ledger = thresholds.ConfirmationLedger(self.root / "ledger")
        with self.assertRaises(thresholds.PreRegistrationError):
            ledger.confirm(plan, self.store, 0.5, **self.cohort())
        self.store.commit(plan)
        outcome = ledger.confirm(plan, self.store, 0.5, **self.cohort())
        self.assertEqual(outcome["status"], "qualified", outcome["reasons"])
        self.assertEqual(outcome["mechanismsMeeting"], ["T1-pcm", "T2-codec"])
        self.assertAlmostEqual(outcome["farPerLanguage"]["confidence"], 0.995)
        # A new ledger over the same directory, as another process would open it, refuses.
        with self.assertRaises(thresholds.PreRegistrationError):
            thresholds.ConfirmationLedger(self.root / "ledger").confirm(plan, self.store, 0.5, **self.cohort())
        self.assertEqual(thresholds.ConfirmationLedger(self.root / "ledger").outcome(plan.digest())["status"],
                         "qualified")

    def test_a_refused_confirmation_is_recorded_and_final(self) -> None:
        plan = self.plan(split_salt="salt-refused")
        self.store.commit(plan)
        ledger = thresholds.ConfirmationLedger(self.root / "ledger")
        refused = ledger.confirm(plan, self.store, 0.5, **self.cohort(n2_negatives=units("n2", 130, alarms=3)))
        self.assertEqual(refused["status"], "refused")
        self.assertIn("far-pooled-not-met", refused["reasons"])
        with self.assertRaises(thresholds.PreRegistrationError):
            ledger.confirm(plan, self.store, 0.5, **self.cohort())
        self.assertEqual(ledger.outcome(plan.digest())["status"], "refused")

    def test_confirmation_checks_every_policy_requirement(self) -> None:
        plan = self.plan()

        def reasons(**overrides) -> list:
            return thresholds.evaluate_confirmation(plan, 0.5, **self.cohort(**overrides))["reasons"]
        self.assertEqual(reasons(), [])
        # Per-language FAR at the Bonferroni confidence: 2 alarms in 130 pass 95% but not 99.5%.
        skewed = units("n2", 130, languages=LANGUAGES[1:]) + units("n2x", 130, alarms=2, languages=("de",))
        self.assertLessEqual(stats.cp_upper(2, 130), 0.05)
        self.assertIn("far-per-language-not-met", reasons(n2_negatives=skewed))
        self.assertIn("too-few-languages", reasons(n2_negatives=units("n2", 130, languages=LANGUAGES[:9])))
        self.assertIn("n3-flag-rate-not-met", reasons(n3_negatives=units("n3", 60, alarms=5)))
        self.assertIn("n3-coverage-not-met", reasons(n3_negatives=units("n3", 50)))
        self.assertIn("clean-abstention-not-met", reasons(n2_negatives=units("n2", 130, abstain=10)))
        missing_sham = reasons(shams={"T1-pcm": units("s1", 30)})
        self.assertIn("sham-missing:T2-codec", missing_sham)
        self.assertIn("sham-departs:T1-pcm", reasons(shams={"T1-pcm": units("s1", 30, alarms=10),
                                                            "T2-codec": units("s2", 30)}))
        # An abstention on a positive is a miss; one mechanism short of two is refused.
        weak = {"T1-pcm": {"severe": units("p1s", 6, alarm=True), "moderate": units("p1m", 6, alarm=True)},
                "T2-codec": {"severe": units("p2s", 6, abstain=6, alarm=True),
                             "moderate": units("p2m", 6, alarm=True)}}
        self.assertIn("cross-mechanism-detection-not-met", reasons(positives=weak))
        no_moderate = {"T1-pcm": {"severe": units("p1s", 6, alarm=True)},
                       "T2-codec": {"severe": units("p2s", 6, alarm=True)}}
        self.assertIn("cross-mechanism-detection-not-met", reasons(positives=no_moderate))
        self.assertIn("far-pooled-not-met", reasons(n2_negatives=units("n2", 100)))

    def test_the_warn_operating_point_needs_its_own_floors(self) -> None:
        plan = self.plan()
        three = LANGUAGES[:3]
        cohort = dict(operating_point=OPERATING_POINTS["warn"], confidence=0.95,
                      n2_negatives=units("n2", 20, languages=three),
                      positives={"T1-pcm": {"severe": units("p", 20, alarm=True, languages=three)}},
                      shams={"T1-pcm": units("s", 20, languages=three)})
        outcome = thresholds.evaluate_confirmation(plan, 0.5, **cohort)
        self.assertEqual(outcome["status"], "qualified", outcome["reasons"])
        self.assertEqual(outcome["operatingPoint"], "warn")
        self.assertAlmostEqual(outcome["farPerLanguage"]["confidence"], 1 - 0.05 / 3)
        self.assertIsNone(outcome["n3"])
        fewer = thresholds.evaluate_confirmation(plan, 0.5, **{**cohort, "n2_negatives": units("n2", 19,
                                                                                              languages=three)})
        self.assertIn("far-pooled-not-met", fewer["reasons"])


if __name__ == "__main__":
    unittest.main()
