"""Experimental window-corrected periodicity, not a calibrated speech-quality gate.

Hann autocorrelation is divided out (Boersma's window correction). A 100 ms
window gives seven periods at the 70 Hz floor. Local peaks avoid search-edge
pseudo-pitches; a 0.01 octave cost prefers the fundamental over equal repeats.
These are frozen candidate definitions, not a claim of Praat equivalence or
cycle-level jitter. The existing v3 features and all gate thresholds are untouched.
"""
from __future__ import annotations
import math
import numpy as np

VERSION = "window-corrected-ac-v1"
FRAME_MS = 100.0
F0_MIN, F0_MAX = 70.0, 400.0
OCTAVE_COST = .01
VOICING_THRESHOLD = .30
HNR_CEILING_DB = 60.0


class WindowCorrectedPitch:
    def __init__(self, sample_rate: int):
        if type(sample_rate) is not int or not 8000 <= sample_rate <= 192000:
            raise ValueError("phonation candidate sample rate must be 8000...192000")
        self.sample_rate = sample_rate
        self.count = int(sample_rate * FRAME_MS / 1000)
        self.fft_count = 1 << (2*self.count-1).bit_length()
        self.window = np.hanning(self.count)
        self.lo = math.ceil(sample_rate/F0_MAX)
        self.hi = math.floor(sample_rate/F0_MIN)
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
        score = corrected[peaks] - OCTAVE_COST*np.log2(peaks/self.lo)
        k = int(peaks[np.argmax(score)])
        a, b, c = corrected[k-1:k+2]
        denominator = a-2*b+c
        delta = float(.5*(a-c)/denominator) if denominator else 0.0
        peak = float(b-.25*(a-c)*delta)
        if peak < VOICING_THRESHOLD:
            return 0.0, max(0.0, peak)
        return self.sample_rate/(k+delta), min(1-1e-6, max(0.0, peak))

    @property
    def estimated_working_bytes(self):
        # Conservative simultaneous real/complex FFT scratch plus input/window/AC.
        return 8*(8*self.fft_count + 6*self.count + 4*(self.hi+2))


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
        "status": "experimental-uncalibrated", "promotionAuthority": False,
        "frameMilliseconds": FRAME_MS, "hopMilliseconds": 10,
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
