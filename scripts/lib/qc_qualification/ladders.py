"""Oracle ladders: known-truth signals for the pitch tracker, HNR and the quality composite (AQ-08).

Audit 2026-09-25 (`docs/audits/2026-09-25-audio-qc-speech-analysis-audit.md`):
section 4.4 makes pYIN and the window-corrected HNR measurands "once oracle
ladders pass (HNR >= 37 dB on noiseless sines, +-1 dB of Parselmouth on SNR
ladders)"; section 4.6 lets the Audiobox and DNSMOS composite serve as the
only DP-31/DP-32 guardrail column "after a ladder test"; section 5.8 states
the metamorphic relation "scores rise monotonically with severity (Spearman
>= 0.9)"; findings AQ-F16 (the HNR proxy reads 0.51, 6.99 and 13.29 dB on
noiseless sines; Praat and the analyzer disagree on pitch), AQ-F18 (neural
quality stays relative and advisory) and AQ-F19 (delivery claims) motivate it.

Three ladders, each a deterministic list of clips whose truth is known by
construction (no judge labels anything; section 5.1 T1):

- **pyin** (16 kHz, the canonical rate `pitch.pyin@1` reads, so the truth sits
  on the tracker's own 10 ms frame grid): steady harmonic tones from 55 to
  950 Hz, formant-shaped "glottal" vowels, exponential glides, vibrato, octave
  jumps, voiced/unvoiced alternation over silence or fricative noise, and white
  noise at 30-0 dB SNR. Per frame the truth is the F0 at the frame centre and
  whether it is voiced; frames whose analysis window touches a voicing change
  or an F0 jump, or the clip's edges, are not scored (`GUARD_SAMPLES`).
  Metrics: gross pitch error rate (GPE, more than 20% off, among frames both
  call voiced), fine pitch error in cents (FPE, the frames without a gross
  error) and voicing decision error (VDE, over scored frames).
- **hnr** (24 kHz, the rate the Stage 1 analyzers read): noiseless sines at 80,
  150 and 300 Hz (the audit's own case), and formant-shaped harmonic sources at
  100-300 Hz with white noise scaled to an exact harmonic-to-noise ratio of 0 to
  40 dB (one noise draw per source, scaled, so each ladder differs only in the
  ratio), plus the noiseless rung.
- **quality** (24 kHz): committed-safe procedural speech (`fixtures.clean_fixture`)
  or lead-supplied recordings, each degraded along four families: additive
  white noise (SNR against the speech RMS), hard clipping (fraction of samples
  above the level), band-limiting (a zero-phase Kaiser-windowed sinc low-pass)
  and codec-like mu-law quantization, five rungs each, plus shams (noise at
  80 dB SNR and a low-pass at 11.9 kHz, the audit's section 5.2 shams).

The composite is the audit's section 4.6 definition: equal-weight z(PQ) +
z(DNSMOS OVRL) - z(WER), each column with duration regressed out over the
evaluated cohort; the WER term enters a ladder only when every rung of it has
a recognizer error rate (procedural pseudo-text has none).

**Criteria.** Each criterion names its source: `audit-4.4` and `audit-5.8`
are the audit's words; `provisional` ones are this module's proposals where the
audit states none (all pYIN limits, the HNR analytic-truth tolerance that
stands in for the Parselmouth comparison until an oracle file is supplied, the
composite's step and sham tolerances). A ladder's verdict is `pass` only when
every gating criterion is the audit's and was evaluated; `pass-provisional`
when a provisional criterion gates or an audit criterion could not be
evaluated; `fail` on any failed gating criterion; `incomplete` when a clip had
no measurement.

Nothing here runs a judge, reads a private file or writes tracked evidence:
the CLI (`scripts/audio_qc_oracle_ladders.py`) writes the WAVs under the build
root and reads the orchestrator's bundle and cache.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from .fixtures import (
    FORMANT_BANDWIDTHS,
    FORMANT_GAINS,
    ROOM_TONE_RMS,
    VOWEL_FORMANTS,
    Fixture,
    clean_fixture,
)
from .pcm import ENGINE_SAMPLE_RATE, SeededStream, json_digest, pcm_digest

LADDER_VERSION = 1
LADDER_SCHEMA = "vocello.audioqc.oracle-ladder/1"
EVALUATION_SCHEMA = "vocello.audioqc.oracle-ladder-evaluation/1"
REPORT_SCHEMA = "vocello.audioqc.oracle-ladder-report/1"
HNR_ORACLE_SCHEMA = "vocello.audioqc.hnr-oracle/1"
LADDERS = ("pyin", "hnr", "quality")
CANONICAL_RATE = 16_000
VERDICTS = ("pass", "pass-provisional", "fail", "incomplete")
CRITERION_STATUSES = ("pass", "fail", "not-evaluated", "not-evaluable")

# --------------------------------------------------------------------------- #
# Synthesis constants
# --------------------------------------------------------------------------- #

LEVEL_DBFS = -20.0
HARMONIC_CEILING_HZ = 7_000.0
FORMANT_FLOOR = 0.02  # as fixtures.render: a harmonic far from every formant keeps this gain
EDGE_RAMP_SECONDS = 0.010
FRICATIVE_LEVEL_DBFS = -30.0

# --------------------------------------------------------------------------- #
# pYIN ladder: the registry's pitch.pyin@1 frame grid (the CLI refuses a mismatch)
# --------------------------------------------------------------------------- #

PYIN_JUDGE = "pitch.pyin@1"
PYIN_RATE = CANONICAL_RATE
PYIN_HOP = 160
PYIN_FRAME = 1024
# A frame is scored only when its analysis window (half a frame each side of
# the centre, librosa's center=True) plus two hops of HMM smoothing clears
# every voicing change, F0 jump and clip edge.
GUARD_SAMPLES = PYIN_FRAME // 2 + 2 * PYIN_HOP
GROSS_ERROR_RATIO = 0.20  # the conventional GPE definition: more than 20% off the true F0
OCTAVE_WINDOW_CENTS = 100.0  # a gross error within a semitone of +-1200 cents is an octave error
CORE_RANGE_HZ = (70.0, 400.0)  # the legacy analyzer's range (AQ-F16); outside it is "extended"

# Provisional limits: audit section 4.4 names pYIN (full 50-1,000 Hz range)
# but states no accuracy criterion for it. The 20% GPE threshold is the
# conventional one; the registry's 0.1-semitone state grid alone quantizes F0
# to +-5 cents (RMS 2.9), so the FPE limits leave room for tracking lag on
# glides and vibrato while still catching a systematic bias of a quarter tone.
# Extended range and noise are looser; the 5 and 0 dB rungs are stress rungs
# with no requirement (reported only).
PYIN_LIMITS: dict[str, dict[str, float]] = {
    "core-clean": {"gpe": 0.02, "fpeRmsCents": 20.0, "vde": 0.05},
    "extended-range": {"gpe": 0.05, "fpeRmsCents": 25.0, "vde": 0.10},
    "noise-20db-plus": {"gpe": 0.03, "fpeRmsCents": 25.0, "vde": 0.08},
    "noise-10db": {"gpe": 0.05, "fpeRmsCents": 35.0, "vde": 0.15},
    "noise-stress": {},
}

# --------------------------------------------------------------------------- #
# HNR ladder
# --------------------------------------------------------------------------- #

HNR_RATE = ENGINE_SAMPLE_RATE
HNR_SECONDS = 1.5
HNR_SINE_F0 = (80.0, 150.0, 300.0)
HNR_GLOTTAL_F0 = (100.0, 150.0, 220.0, 300.0)
HNR_STEPS_DB = (0.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 40.0)
HNR_TRACKERS = {
    # The Stage 1 prosody@3 analyzer's frozen Hann-biased proxy (AQ-F16): expected to fail.
    "prosody@3": "analyze_prosody.voice_hnr_db_mean",
    # The window-corrected candidate of audit section 4.4 (audio_phonation.py).
    "window-corrected-ac-v1": "audio_phonation.windowCorrectedPeriodicityHNRDB",
}
HNR_GATED_TRACKER = "window-corrected-ac-v1"
HNR_NOISELESS_SINE_FLOOR_DB = 37.0  # audit 4.4
HNR_ORACLE_TOLERANCE_DB = 1.0  # audit 4.4: +-1 dB of Parselmouth on SNR ladders
# Provisional stand-in for the Parselmouth comparison: +-1 dB of the constructed
# ratio up to 30 dB. A tracker meeting the 37 dB noiseless floor adds at most
# 10*log10(1 + 10**-0.7) = 0.79 dB of its own there, so the tolerance holds
# for an estimator at that floor; above 30 dB only monotonicity is required.
HNR_TRUTH_TOLERANCE_DB = 1.0
HNR_TRUTH_TOLERANCE_CEILING_DB = 30.0

# --------------------------------------------------------------------------- #
# Quality ladder
# --------------------------------------------------------------------------- #

QUALITY_RATE = ENGINE_SAMPLE_RATE
QUALITY_SOURCES = (("modal", 0), ("modal", 1), ("high-f0", 2), ("breathy", 3))
# Five rungs per family, mildest first.
QUALITY_FAMILIES: dict[str, tuple[str, tuple[float, ...]]] = {
    "noise": ("snrDB", (40.0, 30.0, 20.0, 10.0, 0.0)),
    "clip": ("clippedFraction", (0.002, 0.01, 0.03, 0.08, 0.2)),
    "band": ("cutoffHz", (7_000.0, 5_000.0, 3_500.0, 2_500.0, 1_500.0)),
    "quant": ("muLawBits", (8.0, 6.0, 5.0, 4.0, 3.0)),
}
QUALITY_SHAMS = {"noise": 80.0, "band": 11_900.0}
LOWPASS_HALF_TAPS = 256
LOWPASS_KAISER_BETA = 8.6
MU_LAW = 255.0
AUDIOBOX_JUDGE = "quality.audiobox-aesthetics@1"
DNSMOS_JUDGE = "quality.dnsmos-p835@1"
COMPOSITE_COLUMNS = (("PQ", AUDIOBOX_JUDGE, "PQ", 1.0), ("OVRL", DNSMOS_JUDGE, "OVRL", 1.0))
DIAGNOSTIC_COLUMNS = (("CE", AUDIOBOX_JUDGE), ("CU", AUDIOBOX_JUDGE), ("PC", AUDIOBOX_JUDGE),
                      ("SIG", DNSMOS_JUDGE), ("BAK", DNSMOS_JUDGE))
QUALITY_SPEARMAN_MAXIMUM = -0.9  # audit 5.8: Spearman >= 0.9 with severity; quality falls, so <= -0.9
# Provisional: a rung may exceed the milder one by at most this much (composite
# units: a sum of z-scores), so ties and measurement jitter are allowed while a
# real reversal is not; a sham must stay this close to its clean source.
QUALITY_STEP_TOLERANCE = 0.10
QUALITY_SHAM_TOLERANCE = 0.25


class LadderError(ValueError):
    """A ladder cannot be built or evaluated as asked."""


@dataclass(frozen=True)
class LadderClip:
    clip_id: str
    ladder: str
    condition: str
    group: str
    sample_rate: int
    samples: np.ndarray = field(repr=False)
    truth: Mapping[str, Any]
    digest: str

    @property
    def duration_seconds(self) -> float:
        return self.samples.size / self.sample_rate

    def describe(self) -> dict[str, Any]:
        """The clip's identity and truth: what the ladder's golden digest covers."""
        return {"clipID": self.clip_id, "condition": self.condition, "group": self.group,
                "sampleRate": self.sample_rate, "frames": int(self.samples.size),
                "pcmSHA256": self.digest, "truth": dict(self.truth)}


def _clip(clip_id: str, ladder: str, condition: str, group: str, rate: int, samples: np.ndarray,
          truth: Mapping[str, Any]) -> LadderClip:
    values = np.ascontiguousarray(samples, dtype=np.float64)
    values.setflags(write=False)
    return LadderClip(clip_id, ladder, condition, group, rate, values, dict(truth), pcm_digest(values))


def clips_digest(clips: Sequence[LadderClip]) -> str:
    """The ladder's golden: every clip's identity, PCM16 digest and truth, in order."""
    return json_digest([clip.describe() for clip in clips])


# --------------------------------------------------------------------------- #
# Synthesis
# --------------------------------------------------------------------------- #

def _rms(values: np.ndarray) -> float:
    return float(np.sqrt(np.mean(values ** 2))) if values.size else 0.0


def _raised_cosine(count: int) -> np.ndarray:
    return 0.5 - 0.5 * np.cos(np.pi * np.arange(count) / count)


def spans(mask: np.ndarray) -> list[tuple[int, int]]:
    """[start, end) of every run of True."""
    padded = np.concatenate(([False], np.asarray(mask, dtype=bool), [False]))
    changes = np.flatnonzero(padded[1:] != padded[:-1])
    return [(int(start), int(end)) for start, end in zip(changes[0::2], changes[1::2])]


def ramped(mask: np.ndarray, ramp: int) -> np.ndarray:
    """1 inside each run of the mask, with raised-cosine ramps inside its first and last `ramp` samples."""
    envelope = np.asarray(mask, dtype=np.float64).copy()
    for start, end in spans(mask):
        width = min(ramp, (end - start) // 2)
        if width:
            envelope[start:start + width] *= _raised_cosine(width)
            envelope[end - width:end] *= _raised_cosine(width)[::-1]
    return envelope


def harmonic_source(f0: np.ndarray, rate: int, *, label: str, tilt: float = 1.0, vowel: str | None = None,
                    formant_scale: float = 1.0, harmonics: int | None = None) -> np.ndarray:
    """A harmonic series on a per-sample F0 track: amplitude h**-tilt, optionally formant-shaped.

    With `vowel`, each harmonic's gain follows the five-vowel formant envelope of
    `fixtures.render` at its instantaneous frequency (a floor of 0.02 plus a
    Gaussian bump per formant). Harmonics stay below `HARMONIC_CEILING_HZ` at the
    track's peak, so nothing aliases. Phases are seeded per label.
    """
    track = np.asarray(f0, dtype=np.float64)
    count = harmonics or max(1, int(HARMONIC_CEILING_HZ // float(np.max(track))))
    phase = 2.0 * math.pi * np.cumsum(track) / rate
    offsets = SeededStream(0, "oracle-ladder", "phase", label).uniform(count) * 2.0 * math.pi
    formants = None if vowel is None else tuple(value * formant_scale for value in VOWEL_FORMANTS[vowel])
    output = np.zeros(track.size)
    for harmonic in range(1, count + 1):
        amplitude: Any = float(harmonic) ** -tilt
        if formants is not None:
            frequency = harmonic * track
            gain = np.full(track.size, FORMANT_FLOOR)
            for centre, bandwidth, weight in zip(formants, FORMANT_BANDWIDTHS, FORMANT_GAINS):
                gain += weight * np.exp(-0.5 * ((frequency - centre) / bandwidth) ** 2)
            amplitude = amplitude * gain
        output += amplitude * np.sin(harmonic * phase + offsets[harmonic - 1])
    return output


def _fricative(count: int, label: str) -> np.ndarray:
    """Unit-RMS noise through (1 - z^-2): the band-pass of `fixtures._fricative_noise` (peak at rate/4)."""
    noise = SeededStream(0, "oracle-ladder", "fricative", label).normal(count + 2)
    band = (noise[2:] - noise[:-2]) / math.sqrt(2.0)
    return band / max(_rms(band), 1e-12)


def _white(count: int, *labels: str) -> np.ndarray:
    noise = SeededStream(0, "oracle-ladder", "noise", *labels).normal(count)
    return noise / max(_rms(noise), 1e-12)


# --------------------------------------------------------------------------- #
# pYIN ladder
# --------------------------------------------------------------------------- #

def _group_for_range(*frequencies: float) -> str:
    low, high = CORE_RANGE_HZ
    return "core-clean" if all(low <= value <= high for value in frequencies) else "extended-range"


def pitch_truth(f0: np.ndarray, voiced: np.ndarray, events: Iterable[int]) -> dict[str, Any]:
    """Per-frame truth on pYIN's grid (centre i*hop): F0 (0 when unvoiced), voicing and whether it is scored."""
    count = int(f0.size)
    frames = 1 + count // PYIN_HOP
    centres = np.arange(frames) * PYIN_HOP
    index = np.minimum(centres, count - 1)
    truth_voiced = np.asarray(voiced, dtype=bool)[index]
    truth_f0 = np.where(truth_voiced, f0[index], 0.0)
    scored = (centres - GUARD_SAMPLES >= 0) & (centres + GUARD_SAMPLES <= count)
    for event in events:
        scored &= np.abs(centres - int(event)) >= GUARD_SAMPLES
    return {"frames": int(frames), "hopSamples": PYIN_HOP, "guardSamples": GUARD_SAMPLES,
            "scoredFrames": int(np.count_nonzero(scored)),
            "f0Hz": [round(float(value), 4) for value in truth_f0],
            "voiced": [bool(value) for value in truth_voiced],
            "scored": [bool(value) for value in scored]}


