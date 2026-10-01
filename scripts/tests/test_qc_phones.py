"""QC v2 phone tools: IPA normalization, CTC decoding, alignment, GOP-SF, stutter features, G2P cache.

Pure NumPy: no model, no espeak-ng (a fake engine stands in), no PanPhon package (a small table in
PanPhon's CSV format stands in for the pinned one).
"""

from __future__ import annotations

import io
import itertools
import json
import math
import stat
import sys
import tempfile
import unicodedata
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qc import phones  # noqa: E402
from qc.runners import espeak_g2p  # noqa: E402


def nfd(text: str) -> str:
    return unicodedata.normalize("NFD", text)


def broad(ipa: str, **options) -> list[str]:
    return phones.normalize(phones.segment_ipa(ipa), **options)


def peaky(sequence: list[int], vocab_size: int, *, frames_per_token: int = 2, gap: int = 1,
          peak: float = 0.96) -> np.ndarray:
    """Log-posteriors that spell `sequence` (blank 0 between tokens), like a confident CTC model."""

    path = [0] * gap
    for token in sequence:
        path += [token] * frames_per_token + [0] * gap
    rest = (1.0 - peak) / (vocab_size - 1)
    probs = np.full((len(path), vocab_size), rest)
    probs[np.arange(len(path)), path] = peak
    return np.log(probs)


class FakeEngine:
    name = "fake-espeak"
    version = "test"

    def __init__(self, table: dict[str, str]) -> None:
        self.table = table
        self.calls = 0

    def phonemize(self, text: str, voice: str) -> str:
        self.calls += 1
        return self.table[text]


def write_feature_table(directory: Path) -> Path:
    """A PanPhon-format table for a few segments (features: syl son cons voi lab cor nas)."""

    data = directory / "panphon/data"
    data.mkdir(parents=True)
    rows = [
        "ipa,syl,son,cons,voi,lab,cor,nas",
        "b,-,-,+,+,+,-,-", "p,-,-,+,-,+,-,-", "m,-,+,+,+,+,-,+", "t,-,-,+,-,-,+,-",
        "d,-,-,+,+,-,+,-", "a,+,+,-,+,-,-,-", "ɑ̃,+,+,-,+,-,-,+", "ɡ,-,-,+,+,-,-,-",
    ]
    (data / "ipa_all.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    (data / "feature_weights.csv").write_text("syl,son,cons,voi,lab,cor,nas\n1,1,1,0.5,0.5,0.5,0.5\n",
                                              encoding="utf-8")
    return directory


