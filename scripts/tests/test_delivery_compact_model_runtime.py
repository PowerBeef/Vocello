#!/usr/bin/env python3
"""Compact representation runtime tests without neural model loading."""

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

from delivery_compact_model_runtime import (  # noqa: E402
    CompactRuntimeError,
    NISQA_DIMENSIONS,
    PROJECTION_DIMENSIONS,
    _nisqa_chunks,
    _project,
    _read_pcm,
    _read_wav_native,
)


class NISQARuntimeShapeTests(unittest.TestCase):
    """The clip-quality screen's audio handling, without loading the model."""

    NISQA_ARGS = {"ms_hop_length": 0.01, "ms_seg_length": 15, "ms_seg_hop_length": 4, "ms_max_segments": 1300}

    def test_native_rate_is_preserved_and_stereo_or_empty_audio_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "take.wav"
            with wave.open(str(path), "wb") as output:
                output.setnchannels(1); output.setsampwidth(2); output.setframerate(24_000)
                output.writeframes(struct.pack("<h", 1200) * 2400)
            samples, rate = _read_wav_native(path)
            self.assertEqual((rate, samples.size), (24_000, 2400))
            self.assertAlmostEqual(float(samples[0]), 1200 / 32768, places=6)
            with wave.open(str(path), "wb") as output:
                output.setnchannels(2); output.setsampwidth(2); output.setframerate(24_000)
                output.writeframes(struct.pack("<h", 1) * 400)
            with self.assertRaisesRegex(CompactRuntimeError, "mono PCM16"):
                _read_wav_native(path)
            with wave.open(str(path), "wb") as output:
                output.setnchannels(1); output.setsampwidth(2); output.setframerate(24_000)
            with self.assertRaisesRegex(CompactRuntimeError, "empty"):
                _read_wav_native(path)

    def test_chunks_respect_the_segment_budget_and_absorb_a_short_tail(self) -> None:
        rate = 24_000
        budget_seconds = (1300 * 4 - 15 - 8) * 0.01  # about 51.8 s per chunk
        short = np.zeros(int(rate * 3), dtype=np.float32)
        self.assertEqual(len(_nisqa_chunks(short, rate, self.NISQA_ARGS)), 1)
        long = np.zeros(int(rate * (budget_seconds * 2 + 0.05)), dtype=np.float32)
        chunks = _nisqa_chunks(long, rate, self.NISQA_ARGS)
        # The 50 ms remainder is too short to segment on its own; it joins the previous chunk.
        self.assertEqual(len(chunks), 2)
        self.assertEqual(sum(chunk.size for chunk in chunks), long.size)
        self.assertTrue(all(chunk.size <= int(budget_seconds * rate) + rate for chunk in chunks))
        self.assertEqual(NISQA_DIMENSIONS, ("mos", "noisiness", "discontinuity", "coloration", "loudness"))


class DeliveryCompactModelRuntimeTests(unittest.TestCase):
    def test_projection_is_deterministic_finite_and_unit_normalized(self) -> None:
        hidden = np.arange(60, dtype=np.float32).reshape(10, 6) / 100
        first = _project(hidden)
        self.assertEqual(first, _project(hidden))
        self.assertEqual(len(first), PROJECTION_DIMENSIONS)
        self.assertTrue(all(math.isfinite(value) for value in first))
        self.assertAlmostEqual(math.sqrt(sum(value * value for value in first)), 1.0, places=7)

    def test_too_few_frames_and_noncanonical_audio_fail(self) -> None:
        with self.assertRaisesRegex(CompactRuntimeError, "too short"):
            _project(np.ones((4, 8), dtype=np.float32))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "stereo.wav"
            with wave.open(str(path), "wb") as output:
                output.setnchannels(2); output.setsampwidth(2); output.setframerate(16_000)
                output.writeframes(struct.pack("<200h", *([1] * 200)))
            with self.assertRaisesRegex(CompactRuntimeError, "canonical"):
                _read_pcm(path)


if __name__ == "__main__":
    unittest.main()