def _voicing_events(voiced: np.ndarray) -> list[int]:
    count = int(voiced.size)
    return sorted({edge for start, end in spans(voiced) for edge in (start, end) if 0 < edge < count})


def _pitch_clip(clip_id: str, condition: str, group: str, f0: np.ndarray, *, voiced: np.ndarray | None = None,
                jumps: Sequence[int] = (), tilt: float = 1.0, vowel: str | None = None,
                formant_scale: float = 1.0, unvoiced_fill: str = "silence", snr_db: float | None = None,
                extra: Mapping[str, Any] | None = None) -> LadderClip:
    count = f0.size
    mask = np.ones(count, dtype=bool) if voiced is None else voiced
    ramp = int(EDGE_RAMP_SECONDS * PYIN_RATE)
    periodic = harmonic_source(f0, PYIN_RATE, label=clip_id, tilt=tilt, vowel=vowel, formant_scale=formant_scale)
    periodic *= ramped(mask, ramp)
    level = 10.0 ** (LEVEL_DBFS / 20.0)
    periodic *= level / max(_rms(periodic[mask]), 1e-12)
    output = periodic
    if unvoiced_fill == "fricative":
        output = output + 10.0 ** (FRICATIVE_LEVEL_DBFS / 20.0) * _fricative(count, clip_id) * ramped(~mask, ramp)
    elif unvoiced_fill != "silence":
        raise LadderError(f"unknown unvoiced fill {unvoiced_fill!r}")
    if snr_db is not None:
        output = output + _white(count, clip_id) * level / 10.0 ** (snr_db / 20.0)
    output = output + ROOM_TONE_RMS * _white(count, clip_id, "room-tone")
    truth = pitch_truth(f0, mask, [*_voicing_events(mask), *jumps])
    truth.update({"snrDB": snr_db, "unvoicedFill": unvoiced_fill, **dict(extra or {})})
    return _clip(clip_id, "pyin", condition, group, PYIN_RATE, output, truth)


