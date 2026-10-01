"""RMVPE pitch on onnxruntime (CPU): `<onnx python> -m qc.runners.rmvpe --job <job.json>`.

Weights: `rmvpe.onnx` (fp32) from the RVC project's Hugging Face repository `lj1995/VoiceConversionWebUI`.
The model takes RVC's log-mel front end (`MelSpectrogram(is_half, 128, 16000, 1024, 160, None, 30,
8000)` and `mel2hidden` in RVC's `infer/rmvpe.py`, formerly `infer/lib/rmvpe.py`), which `log_mel`
reproduces in numpy: 16 kHz mono, a 1024-point periodic Hann STFT every 160 samples with centered
reflect padding, magnitude (not power), a 128-band HTK-scale mel filterbank from 30 Hz to 8 kHz with
Slaney area normalization (librosa's `filters.mel(..., htk=True)`), then `log(max(mel, 1e-5))`. The
frame count is zero-padded to a multiple of 32, as `mel2hidden` does, and the output cut back.
RVC's voice-conversion pipeline also high-passes at 48 Hz before pitch; its feature extractor, which
this follows, does not.

Decoding follows RVC's `to_local_average_cents`: the salience-weighted mean of the 9 bins around
the peak of 360 bins (20 cents each from 1997.38 cents re 10 Hz); a frame is voiced when its peak
salience exceeds `threshold` (RVC's 0.03). `confidence` is that peak salience. Voiced frames
outside 40-1100 Hz are reported unvoiced, as the pitch schema fixes the range.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from qc.runners import _kit

SAMPLE_RATE = 16_000
N_FFT = 1024
HOP = 160
N_MELS = 128
MEL_FMIN = 30.0
MEL_FMAX = 8000.0
CLAMP = 1e-5
BINS = 360
CENTS_OFFSET = 1997.3794084376191
THRESHOLD = 0.03
FMIN_HZ = 40.0
FMAX_HZ = 1100.0
MODEL_FILE = "rmvpe.onnx"


def _hz_to_mel_htk(hz: np.ndarray | float) -> np.ndarray:
    return 2595.0 * np.log10(1.0 + np.asarray(hz, dtype=np.float64) / 700.0)


def _mel_to_hz_htk(mel: np.ndarray) -> np.ndarray:
    return 700.0 * (10.0 ** (np.asarray(mel, dtype=np.float64) / 2595.0) - 1.0)


def mel_filterbank(sr: int = SAMPLE_RATE, n_fft: int = N_FFT, n_mels: int = N_MELS, fmin: float = MEL_FMIN, fmax: float = MEL_FMAX) -> np.ndarray:
    """librosa.filters.mel(sr, n_fft, n_mels, fmin, fmax, htk=True, norm='slaney') in numpy."""
    fft_freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)
    mel_points = _mel_to_hz_htk(np.linspace(_hz_to_mel_htk(fmin), _hz_to_mel_htk(fmax), n_mels + 2))
    fdiff = np.diff(mel_points)
    ramps = np.subtract.outer(mel_points, fft_freqs)
    weights = np.zeros((n_mels, fft_freqs.size), dtype=np.float64)
    for i in range(n_mels):
        lower = -ramps[i] / fdiff[i]
        upper = ramps[i + 2] / fdiff[i + 1]
        weights[i] = np.maximum(0.0, np.minimum(lower, upper))
    weights *= (2.0 / (mel_points[2:n_mels + 2] - mel_points[:n_mels]))[:, None]
    return weights.astype(np.float32)


_MEL_BASIS: np.ndarray | None = None


def log_mel(audio: np.ndarray) -> np.ndarray:
    """RVC's RMVPE front end: `[128, frames]` float32, one frame per 10 ms (`len // 160 + 1`)."""
    global _MEL_BASIS
    if _MEL_BASIS is None:
        _MEL_BASIS = mel_filterbank()
    samples = np.asarray(audio, dtype=np.float32)
    pad = N_FFT // 2
    if samples.size <= pad:  # reflect padding needs more samples than the pad
        samples = np.pad(samples, (0, pad + 1 - samples.size))
    padded = np.pad(samples, (pad, pad), mode="reflect")
    window = (0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(N_FFT) / N_FFT)).astype(np.float32)  # periodic Hann
    frames = np.lib.stride_tricks.sliding_window_view(padded, N_FFT)[::HOP]
    magnitude = np.abs(np.fft.rfft(frames * window, axis=1)).astype(np.float32).T  # [513, frames]
    mel = _MEL_BASIS @ magnitude
    return np.log(np.maximum(mel, CLAMP)).astype(np.float32)


