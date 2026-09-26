#!/usr/bin/env python3
"""Pinned compact-model candidate contract tests."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock
import wave

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prepare_delivery_compact_model_config import (  # noqa: E402
    DEFAULT_CONTRACT,
    PreparationError,
    validate_candidate_contract,
    prepare,
)
from delivery_analysis_cache import (  # noqa: E402
    AnalysisCacheError, DeliveryAnalysisCache, canonicalization_identity, configured_resampler,
    digest, file_sha256, RESAMPLER_VERSION, LEGACY_RESAMPLER_VERSION,
)
from delivery_compact_model_adapter import (  # noqa: E402
    CompactAdapterError, run_compact_adapter, run_compact_adapter_batch, validate_adapter_config,
)
from delivery_resource_supervisor import SupervisedResult  # noqa: E402
from run_local_delivery_cascade import run_cascade  # noqa: E402
import delivery_resource_supervisor  # noqa: E402
import independent_asr  # noqa: E402

SUPERVISOR = Path(delivery_resource_supervisor.__file__)


class PrepareDeliveryCompactModelConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[2]
        cls.contract = json.loads(
            (root / "config/delivery-evaluator-v2-candidates.json").read_text(encoding="utf-8")
        )

    def test_tracked_candidate_contract_is_complete_and_research_only(self) -> None:
        self.assertIs(validate_candidate_contract(self.contract), self.contract)
        self.assertFalse(self.contract["normalCIPrerequisite"])
        self.assertFalse(self.contract["promotionAuthority"])

    def test_digest_runtime_and_adoption_drift_fail_closed(self) -> None:
        digest_drift = copy.deepcopy(self.contract)
        digest_drift["candidates"]["whisper-small-mlx"]["weightsSHA256"] = "0" * 63
        with self.assertRaisesRegex(PreparationError, "SHA-256"):
            validate_candidate_contract(digest_drift)
        runtime_drift = copy.deepcopy(self.contract)
        runtime_drift["candidates"]["whisper-small-mlx"]["runtimeDependencies"].pop("mlx")
        with self.assertRaisesRegex(PreparationError, "dependency pins"):
            validate_candidate_contract(runtime_drift)
        gate_drift = copy.deepcopy(self.contract)
        gate_drift["adoptionRequirements"].remove("untouched-independent-reference-holdout-gain")
        with self.assertRaisesRegex(PreparationError, "adoption requirements"):
            validate_candidate_contract(gate_drift)

    def test_whisper_candidate_prepares_from_the_local_snapshot_without_downloading(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contract = copy.deepcopy(self.contract)
            candidate = contract["candidates"]["whisper-small-mlx"]
            snapshot = root / "whisper-small-mlx"
            snapshot.mkdir()
            (snapshot / "weights.npz").write_bytes(b"fixture whisper weights")
            (snapshot / "config.json").write_text('{"n_mels": 80}')
            candidate["weightsSHA256"] = file_sha256(snapshot / "weights.npz")
            candidate["supportingFiles"]["config.json"] = file_sha256(snapshot / "config.json")
            contract_path = root / "contract.json"
            contract_path.write_text(json.dumps(contract))
            pins = candidate["runtimeDependencies"]
            with patch("prepare_delivery_compact_model_config._whisper_runtime_versions", return_value=dict(pins)):
                config = prepare("whisper-small-mlx", contract_path=contract_path, model_root=root)
            self.assertEqual(config["outputFormat"], "whisper-json")
            self.assertEqual(config["decodeOptions"]["languageLock"], "expected-language")
            self.assertEqual(config["weightsPath"], str(snapshot / "weights.npz"))
            # The recognizer child alone is the adapter source (audit #89).
            self.assertTrue(config["commandTemplate"][1].endswith("independent_asr_worker.py"))
            self.assertEqual(config["commandTemplate"][2], "--weights")
            self.assertIs(validate_adapter_config(config), config)
            self.assertEqual(config["executionIdentityVersion"], 4)
            self.assertNotIn("resourceSupervisorSHA256", json.dumps(config))
            # The template's worker is bound by repository-relative path, not this checkout's.
            self.assertEqual(config["preprocessingConfig"]["outputIdentity"]["commandTemplate"][1],
                             "{repository}/scripts/independent_asr_worker.py")

            changed = root / "delivery_resource_supervisor.py"
            changed.write_bytes(SUPERVISOR.read_bytes() + b"\n# a supervisor-only fix\n")
            with patch("delivery_compact_model_adapter.SUPERVISOR_SOURCE", changed), \
                    patch("prepare_delivery_compact_model_config._whisper_runtime_versions",
                          return_value=dict(pins)):
                again = prepare("whisper-small-mlx", contract_path=contract_path, model_root=root)
                self.assertIs(validate_adapter_config(config), config)
            self.assertEqual(again, config)
            self.assertEqual(independent_asr._provenance(again, language_code="en"),
                             independent_asr._provenance(config, language_code="en"))

            drifted = dict(pins, **{"mlx-whisper": "0.0.1"})
            with patch("prepare_delivery_compact_model_config._whisper_runtime_versions", return_value=drifted):
                with self.assertRaisesRegex(PreparationError, "dependency versions drifted"):
                    prepare("whisper-small-mlx", contract_path=contract_path, model_root=root)
            (snapshot / "weights.npz").write_bytes(b"tampered")
            with patch("prepare_delivery_compact_model_config._whisper_runtime_versions", return_value=dict(pins)):
                with self.assertRaisesRegex(PreparationError, "digest changed"):
                    prepare("whisper-small-mlx", contract_path=contract_path, model_root=root)
            unlocked = copy.deepcopy(contract)
            unlocked["candidates"]["whisper-small-mlx"]["decodeOptions"]["languageLock"] = "auto"
            with self.assertRaisesRegex(PreparationError, "lock the language"):
                validate_candidate_contract(unlocked)

    def test_a_candidate_off_its_registry_pin_never_prepares(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contract = copy.deepcopy(self.contract)
            contract["candidates"]["sensevoice-small-q8"]["sourceRevision"] = "1" * 40
            contract_path = root / "contract.json"
            contract_path.write_text(json.dumps(contract))
            with patch("prepare_delivery_compact_model_config._verified") as verify, \
                    self.assertRaisesRegex(PreparationError, "another model or revision"):
                prepare("sensevoice-small-q8", contract_path=contract_path, model_root=root)
            verify.assert_not_called()

    def test_retired_distilhubert_is_provenance_only(self) -> None:
        """AQ-05: retired as a measurand; its permissive license stays recorded."""
        retired = self.contract["retiredCandidates"]["distilhubert"]
        self.assertNotIn("distilhubert", self.contract["candidateOrder"])
        self.assertEqual((retired["status"], retired["licenseTier"], retired["commercialUseCompatible"]),
                         ("retired", "A", True))
        self.assertEqual(retired["registryJudge"], "compact.distilhubert@1")
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(PreparationError, "not registered"):
                prepare("distilhubert", contract_path=DEFAULT_CONTRACT, model_root=Path(temporary))
        mislabeled = copy.deepcopy(self.contract)
        mislabeled["retiredCandidates"]["distilhubert"]["commercialUseCompatible"] = False
        with self.assertRaisesRegex(PreparationError, "status and license"):
            validate_candidate_contract(mislabeled)
        revived = copy.deepcopy(self.contract)
        revived["candidateOrder"].insert(1, "distilhubert")
        with self.assertRaisesRegex(PreparationError, "candidate order"):
            validate_candidate_contract(revived)

    def test_retired_nisqa_keeps_corrected_provenance_and_never_prepares(self) -> None:
        retired = self.contract["retiredCandidates"]["nisqa-v2"]
        self.assertNotIn("nisqa-v2", self.contract["candidateOrder"])
        self.assertFalse(retired["commercialUseCompatible"])
        self.assertIn("CC BY-NC-SA 4.0", retired["license"])
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(PreparationError, "not registered"):
                prepare("nisqa-v2", contract_path=DEFAULT_CONTRACT, model_root=Path(temporary))
        for mutate, message in (
            (lambda c: c["retiredCandidates"]["nisqa-v2"].update(commercialUseCompatible=True),
             "status and license"),
            (lambda c: c["retiredCandidates"]["nisqa-v2"].pop("retiredOn"), "retiredOn"),
            (lambda c: c["candidates"].update({"nisqa-v2": c["retiredCandidates"]["nisqa-v2"]}),
             "coverage|both executable and retired"),
            (lambda c: c.pop("retiredCandidates"), "retired candidate provenance"),
        ):
            broken = copy.deepcopy(self.contract)
            mutate(broken)
            with self.assertRaisesRegex(PreparationError, message):
                validate_candidate_contract(broken)

    def test_adoption_names_the_canonical_host(self) -> None:
        self.assertIn("two-clean-canonical-host-runs", self.contract["adoptionRequirements"])
        stale = copy.deepcopy(self.contract)
        stale["adoptionRequirements"] = [
            "two-clean-eight-gib-host-runs" if item == "two-clean-canonical-host-runs" else item
            for item in stale["adoptionRequirements"]
        ]
        with self.assertRaisesRegex(PreparationError, "adoption requirements"):
            validate_candidate_contract(stale)

    def test_prepared_config_cache_adapter_and_cascade_agree_on_actual_model_input(self) -> None:
        # Only the external model process is a fixture. Exercise the real config
        # producer, validators, canonical writer, compact adapter and composer.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contract = copy.deepcopy(self.contract)
            candidate = contract["candidates"]["sensevoice-small-q8"]
            files = (
                ("sensevoice-q8/" + candidate["weightsFile"], b"fixture q8 weights", candidate, "weightsSHA256"),
                ("runtime-v0.1.9/" + candidate["runtime"]["archiveFile"], b"fixture archive",
                 candidate["runtime"], "archiveSHA256"),
                ("runtime-v0.1.9/extracted/" + candidate["runtime"]["binaryFile"], b"fixture binary",
                 candidate["runtime"], "binarySHA256"),
            )
            for name, content, target, field in files:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                target[field] = file_sha256(path)
            contract_path = root / "contract.json"
            contract_path.write_text(json.dumps(contract))
            config = prepare("sensevoice-small-q8", contract_path=contract_path, model_root=root)
            self.assertEqual(configured_resampler(config), RESAMPLER_VERSION)
            self.assertIs(validate_adapter_config(config), config)
            self.assertEqual(config["preprocessingConfigDigest"], digest(config["preprocessingConfig"]))

            audio = root / "tone.wav"
            samples = np.rint(8000 * np.sin(2*np.pi*150*np.arange(48001)/24000)).astype('<i2')
            with wave.open(str(audio), "wb") as wav:
                wav.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
                wav.writeframes(samples.tobytes())
            cache = DeliveryAnalysisCache(root / "cache")
            derivative = cache.canonicalize(audio)
            launches = []

            def model_process(command, **_kwargs):
                # Read the exact WAV passed across the process boundary, not a
                # recomputed expectation assembled from config fields.
                wav_path = Path(command[command.index("-a") + 1])
                with wave.open(str(wav_path), "rb") as reader:
                    self.assertEqual((reader.getframerate(), reader.getnchannels(), reader.getsampwidth()),
                                     (16000, 1, 2))
                    self.assertEqual(reader.getnframes(), 32001)
                    self.assertEqual(reader.readframes(reader.getnframes()), derivative.derivative_path.read_bytes())
                self.assertEqual(command[-3:], ["--backend", "cpu", "--keep-tags"])
                launches.append(wav_path)
                return SupervisedResult(
                    report={"qualified": True, "qualificationFailures": []},
                    stdout=b"<|en|><|NEUTRAL|><|Speech|><|withitn|>fixture", stderr=b"",
                )

            payload, hit = run_compact_adapter(
                wav_path=audio, config=config, cache=cache, lock_root=root, supervisor=model_process,
            )
            self.assertFalse(hit)
            self.assertFalse(launches[0].exists())
            never_launch = Mock(side_effect=AssertionError("cached representation launched a model"))
            retained, hit = run_compact_adapter(
                wav_path=audio, config=config, cache=cache, lock_root=root, supervisor=never_launch,
            )
            self.assertTrue(hit)
            self.assertEqual(retained, payload)
            manifest = {
                "schemaVersion": 1, "kind": "source-bound-delivery-cascade-input",
                "generationProcessExited": True, "executionPlanDigest": "1" * 64,
                "sourceDigests": {key: "2" * 64 for key in (
                    "retainedPlanSHA256", "executionStateSHA256", "acousticLayerSHA256",
                    "binarySHA256", "runnerSHA256", "analyzerSHA256", "temporalAnalyzerSHA256",
                )},
                "rows": [{
                    "generationID": "fixture-one", "speakerID": "aiden", "scriptID": "fixture",
                    "scriptTranslationGroup": "fixture", "seed": 1, "outputLanguage": "English",
                    "preset": "neutral", "instructedWAV": str(audio), "neutralWAV": str(audio),
                    "instructedSHA256": file_sha256(audio), "neutralSHA256": file_sha256(audio),
                }],
            }
            manifest["manifestDigest"] = digest(manifest)
            # Bind the real batch adapter with a no-launch guard. Identical paired
            # audio must reuse the representation the one-clip path cached.
            def cached_batch(**kwargs):
                return run_compact_adapter_batch(**kwargs, supervisor=never_launch)

            report = run_cascade(manifest=manifest, cache=cache, lock_root=root, compact_config=config,
                                 compact_runner=cached_batch)
            never_launch.assert_not_called()
            self.assertEqual(len(launches), 1)
            self.assertEqual(report["canonicalizationIdentity"], canonicalization_identity(RESAMPLER_VERSION))
            # No review evidence, so the automated review is inconclusive.
            self.assertEqual(report["rows"][0]["route"], "abstained")
            self.assertNotIn(str(root), json.dumps(report))
            self.assertEqual(report["rows"][0]["alwaysLayers"]["compactRepresentation"]["outputIdentityDigest"],
                             config["outputIdentityDigest"])

            # Offline replay (audit AQ-F47): after a supervisor-only change the
            # re-prepared config is identical and the cached representation is
            # served without launching anything.
            changed = root / "delivery_resource_supervisor.py"
            changed.write_bytes(SUPERVISOR.read_bytes() + b"\n# a supervisor-only fix\n")
            with patch("delivery_compact_model_adapter.SUPERVISOR_SOURCE", changed):
                replay_config = prepare("sensevoice-small-q8", contract_path=contract_path, model_root=root)
                self.assertEqual(replay_config, config)
                replayed, hit = run_compact_adapter(
                    wav_path=audio, config=replay_config, cache=cache, lock_root=root,
                    supervisor=never_launch,
                )
            self.assertTrue(hit)
            self.assertEqual(replayed, payload)
            never_launch.assert_not_called()

            legacy = prepare("sensevoice-small-q8", contract_path=contract_path, model_root=root,
                             resampler_version=LEGACY_RESAMPLER_VERSION)
            self.assertEqual(configured_resampler(legacy), LEGACY_RESAMPLER_VERSION)
            self.assertNotEqual(legacy["preprocessingConfigDigest"], config["preprocessingConfigDigest"])
            with self.assertRaisesRegex(ValueError, "resampler"):
                run_compact_adapter(wav_path=audio, config=legacy, cache=cache,
                                    lock_root=root, supervisor=never_launch)
            drifted = copy.deepcopy(config)
            drifted["preprocessingConfig"]["canonicalizationIdentity"]["cacheSourceSHA256"] = "0" * 64
            drifted["preprocessingConfigDigest"] = digest(drifted["preprocessingConfig"])
            with self.assertRaises(AnalysisCacheError):
                run_compact_adapter(wav_path=audio, config=drifted, cache=cache,
                                    lock_root=root, supervisor=never_launch)

    def test_a_run_of_clips_uses_one_persistent_worker(self) -> None:
        """AQ-F42: one supervised worker per run, never one process per clip."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contract = copy.deepcopy(self.contract)
            candidate = contract["candidates"]["sensevoice-small-q8"]
            for name, content, target, field in (
                ("sensevoice-q8/" + candidate["weightsFile"], b"fixture q8 weights", candidate, "weightsSHA256"),
                ("runtime-v0.1.9/" + candidate["runtime"]["archiveFile"], b"fixture archive",
                 candidate["runtime"], "archiveSHA256"),
                ("runtime-v0.1.9/extracted/" + candidate["runtime"]["binaryFile"], b"fixture binary",
                 candidate["runtime"], "binarySHA256"),
            ):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                target[field] = file_sha256(path)
            contract_path = root / "contract.json"
            contract_path.write_text(json.dumps(contract))
            config = prepare("sensevoice-small-q8", contract_path=contract_path, model_root=root)
            clips = []
            for index, frequency in enumerate((150, 190, 230)):
                clip = root / f"clip-{index}.wav"
                samples = np.rint(6000 * np.sin(2 * np.pi * frequency * np.arange(24000) / 24000)).astype("<i2")
                with wave.open(str(clip), "wb") as wav:
                    wav.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
                    wav.writeframes(samples.tobytes())
                clips.append(clip)
            cache = DeliveryAnalysisCache(root / "cache")
            launches = []

            def worker(command, **kwargs):
                job = json.loads(Path(command[command.index("--job") + 1]).read_text(encoding="utf-8"))
                launches.append((job, kwargs))
                self.assertEqual(job["engine"], "native-command")
                self.assertEqual(kwargs["environment"]["OMP_NUM_THREADS"], "2")
                self.assertEqual(kwargs["maximum_rss_bytes"], 5 * 1024**3)
                self.assertIsNone(kwargs["admission"])
                lines = [{"kind": "ready", "engine": "native-command", "threads": 2}]
                lines += [{"kind": "row", "id": row["id"], "childMaxRSSBytes": 1024,
                           "result": {"stdout": "<|en|><|NEUTRAL|><|Speech|><|withitn|>fixture", "wallSeconds": 0.1}}
                          for row in job["rows"]]
                lines.append({"kind": "done", "rows": len(job["rows"])})
                stdout = "".join(json.dumps(line) + "\n" for line in lines).encode()
                return SupervisedResult(report={"qualified": True, "qualificationFailures": [], "returnCode": 0},
                                        stdout=stdout, stderr=b"")

            # Two paths name the same audio: one row, one launch, every clip answered.
            results = run_compact_adapter_batch(wav_paths=clips + [clips[0]], config=config, cache=cache,
                                                lock_root=root, supervisor=worker)
            self.assertEqual(len(launches), 1)
            self.assertEqual(len(launches[0][0]["rows"]), 3)
            self.assertEqual({path for path in results}, set(clips))
            self.assertTrue(all(not hit for _payload, hit in results.values()))
            self.assertEqual(results[clips[0]][0]["modelProvenance"]["threads"], 2)
            # The one-clip path and a second run are served from the same cache entries.
            never = Mock(side_effect=AssertionError("a cached clip launched a model"))
            payload, hit = run_compact_adapter(wav_path=clips[1], config=config, cache=cache, lock_root=root,
                                               supervisor=never)
            self.assertTrue(hit)
            self.assertEqual(payload, results[clips[1]][0])
            again = run_compact_adapter_batch(wav_paths=clips, config=config, cache=cache, lock_root=root,
                                              supervisor=never)
            self.assertTrue(all(hit for _payload, hit in again.values()))
            never.assert_not_called()

            # A clip the worker never answers is refused after the others are cached.
            fresh = root / "fresh.wav"
            with wave.open(str(fresh), "wb") as wav:
                wav.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
                wav.writeframes(np.rint(5000 * np.sin(np.arange(24000) / 3)).astype("<i2").tobytes())

            def silent(command, **_kwargs):
                return SupervisedResult(report={"qualified": True, "qualificationFailures": [], "returnCode": 0},
                                        stdout=b'{"kind": "done", "rows": 1}\n', stderr=b"")

            with self.assertRaisesRegex(CompactAdapterError, "unavailable: crash"):
                run_compact_adapter_batch(wav_paths=[fresh], config=config, cache=cache, lock_root=root,
                                          supervisor=silent)

    def test_invalid_resampler_fails_before_asset_inspection(self) -> None:
        with patch("prepare_delivery_compact_model_config._verified") as verify:
            with self.assertRaisesRegex(PreparationError, "resampler"):
                prepare("sensevoice-small-q8", contract_path=Path("absent"),
                        model_root=Path("absent"), resampler_version="unknown")
            verify.assert_not_called()


if __name__ == "__main__":
    unittest.main()
