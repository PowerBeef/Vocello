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
