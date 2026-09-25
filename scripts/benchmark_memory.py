#!/usr/bin/env python3
"""Strict, run-scoped memory evidence for benchmark publication.

Raw sampler sidecars are intentionally untracked.  This module validates the
exact sidecars selected by a benchmark, derives a small allowlisted summary,
and returns digests that bind the tracked record to those raw samples.

Memory contract v2 (since 2026-09-25): one process gets one memory series.
iOS is a single-process engine/app runtime, and so is macOS since 2026-09-15:
the macOS app-layer and engine-layer samplers both read the one hosting
process, so their samples are merged into one series (never summed) and the
app sidecar adds its samples, its coverage and its submit/terminal order.  A
take qualifies when no gap between consecutive samples exceeds the policy's
unobserved-gap bound (`unobservedGapBound` in
config/memory-qualification-policy.json: a multiple of the sampler cadence with
an absolute floor, higher on the floor tiers, provisional until a consented lane
calibrates it), and each
take publishes the bound it met and how far its sampled peaks fell short of the
exact high-water marks (the MLX allocator's per-request peak and, when the
sampler read it, the kernel's physical-footprint ledger peak).

Contract v1 records (before 2026-09-25) summed uptime-paired app and engine
samples and required 95% periodic coverage; they are never rewritten and the
history validator keeps judging them by those rules.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable


MEMORY_CONTRACT_VERSION = 2
REQUIRED_TELEMETRY_SCHEMA = 8
# Timer health (contract v2): the longest stretch in which the process's memory
# went unobserved, between any two consecutive samples of its one series, may
# not exceed the policy's bound: max(multiple x the sampler's target interval,
# an absolute floor), the floor tiers (8 GB Mac, iPhone) keeping their own floor
# until a record of theirs calibrates it. Each take records the bound it met.
MEMORY_QUALIFICATION_POLICY_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "memory-qualification-policy.json"
)
UNOBSERVED_GAP_POLICY_KEY = "unobservedGapBound"
UNOBSERVED_GAP_FLOOR_TIERS_KEY = "floorTiers"
UNOBSERVED_GAP_STATUSES = frozenset({"provisional", "calibrated"})
# `NativeDeviceMemoryClass` raw values (Sources/QwenVoiceCore/SemanticTypes.swift).
NATIVE_DEVICE_CLASSES = frozenset({"floor_8gb_mac", "mid_16gb_mac", "high_memory_mac", "iphone_pro"})
# The kernel footprint ledger peak and the sampled footprint come from the same
# task_info call; a ledger peak below a sample (beyond rounding) is a broken read.
KERNEL_LEDGER_TOLERANCE_MB = 1.0
# Optional per-sample kernel ledgers read from the same task_vm_info call as
# the footprint: the process-lifetime physical-footprint high-water mark and
# the graphics-tagged footprint.
KERNEL_PEAK_SAMPLE_KEY = "kernelPhysFootprintPeakMB"
# The kernel's limit_bytes_remaining, read in the same call as the footprint
# (iPhone samples since 2026-09-25, audit #68).
LIMIT_REMAINING_SAMPLE_KEY = "processLimitRemainingMB"
GRAPHICS_SAMPLE_KEY = "graphicsFootprintMB"
# The end-of-take MLX snapshot (retained-memory-v2), in order of preference:
# after the routine post-generation cache clear, else after the stream.
MLX_END_OF_TAKE_STAGES = ("after_generation_trim", "after_stream")
# The iPhone memory bands, declared once for the app's shipping budget policy
# and this publication gate (audit V-4; a Swift test pins the Swift side).
IOS_MEMORY_BUDGET_POLICY_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "ios-memory-budget-policy.json"
)
IOS_MEMORY_BUDGET_KEYS = (
    "healthyHeadroomMB", "guardedHeadroomMB", "guardedFootprintMB", "criticalFootprintMB",
    "criticalGPUWorkingSetUsageRatio",
    # The evidence gate on the measured process budget (audit #68).
    "evidenceGuardedBudgetUtilization", "evidenceCriticalBudgetUtilization",
)

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


@dataclass(frozen=True)
class UnobservedGapBound:
    """The longest gap a memory-qualified take's one series may leave (contract v2)."""

    target_interval_multiple: float
    floor_ms: float
    floor_tier_floor_ms: float
    floor_tier_device_classes: frozenset[str]

    def is_floor_tier(self, platform: str, device_class: Any) -> bool:
        """Whether a take belongs to a floor tier: every iPhone, and a Mac whose
        engine row stamps a floor-tier device class (forced or not)."""
        return platform == "ios" or device_class in self.floor_tier_device_classes

    def limit_ms(self, target_interval_ms: float, *, floor_tier: bool = False) -> float:
        floor = self.floor_tier_floor_ms if floor_tier else self.floor_ms
        return max(self.target_interval_multiple * target_interval_ms, floor)


