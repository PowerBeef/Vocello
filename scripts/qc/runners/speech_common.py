"""Shared plumbing for the speech runners (Qwen3-ASR, Qwen3-ForcedAligner, Whisper, ZIPA and the
wav2vec2 phone fallback): the job file, WAV input and resampling, variant keys, atomic result
writes and the per-take loop, as the QC v2 contract's runner protocol defines them.

Standard library plus NumPy, so every runtime and the repository's test python can import it.
`variant_key` and `result_stem` match `qc.store`; a job's own `variantKey` always wins.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import struct
import sys
import tempfile
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

import numpy as np

RESULT_SCHEMA = "vocello.qc.result/1"
SAMPLE_RATE = 16000
LANGUAGES = (
    "chinese", "english", "french", "german", "italian",
    "japanese", "korean", "portuguese", "russian", "spanish",
)
DEBUG_VARIABLE = "QC_RUNNER_DEBUG"  # 1 prints tracebacks (they may hold paths: local debugging only)


class TakeError(Exception):
    """A per-take failure with a stable, privacy-safe code (never a path or a transcript)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# --- keys and records -------------------------------------------------------------------------


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def variant_key(text: str | None, language: str | None, reference_sha256: str | None) -> str:
    """Short hex of (text, language, reference), identical to `qc.store.variant_key`."""

    payload = canonical_json({"language": language, "reference": reference_sha256, "text": text})
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def take_variant(take: Mapping[str, Any], *, depends: bool) -> str | None:
    """The job's `variantKey` when the host gave one, else the key for a dependent output."""

    if "variantKey" in take:
        return take["variantKey"]
    if not depends:
        return None
    return variant_key(take.get("text"), take.get("language"), take.get("referenceSHA256"))


def result_stem(audio_sha256: str, variant: str | None) -> str:
    return f"{audio_sha256}.{variant}" if variant else audio_sha256


def result_record(job: Mapping[str, Any], take: Mapping[str, Any], *, variant: str | None,
                  duration: float | None, outputs: dict[str, Any] | None = None, error: str | None = None,
                  **extra: Any) -> dict[str, Any]:
    if (outputs is None) == (error is None):
        raise ValueError("a result carries either outputs or an error")
    record: dict[str, Any] = {
        "schema": RESULT_SCHEMA, "model": job["model"], "runnerSHA256": job["runnerSHA256"],
        "audioSHA256": take["audioSHA256"], "variantKey": variant,
        "durationSeconds": None if duration is None else round(float(duration), 4),
    }
    if error is not None:
        record["error"] = error
        record.update(extra)
    else:
        record["outputs"] = outputs
    return record


def _write_atomic(path: Path, write: Callable[[Any], None], mode: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, mode, **({"encoding": "utf-8"} if "b" not in mode else {})) as stream:
            write(stream)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def write_json_atomic(path: Path | str, value: Any) -> None:
    def write(stream: Any) -> None:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True)
        stream.write("\n")

    _write_atomic(Path(path), write, "w")


def write_npz_atomic(path: Path | str, arrays: Mapping[str, np.ndarray]) -> None:
    _write_atomic(Path(path), lambda stream: np.savez_compressed(stream, **arrays), "wb")


def load_job(path: Path | str) -> dict[str, Any]:
    job = json.loads(Path(path).read_text(encoding="utf-8"))
    for key in ("model", "modelDir", "outputDir", "runnerSHA256", "takes"):
        if key not in job:
            raise ValueError(f"job is missing {key}")
    job["options"] = dict(job.get("options") or {})
    return job


# --- audio --------------------------------------------------------------------------------------


