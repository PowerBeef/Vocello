#!/usr/bin/env python3
"""QC v2 signal and judge runners with stubbed models: the result schema each writes, RMVPE's numpy
front end and decoding, and the llama.cpp judge's requests and parsing against a fake server."""

from __future__ import annotations

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import socketserver
import sys
import tempfile
import threading
import unittest
import wave

import numpy as np

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

from qc.runners import _kit, _llama, audiobox, redimnet, rmvpe, swiftf0, utmosv2  # noqa: E402

ROOT = SCRIPTS.parent
SR = 24_000


def write_wav(path: Path, samples: np.ndarray, sr: int = SR) -> None:
    pcm = np.clip(np.rint(samples * 32767.0), -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sr)
        writer.writeframes(pcm.tobytes())


def sine(seconds: float, hz: float, sr: int = SR, amplitude: float = 0.4) -> np.ndarray:
    return amplitude * np.sin(2 * np.pi * hz * np.arange(int(round(seconds * sr))) / sr)


class RunnerCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.output = self.root / "results"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def take(self, name: str, samples: np.ndarray, **extra: object) -> dict:
        path = self.root / f"{name}.wav"
        write_wav(path, samples)
        take = {"token": name, "audio": str(path), "audioSHA256": f"{name:0<64}"[:64], "language": "french",
                "text": None, "reference": None, "referenceSHA256": None}
        take.update(extra)
        return take

    def job(self, model: str, takes: list[dict], **options: object) -> dict:
        return {"model": model, "modelDir": str(self.root / "model"), "outputDir": str(self.output),
                "runnerSHA256": "ab" * 32, "options": dict(options), "takes": takes}

    def result(self, take: dict, variant: str | None = None) -> dict:
        record = json.loads(_kit.result_path(self.output, take["audioSHA256"], variant).read_text(encoding="utf-8"))
        self.assertEqual(record["schema"], "vocello.qc.result/1")
        self.assertEqual(record["audioSHA256"], take["audioSHA256"])
        self.assertEqual(record["runnerSHA256"], "ab" * 32)
        self.assertEqual(record["variantKey"], variant)
        return record

    def assert_pitch_schema(self, outputs: dict, hop: float) -> None:
        self.assertAlmostEqual(outputs["hopSeconds"], hop)
        self.assertEqual(len(outputs["f0Hz"]), len(outputs["confidence"]))
        for value in outputs["f0Hz"]:
            self.assertTrue(value is None or outputs["fminHz"] <= value <= outputs["fmaxHz"])


