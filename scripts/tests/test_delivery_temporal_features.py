#!/usr/bin/env python3
"""Synthetic contracts for bounded temporal delivery features."""

from __future__ import annotations

import math
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import wave

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from delivery_temporal_features import analyze_temporal, paired_temporal_delta  # noqa: E402


RATE = 16_000


def _tone(
    duration: float,
    frequency: callable,
    amplitude: callable | None = None,
    noise: float = 0.0,
    pause: tuple[float, float] | None = None,
) -> np.ndarray:
    count = int(duration * RATE)
    phase = 0.0
    values = np.zeros(count, dtype=np.float64)
    rng = np.random.default_rng(20260822)
    for index in range(count):
        time = index / RATE
        phase += 2.0 * math.pi * frequency(time / duration) / RATE
        level = amplitude(time / duration) if amplitude else 0.45
        values[index] = math.sin(phase) * level
    if noise:
        values += rng.normal(0.0, noise, count)
    if pause:
        values[int(pause[0] * RATE):int(pause[1] * RATE)] = 0.0
    return np.clip(np.rint(values * 32767), -32768, 32767).astype("<i2")


def _write(path: Path, samples: np.ndarray) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(RATE)
        output.writeframes(samples.tobytes())


def _all_numbers(value):
    if isinstance(value, dict):
        for child in value.values():
            yield from _all_numbers(child)
    elif isinstance(value, list):
        for child in value:
            yield from _all_numbers(child)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        yield float(value)


class DeliveryTemporalFeatureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _analyze(self, name: str, samples: np.ndarray) -> dict:
        path = self.root / f"{name}.wav"
        _write(path, samples)
        return analyze_temporal(str(path))

    def test_rising_falling_and_early_late_peaks(self) -> None:
        rising = self._analyze("rising", _tone(2.5, lambda x: 120 + 90 * x))
        falling = self._analyze("falling", _tone(2.5, lambda x: 210 - 90 * x))
        self.assertGreater(rising["derivedContours"]["onsetToEndPitchHz"], 35)
        self.assertLess(falling["derivedContours"]["onsetToEndPitchHz"], -35)

        early = self._analyze("early", _tone(2.5, lambda x: 130 + 100 * math.exp(-((x - 0.2) / 0.12) ** 2)))
        late = self._analyze("late", _tone(2.5, lambda x: 130 + 100 * math.exp(-((x - 0.8) / 0.12) ** 2)))
        self.assertLess(early["derivedContours"]["normalizedPeakPosition"], 0.5)
        self.assertGreater(late["derivedContours"]["normalizedPeakPosition"], 0.5)

    def test_onset_burst_delayed_pause_whisper_noise_and_tremor(self) -> None:
        burst = self._analyze("burst", _tone(
            2.5, lambda _x: 160,
            amplitude=lambda x: 0.8 if x < 0.2 else 0.25,
        ))
        self.assertLess(burst["derivedContours"]["energyAttackDB"], -3.0)

        paused = self._analyze("pause", _tone(2.5, lambda _x: 160, pause=(1.8, 2.1)))
        histogram = paused["derivedContours"]["pausePositionHistogram"]
        self.assertGreater(sum(histogram[3:]), sum(histogram[:2]))

        whisper = self._analyze("whisper", _tone(
            2.5, lambda _x: 170, amplitude=lambda _x: 0.02, noise=0.15,
        ))
        self.assertGreater(whisper["derivedContours"]["breathinessPersistence"], 0.0)

        steady = self._analyze("steady", _tone(2.5, lambda _x: 160))
        tremor = self._analyze("tremor", _tone(2.5, lambda x: 160 + 18 * math.sin(x * 40 * math.pi)))
        self.assertGreater(
            tremor["derivedContours"]["tremorPersistenceHz"],
            steady["derivedContours"]["tremorPersistenceHz"],
        )

    def test_identical_pair_delta_is_zero(self) -> None:
        report = self._analyze("same", _tone(2.5, lambda x: 140 + x * 20))
        delta = paired_temporal_delta(report, report)
        self.assertTrue(all(
            abs(value) < 1e-12
            for value in _all_numbers({
                "regions": delta["regions"],
                "derivedContours": delta["derivedContours"],
            })
        ))

    def test_owned_memory_estimate_does_not_grow_with_duration(self) -> None:
        short = self._analyze("short", _tone(1.5, lambda _x: 160))
        long = self._analyze("long", _tone(7.5, lambda _x: 160))
        longer = self._analyze("longer", _tone(12.5, lambda _x: 160))
        self.assertEqual(
            short["memory"]["estimatedPeakWorkingSetBytes"],
            long["memory"]["estimatedPeakWorkingSetBytes"],
        )
        self.assertEqual(long["memory"]["estimatedPeakWorkingSetBytes"], longer["memory"]["estimatedPeakWorkingSetBytes"])
        self.assertEqual(long["memory"]["measuredPeakManagedBufferBytes"], longer["memory"]["measuredPeakManagedBufferBytes"])
        self.assertLessEqual(short["memory"]["measuredPeakManagedBufferBytes"], long["memory"]["measuredPeakManagedBufferBytes"])


if __name__ == "__main__":
    unittest.main()
