#!/usr/bin/env python3
"""Deterministic contracts for the bounded prosody analyzer."""

from __future__ import annotations

import math
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import wave

import numpy as np

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

from analyze_prosody import ANALYZER_ALGORITHM_VERSION, analyze
from prosody_quality_gate import evaluate


SAMPLE_RATE = 24_000


def write_pcm16(path: Path, samples: np.ndarray, channels: int = 1) -> None:
    pcm = np.clip(np.rint(samples * 32767.0), -32768, 32767).astype("<i2")
    if channels > 1:
        pcm = np.repeat(pcm[:, None], channels, axis=1).reshape(-1)
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(2)
        writer.setframerate(SAMPLE_RATE)
        writer.writeframes(pcm.tobytes())


def sine(duration: float, frequency: float = 150.0, amplitude: float = 0.55) -> np.ndarray:
    count = int(round(duration * SAMPLE_RATE))
    time = np.arange(count, dtype=np.float64) / SAMPLE_RATE
    return amplitude * np.sin(2.0 * math.pi * frequency * time)


def modulated_sine(duration: float) -> np.ndarray:
    count = int(round(duration * SAMPLE_RATE))
    time = np.arange(count, dtype=np.float64) / SAMPLE_RATE
    frequency = 155.0 + 38.0 * np.sin(2.0 * math.pi * 1.4 * time)
    phase = np.cumsum(2.0 * math.pi * frequency / SAMPLE_RATE)
    return 0.55 * np.sin(phase)


def harmonic_tone(
    duration: float,
    frequency: float = 150.0,
    amplitude: float = 0.55,
    harmonics: int = 12,
    tilt: float = 1.0,
) -> np.ndarray:
    """Periodic tone with a controllable harmonic roll-off.

    ``tilt`` scales how fast partial amplitude falls with harmonic number: a
    larger tilt darkens the spectrum (more low-frequency dominance).
    """
    count = int(round(duration * SAMPLE_RATE))
    time = np.arange(count, dtype=np.float64) / SAMPLE_RATE
    signal = np.zeros(count, dtype=np.float64)
    for index in range(1, harmonics + 1):
        if index * frequency >= SAMPLE_RATE / 2:
            break
        signal += (index ** -tilt) * np.sin(2.0 * math.pi * index * frequency * time)
    peak = float(np.max(np.abs(signal))) or 1.0
    return amplitude * signal / peak


def noisy_tone(duration: float, noise_ratio: float, frequency: float = 150.0) -> np.ndarray:
    """Harmonic tone mixed with deterministic broadband noise (breathiness)."""
    tone = harmonic_tone(duration, frequency=frequency)
    generator = np.random.default_rng(20260802)
    noise = generator.standard_normal(len(tone))
    noise /= float(np.max(np.abs(noise))) or 1.0
    mixed = (1.0 - noise_ratio) * tone + noise_ratio * noise
    peak = float(np.max(np.abs(mixed))) or 1.0
    return 0.55 * mixed / peak


def tremolo_tone(duration: float, depth_hz: float, rate_hz: float = 9.0) -> np.ndarray:
    """Periodic tone whose F0 wobbles quickly -- a tremor/shakiness fixture."""
    count = int(round(duration * SAMPLE_RATE))
    time = np.arange(count, dtype=np.float64) / SAMPLE_RATE
    frequency = 150.0 + depth_hz * np.sin(2.0 * math.pi * rate_hz * time)
    phase = np.cumsum(2.0 * math.pi * frequency / SAMPLE_RATE)
    return 0.55 * np.sin(phase)


class AnalyzeProsodyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_working_set_is_bounded_independently_of_duration(self) -> None:
        short = self.directory / "short.wav"
        long = self.directory / "long.wav"
        write_pcm16(short, sine(3.0))
        write_pcm16(long, sine(15.0))

        short_report = analyze(str(short))
        long_report = analyze(str(long))

        self.assertNotIn("error", short_report)
        self.assertNotIn("error", long_report)
        self.assertTrue(short_report["analysisWorkingSetDurationBounded"])
        self.assertEqual(short_report["analysisPassCount"], 2)
        self.assertLessEqual(
            abs(
                short_report["analysisMeasuredPeakManagedBufferBytes"]
                - long_report["analysisMeasuredPeakManagedBufferBytes"]
            ),
            int(SAMPLE_RATE * 0.04) * 8,
        )
        self.assertEqual(
            short_report["analysisEstimatedPeakWorkingSetBytes"],
            long_report["analysisEstimatedPeakWorkingSetBytes"],
        )

    def test_repeated_analysis_is_deterministic(self) -> None:
        path = self.directory / "deterministic.wav"
        write_pcm16(path, modulated_sine(4.0))
        self.assertEqual(analyze(str(path)), analyze(str(path)))

    def test_existing_gate_keys_remain_compatible(self) -> None:
        path = self.directory / "consumer.wav"
        write_pcm16(path, modulated_sine(3.0))
        report = analyze(str(path))
        established = {
            "f0_std_hz",
            "f0_turning_points_per_sec",
            "rate_syllable_rate_hz",
            "rate_local_rate_cv",
            "pauses_pause_speech_ratio",
            "pauses_max_pause_seconds",
            "energy_envelope_roughness",
            "rate_cv",
            "pause_ratio",
            "energy_roughness",
        }
        self.assertTrue(established.issubset(report))
        gate = evaluate(str(path))
        self.assertEqual(gate["analyzerAlgorithmVersion"], ANALYZER_ALGORITHM_VERSION)
        self.assertIn("analyzer_peak_working_set_bytes", gate["metrics"])

    def test_silence_gap_spanning_declared_boundary_is_retained(self) -> None:
        path = self.directory / "pause-boundary.wav"
        samples = sine(2.0)
        samples[int(0.75 * SAMPLE_RATE):int(1.25 * SAMPLE_RATE)] = 0.0
        write_pcm16(path, samples)
        report = analyze(str(path), boundary_seconds=[1.0])
        self.assertGreaterEqual(report["pauses_max_pause_seconds"], 0.45)
        self.assertEqual(report["boundaries_observed_count"], 1)
        self.assertEqual(report["boundaries_silence_overlap_count"], 1)

    def test_click_and_clipping_are_counted(self) -> None:
        path = self.directory / "click.wav"
        samples = np.zeros(SAMPLE_RATE, dtype=np.float64)
        midpoint = SAMPLE_RATE // 2
        samples[midpoint] = 1.0
        samples[midpoint + 1] = -1.0
        write_pcm16(path, samples)
        report = analyze(str(path), boundary_seconds=[midpoint / SAMPLE_RATE])
        self.assertGreaterEqual(report["signal_clipping_count"], 2)
        self.assertGreaterEqual(report["signal_click_count"], 2)
        self.assertGreater(report["boundaries_max_sample_jump"], 0.9)

    def test_pitch_flattening_reduces_semitone_spread(self) -> None:
        flat = self.directory / "flat.wav"
        expressive = self.directory / "expressive.wav"
        write_pcm16(flat, sine(5.0))
        write_pcm16(expressive, modulated_sine(5.0))
        flat_report = analyze(str(flat))
        expressive_report = analyze(str(expressive))
        self.assertGreater(
            expressive_report["f0_std_semitones"],
            flat_report["f0_std_semitones"] + 0.2,
        )
        self.assertGreater(
            expressive_report["f0_range_semitones"],
            flat_report["f0_range_semitones"] + 0.5,
        )

    def test_f0_median_tracks_ground_truth_across_supported_voice_range(self) -> None:
        # Harmonic fixtures resemble voiced speech more closely than a pure
        # sine. Cover low through high Built-in Voice fundamentals so octave
        # errors or a speaker-biased pitch anchor fail deterministically.
        for frequency in (80.0, 100.0, 150.0, 220.0, 300.0, 390.0):
            path = self.directory / f"f0-{int(frequency)}.wav"
            write_pcm16(path, harmonic_tone(2.0, frequency=frequency))
            report = analyze(str(path))
            self.assertNotIn("error", report)
            self.assertAlmostEqual(
                report["f0_median_hz"],
                frequency,
                delta=max(1.0, frequency * 0.01),
                msg=f"pitch tracking drifted at {frequency} Hz",
            )

    def test_stereo_downmix_remains_supported(self) -> None:
        path = self.directory / "stereo.wav"
        write_pcm16(path, sine(2.0), channels=2)
        report = analyze(str(path))
        self.assertNotIn("error", report)
        self.assertGreater(report["f0_median_hz"], 0)

    def test_float_nan_wav_fails_closed_instead_of_reporting_finite_pcm(self) -> None:
        # stdlib wave can wrap the bytes, but Vocello's quality contract accepts
        # PCM16 only.  NaN/Inf therefore cannot exist in a supported persisted
        # WAV and an IEEE-float payload must fail before signal claims are made.
        path = self.directory / "float-nan.wav"
        with wave.open(str(path), "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(4)
            writer.setframerate(SAMPLE_RATE)
            writer.writeframes(struct.pack("<f", math.nan) * SAMPLE_RATE)
        report = analyze(str(path))
        self.assertIn("error", report)
        self.assertIn("expected 16-bit PCM", report["error"])

    def test_invalid_or_unsorted_boundaries_fail_closed(self) -> None:
        path = self.directory / "boundaries.wav"
        write_pcm16(path, sine(2.0))
        self.assertIn("error", analyze(str(path), boundary_seconds=[1.0, 0.5]))
        self.assertIn("error", analyze(str(path), boundary_seconds=[2.0]))


class VoiceQualityFeatureTests(unittest.TestCase):
    """Ground-truth contracts for the v3 valence / voice-quality block.

    Each fixture manipulates exactly one acoustic property, so a feature that
    responds to the wrong fixture is a real defect rather than a tuning choice.
    """

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _analyze(self, name: str, samples: np.ndarray) -> dict:
        path = self.directory / name
        write_pcm16(path, samples)
        report = analyze(str(path))
        self.assertNotIn("error", report, msg=report.get("error"))
        return report

    def test_added_noise_lowers_hnr_and_cepstral_peak_prominence(self) -> None:
        clean = self._analyze("clean.wav", harmonic_tone(2.0))
        breathy = self._analyze("breathy.wav", noisy_tone(2.0, noise_ratio=0.55))
        self.assertLess(breathy["voice_hnr_db_mean"], clean["voice_hnr_db_mean"])
        self.assertLess(breathy["voice_cpp_db_mean"], clean["voice_cpp_db_mean"])

    def test_frame_jitter_responds_to_pitch_instability_only(self) -> None:
        steady = self._analyze("steady.wav", tremolo_tone(2.0, depth_hz=0.0))
        shaky = self._analyze("shaky.wav", tremolo_tone(2.0, depth_hz=12.0))
        self.assertGreater(shaky["voice_frame_jitter_pct"], steady["voice_frame_jitter_pct"])
        # A pitch wobble must not masquerade as a spectral-balance change.
        self.assertAlmostEqual(
            shaky["spectral_alpha_ratio_db"], steady["spectral_alpha_ratio_db"], delta=6.0
        )

    def test_spectral_balance_tracks_harmonic_tilt(self) -> None:
        # 40 harmonics of 150 Hz reach 6 kHz, so the >4 kHz share is exercised.
        bright = self._analyze("bright.wav", harmonic_tone(2.0, harmonics=40, tilt=0.3))
        dark = self._analyze("dark.wav", harmonic_tone(2.0, harmonics=40, tilt=2.0))
        # Alpha ratio is low-band over high-band energy: a darker tone raises it.
        self.assertGreater(dark["spectral_alpha_ratio_db"], bright["spectral_alpha_ratio_db"])
        self.assertGreater(dark["spectral_hammarberg_db"], bright["spectral_hammarberg_db"])
        self.assertGreater(bright["spectral_centroid_hz"], dark["spectral_centroid_hz"])
        self.assertGreater(bright["spectral_hf_energy_ratio"], dark["spectral_hf_energy_ratio"])

    def test_voice_quality_block_is_deterministic(self) -> None:
        samples = noisy_tone(1.5, noise_ratio=0.3)
        first = self._analyze("determinism-a.wav", samples)
        second = self._analyze("determinism-b.wav", samples)
        for key, value in first.items():
            if key.startswith(("voice_", "spectral_")):
                self.assertEqual(value, second[key], msg=key)

    def test_new_block_preserves_the_v2_key_surface(self) -> None:
        report = self._analyze("surface.wav", harmonic_tone(1.5))
        for key in (
            "f0_median_hz", "f0_std_semitones", "rate_syllable_rate_hz", "rate_cv",
            "pauses_pause_speech_ratio", "pause_ratio", "energy_envelope_roughness",
            "energy_roughness", "signal_peak", "boundaries_requested_count",
        ):
            self.assertIn(key, report)
        self.assertEqual(report["analyzerAlgorithmVersion"], ANALYZER_ALGORITHM_VERSION)
        self.assertTrue(report["analysisWorkingSetDurationBounded"])

    def test_working_set_stays_bounded_with_the_spectral_pass(self) -> None:
        short = self._analyze("short-spectral.wav", harmonic_tone(1.0))
        long = self._analyze("long-spectral.wav", harmonic_tone(6.0))
        # The measured figure varies only by the pre-existing rolling frame
        # buffer, which the reader observes twice (alone and inside the
        # concatenation), so the bound is two analysis frames.  The spectral
        # pass owns fixed-width spectra and must add nothing duration-dependent.
        frame_bytes = int(SAMPLE_RATE * 0.04) * 8
        self.assertLessEqual(
            abs(
                short["analysisMeasuredPeakManagedBufferBytes"]
                - long["analysisMeasuredPeakManagedBufferBytes"]
            ),
            2 * frame_bytes,
        )
        self.assertEqual(
            short["analysisEstimatedPeakWorkingSetBytes"],
            long["analysisEstimatedPeakWorkingSetBytes"],
        )

    def test_silent_clip_reports_zeroed_voice_quality_without_failing(self) -> None:
        report = self._analyze("silence.wav", np.zeros(SAMPLE_RATE, dtype=np.float64))
        self.assertEqual(report["voice_hnr_db_mean"], 0.0)
        self.assertEqual(report["spectral_measured_frames"], 0)


if __name__ == "__main__":
    unittest.main()
