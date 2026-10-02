"""Per-take features from the runner outputs, each with time-localized evidence.

A feature is `{"value": float or None, "start": seconds or None, "end": seconds or None}`;
None means the inputs were unavailable (a model not run, a take it failed on).
`extract(take, results, context, params)` reads the cached results by role (the
`models` map of `config/qc/detectors.json`: asrA, asrB, align, phones, phonesB,
g2p, pitchA, pitchB, speaker, mos, aesthetics, llm) and returns every feature the
detectors name. `build_context` computes the lane-level references: voice pitch
centroids and per-cell aesthetics baselines (from the newest frozen
`config/qc/references-v<N>.json` first, `qc.references`), clone-reference pitch,
and leave-one-out speaker centroids.

Transcripts are also compared at the sound level (`asr_phonetic_features`): the
script and each ASR transcript go through the same cached G2P, so homophones cost
nothing. Phones come from `qc.phones` (G2P, alignment, GOP) and pitch from `qc.pitch`;
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
LLM_CLASSES = ("stutter", "mispronunciation", "wrong-language", "cutoff", "pause", "devoiced", "pitch",
               "tonal-collapse", "voice-change", "artifact", "unnatural")
AUDIO_FEATURES = (
    "signal.clicks", "signal.dropout_seconds", "signal.clipping_fraction", "signal.terminal_silence_seconds",
    "signal.abrupt_offset_db", "pause.longest_gap_seconds", "pause.nonspeech_level_db", "pause.voiced_blips",
    "pause.mute_confirmed", "pause.unpunctuated_gap_seconds", "end.drop_db_60ms", "end.tail_seconds",
    "end.decay_db_per_ms", "end.file_tail_seconds", "level.lufs", "level.lufs_deviation", "level.true_peak_dbtp",
    "level.lra",
)
# Pauses at least this long are left out of the articulation time the speaking rate divides by.
ARTICULATION_PAUSE_SECONDS = 0.1


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


def _loud_unvoiced_samples(x: np.ndarray, profile: dict[str, np.ndarray], rate: int) -> np.ndarray:
    """Per sample: inside a loud unvoiced frame (a fricative, a whispered syllable).

    A frame is loud when its robust level (1.4826 times its median absolute sample, the RMS of a
    noise) is within 20 dB of the voiced speech median; one click in a pause leaves the median of
    its frame, and so the frame, quiet. Unvoiced is a periodicity under 0.45.
    """

    skip = np.zeros(x.size, dtype=bool)
    _, speech_median = _speech_frames(profile)
    if speech_median is None:
        return skip
    size = max(16, int(round(float(profile["window"]) * rate)))
    step = max(1, int(round(float(profile["hop"]) * rate)))
    padded = np.pad(x, (0, max(0, size - x.size)))
    frames = np.lib.stride_tricks.sliding_window_view(padded, size)[::step]
    count = min(len(frames), profile["level"].size)
    robust = _db(1.4826 * np.median(np.abs(frames[:count]), axis=1))
    loud = (robust > speech_median - 20.0) & (profile["periodicity"][:count] < 0.45)
    for index in np.flatnonzero(loud):
        skip[index * step:index * step + size] = True
    return skip


def click_features(x: np.ndarray, rate: int, params: dict[str, Any], *,
                   profile: dict[str, np.ndarray] | None = None) -> Feature:
    """Clicks: second-difference spikes far above their local level, counted as clusters 5 ms apart.

    The scale is a local one: the MAD of the second difference over 10 ms blocks, the largest of a
    block and its two neighbours (so a block half inside a fricative takes the fricative's scale).
    A take-wide MAD is set by the voiced speech, whose second difference is small, so every fricative
    read as a run of clicks. Loud unvoiced frames are skipped (`_loud_unvoiced_samples`).
    """

    second = np.diff(x, n=2)
    block = max(1, int(round(0.010 * rate)))
    count = second.size // block
    if count == 0:
        return feature(0)
    blocks = second[:count * block].reshape(count, block)
    mad = np.median(np.abs(blocks - np.median(blocks, axis=1, keepdims=True)), axis=1) * 1.4826
    local = mad.copy()
    local[1:] = np.maximum(local[1:], mad[:-1])
    local[:-1] = np.maximum(local[:-1], mad[1:])
    scale = np.concatenate([np.repeat(local, block), np.full(second.size - count * block, local[-1])])
    spiking = np.abs(second) > params.get("clickSigma", 12.0) * (scale + 1e-9) + 0.05
    profile = frame_profile(x, rate) if profile is None else profile
    spiking &= ~_loud_unvoiced_samples(x, profile, rate)[1:-1]  # second[k] is centred on x[k + 1]
    spikes = np.flatnonzero(spiking)
    # One click spans a few samples: count clusters 5 ms apart.
    clusters = 0 if spikes.size == 0 else 1 + int(np.sum(np.diff(spikes) > rate * 0.005))
    worst = int(spikes[np.argmax(np.abs(second[spikes]))]) + 1 if spikes.size else None
    return feature(clusters, worst / rate if worst is not None else None, worst / rate if worst is not None else None)


def signal_features(samples: np.ndarray, rate: int, params: dict[str, Any], *,
                    profile: dict[str, np.ndarray] | None = None) -> dict[str, Feature]:
    """DSP checks: clicks, internal dropouts, clipping, terminal silence and an abrupt offset."""

    out: dict[str, Feature] = {}
    x = np.asarray(samples, dtype=np.float64)
    if x.size < rate // 20:
        return {name: feature() for name in ("signal.clicks", "signal.dropout_seconds", "signal.clipping_fraction",
                                             "signal.terminal_silence_seconds", "signal.abrupt_offset_db")}
    out["signal.clicks"] = click_features(x, rate, params, profile=profile)

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


def _speech_mask(profile: dict[str, np.ndarray]) -> dict[str, Any] | None:
    """Speech frames: the voiced frames, with their short holes bridged and their blips removed.

    Voiced speech is periodic and near speech level; a voiced run under 120 ms with at least
    150 ms of non-speech on both sides, next to quiet, is a blip, not speech. Returns
    `{voiced, speech, blips, quiet, median}`, or None with fewer than two voiced frames.
    """

    hop = float(profile["hop"])
    voiced, speech_median = _speech_frames(profile)
    indices = np.flatnonzero(voiced)
    if indices.size < 2 or speech_median is None:
        return None
    # Periodicity flickers around its threshold: bridge holes of 30 ms or less, so one voiced
    # sound is one run (the fr-0101--dylan blip otherwise splits into three 10 ms runs).
    voiced = voiced.copy()
    for start, end in _runs(~voiced):
        if start > 0 and end < voiced.size and (end - start) * hop <= 0.03 + 1e-9:
            voiced[start:end] = True
    runs = _runs(voiced)
    blip_frames = int(round(0.12 / hop))
    margin = int(round(0.15 / hop))
    quiet = profile["level"] < speech_median - 20.0
    quiet_frames = int(round(0.10 / hop))

    def quiet_run(index: int, step: int) -> int:
        count = 0
        while 0 <= index < quiet.size and quiet[index]:
            count += 1
            index += step
        return count

    speech = voiced.copy()
    blips: list[tuple[int, int]] = []
    for position, (start, end) in enumerate(runs):
        before = start - runs[position - 1][1] if position > 0 else None
        after = runs[position + 1][0] - end if position + 1 < len(runs) else None
        # A blip is a short voiced sound isolated in non-speech and next to quiet: a short vowel
        # between unvoiced consonants (the "o" of "obstruaient" before /pstʁ/) is speech.
        isolated = before is not None and after is not None and before >= margin and after >= margin
        # Skip the frames whose 25 ms window still overlaps the run itself.
        overlap = int(math.ceil(float(profile["window"]) / hop)) - 1
        beside = max(quiet_run(start - 1 - overlap, -1), quiet_run(end + overlap, 1))
        if end - start < blip_frames and isolated and beside >= quiet_frames:
            speech[start:end] = False
            blips.append((start, end))
    return {"voiced": voiced, "speech": speech, "blips": blips, "quiet": quiet, "median": speech_median}


def speech_span(samples: np.ndarray, rate: int, *, profile: dict[str, np.ndarray] | None = None
                ) -> tuple[float, float] | None:
    """From the start of the first to the end of the last speech frame (blips excluded), or None."""

    profile = frame_profile(samples, rate) if profile is None else profile
    mask = _speech_mask(profile)
    inside = np.flatnonzero(mask["speech"]) if mask else np.array([], dtype=int)
    if inside.size < 2:
        return None
    return float(profile["time"][inside[0]]), float(profile["time"][inside[-1]]) + float(profile["hop"])


def _blip_mask(size: int, blips: Iterable[tuple[int, int]]) -> np.ndarray:
    in_blip = np.zeros(size, dtype=bool)
    for start, end in blips:
        in_blip[start:end] = True
    return in_blip


def _gap_frames(profile: dict[str, np.ndarray], mask: dict[str, Any]) -> list[tuple[int, int]]:
    """Every pause between the first and last speech frames, as frame ranges `[start, end)`.

    A pause is a run of quiet frames (20 dB under the speech median) or blips (`_speech_mask`),
    bridging holes of 30 ms or less that hold no speech (the edges of a blip, a click) and dropping
    runs under 30 ms. Loud unvoiced sound (a whispered syllable, a fricative, a breath at speech
    level) is not a pause and bounds one: the fr-0101--dylan gap after the whispered "-tus" of
    "abattus" is the quiet run that follows the whisper.
    """

    speech, quiet = mask["speech"], mask["quiet"]
    inside = np.flatnonzero(speech)
    if inside.size < 2:
        return []
    first, last = int(inside[0]), int(inside[-1])
    hop = float(profile["hop"])
    pausable = (quiet | _blip_mask(speech.size, mask["blips"])) & ~speech
    pausable[:first + 1] = False
    pausable[last:] = False
    short = int(round(0.03 / hop))
    for start, end in _runs(~pausable):
        if first < start and end <= last and end - start <= short and not speech[start:end].any():
            pausable[start:end] = True
    return [(start, end) for start, end in _runs(pausable) if end - start >= short]


def _gap_span(profile: dict[str, np.ndarray], gap: tuple[int, int]) -> tuple[float, float]:
    """A gap's times: from its first quiet frame's start to its last quiet frame's window end (each
    frame's level covers its whole window, so the last quiet frame starts a window before the end)."""

    return float(profile["time"][gap[0]]), float(profile["time"][gap[1] - 1]) + float(profile["window"])


def pause_gaps(samples: np.ndarray, rate: int, *, profile: dict[str, np.ndarray] | None = None,
               minimum: float = 0.0) -> list[float]:
    """The length of every within-sentence pause, as `pause_features` measures the longest, in
    seconds: those of at least `minimum` (the language norms count pauses of 100 ms or more)."""

    profile = frame_profile(samples, rate) if profile is None else profile
    mask = _speech_mask(profile)
    if mask is None:
        return []
    lengths = [end - start for start, end in (_gap_span(profile, gap) for gap in _gap_frames(profile, mask))]
    return [round(length, 6) for length in lengths if length >= minimum - 1e-9]


# Punctuation that does not mark a pause: the apostrophe of "l'arbre" and the hyphen of "peut-être".
WORD_JOINERS = frozenset("'’ʼ-‐‑")


def script_tokens(text: str | None, language: str | None) -> tuple[list[str], list[bool]]:
    """The script's tokens as `normalize_text` splits them, and whether pause punctuation (a comma,
    a full stop, a dash; not an apostrophe or a hyphen) follows each one before the next token."""

    tokens: list[str] = []
    breaks: list[bool] = []
    current = ""
    for char in unicodedata.normalize("NFKC", text or "").lower():
        category = unicodedata.category(char)[0]
        if category in "PSZC":
            if current:
                tokens.append(current)
                breaks.append(False)
                current = ""
            if category == "P" and char not in WORD_JOINERS and tokens:
                breaks[-1] = True
        elif language in CJK_LANGUAGES:
            tokens.append(char)
            breaks.append(False)
        else:
            current += char
    if current:
        tokens.append(current)
        breaks.append(False)
    return tokens, breaks


def unpunctuated_gap(aligned: dict[str, Any] | None, text: str | None, language: str | None) -> Feature:
    """The longest silence between two aligned words that are neighbours in the script with no
    punctuation between them (a norm-only measure: a pause the script does not call for).

    The aligner's words are matched to the script's tokens by an edit alignment, so a word the
    aligner splits or merges differently only loses its own pairs. None without aligned words or a
    script."""

    words = [word for word in (aligned or {}).get("words") or []
             if word.get("start") is not None and word.get("end") is not None and word.get("text")]
    tokens, breaks = script_tokens(text, language)
    if len(words) < 2 or not tokens:
        return feature()
    heard: list[str] = []
    owners: list[int] = []
    for index, word in enumerate(words):
        for token in normalize_text(str(word["text"]), language):
            heard.append(token)
            owners.append(index)
    owner_of = {reference: owners[hypothesis] for op, reference, hypothesis in edit_alignment(tokens, heard)
                if op == "match"}
    first_token: dict[int, int] = {}
    last_token: dict[int, int] = {}
    for token, word in owner_of.items():
        first_token[word] = min(token, first_token.get(word, token))
        last_token[word] = max(token, last_token.get(word, token))
    best = None
    for index in range(len(words) - 1):
        before, after = last_token.get(index), first_token.get(index + 1)
        if before is None or after is None or after != before + 1 or breaks[before]:
            continue
        silence = max(0.0, float(words[index + 1]["start"]) - float(words[index]["end"]))
        if best is None or silence > best[0]:
            best = (silence, float(words[index]["end"]), float(words[index + 1]["start"]))
    if best is None:
        return feature()
    return feature(best[0], *(best[1:] if best[0] > 0 else (None, None)))


def pause_features(samples: np.ndarray, rate: int, aligned: dict[str, Any] | None, *,
                   profile: dict[str, np.ndarray] | None = None, text: str | None = None,
                   language: str | None = None) -> dict[str, Feature]:
    """The longest pause inside the sentence, from the audio alone.

    Speech frames come from `_speech_mask` (voiced, blips removed) and pauses from `_gap_frames`
    (quiet runs between the first and last speech frames). Features: the longest pause's length;
    the loudest sustained non-speech level of the non-speech stretch around it, relative to the
    speech median (a whisper or a breath at speech level next to the pause); and the blips inside
    it. The aligner's word gaps no longer lengthen it: they give `pause.unpunctuated_gap_seconds`
    (`unpunctuated_gap`, with `text`).
    """

    names = ("pause.longest_gap_seconds", "pause.nonspeech_level_db", "pause.voiced_blips")
    out = {name: feature() for name in names}
    out["pause.mute_confirmed"] = feature()
    out["pause.unpunctuated_gap_seconds"] = unpunctuated_gap(aligned, text, language)
    profile = frame_profile(samples, rate) if profile is None else profile
    hop = float(profile["hop"])
    mask = _speech_mask(profile)
    if mask is None:
        return out
    voiced, speech, blips, speech_median = mask["voiced"], mask["speech"], mask["blips"], mask["median"]
    if np.flatnonzero(speech).size < 2:
        return out
    best = max(_gap_frames(profile, mask), key=lambda gap: gap[1] - gap[0], default=None)
    if best is None:
        out["pause.longest_gap_seconds"] = feature(0.0)
        out["pause.nonspeech_level_db"] = feature(None)
        out["pause.voiced_blips"] = feature(0)
        return out
    gap_start, gap_end = _gap_span(profile, best)
    out["pause.longest_gap_seconds"] = feature(gap_end - gap_start, gap_start, gap_end)
    # The non-speech stretch around the pause: from the speech frame before it to the one after.
    before = np.flatnonzero(speech[:best[0]])
    after = np.flatnonzero(speech[best[1]:])
    lo = int(before[-1]) + 1 if before.size else 0
    hi = best[1] + int(after[0]) if after.size else speech.size
    in_blip = _blip_mask(voiced.size, blips)
    stretch = np.zeros(voiced.size, dtype=bool)
    stretch[lo:hi] = True
    nonspeech = stretch & ~in_blip & ~voiced
    # Sustained noise, not a transient: the loudest 100 ms median of the stretch's non-speech frames.
    levels = profile["level"][nonspeech]
    width = max(1, int(round(0.10 / hop)))
    if levels.size >= width:
        loudest = float(np.median(np.lib.stride_tricks.sliding_window_view(levels, width), axis=1).max())
    else:
        loudest = float(np.median(levels)) if levels.size else None
    out["pause.nonspeech_level_db"] = feature(None if loudest is None else loudest - speech_median,
                                              float(profile["time"][lo]), float(profile["time"][hi - 1]) + hop)
    inside_blips = [(start, end) for start, end in blips if best[0] <= start and end <= best[1]]
    out["pause.voiced_blips"] = feature(len(inside_blips), *(
        (float(profile["time"][inside_blips[0][0]]), float(profile["time"][inside_blips[-1][1] - 1]) + hop)
        if inside_blips else (None, None)))
    return out


END_FLOOR_DB = -100.0  # levels are clamped here: digital silence is not 140 dB below speech
# The tail ends at -60 dBFS; past the file's end the padding sits there too, so a cut at the last
# sample drops to the tail floor and no further.
TAIL_FLOOR_DB = -60.0


def end_features(samples: np.ndarray, rate: int, *, profile: dict[str, np.ndarray] | None = None
                 ) -> dict[str, Feature]:
    """How the last word ends, from 10 ms levels: the drop within 60 ms of the final peak, the
    tail from the first 10 dB below it down to -60 dBFS, the decay slope, and the file's tail
    after the last speech frame (`end.file_tail_seconds`, a trim check).

    Levels are clamped at -100 dB and the file is padded at -60 dB, so a take cut at its last
    sample drops to the tail floor rather than to a padding that saturated every drop."""

    names = ("end.drop_db_60ms", "end.tail_seconds", "end.decay_db_per_ms", "end.file_tail_seconds")
    out = {name: feature() for name in names}
    x = np.asarray(samples, dtype=np.float64)
    if x.size >= rate // 20:
        span = speech_span(x, rate, profile=profile)
        if span is not None:
            duration = x.size / rate
            out["end.file_tail_seconds"] = feature(max(0.0, duration - span[1]), span[1], duration)
    step = max(1, int(round(0.010 * rate)))
    count = x.size // step
    if count < 10:
        return out
    level = np.maximum(_db(np.sqrt(np.mean(x[:count * step].reshape(count, step) ** 2, axis=1))), END_FLOOR_DB)
    level = np.concatenate([level, np.full(3, TAIL_FLOOR_DB)])
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
    floor = next((index for index in range(onset, level.size) if level[index] <= TAIL_FLOOR_DB), level.size - 1)
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
    """Word (character, for Chinese and Japanese) insertion and deletion rates, language ID and
    script against the script. The sound-level rate is `asr_phonetic_features`."""

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


# --- sound-level transcript comparison ------------------------------------------------
#
# Word error rates count homophones as errors: "la voie" heard as "la voix" is one wrong word but
# the same sound (/vwa/), and Chinese and Japanese have no spaces and many homophones. Both the
# script and each ASR transcript go through the same G2P (espeak-ng, with a kana reading first for
# Japanese) into broad phones, aligned with the PanPhon feature distance, so a homophone costs
# nothing and a near-identical sound counts as a match.

ASR_FAMILIES = (("asrA", "a"), ("asrB", "b"))
PHONETIC_FEATURES = ("asr.phonetic_error_a", "asr.phonetic_error_b", "asr.phonetic_error_min")


def g2p_cached(text: str | None, language: str | None, layout: store.Layout,
               model_ids: dict[str, str]) -> dict[str, Any] | None:
    """The cached G2P record of a text (the G2P role's cache, else the shared one), or None."""

    if phones is None or not text:
        return None
    for cache_dir in (layout.results_dir(model_ids.get("g2p", "g2p.espeak-ng")), None):
        try:
            return phones.g2p_record(text, language, cache_dir=cache_dir, compute=False)
        except Exception:  # noqa: BLE001 - a cache miss or an unsupported language
            continue
    return None


def transcript(asr: dict[str, Any] | None) -> str:
    """An ASR family's transcript as the G2P reads it."""

    return ((asr or {}).get("text") or "").strip()


def phonetic_error(expected: list[str], heard: list[str], distance: Callable[[str, str], float],
                   near: float = 0.0) -> float | None:
    """The phone error rate of `heard` against `expected` (broad phones): deletions, insertions and
    substitutions over the expected phones, after a PanPhon-weighted alignment.

    Identical sounds cost nothing whatever their spelling (voie and voix are both /vwa/). A
    substitution within `near` of its phone (the near-identity scale of `qc.phones`: /e/ for /ɛ/,
    a voicing pair) counts as a match, as the ASR's language model makes those choices.
    """

    if not expected or phones is None:
        return None
    ops = phones.align(expected, heard, distance=distance)
    errors = sum(1 for op in ops if op["op"] in ("del", "ins") or (op["op"] == "sub" and float(op["cost"]) > near))
    return errors / len(expected)


def asr_phonetic_features(take: dict[str, Any], results: dict[str, Any], layout: store.Layout,
                          model_ids: dict[str, str]) -> dict[str, Feature]:
    """Sound-level transcript errors: the script and each family's transcript through the same G2P.

    `asr.phonetic_error_a` and `_b` are the families' rates; `asr.phonetic_error_min`, the smaller,
    needs both (both families must hear the error). A transcript the G2P job has not read yet, or a
    language without G2P (Japanese without its kana reader), leaves them unavailable.
    """

    out = {name: feature() for name in PHONETIC_FEATURES}
    if phones is None or not take.get("text"):
        return out
    language = take.get("language")
    script = g2p_cached(take["text"], language, layout, model_ids)
    expected = phones.normalize(script["phones"], language=language) if script and script.get("phones") else []
    if not expected:
        return out
    distance, source = phones.default_distance(layout.model_dir(model_ids.get("g2p", "g2p.espeak-ng")))
    near = getattr(phones, "PANPHON_NEAR" if source == "panphon" else "COARSE_NEAR", 0.0)
    values = []
    for role, suffix in ASR_FAMILIES:
        asr = outputs(results, role)
        if asr is None:
            continue
        text = transcript(asr)
        record = g2p_cached(text, language, layout, model_ids) if text else {"phones": []}
        if record is None:
            continue
        value = phonetic_error(expected, phones.normalize(record.get("phones") or [], language=language), distance, near)
        out[f"asr.phonetic_error_{suffix}"] = feature(value)
        values.append(value)
    if len(values) == len(ASR_FAMILIES) and None not in values:
        out["asr.phonetic_error_min"] = feature(min(values))
    return out


def transcript_g2p_takes(takes: list[dict[str, Any]], results_by_token: dict[str, dict[str, Any]],
                         layout: store.Layout, model_ids: dict[str, str]) -> list[dict[str, Any]]:
    """Pseudo-takes that make the G2P job read every ASR transcript not in its cache yet.

    The G2P cache is keyed by text, so a transcript equal to its script costs nothing. G2P reads no
    audio: each pseudo-take's `audioSHA256` is the digest of its language and text, which keys its
    per-take G2P result apart from every real take's.
    """

    if phones is None:
        return []
    pending: dict[str, dict[str, Any]] = {}
    for take in takes:
        language = take.get("language")
        if language not in getattr(phones, "ESPEAK_VOICES", {}):
            continue
        for role, _ in ASR_FAMILIES:
            text = transcript(outputs(results_by_token.get(take["token"], {}), role))
            if not text or g2p_cached(text, language, layout, model_ids) is not None:
                continue
            digest = store.sha256_text(store.canonical_json({"g2pTranscript": text, "language": language}))
            pending.setdefault(digest, {"token": f"asr{digest[:13]}", "audio": take["audio"], "audioSHA256": digest,
                                        "language": language, "text": text, "reference": None,
                                        "referenceSHA256": None})
    return list(pending.values())


# --- pace -------------------------------------------------------------------------------

RATE_FEATURES = ("rate.phones_per_second", "rate.seconds_per_phone", "rate.syllables_per_second")


def rate_features(expected: list[str] | None, span: tuple[float, float] | None,
                  pauses: Iterable[float] | None = None) -> dict[str, Feature]:
    """The articulation rate: phones over the speech span (first to last speech frame) minus its
    pauses of `ARTICULATION_PAUSE_SECONDS` or more (`pause_gaps`), so one long pause no longer reads
    as slow speech.

    Phones are the script's broad G2P phones; syllables are their vowel runs (a diphthong is one
    nucleus). Norms are per language, since phone inventories and syllable shapes differ.
    `rate.seconds_per_phone` is the reciprocal, so a fitted detector can weigh both tails.
    """

    out = {name: feature() for name in RATE_FEATURES}
    if phones is None or not expected or span is None:
        return out
    start, end = span
    paused = sum(float(gap) for gap in pauses or () if float(gap) >= ARTICULATION_PAUSE_SECONDS - 1e-9)
    seconds = end - start - paused
    broad = phones.normalize(expected)
    if seconds < 0.3 or not broad:
        return out
    vowels = getattr(phones, "VOWELS", frozenset())
    nuclei = sum(1 for index, phone in enumerate(broad)
                 if phone[:1] in vowels and (index == 0 or broad[index - 1][:1] not in vowels))
    out["rate.phones_per_second"] = feature(len(broad) / seconds, start, end)
    out["rate.seconds_per_phone"] = feature(seconds / len(broad), start, end)
    if nuclei:
        out["rate.syllables_per_second"] = feature(nuclei / seconds, start, end)
    return out


def word_gaps(aligned: dict[str, Any] | None) -> list[float]:
    """The silences between consecutive aligned words, in seconds (only the positive ones)."""

    words = [word for word in (aligned or {}).get("words") or []
             if word.get("start") is not None and word.get("end") is not None]
    gaps = [float(current["start"]) - float(previous["end"]) for previous, current in zip(words, words[1:])]
    return [gap for gap in gaps if gap > 0]


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

PHONE_FEATURES = ("phones.deletion_rate", "phones.repeat_runs", "phones.low_gop_run", "phones.last_word_coverage",
                  "phones.gop_mean", "phones.substitution_rate", "phones.l1_substitutions", "phones.per",
                  "phones.insertion_rate")


def expected_phones(take: dict[str, Any], results: dict[str, Any], layout: store.Layout,
                    model_ids: dict[str, str]) -> tuple[list[str] | None, list[dict[str, Any]]]:
    """The script's phones and words: the take's G2P result, else the G2P text cache."""

    g2p_out = outputs(results, "g2p")
    if g2p_out and g2p_out.get("phones"):
        return list(g2p_out["phones"]), list(g2p_out.get("words") or [])
    record = g2p_cached(take.get("text"), take.get("language"), layout, model_ids)
    if record is None:
        return None, []
    return list(record["phones"]), list(record.get("words") or [])


def expected_optional(words: list[dict[str, Any]], count: int) -> list[bool] | None:
    """One flag per expected phone: whether its word lists it as optional (a French liaison
    consonant, a final schwa; `qc.runners.espeak_g2p`). None when no phone is optional or the words
    do not spell out the expected phones."""

    flags: list[bool] = []
    for word in words:
        marked = set(word.get("optional") or [])
        flags += [index in marked for index in range(len(word.get("phones") or []))]
    return flags if len(flags) == count and any(flags) else None


def _op_span(ops: Iterable[dict[str, Any]]) -> tuple[float | None, float | None]:
    ops = list(ops)
    starts = [op["start"] for op in ops if op.get("start") is not None]
    ends = [op["end"] for op in ops if op.get("end") is not None]
    return (min(starts) if starts else None, max(ends) if ends else None)


# The phone recognizers' insertions agree within this many seconds (or at the same expected position):
# `phones` (ZIPA, with posteriors for GOP) and `phonesB` (wav2vec2-espeak).
INSERTION_AGREEMENT_SECONDS = 0.06


def _compare_role(role: str, expected: list[str], optional: list[bool] | None, take: dict[str, Any],
                  results: dict[str, Any], layout: store.Layout, model_ids: dict[str, str], params: dict[str, Any],
                  *, posteriors: bool, keep_rhotic_ops: bool = False) -> dict[str, Any] | None:
    """`qc.phones.compare` of one recognizer role's result (its posteriors from that role's own
    result directory, when `posteriors`), or None when the role has no result or it is malformed."""

    recognized_out = outputs(results, role)
    if recognized_out is None:
        return None
    logprobs = vocab = None
    frame_seconds = recognized_out.get("frameSeconds")
    if posteriors and recognized_out.get("posteriors"):
        path = layout.results_dir(model_ids.get(role, "")) / Path(recognized_out["posteriors"]).name
        try:
            with np.load(path, allow_pickle=False) as arrays:
                logprobs = arrays["logprobs"].astype(np.float32)
                vocab = [str(item) for item in arrays["vocab"]]
                if "frameSeconds" in arrays:
                    frame_seconds = float(arrays["frameSeconds"])
        except (OSError, KeyError, ValueError):
            logprobs = vocab = None
    try:
        return phones.compare(expected, recognized_out.get("phones") or [], logprobs=logprobs, vocab=vocab,
                              frame_seconds=frame_seconds,
                              model_dir=layout.model_dir(model_ids.get("g2p", "g2p.espeak-ng")),
                              language=take.get("language"), optional=optional,
                              low_gop=float(params.get("gopLow", -2.3)), keep_rhotic_ops=keep_rhotic_ops)
    except Exception:  # noqa: BLE001 - a malformed result leaves the features unavailable
        return None


def phone_features(take: dict[str, Any], results: dict[str, Any], layout: store.Layout,
                   model_ids: dict[str, str], params: dict[str, Any]) -> dict[str, Feature]:
    """Expected (G2P) against recognized phones through `qc.phones.compare`, per recognizer role:
    PanPhon-weighted alignment (optional liaison consonants and final schwas cost nothing to leave
    out), GOP-SF on the first recognizer's posteriors, and its stutter features.

    Deletions, substitutions, GOP, the L1 pairs and the last word's coverage come from the first
    recognizer (`phones`, ZIPA). `phones.insertion_rate` and `phones.repeat_runs` count only the
    insertions both recognizers made (`qc.phones.agreement`): a recognizer's own habit (ZIPA
    printing French silent letters) is not a stutter. Without the second recognizer's result
    (`phonesB`) those two abstain (None).
    """

    out = {name: feature() for name in PHONE_FEATURES}
    if phones is None or outputs(results, "phones") is None:
        return out
    expected, words = expected_phones(take, results, layout, model_ids)
    if not expected:
        return out
    language = take.get("language")
    optional = expected_optional(words, len(expected))

    def kept(phone: str) -> str:
        return "".join(phones.normalize_phone(phone, keep_rhotics=True, language=language)) if phone else ""

    # The L1 pairs keep the rhotics apart (/ʁ/ heard as /ɹ/), so they are counted on an alignment
    # that keeps them too.
    pairs = {(kept(a), kept(b)) for a, b in params.get("l1Substitutions", {}).get(language, [])}
    pairs = {pair for pair in pairs if pair[0] and pair[0] != pair[1]}
    compared = _compare_role("phones", expected, optional, take, results, layout, model_ids, params,
                             posteriors=True, keep_rhotic_ops=bool(pairs))
    if compared is None:
        return out
    found, ops = compared["features"], compared["ops"]

    deletion_runs = found.get("deletionRuns") or []
    deleted = [op for op in ops if op["op"] == "del"]
    span = max(deletion_runs, key=lambda run: run["count"]) if deletion_runs else None
    out["phones.deletion_rate"] = feature(found.get("deletionRate"), *(
        (span["start"], span["end"]) if span else _op_span(deleted[:1])))
    out["phones.substitution_rate"] = feature(found.get("substitutionRate"),
                                              *_op_span(op for op in ops if op["op"] == "sub"))
    out["phones.per"] = feature(found.get("per"))
    second = _compare_role("phonesB", expected, optional, take, results, layout, model_ids, params, posteriors=False)
    agreed = None
    if second is not None:
        try:
            agreed = phones.agreement(compared, second, model_dir=layout.model_dir(model_ids.get("g2p", "g2p.espeak-ng")),
                                      tolerance=INSERTION_AGREEMENT_SECONDS)["features"]
        except Exception:  # noqa: BLE001 - a malformed result leaves the agreed features unavailable
            agreed = None
    if agreed is not None:
        bursts = agreed.get("insertionBursts") or []
        burst = max(bursts, key=lambda run: run["count"], default=None)
        out["phones.insertion_rate"] = feature(agreed.get("insertionRate"), burst.get("start") if burst else None,
                                               burst.get("end") if burst else None)
        repeats = agreed.get("repeatRuns") or []
        longest = max(repeats, key=lambda run: run.get("n", 1) * run.get("copies", 2), default=None)
        out["phones.repeat_runs"] = feature(agreed.get("repeatCount", len(repeats)),
                                            longest.get("start") if longest else None,
                                            longest.get("end") if longest else None)
    if found.get("meanGop") is not None:
        out["phones.gop_mean"] = feature(found["meanGop"])
        spans = found.get("lowGopSpans") or []
        worst = max(spans, key=lambda item: item["count"], default=None)
        out["phones.low_gop_run"] = feature(worst["count"] if worst else 0, worst.get("start") if worst else None,
                                            worst.get("end") if worst else None)

    if pairs:
        accent_ops = compared.get("rhoticOps") or ops
        l1 = [op for op in accent_ops if (op["op"] == "sub" and (op["expected"], op["recognized"]) in pairs)
              or (op["op"] == "del" and (op["expected"], "") in pairs)]
        out["phones.l1_substitutions"] = feature(len(l1), *_op_span(l1))

    expected_ops = [op for op in ops if op["op"] in ("match", "sub", "del", "skip")]
    last = (len(phones.normalize(words[-1]["phones"], language=language)) if words and words[-1].get("phones")
            else max(1, len(expected_ops) // 10))
    tail = [op for op in expected_ops[-last:] if op["op"] != "skip"]  # an optional phone left out is no loss
    if tail:
        covered = sum(1 for op in tail if op["op"] in ("match", "sub"))
        out["phones.last_word_coverage"] = feature(covered / len(tail), *_op_span(tail))
    return out


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
    """The register a take should sit at: its clone reference, else its voice's median of medians
    (frozen, or the run's own; `build_context`)."""

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


# A voice's speaker centroid needs this many of its other custom-mode takes.
SPEAKER_CENTROID_MIN_TAKES = 3


def speaker_centroid(take: dict[str, Any], whole: Any, context: dict[str, Any]) -> list[float] | None:
    """The take's voice centroid without the take itself (leave-one-out): the mean of the voice's
    other custom-mode whole embeddings, unit length, or None with fewer than
    `SPEAKER_CENTROID_MIN_TAKES` of them. A take never pulls its own anchor toward itself."""

    entry = (context.get("voiceEmbeddings") or {}).get(voice_key(take))
    if not entry:
        return None
    total, count = np.asarray(entry["sum"], dtype=float), int(entry["count"])
    if take.get("token") in entry["members"] and whole is not None:
        own = np.asarray(whole, dtype=float)
        if own.shape != total.shape:
            return None
        total, count = total - own, count - 1
    if count < SPEAKER_CENTROID_MIN_TAKES:
        return None
    norm = float(np.linalg.norm(total))
    return None if norm == 0 else (total / norm).tolist()


def speaker_features(take: dict[str, Any], results: dict[str, Any], context: dict[str, Any]) -> dict[str, Feature]:
    names = ("speaker.max_window_distance", "speaker.whole_distance", "speaker.window_range")
    out = {name: feature() for name in names}
    speaker = outputs(results, "speaker")
    if speaker is None:
        return out
    whole = speaker.get("whole")
    anchor = speaker.get("reference") or speaker_centroid(take, whole, context) or whole
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
    span = None
    pauses: list[float] = []
    if audio is not None:
        profile = frame_profile(audio[0], audio[1])
        out.update(signal_features(audio[0], audio[1], params, profile=profile))
        out.update(pause_features(audio[0], audio[1], outputs(results, "align"), profile=profile,
                                  text=take.get("text"), language=take.get("language")))
        out.update(end_features(audio[0], audio[1], profile=profile))
        out.update(loudness_features(audio[0], audio[1], params.get("loudnessTarget", -23.0)))
        span = speech_span(audio[0], audio[1], profile=profile)
        pauses = pause_gaps(audio[0], audio[1], profile=profile, minimum=ARTICULATION_PAUSE_SECONDS)
    else:
        out.update({name: feature() for name in AUDIO_FEATURES})
    finish = take.get("finishReason")
    out["engine.finish_not_eos"] = feature(None if finish is None else float(finish != "eos"))
    out.update(asr_features(take, results))
    out.update(asr_phonetic_features(take, results, layout, model_ids))
    out.update(align_features(take, results))
    out.update(phone_features(take, results, layout, model_ids, params))
    out.update(rate_features(expected_phones(take, results, layout, model_ids)[0], span, pauses))
    out.update(pitch_features(take, results, context, audio, params))
    out.update(speaker_features(take, results, context))
    out.update(quality_features(take, results, context))
    out.update(llm_features(results))
    return out


AESTHETICS_AXES = ("PQ", "CE")


def take_pitch_median(results: dict[str, Any], params: dict[str, Any]) -> float | None:
    """A take's (or a clip's) median pitch in semitones over the frames both trackers agree on."""

    track_a, track_b = outputs(results, "pitchA"), outputs(results, "pitchB")
    if pitch is None or track_a is None or track_b is None:
        return None
    return pitch.take_median_semitones(
        pitch.agreeing_frames(track_a, track_b, cents=params.get("pitchAgreeCents", 50)))


def build_context(takes: list[dict[str, Any]], results_by_token: dict[str, dict[str, Any]],
                  reference_results: dict[str, dict[str, Any]], params: dict[str, Any], *,
                  layout: store.Layout | None = None, references: dict[str, Any] | None = None) -> dict[str, Any]:
    """The lane-level references a run's takes are scored against.

    The voice pitch centroids (`mode|voice`) and the per-cell Audiobox baselines come first from the
    frozen references (`references`, else the newest `config/qc/references-v<N>.json` under
    `layout`; `qc.references`), so a take scores the same whatever else its run holds. A voice or
    cell the references lack falls back to this run's own takes; `context["references"]` names the
    file, its digest and those fallbacks (None without a references file: every value is the
    run's own). The clone references' pitch is measured per clip, and the speaker centroid is
    leave-one-out over the voice's custom-mode takes (`speaker_centroid`).
    """

    if references is None and layout is not None:
        from qc import references as references_lib

        references = references_lib.load(layout)
    voice_pitch: dict[str, list[float]] = {}
    voice_embeddings: dict[str, dict[str, Any]] = {}
    cell_aesthetics: dict[str, dict[str, list[float]]] = {}
    for take in takes:
        results = results_by_token.get(take["token"], {})
        key = voice_key(take)
        median = take_pitch_median(results, params)
        if median is not None:
            voice_pitch.setdefault(key, []).append(median)
        speaker = outputs(results, "speaker")
        if speaker is not None and speaker.get("whole") and take.get("mode") == "custom":
            vector = np.asarray(speaker["whole"], dtype=float)
            entry = voice_embeddings.setdefault(key, {"sum": np.zeros_like(vector), "count": 0, "members": set()})
            if entry["sum"].shape == vector.shape:
                entry["sum"] = entry["sum"] + vector
                entry["count"] += 1
                entry["members"].add(take["token"])
        aesthetics = outputs(results, "aesthetics")
        if aesthetics is not None:
            bucket = cell_aesthetics.setdefault(str(take.get("cell")), {})
            for axis in AESTHETICS_AXES:
                if aesthetics.get(axis) is not None:
                    bucket.setdefault(axis, []).append(float(aesthetics[axis]))
    reference_pitch = {}
    for reference_sha, results in reference_results.items():
        median = take_pitch_median(results, params)
        if median is not None:
            reference_pitch[reference_sha] = median
    run_pitch = {key: float(np.median(values)) for key, values in voice_pitch.items()}
    run_cells = {cell: {axis: float(np.median(values)) for axis, values in axes.items()}
                 for cell, axes in cell_aesthetics.items()}
    pitch_by_voice, cells, record = dict(run_pitch), dict(run_cells), None
    if references:
        frozen_pitch = {key: float(entry["median"]) for key, entry in (references.get("voicePitch") or {}).items()}
        frozen_cells = {cell: {axis: float(entry["median"]) for axis, entry in axes.items()}
                        for cell, axes in (references.get("cellAesthetics") or {}).items()}
        pitch_by_voice = {**run_pitch, **frozen_pitch}
        cells = {**run_cells, **{cell: {**run_cells.get(cell, {}), **axes} for cell, axes in frozen_cells.items()}}
        record = {"file": references.get("file"), "sha256": references.get("sha256"),
                  "fallbacks": {"voicePitch": sorted(key for key in run_pitch if key not in frozen_pitch),
                                "cellAesthetics": sorted(cell for cell in run_cells if cell not in frozen_cells)}}
    return {
        "voicePitch": pitch_by_voice,
        "voicePitchSD": {key: float(np.std(values)) for key, values in voice_pitch.items() if len(values) > 1},
        "voiceEmbeddings": voice_embeddings,
        "referencePitch": reference_pitch,
        "cellAesthetics": cells,
        "references": record,
    }
