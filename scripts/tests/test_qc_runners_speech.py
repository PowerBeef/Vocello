"""QC v2 speech runners (Qwen3-ASR, Whisper, ZIPA, wav2vec2 phones) and their
shared plumbing: job and result schema, WAV input, resampling, language windows, variant keys.

Every model call is stubbed: the test python has NumPy but no mlx, onnxruntime or torch, and the
runner modules import those only inside their engines.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import struct
import sys
import tempfile
import unittest
import wave
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qc.runners import qwen3_asr, speech_common as common, wav2vec2_phones, whisper, zipa  # noqa: E402


def write_pcm16(path: Path, samples: np.ndarray, rate: int, channels: int = 1) -> str:
    data = np.clip(np.round(np.asarray(samples) * 32767), -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(data.tobytes())
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_wav(path: Path, payload: bytes, *, tag: int, channels: int, rate: int, bits: int) -> None:
    block = channels * bits // 8
    fmt = struct.pack("<HHIIHH", tag, channels, rate, rate * block, block, bits)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(payload)) + payload
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)


def tone(seconds: float, rate: int, frequency: float = 440.0) -> np.ndarray:
    return 0.3 * np.sin(2 * np.pi * frequency * np.arange(int(seconds * rate)) / rate)


class Workspace:
    """A temporary output directory and takes; jobs follow the contract's runner protocol."""

    def __init__(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)

    def take(self, name: str, seconds: float, *, rate: int = 24000, **fields) -> dict:
        path = self.root / f"{name}.wav"
        frequency = 200.0 + sum(name.encode()) % 600  # distinct audio, so distinct digests
        digest = write_pcm16(path, tone(seconds, rate, frequency), rate)
        return {"token": name, "audio": str(path), "audioSHA256": digest, "language": "french", "text": None,
                "reference": None, "referenceSHA256": None, **fields}

    def job(self, model: str, takes: list[dict], **options) -> dict:
        return {"model": model, "modelDir": str(self.root / "model"), "outputDir": str(self.root / "out"),
                "runnerSHA256": "c" * 64, "options": options, "takes": takes}

    def result(self, stem: str) -> dict:
        return json.loads((self.root / "out" / f"{stem}.json").read_text(encoding="utf-8"))

    def close(self) -> None:
        self.directory.cleanup()


def run(job: dict, process, engine, *, depends: bool = False) -> tuple[int, str]:
    with redirect_stdout(io.StringIO()) as stdout, redirect_stderr(io.StringIO()):
        code = common.run_job(job, lambda context: process(engine, context, job["options"]), depends=depends)
    return code, stdout.getvalue()


