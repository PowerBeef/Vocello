#!/usr/bin/env python3
"""Gate one macOS XPC UI benchmark and emit exact, run-scoped evidence."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from benchmark_memory import (  # noqa: E402
    MemoryEvidenceError,
    REQUIRED_TELEMETRY_SCHEMA,
    qualify_memory_rows,
)

DEFAULT_MODES = ["custom", "design", "clone"]
DEFAULT_LENGTHS = ["short", "medium", "long"]
DEFAULT_WARM = 3
SUCCESS_FINISH = frozenset({"eos", "max_tokens", "maxTokens", "completed"})
THERMAL_RANK = {"unknown": -1, "nominal": 0, "fair": 1, "serious": 2, "critical": 3}
TRIM_SEVERITY = {"softTrim": 1, "hardTrim": 2, "fullUnload": 3}


def is_digest(value) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def exact_model_variant(identity: dict, row: dict) -> str | None:
    """Return the typed variant, with an exact resolved-ID compatibility join.

    Early schema-v7 rows carried the exact variant-scoped model ID before the
    dedicated modelVariant field was added. The suffix join is unambiguous and
    does not inspect prompts, paths, or free-form notes.
    """
    variant = identity.get("modelVariant")
    if variant in {"speed", "quality", "compact_speed", "compact_quality"}:
        return variant
    resolved = identity.get("resolvedModelID") or row.get("modelID")
    if isinstance(resolved, str):
        for candidate in ("compact_quality", "compact_speed", "quality", "speed"):
            if resolved.endswith(f"_{candidate}"):
                return candidate
    return None


def run_hardware_context(rows: list[dict]) -> dict:
    environments = [
        (row.get("summary") or {}).get("runEnvironment") or {}
        for row in rows
    ]
    result: dict = {"profileID": "mac-mini-m2-8gb"}
    loads = [env.get("loadAverage1Minute") for env in environments if isinstance(env.get("loadAverage1Minute"), (int, float))]
    free = [env.get("freeStorageBytes") for env in environments if isinstance(env.get("freeStorageBytes"), int)]
    uptime = [env.get("uptimeSeconds") for env in environments if isinstance(env.get("uptimeSeconds"), (int, float))]
    low_power = [env.get("lowPowerModeEnabled") for env in environments if isinstance(env.get("lowPowerModeEnabled"), bool)]
    thermal = []
    for row, env in zip(rows, environments, strict=True):
        snapshot = row.get("thermalState") or {}
        value = snapshot.get("worst") or env.get("thermalState")
        if isinstance(value, str):
            thermal.append(value.lower())
    if loads: result["loadAverage1M"] = max(loads)
    if free: result["freeStorageBytes"] = min(free)
    if uptime: result["uptimeSeconds"] = min(uptime)
    if low_power: result["lowPowerMode"] = any(low_power)
    known = [value for value in thermal if value in THERMAL_RANK]
    if known: result["thermalState"] = max(known, key=THERMAL_RANK.get)
    return result


def prompt_corpus_digest(rows: list[dict]) -> str:
    ordered = [(row.get("notes") or {}).get("promptDigest") for row in rows]
    return hashlib.sha256(json.dumps(
        ordered, sort_keys=False, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")).hexdigest()


def parse_list(raw: str | None, default: list[str]) -> list[str]:
    values = [part.strip() for part in (raw or "").split(",") if part.strip()]
    if not values:
        values = default.copy()
    if len(values) != len(set(values)):
        raise ValueError("matrix values must be unique")
    unknown = set(values) - set(default)
    if unknown:
        raise ValueError(f"unknown matrix values: {', '.join(sorted(unknown))}")
    return values


def expected_cells(modes: list[str], lengths: list[str], warm: int) -> list[str]:
    cells: list[str] = []
    cold_length = "medium" if "medium" in lengths else lengths[0]
    for mode in modes:
        if mode != "clone":
            cells.append(f"{mode}/{cold_length}/cold#0")
        for length in lengths:
            for repetition in range(warm):
                cells.append(f"{mode}/{length}/warm#{repetition}")
    return cells


def read_jsonl_strict(path: Path) -> tuple[list[dict], list[str]]:
    if not path.is_file():
        return [], [f"missing {path}"]
    rows: list[dict] = []
    failures: list[str] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as error:
            failures.append(f"{path}:{line_number}: malformed JSON: {error.msg}")
            continue
        if not isinstance(row, dict):
            failures.append(f"{path}:{line_number}: row is not a JSON object")
            continue
        rows.append(row)
    return rows, failures


def filter_since(rows: list[dict], since_iso: str) -> list[dict]:
    if not since_iso:
        return rows
    return [row for row in rows if (row.get("recordedAt") or "") >= since_iso]


def filter_run_id(rows: list[dict], run_id: str) -> list[dict]:
    if not run_id:
        return rows
    return [row for row in rows if (row.get("notes") or {}).get("benchRunID") == run_id]


def audio_qc_failure(row: dict) -> str | None:
    output = row.get("outputMetrics") or {}
    qc = row.get("audioQC") or output.get("audioQC") or {}
    verdict = qc.get("verdict")
    if verdict in {"pass", "warn"}:
        return None
    if verdict == "fail":
        return f"failed: {qc.get('flags') or []}"
    return f"verdict is missing or invalid: {verdict!r}"


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_v7_engine_telemetry(row: dict) -> list[str]:
    generation = row.get("generationID", "?")
    summary = row.get("summary")
    if not isinstance(summary, dict):
        return [f"generation {generation} has no schema-v7 sampler summary"]
    failures: list[str] = []
    positive = ("targetIntervalNS", "effectiveIntervalNS")
    nonnegative = ("maximumDriftNS", "maximumLatenessNS", "boundarySampleCount", "captureFailureCount")
    for key in positive:
        if not _number(summary.get(key)) or summary[key] <= 0:
            failures.append(f"generation {generation} has invalid sampler {key}")
    for key in nonnegative:
        if not _number(summary.get(key)) or summary[key] < 0:
            failures.append(f"generation {generation} has invalid sampler {key}")
    resources = summary.get("processResourceUsage")
    resource_fields = (
        "userCPUTimeMS", "systemCPUTimeMS", "minorPageFaults", "majorPageFaults",
        "voluntaryContextSwitches", "involuntaryContextSwitches",
        "blockInputOperations", "blockOutputOperations",
    )
    if not isinstance(resources, dict) or any(
        not _number(resources.get(key)) or resources[key] < 0 for key in resource_fields
    ):
        failures.append(f"generation {generation} has incomplete process resource deltas")
    environment = summary.get("runEnvironment")
    if not isinstance(environment, dict):
        failures.append(f"generation {generation} has no run environment")
    else:
        if not _number(environment.get("loadAverage1Minute")):
            failures.append(f"generation {generation} has invalid load-average context")
        if not isinstance(environment.get("freeStorageBytes"), int) or environment["freeStorageBytes"] < 0:
            failures.append(f"generation {generation} has invalid free-storage context")
        if not _number(environment.get("uptimeSeconds")) or environment["uptimeSeconds"] < 0:
            failures.append(f"generation {generation} has invalid uptime context")
        if not isinstance(environment.get("lowPowerModeEnabled"), bool):
            failures.append(f"generation {generation} has invalid low-power context")
        if str(environment.get("thermalState", "")).lower() not in THERMAL_RANK:
            failures.append(f"generation {generation} has invalid thermal context")
    return failures


def validate_v7_frontend(row: dict) -> list[str]:
    generation = row.get("generationID", "?")
    frontend = row.get("frontendMetrics")
    if not isinstance(frontend, dict):
        return [f"generation {generation} has incomplete typed frontend metrics"]
    required_nonnegative = (
        "submitToFirstChunkMS", "submitToPlaybackScheduledMS", "submitToCompletedMS",
        "firstChunkToPlaybackScheduledMS", "delayedHeartbeatCount50",
        "scheduledHeartbeatCount", "completedHeartbeatCount", "heartbeatCoveragePPM",
        "playbackChunksReceived", "playbackContinuityFailures", "playbackUnderruns",
        "playbackStartBufferedChunks", "playbackStartBufferedAudioMS",
        "playbackMinimumQueuedAudioMS",
    )
    if any(not _number(frontend.get(key)) or frontend[key] < 0 for key in required_nonnegative):
        return [f"generation {generation} has incomplete typed frontend lifecycle/playback metrics"]
    if frontend["playbackChunksReceived"] <= 0 or frontend["playbackStartBufferedChunks"] <= 0:
        return [f"generation {generation} has invalid frontend playback health"]
    if row.get("schemaVersion", 0) >= 8:
        for key in ("delayedHeartbeatCount250", "maximumDelayedHeartbeatMS"):
            if not _number(frontend.get(key)) or frontend[key] < 0:
                return [f"generation {generation} has incomplete schema-v8 frontend metrics"]
        source = frontend.get("playbackStartSource")
        if source not in {"liveStream", "finalFile"}:
            return [f"generation {generation} has invalid playback start source"]
        if frontend["playbackStartBufferedAudioMS"] <= 0:
            return [f"generation {generation} has invalid playback start buffer duration"]
        if source == "finalFile" and frontend["playbackStartBufferedChunks"] != 1:
            return [f"generation {generation} has invalid final-file playback buffer semantics"]
        first = frontend["submitToFirstChunkMS"]
        scheduled = frontend["submitToPlaybackScheduledMS"]
        completed = frontend["submitToCompletedMS"]
        delta = frontend["firstChunkToPlaybackScheduledMS"]
        if not first <= scheduled <= completed or abs((scheduled - first) - delta) > 2:
            return [f"generation {generation} has inconsistent frontend lifecycle ordering"]
    return []


def validate_layer(
    layer: str,
    rows: list[dict],
    expected_ids: list[str],
    expected_count: int,
) -> list[str]:
    failures: list[str] = []
    ids = [row.get("generationID") for row in rows]
    if len(rows) != expected_count:
        failures.append(f"{layer} rows {len(rows)} != expected {expected_count}")
    if any(not isinstance(value, str) or not value for value in ids):
        failures.append(f"one or more {layer} rows has no generationID")
    if len(set(ids)) != len(ids):
        failures.append(f"{layer} generationIDs are not unique")
    expected_set = set(expected_ids)
    actual_set = {value for value in ids if isinstance(value, str) and value}
    if actual_set != expected_set:
        failures.append(
            f"{layer} generationID set mismatch: "
            f"missing={sorted(expected_set - actual_set)} unexpected={sorted(actual_set - expected_set)}"
        )
    for row in rows:
        if row.get("finishReason") not in SUCCESS_FINISH:
            failures.append(
                f"{layer} generation {row.get('generationID', '?')} has unsuccessful "
                f"finishReason={row.get('finishReason')!r}"
            )
    return failures


def validate_merged(
    rows: list[dict], expected_ids: list[str], expected_count: int
) -> list[str]:
    failures: list[str] = []
    ids = [row.get("generationID") for row in rows]
    if len(rows) != expected_count:
        failures.append(f"merged rows {len(rows)} != expected {expected_count}")
    if any(not isinstance(value, str) or not value for value in ids):
        failures.append("one or more merged rows has no generationID")
    if len(set(ids)) != len(ids):
        failures.append("merged generationIDs are not unique")
    expected_set = set(expected_ids)
    actual_set = {value for value in ids if isinstance(value, str) and value}
    if actual_set != expected_set:
        failures.append(
            "generations-merged.jsonl generationID set mismatch: "
            f"missing={sorted(expected_set - actual_set)} unexpected={sorted(actual_set - expected_set)}"
        )
    for row in rows:
        required_layers = row.get("requiredLayers")
        missing_layers = row.get("missingLayers")
        if row.get("complete") is not True:
            failures.append(
                f"merged generation {row.get('generationID', '?')} is not explicitly complete"
            )
        if required_layers != ["app", "engine-service", "engine"]:
            failures.append(
                f"merged generation {row.get('generationID', '?')} has invalid requiredLayers={required_layers!r}"
            )
        if missing_layers != []:
            failures.append(
                f"merged generation {row.get('generationID', '?')} has missingLayers={missing_layers!r}"
            )
        missing = [key for key in ("engine", "engineService", "app") if not isinstance(row.get(key), dict)]
        if missing:
            failures.append(
                f"merged generation {row.get('generationID', '?')} missing complete layer payloads: "
                f"{', '.join(missing)}"
            )
            continue
        gid = row.get("generationID")
        for key in ("engine", "engineService", "app"):
            nested_id = row[key].get("generationID")
            if nested_id != gid:
                failures.append(
                    f"merged generation {gid!r} {key}.generationID={nested_id!r} does not match"
                )
    return failures


def validate_process_ownership(
    engine_rows: list[dict],
    service_rows: list[dict],
    app_rows: list[dict],
    merged_rows: list[dict],
    expected_ids: list[str],
) -> list[str]:
    """Prove that app and XPC memory evidence came from the expected processes."""
    failures: list[str] = []

    def indexed(rows: list[dict]) -> dict[str, dict]:
        return {
            row["generationID"]: row
            for row in rows
            if isinstance(row.get("generationID"), str)
        }

    def pid(row: dict | None, location: str) -> int | None:
        value = row.get("processIdentifier") if isinstance(row, dict) else None
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            failures.append(f"{location} has invalid processIdentifier={value!r}")
            return None
        return value

    engine_by_id = indexed(engine_rows)
    service_by_id = indexed(service_rows)
    app_by_id = indexed(app_rows)
    merged_by_id = indexed(merged_rows)
    for generation_id in expected_ids:
        engine_pid = pid(engine_by_id.get(generation_id), f"engine generation {generation_id}")
        service_pid = pid(
            service_by_id.get(generation_id), f"engine-service generation {generation_id}"
        )
        app_pid = pid(app_by_id.get(generation_id), f"app generation {generation_id}")
        if engine_pid is not None and service_pid is not None and engine_pid != service_pid:
            failures.append(
                f"generation {generation_id} engine PID {engine_pid} != engine-service PID {service_pid}"
            )
        if engine_pid is not None and app_pid is not None and engine_pid == app_pid:
            failures.append(
                f"generation {generation_id} app and engine unexpectedly share PID {engine_pid}"
            )

        merged = merged_by_id.get(generation_id)
        for key, expected_pid in (
            ("engine", engine_pid), ("engineService", service_pid), ("app", app_pid)
        ):
            nested_pid = pid(
                merged.get(key) if isinstance(merged, dict) else None,
                f"merged generation {generation_id} {key}",
            )
            if expected_pid is not None and nested_pid is not None and nested_pid != expected_pid:
                failures.append(
                    f"merged generation {generation_id} {key} PID {nested_pid} "
                    f"!= layer PID {expected_pid}"
                )
    return failures


def matrix_scope(modes: list[str], lengths: list[str], warm: int) -> str:
    return (
        "canonical"
        if modes == DEFAULT_MODES and lengths == DEFAULT_LENGTHS and warm == DEFAULT_WARM
        else "focused"
    )


def memory_trim_metrics(engine: dict) -> tuple[int, int]:
    summary = engine.get("summary") or {}
    backend = engine.get("backendMetrics") or {}
    marks = backend.get("stages") or engine.get("stageMarks") or summary.get("stageMarks") or []
    trim_levels = [
        (mark.get("metadata") or {}).get("level")
        for mark in marks
        if isinstance(mark, dict) and mark.get("stage") == "memory_trim"
    ]
    return len(trim_levels), max((TRIM_SEVERITY.get(level, 0) for level in trim_levels), default=0)


def tracked_metrics(engine: dict, service: dict, app: dict) -> dict[str, float | int]:
    metrics: dict[str, float | int] = {}

    def add(name: str, value, scale: float = 1.0) -> None:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            metrics[name] = value * scale

    derived = engine.get("derivedMetrics") or {}
    for source, destination in (
        ("audioSecondsPerWallSecond", "rtf"),
        ("tokensPerSecond", "tokensPerSecond"),
        ("audioSeconds", "audioSeconds"),
        ("decodeWallSeconds", "decodeWallSeconds"),
    ):
        add(destination, derived.get(source))
    add("generatedTokens", derived.get("generatedTokenCount", derived.get("generatedTokens")))
    trim_count, maximum_trim_level = memory_trim_metrics(engine)
    add("memoryTrimCount", trim_count)
    add("maximumTrimLevel", maximum_trim_level)

    summary = engine.get("summary") or {}
    for source, destination in (
        ("physFootprintPeakMB", "peakPhysicalFootprintMB"),
        ("residentPeakMB", "peakResidentMB"),
        ("compressedPeakMB", "peakCompressedMB"),
        ("gpuAllocatedPeakMB", "peakGPUAllocatedMB"),
        ("headroomMinMB", "minimumHeadroomMB"),
        ("boundarySampleCount", "samplerBoundarySampleCount"),
        ("captureFailureCount", "samplerCaptureFailureCount"),
    ):
        add(destination, summary.get(source))
    add("samplerTargetIntervalMS", summary.get("targetIntervalNS"), 1 / 1_000_000)
    add("samplerEffectiveMedianIntervalMS", summary.get("effectiveIntervalNS"), 1 / 1_000_000)
    add("samplerMaximumLatenessMS", summary.get("maximumLatenessNS"), 1 / 1_000_000)
    add("samplerMaximumDriftMS", summary.get("maximumDriftNS"), 1 / 1_000_000)
    resources = summary.get("processResourceUsage") or {}
    add("cpuUserSeconds", resources.get("userCPUTimeMS"), 1 / 1_000)
    add("cpuSystemSeconds", resources.get("systemCPUTimeMS"), 1 / 1_000)
    add(
        "pageFaults",
        sum(value for value in (resources.get("minorPageFaults"), resources.get("majorPageFaults")) if isinstance(value, int)),
    )
    add(
        "contextSwitches",
        sum(value for value in (resources.get("voluntaryContextSwitches"), resources.get("involuntaryContextSwitches")) if isinstance(value, int)),
    )
    add(
        "blockIOOperations",
        sum(value for value in (resources.get("blockInputOperations"), resources.get("blockOutputOperations")) if isinstance(value, int)),
    )

    backend_timings = {
        item.get("key"): item.get("milliseconds")
        for item in (engine.get("backendMetrics") or {}).get("timings") or []
        if isinstance(item, dict)
    }
    for source, destination in (
        ("modelLoad", "modelLoadMS"),
        ("explicitPrewarm", "prewarmMS"),
        ("finalWAVFinish", "finalizationMS"),
    ):
        add(destination, backend_timings.get(source))

    transport = service.get("transportMetrics") or {}
    add("requestToFirstChunkMS", transport.get("requestToFirstChunkMS"))
    transport_counters = transport.get("counters") or service.get("counters") or {}
    add("chunksForwarded", transport_counters.get("chunksForwarded"))
    add("transportChunkGaps", transport_counters.get("chunkGaps"))
    add("transportDuplicateChunks", transport_counters.get("duplicateChunks"))
    add("transportOutOfOrderChunks", transport_counters.get("outOfOrderChunks"))

    frontend = app.get("frontendMetrics") or {}
    for source, destination in (
        ("submitToFirstChunkMS", "submitToFirstChunkMS"),
        ("submitToPlaybackScheduledMS", "playbackScheduledMS"),
        ("firstChunkToPlaybackScheduledMS", "firstChunkToPlaybackScheduledMS"),
        ("submitToCompletedMS", "submitToCompletedMS"),
    ):
        add(destination, frontend.get(source))
    add(
        "uiMaximumDelayedHeartbeatMS",
        frontend.get("maximumDelayedHeartbeatMS", frontend.get("mainThreadMaximumStallMS")),
    )
    counters = app.get("counters") or {}
    timings = app.get("timingsMS") or {}
    add("delayedHeartbeatCount", frontend.get("delayedHeartbeatCount50", counters.get("delayedHeartbeatCount50")))
    add("heartbeatCoverage", frontend.get("heartbeatCoveragePPM", counters.get("heartbeatCoveragePPM")), 1 / 1_000_000)
    add("chunksReceived", frontend.get("playbackChunksReceived", counters.get("playbackChunksReceived")))
    add("continuityFailures", frontend.get("playbackContinuityFailures", counters.get("playbackContinuityFailures")))
    add("underruns", frontend.get("playbackUnderruns", counters.get("playbackUnderruns")))
    add("startBufferDepth", frontend.get("playbackStartBufferedChunks", counters.get("playbackStartBufferedChunks")))
    add("minimumQueueDurationMS", frontend.get("playbackMinimumQueuedAudioMS", timings.get("playbackMinimumQueuedAudioMS")))
    return metrics


def build_manifest(
    diagnostics: Path,
    run_id: str,
    label: str,
    modes: list[str],
    lengths: list[str],
    warm: int,
    cells: list[str],
    engine_rows: list[dict],
    service_rows: list[dict],
    app_rows: list[dict],
    merged_rows: list[dict],
) -> dict:
    memory_evidence, memory_run = qualify_memory_rows(
        rows=engine_rows,
        diagnostics=diagnostics,
        platform="macos",
        app_rows=app_rows,
        require_app_layer=True,
    )
    memory_by_id = {item.generation_id: item for item in memory_evidence}
    app_by_id = {row.get("generationID"): row for row in app_rows}
    takes = []
    warning_count = 0
    for index, (row, cell) in enumerate(zip(engine_rows, cells, strict=True), start=1):
        mode, length, state_repetition = cell.split("/")
        state, repetition = state_repetition.split("#")
        output = row.get("outputMetrics") or {}
        qc = row.get("audioQC") or output.get("audioQC") or {}
        memory = memory_by_id[row["generationID"]]
        frontend = (app_by_id.get(row["generationID"]) or {}).get("frontendMetrics") or {}
        if qc.get("verdict") == "warn" or memory.warnings:
            warning_count += 1
        completeness = {"engine": True, "engineService": True, "app": True, "merged": True}
        takes.append({
            "takeIndex": index,
            "generationID": row["generationID"],
            "cell": cell,
            "mode": mode,
            "length": length,
            "warmState": state,
            "repetition": int(repetition),
            "status": "passedWithWarnings" if qc.get("verdict") == "warn" or memory.warnings else "pass",
            "finishReason": row.get("finishReason"),
            "playbackStartSource": frontend.get("playbackStartSource"),
            "readableWAV": True,
            "atomicPublish": True,
            "outputDurationSeconds": output.get("durationSeconds"),
            "audioQC": {"verdict": qc.get("verdict"), "flags": qc.get("flags") or []},
            "layerCompleteness": completeness,
        })
    status = "passedWithWarnings" if warning_count else "pass"
    scope = matrix_scope(modes, lengths, warm)
    expected = len(cells)
    hardware = run_hardware_context(engine_rows)
    recorded = sorted(
        row.get("recordedAt") for row in engine_rows
        if isinstance(row.get("recordedAt"), str) and row.get("recordedAt")
    )
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    started_at = recorded[0] if recorded else now
    finished_at = recorded[-1] if recorded else now
    selected_telemetry = {
        "engine": engine_rows,
        "engineService": service_rows,
        "app": app_rows,
        "merged": merged_rows,
        "sampleSidecars": memory_run["digestPayload"],
    }
    raw_telemetry_digest = hashlib.sha256(
        json.dumps(
            selected_telemetry,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    telemetry_schema = max(
        (int(row.get("schemaVersion", 0)) for rows in selected_telemetry.values() for row in rows),
        default=0,
    )
    qc_algorithm = max(
        (
            int(((row.get("audioQC") or (row.get("outputMetrics") or {}).get("audioQC") or {})).get("algorithmVersion", 1))
            for row in engine_rows
        ),
        default=1,
    )
    history_takes = []
    service_by_id = {row.get("generationID"): row for row in service_rows}
    for take, row in zip(takes, engine_rows, strict=True):
        generation_id = take["generationID"]
        model_identity = row.get("modelRuntimeIdentity") or {}
        memory = memory_by_id[generation_id]
        metrics = tracked_metrics(
            row,
            service_by_id.get(generation_id) or {},
            app_by_id.get(generation_id) or {},
        )
        metrics.update(memory.metrics)
        qc = take["audioQC"]
        raw_qc = row.get("audioQC") or (row.get("outputMetrics") or {}).get("audioQC") or {}
        qc_metrics = {}
        for source, destination in (
            ("nonFiniteSamples", "nonFiniteCount"),
            ("clippedSamples", "clipCount"),
            ("clickEvents", "discontinuityCount"),
            ("longestSilenceMS", "longestSilenceMS"),
            ("dcOffset", "dcOffset"),
        ):
            value = raw_qc.get(source)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                qc_metrics[destination] = value
        take_warnings = sorted(set(
            (qc["flags"] if qc["verdict"] == "warn" else []) + list(memory.warnings)
        ))
        history_takes.append({
            "takeIndex": take["takeIndex"],
            "generationID": take["generationID"],
            "cell": take["cell"],
            "mode": take["mode"],
            "variant": exact_model_variant(model_identity, row) or "not-applicable",
            "modelID": row.get("modelID") or "not-applicable",
            "modelRepository": model_identity.get("modelRepository") or "not-applicable",
            "modelRevision": model_identity.get("huggingFaceRevision") or "not-applicable",
            "modelArtifactVersion": model_identity.get("artifactVersion") or "not-applicable",
            "modelQuantization": model_identity.get("quantization") or "not-applicable",
            "runtimeProfileSignature": model_identity.get("runtimeProfileSignature") or row.get("modelID") or "not-applicable",
            "fixtureDigest": model_identity.get("fixtureDigest") or "not-applicable",
            "modelIntegrityDigest": model_identity.get("integrityManifestDigest") or "not-applicable",
            "warmState": take["warmState"],
            "length": take["length"],
            "finishReason": "completed",
            "playbackStartSource": (
                (app_by_id.get(generation_id) or {}).get("frontendMetrics") or {}
            ).get("playbackStartSource"),
            "status": "passedWithWarnings" if take_warnings else "passed",
            "layerCompleteness": "complete",
            "layers": ["engine", "engine-service", "app", "merged"],
            "metrics": metrics,
            "output": {
                "readableWAV": True,
                "atomicPublish": True,
                "durationSeconds": take["outputDurationSeconds"],
            },
            "audioQC": {
                "algorithmVersion": raw_qc.get("algorithmVersion", 1),
                "verdict": qc["verdict"],
                "instabilityVerdict": raw_qc.get("instabilityVerdict"),
                "writtenOutputVerdict": raw_qc.get("writtenOutputVerdict"),
                "warningCodes": qc["flags"] if qc["verdict"] == "warn" else [],
                "metrics": qc_metrics,
            },
            "thermalState": ((row.get("summary") or {}).get("thermalState") or {}).get("worst", "unknown"),
            "warnings": take_warnings,
            "memoryStatus": memory.status,
            "sampleSidecarDigest": memory.sidecar_digest,
            **take_quality_identity(row),
        })
    history_record = {
        "schemaVersion": history_record_schema_version(history_takes),
        "run": {
            "id": run_id,
            "kind": "ui-generation",
            "platform": "macos",
            "status": "passedWithWarnings" if warning_count else "passed",
            "label": label or run_id,
            "matrixScope": scope,
            "startedAt": started_at,
            "finishedAt": finished_at,
            "warnings": memory_run["warnings"],
        },
        "hardware": hardware,
        "toolchain": {"optimization": "-O"},
        "inputs": {"corpusHash": prompt_corpus_digest(engine_rows)},
        "evidence": {
            "validatorPassed": True,
            "crashDeltaPassed": True,
            "crashCount": 0,
            "expectedTakeCount": expected,
            "actualTakeCount": len(engine_rows),
            "rawTelemetryDigest": raw_telemetry_digest,
            "telemetrySchemaVersion": telemetry_schema,
            "qcAlgorithmVersion": qc_algorithm,
            "memoryContractVersion": memory_run["memoryContractVersion"],
            "memoryQualified": memory_run["memoryQualified"],
            "sampleSidecarCount": memory_run["sampleSidecarCount"],
            "sampleSidecarsDigest": memory_run["sampleSidecarsDigest"],
        },
        "takes": history_takes,
    }
    return {
        "schemaVersion": 2,
        "benchmarkKind": "ui-generation",
        "platform": "macos",
        "runID": run_id,
        "status": status,
        "warningCount": warning_count,
        "rawTelemetryDigest": raw_telemetry_digest,
        "telemetrySchemaVersion": telemetry_schema,
        "qcAlgorithmVersion": qc_algorithm,
        "matrix": {
            "modes": modes,
            "lengths": lengths,
            "warm": warm,
            "scope": scope,
            "expectedTakeCount": expected,
            "orderedCells": cells,
        },
        "layers": {
            "engine": {"count": expected, "complete": True},
            "engineService": {"count": expected, "complete": True},
            "app": {"count": expected, "complete": True},
            "merged": {"count": expected, "complete": True},
        },
        "takes": takes,
        "historyRecord": history_record,
    }


def take_quality_identity(row: dict) -> dict:
    """Phase 13 fold: the typed quality-registry identity this engine row
    published with, from its open telemetry notes (mirrors
    publish_benchmark_history.quality_identity_fields; keep in lockstep).
    Empty when the row predates the phase-12 registry; the record then
    publishes at schema v2."""
    notes = row.get("notes") if isinstance(row.get("notes"), dict) else {}
    outcome = notes.get("quality_registry_outcome")
    gates = notes.get("quality_registry_required_gates")
    if not isinstance(outcome, str) or not isinstance(gates, str) or not gates:
        return {}
    fields = {
        "qualityRegistryOutcome": outcome,
        "qualityRegistryRequiredGates": sorted(set(gates.split(","))),
    }
    issues = notes.get("quality_registry_issues")
    if isinstance(issues, str) and issues:
        fields["qualityRegistryIssues"] = sorted(set(issues.split(",")))
    return fields


def history_record_schema_version(history_takes: list) -> int:
    """3 when every take carries the quality identity, 2 when none does.
    A mix would publish a record silently missing evidence for some takes."""
    carrying = sum(1 for take in history_takes if "qualityRegistryOutcome" in take)
    if carrying == 0:
        return 2
    if carrying == len(history_takes):
        return 3
    raise SystemExit(
        "takes mix quality-registry identity presence; refusing a partial schema-v3 record"
    )


def write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("diag_dir", type=Path, help="QwenVoice-Debug/diagnostics directory")
    parser.add_argument("--modes", default=",".join(DEFAULT_MODES))
    parser.add_argument("--lengths", default=",".join(DEFAULT_LENGTHS))
    parser.add_argument("--warm", type=int, default=DEFAULT_WARM)
    parser.add_argument("--run-id", default="", help="select only notes.benchRunID rows")
    parser.add_argument("--max-chunk-gaps", type=int, default=0)
    parser.add_argument("--max-delayed-heartbeats-50", type=int, default=0)
    parser.add_argument("--since-recorded", default="")
    parser.add_argument("--label", default="")
    parser.add_argument("--evidence-manifest", type=Path, metavar="PATH")
    parser.add_argument(
        "--crash-delta-passed",
        action="store_true",
        help="assert that the caller completed its pre/post crash-delta gate",
    )
    args = parser.parse_args()

    if args.evidence_manifest and args.evidence_manifest.exists():
        args.evidence_manifest.unlink()
    if args.evidence_manifest and not args.run_id:
        parser.error("--evidence-manifest requires --run-id")
    if args.evidence_manifest and not args.crash_delta_passed:
        parser.error("--evidence-manifest requires --crash-delta-passed")
    if args.warm < 1:
        parser.error("--warm must be at least 1")
    try:
        modes = parse_list(args.modes, DEFAULT_MODES)
        lengths = parse_list(args.lengths, DEFAULT_LENGTHS)
    except ValueError as error:
        parser.error(str(error))

    expected_cell_order = expected_cells(modes, lengths, args.warm)
    expected = len(expected_cell_order)
    paths = {
        "engine": args.diag_dir / "engine" / "generations.jsonl",
        "engine-service": args.diag_dir / "engine-service" / "generations.jsonl",
        "app": args.diag_dir / "app" / "generations.jsonl",
        "merged": args.diag_dir / "generations-merged.jsonl",
    }
    failures: list[str] = []
    loaded: dict[str, list[dict]] = {}
    for layer, path in paths.items():
        rows, read_failures = read_jsonl_strict(path)
        failures.extend(read_failures)
        rows = filter_since(rows, args.since_recorded)
        if layer != "merged":
            rows = filter_run_id(rows, args.run_id)
        loaded[layer] = rows

    engine_rows = loaded["engine"]
    service_rows = loaded["engine-service"]
    app_rows = loaded["app"]
    engine_ids = [row.get("generationID") for row in engine_rows]
    valid_engine_ids = [value for value in engine_ids if isinstance(value, str) and value]
    engine_id_set = set(valid_engine_ids)
    merged_rows = [row for row in loaded["merged"] if row.get("generationID") in engine_id_set]

    if len(engine_rows) != expected:
        failures.append(f"engine rows {len(engine_rows)} != expected {expected}")
    if any(not isinstance(value, str) or not value for value in engine_ids):
        failures.append("one or more engine rows has no generationID")
    if len(set(engine_ids)) != len(engine_ids):
        failures.append("engine generationIDs are not unique")
    failures.extend(validate_layer("engine-service", service_rows, valid_engine_ids, expected))
    failures.extend(validate_layer("app", app_rows, valid_engine_ids, expected))
    failures.extend(validate_merged(merged_rows, valid_engine_ids, expected))
    failures.extend(
        validate_process_ownership(
            engine_rows, service_rows, app_rows, merged_rows, valid_engine_ids
        )
    )

    actual_cells: list[str] = []
    actual_indices: list[int] = []
    for row in engine_rows:
        notes = row.get("notes") or {}
        cell = notes.get("benchCell")
        if isinstance(cell, str):
            actual_cells.append(cell)
        else:
            failures.append(f"generation {row.get('generationID', '?')} has no valid benchCell")
        try:
            actual_indices.append(int(notes.get("benchTakeIndex")))
        except (TypeError, ValueError):
            failures.append(f"generation {row.get('generationID', '?')} has no valid benchTakeIndex")
        finish = row.get("finishReason")
        if finish not in SUCCESS_FINISH:
            failures.append(
                f"generation {row.get('generationID', '?')} has unsuccessful finishReason={finish!r}"
            )
        if qc_failure := audio_qc_failure(row):
            failures.append(f"audioQC {qc_failure} for engine generation {row.get('generationID', '?')}")
        output = row.get("outputMetrics") or {}
        if output.get("readableWAV") is not True:
            failures.append(f"generation {row.get('generationID', '?')} did not prove a readable WAV")
        if output.get("atomicallyPublished") is not True:
            failures.append(f"generation {row.get('generationID', '?')} was not atomically published")
        if not isinstance(output.get("durationSeconds"), (int, float)) or output["durationSeconds"] <= 0:
            failures.append(f"generation {row.get('generationID', '?')} has no positive output duration")
        identity = row.get("modelRuntimeIdentity") or {}
        if row.get("schemaVersion", 0) >= 7:
            failures.extend(validate_v7_engine_telemetry(row))
            if not isinstance(row.get("backendMetrics"), dict):
                failures.append(f"generation {row.get('generationID', '?')} has no typed backend metrics")
            if identity.get("resolvedModelID") != row.get("modelID"):
                failures.append(f"generation {row.get('generationID', '?')} has mismatched typed model identity")
            if exact_model_variant(identity, row) is None:
                failures.append(f"generation {row.get('generationID', '?')} has no exact model variant")
            if not isinstance(identity.get("runtimeProfileSignature"), str) or not identity["runtimeProfileSignature"]:
                failures.append(f"generation {row.get('generationID', '?')} has no typed runtime profile signature")
            if not isinstance(identity.get("modelRepository"), str) or "/" not in identity["modelRepository"]:
                failures.append(f"generation {row.get('generationID', '?')} has no typed model repository")
            revision = identity.get("huggingFaceRevision")
            if not isinstance(revision, str) or len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision):
                failures.append(f"generation {row.get('generationID', '?')} has no pinned model revision")
            if not isinstance(identity.get("artifactVersion"), str) or not identity["artifactVersion"]:
                failures.append(f"generation {row.get('generationID', '?')} has no model artifact version")
            if identity.get("quantization") not in {"4-bit", "8-bit", "unquantized"}:
                failures.append(f"generation {row.get('generationID', '?')} has invalid model quantization")
            if not is_digest(identity.get("integrityManifestDigest")):
                failures.append(f"generation {row.get('generationID', '?')} has no model integrity-manifest digest")
            if not is_digest(notes.get("promptDigest")):
                failures.append(f"generation {row.get('generationID', '?')} has no privacy-safe prompt digest")
            if row.get("mode") in {"design", "clone"} and not is_digest(identity.get("fixtureDigest")):
                failures.append(f"generation {row.get('generationID', '?')} has no exact fixture digest")
        if row.get("schemaVersion", 0) < REQUIRED_TELEMETRY_SCHEMA:
            failures.append(
                f"generation {row.get('generationID', '?')} requires telemetry schema "
                f"v{REQUIRED_TELEMETRY_SCHEMA} or newer for memory qualification"
            )

    if actual_cells != expected_cell_order:
        failures.append(f"benchmark cell order differs: actual={actual_cells} expected={expected_cell_order}")
    if actual_indices != list(range(1, expected + 1)):
        failures.append(f"benchmark take order differs: actual={actual_indices} expected=1..{expected}")
    for row in engine_rows:
        cell = (row.get("notes") or {}).get("benchCell", "")
        intended = "cold" if "/cold#" in cell else "warm"
        if row.get("warmState") != intended:
            failures.append(
                f"generation {row.get('generationID', '?')} warmState={row.get('warmState')!r} "
                f"does not match cell {cell!r}"
            )

    for row in service_rows:
        if row.get("schemaVersion", 0) >= 7:
            transport = row.get("transportMetrics")
            if not isinstance(transport, dict):
                failures.append(f"generation {row.get('generationID', '?')} has no typed transport metrics")
            else:
                if transport.get("requestAccepted") is not True:
                    failures.append(f"generation {row.get('generationID', '?')} was not accepted by XPC transport")
                request_latency = transport.get("requestToFirstChunkMS")
                if not _number(request_latency) or request_latency < 0:
                    failures.append(f"generation {row.get('generationID', '?')} has no request-to-first-chunk transport latency")
        gaps = (row.get("counters") or {}).get("chunkGaps")
        transport_gaps = ((row.get("transportMetrics") or {}).get("counters") or {}).get("chunkGaps")
        gaps = transport_gaps if transport_gaps is not None else gaps
        if gaps is not None and not isinstance(gaps, int):
            failures.append(f"generation {row.get('generationID', '?')} has invalid chunkGaps={gaps!r}")
        elif isinstance(gaps, int) and gaps > args.max_chunk_gaps:
            failures.append(
                f"chunkGaps {gaps} > {args.max_chunk_gaps} (generation {row.get('generationID', '?')})"
            )

    app_by_id = {row.get("generationID"): row for row in app_rows if row.get("generationID")}
    for row in app_rows:
        if row.get("schemaVersion", 0) < 7:
            continue
        failures.extend(validate_v7_frontend(row))
        if row.get("schemaVersion", 0) < REQUIRED_TELEMETRY_SCHEMA:
            failures.append(
                f"app generation {row.get('generationID', '?')} requires telemetry schema "
                f"v{REQUIRED_TELEMETRY_SCHEMA} or newer for memory qualification"
            )
    for engine_row in engine_rows:
        gid = engine_row.get("generationID")
        device = (engine_row.get("notes") or {}).get("deviceClass") or ""
        if device != "floor8GBMac":
            continue
        app_row = app_by_id.get(gid) or {}
        counters = app_row.get("counters") or {}
        frontend = app_row.get("frontendMetrics") or {}
        stalls = frontend.get("delayedHeartbeatCount50", frontend.get("mainThreadStallCount50MS"))
        if stalls is None:
            stalls = counters.get("uiStallCount50")
        if stalls is not None and not isinstance(stalls, int):
            failures.append(f"app generation {gid or '?'} has invalid 50 ms stall counter={stalls!r}")
        elif isinstance(stalls, int) and stalls > args.max_delayed_heartbeats_50:
            failures.append(
                f"delayedHeartbeatCount50 {stalls} > {args.max_delayed_heartbeats_50} (generation {gid})"
            )

    if not failures:
        try:
            qualify_memory_rows(
                rows=engine_rows,
                diagnostics=args.diag_dir,
                platform="macos",
                app_rows=app_rows,
                require_app_layer=True,
            )
        except MemoryEvidenceError as error:
            failures.append(str(error))

    print(
        f"XPC bench gate: expected={expected} engine={len(engine_rows)} "
        f"service={len(service_rows)} app={len(app_rows)} merged={len(merged_rows)}"
    )
    if failures:
        print("FAIL:")
        for item in failures:
            print(f"  - {item}")
        return 1

    if args.evidence_manifest:
        manifest = build_manifest(
            args.diag_dir,
            args.run_id,
            args.label,
            modes,
            lengths,
            args.warm,
            expected_cell_order,
            engine_rows,
            service_rows,
            app_rows,
            merged_rows,
        )
        write_json_atomic(args.evidence_manifest, manifest)
        print(f"evidence={args.evidence_manifest}")
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
