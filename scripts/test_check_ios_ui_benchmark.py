#!/usr/bin/env python3
"""Offline order and output fixtures for check_ios_ui_benchmark.py."""

from __future__ import annotations

import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
TEST_HELPERS = ROOT / "scripts" / "tests"
if str(TEST_HELPERS) not in sys.path:
    sys.path.insert(0, str(TEST_HELPERS))
from test_benchmark_memory import ENGINE_BOUNDARIES, row as memory_row, samples as memory_samples
CHECK = ROOT / "scripts" / "check_ios_ui_benchmark.py"
RUNNER = ROOT / "scripts" / "ui_test.sh"
RUN_ID = "ios-ui-order-fixture"


def make_row(index: int, mode: str, length: str, warm_state: str) -> dict:
    prompt_chars = {"short": 36, "medium": 100, "long": 150}[length]
    return {
        "generationID": f"fixture-{index}",
        "mode": mode,
        "warmState": warm_state,
        "finishReason": "completed",
        "derivedMetrics": {"generatedTokenCount": 200 + index},
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
        row["notes"]["promptDigest"] = "c" * 64
        (diagnostics / "engine" / f"samples-{row['generationID']}.jsonl").write_text(
            "".join(json.dumps(item) + "\n" for item in sidecar), encoding="utf-8"
        )
    for row in app_rows:
        row["schemaVersion"] = 8
        row["frontendMetrics"] = v7_frontend()


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
        malformed_layer: str | None = None,
        evidence: bool = False,
        modes: str = "custom,clone",
        lengths: str = "short,medium",
    ) -> subprocess.CompletedProcess[str]:
        self.last_manifest = None
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

    def test_unrelated_historical_rows_are_not_selected(self) -> None:
        def append_unrelated(rows: list[dict]) -> None:
            unrelated = make_row(99, "custom", "short", "warm")
            unrelated["notes"]["benchRunID"] = "another-run"
            rows.append(unrelated)

        result = self.run_checker(self.expected_order, mutate_rows=append_unrelated)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_runner_does_not_mask_benchmark_gate_failure_in_or_list(self) -> None:
        text = RUNNER.read_text(encoding="utf-8")
        prefix = "validate_ios_benchmark() {\n"
        start = text.index(prefix)
        end = text.index("\n}\n", start) + 3
        function = text[start:end]

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


if __name__ == "__main__":
    raise SystemExit(unittest.main())
