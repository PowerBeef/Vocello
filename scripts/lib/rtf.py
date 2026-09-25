"""Real-time factor (RTF) semantics shared by the benchmark harness.

Since 2026-09-12 Vocello uses the industry-standard definition:

    rtf = synthesis wall seconds ÷ generated audio seconds   (lower is faster)

The wall side is the engine request span on the per-generation monotonic
recorder (prepare entry to the final WAV write) minus one-time startup stages
(model load, prewarm), so cold and warm takes both measure synthesis. The
engine emits it as ``derivedMetrics.requestWallSeconds`` / ``realTimeFactor``;
this module recomputes it from the stage marks when a row predates that field.

Records published before the cutover carry the inverted decode-loop speedup
under ``rtf`` (audio ÷ decode seconds, higher is faster). They are never
rewritten: ``run.rtfDefinition`` is absent on them, present (``"wall/audio"``)
on every new record, and consumers derive a standard RTF for legacy records
from the per-take ``submitToCompletedMS`` / ``audioSeconds`` they already
store. Legacy and standard values never enter one statistic.
"""

from __future__ import annotations

import statistics
from typing import Any, Iterable

STANDARD_RTF_DEFINITION = "wall/audio"
LEGACY_RTF_DEFINITION = "legacy-speedup"
# RTF-bearing records finished at or after this instant must declare rtfDefinition
# (benchmark_history.RTF_BEARING_KINDS; ui-perf and prosody-calibration carry no RTF).
RTF_DEFINITION_CUTOVER = "2026-09-12T00:00:00Z"

TERMINAL_STAGES = ("streamCompleted", "streamGenerationEnded")
STARTUP_INTERVALS = (
    ("startup.model_load_started", "startup.model_loaded"),
    ("startup.prewarm_started", "startup.prewarm_completed"),
)
# Per-take keys naming the startup windows the request wall excludes (audit
# #58), in STARTUP_INTERVALS order; `excludedStartupMS` is their sum.
STARTUP_WINDOW_KEYS = ("modelLoadWindowMS", "prewarmWindowMS")

# What a record's `ttfcMS` measures (audit #59). The key has carried two
# different spans: the macOS CLI bench stamps it from its own submission to the
# first chunk its stream observer receives, while the iOS device runner reads
# the engine recorder's first-chunk mark, measured from prepare entry. Records
# since 2026-09-25 declare which one as `run.ttfcDefinition`; the two never share
# a comparison lineage.
TTFC_CLI_SUBMIT_TO_FIRST_CHUNK = "cli-submit-to-first-chunk"
TTFC_ENGINE_PREPARE_TO_FIRST_CHUNK = "engine-prepare-to-first-chunk"
TTFC_DEFINITIONS = frozenset({TTFC_CLI_SUBMIT_TO_FIRST_CHUNK, TTFC_ENGINE_PREPARE_TO_FIRST_CHUNK})


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def stage_marks(row: dict[str, Any]) -> list[dict[str, Any]]:
    backend = row.get("backendMetrics") or {}
    summary = row.get("summary") or {}
    marks = backend.get("stages") or row.get("stageMarks") or summary.get("stageMarks") or []
    return [mark for mark in marks if isinstance(mark, dict)]


def _first_stage_ms(marks: Iterable[dict[str, Any]]) -> dict[str, int]:
    first: dict[str, int] = {}
    for mark in marks:
        stage = mark.get("stage")
        t_ms = mark.get("tMS")
        if isinstance(stage, str) and stage not in first and isinstance(t_ms, (int, float)) and not isinstance(t_ms, bool):
            first[stage] = int(t_ms)
    return first


def _startup_windows(first: dict[str, int]) -> list[int]:
    """Each STARTUP_INTERVALS window in ms; 0 when absent or not positive."""
    return [
        first[end] - first[start]
        if start in first and end in first and first[end] > first[start] else 0
        for start, end in STARTUP_INTERVALS
    ]


def request_wall_seconds_from_marks(marks: Iterable[dict[str, Any]]) -> float | None:
    """Mirror of `GenerationOutputAdapter.requestWallSeconds(stageMarks:)`."""
    first = _first_stage_ms(marks)
    terminal = next((first[stage] for stage in TERMINAL_STAGES if stage in first), None)
    if terminal is None:
        return None
    wall_ms = terminal - sum(_startup_windows(first))
    return wall_ms / 1000.0 if wall_ms > 0 else None


def startup_windows_ms(row: dict[str, Any]) -> dict[str, float] | None:
    """The startup time the standard RTF leaves out of the request wall (audit #58).

    `modelLoadWindowMS` and `prewarmWindowMS` are the model-load and in-request
    prewarm windows on the take's own stage recorder, and `excludedStartupMS`
    is exactly what `request_wall_seconds_from_marks` subtracts. They are not
    `prewarmMS`, which times the explicit prewarm. None when the row has no
    terminal mark, since there is then no request wall to exclude them from.
    """
    first = _first_stage_ms(stage_marks(row))
    if not any(stage in first for stage in TERMINAL_STAGES):
        return None
    windows = _startup_windows(first)
    result = {key: float(value) for key, value in zip(STARTUP_WINDOW_KEYS, windows, strict=True)}
    result["excludedStartupMS"] = float(sum(windows))
    return result


