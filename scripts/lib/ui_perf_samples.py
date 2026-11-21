"""Window-scoped frame-gap and heartbeat statistics from probe samples (audit #80, #81).

Probe blocks since 2026-09-25 carry, besides their aggregates:

* ``gaps``: every frame gap of the block as ``[end offset from the block start
  (ms), gap (ms)]``, at most 256 (``gapsDropped`` counts the rest). The maximum
  gap is then clipped to the measured window exactly (a gap straddling a window
  edge counts only its in-window part), and p95 comes from the gaps that end in
  the window instead of a histogram bucket's upper edge.
* ``heartbeatCount`` and ``delayedHeartbeats``: the probe watchdog's heartbeats
  completed in the block and each one delayed more than 50 ms as
  ``[completion epoch ms, delay ms]`` (``delayedHeartbeatsDropped`` counts the
  rest), so heartbeat statistics are scoped to the window rather than the launch.

Blocks without the samples (older probes) or with dropped samples yield None,
and the checkers keep their block-level fallbacks.
"""

from __future__ import annotations

import math
from typing import Any, Iterable

# The named spans a UI-perf scenario marker may carry inside its window (audit #32).
PHASE_NAMES = frozenset({"query", "action", "verify"})


def overlap_fraction(block: dict[str, Any], start: int, end: int) -> float:
    span = int(block["endEpochMS"]) - int(block["startEpochMS"])
    if span <= 0:
        return 0.0
    overlap = min(int(block["endEpochMS"]), end) - max(int(block["startEpochMS"]), start)
    return max(0.0, min(1.0, overlap / span))


def span_hitch(blocks: list[dict[str, Any]], start: int, end: int) -> tuple[float, int]:
    """(in-span excess frame time, covered ms) of one span, apportioned like a window."""
    touching = [b for b in blocks if b["endEpochMS"] > start and b["startEpochMS"] < end]
    covered = sum(min(int(b["endEpochMS"]), end) - max(int(b["startEpochMS"]), start) for b in touching)
    excess = sum(b["sumExcessMS"] * overlap_fraction(b, start, end) for b in touching)
    return excess, covered


