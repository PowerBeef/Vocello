"""Recorded takes as injector sources (audit section 5.2, populations N3 and N1).

A natural Vocello take (N3) is a 24 kHz mono PCM16 WAV the engine wrote. The
adapter reads it at its native rate (no resampling: the injectors and the Fast
QC v8 mirror both work at the engine rate; the L0 `polyphase-kaiser5-v2` path
only feeds the 16 kHz judges) and at 1/32767, the scale `pcm.to_pcm16` writes
and the v8 mirror reads back, so the source's PCM digest is the digest of the
file's own PCM16 and an identity sham writes the same samples back.

A FLEURS human recording (N1) is 16 kHz. It is resampled to the engine rate
before any injector sees it, because the catalog is not rate-free: click widths
and cluster spacing, and the overlap-add window of the pitch and rate edits,
are counted in samples at 24 kHz, and `score` and `verify` read clips at 24
kHz, the rate Fast QC v8 and the Stage 0 observations are calibrated at. The
resampler is the Kaiser (beta 5), 10-zero-crossing, zero-phase polyphase
design of `polyphase-kaiser5-v2`, as `lib.playback_capture.resample`
implements it for any rate pair (`audio_resampling.RationalFIR` only writes 16
kHz); `resampling_recipe` names it in every recipe, and the source PCM digest
is the digest of the resampled PCM, so `verify` replays it exactly.

A recording carries none of what a procedural fixture knows by construction:
no word intervals (on N3 they never exist; the aligner runs on N1 and N2 only),
no declared pause intervals, no script to re-render and no render voice. Its
`text` is the request text the take was generated from, which Fast QC reads
for the pause budget and the speaking rate; no injector reads it, and nothing
here writes it out. Injectors that need any of the rest refuse the source with
`InjectorNotApplicable` (`injectors.needs`).

On N1 and N2 the forced aligner's intervals (`audio_qc_calibration_set.py
alignments`, seconds on the take's own timeline) become word intervals
(`word_alignment`, rule `ALIGNMENT_RULE`): each positive-length interval is one
word, mapped to 24 kHz samples by rounding (the aligner's 80 ms frames land on
whole samples), and a gap longer than `PAUSE_GAP_SECONDS` between two words is
a declared pause. A zero-length interval is a unit the aligner squeezed into
its neighbour at its frame resolution: it is no word, so a word-level edit may
carry it with that neighbour. An alignment is refused whole (the take keeps no
word interval) when its words overlap or run backwards, overrun the take by
more than one aligner frame, number fewer than `MINIMUM_WORDS`, or when more
than `MAXIMUM_SQUEEZED_FRACTION` of its intervals are squeezed. For Chinese and
Japanese the aligner's units are characters or short character runs, so a
"word" there is that unit.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import math
import os
import wave
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

from ..playback_capture import resample as polyphase_resample
from .fixtures import Fixture, make_fixture
from .pcm import ENGINE_SAMPLE_RATE, PCM16_FULL_SCALE, to_pcm16

# Source rates a recording may have: the engine's own, and FLEURS's (N1).
SOURCE_RATES = frozenset({ENGINE_SAMPLE_RATE, 16_000})
RESAMPLER = "kaiser5-polyphase"
RESAMPLER_IMPLEMENTATION = "scripts/lib/playback_capture.py resample"
# Aligner intervals as word intervals (`word_alignment`).
ALIGNMENT_RULE = "aligner-words-v1"
ALIGNER_FRAME_SECONDS = 0.08
PAUSE_GAP_SECONDS = 0.2
MINIMUM_WORDS = 5
MAXIMUM_SQUEEZED_FRACTION = 0.2


class RecordingError(ValueError):
    """A take's WAV is missing, unreadable, not PCM16 mono or not what its digest says."""


def resampling_recipe(source_rate: int) -> dict | None:
    """How a source at `source_rate` reaches the engine rate: None when it is read as it is."""
    if source_rate not in SOURCE_RATES:
        raise RecordingError(f"a recording at {source_rate} Hz is not supported "
                             f"({', '.join(str(rate) for rate in sorted(SOURCE_RATES))} Hz are)")
    if source_rate == ENGINE_SAMPLE_RATE:
        return None
    return {"sourceRate": source_rate, "rate": ENGINE_SAMPLE_RATE, "resampler": RESAMPLER,
            "implementation": RESAMPLER_IMPLEMENTATION}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_pcm16_wav(path: Path, *, sample_rate: int = ENGINE_SAMPLE_RATE) -> np.ndarray:
    """The take's samples in [-1, 1] at 1/32767, refusing anything but PCM16 mono at the engine rate."""
    try:
        with wave.open(str(path), "rb") as reader:
            if reader.getsampwidth() != 2 or reader.getnchannels() != 1:
                raise RecordingError(f"{path.name} is not 16-bit mono PCM")
            if reader.getframerate() != sample_rate:
                raise RecordingError(f"{path.name} is {reader.getframerate()} Hz, not {sample_rate} Hz")
            frames = reader.getnframes()
            raw = reader.readframes(frames)
    except (OSError, EOFError, wave.Error) as error:
        raise RecordingError(f"{path.name} is unreadable: {error}") from error
    pcm = np.frombuffer(raw, dtype="<i2")
    if pcm.size != frames:
        raise RecordingError(f"{path.name} declares {frames} frames but holds {pcm.size}")
    return pcm.astype(np.float64) / PCM16_FULL_SCALE