def _samples(seconds: float, rate: int = PYIN_RATE) -> int:
    return int(round(seconds * rate))


def _vuv_mask(seconds: float, *, lead: float = 0.2, voiced: float = 0.3, gap: float = 0.2) -> np.ndarray:
    count = _samples(seconds)
    mask = np.zeros(count, dtype=bool)
    cursor = _samples(lead)
    while cursor + _samples(voiced) + _samples(gap) <= count:
        mask[cursor:cursor + _samples(voiced)] = True
        cursor += _samples(voiced) + _samples(gap)
    return mask


def pyin_clips() -> list[LadderClip]:
    """The pitch ladder (about 48 clips, 85 s at 16 kHz)."""
    clips: list[LadderClip] = []
    steady_seconds = 1.5
    for f0 in (55.0, 65.0, 80.0, 100.0, 125.0, 160.0, 200.0, 250.0, 320.0, 400.0, 500.0, 650.0, 800.0, 950.0):
        clips.append(_pitch_clip(f"pyin-steady-{f0:04.0f}hz", "steady", _group_for_range(f0),
                                 np.full(_samples(steady_seconds), f0)))
    for vowel, f0, scale in (("a", 90.0, 1.0), ("i", 90.0, 1.0), ("u", 140.0, 1.0), ("a", 220.0, 1.16),
                             ("i", 220.0, 1.16), ("u", 330.0, 1.16)):
        clips.append(_pitch_clip(f"pyin-glottal-{vowel}-{f0:04.0f}hz", "glottal", "core-clean",
                                 np.full(_samples(steady_seconds), f0), vowel=vowel, formant_scale=scale))
    for start, end in ((100.0, 250.0), (300.0, 120.0), (70.0, 140.0), (200.0, 400.0), (55.0, 110.0), (400.0, 900.0)):
        count = _samples(steady_seconds)
        track = start * (end / start) ** (np.arange(count) / count)
        clips.append(_pitch_clip(f"pyin-glide-{start:04.0f}-{end:04.0f}hz", "glide", _group_for_range(start, end),
                                 track))
    for centre, cents, rate in ((110.0, 30.0, 4.5), (150.0, 50.0, 5.5), (250.0, 100.0, 6.0), (500.0, 60.0, 5.0)):
        count = _samples(2.0)
        time = np.arange(count) / PYIN_RATE
        track = centre * 2.0 ** (cents / 1200.0 * np.sin(2.0 * math.pi * rate * time))
        span = (centre * 2.0 ** (-cents / 1200.0), centre * 2.0 ** (cents / 1200.0))
        clips.append(_pitch_clip(f"pyin-vibrato-{centre:04.0f}hz-{cents:03.0f}c", "vibrato",
                                 _group_for_range(*span), track,
                                 extra={"vibratoRateHz": rate, "vibratoDepthCents": cents}))
    for start, end, name in ((150.0, 300.0, "up"), (220.0, 110.0, "down"), (90.0, 180.0, "up")):
        count = _samples(2.0)
        at = count // 2
        track = np.where(np.arange(count) < at, start, end).astype(np.float64)
        clips.append(_pitch_clip(f"pyin-octave-{name}-{start:04.0f}hz", "octave-jump", "core-clean", track,
                                 jumps=(at,), extra={"jumpSample": at}))
    for fill, f0 in (("silence", 150.0), ("fricative", 150.0), ("fricative", 240.0)):
        mask = _vuv_mask(2.5)
        clips.append(_pitch_clip(f"pyin-vuv-{fill}-{f0:04.0f}hz", "voicing-alternation", "core-clean",
                                 np.full(mask.size, f0), voiced=mask, vowel="a", unvoiced_fill=fill))
    for snr in (30.0, 20.0, 10.0, 5.0, 0.0):
        group = "noise-20db-plus" if snr >= 20.0 else "noise-10db" if snr >= 10.0 else "noise-stress"
        for f0, scale in ((120.0, 1.0), (240.0, 1.16)):
            clips.append(_pitch_clip(f"pyin-noise-{snr:02.0f}db-{f0:04.0f}hz", "noise", group,
                                     np.full(_samples(steady_seconds), f0), vowel="a", formant_scale=scale,
                                     snr_db=snr))
    for snr in (20.0, 10.0):
        group = "noise-20db-plus" if snr >= 20.0 else "noise-10db"
        mask = _vuv_mask(2.5)
        clips.append(_pitch_clip(f"pyin-vuv-noise-{snr:02.0f}db-0150hz", "voicing-alternation-noise", group,
                                 np.full(mask.size, 150.0), voiced=mask, vowel="a", snr_db=snr))
    return clips


