#!/usr/bin/env python3
"""Bounded temporal-contour features for the governed delivery harness.

The analyzer makes two streaming passes and retains five fixed region
accumulators. It never materializes a clip-wide frame matrix. Requested preset
labels are not inputs; paired deltas are computed only after blind extraction.
"""

from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from analyze_prosody import (  # noqa: E402
    ALPHA_RATIO_HIGH_BAND,
    ALPHA_RATIO_LOW_BAND,
    CPP_QUEFRENCY_MAX_HZ,
    CPP_QUEFRENCY_MIN_HZ,
    F0_HISTOGRAM_STEP_HZ,
    F0_MAX,
    F0_MIN,
    FRAME_MS,
    HF_ENERGY_EDGE_HZ,
    HOP_MS,
    HNR_HISTOGRAM_MAX_DB,
    HNR_HISTOGRAM_MIN_DB,
    HNR_HISTOGRAM_STEP_DB,
    HAMMARBERG_HIGH_BAND,
    HAMMARBERG_LOW_BAND,
    PAUSE_RMS_DB,
    RMS_HISTOGRAM_MAX_DB,
    RMS_HISTOGRAM_MIN_DB,
    RMS_HISTOGRAM_STEP_DB,
    VOICING_AC,
    FixedHistogram,
    ManagedMemoryEstimate,
    RunningMoments,
    _analysis_frames,
    _band_peak_db,
    _band_power,
    _metadata,
    _rms_db,
    cepstral_peak_prominence_db,
    f0_autocorr,
    hnr_db,
)


SCHEMA_VERSION = 1
REGION_COUNT = 5
LAYER_ID = "temporal-contour"
LAYER_VERSION = "1"


class TemporalFeatureError(ValueError):
    """Temporal analysis could not produce a finite, source-bound result."""


class LinearTrend:
    __slots__ = ("count", "sum_x", "sum_y", "sum_xx", "sum_xy")

    def __init__(self) -> None:
        self.count = 0
        self.sum_x = self.sum_y = self.sum_xx = self.sum_xy = 0.0

    def add(self, x: float, y: float) -> None:
        self.count += 1
        self.sum_x += x
        self.sum_y += y
        self.sum_xx += x * x
        self.sum_xy += x * y

    @property
    def slope(self) -> float:
        denominator = self.count * self.sum_xx - self.sum_x * self.sum_x
        if self.count < 2 or abs(denominator) < 1e-12:
            return 0.0
        return (self.count * self.sum_xy - self.sum_x * self.sum_y) / denominator


