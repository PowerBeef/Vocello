"""QC v2 features, detectors and lanes on synthetic audio and stubbed runner outputs.

The acceptance case reproduces fr-0101--dylan as the review measured it: speech-like voiced
syllables, then the /t/ closure and burst of "abattus", its whispered "-tus" (loud and unvoiced,
0.35 s), a 0.8 s pause of faint noise and near-digital silence with one short voiced blip, and a
last vowel cut in about 40 ms. The pause is the quiet run after the whisper, not the whisper with
it; pause.anomalous must flag it. A take with a 0.25 s pause and a natural 200 ms decay must pass.
"""

from __future__ import annotations

import contextlib
import io
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
            self.silence(0.05),  # the /t/ closure of "abattus" (2.97-3.02)
            self.hiss(0.02, -26.0),  # its burst
            self.hiss(0.35, -31.0),  # the whispered "-tus" (3.04-3.39): loud and unvoiced
            self.hiss(0.4, -58.0), self.voiced(0.05, 120, -32.0), self.silence(0.35),  # the pause (3.39-4.19)
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
    def test_fr_0101_dylan_pause_is_the_quiet_run_after_the_whisper(self):
        take = Synth(0).dylan()
        values = {}
        values.update(features.pause_features(take, RATE))
        values.update(features.end_features(take, RATE))
        gap = values["pause.longest_gap_seconds"]
        # The whispered "-tus" is loud unvoiced sound, not a pause: the pause is the 0.8 s quiet run
        # after it (the real take: about 0.82 s, not the 1.21 s that took the whisper in).
        self.assertAlmostEqual(gap["value"], 0.8, delta=0.03)
        self.assertAlmostEqual(gap["start"], 3.39, delta=0.02)
        self.assertAlmostEqual(gap["end"], 4.19, delta=0.02)
        # The 0.2 s pause, then the /t/ closure (a gap of its own, under the 100 ms the norms count),
        # then the whisper, which bounds the closure and the pause.
        gaps = features.pause_gaps(take, RATE)
        self.assertEqual(len(gaps), 3, gaps)
        for measured, expected in zip(gaps, (0.2, 0.045, 0.8)):
            self.assertAlmostEqual(measured, expected, delta=0.02)
        # The non-speech stretch around the pause holds the whisper, at speech level.
        level = values["pause.nonspeech_level_db"]
        self.assertGreater(level["value"], -6.0)
        self.assertLess(level["start"], 3.04)
        self.assertEqual(values["pause.voiced_blips"]["value"], 1)
        self.assertTrue(gap["start"] < values["pause.voiced_blips"]["start"] < gap["end"])
        outcome = detectors.score(by_id("pause.anomalous"), values, "french", None, {})
        self.assertEqual((outcome["scope"], outcome["score"], outcome["cut"]), ("provisional", 1.0, 1.0))
        # Phones heard in the pause cut out alone clear the pause flag; none keep it.
        values["pause.excerpt_phones"] = features.feature(0.0)
        self.assertEqual(detectors.score(by_id("pause.anomalous"), values, "french", None, {})["score"], 1.0)
        values["pause.excerpt_phones"] = features.feature(3.0)
        self.assertEqual(detectors.score(by_id("pause.anomalous"), values, "french", None, {})["score"], 0.0)
        # The ending is still measured, but no detector reads it: a cut-off is content evidence
        # (boundary.cutoff), and the ending is a trimming check.
        self.assertGreater(values["end.drop_db_60ms"]["value"], 30)
        self.assertLess(values["end.tail_seconds"]["value"], 0.05)
        self.assertNotIn("end", {item["name"].split(".", 1)[0] for detector in config()["detectors"]
                                 for item in detector["features"]})

    def test_natural_pause_and_decay_pass(self):
        take = Synth(1).natural()
        values = {}
        values.update(features.pause_features(take, RATE))
        values.update(features.end_features(take, RATE))
        self.assertAlmostEqual(values["pause.longest_gap_seconds"]["value"], 0.25, delta=0.02)
        self.assertLess(values["pause.nonspeech_level_db"]["value"], -30.0)  # a quiet pause
        self.assertLess(values["end.drop_db_60ms"]["value"], 30)
        self.assertGreater(values["end.tail_seconds"]["value"], 0.05)
        self.assertEqual(detectors.score(by_id("pause.anomalous"), values, "french", None, {})["score"], 0.0)

    def test_the_ending_pads_at_the_tail_floor_and_clamps_silence(self):
        synth = Synth(4)
        cut = np.concatenate([synth.silence(0.1), synth.syllables(1.0), synth.voiced(0.3, 100, -28.0)])
        values = features.end_features(cut, RATE)
        # Cut at the last sample: a drop to the -60 dBFS tail floor (about 32 dB), not to a -120 dB
        # padding that made every cut a 90 dB drop.
        self.assertAlmostEqual(values["end.drop_db_60ms"]["value"], 32.0, delta=3.0)
        self.assertAlmostEqual(values["end.file_tail_seconds"]["value"], 0.0, delta=0.03)
        zeros = features.end_features(np.concatenate([cut, np.zeros(int(0.5 * RATE))]), RATE)
        self.assertLessEqual(zeros["end.drop_db_60ms"]["value"], 72.5)  # digital silence clamps at -100 dB
        self.assertAlmostEqual(zeros["end.file_tail_seconds"]["value"], 0.5, delta=0.03)  # the trim check
        self.assertIsNone(features.end_features(np.zeros(RATE), RATE)["end.file_tail_seconds"]["value"])

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
        # The synth's fricatives (hiss between syllables) are no clicks: a take-wide scale counted
        # over twenty of them; the local one counts the one injected click.
        self.assertEqual(features.signal_features(take, RATE, config()["params"])["signal.clicks"]["value"], 0)
        take[RATE] += 0.6  # one click
        values = features.signal_features(take, RATE, config()["params"])
        self.assertEqual(values["signal.clicks"]["value"], 1)
        self.assertAlmostEqual(values["signal.clicks"]["start"], 1.0, delta=0.01)
        self.assertNotIn("signal.clicks", [item["name"] for item in by_id("signal.artifacts")["features"]])
        self.assertEqual(values["signal.clipping_fraction"]["value"], 0.0)
        dropout = np.concatenate([synth.syllables(1.0), np.zeros(int(0.3 * RATE)), synth.syllables(1.0)])
        self.assertAlmostEqual(features.signal_features(dropout, RATE, {})["signal.dropout_seconds"]["value"],
                               0.3, delta=0.02)

    def test_wav_io_and_excerpt(self):
        with tempfile.TemporaryDirectory() as directory:
            source = write_wav(Path(directory) / "take.wav", Synth(3).syllables(1.0))
            samples, rate = features.read_wav(source)
            self.assertEqual((rate, samples.size), (RATE, RATE))
            excerpt = features.excerpt_wav(source, Path(directory) / "work/excerpt.wav", 0.25, 0.5)
            piece, piece_rate = features.read_wav(excerpt)
            self.assertEqual((piece_rate, piece.size), (RATE, int(0.25 * RATE)))
            np.testing.assert_array_equal(piece, samples[int(0.25 * RATE):int(0.5 * RATE)])
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

    def heard(self, *items):
        return [{"phone": phone, "start": start, "end": start + 0.05, "prob": 0.9} for phone, start in items]

    def test_phone_features_through_qc_phones(self):
        if features.phones is None:
            self.skipTest("qc.phones is not available")
        # "les branches de" (l e b ʁ ɑ̃ ʃ d e): a repeated syllable "bran-branches", then a lost /ʃ/.
        g2p = self.result({"phones": ["l", "e", "b", "ʁ", "ɑ̃", "ʃ", "d", "e"],
                           "words": [{"ipa": "le", "phones": ["l", "e"]}, {"ipa": "bʁɑ̃ʃ", "phones": ["b", "ʁ", "ɑ̃", "ʃ"]},
                                     {"ipa": "de", "phones": ["d", "e"]}]})

        def recognized(phones_heard):
            return self.result({"phones": self.heard(*((phone, 0.1 * index) for index, phone in enumerate(phones_heard)))})

        def run(*phones_heard, second=None):
            # Both recognizers hear the same phones unless `second` says otherwise ("" for no result).
            results = {"g2p": g2p, "phones": recognized(phones_heard)}
            if second != "":
                results["phonesB"] = recognized(phones_heard if second is None else second)
            return features.phone_features(self.take(text="Les branches de."), results, Layout(), {}, config()["params"])

        stuttered = ("l", "e", "b", "ʁ", "ɑ̃", "b", "ʁ", "ɑ̃", "ʃ", "d", "e")
        stutter = run(*stuttered)
        self.assertEqual(stutter["phones.repeat_runs"]["value"], 1)
        self.assertEqual(stutter["phones.repeat_runs"]["start"], 0.2)
        self.assertAlmostEqual(stutter["phones.insertion_rate"]["value"], 3 / 8, places=4)
        self.assertEqual(stutter["phones.deletion_rate"]["value"], 0.0)
        self.assertIsNone(stutter["phones.gop_mean"]["value"])  # no posteriors
        # Only one recognizer heard the repetition: its own habit, not a stutter.
        alone = run(*stuttered, second=("l", "e", "b", "ʁ", "ɑ̃", "ʃ", "d", "e"))
        self.assertEqual((alone["phones.repeat_runs"]["value"], alone["phones.insertion_rate"]["value"]), (0, 0.0))
        # Without the second recognizer's result the insertion features abstain; the rest stay.
        single = run(*stuttered, second="")
        self.assertIsNone(single["phones.repeat_runs"]["value"])
        self.assertIsNone(single["phones.insertion_rate"]["value"])
        self.assertEqual(single["phones.deletion_rate"]["value"], 0.0)
        missing = run("l", "e", "b", "ʁ", "ɑ̃", "d", "e")
        self.assertEqual(missing["phones.deletion_rate"]["value"], 0.125)
        self.assertEqual(missing["phones.repeat_runs"]["value"], 0)
        clean = run("l", "e", "b", "ʁ", "ɑ̃", "ʃ", "d", "e")
        self.assertEqual((clean["phones.deletion_rate"]["value"], clean["phones.repeat_runs"]["value"]), (0.0, 0))
        self.assertEqual(clean["phones.last_word_coverage"]["value"], 1.0)
        cut = run("l", "e", "b", "ʁ", "ɑ̃", "ʃ", "d")
        self.assertEqual(cut["phones.last_word_coverage"]["value"], 0.5)  # the last word lost its /e/

    def test_liaison_and_final_schwa_left_out_cost_nothing(self):
        if features.phones is None:
            self.skipTest("qc.phones is not available")
        # "les ormes abattus" as espeak-ng reads it, /lez ɔʁməz abaty/: the liaison /z/ of "les", the
        # schwa and liaison /z/ of "ormes" may all go.
        g2p = self.result({"phones": ["l", "e", "z", "ɔ", "ʁ", "m", "ə", "z", "a", "b", "a", "t", "y"],
                           "words": [{"ipa": "lez", "phones": ["l", "e", "z"], "optional": [2]},
                                     {"ipa": "ɔʁməz", "phones": ["ɔ", "ʁ", "m", "ə", "z"], "optional": [3, 4]},
                                     {"ipa": "abaty", "phones": ["a", "b", "a", "t", "y"], "optional": []}]})
        heard = ("l", "e", "ɔ", "ʁ", "m", "a", "b", "a", "t", "y")
        results = {"g2p": g2p}
        for role in ("phones", "phonesB"):
            results[role] = self.result({"phones": self.heard(*((phone, 0.1 * index) for index, phone in enumerate(heard)))})
        values = features.phone_features(self.take(text="Les ormes abattus."), results, Layout(), {}, config()["params"])
        self.assertEqual(values["phones.deletion_rate"]["value"], 0.0)
        self.assertEqual(values["phones.per"]["value"], 0.0)
        self.assertEqual(values["phones.last_word_coverage"]["value"], 1.0)

    def test_content_phoneme_reads_the_insertions_both_recognizers_agree_on(self):
        """The provisional rule on the agreed insertions: a comparison whose insertions and repeats
        both recognizers made flags; the same first recognizer with a second that heard none of them
        does not (on native French speech ZIPA alone prints the silent letters of 38% of "les")."""

        def measured(per, insertion, repeats):
            runs = [{"start": 1.0 + index, "end": 1.3 + index, "n": 2, "copies": 2, "phones": ["b", "r"]}
                    for index in range(repeats)]
            return {"ops": [], "features": {"per": per, "insertionRate": insertion, "deletionRate": 0.05,
                                            "substitutionRate": per - insertion - 0.05, "repeatRuns": runs,
                                            "repeatCount": repeats, "insertionBursts": [], "deletionRuns": [],
                                            "lowGopSpans": [], "meanGop": None}}

        results = {"g2p": self.result({"phones": ["a"], "words": []}), "phones": self.result({"phones": []}),
                   "phonesB": self.result({"phones": []})}
        detector = by_id("content.phoneme")
        stuttered, clean = measured(0.475, 0.275, 4), measured(0.103, 0.0, 0)
        for name, agreed, expected in (("both heard it", stuttered, 1.0), ("one heard it", clean, 0.0)):
            stub = types.SimpleNamespace(
                compare=lambda *args, **kwargs: stuttered,
                agreement=lambda first, second, agreed=agreed, **kwargs: {"agreed": [], "features": agreed["features"]},
                normalize_phone=lambda phone, **kwargs: [phone], normalize=lambda items, **kwargs: list(items))
            with mock.patch.object(features, "phones", stub):
                values = features.phone_features(self.take(), results, Layout(), {}, config()["params"])
            self.assertEqual(values["phones.repeat_runs"]["value"], agreed["features"]["repeatCount"])
            self.assertEqual(values["phones.insertion_rate"]["value"], agreed["features"]["insertionRate"])
            self.assertEqual(values["phones.deletion_rate"]["value"], 0.05)  # the first recognizer's own
            self.assertEqual(detectors.score(detector, values, "french", None, {})["score"], expected, name)

    def test_phone_features_need_both_inputs(self):
        results = {"phones": self.result({"phones": self.heard(("l", 0.1))})}
        # No G2P result and no G2P cache entry: the phone features stay unavailable.
        self.assertIsNone(features.phone_features(self.take(), results, Layout(Path(tempfile.gettempdir())), {},
                                                  {})["phones.deletion_rate"]["value"])
        with mock.patch.object(features, "phones", None):
            self.assertIsNone(features.phone_features(self.take(), results, Layout(), {}, {})["phones.deletion_rate"]["value"])
        stub = types.SimpleNamespace(compare=mock.Mock(side_effect=ValueError("bad")))
        with mock.patch.object(features, "phones", stub):
            self.assertIsNone(features.phone_features(self.take(), {**results, "g2p": self.result({"phones": ["l"]})},
                                                      Layout(), {}, {})["phones.deletion_rate"]["value"])

    def test_pitch_features_from_two_agreeing_trackers(self):
        if features.pitch is None:
            self.skipTest("qc.pitch is not available")
        hop = 0.01
        f0 = [110.0] * 100 + [220.0] * 60 + [110.0] * 100
        track = {"hopSeconds": hop, "f0Hz": f0, "confidence": [0.9] * len(f0)}
        results = {"pitchA": self.result(track), "pitchB": self.result(track)}
        clone = self.take(referenceSHA256="r" * 64)
        values = features.pitch_features(clone, results, {"referencePitch": {"r" * 64: 0.0}}, config()["params"])
        self.assertGreaterEqual(values["pitch.octave_jumps"]["value"], 1)
        self.assertEqual(values["pitch.tracker_disagreement"]["value"], 0.0)
        self.assertGreater(values["pitch.register_offset_st"]["value"], 0)
        self.assertNotIn("pitch.tone_run_seconds", values)
        # The register offset is measured from the clone reference only: none without one.
        plain = features.pitch_features(self.take(), results, {"referencePitch": {"r" * 64: 0.0}}, config()["params"])
        self.assertIsNone(plain["pitch.register_offset_st"]["value"])
        self.assertGreaterEqual(plain["pitch.octave_jumps"]["value"], 1)
        # build_context measures each reference clip's register on the clip itself.
        context = features.build_context({"r" * 64: results}, config()["params"])
        self.assertEqual(set(context), {"referencePitch"})
        self.assertIn("r" * 64, context["referencePitch"])

    def test_speaker_drift_against_the_clone_reference(self):
        reference = [1.0, 0.0, 0.0]
        speaker = {"windowSeconds": 3, "hopSeconds": 1, "whole": [0.9, 0.1, 0.0], "reference": reference,
                   "windows": [{"start": 0, "end": 3, "embedding": [1.0, 0.0, 0.0]},
                               {"start": 1, "end": 4, "embedding": [0.0, 1.0, 0.0]}]}
        values = features.speaker_features(self.take(), {"speaker": self.result(speaker)})
        self.assertAlmostEqual(values["speaker.max_window_distance"]["value"], 1.0)
        self.assertEqual(values["speaker.max_window_distance"]["start"], 1)
        self.assertGreater(values["speaker.whole_distance"]["value"], 0)
        self.assertGreater(values["speaker.window_range"]["value"], 0.5)
        # Without a clone reference there is nothing to drift from: only the window spread remains.
        plain = features.speaker_features(self.take(), {"speaker": self.result(dict(speaker, reference=None))})
        self.assertIsNone(plain["speaker.max_window_distance"]["value"])
        self.assertIsNone(plain["speaker.whole_distance"]["value"])
        self.assertGreater(plain["speaker.window_range"]["value"], 0.5)

