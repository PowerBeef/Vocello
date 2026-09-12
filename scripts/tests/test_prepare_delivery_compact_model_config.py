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
    PreparationError,
    validate_candidate_contract,
    prepare,
)
from delivery_analysis_cache import (  # noqa: E402
    AnalysisCacheError, DeliveryAnalysisCache, canonicalization_identity, configured_resampler,
    digest, file_sha256, RESAMPLER_VERSION, LEGACY_RESAMPLER_VERSION,
)
from delivery_compact_model_adapter import run_compact_adapter, validate_adapter_config  # noqa: E402
from delivery_resource_supervisor import SupervisedResult  # noqa: E402
from run_local_delivery_cascade import run_cascade  # noqa: E402


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
        digest_drift["candidates"]["distilhubert"]["weightsSHA256"] = "0" * 63
        with self.assertRaisesRegex(PreparationError, "SHA-256"):
            validate_candidate_contract(digest_drift)
        runtime_drift = copy.deepcopy(self.contract)
        runtime_drift["candidates"]["distilhubert"]["runtimeDependencies"].pop("torch")
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
            self.assertIn("independent_asr.py", config["commandTemplate"][1])
            self.assertIs(validate_adapter_config(config), config)

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
            # Bind the real adapter with a no-launch guard. Identical paired
            # audio must reuse the representation even across candidate arms.
            def cached_adapter(**kwargs):
                return run_compact_adapter(**kwargs, supervisor=never_launch)

            with patch("run_local_delivery_cascade.run_compact_adapter", side_effect=cached_adapter):
                report = run_cascade(manifest=manifest, cache=cache, lock_root=root, compact_config=config)
            never_launch.assert_not_called()
            self.assertEqual(len(launches), 1)
            self.assertEqual(report["canonicalizationIdentity"], canonicalization_identity(RESAMPLER_VERSION))
            self.assertEqual(report["rows"][0]["route"], "abstained")  # no calibrated heads
            self.assertNotIn(str(root), json.dumps(report))

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

    def test_invalid_resampler_fails_before_asset_inspection(self) -> None:
        with patch("prepare_delivery_compact_model_config._verified") as verify:
            with self.assertRaisesRegex(PreparationError, "resampler"):
                prepare("sensevoice-small-q8", contract_path=Path("absent"),
                        model_root=Path("absent"), resampler_version="unknown")
            verify.assert_not_called()


if __name__ == "__main__":
    unittest.main()
