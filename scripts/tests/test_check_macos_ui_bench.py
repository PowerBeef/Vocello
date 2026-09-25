#!/usr/bin/env python3
"""Focused fixtures for check_macos_ui_bench.py ordering and output gates."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
TEST_HELPERS = ROOT / "scripts" / "tests"
if str(TEST_HELPERS) not in sys.path:
    sys.path.insert(0, str(TEST_HELPERS))
from test_benchmark_memory import ENGINE_BOUNDARIES, row as memory_row, samples as memory_samples
CHECK = ROOT / "scripts" / "check_macos_ui_bench.py"
RUN_ID = "mac-ui-order-fixture"


def write_provenance_fixture(directory: Path, *, optimization: str = "O") -> Path:
    """A build receipt bound to a real tracked file, exactly as write_build_provenance emits it."""
    executable = ROOT / "scripts" / "dev.sh"
    payload = {
        "schemaVersion": 1,
        "producer": "scripts/ui_test.sh macos benchmark",
        "status": "passed",
        "platform": "macos",
        "scheme": "fixture",
        "configuration": "Release",
        "optimization": optimization,
        "executableRelativePath": "scripts/dev.sh",
        "executableSHA256": hashlib.sha256(executable.read_bytes()).hexdigest(),
    }
    path = directory / "last-build.json"
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    return path


def make_engine_row(index: int, cell: str) -> dict:
    mode, _, state_and_repetition = cell.split("/")
    warm_state, _ = state_and_repetition.split("#")
    generation_id = f"fixture-{index}"
    return {
        "generationID": generation_id,
        "mode": mode,
        "warmState": warm_state,
        "finishReason": "completed",
        "derivedMetrics": {
            "generatedTokenCount": 100 + index,
            "audioSeconds": 4.0,
            "requestWallSeconds": 2.5,
            "realTimeFactor": 0.625,
            "audioSecondsPerWallSecond": 1.8,
        },
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


class CheckMacOSUIBenchmarkTests(unittest.TestCase):
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
        extra_args: list[str] | None = None,
        in_process=None,
    ) -> subprocess.CompletedProcess[str]:
        """Run the checker on a fixture; `in_process` is the imported checker
        module to call directly (so a test can observe it) instead of a subprocess."""
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
                "app": [dict(row) for row in correlated_rows],
                "merged": [
                    {
                        "generationID": row["generationID"],
                        "requiredLayers": ["app", "engine"],
                        "missingLayers": [],
                        "complete": True,
                        "engine": {"generationID": row["generationID"]},
                        "app": {"generationID": row["generationID"]},
                    }
                    for row in engine_rows
                ],
            }
            # One process hosts the app and the engine.
            for row in layers["engine"]:
                row["processIdentifier"] = 42
            for row in layers["app"]:
                row["processIdentifier"] = 42
            for row in layers["merged"]:
                row["engine"]["processIdentifier"] = 42
                row["app"]["processIdentifier"] = 42
            upgrade_layers_to_v8(layers, diagnostics)
            if mutate_layers is not None:
                mutate_layers(layers)
            for layer, rows in (
                ("engine", layers["engine"]),
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
                    "--build-provenance",
                    str(write_provenance_fixture(diagnostics)),
                    "--label",
                    "fixture",
                ])
            command.extend(extra_args or [])
            if in_process is not None:
                output = io.StringIO()
                with mock.patch.object(sys, "argv", command[1:]), contextlib.redirect_stdout(output):
                    status = in_process.main()
                result = subprocess.CompletedProcess(command, status, output.getvalue(), "")
            else:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    check=False,
                )
            if manifest_path.is_file():
                self.last_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            return result

    def test_in_process_memory_is_one_series_not_the_sum_of_two_samplers(self) -> None:
        # Audit #1/#2: the app and engine samplers read the one hosting process;
        # the published peak is that process's largest reading, never a sum.
        result = self.run_checker(self.expected_order, evidence=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        record = self.last_manifest["historyRecord"]
        self.assertEqual(record["evidence"]["memoryContractVersion"], 2)
        self.assertEqual(record["evidence"]["sampleSidecarCount"], 2 * len(self.expected_order))
        for index, take in enumerate(record["takes"], start=1):
            metrics = take["metrics"]
            engine_peak = 2500 + index + len(ENGINE_BOUNDARIES) + 2
            self.assertEqual(metrics["peakPhysicalFootprintMB"], engine_peak)
            self.assertNotIn("alignedProcessSampleCoverage", metrics)
            self.assertIn("samplerMaximumUnobservedGapMS", metrics)
            self.assertEqual(metrics["gpuPeakCaptureMissMB"], 2200.0 - metrics["peakGPUAllocatedMB"])

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

    def test_manifest_hardware_is_the_registry_canonical_macos_profile(self) -> None:
        registry = json.loads((ROOT / "benchmarks" / "hardware-profiles.json").read_text(encoding="utf-8"))
        canonical = [
            profile["id"] for profile in registry["profiles"]
            if profile["platform"] == "macos" and profile.get("canonical") is True
        ]
        self.assertEqual(canonical, ["mac-mini-m6-16gb"])
        result = self.run_checker(self.expected_order, evidence=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.last_manifest["historyRecord"]["hardware"]["profileID"], canonical[0])

    def run_with_stalls(
        self, device_class: str | None, *, forced: bool = False, stalls: int = 2,
        maximum_ms: int = 300, extra_args: list[str] | None = None, evidence: bool = False,
    ):
        def set_device_class(rows: list[dict]) -> None:
            for row in rows:
                if device_class is not None:
                    row["notes"]["deviceClass"] = device_class
                row["notes"]["deviceClassForced"] = "true" if forced else "false"

        def add_stalls(layers: dict[str, list[dict]]) -> None:
            frontend = layers["app"][0]["frontendMetrics"]
            frontend["delayedHeartbeatCount50"] = stalls
            frontend["delayedHeartbeatCount250"] = 1 if maximum_ms > 250 else 0
            frontend["maximumDelayedHeartbeatMS"] = maximum_ms

        return self.run_checker(
            self.expected_order, set_device_class, add_stalls, extra_args=extra_args, evidence=evidence,
        )

    def write_stall_contract(self, directory: Path, **overrides) -> Path:
        contract = json.loads((ROOT / "config" / "macos-ui-stall-gate.json").read_text(encoding="utf-8"))
        contract.update(overrides)
        path = directory / "stall-contract.json"
        path.write_text(json.dumps(contract), encoding="utf-8")
        return path

    def test_main_thread_stall_gate_covers_every_native_mac_tier(self) -> None:
        # Engine rows stamp the raw NativeDeviceMemoryClass value; the case name is accepted too.
        for device_class in ("mid_16gb_mac", "mid16GBMac", "high_memory_mac", "floor_8gb_mac", "floor8GBMac"):
            with self.subTest(device_class=device_class):
                result = self.run_with_stalls(device_class)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        with self.subTest("mid16GBMac without stalls"):
            result = self.run_with_stalls("mid_16gb_mac", stalls=0, maximum_ms=0)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_delayed_heartbeats_within_the_provisional_limit_pass(self) -> None:
        """audit #6: the old zero tolerance on 50 ms heartbeats failed 90% of M2 takes."""
        result = self.run_with_stalls("mid_16gb_mac", stalls=4, maximum_ms=250, evidence=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        stall = self.last_manifest["stallGate"]
        self.assertEqual(
            (stall["gatedTakeCount"], stall["median"], stall["p90"], stall["maximum"], stall["takesAboveLimit"]),
            (5, 0, 250, 250, 0),
        )

    def test_main_thread_stall_gate_skips_forced_non_floor_tiers_only(self) -> None:
        result = self.run_with_stalls("mid_16gb_mac", forced=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # The floor tier stays gated even when forced, as before.
        result = self.run_with_stalls("floor8GBMac", forced=True)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        # Rows without a Mac tier are not gated.
        result = self.run_with_stalls(None)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_the_contract_owns_the_statistic_and_limit(self) -> None:
        # Two heartbeats over 50 ms, none over 250 ms: the shipped contract passes them,
        # a contract declaring the old zero tolerance on the 50 ms count does not.
        result = self.run_with_stalls("mid_16gb_mac", stalls=2, maximum_ms=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with tempfile.TemporaryDirectory() as temporary:
            strict = self.write_stall_contract(
                Path(temporary), statistic="delayedHeartbeatCount50", maximumAllowed=0,
            )
            result = self.run_with_stalls(
                "mid_16gb_mac", stalls=2, maximum_ms=120, extra_args=["--stall-contract", str(strict)],
            )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_a_contract_for_another_profile_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            other = self.write_stall_contract(Path(temporary), calibrationProfile="mac-mini-m2-8gb")
            result = self.run_with_stalls(
                "mid_16gb_mac", stalls=0, maximum_ms=0, extra_args=["--stall-contract", str(other)],
            )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_a_malformed_stall_contract_is_refused(self) -> None:
        if str(ROOT / "scripts") not in sys.path:
            sys.path.insert(0, str(ROOT / "scripts"))
        import check_macos_ui_bench as checker

        shipped = checker.load_stall_contract(checker.DEFAULT_STALL_CONTRACT)
        self.assertEqual((shipped["statistic"], shipped["maximumAllowed"]), ("maximumDelayedHeartbeatMS", 250))
        with tempfile.TemporaryDirectory() as temporary:
            for overrides in (
                {"statistic": "uiStallCount50"},
                {"maximumAllowed": -1},
                {"maximumAllowed": True},
                {"calibrationStatus": "calibrated", "calibrationRuns": []},
                {"calibrationProfile": ""},
            ):
                with self.subTest(overrides=overrides):
                    broken = self.write_stall_contract(Path(temporary), **overrides)
                    with self.assertRaises(checker.StallContractError):
                        checker.load_stall_contract(broken)
                    result = self.run_with_stalls(
                        "mid_16gb_mac", stalls=0, maximum_ms=0, extra_args=["--stall-contract", str(broken)],
                    )
                    self.assertEqual(result.returncode, 1)

    def test_the_evidence_manifest_names_the_stall_contract(self) -> None:
        result = self.run_with_stalls("mid_16gb_mac", stalls=1, maximum_ms=90, evidence=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        stall = self.last_manifest["stallGate"]
        self.assertEqual(stall["policyID"], "macos-ui-stall-gate-provisional-250ms")
        self.assertEqual((stall["statistic"], stall["maximumAllowed"]), ("maximumDelayedHeartbeatMS", 250))
        self.assertEqual((stall["calibrationStatus"], stall["calibrationProfile"]), ("provisional", "mac-mini-m6-16gb"))
        self.assertEqual((stall["gatedTakeCount"], stall["maximum"], stall["takesAboveLimit"]), (5, 90, 0))
        self.assertNotIn("stallGate", self.last_manifest["historyRecord"]["run"])

    def test_censored_heartbeats_are_gated_and_counted(self) -> None:
        """audit #18: a heartbeat still queued at the end of a take is a lower bound."""
        def censored(layers: dict[str, list[dict]]) -> None:
            for row in layers["engine"]:
                row["notes"]["deviceClass"] = "mid_16gb_mac"
            frontend = layers["app"][2]["frontendMetrics"]
            frontend.update({
                "maximumDelayedHeartbeatMS": 180, "delayedHeartbeatCount50": 2,
                "censoredHeartbeatCount": 2, "heartbeatDelayDefinition": "completedAndCensoredPending",
            })

        result = self.run_checker(self.expected_order, mutate_layers=censored, evidence=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.last_manifest["stallGate"]["censoredHeartbeatCount"], 2)
        self.assertEqual(self.last_manifest["stallGate"]["maximum"], 180)

    def test_rows_not_yet_present_exit_apart_from_deterministic_failures(self) -> None:
        """audit #6/#21: the lane retries only the "rows not yet present" outcome."""
        def drop_last_app_row(layers: dict[str, list[dict]]) -> None:
            layers["app"].pop()

        def drop_last_engine_take(layers: dict[str, list[dict]]) -> None:
            for key in ("engine", "app", "merged"):
                layers[key].pop()

        for name, mutate in (("app", drop_last_app_row), ("engine", drop_last_engine_take)):
            with self.subTest(layer=name):
                result = self.run_checker(self.expected_order, mutate_layers=mutate)
                self.assertEqual(result.returncode, 75, result.stdout + result.stderr)

        def fail_audio_qc(rows: list[dict]) -> None:
            rows[0]["audioQC"] = {"verdict": "fail", "flags": ["fixture"]}

        result = self.run_checker(self.expected_order, fail_audio_qc)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_every_take_must_run_the_declared_variant(self) -> None:
        """audit #17: the M6 tier recommends Quality first; the benchmark measures Speed."""
        def one_quality_take(layers: dict[str, list[dict]]) -> None:
            layers["engine"][1]["modelRuntimeIdentity"]["modelVariant"] = "quality"

        def every_take_quality(layers: dict[str, list[dict]]) -> None:
            for row in layers["engine"]:
                row["modelRuntimeIdentity"]["modelVariant"] = "quality"

        result = self.run_checker(self.expected_order, mutate_layers=one_quality_take)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        result = self.run_checker(self.expected_order, mutate_layers=every_take_quality)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        result = self.run_checker(
            self.expected_order, mutate_layers=every_take_quality, extra_args=["--variant", "quality"],
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_the_manifest_reuses_the_gate_memory_qualification(self) -> None:
        """audit #21: a passing run qualifies its memory once, not twice."""
        if str(ROOT / "scripts") not in sys.path:
            sys.path.insert(0, str(ROOT / "scripts"))
        import check_macos_ui_bench as checker

        calls: list[int] = []
        original = checker.qualify_memory_rows

        def counting(**kwargs):
            calls.append(1)
            return original(**kwargs)

        with mock.patch.object(checker, "qualify_memory_rows", side_effect=counting):
            result = self.run_checker(self.expected_order, evidence=True, in_process=checker)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(len(calls), 1)
        self.assertIsNotNone(self.last_manifest)

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

    def test_process_ownership_rejects_app_and_engine_pid_mismatch(self) -> None:
        def split_pid(layers: dict[str, list[dict]]) -> None:
            layers["app"][0]["processIdentifier"] = 43
            layers["merged"][0]["app"]["processIdentifier"] = 43

        result = self.run_checker(self.expected_order, mutate_layers=split_pid)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("app PID 43 != engine PID 42", result.stdout + result.stderr)

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
        self.assertIn("app PID 99 != layer PID 42", result.stdout + result.stderr)

    def test_duplicate_layer_generation_id_fails(self) -> None:
        def duplicate_app_id(layers: dict[str, list[dict]]) -> None:
            layers["app"][1]["generationID"] = "fixture-1"

        result = self.run_checker(self.expected_order, mutate_layers=duplicate_app_id)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("app generationIDs are not unique", result.stdout + result.stderr)

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


class StartupWindowMetricsTests(unittest.TestCase):
    """audit #58: the startup time the standard RTF excludes is published."""

    def test_tracked_metrics_publish_the_excluded_startup_windows(self) -> None:
        if str(ROOT / "scripts") not in sys.path:
            sys.path.insert(0, str(ROOT / "scripts"))
        import check_macos_ui_bench as checker

        engine = {
            "stageMarks": [
                {"stage": "startup.model_load_started", "tMS": 0},
                {"stage": "startup.model_loaded", "tMS": 900},
                {"stage": "startup.prewarm_started", "tMS": 910},
                {"stage": "startup.prewarm_completed", "tMS": 1_110},
                {"stage": "streamCompleted", "tMS": 3_000},
            ],
            "derivedMetrics": {"audioSeconds": 2.0},
        }
        metrics = checker.tracked_metrics(engine, {})
        self.assertEqual(metrics["modelLoadWindowMS"], 900.0)
        self.assertEqual(metrics["prewarmWindowMS"], 200.0)
        self.assertEqual(metrics["excludedStartupMS"], 1_100.0)
        # The request wall (and so RTF) is exactly the terminal mark minus them.
        self.assertAlmostEqual(metrics["requestWallSeconds"], (3_000 - 1_100) / 1_000)


if __name__ == "__main__":
    raise SystemExit(unittest.main())


class PlaybackCaptureEvidenceTests(CheckMacOSUIBenchmarkTests):
    """PC-01: the runner's per-take capture joins the take and yields warn-only evidence."""

    def _capture_fixture(self, root: Path, *, take_index: int, cell: str, duration: float, hole_ms: float = 0.0) -> tuple[Path, Path]:
        import datetime as dt
        import numpy as np
        sys.path.insert(0, str(ROOT / "scripts"))
        from lib import playback_capture as pc
        world_rate = 48_000
        t = np.arange(int(world_rate * duration)) / world_rate
        burst = ((t > 0.2) & (t < duration - 0.3)).astype(float)
        world = 0.4 * np.sin(2 * np.pi * 440 * t) * burst * (1 + 0.3 * np.sin(2 * np.pi * 3 * t))
        outputs = root / "outputs"
        (outputs / "CustomVoice").mkdir(parents=True)
        stamp = dt.datetime(2026, 9, 13, 15, 0, 0)
        reference = outputs / "CustomVoice" / (stamp.strftime("%Y%m%d_%H-%M-%S-") + "000_fixture.wav")
        pc.write_wav_int16(reference, 24_000, pc.resample(world, world_rate, 24_000))
        captures = root / "playback-capture"
        captures.mkdir()
        safe_cell = cell.replace("/", "_")
        played = np.concatenate([np.zeros(int(world_rate * 0.137)), world * 0.7, np.zeros(world_rate)])
        if hole_ms:
            # A dropout inside the spoken part: the app stopped rendering for hole_ms.
            start = int(world_rate * (0.137 + 1.0)); played[start:start + int(world_rate * hole_ms / 1000)] = 0.0
        pc.write_wav_float32(captures / f"take-{take_index:02d}-{safe_cell}.wav", world_rate, played)
        start = stamp.timestamp() * 1000 - 1_000
        (captures / f"take-{take_index:02d}-{safe_cell}.json").write_text(json.dumps({
            "takeIndex": take_index, "cell": cell, "status": "captured",
            # The fixture app schedules playback 30 ms after submit; the burst starts
            # 0.2 s into the file and the capture adds 137 ms, so a click 307 ms after
            # the capture start makes the audible first frame agree with the app.
            "submitClickEpochMS": start + 307, "captureStartEpochMS": start,
            "stopEpochMS": start + duration * 1000 + 3_000,
        }))
        (captures / "capture-run.json").write_text(json.dumps({"runID": RUN_ID}))
        return captures, outputs

    def test_a_captured_take_with_a_dropout_fails_the_lane_but_keeps_its_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            captures, outputs = self._capture_fixture(Path(temp), take_index=2, cell="custom/short/warm#0", duration=3.0, hole_ms=120)

            def set_duration(rows: list[dict]) -> None:
                rows[1]["outputMetrics"]["durationSeconds"] = 3.0

            result = self.run_checker(
                self.expected_order, mutate_engine_rows=set_duration, evidence=True,
                extra_args=["--playback-capture-dir", str(captures), "--outputs-dir", str(outputs)],
            )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("FAIL:", result.stdout)
            self.assertRegex(result.stdout, r"take 2 \(custom/short/warm#0\): playback capture dropouts \d+ > 0")
            # The hole also drags the residual above the gate; both reasons are named.
            self.assertIn("playback capture residual", result.stdout)

    def test_the_bundle_path_follows_the_receipt(self) -> None:
        sys.path.insert(0, str(ROOT / "scripts"))
        import check_macos_ui_bench as checker
        self.assertEqual(
            checker.app_bundle_from_receipt("build/cache/xcode/macos-optimized/Build/Products/Release/Vocello.app/Contents/MacOS/Vocello"),
            "build/cache/xcode/macos-optimized/Build/Products/Release/Vocello.app")
        self.assertIsNone(checker.app_bundle_from_receipt("scripts/dev.sh"))
        self.assertIsNone(checker.app_bundle_from_receipt(None))

    def test_a_late_tap_and_the_app_submit_stamp_are_honoured(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            captures, outputs = self._capture_fixture(Path(temp), take_index=2, cell="custom/short/warm#0", duration=3.0)
            sidecar_path = next(captures.glob("take-02-*.json"))
            sidecar = json.loads(sidecar_path.read_text())
            # The tap attached 10 s after the click (a relaunched app): the reference
            # window must still open at the click.
            sidecar["firstBufferEpochMS"] = sidecar["captureStartEpochMS"]   # the WAV's origin stays
            sidecar["captureStartEpochMS"] = sidecar["submitClickEpochMS"] + 10_000
            sidecar_path.write_text(json.dumps(sidecar))
            click = sidecar["submitClickEpochMS"]

            def stamp_app_submit(layers: dict) -> None:
                layers["app"][1]["timingsMS"] = {"submittedAtEpochMS": click + 20}

            def set_duration(rows: list[dict]) -> None:
                rows[1]["outputMetrics"]["durationSeconds"] = 3.0

            result = self.run_checker(
                self.expected_order, mutate_engine_rows=set_duration, mutate_layers=stamp_app_submit, evidence=True,
                extra_args=["--playback-capture-dir", str(captures), "--outputs-dir", str(outputs)],
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            captured = self.last_manifest["historyRecord"]["takes"][1]
            self.assertEqual(captured["playbackCaptureStatus"], "captured")
            # audible 30 ms after the runner click, 10 ms after the app's submit
            self.assertAlmostEqual(captured["metrics"]["playbackCaptureFirstAudibleMS"], 10.0, delta=21)
            summary = json.loads((captures / "summary.json").read_text())
            take = next(item for item in summary["takes"] if item["takeIndex"] == 2)
            self.assertEqual(take["submitReference"], "app")
            self.assertAlmostEqual(take["clickToSubmitMS"], 20.0, delta=0.1)
            self.assertNotIn("appBundleRelativePath", self.last_manifest)

    def test_a_captured_take_carries_status_digest_and_metrics(self) -> None:
        def pc_frame_ms() -> float:
            sys.path.insert(0, str(ROOT / "scripts"))
            from lib import playback_capture as pc
            return float(pc.FRAME_MS)

        with tempfile.TemporaryDirectory() as temp:
            captures, outputs = self._capture_fixture(Path(temp), take_index=2, cell="custom/short/warm#0", duration=3.0)

            def set_duration(rows: list[dict]) -> None:
                rows[1]["outputMetrics"]["durationSeconds"] = 3.0

            result = self.run_checker(
                self.expected_order, mutate_engine_rows=set_duration, evidence=True,
                extra_args=["--playback-capture-dir", str(captures), "--outputs-dir", str(outputs)],
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            takes = self.last_manifest["historyRecord"]["takes"]
            captured = takes[1]
            self.assertEqual(captured["playbackCaptureStatus"], "captured")
            self.assertEqual(len(captured["playbackCaptureDigest"]), 64)
            self.assertAlmostEqual(captured["metrics"]["playbackCaptureAlignmentMS"], 137.0, delta=1.0)
            self.assertGreaterEqual(captured["metrics"]["playbackCaptureCoverage"], 0.99)
            self.assertEqual(captured["metrics"]["playbackCaptureDropoutCount"], 0.0)
            self.assertNotIn("playback.capture.misaligned", captured["warnings"])
            self.assertAlmostEqual(captured["metrics"]["playbackCaptureFirstAudibleMS"], 30.0, delta=pc_frame_ms() + 1)
            for other in (takes[0], *takes[2:]):
                self.assertEqual(other["playbackCaptureStatus"], "unavailable")
                self.assertNotIn("playbackCaptureDigest", other)
                self.assertFalse([k for k in other["metrics"] if k.startswith("playbackCapture")])
            summary = json.loads((captures / "summary.json").read_text())
            self.assertEqual((summary["captured"], summary["expected"]), (1, 5))
            self.assertEqual(summary["gate"]["failedTakes"], [])
            self.assertEqual(summary["gate"]["coverageMin"], 0.98)
            self.assertEqual(summary["takes"][1]["reference"].endswith("_fixture.wav"), True)

    def test_a_lane_without_a_capture_directory_adds_no_capture_fields(self) -> None:
        result = self.run_checker(self.expected_order, evidence=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for take in self.last_manifest["historyRecord"]["takes"]:
            self.assertNotIn("playbackCaptureStatus", take)
            self.assertFalse([k for k in take["metrics"] if k.startswith("playbackCapture")])
