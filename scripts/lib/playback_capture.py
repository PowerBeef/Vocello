"""Played-audio capture evidence for the macOS UI benchmark lane.

The XCUITest runner taps the Vocello app's own audio output during a take (a
Core Audio process tap with the physical output muted) and writes one capture
WAV plus a JSON sidecar per take under `<run>/playback-capture/`. This module
turns that capture and the take's published WAV into numbers a benchmark record
can carry: how late the first audible sample came after the Generate click,
how far the played audio sits from the file once aligned and gain-matched,
whether anything dropped out, how much of the take was played, and whether the
played signal carries the same step bursts the file QC measures.

Everything here is numpy-only and reference-based: the published WAV is the
reference, the capture is the measurement. Thresholds produce warn-only codes;
the lane never fails on them until a corpus justifies a gate (roadmap PC-02).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
import struct
from pathlib import Path
from typing import Any

import numpy as np

CAPTURE_STATUSES = ("captured", "silent", "unavailable", "referenceUnresolved", "aborted")
REFERENCE_RATE = 24_000
FRAME_MS = 20
SILENCE_DBFS = -50.0
REFERENCE_ACTIVE_DBFS = -40.0
DROPOUT_DROP_DB = 25.0
MIN_DROPOUT_FRAMES = 2
MAX_ALIGNMENT_LAG_S = 20.0   # the tap runs from the app's device start; the lead-in can span a whole generation
REFINE_WINDOW_MS = 50
STEP_BURST_THRESHOLD = 0.25
STEP_BURST_WINDOW_MS = 20
WARN_MISALIGNED_MS = 250.0
WARN_LOW_COVERAGE = 0.95
WARN_HIGH_RESIDUAL_DBFS = -20.0
# The app names published takes `YYYYMMDD_HH-mm-ss-SSS_<prefix>.wav` in local time.
OUTPUT_SUBDIRECTORY = {"custom": "CustomVoice", "design": "VoiceDesign", "clone": "Clones"}
OUTPUT_NAME_RE = re.compile(r"^(\d{8})_(\d{2})-(\d{2})-(\d{2})-(\d{3})_")
METRIC_KEYS = (
    "playbackCaptureAlignmentMS",
    "playbackCaptureResidualDBFS",
    "playbackCaptureDropoutCount",
    "playbackCaptureMaxGapMS",
    "playbackCaptureFirstAudibleMS",
    "playbackCaptureCoverage",
    "playbackCaptureStepBurstPeakCount",
)


class PlaybackCaptureError(ValueError):
    """A capture file or sidecar is unreadable or inconsistent."""


# ------------------------------------------------------------------ WAV I/O

def read_wav(path: Path) -> tuple[int, np.ndarray]:
    """Read a RIFF/WAVE file (PCM 16/24/32 or IEEE float32) into mono float64 in [-1, 1]."""
    data = Path(path).read_bytes()
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise PlaybackCaptureError(f"{Path(path).name}: not a RIFF/WAVE file")
    position = 12
    fmt: dict[str, int] | None = None
    payload: bytes | None = None
    while position + 8 <= len(data):
        chunk_id = data[position:position + 4]
        size = struct.unpack("<I", data[position + 4:position + 8])[0]
        body = data[position + 8:position + 8 + size]
        if chunk_id == b"fmt ":
            tag, channels, rate, _, _, bits = struct.unpack("<HHIIHH", body[:16])
            if tag == 0xFFFE and len(body) >= 26:
                tag = struct.unpack("<H", body[24:26])[0]
            fmt = {"tag": tag, "channels": channels, "rate": rate, "bits": bits}
        elif chunk_id == b"data":
            payload = body
        position += 8 + size + (size & 1)
    if fmt is None or payload is None:
        raise PlaybackCaptureError(f"{Path(path).name}: missing fmt or data chunk")
    channels, bits, tag = fmt["channels"], fmt["bits"], fmt["tag"]
    if channels < 1:
        raise PlaybackCaptureError(f"{Path(path).name}: no channels")
    if tag == 3 and bits == 32:
        samples = np.frombuffer(payload, dtype="<f4").astype(np.float64)
    elif tag == 1 and bits == 16:
        samples = np.frombuffer(payload, dtype="<i2").astype(np.float64) / 32768.0
    elif tag == 1 and bits == 32:
        samples = np.frombuffer(payload, dtype="<i4").astype(np.float64) / 2147483648.0
    elif tag == 1 and bits == 24:
        raw = np.frombuffer(payload[: len(payload) - len(payload) % 3], dtype=np.uint8).reshape(-1, 3)
        ints = (raw[:, 0].astype(np.int32) | (raw[:, 1].astype(np.int32) << 8) | (raw[:, 2].astype(np.int32) << 16))
        ints = np.where(ints >= 1 << 23, ints - (1 << 24), ints)
        samples = ints.astype(np.float64) / 8388608.0
    else:
        raise PlaybackCaptureError(f"{Path(path).name}: unsupported format tag {tag} / {bits} bits")
    frames = len(samples) // channels
    samples = samples[: frames * channels]
    if channels > 1:
        samples = samples.reshape(frames, channels).mean(axis=1)
    return int(fmt["rate"]), samples


def write_wav_float32(path: Path, rate: int, samples: np.ndarray) -> None:
    """Write mono IEEE float32 WAV (the runner's capture format) for tests and tools."""
    pcm = np.asarray(samples, dtype="<f4").tobytes()
    header = struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + len(pcm), b"WAVE", b"fmt ", 16, 3, 1,
                         int(rate), int(rate) * 4, 4, 32, b"data", len(pcm))
    Path(path).write_bytes(header + pcm)


