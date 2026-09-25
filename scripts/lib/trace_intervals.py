"""Per-take statistics of the engine's os_signpost intervals (audit #12, #96, V-2).

The Instruments profile lanes used to publish only row counts, so the one
kernel-timestamped per-stage witness was lost with the trace. This module turns
the engine's decode-loop intervals into a small versioned block per take:

- Intervals are assigned to a take by containment in that take's window: from
  the end of its correlated `Native Prepare Generation` interval to the end of
  its correlated `Native Generation Stream` interval (`take_windows`). An
  engine interval inside no take window is an orphan: prewarm work, or a take
  whose window was dropped.
- Completeness: each decode step emits the 36 intervals of
  `LOOP_STEP_INTERVALS` (the 16-codebook Qwen3-TTS 12 Hz models: 15 code
  predictor steps and 15 samples plus six per-step spans). How many steps a
  take ran follows from its own end reason (`LOOP_STEPS_BEYOND_TOKENS`): a take
  that ends on EOS ran `generatedTokens + 1` steps, the last one sampling EOS;
  a take that hits the token cap (a quality warning, still published) ran
  exactly `generatedTokens`. A take with fewer than 36 x its steps lost loop
  intervals and its statistics are incomplete. `Token Read` (V-2) is reported
  beside them, never counted in the 36.
- Witness: the engine sums the same spans into its JSONL `timingsMS` keys
  (`WITNESS_TIMINGS`), each clock read taken around the same code as its
  interval, so the trace sums and the telemetry line up; a take reports how
  many compared spans drifted beyond `witness_tolerance_ms`. It only reports.

Pure functions: the XML streaming lives in scripts/publish_benchmark_history.py.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

SIGNPOST_SUMMARY_VERSION = 1
INTERVAL_STATISTICS_VERSION = 1
QWEN3_SIGNPOST_SUBSYSTEM = "com.qwenvoice.engine.qwen3"
GENERATION_WINDOW_INTERVAL = "Native Generation Stream"
PREPARE_INTERVAL = "Native Prepare Generation"

# Intervals every decode step emits, with their per-step multiplicity.
LOOP_STEP_INTERVALS: dict[str, int] = {
    "Talker Forward": 1,
    "Sample First Codebook": 1,
    "Code Predictor Loop": 1,
    "Code Predictor Step": 15,
    "Sample Predicted Codebook": 15,
    "Codec Embedding Assembly": 1,
    "Step Eval Flush": 1,
    "EOS Read": 1,
}
LOOP_INTERVALS_PER_STEP = sum(LOOP_STEP_INTERVALS.values())
# Decode steps beyond the generated tokens, by the engine's
# `generation_end_reason`: the EOS step samples no code; the loop stops at the
# token cap without one.
LOOP_STEPS_BEYOND_TOKENS: dict[str, int] = {"eos": 1, "token_cap": 0}


def loop_steps(generated_tokens: int, end_reason: str) -> int:
    """The decode steps a take ran, from its generated tokens and end reason."""
    if end_reason not in LOOP_STEPS_BEYOND_TOKENS:
        raise ValueError(f"unknown generation end reason {end_reason!r}")
    return generated_tokens + LOOP_STEPS_BEYOND_TOKENS[end_reason]

# Every engine interval name and the key it is published under.
INTERVAL_KEYS: dict[str, str] = {
    "Talker Forward": "talkerForward",
    "Sample First Codebook": "sampleFirstCodebook",
    "Code Predictor Loop": "codePredictorLoop",
    "Code Predictor Step": "codePredictorStep",
    "Sample Predicted Codebook": "samplePredictedCodebook",
    "Codec Embedding Assembly": "codecEmbeddingAssembly",
    "Step Eval Flush": "stepEvalFlush",
    "Token Read": "tokenRead",
    "EOS Read": "eosRead",
    "Audio Decoder": "audioDecoder",
    "Audio Chunk Eval": "audioChunkEval",
    "Audio Chunk Flush": "audioChunkFlush",
}
INTERVAL_STAT_KEYS = frozenset({"count", "totalMS", "medianMS", "p95MS", "maxMS"})

# The JSONL timing key the engine sums each interval's span into.
WITNESS_TIMINGS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("Talker Forward",), "qwen_talker_forward_total"),
    (("Sample First Codebook",), "qwen_sample_first_codebook_total"),
    (("Code Predictor Loop",), "qwen_code_predictor_total"),
    (("Code Predictor Step",), "qwen_code_predictor_step_total"),
    (("Sample Predicted Codebook",), "qwen_sample_predicted_codebook_total"),
    (("Codec Embedding Assembly",), "qwen_codec_embedding_assembly_total"),
    (("Step Eval Flush",), "qwen_stream_step_eval_total"),
    (("Token Read",), "qwen_stream_step_token_read_total"),
    (("EOS Read",), "qwen_stream_step_eos_read_total"),
    (("Audio Decoder",), "qwen_stream_decoder_total"),
    (("Audio Chunk Eval", "Audio Chunk Flush"), "qwen_audio_chunk_eval_total"),
)
TAKE_KEYS = frozenset({
    "takeIndex", "generatedTokens", "endReason", "loopSteps", "loopIntervalCount",
    "expectedLoopIntervalCount", "complete", "windowMS", "intervals", "witness",
})
WITNESS_KEYS = frozenset({"comparedCount", "outsideToleranceCount", "maximumDriftMS"})
SUMMARY_KEYS = frozenset({
    "signpostSummaryVersion", "signpostIntervalCount", "signpostBeginCount",
    "signpostEndCount", "signpostPointCount", "orphanIntervalCount",
    "intervalStatistics", "recordedDurationSeconds",
})
SUMMARY_COUNT_KEYS = (
    "signpostIntervalCount", "signpostBeginCount", "signpostEndCount",
    "signpostPointCount", "orphanIntervalCount",
)

Correlation = tuple[str, int, str]


@dataclass(frozen=True)
class Interval:
    name: str
    start_ns: float
    duration_ns: float

    @property
    def end_ns(self) -> float:
        return self.start_ns + self.duration_ns


def is_engine_interval(name: str, subsystem: str | None) -> bool:
    """An engine decode-loop interval. When the export names no subsystem the
    interval names, unique to the owned Qwen3 loop, decide."""
    if name not in INTERVAL_KEYS:
        return False
    return not subsystem or subsystem == QWEN3_SIGNPOST_SUBSYSTEM


def take_windows(
    correlated: Mapping[Correlation, Iterable[tuple[str, Interval]]],
) -> dict[Correlation, tuple[float, float]]:
    """Each take's window. The engine opens the take's decode loop between the
    end of its correlated prepare interval and the start of its generation
    stream, so the window runs from the prepare end (the stream start when no
    prepare interval was kept) to the stream end: a first step that starts a
    moment before the stream interval is still the take's, and prewarm work
    inside the prepare interval is not. Without a stream interval the window
    is the union of the take's correlated intervals."""
    windows: dict[Correlation, tuple[float, float]] = {}
    for correlation, named in correlated.items():
        named = list(named)
        stream = [interval for name, interval in named if name == GENERATION_WINDOW_INTERVAL]
        prepare = [interval for name, interval in named if name == PREPARE_INTERVAL]
        if stream:
            end = max(interval.end_ns for interval in stream)
            start = min(interval.start_ns for interval in stream)
            prepared = [interval.end_ns for interval in prepare if interval.end_ns <= start]
            windows[correlation] = (max(prepared) if prepared else start, end)
        elif named:
            windows[correlation] = (
                min(interval.start_ns for _, interval in named),
                max(interval.end_ns for _, interval in named),
            )
    return windows


