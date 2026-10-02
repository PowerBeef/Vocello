"""QC v2 per-language norms: `qc.py norms` on a synthetic pool, and the provisional rules reading them.

French takes pause about 0.25 s and Japanese takes about 0.5 s: the norms keep the two apart, hold
no take id, path or text, and the pause and rate rules compare each take with its own language's
percentiles (falling back to the fixed rules without norms).
"""

from __future__ import annotations

import importlib.util
import io
import json
import shutil
import sys
import tempfile
import unittest
import wave
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from qc import detectors, features, lanes, norms, store  # noqa: E402
from qc.runners import espeak_g2p  # noqa: E402
from qc.store import Layout  # noqa: E402

RATE = 16000
G2P_ID = "g2p.espeak-ng"
SCRIPT_IPA = {"le chat dort ici.": "lə ʃˈa dˈɔʁ isˈi", "東京に行きます": "tˈo̞o̞kʲo̞o̞ nˈi ˈiki mˈäsɯᵝ"}


class Engine:
    name, version = "fake-espeak", "test"

    def phonemize(self, text: str, voice: str) -> str:
        return SCRIPT_IPA[text if text in SCRIPT_IPA else "東京に行きます"]


class Reader:
    name = espeak_g2p.JAPANESE_READER

    def read(self, text: str) -> str:
        return "トーキョー ニ イキ マス"


def synth(pause: float, seed: int) -> np.ndarray:
    """Voiced syllables, one mid-sentence pause of `pause` seconds, and a 200 ms decay."""

    rng = np.random.default_rng(seed)

    def voiced(seconds: float, f0: float) -> np.ndarray:
        t = np.arange(int(seconds * RATE)) / RATE
        wave_ = sum(np.sin(2 * np.pi * f0 * k * t) / k for k in range(1, 8))
        return 0.05 * wave_ / np.sqrt(np.mean(wave_ ** 2))

    def silence(seconds: float) -> np.ndarray:
        return rng.normal(size=int(seconds * RATE)) * 1e-4

    def syllables(count: int) -> list[np.ndarray]:
        return [voiced(0.18, 110 + 15 * rng.random()) for _ in range(count)]

    last = voiced(0.3, 95)
    last[-int(0.2 * RATE):] *= np.linspace(1, 0, int(0.2 * RATE)) ** 3
    return np.concatenate([silence(0.1), *syllables(5), silence(pause), *syllables(5), last, silence(0.15)])


