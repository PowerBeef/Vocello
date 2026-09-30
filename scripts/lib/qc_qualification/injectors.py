"""The T1 PCM injector catalog (audit section 5.2, label tier T1).

Every injector is a pure function of (source, parameters, seed): the same
source PCM, parameters and seed give byte-identical output, pinned by a golden
PCM16 digest per variant. Every family has a `sham`, the same processing at
zero magnitude, drawing the same positions from the same seeded stream as its
positives, plus a mild / moderate / severe sweep; a `control` is a non-identity
matched processing the audit names (a natural pause of equal length at
punctuation, a same-speaker splice, a peak normalization without clipping).
Positives emit a labeled interval in the output timeline that covers every
sample the injection changed; shams and controls emit none. A variant that
needs something its source lacks (a pause control on a source that declares
no pause) raises `InjectorNotApplicable` instead of substituting another
construction.

Word-aligned edits (deletion, insertion, repetition, truncation) use the
source's exact word intervals, which procedural fixtures carry by construction;
on recorded speech they come from the aligner on N1 and N2 only
(`recordings.word_alignment`). A
recorded natural take (N3, `recordings.recording_fixture`) carries no word
interval, declared pause, script or render voice, so `inject` refuses every
variant that needs one with `InjectorNotApplicable` (`needs`). A few injectors
declare word-free recording variants instead (`Injector.recording_variants`,
named `take-*`): clicks anywhere, a dropout centred on the take, noise against
the whole take's RMS, a cut at a fraction of the take and a run-on appended at
its end. They are declared constructions with their own parameters, never a
silent substitute, and leave every catalog variant's output unchanged. Identity
swaps splice a second voice rendering the same script, so the splice is
time-aligned and only the voice changes. Pitch and rate changes use a
windowed-sinc resampler and plain overlap-add (no correlation search, whose
arg-max could differ between hosts), so they are signal-level constructions,
not natural prosody.

Catalog version 3 adds a band-limit ladder relative to the source's measured
effective bandwidth (SIG-BAND), erratic pitch over seeded spans (PRS-ERRATIC),
an onset identity swap (IDN-ONSET) and the long-form seam families (SEAM-DISC,
SEAM-VOICE), which act at the seam offsets a long-form source declares
(`Fixture.seams`). On a speaker-labelled recording the identity and seam-voice
families splice a *donor*: another recording of the same cohort, of another
speaker of the same language and gender for a positive and another utterance of
the source speaker for the sham (`inject(..., donor=)`; the calibration set
chooses it, `speaker_donors`). The donor's words replace the source's at aligned
word boundaries, level-matched, so the positive and its sham differ only in who
speaks. Every version 2 variant's output is unchanged.

A generated long-form take (N3) has no word interval and no corpus speaker, but
the voice it was generated with is its speaker label (a Built-in speaker, a
Voice Design brief, a clone reference speaker). SEAM-VOICE's `take-voice-*`
recording variants splice from such a *voice donor*, another long-form take of
another voice (`other-voice`) for a positive and of the source's voice
(`same-voice`) for the sham: the segment after the seeded seam (or its first 1
or 2 s) is replaced by the donor's own audio from the start of one of its
segments, level-matched and crossfaded inside the replaced span, so the label
covers exactly the replaced samples and the seams after it move by the length
change (`_voice_splice`). They leave every other variant's output unchanged.

NumPy only. The catalog version and each injector's version are part of every
recipe; changing an injector's output needs a new version and a new golden.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

import numpy as np

from .fixtures import ROOM_TONE_RMS, Fixture, donor_voice, rerender
from .pcm import SeededStream, pcm_digest

CATALOG_VERSION = 3
MECHANISM = "T1-pcm-construction"
SEVERITIES = ("sham", "control", "mild", "moderate", "severe")
NON_DEFECT_SEVERITIES = frozenset({"sham", "control"})
SPLICE_FADE_MS = 5.0
OLA_WINDOW = 960
OLA_HOP = 240
SINC_HALF_WIDTH = 16
# Soft-knee clipping: samples above the knee are squashed by tanh toward an
# asymptote this far above it (about +1 dB), so the output never exceeds it.
SOFT_KNEE_HEADROOM = 0.12
# A dropout centred on a recorded take keeps at least this much of it on each side.
CENTRE_MARGIN_MS = 250.0
# SIG-BAND@1 measures the source's effective bandwidth as Stage 0 does (`audio_qc_observations`,
# `effectiveBandwidthHz`), at these constants of its own, so a change to the observation never moves
# the injector's output: 512-point Hann frames every 10 ms, a frame of mean square 1e-6 or more is
# active, and the bandwidth is the highest long-term-average bin within 50 dB of the peak bin.
BAND_FFT_SIZE = 512
BAND_FRAMES_PER_SECOND = 100
BAND_ACTIVE_MEAN_SQUARE = 1e-6
BAND_THRESHOLD_DB = 50.0
# The low-pass: a Blackman-windowed sinc (about 74 dB of stopband, a 260 Hz transition at 24 kHz).
BAND_TAPS = 511
# A cutoff below this leaves no band-limit to measure, only muffled speech.
BAND_MINIMUM_CUTOFF_HZ = 1_000.0
# No cutoff above this fraction of Nyquist (11.88 kHz at 24 kHz, the audit's 11.9 kHz sham).
BAND_CEILING_FRACTION = 0.99
# SEAM-DISC's largest removal: every variant draws its seam among those with room for it.
SEAM_DISC_MAXIMUM_MS = 20.0
# SEAM-VOICE draws its seam among those whose following segment lasts at least this long.
SEAM_VOICE_MINIMUM_MS = 500.0
# A donor variant's `donor` parameter: another speaker for a positive, the source speaker for its sham.
DONOR_RELATIONS = ("other-speaker", "same-speaker")
# A voice donor's relation (SEAM-VOICE take-voice-*): another voice for a positive, the source's voice for its sham.
VOICE_DONOR_RELATIONS = ("other-voice", "same-voice")
# What a variant may need of its source (`needs`), and how a refusal names it.
NEED_DESCRIPTIONS = {
    "words": "word intervals (from the aligner, on N1 and N2 only)",
    "pauses": "declared pause intervals",
    "script": "a procedural script to re-render",
    "voice": "a procedural render voice",
    "seams": "long-form seam offsets",
    "donor": "a speaker-labelled donor recording (another speaker of the same language and gender, or another "
             "utterance of the source speaker for a sham)",
    "voice-donor": "a voice donor (another long-form take of another voice of the same language, or of the source's "
                   "voice for a sham)",
}
DONOR_NEEDS = frozenset({"donor", "voice-donor"})


class InjectorNotApplicable(ValueError):
    """The variant needs something this source lacks; it is not run on it."""


@dataclass(frozen=True)
class Variant:
    name: str
    severity: str
    parameters: Mapping[str, Any]


@dataclass(frozen=True)
class Injector:
    injector_id: str
    version: int
    defect: str
    classes: tuple[str, ...]
    description: str
    variants: tuple[Variant, ...]
    # (source, parameters, rng[, donor]) -> (samples, labels[, output seams]); the donor is passed only to
    # a variant that needs one, and without output seams the source's stand when the length is kept.
    apply: Callable[..., tuple] = field(repr=False)
    # Word-free variants for recorded takes (N3). They stay out of `variants`
    # and `describe`, so the catalog, M1 and the procedural goldens are as before.
    recording_variants: tuple[Variant, ...] = ()

    @property
    def key(self) -> str:
        return f"{self.injector_id}@{self.version}"

    def variant(self, name: str) -> Variant:
        for variant in (*self.variants, *self.recording_variants):
            if variant.name == name:
                return variant
        raise KeyError(f"{self.key} has no variant {name!r}")

    def describe(self) -> dict:
        return {"injector": self.key, "defect": self.defect, "classes": list(self.classes),
                "mechanism": MECHANISM, "description": self.description,
                "variants": [{"name": variant.name, "severity": variant.severity,
                              "parameters": dict(variant.parameters)} for variant in self.variants]}


@dataclass(frozen=True)
class Injection:
    injector: str
    variant: str
    severity: str
    parameters: dict
    seed: int
    source_family: str
    source_digest: str
    samples: np.ndarray
    labels: tuple[dict, ...]
    digest: str
    # The donor recording's PCM digest, for a variant that splices one.
    donor_digest: str | None = None
    # The output's long-form seam offsets: the source's, moved by the edit; () when the edit moves the
    # timeline in a way no seam mapping follows (a tempo change, a word-level splice).
    seams: tuple[int, ...] = ()

    @property
    def positive(self) -> bool:
        return self.severity not in NON_DEFECT_SEVERITIES

    def recipe(self) -> dict:
        recipe = {"schema": "vocello.audioqc.injection-recipe/1", "catalogVersion": CATALOG_VERSION,
                  "mechanism": MECHANISM, "injector": self.injector, "variant": self.variant,
                  "severity": self.severity, "parameters": self.parameters, "seed": self.seed,
                  "sourceFamily": self.source_family, "sourcePCMSHA256": self.source_digest,
                  "outputPCMSHA256": self.digest, "labels": list(self.labels)}
        if self.donor_digest is not None:
            recipe["donorPCMSHA256"] = self.donor_digest
        return recipe


# --------------------------------------------------------------------------- #
# Signal helpers
# --------------------------------------------------------------------------- #

def _samples(ms: float, rate: int) -> int:
    return int(round(ms * rate / 1000.0))


def _fade(rate: int) -> int:
    return _samples(SPLICE_FADE_MS, rate)


def _room_tone(rng: SeededStream, count: int) -> np.ndarray:
    return ROOM_TONE_RMS * rng.normal(count)


def _speech_rms(source: Fixture) -> float:
    spans = [source.samples[start:end] for start, end in source.words]
    speech = np.concatenate(spans) if spans else source.samples
    return float(np.sqrt(np.mean(speech ** 2))) if speech.size else 0.0


def boundaries(source: Fixture) -> list[int]:
    """Cut points around each word: word i spans [b[i], b[i + 1]), cuts sit mid-gap."""
    words = source.words
    if not words:
        raise ValueError(f"{source.fixture_id} has no word intervals")
    cuts = [words[0][0] // 2]
    for (_, end), (start, _) in zip(words, words[1:]):
        cuts.append((end + start) // 2)
    cuts.append((words[-1][1] + source.samples.size) // 2)
    return cuts


def join(segments: list[np.ndarray], fade: int) -> tuple[np.ndarray, list[int]]:
    """Concatenate with linear crossfades; returns the output and each join's start."""
    output = np.asarray(segments[0], dtype=np.float64)
    starts: list[int] = []
    for segment in segments[1:]:
        segment = np.asarray(segment, dtype=np.float64)
        overlap = min(fade, output.size, segment.size)
        starts.append(output.size - overlap)
        if overlap == 0:
            output = np.concatenate([output, segment])
            continue
        ramp = (np.arange(overlap) + 0.5) / overlap
        mixed = output[output.size - overlap:] * (1.0 - ramp) + segment[:overlap] * ramp
        output = np.concatenate([output[:output.size - overlap], mixed, segment[overlap:]])
    return output, starts


