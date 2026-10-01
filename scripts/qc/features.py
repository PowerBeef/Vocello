"""Per-take features from the runner outputs, each with time-localized evidence.

A feature is `{"value": float or None, "start": seconds or None, "end": seconds or None}`;
None means the inputs were unavailable (a model not run, a take it failed on).
`extract(take, results, context, params)` reads the cached results by role (the
`models` map of `config/qc/detectors.json`: asrA, asrB, align, phones, pitchA,
pitchB, speaker, mos, aesthetics, llm) and returns every feature the detectors
name. `build_context` computes the lane-level references: voice pitch and speaker
centroids, clone-reference pitch, and per-cell aesthetics baselines.

Phones come from `qc.phones` (G2P, alignment, GOP) and pitch from `qc.pitch`;
both are imported guardedly, so a missing module only leaves its features None
(and tests can substitute stubs).
"""

from __future__ import annotations

import importlib
import math
import struct
import unicodedata
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np

from qc import store


def _optional(name: str) -> Any:
    try:
        return importlib.import_module(f"qc.{name}")
    except ImportError:
        return None


phones = _optional("phones")
pitch = _optional("pitch")

Feature = dict[str, Any]
CJK_LANGUAGES = {"chinese", "japanese"}
SCRIPTS = {
    "chinese": ("CJK",), "japanese": ("CJK", "HIRAGANA", "KATAKANA"), "korean": ("HANGUL",),
    "russian": ("CYRILLIC",),
}
LLM_CLASSES = ("stutter", "mispronunciation", "wrong-language", "cutoff", "pause", "pitch", "tonal-collapse",
               "voice-change", "artifact", "unnatural")
AUDIO_FEATURES = (
    "signal.clicks", "signal.dropout_seconds", "signal.clipping_fraction", "signal.terminal_silence_seconds",
    "signal.abrupt_offset_db", "pause.longest_gap_seconds", "pause.nonspeech_level_db", "pause.voiced_blips",
    "pause.mute_confirmed", "end.drop_db_60ms", "end.tail_seconds", "end.decay_db_per_ms", "level.lufs",
    "level.lufs_deviation", "level.true_peak_dbtp", "level.lra",
)


def feature(value: Any = None, start: Any = None, end: Any = None) -> Feature:
    def clean(number: Any) -> float | None:
        if number is None:
            return None
        number = float(number)
        return round(number, 6) if math.isfinite(number) else None

    return {"value": clean(value), "start": clean(start), "end": clean(end)}


def outputs(results: dict[str, Any], role: str) -> dict[str, Any] | None:
    result = results.get(role)
    if not isinstance(result, dict) or "error" in result:
        return None
    value = result.get("outputs")
    return value if isinstance(value, dict) else None


# --- audio --------------------------------------------------------------------