class CommonTests(unittest.TestCase):
    def setUp(self):
        self.space = Workspace()

    def tearDown(self):
        self.space.close()

    def test_variant_key_matches_the_store_formula(self):
        payload = json.dumps({"language": "french", "reference": None, "text": "Bonjour"}, sort_keys=True,
                             ensure_ascii=False, separators=(",", ":"))
        self.assertEqual(common.variant_key("Bonjour", "french", None),
                         hashlib.sha256(payload.encode()).hexdigest()[:16])
        take = {"text": "Bonjour", "language": "french", "referenceSHA256": None}
        self.assertEqual(common.take_variant(take, depends=True), common.variant_key("Bonjour", "french", None))
        self.assertIsNone(common.take_variant(take, depends=False))
        self.assertEqual(common.take_variant({**take, "variantKey": "abc"}, depends=True), "abc")
        self.assertIsNone(common.take_variant({**take, "variantKey": None}, depends=True))

    def test_result_records_and_atomic_writes(self):
        job, take = self.space.job("asr.test", []), {"audioSHA256": "a" * 64}
        record = common.result_record(job, take, variant=None, duration=1.23456, outputs={"text": "x"})
        self.assertEqual(record, {"schema": "vocello.qc.result/1", "model": "asr.test", "runnerSHA256": "c" * 64,
                                  "audioSHA256": "a" * 64, "variantKey": None, "durationSeconds": 1.2346,
                                  "outputs": {"text": "x"}})
        failed = common.result_record(job, take, variant="v", duration=None, error="audio-unreadable", exception="E")
        self.assertEqual((failed["error"], failed["exception"], "outputs" in failed), ("audio-unreadable", "E", False))
        with self.assertRaises(ValueError):
            common.result_record(job, take, variant=None, duration=None)
        common.write_json_atomic(self.space.root / "r.json", record)
        self.assertEqual(json.loads((self.space.root / "r.json").read_text(encoding="utf-8")), record)
        common.write_npz_atomic(self.space.root / "r.npz", {"vocab": np.array(["<blk>", "ɑ", "̃"], dtype=str),
                                                            "logprobs": np.zeros((2, 3), np.float16)})
        with np.load(self.space.root / "r.npz", allow_pickle=False) as arrays:
            self.assertEqual(list(arrays["vocab"]), ["<blk>", "ɑ", "̃"])
        self.assertEqual(sorted(path.name for path in self.space.root.iterdir() if path.name.startswith(".")), [])

    def test_wav_reader_handles_pcm_float_and_channels(self):
        samples = np.array([0.0, 0.5, -0.5, 0.25])
        path = self.space.root / "pcm.wav"
        write_pcm16(path, np.repeat(samples, 2), 8000, channels=2)
        decoded, rate = common._read_riff(path.read_bytes())
        self.assertEqual(rate, 8000)
        np.testing.assert_allclose(decoded, samples, atol=1e-4)
        write_wav(path, np.asarray(samples, "<f4").tobytes(), tag=3, channels=1, rate=16000, bits=32)
        np.testing.assert_allclose(common._read_riff(path.read_bytes())[0], samples, atol=1e-7)
        values = np.round(samples * (1 << 23)).astype(np.int32)
        triples = b"".join(int(value).to_bytes(3, "little", signed=True) for value in values)
        write_wav(path, triples, tag=1, channels=1, rate=16000, bits=24)
        np.testing.assert_allclose(common._read_riff(path.read_bytes())[0], samples, atol=1e-6)
        with self.assertRaises(ValueError):
            common._read_riff(b"not a wav")

    def test_resampling_keeps_speech_band_and_rejects_aliases(self):
        source = 24000
        kept = common.resample(tone(1.0, source, 1000.0), source, 16000)
        self.assertEqual(kept.size, 16000)
        reference = tone(1.0, 16000, 1000.0)
        self.assertLess(np.max(np.abs(kept[200:-200] - reference[200:-200])), 2e-3)
        alias = common.resample(tone(1.0, source, 10000.0), source, 16000)  # above the 8 kHz Nyquist
        self.assertLess(np.sqrt(np.mean(alias[200:-200] ** 2)), 0.3 / math.sqrt(2) * 10 ** (-60 / 20))
        np.testing.assert_allclose(common.resample(np.ones(48000), 48000, 16000)[100:-100], 1.0, atol=1e-6)
        same = np.arange(5, dtype=np.float32)
        np.testing.assert_array_equal(common.resample(same, 16000, 16000), same)
        self.assertEqual(common.resample(tone(1.0, 44100), 44100, 16000).size, 16000)

    def test_take_audio_is_verified_resampled_and_timed(self):
        take = self.space.take("t", 1.5)
        audio, duration = common.load_take_audio(take)
        self.assertEqual((audio.size, duration), (24000, 1.5))
        with self.assertRaises(common.TakeError) as raised:
            common.load_take_audio({**take, "audioSHA256": "0" * 64})
        self.assertEqual(raised.exception.code, "audio-digest-mismatch")
        broken = self.space.root / "broken.wav"
        broken.write_bytes(b"RIFF....nope")
        with self.assertRaises(common.TakeError) as raised:
            common.load_take_audio({"audio": str(broken), "audioSHA256": hashlib.sha256(broken.read_bytes()).hexdigest()})
        self.assertEqual(raised.exception.code, "audio-unreadable")

    def test_language_windows(self):
        self.assertEqual(common.language_windows(9.5), [])
        self.assertEqual(common.language_windows(10.0), [])
        self.assertEqual(common.language_windows(20.0), [(0.0, 10.0), (10.0, 20.0)])
        self.assertEqual(common.language_windows(23.0), [(0.0, 10.0), (10.0, 20.0), (13.0, 23.0)])
        self.assertEqual(common.language_windows(10.4), [(0.0, 10.0), (0.4, 10.4)])
        audio = np.arange(16000 * 3, dtype=np.float32)
        self.assertEqual(common.window_audio(audio, 1.0, 2.5).size, 24000)

    def test_run_job_writes_outputs_npz_and_errors(self):
        good, bad = self.space.take("good", 0.5), self.space.take("bad", 0.5)
        bad["audioSHA256"] = "0" * 64

        def process(engine, context, options):
            if context.take["token"] == "boom":
                raise RuntimeError("private detail /Users/somebody")
            return {"seconds": context.duration, "posteriors": context.npz_name}, {"x": np.ones(2)}

        boom = self.space.take("boom", 0.5)
        code, stdout = run(self.space.job("phones.test", [good, bad, boom]), process, None)
        self.assertEqual(code, 1)
        self.assertEqual(stdout.splitlines(), ["progress 1/3", "progress 2/3", "progress 3/3"])
        result = self.space.result(good["audioSHA256"])
        self.assertEqual(result["outputs"], {"seconds": 0.5, "posteriors": f"{good['audioSHA256']}.npz"})
        self.assertTrue((self.space.root / "out" / f"{good['audioSHA256']}.npz").is_file())
        self.assertEqual(self.space.result("0" * 64)["error"], "audio-digest-mismatch")
        failed = self.space.result(boom["audioSHA256"])
        self.assertEqual((failed["error"], failed["exception"]), ("runner-exception", "RuntimeError"))
        self.assertNotIn("somebody", json.dumps(failed))

    def test_main_exit_codes(self):
        take = self.space.take("t", 0.5)
        path = self.space.root / "job.json"
        path.write_text(json.dumps(self.space.job("asr.test", [take])), encoding="utf-8")

        def fail(job):
            raise OSError("model files missing")

        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(common.main(["--job", str(path)], build_engine=fail, process=None), 2)
        self.assertIn("model load failed (OSError)", stderr.getvalue())
        self.assertNotIn("missing", stderr.getvalue())
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(common.main(["--job", str(path)], build_engine=lambda job: "engine",
                                         process=lambda engine, context, options: ({"engine": engine}, None)), 0)
        self.assertEqual(self.space.result(take["audioSHA256"])["outputs"], {"engine": "engine"})
        path.write_text("{}", encoding="utf-8")
        with redirect_stderr(io.StringIO()):
            self.assertEqual(common.main(["--job", str(path)], build_engine=fail, process=None), 2)


