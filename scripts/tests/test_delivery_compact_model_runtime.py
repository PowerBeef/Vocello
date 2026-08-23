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
    PROJECTION_DIMENSIONS,
    _project,
    _read_pcm,
)


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
