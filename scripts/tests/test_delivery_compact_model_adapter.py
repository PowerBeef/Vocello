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
from unittest import mock
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from delivery_analysis_cache import (  # noqa: E402
    DeliveryAnalysisCache, digest, file_sha256, canonicalization_identity, RESAMPLER_VERSION,
)
from delivery_compact_model_adapter import (  # noqa: E402
    CompactAdapterError,
    bind_output_identity,
    run_compact_adapter,
    validate_adapter_config,
)
from delivery_resource_supervisor import HostSnapshot, run_supervised  # noqa: E402
from delivery_resource_supervisor import SupervisedResult  # noqa: E402
import delivery_resource_supervisor  # noqa: E402
import delivery_compact_model_adapter  # noqa: E402


class DeliveryCompactModelAdapterTests(unittest.TestCase):
    def test_preprocessing_mismatch_refuses_model_launch(self):
        from delivery_analysis_cache import FIR_VERSION, canonicalization_identity
        from unittest.mock import Mock
        cache = DeliveryAnalysisCache(self.root / 'v2', resampler_version=FIR_VERSION)
        self.config['preprocessingConfig'].pop('canonicalizationIdentity')
        self.config['preprocessingConfigDigest'] = digest(self.config['preprocessingConfig'])
        supervisor = Mock(side_effect=AssertionError('must not launch'))
        with self.assertRaisesRegex(ValueError, 'resampler'):
            run_compact_adapter(wav_path=self.audio, config=self.config, cache=cache,
                                lock_root=self.root, supervisor=supervisor)
        supervisor.assert_not_called()
        self.config['preprocessingConfig']['canonicalizationIdentity'] = canonicalization_identity(FIR_VERSION)
        self.config['preprocessingConfigDigest'] = digest(self.config['preprocessingConfig'])
        # Explicit v2 succeeds and the second call is a true no-model cache hit.
        payload, hit = run_compact_adapter(wav_path=self.audio, config=self.config, cache=cache,
                                          lock_root=self.root, supervisor=self._supervisor)
        self.assertFalse(hit)
        again, hit = run_compact_adapter(wav_path=self.audio, config=self.config, cache=cache,
                                        lock_root=self.root, supervisor=supervisor)
        self.assertTrue(hit)
        self.assertEqual(payload, again)
        supervisor.assert_not_called()

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.audio = self.root / "audio.wav"
        with wave.open(str(self.audio), "wb") as output:
            output.setnchannels(1); output.setsampwidth(2); output.setframerate(16_000)
            output.writeframes(struct.pack("<h", 100) * 3200)
        self.weights = self.root / "sensevoice-q8.gguf"
        self.weights.write_bytes(b"fixture weights")
        preprocessing = {
            "sampleRateHz": 16000, "channels": 1, "normalization": "none",
            "canonicalizationIdentity": canonicalization_identity(RESAMPLER_VERSION),
        }
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

    def test_mlx_adapter_measures_physical_footprint_by_default(self) -> None:
        calls = []

        def supervisor(command, **kwargs):
            calls.append(kwargs)
            output = {"transcript": "hello", "language": "en", "detectedLanguage": "en", "segments": [],
                      "languageTag": "en", "emotionTag": "neutral", "eventTag": "speech"}
            report = {"qualified": True, "qualificationFailures": []}
            return SupervisedResult(report, json.dumps(output).encode(), b"")

        whisper = copy.deepcopy(self.config)
        whisper["adapterID"] = "whisper-small-mlx"
        whisper["modelID"] = "whisper-small-mlx-fixture"
        run_compact_adapter(
            wav_path=self.audio, config=whisper, cache=self.cache,
            lock_root=self.root / "lock", supervisor=supervisor,
        )
        self.assertIs(calls[0]["measure_physical_footprint"], True)
        # CPU adapters keep their RSS-only envelope unless a caller asks.
        run_compact_adapter(
            wav_path=self.audio, config=self.config, cache=DeliveryAnalysisCache(self.root / "cpu"),
            lock_root=self.root / "lock", supervisor=supervisor,
        )
        self.assertNotIn("measure_physical_footprint", calls[1])

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

    def _v3_config(self) -> dict:
        config = copy.deepcopy(self.config)
        labels = {
            "languages": ["en"], "emotions": ["NEUTRAL"],
            "events": ["Speech"], "textNormalization": ["withitn"],
        }
        dependencies = {"runtime": "fixture-v1"}
        config.update({
            "outputFormat": "sensevoice-tagged-text",
            "sourceURI": "https://example.invalid/model/revision",
            "trainingDataSourceURI": "https://example.invalid/training-data",
            "labelMap": labels,
            "labelMapDigest": digest(labels),
            "runtimeDependencies": dependencies,
            "runtimeDependenciesDigest": digest(dependencies),
            "adapterSourceSHA256": file_sha256(Path(sys.executable)),
            "adapterLayerSHA256": file_sha256(Path(delivery_compact_model_adapter.__file__)),
        })
        code = "print('<|en|><|NEUTRAL|><|Speech|><|withitn|>hello')"
        config["commandTemplate"] = ["{binary}", "-c", code, "{audio}", "{weights}"]
        return bind_output_identity(config)

    def test_v3_tagged_output_binds_runtime_and_label_map(self) -> None:
        config = self._v3_config()
        self.assertEqual(config["executionIdentityVersion"], 3)
        self.assertNotIn("resourceSupervisorSHA256", json.dumps(config["preprocessingConfig"]))
        payload, hit = run_compact_adapter(
            wav_path=self.audio, config=config, cache=self.cache,
            lock_root=self.root / "lock", supervisor=self._supervisor,
        )
        self.assertFalse(hit)
        self.assertEqual(payload["outputs"]["emotionTag"], "NEUTRAL")
        self.assertEqual(payload["outputs"]["transcript"], "hello")
        provenance = payload["modelProvenance"]
        self.assertEqual(provenance["outputIdentityDigest"], config["outputIdentityDigest"])
        self.assertEqual(provenance["envelopeIdentity"]["resourceSupervisorSHA256"],
                         file_sha256(Path(delivery_resource_supervisor.__file__)))
        drifted = copy.deepcopy(config)
        drifted["runtimeDependencies"]["runtime"] = "fixture-v2"
        with self.assertRaisesRegex(CompactAdapterError, "dependency identity"):
            validate_adapter_config(drifted)
        unbound = copy.deepcopy(config)
        unbound["outputIdentityDigest"] = "0" * 64
        with self.assertRaisesRegex(CompactAdapterError, "output identity digest"):
            validate_adapter_config(unbound)
        # The resource supervisor never enters the output identity.
        leaked = copy.deepcopy(config)
        leaked["resourceSupervisorSHA256"] = "1" * 64
        with self.assertRaisesRegex(CompactAdapterError, "envelope identity"):
            validate_adapter_config(leaked)

    def test_supervisor_bound_v2_configs_must_be_prepared_again(self) -> None:
        legacy = copy.deepcopy(self._v3_config())
        legacy["executionIdentityVersion"] = 2
        with self.assertRaisesRegex(CompactAdapterError, "prepare the configuration again"):
            validate_adapter_config(legacy)

    def test_supervisor_only_change_replays_the_cache_offline(self) -> None:
        """Audit AQ-F47: a supervisor fix is envelope provenance, not a new output identity."""
        config = self._v3_config()
        first, hit = run_compact_adapter(
            wav_path=self.audio, config=config, cache=self.cache,
            lock_root=self.root / "lock", supervisor=self._supervisor,
        )
        self.assertFalse(hit)
        # A supervisor-only change: same code plus a fix, at a different digest.
        changed = self.root / "delivery_resource_supervisor.py"
        changed.write_bytes(Path(delivery_resource_supervisor.__file__).read_bytes()
                            + b"\n# a supervisor-only fix\n")
        original_envelope = delivery_compact_model_adapter.envelope_identity()

        def must_not_launch(*_args, **_kwargs):
            raise AssertionError("a supervisor-only change launched the model")

        with mock.patch.object(delivery_compact_model_adapter, "SUPERVISOR_SOURCE", changed):
            self.assertNotEqual(delivery_compact_model_adapter.envelope_identity(), original_envelope)
            self.assertIs(validate_adapter_config(config), config)
            replayed, hit = run_compact_adapter(
                wav_path=self.audio, config=config, cache=self.cache,
                lock_root=self.root / "lock", supervisor=must_not_launch,
            )
        self.assertTrue(hit)
        self.assertEqual(replayed, first)
        # The cached result keeps the envelope that measured it.
        self.assertEqual(replayed["modelProvenance"]["envelopeIdentity"], original_envelope)
        # An output-identity change is still a new measurement.
        runtime = copy.deepcopy(config)
        runtime["runtimeDependencies"] = {"runtime": "fixture-v2"}
        runtime["runtimeDependenciesDigest"] = digest(runtime["runtimeDependencies"])
        runtime = bind_output_identity(runtime)
        self.assertNotEqual(runtime["outputIdentityDigest"], config["outputIdentityDigest"])
        _payload, hit = run_compact_adapter(
            wav_path=self.audio, config=runtime, cache=self.cache,
            lock_root=self.root / "lock", supervisor=self._supervisor,
        )
        self.assertFalse(hit)

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

    def test_retired_judges_never_launch(self) -> None:
        retired = copy.deepcopy(self.config)
        retired["adapterID"] = "nisqa-v2"
        with self.assertRaisesRegex(CompactAdapterError, "candidate order"):
            validate_adapter_config(retired)
        # The registry is the execution gate even for a permitted adapter id.
        registry = json.loads((Path(__file__).resolve().parents[2]
                               / "config/audio-qc-judges.json").read_text(encoding="utf-8"))
        registry["judges"]["compact.sensevoice-small-q8@1"]["status"] = "quarantined"
        with mock.patch("audio_qc_judges.load_registry", return_value=registry):
            with self.assertRaisesRegex(CompactAdapterError, "quarantined"):
                validate_adapter_config(copy.deepcopy(self.config))


if __name__ == "__main__":
    unittest.main()