def write_wav_int16(path: Path, rate: int, samples: np.ndarray) -> None:
    pcm = np.clip(np.asarray(samples, dtype=np.float64) * 32767.0, -32768, 32767).astype("<i2").tobytes()
    header = struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + len(pcm), b"WAVE", b"fmt ", 16, 1, 1,
                         int(rate), int(rate) * 2, 2, 16, b"data", len(pcm))
    Path(path).write_bytes(header + pcm)


# --------------------------------------------------------------- resampling

def resample(samples: np.ndarray, source_rate: int, target_rate: int = REFERENCE_RATE) -> np.ndarray:
    """Kaiser-windowed sinc polyphase resampling (zero phase, unity passband gain)."""
    x = np.asarray(samples, dtype=np.float64)
    if source_rate == target_rate or len(x) == 0:
        return x.copy()
    if source_rate <= 0 or target_rate <= 0:
        raise PlaybackCaptureError("sample rates must be positive")
    divisor = math.gcd(int(source_rate), int(target_rate))
    up, down = int(target_rate) // divisor, int(source_rate) // divisor
    scale = max(up, down)
    half = 10 * scale
    span = np.arange(2 * half + 1, dtype=np.float64) - half
    window = np.i0(5.0 * np.sqrt(np.maximum(0.0, 1.0 - (span / half) ** 2))) / np.i0(5.0)
    prototype = np.sinc(span / scale) / scale * window
    prototype *= up / math.fsum(prototype.tolist())
    total = (len(x) * up + down - 1) // down
    taps = (2 * half) // up + 1
    out = np.empty(total, dtype=np.float64)
    block = 4096
    for start in range(0, total, block):
        n = np.arange(start, min(total, start + block), dtype=np.int64)
        t = n * down
        first = -((half - t) // up)  # ceil((t - half) / up)
        i = first[:, None] + np.arange(taps, dtype=np.int64)[None, :]
        k = t[:, None] - i * up + half
        valid = (k >= 0) & (k <= 2 * half) & (i >= 0) & (i < len(x))
        coefficients = np.where(valid, prototype[np.clip(k, 0, 2 * half)], 0.0)
        out[start:start + len(n)] = np.sum(coefficients * x[np.clip(i, 0, len(x) - 1)], axis=1)
    return out


# ----------------------------------------------------------------- analysis

def frame_dbfs(samples: np.ndarray, rate: int, frame_ms: int = FRAME_MS) -> np.ndarray:
    hop = max(1, int(rate * frame_ms / 1000))
    count = len(samples) // hop
    if count == 0:
        return np.empty(0)
    frames = samples[: count * hop].reshape(count, hop)
    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1))
    return 20.0 * np.log10(np.maximum(rms, 1e-9))


