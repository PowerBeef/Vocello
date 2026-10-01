"""Pitch helpers for Vocello QC v2: two-tracker agreement, sustained shifts, octave jumps, tone runs.

Pure numpy. Every function takes a pitch track as the runner `outputs` mapping of the pitch schema
(`{"hopSeconds", "f0Hz": [float or null], "confidence"}`), a `Track`, or an `Agreement` (whose
consensus track is used). Frame `i` of a track sits at `i * hopSeconds`; `None`, NaN and non-positive
values are unvoiced.

The two trackers (FCPE and SwiftF0) are combined first: a frame counts only where both are voiced
and within 50 cents of each other. That removes the single-tracker octave errors and voicing drops
that made pYIN report pitch "all over the place", while a real pitch change, seen by both trackers,
survives. Semitones are relative to 100 Hz throughout.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np

REFERENCE_HZ = 100.0


@dataclass(frozen=True)
class Track:
    """A pitch track on a uniform grid: `f0[i]` (Hz, NaN when unvoiced) sits at `i * hop` seconds."""

    hop: float
    f0: np.ndarray
    confidence: np.ndarray | None = None

    @property
    def times(self) -> np.ndarray:
        return np.arange(self.f0.size) * self.hop

    @property
    def voiced(self) -> np.ndarray:
        return np.isfinite(self.f0)

    @property
    def semitones(self) -> np.ndarray:
        return hz_to_semitones(self.f0)


@dataclass(frozen=True)
class Agreement:
    """Two tracks on one grid. `agree` frames are both voiced and within `cents` of each other."""

    hop: float
    f0_a: np.ndarray
    f0_b: np.ndarray
    cents_diff: np.ndarray  # b relative to a, NaN unless both voiced
    agree: np.ndarray
    octave: np.ndarray  # both voiced and about 1200 cents apart
    cents: float

    @property
    def both_voiced(self) -> np.ndarray:
        return np.isfinite(self.cents_diff)

    @property
    def consensus(self) -> Track:
        """The geometric mean of both trackers on agreeing frames, NaN elsewhere."""
        f0 = np.full(self.f0_a.shape, np.nan)
        mask = self.agree
        f0[mask] = np.sqrt(self.f0_a[mask] * self.f0_b[mask])
        return Track(self.hop, f0)

    def summary(self) -> dict[str, Any]:
        both = int(self.both_voiced.sum())
        voiced_any = int((np.isfinite(self.f0_a) | np.isfinite(self.f0_b)).sum())
        return {
            "hopSeconds": self.hop,
            "frames": int(self.agree.size),
            "voicedEither": voiced_any,
            "voicedBoth": both,
            "agreeing": int(self.agree.sum()),
            "octaveDisagreements": int(self.octave.sum()),
            "agreeRatio": float(self.agree.sum() / both) if both else None,
            "octaveRatio": float(self.octave.sum() / both) if both else None,
            "voicingAgreement": float(both / voiced_any) if voiced_any else None,
        }


def hz_to_semitones(f0: Any) -> np.ndarray:
    """Semitones relative to 100 Hz; NaN where the input is unvoiced."""
    values = np.asarray(f0, dtype=float)
    out = np.full(values.shape, np.nan)
    voiced = np.isfinite(values) & (values > 0)
    out[voiced] = 12.0 * np.log2(values[voiced] / REFERENCE_HZ)
    return out


def semitones_to_hz(semitones: float) -> float:
    return float(REFERENCE_HZ * 2.0 ** (semitones / 12.0))


def as_track(track: Any) -> Track:
    """Accept a pitch-schema mapping, a `Track`, an `Agreement` or a `(hop, f0)` pair."""
    if isinstance(track, Track):
        return track
    if isinstance(track, Agreement):
        return track.consensus
    if isinstance(track, Mapping):
        if "outputs" in track and isinstance(track["outputs"], Mapping):
            track = track["outputs"]
        hop = float(track["hopSeconds"])
        f0 = _f0_array(track["f0Hz"])
        confidence = track.get("confidence")
        conf = np.asarray(confidence, dtype=float) if confidence is not None else None
        return Track(hop, f0, conf)
    if isinstance(track, tuple) and len(track) == 2:
        return Track(float(track[0]), _f0_array(track[1]))
    raise TypeError(f"not a pitch track: {type(track).__name__}")


def _f0_array(values: Sequence[Any]) -> np.ndarray:
    f0 = np.array([np.nan if v is None else float(v) for v in values], dtype=float)
    f0[~np.isfinite(f0) | (f0 <= 0)] = np.nan
    return f0


def resample_track(track: Any, hop: float, frames: int | None = None) -> np.ndarray:
    """Nearest-frame resampling onto `k * hop`; frames past the source end are unvoiced."""
    source = as_track(track)
    if hop <= 0:
        raise ValueError("hop must be positive")
    if frames is None:
        duration = (source.f0.size - 1) * source.hop if source.f0.size else 0.0
        frames = int(np.floor(duration / hop + 1e-9)) + 1 if source.f0.size else 0
    times = np.arange(frames) * hop
    index = np.rint(times / source.hop).astype(int)
    out = np.full(frames, np.nan)
    valid = index < source.f0.size
    out[valid] = source.f0[index[valid]]
    return out


def agreeing_frames(
    a: Any,
    b: Any,
    cents: float = 50.0,
    hop: float | None = None,
    octave_tolerance_cents: float = 100.0,
) -> Agreement:
    """Resample both tracks to one hop and keep the frames where both are voiced and within `cents`.

    The default common hop is the finer of the two. Frames where both are voiced and about one
    octave apart (1200 +/- `octave_tolerance_cents`) are flagged in `octave`; they never agree.
    """
    track_a, track_b = as_track(a), as_track(b)
    step = float(hop) if hop else min(track_a.hop, track_b.hop)
    duration = max((track_a.f0.size - 1) * track_a.hop, (track_b.f0.size - 1) * track_b.hop, 0.0)
    frames = int(np.floor(duration / step + 1e-9)) + 1
    f0_a = resample_track(track_a, step, frames)
    f0_b = resample_track(track_b, step, frames)
    both = np.isfinite(f0_a) & np.isfinite(f0_b)
    diff = np.full(frames, np.nan)
    diff[both] = 1200.0 * np.log2(f0_b[both] / f0_a[both])
    magnitude = np.where(both, np.abs(np.nan_to_num(diff)), np.inf)
    agree = magnitude <= cents
    octave = np.abs(magnitude - 1200.0) <= octave_tolerance_cents
    return Agreement(step, f0_a, f0_b, diff, agree, octave, float(cents))


def take_median_semitones(track: Any) -> float | None:
    """The median voiced F0 of a take in semitones relative to 100 Hz (agreeing frames for an
    `Agreement`), or None when nothing is voiced."""
    semitones = as_track(track).semitones
    voiced = semitones[np.isfinite(semitones)]
    return float(np.median(voiced)) if voiced.size else None


def register_offset(take_median: float | None, centroid: float | None) -> float | None:
    """How far a take's median sits from its voice's centroid, in semitones (positive is higher).

    Both arguments are semitones relative to 100 Hz: `take_median_semitones` of the take, and the
    voice's centroid (for example the median of its takes' medians)."""
    if take_median is None or centroid is None:
        return None
    return float(take_median) - float(centroid)


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Half-open `[start, end)` index ranges of the True runs in a boolean array."""
    if mask.size == 0:
        return []
    padded = np.concatenate(([False], mask.astype(bool), [False]))
    edges = np.flatnonzero(np.diff(padded.astype(np.int8)))
    return [(int(edges[i]), int(edges[i + 1])) for i in range(0, edges.size, 2)]