class KitTests(RunnerCase):
    def test_wav_reader_handles_pcm16_and_float32_and_stereo(self) -> None:
        tone = sine(0.1, 440.0)
        pcm = self.root / "pcm.wav"
        write_wav(pcm, tone)
        samples, sr = _kit.read_wav(pcm)
        self.assertEqual(sr, SR)
        self.assertLess(float(np.max(np.abs(samples - tone))), 1e-4)

        stereo = np.stack([tone, -tone * 0], axis=1).astype("<f4")
        body = stereo.tobytes()
        fmt = (b"fmt " + (16).to_bytes(4, "little") + (3).to_bytes(2, "little") + (2).to_bytes(2, "little")
               + SR.to_bytes(4, "little") + (SR * 8).to_bytes(4, "little") + (8).to_bytes(2, "little")
               + (32).to_bytes(2, "little"))
        data = b"data" + len(body).to_bytes(4, "little") + body
        floats = self.root / "float.wav"
        floats.write_bytes(b"RIFF" + (4 + len(fmt) + len(data)).to_bytes(4, "little") + b"WAVE" + fmt + data)
        samples, sr = _kit.read_wav(floats)
        self.assertLess(float(np.max(np.abs(samples - tone / 2))), 1e-6)

    def test_resample_keeps_a_tone(self) -> None:
        out = _kit.resample(sine(1.0, 440.0), SR, 16_000)
        self.assertEqual(out.size, 16_000)
        spectrum = np.abs(np.fft.rfft(out))
        self.assertAlmostEqual(float(np.argmax(spectrum)), 440.0, delta=1.0)

    def test_variant_key_follows_text_language_and_reference(self) -> None:
        base = {"text": "Bonjour", "language": "french", "referenceSHA256": None, "audio": "x"}
        key = _kit.variant_key(base)
        self.assertRegex(key, r"^[0-9a-f]{16}$")
        self.assertEqual(key, _kit.variant_key(dict(base, audio="y", token="t")))
        self.assertNotEqual(key, _kit.variant_key(dict(base, text="Bonsoir")))
        self.assertNotEqual(key, _kit.variant_key(dict(base, referenceSHA256="c" * 64)))
        # The host's canonical form: sorted keys, compact separators, UTF-8, first 16 hex digits.
        canonical = json.dumps({"language": "french", "reference": None, "text": "Bonjour"},
                               sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        self.assertEqual(key, hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16])
        try:
            from qc import store
        except ImportError:
            return
        if hasattr(store, "variant_key"):
            self.assertEqual(key, store.variant_key("Bonjour", "french", None))

    def test_the_jobs_variant_key_decides_the_result_name(self) -> None:
        keyed = self.take("keyed", sine(0.2, 200.0), variantKey="0123456789abcdef")
        unkeyed = self.take("unkeyed", sine(0.2, 200.0), variantKey=None)

        def process(model, take, job):
            return {"ok": True}, 0.2, "ffffffffffffffff"

        self.assertEqual(_kit.run_job(self.job("test.model", [keyed, unkeyed]), None, process), 0)
        self.assertTrue(self.result(keyed, "0123456789abcdef")["outputs"]["ok"])
        self.assertTrue(self.result(unkeyed)["outputs"]["ok"])

    def test_windows_cover_the_take(self) -> None:
        self.assertEqual(_kit.windows(2.5, 4.0, 1.0), [(0.0, 2.5)])
        spans = _kit.windows(6.5, 4.0, 1.0)
        self.assertEqual(spans[0], (0.0, 4.0))
        self.assertEqual(spans[-1], (2.5, 6.5))
        self.assertEqual(len(spans), 4)

    def test_failed_take_writes_an_error_and_the_batch_continues(self) -> None:
        good = self.take("good", sine(0.2, 200.0))
        missing = dict(good, token="missing", audio=str(self.root / "absent.wav"), audioSHA256="f" * 64)

        def process(model, take, job):
            samples, sr, duration = _kit.load_take_audio(take)
            return {"peak": float(np.abs(samples).max())}, duration, None

        code = _kit.run_job(self.job("test.model", [good, missing]), None, process)
        self.assertEqual(code, 1)
        self.assertIn("peak", self.result(good)["outputs"])
        failed = self.result(missing)
        self.assertEqual(failed["error"], "audio-unreadable")
        self.assertNotIn("outputs", failed)
        self.assertEqual([p.name for p in self.output.iterdir() if p.name.startswith(".")], [])

    def test_unit_embedding_is_l2_normalized(self) -> None:
        vector = _kit.unit(np.array([3.0, 4.0]))
        self.assertAlmostEqual(math.hypot(*vector), 1.0, places=6)
        with self.assertRaises(_kit.TakeError):
            _kit.unit(np.zeros(4))


