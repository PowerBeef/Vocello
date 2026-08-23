#!/usr/bin/env python3
"""Pinned compact-model adapter tests without external model acquisition."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from delivery_analysis_cache import DeliveryAnalysisCache, digest, file_sha256  # noqa: E402
from delivery_compact_model_adapter import (  # noqa: E402
    CompactAdapterError,
    run_compact_adapter,
    validate_adapter_config,
)
from delivery_resource_supervisor import HostSnapshot, run_supervised  # noqa: E402
from delivery_resource_supervisor import SupervisedResult  # noqa: E402
import delivery_resource_supervisor  # noqa: E402
import delivery_compact_model_adapter  # noqa: E402


class DeliveryCompactModelAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.audio = self.root / "audio.wav"
        with wave.open(str(self.audio), "wb") as output:
            output.setnchannels(1); output.setsampwidth(2); output.setframerate(16_000)
            output.writeframes(struct.pack("<h", 100) * 3200)
        self.weights = self.root / "sensevoice-q8.gguf"
        self.weights.write_bytes(b"fixture weights")
        preprocessing = {"sampleRateHz": 16000, "channels": 1, "normalization": "none"}
        code = (
            "import json,sys,time; time.sleep(.1); "
            "print(json.dumps({'transcript':'hello','languageTag':'en',"
            "'emotionTag':'neutral','eventTag':'speech'}))"
        )
        self.config = {
            "schemaVersion": 1,
            "adapterID": "sensevoice-small-q8",
            "modelID": "sensevoice-small-q8-fixture",
            "sourceRevision": "revision-fixture-immutable",
            "weightsPath": str(self.weights),
            "weightsSHA256": file_sha256(self.weights),
            "binaryPath": sys.executable,
            "binarySHA256": file_sha256(Path(sys.executable)),
            "license": "Apache-2.0-fixture",
            "commercialUseCompatible": True,
            "trainingDataDeclaration": "fixture-declaration",
            "labelMapDigest": hashlib.sha256(b"labels").hexdigest(),
            "preprocessingConfig": preprocessing,
            "preprocessingConfigDigest": digest(preprocessing),
            "offlineAfterAcquisition": True,
            "commandTemplate": ["{binary}", "-c", code, "{audio}", "{weights}"],
        }
        self.cache = DeliveryAnalysisCache(self.root / "cache")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _supervisor(command, **kwargs):
        return run_supervised(
            command,
            **kwargs,
            snapshotter=lambda: HostSnapshot(50.0, 0, False),
            rss_sampler=lambda _pid: 32 * 1024**2,
        )

    def test_pinned_cpu_process_output_and_cache_hit(self) -> None:
        payload, hit = run_compact_adapter(
            wav_path=self.audio, config=self.config, cache=self.cache,
            lock_root=self.root / "lock", supervisor=self._supervisor,
        )
        self.assertFalse(hit)
        self.assertEqual(payload["outputs"]["languageTag"], "en")
        self.assertFalse(payload["modelProvenance"]["adopted"])
        self.assertNotIn(str(self.root), json.dumps(payload))

        def must_not_launch(*_args, **_kwargs):
            raise AssertionError("cache hit launched the model")

        retained, hit = run_compact_adapter(
            wav_path=self.audio, config=self.config, cache=self.cache,
            lock_root=self.root / "lock", supervisor=must_not_launch,
        )
        self.assertTrue(hit)
        self.assertEqual(retained, payload)

    def test_license_digest_and_requested_label_fail_closed(self) -> None:
        incompatible = copy.deepcopy(self.config)
        incompatible["commercialUseCompatible"] = False
        with self.assertRaisesRegex(CompactAdapterError, "license"):
            validate_adapter_config(incompatible)
        drifted = copy.deepcopy(self.config)
        drifted["weightsSHA256"] = "0" * 64
        with self.assertRaisesRegex(CompactAdapterError, "weights digest"):
            validate_adapter_config(drifted)
        leaked = copy.deepcopy(self.config)
        leaked["commandTemplate"].append("{requestedLabel}")
        with self.assertRaisesRegex(CompactAdapterError, "requested labels"):
            validate_adapter_config(leaked)

    def test_revision_drift_is_a_cache_miss(self) -> None:
        run_compact_adapter(
            wav_path=self.audio, config=self.config, cache=self.cache,
            lock_root=self.root / "lock", supervisor=self._supervisor,
        )
        changed = copy.deepcopy(self.config)
        changed["sourceRevision"] = "revision-two-immutable"
        _payload, hit = run_compact_adapter(
            wav_path=self.audio, config=changed, cache=self.cache,
            lock_root=self.root / "lock", supervisor=self._supervisor,
        )
        self.assertFalse(hit)

    def test_v2_tagged_output_binds_runtime_and_label_map(self) -> None:
        config = copy.deepcopy(self.config)
        labels = {
            "languages": ["en"], "emotions": ["NEUTRAL"],
            "events": ["Speech"], "textNormalization": ["withitn"],
        }
        dependencies = {"runtime": "fixture-v1"}
        source_digest = file_sha256(Path(sys.executable))
        config.update({
            "executionIdentityVersion": 2,
            "outputFormat": "sensevoice-tagged-text",
            "sourceURI": "https://example.invalid/model/revision",
            "trainingDataSourceURI": "https://example.invalid/training-data",
            "labelMap": labels,
            "labelMapDigest": digest(labels),
            "runtimeDependencies": dependencies,
            "runtimeDependenciesDigest": digest(dependencies),
            "adapterSourceSHA256": source_digest,
            "adapterLayerSHA256": file_sha256(Path(delivery_compact_model_adapter.__file__)),
            "resourceSupervisorSHA256": file_sha256(Path(delivery_resource_supervisor.__file__)),
        })
        config["preprocessingConfig"]["executionIdentity"] = {
            "adapterSourceSHA256": source_digest,
            "adapterLayerSHA256": config["adapterLayerSHA256"],
            "resourceSupervisorSHA256": config["resourceSupervisorSHA256"],
            "runtimeDependenciesDigest": digest(dependencies),
            "labelMapDigest": digest(labels),
            "outputFormat": "sensevoice-tagged-text",
        }
        config["preprocessingConfigDigest"] = digest(config["preprocessingConfig"])
        code = "print('<|en|><|NEUTRAL|><|Speech|><|withitn|>hello')"
        config["commandTemplate"] = ["{binary}", "-c", code, "{audio}", "{weights}"]
        payload, hit = run_compact_adapter(
            wav_path=self.audio, config=config, cache=self.cache,
            lock_root=self.root / "lock", supervisor=self._supervisor,
        )
        self.assertFalse(hit)
        self.assertEqual(payload["outputs"]["emotionTag"], "NEUTRAL")
        self.assertEqual(payload["outputs"]["transcript"], "hello")
        drifted = copy.deepcopy(config)
        drifted["runtimeDependencies"]["runtime"] = "fixture-v2"
        with self.assertRaisesRegex(CompactAdapterError, "dependency identity"):
            validate_adapter_config(drifted)

    def test_unqualified_output_can_be_returned_for_forensics_but_is_not_cached(self) -> None:
        def unqualified(_command, **_kwargs):
            return SupervisedResult(
                report={
                    "qualified": False,
                    "qualificationFailures": ["post-exit-memory-recovery-unqualified"],
                },
                stdout=json.dumps({
                    "transcript": "hello", "languageTag": "en",
                    "emotionTag": "neutral", "eventTag": "speech",
                }).encode(),
                stderr=b"",
            )

        payload, hit = run_compact_adapter(
            wav_path=self.audio, config=self.config, cache=self.cache,
            lock_root=self.root / "lock", supervisor=unqualified,
            return_unqualified=True,
        )
        self.assertFalse(hit)
        self.assertFalse(payload["resourceEnvelope"]["qualified"])
        _payload, second_hit = run_compact_adapter(
            wav_path=self.audio, config=self.config, cache=self.cache,
            lock_root=self.root / "lock", supervisor=self._supervisor,
        )
        self.assertFalse(second_hit)


if __name__ == "__main__":
    unittest.main()
