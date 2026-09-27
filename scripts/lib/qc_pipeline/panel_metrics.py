"""L2 metrics and report-only verdicts of the AQ-06 judge panel (audit sections 3.3, 3.5 and 4).

Each panel judge's raw output (L1) is reduced to flat, privacy-safe metrics
(L2), keyed by the L1 key, the metric definition, the digest of every source
that shapes the value and what it reads besides the raw output (the script
digest, the expected language, a reference clip's L1 key). Per category:

- **Recognizers** (Whisper large-v3, Parakeet, Paraformer, SenseVoice f16,
  Qwen3-ASR): the transcript's normalization-v3 WER/CER through
  `language_metrics.score_recognition` (the measurements only, as for
  whisper-small), when the take has a script; the detected language where the
  judge identifies it from the audio (Whisper's first-30-second detection,
  SenseVoice's emitted tag). The transcript stays private.
- **Language ID** (VoxLingua107): the posterior restricted to the ten product
  languages plus an `other` mass, the expected language's share, the top
  language and the margin over the best competitor.
- **Speaker** (CAM++, ResNet293): with a reference clip (the clone lane), the
  cosine between the take's and the reference's embeddings, whole-take and per
  2 s window; without one, no metric.
- **Pitch** (pYIN): voiced fraction and F0 statistics (Hz and semitones).
- **Audiobox Aesthetics**: CE, CU, PC and PQ. **DNSMOS P.835**: SIG, BAK and
  OVRL (and the P.808 MOS its reference script reports).
- **Aligner**: alignment coverage: units aligned of units expected, the aligned
  span over the take and the gaps at each end.

**Report-only verdicts.** Each judge's verdict names it alone and carries no
calibration record, so the composer lists it as `uncalibrated` and it never
decides a take: `reportOnly` keeps it out of every lane's gating set. A
recognizer's accuracy (and, where it identifies the language, its language)
channel reports the pass or fail today's thresholds would give; the other
categories report `uncalibrated` outright, since no operating point exists.
Same-lab judges and ResNet293 are non-voting in the registry and stay
report-only whatever their status; a candidate or shadow judge stays report-only
until a qualified record exists (audit section 5.9).
"""

from __future__ import annotations

import math
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from lib.language_metrics import (
    ACCURACY_METRIC_VERSION,
    LANGUAGE_LOCALE_CODES,
    MAX_ACCURACY_ERROR_RATE,
    NORMALIZATION_DATA_FILES,
)
from lib.qc_qualification.composer import UNAVAILABLE_REASONS

REPO = Path(__file__).resolve().parents[3]
PANEL_METRIC_VERSION = "panel-metrics-v1"
PANEL_METRICS_SOURCE = Path(__file__).resolve()
LANGUAGE_METRICS_SOURCE = REPO / "scripts/lib/language_metrics.py"
VERDICTS_SOURCE = REPO / "scripts/lib/qc_pipeline/verdicts.py"
SENSEVOICE_ADAPTER_SOURCE = REPO / "scripts/delivery_compact_model_adapter.py"
CODE_TO_LANGUAGE = {code: name for name, code in LANGUAGE_LOCALE_CODES.items()}
PRODUCT_CODES = tuple(LANGUAGE_LOCALE_CODES.values())
# Detector class per category (audit section 5.7).
CATEGORY_CLASS = {"asr": "B", "alignment": "C", "lid": "D", "speaker": "E", "pitch": "F",
                  "audiobox": "G", "dnsmos": "G"}
# The one channel of a category without a pass or fail rule today.
CATEGORY_CHANNEL = {"alignment": "coverage", "pitch": "pitch", "audiobox": "quality", "dnsmos": "quality"}
# Statuses whose verdicts can fail a take or a lane (the registry's VERDICT_STATUSES).
VOTING_STATUSES = frozenset({"warn", "gating"})
# The orchestrator's own unavailable codes, mapped onto the composer's reasons.
COMPOSER_UNAVAILABLE = {"admission-timeout": "timeout"}


def metric_definition(category: str) -> str:
    if category == "asr":
        return f"{PANEL_METRIC_VERSION}:asr:{ACCURACY_METRIC_VERSION}"
    return f"{PANEL_METRIC_VERSION}:{category}"


def metric_sources(category: str) -> tuple[Path, ...]:
    """Every source that shapes a category's L2 value, hashed together into its key."""
    if category == "asr":
        return (PANEL_METRICS_SOURCE, LANGUAGE_METRICS_SOURCE, *NORMALIZATION_DATA_FILES, VERDICTS_SOURCE,
                SENSEVOICE_ADAPTER_SOURCE)
    return (PANEL_METRICS_SOURCE,)


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return None
    return float(value)


def _round(value: float | None, places: int = 6) -> float | None:
    return None if value is None else round(value, places)