class FakeTokenizer:
    """Word-level stand-in for the Qwen tokenizer: one token per piece in `PIECES`."""

    PIECES = ["language", " French", " English", " Chinese", " Cantonese", "<asr_text>", "Bon", "jour", ".",
              "<|im_end|>"]

    def encode(self, text, add_special_tokens=False):
        tokens, rest = [], text
        while rest:
            for index, piece in sorted(enumerate(self.PIECES), key=lambda item: -len(item[1])):
                if rest.startswith(piece):
                    tokens.append(index)
                    rest = rest[len(piece):]
                    break
            else:
                tokens.append(len(self.PIECES))
                rest = rest[1:]
        return tokens

    def decode(self, tokens, skip_special_tokens=False):
        return "".join(self.PIECES[token] if token < len(self.PIECES) else "?" for token in tokens)


class FakeQwenModel:
    def __init__(self, tokenizer, script, language_row):
        self.tokenizer, self.script, self.language_row = tokenizer, script, language_row
        self.calls = []

    def stream_generate(self, audio, max_tokens, language):
        self.calls.append((len(audio), max_tokens, language))
        tokens = self.tokenizer.encode(self.script)
        for step, token in enumerate(tokens[:max_tokens]):
            row = np.full(len(FakeTokenizer.PIECES) + 1, -20.0)
            if step == 1:
                row = np.array(self.language_row, dtype=np.float64)
            yield token, row


