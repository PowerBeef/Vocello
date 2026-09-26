#!/usr/bin/env python3
"""Pinned compact-model adapter tests without external model acquisition."""

from __future__ import annotations

import copy
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
    REPOSITORY,
    CompactAdapterError,
    bind_output_identity,
    normalized_command_template,
    run_compact_adapter,
    validate_adapter_config,
)
from delivery_resource_supervisor import HostSnapshot, run_supervised  # noqa: E402
from delivery_resource_supervisor import SupervisedResult  # noqa: E402
import delivery_resource_supervisor  # noqa: E402
import delivery_compact_model_adapter  # noqa: E402

REGISTRY = json.loads((Path(__file__).resolve().parents[2]
                       / "config/audio-qc-judges.json").read_text(encoding="utf-8"))


class DeliveryCompactModelAdapterTests(unittest.TestCase):
    def test_preprocessing_mismatch_refuses_model_launch(self):
        from delivery_analysis_cache import FIR_VERSION, canonicalization_identity
        from unittest.mock import Mock
        cache = DeliveryAnalysisCache(self.root / 'v2', resampler_version=FIR_VERSION)
        self.config['preprocessingConfig'].pop('canonicalizationIdentity')
        self.config = bind_output_identity(self.config)
        supervisor = Mock(side_effect=AssertionError('must not launch'))
        with self.assertRaisesRegex(ValueError, 'resampler'):
            run_compact_adapter(wav_path=self.audio, config=self.config, cache=cache,
                                lock_root=self.root, supervisor=supervisor)
        supervisor.assert_not_called()
        self.config['preprocessingConfig']['canonicalizationIdentity'] = canonicalization_identity(FIR_VERSION)
        self.config = bind_output_identity(self.config)
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
        labels = {"languages": ["en"]}
        dependencies = {"runtime": "fixture-v1"}
        # The registry's pinned repository and revision: the load gate refuses any other.
        pins = REGISTRY["judges"]["compact.sensevoice-small-q8@1"]["pins"]
        self.config = bind_output_identity({
            "schemaVersion": 1,
            "adapterID": "sensevoice-small-q8",
            "modelID": pins["repository"] + ":q8",
            "sourceRevision": pins["revision"],
            "weightsPath": str(self.weights),
            "weightsSHA256": file_sha256(self.weights),
            "binaryPath": sys.executable,
            "binarySHA256": file_sha256(Path(sys.executable)),
            # A native runtime is its own source: the template names no source file.
            "adapterSourceSHA256": file_sha256(Path(sys.executable)),
            "adapterLayerSHA256": file_sha256(Path(delivery_compact_model_adapter.__file__)),
            "license": "Apache-2.0-fixture",
            "commercialUseCompatible": True,
            "trainingDataDeclaration": "fixture-declaration",
            "sourceURI": "https://example.invalid/model/revision",
            "trainingDataSourceURI": "https://example.invalid/training-data",
            "labelMap": labels,
            "labelMapDigest": digest(labels),
            "runtimeDependencies": dependencies,
            "runtimeDependenciesDigest": digest(dependencies),
            "outputFormat": "json",
            "preprocessingConfig": preprocessing,
            "offlineAfterAcquisition": True,
            "commandTemplate": ["{binary}", "-c", code, "{audio}", "{weights}"],
        })
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
        pins = REGISTRY["judges"]["asr.whisper-small@1"]["pins"]
        whisper.update(adapterID="whisper-small-mlx", modelID=pins["repository"], sourceRevision=pins["revision"])
        whisper = bind_output_identity(whisper)
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

    def test_a_model_off_the_registry_pin_never_launches(self) -> None:
        supervisor = mock.Mock(side_effect=AssertionError("must not launch"))
        for field, value in (("sourceRevision", "1" * 40), ("modelID", "FunAudioLLM/SenseVoiceLarge:q8")):
            changed = bind_output_identity({**self.config, field: value})
            with self.subTest(field=field), self.assertRaisesRegex(CompactAdapterError, "another model or revision"):
                run_compact_adapter(wav_path=self.audio, config=changed, cache=self.cache,
                                    lock_root=self.root / "lock", supervisor=supervisor)
        excluded = bind_output_identity({**self.config, "runtimeDependencies": {"zhconv": "1.4.3"},
                                         "runtimeDependenciesDigest": digest({"zhconv": "1.4.3"})})
        with self.assertRaisesRegex(CompactAdapterError, "package zhconv is excluded"):
            validate_adapter_config(excluded)
        supervisor.assert_not_called()

    def _tagged_config(self) -> dict:
        config = copy.deepcopy(self.config)
        labels = {
            "languages": ["en"], "emotions": ["NEUTRAL"],
            "events": ["Speech"], "textNormalization": ["withitn"],
        }
        config.update({
            "outputFormat": "sensevoice-tagged-text",
            "labelMap": labels,
            "labelMapDigest": digest(labels),
        })
        code = "print('<|en|><|NEUTRAL|><|Speech|><|withitn|>hello')"
        config["commandTemplate"] = ["{binary}", "-c", code, "{audio}", "{weights}"]
        return bind_output_identity(config)

    def test_tagged_output_binds_runtime_and_label_map(self) -> None:
        config = self._tagged_config()
        self.assertEqual(config["executionIdentityVersion"], 4)
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

    def test_every_older_identity_version_must_be_prepared_again(self) -> None:
        for version, reason in ((1, "binds no output identity"),
                                (2, "binds the resource supervisor"),
                                (3, "binds neither its command template nor its host"),
                                ("4", "is unsupported")):
            legacy = copy.deepcopy(self.config)
            legacy["executionIdentityVersion"] = version
            with self.subTest(version=version), self.assertRaisesRegex(
                CompactAdapterError, f"{reason}.*prepare the configuration again"
            ):
                validate_adapter_config(legacy)
        unversioned = copy.deepcopy(self.config)
        del unversioned["executionIdentityVersion"]
        with self.assertRaisesRegex(CompactAdapterError, "v1 binds no output identity"):
            validate_adapter_config(unversioned)

    def test_command_template_and_host_are_output_identity(self) -> None:
        flagged = bind_output_identity({
            **self.config, "commandTemplate": [*self.config["commandTemplate"], "--keep-tags"],
        })
        self.assertNotEqual(flagged["outputIdentityDigest"], self.config["outputIdentityDigest"])
        # Repository paths are bound relative, so every checkout shares one identity.
        source = REPOSITORY / "scripts/delivery_compact_model_runtime.py"
        self.assertEqual(normalized_command_template(["{binary}", str(source), "--audio", "{audio}"]),
                         ["{binary}", "{repository}/scripts/delivery_compact_model_runtime.py",
                          "--audio", "{audio}"])
        self.assertEqual(self.config["preprocessingConfig"]["outputIdentity"]["hostProfile"],
                         self.config["hostProfile"])
        other_host = {"system": "Darwin", "machine": "arm64", "modelIdentifier": "Mac14,3"}
        with mock.patch.object(delivery_compact_model_adapter, "host_profile", return_value=other_host):
            with self.assertRaisesRegex(CompactAdapterError, "prepared on another host"):
                validate_adapter_config(self.config)
            moved = bind_output_identity(self.config)
            self.assertIs(validate_adapter_config(moved), moved)
        self.assertNotEqual(moved["outputIdentityDigest"], self.config["outputIdentityDigest"])

    def test_an_edited_adapter_source_is_refused_not_served_from_the_cache(self) -> None:
        source = self.root / "runtime.py"
        source.write_text(
            "import json\nprint(json.dumps({'transcript':'hello','languageTag':'en',"
            "'emotionTag':'neutral','eventTag':'speech'}))\n", encoding="utf-8",
        )
        config = bind_output_identity({
            **self.config, "adapterSourceSHA256": file_sha256(source),
            "commandTemplate": ["{binary}", str(source), "{audio}", "{weights}"],
        })
        _payload, hit = run_compact_adapter(
            wav_path=self.audio, config=config, cache=self.cache,
            lock_root=self.root / "lock", supervisor=self._supervisor,
        )
        self.assertFalse(hit)
        source.write_text(source.read_text(encoding="utf-8") + "# edited\n", encoding="utf-8")
        never = mock.Mock(side_effect=AssertionError("an edited source launched"))
        with self.assertRaisesRegex(CompactAdapterError, "source drifted"):
            run_compact_adapter(wav_path=self.audio, config=config, cache=self.cache,
                                lock_root=self.root / "lock", supervisor=never)
        never.assert_not_called()
        for template, message in (
            (["{binary}", "runtime.py", "{audio}", "{weights}"], "absolute path"),
            (["{binary}", str(source), str(source), "{audio}", "{weights}"], "more than one source"),
            (["{binary}", str(self.root / "absent.py"), "{audio}", "{weights}"], "missing"),
        ):
            with self.subTest(template=template), self.assertRaisesRegex(CompactAdapterError, message):
                validate_adapter_config({**config, "commandTemplate": template})

    def test_supervisor_only_change_replays_the_cache_offline(self) -> None:
        """Audit AQ-F47: a supervisor fix is envelope provenance, not a new output identity."""
        config = self._tagged_config()
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
        registry = copy.deepcopy(REGISTRY)
        registry["judges"]["compact.sensevoice-small-q8@1"]["status"] = "quarantined"
        with mock.patch("audio_qc_judges.load_registry", return_value=registry):
            with self.assertRaisesRegex(CompactAdapterError, "quarantined"):
                validate_adapter_config(copy.deepcopy(self.config))


if __name__ == "__main__":
    unittest.main()
