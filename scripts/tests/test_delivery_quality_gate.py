#!/usr/bin/env python3
"""Unit tests for scripts/delivery_quality_gate.py.

The verdict logic consumes already-analyzed metric dicts, so these tests need
no NumPy and no audio files: they exercise the expectation semantics directly.
"""
import math
import os
import random
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import delivery_quality_gate as gate_module  # noqa: E402
from delivery_quality_gate import (
    ANALYSIS_FAILURE_FLAGS,
    DELIVERY_GATE_ALGORITHM_VERSION,
    delivery_features,
    evaluate_delivery,
    evaluate_neutral_cohort,
    leave_one_out_outlier_report,
    leave_one_out_studentized_residual,
    student_t_two_sided_p,
)
from prosody_profile import (
    SCHEMA_VERSION,
    builtin_profile,
    migrate_profile,
    validate_profile,
)


def metrics(
    f0=150.0, range_hz=60.0, range_st=6.0, std=25.0, voiced=0.7, rate=4.0,
    cv=0.10, pause=0.06, rough=0.25, duration=12.0, clip="take.wav",
):
    return {
        "f0_median_hz": f0,
        "f0_range_hz": range_hz,
        "f0_range_semitones": range_st,
        "f0_std_hz": std,
        "f0_voiced_frac": voiced,
        "rate_syllable_rate_hz": rate,
        "rate_cv": cv,
        "pause_ratio": pause,
        "energy_roughness": rough,
        "durationSec": duration,
        "clip": clip,
    }


