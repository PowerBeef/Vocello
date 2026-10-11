"""Bounded acoustic nominations, not whisper/stutter or quality decisions.

The caller supplies the already validated 60 ms acoustic profile. A separate
20 ms energy scan can discover bursts absent from either phone transcript.
Fixed extraction settings are deliberately uncalibrated; no label is consumed.
"""
from __future__ import annotations

import math

import numpy as np

from qc import phones

SCHEMA = "vocello.qc.acoustic-candidates/1"
MAX_CANDIDATES = 128
MAX_WINDOWS = 2048
MAX_TARGETS = 16
MAX_DURATION_SECONDS = 120
MAX_BATCH_SAMPLES = 524288
SONORANTS = phones.VOWELS | frozenset("mnɲŋljwɥ")
SETTINGS = {
    "phonationContextSeconds": .120, "phonationMaximumCorrelation": .6,
    "phonationMinimumFlatness": .08, "phonationMinimumHighLowDb": 0.,
    "phonationMinimumFrames": 2, "minimumLevelDbfs": -70.,
    "phonationRelativeFloorDb": 25., "burstWindowSeconds": .020,
    "burstHopSeconds": .005, "burstReferencePercentile": 80.,
    "burstRelativeFloorDb": 20., "burstAbsoluteFloorDbfs": -65.,
    "burstMinimumSeconds": .020, "burstMaximumSeconds": .200,
    "burstFlankSeconds": .080, "burstMinimumFlankContrastDb": 6.,
    "alignmentMarginSeconds": .020, "burstMinimumFlankFrames": 8,
    "maximumCandidatesPerProducer": MAX_CANDIDATES, "maximumTargetsPerCandidate": MAX_TARGETS,
    "interpretation": "fixed-uncalibrated-extraction-not-acceptance-thresholds",
}


def _section(status="unavailable", reason=None):
    value = {"schema": SCHEMA, "inputStatus": status, "qualification": "uncalibrated",
             "decision": "not-assessed", "settings": dict(SETTINGS), "candidates": [], "coverage": {},
             "limitations": ["no-qualified-defect-threshold", "request-delivery-compatibility-unassessed"]}
    if reason:
        value["reason"] = reason
    return value


def _runs(mask):
    edges = np.flatnonzero(np.diff(np.r_[False, mask, False]))
    return zip(edges[::2], edges[1::2])


def _span(item, duration):
    if not isinstance(item, dict):
        return None
    start, end = item.get("start"), item.get("end")
    if (any(type(v) not in (int, float) or not math.isfinite(v) for v in (start, end))
            or not 0 <= start < end <= duration):
        return None
    return start, end


def _windows(items, duration):
    if items is None:
        return [], True
    if not isinstance(items, (list, tuple)) or len(items) > MAX_WINDOWS:
        return [], False
    spans = []
    valid = True
    for item in items:
        span = _span(item, duration)
        if span is None:
            valid = False
        else:
            spans.append((span[0], span[1], item))
    return spans, valid