def write_wav(path: Path, samples: np.ndarray) -> str:
    pcm = np.clip(np.rint(samples * 32767), -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(RATE)
        writer.writeframes(pcm.tobytes())
    return str(path)


def norms_document(languages: dict) -> dict:
    return {"schema": norms.NORMS_SCHEMA, "file": "norms-v1.json", "languages": languages}


class PoolFixture(unittest.TestCase):
    PAUSES = {"french": (0.20, 0.22, 0.25, 0.28, 0.30), "japanese": (0.40, 0.45, 0.50, 0.55, 0.60)}

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.layout = Layout(self.root)
        self.layout.config.mkdir(parents=True)
        for name in ("detectors.json", "protocol.json"):
            shutil.copyfile(ROOT / "config/qc" / name, self.layout.config / name)
        runner = self.root / "scripts/qc/runners/stub_g2p.py"
        runner.parent.mkdir(parents=True)
        runner.write_text("# stub\n")
        # The G2P role: the script's phones come from its text cache, which the pool fills below.
        self.g2p = {"id": G2P_ID, "kind": "g2p", "runner": "qc.runners.stub_g2p", "runtime": "onnx",
                    "source": {"host": "huggingface", "repo": "a/b", "revision": "0" * 40,
                               "files": {"w": {"sha256": "0" * 64, "bytes": 1}}},
                    "license": "MIT", "memoryGB": 1, "languages": "any", "version": 1}
        self.layout.registry.write_text(json.dumps({"schemaVersion": 1, "models": [self.g2p]}))
        audio = self.root / "audio"
        audio.mkdir()
        self.takes = []
        for language, pauses in self.PAUSES.items():
            text = "le chat dort ici." if language == "french" else "東京に行きます"
            espeak_g2p.g2p_record(text, language, cache_dir=self.layout.results_dir(G2P_ID), engine=Engine(),
                                  reader=Reader())
            for index, pause in enumerate(pauses):
                take_id = f"{language[:2]}-{index:04d}--secret{index}"
                path = write_wav(audio / f"{take_id}.wav", synth(pause, index))
                take = {"takeID": take_id, "token": store.take_token("pool", take_id), "audio": path,
                        "audioSHA256": store.audio_sha256(path), "language": language, "text": text,
                        "mode": "custom", "voice": "v", "cell": "c", "reference": None, "referenceSHA256": None,
                        "finishReason": "eos", "family": take_id.split("--")[0]}
                self.takes.append(take)
        cut = dict(self.takes[0], takeID="fr-0099--cut", token="cut", finishReason="max-tokens")
        broken = dict(self.takes[1], takeID="fr-0098--gone", token="gone", audio=str(audio / "missing.wav"))
        self.takes += [cut, broken]
        self.manifest = self.root / "takes.json"
        self.manifest.write_text(json.dumps({"schema": store.TAKES_SCHEMA, "source": "pool", "takes": self.takes}))

    def tearDown(self):
        self.directory.cleanup()


class NormsComputationTests(PoolFixture):
    def test_per_language_percentiles_from_the_pool(self):
        document = norms.compute(self.layout, self.takes, min_count=3, echo=lambda line: None)
        self.assertEqual(document["counts"], {"french": 5, "japanese": 5})
        self.assertEqual(document["pool"]["excluded"], {"control": 0, "finishNotEOS": 1, "audioUnreadable": 1})
        self.assertEqual(set(document["models"]), {"g2p"})
        french, japanese = document["languages"]["french"], document["languages"]["japanese"]
        self.assertAlmostEqual(french["pause.gap_seconds"]["p50"], 0.25, delta=0.05)
        self.assertAlmostEqual(japanese["pause.gap_seconds"]["p50"], 0.50, delta=0.05)
        self.assertGreater(japanese["pause.gap_seconds"]["p99"], french["pause.gap_seconds"]["p99"])
        self.assertEqual(french["pause.gap_seconds"]["n"], 5)  # one pause of 100 ms or more per take
        self.assertAlmostEqual(french["pause.longest_gap_seconds"]["p50"], 0.25, delta=0.05)
        self.assertEqual(set(french), set(norms.NORM_FEATURES))
        for name in ("rate.phones_per_second", "rate.syllables_per_second", "end.tail_seconds"):
            self.assertEqual(french[name]["n"], 5, name)
            self.assertEqual(set(detectors.NORM_PERCENTILES) | {"n", "mean"}, set(french[name]), name)
        self.assertLess(french["end.tail_seconds"]["p1"], french["end.tail_seconds"]["p50"] + 1e-9)
        sparse = norms.compute(self.layout, self.takes, min_count=6, echo=lambda line: None)
        self.assertEqual(sparse["languages"], {})  # five takes per language, one value each

    def test_the_document_holds_aggregates_only(self):
        document = norms.compute(self.layout, self.takes, min_count=3, echo=lambda line: None)
        text = json.dumps(document, ensure_ascii=False)
        for take in self.takes:
            for value in (take["takeID"], take["token"], take["audioSHA256"], take["text"]):
                self.assertNotIn(value, text)
        self.assertNotIn(str(self.root), text)
        self.assertNotIn("secret", text)
        self.assertEqual(len(document["pool"]["audioSHA256"]), 64)

    def test_files_are_versioned_and_the_newest_is_read(self):
        self.assertIsNone(norms.load(self.layout))
        document = norms.compute(self.layout, self.takes, min_count=3, echo=lambda line: None)
        first = norms.write(self.layout, document)
        second = norms.write(self.layout, document)
        self.assertEqual((first.name, second.name), ("norms-v1.json", "norms-v2.json"))
        loaded = norms.load(self.layout)
        self.assertEqual((loaded["file"], loaded["version"]), ("norms-v2.json", 2))
        (self.layout.config / "norms-v3.json").write_text("{}")
        with self.assertRaises(ValueError):
            norms.load(self.layout)

    def test_the_command(self):
        spec = importlib.util.spec_from_file_location("qc_cli_norms", SCRIPTS / "qc.py")
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        arguments = ["norms", "--takes", str(self.manifest), "--min-count", "3"]
        with redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(arguments + ["--dry-run"], layout=self.layout), 0)
        self.assertIn("japanese", output.getvalue())
        self.assertIsNone(norms.latest(self.layout))
        with redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(arguments, layout=self.layout), 0)
        self.assertIn("norms-v1.json", output.getvalue())
        self.assertEqual(norms.load(self.layout)["counts"], {"french": 5, "japanese": 5})