# --------------------------------------------------------------------------- #
# pYIN scoring
# --------------------------------------------------------------------------- #

@dataclass
class PitchCounts:
    """Frame counts and cent sums that pool across clips."""

    scored: int = 0
    voicing_errors: int = 0
    truth_voiced: int = 0
    truth_unvoiced: int = 0
    voiced_hits: int = 0
    false_voicing: int = 0
    joint: int = 0
    gross: int = 0
    octave: int = 0
    fine: int = 0
    abs_cents: float = 0.0
    square_cents: float = 0.0
    max_abs_cents: float = 0.0

    def add(self, other: "PitchCounts") -> None:
        for name in ("scored", "voicing_errors", "truth_voiced", "truth_unvoiced", "voiced_hits", "false_voicing",
                     "joint", "gross", "octave", "fine", "abs_cents", "square_cents"):
            setattr(self, name, getattr(self, name) + getattr(other, name))
        self.max_abs_cents = max(self.max_abs_cents, other.max_abs_cents)

    def metrics(self) -> dict[str, Any]:
        def ratio(numerator: float, denominator: int) -> float | None:
            return round(numerator / denominator, 6) if denominator else None

        return {
            "scoredFrames": self.scored, "jointlyVoicedFrames": self.joint, "grossErrorFrames": self.gross,
            "gpe": ratio(self.gross, self.joint),
            "vde": ratio(self.voicing_errors, self.scored),
            "fpeRmsCents": round(math.sqrt(self.square_cents / self.fine), 4) if self.fine else None,
            "fpeMeanAbsCents": round(self.abs_cents / self.fine, 4) if self.fine else None,
            "fpeMaxAbsCents": round(self.max_abs_cents, 4) if self.fine else None,
            "voicedRecall": ratio(self.voiced_hits, self.truth_voiced),
            "voicingFalseAlarmRate": ratio(self.false_voicing, self.truth_unvoiced),
            "octaveErrorRate": ratio(self.octave, self.joint),
        }


