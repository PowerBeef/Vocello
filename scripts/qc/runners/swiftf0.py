"""SwiftF0 pitch on onnxruntime (CPU): `<onnx python> -m qc.runners.swiftf0 --job <job.json>`.

SwiftF0 (`lars76/swift-f0`, MIT; PyPI `swift-f0` 0.3 with its `model.onnx` bundled) makes the fewest
octave errors of the trackers benchmarked with RMVPE. The 0.3 API is `SwiftF0(threads=...).detect(audio,
sample_rate, fmin, fmax)`; it works at 16 kHz with a 256-sample hop, frame `k` centered on sample
`k * 256` (16 ms), and a frame is voiced when its confidence is at least 0.5. The runner resamples to
16 kHz itself (the package needs the LGPL `soxr` extra otherwise), asks for the full supported range
46.875-2093.75 Hz, and reports `confidence` with unvoiced frames as null. A `model.onnx` fetched
into the model directory (hash-verified by `qc.py models verify`) replaces the bundled copy.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from qc.runners import _kit

SAMPLE_RATE = 16_000
HOP_SECONDS = 256 / SAMPLE_RATE
FMIN_HZ = 46.875
FMAX_HZ = 2093.75
VOICED_CONFIDENCE = 0.5
MODEL_FILE = "model.onnx"


def pitch_outputs(timestamps: np.ndarray, pitch_hz: np.ndarray, confidence: np.ndarray) -> dict[str, Any]:
    """Place SwiftF0's frames on the schema grid (`i * hopSeconds`) and null the unvoiced ones."""
    times = np.asarray(timestamps, dtype=np.float64)
    pitch = np.asarray(pitch_hz, dtype=np.float64)
    conf = np.asarray(confidence, dtype=np.float64)
    index = np.rint(times / HOP_SECONDS).astype(int) if times.size else np.zeros(0, dtype=int)
    frames = int(index.max()) + 1 if index.size else 0
    f0: list[float | None] = [None] * frames
    confidences: list[float] = [0.0] * frames
    for i, hz, c in zip(index, pitch, conf):
        if i < 0:
            continue
        c = float(c) if np.isfinite(c) else 0.0
        confidences[i] = round(c, 4)
        voiced = c >= VOICED_CONFIDENCE and np.isfinite(hz) and FMIN_HZ <= hz <= FMAX_HZ
        f0[i] = round(float(hz), 2) if voiced else None
    return {
        "hopSeconds": HOP_SECONDS,
        "f0Hz": f0,
        "confidence": confidences,
        "threshold": VOICED_CONFIDENCE,
        "fminHz": FMIN_HZ,
        "fmaxHz": FMAX_HZ,
    }


def load(job: Mapping[str, Any]) -> Any:
    from swift_f0 import SwiftF0  # type: ignore

    options = job.get("options") or {}
    threads = options.get("threads")
    detector = SwiftF0(threads=int(threads) if threads else None)
    fetched = Path(job["modelDir"]) / options.get("modelFile", MODEL_FILE)
    if fetched.is_file():
        import onnxruntime  # type: ignore

        session_options = onnxruntime.SessionOptions()
        if threads:
            session_options.intra_op_num_threads = int(threads)
        detector.session = onnxruntime.InferenceSession(str(fetched), session_options, providers=["CPUExecutionProvider"])
    return detector


def process(detector: Any, take: Mapping[str, Any], job: Mapping[str, Any]) -> tuple[dict[str, Any], float, None]:
    audio, _, duration = _kit.load_take_audio(take, SAMPLE_RATE)
    result = detector.detect(audio, SAMPLE_RATE, fmin=FMIN_HZ, fmax=FMAX_HZ)
    return pitch_outputs(result.timestamps, result.pitch_hz, result.confidence), duration, None


if __name__ == "__main__":
    sys.exit(_kit.main(load, process))
