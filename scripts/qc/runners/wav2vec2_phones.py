"""wav2vec2-xlsr-53-espeak-cv-ft phone recognizer (transformers on torch): the second recognizer
(role `phonesB`), whose insertions must agree with ZIPA's before a phone feature counts them.

A CTC model over espeak-ng phone labels (`vocab.json`: `<pad>` 0 is the blank; labels such as
`aɪ`, `tʃ`, `iː` or `i5` can hold several IPA symbols, a length mark or a tone digit) at 16 kHz,
one frame per 20 ms. Same phones schema and npz as `qc.runners.zipa`, so either can be the
phones model; `qc.phones` normalizes both label sets onto one inventory.

Only `Wav2Vec2FeatureExtractor` (zero-mean, unit-variance input) and `Wav2Vec2ForCTC` are loaded:
the repository's `Wav2Vec2PhonemeCTCTokenizer` would load phonemizer and espeak, and decoding
needs only `vocab.json`. `pytorch_model.bin` loads with `weights_only` (torch >= 2.6). Runtime
`torch`. Options: `device` (`cpu`), `threads` (torch intra-op threads, 0 = default),
`maxSeconds` (120).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from qc.runners import speech_common as common
from qc.runners.zipa import phones_output

FRAME_SECONDS = 0.02


def read_vocab(path: Path | str, size: int | None = None) -> list[str]:
    table = json.loads(Path(path).read_text(encoding="utf-8"))
    count = max(size or 0, max(table.values()) + 1)
    vocab = [f"<unused-{index}>" for index in range(count)]
    for token, index in table.items():
        vocab[int(index)] = token
    return vocab


class Wav2Vec2Engine:
    def __init__(self, model_dir: str, options: Mapping[str, Any]) -> None:
        import torch
        from transformers import Wav2Vec2FeatureExtractor, Wav2Vec2ForCTC

        threads = int(options.get("threads", 0))
        if threads > 0:
            torch.set_num_threads(threads)
        self.torch = torch
        self.device = str(options.get("device", "cpu"))
        self.extractor = Wav2Vec2FeatureExtractor.from_pretrained(str(model_dir), local_files_only=True)
        self.model = Wav2Vec2ForCTC.from_pretrained(str(model_dir), local_files_only=True).eval().to(self.device)
        self.vocab = read_vocab(Path(model_dir) / "vocab.json", int(self.model.config.vocab_size))
        self.frame_seconds = float(options.get("frameSeconds", FRAME_SECONDS))

    def logprobs(self, audio: np.ndarray) -> np.ndarray:
        inputs = self.extractor(np.asarray(audio, dtype=np.float32), sampling_rate=common.SAMPLE_RATE,
                                return_tensors="pt")
        with self.torch.inference_mode():
            logits = self.model(inputs.input_values.to(self.device)).logits[0]
            scores = self.torch.log_softmax(logits.float(), dim=-1)
        return scores.cpu().numpy()


def build_engine(job: Mapping[str, Any]) -> Wav2Vec2Engine:
    return Wav2Vec2Engine(job["modelDir"], job.get("options") or {})


def process(engine: Any, context: common.TakeContext, options: Mapping[str, Any]
            ) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    if context.audio is None or context.audio.size < common.SAMPLE_RATE // 10:
        raise common.TakeError("audio-too-short")
    if context.duration is not None and context.duration > float(options.get("maxSeconds", 120)):
        raise common.TakeError("audio-too-long")
    return phones_output(engine.logprobs(context.audio), engine.vocab, engine.frame_seconds, context.npz_name)


if __name__ == "__main__":
    sys.exit(common.main(sys.argv[1:], build_engine=build_engine, process=process))