# --------------------------------------------------------------------------- #
# Recognizers
# --------------------------------------------------------------------------- #

def _language_name(value: Any) -> str | None:
    """A detected language as a product language name, the raw code when it is none, or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    code = value.strip().lower()
    if code in LANGUAGE_LOCALE_CODES:
        return code
    return CODE_TO_LANGUAGE.get(code, code if code.isascii() and code.replace("-", "").isalnum() else None)


# The panel's pinned llama.cpp SenseVoice prints the language and emotion tags
# before the transcript (`<|ja|><|EMO_UNKNOWN|>...`); the FunASR runtime the
# delivery adapter reads (delivery_compact_model_adapter.SENSEVOICE_OUTPUT) adds
# the event and text-normalization tags. Both forms parse; the missing tags are
# None. Before 2026-09-27 the panel required all four, so every llama.cpp row
# parsed as an empty transcript (outputParsed false).
PANEL_SENSEVOICE_OUTPUT = re.compile(
    r"^<\|(?P<language>[^|]+)\|><\|(?P<emotion>[^|]+)\|>"
    r"(?:<\|(?P<event>[^|]+)\|><\|(?P<textnorm>[^|]+)\|>)?(?P<transcript>.*)$",
    re.DOTALL,
)


def recognizer_output(judge_id: str, raw: Mapping[str, Any]) -> tuple[str, str | None, dict[str, Any]]:
    """(transcript, detected language, extra metrics) from one recognizer's raw output."""
    extra: dict[str, Any] = {}
    if judge_id == "asr.sensevoice-small-f16@1":
        match = PANEL_SENSEVOICE_OUTPUT.fullmatch(str(raw.get("stdout", "")).strip())
        extra["outputParsed"] = match is not None
        if match is None:
            return "", None, extra
        extra.update(languageTag=match.group("language"), emotionTag=match.group("emotion"),
                     eventTag=match.group("event"), textNormalizationTag=match.group("textnorm"))
        return match.group("transcript").strip(), _language_name(match.group("language")), extra
    transcript = str(raw.get("transcript", "")).strip()
    detected = None
    if judge_id == "asr.whisper-large-v3@1":
        detected = _language_name(raw.get("detectedLanguage"))
        extra["detectedLanguageProbability"] = _finite(raw.get("detectedLanguageProbability"))
        extra["expectedLanguageProbability"] = _finite(raw.get("expectedLanguageProbability"))
        segments = [item for item in raw.get("segments") or [] if isinstance(item, Mapping)]
        extra["segmentCount"] = len(segments)
        starts = [value for value in (_finite(item.get("start")) for item in segments) if value is not None]
        ends = [value for value in (_finite(item.get("end")) for item in segments) if value is not None]
        extra["firstSegmentStartSeconds"] = min(starts) if starts else None
        extra["lastSegmentEndSeconds"] = max(ends) if ends else None
    elif judge_id == "asr.qwen3-asr-1.7b@1":
        # A locked decode echoes its lock; only a language=None pass identifies the language.
        extra["reportedLanguage"] = _language_name(raw.get("detectedLanguage"))
    return transcript, detected, extra


def asr_reduce(judge_id: str, raw: Mapping[str, Any], *, script: str | None,
               language: str) -> tuple[dict[str, Any], str | None]:
    from lib.qc_pipeline.verdicts import asr_metrics

    transcript, detected, extra = recognizer_output(judge_id, raw)
    metrics: dict[str, Any] = {"transcriptEmpty": not transcript, "transcriptCharacters": len(transcript), **extra}
    if isinstance(script, str) and script.strip():
        metrics.update(asr_metrics({"transcript": transcript, "detectedLanguage": detected},
                                   script=script, language=language))
    metrics["detectedLanguage"] = detected
    return metrics, transcript or None


# --------------------------------------------------------------------------- #
# Language ID, speaker, pitch, quality, alignment
# --------------------------------------------------------------------------- #

def lid_reduce(raw: Mapping[str, Any], *, language: str) -> dict[str, Any]:
    """The posterior over the ten product languages plus `other`, from the classifier's log posteriors."""
    log_posteriors = {str(key).strip().lower(): _finite(value)
                      for key, value in (raw.get("logPosteriors") or {}).items()}
    values = {key: value for key, value in log_posteriors.items() if value is not None}
    if not values:
        raise ValueError("the language classifier reported no posterior")
    peak = max(values.values())
    weights = {key: math.exp(value - peak) for key, value in values.items()}
    total = sum(weights.values())
    posterior = {code: weights.get(code, 0.0) / total for code in PRODUCT_CODES}
    other = max(0.0, 1.0 - sum(posterior.values()))
    expected = LANGUAGE_LOCALE_CODES[language]
    ranked = sorted([*posterior.items(), ("other", other)], key=lambda item: (-item[1], item[0]))
    top, top_value = ranked[0]
    competitor = max(value for code, value in ranked if code != expected)
    return {
        "expectedPosterior": _round(posterior[expected]),
        "otherMass": _round(other),
        "topLanguage": CODE_TO_LANGUAGE.get(top, "other"),
        "topPosterior": _round(top_value),
        "margin": _round(posterior[expected] - competitor),
        "classifierTop1": _language_name(raw.get("top1")),
        **{f"posterior.{CODE_TO_LANGUAGE[code]}": _round(value) for code, value in posterior.items()},
    }