def read_wav(path: str | Path) -> tuple[np.ndarray, int]:
    """Mono float32 samples and the rate, for PCM 16/24/32-bit and IEEE float WAVs."""

    raw = Path(path).read_bytes()
    if raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        raise ValueError("not a WAV file")
    offset, fmt, data = 12, None, None
    while offset + 8 <= len(raw):
        chunk, size = raw[offset:offset + 4], struct.unpack("<I", raw[offset + 4:offset + 8])[0]
        body = raw[offset + 8:offset + 8 + size]
        if chunk == b"fmt ":
            tag, channels, rate = struct.unpack("<HHI", body[:8])
            bits = struct.unpack("<H", body[14:16])[0]
            if tag == 0xFFFE and len(body) >= 26:
                tag = struct.unpack("<H", body[24:26])[0]
            fmt = (tag, channels, rate, bits)
        elif chunk == b"data":
            data = body
        offset += 8 + size + (size & 1)
    if fmt is None or data is None:
        raise ValueError("WAV without fmt or data")
    tag, channels, rate, bits = fmt
    width = bits // 8
    data = data[: len(data) - len(data) % (width * channels)]
    if tag == 3 and bits in (32, 64):
        samples = np.frombuffer(data, dtype="<f4" if bits == 32 else "<f8").astype(np.float32)
    elif tag == 1 and bits == 16:
        samples = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0
    elif tag == 1 and bits == 24:
        triplets = np.frombuffer(data, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        values = triplets[:, 0] | (triplets[:, 1] << 8) | (triplets[:, 2] << 16)
        samples = np.where(values >= 1 << 23, values - (1 << 24), values).astype(np.float32) / float(1 << 23)
    elif tag == 1 and bits == 32:
        samples = np.frombuffer(data, dtype="<i4").astype(np.float32) / float(1 << 31)
    else:
        raise ValueError("unsupported WAV format")
    return samples.reshape(-1, channels).mean(axis=1), int(rate)


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    if mask.size == 0:
        return []
    padded = np.concatenate(([False], mask.astype(bool), [False]))
    edges = np.flatnonzero(np.diff(padded.astype(np.int8)))
    return [(int(edges[i]), int(edges[i + 1])) for i in range(0, edges.size, 2)]


def signal_features(samples: np.ndarray, rate: int, params: dict[str, Any]) -> dict[str, Feature]:
    """DSP checks: clicks, internal dropouts, clipping, terminal silence and an abrupt offset."""

    out: dict[str, Feature] = {}
    x = np.asarray(samples, dtype=np.float64)
    if x.size < rate // 20:
        return {name: feature() for name in ("signal.clicks", "signal.dropout_seconds", "signal.clipping_fraction",
                                             "signal.terminal_silence_seconds", "signal.abrupt_offset_db")}
    second = np.diff(x, n=2)
    mad = float(np.median(np.abs(second - np.median(second)))) * 1.4826 + 1e-9
    spikes = np.flatnonzero(np.abs(second) > params.get("clickSigma", 12.0) * mad + 0.05)
    # One click spans a few samples: count clusters 5 ms apart.
    clusters = 0 if spikes.size == 0 else 1 + int(np.sum(np.diff(spikes) > rate * 0.005))
    worst = int(spikes[np.argmax(np.abs(second[spikes]))]) if spikes.size else None
    out["signal.clicks"] = feature(clusters, worst / rate if worst is not None else None,
                                   worst / rate if worst is not None else None)

    silent = np.abs(x) < params.get("silenceAmplitude", 0.0005)
    voiced = np.flatnonzero(~silent)
    first, last = (int(voiced[0]), int(voiced[-1])) if voiced.size else (0, x.size - 1)
    gaps = [(s, e) for s, e in _runs(silent[first:last + 1])]
    longest = max(gaps, key=lambda gap: gap[1] - gap[0], default=None)
    if longest and longest[1] - longest[0] >= rate * 0.02:  # digital silence inside speech
        out["signal.dropout_seconds"] = feature((longest[1] - longest[0]) / rate, (first + longest[0]) / rate,
                                                (first + longest[1]) / rate)
    else:
        out["signal.dropout_seconds"] = feature(0.0)
    clipped = np.flatnonzero(np.abs(x) >= 0.999)
    out["signal.clipping_fraction"] = feature(
        clipped.size / x.size, clipped[0] / rate if clipped.size else None, clipped[-1] / rate if clipped.size else None)
    out["signal.terminal_silence_seconds"] = feature((x.size - 1 - last) / rate, (last + 1) / rate, x.size / rate)

    frame = max(1, int(rate * 0.05))
    energies = np.array([np.sqrt(np.mean(x[i:i + frame] ** 2)) for i in range(first, last + 1 - frame + 1, frame)] or [0.0])
    speech_db = 20 * np.log10(np.median(energies[energies > 0]) + 1e-12) if np.any(energies > 0) else None
    tail = x[max(first, last + 1 - frame):last + 1]
    tail_db = 20 * np.log10(np.sqrt(np.mean(tail ** 2)) + 1e-12) if tail.size else None
    out["signal.abrupt_offset_db"] = feature(
        None if speech_db is None or tail_db is None else tail_db - speech_db, max(0, last + 1 - frame) / rate,
        (last + 1) / rate)
    return out


# --- frame profile, pauses, the ending, loudness -----------------------------------

def _db(value: np.ndarray | float) -> np.ndarray | float:
    return 20.0 * np.log10(np.maximum(value, 1e-12))


def frame_profile(samples: np.ndarray, rate: int, window: float = 0.025, hop: float = 0.010) -> dict[str, np.ndarray]:
    """Per frame: start time, level (dBFS RMS), spectral centroid (Hz), zero-crossing rate and
    periodicity (the normalized autocorrelation peak for 60-400 Hz)."""

    x = np.asarray(samples, dtype=np.float64)
    size, step = max(16, int(round(window * rate))), max(1, int(round(hop * rate)))
    if x.size < size:
        x = np.pad(x, (0, size - x.size))
    frames = np.lib.stride_tricks.sliding_window_view(x, size)[::step]
    times = np.arange(frames.shape[0]) * step / rate
    level = _db(np.sqrt(np.mean(frames ** 2, axis=1)))
    spectrum = np.abs(np.fft.rfft(frames * np.hanning(size), axis=1))
    frequencies = np.fft.rfftfreq(size, 1.0 / rate)
    centroid = (spectrum * frequencies).sum(axis=1) / np.maximum(spectrum.sum(axis=1), 1e-12)
    signs = np.signbit(frames)
    zcr = np.mean(signs[:, 1:] != signs[:, :-1], axis=1)
    centered = frames - frames.mean(axis=1, keepdims=True)
    padded = np.fft.rfft(centered, n=2 * size, axis=1)
    autocorrelation = np.fft.irfft(np.abs(padded) ** 2, axis=1)[:, :size]
    low, high = max(1, int(rate / 400)), min(size - 1, int(rate / 60))
    energy = np.maximum(autocorrelation[:, 0], 1e-12)
    periodicity = autocorrelation[:, low:high + 1].max(axis=1) / energy if high > low else np.zeros(len(frames))
    return {"time": times, "level": level, "centroid": centroid, "zcr": zcr,
            "periodicity": np.clip(periodicity, 0.0, 1.0), "hop": np.array(step / rate),
            "window": np.array(size / rate)}


def _speech_frames(profile: dict[str, np.ndarray]) -> tuple[np.ndarray, float | None]:
    """Voiced speech frames (periodic, within 30 dB of the loud frames) and their median level."""

    level = profile["level"]
    if not np.isfinite(level).any():
        return np.zeros(level.size, dtype=bool), None
    loud = float(np.percentile(level, 95))
    voiced = (profile["periodicity"] >= 0.45) & (level > max(-60.0, loud - 30.0))
    return voiced, (float(np.median(level[voiced])) if voiced.any() else None)


def pause_features(samples: np.ndarray, rate: int, aligned: dict[str, Any] | None) -> dict[str, Feature]:
    """The longest non-speech stretch inside the sentence.

    Voiced speech is periodic and near speech level; a voiced run under 120 ms with at
    least 150 ms of non-speech on both sides is a blip, not speech. A gap is any stretch
    between the first and last speech frames without speech, or between two aligned words.
    Features: its length, its loudest non-speech frame relative to the speech median (a
    breath-like hiss at speech level is not a pause), and the blips inside it.
    """

    names = ("pause.longest_gap_seconds", "pause.nonspeech_level_db", "pause.voiced_blips")
    out = {name: feature() for name in names}
    out["pause.mute_confirmed"] = feature()
    profile = frame_profile(samples, rate)
    hop = float(profile["hop"])
    voiced, speech_median = _speech_frames(profile)
    indices = np.flatnonzero(voiced)
    if indices.size < 2 or speech_median is None:
        return out
    runs = _runs(voiced)
    blip_frames = int(round(0.12 / hop))
    margin = int(round(0.15 / hop))
    speech = voiced.copy()
    blips: list[tuple[int, int]] = []
    for position, (start, end) in enumerate(runs):
        before = start - runs[position - 1][1] if position > 0 else None
        after = runs[position + 1][0] - end if position + 1 < len(runs) else None
        if end - start < blip_frames and before is not None and after is not None and before >= margin and after >= margin:
            speech[start:end] = False
            blips.append((start, end))
    inside = np.flatnonzero(speech)
    if inside.size < 2:
        return out
    first, last = int(inside[0]), int(inside[-1])
    gaps = [(first + start, first + end) for start, end in _runs(~speech[first:last + 1])]
    best = max(gaps, key=lambda gap: gap[1] - gap[0], default=None)
    gap_seconds, gap_start, gap_end = 0.0, None, None
    if best:
        gap_start, gap_end = float(profile["time"][best[0]]), float(profile["time"][best[1] - 1]) + hop
        gap_seconds = gap_end - gap_start
    words = [word for word in (aligned or {}).get("words") or []
             if word.get("start") is not None and word.get("end") is not None]
    for previous, current in zip(words, words[1:]):
        silence = float(current["start"]) - float(previous["end"])
        if silence > gap_seconds:
            gap_seconds, gap_start, gap_end = silence, float(previous["end"]), float(current["start"])
    out["pause.longest_gap_seconds"] = feature(gap_seconds, gap_start, gap_end)
    if gap_start is None:
        out["pause.nonspeech_level_db"] = feature(None)
        out["pause.voiced_blips"] = feature(0)
        return out
    frames = (profile["time"] >= gap_start - 1e-9) & (profile["time"] + hop <= gap_end + 1e-9)
    in_blip = np.zeros(voiced.size, dtype=bool)
    for start, end in blips:
        in_blip[start:end] = True
    nonspeech = frames & ~in_blip & ~voiced
    loudest = float(profile["level"][nonspeech].max()) if nonspeech.any() else None
    out["pause.nonspeech_level_db"] = feature(None if loudest is None else loudest - speech_median, gap_start, gap_end)
    inside_blips = [(start, end) for start, end in blips
                    if profile["time"][start] >= gap_start - 1e-9 and profile["time"][end - 1] < gap_end]
    out["pause.voiced_blips"] = feature(len(inside_blips), *(
        (float(profile["time"][inside_blips[0][0]]), float(profile["time"][inside_blips[-1][1] - 1]) + hop)
        if inside_blips else (None, None)))
    return out


def end_features(samples: np.ndarray, rate: int) -> dict[str, Feature]:
    """How the last word ends, from 10 ms levels: the drop within 60 ms of the final peak, the
    tail from the first 10 dB below it down to -60 dBFS, and the decay slope."""

    names = ("end.drop_db_60ms", "end.tail_seconds", "end.decay_db_per_ms")
    out = {name: feature() for name in names}
    x = np.asarray(samples, dtype=np.float64)
    step = max(1, int(round(0.010 * rate)))
    count = x.size // step
    if count < 10:
        return out
    level = _db(np.sqrt(np.mean(x[:count * step].reshape(count, step) ** 2, axis=1)))
    level = np.concatenate([level, np.full(3, -120.0)])  # a cut at the file's end is a drop to silence
    loud = float(np.percentile(level[:count], 95))
    above = np.flatnonzero(level[:count] > loud - 25.0)
    if above.size == 0:
        return out
    speech_end = int(above[-1])
    window_start = max(0, speech_end - 15)
    peak = window_start + int(np.argmax(level[window_start:speech_end + 1]))
    plateau = float(level[peak])
    onset = next((index for index in range(peak, level.size) if level[index] <= plateau - 10.0), level.size - 1)
    decay_start = max(peak, onset - 1)
    while decay_start > peak and level[decay_start] < plateau - 6.0:
        decay_start -= 1
    floor = next((index for index in range(onset, level.size) if level[index] <= -60.0), level.size - 1)
    drop = float(level[decay_start]) - float(level[decay_start:decay_start + 7].min())
    tail = (floor - onset) * 0.010
    span_ms = max(10.0, (floor - decay_start) * 10.0)
    out["end.drop_db_60ms"] = feature(drop, decay_start * 0.010, min(count, decay_start + 6) * 0.010)
    out["end.tail_seconds"] = feature(tail, onset * 0.010, min(count, floor) * 0.010)
    out["end.decay_db_per_ms"] = feature((float(level[decay_start]) - float(level[floor])) / span_ms,
                                         decay_start * 0.010, min(count, floor) * 0.010)
    return out


# ITU-R BS.1770-4 K-weighting for any rate (the analog-matched biquads of libebur128).
def k_weighting(rate: int) -> list[tuple[np.ndarray, np.ndarray]]:
    f0, gain, q = 1681.974450955533, 3.999843853973347, 0.7071752369554196
    k = math.tan(math.pi * f0 / rate)
    vh = 10 ** (gain / 20.0)
    vb = vh ** 0.4996667741545416
    a0 = 1.0 + k / q + k * k
    shelf = (np.array([(vh + vb * k / q + k * k) / a0, 2.0 * (k * k - vh) / a0, (vh - vb * k / q + k * k) / a0]),
             np.array([1.0, 2.0 * (k * k - 1.0) / a0, (1.0 - k / q + k * k) / a0]))
    f0, q = 38.13547087602444, 0.5003270373238773
    k = math.tan(math.pi * f0 / rate)
    a0 = 1.0 + k / q + k * k
    highpass = (np.array([1.0, -2.0, 1.0]), np.array([1.0, 2.0 * (k * k - 1.0) / a0, (1.0 - k / q + k * k) / a0]))
    return [shelf, highpass]


def _apply_biquads(x: np.ndarray, rate: int, sections: list[tuple[np.ndarray, np.ndarray]]) -> np.ndarray:
    """Causal IIR filtering in the frequency domain, padded by a second so the response decays."""

    size = 1 << int(math.ceil(math.log2(x.size + rate)))
    spectrum = np.fft.rfft(x, n=size)
    z = np.exp(-1j * 2 * np.pi * np.arange(spectrum.size) / size)
    for b, a in sections:
        spectrum *= (b[0] + b[1] * z + b[2] * z * z) / (a[0] + a[1] * z + a[2] * z * z)
    return np.fft.irfft(spectrum, n=size)[:x.size]


def integrated_loudness(samples: np.ndarray, rate: int) -> float | None:
    """BS.1770-4 integrated loudness (LUFS) of a mono signal, with absolute and relative gating."""

    x = np.asarray(samples, dtype=np.float64)
    block, step = int(round(0.4 * rate)), int(round(0.1 * rate))
    if x.size < block:
        return None
    weighted = _apply_biquads(x, rate, k_weighting(rate))
    starts = range(0, x.size - block + 1, step)
    power = np.array([np.mean(weighted[start:start + block] ** 2) for start in starts])
    loudness = -0.691 + 10 * np.log10(np.maximum(power, 1e-20))
    kept = power[loudness > -70.0]
    if kept.size == 0:
        return None
    relative = -0.691 + 10 * np.log10(kept.mean()) - 10.0
    kept = power[(loudness > -70.0) & (loudness > relative)]
    return float(-0.691 + 10 * np.log10(kept.mean())) if kept.size else None


def loudness_range(samples: np.ndarray, rate: int) -> float | None:
    """EBU Tech 3342 loudness range (LU) from 3 s short-term blocks; None under 3 s."""

    x = np.asarray(samples, dtype=np.float64)
    block, step = int(3 * rate), int(round(0.1 * rate))
    if x.size < block:
        return None
    weighted = _apply_biquads(x, rate, k_weighting(rate))
    power = np.array([np.mean(weighted[start:start + block] ** 2) for start in range(0, x.size - block + 1, step)])
    loudness = -0.691 + 10 * np.log10(np.maximum(power, 1e-20))
    kept = power[loudness > -70.0]
    if kept.size == 0:
        return None
    relative = -0.691 + 10 * np.log10(kept.mean()) - 20.0
    gated = loudness[(loudness > -70.0) & (loudness > relative)]
    return float(np.percentile(gated, 95) - np.percentile(gated, 10)) if gated.size else None


def true_peak_dbtp(samples: np.ndarray, oversample: int = 4) -> float | None:
    x = np.asarray(samples, dtype=np.float64)
    if x.size == 0:
        return None
    spectrum = np.fft.rfft(x)
    upsampled = np.fft.irfft(spectrum, n=x.size * oversample) * oversample
    return float(_db(max(np.abs(upsampled).max(), np.abs(x).max())))


def loudness_features(samples: np.ndarray, rate: int, target: float = -23.0) -> dict[str, Feature]:
    lufs = integrated_loudness(samples, rate)
    return {
        "level.lufs": feature(lufs),
        "level.lufs_deviation": feature(None if lufs is None else abs(lufs - target)),
        "level.true_peak_dbtp": feature(true_peak_dbtp(samples)),
        "level.lra": feature(loudness_range(samples, rate)),
    }


def mute_wav(source: str | Path, destination: str | Path, start: float, end: float) -> Path:
    """Copy a PCM or float WAV with `[start, end)` seconds silenced, keeping its format."""

    raw = bytearray(Path(source).read_bytes())
    offset, fmt = 12, None
    while offset + 8 <= len(raw):
        chunk, size = bytes(raw[offset:offset + 4]), struct.unpack("<I", raw[offset + 4:offset + 8])[0]
        if chunk == b"fmt ":
            tag, channels, rate = struct.unpack("<HHI", raw[offset + 8:offset + 16])
            block_align, bits = struct.unpack("<HH", raw[offset + 20:offset + 24])
            fmt = (rate, block_align, bits)
        elif chunk == b"data" and fmt:
            rate, block_align, bits = fmt
            first = offset + 8 + min(size, int(round(start * rate)) * block_align)
            last = offset + 8 + min(size, int(round(end * rate)) * block_align)
            raw[first:last] = (b"\x80" if bits == 8 else b"\x00") * (last - first)
            break
        offset += 8 + size + (size & 1)
    else:
        raise ValueError("WAV without a data chunk")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".part")
    temporary.write_bytes(bytes(raw))
    temporary.replace(destination)
    return destination


