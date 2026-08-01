#!/usr/bin/env python3
"""Validate one physical-iPhone XCUITest benchmark and emit scoped evidence."""

from __future__ import annotations

import argparse
from collections import Counter
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
SUCCESS_FINISH = {"eos", "max_tokens", "maxTokens", "completed"}
THERMAL_RANK = {"unknown": -1, "nominal": 0, "fair": 1, "serious": 2, "critical": 3}
TRIM_SEVERITY = {"softTrim": 1, "hardTrim": 2, "fullUnload": 3}


def is_digest(value) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def exact_model_variant(identity: dict, row: dict) -> str | None:
    """Return the typed variant, with an exact resolved-ID compatibility join."""
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
    environments = [(row.get("summary") or {}).get("runEnvironment") or {} for row in rows]
    result: dict = {"profileID": "iphone-17-pro"}
    loads = [env.get("loadAverage1Minute") for env in environments if isinstance(env.get("loadAverage1Minute"), (int, float))]
    free = [env.get("freeStorageBytes") for env in environments if isinstance(env.get("freeStorageBytes"), int)]
    uptime = [env.get("uptimeSeconds") for env in environments if isinstance(env.get("uptimeSeconds"), (int, float))]
    low_power = [env.get("lowPowerModeEnabled") for env in environments if isinstance(env.get("lowPowerModeEnabled"), bool)]
    thermal = []
    for row, env in zip(rows, environments, strict=True):
        snapshot = row.get("thermalState") or {}
        value = snapshot.get("worst") or env.get("thermalState")
        if isinstance(value, str): thermal.append(value.lower())
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


def parse_list(raw: str, allowed: list[str], kind: str) -> list[str]:
    values = [value.strip() for value in raw.split(",") if value.strip()]
    if not values or len(values) != len(set(values)):
        raise ValueError(f"{kind} list must be non-empty and unique")
    unknown = set(values) - set(allowed)
    if unknown:
        raise ValueError(f"unknown {kind}: {', '.join(sorted(unknown))}")
    return values


def length_bucket(chars: int) -> str:
    """Map the shared XCUITest corpus to its declared length cells.

    The physical-iPhone corpus intentionally uses a 150-character long prompt,
    unlike the older CLI corpus whose long prompt was over 220 characters.
    """
    if chars < 70:
        return "short"
    if chars >= 140:
        return "long"
    return "medium"


def expected_ordered_cells(
    modes: list[str], lengths: list[str], warm: int
) -> list[tuple[str, str, str, int]]:
    cells: list[tuple[str, str, str, int]] = []
    cold_length = "medium" if "medium" in lengths else lengths[0]
    for mode in modes:
        if mode != "clone":
            cells.append((mode, cold_length, "cold", 0))
        for length in lengths:
            cells.extend((mode, length, "warm", repetition) for repetition in range(warm))
    return cells


def cell_name(cell: tuple[str, str, str, int]) -> str:
    mode, length, state, repetition = cell
    return f"{mode}/{length}/{state}#{repetition}"


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


def filter_run(rows: list[dict], run_id: str) -> list[dict]:
    return [row for row in rows if (row.get("notes") or {}).get("benchRunID") == run_id]


