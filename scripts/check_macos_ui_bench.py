#!/usr/bin/env python3
"""Gate one macOS UI benchmark (in-process engine, app + engine telemetry) and emit exact, run-scoped evidence."""

from __future__ import annotations

import argparse
import base64
import binascii
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
from typing import TypeGuard
import sys
import tempfile

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from lib import rtf as rtf_semantics  # noqa: E402
from lib import playback_capture
from lib.build_provenance import ProvenanceError, load_build_provenance  # noqa: E402
from lib.audio_qc import (  # noqa: E402
    SUCCESS_FINISH,
    AudioQCError,
    audio_qc_failure,
    qc_algorithm_version,
    qc_metrics as shared_qc_metrics,
    quality_identity_fields,
    raw_audio_qc,
)
from lib.audio_qc import history_record_schema_version as shared_record_schema_version  # noqa: E402

from benchmark_memory import (  # noqa: E402
    MemoryEvidenceError,
    REQUIRED_TELEMETRY_SCHEMA,
    qualify_memory_rows,
)
from lib import jsonio  # noqa: E402
from lib import bench_seed  # noqa: E402
from lib import ui_bench_matrix  # noqa: E402

DEFAULT_MODES = ["custom", "design", "clone"]
DEFAULT_LENGTHS = ["short", "medium", "long"]
DEFAULT_WARM = 3
# The canonical UI benchmark measures the Speed variant; the tier's own
# recommendation (Quality first on the M6) must never leak into its numbers.
DEFAULT_VARIANT = "speed"
MODEL_VARIANTS = ("speed", "quality", "compact_speed", "compact_quality")
# The stall gate's statistic, limit and calibration profile (audit #6).
DEFAULT_STALL_CONTRACT = SCRIPT_DIR.parent / "config" / "macos-ui-stall-gate.json"
# Each gateable statistic and where an app row carries it: the typed v8
# frontend key, its deprecated frontend alias, then the raw watchdog counter.
STALL_STATISTICS = {
    "maximumDelayedHeartbeatMS": ("maximumDelayedHeartbeatMS", "mainThreadMaximumStallMS", "uiMaxStallMS"),
    "delayedHeartbeatCount250": ("delayedHeartbeatCount250", "mainThreadStallCount250MS", "uiStallCount250"),
    "delayedHeartbeatCount50": ("delayedHeartbeatCount50", "mainThreadStallCount50MS", "uiStallCount50"),
}
# The run-level code a report-only (provisional) stall contract leaves on a
# tracked record whose takes exceed its limit: `(<takes above>/<gated takes>)`.
STALL_REPORT_ONLY_WARNING = "stall.provisional.wouldfail"
# The record's cell aggregate (benchmark_history.CELL_AGGREGATE_VERSIONS): the
# take after a cold take stays out of its cell's statistics, and an IQR needs
# four takes (audit #30).
CELL_AGGREGATE_VERSION = 2
# Some rows or layer files are not there yet (sysexits EX_TEMPFAIL). The lane
# retries only this outcome, briefly; every other failure is deterministic.
ROWS_NOT_YET_PRESENT_EXIT = 75
# A take the mandatory audio check refused (RF-61, audit T5, decision D-5 of
# 2026-11-15). The XCUITest prints one marker per failed take and goes on:
# `VOCELLO_BENCH_TAKE_REFUSED=<base64 of UTF-8 JSON {"cell", "schemaVersion": 1,
# "takeIndex"}>`. The runner cannot tell a refusal from any other failed
# generation, so the marker alone proves nothing: the take's engine row must
# show the audio check's refusal (`audio_qc_refusal`).
REFUSED_MARKER = "VOCELLO_BENCH_TAKE_REFUSED="
REFUSED_MARKER_RE = re.compile(r"VOCELLO_BENCH_TAKE_REFUSED=([A-Za-z0-9+/=]+)")
REFUSED_MARKER_SCHEMA_VERSION = 1
# NativeRuntimeFailureCode.audioQualityRejected, which a failure row stamps in
# `notes.nativeRuntimeFailureCode` (with the flags in `notes.audioQCFlags`).
AUDIO_QC_REFUSAL_CODE = "audio.quality_rejected"
# Refused takes a run may record before the lane fails as a product failure.
DEFAULT_MAX_REFUSED_TAKES = 1
# The run-level code a record with refused takes carries: `(<refused>/<matrix takes>)`.
REFUSED_TAKES_WARNING = "takes.refused"
# `evidence.refusedTakeRule` (benchmark_history.REFUSED_TAKE_RULE): the record
# keeps the takes that completed, is exploratory and is never canonical.
REFUSED_TAKE_RULE = "recorded-exploratory-v1"
THERMAL_RANK = {"unknown": -1, "nominal": 0, "fair": 1, "serious": 2, "critical": 3}
TRIM_SEVERITY = {"softTrim": 1, "hardTrim": 2, "fullUnload": 3}
# NativeDeviceMemoryClass Mac tiers. Engine rows stamp `notes.deviceClass` with
# the raw value (`floor_8gb_mac`); older fixtures and docs use the case name.
MAC_DEVICE_CLASSES = {
    "floor8GBMac": "floor8GBMac", "floor_8gb_mac": "floor8GBMac",
    "mid16GBMac": "mid16GBMac", "mid_16gb_mac": "mid16GBMac",
    "highMemoryMac": "highMemoryMac", "high_memory_mac": "highMemoryMac",
}


def stall_gate_applies(notes: dict) -> bool:
    """Whether the main-thread stall gate covers one engine row.

    The 8 GB floor tier is always gated, forced or native, as before. Every
    other Mac tier (the canonical Mac mini M6 runs `mid16GBMac`) is gated when
    it is the host's native tier; a forced tier is a diagnostic simulation.
    What the gate measures and allows lives in `config/macos-ui-stall-gate.json`.
    """
    device = MAC_DEVICE_CLASSES.get(str(notes.get("deviceClass") or ""))
    if device is None:
        return False
    if device == "floor8GBMac":
        return True
    return str(notes.get("deviceClassForced", "false")).lower() != "true"


def stall_gate_exempt(notes: dict) -> bool:
    """Whether a take the gate does not cover is left out by design: a forced
    non-floor tier, a diagnostic simulation whose record is exploratory. A row
    with no Mac device class is not exempt, only unjudged, and a calibrated
    contract fails a run that holds one (RF-61, audit T6)."""
    return not stall_gate_applies(notes) and str(notes.get("deviceClass") or "") in MAC_DEVICE_CLASSES


def takes_above_load_limit(history_takes: list[dict]) -> list[tuple[int, float]]:
    """(takeIndex, load) of every take whose own one-minute load exceeded the
    stricter per-take limit (maintainer decision 2026-09-25, audit #28): the
    publisher's rule for engine records, applied to the macOS UI benchmark on
    the canonical profile's core count. Such a run's record is exploratory."""
    import publish_benchmark_history as publisher

    cores = int(publisher.canonical_hardware_profile("macos")["cpuCores"])
    return publisher.takes_above_exploratory_load(history_takes, cores)


def diagnostic_memory_tier(rows: list[dict]) -> bool:
    """Whether any engine row ran a forced memory class or an emulated smaller
    Mac (QWENVOICE_SIMULATED_PHYSICAL_MEMORY_GB, audit #11 option b).

    Such a run changes policy values, not the hardware: its record publishes
    only as exploratory evidence, never canonical and never comparable."""
    for row in rows:
        notes = row.get("notes") or {}
        if str(notes.get("deviceClassForced", "false")).lower() == "true":
            return True
        if notes.get("simulatedPhysicalMemoryMB"):
            return True
    return False


def armed_runtime_overrides(rows: list[dict]) -> list[str]:
    """The engine publisher's armed-override rule (BKL-22), on this run's rows."""
    import publish_benchmark_history as publisher

    try:
        return publisher.armed_runtime_overrides(rows)
    except publisher.PublicationError as error:
        raise SystemExit(str(error)) from error


