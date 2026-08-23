#!/usr/bin/env python3
"""Deterministic tests for the content-addressed delivery-analysis cache."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from delivery_analysis_cache import (  # noqa: E402
    AnalysisCacheError,
    DeliveryAnalysisCache,
    LayerIdentity,
    NO_MODEL_DIGEST,
    digest,
)


class DeliveryAnalysisCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.wav = self.root / "input.wav"
        self._write_wav(self.wav, [int(8000 * ((index % 31) / 31.0 - 0.5)) for index in range(2400)])
        self.cache = DeliveryAnalysisCache(self.root / "cache")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _write_wav(path: Path, samples: list[int], rate: int = 24_000) -> None:
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(rate)
            output.writeframes(struct.pack(f"<{len(samples)}h", *samples))

    def _identity(self, **changes: str) -> LayerIdentity:
        canonical = self.cache.canonicalize(self.wav)
        values = {
            "original_wav_sha256": canonical.original_wav_sha256,
            "canonical_derivative_sha256": canonical.canonical_derivative_sha256,
            "layer_id": "fixture",
            "layer_version": "1",
            "binary_sha256": hashlib.sha256(b"binary-v1").hexdigest(),
            "model_id": "none",
            "model_revision": "not-applicable",
            "weights_sha256": NO_MODEL_DIGEST,
            "preprocessing_config_digest": digest({"rate": 16000}),
        }
        values.update(changes)
        return LayerIdentity(**values)

    def test_hit_avoids_compute_and_neutral_can_be_reused(self) -> None:
        identity = self._identity()
        calls = 0

        def compute() -> dict:
            nonlocal calls
            calls += 1
            return {"score": 0.25, "kind": "neutral-control"}

        first, first_hit = self.cache.get_or_compute(identity, compute)
        second, second_hit = self.cache.get_or_compute(identity, compute)
        self.assertFalse(first_hit)
        self.assertTrue(second_hit)
        self.assertEqual(first, second)
        self.assertEqual(calls, 1)

    def test_corrupted_json_and_derivative_fail_closed(self) -> None:
        identity = self._identity()
        self.cache.store(identity, {"score": 1.0})
        entry = self.cache._entry_path(identity)
        entry.write_text("{broken", encoding="utf-8")
        with self.assertRaisesRegex(AnalysisCacheError, "unreadable"):
            self.cache.load(identity)

        other_cache = DeliveryAnalysisCache(self.root / "other-cache")
        canonical = other_cache.canonicalize(self.wav)
        canonical.derivative_path.write_bytes(canonical.derivative_path.read_bytes() + b"x")
        with self.assertRaisesRegex(AnalysisCacheError, "derivative digest"):
            other_cache.canonicalize(self.wav)

    def test_revision_preprocessing_and_audio_changes_miss(self) -> None:
        identity = self._identity()
        self.cache.store(identity, {"score": 1.0})
        self.assertIsNone(self.cache.load(self._identity(model_revision="revision-2")))
        self.assertIsNone(self.cache.load(self._identity(
            preprocessing_config_digest=digest({"rate": 16000, "window": 2})
        )))

        self._write_wav(self.wav, [100] * 2400)
        changed = self._identity()
        self.assertNotEqual(identity.original_wav_sha256, changed.original_wav_sha256)
        self.assertIsNone(self.cache.load(changed))

    def test_interrupted_atomic_replace_leaves_no_committed_record(self) -> None:
        identity = self._identity()
        entry = self.cache._entry_path(identity)
        real_replace = __import__("os").replace

        def fail_layer_replace(source: str, destination: str) -> None:
            if Path(destination) == entry:
                raise OSError("injected interruption")
            real_replace(source, destination)

        with mock.patch("delivery_analysis_cache.os.replace", side_effect=fail_layer_replace):
            with self.assertRaises(OSError):
                self.cache.store(identity, {"score": 1.0})
        self.assertFalse(entry.exists())

    def test_cross_identity_record_and_local_path_are_rejected(self) -> None:
        identity = self._identity()
        self.cache.store(identity, {"score": 1.0})
        entry = self.cache._entry_path(identity)
        record = json.loads(entry.read_text())
        record["identity"]["originalWAVSHA256"] = "0" * 64
        body = dict(record)
        body.pop("recordDigest")
        record["recordDigest"] = digest(body)
        entry.write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaisesRegex(AnalysisCacheError, "identity mismatch"):
            self.cache.load(identity)
        with self.assertRaisesRegex(AnalysisCacheError, "local path"):
            self.cache.store(
                self._identity(layer_version="2"),
                {"detail": "/" + "Users/person/audio.wav"},
            )


if __name__ == "__main__":
    unittest.main()
