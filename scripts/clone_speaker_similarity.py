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
`scripts/tests/test_clone_speaker_similarity.py` exercises everything below the
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
import random
import statistics
import sys
import tempfile
from typing import Any, Callable

# Pinned backend identity: recorded in every result so scores are only ever
# compared within one embedding-model identity.
ECAPA_SOURCE = "speechbrain/spkrec-ecapa-voxceleb"
ECAPA_REVISION = "0f99f2d0ebe89ac095bcc5903c4dd8f72b367286"
# The registry judge this backend is (`config/audio-qc-judges.json`): tier B,
# accepted for internal evaluation only; its snapshot is verified before loading.
ECAPA_JUDGE_ID = "speaker.ecapa-voxceleb@1"
# Waveform preprocessing is part of the score's identity (audit #103): takes
# arrive at 24 kHz and ECAPA reads 16 kHz. The pinned anti-aliased polyphase
# resampler (`scripts/audio_resampling.py`, the one the delivery cache uses)
# replaced `np.interp`, which aliases everything above 8 kHz into the band.
EMBEDDING_SAMPLE_RATE = 16_000
EMBEDDING_RESAMPLER = "polyphase-kaiser5-v2"
ECAPA_PREPROCESSING = {"sampleRateHz": EMBEDDING_SAMPLE_RATE, "resampler": EMBEDDING_RESAMPLER}

# Band calibration needs enough same-voice and different-voice scores to
# estimate a separation; two controls (one cross-gender) cannot (audit #103).
MINIMUM_CALIBRATION_NEGATIVES = 8
SEPARATION_BOOTSTRAP_RESAMPLES = 2_000
SEPARATION_BOOTSTRAP_SEED = 20_260_925

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
        "backend": {
            "source": ECAPA_SOURCE, "revision": ECAPA_REVISION,
            "preprocessing": dict(ECAPA_PREPROCESSING),
        },
        "profile": profile,
        "reference": os.path.basename(reference),
        "takes": rows,
        "aggregate": {
            "count": len(rows),
            "minimum": min(similarities),
            # A true median: the mean of the two middle scores for an even count.
            "median": round(statistics.median(similarities), 4),
            "maximum": max(similarities),
            "weakCount": sum(1 for row in rows if row["band"] == "weak"),
        },
    }


def area_under_curve(positives: list[float], negatives: list[float]) -> float:
    """P(a same-voice score beats a different-voice score); ties count half."""
    wins = sum(
        1.0 if positive > negative else 0.5 if positive == negative else 0.0
        for positive in positives for negative in negatives
    )
    return wins / (len(positives) * len(negatives))


def equal_error_rate(positives: list[float], negatives: list[float]) -> tuple[float, float]:
    """(EER, threshold): accept a score at or above the threshold; the threshold
    where the false-accept and false-reject rates meet (their mean at the
    closest observed crossing)."""
    best: tuple[float, float, float] | None = None
    for threshold in sorted(set(positives) | set(negatives)) + [math.inf]:
        false_accept = sum(value >= threshold for value in negatives) / len(negatives)
        false_reject = sum(value < threshold for value in positives) / len(positives)
        candidate = (abs(false_accept - false_reject), (false_accept + false_reject) / 2.0, threshold)
        if best is None or candidate[:2] < best[:2]:
            best = candidate
    assert best is not None
    return best[1], best[2]


def _percentile_interval(values: list[float]) -> list[float]:
    ordered = sorted(values)
    low = ordered[int(0.025 * (len(ordered) - 1))]
    high = ordered[int(math.ceil(0.975 * (len(ordered) - 1)))]
    return [round(low, 4), round(high, 4)]


