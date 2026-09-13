"""Played-audio capture analysis: synthetic signals with known offsets, gains and holes."""

from __future__ import annotations

import datetime as dt
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import playback_capture as pc  # noqa: E402

WORLD_RATE = 48_000


def speech_like(rate: int, seconds: float = 3.0, seed: int = 7) -> np.ndarray:
    """Tone bursts with pauses: enough structure for alignment, silence for dropout tests."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(rate * seconds)) / rate
    signal = np.zeros_like(t)
    for start, stop in ((0.30, 0.95), (1.10, 1.85), (2.05, 2.70)):
        window = (t >= start) & (t < stop)
        fade = np.minimum(1.0, np.minimum(t - start, stop - t) / 0.03)
        tone = (0.35 * np.sin(2 * np.pi * 310 * t) + 0.20 * np.sin(2 * np.pi * 930 * t)
                + 0.10 * np.sin(2 * np.pi * 2210 * t)) * (1 + 0.3 * np.sin(2 * np.pi * 4.5 * t))
        signal += np.where(window, tone * np.maximum(fade, 0.0), 0.0)
    signal += rng.normal(0, 0.002, len(t))
    return signal


def delayed(world: np.ndarray, delay_ms: float, gain: float, rate: int = WORLD_RATE) -> np.ndarray:
    lead = np.zeros(int(round(rate * delay_ms / 1000)))
    return np.concatenate([lead, world * gain, np.zeros(rate // 2)])


class ResamplerTests(unittest.TestCase):
    def test_two_to_one_decimation_keeps_the_passband_and_kills_the_alias(self) -> None:
        t = np.arange(WORLD_RATE * 2) / WORLD_RATE
        tone = 0.5 * np.sin(2 * np.pi * 1000 * t)
        out = pc.resample(tone, WORLD_RATE, 24_000)
        middle = out[6000:-6000]
        gain_db = 20 * math.log10(float(np.sqrt(np.mean(middle ** 2))) / (0.5 / math.sqrt(2)))
        self.assertLess(abs(gain_db), 0.1)
        alias = pc.resample(0.5 * np.sin(2 * np.pi * 20_000 * t), WORLD_RATE, 24_000)[6000:-6000]
        self.assertLess(20 * math.log10(float(np.sqrt(np.mean(alias ** 2))) + 1e-12), -60)

    def test_rational_rate_keeps_the_passband(self) -> None:
        t = np.arange(44_100 * 2) / 44_100
        out = pc.resample(0.5 * np.sin(2 * np.pi * 1000 * t), 44_100, 24_000)
        middle = out[6000:-6000]
        gain_db = 20 * math.log10(float(np.sqrt(np.mean(middle ** 2))) / (0.5 / math.sqrt(2)))
        self.assertLess(abs(gain_db), 0.2)
        self.assertEqual(len(out), math.ceil(len(t) * 24_000 / 44_100))

    def test_same_rate_is_a_copy(self) -> None:
        x = np.arange(10, dtype=np.float64)
        self.assertTrue(np.array_equal(pc.resample(x, 24_000, 24_000), x))


class ComparisonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.world = speech_like(WORLD_RATE)
        self.reference = pc.resample(self.world, WORLD_RATE, 24_000)

    def test_offset_and_gain_are_recovered(self) -> None:
        capture = pc.resample(delayed(self.world, 137.0, 0.7), WORLD_RATE, 24_000)
        result = pc.compare(self.reference, capture, 24_000)
        self.assertAlmostEqual(result["alignmentMS"], 137.0, delta=1.0)
        self.assertAlmostEqual(result["gain"], 1 / 0.7, delta=0.02)
        self.assertLess(result["residualDBFS"], -40.0)
        self.assertGreaterEqual(result["coverage"], 0.99)
        self.assertEqual(result["dropoutCount"], 0.0)

    def test_a_hole_in_the_played_audio_is_one_dropout(self) -> None:
        played = delayed(self.world, 137.0, 0.7)
        hole_start = int(WORLD_RATE * (0.137 + 1.30))
        played[hole_start: hole_start + int(WORLD_RATE * 0.120)] = 0.0
        capture = pc.resample(played, WORLD_RATE, 24_000)
        result = pc.compare(self.reference, capture, 24_000)
        self.assertEqual(result["dropoutCount"], 1.0)
        self.assertAlmostEqual(result["maxGapMS"], 120.0, delta=20.0)

    def test_silence_does_not_align(self) -> None:
        self.assertIsNone(pc.align(self.reference, np.zeros(48_000), 24_000))
        self.assertEqual(pc.compare(self.reference, np.zeros(48_000), 24_000), {})


class HelperTests(unittest.TestCase):
    def test_step_burst_peak_counts_the_densest_window(self) -> None:
        signal = np.zeros(24_000)
        signal[4000:4030] = np.where(np.arange(30) % 2 == 0, 0.2, -0.2)
        count, start_ms = pc.step_burst_peak(signal, 24_000)
        self.assertEqual(count, 29)
        self.assertAlmostEqual(start_ms, 4001 * 1000 / 24_000, delta=0.05)
        self.assertEqual(pc.step_burst_peak(0.3 * np.sin(np.arange(24_000) / 10), 24_000)[0], 0)

    def test_first_audible_uses_the_runner_clock(self) -> None:
        capture = np.zeros(24_000)
        capture[12_000:] = 0.1
        sidecar = {"captureStartEpochMS": 1_000.0, "submitClickEpochMS": 800.0}
        self.assertAlmostEqual(pc.first_audible_ms(capture, 24_000, sidecar), 700.0, delta=pc.FRAME_MS)
        # The WAV starts at the first delivered buffer, which wins over the arming time.
        self.assertAlmostEqual(pc.first_audible_ms(capture, 24_000, {**sidecar, "firstBufferEpochMS": 1_500.0}),
                               1_200.0, delta=pc.FRAME_MS)
        self.assertIsNone(pc.first_audible_ms(np.zeros(24_000), 24_000, sidecar))
        self.assertIsNone(pc.first_audible_ms(capture, 24_000, {}))

    def test_wav_round_trips_float_and_pcm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            samples = 0.25 * np.sin(np.arange(2400) / 7)
            pc.write_wav_float32(Path(tmp, "f.wav"), 48_000, samples)
            pc.write_wav_int16(Path(tmp, "i.wav"), 24_000, samples)
            rate, back = pc.read_wav(Path(tmp, "f.wav"))
            self.assertEqual(rate, 48_000)
            self.assertLess(float(np.max(np.abs(back - samples))), 1e-6)
            rate, back = pc.read_wav(Path(tmp, "i.wav"))
            self.assertEqual(rate, 24_000)
            self.assertLess(float(np.max(np.abs(back - samples))), 1e-4)
            with self.assertRaises(pc.PlaybackCaptureError):
                Path(tmp, "x.wav").write_bytes(b"nope")
                pc.read_wav(Path(tmp, "x.wav"))

    def test_reference_resolution_uses_the_local_timestamp_window_and_duration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            clones = Path(tmp, "Clones")
            clones.mkdir()
            stamp = dt.datetime(2026, 9, 13, 14, 21, 32, 295_000)
            name = stamp.strftime("%Y%m%d_%H-%M-%S-") + "295_The_train_left.wav"
            pc.write_wav_int16(clones / name, 24_000, np.zeros(int(24_000 * 2.32)))
            other = stamp.replace(minute=25).strftime("%Y%m%d_%H-%M-%S-") + "000_other.wav"
            pc.write_wav_int16(clones / other, 24_000, np.zeros(int(24_000 * 7.28)))
            epoch = stamp.timestamp() * 1000
            found = pc.resolve_reference_wav(Path(tmp), "clone", epoch - 2000, epoch + 5000, 2.32)
            self.assertEqual(found, clones / name)
            self.assertIsNone(pc.resolve_reference_wav(Path(tmp), "clone", epoch - 2000, epoch + 5000, 7.28))
            self.assertIsNone(pc.resolve_reference_wav(Path(tmp), "clone", epoch + 60_000, epoch + 70_000, 2.32))
            self.assertIsNone(pc.resolve_reference_wav(Path(tmp), "unknown", epoch - 2000, epoch + 5000, 2.32))


class AnalyzeTakeTests(unittest.TestCase):
    def _fixture(self, tmp: str, *, delay_ms: float = 137.0, silent: bool = False) -> tuple[dict, Path, Path]:
        world = speech_like(WORLD_RATE)
        reference = Path(tmp, "reference.wav")
        pc.write_wav_int16(reference, 24_000, pc.resample(world, WORLD_RATE, 24_000))
        capture = Path(tmp, "take-01-custom_short_warm#0.wav")
        played = np.zeros(WORLD_RATE * 4) if silent else delayed(world, delay_ms, 0.7)
        pc.write_wav_float32(capture, WORLD_RATE, played)
        sidecar = {"takeIndex": 1, "cell": "custom/short/warm#0", "status": "captured",
                   "captureStartEpochMS": 10_000.0, "submitClickEpochMS": 9_900.0}
        return sidecar, capture, reference

    def test_a_clean_capture_is_captured_with_metrics_and_no_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sidecar, capture, reference = self._fixture(tmp)
            result = pc.analyze_take(sidecar, capture, reference)
            self.assertEqual(result["status"], "captured")
            self.assertEqual(result["warnings"], [])
            self.assertEqual(set(result["metrics"]), set(pc.METRIC_KEYS))
            self.assertAlmostEqual(result["metrics"]["playbackCaptureAlignmentMS"], 137.0, delta=1.0)
            # first audible = capture start (10 000) + delay (137) + burst onset (300) − click (9 900)
            self.assertAlmostEqual(result["metrics"]["playbackCaptureFirstAudibleMS"], 537.0, delta=pc.FRAME_MS + 1)
            self.assertEqual(len(result["digest"]), 64)

    def test_statuses_and_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sidecar, capture, reference = self._fixture(tmp, silent=True)
            self.assertEqual(pc.analyze_take(sidecar, capture, reference)["status"], "silent")
            # A long lead-in inside the capture is not a fault: the tap runs from the
            # app's device start. Misalignment is measured against the app's own
            # playback-scheduled time, in either direction.
            sidecar, capture, reference = self._fixture(tmp, delay_ms=400.0)
            late = pc.analyze_take(sidecar, capture, reference)
            self.assertNotIn("playback.capture.misaligned", late["warnings"])
            self.assertAlmostEqual(late["metrics"]["playbackCaptureAlignmentMS"], 400.0, delta=1.0)
            agreed = pc.analyze_take(sidecar, capture, reference, playback_scheduled_ms=800.0)
            self.assertNotIn("playback.capture.misaligned", agreed["warnings"])
            self.assertIn("playback.capture.misaligned",
                          pc.analyze_take(sidecar, capture, reference, playback_scheduled_ms=300.0)["warnings"])
            self.assertIn("playback.capture.misaligned",
                          pc.analyze_take(sidecar, capture, reference, playback_scheduled_ms=1_300.0)["warnings"])
            self.assertEqual(pc.analyze_take(sidecar, capture, None)["status"], "referenceUnresolved")
            self.assertEqual(pc.analyze_take({**sidecar, "status": "aborted"}, capture, reference)["status"], "aborted")
            self.assertEqual(pc.analyze_take(sidecar, None, reference)["status"], "unavailable")

    def test_collect_captures_joins_sidecars_and_wavs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "take-01-custom_short_warm#0.json").write_text(json.dumps({"takeIndex": 1, "cell": "custom/short/warm#0"}))
            pc.write_wav_float32(Path(tmp, "take-01-custom_short_warm#0.wav"), 48_000, np.zeros(480))
            Path(tmp, "take-02-custom_short_warm#1.json").write_text(json.dumps({"takeIndex": 2, "cell": "custom/short/warm#1"}))
            captures = pc.collect_captures(Path(tmp))
            self.assertEqual(set(captures), {(1, "custom/short/warm#0"), (2, "custom/short/warm#1")})
            self.assertIsNotNone(captures[(1, "custom/short/warm#0")]["wav"])
            self.assertIsNone(captures[(2, "custom/short/warm#1")]["wav"])
            self.assertEqual(pc.collect_captures(Path(tmp, "missing")), {})


if __name__ == "__main__":
    unittest.main()
