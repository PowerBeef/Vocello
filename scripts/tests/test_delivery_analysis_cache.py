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

import numpy as np

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

    def test_preprocessing_and_count_metadata_drift_fail_closed(self) -> None:
        canonical = self.cache.canonicalize(self.wav)
        metadata_path = canonical.derivative_path.with_suffix(".json")
        original = json.loads(metadata_path.read_text())
        for field, value in (
            ("schemaVersion", 99), ("kind", "other"), ("sampleRateHz", 8000),
            ("channels", 2), ("format", "float32"), ("resamplerVersion", "other"),
            ("sampleCount", original["sampleCount"] + 1),
            ("sampleCount", True), ("durationSeconds", 99.0),
        ):
            with self.subTest(field=field):
                body = {**original, field: value}
                body.pop("recordDigest")
                metadata_path.write_text(json.dumps({**body, "recordDigest": digest(body)}))
                with self.assertRaises(AnalysisCacheError):
                    self.cache.canonicalize(self.wav)

    def test_truncated_declared_audio_is_not_cached(self) -> None:
        self.wav.write_bytes(self.wav.read_bytes()[:-100])
        with self.assertRaises(AnalysisCacheError):
            self.cache.canonicalize(self.wav)
        self.assertEqual(list(self.cache.root.rglob("*.json")), [])

    def test_layer_schema_drift_cannot_be_reused(self) -> None:
        identity = self._identity()
        self.cache.store(identity, {"score": 1.0})
        entry = self.cache._entry_path(identity)
        original = json.loads(entry.read_text())
        for field, value in (("schemaVersion", 2), ("schemaVersion", True),
                             ("kind", "other"), ("promotionAuthority", True)):
            with self.subTest(field=field, value=value):
                body = {**original, field: value}
                body.pop("recordDigest")
                entry.write_text(json.dumps({**body, "recordDigest": digest(body)}))
                with self.assertRaisesRegex(AnalysisCacheError, "schema mismatch"):
                    self.cache.get_or_compute(identity, lambda: self.fail("must not recompute corruption"))

    def test_streamed_derivatives_preserve_legacy_bytes_across_blocks(self) -> None:
        expected = {
            (16000, 1): (70006, "03ef64d5ead49477b80bd77f6e8d6dbff533d7544da1b8b3ddd895114473e08b"),
            (16000, 2): (70006, "2484878667528f9ed259c5a6077b86c4f1bb8375cfbfc9972c3e794a25cd5f43"),
            (24000, 1): (46671, "cab5f3ce59ed6cc7256561f708752ba4097fc507bbe5dd90df642bab0b155a4f"),
            (24000, 2): (46671, "4bab751200cbdd612f6164dbab2271be4cd9a5d406ee9edd1ea4bf3964c2b2d9"),
            (44100, 1): (25400, "1228de80c005d586c2553eb2d401cf66a4bf50b2093bb34565bd185cb2e5d584"),
            (44100, 2): (25400, "31ef2aa1308ccad2bf239166259aa11891394c056aa228b69ed62a165ce6f4a9"),
            (48000, 1): (23336, "5d98b3298a8d0710310d384cb753285cbcc889146e9c542dd94c8cb0b069b8a6"),
            (48000, 2): (23336, "c40dcab9410f7878dd91c3fe30645f3669832db7aaaf6e9588494c799faa75ba"),
        }
        for (rate, channels), (count, sha) in expected.items():
            with self.subTest(rate=rate, channels=channels):
                samples = ((np.arange(70007 * channels, dtype=np.int64) * 7919) % 60001 - 30000).astype("<i2")
                with wave.open(str(self.wav), "wb") as output:
                    output.setparams((channels, 2, rate, 0, "NONE", "not compressed"))
                    output.writeframes(samples.tobytes())
                result = self.cache.canonicalize(self.wav)
                self.assertEqual((result.sample_count, result.canonical_derivative_sha256), (count, sha))

    def test_canonical_write_interruption_and_source_change_do_not_publish(self) -> None:
        with mock.patch("delivery_analysis_cache.os.replace", side_effect=OSError("interrupted")):
            with self.assertRaises(OSError):
                self.cache.canonicalize(self.wav)
        self.assertEqual(list(self.cache.root.rglob("*.*")), [])
        from delivery_analysis_cache import file_sha256
        original = file_sha256(self.wav)
        with mock.patch("delivery_analysis_cache.file_sha256", side_effect=[original, "0" * 64]):
            with self.assertRaisesRegex(AnalysisCacheError, "changed during"):
                self.cache.canonicalize(self.wav)
        self.assertEqual(list(self.cache.root.rglob("*.*")), [])

    def test_canonical_memory_does_not_retain_clip_sized_bytes(self) -> None:
        import tracemalloc
        peaks = []
        for seconds in (10, 600):
            with wave.open(str(self.wav), "wb") as output:
                output.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
                for _ in range(seconds):
                    output.writeframesraw(b"\x01\x00" * 24000)
            tracemalloc.start()
            try:
                self.cache.canonicalize(self.wav)
                peaks.append(tracemalloc.get_traced_memory()[1])
            finally:
                tracemalloc.stop()
        # Fixed block arrays plus hash buffers; excludes interpreter baseline.
        self.assertLess(max(peaks), 8 * 1024 * 1024)
        self.assertLess(peaks[1] - peaks[0], 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
