"""Corpus clips as the audio QC tools read them: mono PCM16 WAV at 16 or 24 kHz, with their labels.

Shared by `scripts/audio_qc_corpora.py` (the system interpreter: WAV files and
the WAVs inside zip and tar archives) and `scripts/audio_qc_corpora_worker.py`
(the pinned Parquet runtime: the audio cells of Parquet shards), so a clip is
written and labelled the same way whichever path reads it. numpy and the
standard library only.

- **Decoding.** A RIFF/WAVE file is parsed here: integer PCM of 8, 16, 24 or 32
  bits and IEEE float of 32 or 64 bits, plain or WAVE_FORMAT_EXTENSIBLE.
  Anything else is refused here; the worker decodes other containers (FLAC,
  Ogg Opus, MP3) with soundfile and hands the samples to `clip_from_samples`.
  A data chunk declared longer than the file (a streamed WAV that never wrote
  its size) is read to the file's last whole frame and marked
  `dataChunkTruncated`; a clip with no sample, or a non-finite one, is refused.
- **Scale.** Integer samples are read at their format's full scale (32767 for
  16 bits, 8388607 for 24, 2147483647 for 32, and 127 around 128 for unsigned 8
  bits); float samples as they are.
- **Channels.** Averaged to mono.
- **Rate.** A clip at another rate than its source's output rate (16 or 24 kHz,
  the rates `lib.qc_qualification.recordings` reads) is resampled with the
  Kaiser (beta 5), 10-zero-crossing polyphase design of
  `lib.playback_capture.resample`, the one the calibration tools already use.
- **PCM16.** Each sample x 32767, rounded half to even and clipped to +-32767,
  the clipped samples counted. A mono PCM16 clip already at the output rate
  keeps its samples exactly.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
import re
import struct
from typing import Any, Mapping
import wave

import numpy as np

from .playback_capture import resample

OUTPUT_RATES = (16_000, 24_000)
PCM16_FULL_SCALE = 32767
RESAMPLER = "kaiser5-polyphase"
RESAMPLER_IMPLEMENTATION = "scripts/lib/playback_capture.py resample"
WAV_PCM, WAV_FLOAT, WAV_EXTENSIBLE = 1, 3, 0xFFFE
# The labels a clip may carry, whatever its corpus names them.
EMOTIONS = ("neutral", "happy", "sad", "angry", "fearful", "disgusted", "surprised", "bored")
GENDERS = {"m": "male", "male": "male", "man": "male", "f": "female", "female": "female", "woman": "female",
           "w": "female"}
CLIP_ID = re.compile(r"[A-Za-z0-9._-]+")
UNSAFE_ID_CHARACTERS = re.compile(r"[^A-Za-z0-9._-]+")


class CorpusAudioError(ValueError):
    """One clip cannot be decoded or written; its extraction lists it as skipped, with this reason."""


# --------------------------------------------------------------------------- #
# Decoding
# --------------------------------------------------------------------------- #

def is_wav(data: bytes) -> bool:
    return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE"


def _wav_chunks(data: bytes) -> tuple[bytes, bytes, bool]:
    """The `fmt ` and `data` chunk bodies, and whether the data chunk ran past the file's end."""
    if not is_wav(data):
        raise CorpusAudioError("not a RIFF/WAVE file")
    fmt: bytes | None = None
    payload: bytes | None = None
    truncated = False
    position = 12
    while position + 8 <= len(data):
        identifier = data[position:position + 4]
        size = struct.unpack("<I", data[position + 4:position + 8])[0]
        body = data[position + 8:position + 8 + size]
        if identifier == b"data":
            if payload is not None:
                raise CorpusAudioError("its data chunk appears twice")
            payload = body
            truncated = len(body) != size
        elif identifier == b"fmt ":
            if fmt is not None:
                raise CorpusAudioError("its fmt chunk appears twice")
            if len(body) != size:
                raise CorpusAudioError("its fmt chunk is truncated")
            fmt = body
        position += 8 + size + (size & 1)
    if fmt is None or payload is None:
        raise CorpusAudioError("it has no fmt or data chunk")
    return fmt, payload, truncated