class DetectorConfigTests(unittest.TestCase):
    def test_checked_in_config_is_valid(self):
        detectors.load_config(Layout(ROOT))

    def test_invalid_configs_are_refused(self):
        base = config()
        cases = []
        too_many = json.loads(json.dumps(base))
        too_many["detectors"][0]["features"] = too_many["detectors"][0]["features"] * 2
        cases.append(too_many)
        method = json.loads(json.dumps(base))
        method["detectors"][3]["method"] = "threshold"  # only the logistic remains
        cases.append(method)
        gate_lanes = json.loads(json.dumps(base))
        gate_lanes["detectors"][0]["gateLanes"] = ["no-such-lane"]
        cases.append(gate_lanes)
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
                                 {"name": "level.lufs", "direction": "lower"}]}
        norm = {"french": {"signal.clicks": {"mean": 1.0, "std": 1.0, "median": 1.0, "n": 10},
                           "level.lufs": {"mean": 4.0, "std": 0.5, "median": 4.0, "n": 10}}}
        take = {"signal.clicks": value(3), "level.lufs": value(3.0)}
        self.assertEqual(detectors.score(detector, take, "french", None, norm)["score"], 2.0)  # max oriented z
        fitted = {"models": {"*": {"intercept": -1.0, "weights": [1.0, 1.0], "cut": 0.5}}}
        outcome = detectors.score(detector, take, "french", fitted, norm)
        self.assertAlmostEqual(outcome["score"], detectors.sigmoid(-1 + 2 + 2))
        self.assertEqual(outcome["scope"], "*")
        missing = detectors.score(detector, {"level.lufs": value(3.0)}, "french", fitted, norm)
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
        self.phones = dict(self.asr, id="phones.zipa-large-crctc-500k", kind="phones", runtime="onnx")
        self.layout.registry.write_text(json.dumps({"schemaVersion": 1, "models": [self.asr, self.phones]}))
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
        self.excerpt_phones = []

    def tearDown(self):
        self.directory.cleanup()

    def fake_runner(self, model, takes, options=None, *, layout, echo, **kwargs):
        identity = runtime.runner_identity(layout, model)
        report = runtime.RunnerReport(model=model["id"], runner_sha=identity)
        self.calls.append([take["token"] for take in takes])
        for take in takes:
            if model.get("kind") == "phones":  # a pause cut out alone (`gap…`) hears self.excerpt_phones
                outputs = {"phones": list(self.excerpt_phones) if take["token"].startswith("gap") else [],
                           "frameSeconds": 0.02}
            else:
                outputs = {"text": "De fait, les branches.", "language": "French", "languageProbs": None,
                           "words": None}
            store.write_result(layout.results_dir(model["id"]), model=model["id"], runner_sha=identity,
                               audio_sha=take["audioSHA256"], variant=None, duration_seconds=1.0, outputs=outputs)
            report.ran += 1
        return report

    def run_lane(self, lane="pool", roles=("asrA",)):
        return lanes.run(self.layout, str(self.manifest), lane, roles=list(roles), runner=self.fake_runner,
                         echo=lambda line: None)

    def test_run_flags_the_dylan_take_with_evidence_and_confirms_the_gap(self):
        directory = self.run_lane(roles=("asrA", "phones"))
        flags = store.read_json(directory / "flags.json")
        by_take = {take["takeID"]: take for take in flags["takes"]}
        dylan = {flag["detector"]: flag for flag in by_take["fr-0101--dylan"]["flags"]}
        self.assertIn("pause.anomalous", dylan)
        self.assertNotIn("boundary.cutoff", dylan)  # no provisional rule: it ranks, never flags
        self.assertEqual(dylan["pause.anomalous"]["level"], "report-only")
        evidence = {item["feature"]: item for item in dylan["pause.anomalous"]["evidence"]}
        self.assertAlmostEqual(evidence["pause.longest_gap_seconds"]["start"], 3.39, delta=0.02)
        self.assertEqual(evidence["pause.excerpt_phones"]["value"], 0.0)
        self.assertEqual(flags["models"]["excerptTest"], {"candidates": 1, "tested": 1, "empty": 1})
        self.assertEqual(len(self.calls), 3)  # the takes (asrA, phones), then the pause cut out alone
        self.assertTrue(all(token.startswith("gap") for token in self.calls[-1]))
        aiden = {flag["detector"] for flag in by_take["fr-0102--aiden"]["flags"]}
        self.assertNotIn("pause.anomalous", aiden)
        features_doc = store.read_json(directory / "features.json")
        self.assertTrue(features_doc["models"]["asrA"]["available"])
        self.assertTrue(features_doc["models"]["phones"]["available"])
        self.assertFalse(features_doc["models"]["phonesB"]["available"])  # not registered here
        self.assertEqual(lanes.gate(self.layout, "pool"), lanes.EXIT_PASS)  # report-only never gates

    def test_phones_heard_in_the_pause_alone_clear_the_pause_flag(self):
        self.excerpt_phones = [{"phone": "t", "start": 0.0, "end": 0.04, "prob": 0.9},
                               {"phone": "h", "start": 0.1, "end": 0.14, "prob": 0.9},  # breath-like: ignored
                               {"phone": "y", "start": 0.2, "end": 0.24, "prob": 0.3}]  # below the floor
        directory = self.run_lane(roles=("asrA", "phones"))
        flags = store.read_json(directory / "flags.json")
        dylan = next(take for take in flags["takes"] if take["takeID"] == "fr-0101--dylan")
        self.assertNotIn("pause.anomalous", {flag["detector"] for flag in dylan["flags"]})
        self.assertEqual(flags["models"]["excerptTest"], {"candidates": 1, "tested": 1, "empty": 0})
        row = next(row for row in store.read_json(directory / "features.json")["takes"]
                   if row["takeID"] == "fr-0101--dylan")
        self.assertEqual(row["features"]["pause.excerpt_phones"]["value"], 1.0)

    def write_evaluated_thresholds(self, levels):
        """Thresholds fitted on the current scoring identity, and their evaluation's French levels."""

        thresholds = {"schema": "vocello.qc.thresholds/2", "version": 1, "models": {}, "normalization": {},
                      "scoringSHA256": detectors.scoring_identity(self.layout)["sha256"],
                      "detectors": {detector["id"]: {"reportOnly": True} for detector in config()["detectors"]}}
        path = self.layout.config / "thresholds-v1.json"
        store.write_json_atomic(path, thresholds)
        evaluation = {"version": 1, "thresholdsSHA256": store.sha256_file(path), "detectors": {
            detector: {"languages": {"french": {"level": level}}} for detector, level in levels.items()}}
        store.write_json_atomic(self.root / "benchmarks/qc/eval-v1.json", evaluation)

    def gate_line(self, lane):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = lanes.gate(self.layout, lane)
        return code, output.getvalue()

    def test_gate_levels_come_from_the_evaluation_of_the_thresholds(self):
        self.run_lane("clone")
        # level.loudness: the synths sit near -30 LUFS; boundary.cutoff has no provisional rule to flag with
        self.write_evaluated_thresholds({"pause.anomalous": "fail", "level.loudness": "warn"})
        self.run_lane("clone")
        self.assertEqual(lanes.gate(self.layout, "clone"), lanes.EXIT_FAIL)
        self.write_evaluated_thresholds({"pause.anomalous": "report-only", "level.loudness": "warn"})
        self.run_lane("clone")
        self.assertEqual(lanes.gate(self.layout, "clone"), lanes.EXIT_WARN)
        self.assertEqual(lanes.gate(self.layout, "no-such-lane"), lanes.EXIT_ERROR)

    def test_thresholds_of_other_scoring_code_leave_a_run_report_only(self):
        self.write_evaluated_thresholds({"pause.anomalous": "fail"})
        directory = self.run_lane("clone")
        identity = detectors.scoring_identity(self.layout)
        self.assertEqual(store.read_json(directory / "features.json")["scoringSHA256"], identity["sha256"])
        self.assertEqual(store.read_json(directory / "flags.json")["thresholdsReason"], None)
        self.assertEqual(self.gate_line("clone")[0], lanes.EXIT_FAIL)

        # Editing a detector's feature list changes the scoring identity.
        path = self.layout.config / "detectors.json"
        original = path.read_text()
        document = json.loads(original)
        pause = next(item for item in document["detectors"] if item["id"] == "pause.anomalous")
        pause["features"] = pause["features"][:3]
        path.write_text(json.dumps(document, indent=2))
        directory = self.run_lane("clone")
        flags = store.read_json(directory / "flags.json")
        self.assertFalse(flags["thresholdsApplied"])
        self.assertEqual(flags["thresholdsReason"], "thresholds-v1.json was fitted with other scoring code "
                                                    "(feature, detector, phone or pitch code, detectors.json "
                                                    "or norms)")
        code, line = self.gate_line("clone")
        self.assertEqual(code, lanes.EXIT_PASS)
        self.assertIn("(report-only: thresholds-v1.json was fitted with other scoring code", line)

        # So does an edit of the feature code (here a features.py the identity did not hold before).
        path.write_text(original)
        self.run_lane("clone")
        self.assertEqual(self.gate_line("clone")[0], lanes.EXIT_FAIL)
        (self.root / "scripts/qc/features.py").write_text("# edited feature code\n")
        self.assertNotEqual(detectors.scoring_identity(self.layout)["sha256"], identity["sha256"])
        directory = self.run_lane("clone")
        self.assertIn("other scoring code", store.read_json(directory / "flags.json")["thresholdsReason"])
        self.assertEqual(self.gate_line("clone")[0], lanes.EXIT_PASS)

        # A new norms file is part of the identity too.
        (self.root / "scripts/qc/features.py").unlink()
        store.write_json_atomic(self.layout.config / "norms-v1.json", {"schema": "vocello.qc.norms/1",
                                                                        "languages": {}})
        norms_identity = detectors.scoring_identity(self.layout)
        self.assertEqual(norms_identity["norms"]["file"], "norms-v1.json")
        self.assertNotEqual(norms_identity["sha256"], identity["sha256"])

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
