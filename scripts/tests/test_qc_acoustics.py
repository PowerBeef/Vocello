#!/usr/bin/env python3
"""Analytical signal controls for descriptive, model-independent QC acoustics."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qc import acoustics  # noqa: E402

RATE = 24000


def tone(hz=200, seconds=1., amplitude=.2, rate=RATE):
    return amplitude * np.sin(2 * np.pi * hz * np.arange(round(seconds * rate)) / rate)


class AcousticControlsTests(unittest.TestCase):
    def test_independent_pitch_witness_recovers_analytical_tones(self):
        for hz in (70, 100, 200, 400, 700):
            with self.subTest(hz=hz):
                value = acoustics.analyze(tone(hz), RATE)
                self.assertEqual(value["inputStatus"], "complete")
                self.assertAlmostEqual(value["summary"]["pitchWitnessMedianHz"], hz, delta=.15)
                self.assertGreater(value["summary"]["pitchWitnessFrameFraction"], .98)
                self.assertEqual(value["pitchWitness"]["startSeconds"], .03)
                self.assertEqual(value["decision"], "not-assessed")

    def test_stronger_second_harmonic_does_not_replace_known_fundamental(self):
        signal = tone(150, amplitude=.08) + tone(300, amplitude=.3)
        value = acoustics.analyze(signal, RATE)
        self.assertAlmostEqual(value["summary"]["pitchWitnessMedianHz"], 150, delta=.1)

    def test_gain_changes_level_without_changing_shape_or_pitch(self):
        signal = tone(150) + tone(300, amplitude=.07) + tone(450, amplitude=.03)
        a = acoustics.analyze(signal, RATE)
        b = acoustics.analyze(signal / 10, RATE, reference=a)
        self.assertAlmostEqual(b["summary"]["medianLevelDbfs"] - a["summary"]["medianLevelDbfs"], -20, places=4)
        for key in ("pitchWitnessMedianHz", "medianNormalizedAutocorrelation", "medianCepstralPeakContrast",
                    "medianSpectralFlatness", "medianSpectralTiltDbPerOctave", "medianHighToLowBandDb"):
            with self.subTest(key=key):
                self.assertAlmostEqual(a["summary"][key], b["summary"][key], places=5)
        self.assertAlmostEqual(b["referenceComparison"]["pitchWitnessRegisterShiftSt"], 0, places=4)

    def test_reference_octave_shift_is_signed_and_rate_independent(self):
        reference = acoustics.analyze(tone(100), RATE)
        take = acoustics.analyze(tone(200, rate=48000), 48000, reference=reference)
        self.assertAlmostEqual(take["referenceComparison"]["pitchWitnessRegisterShiftSt"], 12, delta=.01)
        reverse = acoustics.compare(reference, take)
        self.assertAlmostEqual(reverse["pitchWitnessRegisterShiftSt"], -12, delta=.01)
        self.assertEqual(reverse["decision"], "not-assessed")
        self.assertIn("no-calibrated-reference-tolerance", reverse["uncertainties"])

    def test_noise_retains_aperiodic_evidence_without_a_whisper_verdict(self):
        # Synthetic noise is an aperiodicity control, not a labeled human whisper.
        noise = np.random.default_rng(8).normal(0, .05, RATE)
        value = acoustics.analyze(noise, RATE,
                    expected_windows=[{"phone": "a", "start": .1, "end": .9, "voicedTarget": True}])
        voiced = acoustics.analyze(tone(), RATE)
        self.assertLess(value["summary"]["pitchWitnessFrameFraction"], .02)
        self.assertGreater(value["summary"]["medianSpectralFlatness"], .4)
        self.assertLess(value["summary"]["medianNormalizedAutocorrelation"], .3)
        self.assertGreater(value["summary"]["medianSpectralFlatness"], voiced["summary"]["medianSpectralFlatness"])
        window = value["expectedWindows"][0]
        self.assertEqual(window["inputStatus"], "complete")
        self.assertEqual(window["decision"], "not-assessed")
        self.assertIsNone(window["pitchWitnessMedianHz"])
        self.assertIn("no-periodic-pitch-candidate", window["uncertainties"])
        self.assertEqual(value["decision"], "not-assessed")

    def test_fricative_control_is_retained_separately_from_voiced_target(self):
        rng = np.random.default_rng(42)
        noise = rng.normal(0, .04, RATE // 2)
        fricative = np.diff(noise, prepend=noise[0])
        audio = np.concatenate((tone(180, seconds=.5), fricative))
        value = acoustics.analyze(audio, RATE, expected_windows=[
            {"phone": "a", "start": 0, "end": .5, "voicedTarget": True},
            {"phone": "s", "start": .5, "end": 1, "voicedTarget": False}])
        vowel, consonant = value["expectedWindows"]
        self.assertTrue(vowel["voicedTarget"])
        self.assertFalse(consonant["voicedTarget"])
        self.assertAlmostEqual(vowel["pitchWitnessMedianHz"], 180, delta=.1)
        self.assertIsNone(consonant["pitchWitnessMedianHz"])
        self.assertGreater(consonant["medianHighToLowBandDb"], vowel["medianHighToLowBandDb"])
        self.assertGreaterEqual(consonant["analysisSupportStart"], .5)
        self.assertLessEqual(vowel["analysisSupportEnd"], .5)

    def test_silent_ending_and_expected_windows_do_not_need_recognizer_errors(self):
        audio = np.concatenate((tone(seconds=.5), np.zeros(RATE // 2)))
        value = acoustics.analyze(audio, RATE, expected_windows=[
            {"phone": "a", "start": .1, "end": .4},
            {"phone": "i", "start": .65, "end": .95}], recognized_windows=[])
        self.assertEqual(len(value["intervals"]), 4)
        self.assertEqual(value["recognizedWindows"], [])
        self.assertEqual(len(value["expectedWindows"]), 2)
        ending = value["expectedWindows"][1]
        self.assertEqual(ending["medianLevelDbfs"], -240.)
        self.assertIsNone(ending["pitchWitnessMedianHz"])
        self.assertIsNone(ending["medianSpectralFlatness"])
        self.assertEqual(value["intervals"][-1]["medianLevelDbfs"], -240.)

    def test_short_boundary_windows_abstain_instead_of_borrowing_adjacent_sound(self):
        audio = np.concatenate((tone(seconds=.5), np.zeros(RATE // 2)))
        value = acoustics.analyze(audio, RATE, expected_windows=[
            {"phone": "a", "start": .49, "end": .51},
            {"phone": "a", "start": .1, "end": .43}])
        short, measured = value["expectedWindows"]
        self.assertEqual(short["inputStatus"], "unavailable")
        self.assertEqual(short["reason"], "no-full-analysis-frame")
        self.assertEqual(short["frames"], 0)
        self.assertGreaterEqual(measured["analysisSupportStart"], .1)
        self.assertLessEqual(measured["analysisSupportEnd"], .43)

    def test_silence_and_dc_do_not_invent_pitch_spectral_shape_or_reference_shift(self):
        reference = acoustics.analyze(tone(), RATE)
        for signal in (np.zeros(RATE), np.full(RATE, .2)):
            with self.subTest(level=float(signal[0])):
                value = acoustics.analyze(signal, RATE, reference=reference)
                self.assertEqual(value["summary"]["pitchWitnessFrames"], 0)
                self.assertIsNone(value["summary"]["medianNormalizedAutocorrelation"])
                self.assertIsNone(value["summary"]["medianCepstralPeakContrast"])
                self.assertIsNone(value["summary"]["medianSpectralFlatness"])
                self.assertIsNone(value["referenceComparison"]["pitchWitnessRegisterShiftSt"])
                self.assertEqual(value["referenceComparison"]["inputStatus"], "partial")
                json.dumps(value, allow_nan=False)

    def test_invalid_short_nonfinite_and_over_limit_audio_abstain(self):
        for signal, rate, options, reason in (
            (np.zeros(20), RATE, {}, "audio-shorter-than-analysis-window"),
            (np.full(RATE, np.nan), RATE, {}, "nonfinite-audio"),
            (np.full(RATE, np.inf), RATE, {}, "nonfinite-audio"),
            (np.zeros((RATE, 2)), RATE, {}, "audio-must-be-mono-real-numeric"),
            (tone(), RATE, {"max_seconds": .1}, "duration-limit-exceeded"),
            (tone(), RATE, {"batch_frames": 257}, "unsupported-analysis-settings"),
            (tone(), 0, {}, "invalid-analysis-settings"),
            (tone() * 10, RATE, {}, "audio-must-be-normalized-pcm"),
            (np.full(RATE, np.iinfo(np.int64).min), RATE, {}, "audio-must-be-normalized-pcm"),
            ([[1], [1, 2]], RATE, {}, "audio-must-be-mono-real-numeric"),
        ):
            with self.subTest(reason=reason):
                value = acoustics.analyze(signal, rate, **options)
                self.assertEqual(value["inputStatus"], "unavailable")
                self.assertEqual(value["reason"], reason)
                self.assertEqual(value["decision"], "not-assessed")
                json.dumps(value, allow_nan=False)

    def test_batch_size_does_not_change_measurement(self):
        signal = tone(170) + tone(340, amplitude=.03)
        one = acoustics.analyze(signal, RATE, batch_frames=1)
        many = acoustics.analyze(signal, RATE, batch_frames=128)
        self.assertEqual(one["summary"], many["summary"])
        self.assertEqual(one["pitchWitness"], many["pitchWitness"])
        self.assertEqual(one["intervals"], many["intervals"])

    def test_low_reference_coverage_and_incompatible_settings_remain_explicit(self):
        reference = acoustics.analyze(tone(seconds=.06), RATE)
        take = acoustics.analyze(tone(), RATE, reference=reference)
        self.assertEqual(take["referenceComparison"]["inputStatus"], "partial")
        self.assertIsNone(take["referenceComparison"]["pitchWitnessRegisterShiftSt"])
        incompatible = acoustics.analyze(tone(), RATE, window_seconds=.04)
        compared = acoustics.compare(take, incompatible)
        self.assertEqual(compared["reason"], "incompatible-analysis-settings")
        self.assertIsNone(compared["pitchWitnessRegisterShiftSt"])

    def test_invalid_windows_are_retained_and_window_collection_is_bounded(self):
        value = acoustics.analyze(tone(), RATE, expected_windows=[
            {"start": "bad", "end": .4}, {"start": .1, "end": float("nan")},
            {"start": -.1, "end": .4}, {"start": .1, "end": 1.1}, None])
        self.assertEqual(len(value["expectedWindows"]), 5)
        self.assertTrue(all(window["inputStatus"] == "unavailable" for window in value["expectedWindows"]))
        json.dumps(value, allow_nan=False)
        bounded = acoustics.analyze(tone(), RATE, expected_windows=(
            {"start": .1, "end": .2} for _ in range(acoustics.MAX_WINDOWS + 1)))
        self.assertEqual(len(bounded["expectedWindows"]), acoustics.MAX_WINDOWS)
        self.assertEqual(bounded["inputStatus"], "partial")
        self.assertIn("expected-window-limit-exceeded", bounded["uncertainties"])

    def test_malformed_reference_and_window_collection_abstain(self):
        take = acoustics.analyze(tone(), RATE)
        reference = acoustics.analyze(tone(), RATE)
        reference["summary"].pop("pitchWitnessMedianSemitones")
        compared = acoustics.compare(take, reference)
        self.assertEqual(compared["inputStatus"], "unavailable")
        self.assertEqual(compared["reason"], "malformed-audio-summary")
        value = acoustics.analyze(tone(), RATE, expected_windows=4)
        self.assertEqual(value["expectedWindows"][0]["reason"], "invalid-window-collection")
        self.assertEqual(value["decision"], "not-assessed")

    def test_bandwidth_and_unanalyzed_tail_are_reported(self):
        value = acoustics.analyze(tone(seconds=.993, rate=8000), 8000)
        self.assertIsNone(value["summary"]["medianHighToLowBandDb"])
        self.assertFalse(value["coverage"]["spectralFullBandAvailable"])
        self.assertGreater(value["coverage"]["tailUnanalyzedSeconds"], 0)
        self.assertLess(value["coverage"]["tailUnanalyzedSeconds"], .01)
        self.assertIn("insufficient-bandwidth-for-some-spectral-measures", value["uncertainties"])
        self.assertEqual(value["decision"], "not-assessed")


if __name__ == "__main__":
    unittest.main()
