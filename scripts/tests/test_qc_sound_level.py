"""QC v2 sound-level transcript scoring and the Japanese reading before espeak-ng.

The script and each ASR transcript go through the same G2P (a fake espeak-ng engine here) and are
compared phone by phone, so a homophone ("la voie" heard as "la voix", both /vwa/) is no error
while a real substitution or a lost word is. Japanese is read into kana first; without the reader
Japanese abstains instead of comparing espeak-ng's "Chinese letter" readings of kanji.
"""

from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import unittest
import wave
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from qc import detectors, features, lanes, phones, runtime, store  # noqa: E402
from qc.runners import espeak_g2p  # noqa: E402
from qc.store import Layout  # noqa: E402

G2P_ID = "g2p.espeak-ng"
IPA = {
    "la voie": "la vwˈa", "la voix": "la vwˈa", "le chat dort": "lə ʃˈa dˈɔʁ", "le rat dort": "lə ʁˈa dˈɔʁ",
    "le dort": "lə dˈɔʁ", "il est là": "il ɛ lˈa", "il et là": "il e lˈa",
    "トーキョー ニ イキ マス": "tˈo̞o̞kʲo̞o̞ nˈi ˈiki mˈäsɯᵝ",
}


class FakeEngine:
    name = "fake-espeak"
    version = "test"

    def __init__(self, table: dict[str, str] = IPA) -> None:
        self.table = table
        self.texts: list[str] = []

    def phonemize(self, text: str, voice: str) -> str:
        self.texts.append(text)
        if text not in self.table and " " not in text:
            return text  # a French word read alone, for its liaison check
        return self.table[text]


class StubReader:
    name = espeak_g2p.JAPANESE_READER

    def read(self, text: str) -> str:
        return {"東京に行きます": "トーキョー ニ イキ マス"}[text]


def result(outputs: dict) -> dict:
    return {"schema": store.RESULT_SCHEMA, "outputs": outputs}


class PhoneticErrorTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.layout = Layout(Path(self.directory.name))
        self.cache = self.layout.results_dir(G2P_ID)
        self.engine = FakeEngine()

    def tearDown(self):
        self.directory.cleanup()

    def cached(self, *texts: str, language: str = "french") -> None:
        for text in texts:
            espeak_g2p.g2p_record(text, language, cache_dir=self.cache, engine=self.engine)

    def score(self, script: str, heard_a: str | None, heard_b: str | None, language: str = "french") -> dict:
        take = {"token": "t", "language": language, "text": script}
        results = {}
        for role, text in (("asrA", heard_a), ("asrB", heard_b)):
            if text is not None:
                results[role] = result({"text": text, "language": language})
        return features.asr_phonetic_features(take, results, self.layout, {"g2p": G2P_ID})

    def test_a_homophone_is_no_error_but_a_word_error(self):
        self.cached("la voie", "la voix")
        values = self.score("la voie", "la voie", "la voix")
        self.assertEqual(values["asr.phonetic_error_a"]["value"], 0.0)
        self.assertEqual(values["asr.phonetic_error_b"]["value"], 0.0)
        self.assertEqual(values["asr.phonetic_error_min"]["value"], 0.0)
        words = features.asr_features({"language": "french", "text": "la voie"},
                                      {"asrA": result({"text": "la voix"}), "asrB": result({"text": "la voix"})})
        self.assertEqual(features.transcript_distance("la voie", "la voix", "french"), 0.5)  # one word in two
        self.assertEqual(words["asr.edit_rate_min"]["value"], 0.0)  # a substitution, neither inserted nor deleted

    def test_a_real_substitution_and_a_lost_word_count(self):
        self.cached("le chat dort", "le rat dort", "le dort")
        values = self.score("le chat dort", "le rat dort", "le dort")
        self.assertAlmostEqual(values["asr.phonetic_error_a"]["value"], 1 / 7, places=5)  # /ʃ/ heard as /ʁ/
        self.assertAlmostEqual(values["asr.phonetic_error_b"]["value"], 2 / 7, places=5)  # /ʃa/ lost
        self.assertAlmostEqual(values["asr.phonetic_error_min"]["value"], 1 / 7, places=5)  # both must hear it

    def test_a_near_identical_vowel_is_no_error(self):
        # Under PanPhon, /e/ for /ɛ/ is within the phone tools' near-identity scale.
        directory = self.layout.model_dir(G2P_ID) / "panphon/data"
        directory.mkdir(parents=True)
        (directory / "ipa_all.csv").write_text(
            "ipa,syl,son,cons,voi,lab,cor,hi,lo\n"
            "i,+,+,-,+,-,-,+,-\nl,-,+,+,+,-,+,-,-\na,+,+,-,+,-,-,-,+\n"
            "e,+,+,-,+,-,-,-,-\nɛ,+,+,-,+,-,-,-,0\n", encoding="utf-8")
        (directory / "feature_weights.csv").write_text("syl,son,cons,voi,lab,cor,hi,lo\n1,1,1,1,1,1,1,0.1\n",
                                                       encoding="utf-8")
        self.assertEqual(phones.default_distance(self.layout.model_dir(G2P_ID))[1], "panphon")
        self.cached("il est là", "il et là")
        self.assertEqual(self.score("il est là", "il et là", "il est là")["asr.phonetic_error_a"]["value"], 0.0)

    def test_needs_both_families_and_their_transcripts_phones(self):
        self.cached("la voie")
        one = self.score("la voie", "la voie", None)
        self.assertEqual(one["asr.phonetic_error_a"]["value"], 0.0)
        self.assertIsNone(one["asr.phonetic_error_min"]["value"])
        uncached = self.score("la voie", "la voie", "la voix")  # "la voix" was never read by the G2P job
        self.assertIsNone(uncached["asr.phonetic_error_b"]["value"])
        self.assertIsNone(uncached["asr.phonetic_error_min"]["value"])
        silent = self.score("la voie", "", "la voie")
        self.assertEqual(silent["asr.phonetic_error_a"]["value"], 1.0)  # heard nothing: every phone lost
        self.assertIsNone(self.score("la voix", "la voie", "la voie")["asr.phonetic_error_min"]["value"])  # no script

    def test_transcripts_the_g2p_job_still_has_to_read(self):
        self.cached("la voie")
        takes = [{"token": "t1", "audio": "a.wav", "language": "french", "text": "la voie"},
                 {"token": "t2", "audio": "b.wav", "language": "french", "text": "la voie"},
                 {"token": "t3", "audio": "c.wav", "language": "klingon", "text": "x"}]
        results = {"t1": {"asrA": result({"text": "la voie"}), "asrB": result({"text": " la voix "})},
                   "t2": {"asrA": result({"text": "la voix"}), "asrB": {"error": "timeout"}},
                   "t3": {"asrA": result({"text": "y"})}}
        pending = features.transcript_g2p_takes(takes, results, self.layout, {"g2p": G2P_ID})
        self.assertEqual([item["text"] for item in pending], ["la voix"])  # cached, repeated and unsupported skipped
        self.assertEqual(len(pending[0]["audioSHA256"]), 64)
        self.assertNotIn(pending[0]["audioSHA256"], {"a" * 64})
        self.cached("la voix")
        self.assertEqual(features.transcript_g2p_takes(takes, results, self.layout, {"g2p": G2P_ID}), [])