def rolling_median(values: np.ndarray, width: int, min_coverage: float = 0.5) -> np.ndarray:
    """Centered rolling median over `width` frames, ignoring NaN; NaN where fewer than
    `min_coverage` of the window is finite or the center frame itself is NaN."""
    n = values.size
    out = np.full(n, np.nan)
    if n == 0:
        return out
    width = max(1, int(width))
    half = width // 2
    padded = np.concatenate((np.full(half, np.nan), values, np.full(width - 1 - half, np.nan)))
    windows = np.lib.stride_tricks.sliding_window_view(padded, width)
    finite = np.isfinite(windows)
    counts = finite.sum(axis=1)
    enough = (counts >= max(1, int(np.ceil(min_coverage * width)))) & np.isfinite(values)
    if enough.any():
        with np.errstate(all="ignore"):
            out[enough] = np.nanmedian(windows[enough], axis=1)
    return out


def _sliding_min(values: np.ndarray, width: int) -> np.ndarray:
    if values.size < width:
        return np.empty(0)
    return np.lib.stride_tricks.sliding_window_view(values, width).min(axis=1)


@dataclass(frozen=True)
class SustainedShift:
    take_median_st: float | None
    window_medians_st: np.ndarray  # rolling `window` median per frame, NaN when not covered
    shift_st: float | None  # signed; the largest deviation held for at least `window`
    start: float | None
    end: float | None
    detected: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "takeMedianSt": self.take_median_st,
            "shiftSt": self.shift_st,
            "start": self.start,
            "end": self.end,
            "detected": self.detected,
        }


