#!/usr/bin/env python3
"""Every benchmark manifest producer's output passes the history validator (audit #8).

The producers (the publisher's commands and the UI checkers) and the registry
validator were each tested against their own hand-written fixtures, so four
mismatches surfaced only at publication, each costing a new consent-bound run.
These tests feed each producer's own manifest through
`benchmark_history.record_manifest`, which runs `build_record`, the comparison
baseline, `validate_record` and the 256 KiB storage cap, in-process. Only the
host probes are mocked (runtime hardware, the Xcode toolchain, the xcresult
summary and the canonical-hardware check); the fixtures are dated after the RTF
cutover and carry the contract's pinned model identities and v8 memory evidence.
"""
from __future__ import annotations

import contextlib
import copy
import json
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import wave

SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent
for path in (SCRIPTS, SCRIPTS / "tests"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import benchmark_history as history  # noqa: E402
import publish_benchmark_history as publisher  # noqa: E402
import test_check_ios_ui_benchmark as ios_ui  # noqa: E402
import test_check_ios_ui_perf as ios_perf  # noqa: E402
import test_check_macos_ui_bench as mac_ui  # noqa: E402
import test_check_macos_ui_perf as mac_perf  # noqa: E402
from test_publish_benchmark_history import (  # noqa: E402
    engine_row,
    independent_evidence,
    independent_recognition,
    ios_benchmark_app_row,
    source_fixture,
    upgrade_language_memory_row,
)

CONTRACT = json.loads((ROOT / "Sources/Resources/qwenvoice_contract.json").read_text(encoding="utf-8"))
# A post-cutover run window (rtf_semantics.RTF_DEFINITION_CUTOVER is 2026-09-12).
STARTED_AT = "2026-09-20T12:00:00Z"
FINISHED_AT = "2026-09-20T12:05:00Z"
TOOLCHAIN = {
    "xcodeVersion": "26.6", "xcodeBuild": "17F113", "swiftVersion": "Apple Swift version 6.2",
    "sdkName": "macosx", "sdkVersion": "26.5", "appVersion": "2.1.0", "appBuild": "18",
    "executableUUIDs": {"Vocello[arm64]": "12345678-ABCD-4321-ABCD-1234567890AB"},
    "executableHashes": {"Vocello": "a" * 64},
}


def contract_identity(mode: str, variant: str = "speed") -> dict:
    """The typed model identity a real run of this mode stamps: the pinned artifact."""
    definition = next(model for model in CONTRACT["models"] if model["id"] == f"pro_{mode}")
    selected = next(
        (candidate for candidate in definition.get("variants", []) if candidate.get("id") == variant),
        definition,
    )
    folder = str(selected.get("folder", definition.get("folder", "")))
    bits = re.search(r"-(\d+)bit$", folder, re.IGNORECASE)
    identity = {
        "resolvedModelID": f"pro_{mode}_{variant}",
        "modelVariant": variant,
        "modelRepository": selected.get("huggingFaceRepo", definition.get("huggingFaceRepo")),
        "huggingFaceRevision": selected.get("huggingFaceRevision", definition.get("huggingFaceRevision")),
        "artifactVersion": selected.get("artifactVersion", definition.get("artifactVersion")),
        "quantization": f"{bits.group(1)}-bit" if bits else "unquantized",
        "integrityManifestDigest": "b" * 64,
        "runtimeProfileSignature": f"pro_{mode}_{variant}:fixture-v1",
    }
    if mode in {"design", "clone"}:
        identity["fixtureDigest"] = "d" * 64
    return identity


def make_rows_realistic(rows: list[dict]) -> None:
    """Contract model identities and the current Swift QC report shape."""
    for row in rows:
        row["modelRuntimeIdentity"] = contract_identity(row["mode"])
        row["audioQC"] = {
            **(row.get("audioQC") or {}),
            "algorithmVersion": 7, "verdict": "pass", "instabilityVerdict": "pass",
            "writtenOutputVerdict": "pass", "flags": [],
        }


def runtime_hardware(platform: str, _profile: dict) -> dict:
    if platform == "macos":
        return {
            "osName": "macOS", "osVersion": "26.5.2", "osBuild": "25F84",
            "thermalState": "nominal", "lowPowerMode": False, "transport": "local",
            "loadAverage1M": 1.0, "freeStorageBytes": 1_000_000, "uptimeSeconds": 100.0,
        }
    return {
        "osName": "iOS", "osVersion": "26.5", "osBuild": "23F84", "thermalState": "nominal",
        "lowPowerMode": False, "transport": "wired", "loadAverage1M": 1.0,
        "freeStorageBytes": 1_000_000, "uptimeSeconds": 100.0,
    }


def publish_through_registry(
    manifest: dict, *, screenshots: bool = False, run_lane: str | None = None
) -> tuple[dict, int]:
    """Record one producer manifest into an isolated registry; return the record and its size.

    `run_lane` writes the `run.json` a UI lane leaves beside its evidence, which
    is where a ui-perf record takes its run window from."""
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        artifact = root / "artifact"
        artifact.mkdir()
        (artifact / "benchmark-evidence.json").write_text(
            json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8"
        )
        if run_lane is not None:
            (artifact / "run.json").write_text(json.dumps({
                "runID": manifest["runID"], "platform": manifest["platform"], "lane": run_lane,
                "status": "passed", "startedAt": STARTED_AT, "finishedAt": FINISHED_AT,
            }), encoding="utf-8")
        if screenshots:
            # UI runs retain their named xcresult screenshots beside the evidence.
            (artifact / "attachments").mkdir()
            (artifact / "attachments" / "studio-ready.png").write_bytes(b"fixture screenshot")
        schema = root / "schema-v1.json"
        schema.write_bytes(history.SCHEMA_PATH.read_bytes())
        with (
            mock.patch.object(history, "RUNS_ROOT", root / "runs"),
            mock.patch.object(history, "SCHEMA_PATH", schema),
            mock.patch.object(history, "HISTORY_PATH", root / "HISTORY.md"),
            mock.patch.object(history, "default_runtime_hardware", side_effect=runtime_hardware),
            # A UI benchmark declares its optimization; ui-perf takes it from the
            # run-owned build receipt, which the mocked toolchain stands in for.
            mock.patch.object(
                history, "default_toolchain",
                side_effect=lambda _platform, outer, _artifact: {
                    **copy.deepcopy(TOOLCHAIN), "optimization": str(outer.get("optimization") or "-O"),
                },
            ),
            mock.patch.object(history, "digest_xcresult_summary", return_value="f" * 64),
        ):
            path = history.record_manifest(artifact)
            size = path.stat().st_size
            record = json.loads(path.read_text(encoding="utf-8"))
    return record, size


def observed_warm_state(cell: str) -> str:
    """Bench stamps a cold load on a cold cell and on the first retained Clone take."""
    return "cold" if "/cold#" in cell or cell == "clone/speed/medium/retained#0" else "warm"


def write_wave(path: Path) -> None:
    """Two seconds of 24 kHz mono PCM, the shape a bench take writes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(24_000)
        stream.writeframes(b"\0\0" * 48_000)


def canonical_cells() -> list[str]:
    cells = []
    for mode in ("custom", "design", "clone"):
        if mode != "clone":
            cells.append(f"{mode}/medium/cold#0")
        for length in ("short", "medium", "long"):
            cells.extend(f"{mode}/{length}/warm#{repetition}" for repetition in range(3))
    return cells


def mark_censored_heartbeats(app_rows: list[dict]) -> None:
    """App rows of the censored heartbeat definition (audit #18)."""
    for row in app_rows:
        row.setdefault("frontendMetrics", {}).update({
            "censoredHeartbeatCount": 1, "heartbeatDelayDefinition": "completedAndCensoredPending",
        })


class UICheckerRoundTripTests(unittest.TestCase):
    def test_macos_ui_benchmark_manifest_publishes(self) -> None:
        def realistic(layers: dict[str, list[dict]]) -> None:
            make_rows_realistic(layers["engine"])
            mark_censored_heartbeats(layers["app"])

        checker = mac_ui.CheckMacOSUIBenchmarkTests("run_checker")
        result = checker.run_checker(checker.expected_order, mutate_layers=realistic, evidence=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        record, _size = publish_through_registry(checker.last_manifest, screenshots=True)
        self.assertEqual(record["run"]["kind"], "ui-generation")
        self.assertEqual(record["run"]["rtfDefinition"], "wall/audio")
        self.assertEqual(len(record["takes"]), len(checker.expected_order))
        # The censored-definition marker survives into the tracked record.
        self.assertTrue(all(take["metrics"]["censoredHeartbeatCount"] == 1 for take in record["takes"]))

    def test_canonical_macos_ui_benchmark_fits_the_record_cap(self) -> None:
        checker = mac_ui.CheckMacOSUIBenchmarkTests("run_checker")
        cells = canonical_cells()
        self.assertEqual(len(cells), 29)
        result = checker.run_checker(
            cells,
            mutate_layers=lambda layers: make_rows_realistic(layers["engine"]),
            evidence=True,
            extra_args=["--modes", "custom,design,clone", "--lengths", "short,medium,long", "--warm", "3"],
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        record, size = publish_through_registry(checker.last_manifest, screenshots=True)
        self.assertEqual(record["run"]["matrixScope"], "canonical")
        self.assertEqual(len(record["takes"]), 29)
        self.assertLessEqual(size, history.MAX_RECORD_BYTES)

    def test_ios_ui_benchmark_manifest_publishes(self) -> None:
        original = ios_ui.upgrade_rows_to_v8

        def upgrade(rows: list[dict], app_rows: list[dict], diagnostics: Path) -> None:
            original(rows, app_rows, diagnostics)
            make_rows_realistic(rows)
            mark_censored_heartbeats(app_rows)

        checker = ios_ui.CheckIOSUIBenchmarkTests("run_checker")
        with mock.patch.object(ios_ui, "upgrade_rows_to_v8", side_effect=upgrade):
            result = checker.run_checker(checker.expected_order, evidence=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        record, _size = publish_through_registry(checker.last_manifest, screenshots=True)
        self.assertEqual(record["run"]["platform"], "ios")
        self.assertEqual(len(record["takes"]), len(checker.expected_order))
        self.assertTrue(all(take["metrics"]["censoredHeartbeatCount"] == 1 for take in record["takes"]))

    def test_macos_ui_perf_manifest_publishes(self) -> None:
        fixture = mac_perf.UIPerfFixture("run_checker")
        fixture.setUp()
        try:
            log = fixture.write_run()
            # The checker imports the publisher by name at emit time; patch that
            # module object (a test module may have loaded its own copy).
            live_publisher = sys.modules.get("publish_benchmark_history", publisher)
            with mock.patch.object(
                live_publisher, "verify_canonical_hardware", return_value={"profileID": "mac-mini-m6-16gb"}
            ):
                status, _report = fixture.run_checker(log, emit=True)
            self.assertEqual(status, 0)
            manifest = json.loads((fixture.root / "benchmark-evidence.json").read_text(encoding="utf-8"))
        finally:
            fixture.tearDown()
        record, _size = publish_through_registry(manifest, screenshots=True, run_lane="perf")
        self.assertEqual(record["run"]["kind"], "ui-perf")
        self.assertIn("uiHitchMSPerAction", record["takes"][1]["metrics"])

    def test_uncalibrated_macos_ui_perf_manifest_publishes(self) -> None:
        """audit #77: M2 ceilings on the M6 publish one run-level uncalibrated code."""
        fixture = mac_perf.UIPerfFixture("run_checker")
        fixture.setUp()
        try:
            fixture.thresholds.write_text(json.dumps(
                {**fixture.contract, "calibrationProfile": "mac-mini-m2-8gb"}
            ))
            log = fixture.write_run(hitch_by_scenario={"idle-baseline": 50.0})
            live_publisher = sys.modules.get("publish_benchmark_history", publisher)
            with mock.patch.object(
                live_publisher, "verify_canonical_hardware", return_value={"profileID": "mac-mini-m6-16gb"}
            ):
                status, _report = fixture.run_checker(log, emit=True)
            self.assertEqual(status, 0)
            manifest = json.loads((fixture.root / "benchmark-evidence.json").read_text(encoding="utf-8"))
        finally:
            fixture.tearDown()
        record, _size = publish_through_registry(manifest, screenshots=True, run_lane="perf")
        self.assertEqual(record["run"]["warnings"], ["uiperf.uncalibrated:mac-mini-m2-8gb"])
        self.assertEqual(record["run"]["status"], "passedWithWarnings")
        self.assertTrue(all(take["warnings"] == [] for take in record["takes"]))

    def test_ios_ui_perf_manifest_publishes(self) -> None:
        fixture = ios_perf.IOSUIPerfFixture("run_checker")
        fixture.setUp()
        try:
            log = fixture.write_run()
            with mock.patch.object(
                ios_perf.checker, "verify_canonical_iphone", return_value="iphone-17-pro"
            ):
                status, _report = fixture.run_checker(log, require_canonical=True, emit_evidence=True)
            self.assertEqual(status, 0)
            manifest = json.loads((fixture.root / "benchmark-evidence.json").read_text(encoding="utf-8"))
        finally:
            fixture.tearDown()
        record, _size = publish_through_registry(manifest, screenshots=True, run_lane="perf")
        self.assertEqual((record["run"]["kind"], record["run"]["platform"]), ("ui-perf", "ios"))

    def test_a_renamed_metric_is_refused_at_the_round_trip(self) -> None:
        """The mutation the round trip exists for: a producer that drifts from the
        validator's allowlist fails here, not after a consented run."""
        checker = mac_ui.CheckMacOSUIBenchmarkTests("run_checker")
        result = checker.run_checker(
            checker.expected_order,
            mutate_layers=lambda layers: make_rows_realistic(layers["engine"]),
            evidence=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        manifest = copy.deepcopy(checker.last_manifest)
        for take in manifest["historyRecord"]["takes"]:
            take["metrics"]["rtfRenamed"] = take["metrics"].pop("rtf")
        with self.assertRaises(history.HistoryError):
            publish_through_registry(manifest, screenshots=True)


class PublisherRoundTripTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def captured_manifest(self, command, args, *extra_patches) -> dict:
        captured: dict = {}

        def capture(_artifact_dir, manifest, **_kwargs):
            captured["manifest"] = manifest
            return self.root / "benchmark-evidence.json"

        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(publisher, "write_and_record", side_effect=capture))
            stack.enter_context(mock.patch.object(publisher, "source_from_snapshot", return_value=source_fixture()))
            stack.enter_context(mock.patch.object(
                publisher, "crash_delta_from_snapshot", return_value={"passed": True, "count": 0}
            ))
            stack.enter_context(mock.patch.object(
                publisher, "verify_canonical_hardware",
                side_effect=lambda platform, **_kwargs: {
                    "profileID": "mac-mini-m6-16gb" if platform == "macos" else "iphone-17-pro"
                },
            ))
            stack.enter_context(mock.patch.object(publisher, "validated_macos_cli_optimization", return_value="-O"))
            stack.enter_context(mock.patch.object(publisher, "validated_ios_app_optimization", return_value="-O"))
            for patch in extra_patches:
                stack.enter_context(patch)
            command(args)
        return captured["manifest"]

    def v8_engine_rows(
        self, diagnostics: Path, run_id: str, cells: list[tuple[str, str]], *, ios: bool, mutate=None,
    ) -> list[dict]:
        rows = []
        for index, (generation_id, cell) in enumerate(cells, start=1):
            row = engine_row(generation_id, run_id=run_id, cell=cell)
            prefix = cell.split("/", 1)[0]
            mode = prefix if prefix in {"custom", "design", "clone"} else "custom"
            row["mode"] = mode
            row["modelID"] = f"pro_{mode}_speed"
            warm_state = observed_warm_state(cell)
            row["warmState"] = warm_state
            row["backendMetrics"]["warmState"] = warm_state
            row["notes"].update({
                "benchTakeIndex": str(index),
                "deviceClass": "iphone_pro" if ios else "mid_16gb_mac",
                "deviceClassForced": "false",
            })
            upgrade_language_memory_row(row, diagnostics, ios=ios)
            if mutate is not None:
                mutate(row)
            rows.append(row)
        make_rows_realistic(rows)
        (diagnostics / "engine").mkdir(parents=True, exist_ok=True)
        (diagnostics / "engine" / "generations.jsonl").write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8"
        )
        return rows

    def bench_results(self, path: Path, run_id: str, cells: list[tuple[str, str]], outputs: Path, **extra) -> Path:
        takes = []
        for index, (generation_id, cell) in enumerate(cells, start=1):
            mode = cell.split("/", 1)[0]
            name = f"take-{index}.wav"
            write_wave(outputs / name)
            takes.append({
                "takeIndex": index, "generationID": generation_id, "cell": cell,
                "mode": mode, "modelID": f"pro_{mode}_speed", "variant": "speed", "length": "medium",
                "warmState": observed_warm_state(cell),
                "wallSeconds": 1.0, "audioSeconds": 2.0, "firstChunkMS": 300, "outputFileName": name,
            })
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "schemaVersion": 1, "runID": run_id, "label": "roundtrip",
            "startedAt": STARTED_AT, "finishedAt": FINISHED_AT,
            "telemetryMode": "verbose", "seed": 42, "streaming": True,
            "executableSHA256": "a" * 64, "fixtureDigests": {}, "takes": takes, **extra,
        }), encoding="utf-8")
        return path

    def test_macos_memory_qualification_manifest_publishes(self) -> None:
        run_id = "macos-memory-roundtrip-20260920"
        diagnostics = self.root / "diagnostics"
        outputs = self.root / "outputs"
        cells = []
        for mode in ("custom", "design", "clone"):
            if mode != "clone":
                cells.append(f"{mode}/speed/medium/cold#0")
            cells.extend(f"{mode}/speed/medium/retained#{index}" for index in range(3))
        cells = [(f"take-{index}", cell) for index, cell in enumerate(cells, start=1)]
        self.assertEqual(len(cells), 11)
        # The memory lane runs seeded, and the engine stamps its own receipt on
        # every row; a take is published as seeded only when they agree. Each
        # row also carries the engine's per-stage MLX map, whose post-trim
        # snapshot retained-memory-v2 reads.
        def seeded_with_mlx_stages(row: dict) -> None:
            row["notes"].update({"samplingSeed": "19790615", "samplingSeedSource": "requested"})
            take = int(str(row["generationID"]).rsplit("-", 1)[-1])
            row["mlxMemoryByStage"] = {
                "after_stream": {"activeMB": 1900.0 + take, "cacheMB": 300.0, "peakMB": 2200.0},
                "after_generation_trim": {"activeMB": 1800.0 + take, "cacheMB": 0.0, "peakMB": 2200.0},
            }

        self.v8_engine_rows(diagnostics, run_id, cells, ios=False, mutate=seeded_with_mlx_stages)
        results = self.bench_results(
            diagnostics / "bench-results.json", run_id, cells, outputs,
            seed=19_790_615,
            fixtureDigests={"design": "d" * 64, "clone": "d" * 64},
            memoryQualification={
                "policyID": "retained-memory-v1", "modeOrder": ["custom", "design", "clone"],
                "variant": "speed", "length": "medium", "warmRepetitions": 3, "expectedTakeCount": 11,
            },
        )
        args = SimpleNamespace(
            results=results, run_id=run_id, diagnostics=diagnostics, output_dir=outputs,
            platform="macos", artifact_dir=diagnostics, snapshot=self.root / "snapshot.json",
            label="roundtrip",
        )
        manifest = self.captured_manifest(
            lambda arguments: publisher.engine_command(arguments, kind="memory-qualification"), args,
        )
        record, _size = publish_through_registry(manifest)
        self.assertEqual(record["run"]["kind"], "memory-qualification")
        self.assertTrue(record["evidence"]["retentionPassed"])
        # retained-memory-v2 reports beside v1 from the post-trim MLX snapshot:
        # each mode's three retained takes grow by 2 MB (take-N adds N MB).
        retained_v2 = record["evidence"]["retainedMemoryV2"]
        self.assertEqual(retained_v2["calibration"], "uncalibrated")
        self.assertEqual(retained_v2["growthByModeMB"], {"custom": 2.0, "design": 2.0, "clone": 2.0})
        self.assertNotIn("growthLimitMBByMode", retained_v2)
        self.assertEqual(record["takes"][1]["metrics"]["mlxEndActiveMB"], 1802.0)
        self.assertEqual(record["takes"][1]["metrics"]["mlxEndCacheMB"], 0.0)
        # The registry recomputes the block from the takes and holds a
        # calibrated block to its bounds.
        tampered = copy.deepcopy(retained_v2)
        tampered["growthByModeMB"]["clone"] = 0.0
        exceeded = {
            **retained_v2, "calibration": "calibrated", "passed": True,
            "growthLimitMBByMode": {"custom": 1.0, "design": 1.0, "clone": 1.0},
        }
        undeclared_bound = {**retained_v2, "growthLimitMBByMode": {"custom": 9.0}}
        for block in (tampered, exceeded, undeclared_bound):
            with self.assertRaises(history.HistoryError):
                history.validate_retained_memory_v2(block, record["takes"])
        history.validate_retained_memory_v2(
            {**exceeded, "growthLimitMBByMode": {"custom": 4.0, "design": 4.0, "clone": 4.0}},
            record["takes"],
        )

    def test_macos_engine_manifest_publishes(self) -> None:
        run_id = "macos-engine-roundtrip-20260920"
        diagnostics = self.root / "diagnostics"
        outputs = self.root / "outputs"
        cells = [
            ("take-1", "custom/speed/medium/cold#0"),
            ("take-2", "custom/speed/medium/warm#0"),
        ]
        self.v8_engine_rows(diagnostics, run_id, cells, ios=False)
        results = self.bench_results(diagnostics / "bench-results.json", run_id, cells, outputs)
        args = SimpleNamespace(
            results=results, run_id=run_id, diagnostics=diagnostics, output_dir=outputs,
            platform="macos", artifact_dir=diagnostics, snapshot=self.root / "snapshot.json",
            label="roundtrip",
        )
        manifest = self.captured_manifest(publisher.engine_command, args)
        record, _size = publish_through_registry(manifest)
        self.assertEqual(record["run"]["kind"], "engine-generation")
        self.assertEqual(record["run"]["runtimePolicy"], {"deviceClass": "mid_16gb_mac", "deviceClassForced": False})
        self.assertTrue(record["evidence"]["memoryQualified"])

    def test_ios_engine_manifest_publishes(self) -> None:
        run_id = "ios-engine-roundtrip-20260920"
        generation_id = "ios-take-1"
        cell = "custom/speed/device"
        diagnostics = self.root / "diagnostics"
        sentinel = self.root / "device-diagnostics-done.json"
        sentinel.write_text(json.dumps({
            "schemaVersion": 2, "runID": run_id, "generationID": generation_id, "status": "ok",
            "mode": "custom", "variant": "speed", "startedAt": STARTED_AT, "finishedAt": FINISHED_AT,
            "wallSeconds": 5.0, "durationSeconds": 2.0, "deviceModel": "iPhone",
            "systemName": "iOS", "systemVersion": "26.5",
        }), encoding="utf-8")
        self.v8_engine_rows(diagnostics, run_id, [(generation_id, cell)], ios=True)
        app = ios_benchmark_app_row(generation_id, run_id=run_id, cell=cell)
        args = SimpleNamespace(
            sentinel=sentinel, run_id=run_id, diagnostics=diagnostics, artifact_dir=self.root,
            snapshot=self.root / "snapshot.json", crash_diagnostics=self.root / "crashes",
            label="ios-roundtrip", defer_record=True,
        )
        manifest = self.captured_manifest(
            publisher.ios_engine_command, args,
            mock.patch.object(publisher, "load_app_rows", return_value=[app]),
        )
        record, _size = publish_through_registry(manifest)
        self.assertEqual(record["run"]["platform"], "ios")
        self.assertEqual(record["run"]["runtimePolicy"], {"deviceClass": "iphone_pro", "deviceClassForced": False})


    def test_macos_language_manifest_publishes(self) -> None:
        run_id = "lang-roundtrip-20260920"
        matrix = self.root / "matrix.json"
        corpus = self.root / "corpus.json"
        matrix.write_text(json.dumps({"cells": [
            {"id": "fr", "quick": True, "expectedHint": "french", "scriptLang": "french"},
        ]}), encoding="utf-8")
        script = "un deux trois quatre cinq six sept huit"
        corpus.write_text(json.dumps({"languages": [{"id": "french", "script": script}]}), encoding="utf-8")
        diagnostics = self.root / "diagnostics"

        def language_notes(row: dict) -> None:
            row["notes"]["languageHint"] = "french"
            row["notes"]["samplingWAVDigest"] = "a" * 64

        self.v8_engine_rows(diagnostics, run_id, [("fr-id", "fr")], ios=False, mutate=language_notes)
        recognitions = independent_evidence(
            self.root / "independent-asr.json", run_id=run_id, platform="macos",
            cells={"fr": {
                "generationID": "fr-id", "audioSHA256": "a" * 64, "expectedLanguage": "french",
                "expectedOutcome": "pass",
                "recognitions": [independent_recognition(
                    audio_sha256="a" * 64, script=script,
                    transcript="un deux trois quatre cinq six sept neuf",
                )],
            }},
        )
        args = SimpleNamespace(
            matrix=matrix, corpus=corpus, subset="quick", diagnostics=diagnostics,
            run_id=run_id, output_gate="independent", recognitions=recognitions, platform="macos",
            started_at=STARTED_AT, finished_at=FINISHED_AT, label="roundtrip",
            artifact_dir=self.root, snapshot=self.root / "snapshot.json",
        )
        manifest = self.captured_manifest(publisher.language_command, args)
        record, _size = publish_through_registry(manifest)
        self.assertEqual(record["run"]["kind"], "language")
        self.assertEqual(record["evidence"]["languageVerification"]["families"], ["whisper"])

    def test_prosody_calibration_manifest_publishes(self) -> None:
        profile = self.root / "profile.json"
        profile.write_text(json.dumps({"thresholds": {
            "monotone_f0_std_hz": 10.0, "monotone_turning_points_per_sec": 1.0,
            "rushed_syllable_rate_hz": 7.0, "rushed_max_pause_ratio": 0.1,
            "flat_envelope_roughness": 0.02, "flat_rate_cv": 0.2,
            "pause_max_seconds": 1.5, "pause_ratio_max": 0.4,
        }}), encoding="utf-8")
        results = self.root / "calibration-results.json"
        results.write_text(json.dumps({
            "status": "pass", "analysisFailureCount": 0, "runID": "prosody-roundtrip-20260920",
            "label": "roundtrip", "startedAt": STARTED_AT, "finishedAt": FINISHED_AT,
            "goodClipCount": 3, "badClipCount": 4, "targetFalsePositiveRate": 0.05,
            "corpusDigest": "c" * 64, "profileDigest": publisher.digest_file(profile),
            "flagRates": {
                "good_flag_rate": 0.0, "bad_flag_rate": 0.75,
                "false_positive_rate": 0.0, "true_positive_rate": 0.75,
            },
        }), encoding="utf-8")
        args = SimpleNamespace(
            results=results, profile=profile, artifact_dir=self.root, snapshot=self.root / "snapshot.json",
        )
        manifest = self.captured_manifest(publisher.prosody_command, args)
        record, _size = publish_through_registry(manifest)
        self.assertEqual(record["run"]["kind"], "prosody-calibration")


if __name__ == "__main__":
    unittest.main()
