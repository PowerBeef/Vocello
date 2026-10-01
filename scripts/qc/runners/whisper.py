"""Whisper large-v3 on MLX (mlx-whisper): the second ASR family.

Language detection is on: the language comes from Whisper's own detector on the first 30 s, and
`languageProbs` is that detector's distribution (the ten repository languages, plus any other
language at 1% or more). Decoding is greedy (temperature 0, no fallback), with word timestamps,
no initial prompt and no conditioning on previous text, so the script never steers it. Takes
longer than 10 s also get `languageWindows`: the detector on full 10 s windows.

Runtime `mlx`: mlx-whisper loads `config.json` and `weights.npz` (or `weights.safetensors`) from
the local model directory; its tokenizer and mel filters ship inside the package. Word timestamps
use mlx-whisper's default alignment heads (no per-model head table). Options: `fp16` (true),
`windowSeconds` (10).
"""

from __future__ import annotations

import sys
from typing import Any, Mapping

import numpy as np

from qc.runners import speech_common as common

PROBABILITY_FLOOR = 0.01


def named_language_probs(probs: Mapping[str, float], names: Mapping[str, str]) -> dict[str, float]:
    """Whisper's code → probability map as repository language names (others above the floor)."""

    named = {}
    for code, probability in probs.items():
        name = names.get(code, code)
        if name in common.LANGUAGES or probability >= PROBABILITY_FLOOR:
            named[name] = round(float(probability), 6)
    return dict(sorted(named.items(), key=lambda item: -item[1]))


def whisper_words(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    words = []
    for segment in result.get("segments") or []:
        for word in segment.get("words") or []:
            text = str(word.get("word", "")).strip()
            if not text:
                continue
            probability = word.get("probability")
            words.append({"text": text, "start": round(float(word["start"]), 3), "end": round(float(word["end"]), 3),
                          "prob": None if probability is None else round(float(probability), 4)})
    return words


class WhisperEngine:
    """One loaded Whisper model, shared by detection and mlx-whisper's `transcribe`."""

    def __init__(self, model_dir: str, options: Mapping[str, Any]) -> None:
        import mlx.core as mx
        import mlx_whisper
        from mlx_whisper.audio import N_SAMPLES, log_mel_spectrogram, pad_or_trim
        from mlx_whisper.tokenizer import LANGUAGES
        from mlx_whisper.transcribe import ModelHolder

        self.mx, self.whisper = mx, mlx_whisper
        self.path = str(model_dir)
        self.fp16 = options.get("fp16", True) is not False
        self.dtype = mx.float16 if self.fp16 else mx.float32
        # transcribe() fetches the same (path, dtype) from ModelHolder, so this is the only load.
        self.model = ModelHolder.get_model(self.path, self.dtype)
        self.names = dict(LANGUAGES)
        self._mel = lambda audio: log_mel_spectrogram(
            pad_or_trim(mx.array(audio), N_SAMPLES), n_mels=self.model.dims.n_mels).astype(self.dtype)

    def detect(self, audio: np.ndarray) -> dict[str, float]:
        """Whisper's language distribution over the first 30 s, keyed by language code."""

        _, probs = self.model.detect_language(self._mel(np.asarray(audio, dtype=np.float32)))
        return {str(code): float(value) for code, value in probs.items()}

    def transcribe(self, audio: np.ndarray, language: str) -> dict[str, Any]:
        result = self.whisper.transcribe(
            np.asarray(audio, dtype=np.float32), path_or_hf_repo=self.path, language=language,
            temperature=0.0, condition_on_previous_text=False, word_timestamps=True, initial_prompt=None,
            fp16=self.fp16, verbose=None)
        self.mx.clear_cache()
        return result


def build_engine(job: Mapping[str, Any]) -> WhisperEngine:
    return WhisperEngine(job["modelDir"], job.get("options") or {})


def process(engine: Any, context: common.TakeContext, options: Mapping[str, Any]) -> tuple[dict[str, Any], None]:
    if context.audio is None or context.audio.size < common.SAMPLE_RATE // 10:
        raise common.TakeError("audio-too-short")
    probs = engine.detect(context.audio)
    code = max(probs, key=probs.get)
    # Passing the detected code is what transcribe(language=None) does internally (same first
    # 30 s, same detector); doing it here keeps the distribution it chose from.
    result = engine.transcribe(context.audio, code)
    windows = []
    for start, end in common.language_windows(context.duration, float(options.get("windowSeconds", 10.0))):
        window = engine.detect(common.window_audio(context.audio, start, end))
        best = max(window, key=window.get)
        windows.append({"start": start, "end": end, "language": engine.names.get(best, best),
                        "languageProbs": named_language_probs(window, engine.names)})
    outputs = {"text": str(result.get("text", "")).strip(), "language": engine.names.get(code, code),
               "languageProbs": named_language_probs(probs, engine.names), "words": whisper_words(result),
               "languageWindows": windows or None}
    return outputs, None


if __name__ == "__main__":
    sys.exit(common.main(sys.argv[1:], build_engine=build_engine, process=process))