def file_sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_riff(data: bytes) -> tuple[np.ndarray, int]:
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("not a RIFF/WAVE file")
    position, fmt, payload = 12, None, None
    while position + 8 <= len(data):
        chunk, size = data[position:position + 4], int.from_bytes(data[position + 4:position + 8], "little")
        body = data[position + 8:position + 8 + size]
        if chunk == b"fmt ":
            fmt = body
        elif chunk == b"data":
            payload = body
        position += 8 + size + (size & 1)
    if fmt is None or payload is None or len(fmt) < 16:
        raise ValueError("WAV without fmt or data")
    tag, channels, rate, _, _, bits = struct.unpack("<HHIIHH", fmt[:16])
    if tag == 0xFFFE and len(fmt) >= 26:  # WAVE_FORMAT_EXTENSIBLE: the subformat GUID starts with the tag
        tag = int.from_bytes(fmt[24:26], "little")
    width = bits // 8
    if channels < 1 or width < 1:
        raise ValueError("bad WAV format")
    frames = len(payload) // (width * channels)
    raw = payload[:frames * width * channels]
    if tag == 1 and width == 1:
        samples = (np.frombuffer(raw, np.uint8).astype(np.float64) - 128.0) / 128.0
    elif tag == 1 and width == 2:
        samples = np.frombuffer(raw, "<i2") / 32768.0
    elif tag == 1 and width == 3:
        triples = np.frombuffer(raw, np.uint8).reshape(-1, 3).astype(np.int32)
        values = triples[:, 0] | (triples[:, 1] << 8) | (triples[:, 2] << 16)
        samples = np.where(values >= 1 << 23, values - (1 << 24), values) / float(1 << 23)
    elif tag == 1 and width == 4:
        samples = np.frombuffer(raw, "<i4") / float(1 << 31)
    elif tag == 3 and width in (4, 8):
        samples = np.frombuffer(raw, "<f4" if width == 4 else "<f8").astype(np.float64)
    else:
        raise ValueError("unsupported WAV encoding")
    return samples.reshape(-1, channels).mean(axis=1).astype(np.float32), int(rate)


def read_wav(path: Path | str) -> tuple[np.ndarray, int]:
    """Mono float32 samples and the sample rate (soundfile when installed, else a RIFF reader)."""

    try:
        import soundfile
    except ImportError:
        soundfile = None
    if soundfile is not None:
        data, rate = soundfile.read(str(path), dtype="float32", always_2d=True)
        return data.mean(axis=1).astype(np.float32), int(rate)
    return _read_riff(Path(path).read_bytes())


def resample(samples: np.ndarray, rate_in: int, rate_out: int, *, zero_crossings: int = 32,
             beta: float = 8.6) -> np.ndarray:
    """Band-limited resampling: a Kaiser-windowed sinc evaluated per polyphase phase.

    The low-pass sits at the lower Nyquist, so downsampling 24 kHz speech to 16 kHz rejects the
    8-12 kHz band instead of folding it back.
    """

    signal = np.asarray(samples, dtype=np.float64)
    if rate_in == rate_out or signal.size == 0:
        return signal.astype(np.float32)
    common = math.gcd(int(rate_in), int(rate_out))
    up, down = int(rate_out) // common, int(rate_in) // common
    cutoff = min(1.0, up / down)
    width = zero_crossings / cutoff
    reach = int(math.ceil(width))
    taps = np.arange(-reach + 1, reach + 1)
    distance = taps[None, :] - (np.arange(up) / up)[:, None]
    window = np.i0(beta * np.sqrt(np.clip(1.0 - (distance / width) ** 2, 0.0, None))) / np.i0(beta)
    weights = np.where(np.abs(distance) < width, cutoff * np.sinc(cutoff * distance) * window, 0.0)
    weights /= weights.sum(axis=1, keepdims=True)
    count = (signal.size * up) // down
    numerator = np.arange(count, dtype=np.int64) * down
    base, phase = numerator // up, numerator % up
    padded = np.pad(signal, (reach, reach))
    output = np.zeros(count)
    for column, tap in enumerate(taps):
        output += weights[phase, column] * padded[base + tap + reach]
    return output.astype(np.float32)


def load_take_audio(take: Mapping[str, Any], *, rate: int = SAMPLE_RATE, verify: bool = True
                    ) -> tuple[np.ndarray, float]:
    """The take's audio, mono at `rate`, and its duration; the bytes must match `audioSHA256`."""

    path = Path(str(take["audio"]))
    try:
        if verify and file_sha256(path) != take["audioSHA256"]:
            raise TakeError("audio-digest-mismatch")
        samples, source_rate = read_wav(path)
    except TakeError:
        raise
    except (OSError, ValueError, RuntimeError):
        raise TakeError("audio-unreadable") from None
    if samples.size == 0 or source_rate <= 0:
        raise TakeError("audio-empty")
    return resample(samples, source_rate, rate), samples.size / float(source_rate)