class NormalizationTests(unittest.TestCase):
    def test_segmentation_drops_stress_ties_tones_and_boundaries(self):
        self.assertEqual(phones.segment_ipa("ˈt͡ʃɑɹ"), ["t", "ʃ", "ɑ", "ɹ"])
        self.assertEqual(phones.segment_ipa("tʰjɛn˨˩˦"), ["tʰ", "j", "ɛ", "n"])
        self.assertEqual(phones.segment_ipa("le bʁˈɑ̃ʃ"), ["l", "e", "b", "ʁ", nfd("ɑ̃"), "ʃ"])
        self.assertEqual(phones.segment_ipa("aː.ba"), ["aː", "b", "a"])
        self.assertEqual(phones.segment_ipa("(en)hɛloʊ(fr)"), ["h", "ɛ", "l", "o", "ʊ"])

    def test_broad_normalization_map(self):
        cases = {
            "ɡ": ["g"], "aː": ["a"], "ɚ": ["ə"], "ɝ": ["ɜ"], "ʧ": ["t", "ʃ"], "ʦ": ["t", "s"], "t͡s": ["t", "s"],
            "ã": [nfd("ã")], "ç": ["ç"], "ka̠ɡa̠": ["k", "a", "g", "a"], "tS": ["t", "ʃ"], "i5": ["i"],
            "aɪ": ["a", "ɪ"], "ᵻ": ["ɪ"], "pʰ": ["pʰ"], "l̩": ["l"], "ɫ": ["l"], "ɛ̝": ["ɛ"], "u:": ["u"],
            "ʁ": ["r"], "ɾ": ["r"], "ɹ": ["r"], "r": ["r"], "rʲ": ["rʲ"], "ə˞": ["ə"], "s.": ["s"],
        }
        for ipa, expected in cases.items():
            with self.subTest(ipa=ipa):
                self.assertEqual(broad(ipa), expected)

    def test_keep_rhotics_keeps_the_accent_signal(self):
        self.assertEqual(broad("ʁ", keep_rhotics=True), ["ʁ"])
        self.assertEqual(broad("ɹ", keep_rhotics=True), ["ɹ"])
        self.assertNotEqual(broad("bʁɑ̃ʃ", keep_rhotics=True), broad("bɹɑ̃ʃ", keep_rhotics=True))
        self.assertEqual(broad("bʁɑ̃ʃ"), broad("bɹɑ̃ʃ"))

    def test_nasal_vowels_and_marks_attach_to_their_base(self):
        self.assertEqual(phones.normalize_phone("ɔ̃"), [nfd("ɔ̃")])
        self.assertEqual(phones.normalize_phone("ʲ"), [])  # a bare mark has no base

    def test_espeak_and_zipa_spellings_meet(self):
        vocab = ["<blk>", "▁", "b", "ʁ", "ɑ", "̃", "ʃ", "ː", "ɡ"]
        heard = phones.ctc_greedy(peaky([1, 2, 3, 4, 5, 6], len(vocab)), vocab, 0.04)
        self.assertEqual([item["phone"] for item in phones.recognized_phones(heard)], broad("bʁˈɑ̃ʃ"))


class CtcGreedyTests(unittest.TestCase):
    VOCAB = ["<blk>", "▁", "b", "ʁ", "ɑ", "̃", "ʃ", "ː", "a", "<sos/eos>"]

    def test_collapses_runs_merges_modifiers_and_times_frames(self):
        result = phones.ctc_greedy(peaky([1, 2, 4, 5, 7, 6], len(self.VOCAB), frames_per_token=2, gap=1),
                                   self.VOCAB, 0.04)
        self.assertEqual([item["phone"] for item in result], ["b", "ɑ̃ː", "ʃ"])
        self.assertEqual((result[0]["start"], result[0]["end"]), (0.16, 0.24))
        self.assertEqual((result[1]["start"], result[1]["end"]), (0.28, 0.6))  # through the ː frames
        self.assertAlmostEqual(result[0]["prob"], 0.96, places=3)

    def test_modifier_after_a_boundary_is_dropped(self):
        result = phones.ctc_greedy(peaky([1, 7, 8], len(self.VOCAB)), self.VOCAB, 0.04)
        self.assertEqual([item["phone"] for item in result], ["a"])

    def test_repeated_phone_needs_a_blank_between(self):
        result = phones.ctc_greedy(peaky([8, 8], len(self.VOCAB), gap=1), self.VOCAB, 0.02)
        self.assertEqual([item["phone"] for item in result], ["a", "a"])

    def test_rejects_a_mismatched_vocabulary(self):
        with self.assertRaises(ValueError):
            phones.ctc_greedy(np.zeros((3, 4)), ["<blk>", "a"], 0.04)

    def test_token_kinds(self):
        kinds = {"<blk>": "special", "▁": "boundary", "|": "boundary", "ː": "modifier", "̃": "modifier",
                 "ʰ": "modifier", "??": "special", "1": "special", "aɪ": "phone", "i5": "phone", "ǀ": "phone"}
        for token, kind in kinds.items():
            with self.subTest(token=token):
                self.assertEqual(phones.token_kind(token), kind)

    def test_multi_phone_tokens_split_their_span(self):
        heard = phones.recognized_phones([{"phone": "aɪ", "start": 0.0, "end": 0.1, "prob": 0.9}])
        self.assertEqual([(item["phone"], item["start"], item["end"]) for item in heard],
                         [("a", 0.0, 0.05), ("ɪ", 0.05, 0.1)])


