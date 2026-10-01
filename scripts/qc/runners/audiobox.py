"""Audiobox Aesthetics on torch (CPU, or MPS by option): `<torch python> -m qc.runners.audiobox --job <job.json>`.

Meta's Audiobox Aesthetics (`facebook/audiobox-aesthetics`, CC BY 4.0; PyPI `audiobox_aesthetics`) scores
Content Enjoyment, Content Usefulness, Production Complexity and Production Quality. The model directory
holds the repository's `config.json` and `model.safetensors`, loaded with `AesMultiOutput.from_pretrained`
on that local directory (the package would otherwise fetch the hub id); the `checkpoint.pt` format is
the fallback. The predictor is the package's own `AesPredictor.forward`: 16 kHz mono, 10 s chunks
weighted by their valid length, the targets de-normalized. Audio goes in as an in-memory tensor, since
the package's file reader needs `torchaudio.info`, which torchaudio 2.9 removed.
"""
from __future__ import annotations

import contextlib
import io
import os
import sys
from pathlib import Path
from typing import Any, Mapping

from qc.runners import _kit

SAMPLE_RATE = 16_000
AXES = ("CE", "CU", "PC", "PQ")


def build_predictor(model_dir: Path, device: str) -> Any:
    import torch
    from audiobox_aesthetics.infer import AXES_NAME, AesPredictor, initialize_predictor  # type: ignore
    from audiobox_aesthetics.model.aes import AesMultiOutput, Normalize  # type: ignore

    if (model_dir / "config.json").is_file() and (model_dir / "model.safetensors").is_file():
        model = AesMultiOutput.from_pretrained(str(model_dir))
        predictor = AesPredictor.__new__(AesPredictor)  # skip __post_init__: it would load the hub id
        predictor.checkpoint_pth = None
        predictor.precision = "32"
        predictor.batch_size = 1
        predictor.data_col = "path"
        predictor.sample_rate = SAMPLE_RATE
        predictor.model = model
        predictor.target_transform = {
            axis: Normalize(mean=model.target_transform[axis]["mean"], std=model.target_transform[axis]["std"])
            for axis in AXES_NAME
        }
    elif (model_dir / "checkpoint.pt").is_file():
        predictor = initialize_predictor(ckpt=str(model_dir / "checkpoint.pt"))
    else:
        raise FileNotFoundError("audiobox-aesthetics weights")
    predictor.device = torch.device(device)
    predictor.model.to(predictor.device)
    predictor.model.eval()
    return predictor


class Aesthetics:
    def __init__(self, predictor: Any) -> None:
        self.predictor = predictor

    def score(self, audio: Any, sr: int) -> Mapping[str, Any]:
        import torch

        rows = self.predictor.forward([{"path": torch.from_numpy(audio)[None, :], "sample_rate": sr}])
        return rows[0]


def load(job: Mapping[str, Any]) -> Aesthetics:
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    import torch

    options = job.get("options") or {}
    device = str(options.get("device", "cpu"))
    if device == "mps" and not torch.backends.mps.is_available():
        device = "cpu"
    with contextlib.redirect_stdout(io.StringIO()):
        return Aesthetics(build_predictor(Path(job["modelDir"]), device))


def scores(row: Mapping[str, Any]) -> dict[str, float]:
    return {axis: round(float(row[axis]), 4) for axis in AXES}


def process(model: Aesthetics, take: Mapping[str, Any], job: Mapping[str, Any]) -> tuple[dict[str, Any], float, None]:
    audio, sr, duration = _kit.load_take_audio(take, SAMPLE_RATE)
    return scores(model.score(audio, sr)), duration, None


if __name__ == "__main__":
    sys.exit(_kit.main(load, process))