def replace_span(base: np.ndarray, piece: np.ndarray, start: int, fade: int) -> np.ndarray:
    """Length-preserving replacement of base[start:start + len(piece)], crossfaded at both edges."""
    output = np.array(base, dtype=np.float64)
    length = piece.size
    end = start + length
    output[start:end] = piece
    overlap = min(fade, length // 2)
    if overlap:
        ramp = (np.arange(overlap) + 0.5) / overlap
        output[start:start + overlap] = base[start:start + overlap] * (1.0 - ramp) + piece[:overlap] * ramp
        output[end - overlap:end] = piece[length - overlap:] * (1.0 - ramp) + base[end - overlap:end] * ramp
    return output


def resample(samples: np.ndarray, ratio: float) -> np.ndarray:
    """Read the input at positions j * ratio with a Hann-windowed sinc (anti-aliased when ratio > 1)."""
    if ratio <= 0:
        raise ValueError("ratio must be positive")
    count = int(math.floor((samples.size - 1) / ratio)) + 1 if samples.size else 0
    cutoff = min(1.0, 1.0 / ratio)
    taps = np.arange(-SINC_HALF_WIDTH + 1, SINC_HALF_WIDTH + 1)
    padded = np.concatenate([np.zeros(SINC_HALF_WIDTH), samples, np.zeros(SINC_HALF_WIDTH + 1)])
    output = np.empty(count)
    for block in range(0, count, 8_192):
        positions = np.arange(block, min(count, block + 8_192)) * ratio
        base = np.floor(positions).astype(np.int64)
        distance = (positions - base)[:, None] - taps[None, :]
        window = 0.5 + 0.5 * np.cos(np.pi * distance / (SINC_HALF_WIDTH + 1))
        kernel = cutoff * np.sinc(cutoff * distance) * window
        values = padded[base[:, None] + taps[None, :] + SINC_HALF_WIDTH]
        output[block:block + positions.size] = (kernel * values).sum(axis=1)
    return output


def ola_stretch(samples: np.ndarray, factor: float) -> np.ndarray:
    """Overlap-add time stretch by `factor` (output length ~ input x factor), pitch kept."""
    if factor <= 0:
        raise ValueError("factor must be positive")
    length = int(round(samples.size * factor))
    half = OLA_WINDOW // 2
    frames = (length + OLA_WINDOW) // OLA_HOP + 1
    synthesis = np.arange(frames) * OLA_HOP
    analysis = np.round(synthesis / factor).astype(np.int64)
    padded = np.concatenate([np.zeros(half), samples, np.zeros(int(analysis[-1]) + OLA_WINDOW)])
    window = 0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(OLA_WINDOW) / OLA_WINDOW)
    output = np.zeros(int(synthesis[-1]) + OLA_WINDOW)
    weight = np.zeros_like(output)
    offsets = np.arange(OLA_WINDOW)
    np.add.at(output, synthesis[:, None] + offsets[None, :], padded[analysis[:, None] + offsets[None, :]] * window)
    np.add.at(weight, synthesis[:, None] + offsets[None, :], np.broadcast_to(window, (frames, OLA_WINDOW)))
    stretched = np.where(weight > 1e-6, output / np.maximum(weight, 1e-6), 0.0)
    return stretched[half:half + length]


def pitch_shift(samples: np.ndarray, semitones: float) -> np.ndarray:
    """Shift pitch and formants together by `semitones`, keeping the length."""
    ratio = 2.0 ** (semitones / 12.0)
    moved = resample(samples, ratio)
    stretched = ola_stretch(moved, samples.size / max(moved.size, 1))
    if stretched.size < samples.size:
        stretched = np.concatenate([stretched, np.zeros(samples.size - stretched.size)])
    return stretched[:samples.size]


def _longest_word(source: Fixture) -> tuple[int, int]:
    return max(source.words, key=lambda span: (span[1] - span[0], -span[0]))


def _word_index(position: str, count: int, words: int) -> int:
    if count > words - 1:
        # A refusal, not a failure: a recorded take may carry fewer aligned words.
        raise InjectorNotApplicable(f"needs more than {count} words")
    if position == "start":
        return 0
    if position == "middle":
        return (words - count) // 2
    if position == "end":
        return words - count
    raise ValueError(f"unknown position {position!r}")


def _placement(source: Fixture, placement: str) -> np.ndarray:
    rate = source.sample_rate
    margin = _samples(5.0, rate)
    size = source.samples.size
    if placement == "any":
        return np.arange(_samples(10.0, rate), max(_samples(10.0, rate) + 1, size - _samples(10.0, rate)))
    spans = []
    if placement == "voiced":
        spans = [(start + margin, end - margin) for start, end in source.words]
    elif placement == "quiet":
        edges = [0, *[value for span in source.words for value in span], size]
        spans = [(edges[i] + margin, edges[i + 1] - margin) for i in range(0, len(edges), 2)]
    else:
        raise ValueError(f"unknown placement {placement!r}")
    indices = [np.arange(start, end) for start, end in spans if end > start]
    return np.concatenate(indices) if indices else np.arange(size)


# --------------------------------------------------------------------------- #
# Injectors
# --------------------------------------------------------------------------- #