@dataclass
class RegionAccumulator:
    f0: FixedHistogram
    rms: FixedHistogram
    hnr: FixedHistogram
    f0_trend: LinearTrend
    hnr_mean: RunningMoments
    cpp: RunningMoments
    alpha: RunningMoments
    hammarberg: RunningMoments
    hf_ratio: RunningMoments
    centroid: RunningMoments
    flux: RunningMoments
    f0_instability: RunningMoments
    frame_count: int = 0
    voiced_count: int = 0
    syllable_peaks: int = 0
    pause_onsets: int = 0
    pause_offsets: int = 0
    first_f0: float | None = None
    last_f0: float | None = None
    previous_f0: float | None = None

    @classmethod
    def create(cls, memory: ManagedMemoryEstimate) -> "RegionAccumulator":
        f0 = FixedHistogram(F0_MIN - F0_HISTOGRAM_STEP_HZ / 2, F0_MAX + F0_HISTOGRAM_STEP_HZ / 2, F0_HISTOGRAM_STEP_HZ)
        rms = FixedHistogram(RMS_HISTOGRAM_MIN_DB, RMS_HISTOGRAM_MAX_DB, RMS_HISTOGRAM_STEP_DB)
        hnr = FixedHistogram(HNR_HISTOGRAM_MIN_DB, HNR_HISTOGRAM_MAX_DB, HNR_HISTOGRAM_STEP_DB)
        for histogram in (f0, rms, hnr):
            memory.own_histogram(histogram)
        return cls(
            f0, rms, hnr, LinearTrend(), RunningMoments(), RunningMoments(),
            RunningMoments(), RunningMoments(), RunningMoments(), RunningMoments(),
            RunningMoments(), RunningMoments(),
        )

    def report(self) -> dict[str, float | int]:
        duration = self.frame_count * HOP_MS / 1000.0
        f0_median = self.f0.quantile(0.5)
        return {
            "f0MedianHz": f0_median,
            "f0RangeHz": max(0.0, self.f0.quantile(0.9) - self.f0.quantile(0.1)),
            "f0SlopeHzPerSecond": self.f0_trend.slope / max(HOP_MS / 1000.0, 1e-9),
            "voicedFraction": self.voiced_count / self.frame_count if self.frame_count else 0.0,
            "rmsMedianDBFS": self.rms.quantile(0.5),
            "dynamicRangeDB": max(0.0, self.rms.quantile(0.9) - self.rms.quantile(0.1)),
            "hnrDB": self.hnr_mean.mean if self.hnr_mean.count else 0.0,
            "cppDB": self.cpp.mean if self.cpp.count else 0.0,
            "alphaRatioDB": self.alpha.mean if self.alpha.count else 0.0,
            "hammarbergDB": self.hammarberg.mean if self.hammarberg.count else 0.0,
            "highFrequencyEnergyRatio": self.hf_ratio.mean if self.hf_ratio.count else 0.0,
            "spectralCentroidHz": self.centroid.mean if self.centroid.count else 0.0,
            "spectralFlux": self.flux.mean if self.flux.count else 0.0,
            "syllableRateHz": self.syllable_peaks / duration if duration > 0 else 0.0,
            "pauseOnsets": self.pause_onsets,
            "pauseOffsets": self.pause_offsets,
            "f0InstabilityHz": self.f0_instability.mean if self.f0_instability.count else 0.0,
        }


def _counts(path: str, memory: ManagedMemoryEstimate) -> tuple[int, int, int, float]:
    metadata = _metadata(path)
    frames = voiced = audible = 0
    maximum_rms_db = -240.0
    for _index, frame in _analysis_frames(path, metadata, memory):
        frames += 1
        _rms, rms_db = _rms_db(frame)
        maximum_rms_db = max(maximum_rms_db, rms_db)
        f0, correlation = f0_autocorr(frame, metadata.sample_rate)
        if correlation >= VOICING_AC and f0 > 0:
            voiced += 1
        if rms_db >= PAUSE_RMS_DB:
            audible += 1
    if frames == 0:
        raise TemporalFeatureError("audio contains no complete analysis frames")
    return frames, voiced, audible, maximum_rms_db


