#!/usr/bin/env python3
"""The AQ-06 panel engines: the registry's load gate and every file's digest before any load, with fake models."""

from __future__ import annotations

import copy
import hashlib
import math
import os
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import audio_qc_worker  # noqa: E402
from audio_qc_judges import JudgeRegistryError, load_registry  # noqa: E402
from lib.qc_pipeline import panel_engines  # noqa: E402

WEIGHTED = {
    "parakeet-mlx": "asr.parakeet-tdt-0.6b-v3@1",
    "funasr-paraformer": "asr.paraformer-zh@1",
    "qwen3-asr-mlx": "asr.qwen3-asr-1.7b@1",
    "qwen3-aligner-mlx": "align.qwen3-forcedaligner-0.6b@1",
    "speechbrain-lid": "lid.voxlingua107-ecapa@1",
    "wespeaker-onnx": "speaker.campplus-voxceleb@1",
    "audiobox-aesthetics": "quality.audiobox-aesthetics@1",
    "dnsmos-onnx": "quality.dnsmos-p835@1",
}
# Judges that share an engine with a WEIGHTED one.
ALSO_WEIGHTED = (("wespeaker-onnx", "speaker.resnet293-voxceleb@1"),)
DNSMOS = "quality.dnsmos-p835@1"
PYIN = "pitch.pyin@1"
WHISPER = "asr.whisper-large-v3@1"
SENSEVOICE = "asr.sensevoice-small-f16@1"


def _pin(content: bytes, *, large: bool, content_sha256: bool = False) -> dict:
    if large:
        return {"lfsSHA256": hashlib.sha256(content).hexdigest(), "size": len(content)}
    pin = {"gitBlobID": hashlib.sha1(b"blob %d\0" % len(content) + content).hexdigest(), "size": len(content)}
    if content_sha256:
        pin["sha256"] = hashlib.sha256(content).hexdigest()
    return pin


class FakeBackend:
    """Records its construction; returns a result that names the row."""

    built: list[tuple] = []

    def __init__(self, snapshot, config, threads) -> None:
        FakeBackend.built.append((snapshot, config.get("judge"), threads))
        self.warmed = False

    def warm(self) -> None:
        self.warmed = True

    def analyze(self, audio, row):
        if row.get("language") == "boom":
            raise RuntimeError("a row-level library failure")
        return {"samples": len(audio), "language": row.get("language")}


class PanelEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.registry = copy.deepcopy(load_registry())
        FakeBackend.built = []
        self.pcm = self.root / "take.pcm"
        self.pcm.write_bytes(b"\x00\x10" * 1600)
        self.patches = [mock.patch("audio_qc_judges.load_registry", side_effect=lambda: self.registry),
                        mock.patch.object(panel_engines, "installed_packages", return_value=["numpy", "pip"])]
        for patch in self.patches:
            patch.start()

    def tearDown(self) -> None:
        for patch in self.patches:
            patch.stop()
        self.temporary.cleanup()

    def _snapshot(self, judge_id: str) -> tuple[Path, dict]:
        """Fixture files under the judge's pinned revision, and the registry pins them."""
        pins = self.registry["judges"][judge_id]["pins"]
        files = {name: f"fixture {judge_id} {name}".encode() * (50 if "size" in pin and pin["size"] > 10**6 else 1)
                 for name, pin in pins["files"].items()}
        snapshot = self.root / judge_id.replace("@", "-") / pins["revision"]
        snapshot.mkdir(parents=True)
        for name, content in files.items():
            (snapshot / name).parent.mkdir(parents=True, exist_ok=True)
            (snapshot / name).write_bytes(content)
        pins["files"] = {name: _pin(content, large="lfsSHA256" in pins["files"][name],
                                    content_sha256="sha256" in pins["files"][name])
                         for name, content in files.items()}
        config = {"judge": judge_id, "repository": pins["repository"], "revision": pins["revision"],
                  "snapshot": str(snapshot)}
        return snapshot, config

    def _job(self, engine: str, config: dict, threads: int = 2, rows=None) -> dict:
        return {"kind": audio_qc_worker.JOB_KIND, "protocol": audio_qc_worker.PROTOCOL, "threads": threads,
                "engine": engine, "engineConfig": config,
                "rows": rows or [{"id": "a", "pcmPath": str(self.pcm), "language": "en"},
                                 {"id": "missing", "pcmPath": str(self.root / "absent.pcm"), "language": "en"},
                                 {"id": "boom", "pcmPath": str(self.pcm), "language": "boom"}]}

    def _run(self, job: dict) -> list[dict]:
        emitted: list[dict] = []
        audio_qc_worker.run(job, emit=emitted.append, environment=audio_qc_worker.thread_environment(job["threads"]))
        return emitted

    def test_every_weighted_engine_verifies_its_snapshot_before_it_loads(self) -> None:
        for engine, judge_id in (*WEIGHTED.items(), *ALSO_WEIGHTED):
            with self.subTest(engine=engine), mock.patch.dict(panel_engines.BACKENDS, {engine: FakeBackend}):
                FakeBackend.built = []
                snapshot, config = self._snapshot(judge_id)
                threads = self.registry["judges"][judge_id]["execution"]["threads"]
                emitted = self._run(self._job(engine, config, threads))
                self.assertEqual(FakeBackend.built, [(snapshot, judge_id, threads)])
                self.assertEqual([item["kind"] for item in emitted], ["ready", "row", "row-error", "row-error", "done"])
                self.assertEqual(emitted[0]["engine"], engine)
                self.assertEqual(emitted[0]["verifiedFiles"], len(self.registry["judges"][judge_id]["pins"]["files"]))
                self.assertEqual(emitted[1]["result"]["samples"], 1600)
                self.assertEqual(emitted[1]["result"]["decodedSampleCount"], 1600)
                self.assertIn("wallSeconds", emitted[1]["result"])
                # One altered byte in any pinned file: nothing loads.
                FakeBackend.built = []
                victim = sorted(path for path in snapshot.rglob("*") if path.is_file())[0]
                victim.write_bytes(victim.read_bytes()[:-1] + b"#")
                with self.assertRaisesRegex(JudgeRegistryError, "differs from its registry pin"):
                    self._run(self._job(engine, config, threads))
                self.assertEqual(FakeBackend.built, [])

    def test_the_load_gate_refuses_before_any_load(self) -> None:
        engine, judge_id = "parakeet-mlx", WEIGHTED["parakeet-mlx"]
        _snapshot, config = self._snapshot(judge_id)
        with mock.patch.dict(panel_engines.BACKENDS, {engine: FakeBackend}):
            with mock.patch.object(panel_engines, "installed_packages", return_value=["numpy", "soynlp"]):
                with self.assertRaisesRegex(JudgeRegistryError, "package soynlp is excluded"):
                    self._run(self._job(engine, config))
            with self.assertRaisesRegex(panel_engines.PanelEngineError, "not registered to run under"):
                self._run(self._job(engine, {**config, "judge": WEIGHTED["funasr-paraformer"]}))
            with self.assertRaisesRegex(JudgeRegistryError, "another model or revision"):
                self._run(self._job(engine, {**config, "revision": "1" * 40}))
            self.registry["judges"][judge_id]["status"] = "quarantined"
            with self.assertRaisesRegex(JudgeRegistryError, "quarantined"):
                self._run(self._job(engine, config))
            with self.assertRaisesRegex(panel_engines.PanelEngineError, "lacks snapshot"):
                self._run(self._job(engine, {key: value for key, value in config.items() if key != "snapshot"}))
        self.assertEqual(FakeBackend.built, [])

    def test_pyin_runs_without_weights_but_not_without_the_gate(self) -> None:
        config = {"judge": PYIN, "configuration": self.registry["judges"][PYIN]["configuration"]}
        with mock.patch.dict(panel_engines.BACKENDS, {"pyin-librosa": FakeBackend}):
            emitted = self._run(self._job("pyin-librosa", config, threads=1))
            self.assertEqual(FakeBackend.built, [(None, PYIN, 1)])
            self.assertEqual(emitted[0]["verifiedFiles"], 0)
            with mock.patch.object(panel_engines, "installed_packages", return_value=["librosa", "pykakasi"]):
                with self.assertRaisesRegex(JudgeRegistryError, "package pykakasi is excluded"):
                    self._run(self._job("pyin-librosa", config, threads=1))
        self.assertEqual(len(FakeBackend.built), 1)

    def test_whisper_large_v3_uses_the_panel_decode_from_its_verified_snapshot(self) -> None:
        loads = []

        class FakeRecognizer:
            def __init__(self, model_dir, decode, *, warmup_language=None):
                loads.append((model_dir, warmup_language))
                self.decode = decode
                self.model_load_seconds, self.warmup_seconds = 2.5, 0.5

            def _options(self, language):
                return {"language": language, "temperature": 0.0}

            def recognize(self, audio, language):
                return {"transcript": "fixture", "language": language, "options": self._options(language),
                        "decodedSampleCount": len(audio), "sampleRateHz": 16000, "wallSeconds": 0.1}

        snapshot, config = self._snapshot(WHISPER)
        config["decodeOptions"] = self.registry["judges"][WHISPER]["decodeOptions"]
        with mock.patch("independent_asr_worker.Recognizer", FakeRecognizer):
            emitted = self._run(self._job("whisper-mlx", config))
        self.assertEqual(loads, [(snapshot, "en")])
        self.assertEqual(emitted[0]["modelLoadSeconds"], 2.5)
        options = emitted[1]["result"]["options"]
        self.assertIsNone(options["no_speech_threshold"])
        self.assertIsNone(options["initial_prompt"])
        self.assertEqual(emitted[1]["result"]["decodedSampleCount"], 1600)

    def test_sensevoice_runs_its_pinned_binary_on_the_pinned_gguf(self) -> None:
        snapshot, config = self._snapshot(SENSEVOICE)
        binary = self.root / "llama-funasr-sensevoice"
        binary.write_text('#!/bin/sh\necho "<|ja|><|NEUTRAL|><|Speech|><|woitn|>$2"\n', encoding="utf-8")
        binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
        acquisition = self.registry["acquisition"]
        artifact = acquisition["artifacts"][acquisition["runtimes"]["sensevoice-llamacpp"]["artifact"]]
        artifact["members"] = {"llama-funasr-sensevoice": hashlib.sha256(binary.read_bytes()).hexdigest()}
        config["binary"] = str(binary)
        emitted = self._run(self._job("sensevoice-llamacpp", config, rows=[
            {"id": "a", "pcmPath": str(self.pcm), "language": "ja"}]))
        self.assertEqual(emitted[0]["engine"], "sensevoice-llamacpp")
        self.assertEqual(emitted[0]["verifiedFiles"], 2)
        self.assertIn(str(snapshot / "sensevoice-small-f16.gguf"), emitted[1]["result"]["stdout"])
        binary.write_text("#!/bin/sh\necho swapped\n", encoding="utf-8")
        with self.assertRaisesRegex(panel_engines.PanelEngineError, "differs from its pinned digest"):
            self._run(self._job("sensevoice-llamacpp", config))

    def test_every_orchestrated_registry_judge_has_a_worker_engine(self) -> None:
        judges = self.registry["judges"]
        for judge_id, judge in judges.items():
            for block in ("execution", "plannedExecution"):
                execution = judge.get(block) or {}
                if execution.get("orchestrated") and execution.get("engine") != "in-process":
                    with self.subTest(judge=judge_id):
                        self.assertIn(execution["engine"], audio_qc_worker.ENGINES)
        self.assertEqual(set(audio_qc_worker.PANEL_ENGINES), set(panel_engines.ENGINE_NAMES))

    def test_alignment_units_and_json_safe_arrays(self) -> None:
        self.assertEqual(panel_engines.alignment_units("안녕 하세요 여러분", "ko"), ["안녕", "하세요", "여러분"])
        self.assertEqual(panel_engines.alignment_units("你好 世界", "zh"), ["你", "好", "世", "界"])
        self.assertEqual(panel_engines.alignment_units("Bonjour le monde", "fr"), ["Bonjour", "le", "monde"])
        self.assertEqual(panel_engines._finite([1.0, math.nan, 2.5]), [1.0, None, 2.5])

    def test_the_aligner_reads_dict_and_attribute_intervals(self) -> None:
        """mlx-audio's aligner yields dict segments (text/start/end) and object items (start_time/end_time)."""
        core = SimpleNamespace(array=lambda audio: audio)
        shapes = {
            "dict segments": [{"text": "Bonjour", "start": 0.0, "end": 0.42}, {"text": "monde", "start": 0.5, "end": 0.9}],
            "dict items": [{"text": "Bonjour", "start_time": 0.0, "end_time": 0.42},
                           {"text": "monde", "start_time": 0.5, "end_time": 0.9}],
            "attribute segments": [SimpleNamespace(text="Bonjour", start=0.0, end=0.42),
                                   SimpleNamespace(text="monde", start=0.5, end=0.9)],
            "attribute items": [SimpleNamespace(text="Bonjour", start_time=0.0, end_time=0.42),
                                SimpleNamespace(text="monde", start_time=0.5, end_time=0.9)],
        }
        expected = [{"unit": "Bonjour", "start": 0.0, "end": 0.42}, {"unit": "monde", "start": 0.5, "end": 0.9}]
        row = {"referenceText": "Bonjour monde", "language": "fr"}
        for name, segments in shapes.items():
            backend = object.__new__(panel_engines.Qwen3AlignerBackend)
            backend.model = SimpleNamespace(generate=lambda audio, text, language, segments=segments:
                                            SimpleNamespace(segments=segments))
            with self.subTest(shape=name), mock.patch.dict(sys.modules, {"mlx": SimpleNamespace(core=core),
                                                                         "mlx.core": core}):
                result = backend.analyze(np.zeros(16, dtype=np.float32), row)
                self.assertEqual(result["intervals"], expected)
                self.assertEqual(result["units"], ["Bonjour", "monde"])
        for broken in ({"text": "x", "start": 0.1}, SimpleNamespace(text="x", start=None, end=0.2),
                       {"text": "x", "start": "soon", "end": 0.2}, {"text": "x", "start": object(), "end": 0.2}):
            with self.subTest(broken=repr(broken)), self.assertRaises(ValueError):
                panel_engines.aligned_interval(broken)


    def test_every_engine_runs_offline_with_empty_per_run_caches(self) -> None:
        """A model cached anywhere on the host can never load: every cache points into an empty run directory."""
        shared = self.root / "shared-cache"
        (shared / "hub/models--fixture").mkdir(parents=True)
        seen: dict[str, str | None] = {}
        watched = (*panel_engines.CACHE_VARIABLES, "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")

        class CacheProbe(FakeBackend):
            def __init__(self, snapshot, config, threads) -> None:
                super().__init__(snapshot, config, threads)
                seen.update({name: os.environ.get(name) for name in watched})

        engine, judge_id = "wespeaker-onnx", WEIGHTED["wespeaker-onnx"]
        _snapshot, config = self._snapshot(judge_id)
        inherited = {name: str(shared) for name in panel_engines.CACHE_VARIABLES}
        with mock.patch.dict(os.environ, {**inherited, "HF_HUB_OFFLINE": "0"}), \
                mock.patch.dict(panel_engines.BACKENDS, {engine: CacheProbe}):
            self._run(self._job(engine, config))
        self.assertEqual((seen["HF_HUB_OFFLINE"], seen["TRANSFORMERS_OFFLINE"]), ("1", "1"))
        caches = [Path(str(seen[name])) for name in panel_engines.CACHE_VARIABLES]
        self.assertEqual(len(set(caches)), len(caches))
        run_root = caches[0].parent
        self.assertTrue(run_root.name.startswith("vocello-audio-qc-empty-cache-"))
        for cache in caches:
            with self.subTest(cache=cache.name):
                self.assertEqual(cache.parent, run_root)
                self.assertNotEqual(cache, shared)
                self.assertEqual(list(cache.iterdir()), [])

    def test_a_symbolic_link_inside_a_panel_snapshot_refuses_the_load(self) -> None:
        engine, judge_id = "wespeaker-onnx", WEIGHTED["wespeaker-onnx"]
        snapshot, config = self._snapshot(judge_id)
        victim = snapshot / "config.yaml"
        outside = self.root / "outside-config.yaml"
        outside.write_bytes(victim.read_bytes())
        victim.unlink()
        victim.symlink_to(outside)
        with mock.patch.dict(panel_engines.BACKENDS, {engine: FakeBackend}):
            with self.assertRaisesRegex(JudgeRegistryError, r"symbolic link \(config\.yaml\)"):
                self._run(self._job(engine, config))
        self.assertEqual(FakeBackend.built, [])