def transcript_distance(original: str, other: str, language: str | None) -> float | None:
    """Normalized word (character, for Chinese and Japanese) edit distance between two transcripts."""

    reference = normalize_text(original, language)
    hypothesis = normalize_text(other, language)
    if not reference:
        return None
    edits = sum(1 for op in edit_alignment(reference, hypothesis) if op[0] != "match")
    return edits / len(reference)


# --- text and ASR ------------------------------------------------------------

def normalize_text(text: str, language: str | None) -> list[str]:
    """Words (characters for Chinese and Japanese), lowercased, without punctuation."""

    text = unicodedata.normalize("NFKC", text or "").lower()
    text = "".join(" " if unicodedata.category(ch)[0] in "PSZC" else ch for ch in text)
    if language in CJK_LANGUAGES:
        return [ch for ch in text if not ch.isspace()]
    return text.split()


def edit_alignment(reference: list[str], hypothesis: list[str]) -> list[tuple[str, int | None, int | None]]:
    """Levenshtein alignment: (op, reference index, hypothesis index), op in match/sub/ins/del."""

    rows, cols = len(reference) + 1, len(hypothesis) + 1
    cost = np.zeros((rows, cols), dtype=np.int32)
    cost[:, 0] = np.arange(rows)
    cost[0, :] = np.arange(cols)
    for i in range(1, rows):
        for j in range(1, cols):
            same = reference[i - 1] == hypothesis[j - 1]
            cost[i, j] = min(cost[i - 1, j - 1] + (0 if same else 1), cost[i - 1, j] + 1, cost[i, j - 1] + 1)
    ops: list[tuple[str, int | None, int | None]] = []
    i, j = rows - 1, cols - 1
    while i > 0 or j > 0:
        if i > 0 and j > 0 and cost[i, j] == cost[i - 1, j - 1] + (0 if reference[i - 1] == hypothesis[j - 1] else 1):
            ops.append(("match" if reference[i - 1] == hypothesis[j - 1] else "sub", i - 1, j - 1))
            i, j = i - 1, j - 1
        elif i > 0 and cost[i, j] == cost[i - 1, j] + 1:
            ops.append(("del", i - 1, None))
            i -= 1
        else:
            ops.append(("ins", None, j - 1))
            j -= 1
    return ops[::-1]