def _gap_number(block: dict[str, Any], key: str, minimum: float, location: str) -> float:
    value = block.get(key)
    if (
        isinstance(value, bool) or not isinstance(value, (int, float))
        or not math.isfinite(value) or value < minimum
    ):
        raise MemoryEvidenceError(f"{location}.{key} must be a finite number of at least {minimum:g}")
    return float(value)


def _require_gap_calibration_status(block: dict[str, Any], location: str) -> None:
    status = block.get("status")
    run_id = block.get("calibrationRunID")
    if status not in UNOBSERVED_GAP_STATUSES or (
        (status == "calibrated") != (isinstance(run_id, str) and bool(run_id))
    ) or (status == "provisional" and run_id is not None):
        raise MemoryEvidenceError(
            f"{location} status must be provisional (no run ID) or calibrated (with its run ID)"
        )


def load_unobserved_gap_bound(path: Path | None = None) -> UnobservedGapBound:
    """The declared unobserved-gap bound; fails closed on a missing or malformed block."""
    source = path or MEMORY_QUALIFICATION_POLICY_PATH
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MemoryEvidenceError(f"memory qualification policy is unreadable: {error}") from error
    block = document.get(UNOBSERVED_GAP_POLICY_KEY) if isinstance(document, dict) else None
    if not isinstance(block, dict):
        raise MemoryEvidenceError(
            f"memory qualification policy has no {UNOBSERVED_GAP_POLICY_KEY} block"
        )
    multiple = _gap_number(block, "targetIntervalMultiple", 1.0, UNOBSERVED_GAP_POLICY_KEY)
    floor = _gap_number(block, "floorMS", 0.0, UNOBSERVED_GAP_POLICY_KEY)
    _require_gap_calibration_status(block, UNOBSERVED_GAP_POLICY_KEY)
    tiers_location = f"{UNOBSERVED_GAP_POLICY_KEY}.{UNOBSERVED_GAP_FLOOR_TIERS_KEY}"
    tiers = block.get(UNOBSERVED_GAP_FLOOR_TIERS_KEY)
    if not isinstance(tiers, dict):
        raise MemoryEvidenceError(f"memory qualification policy has no {tiers_location} block")
    classes = tiers.get("deviceClasses")
    if (
        not isinstance(classes, list) or not classes
        or not all(isinstance(value, str) for value in classes)
        or len(set(classes)) != len(classes)
        or not set(classes) <= NATIVE_DEVICE_CLASSES
        or "iphone_pro" not in classes
    ):
        raise MemoryEvidenceError(
            f"{tiers_location}.deviceClasses must list distinct native device classes, "
            "the iPhone's included"
        )
    # A floor tier's floor never undercuts the general floor.
    tier_floor = _gap_number(tiers, "floorMS", floor, tiers_location)
    _require_gap_calibration_status(tiers, tiers_location)
    return UnobservedGapBound(multiple, floor, tier_floor, frozenset(classes))


