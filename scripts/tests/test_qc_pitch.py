#!/usr/bin/env python3
"""QC v2 pitch helpers on synthetic tracks and tones."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

import numpy as np

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

from qc import pitch  # noqa: E402

HOP = 0.01


def track(*segments: tuple[float, float | None], hop: float = HOP) -> dict:
    """A pitch-schema mapping from `(seconds, hz or None)` segments."""
    f0: list[float | None] = []
    for seconds, hz in segments:
        f0.extend([hz] * int(round(seconds / hop)))
    return {"hopSeconds": hop, "f0Hz": f0, "confidence": [0.0 if v is None else 0.9 for v in f0]}


def intonation(seconds: float, base: float = 150.0, depth_st: float = 3.0, rate: float = 3.0, hop: float = HOP) -> list[float]:
    times = np.arange(int(round(seconds / hop))) * hop
    return list(base * 2.0 ** (depth_st * np.sin(2 * np.pi * rate * times) / 12.0))


class AgreementTests(unittest.TestCase):
    def test_step_seen_by_both_trackers_agrees_and_counts_as_an_octave_jump(self) -> None:
        a = track((1.0, 200.0), (1.0, 400.0))
        # The second tracker runs at SwiftF0's 16 ms hop and reads 20 cents sharp.
        sharp = 2.0 ** (20 / 1200)
        b = track((1.0, 200.0 * sharp), (1.0, 400.0 * sharp), hop=0.016)
        agreement = pitch.agreeing_frames(a, b)
        self.assertAlmostEqual(agreement.hop, HOP)
        summary = agreement.summary()
        self.assertGreater(summary["agreeRatio"], 0.97)
        # Only the frame or two where the 16 ms grid straddles the step may disagree.
        self.assertLessEqual(summary["octaveDisagreements"], 2)
        jumps = pitch.octave_jumps(agreement)
        self.assertEqual(len(jumps), 1)
        self.assertAlmostEqual(jumps[0].jump_st, 12.0, delta=0.2)
        self.assertAlmostEqual(jumps[0].time, 1.0, delta=0.03)

    def test_one_tracker_octave_error_is_flagged_but_never_counts_as_a_jump(self) -> None:
        a = track((2.0, 200.0))
        b = track((0.9, 200.0), (0.2, 100.0), (0.9, 200.0))
        agreement = pitch.agreeing_frames(a, b)
        self.assertEqual(int(agreement.octave.sum()), 20)
        self.assertFalse(agreement.agree[95:105].any())
        self.assertEqual(pitch.octave_jumps(agreement), [])
        self.assertAlmostEqual(pitch.take_median_semitones(agreement), 12.0, places=6)

    def test_voicing_drop_by_one_tracker_leaves_a_gap_not_a_jump(self) -> None:
        a = track((1.0, 220.0), (0.2, None), (1.0, 220.0))
        b = track((2.2, 220.0))
        agreement = pitch.agreeing_frames(a, b)
        self.assertEqual(int(agreement.both_voiced.sum()), 200)
        self.assertEqual(pitch.octave_jumps(agreement), [])

    def test_schema_mapping_with_nulls_and_result_envelope_are_accepted(self) -> None:
        mapping = {"outputs": {"hopSeconds": 0.02, "f0Hz": [None, 100.0, 0.0, 200.0], "confidence": [0, 1, 0, 1]}}
        source = pitch.as_track(mapping)
        self.assertEqual(source.voiced.tolist(), [False, True, False, True])
        self.assertAlmostEqual(source.semitones[3], 12.0)


class RegisterTests(unittest.TestCase):
    def test_take_median_and_register_offset(self) -> None:
        self.assertAlmostEqual(pitch.take_median_semitones(track((1.0, 200.0))), 12.0)
        self.assertIsNone(pitch.take_median_semitones(track((1.0, None))))
        self.assertAlmostEqual(pitch.register_offset(14.5, 12.0), 2.5)
        self.assertIsNone(pitch.register_offset(None, 12.0))


class SustainedShiftTests(unittest.TestCase):
    def test_six_semitone_shift_held_half_a_second_is_detected(self) -> None:
        shifted = 200.0 * 2.0 ** (6 / 12)
        result = pitch.sustained_shifts(track((2.0, 200.0), (0.5, shifted), (1.0, 200.0)))
        self.assertTrue(result.detected)
        self.assertAlmostEqual(result.take_median_st, 12.0, places=6)
        self.assertAlmostEqual(result.shift_st, 6.0, places=4)
        self.assertAlmostEqual(result.start, 2.0, delta=0.03)
        self.assertAlmostEqual(result.end, 2.5, delta=0.03)
        self.assertEqual(result.to_dict()["detected"], True)

    def test_downward_shift_is_signed(self) -> None:
        lowered = 200.0 * 2.0 ** (-8 / 12)
        result = pitch.sustained_shifts(track((2.0, 200.0), (0.6, lowered), (1.0, 200.0)))
        self.assertTrue(result.detected)
        self.assertAlmostEqual(result.shift_st, -8.0, places=4)

    def test_brief_excursion_is_not_sustained(self) -> None:
        spike = 200.0 * 2.0 ** (9 / 12)
        result = pitch.sustained_shifts(track((1.5, 200.0), (0.1, spike), (1.5, 200.0)))
        self.assertFalse(result.detected)
        self.assertLess(abs(result.shift_st), 6.0)

    def test_ordinary_intonation_is_not_a_shift(self) -> None:
        result = pitch.sustained_shifts({"hopSeconds": HOP, "f0Hz": intonation(3.0)})
        self.assertFalse(result.detected)


SR = 16_000


def harmonic_voice(f0: np.ndarray, sr: int, hop: float, seed: int = 0) -> np.ndarray:
    """A speech-like source: harmonics with a 1/k rolloff and a little noise, following `f0`."""
    samples = int(round(f0.size * hop * sr))
    per_sample = np.interp(np.arange(samples) / sr, np.arange(f0.size) * hop, f0)
    phase = 2 * np.pi * np.cumsum(per_sample) / sr
    voice = np.zeros(samples)
    for k in range(1, 30):
        voice += np.where(k * per_sample < sr / 2, np.sin(k * phase) / k, 0.0)
    voice = 0.3 * voice / np.abs(voice).max()
    return voice + 0.01 * np.random.default_rng(seed).standard_normal(samples)


class ToneRunTests(unittest.TestCase):
    def test_voice_collapsing_into_a_730_hz_tone_is_detected(self) -> None:
        speech = intonation(1.0)
        tone = [730.0] * 60
        f0 = np.array(speech + tone + intonation(1.0, base=140.0))
        audio = harmonic_voice(f0, SR, HOP)
        start, end = int(1.0 * SR), int(1.6 * SR)
        t = np.arange(end - start) / SR
        audio[start:end] = 0.3 * np.sin(2 * np.pi * 730.0 * t)
        result = pitch.tone_runs({"hopSeconds": HOP, "f0Hz": list(f0)}, audio, SR)
        self.assertTrue(result.detected)
        self.assertTrue(result.tone_like)
        self.assertAlmostEqual(result.start, 1.0, delta=0.02)
        self.assertAlmostEqual(result.end, 1.6, delta=0.02)
        self.assertAlmostEqual(result.median_hz, 730.0, delta=1.0)
        self.assertLess(result.std_st, 0.3)
        self.assertLess(result.flatness, 0.005)
        self.assertGreater(result.hnr_db, 25.0)

    def test_tone_seen_only_through_agreeing_frames(self) -> None:
        a = {"hopSeconds": HOP, "f0Hz": intonation(1.0) + [730.0] * 50}
        b = {"hopSeconds": HOP, "f0Hz": intonation(1.0) + [730.0 * 2 ** (10 / 1200)] * 50}
        result = pitch.tone_runs(pitch.agreeing_frames(a, b))
        self.assertTrue(result.detected)
        self.assertAlmostEqual(result.duration, 0.5, delta=0.02)
        self.assertFalse(result.tone_like)  # no audio, so no spectral evidence

    def test_intonated_speech_is_not_a_tone(self) -> None:
        f0 = np.array(intonation(2.0))
        audio = harmonic_voice(f0, SR, HOP)
        result = pitch.tone_runs({"hopSeconds": HOP, "f0Hz": list(f0)}, audio, SR)
        self.assertFalse(result.detected)
        self.assertFalse(result.tone_like)

    def test_steady_but_noisy_span_is_detected_but_not_tone_like(self) -> None:
        f0 = np.array([300.0] * 60)
        noise = 0.2 * np.random.default_rng(1).standard_normal(int(0.6 * SR))
        result = pitch.tone_runs({"hopSeconds": HOP, "f0Hz": list(f0)}, noise, SR)
        self.assertTrue(result.detected)
        self.assertFalse(result.tone_like)
        self.assertGreater(result.flatness, 0.1)

    def test_unvoiced_track(self) -> None:
        result = pitch.tone_runs(track((1.0, None)))
        self.assertFalse(result.detected)
        self.assertEqual(result.duration, 0.0)


class SummaryTests(unittest.TestCase):
    def test_summary_of_two_runner_outputs_is_json_ready(self) -> None:
        f0 = intonation(1.0) + [730.0] * 60 + intonation(1.0)
        rmvpe = {"hopSeconds": HOP, "f0Hz": f0, "confidence": [0.9] * len(f0)}
        swift = {"hopSeconds": 0.016, "f0Hz": [f0[int(round(i * 1.6))] for i in range(int(len(f0) / 1.6))]}
        audio = harmonic_voice(np.array(f0), SR, HOP)
        summary = pitch.summarize(rmvpe, swift, audio, SR)
        json.dumps(summary, allow_nan=False)
        self.assertGreater(summary["agreement"]["agreeRatio"], 0.9)
        self.assertTrue(summary["toneRun"]["detected"])
        self.assertAlmostEqual(summary["toneRun"]["medianHz"], 730.0, delta=1.0)
        self.assertEqual(sorted(summary), ["agreement", "octaveJumps", "sustainedShift", "takeMedianSt", "toneRun"])


if __name__ == "__main__":
    unittest.main()