def run_runtime_policy(rows: list[dict]) -> dict | None:
    """The record's memory-tier provenance, `run.runtimePolicy` (audit #19).

    The engine publisher's block, reused so a forced tier or an emulated
    smaller Mac (audit #11) names itself on the tracked UI record, not only in
    untracked telemetry. Rows that predate the stamp yield None; a partly
    stamped, mixed-tier or mixed-emulation selection raises ValueError."""
    import publish_benchmark_history as publisher

    try:
        return publisher.runtime_policy_provenance(rows)
    except publisher.PublicationError as error:
        raise ValueError(str(error)) from error


def read_refused_markers(log_path: Path | None, cells: list[str]) -> tuple[dict[int, str], list[str]]:
    """The takes the runner marked refused, {1-based take index: cell}, and failures.

    A marker that is not base64 JSON of the declared shape, or that names a take
    or a cell the selected matrix does not hold, is a failure: the run's own
    account of itself cannot be trusted. A repeated identical marker is one marker.
    """
    if log_path is None:
        return {}, []
    try:
        text = Path(log_path).read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        return {}, [f"unreadable xcodebuild log {log_path}: {type(error).__name__}"]
    markers: dict[int, str] = {}
    failures: list[str] = []
    for line in text.splitlines():
        if REFUSED_MARKER not in line:
            continue
        matches = REFUSED_MARKER_RE.findall(line)
        if not matches:
            failures.append("a refused-take marker carries no base64 payload")
        for encoded in matches:
            try:
                marker = json.loads(base64.b64decode(encoded, validate=True).decode("utf-8"))
            except (binascii.Error, UnicodeDecodeError, ValueError) as error:
                failures.append(f"a refused-take marker is not base64 JSON: {type(error).__name__}")
                continue
            index = marker.get("takeIndex") if isinstance(marker, dict) else None
            cell = marker.get("cell") if isinstance(marker, dict) else None
            if (
                not isinstance(marker, dict)
                or marker.get("schemaVersion") != REFUSED_MARKER_SCHEMA_VERSION
                or isinstance(index, bool) or not isinstance(index, int)
                or not isinstance(cell, str)
            ):
                failures.append(
                    'a refused-take marker is not {"cell", "schemaVersion": '
                    f'{REFUSED_MARKER_SCHEMA_VERSION}, "takeIndex"}}'
                )
                continue
            if not 1 <= index <= len(cells):
                failures.append(
                    f"a refused-take marker names take {index} ({cell!r}), outside the matrix's 1..{len(cells)}"
                )
                continue
            if cell != cells[index - 1]:
                failures.append(
                    f"a refused-take marker names take {index} as {cell!r}; the matrix runs "
                    f"{cells[index - 1]!r} there"
                )
                continue
            markers[index] = cell
    return markers, failures


def audio_qc_refusal(row: dict) -> list[str] | None:
    """The flags of the mandatory audio check's refusal, or None when the engine
    row shows none.

    A refused take ends `failed` and names the refusal one of two ways: the
    engine's failure code `audio.quality_rejected` in its notes (a take stopped
    mid-stream for runaway trailing silence carries only this, with the flags
    in `notes.audioQCFlags`), or an `audioQC` report whose verdict is `fail`
    (the final check). Any other failed generation returns None."""
    if str(row.get("finishReason")).lower() != "failed":
        return None
    notes = row.get("notes")
    if not isinstance(notes, dict):
        notes = {}
    qc = raw_audio_qc(row)
    flags = [flag for flag in qc.get("flags") or [] if isinstance(flag, str)]
    if qc.get("verdict") == "fail":
        return flags
    if notes.get("nativeRuntimeFailureCode") == AUDIO_QC_REFUSAL_CODE:
        noted = notes.get("audioQCFlags")
        return flags or ([noted] if isinstance(noted, str) and noted else [])
    return None


def classify_refused_takes(
    markers: dict[int, str], engine_rows: list[dict],
) -> tuple[dict[int, dict], list[str]]:
    """The marked takes whose engine row proves the refusal, and why the others fail.

    The runner prints its marker for any failed generation, so each marked take
    must have exactly one engine row, naming the same cell, that shows the audio
    check's refusal. A marked take with no engine row, or with a row that failed
    another way or did not fail, stays a failed take."""
    by_index: dict[int, list[dict]] = {}
    for row in engine_rows:
        try:
            index = int(str((row.get("notes") or {}).get("benchTakeIndex")))
        except ValueError:
            continue
        by_index.setdefault(index, []).append(row)
    refused: dict[int, dict] = {}
    failures: list[str] = []
    for index, cell in sorted(markers.items()):
        take = f"take {index} ({cell})"
        rows = by_index.get(index, [])
        if not rows:
            failures.append(
                f"{take} is marked refused but left no engine row; a refusal without its "
                "audio-check evidence is a failed take"
            )
            continue
        if len(rows) > 1:
            failures.append(f"{take} is marked refused and has {len(rows)} engine rows")
            continue
        row = rows[0]
        notes = row.get("notes") or {}
        generation_id = row.get("generationID")
        flags = audio_qc_refusal(row)
        if notes.get("benchCell") != cell:
            failures.append(
                f"{take} is marked refused, but its engine row names cell {notes.get('benchCell')!r}"
            )
        elif flags is None:
            failures.append(
                f"{take} is marked refused, but its engine row does not show the mandatory audio "
                f"check's refusal (finishReason={row.get('finishReason')!r}, "
                f"nativeRuntimeFailureCode={notes.get('nativeRuntimeFailureCode')!r}); "
                "a generation that failed another way is a failed take"
            )
        elif not isinstance(generation_id, str) or not generation_id:
            failures.append(f"{take} is marked refused, but its engine row has no generationID")
        else:
            refused[index] = {"cell": cell, "generationID": generation_id, "flags": flags}
    return refused, failures


def refused_cells(refused: dict[int, dict]) -> list[dict]:
    """`refusedCells`: each refused take's index and cell, in take order."""
    return [{"takeIndex": index, "cell": refused[index]["cell"]} for index in sorted(refused)]


def refused_takes_line(refused: dict[int, dict]) -> str:
    """The lane's one-line account of its refused takes."""
    listed = ", ".join(f"take {index} ({refused[index]['cell']})" for index in sorted(refused))
    return f"REFUSED {len(refused)} take(s): {listed}"


def take_seed(notes: dict) -> tuple[int | None, str | None]:
    """The take's effective sampling seed and its source from the engine's
    receipt (`samplingSeed`, `samplingSeedSource`: requested or generated)."""
    raw = notes.get("samplingSeed")
    source = notes.get("samplingSeedSource")
    try:
        seed = int(str(raw))
    except (TypeError, ValueError):
        return None, source if isinstance(source, str) else None
    if not 0 <= seed <= (1 << 64) - 1:
        return None, source if isinstance(source, str) else None
    return seed, source if isinstance(source, str) else None


class StallContractError(ValueError):
    pass


def load_stall_contract(path: Path) -> dict:
    """The stall gate's declared statistic, limit and calibration profile (audit #6).

    The status decides whether the limit gates (maintainer decision 2026-09-25):
    a provisional contract reports only, recording every gated take's value and
    whether the run would fail, and never fails a run; a calibrated contract,
    which must name the run IDs that calibrated it, fails a run above its limit.
    """
    try:
        contract = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StallContractError(f"unreadable stall contract {path}: {error}") from None
    if not isinstance(contract, dict) or contract.get("schemaVersion") != 1:
        raise StallContractError(f"unsupported stall contract: {path}")
    if contract.get("statistic") not in STALL_STATISTICS:
        raise StallContractError(
            f"stall contract statistic must be one of {', '.join(sorted(STALL_STATISTICS))}: {path}"
        )
    limit = contract.get("maximumAllowed")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        raise StallContractError(f"stall contract maximumAllowed must be a non-negative integer: {path}")
    for key in ("policyID", "calibrationProfile", "definition"):
        if not isinstance(contract.get(key), str) or not contract[key].strip():
            raise StallContractError(f"stall contract needs a {key}: {path}")
    runs = contract.get("calibrationRuns")
    if not isinstance(runs, list) or not all(isinstance(run, str) and run for run in runs):
        raise StallContractError(f"stall contract calibrationRuns must list run IDs: {path}")
    status = contract.get("calibrationStatus")
    if status not in {"provisional", "calibrated"}:
        raise StallContractError(f"stall contract calibrationStatus must be provisional or calibrated: {path}")
    if status == "calibrated" and not runs:
        raise StallContractError(f"a calibrated stall contract names the runs that calibrated it: {path}")
    return contract


