"""Procedural speech-like sources and abstention fixtures (audit section 5.2).

No WAV is committed: every fixture is generated from a seed. A source is a
*script* (word and syllable timing, vowels, punctuation pauses, intonation and a
pseudo-text whose letter count sets a plausible speaking rate) rendered by a
*voice* (F0, formant scale, level, breathiness). Voiced syllables are additive
harmonic "glottal" series shaped by five-vowel formant envelopes, some onsets
carry a fricative noise burst, and a -80 dBFS room tone fills every pause.

The script is the source family: its injections and its re-renders by another
voice (the time-aligned donors of identity splices) are one unit of
independence. These are T1 construction material, neither N1 nor N2: they can
measure a signal detector's detection rate and its false alarms on clean
procedural speech, never an in-domain false-alarm rate (A2).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Iterable

import numpy as np

from .pcm import ENGINE_SAMPLE_RATE, SeededStream, pcm_digest

FIXTURE_VERSION = 1
ROOM_TONE_RMS = 1.0e-4
VOWEL_FORMANTS = {
    "a": (730.0, 1090.0, 2440.0),
    "e": (530.0, 1840.0, 2480.0),
    "i": (270.0, 2290.0, 3010.0),
    "o": (570.0, 840.0, 2410.0),
    "u": (300.0, 870.0, 2240.0),
}
FORMANT_BANDWIDTHS = (90.0, 120.0, 170.0)
FORMANT_GAINS = (1.0, 0.55, 0.3)
HARMONIC_CEILING_HZ = 5_000.0
CONSONANT_LETTERS = "bdfgklmnprstvz"
VOWEL_LETTERS = "aeiou"
CLEAN_STRATA = ("modal", "quiet", "breathy", "long-pause", "high-f0")
ABSTENTION_KINDS = (
    "digital-silence", "white-noise", "music", "square-wave", "nan-bearing", "short-clip",
    "long-take", "whisper", "shout", "extreme-f0", "repeated-word", "explicit-long-pause",
)


@dataclass(frozen=True)
class Voice:
    voice_id: str
    f0_hz: float
    formant_scale: float
    level_dbfs: float = -20.0
    breathiness: float = 0.06
    excursion_st: float = 3.0


VOICES = {
    "low": Voice("low", 112.0, 1.0),
    "high": Voice("high", 205.0, 1.16),
}


@dataclass(frozen=True)
class Syllable:
    start: int
    end: int
    vowel: str
    fricative_onset: bool
    accent: float


@dataclass(frozen=True)
class Script:
    family: str
    sample_rate: int
    length: int
    syllables: tuple[Syllable, ...]
    words: tuple[tuple[int, int], ...]
    pauses: tuple[tuple[int, int], ...]
    text: str
    seed: int


@dataclass(frozen=True)
class Fixture:
    fixture_id: str
    family: str
    stratum: str
    sample_rate: int
    samples: np.ndarray
    words: tuple[tuple[int, int], ...]
    pauses: tuple[tuple[int, int], ...]
    text: str
    script: Script | None
    voice: Voice | None
    digest: str

    @property
    def duration_seconds(self) -> float:
        return self.samples.size / self.sample_rate

    def describe(self) -> dict:
        return {"fixture": self.fixture_id, "family": self.family, "stratum": self.stratum,
                "sampleRate": self.sample_rate, "frames": int(self.samples.size),
                "words": len(self.words), "declaredPauses": len(self.pauses),
                "voice": None if self.voice is None else self.voice.voice_id,
                "pcmSHA256": self.digest}


def _frozen(samples: np.ndarray) -> np.ndarray:
    values = np.ascontiguousarray(samples, dtype=np.float64)
    values.setflags(write=False)
    return values


def make_fixture(fixture_id: str, family: str, stratum: str, samples: np.ndarray, *,
                 sample_rate: int = ENGINE_SAMPLE_RATE, words: Iterable[tuple[int, int]] = (),
                 pauses: Iterable[tuple[int, int]] = (), text: str = "", script: Script | None = None,
                 voice: Voice | None = None) -> Fixture:
    frozen = _frozen(samples)
    return Fixture(fixture_id, family, stratum, sample_rate, frozen, tuple(words), tuple(pauses), text,
                   script, voice, pcm_digest(frozen))


# --------------------------------------------------------------------------- #
# Scripts
# --------------------------------------------------------------------------- #

def _seconds(rng: SeededStream, low: float, high: float) -> float:
    return rng.uniform_one(low, high)


def make_script(index: int, *, stratum: str = "modal", sample_rate: int = ENGINE_SAMPLE_RATE,
                word_count: int | None = None, repeated_word: bool = False,
                pause_seconds: tuple[float, float] | None = None) -> Script:
    """A deterministic word, syllable and pause plan with its pseudo-text."""
    family = f"proc-script-{stratum}-{index:04d}"
    rng = SeededStream(index, "script", stratum)
    words_wanted = word_count or 5 + rng.integer(5)
    long_pause = stratum == "long-pause"
    pause_range = pause_seconds or ((0.9, 1.5) if long_pause else (0.22, 0.52))
    cursor = int(_seconds(rng, 0.15, 0.3) * sample_rate)
    syllables: list[Syllable] = []
    words: list[tuple[int, int]] = []
    pauses: list[tuple[int, int]] = []
    pause_after: list[bool] = []
    template: list[tuple[float, str, bool]] | None = None
    forced_pause = rng.integer(max(1, words_wanted - 1)) if long_pause and words_wanted > 1 else -1
    for word_index in range(words_wanted):
        if repeated_word and template is not None:
            plan = template
        else:
            plan = [(_seconds(rng, 0.11, 0.23), VOWEL_LETTERS[rng.integer(5)], rng.uniform_one() < 0.35)
                    for _ in range(1 + rng.integer(3))]
            template = template or plan
        start = cursor
        for duration, vowel, fricative in plan:
            length = int(duration * sample_rate)
            syllables.append(Syllable(cursor, cursor + length, vowel, fricative, rng.uniform_one()))
            cursor += length
        words.append((start, cursor))
        last = word_index == words_wanted - 1
        pause = not last and (word_index == forced_pause or (not long_pause and rng.uniform_one() < 0.25))
        pause_after.append(pause)
        if last:
            break
        gap = int((_seconds(rng, *pause_range) if pause else _seconds(rng, 0.03, 0.11)) * sample_rate)
        if pause:
            pauses.append((cursor, cursor + gap))
        cursor += gap
    length = cursor + int(_seconds(rng, 0.25, 0.45) * sample_rate)
    text = _pseudo_text(rng, words, pause_after, length / sample_rate, repeated_word)
    return Script(family, sample_rate, length, tuple(syllables), tuple(words), tuple(pauses), text, index)


def _pseudo_text(rng: SeededStream, words: list[tuple[int, int]], pause_after: list[bool],
                 duration: float, repeated: bool) -> str:
    """Letters whose count gives 0.068-0.092 s per unit, like ordinary benchmark takes."""
    units = max(2 * len(words), round(duration / _seconds(rng, 0.068, 0.092)))
    spans = [end - start for start, end in words]
    total = sum(spans)
    counts = [max(2, round(units * span / total)) for span in spans]
    if repeated:
        counts = [counts[0]] * len(counts)
    tokens = []
    first_word = None
    for count, pause in zip(counts, pause_after):
        if repeated and first_word is not None:
            word = first_word
        else:
            word = "".join(CONSONANT_LETTERS[rng.integer(len(CONSONANT_LETTERS))] if position % 2 == 0
                           else VOWEL_LETTERS[rng.integer(len(VOWEL_LETTERS))] for position in range(count))
            first_word = first_word or word
        tokens.append(word + ("," if pause else ""))
    return " ".join(tokens) + "."


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #

def _raised_cosine_envelope(length: int, attack: int, release: int) -> np.ndarray:
    envelope = np.linspace(1.0, 0.82, length) if length else np.zeros(0)
    attack = min(attack, length // 2)
    release = min(release, length // 2)
    if attack:
        envelope[:attack] *= 0.5 - 0.5 * np.cos(np.pi * np.arange(attack) / attack)
    if release:
        envelope[length - release:] *= 0.5 + 0.5 * np.cos(np.pi * np.arange(1, release + 1) / release)
    return envelope


def _high_passed_noise(rng: SeededStream, count: int) -> np.ndarray:
    noise = rng.normal(count + 1)
    return np.diff(noise) / math.sqrt(2.0)


def render(script: Script, voice: Voice, *, render_seed: int = 0) -> np.ndarray:
    """Render a script with a voice; `render_seed` varies jitter and noise only."""
    rate = script.sample_rate
    count = script.length
    rng = SeededStream(script.seed, "render", script.family, voice.voice_id, str(render_seed))
    time = np.arange(count, dtype=np.float64) / rate
    duration = count / rate
    semitones = 1.5 - 3.0 * time / max(duration, 1e-9)
    for syllable in script.syllables:
        span = syllable.end - syllable.start
        bump = np.sin(np.pi * np.arange(span) / max(span, 1)) ** 2
        semitones[syllable.start:syllable.end] += voice.excursion_st * (syllable.accent - 0.5) * bump
    phases = rng.uniform(3) * 2.0 * math.pi
    rates = 2.0 + 4.0 * rng.uniform(3)
    for phase, wobble in zip(phases, rates):
        semitones += 0.12 * np.sin(2.0 * math.pi * wobble * time + phase)
    f0 = voice.f0_hz * np.power(2.0, semitones / 12.0)
    phase = 2.0 * math.pi * np.cumsum(f0) / rate
    output = np.zeros(count, dtype=np.float64)
    speech_mask = np.zeros(count, dtype=bool)
    formants = {name: tuple(value * voice.formant_scale for value in values)
                for name, values in VOWEL_FORMANTS.items()}
    for syllable in script.syllables:
        start, end = syllable.start, syllable.end
        speech_mask[start:end] = True
        voiced_start = start + (int(0.3 * (end - start)) if syllable.fricative_onset else 0)
        length = end - voiced_start
        envelope = _raised_cosine_envelope(length, int(0.015 * rate), int(0.03 * rate))
        segment_f0 = float(np.mean(f0[voiced_start:end]))
        harmonics = np.arange(1, max(3, int(HARMONIC_CEILING_HZ / float(np.max(f0[voiced_start:end])))) + 1)
        frequencies = harmonics * segment_f0
        gains = np.full(harmonics.size, 0.02)
        for centre, bandwidth, weight in zip(formants[syllable.vowel], FORMANT_BANDWIDTHS, FORMANT_GAINS):
            gains += weight * np.exp(-0.5 * ((frequencies - centre) / bandwidth) ** 2)
        amplitudes = gains / harmonics
        waves = np.sin(np.outer(harmonics, phase[voiced_start:end]))
        voiced = (amplitudes[:, None] * waves).sum(axis=0) * envelope
        level = float(np.sqrt(np.mean(voiced ** 2))) if length else 0.0
        aspiration = _high_passed_noise(rng, length) * envelope * level
        output[voiced_start:end] += (1.0 - voice.breathiness) * voiced + voice.breathiness * aspiration
        if syllable.fricative_onset and voiced_start > start:
            burst = voiced_start - start + int(0.01 * rate)
            burst = min(burst, end - start)
            burst_envelope = _raised_cosine_envelope(burst, int(0.005 * rate), int(0.012 * rate))
            output[start:start + burst] += 0.35 * level * _high_passed_noise(rng, burst) * burst_envelope
    speech = output[speech_mask]
    rms = float(np.sqrt(np.mean(speech ** 2))) if speech.size else 0.0
    if rms > 0:
        output *= 10.0 ** (voice.level_dbfs / 20.0) / rms
    output += ROOM_TONE_RMS * rng.normal(count)
    return output


def _voice_for(index: int, stratum: str) -> Voice:
    base = VOICES["low" if index % 2 == 0 else "high"]
    rng = SeededStream(index, "voice", stratum)
    f0 = base.f0_hz * 2.0 ** (rng.uniform_one(-2.0, 2.0) / 12.0)
    voice = replace(base, voice_id=f"{base.voice_id}-{stratum}-{index:04d}", f0_hz=f0)
    if stratum == "quiet":
        return replace(voice, level_dbfs=-34.0)
    if stratum == "breathy":
        return replace(voice, level_dbfs=-30.0, breathiness=0.85)
    if stratum == "high-f0":
        return replace(voice, f0_hz=rng.uniform_one(290.0, 380.0), formant_scale=1.2, excursion_st=6.0)
    return voice


def clean_fixture(index: int, stratum: str = "modal") -> Fixture:
    """One clean procedural source of a stratum: its script is the family."""
    if stratum not in CLEAN_STRATA:
        raise ValueError(f"unknown stratum {stratum!r}")
    script = make_script(index, stratum=stratum)
    voice = _voice_for(index, stratum)
    samples = render(script, voice)
    return make_fixture(f"proc-{stratum}-{index:04d}", script.family, stratum, samples,
                        sample_rate=script.sample_rate, words=script.words, pauses=script.pauses,
                        text=script.text, script=script, voice=voice)


def donor_voice(voice: Voice, relation: str) -> Voice:
    """A second voice for identity splices: `close` (same register) or `cross-gender`."""
    if relation == "close":
        return replace(voice, voice_id=f"{voice.voice_id}+close", f0_hz=voice.f0_hz * 1.18,
                       formant_scale=voice.formant_scale * 1.06)
    if relation == "cross-gender":
        up = voice.f0_hz < 160.0
        return replace(voice, voice_id=f"{voice.voice_id}+cross",
                       f0_hz=voice.f0_hz * (1.85 if up else 0.54),
                       formant_scale=voice.formant_scale * (1.16 if up else 0.86))
    if relation == "self":
        return voice
    raise ValueError(f"unknown donor relation {relation!r}")


def rerender(fixture: Fixture, voice: Voice, *, render_seed: int = 0) -> np.ndarray:
    """The fixture's script rendered by another voice, sample-aligned with it."""
    if fixture.script is None:
        raise ValueError("fixture has no script to re-render")
    return render(fixture.script, voice, render_seed=render_seed)