def _estimate_voiced(f0: Any, flag: Any) -> float | None:
    """The estimate's F0 when it calls the frame voiced, else None."""
    if flag is not True or isinstance(f0, bool) or not isinstance(f0, (int, float)):
        return None
    value = float(f0)
    return value if math.isfinite(value) and value > 0.0 else None


def score_pitch(truth: Mapping[str, Any], estimate: Mapping[str, Any]) -> PitchCounts:
    """One clip's counts: the tracker's per-frame `f0Hz` and `voiced` against the truth."""
    frames = int(truth["frames"])
    f0 = list(estimate.get("f0Hz") or [])
    flags = list(estimate.get("voiced") or [])
    if len(f0) != frames or len(flags) != frames:
        raise LadderError(f"the estimate has {len(f0)} frames, the truth {frames}")
    counts = PitchCounts()
    for index in range(frames):
        if not truth["scored"][index]:
            continue
        counts.scored += 1
        true_voiced = bool(truth["voiced"][index])
        estimated = _estimate_voiced(f0[index], flags[index])
        if true_voiced:
            counts.truth_voiced += 1
        else:
            counts.truth_unvoiced += 1
        if true_voiced != (estimated is not None):
            counts.voicing_errors += 1
        if estimated is not None and not true_voiced:
            counts.false_voicing += 1
        if not (true_voiced and estimated is not None):
            continue
        counts.voiced_hits += 1
        counts.joint += 1
        reference = float(truth["f0Hz"][index])
        cents = 1200.0 * math.log2(estimated / reference)
        if abs(estimated / reference - 1.0) > GROSS_ERROR_RATIO:
            counts.gross += 1
            if abs(abs(cents) - 1200.0) <= OCTAVE_WINDOW_CENTS:
                counts.octave += 1
            continue
        counts.fine += 1
        counts.abs_cents += abs(cents)
        counts.square_cents += cents * cents
        counts.max_abs_cents = max(counts.max_abs_cents, abs(cents))
    return counts


def _criterion(criterion_id: str, source: str, metric: str, comparison: str, limit: float | None,
               observed: float | None, *, gating: bool = True, status: str | None = None) -> dict[str, Any]:
    if status is None:
        if observed is None:
            status = "not-evaluable"
        elif comparison == "max":
            status = "pass" if observed <= limit else "fail"
        elif comparison == "min":
            status = "pass" if observed >= limit else "fail"
        else:
            raise LadderError(f"unknown comparison {comparison!r}")
    return {"id": criterion_id, "source": source, "metric": metric, "comparison": comparison,
            "limit": limit, "observed": None if observed is None else round(float(observed), 6),
            "status": status, "gating": gating}


def verdict(criteria: Sequence[Mapping[str, Any]], *, missing_clips: int = 0) -> str:
    """The ladder's verdict from its gating criteria (see the module docstring)."""
    gating = [criterion for criterion in criteria if criterion["gating"]]
    if any(criterion["status"] == "fail" for criterion in gating):
        return "fail"
    if missing_clips or any(criterion["status"] == "not-evaluable" for criterion in gating):
        return "incomplete"
    provisional = any(criterion["source"] == "provisional" for criterion in gating) or any(
        criterion["status"] == "not-evaluated" and criterion["source"].startswith("audit") for criterion in criteria)
    return "pass-provisional" if provisional else "pass"


def evaluate_pitch(truths: Mapping[str, Mapping[str, Any]], groups: Mapping[str, str],
                   estimates: Mapping[str, Mapping[str, Any] | None]) -> dict[str, Any]:
    """Pooled per-group metrics and criteria for one pitch tracker over the ladder."""
    pooled = {group: PitchCounts() for group in PYIN_LIMITS}
    per_clip: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for clip_id, truth in truths.items():
        estimate = estimates.get(clip_id)
        if estimate is None:
            missing.append(clip_id)
            continue
        try:
            counts = score_pitch(truth, estimate)
        except LadderError:
            missing.append(clip_id)
            continue
        pooled[groups[clip_id]].add(counts)
        per_clip[clip_id] = {"group": groups[clip_id], **counts.metrics()}
    criteria = []
    group_metrics = {}
    for group, limits in PYIN_LIMITS.items():
        metrics = pooled[group].metrics()
        group_metrics[group] = metrics
        for metric, limit in limits.items():
            criteria.append(_criterion(f"{group}.{metric}", "provisional", metric, "max", limit, metrics[metric]))
    worst = sorted(per_clip.items(), key=lambda item: (-(item[1]["gpe"] or 0.0), -(item[1]["vde"] or 0.0), item[0]))
    return {"groups": group_metrics, "criteria": criteria, "clips": per_clip,
            "worstClips": [clip_id for clip_id, _ in worst[:5]], "missingClips": sorted(missing),
            "verdict": verdict(criteria, missing_clips=len(missing))}


# --------------------------------------------------------------------------- #
# HNR ladder
# --------------------------------------------------------------------------- #

def _hnr_periodic(source: str, f0: float) -> np.ndarray:
    count = int(round(HNR_SECONDS * HNR_RATE))
    track = np.full(count, f0)
    label = f"hnr-{source}-{f0:04.0f}hz"
    if source == "sine":
        periodic = harmonic_source(track, HNR_RATE, label=label, harmonics=1)
    else:
        periodic = harmonic_source(track, HNR_RATE, label=label, vowel="a", formant_scale=1.0 if f0 < 160 else 1.16)
    return periodic * 10.0 ** (LEVEL_DBFS / 20.0) / _rms(periodic)


