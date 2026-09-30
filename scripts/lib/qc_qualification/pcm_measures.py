"""PCM shape measures that no Fast QC v8 field or Stage 0 observation carries (AQ-07 v2 detectors).

`audio_qc_calibration_set.py score` measures every clip with `measure` beside
Fast QC v8 and the Stage 0 observations and keeps the result as the clip's
`pcmMeasures` block in `measurements.json`; the detector registry reads it as
the `pcm` source (`detectors.PCM_SCORE_FIELDS`). Every measure reads the take's
PCM16 values (the persisted integers, read back at 1/32767 and rounded as
`pcm.to_pcm16` writes them), so it depends on nothing but the samples:

- `symmetricFlatTopFraction`: flat tops on both polarities. A flat top is a run
  of at least `FLAT_TOP_MIN_RUN` consecutive equal PCM16 values whose magnitude
  lies within `FLAT_TOP_PEAK_FRACTION` of the take's own peak magnitude;
  `flatTopPositive` and `flatTopNegative` count the samples on positive and on
  negative flat tops, and the score is the smaller count over the take's
  samples. Speech reaches its peak on isolated samples; a clipping stage at any
  level, below full scale (hard or soft-knee limiting) or at it (an over-range
  signal written to PCM16), holds the waveform at the level it limits to on both
  sides, run after run, while a one-sided plateau (a single clamped burst) leaves
  one polarity clean. Relative to the take's own peak, so a gain change moves
  nothing. A take without a nonzero sample has no peak and no value.
- `longestInteriorDigitalSilenceMS`: the longest run of samples that are exactly
  zero strictly between the take's first and last nonzero samples (a dropout to
  digital silence). `trailingDigitalSilenceMS` and `leadingDigitalSilenceMS`:
  the exact-zero runs after the last and before the first nonzero sample. A take
  without a nonzero sample is digital silence throughout: every run is its whole
  duration. Room tone and codec output are never exactly zero for long, whatever
  the recording's noise floor, so these do not depend on recording conditions
  as Fast QC's -60 dBFS silence floor does.
- `lastActiveSeconds`: the end of the take's last active span. 10 ms frames are
  active when their level is at least `ACTIVE_BELOW_LOUD_DB` below the take's
  loud level (the 95th percentile frame level, nearest rank) and at least
  `ACTIVE_ABOVE_FLOOR_DB` above its floor (the 10th percentile); active frames
  separated by at most `ACTIVE_GAP_FRAMES` inactive ones form one span, and only
  a span of at least `ACTIVE_MIN_FRAMES` frames counts, so a click or a short
  breath after the last word does not. None when no span counts.

`source_sha256` digests this file; `measure` stamps it into every block, and
`detectors.component_value` refuses a block measured by other code, while
`detectors.scoring_sources` binds this file into the scoring-code digest a plan
binds (A7). No file is read and no model runs here.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

import numpy as np

from .pcm import to_pcm16

PCM_MEASURES_VERSION = "pcm-measures/1"
FLAT_TOP_PEAK_FRACTION = 0.99
FLAT_TOP_MIN_RUN = 2
FRAME_SECONDS = 0.01
LOUD_QUANTILE = 0.95
FLOOR_QUANTILE = 0.10
ACTIVE_BELOW_LOUD_DB = 35.0
ACTIVE_ABOVE_FLOOR_DB = 10.0
ACTIVE_GAP_FRAMES = 5
ACTIVE_MIN_FRAMES = 15
LEVEL_FLOOR_DB = -120.0
ROUNDING_DECIMALS = 9
FIELDS = ("peakPCM16", "flatTopPositive", "flatTopNegative", "symmetricFlatTopFraction",
          "longestInteriorDigitalSilenceMS", "trailingDigitalSilenceMS", "leadingDigitalSilenceMS",
          "lastActiveSeconds")


def source_sha256() -> str:
    """The digest of this module's bytes, which every measured block carries."""
    return hashlib.sha256(Path(__file__).resolve().read_bytes()).hexdigest()


def pcm16_values(samples: Any) -> np.ndarray:
    """The take's PCM16 integers (int64), as `pcm.to_pcm16` writes them."""
    return to_pcm16(np.asarray(samples, dtype=np.float64)).astype(np.int64)


