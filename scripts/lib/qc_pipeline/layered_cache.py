"""The L0-L2 analysis cache of the staged pipeline (audit section 3.5).

| Layer | Key | Content |
|---|---|---|
| L0 canonical | original WAV SHA-256 + resampler identity | canonical 16 kHz mono PCM16 |
| L1 raw | L0 + judge **output** identity + request | a judge's raw output (private text included) |
| L2 metrics | L1 + metric-definition version + metric source + scoring inputs | measurements only |
| L3 verdict | never cached | recomputed from L2, the rule and the calibration record |

It layers on `DeliveryAnalysisCache`, whose entries are atomic, digest-bound and
fail closed, under the owned `build/cache/delivery-analysis` root. L0 is that
cache's canonicalization (`polyphase-kaiser5-v2`, its resampler source digests
bound). An L1 key binds the judge's output identity (AQ-01: model, weights,
runtime, worker source, command template, decode options, the host until
cross-host determinism is measured, and the judge's declared thread count) and
the request (for a recognizer, its locked language), never the envelope: a
supervisor fix reuses every entry. An L2 key binds the L1 key, the metric
definition's version and the source of the module that computes it, and what
the metric reads besides the raw output (the reference text digest and the
expected language), so a normalization change recomputes L2 without launching
a model. Verdict fields and thresholds never enter L2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
from typing import Any, Callable, Mapping

from delivery_analysis_cache import (
    LEGACY_RESAMPLER_VERSION,
    NO_MODEL_DIGEST,
    CanonicalAudio,
    DeliveryAnalysisCache,
    LayerIdentity,
    digest,
)

L1_LAYER = "audio-qc-l1-raw"
L2_LAYER = "audio-qc-l2-metrics"
L1_LAYER_VERSION = "1"


def _sha256(value: Any) -> str:
    if isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value):
        return value
    raise ValueError("expected a lowercase SHA-256 digest")


def output_identity_digest(judge_id: str, components: Mapping[str, Any]) -> str:
    """One judge's output identity as a digest: what can change its output, nothing else."""
    if "threads" not in components:
        raise ValueError("a judge's output identity records its declared thread count")
    return digest({"judge": judge_id, "outputIdentity": dict(components)})


@dataclass(frozen=True)
class JudgeIdentity:
    """What keys one judge's L1 entries."""

    judge_id: str
    output_identity: str
    model_id: str = "none"
    model_revision: str = "not-applicable"
    weights_sha256: str = NO_MODEL_DIGEST

    def __post_init__(self) -> None:
        _sha256(self.output_identity)
        _sha256(self.weights_sha256)


def l1_identity(canonical: CanonicalAudio, judge: JudgeIdentity, request: Mapping[str, Any]) -> LayerIdentity:
    return LayerIdentity(
        original_wav_sha256=canonical.original_wav_sha256,
        canonical_derivative_sha256=canonical.canonical_derivative_sha256,
        layer_id=f"{L1_LAYER}:{judge.judge_id}",
        layer_version=L1_LAYER_VERSION,
        binary_sha256=judge.output_identity,
        model_id=judge.model_id,
        model_revision=judge.model_revision,
        weights_sha256=judge.weights_sha256,
        preprocessing_config_digest=digest({"request": dict(request)}),
    )


def l2_identity(l1: LayerIdentity, *, metric_definition: str, metric_source_sha256: str,
                inputs: Mapping[str, Any]) -> LayerIdentity:
    judge_id = l1.layer_id.split(":", 1)[1]
    return LayerIdentity(
        original_wav_sha256=l1.original_wav_sha256,
        canonical_derivative_sha256=l1.canonical_derivative_sha256,
        layer_id=f"{L2_LAYER}:{judge_id}",
        layer_version=metric_definition,
        binary_sha256=_sha256(metric_source_sha256),
        model_id=l1.model_id,
        model_revision=l1.model_revision,
        weights_sha256=l1.weights_sha256,
        preprocessing_config_digest=digest({"l1Key": l1.key, "inputs": dict(inputs)}),
    )


def file_digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


@dataclass
class LayerCounters:
    hits: int = 0
    misses: int = 0

    def report(self) -> dict[str, int]:
        return {"hits": self.hits, "misses": self.misses}


@dataclass
class LayeredCache:
    """L0-L2 over one `DeliveryAnalysisCache`, with hit and miss counts per layer."""

    cache: DeliveryAnalysisCache
    counters: dict[str, LayerCounters] = field(
        default_factory=lambda: {"L0": LayerCounters(), "L1": LayerCounters(), "L2": LayerCounters()}
    )

    @property
    def resampler_version(self) -> str:
        return self.cache.resampler_version

    def canonical(self, wav: Path) -> CanonicalAudio:
        """L0: the canonical derivative (created on a miss, verified on a hit)."""
        original = file_digest(wav) if wav.is_file() else ""
        audio_dir = self.cache.root / "audio"
        if self.cache.resampler_version != LEGACY_RESAMPLER_VERSION:
            audio_dir = audio_dir / self.cache.resampler_version
        existed = bool(original) and (audio_dir / original[:2] / f"{original}.json").exists()
        canonical = self.cache.canonicalize(wav)
        self.counters["L0"].hits += existed
        self.counters["L0"].misses += not existed
        return canonical

    def load_l1(self, identity: LayerIdentity) -> dict[str, Any] | None:
        value = self.cache.load(identity)
        self.counters["L1"].hits += value is not None
        self.counters["L1"].misses += value is None
        return value

    def store_l1(self, identity: LayerIdentity, payload: dict[str, Any]) -> dict[str, Any]:
        return self.cache.store(identity, payload)

    def l1_or_compute(self, identity: LayerIdentity, compute: Callable[[], dict[str, Any]]) -> tuple[dict[str, Any], bool]:
        value, hit = self.cache.get_or_compute(identity, compute)
        self.counters["L1"].hits += hit
        self.counters["L1"].misses += not hit
        return value, hit

    def l2_or_compute(self, identity: LayerIdentity, compute: Callable[[], dict[str, Any]]) -> tuple[dict[str, Any], bool]:
        value, hit = self.cache.get_or_compute(identity, compute)
        self.counters["L2"].hits += hit
        self.counters["L2"].misses += not hit
        return value, hit

    def report(self) -> dict[str, Any]:
        return {layer: counter.report() for layer, counter in self.counters.items()}
