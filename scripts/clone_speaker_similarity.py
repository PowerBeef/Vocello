#!/usr/bin/env python3
"""Dev-lane speaker-similarity metric for clone fidelity (Stage 3, Q1a).

Computes the cosine similarity between a clone reference recording and one or
more generated takes using a pinned speaker-embedding model. This is the one
clone-rubric axis with no deterministic coverage elsewhere; the score is an
ADVISORY dev-lane metric — it is not a CI gate, not a packaging prerequisite,
and it never publishes benchmark history. PASS-only publication rules are
unchanged.

The embedding backend (SpeechBrain ECAPA-TDNN) is a heavy operator-local
dependency loaded lazily, exactly like the NumPy prosody analyzer: this script
must import and its verdict logic must be testable with no torch installed.
`scripts/test_clone_speaker_similarity.py` exercises everything below the
backend boundary with injected embeddings.

Usage:
    scripts/clone_speaker_similarity.py --reference REF.wav TAKE1.wav [TAKE2.wav …] \
        [--json OUT.json] [--profile PROFILE.json]

Output (stdout table, optional JSON sidecar):
    per-take cosine similarity + advisory band, plus the run aggregate.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Callable

# Pinned backend identity: recorded in every result so scores are only ever
# compared within one embedding-model identity.
ECAPA_SOURCE = "speechbrain/spkrec-ecapa-voxceleb"
ECAPA_REVISION = "0f99f2d0ebe89ac095bcc5903c4dd8f72b367286"

# Advisory bands (uncalibrated defaults; a calibration profile may override).
# ECAPA cosine similarity for same-speaker verification typically sits well
# above 0.5; cross-speaker pairs cluster near or below 0.2. Bands are advisory
# until a measured distribution over the shipping clone path exists.
BUILTIN_PROFILE: dict[str, Any] = {
    "profileVersion": 1,
    "strongMinimum": 0.60,
    "acceptableMinimum": 0.45,
}


def load_similarity_profile(path: str | None) -> dict[str, Any]:
    if path is None:
        return dict(BUILTIN_PROFILE)
    with open(path, encoding="utf-8") as handle:
        loaded = json.load(handle)
    profile = dict(BUILTIN_PROFILE)
    for key in ("profileVersion", "strongMinimum", "acceptableMinimum"):
        if key in loaded:
            profile[key] = loaded[key]
    if not profile["acceptableMinimum"] <= profile["strongMinimum"]:
        raise ValueError("similarity profile bands are inverted")
    return profile


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        raise ValueError("embeddings must be non-empty and equally sized")
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        raise ValueError("zero-norm embedding")
    return dot / (norm_a * norm_b)


def advisory_band(similarity: float, profile: dict[str, Any]) -> str:
    if similarity >= profile["strongMinimum"]:
        return "strong"
    if similarity >= profile["acceptableMinimum"]:
        return "acceptable"
    return "weak"


def analyze_takes(
    reference: str,
    takes: list[str],
    embed: Callable[[str], list[float]],
    profile: dict[str, Any],
) -> dict[str, Any]:
    """Pure aggregation over an injected embedding function.

    Basenames only in the result — the sidecar must stay privacy-safe.
    """
    if not takes:
        raise ValueError("at least one generated take is required")
    reference_embedding = embed(reference)
    rows: list[dict[str, Any]] = []
    for take in takes:
        similarity = cosine_similarity(reference_embedding, embed(take))
        rows.append(
            {
                "take": os.path.basename(take),
                "cosineSimilarity": round(similarity, 4),
                "band": advisory_band(similarity, profile),
            }
        )
    similarities = [row["cosineSimilarity"] for row in rows]
    return {
        "metric": "speaker-cosine-similarity",
        "advisory": True,
        "backend": {"source": ECAPA_SOURCE, "revision": ECAPA_REVISION},
        "profile": profile,
        "reference": os.path.basename(reference),
        "takes": rows,
        "aggregate": {
            "count": len(rows),
            "minimum": min(similarities),
            "median": sorted(similarities)[len(similarities) // 2],
            "maximum": max(similarities),
            "weakCount": sum(1 for row in rows if row["band"] == "weak"),
        },
    }


def ecapa_embedder() -> Callable[[str], list[float]]:
    """Load the pinned ECAPA backend. Operator-local heavy dependency.

    The exact revision is materialized with ``snapshot_download`` and loaded
    from the local path, so the pin holds regardless of whether the installed
    speechbrain still forwards a ``revision`` argument (1.x dropped it).
    """
    import wave  # noqa: PLC0415

    import numpy as np  # noqa: PLC0415
    import torch  # noqa: PLC0415
    from huggingface_hub import snapshot_download  # noqa: PLC0415
    from speechbrain.inference.speaker import EncoderClassifier  # noqa: PLC0415

    local_source = snapshot_download(repo_id=ECAPA_SOURCE, revision=ECAPA_REVISION)
    classifier = EncoderClassifier.from_hparams(
        source=local_source,
        run_opts={"device": "cpu"},
    )

    def embed(path: str) -> list[float]:
        with wave.open(path, "rb") as reader:
            if reader.getsampwidth() != 2:
                raise ValueError(f"expected 16-bit PCM: {path}")
            sample_rate = reader.getframerate()
            channel_count = reader.getnchannels()
            frames = reader.readframes(reader.getnframes())
        pcm = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
        if channel_count > 1:
            pcm = pcm.reshape(-1, channel_count).mean(axis=1)
        if sample_rate != 16_000 and len(pcm) > 1:
            duration = len(pcm) / sample_rate
            target_count = int(round(duration * 16_000))
            positions = np.linspace(0.0, len(pcm) - 1, target_count)
            pcm = np.interp(positions, np.arange(len(pcm)), pcm).astype(np.float32)
        waveform = torch.from_numpy(pcm).unsqueeze(0)
        with torch.no_grad():
            embedding = classifier.encode_batch(waveform)
        return [float(x) for x in embedding.squeeze().tolist()]

    return embed


def write_sidecar(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".speaker-sim-", suffix=".json", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", required=True, help="clone reference WAV")
    parser.add_argument("takes", nargs="+", help="generated take WAVs")
    parser.add_argument("--json", help="write the result sidecar to this path")
    parser.add_argument("--profile", help="advisory-band calibration profile JSON")
    args = parser.parse_args()

    profile = load_similarity_profile(args.profile)
    result = analyze_takes(args.reference, args.takes, ecapa_embedder(), profile)
    for row in result["takes"]:
        print(f"{row['band']:>10}  {row['cosineSimilarity']:.4f}  {row['take']}")
    aggregate = result["aggregate"]
    print(
        f"aggregate: n={aggregate['count']} min={aggregate['minimum']:.4f} "
        f"median={aggregate['median']:.4f} max={aggregate['maximum']:.4f} "
        f"weak={aggregate['weakCount']}"
    )
    if args.json:
        write_sidecar(Path(args.json), result)
        print(f"sidecar: {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
