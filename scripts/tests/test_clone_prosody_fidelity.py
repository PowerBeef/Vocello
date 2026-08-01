#!/usr/bin/env python3
"""Unit tests for scripts/clone_prosody_fidelity.py.

Verdict logic runs on already-analyzed metric dicts — no NumPy, no audio.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from clone_prosody_fidelity import (
    ANALYSIS_FAILURE_FLAGS,
    CLONE_FIDELITY_ALGORITHM_VERSION,
    clone_features,
    evaluate_clone_fidelity,
    evaluate_takes,
)


def metrics(f0=180.0, range_st=5.0, voiced=0.65, rate=4.2, pause=0.08, rough=0.24, clip="take.wav"):
    return {
        "f0_median_hz": f0,
        "f0_range_semitones": range_st,
        "f0_voiced_frac": voiced,
        "rate_syllable_rate_hz": rate,
        "pause_ratio": pause,
        "energy_roughness": rough,
        "clip": clip,
    }


class CloneProsodyFidelityTests(unittest.TestCase):
    def test_faithful_take_passes(self):
        verdict = evaluate_clone_fidelity(metrics(), metrics(f0=185.0, rate=4.4))
        self.assertTrue(verdict["passed"], verdict["flags"])
        self.assertEqual(verdict["algorithmVersion"], CLONE_FIDELITY_ALGORITHM_VERSION)

    def test_pitch_register_mismatch_flags(self):
        # A full fourth above the reference register (~5 semitones).
        verdict = evaluate_clone_fidelity(metrics(f0=150.0), metrics(f0=200.0))
        self.assertIn("clone_pitch_register_mismatch", verdict["flags"])

    def test_pacing_mismatch_flags(self):
        verdict = evaluate_clone_fidelity(metrics(rate=4.0), metrics(rate=6.0))
        self.assertIn("clone_pacing_mismatch", verdict["flags"])

    def test_expressiveness_mismatch_flags(self):
        verdict = evaluate_clone_fidelity(metrics(range_st=3.0), metrics(range_st=9.0))
        self.assertIn("clone_expressiveness_mismatch", verdict["flags"])

    def test_voicing_mismatch_flags(self):
        verdict = evaluate_clone_fidelity(metrics(voiced=0.7), metrics(voiced=0.4))
        self.assertIn("clone_voicing_mismatch", verdict["flags"])

    def test_analysis_error_is_failure_class(self):
        verdict = evaluate_clone_fidelity({"error": "boom"}, metrics())
        self.assertEqual(verdict["flags"], ["analysis_failed"])
        self.assertIn("analysis_failed", ANALYSIS_FAILURE_FLAGS)

    def test_incomplete_metrics_are_failure_class(self):
        broken = metrics()
        del broken["f0_range_semitones"]
        verdict = evaluate_clone_fidelity(metrics(), broken)
        self.assertEqual(verdict["flags"], ["metrics_incomplete"])

    def test_features_are_speaker_fair(self):
        features = clone_features(metrics(f0=150.0, rate=4.0), metrics(f0=300.0, rate=5.0))
        self.assertAlmostEqual(features["pitch_shift_semitones"], 12.0, places=6)
        self.assertAlmostEqual(features["rate_ratio"], 1.25, places=6)

    def test_aggregate_counts_flags(self):
        report = evaluate_takes(
            metrics(),
            [metrics(f0=182.0), metrics(f0=260.0, clip="wild.wav")],
        )
        self.assertEqual(report["aggregate"]["count"], 2)
        self.assertEqual(report["aggregate"]["clean"], 1)
        self.assertEqual(
            report["aggregate"]["flagCounts"], {"clone_pitch_register_mismatch": 1}
        )


if __name__ == "__main__":
    unittest.main()
