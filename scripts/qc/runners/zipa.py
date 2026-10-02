"""ZIPA-large CR-CTC phone recognizer (ONNX Runtime, CPU): phones with no external language model or lexicon.

Its training data still shapes what it prints (it writes French silent letters on native speech), so
`qc.phones.agreement` counts an insertion only when the second recognizer also makes it.

ZIPA (Zhu et al., ACL 2025) is a Zipformer trained with CR-CTC on IPA-Pack++ over 127 IPA tokens
(`tokens.txt`: `<blk>` 0, the word-start token `▁`, letters, and diacritics such as `̃`, `ʰ` and
`ː` as tokens of their own). The ONNX export takes `x` [1, T, 80] float32 fbank and `x_lens` [1]
int64 and returns `log_probs` [1, T', 127] (log-softmax) and `log_probs_len` [1]; the encoder
subsamples its 10 ms feature frames; the output frame step is measured per take from the ratio of
feature frames to output frames (2x, 20 ms, for the large CR-CTC export), not assumed.

The front end is the icefall/lhotse 80-bin Kaldi fbank the model was trained on, computed with
kaldi-native-fbank (no torch, lhotse or k2): 25 ms povey window, 10 ms shift, dither 0,
`snip_edges` false, preemphasis 0.97, DC removal, mel 20 Hz to Nyquist - 400 Hz, natural log of
power, on samples in [-1, 1] at 16 kHz. These are lhotse's `FbankConfig` defaults and the
options of ZIPA's own `onnx_pretrained_ctc.py` (kaldifeat).

Output: greedy CTC phones with frame times, and `<stem>.npz` holding `logprobs` [frames x vocab]
float16, `vocab` and `frameSeconds` for GOP. Runtime `onnx`. Options: `modelFile` (`model.onnx`,
the FP32 export; `model.fp16.onnx` and `model.int8.onnx` are lighter and slightly less accurate),
`threads` (ONNX Runtime intra-op threads, 0 = its default), `frameSeconds` (an override; default
measured).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from qc import phones as phone_tools
from qc.runners import speech_common as common

FRAME_SECONDS = 0.02
FEATURE_SHIFT_SECONDS = 0.01
FBANK_BINS = 80


def read_tokens(path: Path | str) -> list[str]:
    """`tokens.txt` (`<token> <id>` per line) as a list indexed by id."""

    table: dict[int, str] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        token, _, index = line.rstrip("\n").rpartition(" ")
        table[int(index)] = token
    return [table.get(index, f"<unused-{index}>") for index in range(max(table) + 1)]


def phones_output(logprobs: np.ndarray, vocab: list[str], frame_seconds: float, npz_name: str
                  ) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    """The phones-schema outputs and the posteriors npz arrays (shared with the wav2vec2 runner)."""

    scores = np.asarray(logprobs, dtype=np.float32)
    phones = phone_tools.ctc_greedy(scores, vocab, frame_seconds)
    arrays = {"logprobs": scores.astype(np.float16), "vocab": np.array(vocab, dtype=str),
              "frameSeconds": np.array(frame_seconds, dtype=np.float64)}
    outputs = {"phones": phones, "posteriors": npz_name, "frameSeconds": frame_seconds,
               "frames": int(scores.shape[0])}
    return outputs, arrays


class ZipaEngine:
    def __init__(self, model_dir: str, options: Mapping[str, Any]) -> None:
        import kaldi_native_fbank
        import onnxruntime

        directory = Path(model_dir)
        settings = onnxruntime.SessionOptions()
        threads = int(options.get("threads", 0))
        if threads > 0:
            settings.intra_op_num_threads = threads
        self.session = onnxruntime.InferenceSession(
            str(directory / str(options.get("modelFile", "model.onnx"))), sess_options=settings,
            providers=["CPUExecutionProvider"])
        self.inputs = [item.name for item in self.session.get_inputs()]
        self.vocab = read_tokens(directory / "tokens.txt")
        self.frame_override = options.get("frameSeconds")
        self.frame_seconds = float(self.frame_override or FRAME_SECONDS)
        self.fbank = kaldi_native_fbank

    def features(self, audio: np.ndarray) -> np.ndarray:
        options = self.fbank.FbankOptions()
        options.frame_opts.samp_freq = common.SAMPLE_RATE
        options.frame_opts.frame_shift_ms = 10.0
        options.frame_opts.frame_length_ms = 25.0
        options.frame_opts.dither = 0.0
        options.frame_opts.snip_edges = False
        options.frame_opts.window_type = "povey"
        options.frame_opts.preemph_coeff = 0.97
        options.frame_opts.remove_dc_offset = True
        options.mel_opts.num_bins = FBANK_BINS
        options.mel_opts.low_freq = 20.0
        options.mel_opts.high_freq = -400.0
        computer = self.fbank.OnlineFbank(options)
        computer.accept_waveform(common.SAMPLE_RATE, np.asarray(audio, dtype=np.float32).tolist())
        computer.input_finished()
        frames = [computer.get_frame(index) for index in range(computer.num_frames_ready)]
        if not frames:
            raise common.TakeError("audio-too-short")
        return np.asarray(frames, dtype=np.float32)

    def logprobs(self, audio: np.ndarray) -> np.ndarray:
        features = self.features(audio)
        outputs = self.session.run(None, {self.inputs[0]: features[None, :, :],
                                          self.inputs[1]: np.array([features.shape[0]], dtype=np.int64)})
        scores = outputs[0][0]
        if len(outputs) > 1:
            scores = scores[:int(np.asarray(outputs[1]).reshape(-1)[0])]
        if scores.shape[-1] != len(self.vocab):
            raise RuntimeError("ZIPA output width does not match tokens.txt")
        if not self.frame_override and scores.shape[0]:
            # The encoder's subsampling, measured: feature frames per output frame, as a whole number.
            ratio = max(1, int(round(features.shape[0] / scores.shape[0])))
            self.frame_seconds = FEATURE_SHIFT_SECONDS * ratio
        return scores


def build_engine(job: Mapping[str, Any]) -> ZipaEngine:
    return ZipaEngine(job["modelDir"], job.get("options") or {})


def process(engine: Any, context: common.TakeContext, options: Mapping[str, Any]
            ) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    if context.audio is None or context.audio.size < common.SAMPLE_RATE // 10:
        raise common.TakeError("audio-too-short")
    return phones_output(engine.logprobs(context.audio), engine.vocab, engine.frame_seconds, context.npz_name)


if __name__ == "__main__":
    sys.exit(common.main(sys.argv[1:], build_engine=build_engine, process=process))
