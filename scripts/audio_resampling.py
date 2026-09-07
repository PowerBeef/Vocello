#!/usr/bin/env python3
"""Bounded rational FIR resampling for operator-side audio analysis, never TTS.

v2 matches the mathematical Kaiser-5, 10-zero-crossing, zero-padded,
delay-compensated polyphase reference (SciPy resample_poly). Input and output
are Float64 PCM units. Quantization belongs to the cache's publication boundary.
No SciPy or external model is required. Working storage is independent of duration.
"""
from __future__ import annotations

from collections import OrderedDict
import math
from typing import Iterable, Iterator

import numpy as np

RESAMPLER_VERSION = "polyphase-kaiser5-v2"
OUTPUT_RATE = 16_000
INPUT_BLOCK_FRAMES = 16_384
OUTPUT_BLOCK_FRAMES = 1_024
MAX_PHASE_CACHE = 256


class RationalFIR:
    """Finite, zero-phase FIR with integer phase accounting across input blocks."""

    def __init__(self, source_rate: int) -> None:
        if type(source_rate) is not int or not 8_000 <= source_rate <= 192_000:
            raise ValueError("v2 resampling requires an integer rate in 8000...192000 Hz")
        divisor = math.gcd(source_rate, OUTPUT_RATE)
        self.up, self.down = OUTPUT_RATE // divisor, source_rate // divisor
        self.scale = max(self.up, self.down)
        self.half = 10 * self.scale
        self.taps = (2 * self.half + self.up - 1) // self.up + 1
        self.phases: OrderedDict[int, np.ndarray] = OrderedDict()
        # Sum the prototype in bounded chunks, including uncommon coprime rates.
        self.normalization = math.fsum(
            float(np.sum(self._prototype(np.arange(start, min(start + INPUT_BLOCK_FRAMES,
                                                            2 * self.half + 1)))))
            for start in range(0, 2 * self.half + 1, INPUT_BLOCK_FRAMES)
        )

    def _prototype(self, indices: np.ndarray) -> np.ndarray:
        centered = indices.astype(np.float64) - self.half
        window = np.i0(5.0 * np.sqrt(np.maximum(0.0, 1.0 - (centered / self.half) ** 2))) / np.i0(5.0)
        return np.sinc(centered / self.scale) / self.scale * window

    def _phase(self, phase: int) -> np.ndarray:
        if phase in self.phases:
            self.phases.move_to_end(phase)
            return self.phases[phase]
        indices = phase + self.up * np.arange(self.taps)
        coefficients = self._prototype(indices) * self.up / self.normalization
        coefficients[indices > 2 * self.half] = 0.0
        self.phases[phase] = coefficients
        if len(self.phases) > MAX_PHASE_CACHE:
            self.phases.popitem(last=False)
        return coefficients

    def blocks(self, source: Iterable[np.ndarray], frame_count: int) -> Iterator[np.ndarray]:
        if type(frame_count) is not int or frame_count <= 0:
            raise ValueError("v2 resampling requires a positive frame count")
        buffer = np.empty(0, dtype=np.float64)
        start = observed = emitted = 0
        total_output = (frame_count * self.up + self.down - 1) // self.down

        def emit(limit: int) -> Iterator[np.ndarray]:
            nonlocal emitted, start, buffer
            while emitted < limit:
                end = min(limit, emitted + OUTPUT_BLOCK_FRAMES)
                times = np.arange(emitted, end, dtype=np.int64) * self.down + self.half
                indices = times[:, None] // self.up - np.arange(self.taps)
                phases = times % self.up
                weights = np.empty(indices.shape, dtype=np.float64)
                for phase in np.unique(phases):
                    weights[phases == phase] = self._phase(int(phase))
                local = indices - start
                valid = (indices >= 0) & (indices < observed)
                if np.any(valid & ((local < 0) | (local >= len(buffer)))):
                    raise ValueError("resampler overlap ownership lost")
                values = buffer[np.clip(local, 0, len(buffer) - 1)]
                values[~valid] = 0.0
                yield np.sum(values * weights, axis=1)
                emitted = end
            retain_from = max(start, (emitted * self.down + self.half) // self.up - self.taps + 1)
            drop = min(len(buffer), retain_from - start)
            buffer = buffer[drop:].copy()
            start += drop

        for block in source:
            if (not isinstance(block, np.ndarray) or block.ndim != 1
                    or len(block) > INPUT_BLOCK_FRAMES or not np.all(np.isfinite(block))):
                raise ValueError("invalid or unbounded resampler input block")
            if not len(block):
                continue
            observed += len(block)
            if observed > frame_count:
                raise ValueError("resampler received excess source frames")
            if self.up == self.down:
                yield block.astype(np.float64, copy=True)
                continue
            buffer = np.concatenate((buffer, block))
            # Output m is safe once floor((m*down+half)/up) < observed.
            available = max(0, (observed * self.up - self.half + self.down - 1) // self.down)
            yield from emit(min(total_output, available))
        if observed != frame_count:
            raise ValueError("resampler source frame count mismatch")
        if self.up != self.down:
            yield from emit(total_output)