class DeliveryGateTests(unittest.TestCase):
    def test_builtin_profile_covers_all_presets_including_neutral(self):
        profile = validate_profile(builtin_profile())
        presets = set(profile["delivery_expectations"]["presets"].keys())
        self.assertEqual(
            presets,
            {"neutral", "happy", "sad", "angry", "fearful", "surprised",
             "calm", "whisper"},
        )

    def test_matching_angry_take_passes(self):
        instructed = metrics(f0=165.0, rate=4.4, range_hz=80.0, std=35.0, rough=0.28)
        verdict = evaluate_delivery(instructed, metrics(), "angry.strong")
        self.assertTrue(verdict["passed"])
        self.assertEqual(verdict["flags"], [])
        self.assertEqual(verdict["algorithmVersion"], DELIVERY_GATE_ALGORITHM_VERSION)
        self.assertEqual(verdict["preset"], "angry")
        self.assertEqual(verdict["intensity"], "strong")

    def test_opposite_direction_flags_required_features(self):
        # An aroused, pitch-lively take scored as sad misses both required
        # directions (sad keeps required tiers under the calibrated profile).
        verdict = evaluate_delivery(
            metrics(f0=165.0, rate=4.5, std=35.0), metrics(), "sad.normal"
        )
        self.assertFalse(verdict["passed"])
        self.assertIn("delivery_direction_miss_arousal_score", verdict["flags"])
        self.assertIn("delivery_direction_miss_pitch_variation_delta_hz", verdict["flags"])

    def test_weak_effect_flags_but_direction_holds(self):
        # Right direction, but well under the calibrated normal-intensity floor.
        verdict = evaluate_delivery(metrics(f0=145.0, std=23.0), metrics(), "sad.normal")
        self.assertFalse(verdict["passed"])
        self.assertTrue(
            all(flag.startswith("delivery_effect_weak_") for flag in verdict["flags"]),
            verdict["flags"],
        )

    def test_bare_preset_defaults_to_normal_intensity(self):
        verdict = evaluate_delivery(metrics(f0=138.0, rate=3.4, std=15.0), metrics(), "sad")
        self.assertEqual(verdict["intensity"], "normal")
        self.assertTrue(verdict["passed"], verdict["flags"])

    def test_uncovered_preset_reports_expectation_missing(self):
        verdict = evaluate_delivery(metrics(), metrics(), "bogus.normal")
        self.assertFalse(verdict["passed"])
        self.assertEqual(verdict["flags"], ["expectation_missing"])
        self.assertIn("expectation_missing", ANALYSIS_FAILURE_FLAGS)

    def test_analysis_error_reports_analysis_failed(self):
        verdict = evaluate_delivery({"error": "boom"}, metrics(), "happy.normal")
        self.assertEqual(verdict["flags"], ["analysis_failed"])

    def test_incomplete_metrics_report_metrics_incomplete(self):
        broken = metrics()
        del broken["f0_range_semitones"]
        verdict = evaluate_delivery(broken, metrics(), "surprised.normal")
        self.assertEqual(verdict["flags"], ["metrics_incomplete"])

    def test_features_include_semitone_pitch_shift(self):
        features = delivery_features(metrics(f0=300.0), metrics(f0=150.0), builtin_profile())
        self.assertAlmostEqual(features["pitch_shift_semitones"], 12.0, places=6)

    def test_whisper_expects_reduced_pitch_variation_and_arousal(self):
        whispered = metrics(voiced=0.5, std=15.0, rate=3.6)
        verdict = evaluate_delivery(whispered, metrics(), "whisper.normal")
        self.assertTrue(verdict["passed"], verdict["flags"])
        loud = metrics(voiced=0.75)
        self.assertFalse(evaluate_delivery(loud, metrics(), "whisper.normal")["passed"])

    def test_neutral_cohort_consistent_passes(self):
        cohort = [
            metrics(f0=148.0 + i, rate=4.0 + 0.05 * i, clip=f"c{i}.wav") for i in range(6)
        ]
        verdict = evaluate_neutral_cohort(cohort)
        self.assertTrue(verdict["passed"])
        self.assertEqual(verdict["cohortSize"], 6)

    def test_neutral_cohort_wide_spread_flags(self):
        cohort = [metrics(f0=140.0, clip="a.wav"), metrics(f0=150.0, clip="b.wav"),
                  metrics(f0=145.0, clip="c.wav"), metrics(f0=230.0, rate=6.2, clip="d.wav")]
        verdict = evaluate_neutral_cohort(cohort)
        self.assertFalse(verdict["passed"])
        self.assertIn("pitch_spread_exceeded", verdict["flags"])

    def test_binding_outlier_check_stays_on_the_calibrated_population_z(self):
        # The candidate sits inside the population SD, so |z| <= sqrt(n - 1)
        # = 1.73 at n = 4 and the calibrated 2.5 bound cannot fire (audit #105).
        # The leave-one-out score reports the take without gating it.
        cohort = [metrics(f0=148.0, clip="a.wav"), metrics(f0=149.0, clip="b.wav"),
                  metrics(f0=150.0, clip="c.wav"), metrics(f0=175.0, clip="d.wav")]
        verdict = evaluate_neutral_cohort(cohort)
        self.assertTrue(verdict["passed"], verdict["flags"])
        self.assertEqual(verdict["outlierAlgorithm"], "population-z-v1")
        self.assertLessEqual(verdict["metrics"]["max_abs_z"], math.sqrt(3))
        report = verdict["leaveOneOutOutlier"]
        self.assertIs(report["reportOnly"], True)
        self.assertEqual(report["algorithm"], "leave-one-out-studentized-t-v1")
        self.assertEqual((report["candidate"], report["degreesOfFreedom"]), ("d.wav", 2))
        self.assertGreater(report["maxAbsScore"], 20.0)
        self.assertLess(report["bonferroniPValue"], 0.01)
        # The report-only alpha flags the candidate; the flag binds nothing
        # until calibration evidence exists, so the cohort still passes.
        self.assertEqual((report["alpha"], report["alphaStatus"]), (0.05, "report-only-uncalibrated"))
        self.assertIs(report["flagged"], True)
        self.assertIs(report["bindsVerdict"], False)
        self.assertNotIn("arousal_outlier", verdict["flags"])

    def test_leave_one_out_flag_follows_the_report_alpha_and_never_binds(self):
        steady = [metrics(f0=148.0 + 0.5 * i, clip=f"s{i}.wav") for i in range(6)]
        report = evaluate_neutral_cohort(steady)["leaveOneOutOutlier"]
        self.assertIs(report["flagged"], False)
        # No score without two other takes, so nothing to flag.
        self.assertIs(leave_one_out_outlier_report([1.0, 9.0], ["a.wav", "b.wav"])["flagged"], False)
        for p_value, flagged in ((0.04, True), (0.06, False), (0.2, False)):
            with self.subTest(p_value=p_value), mock.patch.object(
                gate_module, "student_t_two_sided_p", return_value=p_value / 6
            ):
                verdict = evaluate_neutral_cohort(steady)
                self.assertIs(verdict["leaveOneOutOutlier"]["flagged"], flagged)
                self.assertTrue(verdict["passed"], verdict["flags"])

    def test_neutral_outlier_at_n8(self):
        steady = [metrics(f0=148.0 + 0.5 * i, clip=f"s{i}.wav") for i in range(8)]
        verdict = evaluate_neutral_cohort(steady)
        self.assertTrue(verdict["passed"], verdict["flags"])
        self.assertLess(verdict["metrics"]["max_abs_z"], 2.5)
        self.assertEqual(verdict["leaveOneOutOutlier"]["bonferroniPValue"], 1.0)
        wandering = steady[:7] + [metrics(f0=170.0, clip="w.wav")]
        verdict = evaluate_neutral_cohort(wandering)
        self.assertEqual(verdict["outliers"], ["w.wav"])
        self.assertIn("arousal_outlier", verdict["flags"])
        self.assertEqual(verdict["leaveOneOutOutlier"]["candidate"], "w.wav")
        self.assertLess(verdict["leaveOneOutOutlier"]["bonferroniPValue"], 1e-4)

    def test_student_t_tail_matches_tabulated_critical_values(self):
        # Two-sided 5% critical values of Student's t.
        for statistic, degrees in ((12.706, 1), (4.303, 2), (3.182, 3), (2.776, 4),
                                   (2.571, 5), (2.447, 6), (2.365, 7), (2.228, 10)):
            self.assertAlmostEqual(student_t_two_sided_p(statistic, degrees), 0.05, places=3)
        self.assertEqual(student_t_two_sided_p(0.0, 3), 1.0)
        self.assertEqual(student_t_two_sided_p(float("inf"), 3), 0.0)
        with self.assertRaises(ValueError):
            student_t_two_sided_p(1.0, 0)

    def test_leave_one_out_score_handles_exact_agreement(self):
        self.assertEqual(leave_one_out_studentized_residual([1.0, 1.0, 1.0, 1.0], 3), 0.0)
        self.assertEqual(leave_one_out_studentized_residual([1.0, 1.0, 1.0, 2.0], 3), float("inf"))
        self.assertAlmostEqual(
            leave_one_out_studentized_residual([1.0, 2.0, 3.0, 5.0], 3), 3.0 / math.sqrt(4.0 / 3.0)
        )
        self.assertIsNone(leave_one_out_studentized_residual([1.0, 2.0], 1))
        verdict = evaluate_neutral_cohort([metrics(clip=f"{i}.wav") for i in range(3)]
                                          + [metrics(f0=160.0, clip="x.wav")])
        self.assertTrue(verdict["passed"], verdict["flags"])
        report = verdict["leaveOneOutOutlier"]
        self.assertEqual(report["candidate"], "x.wav")
        self.assertIsNone(report["maxAbsScore"])
        self.assertEqual(report["bonferroniPValue"], 0.0)

    def test_healthy_cohorts_pass_at_the_calibrated_rate(self):
        """Seeded null simulation (audit #105 review): healthy cohorts of four to
        eight takes pass the binding check as often as they did under the
        calibrated statistic (never below eight takes, where it cannot fire), and
        the report-only family-wise p-value is calibrated near its nominal 5%."""
        rng = random.Random(20260925)
        trials = 1000
        for size in range(4, 9):
            failed = flagged = 0
            for _ in range(trials):
                # Healthy: independent normal arousal proxies (only the F0 range
                # varies, so the pitch and rate spreads stay in bounds).
                cohort = [metrics(range_hz=60.0 + 8.0 * rng.gauss(0.0, 1.0), clip=f"{i}.wav")
                          for i in range(size)]
                verdict = evaluate_neutral_cohort(cohort)
                self.assertTrue(set(verdict["flags"]) <= {"arousal_outlier"}, verdict["flags"])
                failed += not verdict["passed"]
                flagged += verdict["leaveOneOutOutlier"]["flagged"]
            with self.subTest(size=size):
                if size <= 7:
                    self.assertEqual(failed, 0)
                else:
                    self.assertLessEqual(failed / trials, 0.02)
                # The leave-one-out median/MAD score this replaced crossed 2.5 in
                # 58-82% of these cohorts; the studentized score stays near 5%.
                self.assertGreater(flagged / trials, 0.02)
                self.assertLess(flagged / trials, 0.08)

    def test_neutral_cohort_too_small_is_failure_class(self):
        verdict = evaluate_neutral_cohort([metrics(), metrics()])
        self.assertEqual(verdict["flags"], ["cohort_too_small"])
        self.assertIn("cohort_too_small", ANALYSIS_FAILURE_FLAGS)