def load_ios_memory_budget(path: Path | None = None) -> dict[str, float]:
    """The declared iPhone memory bands; fails closed on a missing or malformed contract."""
    source = path or IOS_MEMORY_BUDGET_POLICY_PATH
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MemoryEvidenceError(f"iOS memory budget policy is unreadable: {error}") from error
    if not isinstance(document, dict) or document.get("schemaVersion") != 1:
        raise MemoryEvidenceError("iOS memory budget policy must be a schemaVersion 1 object")
    bands: dict[str, float] = {}
    for key in IOS_MEMORY_BUDGET_KEYS:
        value = document.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise MemoryEvidenceError(f"iOS memory budget policy {key} must be a positive number")
        bands[key] = float(value)
    if not (
        bands["guardedHeadroomMB"] < bands["healthyHeadroomMB"]
        and bands["guardedFootprintMB"] < bands["criticalFootprintMB"]
        and bands["criticalGPUWorkingSetUsageRatio"] <= 1
        and bands["evidenceGuardedBudgetUtilization"]
        < bands["evidenceCriticalBudgetUtilization"] <= 1
    ):
        raise MemoryEvidenceError("iOS memory budget policy bands are out of order")
    return bands


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
    # Per-sample kernel ledgers, in sample order; empty when not sampled. A
    # graphics value is None on a sample whose read the sampler dropped.
    kernel_peaks: tuple[float, ...] = ()
    graphics: tuple[float | None, ...] = ()


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
    uptimes: list[int] = []
    # Optional kernel ledgers (samplers since 2026-09-25). The footprint peak
    # is all or none; the graphics ledger is only reported, so a sample whose
    # read the sampler dropped (a negative ledger) is tolerated as None.
    kernel_peaks: list[float] = []
    graphics: list[float | None] = []
    kernel_present = any(KERNEL_PEAK_SAMPLE_KEY in sample for sample in samples)
    graphics_present = any(GRAPHICS_SAMPLE_KEY in sample for sample in samples)
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
        uptimes.append(uptime)
        if kernel_present:
            # Not checked for monotonicity in sidecar order: a sample reads its
            # clocks before task_info, and a periodic capture preempted between
            # the two can read the ledger after a later-stamped boundary
            # capture, so a new high can sort first. Only the series-level
            # bound (the ledger's max covers the sampled footprint's max) holds
            # under every interleaving; see `_apply_peak_fidelity`.
            kernel_peaks.append(_finite(
                sample.get(KERNEL_PEAK_SAMPLE_KEY), f"{prefix}.{KERNEL_PEAK_SAMPLE_KEY}"
            ))
        if graphics_present:
            graphics.append(
                _finite(sample[GRAPHICS_SAMPLE_KEY], f"{prefix}.{GRAPHICS_SAMPLE_KEY}")
                if GRAPHICS_SAMPLE_KEY in sample else None
            )
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
    # Deadlines honoured: informational since contract v2, which gates on the
    # longest unobserved gap of the process's series instead (audit #66).
    coverage = 1.0 if expected == 0 else min(1.0, periodic_count / expected)
    warnings: list[str] = []

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
    # The typed summary repeats the ledgers when the sampler read them.
    for summary_key, values, pick in (
        ("kernelPhysFootprintPeakStartMB", kernel_peaks, 0),
        ("kernelPhysFootprintPeakMB", kernel_peaks, -1),
        ("graphicsFootprintEndMB", graphics, -1),
    ):
        if summary_key in summary:
            if not values or values[pick] is None:
                raise MemoryEvidenceError(
                    f"generation {generation_id} {layer}: {summary_key} has no sampled ledger"
                )
            match(summary_key, float(values[pick]))

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
        "samplerMaximumUnobservedGapMS": _maximum_gap_ms(uptimes),
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
        if (end_of_take := _mlx_end_of_take(row, generation_id)) is not None:
            metrics["mlxEndActiveMB"], metrics["mlxEndCacheMB"] = end_of_take
    if platform == "ios":
        # The budget each sample measured: footprint plus what remained before
        # the process limit, from the same task_vm_info call when the sample
        # carries it (audit #68), else from the separate headroom reading.
        remaining = [
            float(sample[LIMIT_REMAINING_SAMPLE_KEY])
            if isinstance(sample.get(LIMIT_REMAINING_SAMPLE_KEY), (int, float))
            and not isinstance(sample.get(LIMIT_REMAINING_SAMPLE_KEY), bool)
            and math.isfinite(float(sample[LIMIT_REMAINING_SAMPLE_KEY]))
            and float(sample[LIMIT_REMAINING_SAMPLE_KEY]) >= 0
            else available
            for sample, available in zip(samples, headroom, strict=True)
        ]
        budget = [used + left for used, left in zip(footprint, remaining, strict=True)]
        utilization = [used / total if total > 0 else 0.0 for used, total in zip(footprint, budget, strict=True)]
        metrics.update({
            "headroomStartMB": headroom[0],
            "headroomEndMB": headroom[-1],
            "minimumHeadroomMB": min(headroom),
            "peakProcessBudgetUtilization": max(utilization),
            "impliedProcessLimitMB": min(implied_limits),
            "totalDeviceRAMMB": min(total_ram),
        })
        same_call = [
            abs(float(sample[LIMIT_REMAINING_SAMPLE_KEY]) - available)
            for sample, available in zip(samples, headroom, strict=True)
            if isinstance(sample.get(LIMIT_REMAINING_SAMPLE_KEY), (int, float))
            and not isinstance(sample.get(LIMIT_REMAINING_SAMPLE_KEY), bool)
        ]
        if same_call:
            # How far the kernel's limit_bytes_remaining and os_proc_available_memory
            # disagree on one sample: the device run that proves they measure
            # the same budget reads this (audit #68).
            metrics["processLimitRemainingDriftMB"] = max(same_call)
    return LayerEvidence(
        layer, digest, tuple(samples), metrics, tuple(warnings),
        tuple(kernel_peaks), tuple(graphics),
    )