def phonation(profile, expected_windows, duration):
    """Nominate low-periodicity spectral regions near expected sonorants.

    Acoustic frame support can extend beyond the expected phone. No missing F0
    becomes zero or silence; rhotics/fricatives are not assumed voiced targets.
    """
    result = _section()
    if duration > MAX_DURATION_SECONDS:
        result["reason"] = "candidate-duration-limit-exceeded"
        return result
    windows, valid = _windows(expected_windows, duration)
    eligible = [(a, b, w) for a, b, w in windows
                if isinstance(w.get("phone"), str) and w["phone"][:1] in SONORANTS]
    result["coverage"] = {"expectedWindows": len(windows), "eligibleWindows": len(eligible)}
    if not valid:
        result["reason"] = "invalid-or-excessive-expected-windows"
        return result
    if not eligible:
        result["reason"] = "no-eligible-expected-sonorants"
        return result
    if not (np.isfinite(profile["flatness"]).any() or np.isfinite(profile["band_ratio"]).any()):
        result["reason"] = "no-supported-spectral-frames"
        return result
    if not np.isfinite(profile["correlation"]).any():
        result["reason"] = "no-signal-supported-periodicity-frames"
        return result
    level = profile["level"]
    reference = float(np.median(level[np.isfinite(level)]))
    spectral = ((profile["flatness"] > SETTINGS["phonationMinimumFlatness"])
                | (profile["band_ratio"] > SETTINGS["phonationMinimumHighLowDb"]))
    low_periodicity = ((profile["correlation"] < SETTINGS["phonationMaximumCorrelation"])
                       & spectral & (level > max(SETTINGS["minimumLevelDbfs"], reference - SETTINGS["phonationRelativeFloorDb"])))
    nominated = np.zeros(len(level), dtype=bool)
    supported_frames = (np.isfinite(profile["correlation"]) & np.isfinite(level)
        & (np.isfinite(profile["flatness"]) | np.isfinite(profile["band_ratio"])))
    targets = []
    supported_targets = 0
    for start, end, item in eligible:
        center = (start + end) / 2
        half = SETTINGS["phonationContextSeconds"] / 2
        a, b = max(0., center - half), min(duration, center + half)
        mask = (profile["center"] >= a) & (profile["center"] < b)
        if not np.any(mask & supported_frames):
            continue
        supported_targets += 1
        nominated |= mask & supported_frames
        targets.append((a, b, {"start": start, "end": end, "phone": item["phone"],
                               "source": item.get("source")}))
    result["coverage"].update(supportedTargets=supported_targets,
        unsupportedTargets=len(eligible) - supported_targets)
    if not supported_targets:
        result["reason"] = "no-signal-supported-target-contexts"
        return result
    result["inputStatus"] = "complete" if supported_targets == len(eligible) else "partial"
    if supported_targets < len(eligible):
        result["reason"] = "some-target-contexts-unsupported"
    for a, b in _runs(low_periodicity & nominated):
        if b - a < SETTINGS["phonationMinimumFrames"]:
            continue
        if len(result["candidates"]) >= MAX_CANDIDATES:
            result.update(inputStatus="partial", reason="candidate-budget-exceeded")
            break
        start, end = float(profile["start"][a]), float(profile["end"][b - 1])
        supporting = [item for x, y, item in targets if x < end and y > start]
        truncated = len(supporting) > MAX_TARGETS
        if truncated:
            result.update(inputStatus="partial", reason="target-provenance-budget-exceeded")
        result["candidates"].append({"class": "phonation-anomaly", "start": start, "end": end,
            "candidateType": "expected-sonorant-low-periodicity", "source": "acoustic-phonation",
            "status": "candidate", "frames": int(b - a), "expectedTargets": supporting[:MAX_TARGETS],
            "targetProvenanceTruncated": truncated,
            "medianCorrelation": float(np.median(profile["correlation"][a:b])),
            "medianLevelDbfs": float(np.median(level[a:b])),
            "uncertainties": ["context-may-include-adjacent-phones", "expected-phone-timing-is-approximate",
                              "unvoiced-consonant-noise-breath-and-alignment-confounds",
                              "candidate-is-not-a-whisper-verdict"]})
    result["limitations"].append("normal-contextual-sonorant-devoicing-can-be-nominated")
    return result


