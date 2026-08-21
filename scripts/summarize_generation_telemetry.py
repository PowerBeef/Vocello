#!/usr/bin/env python3
"""Summarize per-generation telemetry into a mode × model × cold/warm table.

Analysis of the JSONL the runtime telemetry already writes. It joins
the per-layer rows by `generationID` and prints a comparison table; for the warm
runs in a cell it reports the median, for cold the single value (median if several).

Use `--run-id` for strict selection from an accumulated diagnostics directory, or
`--evidence-manifest` to consume the exact ordered generation IDs and cells emitted
by a benchmark validator. Unscoped invocation remains available for historical
interactive analysis.

Usage:
    python3 scripts/summarize_generation_telemetry.py [DIAGNOSTICS_DIR] [--label RUN_ID]

`--label` stamps an opaque privacy-safe identifier; the report is auto-stamped with the current date
and short Git SHA. Repo-tracked history is owned by `benchmark_history.py` and its
validated evidence manifests, never by redirecting this human-readable table.

Default DIAGNOSTICS_DIR:
    ~/Library/Application Support/QwenVoice-Debug/diagnostics

See docs/reference/telemetry-and-benchmarking.md for the benchmark procedure.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import statistics
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_DIR = os.path.expanduser(
    "~/Library/Application Support/QwenVoice-Debug/diagnostics"
)

# Engine rows with these finishReason values are omitted from benchmark medians
# (failed/superseded/cancelled runs would skew RTF and memory aggregates).
_BENCHMARK_SUCCESS_FINISH_REASONS = frozenset({
    "eos",
    "max_tokens",
    "maxTokens",
    "completed",
})


def opaque_label(value: str) -> str:
    if value == "":
        return value
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", value):
        raise argparse.ArgumentTypeError(
            "must be an opaque 1-96 character ID using letters, digits, dot, underscore, or hyphen"
        )
    return value


def _engine_row_counts_for_benchmark(row):
    """True when an engine JSONL row should contribute to benchmark aggregates."""
    finish = row.get("finishReason")
    if finish is None:
        return True  # legacy rows without finishReason
    return finish in _BENCHMARK_SUCCESS_FINISH_REASONS


def git_short_sha():
    """Short HEAD SHA of the repo in CWD, or '-' when unavailable."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        sha = out.stdout.strip()
        return sha if out.returncode == 0 and sha else "-"
    except Exception:
        return "-"


def today_str():
    return datetime.date.today().isoformat()


class TelemetrySelectionError(ValueError):
    """Raised when scoped benchmark evidence is malformed or incomplete."""


