"""Canonical PCM, digests and seeded randomness for the qualification engine.

Digests are taken over PCM16, the format every published take has, so a
last-place floating-point difference between hosts (libm, SIMD paths) cannot
change a golden. Quantization rounds half away from zero, as Swift's
`rounded()` does when the engine writes its WAV.

Randomness comes from `PCG64.random_raw()` words, whose stream NumPy keeps
stable across releases; `Generator` distribution methods may change and are
never used. Every draw is keyed by a seed and a label path, so adding a draw in
one place never shifts another.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

import numpy as np

ENGINE_SAMPLE_RATE = 24_000
PCM16_FULL_SCALE = 32767.0
PCM_DIGEST_SCHEMA = b"vocello.qc.pcm16le/1\n"
RNG_SCHEMA = "vocello.qc.rng/1"


def as_samples(values: Any) -> np.ndarray:
    """A contiguous one-dimensional float64 copy."""
    samples = np.array(values, dtype=np.float64, copy=True)
    if samples.ndim != 1:
        raise ValueError("PCM must be one-dimensional (mono)")
    return np.ascontiguousarray(samples)


def to_pcm16(samples: np.ndarray) -> np.ndarray:
    """Little-endian PCM16; non-finite samples become 0 (the digest records them)."""
    finite = np.where(np.isfinite(samples), samples, 0.0)
    scaled = finite * PCM16_FULL_SCALE
    rounded = np.sign(scaled) * np.floor(np.abs(scaled) + 0.5)
    return np.clip(rounded, -32768.0, 32767.0).astype("<i2")


def pcm_digest(samples: np.ndarray) -> str:
    """SHA-256 over the canonical PCM16 bytes, the length and any non-finite indices."""
    values = np.asarray(samples, dtype=np.float64)
    digest = hashlib.sha256(PCM_DIGEST_SCHEMA)
    digest.update(int(values.size).to_bytes(8, "little"))
    digest.update(to_pcm16(values).tobytes())
    bad = np.flatnonzero(~np.isfinite(values))
    if bad.size:
        digest.update(b"nonfinite")
        digest.update(bad.astype("<i8").tobytes())
    return digest.hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("utf-8")


def json_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


class SeededStream:
    """Deterministic draws for one (seed, label path)."""

    def __init__(self, seed: int, *labels: str) -> None:
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise ValueError("seed must be a non-negative integer")
        key = hashlib.sha256("|".join((RNG_SCHEMA, str(seed), *labels)).encode("utf-8")).digest()
        self._bits = np.random.PCG64(int.from_bytes(key[:16], "little"))

    def uniform(self, count: int) -> np.ndarray:
        """Uniform draws in [0, 1) from the top 53 bits of each raw word (exact)."""
        raw = self._bits.random_raw(int(count))
        return (np.asarray(raw, dtype=np.uint64) >> np.uint64(11)).astype(np.float64) * (2.0 ** -53)

    def uniform_one(self, low: float = 0.0, high: float = 1.0) -> float:
        return float(low + (high - low) * self.uniform(1)[0])

    def integers(self, high: int, count: int) -> np.ndarray:
        """Integers in [0, high)."""
        if high <= 0:
            raise ValueError("high must be positive")
        return np.minimum(np.floor(self.uniform(count) * high).astype(np.int64), high - 1)

    def integer(self, high: int) -> int:
        return int(self.integers(high, 1)[0])

    def normal(self, count: int) -> np.ndarray:
        """Standard normal draws by Box-Muller over two uniform streams."""
        count = int(count)
        first = self.uniform(count)
        second = self.uniform(count)
        radius = np.sqrt(-2.0 * np.log1p(-first))
        return radius * np.cos(2.0 * math.pi * second)