def separation(
    positives: list[float], negatives: list[float], *,
    resamples: int = SEPARATION_BOOTSTRAP_RESAMPLES, seed: int = SEPARATION_BOOTSTRAP_SEED,
) -> dict[str, Any] | None:
    """Same-voice versus different-voice separation with 95% intervals.

    Positives (clone takes) and negatives (controls) are resampled separately
    with a fixed seed, so an interval is reproducible. The bands stay advisory:
    ``bandCalibrationReady`` says only whether enough negatives exist to fit them.
    """
    if not positives or not negatives:
        return None
    generator = random.Random(seed)
    aucs: list[float] = []
    eers: list[float] = []
    for _ in range(resamples):
        sample_positive = [generator.choice(positives) for _ in positives]
        sample_negative = [generator.choice(negatives) for _ in negatives]
        aucs.append(area_under_curve(sample_positive, sample_negative))
        eers.append(equal_error_rate(sample_positive, sample_negative)[0])
    eer, threshold = equal_error_rate(positives, negatives)
    return {
        "positives": len(positives),
        "negatives": len(negatives),
        "auc": round(area_under_curve(positives, negatives), 4),
        "aucInterval95": _percentile_interval(aucs),
        "equalErrorRate": round(eer, 4),
        "equalErrorRateThreshold": None if math.isinf(threshold) else round(threshold, 4),
        "equalErrorRateInterval95": _percentile_interval(eers),
        "bootstrap": {"method": "stratified-percentile", "resamples": resamples, "seed": seed},
        "minimumCalibrationNegatives": MINIMUM_CALIBRATION_NEGATIVES,
        "bandCalibrationReady": len(negatives) >= MINIMUM_CALIBRATION_NEGATIVES,
    }


def resample_for_embedding(pcm: Any, sample_rate: int) -> Any:
    """Mono float PCM at ``sample_rate`` to 16 kHz through the pinned resampler."""
    import numpy as np  # noqa: PLC0415

    from audio_resampling import INPUT_BLOCK_FRAMES, RESAMPLER_VERSION, RationalFIR  # noqa: PLC0415

    if RESAMPLER_VERSION != EMBEDDING_RESAMPLER:
        raise ValueError("the pinned embedding resampler changed; bump the ECAPA preprocessing identity")
    samples = np.asarray(pcm, dtype=np.float64)
    if sample_rate == EMBEDDING_SAMPLE_RATE or samples.size == 0:
        return samples.astype(np.float32)
    resampler = RationalFIR(int(sample_rate))
    blocks = (samples[start:start + INPUT_BLOCK_FRAMES] for start in range(0, samples.size, INPUT_BLOCK_FRAMES))
    return np.concatenate(list(resampler.blocks(blocks, int(samples.size)))).astype(np.float32)


def pinned_ecapa_snapshot(snapshot_download: Callable[..., str]) -> str:
    """The local path of the pinned ECAPA snapshot; never a network fetch."""
    try:
        return snapshot_download(
            repo_id=ECAPA_SOURCE, revision=ECAPA_REVISION, local_files_only=True,
        )
    except Exception as error:  # noqa: BLE001 - any cache miss is the same refusal
        raise RuntimeError(
            f"the pinned ECAPA snapshot {ECAPA_SOURCE}@{ECAPA_REVISION[:12]} is not in the local "
            "Hugging Face cache; nothing is downloaded here (maintainer: "
            f"hf download {ECAPA_SOURCE} --revision {ECAPA_REVISION})"
        ) from error


def verify_ecapa_snapshot(local_source: str) -> dict[str, str]:
    """Verify the cached snapshot against the judge registry before it loads (audit AQ-F04).

    The registry must still let the judge run and name the same repository and
    revision; every snapshot file must match its content address and any
    per-file pin. Returns each file's SHA-256.
    """
    from audio_qc_judges import JudgeRegistryError, verify_judge_snapshot

    try:
        return verify_judge_snapshot(
            ECAPA_JUDGE_ID, Path(local_source), repository=ECAPA_SOURCE, revision=ECAPA_REVISION,
        )
    except JudgeRegistryError as error:
        raise RuntimeError(f"the pinned ECAPA snapshot failed verification: {error}") from error


def ecapa_embedder() -> Callable[[str], list[float]]:
    """Load the pinned ECAPA backend. Operator-local heavy dependency.

    The exact revision is loaded from the local Hugging Face cache only
    (``local_files_only``), so the pin holds regardless of whether the installed
    speechbrain still forwards a ``revision`` argument (1.x dropped it), and a run
    never fetches a model (audit #103). The maintainer caches the snapshot once.
    Its bytes are verified against the judge registry before every load.
    """
    import wave  # noqa: PLC0415

    import numpy as np  # noqa: PLC0415
    import torch  # noqa: PLC0415
    from huggingface_hub import snapshot_download  # noqa: PLC0415
    from speechbrain.inference.speaker import EncoderClassifier  # noqa: PLC0415

    local_source = pinned_ecapa_snapshot(snapshot_download)
    verify_ecapa_snapshot(local_source)
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
        pcm = resample_for_embedding(pcm, sample_rate)
        waveform = torch.from_numpy(np.ascontiguousarray(pcm)).unsqueeze(0)
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