class AlignTests(unittest.TestCase):
    def setUp(self):
        self.distance = phones.coarse_distance

    def heard(self, ipa: str, step: float = 0.1) -> list[dict]:
        return [{"phone": phone, "start": round(i * step, 3), "end": round((i + 1) * step, 3)}
                for i, phone in enumerate(broad(ipa))]

    def test_identical_sequences_match(self):
        ops = phones.align(broad("vjø"), self.heard("vjø"), distance=self.distance)
        self.assertEqual([op["op"] for op in ops], ["match"] * 3)

    def test_deletion_takes_the_gap_between_neighbours(self):
        ops = phones.align(broad("ɔʁm"), self.heard("ɔm"), distance=self.distance)
        self.assertEqual([op["op"] for op in ops], ["match", "del", "match"])
        self.assertEqual((ops[1]["start"], ops[1]["end"]), (0.1, 0.1))
        self.assertEqual(ops[1]["expected"], "r")

    def test_insertion_and_substitution(self):
        ops = phones.align(["b", "a"], self.heard("pba"), distance=self.distance)
        self.assertEqual([op["op"] for op in ops], ["ins", "match", "match"])
        ops = phones.align(["b", "a"], self.heard("pa"), distance=self.distance)
        self.assertEqual([op["op"] for op in ops], ["sub", "match"])
        self.assertEqual(ops[0]["cost"], 0.6)

    def test_empty_sides(self):
        self.assertEqual([op["op"] for op in phones.align([], self.heard("ab"), distance=self.distance)], ["ins", "ins"])
        self.assertEqual([op["op"] for op in phones.align(["a"], [], distance=self.distance)], ["del"])

    def test_panphon_table_distance(self):
        with tempfile.TemporaryDirectory() as temporary:
            features = phones.load_phone_features(write_feature_table(Path(temporary)))
            self.assertIsNotNone(features)
            self.assertEqual(features.distance("b", "b"), 0.0)
            self.assertLess(features.distance("b", "p"), features.distance("b", "a"))
            self.assertLess(features.distance("a", nfd("ɑ̃")), features.distance("a", "t"))
            self.assertEqual(features.distance("g", "b"), features.distance("ɡ", "b"))  # ASCII g → PanPhon's ɡ
            self.assertEqual(features.distance("b", "ʃ"), phones.coarse_distance("b", "ʃ"))  # unknown → coarse
            self.assertTrue(0.0 <= features.distance("a", "t") <= 1.0)
            distance, source = phones.default_distance(temporary)
            self.assertEqual(source, "panphon")
            self.assertEqual(phones.default_distance(Path(temporary) / "missing")[1], "coarse")


def brute_force(scores: np.ndarray, accept) -> float:
    total = 0.0
    frames, width = scores.shape
    for path in itertools.product(range(width), repeat=frames):
        collapsed = [token for token, _ in itertools.groupby(path) if token != 0]
        if accept(collapsed):
            total += math.exp(sum(scores[t, token] for t, token in enumerate(path)))
    return math.log(total)


