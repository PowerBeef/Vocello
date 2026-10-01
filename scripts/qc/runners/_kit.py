"""Shared plumbing for the QC v2 signal and judge runners (RMVPE, SwiftF0, ReDimNet, UTMOSv2,
Audiobox, the llama.cpp judges): the job file, WAV input, resampling, the variant key and atomic
result writes, as the runner protocol in the QC v2 contract defines them.

numpy and the standard library only, so every runtime (onnx, torch, llamacpp) and the test python
can import it. soundfile and scipy are used when the runtime has them.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import struct
import tempfile
import time
import wave
from math import gcd
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import numpy as np

RESULT_SCHEMA = "vocello.qc.result/1"


class TakeError(Exception):
    """A per-take failure with a stable, privacy-safe code (never paths or transcripts)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# --- job ---------------------------------------------------------------------------------------


def parse_job_argument(argv: Iterable[str] | None = None) -> Path:
    parser = argparse.ArgumentParser(description="QC v2 runner")
    parser.add_argument("--job", required=True, type=Path)
    return parser.parse_args(list(argv) if argv is not None else None).job


def load_job(path: Path) -> dict[str, Any]:
    job = json.loads(Path(path).read_text(encoding="utf-8"))
    for key in ("model", "modelDir", "outputDir", "runnerSHA256", "takes"):
        if key not in job:
            raise SystemExit(f"job is missing {key}")
    job.setdefault("options", {})
    return job


