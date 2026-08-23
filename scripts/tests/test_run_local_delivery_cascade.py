#!/usr/bin/env python3
"""Deterministic cascade routing and cache-reuse tests."""

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

from delivery_analysis_cache import DeliveryAnalysisCache, digest  # noqa: E402
from run_local_delivery_cascade import (  # noqa: E402
    CascadeError,
    build_cascade_manifest,
    run_cascade,
)


class LocalDeliveryCascadeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.neutral = self.root / "neutral.wav"
        self.one = self.root / "one.wav"
        self.two = self.root / "two.wav"
        self._tone(self.neutral, 150)
        self._tone(self.one, 180)
        self._tone(self.two, 210)
        self.manifest = self._seal({
            "schemaVersion": 1,
            "kind": "source-bound-delivery-cascade-input",
            "generationProcessExited": True,
            "executionPlanDigest": "1" * 64,
            "sourceDigests": {
                "retainedPlanSHA256": "2" * 64,
                "executionStateSHA256": "3" * 64,
                "acousticLayerSHA256": "4" * 64,
                "binarySHA256": "5" * 64,
                "runnerSHA256": "6" * 64,
                "analyzerSHA256": "7" * 64,
                "temporalAnalyzerSHA256": "8" * 64,
            },
            "rows": [self._row("one", self.one, 1), self._row("two", self.two, 2)],
        })
        self.cache = DeliveryAnalysisCache(self.root / "cache")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _tone(path: Path, frequency: float) -> None:
        samples = [int(math.sin(2 * math.pi * frequency * index / 16_000) * 8000) for index in range(32_000)]
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1); output.setsampwidth(2); output.setframerate(16_000)
            output.writeframes(struct.pack(f"<{len(samples)}h", *samples))

    @staticmethod
    def _sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _seal(body: dict) -> dict:
        body = dict(body)
        body.pop("manifestDigest", None)
        return {**body, "manifestDigest": digest(body)}

    def _row(self, generation: str, instructed: Path, seed: int) -> dict:
        return {
            "generationID": generation,
            "speakerID": "aiden", "scriptID": "script-1",
            "scriptTranslationGroup": "translation-1",
            "outputLanguage": "English", "preset": "happy", "seed": seed,
            "instructedWAV": str(instructed), "instructedSHA256": self._sha(instructed),
            "neutralWAV": str(self.neutral), "neutralSHA256": self._sha(self.neutral),
        }

    def test_always_layers_run_and_shared_neutral_is_reused(self) -> None:
        first = run_cascade(
            manifest=self.manifest, cache=self.cache, lock_root=self.root / "lock",
        )
        self.assertEqual(first["rowCount"], 2)
        self.assertEqual(len(first["composerSHA256"]), 64)
        self.assertEqual(
            first["reportDigest"],
            digest({key: value for key, value in first.items() if key != "reportDigest"}),
        )
        self.assertTrue(all(row["route"] == "abstained" for row in first["rows"]))
        self.assertGreater(first["cache"]["hits"], 0)
        self.assertTrue(all(
            row["alwaysLayers"]["temporalAcoustics"]["kind"] == "instructed-minus-neutral-temporal-delta"
            for row in first["rows"]
        ))
        self.assertTrue(all(
            row["alwaysLayers"]["audioQC"]["instructed"]["status"] == "complete"
            for row in first["rows"]
        ))
        second = run_cascade(
            manifest=self.manifest, cache=self.cache, lock_root=self.root / "lock",
        )
        self.assertEqual(second["cache"]["misses"], 0)
        self.assertGreater(second["cache"]["hits"], first["cache"]["hits"])
        self.assertNotIn(str(self.root), json.dumps(second))

    def test_generation_process_must_exit_and_audio_is_digest_bound(self) -> None:
        active = dict(self.manifest)
        active["generationProcessExited"] = False
        active = self._seal(active)
        with self.assertRaisesRegex(CascadeError, "must exit"):
            run_cascade(manifest=active, cache=self.cache, lock_root=self.root / "lock")
        changed = json.loads(json.dumps(self.manifest))
        changed["rows"][0]["instructedSHA256"] = "0" * 64
        changed = self._seal(changed)
        with self.assertRaisesRegex(CascadeError, "missing or changed"):
            run_cascade(manifest=changed, cache=self.cache, lock_root=self.root / "lock")

    def test_all_zero_pcm_is_rejected_by_the_distinct_qc_layer(self) -> None:
        silent = self.root / "silent.wav"
        with wave.open(str(silent), "wb") as output:
            output.setnchannels(1); output.setsampwidth(2); output.setframerate(16_000)
            output.writeframes(b"\0\0" * 32_000)
        manifest = dict(self.manifest)
        manifest["rows"] = [self._row("silent", silent, 3)]
        manifest = self._seal(manifest)
        result = run_cascade(
            manifest=manifest, cache=self.cache, lock_root=self.root / "lock",
        )
        self.assertEqual(result["rows"][0]["route"], "rejected")
        self.assertEqual(
            result["rows"][0]["alwaysLayers"]["audioQC"]["instructed"]["errorCode"],
            "all-zero-pcm",
        )

    def test_operator_manifest_is_derived_from_one_sealed_runner_identity(self) -> None:
        run_dir = self.root / "run"
        audio_dir = run_dir / "audio"
        audio_dir.mkdir(parents=True)
        instructed = audio_dir / "take.wav"
        neutral = audio_dir / "neutral.wav"
        instructed.write_bytes(self.one.read_bytes())
        neutral.write_bytes(self.neutral.read_bytes())
        execution_digest = "a" * 64
        identity = {
            "binarySHA256": "b" * 64,
            "runnerSHA256": "c" * 64,
            "analyzerSHA256": "d" * 64,
            "temporalAnalyzerSHA256": "e" * 64,
        }
        plan = {
            "executionPlanDigest": execution_digest,
            "executionIdentity": identity,
            "rows": [{
                "takeID": "take-1", "speakerID": "aiden", "seed": 9,
                "outputLanguage": "English", "preset": "happy",
                "script": {"scriptID": "script-1", "translationGroup": "translation-1"},
            }],
        }
        state = {
            "executionPlanDigest": execution_digest,
            "takes": {"take-1": {
                "status": "complete", "generationID": "generation-1",
                "referenceKey": "reference-1", "audio": "audio/take.wav",
                "audioSHA256": self._sha(instructed),
            }},
            "references": {"reference-1": {
                "status": "complete", "audio": "audio/neutral.wav",
                "audioSHA256": self._sha(neutral),
            }},
        }
        acoustic = {
            "manifestDigest": execution_digest,
            "rows": [{"takeID": "take-1", "generationID": "generation-1"}],
        }
        plan_path = self.root / "plan.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        (run_dir / "execution-plan.json").write_text(json.dumps(plan), encoding="utf-8")
        (run_dir / "execution-state.json").write_text(json.dumps(state), encoding="utf-8")
        (run_dir / "acoustic-layer.json").write_text(json.dumps(acoustic), encoding="utf-8")
        manifest = build_cascade_manifest(plan_path=plan_path, run_dir=run_dir)
        self.assertEqual(manifest["executionPlanDigest"], execution_digest)
        self.assertEqual(manifest["rows"][0]["generationID"], "generation-1")
        self.assertEqual(manifest["manifestDigest"], digest({
            key: value for key, value in manifest.items() if key != "manifestDigest"
        }))
        state["executionPlanDigest"] = "f" * 64
        (run_dir / "execution-state.json").write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaisesRegex(CascadeError, "identities differ"):
            build_cascade_manifest(plan_path=plan_path, run_dir=run_dir)


if __name__ == "__main__":
    unittest.main()