def decode_wav(data: bytes) -> tuple[np.ndarray, int, dict[str, Any]]:
    """A WAV's frames (samples x channels, at the format's own scale), its rate and what it was.

    Integer PCM of 16 bits is returned as int16, other integer widths as int64
    and float as float64; `scale` says how to reach [-1, 1].
    """
    fmt, payload, truncated = _wav_chunks(data)
    if len(fmt) < 16:
        raise CorpusAudioError("its fmt chunk is too short")
    tag, channels, rate, _byte_rate, align, bits = struct.unpack("<HHIIHH", fmt[:16])
    if tag == WAV_EXTENSIBLE:
        if len(fmt) < 40:
            raise CorpusAudioError("its extensible fmt chunk is too short")
        tag = struct.unpack("<H", fmt[24:26])[0]
    if channels < 1 or rate < 1 or align < 1 or align % channels:
        raise CorpusAudioError("its fmt chunk declares no channel, rate or frame size")
    width = align // channels
    usable = len(payload) - len(payload) % align
    if usable != len(payload) and not truncated:
        raise CorpusAudioError("its data chunk ends inside a frame")
    payload = payload[:usable]
    if tag == WAV_PCM and width in (1, 2, 3, 4) and bits <= 8 * width:
        if width == 1:
            frames = np.frombuffer(payload, dtype=np.uint8).astype(np.int64) - 128
            scale = 127.0
        elif width == 2:
            frames = np.frombuffer(payload, dtype="<i2")
            scale = float(PCM16_FULL_SCALE)
        elif width == 3:
            raw = np.frombuffer(payload, dtype=np.uint8).reshape(-1, 3).astype(np.int64)
            frames = raw[:, 0] | (raw[:, 1] << 8) | (raw[:, 2] << 16)
            frames = np.where(frames >= 1 << 23, frames - (1 << 24), frames)
            scale = float((1 << 23) - 1)
        else:
            frames = np.frombuffer(payload, dtype="<i4").astype(np.int64)
            scale = float((1 << 31) - 1)
        kind = f"wav-pcm{8 * width}"
    elif tag == WAV_FLOAT and width in (4, 8):
        frames = np.frombuffer(payload, dtype="<f4" if width == 4 else "<f8").astype(np.float64)
        if not np.all(np.isfinite(frames)):
            raise CorpusAudioError("it holds a non-finite sample")
        scale = 1.0
        kind = f"wav-float{8 * width}"
    else:
        raise CorpusAudioError(f"its format is neither integer PCM nor IEEE float (format {tag}, {bits} bits)")
    frames = frames.reshape(-1, channels)
    if frames.shape[0] == 0:
        raise CorpusAudioError("it holds no sample")
    return frames, rate, {"sourceFormat": kind, "sourceRate": rate, "sourceChannels": channels, "scale": scale,
                          "dataChunkTruncated": truncated}


# --------------------------------------------------------------------------- #
# Conforming and writing
# --------------------------------------------------------------------------- #

def wav_bytes(pcm: np.ndarray, rate: int) -> bytes:
    """Canonical mono PCM16 WAV bytes (a 44-byte header)."""
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(np.asarray(pcm, dtype="<i2").tobytes())
    return output.getvalue()


def conform(frames: np.ndarray, rate: int, *, scale: float, output_rate: int) -> tuple[np.ndarray, dict[str, Any]]:
    """Frames (samples x channels) as mono PCM16 at `output_rate`, and what that took."""
    if output_rate not in OUTPUT_RATES:
        raise CorpusAudioError(f"the output rate is one of {', '.join(str(value) for value in OUTPUT_RATES)} Hz")
    if frames.ndim != 2 or frames.shape[0] == 0 or frames.shape[1] == 0:
        raise CorpusAudioError("it holds no sample")
    if frames.dtype == np.int16 and frames.shape[1] == 1 and rate == output_rate:
        return frames[:, 0].astype("<i2"), {"resampled": False, "clippedSamples": 0}
    values = frames.astype(np.float64) / scale
    mono = values[:, 0] if values.shape[1] == 1 else values.mean(axis=1)
    if not np.all(np.isfinite(mono)):
        raise CorpusAudioError("it holds a non-finite sample")
    resampled = rate != output_rate
    if resampled:
        mono = resample(mono, rate, output_rate)
    scaled = np.rint(mono * PCM16_FULL_SCALE)
    clipped = int(np.count_nonzero(np.abs(scaled) > PCM16_FULL_SCALE))
    pcm = np.clip(scaled, -PCM16_FULL_SCALE, PCM16_FULL_SCALE).astype("<i2")
    if pcm.size == 0:
        raise CorpusAudioError("it holds no sample at the output rate")
    return pcm, {"resampled": resampled, "clippedSamples": clipped}


def clip_from_samples(frames: np.ndarray, rate: int, *, scale: float, output_rate: int,
                      source: Mapping[str, Any]) -> tuple[bytes, dict[str, Any]]:
    """The clip's WAV bytes and its audio facts, from decoded frames and what the decoder said."""
    pcm, done = conform(frames, rate, scale=scale, output_rate=output_rate)
    info = {"sampleRate": output_rate, "samples": int(pcm.size),
            "durationSeconds": round(pcm.size / output_rate, 6), **done,
            "sourceFormat": source["sourceFormat"], "sourceRate": int(source["sourceRate"]),
            "sourceChannels": int(source["sourceChannels"])}
    if source.get("dataChunkTruncated"):
        info["dataChunkTruncated"] = True
    return wav_bytes(pcm, output_rate), info