class GopTests(unittest.TestCase):
    def random_scores(self, seed: int, frames: int = 6, width: int = 4) -> np.ndarray:
        values = np.random.default_rng(seed).normal(size=(frames, width))
        return values - np.log(np.exp(values).sum(axis=1, keepdims=True))

    def test_ctc_likelihood_matches_enumeration(self):
        scores = self.random_scores(1)
        for tokens in ([1, 2], [1, 1], [3], [1, 2, 3]):
            with self.subTest(tokens=tokens):
                self.assertAlmostEqual(phones.ctc_log_likelihood(scores, tokens),
                                       brute_force(scores, lambda seq, t=tokens: seq == t), places=9)

    def test_free_term_matches_enumeration(self):
        for seed, tokens in ((2, [1, 2, 3]), (3, [1, 1, 2]), (4, [2, 3, 2]), (5, [1, 2])):
            scores = self.random_scores(seed)
            states = np.array([0] + [item for token in tokens for item in (token, 0)])
            emissions = scores[:, states]
            skip = np.array([s % 2 == 1 and s >= 3 and states[s] != states[s - 2] for s in range(len(states))])
            alpha, beta = phones._ctc_alpha(emissions, skip), phones._ctc_beta(emissions, skip)
            for first in range(len(tokens)):
                prefix, suffix = tokens[:first], tokens[first + 1:]

                def accept(seq, prefix=prefix, suffix=suffix):
                    return (len(seq) >= len(prefix) + len(suffix) and seq[:len(prefix)] == prefix
                            and seq[len(seq) - len(suffix):] == suffix)

                with self.subTest(seed=seed, tokens=tokens, free=first):
                    self.assertAlmostEqual(
                        phones._free_log_prob(alpha, beta, scores, tokens, first, first + 1),
                        brute_force(scores, accept), places=9)

    def test_clean_take_scores_near_zero(self):
        vocab = ["<blk>", "a", "b", "c", "d"]
        result = phones.gop(peaky([1, 2, 3], len(vocab)), vocab, ["a", "b", "c"], frame_seconds=0.04)
        values = [entry["gop"] for entry in result["phones"]]
        self.assertTrue(all(-0.5 < value <= 0.0 for value in values), values)
        self.assertEqual(result["frames"], 10)
        self.assertEqual((result["phones"][1]["start"], result["phones"][1]["end"]), (0.16, 0.24))
        self.assertGreater(result["phones"][1]["occupancy"], 1.5)

    def test_substituted_and_missing_phones_score_low(self):
        vocab = ["<blk>", "a", "b", "c", "d"]
        swapped = phones.gop(peaky([1, 4, 3], len(vocab)), vocab, ["a", "b", "c"])
        values = [entry["gop"] for entry in swapped["phones"]]
        self.assertLess(values[1], -5.0)
        self.assertGreater(values[0], values[1] + 3)
        self.assertGreater(values[2], values[1] + 3)
        missing = phones.gop(peaky([1, 3], len(vocab)), vocab, ["a", "b", "c"])
        values = [entry["gop"] for entry in missing["phones"]]
        self.assertLess(values[1], math.log(0.1))  # below the default low-GOP threshold
        self.assertGreater(min(values[0], values[2]), values[1] + 2)

    def test_vocabulary_merges_onto_broad_labels(self):
        vocab = ["<blk>", "▁", "b", "ʁ", "ɑ", "̃", "ʃ", "ː"]
        labels, groups, folded = phones.ctc_labels(vocab)
        self.assertIn("̃", labels)
        self.assertEqual(sorted(folded), [0, 1, 7])  # blank, ▁ and the dropped length mark
        result = phones.gop(peaky([1, 2, 3, 4, 5, 6], len(vocab)), vocab, phones.segment_ipa("bʁɑ̃ʃ"))
        self.assertEqual([entry["phone"] for entry in result["phones"]], ["b", "ʁ", nfd("ɑ̃"), "ʃ"])
        self.assertTrue(all(entry["gop"] > -0.5 for entry in result["phones"]))
        wav2vec = ["<pad>", "<s>", "a", "aɪ", "i5", "iː", "t"]
        labels, groups, _ = phones.ctc_labels(wav2vec)
        self.assertEqual(groups[labels.index("i")], [4, 5])

    def test_multi_phone_labels_cover_both_phones(self):
        vocab = ["<pad>", "aɪ", "t"]
        result = phones.gop(peaky([2, 1, 2], len(vocab)), vocab, ["t", "a", "ɪ", "t"])
        self.assertEqual([entry["gop"] is not None for entry in result["phones"]], [True] * 4)
        self.assertEqual(result["phones"][1]["gop"], result["phones"][2]["gop"])

    def test_inexpressible_phone_and_too_short_input(self):
        vocab = ["<blk>", "a", "b"]
        result = phones.gop(peaky([1, 2], len(vocab)), vocab, ["a", "χ", "b"])
        self.assertIsNone(result["phones"][1]["gop"])
        short = phones.gop(np.log(np.full((1, 3), 1 / 3)), vocab, ["a", "b"])
        self.assertIsNone(short["logLikelihood"])
        self.assertIsNone(short["phones"][0]["gop"])


