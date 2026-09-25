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
import functools
import json
import hashlib
import os
import re
import statistics
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))
from lib import jsonio  # noqa: E402
from lib import rtf as rtf_semantics  # noqa: E402

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
    # `prosodyEffect` is the instructed take's absolute expressiveness (audit
    # #9); only `pairedProsodyEffect` is the effect against the paired neutral.
    # A sidecar written before the paired key existed shows no effect.
    paired = [r["pairedProsodyEffect"] for r in rows if "pairedProsodyEffect" in r]
    return {
        "effect": med(paired) if len(paired) == len(rows) else None,
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
        app_frontend = app.get("frontendMetrics") or {}
        run = {
            "generationID": row.get("generationID"),
            "appTTFCMS": app_frontend.get("submitToFirstChunkMS")
                if app_frontend.get("submitToFirstChunkMS") is not None
                else (app.get("timingsMS") or {}).get("submitToFirstChunkMS"),
            "engineFirstChunkMS": first_stage_mark_ms(engine, "firstChunk"),
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
        # Standard RTF (request wall ÷ audio, lower is faster) and the decode-loop
        # speedup (audio ÷ decode seconds, higher is faster) that older summaries
        # printed under the RTF heading.
        "rtf": rtf_semantics.engine_rtf(e),
        "decodeSpeedupX": derived.get("audioSecondsPerWallSecond"),
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
        # Exact per-request MLX high-water mark (memoryMetrics, telemetry v8).
        # Unlike the sampled phys_footprint peak it does not drift between
        # identical runs, so the gate judges memory on it.
        "mlxPeakMB": (e.get("memoryMetrics") or {}).get("mlxCumulativePeakMB"),
        # Seeded takes are token-exact; the count shows whether they were.
        "generatedTokens": derived.get("generatedTokenCount"),
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
        # Whether the tier was forced via QWENVOICE_FORCE_MEMORY_CLASS or
        # emulated via QWENVOICE_SIMULATED_PHYSICAL_MEMORY_GB (vs the native
        # tier) — so a real 8 GB Mac isn't mislabeled "forced".
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
    speedups: list = field(default_factory=list)
    tokpss: list = field(default_factory=list)
    ttfcs: list = field(default_factory=list)
    decode_loop_ms: list = field(default_factory=list)
    peak_gpu_mb: list = field(default_factory=list)
    phys_foot_mb: list = field(default_factory=list)
    mlx_peak_mb: list = field(default_factory=list)
    generated_tokens: list = field(default_factory=list)
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
        if run.get("decodeSpeedupX") is not None:
            self.speedups.append(run["decodeSpeedupX"])
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
        if run.get("mlxPeakMB") is not None:
            self.mlx_peak_mb.append(run["mlxPeakMB"])
        if run.get("generatedTokens") is not None:
            self.generated_tokens.append(run["generatedTokens"])
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
            "n": len(self.rtfs) or len(self.speedups) or len(self.tokpss) or len(self.ttfcs),
            "rtf": med(self.rtfs),
            "decodeSpeedupX": med(self.speedups),
            "tokps": med(self.tokpss),
            "ttfcMS": med(self.ttfcs),
            "decodeLoopMS": med(self.decode_loop_ms),
            "peakGpuMB": med(self.peak_gpu_mb),
            "physFootMB": med(self.phys_foot_mb),
            "headMinMB": med(self.head_min_mb),
            "gpuWsRatioPeak": med(self.gpu_ws_ratio_peaks),
            "thermalWorst": _worst_thermal(self.thermal_worsts),
            "rtfIQR": iqr(self.rtfs),
            "rtfMAD": mad(self.rtfs),
            "physFootIQR": iqr(self.phys_foot_mb),
            "physFootMAD": mad(self.phys_foot_mb),
            "mlxPeakMB": med(self.mlx_peak_mb),
            "mlxPeakMAD": mad(self.mlx_peak_mb),
            "generatedTokenCounts": list(self.generated_tokens),
            "trims": med(self.trims),
            "worstTrim": worst_trim,
            "uiDelayedHeartbeat50": med(self.ui_stalls),
            "uiMaxDelayedHeartbeatMS": med(self.ui_max_stalls),
            "uiHeartbeatCoverage": med(self.ui_heartbeat_coverage),
            "qcVerdict": qc,
            "qcFlags": sorted(self.qc_flags),
            "chunkCount": med(self.chunk_counts),
            "firstChunkArrivalMS": med(self.first_chunk_arrivals),
            "firstChunkArrivalMAD": mad(self.first_chunk_arrivals),
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
    # The step's sampled-token read (V-2): under `.pipelined` the host's wait
    # for the GPU work stepEval only enqueued. Rows written before BT-06
    # (2026-09-25) lack it.
    ("tokRead", "qwen_stream_step_token_read_total"),
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

    `cells` is a dict of finalized cell summaries (as returned by aggregate_runs).
    `engineFirstChunkMS` is the engine-side first-chunk arrival (median of
    chunkTimeline[0].arrivalMS), the only latency a headless `--engine-only` run
    has; app-level `ttfcMS` stays with the UI lanes."""
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
                "rtfMAD": s.get("rtfMAD"),
                "physFootMAD": s.get("physFootMAD"),
                "decodeSpeedupX": s.get("decodeSpeedupX"),
                "tokps": s["tokps"],
                "ttfcMS": s["ttfcMS"],
                "engineFirstChunkMS": s.get("firstChunkArrivalMS"),
                "engineFirstChunkMAD": s.get("firstChunkArrivalMAD"),
                "physFootMB": s["physFootMB"],
                "mlxPeakMB": s.get("mlxPeakMB"),
                "mlxPeakMAD": s.get("mlxPeakMAD"),
                "generatedTokens": med(s.get("generatedTokenCounts") or []),
                "generatedTokenCounts": list(s.get("generatedTokenCounts") or []),
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


BASELINE_SCHEMA_VERSION = 2

# The OS and toolchain that measured a run. They come from the run's own
# evidence (the pre-run source snapshot folds them into the manifest's hardware
# and toolchain blocks), never from the tools installed when a baseline is saved
# or compared, so a baseline seeded from older evidence after a toolchain update
# keeps the identity of the run that produced it. A new OS or Xcode build number
# is a new identity and forces a re-seed.
HOST_IDENTITY_KEYS = ("osVersion", "osBuild", "xcodeVersion", "xcodeBuild", "swiftVersion")
_HOST_IDENTITY_SOURCES = {
    "osVersion": "hardware",
    "osBuild": "hardware",
    "xcodeVersion": "toolchain",
    "xcodeBuild": "toolchain",
    "swiftVersion": "toolchain",
}
# The memory tier the rows ran under (audit #19), from the record's
# `run.runtimePolicy`. A baseline saved before it compares without it, like a
# baseline saved before the host keys, and the caller says so.
RUNTIME_POLICY_IDENTITY_KEYS = ("deviceClass",)
# The identity keys a pre-run preflight can predict without evidence: the host,
# the optimization the gate builds and the matrix it will run. Models, corpus
# and evidence versions are only known once the takes exist.
PREFLIGHT_IDENTITY_KEYS = (
    "kind", "platform", "matrixScope", "hardwareProfile", *HOST_IDENTITY_KEYS,
    "optimization", "matrixHash",
)


def _identity_fields(history):
    """Every identity field the given historyRecord-shaped payload carries."""
    def section(name):
        value = history.get(name)
        return value if isinstance(value, dict) else {}

    run, hardware, toolchain, inputs, evidence = (
        section("run"), section("hardware"), section("toolchain"), section("inputs"), section("evidence"),
    )
    sources = {"hardware": hardware, "toolchain": toolchain}
    fields = {
        "kind": run.get("kind"),
        "platform": run.get("platform"),
        "matrixScope": run.get("matrixScope"),
        "hardwareProfile": hardware.get("profileID"),
        **{key: sources[_HOST_IDENTITY_SOURCES[key]].get(key) for key in HOST_IDENTITY_KEYS},
        "optimization": toolchain.get("optimization"),
        "matrixHash": inputs.get("matrixHash"),
        "corpusHash": inputs.get("corpusHash"),
        "telemetrySchemaVersion": evidence.get("telemetrySchemaVersion"),
        "qcAlgorithmVersion": evidence.get("qcAlgorithmVersion"),
    }
    models = history.get("models")
    if isinstance(models, list) and models and all(isinstance(model, dict) for model in models):
        fields["models"] = [
            {
                key: model.get(key)
                for key in (
                    "mode", "modelID", "variant", "quantization", "revision",
                    "artifactVersion", "integrityDigest", "runtimeProfileSignature",
                    "fixtureDigest",
                )
            }
            for model in models
        ]
    return fields


def baseline_identity_from_evidence(payload, *, require_host_identity=True, require_device_class=True):
    """Return the performance-comparison identity from validated evidence.

    Source and executable digests are deliberately excluded: a regression
    baseline must survive source changes to detect their performance impact.
    The optimization, topology, hardware, host OS and toolchain build, model
    artifact, matrix/corpus (the matrix hash binds the sampling seed), and
    evidence semantics remain exact so unlike lanes can never compare. Every
    field is read from the evidence; nothing is probed on the comparing host.
    `require_host_identity=False` is only for comparing with a baseline saved
    before host identity was recorded, which ignores those keys.

    The memory tier (`deviceClass`) comes from the record's `run.runtimePolicy`,
    which the publisher derives from the rows' own stamps; evidence that ran
    under a forced memory class never yields an identity. Evidence from rows
    that predate the stamp has no `runtimePolicy`: seeding always requires it,
    and comparing with a baseline saved before the tier was bound passes
    `require_device_class=False`, which leaves the tier out as that baseline does.
    """
    if not isinstance(payload, dict):
        raise ValueError("baseline identity requires an evidence manifest")
    history = payload.get("historyRecord")
    if not isinstance(history, dict):
        raise ValueError("baseline identity evidence has no historyRecord")
    if not all(
        isinstance(history.get(name), dict)
        for name in ("run", "hardware", "toolchain", "inputs", "evidence")
    ):
        raise ValueError("baseline identity evidence is incomplete")
    models = history.get("models")
    if not isinstance(models, list) or not models or any(not isinstance(model, dict) for model in models):
        raise ValueError("baseline identity evidence has no model identities")
    fields = _identity_fields(history)
    if fields["optimization"] not in {"-O", "-Onone"}:
        raise ValueError("baseline identity has an unsupported optimization")
    identity = {
        key: fields[key]
        for key in (
            "kind", "platform", "matrixScope", "hardwareProfile", *HOST_IDENTITY_KEYS,
            "optimization", "matrixHash", "corpusHash", "models",
            "telemetrySchemaVersion", "qcAlgorithmVersion",
        )
    }
    runtime_policy = history["run"].get("runtimePolicy")
    if runtime_policy is not None or require_device_class:
        if not isinstance(runtime_policy, dict):
            raise ValueError("baseline identity evidence has no runtimePolicy (memory tier)")
        if runtime_policy.get("deviceClassForced") is not False:
            raise ValueError("baseline identity evidence ran under a forced memory class")
        identity["deviceClass"] = runtime_policy.get("deviceClass")
    missing = [
        key for key, value in identity.items()
        if value in (None, "", []) and (require_host_identity or key not in HOST_IDENTITY_KEYS)
    ]
    if missing:
        raise ValueError(
            "baseline identity is missing: " + ", ".join(sorted(missing))
            + " (evidence captured before the run-time host identity was recorded cannot seed or compare)"
        )
    return identity


def identity_differences(baseline_identity, current_identity, keys=None):
    """Sorted identity keys whose values differ, including keys only one side has."""
    baseline_identity = baseline_identity if isinstance(baseline_identity, dict) else {}
    current_identity = current_identity if isinstance(current_identity, dict) else {}
    candidates = set(keys) if keys is not None else set(baseline_identity) | set(current_identity)
    return sorted(
        key for key in candidates
        if baseline_identity.get(key) != current_identity.get(key)
        or (key in baseline_identity) != (key in current_identity)
    )


def host_load_verdict(evidence_payload, *, cpu_count=None, states=None):
    """Reasons the host was too busy, throttled or in low power for a verdict.

    Every take records its run environment at generation start; the publisher
    keeps each take's one-minute load (`metrics.loadAverage1M`) and low-power
    state, and folds the run's worst thermal state into the hardware block. The
    busiest judged take decides (the warm takes when `states` names them), so
    load that arrives after the first sample is not missed; evidence without
    per-take load falls back to the run's first sample. A comparison under heavy
    load, throttling or low power is inconclusive, never a pass or a regression.
    """
    if not isinstance(evidence_payload, dict):
        return []
    history = evidence_payload.get("historyRecord") or {}
    hardware = history.get("hardware") or {}
    takes = [take for take in history.get("takes") or [] if isinstance(take, dict)]
    if states is not None:
        wanted = set(states)
        takes = [take for take in takes if take.get("warmState") in wanted]

    def number(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    take_loads = [
        load for take in takes
        if (load := number((take.get("metrics") or {}).get("loadAverage1M"))) is not None
    ]
    reasons = []
    cores = cpu_count or os.cpu_count() or 1
    if take_loads:
        load, source = max(take_loads), f"busiest of {len(take_loads)} judged take(s)"
    else:
        load, source = number(hardware.get("loadAverage1M")), "run sample"
    if load is not None and load > 2.0 * cores:
        reasons.append(f"load average {load:.2f} exceeds 2x{cores} cores ({source})")
    thermal = str(hardware.get("thermalState", "nominal")).lower()
    if thermal in {"serious", "critical"}:
        reasons.append(f"thermal state {thermal}")
    low_power = hardware.get("lowPowerMode") is True or any(
        number((take.get("metrics") or {}).get("lowPowerMode")) == 1.0 for take in takes
    )
    if low_power:
        reasons.append("low power mode was enabled")
    return reasons


# Regression floors by metric, as fractions of the baseline median. A metric
# not listed uses the flat --regress-threshold (5 %). A floor keeps a threshold
# from collapsing onto the flat value when three consecutive takes happen to
# agree, which the within-run dispersion term alone cannot (audit #5). Each
# floor clears the drift measured between committed identical-source M2 runs
# (1,258 ordered pairs of clean records on one commit, replayed offline):
# - physFootMB: the sampled phys_footprint peak moved up to +25.6 % (+16.5 %
#   in the gate cell: warm medians 2273, 2315, 2511 and 2649 MB around
#   b88d6d03), while a baseline's own three takes can agree to 0.05 MB.
# - engineFirstChunkMS: first-chunk medians moved up to +13 % (p90 of the
#   between-run range 12.6 %); the first warm take after a load skews it.
# - mlxPeakMB: the exact MLX high-water mark never moved more than 0.61 % and
#   agreed to 0.001 MB across four gate runs on three commits, so a tight floor
#   makes it the memory-regression signal.
METRIC_THRESHOLD_FLOORS = {
    "engineFirstChunkMS": 0.15,
    "physFootMB": 0.30,
    "mlxPeakMB": 0.02,
}
# (metric, regression direction, within-run dispersion key) in verdict order.
COMPARED_METRICS = (
    ("rtf", "up", "rtfMAD"),
    ("ttfcMS", "up", None),
    ("engineFirstChunkMS", "up", "engineFirstChunkMAD"),
    ("physFootMB", "up", "physFootMAD"),
    ("mlxPeakMB", "up", "mlxPeakMAD"),
    ("tokps", "down", None),
)
# Metrics added after baselines were first saved: a baseline cell without the
# key predates them and is not judged on them (a key present with no value is
# still a coverage failure).
LATER_BASELINE_METRICS = frozenset({"engineFirstChunkMS", "mlxPeakMB"})
# A between-run spread widens a threshold once a baseline pools this many runs.
MINIMUM_POOLED_RUNS = 3


def effective_threshold(base_cell, threshold, median_key="rtf", mad_key="rtfMAD"):
    """Widen the flat threshold to three median absolute deviations of the
    baseline's own takes when it has at least three samples; one-take baselines
    keep the flat value."""
    n = base_cell.get("n")
    mad_value = base_cell.get(mad_key)
    median = base_cell.get(median_key)
    if (
        isinstance(n, int) and n >= 3
        and isinstance(mad_value, (int, float)) and isinstance(median, (int, float)) and median
    ):
        return max(threshold, 3.0 * float(mad_value) / abs(float(median)))
    return threshold


def metric_threshold(base_cell, metric, threshold, mad_key=None):
    """(threshold, basis) for one metric of one baseline cell.

    The largest of: the metric's floor (or the flat threshold), three MADs of
    the baseline's own takes (n >= 3), and the full range of the per-run medians
    when the baseline pools at least three seeded runs (so no seed run would
    have regressed against the baseline it helped build).
    """
    candidates = [(METRIC_THRESHOLD_FLOORS.get(metric, threshold), "floor")]
    if mad_key:
        within = effective_threshold(base_cell, 0.0, metric, mad_key)
        if within > 0:
            candidates.append((within, "3 MAD of the baseline takes"))
    runs = base_cell.get("runCount")
    spread = (base_cell.get("runSpread") or {}).get(metric)
    if (
        isinstance(runs, int) and runs >= MINIMUM_POOLED_RUNS
        and isinstance(spread, (int, float)) and not isinstance(spread, bool) and spread > 0
    ):
        candidates.append((float(spread), f"range of {runs} seeded runs"))
    return max(candidates, key=lambda candidate: candidate[0])


def baseline_document(cells, evidence_payload=None):
    if evidence_payload is None:
        # Ad-hoc local baseline: no identity, but it still declares which RTF it
        # stores. Governed callers pass --require-baseline-identity and reject it.
        return {
            "schemaVersion": BASELINE_SCHEMA_VERSION,
            "rtfDefinition": rtf_semantics.STANDARD_RTF_DEFINITION,
            "cells": cells,
        }
    return {
        "schemaVersion": BASELINE_SCHEMA_VERSION,
        "rtfDefinition": rtf_semantics.STANDARD_RTF_DEFINITION,
        "identity": baseline_identity_from_evidence(evidence_payload),
        "cells": cells,
    }


def baseline_rtf_definition(payload):
    """`wall/audio` for baselines saved since the RTF cutover, else legacy.

    A legacy baseline's `rtf` is the decode-loop speedup, so it is compared
    against the current `decodeSpeedupX` (the same quantity) rather than the
    standard RTF; the caller prints that this happened."""
    if isinstance(payload, dict) and payload.get("rtfDefinition") == rtf_semantics.STANDARD_RTF_DEFINITION:
        return rtf_semantics.STANDARD_RTF_DEFINITION
    return rtf_semantics.LEGACY_RTF_DEFINITION


def baseline_cells(payload, *, current_identity=None, require_identity=False):
    """The baseline's cells once its identity (if any) matches the current run.

    `current_identity` is the run's identity, or a callable that derives it
    (`require_host_identity=` keyword) and is called only when the baseline
    carries an identity to compare, so an ad-hoc or legacy baseline never needs
    evidence the run lacks.
    """
    if isinstance(payload, list):
        if require_identity:
            raise ValueError("legacy baseline has no optimization/topology identity")
        return payload
    if not isinstance(payload, dict) or payload.get("schemaVersion") != BASELINE_SCHEMA_VERSION:
        raise ValueError("baseline must be a legacy cell array or schema-v2 object")
    cells = payload.get("cells")
    identity = payload.get("identity")
    if not isinstance(cells, list) or not cells:
        raise ValueError("schema-v2 baseline has no cells")
    if identity is None and not require_identity:
        # Ad-hoc local baseline saved without an evidence manifest.
        return cells
    if not isinstance(identity, dict):
        raise ValueError("schema-v2 baseline has no identity")
    # A baseline saved before host identity was recorded compares the rest, and
    # the caller says so.
    legacy_host = not any(key in identity for key in HOST_IDENTITY_KEYS)
    legacy_device = any(key not in identity for key in RUNTIME_POLICY_IDENTITY_KEYS)
    if callable(current_identity):
        current_identity = current_identity(
            require_host_identity=not legacy_host, require_device_class=not legacy_device,
        )
    if current_identity is None:
        raise ValueError("schema-v2 baseline comparison requires current evidence identity")
    comparable_current = dict(current_identity)
    if legacy_host:
        for key in HOST_IDENTITY_KEYS:
            comparable_current.pop(key, None)
    if legacy_device:
        for key in RUNTIME_POLICY_IDENTITY_KEYS:
            comparable_current.pop(key, None)
    differences = identity_differences(identity, comparable_current)
    if differences:
        raise ValueError(
            "baseline optimization/topology identity differs from current evidence: "
            + ", ".join(differences)
        )
    return cells


def baseline_lacks_host_identity(payload):
    identity = payload.get("identity") if isinstance(payload, dict) else None
    return isinstance(identity, dict) and not any(key in identity for key in HOST_IDENTITY_KEYS)


def baseline_lacks_device_class(payload):
    identity = payload.get("identity") if isinstance(payload, dict) else None
    return isinstance(identity, dict) and any(
        key not in identity for key in RUNTIME_POLICY_IDENTITY_KEYS
    )


def forced_memory_class_rows(runs):
    """Rows that ran under QWENVOICE_FORCE_MEMORY_CLASS or an emulated smaller
    Mac, QWENVOICE_SIMULATED_PHYSICAL_MEMORY_GB (audit #19, #11).

    A forced tier changes policy values, not the hardware, so such rows are
    exploratory evidence: a regression baseline is never saved or seeded from
    them and never compared with them."""
    return [run for run in runs if run.get("deviceClassForced")]


def baseline_bytes(document):
    """The saved baseline's encoding: indent 2, key order kept, ASCII, newline."""
    return (json.dumps(document, indent=2) + "\n").encode("utf-8")


def compare_summaries(
    baseline, current, threshold=0.05, migrations=(),
    baseline_definition=rtf_semantics.STANDARD_RTF_DEFINITION, states=None, details=None,
):
    """Return regression entries where current is worse than baseline by > threshold.

    `states` restricts the verdict to cells in those warm states (the gate bench
    compares its warm medians only; the single cold take stays
    informational). None compares every cell. `details`, when a list, receives
    one row per judged (cell, metric) with the threshold and its basis, so the
    caller can print and keep the thresholds it used.

    A regression is:
      - rtf increased beyond its threshold (standard RTF = request wall ÷ audio;
        lower is better); against a legacy baseline the baseline's speedup is
        compared with the current `decodeSpeedupX` instead (decrease = regression)
      - tokps decreased, or ttfcMS, engineFirstChunkMS, physFootMB or mlxPeakMB
        increased, beyond their thresholds (`metric_threshold`: the metric's floor,
        three baseline MADs, or the between-run range of a pooled baseline)
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
    if states is not None:
        wanted = set(states)
        baseline_by_key = {key: cell for key, cell in baseline_by_key.items() if key[2] in wanted}
        current_by_key = {key: cell for key, cell in current_by_key.items() if key[2] in wanted}
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
    legacy_baseline = baseline_definition != rtf_semantics.STANDARD_RTF_DEFINITION
    for key, cur in current_by_key.items():
        base = baseline_by_key.get(key)
        if base is None:
            continue
        # A cell without a sample count is not evidence on either side.
        if any(not isinstance(cell.get("n"), int) or cell["n"] < 1 for cell in (base, cur)):
            regressions.append({
                "cellKey": key, "metric": "coverage.n",
                "baseline": base.get("n"), "current": cur.get("n"),
            })
            continue
        for metric, direction, mad_key in COMPARED_METRICS:
            if metric == "rtf" and legacy_baseline:
                direction = "down"
            if metric in LATER_BASELINE_METRICS and metric not in base:
                if details is not None:
                    details.append({
                        "cellKey": list(key), "metric": metric, "judged": False,
                        "reason": "the baseline predates this metric",
                    })
                continue
            b = base.get(metric)
            c = cur.get("decodeSpeedupX" if metric == "rtf" and legacy_baseline else metric)
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
            metric_limit, basis = metric_threshold(base, metric, threshold, mad_key)
            is_regression = (
                (direction == "up" and delta > metric_limit)
                or (direction == "down" and -delta > metric_limit)
            )
            if details is not None:
                details.append({
                    "cellKey": list(key), "metric": metric, "judged": True,
                    "direction": direction, "baseline": b, "current": c, "delta": delta,
                    "threshold": metric_limit, "basis": basis, "regression": is_regression,
                })
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


# ---------------------------------------------------------------------------
# Governed seeding: a baseline pooled from several identical-source runs.
# ---------------------------------------------------------------------------

_POOLED_VALUE_KEYS = (
    "rtf", "decodeSpeedupX", "tokps", "ttfcMS", "engineFirstChunkMS",
    "physFootMB", "mlxPeakMB", "generatedTokens",
)
_POOLED_MAD_KEYS = ("rtfMAD", "physFootMAD", "engineFirstChunkMAD", "mlxPeakMAD")


def _numbers(values):
    return [
        float(value) for value in values
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]


def pooled_cells(seeded_runs):
    """Pool per-run cell summaries into one baseline cell per cell key.

    Each value is the median of the per-run medians, which is what a single gate
    run is compared with; `runSpread` keeps the between-run range of each
    compared metric relative to that pooled median, and `n` is the smallest
    per-run take count.
    """
    members_by_key = {}
    order = []
    for run in seeded_runs:
        for cell in run.get("cells") or []:
            key = tuple(cell["cellKey"])
            if key not in members_by_key:
                members_by_key[key] = []
                order.append(key)
            members_by_key[key].append(cell)
    pooled = []
    for key in order:
        members = members_by_key[key]
        mode, model_id, state, bucket = key
        cell = {
            "cellKey": list(key), "mode": mode, "modelID": model_id,
            "warmState": state, "lenBucket": bucket,
            "n": min(
                (member["n"] for member in members if isinstance(member.get("n"), int)),
                default=None,
            ),
            "runCount": len(members),
        }
        for name in (*_POOLED_VALUE_KEYS, *_POOLED_MAD_KEYS):
            values = _numbers(member.get(name) for member in members)
            cell[name] = statistics.median(values) if values else None
        spread = {}
        for metric, _direction, _mad in COMPARED_METRICS:
            values = _numbers(member.get(metric) for member in members)
            if len(values) >= 2 and cell.get(metric):
                spread[metric] = (max(values) - min(values)) / abs(cell[metric])
        cell["runSpread"] = spread
        verdicts = [member.get("qcVerdict") for member in members if member.get("qcVerdict")]
        cell["qcVerdict"] = max(
            verdicts, key=lambda verdict: _QC_SEVERITY.get(verdict.split(":")[0], 0), default=None,
        )
        cell["generatedTokenCounts"] = [
            count for member in members for count in member.get("generatedTokenCounts") or []
        ]
        pooled.append(cell)
    return pooled


def _evidence_source(evidence_payload):
    history = (evidence_payload or {}).get("historyRecord") or {}
    source = history.get("source") if isinstance(history.get("source"), dict) else {}
    return source.get("commit"), source.get("dirty")


class SeedRefused(ValueError):
    """The run cannot seed a baseline; nothing was written."""

    def __init__(self, message, *, inconclusive=False):
        super().__init__(message)
        self.inconclusive = inconclusive


def seed_baseline(path, cells, evidence_payload, *, states=None, minimum_takes=3, cpu_count=None):
    """Add one governed run to the pooled baseline at `path` and return it.

    Refuses (SeedRefused, nothing written) unless the run has complete evidence
    identity, a clean source commit, a quiet host over its judged takes and at
    least `minimum_takes` takes in every judged cell. A baseline at `path` with
    the same identity whose seeded runs share this run's commit gains the run;
    any other file is replaced by a new one-run baseline. Returns
    (document, pooled_run_count, replaced_previous).
    """
    if evidence_payload is None:
        raise SeedRefused("seeding requires --evidence-manifest (the baseline identity comes from the run's evidence)")
    # The host verdict comes first, as in a comparison (audit V-7): a loaded run
    # is inconclusive whatever else is wrong with its evidence.
    load_reasons = host_load_verdict(evidence_payload, cpu_count=cpu_count, states=states)
    if load_reasons:
        raise SeedRefused("the host was not quiet: " + "; ".join(load_reasons), inconclusive=True)
    identity = baseline_identity_from_evidence(evidence_payload)
    commit, dirty = _evidence_source(evidence_payload)
    if not isinstance(commit, str) or not commit or dirty is not False:
        raise SeedRefused("seeding requires evidence from a clean source commit")
    judged = [
        cell for cell in cells
        if states is None or cell["cellKey"][2] in set(states)
    ]
    if not judged:
        raise SeedRefused("the run has no cell in the judged states")
    short = [
        "/".join(str(part) for part in cell["cellKey"]) for cell in judged
        if not isinstance(cell.get("n"), int) or cell["n"] < minimum_takes
    ]
    if short:
        raise SeedRefused(f"every judged cell needs at least {minimum_takes} takes: " + ", ".join(short))
    run_id = evidence_payload.get("runID")
    if not isinstance(run_id, str) or not run_id:
        raise SeedRefused("the evidence manifest has no runID")

    existing = None
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as stream:
                existing = json.load(stream)
        except (OSError, json.JSONDecodeError):
            existing = None
    runs = []
    replaced = existing is not None
    if (
        isinstance(existing, dict)
        and existing.get("schemaVersion") == BASELINE_SCHEMA_VERSION
        and existing.get("identity") == identity
        and isinstance(existing.get("seededRuns"), list)
        and existing["seededRuns"]
        and all(
            isinstance(run, dict) and run.get("sourceCommit") == commit
            for run in existing["seededRuns"]
        )
    ):
        runs = list(existing["seededRuns"])
        replaced = False
    if any(run.get("runID") == run_id for run in runs):
        return existing, len(runs), False
    runs.append({"runID": run_id, "sourceCommit": commit, "cells": cells})
    document = {
        "schemaVersion": BASELINE_SCHEMA_VERSION,
        "rtfDefinition": rtf_semantics.STANDARD_RTF_DEFINITION,
        "identity": identity,
        "seededRuns": runs,
        "cells": pooled_cells(runs),
    }
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    temporary = f"{path}.tmp.{os.getpid()}"
    with open(temporary, "w", encoding="utf-8") as stream:
        json.dump(document, stream, indent=2)
        stream.write("\n")
    os.replace(temporary, path)
    return document, len(runs), replaced


def _short(value):
    text = str(value)
    return text if len(text) <= 24 else text[:12] + "..."


def preflight_baseline(baseline_path, expected_payload, *, seeding):
    """Predict before any build whether the gate bench can use its baseline.

    `expected_payload` is the partial evidence `publish_benchmark_history.py
    expected-identity` derives from the live host and the gate matrix. Returns
    (exit_code, lines): 1 when a comparison is predicted to be BASELINE INVALID
    or a seed run could not be accepted, else 0.
    """
    history = (expected_payload or {}).get("historyRecord")
    if not isinstance(history, dict):
        return 1, ["preflight: the expected identity has no historyRecord"]
    fields = _identity_fields(history)
    expected = {key: fields.get(key) for key in PREFLIGHT_IDENTITY_KEYS}
    unknown = sorted(key for key, value in expected.items() if value in (None, ""))
    if unknown:
        return 1, ["preflight: the expected identity is missing " + ", ".join(unknown)]
    commit, dirty = _evidence_source(expected_payload)
    payload = None
    if os.path.exists(baseline_path):
        try:
            with open(baseline_path, "r", encoding="utf-8") as stream:
                payload = json.load(stream)
        except (OSError, json.JSONDecodeError) as error:
            if not seeding:
                return 1, [f"preflight: the baseline is unreadable: {error}"]
    identity = payload.get("identity") if isinstance(payload, dict) else None

    if seeding:
        if dirty is not False or not commit:
            return 1, ["preflight: seeding needs a clean source commit; commit or discard the changes first"]
        runs = payload.get("seededRuns") if isinstance(payload, dict) else None
        if (
            isinstance(identity, dict)
            and not identity_differences(identity, expected, PREFLIGHT_IDENTITY_KEYS)
            and isinstance(runs, list) and runs
            and all(isinstance(run, dict) and run.get("sourceCommit") == commit for run in runs)
        ):
            return 0, [
                f"preflight: this run joins {len(runs)} staged seed run(s) from commit {commit[:12]} "
                "if its models, corpus and evidence versions match too"
            ]
        return 0, ["preflight: this run starts a new staged baseline (no staged runs share this host, matrix and commit)"]

    if payload is None:
        return 0, ["preflight: no committed baseline; the gate bench will run without a comparison"]
    if not isinstance(identity, dict):
        return 1, ["preflight: the committed baseline has no identity, so the governed comparison cannot use it"]
    known = list(PREFLIGHT_IDENTITY_KEYS)
    if not any(key in identity for key in HOST_IDENTITY_KEYS):
        # The same rule as baseline_cells: a baseline saved before host identity
        # was recorded is compared on the rest.
        known = [key for key in known if key not in HOST_IDENTITY_KEYS]
    differences = identity_differences(identity, expected, known)
    if differences:
        return 1, [
            "preflight: the comparison would be BASELINE INVALID; the baseline differs on "
            + "; ".join(
                f"{key} (baseline {_short(identity.get(key, 'absent'))}, "
                f"this gate {_short(expected.get(key))})"
                for key in differences
            )
        ]
    runs = payload.get("seededRuns") if isinstance(payload, dict) else None
    lines = [
        "preflight: the baseline identity matches on "
        + ", ".join(known) + "; models, corpus and evidence versions are checked after the run"
    ]
    if not isinstance(runs, list) or len(runs) < MINIMUM_POOLED_RUNS:
        lines.append(
            f"preflight: note: the baseline pools {len(runs) if isinstance(runs, list) else 0} seeded run(s); "
            f"at least {MINIMUM_POOLED_RUNS} give it a between-run threshold"
        )
    return 0, lines


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


def _cell_label(cell_key):
    mode, model_id, state, bucket = cell_key
    return f"{mode}/{short_model(model_id)}/{state}/{bucket}"


def _fmt_value(value):
    if isinstance(value, float):
        return f"{value:.4g}" if abs(value) < 10 else f"{value:.1f}"
    return "-" if value is None else str(value)


def print_threshold_floors(threshold):
    floors = ", ".join(
        f"{metric} {METRIC_THRESHOLD_FLOORS.get(metric, threshold):.0%}"
        for metric, _direction, _mad in COMPARED_METRICS
    )
    print(
        f"threshold floors: {floors}; each widens to 3 MADs of the baseline takes (n >= 3) "
        f"or to the range of a pooled baseline's runs (>= {MINIMUM_POOLED_RUNS} runs)"
    )


def print_comparison(details, threshold):
    """Print every judged (cell, metric) with the threshold that decided it."""
    print_threshold_floors(threshold)
    header = (
        f"{'cell':<36} {'metric':<18} {'baseline':>10} {'current':>10} "
        f"{'delta':>8} {'threshold':>9}  basis"
    )
    print(header)
    print("-" * len(header))
    for row in details:
        label = _cell_label(row["cellKey"])
        if not row.get("judged"):
            print(f"{label:<36} {row['metric']:<18} {'-':>10} {'-':>10} {'-':>8} {'-':>9}  not judged: {row['reason']}")
            continue
        flag = "  REGRESSION" if row["regression"] else ""
        print(
            f"{label:<36} {row['metric']:<18} {_fmt_value(row['baseline']):>10} "
            f"{_fmt_value(row['current']):>10} {row['delta']:>+8.2%} {row['threshold']:>9.2%}  "
            f"{row['basis']}{flag}"
        )


def pooled_threshold_rows(cells, threshold, states=None):
    """The thresholds a (pooled) baseline implies for each compared metric."""
    rows = []
    for cell in cells:
        if states is not None and cell["cellKey"][2] not in set(states):
            continue
        for metric, _direction, mad_key in COMPARED_METRICS:
            if cell.get(metric) is None:
                continue
            limit, basis = metric_threshold(cell, metric, threshold, mad_key)
            rows.append({
                "cellKey": list(cell["cellKey"]), "metric": metric, "value": cell[metric],
                "threshold": limit, "basis": basis,
                "runSpread": (cell.get("runSpread") or {}).get(metric),
            })
    return rows


def determinism_report(evidence_payload, current, baseline=None, states=None):
    """Whether seeded takes agreed on their token counts, and with the baseline.

    Seeded takes are token-exact (request-local sampling), so differing counts
    inside one seeded cell mean the sampling was not reproducible; a count that
    differs from the baseline means the engine's output changed. Both are
    reported, never a performance verdict: a legitimate engine change alters
    tokens.
    """
    history = (evidence_payload or {}).get("historyRecord") or {}
    seeds = {
        take.get("seed") for take in history.get("takes") or [] if isinstance(take, dict)
    }
    seeded = bool(seeds) and None not in seeds and len(seeds) == 1
    report = {"seed": next(iter(seeds)) if seeded else None, "cells": []}
    baseline_by_key = {tuple(cell["cellKey"]): cell for cell in baseline or []}
    for cell in current:
        key = tuple(cell["cellKey"])
        if states is not None and key[2] not in set(states):
            continue
        counts = [count for count in cell.get("generatedTokenCounts") or [] if count is not None]
        entry = {
            "cellKey": list(key),
            "generatedTokenCounts": counts,
            "consistent": len(set(counts)) <= 1 if counts else None,
        }
        base = baseline_by_key.get(key)
        if base is not None and base.get("generatedTokens") is not None and cell.get("generatedTokens") is not None:
            entry["baselineGeneratedTokens"] = base["generatedTokens"]
            entry["engineOutputChanged"] = base["generatedTokens"] != cell["generatedTokens"]
        report["cells"].append(entry)
    return report


def print_determinism(report):
    for entry in report["cells"]:
        label = _cell_label(entry["cellKey"])
        counts = entry["generatedTokenCounts"]
        if report["seed"] is not None and entry["consistent"] is False:
            print(
                f"WARNING: {label}: seeded takes disagree on generatedTokens {counts}; "
                "sampling was not reproducible (informational, no verdict)"
            )
        if entry.get("engineOutputChanged"):
            print(
                f"note: {label}: engine output changed (generatedTokens baseline "
                f"{entry['baselineGeneratedTokens']:g}, current {counts}); informational, no verdict"
            )


def write_verdict(path, payload):
    if not path:
        return
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    temporary = f"{path}.tmp.{os.getpid()}"
    with open(temporary, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, default=list)
        stream.write("\n")
    os.replace(temporary, path)


def print_merged_table(merged_runs):
    """Print cross-layer first-chunk latency table from generations-merged.jsonl."""
    if not merged_runs:
        return
    header = (
        f"{'generationID':<16} {'appTTFCMS':>11} "
        f"{'engineFirstChunkMS':>20} "
        f"{'frontendOverheadMS':>18}"
    )
    print("\nCross-layer first-chunk latency (ms)\n")
    print(header)
    print("-" * len(header))
    for run in merged_runs:
        print(
            f"{run['generationID']:<16} {fmt(run['appTTFCMS'], 0):>11} "
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
        "--require-baseline-identity",
        action="store_true",
        help="reject legacy baselines and require exact optimization/topology identity",
    )
    parser.add_argument(
        "--baseline-migrations",
        metavar="PATH",
        default=os.path.join(os.path.dirname(__file__), "..", "config", "benchmark-baseline-migrations.json"),
        help="reviewed schema-v1 cell-key migration contract",
    )
    parser.add_argument("--regress-threshold", type=float, default=0.05,
                        help="relative delta threshold for regression (default 0.05)")
    parser.add_argument("--compare-states", metavar="STATE[,STATE]",
                        help="restrict the baseline verdict to these warm states (e.g. warm); "
                             "other cells are informational")
    parser.add_argument(
        "--seed-baseline", metavar="PATH",
        help="governed seed: add this run to the pooled baseline at PATH when its evidence is "
             "complete, its source is a clean commit, the host was quiet and every judged cell has "
             "at least --seed-minimum-takes takes (exit 3 on a busy host, 1 on any other refusal)",
    )
    parser.add_argument("--seed-minimum-takes", type=int, default=3,
                        help="takes every judged cell needs before it may seed (default 3)")
    parser.add_argument("--verdict-json", metavar="PATH",
                        help="write the comparison or seed verdict, the baseline digest and every "
                             "threshold used to PATH")
    parser.add_argument(
        "--preflight-baseline", metavar="PATH",
        help="predict, from --expected-identity and without telemetry, whether the gate bench "
             "can compare against (or, with --seeding, seed into) the baseline at PATH",
    )
    parser.add_argument("--expected-identity", metavar="PATH",
                        help="partial evidence from publish_benchmark_history.py expected-identity")
    parser.add_argument("--seeding", action="store_true",
                        help="with --preflight-baseline: the run will seed rather than compare")
    args = parser.parse_args()
    if args.preflight_baseline:
        if not args.expected_identity:
            parser.error("--preflight-baseline requires --expected-identity")
        try:
            with open(args.expected_identity, "r", encoding="utf-8") as stream:
                expected_payload = json.load(stream)
        except (OSError, json.JSONDecodeError) as error:
            print(f"preflight: the expected identity is unreadable: {error}")
            return 1
        status, lines = preflight_baseline(
            args.preflight_baseline, expected_payload, seeding=args.seeding,
        )
        for line in lines:
            print(line)
        return status
    diag_dir = args.diag_dir
    generation_ids = None
    cell_by_id = None
    selected_run_id = args.run_id
    strict_selection = bool(args.run_id or args.evidence_manifest)
    evidence_payload = None
    try:
        if args.evidence_manifest:
            evidence_payload, selected_run_id, generation_ids, cell_by_id = load_evidence_selection(
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

    if args.save_baseline or args.seed_baseline or args.compare_baseline:
        forced = forced_memory_class_rows(runs)
        if forced:
            print(
                f"FAIL: {len(forced)} selected row(s) ran under a forced or emulated memory class "
                "(QWENVOICE_FORCE_MEMORY_CLASS, QWENVOICE_SIMULATED_PHYSICAL_MEMORY_GB); "
                "a regression baseline is never saved, "
                "seeded from or compared with forced rows."
            )
            return 1

    if args.save_baseline:
        # Ungoverned save for ad-hoc local comparison; the gate seeds through
        # --seed-baseline, which adds the host, source and take-count checks.
        # The whole document is built before the target is touched, and it is
        # written atomically: a refused identity leaves an existing (possibly
        # committed) baseline intact.
        try:
            document = baseline_document(build_summary(cells), evidence_payload)
            jsonio.atomic_json(
                Path(args.save_baseline), document, mkdir=False, encoder=baseline_bytes,
            )
        except (OSError, ValueError) as error:
            print(f"FAIL: cannot save the baseline: {error}")
            return 1

    stamp = f"{today_str()} · {git_short_sha()}"
    if args.label:
        stamp += f" · {args.label}"
    print(f"\n[{stamp}]")

    variance_cols = ""
    if args.show_variance:
        variance_cols = f" {'RTF_IQR':>7} {'physFoot_IQR':>12}"
    header = (
        f"{'mode':<8} {'model':<26} {'state':<5} {'len':<6} {'n':>2} "
        f"{'RTF':>6} {'xRT':>6} {'tok/s':>7} {'TTFC ms':>8} {'decode ms':>9} "
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
    print("RTF = request wall ÷ audio (lower is faster); xRT = decode-loop speedup (audio ÷ decode s, higher is faster)")
    print(f"tier: {', '.join(tiers)}"
          + ("   ⚠ forced or emulated (QWENVOICE_FORCE_MEMORY_CLASS, "
             "QWENVOICE_SIMULATED_PHYSICAL_MEMORY_GB)" if forced else "")
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
            f"{fmt(summary.get('decodeSpeedupX')):>6} "
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
            f"{'RTF':>6} {'xRT':>6} {'tok/s':>7} {'decode ms':>9} {'physFoot':>8} {'QC':<12}"
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
                f"{fmt(summary.get('decodeSpeedupX')):>6} "
                f"{fmt(summary['tokps']):>7} "
                f"{fmt(summary['decodeLoopMS'], 0):>9} "
                f"{fmt(summary['physFootMB'], 0):>8} "
                f"{cell_qc(summary):<12}"
            )
            if has_prosody:
                p = prosody_for_delivery(prosody_rows, mode, model_id, delivery)
                if p:
                    effect = "-" if p["effect"] is None else f"{p['effect']:+.2f}"
                    base += (
                        f" {p['n']:>5} {effect:>8} {p['dF0Std']:>+7.2f} "
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
        f"{'talker':>7} {'sampCB0':>7} {'codePred':>8} {'code2wav':>8} {'stepEval':>8} "
        f"{'tokRead':>7} {'other':>7}"
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
            f"{fmt(dec.get('tokRead'), 0):>7} "
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
        "stepEval = qwen_stream_step_eval_total · tokRead = qwen_stream_step_token_read_total "
        "(the step's GPU wait under the pipelined policy) · other = remainder (codec-embedding "
        "assembly + EOS read + audio-chunk eval + unattributed). Named + other ≈ decode ms."
    )
    print(
        "⚠ These are Swift-side wall-clock timers around LAZY MLX ops, not per-stage GPU "
        "compute. talker/codePred measure graph-BUILD time; the fused compute of "
        "Talker+CodePredictor+sampling lands in stepEval under a synchronous eval and in "
        "tokRead under the default pipelined policy. code2wav≈0 because the "
        "decoder is asyncEval'd (Phase 2c) and overlaps the token loop — pipelined, not free. "
        "To attribute compute per stage, capture the os_signpost intervals (Talker Forward / "
        "Code Predictor Loop / Step Eval Flush / Token Read / Audio Decoder) under Instruments "
        "xctrace."
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
            "Delivery prosody: prosEff = paired prosody effect (pairedProsodyEffect): the "
            "weighted instructed-minus-neutral deltas (+F0 dynamics +rate variability -pauses "
            "+roughness); '-' for a sidecar that predates it. Requires `vocello bench --delivery`."
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

    compare_states = None
    if args.compare_states:
        compare_states = tuple(s for s in args.compare_states.split(",") if s)

    if args.seed_baseline:
        return seed_baseline_command(args, cells, evidence_payload, compare_states)

    if args.compare_baseline:
        return compare_baseline_command(args, cells, evidence_payload, compare_states, selected_run_id)

    return 0


def seed_baseline_command(args, cells, evidence_payload, compare_states):
    """Governed seed of a pooled baseline from this run (exit 0/1/3)."""
    current = build_summary(cells)
    verdict = {
        "schemaVersion": 1,
        "mode": "seed",
        "runID": (evidence_payload or {}).get("runID"),
        "baseline": {"file": os.path.basename(args.seed_baseline)},
        "states": list(compare_states) if compare_states else None,
        "flatThreshold": args.regress_threshold,
        "thresholdFloors": dict(METRIC_THRESHOLD_FLOORS),
        "hostLoad": host_load_verdict(evidence_payload, states=compare_states),
        "determinism": determinism_report(evidence_payload, current, states=compare_states),
    }
    print_determinism(verdict["determinism"])
    try:
        document, run_count, replaced = seed_baseline(
            args.seed_baseline, current, evidence_payload,
            states=compare_states, minimum_takes=args.seed_minimum_takes,
        )
    except SeedRefused as error:
        verdict["verdict"] = "inconclusive" if error.inconclusive else "refused"
        verdict["reason"] = str(error)
        write_verdict(args.verdict_json, verdict)
        label = "INCONCLUSIVE" if error.inconclusive else "FAIL"
        print(f"\n{label}: this run cannot seed the baseline: {error}. Nothing was written.")
        return 3 if error.inconclusive else 1
    except ValueError as error:
        verdict["verdict"] = "refused"
        verdict["reason"] = str(error)
        write_verdict(args.verdict_json, verdict)
        print(f"\nFAIL: this run cannot seed the baseline: {error}. Nothing was written.")
        return 1
    with open(args.seed_baseline, "rb") as stream:
        digest = hashlib.sha256(stream.read()).hexdigest()
    rows = pooled_threshold_rows(document["cells"], args.regress_threshold, compare_states)
    verdict.update({
        "verdict": "seeded",
        "baseline": {
            "file": os.path.basename(args.seed_baseline), "sha256": digest,
            "seededRuns": run_count, "replacedPrevious": replaced,
            "sourceCommits": sorted({run.get("sourceCommit") for run in document.get("seededRuns") or []}),
        },
        "thresholds": rows,
    })
    write_verdict(args.verdict_json, verdict)
    prefix = "a new baseline (the previous file had another identity or source commit)" if replaced else "the baseline"
    print(
        f"\nBASELINE SEEDED: {prefix} now pools {run_count} run(s) from commit "
        f"{str(document['seededRuns'][0].get('sourceCommit'))[:12]}"
        + ("" if run_count >= MINIMUM_POOLED_RUNS
           else f"; seed at least {MINIMUM_POOLED_RUNS} before promoting it")
    )
    print_threshold_floors(args.regress_threshold)
    for row in rows:
        spread = row["runSpread"]
        spread_text = "-" if spread is None else f"{spread:.2%}"
        print(
            f"  {_cell_label(row['cellKey']):<36} {row['metric']:<18} {_fmt_value(row['value']):>10}  "
            f"between-run range {spread_text:>7}  threshold {row['threshold']:.2%} ({row['basis']})"
        )
    return 0


def compare_baseline_command(args, cells, evidence_payload, compare_states, selected_run_id):
    """Compare this run with a saved baseline (exit 0 pass, 1 invalid, 2 regression, 3 inconclusive)."""
    verdict = {
        "schemaVersion": 1,
        "mode": "compare",
        "runID": selected_run_id or None,
        "baseline": {"file": os.path.basename(args.compare_baseline)},
        "states": list(compare_states) if compare_states else None,
        "flatThreshold": args.regress_threshold,
        "thresholdFloors": dict(METRIC_THRESHOLD_FLOORS),
    }
    try:
        with open(args.compare_baseline, "rb") as f:
            raw = f.read()
        verdict["baseline"]["sha256"] = hashlib.sha256(raw).hexdigest()
        baseline_payload = json.loads(raw)
        if isinstance(baseline_payload, dict):
            runs = baseline_payload.get("seededRuns")
            verdict["baseline"]["seededRuns"] = len(runs) if isinstance(runs, list) else 0
        migrations = load_baseline_migrations(args.baseline_migrations)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        verdict.update({"verdict": "baselineInvalid", "reason": str(error)})
        write_verdict(args.verdict_json, verdict)
        print(f"FAIL: baseline comparison contract is invalid: {error}")
        return 1
    # The host verdict comes first: a loaded run says nothing about the engine,
    # whatever the baseline's identity (audit V-7). An identity problem found
    # alongside is still printed so the rerun does not discover it next.
    identity_error = None
    baseline = None
    try:
        # Derived only when the baseline has an identity to compare: an ad-hoc
        # or legacy baseline compares evidence that predates the host identity.
        current_identity = (
            functools.partial(baseline_identity_from_evidence, evidence_payload)
            if evidence_payload is not None
            else None
        )
        baseline = baseline_cells(
            baseline_payload,
            current_identity=current_identity,
            require_identity=args.require_baseline_identity,
        )
    except ValueError as error:
        identity_error = error
    current = build_summary(cells)
    load_reasons = host_load_verdict(evidence_payload, states=compare_states)
    verdict["hostLoad"] = load_reasons
    verdict["determinism"] = determinism_report(
        evidence_payload, current, baseline if identity_error is None else None, compare_states,
    )
    if load_reasons:
        verdict["verdict"] = "inconclusive"
        if identity_error is not None:
            verdict["identityError"] = str(identity_error)
        write_verdict(args.verdict_json, verdict)
        print(
            "\nINCONCLUSIVE: the host was not quiet during this run ("
            + "; ".join(load_reasons)
            + "); no regression verdict. Rerun on an idle, cool machine."
        )
        if identity_error is not None:
            print(f"note: the baseline would not have compared either: {identity_error}")
        return 3
    if identity_error is not None:
        verdict.update({"verdict": "baselineInvalid", "reason": str(identity_error)})
        write_verdict(args.verdict_json, verdict)
        print(f"FAIL: baseline comparison contract is invalid: {identity_error}")
        return 1
    if baseline_lacks_host_identity(baseline_payload):
        print(
            "\nnote: legacy baseline has no OS/Xcode identity; "
            "re-save it to bind the comparison to this toolchain."
        )
    if baseline_lacks_device_class(baseline_payload):
        print(
            "\nnote: baseline predates the device-class identity; "
            "re-save it to bind the comparison to this memory tier."
        )
    baseline_definition = baseline_rtf_definition(baseline_payload)
    if baseline_definition != rtf_semantics.STANDARD_RTF_DEFINITION:
        print(
            "\nnote: legacy baseline (pre-2026-09-12) stores the decode-loop speedup under rtf; "
            "comparing it with the current decodeSpeedupX. Re-save the baseline to compare "
            "standard RTF (wall/audio)."
        )
    if compare_states:
        print(f"\n(verdict on {', '.join(compare_states)} cells only; other cells are informational)")
    details = []
    try:
        regressions = compare_summaries(
            baseline, current, threshold=args.regress_threshold, migrations=migrations,
            baseline_definition=baseline_definition, states=compare_states, details=details,
        )
    except ValueError as error:
        verdict.update({"verdict": "baselineInvalid", "reason": str(error)})
        write_verdict(args.verdict_json, verdict)
        print(f"FAIL: baseline comparison contract is invalid: {error}")
        return 1
    print()
    print_comparison(details, args.regress_threshold)
    print_determinism(verdict["determinism"])
    print_regressions(regressions)
    verdict.update({
        "verdict": "regression" if regressions else "pass",
        "comparisons": details,
        "regressions": [
            {**entry, "cellKey": list(entry["cellKey"])} for entry in regressions
        ],
    })
    write_verdict(args.verdict_json, verdict)
    return 2 if regressions else 0


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