def _mlx_end_of_take(row: dict[str, Any], generation_id: str) -> tuple[float, float] | None:
    """MLX active and cache memory at the end of a take (retained-memory-v2).

    The snapshot after the routine post-generation cache clear when the tier
    runs one, otherwise the one after the stream; None when the row has
    neither (older or failed rows).
    """
    stages = row.get("mlxMemoryByStage")
    if not isinstance(stages, dict):
        return None
    for stage in MLX_END_OF_TAKE_STAGES:
        snapshot = stages.get(stage)
        if isinstance(snapshot, dict):
            location = f"{generation_id}.mlxMemoryByStage.{stage}"
            return (
                _finite(snapshot.get("activeMB"), f"{location}.activeMB"),
                _finite(snapshot.get("cacheMB"), f"{location}.cacheMB"),
            )
    return None


def _maximum_gap_ms(uptimes: Iterable[int]) -> float:
    """The longest interval, in ms, between two consecutive samples of one series."""
    ordered = sorted(uptimes)
    return max(
        (later - earlier for earlier, later in zip(ordered, ordered[1:])), default=0
    ) / 1_000_000


def _process_identifier(row: dict[str, Any] | None) -> int | None:
    value = row.get("processIdentifier") if isinstance(row, dict) else None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _one_process_series(
    engine: LayerEvidence, app: LayerEvidence
) -> tuple[dict[str, float | int], list[float], list[float | None]]:
    """One memory series for the one process both macOS layers sampled (contract v2).

    Since 2026-09-15 the engine runs inside the app process, so the app-layer
    and engine-layer samplers are two readers of one process: every value is
    the whole process, and adding them would count it twice (audit #1/#2).
    The series is the union of both layers' samples in absolute-uptime order,
    a duplicate uptime kept once (the engine's), so it spans the app's
    submit-to-terminal window. Returns the series metrics and its kernel
    ledgers in the same order.
    """
    entries = sorted(
        (int(sample["capturedUptimeNS"]), order, index)
        for order, layer in enumerate((engine, app))
        for index, sample in enumerate(layer.samples)
    )
    layers = (engine, app)
    series: list[tuple[int, LayerEvidence, int]] = []
    seen: set[int] = set()
    for uptime, order, index in entries:
        if uptime in seen:
            continue
        seen.add(uptime)
        series.append((uptime, layers[order], index))
    samples = [layer.samples[index] for _, layer, index in series]
    uptimes = [uptime for uptime, _, _ in series]
    resident = [float(sample["residentMB"]) for sample in samples]
    footprint = [float(sample["physFootprintMB"]) for sample in samples]
    compressed = [float(sample["compressedMB"]) for sample in samples]
    gpu = [float(sample["gpuAllocatedMB"]) for sample in samples]
    recommended = [float(sample["gpuRecommendedWorkingSetMB"]) for sample in samples]
    reference = max(recommended)
    if any(
        not math.isclose(value, reference, rel_tol=0.01, abs_tol=1.0) for value in recommended
    ):
        # A device-wide recommendation: both readers must report the same one.
        raise MemoryEvidenceError(
            "macOS app/engine Metal recommended working-set limits disagree"
        )
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
        "gpuRecommendedWorkingSetMB": reference,
        "gpuWorkingSetUsageRatioPeak": max(
            allocated / limit for allocated, limit in zip(gpu, recommended, strict=True)
        ),
        "memoryTimeToPeakMS": (uptimes[peak_index] - uptimes[0]) / 1_000_000,
        "samplerMaximumUnobservedGapMS": _maximum_gap_ms(uptimes),
    }
    kernel = (
        [layer.kernel_peaks[index] for _, layer, index in series] if engine.kernel_peaks else []
    )
    graphics = [layer.graphics[index] for _, layer, index in series] if engine.graphics else []
    return metrics, kernel, graphics


