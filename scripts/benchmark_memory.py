#!/usr/bin/env python3
"""Strict, run-scoped memory evidence for benchmark publication.

Raw sampler sidecars are intentionally untracked.  This module validates the
exact sidecars selected by a benchmark, derives a small allowlisted summary,
and returns digests that bind the tracked record to those raw samples.

iOS is a single-process engine/app runtime, and so is macOS since 2026-09-15.
Older macOS records came from separate engine-service and app processes, so
macOS aggregate peaks are calculated only from samples whose
absolute uptime timestamps can be paired within one sampling cadence.  It is
never valid to add independent process maxima.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable


MEMORY_CONTRACT_VERSION = 1
REQUIRED_TELEMETRY_SCHEMA = 8
MINIMUM_COVERAGE = 0.95
PERFECT_COVERAGE = 1.0

ENGINE_BOUNDARY_REQUIREMENTS: dict[str, frozenset[str]] = {
    "preparation-start": frozenset({"before_preparation"}),
    "mode-preparation-start": frozenset({"before_mode_preparation"}),
    "mode-preparation-end": frozenset({"after_mode_preparation"}),
    "prewarm-start": frozenset({"before_prewarm", "prewarm_skipped"}),
    "prewarm-end": frozenset({"after_prewarm", "prewarm_skipped"}),
    "model-load-start": frozenset({"before_model_load"}),
    "model-load-end": frozenset({"after_model_load"}),
    "preparation-end": frozenset({"after_preparation"}),
    "session-start": frozenset({"session_start"}),
    "first-output": frozenset({"first_chunk", "final_audio_materialized"}),
    "final-audio-materialized": frozenset({"final_audio_materialized"}),
    "final-wav-start": frozenset({"before_final_wav"}),
    "audio-qc-start": frozenset({"before_audio_qc"}),
    "audio-qc-end": frozenset({"after_audio_qc"}),
    "final-wav-end": frozenset({"after_final_wav"}),
    "post-generation-memory-action-start": frozenset({
        "post_generation", "before_post_generation_trim",
    }),
    "post-generation-memory-action-end": frozenset({
        "post_generation", "post_generation_trim",
    }),
    "terminal": frozenset({
        "terminal_success", "terminal_failure", "terminal_cancelled",
        "preparation_failed",
    }),
}
APP_BOUNDARY_REQUIREMENTS: dict[str, frozenset[str]] = {
    "app-submit": frozenset({"app_submit"}),
    "app-terminal": frozenset({"app_terminal"}),
}
ENGINE_REQUIRED_BOUNDARY_NAMES = frozenset(ENGINE_BOUNDARY_REQUIREMENTS)
APP_REQUIRED_BOUNDARY_NAMES = frozenset(APP_BOUNDARY_REQUIREMENTS)

# These are ordering constraints between semantic lifecycle milestones, not an
# exact raw-sample sequence.  Periodic samples and diagnostic-only boundaries
# may appear anywhere between the constrained milestones.  Some production
# paths intentionally collapse two semantic milestones into one raw boundary:
# `prewarm_skipped` satisfies both prewarm edges, `post_generation` satisfies
# both post-generation memory-action edges, and a non-streaming
# `final_audio_materialized` sample can also be the first output.
ENGINE_BOUNDARY_PARTIAL_ORDER: tuple[tuple[str, str], ...] = (
    ("preparation-start", "model-load-start"),
    ("model-load-start", "model-load-end"),
    ("model-load-end", "mode-preparation-start"),
    ("mode-preparation-start", "prewarm-start"),
    ("prewarm-start", "prewarm-end"),
    ("prewarm-end", "mode-preparation-end"),
    ("mode-preparation-end", "preparation-end"),
    ("preparation-end", "session-start"),
    ("session-start", "first-output"),
    ("first-output", "final-audio-materialized"),
    ("final-audio-materialized", "final-wav-start"),
    ("final-wav-start", "audio-qc-start"),
    ("audio-qc-start", "audio-qc-end"),
    ("audio-qc-end", "final-wav-end"),
    ("final-wav-end", "post-generation-memory-action-start"),
    ("post-generation-memory-action-start", "post-generation-memory-action-end"),
    ("post-generation-memory-action-end", "terminal"),
)
APP_BOUNDARY_PARTIAL_ORDER: tuple[tuple[str, str], ...] = (
    ("app-submit", "app-terminal"),
)

ENGINE_TERMINAL_BOUNDARIES = frozenset({
    "terminal_success", "terminal_failure", "terminal_cancelled", "preparation_failed",
})

PRESSURE_LEVELS = {"none": 0, "softTrim": 1, "hardTrim": 2, "fullUnload": 3}
PRESSURE_BANDS = {"healthy": 0, "guarded": 1, "critical": 2}
# The per-tier policy (`clearCacheAfterGeneration`, the 8 GB Mac and the iPhone
# Pro tiers) clears the MLX cache after every successful take and records it as
# a soft trim.  That routine clear is not memory pressure: it is published as
# `policyCacheClearCount` and raises neither the pressure level nor a warning.
# Only this exact source and reason qualify; every other soft trim (kernel,
# application, runtime budget relief, or a store trim whose reason merely
# starts with "post_generation") still warns.
POLICY_CACHE_CLEAR_SOURCE = "post-generation"
POLICY_CACHE_CLEAR_REASON = "post_generation_cache_clear"


def is_policy_cache_clear(level: str, source: str, reason: str) -> bool:
    """True only for the routine per-tier post-generation MLX cache clear."""
    return (
        level == "softTrim"
        and source == POLICY_CACHE_CLEAR_SOURCE
        and reason == POLICY_CACHE_CLEAR_REASON
    )
MEMORY_EVENT_KINDS = frozenset({
    "pressure-signal",
    "application-warning",
    "budget-transition",
    "trim-action",
    "unload",
    "memory-exit",
})


class MemoryEvidenceError(ValueError):
    """Raised when benchmark memory evidence is absent or unsafe to publish."""


def _finite(value: Any, location: str, *, minimum: float = 0.0) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or float(value) < minimum
    ):
        raise MemoryEvidenceError(f"{location} must be finite and >= {minimum:g}")
    return float(value)


def _integer(value: Any, location: str, *, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise MemoryEvidenceError(f"{location} must be an integer >= {minimum}")
    return value


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _strict_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MemoryEvidenceError(f"duplicate JSON key {key!r} in memory sidecar")
        result[key] = value
    return result


def _read_sidecar(path: Path) -> tuple[list[dict[str, Any]], str]:
    if not path.is_file() or path.is_symlink():
        raise MemoryEvidenceError(f"missing memory sample sidecar: {path}")
    raw_bytes = path.read_bytes()
    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(raw_bytes.decode("utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw, object_pairs_hook=_strict_object_pairs)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise MemoryEvidenceError(
                f"{path}:{line_number}: malformed memory sample: {error}"
            ) from error
        if not isinstance(value, dict):
            raise MemoryEvidenceError(f"{path}:{line_number}: sample is not an object")
        rows.append(value)
    if not rows:
        raise MemoryEvidenceError(f"empty memory sample sidecar: {path}")
    return rows, _sha256_bytes(raw_bytes)


def _find_exact_sidecar(diagnostics: Path, layer: str, generation_id: str) -> Path:
    basename = f"samples-{generation_id}.jsonl"
    direct = diagnostics / layer / basename
    if direct.is_file() and not direct.is_symlink():
        return direct
    matches = sorted(
        path for path in diagnostics.rglob(basename)
        if path.is_file() and not path.is_symlink() and path.parent.name == layer
    )
    if len(matches) != 1:
        raise MemoryEvidenceError(
            f"generation {generation_id}: expected exactly one {layer} sample sidecar, "
            f"found {len(matches)}"
        )
    return matches[0]


def _validate_lifecycle_boundary_order(
    *,
    generation_id: str,
    layer: str,
    boundary_positions: dict[str, list[int]],
) -> None:
    """Validate raw lifecycle ordering while allowing collapsed alternatives.

    Raw sidecar order is authoritative after the sample clocks have been
    checked as monotonic.  Comparing indexes, rather than requiring increasing
    timestamps, preserves legitimate same-time captures and lets one collapsed
    boundary satisfy two adjacent semantic milestones.
    """
    if layer == "engine":
        requirements = ENGINE_BOUNDARY_REQUIREMENTS
        partial_order = ENGINE_BOUNDARY_PARTIAL_ORDER
    else:
        requirements = APP_BOUNDARY_REQUIREMENTS
        partial_order = APP_BOUNDARY_PARTIAL_ORDER

    recognized = set().union(*requirements.values())
    duplicates = sorted(
        boundary for boundary in recognized
        if len(boundary_positions.get(boundary, ())) > 1
    )
    if duplicates:
        raise MemoryEvidenceError(
            f"generation {generation_id} {layer}: duplicate lifecycle boundaries: "
            + ", ".join(duplicates)
        )

    if layer == "engine":
        branches = (
            ("prewarm", "prewarm_skipped", ("before_prewarm", "after_prewarm")),
            (
                "post-generation memory action",
                "post_generation",
                ("before_post_generation_trim", "post_generation_trim"),
            ),
        )
        for label, collapsed, expanded in branches:
            collapsed_present = collapsed in boundary_positions
            expanded_present = [boundary in boundary_positions for boundary in expanded]
            if collapsed_present and any(expanded_present):
                raise MemoryEvidenceError(
                    f"generation {generation_id} engine: {label} mixes collapsed and "
                    "expanded lifecycle boundaries"
                )
            if not collapsed_present and not all(expanded_present):
                raise MemoryEvidenceError(
                    f"generation {generation_id} engine: {label} lifecycle branch is incomplete"
                )

        terminals = sorted(
            boundary for boundary in ENGINE_TERMINAL_BOUNDARIES
            if boundary in boundary_positions
        )
        if len(terminals) != 1:
            raise MemoryEvidenceError(
                f"generation {generation_id} engine: expected exactly one terminal lifecycle "
                f"boundary, found {len(terminals)}"
            )

    resolved_positions: dict[str, int] = {}
    for semantic_name, alternatives in requirements.items():
        if semantic_name == "first-output" and "first_chunk" in boundary_positions:
            # A streaming take that emitted a first chunk must place it before
            # final materialization.  Falling back to the earlier of the two
            # alternatives would incorrectly hide a late/out-of-order chunk.
            matches = list(boundary_positions["first_chunk"])
        else:
            matches = [
                position
                for boundary in alternatives
                for position in boundary_positions.get(boundary, ())
            ]
        if not matches:
            # Presence is checked separately, but keep this helper fail-closed
            # when it is reused independently.
            raise MemoryEvidenceError(
                f"generation {generation_id} {layer}: missing lifecycle boundary "
                f"{semantic_name}"
            )
        resolved_positions[semantic_name] = min(matches)

    for earlier, later in partial_order:
        if resolved_positions[earlier] > resolved_positions[later]:
            raise MemoryEvidenceError(
                f"generation {generation_id} {layer}: lifecycle boundary order is invalid: "
                f"{earlier} must not occur after {later}"
            )


def _stage_marks(row: dict[str, Any]) -> list[dict[str, Any]]:
    backend = row.get("backendMetrics") or {}
    summary = row.get("summary") or {}
    marks = backend.get("stages") or row.get("stageMarks") or summary.get("stageMarks") or []
    return [mark for mark in marks if isinstance(mark, dict)]


@dataclass(frozen=True)
class MemoryEventSummary:
    warnings: list[str]
    failures: list[str]
    pressure_event_count: int
    maximum_pressure_level: int
    trim_count: int
    maximum_trim: int
    policy_cache_clear_count: int


def _memory_warnings_and_failures(row: dict[str, Any]) -> MemoryEventSummary:
    warnings: set[str] = set()
    failures: list[str] = []
    pressure_event_count = 0
    maximum_pressure_level = 0
    trim_count = 0
    maximum_trim = 0
    policy_cache_clear_count = 0

    memory_metrics = row.get("memoryMetrics") if isinstance(row.get("memoryMetrics"), dict) else {}
    typed_events = memory_metrics.get("events") if isinstance(memory_metrics.get("events"), list) else []
    typed_kind_counts: dict[str, int] = {}
    for event in typed_events:
        if not isinstance(event, dict):
            failures.append("memoryMetrics.events contains a non-object")
            continue
        kind = str(event.get("kind") or "")
        if kind not in MEMORY_EVENT_KINDS:
            failures.append(f"unknown typed memory event kind {kind!r}")
            continue
        level = str(event.get("trimLevel") or "none")
        policy_clear = kind == "trim-action" and is_policy_cache_clear(
            level, str(event.get("source") or ""), str(event.get("reasonCode") or "")
        )
        # The cross-check below keeps routine clears apart from other trims, so
        # a stage mark cannot turn a typed pressure trim into a routine one.
        counted_kind = "policy-cache-clear" if policy_clear else kind
        typed_kind_counts[counted_kind] = typed_kind_counts.get(counted_kind, 0) + 1
        if policy_clear:
            # Still a trim action (memoryTrimCount and maximumTrimLevel keep
            # their meaning), but never pressure and never a warning.
            policy_cache_clear_count += 1
            trim_count += 1
            maximum_trim = max(maximum_trim, PRESSURE_LEVELS[level])
            continue
        maximum_pressure_level = max(
            maximum_pressure_level, PRESSURE_LEVELS.get(level, 0)
        )
        if kind == "pressure-signal":
            pressure_event_count += 1
            if level in {"hardTrim", "fullUnload"}:
                failures.append(f"memory pressure signal reached {level}")
            elif level == "softTrim":
                warnings.add("memory.pressure.soft_trim")
        elif kind == "application-warning":
            failures.append("application memory warning was recorded")
        elif kind == "budget-transition":
            current_band = str(event.get("currentPressureBand") or "")
            if current_band not in PRESSURE_BANDS:
                failures.append(
                    f"budget transition has invalid current pressure band {current_band!r}"
                )
            else:
                maximum_pressure_level = max(
                    maximum_pressure_level, PRESSURE_BANDS[current_band]
                )
                if current_band == "critical":
                    failures.append("memory budget transitioned to critical")
                elif current_band == "guarded":
                    warnings.add("memory.pressure.guarded")
        elif kind == "trim-action":
            trim_count += 1
            maximum_trim = max(maximum_trim, PRESSURE_LEVELS.get(level, 0))
            if level in {"hardTrim", "fullUnload"}:
                failures.append(f"memory trim reached {level}")
            elif level == "softTrim":
                warnings.add("memory.pressure.soft_trim")
            elif level != "none":
                failures.append(f"memory trim has invalid level {level!r}")
        elif kind == "unload":
            maximum_pressure_level = max(
                maximum_pressure_level, PRESSURE_LEVELS["fullUnload"]
            )
            failures.append("model unload was recorded during the benchmark take")
        elif kind == "memory-exit":
            failures.append("memory exit was recorded")

    # Compatibility cross-check: v8 typed events are authoritative, but the
    # stage marks must not contain an event that the typed projection omitted.
    stage_kind_counts: dict[str, int] = {}
    for mark in _stage_marks(row):
        stage = str(mark.get("stage") or "")
        metadata = mark.get("metadata") if isinstance(mark.get("metadata"), dict) else {}
        level = str(metadata.get("level") or metadata.get("action") or "none")
        reason = str(metadata.get("reason") or "").lower()
        if stage == "memory_pressure":
            stage_kind_counts["pressure-signal"] = stage_kind_counts.get("pressure-signal", 0) + 1
            maximum_pressure_level = max(maximum_pressure_level, PRESSURE_LEVELS.get(level, 0))
            if level in {"hardTrim", "fullUnload"}:
                failures.append(f"memory pressure reached {level}")
            elif level == "softTrim":
                warnings.add("memory.pressure.soft_trim")
        elif stage == "memory_trim":
            if is_policy_cache_clear(
                level, str(metadata.get("source") or ""), str(metadata.get("reason") or "")
            ):
                stage_kind_counts["policy-cache-clear"] = stage_kind_counts.get(
                    "policy-cache-clear", 0
                ) + 1
                continue
            stage_kind_counts["trim-action"] = stage_kind_counts.get("trim-action", 0) + 1
            if level in {"hardTrim", "fullUnload"}:
                failures.append(f"memory trim reached {level}")
            elif level == "softTrim":
                warnings.add("memory.pressure.soft_trim")
        elif stage == "memory_budget_transition":
            stage_kind_counts["budget-transition"] = stage_kind_counts.get(
                "budget-transition", 0
            ) + 1
            current_band = str(metadata.get("currentBand") or "")
            if current_band == "critical":
                failures.append("memory budget transitioned to critical")
            elif current_band == "guarded":
                warnings.add("memory.pressure.guarded")
        elif stage == "memory_unload":
            stage_kind_counts["unload"] = stage_kind_counts.get("unload", 0) + 1
            failures.append("model unload was recorded during the benchmark take")
        elif "memory_warning" in stage.lower() or "memory warning" in reason:
            stage_kind_counts["application-warning"] = stage_kind_counts.get(
                "application-warning", 0
            ) + 1
            failures.append("application memory warning was recorded")

    comparable_typed = {
        kind: count for kind, count in typed_kind_counts.items() if kind != "memory-exit"
    }
    if comparable_typed != stage_kind_counts:
        failures.append("typed memory events do not match lifecycle marks by kind")

    summary = row.get("summary") or {}
    notes = row.get("notes") or {}
    band = str(
        memory_metrics.get("worstPressureBand")
        or
        notes.get("worstMemoryPressureBand")
        or notes.get("memoryPressureBand")
        or summary.get("worstMemoryPressureBand")
        or "healthy"
    ).lower()
    if band not in PRESSURE_BANDS:
        failures.append(f"invalid memory pressure band {band!r}")
    elif band == "critical":
        failures.append("memory pressure band reached critical")
    elif band == "guarded":
        warnings.add("memory.pressure.guarded")

    for source in (row, notes, summary):
        for key in ("memoryWarningCount", "appMemoryWarningCount", "memoryExitCount"):
            if key in source and _integer(source[key], key) > 0:
                failures.append(f"{key} is nonzero")
        for key in ("memoryExit", "wasJetsamTerminated", "outOfMemory"):
            if source.get(key) is True:
                failures.append(f"{key} is true")
        for key in ("exitReason", "terminationReason"):
            value = str(source.get(key) or "").lower()
            if value and any(token in value for token in ("memory", "jetsam", "oom")):
                failures.append(f"{key} indicates a memory exit")
    return MemoryEventSummary(
        warnings=sorted(warnings),
        failures=failures,
        pressure_event_count=pressure_event_count,
        maximum_pressure_level=maximum_pressure_level,
        trim_count=trim_count,
        maximum_trim=maximum_trim,
        policy_cache_clear_count=policy_cache_clear_count,
    )


@dataclass(frozen=True)
class LayerEvidence:
    layer: str
    digest: str
    samples: tuple[dict[str, Any], ...]
    metrics: dict[str, float | int]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class TakeMemoryEvidence:
    generation_id: str
    status: str
    warnings: tuple[str, ...]
    sidecar_digest: str
    sidecar_digests: dict[str, str]
    metrics: dict[str, float | int]


def _validate_layer(
    *,
    row: dict[str, Any],
    layer: str,
    path: Path,
    platform: str,
) -> LayerEvidence:
    generation_id = str(row.get("generationID") or "?")
    telemetry_schema = _integer(row.get("schemaVersion"), f"{generation_id}.schemaVersion")
    if telemetry_schema < REQUIRED_TELEMETRY_SCHEMA:
        raise MemoryEvidenceError(
            f"generation {generation_id}: memory-qualified publication requires telemetry "
            f"schema v{REQUIRED_TELEMETRY_SCHEMA} or newer"
        )
    summary = row.get("summary")
    if not isinstance(summary, dict):
        raise MemoryEvidenceError(f"generation {generation_id}: missing sampler summary")
    memory_metrics = row.get("memoryMetrics")
    if not isinstance(memory_metrics, dict):
        raise MemoryEvidenceError(f"generation {generation_id}: missing typed memory metrics")
    samples, digest = _read_sidecar(path)
    if samples[0].get("kind") != "start" or samples[-1].get("kind") != "stop":
        raise MemoryEvidenceError(
            f"generation {generation_id} {layer}: sidecar must begin with start and end with stop"
        )
    if sum(sample.get("kind") == "start" for sample in samples) != 1:
        raise MemoryEvidenceError(f"generation {generation_id} {layer}: start sample count is not one")
    if sum(sample.get("kind") == "stop" for sample in samples) != 1:
        raise MemoryEvidenceError(f"generation {generation_id} {layer}: stop sample count is not one")

    previous_elapsed = -1
    previous_uptime = -1
    boundaries: set[str] = set()
    boundary_positions: dict[str, list[int]] = {}
    resident: list[float] = []
    footprint: list[float] = []
    compressed: list[float] = []
    gpu: list[float] = []
    gpu_recommended: list[float] = []
    gpu_ratios: list[float] = []
    headroom: list[float] = []
    implied_limits: list[float] = []
    total_ram: list[float] = []
    periodic_count = 0
    boundary_count = 0
    for index, sample in enumerate(samples):
        prefix = f"generation {generation_id} {layer} sample {index}"
        if sample.get("memoryCaptureSucceeded") is not True:
            raise MemoryEvidenceError(f"{prefix}: process-memory capture failed")
        elapsed = int(_finite(sample.get("capturedElapsedNS"), f"{prefix}.capturedElapsedNS"))
        uptime = int(_finite(sample.get("capturedUptimeNS"), f"{prefix}.capturedUptimeNS"))
        if elapsed < previous_elapsed or uptime < previous_uptime:
            raise MemoryEvidenceError(f"{prefix}: sample clocks are not monotonic")
        previous_elapsed, previous_uptime = elapsed, uptime
        kind = sample.get("kind")
        if kind not in {"start", "periodic", "boundary", "stop"}:
            raise MemoryEvidenceError(f"{prefix}: invalid sample kind {kind!r}")
        if kind == "periodic":
            periodic_count += 1
        if kind == "boundary":
            boundary_count += 1
            boundary = sample.get("boundary")
            if not isinstance(boundary, str) or not boundary:
                raise MemoryEvidenceError(f"{prefix}: boundary name is missing")
            boundaries.add(boundary)
            boundary_positions.setdefault(boundary, []).append(index)
        resident.append(_finite(sample.get("residentMB"), f"{prefix}.residentMB"))
        footprint.append(_finite(sample.get("physFootprintMB"), f"{prefix}.physFootprintMB"))
        compressed.append(_finite(sample.get("compressedMB"), f"{prefix}.compressedMB"))
        gpu.append(_finite(sample.get("gpuAllocatedMB"), f"{prefix}.gpuAllocatedMB"))
        gpu_recommended.append(_finite(
            sample.get("gpuRecommendedWorkingSetMB"),
            f"{prefix}.gpuRecommendedWorkingSetMB",
            minimum=1,
        ))
        if sample.get("metalCaptureSucceeded") is not True:
            raise MemoryEvidenceError(f"{prefix}: Metal memory capture failed")
        gpu_ratios.append(_finite(
            sample.get("gpuWorkingSetUsageRatio"), f"{prefix}.gpuWorkingSetUsageRatio"
        ))
        expected_ratio = gpu[-1] / gpu_recommended[-1]
        if not math.isclose(gpu_ratios[-1], expected_ratio, rel_tol=1e-6, abs_tol=1e-6):
            raise MemoryEvidenceError(f"{prefix}: Metal working-set ratio is not aligned")
        if platform == "ios":
            if sample.get("headroomCaptureSucceeded") is not True:
                raise MemoryEvidenceError(f"{prefix}: process-headroom capture failed")
            headroom.append(_finite(sample.get("headroomMB"), f"{prefix}.headroomMB"))
            implied_limits.append(_finite(
                sample.get("impliedProcessLimitMB"), f"{prefix}.impliedProcessLimitMB",
                minimum=1,
            ))
            total_ram.append(_finite(
                sample.get("totalDeviceRAMMB"), f"{prefix}.totalDeviceRAMMB", minimum=1
            ))
            if not math.isclose(
                implied_limits[-1], footprint[-1] + headroom[-1], rel_tol=1e-6, abs_tol=0.01
            ):
                raise MemoryEvidenceError(f"{prefix}: implied process limit is not aligned")
            if implied_limits[-1] > total_ram[-1] + 0.01:
                raise MemoryEvidenceError(f"{prefix}: implied process limit exceeds total RAM")

    requirements = (
        ENGINE_BOUNDARY_REQUIREMENTS if layer == "engine" else APP_BOUNDARY_REQUIREMENTS
    )
    missing = sorted(
        name for name, alternatives in requirements.items()
        if not boundaries.intersection(alternatives)
    )
    if missing:
        qualifier = "mandatory" if layer == "engine" else "app"
        raise MemoryEvidenceError(
            f"generation {generation_id}: missing {qualifier} memory boundaries: "
            + ", ".join(missing)
        )
    _validate_lifecycle_boundary_order(
        generation_id=generation_id,
        layer=layer,
        boundary_positions=boundary_positions,
    )

    sample_count = _integer(summary.get("sampleCount"), f"{generation_id}.sampleCount", minimum=1)
    summary_periodic = _integer(
        summary.get("periodicSampleCount"), f"{generation_id}.periodicSampleCount"
    )
    summary_boundary = _integer(
        summary.get("boundarySampleCount"), f"{generation_id}.boundarySampleCount"
    )
    capture_failures = _integer(
        summary.get("captureFailureCount"), f"{generation_id}.captureFailureCount"
    )
    missed = _integer(
        summary.get("missedPeriodicDeadlineCount"),
        f"{generation_id}.missedPeriodicDeadlineCount",
    )
    if (sample_count, summary_periodic, summary_boundary) != (
        len(samples), periodic_count, boundary_count
    ):
        raise MemoryEvidenceError(f"generation {generation_id} {layer}: summary/sample counts disagree")
    if capture_failures != 0:
        raise MemoryEvidenceError(f"generation {generation_id} {layer}: capture failures are nonzero")
    coverage_summary = summary.get("captureCoverage")
    if not isinstance(coverage_summary, dict):
        raise MemoryEvidenceError(f"generation {generation_id} {layer}: missing split capture coverage")
    if (
        _integer(coverage_summary.get("totalSampleCount"), "captureCoverage.totalSampleCount")
        != len(samples)
        or _integer(
            coverage_summary.get("memorySuccessfulSampleCount"),
            "captureCoverage.memorySuccessfulSampleCount",
        ) != len(samples)
        or _integer(
            coverage_summary.get("memoryCaptureFailureCount"),
            "captureCoverage.memoryCaptureFailureCount",
        ) != 0
        or not math.isclose(
            _finite(coverage_summary.get("memoryCoverageRatio"), "captureCoverage.memoryCoverageRatio"),
            1.0, rel_tol=0, abs_tol=1e-12,
        )
        or coverage_summary.get("processResourceCaptureSucceeded") is not True
        or _integer(
            coverage_summary.get("processResourceCaptureFailureCount"),
            "captureCoverage.processResourceCaptureFailureCount",
        ) != 0
    ):
        raise MemoryEvidenceError(f"generation {generation_id} {layer}: memory capture coverage is incomplete")
    if (
        _integer(
            coverage_summary.get("metalSuccessfulSampleCount"),
            "captureCoverage.metalSuccessfulSampleCount",
        ) != len(samples)
        or not math.isclose(
            _finite(coverage_summary.get("metalCoverageRatio"), "captureCoverage.metalCoverageRatio"),
            1.0, rel_tol=0, abs_tol=1e-12,
        )
    ):
        raise MemoryEvidenceError(f"generation {generation_id} {layer}: Metal coverage is incomplete")
    if platform == "ios" and (
        _integer(
            coverage_summary.get("headroomSuccessfulSampleCount"),
            "captureCoverage.headroomSuccessfulSampleCount",
        ) != len(samples)
        or not math.isclose(
            _finite(coverage_summary.get("headroomCoverageRatio"), "captureCoverage.headroomCoverageRatio"),
            1.0, rel_tol=0, abs_tol=1e-12,
        )
    ):
        raise MemoryEvidenceError(f"generation {generation_id}: iOS headroom coverage is incomplete")
    if (
        summary.get("resourceCaptureSucceeded") is not True
        or _integer(
            summary.get("resourceCaptureFailureCount"),
            f"{generation_id}.resourceCaptureFailureCount",
        ) != 0
    ):
        raise MemoryEvidenceError(
            f"generation {generation_id} {layer}: process-resource capture failed"
        )
    resource_usage = summary.get("processResourceUsage")
    if not isinstance(resource_usage, dict):
        raise MemoryEvidenceError(
            f"generation {generation_id} {layer}: process-resource usage is missing"
        )
    for key in (
        "userCPUTimeMS", "systemCPUTimeMS", "minorPageFaults", "majorPageFaults",
        "voluntaryContextSwitches", "involuntaryContextSwitches",
        "blockInputOperations", "blockOutputOperations",
    ):
        _finite(resource_usage.get(key), f"{generation_id}.processResourceUsage.{key}")
    boundary_coverage = summary.get("boundaryCoverage")
    if (
        not isinstance(boundary_coverage, dict)
        or boundary_coverage.get("missingBoundaryNames") != []
        or not math.isclose(
            _finite(boundary_coverage.get("coverageRatio"), "boundaryCoverage.coverageRatio"),
            1.0, rel_tol=0, abs_tol=1e-12,
        )
    ):
        raise MemoryEvidenceError(f"generation {generation_id} {layer}: mandatory boundary coverage failed")
    expected_boundary_names = (
        ENGINE_REQUIRED_BOUNDARY_NAMES if layer == "engine" else APP_REQUIRED_BOUNDARY_NAMES
    )
    if set(boundary_coverage.get("requiredBoundaryNames") or []) != expected_boundary_names:
        raise MemoryEvidenceError(
            f"generation {generation_id} {layer}: boundary contract names are incomplete"
        )
    if memory_metrics.get("captureCoverage") != coverage_summary:
        raise MemoryEvidenceError(
            f"generation {generation_id} {layer}: typed capture coverage disagrees with summary"
        )
    if memory_metrics.get("boundaryCoverage") != boundary_coverage:
        raise MemoryEvidenceError(
            f"generation {generation_id} {layer}: typed boundary coverage disagrees with summary"
        )
    expected_role = "app" if layer == "app" else {
        "engine", "engine-service", "current-process",
    }
    sample_roles = {sample.get("processRole") for sample in samples}
    summary_role = summary.get("processRole")
    typed_role = memory_metrics.get("processRole")
    if layer == "app":
        roles_valid = sample_roles == {expected_role} and summary_role == expected_role and typed_role == expected_role
    else:
        roles_valid = (
            len(sample_roles) == 1
            and next(iter(sample_roles)) in expected_role
            and summary_role in expected_role
            and typed_role == summary_role
        )
    if not roles_valid:
        raise MemoryEvidenceError(f"generation {generation_id} {layer}: process role is inconsistent")

    target_ns = _finite(summary.get("targetIntervalNS"), f"{generation_id}.targetIntervalNS", minimum=1)
    elapsed_opportunities = max(0, int((previous_elapsed - int(samples[0]["capturedElapsedNS"])) // target_ns))
    expected = max(periodic_count + missed, elapsed_opportunities)
    coverage = 1.0 if expected == 0 else min(1.0, periodic_count / expected)
    if coverage + 1e-12 < MINIMUM_COVERAGE:
        raise MemoryEvidenceError(
            f"generation {generation_id} {layer}: sampler coverage {coverage:.3%} is below 95%"
        )
    warnings: list[str] = []
    if coverage + 1e-12 < PERFECT_COVERAGE:
        warnings.append("memory.sampler.coverage")

    def match(summary_key: str, actual: float) -> None:
        value = _finite(summary.get(summary_key), f"{generation_id}.{summary_key}")
        if not math.isclose(value, actual, rel_tol=1e-6, abs_tol=1e-6):
            raise MemoryEvidenceError(
                f"generation {generation_id} {layer}: {summary_key} does not match sidecar"
            )

    match("residentPeakMB", max(resident))
    match("physFootprintPeakMB", max(footprint))
    match("compressedPeakMB", max(compressed))
    match("gpuAllocatedPeakMB", max(gpu))
    match("gpuRecommendedWorkingSetMB", max(gpu_recommended))
    match("gpuWorkingSetUsageRatioPeak", max(gpu_ratios))
    if platform == "ios":
        match("headroomMinMB", min(headroom))
        match("totalDeviceRAMMB", min(total_ram))

    max_gpu_recommended = max(gpu_recommended)
    gpu_ratio = max(gpu_ratios)
    peak_index = max(range(len(footprint)), key=footprint.__getitem__)
    metrics: dict[str, float | int] = {
        "residentStartMB": resident[0],
        "residentEndMB": resident[-1],
        "residentDeltaMB": resident[-1] - resident[0],
        "peakResidentMB": max(resident),
        "physicalFootprintStartMB": footprint[0],
        "physicalFootprintEndMB": footprint[-1],
        "physicalFootprintDeltaMB": footprint[-1] - footprint[0],
        "peakPhysicalFootprintMB": max(footprint),
        "peakCompressedMB": max(compressed),
        "peakGPUAllocatedMB": max(gpu),
        "gpuRecommendedWorkingSetMB": max_gpu_recommended,
        "gpuWorkingSetUsageRatioPeak": gpu_ratio,
        "memoryTimeToPeakMS": (
            int(samples[peak_index]["capturedElapsedNS"])
            - int(samples[0]["capturedElapsedNS"])
        ) / 1_000_000,
        "samplerSampleCount": len(samples),
        "samplerPeriodicSampleCount": periodic_count,
        "samplerBoundarySampleCount": boundary_count,
        "samplerCaptureFailureCount": 0,
        "samplerMissedDeadlineCount": missed,
        "samplerCoverage": coverage,
        "samplerTargetIntervalMS": target_ns / 1_000_000,
    }
    if layer == "engine":
        mlx_fields = {
            "mlxCumulativePeakMB": "mlxPeakMB",
            "mlxActivePeakMB": "mlxActivePeakMB",
            "mlxCachePeakMB": "mlxCachePeakMB",
        }
        for source, destination in mlx_fields.items():
            metrics[destination] = _finite(
                memory_metrics.get(source), f"{generation_id}.memoryMetrics.{source}"
            )
        mlx_stage_count = _integer(
            memory_metrics.get("mlxStageCount"), "memoryMetrics.mlxStageCount", minimum=1
        )
        mlx_stage_names = memory_metrics.get("mlxStageNames")
        if (
            not isinstance(mlx_stage_names, list)
            or any(not isinstance(name, str) or not name for name in mlx_stage_names)
            or len(mlx_stage_names) != min(mlx_stage_count, 64)
        ):
            raise MemoryEvidenceError(
                f"generation {generation_id}: MLX stage count/names are inconsistent"
            )
    if platform == "ios":
        budget = [used + available for used, available in zip(footprint, headroom, strict=True)]
        utilization = [used / total if total > 0 else 0.0 for used, total in zip(footprint, budget, strict=True)]
        metrics.update({
            "headroomStartMB": headroom[0],
            "headroomEndMB": headroom[-1],
            "minimumHeadroomMB": min(headroom),
            "peakProcessBudgetUtilization": max(utilization),
            "impliedProcessLimitMB": min(implied_limits),
            "totalDeviceRAMMB": min(total_ram),
        })
    return LayerEvidence(layer, digest, tuple(samples), metrics, tuple(warnings))


def _aligned_macos_metrics(engine: LayerEvidence, app: LayerEvidence) -> dict[str, float | int]:
    engine_samples = list(engine.samples)
    app_samples = list(app.samples)
    if not engine_samples or not app_samples:
        raise MemoryEvidenceError("macOS aggregate memory evidence has an empty layer")
    cadence_ns = int(max(
        float(engine.metrics["samplerTargetIntervalMS"]),
        float(app.metrics["samplerTargetIntervalMS"]),
    ) * 1_000_000)
    # Pair within one declared cadence using the shared absolute uptime clock.
    # Pairing is based on absolute uptime. Reuse is intentional: lifecycle
    # boundary samples make the two layers uneven, so each sample is associated
    # with the nearest sample in the other layer and duplicate pairs are then
    # removed. Aggregate peaks still come only from real same-window pairs.
    overlap_start = max(
        int(engine_samples[0]["capturedUptimeNS"]), int(app_samples[0]["capturedUptimeNS"])
    )
    overlap_end = min(
        int(engine_samples[-1]["capturedUptimeNS"]), int(app_samples[-1]["capturedUptimeNS"])
    )
    if overlap_end < overlap_start:
        raise MemoryEvidenceError("macOS app/engine memory sidecars have no active overlap")
    engine_overlap = [
        (index, sample) for index, sample in enumerate(engine_samples)
        if overlap_start <= int(sample["capturedUptimeNS"]) <= overlap_end
    ]
    app_overlap = [
        (index, sample) for index, sample in enumerate(app_samples)
        if overlap_start <= int(sample["capturedUptimeNS"]) <= overlap_end
    ]
    if not engine_overlap or not app_overlap:
        raise MemoryEvidenceError("macOS app/engine memory sidecars have no overlap samples")
    pair_indexes: set[tuple[int, int]] = set()
    # A generation's app sampler starts just before the XPC engine sampler and
    # stops just after it.  Keep the denominator limited to the true active
    # overlap, but allow the nearest same-generation sample from either edge as
    # a pairing candidate when it is still within one cadence.  Excluding that
    # edge sample makes sub-millisecond startup skew look like a 500 ms hole:
    # the next periodic app sample can land a few milliseconds beyond the
    # cadence even though both samplers captured the boundary successfully.
    all_engine = list(enumerate(engine_samples))
    all_app = list(enumerate(app_samples))
    for engine_index, engine_sample in engine_overlap:
        engine_time = int(engine_sample["capturedUptimeNS"])
        app_index, candidate = min(
            all_app,
            key=lambda item: abs(int(item[1]["capturedUptimeNS"]) - engine_time),
        )
        if abs(int(candidate["capturedUptimeNS"]) - engine_time) <= cadence_ns:
            pair_indexes.add((engine_index, app_index))
    for app_index, app_sample in app_overlap:
        app_time = int(app_sample["capturedUptimeNS"])
        engine_index, candidate = min(
            all_engine,
            key=lambda item: abs(int(item[1]["capturedUptimeNS"]) - app_time),
        )
        if abs(int(candidate["capturedUptimeNS"]) - app_time) <= cadence_ns:
            pair_indexes.add((engine_index, app_index))
    pairs = [
        (engine_samples[engine_index], app_samples[app_index])
        for engine_index, app_index in sorted(
            pair_indexes,
            key=lambda item: (
                max(
                    int(engine_samples[item[0]]["capturedUptimeNS"]),
                    int(app_samples[item[1]]["capturedUptimeNS"]),
                ),
                item,
            ),
        )
    ]
    if not pairs:
        raise MemoryEvidenceError("macOS app/engine memory sidecars have no uptime-aligned samples")
    engine_overlap_indexes = {index for index, _ in engine_overlap}
    app_overlap_indexes = {index for index, _ in app_overlap}
    paired_engine_indexes = {
        engine_index for engine_index, _ in pair_indexes
        if engine_index in engine_overlap_indexes
    }
    paired_app_indexes = {
        app_index for _, app_index in pair_indexes
        if app_index in app_overlap_indexes
    }
    engine_coverage = len(paired_engine_indexes) / max(1, len(engine_overlap))
    app_coverage = len(paired_app_indexes) / max(1, len(app_overlap))
    paired_coverage = min(engine_coverage, app_coverage)
    if paired_coverage + 1e-12 < MINIMUM_COVERAGE:
        raise MemoryEvidenceError(
            f"macOS app/engine aligned-sample coverage {paired_coverage:.3%} is below 95%"
        )
    resident = [
        float(engine_sample["residentMB"]) + float(app_sample["residentMB"])
        for engine_sample, app_sample in pairs
    ]
    footprint = [
        float(engine_sample["physFootprintMB"]) + float(app_sample["physFootprintMB"])
        for engine_sample, app_sample in pairs
    ]
    compressed = [
        float(engine_sample["compressedMB"]) + float(app_sample["compressedMB"])
        for engine_sample, app_sample in pairs
    ]
    gpu = [
        float(engine_sample["gpuAllocatedMB"]) + float(app_sample["gpuAllocatedMB"])
        for engine_sample, app_sample in pairs
    ]
    gpu_recommended: list[float] = []
    for engine_sample, app_sample in pairs:
        engine_recommended = float(engine_sample["gpuRecommendedWorkingSetMB"])
        app_recommended = float(app_sample["gpuRecommendedWorkingSetMB"])
        if not math.isclose(
            engine_recommended, app_recommended, rel_tol=0.01, abs_tol=1.0
        ):
            raise MemoryEvidenceError(
                "macOS app/engine Metal recommended working-set limits disagree"
            )
        # This is a device-wide recommendation, not a per-process allowance;
        # summing it would double the denominator and understate GPU pressure.
        gpu_recommended.append(min(engine_recommended, app_recommended))
    gpu_ratios = [
        allocated / recommended
        for allocated, recommended in zip(gpu, gpu_recommended, strict=True)
    ]
    peak_index = max(range(len(footprint)), key=footprint.__getitem__)
    aligned_times = [
        max(
            int(engine_sample["capturedUptimeNS"]),
            int(app_sample["capturedUptimeNS"]),
        )
        for engine_sample, app_sample in pairs
    ]
    first_time = aligned_times[0]
    peak_time = aligned_times[peak_index]
    return {
        "alignedProcessSampleCount": len(pairs),
        "alignedProcessSampleCoverage": paired_coverage,
        "alignedEngineSampleCoverage": engine_coverage,
        "alignedAppSampleCoverage": app_coverage,
        "residentStartMB": resident[0],
        "residentEndMB": resident[-1],
        "residentDeltaMB": resident[-1] - resident[0],
        "peakResidentMB": max(resident),
        "physicalFootprintStartMB": footprint[0],
        "physicalFootprintEndMB": footprint[-1],
        "physicalFootprintDeltaMB": footprint[-1] - footprint[0],
        "peakPhysicalFootprintMB": max(footprint),
        "peakCompressedMB": max(compressed),
        "peakGPUAllocatedMB": max(gpu),
        "gpuRecommendedWorkingSetMB": min(gpu_recommended),
        "gpuWorkingSetUsageRatioPeak": max(gpu_ratios),
        "memoryTimeToPeakMS": (peak_time - first_time) / 1_000_000,
    }


def qualify_take_memory(
    *,
    row: dict[str, Any],
    diagnostics: Path,
    platform: str,
    app_row: dict[str, Any] | None = None,
    require_app_layer: bool = False,
) -> TakeMemoryEvidence:
    if platform not in {"ios", "macos"}:
        raise MemoryEvidenceError(f"unsupported memory-evidence platform {platform!r}")
    generation_id = row.get("generationID")
    if not isinstance(generation_id, str) or not generation_id:
        raise MemoryEvidenceError("memory evidence row has no generationID")
    engine = _validate_layer(
        row=row,
        layer="engine",
        path=_find_exact_sidecar(diagnostics, "engine", generation_id),
        platform=platform,
    )
    layers = [engine]
    metrics = dict(engine.metrics)
    if platform == "macos" and require_app_layer:
        if not isinstance(app_row, dict) or app_row.get("generationID") != generation_id:
            raise MemoryEvidenceError(f"generation {generation_id}: missing matching macOS app row")
        app = _validate_layer(
            row=app_row,
            layer="app",
            path=_find_exact_sidecar(diagnostics, "app", generation_id),
            platform=platform,
        )
        layers.append(app)
        metrics = _aligned_macos_metrics(engine, app)
        # Keep layer-level coverage/capture health without conflating layer peaks.
        metrics.update({
            "samplerSampleCount": sum(int(layer.metrics["samplerSampleCount"]) for layer in layers),
            "samplerPeriodicSampleCount": sum(int(layer.metrics["samplerPeriodicSampleCount"]) for layer in layers),
            "samplerBoundarySampleCount": sum(int(layer.metrics["samplerBoundarySampleCount"]) for layer in layers),
            "samplerCaptureFailureCount": 0,
            "samplerMissedDeadlineCount": sum(int(layer.metrics["samplerMissedDeadlineCount"]) for layer in layers),
            "samplerCoverage": min(float(layer.metrics["samplerCoverage"]) for layer in layers),
            "samplerTargetIntervalMS": max(float(layer.metrics["samplerTargetIntervalMS"]) for layer in layers),
            # MLX accounting is process-local to the engine service and must
            # survive the replacement of process-memory metrics by aligned
            # app+engine aggregates.
            "mlxPeakMB": engine.metrics["mlxPeakMB"],
            "mlxActivePeakMB": engine.metrics["mlxActivePeakMB"],
            "mlxCachePeakMB": engine.metrics["mlxCachePeakMB"],
        })

    events = _memory_warnings_and_failures(row)
    pressure_warnings = list(events.warnings)
    pressure_failures = list(events.failures)
    pressure_event_count = events.pressure_event_count
    maximum_pressure_level = events.maximum_pressure_level
    trim_count = events.trim_count
    maximum_trim = events.maximum_trim
    policy_cache_clear_count = events.policy_cache_clear_count
    if platform == "macos" and require_app_layer and app_row is not None:
        app_events = _memory_warnings_and_failures(app_row)
        pressure_warnings.extend(app_events.warnings)
        pressure_failures.extend(app_events.failures)
        pressure_event_count += app_events.pressure_event_count
        maximum_pressure_level = max(maximum_pressure_level, app_events.maximum_pressure_level)
        trim_count += app_events.trim_count
        maximum_trim = max(maximum_trim, app_events.maximum_trim)
        policy_cache_clear_count += app_events.policy_cache_clear_count
    if pressure_failures:
        raise MemoryEvidenceError(
            f"generation {generation_id}: " + "; ".join(sorted(set(pressure_failures)))
        )
    warnings = sorted(set(pressure_warnings).union(*(layer.warnings for layer in layers)))
    if (
        platform == "macos"
        and require_app_layer
        and float(metrics["alignedProcessSampleCoverage"]) < PERFECT_COVERAGE
    ):
        warnings = sorted(set(warnings).union({"memory.alignment.coverage"}))
    if platform == "ios":
        peak_footprint = float(metrics["peakPhysicalFootprintMB"])
        minimum_headroom = float(metrics["minimumHeadroomMB"])
        metal_ratio = float(metrics["gpuWorkingSetUsageRatioPeak"])
        if peak_footprint >= 5.2 * 1024:
            raise MemoryEvidenceError(
                f"generation {generation_id}: physical footprint reached the 5.2 GiB failure limit"
            )
        if minimum_headroom < 384:
            raise MemoryEvidenceError(
                f"generation {generation_id}: process headroom fell below 384 MiB"
            )
        if metal_ratio >= 0.8:
            raise MemoryEvidenceError(
                f"generation {generation_id}: Metal working-set ratio reached 0.8"
            )
        if peak_footprint >= 4.5 * 1024:
            warnings.append("memory.footprint.guarded")
        if minimum_headroom < 768:
            warnings.append("memory.headroom.guarded")
        warnings = sorted(set(warnings))
    metrics.update({
        "memoryPressureEventCount": pressure_event_count,
        "maximumPressureLevel": maximum_pressure_level,
        "memoryTrimCount": trim_count,
        "maximumTrimLevel": maximum_trim,
        "policyCacheClearCount": policy_cache_clear_count,
        "memoryWarningCount": 0,
        "memoryExitCount": 0,
    })
    sidecar_digests = {layer.layer: layer.digest for layer in layers}
    combined_digest = _sha256_bytes(_canonical_bytes([
        {"layer": layer.layer, "digest": layer.digest} for layer in layers
    ]))
    return TakeMemoryEvidence(
        generation_id=generation_id,
        status="qualifiedWithWarnings" if warnings else "qualified",
        warnings=tuple(warnings),
        sidecar_digest=combined_digest,
        sidecar_digests=sidecar_digests,
        metrics=metrics,
    )


def qualify_memory_rows(
    *,
    rows: Iterable[dict[str, Any]],
    diagnostics: Path,
    platform: str,
    app_rows: Iterable[dict[str, Any]] | None = None,
    require_app_layer: bool = False,
) -> tuple[list[TakeMemoryEvidence], dict[str, Any]]:
    selected = list(rows)
    app_by_id = {
        row.get("generationID"): row for row in (app_rows or [])
        if isinstance(row, dict) and isinstance(row.get("generationID"), str)
    }
    qualified = [
        qualify_take_memory(
            row=row,
            diagnostics=diagnostics,
            platform=platform,
            app_row=app_by_id.get(row.get("generationID")),
            require_app_layer=require_app_layer,
        )
        for row in selected
    ]
    if not qualified:
        raise MemoryEvidenceError("memory qualification selected no generations")
    aggregate_payload = [
        {
            "generationID": item.generation_id,
            "digest": item.sidecar_digest,
            "layers": item.sidecar_digests,
        }
        for item in qualified
    ]
    warnings = sorted({warning for item in qualified for warning in item.warnings})
    return qualified, {
        "memoryContractVersion": MEMORY_CONTRACT_VERSION,
        "memoryQualified": True,
        "sampleSidecarCount": sum(len(item.sidecar_digests) for item in qualified),
        "sampleSidecarsDigest": _sha256_bytes(_canonical_bytes(aggregate_payload)),
        "status": "qualifiedWithWarnings" if warnings else "qualified",
        "warnings": warnings,
        "digestPayload": aggregate_payload,
    }