def align(reference: np.ndarray, capture: np.ndarray, rate: int,
          max_lag_s: float = MAX_ALIGNMENT_LAG_S) -> int | None:
    """Capture sample index at which the reference starts (envelope search, sample refinement)."""
    hop = int(rate * FRAME_MS / 1000)
    ref_env = np.power(10.0, frame_dbfs(reference, rate) / 20.0)
    cap_env = np.power(10.0, frame_dbfs(capture, rate) / 20.0)
    if len(ref_env) < 2 or len(cap_env) < 2 or float(np.max(ref_env)) < 1e-6 or float(np.max(cap_env)) < 1e-6:
        return None
    ref_env = ref_env - ref_env.mean()
    cap_env = cap_env - cap_env.mean()
    max_lag = int(max_lag_s * 1000 / FRAME_MS)
    best_lag, best_score = None, -math.inf
    for lag in range(0, min(max_lag, len(cap_env) - 1) + 1):
        overlap = min(len(ref_env), len(cap_env) - lag)
        if overlap < 2:
            break
        score = float(np.dot(ref_env[:overlap], cap_env[lag:lag + overlap])) / math.sqrt(overlap)
        if score > best_score:
            best_lag, best_score = lag, score
    if best_lag is None:
        return None
    coarse = best_lag * hop
    # Sample-level refinement on the first second of active reference.
    active = np.where(np.abs(reference) > 10 ** (REFERENCE_ACTIVE_DBFS / 20))[0]
    if len(active) == 0:
        return coarse
    window_start = int(active[0])
    window = reference[window_start: window_start + rate]
    radius = int(rate * REFINE_WINDOW_MS / 1000)
    best_offset, best_corr = coarse, -math.inf
    norm_window = float(np.linalg.norm(window)) or 1.0
    for offset in range(coarse - radius, coarse + radius + 1):
        begin = offset + window_start
        if begin < 0 or begin + len(window) > len(capture):
            continue
        segment = capture[begin: begin + len(window)]
        corr = float(np.dot(window, segment)) / (norm_window * (float(np.linalg.norm(segment)) or 1.0))
        if corr > best_corr:
            best_offset, best_corr = offset, corr
    return best_offset


def compare(reference: np.ndarray, capture: np.ndarray, rate: int) -> dict[str, float]:
    """Alignment, gain-matched residual, dropouts and coverage of the capture against the reference."""
    lag = align(reference, capture, rate)
    if lag is None:
        return {}
    overlap = min(len(reference), len(capture) - lag)
    if overlap <= 0:
        return {}
    ref = reference[:overlap]
    cap = capture[lag: lag + overlap]
    denominator = float(np.dot(cap, cap))
    gain = float(np.dot(ref, cap)) / denominator if denominator > 0 else 0.0
    residual = ref - cap * gain
    residual_dbfs = 20.0 * math.log10(max(float(np.sqrt(np.mean(residual ** 2))), 1e-9))
    ref_db = frame_dbfs(ref, rate)
    cap_db = frame_dbfs(cap * gain, rate) if gain > 0 else frame_dbfs(cap, rate)
    dropped = (ref_db > REFERENCE_ACTIVE_DBFS) & (cap_db < ref_db - DROPOUT_DROP_DB)
    dropout_count = 0
    longest = 0
    run = 0
    for flag in dropped:
        if flag:
            run += 1
        else:
            if run >= MIN_DROPOUT_FRAMES:
                dropout_count += 1
                longest = max(longest, run)
            run = 0
    if run >= MIN_DROPOUT_FRAMES:
        dropout_count += 1
        longest = max(longest, run)
    return {
        "alignmentMS": lag * 1000.0 / rate,
        "residualDBFS": residual_dbfs,
        "dropoutCount": float(dropout_count),
        "maxGapMS": longest * float(FRAME_MS),
        "coverage": overlap / len(reference) if len(reference) else 0.0,
        "gain": gain,
    }