def hnr_clips() -> list[LadderClip]:
    """Noiseless sines, then per glottal source its SNR steps and the noiseless rung (39 clips, 58.5 s)."""
    clips = []
    for f0 in HNR_SINE_F0:
        clip_id = f"hnr-sine-{f0:04.0f}hz-noiseless"
        clips.append(_clip(clip_id, "hnr", "noiseless-sine", "noiseless-sine", HNR_RATE, _hnr_periodic("sine", f0),
                           {"ladder": f"hnr-sine-{f0:04.0f}hz", "source": "sine", "f0Hz": f0, "hnrDB": None,
                            "noiseless": True}))
    for f0 in HNR_GLOTTAL_F0:
        ladder = f"hnr-glottal-{f0:04.0f}hz"
        periodic = _hnr_periodic("glottal", f0)
        draw = _white(periodic.size, ladder)
        harmonic_energy = float(np.sum(periodic ** 2))
        for snr in HNR_STEPS_DB:
            scale = math.sqrt(harmonic_energy / (float(np.sum(draw ** 2)) * 10.0 ** (snr / 10.0)))
            clips.append(_clip(f"{ladder}-snr{snr:02.0f}db", "hnr", "snr-step", "snr-ladder", HNR_RATE,
                               periodic + scale * draw,
                               {"ladder": ladder, "source": "glottal", "f0Hz": f0, "hnrDB": snr, "noiseless": False}))
        clips.append(_clip(f"{ladder}-noiseless", "hnr", "noiseless", "snr-ladder", HNR_RATE, periodic,
                           {"ladder": ladder, "source": "glottal", "f0Hz": f0, "hnrDB": None, "noiseless": True}))
    return clips


def _truth_order(truth: Mapping[str, Any]) -> float:
    return math.inf if truth["noiseless"] else float(truth["hnrDB"])


def evaluate_hnr_tracker(truths: Mapping[str, Mapping[str, Any]], readings: Mapping[str, float | None],
                         oracle: Mapping[str, float] | None) -> dict[str, Any]:
    """One tracker's criteria over the HNR ladder; `oracle` is Parselmouth's reading per clip, when supplied."""
    sines = [clip_id for clip_id, truth in truths.items() if truth["source"] == "sine" and truth["noiseless"]]
    sine_readings = [readings.get(clip_id) for clip_id in sines]
    sine_floor = None if any(value is None for value in sine_readings) else min(sine_readings)
    criteria = [_criterion("noiseless-sine-floor", "audit-4.4", "minimumNoiselessSineHNRDB", "min",
                           HNR_NOISELESS_SINE_FLOOR_DB, sine_floor)]
    ladders: dict[str, list[str]] = {}
    for clip_id, truth in truths.items():
        if truth["source"] != "sine":
            ladders.setdefault(truth["ladder"], []).append(clip_id)
    reversals, worst_reversal, incomplete = 0, 0.0, False
    ladder_readings = {}
    for ladder, members in sorted(ladders.items()):
        ordered = sorted(members, key=lambda clip_id: _truth_order(truths[clip_id]))
        values = [readings.get(clip_id) for clip_id in ordered]
        ladder_readings[ladder] = [None if value is None else round(float(value), 4) for value in values]
        if any(value is None for value in values):
            incomplete = True
            continue
        for lower, higher in zip(values, values[1:]):
            if higher < lower:
                reversals += 1
                worst_reversal = max(worst_reversal, lower - higher)
    criteria.append(_criterion("monotone-in-truth", "audit-5.8", "largestReversalDB", "max", 0.0,
                               None if incomplete else worst_reversal))
    in_range = [clip_id for clip_id, truth in truths.items()
                if not truth["noiseless"] and float(truth["hnrDB"]) <= HNR_TRUTH_TOLERANCE_CEILING_DB]
    errors = [None if readings.get(clip_id) is None else abs(float(readings[clip_id]) - float(truths[clip_id]["hnrDB"]))
              for clip_id in in_range]
    truth_error = None if any(value is None for value in errors) or not errors else max(errors)
    oracle_ids = [clip_id for clip_id, truth in truths.items() if not truth["noiseless"]]
    oracle_error = None
    oracle_status = "not-evaluated"
    if oracle is not None:
        deltas = [None if readings.get(clip_id) is None or clip_id not in oracle
                  else abs(float(readings[clip_id]) - float(oracle[clip_id])) for clip_id in oracle_ids]
        oracle_error = None if any(value is None for value in deltas) else max(deltas)
        oracle_status = None
    criteria.append(_criterion("analytic-truth-1db", "provisional", "maximumAbsErrorDBAtOrBelow30DB", "max",
                               HNR_TRUTH_TOLERANCE_DB, truth_error, gating=oracle is None))
    criteria.append(_criterion("parselmouth-1db", "audit-4.4", "maximumAbsDeltaFromOracleDB", "max",
                               HNR_ORACLE_TOLERANCE_DB, oracle_error, gating=oracle is not None,
                               status=oracle_status))
    return {"criteria": criteria, "ladders": ladder_readings,
            "noiselessSines": {clip_id: None if value is None else round(float(value), 4)
                               for clip_id, value in zip(sines, sine_readings)},
            "reversals": reversals,
            "maximumAbsErrorDB": None if truth_error is None else round(truth_error, 4),
            "verdict": verdict(criteria, missing_clips=sum(1 for clip_id in truths if readings.get(clip_id) is None))}


# --------------------------------------------------------------------------- #
# Quality ladder
# --------------------------------------------------------------------------- #

def lowpass(samples: np.ndarray, cutoff_hz: float, rate: int) -> np.ndarray:
    """A zero-phase Kaiser-windowed sinc low-pass (513 taps, beta 8.6, unity DC gain)."""
    taps = np.arange(-LOWPASS_HALF_TAPS, LOWPASS_HALF_TAPS + 1, dtype=np.float64)
    fraction = 2.0 * cutoff_hz / rate
    kernel = fraction * np.sinc(fraction * taps) * np.kaiser(taps.size, LOWPASS_KAISER_BETA)
    kernel /= float(np.sum(kernel))
    return np.convolve(samples, kernel, mode="same")


def hard_clip(samples: np.ndarray, fraction: float) -> np.ndarray:
    """Flat tops at the magnitude that `fraction` of the samples exceed (SIG-CLIP's hard mode, finer steps)."""
    magnitude = np.sort(np.abs(samples))[::-1]
    level = float(magnitude[min(int(math.ceil(fraction * magnitude.size)), magnitude.size - 1)])
    return np.clip(samples, -level, level)


