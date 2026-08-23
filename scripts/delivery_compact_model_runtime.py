#!/usr/bin/env python3
"""CPU-only executor for pinned compact delivery representation models.

This process receives canonical 16 kHz mono PCM, never receives a requested
delivery label, and emits one privacy-safe JSON object. Model acquisition and
provenance validation remain the caller's responsibility.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import wave

import numpy as np


PROJECTION_VERSION = "signed-gaussian-mean-std-five-region-v1"
PROJECTION_SEED = 20260823
PROJECTION_DIMENSIONS = 128


class CompactRuntimeError(ValueError):
    """The local compact runtime input or model is invalid."""


def _read_pcm(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as reader:
        if (
            reader.getnchannels() != 1 or reader.getsampwidth() != 2
            or reader.getframerate() != 16_000
        ):
            raise CompactRuntimeError("input must be canonical 16 kHz mono PCM16")
        frames = reader.readframes(reader.getnframes())
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if samples.size == 0 or not np.all(np.isfinite(samples)):
        raise CompactRuntimeError("input audio is empty or non-finite")
    return samples


def _project(hidden: np.ndarray) -> list[float]:
    if hidden.ndim != 2 or hidden.shape[0] < 1 or hidden.shape[1] < 1:
        raise CompactRuntimeError("DistilHuBERT hidden representation is invalid")
    regions = [region for region in np.array_split(hidden, 5, axis=0) if len(region)]
    if len(regions) != 5:
        raise CompactRuntimeError("DistilHuBERT output is too short for five regions")
    pooled = np.concatenate((
        hidden.mean(axis=0), hidden.std(axis=0),
        *(region.mean(axis=0) for region in regions),
    )).astype(np.float64)
    generator = np.random.default_rng(PROJECTION_SEED)
    projection = generator.choice(
        np.asarray((-1.0, 1.0)), size=(pooled.size, PROJECTION_DIMENSIONS)
    ) / np.sqrt(PROJECTION_DIMENSIONS)
    embedded = pooled @ projection
    norm = float(np.linalg.norm(embedded))
    if not np.isfinite(norm) or norm <= 0:
        raise CompactRuntimeError("DistilHuBERT projected embedding is degenerate")
    embedded /= norm
    return [round(float(value), 9) for value in embedded]


def distilhubert(weights: Path, audio: Path) -> dict[str, object]:
    os.environ.update({
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "TOKENIZERS_PARALLELISM": "false",
    })
    samples = _read_pcm(audio)
    try:
        import torch
        from transformers import AutoFeatureExtractor, AutoModel
    except ImportError as error:
        raise CompactRuntimeError("pinned DistilHuBERT runtime dependencies are unavailable") from error
    torch.set_num_threads(min(4, max(1, os.cpu_count() or 1)))
    try:
        torch.set_num_interop_threads(1)
    except RuntimeError:
        pass
    model_dir = weights.parent
    if not weights.is_file():
        raise CompactRuntimeError("pinned DistilHuBERT weights are missing")
    extractor = AutoFeatureExtractor.from_pretrained(model_dir, local_files_only=True)
    model = AutoModel.from_pretrained(
        model_dir, local_files_only=True, use_safetensors=True
    ).to("cpu").eval()
    inputs = extractor(samples, sampling_rate=16_000, return_tensors="pt")
    with torch.inference_mode():
        hidden = model(**{key: value.to("cpu") for key, value in inputs.items()}).last_hidden_state[0]
    array = hidden.detach().to(dtype=torch.float32).cpu().numpy()
    return {
        "embedding": _project(array),
        "embeddingDimensions": PROJECTION_DIMENSIONS,
        "projectionVersion": PROJECTION_VERSION,
        "frameCount": int(array.shape[0]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", choices=("distilhubert",))
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--audio", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.model == "distilhubert":
            output = distilhubert(args.weights, args.audio)
        else:  # pragma: no cover - argparse owns the branch
            raise CompactRuntimeError("unsupported compact runtime")
        print(json.dumps(output, sort_keys=True, separators=(",", ":")))
        return 0
    except CompactRuntimeError as error:
        print(f"Compact delivery runtime: FAIL\n{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