def step_burst_peak(samples: np.ndarray, rate: int) -> tuple[int, float | None]:
    """Densest window of sample-to-sample steps above a quarter of full scale (count, start ms)."""
    if len(samples) < 2:
        return 0, None
    large = (np.abs(np.diff(samples)) > STEP_BURST_THRESHOLD).astype(np.int64)
    window = max(1, int(rate * STEP_BURST_WINDOW_MS / 1000))
    if len(large) < window:
        count = int(large.sum())
        return count, (float(np.argmax(large)) * 1000.0 / rate if count else None)
    sums = np.convolve(large, np.ones(window, dtype=np.int64), mode="valid")
    count = int(sums.max())
    if count == 0:
        return 0, None
    start = int(np.argmax(sums))
    first = start + int(np.argmax(large[start:start + window]))
    return count, (first + 1) * 1000.0 / rate


def first_audible_ms(capture: np.ndarray, rate: int, sidecar: dict[str, Any],
                     submit_epoch_ms: float | None = None) -> float | None:
    """Milliseconds from submit to the first audible captured frame.

    The capture's first sample is the first buffer the tap delivered
    (`firstBufferEpochMS`), not the moment the runner armed the tap: the tap
    only runs once the app's output device does. The submit reference is the
    app's own wall-clock stamp (`submittedAtEpochMS` on its row) when the
    caller has it; the runner's click stamp is the fallback and precedes the
    app's submit by the UI driver's dispatch latency (seconds on a busy
    accessibility tree, not milliseconds).
    """
    start = sidecar.get("firstBufferEpochMS")
    if not isinstance(start, (int, float)):
        start = sidecar.get("captureStartEpochMS")
    click = submit_epoch_ms if isinstance(submit_epoch_ms, (int, float)) else sidecar.get("submitClickEpochMS")
    if not isinstance(start, (int, float)) or not isinstance(click, (int, float)):
        return None
    levels = frame_dbfs(capture, rate)
    audible = np.where(levels >= SILENCE_DBFS)[0]
    if len(audible) == 0:
        return None
    return float(start) + float(audible[0]) * FRAME_MS - float(click)


# -------------------------------------------------------------- run join