def voice_metrics(hnr=12.0, cpp=20.0, jitter=2.5, shimmer=1.0, alpha=15.0,
                  hammarberg=27.0, hf=0.12, centroid=1400.0, flux=0.30,
                  turning=20.0, max_pause=0.2, dynamic_range=18.0, **kwargs):
    """A v3 metric dict: the v2 surface plus the voice-quality/spectral block."""
    base = metrics(**kwargs)
    base.update({
        "voice_hnr_db_mean": hnr,
        "voice_cpp_db_mean": cpp,
        "voice_frame_jitter_pct": jitter,
        "voice_frame_shimmer_db": shimmer,
        "spectral_alpha_ratio_db": alpha,
        "spectral_hammarberg_db": hammarberg,
        "spectral_hf_energy_ratio": hf,
        "spectral_centroid_hz": centroid,
        "spectral_flux": flux,
        "f0_turning_points_per_sec": turning,
        "pauses_max_pause_seconds": max_pause,
        "energy_dynamic_range_db": dynamic_range,
    })
    return base


class VoiceQualityFeatureTests(unittest.TestCase):
    """The analyzer-v3 paired block, and its backward-compatibility contract."""

    def test_v2_metric_dicts_still_produce_a_verdict_without_the_new_block(self):
        # Every bench-prosody.json row banked before analyzer v3 carries only
        # the v2 surface. Those rows must keep evaluating, with the new
        # features simply absent rather than the verdict failing.
        features = delivery_features(metrics(f0=170.0), metrics(), builtin_profile())
        self.assertIn("arousal_score", features)
        for absent in ("hnr_delta_db", "voice_tension_score", "voice_breathiness_score"):
            self.assertNotIn(absent, features)
        verdict = evaluate_delivery(metrics(f0=170.0), metrics(), "happy.normal")
        self.assertNotIn("metrics_incomplete", verdict["flags"])

    def test_voice_quality_deltas_are_signed_instructed_minus_neutral(self):
        features = delivery_features(
            voice_metrics(hnr=9.0, cpp=15.0, jitter=3.4),
            voice_metrics(hnr=12.0, cpp=20.0, jitter=2.5),
            builtin_profile(),
        )
        self.assertAlmostEqual(features["hnr_delta_db"], -3.0)
        self.assertAlmostEqual(features["cpp_delta_db"], -5.0)
        self.assertAlmostEqual(features["jitter_delta_pct"], 0.9)

    def test_breathiness_score_rises_when_hnr_and_cpp_fall(self):
        # The whisper signature: aspiration noise lowers both harmonicity
        # measures, which must read as *more* breathy, not less.
        breathy = delivery_features(
            voice_metrics(hnr=8.0, cpp=14.0), voice_metrics(), builtin_profile()
        )
        pressed = delivery_features(
            voice_metrics(hnr=15.0, cpp=23.0), voice_metrics(), builtin_profile()
        )
        self.assertGreater(breathy["voice_breathiness_score"], 0.0)
        self.assertLess(pressed["voice_breathiness_score"], 0.0)

    def test_tension_score_rises_with_a_brighter_pressed_spectrum(self):
        # The angry signature: relatively more energy above 1 kHz, so the alpha
        # ratio and Hammarberg index fall while the HF share rises.
        tense = delivery_features(
            voice_metrics(alpha=11.5, hammarberg=22.0, hf=0.16),
            voice_metrics(), builtin_profile(),
        )
        dark = delivery_features(
            voice_metrics(alpha=18.0, hammarberg=30.0, hf=0.09),
            voice_metrics(), builtin_profile(),
        )
        self.assertGreater(tense["voice_tension_score"], 0.0)
        self.assertLess(dark["voice_tension_score"], 0.0)

    def test_cadence_deltas_cover_the_previously_unbound_v2_keys(self):
        # `dramatic` is described by held pauses and `surprised` by contour
        # turns; both were measured by v2 and bound to no expectation.
        features = delivery_features(
            voice_metrics(turning=26.0, max_pause=0.62, dynamic_range=21.0),
            voice_metrics(), builtin_profile(),
        )
        self.assertAlmostEqual(features["turning_points_delta_per_sec"], 6.0)
        self.assertAlmostEqual(features["max_pause_delta_seconds"], 0.42)
        self.assertAlmostEqual(features["dynamic_range_delta_db"], 3.0)

    def test_optional_expectation_feature_skips_as_unavailable(self):
        # whisper's calibrated block requires voice_breathiness_score, but a
        # v2-analyzed pair has no voice block: the entry must skip into
        # unavailableFeatures — never metrics_incomplete, never a warn.
        whispered = metrics(voiced=0.5, std=15.0, rate=3.6)
        verdict = evaluate_delivery(whispered, metrics(), "whisper.normal")
        self.assertTrue(verdict["passed"], verdict["flags"])
        self.assertEqual(verdict["unavailableFeatures"], ["voice_breathiness_score"])
        self.assertEqual(verdict["algorithmVersion"], DELIVERY_GATE_ALGORITHM_VERSION)

    def test_breathiness_required_evaluates_when_v3_block_present(self):
        neutral = voice_metrics()
        breathy = voice_metrics(hnr=8.0, cpp=14.0, voiced=0.5, std=15.0, rate=3.6)
        verdict = evaluate_delivery(breathy, neutral, "whisper.normal")
        self.assertTrue(verdict["passed"], verdict["flags"])
        self.assertEqual(verdict["unavailableFeatures"], [])
        self.assertIn("voice_breathiness_score", verdict["metrics"])
        pressed = voice_metrics(hnr=15.0, cpp=23.0, voiced=0.75)
        verdict = evaluate_delivery(pressed, neutral, "whisper.normal")
        self.assertFalse(verdict["passed"])
        self.assertIn("delivery_direction_miss_voice_breathiness_score", verdict["flags"])

    def test_fearful_strong_expects_raised_arousal(self):
        # fearful.strong asks for "trembling panic … urgent … fast uneven
        # pacing": the calibration flipped its arousal direction to +1, so an
        # urgent high-pitched take with added pauses adheres.
        urgent = metrics(f0=170.0, rate=4.6, pause=0.08)
        verdict = evaluate_delivery(urgent, metrics(), "fearful.strong")
        self.assertTrue(verdict["passed"], verdict["flags"])
        self.assertIn("turning_points_delta_per_sec", verdict["unavailableFeatures"])
        placid = metrics(f0=140.0, rate=3.2, pause=0.05)
        verdict = evaluate_delivery(placid, metrics(), "fearful.strong")
        self.assertFalse(verdict["passed"])
        self.assertIn("delivery_direction_miss_pause_ratio_delta", verdict["flags"])

    def test_profile_migration_fills_the_new_weight_section(self):
        legacy = builtin_profile()
        legacy["schema_version"] = 2
        del legacy["delivery_weights"]["voice_quality"]
        migrated = migrate_profile(legacy)
        self.assertEqual(migrated["schema_version"], SCHEMA_VERSION)
        self.assertIn("voice_quality", migrated["delivery_weights"])
        validate_profile(migrated)

    def test_schema_v4_uses_measured_tier_scale_and_normal_shipping_floors(self):
        profile = builtin_profile()
        expectations = profile["delivery_expectations"]
        self.assertEqual(expectations["intensity_scale"], {"normal": 1.0, "strong": 1.0})
        for preset in ("happy", "angry"):
            features = expectations["presets"][preset]
            self.assertTrue(features)
            self.assertTrue(all(
                specification["tier"] == "supporting"
                and specification["min_effect_normal"] == 0.0
                for specification in features.values()
            ))


