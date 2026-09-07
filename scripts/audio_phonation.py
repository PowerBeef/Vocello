"""Experimental window-corrected periodicity, not a calibrated speech-quality gate.

Hann autocorrelation is divided out (Boersma's window correction). A 100 ms
window gives seven periods at the 70 Hz floor. Local peaks avoid search-edge
pseudo-pitches; a 0.01 octave cost prefers the fundamental over equal repeats.
These are frozen candidate definitions, not a claim of Praat equivalence or
cycle-level jitter. The existing v3 features and all gate thresholds are untouched.
"""
from __future__ import annotations
import hashlib
import math
from pathlib import Path
import numpy as np

VERSION = "window-corrected-ac-v1"
FRAME_MS = 100.0
F0_MIN, F0_MAX = 70.0, 400.0
OCTAVE_COST = .01
VOICING_THRESHOLD = .30
HNR_CEILING_DB = 60.0
# Numerical interpolation tolerance, not a wider physiological pitch range.
# Snap only estimates within 0.001 Hz of an inclusive endpoint to that endpoint.
BOUNDARY_TOLERANCE_HZ = .001


class WindowCorrectedPitch:
    def __init__(self, sample_rate: int):
        if type(sample_rate) is not int or not 8000 <= sample_rate <= 192000:
            raise ValueError("phonation candidate sample rate must be 8000...192000")
        self.sample_rate = sample_rate
        self.count = int(sample_rate * FRAME_MS / 1000)
        self.fft_count = 1 << (2*self.count-1).bit_length()
        self.window = np.hanning(self.count)
        # Include both possible integer neighbours of each fractional boundary.
        # Filtering integer lags first loses in-range peaks before interpolation.
        self.lo = math.floor(sample_rate/F0_MAX)
        self.hi = math.ceil(sample_rate/F0_MIN)
        ac = self._ac(self.window)
        self.window_ac = ac / ac[0]

    def _ac(self, x):
        spectrum = np.fft.rfft(x, self.fft_count)
        return np.fft.irfft(np.abs(spectrum)**2, self.fft_count)[:self.hi+2]

    def measure(self, frame: np.ndarray) -> tuple[float, float]:
        if frame.shape != (self.count,) or not np.all(np.isfinite(frame)):
            raise ValueError("phonation frame must be complete and finite")
        x = (frame - frame.mean()) * self.window
        if np.dot(x, x) < 1e-6:
            return 0.0, 0.0
        raw = self._ac(x)
        corrected = (raw/raw[0])/self.window_ac
        peaks = np.flatnonzero((corrected[1:-1] > corrected[:-2]) &
                               (corrected[1:-1] >= corrected[2:]))+1
        peaks = peaks[(peaks >= self.lo) & (peaks <= self.hi)]
        if not len(peaks):
            return 0.0, 0.0
        a, b, c = corrected[peaks-1], corrected[peaks], corrected[peaks+1]
        denominator = a-2*b+c
        delta = np.divide(.5*(a-c), denominator, out=np.zeros_like(b), where=denominator != 0)
        lag = peaks + delta
        frequencies = self.sample_rate/lag
        valid = (frequencies >= F0_MIN-BOUNDARY_TOLERANCE_HZ) & \
                (frequencies <= F0_MAX+BOUNDARY_TOLERANCE_HZ)
        if not np.any(valid):
            return 0.0, 0.0
        # Preserve the existing ranking among the now-valid candidate peaks.
        periodicities = b-.25*(a-c)*delta
        score = b[valid] - OCTAVE_COST*np.log2(peaks[valid]/self.lo)
        chosen = int(np.argmax(score))
        peak = float(periodicities[valid][chosen])
        if peak < VOICING_THRESHOLD:
            return 0.0, max(0.0, peak)
        frequency = float(np.clip(frequencies[valid][chosen], F0_MIN, F0_MAX))
        return frequency, min(1-1e-6, max(0.0, peak))

    @property
    def estimated_working_bytes(self):
        # FFT scratch, input/window/AC, and bounded vectorized peak interpolation.
        return 8*(8*self.fft_count + 6*self.count + 20*(self.hi+2))


def analyze_phonation(path: str) -> dict:
    from analyze_prosody import (_metadata, _analysis_frames, ManagedMemoryEstimate,
                                 FixedHistogram, RunningMoments)
    metadata = _metadata(path)
    estimator = WindowCorrectedPitch(metadata.sample_rate)
    memory = ManagedMemoryEstimate()
    pitches = FixedHistogram(69.95, 400.05, .1)
    harmonicity = RunningMoments()
    count = voiced = 0
    for _, frame in _analysis_frames(path, metadata, memory, frame_ms=FRAME_MS):
        count += 1
        f0, periodicity = estimator.measure(frame)
        if f0:
            voiced += 1
            pitches.add(f0)
            harmonicity.add(min(HNR_CEILING_DB, 10*math.log10(periodicity/(1-periodicity))))
    return {
        "schemaVersion": 1, "algorithmVersion": VERSION,
        "implementationSHA256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "frameReaderSHA256": hashlib.sha256(Path(__file__).with_name('analyze_prosody.py').read_bytes()).hexdigest(),
        "numpyVersion": np.__version__,
        "status": "experimental-uncalibrated", "promotionAuthority": False,
        "frameMilliseconds": FRAME_MS, "hopMilliseconds": 10,
        "f0FloorHz": F0_MIN, "f0CeilingHz": F0_MAX,
        "boundaryToleranceHz": BOUNDARY_TOLERANCE_HZ,
        "octaveCost": OCTAVE_COST, "hnrCeilingDB": HNR_CEILING_DB,
        "frameCount": count, "voicedFrameCount": voiced,
        "f0MedianHz": pitches.quantile(.5) if voiced else None,
        "f0RangeHz": pitches.quantile(.9)-pitches.quantile(.1) if voiced else None,
        "windowCorrectedPeriodicityHNRDB": harmonicity.mean if voiced else None,
        "abstentionReason": ("insufficient-duration" if not count else "no-periodic-frames") if not voiced else None,
        "analysisPassCount": 1, "workingSetDurationBounded": True,
        "estimatedPeakWorkingBytes": estimator.estimated_working_bytes +
            memory.estimated_peak_working_set_bytes(estimator.count, metadata.channel_count) + pitches.counts.nbytes,
    }