def sustained_shifts(track: Any, window: float = 0.3, min_shift_st: float = 6.0) -> SustainedShift:
    """The largest deviation from the take median that persists at least `window` seconds.

    Each voiced frame gets the median of the `window`-second window centered on it. The sustained
    shift is the largest `x` such that, for at least `window` seconds of consecutive frames, every
    window median sits at least `x` semitones from the take median on the same side. `detected`
    when `|x| >= min_shift_st`."""
    source = as_track(track)
    semitones = source.semitones
    median = take_median_semitones(source)
    width = max(1, int(round(window / source.hop)))
    medians = rolling_median(semitones, width)
    if median is None:
        return SustainedShift(None, medians, None, None, None, False)
    deviation = medians - median
    best: tuple[float, int, int] | None = None
    for sign in (1.0, -1.0):
        signed = np.where(np.isfinite(deviation) & (sign * deviation > 0), sign * deviation, 0.0)
        held = _sliding_min(signed, width)
        if held.size == 0:
            continue
        index = int(np.argmax(held))
        value = float(held[index])
        if value > 0 and (best is None or value > abs(best[0])):
            best = (sign * value, index, index + width)
    if best is None:
        return SustainedShift(median, medians, 0.0, None, None, False)
    shift, lo, hi = best
    # Grow the reported span to the whole run that stays beyond the held level.
    beyond = np.isfinite(deviation) & (np.sign(shift) * deviation >= abs(shift) - 1e-9)
    while lo > 0 and beyond[lo - 1]:
        lo -= 1
    while hi < beyond.size and beyond[hi]:
        hi += 1
    return SustainedShift(
        take_median_st=median,
        window_medians_st=medians,
        shift_st=shift,
        start=lo * source.hop,
        end=hi * source.hop,
        detected=abs(shift) >= min_shift_st - 1e-6,
    )


@dataclass(frozen=True)
class OctaveJump:
    time: float  # boundary between the two segments
    from_st: float
    to_st: float

    @property
    def jump_st(self) -> float:
        return self.to_st - self.from_st

    def to_dict(self) -> dict[str, Any]:
        return {"time": self.time, "fromSt": self.from_st, "toSt": self.to_st, "jumpSt": self.jump_st}