def output_failure(row: dict) -> str | None:
    output = row.get("outputMetrics") or {}
    qc = row.get("audioQC") or output.get("audioQC") or {}
    if row.get("finishReason") not in SUCCESS_FINISH:
        return f"unsuccessful finishReason={row.get('finishReason')!r}"
    if output.get("readableWAV") is not True:
        return "outputMetrics.readableWAV is not true"
    if output.get("atomicallyPublished") is not True:
        return "outputMetrics.atomicallyPublished is not true"
    if not isinstance(output.get("durationSeconds"), (int, float)) or output["durationSeconds"] <= 0:
        return "output duration is missing or non-positive"
    verdict = qc.get("verdict")
    if verdict not in {"pass", "warn"}:
        if verdict == "fail":
            return f"audioQC failed: {qc.get('flags') or []}"
        return f"audioQC verdict is missing or invalid: {verdict!r}"
    return None


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_v7_engine_telemetry(row: dict) -> list[str]:
    generation = row.get("generationID", "?")
    summary = row.get("summary")
    if not isinstance(summary, dict):
        return [f"{generation}: missing schema-v7 sampler summary"]
    failures: list[str] = []
    for key in ("targetIntervalNS", "effectiveIntervalNS"):
        if not _number(summary.get(key)) or summary[key] <= 0:
            failures.append(f"{generation}: invalid sampler {key}")
    for key in ("maximumDriftNS", "maximumLatenessNS", "boundarySampleCount", "captureFailureCount"):
        if not _number(summary.get(key)) or summary[key] < 0:
            failures.append(f"{generation}: invalid sampler {key}")
    resources = summary.get("processResourceUsage")
    resource_fields = (
        "userCPUTimeMS", "systemCPUTimeMS", "minorPageFaults", "majorPageFaults",
        "voluntaryContextSwitches", "involuntaryContextSwitches",
        "blockInputOperations", "blockOutputOperations",
    )
    if not isinstance(resources, dict) or any(
        not _number(resources.get(key)) or resources[key] < 0 for key in resource_fields
    ):
        failures.append(f"{generation}: incomplete process resource deltas")
    environment = summary.get("runEnvironment")
    if not isinstance(environment, dict):
        failures.append(f"{generation}: missing run environment")
    else:
        if not _number(environment.get("loadAverage1Minute")):
            failures.append(f"{generation}: invalid load-average context")
        if not isinstance(environment.get("freeStorageBytes"), int) or environment["freeStorageBytes"] < 0:
            failures.append(f"{generation}: invalid free-storage context")
        if not _number(environment.get("uptimeSeconds")) or environment["uptimeSeconds"] < 0:
            failures.append(f"{generation}: invalid uptime context")
        if not isinstance(environment.get("lowPowerModeEnabled"), bool):
            failures.append(f"{generation}: invalid low-power context")
        if str(environment.get("thermalState", "")).lower() not in THERMAL_RANK:
            failures.append(f"{generation}: invalid thermal context")
    return failures


def validate_v7_frontend(row: dict) -> list[str]:
    generation = row.get("generationID", "?")
    frontend = row.get("frontendMetrics")
    if not isinstance(frontend, dict):
        return [f"{generation}: incomplete typed frontend metrics"]
    required_nonnegative = (
        "submitToFirstChunkMS", "submitToPlaybackScheduledMS", "submitToCompletedMS",
        "firstChunkToPlaybackScheduledMS", "delayedHeartbeatCount50",
        "scheduledHeartbeatCount", "completedHeartbeatCount", "heartbeatCoveragePPM",
        "playbackChunksReceived", "playbackContinuityFailures", "playbackUnderruns",
        "playbackStartBufferedChunks", "playbackStartBufferedAudioMS",
        "playbackMinimumQueuedAudioMS",
    )
    if any(not _number(frontend.get(key)) or frontend[key] < 0 for key in required_nonnegative):
        return [f"{generation}: incomplete typed frontend lifecycle/playback metrics"]
    start_source = frontend.get("playbackStartSource")
    if start_source not in {"liveStream", "finalFile"}:
        return [f"{generation}: missing or invalid typed playback start source"]
    if frontend["playbackChunksReceived"] <= 0 or frontend["playbackStartBufferedChunks"] <= 0:
        return [f"{generation}: invalid frontend playback health"]
    if start_source == "finalFile" and frontend["playbackStartBufferedChunks"] != 1:
        return [f"{generation}: final-file playback must expose one active file buffer"]
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
    if Counter(ids) != Counter(expected_ids):
        missing = sorted(set(expected_ids) - {value for value in ids if isinstance(value, str)})
        unexpected = sorted({value for value in ids if isinstance(value, str)} - set(expected_ids))
        failures.append(
            f"{layer} generationID set mismatch: missing={missing} unexpected={unexpected}"
        )
    for row in rows:
        if row.get("finishReason") not in SUCCESS_FINISH:
            failures.append(
                f"{layer} generation {row.get('generationID', '?')} has unsuccessful "
                f"finishReason={row.get('finishReason')!r}"
            )
    return failures