def _energy(raw, rate):
    size, hop = round(SETTINGS["burstWindowSeconds"] * rate), round(SETTINGS["burstHopSeconds"] * rate)
    count = 1 + (len(raw) - size) // hop
    levels = np.empty(count)
    batch = max(1, MAX_BATCH_SAMPLES // size)
    for offset in range(0, count, batch):
        length = min(batch, count - offset)
        segment = raw[offset * hop:(offset + length - 1) * hop + size]
        frames = np.lib.stride_tricks.sliding_window_view(segment, size)[::hop]
        frames = np.array(frames, dtype=np.float64, copy=True)
        levels[offset:offset + length] = 20 * np.log10(np.maximum(np.sqrt(np.mean(frames * frames, axis=1)), 1e-12))
    starts = np.arange(count) * hop / rate
    return levels, starts, starts + size / rate


def fragments(raw, rate, profile, expected_windows, recognized_windows, duration):
    """Scan full audio for short isolated energy bursts, independent of errors.

    Expected/recognized timing only describes coverage after nomination. A burst
    covered by either inventory contributes to the aligned-burst count. Missing
    inventories make coverage partial, never clean.
    """
    result = _section("complete")
    if duration > MAX_DURATION_SECONDS:
        return _section(reason="candidate-duration-limit-exceeded")
    expected, expected_valid = _windows(expected_windows, duration)
    recognized, recognized_valid = _windows(recognized_windows, duration)
    alignment_available = bool(expected or recognized)
    if not expected_valid or not recognized_valid:
        result.update(inputStatus="partial", reason="invalid-or-excessive-alignment-windows")
    elif not alignment_available:
        result.update(inputStatus="partial", reason="no-alignment-coverage")
    if len(raw) < round(SETTINGS["burstWindowSeconds"] * rate):
        return _section(reason="audio-shorter-than-burst-window")
    level, starts, ends = _energy(raw, rate)
    threshold = max(SETTINGS["burstAbsoluteFloorDbfs"],
                    float(np.percentile(level, SETTINGS["burstReferencePercentile"])) - SETTINGS["burstRelativeFloorDb"])
    result["coverage"] = {"energyFrames": len(level), "energyFloorDbfs": threshold,
        "expectedWindows": len(expected), "recognizedWindows": len(recognized),
        "alignmentAvailable": alignment_available, "alignedShortBursts": 0,
        "tailUnanalyzedSeconds": max(0., duration - float(ends[-1]))}
    result["limitations"] += ["burst-is-not-confirmed-speech-or-false-start",
                              "breath-click-hesitation-and-word-transition-confounds",
                              "ctc-occupancy-is-not-complete-speech-coverage"]
    for a, b in _runs(level > threshold):
        start, end = float(starts[a]), float(ends[b - 1])
        if not SETTINGS["burstMinimumSeconds"] <= end - start <= SETTINGS["burstMaximumSeconds"]:
            continue
        flank = SETTINGS["burstFlankSeconds"]
        left = level[(ends <= start) & (starts >= start - flank)]
        right = level[(starts >= end) & (ends <= end + flank)]
        minimum_flank_frames = SETTINGS["burstMinimumFlankFrames"]
        if min(len(left), len(right)) < minimum_flank_frames:
            continue  # edges do not acquire synthetic quiet padding
        peak = float(np.max(level[a:b]))
        contrast = peak - max(float(np.median(left)), float(np.median(right)))
        if contrast < SETTINGS["burstMinimumFlankContrastDb"]:
            continue
        margin = SETTINGS["alignmentMarginSeconds"]
        covered = any(x < end + margin and y > start - margin for x, y, _ in (*expected, *recognized))
        if covered:
            result["coverage"]["alignedShortBursts"] += 1
            continue
        if len(result["candidates"]) >= MAX_CANDIDATES:
            result.update(inputStatus="partial", reason="candidate-budget-exceeded")
            break
        long = (profile["end"] > start) & (profile["start"] < end)
        correlations = profile["correlation"][long]
        correlations = correlations[np.isfinite(correlations)]
        result["candidates"].append({"class": "short-fragment", "start": start, "end": end,
            "source": "acoustic-burst", "candidateType": "isolated-unaligned-burst", "status": "candidate",
            "energyFrames": int(b - a), "peakLevelDbfs": peak, "flankContrastDb": contrast,
            "alignmentCoverage": "uncovered" if alignment_available else "unknown",
            "contextMaximumCorrelation": float(np.max(correlations)) if correlations.size else None,
            "uncertainties": ["context-periodicity-support-overlaps-burst-boundaries",
                              "not-a-stutter-or-extra-syllable-verdict"]})
    return result