def assign_intervals(
    intervals: Iterable[Interval], windows: Mapping[Correlation, tuple[float, float]],
) -> tuple[dict[Correlation, list[Interval]], int]:
    """Assign each engine interval to the take window that contains it."""
    ordered = sorted(windows.items(), key=lambda item: item[1][0])
    assigned: dict[Correlation, list[Interval]] = {correlation: [] for correlation, _ in ordered}
    orphans = 0
    for interval in intervals:
        owner = next(
            (
                correlation for correlation, (start, end) in ordered
                if start <= interval.start_ns and interval.end_ns <= end
            ),
            None,
        )
        if owner is None:
            orphans += 1
        else:
            assigned[owner].append(interval)
    return assigned, orphans


def _nearest_rank(ordered: list[float], fraction: float) -> float:
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def _milliseconds(nanoseconds: float) -> float:
    return round(nanoseconds / 1_000_000.0, 3)


def witness_tolerance_ms(telemetry_ms: float, count: int) -> float:
    """How far a trace sum may drift from its JSONL total before it is reported:
    5 ms, 5% of the total, or 10 us per interval (the signpost calls sit just
    inside the clock reads), whichever is largest."""
    return max(5.0, 0.05 * abs(telemetry_ms), 0.01 * count)


def take_statistics(
    *,
    take_index: int,
    window: tuple[float, float] | None,
    intervals: Iterable[Interval],
    generated_tokens: int,
    end_reason: str,
    timings_ms: Mapping[str, Any] | None,
) -> dict[str, Any]:
    steps = loop_steps(generated_tokens, end_reason)
    by_name: dict[str, list[float]] = {}
    for interval in intervals:
        by_name.setdefault(interval.name, []).append(interval.duration_ns)
    statistics: dict[str, dict[str, Any]] = {}
    for name in INTERVAL_KEYS:
        durations = sorted(by_name.get(name, []))
        if not durations:
            continue
        statistics[INTERVAL_KEYS[name]] = {
            "count": len(durations),
            "totalMS": _milliseconds(sum(durations)),
            "medianMS": _milliseconds(_nearest_rank(durations, 0.5)),
            "p95MS": _milliseconds(_nearest_rank(durations, 0.95)),
            "maxMS": _milliseconds(durations[-1]),
        }
    loop_count = sum(len(by_name.get(name, [])) for name in LOOP_STEP_INTERVALS)
    expected = LOOP_INTERVALS_PER_STEP * steps
    compared = outside = 0
    maximum_drift = 0.0
    for names, key in WITNESS_TIMINGS:
        telemetry = (timings_ms or {}).get(key)
        if isinstance(telemetry, bool) or not isinstance(telemetry, (int, float)):
            continue
        count = sum(len(by_name.get(name, [])) for name in names)
        if count == 0:
            continue
        traced = sum(sum(by_name.get(name, [])) for name in names) / 1_000_000.0
        drift = traced - float(telemetry)
        compared += 1
        maximum_drift = max(maximum_drift, abs(drift))
        if abs(drift) > witness_tolerance_ms(float(telemetry), count):
            outside += 1
    return {
        "takeIndex": take_index,
        "generatedTokens": generated_tokens,
        "endReason": end_reason,
        "loopSteps": steps,
        "loopIntervalCount": loop_count,
        "expectedLoopIntervalCount": expected,
        "complete": loop_count >= expected,
        "windowMS": _milliseconds(window[1] - window[0]) if window else 0.0,
        "intervals": statistics,
        "witness": {
            "comparedCount": compared,
            "outsideToleranceCount": outside,
            "maximumDriftMS": round(maximum_drift, 3),
        },
    }