def octave_jumps(
    agreement: Agreement,
    low_st: float = 10.0,
    high_st: float = 14.0,
    max_gap: float = 0.25,
    min_segment: float = 0.05,
    edge: float = 0.05,
    split_st: float = 3.0,
) -> list[OctaveJump]:
    """Transitions of `low_st`..`high_st` semitones between adjacent agreeing segments.

    Only agreeing frames count, so both trackers see both sides of every jump; a one-tracker octave
    error breaks agreement and never counts. A segment is a run of agreeing frames, split where
    consecutive frames differ by more than `split_st`. Two segments are adjacent when at most
    `max_gap` seconds separate them; each side's level is the median of its `edge` seconds next to
    the boundary. Segments shorter than `min_segment` seconds are ignored."""
    if not isinstance(agreement, Agreement):
        raise TypeError("octave_jumps needs an Agreement from agreeing_frames")
    semitones = agreement.consensus.semitones
    hop = agreement.hop
    segments: list[tuple[int, int]] = []
    for start, end in _runs(agreement.agree):
        cut = start
        for i in range(start + 1, end):
            if abs(semitones[i] - semitones[i - 1]) > split_st:
                segments.append((cut, i))
                cut = i
        segments.append((cut, end))
    min_frames = max(1, int(round(min_segment / hop)))
    edge_frames = max(1, int(round(edge / hop)))
    segments = [(s, e) for s, e in segments if e - s >= min_frames]
    jumps: list[OctaveJump] = []
    for (s1, e1), (s2, e2) in zip(segments, segments[1:]):
        if (s2 - e1) * hop > max_gap + 1e-9:
            continue
        before = float(np.median(semitones[max(s1, e1 - edge_frames):e1]))
        after = float(np.median(semitones[s2:min(e2, s2 + edge_frames)]))
        if low_st <= abs(after - before) <= high_st:
            jumps.append(OctaveJump(time=0.5 * (e1 + s2) * hop, from_st=before, to_st=after))
    return jumps


@dataclass(frozen=True)
class ToneRun:
    start: float | None
    end: float | None
    median_hz: float | None
    std_st: float | None
    flatness: float | None  # mean spectral flatness of the span (0 for a pure tone)
    hnr_db: float | None  # autocorrelation harmonic-to-noise proxy at the run's period
    detected: bool  # a run at least `min_duration` long with F0 std under `max_std_st`
    tone_like: bool  # detected, with a near-zero spectral flatness and a high HNR proxy

    @property
    def duration(self) -> float:
        return (self.end - self.start) if self.start is not None and self.end is not None else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "durationSeconds": self.duration,
            "medianHz": self.median_hz,
            "stdSt": self.std_st,
            "flatness": self.flatness,
            "hnrDb": self.hnr_db,
            "detected": self.detected,
            "toneLike": self.tone_like,
        }


def _longest_stable_run(semitones: np.ndarray, max_std: float) -> tuple[int, int]:
    """The longest `[start, end)` of consecutive voiced frames whose standard deviation stays under
    `max_std` (two-pointer scan with running sums)."""
    best = (0, 0)
    for run_start, run_end in _runs(np.isfinite(semitones)):
        values = semitones[run_start:run_end]
        total = 0.0
        squares = 0.0
        left = 0
        for right, value in enumerate(values):
            total += value
            squares += value * value
            while right > left:
                count = right - left + 1
                mean = total / count
                variance = max(squares / count - mean * mean, 0.0)
                if variance < max_std * max_std:
                    break
                total -= values[left]
                squares -= values[left] * values[left]
                left += 1
            if right + 1 - left > best[1] - best[0]:
                best = (run_start + left, run_start + right + 1)
    return best


def spectral_flatness(audio: np.ndarray, sr: int, frame: float = 0.032, hop: float = 0.016) -> float | None:
    """Mean spectral flatness (geometric over arithmetic mean of the power spectrum) of the frames
    of `audio`, skipping silent frames; None when no frame has energy."""
    samples = np.asarray(audio, dtype=float)
    size = max(16, int(round(frame * sr)))
    step = max(1, int(round(hop * sr)))
    if samples.size < size:
        samples = np.pad(samples, (0, size - samples.size))
    frames = np.lib.stride_tricks.sliding_window_view(samples, size)[::step]
    power = np.abs(np.fft.rfft(frames * np.hanning(size), axis=1)) ** 2
    energy = power.mean(axis=1)
    keep = energy > 1e-10 * max(float(energy.max()), 1e-30)
    if not keep.any():
        return None
    power = power[keep] + 1e-12
    flatness = np.exp(np.log(power).mean(axis=1)) / power.mean(axis=1)
    return float(flatness.mean())