class StutterTests(unittest.TestCase):
    SCRIPT = "le bʁɑ̃ʃ de vjø ɔʁm"

    def heard(self, ipa: str) -> list[dict]:
        return [{"phone": phone, "start": round(i * 0.08, 3), "end": round((i + 1) * 0.08, 3)}
                for i, phone in enumerate(broad(ipa))]

    def features(self, script: str, heard: str, **options) -> dict:
        ops = phones.align(broad(script), self.heard(heard), distance=phones.coarse_distance)
        return phones.stutter_features(ops, distance=phones.coarse_distance, **options)

    def test_near_identity_follows_the_distance_scale(self):
        # A PanPhon-scaled distance puts different phones well under the coarse fallback's 0.25 (l/r
        # near 0.09), so with that cutoff "l e b" would pass for a copy of "r ɑ̃ b". The default cutoff
        # follows the distance, so only the true repetition counts.
        def small_scale(a: str, b: str) -> float:
            return 0.0 if a == b else (0.02 if {a, b} in ({"b", "p"}, {"s", "z"}) else 0.09)

        script = "le bʁɑ̃ʃ de"
        ops = phones.align(broad(script), self.heard("le bʁɑ̃ bʁɑ̃ʃ de"), distance=small_scale)
        runs = phones.stutter_features(ops, distance=small_scale)["repeatRuns"]
        self.assertEqual([(run["phones"], run["start"]) for run in runs], [(["b", "r", nfd("ɑ̃")], 0.16)])

    def test_repeated_syllable_is_a_run_and_a_burst(self):
        result = self.features(self.SCRIPT, "le bʁɑ̃ bʁɑ̃ʃ de vjø ɔʁm")
        self.assertEqual(result["repeatCount"], 1)
        run = result["repeatRuns"][0]
        self.assertEqual((run["n"], run["copies"], run["phones"]), (3, 2, ["b", "r", nfd("ɑ̃")]))
        self.assertEqual(run["start"], 0.16)
        self.assertEqual(len(result["insertionBursts"]), 1)
        self.assertEqual(result["insertionBursts"][0]["count"], 3)
        self.assertEqual(result["deletions"], 0)

    def test_missing_phones_raise_the_deletion_rate(self):
        result = self.features(self.SCRIPT, "le bʁɔʃ de vjø ɔm")
        self.assertEqual(result["expectedCount"], 14)
        self.assertEqual(result["deletions"], 1)
        self.assertEqual(result["deletionRate"], round(1 / 14, 4))
        self.assertEqual(result["substitutions"], 1)
        self.assertEqual(result["repeatCount"], 0)

    def test_missing_syllable_is_a_deletion_run(self):
        result = self.features("de bʁɑ̃ʃ", "de ʃ")
        self.assertEqual(result["maxDeletionRun"], 3)
        self.assertEqual(result["deletionRuns"][0]["phones"], ["b", "r", nfd("ɑ̃")])

    def test_repetition_in_the_script_is_not_a_stutter(self):
        self.assertEqual(self.features("no no no", "no no no")["repeatCount"], 0)

    def test_single_phone_repeats_need_three_copies(self):
        self.assertEqual(self.features("ba", "bba")["repeatCount"], 0)
        result = self.features("ba", "bbba")
        self.assertEqual(result["repeatCount"], 1)
        self.assertEqual(result["repeatRuns"][0]["copies"], 3)

    def test_low_gop_spans(self):
        gop = {"phones": [
            {"index": 0, "phone": "a", "gop": -0.1, "start": 0.0, "end": 0.1},
            {"index": 1, "phone": "b", "gop": -4.0, "start": 0.1, "end": 0.2},
            {"index": 2, "phone": "c", "gop": -6.0, "start": 0.2, "end": 0.3},
            {"index": 3, "phone": "d", "gop": None},
            {"index": 4, "phone": "e", "gop": -3.0, "start": 0.4, "end": 0.5},
        ]}
        result = phones.stutter_features([], gop=gop, distance=phones.coarse_distance)
        self.assertEqual([(span["count"], span["phones"]) for span in result["lowGopSpans"]],
                         [(2, ["b", "c"]), (1, ["e"])])
        self.assertEqual(result["lowGopSpans"][0]["meanGop"], -5.0)
        self.assertEqual(result["lowGopFraction"], 0.75)
        self.assertEqual(result["minGop"], -6.0)

    def test_times_fill_ops_without_times(self):
        times = [{"start": round(i * 0.1, 3), "end": round((i + 1) * 0.1, 3)} for i in range(5)]
        ops = phones.align(["d", "e", "a"], ["d", "a"], distance=phones.coarse_distance)
        self.assertIsNone(ops[0]["start"])
        result = phones.stutter_features(ops, times, distance=phones.coarse_distance, min_deletion_run=1)
        self.assertEqual(result["deletionRuns"][0]["phones"], ["e"])
        self.assertEqual((result["deletionRuns"][0]["start"], result["deletionRuns"][0]["end"]), (0.1, 0.1))
        ops = phones.align(["d", "a", "b"], ["d", "a", "b", "a", "b"], distance=phones.coarse_distance)
        result = phones.stutter_features(ops, times, distance=phones.coarse_distance)
        self.assertEqual(result["repeatRuns"][0]["phones"], ["a", "b"])
        self.assertEqual((result["repeatRuns"][0]["start"], result["repeatRuns"][0]["end"]), (0.1, 0.5))

    def test_compare_runs_the_whole_pipeline(self):
        vocab = ["<blk>", "▁", "l", "e", "b", "ʁ", "ɑ", "̃", "ʃ"]
        spoken = [1, 2, 3, 4, 5, 6, 7, 4, 5, 6, 7, 8]  # "le bʁɑ̃ bʁɑ̃ʃ"
        scores = peaky(spoken, len(vocab))
        heard = phones.ctc_greedy(scores, vocab, 0.04)
        result = phones.compare(phones.segment_ipa("le bʁɑ̃ʃ"), heard, logprobs=scores, vocab=vocab,
                                frame_seconds=0.04, model_dir=Path(tempfile.gettempdir()) / "qc-no-panphon")
        self.assertEqual(result["distance"], "coarse")
        self.assertEqual(result["features"]["repeatCount"], 1)
        self.assertEqual(len(result["gop"]["phones"]), 6)
        self.assertLess(min(entry["gop"] for entry in result["gop"]["phones"]), -1.0)


