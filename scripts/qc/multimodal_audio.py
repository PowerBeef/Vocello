"""Deterministic 16 kHz mono WAV normalization, local cropping, stitching and Q1 control transforms.

Used strictly by the offline, report-only multimodal audio QC complement (`RF-72`).
Intentionally excluded from `qc.detectors.SCORING_SOURCES` so existing QC v2
scoring identities and calibrated thresholds remain unchanged.
"""

from __future__ import annotations

import math
import os
import tempfile
import wave
from pathlib import Path
from typing import Any

import numpy as np

from qc import store

TARGET_RATE = 16000
DEFAULT_MARKER_SILENCE_S = 0.45
DEFAULT_MARKER_TONE_S = 0.12
DEFAULT_MARKER_FREQ_HZ = 440.0
DEFAULT_MARKER_DBFS = -18.0
DEFAULT_MARKER_FADE_S = 0.015


class MultimodalAudioError(ValueError):
    """Input WAV cannot be decoded, normalized, cropped or stitched safely."""


def read_wav_mono_float(path: Path | str) -> tuple[np.ndarray, int]:
    """Read an uncompressed PCM WAV as float64 mono in [-1.0, 1.0]."""

    wav_path = Path(path)
    if not wav_path.is_file():
        raise MultimodalAudioError(f"audio file not found: {wav_path.name}")
    try:
        with wave.open(str(wav_path), "rb") as reader:
            channels = reader.getnchannels()
            width = reader.getsampwidth()
            rate = reader.getframerate()
            nframes = reader.getnframes()
            raw = reader.readframes(nframes)
    except (wave.Error, EOFError, OSError) as error:
        raise MultimodalAudioError(f"unreadable WAV {wav_path.name}: {error}") from error
    if channels < 1 or rate < 1000 or nframes < 1:
        raise MultimodalAudioError(f"invalid WAV header in {wav_path.name}")
    if width == 2:
        data = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    elif width == 3:
        bytes_ = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
        signed = (
            bytes_[:, 0].astype(np.int32)
            | (bytes_[:, 1].astype(np.int32) << 8)
            | (bytes_[:, 2].astype(np.int32) << 16)
        )
        signed = np.where(signed >= 0x800000, signed - 0x1000000, signed)
        data = signed.astype(np.float64) / 8388608.0
    elif width == 4:
        data = np.frombuffer(raw, dtype="<i4").astype(np.float64) / 2147483648.0
    else:
        raise MultimodalAudioError(f"unsupported PCM sample width {width} in {wav_path.name}")
    if data.size != nframes * channels:
        raise MultimodalAudioError(f"truncated PCM frames in {wav_path.name}")
    if channels > 1:
        data = data.reshape(nframes, channels).mean(axis=1)
    if not np.isfinite(data).all():
        raise MultimodalAudioError(f"non-finite PCM samples in {wav_path.name}")
    return np.clip(data, -1.0, 1.0), int(rate)


def resample_audio(samples: np.ndarray, src_rate: int, dst_rate: int = TARGET_RATE) -> np.ndarray:
    """Band-limited FFT resampling for deterministic 16 kHz multimodal staging."""

    if src_rate <= 0 or dst_rate <= 0:
        raise MultimodalAudioError("sample rates must be positive")
    if samples.size == 0:
        return np.zeros(0, dtype=np.float64)
    if src_rate == dst_rate:
        return np.asarray(samples, dtype=np.float64, copy=True)
    target_len = max(1, int(round(samples.size * dst_rate / src_rate)))
    if samples.size < 16 or target_len < 16:
        old_grid = np.linspace(0.0, 1.0, samples.size, endpoint=False)
        new_grid = np.linspace(0.0, 1.0, target_len, endpoint=False)
        return np.interp(new_grid, old_grid, samples).astype(np.float64)
    spectrum = np.fft.rfft(samples)
    out_bins = target_len // 2 + 1
    resized = np.zeros(out_bins, dtype=np.complex128)
    keep = min(spectrum.size, out_bins)
    resized[:keep] = spectrum[:keep]
    # Keep Nyquist bin real-valued on even-length truncation.
    if target_len % 2 == 0 and keep == out_bins and spectrum.size > out_bins:
        resized[-1] = resized[-1].real
    out = np.fft.irfft(resized, n=target_len) * (target_len / samples.size)
    return np.clip(out, -1.0, 1.0)