def _region_index(seen: int, total: int) -> int:
    return min(REGION_COUNT - 1, max(0, seen * REGION_COUNT // max(total, 1)))


def analyze_temporal(path: str) -> dict[str, Any]:
    metadata = _metadata(path)
    memory = ManagedMemoryEstimate()
    frame_count, voiced_total, audible_total, maximum_rms_db = _counts(path, memory)
    segmentation = "voiced-content" if voiced_total else "audible-content-fallback"
    content_total = voiced_total if voiced_total else audible_total
    if content_total == 0:
        raise TemporalFeatureError("audio contains no voiced or audible analysis content")
    regions = [RegionAccumulator.create(memory) for _ in range(REGION_COUNT)]
    window = np.hanning(max(1, int(metadata.sample_rate * FRAME_MS / 1000.0)))
    frequencies = np.fft.rfftfreq(len(window), d=1.0 / metadata.sample_rate)
    previous_spectrum: np.ndarray | None = None
    content_seen = 0
    last_region = 0
    in_pause = False
    envelope: deque[tuple[int, float]] = deque(maxlen=3)

    for frame_index, frame in _analysis_frames(path, metadata, memory):
        rms, rms_db = _rms_db(frame)
        f0, correlation = f0_autocorr(frame, metadata.sample_rate)
        voiced = correlation >= VOICING_AC and f0 > 0
        audible = rms_db >= PAUSE_RMS_DB
        advances = voiced if voiced_total else audible
        region_index = _region_index(content_seen, content_total)
        if advances:
            content_seen += 1
        last_region = region_index
        region = regions[region_index]
        region.frame_count += 1
        region.rms.add(rms_db)
        if voiced:
            region.voiced_count += 1
            region.f0.add(f0)
            region.f0_trend.add(float(region.frame_count), f0)
            region.hnr.add(hnr_db(correlation))
            region.hnr_mean.add(hnr_db(correlation))
            if region.first_f0 is None:
                region.first_f0 = f0
            if region.previous_f0 is not None:
                region.f0_instability.add(abs(f0 - region.previous_f0))
            region.previous_f0 = f0
            region.last_f0 = f0

        silent = rms_db < PAUSE_RMS_DB
        if silent and not in_pause:
            region.pause_onsets += 1
            in_pause = True
        elif not silent and in_pause:
            region.pause_offsets += 1
            in_pause = False

        envelope.append((region_index, rms / max(1.0, 10 ** (maximum_rms_db / 20.0) * 32768.0)))
        if len(envelope) == 3:
            left, middle, right = envelope
            if middle[1] > left[1] and middle[1] >= right[1] and middle[1] > 0.15:
                regions[middle[0]].syllable_peaks += 1

        if audible:
            spectrum = np.fft.rfft(frame * window)
            magnitude = np.abs(spectrum)
            power = magnitude * magnitude
            total = float(power.sum())
            memory.observe(spectrum, magnitude, power, frequencies, window)
            if total > 0:
                low = _band_power(power, frequencies, *ALPHA_RATIO_LOW_BAND)
                high = _band_power(power, frequencies, *ALPHA_RATIO_HIGH_BAND)
                region.alpha.add(10.0 * math.log10(max(low, 1e-30) / max(high, 1e-30)))
                region.hammarberg.add(
                    _band_peak_db(power, frequencies, *HAMMARBERG_LOW_BAND)
                    - _band_peak_db(power, frequencies, *HAMMARBERG_HIGH_BAND)
                )
                region.hf_ratio.add(_band_power(power, frequencies, HF_ENERGY_EDGE_HZ, float(metadata.sample_rate)) / total)
                region.centroid.add(float(np.dot(frequencies, power) / total))
                normalized = magnitude / math.sqrt(total)
                if previous_spectrum is not None:
                    difference = normalized - previous_spectrum
                    region.flux.add(float(np.sqrt(np.dot(difference, difference))))
                previous_spectrum = normalized
                log_magnitude = np.log(np.maximum(magnitude, 1e-30))
                region.cpp.add(cepstral_peak_prominence_db(
                    log_magnitude, metadata.sample_rate,
                    CPP_QUEFRENCY_MIN_HZ, CPP_QUEFRENCY_MAX_HZ,
                ))
                memory.observe(normalized, log_magnitude)
    if in_pause:
        regions[last_region].pause_offsets += 1

    region_reports = [region.report() for region in regions]
    f0 = [float(region["f0MedianHz"]) for region in region_reports]
    energy = [float(region["rmsMedianDBFS"]) for region in region_reports]
    cadence = [float(region["syllableRateHz"]) for region in region_reports]
    peak_index = int(np.argmax(f0)) if any(value > 0 for value in f0) else 0
    local_moves = [right - left for left, right in zip(f0, f0[1:])]
    pause_counts = [int(region["pauseOnsets"]) for region in region_reports]
    pause_total = sum(pause_counts)
    breathy = [
        float(region["hnrDB"]) < 3.0 or float(region["cppDB"]) < 6.0
        for region in region_reports
    ]
    tense = [
        float(region["spectralCentroidHz"]) > 1200.0
        and float(region["hammarbergDB"]) < 25.0
        for region in region_reports
    ]
    derived = {
        "onsetToEndPitchHz": f0[-1] - f0[0],
        "onsetToPeakPitchHz": f0[peak_index] - f0[0],
        "peakToEndPitchHz": f0[-1] - f0[peak_index],
        "maximumLocalRiseHz": max([0.0, *local_moves]),
        "maximumLocalFallHz": min([0.0, *local_moves]),
        "normalizedPeakPosition": peak_index / (REGION_COUNT - 1),
        "phraseFinalPitchSlopeHz": f0[-1] - f0[-2],
        "energyAttackDB": energy[1] - energy[0],
        "energyReleaseDB": energy[-1] - max(energy),
        "cadenceAccelerationHz": cadence[-1] - cadence[0],
        "pausePositionHistogram": [count / pause_total if pause_total else 0.0 for count in pause_counts],
        "breathinessPersistence": sum(breathy) / REGION_COUNT,
        "tensionPersistence": sum(tense) / REGION_COUNT,
        "contourAbruptnessHz": max([0.0, *(abs(value) for value in local_moves)]),
        "tremorPersistenceHz": sum(float(region["f0InstabilityHz"]) for region in region_reports) / REGION_COUNT,
    }
    frame_samples = int(metadata.sample_rate * FRAME_MS / 1000.0)
    report = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "bounded-temporal-delivery-features",
        "promotionAuthority": False,
        "layerID": LAYER_ID,
        "layerVersion": LAYER_VERSION,
        "regionCount": REGION_COUNT,
        "segmentationBasis": segmentation,
        "regions": region_reports,
        "derivedContours": derived,
        "memory": {
            "boundedByClipDuration": False,
            "analysisPasses": 2,
            "frameCount": frame_count,
            "measuredPeakManagedBufferBytes": memory.measured_peak_managed_buffer_bytes,
            "estimatedPeakWorkingSetBytes": memory.estimated_peak_working_set_bytes(
                frame_samples, metadata.channel_count
            ) + REGION_COUNT * 16_384,
        },
    }
    _require_finite(report)
    return report


def _numeric_delta(left: Any, right: Any) -> Any:
    if isinstance(left, dict) and isinstance(right, dict):
        return {
            key: _numeric_delta(left[key], right[key])
            for key in left.keys() & right.keys()
            if key not in {"schemaVersion", "kind", "promotionAuthority", "layerID", "layerVersion", "memory", "segmentationBasis"}
        }
    if isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
        return [_numeric_delta(a, b) for a, b in zip(left, right)]
    if isinstance(left, bool) or isinstance(right, bool):
        return None
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return float(left) - float(right)
    return None


def paired_temporal_delta(instructed: dict[str, Any], neutral: dict[str, Any]) -> dict[str, Any]:
    if instructed.get("schemaVersion") != SCHEMA_VERSION or neutral.get("schemaVersion") != SCHEMA_VERSION:
        raise TemporalFeatureError("paired temporal inputs have incompatible schemas")
    result = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "instructed-minus-neutral-temporal-delta",
        "promotionAuthority": False,
        "regions": _numeric_delta(instructed["regions"], neutral["regions"]),
        "derivedContours": _numeric_delta(
            instructed["derivedContours"], neutral["derivedContours"]
        ),
    }
    _require_finite(result)
    return result


def _require_finite(value: Any) -> None:
    if isinstance(value, dict):
        for child in value.values():
            _require_finite(child)
    elif isinstance(value, list):
        for child in value:
            _require_finite(child)
    elif isinstance(value, float) and not math.isfinite(value):
        raise TemporalFeatureError("temporal feature output contains a non-finite value")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wav", type=Path)
    parser.add_argument("--neutral", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        result = analyze_temporal(str(args.wav))
        if args.neutral:
            result = paired_temporal_delta(result, analyze_temporal(str(args.neutral)))
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (TemporalFeatureError, ValueError, OSError) as error:
        print(f"Delivery temporal features: FAIL\n{error}", file=__import__("sys").stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