def language_windows(duration: float | None, window: float = 10.0) -> list[tuple[float, float]]:
    """Full-length windows for language ID on takes longer than one window, else none.

    Windows start every `window` seconds; when the last one would run past the end it is moved
    back to end with the take, so every window holds `window` seconds of audio.
    """

    if duration is None or duration <= window:
        return []
    spans, start = [], 0.0
    while start + window <= duration + 1e-9:
        spans.append((round(start, 3), round(start + window, 3)))
        start += window
    if spans[-1][1] < duration - 1e-6:
        spans.append((round(duration - window, 3), round(duration, 3)))
    return spans


def window_audio(audio: np.ndarray, start: float, end: float, rate: int = SAMPLE_RATE) -> np.ndarray:
    return audio[int(round(start * rate)):int(round(end * rate))]


# --- the runner loop ----------------------------------------------------------------------------


@dataclass
class TakeContext:
    take: Mapping[str, Any]
    audio: np.ndarray | None
    duration: float | None
    variant: str | None
    stem: str
    npz_name: str


@contextlib.contextmanager
def stdout_to_stderr() -> Iterator[None]:
    """Library chatter goes to stderr; stdout carries only progress lines."""

    with contextlib.redirect_stdout(sys.stderr):
        yield


def offline() -> None:
    """Model files are verified locally; nothing may reach the network at load time."""

    for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE"):
        os.environ.setdefault(name, "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


def _debug() -> None:
    if os.environ.get(DEBUG_VARIABLE) == "1":
        traceback.print_exc(file=sys.stderr)


Process = Callable[[TakeContext], "tuple[dict[str, Any], dict[str, np.ndarray] | None]"]


def run_job(job: Mapping[str, Any], process: Process, *, depends: bool = False, needs_audio: bool = True) -> int:
    """Process every take and write its result (or its error) atomically; 0 when all succeeded."""

    output_dir = Path(job["outputDir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    takes = list(job.get("takes") or [])
    failures = 0
    for index, take in enumerate(takes, start=1):
        variant = take_variant(take, depends=depends)
        stem = result_stem(take["audioSHA256"], variant)
        duration = None
        try:
            audio = None
            if needs_audio:
                audio, duration = load_take_audio(take)
            context = TakeContext(take, audio, duration, variant, stem, f"{stem}.npz")
            with stdout_to_stderr():
                outputs, arrays = process(context)
            if arrays:
                write_npz_atomic(output_dir / context.npz_name, arrays)
            record = result_record(job, take, variant=variant, duration=duration, outputs=outputs)
        except TakeError as error:
            failures += 1
            record = result_record(job, take, variant=variant, duration=duration, error=error.code)
        except Exception as error:  # noqa: BLE001 - one take's failure never stops the job
            failures += 1
            _debug()
            print(f"qc runner: take {index} failed ({type(error).__name__})", file=sys.stderr)
            record = result_record(job, take, variant=variant, duration=duration, error="runner-exception",
                                   exception=type(error).__name__)
        write_json_atomic(output_dir / f"{stem}.json", record)
        print(f"progress {index}/{len(takes)}", flush=True)
    return 0 if failures == 0 else 1


def main(argv: list[str] | None, *, build_engine: Callable[[Mapping[str, Any]], Any],
         process: Callable[[Any, TakeContext, Mapping[str, Any]], Any], depends: bool = False) -> int:
    """`python -m qc.runners.<name> --job job.json`: 0 all takes done, 1 some failed, 2 no run."""

    parser = argparse.ArgumentParser(description="QC v2 speech runner")
    parser.add_argument("--job", required=True)
    args = parser.parse_args(argv)
    try:
        job = load_job(args.job)
    except (OSError, ValueError) as error:
        print(f"qc runner: unreadable job ({type(error).__name__})", file=sys.stderr)
        return 2
    offline()
    try:
        with stdout_to_stderr():
            engine = build_engine(job)
    except Exception as error:  # noqa: BLE001 - reported as a code, never as text
        _debug()
        print(f"qc runner: {job['model']}: model load failed ({type(error).__name__})", file=sys.stderr)
        return 2
    options = job["options"]
    return run_job(job, lambda context: process(engine, context, options), depends=depends)