def write_pcm16_wav(path: Path, samples: np.ndarray, *, sample_rate: int = ENGINE_SAMPLE_RATE) -> str:
    """Write canonical PCM16 mono (atomically) and return the file's SHA-256."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with wave.open(str(temporary), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(to_pcm16(samples).tobytes())
    os.replace(temporary, path)
    return file_sha256(path)


def recording_fixture(take_id: str, family: str, stratum: str, samples: np.ndarray, *, text: str = "",
                      sample_rate: int = ENGINE_SAMPLE_RATE) -> Fixture:
    """A `Fixture` for a recorded take: its PCM and request text, and nothing it cannot honestly know."""
    return make_fixture(take_id, family, stratum, samples, sample_rate=sample_rate, words=(), pauses=(),
                        text=text, script=None, voice=None)


@dataclass(frozen=True)
class WordAlignment:
    """An aligner's intervals as word and pause intervals in samples; `issue` names why none are usable."""

    words: tuple[tuple[int, int], ...]
    pauses: tuple[tuple[int, int], ...]
    intervals: int
    squeezed: int
    issue: str | None

    @property
    def usable(self) -> bool:
        return self.issue is None

    def describe(self) -> dict:
        return {"rule": ALIGNMENT_RULE, "intervals": self.intervals, "squeezed": self.squeezed,
                "words": len(self.words), "pauses": len(self.pauses), "issue": self.issue}


def word_alignment(intervals: Iterable[Sequence[float]], *, frames: int,
                   sample_rate: int = ENGINE_SAMPLE_RATE) -> WordAlignment:
    """Word intervals, and pauses between them, from (start, end) seconds on a take of `frames` samples."""
    spans = [(float(start), float(end)) for start, end in intervals]
    total = len(spans)

    def refused(issue: str, squeezed: int = 0) -> WordAlignment:
        return WordAlignment((), (), total, squeezed, issue)

    if any(not (math.isfinite(start) and math.isfinite(end)) or start < 0.0 for start, end in spans):
        return refused("an interval is not a finite, non-negative time")
    positive = [(start, end) for start, end in spans if end > start]
    squeezed = total - len(positive)
    tolerance = int(round(ALIGNER_FRAME_SECONDS * sample_rate))
    words: list[tuple[int, int]] = []
    for start, end in positive:
        first, last = int(round(start * sample_rate)), int(round(end * sample_rate))
        if last > frames + tolerance:
            return refused("an interval overruns the take by more than one aligner frame", squeezed)
        first, last = min(first, frames), min(last, frames)
        if last <= first:
            squeezed += 1
            continue
        words.append((first, last))
    if any(later[0] < earlier[1] for earlier, later in zip(words, words[1:])):
        return refused("intervals overlap or run backwards", squeezed)
    if total and squeezed / total > MAXIMUM_SQUEEZED_FRACTION:
        return refused(f"more than {MAXIMUM_SQUEEZED_FRACTION:.0%} of the intervals are squeezed to zero length",
                       squeezed)
    if len(words) < MINIMUM_WORDS:
        return refused(f"fewer than {MINIMUM_WORDS} aligned words", squeezed)
    gap = PAUSE_GAP_SECONDS * sample_rate
    pauses = tuple((earlier[1], later[0]) for earlier, later in zip(words, words[1:]) if later[0] - earlier[1] > gap)
    return WordAlignment(tuple(words), pauses, total, squeezed, None)


def with_alignment(fixture: Fixture, alignment: WordAlignment) -> Fixture:
    """The recording with the aligner's word and pause intervals (unchanged PCM, so an unchanged digest)."""
    if not alignment.usable:
        return fixture
    return replace(fixture, words=alignment.words, pauses=alignment.pauses)


def load_recording(path: Path, *, take_id: str, family: str, stratum: str, text: str = "",
                   expected_sha256: str | None = None,
                   source_rate: int = ENGINE_SAMPLE_RATE) -> tuple[Fixture, str]:
    """Read, digest-check and adapt one take; returns the fixture and the WAV file's SHA-256.

    The WAV must be at `source_rate`; a source below the engine rate is
    resampled to it (`resampling_recipe`), so the fixture is always 24 kHz.
    """
    if not path.is_file():
        raise RecordingError(f"{take_id}: its WAV is missing")
    digest = file_sha256(path)
    if expected_sha256 is not None and digest != expected_sha256:
        raise RecordingError(f"{take_id}: its WAV digest differs from the manifest")
    samples = read_pcm16_wav(path, sample_rate=source_rate)
    if resampling_recipe(source_rate) is not None:
        samples = polyphase_resample(samples, source_rate, ENGINE_SAMPLE_RATE)
    return recording_fixture(take_id, family, stratum, samples, text=text), digest