def _cosine(first: Sequence[Any], second: Sequence[Any]) -> float | None:
    a = [_finite(value) for value in first]
    b = [_finite(value) for value in second]
    if not a or len(a) != len(b) or any(value is None for value in (*a, *b)):
        return None
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return None if norm == 0.0 else dot / norm


def speaker_reduce(raw: Mapping[str, Any], reference: Mapping[str, Any] | None) -> dict[str, Any]:
    """The cosine against the reference clip's embedding; no metric without a reference."""
    if reference is None:
        return {}
    embedding = reference.get("embedding") or []
    cosine = _cosine(raw.get("embedding") or [], embedding)
    windows = [_cosine(item.get("embedding") or [], embedding)
               for item in raw.get("windows") or [] if isinstance(item, Mapping)]
    windows = [value for value in windows if value is not None]
    return {
        "cosine": _round(cosine),
        "windowCount": len(windows),
        "windowCosineMinimum": _round(min(windows)) if windows else None,
        "windowCosineMean": _round(sum(windows) / len(windows)) if windows else None,
        "onsetWindowCosine": _round(windows[0]) if windows else None,
        "embeddingDimension": len(raw.get("embedding") or []),
    }


def _percentile(sorted_values: list[float], fraction: float) -> float:
    position = fraction * (len(sorted_values) - 1)
    lower = math.floor(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * (position - lower)


def pitch_reduce(raw: Mapping[str, Any]) -> dict[str, Any]:
    """F0 statistics over voiced frames (Hz and semitones about the median)."""
    f0 = list(raw.get("f0Hz") or [])
    voiced = list(raw.get("voiced") or [])
    probability = [value for value in (_finite(item) for item in raw.get("voicedProbability") or [])
                   if value is not None]
    values = sorted(hz for hz in (_finite(item) for item, flag in zip(f0, voiced) if flag is True)
                    if hz is not None and hz > 0)
    metrics: dict[str, Any] = {
        "frames": len(f0), "voicedFrames": len(values),
        "voicedFraction": _round(len(values) / len(f0)) if f0 else None,
        "meanVoicedProbability": _round(sum(probability) / len(probability)) if probability else None,
        "hopSeconds": _finite(raw.get("hopSeconds")),
    }
    if not values:
        return {**metrics, "f0MedianHz": None, "f0MeanHz": None, "f0P05Hz": None, "f0P95Hz": None,
                "f0RangeSemitones": None, "f0StdSemitones": None}
    median = _percentile(values, 0.5)
    semitones = [12.0 * math.log2(value / median) for value in values]
    mean_st = sum(semitones) / len(semitones)
    p05, p95 = _percentile(values, 0.05), _percentile(values, 0.95)
    return {
        **metrics,
        "f0MedianHz": _round(median, 4), "f0MeanHz": _round(sum(values) / len(values), 4),
        "f0P05Hz": _round(p05, 4), "f0P95Hz": _round(p95, 4),
        "f0RangeSemitones": _round(12.0 * math.log2(p95 / p05), 4),
        "f0StdSemitones": _round(math.sqrt(sum((value - mean_st) ** 2 for value in semitones) / len(semitones)), 4),
    }


def audiobox_reduce(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {axis: _finite(raw.get(axis)) for axis in ("CE", "CU", "PC", "PQ")}


def dnsmos_reduce(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {"SIG": _finite(raw.get("SIG")), "BAK": _finite(raw.get("BAK")), "OVRL": _finite(raw.get("OVRL")),
            "P808_MOS": _finite(raw.get("P808_MOS")), "windowsScored": raw.get("windowsScored")
            if type(raw.get("windowsScored")) is int else None}


def alignment_reduce(raw: Mapping[str, Any], *, duration_seconds: float) -> dict[str, Any]:
    """Alignment coverage: which expected units received an interval, and how much of the take they span."""
    expected = len(raw.get("units") or [])
    intervals = []
    for item in raw.get("intervals") or []:
        start, end = (_finite(item.get("start")), _finite(item.get("end"))) if isinstance(item, Mapping) else (None, None)
        if start is not None and end is not None and end > start >= 0.0:
            intervals.append((start, end))
    first = min((start for start, _ in intervals), default=None)
    last = max((end for _, end in intervals), default=None)
    span = (last - first) if intervals else None
    return {
        "unitsExpected": expected,
        "unitsAligned": len(intervals),
        "unitCoverage": _round(len(intervals) / expected) if expected else None,
        "spanStartSeconds": _round(first),
        "spanEndSeconds": _round(last),
        "spanCoverage": _round(span / duration_seconds) if span is not None and duration_seconds > 0 else None,
        "tailGapSeconds": _round(duration_seconds - last) if last is not None else None,
        "monotonic": all(later[0] >= earlier[0] for earlier, later in zip(intervals, intervals[1:])),
    }


def reduce(judge_id: str, category: str, raw: Mapping[str, Any], *, script: str | None, language: str,
           duration_seconds: float, reference: Mapping[str, Any] | None = None) -> tuple[dict[str, Any], str | None]:
    """A panel judge's L2 metrics and its private text (a recognizer's transcript), from its L1 output."""
    if category == "asr":
        return asr_reduce(judge_id, raw, script=script, language=language)
    if category == "lid":
        return lid_reduce(raw, language=language), None
    if category == "speaker":
        return speaker_reduce(raw, reference), None
    if category == "pitch":
        return pitch_reduce(raw), None
    if category == "audiobox":
        return audiobox_reduce(raw), None
    if category == "dnsmos":
        return dnsmos_reduce(raw), None
    if category == "alignment":
        return alignment_reduce(raw, duration_seconds=duration_seconds), None
    raise ValueError(f"unknown panel category {category!r}")


# --------------------------------------------------------------------------- #
# Report-only verdicts
# --------------------------------------------------------------------------- #

def report_only(judge: Mapping[str, Any]) -> bool:
    """A panel judge votes only when the registry says it votes and it is qualified at warn or above."""
    return not (judge.get("voting") is True and judge.get("status") in VOTING_STATUSES)


def detector_id(judge_id: str, channel: str) -> str:
    name, version = judge_id.rsplit("@", 1)
    return f"panel.{name}.{channel}@{version}"


def composer_reason(reason: str) -> str:
    """A measurement's unavailable code as a composer reason (`admission-timeout` is a timeout)."""
    mapped = COMPOSER_UNAVAILABLE.get(reason, reason)
    return mapped if mapped in UNAVAILABLE_REASONS else "crash"


def _verdict(judge_id: str, channel: str, klass: str, stage: int, status: str, reasons: list[str],
             reporting_only: bool) -> dict[str, Any]:
    verdict = {"detector": detector_id(judge_id, channel), "class": klass, "stage": stage, "judges": [judge_id],
               "status": status, "reasons": sorted(set(reasons)), "calibration": None}
    if reporting_only:
        verdict["reportOnly"] = True
    return verdict


def panel_verdicts(judge_id: str, category: str, *, stage: int, reporting_only: bool, measurement: str,
                   metrics: Mapping[str, Any], language: str, has_script: bool,
                   unavailable_reason: str | None = None,
                   language_channel: bool = False) -> list[dict[str, Any]]:
    """One judge's detector verdicts for one take (report-only unless it votes and is qualified)."""
    klass = CATEGORY_CLASS[category]
    channels: list[tuple[str, str]] = []
    if category == "asr":
        if has_script:
            channels.append(("accuracy", "B"))
        if language_channel:
            channels.append(("language", "D"))
    elif category == "lid":
        channels.append(("language", "D"))
    elif category == "speaker":
        if metrics.get("cosine") is not None or measurement == "unavailable":
            channels.append(("identity", klass))
    else:
        channels.append((CATEGORY_CHANNEL[category], klass))
    output = []
    for channel, channel_class in channels:
        if measurement == "unavailable":
            output.append(_verdict(judge_id, channel, channel_class, stage, "unavailable",
                                   [composer_reason(unavailable_reason or "crash")], reporting_only))
            continue
        if measurement != "complete":
            continue
        if category == "asr" and channel == "accuracy":
            rate = metrics.get("errorRate")
            if not isinstance(rate, (int, float)):
                continue
            status = "pass" if rate <= MAX_ACCURACY_ERROR_RATE else "fail"
        elif channel == "language" and category == "asr":
            detected = metrics.get("detectedLanguage")
            if detected is None:
                continue
            status = "pass" if detected == language else "fail"
        elif channel == "language":
            status = "pass" if metrics.get("topLanguage") == language else "fail"
        else:
            status = "uncalibrated"
        output.append(_verdict(judge_id, channel, channel_class, stage, status,
                               ["no-qualified-record"] if status == "uncalibrated" else [], reporting_only))
    return output
