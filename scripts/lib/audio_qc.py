"""Audio-QC take mapping shared by the publisher and the two UI benchmark gates.

The engine writes one `audioQC` report per generation (thresholds live once, in
Swift, in `makeAudioQCReport`). Three Python consumers fold that report into a
tracked benchmark take: `publish_benchmark_history.py`, `check_macos_xpc_bench.py`
and `check_ios_ui_benchmark.py`. This module holds the one copy of the
finish-reason predicate, the QC failure predicate, the five-key metric rename,
the quality-registry identity fold and the record schema-version rule.
"""

from __future__ import annotations

import math
from typing import Any


class AudioQCError(ValueError):
    """A take set cannot be published as one consistent record."""


# The engine emits `eos` and `max_tokens`; the other spellings appear in
# older telemetry rows and are compared case-insensitively.
SUCCESS_FINISH = frozenset({"eos", "max_tokens", "maxtokens", "completed", "complete", "success", "ok"})

# Engine `audioQC` key → tracked take metric key.
QC_METRIC_MAP = (
    ("clickEvents", "discontinuityCount"),
    ("clippedSamples", "clipCount"),
    ("nonFiniteSamples", "nonFiniteCount"),
    ("longestSilenceMS", "longestSilenceMS"),
    ("dcOffset", "dcOffset"),
)
VERDICT_KEYS = ("verdict", "instabilityVerdict", "writtenOutputVerdict")
VERDICT_RANK = {"pass": 0, "warn": 1, "fail": 2}


def finish_succeeded(value: Any) -> bool:
    return str(value).lower() in SUCCESS_FINISH


def finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def raw_audio_qc(row: dict[str, Any]) -> dict[str, Any]:
    """The engine's report, whether it sits at the row root or under outputMetrics."""
    output = row.get("outputMetrics") if isinstance(row.get("outputMetrics"), dict) else {}
    qc = row.get("audioQC") or output.get("audioQC") or {}
    return qc if isinstance(qc, dict) else {}


def qc_metrics(raw_qc: dict[str, Any]) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for source, target in QC_METRIC_MAP:
        if (value := finite_number(raw_qc.get(source))) is not None:
            metrics[target] = value
    return metrics


def qc_verdicts(raw_qc: dict[str, Any]) -> list[str]:
    return [str(raw_qc.get(key)).lower() for key in VERDICT_KEYS if raw_qc.get(key) is not None]


def audio_qc_failure(row: dict[str, Any]) -> str | None:
    """Why the take's overall verdict blocks publication, or None when pass/warn."""
    qc = raw_audio_qc(row)
    verdict = qc.get("verdict")
    if verdict in {"pass", "warn"}:
        return None
    if verdict == "fail":
        return f"failed: {qc.get('flags') or []}"
    return f"verdict is missing or invalid: {verdict!r}"


def output_failure(row: dict[str, Any]) -> str | None:
    """The full per-take output predicate: finish, atomic readable WAV, duration, QC."""
    output = row.get("outputMetrics") if isinstance(row.get("outputMetrics"), dict) else {}
    if not finish_succeeded(row.get("finishReason")):
        return f"unsuccessful finishReason={row.get('finishReason')!r}"
    if output.get("readableWAV") is not True:
        return "outputMetrics.readableWAV is not true"
    if output.get("atomicallyPublished") is not True:
        return "outputMetrics.atomicallyPublished is not true"
    duration = finite_number(output.get("durationSeconds"))
    if duration is None or duration <= 0:
        return "output duration is missing or non-positive"
    if failure := audio_qc_failure(row):
        return f"audioQC {failure}"
    return None


def qc_record(row: dict[str, Any]) -> dict[str, Any]:
    """The tracked `audioQC` block of one take (publisher shape)."""
    qc = raw_audio_qc(row)
    verdicts = qc_verdicts(qc)
    verdict = max(verdicts or ["pass"], key=lambda item: VERDICT_RANK.get(item, 99))
    flags = [str(item) for item in qc.get("flags", []) if isinstance(item, str)]
    if str(qc.get("instabilityVerdict", "pass")).lower() == "warn":
        flags.append("instability-warn")
    if str(qc.get("writtenOutputVerdict", "pass")).lower() == "warn":
        flags.append("written-output-warn")
    return {
        "algorithmVersion": int(qc.get("algorithmVersion", 1)),
        "verdict": verdict,
        "instabilityVerdict": str(qc.get("instabilityVerdict", qc.get("verdict", "pass"))).lower(),
        "writtenOutputVerdict": str(qc.get("writtenOutputVerdict", qc.get("verdict", "pass"))).lower(),
        "warningCodes": sorted(set(flags)) if verdict == "warn" else [],
        "metrics": qc_metrics(qc),
    }


def qc_algorithm_version(rows: list[dict[str, Any]]) -> int:
    return max((int(raw_audio_qc(row).get("algorithmVersion", 1)) for row in rows), default=1)


def quality_identity_fields(row: dict[str, Any]) -> dict[str, Any]:
    """Typed quality-registry identity from the engine row's open telemetry notes.

    Empty when the row predates the phase-12 registry; the record then
    publishes at schema v2. A run mixing both is refused by
    `history_record_schema_version`.
    """
    notes = row.get("notes") if isinstance(row.get("notes"), dict) else {}
    outcome = notes.get("quality_registry_outcome")
    gates = notes.get("quality_registry_required_gates")
    if not isinstance(outcome, str) or not isinstance(gates, str) or not gates:
        return {}
    fields: dict[str, Any] = {
        "qualityRegistryOutcome": outcome,
        "qualityRegistryRequiredGates": sorted(set(gates.split(","))),
    }
    issues = notes.get("quality_registry_issues")
    if isinstance(issues, str) and issues:
        fields["qualityRegistryIssues"] = sorted(set(issues.split(",")))
    return fields


def history_record_schema_version(takes: list[dict[str, Any]]) -> int:
    """3 when every take carries the quality identity, 2 when none does.

    A mix would publish a record silently missing evidence for some takes.
    """
    carrying = sum(1 for take in takes if "qualityRegistryOutcome" in take)
    if carrying == 0:
        return 2
    if carrying == len(takes):
        return 3
    raise AudioQCError("takes mix quality-registry identity presence; refusing a partial schema-v3 record")