def _click(source: Fixture, parameters: dict, rng: SeededStream) -> tuple[np.ndarray, list[dict]]:
    output = np.array(source.samples)
    candidates = _placement(source, parameters["placement"])
    events = max(1, int(round(parameters["ratePerSecond"] * source.duration_seconds)))
    clustered = parameters["clustered"]
    groups = max(1, events // 3) if clustered else events
    picks = np.sort(candidates[rng.integers(candidates.size, groups)])
    signs = np.where(rng.uniform(groups) < 0.5, -1.0, 1.0)
    width = parameters["widthSamples"]
    amplitude = parameters["amplitude"]
    labels = []
    seen: set[int] = set()
    for pick, sign in zip(picks, signs):
        for offset in ((0, 96, 192) if clustered else (0,)):
            start = int(pick) + offset
            if start in seen or start + width > output.size:
                continue
            seen.add(start)
            output[start:start + width] += sign * amplitude
            if amplitude > 0:
                labels.append({"kind": "click", "startSample": start, "endSample": start + width})
    return output, sorted(labels, key=lambda label: label["startSample"])


def _dropout(source: Fixture, parameters: dict, rng: SeededStream) -> tuple[np.ndarray, list[dict]]:
    rate = source.sample_rate
    length = _samples(parameters["durationMS"], rate)
    if parameters.get("mode") == "natural-pause":
        # The matched control: the source's first declared (punctuation) pause
        # re-timed to exactly the dropout's length, room tone throughout, so a
        # natural pause of equal length sits where the text puts a pause.
        if not source.pauses:
            raise InjectorNotApplicable(f"{source.fixture_id} declares no pause")
        first, last = source.pauses[0]
        output, _ = join([source.samples[:first], _room_tone(rng, length), source.samples[last:]], 0)
        return output, []
    placement = parameters["placement"]
    if placement == "centre":
        # Recorded takes: the span sits at the take's centre, a margin clear of
        # either end, wherever its words fall (none are known).
        if length + 2 * _samples(CENTRE_MARGIN_MS, rate) > source.samples.size:
            raise InjectorNotApplicable(f"{source.fixture_id} is shorter than the span and its margins")
        start = (source.samples.size - length) // 2
    else:
        if placement == "intra-word":
            first, last = _longest_word(source)
            start = (first + last) // 2 - length // 2
        elif placement == "interior":
            first, last = source.words[0][0], source.words[-1][1]
            start = (first + last) // 2 - length // 2
        elif placement == "pause":
            if not source.pauses:
                raise InjectorNotApplicable(f"{source.fixture_id} declares no pause")
            first, last = source.pauses[0]
            start = (first + last) // 2 - length // 2
        else:
            raise ValueError(f"unknown placement {placement!r}")
        # Keep the span interior: it ends at least 100 ms before the last word does,
        # unless the speech is shorter than the span itself.
        latest = source.words[-1][1] - _samples(100.0, rate) - length
        start = max(source.words[0][0], min(start, latest))
    end = min(start + length, source.samples.size)
    attenuation = parameters["attenuationDB"]
    gain = 0.0 if attenuation is None else 10.0 ** (attenuation / 20.0)
    size = source.samples.size
    multiplier = np.ones(size)
    multiplier[start:end] = gain
    ramp = _samples(parameters["rampMS"], rate)
    lead, trail = start, end
    if ramp:
        steps = np.arange(1, ramp + 1) / (ramp + 1)
        lead = max(0, start - ramp)
        multiplier[lead:start] = (1.0 - steps * (1.0 - gain))[ramp - (start - lead):]
        trail = min(size, end + ramp)
        multiplier[end:trail] = (gain + steps * (1.0 - gain))[:trail - end]
    output = source.samples * multiplier
    # The label covers every sample the multiplier moves, ramps included; the
    # full-depth span is recorded beside it.
    labels = [{"kind": "dropout", "startSample": lead, "endSample": trail,
               "fullDepthStartSample": start, "fullDepthEndSample": end}] if gain < 1.0 else []
    return output, labels


def _clip_level(samples: np.ndarray, fraction: float) -> tuple[float, int]:
    """The magnitude that `fraction` of the samples exceed, and how many do."""
    magnitude = np.sort(np.abs(samples))[::-1]
    beyond = int(math.ceil(fraction * magnitude.size))
    level = float(magnitude[min(beyond, magnitude.size - 1)])
    return level, int(np.count_nonzero(np.abs(samples) > level))


def _clip(source: Fixture, parameters: dict, rng: SeededStream) -> tuple[np.ndarray, list[dict]]:
    samples = source.samples
    mode = parameters["mode"]
    if mode == "peak-normalize":
        # The level control: a whole-file gain that brings the peak to full
        # scale and clips nothing. It is not a sham (every sample moves); it
        # separates a detector's response to level from its response to clipping.
        peak = float(np.max(np.abs(samples)))
        return samples * (parameters["targetPeak"] / max(peak, 1e-12)), []
    level, over = _clip_level(samples, parameters["clippedFraction"])
    if parameters["clippedFraction"] > 0 and over == 0:
        # The loudest samples share one magnitude (the source is already flat at its peak), so
        # none lies above the level: every mode would change and label nothing. Only these
        # sources change; every other output stays byte-identical under catalog version 2.
        raise InjectorNotApplicable(f"{source.fixture_id} is already flat at its peak: nothing lies above "
                                    "the clip level")
    magnitude = np.abs(samples)
    if mode == "overdrive":
        # Level beyond full scale, nothing flattened: the physical over-range
        # event. The gain moves every sample, so the label is the whole take.
        gain = 1.0 / max(level, 1e-12)
        output = samples * gain
        labels = [{"kind": "over-range", "startSample": 0, "endSample": samples.size,
                   "gainDB": round(20.0 * math.log10(gain), 6), "overRangeSamples": over}] if over else []
        return output, labels
    if mode == "hard":
        # Flat tops at the level the fraction exceeds, no gain: exactly the
        # samples above it change. Fraction 0 changes nothing (the sham).
        output = np.clip(samples, -level, level)
    elif mode == "soft-knee":
        # Identity up to the knee (the same level), then a tanh squash toward
        # an asymptote SOFT_KNEE_HEADROOM above it: continuous in value and
        # slope, bounded, and it changes exactly the samples above the knee.
        span = SOFT_KNEE_HEADROOM * level
        squashed = level + span * np.tanh((magnitude - level) / max(span, 1e-12))
        output = np.where(magnitude > level, np.sign(samples) * squashed, samples)
    else:
        raise ValueError(f"unknown clipping mode {mode!r}")
    changed = np.flatnonzero(magnitude > level)
    labels = [{"kind": "clipping", "startSample": int(changed[0]), "endSample": int(changed[-1]) + 1,
               "clippedSamples": int(changed.size), "mode": mode,
               "levelDBFS": round(20.0 * math.log10(max(level, 1e-12)), 6)}] if changed.size else []
    return output, labels


def _dc(source: Fixture, parameters: dict, rng: SeededStream) -> tuple[np.ndarray, list[dict]]:
    offset = parameters["offset"]
    labels = [{"kind": "dc-offset", "startSample": 0, "endSample": source.samples.size}] if offset else []
    return source.samples + offset, labels


def _level(source: Fixture, parameters: dict, rng: SeededStream) -> tuple[np.ndarray, list[dict]]:
    gain = parameters["gainDB"]
    labels = [{"kind": "level", "startSample": 0, "endSample": source.samples.size}] if gain else []
    return source.samples * 10.0 ** (gain / 20.0), labels


def _noise(source: Fixture, parameters: dict, rng: SeededStream) -> tuple[np.ndarray, list[dict]]:
    count = source.samples.size
    white = rng.normal(count)
    kind = parameters["kind"]
    if kind == "white":
        noise = white
    elif kind == "hum":
        time = np.arange(count) / source.sample_rate
        noise = sum(weight * np.sin(2.0 * math.pi * 50.0 * harmonic * time)
                    for harmonic, weight in ((1, 1.0), (2, 0.5), (3, 0.3)))
    else:
        raise ValueError(f"unknown noise kind {kind!r}")
    snr = parameters["snrDB"]
    if snr is None:
        return np.array(source.samples), []
    # `take`: against the whole take's RMS, pauses included (recorded takes,
    # whose speech spans are unknown); by default against the speech RMS.
    if parameters.get("snrReference", "speech") == "take":
        reference = float(np.sqrt(np.mean(source.samples ** 2)))
    else:
        reference = _speech_rms(source)
    scale = reference / 10.0 ** (snr / 20.0) / float(np.sqrt(np.mean(noise ** 2)))
    output = source.samples + scale * noise
    positive = snr < 60.0
    labels = [{"kind": "noise", "startSample": 0, "endSample": count}] if positive else []
    return output, labels


def _silence(source: Fixture, parameters: dict, rng: SeededStream) -> tuple[np.ndarray, list[dict]]:
    count = _samples(parameters["seconds"] * 1000.0, source.sample_rate)
    fill = np.zeros(count) if parameters["fill"] == "zeros" else _room_tone(rng, count)
    if parameters["position"] == "leading":
        output = np.concatenate([fill, source.samples])
        span = (0, count)
    elif parameters["position"] == "terminal":
        output = np.concatenate([source.samples, fill])
        span = (source.samples.size, source.samples.size + count)
    else:
        raise ValueError("position must be leading or terminal")
    labels = [{"kind": "silence", "startSample": span[0], "endSample": span[1]}] if count else []
    return output, labels


def _truncate(source: Fixture, parameters: dict, rng: SeededStream) -> tuple[np.ndarray, list[dict]]:
    if "keepFraction" in parameters:
        # Recorded takes: a hard cut at a fraction of the take's length. The cut
        # is sample-exact, but with no word interval known it cannot guarantee
        # that speech, rather than the trailing pause, was removed.
        size = source.samples.size
        cut = int(round(parameters["keepFraction"] * size))
        output = np.array(source.samples[:cut])
        fade = min(_samples(parameters["fadeMS"], source.sample_rate), output.size)
        if fade:
            output[output.size - fade:] *= np.linspace(1.0, 0.0, fade + 1)[1:]
        labels = [{"kind": "truncation", "startSample": cut, "endSample": cut, "removedSamples": size - cut,
                   "basis": "take-fraction"}] if cut < size else []
        return output, labels
    words = source.words
    removed = parameters["wordsRemoved"]
    partial = parameters["partialFraction"]
    size = source.samples.size
    if (removed or partial) and removed > len(words) - 1:
        raise InjectorNotApplicable(f"{source.fixture_id} has too few words to cut {removed}")
    if removed == 0 and partial == 0:
        cut = size
    elif partial == 0:
        cut = words[len(words) - removed][0]
    else:
        start, end = words[len(words) - 1 - removed]
        cut = end - int(round(partial * (end - start)))
    output = np.array(source.samples[:cut])
    fade = min(_samples(parameters["fadeMS"], source.sample_rate), output.size)
    if fade:
        output[output.size - fade:] *= np.linspace(1.0, 0.0, fade + 1)[1:]
    labels = [{"kind": "truncation", "startSample": cut, "endSample": cut, "removedSamples": size - cut}] \
        if cut < size else []
    return output, labels


def _run_on_take_end(source: Fixture, parameters: dict, rng: SeededStream) -> tuple[np.ndarray, list[dict]]:
    """Recorded takes: material appended after the take's last sample.

    With no word interval known, the repeated material is a `spanSeconds` span
    of the take's own middle; the sham appends room tone.
    """
    rate = source.sample_rate
    size = source.samples.size
    wanted = _samples(parameters["appendSeconds"] * 1000.0, rate)
    content = parameters["content"]
    if content == "room-tone":
        appended = [_room_tone(rng, wanted)]
    elif content == "repeat-span":
        span = _samples(parameters["spanSeconds"] * 1000.0, rate)
        if 2 * span > size:
            raise InjectorNotApplicable(f"{source.fixture_id} is shorter than twice the repeated span")
        start = (size - span) // 2
        appended = [source.samples[start:start + span]] * max(1, int(math.ceil(wanted / span)))
    else:
        raise ValueError(f"unknown run-on content {content!r}")
    output, starts = join([source.samples, *appended], _fade(rate))
    labels = [] if content == "room-tone" else [
        {"kind": "run-on", "startSample": starts[0], "endSample": int(output.size), "basis": "take-end"}]
    return output, labels


def _run_on(source: Fixture, parameters: dict, rng: SeededStream) -> tuple[np.ndarray, list[dict]]:
    if parameters.get("anchor") == "take-end":
        return _run_on_take_end(source, parameters, rng)
    rate = source.sample_rate
    cuts = boundaries(source)
    insert = min(source.samples.size, source.words[-1][1] + _samples(60.0, rate))
    wanted = _samples(parameters["appendSeconds"] * 1000.0, rate)
    content = parameters["content"]
    if content == "room-tone":
        appended = [_room_tone(rng, wanted)]
    else:
        tail = source.samples[cuts[-2]:insert]
        if content == "reversed-tail":
            tail = tail[::-1]
        elif content != "repeat-tail":
            raise ValueError(f"unknown run-on content {content!r}")
        appended = [tail] * max(1, int(math.ceil(wanted / max(tail.size, 1))))
    fade = _fade(rate)
    output, starts = join([source.samples[:insert], *appended, source.samples[insert:]], fade)
    labels = [] if content == "room-tone" else [
        {"kind": "run-on", "startSample": starts[0], "endSample": starts[-1]}]
    return output, labels


def _repeat(source: Fixture, parameters: dict, rng: SeededStream) -> tuple[np.ndarray, list[dict]]:
    cuts = boundaries(source)
    count, repeats = parameters["words"], parameters["repeats"]
    first = _word_index(parameters["position"], count, len(source.words))
    segment = source.samples[cuts[first]:cuts[first + count]]
    pieces = [source.samples[:cuts[first + count]], *([segment] * repeats), source.samples[cuts[first + count]:]]
    output, starts = join(pieces, _fade(source.sample_rate))
    labels = [{"kind": "repetition", "startSample": starts[0], "endSample": starts[-1],
               "repeats": repeats, "words": count}] if repeats else []
    return output, labels


def _delete(source: Fixture, parameters: dict, rng: SeededStream) -> tuple[np.ndarray, list[dict]]:
    cuts = boundaries(source)
    count = parameters["words"]
    first = _word_index(parameters["position"], count, len(source.words))
    fade = _fade(source.sample_rate)
    head, removed, tail = (source.samples[:cuts[first]], source.samples[cuts[first]:cuts[first + count]],
                           source.samples[cuts[first + count]:])
    if not parameters["remove"]:
        output, _ = join([head, removed, tail], fade)
        return output, []
    gap = _samples(parameters["gapMS"], source.sample_rate)
    output, starts = join([head, _room_tone(rng, gap), tail] if gap else [head, tail], fade)
    return output, [{"kind": "deletion", "startSample": starts[0], "endSample": starts[-1],
                     "deletedSamples": int(removed.size), "words": count}]


def _insert(source: Fixture, parameters: dict, rng: SeededStream) -> tuple[np.ndarray, list[dict]]:
    cuts = boundaries(source)
    words = len(source.words)
    at = _word_index(parameters["position"], 1, words)
    donors = [int(index) for index in rng.integers(words, 4)][:parameters["words"]]
    pieces = [source.samples[:cuts[at]], *[source.samples[cuts[index]:cuts[index + 1]] for index in donors],
              source.samples[cuts[at]:]]
    output, starts = join(pieces, _fade(source.sample_rate))
    labels = [{"kind": "insertion", "startSample": starts[0], "endSample": starts[-1],
               "words": len(donors)}] if donors else []
    return output, labels


def _pitch_segment(source: Fixture, start: int, length: int, semitones: float) -> np.ndarray:
    context = OLA_WINDOW
    low = max(0, start - context)
    high = min(source.samples.size, start + length + context)
    shifted = pitch_shift(source.samples[low:high], semitones)
    piece = shifted[start - low:start - low + length]
    return replace_span(source.samples, piece, start, _fade(source.sample_rate))


def _octave(source: Fixture, parameters: dict, rng: SeededStream) -> tuple[np.ndarray, list[dict]]:
    first, last = _longest_word(source)
    fade = _fade(source.sample_rate)
    length = min(_samples(parameters["durationMS"], source.sample_rate), last - first - 2 * fade)
    start = (first + last) // 2 - length // 2
    semitones = parameters["semitones"]
    output = _pitch_segment(source, start, length, semitones)
    labels = [{"kind": "pitch-jump", "startSample": start, "endSample": start + length}] if semitones else []
    return output, labels


def _pitch_break(source: Fixture, parameters: dict, rng: SeededStream) -> tuple[np.ndarray, list[dict]]:
    first, last = _longest_word(source)
    start = (first + last) // 2
    semitones = parameters["semitones"]
    output = _pitch_segment(source, start, last - start, semitones)
    labels = [{"kind": "pitch-break", "startSample": start, "endSample": last}] if semitones else []
    return output, labels


def _rate(source: Fixture, parameters: dict, rng: SeededStream) -> tuple[np.ndarray, list[dict]]:
    speed = parameters["speed"]
    output = ola_stretch(source.samples, 1.0 / speed)
    labels = [{"kind": "rate", "startSample": 0, "endSample": output.size}] if speed != 1.0 else []
    return output, labels


def _shift(source: Fixture, parameters: dict, rng: SeededStream) -> tuple[np.ndarray, list[dict]]:
    semitones = parameters["semitones"]
    output = pitch_shift(source.samples, semitones)
    labels = [{"kind": "pitch-formant-shift", "startSample": 0, "endSample": output.size}] if semitones else []
    return output, labels


def _swap(source: Fixture, parameters: dict, rng: SeededStream,
          donor: Fixture | None = None) -> tuple[np.ndarray, list[dict]] | tuple[np.ndarray, list[dict], tuple]:
    if "donor" in parameters:
        # A speaker-labelled recording (catalog version 3): a donor recording's words spliced in.
        return _donor_splice(source, donor, parameters, kind="identity-swap")
    if source.voice is None or source.script is None:
        raise ValueError("an identity swap needs a procedural source with a script and a voice")
    relation = parameters["relation"]
    donor = rerender(source, donor_voice(source.voice, relation), render_seed=parameters["renderSeed"])
    first, last = source.words[0][0], source.words[-1][1]
    length = min(_samples(parameters["durationMS"], source.sample_rate), last - first)
    position = parameters["position"]
    start = {"onset": first, "middle": (first + last) // 2 - length // 2, "end": last - length}[position]
    output = replace_span(source.samples, donor[start:start + length], start, _fade(source.sample_rate))
    labels = [{"kind": "identity-swap", "startSample": start, "endSample": start + length,
               "relation": relation}] if relation != "self" else []
    return output, labels


# --------------------------------------------------------------------------- #
# Catalog version 3
# --------------------------------------------------------------------------- #

def effective_bandwidth(samples: np.ndarray, rate: int) -> float | None:
    """The source's effective bandwidth in Hz (Stage 0's definition at SIG-BAND@1's constants).

    The highest bin of the long-term average spectrum of active frames within
    BAND_THRESHOLD_DB of its peak bin (DC excluded), as a frequency; None when
    no frame is active.
    """
    size = BAND_FFT_SIZE
    hop = rate // BAND_FRAMES_PER_SECOND
    count = (samples.size - size) // hop + 1 if hop > 0 and samples.size >= size else 0
    if count <= 0:
        return None
    window = 0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(size) / size)
    energy = float((window * window).sum())
    frames = samples[np.arange(size)[None, :] + hop * np.arange(count)[:, None]] * window[None, :]
    active = (frames * frames).sum(axis=1) / energy >= BAND_ACTIVE_MEAN_SQUARE
    if not active.any():
        return None
    spectrum = (np.abs(np.fft.rfft(frames[active], axis=1)) ** 2).sum(axis=0) / (energy * int(active.sum()))
    levels = 10.0 * np.log10(np.maximum(spectrum[1:], 1e-20))
    highest = int(np.flatnonzero(levels >= float(levels.max()) - BAND_THRESHOLD_DB).max()) + 1
    return highest * rate / size


def lowpass(samples: np.ndarray, cutoff_hz: float, rate: int, taps: int = BAND_TAPS) -> np.ndarray:
    """Zero-phase low-pass: a Blackman-windowed sinc of `taps` (odd) taps, unit DC gain, applied centred."""
    if taps < 3 or taps % 2 == 0:
        raise ValueError("taps must be odd and at least 3")
    half = taps // 2
    offsets = np.arange(-half, half + 1)
    normalized = cutoff_hz / rate
    kernel = 2.0 * normalized * np.sinc(2.0 * normalized * offsets)
    kernel = kernel * (0.42 + 0.5 * np.cos(np.pi * offsets / half) + 0.08 * np.cos(2.0 * np.pi * offsets / half))
    kernel /= kernel.sum()
    return np.convolve(samples, kernel)[half:half + samples.size]


def _band_limit(source: Fixture, parameters: dict, rng: SeededStream) -> tuple[np.ndarray, list[dict]]:
    rate = source.sample_rate
    bandwidth = effective_bandwidth(source.samples, rate)
    if bandwidth is None:
        raise InjectorNotApplicable(f"{source.fixture_id} has no active frame, so no measured band to cut")
    fraction = parameters["bandwidthFraction"]
    cutoff = min(fraction * bandwidth, BAND_CEILING_FRACTION * rate / 2.0)
    positive = fraction < 1.0
    if positive and cutoff < BAND_MINIMUM_CUTOFF_HZ:
        raise InjectorNotApplicable(f"{source.fixture_id}'s effective bandwidth of {bandwidth:.0f} Hz puts the cutoff "
                                    f"below {BAND_MINIMUM_CUTOFF_HZ:.0f} Hz")
    output = lowpass(source.samples, cutoff, rate, parameters["taps"])
    if not positive:
        return output, []
    after = effective_bandwidth(output, rate)
    if after is None or after >= bandwidth:
        # The source had no content the measure sees above the cutoff: nothing was cut.
        raise InjectorNotApplicable(f"{source.fixture_id}: a low-pass at {cutoff:.0f} Hz leaves its measured "
                                    "bandwidth unchanged")
    return output, [{"kind": "band-limit", "startSample": 0, "endSample": int(output.size),
                     "cutoffHz": round(cutoff, 3), "sourceBandwidthHz": round(bandwidth, 3),
                     "outputBandwidthHz": round(after, 3)}]


def _erratic(source: Fixture, parameters: dict, rng: SeededStream) -> tuple[np.ndarray, list[dict]]:
    """Seeded 150-300 ms spans over the whole take, each shifted up or down, crossfaded into each other."""
    rate = source.sample_rate
    size = source.samples.size
    shortest = _samples(parameters["minimumSpanMS"], rate)
    longest = _samples(parameters["maximumSpanMS"], rate)
    starts = [0]
    while True:
        following = starts[-1] + shortest + rng.integer(longest - shortest + 1)
        if following >= size:
            break
        starts.append(following)
    if len(starts) > 1 and size - starts[-1] < shortest:
        starts.pop()  # a remainder shorter than a span joins the span before it
    if len(starts) < 2:
        raise InjectorNotApplicable(f"{source.fixture_id} is shorter than two spans")
    ends = [*starts[1:], size]
    signs = np.where(rng.uniform(len(starts)) < 0.5, -1.0, 1.0)
    magnitude = parameters["semitones"]
    fade = _fade(rate)
    lead, lag = fade // 2, fade - fade // 2
    rise = (np.arange(fade) + 0.5) / fade
    output = np.zeros(size)
    last = len(starts) - 1
    spans = []
    for index, (start, end, sign) in enumerate(zip(starts, ends, signs)):
        semitones = float(sign * magnitude)
        # Each span reaches half a fade into its neighbours; the two ramps there sum to one.
        first = start - lead if index else 0
        final = end + lag if index < last else size
        low, high = max(0, first - OLA_WINDOW), min(size, final + OLA_WINDOW)
        shifted = pitch_shift(source.samples[low:high], semitones)
        weights = np.ones(final - first)
        if index:
            weights[:fade] = rise
        if index < last:
            weights[weights.size - fade:] = 1.0 - rise
        output[first:final] += shifted[first - low:final - low] * weights
        spans.append([int(start), int(end), semitones])
    labels = [{"kind": "erratic-pitch", "startSample": 0, "endSample": size, "semitones": magnitude,
               "spans": spans}] if magnitude else []
    return output, labels


def _shift_seams(seams: tuple[int, ...], start: int, end: int, delta: int) -> tuple[int, ...]:
    """Seams after an edit that replaced [start, end) and moved what follows by `delta` (inside ones go)."""
    return tuple(sorted({seam for seam in seams if seam <= start} | {seam + delta for seam in seams if seam >= end}))


def _pick_seam(source: Fixture, rng: SeededStream, room: int) -> tuple[int, int]:
    """A seeded seam whose following segment holds at least `room` samples: (seam, segment end)."""
    bounds = sorted({seam for seam in source.seams if 0 < seam < source.samples.size})
    ends = [*bounds[1:], source.samples.size]
    usable = [(seam, end) for seam, end in zip(bounds, ends) if end - seam >= room]
    if not usable:
        raise InjectorNotApplicable(f"{source.fixture_id} has no seam followed by {room} samples of its segment")
    return usable[rng.integer(len(usable))]


def _aligned_splice(source: Fixture, relation: str, render_seed: int, start: int, length: int) -> np.ndarray:
    """IDN-SWAP's construction: [start, start + length) from the script re-rendered by a second voice."""
    if source.voice is None or source.script is None:
        raise ValueError("an aligned splice needs a procedural source with a script and a voice")
    donor = rerender(source, donor_voice(source.voice, relation), render_seed=render_seed)
    return replace_span(source.samples, donor[start:start + length], start, _fade(source.sample_rate))


def _closest(cuts: list[int], first: int, target: int) -> int:
    """The last cut index after `first` whose span from cuts[first] is closest to `target` (fewest words on a tie)."""
    return min(range(first + 1, len(cuts)), key=lambda last: (abs(cuts[last] - cuts[first] - target), last))


def _source_span(source: Fixture, position: str, target: int | None,
                 seam: tuple[int, int] | None) -> tuple[int, int]:
    """[start, end) the donor replaces: whole words closest to `target` at a position, or from a seam."""
    cuts = boundaries(source)
    if position == "seam":
        start, segment_end = seam
        if target is None:
            return start, segment_end
        ends = [cut for cut in cuts if start < cut < segment_end] + [segment_end]
        return start, min(ends, key=lambda cut: (abs(cut - start - target), cut))
    words = len(cuts) - 1
    best: tuple[int, int, int] | None = None
    for count in range(1, words + 1):
        first = {"onset": 0, "middle": (words - count) // 2, "end": words - count}[position]
        error = abs(cuts[first + count] - cuts[first] - target)
        if best is None or error < best[0]:
            best = (error, cuts[first], cuts[first + count])
    return best[1], best[2]


def _rms(samples: np.ndarray) -> float:
    return float(np.sqrt(np.mean(samples ** 2))) if samples.size else 0.0


def _donor_splice(source: Fixture, donor: Fixture, parameters: dict, *, kind: str,
                  seam: tuple[int, int] | None = None) -> tuple[np.ndarray, list[dict], tuple[int, ...]]:
    """A recording's words replaced by a donor recording's opening words, at aligned word boundaries.

    The source span is the whole words closest to `durationMS` at the position
    (or from a seam to the word cut closest to it, or to the segment's end);
    the donor gives its words from its first, closest in length, scaled to the
    replaced span's RMS and spliced with the catalog's 5 ms crossfades. The
    label covers every output sample the donor reaches; outside it the output
    is the source, moved by the length change after it.
    """
    if donor is None:
        raise ValueError("a donor variant needs its donor")
    if donor.sample_rate != source.sample_rate:
        raise ValueError("the donor and the source must share a sample rate")
    if not donor.words:
        raise InjectorNotApplicable(f"{source.fixture_id}: its donor has no word intervals")
    rate = source.sample_rate
    duration = parameters["durationMS"]
    target = None if duration is None else _samples(duration, rate)
    start, end = _source_span(source, parameters["position"], target, seam)
    donor_cuts = boundaries(donor)
    last = _closest(donor_cuts, 0, end - start)
    piece = np.asarray(donor.samples[donor_cuts[0]:donor_cuts[last]], dtype=np.float64)
    level = _rms(piece)
    piece = piece * (_rms(source.samples[start:end]) / level if level > 0 else 1.0)
    head, tail = source.samples[:start], source.samples[end:]
    fade = _fade(rate)
    output, starts = join([head, piece, tail], fade)
    first_overlap = min(fade, head.size, piece.size)
    second_overlap = min(fade, head.size + piece.size - first_overlap, tail.size)
    delta = int(output.size) - int(source.samples.size)
    seams = _shift_seams(source.seams, start, end, delta)
    relation = parameters["donor"]
    if relation not in DONOR_RELATIONS:
        raise ValueError(f"unknown donor relation {relation!r}")
    if relation != "other-speaker":
        return output, [], seams
    label = {"kind": kind, "startSample": int(starts[0]), "endSample": int(starts[-1] + second_overlap),
             "position": parameters["position"], "donorRelation": relation, "replacedSamples": int(end - start),
             "donorSamples": int(piece.size)}
    if seam is not None:
        label["seamSample"] = int(start)
    return output, [label], seams


def _onset(source: Fixture, parameters: dict, rng: SeededStream,
           donor: Fixture | None = None) -> tuple[np.ndarray, list[dict]] | tuple[np.ndarray, list[dict], tuple]:
    if "donor" in parameters:
        return _donor_splice(source, donor, parameters, kind="identity-swap")
    first, last = source.words[0][0], source.words[-1][1]
    length = min(_samples(parameters["durationMS"], source.sample_rate), last - first)
    relation = parameters["relation"]
    output = _aligned_splice(source, relation, parameters["renderSeed"], first, length)
    labels = [{"kind": "identity-swap", "startSample": first, "endSample": first + length, "relation": relation,
               "position": "onset"}] if relation != "self" else []
    return output, labels


def _seam_disc(source: Fixture, parameters: dict, rng: SeededStream) -> tuple[np.ndarray, list[dict], tuple]:
    rate = source.sample_rate
    seam, _end = _pick_seam(source, rng, _samples(SEAM_DISC_MAXIMUM_MS, rate) + 1)
    removed = _samples(parameters["removeMS"], rate)
    output = np.concatenate([source.samples[:seam], source.samples[seam + removed:]])
    labels = [{"kind": "seam-discontinuity", "startSample": seam, "endSample": seam, "seamSample": seam,
               "removedSamples": removed}] if removed else []
    return output, labels, _shift_seams(source.seams, seam, seam + removed, -removed)


def replace_resized(base: np.ndarray, piece: np.ndarray, start: int, end: int, fade: int) -> np.ndarray:
    """base[start:end] replaced by `piece` of any length, crossfaded inside the replaced span.

    The piece's first and last `overlap` samples are mixed with the replaced
    span's own first and last samples (as `replace_span` does), so every output
    sample outside [start, start + piece.size) is the source's, the ones after
    it moved by the length change. With a piece of the span's length it is
    `replace_span`.
    """
    base = np.asarray(base, dtype=np.float64)
    mixed = np.array(piece, dtype=np.float64)
    overlap = min(fade, mixed.size // 2, (end - start) // 2)
    if overlap:
        ramp = (np.arange(overlap) + 0.5) / overlap
        mixed[:overlap] = base[start:start + overlap] * (1.0 - ramp) + mixed[:overlap] * ramp
        mixed[mixed.size - overlap:] = mixed[mixed.size - overlap:] * (1.0 - ramp) + base[end - overlap:end] * ramp
    return np.concatenate([base[:start], mixed, base[end:]])


def _active_rms(samples: np.ndarray) -> float:
    """The RMS over non-zero samples: a long-form assembler's inserted pauses are exact zeros."""
    return _rms(samples[samples != 0.0])


def _voice_splice(source: Fixture, donor: Fixture | None, parameters: dict, *,
                  seam: tuple[int, int]) -> tuple[np.ndarray, list[dict], tuple[int, ...]]:
    """SEAM-VOICE on a long-form take from a voice donor: the donor's own audio from the start of a segment.

    The source span is the segment after the seeded seam (to the next seam or
    the take's end) or its first `durationMS`. The donor gives the segment
    after one of its own seams: the whole segment for a whole-segment span,
    else its first samples of the span's length, among its segments at least
    that long (at least SEAM_VOICE_MINIMUM_MS for a whole segment), the one
    closest in length to the source's segment (the earliest on a tie). It is
    scaled to the replaced span's RMS over non-zero samples and crossfaded over
    5 ms inside the span (`replace_resized`), so its first sample lands on the
    seam, the label covers exactly the replaced samples, and the seams after
    the span move by the length change (a mild or moderate span keeps it).
    """
    if donor is None:
        raise ValueError("a voice-donor variant needs its donor")
    if donor.sample_rate != source.sample_rate:
        raise ValueError("the donor and the source must share a sample rate")
    relation = parameters["donor"]
    if relation not in VOICE_DONOR_RELATIONS:
        raise ValueError(f"unknown voice donor relation {relation!r}")
    rate = source.sample_rate
    start, segment_end = seam
    duration = parameters["durationMS"]
    end = segment_end if duration is None else min(start + _samples(duration, rate), segment_end)
    room = _samples(SEAM_VOICE_MINIMUM_MS, rate) if duration is None else end - start
    bounds = sorted({offset for offset in donor.seams if 0 < offset < donor.samples.size})
    ends = [*bounds[1:], donor.samples.size]
    usable = [(offset, until) for offset, until in zip(bounds, ends) if until - offset >= room]
    if not usable:
        raise InjectorNotApplicable(f"{source.fixture_id}: its donor has no seam followed by {room} samples of "
                                    "its segment")
    wanted = segment_end - start
    donor_seam, donor_end = min(usable, key=lambda span: (abs(span[1] - span[0] - wanted), span[0]))
    piece = np.asarray(donor.samples[donor_seam:donor_end if duration is None else donor_seam + end - start],
                       dtype=np.float64)
    level = _active_rms(piece)
    piece = piece * (_active_rms(source.samples[start:end]) / level if level > 0 else 1.0)
    output = replace_resized(source.samples, piece, start, end, _fade(rate))
    seams = _shift_seams(source.seams, start, end, int(piece.size) - (end - start))
    if relation != "other-voice":
        return output, [], seams
    return output, [{"kind": "seam-voice", "startSample": int(start), "endSample": int(start + piece.size),
                     "seamSample": int(start), "position": "seam", "donorRelation": relation,
                     "replacedSamples": int(end - start), "donorSamples": int(piece.size),
                     "donorSeamSample": int(donor_seam)}], seams


def _seam_voice(source: Fixture, parameters: dict, rng: SeededStream,
                donor: Fixture | None = None) -> tuple[np.ndarray, list[dict], tuple]:
    rate = source.sample_rate
    seam, segment_end = _pick_seam(source, rng, _samples(SEAM_VOICE_MINIMUM_MS, rate))
    if parameters.get("donor") in VOICE_DONOR_RELATIONS:
        return _voice_splice(source, donor, parameters, seam=(seam, segment_end))
    if "donor" in parameters:
        return _donor_splice(source, donor, parameters, kind="seam-voice", seam=(seam, segment_end))
    duration = parameters["durationMS"]
    length = segment_end - seam if duration is None else min(_samples(duration, rate), segment_end - seam)
    relation = parameters["relation"]
    output = _aligned_splice(source, relation, parameters["renderSeed"], seam, length)
    labels = [{"kind": "seam-voice", "startSample": seam, "endSample": seam + length, "seamSample": seam,
               "relation": relation}] if relation != "self" else []
    return output, labels, source.seams


def _variants(sham: dict, sweep: dict[str, dict], *, controls: dict[str, dict] | None = None,
              extra: dict[str, tuple[str, dict]] | None = None) -> tuple[Variant, ...]:
    variants = [Variant("sham", "sham", sham)]
    variants += [Variant(name, "control", parameters) for name, parameters in (controls or {}).items()]
    variants += [Variant(name, name, parameters) for name, parameters in sweep.items()]
    variants += [Variant(name, severity, parameters) for name, (severity, parameters) in (extra or {}).items()]
    return tuple(variants)


def _take_variants(sham: dict | None, sweep: dict[str, dict], *, prefix: str = "take") -> tuple[Variant, ...]:
    """Recording variants `<prefix>-<severity>`: a sham (when the catalog's needs a word) and the sweep."""
    variants = [Variant(f"{prefix}-sham", "sham", sham)] if sham is not None else []
    return tuple(variants + [Variant(f"{prefix}-{name}", name, parameters) for name, parameters in sweep.items()])


def _catalog() -> dict[str, Injector]:
    click = {"widthSamples": 1, "placement": "voiced", "clustered": False}
    drop = {"placement": "interior", "attenuationDB": None, "rampMS": 0.0, "mode": "attenuate"}
    swap = {"position": "middle", "renderSeed": 0}
    take_click = {**click, "placement": "any"}
    take_drop = {**drop, "placement": "centre"}
    take_noise = {"kind": "white", "snrReference": "take"}
    take_run_on = {"anchor": "take-end", "spanSeconds": 0.5}
    band = {"taps": BAND_TAPS}
    erratic = {"minimumSpanMS": 150.0, "maximumSpanMS": 300.0}
    onset = {"renderSeed": 0}
    take_onset = {"position": "onset"}
    seam_voice = {"renderSeed": 0}
    take_seam = {"position": "seam"}
    injectors = [
        Injector("SIG-CLICK", 1, "clicks", ("A",),
                 "Impulses of 1-3 samples at a rate per second, voiced, quiet or anywhere; "
                 "sham: the moderate positions at zero amplitude.",
                 _variants({**click, "amplitude": 0.0, "ratePerSecond": 5.0},
                           {"mild": {**click, "amplitude": 0.2, "ratePerSecond": 1.0},
                            "moderate": {**click, "amplitude": 0.5, "ratePerSecond": 5.0},
                            "severe": {**click, "amplitude": 1.0, "ratePerSecond": 50.0}},
                           extra={"quiet-clustered": ("moderate", {"widthSamples": 3, "placement": "quiet",
                                                                   "clustered": True, "amplitude": 0.5,
                                                                   "ratePerSecond": 5.0})}),
                 _click,
                 recording_variants=_take_variants(
                     {**take_click, "amplitude": 0.0, "ratePerSecond": 5.0},
                     {"mild": {**take_click, "amplitude": 0.2, "ratePerSecond": 1.0},
                      "moderate": {**take_click, "amplitude": 0.5, "ratePerSecond": 5.0},
                      "severe": {**take_click, "amplitude": 1.0, "ratePerSecond": 50.0}})),
        Injector("SIG-DROP", 2, "dropout", ("A", "C"),
                 "A span zeroed or attenuated inside a word, the interior or a pause, with optional ramps "
                 "that the label includes; sham: the moderate span at 0 dB; control: the first declared "
                 "punctuation pause re-timed to the same length (sources with a declared pause only).",
                 _variants({**drop, "durationMS": 600.0, "attenuationDB": 0.0},
                           {"mild": {**drop, "durationMS": 150.0, "placement": "intra-word"},
                            "moderate": {**drop, "durationMS": 600.0},
                            "severe": {**drop, "durationMS": 2000.0}},
                           controls={"control-natural-pause": {**drop, "durationMS": 600.0,
                                                               "mode": "natural-pause"}},
                           extra={"attenuated-ramped": ("moderate", {**drop, "durationMS": 600.0,
                                                                     "attenuationDB": -60.0, "rampMS": 5.0})}),
                 _dropout,
                 recording_variants=_take_variants(
                     {**take_drop, "durationMS": 600.0, "attenuationDB": 0.0},
                     {"mild": {**take_drop, "durationMS": 150.0},
                      "moderate": {**take_drop, "durationMS": 600.0},
                      "severe": {**take_drop, "durationMS": 2000.0}})),
        Injector("SIG-CLIP", 2, "clipping", ("A",),
                 "The loudest fraction of samples flattened at the level they exceed (hard) or squashed "
                 "above it by a soft knee, with no gain, so the label covers exactly the changed samples; "
                 "over-range: a gain that drives the fraction beyond full scale unflattened (labeled whole "
                 "take); sham: fraction 0 (identity); control: peak normalization to full scale, nothing "
                 "clipped.",
                 _variants({"clippedFraction": 0.0, "mode": "hard"},
                           {"mild": {"clippedFraction": 0.001, "mode": "hard"},
                            "moderate": {"clippedFraction": 0.01, "mode": "hard"},
                            "severe": {"clippedFraction": 0.05, "mode": "hard"}},
                           controls={"control-peak-normalized": {"mode": "peak-normalize", "targetPeak": 1.0}},
                           extra={"soft-knee-moderate": ("moderate", {"clippedFraction": 0.01,
                                                                      "mode": "soft-knee"}),
                                  "over-range-moderate": ("moderate", {"clippedFraction": 0.01,
                                                                       "mode": "overdrive"})}),
                 _clip),
        Injector("SIG-DC", 1, "dc offset", ("A",), "A constant offset; sham: offset 0.",
                 _variants({"offset": 0.0}, {"mild": {"offset": 0.02}, "moderate": {"offset": 0.08},
                                            "severe": {"offset": 0.3}}), _dc),
        Injector("SIG-LEVEL", 1, "level", ("A",), "A gain drop; sham: 0 dB.",
                 _variants({"gainDB": 0.0}, {"mild": {"gainDB": -10.0}, "moderate": {"gainDB": -30.0},
                                            "severe": {"gainDB": -50.0}}), _level),
        Injector("SIG-NOISE", 1, "additive noise", ("A", "G"),
                 "White noise or mains hum at an SNR against the speech RMS; sham: the same draw at zero "
                 "gain; control: white noise at 80 dB SNR.",
                 _variants({"kind": "white", "snrDB": None},
                           {"mild": {"kind": "white", "snrDB": 30.0},
                            "moderate": {"kind": "white", "snrDB": 15.0},
                            "severe": {"kind": "white", "snrDB": 0.0}},
                           controls={"control-80db": {"kind": "white", "snrDB": 80.0}},
                           extra={"hum-moderate": ("moderate", {"kind": "hum", "snrDB": 20.0})}),
                 _noise,
                 recording_variants=_take_variants(
                     {**take_noise, "snrDB": None},
                     {"mild": {**take_noise, "snrDB": 30.0}, "moderate": {**take_noise, "snrDB": 15.0},
                      "severe": {**take_noise, "snrDB": 0.0}})),
        Injector("SIG-SIL", 1, "leading or terminal silence", ("A", "C"),
                 "Zeros or room tone added before or after the take; sham: 0 s.",
                 _variants({"position": "terminal", "seconds": 0.0, "fill": "zeros"},
                           {"mild": {"position": "terminal", "seconds": 1.0, "fill": "zeros"},
                            "moderate": {"position": "terminal", "seconds": 2.5, "fill": "zeros"},
                            "severe": {"position": "terminal", "seconds": 10.0, "fill": "zeros"}},
                           extra={"leading-moderate": ("moderate", {"position": "leading", "seconds": 2.5,
                                                                    "fill": "zeros"})}),
                 _silence),
        Injector("BND-TRUNC", 1, "truncation", ("C",),
                 "A hard cut through the last words (whole words, then part of the new last word); "
                 "sham: no cut, a 20 ms fade at the natural end.",
                 _variants({"wordsRemoved": 0, "partialFraction": 0.0, "fadeMS": 20.0},
                           {"mild": {"wordsRemoved": 0, "partialFraction": 0.5, "fadeMS": 0.0},
                            "moderate": {"wordsRemoved": 1, "partialFraction": 0.5, "fadeMS": 0.0},
                            "severe": {"wordsRemoved": 3, "partialFraction": 0.5, "fadeMS": 0.0}}),
                 _truncate,
                 # The catalog sham (a fade at the natural end) needs no word.
                 recording_variants=_take_variants(
                     None, {"mild": {"keepFraction": 0.8, "fadeMS": 0.0},
                            "moderate": {"keepFraction": 0.65, "fadeMS": 0.0},
                            "severe": {"keepFraction": 0.5, "fadeMS": 0.0}})),
        Injector("BND-RUNON", 1, "run-on", ("C",),
                 "The last word repeated (or reversed) after the script ends; sham: 300 ms of room tone.",
                 _variants({"appendSeconds": 0.3, "content": "room-tone"},
                           {"mild": {"appendSeconds": 0.5, "content": "repeat-tail"},
                            "moderate": {"appendSeconds": 1.5, "content": "repeat-tail"},
                            "severe": {"appendSeconds": 4.0, "content": "repeat-tail"}},
                           extra={"reversed-moderate": ("moderate", {"appendSeconds": 1.5,
                                                                     "content": "reversed-tail"})}),
                 _run_on,
                 recording_variants=_take_variants(
                     {**take_run_on, "appendSeconds": 0.3, "content": "room-tone"},
                     {"mild": {**take_run_on, "appendSeconds": 0.5, "content": "repeat-span"},
                      "moderate": {**take_run_on, "appendSeconds": 1.5, "content": "repeat-span"},
                      "severe": {**take_run_on, "appendSeconds": 4.0, "content": "repeat-span"}})),
        Injector("CNT-REP", 1, "repetition or loop", ("B", "I"),
                 "Words repeated in place; sham: the splice at the same boundary with no repeat.",
                 _variants({"words": 2, "repeats": 0, "position": "middle"},
                           {"mild": {"words": 1, "repeats": 1, "position": "middle"},
                            "moderate": {"words": 2, "repeats": 2, "position": "middle"},
                            "severe": {"words": 3, "repeats": 4, "position": "middle"}}),
                 _repeat),
        Injector("CNT-DEL", 1, "word deletion", ("B",),
                 "Words removed by splicing at mid-gap cuts; sham: removed and re-inserted (splice only).",
                 _variants({"words": 2, "position": "middle", "gapMS": 0.0, "remove": False},
                           {"mild": {"words": 1, "position": "middle", "gapMS": 0.0, "remove": True},
                            "moderate": {"words": 2, "position": "middle", "gapMS": 0.0, "remove": True},
                            "severe": {"words": 3, "position": "start", "gapMS": 0.0, "remove": True}}),
                 _delete),
        Injector("CNT-INS", 1, "word insertion", ("B",),
                 "Same-speaker donor words spliced in at a boundary; sham: the splice with nothing inserted.",
                 _variants({"words": 0, "position": "middle"},
                           {"mild": {"words": 1, "position": "middle"},
                            "moderate": {"words": 2, "position": "middle"},
                            "severe": {"words": 4, "position": "middle"}}),
                 _insert),
        Injector("PRS-OCT", 1, "octave jump", ("F",),
                 "A span inside the longest word shifted by an octave; sham: 0 st through the same shifter.",
                 _variants({"semitones": 0.0, "durationMS": 200.0},
                           {"mild": {"semitones": 12.0, "durationMS": 80.0},
                            "moderate": {"semitones": 12.0, "durationMS": 200.0},
                            "severe": {"semitones": 12.0, "durationMS": 400.0}},
                           extra={"down-moderate": ("moderate", {"semitones": -12.0, "durationMS": 200.0})}),
                 _octave),
        Injector("PRS-BRK", 1, "pitch break", ("F",),
                 "A pitch step from the middle of the longest word to its end; sham: 0 st.",
                 _variants({"semitones": 0.0}, {"mild": {"semitones": 3.0}, "moderate": {"semitones": 5.0},
                                               "severe": {"semitones": 7.0}}),
                 _pitch_break),
        Injector("PRS-RATE", 1, "speed change", ("F", "C"),
                 "Overlap-add tempo change of the whole take, pitch kept; sham: 1.0x through the same path.",
                 _variants({"speed": 1.0}, {"mild": {"speed": 1.1}, "moderate": {"speed": 0.8},
                                           "severe": {"speed": 0.7}},
                           extra={"fast-severe": ("severe", {"speed": 1.3})}),
                 _rate),
        Injector("IDN-SHIFT", 1, "pitch and formant shift", ("E",),
                 "The whole take's pitch and formants shifted, length kept; sham: 0 st.",
                 _variants({"semitones": 0.0}, {"mild": {"semitones": 2.0}, "moderate": {"semitones": 4.0},
                                               "severe": {"semitones": -4.0}}),
                 _shift),
        Injector("IDN-SWAP", 1, "identity swap", ("E",),
                 "A time-aligned span of a second voice rendering the same script, spliced in at onset, "
                 "middle or end; sham: the source's own render (zero magnitude); control: a same-speaker "
                 "re-render.",
                 _variants({**swap, "relation": "self", "durationMS": 1000.0},
                           {"mild": {**swap, "relation": "close", "durationMS": 300.0},
                            "moderate": {**swap, "relation": "cross-gender", "durationMS": 1000.0,
                                         "position": "onset"},
                            "severe": {**swap, "relation": "cross-gender", "durationMS": 3000.0}},
                           controls={"control-same-speaker": {**swap, "relation": "self", "durationMS": 1000.0,
                                                              "renderSeed": 1}}),
                 _swap,
                 # Speaker-labelled recordings: another speaker's words over 0.3 s (middle), 1 s (onset) or
                 # 3 s (middle); the sham splices another utterance of the source speaker over the severe span.
                 recording_variants=_take_variants(
                     {"donor": "same-speaker", "position": "middle", "durationMS": 3000.0},
                     {"mild": {"donor": "other-speaker", "position": "middle", "durationMS": 300.0},
                      "moderate": {"donor": "other-speaker", "position": "onset", "durationMS": 1000.0},
                      "severe": {"donor": "other-speaker", "position": "middle", "durationMS": 3000.0}})),
        Injector("SIG-BAND", 1, "band-limit", ("A", "G"),
                 "A zero-phase low-pass (a 511-tap Blackman-windowed sinc) at 0.7, 0.5 or 0.3 of the source's "
                 "measured effective bandwidth (Stage 0's definition), so it cuts content the source has "
                 "whatever its sampling history (FLEURS-derived N2 near 8 kHz, natural takes near 11.5 kHz); "
                 "refused without an active frame, below a 1 kHz cutoff, or when the measured bandwidth does "
                 "not drop; sham: the same low-pass at 1.1 of the bandwidth, at most 0.99 of Nyquist.",
                 _variants({**band, "bandwidthFraction": 1.1},
                           {"mild": {**band, "bandwidthFraction": 0.7},
                            "moderate": {**band, "bandwidthFraction": 0.5},
                            "severe": {**band, "bandwidthFraction": 0.3}}),
                 _band_limit),
        Injector("PRS-ERRATIC", 1, "erratic pitch", ("F",),
                 "The take cut into seeded 150-300 ms spans, each shifted by a seeded sign of 2, 4 or 7 "
                 "semitones through the shifter of PRS-OCT, length kept and neighbours crossfaded over 5 ms; "
                 "needs no word interval; sham: 0 st through the same path.",
                 _variants({**erratic, "semitones": 0.0},
                           {"mild": {**erratic, "semitones": 2.0}, "moderate": {**erratic, "semitones": 4.0},
                            "severe": {**erratic, "semitones": 7.0}}),
                 _erratic),
        Injector("IDN-ONSET", 1, "onset identity swap", ("E",),
                 "Another voice over the first 0.3, 1.0 or 1.5 s of speech from the first word: a time-aligned "
                 "re-render of the script by a close voice; sham: the source's own render (zero magnitude); "
                 "control: a same-speaker re-render. On a speaker-labelled recording (take-*), another "
                 "speaker's opening words over the source's first words; sham: another utterance of the source "
                 "speaker the same way.",
                 _variants({**onset, "relation": "self", "durationMS": 1500.0},
                           {"mild": {**onset, "relation": "close", "durationMS": 300.0},
                            "moderate": {**onset, "relation": "close", "durationMS": 1000.0},
                            "severe": {**onset, "relation": "close", "durationMS": 1500.0}},
                           controls={"control-same-speaker": {**onset, "relation": "self", "durationMS": 1500.0,
                                                              "renderSeed": 1}}),
                 _onset,
                 recording_variants=_take_variants(
                     {**take_onset, "donor": "same-speaker", "durationMS": 1500.0},
                     {"mild": {**take_onset, "donor": "other-speaker", "durationMS": 300.0},
                      "moderate": {**take_onset, "donor": "other-speaker", "durationMS": 1000.0},
                      "severe": {**take_onset, "donor": "other-speaker", "durationMS": 1500.0}})),
        Injector("SEAM-DISC", 1, "seam discontinuity", ("J",),
                 "1, 5 or 20 ms of samples removed right after a seeded long-form seam, with no crossfade; "
                 "needs the source's seam offsets; sham: nothing removed at the same seam.",
                 _variants({"removeMS": 0.0}, {"mild": {"removeMS": 1.0}, "moderate": {"removeMS": 5.0},
                                               "severe": {"removeMS": 20.0}}),
                 _seam_disc),
        Injector("SEAM-VOICE", 1, "voice change at a seam", ("J",),
                 "The segment after a seeded long-form seam re-rendered by a close voice, time-aligned, for "
                 "1 s, 2 s or the whole segment; sham: the source's own render (zero magnitude); control: a "
                 "same-speaker re-render. On a speaker-labelled recording (take-*), another speaker's words "
                 "from the seam; sham: another utterance of the source speaker the same way. On a generated "
                 "long-form take (take-voice-*), another voice's long-form take from the start of one of its "
                 "segments; sham: another take of the source's voice the same way.",
                 _variants({**seam_voice, "relation": "self", "durationMS": None},
                           {"mild": {**seam_voice, "relation": "close", "durationMS": 1000.0},
                            "moderate": {**seam_voice, "relation": "close", "durationMS": 2000.0},
                            "severe": {**seam_voice, "relation": "close", "durationMS": None}},
                           controls={"control-same-speaker": {**seam_voice, "relation": "self", "durationMS": None,
                                                              "renderSeed": 1}}),
                 _seam_voice,
                 recording_variants=_take_variants(
                     {**take_seam, "donor": "same-speaker", "durationMS": None},
                     {"mild": {**take_seam, "donor": "other-speaker", "durationMS": 1000.0},
                      "moderate": {**take_seam, "donor": "other-speaker", "durationMS": 2000.0},
                      "severe": {**take_seam, "donor": "other-speaker", "durationMS": None}})
                 # Generated long-form takes: the voice each was generated with is its speaker label.
                 + _take_variants(
                     {**take_seam, "donor": "same-voice", "durationMS": None},
                     {"mild": {**take_seam, "donor": "other-voice", "durationMS": 1000.0},
                      "moderate": {**take_seam, "donor": "other-voice", "durationMS": 2000.0},
                      "severe": {**take_seam, "donor": "other-voice", "durationMS": None}}, prefix="take-voice")),
    ]
    return {injector.injector_id: injector for injector in injectors}


CATALOG: dict[str, Injector] = _catalog()


def needs(injector_id: str, parameters: Mapping[str, Any]) -> tuple[str, ...]:
    """What a variant needs of its source beyond PCM (keys of NEED_DESCRIPTIONS)."""
    if injector_id == "SIG-CLICK":
        return ("words",) if parameters["placement"] in ("voiced", "quiet") else ()
    if injector_id == "SIG-DROP":
        if parameters.get("mode") == "natural-pause":
            return ("pauses",)
        placement = parameters["placement"]
        return () if placement == "centre" else ("words", "pauses") if placement == "pause" else ("words",)
    if injector_id == "SIG-NOISE":
        return () if parameters["snrDB"] is None or parameters.get("snrReference") == "take" else ("words",)
    if injector_id == "BND-TRUNC":
        cut = "keepFraction" not in parameters and (parameters["wordsRemoved"] or parameters["partialFraction"])
        return ("words",) if cut else ()
    if injector_id == "BND-RUNON":
        return () if parameters.get("anchor") == "take-end" else ("words",)
    if injector_id in ("CNT-REP", "CNT-DEL", "CNT-INS", "PRS-OCT", "PRS-BRK"):
        return ("words",)
    if injector_id in ("IDN-SWAP", "IDN-ONSET"):
        return ("words", "donor") if "donor" in parameters else ("script", "voice", "words")
    if injector_id == "SEAM-VOICE":
        if parameters.get("donor") in VOICE_DONOR_RELATIONS:
            return ("voice-donor", "seams")
        return ("words", "donor", "seams") if "donor" in parameters else ("script", "voice", "seams")
    if injector_id == "SEAM-DISC":
        return ("seams",)
    return ()


def _has(source: Fixture, need: str) -> bool:
    return bool(source.words if need == "words" else source.pauses if need == "pauses"
                else source.seams if need == "seams"
                else source.script is not None if need == "script" else source.voice is not None)


def inject(injector_id: str, variant: str, source: Fixture, seed: int, *,
           donor: Fixture | None = None) -> Injection:
    """Apply one catalog (or recording) variant to a source under a seed.

    `donor`: the donor recording (or voice donor) of a variant that splices one
    (its `donor` parameter names the relation); any other variant refuses a donor.
    """
    injector = CATALOG[injector_id]
    chosen = injector.variant(variant)
    parameters = dict(chosen.parameters)
    required = needs(injector_id, parameters)
    if donor is not None and not DONOR_NEEDS & set(required):
        raise ValueError(f"{injector.key} {chosen.name} takes no donor")
    missing = [need for need in required
               if not (donor is not None if need in DONOR_NEEDS else _has(source, need))]
    if missing:
        raise InjectorNotApplicable(f"{source.fixture_id}: {injector.key} {chosen.name} needs "
                                    + "; ".join(NEED_DESCRIPTIONS[need] for need in missing))
    # The stream depends on the injector, the source and the seed, never on the
    # variant: a sham draws the same positions as its positives.
    rng = SeededStream(seed, injector.key, source.digest)
    result = injector.apply(source, parameters, rng, donor) if donor is not None \
        else injector.apply(source, parameters, rng)
    samples, labels = result[0], result[1]
    samples = np.ascontiguousarray(samples, dtype=np.float64)
    samples.setflags(write=False)
    # Without an explicit mapping, seams stand only where the edit kept the timeline.
    seams = tuple(int(seam) for seam in result[2]) if len(result) > 2 \
        else source.seams if samples.size == source.samples.size else ()
    if chosen.severity in NON_DEFECT_SEVERITIES and labels:
        raise AssertionError(f"{injector.key} {variant} labeled a defect in a sham or control")
    if chosen.severity not in NON_DEFECT_SEVERITIES and not labels:
        raise AssertionError(f"{injector.key} {variant} produced no labeled interval")
    return Injection(injector.key, chosen.name, chosen.severity, parameters, seed, source.family,
                     source.digest, samples, tuple(labels), pcm_digest(samples),
                     donor_digest=None if donor is None else donor.digest, seams=seams)


def catalog_description() -> dict:
    return {"schema": "vocello.audioqc.injector-catalog/1", "catalogVersion": CATALOG_VERSION,
            "mechanism": MECHANISM,
            "injectors": [injector.describe() for injector in CATALOG.values()]}
