"""Per-take plausibility of a CPU profile's cycle weights (audit #97).

The one -O macOS CPU profile showed 0.651 GHz of CPU Profiler cycles per
rusage CPU-second, against 2.04-2.43 GHz on -Onone profiles, and its trace was
deleted, so the disagreement between the two CPU witnesses could not be
diagnosed. A profile now publishes, per take:

- the CPU Profiler cycle weight of the target's samples inside the take's
  generation window (from the start of its correlated prepare interval to the
  end of its correlated generation stream, the span the engine's own rusage
  delta covers),
- that take's rusage CPU seconds (user + system, from its telemetry row),
- their ratio in gigacycles per CPU-second, and whether it falls inside a
  provisional band of plausible average core clocks.

Beside them, `unresolvedRowCount` counts the target's CPU rows whose sample
time or weight could not be resolved: rows the sums silently lost. The block
only reports: an implausible take carries a warning, never a failure, and the
raw trace is kept only on an explicit --keep-trace.

Pure functions; the XML streaming lives in scripts/publish_benchmark_history.py.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping

CPU_PLAUSIBILITY_VERSION = 1
# Average core clock a take's cycles per CPU-second may plausibly show on
# Apple silicon, in GHz: efficiency cores idle near 0.6-1 GHz, performance
# cores peak near 4.5. Provisional and uncalibrated: the block records the
# band it was judged against, and a kept-trace profile calibrates it.
PLAUSIBLE_GIGACYCLES_PER_CPU_SECOND = (0.8, 5.0)
BLOCK_KEYS = frozenset({"version", "unresolvedRowCount", "band", "takes"})
TAKE_KEYS = frozenset({
    "takeIndex", "cycleWeight", "cpuSeconds", "gigacyclesPerCPUSecond", "plausible",
})
GENERATION_WINDOW_INTERVAL = "Native Generation Stream"
PREPARE_INTERVAL = "Native Prepare Generation"

Correlation = tuple[str, int, str]


def generation_windows(
    correlated: Mapping[Correlation, Iterable[tuple[str, Any]]],
) -> dict[Correlation, tuple[float, float]]:
    """Each take's generation window: from the start of its prepare interval
    (the stream start without one) to the end of its generation stream.
    `correlated` maps a take to its (name, interval) pairs, each interval
    exposing `start_ns` and `end_ns`."""
    windows: dict[Correlation, tuple[float, float]] = {}
    for correlation, named in correlated.items():
        named = list(named)
        stream = [interval for name, interval in named if name == GENERATION_WINDOW_INTERVAL]
        if not stream:
            continue
        prepare = [interval for name, interval in named if name == PREPARE_INTERVAL]
        start = min(interval.start_ns for interval in (prepare or stream))
        windows[correlation] = (start, max(interval.end_ns for interval in stream))
    return windows


def _round(value: float) -> float:
    return round(value, 6)


def take_plausibility(
    *, take_index: int, cycle_weight: float, cpu_seconds: float | None,
    band: tuple[float, float] = PLAUSIBLE_GIGACYCLES_PER_CPU_SECOND,
) -> dict[str, Any]:
    """One take's entry. Without CPU seconds or cycles there is no ratio, and
    the take is neither plausible nor implausible (None)."""
    ratio: float | None = None
    if cpu_seconds is not None and cpu_seconds > 0 and cycle_weight > 0:
        ratio = cycle_weight / cpu_seconds / 1e9
    return {
        "takeIndex": take_index,
        "cycleWeight": _round(cycle_weight),
        "cpuSeconds": _round(cpu_seconds) if cpu_seconds is not None else None,
        "gigacyclesPerCPUSecond": _round(ratio) if ratio is not None else None,
        "plausible": None if ratio is None else band[0] <= ratio <= band[1],
    }


def cpu_plausibility(
    *,
    samples: Iterable[tuple[float, float]],
    unresolved_rows: int,
    correlated: Mapping[Correlation, Iterable[tuple[str, Any]]],
    expectations: Mapping[Correlation, Mapping[str, Any]],
    band: tuple[float, float] = PLAUSIBLE_GIGACYCLES_PER_CPU_SECOND,
) -> dict[str, Any]:
    """The versioned block: `samples` are (sample time ns, cycle weight) pairs
    of the target's CPU rows; `expectations` carry each take's `cpuSeconds`."""
    windows = generation_windows(correlated)
    ordered = sorted(expectations, key=lambda correlation: correlation[1])
    weights = {correlation: 0.0 for correlation in ordered}
    spans = [(correlation, windows[correlation]) for correlation in ordered if correlation in windows]
    for time_ns, weight in samples:
        for correlation, (start, end) in spans:
            if start <= time_ns <= end:
                weights[correlation] += weight
                break
    takes = []
    for correlation in ordered:
        seconds = expectations[correlation].get("cpuSeconds")
        takes.append(take_plausibility(
            take_index=correlation[1],
            cycle_weight=weights[correlation],
            cpu_seconds=float(seconds) if isinstance(seconds, (int, float))
            and not isinstance(seconds, bool) and math.isfinite(float(seconds)) else None,
            band=band,
        ))
    return {
        "version": CPU_PLAUSIBILITY_VERSION,
        "unresolvedRowCount": int(unresolved_rows),
        "band": [band[0], band[1]],
        "takes": takes,
    }


def implausible_take_indices(block: Mapping[str, Any]) -> list[int]:
    return [
        int(take["takeIndex"]) for take in block.get("takes", [])
        if isinstance(take, dict) and take.get("plausible") is False
    ]


def _non_negative(value: Any, location: str) -> float:
    if (
        isinstance(value, bool) or not isinstance(value, (int, float))
        or not math.isfinite(float(value)) or value < 0
    ):
        raise ValueError(f"{location} must be a finite non-negative number")
    return float(value)


def validate_cpu_plausibility(block: Any, *, take_indices: Iterable[int]) -> None:
    """Validate a published block against the record's takes."""
    if not isinstance(block, dict) or set(block) != BLOCK_KEYS:
        raise ValueError("trace cpuPlausibility has unexpected or missing fields")
    if block["version"] != CPU_PLAUSIBILITY_VERSION:
        raise ValueError("trace cpuPlausibility has an unsupported version")
    unresolved = block["unresolvedRowCount"]
    if isinstance(unresolved, bool) or not isinstance(unresolved, int) or unresolved < 0:
        raise ValueError("trace cpuPlausibility unresolvedRowCount must be a non-negative integer")
    band = block["band"]
    if (
        not isinstance(band, list) or len(band) != 2
        or _non_negative(band[0], "band") >= _non_negative(band[1], "band")
    ):
        raise ValueError("trace cpuPlausibility band must be an increasing pair")
    takes = block["takes"]
    if not isinstance(takes, list) or [
        take.get("takeIndex") if isinstance(take, dict) else None for take in takes
    ] != sorted(set(take_indices)):
        raise ValueError("trace cpuPlausibility must list every profiled take once, in order")
    for take in takes:
        location = f"trace cpuPlausibility take {take['takeIndex']}"
        if set(take) != TAKE_KEYS:
            raise ValueError(f"{location} has unexpected or missing fields")
        cycles = _non_negative(take["cycleWeight"], f"{location} cycleWeight")
        seconds = take["cpuSeconds"]
        ratio = take["gigacyclesPerCPUSecond"]
        if seconds is not None:
            seconds = _non_negative(seconds, f"{location} cpuSeconds")
        if ratio is None:
            if seconds is not None and seconds > 0 and cycles > 0:
                raise ValueError(f"{location} omits a ratio its cycles and CPU seconds define")
            if take["plausible"] is not None:
                raise ValueError(f"{location} judges a take without a ratio")
            continue
        ratio = _non_negative(ratio, f"{location} gigacyclesPerCPUSecond")
        if seconds is None or seconds <= 0 or not math.isclose(
            ratio, cycles / seconds / 1e9, rel_tol=1e-4, abs_tol=1e-6,
        ):
            raise ValueError(f"{location} ratio does not follow from its cycles and CPU seconds")
        if take["plausible"] is not (float(band[0]) <= ratio <= float(band[1])):
            raise ValueError(f"{location} plausibility does not match its band")
