#!/usr/bin/env python3
"""QC v2 signal runners with stubbed models: the result schema each writes and FCPE's decoding."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
import wave

import numpy as np

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

from qc.runners import _kit, fcpe, redimnet, swiftf0  # noqa: E402

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

    def test_a_model_that_fails_to_load_records_an_error_per_take(self) -> None:
        take = self.take("short", sine(0.5, 180.0), variantKey="0123456789abcdef")
        job_path = self.root / "job.json"
        job_path.write_text(json.dumps(self.job("test.model", [take])), encoding="utf-8")

        def load(job):
            raise OSError("no weights")

        code = _kit.main(load, lambda model, take, job: ({}, 0.0, None), argv=["--job", str(job_path)])
        self.assertEqual(code, 1)
        self.assertEqual(self.result(take, "0123456789abcdef")["error"], "model-load-failed:OSError")

    def test_unit_embedding_is_l2_normalized(self) -> None:
        vector = _kit.unit(np.array([3.0, 4.0]))
        self.assertAlmostEqual(math.hypot(*vector), 1.0, places=6)
        with self.assertRaises(_kit.TakeError):
            _kit.unit(np.zeros(4))


FCPE_BINS = 360
FCPE_TABLE = np.linspace(1200 * math.log2(32.70 / 10), 1200 * math.log2(1975.5 / 10), FCPE_BINS)


def fcpe_bin(hz: float) -> int:
    return int(np.argmin(np.abs(FCPE_TABLE - 1200 * math.log2(hz / 10))))


class StubFcpe:
    """torchfcpe's salience for a steady `hz`, with the first `silent` frames below the threshold."""

    def __init__(self, hz: float, silent: int = 10) -> None:
        self.cent_table = FCPE_TABLE
        self.threshold = fcpe.THRESHOLD
        self.hz = hz
        self.silent = silent
        self.sizes: list[int] = []

    def salience(self, audio: np.ndarray) -> np.ndarray:
        self.sizes.append(audio.size)
        frames = audio.size // fcpe.HOP + 2  # torchfcpe may return a frame more; the runner trims
        latent = np.full((frames, FCPE_BINS), 0.001)
        latent[:, fcpe_bin(self.hz)] = 0.8
        latent[: self.silent, :] = 0.002
        return latent


class FcpeTests(RunnerCase):
    def test_decode_follows_the_local_argmax_decoder_and_threshold(self) -> None:
        latent = np.zeros((4, FCPE_BINS))
        latent[0, 100] = 0.9
        latent[1, 200] = latent[1, 201] = 0.5
        latent[2, 50] = 0.005  # below torchfcpe's 0.006
        latent[3, 0] = latent[3, 1] = 0.3  # the window clamps at the table's start
        f0, peak = fcpe.decode(latent, FCPE_TABLE)
        self.assertAlmostEqual(f0[0], 10 * 2 ** (FCPE_TABLE[100] / 1200), places=6)
        self.assertAlmostEqual(f0[1], 10 * 2 ** ((FCPE_TABLE[200] + FCPE_TABLE[201]) / 2 / 1200), places=6)
        self.assertEqual(f0[2], 0.0)
        clamped = (0.3 * FCPE_TABLE[0] * 5 + 0.3 * FCPE_TABLE[1]) / (0.3 * 6)
        self.assertAlmostEqual(f0[3], 10 * 2 ** (clamped / 1200), places=6)
        self.assertAlmostEqual(float(peak[0]), 0.9)

    def test_runner_writes_the_pitch_schema_with_a_stub_model(self) -> None:
        stub = StubFcpe(200.0)
        take = self.take("tone", sine(0.5, 200.0))
        self.assertEqual(_kit.run_job(self.job("pitch.fcpe", [take]), stub, fcpe.process), 0)
        self.assertEqual(stub.sizes, [8_000])  # resampled to 16 kHz
        outputs = self.result(take)["outputs"]
        self.assert_pitch_schema(outputs, 0.01)
        self.assertEqual(len(outputs["f0Hz"]), 8_000 // 160 + 1)
        self.assertIsNone(outputs["f0Hz"][0])
        self.assertAlmostEqual(outputs["f0Hz"][20], 200.0, delta=6.0)
        self.assertEqual(outputs["confidence"][20], 0.8)
        self.assertEqual((outputs["threshold"], outputs["fminHz"], outputs["fmaxHz"]), (0.006, 40.0, 1100.0))

    def test_frames_outside_40_to_1100_hz_are_unvoiced(self) -> None:
        for hz in (35.0, 1500.0):
            outputs = fcpe.pitch_outputs(np.array([hz, 730.0]), np.array([0.9, 0.9]))
            self.assertEqual(outputs["f0Hz"], [None, 730.0])

    def test_checkpoint_is_found_in_the_model_directory_first(self) -> None:
        model_dir = self.root / "model"
        fetched = model_dir / "torchfcpe/assets/fcpe_c_v001.pt"
        fetched.parent.mkdir(parents=True)
        fetched.write_bytes(b"")
        self.assertEqual(fcpe.find_checkpoint(model_dir, {}), fetched)
        other = model_dir / "custom.pt"
        other.write_bytes(b"")
        self.assertEqual(fcpe.find_checkpoint(model_dir, {"modelFile": "custom.pt"}), other)


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
        self.releases = 0

    def embed(self, batch: np.ndarray) -> np.ndarray:
        self.batches.append(batch.shape)
        rows = []
        for clip in batch:
            vector = np.cos(np.arange(192) * (1.0 + float(np.sqrt(np.mean(clip ** 2)))))
            vector[0] += clip.size / 16_000
            rows.append(vector / np.linalg.norm(vector))
        return np.stack(rows)

    def release(self) -> None:
        self.releases += 1


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

    def test_windows_go_in_fixed_size_batches_and_each_take_releases(self) -> None:
        model = self.model()
        long = self.take("long", sine(9.5, 180.0))  # windows at 0..5 s and 5.5 s: seven of them
        short = self.take("short", sine(0.2, 200.0))
        self.assertEqual(_kit.run_job(self.job("speaker.redimnet2-plus", [long, short]), model, redimnet.process), 1)
        windows = self.result(long)["outputs"]["windows"]
        self.assertEqual(len(windows), 7)
        self.assertEqual(windows[-1]["start"], 5.5)
        window_batches = [shape for shape in model["embedder"].batches if shape[1] == 64_000]
        self.assertEqual(window_batches, [(redimnet.BATCH, 64_000)] * 2)  # 4 + 3, the last one padded
        # The padding is dropped: the last window is the clip's last 4 s, embedded as if alone.
        audio, _, _ = _kit.load_take_audio(long, redimnet.SAMPLE_RATE)
        self.assertEqual(windows[-1]["embedding"], _kit.unit(StubEmbedder().embed(audio[None, -64_000:])[0]))
        self.assertEqual(model["embedder"].releases, 2)  # after every take, failed ones included

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


if __name__ == "__main__":
    unittest.main()