class RateFeatureTests(unittest.TestCase):
    def test_rate_over_the_speech_span(self):
        values = features.rate_features(["l", "a", "v", "w", "a", "t", "aɪ"], (0.5, 1.5))
        self.assertAlmostEqual(values["rate.phones_per_second"]["value"], 8.0)  # "aɪ" is two broad phones
        self.assertAlmostEqual(values["rate.seconds_per_phone"]["value"], 0.125)
        self.assertAlmostEqual(values["rate.syllables_per_second"]["value"], 3.0)  # a, a, aɪ (one nucleus)
        self.assertEqual((values["rate.phones_per_second"]["start"], values["rate.phones_per_second"]["end"]), (0.5, 1.5))
        self.assertIsNone(features.rate_features(["a"], (0.0, 0.2))["rate.phones_per_second"]["value"])
        self.assertIsNone(features.rate_features(None, (0.0, 2.0))["rate.phones_per_second"]["value"])

    def test_rate_is_over_the_articulation_time(self):
        # A 2 s span with a 1 s pause articulates for 1 s; a 50 ms gap is a closure, not a pause.
        values = features.rate_features(["l", "a", "v", "w", "a", "t", "aɪ"], (0.5, 2.5), [1.0, 0.05])
        self.assertAlmostEqual(values["rate.phones_per_second"]["value"], 8.0)
        self.assertAlmostEqual(values["rate.seconds_per_phone"]["value"], 0.125)
        self.assertEqual((values["rate.phones_per_second"]["start"], values["rate.phones_per_second"]["end"]), (0.5, 2.5))
        # Pauses that leave under 0.3 s of speech leave the rate unavailable.
        self.assertIsNone(features.rate_features(["a", "b"], (0.0, 1.0), [0.8])["rate.phones_per_second"]["value"])
        # From the audio: the same script with a 0.25 s and a 1.0 s pause has one articulation rate.
        script = ["a"] * 12
        rates = []
        for pause in (0.25, 1.0):
            audio = synth(pause, 0)
            span = features.speech_span(audio, RATE)
            gaps = features.pause_gaps(audio, RATE, minimum=features.ARTICULATION_PAUSE_SECONDS)
            rates.append(features.rate_features(script, span, gaps)["rate.phones_per_second"]["value"])
        self.assertAlmostEqual(rates[0], rates[1], delta=0.1)

    def test_speech_span_skips_the_leading_and_trailing_silence(self):
        start, end = features.speech_span(synth(0.3, 0), RATE)
        self.assertAlmostEqual(start, 0.1, delta=0.03)
        self.assertGreater(end, 0.1 + 10 * 0.18 + 0.3 + 0.05)
        self.assertIsNone(features.speech_span(np.zeros(RATE), RATE))