def _apply_peak_fidelity(
    metrics: dict[str, float | int],
    kernel: list[float],
    graphics: list[float | None],
    generation_id: str,
) -> None:
    """Measure the sampled peaks against the exact high-water marks (contract v2).

    Metal-allocated memory is never below MLX's active memory, so a sampled
    Metal peak below the exact per-request `mlxPeakMB` proves the sampler
    missed the take's peak; `gpuPeakCaptureMissMB` says by how much (0 when it
    caught it). When the sampler read the kernel's physical-footprint ledger,
    its lifetime high-water mark is published beside the sampled peak: exact
    for the take when it rose inside the take's window, otherwise only an upper
    bound set earlier in the process. A ledger peak below a sampled footprint
    is a broken read and fails qualification; a miss is reported, never failed.
    """
    metrics["gpuPeakCaptureMissMB"] = max(
        0.0, float(metrics["mlxPeakMB"]) - float(metrics["peakGPUAllocatedMB"])
    )
    if kernel:
        kernel_peak = max(kernel)
        sampled_peak = float(metrics["peakPhysicalFootprintMB"])
        if kernel_peak + KERNEL_LEDGER_TOLERANCE_MB < sampled_peak:
            raise MemoryEvidenceError(
                f"generation {generation_id}: the kernel footprint ledger peak "
                f"{kernel_peak:.1f} MB is below the sampled footprint peak {sampled_peak:.1f} MB"
            )
        exact = kernel_peak > min(kernel)
        metrics["kernelPhysFootprintPeakMB"] = kernel_peak
        metrics["kernelPhysFootprintPeakExact"] = 1 if exact else 0
        if exact:
            metrics["footprintPeakCaptureMissMB"] = max(0.0, kernel_peak - sampled_peak)
    # Reported when the series' last sample read the graphics ledger.
    if graphics and graphics[-1] is not None:
        metrics["graphicsFootprintEndMB"] = graphics[-1]


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
    kernel = list(engine.kernel_peaks)
    graphics = list(engine.graphics)
    if platform == "macos" and require_app_layer:
        if not isinstance(app_row, dict) or app_row.get("generationID") != generation_id:
            raise MemoryEvidenceError(f"generation {generation_id}: missing matching macOS app row")
        engine_pid = _process_identifier(row)
        app_pid = _process_identifier(app_row)
        if engine_pid is None or app_pid is None:
            raise MemoryEvidenceError(
                f"generation {generation_id}: macOS memory evidence needs both layers' "
                "process identifier"
            )
        if engine_pid != app_pid:
            # The engine runs in the app process; two processes would need a
            # system-level measure this contract does not claim.
            raise MemoryEvidenceError(
                f"generation {generation_id}: app PID {app_pid} and engine PID {engine_pid} "
                "differ; one process has one memory series"
            )
        app = _validate_layer(
            row=app_row,
            layer="app",
            path=_find_exact_sidecar(diagnostics, "app", generation_id),
            platform=platform,
        )
        layers.append(app)
        if (
            bool(engine.kernel_peaks) != bool(app.kernel_peaks)
            or bool(engine.graphics) != bool(app.graphics)
        ):
            raise MemoryEvidenceError(
                f"generation {generation_id}: the app and engine layers sampled different "
                "kernel ledgers"
            )
        metrics, kernel, graphics = _one_process_series(engine, app)
        # Layer-level capture health stays per layer; the peaks come only from
        # the one process series above.
        metrics.update({
            "samplerSampleCount": sum(int(layer.metrics["samplerSampleCount"]) for layer in layers),
            "samplerPeriodicSampleCount": sum(int(layer.metrics["samplerPeriodicSampleCount"]) for layer in layers),
            "samplerBoundarySampleCount": sum(int(layer.metrics["samplerBoundarySampleCount"]) for layer in layers),
            "samplerCaptureFailureCount": 0,
            "samplerMissedDeadlineCount": sum(int(layer.metrics["samplerMissedDeadlineCount"]) for layer in layers),
            "samplerCoverage": min(float(layer.metrics["samplerCoverage"]) for layer in layers),
            "samplerTargetIntervalMS": max(float(layer.metrics["samplerTargetIntervalMS"]) for layer in layers),
            # MLX accounting is the engine's own allocator counter.
            "mlxPeakMB": engine.metrics["mlxPeakMB"],
            "mlxActivePeakMB": engine.metrics["mlxActivePeakMB"],
            "mlxCachePeakMB": engine.metrics["mlxCachePeakMB"],
        })
        for key in ("mlxEndActiveMB", "mlxEndCacheMB"):
            if key in engine.metrics:
                metrics[key] = engine.metrics[key]

    target_ms = float(metrics["samplerTargetIntervalMS"])
    gap_ms = float(metrics["samplerMaximumUnobservedGapMS"])
    gap_bound = load_unobserved_gap_bound()
    notes = row.get("notes") if isinstance(row.get("notes"), dict) else {}
    floor_tier = gap_bound.is_floor_tier(platform, notes.get("deviceClass"))
    limit_ms = gap_bound.limit_ms(target_ms, floor_tier=floor_tier)
    if gap_ms > limit_ms + 1e-9:
        floor_ms = gap_bound.floor_tier_floor_ms if floor_tier else gap_bound.floor_ms
        raise MemoryEvidenceError(
            f"generation {generation_id}: the process memory went unobserved for "
            f"{gap_ms:.1f} ms, more than the {limit_ms:g} ms bound "
            f"(max({gap_bound.target_interval_multiple:g}x the {target_ms:g} ms sampler "
            f"cadence, {floor_ms:g} ms{' on a floor tier' if floor_tier else ''}))"
        )
    metrics["samplerUnobservedGapLimitMS"] = limit_ms
    _apply_peak_fidelity(metrics, kernel, graphics, generation_id)

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
    if platform == "ios":
        # The measured process budget (audit #68): the peak share of the
        # take's own limit, exact through the kernel ledger when it rose inside
        # the take, and the minimum headroom. The absolute footprint bands and
        # the Metal working-set ratio stay app-side admission bands only: every
        # iPhone reports an 8 GiB Metal working set against a 6 GiB limit.
        bands = load_ios_memory_budget()
        utilization = float(metrics["peakProcessBudgetUtilization"])
        limit = float(metrics["impliedProcessLimitMB"])
        if metrics.get("kernelPhysFootprintPeakExact") == 1 and limit > 0:
            utilization = max(utilization, float(metrics["kernelPhysFootprintPeakMB"]) / limit)
        metrics["peakProcessBudgetUtilization"] = utilization
        minimum_headroom = float(metrics["minimumHeadroomMB"])
        if utilization >= bands["evidenceCriticalBudgetUtilization"]:
            raise MemoryEvidenceError(
                f"generation {generation_id}: the take used {utilization:.3f} of its process "
                f"budget (fails at {bands['evidenceCriticalBudgetUtilization']:g})"
            )
        if minimum_headroom < bands["guardedHeadroomMB"]:
            raise MemoryEvidenceError(
                f"generation {generation_id}: process headroom fell below "
                f"{bands['guardedHeadroomMB']:g} MiB"
            )
        if utilization >= bands["evidenceGuardedBudgetUtilization"]:
            warnings.append("memory.budget.guarded")
        if minimum_headroom < bands["healthyHeadroomMB"]:
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
