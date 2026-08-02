#!/usr/bin/env python3
"""Bounded, reference-free prosody analysis for Vocello PCM16 output.

Algorithm v3 deliberately uses two bounded passes over the WAV.  It never
loads the complete clip or constructs an ``N x frameWidth`` matrix:

* pass 1 validates PCM16, measures signal continuity, and builds the pitch
  anchor needed for deterministic octave rejection;
* pass 2 computes pitch, cadence, pause, energy, voice-quality, spectral, and
  optional declared-boundary summaries with fixed histograms and small rolling
  windows.

The established v1/v2 output keys remain available to existing gates.  Pitch and
level percentiles come from deterministic fixed-width histograms, so values
near a bin boundary may differ slightly from v1; ``analyzerAlgorithmVersion``
makes that methodological change explicit.  No ML model or raw audio is kept.

v3 adds the *valence* half of delivery.  v1/v2 measured only arousal-bearing
dimensions (pitch height/variation, rate, pauses, energy dynamics), which cannot
separate emotions that share arousal but oppose in valence -- happy versus angry
being the canonical pair -- and cannot describe phonation at all, so ``whisper``
had no breathiness measure and ``fearful`` had no tremor measure.  v3 adds:

* ``voice_*`` -- harmonics-to-noise ratio (from the autocorrelation pass 2
  already computes), frame-rate pitch/amplitude perturbation, and cepstral peak
  prominence;
* ``spectral_*`` -- the eGeMAPS-defined balance descriptors (alpha ratio,
  Hammarberg index, band slopes) plus centroid, flux, and high-frequency share.

Feature definitions follow Eyben et al. 2016 (GeMAPS/eGeMAPS) and Boersma 1993
(HNR).  They are reimplemented here in NumPy rather than taken from openSMILE,
whose licence forbids commercial use of the software *and* of features extracted
with it.  Every addition is computed from the frame the analyzer already holds,
so the bounded-working-set and determinism contracts are unchanged.


Usage:
  scripts/analyze_prosody.py <wav> [<wav> ...] [--json]
  scripts/analyze_prosody.py <wav> --boundary-seconds 1.25,2.75 --json
  python3 -c "from analyze_prosody import analyze; print(analyze('clip.wav'))"
"""

from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
import json
import math
import os
import sys
import wave
from typing import Callable, Iterable, Iterator, Sequence

import numpy as np


ANALYZER_ALGORITHM_VERSION = 3
ANALYSIS_PASS_COUNT = 2
READ_BLOCK_FRAMES = 16_384

F0_MIN, F0_MAX = 70.0, 400.0
FRAME_MS, HOP_MS = 40.0, 10.0
VOICING_AC = 0.30
SYLLABLE_SMOOTH_MS = 50.0
SYLLABLE_THR = 0.15
PAUSE_RMS_DB = -50.0
PAUSE_MIN_MS = 60.0
RATE_WINDOW_MS = 2000.0
EDGE_SKIP_MS = 100.0

F0_HISTOGRAM_STEP_HZ = 0.25
RMS_HISTOGRAM_MIN_DB = -240.0
RMS_HISTOGRAM_MAX_DB = 0.0
RMS_HISTOGRAM_STEP_DB = 0.05
RATE_HISTOGRAM_MAX_HZ = 32.0
RATE_HISTOGRAM_STEP_HZ = 0.05
CLICK_DELTA_NORMALIZED = 0.45

# --- v3 voice-quality / spectral constants -------------------------------
# Band edges follow eGeMAPS (Eyben et al. 2016).  Frequencies in Hz.
ALPHA_RATIO_LOW_BAND = (50.0, 1000.0)
ALPHA_RATIO_HIGH_BAND = (1000.0, 5000.0)
HAMMARBERG_LOW_BAND = (0.0, 2000.0)
HAMMARBERG_HIGH_BAND = (2000.0, 5000.0)
SPECTRAL_SLOPE_BANDS = ((0.0, 500.0), (500.0, 1500.0))
HF_ENERGY_EDGE_HZ = 4000.0
# Cepstral peak search window, expressed as the F0 band it corresponds to.
CPP_QUEFRENCY_MIN_HZ, CPP_QUEFRENCY_MAX_HZ = F0_MIN, F0_MAX
# Frames quieter than this contribute no spectral balance measurement: the
# spectrum of near-silence is noise-shaped and would dominate the averages.
SPECTRAL_FLOOR_DB = PAUSE_RMS_DB
HNR_HISTOGRAM_MIN_DB = -20.0
HNR_HISTOGRAM_MAX_DB = 60.0
HNR_HISTOGRAM_STEP_DB = 0.1


@dataclass(frozen=True)
class WavMetadata:
    sample_rate: int
    frame_count: int
    channel_count: int
    sample_width: int

    @property
    def duration_seconds(self) -> float:
        return self.frame_count / self.sample_rate if self.sample_rate > 0 else 0.0


class RunningMoments:
    """Constant-space mean/variance accumulator."""

    __slots__ = ("count", "mean", "m2")

    def __init__(self) -> None:
        self.count = 0
        self.mean = 0.0
        self.m2 = 0.0

    def add(self, value: float) -> None:
        self.count += 1
        delta = value - self.mean
        self.mean += delta / self.count
        self.m2 += delta * (value - self.mean)

    @property
    def standard_deviation(self) -> float:
        return math.sqrt(max(0.0, self.m2 / self.count)) if self.count else 0.0


class FixedHistogram:
    """Deterministic bounded distribution with fixed-width bins."""

    __slots__ = ("minimum", "maximum", "step", "counts", "total")

    def __init__(self, minimum: float, maximum: float, step: float) -> None:
        if not (maximum > minimum and step > 0):
            raise ValueError("invalid histogram bounds")
        self.minimum = minimum
        self.maximum = maximum
        self.step = step
        bin_count = int(math.ceil((maximum - minimum) / step)) + 1
        self.counts = np.zeros(bin_count, dtype=np.uint64)
        self.total = 0

    def add(self, value: float) -> None:
        if not math.isfinite(value):
            return
        clamped = min(self.maximum, max(self.minimum, value))
        index = int((clamped - self.minimum) / self.step)
        index = min(len(self.counts) - 1, max(0, index))
        self.counts[index] += 1
        self.total += 1

    def quantile(self, fraction: float) -> float:
        if self.total == 0:
            return 0.0
        position = min(1.0, max(0.0, fraction)) * (self.total - 1)
        lower_rank = int(math.floor(position))
        upper_rank = int(math.ceil(position))

        def value_at(rank: int) -> float:
            cumulative = 0
            for index, count in enumerate(self.counts):
                cumulative += int(count)
                if cumulative > rank:
                    return min(self.maximum, self.minimum + (index + 0.5) * self.step)
            return self.maximum

        lower = value_at(lower_rank)
        upper = value_at(upper_rank)
        return lower + (upper - lower) * (position - lower_rank)

    @property
    def nbytes(self) -> int:
        return int(self.counts.nbytes)