def _runs(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(start, length) of every maximal run of equal consecutive values."""
    if values.size == 0:
        return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64)
    starts = np.concatenate(([0], np.flatnonzero(values[1:] != values[:-1]) + 1))
    lengths = np.diff(np.concatenate((starts, [values.size])))
    return starts, lengths


def flat_tops(values: np.ndarray) -> dict:
    """The take's peak magnitude and its samples on positive and negative flat tops within 1% of it, and the
    sign-symmetric score (see the module docstring)."""
    values = np.asarray(values, dtype=np.int64)
    peak = int(np.max(np.abs(values))) if values.size else 0
    if peak == 0:
        return {"peakPCM16": peak, "flatTopPositive": None, "flatTopNegative": None,
                "symmetricFlatTopFraction": None}
    starts, lengths = _runs(values)
    levels = values[starts]
    held = (lengths >= FLAT_TOP_MIN_RUN) & (np.abs(levels) >= FLAT_TOP_PEAK_FRACTION * peak)
    positive = int(lengths[held & (levels > 0)].sum())
    negative = int(lengths[held & (levels < 0)].sum())
    return {"peakPCM16": peak, "flatTopPositive": positive, "flatTopNegative": negative,
            "symmetricFlatTopFraction": min(positive, negative) / values.size}


def digital_silence(values: np.ndarray, sample_rate: int) -> dict:
    """The exact-zero runs inside, after and before the take's nonzero samples, in milliseconds."""
    values = np.asarray(values, dtype=np.int64)
    milliseconds = 1000.0 / sample_rate
    nonzero = np.flatnonzero(values != 0)
    if nonzero.size == 0:
        whole = values.size * milliseconds
        return {"longestInteriorDigitalSilenceMS": whole, "trailingDigitalSilenceMS": whole,
                "leadingDigitalSilenceMS": whole}
    first, last = int(nonzero[0]), int(nonzero[-1])
    gaps = np.diff(nonzero) - 1
    interior = int(gaps.max()) if gaps.size else 0
    return {"longestInteriorDigitalSilenceMS": interior * milliseconds,
            "trailingDigitalSilenceMS": (values.size - 1 - last) * milliseconds,
            "leadingDigitalSilenceMS": first * milliseconds}


def _nearest_rank(ordered: np.ndarray, quantile: float) -> float:
    index = min(ordered.size - 1, max(0, math.ceil(quantile * ordered.size) - 1))
    return float(ordered[index])


def frame_levels(values: np.ndarray, sample_rate: int) -> np.ndarray:
    """Each whole 10 ms frame's mean-square level in dBFS (at 1/32767), floored at -120 dB."""
    size = int(round(FRAME_SECONDS * sample_rate))
    count = np.asarray(values).size // size
    if count == 0:
        return np.zeros(0)
    frames = (np.asarray(values[:count * size], dtype=np.float64) / 32767.0).reshape(count, size)
    power = np.mean(frames * frames, axis=1)
    return np.maximum(10.0 * np.log10(np.maximum(power, 1e-30)), LEVEL_FLOOR_DB)


def last_active_seconds(values: np.ndarray, sample_rate: int) -> float | None:
    """The end, in seconds, of the take's last active span (see the module docstring)."""
    levels = frame_levels(values, sample_rate)
    if levels.size == 0:
        return None
    ordered = np.sort(levels)
    threshold = max(_nearest_rank(ordered, LOUD_QUANTILE) - ACTIVE_BELOW_LOUD_DB,
                    _nearest_rank(ordered, FLOOR_QUANTILE) + ACTIVE_ABOVE_FLOOR_DB)
    active = np.flatnonzero(levels >= threshold)
    if active.size == 0:
        return None
    # Spans: active frames joined across gaps of at most ACTIVE_GAP_FRAMES inactive frames.
    breaks = np.flatnonzero(np.diff(active) > ACTIVE_GAP_FRAMES + 1)
    span_starts = np.concatenate(([active[0]], active[breaks + 1]))
    span_ends = np.concatenate((active[breaks], [active[-1]]))
    kept = np.flatnonzero(span_ends - span_starts + 1 >= ACTIVE_MIN_FRAMES)
    if kept.size == 0:
        return None
    return float(span_ends[kept[-1]] + 1) * FRAME_SECONDS


def measure(samples: Any, sample_rate: int) -> dict:
    """The clip's `pcmMeasures` block: every field of `FIELDS`, the version and this module's digest."""
    values = pcm16_values(samples)
    block: dict[str, Any] = {"version": PCM_MEASURES_VERSION, "sourceSHA256": source_sha256(),
                             "sampleRate": int(sample_rate), "samples": int(values.size)}
    block.update(flat_tops(values))
    block.update(digital_silence(values, sample_rate))
    block["lastActiveSeconds"] = last_active_seconds(values, sample_rate)
    for key in FIELDS:
        if isinstance(block[key], float):
            block[key] = round(block[key], ROUNDING_DECIMALS)
    return block