class DeliveryCellAdherenceTests(unittest.TestCase):
    """Audit #39: the adherence verdict is the cell's, not one noisy pair's."""

    @staticmethod
    def sad_takes(pitch_variation, arousal=None):
        # sad.normal requires arousal -1 (floor 1.0) and pitch variation -1 (floor 4.3).
        arousal = arousal if arousal is not None else [-2.0] * len(pitch_variation)
        return [
            {"pitch_variation_delta_hz": value, "arousal_score": score, "pause_ratio_delta": 0.01}
            for value, score in zip(pitch_variation, arousal)
        ]

    def test_a_cell_whose_median_holds_passes_despite_noisy_takes(self):
        from delivery_quality_gate import evaluate_delivery_cell
        # Two of seven takes would flag per take (one wrong way, one weak), but
        # the cell's median effect clears the floor.
        takes = self.sad_takes([-8.0, -7.5, 2.0, -9.0, -3.0, -6.5, -8.2])
        per_take = [
            evaluate_delivery(metrics(std=25.0 + value), metrics(), "sad.normal")["flags"]
            for value in (-8.0, -7.5, 2.0, -9.0, -3.0, -6.5, -8.2)
        ]
        self.assertGreater(sum(1 for flags in per_take if flags), 0)
        verdict = evaluate_delivery_cell(takes, "sad.normal")
        self.assertEqual(verdict["status"], "pass")
        self.assertEqual(verdict["flags"], [])
        self.assertEqual(verdict["algorithm"], "delivery-cell-adherence-v1")
        feature = verdict["features"]["pitch_variation_delta_hz"]
        self.assertEqual((feature["n"], feature["tier"], feature["judged"]), (7, "required", True))
        self.assertAlmostEqual(feature["medianSignedEffect"], 7.5)
        # paired_report annotations ride along and never decide.
        self.assertIsNotNone(feature["wilcoxonPValue"])
        self.assertEqual(len(feature["meanInterval"]), 2)

    def test_a_cell_that_moved_the_wrong_way_or_too_little_warns(self):
        from delivery_quality_gate import evaluate_delivery_cell
        wrong = evaluate_delivery_cell(self.sad_takes([1.0, 2.0, -0.5, 3.0, 0.5]), "sad.normal")
        self.assertEqual(wrong["status"], "warn")
        self.assertIn("cell_direction_miss_pitch_variation_delta_hz", wrong["flags"])
        weak = evaluate_delivery_cell(self.sad_takes([-2.0, -1.0, -3.0, -2.5, -1.5]), "sad.normal")
        self.assertEqual(weak["flags"], ["cell_effect_weak_pitch_variation_delta_hz"])
        # A supporting feature flags only a clear opposite move of the cell.
        happy = [{"pitch_shift_semitones": value} for value in (-0.5, -0.2, -0.8, 0.1, -0.4)]
        self.assertEqual(
            evaluate_delivery_cell(happy, "happy.normal")["flags"],
            ["cell_supporting_miss_pitch_shift_semitones"],
        )

    def test_too_few_takes_or_no_expectation_never_warn(self):
        from delivery_quality_gate import CELL_MINIMUM_TAKES, evaluate_delivery_cell
        self.assertEqual(CELL_MINIMUM_TAKES, 5)
        few = evaluate_delivery_cell(self.sad_takes([1.0, 2.0]), "sad.normal")
        self.assertEqual((few["status"], few["flags"]), ("insufficient", []))
        self.assertFalse(few["features"]["pitch_variation_delta_hz"]["judged"])
        uncovered = evaluate_delivery_cell([{"arousal_score": 1.0}] * 6, "excited.strong")
        self.assertEqual((uncovered["status"], uncovered["flags"]), ("unavailable", ["expectation_missing"]))
        # Missing and non-finite features are skipped, never judged.
        skipped = evaluate_delivery_cell([{"arousal_score": float("nan")}] * 6, "sad.normal")
        self.assertEqual(skipped["status"], "insufficient")

    def test_the_per_take_gate_is_version_three(self):
        self.assertEqual(DELIVERY_GATE_ALGORITHM_VERSION, 3)


if __name__ == "__main__":
    unittest.main()