class ManagedMemoryEstimate:
    """Tracks deterministic analyzer-owned numeric-buffer high water."""

    __slots__ = ("histogram_bytes", "peak_histogram_bytes", "peak_transient_bytes")

    def __init__(self) -> None:
        self.histogram_bytes = 0
        self.peak_histogram_bytes = 0
        self.peak_transient_bytes = 0

    def own_histogram(self, histogram: FixedHistogram) -> None:
        self.histogram_bytes += histogram.nbytes
        self.peak_histogram_bytes = max(self.peak_histogram_bytes, self.histogram_bytes)

    def release_histogram(self, histogram: FixedHistogram) -> None:
        self.histogram_bytes = max(0, self.histogram_bytes - histogram.nbytes)

    def observe(self, *arrays: np.ndarray, raw_bytes: int = 0) -> None:
        numeric_bytes = sum(int(array.nbytes) for array in arrays)
        self.peak_transient_bytes = max(self.peak_transient_bytes, numeric_bytes + raw_bytes)

    @property
    def measured_peak_managed_buffer_bytes(self) -> int:
        return self.peak_histogram_bytes + self.peak_transient_bytes

    def estimated_peak_working_set_bytes(self, frame_samples: int, channel_count: int) -> int:
        # In addition to measured owned buffers, one F0 call temporarily owns a
        # demeaned frame, Hann window, windowed frame, and autocorrelation.  A
        # small fixed allowance covers deques, scalars, wave state, and Python
        # container overhead.  This estimate excludes NumPy/Python runtimes.
        f0_temporary_bytes = frame_samples * 8 * 5
        # v3 spectral block: one rfft per frame owns a complex spectrum plus
        # magnitude, power, log-magnitude, normalized and previous-normalized
        # spectra and the cepstrum -- all (frame_samples/2 + 1) wide, with the
        # complex spectrum counting double.  Retained frequency and window
        # vectors are frame-width.  Bounded by frame size, not clip length.
        spectrum_bins = frame_samples // 2 + 1
        spectral_temporary_bytes = spectrum_bins * 8 * 9 + frame_samples * 8 * 2
        theoretical_block_bytes = (
            READ_BLOCK_FRAMES * channel_count * 2  # raw PCM bytes
            + READ_BLOCK_FRAMES * channel_count * 2  # Int16 view accounting
            + READ_BLOCK_FRAMES * 8  # mono Float64 block
            + (READ_BLOCK_FRAMES + frame_samples) * 8  # rolling frame buffer
        )
        fixed_python_allowance = 64 * 1024
        return (
            self.peak_histogram_bytes
            + theoretical_block_bytes
            + f0_temporary_bytes
            + spectral_temporary_bytes
            + fixed_python_allowance
        )


class CenteredSmoother:
    """Streaming centered moving average with edge-value padding."""

    __slots__ = ("width", "pad", "values", "first", "last", "next_index")

    def __init__(self, width: int) -> None:
        if width < 1 or width % 2 == 0:
            raise ValueError("smoother width must be a positive odd number")
        self.width = width
        self.pad = width // 2
        self.values: deque[tuple[int, float]] = deque(maxlen=width)
        self.first: float | None = None
        self.last: float | None = None
        self.next_index = 0

    def _value(self, index: int, final_index: int | None = None) -> float:
        if index < 0:
            assert self.first is not None
            return self.first
        if final_index is not None and index > final_index:
            assert self.last is not None
            return self.last
        for item_index, value in self.values:
            if item_index == index:
                return value
        raise RuntimeError(f"smoother lost bounded sample {index}")

    def push(self, value: float) -> tuple[int, float] | None:
        index = self.next_index
        self.next_index += 1
        if self.first is None:
            self.first = value
        self.last = value
        self.values.append((index, value))
        if index < self.pad:
            return None
        center = index - self.pad
        total = sum(self._value(position) for position in range(center - self.pad, center + self.pad + 1))
        return center, total / self.width

    def finish(self) -> Iterator[tuple[int, float]]:
        if self.last is None:
            return
        final_index = self.next_index - 1
        for center in range(max(0, self.next_index - self.pad), self.next_index):
            total = sum(
                self._value(position, final_index=final_index)
                for position in range(center - self.pad, center + self.pad + 1)
            )
            yield center, total / self.width


