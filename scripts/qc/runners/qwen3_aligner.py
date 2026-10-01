"""Qwen3-ForcedAligner 0.6B on MLX (mlx-audio): start and end times for the take's script.

Units: characters for Chinese and Japanese (a run of Latin letters or digits stays one unit),
eojeol (whitespace words) for Korean, and words elsewhere, split at whitespace and punctuation
with letters, digits and apostrophes kept (mlx-audio's own cleaning). The runner splits the text
itself and hands mlx-audio the units joined by spaces through its whitespace path, so mlx-audio
never imports nagisa (Japanese) or soynlp (Korean, GPL-3.0): in mlx-audio 0.5.x the aligner's
`language` argument only selects that word splitter.

The aligner predicts each unit boundary as a timestamp class; it has no per-unit confidence, so
`score` is null. The output depends on the text and language: results carry a variant key.
Runtime `mlx`. Options: `maxSeconds` (300).
"""

from __future__ import annotations

import sys
import unicodedata
from typing import Any, Mapping, Sequence

from qc.runners import speech_common as common

PRESPLIT_LANGUAGE = "English"  # selects mlx-audio's whitespace splitter; the units are ours
CHARACTER_LANGUAGES = ("chinese", "japanese")


def _kept(char: str) -> bool:
    return char == "'" or unicodedata.category(char)[0] in "LN"


def _is_han(char: str) -> bool:
    code = ord(char)
    return (0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF or 0x20000 <= code <= 0x2CEAF
            or 0xF900 <= code <= 0xFAFF)


def _is_kana(char: str) -> bool:
    code = ord(char)
    return 0x3040 <= code <= 0x30FF or 0x31F0 <= code <= 0x31FF or 0xFF66 <= code <= 0xFF9F


def alignment_units(text: str, language: str | None) -> list[str]:
    """The script's units. Each unit is unchanged by mlx-audio's whitespace splitter (letters,
    digits and apostrophes only; Han characters on their own), so its items map 1:1 to ours."""

    if language == "korean":
        units = []
        for word in text.split():
            units += alignment_units("".join(char for char in word if _kept(char)), "english")
        return units
    characters = language in CHARACTER_LANGUAGES
    units: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            units.append("".join(buffer))
            buffer.clear()

    for char in text:
        if _is_han(char) or (characters and _is_kana(char)):
            flush()
            units.append(char)
        elif _kept(char):
            buffer.append(char)
        else:
            flush()
    flush()
    return units


def unit_kind(language: str | None) -> str:
    return "char" if language in CHARACTER_LANGUAGES else "word"


def _field(item: Any, *names: str) -> Any:
    for name in names:
        value = item.get(name) if isinstance(item, Mapping) else getattr(item, name, None)
        if value is not None:
            return value
    return None


class AlignerEngine:
    def __init__(self, model_dir: str, options: Mapping[str, Any]) -> None:
        import mlx.core as mx
        from mlx_audio.stt.utils import load_model

        self.mx = mx
        self.model = load_model(str(model_dir))

    def align(self, audio: Any, units: Sequence[str]) -> list[tuple[str, float, float]]:
        result = self.model.generate(audio, text=" ".join(units), language=PRESPLIT_LANGUAGE)
        items = getattr(result, "items", None)
        if items is None:
            items = getattr(result, "segments", None) or []
        spans = [(str(_field(item, "text")), float(_field(item, "start_time", "start")),
                  float(_field(item, "end_time", "end"))) for item in items]
        self.mx.clear_cache()
        return spans


def build_engine(job: Mapping[str, Any]) -> AlignerEngine:
    return AlignerEngine(job["modelDir"], job.get("options") or {})


def process(engine: Any, context: common.TakeContext, options: Mapping[str, Any]) -> tuple[dict[str, Any], None]:
    take = context.take
    language = take.get("language")
    if language not in common.LANGUAGES:
        raise common.TakeError("language-unsupported")
    if not take.get("text"):
        raise common.TakeError("text-missing")
    units = alignment_units(str(take["text"]), language)
    if not units:
        raise common.TakeError("text-missing")
    if context.duration is not None and context.duration > float(options.get("maxSeconds", 300)):
        raise common.TakeError("audio-too-long")
    spans = engine.align(context.audio, units)
    if len(spans) != len(units):
        raise common.TakeError("alignment-units-mismatch")
    words = [{"text": unit, "start": round(start, 3), "end": round(end, 3), "score": None}
             for unit, (_, start, end) in zip(units, spans)]
    return {"words": words, "units": unit_kind(language)}, None


if __name__ == "__main__":
    sys.exit(common.main(sys.argv[1:], build_engine=build_engine, process=process, depends=True))
