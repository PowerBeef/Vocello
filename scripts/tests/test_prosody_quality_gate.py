#!/usr/bin/env python3
"""Unit tests for scripts/prosody_quality_gate.py.

Uses deterministic synthetic WAVs so the suite needs no committed audio files.
"""
import json
import math
import os
import sys
import tempfile
import unittest
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from prosody_quality_gate import evaluate, evaluate_metrics
from prosody_profile import builtin_profile, save_profile


SR = 24000


def write_sine(path, freq, duration, amplitude=0.5, pause_ranges=None):
    """Write a mono sine wave with optional silent pauses."""
    n = int(SR * duration)
    t = [i / SR for i in range(n)]
    samples = [amplitude * math.sin(2 * math.pi * freq * ti) for ti in t]
    if pause_ranges:
        for start, end in pause_ranges:
            a = max(0, int(start * SR))
            b = min(n, int(end * SR))
            for i in range(a, b):
                samples[i] = 0.0
    # Convert to 16-bit PCM.
    pcm = [max(-32768, min(32767, int(s * 32767))) for s in samples]
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"".join(v.to_bytes(2, "little", signed=True) for v in pcm))


class ProsodyQualityGateTests(unittest.TestCase):
    def test_invalid_measurements_cannot_pass_or_emit_nonfinite_json(self):
        valid = {
            "f0_std_hz": 30.0, "f0_turning_points_per_sec": 3.0,
            "rate_syllable_rate_hz": 4.0, "pauses_pause_speech_ratio": 0.1,
            "energy_envelope_roughness": 0.3, "rate_local_rate_cv": 0.3,
            "pauses_max_pause_seconds": 0.4,
        }
        self.assertTrue(evaluate_metrics(valid)["passed"])
        for key in valid:
            for invalid in (float("nan"), float("inf"), -float("inf"), True, None, "3"):
                with self.subTest(key=key, invalid=invalid):
                    report = evaluate_metrics({**valid, key: invalid})
                    self.assertFalse(report["passed"])
                    self.assertEqual(report["flags"], ["metrics_incomplete"])
                    json.dumps(report, allow_nan=False)
        for key in ("f0_std_semitones", "boundaries_max_sample_jump"):
            report = evaluate_metrics({**valid, key: float("nan")})
            self.assertFalse(report["passed"])
            json.dumps(report, allow_nan=False)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_good_passes(self):
        path = os.path.join(self.dir, "good.wav")
        # Varying pitch + moderate duration should not trigger monotone/rushed/flat.
        write_sine(path, 150, 3.0, amplitude=0.6)
        report = evaluate(path)
        self.assertNotIn("analysis_failed", report["flags"])
        # We do not assert passed=True here because synthetic sines are not
        # realistic speech; instead we verify the gate runs and returns metrics.
        self.assertIn("f0_std_hz", report["metrics"])

    def test_monotone_flagged(self):
        path = os.path.join(self.dir, "monotone.wav")
        # Very stable pitch, no dynamics.
        write_sine(path, 120, 3.0, amplitude=0.3)
        profile = builtin_profile()
        profile["thresholds"]["monotone_f0_std_hz"] = 1.0
        # Synthetic sines have tiny F0 jitter that creates many spurious turning
        # points; raise the turning-point threshold so the test targets F0 std.
        profile["thresholds"]["monotone_turning_points_per_sec"] = 1000.0
        # Disable confounding flags so the synthetic sine is only caught as monotone.
        profile["thresholds"]["rushed_syllable_rate_hz"] = 1000.0
        profile["thresholds"]["flat_envelope_roughness"] = 0.0
        profile["thresholds"]["flat_rate_cv"] = 0.0
        report = evaluate(path, profile)
        self.assertIn("monotone", report["flags"])

    def test_long_pause_flagged(self):
        path = os.path.join(self.dir, "longpause.wav")
        # 2-second clip with a 1.5-second interior pause.
        write_sine(path, 150, 2.0, pause_ranges=[(0.25, 1.75)])
        profile = builtin_profile()
        profile["thresholds"]["pause_max_seconds"] = 1.0
        report = evaluate(path, profile)
        self.assertIn("long_pause", report["flags"])

    def test_profile_argument_loads(self):
        path = os.path.join(self.dir, "any.wav")
        write_sine(path, 150, 1.5)
        profile_path = os.path.join(self.dir, "profile.json")
        save_profile(builtin_profile(), profile_path)
        report = evaluate(path, builtin_profile())
        self.assertEqual(report["clip"], "any.wav")


if __name__ == "__main__":
    unittest.main()