class PeakAndRateAccumulator:
    """Counts envelope peaks and overlapping local-rate windows in O(1) space."""

    __slots__ = (
        "threshold", "history", "peak_count", "window_frames", "stride",
        "analysis_frame_count", "active_windows", "rate_histogram", "rate_moments",
    )

    def __init__(
        self,
        threshold: float,
        window_frames: int,
        analysis_frame_count: int,
        rate_histogram: FixedHistogram,
    ) -> None:
        self.threshold = threshold
        self.history: deque[tuple[int, float]] = deque(maxlen=3)
        self.peak_count = 0
        self.window_frames = window_frames
        self.stride = max(1, window_frames // 2)
        self.analysis_frame_count = analysis_frame_count
        self.active_windows: dict[int, int] = {}
        if 0 < analysis_frame_count - window_frames:
            self.active_windows[0] = 0
        self.rate_histogram = rate_histogram
        self.rate_moments = RunningMoments()

    def _observe_peak_index(self, frame_index: int, is_peak: bool) -> None:
        if frame_index % self.stride == 0 and frame_index < self.analysis_frame_count - self.window_frames:
            self.active_windows[frame_index] = 0
        if is_peak:
            self.peak_count += 1
            for start in tuple(self.active_windows):
                if start <= frame_index < start + self.window_frames:
                    self.active_windows[start] += 1
        finished = [
            start for start in self.active_windows
            if frame_index >= start + self.window_frames - 1
        ]
        for start in finished:
            duration = self.window_frames * HOP_MS / 1000.0
            rate = self.active_windows.pop(start) / duration if duration > 0 else 0.0
            self.rate_moments.add(rate)
            self.rate_histogram.add(rate)

    def push(self, index: int, value: float) -> None:
        self.history.append((index, value))
        if len(self.history) < 3:
            return
        left, middle, right = self.history
        middle_index, middle_value = middle
        is_peak = (
            middle_value > left[1]
            and middle_value >= right[1]
            and middle_value > self.threshold
        )
        self._observe_peak_index(middle_index, is_peak)

    def finish(self) -> None:
        # The legacy detector excludes first and last frames.  Advance any
        # remaining valid non-edge frame so its local-rate window can close.
        if self.analysis_frame_count > 1:
            final_non_edge = self.analysis_frame_count - 2
            for index in range(
                self.history[-2][0] + 1 if len(self.history) >= 2 else 0,
                final_non_edge + 1,
            ):
                self._observe_peak_index(index, False)
        for start in sorted(self.active_windows):
            if start + self.window_frames <= self.analysis_frame_count:
                duration = self.window_frames * HOP_MS / 1000.0
                rate = self.active_windows[start] / duration if duration > 0 else 0.0
                self.rate_moments.add(rate)
                self.rate_histogram.add(rate)
        self.active_windows.clear()


class PauseAccumulator:
    __slots__ = (
        "minimum_frames", "edge_frames", "total_frames", "in_pause", "start",
        "count", "total_seconds", "maximum_seconds",
    )

    def __init__(self, minimum_frames: int, edge_frames: int, total_frames: int) -> None:
        self.minimum_frames = minimum_frames
        self.edge_frames = edge_frames
        self.total_frames = total_frames
        self.in_pause = False
        self.start = 0
        self.count = 0
        self.total_seconds = 0.0
        self.maximum_seconds = 0.0

    def _record(self, start: int, end: int, require_trailing_edge: bool) -> None:
        length = end - start
        if length < self.minimum_frames or start < self.edge_frames:
            return
        if require_trailing_edge and end > self.total_frames - self.edge_frames:
            return
        seconds = length * HOP_MS / 1000.0
        self.count += 1
        self.total_seconds += seconds
        self.maximum_seconds = max(self.maximum_seconds, seconds)

    def add(self, index: int, is_silent: bool) -> None:
        if is_silent and not self.in_pause:
            self.in_pause = True
            self.start = index
        elif not is_silent and self.in_pause:
            self.in_pause = False
            self._record(self.start, index, require_trailing_edge=True)

    def finish(self) -> None:
        if self.in_pause:
            # Preserve v1's established treatment of a terminal run.  It is
            # included once it starts beyond the leading edge.
            self._record(self.start, self.total_frames, require_trailing_edge=False)
            self.in_pause = False


class BoundaryAccumulator:
    """Aggregates frame-level continuity around declared sample boundaries."""

    __slots__ = (
        "boundary_frame_indices", "boundary_index", "previous", "observed", "max_rms_jump_db",
        "max_pitch_jump_semitones", "silence_overlap_count",
    )

    def __init__(self, sample_offsets: Sequence[int], frame_samples: int, hop_samples: int) -> None:
        self.boundary_frame_indices = [
            max(1, int(round((offset - frame_samples / 2) / hop_samples)))
            for offset in sample_offsets
        ]
        self.boundary_index = 0
        self.previous: tuple[float, float, bool] | None = None
        self.observed = 0
        self.max_rms_jump_db = 0.0
        self.max_pitch_jump_semitones = 0.0
        self.silence_overlap_count = 0

    def add(self, frame_index: int, rms_db: float, f0: float, voiced: bool) -> None:
        current = (rms_db, f0, voiced)
        while (
            self.boundary_index < len(self.boundary_frame_indices)
            and self.boundary_frame_indices[self.boundary_index] <= frame_index
        ):
            if self.previous is not None:
                previous_rms, previous_f0, previous_voiced = self.previous
                self.observed += 1
                self.max_rms_jump_db = max(self.max_rms_jump_db, abs(rms_db - previous_rms))
                if previous_voiced and voiced and previous_f0 > 0 and f0 > 0:
                    semitones = abs(12.0 * math.log2(f0 / previous_f0))
                    self.max_pitch_jump_semitones = max(self.max_pitch_jump_semitones, semitones)
                if rms_db < PAUSE_RMS_DB or previous_rms < PAUSE_RMS_DB:
                    self.silence_overlap_count += 1
            self.boundary_index += 1
        self.previous = current


def _metadata(path: str) -> WavMetadata:
    with wave.open(path, "rb") as reader:
        metadata = WavMetadata(
            sample_rate=reader.getframerate(),
            frame_count=reader.getnframes(),
            channel_count=reader.getnchannels(),
            sample_width=reader.getsampwidth(),
        )
    if metadata.sample_width != 2:
        raise ValueError(f"expected 16-bit PCM, got sampwidth={metadata.sample_width}")
    if metadata.sample_rate <= 0 or metadata.channel_count <= 0:
        raise ValueError("invalid WAV sample rate or channel count")
    return metadata


def _pcm_blocks(
    path: str,
    metadata: WavMetadata,
    memory: ManagedMemoryEstimate,
) -> Iterator[np.ndarray]:
    with wave.open(path, "rb") as reader:
        while True:
            raw = reader.readframes(READ_BLOCK_FRAMES)
            if not raw:
                break
            pcm = np.frombuffer(raw, dtype="<i2")
            if len(pcm) % metadata.channel_count:
                raise ValueError("truncated interleaved PCM frame")
            if metadata.channel_count > 1:
                mono = pcm.reshape(-1, metadata.channel_count).astype(np.float64).mean(axis=1)
            else:
                mono = pcm.astype(np.float64)
            # ``pcm`` is a zero-copy view over ``raw``; count their shared
            # backing bytes once, plus the owned mono Float64 conversion.
            memory.observe(mono, raw_bytes=len(raw))
            yield mono


def _analysis_frames(
    path: str,
    metadata: WavMetadata,
    memory: ManagedMemoryEstimate,
    block_observer: Callable[[np.ndarray, int], None] | None = None,
) -> Iterator[tuple[int, np.ndarray]]:
    frame_samples = int(metadata.sample_rate * FRAME_MS / 1000.0)
    hop_samples = int(metadata.sample_rate * HOP_MS / 1000.0)
    if frame_samples <= 0 or hop_samples <= 0:
        raise ValueError("sample rate is too low for the analysis frame contract")
    retained = np.empty(0, dtype=np.float64)
    frame_index = 0
    observed_samples = 0
    for block in _pcm_blocks(path, metadata, memory):
        if block_observer is not None:
            block_observer(block, observed_samples)
        observed_samples += len(block)
        if len(retained):
            combined = np.concatenate((retained, block))
            memory.observe(retained, block, combined)
        else:
            combined = block
            memory.observe(block)
        cursor = 0
        while cursor + frame_samples <= len(combined):
            frame = combined[cursor:cursor + frame_samples]
            # ``frame`` is a view into ``combined`` and owns no second payload.
            memory.observe(combined)
            yield frame_index, frame
            frame_index += 1
            cursor += hop_samples
        retained = combined[cursor:].copy()
        memory.observe(combined, retained)


def f0_autocorr(frame: np.ndarray, sample_rate: int) -> tuple[float, float]:
    """Normalized-autocorrelation F0 for one frame."""
    centered = frame - frame.mean()
    windowed = centered * np.hanning(len(centered))
    energy = np.dot(windowed, windowed)
    if energy < 1e-6:
        return 0.0, 0.0
    autocorrelation = np.correlate(windowed, windowed, mode="full")[len(windowed) - 1:]
    ac0 = autocorrelation[0]
    if ac0 <= 0:
        return 0.0, 0.0
    lag_min = max(1, int(sample_rate / F0_MAX))
    lag_max = min(len(autocorrelation) - 1, int(sample_rate / F0_MIN))
    if lag_max <= lag_min:
        return 0.0, 0.0
    segment = autocorrelation[lag_min:lag_max + 1]
    peak_index = int(np.argmax(segment))
    peak = float(segment[peak_index] / ac0)
    lag = float(lag_min + peak_index)
    if 0 < peak_index < len(segment) - 1:
        before, at, after = segment[peak_index - 1], segment[peak_index], segment[peak_index + 1]
        denominator = before - 2 * at + after
        if denominator != 0:
            lag += float(0.5 * (before - after) / denominator)
    return (sample_rate / lag if lag > 0 else 0.0), peak


def _rms_db(frame: np.ndarray) -> tuple[float, float]:
    rms = math.sqrt(float(np.dot(frame, frame)) / len(frame)) if len(frame) else 0.0
    rms_db = 20.0 * math.log10(max(rms, 1e-9) / 32768.0)
    return rms, rms_db


def hnr_db(autocorrelation_peak: float) -> float:
    """Harmonics-to-noise ratio in dB from a normalized autocorrelation peak.

    Boersma (1993): with ``r`` the normalized autocorrelation at the pitch lag,
    the harmonic share of the frame's energy is ``r`` and the noise share is
    ``1 - r``, so ``HNR = 10*log10(r / (1 - r))``.  The peak is already computed
    by ``f0_autocorr`` for pitch, so this costs nothing beyond the arithmetic.
    Clamped to keep the logarithm finite at the degenerate ends.
    """
    ratio = min(max(float(autocorrelation_peak), 1e-6), 1.0 - 1e-6)
    return 10.0 * math.log10(ratio / (1.0 - ratio))


def _band_power(power: np.ndarray, frequencies: np.ndarray, low: float, high: float) -> float:
    mask = (frequencies >= low) & (frequencies < high)
    return float(power[mask].sum()) if mask.any() else 0.0


def _band_peak_db(power: np.ndarray, frequencies: np.ndarray, low: float, high: float) -> float:
    mask = (frequencies >= low) & (frequencies < high)
    if not mask.any():
        return -240.0
    return 10.0 * math.log10(max(float(power[mask].max()), 1e-30))


def _band_slope_db_per_khz(
    power: np.ndarray, frequencies: np.ndarray, low: float, high: float
) -> float:
    """Least-squares slope of the dB spectrum across one band, in dB per kHz."""
    mask = (frequencies >= low) & (frequencies < high)
    if mask.sum() < 2:
        return 0.0
    band_frequencies = frequencies[mask] / 1000.0
    band_db = 10.0 * np.log10(np.maximum(power[mask], 1e-30))
    centered_frequency = band_frequencies - band_frequencies.mean()
    denominator = float(np.dot(centered_frequency, centered_frequency))
    if denominator <= 0.0:
        return 0.0
    return float(np.dot(centered_frequency, band_db - band_db.mean()) / denominator)


def cepstral_peak_prominence_db(
    log_magnitude: np.ndarray, sample_rate: int, minimum_hz: float, maximum_hz: float
) -> float:
    """Cepstral peak prominence (Hillenbrand): peak height above the cepstral trend.

    The real cepstrum of the log magnitude spectrum has a peak at the pitch
    quefrency for periodic voices; how far that peak stands above the regression
    line through the cepstrum is the single strongest voice-quality/dysphonia
    predictor in the literature.  Breathy and whispered phonation flatten it.
    No temporal smoothing is applied here -- averaging over frames happens in
    the accumulator -- so this is CPP rather than CPPS.
    """
    cepstrum = np.abs(np.fft.irfft(log_magnitude))
    minimum_quefrency = max(1, int(sample_rate / max(maximum_hz, 1e-9)))
    maximum_quefrency = min(len(cepstrum) - 1, int(sample_rate / max(minimum_hz, 1e-9)))
    if maximum_quefrency <= minimum_quefrency:
        return 0.0
    search = cepstrum[minimum_quefrency:maximum_quefrency + 1]
    peak_offset = int(np.argmax(search))
    peak_quefrency = minimum_quefrency + peak_offset
    peak_db = 20.0 * math.log10(max(float(search[peak_offset]), 1e-30))

    # Regression baseline over the same quefrency window, in dB.
    quefrencies = np.arange(minimum_quefrency, maximum_quefrency + 1, dtype=np.float64)
    trend_db = 20.0 * np.log10(np.maximum(search, 1e-30))
    centered_quefrency = quefrencies - quefrencies.mean()
    denominator = float(np.dot(centered_quefrency, centered_quefrency))
    if denominator <= 0.0:
        return 0.0
    slope = float(np.dot(centered_quefrency, trend_db - trend_db.mean()) / denominator)
    intercept = float(trend_db.mean() - slope * quefrencies.mean())
    return peak_db - (slope * peak_quefrency + intercept)


class SpectralAccumulator:
    """Constant-space accumulator for the v3 voice-quality / spectral block.

    One ``rfft`` per analysis frame.  Only the previous frame's normalized
    magnitude spectrum is retained (for flux), so the working set stays bounded
    regardless of clip length.
    """

    __slots__ = (
        "sample_rate", "frequencies", "window", "previous_magnitude",
        "alpha_ratio", "hammarberg", "slope_low", "slope_high",
        "centroid", "flux", "hf_ratio", "cpp", "hnr", "hnr_histogram",
        "jitter", "shimmer", "_previous_period", "_previous_amplitude",
    )

    def __init__(self, sample_rate: int, frame_samples: int, hnr_histogram: FixedHistogram) -> None:
        self.sample_rate = sample_rate
        self.frequencies = np.fft.rfftfreq(frame_samples, d=1.0 / sample_rate)
        self.window = np.hanning(frame_samples)
        self.previous_magnitude: np.ndarray | None = None
        self.alpha_ratio = RunningMoments()
        self.hammarberg = RunningMoments()
        self.slope_low = RunningMoments()
        self.slope_high = RunningMoments()
        self.centroid = RunningMoments()
        self.flux = RunningMoments()
        self.hf_ratio = RunningMoments()
        self.cpp = RunningMoments()
        self.hnr = RunningMoments()
        self.hnr_histogram = hnr_histogram
        self.jitter = RunningMoments()
        self.shimmer = RunningMoments()
        self._previous_period: float | None = None
        self._previous_amplitude: float | None = None

    @property
    def nbytes(self) -> int:
        spectrum_bytes = self.frequencies.nbytes + self.window.nbytes
        if self.previous_magnitude is not None:
            spectrum_bytes += self.previous_magnitude.nbytes
        return spectrum_bytes

    def add_spectral(self, frame: np.ndarray, memory: "ManagedMemoryEstimate") -> None:
        """Spectral balance for one audible frame (voiced or not).

        Consonant energy lives in unvoiced frames, so the spectral block is
        measured on every audible frame rather than only the voiced ones.
        """
        spectrum = np.fft.rfft(frame * self.window)
        magnitude = np.abs(spectrum)
        power = magnitude * magnitude
        memory.observe(spectrum, magnitude, power, self.frequencies, self.window)

        total_power = float(power.sum())
        if total_power <= 0.0:
            return

        low = _band_power(power, self.frequencies, *ALPHA_RATIO_LOW_BAND)
        high = _band_power(power, self.frequencies, *ALPHA_RATIO_HIGH_BAND)
        self.alpha_ratio.add(10.0 * math.log10(max(low, 1e-30) / max(high, 1e-30)))

        self.hammarberg.add(
            _band_peak_db(power, self.frequencies, *HAMMARBERG_LOW_BAND)
            - _band_peak_db(power, self.frequencies, *HAMMARBERG_HIGH_BAND)
        )

        (low_band, high_band) = SPECTRAL_SLOPE_BANDS
        self.slope_low.add(_band_slope_db_per_khz(power, self.frequencies, *low_band))
        self.slope_high.add(_band_slope_db_per_khz(power, self.frequencies, *high_band))

        self.centroid.add(float(np.dot(self.frequencies, power) / total_power))
        self.hf_ratio.add(
            _band_power(power, self.frequencies, HF_ENERGY_EDGE_HZ, float(self.sample_rate))
            / total_power
        )

        normalized = magnitude / math.sqrt(total_power)
        if self.previous_magnitude is not None:
            difference = normalized - self.previous_magnitude
            self.flux.add(float(np.sqrt(np.dot(difference, difference))))
        self.previous_magnitude = normalized
        memory.observe(normalized)

        log_magnitude = np.log(np.maximum(magnitude, 1e-30))
        memory.observe(log_magnitude)
        self.cpp.add(
            cepstral_peak_prominence_db(
                log_magnitude, self.sample_rate, CPP_QUEFRENCY_MIN_HZ, CPP_QUEFRENCY_MAX_HZ
            )
        )

    def add_voiced(self, f0: float, autocorrelation_peak: float, rms: float) -> None:
        """Voice-quality for one accepted-voiced frame."""
        value = hnr_db(autocorrelation_peak)
        self.hnr.add(value)
        self.hnr_histogram.add(value)

        # Frame-rate perturbation.  This is a 10 ms-hop pitch/amplitude
        # instability measure, NOT cycle-level jitter/shimmer: it indexes tremor
        # and unsteadiness at the frame rate, which is what a "shaky" delivery
        # instruction produces.  Named accordingly so it is not mistaken for the
        # Praat cycle-level measures.
        period = 1.0 / f0 if f0 > 0 else 0.0
        if period > 0.0:
            if self._previous_period is not None and self._previous_period > 0.0:
                mean_period = 0.5 * (period + self._previous_period)
                if mean_period > 0.0:
                    self.jitter.add(100.0 * abs(period - self._previous_period) / mean_period)
            self._previous_period = period
        if rms > 0.0:
            if self._previous_amplitude is not None and self._previous_amplitude > 0.0:
                self.shimmer.add(abs(20.0 * math.log10(rms / self._previous_amplitude)))
            self._previous_amplitude = rms

    def break_voiced_run(self) -> None:
        """Unvoiced/silent frame: perturbation must not span the discontinuity."""
        self._previous_period = None
        self._previous_amplitude = None


def _sample_offsets(boundary_seconds: Iterable[float], metadata: WavMetadata) -> list[int]:
    offsets: list[int] = []
    previous = -1
    for value in boundary_seconds:
        seconds = float(value)
        if not math.isfinite(seconds) or seconds <= 0 or seconds >= metadata.duration_seconds:
            raise ValueError(f"boundary seconds must be finite and inside the clip: {value!r}")
        offset = int(round(seconds * metadata.sample_rate))
        if offset <= previous:
            raise ValueError("boundary seconds must be strictly increasing")
        offsets.append(offset)
        previous = offset
    return offsets


def _signal_and_anchor_pass(
    path: str,
    metadata: WavMetadata,
    boundary_offsets: Sequence[int],
    memory: ManagedMemoryEstimate,
) -> dict[str, object]:
    f0_histogram = FixedHistogram(
        F0_MIN - F0_HISTOGRAM_STEP_HZ / 2,
        F0_MAX + F0_HISTOGRAM_STEP_HZ / 2,
        F0_HISTOGRAM_STEP_HZ,
    )
    memory.own_histogram(f0_histogram)
    analysis_frame_count = 0
    voiced_frame_count = 0
    maximum_rms = 0.0
    sample_count = 0
    clipping_count = 0
    click_count = 0
    peak_normalized = 0.0
    maximum_sample_jump = 0.0
    previous_sample: float | None = None
    requested_boundary_cursor = 0
    boundary_sample_jump_max = 0.0
    boundary_sample_observed = 0

    def observe_signal_block(block: np.ndarray, block_start: int) -> None:
        nonlocal sample_count, clipping_count, click_count, peak_normalized
        nonlocal maximum_sample_jump, previous_sample, requested_boundary_cursor
        nonlocal boundary_sample_jump_max, boundary_sample_observed
        normalized = block / 32768.0
        memory.observe(block, normalized)
        if len(normalized):
            peak_normalized = max(peak_normalized, float(np.max(np.abs(normalized))))
            clipping_count += int(np.count_nonzero(np.abs(block) >= 32767.0))
            if previous_sample is not None:
                first_jump = abs(float(normalized[0]) - previous_sample)
                maximum_sample_jump = max(maximum_sample_jump, first_jump)
                if first_jump >= CLICK_DELTA_NORMALIZED:
                    click_count += 1
            if len(normalized) > 1:
                jumps = np.abs(np.diff(normalized))
                maximum_sample_jump = max(maximum_sample_jump, float(np.max(jumps)))
                click_count += int(np.count_nonzero(jumps >= CLICK_DELTA_NORMALIZED))
            block_end = block_start + len(normalized)
            while (
                requested_boundary_cursor < len(boundary_offsets)
                and boundary_offsets[requested_boundary_cursor] < block_end
            ):
                offset = boundary_offsets[requested_boundary_cursor]
                local = offset - block_start
                if local == 0:
                    before = previous_sample
                    after = float(normalized[0])
                else:
                    before = float(normalized[local - 1])
                    after = float(normalized[local])
                if before is not None:
                    boundary_sample_observed += 1
                    boundary_sample_jump_max = max(boundary_sample_jump_max, abs(after - before))
                requested_boundary_cursor += 1
            previous_sample = float(normalized[-1])
        sample_count += len(normalized)

    for _index, frame in _analysis_frames(
        path,
        metadata,
        memory,
        block_observer=observe_signal_block,
    ):
        analysis_frame_count += 1
        rms, _ = _rms_db(frame)
        maximum_rms = max(maximum_rms, rms)
        f0, autocorrelation_peak = f0_autocorr(frame, metadata.sample_rate)
        if autocorrelation_peak >= VOICING_AC and f0 > 0:
            voiced_frame_count += 1
            f0_histogram.add(f0)

    result = {
        "analysis_frame_count": analysis_frame_count,
        "voiced_frame_count": voiced_frame_count,
        "maximum_rms": maximum_rms,
        "anchor_median_hz": f0_histogram.quantile(0.5),
        "sample_count": sample_count,
        "clipping_count": clipping_count,
        "click_count": click_count,
        "peak_normalized": peak_normalized,
        "maximum_sample_jump": maximum_sample_jump,
        "boundary_sample_observed": boundary_sample_observed,
        "boundary_sample_jump_max": boundary_sample_jump_max,
    }
    memory.release_histogram(f0_histogram)
    return result


def _analysis_pass(
    path: str,
    metadata: WavMetadata,
    anchor: dict[str, object],
    boundary_offsets: Sequence[int],
    memory: ManagedMemoryEstimate,
) -> dict[str, object]:
    f0_histogram = FixedHistogram(
        F0_MIN - F0_HISTOGRAM_STEP_HZ / 2,
        F0_MAX + F0_HISTOGRAM_STEP_HZ / 2,
        F0_HISTOGRAM_STEP_HZ,
    )
    rms_histogram = FixedHistogram(
        RMS_HISTOGRAM_MIN_DB - RMS_HISTOGRAM_STEP_DB / 2,
        RMS_HISTOGRAM_MAX_DB + RMS_HISTOGRAM_STEP_DB / 2,
        RMS_HISTOGRAM_STEP_DB,
    )
    rate_histogram = FixedHistogram(
        -RATE_HISTOGRAM_STEP_HZ / 2,
        RATE_HISTOGRAM_MAX_HZ + RATE_HISTOGRAM_STEP_HZ / 2,
        RATE_HISTOGRAM_STEP_HZ,
    )
    hnr_histogram = FixedHistogram(
        HNR_HISTOGRAM_MIN_DB - HNR_HISTOGRAM_STEP_DB / 2,
        HNR_HISTOGRAM_MAX_DB + HNR_HISTOGRAM_STEP_DB / 2,
        HNR_HISTOGRAM_STEP_DB,
    )
    for histogram in (f0_histogram, rms_histogram, rate_histogram, hnr_histogram):
        memory.own_histogram(histogram)

    f0_moments = RunningMoments()
    semitone_moments = RunningMoments()
    rms_moments = RunningMoments()
    envelope_moments = RunningMoments()
    f0_turning_points = 0
    rise_frames = 0
    fall_frames = 0
    previous_f0: float | None = None
    before_previous_f0: float | None = None

    analysis_frame_count = int(anchor["analysis_frame_count"])
    maximum_rms = float(anchor["maximum_rms"])
    median_anchor = float(anchor["anchor_median_hz"])
    smoother_width = max(1, int(SYLLABLE_SMOOTH_MS / HOP_MS))
    if smoother_width % 2 == 0:
        smoother_width += 1
    smoother = CenteredSmoother(smoother_width)
    peak_accumulator = PeakAndRateAccumulator(
        threshold=SYLLABLE_THR,
        window_frames=max(1, int(RATE_WINDOW_MS / HOP_MS)),
        analysis_frame_count=analysis_frame_count,
        rate_histogram=rate_histogram,
    )
    pause_accumulator = PauseAccumulator(
        minimum_frames=max(1, int(PAUSE_MIN_MS / HOP_MS)),
        edge_frames=int(EDGE_SKIP_MS / HOP_MS),
        total_frames=analysis_frame_count,
    )
    frame_samples = int(metadata.sample_rate * FRAME_MS / 1000.0)
    hop_samples = int(metadata.sample_rate * HOP_MS / 1000.0)
    boundary_accumulator = BoundaryAccumulator(boundary_offsets, frame_samples, hop_samples)
    spectral = SpectralAccumulator(metadata.sample_rate, frame_samples, hnr_histogram)

    for frame_index, frame in _analysis_frames(path, metadata, memory):
        rms, rms_db = _rms_db(frame)
        rms_moments.add(rms_db)
        rms_histogram.add(rms_db)
        audible = rms_db >= SPECTRAL_FLOOR_DB
        pause_accumulator.add(frame_index, rms_db < PAUSE_RMS_DB)
        if audible:
            spectral.add_spectral(frame, memory)

        envelope = rms / (maximum_rms + 1e-9)
        smoothed = smoother.push(envelope)
        if smoothed is not None:
            smooth_index, smooth_value = smoothed
            envelope_moments.add(smooth_value)
            peak_accumulator.push(smooth_index, smooth_value)

        f0, autocorrelation_peak = f0_autocorr(frame, metadata.sample_rate)
        voiced = autocorrelation_peak >= VOICING_AC and f0 > 0
        accepted = (
            voiced
            and median_anchor > 0
            and 0.5 * median_anchor <= f0 <= 2.0 * median_anchor
        )
        boundary_accumulator.add(frame_index, rms_db, f0, voiced)
        if not accepted:
            spectral.break_voiced_run()
            continue
        spectral.add_voiced(f0, autocorrelation_peak, rms)
        f0_histogram.add(f0)
        f0_moments.add(f0)
        semitone_moments.add(12.0 * math.log2(f0 / median_anchor))
        if previous_f0 is not None:
            difference = f0 - previous_f0
            if difference > 1.0:
                rise_frames += 1
            elif difference < -1.0:
                fall_frames += 1
        if before_previous_f0 is not None and previous_f0 is not None:
            if (
                (previous_f0 > before_previous_f0 and previous_f0 > f0)
                or (previous_f0 < before_previous_f0 and previous_f0 < f0)
            ):
                f0_turning_points += 1
        before_previous_f0 = previous_f0
        previous_f0 = f0

    for smooth_index, smooth_value in smoother.finish():
        envelope_moments.add(smooth_value)
        peak_accumulator.push(smooth_index, smooth_value)
    peak_accumulator.finish()
    pause_accumulator.finish()

    return {
        "f0_histogram": f0_histogram,
        "f0_moments": f0_moments,
        "semitone_moments": semitone_moments,
        "rms_histogram": rms_histogram,
        "rms_moments": rms_moments,
        "envelope_moments": envelope_moments,
        "f0_turning_points": f0_turning_points,
        "rise_frames": rise_frames,
        "fall_frames": fall_frames,
        "peak_accumulator": peak_accumulator,
        "pause_accumulator": pause_accumulator,
        "boundary_accumulator": boundary_accumulator,
        "spectral": spectral,
        "hnr_histogram": hnr_histogram,
    }


def _empty_pitch() -> dict[str, float]:
    return {
        "median_hz": 0.0,
        "mean_hz": 0.0,
        "std_hz": 0.0,
        "range_hz": 0.0,
        "p10_hz": 0.0,
        "p90_hz": 0.0,
        "voiced_frac": 0.0,
        "turning_points_per_sec": 0.0,
        "rising_rate_hz_per_sec": 0.0,
        "falling_rate_hz_per_sec": 0.0,
        "std_semitones": 0.0,
        "range_semitones": 0.0,
        "p10_relative_semitones": 0.0,
        "p90_relative_semitones": 0.0,
    }


def _analyze(path: str, boundary_seconds: Iterable[float]) -> dict[str, object]:
    metadata = _metadata(path)
    duration = metadata.duration_seconds
    frame_samples = int(metadata.sample_rate * FRAME_MS / 1000.0)
    hop_samples = int(metadata.sample_rate * HOP_MS / 1000.0)
    expected_analysis_frames = (
        1 + (metadata.frame_count - frame_samples) // hop_samples
        if metadata.frame_count >= frame_samples
        else 0
    )
    if expected_analysis_frames == 0:
        return {
            "clip": os.path.basename(path),
            "durationSec": round(duration, 3),
            "error": "too_short",
            "analyzerAlgorithmVersion": ANALYZER_ALGORITHM_VERSION,
        }

    boundary_offsets = _sample_offsets(boundary_seconds, metadata)
    memory = ManagedMemoryEstimate()
    anchor = _signal_and_anchor_pass(path, metadata, boundary_offsets, memory)
    if int(anchor["sample_count"]) != metadata.frame_count:
        raise ValueError("PCM frame count changed while analyzing")
    if int(anchor["analysis_frame_count"]) != expected_analysis_frames:
        raise ValueError("analysis frame count disagrees with WAV metadata")
    metrics = _analysis_pass(path, metadata, anchor, boundary_offsets, memory)

    f0_histogram = metrics["f0_histogram"]
    assert isinstance(f0_histogram, FixedHistogram)
    f0_moments = metrics["f0_moments"]
    semitone_moments = metrics["semitone_moments"]
    assert isinstance(f0_moments, RunningMoments)
    assert isinstance(semitone_moments, RunningMoments)
    voiced_fraction = int(anchor["voiced_frame_count"]) / expected_analysis_frames
    accepted_voiced_duration = duration * voiced_fraction

    if f0_moments.count:
        median_hz = f0_histogram.quantile(0.5)
        p10_hz = f0_histogram.quantile(0.10)
        p90_hz = f0_histogram.quantile(0.90)
        reference = max(median_hz, 1e-9)
        f0_group = {
            "median_hz": round(median_hz, 1),
            "mean_hz": round(f0_moments.mean, 1),
            "std_hz": round(f0_moments.standard_deviation, 1),
            "range_hz": round(p90_hz - p10_hz, 1),
            "p10_hz": round(p10_hz, 1),
            "p90_hz": round(p90_hz, 1),
            "voiced_frac": round(voiced_fraction, 3),
            "turning_points_per_sec": (
                round(int(metrics["f0_turning_points"]) / accepted_voiced_duration, 2)
                if accepted_voiced_duration > 0 else 0.0
            ),
            # Preserve the established v1 keys and arithmetic.  These values
            # count rising/falling accepted transitions normalized by voiced
            # duration; the names are retained for consumer compatibility.
            "rising_rate_hz_per_sec": (
                round(int(metrics["rise_frames"]) * HOP_MS / 1000.0 / accepted_voiced_duration, 2)
                if accepted_voiced_duration > 0 else 0.0
            ),
            "falling_rate_hz_per_sec": (
                round(int(metrics["fall_frames"]) * HOP_MS / 1000.0 / accepted_voiced_duration, 2)
                if accepted_voiced_duration > 0 else 0.0
            ),
            "std_semitones": round(semitone_moments.standard_deviation, 3),
            "range_semitones": round(12.0 * math.log2(max(p90_hz, 1e-9) / max(p10_hz, 1e-9)), 3),
            "p10_relative_semitones": round(12.0 * math.log2(max(p10_hz, 1e-9) / reference), 3),
            "p90_relative_semitones": round(12.0 * math.log2(max(p90_hz, 1e-9) / reference), 3),
        }
    else:
        f0_group = _empty_pitch()

    peak_accumulator = metrics["peak_accumulator"]
    pause_accumulator = metrics["pause_accumulator"]
    rms_histogram = metrics["rms_histogram"]
    rms_moments = metrics["rms_moments"]
    envelope_moments = metrics["envelope_moments"]
    boundary_accumulator = metrics["boundary_accumulator"]
    assert isinstance(peak_accumulator, PeakAndRateAccumulator)
    assert isinstance(pause_accumulator, PauseAccumulator)
    assert isinstance(rms_histogram, FixedHistogram)
    assert isinstance(rms_moments, RunningMoments)
    assert isinstance(envelope_moments, RunningMoments)
    assert isinstance(boundary_accumulator, BoundaryAccumulator)

    local_rate_mean = peak_accumulator.rate_moments.mean
    local_rate_std = peak_accumulator.rate_moments.standard_deviation
    rate_group = {
        "syllable_rate_hz": round(peak_accumulator.peak_count / duration, 2) if duration > 0 else 0.0,
        "local_rate_mean_hz": round(local_rate_mean, 2),
        "local_rate_std_hz": round(local_rate_std, 2),
        "local_rate_cv": round(local_rate_std / (local_rate_mean + 1e-9), 2) if peak_accumulator.rate_moments.count else 0.0,
        "local_rate_p10_hz": round(peak_accumulator.rate_histogram.quantile(0.10), 2),
        "local_rate_p90_hz": round(peak_accumulator.rate_histogram.quantile(0.90), 2),
    }
    pause_group = {
        "pause_count": pause_accumulator.count,
        "total_pause_seconds": round(pause_accumulator.total_seconds, 3),
        "mean_pause_seconds": (
            round(pause_accumulator.total_seconds / pause_accumulator.count, 3)
            if pause_accumulator.count else 0.0
        ),
        "max_pause_seconds": round(pause_accumulator.maximum_seconds, 3),
        "pause_speech_ratio": round(pause_accumulator.total_seconds / duration, 3) if duration > 0 else 0.0,
    }
    rms_p10 = rms_histogram.quantile(0.10)
    rms_p90 = rms_histogram.quantile(0.90)
    energy_group = {
        "rms_mean_db": round(rms_moments.mean, 1),
        "rms_std_db": round(rms_moments.standard_deviation, 1),
        "rms_p10_db": round(rms_p10, 1),
        "rms_p90_db": round(rms_p90, 1),
        "dynamic_range_db": round(rms_p90 - rms_p10, 1),
        "envelope_roughness": round(envelope_moments.standard_deviation, 3),
    }
    boundary_group = {
        "requested_count": len(boundary_offsets),
        "observed_count": min(
            int(anchor["boundary_sample_observed"]),
            boundary_accumulator.observed,
        ),
        "max_sample_jump": round(float(anchor["boundary_sample_jump_max"]), 6),
        "max_rms_jump_db": round(boundary_accumulator.max_rms_jump_db, 3),
        "max_pitch_jump_semitones": round(boundary_accumulator.max_pitch_jump_semitones, 3),
        "silence_overlap_count": boundary_accumulator.silence_overlap_count,
    }
    signal_group = {
        "peak": round(float(anchor["peak_normalized"]), 6),
        "clipping_count": int(anchor["clipping_count"]),
        "nonfinite_sample_count": 0,
        "click_count": int(anchor["click_count"]),
        "max_sample_jump": round(float(anchor["maximum_sample_jump"]), 6),
    }

    spectral = metrics["spectral"]
    hnr_histogram = metrics["hnr_histogram"]
    assert isinstance(spectral, SpectralAccumulator)
    assert isinstance(hnr_histogram, FixedHistogram)
    voice_group = {
        "hnr_db_mean": round(spectral.hnr.mean, 2) if spectral.hnr.count else 0.0,
        "hnr_db_std": round(spectral.hnr.standard_deviation, 2) if spectral.hnr.count else 0.0,
        "hnr_db_p10": round(hnr_histogram.quantile(0.10), 2) if spectral.hnr.count else 0.0,
        "hnr_db_p90": round(hnr_histogram.quantile(0.90), 2) if spectral.hnr.count else 0.0,
        "cpp_db_mean": round(spectral.cpp.mean, 2) if spectral.cpp.count else 0.0,
        "cpp_db_std": round(spectral.cpp.standard_deviation, 2) if spectral.cpp.count else 0.0,
        "frame_jitter_pct": round(spectral.jitter.mean, 3) if spectral.jitter.count else 0.0,
        "frame_shimmer_db": round(spectral.shimmer.mean, 3) if spectral.shimmer.count else 0.0,
    }
    spectral_group = {
        "alpha_ratio_db": round(spectral.alpha_ratio.mean, 2) if spectral.alpha_ratio.count else 0.0,
        "hammarberg_db": round(spectral.hammarberg.mean, 2) if spectral.hammarberg.count else 0.0,
        "slope_0_500_db_per_khz": (
            round(spectral.slope_low.mean, 2) if spectral.slope_low.count else 0.0
        ),
        "slope_500_1500_db_per_khz": (
            round(spectral.slope_high.mean, 2) if spectral.slope_high.count else 0.0
        ),
        "centroid_hz": round(spectral.centroid.mean, 1) if spectral.centroid.count else 0.0,
        "centroid_std_hz": (
            round(spectral.centroid.standard_deviation, 1) if spectral.centroid.count else 0.0
        ),
        "flux": round(spectral.flux.mean, 4) if spectral.flux.count else 0.0,
        "hf_energy_ratio": round(spectral.hf_ratio.mean, 4) if spectral.hf_ratio.count else 0.0,
        "measured_frames": spectral.alpha_ratio.count,
    }

    flat: dict[str, object] = {
        "clip": os.path.basename(path),
        "durationSec": round(duration, 3),
        "analyzerAlgorithmVersion": ANALYZER_ALGORITHM_VERSION,
        "analysisPassCount": ANALYSIS_PASS_COUNT,
        "analysisMeasuredPeakManagedBufferBytes": memory.measured_peak_managed_buffer_bytes,
        "analysisEstimatedPeakWorkingSetBytes": memory.estimated_peak_working_set_bytes(
            frame_samples, metadata.channel_count
        ),
        "analysisWorkingSetMeasurementMethod": "owned_numeric_buffers_plus_fixed_temporary_estimate",
        "analysisWorkingSetDurationBounded": True,
    }
    flat.update({f"f0_{key}": value for key, value in f0_group.items()})
    flat.update({f"rate_{key}": value for key, value in rate_group.items()})
    flat.update({f"pauses_{key}": value for key, value in pause_group.items()})
    flat.update({f"energy_{key}": value for key, value in energy_group.items()})
    flat.update({f"boundaries_{key}": value for key, value in boundary_group.items()})
    flat.update({f"signal_{key}": value for key, value in signal_group.items()})
    flat.update({f"voice_{key}": value for key, value in voice_group.items()})
    flat.update({f"spectral_{key}": value for key, value in spectral_group.items()})
    flat["rate_cv"] = flat["rate_local_rate_cv"]
    flat["pause_ratio"] = flat["pauses_pause_speech_ratio"]
    flat["energy_roughness"] = flat["energy_envelope_roughness"]
    return flat


def analyze(path: str, boundary_seconds: Iterable[float] = ()) -> dict[str, object]:
    """Analyze one WAV without raising file/format/analysis errors to callers."""
    try:
        return _analyze(path, boundary_seconds)
    except Exception as error:
        return {
            "clip": os.path.basename(path),
            "error": str(error),
            "durationSec": 0.0,
            "analyzerAlgorithmVersion": ANALYZER_ALGORITHM_VERSION,
        }


def _parse_boundary_seconds(value: str) -> tuple[float, ...]:
    if not value.strip():
        return ()
    try:
        return tuple(float(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as error:
        raise argparse.ArgumentTypeError("boundary seconds must be comma-separated numbers") from error


def main() -> None:
    parser = argparse.ArgumentParser(description="Bounded reference-free prosody analyzer.")
    parser.add_argument("clips", nargs="*", help="PCM16 WAV file(s) to analyze")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument(
        "--boundary-seconds",
        type=_parse_boundary_seconds,
        default=(),
        help="optional strictly increasing comma-separated boundaries applied to each clip",
    )
    arguments = parser.parse_args()
    if not arguments.clips:
        parser.print_help()
        return
    output = [analyze(path, boundary_seconds=arguments.boundary_seconds) for path in arguments.clips]
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
