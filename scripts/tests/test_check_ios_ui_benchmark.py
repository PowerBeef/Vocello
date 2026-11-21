#!/usr/bin/env python3
"""Offline order and output fixtures for check_ios_ui_benchmark.py."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any
import shlex
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
TEST_HELPERS = ROOT / "scripts" / "tests"
if str(TEST_HELPERS) not in sys.path:
    sys.path.insert(0, str(TEST_HELPERS))
from test_benchmark_memory import ENGINE_BOUNDARIES, row as memory_row, samples as memory_samples
from shell_stubs import ui_function
CHECK = ROOT / "scripts" / "check_ios_ui_benchmark.py"
RUN_ID = "ios-ui-order-fixture"


def write_provenance_fixture(directory: Path, *, optimization: str = "O") -> Path:
    """A build receipt bound to a real tracked file, exactly as write_build_provenance emits it."""
    executable = ROOT / "scripts" / "dev.sh"
    payload = {
        "schemaVersion": 1,
        "producer": "scripts/ui_test.sh ios benchmark",
        "status": "passed",
        "platform": "ios",
        "scheme": "fixture",
        "configuration": "Release",
        "optimization": optimization,
        "executableRelativePath": "scripts/dev.sh",
        "executableSHA256": hashlib.sha256(executable.read_bytes()).hexdigest(),
    }
    path = directory / "last-build.json"
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    return path


def make_row(index: int, mode: str, length: str, warm_state: str) -> dict:
    prompt_chars = {"short": 36, "medium": 100, "long": 150}[length]
    return {
        "generationID": f"fixture-{index}",
        "mode": mode,
        "warmState": warm_state,
        "finishReason": "completed",
        "derivedMetrics": {
            "generatedTokenCount": 200 + index,
            "audioSeconds": 4.0,
            "requestWallSeconds": 2.5,
            "realTimeFactor": 0.625,
            "audioSecondsPerWallSecond": 1.8,
        },
        "summary": {"stageMarks": []},
        "notes": {
            "benchRunID": RUN_ID,
            "promptChars": str(prompt_chars),
            "quality_registry_outcome": "pass",
            "quality_registry_required_gates": "terminal,token_cap,codec_behavior,persisted_wav,streaming_continuity",
        },
        "outputMetrics": {
            "readableWAV": True,
            "atomicallyPublished": True,
            "durationSeconds": 1.0,
        },
        "audioQC": {"verdict": "pass"},
    }


def v7_summary() -> dict:
    return {
        "targetIntervalNS": 500_000_000, "effectiveIntervalNS": 505_000_000,
        "maximumDriftNS": 5_000_000, "maximumLatenessNS": 5_000_000,
        "boundarySampleCount": 4, "captureFailureCount": 0,
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
        "delayedHeartbeatCount50": 0, "scheduledHeartbeatCount": 10,
        "completedHeartbeatCount": 10, "heartbeatCoveragePPM": 1_000_000,
        "playbackChunksReceived": 4, "playbackContinuityFailures": 0,
        "playbackUnderruns": 0, "playbackStartSource": "liveStream",
        "playbackStartBufferedChunks": 2,
        "playbackStartBufferedAudioMS": 120, "playbackMinimumQueuedAudioMS": 80,
    }


def upgrade_rows_to_v8(
    engine_rows: list[dict], app_rows: list[dict], diagnostics: Path
) -> None:
    for row in engine_rows:
        mode = row["mode"]
        model_id = f"pro_{mode}_speed"
        sidecar = memory_samples(
            role="engine", boundaries=ENGINE_BOUNDARIES, ios=True,
            footprint=3000 + int(str(row["generationID"]).rsplit("-", 1)[-1]),
        )
        memory = memory_row(row["generationID"], sidecar, layer="engine", ios=True)
        row["schemaVersion"] = 8
        row["summary"] = {**memory["summary"], **v7_summary()}
        row["summary"]["sampleCount"] = len(sidecar)
        row["summary"]["periodicSampleCount"] = 1
        row["summary"]["boundarySampleCount"] = len(ENGINE_BOUNDARIES)
        row["summary"]["captureFailureCount"] = 0
        row["summary"]["missedPeriodicDeadlineCount"] = 0
        row["summary"]["captureCoverage"] = memory["summary"]["captureCoverage"]
        row["summary"]["boundaryCoverage"] = memory["summary"]["boundaryCoverage"]
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
        row["processIdentifier"] = 4242
        row["notes"]["promptDigest"] = "c" * 64
        (diagnostics / "engine" / f"samples-{row['generationID']}.jsonl").write_text(
            "".join(json.dumps(item) + "\n" for item in sidecar), encoding="utf-8"
        )
    for row in app_rows:
        gid = row.get("generationID") or "fixture-0"
        suffix = int(str(gid).rsplit("-", 1)[-1]) if str(gid).rsplit("-", 1)[-1].isdigit() else 0
        app_sidecar = memory_samples(
            role="app",
            boundaries=["app_submit", "app_terminal"],
            ios=True,
            footprint=3000 + suffix,
        )
        app_memory = memory_row(gid, app_sidecar, layer="app", ios=True)
        row["schemaVersion"] = 8
        row["processIdentifier"] = 4242
        row["summary"] = app_memory["summary"]
        row["memoryMetrics"] = app_memory["memoryMetrics"]
        row["frontendMetrics"] = v7_frontend()
        (diagnostics / "app" / f"samples-{gid}.jsonl").write_text(
            "".join(json.dumps(item) + "\n" for item in app_sidecar), encoding="utf-8"
        )


class CheckIOSUIBenchmarkTests(unittest.TestCase):
    expected_order = [
        ("custom", "medium", "cold"),
        ("custom", "short", "warm"),
        ("custom", "medium", "warm"),
        ("clone", "short", "warm"),
        ("clone", "medium", "warm"),
    ]

    def run_checker(
        self,
        cells: list[tuple[str, str, str]],
        mutate_rows=None,
        mutate_app_rows=None,
        mutate_engine_after_upgrade=None,
        malformed_layer: str | None = None,
        evidence: bool = False,
        modes: str = "custom,clone",
        lengths: str = "short,medium",
        extra_args: list[str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        self.last_manifest: Any = None
        with tempfile.TemporaryDirectory() as temp:
            diagnostics = Path(temp)
            engine = diagnostics / "engine"
            app = diagnostics / "app"
            engine.mkdir()
            app.mkdir()
            rows = [make_row(index, *cell) for index, cell in enumerate(cells, start=1)]
            if mutate_rows is not None:
                mutate_rows(rows)
            app_rows = [
                {
                    "generationID": row.get("generationID"),
                    "finishReason": "completed",
                    "notes": {
                        "benchRunID": (row.get("notes") or {}).get("benchRunID")
                    },
                }
                for row in rows
            ]
            upgrade_rows_to_v8(rows, app_rows, diagnostics)
            if mutate_engine_after_upgrade is not None:
                mutate_engine_after_upgrade(rows)
            if mutate_app_rows is not None:
                mutate_app_rows(app_rows)
            (engine / "generations.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in rows)
                + ("{not-json\n" if malformed_layer == "engine" else ""),
                encoding="utf-8",
            )
            (app / "generations.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in app_rows)
                + ("{not-json\n" if malformed_layer == "app" else ""),
                encoding="utf-8",
            )
            command = [
                sys.executable,
                str(CHECK),
                str(diagnostics),
                "--run-id",
                RUN_ID,
                "--modes",
                modes,
                "--lengths",
                lengths,
                "--warm",
                "1",
            ]
            generation_map = diagnostics / "generation-map.json"
            generation_map.write_text(json.dumps({
                "schemaVersion": 1,
                "runID": RUN_ID,
                "takes": [
                    {
                        "takeIndex": index,
                        "cell": f"{mode}/{length}/{warm_state}#0",
                        "generationID": f"fixture-{index}",
                    }
                    for index, (mode, length, warm_state) in enumerate(cells, start=1)
                ],
            }) + "\n", encoding="utf-8")
            command.extend(["--generation-map", str(generation_map)])
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

    def test_exact_order_passes(self) -> None:
        result = self.run_checker(self.expected_order)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_same_distribution_in_wrong_order_fails(self) -> None:
        reordered = self.expected_order.copy()
        reordered[1], reordered[2] = reordered[2], reordered[1]
        result = self.run_checker(reordered)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("generation map take 2", result.stdout + result.stderr)

    def test_missing_audio_qc_fails(self) -> None:
        def remove_audio_qc(rows: list[dict]) -> None:
            rows[0].pop("audioQC")

        result = self.run_checker(self.expected_order, remove_audio_qc)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("audioQC verdict is missing", result.stdout + result.stderr)

    def test_audio_qc_warning_is_accepted(self) -> None:
        def mark_warning(rows: list[dict]) -> None:
            rows[0]["audioQC"] = {"verdict": "warn", "flags": ["fixture"]}

        result = self.run_checker(self.expected_order, mark_warning)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_audio_qc_failure_fails(self) -> None:
        def mark_failure(rows: list[dict]) -> None:
            rows[0]["audioQC"] = {
                "verdict": "fail",
                "flags": ["dropout:excess2(2/0)"],
            }

        result = self.run_checker(self.expected_order, mark_failure)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("audioQC failed", result.stdout + result.stderr)

    def test_150_character_prompt_is_long_and_manifest_uses_exact_cell(self) -> None:
        cells = [
            ("custom", "long", "cold"),
            ("custom", "long", "warm"),
        ]
        result = self.run_checker(
            cells,
            evidence=True,
            modes="custom",
            lengths="long",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            self.last_manifest["matrix"]["orderedCells"],
            ["custom/long/cold#0", "custom/long/warm#0"],
        )
        self.assertEqual([take["length"] for take in self.last_manifest["takes"]], ["long", "long"])

    def test_evidence_manifest_contains_correlated_engine_and_app_rows(self) -> None:
        result = self.run_checker(self.expected_order, evidence=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        manifest = self.last_manifest
        self.assertEqual(manifest["runID"], RUN_ID)
        self.assertTrue(manifest["layers"]["engine"]["complete"])
        self.assertTrue(manifest["layers"]["app"]["complete"])
        self.assertTrue(
            all(take["layerCompleteness"] == {"engine": True, "app": True} for take in manifest["takes"])
        )
        self.assertTrue(manifest["historyRecord"]["evidence"]["validatorPassed"])
        first_metrics = manifest["historyRecord"]["takes"][0]["metrics"]
        self.assertEqual(first_metrics["generatedTokens"], 201)
        self.assertEqual(first_metrics["memoryTrimCount"], 0)
        self.assertEqual(first_metrics["maximumTrimLevel"], 0)
        self.assertEqual(self.last_manifest["schemaVersion"], 2)
        self.assertTrue(self.last_manifest["historyRecord"]["evidence"]["memoryQualified"])

    def test_missing_app_row_fails_without_evidence(self) -> None:
        def remove_app(rows: list[dict]) -> None:
            rows.pop()

        result = self.run_checker(
            self.expected_order,
            mutate_app_rows=remove_app,
            evidence=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("app rows 4 != expected 5", result.stdout + result.stderr)
        self.assertIsNone(self.last_manifest)

    def test_duplicate_app_generation_id_fails(self) -> None:
        def duplicate_app(rows: list[dict]) -> None:
            rows[1]["generationID"] = rows[0]["generationID"]

        result = self.run_checker(self.expected_order, mutate_app_rows=duplicate_app)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("app generationIDs are not unique", result.stdout + result.stderr)

    def test_malformed_jsonl_fails(self) -> None:
        result = self.run_checker(self.expected_order, malformed_layer="engine")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("malformed JSON", result.stdout + result.stderr)

    FULL_CELLS = [
        ("custom", "medium", "cold"), ("custom", "short", "warm"), ("custom", "medium", "warm"),
        ("clone", "short", "warm"), ("clone", "medium", "warm"),
    ]

    def test_prompt_length_must_match_the_positional_cell(self) -> None:
        cells = self.FULL_CELLS

        def short_prompt_under_medium_cell(rows):
            rows[2]["notes"]["promptChars"] = "36"

        result = self.run_checker(cells, mutate_rows=short_prompt_under_medium_cell)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("is a short prompt, not the medium cell", result.stdout + result.stderr)

        def no_prompt_length(rows):
            rows[1]["notes"].pop("promptChars", None)

        result = self.run_checker(cells, mutate_rows=no_prompt_length)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("no promptChars", result.stdout + result.stderr)

    def test_each_take_keeps_its_load_and_a_busy_take_makes_the_run_exploratory(self) -> None:
        """audit #28 (iPhone): the per-take load rule of engine and macOS UI records."""
        result = self.run_checker(self.expected_order, evidence=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        record = self.last_manifest["historyRecord"]
        self.assertTrue(all(take["metrics"]["loadAverage1M"] == 1.0 for take in record["takes"]))
        self.assertNotIn("classification", record["run"])

        profiles = json.loads((ROOT / "benchmarks" / "hardware-profiles.json").read_text(encoding="utf-8"))
        limit = next(
            profile["cpuCores"] for profile in profiles["profiles"]
            if profile["platform"] == "ios" and profile.get("canonical") is True
        )

        def busy_second_take(rows: list[dict]) -> None:
            rows[1]["summary"]["runEnvironment"]["loadAverage1Minute"] = limit + 0.5

        result = self.run_checker(self.expected_order, mutate_engine_after_upgrade=busy_second_take, evidence=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        record = self.last_manifest["historyRecord"]
        self.assertEqual(record["takes"][1]["metrics"]["loadAverage1M"], limit + 0.5)
        self.assertEqual(record["run"]["classification"], "exploratory")

    def test_the_manifest_names_the_runs_armed_runtime_overrides(self) -> None:
        """BKL-22 (iPhone): the gate still passes; the record step refuses the
        manifest by the keys it names."""
        result = self.run_checker(self.expected_order, evidence=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("armedRuntimeOverrideKeys", self.last_manifest)

        def armed(rows: list[dict]) -> None:
            for row in rows:
                row["summary"]["runEnvironment"]["runtimeDebugProvenance"] = {
                    "internalDiagnosticsAvailable": True, "masterGateRequested": True,
                    "activeOverrideKeys": [
                        "QVOICE_IOS_DEVICE_RUN_ID", "QWENVOICE_BENCH_SEED_POLICY", "QWENVOICE_MIXED_PRECISION",
                    ],
                    "activeOverrideDigest": "d" * 64,
                }

        result = self.run_checker(self.expected_order, mutate_engine_after_upgrade=armed, evidence=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.last_manifest["armedRuntimeOverrideKeys"], ["QWENVOICE_MIXED_PRECISION"])

    def test_takes_sample_under_the_seed_policy_the_lane_selected(self) -> None:
        """audit #29: seed = hash(cell) per take; generated seeds differ per take."""
        from lib import bench_seed

        cells = self.FULL_CELLS
        names = [f"{mode}/{length}/{state}#0" for mode, length, state in cells]

        def generated(rows):
            for index, row in enumerate(rows, start=1):
                row["notes"].update({"samplingSeed": str(1000 + index), "samplingSeedSource": "generated"})

        # Every generation draws its own effective seed, so distinct seeds in a
        # mode are the normal generated case (the old one-seed rule never held).
        result = self.run_checker(cells, mutate_rows=generated, evidence=True, extra_args=["--seed-policy", "generated"])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        record = self.last_manifest["historyRecord"]
        self.assertEqual(record["run"]["seedPolicy"], "generated")
        self.assertTrue(all("seed" not in take for take in record["takes"]))

        def policy(rows):
            for row, name in zip(rows, names, strict=True):
                row["notes"].update({
                    "samplingSeed": str(bench_seed.cell_seed(name)), "samplingSeedSource": "requested",
                    "samplingSeedPolicy": "cell-hash-v1",
                })

        result = self.run_checker(cells, mutate_rows=policy, evidence=True, extra_args=["--seed-policy", "cell-hash-v1"])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        record = self.last_manifest["historyRecord"]
        self.assertEqual(record["run"]["seedPolicy"], "cell-hash-v1")
        self.assertEqual([take["seed"] for take in record["takes"]], [bench_seed.cell_seed(name) for name in names])

        def off_schedule(rows):
            policy(rows)
            rows[2]["notes"]["samplingSeed"] = str(bench_seed.cell_seed(names[1]))

        result = self.run_checker(cells, mutate_rows=off_schedule, extra_args=["--seed-policy", "cell-hash-v1"])
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("not its cell-hash-v1 seed", result.stdout + result.stderr)

        # A build that ignored the knob sampled random seeds under a policy run.
        result = self.run_checker(cells, mutate_rows=generated, extra_args=["--seed-policy", "cell-hash-v1"])
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("selected seed policy cell-hash-v1", result.stdout + result.stderr)

    def test_every_take_gets_the_model_identity_check_with_one_seed_per_mode(self) -> None:
        # V-1: the per-take identity and schema checks once ran only when a mode
        # used several seeds, and then only against the last row. A defect on
        # any earlier take must refuse publication with one seed per mode.
        def seed_every_take(rows):
            for row in rows:
                row["notes"]["samplingSeed"] = "42"

        breakages = {
            "revision": lambda row: row["modelRuntimeIdentity"].pop("huggingFaceRevision"),
            "integrity": lambda row: row["modelRuntimeIdentity"].pop("integrityManifestDigest"),
            "prompt-digest": lambda row: row["notes"].pop("promptDigest"),
            "fixture-digest": lambda row: row["modelRuntimeIdentity"].pop("fixtureDigest"),
        }
        for name, breakage in breakages.items():
            # Take 4 is the first clone take, so it has a fixture digest to
            # lose; every other defect lands on take 1, never the last row.
            target = 3 if name == "fixture-digest" else 0

            def break_one_take(rows, breakage=breakage, target=target):
                breakage(rows[target])

            with self.subTest(breakage=name):
                result = self.run_checker(
                    self.expected_order,
                    mutate_rows=seed_every_take,
                    mutate_engine_after_upgrade=break_one_take,
                    evidence=True,
                )
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIsNone(self.last_manifest)

        # The same seeded matrix without a defect still passes.
        result = self.run_checker(
            self.expected_order, mutate_rows=seed_every_take, evidence=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_schema_v8_complete_accuracy_evidence_passes(self) -> None:
        result = self.run_checker(
            self.expected_order,
            evidence=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(
            all(
                take["playbackStartSource"] == "liveStream"
                for take in self.last_manifest["historyRecord"]["takes"]
            )
        )

    def test_schema_v8_missing_sampler_resource_or_environment_fails(self) -> None:
        for field, message in (
            ("maximumDriftNS", "invalid sampler maximumDriftNS"),
            ("processResourceUsage", "incomplete process resource deltas"),
            ("runEnvironment", "missing run environment"),
        ):
            def app(rows, field=field):
                self._current_rows[0]["summary"].pop(field)
            with self.subTest(field=field):
                def engine(rows):
                    self._current_rows = rows
                result = self.run_checker(
                    self.expected_order, mutate_rows=engine, mutate_app_rows=app
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stdout + result.stderr)

    def test_schema_v8_frontend_lifecycle_and_playback_health_are_required(self) -> None:
        def app(rows):
            rows[0]["frontendMetrics"].pop("playbackMinimumQueuedAudioMS")
        result = self.run_checker(
            self.expected_order, mutate_app_rows=app
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("incomplete typed frontend lifecycle/playback", result.stdout + result.stderr)

    def test_schema_v8_typed_playback_start_source_is_required(self) -> None:
        def app(rows):
            rows[0]["frontendMetrics"].pop("playbackStartSource")
        result = self.run_checker(
            self.expected_order, mutate_app_rows=app
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing or invalid typed playback start source", result.stdout + result.stderr)

    def test_schema_v8_final_file_uses_one_active_file_buffer(self) -> None:
        def app(rows):
            rows[0]["frontendMetrics"]["playbackStartSource"] = "finalFile"
            rows[0]["frontendMetrics"]["playbackStartBufferedChunks"] = 2
        result = self.run_checker(
            self.expected_order, mutate_app_rows=app
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("final-file playback must expose one active file buffer", result.stdout + result.stderr)

    def test_playback_underruns_and_continuity_failures_are_reported_not_gated(self) -> None:
        """RF-61, audit T4: what the Mac gate fails is named here and stays
        report-only until a phone run calibrates it."""
        def app(rows):
            rows[1]["frontendMetrics"]["playbackUnderruns"] = 2
            rows[3]["frontendMetrics"]["playbackContinuityFailures"] = 1
        result = self.run_checker(self.expected_order, mutate_app_rows=app, evidence=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("WARN (playback health, report only", result.stdout)
        self.assertIn("take 2 (custom/short/warm#0): playbackUnderruns 2 > 0", result.stdout)
        self.assertIn("take 4 (clone/short/warm#0): playbackContinuityFailures 1 > 0", result.stdout)
        # The record is the one a clean run publishes: no status or warning code changes.
        record = self.last_manifest["historyRecord"]
        self.assertEqual(record["run"]["status"], "passed")
        self.assertTrue(all(take["warnings"] == [] for take in record["takes"]))
        clean = self.run_checker(self.expected_order)
        self.assertEqual(clean.returncode, 0, clean.stdout + clean.stderr)
        self.assertNotIn("WARN (playback health", clean.stdout)

    def test_unrelated_historical_rows_are_not_selected(self) -> None:
        def append_unrelated(rows: list[dict]) -> None:
            unrelated = make_row(99, "custom", "short", "warm")
            unrelated["notes"]["benchRunID"] = "another-run"
            rows.append(unrelated)

        result = self.run_checker(self.expected_order, mutate_rows=append_unrelated)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_runner_does_not_mask_benchmark_gate_failure_in_or_list(self) -> None:
        # ui_test.sh runs its lane at top level, so the shared loader in
        # scripts/tests/shell_stubs.py takes this one function.
        function = ui_function("validate_ios_benchmark")

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scripts = root / "scripts"
            output = root / "output"
            scripts.mkdir()
            output.mkdir()
            attachments = output / "attachments"
            attachments.mkdir()
            (attachments / "generation-map.json").write_text("{}\n", encoding="utf-8")
            (attachments / "manifest.json").write_text(json.dumps([{
                "attachments": [{
                    "suggestedHumanReadableName": "ios-benchmark-generation-map.json",
                    "exportedFileName": "generation-map.json",
                }],
            }]) + "\n", encoding="utf-8")

            pull = scripts / "ios_device.sh"
            pull.write_text(
                "#!/usr/bin/env bash\nmkdir -p \"$2/engine\"\n",
                encoding="utf-8",
            )
            pull.chmod(0o755)
            (scripts / "check_ios_ui_benchmark.py").write_text(
                "print('fixture gate failure')\nraise SystemExit(7)\n",
                encoding="utf-8",
            )
            (scripts / "summarize_generation_telemetry.py").write_text(
                "from pathlib import Path\nPath(__file__).with_name('summarizer-ran').touch()\n",
                encoding="utf-8",
            )

            shell = f"""
set -euo pipefail
ROOT_DIR={shlex.quote(str(root))}
out={shlex.quote(str(output))}
run_id=fixture-run
modes=custom
lengths=short
warm=1
label=fixture
seed_policy=cell-hash-v1
matrix_allocation=
matrix_version=uniform-v1
{function}
if validate_ios_benchmark; then
  touch "$out/passed"
  exit 0
else
  exit $?
fi
"""
            result = subprocess.run(
                ["bash", "-c", shell],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse((output / "passed").exists())
            self.assertFalse((scripts / "summarizer-ran").exists())
            self.assertIn("fixture gate failure", result.stdout + result.stderr)


class StartupWindowMetricsTests(unittest.TestCase):
    """audit #58: the startup time the standard RTF excludes is published."""

    def test_tracked_metrics_publish_the_excluded_startup_windows(self) -> None:
        if str(ROOT / "scripts") not in sys.path:
            sys.path.insert(0, str(ROOT / "scripts"))
        import check_ios_ui_benchmark as checker

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


class IOSRefusedAndOwnershipParityTests(unittest.TestCase):
    """Wave 2 macOS parity: refused takes, process ownership, take identity and variant checks."""

    def _marker_line(self, take_index: int, cell: str) -> str:
        payload = json.dumps({"cell": cell, "schemaVersion": 1, "takeIndex": take_index}, sort_keys=True)
        return "VOCELLO_BENCH_TAKE_REFUSED=" + base64.b64encode(payload.encode("utf-8")).decode("ascii")

    def test_single_refused_take_publishes_exploratory_manifest(self) -> None:
        cells = [("custom", "medium", "cold"), ("custom", "short", "warm"), ("custom", "medium", "warm")]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            diagnostics = root / "diag"
            (diagnostics / "engine").mkdir(parents=True)
            (diagnostics / "app").mkdir(parents=True)
            rows = [make_row(index, *cell) for index, cell in enumerate(cells, start=1)]
            # Take 2 is refused by Fast QC.
            rows[1]["finishReason"] = "failed"
            rows[1]["audioQC"] = {"verdict": "fail", "flags": ["excess_trailing_silence"]}
            rows[1]["notes"]["nativeRuntimeFailureCode"] = "audio.quality_rejected"
            rows[1]["notes"]["audioQCFlags"] = "excess_trailing_silence"
            rows[1]["outputMetrics"] = {"readableWAV": False, "atomicallyPublished": False}
            completed_rows = [rows[0], rows[2]]
            app_rows = [
                {"generationID": row["generationID"], "finishReason": "completed", "notes": {"benchRunID": RUN_ID}}
                for row in completed_rows
            ]
            upgrade_rows_to_v8(completed_rows, app_rows, diagnostics)
            rows[1]["schemaVersion"] = 8
            rows[1]["processIdentifier"] = 4242
            (diagnostics / "engine" / "generations.jsonl").write_text(
                "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
            )
            (diagnostics / "app" / "generations.jsonl").write_text(
                "".join(json.dumps(r) + "\n" for r in app_rows), encoding="utf-8"
            )
            gen_map = root / "map.json"
            gen_map.write_text(json.dumps({
                "schemaVersion": 1,
                "runID": RUN_ID,
                "takes": [
                    {"takeIndex": 1, "cell": "custom/medium/cold#0", "generationID": "fixture-1"},
                    {"takeIndex": 2, "cell": "custom/short/warm#0", "refused": True},
                    {"takeIndex": 3, "cell": "custom/medium/warm#0", "generationID": "fixture-3"},
                ],
            }), encoding="utf-8")
            xcode_log = root / "xcodebuild.log"
            xcode_log.write_text(self._marker_line(2, "custom/short/warm#0") + "\n", encoding="utf-8")
            evidence = root / "evidence.json"
            provenance = write_provenance_fixture(root)
            completed = subprocess.run([
                sys.executable, str(CHECK), str(diagnostics),
                "--run-id", RUN_ID, "--modes", "custom", "--lengths", "short,medium", "--warm", "1",
                "--generation-map", str(gen_map),
                "--xcodebuild-log", str(xcode_log),
                "--variant", "speed",
                "--evidence-manifest", str(evidence),
                "--build-provenance", str(provenance),
                "--crash-delta-passed",
            ], capture_output=True, text=True, check=False)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            manifest = json.loads(evidence.read_text(encoding="utf-8"))
            record = manifest["historyRecord"]
            self.assertEqual(record["run"]["classification"], "exploratory")
            self.assertIn("takes.refused(1/3)", record["run"]["warnings"])
            self.assertEqual(record["evidence"]["refusedTakeRule"], "recorded-exploratory-v1")
            self.assertEqual(len(record["evidence"]["refusedCells"]), 1)
            self.assertEqual(len(record["takes"]), 2)

    def test_mismatched_app_pid_and_take_identity_fail(self) -> None:
        cells = [("custom", "medium", "cold"), ("custom", "short", "warm")]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            diagnostics = root / "diag"
            (diagnostics / "engine").mkdir(parents=True)
            (diagnostics / "app").mkdir(parents=True)
            rows = [make_row(index, *cell) for index, cell in enumerate(cells, start=1)]
            app_rows = [
                {"generationID": row["generationID"], "finishReason": "completed", "notes": {"benchRunID": RUN_ID}}
                for row in rows
            ]
            upgrade_rows_to_v8(rows, app_rows, diagnostics)
            app_rows[0]["processIdentifier"] = 9999
            rows[1]["notes"]["benchCell"] = "custom/short/warm#0"
            app_rows[1]["notes"]["benchCell"] = "custom/medium/cold#0"
            (diagnostics / "engine" / "generations.jsonl").write_text(
                "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
            )
            (diagnostics / "app" / "generations.jsonl").write_text(
                "".join(json.dumps(r) + "\n" for r in app_rows), encoding="utf-8"
            )
            gen_map = root / "map.json"
            gen_map.write_text(json.dumps({
                "schemaVersion": 1,
                "runID": RUN_ID,
                "takes": [
                    {"takeIndex": 1, "cell": "custom/medium/cold#0", "generationID": "fixture-1"},
                    {"takeIndex": 2, "cell": "custom/short/warm#0", "generationID": "fixture-2"},
                ],
            }), encoding="utf-8")
            completed = subprocess.run([
                sys.executable, str(CHECK), str(diagnostics),
                "--run-id", RUN_ID, "--modes", "custom", "--lengths", "short", "--warm", "1",
                "--generation-map", str(gen_map), "--variant", "quality",
            ], capture_output=True, text=True, check=False)
            self.assertEqual(completed.returncode, 1)
            self.assertIn("app PID 9999 != engine PID 4242", completed.stdout)
            self.assertIn("names benchCell='custom/medium/cold#0'", completed.stdout)
            self.assertIn("variant 'speed' != expected 'quality'", completed.stdout)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