class RmvpeTests(RunnerCase):
    def test_mel_filterbank_matches_librosa_htk_slaney_shape(self) -> None:
        basis = rmvpe.mel_filterbank()
        self.assertEqual(basis.shape, (128, 513))
        self.assertTrue((basis >= 0).all())
        peaks = basis.argmax(axis=1)
        self.assertTrue((np.diff(peaks) >= 0).all())
        freqs = np.fft.rfftfreq(1024, 1 / 16_000)
        self.assertGreaterEqual(freqs[peaks[0]], 25.0)
        self.assertLessEqual(freqs[peaks[-1]], 8000.0)
        # Slaney normalization: each triangle's area in Hz is about 1 (2 / band width * band width / 2).
        areas = basis.sum(axis=1) * (16_000 / 1024)
        self.assertTrue(np.allclose(areas, 1.0, atol=0.12))
        self.assertAlmostEqual(float(areas[40:].mean()), 1.0, delta=0.01)

    def test_log_mel_frames_and_padding(self) -> None:
        audio = sine(1.0, 1000.0, 16_000)
        mel = rmvpe.log_mel(audio)
        self.assertEqual(mel.shape, (128, 16_000 // 160 + 1))
        self.assertAlmostEqual(float(mel.min()), math.log(1e-5), places=3) if mel.min() < -11 else None
        peak_band = int(mel[:, 50].argmax())
        centers = rmvpe._mel_to_hz_htk(np.linspace(rmvpe._hz_to_mel_htk(30.0), rmvpe._hz_to_mel_htk(8000.0), 130))[1:-1]
        self.assertLess(abs(centers[peak_band] - 1000.0), 60.0)
        padded = rmvpe.pad_frames(mel)
        self.assertEqual(padded.shape[1] % 32, 0)
        self.assertTrue((padded[:, mel.shape[1]:] == 0).all())

    def test_decode_uses_the_local_average_and_threshold(self) -> None:
        hidden = np.zeros((3, 360), dtype=np.float32)
        hidden[0, 100] = 0.9
        hidden[1, 200] = 0.5
        hidden[1, 201] = 0.5
        hidden[2, 50] = 0.02  # below RVC's 0.03
        f0, peak = rmvpe.decode(hidden)
        self.assertAlmostEqual(f0[0], 10 * 2 ** ((20 * 100 + rmvpe.CENTS_OFFSET) / 1200), places=3)
        self.assertAlmostEqual(f0[1], 10 * 2 ** ((20 * 200.5 + rmvpe.CENTS_OFFSET) / 1200), places=3)
        self.assertEqual(f0[2], 0.0)
        self.assertAlmostEqual(float(peak[0]), 0.9, places=6)

    def test_runner_writes_the_pitch_schema_with_a_stub_session(self) -> None:
        class Port:
            def __init__(self, name: str) -> None:
                self.name = name

        class Session:
            def __init__(self) -> None:
                self.shapes = []

            def get_inputs(self):
                return [Port("input")]

            def get_outputs(self):
                return [Port("output")]

            def run(self, names, feed):
                mel = feed["input"]
                self.shapes.append(mel.shape)
                hidden = np.zeros((1, mel.shape[2], 360), dtype=np.float32)
                bin_200hz = int(round((1200 * math.log2(200 / 10) - rmvpe.CENTS_OFFSET) / 20))
                hidden[0, :, bin_200hz] = 0.8
                hidden[0, :10, :] = 0.0  # silence first
                return [hidden]

        session = Session()
        take = self.take("tone", sine(0.5, 200.0))
        code = _kit.run_job(self.job("pitch.rmvpe", [take]), rmvpe.Model(session, rmvpe.THRESHOLD), rmvpe.process)
        self.assertEqual(code, 0)
        record = self.result(take)
        outputs = record["outputs"]
        self.assert_pitch_schema(outputs, 0.01)
        self.assertEqual(len(outputs["f0Hz"]), 16_000 // 2 // 160 + 1)
        self.assertEqual(session.shapes[0][1], 128)
        self.assertEqual(session.shapes[0][2] % 32, 0)
        self.assertIsNone(outputs["f0Hz"][0])
        self.assertAlmostEqual(outputs["f0Hz"][20], 200.0, delta=3.0)
        self.assertEqual(outputs["threshold"], 0.03)
        self.assertAlmostEqual(record["durationSeconds"], 0.5, places=3)


class SwiftF0Tests(RunnerCase):
    def test_runner_maps_frames_to_the_grid_and_nulls_unvoiced(self) -> None:
        class Result:
            def __init__(self, n: int) -> None:
                self.timestamps = np.arange(n) * 0.016
                self.pitch_hz = np.full(n, 730.0)
                self.pitch_hz[3] = 2500.0
                self.confidence = np.full(n, 0.9)
                self.confidence[1] = 0.4

        class Detector:
            def __init__(self) -> None:
                self.calls = []

            def detect(self, audio, sample_rate, fmin=None, fmax=None):
                self.calls.append((audio.size, sample_rate, fmin, fmax))
                return Result(max(1, audio.size // 256))

        detector = Detector()
        take = self.take("tone", sine(0.64, 730.0))
        self.assertEqual(_kit.run_job(self.job("pitch.swiftf0", [take]), detector, swiftf0.process), 0)
        self.assertEqual(detector.calls[0], (int(0.64 * 16_000), 16_000, 46.875, 2093.75))
        outputs = self.result(take)["outputs"]
        self.assert_pitch_schema(outputs, 0.016)
        self.assertEqual(len(outputs["f0Hz"]), 40)
        self.assertEqual(outputs["f0Hz"][0], 730.0)
        self.assertIsNone(outputs["f0Hz"][1])  # confidence under 0.5
        self.assertIsNone(outputs["f0Hz"][3])  # beyond the supported range
        self.assertEqual(outputs["confidence"][1], 0.4)


class StubEmbedder:
    """192-d embeddings that depend on the clip (its RMS and length), like a real encoder's would."""

    def __init__(self) -> None:
        self.batches: list[tuple[int, int]] = []

    def embed(self, batch: np.ndarray) -> np.ndarray:
        self.batches.append(batch.shape)
        rows = []
        for clip in batch:
            vector = np.cos(np.arange(192) * (1.0 + float(np.sqrt(np.mean(clip ** 2)))))
            vector[0] += clip.size / 16_000
            rows.append(vector / np.linalg.norm(vector))
        return np.stack(rows)


class RedimnetTests(RunnerCase):
    def model(self) -> dict:
        return {"embedder": StubEmbedder(), "references": {}}

    def test_windows_whole_and_reference_with_a_variant_key(self) -> None:
        model = self.model()
        reference = self.root / "reference.wav"
        write_wav(reference, sine(3.0, 150.0))
        clone = self.take("clone", sine(6.5, 180.0), reference=str(reference), referenceSHA256="c" * 64)
        plain = self.take("plain", sine(2.5, 180.0))
        job = self.job("speaker.redimnet2-plus", [clone, plain])
        self.assertEqual(_kit.run_job(job, model, redimnet.process, redimnet.variant_of), 0)

        outputs = self.result(clone, _kit.variant_key(clone))["outputs"]
        self.assertEqual((outputs["windowSeconds"], outputs["hopSeconds"]), (4.0, 1.0))
        self.assertEqual([(w["start"], w["end"]) for w in outputs["windows"]],
                         [(0.0, 4.0), (1.0, 5.0), (2.0, 6.0), (2.5, 6.5)])
        for vector in [w["embedding"] for w in outputs["windows"]] + [outputs["whole"], outputs["reference"]]:
            self.assertEqual(len(vector), 192)
            self.assertAlmostEqual(float(np.linalg.norm(vector)), 1.0, places=5)
        self.assertIn((4, 64_000), model["embedder"].batches)  # the windows go as one 4 s batch

        short = self.result(plain)["outputs"]
        self.assertEqual(len(short["windows"]), 1)
        self.assertEqual(short["windows"][0]["start"], 0.0)
        self.assertAlmostEqual(short["windows"][0]["end"], 2.5, places=3)
        self.assertEqual(short["windows"][0]["embedding"], short["whole"])
        self.assertIsNone(short["reference"])

    def test_reference_is_embedded_once_per_digest(self) -> None:
        model = self.model()
        reference = self.root / "reference.wav"
        write_wav(reference, sine(2.0, 150.0))
        takes = [self.take(f"t{i}", sine(1.0, 200.0 + i), reference=str(reference), referenceSHA256="d" * 64) for i in range(3)]
        self.assertEqual(_kit.run_job(self.job("speaker.redimnet2-plus", takes), model, redimnet.process, redimnet.variant_of), 0)
        self.assertEqual(list(model["references"]), ["d" * 64])

    def test_too_short_take_is_an_error(self) -> None:
        take = self.take("blip", sine(0.2, 200.0))
        self.assertEqual(_kit.run_job(self.job("speaker.redimnet2-plus", [take]), self.model(), redimnet.process), 1)
        self.assertEqual(self.result(take)["error"], "audio-too-short")

    def test_checkpoint_keys_are_stripped_to_the_encoder(self) -> None:
        state = {"_orig_mod.encoder.model.backbone.head.weight": 1, "encoder._orig_mod.spec_frontend.fb": 2,
                 "_orig_mod.classifier.weight": 3, "module._orig_mod.bridge.x": 4,
                 "_orig_mod.encoder.model.backbone.submodule.weight": 5}
        self.assertEqual(redimnet.encoder_state(state), {"model.backbone.head.weight": 1, "spec_frontend.fb": 2,
                                                         "model.backbone.submodule.weight": 5})

        class Result:
            def __init__(self, missing, unexpected):
                self.missing_keys, self.unexpected_keys = missing, unexpected

        redimnet.check_load(Result(["spec_frontend.fb", "model.spec.fb"], []))
        with self.assertRaises(RuntimeError):
            redimnet.check_load(Result(["model.linear.weight"], []))
        with self.assertRaises(RuntimeError):
            redimnet.check_load(Result([], ["classifier.weight"]))

    def test_code_is_imported_without_running_the_asv_package_init(self) -> None:
        code = self.root / "model/code/redimnet2-plus-2a8d6dbd"
        (code / "asv/models").mkdir(parents=True)
        (code / "asv/__init__.py").write_text("raise ImportError('hydra')\n", encoding="utf-8")
        (code / "asv/models/__init__.py").write_text("raise ImportError('omegaconf')\n", encoding="utf-8")
        (code / "asv/models/redimnet2.py").write_text("class ReDimNet2Encoder:\n    marker = 'ok'\n", encoding="utf-8")
        root = redimnet.find_code_root(self.root / "model", {})
        self.assertEqual(root, code)
        saved = {name: sys.modules.pop(name) for name in list(sys.modules) if name == "asv" or name.startswith("asv.")}
        try:
            self.assertEqual(redimnet.import_encoder_class(root).marker, "ok")
        finally:
            for name in [n for n in sys.modules if n == "asv" or n.startswith("asv.")]:
                del sys.modules[name]
            sys.modules.update(saved)


class StubScorer:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[int, ...], int]] = []

    def predict(self, clips: np.ndarray, repetitions: int) -> np.ndarray:
        self.calls.append((clips.shape, repetitions))
        return 3.0 + np.sqrt(np.mean(clips ** 2, axis=1))


class Utmosv2Tests(RunnerCase):
    def model(self, **overrides: object) -> dict:
        model = {"scorer": StubScorer(), "repetitions": 5, "windowRepetitions": 1, "windows": True, "fold": 0}
        model.update(overrides)
        return model

    def test_whole_take_and_three_second_windows(self) -> None:
        model = self.model()
        take = self.take("long", np.concatenate([sine(3.0, 200.0, amplitude=0.2), sine(2.5, 200.0, amplitude=0.6)]))
        self.assertEqual(_kit.run_job(self.job("mos.utmosv2", [take]), model, utmosv2.process), 0)
        outputs = self.result(take)["outputs"]
        self.assertIsInstance(outputs["mos"], float)
        spans = [(w["start"], w["end"]) for w in outputs["windows"]]
        self.assertEqual(spans, [(0.0, 3.0), (1.0, 4.0), (2.0, 5.0), (2.5, 5.5)])
        self.assertLess(outputs["windows"][0]["mos"], outputs["windows"][-1]["mos"])
        (whole_shape, whole_reps), (window_shape, window_reps) = model["scorer"].calls
        self.assertEqual((whole_shape[0], whole_reps), (1, 5))
        self.assertEqual((window_shape, window_reps), ((4, utmosv2.WINDOW_SAMPLES), 1))
        self.assertEqual(utmosv2.WINDOW_SAMPLES, 48_001)

    def test_short_take_is_one_window(self) -> None:
        take = self.take("short", sine(2.0, 200.0))
        self.assertEqual(_kit.run_job(self.job("mos.utmosv2", [take]), self.model(), utmosv2.process), 0)
        outputs = self.result(take)["outputs"]
        self.assertEqual(len(outputs["windows"]), 1)
        self.assertEqual(outputs["windows"][0]["mos"], outputs["mos"])

    def test_local_code_and_ssl_directories_are_found(self) -> None:
        model_dir = self.root / "model"
        (model_dir / "code/UTMOSv2-cc2700db/utmosv2").mkdir(parents=True)
        (model_dir / "code/UTMOSv2-cc2700db/utmosv2/__init__.py").write_text("", encoding="utf-8")
        ssl = model_dir / "deps/wav2vec2-base"
        ssl.mkdir(parents=True)
        for name in ("config.json", "preprocessor_config.json"):
            (ssl / name).write_text("{}", encoding="utf-8")
        self.assertEqual(utmosv2.find_code_root(model_dir, {}), model_dir / "code/UTMOSv2-cc2700db")
        self.assertEqual(utmosv2.find_ssl_dir(model_dir, {}), ssl)
        self.assertIsNone(utmosv2.find_ssl_dir(self.root / "elsewhere", {}))


class AudioboxTests(RunnerCase):
    def test_runner_writes_the_four_axes(self) -> None:
        class Stub:
            def __init__(self) -> None:
                self.seen = []

            def score(self, audio, sr):
                self.seen.append((audio.size, sr))
                return {"CE": 6.123456, "CU": 7.5, "PC": 2.25, "PQ": 7.75, "extra": 1}

        stub = Stub()
        take = self.take("take", sine(1.5, 220.0))
        self.assertEqual(_kit.run_job(self.job("aesthetics.audiobox-aesthetics", [take]), stub, audiobox.process), 0)
        self.assertEqual(stub.seen, [(24_000, 16_000)])
        self.assertEqual(self.result(take)["outputs"], {"CE": 6.1235, "CU": 7.5, "PC": 2.25, "PQ": 7.75})


# --- the llama.cpp judge -------------------------------------------------------------------------


def token_stream(text: str, probabilities: dict[str, float]) -> list[dict]:
    """Split generated JSON into tokens with `true`/`false` as their own tokens, giving each class's
    `present` value top log-probabilities from `probabilities` (P(true))."""
    tokens: list[dict] = []
    cursor = 0
    for name, p_true in probabilities.items():
        at = text.find('"present":', text.find(json.dumps(name), cursor)) + len('"present":')
        literal = "true" if text.startswith("true", at) else "false"
        if at > cursor:
            tokens.append({"token": text[cursor:at], "logprob": 0.0, "top_logprobs": []})
        top = [{"token": "true", "logprob": math.log(p_true)}, {"token": "false", "logprob": math.log(1 - p_true)}]
        tokens.append({"token": literal, "logprob": math.log(p_true if literal == "true" else 1 - p_true), "top_logprobs": top})
        cursor = at + len(literal)
    tokens.append({"token": text[cursor:], "logprob": 0.0, "top_logprobs": []})
    return tokens


class LocalHTTPServer(ThreadingHTTPServer):
    def server_bind(self) -> None:
        # HTTPServer.server_bind resolves its own FQDN, which can stall on a host without DNS.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class FakeLlamaServer:
    """`/health` and `/v1/chat/completions` like llama-server: a transcript, or the rubric JSON with
    log-probabilities when the request carries a JSON schema."""

    def __init__(self, stutter_chunk: int = 1) -> None:
        self.requests: list[dict] = []
        self.stutter_chunk = stutter_chunk
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _reply(self, payload: dict) -> None:
                data = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                self._reply({"status": "ok"})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                owner.requests.append(body)
                self._reply(owner.answer(body))

        self.httpd = LocalHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def answer(self, body: dict) -> dict:
        if "response_format" not in body:
            return {"choices": [{"message": {"role": "assistant", "content": " bon-bonjour "}}]}
        chunk = sum(1 for r in self.requests if "response_format" in r)
        stutter = chunk == self.stutter_chunk
        classes = {name: {"present": False, "severity": "none", "start": None, "end": None, "evidence": ""}
                   for name in _llama.class_ids()}
        if stutter:
            classes["stutter"] = {"present": True, "severity": "moderate", "start": 0.5, "end": 0.9,
                                  "evidence": "bon-bonjour repeated"}
        text = json.dumps(classes)
        probabilities = {name: (0.8 if stutter and name == "stutter" else 0.1) for name in _llama.class_ids()}
        return {"choices": [{"message": {"role": "assistant", "content": text},
                             "logprobs": {"content": token_stream(text, probabilities)}}]}

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


class LlamaJudgeTests(RunnerCase):
    def test_class_ids_match_the_contract_and_the_protocol(self) -> None:
        expected = ["stutter", "mispronunciation", "wrong-language", "cutoff", "pitch", "tonal-collapse",
                    "voice-change", "artifact", "unnatural", "other"]
        self.assertEqual(_llama.class_ids(), expected)
        protocol = ROOT / "config/qc/protocol.json"
        if protocol.is_file():
            classes = json.loads(protocol.read_text(encoding="utf-8")).get("classes", [])
            ids = [c if isinstance(c, str) else c.get("id") for c in classes]
            self.assertEqual(ids, expected)

    def test_requests_are_deterministic_and_the_script_goes_only_to_the_rubric(self) -> None:
        wav = _kit.wav_bytes(np.zeros(1600), 16_000)
        transcript = _llama.chat_request(_llama.transcript_prompt(), wav, seed=7, max_tokens=64)
        self.assertEqual(transcript["temperature"], 0.0)
        self.assertEqual(transcript["seed"], 7)
        self.assertNotIn("response_format", transcript)
        parts = transcript["messages"][0]["content"]
        self.assertEqual(parts[0]["type"], "input_audio")
        self.assertEqual(parts[0]["input_audio"]["format"], "wav")
        prompt = _llama.rubric_prompt("french", "Bonjour à tous.", 3.0)
        self.assertIn("French", prompt)
        self.assertIn("Bonjour à tous.", prompt)
        rubric = _llama.chat_request(prompt, wav, seed=7, max_tokens=64, schema=_llama.rubric_schema(), logprobs=5)
        schema = rubric["response_format"]["json_schema"]["schema"]
        self.assertEqual(schema["required"], _llama.class_ids())
        self.assertEqual(list(schema["properties"]["cutoff"]["properties"])[0], "present")
        self.assertTrue(rubric["logprobs"])
        self.assertEqual(rubric["top_logprobs"], 5)

    def test_rubric_parsing_normalizes_and_reads_p_yes(self) -> None:
        verdicts = {name: {"present": False, "severity": "none", "start": None, "end": None, "evidence": ""}
                    for name in _llama.class_ids()}
        verdicts["cutoff"] = {"present": True, "severity": "none", "start": 2.0, "end": 1.5, "evidence": "ends mid-word"}
        verdicts["pitch"] = {"present": False, "severity": "severe", "start": 1.0, "end": 2.0, "evidence": ""}
        text = json.dumps(verdicts)
        response = {"choices": [{"message": {"content": text},
                                 "logprobs": {"content": token_stream(text, {"stutter": 0.25, "cutoff": 0.9})}}]}
        parsed = _llama.parse_rubric(response)
        self.assertEqual(parsed["cutoff"]["severity"], "mild")
        self.assertEqual((parsed["cutoff"]["start"], parsed["cutoff"]["end"]), (1.5, 2.0))
        self.assertEqual(parsed["pitch"]["severity"], "none")
        self.assertIsNone(parsed["pitch"]["start"])
        self.assertAlmostEqual(parsed["stutter"]["pYes"], 0.25, places=5)
        self.assertAlmostEqual(parsed["cutoff"]["pYes"], 0.9, places=5)
        self.assertIsNone(parsed["artifact"]["pYes"])
        no_logprobs = _llama.parse_rubric({"choices": [{"message": {"content": "```json\n" + text + "\n```"}}]})
        self.assertIsNone(no_logprobs["cutoff"]["pYes"])
        with self.assertRaises(_kit.TakeError):
            _llama.parse_rubric({"choices": [{"message": {"content": "no json here"}}]})

    def test_server_command_binds_localhost_with_the_projector(self) -> None:
        command = _llama.server_command(Path("/opt/llama-server"), Path("m.gguf"), Path("mmproj.gguf"), 8099,
                                        _llama.Profile("gemma"), {})
        self.assertEqual(command[command.index("--host") + 1], "127.0.0.1")
        self.assertEqual(command[command.index("--mmproj") + 1], "mmproj.gguf")
        self.assertEqual(command[command.index("--port") + 1], "8099")

    def test_model_files_and_the_unpacked_server_are_found(self) -> None:
        model_dir = self.root / "model"
        model_dir.mkdir()
        (model_dir / "gemma-it-q4_0.gguf").write_bytes(b"")
        (model_dir / "mmproj-gemma-f16.gguf").write_bytes(b"")
        model, mmproj = _llama.find_model_files(model_dir, _llama.Profile("gemma"), {})
        self.assertEqual((model.name, mmproj.name), ("gemma-it-q4_0.gguf", "mmproj-gemma-f16.gguf"))
        unpacked = self.root / "llamacpp/llama-b11146"
        unpacked.mkdir(parents=True)
        (unpacked / "llama-server").write_bytes(b"")
        found = _llama.find_server_binary({"llamacppDir": str(self.root / "llamacpp")})
        self.assertEqual(found, unpacked / "llama-server")
        from qc.runners import gemma_judge, qwen_omni_judge
        self.assertEqual(gemma_judge.PROFILE.mmproj_file, "mmproj-gemma-4-12b-it-qat-q4_0.gguf")
        self.assertEqual(qwen_omni_judge.PROFILE.model_file, "Qwen2.5-Omni-7B-Q4_K_M.gguf")
        self.assertIn("--reasoning", _llama.server_command(found, model, mmproj, 1, gemma_judge.PROFILE, {}))

    def test_judge_end_to_end_against_a_fake_server_with_chunk_merging(self) -> None:
        server = FakeLlamaServer(stutter_chunk=2)
        self.addCleanup(server.close)
        take = self.take("long", sine(5.0, 180.0), text="Bonjour à tous.", language="french")
        job = self.job("llm.gemma", [take], serverURL=server.url, chunkSeconds=2.0, seed=11)
        job_path = self.root / "job.json"
        job_path.write_text(json.dumps(job), encoding="utf-8")
        load, process, close, variant_of = _llama.make_runner(_llama.Profile("gemma"))
        code = _kit.main(load, process, variant_of=variant_of, argv=["--job", str(job_path)], close=close)
        self.assertEqual(code, 0)
        record = self.result(take, _kit.variant_key(take))
        outputs = record["outputs"]
        self.assertEqual(outputs["chunks"], 3)
        self.assertEqual(outputs["transcript"], "bon-bonjour bon-bonjour bon-bonjour")
        stutter = outputs["classes"]["stutter"]
        self.assertTrue(stutter["present"])
        self.assertEqual(stutter["severity"], "moderate")
        offset = round(5.0 / 3, 3)
        self.assertAlmostEqual(stutter["start"], offset + 0.5, places=2)
        self.assertAlmostEqual(stutter["pYes"], 0.8, places=5)
        self.assertFalse(outputs["classes"]["cutoff"]["present"])
        self.assertAlmostEqual(outputs["classes"]["cutoff"]["pYes"], 0.1, places=5)
        self.assertEqual(sorted(outputs["classes"]), sorted(_llama.class_ids()))
        self.assertEqual(len(server.requests), 6)
        for request in server.requests:
            self.assertEqual(request["seed"], 11)
            self.assertEqual(request["temperature"], 0.0)
            text = request["messages"][0]["content"][1]["text"]
            self.assertEqual("Bonjour à tous." in text, "response_format" in request)
            audio = request["messages"][0]["content"][0]["input_audio"]
            self.assertEqual(audio["format"], "wav")

    def test_unreachable_server_records_an_error_per_take(self) -> None:
        take = self.take("short", sine(0.5, 180.0))
        job = self.job("llm.gemma", [take], serverURL="http://127.0.0.1:9", startupTimeout=0.5)
        job_path = self.root / "job.json"
        job_path.write_text(json.dumps(job), encoding="utf-8")
        load, process, close, variant_of = _llama.make_runner(_llama.Profile("gemma"))
        code = _kit.main(load, process, variant_of=variant_of, argv=["--job", str(job_path)], close=close)
        self.assertEqual(code, 1)
        self.assertTrue(self.result(take, _kit.variant_key(take))["error"].startswith("model-load-failed"))


if __name__ == "__main__":
    unittest.main()