def stall_contract_enforced(contract: dict) -> bool:
    """Whether the contract's limit fails a run: only once it is calibrated."""
    return contract["calibrationStatus"] == "calibrated" and bool(contract["calibrationRuns"])


def stall_report_warning(stall_gate: dict) -> str | None:
    """The tracked record's run warning for a report-only limit the run exceeded."""
    if stall_gate.get("enforced") or not stall_gate.get("wouldFail"):
        return None
    return f"{STALL_REPORT_ONLY_WARNING}({stall_gate['takesAboveLimit']}/{stall_gate['gatedTakeCount']})"


def stall_statistic_value(app_row: dict, statistic: str):
    """The row's value for the contract's statistic, or None when it carries none."""
    frontend = app_row.get("frontendMetrics") or {}
    counters = app_row.get("counters") or {}
    typed, alias, counter = STALL_STATISTICS[statistic]
    for value in (frontend.get(typed), frontend.get(alias), counters.get(counter)):
        if value is not None:
            return value
    return None


def stall_gate_summary(
    contract: dict, observed: list[tuple[str, int]], censored: int,
    *, expected: int | None = None, exempt: int = 0, refused: int = 0,
) -> dict:
    """What the gate saw, for calibration: the per-take distribution of the statistic.

    `observed` is each gated take's (cell, value) in take order; `takes` keeps
    them all, because calibrating the contract needs the whole distribution.
    `expected` is the selected matrix's take count and `exempt` the forced-tier
    diagnostic takes among them; `coversMatrix` says every other take was gated.
    A take the audio check `refused` is outside the gate: `expected` counts only
    the takes that completed, and the summary names how many were refused.
    """
    values = sorted(value for _, value in observed)

    def quantile(fraction: float):
        if not values:
            return None
        return values[min(len(values) - 1, int(round(fraction * (len(values) - 1))))]

    limit = contract["maximumAllowed"]
    above = sum(1 for value in values if value > limit)
    return {
        "policyID": contract["policyID"],
        "statistic": contract["statistic"],
        "maximumAllowed": limit,
        "calibrationProfile": contract["calibrationProfile"],
        "calibrationStatus": contract["calibrationStatus"],
        # A provisional limit reports only; `wouldFail` is what it would decide.
        "enforced": stall_contract_enforced(contract),
        "wouldFail": above > 0,
        "gatedTakeCount": len(values),
        # The gate cannot pass empty (audit T6): what the matrix owed it.
        **({
            "expectedTakeCount": expected, "exemptTakeCount": exempt,
            "coversMatrix": len(values) + exempt >= expected,
        } if expected is not None else {}),
        **({"refusedTakeCount": refused} if refused else {}),
        "takesAboveLimit": above,
        "median": quantile(0.5),
        "p90": quantile(0.9),
        "maximum": values[-1] if values else None,
        "censoredHeartbeatCount": censored,
        "takes": [{"cell": cell, "value": value} for cell, value in observed],
    }


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


def canonical_macos_profile_id() -> str:
    """The registry's canonical macOS profile ID (a registry lookup, no live probe).

    `scripts/ui_test.sh` proves the live host matches this profile through
    `publish_benchmark_history.py verify-hardware` before a benchmark build,
    and the recorder fills the remaining hardware fields from the same profile.
    """
    import publish_benchmark_history as publisher

    return str(publisher.canonical_hardware_profile("macos")["id"])


def run_hardware_context(rows: list[dict], profile_id: str) -> dict:
    environments = [
        (row.get("summary") or {}).get("runEnvironment") or {}
        for row in rows
    ]
    result: dict = {"profileID": profile_id}
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


def expected_cells(
    modes: list[str], lengths: list[str], warm: int, allocation: dict[str, int] | None = None,
) -> list[str]:
    """The ordered take cells, under a declared matrix allocation when given (audit #30)."""
    return ui_bench_matrix.expected_cells(modes, lengths, warm, allocation)


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


def _number(value) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_v7_engine_telemetry(row: dict) -> list[str]:
    generation = row.get("generationID", "?")
    summary = row.get("summary")
    if not isinstance(summary, dict):
        return [f"generation {generation} has no schema-v7 sampler summary"]
    failures: list[str] = []
    if rtf_semantics.engine_rtf(row) is None:
        failures.append(
            f"generation {generation} has no measurable request wall time "
            "(no realTimeFactor and no terminal stage mark)"
        )
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


def playback_health_failures(frontend: dict, max_underruns: int = 0) -> list[str]:
    """Why a take's playback was not continuous (RF-61, audit T4).

    The app counts a continuity failure when a streamed chunk does not follow
    the previous one and an underrun when the player ran out of queued audio.
    Both only had to be non-negative, so the lane that guarantees playback could
    not fail on them. A continuity failure always fails the take; underruns fail
    it above `max_underruns` (`--max-playback-underruns`, default 0). Missing or
    malformed counters are `validate_v7_frontend`'s failure, not repeated here."""
    failures: list[str] = []
    continuity = frontend.get("playbackContinuityFailures")
    if _number(continuity) and continuity > 0:
        failures.append(f"playbackContinuityFailures {continuity:g} > 0")
    underruns = frontend.get("playbackUnderruns")
    if _number(underruns) and underruns > max_underruns:
        failures.append(f"playbackUnderruns {underruns:g} > {max_underruns}")
    return failures


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
        if str(row.get("finishReason")).lower() not in SUCCESS_FINISH:
            failures.append(
                f"{layer} generation {row.get('generationID', '?')} has unsuccessful "
                f"finishReason={row.get('finishReason')!r}"
            )
    return failures


# The take identity both layers stamp from the benchmark's current-take file.
TAKE_IDENTITY_NOTES = ("benchTakeIndex", "benchCell")


