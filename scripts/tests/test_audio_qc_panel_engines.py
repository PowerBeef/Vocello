#!/usr/bin/env python3
"""The AQ-06 panel engines: the registry's load gate and every file's digest before any load, with fake models."""

from __future__ import annotations

import copy
import hashlib
import math
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock

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
}
PYIN = "pitch.pyin@1"
WHISPER = "asr.whisper-large-v3@1"
SENSEVOICE = "asr.sensevoice-small-f16@1"


def _pin(content: bytes, *, large: bool) -> dict:
    if large:
        return {"lfsSHA256": hashlib.sha256(content).hexdigest(), "size": len(content)}
    return {"gitBlobID": hashlib.sha1(b"blob %d\0" % len(content) + content).hexdigest(), "size": len(content)}


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
        pins["files"] = {name: _pin(content, large="lfsSHA256" in pins["files"][name])
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
        for engine, judge_id in WEIGHTED.items():
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
                victim = sorted(snapshot.iterdir())[0]
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


if __name__ == "__main__":
    unittest.main()
