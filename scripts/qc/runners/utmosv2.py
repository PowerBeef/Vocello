"""UTMOSv2 naturalness MOS on torch (CPU, or MPS by option): `<torch python> -m qc.runners.utmosv2 --job <job.json>`.

UTMOSv2 (`sarulab-speech/UTMOSv2`, MIT; VoiceMOS 2024 winner) is installed from git at a pinned commit
(`config/qc/runtimes/torch.txt`), or loaded from that commit's archive under `<modelDir>/code/`. The
weights are a fold checkpoint `fold<k>_s42_best_model.pth` (MIT) in the model directory, passed as
`checkpoint_path` so the library's own `wget` download never runs.

Building the model would still reach the network: `timm.create_model(..., pretrained=True)` for its
EfficientNetV2-S spectrogram backbones and `transformers` `from_pretrained("facebook/wav2vec2-base")`
for its SSL branch. The fold checkpoint is loaded strictly over every one of those weights, so the
runner forces timm's `pretrained=False` and points the wav2vec2 calls at a local copy of
`facebook/wav2vec2-base` (`config.json`, `preprocessor_config.json`, and `pytorch_model.bin` when
present, else built from the config). `HF_HUB_OFFLINE` and `TRANSFORMERS_OFFLINE` are set before
anything imports the hub, so a missing file fails instead of downloading.

UTMOSv2 scores random crops (3 s for the SSL branch, two 1.4 s spectrogram crops with mixup), so
every prediction is seeded and the whole take averages `repetitions` passes (5, the paper's
setting). Windows are 3 s at a 1 s hop; each holds 48,001 samples so the SSL branch crops from the
window start instead of tiling it. `remove_silent_section` is off (its signed threshold drops quiet
speech). A take of 3 s or less is one whole-take window.
"""
from __future__ import annotations

import contextlib
import io
import os
import random
import sys
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from qc.runners import _kit

SAMPLE_RATE = 16_000
WINDOW_SECONDS = 3.0
HOP_SECONDS = 1.0
WINDOW_SAMPLES = int(WINDOW_SECONDS * SAMPLE_RATE) + 1
CONFIG = "fusion_stage3"
SSL_NAME = "facebook/wav2vec2-base"
SEED = 0


def candidate_dirs(base: Path) -> list[Path]:
    return [base] + (sorted(p for p in base.iterdir() if p.is_dir()) if base.is_dir() else [])


def find_code_root(model_dir: Path, options: Mapping[str, Any]) -> Path | None:
    """A UTMOSv2 source tree (`utmosv2/__init__.py`) from `options.codeDir` or `<modelDir>/code`."""
    roots = [Path(options["codeDir"])] if options.get("codeDir") else []
    for candidate in roots + candidate_dirs(model_dir / "code"):
        if (candidate / "utmosv2/__init__.py").is_file():
            return candidate
    return None


def find_ssl_dir(model_dir: Path, options: Mapping[str, Any]) -> Path | None:
    """The local `facebook/wav2vec2-base` directory (`options.ssl`, or beside the checkpoint)."""
    candidates = [Path(options["ssl"])] if options.get("ssl") else []
    for base in (model_dir / "deps", model_dir, model_dir.parent):
        candidates += [base / "wav2vec2-base", base / "facebook--wav2vec2-base", base / "mos.utmosv2.dep.wav2vec2-base"]
    for candidate in candidates:
        if (candidate / "config.json").is_file() and (candidate / "preprocessor_config.json").is_file():
            return candidate
    return None


def go_offline(ssl_dir: Path | None) -> None:
    """Keep model construction off the network (see the module docstring)."""
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    import timm  # type: ignore

    create = timm.create_model
    if not getattr(create, "_qcOffline", False):
        def create_model(*args: Any, **kwargs: Any) -> Any:
            kwargs["pretrained"] = False  # the fold checkpoint replaces these weights
            return create(*args, **kwargs)

        create_model._qcOffline = True  # type: ignore[attr-defined]
        timm.create_model = create_model
    if ssl_dir is None:
        return
    import transformers  # type: ignore

    extractor = transformers.AutoFeatureExtractor.from_pretrained
    model = transformers.AutoModel.from_pretrained
    has_weights = any((ssl_dir / name).is_file() for name in ("pytorch_model.bin", "model.safetensors"))

    def local_extractor(cls: Any, name: Any, *args: Any, **kwargs: Any) -> Any:
        return extractor(str(ssl_dir) if name == SSL_NAME else name, *args, **kwargs)

    def local_model(cls: Any, name: Any, *args: Any, **kwargs: Any) -> Any:
        if name != SSL_NAME:
            return model(name, *args, **kwargs)
        if has_weights:
            return model(str(ssl_dir), *args, **kwargs)
        return transformers.AutoModel.from_config(transformers.AutoConfig.from_pretrained(str(ssl_dir)))

    transformers.AutoFeatureExtractor.from_pretrained = classmethod(local_extractor)
    transformers.AutoModel.from_pretrained = classmethod(local_model)


