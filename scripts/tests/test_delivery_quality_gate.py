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
from prosody_profile import builtin_profile, validate_profile


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
             "excited", "calm", "whisper", "dramatic"},
        )

    def test_matching_excited_take_passes(self):
        instructed = metrics(f0=160.0, rate=4.4, range_hz=80.0, std=35.0, rough=0.28)
        verdict = evaluate_delivery(instructed, metrics(), "excited.strong")
        self.assertTrue(verdict["passed"])
        self.assertEqual(verdict["flags"], [])
        self.assertEqual(verdict["algorithmVersion"], DELIVERY_GATE_ALGORITHM_VERSION)
        self.assertEqual(verdict["preset"], "excited")
        self.assertEqual(verdict["intensity"], "strong")

    def test_opposite_direction_flags_required_features(self):
        verdict = evaluate_delivery(metrics(f0=140.0, rate=3.6), metrics(), "excited.normal")
        self.assertFalse(verdict["passed"])
        self.assertIn("delivery_direction_miss_pitch_variation_delta_hz", verdict["flags"])
        self.assertIn("delivery_supporting_miss_arousal_score", verdict["flags"])

    def test_weak_effect_flags_but_direction_holds(self):
        # Right direction, but well under the normal-intensity magnitude.
        verdict = evaluate_delivery(metrics(f0=151.0, std=26.0), metrics(), "excited.normal")
        self.assertFalse(verdict["passed"])
        self.assertTrue(
            all(flag.startswith("delivery_effect_weak_") for flag in verdict["flags"]),
            verdict["flags"],
        )

    def test_bare_preset_defaults_to_normal_intensity(self):
        verdict = evaluate_delivery(metrics(f0=140.0, rate=3.5), metrics(), "sad")
        self.assertEqual(verdict["intensity"], "normal")
        self.assertTrue(verdict["passed"])

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


if __name__ == "__main__":
    unittest.main()
