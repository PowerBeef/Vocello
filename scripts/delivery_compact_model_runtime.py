#!/usr/bin/env python3
"""CPU-only executor for pinned compact delivery representation models.

This process receives mono PCM16 (canonical 16 kHz for representation models,
the original rate for the NISQA clip-quality screen), never receives a
requested delivery label, and emits one privacy-safe JSON object. Model
acquisition and provenance validation remain the caller's responsibility.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any
import wave

import numpy as np


PROJECTION_VERSION = "signed-gaussian-mean-std-five-region-v1"
PROJECTION_SEED = 20260823
PROJECTION_DIMENSIONS = 128
# NISQA v2 output order (the port's comment: MOS, noisiness, discontinuity, coloration, loudness).
NISQA_DIMENSIONS = ("mos", "noisiness", "discontinuity", "coloration", "loudness")


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


def _read_wav_native(path: Path) -> tuple[np.ndarray, int]:
    """Mono PCM16 at whatever rate the file carries (the clip-quality screen scores the original)."""
    with wave.open(str(path), "rb") as reader:
        if reader.getnchannels() != 1 or reader.getsampwidth() != 2:
            raise CompactRuntimeError("input must be mono PCM16")
        rate = reader.getframerate()
        frames = reader.readframes(reader.getnframes())
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if rate <= 0 or samples.size == 0 or not np.all(np.isfinite(samples)):
        raise CompactRuntimeError("input audio is empty or non-finite")
    return samples, rate


def _nisqa_chunks(samples: np.ndarray, rate: int, args: dict[str, Any]) -> list[np.ndarray]:
    """Split audio so every chunk fits the model's segment budget (about 52 s at a 10 ms hop)."""
    hop = float(args["ms_hop_length"])
    budget_frames = int(args["ms_max_segments"]) * int(args["ms_seg_hop_length"])
    chunk_samples = int((budget_frames - int(args["ms_seg_length"]) - 8) * hop * rate)
    if chunk_samples <= 0:
        raise CompactRuntimeError("NISQA segment budget is invalid")
    chunks = [samples[start:start + chunk_samples] for start in range(0, samples.size, chunk_samples)]
    minimum = int(rate * hop * (int(args["ms_seg_length"]) + 1))
    if len(chunks) > 1 and chunks[-1].size < minimum:
        chunks[-2] = np.concatenate((chunks[-2], chunks[-1]))
        chunks.pop()
    return chunks


def nisqa(weights: Path, audio: Path) -> dict[str, object]:
    """NISQA v2 non-intrusive quality dimensions of one clip at its native rate."""
    samples, rate = _read_wav_native(audio)
    try:
        import torch
        from torchmetrics.functional.audio import nisqa as port
    except ImportError as error:
        raise CompactRuntimeError("pinned NISQA runtime dependencies are unavailable") from error
    torch.set_num_threads(min(4, max(1, os.cpu_count() or 1)))
    try:
        torch.set_num_interop_threads(1)
    except RuntimeError:
        pass
    if not weights.is_file():
        raise CompactRuntimeError("pinned NISQA weights are missing")
    checkpoint = torch.load(weights, map_location="cpu", weights_only=True)
    args = checkpoint["args"]
    model = port._NISQADIM(args)
    model.load_state_dict(checkpoint["model_state_dict"], strict=True)
    model.eval()
    chunks = _nisqa_chunks(samples, rate, args)
    per_chunk: list[list[float]] = []
    for chunk in chunks:
        mel = port._get_librosa_melspec(chunk[None, :], rate, args)
        try:
            segments, n_wins = port._segment_specs(torch.from_numpy(mel), args)
        except RuntimeError as error:
            raise CompactRuntimeError(f"NISQA cannot segment this clip: {error}") from error
        with torch.inference_mode():
            scores = model(segments, n_wins.expand(segments.shape[0]))[0]
        values = [float(value) for value in scores.tolist()]
        if len(values) != len(NISQA_DIMENSIONS) or any(not np.isfinite(value) for value in values):
            raise CompactRuntimeError("NISQA emitted an invalid score vector")
        per_chunk.append(values)
    matrix = np.asarray(per_chunk, dtype=np.float64)
    weights_per_chunk = np.asarray([chunk.size for chunk in chunks], dtype=np.float64)
    weighted = (matrix * weights_per_chunk[:, None]).sum(axis=0) / weights_per_chunk.sum()
    return {
        **{name: round(float(value), 4) for name, value in zip(NISQA_DIMENSIONS, weighted)},
        "minimumChunkMOS": round(float(matrix[:, 0].min()), 4),
        "chunkCount": int(matrix.shape[0]),
        "sampleRateHz": int(rate),
        "durationSeconds": round(float(samples.size) / rate, 3),
        "modelArchitecture": str(args.get("model")),
        "frontEnd": {
            "nFFT": int(args["ms_n_fft"]), "hopSeconds": float(args["ms_hop_length"]),
            "windowSeconds": float(args["ms_win_length"]), "nMels": int(args["ms_n_mels"]),
            "fmaxHz": int(args["ms_fmax"]), "segmentLength": int(args["ms_seg_length"]),
            "segmentHop": int(args["ms_seg_hop_length"]), "maxSegments": int(args["ms_max_segments"]),
        },
    }


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
    parser.add_argument("model", choices=("distilhubert", "nisqa"))
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--audio", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.model == "distilhubert":
            output = distilhubert(args.weights, args.audio)
        elif args.model == "nisqa":
            output = nisqa(args.weights, args.audio)
        else:  # pragma: no cover - argparse owns the branch
            raise CompactRuntimeError("unsupported compact runtime")
        print(json.dumps(output, sort_keys=True, separators=(",", ":")))
        return 0
    except CompactRuntimeError as error:
        print(f"Compact delivery runtime: FAIL\n{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
