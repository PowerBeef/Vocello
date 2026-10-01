"""QC v2 features, detectors and lanes on synthetic audio and stubbed runner outputs.

The acceptance case reproduces fr-0101--dylan: speech-like voiced syllables, a 1.1 s gap of
breath-like hiss, faint noise, a short voiced blip and near-digital silence mid-sentence, and
a last vowel cut in about 40 ms. pause.anomalous and boundary.abrupt-end must flag it; a take
with a 0.25 s pause and a natural 200 ms decay must pass.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import types
import unittest
import wave
from pathlib import Path
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from qc import detectors, features, lanes, label, runtime, store  # noqa: E402
from qc.store import Layout  # noqa: E402

RATE = 24000


class Synth:
    def __init__(self, seed: int = 0) -> None:
        self.rng = np.random.default_rng(seed)

    def voiced(self, seconds: float, f0: float = 110.0, db: float = -28.0) -> np.ndarray:
        t = np.arange(int(seconds * RATE)) / RATE
        wave_ = sum(np.sin(2 * np.pi * f0 * k * t) / k for k in range(1, 12))
        return wave_ / np.sqrt(np.mean(wave_ ** 2)) * 10 ** (db / 20)

    def hiss(self, seconds: float, db: float) -> np.ndarray:
        noise = self.rng.normal(size=int(seconds * RATE))
        spectrum = np.fft.rfft(noise)
        frequencies = np.fft.rfftfreq(noise.size, 1 / RATE)
        spectrum[(frequencies < 3000) | (frequencies > 7000)] = 0
        noise = np.fft.irfft(spectrum, n=noise.size)
        return noise / np.sqrt(np.mean(noise ** 2)) * 10 ** (db / 20)

    def silence(self, seconds: float, db: float = -75.0) -> np.ndarray:
        return self.rng.normal(size=int(seconds * RATE)) * 10 ** (db / 20)

    def syllables(self, seconds: float) -> np.ndarray:
        parts: list[np.ndarray] = []
        while sum(map(len, parts)) < seconds * RATE:
            parts += [self.voiced(0.16, 100 + 20 * self.rng.random()), self.hiss(0.06, -34.0)]
        return np.concatenate(parts)[: int(seconds * RATE)]

    def dylan(self) -> np.ndarray:
        return np.concatenate([
            self.silence(0.07), self.syllables(0.7), self.silence(0.2), self.syllables(2.0),
            self.hiss(0.35, -31.0), self.hiss(0.4, -58.0), self.voiced(0.05, 120, -32.0), self.silence(0.3),
            self.syllables(1.1), self.voiced(0.2, 92, -33.0),
            self.voiced(0.03, 92, -45.0), self.voiced(0.02, 92, -60.0), self.silence(0.02, -90.0),
        ])

    def natural(self) -> np.ndarray:
        last = self.voiced(0.35, 92, -33.0)
        fade = int(0.2 * RATE)
        last[-fade:] *= np.linspace(1, 0, fade) ** 3
        return np.concatenate([self.silence(0.07), self.syllables(0.7), self.silence(0.25), self.syllables(3.0),
                               last, self.silence(0.15)])


def write_wav(path: Path, samples: np.ndarray) -> Path:
    pcm = np.clip(np.rint(samples * 32767), -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(RATE)
        writer.writeframes(pcm.tobytes())
    return path


def config(layout_root: Path | None = None) -> dict:
    return json.loads((ROOT / "config/qc/detectors.json").read_text())


def by_id(name: str) -> dict:
    return next(detector for detector in config()["detectors"] if detector["id"] == name)


class SignalFeatureTests(unittest.TestCase):
    def test_fr_0101_dylan_pause_and_abrupt_end_are_flagged(self):
        take = Synth(0).dylan()
        values = {}
        values.update(features.pause_features(take, RATE, None))
        values.update(features.end_features(take, RATE))
        gap = values["pause.longest_gap_seconds"]
        self.assertAlmostEqual(gap["value"], 1.1, delta=0.08)
        self.assertAlmostEqual(gap["start"], 2.97, delta=0.08)
        self.assertAlmostEqual(gap["end"], 4.07, delta=0.08)
        self.assertGreater(values["pause.nonspeech_level_db"]["value"], -6.0)  # hiss near speech level
        self.assertEqual(values["pause.voiced_blips"]["value"], 1)
        self.assertGreater(values["end.drop_db_60ms"]["value"], 30)
        self.assertLess(values["end.tail_seconds"]["value"], 0.05)
        for detector_id in ("pause.anomalous", "boundary.abrupt-end"):
            outcome = detectors.score(by_id(detector_id), values, "french", None, {})
            self.assertEqual((outcome["scope"], outcome["score"], outcome["cut"]), ("provisional", 1.0, 1.0), detector_id)
        # A mute test that found words in the gap clears the pause flag.
        values["pause.mute_confirmed"] = features.feature(0.0)
        self.assertEqual(detectors.score(by_id("pause.anomalous"), values, "french", None, {})["score"], 0.0)

    def test_natural_pause_and_decay_pass(self):
        take = Synth(1).natural()
        values = {}
        values.update(features.pause_features(take, RATE, None))
        values.update(features.end_features(take, RATE))
        self.assertLess(values["pause.longest_gap_seconds"]["value"], 0.4)
        self.assertLess(values["end.drop_db_60ms"]["value"], 30)
        self.assertGreater(values["end.tail_seconds"]["value"], 0.05)
        for detector_id in ("pause.anomalous", "boundary.abrupt-end"):
            self.assertEqual(detectors.score(by_id(detector_id), values, "french", None, {})["score"], 0.0)

    def test_aligned_word_gaps_count(self):
        take = Synth(1).natural()
        aligned = {"words": [{"text": "a", "start": 0.1, "end": 0.5}, {"text": "b", "start": 1.3, "end": 1.6}]}
        gap = features.pause_features(take, RATE, aligned)["pause.longest_gap_seconds"]
        self.assertAlmostEqual(gap["value"], 0.8, places=3)
        self.assertEqual((gap["start"], gap["end"]), (0.5, 1.3))

    def test_k_weighting_and_loudness(self):
        (b1, a1), (b2, a2) = features.k_weighting(48000)
        np.testing.assert_allclose(b1, [1.53512485958697, -2.69169618940638, 1.19839281085285], atol=1e-8)
        np.testing.assert_allclose(a1, [1.0, -1.69065929318241, 0.73248077421585], atol=1e-8)
        np.testing.assert_allclose(a2, [1.0, -1.99004745483398, 0.99007225036621], atol=1e-8)
        for rate in (48000, RATE):
            sine = np.sin(2 * np.pi * 997 * np.arange(rate * 4) / rate)
            self.assertAlmostEqual(features.integrated_loudness(sine, rate), -3.01, delta=0.05)
            self.assertAlmostEqual(features.integrated_loudness(0.1 * sine, rate), -23.01, delta=0.05)
        quiet = features.loudness_features(0.05 * np.sin(2 * np.pi * 300 * np.arange(RATE * 4) / RATE), RATE)
        self.assertGreater(quiet["level.lufs_deviation"]["value"], 4)
        self.assertAlmostEqual(quiet["level.true_peak_dbtp"]["value"], 20 * np.log10(0.05), delta=0.1)
        self.assertEqual(detectors.score(by_id("level.loudness"), quiet, "french", None, {})["score"], 1.0)
        self.assertIsNone(features.integrated_loudness(np.zeros(100), RATE))

    def test_dsp_checks(self):
        synth = Synth(2)
        take = synth.natural()
        take[RATE] += 0.6  # one click
        values = features.signal_features(take, RATE, config()["params"])
        self.assertGreaterEqual(values["signal.clicks"]["value"], 1)
        self.assertAlmostEqual(values["signal.clicks"]["start"], 1.0, delta=0.01)
        self.assertEqual(values["signal.clipping_fraction"]["value"], 0.0)
        dropout = np.concatenate([synth.syllables(1.0), np.zeros(int(0.3 * RATE)), synth.syllables(1.0)])
        self.assertAlmostEqual(features.signal_features(dropout, RATE, {})["signal.dropout_seconds"]["value"],
                               0.3, delta=0.02)

    def test_wav_io_and_mute(self):
        with tempfile.TemporaryDirectory() as directory:
            source = write_wav(Path(directory) / "take.wav", Synth(3).syllables(1.0))
            samples, rate = features.read_wav(source)
            self.assertEqual((rate, samples.size), (RATE, RATE))
            muted = features.mute_wav(source, Path(directory) / "work/muted.wav", 0.25, 0.5)
            self.assertEqual(muted.stat().st_size, source.stat().st_size)
            quiet, _ = features.read_wav(muted)
            self.assertTrue(np.all(quiet[int(0.25 * RATE):int(0.5 * RATE)] == 0))
            np.testing.assert_array_equal(quiet[: int(0.25 * RATE)], samples[: int(0.25 * RATE)])
        self.assertEqual(features.transcript_distance("le chat dort", "le chat dort", "french"), 0.0)
        self.assertAlmostEqual(features.transcript_distance("le chat dort", "le dort", "french"), 1 / 3)


class ModelFeatureTests(unittest.TestCase):
    def take(self, **overrides):
        take = {"token": "t1", "takeID": "fr-0001--aiden", "language": "french", "text": "Le chat dort ici.",
                "mode": "custom", "voice": "aiden", "cell": "standard", "reference": None, "referenceSHA256": None}
        take.update(overrides)
        return take

    def result(self, outputs):
        return {"schema": store.RESULT_SCHEMA, "outputs": outputs}

    def test_asr_features_need_both_families(self):
        results = {"asrA": self.result({"text": "Le chat chat dort ici.", "language": "French", "languageProbs": None}),
                   "asrB": self.result({"text": "Le chat dort ici", "language": "fr",
                                        "languageProbs": {"fr": 0.9, "en": 0.1}})}
        values = features.asr_features(self.take(), results)
        self.assertEqual(values["asr.edit_rate_min"]["value"], 0.0)  # only one family heard the repeat
        self.assertAlmostEqual(values["asr.language_mismatch_min"]["value"], 0.0)
        cyrillic = {"asrA": self.result({"text": "Привет мир", "language": "russian"}),
                    "asrB": self.result({"text": "Привет", "language": "ru"})}
        values = features.asr_features(self.take(), cyrillic)
        self.assertEqual(values["asr.script_mismatch_min"]["value"], 1.0)
        self.assertEqual(values["asr.language_mismatch_min"]["value"], 1.0)
        self.assertIsNone(features.asr_features(self.take(), {"asrA": cyrillic["asrA"]})["asr.edit_rate_min"]["value"])

    def test_phone_features_with_a_stubbed_phones_module(self):
        stub = types.SimpleNamespace(
            g2p=lambda text, language: ["l", "ə", "ʃ", "a"] if "ici" not in text else ["i", "s", "i"],
            # "lə lə ʃa" heard as "lə lə u": a repeated syllable, a lost /ʃ/ and /a/ heard as /u/.
            align=lambda expected, recognized: [
                ("ins", None, "l", 0.1, 0.15), ("ins", None, "ə", 0.15, 0.2), ("match", "l", "l", 0.2, 0.25),
                ("match", "ə", "ə", 0.25, 0.3), ("del", "ʃ", None, None, None), ("sub", "a", "u", 0.4, 0.5)],
        )
        results = {"phones": self.result({"phones": [{"phone": "l", "start": 0, "end": 0.1, "prob": 0.9}]})}
        with mock.patch.object(features, "phones", stub):
            values = features.phone_features(self.take(text="Le chat."), results, Layout(), {}, config()["params"])
        self.assertEqual(values["phones.deletion_rate"]["value"], 0.25)
        self.assertEqual(values["phones.repeat_runs"]["value"], 1)
        self.assertEqual((values["phones.repeat_runs"]["start"], values["phones.repeat_runs"]["end"]), (0.1, 0.2))
        self.assertEqual(values["phones.substitution_rate"]["value"], 0.25)
        with mock.patch.object(features, "phones", None):
            self.assertIsNone(features.phone_features(self.take(), results, Layout(), {}, {})["phones.deletion_rate"]["value"])

    def test_pitch_features_from_two_agreeing_trackers(self):
        if features.pitch is None:
            self.skipTest("qc.pitch is not available")
        hop = 0.01
        f0 = [110.0] * 100 + [220.0] * 60 + [110.0] * 100
        track = {"hopSeconds": hop, "f0Hz": f0, "confidence": [0.9] * len(f0)}
        values = features.pitch_features(self.take(), {"pitchA": self.result(track), "pitchB": self.result(track)},
                                         {"voicePitch": {"custom|aiden": 0.0}}, None, config()["params"])
        self.assertGreaterEqual(values["pitch.octave_jumps"]["value"], 1)
        self.assertEqual(values["pitch.tracker_disagreement"]["value"], 0.0)
        self.assertGreater(values["pitch.register_offset_st"]["value"], 0)

    def test_speaker_drift_against_the_clone_reference(self):
        reference = [1.0, 0.0, 0.0]
        speaker = {"windowSeconds": 3, "hopSeconds": 1, "whole": [0.9, 0.1, 0.0], "reference": reference,
                   "windows": [{"start": 0, "end": 3, "embedding": [1.0, 0.0, 0.0]},
                               {"start": 1, "end": 4, "embedding": [0.0, 1.0, 0.0]}]}
        values = features.speaker_features(self.take(), {"speaker": self.result(speaker)}, {})
        self.assertAlmostEqual(values["speaker.max_window_distance"]["value"], 1.0)
        self.assertEqual(values["speaker.max_window_distance"]["start"], 1)
        self.assertGreater(values["speaker.window_range"]["value"], 0.5)

    def test_llm_and_quality_features(self):
        judged = {"transcript": "x", "classes": {"stutter": {"present": True, "severity": "mild", "start": 1.0,
                                                             "end": 1.5, "evidence": "", "pYes": None}}}
        values = features.llm_features({"llm": self.result(judged)})
        self.assertEqual((values["llm.stutter"]["value"], values["llm.stutter"]["start"]), (1.0, 1.0))
        self.assertIsNone(values["llm.pitch"]["value"])
        quality = features.quality_features(self.take(), {
            "mos": self.result({"mos": 3.1, "windows": [{"start": 0, "end": 3, "mos": 2.0}, {"start": 1, "end": 4, "mos": 3.5}]}),
            "aesthetics": self.result({"CE": 5.0, "CU": 5.0, "PC": 2.0, "PQ": 6.0})},
            {"cellAesthetics": {"standard": {"PQ": 7.0, "CE": 5.5}}})
        self.assertEqual((quality["mos.worst_window"]["value"], quality["aesthetics.pq_delta"]["value"]), (2.0, -1.0))


class DetectorConfigTests(unittest.TestCase):
    def test_checked_in_config_is_valid(self):
        detectors.load_config(Layout(ROOT))

    def test_invalid_configs_are_refused(self):
        base = config()
        cases = []
        too_many = json.loads(json.dumps(base))
        too_many["detectors"][0]["features"] = too_many["detectors"][0]["features"] * 2
        cases.append(too_many)
        threshold = json.loads(json.dumps(base))
        threshold["detectors"][3]["method"] = "threshold"
        cases.append(threshold)
        rule = json.loads(json.dumps(base))
        rule["detectors"][0]["provisional"] = {"all": [{"feature": "pause.longest_gap_seconds", "op": "~", "value": 1}]}
        cases.append(rule)
        unknown = json.loads(json.dumps(base))
        unknown["detectors"][5]["class"] = "vibes"
        cases.append(unknown)
        classes = {item["id"] for item in json.loads((ROOT / "config/qc/protocol.json").read_text())["classes"]}
        for document in cases:
            with self.assertRaises(detectors.ConfigError):
                detectors.validate_config(document, class_ids=classes)

    def test_rules_and_scores(self):
        rule = {"all": [{"feature": "a", "op": ">", "value": 1}], "none": [{"feature": "b", "op": "==", "value": 0}]}
        value = features.feature
        self.assertTrue(detectors.rule_holds(rule, {"a": value(2)}))
        self.assertFalse(detectors.rule_holds(rule, {"a": value(2), "b": value(0)}))
        self.assertIsNone(detectors.rule_holds(rule, {"b": value(1)}))
        self.assertTrue(detectors.rule_holds({"any": [{"feature": "a", "op": "<", "value": 0},
                                                      {"feature": "c", "op": ">", "value": 0}]}, {"c": value(1)}))
        detector = {"id": "d", "class": "artifact", "method": "logistic",
                    "features": [{"name": "signal.clicks", "direction": "higher"},
                                 {"name": "mos.whole", "direction": "lower"}]}
        norm = {"french": {"signal.clicks": {"mean": 1.0, "std": 1.0, "median": 1.0, "n": 10},
                           "mos.whole": {"mean": 4.0, "std": 0.5, "median": 4.0, "n": 10}}}
        take = {"signal.clicks": value(3), "mos.whole": value(3.0)}
        self.assertEqual(detectors.score(detector, take, "french", None, norm)["score"], 2.0)  # max oriented z
        fitted = {"models": {"*": {"intercept": -1.0, "weights": [1.0, 1.0], "cut": 0.5}}}
        outcome = detectors.score(detector, take, "french", fitted, norm)
        self.assertAlmostEqual(outcome["score"], detectors.sigmoid(-1 + 2 + 2))
        self.assertEqual(outcome["scope"], "*")
        missing = detectors.score(detector, {"mos.whole": value(3.0)}, "french", fitted, norm)
        self.assertAlmostEqual(missing["score"], detectors.sigmoid(-1 + 0 + 2))  # the median fills clicks


class LaneTests(unittest.TestCase):
    """`qc.py run` end to end with one stubbed ASR model, then gate and queue."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.layout = Layout(self.root)
        self.layout.config.mkdir(parents=True)
        for name in ("detectors.json", "protocol.json"):
            shutil.copyfile(ROOT / "config/qc" / name, self.layout.config / name)
        runner = self.root / "scripts/qc/runners/stub_asr.py"
        runner.parent.mkdir(parents=True)
        runner.write_text("# stub\n")
        self.asr = {"id": "asr.qwen3-asr-1.7b", "kind": "asr", "runner": "qc.runners.stub_asr", "runtime": "mlx",
                    "source": {"host": "huggingface", "repo": "a/b", "revision": "0" * 40,
                               "files": {"w": {"sha256": "0" * 64, "bytes": 1}}},
                    "license": "MIT", "memoryGB": 1, "languages": "any", "version": 1}
        self.layout.registry.write_text(json.dumps({"schemaVersion": 1, "models": [self.asr]}))
        audio = self.root / "audio"
        audio.mkdir()
        takes = []
        for index, (take_id, samples) in enumerate((("fr-0101--dylan", Synth(0).dylan()),
                                                     ("fr-0102--aiden", Synth(1).natural()))):
            path = write_wav(audio / f"{take_id}.wav", samples)
            takes.append({"takeID": take_id, "token": store.take_token("pool-a", take_id), "audio": str(path),
                          "audioSHA256": store.audio_sha256(path), "language": "french", "text": "De fait, les branches.",
                          "mode": "custom", "voice": take_id.split("--")[1], "cell": "standard", "reference": None,
                          "referenceSHA256": None, "referenceText": None, "finishReason": "eos", "seed": index,
                          "family": take_id.split("--")[0]})
        self.manifest = self.root / "takes.json"
        self.manifest.write_text(json.dumps({"schema": store.TAKES_SCHEMA, "source": "pool-a", "takes": takes}))
        self.calls = []

    def tearDown(self):
        self.directory.cleanup()

    def fake_runner(self, model, takes, options=None, *, layout, echo, **kwargs):
        identity = runtime.runner_identity(layout, model)
        report = runtime.RunnerReport(model=model["id"], runner_sha=identity)
        self.calls.append([take["token"] for take in takes])
        for take in takes:
            store.write_result(layout.results_dir(model["id"]), model=model["id"], runner_sha=identity,
                               audio_sha=take["audioSHA256"], variant=None, duration_seconds=1.0,
                               outputs={"text": "De fait, les branches.", "language": "French", "languageProbs": None,
                                        "words": None})
            report.ran += 1
        return report

    def run_lane(self, lane="pool"):
        return lanes.run(self.layout, str(self.manifest), lane, roles=["asrA"], runner=self.fake_runner,
                         echo=lambda line: None)

    def test_run_flags_the_dylan_take_with_evidence_and_confirms_the_gap(self):
        directory = self.run_lane()
        flags = store.read_json(directory / "flags.json")
        by_take = {take["takeID"]: take for take in flags["takes"]}
        dylan = {flag["detector"]: flag for flag in by_take["fr-0101--dylan"]["flags"]}
        self.assertIn("pause.anomalous", dylan)
        self.assertIn("boundary.abrupt-end", dylan)
        self.assertEqual(dylan["pause.anomalous"]["level"], "report-only")
        evidence = {item["feature"]: item for item in dylan["pause.anomalous"]["evidence"]}
        self.assertAlmostEqual(evidence["pause.longest_gap_seconds"]["start"], 2.97, delta=0.08)
        self.assertEqual(evidence["pause.mute_confirmed"]["value"], 1.0)
        self.assertEqual(flags["models"]["muteTest"], {"candidates": 1, "tested": 1, "confirmed": 1})
        self.assertEqual(len(self.calls), 2)  # the takes, then the muted variant
        aiden = {flag["detector"] for flag in by_take["fr-0102--aiden"]["flags"]}
        self.assertNotIn("pause.anomalous", aiden)
        self.assertNotIn("boundary.abrupt-end", aiden)
        features_doc = store.read_json(directory / "features.json")
        self.assertTrue(features_doc["models"]["asrA"]["available"])
        self.assertFalse(features_doc["models"]["phones"]["available"])
        self.assertEqual(lanes.gate(self.layout, "pool"), lanes.EXIT_PASS)  # report-only never gates

    def test_gate_levels_come_from_the_evaluation_of_the_thresholds(self):
        self.run_lane("clone")
        thresholds = {"schema": "vocello.qc.thresholds/1", "version": 1, "models": {}, "normalization": {},
                      "detectors": {detector["id"]: {"reportOnly": True} for detector in config()["detectors"]}}
        path = self.layout.config / "thresholds-v1.json"
        store.write_json_atomic(path, thresholds)
        evaluation = {"version": 1, "thresholdsSHA256": store.sha256_file(path), "detectors": {
            "pause.anomalous": {"languages": {"french": {"level": "fail"}}},
            "boundary.abrupt-end": {"languages": {"french": {"level": "warn"}}}}}
        store.write_json_atomic(self.root / "benchmarks/qc/eval-v1.json", evaluation)
        self.run_lane("clone")
        self.assertEqual(lanes.gate(self.layout, "clone"), lanes.EXIT_FAIL)
        evaluation["detectors"]["pause.anomalous"]["languages"]["french"]["level"] = "report-only"
        store.write_json_atomic(self.root / "benchmarks/qc/eval-v1.json", evaluation)
        self.run_lane("clone")
        self.assertEqual(lanes.gate(self.layout, "clone"), lanes.EXIT_WARN)
        self.assertEqual(lanes.gate(self.layout, "no-such-lane"), lanes.EXIT_ERROR)

    def test_queue_writes_a_label_batch_of_unlabelled_takes(self):
        directory = self.run_lane()
        path = lanes.queue(self.layout, 1, run_id=directory.name, name="queue-1")
        batch = label.load_batch(self.layout, "queue-1")
        self.assertEqual(path.name, "queue-1.json")
        self.assertEqual(batch["kind"], "queue")
        self.assertEqual(len(batch["items"]), 1)
        self.assertEqual(batch["takes"][batch["items"][0]["takeToken"]]["takeID"], "fr-0101--dylan")
        self.assertIsNone(batch["items"][0]["inclusionProbability"])
        # A labelled take leaves the queue.
        store.append_jsonl(self.layout.labels / "queue-1.jsonl", {"token": batch["items"][0]["token"],
                                                                  "verdict": "objectionable", "classes": {}})
        lanes.queue(self.layout, 1, run_id=directory.name, name="queue-2")
        second = label.load_batch(self.layout, "queue-2")
        self.assertEqual(second["takes"][second["items"][0]["takeToken"]]["takeID"], "fr-0102--aiden")

    def test_parse_roles(self):
        self.assertEqual(lanes.parse_roles("asrA,asr.whisper-large-v3", config()), ["asrA", "asrB"])
        with self.assertRaises(ValueError):
            lanes.parse_roles("nope", config())
        with self.assertRaises(ValueError):
            lanes.run(self.layout, str(self.manifest), "../escape", runner=self.fake_runner)


if __name__ == "__main__":
    unittest.main()
