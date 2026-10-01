"""Qwen2.5-Omni-7B as the fallback audio QC judge through llama.cpp: `<onnx python> -m qc.runners.qwen_omni_judge --job <job.json>`.

Used when Gemma 4 fails. Weights: `ggml-org/Qwen2.5-Omni-7B-GGUF` (Apache-2.0 upstream; the GGUF card's
`qwen-research` label belongs to the 3B), the Q4_K_M model with the f16 projector, which holds the
Whisper-style audio encoder (llama.cpp since b5508). Same server flow, requests and output schema as
the Gemma judge (`qc.runners._llama`), with the same 30 s chunks.
"""
from __future__ import annotations

import sys

from qc.runners import _llama

PROFILE = _llama.Profile(
    name="qwen2.5-omni-7b-q4_k_m",
    model_file="Qwen2.5-Omni-7B-Q4_K_M.gguf",
    mmproj_file="mmproj-Qwen2.5-Omni-7B-f16.gguf",
    context=8192,
)

if __name__ == "__main__":
    sys.exit(_llama.run(PROFILE))