class Scorer:
    def __init__(self, model: Any, device: str, dataset: str, batch: int) -> None:
        self.model = model
        self.device = device
        self.dataset = dataset
        self.batch = batch

    def predict(self, clips: np.ndarray, repetitions: int) -> np.ndarray:
        """MOS per row of `clips` ([N, T], 16 kHz), seeded so the result never depends on order."""
        import torch

        random.seed(SEED)
        np.random.seed(SEED)
        torch.manual_seed(SEED)
        values = self.model.predict(
            data=np.ascontiguousarray(clips, dtype=np.float32), sr=SAMPLE_RATE, predict_dataset=self.dataset,
            device=self.device, num_workers=0, batch_size=self.batch, num_repetitions=repetitions,
            remove_silent_section=False, verbose=False,
        )
        return np.atleast_1d(np.asarray(values, dtype=np.float64))


@contextlib.contextmanager
def quiet_stdout():
    """The library prints the checkpoint path on load; runners keep stdout to progress lines."""
    with contextlib.redirect_stdout(io.StringIO()):
        yield


def load(job: Mapping[str, Any]) -> dict[str, Any]:
    options = job.get("options") or {}
    model_dir = Path(job["modelDir"])
    code_root = find_code_root(model_dir, options)
    if code_root is not None and str(code_root) not in sys.path:
        sys.path.insert(0, str(code_root))
    go_offline(find_ssl_dir(model_dir, options))
    import torch
    import utmosv2  # type: ignore

    fold = int(options.get("fold", 0))
    checkpoint = model_dir / options.get("checkpointFile", f"fold{fold}_s42_best_model.pth")
    if not checkpoint.is_file():
        raise FileNotFoundError("utmosv2 checkpoint")
    device = str(options.get("device", "cpu"))
    if device == "mps" and not torch.backends.mps.is_available():
        device = "cpu"
    with quiet_stdout():
        model = utmosv2.create_model(pretrained=True, config=CONFIG, fold=fold, checkpoint_path=checkpoint, device="cpu")
    return {
        "scorer": Scorer(model, device, str(options.get("predictDataset", "sarulab")), int(options.get("batchSize", 16))),
        "repetitions": int(options.get("repetitions", 5)),
        "windowRepetitions": int(options.get("windowRepetitions", 1)),
        "windows": bool(options.get("windows", True)),
        "fold": fold,
    }


def window_scores(scorer: Any, audio: np.ndarray, duration: float, repetitions: int) -> list[dict[str, Any]]:
    spans = _kit.windows(duration, WINDOW_SECONDS, HOP_SECONDS)
    clips = []
    for start, _ in spans:
        offset = max(0, min(int(round(start * SAMPLE_RATE)), audio.size - WINDOW_SAMPLES))
        clip = audio[offset:offset + WINDOW_SAMPLES]
        clips.append(np.pad(clip, (0, WINDOW_SAMPLES - clip.size)))
    scores = scorer.predict(np.stack(clips), repetitions)
    return [{"start": start, "end": end, "mos": round(float(score), 4)} for (start, end), score in zip(spans, scores)]


def process(model: Mapping[str, Any], take: Mapping[str, Any], job: Mapping[str, Any]) -> tuple[dict[str, Any], float, None]:
    scorer = model["scorer"]
    audio, _, duration = _kit.load_take_audio(take, SAMPLE_RATE)
    seconds = audio.size / SAMPLE_RATE
    whole = round(float(scorer.predict(audio[None, :], model["repetitions"])[0]), 4)
    if seconds <= WINDOW_SECONDS + 1e-9 or not model["windows"]:
        windows = [{"start": 0.0, "end": round(seconds, 6), "mos": whole}] if model["windows"] else []
    else:
        windows = window_scores(scorer, audio, seconds, model["windowRepetitions"])
    outputs = {"mos": whole, "windows": windows, "fold": model["fold"], "repetitions": model["repetitions"]}
    return outputs, duration, None


if __name__ == "__main__":
    sys.exit(_kit.main(load, process))