def matrix_scope(modes: list[str], lengths: list[str], warm: int) -> str:
    return (
        "canonical"
        if modes == DEFAULT_MODES and lengths == DEFAULT_LENGTHS and warm == 3
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


def tracked_metrics(engine: dict, app: dict) -> dict[str, float | int]:
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
    add("pageFaults", sum(value for value in (resources.get("minorPageFaults"), resources.get("majorPageFaults")) if isinstance(value, int)))
    add("contextSwitches", sum(value for value in (resources.get("voluntaryContextSwitches"), resources.get("involuntaryContextSwitches")) if isinstance(value, int)))
    add("blockIOOperations", sum(value for value in (resources.get("blockInputOperations"), resources.get("blockOutputOperations")) if isinstance(value, int)))
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
    cells: list[tuple[str, str, str, int]],
    engine_rows: list[dict],
    app_rows: list[dict],
) -> dict:
    memory_evidence, memory_run = qualify_memory_rows(
        rows=engine_rows,
        diagnostics=diagnostics,
        platform="ios",
    )
    memory_by_id = {item.generation_id: item for item in memory_evidence}
    takes = []
    warning_count = 0
    for index, (row, cell) in enumerate(zip(engine_rows, cells, strict=True), start=1):
        output = row.get("outputMetrics") or {}
        qc = row.get("audioQC") or output.get("audioQC") or {}
        memory = memory_by_id[row["generationID"]]
        if qc.get("verdict") == "warn" or memory.warnings:
            warning_count += 1
        completeness = {"engine": True, "app": True}
        takes.append({
            "takeIndex": index,
            "generationID": row["generationID"],
            "cell": cell_name(cell),
            "mode": cell[0],
            "length": cell[1],
            "warmState": cell[2],
            "repetition": cell[3],
            "status": "passedWithWarnings" if qc.get("verdict") == "warn" or memory.warnings else "pass",
            "finishReason": row.get("finishReason"),
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
        "app": app_rows,
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
    app_by_id = {row.get("generationID"): row for row in app_rows}
    for take, row in zip(takes, engine_rows, strict=True):
        model_identity = row.get("modelRuntimeIdentity") or {}
        app_row = app_by_id.get(take["generationID"]) or {}
        memory = memory_by_id[take["generationID"]]
        metrics = tracked_metrics(row, app_row)
        metrics.update(memory.metrics)
        playback_start_source = (app_row.get("frontendMetrics") or {}).get(
            "playbackStartSource"
        )
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
        history_take = {
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
            "status": "passedWithWarnings" if take_warnings else "passed",
            "layerCompleteness": "complete",
            "layers": ["engine", "app"],
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
        }
        if playback_start_source in {"liveStream", "finalFile"}:
            history_take["playbackStartSource"] = playback_start_source
        history_takes.append(history_take)
    history_record = {
        "schemaVersion": history_record_schema_version(history_takes),
        "run": {
            "id": run_id,
            "kind": "ui-generation",
            "platform": "ios",
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
        "platform": "ios",
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
            "orderedCells": [cell_name(cell) for cell in cells],
        },
        "layers": {
            "engine": {"count": len(engine_rows), "complete": True},
            "app": {"count": len(engine_rows), "complete": True},
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
    parser.add_argument("diagnostics", type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--modes", default=",".join(DEFAULT_MODES))
    parser.add_argument("--lengths", default=",".join(DEFAULT_LENGTHS))
    parser.add_argument("--warm", type=int, default=3)
    parser.add_argument("--label", default="")
    parser.add_argument("--generation-map", type=Path, required=True)
    parser.add_argument("--evidence-manifest", type=Path, metavar="PATH")
    parser.add_argument(
        "--crash-delta-passed",
        action="store_true",
        help="assert that the caller completed its pre/post crash-delta gate",
    )
    args = parser.parse_args()

    if args.evidence_manifest and args.evidence_manifest.exists():
        args.evidence_manifest.unlink()
    if args.evidence_manifest and not args.crash_delta_passed:
        parser.error("--evidence-manifest requires --crash-delta-passed")

    try:
        modes = parse_list(args.modes, DEFAULT_MODES, "mode")
        lengths = parse_list(args.lengths, DEFAULT_LENGTHS, "length")
    except ValueError as error:
        parser.error(str(error))
    if args.warm < 1:
        parser.error("--warm must be at least 1")

    expected_cells = expected_ordered_cells(modes, lengths, args.warm)
    expected_count = len(expected_cells)
    try:
        generation_map = json.loads(args.generation_map.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        parser.error(f"invalid --generation-map: {error}")
    mapped_takes = generation_map.get("takes") if isinstance(generation_map, dict) else None
    if (
        not isinstance(generation_map, dict)
        or generation_map.get("schemaVersion") != 1
        or generation_map.get("runID") != args.run_id
        or not isinstance(mapped_takes, list)
    ):
        parser.error("--generation-map identity or schema does not match this run")
    mapped_ids: list[str] = []
    map_failures: list[str] = []
    for index, expected_cell in enumerate(expected_cells, start=1):
        entry = mapped_takes[index - 1] if index <= len(mapped_takes) else None
        if not isinstance(entry, dict):
            map_failures.append(f"generation map is missing take {index}")
            continue
        if entry.get("takeIndex") != index or entry.get("cell") != cell_name(expected_cell):
            map_failures.append(
                f"generation map take {index} is {entry.get('cell')!r}; expected {cell_name(expected_cell)!r}"
            )
        generation_id = entry.get("generationID")
        if not isinstance(generation_id, str) or not generation_id:
            map_failures.append(f"generation map take {index} has no generationID")
        else:
            mapped_ids.append(generation_id)
    if len(mapped_takes) != expected_count:
        map_failures.append(f"generation map rows {len(mapped_takes)} != expected {expected_count}")
    if len({value.lower() for value in mapped_ids}) != len(mapped_ids):
        map_failures.append("generation map IDs are not unique")

    engine_path = args.diagnostics / "engine" / "generations.jsonl"
    app_path = args.diagnostics / "app" / "generations.jsonl"
    all_engine_rows, failures = read_jsonl_strict(engine_path)
    all_app_rows, app_read_failures = read_jsonl_strict(app_path)
    failures.extend(app_read_failures)
    failures.extend(map_failures)
    selected_engine_rows = filter_run(all_engine_rows, args.run_id)
    app_rows = filter_run(all_app_rows, args.run_id)
    engine_by_id = {
        str(row.get("generationID")).lower(): row
        for row in selected_engine_rows if row.get("generationID")
    }
    engine_rows: list[dict] = []
    for generation_id in mapped_ids:
        if (row := engine_by_id.get(generation_id.lower())) is None:
            failures.append(f"generation map ID {generation_id} has no engine row")
        else:
            engine_rows.append(row)
    unexpected_engine_ids = sorted(set(engine_by_id) - {value.lower() for value in mapped_ids})
    if unexpected_engine_ids:
        failures.append(f"run has engine rows absent from the generation map: {unexpected_engine_ids}")

    generation_ids = [row.get("generationID") for row in engine_rows]
    if len(engine_rows) != expected_count:
        failures.append(f"engine rows {len(engine_rows)} != expected {expected_count}")
    if any(not isinstance(value, str) or not value for value in generation_ids):
        failures.append("one or more engine rows has no generationID")
    if len(set(generation_ids)) != len(generation_ids):
        failures.append("engine generationIDs are not unique")

    actual_cells: list[tuple[str, str, str, int]] = []
    for index, row in enumerate(engine_rows):
        notes = row.get("notes") or {}
        mapped_cell = expected_cells[index] if index < expected_count else ("?", "?", "?", 0)
        inferred = (row.get("mode") or "?", row.get("warmState") or "?")
        actual_cells.append(mapped_cell)
        if index < expected_count:
            expected_cell = expected_cells[index]
            if inferred != (expected_cell[0], expected_cell[2]):
                failures.append(
                    f"take {index + 1} telemetry identity mismatch: actual={inferred} "
                    f"expected={(expected_cell[0], expected_cell[2])}"
                )
            explicit_cell = notes.get("benchCell")
            if explicit_cell is not None and explicit_cell != cell_name(expected_cell):
                failures.append(
                    f"take {index + 1} benchCell={explicit_cell!r} "
                    f"!= expected {cell_name(expected_cell)!r}"
                )
            explicit_index = notes.get("benchTakeIndex")
            if explicit_index is not None:
                try:
                    parsed_index = int(explicit_index)
                except (TypeError, ValueError):
                    parsed_index = -1
                if parsed_index != index + 1:
                    failures.append(
                        f"take {index + 1} benchTakeIndex={explicit_index!r} is invalid"
                    )
        if failure := output_failure(row):
            failures.append(f"{row.get('generationID', '?')}: {failure}")
        identity = row.get("modelRuntimeIdentity") or {}
        if row.get("schemaVersion", 0) >= 7:
            failures.extend(validate_v7_engine_telemetry(row))
            if not isinstance(row.get("backendMetrics"), dict):
                failures.append(f"{row.get('generationID', '?')}: missing typed backend metrics")
            if identity.get("resolvedModelID") != row.get("modelID"):
                failures.append(f"{row.get('generationID', '?')}: mismatched typed model identity")
            if exact_model_variant(identity, row) is None:
                failures.append(f"{row.get('generationID', '?')}: missing exact model variant")
            if not isinstance(identity.get("runtimeProfileSignature"), str) or not identity["runtimeProfileSignature"]:
                failures.append(f"{row.get('generationID', '?')}: missing typed runtime profile signature")
            if not isinstance(identity.get("modelRepository"), str) or "/" not in identity["modelRepository"]:
                failures.append(f"{row.get('generationID', '?')}: missing typed model repository")
            revision = identity.get("huggingFaceRevision")
            if not isinstance(revision, str) or len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision):
                failures.append(f"{row.get('generationID', '?')}: missing pinned model revision")
            if not isinstance(identity.get("artifactVersion"), str) or not identity["artifactVersion"]:
                failures.append(f"{row.get('generationID', '?')}: missing model artifact version")
            if identity.get("quantization") not in {"4-bit", "8-bit", "unquantized"}:
                failures.append(f"{row.get('generationID', '?')}: invalid model quantization")
            if not is_digest(identity.get("integrityManifestDigest")):
                failures.append(f"{row.get('generationID', '?')}: missing model integrity-manifest digest")
            if not is_digest(notes.get("promptDigest")):
                failures.append(f"{row.get('generationID', '?')}: missing privacy-safe prompt digest")
            if row.get("mode") in {"design", "clone"} and not is_digest(identity.get("fixtureDigest")):
                failures.append(f"{row.get('generationID', '?')}: missing exact fixture digest")
        if row.get("schemaVersion", 0) < REQUIRED_TELEMETRY_SCHEMA:
            failures.append(
                f"{row.get('generationID', '?')}: benchmark publication requires telemetry "
                f"schema v{REQUIRED_TELEMETRY_SCHEMA} or newer"
            )

    valid_ids = [value for value in generation_ids if isinstance(value, str) and value]
    failures.extend(validate_layer("app", app_rows, valid_ids, expected_count))
    for row in app_rows:
        if row.get("schemaVersion", 0) < 7:
            continue
        failures.extend(validate_v7_frontend(row))

    if not failures:
        try:
            qualify_memory_rows(
                rows=engine_rows,
                diagnostics=args.diagnostics,
                platform="ios",
            )
        except MemoryEvidenceError as error:
            failures.append(str(error))

    print(
        f"iOS XCUITest benchmark: runID={args.run_id} rows={len(engine_rows)} "
        f"app={len(app_rows)} expected={expected_count}"
    )
    for cell, count in sorted(Counter(actual_cells).items()):
        print(f"  {'/'.join(map(str, cell)):<32} n={count}")
    if failures:
        print("FAIL:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    if args.evidence_manifest:
        manifest = build_manifest(
            args.diagnostics,
            args.run_id,
            args.label,
            modes,
            lengths,
            args.warm,
            expected_cells,
            engine_rows,
            app_rows,
        )
        write_json_atomic(args.evidence_manifest, manifest)
        print(f"evidence={args.evidence_manifest}")
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