class JapaneseReadingTests(unittest.TestCase):
    def test_japanese_is_read_into_kana_before_espeak(self):
        engine = FakeEngine()
        with tempfile.TemporaryDirectory() as cache:
            record = espeak_g2p.g2p_record("東京に行きます", "japanese", cache_dir=cache, engine=engine,
                                           reader=StubReader())
            self.assertEqual(engine.texts, ["トーキョー ニ イキ マス"])
            self.assertEqual(record["reading"], "トーキョー ニ イキ マス")
            self.assertEqual(record["reader"], espeak_g2p.JAPANESE_READER)
            self.assertEqual(len(record["words"]), 4)
            # The host reads it back without the reader: the key names the pinned reader.
            self.assertEqual(phones.g2p("東京に行きます", "japanese", cache_dir=cache, compute=False), record["phones"])
            self.assertEqual(espeak_g2p.g2p_espeak("東京に行きます", "japanese", engine=engine, reader=StubReader()),
                             record["phones"])
        key = espeak_g2p.g2p_key("東京", "japanese")
        with mock.patch.object(espeak_g2p, "JAPANESE_READER", "fugashi-2+unidic-lite-2"):
            self.assertNotEqual(espeak_g2p.g2p_key("東京", "japanese"), key)
            self.assertEqual(espeak_g2p.g2p_key("la voie", "french"), espeak_g2p.g2p_key("la voie", "french"))

    def test_without_the_reader_japanese_abstains(self):
        missing = mock.patch.object(espeak_g2p, "default_reader",
                                    side_effect=phones.G2PUnavailable("Japanese G2P needs fugashi"))
        with tempfile.TemporaryDirectory() as cache, missing:
            with self.assertRaises(phones.G2PUnavailable):
                espeak_g2p.g2p_record("東京に行きます", "japanese", cache_dir=cache, engine=FakeEngine())
            job = {"model": G2P_ID, "outputDir": cache, "runnerSHA256": "f" * 64, "options": {}, "takes": [
                {"token": "ja", "audio": "x.wav", "audioSHA256": "a" * 64, "language": "japanese",
                 "text": "東京に行きます", "variantKey": None},
                {"token": "fr", "audio": "y.wav", "audioSHA256": "b" * 64, "language": "french",
                 "text": "la voie", "variantKey": None}]}
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as stderr:
                self.assertEqual(espeak_g2p.run_g2p_job(job, engine=FakeEngine()), 1)
            self.assertIn("Japanese abstains", stderr.getvalue())
            self.assertFalse((Path(cache) / f"{'a' * 64}.json").exists())  # retried by the next run
            self.assertIn("outputs", json.loads((Path(cache) / f"{'b' * 64}.json").read_text(encoding="utf-8")))
            # So the host's Japanese phonetic features are unavailable, not scored against kanji names.
            layout = Layout(Path(cache))
            take = {"token": "t", "language": "japanese", "text": "東京に行きます"}
            asr = {"asrA": result({"text": "東京に行きます"}), "asrB": result({"text": "東京に行きます"})}
            values = features.asr_phonetic_features(take, asr, layout, {"g2p": G2P_ID})
            self.assertTrue(all(value["value"] is None for value in values.values()))

    def test_the_pinned_reader_when_installed(self):
        try:
            reader = espeak_g2p.default_reader()
        except phones.G2PUnavailable:
            self.skipTest("fugashi and unidic-lite are not installed in this python (the onnx runtime has them)")
        self.assertEqual(reader.read("東京に行きます"), "トーキョー ニ イキ マス")
        self.assertEqual(reader.read("今日は"), "キョー ワ")