def _asr_edit(take: dict[str, Any], asr: dict[str, Any] | None) -> Feature | None:
    if asr is None or not take.get("text"):
        return None
    language = take.get("language")
    reference = normalize_text(take["text"], language)
    hypothesis = normalize_text(asr.get("text") or "", language)
    if not reference:
        return None
    ops = edit_alignment(reference, hypothesis)
    errors = [op for op in ops if op[0] in ("ins", "del")]
    words = asr.get("words") or []
    span_start = span_end = None
    inserted = [op[2] for op in errors if op[0] == "ins" and op[2] is not None]
    if inserted and language not in CJK_LANGUAGES and len(words) == len(hypothesis):
        span_start, span_end = words[inserted[0]].get("start"), words[inserted[-1]].get("end")
    return feature(len(errors) / len(reference), span_start, span_end)


def asr_language(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip().strip("<|>").strip().lower()
    try:
        return store.normalize_language(cleaned)
    except ValueError:
        return None


def _language_mismatch(take: dict[str, Any], asr: dict[str, Any] | None) -> float | None:
    if asr is None:
        return None
    expected = take.get("language")
    probabilities = asr.get("languageProbs")
    if isinstance(probabilities, dict) and probabilities:
        normalized: dict[str, float] = {}
        for key, probability in probabilities.items():
            name = asr_language(key)
            if name and isinstance(probability, (int, float)):
                normalized[name] = normalized.get(name, 0.0) + float(probability)
        if normalized:
            return 1.0 - normalized.get(expected, 0.0)
    detected = asr_language(asr.get("language"))
    return None if detected is None else float(detected != expected)


def script_mismatch(text: str, language: str | None) -> float | None:
    letters = [ch for ch in text or "" if ch.isalpha()]
    if not letters:
        return None
    expected = SCRIPTS.get(language or "", ("LATIN",))
    wrong = 0
    for ch in letters:
        name = unicodedata.name(ch, "")
        if not any(name.startswith(script) for script in expected):
            wrong += 1
    return wrong / len(letters)


def _min(values: Iterable[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return min(present) if present else None


def asr_features(take: dict[str, Any], results: dict[str, Any]) -> dict[str, Feature]:
    asrs = [outputs(results, "asrA"), outputs(results, "asrB")]
    edits = [_asr_edit(take, asr) for asr in asrs]
    present = [edit for edit in edits if edit is not None]
    # Both families must hear the error: the smaller rate, localized where that family found it.
    best = min(present, key=lambda edit: edit["value"]) if len(present) == 2 else None
    language = take.get("language")
    return {
        "asr.edit_rate_min": best or feature(),
        "asr.language_mismatch_min": feature(_min(_language_mismatch(take, asr) for asr in asrs)
                                             if all(asr is not None for asr in asrs) else None),
        "asr.script_mismatch_min": feature(_min(script_mismatch(asr.get("text") or "", language) for asr in asrs)
                                           if all(asr is not None for asr in asrs) else None),
    }


def align_features(take: dict[str, Any], results: dict[str, Any]) -> dict[str, Feature]:
    aligned = outputs(results, "align")
    words = [word for word in (aligned or {}).get("words") or [] if word.get("start") is not None
             and word.get("end") is not None]
    if len(words) < 2:
        return {"align.last_word_ratio": feature()}
    durations = [max(0.0, float(word["end"]) - float(word["start"])) for word in words]
    typical = float(np.median(durations[:-1])) or 1e-3
    last = words[-1]
    return {"align.last_word_ratio": feature(durations[-1] / typical, last["start"], last["end"])}


# --- phones ----------------------------------------------------------------------

_OPS = {"match": "match", "equal": "match", "ok": "match", "sub": "sub", "substitute": "sub",
        "substitution": "sub", "ins": "ins", "insert": "ins", "insertion": "ins", "del": "del",
        "delete": "del", "deletion": "del"}


def _op(name: Any) -> str:
    return _OPS.get(str(name).lower(), str(name).lower())


def phone_features(take: dict[str, Any], results: dict[str, Any], layout: store.Layout,
                   model_ids: dict[str, str], params: dict[str, Any]) -> dict[str, Feature]:
    names = ("phones.deletion_rate", "phones.repeat_runs", "phones.low_gop_run", "phones.last_word_coverage",
             "phones.gop_mean", "phones.substitution_rate", "phones.l1_substitutions")
    empty = {name: feature() for name in names}
    recognized_out = outputs(results, "phones")
    if phones is None or recognized_out is None or not take.get("text"):
        return empty
    language = take.get("language")
    try:
        expected = list(phones.g2p(take["text"], language))
    except Exception:  # noqa: BLE001 - a G2P gap leaves the features unavailable
        return empty
    recognized = recognized_out.get("phones") or []
    if not expected:
        return empty
    ops = [(_op(op), exp, rec, start, end) for op, exp, rec, start, end in phones.align(expected, recognized)]
    out = dict(empty)
    deletions = [op for op in ops if op[0] == "del"]
    out["phones.deletion_rate"] = feature(len(deletions) / len(expected), *_span(deletions))
    substitutions = [op for op in ops if op[0] == "sub"]
    out["phones.substitution_rate"] = feature(len(substitutions) / len(expected), *_span(substitutions))
    pairs = {tuple(pair) for pair in params.get("l1Substitutions", {}).get(language, [])}
    l1 = [op for op in ops if (op[0] == "sub" and (op[1], op[2]) in pairs) or (op[0] == "del" and (op[1], "") in pairs)]
    out["phones.l1_substitutions"] = feature(len(l1), *_span(l1)) if pairs else feature()
    repeats = _repeat_runs(ops)
    longest = max(repeats, key=lambda run: len(run), default=[])
    out["phones.repeat_runs"] = feature(len(repeats), *_span(longest))

    last_word = normalize_text(take["text"], language)[-1:] if language not in CJK_LANGUAGES else []
    tail_length = len(phones.g2p(last_word[0], language)) if last_word else max(1, len(expected) // 10)
    tail = _expected_ops(ops)[-tail_length:]
    covered = [op for op in tail if op[0] in ("match", "sub")]
    out["phones.last_word_coverage"] = feature(len(covered) / max(1, len(tail)), *_span(tail))

    posteriors = recognized_out.get("posteriors")
    if posteriors and hasattr(phones, "gop"):
        path = layout.results_dir(model_ids["phones"]) / Path(posteriors).name
        try:
            with np.load(path, allow_pickle=False) as arrays:
                scores = [float(score) for score in phones.gop(arrays["logprobs"], list(arrays["vocab"]), expected)]
        except (OSError, KeyError, ValueError):
            scores = []
        if scores:
            out["phones.gop_mean"] = feature(float(np.mean(scores)))
            low = np.array([score < params.get("gopLow", -2.0) for score in scores])
            runs = _runs(low)
            if runs:
                start, end = max(runs, key=lambda run: run[1] - run[0])
                expected_ops = _expected_ops(ops)
                span = _span(expected_ops[start:end]) if len(expected_ops) == len(scores) else (None, None)
                out["phones.low_gop_run"] = feature(end - start, *span)
            else:
                out["phones.low_gop_run"] = feature(0)
    return out


def _expected_ops(ops: list[tuple]) -> list[tuple]:
    return [op for op in ops if op[0] in ("match", "sub", "del")]


def _span(ops: list[tuple]) -> tuple[float | None, float | None]:
    starts = [op[3] for op in ops if op[3] is not None]
    ends = [op[4] for op in ops if op[4] is not None]
    return (min(starts) if starts else None, max(ends) if ends else None)


def _repeat_runs(ops: list[tuple]) -> list[list[tuple]]:
    """Runs of inserted phones that repeat the recognized phones right after or before them."""

    recognized = [(index, op) for index, op in enumerate(ops) if op[0] in ("match", "sub", "ins")]
    runs: list[list[tuple]] = []
    position = 0
    while position < len(recognized):
        index, op = recognized[position]
        if op[0] != "ins":
            position += 1
            continue
        end = position
        while end < len(recognized) and recognized[end][1][0] == "ins":
            end += 1
        inserted = [item[1][2] for item in recognized[position:end]]
        after = [item[1][2] for item in recognized[end:end + len(inserted)]]
        before = [item[1][2] for item in recognized[max(0, position - len(inserted)):position]]
        if inserted and (inserted == after or inserted == before):
            runs.append([item[1] for item in recognized[position:end]])
        position = end
    return runs


# --- pitch -------------------------------------------------------------------------

def pitch_features(take: dict[str, Any], results: dict[str, Any], context: dict[str, Any],
                   audio: tuple[np.ndarray, int] | None, params: dict[str, Any]) -> dict[str, Feature]:
    names = ("pitch.sustained_shift_st", "pitch.octave_jumps", "pitch.register_offset_st",
             "pitch.tracker_disagreement", "pitch.tone_run_seconds", "pitch.tone_flatness", "pitch.tone_hnr_db")
    out = {name: feature() for name in names}
    track_a, track_b = outputs(results, "pitchA"), outputs(results, "pitchB")
    if pitch is None or track_a is None or track_b is None:
        return out
    agreement = pitch.agreeing_frames(track_a, track_b, cents=params.get("pitchAgreeCents", 50))
    summary = agreement.summary()
    if summary.get("agreeRatio") is not None:
        out["pitch.tracker_disagreement"] = feature(1.0 - summary["agreeRatio"])
    shift = pitch.sustained_shifts(agreement)
    if shift.shift_st is not None:
        out["pitch.sustained_shift_st"] = feature(abs(shift.shift_st), shift.start, shift.end)
    jumps = pitch.octave_jumps(agreement)
    out["pitch.octave_jumps"] = feature(len(jumps), *((jumps[0].time, jumps[-1].time) if jumps else (None, None)))
    median = pitch.take_median_semitones(agreement)
    centroid = centroid_for(take, context)
    if median is not None and centroid is not None:
        out["pitch.register_offset_st"] = feature(abs(median - centroid))
    samples, rate = audio if audio else (None, None)
    tone = pitch.tone_runs(agreement, samples, rate)
    if tone.start is not None:
        out["pitch.tone_run_seconds"] = feature(tone.duration, tone.start, tone.end)
        out["pitch.tone_flatness"] = feature(tone.flatness, tone.start, tone.end)
        out["pitch.tone_hnr_db"] = feature(tone.hnr_db, tone.start, tone.end)
    return out


def centroid_for(take: dict[str, Any], context: dict[str, Any]) -> float | None:
    """The register a take should sit at: its clone reference, else its voice's median of medians."""

    reference = take.get("referenceSHA256")
    if reference and reference in context.get("referencePitch", {}):
        return context["referencePitch"][reference]
    return context.get("voicePitch", {}).get(voice_key(take))


def voice_key(take: dict[str, Any]) -> str:
    return f"{take.get('mode')}|{take.get('voice')}"


# --- speaker, quality, judge ----------------------------------------------------------

def _cosine_distance(a: Any, b: Any) -> float | None:
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if a.size == 0 or a.shape != b.shape:
        return None
    norm = float(np.linalg.norm(a) * np.linalg.norm(b))
    return None if norm == 0 else 1.0 - float(np.dot(a, b)) / norm


def speaker_features(take: dict[str, Any], results: dict[str, Any], context: dict[str, Any]) -> dict[str, Feature]:
    names = ("speaker.max_window_distance", "speaker.whole_distance", "speaker.window_range")
    out = {name: feature() for name in names}
    speaker = outputs(results, "speaker")
    if speaker is None:
        return out
    whole = speaker.get("whole")
    anchor = speaker.get("reference") or context.get("voiceEmbedding", {}).get(voice_key(take)) or whole
    windows = [window for window in speaker.get("windows") or [] if window.get("embedding")]
    if anchor is not None and whole is not None and anchor is not whole:
        out["speaker.whole_distance"] = feature(_cosine_distance(whole, anchor))
    distances = [(_cosine_distance(window["embedding"], anchor), window) for window in windows] if anchor else []
    distances = [(distance, window) for distance, window in distances if distance is not None]
    if distances:
        worst, window = max(distances, key=lambda item: item[0])
        out["speaker.max_window_distance"] = feature(worst, window.get("start"), window.get("end"))
    if whole is not None and windows:
        own = [_cosine_distance(window["embedding"], whole) for window in windows]
        own = [value for value in own if value is not None]
        if own:
            out["speaker.window_range"] = feature(max(own) - min(own))
    return out


def quality_features(take: dict[str, Any], results: dict[str, Any], context: dict[str, Any]) -> dict[str, Feature]:
    out = {name: feature() for name in ("mos.whole", "mos.worst_window", "aesthetics.pq_delta", "aesthetics.ce_delta")}
    mos = outputs(results, "mos")
    if mos is not None:
        out["mos.whole"] = feature(mos.get("mos"))
        windows = [window for window in mos.get("windows") or [] if window.get("mos") is not None]
        if windows:
            worst = min(windows, key=lambda window: window["mos"])
            out["mos.worst_window"] = feature(worst["mos"], worst.get("start"), worst.get("end"))
    aesthetics = outputs(results, "aesthetics")
    baseline = context.get("cellAesthetics", {}).get(str(take.get("cell")), {})
    if aesthetics is not None:
        for axis, name in (("PQ", "aesthetics.pq_delta"), ("CE", "aesthetics.ce_delta")):
            if aesthetics.get(axis) is not None and baseline.get(axis) is not None:
                out[name] = feature(float(aesthetics[axis]) - baseline[axis])
    return out


def llm_features(results: dict[str, Any]) -> dict[str, Feature]:
    judged = outputs(results, "llm")
    classes = (judged or {}).get("classes") or {}
    out = {}
    for class_id in LLM_CLASSES:
        verdict = classes.get(class_id)
        if not isinstance(verdict, dict):
            out[f"llm.{class_id}"] = feature()
            continue
        value = verdict.get("pYes")
        if value is None:
            value = 1.0 if verdict.get("present") else 0.0
        out[f"llm.{class_id}"] = feature(value, verdict.get("start"), verdict.get("end"))
    return out


# --- the whole take -------------------------------------------------------------------

def extract(take: dict[str, Any], results: dict[str, Any], context: dict[str, Any], *,
            params: dict[str, Any], layout: store.Layout, model_ids: dict[str, str],
            load_audio: Callable[[str], tuple[np.ndarray, int]] = read_wav) -> dict[str, Feature]:
    """Every feature of one take. `results` maps role -> the take's cached result."""

    audio = None
    try:
        audio = load_audio(take["audio"])
    except (OSError, ValueError):
        audio = None
    out: dict[str, Feature] = {}
    if audio is not None:
        out.update(signal_features(audio[0], audio[1], params))
        out.update(pause_features(audio[0], audio[1], outputs(results, "align")))
        out.update(end_features(audio[0], audio[1]))
        out.update(loudness_features(audio[0], audio[1], params.get("loudnessTarget", -23.0)))
    else:
        out.update({name: feature() for name in AUDIO_FEATURES})
    finish = take.get("finishReason")
    out["engine.finish_not_eos"] = feature(None if finish is None else float(finish != "eos"))
    out.update(asr_features(take, results))
    out.update(align_features(take, results))
    out.update(phone_features(take, results, layout, model_ids, params))
    out.update(pitch_features(take, results, context, audio, params))
    out.update(speaker_features(take, results, context))
    out.update(quality_features(take, results, context))
    out.update(llm_features(results))
    return out


def build_context(takes: list[dict[str, Any]], results_by_token: dict[str, dict[str, Any]],
                  reference_results: dict[str, dict[str, Any]], params: dict[str, Any]) -> dict[str, Any]:
    """Lane-level references from every take of the run (and the clone references' pitch)."""

    voice_pitch: dict[str, list[float]] = {}
    voice_embedding: dict[str, list[np.ndarray]] = {}
    cell_aesthetics: dict[str, dict[str, list[float]]] = {}
    for take in takes:
        results = results_by_token.get(take["token"], {})
        key = voice_key(take)
        track_a, track_b = outputs(results, "pitchA"), outputs(results, "pitchB")
        if pitch is not None and track_a is not None and track_b is not None:
            median = pitch.take_median_semitones(
                pitch.agreeing_frames(track_a, track_b, cents=params.get("pitchAgreeCents", 50)))
            if median is not None:
                voice_pitch.setdefault(key, []).append(median)
        speaker = outputs(results, "speaker")
        if speaker is not None and speaker.get("whole") and take.get("mode") == "custom":
            voice_embedding.setdefault(key, []).append(np.asarray(speaker["whole"], dtype=float))
        aesthetics = outputs(results, "aesthetics")
        if aesthetics is not None:
            bucket = cell_aesthetics.setdefault(str(take.get("cell")), {})
            for axis in ("PQ", "CE"):
                if aesthetics.get(axis) is not None:
                    bucket.setdefault(axis, []).append(float(aesthetics[axis]))
    reference_pitch = {}
    for reference_sha, results in reference_results.items():
        track_a, track_b = outputs(results, "pitchA"), outputs(results, "pitchB")
        if pitch is not None and track_a is not None and track_b is not None:
            median = pitch.take_median_semitones(
                pitch.agreeing_frames(track_a, track_b, cents=params.get("pitchAgreeCents", 50)))
            if median is not None:
                reference_pitch[reference_sha] = median
    embeddings = {}
    for key, vectors in voice_embedding.items():
        mean = np.mean(vectors, axis=0)
        norm = float(np.linalg.norm(mean))
        if norm > 0:
            embeddings[key] = (mean / norm).tolist()
    return {
        "voicePitch": {key: float(np.median(values)) for key, values in voice_pitch.items()},
        "voicePitchSD": {key: float(np.std(values)) for key, values in voice_pitch.items() if len(values) > 1},
        "voiceEmbedding": embeddings,
        "referencePitch": reference_pitch,
        "cellAesthetics": {cell: {axis: float(np.median(values)) for axis, values in axes.items()}
                           for cell, axes in cell_aesthetics.items()},
    }