def load_sidecar(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise PlaybackCaptureError(f"cannot read capture sidecar {Path(path).name}: {error}") from error
    if not isinstance(payload, dict):
        raise PlaybackCaptureError(f"capture sidecar {Path(path).name} must be a JSON object")
    return payload


def collect_captures(capture_dir: Path) -> dict[tuple[int, str], dict[str, Any]]:
    """Map (takeIndex, cell) → {"sidecar": dict, "wav": Path | None} for a run's capture directory."""
    captures: dict[tuple[int, str], dict[str, Any]] = {}
    directory = Path(capture_dir)
    if not directory.is_dir():
        return captures
    for sidecar_path in sorted(directory.glob("take-*.json")):
        sidecar = load_sidecar(sidecar_path)
        index = sidecar.get("takeIndex")
        cell = sidecar.get("cell")
        if not isinstance(index, int) or not isinstance(cell, str):
            raise PlaybackCaptureError(f"capture sidecar {sidecar_path.name} lacks takeIndex/cell")
        wav = sidecar_path.with_suffix(".wav")
        captures[(index, cell)] = {"sidecar": sidecar, "wav": wav if wav.is_file() else None}
    return captures


def _local_epoch_ms(name: str) -> float | None:
    match = OUTPUT_NAME_RE.match(name)
    if not match:
        return None
    day, hour, minute, second, millis = match.groups()
    stamp = dt.datetime(int(day[:4]), int(day[4:6]), int(day[6:8]), int(hour), int(minute), int(second),
                        int(millis) * 1000)
    return stamp.timestamp() * 1000.0


def resolve_reference_wav(outputs_dir: Path, mode: str, window_start_epoch_ms: float,
                          window_end_epoch_ms: float, expected_duration_s: float | None,
                          tolerance_s: float = 0.1) -> Path | None:
    """The published take WAV: named inside the window and matching the engine's duration."""
    subdirectory = OUTPUT_SUBDIRECTORY.get(mode)
    if subdirectory is None:
        return None
    candidates = []
    for path in sorted(Path(outputs_dir, subdirectory).glob("*.wav")):
        stamp = _local_epoch_ms(path.name)
        if stamp is None or not (window_start_epoch_ms <= stamp <= window_end_epoch_ms):
            continue
        if expected_duration_s is not None:
            try:
                rate, samples = read_wav(path)
            except PlaybackCaptureError:
                continue
            if abs(len(samples) / rate - expected_duration_s) > tolerance_s:
                continue
        candidates.append(path)
    return candidates[0] if len(candidates) == 1 else None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def analyze_take(sidecar: dict[str, Any], capture_wav: Path | None,
                 reference_wav: Path | None, playback_scheduled_ms: float | None = None,
                 submit_epoch_ms: float | None = None) -> dict[str, Any]:
    """Status, numeric metrics, warn codes and digest for one take's capture.

    `playback_scheduled_ms` is the app's own submit → playback-scheduled figure
    for the take; when known, `playback.capture.misaligned` says the audible
    first frame disagrees with it by more than WARN_MISALIGNED_MS in either
    direction (the app's timeline stops at scheduling, the tap hears the result).
    """
    result: dict[str, Any] = {"status": "unavailable", "metrics": {}, "warnings": [], "digest": None}
    status = sidecar.get("status")
    if status == "aborted":
        result["status"] = "aborted"
        return result
    if capture_wav is None or status not in (None, "captured", "silent"):
        return result
    rate, capture = read_wav(capture_wav)
    result["digest"] = sha256_file(capture_wav)
    capture = resample(capture, rate, REFERENCE_RATE)
    levels = frame_dbfs(capture, REFERENCE_RATE)
    if len(levels) == 0 or float(np.max(levels)) < SILENCE_DBFS:
        result["status"] = "silent"
        result["warnings"].append("playback.capture.silent")
        return result
    metrics: dict[str, float] = {}
    audible = first_audible_ms(capture, REFERENCE_RATE, sidecar, submit_epoch_ms)
    if audible is not None:
        metrics["playbackCaptureFirstAudibleMS"] = round(audible, 1)
    count, _ = step_burst_peak(capture, REFERENCE_RATE)
    metrics["playbackCaptureStepBurstPeakCount"] = float(count)
    if reference_wav is None:
        result["status"] = "referenceUnresolved"
        result["metrics"] = metrics
        return result
    reference_rate, reference = read_wav(reference_wav)
    reference = resample(reference, reference_rate, REFERENCE_RATE)
    comparison = compare(reference, capture, REFERENCE_RATE)
    result["status"] = "captured"
    if not comparison:
        result["warnings"].append("playback.capture.misaligned")
        result["metrics"] = metrics
        return result
    metrics.update({
        "playbackCaptureAlignmentMS": round(comparison["alignmentMS"], 1),
        "playbackCaptureResidualDBFS": round(comparison["residualDBFS"], 1),
        "playbackCaptureDropoutCount": comparison["dropoutCount"],
        "playbackCaptureMaxGapMS": round(comparison["maxGapMS"], 1),
        "playbackCaptureCoverage": round(comparison["coverage"], 3),
    })
    warnings = result["warnings"]
    if (audible is not None and isinstance(playback_scheduled_ms, (int, float))
            and abs(audible - float(playback_scheduled_ms)) > WARN_MISALIGNED_MS):
        warnings.append("playback.capture.misaligned")
    if comparison["dropoutCount"] > 0:
        warnings.append("playback.capture.dropouts")
    if comparison["coverage"] < WARN_LOW_COVERAGE:
        warnings.append("playback.capture.low_coverage")
    if comparison["residualDBFS"] > WARN_HIGH_RESIDUAL_DBFS:
        warnings.append("playback.capture.high_residual")
    result["metrics"] = metrics
    return result