class NormRuleTests(unittest.TestCase):
    NORMS = norms_document({
        "french": {"pause.gap_seconds": {"p99": 0.9}, "pause.longest_gap_seconds": {"p99": 5.0},
                   "end.tail_seconds": {"p1": 0.0}, "rate.phones_per_second": {"p1": 8.0, "p99": 16.0}},
        "japanese": {"pause.gap_seconds": {"p99": 0.3}, "end.tail_seconds": {"p1": 0.08}},
    })

    def detector(self, name: str) -> dict:
        config = json.loads((ROOT / "config/qc/detectors.json").read_text())
        return next(item for item in config["detectors"] if item["id"] == name)

    def score(self, name: str, language: str, norms_doc=None, **values) -> dict:
        found = {key.replace("__", "."): features.feature(value) for key, value in values.items()}
        return detectors.score(self.detector(name), found, language, None, {}, norms=norms_doc)

    def test_the_pause_flag_sits_above_the_language_p99_and_0_5_s(self):
        self.assertEqual(self.score("pause.anomalous", "french", pause__longest_gap_seconds=0.7)["score"], 1.0)
        self.assertEqual(self.score("pause.anomalous", "french", self.NORMS, pause__longest_gap_seconds=0.7)["score"], 0.0)
        outcome = self.score("pause.anomalous", "french", self.NORMS, pause__longest_gap_seconds=1.0)
        self.assertEqual(outcome["score"], 1.0)
        # Every pause's p99, not that of each take's longest.
        self.assertEqual(outcome["rule"][0], {"when": "all", "feature": "pause.longest_gap_seconds", "op": ">",
                                              "threshold": 0.9, "norm": "pause.gap_seconds:p99"})
        # A short p99 never lowers the flag under 0.5 s.
        self.assertEqual(self.score("pause.anomalous", "japanese", self.NORMS, pause__longest_gap_seconds=0.45)["score"], 0.0)
        self.assertEqual(self.score("pause.anomalous", "japanese", self.NORMS, pause__longest_gap_seconds=0.6)["score"], 1.0)
        # A language the norms lack keeps the fixed rule.
        fallback = self.score("pause.anomalous", "german", self.NORMS, pause__longest_gap_seconds=0.7)
        self.assertEqual((fallback["score"], fallback["rule"][0]["threshold"], fallback["rule"][0]["norm"]), (1.0, 0.5, None))

    def test_rate_outliers_need_norms(self):
        self.assertIsNone(self.score("prosody.rate", "french", rate__phones_per_second=5.0)["scope"])  # uncalibrated
        for rate, expected in ((5.0, 1.0), (12.0, 0.0), (20.0, 1.0)):
            outcome = self.score("prosody.rate", "french", self.NORMS, rate__phones_per_second=rate)
            self.assertEqual((outcome["scope"], outcome["score"]), ("provisional", expected), rate)
        self.assertIsNone(self.score("prosody.rate", "german", self.NORMS, rate__phones_per_second=5.0)["scope"])

    def test_conditions_validate(self):
        config = json.loads((ROOT / "config/qc/detectors.json").read_text())
        classes = {item["id"] for item in json.loads((ROOT / "config/qc/protocol.json").read_text())["classes"]}
        detectors.validate_config(config, class_ids=classes)
        bad = ({"feature": "rate.phones_per_second", "op": "<", "norm": "p42"},
               {"feature": "rate.phones_per_second", "op": "<", "norm": "p1", "atLeast": "x"},
               {"feature": "rate.phones_per_second", "op": "<"},
               {"feature": "rate.phones_per_second", "op": "<", "value": True},
               {"feature": "rate.phones_per_second", "op": "<", "value": 1, "normFeature": "pause.gap_seconds"})
        for condition in bad:
            document = json.loads(json.dumps(config))
            document["detectors"][0]["provisional"] = {"any": [condition]}
            with self.assertRaises(detectors.ConfigError, msg=condition):
                detectors.validate_config(document, class_ids=classes)

    def test_a_run_records_the_norms_and_each_flag_s_thresholds(self):
        with tempfile.TemporaryDirectory() as directory:
            layout = Layout(Path(directory))
            layout.config.mkdir(parents=True)
            for name in ("detectors.json", "protocol.json"):
                shutil.copyfile(ROOT / "config/qc" / name, layout.config / name)
            store.write_json_atomic(layout.config / "norms-v1.json", dict(self.NORMS, file=None))
            config = detectors.load_config(layout)
            rows = [{"token": token, "takeID": token, "language": "french",
                     "features": {"pause.longest_gap_seconds": features.feature(gap, 1.0, 1.0 + gap)}}
                    for token, gap in (("short", 0.7), ("long", 1.2))]
            flags = lanes.score_run(layout, config, rows, {})
        self.assertEqual(flags["norms"], "norms-v1.json")
        by_token = {take["token"]: {flag["detector"]: flag for flag in take["flags"]} for take in flags["takes"]}
        self.assertNotIn("pause.anomalous", by_token["short"])
        self.assertEqual(by_token["long"]["pause.anomalous"]["rule"][0]["threshold"], 0.9)


if __name__ == "__main__":
    unittest.main()