def variant_key(take: Mapping[str, Any]) -> str:
    """The short hex of `(text, language, reference)` for outputs that depend on them; the same
    canonical JSON digest as the host's `qc.store.variant_key`."""
    payload = json.dumps(
        {"text": take.get("text"), "language": take.get("language"), "reference": take.get("referenceSHA256")},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def result_path(output_dir: Path | str, audio_sha256: str, variant: str | None, suffix: str = ".json") -> Path:
    stem = audio_sha256 if not variant else f"{audio_sha256}.{variant}"
    return Path(output_dir) / f"{stem}{suffix}"


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def write_result(
    job: Mapping[str, Any],
    take: Mapping[str, Any],
    *,
    outputs: Mapping[str, Any] | None = None,
    error: str | None = None,
    duration: float | None = None,
    variant: str | None = None,
) -> Path:
    """Write `<outputDir>/<audioSHA256>[.<variantKey>].json` atomically; `error` replaces `outputs`."""
    record: dict[str, Any] = {
        "schema": RESULT_SCHEMA,
        "model": job["model"],
        "runnerSHA256": job["runnerSHA256"],
        "audioSHA256": take["audioSHA256"],
        "variantKey": variant,
        "durationSeconds": None if duration is None else round(float(duration), 4),
    }
    if error is not None:
        record["error"] = error
    else:
        record["outputs"] = outputs
    path = result_path(job["outputDir"], take["audioSHA256"], variant)
    data = json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    _atomic_write_bytes(path, data + b"\n")
    return path


def write_npz(job: Mapping[str, Any], take: Mapping[str, Any], variant: str | None, **arrays: np.ndarray) -> str:
    """Write the take's `.npz` sidecar atomically and return its file name for `outputs`."""
    path = result_path(job["outputDir"], take["audioSHA256"], variant, ".npz")
    buffer = io.BytesIO()
    np.savez_compressed(buffer, **arrays)
    _atomic_write_bytes(path, buffer.getvalue())
    return path.name


def progress(model: str, done: int, total: int) -> None:
    print(f"[{model}] {done}/{total}", flush=True)


ProcessTake = Callable[[Any, Mapping[str, Any], Mapping[str, Any]], "tuple[dict[str, Any], float, str | None]"]


VariantOf = Callable[[Mapping[str, Any]], "str | None"]


def take_variant(take: Mapping[str, Any], variant_of: VariantOf | None = None) -> str | None:
    """The take's result variant: the host's `variantKey` when the job carries one (it decides
    which models are variant-keyed), else `variant_of(take)`."""
    if "variantKey" in take:
        return take["variantKey"]
    return variant_of(take) if variant_of else None


def run_job(job: Mapping[str, Any], model: Any, process: ProcessTake, variant_of: VariantOf | None = None) -> int:
    """Process every take with an already-loaded model. `process(model, take, job)` returns
    `(outputs, durationSeconds, variantKey)` or raises; a failure becomes the take's `error` code and
    the loop continues. Results go under the job take's `variantKey` when it has one. Returns 0
    when every take succeeded."""
    takes = list(job["takes"])
    failures = 0
    for index, take in enumerate(takes, start=1):
        try:
            outputs, duration, variant = process(model, take, job)
            variant = take["variantKey"] if "variantKey" in take else variant
            write_result(job, take, outputs=outputs, duration=duration, variant=variant)
        except Exception as failure:  # noqa: BLE001 - one take never stops the batch
            failures += 1
            code = failure.code if isinstance(failure, TakeError) else f"failed:{type(failure).__name__}"
            write_result(job, take, error=code, variant=take_variant(take, variant_of))
        progress(job["model"], index, len(takes))
    return 0 if failures == 0 else 1


def fail_all(job: Mapping[str, Any], code: str, variant_of: Callable[[Mapping[str, Any]], str | None] | None = None) -> int:
    """Record the same error for every take (the model failed to load) and return exit code 1."""
    for take in job["takes"]:
        write_result(job, take, error=code, variant=take_variant(take, variant_of))
    return 1


def main(
    load: Callable[[Mapping[str, Any]], Any],
    process: ProcessTake,
    variant_of: Callable[[Mapping[str, Any]], str | None] | None = None,
    argv: Iterable[str] | None = None,
    close: Callable[[Any], None] | None = None,
) -> int:
    """The runner entry point: read the job, load the model once, process every take, close."""
    job = load_job(parse_job_argument(argv))
    started = time.monotonic()
    try:
        model = load(job)
    except Exception as failure:  # noqa: BLE001
        print(f"[{job['model']}] model load failed: {type(failure).__name__}", flush=True)
        return fail_all(job, f"model-load-failed:{type(failure).__name__}", variant_of)
    try:
        code = run_job(job, model, process, variant_of)
    finally:
        if close is not None:
            close(model)
    print(f"[{job['model']}] done in {time.monotonic() - started:.1f}s", flush=True)
    return code


# --- audio -------------------------------------------------------------------------------------


def read_wav(path: str | Path) -> tuple[np.ndarray, int]:
    """Mono float32 samples in [-1, 1] and the sample rate. soundfile when available, else a
    RIFF/WAVE reader for PCM 8/16/24/32-bit and IEEE float 32/64 (also WAVE_FORMAT_EXTENSIBLE)."""
    try:
        import soundfile  # type: ignore

        data, sr = soundfile.read(str(path), dtype="float32", always_2d=True)
        return np.ascontiguousarray(data.mean(axis=1), dtype=np.float32), int(sr)
    except ImportError:
        pass
    raw = Path(path).read_bytes()
    if len(raw) < 12 or raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        raise TakeError("audio-unreadable")
    offset = 12
    fmt: tuple[int, int, int, int] | None = None
    data_bytes: bytes | None = None
    while offset + 8 <= len(raw):
        chunk, size = raw[offset:offset + 4], struct.unpack("<I", raw[offset + 4:offset + 8])[0]
        body = raw[offset + 8:offset + 8 + size]
        if chunk == b"fmt ":
            tag, channels, sr = struct.unpack("<HHI", body[:8])
            bits = struct.unpack("<H", body[14:16])[0]
            if tag == 0xFFFE and len(body) >= 26:
                tag = struct.unpack("<H", body[24:26])[0]
            fmt = (tag, channels, sr, bits)
        elif chunk == b"data":
            data_bytes = body
        offset += 8 + size + (size & 1)
    if fmt is None or data_bytes is None:
        raise TakeError("audio-unreadable")
    tag, channels, sr, bits = fmt
    width = bits // 8
    if channels < 1 or width < 1:
        raise TakeError("audio-unreadable")
    usable = len(data_bytes) - len(data_bytes) % (width * channels)
    data_bytes = data_bytes[:usable]
    if tag == 3 and bits in (32, 64):
        samples = np.frombuffer(data_bytes, dtype="<f4" if bits == 32 else "<f8").astype(np.float32)
    elif tag == 1 and bits == 8:
        samples = (np.frombuffer(data_bytes, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif tag == 1 and bits == 16:
        samples = np.frombuffer(data_bytes, dtype="<i2").astype(np.float32) / 32768.0
    elif tag == 1 and bits == 24:
        triplets = np.frombuffer(data_bytes, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        values = triplets[:, 0] | (triplets[:, 1] << 8) | (triplets[:, 2] << 16)
        values = np.where(values >= 1 << 23, values - (1 << 24), values)
        samples = values.astype(np.float32) / float(1 << 23)
    elif tag == 1 and bits == 32:
        samples = np.frombuffer(data_bytes, dtype="<i4").astype(np.float32) / float(1 << 31)
    else:
        raise TakeError("audio-unsupported-format")
    samples = samples.reshape(-1, channels).mean(axis=1)
    return np.ascontiguousarray(samples, dtype=np.float32), int(sr)


def resample(samples: np.ndarray, sr: int, target: int) -> np.ndarray:
    """Band-limited resampling: scipy's polyphase filter when available, else an FFT resample."""
    samples = np.asarray(samples, dtype=np.float32)
    if sr == target or samples.size == 0:
        return samples
    try:
        from scipy.signal import resample_poly  # type: ignore

        divisor = gcd(int(sr), int(target))
        return resample_poly(samples, target // divisor, sr // divisor).astype(np.float32)
    except ImportError:
        pass
    count = int(round(samples.size * target / sr))
    spectrum = np.fft.rfft(samples.astype(np.float64))
    bins = count // 2 + 1
    if bins <= spectrum.size:
        spectrum = spectrum[:bins]
    else:
        spectrum = np.concatenate((spectrum, np.zeros(bins - spectrum.size, dtype=spectrum.dtype)))
    return (np.fft.irfft(spectrum, n=count) * (count / samples.size)).astype(np.float32)


def load_take_audio(take: Mapping[str, Any], target_sr: int | None = None, key: str = "audio") -> tuple[np.ndarray, int, float]:
    """The take's (or its reference's) mono audio, resampled to `target_sr` when given, and its
    duration in seconds at the source rate."""
    path = take.get(key)
    if not path:
        raise TakeError(f"{key}-missing")
    try:
        samples, sr = read_wav(path)
    except TakeError:
        raise
    except Exception:  # noqa: BLE001
        raise TakeError(f"{key}-unreadable") from None
    if samples.size == 0:
        raise TakeError(f"{key}-empty")
    duration = samples.size / float(sr)
    if target_sr is not None and sr != target_sr:
        samples, sr = resample(samples, sr, target_sr), target_sr
    return samples, sr, duration


def wav_bytes(samples: np.ndarray, sr: int) -> bytes:
    """16-bit PCM mono WAV bytes."""
    pcm = np.clip(np.rint(np.asarray(samples, dtype=np.float64) * 32767.0), -32768, 32767).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(int(sr))
        writer.writeframes(pcm.tobytes())
    return buffer.getvalue()


def windows(duration: float, length: float, hop: float) -> list[tuple[float, float]]:
    """`length`-second windows every `hop` seconds covering `[0, duration]`; the last window is
    aligned to the end. A take shorter than `length` is one whole-take window."""
    if duration <= length + 1e-9:
        return [(0.0, float(duration))]
    starts = list(np.arange(0.0, duration - length + 1e-9, hop))
    if duration - (starts[-1] + length) > 1e-6:
        starts.append(duration - length)
    return [(round(float(s), 6), round(float(s) + length, 6)) for s in starts]


def rounded(values: Iterable[float | None], digits: int = 4) -> list[float | None]:
    return [None if v is None or not np.isfinite(v) else round(float(v), digits) for v in values]


def unit(vector: np.ndarray) -> list[float]:
    """An L2-normalized embedding as a JSON-ready list."""
    vector = np.asarray(vector, dtype=np.float64).reshape(-1)
    norm = float(np.linalg.norm(vector))
    if not np.isfinite(norm) or norm == 0:
        raise TakeError("embedding-degenerate")
    return [round(float(v), 6) for v in vector / norm]


def repository_root() -> Path:
    return Path(__file__).resolve().parents[3]