def pad_frames(mel: np.ndarray, multiple: int = 32) -> np.ndarray:
    frames = mel.shape[-1]
    padded = multiple * ((frames - 1) // multiple + 1)
    return np.pad(mel, ((0, 0), (0, padded - frames))) if padded > frames else mel


CENTS_MAPPING = 20.0 * np.arange(BINS) + CENTS_OFFSET


def decode(hidden: np.ndarray, threshold: float = THRESHOLD) -> tuple[np.ndarray, np.ndarray]:
    """`(f0 Hz with 0 when unvoiced, peak salience)` from the `[frames, 360]` salience."""
    salience = np.asarray(hidden, dtype=np.float32)
    center = np.argmax(salience, axis=1)
    padded = np.pad(salience, ((0, 0), (4, 4)))
    mapping = np.pad(CENTS_MAPPING, (4, 4))
    index = center[:, None] + np.arange(9)[None, :]
    rows = np.arange(salience.shape[0])[:, None]
    local = padded[rows, index]
    cents_local = mapping[index]
    weighted = (local * cents_local).sum(axis=1) / np.maximum(local.sum(axis=1), 1e-12)
    peak = salience.max(axis=1)
    f0 = np.where(peak > threshold, 10.0 * 2.0 ** (weighted / 1200.0), 0.0)
    return f0, peak


def pitch_outputs(f0: np.ndarray, confidence: np.ndarray, threshold: float = THRESHOLD) -> dict[str, Any]:
    in_range = (f0 >= FMIN_HZ) & (f0 <= FMAX_HZ)
    return {
        "hopSeconds": HOP / SAMPLE_RATE,
        "f0Hz": [round(float(v), 2) if ok else None for v, ok in zip(f0, in_range)],
        "confidence": _kit.rounded(confidence, 4),
        "threshold": threshold,
        "fminHz": FMIN_HZ,
        "fmaxHz": FMAX_HZ,
    }


class Model:
    def __init__(self, session: Any, threshold: float) -> None:
        self.session = session
        self.threshold = threshold
        self.input_name = session.get_inputs()[0].name
        self.output_name = session.get_outputs()[0].name

    def hidden(self, mel: np.ndarray) -> np.ndarray:
        frames = mel.shape[-1]
        feed = pad_frames(mel)[None, :, :].astype(np.float32)
        out = self.session.run([self.output_name], {self.input_name: feed})[0]
        return np.asarray(out)[0, :frames, :]


def load(job: Mapping[str, Any]) -> Model:
    import onnxruntime  # type: ignore

    options = job.get("options") or {}
    path = Path(job["modelDir"]) / options.get("modelFile", MODEL_FILE)
    session_options = onnxruntime.SessionOptions()
    if options.get("threads"):
        session_options.intra_op_num_threads = int(options["threads"])
    session = onnxruntime.InferenceSession(str(path), sess_options=session_options, providers=["CPUExecutionProvider"])
    return Model(session, float(options.get("threshold", THRESHOLD)))


def process(model: Model, take: Mapping[str, Any], job: Mapping[str, Any]) -> tuple[dict[str, Any], float, None]:
    audio, _, duration = _kit.load_take_audio(take, SAMPLE_RATE)
    mel = log_mel(audio)
    f0, confidence = decode(model.hidden(mel), model.threshold)
    return pitch_outputs(f0, confidence, model.threshold), duration, None


if __name__ == "__main__":
    sys.exit(_kit.main(load, process))