def phase_hitch_rates(marker: dict[str, Any], blocks: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Per phase name, the phases' total duration and hitch rate (audit #32).

    Optional marker field `phases`: [{name, startEpochMS, endEpochMS}, ...],
    ordered, disjoint (a phase may start where the previous ended) and inside
    the window. Report-only: no record metric or ceiling reads it."""
    phases = marker.get("phases")
    if phases is None:
        return None
    scenario = marker["scenario"]
    start, end = int(marker["windowStartEpochMS"]), int(marker["windowEndEpochMS"])
    if not isinstance(phases, list) or not phases:
        raise ValueError(f"scenario '{scenario}': phases must be a non-empty list")
    totals: dict[str, dict[str, float]] = {}
    previous_end = start
    for phase in phases:
        try:
            name = phase["name"]
            phase_start, phase_end = int(phase["startEpochMS"]), int(phase["endEpochMS"])
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"scenario '{scenario}': malformed phase marker") from None
        if name not in PHASE_NAMES:
            raise ValueError(f"scenario '{scenario}': unknown phase {name!r}")
        if not previous_end <= phase_start <= phase_end <= end:
            raise ValueError(f"scenario '{scenario}': phases must be ordered, disjoint and inside the window")
        previous_end = phase_end
        excess, covered = span_hitch(blocks, phase_start, phase_end)
        entry = totals.setdefault(name, {"durationMS": 0.0, "excessMS": 0.0, "coveredMS": 0.0})
        entry["durationMS"] += phase_end - phase_start
        entry["excessMS"] += excess
        entry["coveredMS"] += covered
    return {
        name: {
            "durationMS": int(entry["durationMS"]),
            "hitchTimeMSPerS": round(entry["excessMS"] / (entry["coveredMS"] / 1000.0), 3)
            if entry["coveredMS"] > 0 else None,
        }
        for name, entry in sorted(totals.items())
    }


def cycle_hitch_rates(marker: dict[str, Any], blocks: list[dict[str, Any]]) -> list[float] | None:
    """Per-cycle hitch time for a scenario that marks its repeated cycles (audit #34(b)).

    Optional marker field `cycles`: [{startEpochMS, endEpochMS}, ...], ordered,
    non-overlapping and inside the scenario window. Each cycle is apportioned
    exactly like the window, so the rates are within-run samples of the same
    statistic. Markers without cycles return None."""
    cycles = marker.get("cycles")
    if cycles is None:
        return None
    scenario = marker["scenario"]
    start, end = int(marker["windowStartEpochMS"]), int(marker["windowEndEpochMS"])
    if not isinstance(cycles, list) or not cycles:
        raise ValueError(f"scenario '{scenario}': cycles must be a non-empty list")
    rates = []
    previous_end = start
    for cycle in cycles:
        try:
            cycle_start, cycle_end = int(cycle["startEpochMS"]), int(cycle["endEpochMS"])
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"scenario '{scenario}': malformed cycle marker") from None
        if not previous_end <= cycle_start < cycle_end <= end:
            raise ValueError(f"scenario '{scenario}': cycles must be ordered, disjoint and inside the window")
        previous_end = cycle_end
        excess, covered = span_hitch(blocks, cycle_start, cycle_end)
        rates.append(round(excess / (covered / 1000.0), 3) if covered > 0 else 0.0)
    return rates


def _complete(blocks: list[dict[str, Any]], key: str, dropped: str) -> bool:
    return bool(blocks) and all(key in block and not block.get(dropped) for block in blocks)


def percentile(values: Iterable[float], fraction: float) -> float | None:
    """Nearest-rank percentile; None for no values."""
    ordered = sorted(values)
    if not ordered:
        return None
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def window_gaps(blocks: list[dict[str, Any]], start: int, end: int) -> dict[str, Any] | None:
    """The window's clipped maximum gap, sample p95 and sample count, or None."""
    if not _complete(blocks, "gaps", "gapsDropped"):
        return None
    clipped: list[float] = []
    inside: list[float] = []
    for block in blocks:
        block_start = int(block["startEpochMS"])
        samples = block["gaps"]
        if not isinstance(samples, list):
            raise ValueError("probe block gaps must be a list")
        for sample in samples:
            if not isinstance(sample, list) or len(sample) != 2:
                raise ValueError("probe block gap samples are [end offset ms, gap ms] pairs")
            offset, gap = float(sample[0]), float(sample[1])
            gap_end = block_start + offset
            portion = min(gap_end, end) - max(gap_end - gap, start)
            if portion > 0:
                clipped.append(portion)
            if start <= gap_end <= end:
                inside.append(gap)
    p95 = percentile(inside, 0.95)
    return {
        "maxGapMS": round(max(clipped, default=0.0), 2),
        "p95GapMS": round(p95, 2) if p95 is not None else None,
        "gapSampleCount": len(inside),
    }


def window_heartbeats(
    blocks: list[dict[str, Any]], start: int, end: int, fractions: dict[int, float],
) -> dict[str, Any] | None:
    """The window's heartbeats: completed (apportioned like the window), the
    ones delayed past 50 and 250 ms and the largest of those delays (0 when no
    heartbeat was delayed past 50 ms), by completion time; or None."""
    if not _complete(blocks, "heartbeatCount", "delayedHeartbeatsDropped"):
        return None
    completed = sum(float(block["heartbeatCount"]) * fractions[id(block)] for block in blocks)
    delays: list[int] = []
    for block in blocks:
        for event in block.get("delayedHeartbeats") or []:
            if not isinstance(event, list) or len(event) != 2:
                raise ValueError("probe block delayed heartbeats are [completion epoch ms, delay ms] pairs")
            completed_at, delay = int(event[0]), int(event[1])
            if start <= completed_at <= end:
                delays.append(delay)
    return {
        "heartbeatCount": int(round(completed)),
        "delayedHeartbeatCount50": sum(1 for delay in delays if delay > 50),
        "delayedHeartbeatCount250": sum(1 for delay in delays if delay > 250),
        "maximumDelayedHeartbeatMS": max(delays, default=0),
    }


def take_metrics(summary: dict[str, Any]) -> dict[str, Any]:
    """The record metrics of the window-scoped statistics a summary carries."""
    metrics: dict[str, Any] = {}
    if summary.get("gapSampleCount") is not None:
        metrics["uiGapSampleCount"] = summary["gapSampleCount"]
        if summary.get("p95GapMS") is not None:
            metrics["uiP95GapMS"] = summary["p95GapMS"]
    heartbeats = summary.get("windowHeartbeats")
    if heartbeats:
        metrics.update({
            "uiWindowHeartbeatCount": heartbeats["heartbeatCount"],
            "uiWindowDelayedHeartbeatCount50": heartbeats["delayedHeartbeatCount50"],
            "uiWindowDelayedHeartbeatCount250": heartbeats["delayedHeartbeatCount250"],
            "uiWindowMaximumDelayedHeartbeatMS": heartbeats["maximumDelayedHeartbeatMS"],
        })
    return metrics


def apply(summary: dict[str, Any], blocks: list[dict[str, Any]], start: int, end: int,
          fractions: dict[int, float]) -> None:
    """Fold the sample statistics into a scenario summary in place: the clipped
    maximum gap replaces the block maximum and the sample p95 replaces the
    bucket-edge approximation."""
    gaps = window_gaps(blocks, start, end)
    if gaps is not None:
        summary["maxGapMS"] = gaps["maxGapMS"]
        summary["maxGapClipped"] = True
        summary["p95GapMS"] = gaps["p95GapMS"]
        summary["gapSampleCount"] = gaps["gapSampleCount"]
        summary["p95GapMSApprox"] = None
    heartbeats = window_heartbeats(blocks, start, end, fractions)
    if heartbeats is not None:
        summary["windowHeartbeats"] = heartbeats
