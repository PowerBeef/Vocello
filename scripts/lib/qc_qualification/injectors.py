"""The T1 PCM injector catalog (audit section 5.2, label tier T1).

Every injector is a pure function of (source, parameters, seed): the same
source PCM, parameters and seed give byte-identical output, pinned by a golden
PCM16 digest per variant. Every family has a `sham`, the same processing at
zero magnitude, drawing the same positions from the same seeded stream as its
positives, plus a mild / moderate / severe sweep; a `control` is a non-identity
matched sham the audit names (a natural pause of equal length, a same-speaker
splice). Positives emit the exact labeled interval in the output timeline;
shams and controls emit none.

Word-aligned edits (deletion, insertion, repetition, truncation) use the
source's exact word intervals, which procedural fixtures carry by construction;
on recorded speech they would come from the aligner on N1 and N2 only. Identity
swaps splice a second voice rendering the same script, so the splice is
time-aligned and only the voice changes. Pitch and rate changes use a
windowed-sinc resampler and plain overlap-add (no correlation search, whose
arg-max could differ between hosts), so they are signal-level constructions,
not natural prosody.

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

CATALOG_VERSION = 1
MECHANISM = "T1-pcm-construction"
SEVERITIES = ("sham", "control", "mild", "moderate", "severe")
NON_DEFECT_SEVERITIES = frozenset({"sham", "control"})
SPLICE_FADE_MS = 5.0
OLA_WINDOW = 960
OLA_HOP = 240
SINC_HALF_WIDTH = 16


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
    apply: Callable[[Fixture, dict, SeededStream], tuple[np.ndarray, list[dict]]] = field(repr=False)

    @property
    def key(self) -> str:
        return f"{self.injector_id}@{self.version}"

    def variant(self, name: str) -> Variant:
        for variant in self.variants:
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

    @property
    def positive(self) -> bool:
        return self.severity not in NON_DEFECT_SEVERITIES

    def recipe(self) -> dict:
        return {"schema": "vocello.audioqc.injection-recipe/1", "catalogVersion": CATALOG_VERSION,
                "mechanism": MECHANISM, "injector": self.injector, "variant": self.variant,
                "severity": self.severity, "parameters": self.parameters, "seed": self.seed,
                "sourceFamily": self.source_family, "sourcePCMSHA256": self.source_digest,
                "outputPCMSHA256": self.digest, "labels": list(self.labels)}


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
        raise ValueError(f"needs more than {count} words")
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
        cut = source.pauses[0][0] + (source.pauses[0][1] - source.pauses[0][0]) // 2 if source.pauses \
            else boundaries(source)[len(source.words) // 2]
        output, _ = join([source.samples[:cut], _room_tone(rng, length), source.samples[cut:]], 0)
        return output, []
    placement = parameters["placement"]
    if placement == "intra-word":
        first, last = _longest_word(source)
        start = (first + last) // 2 - length // 2
    elif placement == "interior":
        first, last = source.words[0][0], source.words[-1][1]
        start = (first + last) // 2 - length // 2
    elif placement == "pause":
        first, last = source.pauses[0] if source.pauses else (source.words[0][1], source.words[1][0])
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
    if ramp:
        steps = np.arange(1, ramp + 1) / (ramp + 1)
        lead = max(0, start - ramp)
        multiplier[lead:start] = (1.0 - steps * (1.0 - gain))[ramp - (start - lead):]
        trail = min(size, end + ramp)
        multiplier[end:trail] = (gain + steps * (1.0 - gain))[:trail - end]
    output = source.samples * multiplier
    labels = [{"kind": "dropout", "startSample": start, "endSample": end}] if gain < 1.0 else []
    return output, labels


def _clip(source: Fixture, parameters: dict, rng: SeededStream) -> tuple[np.ndarray, list[dict]]:
    magnitude = np.sort(np.abs(source.samples))[::-1]
    fraction = parameters["clippedFraction"]
    beyond = int(math.ceil(fraction * magnitude.size))
    level = magnitude[min(beyond, magnitude.size - 1)]
    driven = source.samples / max(float(level), 1e-12)
    mode = parameters["mode"]
    if mode == "hard":
        output = np.clip(driven, -1.0, 1.0)
    elif mode == "tanh":
        output = np.tanh(driven) / math.tanh(1.0) if beyond else driven
        output = np.clip(output, -1.0, 1.0)
    elif mode == "overdrive":
        output = driven
    else:
        raise ValueError(f"unknown clipping mode {mode!r}")
    over = np.flatnonzero(np.abs(driven) > 1.0)
    labels = [{"kind": "clipping", "startSample": int(over[0]), "endSample": int(over[-1]) + 1,
               "drivenSamples": int(over.size)}] if beyond and over.size else []
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
    scale = _speech_rms(source) / 10.0 ** (snr / 20.0) / float(np.sqrt(np.mean(noise ** 2)))
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
    words = source.words
    removed = parameters["wordsRemoved"]
    partial = parameters["partialFraction"]
    size = source.samples.size
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


def _run_on(source: Fixture, parameters: dict, rng: SeededStream) -> tuple[np.ndarray, list[dict]]:
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


def _swap(source: Fixture, parameters: dict, rng: SeededStream) -> tuple[np.ndarray, list[dict]]:
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


def _variants(sham: dict, sweep: dict[str, dict], *, controls: dict[str, dict] | None = None,
              extra: dict[str, tuple[str, dict]] | None = None) -> tuple[Variant, ...]:
    variants = [Variant("sham", "sham", sham)]
    variants += [Variant(name, "control", parameters) for name, parameters in (controls or {}).items()]
    variants += [Variant(name, name, parameters) for name, parameters in sweep.items()]
    variants += [Variant(name, severity, parameters) for name, (severity, parameters) in (extra or {}).items()]
    return tuple(variants)


def _catalog() -> dict[str, Injector]:
    click = {"widthSamples": 1, "placement": "voiced", "clustered": False}
    drop = {"placement": "interior", "attenuationDB": None, "rampMS": 0.0, "mode": "attenuate"}
    swap = {"position": "middle", "renderSeed": 0}
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
                 _click),
        Injector("SIG-DROP", 1, "dropout", ("A", "C"),
                 "A span zeroed or attenuated inside a word, the interior or a pause; sham: the moderate "
                 "span at 0 dB; control: a natural pause of equal length at punctuation.",
                 _variants({**drop, "durationMS": 600.0, "attenuationDB": 0.0},
                           {"mild": {**drop, "durationMS": 150.0, "placement": "intra-word"},
                            "moderate": {**drop, "durationMS": 600.0},
                            "severe": {**drop, "durationMS": 2000.0}},
                           controls={"control-natural-pause": {**drop, "durationMS": 600.0,
                                                               "mode": "natural-pause"}},
                           extra={"attenuated-ramped": ("moderate", {**drop, "durationMS": 600.0,
                                                                     "attenuationDB": -60.0, "rampMS": 5.0})}),
                 _dropout),
        Injector("SIG-CLIP", 1, "clipping", ("A",),
                 "Gain that drives a fraction of samples beyond full scale, then hard, tanh or no "
                 "clipping; sham: the same gain at fraction 0 (peak normalized, nothing clipped).",
                 _variants({"clippedFraction": 0.0, "mode": "hard"},
                           {"mild": {"clippedFraction": 0.001, "mode": "hard"},
                            "moderate": {"clippedFraction": 0.01, "mode": "hard"},
                            "severe": {"clippedFraction": 0.05, "mode": "hard"}},
                           extra={"tanh-moderate": ("moderate", {"clippedFraction": 0.01, "mode": "tanh"}),
                                  "overdrive-moderate": ("moderate", {"clippedFraction": 0.01,
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
                 _noise),
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
                 _truncate),
        Injector("BND-RUNON", 1, "run-on", ("C",),
                 "The last word repeated (or reversed) after the script ends; sham: 300 ms of room tone.",
                 _variants({"appendSeconds": 0.3, "content": "room-tone"},
                           {"mild": {"appendSeconds": 0.5, "content": "repeat-tail"},
                            "moderate": {"appendSeconds": 1.5, "content": "repeat-tail"},
                            "severe": {"appendSeconds": 4.0, "content": "repeat-tail"}},
                           extra={"reversed-moderate": ("moderate", {"appendSeconds": 1.5,
                                                                     "content": "reversed-tail"})}),
                 _run_on),
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
                 _swap),
    ]
    return {injector.injector_id: injector for injector in injectors}


CATALOG: dict[str, Injector] = _catalog()


def inject(injector_id: str, variant: str, source: Fixture, seed: int) -> Injection:
    """Apply one catalog variant to a source under a seed."""
    injector = CATALOG[injector_id]
    chosen = injector.variant(variant)
    parameters = dict(chosen.parameters)
    # The stream depends on the injector, the source and the seed, never on the
    # variant: a sham draws the same positions as its positives.
    rng = SeededStream(seed, injector.key, source.digest)
    samples, labels = injector.apply(source, parameters, rng)
    samples = np.ascontiguousarray(samples, dtype=np.float64)
    samples.setflags(write=False)
    if chosen.severity in NON_DEFECT_SEVERITIES and labels:
        raise AssertionError(f"{injector.key} {variant} labeled a defect in a sham or control")
    if chosen.severity not in NON_DEFECT_SEVERITIES and not labels:
        raise AssertionError(f"{injector.key} {variant} produced no labeled interval")
    return Injection(injector.key, chosen.name, chosen.severity, parameters, seed, source.family,
                     source.digest, samples, tuple(labels), pcm_digest(samples))


def catalog_description() -> dict:
    return {"schema": "vocello.audioqc.injector-catalog/1", "catalogVersion": CATALOG_VERSION,
            "mechanism": MECHANISM,
            "injectors": [injector.describe() for injector in CATALOG.values()]}
