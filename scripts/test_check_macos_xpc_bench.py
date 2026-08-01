#!/usr/bin/env python3
"""Focused fixtures for check_macos_xpc_bench.py ordering and output gates."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
TEST_HELPERS = ROOT / "scripts" / "tests"
if str(TEST_HELPERS) not in sys.path:
    sys.path.insert(0, str(TEST_HELPERS))
from test_benchmark_memory import ENGINE_BOUNDARIES, row as memory_row, samples as memory_samples
CHECK = ROOT / "scripts" / "check_macos_xpc_bench.py"
RUN_ID = "mac-ui-order-fixture"


def make_engine_row(index: int, cell: str) -> dict:
    mode, _, state_and_repetition = cell.split("/")
    warm_state, _ = state_and_repetition.split("#")
    generation_id = f"fixture-{index}"
    return {
        "generationID": generation_id,
        "mode": mode,
        "warmState": warm_state,
        "finishReason": "completed",
        "derivedMetrics": {"generatedTokenCount": 100 + index},
        "stageMarks": [],
        "notes": {
            "benchRunID": RUN_ID,
            "benchTakeIndex": str(index),
            "benchCell": cell,
            "quality_registry_outcome": "pass",
            "quality_registry_required_gates": "terminal,token_cap,codec_behavior,persisted_wav,streaming_continuity",
        },
        "outputMetrics": {
            "readableWAV": True,
            "atomicallyPublished": True,
            "durationSeconds": 1.0,
        },
        "audioQC": {"verdict": "pass", "flags": []},
    }


def v7_summary() -> dict:
    return {
        "targetIntervalNS": 500_000_000,
        "effectiveIntervalNS": 505_000_000,
        "maximumDriftNS": 5_000_000,
        "maximumLatenessNS": 5_000_000,
        "boundarySampleCount": 4,
        "captureFailureCount": 0,
        "processResourceUsage": {
            "userCPUTimeMS": 100.0, "systemCPUTimeMS": 20.0,
            "minorPageFaults": 1, "majorPageFaults": 0,
            "voluntaryContextSwitches": 2, "involuntaryContextSwitches": 1,
            "blockInputOperations": 0, "blockOutputOperations": 0,
        },
        "runEnvironment": {
            "loadAverage1Minute": 1.0, "freeStorageBytes": 1_000_000,
            "uptimeSeconds": 10.0, "lowPowerModeEnabled": False,
            "thermalState": "nominal",
        },
    }


def v7_frontend() -> dict:
    return {
        "submitToFirstChunkMS": 10, "submitToPlaybackScheduledMS": 30,
        "submitToCompletedMS": 100, "firstChunkToPlaybackScheduledMS": 20,
        "delayedHeartbeatCount50": 0, "delayedHeartbeatCount250": 0,
        "maximumDelayedHeartbeatMS": 0, "scheduledHeartbeatCount": 10,
        "completedHeartbeatCount": 10, "heartbeatCoveragePPM": 1_000_000,
        "playbackChunksReceived": 4, "playbackContinuityFailures": 0,
        "playbackUnderruns": 0, "playbackStartSource": "finalFile",
        "playbackStartBufferedChunks": 1,
        "playbackStartBufferedAudioMS": 120, "playbackMinimumQueuedAudioMS": 80,
    }


def upgrade_layers_to_v8(layers: dict[str, list[dict]], diagnostics: Path) -> None:
    for row in layers["engine"]:
        mode = row["mode"]
        model_id = f"pro_{mode}_speed"
        sidecar = memory_samples(
            role="engine", boundaries=ENGINE_BOUNDARIES, ios=False,
            footprint=2500 + int(str(row["generationID"]).rsplit("-", 1)[-1]),
        )
        memory = memory_row(row["generationID"], sidecar, layer="engine", ios=False)
        row["schemaVersion"] = 8
        row["summary"] = {**memory["summary"], **v7_summary()}
        row["summary"].update({
            "sampleCount": len(sidecar), "periodicSampleCount": 1,
            "boundarySampleCount": len(ENGINE_BOUNDARIES), "captureFailureCount": 0,
            "missedPeriodicDeadlineCount": 0,
            "captureCoverage": memory["summary"]["captureCoverage"],
            "boundaryCoverage": memory["summary"]["boundaryCoverage"],
        })
        row["memoryMetrics"] = memory["memoryMetrics"]
        row["backendMetrics"] = {"timings": [], "stages": []}
        row["modelID"] = model_id
        row["modelRuntimeIdentity"] = {
            "resolvedModelID": model_id, "modelVariant": "speed",
            "runtimeProfileSignature": f"{model_id}:fixture-v1",
            "modelRepository": "mlx-community/Qwen3-TTS-fixture",
            "huggingFaceRevision": "a" * 40, "artifactVersion": "fixture-v1",
            "quantization": "4-bit", "integrityManifestDigest": "b" * 64,
        }
        if mode in {"design", "clone"}:
            row["modelRuntimeIdentity"]["fixtureDigest"] = "d" * 64
        row["notes"]["promptDigest"] = "c" * 64
        (diagnostics / "engine").mkdir(exist_ok=True)
        (diagnostics / "engine" / f"samples-{row['generationID']}.jsonl").write_text(
            "".join(json.dumps(item) + "\n" for item in sidecar), encoding="utf-8"
        )
    for row in layers["engine-service"]:
        row["schemaVersion"] = 8
        row["transportMetrics"] = {
            "requestAccepted": True, "requestToFirstChunkMS": 9,
            "counters": {"chunkGaps": 0},
        }
    for row in layers["app"]:
        sidecar = memory_samples(
            role="app", boundaries=["app_submit", "app_terminal"], ios=False,
            footprint=200, uptime_offset=10_000_000,
        )
        memory = memory_row(row["generationID"], sidecar, layer="app", ios=False)
        row["schemaVersion"] = 8
        row["frontendMetrics"] = v7_frontend()
        row["summary"] = memory["summary"]
        row["summary"].update({
            "targetIntervalNS": 500_000_000, "effectiveIntervalNS": 500_000_000,
            "maximumDriftNS": 0, "maximumLatenessNS": 0,
            "missedPeriodicDeadlineCount": 0,
            "processResourceUsage": v7_summary()["processResourceUsage"],
            "runEnvironment": v7_summary()["runEnvironment"],
        })
        row["memoryMetrics"] = memory["memoryMetrics"]
        (diagnostics / "app").mkdir(exist_ok=True)
        (diagnostics / "app" / f"samples-{row['generationID']}.jsonl").write_text(
            "".join(json.dumps(item) + "\n" for item in sidecar), encoding="utf-8"
        )


class CheckMacOSXPCBenchmarkTests(unittest.TestCase):
    expected_order = [
        "custom/medium/cold#0",
        "custom/short/warm#0",
        "custom/medium/warm#0",
        "clone/short/warm#0",
        "clone/medium/warm#0",
    ]

    def run_checker(
        self,
        cells: list[str],
        mutate_engine_rows=None,
        mutate_layers=None,
        malformed_layer: str | None = None,
        evidence: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        self.last_manifest = None
        with tempfile.TemporaryDirectory() as temp:
            diagnostics = Path(temp)
            engine_rows = [
                make_engine_row(index, cell)
                for index, cell in enumerate(cells, start=1)
            ]
            if mutate_engine_rows is not None:
                mutate_engine_rows(engine_rows)

            correlated_rows = [
                {
                    "generationID": row["generationID"],
                    "finishReason": "completed",
                    "notes": {"benchRunID": RUN_ID},
                }
                for row in engine_rows
            ]
            layers = {
                "engine": engine_rows,
                "engine-service": [dict(row) for row in correlated_rows],
                "app": [dict(row) for row in correlated_rows],
                "merged": [
                    {
                        "generationID": row["generationID"],
                        "requiredLayers": ["app", "engine-service", "engine"],
                        "missingLayers": [],
                        "complete": True,
                        "engine": {"generationID": row["generationID"]},
                        "engineService": {"generationID": row["generationID"]},
                        "app": {"generationID": row["generationID"]},
                    }
                    for row in engine_rows
                ],
            }
            for row in layers["engine"]:
                row["processIdentifier"] = 42
            for row in layers["engine-service"]:
                row["processIdentifier"] = 42
            for row in layers["app"]:
                row["processIdentifier"] = 43
            for row in layers["merged"]:
                row["engine"]["processIdentifier"] = 42
                row["engineService"]["processIdentifier"] = 42
                row["app"]["processIdentifier"] = 43
            upgrade_layers_to_v8(layers, diagnostics)
            if mutate_layers is not None:
                mutate_layers(layers)
            for layer, rows in (
                ("engine", layers["engine"]),
                ("engine-service", layers["engine-service"]),
                ("app", layers["app"]),
            ):
                directory = diagnostics / layer
                directory.mkdir(exist_ok=True)
                path = directory / "generations.jsonl"
                path.write_text(
                    "".join(json.dumps(row) + "\n" for row in rows)
                    + ("{not-json\n" if malformed_layer == layer else ""),
                    encoding="utf-8",
                )
            (diagnostics / "generations-merged.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in layers["merged"])
                + ("{not-json\n" if malformed_layer == "merged" else ""),
                encoding="utf-8",
            )
            command = [
                sys.executable,
                str(CHECK),
                str(diagnostics),
                "--run-id",
                RUN_ID,
                "--modes",
                "custom,clone",
                "--lengths",
                "short,medium",
                "--warm",
                "1",
            ]
            manifest_path = diagnostics / "benchmark-evidence.json"
            if evidence:
                command.extend([
                    "--evidence-manifest",
                    str(manifest_path),
                    "--crash-delta-passed",
                    "--label",
                    "fixture",
                ])
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
            )
            if manifest_path.is_file():
                self.last_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            return result

    def test_quality_identity_stamps_schema_v3(self) -> None:
        result = self.run_checker(self.expected_order, evidence=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        record = self.last_manifest["historyRecord"]
        self.assertEqual(record["schemaVersion"], 3)
        for take in record["takes"]:
            self.assertEqual(take["qualityRegistryOutcome"], "pass")
            self.assertEqual(
                take["qualityRegistryRequiredGates"],
                ["codec_behavior", "persisted_wav", "streaming_continuity", "terminal", "token_cap"],
            )

    def test_rows_without_registry_notes_publish_schema_v2(self) -> None:
        def strip(rows: list[dict]) -> None:
            for row in rows:
                row["notes"].pop("quality_registry_outcome")
                row["notes"].pop("quality_registry_required_gates")

        result = self.run_checker(self.expected_order, strip, evidence=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        record = self.last_manifest["historyRecord"]
        self.assertEqual(record["schemaVersion"], 2)
        self.assertTrue(all("qualityRegistryOutcome" not in take for take in record["takes"]))

    def test_mixed_registry_identity_refuses_partial_v3(self) -> None:
        def strip_first(rows: list[dict]) -> None:
            rows[0]["notes"].pop("quality_registry_outcome")
            rows[0]["notes"].pop("quality_registry_required_gates")

        result = self.run_checker(self.expected_order, strip_first, evidence=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refusing a partial schema-v3 record", result.stdout + result.stderr)

    def test_exact_order_and_pass_qc_pass(self) -> None:
        result = self.run_checker(self.expected_order)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_same_distribution_with_sequential_indices_in_wrong_order_fails(self) -> None:
        reordered = self.expected_order.copy()
        reordered[1], reordered[2] = reordered[2], reordered[1]
        result = self.run_checker(reordered)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("benchmark cell order differs", result.stdout + result.stderr)

    def test_missing_audio_qc_fails(self) -> None:
        def remove_audio_qc(rows: list[dict]) -> None:
            rows[0].pop("audioQC")

        result = self.run_checker(self.expected_order, remove_audio_qc)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("audioQC verdict is missing", result.stdout + result.stderr)

    def test_failed_audio_qc_fails(self) -> None:
        def fail_audio_qc(rows: list[dict]) -> None:
            rows[0]["audioQC"] = {"verdict": "fail", "flags": ["fixture"]}

        result = self.run_checker(self.expected_order, fail_audio_qc)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("audioQC failed", result.stdout + result.stderr)

    def test_audio_qc_warning_is_accepted(self) -> None:
        def warn_audio_qc(rows: list[dict]) -> None:
            rows[0]["audioQC"] = {"verdict": "warn", "flags": ["fixture"]}

        result = self.run_checker(self.expected_order, warn_audio_qc)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_evidence_manifest_contains_exact_order_and_complete_layers(self) -> None:
        result = self.run_checker(self.expected_order, evidence=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        manifest = self.last_manifest
        self.assertIsNotNone(manifest)
        self.assertEqual(manifest["runID"], RUN_ID)
        self.assertEqual(manifest["matrix"]["orderedCells"], self.expected_order)
        self.assertEqual(
            [take["generationID"] for take in manifest["takes"]],
            [f"fixture-{index}" for index in range(1, 6)],
        )
        self.assertTrue(all(manifest["layers"][key]["complete"] for key in manifest["layers"]))
        self.assertTrue(manifest["historyRecord"]["evidence"]["crashDeltaPassed"])
        first_metrics = manifest["historyRecord"]["takes"][0]["metrics"]
        self.assertEqual(first_metrics["generatedTokens"], 101)
        self.assertEqual(first_metrics["memoryTrimCount"], 0)
        self.assertEqual(first_metrics["maximumTrimLevel"], 0)
        self.assertEqual(
            manifest["historyRecord"]["takes"][0]["playbackStartSource"],
            "finalFile",
        )
        self.assertEqual(manifest["schemaVersion"], 2)
        self.assertEqual(manifest["historyRecord"]["evidence"]["sampleSidecarCount"], 10)

    def test_missing_correlated_layer_row_fails_without_evidence(self) -> None:
        def remove_app_row(layers: dict[str, list[dict]]) -> None:
            layers["app"].pop()

        result = self.run_checker(
            self.expected_order,
            mutate_layers=remove_app_row,
            evidence=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("app rows 4 != expected 5", result.stdout + result.stderr)
        self.assertIsNone(self.last_manifest)

    def test_incomplete_merged_row_fails(self) -> None:
        def remove_nested_app(layers: dict[str, list[dict]]) -> None:
            layers["merged"][0].pop("app")

        result = self.run_checker(self.expected_order, mutate_layers=remove_nested_app)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing complete layer payloads: app", result.stdout + result.stderr)

    def test_process_ownership_rejects_same_app_and_engine_pid(self) -> None:
        def share_pid(layers: dict[str, list[dict]]) -> None:
            layers["app"][0]["processIdentifier"] = 42
            layers["merged"][0]["app"]["processIdentifier"] = 42

        result = self.run_checker(self.expected_order, mutate_layers=share_pid)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("app and engine unexpectedly share PID", result.stdout + result.stderr)

    def test_process_ownership_rejects_engine_service_pid_mismatch(self) -> None:
        def mismatch(layers: dict[str, list[dict]]) -> None:
            layers["engine-service"][0]["processIdentifier"] = 44
            layers["merged"][0]["engineService"]["processIdentifier"] = 44

        result = self.run_checker(self.expected_order, mutate_layers=mismatch)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("engine PID 42 != engine-service PID 44", result.stdout + result.stderr)

    def test_process_ownership_rejects_invalid_and_nested_mismatched_pid(self) -> None:
        for value in (None, True, 0, -1):
            def invalid(layers: dict[str, list[dict]], value=value) -> None:
                layers["engine"][0]["processIdentifier"] = value

            with self.subTest(value=value):
                result = self.run_checker(self.expected_order, mutate_layers=invalid)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("invalid processIdentifier", result.stdout + result.stderr)

        def nested_mismatch(layers: dict[str, list[dict]]) -> None:
            layers["merged"][0]["app"]["processIdentifier"] = 99

        result = self.run_checker(self.expected_order, mutate_layers=nested_mismatch)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("app PID 99 != layer PID 43", result.stdout + result.stderr)

    def test_duplicate_layer_generation_id_fails(self) -> None:
        def duplicate_service_id(layers: dict[str, list[dict]]) -> None:
            layers["engine-service"][1]["generationID"] = "fixture-1"

        result = self.run_checker(self.expected_order, mutate_layers=duplicate_service_id)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("engine-service generationIDs are not unique", result.stdout + result.stderr)

    def test_malformed_jsonl_fails(self) -> None:
        result = self.run_checker(self.expected_order, malformed_layer="engine")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("malformed JSON", result.stdout + result.stderr)

    def test_schema_v8_complete_accuracy_evidence_passes(self) -> None:
        result = self.run_checker(self.expected_order)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_schema_v8_missing_sampler_resource_or_environment_fails(self) -> None:
        for field, message in (
            ("maximumDriftNS", "invalid sampler maximumDriftNS"),
            ("processResourceUsage", "incomplete process resource deltas"),
            ("runEnvironment", "has no run environment"),
        ):
            def mutate(layers, field=field):
                layers["engine"][0]["summary"].pop(field)
            with self.subTest(field=field):
                result = self.run_checker(self.expected_order, mutate_layers=mutate)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stdout + result.stderr)

    def test_schema_v8_transport_acceptance_and_latency_are_required(self) -> None:
        for field, value, message in (
            ("requestAccepted", False, "was not accepted by XPC transport"),
            ("requestToFirstChunkMS", None, "has no request-to-first-chunk"),
        ):
            def mutate(layers, field=field, value=value):
                layers["engine-service"][0]["transportMetrics"][field] = value
            with self.subTest(field=field):
                result = self.run_checker(self.expected_order, mutate_layers=mutate)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stdout + result.stderr)

    def test_schema_v8_frontend_lifecycle_and_playback_health_are_required(self) -> None:
        def mutate(layers):
            layers["app"][0]["frontendMetrics"].pop("playbackMinimumQueuedAudioMS")
        result = self.run_checker(self.expected_order, mutate_layers=mutate)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("incomplete typed frontend lifecycle/playback", result.stdout + result.stderr)

    def test_schema_v8_frontend_source_and_lifecycle_order_are_required(self) -> None:
        def missing_source(layers):
            layers["app"][0]["frontendMetrics"].pop("playbackStartSource")
        result = self.run_checker(self.expected_order, mutate_layers=missing_source)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid playback start source", result.stdout + result.stderr)

        def inconsistent_order(layers):
            layers["app"][0]["frontendMetrics"]["submitToPlaybackScheduledMS"] = 9
        result = self.run_checker(self.expected_order, mutate_layers=inconsistent_order)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("inconsistent frontend lifecycle ordering", result.stdout + result.stderr)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
