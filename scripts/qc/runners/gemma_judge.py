"""Gemma 4 12B-it as an audio QC judge through llama.cpp: `<onnx python> -m qc.runners.gemma_judge --job <job.json>`.

Weights: `google/gemma-4-12B-it-qat-q4_0-gguf` (Apache-2.0), the QAT Q4_0 model and its BF16 projector,
which carries the audio path of the encoder-free "unified" 12B (`gemma4ua`). Runtime: the pinned
llama.cpp release (b11146, v0.5.0) unpacked under `build/cache/qc/runtimes/llamacpp/`; the 12B's
audio needs b9512 or later. Audio is at most 30 s per request and thinking stays off (llama.cpp
issue #24138: loops on longer clips or with thinking on). The flow is `qc.runners._llama`.

Options (job `options`): `llamacppDir` (set by the host; `llama-server` is found below it) or
`server` (its path), `serverURL` (attach to a running server), `modelFile`, `mmprojFile`, `context`,
`gpuLayers`, `threads`, `serverArgs`, `serverLog`, `seed`, `topLogprobs`, `chunkSeconds` (at most 30),
`startupTimeout`, `requestTimeout`.
"""
from __future__ import annotations

import sys

from qc.runners import _llama

PROFILE = _llama.Profile(
    name="gemma-4-12b-it-qat-q4_0",
    model_file="gemma-4-12b-it-qat-q4_0.gguf",
    mmproj_file="mmproj-gemma-4-12b-it-qat-q4_0.gguf",
    context=8192,
)

if __name__ == "__main__":
    sys.exit(_llama.run(PROFILE))
