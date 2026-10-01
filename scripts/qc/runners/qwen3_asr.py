"""Qwen3-ASR 1.7B on MLX (mlx-audio): transcript, language and language probabilities.

The take is transcribed WITHOUT its script as context: no system prompt, no hotwords and no forced
language. Qwen3-ASR then writes `language <Name><asr_text><transcript>`, so the step that emits the
language name carries the language distribution. `languageProbs` is that step's posterior over
the first token of each supported language name, renormalized over those languages (a first
token shared by two names splits its mass evenly). Takes longer than 10 s also get
`languageWindows`: the same language ID on full 10 s windows, decoded only up to `<asr_text>`.

Runtime `mlx`: mlx-audio (`mlx_audio.stt.utils.load_model` on the local model directory, which
also loads the tokenizer and feature extractor through transformers). Options: `maxTokens` (a
fixed decode budget), `maxTokensPerSecond` (16), `windowSeconds` (10), `maxSeconds` (600).
"""

from __future__ import annotations

import re
import sys
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from qc.runners import speech_common as common

ASR_TEXT_TAG = "<asr_text>"
LANGUAGE_STEPS = 6
WINDOW_TOKENS = 8
_SPECIAL = re.compile(r"<\|[^|<>]*\|>")


def parse_asr_output(raw: str) -> tuple[str | None, str]:
    """`language French<asr_text>Bonjour.` → (`french`, `Bonjour.`); no language for `None`."""

    language = None
    text = raw
    if ASR_TEXT_TAG in raw:
        head, text = raw.split(ASR_TEXT_TAG, 1)
        head = _SPECIAL.sub("", head).strip()
        if head.lower().startswith("language"):
            head = head[len("language"):].strip()
        language = head.lower() or None
    if language in ("none", "unknown"):
        language = None
    return language, _SPECIAL.sub("", text).replace(ASR_TEXT_TAG, "").strip()


def first_token_candidates(names: Sequence[str], encode: Callable[[str], Sequence[int]]) -> dict[int, list[str]]:
    """First token id of ` <Name>` (how the name follows `language`) → the language names."""

    candidates: dict[int, list[str]] = {}
    for name in names:
        tokens = list(encode(" " + name))
        if tokens:
            candidates.setdefault(int(tokens[0]), []).append(name.lower())
    return candidates


def language_step(tokens: Sequence[int], decode: Callable[[int], str]) -> int | None:
    """The generation step that emits the language name: the prefix before it reads `language`."""

    for step in range(min(len(tokens), LANGUAGE_STEPS)):
        if decode(step).strip().lower() == "language":
            return step
    return None


def language_probs(row: np.ndarray, candidates: Mapping[int, Sequence[str]]) -> dict[str, float] | None:
    """Renormalized posterior over the candidate languages from one step's log-probabilities."""

    if not candidates:
        return None
    ids = list(candidates)
    scores = np.asarray(row, dtype=np.float64)[ids]
    if not np.isfinite(scores).any():
        return None
    weights = np.exp(scores - scores.max())
    weights /= weights.sum()
    probs: dict[str, float] = {}
    for token, weight in zip(ids, weights):
        names = candidates[token]
        for name in names:
            probs[name] = round(float(weight) / len(names), 6)
    return dict(sorted(probs.items(), key=lambda item: -item[1]))


def token_budget(duration: float | None, options: Mapping[str, Any]) -> int:
    if options.get("maxTokens"):
        return int(options["maxTokens"])
    return int(64 + float(options.get("maxTokensPerSecond", 16)) * float(duration or 0.0))


class Qwen3AsrEngine:
    """One loaded Qwen3-ASR model; greedy decoding through mlx-audio's `stream_generate`."""

    def __init__(self, model_dir: str, options: Mapping[str, Any]) -> None:
        import mlx.core as mx
        from mlx_audio.stt.utils import load_model

        self.mx = mx
        self.model = load_model(str(model_dir))
        self.tokenizer = self.model._tokenizer
        names = list(getattr(self.model.config, "support_languages", None) or [])
        self.candidates = first_token_candidates(names, self._encode)

    def _encode(self, text: str) -> list[int]:
        return list(self.tokenizer.encode(text, add_special_tokens=False))

    def _decode(self, tokens: Sequence[int]) -> str:
        return self.tokenizer.decode(list(tokens), skip_special_tokens=False)

    def _row(self, logprobs: Any) -> np.ndarray:
        if self.mx is not None:
            logprobs = logprobs.astype(self.mx.float32)
        return np.asarray(logprobs, dtype=np.float64).reshape(-1)

    def _generate(self, audio: np.ndarray, max_tokens: int, stop_at_text: bool) -> tuple[list[int], list[np.ndarray]]:
        tokens: list[int] = []
        rows: list[np.ndarray] = []
        for token, logprobs in self.model.stream_generate(np.asarray(audio, dtype=np.float32),
                                                          max_tokens=max_tokens, language=None):
            tokens.append(int(token))
            if len(rows) < LANGUAGE_STEPS:
                rows.append(self._row(logprobs))
            if stop_at_text and ASR_TEXT_TAG in self._decode(tokens):
                break
        if self.mx is not None:
            self.mx.clear_cache()
        return tokens, rows

    def _language(self, tokens: list[int], rows: list[np.ndarray]) -> dict[str, float] | None:
        step = language_step(tokens, lambda count: self._decode(tokens[:count]))
        if step is None or step >= len(rows):
            return None
        return language_probs(rows[step], self.candidates)

    def transcribe(self, audio: np.ndarray, max_tokens: int) -> dict[str, Any]:
        tokens, rows = self._generate(audio, max_tokens, stop_at_text=False)
        language, text = parse_asr_output(self._decode(tokens))
        return {"text": text, "language": language, "languageProbs": self._language(tokens, rows),
                "truncated": len(tokens) >= max_tokens}

    def identify(self, audio: np.ndarray) -> dict[str, Any]:
        tokens, rows = self._generate(audio, WINDOW_TOKENS, stop_at_text=True)
        language, _ = parse_asr_output(self._decode(tokens))
        return {"language": language, "languageProbs": self._language(tokens, rows)}


def build_engine(job: Mapping[str, Any]) -> Qwen3AsrEngine:
    return Qwen3AsrEngine(job["modelDir"], job.get("options") or {})


def process(engine: Any, context: common.TakeContext, options: Mapping[str, Any]
            ) -> tuple[dict[str, Any], None]:
    if context.duration is not None and context.duration > float(options.get("maxSeconds", 600)):
        raise common.TakeError("audio-too-long")
    if context.audio is None or context.audio.size < common.SAMPLE_RATE // 10:
        raise common.TakeError("audio-too-short")
    result = engine.transcribe(context.audio, token_budget(context.duration, options))
    windows = []
    for start, end in common.language_windows(context.duration, float(options.get("windowSeconds", 10.0))):
        identified = engine.identify(common.window_audio(context.audio, start, end))
        windows.append({"start": start, "end": end, "language": identified["language"],
                        "languageProbs": identified["languageProbs"]})
    outputs = {"text": result["text"], "language": result["language"], "languageProbs": result["languageProbs"],
               "words": None, "languageWindows": windows or None, "truncated": bool(result["truncated"])}
    return outputs, None


if __name__ == "__main__":
    sys.exit(common.main(sys.argv[1:], build_engine=build_engine, process=process))