def hnr_proxy_db(audio: np.ndarray, sr: int, f0_hz: float, frame: float = 0.04, cap_db: float = 40.0) -> float | None:
    """A harmonic-to-noise proxy: the mean normalized autocorrelation `r` at the best lag within 10%
    of the period, as `10 log10(r / (1 - r))`, capped at `cap_db`."""
    samples = np.asarray(audio, dtype=float)
    if not f0_hz or f0_hz <= 0:
        return None
    period = sr / f0_hz
    size = max(int(round(frame * sr)), int(np.ceil(2.5 * period)))
    lags = np.arange(max(1, int(np.floor(period * 0.9))), int(np.ceil(period * 1.1)) + 1)
    if samples.size < size + lags[-1]:
        return None
    correlations = []
    for start in range(0, samples.size - size - int(lags[-1]) + 1, size):
        x = samples[start:start + size]
        ex = float(np.dot(x, x))
        if ex <= 1e-12:
            continue
        r = np.full(lags.size, -1.0)
        for i, lag in enumerate(lags):
            y = samples[start + lag:start + lag + size]
            ey = float(np.dot(y, y))
            if ey > 1e-12:
                r[i] = float(np.dot(x, y)) / np.sqrt(ex * ey)
        i = int(np.argmax(r))
        best = float(r[i])
        if 0 < i < r.size - 1:
            # The period is rarely a whole number of samples: refine the peak parabolically.
            curvature = r[i - 1] - 2.0 * r[i] + r[i + 1]
            if curvature < 0:
                best = float(r[i] - (r[i - 1] - r[i + 1]) ** 2 / (8.0 * curvature))
        correlations.append(min(best, 1.0))
    if not correlations:
        return None
    r = float(np.clip(np.mean(correlations), 1e-6, 1.0))
    if r >= 1.0 - 10 ** (-cap_db / 10):
        return cap_db
    return float(min(cap_db, 10.0 * np.log10(r / (1.0 - r))))


def tone_runs(
    track: Any,
    audio: np.ndarray | None = None,
    sr: int | None = None,
    max_std_st: float = 0.3,
    min_duration: float = 0.4,
    max_flatness: float = 0.005,
    min_hnr_db: float = 25.0,
) -> ToneRun:
    """The longest run whose F0 standard deviation stays under `max_std_st` semitones.

    `detected` when the run lasts at least `min_duration` seconds: a voice collapsing into a
    sustained tone (the ~730 Hz defect) holds a pitch far more steadily than speech. With the take's
    audio, the span's spectral flatness and periodicity are measured too; `tone_like` adds a near-zero
    flatness and a high harmonic-to-noise proxy. The flatness and HNR defaults are provisional until
    the thresholds are fitted on labels."""
    source = as_track(track)
    lo, hi = _longest_stable_run(source.semitones, max_std_st)
    if hi <= lo:
        return ToneRun(None, None, None, None, None, None, False, False)
    span = source.semitones[lo:hi]
    start, end = lo * source.hop, hi * source.hop
    median_hz = semitones_to_hz(float(np.median(span)))
    std = float(np.std(span))
    detected = (end - start) >= min_duration - 1e-9
    flatness = hnr = None
    if audio is not None and sr:
        samples = np.asarray(audio, dtype=float)
        if samples.ndim > 1:
            samples = samples.mean(axis=1)
        clip = samples[int(start * sr):int(end * sr)]
        if clip.size:
            flatness = spectral_flatness(clip, sr)
            hnr = hnr_proxy_db(clip, sr, median_hz)
    tone_like = bool(
        detected
        and flatness is not None
        and flatness <= max_flatness
        and hnr is not None
        and hnr >= min_hnr_db
    )
    return ToneRun(start, end, median_hz, std, flatness, hnr, bool(detected), tone_like)


def summarize(fcpe: Any, swiftf0: Any, audio: np.ndarray | None = None, sr: int | None = None) -> dict[str, Any]:
    """Every pitch feature of one take from its two tracks (the FCPE and SwiftF0 runner outputs),
    JSON-ready: the agreement, the take median, the largest sustained shift, the octave jumps and the
    longest tone run, all on the agreeing frames. The register offset needs the voice's other takes."""
    agreement = agreeing_frames(fcpe, swiftf0)
    return {
        "agreement": agreement.summary(),
        "takeMedianSt": take_median_semitones(agreement),
        "sustainedShift": sustained_shifts(agreement).to_dict(),
        "octaveJumps": [jump.to_dict() for jump in octave_jumps(agreement)],
        "toneRun": tone_runs(agreement, audio, sr).to_dict(),
    }