def load_normalized_16k(path: Path | str, *, target_rate: int = TARGET_RATE,
                        max_seconds: float | None = None) -> np.ndarray:
    """Read a WAV, downmix to mono, resample to `target_rate`, and optionally cap length."""

    samples, rate = read_wav_mono_float(path)
    normalized = resample_audio(samples, rate, target_rate)
    if max_seconds is not None and max_seconds > 0:
        cap = int(round(max_seconds * target_rate))
        if normalized.size > cap:
            normalized = normalized[:cap]
    return normalized


def write_wav_pcm16(path: Path | str, samples: np.ndarray, rate: int = TARGET_RATE) -> dict[str, Any]:
    """Write mono 16-bit PCM WAV atomically and return its verified metadata."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    clipped = np.clip(np.asarray(samples, dtype=np.float64), -1.0, 1.0)
    pcm = np.clip(np.rint(clipped * 32767.0), -32768, 32767).astype("<i2")
    fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    os.close(fd)
    try:
        with wave.open(temporary, "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(rate)
            writer.writeframes(pcm.tobytes())
        os.replace(temporary, destination)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return {
        "sha256": store.audio_sha256(destination),
        "sampleRate": rate,
        "channels": 1,
        "samples": int(pcm.size),
        "durationSeconds": round(float(pcm.size) / float(rate), 4),
    }


def make_marker_tone(
    *,
    rate: int = TARGET_RATE,
    silence_s: float = DEFAULT_MARKER_SILENCE_S,
    tone_s: float = DEFAULT_MARKER_TONE_S,
    freq_hz: float = DEFAULT_MARKER_FREQ_HZ,
    dbfs: float = DEFAULT_MARKER_DBFS,
    fade_s: float = DEFAULT_MARKER_FADE_S,
) -> np.ndarray:
    """Build [silence | cosine-ramped 440 Hz tone | silence] delimiter for stitched streams."""

    silence_n = max(0, int(round(silence_s * rate)))
    tone_n = max(1, int(round(tone_s * rate)))
    t = np.arange(tone_n, dtype=np.float64) / float(rate)
    amp = 10.0 ** (dbfs / 20.0)
    tone = amp * np.sin(2.0 * math.pi * freq_hz * t)
    fade_n = min(tone_n // 2, max(1, int(round(fade_s * rate))))
    ramp = 0.5 * (1.0 - np.cos(math.pi * np.linspace(0.0, 1.0, fade_n)))
    tone[:fade_n] *= ramp
    tone[-fade_n:] *= ramp[::-1]
    pad = np.zeros(silence_n, dtype=np.float64)
    return np.concatenate([pad, tone, pad])


def crop_window(samples: np.ndarray, rate: int, center_s: float, window_s: float = 2.5) -> tuple[np.ndarray, float, float]:
    """Extract a bounded local zoom window centered on `center_s`, returning `(audio, start_s, end_s)`."""

    if samples.size == 0 or rate <= 0:
        raise MultimodalAudioError("cannot crop empty audio")
    duration = samples.size / float(rate)
    half = max(0.25, window_s / 2.0)
    start_s = max(0.0, center_s - half)
    end_s = min(duration, start_s + 2.0 * half)
    start_s = max(0.0, end_s - 2.0 * half)
    start_idx = max(0, int(round(start_s * rate)))
    end_idx = min(samples.size, max(start_idx + 1, int(round(end_s * rate))))
    return samples[start_idx:end_idx].copy(), round(start_idx / rate, 3), round(end_idx / rate, 3)


def stitch_segments(
    segments: list[np.ndarray],
    *,
    rate: int = TARGET_RATE,
    marker: np.ndarray | None = None,
) -> tuple[np.ndarray, list[dict[str, float]]]:
    """Concatenate audio clips into a single stream with delimiter tones and exact timelines."""

    if not segments:
        raise MultimodalAudioError("at least one audio segment is required for stitching")
    delimiter = make_marker_tone(rate=rate) if marker is None else marker
    parts: list[np.ndarray] = []
    timeline: list[dict[str, float]] = []
    cursor = 0
    for index, segment in enumerate(segments):
        if index > 0 and delimiter.size > 0:
            parts.append(delimiter)
            cursor += delimiter.size
        seg = np.asarray(segment, dtype=np.float64)
        start = cursor / float(rate)
        parts.append(seg)
        cursor += seg.size
        end = cursor / float(rate)
        timeline.append({"index": index + 1, "startSeconds": round(start, 3), "endSeconds": round(end, 3)})
    return np.concatenate(parts), timeline


def build_longform_slices(
    samples: np.ndarray,
    rate: int = TARGET_RATE,
    *,
    slice_s: float = 6.0,
    min_duration_s: float = 18.0,
) -> list[np.ndarray]:
    """Split a long recording into [opening, middle, final] slices for consistency auditing."""

    duration = samples.size / float(rate)
    if duration < min_duration_s:
        return [samples.copy()]
    slice_n = max(1, int(round(slice_s * rate)))
    mid_start = max(0, (samples.size - slice_n) // 2)
    return [
        samples[:slice_n].copy(),
        samples[mid_start:mid_start + slice_n].copy(),
        samples[-slice_n:].copy(),
    ]


def apply_harmless_transform(samples: np.ndarray, rate: int, kind: str) -> np.ndarray:
    """Apply a validity-preserving transform for Q1 C5 false-alarm invariance tests."""

    if kind == "gain_plus_3db":
        return np.clip(samples * (10.0 ** (3.0 / 20.0)), -0.98, 0.98)
    if kind == "gain_minus_3db":
        return samples * (10.0 ** (-3.0 / 20.0))
    if kind == "lead_silence_200ms":
        pad = np.zeros(int(round(0.2 * rate)), dtype=np.float64)
        return np.concatenate([pad, samples])
    raise MultimodalAudioError(f"unknown harmless transform: {kind!r}")


def apply_clear_perturbation(samples: np.ndarray, rate: int, kind: str, *, seed: int = 0) -> np.ndarray:
    """Apply an objectively audible defect for Q1 C2 order-swap sensitivity controls."""

    rng = np.random.default_rng(seed)
    out = np.asarray(samples, dtype=np.float64, copy=True)
    if kind == "heavy_noise":
        rms = float(np.sqrt(np.mean(out * out))) if out.size else 0.05
        noise = rng.normal(0.0, max(0.04, rms * 1.1), size=out.size)
        return np.clip(out + noise, -1.0, 1.0)
    if kind == "hard_clip":
        return np.clip(out * 9.0, -0.35, 0.35)
    if kind == "mid_dropout_600ms":
        drop_n = min(out.size // 2, int(round(0.6 * rate)))
        start = max(0, (out.size - drop_n) // 2)
        out[start:start + drop_n] = 0.0
        return out
    if kind == "speed_1_4x":
        # Pitch-and-tempo warp by 1.4x: unmistakably chipmunked/rushed vs clean reference.
        target_len = max(16, int(round(out.size / 1.4)))
        old_grid = np.linspace(0.0, 1.0, out.size, endpoint=False)
        new_grid = np.linspace(0.0, 1.0, target_len, endpoint=False)
        return np.interp(new_grid, old_grid, out).astype(np.float64)
    raise MultimodalAudioError(f"unknown clear perturbation: {kind!r}")