def iter_jsonl(path, *, strict=False):
    """Lazy stream of decoded JSON objects from a JSONL file."""
    if not os.path.exists(path):
        if strict:
            raise TelemetrySelectionError(f"missing telemetry file: {path}")
        return
    with open(path, "r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                if strict:
                    raise TelemetrySelectionError(
                        f"{path}:{line_number}: malformed JSON: {error.msg}"
                    ) from error
                continue
            if not isinstance(row, dict):
                if strict:
                    raise TelemetrySelectionError(
                        f"{path}:{line_number}: row is not a JSON object"
                    )
                continue
            yield row


def read_jsonl(path, *, strict=False):
    """Eager load of a JSONL file; kept for callers that need a list."""
    return list(iter_jsonl(path, strict=strict))


def load_evidence_selection(path, requested_run_id=""):
    """Validate a benchmark-evidence manifest and return its exact selection."""
    manifest_path = Path(path)
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise TelemetrySelectionError(f"missing evidence manifest: {manifest_path}") from error
    except json.JSONDecodeError as error:
        raise TelemetrySelectionError(
            f"{manifest_path}: malformed JSON: {error.msg}"
        ) from error
    if not isinstance(payload, dict):
        raise TelemetrySelectionError("evidence manifest root must be an object")
    if payload.get("schemaVersion") not in {1, 2}:
        raise TelemetrySelectionError(
            f"unsupported evidence schemaVersion={payload.get('schemaVersion')!r}"
        )
    benchmark_kind = payload.get("benchmarkKind")
    if benchmark_kind in {
        "engine-generation", "language", "instrument-profile", "memory-qualification",
    }:
        return _load_non_ui_evidence_selection(payload, requested_run_id=requested_run_id)
    if benchmark_kind != "ui-generation":
        raise TelemetrySelectionError(
            f"unsupported evidence benchmarkKind={benchmark_kind!r}"
        )
    if payload.get("status") not in {"pass", "passedWithWarnings"}:
        raise TelemetrySelectionError("evidence manifest does not describe a successful run")
    run_id = payload.get("runID")
    if not isinstance(run_id, str) or not run_id:
        raise TelemetrySelectionError("evidence manifest has no runID")
    if requested_run_id and requested_run_id != run_id:
        raise TelemetrySelectionError(
            f"--run-id {requested_run_id!r} does not match evidence runID {run_id!r}"
        )
    matrix = payload.get("matrix")
    takes = payload.get("takes")
    if not isinstance(matrix, dict) or not isinstance(takes, list) or not takes:
        raise TelemetrySelectionError("evidence manifest has no non-empty matrix/takes")
    expected_count = matrix.get("expectedTakeCount")
    ordered_cells = matrix.get("orderedCells")
    if expected_count != len(takes) or not isinstance(ordered_cells, list) or len(ordered_cells) != len(takes):
        raise TelemetrySelectionError("evidence matrix/take counts are inconsistent")
    layers = payload.get("layers")
    if not isinstance(layers, dict) or not layers:
        raise TelemetrySelectionError("evidence manifest has no layer completeness")
    for layer, detail in layers.items():
        if not isinstance(detail, dict) or detail.get("complete") is not True:
            raise TelemetrySelectionError(f"evidence layer {layer!r} is incomplete")

    generation_ids = []
    cell_by_id = {}
    for index, (take, ordered_cell) in enumerate(zip(takes, ordered_cells, strict=True), start=1):
        if not isinstance(take, dict):
            raise TelemetrySelectionError(f"evidence take {index} is not an object")
        if take.get("takeIndex") != index:
            raise TelemetrySelectionError(f"evidence takeIndex sequence is invalid at take {index}")
        generation_id = take.get("generationID")
        cell = take.get("cell")
        if not isinstance(generation_id, str) or not generation_id:
            raise TelemetrySelectionError(f"evidence take {index} has no generationID")
        if generation_id in cell_by_id:
            raise TelemetrySelectionError(f"duplicate evidence generationID: {generation_id}")
        if not isinstance(cell, str) or cell != ordered_cell or len(cell.split("/")) != 3:
            raise TelemetrySelectionError(f"evidence take {index} has an invalid ordered cell")
        if take.get("status") not in {"pass", "passedWithWarnings"}:
            raise TelemetrySelectionError(f"evidence take {index} is not successful")
        if take.get("finishReason") not in _BENCHMARK_SUCCESS_FINISH_REASONS:
            raise TelemetrySelectionError(f"evidence take {index} has an unsuccessful finishReason")
        if take.get("readableWAV") is not True or take.get("atomicPublish") is not True:
            raise TelemetrySelectionError(f"evidence take {index} has invalid output proof")
        audio_qc = take.get("audioQC")
        if not isinstance(audio_qc, dict) or audio_qc.get("verdict") not in {"pass", "warn"}:
            raise TelemetrySelectionError(f"evidence take {index} has invalid audioQC proof")
        completeness = take.get("layerCompleteness")
        if not isinstance(completeness, dict) or not completeness or not all(
            value is True for value in completeness.values()
        ):
            raise TelemetrySelectionError(f"evidence take {index} has incomplete layers")
        generation_ids.append(generation_id)
        cell_by_id[generation_id] = cell
    return payload, run_id, generation_ids, cell_by_id


def _load_non_ui_evidence_selection(payload, *, requested_run_id=""):
    """Select exact engine rows from a validated non-UI history manifest.

    Non-UI publishers freeze their ordered takes under ``historyRecord`` rather
    than the UI validator's top-level matrix. Keep the UI contract strict while
    accepting the three generation-backed headless kinds that invoke this
    summarizer after their own validator has passed.
    """
    if payload.get("status") not in {"passed", "passedWithWarnings"}:
        raise TelemetrySelectionError(
            "non-UI evidence manifest does not describe a successful run"
        )
    run_id = payload.get("runID")
    if not isinstance(run_id, str) or not run_id:
        raise TelemetrySelectionError("non-UI evidence manifest has no runID")
    if requested_run_id and requested_run_id != run_id:
        raise TelemetrySelectionError(
            f"--run-id {requested_run_id!r} does not match evidence runID {run_id!r}"
        )

    history_record = payload.get("historyRecord")
    if not isinstance(history_record, dict):
        raise TelemetrySelectionError("non-UI evidence manifest has no historyRecord")
    if history_record.get("schemaVersion") not in {1, 2, 3}:
        raise TelemetrySelectionError(
            "non-UI evidence historyRecord has an unsupported schemaVersion"
        )
    platform = payload.get("platform")
    if not isinstance(platform, str) or not platform:
        raise TelemetrySelectionError("non-UI evidence manifest has no platform")
    history_run = history_record.get("run")
    if (
        not isinstance(history_run, dict)
        or history_run.get("id") != run_id
        or history_run.get("kind") != payload.get("benchmarkKind")
        or history_run.get("platform") != platform
        or history_run.get("status") != payload.get("status")
    ):
        raise TelemetrySelectionError("non-UI evidence run identity is inconsistent")
    takes = history_record.get("takes")
    expected_count = payload.get("expectedTakeCount")
    actual_count = payload.get("actualTakeCount")
    if (
        not isinstance(takes, list)
        or not takes
        or expected_count != len(takes)
        or actual_count != len(takes)
    ):
        raise TelemetrySelectionError("non-UI evidence take counts are inconsistent")

    generation_ids = []
    cell_by_id = {}
    for index, take in enumerate(takes, start=1):
        if not isinstance(take, dict) or take.get("takeIndex") != index:
            raise TelemetrySelectionError(
                f"non-UI evidence takeIndex sequence is invalid at take {index}"
            )
        generation_id = take.get("generationID")
        cell = take.get("cell")
        if not isinstance(generation_id, str) or not generation_id:
            raise TelemetrySelectionError(
                f"non-UI evidence take {index} has no generationID"
            )
        if generation_id in cell_by_id:
            raise TelemetrySelectionError(
                f"duplicate evidence generationID: {generation_id}"
            )
        if not isinstance(cell, str) or not cell:
            raise TelemetrySelectionError(f"non-UI evidence take {index} has no cell")
        if take.get("status") not in {"passed", "passedWithWarnings"}:
            raise TelemetrySelectionError(
                f"non-UI evidence take {index} is not successful"
            )
        if take.get("finishReason") not in _BENCHMARK_SUCCESS_FINISH_REASONS:
            raise TelemetrySelectionError(
                f"non-UI evidence take {index} has an unsuccessful finishReason"
            )
        output = take.get("output")
        if (
            not isinstance(output, dict)
            or output.get("readableWAV") is not True
            or output.get("atomicPublish") is not True
        ):
            raise TelemetrySelectionError(
                f"non-UI evidence take {index} has invalid output proof"
            )
        audio_qc = take.get("audioQC")
        if not isinstance(audio_qc, dict) or audio_qc.get("verdict") not in {"pass", "warn"}:
            raise TelemetrySelectionError(
                f"non-UI evidence take {index} has invalid audioQC proof"
            )
        layers = take.get("layers")
        if take.get("layerCompleteness") != "complete" or not isinstance(layers, list) or "engine" not in layers:
            raise TelemetrySelectionError(
                f"non-UI evidence take {index} has incomplete engine telemetry"
            )
        generation_ids.append(generation_id)
        cell_by_id[generation_id] = cell
    return payload, run_id, generation_ids, cell_by_id


def _select_rows(rows, *, run_id="", generation_ids=None, layer="telemetry"):
    """Select and deterministically order one run's rows."""
    selected = list(rows)
    if run_id:
        selected = [
            row for row in selected
            if (row.get("notes") or {}).get("benchRunID") == run_id
        ]
    ids = [row.get("generationID") for row in selected]
    if any(not isinstance(value, str) or not value for value in ids):
        raise TelemetrySelectionError(f"one or more selected {layer} rows has no generationID")
    if len(set(ids)) != len(ids):
        raise TelemetrySelectionError(f"selected {layer} generationIDs are not unique")
    if generation_ids is None:
        return selected
    expected = list(generation_ids)
    by_id = {row["generationID"]: row for row in selected}
    missing = [generation_id for generation_id in expected if generation_id not in by_id]
    unexpected = sorted(set(by_id) - set(expected))
    if missing or unexpected:
        raise TelemetrySelectionError(
            f"{layer} selection mismatch: missing={missing} unexpected={unexpected}"
        )
    return [by_id[generation_id] for generation_id in expected]


# Prompt-length buckets for the benchmark length sweep. Thresholds tied to the
# fixed corpora (short ~35, medium ~100, long >=150 chars); see
# docs/reference/telemetry-and-benchmarking.md. Rows with no promptChars
# (pre-length-capture runs) bucket as "n/a".
LEN_ORDER = {"short": 0, "medium": 1, "long": 2, "n/a": 3}


def len_bucket(prompt_chars):
    if not prompt_chars:
        return "n/a"
    if prompt_chars < 70:
        return "short"
    if prompt_chars >= 140:
        return "long"
    return "medium"


def load_prosody(diag_dir):
    """Load bench-prosody.json sidecar, if present. Returns list of rows."""
    path = os.path.join(diag_dir, "bench-prosody.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return []


def prosody_for_delivery(prosody_rows, mode, model_id, delivery):
    """Median prosody effect and supporting deltas for a delivery cell."""
    rows = [
        r for r in prosody_rows
        if r["mode"] == mode and r["model"] == model_id and r["delivery"] == delivery
    ]
    if not rows:
        return None
    return {
        "effect": med(r["prosodyEffect"] for r in rows),
        "dF0Std": med(r["dF0Std"] for r in rows),
        "dRateCV": med(r["dRateCV"] for r in rows),
        "dPauseRatio": med(r["dPauseRatio"] for r in rows),
        "dRoughness": med(r["dRoughness"] for r in rows),
        "n": len(rows),
    }


def first_stage_mark_ms(record, stage):
    for mark in record.get("stageMarks", []):
        if mark.get("stage") == stage:
            return mark.get("tMS")
    return None


def load_merged_runs(diag_dir, *, run_id="", generation_ids=None, strict=False):
    """Load generations-merged.jsonl and join per-layer first-chunk marks."""
    path = os.path.join(diag_dir, "generations-merged.jsonl")
    rows = read_jsonl(path, strict=strict)
    if generation_ids is not None:
        expected_set = set(generation_ids)
        rows = [row for row in rows if row.get("generationID") in expected_set]
        rows = _select_rows(
            rows,
            generation_ids=generation_ids,
            layer="merged",
        )
    elif run_id:
        # Merged rows do not carry notes.benchRunID. Resolve the run through the
        # exact engine IDs selected by that stamp.
        engine_rows = _select_rows(
            iter_jsonl(
                os.path.join(diag_dir, "engine", "generations.jsonl"),
                strict=strict,
            ),
            run_id=run_id,
            layer="engine",
        )
        engine_ids = [row["generationID"] for row in engine_rows]
        engine_id_set = set(engine_ids)
        rows = [row for row in rows if row.get("generationID") in engine_id_set]
        rows = _select_rows(rows, generation_ids=engine_ids, layer="merged")
    runs = []
    for row in rows:
        app = row.get("app") or {}
        engine = row.get("engine") or {}
        engine_service = row.get("engineService") or {}
        app_frontend = app.get("frontendMetrics") or {}
        run = {
            "generationID": row.get("generationID"),
            "appTTFCMS": app_frontend.get("submitToFirstChunkMS")
                if app_frontend.get("submitToFirstChunkMS") is not None
                else (app.get("timingsMS") or {}).get("submitToFirstChunkMS"),
            "engineFirstChunkMS": first_stage_mark_ms(engine, "firstChunk"),
            "engineServiceFirstChunkMS": first_stage_mark_ms(engine_service, "firstChunk"),
        }
        if run["appTTFCMS"] is not None and run["engineFirstChunkMS"] is not None:
            run["frontendOverheadMS"] = run["appTTFCMS"] - run["engineFirstChunkMS"]
        runs.append(run)
    return runs


def _app_index(diag_dir, *, run_id="", generation_ids=None, strict=False):
    """Stream app/generations.jsonl and keep only the fields needed for joining."""
    index = {}
    path = os.path.join(diag_dir, "app", "generations.jsonl")
    rows = _select_rows(
        iter_jsonl(path, strict=strict),
        run_id=run_id,
        generation_ids=generation_ids,
        layer="app",
    ) if (run_id or generation_ids is not None) else iter_jsonl(path, strict=strict)
    for a in rows:
        gid = a.get("generationID")
        if gid is None:
            continue
        index[gid] = {
            "timingsMS": a.get("timingsMS") or {},
            "counters": a.get("counters") or {},
            "frontendMetrics": a.get("frontendMetrics") or {},
        }
    return index


def _engine_run(e, app_lookup, *, cell_override=None):
    """Build one per-run dict from an engine row + joined app row."""
    derived = e.get("derivedMetrics") or {}
    timings = e.get("timingsMS") or {}
    summary = e.get("summary") or {}
    a = app_lookup.get(e.get("generationID")) or {}
    app_timings = a.get("timingsMS") or {}
    app_counters = a.get("counters") or {}
    frontend = a.get("frontendMetrics") or {}
    backend_timings = {
        item.get("key"): item.get("milliseconds")
        for item in (e.get("backendMetrics") or {}).get("timings") or []
        if isinstance(item, dict)
    }
    qc = e.get("audioQC") or {}
    trim_count, pressure_count, worst = count_memory_events(e, summary)
    notes = e.get("notes") or {}
    bucket = len_bucket(int(notes.get("promptChars") or 0))
    if cell_override:
        parts = cell_override.split("/")
        if len(parts) == 3:
            bucket = parts[1]
    run = {
        "generationID": e.get("generationID"),
        "mode": e.get("mode") or "?",
        "modelID": e.get("modelID") or "?",
        "warmState": e.get("warmState") or "?",
        "finishReason": e.get("finishReason"),
        "rtf": derived.get("audioSecondsPerWallSecond"),
        "tokps": derived.get("tokensPerSecond"),
        "audioSec": derived.get("audioSeconds"),
        "ttfcMS": frontend.get("submitToFirstChunkMS")
            if frontend.get("submitToFirstChunkMS") is not None
            else app_timings.get("submitToFirstChunkMS"),
        # UI-responsiveness KPI (app row, sampled heartbeat watchdog). These
        # are delayed observed heartbeats, not an exhaustive main-thread stall count.
        "uiDelayedHeartbeat50": frontend.get(
            "delayedHeartbeatCount50",
            app_counters.get("delayedHeartbeatCount50", app_counters.get("uiStallCount50")),
        ),
        "uiDelayedHeartbeat250": frontend.get(
            "delayedHeartbeatCount250",
            app_counters.get("delayedHeartbeatCount250", app_counters.get("uiStallCount250")),
        ),
        "uiMaxDelayedHeartbeatMS": frontend.get("maximumDelayedHeartbeatMS")
            if frontend.get("maximumDelayedHeartbeatMS") is not None
            else app_counters.get("maximumDelayedHeartbeatMS", app_counters.get("uiMaxStallMS")),
        "uiHeartbeatCoverage": (
            frontend.get("heartbeatCoveragePPM") / 1_000_000
            if isinstance(frontend.get("heartbeatCoveragePPM"), (int, float))
            else app_counters.get("heartbeatCoveragePPM") / 1_000_000
            if isinstance(app_counters.get("heartbeatCoveragePPM"), (int, float))
            else None
        ),
        "decodeLoopMS": backend_timings.get("tokenLoop")
            if backend_timings.get("tokenLoop") is not None
            else timings.get("qwen_token_loop_total"),
        "peakGpuMB": summary.get("gpuAllocatedPeakMB"),
        "peakRssMB": summary.get("residentPeakMB"),
        # phys_footprint is the figure Jetsam judges on Apple Silicon — the
        # most OOM-relevant peak. headroomMin = closest the process came to
        # exhausting its available memory budget during the run.
        "physFootMB": summary.get("physFootprintPeakMB"),
        "headMinMB": summary.get("headroomMinMB"),
        "gpuWsRatioPeak": summary.get("gpuWorkingSetUsageRatioPeak"),
        "thermalWorst": (e.get("thermalState") or {}).get("worst"),
        "compressedMB": summary.get("compressedPeakMB"),
        # Kernel memory-pressure activity during the run (stage marks).
        "trims": trim_count,
        "pressure": pressure_count,
        "worstTrim": worst,
        # Resolved device tier this row ran under (notes.deviceClass) —
        # reveals a forced-tier benchmark and the floor Quality→Speed fallback.
        "deviceClass": notes.get("deviceClass") or "?",
        # Whether the tier was forced via QWENVOICE_FORCE_MEMORY_CLASS (vs the
        # native tier) — so a real 8 GB Mac isn't mislabeled "forced".
        "deviceClassForced": notes.get("deviceClassForced") == "true",
        # Input script length (notes.promptChars) → bucket for the
        # short/medium/long sweep. RTF/decode/KV-cache all scale with it.
        "promptChars": int(notes.get("promptChars") or 0),
        "lenBucket": bucket,
        "benchRunID": notes.get("benchRunID"),
        "benchCell": cell_override or notes.get("benchCell"),
        # Bench delivery-cell id (notes.delivery, preset id)
        # for instruct-bearing takes from `vocello bench --delivery`.
        # Empty for plain matrix takes; delivery rows are segregated into
        # their own block so the headline cells stay comparable.
        "delivery": notes.get("delivery") or "",
        # GPU peak MB at pipeline boundaries (mlxMemoryByStage) — shows WHERE
        # GPU memory grows and how much a trim reclaims.
        "gpuByStage": gpu_peak_by_stage(e.get("mlxMemoryByStage") or {}),
        # Per-stage decode ms (timingsMS) — shows WHERE the decode loop spends
        # wall time (Talker / Code Predictor / Code2Wav / eval). Sums ≈ decode ms.
        "decodeStages": decode_stage_breakdown(timings),
        # Streaming chunk timeline — per-cell medians of first-chunk arrival,
        # inter-chunk interval, and the per-chunk substage latencies.
        "chunkCount": None,
        "firstChunkArrivalMS": None,
        "medianInterChunkMS": None,
        **{f"chunk_{key}": None for key in _CHUNK_SUBSTAGE_KEYS},
        **{f"mimi_{key}": None for key in _MIMI_DECODER_KEYS},
        # Reference-free audio-quality verdict (engine).
        "qcVerdict": qc.get("verdict"),
        "qcFlags": qc.get("flags") or [],
    }
    chunks = e.get("chunkTimeline") or []
    if chunks:
        run["chunkCount"] = len(chunks)
        run["firstChunkArrivalMS"] = chunks[0]["arrivalMS"]
        run["medianInterChunkMS"] = med(
            chunks[i]["arrivalMS"] - chunks[i - 1]["arrivalMS"]
            for i in range(1, len(chunks))
        )
        for key in _CHUNK_SUBSTAGE_KEYS:
            run[f"chunk_{key}"] = med(c[key] for c in chunks if key in c)
        for key in _MIMI_DECODER_KEYS:
            values = [
                c.get("mimiDecoderBreakdownMS", {}).get(key)
                for c in chunks
                if c.get("mimiDecoderBreakdownMS")
            ]
            run[f"mimi_{key}"] = med(values) if values else None
    return run


def load_runs(
    diag_dir,
    *,
    run_id="",
    generation_ids=None,
    cell_by_id=None,
    strict=False,
    engine_only=False,
):
    """Join engine + app rows by generationID. Returns list of per-run dicts."""
    app_lookup = {} if engine_only else _app_index(
        diag_dir,
        run_id=run_id,
        generation_ids=generation_ids,
        strict=strict,
    )
    path = os.path.join(diag_dir, "engine", "generations.jsonl")
    rows = _select_rows(
        iter_jsonl(path, strict=strict),
        run_id=run_id,
        generation_ids=generation_ids,
        layer="engine",
    ) if (run_id or generation_ids is not None) else iter_jsonl(path, strict=strict)
    return [
        _engine_run(
            e,
            app_lookup,
            cell_override=(cell_by_id or {}).get(e.get("generationID")),
        )
        for e in rows
        if _engine_row_counts_for_benchmark(e)
    ]


@dataclass
class CellAccumulator:
    """Streaming accumulator for one benchmark cell's aggregate metrics."""

    key: tuple
    rtfs: list = field(default_factory=list)
    tokpss: list = field(default_factory=list)
    ttfcs: list = field(default_factory=list)
    decode_loop_ms: list = field(default_factory=list)
    peak_gpu_mb: list = field(default_factory=list)
    phys_foot_mb: list = field(default_factory=list)
    head_min_mb: list = field(default_factory=list)
    gpu_ws_ratio_peaks: list = field(default_factory=list)
    thermal_worsts: list = field(default_factory=list)
    trims: list = field(default_factory=list)
    worst_trims: list = field(default_factory=list)
    ui_stalls: list = field(default_factory=list)
    ui_max_stalls: list = field(default_factory=list)
    ui_heartbeat_coverage: list = field(default_factory=list)
    qc_verdicts: list = field(default_factory=list)
    qc_flags: set = field(default_factory=set)
    chunk_counts: list = field(default_factory=list)
    first_chunk_arrivals: list = field(default_factory=list)
    median_inter_chunks: list = field(default_factory=list)
    chunk_substage_values: dict = field(default_factory=lambda: defaultdict(list))
    mimi_decoder_values: dict = field(default_factory=lambda: defaultdict(list))
    gpu_by_stage: dict = field(default_factory=lambda: defaultdict(list))
    decode_stages: dict = field(default_factory=lambda: defaultdict(list))

    def add_run(self, run: dict) -> None:
        """Ingest one run into the accumulator's lists."""
        if run.get("rtf") is not None:
            self.rtfs.append(run["rtf"])
        if run.get("tokps") is not None:
            self.tokpss.append(run["tokps"])
        if run.get("ttfcMS") is not None:
            self.ttfcs.append(run["ttfcMS"])
        if run.get("decodeLoopMS") is not None:
            self.decode_loop_ms.append(run["decodeLoopMS"])
        if run.get("peakGpuMB") is not None:
            self.peak_gpu_mb.append(run["peakGpuMB"])
        if run.get("physFootMB") is not None:
            self.phys_foot_mb.append(run["physFootMB"])
        if run.get("headMinMB") is not None:
            self.head_min_mb.append(run["headMinMB"])
        if run.get("gpuWsRatioPeak") is not None:
            self.gpu_ws_ratio_peaks.append(run["gpuWsRatioPeak"])
        if run.get("thermalWorst") is not None:
            self.thermal_worsts.append(run["thermalWorst"])
        if run.get("trims") is not None:
            self.trims.append(run["trims"])
        if run.get("worstTrim") is not None:
            self.worst_trims.append(run["worstTrim"])
        if run.get("uiDelayedHeartbeat50") is not None:
            self.ui_stalls.append(run["uiDelayedHeartbeat50"])
        if run.get("uiMaxDelayedHeartbeatMS") is not None:
            self.ui_max_stalls.append(run["uiMaxDelayedHeartbeatMS"])
        if run.get("uiHeartbeatCoverage") is not None:
            self.ui_heartbeat_coverage.append(run["uiHeartbeatCoverage"])
        if run.get("qcVerdict") is not None:
            self.qc_verdicts.append(run["qcVerdict"])
        for f in run.get("qcFlags") or []:
            self.qc_flags.add(f.split(":")[0])
        if run.get("chunkCount") is not None:
            self.chunk_counts.append(run["chunkCount"])
        if run.get("firstChunkArrivalMS") is not None:
            self.first_chunk_arrivals.append(run["firstChunkArrivalMS"])
        if run.get("medianInterChunkMS") is not None:
            self.median_inter_chunks.append(run["medianInterChunkMS"])
        for key in _CHUNK_SUBSTAGE_KEYS:
            v = run.get(f"chunk_{key}")
            if v is not None:
                self.chunk_substage_values[key].append(v)
        for key in _MIMI_DECODER_KEYS:
            v = run.get(f"mimi_{key}")
            if v is not None:
                self.mimi_decoder_values[key].append(v)
        for label, values in (run.get("gpuByStage") or {}).items():
            if values is not None:
                self.gpu_by_stage[label].append(values)
        for label, value in (run.get("decodeStages") or {}).items():
            if value is not None:
                self.decode_stages[label].append(value)

    def finalize(self) -> dict:
        """Return a JSON-serializable summary dict for this cell."""
        mode, model_id, state, bucket = self.key
        # Worst QC verdict across the cell.
        worst_qc, qc_rank = None, -1
        for v in self.qc_verdicts:
            rank = _QC_SEVERITY.get(v, 0)
            if rank > qc_rank:
                qc_rank, worst_qc = rank, v
        if worst_qc is None:
            qc = "-"
        elif worst_qc == "pass":
            qc = "pass"
        else:
            flags = sorted(self.qc_flags)
            qc = f"{worst_qc}:{','.join(flags[:2])}" if flags else worst_qc

        # Worst trim level across the cell.
        worst_trim, worst_rank = None, 0
        for level in self.worst_trims:
            rank = _TRIM_SEVERITY.get(level, 0)
            if rank > worst_rank:
                worst_rank, worst_trim = rank, level

        return {
            "key": self.key,
            "mode": mode,
            "modelID": model_id,
            "warmState": state,
            "lenBucket": bucket,
            "delivery": None,
            "n": len(self.rtfs) or len(self.tokpss) or len(self.ttfcs),
            "rtf": med(self.rtfs),
            "tokps": med(self.tokpss),
            "ttfcMS": med(self.ttfcs),
            "decodeLoopMS": med(self.decode_loop_ms),
            "peakGpuMB": med(self.peak_gpu_mb),
            "physFootMB": med(self.phys_foot_mb),
            "headMinMB": med(self.head_min_mb),
            "gpuWsRatioPeak": med(self.gpu_ws_ratio_peaks),
            "thermalWorst": _worst_thermal(self.thermal_worsts),
            "rtfIQR": iqr(self.rtfs),
            "physFootIQR": iqr(self.phys_foot_mb),
            "trims": med(self.trims),
            "worstTrim": worst_trim,
            "uiDelayedHeartbeat50": med(self.ui_stalls),
            "uiMaxDelayedHeartbeatMS": med(self.ui_max_stalls),
            "uiHeartbeatCoverage": med(self.ui_heartbeat_coverage),
            "qcVerdict": qc,
            "qcFlags": sorted(self.qc_flags),
            "chunkCount": med(self.chunk_counts),
            "firstChunkArrivalMS": med(self.first_chunk_arrivals),
            "medianInterChunkMS": med(self.median_inter_chunks),
            "chunkSubstageMS": {
                key: med(values) for key, values in self.chunk_substage_values.items()
            },
            "mimiDecoderBreakdownMS": {
                key: med(values) for key, values in self.mimi_decoder_values.items()
            },
            "gpuByStage": {
                label: med(values) for label, values in self.gpu_by_stage.items()
            },
            "decodeStages": {
                label: med(values) for label, values in self.decode_stages.items()
            },
        }


def aggregate_runs(
    diag_dir,
    *,
    run_id="",
    generation_ids=None,
    cell_by_id=None,
    strict=False,
    engine_only=False,
):
    """Stream engine + app rows and aggregate them into finalized cell summaries.

    Returns (runs, cells, delivery_cells, skipped_failed) where `runs` is the
    materialized list of per-run dicts, and the cell dicts are keyed by
    (mode, modelID, warmState, bucket) with delivery cells keyed by
    (mode, modelID, warmState, delivery). Rows with finishReason
    failed/superseded/cancelled are omitted from aggregates.
    """
    app_lookup = {} if engine_only else _app_index(
        diag_dir,
        run_id=run_id,
        generation_ids=generation_ids,
        strict=strict,
    )
    accumulators = {}
    delivery_accumulators = {}
    runs = []
    skipped_failed = 0
    path = os.path.join(diag_dir, "engine", "generations.jsonl")
    engine_rows = _select_rows(
        iter_jsonl(path, strict=strict),
        run_id=run_id,
        generation_ids=generation_ids,
        layer="engine",
    ) if (run_id or generation_ids is not None) else iter_jsonl(path, strict=strict)
    for e in engine_rows:
        if not _engine_row_counts_for_benchmark(e):
            skipped_failed += 1
            continue
        run = _engine_run(
            e,
            app_lookup,
            cell_override=(cell_by_id or {}).get(e.get("generationID")),
        )
        runs.append(run)
        if run.get("delivery"):
            key = (run["mode"], run["modelID"], run["warmState"], run["delivery"])
            acc = delivery_accumulators.setdefault(key, CellAccumulator(key=key))
        else:
            key = (run["mode"], run["modelID"], run["warmState"], run["lenBucket"])
            acc = accumulators.setdefault(key, CellAccumulator(key=key))
        acc.add_run(run)
    cells = {k: v.finalize() for k, v in accumulators.items()}
    delivery_cells = {}
    for key, acc in delivery_accumulators.items():
        summary = acc.finalize()
        summary["lenBucket"] = None
        summary["delivery"] = key[3]
        delivery_cells[key] = summary
    return runs, cells, delivery_cells, skipped_failed


# Worst-first ranking of QC verdicts for cell aggregation.
_QC_SEVERITY = {"pass": 0, "warn": 1, "fail": 2}

_THERMAL_SEVERITY = {
    "nominal": 0,
    "fair": 1,
    "serious": 2,
    "critical": 3,
}


def _worst_thermal(states):
    """Return the worst thermal state label seen in a cell."""
    if not states:
        return None
    worst, rank = None, -1
    for state in states:
        if state is None:
            continue
        r = _THERMAL_SEVERITY.get(state, 0)
        if r > rank:
            rank, worst = r, state
    return worst


def cell_qc(group):
    """Worst verdict across a cell + the distinct flags that tripped (compact).

    Accepts either a list of run dicts (legacy) or a finalized cell summary dict."""
    if isinstance(group, dict):
        return group.get("qcVerdict") or "-"
    worst, rank = None, -1
    flags = []
    for r in group:
        v = r.get("qcVerdict")
        if v is None:
            continue
        if _QC_SEVERITY.get(v, 0) > rank:
            rank, worst = _QC_SEVERITY.get(v, 0), v
        for f in r.get("qcFlags") or []:
            tag = f.split(":")[0]
            if tag not in flags:
                flags.append(tag)
    if worst is None:
        return "-"
    if worst == "pass":
        return "pass"
    return f"{worst}:{','.join(flags[:2])}" if flags else worst


# Boundary stages we surface for GPU growth, in pipeline order. Each cell takes the
# first stage present (streaming and quality-first paths name them differently).
_GPU_STAGE_GROUPS = [
    ("load", ["after_load", "after_clone_conditioning", "after_prewarm"]),
    ("stream", ["before_stream", "first_chunk", "before_quality_generation"]),
    ("peak", ["after_final_write", "after_stream"]),
    ("trim", ["after_generation_trim"]),
]


def gpu_peak_by_stage(mlx_by_stage):
    """Pick GPU peak MB at each pipeline boundary group from mlxMemoryByStage."""
    out = {}
    for label, candidates in _GPU_STAGE_GROUPS:
        for stage in candidates:
            snap = mlx_by_stage.get(stage)
            if snap and snap.get("peakMB") is not None:
                out[label] = snap.get("peakMB")
                break
    return out


# Top-level decode-loop stages (timingsMS keys) in pipeline order. The engine
# attributes the wall clock of the hot token loop to exactly these stages plus an
# audio-chunk-eval / unattributed remainder (see qwenTokenLoopUnattributedMS in the
# owned Qwen3TTS.swift), so named stages + "other" sum to qwen_token_loop_total.
# This decomposition answers WHERE decode time goes: the Talker forward, the
# autoregressive 15× Code Predictor loop, the Code2Wav audio decoder, or the
# frame-boundary eval flush.
_DECODE_STAGE_KEYS = [
    ("talker", "qwen_talker_forward_total"),        # Talker (CB0) forward
    ("sampCB0", "qwen_sample_first_codebook_total"),  # sample first codebook
    ("codePred", "qwen_code_predictor_total"),      # 15× Code Predictor loop
    ("code2wav", "qwen_stream_decoder_total"),      # Code2Wav audio decoder
    ("stepEval", "qwen_stream_step_eval_total"),    # per-frame eval flush
]


# Per-chunk substage keys written by the engine into chunkTimeline. Used for both
# placeholder initialization and aggregate extraction in load_runs().
_CHUNK_SUBSTAGE_KEYS = [
    "talkerForwardMS",
    "codePredictorMS",
    "streamStepEvalMS",
    "audioDecoderMS",
]

# Phase 4 per-frame Mimi decoder step-breakdown keys written into
# chunkTimeline[].mimiDecoderBreakdownMS.
_MIMI_DECODER_KEYS = [
    "quantizerMS",
    "preConvMS",
    "preTransformerMS",
    "upsampleMS",
    "initConvMS",
    "decoderBlocksMS",
    "outputSnakeMS",
    "outputConvMS",
    "totalMS",
]


def decode_stage_breakdown(timings):
    """Per-stage decode ms from timingsMS. 'other' = qwen_token_loop_total minus the
    named stages — it folds the small stages the engine also attributes (codec-embedding
    assembly, EOS read, audio-chunk eval) plus the unattributed remainder, so the row
    sums to the loop total. Returns {} when there is no loop total (e.g. load-only rows)."""
    total = timings.get("qwen_token_loop_total")
    if not total:
        return {}
    out = {}
    named_sum = 0
    for label, key in _DECODE_STAGE_KEYS:
        value = timings.get(key)
        if isinstance(value, (int, float)):
            out[label] = value
            named_sum += value
    out["other"] = max(0, total - named_sum)
    return out


# Worst-first ranking of trim levels for the `trims` column annotation.
_TRIM_SEVERITY = {"fullUnload": 3, "hardTrim": 2, "softTrim": 1}


def count_memory_events(engine_row, summary):
    """Count memory_trim / memory_pressure stage marks and the worst trim level.

    Marks live on the engine row's top-level `stageMarks` (and mirror into
    `summary.stageMarks`); each carries `stage` + `metadata.level`. These are
    written by NativeEngineRuntime.trimMemory (memory_trim) and
    recordMemoryPressureObserved (memory_pressure)."""
    marks = engine_row.get("stageMarks") or summary.get("stageMarks") or []
    trim_count = 0
    pressure_count = 0
    worst_rank = 0
    worst_label = None
    for mark in marks:
        stage = mark.get("stage")
        level = (mark.get("metadata") or {}).get("level")
        if stage == "memory_trim":
            trim_count += 1
            rank = _TRIM_SEVERITY.get(level, 0)
            if rank > worst_rank:
                worst_rank, worst_label = rank, level
        elif stage == "memory_pressure":
            pressure_count += 1
    return trim_count, pressure_count, worst_label


def short_model(model_id):
    """Compact a long model id to its distinguishing tail (e.g. 4bit / 8bit)."""
    if not model_id or model_id == "?":
        return "?"
    tail = model_id.replace("Qwen3-TTS-12Hz-1.7B-", "")
    return tail[:26]


def med(values):
    nums = [v for v in values if isinstance(v, (int, float))]
    return statistics.median(nums) if nums else None


def _quartiles(nums):
    """Return (Q1, Q3) for a sorted numeric list using the median-of-halves method."""
    if len(nums) < 2:
        return None, None
    q1 = statistics.median(nums[:len(nums) // 2])
    q3 = statistics.median(nums[(len(nums) + 1) // 2:])
    return q1, q3


def iqr(values):
    nums = sorted(v for v in values if isinstance(v, (int, float)))
    q1, q3 = _quartiles(nums)
    if q1 is None or q3 is None:
        return None
    return q3 - q1


def mad(values):
    nums = [v for v in values if isinstance(v, (int, float))]
    if not nums:
        return None
    median_value = statistics.median(nums)
    return statistics.median(abs(x - median_value) for x in nums)


def reject_outliers(values, factor=1.5):
    """Return sorted values inside the Tukey fence (factor * IQR beyond Q1/Q3).

    factor=1.5 is the conventional Tukey fence for outlier detection.
    A minimum of 4 numeric samples is required before filtering; below that the
    sorted input is returned unchanged because quartiles are unstable.
    """
    nums = sorted(v for v in values if isinstance(v, (int, float)))
    if len(nums) < 4:
        # Too few samples for a stable IQR-based filter.
        return nums
    q1, q3 = _quartiles(nums)
    spread = q3 - q1
    lo = q1 - factor * spread
    hi = q3 + factor * spread
    return [x for x in nums if lo <= x <= hi]


def fmt(value, places=2):
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{places}f}"
    return str(value)


def fmt_ui_heartbeat(group):
    """UI-responsiveness cell: '<delayed>/>50ms max/coverage' from sampled
    MainThreadStallWatchdog heartbeats ('—' when the app row carried none —
    CLI bench runs have no UI, and overlapping generations omit the report).

    Accepts either a list of run dicts (legacy) or a finalized cell summary dict."""
    if isinstance(group, dict):
        delayed = group.get("uiDelayedHeartbeat50")
        max_ms = group.get("uiMaxDelayedHeartbeatMS")
        coverage = group.get("uiHeartbeatCoverage")
    else:
        delayed = med(r["uiDelayedHeartbeat50"] for r in group)
        max_ms = med(r["uiMaxDelayedHeartbeatMS"] for r in group)
        coverage = med(r["uiHeartbeatCoverage"] for r in group)
    if delayed is None and max_ms is None and coverage is None:
        return "—"
    coverage_text = "-" if coverage is None else f"{coverage * 100:.0f}%"
    return f"{fmt(delayed, 0)}/{fmt(max_ms, 0)}ms/{coverage_text}"


def build_summary(cells):
    """Build a JSON-serializable summary of per-cell medians for baseline save/compare.

    `cells` is a dict of finalized cell summaries (as returned by aggregate_runs)."""
    summary = []
    for key, s in cells.items():
        mode, model_id, state, lb = key
        summary.append(
            {
                "cellKey": [mode, model_id, state, lb],
                "mode": mode,
                "modelID": model_id,
                "warmState": state,
                "lenBucket": lb,
                "n": s["n"],
                "rtf": s["rtf"],
                "tokps": s["tokps"],
                "ttfcMS": s["ttfcMS"],
                "physFootMB": s["physFootMB"],
                "qcVerdict": cell_qc(s),
            }
        )
    return summary


def load_baseline_migrations(path):
    """Load reviewed cell-key migrations used by baseline comparison."""
    with open(path, "r", encoding="utf-8") as stream:
        document = json.load(stream)
    if set(document) != {"schemaVersion", "migrations"} or document["schemaVersion"] != 1:
        raise ValueError("baseline migration contract must use schemaVersion 1")
    migrations = document["migrations"]
    if not isinstance(migrations, list):
        raise ValueError("baseline migrations must be an array")
    old_keys = set()
    new_keys = set()
    for index, migration in enumerate(migrations):
        if not isinstance(migration, dict) or set(migration) != {
            "baselineCellKey", "currentCellKey", "reason"
        }:
            raise ValueError(f"baseline migration {index} is malformed")
        old_key = tuple(migration["baselineCellKey"])
        new_key = tuple(migration["currentCellKey"])
        if len(old_key) != 4 or len(new_key) != 4 or not all(
            isinstance(value, str) and value for value in (*old_key, *new_key)
        ):
            raise ValueError(f"baseline migration {index} has an invalid cell key")
        if not isinstance(migration["reason"], str) or not migration["reason"].strip():
            raise ValueError(f"baseline migration {index} requires a reason")
        if old_key in old_keys or new_key in new_keys:
            raise ValueError("baseline migrations must be one-to-one")
        old_keys.add(old_key)
        new_keys.add(new_key)
    return migrations


def compare_summaries(baseline, current, threshold=0.05, migrations=()):
    """Return regression entries where current is worse than baseline by > threshold.

    A regression is:
      - rtf decreased by > threshold (rtf = audioSecondsPerWallSecond; higher is better)
      - tokps decreased by > threshold
      - ttfcMS increased by > threshold
      - physFootMB increased by > threshold
      - qcVerdict worsened (pass -> warn/fail, warn -> fail)
    """
    baseline_by_key = {tuple(b["cellKey"]): b for b in baseline}
    current_by_key = {tuple(c["cellKey"]): c for c in current}
    for migration in migrations:
        old_key = tuple(migration["baselineCellKey"])
        new_key = tuple(migration["currentCellKey"])
        if old_key not in baseline_by_key:
            continue
        if new_key in baseline_by_key and new_key != old_key:
            raise ValueError(f"baseline migration collides with existing cell: {new_key}")
        migrated = dict(baseline_by_key.pop(old_key))
        migrated["cellKey"] = list(new_key)
        baseline_by_key[new_key] = migrated
    regressions = []
    for key in sorted(baseline_by_key.keys() - current_by_key.keys()):
        regressions.append(
            {
                "cellKey": key,
                "metric": "coverage.cell",
                "baseline": "present",
                "current": "missing",
            }
        )
    for key in sorted(current_by_key.keys() - baseline_by_key.keys()):
        regressions.append(
            {
                "cellKey": key,
                "metric": "coverage.cell",
                "baseline": "missing",
                "current": "present",
            }
        )
    for key, cur in current_by_key.items():
        base = baseline_by_key.get(key)
        if base is None:
            continue
        for metric, direction in [
            ("rtf", "down"),
            ("ttfcMS", "up"),
            ("physFootMB", "up"),
            ("tokps", "down"),
        ]:
            b = base.get(metric)
            c = cur.get(metric)
            if b is None and c is None:
                continue
            if b is None or c is None or b == 0:
                regressions.append(
                    {
                        "cellKey": key,
                        "metric": f"coverage.{metric}",
                        "baseline": b,
                        "current": c,
                    }
                )
                continue
            delta = (c - b) / b
            is_regression = (
                (direction == "up" and delta > threshold)
                or (direction == "down" and -delta > threshold)
            )
            if is_regression:
                regressions.append(
                    {
                        "cellKey": key,
                        "metric": metric,
                        "baseline": b,
                        "current": c,
                        "delta": delta,
                    }
                )
        b_qc = base.get("qcVerdict")
        c_qc = cur.get("qcVerdict")
        if b_qc is None or c_qc is None:
            regressions.append(
                {
                    "cellKey": key,
                    "metric": "coverage.qcVerdict",
                    "baseline": b_qc,
                    "current": c_qc,
                }
            )
            continue
        if b_qc and c_qc and b_qc != "-":
            b_sev = _QC_SEVERITY.get(b_qc.split(":")[0], 0)
            c_sev = _QC_SEVERITY.get(c_qc.split(":")[0], 0)
            if c_sev > b_sev:
                regressions.append(
                    {
                        "cellKey": key,
                        "metric": "qcVerdict",
                        "baseline": b_qc,
                        "current": c_qc,
                    }
                )
    return regressions


def print_regressions(regressions):
    """Print a Markdown-aligned table of detected regressions."""
    if not regressions:
        print("\nNo regressions detected against baseline.")
        return
    print(f"\n⚠ Regressions detected ({len(regressions)} cell-metrics exceeded threshold):")
    header = (
        f"{'mode':<8} {'model':<26} {'state':<5} {'len':<6} "
        f"{'metric':<12} {'baseline':>10} {'current':>10} {'delta':>10}"
    )
    print(header)
    print("-" * len(header))
    for r in regressions:
        mode, model_id, state, lb = r["cellKey"]
        baseline = r.get("baseline")
        current = r.get("current")
        if isinstance(baseline, float):
            baseline_str = f"{baseline:.3f}"
        else:
            baseline_str = str(baseline) if baseline is not None else "-"
        if isinstance(current, float):
            current_str = f"{current:.3f}"
        else:
            current_str = str(current) if current is not None else "-"
        delta_str = f"{r['delta']:+.2%}" if "delta" in r else "-"
        print(
            f"{mode:<8} {short_model(model_id):<26} {state:<5} {lb:<6} "
            f"{r['metric']:<12} {baseline_str:>10} {current_str:>10} {delta_str:>10}"
        )


def print_merged_table(merged_runs):
    """Print cross-layer first-chunk latency table from generations-merged.jsonl."""
    if not merged_runs:
        return
    header = (
        f"{'generationID':<16} {'appTTFCMS':>11} "
        f"{'engineServiceFirstChunkMS':>26} {'engineFirstChunkMS':>20} "
        f"{'frontendOverheadMS':>18}"
    )
    print("\nCross-layer first-chunk latency (ms)\n")
    print(header)
    print("-" * len(header))
    for run in merged_runs:
        print(
            f"{run['generationID']:<16} {fmt(run['appTTFCMS'], 0):>11} "
            f"{fmt(run['engineServiceFirstChunkMS'], 0):>26} "
            f"{fmt(run['engineFirstChunkMS'], 0):>20} "
            f"{fmt(run.get('frontendOverheadMS'), 0):>18}"
        )


def main():
    parser = argparse.ArgumentParser(description="Summarize per-generation telemetry.")
    parser.add_argument("diag_dir", nargs="?", default=DEFAULT_DIR,
                        help="diagnostics dir (default: QwenVoice-Debug/diagnostics)")
    parser.add_argument("--label", default="", type=opaque_label,
                        help="opaque privacy-safe identifier stamped on the human-readable output")
    parser.add_argument("--show-variance", action="store_true",
                        help="include IQR columns for RTF and physFoot in the summary table")
    parser.add_argument("--merged", action="store_true",
                        help="show cross-layer first-chunk latency from generations-merged.jsonl")
    parser.add_argument("--engine-only", action="store_true",
                        help="summarize a headless engine benchmark without requiring app telemetry")
    parser.add_argument("--run-id", default="",
                        help="strictly select rows stamped with notes.benchRunID")
    parser.add_argument("--evidence-manifest", metavar="PATH",
                        help="strictly select the exact ordered takes in benchmark-evidence.json")
    parser.add_argument("--save-baseline", metavar="PATH",
                        help="write current summary as JSON baseline")
    parser.add_argument("--compare-baseline", metavar="PATH",
                        help="compare to saved baseline and highlight regressions")
    parser.add_argument(
        "--baseline-migrations",
        metavar="PATH",
        default=os.path.join(os.path.dirname(__file__), "..", "config", "benchmark-baseline-migrations.json"),
        help="reviewed schema-v1 cell-key migration contract",
    )
    parser.add_argument("--regress-threshold", type=float, default=0.05,
                        help="relative delta threshold for regression (default 0.05)")
    args = parser.parse_args()
    diag_dir = args.diag_dir
    generation_ids = None
    cell_by_id = None
    selected_run_id = args.run_id
    strict_selection = bool(args.run_id or args.evidence_manifest)
    try:
        if args.evidence_manifest:
            _, selected_run_id, generation_ids, cell_by_id = load_evidence_selection(
                args.evidence_manifest,
                requested_run_id=args.run_id,
            )
        runs, cells, delivery_cells, skipped_failed = aggregate_runs(
            diag_dir,
            run_id=selected_run_id,
            generation_ids=generation_ids,
            cell_by_id=cell_by_id,
            strict=strict_selection,
            engine_only=args.engine_only,
        )
    except TelemetrySelectionError as error:
        print(f"FAIL: {error}")
        return 1
    if not runs:
        scope = f" for runID={selected_run_id}" if selected_run_id else ""
        print(f"No telemetry rows{scope} under {diag_dir}/engine/generations.jsonl")
        print("Run the benchmark first (see docs/reference/telemetry-and-benchmarking.md).")
        return 1
    if skipped_failed:
        print(f"(skipped {skipped_failed} non-success engine row(s) with finishReason failed/superseded/cancelled)")
    prosody_rows = load_prosody(diag_dir)

    if args.save_baseline:
        summary = build_summary(cells)
        with open(args.save_baseline, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)

    stamp = f"{today_str()} · {git_short_sha()}"
    if args.label:
        stamp += f" · {args.label}"
    print(f"\n[{stamp}]")

    variance_cols = ""
    if args.show_variance:
        variance_cols = f" {'RTF_IQR':>7} {'physFoot_IQR':>12}"
    header = (
        f"{'mode':<8} {'model':<26} {'state':<5} {'len':<6} {'n':>2} "
        f"{'RTF':>6} {'tok/s':>7} {'TTFC ms':>8} {'decode ms':>9} "
        f"{'peakGPU':>8} {'physFoot':>8} {'headMin':>8} {'gpuWS':>6} {'thermal':<8} "
        f"{'trims':>9} {'UI heartbeat':>18} {'QC':<12}"
        + variance_cols
    )
    tiers = sorted({r["deviceClass"] for r in runs})
    forced = any(r["deviceClassForced"] for r in runs)
    print(f"\nTelemetry summary — {diag_dir}")
    if selected_run_id:
        print(f"runID: {selected_run_id} (strictly scoped)")
    print(f"({len(runs)} runs across {len(cells) + len(delivery_cells)} cells; warm shows median)")
    print(f"tier: {', '.join(tiers)}"
          + ("   ⚠ forced (QWENVOICE_FORCE_MEMORY_CLASS)" if forced else "")
          + "\n")
    print(header)
    print("-" * len(header))

    cell_sort = lambda k: (k[0], short_model(k[1]), k[2] != "cold", LEN_ORDER.get(k[3], 9))
    for key in sorted(cells.keys(), key=cell_sort):
        mode, model_id, state, lb = key
        summary = cells[key]
        n = summary["n"]
        row = (
            f"{mode:<8} {short_model(model_id):<26} {state:<5} {lb:<6} {n:>2} "
            f"{fmt(summary['rtf']):>6} "
            f"{fmt(summary['tokps']):>7} "
            f"{fmt(summary['ttfcMS'], 0):>8} "
            f"{fmt(summary['decodeLoopMS'], 0):>9} "
            f"{fmt(summary['peakGpuMB'], 0):>8} "
            f"{fmt(summary['physFootMB'], 0):>8} "
            f"{fmt(summary.get('headMinMB'), 0):>8} "
            f"{fmt(summary.get('gpuWsRatioPeak')):>6} "
            f"{(summary.get('thermalWorst') or '-'):<8} "
            f"{fmt_trims(summary):>9} "
            f"{fmt_ui_heartbeat(summary):>18} "
            f"{cell_qc(summary):<12}"
        )
        if args.show_variance:
            row += (
                f" {fmt(summary.get('rtfIQR')):>7} "
                f"{fmt(summary.get('physFootIQR'), 0):>12}"
            )
        print(row)

    # Delivery cells (vocello bench --delivery): instruct-bearing takes, keyed by
    # the delivery preset id instead of the length bucket (they all run the medium
    # text). Kept out of the tables above so the headline matrix stays comparable;
    # QC + the deterministic paired prosody comparison are the point of these rows.
    if delivery_cells:
        has_prosody = bool(prosody_rows)
        d_header = (
            f"{'mode':<8} {'model':<26} {'state':<5} {'delivery':<16} {'n':>2} "
            f"{'RTF':>6} {'tok/s':>7} {'decode ms':>9} {'physFoot':>8} {'QC':<12}"
            + (f" {'prosN':>5} {'prosEff':>8} {'dF0Std':>7} {'dRateCV':>8} {'dPauseR':>8} {'dRough':>7}" if has_prosody else "")
        )
        print("\nDelivery cells (--delivery; medium text, instruct-bearing) — notes.delivery\n")
        print(d_header)
        print("-" * len(d_header))
        d_sort = lambda k: (k[0], short_model(k[1]), k[2] != "cold", k[3])
        for key in sorted(delivery_cells.keys(), key=d_sort):
            mode, model_id, state, delivery = key
            summary = delivery_cells[key]
            base = (
                f"{mode:<8} {short_model(model_id):<26} {state:<5} {delivery:<16} {summary['n']:>2} "
                f"{fmt(summary['rtf']):>6} "
                f"{fmt(summary['tokps']):>7} "
                f"{fmt(summary['decodeLoopMS'], 0):>9} "
                f"{fmt(summary['physFootMB'], 0):>8} "
                f"{cell_qc(summary):<12}"
            )
            if has_prosody:
                p = prosody_for_delivery(prosody_rows, mode, model_id, delivery)
                if p:
                    base += (
                        f" {p['n']:>5} {p['effect']:>+8.2f} {p['dF0Std']:>+7.2f} "
                        f"{p['dRateCV']:>+8.3f} {p['dPauseRatio']:>+8.3f} {p['dRoughness']:>+7.3f}"
                    )
                else:
                    base += "     -        -       -        -        -       -"
            print(base)

    # GPU memory by pipeline stage (peak MB) — shows WHERE GPU memory grows and how
    # much the post-generation trim reclaims. Median over each cell's runs.
    gpu_header = (
        f"{'mode':<8} {'model':<26} {'state':<5} {'len':<6} "
        f"{'load':>8} {'stream':>8} {'peak':>8} {'trim':>8}"
    )
    print("\nGPU MB by stage (peak; median over cell) — mlxMemoryByStage\n")
    print(gpu_header)
    print("-" * len(gpu_header))
    for key in sorted(cells.keys(), key=cell_sort):
        mode, model_id, state, lb = key
        summary = cells[key]
        gpu = summary.get("gpuByStage") or {}
        print(
            f"{mode:<8} {short_model(model_id):<26} {state:<5} {lb:<6} "
            f"{fmt(gpu.get('load'), 0):>8} "
            f"{fmt(gpu.get('stream'), 0):>8} "
            f"{fmt(gpu.get('peak'), 0):>8} "
            f"{fmt(gpu.get('trim'), 0):>8}"
        )

    # Decode-loop breakdown (ms per stage; median over cell) — from timingsMS. Answers
    # WHERE decode wall time goes: Talker forward vs the autoregressive 15× Code Predictor
    # loop vs the Code2Wav audio decoder vs the frame-boundary eval flush. Named stages +
    # "other" sum to the decode ms column (qwen_token_loop_total).
    dec_header = (
        f"{'mode':<8} {'model':<26} {'state':<5} {'len':<6} "
        f"{'talker':>7} {'sampCB0':>7} {'codePred':>8} {'code2wav':>8} {'stepEval':>8} {'other':>7}"
    )
    print("\nDecode breakdown (ms; median over cell) — timingsMS (named + other ≈ decode ms)\n")
    print(dec_header)
    print("-" * len(dec_header))
    for key in sorted(cells.keys(), key=cell_sort):
        mode, model_id, state, lb = key
        summary = cells[key]
        dec = summary.get("decodeStages") or {}
        print(
            f"{mode:<8} {short_model(model_id):<26} {state:<5} {lb:<6} "
            f"{fmt(dec.get('talker'), 0):>7} "
            f"{fmt(dec.get('sampCB0'), 0):>7} "
            f"{fmt(dec.get('codePred'), 0):>8} "
            f"{fmt(dec.get('code2wav'), 0):>8} "
            f"{fmt(dec.get('stepEval'), 0):>8} "
            f"{fmt(dec.get('other'), 0):>7}"
        )

    # Streaming chunk timeline (cells that actually have chunkTimeline data).
    # Medians over cell: chunk count, first-chunk arrival, inter-chunk gap, and the
    # per-chunk substage latencies (Talker / Code Predictor / step eval / decoder).
    chunk_cells = {
        k: s for k, s in cells.items()
        if s.get("chunkCount") is not None
    }
    if chunk_cells:
        chunk_header = (
            f"{'mode':<8} {'model':<26} {'state':<5} {'len':<6} "
            f"{'nChunks':>7} {'firstChunkMS':>12} {'medianInterChunkMS':>18} "
            f"{'talker':>7} {'codePred':>8} {'stepEval':>8} {'audioDecoder':>12}"
        )
        print("\nChunk timeline summary (streaming cells; median over cell)\n")
        print(chunk_header)
        print("-" * len(chunk_header))
        for key in sorted(chunk_cells.keys(), key=cell_sort):
            mode, model_id, state, lb = key
            summary = chunk_cells[key]
            cs = summary.get("chunkSubstageMS") or {}
            print(
                f"{mode:<8} {short_model(model_id):<26} {state:<5} {lb:<6} "
                f"{fmt(summary['chunkCount'], 0):>7} "
                f"{fmt(summary['firstChunkArrivalMS'], 0):>12} "
                f"{fmt(summary['medianInterChunkMS'], 0):>18} "
                f"{fmt(cs.get('talkerForwardMS'), 0):>7} "
                f"{fmt(cs.get('codePredictorMS'), 0):>8} "
                f"{fmt(cs.get('streamStepEvalMS'), 0):>8} "
                f"{fmt(cs.get('audioDecoderMS'), 0):>12}"
            )

    # Per-frame Mimi decoder step breakdown (cells that emitted step timings).
    mimi_cells = {
        k: s for k, s in cells.items()
        if (s.get("mimiDecoderBreakdownMS") or {})
    }
    if mimi_cells:
        mimi_header = (
            f"{'mode':<8} {'model':<26} {'state':<5} {'len':<6} "
            f"{'quant':>6} {'preC':>5} {'preT':>5} {'upsm':>5} "
            f"{'initC':>5} {'blocks':>6} {'snake':>6} {'outC':>5} {'total':>6}"
        )
        print("\nMimi decoder breakdown per frame (ms; median over cell)\n")
        print(mimi_header)
        print("-" * len(mimi_header))
        for key in sorted(mimi_cells.keys(), key=cell_sort):
            mode, model_id, state, lb = key
            summary = mimi_cells[key]
            md = summary.get("mimiDecoderBreakdownMS") or {}
            print(
                f"{mode:<8} {short_model(model_id):<26} {state:<5} {lb:<6} "
                f"{fmt(md.get('quantizerMS'), 0):>6} "
                f"{fmt(md.get('preConvMS'), 0):>5} "
                f"{fmt(md.get('preTransformerMS'), 0):>5} "
                f"{fmt(md.get('upsampleMS'), 0):>5} "
                f"{fmt(md.get('initConvMS'), 0):>5} "
                f"{fmt(md.get('decoderBlocksMS'), 0):>6} "
                f"{fmt(md.get('outputSnakeMS'), 0):>6} "
                f"{fmt(md.get('outputConvMS'), 0):>5} "
                f"{fmt(md.get('totalMS'), 0):>6}"
            )

    print(
        "\nRTF = audioSeconds / wallSeconds (>1 faster than realtime). "
        "tok/s = codec tokens/s. TTFC = submit→first chunk. "
        "decode ms = qwen_token_loop_total. peakGPU/physFoot/GPU-stage = MB."
    )
    print(
        "Decode breakdown (ms, median): talker = qwen_talker_forward_total · "
        "sampCB0 = qwen_sample_first_codebook_total · codePred = qwen_code_predictor_total "
        "(15× loop) · code2wav = qwen_stream_decoder_total (audio decoder) · "
        "stepEval = qwen_stream_step_eval_total · other = remainder (codec-embedding "
        "assembly + EOS read + audio-chunk eval + unattributed). Named + other ≈ decode ms."
    )
    print(
        "⚠ These are Swift-side wall-clock timers around LAZY MLX ops, not per-stage GPU "
        "compute. talker/codePred measure graph-BUILD time; the single per-frame eval() makes "
        "stepEval the fused compute of Talker+CodePredictor+sampling. code2wav≈0 because the "
        "decoder is asyncEval'd (Phase 2c) and overlaps the token loop — pipelined, not free. "
        "To attribute compute per stage, capture the os_signpost intervals (Talker Forward / "
        "Code Predictor Loop / Step Eval Flush / Audio Decoder) under Instruments xctrace."
    )
    print(
        "physFoot = phys_footprint peak (the figure Jetsam judges — the OOM-relevant "
        "peak; peakRSS + headMin are in the records too). trims = median memory_trim "
        "count [worst level]; raw kernel pressure also recorded as memory_pressure marks."
    )
    print(
        "QC = reference-free audio defect verdict (pass / warn / fail:flags — "
        "nonfinite/clipping/clicks/dropout/near_silent). Promotion also uses fixed-seed "
        "exact-WAV, ASR, and applicable prosody evidence; listening is optional annotation."
    )
    if prosody_rows:
        print(
            "Delivery prosody: prosEff = signed prosody-effect score vs paired neutral "
            "(+F0 dynamics +rate variability -pauses +roughness). Requires `vocello bench --delivery`."
        )

    if args.merged:
        try:
            merged_runs = load_merged_runs(
                diag_dir,
                run_id=selected_run_id,
                generation_ids=generation_ids,
                strict=strict_selection,
            )
        except TelemetrySelectionError as error:
            print(f"\nFAIL: {error}")
            return 1
        if merged_runs:
            print_merged_table(merged_runs)
        else:
            print("\nNo generations-merged.jsonl found; cross-layer table skipped.")

    if args.compare_baseline:
        try:
            with open(args.compare_baseline, "r", encoding="utf-8") as f:
                baseline = json.load(f)
            migrations = load_baseline_migrations(args.baseline_migrations)
            current = build_summary(cells)
            regressions = compare_summaries(
                baseline, current, threshold=args.regress_threshold, migrations=migrations
            )
        except (OSError, ValueError, json.JSONDecodeError) as error:
            print(f"FAIL: baseline comparison contract is invalid: {error}")
            return 1
        print_regressions(regressions)
        if regressions:
            return 2

    return 0


def fmt_trims(group):
    """Median memory_trim count for the cell, annotated with the worst level seen.

    Accepts either a list of run dicts (legacy) or a finalized cell summary dict."""
    if isinstance(group, dict):
        count = group.get("trims")
        worst = group.get("worstTrim")
    else:
        count = med(r["trims"] for r in group)
        worst = None
        worst_rank = 0
        for r in group:
            rank = _TRIM_SEVERITY.get(r.get("worstTrim"), 0)
            if rank > worst_rank:
                worst_rank, worst = rank, r["worstTrim"]
    if count is None:
        return "-"
    label = f"{int(count)}"
    if worst:
        # soft/hard/full — short tag keeps the column narrow.
        label += f" {worst.replace('Trim', '').replace('Unload', '')[:4]}"
    return label


if __name__ == "__main__":
    raise SystemExit(main())