class Qwen3AsrTests(unittest.TestCase):
    def test_output_parsing(self):
        self.assertEqual(qwen3_asr.parse_asr_output("language French<asr_text>Bonjour."), ("french", "Bonjour."))
        self.assertEqual(qwen3_asr.parse_asr_output("language None<asr_text>"), (None, ""))
        self.assertEqual(qwen3_asr.parse_asr_output("Bonjour<|im_end|>"), (None, "Bonjour"))
        self.assertEqual(qwen3_asr.parse_asr_output("language English<asr_text>"), ("english", ""))

    def test_language_probabilities_from_the_language_step(self):
        tokenizer = FakeTokenizer()
        candidates = qwen3_asr.first_token_candidates(["French", "English", "Chinese"], tokenizer.encode)
        self.assertEqual(candidates, {1: ["french"], 2: ["english"], 3: ["chinese"]})
        row = np.full(11, -30.0)
        row[[1, 2, 3]] = np.log([0.6, 0.2, 0.1])
        probs = qwen3_asr.language_probs(row, candidates)
        self.assertEqual(list(probs), ["french", "english", "chinese"])
        self.assertAlmostEqual(sum(probs.values()), 1.0, places=5)
        self.assertAlmostEqual(probs["french"], 0.6 / 0.9, places=5)
        shared = qwen3_asr.language_probs(row, {1: ["french", "frenchy"]})
        self.assertEqual(shared, {"french": 0.5, "frenchy": 0.5})
        tokens = tokenizer.encode("language French<asr_text>Bonjour")
        self.assertEqual(qwen3_asr.language_step(tokens, lambda count: tokenizer.decode(tokens[:count])), 1)
        self.assertIsNone(qwen3_asr.language_step([6, 7], lambda count: tokenizer.decode([6, 7][:count])))
        self.assertIsNone(qwen3_asr.language_probs(row, {}))

    def test_token_budget(self):
        self.assertEqual(qwen3_asr.token_budget(10.0, {}), 224)
        self.assertEqual(qwen3_asr.token_budget(10.0, {"maxTokens": 50}), 50)

    def engine(self, script: str) -> qwen3_asr.Qwen3AsrEngine:
        tokenizer = FakeTokenizer()
        row = np.full(11, -30.0)
        row[[1, 2, 3, 4]] = np.log([0.7, 0.2, 0.05, 0.05])
        engine = object.__new__(qwen3_asr.Qwen3AsrEngine)
        engine.mx, engine.tokenizer = None, tokenizer
        engine.model = FakeQwenModel(tokenizer, script, row)
        engine.candidates = qwen3_asr.first_token_candidates(["French", "English", "Chinese", "Cantonese"],
                                                             engine._encode)
        return engine

    def test_engine_transcribes_without_a_forced_language(self):
        engine = self.engine("language French<asr_text>Bonjour.")
        result = engine.transcribe(np.zeros(16000, np.float32), 64)
        self.assertEqual((result["text"], result["language"], result["truncated"]), ("Bonjour.", "french", False))
        self.assertAlmostEqual(result["languageProbs"]["french"], 0.7, places=5)
        self.assertEqual(engine.model.calls[0][2], None)
        identified = engine.identify(np.zeros(16000, np.float32))
        self.assertEqual(identified["language"], "french")
        self.assertEqual(engine.model.calls[1][1], qwen3_asr.WINDOW_TOKENS)
        self.assertTrue(engine.transcribe(np.zeros(16000, np.float32), 3)["truncated"])

    def test_runner_writes_the_asr_schema_with_windows(self):
        space = Workspace()
        try:
            short, long = space.take("short", 2.0), space.take("long", 23.0)
            engine = self.engine("language French<asr_text>Bonjour.")
            code, _ = run(space.job("asr.qwen3-asr-1.7b", [short, long]), qwen3_asr.process, engine)
            self.assertEqual(code, 0)
            first = space.result(short["audioSHA256"])
            self.assertEqual(set(first["outputs"]), {"text", "language", "languageProbs", "words",
                                                     "languageWindows", "truncated"})
            self.assertEqual((first["outputs"]["text"], first["outputs"]["words"]), ("Bonjour.", None))
            self.assertIsNone(first["outputs"]["languageWindows"])
            self.assertIsNone(first["variantKey"])
            windows = space.result(long["audioSHA256"])["outputs"]["languageWindows"]
            self.assertEqual([(item["start"], item["end"]) for item in windows], [(0.0, 10.0), (10.0, 20.0), (13.0, 23.0)])
            self.assertEqual({item["language"] for item in windows}, {"french"})
            self.assertEqual(engine.model.calls[2][0], 160000)  # each window is 10 s at 16 kHz
        finally:
            space.close()


class FakeWhisper:
    names = {"fr": "french", "en": "english", "nl": "dutch", "sw": "swahili"}

    def __init__(self):
        self.languages = []

    def detect(self, audio):
        return {"fr": 0.9, "en": 0.05, "nl": 0.04, "sw": 0.01 - 1e-9}

    def transcribe(self, audio, language):
        self.languages.append(language)
        return {"text": " Les branches.", "language": language, "segments": [{"words": [
            {"word": " Les", "start": 0.1, "end": 0.32, "probability": 0.98},
            {"word": " branches.", "start": 0.32, "end": 0.9, "probability": 0.81234}]}]}