def validate_take_identity(engine_rows: list[dict], app_rows: list[dict]) -> list[str]:
    """An app row names the same take as its engine row (audit #74).

    The runner moves the shared current-take file to the next take once a take
    completes; a layer that read it late would stamp the next take. The app
    layer snapshots it at submit, and this check refuses a run where either
    layer's identity still disagrees. A row without a take identity is left to
    the other checks (engine rows must carry one)."""
    failures: list[str] = []
    engine_by_id = {row.get("generationID"): row for row in engine_rows}
    for app_row in app_rows:
        engine_row = engine_by_id.get(app_row.get("generationID"))
        if engine_row is None:
            continue
        app_notes = app_row.get("notes") or {}
        engine_notes = engine_row.get("notes") or {}
        for key in TAKE_IDENTITY_NOTES:
            if key in app_notes and str(app_notes[key]) != str(engine_notes.get(key)):
                failures.append(
                    f"app generation {app_row.get('generationID', '?')} names {key}="
                    f"{app_notes[key]!r}, its engine row {engine_notes.get(key)!r}"
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
        if required_layers != ["app", "engine"]:
            failures.append(
                f"merged generation {row.get('generationID', '?')} has invalid requiredLayers={required_layers!r}"
            )
        if missing_layers != []:
            failures.append(
                f"merged generation {row.get('generationID', '?')} has missingLayers={missing_layers!r}"
            )
        missing = [key for key in ("engine", "app") if not isinstance(row.get(key), dict)]
        if missing:
            failures.append(
                f"merged generation {row.get('generationID', '?')} missing complete layer payloads: "
                f"{', '.join(missing)}"
            )
            continue
        gid = row.get("generationID")
        for key in ("engine", "app"):
            nested_id = row[key].get("generationID")
            if nested_id != gid:
                failures.append(
                    f"merged generation {gid!r} {key}.generationID={nested_id!r} does not match"
                )
    return failures


def validate_process_ownership(
    engine_rows: list[dict],
    app_rows: list[dict],
    merged_rows: list[dict],
    expected_ids: list[str],
) -> list[str]:
    """Prove that the app and engine rows came from the one in-process host."""
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
    app_by_id = indexed(app_rows)
    merged_by_id = indexed(merged_rows)
    for generation_id in expected_ids:
        engine_pid = pid(engine_by_id.get(generation_id), f"engine generation {generation_id}")
        app_pid = pid(app_by_id.get(generation_id), f"app generation {generation_id}")
        # The engine runs inside the app process (since 2026-09-15): both rows
        # must name the same PID, or the evidence came from two different hosts.
        if engine_pid is not None and app_pid is not None and engine_pid != app_pid:
            failures.append(
                f"generation {generation_id} app PID {app_pid} != engine PID {engine_pid}"
            )

        merged = merged_by_id.get(generation_id)
        for key, expected_pid in (("engine", engine_pid), ("app", app_pid)):
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


def matrix_scope(
    modes: list[str], lengths: list[str], warm: int, allocation: dict[str, int] | None = None,
) -> str:
    """Canonical only for the declared canonical matrix of config/ui-bench-matrix.json."""
    return "canonical" if ui_bench_matrix.is_canonical(modes, lengths, warm, allocation) else "focused"


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
    # Standard real-time factor (engine request wall ÷ audio, lower is faster).
    # The decode-loop speedup legacy records called "rtf" keeps its own key, and
    # the app-layer span (adds transport and UI dispatch) is published beside it.
    add("rtf", rtf_semantics.engine_rtf(engine))
    add("requestWallSeconds", rtf_semantics.request_wall_seconds(engine))
    add("decodeSpeedupX", rtf_semantics.decode_speedup(engine))
    add("rtfAppEndToEnd", rtf_semantics.app_end_to_end_rtf(app, rtf_semantics.audio_seconds(engine)))
    # The startup windows the standard RTF leaves out of the request wall.
    for name, value in (rtf_semantics.startup_windows_ms(engine) or {}).items():
        add(name, value)
    for source, destination in (
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
    # The take's own one-minute load average (audit #28); the run's hardware
    # block keeps only the busiest take's.
    add("loadAverage1M", (summary.get("runEnvironment") or {}).get("loadAverage1Minute"))
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
    # Present only on rows whose heartbeat statistics include the censored
    # lower bound of heartbeats still queued at session end (audit #18): its
    # presence marks that definition in the tracked record.
    add("censoredHeartbeatCount", frontend.get("censoredHeartbeatCount"))
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


def app_bundle_from_receipt(executable_relative_path) -> str | None:
    """`.../Vocello.app/Contents/MacOS/Vocello` -> `.../Vocello.app`; None for anything else."""
    if not isinstance(executable_relative_path, str):
        return None
    marker = "/Contents/MacOS/"
    if marker not in executable_relative_path:
        return None
    bundle = executable_relative_path.split(marker)[0]
    return bundle if bundle.endswith(".app") else None


def evaluate_playback_capture(
    take_index: int, cell: str, mode: str, duration_seconds, captures: dict,
    capture_dir: Path | None, outputs_dir: Path | None, playback_scheduled_ms=None,
    submit_epoch_ms=None, *, armed: bool = False,
) -> dict:
    """Played-audio capture evidence for one take (PC-01): fields, metrics, warn codes, summary.

    A lane without a capture directory adds nothing; a lane with one but no sidecar
    for the take marks it unavailable. Comparison metrics exist only when the capture
    aligned with the published WAV. Warnings never fail the lane; `gateFailures` do
    (PC-02): a captured take outside the gate, a silent take, and, when the runner
    `armed` capture, a planned take that did not end captured (RF-61, audit T3).
    """
    empty = {"fields": {}, "metrics": {}, "warnings": [], "summary": None}
    if capture_dir is None:
        return empty
    entry = captures.get((take_index, cell))
    if entry is None:
        gate = playback_capture.gate_failures("unavailable", {}, armed=armed)
        return {"fields": {"playbackCaptureStatus": "unavailable"}, "metrics": {}, "warnings": [],
                "summary": {"takeIndex": take_index, "cell": cell, "status": "unavailable",
                            **({"gateFailures": gate} if gate else {})},
                "gateFailures": gate}
    sidecar = entry["sidecar"]
    reference = None
    # The window opens at the earlier of the click and the tap's arming: on a
    # relaunched app the tap attaches only when the process opens its device,
    # after the take's WAV already carries the generation's timestamp.
    stamps = [v for v in (sidecar.get("submitClickEpochMS"), sidecar.get("captureStartEpochMS"))
              if isinstance(v, (int, float))]
    start = min(stamps) if stamps else None
    if outputs_dir is not None and entry["wav"] is not None and isinstance(start, (int, float)):
        stop = sidecar.get("stopEpochMS")
        if not isinstance(stop, (int, float)):
            stop = float(start) + 600_000.0
        expected = duration_seconds if isinstance(duration_seconds, (int, float)) else None
        reference = playback_capture.resolve_reference_wav(
            Path(outputs_dir), mode, float(start) - 2_000.0, float(stop) + 5_000.0, expected,
        )
    try:
        result = playback_capture.analyze_take(
            sidecar, entry["wav"], reference,
            playback_scheduled_ms if isinstance(playback_scheduled_ms, (int, float)) else None,
            submit_epoch_ms if isinstance(submit_epoch_ms, (int, float)) else None,
        )
    except playback_capture.PlaybackCaptureError as error:
        result = {"status": "aborted", "metrics": {}, "warnings": [], "digest": None, "error": str(error)}
    fields = {"playbackCaptureStatus": result["status"]}
    if result.get("digest"):
        fields["playbackCaptureDigest"] = result["digest"]
    summary = {
        "takeIndex": take_index, "cell": cell, "status": result["status"],
        "reference": reference.name if reference is not None else None,
        "metrics": result["metrics"], "warnings": result["warnings"],
    }
    click = sidecar.get("submitClickEpochMS")
    if isinstance(submit_epoch_ms, (int, float)) and isinstance(click, (int, float)):
        # UI-driver dispatch latency: how long after the runner's click stamp the
        # app actually registered the submit. Diagnostic, never a record metric.
        summary["clickToSubmitMS"] = round(float(submit_epoch_ms) - float(click), 1)
        summary["submitReference"] = "app"
    elif isinstance(click, (int, float)):
        summary["submitReference"] = "runnerClick"
    if result.get("error"):
        summary["error"] = result["error"]
    gate = playback_capture.gate_failures(
        result["status"], result["metrics"], playback_scheduled_ms, armed=armed,
    )
    if gate:
        summary["gateFailures"] = gate
    return {"fields": fields, "metrics": dict(result["metrics"]), "warnings": list(result["warnings"]),
            "summary": summary, "gateFailures": gate}


def starts_session(cells: list[str], position: int) -> bool:
    """Whether the take at 0-based `position` starts a new app session: the first
    take, a cold take, or the first Clone take after another mode
    (`VocelloMacBenchmarkUITests.startsSession`)."""
    if position == 0 or "/cold#" in cells[position]:
        return True
    return cells[position].startswith("clone/") and not cells[position - 1].startswith("clone/")


def capture_plan(cells: list[str]) -> set[int]:
    """The 1-based takes whose played audio the runner captures (audit #31, #74):
    the last warm repetition of each mode and length, never a take that starts a
    session (a relaunched app opens its audio device only at its first playback,
    so the tap would attach mid-take). `VocelloMacBenchmarkUITests.capturesPlayback`
    applies the same plan; every other take stops its playback at completion."""
    last: dict[str, int] = {}
    for position, cell in enumerate(cells):
        if "/warm#" in cell:
            last[cell.rsplit("#", 1)[0]] = position
    return {position + 1 for position in last.values() if not starts_session(cells, position)}


def owed_captures(cells: list[str], refused: frozenset[int] | set[int] = frozenset()) -> set[int]:
    """The planned takes that owe a capture: the plan less the takes the audio
    check refused. The plan itself never moves: a cell whose captured repetition
    was refused has no played-audio evidence in that run."""
    return capture_plan(cells) - set(refused)


def evaluate_all_captures(
    cells: list[str], engine_rows: list[dict], app_rows: list[dict],
    playback_capture_dir: Path | None, outputs_dir: Path | None,
    refused: frozenset[int] | set[int] = frozenset(),
) -> dict[int, dict]:
    """The capture evidence of every planned take, keyed by take index, before the
    verdict is decided; takes outside the capture plan carry none. When the runner
    armed capture (its run manifest is in the directory), every planned take must
    end captured (RF-61, audit T3). A `refused` take owes none, and whatever its
    aborted capture left is not read."""
    if playback_capture_dir is None:
        return {}
    armed = playback_capture.capture_armed(playback_capture_dir)
    captures = playback_capture.collect_captures(playback_capture_dir)
    app_by_id = {row.get("generationID"): row for row in app_rows}
    planned = owed_captures(cells, refused)
    results: dict[int, dict] = {}
    for index, (row, cell) in enumerate(zip(engine_rows, cells, strict=True), start=1):
        if index not in planned:
            continue
        mode = cell.split("/")[0]
        output = row.get("outputMetrics") or {}
        app_row = app_by_id.get(row.get("generationID")) or {}
        frontend = app_row.get("frontendMetrics") or {}
        app_timings = app_row.get("timingsMS") or {}
        results[index] = evaluate_playback_capture(
            index, cell, mode, output.get("durationSeconds"), captures,
            playback_capture_dir, outputs_dir, frontend.get("submitToPlaybackScheduledMS"),
            app_timings.get("submittedAtEpochMS"), armed=armed,
        )
    return results


def build_manifest(
    diagnostics: Path,
    run_id: str,
    label: str,
    modes: list[str],
    lengths: list[str],
    warm: int,
    cells: list[str],
    engine_rows: list[dict],
    app_rows: list[dict],
    merged_rows: list[dict],
    *,
    optimization: str,
    playback_capture_dir: Path | None = None,
    outputs_dir: Path | None = None,
    app_bundle_relative_path: str | None = None,
    capture_results: dict[int, dict] | None = None,
    memory_qualification: tuple | None = None,
    stall_gate: dict | None = None,
    runtime_policy: dict | None = None,
    seed_policy: str | None = None,
    allocation: dict[str, int] | None = None,
    matrix_version: str | None = None,
    refused: dict[int, dict] | None = None,
) -> dict:
    """The run's evidence manifest and the tracked record it publishes.

    `refused` maps a take index to a take the mandatory audio check refused
    (`classify_refused_takes`). Such a take stays in the manifest's `takes` with
    status `refused` and no metrics, and is left out of everything else: the
    record's takes and cells, the memory qualification, the telemetry digest and
    the capture plan. The record then names it in `evidence.refusedCells` and is
    exploratory. Without refused takes the manifest is what it always was."""
    refused = refused or {}
    all_engine_rows = engine_rows
    all_app_ids = {row.get("generationID") for row in app_rows}
    all_merged_ids = {row.get("generationID") for row in merged_rows}
    if refused:
        refused_ids = {item["generationID"] for item in refused.values()}
        engine_rows = [row for row in engine_rows if row.get("generationID") not in refused_ids]
        app_rows = [row for row in app_rows if row.get("generationID") not in refused_ids]
        merged_rows = [row for row in merged_rows if row.get("generationID") not in refused_ids]
    # The gate already qualified these rows; reuse its result (audit #21).
    memory_evidence, memory_run = memory_qualification or qualify_memory_rows(
        rows=engine_rows,
        diagnostics=diagnostics,
        platform="macos",
        app_rows=app_rows,
        require_app_layer=True,
    )
    memory_by_id = {item.generation_id: item for item in memory_evidence}
    app_by_id = {row.get("generationID"): row for row in app_rows}
    if capture_results is None:
        capture_results = evaluate_all_captures(
            cells, all_engine_rows, app_rows, playback_capture_dir, outputs_dir, set(refused),
        )
    capture_by_index: dict[int, dict] = {}
    capture_summary: list[dict] = []
    takes = []
    warning_count = 0
    for index, (row, cell) in enumerate(zip(all_engine_rows, cells, strict=True), start=1):
        mode, length, state_repetition = cell.split("/")
        state, repetition = state_repetition.split("#")
        if index in refused:
            seed, seed_source = take_seed(row.get("notes") or {})
            takes.append({
                "takeIndex": index,
                "generationID": row["generationID"],
                "cell": cell,
                "mode": mode,
                "length": length,
                "warmState": state,
                "repetition": int(repetition),
                # Refused by the mandatory audio check: recorded, never retried,
                # and it carries no timing, output or playback evidence.
                "status": "refused",
                "finishReason": row.get("finishReason"),
                "audioQC": {"verdict": "fail", "flags": refused[index]["flags"]},
                "layerCompleteness": {
                    "engine": True,
                    "app": row["generationID"] in all_app_ids,
                    "merged": row["generationID"] in all_merged_ids,
                },
                "samplingSeed": seed,
                "samplingSeedSource": seed_source,
                "followsColdTake": index > 1 and "/cold#" in cells[index - 2],
            })
            continue
        output = row.get("outputMetrics") or {}
        qc = row.get("audioQC") or output.get("audioQC") or {}
        memory = memory_by_id[row["generationID"]]
        frontend = (app_by_id.get(row["generationID"]) or {}).get("frontendMetrics") or {}
        capture = capture_results.get(index) or {"fields": {}, "metrics": {}, "warnings": [], "summary": None, "gateFailures": []}
        capture_by_index[index] = capture
        if capture["summary"] is not None:
            capture_summary.append(capture["summary"])
        if qc.get("verdict") == "warn" or memory.warnings or capture["warnings"]:
            warning_count += 1
        completeness = {"engine": True, "app": True, "merged": True}
        seed, seed_source = take_seed(row.get("notes") or {})
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
            # The seed each take sampled with (audit #29): generated per take
            # until a seed policy pins it, so run-ons can be reproduced.
            "samplingSeed": seed,
            "samplingSeedSource": seed_source,
            # The first warm take after a cold take pays a settling cost (audit
            # #30: in the 16 canonical M2 runs it is the slowest take of its
            # cell in 14 for custom/short and 11 for design/short). The tracked
            # record keeps it but leaves it out of its cell's statistics.
            "followsColdTake": index > 1 and "/cold#" in cells[index - 2],
        })
    run_warnings = list(memory_run["warnings"])
    stall_warning = stall_report_warning(stall_gate) if stall_gate else None
    if stall_warning:
        run_warnings.append(stall_warning)
    expected = len(cells)
    if refused:
        run_warnings.append(f"{REFUSED_TAKES_WARNING}({len(refused)}/{expected})")
    status = "passedWithWarnings" if warning_count or run_warnings else "pass"
    scope = matrix_scope(modes, lengths, warm, allocation)
    hardware = run_hardware_context(engine_rows, canonical_macos_profile_id())
    # The run's span covers every take it ran, a refused one included.
    recorded = sorted(
        stamp for stamp in (row.get("recordedAt") for row in all_engine_rows)
        if isinstance(stamp, str) and stamp
    )
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    started_at = recorded[0] if recorded else now
    finished_at = recorded[-1] if recorded else now
    selected_telemetry = {
        "engine": engine_rows,
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
    qc_algorithm = qc_algorithm_version(engine_rows)
    history_takes = []
    completed_takes = [take for take in takes if take["status"] != "refused"]
    for take, row in zip(completed_takes, engine_rows, strict=True):
        generation_id = take["generationID"]
        model_identity = row.get("modelRuntimeIdentity") or {}
        memory = memory_by_id[generation_id]
        metrics = tracked_metrics(row, app_by_id.get(generation_id) or {})
        metrics.update(memory.metrics)
        qc = take["audioQC"]
        raw_qc = raw_audio_qc(row)
        qc_metrics = shared_qc_metrics(raw_qc)
        capture = capture_by_index[take["takeIndex"]]
        metrics.update(capture["metrics"])
        take_warnings = sorted(set(
            (qc["flags"] if qc["verdict"] == "warn" else []) + list(memory.warnings) + capture["warnings"]
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
            "layers": ["engine", "app", "merged"],
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
            # A seed the benchmark requested and the engine confirmed, as the
            # engine publisher records it; a generated seed stays in the manifest.
            **({"seed": take["samplingSeed"]} if take["samplingSeedSource"] == "requested"
               and take["samplingSeed"] is not None else {}),
            # The first warm take after a cold take (audit #30): cell aggregate
            # 2 leaves it out of its cell's statistics.
            **({"followsColdTake": True} if take["followsColdTake"] else {}),
            **capture["fields"],
            **take_quality_identity(row),
        })
    busy_takes = takes_above_load_limit(history_takes)
    if busy_takes:
        listed = ", ".join(f"take {index} at {load:.2f}" for index, load in busy_takes)
        print(f"note: {listed} exceeded the per-take load limit; the record is exploratory")
    if refused:
        print(
            f"note: {len(refused)} take(s) refused by the mandatory audio check; the record keeps the "
            f"{len(history_takes)} that completed, is exploratory and is never canonical"
        )
    # A refused take leaves the matrix incomplete (decision D-5): never canonical.
    exploratory = diagnostic_memory_tier(engine_rows) or bool(busy_takes) or bool(refused)
    planned_captures = owed_captures(cells, set(refused))
    if playback_capture_dir is not None:
        write_json_atomic(Path(playback_capture_dir) / "summary.json", {
            "schemaVersion": 1,
            "runID": run_id,
            "takes": capture_summary,
            "captured": sum(1 for item in capture_summary if item.get("status") == "captured"),
            # Whether the runner armed capture, so every planned take owed one (audit T3).
            "armed": playback_capture.capture_armed(playback_capture_dir),
            # One captured repetition per cell (audit #31): the plan, not every take.
            "expected": len(planned_captures),
            "plannedTakes": sorted(planned_captures),
            # Planned takes the audio check refused owe no capture.
            **({"refusedTakes": sorted(capture_plan(cells) & set(refused))} if refused else {}),
            "gate": {
                "coverageMin": playback_capture.GATE_COVERAGE_MIN,
                "residualMaxDBFS": playback_capture.GATE_RESIDUAL_MAX_DBFS,
                "dropoutMax": playback_capture.GATE_DROPOUT_MAX,
                "misalignedMaxMS": playback_capture.GATE_MISALIGNED_MAX_MS,
                "failedTakes": [item["takeIndex"] for item in capture_summary if item.get("gateFailures")],
            },
        })
    history_record = {
        "schemaVersion": history_record_schema_version(history_takes),
        "run": {
            "id": run_id,
            "kind": "ui-generation",
            "platform": "macos",
            "status": "passedWithWarnings" if warning_count or run_warnings else "passed",
            "label": label or run_id,
            "matrixScope": scope,
            "startedAt": started_at,
            "finishedAt": finished_at,
            "warnings": run_warnings,
            "rtfDefinition": rtf_semantics.STANDARD_RTF_DEFINITION,
            # How every take chose its sampling seed (audit #29); lineage
            # contract 2 keys a seeded matrix apart from random seeds.
            **({"seedPolicy": seed_policy} if seed_policy is not None else {}),
            # A forced or emulated memory tier (audit #11), a take above the
            # per-take load limit (audit #28) or a refused take (audit T5) is
            # exploratory evidence.
            **({"classification": "exploratory"} if exploratory else {}),
            # The tier the takes ran under, forced or emulated included; never
            # part of the comparison key.
            **({"runtimePolicy": runtime_policy} if runtime_policy is not None else {}),
        },
        "hardware": hardware,
        "toolchain": {"optimization": optimization},
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
            # The cells leave the take after a cold take out and publish an
            # IQR only from four takes (audit #30).
            "cellAggregateVersion": CELL_AGGREGATE_VERSION,
            # The takes the mandatory audio check refused, and the rule the
            # record follows for them (audit T5): they are in no take, cell or
            # median here, and the record is exploratory, never canonical.
            **({
                "refusedCells": refused_cells(refused),
                "refusedTakeRule": REFUSED_TAKE_RULE,
            } if refused else {}),
        },
        "takes": history_takes,
    }
    refused_layers = [take["layerCompleteness"] for take in takes if take["status"] == "refused"]
    layer_counts = {
        "engine": expected,
        "app": len(app_rows) + sum(1 for layers in refused_layers if layers["app"]),
        "merged": len(merged_rows) + sum(1 for layers in refused_layers if layers["merged"]),
    } if refused else {"engine": expected, "app": expected, "merged": expected}
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
            # The declared matrix version and its warm reallocation (audit #30).
            **({"version": matrix_version} if matrix_version else {}),
            "warmAllocation": dict(allocation or {}),
            "scope": scope,
            "expectedTakeCount": expected,
            "orderedCells": cells,
        },
        # Every take that completed has all three layers; a refused take's app
        # and merged rows are counted when it left them.
        "layers": {
            "engine": {"count": layer_counts["engine"], "complete": True},
            "app": {"count": layer_counts["app"], "complete": True},
            "merged": {"count": layer_counts["merged"], "complete": True},
        },
        "takes": takes,
        **({"refusedCells": refused_cells(refused)} if refused else {}),
        # The bundle the lane built and drove; the record step hashes its
        # executables instead of assuming an arena.
        **({"appBundleRelativePath": app_bundle_relative_path} if app_bundle_relative_path else {}),
        # The stall contract this run was judged under and what it observed
        # (run artifact only; the tracked record stays on its allowlist).
        **({"stallGate": stall_gate} if stall_gate else {}),
        # The runtime overrides that keep this run out of history (BKL-22);
        # `benchmark_history.py record` refuses a manifest that names any. An
        # unarmed run writes the manifest it always wrote.
        **({"armedRuntimeOverrideKeys": armed} if (armed := armed_runtime_overrides(all_engine_rows)) else {}),
        "historyRecord": history_record,
    }


