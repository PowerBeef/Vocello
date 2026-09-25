#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tempfile
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "benchmark_history.py"
SPEC = importlib.util.spec_from_file_location("benchmark_history", SCRIPT)
assert SPEC and SPEC.loader
history = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = history
SPEC.loader.exec_module(history)
import publish_benchmark_history as publisher


DIGEST = "d" * 64
# Frozen copies of two published records (audit #94): a new publication or a
# pruned record never changes a test input.
FROZEN_RECORDS = Path(__file__).resolve().parent / "fixtures" / "benchmark-records"


def generation_take(index: int = 1, *, length: str = "long", warning: bool = False) -> dict:
    return {
        "takeIndex": index,
        "generationID": f"generation-{index}",
        "cell": f"custom/pro_custom_speed/warm/{length}",
        "mode": "custom",
        "modelID": "pro_custom_speed",
        "modelRepository": "mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-4bit",
        "modelRevision": "f35faf19b0cc2160865af64ecf0f22f83d335135",
        "modelArtifactVersion": "2026.04.05.2",
        "modelQuantization": "4-bit",
        "modelIntegrityDigest": "8" * 64,
        "runtimeProfileSignature": "pro_custom_speed",
        "fixtureDigest": "not-applicable",
        "variant": "speed",
        "warmState": "warm",
        "length": length,
        "finishReason": "completed",
        "status": "passed",
        "layerCompleteness": "complete",
        "layers": ["engine", "app"],
        "durationSeconds": 1.5,
        "metrics": {"rtf": 2.0, "tokensPerSecond": 25.0, "ttfcMS": 500.0},
        "output": {
            "readableWAV": True,
            "atomicPublish": True,
            "durationSeconds": 3.0,
            "sampleRate": 24000,
            "channels": 1,
            "frames": 72000,
            "fileDigest": DIGEST,
        },
        "audioQC": {
            "algorithmVersion": 2,
            "verdict": "warn" if warning else "pass",
            "instabilityVerdict": "pass",
            "writtenOutputVerdict": "warn" if warning else "pass",
            "warningCodes": ["long-silence"] if warning else [],
            "metrics": {"longestSilenceMS": 800.0 if warning else 100.0},
        },
        "thermalState": "nominal",
        "warnings": [],
    }


def record_fixture(
    *,
    run_id: str = "macos-bench-20260712-120000",
    kind: str = "ui-generation",
    platform: str = "macos",
    profile: str = "mac-mini-m2-8gb",
    takes: list[dict] | None = None,
    dirty: bool = False,
) -> dict:
    selected_takes = copy.deepcopy(takes if takes is not None else [generation_take()])
    return {
        "schemaVersion": 1,
        "run": {
            "id": run_id,
            "kind": kind,
            "platform": platform,
            "label": "fixture",
            "startedAt": "2026-07-12T12:00:00Z",
            "finishedAt": "2026-07-12T12:01:00Z",
            "durationSeconds": 60,
            "status": "passed",
            "matrixScope": "canonical" if len(selected_takes) == 29 else "focused",
            "classification": "exploratory" if dirty else "focused",
            "warnings": [],
        },
        "hardware": {
            "profileID": profile,
            "modelIdentifier": "Mac14,3" if platform == "macos" else "iPhone18,1",
            "marketingName": "Mac mini (M2, 8 GB)" if platform == "macos" else "iPhone 17 Pro",
            "chip": "Apple M2" if platform == "macos" else "Apple A19 Pro",
            "memoryBytes": 8_589_934_592 if platform == "macos" else 12_884_901_888,
            "cpuCores": 8 if platform == "macos" else 6,
            "performanceCores": 4 if platform == "macos" else 2,
            "efficiencyCores": 4,
            "osName": "macOS" if platform == "macos" else "iOS",
            "osVersion": "26.5.2",
            "osBuild": "25F84" if platform == "macos" else "23F84",
            "thermalState": "nominal",
            "lowPowerMode": False,
            "transport": "local" if platform == "macos" else "local-network",
            "loadAverage1M": 1.0,
            "freeStorageBytes": 1_000_000,
            "uptimeSeconds": 100.0,
        },
        "source": {
            "commit": "a" * 40,
            "dirty": dirty,
            "changedPaths": ["Sources/Example.swift"] if dirty else [],
            "workspaceFingerprint": "1" * 64,
            "preFingerprint": "1" * 64,
            "postFingerprint": "1" * 64,
            "fingerprintsMatch": True,
        },
        "toolchain": {
            "xcodeVersion": "26.6",
            "xcodeBuild": "17F113",
            "swiftVersion": "6.3.3",
            "sdkName": "macosx" if platform == "macos" else "iphoneos",
            "sdkVersion": "26.6",
            "optimization": "-O",
            "appVersion": "2.1.0",
            "appBuild": "1",
            "executableUUIDs": {"Vocello": "11111111-1111-1111-1111-111111111111"},
            "executableHashes": {"Vocello": "2" * 64},
        },
        "inputs": {
            "contractHash": "3" * 64,
            "dependencyLockHash": "4" * 64,
            "projectInputHash": "5" * 64,
            "harnessHash": "6" * 64,
            "matrixHash": "7" * 64,
            "corpusHash": "not-applicable",
        },
        "models": [{
            "mode": "custom",
            "modelID": "mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-4bit",
            "variant": "speed",
            "quantization": "4-bit",
            "revision": "f35faf19b0cc2160865af64ecf0f22f83d335135",
            "artifactVersion": "2026.04.05.2",
            "integrityDigest": "8" * 64,
            "runtimeProfileSignature": "pro_custom_speed",
            "fixtureDigest": "not-applicable",
        }],
        "evidence": {
            "validatorSchemaVersion": 1,
            "telemetrySchemaVersion": 7,
            "qcAlgorithmVersion": 2,
            "validatorPassed": True,
            "crashDeltaPassed": True,
            "crashCount": 0,
            "expectedTakeCount": len(selected_takes),
            "actualTakeCount": len(selected_takes),
            "resultBundleDigest": "9" * 64,
            "rawTelemetryDigest": "c" * 64,
            "screenshotDigests": [{"name": "final.png", "digest": "e" * 64}],
        },
        "takes": selected_takes,
        "comparison": {
            "comparable": not dirty,
            "baselineRunID": None,
            "deltas": {},
        },
        "listening": {"status": "not-performed", "note": "", "annotatedAt": None},
    }


M6_HARDWARE = {
    "profileID": "mac-mini-m6-16gb",
    "modelIdentifier": "Mac18,5",
    "marketingName": "Mac mini (M6, 16 GB)",
    "chip": "Apple M6",
    "memoryBytes": 17_179_869_184,
    "cpuCores": 12,
    "performanceCores": 6,
    "efficiencyCores": 6,
}


def quality_v3_language_fixture(run_id: str) -> dict:
    """A schema-v3 language record that satisfies the memory and quality contracts."""
    record = record_fixture(run_id=run_id, kind="language")
    record["schemaVersion"] = 3
    record["evidence"].update({
        "telemetrySchemaVersion": 8,
        "memoryContractVersion": 1,
        "memoryQualified": True,
        "sampleSidecarCount": 1,
        "sampleSidecarsDigest": "a" * 64,
    })
    take = record["takes"][0]
    take["memoryStatus"] = "qualified"
    take["sampleSidecarDigest"] = "b" * 64
    take["metrics"].update({key: 0.0 for key in history.MEMORY_REQUIRED_METRICS})
    take["metrics"].update({
        "samplerCoverage": 1.0,
        "samplerSampleCount": 10.0,
        "samplerBoundarySampleCount": 8.0,
        "samplerPeriodicSampleCount": 1.0,
        "gpuRecommendedWorkingSetMB": 4096.0,
        "mlxActivePeakMB": 100.0,
        "mlxCachePeakMB": 10.0,
        "mlxPeakMB": 110.0,
    })
    take["qualityRegistryOutcome"] = "pass"
    take["qualityRegistryRequiredGates"] = sorted(history.QUALITY_FAST_GATES)
    return record


def trace_summary(take_count: int = 1) -> dict:
    return {
        "artifact": "build/profiles/fixture.trace",
        "capturedDataRowCount": 16,
        "capturedRowsBySchema": {"cpu-profile": 12, "os-signpost": 4},
        "correlatedSignpostEventCount": take_count,
        "correlationFieldsVerified": True,
        "cpuCycleWeight": 100,
        "cpuSampleCount": 12,
        "cpuSampleSpanMS": 9.0,
        "processCount": 2,
        "schemaCount": 2,
        "signpostEventCount": 4,
        "signpostSchemaCount": 1,
        "tableCount": 2,
        "targetPIDVerified": True,
        "targetProcess": "vocello",
        "tocDigest": "f" * 64,
    }


def telemetry_overhead_takes() -> list[dict]:
    rotations = (
        ("off", "lightweight", "verbose"),
        ("lightweight", "verbose", "off"),
        ("verbose", "off", "lightweight"),
    )
    takes = []
    for rotation, modes in enumerate(rotations, start=1):
        for order, telemetry_mode in enumerate(modes, start=1):
            for measured in range(1, 3):
                take = generation_take(len(takes) + 1, length="medium")
                for key in ("layerCompleteness", "layers", "output", "audioQC"):
                    take.pop(key)
                take.update({
                    "cell": f"rotation-{rotation}/order-{order}/{telemetry_mode}/take-{measured}",
                    "modelID": "pro_custom_speed",
                    "warmState": "warm",
                    "finishReason": "completed",
                    "thermalState": "nominal",
                    "metrics": {
                        "rtf": 1.0, "ttfcMS": 10.0, "audioSeconds": 2.0,
                        "loadAverage1M": 1.0, "freeStorageBytes": 1_000_000.0,
                        "uptimeSeconds": 100.0, "lowPowerMode": 0.0,
                    },
                    "output": {
                        "readableWAV": True, "atomicPublish": True,
                        "durationSeconds": 2.0, "fileDigest": f"{rotation}{measured}" * 32,
                    },
                })
                takes.append(take)
    return takes


def prosody_take(run_id: str) -> dict:
    return {
        "takeIndex": 1,
        "generationID": f"{run_id}-analysis",
        "cell": "prosody-calibration/corpus",
        "mode": "not-applicable",
        "modelID": "not-applicable",
        "variant": "not-applicable",
        "warmState": "not-applicable",
        "length": "not-applicable",
        "finishReason": "completed",
        "status": "passed",
        "metrics": {
            "goodClipCount": 2.0, "badClipCount": 2.0,
            "targetFalsePositiveRate": 0.05, "observedFalsePositiveRate": 0.0,
            "observedTruePositiveRate": 0.5, "goodFlagRate": 0.0, "badFlagRate": 0.5,
            "monotoneF0StdThresholdHz": 1.0,
            "monotoneTurningPointsThresholdPerSecond": 1.0,
            "rushedSyllableRateThresholdHz": 10.0, "rushedMaximumPauseRatio": 0.1,
            "flatEnvelopeRoughnessThreshold": 0.1, "flatRateCVThreshold": 0.1,
            "maximumPauseThresholdSeconds": 1.0, "maximumPauseRatioThreshold": 0.5,
        },
        "warnings": [],
    }


def fixed_runtime_hardware(platform: str, _profile: dict) -> dict:
    """What the live host probes return, without running them.

    `build_record` always probes the host (`swift -e` on the Mac, `devicectl`
    for a paired iPhone) and `merge_missing` discards the answer whenever the
    fixture already carries the key, so the unit tests never need the host:
    the probes' own parsing is covered by `HostProbeParsingTests`."""
    if platform == "macos":
        return {
            "osName": "macOS", "osVersion": "26.5.2", "osBuild": "25F84",
            "thermalState": "nominal", "lowPowerMode": False, "transport": "local",
            "loadAverage1M": 1.0, "freeStorageBytes": 1_000_000, "uptimeSeconds": 100.0,
        }
    return {
        "osName": "iOS", "thermalState": "unknown", "lowPowerMode": None,
        "transport": "physical-device",
    }


class HostProbeParsingTests(unittest.TestCase):
    """The only host probes `build_record` runs, parsed from canned output."""

    def test_mac_probe_parses_thermal_state_and_low_power(self) -> None:
        answers = {
            ("sw_vers", "-productName"): "macOS",
            ("sw_vers", "-productVersion"): "26.6.2",
            ("sw_vers", "-buildVersion"): "25G99",
        }

        def run_command(arguments: list[str], *, check: bool = True) -> str:
            if arguments[0] == "swift":
                return swift_answer
            return answers[tuple(arguments)]

        for swift_answer, thermal, low_power in (
            ("2\n1", "serious", True),
            ("0\n0", "nominal", False),
            ("7\n0", "unknown", False),
            ("", "unknown", False),
        ):
            with self.subTest(swift=swift_answer), mock.patch.object(history, "run_command", side_effect=run_command):
                result = history.mac_runtime_hardware()
            self.assertEqual(
                (result["osName"], result["osVersion"], result["osBuild"]),
                ("macOS", "26.6.2", "25G99"),
            )
            self.assertEqual(result["thermalState"], thermal)
            self.assertIs(result["lowPowerMode"], low_power)
            self.assertEqual(result["transport"], "local")
            for key in ("loadAverage1M", "freeStorageBytes", "uptimeSeconds"):
                self.assertIsInstance(result[key], (int, float))

    def test_ios_probe_reads_exactly_one_matching_device(self) -> None:
        profile = {"modelIdentifier": "iPhone18,1"}

        def device(transport: str) -> dict:
            return {
                "deviceProperties": {"osVersionNumber": "26.6.1", "osBuildUpdate": "23G83"},
                "connectionProperties": {"transportType": transport},
            }

        def fake_devicectl(devices: list[dict], returncode: int = 0):
            def run(command, **_kwargs):
                self.assertIn("iPhone18,1", " ".join(command))
                output = Path(command[command.index("--json-output") + 1])
                output.write_text(json.dumps({"result": {"devices": devices}}), encoding="utf-8")
                return SimpleNamespace(returncode=returncode)

            return run

        base = {"osName": "iOS", "thermalState": "unknown", "lowPowerMode": None}
        for name, devices, returncode, expected in (
            ("wired", [device("wired")], 0,
             {**base, "transport": "wired", "osVersion": "26.6.1", "osBuild": "23G83"}),
            ("network", [device("localNetwork")], 0,
             {**base, "transport": "local-network", "osVersion": "26.6.1", "osBuild": "23G83"}),
            ("other-transport", [device("bluetooth")], 0,
             {**base, "transport": "physical-device", "osVersion": "26.6.1", "osBuild": "23G83"}),
            ("ambiguous", [device("wired"), device("wired")], 0, {**base, "transport": "physical-device"}),
            ("failed", [device("wired")], 1, {**base, "transport": "physical-device"}),
        ):
            with self.subTest(name=name), mock.patch.object(
                history.subprocess, "run", side_effect=fake_devicectl(devices, returncode)
            ):
                self.assertEqual(history.ios_runtime_hardware(profile), expected)


class BenchmarkHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.runs = self.root / "runs"
        self.index = self.root / "HISTORY.md"
        self.schema = self.root / "schema-v1.json"
        self.schema.write_bytes(history.SCHEMA_PATH.read_bytes())
        self.patches = [
            mock.patch.object(history, "RUNS_ROOT", self.runs),
            mock.patch.object(history, "SCHEMA_PATH", self.schema),
            mock.patch.object(history, "HISTORY_PATH", self.index),
            # Never query the host (or a paired iPhone) from a unit test.
            mock.patch.object(history, "default_runtime_hardware", side_effect=fixed_runtime_hardware),
        ]
        for patcher in self.patches:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patches):
            patcher.stop()
        self.temporary.cleanup()

    def write_manifest(self, payload: dict, name: str = "artifact") -> Path:
        directory = self.root / name
        directory.mkdir()
        (directory / "benchmark-evidence.json").write_text(
            json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8"
        )
        return directory

    def publish(self, record: dict, name: str = "artifact") -> Path:
        return history.record_manifest(self.write_manifest({"historyRecord": record}, name))

    def test_git_status_paths_preserve_leading_dot_on_first_entry(self) -> None:
        raw = (
            " M .claude/rules/backend-mlx.md\0"
            " M CLAUDE.md\0"
            "?? benchmarks/runs/example.json\0"
            "?? .local-fixture\0"
        )
        self.assertEqual(
            history.parse_git_status_paths(raw),
            [".claude/rules/backend-mlx.md", ".local-fixture", "CLAUDE.md"],
        )

    def test_rebuild_index_validates_each_unchanged_record_once(self) -> None:
        # Audit #73: rebuild-index validated the whole registry twice and
        # recomputed comparison keys once per pair of records.
        self.publish(record_fixture(run_id="once-a-20260712"), "once-a")
        second = record_fixture(run_id="once-b-20260712")
        second["takes"][0]["generationID"] = "generation-once-b"
        self.publish(second, "once-b")
        with (
            mock.patch.object(history, "validate_record", wraps=history.validate_record) as validated,
            mock.patch.object(history, "comparison_key", wraps=history.comparison_key) as keyed,
        ):
            history.rebuild_index(check=True)
        self.assertEqual(validated.call_count, 2)
        # Linear, not per pair: per record one key in its validation, one for the
        # reconciliation and one for its fixed-point check.
        self.assertEqual(keyed.call_count, 3 * 2)

    def test_record_is_atomic_valid_and_idempotent(self) -> None:
        directory = self.write_manifest({"historyRecord": record_fixture()})
        first = history.record_manifest(directory)
        before = first.read_bytes()
        second = history.record_manifest(directory)
        self.assertEqual(first, second)
        self.assertEqual(before, second.read_bytes())
        history.validate_all()
        self.assertIn("macos-bench-20260712-120000", self.index.read_text())
        self.assertFalse(any(path.name.startswith(".") for path in first.parent.iterdir()))

    def test_full_29_take_memory_record_uses_bounded_canonical_storage(self) -> None:
        # Match the production macOS UI shape: 29 exact takes, 11 aggregate
        # cells, and the complete per-take performance/memory/frontend payload.
        # The intentionally dirty source list also protects exploratory runs,
        # where exact changed-path provenance is larger than a clean baseline.
        metric_keys = {
            "alignedAppSampleCoverage", "alignedEngineSampleCoverage",
            "alignedProcessSampleCount", "alignedProcessSampleCoverage",
            "audioSeconds", "blockIOOperations", "chunksForwarded", "chunksReceived",
            "contextSwitches", "continuityFailures", "cpuSystemSeconds", "cpuUserSeconds",
            "decodeSpeedupX", "decodeWallSeconds", "delayedHeartbeatCount", "finalizationMS",
            "firstChunkToPlaybackScheduledMS", "generatedTokens",
            "gpuRecommendedWorkingSetMB", "gpuWorkingSetUsageRatioPeak",
            "heartbeatCoverage", "maximumPressureLevel", "maximumTrimLevel",
            "memoryExitCount", "memoryPressureEventCount", "memoryTimeToPeakMS",
            "memoryTrimCount", "memoryWarningCount", "minimumQueueDurationMS",
            "mlxActivePeakMB", "mlxCachePeakMB", "mlxPeakMB", "modelLoadMS",
            "pageFaults", "peakCompressedMB", "peakGPUAllocatedMB",
            "peakPhysicalFootprintMB", "peakResidentMB", "physicalFootprintDeltaMB",
            "physicalFootprintEndMB", "physicalFootprintStartMB", "playbackScheduledMS",
            "requestToFirstChunkMS", "residentDeltaMB", "residentEndMB",
            "requestWallSeconds", "residentStartMB", "rtf", "rtfAppEndToEnd", "samplerBoundarySampleCount",
            "samplerCaptureFailureCount", "samplerCoverage",
            "samplerEffectiveMedianIntervalMS", "samplerMaximumDriftMS",
            "samplerMaximumLatenessMS", "samplerMissedDeadlineCount",
            "samplerPeriodicSampleCount", "samplerSampleCount",
            "samplerTargetIntervalMS", "startBufferDepth", "submitToCompletedMS",
            "submitToFirstChunkMS", "tokensPerSecond", "transportChunkGaps",
            "transportDuplicateChunks", "transportOutOfOrderChunks",
            "uiMaximumDelayedHeartbeatMS", "underruns",
        }
        zero_metrics = {
            "samplerCaptureFailureCount", "memoryWarningCount", "memoryExitCount",
            "memoryPressureEventCount", "memoryTrimCount", "maximumPressureLevel",
            "maximumTrimLevel", "continuityFailures", "underruns", "transportChunkGaps",
            "transportDuplicateChunks", "transportOutOfOrderChunks",
        }
        coverage_metrics = {
            "samplerCoverage", "alignedProcessSampleCoverage",
            "alignedEngineSampleCoverage", "alignedAppSampleCoverage", "heartbeatCoverage",
        }
        runtime_signature = (
            "qwen3_tts|custom_voice|4bit|24000|qwen3_tts_tokenizer_12hz|"
            "auto,chinese,english,french,german,italian,japanese,korean,portuguese,russian,spanish"
        )
        cell_counts = (1, 3, 3, 3, 1, 3, 3, 3, 3, 3, 3)
        takes: list[dict] = []
        for cell_index, count in enumerate(cell_counts, start=1):
            for repetition in range(1, count + 1):
                take_index = len(takes) + 1
                length = ("short", "medium", "long")[cell_index % 3]
                take = generation_take(take_index, length=length)
                take.update({
                    "cell": f"custom/cell-{cell_index:02d}/warm/{length}#{repetition}",
                    "layers": ["engine", "engine-service", "app", "merged"],
                    "memoryStatus": "qualified",
                    "playbackStartSource": "finalFile",
                    "runtimeProfileSignature": runtime_signature,
                    "sampleSidecarDigest": f"{take_index:064x}",
                })
                take["metrics"] = {key: 1.0 for key in metric_keys}
                take["metrics"].update({key: 0.0 for key in zero_metrics})
                take["metrics"].update({key: 1.0 for key in coverage_metrics})
                takes.append(take)

        record = record_fixture(
            run_id="full-memory-v2-regression", takes=takes, dirty=True,
        )
        record["schemaVersion"] = 2
        record["models"][0]["runtimeProfileSignature"] = runtime_signature
        record["source"]["changedPaths"] = [
            f"Sources/Generated/TelemetryEvidenceComponent{index:03d}WithLongName.swift"
            for index in range(320)
        ]
        record["evidence"].update({
            "telemetrySchemaVersion": 8,
            "memoryContractVersion": 1,
            "memoryQualified": True,
            "sampleSidecarCount": 58,
            "sampleSidecarsDigest": "a" * 64,
        })

        directory = self.write_manifest({"historyRecord": record}, "full-memory-v2")
        path = history.record_manifest(directory)
        stored = path.read_bytes()
        published = json.loads(stored)

        # This is the exact regression: presentation whitespace alone would
        # exceed the contract, while no allowlisted evidence needs removing.
        pretty = (json.dumps(published, indent=2, sort_keys=True) + "\n").encode()
        self.assertGreater(len(pretty), history.MAX_RECORD_BYTES)
        self.assertLessEqual(len(stored), history.MAX_RECORD_BYTES)
        self.assertEqual(stored, history.stored_json_bytes(published))
        self.assertEqual(len(published["takes"]), 29)
        self.assertEqual(len(published["cells"]), 11)
        self.assertEqual(set(published["takes"][0]["metrics"]), metric_keys)
        self.assertEqual(set(published["cells"][0]["statistics"]), metric_keys)
        self.assertIn("output", published["takes"][0])
        self.assertIn("audioQC", published["takes"][0])

        before = stored
        self.assertEqual(history.record_manifest(directory), path)
        self.assertEqual(path.read_bytes(), before)
        history.validate_all()

    def test_take_seed_is_optional_but_must_be_uint64(self) -> None:
        valid = record_fixture(run_id="seed-valid")
        valid["takes"][0]["seed"] = (1 << 64) - 1
        path = self.publish(valid, "seed-valid")
        self.assertEqual(json.loads(path.read_text())["takes"][0]["seed"], (1 << 64) - 1)

        for index, seed in enumerate((True, -1, 1 << 64)):
            record = record_fixture(run_id=f"seed-invalid-{index}")
            record["takes"][0]["seed"] = seed
            with self.subTest(seed=seed), self.assertRaises(history.HistoryError):
                self.publish(record, f"seed-invalid-{index}")

    def test_take_playback_start_source_is_optional_and_typed(self) -> None:
        valid = record_fixture(run_id="playback-source-valid")
        valid["takes"][0]["playbackStartSource"] = "finalFile"
        path = self.publish(valid, "playback-source-valid")
        self.assertEqual(
            json.loads(path.read_text())["takes"][0]["playbackStartSource"],
            "finalFile",
        )

        invalid = record_fixture(run_id="playback-source-invalid")
        invalid["takes"][0]["playbackStartSource"] = "unknown"
        with self.assertRaisesRegex(history.HistoryError, "playbackStartSource"):
            self.publish(invalid, "playback-source-invalid")

    def test_language_independent_family_has_its_own_identity_and_metrics(self) -> None:
        valid = record_fixture(run_id="independent-valid", kind="language")
        valid["evidence"]["languageVerification"] = {
            **history.INDEPENDENT_VERIFICATION_IDENTITY,
            "families": ["whisper"],
            "independentRecognitionAlgorithm": "mlx-whisper-locked-decode-v1",
            "independentModelIdentitySHA256": "2" * 64,
            "hintCellsPassed": 1, "hintCellsExpected": 1,
            "outputCellsPassed": 1, "outputCellsExpected": 1, "negativeControlsConfirmed": 0,
        }
        valid["takes"][0].update({"accuracyMetric": "wordErrorRate", "accuracyThreshold": 0.15})
        valid["takes"][0]["metrics"].update({
            "independentWordErrorRate": 0.125, "independentCharacterErrorRate": 0.1,
            "independentPrimaryAccuracyScore": 0.125, "independentLanguageMatchScore": 0.97,
            "independentLanguagePass": 1.0, "independentAccuracyPass": 1.0,
            "independentRecognitionDurationSeconds": 0.4,
        })
        self.publish(valid, "independent-valid")

        mutations = {
            "apple identity for a whisper-only record": lambda record: record["evidence"]["languageVerification"].update(
                {"recognitionAlgorithm": "apple-speech-file-consensus-v2"}),
            "provenance without the family": lambda record: record["evidence"]["languageVerification"].__setitem__(
                "families", ["apple-speech"]),
            "missing model identity": lambda record: record["evidence"]["languageVerification"].pop(
                "independentModelIdentitySHA256"),
            "score above the gate": lambda record: record["takes"][0]["metrics"].update(
                {"independentWordErrorRate": 0.2, "independentPrimaryAccuracyScore": 0.2}),
            "in-app metrics without apple-speech": lambda record: record["takes"][0]["metrics"].update(
                {"wordErrorRate": 0.1}),
            "unsorted families": lambda record: record["evidence"]["languageVerification"].__setitem__(
                "families", ["whisper", "apple-speech"]),
        }
        for index, (label, mutate) in enumerate(mutations.items()):
            record = copy.deepcopy(valid)
            record["run"]["id"] = f"independent-invalid-{index}"
            mutate(record)
            with self.subTest(label=label), self.assertRaises(history.HistoryError):
                self.publish(record, f"independent-invalid-{index}")

        legacy = record_fixture(run_id="apple-legacy", kind="language")
        legacy["evidence"]["languageVerification"] = dict(history.APPLE_SPEECH_VERIFICATION_IDENTITY)
        legacy["takes"][0].update({"accuracyMetric": "wordErrorRate", "accuracyThreshold": 0.15})
        legacy["takes"][0]["metrics"].update({
            "wordErrorRate": 0.125, "characterErrorRate": 0.125, "primaryAccuracyScore": 0.125,
            "accuracyThreshold": 0.15, "languageMatchScore": 0.9, "outputLanguagePass": 1.0,
            "outputAccuracyPass": 1.0, "referenceTokenCount": 8.0, "hypothesisTokenCount": 8.0,
            "referenceCharacterCount": 32.0, "hypothesisCharacterCount": 32.0, "substitutions": 1.0,
            "insertions": 0.0, "deletions": 0.0, "characterSubstitutions": 4.0,
            "characterInsertions": 0.0, "characterDeletions": 0.0, "recognitionPassCount": 3.0,
            "recognitionDurationSeconds": 0.3,
        })
        self.publish(legacy, "apple-legacy")

    @staticmethod
    def _schema_v3_language_record(run_id: str) -> dict:
        """A schema-v3 language record: memory-qualified take with the quality identity."""
        record = record_fixture(run_id=run_id, kind="language")
        record["schemaVersion"] = 3
        record["evidence"].update({
            "telemetrySchemaVersion": 8,
            "memoryContractVersion": 1,
            "memoryQualified": True,
            "sampleSidecarCount": 1,
            "sampleSidecarsDigest": "a" * 64,
        })
        take = record["takes"][0]
        take["memoryStatus"] = "qualified"
        take["sampleSidecarDigest"] = "b" * 64
        take["metrics"].update({key: 0.0 for key in history.MEMORY_REQUIRED_METRICS})
        take["metrics"].update({
            "samplerCoverage": 1.0,
            "samplerSampleCount": 10.0,
            "samplerBoundarySampleCount": 8.0,
            "samplerPeriodicSampleCount": 1.0,
            "gpuRecommendedWorkingSetMB": 4096.0,
            "mlxActivePeakMB": 100.0,
            "mlxCachePeakMB": 10.0,
            "mlxPeakMB": 110.0,
        })
        take["qualityRegistryOutcome"] = "pass"
        take["qualityRegistryRequiredGates"] = sorted(history.QUALITY_FAST_GATES)
        return record

    def test_playback_capture_fields_are_v3_take_evidence(self) -> None:
        # A frozen schema-v3 macOS UI record (macos-xcui-benchmark-20260916-014846)
        # is the fixture: the capture fields join its takes without disturbing the
        # rest of the schema-v3 contract.
        base = json.loads((FROZEN_RECORDS / "macos-ui-generation-v3.json").read_text())
        self.assertEqual(base["schemaVersion"], 3)

        def with_capture(**overrides: object) -> dict:
            record = copy.deepcopy(base)
            take = record["takes"][0]
            take["playbackCaptureStatus"] = "captured"
            take["playbackCaptureDigest"] = "c" * 64
            take["metrics"].update({
                "playbackCaptureAlignmentMS": 137.2, "playbackCaptureResidualDBFS": -43.1,
                "playbackCaptureDropoutCount": 0.0, "playbackCaptureMaxGapMS": 0.0,
                "playbackCaptureFirstAudibleMS": 512.0, "playbackCaptureCoverage": 0.998,
                "playbackCaptureStepBurstPeakCount": 0.0,
            })
            take.update(overrides)
            record["cells"] = history.aggregate_cells(record["takes"])
            record["evidence"]["selectedEvidenceDigest"] = history.selected_evidence_digest(record)
            record["digest"] = history.record_digest(record)
            return record

        history.validate_record(with_capture())
        unavailable = with_capture(playbackCaptureStatus="unavailable")
        for key in list(unavailable["takes"][0]["metrics"]):
            if key.startswith("playbackCapture"):
                unavailable["takes"][0]["metrics"].pop(key)
        unavailable["takes"][0].pop("playbackCaptureDigest")
        unavailable["cells"] = history.aggregate_cells(unavailable["takes"])
        unavailable["evidence"]["selectedEvidenceDigest"] = history.selected_evidence_digest(unavailable)
        unavailable["digest"] = history.record_digest(unavailable)
        history.validate_record(unavailable)

        for label, record in (
            ("unknown status", with_capture(playbackCaptureStatus="heard")),
            ("digest on an unavailable take", with_capture(playbackCaptureStatus="unavailable")),
            ("comparison metrics without a capture", with_capture(playbackCaptureStatus="silent")),
        ):
            with self.subTest(label=label), self.assertRaises(history.HistoryError):
                history.validate_record(record)
        v2 = with_capture()
        v2["schemaVersion"] = 2
        for take in v2["takes"]:
            for key in ("qualityRegistryOutcome", "qualityRegistryRequiredGates", "qualityRegistryIssues"):
                take.pop(key, None)
        v2["cells"] = history.aggregate_cells(v2["takes"])
        v2["evidence"]["selectedEvidenceDigest"] = history.selected_evidence_digest(v2)
        v2["digest"] = history.record_digest(v2)
        with self.assertRaises(history.HistoryError):
            history.validate_record(v2)

    def test_language_negative_control_take_is_evidence_only_when_it_failed(self) -> None:
        valid = self._schema_v3_language_record("control-valid")
        valid["evidence"]["languageVerification"] = {
            **history.INDEPENDENT_VERIFICATION_IDENTITY,
            "families": ["whisper"],
            "independentRecognitionAlgorithm": "mlx-whisper-locked-decode-v1",
            "independentModelIdentitySHA256": "2" * 64,
            "hintCellsPassed": 1, "hintCellsExpected": 1,
            "outputCellsPassed": 1, "outputCellsExpected": 1, "negativeControlsConfirmed": 1,
        }
        # A pinned English hint over a French script: the English-locked
        # verification ran, detected English weakly and missed the accuracy gate.
        valid["takes"][0].update({
            "accuracyMetric": "wordErrorRate", "accuracyThreshold": 0.15, "expectedOutcome": "fail",
        })
        valid["takes"][0]["metrics"].update({
            "independentWordErrorRate": 0.5625, "independentCharacterErrorRate": 0.23,
            "independentPrimaryAccuracyScore": 0.5625, "independentLanguageMatchScore": 0.89,
            "independentLanguagePass": 1.0, "independentAccuracyPass": 0.0,
            "independentRecognitionDurationSeconds": 0.7,
        })
        self.publish(valid, "control-valid")

        mutations = {
            "control that passed": lambda record: record["takes"][0]["metrics"].update(
                {"independentWordErrorRate": 0.0, "independentPrimaryAccuracyScore": 0.0,
                 "independentAccuracyPass": 1.0}),
            "pass flag disagreeing with the score": lambda record: record["takes"][0]["metrics"].update(
                {"independentWordErrorRate": 0.1, "independentPrimaryAccuracyScore": 0.1}),
            "control not counted": lambda record: record["evidence"]["languageVerification"].__setitem__(
                "negativeControlsConfirmed", 0),
            "unknown expected outcome": lambda record: record["takes"][0].__setitem__(
                "expectedOutcome", "maybe"),
            "control without an accuracy gate": lambda record: (
                record["takes"][0].pop("accuracyMetric"), record["takes"][0].pop("accuracyThreshold")),
        }
        for index, (label, mutate) in enumerate(mutations.items()):
            record = copy.deepcopy(valid)
            record["run"]["id"] = f"control-invalid-{index}"
            mutate(record)
            with self.subTest(label=label), self.assertRaises(history.HistoryError):
                self.publish(record, f"control-invalid-{index}")

        # An ordinary take that failed its verification is still refused.
        failed = copy.deepcopy(valid)
        failed["run"]["id"] = "control-plain-failure"
        failed["takes"][0].pop("expectedOutcome")
        failed["evidence"]["languageVerification"]["negativeControlsConfirmed"] = 0
        with self.assertRaises(history.HistoryError):
            self.publish(failed, "control-plain-failure")

        apple = self._schema_v3_language_record("apple-control")
        apple["evidence"]["languageVerification"] = dict(history.APPLE_SPEECH_VERIFICATION_IDENTITY)
        apple["takes"][0].update({
            "accuracyMetric": "wordErrorRate", "accuracyThreshold": 0.15, "expectedOutcome": "fail",
        })
        apple["takes"][0]["metrics"].update({
            "wordErrorRate": 0.5, "characterErrorRate": 0.5, "primaryAccuracyScore": 0.5,
            "accuracyThreshold": 0.15, "languageMatchScore": 0.4, "outputLanguagePass": 0.0,
            "outputAccuracyPass": 0.0, "referenceTokenCount": 8.0, "hypothesisTokenCount": 8.0,
            "referenceCharacterCount": 32.0, "hypothesisCharacterCount": 32.0, "substitutions": 4.0,
            "insertions": 0.0, "deletions": 0.0, "characterSubstitutions": 16.0,
            "characterInsertions": 0.0, "characterDeletions": 0.0, "recognitionPassCount": 3.0,
            "recognitionDurationSeconds": 0.3,
        })
        self.publish(apple, "apple-control")

    def test_language_take_accuracy_gate_is_bounded_and_paired(self) -> None:
        valid = record_fixture(run_id="accuracy-valid", kind="language")
        provenance = {
            "outputSchemaVersion": 3,
            "outputAlgorithm": "language-output-verifier-v3",
            "recognitionSchemaVersion": 2,
            "recognitionAlgorithm": "apple-speech-file-consensus-v2",
            "accuracyMetricVersion": "normalized-edit-rate-v1",
            "requiredPassCount": 3,
        }
        valid["evidence"]["languageVerification"] = provenance
        valid["takes"][0].update({
            "accuracyMetric": "characterErrorRate",
            "accuracyThreshold": 0.15,
        })
        valid["takes"][0]["metrics"].update({
            "wordErrorRate": 0.125,
            "characterErrorRate": 0.125,
            "primaryAccuracyScore": 0.125,
            "accuracyThreshold": 0.15,
            "languageMatchScore": 0.9,
            "outputLanguagePass": 1.0,
            "outputAccuracyPass": 1.0,
            "referenceTokenCount": 8.0,
            "hypothesisTokenCount": 8.0,
            "referenceCharacterCount": 32.0,
            "hypothesisCharacterCount": 32.0,
            "substitutions": 1.0,
            "insertions": 0.0,
            "deletions": 0.0,
            "characterSubstitutions": 4.0,
            "characterInsertions": 0.0,
            "characterDeletions": 0.0,
            "recognitionPassCount": 3.0,
            "recognitionDurationSeconds": 0.3,
        })
        self.publish(valid, "accuracy-valid")

        for index, mutate in enumerate((
            lambda take: take.__setitem__("accuracyMetric", "unknown"),
            lambda take: take.pop("accuracyThreshold"),
            lambda take: take.__setitem__("accuracyThreshold", 2.0),
        )):
            record = record_fixture(run_id=f"accuracy-invalid-{index}", kind="language")
            record["evidence"]["languageVerification"] = copy.deepcopy(provenance)
            record["takes"][0].update({
                "accuracyMetric": "wordErrorRate", "accuracyThreshold": 0.15,
            })
            record["takes"][0]["metrics"] = copy.deepcopy(valid["takes"][0]["metrics"])
            mutate(record["takes"][0])
            with self.subTest(index=index), self.assertRaises(history.HistoryError):
                self.publish(record, f"accuracy-invalid-{index}")

        missing_provenance = copy.deepcopy(valid)
        missing_provenance["run"]["id"] = "accuracy-missing-provenance"
        missing_provenance["evidence"].pop("languageVerification")
        with self.assertRaisesRegex(history.HistoryError, "verifier provenance"):
            self.publish(missing_provenance, "accuracy-missing-provenance")

        tampered_counts = copy.deepcopy(valid)
        tampered_counts["run"]["id"] = "accuracy-tampered-counts"
        tampered_counts["takes"][0]["metrics"]["characterSubstitutions"] = 3.0
        with self.assertRaisesRegex(history.HistoryError, "do not match tracked counts"):
            self.publish(tampered_counts, "accuracy-tampered-counts")

        out_of_range_score = copy.deepcopy(valid)
        out_of_range_score["run"]["id"] = "accuracy-out-of-range-score"
        out_of_range_score["takes"][0]["metrics"]["languageMatchScore"] = 1.000_000_000_1
        with self.assertRaisesRegex(history.HistoryError, "language accuracy gate metrics"):
            self.publish(out_of_range_score, "accuracy-out-of-range-score")

    def test_schema_v2_language_requires_complete_memory_qualification(self) -> None:
        valid = record_fixture(run_id="language-memory-v2", kind="language")
        valid["schemaVersion"] = 2
        valid["evidence"].update({
            "telemetrySchemaVersion": 8,
            "memoryContractVersion": 1,
            "memoryQualified": True,
            "sampleSidecarCount": 1,
            "sampleSidecarsDigest": "a" * 64,
        })
        take = valid["takes"][0]
        take["memoryStatus"] = "qualified"
        take["sampleSidecarDigest"] = "b" * 64
        take["metrics"].update({key: 0.0 for key in history.MEMORY_REQUIRED_METRICS})
        take["metrics"].update({
            "samplerCoverage": 1.0,
            "samplerSampleCount": 10.0,
            "samplerBoundarySampleCount": 8.0,
            "samplerPeriodicSampleCount": 1.0,
            "gpuRecommendedWorkingSetMB": 4096.0,
            "mlxActivePeakMB": 100.0,
            "mlxCachePeakMB": 10.0,
            "mlxPeakMB": 110.0,
        })
        path = self.publish(valid, "language-memory-v2")
        published = json.loads(path.read_text())
        self.assertTrue(published["evidence"]["memoryQualified"])
        self.assertEqual(published["takes"][0]["memoryStatus"], "qualified")

        for name, mutate in (
            (
                "missing-run-digest",
                lambda record: record["evidence"].pop("sampleSidecarsDigest"),
            ),
            (
                "missing-take-digest",
                lambda record: record["takes"][0].pop("sampleSidecarDigest"),
            ),
            (
                "legacy-telemetry",
                lambda record: record["evidence"].__setitem__("telemetrySchemaVersion", 7),
            ),
        ):
            candidate = copy.deepcopy(valid)
            candidate["run"]["id"] = f"language-memory-v2-{name}"
            mutate(candidate)
            with self.subTest(name=name), self.assertRaises(history.HistoryError):
                self.publish(candidate, f"language-memory-v2-{name}")

    def test_policy_cache_clear_count_is_optional_and_a_subset_of_trims(self) -> None:
        def memory_record(run_id: str) -> dict:
            record = record_fixture(run_id=run_id, kind="language")
            record["schemaVersion"] = 2
            record["evidence"].update({
                "telemetrySchemaVersion": 8,
                "memoryContractVersion": 1,
                "memoryQualified": True,
                "sampleSidecarCount": 1,
                "sampleSidecarsDigest": "a" * 64,
            })
            take = record["takes"][0]
            take["memoryStatus"] = "qualified"
            take["sampleSidecarDigest"] = "b" * 64
            take["metrics"].update({key: 0.0 for key in history.MEMORY_REQUIRED_METRICS})
            take["metrics"].update({
                "samplerCoverage": 1.0, "gpuRecommendedWorkingSetMB": 4096.0,
                "memoryTrimCount": 1.0, "maximumTrimLevel": 1.0,
            })
            return record

        # A routine clear with no pressure: qualified with no memory warning.
        routine = memory_record("policy-clear-routine")
        routine["takes"][0]["metrics"]["policyCacheClearCount"] = 1.0
        published = json.loads(self.publish(routine, "policy-clear-routine").read_text())
        self.assertEqual(published["takes"][0]["metrics"]["policyCacheClearCount"], 1.0)
        self.assertEqual(published["takes"][0]["memoryStatus"], "qualified")
        # A legacy-shaped take without the key still validates.
        self.publish(memory_record("policy-clear-legacy"), "policy-clear-legacy")

        for index, count in enumerate((2.0, -1.0, 0.5)):
            candidate = memory_record(f"policy-clear-invalid-{index}")
            candidate["takes"][0]["metrics"]["policyCacheClearCount"] = count
            with self.subTest(count=count), self.assertRaises(history.HistoryError):
                self.publish(candidate, candidate["run"]["id"])

    def test_ttfc_definition_is_typed_v2_only_and_isolates_lineages(self) -> None:
        def v2_record(run_id: str, definition: str | None) -> dict:
            record = record_fixture(run_id=run_id, kind="language")
            record["schemaVersion"] = 2
            record["evidence"].update({
                "telemetrySchemaVersion": 8, "memoryContractVersion": 1,
                "memoryQualified": True, "sampleSidecarCount": 1,
                "sampleSidecarsDigest": "a" * 64,
            })
            take = record["takes"][0]
            take.update({"memoryStatus": "qualified", "sampleSidecarDigest": "b" * 64})
            take["metrics"].update({key: 0.0 for key in history.MEMORY_REQUIRED_METRICS})
            take["metrics"].update({"samplerCoverage": 1.0, "gpuRecommendedWorkingSetMB": 4096.0})
            if definition is not None:
                record["run"]["ttfcDefinition"] = definition
            return record

        cli = v2_record("ttfc-cli", "cli-submit-to-first-chunk")
        published = json.loads(self.publish(cli, "ttfc-cli").read_text())
        self.assertEqual(published["run"]["ttfcDefinition"], "cli-submit-to-first-chunk")
        # Legacy records (no declaration) keep their comparison key unchanged;
        # the two definitions, and a declared one versus none, never share one.
        legacy = v2_record("ttfc-legacy", None)
        engine = v2_record("ttfc-engine", "engine-prepare-to-first-chunk")
        self.assertEqual(
            len({history.comparison_key(item) for item in (cli, legacy, engine)}), 3
        )
        undeclared = copy.deepcopy(legacy)
        undeclared["run"].pop("ttfcDefinition", None)
        self.assertEqual(history.comparison_key(legacy), history.comparison_key(undeclared))

        invalid_cases = {
            "unknown": v2_record("ttfc-unknown", "wall-clock"),
            "no-ttfc-take": v2_record("ttfc-orphan", "cli-submit-to-first-chunk"),
            "schema-v1": record_fixture(run_id="ttfc-v1"),
        }
        invalid_cases["no-ttfc-take"]["takes"][0]["metrics"].pop("ttfcMS")
        invalid_cases["schema-v1"]["run"]["ttfcDefinition"] = "cli-submit-to-first-chunk"
        for name, candidate in invalid_cases.items():
            with self.subTest(case=name), self.assertRaises(history.HistoryError):
                self.publish(candidate, candidate["run"]["id"])

    def test_startup_windows_must_be_complete_and_sum_to_the_exclusion(self) -> None:
        valid = record_fixture(run_id="startup-windows")
        valid["takes"][0]["metrics"].update({
            "modelLoadWindowMS": 1500.0, "prewarmWindowMS": 500.0, "excludedStartupMS": 2000.0,
        })
        self.publish(valid, "startup-windows")
        for name, change in (
            ("wrong-sum", {"excludedStartupMS": 1999.0}),
            ("negative", {"prewarmWindowMS": -1.0, "excludedStartupMS": 1499.0}),
        ):
            candidate = copy.deepcopy(valid)
            candidate["run"]["id"] = f"startup-windows-{name}"
            candidate["takes"][0]["metrics"].update(change)
            with self.subTest(case=name), self.assertRaises(history.HistoryError):
                self.publish(candidate, candidate["run"]["id"])
        partial = copy.deepcopy(valid)
        partial["run"]["id"] = "startup-windows-partial"
        partial["takes"][0]["metrics"].pop("prewarmWindowMS")
        with self.assertRaises(history.HistoryError):
            self.publish(partial, partial["run"]["id"])

    def test_paired_prosody_effect_publishes_beside_the_legacy_key(self) -> None:
        record = record_fixture(run_id="paired-prosody-fixture", kind="engine-generation")
        record["takes"][0]["metrics"].update({
            "deliveryDF0StdHz": 10.0, "deliveryDRateCV": 0.1,
            "deliveryDPauseRatio": -0.1, "deliveryDRoughness": 0.05,
            "deliveryProsodyEffect": 10.0, "deliveryPairedProsodyEffect": 5.0,
        })
        published = json.loads(self.publish(record, "paired-prosody").read_text())
        metrics = published["takes"][0]["metrics"]
        self.assertEqual(metrics["deliveryPairedProsodyEffect"], 5.0)
        self.assertEqual(metrics["deliveryProsodyEffect"], 10.0)

    def test_sampled_peak_below_the_exact_mlx_peak_is_reported_not_fatal(self) -> None:
        record = record_fixture(
            run_id="peak-miss-fixture",
            takes=[generation_take(1), generation_take(2), generation_take(3)],
        )
        missed, caught, unmeasured = record["takes"]
        missed["metrics"].update({
            "mlxPeakMB": 2500.0, "peakGPUAllocatedMB": 2300.0, "peakPhysicalFootprintMB": 2400.0,
        })
        caught["metrics"].update({
            "mlxPeakMB": 2500.0, "peakGPUAllocatedMB": 2600.0, "peakPhysicalFootprintMB": 2900.0,
        })
        unmeasured["metrics"].update({"peakGPUAllocatedMB": 2000.0})
        summary = history.sampled_peak_misses(record)
        self.assertEqual(summary["comparedTakeCount"], 2)
        self.assertEqual(summary["missedTakeCount"], 1)
        self.assertEqual(summary["footprintMissedTakeCount"], 1)
        self.assertEqual(summary["takes"], [{
            "takeIndex": 1, "cell": missed["cell"], "metalGapMB": 200.0,
        }])
        self.assertEqual(summary["maximumGapMB"], 200.0)
        self.assertIsNotNone(history.sampled_peak_warning(summary))

        clean = copy.deepcopy(record)
        clean["takes"][0]["metrics"]["peakGPUAllocatedMB"] = 2500.0
        self.assertEqual(history.sampled_peak_misses(clean)["missedTakeCount"], 0)
        self.assertIsNone(history.sampled_peak_warning(history.sampled_peak_misses(clean)))

        no_memory = record_fixture(run_id="peak-miss-none")
        report = history.sampled_peak_report([
            (Path("a.json"), record), (Path("b.json"), clean), (Path("c.json"), no_memory),
        ])
        self.assertEqual(
            [item["runID"] for item in report["records"]],
            ["peak-miss-fixture", "peak-miss-fixture"],
        )
        group = report["totals"]["ui-generation/macos"]
        self.assertEqual(
            (group["recordCount"], group["comparedTakeCount"], group["missedTakeCount"]),
            (2, 4, 1),
        )

        # A published record with a missed peak still validates: the warning
        # is advisory and the stored record is never rewritten.
        path = self.publish(record, "peak-miss-fixture")
        before = path.read_bytes()
        with mock.patch("sys.stderr"), mock.patch("sys.stdout"):
            self.assertEqual(history.main(["validate", "--all"]), 0)
            self.assertEqual(history.main(["validate", str(path)]), 0)
            self.assertEqual(history.main(["peak-miss-report", "--json"]), 0)
        self.assertEqual(path.read_bytes(), before)

    def test_runtime_policy_provenance_is_validated_and_never_keys_history(self) -> None:
        valid = record_fixture(run_id="policy-native-20260712", kind="language")
        valid["schemaVersion"] = 2
        valid["evidence"].update({
            "telemetrySchemaVersion": 8,
            "memoryContractVersion": 1,
            "memoryQualified": True,
            "sampleSidecarCount": 1,
            "sampleSidecarsDigest": "a" * 64,
        })
        take = valid["takes"][0]
        take["memoryStatus"] = "qualified"
        take["sampleSidecarDigest"] = "b" * 64
        take["metrics"].update({key: 0.0 for key in history.MEMORY_REQUIRED_METRICS})
        take["metrics"].update({
            "samplerCoverage": 1.0, "samplerSampleCount": 10.0,
            "samplerBoundarySampleCount": 8.0, "samplerPeriodicSampleCount": 1.0,
            "gpuRecommendedWorkingSetMB": 4096.0, "mlxActivePeakMB": 100.0,
            "mlxCachePeakMB": 10.0, "mlxPeakMB": 110.0,
        })
        native = {"deviceClass": "floor_8gb_mac", "deviceClassForced": False}
        valid["run"]["runtimePolicy"] = native
        published = json.loads(self.publish(valid, "policy-native").read_text())
        self.assertEqual(published["run"]["runtimePolicy"], native)
        # History is never keyed on the policy block.
        unstamped = copy.deepcopy(published)
        unstamped["run"].pop("runtimePolicy")
        self.assertEqual(history.comparison_key(published), history.comparison_key(unstamped))

        forced = copy.deepcopy(valid)
        forced["run"].update({
            "id": "policy-forced-20260712", "classification": "exploratory",
            "runtimePolicy": {"deviceClass": "mid_16gb_mac", "deviceClassForced": True},
        })
        forced["takes"][0]["generationID"] = "generation-forced"
        self.publish(forced, "policy-forced")

        for name, policy in (
            ("wrong-platform", {"deviceClass": "iphone_pro", "deviceClassForced": False}),
            ("forced-comparable", {"deviceClass": "mid_16gb_mac", "deviceClassForced": True}),
            ("unknown-class", {"deviceClass": "m6_mac", "deviceClassForced": False}),
            ("extra-key", {**native, "mlxCacheLimitMB": 1024}),
            ("string-flag", {"deviceClass": "floor_8gb_mac", "deviceClassForced": "false"}),
        ):
            candidate = copy.deepcopy(valid)
            candidate["run"]["id"] = f"policy-{name}-20260712"
            candidate["run"]["runtimePolicy"] = policy
            with self.subTest(name=name), self.assertRaises(history.HistoryError):
                self.publish(candidate, f"policy-{name}")

        # Schema-v1 history predates the block and can never declare it.
        legacy = record_fixture(run_id="policy-v1-20260712")
        legacy["run"]["runtimePolicy"] = native
        with self.assertRaises(history.HistoryError):
            self.publish(legacy, "policy-v1")

    def test_schema_v3_generation_records_require_the_quality_identity(self) -> None:
        valid = quality_v3_language_fixture("language-quality-v3")
        path = self.publish(valid, "language-quality-v3")
        published = json.loads(path.read_text())
        self.assertEqual(published["schemaVersion"], 3)
        self.assertEqual(published["takes"][0]["qualityRegistryOutcome"], "pass")
        history.validate_all()

        def set_warning_without_issues(record: dict) -> None:
            record["takes"][0]["qualityRegistryOutcome"] = "warning"

        def set_pass_with_issues(record: dict) -> None:
            record["takes"][0]["qualityRegistryIssues"] = ["quality_gate_warning.token_cap"]

        def downgrade_keeping_fields(record: dict) -> None:
            record["schemaVersion"] = 2

        for name, mutate in (
            ("missing-outcome", lambda record: record["takes"][0].pop("qualityRegistryOutcome")),
            ("failing-outcome", lambda record: record["takes"][0].__setitem__(
                "qualityRegistryOutcome", "fail")),
            ("missing-fast-gate", lambda record: record["takes"][0].__setitem__(
                "qualityRegistryRequiredGates",
                sorted(history.QUALITY_FAST_GATES - {"persisted_wav"}))),
            ("unsorted-gates", lambda record: record["takes"][0].__setitem__(
                "qualityRegistryRequiredGates",
                list(reversed(sorted(history.QUALITY_FAST_GATES))))),
            ("warning-without-issues", set_warning_without_issues),
            ("pass-with-issues", set_pass_with_issues),
            ("v2-with-quality-keys", downgrade_keeping_fields),
        ):
            candidate = copy.deepcopy(valid)
            candidate["run"]["id"] = f"language-quality-v3-{name}"
            mutate(candidate)
            with self.subTest(name=name), self.assertRaises(history.HistoryError):
                self.publish(candidate, f"language-quality-v3-{name}")

    def test_schema_v2_macos_ui_requires_both_aligned_process_coverages(self) -> None:
        valid = record_fixture(run_id="macos-ui-memory-v2")
        valid["schemaVersion"] = 2
        valid["evidence"].update({
            "telemetrySchemaVersion": 8,
            "memoryContractVersion": 1,
            "memoryQualified": True,
            "sampleSidecarCount": 2,
            "sampleSidecarsDigest": "a" * 64,
        })
        take = valid["takes"][0]
        take["memoryStatus"] = "qualified"
        take["sampleSidecarDigest"] = "b" * 64
        take["playbackStartSource"] = "finalFile"
        take["metrics"].update({key: 0.0 for key in history.MEMORY_REQUIRED_METRICS})
        take["metrics"].update({
            "samplerCoverage": 1.0,
            "samplerSampleCount": 10.0,
            "samplerBoundarySampleCount": 8.0,
            "samplerPeriodicSampleCount": 1.0,
            "gpuRecommendedWorkingSetMB": 4096.0,
            "mlxActivePeakMB": 100.0,
            "mlxCachePeakMB": 10.0,
            "mlxPeakMB": 110.0,
            "alignedProcessSampleCount": 10.0,
            "alignedProcessSampleCoverage": 1.0,
            "alignedEngineSampleCoverage": 1.0,
            "alignedAppSampleCoverage": 1.0,
        })
        self.publish(valid, "macos-ui-memory-v2")

        for key in ("alignedEngineSampleCoverage", "alignedAppSampleCoverage"):
            missing = copy.deepcopy(valid)
            missing["run"]["id"] = f"macos-ui-memory-v2-missing-{key}"
            missing["takes"][0]["metrics"].pop(key)
            with self.subTest(key=key), self.assertRaisesRegex(
                history.HistoryError, "memory-qualified take metrics are incomplete"
            ):
                self.publish(missing, missing["run"]["id"])

        invalid = copy.deepcopy(valid)
        invalid["run"]["id"] = "macos-ui-memory-v2-app-coverage-low"
        invalid["takes"][0]["metrics"]["alignedAppSampleCoverage"] = 0.94
        with self.assertRaisesRegex(history.HistoryError, "alignedAppSampleCoverage"):
            self.publish(invalid, invalid["run"]["id"])

    def memory_contract_v2_record(self, run_id: str) -> dict:
        record = record_fixture(run_id=run_id)
        record["schemaVersion"] = 2
        record["evidence"].update({
            "telemetrySchemaVersion": 8,
            "memoryContractVersion": 2,
            "memoryQualified": True,
            "sampleSidecarCount": 2,
            "sampleSidecarsDigest": "a" * 64,
        })
        take = record["takes"][0]
        take["memoryStatus"] = "qualified"
        take["sampleSidecarDigest"] = "b" * 64
        take["playbackStartSource"] = "finalFile"
        take["metrics"].update({key: 0.0 for key in history.MEMORY_REQUIRED_METRICS})
        take["metrics"].update({
            "samplerCoverage": 0.9,  # informational under contract v2
            "samplerSampleCount": 10.0,
            "samplerBoundarySampleCount": 8.0,
            "samplerPeriodicSampleCount": 1.0,
            "samplerTargetIntervalMS": 500.0,
            "samplerMaximumUnobservedGapMS": 1000.0,
            "samplerUnobservedGapLimitMS": 1000.0,
            "gpuRecommendedWorkingSetMB": 4096.0,
            "peakGPUAllocatedMB": 90.0,
            "peakPhysicalFootprintMB": 300.0,
            "mlxActivePeakMB": 100.0,
            "mlxCachePeakMB": 10.0,
            "mlxPeakMB": 110.0,
            "gpuPeakCaptureMissMB": 20.0,
            "kernelPhysFootprintPeakMB": 340.0,
            "kernelPhysFootprintPeakExact": 1.0,
            "footprintPeakCaptureMissMB": 40.0,
            "graphicsFootprintEndMB": 80.0,
        })
        return record

    def test_memory_contract_v2_takes_have_one_series_a_bounded_gap_and_peak_fidelity(self) -> None:
        valid = self.memory_contract_v2_record("macos-ui-memory-contract-v2")
        self.publish(valid, valid["run"]["id"])

        def mutated(name: str, change) -> dict:
            candidate = copy.deepcopy(valid)
            candidate["run"]["id"] = f"macos-ui-memory-contract-v2-{name}"
            change(candidate["takes"][0]["metrics"])
            return candidate

        cases = {
            "pairing": (
                lambda metrics: metrics.update({"alignedProcessSampleCoverage": 1.0}),
                "carries no pairing metrics",
            ),
            "no-gap": (
                lambda metrics: metrics.pop("samplerMaximumUnobservedGapMS"),
                "incomplete: samplerMaximumUnobservedGapMS",
            ),
            # The gap cases assert only that the record is refused.
            "long-gap": (
                lambda metrics: metrics.update({"samplerMaximumUnobservedGapMS": 1000.5}),
                None,
            ),
            "no-bound": (lambda metrics: metrics.pop("samplerUnobservedGapLimitMS"), None),
            "bound-below-cadence": (
                lambda metrics: metrics.update({
                    "samplerMaximumUnobservedGapMS": 100.0, "samplerUnobservedGapLimitMS": 400.0,
                }),
                None,
            ),
            "no-cadence": (lambda metrics: metrics.pop("samplerTargetIntervalMS"), None),
            "boolean-exact": (
                lambda metrics: metrics.update({"kernelPhysFootprintPeakExact": True}), None,
            ),
            "wrong-miss": (
                lambda metrics: metrics.update({"gpuPeakCaptureMissMB": 0.0}),
                "gpuPeakCaptureMissMB does not match",
            ),
            "ledger-below-sample": (
                lambda metrics: metrics.update({
                    "kernelPhysFootprintPeakMB": 250.0, "footprintPeakCaptureMissMB": 0.0,
                }),
                "ledger peak is below",
            ),
            "upper-bound-miss": (
                lambda metrics: metrics.update({"kernelPhysFootprintPeakExact": 0.0}),
                "belongs only to an exact kernel peak",
            ),
            "partial-ledger": (
                lambda metrics: metrics.pop("kernelPhysFootprintPeakExact"),
                "ledger metrics are incomplete",
            ),
        }
        for name, (change, message) in cases.items():
            candidate = mutated(name, change)
            refused = (
                self.assertRaises(history.HistoryError) if message is None
                else self.assertRaisesRegex(history.HistoryError, message)
            )
            with self.subTest(case=name), refused:
                self.publish(candidate, candidate["run"]["id"])

        unknown = copy.deepcopy(valid)
        unknown["run"]["id"] = "macos-ui-memory-contract-v3"
        unknown["evidence"]["memoryContractVersion"] = 3
        with self.assertRaises(history.HistoryError):
            self.publish(unknown, unknown["run"]["id"])

    def test_memory_contract_v2_never_shares_a_lineage_with_v1(self) -> None:
        record = self.memory_contract_v2_record("macos-ui-memory-lineage")
        legacy = copy.deepcopy(record)
        legacy["evidence"]["memoryContractVersion"] = 1
        self.assertNotEqual(history.comparison_key(record), history.comparison_key(legacy))
        # A v1 record's key is computed exactly as before the marker existed.
        without = copy.deepcopy(legacy)
        without["evidence"].pop("memoryContractVersion")
        self.assertEqual(history.comparison_key(legacy), history.comparison_key(without))

    def test_nested_manifest_selects_only_current_run(self) -> None:
        payload = {
            "schemaVersion": 1,
            "benchmarkKind": "ui-generation",
            "platform": "ios",
            "runID": "ios-current-20260712",
            "status": "pass",
            "expectedTakeCount": 1,
            "takes": [generation_take(1, length="medium")] * 300,
            "historyRecord": record_fixture(
                run_id="ios-current-20260712", platform="ios", profile="iphone-17-pro",
                takes=[generation_take(1, length="long")],
            ),
        }
        path = history.record_manifest(self.write_manifest(payload))
        record = json.loads(path.read_text())
        self.assertEqual(len(record["takes"]), 1)
        self.assertEqual(record["takes"][0]["length"], "long")
        self.assertEqual(record["cells"][0]["length"], "long")

    def test_warning_becomes_passed_with_warnings(self) -> None:
        path = self.publish(record_fixture(takes=[generation_take(warning=True)]))
        record = json.loads(path.read_text())
        self.assertEqual(record["run"]["status"], "passedWithWarnings")
        self.assertEqual(record["cells"][0]["status"], "passedWithWarnings")

    def test_recorder_enriches_runtime_toolchain_and_artifact_digests(self) -> None:
        record = record_fixture()
        record["hardware"] = {"profileID": "mac-mini-m2-8gb"}
        record["toolchain"] = {}
        record["evidence"].pop("resultBundleDigest")
        record["evidence"].pop("screenshotDigests")
        directory = self.write_manifest({"historyRecord": record})
        attachments = directory / "attachments"
        attachments.mkdir()
        screenshot = attachments / "settings-ready.png"
        screenshot.write_bytes(b"not raw image content in record")
        runtime = {
            "osName": "macOS", "osVersion": "26.5.2", "osBuild": "25F84",
            "thermalState": "nominal", "lowPowerMode": False, "transport": "local",
            "loadAverage1M": 1.0, "freeStorageBytes": 1_000_000,
            "uptimeSeconds": 100.0,
        }
        toolchain = record_fixture()["toolchain"]
        with (
            mock.patch.object(history, "default_runtime_hardware", return_value=runtime),
            mock.patch.object(history, "default_toolchain", return_value=toolchain),
            mock.patch.object(history, "digest_xcresult_summary", return_value="f" * 64),
        ):
            path = history.record_manifest(directory)
        published = json.loads(path.read_text())
        self.assertEqual(published["hardware"]["osBuild"], "25F84")
        self.assertEqual(published["toolchain"]["xcodeBuild"], "17F113")
        self.assertEqual(published["evidence"]["resultBundleDigest"], "f" * 64)
        self.assertEqual(published["evidence"]["screenshotDigests"], [{
            "name": "settings-ready.png", "digest": history.file_digest(screenshot),
        }])

    def test_recorder_uses_retained_xcresult_os_identity_without_live_device(self) -> None:
        record = record_fixture(platform="ios", profile="iphone-17-pro")
        record["hardware"] = {"profileID": "iphone-17-pro"}
        directory = self.write_manifest({"historyRecord": record})
        (directory / "xcresult-test-summary.json").write_text(json.dumps({
            "devicesAndConfigurations": [{
                "device": {
                    "platform": "iOS",
                    "osVersion": "26.6.1",
                    "osBuildNumber": "23G83",
                }
            }]
        }), encoding="utf-8")
        runtime = {
            "osName": "iOS", "thermalState": "unknown", "lowPowerMode": None,
            "transport": "physical-device",
            "loadAverage1M": 1.0, "freeStorageBytes": 1_000_000,
            "uptimeSeconds": 100.0,
        }
        with mock.patch.object(history, "default_runtime_hardware", return_value=runtime):
            path = history.record_manifest(directory)
        published = json.loads(path.read_text())
        self.assertEqual(published["hardware"]["osVersion"], "26.6.1")
        self.assertEqual(published["hardware"]["osBuild"], "23G83")

    def test_explicit_cli_identity_does_not_inherit_an_unrelated_app_bundle(self) -> None:
        repo = self.root / "repo"
        cli = repo / "build" / "vocello"
        cli.parent.mkdir(parents=True)
        cli.write_bytes(b"cli-binary")
        (repo / "project.yml").write_text(
            'MARKETING_VERSION: "2.1.0"\nCURRENT_PROJECT_VERSION: "18"\n',
            encoding="utf-8",
        )
        with (
            mock.patch.object(history, "REPO_ROOT", repo.resolve()),
            mock.patch.object(history, "run_command", return_value=""),
        ):
            identity = history.app_identity(
                "macos", {"executableRelativePaths": {"vocello": "build/vocello"}}, repo
            )
        self.assertEqual(set(identity["executableHashes"]), {"vocello"})
        self.assertEqual(identity["appVersion"], "2.1.0")
        self.assertEqual(identity["appBuild"], "18")

    def test_macos_perf_identity_uses_verified_run_receipt_not_development_cache(self) -> None:
        repo = self.root / "perf-repo"
        relative = Path("build/cache/xcode/macos-optimized/Build/Products/Release/Vocello.app/Contents/MacOS/Vocello")
        executable = repo / relative
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"optimized-ui-app")
        (executable.parents[1] / "Info.plist").write_bytes(history.plistlib.dumps({
            "CFBundleExecutable": "Vocello", "CFBundleShortVersionString": "3.0.0",
            "CFBundleVersion": "24",
        }))
        development = repo / "build/cache/xcode/macos/Build/Products/Release/Vocello.app"
        other = development / "Contents/MacOS/Vocello"
        other.parent.mkdir(parents=True)
        other.write_bytes(b"unrelated-development-app")
        (development / "Contents/Info.plist").write_bytes(history.plistlib.dumps({
            "CFBundleExecutable": "Vocello", "CFBundleShortVersionString": "old",
            "CFBundleVersion": "1",
        }))
        artifact = repo / "artifact"
        artifact.mkdir()
        receipt = artifact / "last-build.json"
        receipt.write_text(json.dumps({
            "schemaVersion": 1, "status": "passed", "platform": "macos",
            "producer": "scripts/ui_test.sh macos perf", "optimization": "O",
            "executableRelativePath": str(relative),
            "executableSHA256": history.file_digest(executable),
        }))
        outer = {"benchmarkKind": "ui-perf"}
        with (
            mock.patch.object(history, "REPO_ROOT", repo.resolve()),
            mock.patch.object(history, "MACOS_DERIVED_DATA", development.parents[3]),
            mock.patch.object(history, "run_command", return_value="Xcode 27.0\nBuild version test"),
        ):
            result = history.default_toolchain("macos", outer, artifact)
            self.assertEqual(result["optimization"], "-O")
            self.assertEqual(result["executableHashes"], {"Vocello": history.file_digest(executable)})
            self.assertEqual(result["appVersion"], "3.0.0")
            self.assertEqual(result["appBuild"], "24")
            executable.write_bytes(b"rebuilt-after-the-run")
            with self.assertRaisesRegex(history.HistoryError, "changed since"):
                history.default_toolchain("macos", outer, artifact)
            receipt.unlink()
            with self.assertRaisesRegex(history.HistoryError, "unreadable"):
                history.default_toolchain("macos", outer, artifact)

    def test_pre_run_source_snapshot_is_compared_with_post_run_state(self) -> None:
        record = record_fixture()
        before = copy.deepcopy(record["source"])
        record.pop("source")
        directory = self.write_manifest({"historyRecord": record})
        (directory / "benchmark-source.json").write_text(json.dumps({
            "schemaVersion": 1,
            "capturedAt": "2026-07-12T12:00:00Z",
            "source": before,
        }) + "\n", encoding="utf-8")
        after = copy.deepcopy(before)
        after["workspaceFingerprint"] = "f" * 64
        after["preFingerprint"] = "f" * 64
        after["postFingerprint"] = "f" * 64
        with mock.patch.object(history, "git_state", return_value=after):
            path = history.record_manifest(directory)
        published = json.loads(path.read_text())
        self.assertEqual(published["source"]["preFingerprint"], "1" * 64)
        self.assertEqual(published["source"]["postFingerprint"], "f" * 64)
        self.assertFalse(published["source"]["fingerprintsMatch"])
        self.assertEqual(published["run"]["classification"], "exploratory")
        self.assertFalse(published["comparison"]["comparable"])

    def test_dirty_run_is_exploratory_and_not_comparable(self) -> None:
        path = self.publish(record_fixture(dirty=True))
        record = json.loads(path.read_text())
        self.assertEqual(record["run"]["classification"], "exploratory")
        self.assertFalse(record["comparison"]["comparable"])

    def test_nearest_compatible_clean_run_produces_metric_deltas(self) -> None:
        first = record_fixture(run_id="macos-bench-20260712-120000")
        self.publish(first, "first-compatible")
        second_take = generation_take()
        second_take["metrics"]["rtf"] = 2.2
        second = record_fixture(
            run_id="macos-bench-20260712-121000",
            takes=[second_take],
        )
        second["run"]["startedAt"] = "2026-07-12T12:10:00Z"
        second["run"]["finishedAt"] = "2026-07-12T12:11:00Z"
        path = self.publish(second, "second-compatible")
        published = json.loads(path.read_text())
        comparison = published["comparison"]
        self.assertEqual(comparison["baselineRunID"], "macos-bench-20260712-120000")
        rtf_delta = comparison["deltas"][second_take["cell"]]["rtf"]
        self.assertAlmostEqual(rtf_delta["absolute"], 0.2)
        self.assertAlmostEqual(rtf_delta["percent"], 10.0)
        self.assertIn("RTF +10.0%", self.index.read_text())

    def test_new_records_store_only_the_trend_deltas(self) -> None:
        first = self._schema_v3_language_record("mac-lang-bench-20260712-130000")
        first["takes"][0]["metrics"]["physicalFootprintStartMB"] = 900.0
        self.publish(first, "trend-first")
        second = self._schema_v3_language_record("mac-lang-bench-20260712-131000")
        second["run"]["startedAt"] = "2026-07-12T13:10:00Z"
        second["run"]["finishedAt"] = "2026-07-12T13:11:00Z"
        take = second["takes"][0]
        take["metrics"]["rtf"] = take["metrics"].get("rtf", 2.0) + 0.2
        take["metrics"]["physicalFootprintStartMB"] = 950.0
        published = json.loads(self.publish(second, "trend-second").read_text())
        comparison = published["comparison"]
        self.assertEqual(comparison["deltaMetrics"], "trend-v1")
        self.assertEqual(comparison["baselineRunID"], "mac-lang-bench-20260712-130000")
        cell_deltas = comparison["deltas"][take["cell"]]
        self.assertIn("rtf", cell_deltas)
        self.assertNotIn("physicalFootprintStartMB", cell_deltas, "only trend metrics are stored")
        self.assertTrue(set(cell_deltas) <= history.COMPARISON_DELTA_METRICS["trend-v1"])

    def test_an_unknown_delta_declaration_is_rejected(self) -> None:
        record = record_fixture(run_id="macos-bench-20260712-140000")
        record["comparison"]["deltaMetrics"] = "everything"
        with self.assertRaises(history.HistoryError):
            history.validate_record(record)

    def test_cross_optimization_records_are_never_compared(self) -> None:
        baseline = record_fixture(run_id="optimization-onone")
        baseline["toolchain"]["optimization"] = "-Onone"
        self.publish(baseline, "optimization-onone")

        optimized = record_fixture(run_id="optimization-o")
        optimized["takes"][0]["metrics"]["rtf"] = 2.1
        optimized["run"]["startedAt"] = "2026-07-12T12:10:00Z"
        optimized["run"]["finishedAt"] = "2026-07-12T12:11:00Z"
        path = self.publish(optimized, "optimization-o")
        comparison = json.loads(path.read_text())["comparison"]
        self.assertIsNone(comparison["baselineRunID"])
        self.assertEqual(comparison["deltas"], {})

    def test_records_without_an_rtf_need_no_rtf_definition_after_the_cutover(self) -> None:
        # ui-perf measures frame health; the first perf run after the cutover
        # (macos-xcui-perf-20260913-173142) was refused for a declaration it has
        # nothing to declare. A tracked ui-perf record moved past the cutover must
        # validate as it is, while an RTF-bearing kind keeps the requirement.
        # The fixture is a frozen published ui-perf record (macos-xcui-perf-20260922-162034).
        record = json.loads((FROZEN_RECORDS / "macos-ui-perf.json").read_text())
        self.assertNotIn("rtfDefinition", record["run"])
        record["run"]["finishedAt"] = "2026-09-20T12:01:00Z"
        record["digest"] = history.record_digest(record)
        history.validate_record(record)
        self.assertNotIn("ui-perf", history.RTF_BEARING_KINDS)
        self.assertNotIn("prosody-calibration", history.RTF_BEARING_KINDS)
        self.assertTrue({"ui-generation", "engine-generation", "language",
                         "memory-qualification"} <= history.RTF_BEARING_KINDS)

    def test_rtf_definition_is_required_after_the_cutover_and_isolates_lineages(self) -> None:
        legacy = record_fixture(run_id="rtf-legacy-20260712")
        # Legacy UI takes store the app submit→completed span, from which a
        # standard RTF is derived at render time (2.1 s ÷ 3 s = 0.70).
        legacy["takes"][0]["metrics"].update({"audioSeconds": 3.0, "submitToCompletedMS": 2100.0})
        legacy_path = self.publish(legacy, "rtf-legacy")
        legacy_record = json.loads(legacy_path.read_text())
        self.assertNotIn("rtfDefinition", legacy_record["run"])

        # A record finished after the cutover without the declaration is refused.
        undeclared = record_fixture(run_id="rtf-undeclared-20260920")
        undeclared["run"]["startedAt"] = "2026-09-20T12:00:00Z"
        undeclared["run"]["finishedAt"] = "2026-09-20T12:01:00Z"
        with self.assertRaisesRegex(history.HistoryError, "rtfDefinition"):
            self.publish(undeclared, "rtf-undeclared")

        # A wrong definition is refused outright.
        wrong = record_fixture(run_id="rtf-wrong-20260920")
        wrong["run"]["rtfDefinition"] = "audio/wall"
        with self.assertRaisesRegex(history.HistoryError, "rtfDefinition"):
            self.publish(wrong, "rtf-wrong")

        # A standard record is accepted, starts its own comparison lineage, and the
        # index shows the measured value while the legacy record shows a derived one.
        standard = record_fixture(run_id="rtf-standard-20260920")
        standard["run"].update({
            "startedAt": "2026-09-20T12:00:00Z", "finishedAt": "2026-09-20T12:01:00Z",
            "rtfDefinition": "wall/audio",
        })
        standard["takes"][0]["metrics"].update({"rtf": 0.62, "decodeSpeedupX": 1.9, "requestWallSeconds": 1.86})
        standard_path = self.publish(standard, "rtf-standard")
        standard_record = json.loads(standard_path.read_text())
        self.assertEqual(standard_record["run"]["rtfDefinition"], "wall/audio")
        self.assertNotEqual(standard_record["comparison"]["key"], legacy_record["comparison"]["key"])
        self.assertIsNone(standard_record["comparison"]["baselineRunID"])
        index = self.index.read_text()
        self.assertIn("| 0.62 |", index)
        legacy_row = next(line for line in index.splitlines() if "rtf-legacy-20260712" in line)
        self.assertIn("| ~0.70 |", legacy_row)

    def test_all_record_kinds_validate(self) -> None:
        for index, kind in enumerate(sorted(history.KINDS), start=1):
            takes = [generation_take()]
            if kind == "telemetry-overhead":
                takes = telemetry_overhead_takes()
            elif kind == "prosody-calibration":
                takes = [prosody_take(f"kind-{index}-20260712")]
            record = record_fixture(run_id=f"kind-{index}-20260712", kind=kind, takes=takes)
            if kind == "prosody-calibration":
                record["inputs"]["corpusHash"] = "a" * 64
                record["inputs"]["analysisProfileHash"] = "b" * 64
                record["models"] = []
                record["evidence"]["telemetrySchemaVersion"] = "not-applicable"
                record["evidence"]["qcAlgorithmVersion"] = "not-applicable"
            if kind == "telemetry-overhead":
                record["run"]["platform"] = "macos"
                record["evidence"]["telemetrySchemaVersion"] = 7
                record["evidence"]["qcAlgorithmVersion"] = "not-applicable"
            if kind == "instrument-profile":
                record["run"]["matrixScope"] = "instrumented"
                record["run"]["classification"] = "instrumented"
                record["evidence"]["trace"] = {
                    "digest": "f" * 64,
                    "template": "Time Profiler",
                    "durationSeconds": 10,
                    "validated": True,
                    "summary": trace_summary(len(takes)),
                }
            self.publish(record, name=f"kind-{index}")
        history.validate_all()
        self.assertEqual(len(history.all_record_paths()), len(history.KINDS))

    def test_superseded_model_pins_remain_valid_but_current_version_must_match(self) -> None:
        contract = json.loads(
            (history.REPO_ROOT / "Sources/Resources/qwenvoice_contract.json").read_text(encoding="utf-8")
        )
        current = next(model for model in contract["models"] if model["id"] == "pro_custom")
        speed = next(variant for variant in current["variants"] if variant["id"] == "speed")
        self.assertLess(
            history.artifact_version_key("2026.04.05.2"),
            history.artifact_version_key(speed["artifactVersion"]),
        )
        # Fixture records pin the strictly older artifact identity; immutable
        # published history must stay valid after a contract re-pin.
        self.publish(record_fixture(run_id="superseded-20260726-000001"), name="superseded")
        history.validate_all()
        # A record claiming the current artifactVersion must match the pinned
        # identity exactly — supersession never excuses a same-version mismatch.
        record = record_fixture(run_id="mismatch-20260726-000002")
        for take in record["takes"]:
            take["modelArtifactVersion"] = speed["artifactVersion"]
        record["models"][0]["artifactVersion"] = speed["artifactVersion"]
        with self.assertRaises(history.HistoryError):
            self.publish(record, name="mismatch")

    def test_telemetry_overhead_requires_exact_rotations_and_context(self) -> None:
        takes = telemetry_overhead_takes()
        def break_parity(value: list[dict]) -> None:
            value[2]["output"]["fileDigest"] = "f" * 64

        def exceed_threshold(value: list[dict]) -> None:
            for take in value:
                if "/lightweight/" in take["cell"]:
                    take["metrics"]["rtf"] = 0.8

        for index, mutate in enumerate((
            lambda value: value.pop(),
            lambda value: value[0].__setitem__("cell", value[1]["cell"]),
            lambda value: value[0]["metrics"].pop("loadAverage1M"),
            break_parity,
            exceed_threshold,
        )):
            candidate = copy.deepcopy(takes)
            mutate(candidate)
            record = record_fixture(
                run_id=f"overhead-invalid-{index}", kind="telemetry-overhead", takes=candidate,
            )
            record["evidence"]["telemetrySchemaVersion"] = 7
            record["evidence"]["qcAlgorithmVersion"] = "not-applicable"
            with self.assertRaises(history.HistoryError):
                self.publish(record, f"overhead-invalid-{index}")

    def test_instrument_profile_requires_structured_pid_cpu_and_signpost_proof(self) -> None:
        for index, summary in enumerate((
            "cpu-sample-summary-v1",
            {**trace_summary(), "targetPIDVerified": False},
            {**trace_summary(), "cpuSampleCount": 0},
            {**trace_summary(), "correlatedSignpostEventCount": 0},
        )):
            record = record_fixture(run_id=f"profile-invalid-{index}", kind="instrument-profile")
            record["run"]["matrixScope"] = "instrumented"
            record["run"]["classification"] = "instrumented"
            record["evidence"]["trace"] = {
                "digest": "f" * 64, "template": "CPU Profiler + os_signpost",
                "durationSeconds": 10, "validated": True, "summary": summary,
            }
            with self.assertRaises(history.HistoryError):
                self.publish(record, f"profile-invalid-{index}")

    def profile_producer_manifest(self, run_id: str, *, quality: bool, policy: str) -> dict:
        """Exercise the production schema selector and retention writer together."""
        fixture = record_fixture(run_id=run_id, kind="instrument-profile")
        take = fixture["takes"][0]
        take.update(memoryStatus="qualified", sampleSidecarDigest="b" * 64)
        take["metrics"].update({key: 0.0 for key in history.MEMORY_REQUIRED_METRICS})
        take["metrics"].update({
            "samplerCoverage": 1.0, "samplerSampleCount": 10.0,
            "samplerBoundarySampleCount": 8.0, "samplerPeriodicSampleCount": 1.0,
            "gpuRecommendedWorkingSetMB": 4096.0, "mlxActivePeakMB": 100.0,
            "mlxCachePeakMB": 10.0, "mlxPeakMB": 110.0,
        })
        if quality:
            take["qualityRegistryOutcome"] = "pass"
            take["qualityRegistryRequiredGates"] = sorted(history.QUALITY_FAST_GATES)
        trace_path = self.root / "build" / f"{run_id}.trace"
        trace_path.mkdir(parents=True)
        (trace_path / "fixture.data").write_bytes(b"synthetic trace")
        summary = {**trace_summary(), "artifact": f"build/{run_id}.trace"}
        args = SimpleNamespace(
            trace=trace_path, run_id=run_id, template="CPU Profiler + os_signpost",
            duration=10.0, target_process="vocello", profile_kind="cpu",
            retention_policy=policy,
        )
        with (
            mock.patch.object(publisher, "ROOT", self.root),
            mock.patch.object(publisher, "source_from_snapshot", return_value=fixture["source"]),
            mock.patch.object(publisher, "verify_canonical_hardware", return_value=fixture["hardware"]),
        ):
            retention = publisher.write_trace_summary_artifact(
                args, trace_digest="f" * 64,
                original_ephemeral_path=summary["artifact"], trace_summary=summary,
            )
            manifest = publisher.record_shell(
                kind="instrument-profile", platform="macos", run_id=run_id,
                label="fixture", started_at=fixture["run"]["startedAt"],
                finished_at=fixture["run"]["finishedAt"], matrix_scope="instrumented",
                artifact_dir=trace_path.parent, snapshot=self.root / "snapshot.json",
                takes=[take], raw_digest=history.sha256_bytes(run_id.encode()),
                telemetry_schema=8, qc_algorithm=2, optimization="-O",
                inputs=fixture["inputs"], models=fixture["models"],
                classification="instrumented", crash_delta={"passed": True, "count": 0},
                memory_evidence={
                    "memoryContractVersion": 1, "memoryQualified": True,
                    "sampleSidecarCount": 1, "sampleSidecarsDigest": "a" * 64,
                },
                trace={
                    "digest": "f" * 64, "template": args.template,
                    "durationSeconds": args.duration, "validated": True,
                    "summary": summary, **retention,
                },
            )
            # This fixture qualifies retention/schema composition, not a local
            # build. Supply the synthetic executable identity explicitly so
            # cache cleanup cannot change which validation rule is exercised.
            manifest["historyRecord"]["toolchain"].update(fixture["toolchain"])
            return manifest

    def test_production_profile_retention_publishes_v2_and_v3_without_downgrade(self) -> None:
        for quality in (False, True):
            for policy in ("summaryOnly", "keptExplicitly"):
                run_id = f"profile-producer-v{3 if quality else 2}-{policy}"
                with self.subTest(quality=quality, policy=policy):
                    manifest = self.profile_producer_manifest(run_id, quality=quality, policy=policy)
                    directory = self.write_manifest(manifest, run_id)
                    path = history.record_manifest(directory)
                    record = json.loads(path.read_text())
                    self.assertEqual(record["schemaVersion"], 3 if quality else 2)
                    self.assertEqual(record["evidence"]["trace"]["retentionPolicy"], policy)
                    self.assertEqual("qualityRegistryOutcome" in record["takes"][0], quality)
                    before = path.read_bytes()
                    self.assertEqual(history.record_manifest(directory).read_bytes(), before)
                    self.assertTrue((self.root / "build" / f"{run_id}.trace").is_dir())
        history.validate_all()

    def test_v3_profile_retention_still_rejects_corruption_and_missing_quality(self) -> None:
        for name, mutate in (
            ("missing-retention", lambda record: record["evidence"]["trace"].pop("summaryArtifact")),
            ("capture-digest", lambda record: record["evidence"]["trace"].__setitem__("captureSettingsDigest", "0" * 64)),
            ("retention-policy", lambda record: record["evidence"]["trace"].__setitem__("rawTraceRetained", True)),
            ("unsafe-path", lambda record: record["evidence"]["trace"]["summaryArtifact"].__setitem__("path", "../private.json")),
            ("missing-quality", lambda record: record["takes"][0].pop("qualityRegistryOutcome")),
            ("unknown-schema", lambda record: record.__setitem__("schemaVersion", 4)),
            ("v1-retention", lambda record: record.__setitem__("schemaVersion", 1)),
        ):
            run_id = f"profile-v3-invalid-{name}"
            manifest = self.profile_producer_manifest(run_id, quality=True, policy="summaryOnly")
            mutate(manifest["historyRecord"])
            with self.subTest(name=name), self.assertRaises(history.HistoryError):
                history.record_manifest(self.write_manifest(manifest, run_id))
            self.assertFalse(list(self.runs.rglob("*.json")))
            self.assertTrue((self.root / "build" / f"{run_id}.trace").is_dir())

    def test_only_a_memory_profile_keeps_its_raw_trace_by_default(self) -> None:
        # A valid CPU profile that kept its trace explicitly publishes; the
        # same record claiming the memory-only default is refused.
        run_id = "profile-cpu-kept"
        manifest = self.profile_producer_manifest(run_id, quality=True, policy="keptExplicitly")
        history.record_manifest(self.write_manifest(manifest, run_id))
        run_id = "profile-cpu-kept-by-default"
        manifest = self.profile_producer_manifest(run_id, quality=True, policy="keptExplicitly")
        manifest["historyRecord"]["evidence"]["trace"]["retentionPolicy"] = "keptByDefault"
        with self.assertRaises(history.HistoryError):
            history.record_manifest(self.write_manifest(manifest, run_id))

    def test_memory_instrument_profile_requires_and_accepts_target_rows(self) -> None:
        record = record_fixture(run_id="profile-memory-valid", kind="instrument-profile")
        record["schemaVersion"] = 2
        record["run"]["matrixScope"] = "instrumented"
        record["run"]["classification"] = "instrumented"
        record["evidence"].update({
            "telemetrySchemaVersion": 8,
            "memoryContractVersion": 1,
            "memoryQualified": True,
            "sampleSidecarCount": 1,
            "sampleSidecarsDigest": "a" * 64,
        })
        take = record["takes"][0]
        take["memoryStatus"] = "qualified"
        take["sampleSidecarDigest"] = "b" * 64
        take["metrics"].update({key: 0.0 for key in history.MEMORY_REQUIRED_METRICS})
        take["metrics"].update({
            "samplerCoverage": 1.0,
            "samplerSampleCount": 10.0,
            "samplerBoundarySampleCount": 8.0,
            "samplerPeriodicSampleCount": 1.0,
            "gpuRecommendedWorkingSetMB": 4096.0,
            "mlxActivePeakMB": 100.0,
            "mlxCachePeakMB": 10.0,
            "mlxPeakMB": 110.0,
        })
        summary = {
            **trace_summary(),
            "memoryTraceEvidenceVersion": 2,
            "allocationTargetDataBytes": 4096,
            "allocationTrackPresent": True,
            "allocationListPresent": True,
            "allocationDataExportStatus": "notExportable",
            "allocationTargetRowCount": 0,
            "vmTrackerTrackPresent": True,
            "vmTrackerRegionMapPresent": True,
            "vmTrackerDataExportStatus": "notExportable",
            "vmTrackerTargetRowCount": 0,
        }
        # TOC-advertised schemas are retained even when exact-PID filtering
        # yields no rows. Zero is valid for an ancillary schema; aggregate CPU,
        # signpost, allocation, and VM requirements remain independently strict.
        summary["capturedRowsBySchema"]["kdebug-signpost"] = 0
        record["evidence"]["trace"] = {
            "digest": "f" * 64,
            "template": "CPU Profiler + Allocations + VM Tracker + os_signpost",
            "durationSeconds": 10,
            "validated": True,
            "summary": summary,
        }
        # A v2 record published before trace-retention metadata existed remains
        # valid for read-only history compatibility.
        self.publish(record, "profile-memory-valid")

        retained = copy.deepcopy(record)
        retained["run"]["id"] = "profile-memory-retention-valid"
        retained["evidence"]["rawTelemetryDigest"] = "1" * 64
        capture_settings = {
            "profileKind": "memory",
            "template": retained["evidence"]["trace"]["template"],
            "requestedDurationSeconds": 10.0,
            "targetProcess": summary["targetProcess"],
            "exactPID": True,
        }
        retained["evidence"]["trace"].update({
            "originalEphemeralPath": summary["artifact"],
            "summaryArtifact": {
                "path": "build/profiles/fixture-summary.json",
                "digest": "e" * 64,
            },
            "rawTraceRetained": False,
            "retentionPolicy": "summaryOnly",
            "captureSettings": capture_settings,
            "captureSettingsDigest": history.sha256_bytes(
                history.canonical_bytes(capture_settings)
            ),
        })
        self.publish(retained, "profile-memory-retention-valid")

        explicit = copy.deepcopy(retained)
        explicit["run"]["id"] = "profile-memory-retention-kept"
        explicit["evidence"]["rawTelemetryDigest"] = "2" * 64
        explicit["evidence"]["trace"]["retentionPolicy"] = "keptExplicitly"
        explicit["evidence"]["trace"]["rawTraceRetained"] = True
        self.publish(explicit, "profile-memory-retention-kept")

        # A memory profile keeps its raw trace by default (audit #69).
        by_default = copy.deepcopy(explicit)
        by_default["run"]["id"] = "profile-memory-retention-default"
        by_default["evidence"]["rawTelemetryDigest"] = "3" * 64
        by_default["evidence"]["trace"]["retentionPolicy"] = "keptByDefault"
        self.publish(by_default, "profile-memory-retention-default")
        discarded = copy.deepcopy(by_default)
        discarded["run"]["id"] = "profile-memory-retention-default-discarded"
        discarded["evidence"]["trace"]["rawTraceRetained"] = False
        with self.assertRaisesRegex(history.HistoryError, "conflicts with its retentionPolicy"):
            self.publish(discarded, discarded["run"]["id"])

        for label, mutate, message in (
            (
                "missing",
                lambda trace: trace.pop("summaryArtifact"),
                "metadata is incomplete",
            ),
            (
                "policy",
                lambda trace: trace.__setitem__("rawTraceRetained", True),
                "conflicts with its retentionPolicy",
            ),
            (
                "capture-digest",
                lambda trace: trace.__setitem__("captureSettingsDigest", "0" * 64),
                "does not match captureSettings",
            ),
            (
                "summary-inside-trace",
                lambda trace: trace["summaryArtifact"].__setitem__(
                    "path", "build/profiles/fixture.trace/summary.json"
                ),
                "outside the ephemeral trace bundle",
            ),
        ):
            invalid = copy.deepcopy(retained)
            invalid["run"]["id"] = f"profile-memory-retention-{label}"
            invalid["evidence"]["rawTelemetryDigest"] = str(
                3 + ("missing", "policy", "capture-digest", "summary-inside-trace").index(label)
            ) * 64
            mutate(invalid["evidence"]["trace"])
            with self.subTest(retention=label), self.assertRaisesRegex(
                history.HistoryError, message
            ):
                self.publish(invalid, f"profile-memory-retention-{label}")

        for key in (
            "memoryTraceEvidenceVersion", "allocationTargetDataBytes",
            "allocationTrackPresent", "allocationListPresent",
            "allocationDataExportStatus", "allocationTargetRowCount",
            "vmTrackerTrackPresent", "vmTrackerRegionMapPresent",
            "vmTrackerDataExportStatus", "vmTrackerTargetRowCount",
        ):
            invalid = copy.deepcopy(record)
            invalid["run"]["id"] = f"profile-memory-missing-{key}"
            invalid["evidence"]["trace"]["summary"].pop(key)
            with self.subTest(key=key), self.assertRaises(history.HistoryError):
                self.publish(invalid, f"profile-memory-missing-{key}")

        for status_key, count_key, label in (
            ("allocationDataExportStatus", "allocationTargetRowCount", "Allocations"),
            ("vmTrackerDataExportStatus", "vmTrackerTargetRowCount", "VM Tracker"),
        ):
            invalid = copy.deepcopy(record)
            invalid["run"]["id"] = f"profile-memory-empty-{count_key}"
            invalid["evidence"]["trace"]["summary"][status_key] = "targetRows"
            with self.subTest(label=label), self.assertRaisesRegex(
                history.HistoryError, f"exact-PID {label} exported rows"
            ):
                self.publish(invalid, f"profile-memory-empty-{count_key}")

    def test_prosody_requires_exact_aggregate_semantics(self) -> None:
        run_id = "prosody-invalid"
        for index, mutate in enumerate((
            lambda take: take["metrics"].__setitem__("goodClipCount", 1.0),
            lambda take: take["metrics"].pop("observedTruePositiveRate"),
            lambda take: take.__setitem__("cell", "another-cell"),
        )):
            take = prosody_take(run_id)
            mutate(take)
            record = record_fixture(run_id=run_id, kind="prosody-calibration", takes=[take])
            record["models"] = []
            record["inputs"]["corpusHash"] = "a" * 64
            record["inputs"]["analysisProfileHash"] = "b" * 64
            record["evidence"]["telemetrySchemaVersion"] = "not-applicable"
            record["evidence"]["qcAlgorithmVersion"] = "not-applicable"
            with self.assertRaises(history.HistoryError):
                self.publish(record, f"prosody-invalid-{index}")

    def test_required_hardware_and_cell_aggregates_cannot_be_removed(self) -> None:
        path = self.publish(record_fixture())
        for section, key in (("hardware", "uptimeSeconds"), ("cells", "worstThermalState")):
            record = json.loads(path.read_text())
            if section == "cells":
                record["cells"][0].pop(key)
            else:
                record[section].pop(key)
            record["digest"] = history.record_digest(record)
            with self.assertRaises(history.HistoryError):
                history.validate_record(record)

    def test_machine_labels_and_warnings_reject_free_form_content(self) -> None:
        cases = [
            lambda record: record["run"].__setitem__("label", "Patrice iPhone benchmark"),
            lambda record: record["run"]["warnings"].append("raw engine failure text"),
            lambda record: record["takes"][0]["warnings"].append("private transcript text"),
            lambda record: record["takes"][0]["audioQC"]["warningCodes"].append("voice description"),
        ]
        for index, mutate in enumerate(cases):
            record = record_fixture(run_id=f"privacy-machine-{index}")
            mutate(record)
            with self.assertRaises(history.HistoryError):
                self.publish(record, f"privacy-machine-{index}")

    def test_machine_warning_accepts_a_bounded_numeric_threshold(self) -> None:
        record = record_fixture(run_id="bounded-warning")
        record["run"]["warnings"] = ["uiperf.cadence:ios-player-scrub(34/55-65)"]
        path = self.publish(record, "bounded-warning")
        self.assertEqual(
            json.loads(path.read_text())["run"]["warnings"],
            ["uiperf.cadence:ios-player-scrub(34/55-65)"],
        )

    def test_out_of_order_publish_reconciles_nearest_earlier_baseline(self) -> None:
        later = record_fixture(run_id="compatible-later")
        later["run"]["startedAt"] = "2026-07-12T12:20:00Z"
        later["run"]["finishedAt"] = "2026-07-12T12:21:00Z"
        later_path = self.publish(later, "later-first")
        self.assertIsNone(json.loads(later_path.read_text())["comparison"]["baselineRunID"])

        earlier = record_fixture(run_id="compatible-earlier")
        earlier["takes"][0]["metrics"]["rtf"] = 1.5
        earlier["run"]["startedAt"] = "2026-07-12T12:10:00Z"
        earlier["run"]["finishedAt"] = "2026-07-12T12:11:00Z"
        self.publish(earlier, "earlier-second")
        reconciled = json.loads(later_path.read_text())
        self.assertEqual(reconciled["comparison"]["baselineRunID"], "compatible-earlier")
        history.validate_all()

    def test_failed_out_of_order_index_write_restores_reconciled_records(self) -> None:
        later = record_fixture(run_id="rollback-later")
        later["run"]["startedAt"] = "2026-07-12T12:20:00Z"
        later["run"]["finishedAt"] = "2026-07-12T12:21:00Z"
        later_path = self.publish(later, "rollback-later")
        before = later_path.read_bytes()

        earlier = record_fixture(run_id="rollback-earlier")
        earlier["takes"][0]["metrics"]["rtf"] = 1.5
        earlier["run"]["startedAt"] = "2026-07-12T12:10:00Z"
        earlier["run"]["finishedAt"] = "2026-07-12T12:11:00Z"
        original_writer = history.atomic_text_write
        calls = 0

        def fail_once(path: Path, text: str) -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("simulated index failure")
            original_writer(path, text)

        with (
            mock.patch.object(history, "atomic_text_write", side_effect=fail_once),
            self.assertRaises(OSError),
        ):
            self.publish(earlier, "rollback-earlier")
        self.assertEqual(later_path.read_bytes(), before)
        self.assertFalse((self.runs / "ui-generation" / "rollback-earlier.json").exists())
        history.validate_all()

    def test_index_check_rejects_and_rebuild_repairs_stale_comparison(self) -> None:
        first = record_fixture(run_id="comparison-first")
        self.publish(first, "comparison-first")
        second = record_fixture(run_id="comparison-second")
        second["takes"][0]["metrics"]["rtf"] = 2.5
        second["run"]["startedAt"] = "2026-07-12T12:10:00Z"
        second["run"]["finishedAt"] = "2026-07-12T12:11:00Z"
        second_path = self.publish(second, "comparison-second")
        stale = json.loads(second_path.read_text())
        stale["comparison"]["baselineRunID"] = None
        stale["comparison"]["deltas"] = {}
        stale["digest"] = history.record_digest(stale)
        second_path.write_text(json.dumps(stale), encoding="utf-8")
        with self.assertRaisesRegex(history.HistoryError, "comparison metadata is stale"):
            history.rebuild_index(check=True)
        history.rebuild_index()
        repaired = json.loads(second_path.read_text())
        self.assertEqual(repaired["comparison"]["baselineRunID"], "comparison-first")

    def test_cell_statistics_group_repetitions_without_losing_take_identity(self) -> None:
        takes = []
        for index, rtf in enumerate((1.0, 2.0, 3.0), start=1):
            take = generation_take(index)
            take["cell"] = f"custom/short/warm#{index - 1}"
            take["metrics"]["rtf"] = rtf
            takes.append(take)
        cells = history.aggregate_cells(takes)
        self.assertEqual([take["cell"] for take in takes], [
            "custom/short/warm#0", "custom/short/warm#1", "custom/short/warm#2",
        ])
        self.assertEqual(len(cells), 1)
        self.assertEqual(cells[0]["key"], "custom/short/warm")
        self.assertEqual(cells[0]["count"], 3)
        self.assertEqual(cells[0]["statistics"]["rtf"]["median"], 2.0)
        self.assertGreater(cells[0]["statistics"]["rtf"]["iqr"], 0)

    def test_failed_success_contract_never_writes(self) -> None:
        mutations = []
        mutations.append(lambda record: record["evidence"].__setitem__("crashDeltaPassed", False))
        mutations.append(lambda record: record["evidence"].__setitem__("validatorPassed", False))
        mutations.append(lambda record: record["evidence"].__setitem__("actualTakeCount", 0))
        mutations.append(lambda record: record["takes"][0].__setitem__("takeIndex", 2))
        mutations.append(lambda record: record["takes"][0].__setitem__("finishReason", "failed"))
        mutations.append(lambda record: record["takes"][0].__setitem__("layerCompleteness", "partial"))
        mutations.append(lambda record: record["takes"][0]["audioQC"].__setitem__("verdict", "fail"))
        mutations.append(lambda record: record["takes"][0]["audioQC"].pop("instabilityVerdict"))
        mutations.append(lambda record: record["takes"][0]["audioQC"].__setitem__("writtenOutputVerdict", "fail"))
        mutations.append(lambda record: record["takes"][0]["audioQC"].__setitem__("algorithmVersion", 1))
        mutations.append(lambda record: record["takes"][0]["output"].__setitem__("readableWAV", False))
        for index, mutate in enumerate(mutations):
            record = record_fixture(run_id=f"invalid-{index}-20260712")
            mutate(record)
            with self.assertRaises(history.HistoryError):
                self.publish(record, name=f"invalid-{index}")
        self.assertEqual(history.all_record_paths(), [])

    def test_duplicate_run_and_evidence_conflicts_fail(self) -> None:
        record = record_fixture()
        self.publish(record, "first")
        changed = copy.deepcopy(record)
        changed["run"]["label"] = "different"
        with self.assertRaisesRegex(history.HistoryError, "run ID already exists"):
            self.publish(changed, "second")

        first_record = json.loads((self.runs / "ui-generation" / "macos-bench-20260712-120000.json").read_text())
        second_record = copy.deepcopy(first_record)
        second_record["run"]["id"] = "different-run-20260712"
        second_record["digest"] = history.record_digest(second_record)
        with self.assertRaisesRegex(history.HistoryError, "duplicate evidence digest"):
            history.validate_all([
                (self.runs / "ui-generation" / "macos-bench-20260712-120000.json", first_record),
                (self.runs / "ui-generation" / "different-run-20260712.json", second_record),
            ])

    def test_privacy_and_unknown_fields_are_rejected(self) -> None:
        cases = [
            ("deviceName", "Patrice phone"),
            ("label", "/Users/example/private/run"),
            ("label", "private/run"),
            ("label", "person@example.com"),
            ("label", "https://example.com/run"),
        ]
        for index, (key, value) in enumerate(cases):
            record = record_fixture(run_id=f"privacy-{index}-20260712")
            if key == "deviceName":
                record["hardware"][key] = value
            else:
                record["run"][key] = value
            with self.assertRaises(history.HistoryError):
                self.publish(record, f"privacy-{index}")

    def test_oversized_record_is_rejected_before_publish(self) -> None:
        record = record_fixture()
        record["run"]["warnings"] = ["x" * 260_000]
        with self.assertRaises(history.HistoryError):
            self.publish(record)
        self.assertEqual(history.all_record_paths(), [])

    def test_index_check_detects_drift(self) -> None:
        self.publish(record_fixture())
        history.rebuild_index(check=True)
        self.index.write_text("edited\n", encoding="utf-8")
        with self.assertRaisesRegex(history.HistoryError, "not reproducible"):
            history.rebuild_index(check=True)

    def test_annotation_is_private_safe_and_idempotent(self) -> None:
        path = self.publish(record_fixture())
        first = history.annotate("macos-bench-20260712-120000", "pass", "Listening review passed")
        before = first.read_bytes()
        second = history.annotate("macos-bench-20260712-120000", "pass", "Listening review passed")
        self.assertEqual(path, second)
        self.assertEqual(before, second.read_bytes())
        with self.assertRaises(history.HistoryError):
            history.annotate("macos-bench-20260712-120000", "pass", "/Users/example/review")

    def test_registry_tree_rejects_unknown_files_directories_and_kinds(self) -> None:
        cases = [
            ("ui-generation/raw.ndjson", False),
            ("ui-generation/nested", True),
            ("unknown-kind/run.json", False),
        ]
        for index, (relative, directory) in enumerate(cases):
            with self.subTest(relative=relative):
                path = self.runs / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                if directory:
                    path.mkdir()
                else:
                    path.write_text("{}\n", encoding="utf-8")
                with self.assertRaises(history.HistoryError):
                    history.validate_all()
                if path.is_dir():
                    path.rmdir()
                else:
                    path.unlink()
                unknown_parent = self.runs / "unknown-kind"
                if unknown_parent.exists():
                    unknown_parent.rmdir()

    def test_storage_scan_rejects_raw_files_and_bundle_directories(self) -> None:
        raw = self.root / "captured-audio.caf"
        raw.write_bytes(b"raw")
        with (
            mock.patch.object(history, "BENCHMARK_ROOT", self.root),
            self.assertRaisesRegex(history.HistoryError, "raw benchmark artifact"),
        ):
            history.validate_benchmark_storage_tree()
        raw.unlink()

        bundle = self.root / "result.xcresult"
        bundle.mkdir()
        with (
            mock.patch.object(history, "BENCHMARK_ROOT", self.root),
            self.assertRaisesRegex(history.HistoryError, "raw benchmark bundle"),
        ):
            history.validate_benchmark_storage_tree()

    def test_schema_rejects_duplicate_keys_and_contract_drift(self) -> None:
        original = self.schema.read_text(encoding="utf-8")
        self.schema.write_text(
            original.replace('"title": "Vocello benchmark history record",',
                             '"title": "first",\n  "title": "second",'),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(history.HistoryError, "duplicate JSON key: title"):
            history.validate_all()

        schema = json.loads(original)
        schema["$defs"]["run"]["properties"]["kind"]["enum"].remove("language")
        self.schema.write_text(json.dumps(schema), encoding="utf-8")
        with self.assertRaisesRegex(history.HistoryError, "run.kind enum drifted"):
            history.validate_all()

    def test_every_record_is_evaluated_against_schema_v1(self) -> None:
        self.publish(record_fixture())
        schema = json.loads(self.schema.read_text(encoding="utf-8"))
        schema["$defs"]["run"]["properties"]["label"]["maxLength"] = 2
        self.schema.write_text(json.dumps(schema), encoding="utf-8")
        with self.assertRaisesRegex(history.HistoryError, "run.label exceeds"):
            history.validate_all()


    def test_canonical_m6_record_validates_and_schema_v1_stays_frozen(self) -> None:
        m6 = quality_v3_language_fixture("language-m6-v3")
        m6["hardware"].update(M6_HARDWARE)
        path = self.publish(m6, "language-m6-v3")
        published = json.loads(path.read_text())
        self.assertEqual(published["hardware"]["profileID"], "mac-mini-m6-16gb")
        self.assertEqual(published["hardware"]["memoryBytes"], 17_179_869_184)
        history.validate_all()

        # schema-v1 predates the M6 and is frozen: it cannot carry an M6 record.
        legacy = record_fixture(run_id="macos-m6-v1")
        legacy["hardware"].update(M6_HARDWARE)
        with self.assertRaises(history.HistoryError):
            self.publish(legacy, "macos-m6-v1")

        # A record cannot borrow the retired M2 profile ID for M6 hardware.
        mislabeled = quality_v3_language_fixture("language-m6-mislabeled")
        mislabeled["hardware"].update(M6_HARDWARE)
        mislabeled["hardware"]["profileID"] = "mac-mini-m2-8gb"
        with self.assertRaisesRegex(history.HistoryError, "does not match the canonical profile"):
            self.publish(mislabeled, "language-m6-mislabeled")

    def test_m2_and_m6_records_never_share_a_comparison_key(self) -> None:
        m2 = record_fixture()
        m6 = copy.deepcopy(m2)
        m6["hardware"].update(M6_HARDWARE)
        self.assertNotEqual(history.comparison_key(m2), history.comparison_key(m6))
        self.assertEqual(history.comparison_key(m2), history.comparison_key(copy.deepcopy(m2)))

    def test_registry_names_exactly_one_canonical_profile_per_platform(self) -> None:
        profiles = history.load_profiles()
        platforms = {profile["platform"] for profile in profiles.values()}
        self.assertEqual(platforms, {"macos", "ios"})
        for platform in sorted(platforms):
            canonical = [
                profile["id"] for profile in profiles.values()
                if profile["platform"] == platform and profile.get("canonical") is True
            ]
            self.assertEqual(len(canonical), 1, (platform, canonical))
        self.assertIs(profiles["mac-mini-m2-8gb"]["canonical"], False)
        self.assertIs(profiles["mac-mini-m6-16gb"]["canonical"], True)

    def test_schema_v1_profiles_are_a_subset_while_live_schemas_match_exactly(self) -> None:
        for version in (1, 2, 3):
            history.load_schema_contract(version)

        schema = json.loads(self.schema.read_text(encoding="utf-8"))
        schema["$defs"]["hardware"]["properties"]["profileID"]["enum"].append("unregistered-mac")
        self.schema.write_text(json.dumps(schema), encoding="utf-8")
        with self.assertRaisesRegex(history.HistoryError, "hardware profiles drifted"):
            history.load_schema_contract(1)

        for version in (2, 3):
            live = json.loads(history.SCHEMA_PATHS[version].read_text(encoding="utf-8"))
            live["$defs"]["hardware"]["properties"]["profileID"]["enum"].remove("mac-mini-m6-16gb")
            stale = self.root / f"schema-v{version}-stale.json"
            stale.write_text(json.dumps(live), encoding="utf-8")
            with (
                self.subTest(version=version),
                mock.patch.dict(history.SCHEMA_PATHS, {version: stale}),
                self.assertRaisesRegex(history.HistoryError, "hardware profiles drifted"),
            ):
                history.load_schema_contract(version)


if __name__ == "__main__":
    unittest.main()