class G2PTests(unittest.TestCase):
    TABLE = {"les branches": "le bʁˈɑ̃ʃ", "hello world": "(en)həlˈoʊ wˈɜːld(fr)", "bonjour": "bɔ̃ʒˈuʁ"}

    def test_record_is_cached_by_language_and_text(self):
        engine = FakeEngine(self.TABLE)
        with tempfile.TemporaryDirectory() as cache:
            record = phones.g2p_record("les branches", "french", cache_dir=cache, engine=engine)
            self.assertEqual(record["schema"], espeak_g2p.G2P_SCHEMA)
            self.assertEqual(record["phones"], ["l", "e", "b", "ʁ", nfd("ɑ̃"), "ʃ"])
            self.assertEqual([word["ipa"] for word in record["words"]], ["le", "bʁˈɑ̃ʃ"])
            path = Path(cache) / f"{espeak_g2p.g2p_key('les branches', 'french')}.json"
            self.assertTrue(path.is_file())
            self.assertEqual(phones.g2p("les branches", "french", cache_dir=cache, compute=False), record["phones"])
            self.assertEqual(engine.calls, 1)
            with self.assertRaises(phones.G2PCacheMiss):
                phones.g2p("bonjour", "french", cache_dir=cache, compute=False)

    def test_key_depends_on_language_and_text(self):
        key = espeak_g2p.g2p_key("bonjour", "french")
        self.assertEqual(len(key), 64)
        self.assertEqual(key, espeak_g2p.g2p_key("bonjour", "french"))
        self.assertNotEqual(key, espeak_g2p.g2p_key("bonjour", "english"))
        self.assertNotEqual(key, espeak_g2p.g2p_key("Bonjour", "french"))

    def test_language_switch_markers_are_removed(self):
        engine = FakeEngine(self.TABLE)
        self.assertEqual(phones.g2p_espeak("hello world", "english", engine=engine),
                         ["h", "ə", "l", "o", "ʊ", "w", "ɜː", "l", "d"])

    def test_unsupported_language(self):
        with self.assertRaises(ValueError):
            phones.g2p_record("hola", "klingon", cache_dir=tempfile.gettempdir(), engine=FakeEngine({}))

    def test_every_repository_language_has_an_espeak_voice(self):
        self.assertEqual(sorted(phones.ESPEAK_VOICES), sorted(phones.LANGUAGES))

    def test_job_fills_the_cache_and_writes_take_results(self):
        engine = FakeEngine(self.TABLE)
        with tempfile.TemporaryDirectory() as cache:
            job = {"model": phones.G2P_MODEL_ID, "modelDir": cache, "outputDir": cache, "runnerSHA256": "f" * 64,
                   "options": {}, "takes": [
                       {"token": "t1", "audio": "unused.wav", "audioSHA256": "a" * 64, "language": "french",
                        "text": "les branches", "variantKey": None},
                       {"token": "t2", "audio": "unused.wav", "audioSHA256": "b" * 64, "language": "french",
                        "text": None, "variantKey": None}]}
            with redirect_stdout(io.StringIO()) as stdout:
                code = espeak_g2p.run_g2p_job(job, engine=engine)
            self.assertEqual(code, 1)  # the take without a script failed
            self.assertEqual(stdout.getvalue().splitlines(), ["progress 1/1"])
            first = json.loads((Path(cache) / f"{'a' * 64}.json").read_text(encoding="utf-8"))
            self.assertEqual(first["schema"], "vocello.qc.result/1")
            self.assertEqual(first["outputs"]["phones"], ["l", "e", "b", "ʁ", nfd("ɑ̃"), "ʃ"])
            second = json.loads((Path(cache) / f"{'b' * 64}.json").read_text(encoding="utf-8"))
            self.assertEqual(second["error"], "text-missing")

    def test_job_entries_refuse_an_unreadable_job(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "job.json"
            path.write_text("{}", encoding="utf-8")
            with redirect_stderr(io.StringIO()):
                self.assertEqual(phones.main(["--g2p-job", str(path)]), 2)
                self.assertEqual(espeak_g2p.main(["--job", str(path)]), 2)

    def test_job_without_an_engine_exits_2(self):
        try:
            espeak_g2p.default_engine()
        except phones.G2PUnavailable:
            with tempfile.TemporaryDirectory() as temporary, redirect_stderr(io.StringIO()):
                job = {"outputDir": temporary, "takes": []}
                self.assertEqual(espeak_g2p.run_g2p_job(job), 2)
        else:
            self.skipTest("an espeak-ng engine is available")

    def test_binary_engine_runs_espeak_as_a_subprocess(self):
        with tempfile.TemporaryDirectory() as temporary:
            script = Path(temporary) / "espeak-ng"
            script.write_text(f"#!{sys.executable}\nimport sys\nsys.stdin.read()\nprint(' bɔ̃ʒˈuʁ')\n",
                              encoding="utf-8")
            script.chmod(script.stat().st_mode | stat.S_IXUSR)
            engine = espeak_g2p.EspeakBinary(str(script))
            self.assertEqual(engine.phonemize("bonjour", "fr"), "bɔ̃ʒˈuʁ")
            self.assertEqual(phones.g2p_espeak("bonjour", "french", engine=engine), ["b", nfd("ɔ̃"), "ʒ", "u", "ʁ"])

    def test_library_engine_needs_the_loader(self):
        try:
            import espeakng_loader  # noqa: F401
        except ImportError:
            with self.assertRaises(phones.G2PUnavailable):
                espeak_g2p.EspeakLibrary()
        else:
            self.skipTest("espeakng-loader is installed")


if __name__ == "__main__":
    unittest.main()
