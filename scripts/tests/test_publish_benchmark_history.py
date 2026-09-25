#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import contextlib
import hashlib
import io
import json
from pathlib import Path
import plistlib
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest import mock
import wave


SCRIPT = Path(__file__).resolve().parents[1] / "publish_benchmark_history.py"
SPEC = importlib.util.spec_from_file_location("publish_benchmark_history", SCRIPT)
assert SPEC and SPEC.loader
publisher = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = publisher
SPEC.loader.exec_module(publisher)

TEST_HELPERS = SCRIPT.parent / "tests"
if str(TEST_HELPERS) not in sys.path:
    sys.path.insert(0, str(TEST_HELPERS))
from test_benchmark_memory import (  # noqa: E402
    ENGINE_BOUNDARIES,
    row as memory_row,
    samples as memory_samples,
)


def source_fixture() -> dict:
    return {
        "commit": "a" * 40,
        "dirty": False,
        "changedPaths": [],
        "workspaceFingerprint": "b" * 64,
        "preFingerprint": "b" * 64,
        "postFingerprint": "b" * 64,
        "fingerprintsMatch": True,
    }


def engine_row(generation_id: str, *, run_id: str = "run-one", cell: str = "custom/speed/medium/warm#0", qc: str = "pass") -> dict:
    return {
        "schemaVersion": 7,
        "generationID": generation_id,
        "layer": "engine",
        "mode": "custom",
        "modelID": "pro_custom_speed",
        "modelRuntimeIdentity": {
            "resolvedModelID": "pro_custom_speed",
            "modelRepository": "PowerBeef02/Qwen3-TTS-12Hz-1.7B-CustomVoice-4bit",
            "huggingFaceRevision": "29c4b746cd1e2a916f0233b241019205dffbfbc2",
            "artifactVersion": "2026.09.14.1",
            "quantization": "4-bit",
            "integrityManifestDigest": "f" * 64,
            "runtimeProfileSignature": "pro_custom_speed:fixture-v1",
        },
        "warmState": "warm",
        "finishReason": "eos",
        "notes": {
            "benchRunID": run_id,
            "benchTakeIndex": "1",
            "benchCell": cell,
            "promptDigest": "1" * 64,
            "samplingSeed": "42",
            "samplingVariation": "expressive",
        },
        "derivedMetrics": {
            "audioSeconds": 2.0,
            "requestWallSeconds": 1.5,
            "realTimeFactor": 0.75,
            "audioSecondsPerWallSecond": 1.5,
            "tokensPerSecond": 20.0,
            "generatedTokenCount": 42,
        },
        "backendMetrics": {
            "finishReason": "eos",
            "warmState": "warm",
            "usedStreaming": True,
            "stages": [],
            "timings": [{"key": "modelLoad", "milliseconds": 4.0}],
            "counters": [],
            "finalChunkBarrierObserved": True,
        },
        "summary": {"physFootprintPeakMB": 100.0},
        "timingsMS": {"native_model_load_ms": 4.0},
        "thermalState": {"worst": "nominal"},
        "outputMetrics": {
            "readableWAV": True,
            "atomicallyPublished": True,
            "durationSeconds": 2.0,
        },
        "audioQC": {
            "algorithmVersion": 2,
            "verdict": qc,
            "instabilityVerdict": "pass",
            "writtenOutputVerdict": qc,
            "flags": ["long-silence"] if qc == "warn" else [],
            "clickEvents": 0,
            "clippedSamples": 0,
            "nonFiniteSamples": 0,
            "longestSilenceMS": 10,
        },
    }


def app_row(generation_id: str, *, run_id: str = "lang-ios", cell: str = "fr") -> dict:
    return {
        "schemaVersion": 7,
        "generationID": generation_id,
        "layer": "app",
        "mode": "custom",
        "finishReason": "completed",
        "notes": {
            "benchRunID": run_id,
            "benchCell": cell,
        },
        "timingsMS": {"submitToCompletedMS": 100},
        "frontendMetrics": {"submitToCompletedMS": 100},
    }


def ios_benchmark_app_row(
    generation_id: str,
    *,
    run_id: str,
    cell: str,
    take_index: int = 1,
    mode: str = "custom",
) -> dict:
    row = app_row(generation_id, run_id=run_id, cell=cell)
    row["schemaVersion"] = 8
    row["mode"] = mode
    row["notes"]["benchTakeIndex"] = str(take_index)
    return row


def successful_asr_verification(
    *,
    reference: str = "un deux trois quatre cinq six sept huit",
    transcript: str = "un deux trois quatre cinq six sept neuf",
) -> dict:
    word_metrics, character_metrics = publisher.recomputed_accuracy(
        reference, transcript, "french",
    )
    repetitions = [
        {
            "passIndex": index,
            "localeIdentifier": "fr-CA",
            "authorizationStatus": "authorized",
            "recognizerAvailable": True,
            "supportsOnDeviceRecognition": True,
            "finalResultStatus": "finalResult",
            "recognitionDurationSeconds": 0.1,
            "transcript": transcript,
            "segmentCount": 4,
            "segmentStartSeconds": 0.0,
            "segmentEndSeconds": 1.9,
            "timingCoverageSeconds": 1.9,
            "averageConfidence": 0.9,
            "minimumConfidence": 0.8,
            "errorDomain": None,
            "errorCode": None,
        }
        for index in range(1, 4)
    ]
    return {
        "schemaVersion": 3,
        "algorithmVersion": "language-output-verifier-v3",
        "transcript": transcript,
        "detectedLanguage": "french",
        "expectedLanguage": "french",
        "languageMatchScore": 0.875,
        "wordErrorRate": word_metrics["errorRate"],
        "characterErrorRate": character_metrics["errorRate"],
        "accuracyMetric": "wordErrorRate",
        "accuracyMetricVersion": "normalized-edit-rate-v1",
        "accuracyThreshold": 0.15,
        "accuracyValue": word_metrics["errorRate"],
        "referenceTokenCount": word_metrics["referenceCount"],
        "hypothesisTokenCount": word_metrics["hypothesisCount"],
        "referenceCharacterCount": character_metrics["referenceCount"],
        "hypothesisCharacterCount": character_metrics["hypothesisCount"],
        "substitutions": word_metrics["substitutions"],
        "insertions": word_metrics["insertions"],
        "deletions": word_metrics["deletions"],
        "characterSubstitutions": character_metrics["substitutions"],
        "characterInsertions": character_metrics["insertions"],
        "characterDeletions": character_metrics["deletions"],
        "languagePass": True,
        "accuracyPass": True,
        "pass": True,
        "skipReason": None,
        "recognition": {
            "schemaVersion": 2,
            "algorithmVersion": "apple-speech-file-consensus-v2",
            "expectedLanguage": "french",
            "selectedLocaleIdentifier": "fr-CA",
            "authorizationStatus": "authorized",
            "recognizerAvailable": True,
            "supportsOnDeviceRecognition": True,
            "requiredPassCount": 3,
            "recognitionDurationSeconds": 0.3,
            "repetitions": repetitions,
            "evidenceConsistency": True,
            "consensusStatus": "consistent",
            "transcript": transcript,
        },
    }


def language_plan(
    *, matrix: Path, corpus: Path, run_id: str = "lang-ios", seed: int | None = None
) -> dict:
    if seed is None:
        seed = publisher.stable_default_seed({"mode": "custom", "scriptLang": "french"})
    plan = {
        "schemaVersion": 1,
        "runID": run_id,
        "subset": "quick",
        "kind": "languageBenchmark",
        "matrixDigest": publisher.digest_file(matrix),
        "corpusDigest": publisher.digest_file(corpus),
        "cohortID": None,
        "cohortDigest": None,
        "seedPolicy": publisher.LANGUAGE_SEED_POLICY,
        "samplingVariation": "expressive",
        "promptEquivalenceGroups": [],
        "requireEveryTakePass": True,
        "takeCount": 1,
        "takes": [{
            "takeIndex": 1,
            "seedIndex": None,
            "seed": seed,
            "samplingVariation": "expressive",
            "cellID": "fr",
            "childRunID": f"{run_id}--fr",
            "mode": "custom",
            "variant": "speed",
            "uiHint": "auto",
            "scriptLang": "french",
            "expectedHint": "french",
            "customSpeakerID": "aiden",
            "designInstruction": None,
            "designInstructionDigest": None,
            "promptEquivalenceGroup": None,
            "skipOutputVerification": False,
        }],
    }
    plan["planDigest"] = publisher.digest_bytes(publisher.canonical_bytes(plan))
    return plan


def language_sentinel(
    *, output_path: Path, seed: int = 42, verification: dict | None = None
) -> dict:
    with wave.open(str(output_path), "rb") as stream:
        sample_rate = stream.getframerate()
        channels = stream.getnchannels()
        frames = stream.getnframes()
    return {
        "schemaVersion": 2,
        "runID": "lang-ios--fr",
        "generationID": "fr-generation",
        "status": "ok",
        "seed": seed,
        "samplingVariation": "expressive",
        "requestedLanguageHint": "auto",
        "languageHintSource": "auto",
        "customSpeakerID": "aiden",
        "fixtureDigest": None,
        "deviceModel": "iPhone",
        "systemName": "iOS",
        "systemVersion": "26.5",
        "outputEvidence": {
            "artifactRelativePath": "output.wav",
            "sha256": publisher.digest_file(output_path),
            "byteCount": output_path.stat().st_size,
            "durationSeconds": frames / sample_rate,
            "sampleRate": sample_rate,
            "channelCount": channels,
            "frameCount": frames,
        },
        "outputVerification": verification or successful_asr_verification(),
    }


def independent_recognition(*, audio_sha256: str, script: str, transcript: str | None = None,
                            language: str = "french", detected: str | None = None,
                            duration: float = 2.0, provenance: dict | None = None) -> dict:
    """One whisper-family recognition as `scripts/independent_asr.py` emits it."""
    return {
        "schemaVersion": 1,
        "algorithmVersion": publisher.INDEPENDENT_ASR_ALGORITHM,
        "modelFamily": "whisper",
        "audioSHA256": audio_sha256,
        "inputTextSHA256": publisher.text_sha256(script),
        "status": "complete",
        "outputLanguage": language,
        "decodeLanguage": "fr",
        "detectedLanguage": detected or language,
        "languageMatchScore": 0.97,
        "detectedLanguageProbability": 0.97,
        "fullFileProcessed": True,
        "processedDurationSeconds": duration,
        "segmentCount": 1,
        "firstSegmentStartSeconds": 0.0,
        "lastSegmentEndSeconds": duration,
        "recognitionDurationSeconds": 0.4,
        "maximumNoSpeechProbability": 0.02,
        "meanAverageLogProbability": -0.25,
        "transcript": script if transcript is None else transcript,
        "provenance": provenance or {
            "runtimeSHA256": "1" * 64, "modelIdentitySHA256": "2" * 64, "configSHA256": "3" * 64,
        },
    }


def independent_evidence(path: Path, *, run_id: str, platform: str, cells: dict) -> Path:
    path.write_text(json.dumps({
        "schemaVersion": 1,
        "kind": "independent-asr-language-evidence",
        "runID": run_id,
        "platform": platform,
        "generationProcessExited": True,
        "families": ["whisper"],
        "producer": {
            "adapterID": "whisper-small-mlx", "algorithmVersion": publisher.INDEPENDENT_ASR_ALGORITHM,
            "modelLaunches": 1, "cacheHits": 0, "rowCount": len(cells),
            "resourceEnvelope": {"qualified": True, "peakRSSBytes": 900 * 1024**2},
        },
        "cells": cells,
    }))
    return path


def qualified_memory_fixture(generation_ids: list[str]) -> tuple[list[SimpleNamespace], dict]:
    qualified = [
        SimpleNamespace(
            generation_id=generation_id,
            metrics={"peakPhysicalFootprintMB": 100.0},
            sidecar_digest=(f"{index:x}" * 64)[:64],
            status="qualified",
            warnings=(),
        )
        for index, generation_id in enumerate(generation_ids, start=1)
    ]
    payload = [
        {
            "generationID": item.generation_id,
            "digest": item.sidecar_digest,
            "layers": {"engine": item.sidecar_digest},
        }
        for item in qualified
    ]
    return qualified, {
        "memoryContractVersion": 1,
        "memoryQualified": True,
        "sampleSidecarCount": len(qualified),
        "sampleSidecarsDigest": "e" * 64,
        "status": "qualified",
        "warnings": [],
        "digestPayload": payload,
    }


def upgrade_language_memory_row(row: dict, diagnostics: Path, *, ios: bool) -> None:
    sidecar = memory_samples(
        role="engine", boundaries=ENGINE_BOUNDARIES, ios=ios, footprint=3000 if ios else 2500
    )
    memory = memory_row(row["generationID"], sidecar, layer="engine", ios=ios)
    row["schemaVersion"] = 8
    row["summary"] = memory["summary"]
    row["memoryMetrics"] = memory["memoryMetrics"]
    row["backendMetrics"] = {
        **row.get("backendMetrics", {}),
        "stages": [],
    }
    directory = diagnostics / "engine"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"samples-{row['generationID']}.jsonl").write_text(
        "".join(json.dumps(sample, sort_keys=True) + "\n" for sample in sidecar),
        encoding="utf-8",
    )


class PublisherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def capture_manifest(self):
        captured: dict = {}

        def fake_write(artifact_dir, manifest, **kwargs):
            captured["manifest"] = manifest
            captured["deferRecord"] = kwargs.get("defer_record", False)
            return artifact_dir / "benchmark-evidence.json"

        return captured, mock.patch.object(publisher, "write_and_record", side_effect=fake_write)

    def hardware_patch(self):
        """Live-host evidence the fixtures cannot supply: canonical hardware and
        the hash-bound build receipts that prove the optimization label."""
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(
            publisher,
            "verify_canonical_hardware",
            side_effect=lambda platform, **_kwargs: {
                "profileID": "mac-mini-m6-16gb" if platform == "macos" else "iphone-17-pro"
            },
        ))
        stack.enter_context(mock.patch.object(
            publisher, "validated_ios_app_optimization", return_value="-O",
        ))
        stack.enter_context(mock.patch.object(
            publisher, "validated_macos_cli_optimization", return_value="-O",
        ))
        return stack

    def make_wave(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(24_000)
            stream.writeframes(b"\0\0" * 240)

    def write_cli_provenance(self, binary: Path, *, optimization: str = "O") -> Path:
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.write_bytes(b"optimized-vocello-fixture")
        path = binary.with_name(binary.name + ".provenance.json")
        path.write_text(json.dumps({
            "schemaVersion": 1,
            "producer": "scripts/build.sh cli-optimized",
            "status": "passed",
            "scheme": "VocelloCLI",
            "configuration": "Release",
            "architecture": "arm64",
            "optimization": optimization,
            "executableRelativePath": binary.resolve().relative_to(self.root.resolve()).as_posix(),
            "executableSHA256": publisher.digest_file(binary),
        }), encoding="utf-8")
        return path

    def test_macos_cli_optimization_requires_exact_hash_bound_provenance(self) -> None:
        binary = self.root / "build" / "vocello"
        self.write_cli_provenance(binary)
        with mock.patch.object(publisher, "ROOT", self.root):
            self.assertEqual(publisher.validated_macos_cli_optimization(binary), "-O")

            binary.write_bytes(b"different-binary")
            with self.assertRaisesRegex(publisher.PublicationError, "executableSHA256"):
                publisher.validated_macos_cli_optimization(binary)

    def test_macos_cli_optimization_rejects_unoptimized_build(self) -> None:
        binary = self.root / "build" / "vocello"
        self.write_cli_provenance(binary, optimization="Onone")
        with mock.patch.object(publisher, "ROOT", self.root):
            with self.assertRaisesRegex(publisher.PublicationError, "optimization"):
                publisher.validated_macos_cli_optimization(binary)

    def test_engine_uses_only_ordered_manifest_generations(self) -> None:
        diagnostics = self.root / "diagnostics"
        output_dir = self.root / "outputs"
        diagnostics.mkdir()
        self.make_wave(output_dir / "take.wav")
        results = diagnostics / "bench-results.json"
        results.write_text(json.dumps({
            "schemaVersion": 1,
            "runID": "run-one",
            "label": "fixture",
            "startedAt": "2026-07-12T12:00:00Z",
            "finishedAt": "2026-07-12T12:01:00Z",
            "telemetryMode": "verbose",
            "seed": 42,
            "streaming": True,
            "executableSHA256": "a" * 64,
            "fixtureDigests": {},
            "takes": [{
                "takeIndex": 1,
                "generationID": "selected",
                "cell": "custom/speed/medium/warm#0",
                "mode": "custom",
                "modelID": "pro_custom_speed",
                "variant": "speed",
                "length": "medium",
                "warmState": "warm",
                "wallSeconds": 1.0,
                "audioSeconds": 2.0,
                "firstChunkMS": 100,
                "firstChunkUptimeNS": 9_000_004_000_000,
                "outputFileName": "take.wav",
            }],
        }))
        unrelated = [engine_row(f"old-{index}", run_id="old") for index in range(300)]
        selected = engine_row("selected")
        selected["streamingTelemetryV9"] = {"chunks": [{
            "index": 0, "transportSequence": 0, "previewPublishedAtNS": 9_000_000_000_000,
        }]}
        args = SimpleNamespace(
            results=results, run_id="run-one", diagnostics=diagnostics,
            output_dir=output_dir, platform="macos", artifact_dir=diagnostics,
            snapshot=self.root / "snapshot.json", label="fixture",
        )
        captured, write_patch = self.capture_manifest()
        with (
            mock.patch.object(publisher, "load_engine_rows", return_value=unrelated + [selected]),
            mock.patch.object(
                publisher,
                "qualify_memory_rows",
                return_value=([SimpleNamespace(
                    generation_id="selected", metrics={}, sidecar_digest="f" * 64,
                    status="qualified", warnings=(),
                )], {
                    "memoryContractVersion": 1, "memoryQualified": True,
                    "sampleSidecarCount": 1, "sampleSidecarsDigest": "e" * 64,
                    "digestPayload": [{"generationID": "selected", "digest": "f" * 64}],
                }),
            ),
            mock.patch.object(publisher, "source_from_snapshot", return_value=source_fixture()),
            mock.patch.object(publisher, "crash_delta_from_snapshot", return_value={"passed": True, "count": 0}),
            mock.patch.object(publisher, "validated_macos_cli_optimization", return_value="-O"),
            self.hardware_patch(),
            write_patch,
        ):
            publisher.engine_command(args)
        record = captured["manifest"]["historyRecord"]
        self.assertEqual([take["generationID"] for take in record["takes"]], ["selected"])
        self.assertEqual(record["takes"][0]["metrics"]["ttfcMS"], 100.0)
        # The observer's lag behind the engine's first-chunk hand-off (audit #48).
        self.assertEqual(record["takes"][0]["metrics"]["ttfcObserverLagMS"], 4.0)
        # Standard RTF comes from the engine row (request wall ÷ audio), never from
        # the bench take's wall clock; the decode speedup keeps its own key.
        metrics = record["takes"][0]["metrics"]
        self.assertEqual(metrics["rtf"], 0.75)
        self.assertEqual(metrics["requestWallSeconds"], 1.5)
        self.assertEqual(metrics["decodeSpeedupX"], 1.5)
        self.assertEqual(record["run"]["rtfDefinition"], "wall/audio")
        # The macOS CLI bench stamps ttfcMS from its own submission (audit #59).
        self.assertEqual(record["run"]["ttfcDefinition"], "cli-submit-to-first-chunk")
        self.assertEqual(
            record["takes"][0]["runtimeProfileSignature"],
            "pro_custom_speed:fixture-v1",
        )
        self.assertEqual(record["toolchain"]["optimization"], "-O")
        self.assertEqual(record["evidence"]["actualTakeCount"], 1)

    def test_ttfc_definition_follows_the_bench_results_producer(self) -> None:
        with_ttfc = [{"metrics": {"ttfcMS": 400.0}}, {"metrics": {}}]
        self.assertEqual(
            publisher.engine_ttfc_definition("macos", with_ttfc), "cli-submit-to-first-chunk"
        )
        self.assertEqual(
            publisher.engine_ttfc_definition("ios", with_ttfc), "engine-prepare-to-first-chunk"
        )
        self.assertIsNone(publisher.engine_ttfc_definition("macos", [{"metrics": {}}]))

    def test_row_metrics_publish_the_startup_windows_rtf_excludes(self) -> None:
        row = engine_row("windows")
        row["backendMetrics"]["stages"] = [
            {"stage": "startup.model_load_started", "tMS": 10},
            {"stage": "startup.model_loaded", "tMS": 1_210},
            {"stage": "startup.prewarm_started", "tMS": 1_220},
            {"stage": "startup.prewarm_completed", "tMS": 1_520},
            {"stage": "streamCompleted", "tMS": 4_000},
        ]
        metrics = publisher.row_metrics(row)
        self.assertEqual(metrics["modelLoadWindowMS"], 1_200.0)
        self.assertEqual(metrics["prewarmWindowMS"], 300.0)
        self.assertEqual(metrics["excludedStartupMS"], 1_500.0)
        # prewarmMS keeps timing the explicit prewarm; it is not the window.
        self.assertNotIn("prewarmMS", metrics)
        self.assertNotIn("excludedStartupMS", publisher.row_metrics(engine_row("no-marks")))

    def gate_results(self, diagnostics: Path, *, seed: int | None) -> Path:
        results = diagnostics / "bench-results.json"
        results.write_text(json.dumps({
            "schemaVersion": 1, "runID": "run-one", "label": "fixture",
            "startedAt": "2026-07-12T12:00:00Z", "finishedAt": "2026-07-12T12:01:00Z",
            "telemetryMode": "verbose", "seed": seed, "streaming": True,
            "executableSHA256": "a" * 64, "fixtureDigests": {},
            "takes": [{
                "takeIndex": 1, "generationID": "selected", "cell": "custom/speed/medium/warm#0",
                "mode": "custom", "modelID": "pro_custom_speed", "variant": "speed",
                "length": "medium", "warmState": "warm", "wallSeconds": 1.0,
                "audioSeconds": 2.0, "firstChunkMS": 100, "outputFileName": "take.wav",
            }],
        }))
        return results

    def publish_gate_fixture(self, row: dict, *, seed: int | None, snapshot: Path) -> dict:
        diagnostics = self.root / "diagnostics"
        output_dir = self.root / "outputs"
        diagnostics.mkdir(exist_ok=True)
        self.make_wave(output_dir / "take.wav")
        args = SimpleNamespace(
            results=self.gate_results(diagnostics, seed=seed), run_id="run-one",
            diagnostics=diagnostics, output_dir=output_dir, platform="macos",
            artifact_dir=diagnostics, snapshot=snapshot, label="fixture",
        )
        captured, write_patch = self.capture_manifest()
        with (
            mock.patch.object(publisher, "load_engine_rows", return_value=[row]),
            mock.patch.object(
                publisher, "qualify_memory_rows",
                return_value=([SimpleNamespace(
                    generation_id="selected", metrics={}, sidecar_digest="f" * 64,
                    status="qualified", warnings=(),
                )], {
                    "memoryContractVersion": 1, "memoryQualified": True,
                    "sampleSidecarCount": 1, "sampleSidecarsDigest": "e" * 64,
                    "digestPayload": [{"generationID": "selected", "digest": "f" * 64}],
                }),
            ),
            mock.patch.object(publisher, "source_from_snapshot", return_value=source_fixture()),
            mock.patch.object(publisher, "crash_delta_from_snapshot", return_value={"passed": True, "count": 0}),
            self.hardware_patch(),
            write_patch,
        ):
            publisher.engine_command(args)
        return captured["manifest"]["historyRecord"]

    def test_engine_publishes_the_seed_per_take_load_and_run_time_host_identity(self) -> None:
        row = engine_row("selected")
        row["notes"]["samplingSeed"] = "19790615"
        row["summary"]["runEnvironment"] = {
            "loadAverage1Minute": 3.25, "lowPowerModeEnabled": False, "thermalState": "nominal",
            "uptimeSeconds": 100.0,
        }
        snapshot = self.root / "benchmark-source.json"
        snapshot.write_text(json.dumps({
            "schemaVersion": 1, "source": source_fixture(),
            "crashEvidence": {"scope": "macos", "digests": []},
            "host": {
                "osVersion": "27.0", "osBuild": "26A100", "xcodeVersion": "27.0",
                "xcodeBuild": "27A266a", "swiftVersion": "Apple Swift version 6.4",
            },
        }))
        record = self.publish_gate_fixture(row, seed=19790615, snapshot=snapshot)
        take = record["takes"][0]
        self.assertEqual(take["seed"], 19790615)
        self.assertEqual(take["metrics"]["loadAverage1M"], 3.25)
        self.assertEqual(take["metrics"]["lowPowerMode"], 0.0)
        self.assertEqual((record["hardware"]["osVersion"], record["hardware"]["osBuild"]), ("27.0", "26A100"))
        self.assertEqual(record["toolchain"]["xcodeBuild"], "27A266a")
        self.assertEqual(record["toolchain"]["optimization"], "-O")

        # A take whose engine receipt names another seed cannot be published as seeded.
        row["notes"]["samplingSeed"] = "42"
        with self.assertRaisesRegex(publisher.PublicationError, "sampled with seed 42"):
            self.publish_gate_fixture(row, seed=19790615, snapshot=snapshot)
        # Nor can a take without the engine's receipt: the engine writes one for
        # every seeded request, so its absence is broken telemetry.
        del row["notes"]["samplingSeed"]
        with self.assertRaisesRegex(publisher.PublicationError, "no samplingSeed receipt"):
            self.publish_gate_fixture(row, seed=19790615, snapshot=snapshot)
        # Or one whose receipt says the engine drew its own seed.
        row["notes"].update({"samplingSeed": "19790615", "samplingSeedSource": "generated"})
        with self.assertRaisesRegex(publisher.PublicationError, "generated seed"):
            self.publish_gate_fixture(row, seed=19790615, snapshot=snapshot)
        row["notes"]["samplingSeedSource"] = "requested"
        self.assertEqual(self.publish_gate_fixture(row, seed=19790615, snapshot=snapshot)["takes"][0]["seed"], 19790615)

    def publish_loaded_run(self, loads: list[float]) -> dict:
        """A multi-take engine run whose takes each recorded their own load."""
        diagnostics = self.root / f"diagnostics-{len(loads)}-{max(loads)}"
        output_dir = diagnostics / "outputs"
        diagnostics.mkdir()
        rows, result_takes, qualified = [], [], []
        for index, load in enumerate(loads):
            cell = f"custom/speed/medium/warm#{index}"
            row = engine_row(f"take-{index}", cell=cell)
            row["notes"]["benchTakeIndex"] = str(index + 1)
            row["summary"]["runEnvironment"] = {
                "loadAverage1Minute": load, "lowPowerModeEnabled": False, "thermalState": "nominal",
            }
            rows.append(row)
            self.make_wave(output_dir / f"take-{index}.wav")
            result_takes.append({
                "takeIndex": index + 1, "generationID": f"take-{index}", "cell": cell,
                "mode": "custom", "modelID": "pro_custom_speed", "variant": "speed",
                "length": "medium", "warmState": "warm", "wallSeconds": 1.0,
                "audioSeconds": 2.0, "firstChunkMS": 100, "outputFileName": f"take-{index}.wav",
            })
            qualified.append(SimpleNamespace(
                generation_id=f"take-{index}", metrics={}, sidecar_digest="f" * 64,
                status="qualified", warnings=(),
            ))
        results = diagnostics / "bench-results.json"
        results.write_text(json.dumps({
            "schemaVersion": 1, "runID": "run-one", "label": "fixture",
            "startedAt": "2026-07-12T12:00:00Z", "finishedAt": "2026-07-12T12:01:00Z",
            "telemetryMode": "verbose", "seed": None, "streaming": True,
            "executableSHA256": "a" * 64, "fixtureDigests": {}, "takes": result_takes,
        }))
        args = SimpleNamespace(
            results=results, run_id="run-one", diagnostics=diagnostics, output_dir=output_dir,
            platform="macos", artifact_dir=diagnostics, snapshot=self.root / "missing-source.json",
            label="fixture",
        )
        captured, write_patch = self.capture_manifest()
        with (
            mock.patch.object(publisher, "load_engine_rows", return_value=rows),
            mock.patch.object(publisher, "qualify_memory_rows", return_value=(qualified, {
                "memoryContractVersion": 1, "memoryQualified": True,
                "sampleSidecarCount": len(loads), "sampleSidecarsDigest": "e" * 64,
                "digestPayload": [{"generationID": row["generationID"], "digest": "f" * 64} for row in rows],
            })),
            mock.patch.object(publisher, "source_from_snapshot", return_value=source_fixture()),
            mock.patch.object(publisher, "crash_delta_from_snapshot", return_value={"passed": True, "count": 0}),
            self.hardware_patch(),
            write_patch,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            publisher.engine_command(args)
        return captured["manifest"]["historyRecord"]

    def test_a_take_above_the_per_take_load_limit_marks_the_record_exploratory(self) -> None:
        cores = publisher.canonical_hardware_profile("macos")["cpuCores"]
        limit = publisher.EXPLORATORY_TAKE_LOAD_PER_CORE * cores
        # Every take at or under the limit: the registry derives the classification.
        quiet = self.publish_loaded_run([2.0, limit, 3.5])
        self.assertNotIn("classification", quiet["run"])
        self.assertEqual([take["metrics"]["loadAverage1M"] for take in quiet["takes"]], [2.0, limit, 3.5])
        # One busy take in the middle of the run is enough; the first sample alone
        # (the run's hardware.loadAverage1M) would have missed it.
        busy = self.publish_loaded_run([2.0, limit + 0.5, 3.5])
        self.assertEqual(busy["run"]["classification"], "exploratory")
        self.assertEqual(
            publisher.takes_above_exploratory_load(busy["takes"], cores), [(2, limit + 0.5)],
        )
        # The limit classifies timing records only; a profile stays instrumented
        # and a memory-qualification record keeps its derived classification.
        rows = [engine_row("take-0")]
        self.assertEqual(
            publisher.engine_record_classification("instrument-profile", "macos", busy["takes"], rows),
            "instrumented",
        )
        self.assertIsNone(
            publisher.engine_record_classification("memory-qualification", "macos", busy["takes"], rows),
        )

    def test_engine_without_a_seed_or_host_snapshot_publishes_as_before(self) -> None:
        record = self.publish_gate_fixture(
            engine_row("selected"), seed=None, snapshot=self.root / "missing-source.json",
        )
        self.assertNotIn("seed", record["takes"][0])
        self.assertEqual(record["toolchain"], {"optimization": "-O"})
        self.assertNotIn("osBuild", record["hardware"])

    def test_gate_matrix_hash_reproduces_the_committed_unseeded_gate_record(self) -> None:
        cells = publisher.bench_matrix_cells(["custom"], ["speed"], ["medium"], 3)
        self.assertEqual(cells, [
            "custom/speed/medium/cold#0", "custom/speed/medium/warm#0",
            "custom/speed/medium/warm#1", "custom/speed/medium/warm#2",
        ])
        # inputs.matrixHash of mac-gate-bench-20260912-234613-c8f8a8c6, the last
        # unseeded gate record, and of the committed gate baseline.
        self.assertEqual(
            publisher.engine_matrix_hash(cells, "verbose", True, None),
            "2b93d8edbc798e8401ca1cad32c10d2968fc3d3bf596939d9e67afcad7d034a6",
        )
        self.assertNotEqual(
            publisher.engine_matrix_hash(cells, "verbose", True, 19790615),
            publisher.engine_matrix_hash(cells, "verbose", True, None),
        )
        self.assertEqual(
            publisher.bench_matrix_cells(["clone"], ["speed"], ["short", "long"], 1),
            ["clone/speed/short/warm#0", "clone/speed/long/warm#0"],
        )

    def test_expected_identity_predicts_the_gate_bench_identity(self) -> None:
        host = {
            "osVersion": "27.0", "osBuild": "26A100", "xcodeVersion": "27.0",
            "xcodeBuild": "27A266a", "swiftVersion": "Apple Swift version 6.4",
        }
        output = self.root / "expected-identity.json"
        args = SimpleNamespace(
            platform="macos", modes="custom", variants="speed", lengths="medium", warm=5,
            seed=19790615, telemetry_mode="verbose", no_stream=False, output=output,
        )
        with (
            self.hardware_patch(),
            mock.patch.object(publisher, "macos_host_identity", return_value=host),
            mock.patch.object(publisher, "history_git_state", return_value=source_fixture()),
        ):
            publisher.expected_identity_command(args)
        history = json.loads(output.read_text())["historyRecord"]
        self.assertEqual(history["hardware"], {"profileID": "mac-mini-m6-16gb", "osVersion": "27.0", "osBuild": "26A100"})
        self.assertEqual(history["toolchain"]["optimization"], "-O")
        self.assertEqual(history["run"]["matrixScope"], "focused")
        self.assertEqual(history["source"], {"commit": "a" * 40, "dirty": False})
        # The gate bench runs five warm takes: every warm#N cell is in the hash.
        cells = publisher.bench_matrix_cells(["custom"], ["speed"], ["medium"], 5)
        self.assertEqual(cells[-1], "custom/speed/medium/warm#4")
        self.assertEqual(
            history["inputs"]["matrixHash"],
            publisher.engine_matrix_hash(cells, "verbose", True, 19790615),
        )

    def test_macos_snapshot_records_the_run_time_host_identity(self) -> None:
        responses = {
            ("xcodebuild", "-version"): "Xcode 27.0\nBuild version 27A266a",
            ("swiftc", "--version"): "Apple Swift version 6.4 (swiftlang-6.4)\nTarget: arm64-apple-macosx27.0",
            ("sw_vers", "-productVersion"): "27.0",
            ("sw_vers", "-buildVersion"): "26A100",
        }
        history = SimpleNamespace(
            run_command=lambda arguments, **_kwargs: responses[tuple(arguments)],
            HistoryError=RuntimeError,
            git_state=source_fixture,
        )
        with mock.patch.object(publisher, "_load_history_module", return_value=history):
            identity = publisher.macos_host_identity()
            self.assertEqual(identity, {
                "osVersion": "27.0", "osBuild": "26A100", "xcodeVersion": "27.0",
                "xcodeBuild": "27A266a", "swiftVersion": "Apple Swift version 6.4 (swiftlang-6.4)",
            })
            macos = self.root / "macos" / "benchmark-source.json"
            with mock.patch.object(publisher, "crash_digests", return_value=[]):
                publisher.capture_snapshot(macos, "macos")
                publisher.capture_snapshot(self.root / "none.json", "none")
        self.assertEqual(publisher.snapshot_host_identity(macos), identity)
        self.assertEqual(publisher.snapshot_host_identity(self.root / "none.json"), {})
        self.assertEqual(publisher.snapshot_host_identity(self.root / "absent.json"), {})

    def test_engine_matrix_scope_is_canonical_only_for_the_full_speed_matrix(self) -> None:
        def take(cell: str, delivery: str | None = None) -> dict:
            return {"cell": cell, "delivery": delivery}

        full = []
        for mode in ("custom", "design", "clone"):
            if mode != "clone":
                full.append(take(f"{mode}/speed/medium/cold#0"))
            for length in ("short", "medium", "long"):
                for repetition in range(3):
                    full.append(take(f"{mode}/speed/{length}/warm#{repetition}"))
        self.assertEqual(len(full), 29)
        self.assertEqual(publisher.canonical_engine_matrix_scope(full), "canonical")
        self.assertEqual(publisher.canonical_engine_matrix_scope(full[:-1]), "focused")
        self.assertEqual(publisher.canonical_engine_matrix_scope([take("custom/speed/medium/warm#0")]), "focused")
        with_delivery = [dict(item) for item in full]
        with_delivery[3]["delivery"] = "happy.strong"
        self.assertEqual(publisher.canonical_engine_matrix_scope(with_delivery), "focused")

    def test_macos_cli_optimization_binds_the_executed_digest(self) -> None:
        binary = self.root / "vocello"
        self.write_cli_provenance(binary)
        recorded = json.loads(binary.with_name("vocello.provenance.json").read_text())["executableSHA256"]
        with mock.patch.object(publisher, "ROOT", self.root):
            self.assertEqual(
                publisher.validated_macos_cli_optimization(binary, executed_sha256=recorded), "-O",
            )
            with self.assertRaisesRegex(publisher.PublicationError, "executedSHA256"):
                publisher.validated_macos_cli_optimization(binary, executed_sha256="0" * 64)

    def test_ios_app_optimization_requires_a_receipt_for_the_installed_binary(self) -> None:
        executable = self.root / "Vocello.app" / "Vocello"
        executable.parent.mkdir()
        executable.write_bytes(b"ios app")
        receipt = self.root / "last-build.json"
        payload = {
            "schemaVersion": 1, "producer": "scripts/ios_device.sh build --optimized",
            "status": "passed", "platform": "ios", "optimization": "O",
            "executableRelativePath": str(executable.relative_to(self.root)),
            "executableSHA256": hashlib.sha256(b"ios app").hexdigest(),
        }
        receipt.write_text(json.dumps(payload))
        original = publisher.load_build_provenance
        rooted = lambda path, **kw: original(path, root=self.root, **kw)  # noqa: E731
        with mock.patch.object(publisher, "load_build_provenance", side_effect=rooted):
            self.assertEqual(publisher.validated_ios_app_optimization(receipt, executable), "-O")
            payload["producer"] = "scripts/ui_test.sh ios benchmark"
            receipt.write_text(json.dumps(payload))
            with self.assertRaisesRegex(publisher.PublicationError, "unproven"):
                publisher.validated_ios_app_optimization(receipt, executable)
            payload["producer"] = "scripts/ios_device.sh build"
            receipt.write_text(json.dumps(payload))
            other = self.root / "other"
            other.write_bytes(b"x")
            with self.assertRaisesRegex(publisher.PublicationError, "different executable"):
                publisher.validated_ios_app_optimization(receipt, other)

    def test_engine_take_refuses_a_row_without_a_measurable_request_span(self) -> None:
        row = engine_row("no-wall")
        row["derivedMetrics"] = {"audioSeconds": 2.0, "audioSecondsPerWallSecond": 1.5}
        take = {
            "generationID": "no-wall", "cell": row["notes"]["benchCell"], "mode": "custom",
            "modelID": "pro_custom_speed", "warmState": "warm", "wallSeconds": 1.0,
        }
        with self.assertRaisesRegex(publisher.PublicationError, "request wall time"):
            publisher.engine_take(1, take, row, None, run_id=row["notes"]["benchRunID"])
        row["backendMetrics"]["stages"] = [
            {"stage": "startup.request_validated", "tMS": 0},
            {"stage": "streamCompleted", "tMS": 1_600},
        ]
        recovered = publisher.engine_take(1, take, row, None, run_id=row["notes"]["benchRunID"])
        self.assertEqual(recovered["metrics"]["rtf"], 0.8)

    def test_ios_app_correlation_is_exact_completed_and_engine_memory_owned(self) -> None:
        generation_id = "ios-correlation-generation"
        run_id = "ios-correlation-run"
        cell = "custom/speed/device"
        engine = engine_row(generation_id, run_id=run_id, cell=cell)
        engine["schemaVersion"] = 8
        take = {
            "generationID": generation_id,
            "cell": cell,
            "mode": "custom",
        }
        app = ios_benchmark_app_row(
            generation_id, run_id=run_id, cell=cell
        )
        with mock.patch.object(publisher, "load_app_rows", return_value=[app]):
            selected = publisher.correlated_ios_app_rows(
                diagnostics=self.root,
                engine_rows=[engine],
                takes=[take],
                run_id=run_id,
            )
        self.assertEqual(selected, [app])

        cases = {
            "missing": [],
            "duplicate": [app, copy.deepcopy(app)],
            "wrong-take": [{
                **app,
                "notes": {**app["notes"], "benchTakeIndex": "2"},
            }],
            "failed": [{**app, "finishReason": "failed"}],
            "frontend-incomplete": [{**app, "frontendMetrics": {}}],
            "app-memory-owner": [{
                **app,
                "summary": {"physFootprintPeakMB": 1.0},
            }],
        }
        for name, rows in cases.items():
            with (
                self.subTest(name=name),
                mock.patch.object(publisher, "load_app_rows", return_value=rows),
                self.assertRaises(publisher.PublicationError),
            ):
                publisher.correlated_ios_app_rows(
                    diagnostics=self.root,
                    engine_rows=[engine],
                    takes=[take],
                    run_id=run_id,
                )

    def test_ios_headless_binds_app_row_into_layers_and_evidence_digest(self) -> None:
        run_id = "ios-headless-run"
        generation_id = "ios-headless-generation"
        cell = "custom/speed/device"
        sentinel_path = self.root / "device-diagnostics-done.json"
        sentinel_path.write_text(json.dumps({
            "schemaVersion": 2,
            "runID": run_id,
            "generationID": generation_id,
            "status": "ok",
            "mode": "custom",
            "variant": "speed",
            "startedAt": "2026-07-13T07:00:00Z",
            "finishedAt": "2026-07-13T07:00:05Z",
            "wallSeconds": 5.0,
            "durationSeconds": 2.0,
            "deviceModel": "iPhone",
            "systemName": "iOS",
            "systemVersion": "26.5",
        }), encoding="utf-8")
        engine = engine_row(generation_id, run_id=run_id, cell=cell)
        engine["schemaVersion"] = 8
        app = ios_benchmark_app_row(
            generation_id, run_id=run_id, cell=cell
        )
        qualified_memory, memory_run = qualified_memory_fixture([generation_id])
        args = SimpleNamespace(
            sentinel=sentinel_path,
            run_id=run_id,
            diagnostics=self.root / "diagnostics",
            artifact_dir=self.root,
            snapshot=self.root / "snapshot.json",
            crash_diagnostics=self.root / "crashes",
            label="ios-headless",
            defer_record=True,
        )
        captured, write_patch = self.capture_manifest()
        with (
            mock.patch.object(publisher, "load_engine_rows", return_value=[engine]),
            mock.patch.object(publisher, "load_app_rows", return_value=[app]),
            mock.patch.object(
                publisher,
                "qualify_memory_rows",
                return_value=(qualified_memory, memory_run),
            ),
            mock.patch.object(publisher, "source_from_snapshot", return_value=source_fixture()),
            mock.patch.object(
                publisher,
                "crash_delta_from_snapshot",
                return_value={"passed": True, "count": 0},
            ),
            self.hardware_patch(),
            write_patch,
        ):
            publisher.ios_engine_command(args)

        record = captured["manifest"]["historyRecord"]
        self.assertEqual(record["takes"][0]["layers"], ["engine", "app"])
        self.assertEqual(record["evidence"]["sampleSidecarCount"], 1)
        self.assertEqual(
            record["evidence"]["rawTelemetryDigest"],
            publisher.digest_bytes(publisher.canonical_bytes({
                "telemetry": [engine],
                "appTelemetry": [app],
                "sampleSidecars": memory_run["digestPayload"],
            })),
        )

    def test_engine_take_requires_exact_run_take_and_cell_provenance(self) -> None:
        take = {
            "generationID": "selected",
            "cell": "custom/speed/medium/warm#0",
            "mode": "custom",
            "modelID": "pro_custom_speed",
            "variant": "speed",
            "warmState": "warm",
            "length": "medium",
            "wallSeconds": 1.0,
            "audioSeconds": 2.0,
        }
        for missing_key in ("benchRunID", "benchTakeIndex", "benchCell"):
            row = engine_row("selected")
            del row["notes"][missing_key]
            with self.subTest(missing_key=missing_key), self.assertRaises(
                publisher.PublicationError
            ):
                publisher.engine_take(1, take, row, None, run_id="run-one")
        wrong = engine_row("selected")
        wrong["notes"]["benchRunID"] = "another-run"
        with self.assertRaisesRegex(publisher.PublicationError, "benchRunID"):
            publisher.engine_take(1, take, wrong, None, run_id="run-one")

    def test_engine_take_requires_observed_warm_state_agreement(self) -> None:
        take = {
            "generationID": "selected",
            "cell": "custom/speed/medium/warm#0",
            "mode": "custom",
            "modelID": "pro_custom_speed",
            "variant": "speed",
            "warmState": "warm",
            "length": "medium",
        }
        for observed in ("cold", "unknown", "", None):
            row = engine_row("selected")
            row["warmState"] = observed
            with self.subTest(observed=observed), self.assertRaisesRegex(
                publisher.PublicationError, "warm state"
            ):
                publisher.engine_take(1, take, row, None, run_id="run-one")
        for layer in ("backendMetrics", "requestReceipt"):
            row = engine_row("selected")
            row.setdefault(layer, {})["warmState"] = "cold"
            with self.subTest(layer=layer), self.assertRaisesRegex(
                publisher.PublicationError, "warm state"
            ):
                publisher.engine_take(1, take, row, None, run_id="run-one")
        row = engine_row("selected")
        del row["warmState"]
        with self.assertRaisesRegex(publisher.PublicationError, "warm state"):
            publisher.engine_take(1, take, row, None, run_id="run-one")

        # Older rows need not carry a request receipt, but never override the engine.
        row = engine_row("selected")
        built = publisher.engine_take(1, take, row, None, run_id="run-one")
        self.assertEqual(built["warmState"], "warm")
        row["requestReceipt"] = {"warmState": "warm"}
        self.assertEqual(
            publisher.engine_take(1, take, row, None, run_id="run-one")["warmState"],
            "warm",
        )
        # A retained-memory cell can truthfully be cold despite its neutral cell name.
        cold = dict(take, warmState="cold", cell="custom/speed/medium/retained#0")
        row["notes"]["benchCell"] = cold["cell"]
        row["warmState"] = row["backendMetrics"]["warmState"] = "cold"
        row["requestReceipt"]["warmState"] = "cold"
        self.assertEqual(
            publisher.engine_take(1, cold, row, None, run_id="run-one")["warmState"],
            "cold",
        )

    def test_quality_identity_folds_into_takes_and_selects_schema_v3(self) -> None:
        take = {
            "generationID": "selected",
            "cell": "custom/speed/medium/warm#0",
            "mode": "custom",
            "modelID": "pro_custom_speed",
            "variant": "speed",
            "warmState": "warm",
            "length": "medium",
            "wallSeconds": 1.0,
            "audioSeconds": 2.0,
        }
        row = engine_row("selected")
        row["notes"].update({
            "quality_registry_outcome": "warning",
            "quality_registry_required_gates":
                "codec_behavior,persisted_wav,streaming_continuity,terminal,token_cap",
            "quality_registry_issues": "quality_gate_warning.token_cap",
        })
        built = publisher.engine_take(1, take, row, None, run_id="run-one")
        self.assertEqual(built["qualityRegistryOutcome"], "warning")
        self.assertEqual(
            built["qualityRegistryRequiredGates"],
            ["codec_behavior", "persisted_wav", "streaming_continuity", "terminal", "token_cap"],
        )
        self.assertEqual(built["qualityRegistryIssues"], ["quality_gate_warning.token_cap"])

        # Pre-registry rows fold nothing and keep the record at schema v2.
        legacy = publisher.engine_take(1, take, engine_row("selected"), None, run_id="run-one")
        self.assertNotIn("qualityRegistryOutcome", legacy)
        self.assertEqual(publisher.history_record_schema_version([legacy]), 2)
        self.assertEqual(publisher.history_record_schema_version([built]), 3)
        with self.assertRaisesRegex(publisher.PublicationError, "mix quality-registry"):
            publisher.history_record_schema_version([built, legacy])

    def test_delivery_prosody_gate_verdict_folds_into_published_warnings(self) -> None:
        clean_delivery_gate = {
            "passed": True,
            "flags": [],
            "metrics": {"pitch_shift_semitones": 0.9, "arousal_score": 1.7},
        }

        def fixture(
            gate: object, delivery_gate: object = clean_delivery_gate
        ) -> tuple[list[dict], list[dict], list[dict]]:
            result_takes = [{
                "generationID": "delivery-current",
                "delivery": "happy.strong",
                "mode": "custom",
                "modelID": "pro_custom_speed",
            }]
            takes = [{
                "generationID": "delivery-current",
                "metrics": {},
                "warnings": [],
                "status": "passed",
            }]
            row: dict = {
                "runID": "run-current",
                "generationID": "delivery-current",
                "mode": "custom",
                "model": "pro_custom_speed",
                "delivery": "happy.strong",
                "deliveryMetrics": {"f0_std_hz": 31.5},
                "dF0Std": 6.4,
                "dRateCV": 0.03,
                "prosodyEffect": 1.2,
                "pairedProsodyEffect": 0.8,
            }
            if gate is not None:
                row["qualityGate"] = gate
            if delivery_gate is not None:
                row["deliveryGate"] = delivery_gate
            return result_takes, takes, [row]

        def fold(*arguments) -> None:
            publisher.fold_delivery_prosody(*arguments, run_id="run-current")

        clean = fixture({"passed": True, "flags": []})
        fold(*clean)
        self.assertEqual(clean[1][0]["warnings"], [])
        self.assertEqual(clean[1][0]["status"], "passed")
        self.assertEqual(clean[1][0]["metrics"]["f0StdHz"], 31.5)
        # Paired deltas and adherence measurements are banked for calibration.
        self.assertEqual(clean[1][0]["metrics"]["deliveryDF0StdHz"], 6.4)
        self.assertEqual(clean[1][0]["metrics"]["deliveryDRateCV"], 0.03)
        # The legacy key is published unchanged beside the paired effect.
        self.assertEqual(clean[1][0]["metrics"]["deliveryProsodyEffect"], 1.2)
        self.assertEqual(clean[1][0]["metrics"]["deliveryPairedProsodyEffect"], 0.8)
        self.assertEqual(clean[1][0]["metrics"]["deliveryPitchShiftSemitones"], 0.9)
        self.assertEqual(clean[1][0]["metrics"]["deliveryArousalScore"], 1.7)

        flagged = fixture({"passed": False, "flags": ["monotone", "long_pause"]})
        fold(*flagged)
        self.assertEqual(
            flagged[1][0]["warnings"],
            ["prosody_gate:long_pause", "prosody_gate:monotone"],
        )
        self.assertEqual(flagged[1][0]["status"], "passedWithWarnings")

        adherence_flagged = fixture(
            {"passed": True, "flags": []},
            {"passed": False, "flags": ["delivery_effect_weak_rate_delta_hz"], "metrics": {}},
        )
        fold(*adherence_flagged)
        self.assertEqual(
            adherence_flagged[1][0]["warnings"],
            ["delivery_gate:delivery_effect_weak_rate_delta_hz"],
        )
        self.assertEqual(adherence_flagged[1][0]["status"], "passedWithWarnings")

        for name, gate, delivery_gate in (
            ("missing", None, clean_delivery_gate),
            ("malformed", {"passed": "yes"}, clean_delivery_gate),
            ("incomplete", {"passed": False, "flags": ["metrics_incomplete"]}, clean_delivery_gate),
            ("missing_delivery_gate", {"passed": True, "flags": []}, None),
            ("malformed_delivery_gate", {"passed": True, "flags": []}, {"passed": 1}),
            (
                "uncovered_delivery_gate",
                {"passed": True, "flags": []},
                {"passed": False, "flags": ["expectation_missing"], "metrics": {}},
            ),
        ):
            with self.subTest(name=name), self.assertRaises(publisher.PublicationError):
                fold(*fixture(gate, delivery_gate))

    def test_delivery_prosody_joins_by_generation_and_refuses_a_stale_sidecar(self) -> None:
        """Audit #104: the sidecar row is the take's own (generation ID, run ID)."""
        gate = {"passed": True, "flags": []}

        def fixture(**row_overrides) -> tuple[list[dict], list[dict], list[dict]]:
            result_takes = [{"generationID": "delivery-current", "delivery": "happy.strong",
                             "mode": "custom", "modelID": "pro_custom_speed"}]
            takes = [{"generationID": "delivery-current", "metrics": {}, "warnings": [],
                      "status": "passed"}]
            row = {"runID": "run-current", "generationID": "delivery-current", "mode": "custom",
                   "model": "pro_custom_speed", "delivery": "happy.strong",
                   "deliveryMetrics": {"f0_std_hz": 31.5}, "qualityGate": gate,
                   "deliveryGate": {"passed": True, "flags": [], "metrics": {}}}
            row.update(row_overrides)
            return result_takes, takes, [row]

        publisher.fold_delivery_prosody(*fixture(), run_id="run-current")
        cases = {
            # An earlier run's sidecar with the same cell: the same (mode, model,
            # delivery) the old join accepted.
            "stale-run": {"runID": "run-earlier", "generationID": "delivery-earlier"},
            "same-generation-other-run": {"runID": "run-earlier"},
            "other-cell": {"delivery": "calm.normal"},
        }
        for name, overrides in cases.items():
            with self.subTest(name=name), self.assertRaises(publisher.PublicationError):
                publisher.fold_delivery_prosody(*fixture(**overrides), run_id="run-current")

    def test_forced_memory_profile_is_exploratory(self) -> None:
        self.assertFalse(publisher.uses_forced_memory_profile([engine_row("native")]))
        forced = engine_row("forced")
        forced["notes"]["deviceClassForced"] = "true"
        self.assertTrue(publisher.uses_forced_memory_profile([forced]))
        simulated = engine_row("simulated")
        simulated["notes"]["memoryProfile"] = "iphone15pro"
        simulated["notes"]["simulatedProcessLimitMB"] = "5000"
        self.assertTrue(publisher.uses_forced_memory_profile([simulated]))
        # A Mac emulating the 8 GB floor (audit #11 option b).
        emulated = engine_row("emulated")
        emulated["notes"]["simulatedPhysicalMemoryMB"] = "8192"
        self.assertTrue(publisher.uses_forced_memory_profile([emulated]))

    def test_runtime_policy_provenance_comes_from_the_rows_own_stamps(self) -> None:
        def stamped(generation_id: str, device_class: str | None, forced: str = "false") -> dict:
            row = engine_row(generation_id)
            if device_class is not None:
                row["notes"].update({"deviceClass": device_class, "deviceClassForced": forced})
            return row

        self.assertIsNone(publisher.runtime_policy_provenance([engine_row("legacy")]))
        self.assertEqual(
            publisher.runtime_policy_provenance([stamped("a", "floor_8gb_mac"), stamped("b", "floor_8gb_mac")]),
            {"deviceClass": "floor_8gb_mac", "deviceClassForced": False},
        )
        self.assertEqual(
            publisher.runtime_policy_provenance([stamped("a", "mid_16gb_mac", "true")]),
            {"deviceClass": "mid_16gb_mac", "deviceClassForced": True},
        )
        for rows in (
            [stamped("a", "floor_8gb_mac"), stamped("b", "mid_16gb_mac")],
            [stamped("a", "floor_8gb_mac"), stamped("b", None)],
        ):
            with self.subTest(rows=[row["notes"].get("deviceClass") for row in rows]):
                with self.assertRaises(publisher.PublicationError):
                    publisher.runtime_policy_provenance(rows)

    def test_an_emulated_floor_names_its_emulated_memory(self) -> None:
        """audit #11 option b: the M6 emulating an 8 GB Mac is a forced floor tier."""
        def emulated(generation_id: str, megabytes: str | None, forced: str = "true") -> dict:
            row = engine_row(generation_id)
            row["notes"].update({"deviceClass": "floor_8gb_mac", "deviceClassForced": forced})
            if megabytes is not None:
                row["notes"]["simulatedPhysicalMemoryMB"] = megabytes
            return row

        self.assertEqual(
            publisher.runtime_policy_provenance([emulated("a", "8192"), emulated("b", "8192")]),
            {"deviceClass": "floor_8gb_mac", "deviceClassForced": True, "simulatedPhysicalMemoryMB": 8192},
        )
        for name, rows in (
            ("mixed emulation", [emulated("a", "8192"), emulated("b", None)]),
            ("two machines", [emulated("a", "8192"), emulated("b", "4096")]),
            ("not forced", [emulated("a", "8192", forced="false")]),
            ("not a number", [emulated("a", "eight")]),
        ):
            with self.subTest(name=name), self.assertRaises(publisher.PublicationError):
                publisher.runtime_policy_provenance(rows)

    @staticmethod
    def sysctl_run(values: dict[tuple[str, ...], str]):
        def run(command, **_kwargs):
            return SimpleNamespace(returncode=0, stdout=values[tuple(command)], stderr="")

        return run

    def test_mac_hardware_profile_requires_exact_model_and_ram(self) -> None:
        # Reads the real registry: the Mac mini M6 16 GB is the canonical macOS host.
        values = {
            ("sysctl", "-n", "hw.model"): "Mac18,5\n",
            ("sysctl", "-n", "hw.memsize"): "17179869184\n",
        }
        with mock.patch.object(publisher.subprocess, "run", side_effect=self.sysctl_run(values)):
            self.assertEqual(
                publisher.verify_canonical_hardware("macos"),
                {"profileID": "mac-mini-m6-16gb"},
            )
        for model, memory in (
            ("Mac14,3", "8589934592"),  # the retired canonical Mac mini M2 8 GB
            ("Mac18,5", "8589934592"),  # right model, wrong memory
        ):
            values = {
                ("sysctl", "-n", "hw.model"): f"{model}\n",
                ("sysctl", "-n", "hw.memsize"): f"{memory}\n",
            }
            with (
                self.subTest(model=model, memory=memory),
                mock.patch.object(publisher.subprocess, "run", side_effect=self.sysctl_run(values)),
                self.assertRaisesRegex(publisher.PublicationError, "does not match"),
            ):
                publisher.verify_canonical_hardware("macos")

    def test_registry_has_one_canonical_profile_per_platform(self) -> None:
        self.assertEqual(publisher.canonical_hardware_profile("macos")["id"], "mac-mini-m6-16gb")
        self.assertEqual(publisher.canonical_hardware_profile("ios")["id"], "iphone-17-pro")

    def test_verify_hardware_command_prints_the_canonical_profile(self) -> None:
        canonical = {
            ("sysctl", "-n", "hw.model"): "Mac18,5\n",
            ("sysctl", "-n", "hw.memsize"): "17179869184\n",
        }
        with (
            mock.patch.object(publisher.subprocess, "run", side_effect=self.sysctl_run(canonical)),
            mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            self.assertEqual(publisher.main(["verify-hardware", "--platform", "macos"]), 0)
        self.assertEqual(stdout.getvalue().strip(), "mac-mini-m6-16gb")

        retired = {
            ("sysctl", "-n", "hw.model"): "Mac14,3\n",
            ("sysctl", "-n", "hw.memsize"): "8589934592\n",
        }
        with (
            mock.patch.object(publisher.subprocess, "run", side_effect=self.sysctl_run(retired)),
            mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
            mock.patch("sys.stderr", new_callable=io.StringIO) as stderr,
        ):
            self.assertEqual(publisher.main(["verify-hardware", "--platform", "macos"]), 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("does not match the canonical benchmark profile", stderr.getvalue())
        self.assertNotIn("repair:", stderr.getvalue())

        with mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            self.assertEqual(publisher.main(["verify-hardware", "--platform", "ios"]), 1)
        self.assertIn("--diagnostics and --run-id", stderr.getvalue())

    def test_ui_test_macos_benchmark_refuses_a_non_canonical_host_before_building(self) -> None:
        text = (SCRIPT.parent / "ui_test.sh").read_text(encoding="utf-8")
        gate = text.index("verify-hardware --platform macos")
        self.assertIn("non-canonical host; benchmark records are not publishable", text[gate:gate + 300])
        self.assertLess(gate, text.index("command -v xcodebuild"))

    def test_ios_hardware_profile_binds_sentinel_to_one_exact_coredevice(self) -> None:
        product_type = "iPhone18,1"

        def run(command, **_kwargs):
            output = Path(command[command.index("--json-output") + 1])
            output.write_text(json.dumps({"result": {"devices": [{
                "hardwareProperties": {"platform": "iOS", "productType": product_type},
                "deviceProperties": {"osVersionNumber": "26.5"},
                "connectionProperties": {"pairingState": "paired"},
            }]}}), encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        evidence = [{"deviceModel": "iPhone", "systemName": "iOS", "systemVersion": "26.5"}]
        with mock.patch.object(publisher.subprocess, "run", side_effect=run):
            self.assertEqual(
                publisher.verify_canonical_hardware("ios", ios_evidence=evidence),
                {"profileID": "iphone-17-pro"},
            )
        product_type = "iPhone17,1"
        with (
            mock.patch.object(publisher.subprocess, "run", side_effect=run),
            self.assertRaisesRegex(publisher.PublicationError, "does not match"),
        ):
            publisher.verify_canonical_hardware("ios", ios_evidence=evidence)

    def test_ios_headless_hardware_evidence_uses_exact_run_manifest(self) -> None:
        run_id = "ios-memory-run"
        run_dir = self.root / run_id
        run_dir.mkdir()
        (run_dir / "manifest.json").write_text(json.dumps({
            "runID": run_id,
            "deviceModel": "iPhone",
            "systemName": "iOS",
            "systemVersion": "26.5",
            "appSupportDirectory": "/private/sensitive/path",
        }), encoding="utf-8")

        self.assertEqual(
            publisher.ios_run_hardware_evidence(self.root, run_id),
            [{
                "deviceModel": "iPhone",
                "systemName": "iOS",
                "systemVersion": "26.5",
            }],
        )
        payload = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        payload["runID"] = "wrong-run"
        (run_dir / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(publisher.PublicationError, "does not match"):
            publisher.ios_run_hardware_evidence(self.root, run_id)

    def test_failed_qc_never_reaches_recording(self) -> None:
        row = engine_row("bad", qc="fail")
        with self.assertRaises(publisher.PublicationError):
            publisher.successful_row(row)

    def test_delayed_repair_records_frozen_manifest_directly(self) -> None:
        completed = SimpleNamespace(returncode=1, stderr="registry rejected", stdout="")
        with mock.patch.object(publisher.subprocess, "run", return_value=completed):
            with self.assertRaisesRegex(
                publisher.PublicationError,
                r"scripts/benchmark_history\.py record --artifact-dir",
            ):
                publisher.write_and_record(self.root, {"schemaVersion": 1})
        self.assertEqual(
            json.loads((self.root / "benchmark-evidence.json").read_text()),
            {"schemaVersion": 1},
        )

    def test_deferred_record_writes_evidence_without_touching_registry(self) -> None:
        with mock.patch.object(publisher.subprocess, "run") as run:
            path = publisher.write_and_record(
                self.root, {"schemaVersion": 1}, defer_record=True
            )
        self.assertEqual(path, self.root / "benchmark-evidence.json")
        self.assertEqual(
            json.loads(path.read_text(encoding="utf-8")),
            {"schemaVersion": 1},
        )
        run.assert_not_called()

    def test_v7_sampler_resource_environment_and_dual_qc_are_distilled(self) -> None:
        row = engine_row("v7", qc="pass")
        row["summary"].update({
            "headroomMinMB": 512.0,
            "targetIntervalNS": 500_000_000,
            "effectiveIntervalNS": 510_000_000,
            "maximumLatenessNS": 12_000_000,
            "maximumDriftNS": 9_000_000,
            "boundarySampleCount": 4,
            "captureFailureCount": 1,
            "processResourceUsage": {
                "userCPUTimeMS": 2_500.0,
                "systemCPUTimeMS": 500.0,
                "minorPageFaults": 10,
                "majorPageFaults": 2,
                "voluntaryContextSwitches": 3,
                "involuntaryContextSwitches": 4,
                "blockInputOperations": 5,
                "blockOutputOperations": 6,
            },
            "stageMarks": [
                {"stage": "memory_trim", "metadata": {"level": "softTrim"}},
                {"stage": "memory_trim", "metadata": {"level": "hardTrim"}},
            ],
            "runEnvironment": {
                "loadAverage1Minute": 1.25,
                "freeStorageBytes": 123_456,
                "uptimeSeconds": 99.0,
                "lowPowerModeEnabled": True,
                "thermalState": "fair",
            },
        })
        row["audioQC"].update({
            "instabilityVerdict": "pass",
            "writtenOutputVerdict": "warn",
            "dcOffset": 0.06,
            "flags": ["dc_offset"],
        })
        metrics = publisher.row_metrics(row)
        self.assertEqual(metrics["samplerTargetIntervalMS"], 500.0)
        self.assertEqual(metrics["samplerEffectiveMedianIntervalMS"], 510.0)
        self.assertEqual(metrics["samplerMaximumLatenessMS"], 12.0)
        self.assertEqual(metrics["samplerMaximumDriftMS"], 9.0)
        self.assertEqual(metrics["cpuUserSeconds"], 2.5)
        self.assertEqual(metrics["pageFaults"], 12.0)
        self.assertEqual(metrics["contextSwitches"], 7.0)
        self.assertEqual(metrics["generatedTokens"], 42.0)
        self.assertEqual(metrics["memoryTrimCount"], 2.0)
        self.assertEqual(metrics["maximumTrimLevel"], 2.0)
        self.assertEqual(metrics["blockIOOperations"], 11.0)
        self.assertEqual(publisher.hardware_context([row]), {
            "loadAverage1M": 1.25,
            "freeStorageBytes": 123_456,
            "uptimeSeconds": 99.0,
            "lowPowerMode": True,
            "thermalState": "fair",
        })
        qc = publisher.qc_record(row)
        self.assertEqual(qc["verdict"], "warn")
        self.assertEqual(qc["metrics"]["dcOffset"], 0.06)
        self.assertIn("written-output-warn", qc["warningCodes"])

    def test_v7_runtime_and_fixture_identity_is_typed_and_cross_checked(self) -> None:
        row = engine_row("design-id")
        row["mode"] = "design"
        row["modelID"] = "pro_design_speed"
        row["modelRuntimeIdentity"] = {
            "resolvedModelID": "pro_design_speed",
            "modelRepository": "PowerBeef02/Qwen3-TTS-12Hz-1.7B-VoiceDesign-4bit",
            "huggingFaceRevision": "62f2646e55499e3d5bc73abec274342718220ffe",
            "artifactVersion": "2026.09.14.1",
            "quantization": "4-bit",
            "integrityManifestDigest": "c" * 64,
            "runtimeProfileSignature": "pro_design_speed:profile-v2",
            "fixtureDigest": "d" * 64,
        }
        identity = publisher.runtime_identity(
            row, mode="design", model_id="pro_design_speed"
        )
        self.assertEqual(identity["runtimeProfileSignature"], "pro_design_speed:profile-v2")
        self.assertEqual(identity["fixtureDigest"], "d" * 64)
        self.assertEqual(identity["modelIntegrityDigest"], "c" * 64)
        takes = [{"mode": "design", "fixtureDigest": identity["fixtureDigest"]}]
        publisher.require_fixture_cross_check(
            takes, {"design": "d" * 64}, source="fixture"
        )
        with self.assertRaises(publisher.PublicationError):
            publisher.require_fixture_cross_check(
                takes, {"design": "e" * 64}, source="fixture"
            )
        row["modelRuntimeIdentity"]["resolvedModelID"] = "wrong-model"
        with self.assertRaises(publisher.PublicationError):
            publisher.runtime_identity(row, mode="design", model_id="pro_design_speed")
        row["modelRuntimeIdentity"]["resolvedModelID"] = "pro_design_speed"
        del row["modelRuntimeIdentity"]["runtimeProfileSignature"]
        with self.assertRaises(publisher.PublicationError):
            publisher.runtime_identity(row, mode="design", model_id="pro_design_speed")

    def test_crash_delta_uses_before_after_content_hashes(self) -> None:
        before = self.root / "before"
        after = self.root / "after"
        (before / "crashes").mkdir(parents=True)
        (after / "crashes").mkdir(parents=True)
        (before / "crashes" / "old.ips").write_bytes(b"old")
        (after / "crashes" / "renamed.ips").write_bytes(b"old")
        snapshot = self.root / "benchmark-source.json"
        publisher.capture_snapshot(snapshot, "ios", before)
        self.assertEqual(
            publisher.crash_delta_from_snapshot(snapshot, expected_scope="ios", diagnostics=after),
            {"passed": True, "count": 0},
        )
        (after / "crashes" / "new.ips").write_bytes(b"new")
        with self.assertRaises(publisher.PublicationError):
            publisher.crash_delta_from_snapshot(snapshot, expected_scope="ios", diagnostics=after)

    def test_language_hint_only_is_partial_and_ordered(self) -> None:
        matrix = self.root / "matrix.json"
        corpus = self.root / "corpus.json"
        matrix.write_text(json.dumps({"cells": [
            {"id": "fr", "quick": True, "expectedHint": "french"},
            {"id": "en", "quick": True, "expectedHint": "english"},
        ]}))
        reference_script = "un deux trois quatre cinq six sept huit"
        corpus.write_text(json.dumps({"languages": [{
            "id": "french", "script": reference_script,
            "customSpeakerID": "aiden",
            "designInstruction": "A warm, friendly narrator with a calm, measured pace.",
        }]}))
        fr = engine_row("fr-id", run_id="lang-run", cell="fr")
        en = engine_row("en-id", run_id="lang-run", cell="en")
        fr["notes"]["languageHint"] = "french"
        en["notes"]["languageHint"] = "english"
        args = SimpleNamespace(
            matrix=matrix, corpus=corpus, subset="quick", diagnostics=self.root,
            run_id="lang-run", output_gate="not-performed", platform="macos",
            started_at="2026-07-12T12:00:00Z", finished_at="2026-07-12T12:01:00Z",
            label="fixture", artifact_dir=self.root, snapshot=self.root / "snapshot.json",
        )
        captured, write_patch = self.capture_manifest()
        with (
            mock.patch.object(publisher, "load_engine_rows", return_value=[en, fr]),
            mock.patch.object(
                publisher, "qualify_memory_rows",
                return_value=qualified_memory_fixture(["fr-id", "en-id"]),
            ),
            mock.patch.object(publisher, "source_from_snapshot", return_value=source_fixture()),
            mock.patch.object(publisher, "crash_delta_from_snapshot", return_value={"passed": True, "count": 0}),
            self.hardware_patch(),
            write_patch,
        ):
            publisher.language_command(args)
        record = captured["manifest"]["historyRecord"]
        self.assertEqual(record["run"]["matrixScope"], "partial")
        self.assertEqual([take["cell"] for take in record["takes"]], ["fr", "en"])
        self.assertTrue(all(take["layerCompleteness"] == "complete" for take in record["takes"]))
        self.assertTrue(all(take["output"]["readableWAV"] for take in record["takes"]))
        self.assertTrue(all(take["audioQC"]["verdict"] == "pass" for take in record["takes"]))

    def test_language_v2_requires_v8_and_binds_the_exact_memory_sidecar(self) -> None:
        diagnostics = self.root / "language-memory-diagnostics"
        matrix = self.root / "memory-matrix.json"
        corpus = self.root / "memory-corpus.json"
        matrix.write_text(json.dumps({"cells": [
            {"id": "fr", "quick": True, "expectedHint": "french"},
        ]}))
        corpus.write_text(json.dumps({"languages": [
            {"id": "french", "script": "un deux trois"},
        ]}))
        row = engine_row("fr-memory", run_id="lang-memory", cell="fr")
        row["notes"]["languageHint"] = "french"
        upgrade_language_memory_row(row, diagnostics, ios=False)
        # A historical sidecar in the same tree must not enter this run's exact
        # selection or aggregate digest.
        unrelated = diagnostics / "engine" / "samples-unrelated.jsonl"
        unrelated.write_text("{}\n", encoding="utf-8")
        args = SimpleNamespace(
            matrix=matrix, corpus=corpus, subset="quick", diagnostics=diagnostics,
            run_id="lang-memory", output_gate="not-performed", platform="macos",
            started_at="2026-07-12T12:00:00Z", finished_at="2026-07-12T12:01:00Z",
            label="fixture", artifact_dir=diagnostics,
            snapshot=self.root / "snapshot.json",
        )
        captured, write_patch = self.capture_manifest()
        common = (
            mock.patch.object(publisher, "load_engine_rows", return_value=[row]),
            mock.patch.object(publisher, "source_from_snapshot", return_value=source_fixture()),
            mock.patch.object(
                publisher, "crash_delta_from_snapshot", return_value={"passed": True, "count": 0}
            ),
            self.hardware_patch(),
            write_patch,
        )
        with common[0], common[1], common[2], common[3], common[4]:
            publisher.language_command(args)
        record = captured["manifest"]["historyRecord"]
        self.assertEqual(record["schemaVersion"], 2)
        self.assertEqual(record["evidence"]["telemetrySchemaVersion"], 8)
        self.assertTrue(record["evidence"]["memoryQualified"])
        self.assertEqual(record["evidence"]["sampleSidecarCount"], 1)
        self.assertRegex(record["evidence"]["sampleSidecarsDigest"], r"^[0-9a-f]{64}$")
        self.assertEqual(record["takes"][0]["memoryStatus"], "qualified")
        self.assertRegex(record["takes"][0]["sampleSidecarDigest"], r"^[0-9a-f]{64}$")
        self.assertIn("peakPhysicalFootprintMB", record["takes"][0]["metrics"])

        row["schemaVersion"] = 7
        with (
            mock.patch.object(publisher, "load_engine_rows", return_value=[row]),
            self.assertRaisesRegex(publisher.PublicationError, "schema v8"),
        ):
            publisher.language_command(args)

        row["schemaVersion"] = 8
        (diagnostics / "engine" / "samples-fr-memory.jsonl").unlink()
        with (
            mock.patch.object(publisher, "load_engine_rows", return_value=[row]),
            self.assertRaisesRegex(publisher.PublicationError, "sample sidecar"),
        ):
            publisher.language_command(args)

    def test_ios_language_binds_sanitized_asr_evidence_and_per_take_scores(self) -> None:
        matrix = self.root / "matrix.json"
        corpus = self.root / "corpus.json"
        matrix.write_text(json.dumps({"cells": [
            {
                "id": "fr", "quick": True, "expectedHint": "french",
                "mode": "custom", "variant": "speed", "scriptLang": "french",
            },
        ]}))
        reference_script = "un deux trois quatre cinq six sept huit"
        corpus.write_text(json.dumps({"languages": [{
            "id": "french", "script": reference_script,
            "customSpeakerID": "aiden",
            "designInstruction": "A warm, friendly narrator with a calm, measured pace.",
        }]}))
        plan_path = self.root / "language-run-plan.json"
        plan = language_plan(matrix=matrix, corpus=corpus)
        plan_path.write_text(json.dumps(plan))
        row = engine_row("fr-generation", run_id="lang-ios", cell="fr")
        planned_seed = plan["takes"][0]["seed"]
        row["notes"]["samplingSeed"] = str(planned_seed)
        row["notes"]["languageHint"] = "french"
        sentinel_dir = self.root / "diagnostics" / "lang-ios--fr"
        sentinel_dir.mkdir(parents=True)
        output_path = sentinel_dir / "output.wav"
        self.make_wave(output_path)
        sentinel = language_sentinel(output_path=output_path, seed=planned_seed)
        (sentinel_dir / "device-diagnostics-done.json").write_text(json.dumps(sentinel))
        args = SimpleNamespace(
            matrix=matrix, corpus=corpus, subset="quick", diagnostics=self.root / "diagnostics",
            plan=plan_path,
            crash_diagnostics=None, run_id="lang-ios", output_gate="pass", platform="ios",
            started_at="2026-07-12T12:00:00Z", finished_at="2026-07-12T12:01:00Z",
            label="fixture", artifact_dir=self.root, snapshot=self.root / "snapshot.json",
            design_fixture_digest=None,
        )
        captured, write_patch = self.capture_manifest()
        with (
            mock.patch.object(publisher, "load_engine_rows", return_value=[row]),
            mock.patch.object(publisher, "load_app_rows", return_value=[app_row("fr-generation")]),
            mock.patch.object(
                publisher, "qualify_memory_rows",
                return_value=qualified_memory_fixture(["fr-generation"]),
            ),
            mock.patch.object(publisher, "source_from_snapshot", return_value=source_fixture()),
            mock.patch.object(publisher, "crash_delta_from_snapshot", return_value={"passed": True, "count": 0}),
            self.hardware_patch(),
            write_patch,
        ):
            publisher.language_command(args)
        manifest = captured["manifest"]
        take_metrics = manifest["historyRecord"]["takes"][0]["metrics"]
        self.assertEqual(take_metrics["wordErrorRate"], 0.125)
        self.assertEqual(take_metrics["characterErrorRate"], 0.125)
        self.assertEqual(take_metrics["languageMatchScore"], 0.875)
        self.assertEqual(take_metrics["outputLanguagePass"], 1.0)
        self.assertEqual(take_metrics["outputAccuracyPass"], 1.0)
        self.assertEqual(take_metrics["recognitionPassCount"], 3.0)
        self.assertEqual(take_metrics["substitutions"], 1.0)
        self.assertEqual(take_metrics["accuracyThreshold"], 0.15)
        self.assertEqual(take_metrics["primaryAccuracyScore"], 0.125)
        self.assertEqual(manifest["historyRecord"]["takes"][0]["seed"], planned_seed)
        self.assertEqual(
            manifest["historyRecord"]["takes"][0]["layers"], ["engine", "app"]
        )
        self.assertEqual(
            manifest["historyRecord"]["takes"][0]["accuracyMetric"], "wordErrorRate"
        )
        self.assertEqual(
            manifest["historyRecord"]["takes"][0]["output"]["fileDigest"],
            publisher.digest_file(output_path),
        )
        self.assertRegex(
            manifest["historyRecord"]["inputs"]["analysisProfileHash"], r"^[0-9a-f]{64}$"
        )
        expected_analysis_profile = {
            "contract": "autonomous-language-output-v3",
            "seedPolicy": plan["seedPolicy"],
            "takes": [{
                "cell": "fr",
                "seed": planned_seed,
                "samplingVariation": "expressive",
                "promptEquivalenceGroup": None,
                "outputVerificationRequired": True,
                "customSpeakerID": "aiden",
                "designInstructionDigest": None,
                "expectedLanguage": "french",
                "selectedLocaleIdentifier": "fr-CA",
                "accuracyMetricVersion": "normalized-edit-rate-v1",
                "accuracyMetric": "wordErrorRate",
                "accuracyThreshold": 0.15,
                "outputVerifierSchemaVersion": 3,
                "outputVerifierAlgorithm": "language-output-verifier-v3",
                "recognitionSchemaVersion": 2,
                "recognitionAlgorithm": "apple-speech-file-consensus-v2",
                "requiredPassCount": 3,
            }],
        }
        self.assertEqual(
            manifest["historyRecord"]["inputs"]["analysisProfileHash"],
            publisher.digest_bytes(publisher.canonical_bytes(expected_analysis_profile)),
        )
        language_verification = manifest["historyRecord"]["evidence"]["languageVerification"]
        self.assertEqual({
            key: language_verification[key] for key in (
                "outputSchemaVersion", "outputAlgorithm", "recognitionSchemaVersion",
                "recognitionAlgorithm", "accuracyMetricVersion", "requiredPassCount", "families",
            )
        }, {
            "outputSchemaVersion": 3,
            "outputAlgorithm": "language-output-verifier-v3",
            "recognitionSchemaVersion": 2,
            "recognitionAlgorithm": "apple-speech-file-consensus-v2",
            "accuracyMetricVersion": "normalized-edit-rate-v1",
            "requiredPassCount": 3,
            "families": ["apple-speech"],
        })
        # Run-level counts live here once, never as constants on every take.
        self.assertEqual(language_verification["hintCellsPassed"], language_verification["hintCellsExpected"])
        self.assertEqual(language_verification["outputCellsPassed"], language_verification["outputCellsExpected"])
        self.assertEqual(language_verification["negativeControlsConfirmed"], 0)
        for take in manifest["historyRecord"]["takes"]:
            self.assertNotIn("hintCellsPassed", take["metrics"])
            self.assertNotIn("outputCellsPassed", take["metrics"])
        sanitized = publisher.sanitized_asr_evidence(
            cell={"id": "fr", "expectedHint": "french"},
            planned_take=plan["takes"][0],
            sentinel=sentinel,
            engine_row=row,
            parent_run_id="lang-ios",
            reference_script=reference_script,
        )
        self.assertNotIn("transcript", sanitized)
        self.assertNotIn("runID", sanitized)
        # Audit #84: the deletion run is recomputed from the transcript, and an
        # app-reported value must agree with it (one substitution: run 0).
        self.assertEqual(sanitized["longestDeletionRun"], 0)
        self.assertEqual(take_metrics["longestDeletionRun"], 0.0)
        parity = copy.deepcopy(sentinel)
        parity["outputVerification"]["longestDeletionRun"] = 0
        publisher.sanitized_asr_evidence(
            cell={"id": "fr", "expectedHint": "french"}, planned_take=plan["takes"][0],
            sentinel=parity, engine_row=row, parent_run_id="lang-ios",
            reference_script=reference_script,
        )
        parity["outputVerification"]["longestDeletionRun"] = 2
        with self.assertRaises(publisher.PublicationError):
            publisher.sanitized_asr_evidence(
                cell={"id": "fr", "expectedHint": "french"}, planned_take=plan["takes"][0],
                sentinel=parity, engine_row=row, parent_run_id="lang-ios",
                reference_script=reference_script,
            )
        mismatched = dict(sentinel)
        mismatched["generationID"] = "another-generation"
        with self.assertRaisesRegex(publisher.PublicationError, "another generation"):
            publisher.sanitized_asr_evidence(
                cell={"id": "fr", "expectedHint": "french"},
                planned_take=plan["takes"][0],
                sentinel=mismatched,
                engine_row=row,
                parent_run_id="lang-ios",
                reference_script=reference_script,
            )

        for name, app_rows, message in (
            ("missing", [], "0 app rows"),
            ("duplicate", [app_row("fr-generation"), app_row("fr-generation")], "2 app rows"),
            (
                "wrong-mode",
                [{**app_row("fr-generation"), "mode": "design"}],
                "app telemetry identity",
            ),
            (
                "missing-frontend-completion",
                [{**app_row("fr-generation"), "frontendMetrics": {}}],
                "app telemetry identity",
            ),
        ):
            with (
                self.subTest(name=name),
                mock.patch.object(publisher, "load_engine_rows", return_value=[row]),
                mock.patch.object(publisher, "load_app_rows", return_value=app_rows),
                self.assertRaisesRegex(publisher.PublicationError, message),
            ):
                publisher.language_command(args)

        tampered_sentinel = copy.deepcopy(sentinel)
        tampered_sentinel["customSpeakerID"] = "vivian"
        (sentinel_dir / "device-diagnostics-done.json").write_text(
            json.dumps(tampered_sentinel)
        )
        with (
            mock.patch.object(publisher, "load_engine_rows", return_value=[row]),
            mock.patch.object(
                publisher, "load_app_rows", return_value=[app_row("fr-generation")]
            ),
            self.assertRaisesRegex(publisher.PublicationError, "Custom speaker"),
        ):
            publisher.language_command(args)
        (sentinel_dir / "device-diagnostics-done.json").write_text(json.dumps(sentinel))

        self.assertNotIn(
            successful_asr_verification()["transcript"],
            json.dumps(manifest, sort_keys=True),
        )

    def _publish_two_language_cells(self, *, english_provenance: dict | None = None,
                                    english_expected_outcome: str = "pass",
                                    english_transcript: str | None = None) -> dict:
        matrix = self.root / "matrix.json"
        corpus = self.root / "corpus.json"
        matrix.write_text(json.dumps({"cells": [
            {"id": "fr", "quick": True, "expectedHint": "french", "scriptLang": "french"},
            {"id": "en", "quick": True, "expectedHint": "english", "scriptLang": "english",
             "expectedOutcome": english_expected_outcome},
        ]}))
        french = "un deux trois quatre cinq six sept huit"
        english = "one two three four five six seven eight"
        corpus.write_text(json.dumps({"languages": [
            {"id": "french", "script": french}, {"id": "english", "script": english},
        ]}))
        rows = []
        cells = {}
        for cell_id, digest, language, script, provenance in (
            ("fr", "a" * 64, "french", french, None),
            ("en", "b" * 64, "english", english, english_provenance),
        ):
            row = engine_row(f"{cell_id}-id", run_id="lang-run", cell=cell_id)
            row["notes"]["languageHint"] = language
            row["notes"]["samplingWAVDigest"] = digest
            rows.append(row)
            cells[cell_id] = {
                "generationID": f"{cell_id}-id", "audioSHA256": digest, "expectedLanguage": language,
                "expectedOutcome": "pass",
                "recognitions": [independent_recognition(
                    audio_sha256=digest, script=script, language=language, provenance=provenance,
                    transcript=english_transcript if cell_id == "en" else None,
                )],
            }
        recognitions = independent_evidence(
            self.root / "independent-asr.json", run_id="lang-run", platform="macos", cells=cells,
        )
        args = SimpleNamespace(
            matrix=matrix, corpus=corpus, subset="quick", diagnostics=self.root,
            run_id="lang-run", output_gate="independent", recognitions=recognitions, platform="macos",
            started_at="2026-09-12T12:00:00Z", finished_at="2026-09-12T12:01:00Z",
            label="fixture", artifact_dir=self.root, snapshot=self.root / "snapshot.json",
        )
        captured, write_patch = self.capture_manifest()
        patches = (
            mock.patch.object(publisher, "load_engine_rows", return_value=rows),
            mock.patch.object(publisher, "qualify_memory_rows",
                              return_value=qualified_memory_fixture(["fr-id", "en-id"])),
            mock.patch.object(publisher, "source_from_snapshot", return_value=source_fixture()),
            mock.patch.object(publisher, "crash_delta_from_snapshot", return_value={"passed": True, "count": 0}),
            self.hardware_patch(),
            write_patch,
        )
        with contextlib.ExitStack() as stack:
            for item in patches:
                stack.enter_context(item)
            publisher.language_command(args)
        return captured["manifest"]["historyRecord"]

    def test_cells_of_different_languages_share_one_recognizer_identity(self) -> None:
        # The producer locks the decode language per row, so configSHA256 differs
        # between a French and an English cell while the runtime and model do not.
        record = self._publish_two_language_cells(english_provenance={
            "runtimeSHA256": "1" * 64, "modelIdentitySHA256": "2" * 64, "configSHA256": "4" * 64,
        })
        verification = record["evidence"]["languageVerification"]
        self.assertEqual(verification["independentModelIdentitySHA256"], "2" * 64)
        self.assertEqual(verification["outputCellsPassed"], 2)

    def test_a_negative_control_take_is_stamped_with_its_expected_failure(self) -> None:
        record = self._publish_two_language_cells(
            english_expected_outcome="fail",
            english_transcript="nine ten eleven twelve thirteen fourteen fifteen sixteen",
        )
        verification = record["evidence"]["languageVerification"]
        self.assertEqual(verification["negativeControlsConfirmed"], 1)
        self.assertEqual(verification["outputCellsPassed"], 2)
        by_cell = {take["cell"]: take for take in record["takes"]}
        self.assertEqual(by_cell["en"]["expectedOutcome"], "fail")
        self.assertNotIn("expectedOutcome", by_cell["fr"])
        self.assertEqual(by_cell["en"]["metrics"]["independentAccuracyPass"], 0.0)

    def test_two_recognizer_models_in_one_run_refuse_publication(self) -> None:
        with self.assertRaises(publisher.PublicationError) as raised:
            self._publish_two_language_cells(english_provenance={
                "runtimeSHA256": "1" * 64, "modelIdentitySHA256": "9" * 64, "configSHA256": "3" * 64,
            })
        self.assertIn("more than one recognizer identity", str(raised.exception))

    def test_macos_language_publishes_a_single_whisper_witness_as_focused(self) -> None:
        matrix = self.root / "matrix.json"
        corpus = self.root / "corpus.json"
        matrix.write_text(json.dumps({"cells": [
            {"id": "fr", "quick": True, "expectedHint": "french", "scriptLang": "french"},
        ]}))
        reference_script = "un deux trois quatre cinq six sept huit"
        corpus.write_text(json.dumps({"languages": [{"id": "french", "script": reference_script}]}))
        fr = engine_row("fr-id", run_id="lang-run", cell="fr")
        fr["notes"]["languageHint"] = "french"
        fr["notes"]["samplingWAVDigest"] = "a" * 64
        recognitions = independent_evidence(
            self.root / "independent-asr.json", run_id="lang-run", platform="macos",
            cells={"fr": {
                "generationID": "fr-id", "audioSHA256": "a" * 64, "expectedLanguage": "french",
                "expectedOutcome": "pass",
                "recognitions": [independent_recognition(
                    audio_sha256="a" * 64, script=reference_script,
                    transcript="un deux trois quatre cinq six sept neuf",
                )],
            }},
        )
        args = SimpleNamespace(
            matrix=matrix, corpus=corpus, subset="quick", diagnostics=self.root,
            run_id="lang-run", output_gate="independent", recognitions=recognitions, platform="macos",
            started_at="2026-09-12T12:00:00Z", finished_at="2026-09-12T12:01:00Z",
            label="fixture", artifact_dir=self.root, snapshot=self.root / "snapshot.json",
        )
        captured, write_patch = self.capture_manifest()
        patches = (
            mock.patch.object(publisher, "load_engine_rows", return_value=[fr]),
            mock.patch.object(publisher, "qualify_memory_rows", return_value=qualified_memory_fixture(["fr-id"])),
            mock.patch.object(publisher, "source_from_snapshot", return_value=source_fixture()),
            mock.patch.object(publisher, "crash_delta_from_snapshot", return_value={"passed": True, "count": 0}),
            self.hardware_patch(),
            write_patch,
        )
        with contextlib.ExitStack() as stack:
            for item in patches:
                stack.enter_context(item)
            publisher.language_command(args)
        record = captured["manifest"]["historyRecord"]
        self.assertEqual(record["run"]["matrixScope"], "focused")
        verification = record["evidence"]["languageVerification"]
        self.assertEqual(verification["families"], ["whisper"])
        self.assertEqual(verification["recognitionAlgorithm"], publisher.INDEPENDENT_ASR_ALGORITHM)
        self.assertEqual(verification["outputAlgorithm"], publisher.INDEPENDENT_OUTPUT_ALGORITHM)
        self.assertEqual(verification["requiredPassCount"], 1)
        self.assertEqual(verification["independentModelIdentitySHA256"], "2" * 64)
        self.assertEqual(verification["outputCellsPassed"], 1)
        take = record["takes"][0]
        self.assertEqual(take["accuracyMetric"], "wordErrorRate")
        self.assertEqual(take["metrics"]["independentWordErrorRate"], 0.125)
        self.assertEqual(take["metrics"]["independentPrimaryAccuracyScore"], 0.125)
        self.assertEqual(take["metrics"]["independentLanguagePass"], 1.0)
        self.assertEqual(take["detectedLanguages"], {"whisper": "french"})
        # Audit #86: the macOS take names its audio by the engine's WAV digest.
        self.assertEqual(take["output"]["fileDigest"], "a" * 64)
        self.assertEqual(verification["languageCheckKinds"], {"whisper": "audio-language-identification"})
        # Whisper's confidence is published beside its verdict (audit #89).
        self.assertEqual(take["metrics"]["independentMaximumNoSpeechProbability"], 0.02)
        self.assertEqual(take["metrics"]["independentMeanAverageLogProbability"], -0.25)
        self.assertNotIn("wordErrorRate", take["metrics"])
        self.assertNotIn("recognitionPassCount", take["metrics"])
        self.assertEqual(captured["manifest"]["historyRecord"]["inputs"].get("analysisProfileHash") is not None, True)

        # A failing transcript, a wrong detected language, or audio bound to
        # other bytes each refuses publication; a supplied score never helps.
        for label, mutate in (
            ("failed", lambda c: c["recognitions"][0].__setitem__("transcript", "neuf huit sept six cinq quatre trois deux")),
            ("failed", lambda c: c["recognitions"][0].__setitem__("detectedLanguage", "english")),
            ("other audio", lambda c: c.__setitem__("audioSHA256", "b" * 64)),
            ("unqualified", lambda c: c["recognitions"][0].__setitem__("audioSHA256", "b" * 64)),
            ("unqualified", lambda c: c["recognitions"][0].__setitem__("fullFileProcessed", False)),
        ):
            payload = json.loads(recognitions.read_text())
            mutate(payload["cells"]["fr"])
            payload["cells"]["fr"]["recognitions"][0]["errorRate"] = 0.0
            bad = self.root / "bad.json"
            bad.write_text(json.dumps(payload))
            args.recognitions = bad
            with self.subTest(label=label), contextlib.ExitStack() as stack:
                for item in patches:
                    stack.enter_context(item)
                with self.assertRaisesRegex(publisher.PublicationError, label):
                    publisher.language_command(args)

    def test_pinned_and_auto_takes_of_one_group_must_be_one_audio(self) -> None:
        """Audit #86: the group shares prompt and seed, so its WAVs are byte-identical."""
        cells = [
            {"id": "custom-en-pinned", "promptEquivalenceGroup": "custom-english-v1"},
            {"id": "custom-en-auto", "promptEquivalenceGroup": "custom-english-v1"},
            {"id": "design-en-pinned"},
            {"id": "custom-fr-pinned", "promptEquivalenceGroup": "custom-french-v1"},
            {"id": "custom-fr-auto", "promptEquivalenceGroup": "custom-french-v1"},
        ]

        def takes(*digests, seeds=(7, 7, 8, 9, 9)):
            return [{"seed": seed, "output": {"fileDigest": digest} if digest else {}}
                    for seed, digest in zip(seeds, digests)]

        publisher.validate_equivalent_outputs(cells, takes("a" * 64, "a" * 64, "b" * 64, "c" * 64, "c" * 64))
        # A member without a digest cannot be compared; seeds that differ are not one group.
        publisher.validate_equivalent_outputs(cells, takes("a" * 64, None, "b" * 64, "c" * 64, "c" * 64))
        publisher.validate_equivalent_outputs(
            cells, takes("a" * 64, "d" * 64, "b" * 64, "c" * 64, "c" * 64, seeds=(7, 6, 8, 9, 9)))
        with self.assertRaises(publisher.PublicationError):
            publisher.validate_equivalent_outputs(cells, takes("a" * 64, "a" * 64, "b" * 64, "c" * 64, "e" * 64))

    def test_a_skipped_phrase_under_the_gate_warns_but_never_fails(self) -> None:
        """Audit #84: two consecutive deleted words on a 17-word script pass the
        15 % gate; the take is published with the run and a warning."""
        script = ("chaque matin le jardin calme ouvre ses portes et le vieux jardinier "
                  "arrose chaque rose avant midi")
        transcript = script.replace("le jardin ", "")
        evidence = publisher.sanitized_independent_evidence(
            cell={"id": "fr", "expectedHint": "french"},
            engine_row={"generationID": "fr-id"},
            entry={"generationID": "fr-id", "audioSHA256": "a" * 64, "recognitions": [
                independent_recognition(audio_sha256="a" * 64, script=script, transcript=transcript),
            ]},
            reference_script=script, expected_audio_sha256="a" * 64, duration_seconds=2.0,
            apple_evidence=None,
        )
        self.assertTrue(evidence["pass"])
        self.assertEqual(evidence["longestDeletionRun"], 2)
        take = {"warnings": []}
        publisher.flag_deletion_run(take, evidence["longestDeletionRun"], family="whisper",
                                    negative_control=False)
        self.assertEqual(take["warnings"], ["language.deletion_run:whisper"])
        for run, control in ((1, False), (4, True)):
            quiet = {"warnings": []}
            publisher.flag_deletion_run(quiet, run, family="whisper", negative_control=control)
            self.assertEqual(quiet["warnings"], [])

    def test_ios_language_requires_two_recognizer_families_to_agree(self) -> None:
        matrix = self.root / "matrix.json"
        corpus = self.root / "corpus.json"
        matrix.write_text(json.dumps({"cells": [
            {"id": "fr", "quick": True, "expectedHint": "french",
             "mode": "custom", "variant": "speed", "scriptLang": "french"},
        ]}))
        reference_script = "un deux trois quatre cinq six sept huit"
        corpus.write_text(json.dumps({"languages": [{
            "id": "french", "script": reference_script, "customSpeakerID": "aiden",
            "designInstruction": "A warm, friendly narrator with a calm, measured pace.",
        }]}))
        plan_path = self.root / "language-run-plan.json"
        plan = language_plan(matrix=matrix, corpus=corpus)
        plan_path.write_text(json.dumps(plan))
        row = engine_row("fr-generation", run_id="lang-ios", cell="fr")
        row["notes"]["samplingSeed"] = str(plan["takes"][0]["seed"])
        row["notes"]["languageHint"] = "french"
        sentinel_dir = self.root / "diagnostics" / "lang-ios--fr"
        sentinel_dir.mkdir(parents=True)
        output_path = sentinel_dir / "output.wav"
        self.make_wave(output_path)
        sentinel = language_sentinel(output_path=output_path, seed=plan["takes"][0]["seed"])
        (sentinel_dir / "device-diagnostics-done.json").write_text(json.dumps(sentinel))
        with wave.open(str(output_path), "rb") as stream:
            duration = stream.getnframes() / stream.getframerate()
        wav_digest = publisher.digest_file(output_path)
        recognitions = independent_evidence(
            self.root / "independent-asr.json", run_id="lang-ios", platform="ios",
            cells={"fr": {
                "generationID": "fr-generation", "audioSHA256": wav_digest, "expectedLanguage": "french",
                "expectedOutcome": "pass",
                "recognitions": [independent_recognition(
                    audio_sha256=wav_digest, script=reference_script, duration=duration,
                )],
            }},
        )
        args = SimpleNamespace(
            matrix=matrix, corpus=corpus, subset="quick", diagnostics=self.root / "diagnostics",
            plan=plan_path, recognitions=recognitions,
            crash_diagnostics=None, run_id="lang-ios", output_gate="pass", platform="ios",
            started_at="2026-09-12T12:00:00Z", finished_at="2026-09-12T12:01:00Z",
            label="fixture", artifact_dir=self.root, snapshot=self.root / "snapshot.json",
            design_fixture_digest=None,
        )
        captured, write_patch = self.capture_manifest()
        patches = (
            mock.patch.object(publisher, "load_engine_rows", return_value=[row]),
            mock.patch.object(publisher, "load_app_rows", return_value=[app_row("fr-generation")]),
            mock.patch.object(publisher, "qualify_memory_rows", return_value=qualified_memory_fixture(["fr-generation"])),
            mock.patch.object(publisher, "source_from_snapshot", return_value=source_fixture()),
            mock.patch.object(publisher, "crash_delta_from_snapshot", return_value={"passed": True, "count": 0}),
            self.hardware_patch(),
            write_patch,
        )
        with contextlib.ExitStack() as stack:
            for item in patches:
                stack.enter_context(item)
            publisher.language_command(args)
        record = captured["manifest"]["historyRecord"]
        verification = record["evidence"]["languageVerification"]
        self.assertEqual(verification["families"], ["apple-speech", "whisper"])
        self.assertEqual(verification["recognitionAlgorithm"], "apple-speech-file-consensus-v2")
        self.assertEqual(verification["independentRecognitionAlgorithm"], publisher.INDEPENDENT_ASR_ALGORITHM)
        metrics = record["takes"][0]["metrics"]
        self.assertEqual(metrics["wordErrorRate"], 0.125)
        self.assertEqual(metrics["independentWordErrorRate"], 0.0)
        self.assertEqual(metrics["recognitionPassCount"], 3.0)
        # Audit #42: each family's check is declared for what it observes, and
        # each family's detected language is published per take.
        self.assertEqual(verification["languageCheckKinds"], {
            "apple-speech": "transcript-language-consistency",
            "whisper": "audio-language-identification",
        })
        self.assertEqual(set(record["takes"][0]["detectedLanguages"]), {"apple-speech", "whisper"})
        self.assertEqual(record["takes"][0]["detectedLanguages"]["whisper"], "french")
        profile_takes = captured["manifest"]["historyRecord"]["inputs"]
        self.assertRegex(profile_takes["analysisProfileHash"], r"^[0-9a-f]{64}$")

        payload = json.loads(recognitions.read_text())
        payload["cells"]["fr"]["recognitions"][0]["transcript"] = "des mots entièrement différents ici présents"
        disagreeing = self.root / "disagree.json"
        disagreeing.write_text(json.dumps(payload))
        args.recognitions = disagreeing
        with contextlib.ExitStack() as stack:
            for item in patches:
                stack.enter_context(item)
            with self.assertRaisesRegex(publisher.PublicationError, "did not agree"):
                publisher.language_command(args)

    def test_language_publication_rejects_mode_fixture_tampering(self) -> None:
        custom_take = {
            "mode": "custom",
            "customSpeakerID": "aiden",
            "designInstruction": None,
            "designInstructionDigest": None,
        }
        publisher.validate_language_mode_fixture_identity(
            cell_id="custom-en-pinned",
            planned_take=custom_take,
            sentinel={"customSpeakerID": "aiden", "fixtureDigest": None},
        )
        with self.assertRaisesRegex(publisher.PublicationError, "Custom speaker"):
            publisher.validate_language_mode_fixture_identity(
                cell_id="custom-en-pinned",
                planned_take=custom_take,
                sentinel={"customSpeakerID": "vivian", "fixtureDigest": None},
            )

        instruction = "A warm, friendly narrator with a calm, measured pace."
        instruction_digest = publisher.digest_bytes(instruction.encode("utf-8"))
        design_take = {
            "mode": "design",
            "customSpeakerID": None,
            "designInstruction": instruction,
            "designInstructionDigest": instruction_digest,
        }
        publisher.validate_language_mode_fixture_identity(
            cell_id="design-en-pinned",
            planned_take=design_take,
            sentinel={"customSpeakerID": None, "fixtureDigest": instruction_digest},
        )
        with self.assertRaisesRegex(publisher.PublicationError, "Design fixture digest"):
            publisher.validate_language_mode_fixture_identity(
                cell_id="design-en-pinned",
                planned_take=design_take,
                sentinel={"customSpeakerID": None, "fixtureDigest": "d" * 64},
            )

    def test_ios_language_requires_a_non_cohort_immutable_plan(self) -> None:
        with self.assertRaisesRegex(publisher.PublicationError, "immutable run plan"):
            publisher.load_language_plan(
                SimpleNamespace(platform="ios", plan=None),
                [{"id": "fr"}],
            )

        matrix = self.root / "matrix.json"
        corpus = self.root / "corpus.json"
        matrix.write_text(json.dumps({"cells": [{
            "id": "fr", "quick": True, "expectedHint": "french",
            "mode": "custom", "variant": "speed", "scriptLang": "french",
        }]}))
        corpus.write_text(json.dumps({"languages": [{
            "id": "french", "script": "un deux trois quatre cinq six sept huit",
            "customSpeakerID": "aiden",
            "designInstruction": "A warm, friendly narrator with a calm, measured pace.",
        }]}))
        plan = language_plan(matrix=matrix, corpus=corpus)
        plan["cohortID"] = "diagnostic-cohort"
        plan["cohortDigest"] = "d" * 64
        plan.pop("planDigest")
        plan["planDigest"] = publisher.digest_bytes(publisher.canonical_bytes(plan))
        plan_path = self.root / "cohort-plan.json"
        plan_path.write_text(json.dumps(plan))
        args = SimpleNamespace(
            platform="ios", plan=plan_path, run_id="lang-ios", matrix=matrix,
            corpus=corpus, subset="quick",
        )
        with self.assertRaisesRegex(publisher.PublicationError, "intentionally unpublished"):
            publisher.load_language_plan(args, publisher.selected_language_cells(matrix, "quick"))

    def test_language_plan_rejects_seed_or_take_order_drift(self) -> None:
        matrix = self.root / "matrix.json"
        corpus = self.root / "corpus.json"
        matrix.write_text(json.dumps({"cells": [{
            "id": "fr", "quick": True, "expectedHint": "french",
            "mode": "custom", "variant": "speed", "scriptLang": "french",
        }]}))
        corpus.write_text(json.dumps({"languages": [{
            "id": "french", "script": "un deux trois quatre cinq six sept huit",
            "customSpeakerID": "aiden",
            "designInstruction": "A warm, friendly narrator with a calm, measured pace.",
        }]}))
        cells = publisher.selected_language_cells(matrix, "quick")
        for name, mutate, message in (
            ("string-seed", lambda value: value["takes"][0].__setitem__("seed", "42"), "planned seed"),
            (
                "rehashed-numeric-seed",
                lambda value: value["takes"][0].__setitem__(
                    "seed", value["takes"][0]["seed"] + 1
                ),
                "deterministic tracked seed",
            ),
            (
                "rehashed-take-variation",
                lambda value: value["takes"][0].__setitem__(
                    "samplingVariation", "balanced"
                ),
                "expressive sampling variation",
            ),
            (
                "rehashed-seed-policy",
                lambda value: value.__setitem__("seedPolicy", "alternate-policy"),
                "seed policy",
            ),
            (
                "rehashed-plan-variation",
                lambda value: value.__setitem__("samplingVariation", "balanced"),
                "sampling variation",
            ),
            ("zero-index", lambda value: value["takes"][0].__setitem__("takeIndex", 0), "one-based"),
            (
                "wrong-ui-hint",
                lambda value: value["takes"][0].__setitem__("uiHint", "french"),
                "plan identity",
            ),
            (
                "rehashed-custom-speaker",
                lambda value: value["takes"][0].__setitem__("customSpeakerID", "vivian"),
                "mode fixture does not match the corpus",
            ),
        ):
            plan = language_plan(matrix=matrix, corpus=corpus)
            mutate(plan)
            plan.pop("planDigest")
            plan["planDigest"] = publisher.digest_bytes(publisher.canonical_bytes(plan))
            path = self.root / f"{name}.json"
            path.write_text(json.dumps(plan))
            args = SimpleNamespace(
                platform="ios", plan=path, run_id="lang-ios", matrix=matrix,
                corpus=corpus, subset="quick",
            )
            with self.subTest(name=name), self.assertRaisesRegex(publisher.PublicationError, message):
                publisher.load_language_plan(args, cells)

        design_matrix = self.root / "design-matrix.json"
        design_matrix.write_text(json.dumps({"cells": [{
            "id": "design-fr-pinned", "quick": True, "expectedHint": "french",
            "mode": "design", "variant": "speed", "scriptLang": "french",
            "uiHint": "french",
        }]}))
        design_plan = language_plan(matrix=design_matrix, corpus=corpus)
        instruction = "A warm, friendly narrator with a calm, measured pace."
        design_plan["takes"][0].update({
            "cellID": "design-fr-pinned",
            "childRunID": "lang-ios--design-fr-pinned",
            "mode": "design",
            "uiHint": "french",
            "customSpeakerID": None,
            "designInstruction": instruction,
            "designInstructionDigest": publisher.digest_bytes(instruction.encode("utf-8")),
        })
        design_plan.pop("planDigest")
        design_plan["planDigest"] = publisher.digest_bytes(
            publisher.canonical_bytes(design_plan)
        )
        design_cells = publisher.selected_language_cells(design_matrix, "quick")
        design_plan["takes"][0]["seed"] = publisher.stable_default_seed(design_cells[0])
        design_plan["takes"][0]["designInstructionDigest"] = "d" * 64
        design_plan.pop("planDigest")
        design_plan["planDigest"] = publisher.digest_bytes(
            publisher.canonical_bytes(design_plan)
        )
        design_path = self.root / "rehashed-design-fixture.json"
        design_path.write_text(json.dumps(design_plan))
        design_args = SimpleNamespace(
            platform="ios", plan=design_path, run_id="lang-ios",
            matrix=design_matrix, corpus=corpus, subset="quick",
        )
        with self.assertRaisesRegex(
            publisher.PublicationError, "mode fixture does not match the corpus"
        ):
            publisher.load_language_plan(design_args, design_cells)

    def test_language_asr_requires_exact_on_device_consensus_and_sampling_identity(self) -> None:
        matrix = self.root / "matrix.json"
        corpus = self.root / "corpus.json"
        matrix.write_text(json.dumps({"cells": []}))
        corpus.write_text(json.dumps({"languages": []}))
        plan = language_plan(matrix=matrix, corpus=corpus)
        planned_seed = plan["takes"][0]["seed"]
        output_path = self.root / "output.wav"
        self.make_wave(output_path)
        baseline = language_sentinel(output_path=output_path, seed=planned_seed)
        row = engine_row("fr-generation", run_id="lang-ios", cell="fr")
        row["notes"]["samplingSeed"] = str(planned_seed)
        cell = {"id": "fr", "expectedHint": "french"}
        reference_script = "un deux trois quatre cinq six sept huit"

        cases = []
        wrong_seed = copy.deepcopy(baseline)
        wrong_seed["seed"] = planned_seed + 1
        cases.append(("sentinel-seed", wrong_seed, row, "sentinel seed"))
        wrong_requested_hint = copy.deepcopy(baseline)
        wrong_requested_hint["requestedLanguageHint"] = "french"
        wrong_requested_hint["languageHintSource"] = "explicit"
        cases.append(("requested-hint", wrong_requested_hint, row, "requested hint"))
        wrong_engine = copy.deepcopy(row)
        wrong_engine["notes"]["samplingVariation"] = "balanced"
        cases.append(("engine-variation", baseline, wrong_engine, "engine variation"))
        unavailable = copy.deepcopy(baseline)
        unavailable["outputVerification"]["recognition"]["recognizerAvailable"] = False
        cases.append(("unavailable", unavailable, row, "consensus contract"))
        two_passes = copy.deepcopy(baseline)
        two_passes["outputVerification"]["recognition"]["repetitions"].pop()
        cases.append(("two-passes", two_passes, row, "exactly three"))
        disagreement = copy.deepcopy(baseline)
        disagreement["outputVerification"]["recognition"]["repetitions"][2]["transcript"] = "different"
        cases.append(("disagreement", disagreement, row, "consensus is inconsistent"))
        nonfinite = copy.deepcopy(baseline)
        nonfinite["outputVerification"]["characterErrorRate"] = float("inf")
        cases.append(("nonfinite-cer", nonfinite, row, "non-finite"))
        tampered = copy.deepcopy(baseline)
        tampered["outputVerification"]["hypothesisCharacterCount"] += 1
        cases.append(("tampered-metrics", tampered, row, "do not match corpus"))
        wrong_primary = copy.deepcopy(baseline)
        wrong_primary["outputVerification"]["accuracyMetric"] = "characterErrorRate"
        cases.append(("wrong-primary", wrong_primary, row, "primary accuracy gate"))
        wrong_algorithm = copy.deepcopy(baseline)
        wrong_algorithm["outputVerification"]["recognition"]["schemaVersion"] = 1
        cases.append(("old-recognition", wrong_algorithm, row, "unsupported recognition"))
        wrong_locale = copy.deepcopy(baseline)
        wrong_locale["outputVerification"]["recognition"]["selectedLocaleIdentifier"] = "zh-CN"
        for repetition in wrong_locale["outputVerification"]["recognition"]["repetitions"]:
            repetition["localeIdentifier"] = "zh-CN"
        cases.append(("wrong-locale", wrong_locale, row, "locale does not match"))
        out_of_range_score = copy.deepcopy(baseline)
        out_of_range_score["outputVerification"]["languageMatchScore"] = 1.000_000_000_1
        cases.append(("out-of-range-score", out_of_range_score, row, "non-finite ASR scores"))
        empty_skip_reason = copy.deepcopy(baseline)
        empty_skip_reason["outputVerification"]["skipReason"] = ""
        cases.append(("empty-skip-reason", empty_skip_reason, row, "failed output verification"))
        padded_transcript = copy.deepcopy(baseline)
        padded = f" {padded_transcript['outputVerification']['transcript']} "
        padded_transcript["outputVerification"]["transcript"] = padded
        padded_transcript["outputVerification"]["recognition"]["transcript"] = padded
        for repetition in padded_transcript["outputVerification"]["recognition"]["repetitions"]:
            repetition["transcript"] = padded
        cases.append(("padded-transcript", padded_transcript, row, "recognition pass"))

        for name, sentinel, candidate_row, message in cases:
            with self.subTest(name=name), self.assertRaisesRegex(publisher.PublicationError, message):
                publisher.sanitized_asr_evidence(
                    cell=cell,
                    planned_take=plan["takes"][0],
                    sentinel=sentinel,
                    engine_row=candidate_row,
                    parent_run_id="lang-ios",
                    reference_script=reference_script,
                )

    def test_language_asr_uses_character_error_for_chinese_and_japanese(self) -> None:
        output_path = self.root / "output.wav"
        self.make_wave(output_path)
        for language, reference, transcript in (
            ("chinese", "火车在黎明时离开", "火车在黎明时离开"),
            ("japanese", "列車は夜明けに出発", "列車は夜明けに出発"),
        ):
            verification = successful_asr_verification(reference=reference, transcript=transcript)
            verification.update({
                "expectedLanguage": language,
                "detectedLanguage": language,
                "accuracyMetric": "characterErrorRate",
                "accuracyValue": verification["characterErrorRate"],
            })
            verification["recognition"].update({
                "expectedLanguage": language,
                "selectedLocaleIdentifier": "zh-CN" if language == "chinese" else "ja-JP",
            })
            for repetition in verification["recognition"]["repetitions"]:
                repetition["localeIdentifier"] = verification["recognition"]["selectedLocaleIdentifier"]
            sentinel = language_sentinel(output_path=output_path, verification=verification)
            row = engine_row("fr-generation", run_id="lang-ios", cell="fr")
            planned_take = {
                "childRunID": "lang-ios--fr",
                "seed": 42,
                "samplingVariation": "expressive",
            }
            with self.subTest(language=language):
                evidence = publisher.sanitized_asr_evidence(
                    cell={"id": "fr", "expectedHint": language},
                    planned_take=planned_take,
                    sentinel=sentinel,
                    engine_row=row,
                    parent_run_id="lang-ios",
                    reference_script=reference,
                )
                self.assertEqual(evidence["accuracyMetric"], "characterErrorRate")
                self.assertEqual(evidence["primaryAccuracyScore"], 0.0)

    def test_language_character_metrics_preserve_japanese_dakuten(self) -> None:
        _word, metrics = publisher.recomputed_accuracy("かきくけこ", "がきくけこ", "japanese")
        self.assertEqual(metrics["substitutions"], 1)
        self.assertEqual(metrics["errorRate"], 0.2)

    def test_language_output_is_independently_hashed_and_read(self) -> None:
        output_path = self.root / "output.wav"
        self.make_wave(output_path)
        sentinel = language_sentinel(output_path=output_path)
        evidence = publisher.language_output_evidence(sentinel, output_path, "fr")
        self.assertEqual(evidence["fileDigest"], publisher.digest_file(output_path))
        self.assertEqual(evidence["frames"], 240)

        mismatched = copy.deepcopy(sentinel)
        mismatched["outputEvidence"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(publisher.PublicationError, "invalid output metadata"):
            publisher.language_output_evidence(mismatched, output_path, "fr")

    def test_prompt_equivalence_requires_equal_resolved_digests(self) -> None:
        planned = [
            {"cellID": "auto", "seed": 42, "promptEquivalenceGroup": "english"},
            {"cellID": "pinned", "seed": 42, "promptEquivalenceGroup": "english"},
        ]
        sentinels = {
            cell: {
                "promptDigestScope": "resolved",
                "resolvedPromptAssemblyDigest": "a" * 64,
            }
            for cell in ("auto", "pinned")
        }
        rows = {
            cell: {"notes": {"resolvedPromptAssemblyDigest": "a" * 64}}
            for cell in ("auto", "pinned")
        }
        publisher.validate_prompt_equivalence(
            planned_takes=planned, sentinels=sentinels, rows_by_cell=rows
        )
        sentinels["pinned"]["resolvedPromptAssemblyDigest"] = "b" * 64
        rows["pinned"]["notes"].pop("resolvedPromptAssemblyDigest")
        with self.assertRaisesRegex(publisher.PublicationError, "is inconsistent"):
            publisher.validate_prompt_equivalence(
                planned_takes=planned, sentinels=sentinels, rows_by_cell=rows
            )

    def test_legacy_telemetry_overhead_parser_requires_eighteen_samples(self) -> None:
        rotations = [
            ("off", "lightweight", "verbose"),
            ("lightweight", "verbose", "off"),
            ("verbose", "off", "lightweight"),
        ]
        results = {}
        pcm = {
            f"r{rotation}-t{measured}": f"{rotation}{measured}" * 32
            for rotation in range(1, 4) for measured in range(1, 3)
        }
        for mode in ("off", "lightweight", "verbose"):
            results[mode] = {"pcmSHA256": dict(pcm), "samples": [
                {
                    "rotation": rotation,
                    "modeOrder": rotations[rotation - 1].index(mode) + 1,
                    "measuredTake": measured,
                    "generationID": f"{mode}-{rotation}-{measured}",
                    "rtf": 1.0,
                    "ttfcMS": 10.0,
                    "audioSeconds": 2.0,
                    "environment": {
                        "loadAverage1Minute": float(rotation) + measured / 10,
                        "freeStorageBytes": 900 - measured,
                        "uptimeSeconds": 100.0 + measured,
                        "lowPowerModeEnabled": rotation == 2,
                        "thermalState": "nominal",
                    },
                }
                for rotation in range(1, 4) for measured in range(1, 3)
            ]}
        contexts = []
        for rotation, order in enumerate(rotations, start=1):
            for mode_order, mode in enumerate(order, start=1):
                contexts.append({
                    "rotation": rotation,
                    "order": mode_order,
                    "mode": mode,
                    "before": {
                        "loadAverage": [float(rotation), 0.0, 0.0],
                        "freeStorageBytes": 1000 - rotation,
                        "uptimeSeconds": 50.0 + rotation,
                        "lowPowerMode": rotation == 2,
                        "thermalState": "nominal",
                    },
                    "after": {"thermalState": "fair" if rotation == 3 else "nominal"},
                })
        verdict = self.root / "verdict.json"
        verdict.write_text(json.dumps({
            "schemaVersion": 2,
            "runID": "telemetry-overhead-fixture",
            "startedAt": "2026-07-12T12:00:00Z",
            "completedAt": "2026-07-12T12:01:00Z",
            "status": "pass",
            "summary": {
                "telemetrySchemaVersion": 8,
                "modelID": "pro_custom_speed",
                "modelRuntimeIdentity": engine_row("identity")["modelRuntimeIdentity"],
                "pcmParity": True,
                "failures": [],
                "results": results,
                "machineContext": contexts,
            },
        }))
        args = SimpleNamespace(
            verdict=verdict, artifact_dir=self.root, snapshot=self.root / "snapshot.json",
        )
        captured, write_patch = self.capture_manifest()
        with (
            mock.patch.object(publisher, "source_from_snapshot", return_value=source_fixture()),
            mock.patch.object(publisher, "crash_delta_from_snapshot", return_value={"passed": True, "count": 0}),
            self.hardware_patch(),
            write_patch,
        ):
            publisher._legacy_telemetry_overhead_record(args)
        takes = captured["manifest"]["historyRecord"]["takes"]
        self.assertEqual(len(takes), 18)
        self.assertEqual(
            captured["manifest"]["historyRecord"]["run"]["ttfcDefinition"],
            "cli-submit-to-first-chunk",
        )
        self.assertEqual(
            [take["cell"] for take in takes[:8]],
            [
                "rotation-1/order-1/off/take-1",
                "rotation-1/order-1/off/take-2",
                "rotation-1/order-2/lightweight/take-1",
                "rotation-1/order-2/lightweight/take-2",
                "rotation-1/order-3/verbose/take-1",
                "rotation-1/order-3/verbose/take-2",
                "rotation-2/order-1/lightweight/take-1",
                "rotation-2/order-1/lightweight/take-2",
            ],
        )
        self.assertEqual(takes[0]["metrics"]["loadAverage1M"], 1.1)
        self.assertEqual(takes[6]["metrics"]["lowPowerMode"], 1.0)
        self.assertEqual(takes[-1]["thermalState"], "fair")
        self.assertEqual(takes[0]["output"], {
            "readableWAV": True,
            "atomicPublish": True,
            "durationSeconds": 2.0,
            "fileDigest": pcm["r1-t1"],
        })
        self.assertEqual(
            [take["output"]["fileDigest"] for take in takes if "/off/" in take["cell"]],
            [pcm[f"r{rotation}-t{measured}"] for rotation in range(1, 4) for measured in range(1, 3)],
        )
        self.assertTrue(all(
            take["runtimeProfileSignature"] == "pro_custom_speed:fixture-v1"
            for take in takes
        ))
        self.assertTrue(all(take["modelIntegrityDigest"] == "f" * 64 for take in takes))
        models = captured["manifest"]["historyRecord"]["models"]
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0]["mode"], "custom")
        self.assertEqual(
            models[0]["modelID"],
            "PowerBeef02/Qwen3-TTS-12Hz-1.7B-CustomVoice-4bit",
        )
        self.assertEqual(models[0]["revision"], "29c4b746cd1e2a916f0233b241019205dffbfbc2")
        invalid = json.loads(verdict.read_text())
        invalid["summary"]["results"]["off"]["pcmSHA256"]["r1-t1"] = (
            publisher.hashlib.sha256(b"").hexdigest()
        )
        verdict.write_text(json.dumps(invalid))
        with self.assertRaisesRegex(publisher.PublicationError, "empty or invalid PCM"):
            publisher._legacy_telemetry_overhead_record(args)

    def test_telemetry_overhead_rejects_schema_v2_publication(self) -> None:
        verdict = self.root / "verdict.json"
        verdict.write_text(json.dumps({
            "schemaVersion": 2,
            "runID": "telemetry-overhead-fixture",
            "startedAt": "2026-07-12T12:00:00Z",
            "completedAt": "2026-07-12T12:01:00Z",
            "status": "pass",
            "summary": {"pcmParity": True, "failures": [], "results": {}},
        }))
        args = SimpleNamespace(
            verdict=verdict, artifact_dir=self.root, snapshot=self.root / "snapshot.json",
        )
        with self.assertRaisesRegex(
            publisher.PublicationError,
            "cannot publish schema-v2 history",
        ):
            publisher.telemetry_overhead_command(args)

    def test_memory_retention_policy_passes_and_rejects_growth_or_matrix_drift(self) -> None:
        policy_path = self.root / "memory-policy.json"
        policy_path.write_text(json.dumps({
            "schemaVersion": 1,
            "policyID": "retained-memory-v1",
            "metric": "withinModeRetainedPhysicalFootprintGrowth",
            "modes": ["custom", "design", "clone"],
            "variant": "speed",
            "length": "medium",
            "repetitionsPerMode": 3,
            "seed": 19790615,
            "retentionThresholdFractionOfPhysicalMemory": 0.05,
            "expectedTakeCounts": {"macos": 11, "ios": 9},
        }), encoding="utf-8")
        takes = []
        index = 1
        for mode in ("custom", "design", "clone"):
            if mode != "clone":
                takes.append({
                    "takeIndex": index, "mode": mode,
                    "cell": f"{mode}/speed/medium/cold#0", "variant": "speed",
                    "length": "medium", "warmState": "cold",
                    "metrics": {"physicalFootprintEndMB": 3000.0},
                })
                index += 1
            for repetition in range(3):
                takes.append({
                    "takeIndex": index, "mode": mode,
                    "cell": f"{mode}/speed/medium/retained#{repetition}", "variant": "speed",
                    "length": "medium", "warmState": "warm",
                    "metrics": {"physicalFootprintEndMB": 3000.0 + repetition * 10},
                })
                index += 1
        results = {
            "seed": 19790615,
            "memoryQualification": {"policyID": "retained-memory-v1"},
        }
        with mock.patch.object(publisher, "MEMORY_POLICY_PATH", policy_path):
            evidence, digest = publisher.memory_retention_evidence(results, takes, "macos")
            self.assertTrue(evidence["retentionPassed"])
            self.assertEqual(evidence["maximumRetainedGrowthMB"], 20.0)
            self.assertEqual(len(digest), 64)

            # The threshold is a fraction of the canonical profile's physical memory
            # (the registry's canonical macOS host), so spikes scale with it.
            memory_mb = publisher.canonical_hardware_profile("macos")["memoryBytes"] / 1_048_576.0
            excessive = copy.deepcopy(takes)
            excessive[3]["metrics"]["physicalFootprintEndMB"] = 3000.0 + 0.06 * memory_mb
            with self.assertRaisesRegex(publisher.PublicationError, "exceeds policy threshold"):
                publisher.memory_retention_evidence(results, excessive, "macos")

            recovered_spike = copy.deepcopy(takes)
            recovered_spike[2]["metrics"]["physicalFootprintEndMB"] = 3000.0 + 0.075 * memory_mb
            recovered_spike[3]["metrics"]["physicalFootprintEndMB"] = 3010.0
            with self.assertRaisesRegex(publisher.PublicationError, "exceeds policy threshold"):
                publisher.memory_retention_evidence(results, recovered_spike, "macos")

            recovered_below_baseline = copy.deepcopy(takes)
            for take in recovered_below_baseline:
                if take["mode"] == "custom" and "/retained#" in take["cell"]:
                    repetition = int(take["cell"].rsplit("#", 1)[-1])
                    take["metrics"]["physicalFootprintEndMB"] = 3000.0 - repetition * 10
            recovered, _ = publisher.memory_retention_evidence(
                results, recovered_below_baseline, "macos"
            )
            self.assertGreaterEqual(recovered["maximumRetainedGrowthMB"], 0.0)

            reordered = copy.deepcopy(takes)
            reordered[0], reordered[1] = reordered[1], reordered[0]
            with self.assertRaisesRegex(publisher.PublicationError, "ordered matrix"):
                publisher.memory_retention_evidence(results, reordered, "macos")

    def test_retained_memory_v2_reports_mlx_growth_and_gates_only_once_calibrated(self) -> None:
        # The live policy supplies the contract's shape; both platforms start
        # explicitly uncalibrated here, whatever a maintainer records later.
        policy = json.loads(publisher.MEMORY_POLICY_PATH.read_text(encoding="utf-8"))
        for platform_entry in ("macos", "ios"):
            policy["retainedMemoryV2"]["calibration"][platform_entry] = {
                "status": "uncalibrated", "calibrationRunID": None,
                "growthLimitMBByMode": {"custom": None, "design": None, "clone": None},
            }
        takes = []
        index = 1
        for mode in ("custom", "design", "clone"):
            if mode != "clone":
                takes.append({
                    "takeIndex": index, "mode": mode, "cell": f"{mode}/speed/medium/cold#0",
                    "variant": "speed", "length": "medium",
                    "metrics": {"physicalFootprintEndMB": 3000.0, "mlxEndActiveMB": 1500.0},
                })
                index += 1
            for repetition in range(3):
                takes.append({
                    "takeIndex": index, "mode": mode,
                    "cell": f"{mode}/speed/medium/retained#{repetition}",
                    "variant": "speed", "length": "medium",
                    "metrics": {
                        "physicalFootprintEndMB": 3000.0,
                        # Clone keeps 30 MB more MLX memory after every take.
                        "mlxEndActiveMB": 1800.0 + (30.0 * repetition if mode == "clone" else 0.0),
                    },
                })
                index += 1
        results = {"seed": 19790615, "memoryQualification": {"policyID": "retained-memory-v1"}}
        policy_path = self.root / "memory-policy.json"

        def evidence_with(mutate=None, platform: str = "macos", candidate_takes=takes):
            candidate = copy.deepcopy(policy)
            if mutate is not None:
                mutate(candidate["retainedMemoryV2"])
            policy_path.write_text(json.dumps(candidate), encoding="utf-8")
            with mock.patch.object(publisher, "MEMORY_POLICY_PATH", policy_path):
                return publisher.memory_retention_evidence(results, candidate_takes, platform)[0]

        uncalibrated = evidence_with()["retainedMemoryV2"]
        self.assertEqual(uncalibrated, {
            "policyID": "retained-memory-v2",
            "metric": "withinModeRetainedMLXActiveGrowth",
            "calibration": "uncalibrated",
            "growthByModeMB": {"custom": 0.0, "design": 0.0, "clone": 60.0},
            "maximumRetainedGrowthMB": 60.0,
        })

        def calibrate(limit: float):
            def apply(block: dict) -> None:
                block["calibration"]["macos"] = {
                    "status": "calibrated", "calibrationRunID": "mac-memory-calibration-fixture",
                    "growthLimitMBByMode": {"custom": limit, "design": limit, "clone": limit},
                }
            return apply

        calibrated = evidence_with(calibrate(64.0))["retainedMemoryV2"]
        self.assertEqual(calibrated["calibration"], "calibrated")
        self.assertTrue(calibrated["passed"])
        with self.assertRaisesRegex(publisher.PublicationError, "exceeds its calibrated bound in: clone"):
            evidence_with(calibrate(50.0))
        # The iPhone entry stays uncalibrated whatever the Mac declares.
        ios_takes = [take for take in takes if "/cold#" not in take["cell"]]
        self.assertEqual(
            evidence_with(calibrate(50.0), platform="ios", candidate_takes=ios_takes)
            ["retainedMemoryV2"]["calibration"],
            "uncalibrated",
        )

        drifts = {
            "stages": lambda block: block.update({"endOfTakeStages": ["after_stream"]}),
            "bound-while-uncalibrated": lambda block: block["calibration"]["macos"][
                "growthLimitMBByMode"].update({"custom": 10.0}),
            "calibrated-without-bounds": lambda block: block["calibration"]["macos"].update(
                {"status": "calibrated", "calibrationRunID": "fixture"}
            ),
        }
        for name, mutate in drifts.items():
            with self.subTest(drift=name), self.assertRaises(publisher.PublicationError):
                evidence_with(mutate)
        missing = copy.deepcopy(takes)
        missing[2]["metrics"].pop("mlxEndActiveMB")
        with self.assertRaisesRegex(publisher.PublicationError, "end-of-take MLX evidence"):
            evidence_with(candidate_takes=missing)

    def test_prosody_calibration_retains_aggregate_accuracy_and_thresholds(self) -> None:
        profile = self.root / "profile.json"
        thresholds = {
            "monotone_f0_std_hz": 10.0,
            "monotone_turning_points_per_sec": 1.0,
            "rushed_syllable_rate_hz": 7.0,
            "rushed_max_pause_ratio": 0.1,
            "flat_envelope_roughness": 0.02,
            "flat_rate_cv": 0.2,
            "pause_max_seconds": 1.5,
            "pause_ratio_max": 0.4,
        }
        profile.write_text(json.dumps({"thresholds": thresholds}))
        result = self.root / "calibration-results.json"
        result.write_text(json.dumps({
            "status": "pass",
            "analysisFailureCount": 0,
            "runID": "prosody-fixture",
            "label": "fixture",
            "startedAt": "2026-07-12T12:00:00Z",
            "finishedAt": "2026-07-12T12:01:00Z",
            "goodClipCount": 3,
            "badClipCount": 4,
            "targetFalsePositiveRate": 0.05,
            "corpusDigest": "c" * 64,
            "profileDigest": publisher.digest_file(profile),
            "flagRates": {
                "good_flag_rate": 0.0,
                "bad_flag_rate": 0.75,
                "false_positive_rate": 0.0,
                "true_positive_rate": 0.75,
            },
        }))
        args = SimpleNamespace(
            results=result,
            profile=profile,
            artifact_dir=self.root,
            snapshot=self.root / "snapshot.json",
        )
        captured, write_patch = self.capture_manifest()
        with (
            mock.patch.object(publisher, "source_from_snapshot", return_value=source_fixture()),
            self.hardware_patch(),
            write_patch,
        ):
            publisher.prosody_command(args)
        metrics = captured["manifest"]["historyRecord"]["takes"][0]["metrics"]
        self.assertEqual(metrics["analyzerAlgorithmVersion"], 1.0)
        self.assertEqual(metrics["goodClipCount"], 3.0)
        self.assertEqual(metrics["observedTruePositiveRate"], 0.75)
        self.assertEqual(metrics["maximumPauseThresholdSeconds"], 1.5)

    def test_profile_requires_a_nonempty_exported_trace_toc(self) -> None:
        trace = self.root / "build" / "profile.trace"
        trace.mkdir(parents=True)
        (trace / "data.bin").write_bytes(b"trace")
        toc = self.root / "trace-toc.xml"
        toc.write_text(
            "<trace-toc><run><processes><process name='Vocello' pid='4242'/>"
            "<process name='kernel' pid='0'/></processes><data>"
            "<table schema='time-profile'/><table schema='os-signpost'/></data></run></trace-toc>"
        )
        args = SimpleNamespace(
            trace=trace,
            toc=toc,
            template="Time Profiler",
            duration=10.0,
            target_process="Vocello",
            target_pid=4242,
            run_id="profile-fixture",
        )
        extracted = {
            "capturedRowsBySchema": {"time-profile": 12, "os-signpost": 8},
            "capturedDataRowCount": 20,
            "cpuSampleCount": 12,
            "cpuSampleWeightMS": 12.0,
            "cpuSampleSpanMS": 9.0,
            "signpostEventCount": 8,
            "correlatedSignpostEventCount": 4,
            "correlationFieldsVerified": True,
        }
        with (
            mock.patch.object(publisher, "ROOT", self.root),
            mock.patch.object(
                publisher, "extract_trace_data_summary", return_value=extracted
            ) as extract,
        ):
            evidence = publisher.trace_evidence(
                args,
                expected_correlations={
                    ("profile-generation", 1, "custom/speed/medium/warm#0")
                },
            )
            self.assertEqual(evidence["summary"]["tableCount"], 2)
            self.assertEqual(evidence["summary"]["schemaCount"], 2)
            self.assertEqual(evidence["summary"]["signpostSchemaCount"], 1)
            self.assertEqual(evidence["summary"]["processCount"], 2)
            self.assertTrue(evidence["summary"]["targetPIDVerified"])
            self.assertEqual(evidence["summary"]["cpuSampleCount"], 12)
            self.assertEqual(evidence["summary"]["correlatedSignpostEventCount"], 4)
            self.assertEqual(extract.call_args.kwargs["target_pid"], 4242)
            self.assertEqual(evidence["retentionPolicy"], "summaryOnly")
            self.assertFalse(evidence["rawTraceRetained"])
            self.assertEqual(
                evidence["originalEphemeralPath"], "build/profile.trace"
            )
            self.assertEqual(
                evidence["summaryArtifact"]["path"], "build/profile-summary.json"
            )
            summary_artifact = self.root / evidence["summaryArtifact"]["path"]
            self.assertTrue(summary_artifact.is_file())
            self.assertEqual(
                evidence["summaryArtifact"]["digest"],
                publisher.digest_file(summary_artifact),
            )
            frozen = json.loads(summary_artifact.read_text(encoding="utf-8"))
            self.assertEqual(frozen["traceDigest"], evidence["digest"])
            self.assertEqual(frozen["captureSettings"], evidence["captureSettings"])
            self.assertEqual(
                frozen["captureSettingsDigest"], evidence["captureSettingsDigest"]
            )
            self.assertTrue(trace.is_dir(), "the publisher must not delete raw traces")
            extract.reset_mock()
            args.target_pid = None
            derived = publisher.trace_evidence(
                args,
                expected_correlations={
                    ("profile-generation", 1, "custom/speed/medium/warm#0")
                },
            )
            self.assertTrue(derived["summary"]["targetPIDVerified"])
            self.assertEqual(extract.call_args.kwargs["target_pid"], 4242)
            args.retention_policy = "keptExplicitly"
            args.summary_artifact = self.root / "build" / "kept-profile-summary.json"
            kept = publisher.trace_evidence(
                args,
                expected_correlations={
                    ("profile-generation", 1, "custom/speed/medium/warm#0")
                },
            )
            self.assertEqual(kept["retentionPolicy"], "keptExplicitly")
            self.assertTrue(kept["rawTraceRetained"])
            self.assertEqual(
                kept["summaryArtifact"]["path"], "build/kept-profile-summary.json"
            )
            args.summary_artifact = trace / "invalid-summary.json"
            with self.assertRaisesRegex(
                publisher.PublicationError, "outside the raw trace bundle"
            ):
                publisher.trace_evidence(
                    args,
                    expected_correlations={
                        ("profile-generation", 1, "custom/speed/medium/warm#0")
                    },
                )
            args.summary_artifact = None
            args.target_pid = 4242
            args.target_pid = 9999
            with self.assertRaises(publisher.PublicationError):
                publisher.trace_evidence(
                    args,
                    expected_correlations={
                        ("profile-generation", 1, "custom/speed/medium/warm#0")
                    },
                )
            args.target_pid = 4242
            args.target_process = "WrongTarget"
            with self.assertRaises(publisher.PublicationError):
                publisher.trace_evidence(
                    args,
                    expected_correlations={
                        ("profile-generation", 1, "custom/speed/medium/warm#0")
                    },
                )

    def test_memory_profile_reports_unexportable_tracks_without_claiming_rows(self) -> None:
        trace = self.root / "build" / "memory-profile.trace"
        trace.mkdir(parents=True)
        (trace / "data.bin").write_bytes(b"trace")
        allocation_dir = trace / "Trace1.run"
        allocation_dir.mkdir()
        (allocation_dir / "event_data_4242.oa").write_bytes(b"allocation-events")
        toc = self.root / "memory-trace-toc.xml"
        toc.write_text(
            "<trace-toc><run><processes><process name='Vocello' pid='4242'/></processes>"
            "<data><table schema='time-profile'/><table schema='os-signpost'/></data>"
            "<tracks><track name='Allocations'><details><detail name='Allocations List'/></details></track>"
            "<track name='VM Tracker'><details><detail name='Regions Map'/></details></track></tracks>"
            "</run></trace-toc>"
        )
        args = SimpleNamespace(
            trace=trace,
            toc=toc,
            template="CPU Profiler + Allocations + VM Tracker + os_signpost",
            duration=10.0,
            target_process="Vocello",
            target_pid=4242,
            run_id="memory-profile-fixture",
            profile_kind="memory",
        )
        extracted = {
            "capturedRowsBySchema": {
                "time-profile": 12,
                "os-signpost": 4,
            },
            "capturedDataRowCount": 16,
            "cpuSampleCount": 12,
            "cpuSampleSpanMS": 9.0,
            "signpostEventCount": 4,
            "correlatedSignpostEventCount": 1,
            "correlationFieldsVerified": True,
        }
        correlations = {("generation", 1, "custom/speed/medium/warm#0")}
        with (
            mock.patch.object(publisher, "ROOT", self.root),
            mock.patch.object(
                publisher, "extract_trace_data_summary", return_value=extracted
            ),
        ):
            evidence = publisher.trace_evidence(
                args, expected_correlations=correlations
            )
        self.assertEqual(
            evidence["summary"]["allocationTargetDataBytes"], len(b"allocation-events")
        )
        self.assertEqual(evidence["summary"]["memoryTraceEvidenceVersion"], 2)
        self.assertTrue(evidence["summary"]["allocationTrackPresent"])
        self.assertTrue(evidence["summary"]["allocationListPresent"])
        self.assertTrue(evidence["summary"]["vmTrackerTrackPresent"])
        self.assertTrue(evidence["summary"]["vmTrackerRegionMapPresent"])
        self.assertEqual(evidence["summary"]["allocationDataExportStatus"], "notExportable")
        self.assertEqual(evidence["summary"]["allocationTargetRowCount"], 0)
        self.assertEqual(evidence["summary"]["vmTrackerDataExportStatus"], "notExportable")
        self.assertEqual(evidence["summary"]["vmTrackerTargetRowCount"], 0)
        self.assertNotIn("allocationTrackVerified", evidence["summary"])
        self.assertNotIn("vmTrackerTrackVerified", evidence["summary"])
        self.assertNotIn("vmTrackerRegionMapVerified", evidence["summary"])

        (allocation_dir / "event_data_4242.oa").unlink()
        with (
            mock.patch.object(publisher, "ROOT", self.root),
            mock.patch.object(publisher, "extract_trace_data_summary", return_value=extracted),
            self.assertRaisesRegex(publisher.PublicationError, "allocation event data"),
        ):
            publisher.trace_evidence(args, expected_correlations=correlations)

    def test_macos_memory_profile_rejects_vm_tracker_automatic_snapshots(self) -> None:
        trace = self.root / "build" / "memory-template.trace"
        trace.mkdir(parents=True)

        def write_template(enabled: bool) -> None:
            with (trace / "form.template").open("wb") as stream:
                plistlib.dump(
                    {
                        "$objects": [
                            "$null",
                            "XRVMInstrumentKey_autoSnapshot",
                            enabled,
                            {
                                "NS.keys": [plistlib.UID(1)],
                                "NS.objects": [plistlib.UID(2)],
                            },
                        ]
                    },
                    stream,
                    fmt=plistlib.FMT_BINARY,
                )

        write_template(False)
        publisher.require_vm_tracker_auto_snapshot_disabled(trace)

        write_template(True)
        with self.assertRaisesRegex(
            publisher.PublicationError,
            "automatic snapshots are enabled",
        ):
            publisher.require_vm_tracker_auto_snapshot_disabled(trace)

        with (trace / "form.template").open("wb") as stream:
            plistlib.dump({"$objects": ["$null"]}, stream, fmt=plistlib.FMT_BINARY)
        with self.assertRaisesRegex(
            publisher.PublicationError,
            "does not expose",
        ):
            publisher.require_vm_tracker_auto_snapshot_disabled(trace)

    def test_memory_profile_requires_target_rows_for_exportable_memory_tables(self) -> None:
        trace = self.root / "build" / "memory-exportable.trace"
        trace.mkdir(parents=True)
        (trace / "data.bin").write_bytes(b"trace")
        allocation_dir = trace / "Trace1.run"
        allocation_dir.mkdir()
        (allocation_dir / "event_data_4242.oa").write_bytes(b"allocation-events")
        toc = self.root / "memory-exportable-toc.xml"
        toc.write_text(
            "<trace-toc><run><processes><process name='Vocello' pid='4242'/></processes>"
            "<data><table schema='time-profile'/><table schema='os-signpost'/>"
            "<table schema='allocations'/><table schema='vm-tracker'/></data>"
            "<tracks><track name='Allocations'><details><detail name='Allocations List'/></details></track>"
            "<track name='VM Tracker'><details><detail name='Regions Map'/></details></track></tracks>"
            "</run></trace-toc>"
        )
        args = SimpleNamespace(
            trace=trace,
            toc=toc,
            template="CPU Profiler + Allocations + VM Tracker + os_signpost",
            duration=10.0,
            target_process="Vocello",
            target_pid=4242,
            run_id="memory-profile-exportable",
            profile_kind="memory",
        )
        extracted = {
            "capturedRowsBySchema": {
                "time-profile": 12,
                "os-signpost": 4,
                "allocations": 3,
                "vm-tracker": 2,
            },
            "capturedDataRowCount": 21,
            "cpuSampleCount": 12,
            "cpuSampleSpanMS": 9.0,
            "signpostEventCount": 4,
            "correlatedSignpostEventCount": 1,
            "correlationFieldsVerified": True,
        }
        correlations = {("generation", 1, "custom/speed/medium/warm#0")}
        with (
            mock.patch.object(publisher, "ROOT", self.root),
            mock.patch.object(
                publisher, "extract_trace_data_summary", return_value=extracted
            ),
        ):
            evidence = publisher.trace_evidence(
                args, expected_correlations=correlations
            )
        self.assertEqual(evidence["summary"]["allocationDataExportStatus"], "targetRows")
        self.assertEqual(evidence["summary"]["allocationTargetRowCount"], 3)
        self.assertEqual(evidence["summary"]["vmTrackerDataExportStatus"], "targetRows")
        self.assertEqual(evidence["summary"]["vmTrackerTargetRowCount"], 2)

        for schema, message in (
            ("allocations", "Allocations tables"),
            ("vm-tracker", "VM Tracker tables"),
        ):
            wrong_pid_only = copy.deepcopy(extracted)
            wrong_pid_only["capturedRowsBySchema"][schema] = 0
            with (
                self.subTest(schema=schema),
                mock.patch.object(publisher, "ROOT", self.root),
                mock.patch.object(
                    publisher,
                    "extract_trace_data_summary",
                    return_value=wrong_pid_only,
                ),
                self.assertRaisesRegex(publisher.PublicationError, message),
            ):
                publisher.trace_evidence(args, expected_correlations=correlations)

    def test_trace_summary_extracts_cpu_samples_and_correlated_signposts(self) -> None:
        trace = self.root / "profile.trace"
        trace.mkdir()

        def fake_export(command, **_kwargs):
            output = Path(command[command.index("--output") + 1])
            xpath = command[command.index("--xpath") + 1]
            if "time-profile" in xpath:
                xml = """<trace-query-result>
                <process id='target' pid='4242'/>
                <row><process pid='9999'/><sample-time>0</sample-time><weight>9000000</weight></row>
                <row><process ref='target'/><sample-time id='t1'>1000000</sample-time><weight id='w1'>1000000</weight></row>
                <row><process pid='4242'/><sample-time id='t2'>4000000</sample-time><weight ref='w1'/></row>
                </trace-query-result>"""
            else:
                xml = """<trace-query-result>
                <row><process pid='9999'/><string>runID=profile-run generationID=wrong takeIndex=1 cell=wrong</string></row>
                <row><process pid='4242'/><string>runID=profile-run generationID=gen-1 takeIndex=1 cell=custom/speed/medium/warm#0</string></row>
                </trace-query-result>"""
            output.write_text(xml, encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with mock.patch.object(publisher.subprocess, "run", side_effect=fake_export):
            summary = publisher.extract_trace_data_summary(
                trace, {"time-profile", "os-signpost"}, run_id="profile-run",
                target_pid=4242,
                expected_correlations={
                    ("gen-1", 1, "custom/speed/medium/warm#0")
                },
            )
        self.assertEqual(summary["cpuSampleCount"], 2)
        self.assertEqual(summary["cpuSampleWeightMS"], 2.0)
        self.assertEqual(summary["cpuSampleSpanMS"], 3.0)
        self.assertEqual(summary["correlatedSignpostEventCount"], 1)
        self.assertEqual(summary["capturedRowsBySchema"]["time-profile"], 2)
        self.assertEqual(summary["capturedRowsBySchema"]["os-signpost"], 1)

    def test_trace_summary_filters_memory_tables_to_the_exact_target_pid(self) -> None:
        trace = self.root / "profile-memory-rows.trace"
        trace.mkdir()

        def fake_export(command, **_kwargs):
            output = Path(command[command.index("--output") + 1])
            xpath = command[command.index("--xpath") + 1]
            if "time-profile" in xpath:
                xml = """<trace-query-result>
                <row><process pid='4242'/><sample-time>1000000</sample-time><weight>1000000</weight></row>
                <row><process pid='4242'/><sample-time>4000000</sample-time><weight>1000000</weight></row>
                </trace-query-result>"""
            elif "os-signpost" in xpath:
                xml = """<trace-query-result>
                <row><process pid='4242'/><string>runID=profile-run generationID=gen-1 takeIndex=1 cell=custom/speed/medium/warm#0</string></row>
                </trace-query-result>"""
            elif "allocations" in xpath:
                xml = """<trace-query-result>
                <row><process pid='9999'/><size>900</size></row>
                <row><process pid='4242'/><size>100</size></row>
                </trace-query-result>"""
            else:
                xml = """<trace-query-result>
                <row><process pid='9999'/><region-size>4096</region-size></row>
                </trace-query-result>"""
            output.write_text(xml, encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with mock.patch.object(publisher.subprocess, "run", side_effect=fake_export):
            summary = publisher.extract_trace_data_summary(
                trace,
                {"time-profile", "os-signpost", "allocations", "vm-tracker"},
                run_id="profile-run",
                target_pid=4242,
                expected_correlations={
                    ("gen-1", 1, "custom/speed/medium/warm#0")
                },
            )
        self.assertEqual(summary["capturedRowsBySchema"]["allocations"], 1)
        self.assertEqual(summary["capturedRowsBySchema"]["vm-tracker"], 0)
        with self.assertRaisesRegex(publisher.PublicationError, "VM Tracker tables"):
            publisher._memory_trace_export_evidence(summary["capturedRowsBySchema"])

    def test_trace_summary_resolves_cpu_profiler_and_reused_signpost_values(self) -> None:
        trace = self.root / "profile.trace"
        trace.mkdir()

        def fake_export(command, **_kwargs):
            output = Path(command[command.index("--output") + 1])
            xpath = command[command.index("--xpath") + 1]
            if "cpu-profile" in xpath:
                xml = """<trace-query-result>
                <process id='target' pid='4242'/>
                <row><process ref='target'/><sample-time id='t1'>1000000</sample-time><cycle-weight id='w1'>100</cycle-weight></row>
                <row><process ref='target'/><sample-time>4000000</sample-time><cycle-weight>200</cycle-weight></row>
                </trace-query-result>"""
            else:
                xml = """<trace-query-result>
                <process id='target' pid='4242'/>
                <os-log-metadata id='cold' fmt='runID= profile-run generationID= gen-1 takeIndex= 1 cell= custom/speed/medium/cold#0'/>
                <os-log-metadata id='warm' fmt='runID= profile-run generationID= gen-2 takeIndex= 2 cell= custom/speed/medium/warm#0'/>
                <row><process ref='target'/><os-log-metadata ref='cold'/></row>
                <row><process ref='target'/><os-log-metadata ref='warm'/></row>
                </trace-query-result>"""
            output.write_text(xml, encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with mock.patch.object(publisher.subprocess, "run", side_effect=fake_export):
            summary = publisher.extract_trace_data_summary(
                trace, {"cpu-profile", "os-signpost"}, run_id="profile-run",
                target_pid=4242,
                expected_correlations={
                    ("gen-1", 1, "custom/speed/medium/cold#0"),
                    ("gen-2", 2, "custom/speed/medium/warm#0"),
                },
            )
        self.assertEqual(summary["cpuSampleCount"], 2)
        self.assertEqual(summary["cpuCycleWeight"], 300)
        self.assertEqual(summary["cpuSampleSpanMS"], 3.0)
        self.assertEqual(summary["correlatedSignpostEventCount"], 2)

    def test_trace_summary_rejects_signposts_without_cpu_profile(self) -> None:
        trace = self.root / "profile.trace"
        trace.mkdir()

        def fake_export(command, **_kwargs):
            output = Path(command[command.index("--output") + 1])
            output.write_text(
                """<trace-query-result><process id='target' pid='4242'/>
                <row><process ref='target'/><string>runID=profile-run generationID=gen-1 takeIndex=1 cell=custom/speed/medium/warm#0</string></row>
                </trace-query-result>""",
                encoding="utf-8",
            )
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with (
            mock.patch.object(publisher.subprocess, "run", side_effect=fake_export),
            self.assertRaisesRegex(publisher.PublicationError, "CPU Profiler or Time Profiler"),
        ):
            publisher.extract_trace_data_summary(
                trace, {"os-signpost"}, run_id="profile-run", target_pid=4242,
                expected_correlations={
                    ("gen-1", 1, "custom/speed/medium/warm#0")
                },
            )

    def test_trace_rejects_wrong_or_split_correlation_rows(self) -> None:
        trace = self.root / "profile.trace"
        trace.mkdir()

        def fake_export(command, **_kwargs):
            output = Path(command[command.index("--output") + 1])
            xpath = command[command.index("--xpath") + 1]
            if "time-profile" in xpath:
                xml = """<trace-query-result><row><process pid='4242'/><sample-time>1</sample-time><weight>1</weight></row></trace-query-result>"""
            else:
                xml = """<trace-query-result>
                <row><process pid='4242'/><string>runID=profile-run generationID=wrong takeIndex=1 cell=custom/speed/medium/warm#0</string></row>
                <row><process pid='4242'/><string>runID=profile-run generationID=gen-1</string></row>
                <row><process pid='4242'/><string>takeIndex=1 cell=custom/speed/medium/warm#0</string></row>
                </trace-query-result>"""
            output.write_text(xml, encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with (
            mock.patch.object(publisher.subprocess, "run", side_effect=fake_export),
            self.assertRaisesRegex(publisher.PublicationError, "correlated signpost"),
        ):
            publisher.extract_trace_data_summary(
                trace, {"time-profile", "os-signpost"}, run_id="profile-run",
                target_pid=4242,
                expected_correlations={
                    ("gen-1", 1, "custom/speed/medium/warm#0")
                },
            )

    @staticmethod
    def interval_export(*, generated_tokens: int, dropped: int = 0) -> str:
        """An os-signpost-interval export shaped like xctrace's: a column schema,
        values defined once with `id` and reused with `ref`, one correlated
        generation-stream interval and the engine loop inside it."""
        message = "runID=profile-run generationID=gen-1 takeIndex=1 cell=custom/speed/medium/warm#0"
        columns = ("start", "duration", "process", "subsystem", "category", "name", "start-message")
        schema = "".join(f"<col><mnemonic>{name}</mnemonic></col>" for name in columns)
        rows = [
            # The take window, correlated by its start message.
            "<row><start-time>1000000</start-time><duration>900000000</duration>"
            "<process id='p' fmt='vocello (4242)'><pid id='pp' fmt='4242'>4242</pid></process>"
            "<subsystem id='se' fmt='com.qwenvoice.engine'>com.qwenvoice.engine</subsystem>"
            "<category id='cg' fmt='generation'>generation</category>"
            "<signpost-name fmt='Native Generation Stream'>Native Generation Stream</signpost-name>"
            f"<os-log-metadata fmt='{message}'/></row>",
            # A prewarm loop interval before the window: an orphan.
            "<row><start-time>0</start-time><duration>100000</duration><process ref='p'/>"
            "<subsystem id='sq' fmt='com.qwenvoice.engine.qwen3'>com.qwenvoice.engine.qwen3</subsystem>"
            "<category ref='cg'/><signpost-name fmt='Talker Forward'>Talker Forward</signpost-name>"
            "<sentinel/></row>",
            # Another process's interval inside the window is not the target's.
            "<row><start-time>2000000</start-time><duration>100000</duration>"
            "<process fmt='other (9999)'><pid fmt='9999'>9999</pid></process>"
            "<subsystem ref='sq'/><category ref='cg'/>"
            "<signpost-name fmt='Talker Forward'>Talker Forward</signpost-name><sentinel/></row>",
        ]
        names: list[str] = []
        for _ in range(generated_tokens + 1):
            for name, multiplicity in publisher.trace_intervals.LOOP_STEP_INTERVALS.items():
                names.extend([name] * multiplicity)
            names.append("Token Read")
        loop_names = [name for name in names if name != "Token Read"]
        drop_from = len(loop_names) - dropped
        kept = []
        loop_seen = 0
        for name in names:
            if name != "Token Read":
                loop_seen += 1
                if loop_seen > drop_from:
                    continue
            kept.append(name)
        defined: set[str] = set()
        start = 10_000_000
        for index, name in enumerate(kept):
            key = name.replace(" ", "-").lower()
            name_element = (
                f"<signpost-name ref='{key}'/>" if key in defined
                else f"<signpost-name id='{key}' fmt='{name}'>{name}</signpost-name>"
            )
            defined.add(key)
            duration = "<duration ref='d'/>" if index else "<duration id='d'>400000</duration>"
            rows.append(
                f"<row><start-time>{start}</start-time>{duration}<process ref='p'/>"
                f"<subsystem ref='sq'/><category ref='cg'/>{name_element}<sentinel/></row>"
            )
            start += 1_000_000
        return (
            "<trace-query-result><node>"
            f"<schema name='os-signpost-interval'>{schema}</schema>"
            + "".join(rows)
            + "</node></trace-query-result>"
        )

    def extract_intervals(self, *, dropped: int = 0, require_complete: bool = True) -> dict:
        trace = self.root / "profile-intervals.trace"
        trace.mkdir(exist_ok=True)
        message = "runID=profile-run generationID=gen-1 takeIndex=1 cell=custom/speed/medium/warm#0"

        def fake_export(command, **_kwargs):
            output = Path(command[command.index("--output") + 1])
            xpath = command[command.index("--xpath") + 1]
            if "time-profile" in xpath:
                xml = """<trace-query-result>
                <row><process pid='4242'/><sample-time>1000000</sample-time><weight>1000000</weight></row>
                <row><process pid='4242'/><sample-time>4000000</sample-time><weight>1000000</weight></row>
                </trace-query-result>"""
            elif "os-signpost-interval" in xpath:
                xml = self.interval_export(generated_tokens=2, dropped=dropped)
            else:
                xml = f"""<trace-query-result><node>
                <schema name='os-signpost'><col><mnemonic>time</mnemonic></col>
                <col><mnemonic>event-type</mnemonic></col><col><mnemonic>process</mnemonic></col>
                <col><mnemonic>message</mnemonic></col></schema>
                <row><event-time>1000000</event-time><event-type id='b' fmt='Begin'>Begin</event-type>
                <process pid='4242'/><os-log-metadata fmt='{message}'/></row>
                <row><event-time>901000000</event-time><event-type fmt='End'>End</event-type>
                <process pid='4242'/><os-log-metadata fmt='{message}'/></row>
                <row><event-time>5000000</event-time><event-type fmt='Event'>Event</event-type>
                <process pid='4242'/><os-log-metadata fmt='{message}'/></row>
                </node></trace-query-result>"""
            output.write_text(xml, encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with mock.patch.object(publisher.subprocess, "run", side_effect=fake_export):
            return publisher.extract_trace_data_summary(
                trace, {"time-profile", "os-signpost", "os-signpost-interval"},
                run_id="profile-run", target_pid=4242,
                expected_correlations={("gen-1", 1, "custom/speed/medium/warm#0")},
                take_expectations={
                    ("gen-1", 1, "custom/speed/medium/warm#0"): {
                        "generatedTokens": 2,
                        "endReason": "eos",
                        "timingsMS": {"qwen_talker_forward_total": 1},
                    },
                },
                require_complete_intervals=require_complete,
            )

    def test_trace_summary_publishes_per_take_loop_interval_statistics(self) -> None:
        summary = self.extract_intervals()
        # The window row, the prewarm orphan and 3 steps of 36 + Token Read.
        self.assertEqual(summary["capturedRowsBySchema"]["os-signpost-interval"], 2 + 3 * 37)
        self.assertEqual(summary["signpostIntervalCount"], 2 + 3 * 37)
        self.assertEqual(
            (summary["signpostBeginCount"], summary["signpostEndCount"], summary["signpostPointCount"]),
            (1, 1, 1),
        )
        self.assertEqual(summary["orphanIntervalCount"], 1)
        self.assertEqual(summary["signpostSummaryVersion"], 1)
        take = summary["intervalStatistics"]["takes"][0]
        self.assertEqual(take["takeIndex"], 1)
        self.assertEqual(take["loopSteps"], 3)
        self.assertEqual(take["expectedLoopIntervalCount"], 108)
        self.assertEqual(take["loopIntervalCount"], 108)
        self.assertTrue(take["complete"])
        self.assertEqual(take["intervals"]["tokenRead"]["count"], 3)
        self.assertEqual(take["intervals"]["talkerForward"]["totalMS"], 1.2)
        self.assertEqual(take["witness"]["comparedCount"], 1)
        self.assertEqual(take["witness"]["outsideToleranceCount"], 0)
        self.assertEqual(take["windowMS"], 900.0)

    def test_profile_takes_are_sized_by_their_own_end_reason(self) -> None:
        diagnostics = self.root / "profile-end-reason"
        (diagnostics / "engine").mkdir(parents=True)
        correlations = {
            ("gen-eos", 1, "custom/speed/medium/cold#0"),
            ("gen-cap", 2, "custom/speed/medium/warm#0"),
        }
        rows = []
        for generation_id, reason in (("gen-eos", "eos"), ("gen-cap", "token_cap")):
            row = engine_row(generation_id)
            row["timingsMS"]["qwen_generated_code_count"] = 42
            row["notes"]["generation_end_reason"] = reason
            rows.append(row)
        path = diagnostics / "engine" / "generations.jsonl"

        def write(candidates: list[dict]) -> None:
            path.write_text(
                "".join(json.dumps(row) + "\n" for row in candidates), encoding="utf-8"
            )

        write(rows)
        args = SimpleNamespace(diagnostics=diagnostics)
        expectations = publisher._profile_take_expectations(args, correlations)
        self.assertEqual(
            {correlation[0]: expectation["endReason"] for correlation, expectation in expectations.items()},
            {"gen-eos": "eos", "gen-cap": "token_cap"},
        )
        # A capped take ran exactly its tokens, so a lossless trace of it is
        # complete at 36 x tokens.
        takes, _ = publisher.trace_intervals.interval_statistics(
            correlated={}, engine_intervals=[], expectations=expectations,
        )
        self.assertEqual([take["loopSteps"] for take in takes], [43, 42])

        for reason in (None, "failed"):
            with self.subTest(reason=reason):
                if reason is None:
                    rows[1]["notes"].pop("generation_end_reason", None)
                else:
                    rows[1]["notes"]["generation_end_reason"] = reason
                write(rows)
                with self.assertRaises(publisher.PublicationError):
                    publisher._profile_take_expectations(args, correlations)

    def test_a_macos_trace_short_of_the_loop_intervals_is_refused(self) -> None:
        with self.assertRaises(publisher.PublicationError):
            self.extract_intervals(dropped=1)
        # The same trace without the requirement: the take is one interval short.
        summary = self.extract_intervals(dropped=1, require_complete=False)
        take = summary["intervalStatistics"]["takes"][0]
        self.assertEqual((take["loopIntervalCount"], take["expectedLoopIntervalCount"]), (107, 108))
        self.assertFalse(take["complete"])


if __name__ == "__main__":
    unittest.main()