def mu_law(samples: np.ndarray, bits: int) -> np.ndarray:
    """Mu-law (255) companding, quantized to `bits` (sign included), then expanded: codec-like quantization."""
    values = np.clip(samples, -1.0, 1.0)
    compressed = np.sign(values) * np.log1p(MU_LAW * np.abs(values)) / math.log1p(MU_LAW)
    levels = 2 ** (int(bits) - 1) - 1
    scaled = compressed * levels
    quantized = np.sign(scaled) * np.floor(np.abs(scaled) + 0.5) / levels
    return np.sign(quantized) * np.expm1(np.abs(quantized) * math.log1p(MU_LAW)) / MU_LAW


def speech_rms(source: Fixture) -> float:
    """RMS over the source's word intervals (a recording has none: the whole take)."""
    spans_ = [source.samples[start:end] for start, end in source.words]
    speech = np.concatenate(spans_) if spans_ else np.asarray(source.samples)
    return _rms(speech)


def degrade(source: Fixture, family: str, parameter: float) -> np.ndarray:
    samples = np.asarray(source.samples, dtype=np.float64)
    if family == "noise":
        draw = _white(samples.size, "quality", source.digest)
        return samples + draw * speech_rms(source) / 10.0 ** (parameter / 20.0)
    if family == "clip":
        return hard_clip(samples, parameter)
    if family == "band":
        return lowpass(samples, parameter, source.sample_rate)
    if family == "quant":
        return mu_law(samples, int(parameter))
    raise LadderError(f"unknown degradation family {family!r}")


def procedural_quality_sources() -> list[Fixture]:
    return [clean_fixture(index, stratum) for stratum, index in QUALITY_SOURCES]


def quality_clips(sources: Sequence[tuple[str, Fixture, Mapping[str, Any]]] | None = None) -> list[LadderClip]:
    """Per source: the clean rung, five rungs per family and the shams (23 clips per source).

    `sources` are (source id, 24 kHz fixture, extra truth) triples; by default the
    committed-safe procedural sources. Extra truth carries a recording's language
    and text digest (never its text).
    """
    if sources is None:
        sources = [(fixture.fixture_id, fixture, {}) for fixture in procedural_quality_sources()]
    clips = []
    for source_id, source, extra in sources:
        if source.sample_rate != QUALITY_RATE:
            raise LadderError(f"{source_id}: a quality source is at {QUALITY_RATE} Hz")
        base = {"source": source_id, "sourcePCMSHA256": source.digest, **dict(extra)}
        clips.append(_clip(f"q-{source_id}-clean", "quality", "clean", "clean", QUALITY_RATE, source.samples,
                           {**base, "family": None, "severityRank": 0, "parameter": None, "sham": False}))
        for family, (parameter_name, rungs) in QUALITY_FAMILIES.items():
            for rank, value in enumerate(rungs, start=1):
                clips.append(_clip(f"q-{source_id}-{family}-{rank}", "quality", family, family, QUALITY_RATE,
                                   degrade(source, family, value),
                                   {**base, "family": family, "severityRank": rank, "parameterName": parameter_name,
                                    "parameter": value, "sham": False}))
            if family in QUALITY_SHAMS:
                value = QUALITY_SHAMS[family]
                clips.append(_clip(f"q-{source_id}-{family}-sham", "quality", f"{family}-sham", "sham", QUALITY_RATE,
                                   degrade(source, family, value),
                                   {**base, "family": family, "severityRank": 0, "parameterName": parameter_name,
                                    "parameter": value, "sham": True}))
    return clips