def take_quality_identity(row: dict) -> dict:
    """The typed quality-registry identity this engine row published with (shared fold)."""
    return quality_identity_fields(row)


def history_record_schema_version(history_takes: list) -> int:
    try:
        return shared_record_schema_version(history_takes)
    except AudioQCError as error:
        raise SystemExit(str(error)) from error


write_json_atomic = jsonio.atomic_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("diag_dir", type=Path, help="QwenVoice-Debug/diagnostics directory")
    parser.add_argument("--modes", default=",".join(DEFAULT_MODES))
    parser.add_argument("--lengths", default=",".join(DEFAULT_LENGTHS))
    parser.add_argument("--warm", type=int, default=DEFAULT_WARM)
    parser.add_argument("--run-id", default="", help="select only notes.benchRunID rows")
    parser.add_argument(
        "--stall-contract", type=Path, default=DEFAULT_STALL_CONTRACT, metavar="PATH",
        help="the stall gate's statistic, limit and calibration profile (config/macos-ui-stall-gate.json)",
    )
    parser.add_argument(
        "--allocation", default="", metavar="MODE/LENGTH=N,...",
        help="warm repetitions per mode and length of a declared matrix version (audit #30)",
    )
    parser.add_argument("--matrix-version", default="", help="the config/ui-bench-matrix.json version run")
    parser.add_argument(
        "--seed-policy", choices=bench_seed.LANE_SEED_POLICIES, default=None,
        help="the seed policy the lane selected (audit #29); every take must have sampled under it",
    )
    parser.add_argument(
        "--variant", choices=MODEL_VARIANTS, default=DEFAULT_VARIANT,
        help="the model variant every take must have run (default: speed)",
    )
    parser.add_argument("--since-recorded", default="")
    parser.add_argument("--label", default="")
    parser.add_argument("--evidence-manifest", type=Path, metavar="PATH")
    parser.add_argument(
        "--build-provenance", type=Path, metavar="PATH",
        help="last-build.json written by the lane's build step; binds toolchain.optimization "
             "to the executable that ran (required with --evidence-manifest)",
    )
    parser.add_argument(
        "--crash-delta-passed",
        action="store_true",
        help="assert that the caller completed its pre/post crash-delta gate",
    )
    parser.add_argument(
        "--playback-capture-dir", type=Path, metavar="DIR",
        help="the runner's per-take capture WAVs and sidecars (PC-01). A silent take fails; when the "
             "directory holds the runner's capture-run.json (capture was armed), every planned take must "
             "be captured, otherwise takes without a capture are marked unavailable",
    )
    parser.add_argument(
        "--outputs-dir", type=Path, metavar="DIR",
        help="the app's published outputs root, used to resolve each take's WAV for the capture comparison",
    )
    parser.add_argument(
        "--max-playback-underruns", type=int, default=0, metavar="N",
        help="playback underruns a take may report before it fails (default 0; audit T4). "
             "A playback continuity failure always fails the take",
    )
    parser.add_argument(
        "--xcodebuild-log", type=Path, metavar="PATH",
        help="the run's xcodebuild log, read for the runner's refused-take markers "
             f"({REFUSED_MARKER}<base64 JSON>). A marked take is recorded as refused only when its "
             "engine row shows the mandatory audio check's refusal; any other marked take fails the run. "
             "Without the log no take can be recorded as refused",
    )
    parser.add_argument(
        "--max-refused-takes", type=int, default=DEFAULT_MAX_REFUSED_TAKES, metavar="N",
        help="takes the mandatory audio check may refuse before the run fails as a product failure "
             f"(default {DEFAULT_MAX_REFUSED_TAKES}). A refused take is recorded and the takes that "
             "completed are published as an exploratory record that is never canonical. A refused "
             "take is never retried and the seeds never move for one (decision of 2026-11-15)",
    )
    args = parser.parse_args()
    if args.max_playback_underruns < 0:
        parser.error("--max-playback-underruns must be 0 or more")
    if args.max_refused_takes < 0:
        parser.error("--max-refused-takes must be 0 or more")

    if args.evidence_manifest and args.evidence_manifest.exists():
        args.evidence_manifest.unlink()
    if args.evidence_manifest and not args.run_id:
        parser.error("--evidence-manifest requires --run-id")
    if args.evidence_manifest and not args.crash_delta_passed:
        parser.error("--evidence-manifest requires --crash-delta-passed")
    if args.evidence_manifest and not args.build_provenance:
        parser.error("--evidence-manifest requires --build-provenance")
    if args.warm < 1:
        parser.error("--warm must be at least 1")
    optimization = "unverified"
    app_bundle_relative_path = None
    if args.build_provenance:
        try:
            receipt = load_build_provenance(args.build_provenance, platform="macos")
        except ProvenanceError as error:
            print(f"FAIL: build provenance: {error}")
            return 1
        optimization = receipt["optimization"]
        app_bundle_relative_path = app_bundle_from_receipt(receipt.get("executableRelativePath"))
    try:
        modes = parse_list(args.modes, DEFAULT_MODES)
        lengths = parse_list(args.lengths, DEFAULT_LENGTHS)
        allocation = ui_bench_matrix.parse_allocation(args.allocation)
    except ValueError as error:
        parser.error(str(error))
    try:
        stall_contract = load_stall_contract(args.stall_contract)
    except StallContractError as error:
        print(f"FAIL: {error}")
        return 1

    expected_cell_order = expected_cells(modes, lengths, args.warm, allocation)
    expected = len(expected_cell_order)
    paths = {
        "engine": args.diag_dir / "engine" / "generations.jsonl",
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
    app_rows = loaded["app"]
    engine_ids = [row.get("generationID") for row in engine_rows]
    valid_engine_ids = [value for value in engine_ids if isinstance(value, str) and value]
    engine_id_set = set(valid_engine_ids)
    merged_rows = [row for row in loaded["merged"] if row.get("generationID") in engine_id_set]

    # Refused takes (audit T5): the runner's markers, each proven by its engine
    # row. A refused take is recorded and left out of every gate below; the
    # checks that follow judge only the takes that completed.
    markers, marker_failures = read_refused_markers(args.xcodebuild_log, expected_cell_order)
    failures.extend(marker_failures)
    refused, refusal_failures = classify_refused_takes(markers, engine_rows)
    failures.extend(refusal_failures)
    refused_ids = {item["generationID"] for item in refused.values()}
    if len(refused) > args.max_refused_takes:
        failures.append(
            f"{len(refused)} take(s) refused by the mandatory audio check, above the allowance of "
            f"{args.max_refused_takes} (--max-refused-takes): "
            + ", ".join(f"take {index} ({refused[index]['cell']})" for index in sorted(refused))
            + "; a product failure, not a benchmark result"
        )
    all_engine_rows, all_app_rows, all_merged_rows = engine_rows, app_rows, merged_rows
    if refused:
        engine_rows = [row for row in engine_rows if row.get("generationID") not in refused_ids]
        app_rows = [row for row in app_rows if row.get("generationID") not in refused_ids]
        merged_rows = [row for row in merged_rows if row.get("generationID") not in refused_ids]
        valid_engine_ids = [value for value in valid_engine_ids if value not in refused_ids]
        engine_id_set = set(valid_engine_ids)
        # The app records a failed generation as failed; a row that reports the
        # refused take as completed contradicts the engine.
        for row in all_app_rows:
            if row.get("generationID") in refused_ids and str(row.get("finishReason")).lower() in SUCCESS_FINISH:
                failures.append(
                    f"app generation {row.get('generationID', '?')} reports finishReason="
                    f"{row.get('finishReason')!r} for a take the audio check refused"
                )
    completed_expected = expected - len(refused)

    # Rows that are simply not there yet: a missing layer file, fewer engine
    # rows than the matrix, or an engine take whose app or merged row has not
    # landed. Only this outcome is worth a short retry (audit #6, #21). A
    # refused take's app and merged rows are not waited for.
    rows_pending: list[str] = [f"{layer} file absent" for layer, path in paths.items() if not path.is_file()]
    if len(all_engine_rows) < expected:
        rows_pending.append(f"engine rows {len(all_engine_rows)} of {expected}")
    for layer, rows in (("app", app_rows), ("merged", merged_rows)):
        missing = engine_id_set - {row.get("generationID") for row in rows}
        if missing:
            rows_pending.append(f"{layer} rows missing for {len(missing)} engine take(s)")

    if stall_contract["calibrationProfile"] != canonical_macos_profile_id():
        failures.append(
            f"stall contract {stall_contract['policyID']} names calibration profile "
            f"{stall_contract['calibrationProfile']!r}, not the canonical macOS profile "
            f"{canonical_macos_profile_id()!r}; re-declare it for this host"
        )

    if len(all_engine_rows) != expected:
        failures.append(f"engine rows {len(all_engine_rows)} != expected {expected}")
    if any(not isinstance(value, str) or not value for value in engine_ids):
        failures.append("one or more engine rows has no generationID")
    if len(set(engine_ids)) != len(engine_ids):
        failures.append("engine generationIDs are not unique")
    failures.extend(validate_layer("app", app_rows, valid_engine_ids, completed_expected))
    failures.extend(validate_take_identity(all_engine_rows, all_app_rows))
    failures.extend(validate_merged(merged_rows, valid_engine_ids, completed_expected))
    failures.extend(
        validate_process_ownership(engine_rows, app_rows, merged_rows, valid_engine_ids)
    )

    actual_cells: list[str] = []
    actual_indices: list[int] = []
    for row in all_engine_rows:
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
        if row.get("generationID") in refused_ids:
            # A refused take keeps its place in the matrix and owes nothing else:
            # it published no audio and its row is a failure row by design.
            continue
        finish = row.get("finishReason")
        if str(finish).lower() not in SUCCESS_FINISH:
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
            variant = exact_model_variant(identity, row)
            if variant is None:
                failures.append(f"generation {row.get('generationID', '?')} has no exact model variant")
            elif variant != args.variant:
                # The tier may recommend another variant (Quality first on
                # the M6); the benchmark's label claims only the declared one.
                failures.append(
                    f"generation {row.get('generationID', '?')} ran the {variant} variant, "
                    f"not the declared {args.variant} variant"
                )
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
    # The takes that completed, each with its place in the matrix; a refused
    # take is in none of the gates below (playback health, stalls, captures).
    completed_takes = [
        (index, row) for index, row in enumerate(all_engine_rows, start=1)
        if row.get("generationID") not in refused_ids
    ]
    # Playback health (RF-61, audit T4): a take whose stream broke or whose
    # player ran dry fails, named by its place in the matrix.
    for index, engine_row in completed_takes:
        gid = engine_row.get("generationID")
        frontend = (app_by_id.get(gid) or {}).get("frontendMetrics")
        if not isinstance(frontend, dict):
            continue  # already a failure above
        cell = (engine_row.get("notes") or {}).get("benchCell")
        take = f"take {index} ({cell})" if isinstance(cell, str) else f"take {index}"
        for reason in playback_health_failures(frontend, args.max_playback_underruns):
            failures.append(f"{take}: {reason} (generation {gid or '?'})")
    # The stall gate (audit #6): the contract names the statistic and limit, and
    # its status whether the limit fails the run or only reports (provisional).
    statistic = stall_contract["statistic"]
    stall_limit = stall_contract["maximumAllowed"]
    stall_enforced = stall_contract_enforced(stall_contract)
    stall_observed: list[tuple[str, int]] = []
    stall_exempt = 0
    stall_unjudged: list[str] = []
    censored_heartbeats = 0
    for index, engine_row in completed_takes:
        gid = engine_row.get("generationID")
        notes = engine_row.get("notes") or {}
        if not stall_gate_applies(notes):
            if stall_gate_exempt(notes):
                stall_exempt += 1
            else:
                cell = notes.get("benchCell") if isinstance(notes.get("benchCell"), str) else "?"
                stall_unjudged.append(f"take {index} ({cell}) deviceClass={notes.get('deviceClass')!r}")
            continue
        app_row = app_by_id.get(gid)
        if app_row is None:
            continue  # the missing app row is already a failure above
        value = stall_statistic_value(app_row, statistic)
        if value is None:
            failures.append(f"app generation {gid or '?'} has no {statistic} for the stall gate")
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            failures.append(f"app generation {gid or '?'} has invalid {statistic}={value!r}")
            continue
        cell = notes.get("benchCell") if isinstance(notes.get("benchCell"), str) else f"take {index}"
        stall_observed.append((cell, value))
        censored = (app_row.get("frontendMetrics") or {}).get("censoredHeartbeatCount")
        if isinstance(censored, int) and not isinstance(censored, bool) and censored > 0:
            censored_heartbeats += censored
        if value > stall_limit and stall_enforced:
            failures.append(
                f"{statistic} {value} > {stall_limit} (generation {gid}; "
                f"stall contract {stall_contract['policyID']}, {stall_contract['calibrationStatus']})"
            )
    stall_gate = stall_gate_summary(
        stall_contract, stall_observed, censored_heartbeats,
        expected=completed_expected, exempt=stall_exempt, refused=len(refused),
    )
    # The gate cannot pass empty (RF-61, audit T6): a row without a Mac device
    # class used to skip it silently, so a calibrated limit could judge nothing.
    # Every take of the selected matrix must be gated, bar the forced-tier
    # diagnostic takes the gate leaves out by design. A take already failed
    # above (a missing row or statistic) is not reported a second time.
    if stall_enforced and not stall_gate["coversMatrix"] and (stall_unjudged or not failures):
        failures.append(
            f"stall gate {stall_contract['policyID']} judged {len(stall_observed)} of {completed_expected} takes "
            f"({stall_exempt} forced-tier diagnostic take(s) exempt); a calibrated gate must cover the matrix"
            + (f": unjudged {'; '.join(stall_unjudged)}" if stall_unjudged else "")
        )

    # The seed policy (audit #29): under a cell-hash policy every take sampled with its
    # cell's seed; the lane's selection must match what the rows ran.
    # A refused take is judged with the rest: it was refused at its cell's seed,
    # and the seeds never move for one (decision of 2026-11-15).
    seed_policy = None
    if len(all_engine_rows) == expected:
        seed_policy, seed_failures = bench_seed.run_seed_policy([
            (cell, row.get("notes") or {}) for cell, row in zip(expected_cell_order, all_engine_rows, strict=True)
        ])
        failures.extend(seed_failures)
        failures.extend(bench_seed.expected_policy_failure(args.seed_policy, seed_policy))

    # The record's tier provenance (audit #19, #11): a selection that does not
    # share one stamped tier and one emulation cannot publish a record.
    runtime_policy = None
    if args.evidence_manifest:
        try:
            runtime_policy = run_runtime_policy(engine_rows)
        except ValueError as error:
            failures.append(f"runtime policy: {error}")

    memory_qualification = None
    if not failures:
        try:
            memory_qualification = qualify_memory_rows(
                rows=engine_rows,
                diagnostics=args.diag_dir,
                platform="macos",
                app_rows=app_rows,
                require_app_layer=True,
            )
        except MemoryEvidenceError as error:
            failures.append(str(error))

    # Played-audio gate (PC-02): captured takes must match what the app played, a
    # silent take fails, and an armed run owes every planned capture (audit T3).
    capture_results: dict[int, dict] | None = None
    if not failures and args.playback_capture_dir is not None:
        capture_results = evaluate_all_captures(
            expected_cell_order, all_engine_rows, app_rows, args.playback_capture_dir, args.outputs_dir,
            set(refused),
        )
        if not playback_capture.capture_armed(args.playback_capture_dir):
            print(
                f"note: no {playback_capture.ARMED_MANIFEST} in {args.playback_capture_dir}: the runner did not "
                "arm played-audio capture, so planned takes without a capture are unavailable, not failures"
            )
        for index, capture in sorted(capture_results.items()):
            for reason in capture.get("gateFailures", []):
                failures.append(f"take {index} ({expected_cell_order[index - 1]}): {reason}")

    print(
        f"macOS UI bench gate: expected={expected} engine={len(all_engine_rows)} "
        f"app={len(all_app_rows)} merged={len(all_merged_rows)}"
    )
    if refused:
        # One line the lane repeats in its summary; the gates below judged the rest.
        print(refused_takes_line(refused))
    enforcement = "enforced" if stall_enforced else "report only, never fails the run"
    would_fail = "yes" if stall_gate["wouldFail"] else "no"
    print(
        f"stall gate {stall_gate['policyID']} ({stall_gate['calibrationStatus']} on "
        f"{stall_gate['calibrationProfile']}, {enforcement}): {statistic} <= {stall_limit} over "
        f"{stall_gate['gatedTakeCount']} gated take(s) of {completed_expected} "
        f"({stall_exempt} exempt); median={stall_gate['median']} "
        f"p90={stall_gate['p90']} max={stall_gate['maximum']} "
        f"above={stall_gate['takesAboveLimit']} wouldFail={would_fail} "
        f"censoredHeartbeats={censored_heartbeats}"
    )
    # Every gated take's value, pass or fail: a failing run writes no manifest,
    # so this output is all that records the distribution a calibration needs.
    print(
        f"stall gate takes ({statistic}): "
        + (", ".join(f"{take['cell']}={take['value']}" for take in stall_gate["takes"]) or "none")
    )
    if failures:
        print("FAIL:")
        for item in failures:
            print(f"  - {item}")
        if rows_pending:
            print(f"ROWS NOT YET PRESENT: {'; '.join(rows_pending)}")
            return ROWS_NOT_YET_PRESENT_EXIT
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
            all_engine_rows,
            all_app_rows,
            all_merged_rows,
            optimization=optimization,
            playback_capture_dir=args.playback_capture_dir,
            outputs_dir=args.outputs_dir,
            app_bundle_relative_path=app_bundle_relative_path,
            capture_results=capture_results,
            memory_qualification=memory_qualification,
            stall_gate=stall_gate,
            runtime_policy=runtime_policy,
            seed_policy=seed_policy,
            allocation=allocation,
            matrix_version=args.matrix_version or None,
            refused=refused,
        )
        write_json_atomic(args.evidence_manifest, manifest)
        print(f"evidence={args.evidence_manifest}")
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