# --------------------------------------------------------------------------- #
# Abstention fixtures
# --------------------------------------------------------------------------- #

def _tone(frequencies: Iterable[float], seconds: float, rate: int, level_dbfs: float) -> np.ndarray:
    time = np.arange(int(seconds * rate)) / rate
    wave = np.zeros(time.size)
    for frequency in frequencies:
        for harmonic in range(1, 5):
            wave += np.sin(2.0 * math.pi * frequency * harmonic * time) / harmonic
    wave *= 1.0 + 0.2 * np.sin(2.0 * math.pi * 5.0 * time)
    return wave * 10.0 ** (level_dbfs / 20.0) / float(np.sqrt(np.mean(wave ** 2)))


def abstention_fixture(kind: str, sample_rate: int = ENGINE_SAMPLE_RATE) -> Fixture:
    """Inputs a judge must never pass: out of scope, degenerate or unqualified text classes."""
    rate = sample_rate
    family = f"abstention-{kind}"

    def scripted(script: Script, voice: Voice) -> Fixture:
        return make_fixture(f"abstention-{kind}", family, f"abstention/{kind}", render(script, voice),
                            sample_rate=rate, words=script.words, pauses=script.pauses, text=script.text,
                            script=script, voice=voice)

    if kind == "digital-silence":
        return make_fixture(family, family, f"abstention/{kind}", np.zeros(3 * rate), sample_rate=rate,
                            text="silence only.")
    if kind == "white-noise":
        noise = SeededStream(1, "abstention", kind).normal(3 * rate) * 0.1
        return make_fixture(family, family, f"abstention/{kind}", noise, sample_rate=rate,
                            text="noise only, no speech.")
    if kind == "music":
        return make_fixture(family, family, f"abstention/{kind}", _tone((220.0, 277.18, 329.63), 3.0, rate,
                                                                       -20.0), sample_rate=rate,
                            text="a chord, no speech.")
    if kind == "square-wave":
        time = np.arange(3 * rate) / rate
        square = 0.3 * np.sign(np.sin(2.0 * math.pi * 200.0 * time))
        return make_fixture(family, family, f"abstention/{kind}", square, sample_rate=rate,
                            text="a square wave, no speech.")
    if kind == "nan-bearing":
        base = clean_fixture(9_001, "modal")
        samples = np.array(base.samples)
        positions = SeededStream(1, "abstention", kind).integers(samples.size, 16)
        samples[positions] = np.nan
        return make_fixture(family, family, f"abstention/{kind}", samples, sample_rate=rate,
                            words=base.words, pauses=base.pauses, text=base.text, script=base.script,
                            voice=base.voice)
    if kind == "short-clip":
        return scripted(make_script(9_002, stratum="modal", word_count=1), VOICES["low"])
    if kind == "long-take":
        return scripted(make_script(9_003, stratum="modal", word_count=135), VOICES["high"])
    if kind == "whisper":
        return scripted(make_script(9_004, stratum="modal"),
                        replace(VOICES["low"], voice_id="whisper", breathiness=1.0, level_dbfs=-32.0))
    if kind == "shout":
        return scripted(make_script(9_005, stratum="modal"),
                        replace(VOICES["high"], voice_id="shout", level_dbfs=-9.0, excursion_st=7.0))
    if kind == "extreme-f0":
        return scripted(make_script(9_006, stratum="modal"),
                        replace(VOICES["high"], voice_id="extreme-f0", f0_hz=650.0, formant_scale=1.3))
    if kind == "repeated-word":
        return scripted(make_script(9_007, stratum="modal", word_count=8, repeated_word=True), VOICES["low"])
    if kind == "explicit-long-pause":
        return scripted(make_script(9_008, stratum="long-pause", pause_seconds=(2.4, 2.6)), VOICES["low"])
    raise ValueError(f"unknown abstention fixture {kind!r}")
