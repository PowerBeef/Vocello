#!/usr/bin/env python3
"""Unit tests for scripts/delivery_quality_gate.py.

The verdict logic consumes already-analyzed metric dicts, so these tests need
no NumPy and no audio files: they exercise the expectation semantics directly.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from delivery_quality_gate import (
    ANALYSIS_FAILURE_FLAGS,
    DELIVERY_GATE_ALGORITHM_VERSION,
    delivery_features,
    evaluate_delivery,
    evaluate_neutral_cohort,
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
        self.assertEqual(verdict["algorithmVersion"], 2)

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


if __name__ == "__main__":
    unittest.main()