class TranscriptLaneTests(unittest.TestCase):
    """`qc.py run` reads the transcripts with a second G2P pass after the ASR roles."""

    TRANSCRIPTS = {"fr-0001--aiden": ("la voie", "la voix"), "fr-0002--ryan": ("le rat dort", "le rat dort")}
    SCRIPTS = {"fr-0001--aiden": "la voie", "fr-0002--ryan": "le chat dort"}

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.layout = Layout(self.root)
        self.layout.config.mkdir(parents=True)
        for name in ("detectors.json", "protocol.json"):
            shutil.copyfile(ROOT / "config/qc" / name, self.layout.config / name)
        runners = self.root / "scripts/qc/runners"
        runners.mkdir(parents=True)
        source = {"host": "huggingface", "repo": "a/b", "revision": "0" * 40,
                  "files": {"w": {"sha256": "0" * 64, "bytes": 1}}}
        registry = []
        for model_id, kind, runner in (("asr.qwen3-asr-1.7b", "asr", "stub_asr"), ("asr.whisper-large-v3", "asr", "stub_asr"),
                                       (G2P_ID, "g2p", "stub_g2p")):
            (runners / f"{runner}.py").write_text("# stub\n")
            registry.append({"id": model_id, "kind": kind, "runner": f"qc.runners.{runner}", "runtime": "mlx",
                             "source": source, "license": "MIT", "memoryGB": 1, "languages": "any", "version": 1})
        self.layout.registry.write_text(json.dumps({"schemaVersion": 1, "models": registry}))
        takes = []
        rate = 16000
        tone = (0.1 * np.sin(2 * np.pi * 150 * np.arange(rate) / rate) * 32767).astype("<i2")
        for take_id, script in self.SCRIPTS.items():
            path = self.root / f"{take_id}.wav"
            with wave.open(str(path), "wb") as writer:
                writer.setnchannels(1)
                writer.setsampwidth(2)
                writer.setframerate(rate)
                writer.writeframes(tone.tobytes())
            takes.append({"takeID": take_id, "token": store.take_token("pool", take_id), "audio": str(path),
                          "audioSHA256": store.sha256_text(take_id), "language": "french", "text": script,
                          "mode": "custom", "voice": "v", "cell": "standard", "reference": None,
                          "referenceSHA256": None, "finishReason": "eos", "family": take_id.split("--")[0]})
        self.takes = {take["token"]: take for take in takes}
        self.manifest = self.root / "takes.json"
        self.manifest.write_text(json.dumps({"schema": store.TAKES_SCHEMA, "source": "pool", "takes": takes}))
        self.calls: list[tuple[str, list[str]]] = []

    def tearDown(self):
        self.directory.cleanup()

    def fake_runner(self, model, takes, options=None, *, layout, echo, **kwargs):
        identity = runtime.runner_identity(layout, model)
        self.calls.append((model["id"], [take.get("text") for take in takes]))
        output = layout.results_dir(model["id"])
        if model["kind"] == "g2p":
            job = {"model": model["id"], "outputDir": str(output), "runnerSHA256": identity, "options": {},
                   "takes": [dict(take, variantKey=None) for take in takes]}
            with redirect_stdout(io.StringIO()):
                espeak_g2p.run_g2p_job(job, engine=FakeEngine())
        else:
            family = 0 if model["id"] == "asr.qwen3-asr-1.7b" else 1
            for take in takes:
                text = self.TRANSCRIPTS[take["takeID"]][family] if "takeID" in take else take["text"]
                store.write_result(output, model=model["id"], runner_sha=identity, audio_sha=take["audioSHA256"],
                                   variant=None, duration_seconds=1.0, outputs={"text": text, "language": "French"})
        return runtime.RunnerReport(model=model["id"], runner_sha=identity)

    def run_lane(self):
        return lanes.run(self.layout, str(self.manifest), "pool", roles=["asrA", "asrB", "g2p"],
                         runner=self.fake_runner, echo=lambda line: None)

    def test_the_transcripts_are_read_after_the_asr_roles(self):
        directory = self.run_lane()
        order = [model_id for model_id, _ in self.calls]
        self.assertEqual(order, ["asr.qwen3-asr-1.7b", "asr.whisper-large-v3", G2P_ID, G2P_ID])
        self.assertEqual(sorted(self.calls[-1][1]), ["la voix", "le rat dort"])  # only texts not cached yet
        rows = {row["takeID"]: row["features"] for row in store.read_json(directory / "features.json")["takes"]}
        self.assertEqual(rows["fr-0001--aiden"]["asr.phonetic_error_min"]["value"], 0.0)
        self.assertAlmostEqual(rows["fr-0002--ryan"]["asr.phonetic_error_min"]["value"], 1 / 7, places=5)
        flags = store.read_json(directory / "flags.json")
        self.assertEqual(flags["models"]["g2pTranscripts"], {"texts": 2})
        self.assertIsNone(flags["norms"])
        self.calls.clear()
        self.run_lane()
        # The stub scores every role again, but no transcript is left for the second G2P pass.
        self.assertEqual([model_id for model_id, _ in self.calls], ["asr.qwen3-asr-1.7b", "asr.whisper-large-v3", G2P_ID])


class ContentDetectorTests(unittest.TestCase):
    def test_content_asr_reads_the_phonetic_error_first(self):
        config = json.loads((ROOT / "config/qc/detectors.json").read_text())
        detector = next(item for item in config["detectors"] if item["id"] == "content.asr")
        self.assertEqual([item["name"] for item in detector["features"]], ["asr.phonetic_error_min", "asr.edit_rate_min"])
        reading = {name for item in config["detectors"] for name in (feature["name"] for feature in item["features"])}
        self.assertTrue({"asr.phonetic_error_min", "asr.edit_rate_min"} <= reading)
        self.assertIn("g2p", detectors.detector_roles(detector))


if __name__ == "__main__":
    unittest.main()
