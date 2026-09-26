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
supervisor fix reuses every entry. An L1 payload is what the judge measured,
never how long it took (`wallSeconds` rides beside it as provenance). An L2
key binds the L1 key, the metric definition's version, the digest of every
source that shapes the L2 value (a declared list, `metric_sources_digest`),
and what the metric reads besides the raw output (the reference text digest
and the expected language), so a normalization change recomputes L2 without
launching a model. Verdict fields and thresholds never enter L2.

Several orchestrators share the cache. A run that finds an entry another run
stored first adopts it (`store_or_adopt`): the first stored value is the
entry, and a second run of a nondeterministic judge never fails its takes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import threading
from typing import Any, Callable, Mapping, Sequence

from delivery_analysis_cache import (
    LEGACY_RESAMPLER_VERSION,
    NO_MODEL_DIGEST,
    AnalysisCacheError,
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


def metric_sources_digest(sources: Sequence[Path]) -> str:
    """One digest over every source file that shapes an L2 value, in declared order."""
    if not sources:
        raise ValueError("an L2 metric declares the sources that shape it")
    return digest({"metricSources": [{"name": path.name, "sha256": file_digest(path)} for path in sources]})


def store_or_adopt(cache: DeliveryAnalysisCache, identity: LayerIdentity,
                   payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Store an entry, or adopt the one another run stored first under the same key.

    Returns the entry and whether it was adopted. Any other failure (an unsafe
    payload, a corrupt entry) still raises.
    """
    try:
        return cache.store(identity, payload), False
    except AnalysisCacheError:
        retained = cache.load(identity)
        if retained is None:
            raise
        return retained, True


@dataclass
class LayerCounters:
    hits: int = 0
    misses: int = 0
    adopted: int = 0

    def report(self) -> dict[str, int]:
        return {"hits": self.hits, "misses": self.misses, "adopted": self.adopted}


@dataclass
class LayeredCache:
    """L0-L2 over one `DeliveryAnalysisCache`, with hit and miss counts per layer."""

    cache: DeliveryAnalysisCache
    counters: dict[str, LayerCounters] = field(
        default_factory=lambda: {"L0": LayerCounters(), "L1": LayerCounters(), "L2": LayerCounters()}
    )
    # Workers of several judges re-check L1 from their own threads.
    _adopt_lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

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

    def store_l1(self, identity: LayerIdentity, payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Store a launched row's L1, adopting what another run stored first."""
        stored, adopted = store_or_adopt(self.cache, identity, payload)
        with self._adopt_lock:
            self.counters["L1"].adopted += adopted
        return stored, adopted

    def adopt_l1(self, identity: LayerIdentity) -> dict[str, Any] | None:
        """An entry another run stored after this one planned it (re-checked after admission)."""
        value = self.cache.load(identity)
        with self._adopt_lock:
            self.counters["L1"].adopted += value is not None
        return value

    def _or_compute(self, layer: str, identity: LayerIdentity,
                    compute: Callable[[], dict[str, Any]]) -> tuple[dict[str, Any], bool]:
        retained = self.cache.load(identity)
        if retained is not None:
            self.counters[layer].hits += 1
            return retained, True
        self.counters[layer].misses += 1
        value, adopted = store_or_adopt(self.cache, identity, compute())
        self.counters[layer].adopted += adopted
        return value, False

    def l1_or_compute(self, identity: LayerIdentity, compute: Callable[[], dict[str, Any]]) -> tuple[dict[str, Any], bool]:
        return self._or_compute("L1", identity, compute)

    def l2_or_compute(self, identity: LayerIdentity, compute: Callable[[], dict[str, Any]]) -> tuple[dict[str, Any], bool]:
        return self._or_compute("L2", identity, compute)

    def report(self) -> dict[str, Any]:
        return {layer: counter.report() for layer, counter in self.counters.items()}