def request_wall_seconds(row: dict[str, Any]) -> float | None:
    derived = row.get("derivedMetrics") or {}
    value = _finite(derived.get("requestWallSeconds"))
    if value is not None and value > 0:
        return value
    return request_wall_seconds_from_marks(stage_marks(row))


def audio_seconds(row: dict[str, Any]) -> float | None:
    derived = row.get("derivedMetrics") or {}
    value = _finite(derived.get("audioSeconds"))
    if value is not None and value > 0:
        return value
    output = row.get("outputMetrics") or {}
    value = _finite(output.get("durationSeconds"))
    return value if value is not None and value > 0 else None


def engine_rtf(row: dict[str, Any]) -> float | None:
    """Standard RTF of one engine telemetry row, or None when it cannot be measured."""
    derived = row.get("derivedMetrics") or {}
    value = _finite(derived.get("realTimeFactor"))
    if value is not None and value > 0:
        return value
    wall = request_wall_seconds(row)
    audio = audio_seconds(row)
    if wall is None or audio is None:
        return None
    return wall / audio


def decode_speedup(row: dict[str, Any]) -> float | None:
    """Decode-loop speedup (audio ÷ decode seconds), the figure legacy records called RTF."""
    derived = row.get("derivedMetrics") or {}
    value = _finite(derived.get("audioSecondsPerWallSecond"))
    return value if value is not None and value > 0 else None


def app_end_to_end_rtf(app_row: dict[str, Any] | None, audio: float | None) -> float | None:
    """App-layer RTF (submit → completed ÷ audio); adds transport and UI dispatch."""
    if not isinstance(app_row, dict) or audio is None or audio <= 0:
        return None
    frontend = app_row.get("frontendMetrics") or {}
    timings = app_row.get("timingsMS") or {}
    completed = _finite(frontend.get("submitToCompletedMS"))
    if completed is None:
        completed = _finite(timings.get("submitToCompletedMS"))
    if completed is None or completed <= 0:
        return None
    return completed / 1000.0 / audio


def record_definition(record: dict[str, Any]) -> str:
    run = record.get("run") or {}
    return run.get("rtfDefinition") or LEGACY_RTF_DEFINITION


def is_standard(record: dict[str, Any]) -> bool:
    return record_definition(record) == STANDARD_RTF_DEFINITION


def legacy_take_rtf(kind: str, metrics: dict[str, Any]) -> float | None:
    """Standard RTF derived from a legacy take's stored metrics.

    UI records store the app submit→completed span; legacy CLI
    (`engine-generation`) records stored end-to-end audio ÷ wall under `rtf`,
    so its inverse is exact. Anything else has no defensible derivation.
    """
    audio = _finite(metrics.get("audioSeconds"))
    completed = _finite(metrics.get("submitToCompletedMS"))
    if audio and audio > 0 and completed and completed > 0:
        return completed / 1000.0 / audio
    speedup = _finite(metrics.get("rtf"))
    if kind == "engine-generation" and speedup and speedup > 0:
        return 1.0 / speedup
    return None


def take_rtf(record: dict[str, Any], take: dict[str, Any]) -> tuple[float | None, bool]:
    """(standard RTF, derived?) for one take of a record."""
    metrics = take.get("metrics") or {}
    if is_standard(record):
        value = _finite(metrics.get("rtf"))
        return (value if value and value > 0 else None), False
    kind = str((record.get("run") or {}).get("kind", ""))
    return legacy_take_rtf(kind, metrics), True


def record_rtf_median(record: dict[str, Any]) -> tuple[float | None, bool]:
    """(median standard RTF across takes, derived?) or (None, derived?)."""
    values: list[float] = []
    derived = not is_standard(record)
    for take in record.get("takes", []):
        value, _ = take_rtf(record, take)
        if value is not None:
            values.append(value)
    if not values:
        return None, derived
    return statistics.median(values), derived


def regression_percent(baseline: float, candidate: float, definition: str = STANDARD_RTF_DEFINITION) -> float:
    """Positive means the candidate is slower, under either definition."""
    if baseline <= 0:
        return 0.0
    if definition == STANDARD_RTF_DEFINITION:
        return (candidate / baseline - 1.0) * 100.0
    return (1.0 - candidate / baseline) * 100.0


def format_rtf(value: float | None, derived: bool = False) -> str:
    if value is None:
        return "—"
    return f"{'~' if derived else ''}{value:.2f}"