def interval_statistics(
    *,
    correlated: Mapping[Correlation, Iterable[tuple[str, Interval]]],
    engine_intervals: Iterable[Interval],
    expectations: Mapping[Correlation, Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """(per-take statistics in take order, orphan interval count)."""
    windows = take_windows(correlated)
    assigned, orphans = assign_intervals(engine_intervals, windows)
    takes: list[dict[str, Any]] = []
    for correlation in sorted(expectations, key=lambda item: item[1]):
        expectation = expectations[correlation]
        takes.append(take_statistics(
            take_index=correlation[1],
            window=windows.get(correlation),
            intervals=assigned.get(correlation, []),
            generated_tokens=int(expectation["generatedTokens"]),
            end_reason=str(expectation["endReason"]),
            timings_ms=expectation.get("timingsMS"),
        ))
    return takes, orphans


def _require_count(value: Any, location: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{location} must be an integer of at least {minimum}")
    return value


def _require_milliseconds(value: Any, location: str) -> float:
    if (
        isinstance(value, bool) or not isinstance(value, (int, float))
        or not math.isfinite(float(value)) or value < 0
    ):
        raise ValueError(f"{location} must be a finite non-negative number")
    return float(value)


def validate_signpost_summary(
    summary: Mapping[str, Any], *, take_indices: Iterable[int], require_complete: bool,
) -> None:
    """Validate the versioned signpost block of a published trace summary."""
    if summary.get("signpostSummaryVersion") != SIGNPOST_SUMMARY_VERSION:
        raise ValueError("trace signpost summary has an unsupported version")
    for key in SUMMARY_COUNT_KEYS:
        _require_count(summary.get(key), f"trace summary {key}")
    if "recordedDurationSeconds" in summary:
        duration = summary["recordedDurationSeconds"]
        if _require_milliseconds(duration, "trace summary recordedDurationSeconds") <= 0:
            raise ValueError("trace summary recordedDurationSeconds must be positive")
    statistics = summary.get("intervalStatistics")
    if not isinstance(statistics, dict) or set(statistics) != {"version", "takes"}:
        raise ValueError("trace intervalStatistics must be an object with version and takes")
    if statistics["version"] != INTERVAL_STATISTICS_VERSION:
        raise ValueError("trace intervalStatistics has an unsupported version")
    takes = statistics["takes"]
    expected_indices = sorted(set(take_indices))
    if not isinstance(takes, list) or [
        take.get("takeIndex") if isinstance(take, dict) else None for take in takes
    ] != expected_indices:
        raise ValueError("trace intervalStatistics must list every profiled take once, in order")
    for take in takes:
        location = f"trace intervalStatistics take {take['takeIndex']}"
        if set(take) != TAKE_KEYS:
            raise ValueError(f"{location} has unexpected or missing fields")
        tokens = _require_count(take["generatedTokens"], f"{location} generatedTokens", minimum=1)
        end_reason = take["endReason"]
        if not isinstance(end_reason, str) or end_reason not in LOOP_STEPS_BEYOND_TOKENS:
            raise ValueError(f"{location} endReason must be eos or token_cap")
        if _require_count(take["loopSteps"], f"{location} loopSteps", minimum=1) != loop_steps(
            tokens, end_reason
        ):
            raise ValueError(f"{location} loopSteps does not follow from its tokens and endReason")
        count = _require_count(take["loopIntervalCount"], f"{location} loopIntervalCount")
        expected = _require_count(
            take["expectedLoopIntervalCount"], f"{location} expectedLoopIntervalCount"
        )
        if expected != LOOP_INTERVALS_PER_STEP * take["loopSteps"]:
            raise ValueError(f"{location} expects the wrong number of loop intervals")
        if take["complete"] is not (count >= expected):
            raise ValueError(f"{location} completeness does not match its counts")
        if require_complete and take["complete"] is not True:
            raise ValueError(f"{location} lost loop intervals ({count} of {expected})")
        _require_milliseconds(take["windowMS"], f"{location} windowMS")
        intervals = take["intervals"]
        if not isinstance(intervals, dict) or not set(intervals) <= set(INTERVAL_KEYS.values()):
            raise ValueError(f"{location} names an unknown interval")
        for key, stats in intervals.items():
            if not isinstance(stats, dict) or set(stats) != INTERVAL_STAT_KEYS:
                raise ValueError(f"{location} interval {key} has unexpected fields")
            _require_count(stats["count"], f"{location} {key}.count", minimum=1)
            values = [
                _require_milliseconds(stats[field], f"{location} {key}.{field}")
                for field in ("medianMS", "p95MS", "maxMS")
            ]
            _require_milliseconds(stats["totalMS"], f"{location} {key}.totalMS")
            if not values[0] <= values[1] <= values[2]:
                raise ValueError(f"{location} interval {key} percentiles are out of order")
        witness = take["witness"]
        if not isinstance(witness, dict) or set(witness) != WITNESS_KEYS:
            raise ValueError(f"{location} witness has unexpected fields")
        compared = _require_count(witness["comparedCount"], f"{location} witness.comparedCount")
        if _require_count(
            witness["outsideToleranceCount"], f"{location} witness.outsideToleranceCount"
        ) > compared:
            raise ValueError(f"{location} witness reports more drifts than comparisons")
        _require_milliseconds(witness["maximumDriftMS"], f"{location} witness.maximumDriftMS")