def clip_from_wav(data: bytes, *, output_rate: int) -> tuple[bytes, dict[str, Any]]:
    """A WAV file's bytes as the clip to write, and its audio facts."""
    frames, rate, source = decode_wav(data)
    return clip_from_samples(frames, rate, scale=source["scale"], output_rate=output_rate, source=source)


# --------------------------------------------------------------------------- #
# Labels
# --------------------------------------------------------------------------- #

def clip_id(*parts: str) -> str:
    """A clip id of letters, digits, '.', '_' and '-' (the take-id alphabet) from its parts."""
    joined = "-".join(UNSAFE_ID_CHARACTERS.sub("_", str(part)).strip("_") for part in parts if str(part))
    if not joined or not CLIP_ID.fullmatch(joined):
        raise CorpusAudioError("the clip has no usable id")
    return joined


def label_text(value: Any) -> str | None:
    """A label as a stripped string, or None when absent or empty."""
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    return text or None


def gender(value: Any, mapping: Mapping[str, str] | None = None) -> str | None:
    """`male`, `female`, a mapped value, or None: never a guess."""
    text = label_text(value)
    if text is None:
        return None
    if mapping and text in mapping:
        return mapping[text]
    return GENDERS.get(text.lower())


def emotion(value: Any, mapping: Mapping[str, str] | None) -> tuple[str | None, str | None]:
    """The corpus's own emotion label and its canonical name (`EMOTIONS`), when the registry maps it."""
    text = label_text(value)
    if text is None:
        return None, None
    canonical = (mapping or {}).get(text, (mapping or {}).get(text.lower()))
    return text, canonical if canonical in EMOTIONS else None


# --------------------------------------------------------------------------- #
# The clip sink
# --------------------------------------------------------------------------- #

# Every clip record carries these labels (None when its corpus has none).
LABEL_FIELDS = ("language", "split", "sourceID", "speaker", "gender", "emotion", "emotionCanonical", "intensity",
                "accent", "scores", "text", "textID")


class ClipSink:
    """Writes each clip once under `wav/` and records it; identical PCM is one clip with its duplicates.

    The audit's unit of independence is the source family, deduplicated by PCM
    digest (section 5.4): a clip whose PCM16 bytes equal an earlier clip's (the
    MLS 1-hour set may repeat clips of the 9-hour set) is not written again but
    listed under that clip's `duplicates`. A clip id already taken by other
    audio is skipped with its reason, never overwritten.
    """

    def __init__(self, wav_directory: Path) -> None:
        self.wav_directory = Path(wav_directory)
        self.wav_directory.mkdir(parents=True, exist_ok=True)
        self.clips: list[dict[str, Any]] = []
        self.skipped: list[dict[str, str]] = []
        self._by_digest: dict[str, dict[str, Any]] = {}
        self._ids: set[str] = set()

    def skip(self, origin: str, reason: str) -> None:
        self.skipped.append({"origin": origin, "reason": reason})

    def add(self, identifier: str, data: bytes, info: Mapping[str, Any], labels: Mapping[str, Any], *,
            origin: str, source_sha256: str) -> str:
        """`written`, `duplicate` or `skipped`."""
        digest = hashlib.sha256(data).hexdigest()
        if digest in self._by_digest:
            self._by_digest[digest]["duplicates"].append({"origin": origin, "split": labels.get("split"),
                                                          "sourceID": labels.get("sourceID")})
            return "duplicate"
        if identifier in self._ids or not CLIP_ID.fullmatch(identifier):
            self.skip(origin, f"its clip id {identifier} is already taken by other audio")
            return "skipped"
        with (self.wav_directory / f"{identifier}.wav").open("xb") as handle:
            handle.write(data)
        source = {"origin": origin, "sha256": source_sha256, "format": info["sourceFormat"],
                  "sampleRate": info["sourceRate"], "channels": info["sourceChannels"]}
        if info.get("dataChunkTruncated"):
            source["dataChunkTruncated"] = True
        record = {"clipID": identifier, "family": identifier, **{field: labels.get(field) for field in LABEL_FIELDS},
                  "durationSeconds": info["durationSeconds"], "sampleRate": info["sampleRate"],
                  "samples": info["samples"], "wavPath": f"wav/{identifier}.wav", "wavSHA256": digest,
                  "wavBytes": len(data), "resampled": info["resampled"], "clippedSamples": info["clippedSamples"],
                  "source": source, "duplicates": []}
        self.clips.append(record)
        self._by_digest[digest] = record
        self._ids.add(identifier)
        return "written"

    def result(self) -> dict[str, Any]:
        return {"clips": self.clips, "skipped": self.skipped,
                "duplicates": sum(len(clip["duplicates"]) for clip in self.clips)}
