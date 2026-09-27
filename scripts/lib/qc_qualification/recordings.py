"""Recorded takes as injector sources (audit section 5.2, population N3).

A natural Vocello take is a 24 kHz mono PCM16 WAV the engine wrote. The
adapter reads it at its native rate (no resampling: the injectors and the Fast
QC v8 mirror both work at the engine rate; the L0 `polyphase-kaiser5-v2` path
only feeds the 16 kHz judges) and at 1/32767, the scale `pcm.to_pcm16` writes
and the v8 mirror reads back, so the source's PCM digest is the digest of the
file's own PCM16 and an identity sham writes the same samples back.

A recording carries none of what a procedural fixture knows by construction:
no word intervals (on N3 they never exist; the aligner runs on N1 and N2 only),
no declared pause intervals, no script to re-render and no render voice. Its
`text` is the request text the take was generated from, which Fast QC reads
for the pause budget and the speaking rate; no injector reads it, and nothing
here writes it out. Injectors that need any of the rest refuse the source with
`InjectorNotApplicable` (`injectors.needs`).
"""

from __future__ import annotations

import hashlib
import os
import wave
from pathlib import Path

import numpy as np

from .fixtures import Fixture, make_fixture
from .pcm import ENGINE_SAMPLE_RATE, PCM16_FULL_SCALE, to_pcm16


class RecordingError(ValueError):
    """A take's WAV is missing, unreadable, not PCM16 mono or not what its digest says."""


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


def load_recording(path: Path, *, take_id: str, family: str, stratum: str, text: str = "",
                   expected_sha256: str | None = None) -> tuple[Fixture, str]:
    """Read, digest-check and adapt one take; returns the fixture and the WAV file's SHA-256."""
    if not path.is_file():
        raise RecordingError(f"{take_id}: its WAV is missing")
    digest = file_sha256(path)
    if expected_sha256 is not None and digest != expected_sha256:
        raise RecordingError(f"{take_id}: its WAV digest differs from the manifest")
    return recording_fixture(take_id, family, stratum, read_pcm16_wav(path), text=text), digest
