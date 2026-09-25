#!/usr/bin/env python3
"""The whisper-small MLX recognizer child (the only place MLX loads).

`independent_asr.py transcribe` runs this file in one supervised subprocess
after the generator has exited, and the `whisper-small-mlx` compact adapter runs
it for one file. Its SHA-256 is the recognizer's source identity in cache keys
and provenance (audit #89), so a change to the manifest builders or the
publisher-facing producer never invalidates cached recognitions; only a change
here does.

What a row reports is measured, not copied from its inputs (audit #89):

- ``decodedSampleCount`` is the length of the PCM the recognizer actually read
  (16 kHz), so the producer's processed duration can disagree with the WAV.
- The model loads once, and a warm-up on one second of silence runs every path
  a timed row uses (a language detection, then one full transcription with the
  job's decode options and a locked language, which pays for the decode loop
  and the tokenizer) before any row is timed; ``wallSeconds`` is per-row
  recognition only and ``modelLoadSeconds`` and ``warmupSeconds`` are reported
  once for the job.
- Every segment keeps whisper's no-speech probability and average log
  probability.

Standard library, NumPy and the pinned ``mlx`` / ``mlx-whisper`` only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from typing import Any
import wave


SCHEMA_VERSION = 1
SAMPLE_RATE_HZ = 16_000


class WorkerError(ValueError):
    """The job or its audio is unusable."""


def read_pcm16(path: Path) -> Any:
    import numpy as np
    data = np.frombuffer(path.read_bytes(), dtype="<i2")
    return data.astype(np.float32) / 32768.0


def read_wav16k(path: Path) -> Any:
    import numpy as np
    with wave.open(str(path), "rb") as stream:
        if stream.getframerate() != SAMPLE_RATE_HZ or stream.getnchannels() != 1 or stream.getsampwidth() != 2:
            raise WorkerError("worker single-file input must be 16 kHz mono PCM16")
        frames = stream.readframes(stream.getnframes())
    return np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0


class Recognizer:
    """One loaded, warmed whisper model; rows are timed only after warm-up."""

    def __init__(self, model_dir: Path, decode: dict[str, Any], *,
                 warmup_language: str | None = None) -> None:
        import mlx.core as mx
        import mlx_whisper
        from mlx_whisper.audio import N_SAMPLES, log_mel_spectrogram, pad_or_trim
        from mlx_whisper.transcribe import ModelHolder

        self.model_dir = model_dir
        self.decode = decode
        self.fp16 = decode.get("fp16", True) is not False
        self.dtype = mx.float16 if self.fp16 else mx.float32
        started = time.monotonic()
        # mlx_whisper.transcribe fetches the same (path, dtype) from ModelHolder,
        # so this is the only load.
        self.model = ModelHolder.get_model(str(model_dir), self.dtype)
        self.model_load_seconds = time.monotonic() - started
        self._mx = mx
        self._segment = lambda audio: log_mel_spectrogram(
            pad_or_trim(mx.array(audio), N_SAMPLES), n_mels=self.model.dims.n_mels,
        ).astype(self.dtype)
        started = time.monotonic()
        # Warm on silence exactly what a timed row runs: the encoder and one
        # decoder step (language detection), then a full transcription with the
        # same options and a locked language (the KV-cache decode loop and the
        # tokenizer), so the first timed row pays for no first use.
        import numpy as np
        silence = np.zeros(SAMPLE_RATE_HZ, dtype=np.float32)
        self.model.detect_language(self._segment(silence))
        mlx_whisper.transcribe(silence, **self._options(warmup_language or "en"))
        self.warmup_seconds = time.monotonic() - started

    def _options(self, language: str | None) -> dict[str, Any]:
        options: dict[str, Any] = {
            "path_or_hf_repo": str(self.model_dir),
            "temperature": float(self.decode.get("temperature", 0.0)),
            "condition_on_previous_text": bool(self.decode.get("conditionOnPreviousText", False)),
            "fp16": self.fp16,
            "word_timestamps": bool(self.decode.get("wordTimestamps", False)),
            "verbose": None,
        }
        if language is not None:
            options["language"] = language
        return options

    def recognize(self, audio: Any, language: str | None) -> dict[str, Any]:
        import mlx_whisper

        started = time.monotonic()
        # Language identification reads the first 30 s exactly as upstream
        # Whisper does: pad or trim the *audio* to 30 s, then its log-mel.
        _tokens, probabilities = self.model.detect_language(self._segment(audio))
        detected = max(probabilities, key=probabilities.get)
        result = mlx_whisper.transcribe(audio, **self._options(language))
        segments = [
            {
                "start": float(item.get("start", 0.0)),
                "end": float(item.get("end", 0.0)),
                "noSpeechProb": float(item.get("no_speech_prob", 0.0)),
                "avgLogprob": float(item.get("avg_logprob", 0.0)),
            }
            for item in result.get("segments", [])
        ]
        return {
            "transcript": str(result.get("text", "")).strip(),
            "language": result.get("language"),
            "detectedLanguage": detected,
            "detectedLanguageProbability": float(probabilities[detected]),
            "expectedLanguageProbability": (
                float(probabilities.get(language, 0.0)) if language else float(probabilities[detected])
            ),
            "segments": segments,
            "decodedSampleCount": int(len(audio)),
            "sampleRateHz": SAMPLE_RATE_HZ,
            "wallSeconds": time.monotonic() - started,
        }


def run_job(job: dict[str, Any]) -> dict[str, Any]:
    rows = job.get("rows")
    if not isinstance(rows, list) or not rows:
        raise WorkerError("worker job has no rows")
    recognizer = Recognizer(
        Path(str(job["weights"])).parent, job.get("decodeOptions") or {},
        warmup_language=rows[0].get("language"),
    )
    output = []
    for row in rows:
        audio = read_pcm16(Path(str(row["pcmPath"])))
        output.append({"id": row["id"], **recognizer.recognize(audio, row.get("language"))})
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "independent-asr-worker-output",
        "modelLoadSeconds": recognizer.model_load_seconds,
        "warmupSeconds": recognizer.warmup_seconds,
        "rows": output,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--job", type=Path)
    parser.add_argument("--weights", type=Path)
    parser.add_argument("--audio", type=Path)
    parser.add_argument("--language")
    args = parser.parse_args(argv)
    try:
        if args.job is not None:
            job = json.loads(args.job.read_text(encoding="utf-8"))
            if not isinstance(job, dict):
                raise WorkerError("worker job must be an object")
            payload = run_job(job)
        else:
            if args.weights is None or args.audio is None:
                raise WorkerError("worker needs --job or --weights with --audio")
            recognizer = Recognizer(Path(args.weights).parent, {}, warmup_language=args.language)
            payload = {
                **recognizer.recognize(read_wav16k(args.audio), args.language),
                "modelLoadSeconds": recognizer.model_load_seconds,
                "warmupSeconds": recognizer.warmup_seconds,
            }
    except (WorkerError, OSError, ValueError, KeyError) as error:
        print(f"independent-asr-worker: FAIL\n{type(error).__name__}: {error}", file=sys.stderr)
        return 1
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.write("\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
