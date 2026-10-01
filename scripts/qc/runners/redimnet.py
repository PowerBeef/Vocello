"""ReDimNet2+ speaker embeddings on torch (CPU, or MPS by option): `<torch python> -m qc.runners.redimnet --job <job.json>`.

Weights: `lab260/redimnet2-plus` (Apache-2.0), `pytorch_model_fsdp.bin`, a plain state dict of the
ASV model (`_orig_mod.` prefixed, encoder plus a SphereFace2 classifier that is dropped). 0.35% EER on
VoxCeleb1-O with 4 s windows, against CAM++'s 0.66%. Code: `lab260ru/redimnet2-plus` (MIT), pinned by
commit and unpacked under `<modelDir>/code/` (or `options.codeDir`); it is not a pip package and has no
torch.hub entry. Only its `asv/models/redimnet2.py` and `asv/models/redimnet2_vendor/` are imported:
`asv` and `asv.models` are registered as bare packages so their `__init__` (hydra, omegaconf) never
runs. It needs torch, torchaudio and scipy.

The encoder is the B6 preset (`out_channels` 224, 2-D head: the released checkpoint's head is a 1x1
Conv2d over 72 mel bands, pooled from 224 x 9 features), built with `pretrained=False` so
nothing is downloaded. Its `forward` takes a spectrogram: the trained front end is the module's own
`spec_frontend` (pre-emphasis, 400-sample Hamming, 512-point FFT, hop 160, the preset's mel bands,
log, per-utterance mean removal) applied to 16 kHz `[B, T]` audio, as the authors' submission code
does, not the model card's torchaudio snippet (whose 64 mels may not match). A front-end or shape
mismatch fails the strict tensor-shape load. Embeddings are 192-d and L2-normalized.

Outputs: 4 s windows at a 1 s hop (a take shorter than 4 s is one whole-take window), the whole-take
embedding, and the clone reference's whole embedding when the take has one (then the result is keyed
by the variant).
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from qc.runners import _kit

SAMPLE_RATE = 16_000
WINDOW_SECONDS = 4.0
HOP_SECONDS = 1.0
MAX_SECONDS = 60.0  # the model card's maximum input; longer audio is embedded per 60 s and averaged
MIN_SECONDS = 0.5
WEIGHTS_FILE = "pytorch_model_fsdp.bin"
MODEL_OVERRIDES = {"out_channels": 224, "return_2d_output": True}
BATCH = 16


def find_code_root(model_dir: Path, options: Mapping[str, Any]) -> Path:
    """The directory holding `asv/models/redimnet2.py`: `options.codeDir`, `<modelDir>/code` or one
    level below it (an unpacked GitHub archive)."""
    candidates = [Path(options["codeDir"])] if options.get("codeDir") else []
    code = model_dir / "code"
    candidates += [code] + (sorted(p for p in code.iterdir() if p.is_dir()) if code.is_dir() else [])
    for candidate in candidates:
        if (candidate / "asv/models/redimnet2.py").is_file():
            return candidate
    raise FileNotFoundError("redimnet2-plus code")


def import_encoder_class(code_root: Path) -> Any:
    for name, relative in (("asv", "asv"), ("asv.models", "asv/models")):
        if name not in sys.modules:
            package = types.ModuleType(name)
            package.__path__ = [str(code_root / relative)]  # a bare package: its __init__ never runs
            sys.modules[name] = package
    from asv.models.redimnet2 import ReDimNet2Encoder  # type: ignore

    return ReDimNet2Encoder


def strip_prefixes(state: Mapping[str, Any]) -> dict[str, Any]:
    """Drop torch.compile's `_orig_mod` segments wherever they sit and DDP's leading `module.`."""
    cleaned = {}
    for key, value in state.items():
        parts = [part for part in key.split(".") if part != "_orig_mod"]
        while parts and parts[0] == "module":
            parts.pop(0)
        cleaned[".".join(parts)] = value
    return cleaned


def encoder_state(state: Mapping[str, Any]) -> dict[str, Any]:
    """The encoder's tensors from an ASV-model state dict (`encoder.` prefix; the classifier and any
    other head are dropped), or the dict itself when it is already encoder-only."""
    state = strip_prefixes(state)
    if "state_dict" in state and isinstance(state["state_dict"], Mapping):
        state = strip_prefixes(state["state_dict"])
    encoder = {key[len("encoder."):]: value for key, value in state.items() if key.startswith("encoder.")}
    return encoder or dict(state)


def check_load(result: Any) -> None:
    """Only the front-end alias may be missing (its filterbank is rebuilt identically in __init__)."""
    missing = [k for k in result.missing_keys if not k.startswith(("spec_frontend.", "model.spec."))]
    unexpected = list(result.unexpected_keys)
    if missing or unexpected:
        raise RuntimeError(f"redimnet2-plus checkpoint mismatch: {len(missing)} missing, {len(unexpected)} unexpected")


class Embedder:
    """Wraps the encoder: `embed(batch [N, T] float32 at 16 kHz) -> [N, D]` L2-normalized."""

    def __init__(self, encoder: Any, device: str) -> None:
        import torch

        self.torch = torch
        self.encoder = encoder.to(device).eval()
        self.device = device

    def embed(self, batch: np.ndarray) -> np.ndarray:
        torch = self.torch
        with torch.inference_mode():
            audio = torch.from_numpy(np.ascontiguousarray(batch, dtype=np.float32)).to(self.device)
            spectrum = self.encoder.spec_frontend(audio)
            embeddings = self.encoder(spectrum).float()
            embeddings = torch.nn.functional.normalize(embeddings, dim=1)
        return embeddings.cpu().numpy()


def load(job: Mapping[str, Any]) -> dict[str, Any]:
    import torch

    options = job.get("options") or {}
    model_dir = Path(job["modelDir"])
    encoder_class = import_encoder_class(find_code_root(model_dir, options))
    encoder = encoder_class(model_name="b6", pretrained=False, model_overrides=dict(MODEL_OVERRIDES))
    state = torch.load(model_dir / options.get("weightsFile", WEIGHTS_FILE), map_location="cpu", weights_only=True)
    check_load(encoder.load_state_dict(encoder_state(state), strict=False))
    device = str(options.get("device", "cpu"))
    if device == "mps" and not torch.backends.mps.is_available():
        device = "cpu"
    torch.manual_seed(0)
    return {"embedder": Embedder(encoder, device), "references": {}}


def whole_embedding(embedder: Any, audio: np.ndarray) -> np.ndarray:
    """One embedding for the whole clip; clips over 60 s are averaged over 60 s pieces."""
    limit = int(MAX_SECONDS * SAMPLE_RATE)
    if audio.size <= limit:
        return embedder.embed(audio[None, :])[0]
    pieces = [audio[i:i + limit] for i in range(0, audio.size, limit)]
    pieces = [p for p in pieces if p.size >= MIN_SECONDS * SAMPLE_RATE]
    mean = np.mean([embedder.embed(p[None, :])[0] for p in pieces], axis=0)
    return mean / max(float(np.linalg.norm(mean)), 1e-12)


def window_embeddings(embedder: Any, audio: np.ndarray, duration: float) -> list[dict[str, Any]]:
    spans = _kit.windows(duration, WINDOW_SECONDS, HOP_SECONDS)
    if len(spans) == 1:
        return [{"start": 0.0, "end": round(duration, 6), "embedding": _kit.unit(whole_embedding(embedder, audio))}]
    length = int(round(WINDOW_SECONDS * SAMPLE_RATE))
    batch = []
    for start, _ in spans:
        offset = min(int(round(start * SAMPLE_RATE)), audio.size - length)
        batch.append(audio[offset:offset + length])
    vectors = np.concatenate([embedder.embed(np.stack(batch[i:i + BATCH])) for i in range(0, len(batch), BATCH)])
    return [{"start": start, "end": end, "embedding": _kit.unit(vector)} for (start, end), vector in zip(spans, vectors)]


def variant_of(take: Mapping[str, Any]) -> str | None:
    return _kit.variant_key(take) if take.get("reference") else None


def process(model: Mapping[str, Any], take: Mapping[str, Any], job: Mapping[str, Any]) -> tuple[dict[str, Any], float, str | None]:
    embedder = model["embedder"]
    audio, _, duration = _kit.load_take_audio(take, SAMPLE_RATE)
    if audio.size < MIN_SECONDS * SAMPLE_RATE:
        raise _kit.TakeError("audio-too-short")
    duration_16k = audio.size / SAMPLE_RATE
    outputs: dict[str, Any] = {
        "windowSeconds": WINDOW_SECONDS,
        "hopSeconds": HOP_SECONDS,
        "windows": window_embeddings(embedder, audio, duration_16k),
        "whole": _kit.unit(whole_embedding(embedder, audio)),
        "reference": None,
    }
    if take.get("reference"):
        key = take.get("referenceSHA256") or str(take["reference"])
        if key not in model["references"]:
            reference, _, _ = _kit.load_take_audio(take, SAMPLE_RATE, key="reference")
            if reference.size < MIN_SECONDS * SAMPLE_RATE:
                raise _kit.TakeError("reference-too-short")
            model["references"][key] = _kit.unit(whole_embedding(embedder, reference))
        outputs["reference"] = model["references"][key]
    return outputs, duration, variant_of(take)


if __name__ == "__main__":
    sys.exit(_kit.main(load, process, variant_of=variant_of))