def _ranks(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start
        while end + 1 < len(order) and values[order[end + 1]] == values[order[start]]:
            end += 1
        for position in range(start, end + 1):
            ranks[order[position]] = (start + end) / 2.0 + 1.0
        start = end + 1
    return ranks


def spearman(first: Sequence[float], second: Sequence[float]) -> float | None:
    """Spearman's rank correlation (average ranks for ties); None when either side is constant."""
    if len(first) != len(second) or len(first) < 2:
        return None
    a, b = np.array(_ranks(first)), np.array(_ranks(second))
    a -= a.mean()
    b -= b.mean()
    norm = math.sqrt(float(np.dot(a, a)) * float(np.dot(b, b)))
    return None if norm == 0.0 else float(np.dot(a, b)) / norm


def standardize(values: Mapping[str, float], durations: Mapping[str, float]) -> dict[str, float]:
    """z-scores over the cohort after regressing out duration (ordinary least squares with an intercept)."""
    keys = sorted(values)
    if not keys:
        return {}
    y = np.array([float(values[key]) for key in keys])
    d = np.array([float(durations[key]) for key in keys])
    if len(keys) > 2 and float(np.var(d)) > 0.0:
        slope = float(np.dot(d - d.mean(), y - y.mean()) / np.dot(d - d.mean(), d - d.mean()))
        residual = y - (y.mean() + slope * (d - d.mean()))
    else:
        residual = y - y.mean()
    spread = float(np.std(residual))
    z = residual / spread if spread > 0.0 else np.zeros_like(residual)
    return {key: float(value) for key, value in zip(keys, z)}


def evaluate_quality(truths: Mapping[str, Mapping[str, Any]], columns: Mapping[str, Mapping[str, float]],
                     durations: Mapping[str, float], *, wer: Mapping[str, float] | None = None,
                     diagnostics: Mapping[str, Mapping[str, float]] | None = None) -> dict[str, Any]:
    """The composite's ladder test.

    `columns` maps PQ and OVRL to per-clip values, `wer` a recognizer's error
    rate per clip (optional), `durations` the canonical duration per clip.
    """
    missing = sorted(clip_id for clip_id in truths
                     if any(clip_id not in columns.get(name, {}) for name, *_ in COMPOSITE_COLUMNS))
    z = {name: standardize(columns.get(name, {}), durations) for name, *_ in COMPOSITE_COLUMNS}
    by_source: dict[str, list[str]] = {}
    for clip_id, truth in truths.items():
        by_source.setdefault(truth["source"], []).append(clip_id)
    wer = wer or {}
    wer_sources = {source for source, members in by_source.items() if members and all(m in wer for m in members)}
    z_wer = standardize({clip_id: wer[clip_id] for source in wer_sources for clip_id in by_source[source]}, durations)
    composite: dict[str, float | None] = {}
    for clip_id, truth in truths.items():
        if clip_id in missing:
            composite[clip_id] = None
            continue
        value = sum(weight * z[name][clip_id] for name, _judge, _metric, weight in COMPOSITE_COLUMNS)
        if truth["source"] in wer_sources:
            value -= z_wer[clip_id]
        composite[clip_id] = value
    ladders = []
    worst_rho, worst_step, worst_sham = -1.0, 0.0, 0.0
    rho_incomplete = step_incomplete = sham_incomplete = False
    diagnostics = diagnostics or {}
    for source, members in sorted(by_source.items()):
        clean = [clip_id for clip_id in members if truths[clip_id]["family"] is None]
        for family in QUALITY_FAMILIES:
            rungs = sorted((clip_id for clip_id in members if truths[clip_id]["family"] == family
                            and not truths[clip_id]["sham"]), key=lambda clip_id: truths[clip_id]["severityRank"])
            ordered = clean + rungs
            values = [composite.get(clip_id) for clip_id in ordered]
            severities = [truths[clip_id]["severityRank"] for clip_id in ordered]
            entry: dict[str, Any] = {"source": source, "family": family, "clips": ordered,
                                     "composite": [None if value is None else round(value, 4) for value in values],
                                     "werTerm": source in wer_sources}
            if any(value is None for value in values) or len(ordered) < 2:
                rho_incomplete = step_incomplete = True
                entry.update(spearman=None, largestRise=None)
            else:
                rho = spearman(severities, values)
                rise = max(0.0, *(later - earlier for earlier, later in zip(values, values[1:])))
                entry.update(spearman=None if rho is None else round(rho, 4), largestRise=round(rise, 4))
                worst_rho = max(worst_rho, 1.0 if rho is None else rho)
                worst_step = max(worst_step, rise)
            components = {}
            for name, source_values in [*((name, columns.get(name, {})) for name, *_ in COMPOSITE_COLUMNS),
                                        *diagnostics.items(), ("errorRate", wer)]:
                series = [source_values.get(clip_id) for clip_id in ordered]
                if series and all(value is not None for value in series):
                    rho = spearman(severities, [float(value) for value in series])
                    components[name] = None if rho is None else round(rho, 4)
            entry["componentSpearman"] = components
            ladders.append(entry)
        for clip_id in (clip_id for clip_id in members if truths[clip_id]["sham"]):
            if not clean or composite.get(clip_id) is None or composite.get(clean[0]) is None:
                sham_incomplete = True
                continue
            worst_sham = max(worst_sham, abs(composite[clip_id] - composite[clean[0]]))
    criteria = [
        _criterion("severity-spearman", "audit-5.8", "largestSpearmanWithSeverity", "max", QUALITY_SPEARMAN_MAXIMUM,
                   None if rho_incomplete else worst_rho),
        _criterion("step-tolerance", "provisional", "largestRiseBetweenRungs", "max", QUALITY_STEP_TOLERANCE,
                   None if step_incomplete else worst_step),
        _criterion("sham-tolerance", "provisional", "largestShamDeltaFromClean", "max", QUALITY_SHAM_TOLERANCE,
                   None if sham_incomplete else worst_sham),
    ]
    by_family = {family: {"ladders": sum(1 for entry in ladders if entry["family"] == family),
                          "passing": sum(1 for entry in ladders if entry["family"] == family
                                         and entry["spearman"] is not None
                                         and entry["spearman"] <= QUALITY_SPEARMAN_MAXIMUM
                                         and entry["largestRise"] <= QUALITY_STEP_TOLERANCE)}
                 for family in QUALITY_FAMILIES}
    return {"criteria": criteria, "ladders": ladders, "families": by_family,
            "werSources": sorted(wer_sources), "missingClips": missing,
            "verdict": verdict(criteria, missing_clips=len(missing))}


# --------------------------------------------------------------------------- #
# The criteria as data (the truth file and the doc read these)
# --------------------------------------------------------------------------- #

def criteria_description(ladder: str) -> dict[str, Any]:
    if ladder == "pyin":
        return {"judge": PYIN_JUDGE, "grossErrorRatio": GROSS_ERROR_RATIO, "guardSamples": GUARD_SAMPLES,
                "coreRangeHz": list(CORE_RANGE_HZ), "limits": PYIN_LIMITS, "source": "provisional"}
    if ladder == "hnr":
        return {"trackers": dict(HNR_TRACKERS), "gatedTracker": HNR_GATED_TRACKER,
                "noiselessSineFloorDB": {"limit": HNR_NOISELESS_SINE_FLOOR_DB, "source": "audit-4.4"},
                "oracleToleranceDB": {"limit": HNR_ORACLE_TOLERANCE_DB, "source": "audit-4.4"},
                "analyticTruthToleranceDB": {"limit": HNR_TRUTH_TOLERANCE_DB,
                                             "ceilingDB": HNR_TRUTH_TOLERANCE_CEILING_DB, "source": "provisional"},
                "monotone": {"largestReversalDB": 0.0, "source": "audit-5.8"}}
    if ladder == "quality":
        return {"composite": "z(PQ)+z(OVRL)-z(WER), duration regressed out", "source": "audit-4.6",
                "spearmanMaximum": {"limit": QUALITY_SPEARMAN_MAXIMUM, "source": "audit-5.8"},
                "stepTolerance": {"limit": QUALITY_STEP_TOLERANCE, "source": "provisional"},
                "shamTolerance": {"limit": QUALITY_SHAM_TOLERANCE, "source": "provisional"},
                "families": {family: {"parameter": name, "rungs": list(rungs)}
                             for family, (name, rungs) in QUALITY_FAMILIES.items()},
                "shams": dict(QUALITY_SHAMS)}
    raise LadderError(f"unknown ladder {ladder!r}")


def ladder_clips(ladder: str, *, quality_sources: Sequence[tuple[str, Fixture, Mapping[str, Any]]] | None = None
                 ) -> list[LadderClip]:
    if ladder == "pyin":
        return pyin_clips()
    if ladder == "hnr":
        return hnr_clips()
    if ladder == "quality":
        return quality_clips(quality_sources)
    raise LadderError(f"unknown ladder {ladder!r}")