class DnsmosTests(unittest.TestCase):
    """The DNSMOS P.835 port: windowing, calibration and scoring against hand-computed values (no model)."""

    SIG, BAK, OVRL = (panel_engines.DNSMOS_POLYNOMIALS[axis] for axis in ("SIG", "BAK", "OVRL"))

    def test_windows_follow_the_reference_arithmetic(self) -> None:
        windows = panel_engines.dnsmos_windows
        # One window is int(9.01 * 16000) = 144,160 samples; a 3 s take doubles twice, to 192,000.
        self.assertEqual(windows(48_000), (192_000, 3, [(0, 144_160), (16_000, 160_160), (32_000, 176_160)]))
        self.assertEqual(windows(144_160), (144_160, 1, [(0, 144_160)]))
        self.assertEqual(windows(152_000), (152_000, 1, [(0, 144_160)]))
        # A 20 s take has int(20 - 9.01) + 1 = 11 hops, but int((idx + 9.01) * 16000) truncates to one
        # sample short for idx 7-10 (16.009999999999998 * 16000 = 256159.99999999997), so the reference
        # skips those windows and scores the ones starting at 0-6 s.
        length, hops, scored = windows(320_000)
        self.assertEqual((length, hops), (320_000, 11))
        self.assertEqual([start for start, _end in scored], [0, 16_000, 32_000, 48_000, 64_000, 80_000, 96_000])
        self.assertTrue(all(end - start == 144_160 for start, end in scored))
        # One sample tiles to 2**18 = 262,144 samples: int(16 - 9.01) + 1 = 7 hops.
        self.assertEqual(windows(1)[:2], (262_144, 7))
        with self.assertRaises(ValueError):
            windows(0)

    def test_the_calibration_is_the_non_personalized_polynomial_mapping(self) -> None:
        calibrate = panel_engines.dnsmos_calibrate
        # By hand: SIG(3) = -0.08397278 * 9 + 1.22083953 * 3 + 0.0052439 = 2.91200747, and so on.
        for raw, expected in ((3.0, {"SIG": 2.91200747, "BAK": 3.24640004, "OVRL": 2.78345392}),
                              (1.0, {"SIG": 1.14211065, "BAK": 1.0814408, "OVRL": 1.0938272}),
                              (0.0, {"SIG": 0.0052439, "BAK": -0.39604546, "OVRL": 0.04602535}),
                              (2.0, {"SIG": 2.11103184, "BAK": 2.2955893, "OVRL": 2.00630339})):
            values = calibrate(raw, raw, raw)
            for axis, value in expected.items():
                with self.subTest(raw=raw, axis=axis):
                    self.assertAlmostEqual(values[axis], value, places=8)
        # The same doubles numpy's poly1d produces for the models' float32 outputs.
        for raw in (np.float32(3.3712), np.float32(1.25), np.float32(4.8)):
            for coefficients in (self.SIG, self.BAK, self.OVRL):
                self.assertEqual(panel_engines.dnsmos_polynomial(coefficients, raw),
                                 float(np.poly1d(coefficients)(raw)))

    def test_the_scorer_feeds_each_model_its_reference_input_and_averages_the_windows(self) -> None:
        primary_inputs, p808_inputs, mel_inputs = [], [], []

        def primary(features):
            primary_inputs.append(features)
            return [np.array([[float(len(primary_inputs)), 2.0, 3.0]], dtype=np.float32)]

        def p808(features):
            p808_inputs.append(features)
            return [np.array([[3.5]], dtype=np.float32)]

        def melspec(audio):
            mel_inputs.append(audio)
            return np.zeros((900, 120))

        audio = ((np.arange(48_000) % 200) - 100).astype(np.float32) / 32768.0
        result = panel_engines.DnsmosScorer(primary, p808, melspec).score(audio)
        self.assertEqual((result["numHops"], result["windowsScored"], result["lenSeconds"]), (3, 3, 3.0))
        self.assertEqual([window["startSeconds"] for window in result["windows"]], [0.0, 1.0, 2.0])
        # The P.835 model reads the 9.01 s window as float32; the P.808 features drop its last 160 samples.
        self.assertEqual((primary_inputs[0].shape, primary_inputs[0].dtype), ((1, 144_160), np.float32))
        self.assertEqual((p808_inputs[0].shape, p808_inputs[0].dtype), ((1, 900, 120), np.float32))
        self.assertEqual((len(mel_inputs[0]), mel_inputs[0].dtype), (144_000, np.float64))
        np.testing.assert_array_equal(primary_inputs[1][0], np.tile(audio, 4)[16_000:160_160])
        # Raw SIG 1, 2, 3 average to 2; the calibrated SIG is the mean of each window's calibrated value.
        self.assertAlmostEqual(result["raw"]["SIG"], 2.0)
        self.assertAlmostEqual(result["SIG"], (1.14211065 + 2.11103184 + 2.91200747) / 3, places=8)
        self.assertAlmostEqual(result["BAK"], 2.2955893, places=8)
        self.assertAlmostEqual(result["OVRL"], 2.78345392, places=8)
        self.assertAlmostEqual(result["P808_MOS"], 3.5)
        with self.assertRaises(ValueError):
            panel_engines.DnsmosScorer(primary, p808, melspec).score(np.zeros(0, dtype=np.float32))

    def test_the_backend_wires_both_sessions_and_the_reference_mel_features(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        snapshot = Path(temporary.name) / "591184a9fcb2cbdec02520fed81a32bbbf9d73ff"
        (snapshot / "DNSMOS/DNSMOS").mkdir(parents=True)
        for name in ("sig_bak_ovr.onnx", "model_v8.onnx"):
            (snapshot / "DNSMOS/DNSMOS" / name).write_bytes(b"fixture")
        configuration = copy.deepcopy(load_registry()["judges"][DNSMOS]["configuration"])
        sessions = []

        class FakeSession:
            def __init__(self, path, sess_options=None, providers=None) -> None:
                self.path, self.options, self.providers, self.feeds = Path(path), sess_options, providers, []
                sessions.append(self)

            def run(self, outputs, feeds):
                self.feeds.append(feeds)
                if self.path.name == "model_v8.onnx":
                    return [np.array([[3.25]], dtype=np.float32)]
                return [np.array([[3.0, 3.0, 3.0]], dtype=np.float32)]

        mel_calls = []

        def melspectrogram(**kwargs):
            mel_calls.append(kwargs)
            return np.ones((120, 900))

        modules = {
            "onnxruntime": SimpleNamespace(SessionOptions=SimpleNamespace, InferenceSession=FakeSession,
                                           ExecutionMode=SimpleNamespace(ORT_SEQUENTIAL="sequential")),
            "librosa": SimpleNamespace(feature=SimpleNamespace(melspectrogram=melspectrogram),
                                       power_to_db=lambda spectrum, ref: np.zeros_like(spectrum)),
        }
        config = {"judge": DNSMOS, "configuration": configuration}
        with mock.patch.dict(sys.modules, modules):
            result = panel_engines.DnsmosBackend(snapshot, config, 1).analyze(np.zeros(48_000, dtype=np.float32), {})
            for override in ({"primaryModel": "../escape.onnx"}, {"p808Model": "DNSMOS/DNSMOS/absent.onnx"},
                             {"personalized": True}, {"sampleRateHz": 48_000}):
                with self.subTest(override=override), self.assertRaises(panel_engines.PanelEngineError):
                    panel_engines.DnsmosBackend(snapshot, {**config, "configuration": {**configuration, **override}}, 1)
        self.assertEqual([session.path.name for session in sessions[:2]], ["sig_bak_ovr.onnx", "model_v8.onnx"])
        for session in sessions[:2]:
            self.assertEqual(session.providers, ["CPUExecutionProvider"])
            self.assertEqual((session.options.intra_op_num_threads, session.options.inter_op_num_threads), (1, 1))
            self.assertEqual(set(session.feeds[0]), {"input_1"})
        self.assertEqual(sessions[1].feeds[0]["input_1"].shape, (1, 900, 120))
        kwargs = mel_calls[0]
        self.assertEqual({key: kwargs[key] for key in ("sr", "n_fft", "hop_length", "n_mels", "pad_mode")},
                         {"sr": 16_000, "n_fft": 321, "hop_length": 160, "n_mels": 120, "pad_mode": "reflect"})
        self.assertEqual(len(kwargs["y"]), 144_000)
        self.assertEqual((result["numHops"], result["P808_MOS"]), (3, 3.25))
        self.assertAlmostEqual(result["OVRL"], 2.78345392, places=7)


if __name__ == "__main__":
    unittest.main()
