#!/usr/bin/env python3
"""Deterministic listener-attention anchor tests."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prepare_delivery_listener_anchors import AnchorError, prepare  # noqa: E402


class DeliveryListenerAnchorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _tone(self, name: str, frequency: float) -> Path:
        path = self.root / name
        samples = [
            int(math.sin(2 * math.pi * frequency * index / 16_000) * 8000)
            for index in range(32_000)
        ]
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1); output.setsampwidth(2); output.setframerate(16_000)
            output.writeframes(struct.pack(f"<{len(samples)}h", *samples))
        return path

    def test_anchor_is_deterministic_degraded_and_label_blind(self) -> None:
        one, two = self._tone("one.wav", 180), self._tone("two.wav", 240)
        first = prepare(sources=[one, two], output_dir=self.root / "out", output_language="Chinese")
        second = prepare(sources=[one, two], output_dir=self.root / "out", output_language="Chinese")
        self.assertEqual(first, second)
        self.assertFalse(first["requestedDeliveryLabelsUsed"])
        self.assertNotEqual(first["anchors"][0]["expectedSHA256"], first["anchors"][0]["comparisonSHA256"])
        self.assertNotIn("preset", json.dumps(first).lower())

    def test_anchor_preserves_real_vocello_sample_rate(self) -> None:
        source = self.root / "vocello-24khz.wav"
        samples = [
            int(math.sin(2 * math.pi * 180 * index / 24_000) * 8000)
            for index in range(48_000)
        ]
        with wave.open(str(source), "wb") as output:
            output.setnchannels(1); output.setsampwidth(2); output.setframerate(24_000)
            output.writeframes(struct.pack(f"<{len(samples)}h", *samples))
        report = prepare(
            sources=[source], output_dir=self.root / "out-24khz",
            output_language="English",
        )
        comparison = Path(report["anchors"][0]["comparisonPath"])
        with wave.open(str(comparison), "rb") as reader:
            self.assertEqual(reader.getframerate(), 24_000)
            self.assertEqual(reader.getnchannels(), 1)
            self.assertEqual(reader.getsampwidth(), 2)

    def test_duplicate_or_short_sources_fail_closed(self) -> None:
        source = self._tone("one.wav", 180)
        with self.assertRaisesRegex(AnchorError, "byte-distinct"):
            prepare(sources=[source, source], output_dir=self.root / "out", output_language="Chinese")
        short = self.root / "short.wav"
        with wave.open(str(short), "wb") as output:
            output.setnchannels(1); output.setsampwidth(2); output.setframerate(16_000)
            output.writeframes(struct.pack("<100h", *([1] * 100)))
        with self.assertRaisesRegex(AnchorError, "at least one second"):
            prepare(sources=[short], output_dir=self.root / "out", output_language="Chinese")


if __name__ == "__main__":
    unittest.main()
