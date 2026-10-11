"""Acoustic nomination behavior on deterministic signals, never quality labels."""
import unittest
from unittest.mock import patch

import numpy as np

from qc import acoustics, candidates


RATE = 16000


def tone(duration=1.):
    t = np.arange(round(RATE * duration)) / RATE
    return (.1 * np.sin(2 * np.pi * 120 * t)).astype(np.float32)


def burst(start=.44, end=.50):
    raw = np.zeros(RATE, dtype=np.float32)
    raw[round(start * RATE):round(end * RATE)] = tone()[round(start * RATE):round(end * RATE)]
    return raw


def analyze(raw, expected=None, recognized=None, **settings):
    return acoustics.analyze(raw, RATE, expected_windows=expected, recognized_windows=recognized,
                             **settings).get("candidateProducers", {})


class AcousticCandidatesTests(unittest.TestCase):
    def setUp(self):
        self.window = [{"start": .44, "end": .48, "phone": "y", "source": "phones"}]
        self.noisy = tone()
        self.noisy[int(.4 * RATE):int(.54 * RATE)] = np.random.default_rng(71).normal(0, .03, int(.14 * RATE))

    def test_low_periodicity_expected_vowel_is_nominated_without_recognizer_error(self):
        report = analyze(self.noisy, self.window)["phonation-anomaly"]
        self.assertEqual(report["inputStatus"], "complete")
        self.assertTrue(report["candidates"])
        event = report["candidates"][0]
        self.assertLess(event["start"], .48)
        self.assertGreater(event["end"], .44)
        self.assertEqual(event["class"], "phonation-anomaly")
        self.assertEqual(event["expectedTargets"][0]["source"], "phones")
        self.assertIn("candidate-is-not-a-whisper-verdict", event["uncertainties"])
        self.assertEqual(report["decision"], "not-assessed")

    def test_periodic_vowel_and_unvoiced_fricative_do_not_become_whisper_candidates(self):
        self.assertFalse(analyze(tone(), self.window)["phonation-anomaly"]["candidates"])
        fricative = [dict(self.window[0], phone="s")]
        result = analyze(self.noisy, fricative)["phonation-anomaly"]
        self.assertFalse(result["candidates"])
        self.assertEqual(result["reason"], "no-eligible-expected-sonorants")

    def test_noise_outside_eligible_context_does_not_nominate_that_phone(self):
        away = [dict(self.window[0], start=.75, end=.8)]
        self.assertFalse(analyze(self.noisy, away)["phonation-anomaly"]["candidates"])

    def test_silence_does_not_become_zero_pitch_or_whisper(self):
        result = acoustics.analyze(np.zeros(RATE), RATE, expected_windows=self.window)
        self.assertFalse(result["candidateProducers"]["phonation-anomaly"]["candidates"])
        self.assertEqual(result["candidateProducers"]["phonation-anomaly"]["inputStatus"], "unavailable")
        self.assertIsNone(result["summary"]["pitchWitnessMedianHz"])

    def test_missing_expected_windows_abstain_for_phonation(self):
        result = analyze(self.noisy)["phonation-anomaly"]
        self.assertEqual(result["inputStatus"], "unavailable")
        self.assertFalse(result["candidates"])

    def test_support_is_measured_in_each_target_context(self):
        raw = np.zeros(RATE, dtype=np.float32)
        raw[:int(.2 * RATE)] = tone()[:int(.2 * RATE)]
        silent = {"start": .8, "end": .85, "phone": "a"}
        result = analyze(raw, [silent])["phonation-anomaly"]
        self.assertEqual(result["inputStatus"], "unavailable")
        self.assertEqual(result["coverage"]["unsupportedTargets"], 1)
        mixed = analyze(raw, [{"start": .05, "end": .1, "phone": "a"}, silent])["phonation-anomaly"]
        self.assertEqual(mixed["inputStatus"], "partial")
        self.assertEqual(mixed["coverage"]["supportedTargets"], 1)

    def test_target_context_with_no_frame_centers_is_unavailable(self):
        raw = tone()
        # The final frame center is .9; the target lies in the unframed tail.
        target = [{"start": .99, "end": 1., "phone": "a"}]
        result = analyze(raw, target, window_seconds=.12, hop_seconds=.12)["phonation-anomaly"]
        self.assertEqual(result["inputStatus"], "unavailable")
        self.assertEqual(result["reason"], "no-signal-supported-target-contexts")

    def test_unsupported_spectral_bandwidth_does_not_claim_complete_phonation(self):
        report = acoustics.analyze(tone()[:2000], 2000, expected_windows=self.window)
        self.assertEqual(report["candidateProducers"]["phonation-anomaly"]["reason"], "no-supported-spectral-frames")

    def test_isolated_burst_outside_alignment_is_found_without_phone_error(self):
        anchor = [{"start": .8, "end": .9, "phone": "a"}]
        result = analyze(burst(), anchor)["short-fragment"]
        self.assertEqual(result["inputStatus"], "complete")
        self.assertEqual(len(result["candidates"]), 1)
        event = result["candidates"][0]
        self.assertLessEqual(event["start"], .44)
        self.assertGreaterEqual(event["end"], .50)
        self.assertEqual(event["alignmentCoverage"], "uncovered")
        self.assertEqual(event["status"], "candidate")
        self.assertEqual(result["decision"], "not-assessed")

    def test_either_alignment_inventory_prevents_claiming_unaligned_burst(self):
        for role in ("expected", "recognized"):
            with self.subTest(role=role):
                report = analyze(burst(), **{role: self.window})["short-fragment"]
                self.assertFalse(report["candidates"])
                self.assertEqual(report["coverage"]["alignedShortBursts"], 1)

    def test_audio_only_burst_has_unknown_alignment_and_partial_coverage(self):
        report = analyze(burst())["short-fragment"]
        self.assertEqual(report["inputStatus"], "partial")
        self.assertEqual(report["candidates"][0]["alignmentCoverage"], "unknown")

    def test_silence_edges_and_long_spans_do_not_acquire_short_fragment_events(self):
        for raw in (np.zeros(RATE), tone(), burst(0, .06), burst(.94, 1), burst(.3, .65)):
            with self.subTest():
                self.assertFalse(analyze(raw)["short-fragment"]["candidates"])

    def test_window_bounds_and_collection_budgets_preserve_missingness(self):
        for windows in ([{"start": True, "end": .5, "phone": "a"}],
                        [{"start": -.1, "end": .5, "phone": "a"}],
                        self.window * (candidates.MAX_WINDOWS + 1), iter(self.window)):
            with self.subTest():
                result = analyze(self.noisy, windows)
                self.assertEqual(result["phonation-anomaly"]["inputStatus"], "unavailable")
                self.assertNotEqual(result["short-fragment"]["inputStatus"], "complete")

    def test_provenance_and_candidate_output_budgets_are_explicit(self):
        result = analyze(self.noisy, self.window * (candidates.MAX_TARGETS + 1))["phonation-anomaly"]
        self.assertEqual(result["inputStatus"], "partial")
        self.assertTrue(result["candidates"][0]["targetProvenanceTruncated"])
        self.assertEqual(len(result["candidates"][0]["expectedTargets"]), candidates.MAX_TARGETS)
        raw = burst(.24, .3) + burst(.64, .7)
        with patch.object(candidates, "MAX_CANDIDATES", 1):
            result = analyze(raw)["short-fragment"]
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["reason"], "candidate-budget-exceeded")

    def test_invalid_audio_is_rejected_before_candidate_construction(self):
        for raw in (np.full(RATE, np.nan), np.full(RATE, 2.), np.zeros((2, RATE))):
            with self.subTest():
                report = acoustics.analyze(raw, RATE, expected_windows=self.window)
                self.assertEqual(report["inputStatus"], "unavailable")
                self.assertNotIn("candidateProducers", report)


if __name__ == "__main__":
    unittest.main()