class WhisperTests(unittest.TestCase):
    def test_language_probabilities_by_name(self):
        named = whisper.named_language_probs(FakeWhisper().detect(None), FakeWhisper.names)
        self.assertEqual(list(named), ["french", "english", "dutch"])  # swahili under the floor is dropped

    def test_runner_writes_words_and_detected_language(self):
        space = Workspace()
        try:
            take = space.take("t", 12.0)
            engine = FakeWhisper()
            code, _ = run(space.job("asr.whisper-large-v3", [take]), whisper.process, engine)
            self.assertEqual(code, 0)
            outputs = space.result(take["audioSHA256"])["outputs"]
            self.assertEqual((outputs["text"], outputs["language"]), ("Les branches.", "french"))
            self.assertEqual(outputs["words"][1], {"text": "branches.", "start": 0.32, "end": 0.9, "prob": 0.8123})
            self.assertEqual(engine.languages, ["fr"])
            self.assertEqual([(item["start"], item["end"], item["language"]) for item in outputs["languageWindows"]],
                             [(0.0, 10.0, "french"), (2.0, 12.0, "french")])
        finally:
            space.close()


class FakePhones:
    def __init__(self, vocab, logprobs, frame_seconds):
        self.vocab, self.scores, self.frame_seconds = vocab, logprobs, frame_seconds

    def logprobs(self, audio):
        return self.scores


def peaky(sequence, width, peak=0.96):
    path = [0]
    for token in sequence:
        path += [token, token, 0]
    probs = np.full((len(path), width), (1 - peak) / (width - 1))
    probs[np.arange(len(path)), path] = peak
    return np.log(probs).astype(np.float32)


class PhoneRunnerTests(unittest.TestCase):
    def test_tokens_file_keeps_combining_marks(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "tokens.txt"
            path.write_text("<blk> 0\n▁ 1\nɑ 2\ñ 3\nʃ 4\n", encoding="utf-8")
            self.assertEqual(zipa.read_tokens(path), ["<blk>", "▁", "ɑ", "̃", "ʃ"])
            vocab_path = Path(temporary) / "vocab.json"
            vocab_path.write_text(json.dumps({"<pad>": 0, "<s>": 1, "aɪ": 3}), encoding="utf-8")
            self.assertEqual(wav2vec2_phones.read_vocab(vocab_path, 5), ["<pad>", "<s>", "<unused-2>", "aɪ", "<unused-4>"])

    def check_runner(self, module, vocab, sequence, frame_seconds, expected_phones):
        space = Workspace()
        try:
            take = space.take("t", 1.0)
            engine = FakePhones(vocab, peaky(sequence, len(vocab)), frame_seconds)
            code, _ = run(space.job(f"phones.{module.__name__}", [take]), module.process, engine)
            self.assertEqual(code, 0)
            outputs = space.result(take["audioSHA256"])["outputs"]
            self.assertEqual([item["phone"] for item in outputs["phones"]], expected_phones)
            self.assertEqual(outputs["posteriors"], f"{take['audioSHA256']}.npz")
            self.assertEqual((outputs["frameSeconds"], outputs["frames"]), (frame_seconds, 3 * len(sequence) + 1))
            with np.load(space.root / "out" / outputs["posteriors"], allow_pickle=False) as arrays:
                self.assertEqual(arrays["logprobs"].dtype, np.float16)
                self.assertEqual(arrays["logprobs"].shape, (3 * len(sequence) + 1, len(vocab)))
                self.assertEqual(list(arrays["vocab"]), vocab)
                self.assertEqual(float(arrays["frameSeconds"]), frame_seconds)
            # Token j of the sequence holds frames 3j-2 and 3j-1, so the last phone ends at frame 3n.
            self.assertEqual(outputs["phones"][-1]["end"], round(3 * len(sequence) * frame_seconds, 3))
        finally:
            space.close()

    def test_zipa_runner_output(self):
        self.check_runner(zipa, ["<blk>", "▁", "b", "ʁ", "ɑ", "̃", "ʃ"], [1, 2, 3, 4, 5, 6], 0.04,
                          ["b", "ʁ", "ɑ̃", "ʃ"])

    def test_wav2vec2_runner_output(self):
        self.check_runner(wav2vec2_phones, ["<pad>", "<s>", "b", "ʁ", "ɑ̃", "ʃ", "aɪ"], [2, 3, 4, 5, 6], 0.02,
                          ["b", "ʁ", "ɑ̃", "ʃ", "aɪ"])

    def test_engines_need_their_runtimes(self):
        for module, name in ((zipa, "ZipaEngine"), (wav2vec2_phones, "Wav2Vec2Engine"), (whisper, "WhisperEngine"),
                             (qwen3_asr, "Qwen3AsrEngine")):
            with self.subTest(engine=name):
                try:
                    getattr(module, name)("/nonexistent-model-dir", {})
                except ImportError:
                    pass  # the runtime package is absent here, as in the repository's python
                except Exception:  # noqa: BLE001 - present runtime, missing model: also fine
                    pass


if __name__ == "__main__":
    unittest.main()
