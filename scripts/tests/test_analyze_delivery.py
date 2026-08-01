#!/usr/bin/env python3
"""Unit tests for scripts/analyze_delivery.py.

Deterministic synthetic WAVs, mirroring test_prosody_quality_gate.py, so the
suite needs no committed audio.
"""
import math
import os
import sys
import tempfile
import unittest
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from analyze_delivery import analyze


SR = 24000


def write_sine(path, freq, duration, amplitude=0.5):
    n = int(SR * duration)
    samples = [amplitude * math.sin(2 * math.pi * freq * i / SR) for i in range(n)]
    pcm = [max(-32768, min(32767, int(s * 32767))) for s in samples]
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"".join(v.to_bytes(2, "little", signed=True) for v in pcm))


class AnalyzeDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_reports_expected_keys_for_valid_clip(self):
        path = os.path.join(self.dir, "tone.wav")
        write_sine(path, 150, 2.0)
        report = analyze(path)
        self.assertNotIn("error", report)
        for key in ("clip", "durationSec", "f0_median_hz", "f0_range_hz",
                    "voiced_frac", "syllable_rate_hz", "rms_voiced_db",
                    "n_voiced_frames"):
            self.assertIn(key, report)
        self.assertEqual(report["clip"], "tone.wav")
        self.assertAlmostEqual(report["durationSec"], 2.0, places=2)

    def test_f0_tracks_the_sine_frequency(self):
        path = os.path.join(self.dir, "a150.wav")
        write_sine(path, 150, 2.0)
        report = analyze(path)
        self.assertGreater(report["n_voiced_frames"], 0)
        self.assertAlmostEqual(report["f0_median_hz"], 150.0, delta=5.0)
        self.assertGreater(report["voiced_frac"], 0.5)

    def test_too_short_clip_reports_error(self):
        path = os.path.join(self.dir, "blip.wav")
        write_sine(path, 150, 0.01)
        report = analyze(path)
        self.assertEqual(report.get("error"), "too_short")


if __name__ == "__main__":
    unittest.main()
