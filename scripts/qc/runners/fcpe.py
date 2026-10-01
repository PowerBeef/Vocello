"""FCPE pitch on torch (CPU, or MPS by option): `<torch python> -m qc.runners.fcpe --job <job.json>`.

FCPE (Fast Context-based Pitch Estimation, `CNChTu/FCPE`, MIT) is the second pitch tracker beside
SwiftF0. Code: PyPI `torchfcpe` 0.0.4. Weights: `torchfcpe/assets/fcpe_c_v001.pt`, shipped in that MIT
repository and wheel; the copy fetched into the model directory (hash-verified by
`qc.py models verify`) is used, else the wheel's own. The checkpoint is a plain state dict plus a
config dict, so it loads with `torch.load(weights_only=True)`. (The authors' later paper checkpoint,
`DDSP_200k.pt` on Hugging Face `ChiTu/FCPE`, is CC BY-NC-SA 4.0 and is not used.)

The bundled model (conv-only conformer, 360 bins over 32.70-1975.5 Hz) takes torchfcpe's own
16 kHz log-mel (128 bands, 1024-point STFT, hop 160), so frames come every 10 ms, `len // 160 + 1` of
them; torchfcpe's left padding centres frame `k` 5 ms after `k * 10 ms`, within the half-frame the
schema's grid allows. The runner runs the model to its sigmoid salience and decodes it here as
torchfcpe's `local_argmax` decoder does: the salience-weighted mean of the 9 bins around the peak.
`confidence` is the peak salience, FCPE's voicing output; a frame is voiced above `threshold`
(torchfcpe's recommended 0.006). Voiced frames outside 40-1100 Hz are reported unvoiced, as the
pitch schema fixes the range.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from qc.runners import _kit

SAMPLE_RATE = 16_000
HOP = 160
HOP_SECONDS = HOP / SAMPLE_RATE
THRESHOLD = 0.006
FMIN_HZ = 40.0
FMAX_HZ = 1100.0
MODEL_FILES = ("torchfcpe/assets/fcpe_c_v001.pt", "fcpe_c_v001.pt")


def decode(latent: np.ndarray, cent_table: np.ndarray, threshold: float = THRESHOLD) -> tuple[np.ndarray, np.ndarray]:
    """`(f0 Hz with 0 when unvoiced, peak salience)` from the `[frames, bins]` salience, as
    torchfcpe's `latent2cents_local_decoder` (window indices clamped at the table's ends)."""
    salience = np.asarray(latent, dtype=np.float64)
    cents_table = np.asarray(cent_table, dtype=np.float64)
    bins = salience.shape[1]
    peak_index = salience.argmax(axis=1)
    window = np.clip(peak_index[:, None] + np.arange(-4, 5)[None, :], 0, bins - 1)
    rows = np.arange(salience.shape[0])[:, None]
    weights = salience[rows, window]
    cents = (weights * cents_table[window]).sum(axis=1) / np.maximum(weights.sum(axis=1), 1e-12)
    peak = salience.max(axis=1)
    f0 = np.where(peak > threshold, 10.0 * 2.0 ** (cents / 1200.0), 0.0)
    return f0, peak


def pitch_outputs(f0: np.ndarray, confidence: np.ndarray, threshold: float = THRESHOLD) -> dict[str, Any]:
    in_range = (f0 >= FMIN_HZ) & (f0 <= FMAX_HZ)
    return {
        "hopSeconds": HOP_SECONDS,
        "f0Hz": [round(float(v), 2) if ok else None for v, ok in zip(f0, in_range)],
        "confidence": _kit.rounded(confidence, 4),
        "threshold": threshold,
        "fminHz": FMIN_HZ,
        "fmaxHz": FMAX_HZ,
    }


def find_checkpoint(model_dir: Path, options: Mapping[str, Any]) -> Path:
    """The fetched checkpoint (`options.modelFile`, or the repository path under the model
    directory), else the one inside the installed torchfcpe wheel."""
    names = [options["modelFile"]] if options.get("modelFile") else list(MODEL_FILES)
    for name in names:
        if (model_dir / name).is_file():
            return model_dir / name
    import torchfcpe  # type: ignore

    bundled = Path(torchfcpe.__file__).parent / "assets" / "fcpe_c_v001.pt"
    if not bundled.is_file():
        raise FileNotFoundError("fcpe checkpoint")
    return bundled


class Tracker:
    """torchfcpe's inference module, run to its salience: `salience(audio 16 kHz) -> [frames, bins]`."""

    def __init__(self, model: Any, device: str, threshold: float) -> None:
        import torch

        self.torch = torch
        self.model = model
        self.device = device
        self.threshold = threshold
        self.cent_table = model.model.cent_table.detach().cpu().numpy().astype(np.float64)

    def salience(self, audio: np.ndarray) -> np.ndarray:
        torch = self.torch
        with torch.inference_mode():
            wav = torch.from_numpy(np.ascontiguousarray(audio, dtype=np.float32))[None, :, None].to(self.device)
            mel = self.model.wav2mel(wav, SAMPLE_RATE)  # (1, frames, 128)
            latent = self.model.model(mel)  # (1, frames, bins), sigmoid
        return latent[0].float().cpu().numpy()


def load(job: Mapping[str, Any]) -> Tracker:
    import torch
    from torchfcpe.models_infer import InferCFNaiveMelPE  # type: ignore
    from torchfcpe.tools import DotDict  # type: ignore

    options = job.get("options") or {}
    checkpoint = torch.load(find_checkpoint(Path(job["modelDir"]), options), map_location="cpu", weights_only=True)
    config = checkpoint["config_dict"]
    # As torchfcpe's own loader does for the bundled model (inert in eval mode).
    config["model"]["conv_dropout"] = 0.0
    config["model"]["atten_dropout"] = 0.0
    device = str(options.get("device", "cpu"))
    if device == "mps" and not torch.backends.mps.is_available():
        device = "cpu"
    model = InferCFNaiveMelPE(DotDict(config), checkpoint["model"]).to(device).eval()
    return Tracker(model, device, float(options.get("threshold", THRESHOLD)))


def process(tracker: Tracker, take: Mapping[str, Any], job: Mapping[str, Any]) -> tuple[dict[str, Any], float, None]:
    audio, _, duration = _kit.load_take_audio(take, SAMPLE_RATE)
    expected = audio.size // HOP + 1
    latent = tracker.salience(audio)[:expected]
    f0, confidence = decode(latent, tracker.cent_table, tracker.threshold)
    return pitch_outputs(f0, confidence, tracker.threshold), duration, None


if __name__ == "__main__":
    sys.exit(_kit.main(load, process))
