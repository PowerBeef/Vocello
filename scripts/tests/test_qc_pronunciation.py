"""No-model tests of narrow pronunciation hypotheses and retained CTC evidence."""
from __future__ import annotations

import itertools
import json
import math
import unittest

import numpy as np

from qc import phones, pronunciation


def peaky(sequence, width, peak=.95):
    path = [0]
    for token in sequence:
        path.extend([token, token, 0])
    values = np.full((len(path), width), (1-peak) / (width-1))
    values[np.arange(len(path)), path] = peak
    return np.log(values)


def heard(*items):
    return {"phones": [{"phone": phone, "start": i * .1, "end": (i+1) * .1}
                       for i, phone in enumerate(items)]}


def posterior(sequence, vocab):
    return {"logprobs": peaky(sequence, len(vocab)), "vocab": vocab, "frameSeconds": .02}


class PronunciationTests(unittest.TestCase):
    def test_clean_canonical_retains_raw_length_nasality_and_rhotic(self):
        expected = ["ʁ", "ɑ̃ː", "p"]
        data = posterior([1, 2, 3], ["<blk>", "ʁ", "ɑ̃ː", "p"])
        raw = heard(*expected)
        result = pronunciation.analyze(expected, [], {"phones": raw, "phonesB": raw},
                                       posteriors={"phones": data, "phonesB": data})
        self.assertEqual(result["inputStatus"], "complete")
        self.assertEqual(result["decision"], "not-assessed")
        self.assertEqual(result["nativeAccentDecision"], "not-assessed")
        role = result["roles"]["phones"]
        self.assertEqual(role["originalTokens"], raw["phones"])
        self.assertEqual(role["localizedCandidates"], [])
        fit = role["posterior"]
        self.assertEqual(fit["bestConstrainedPath"], "canonical")
        self.assertEqual(len(fit["expectedWindows"]), 3)
        self.assertEqual(fit["expectedWindowsStatus"], "complete")
        self.assertEqual(fit["expectedWindows"][1]["phone"], phones.segment_ipa("ɑ̃ː")[0])
        self.assertGreater(fit["meanEntropyNats"], 0)
        json.dumps(result, allow_nan=False)

    def test_reviewed_path_fit_and_canonical_windows_do_not_depend_on_emitted_error(self):
        # Greedy artifact still says canonical /ʁ/ while retained posterior favors /ɹ/.
        raw = heard("ʁ", "a")
        data = posterior([2, 3], ["<blk>", "ʁ", "ɹ", "a"])
        result = pronunciation.analyze(["ʁ", "a"], [], {"phones": raw}, posteriors={"phones": data},
                        alternatives=[{"id": "rhotic-comparison", "phones": ["ɹ", "a"],
                                       "reason": "reviewed comparison only; no accent verdict"}])
        role = result["roles"]["phones"]
        self.assertEqual(role["localizedCandidates"], [])
        fit = role["posterior"]
        self.assertEqual(fit["bestConstrainedPath"], "rhotic-comparison")
        self.assertEqual(fit["greedyLabels"], ["ɹ", "a"])
        self.assertEqual(fit["expectedWindows"][0]["phone"], "ʁ")
        self.assertFalse(role["posteriorGreedyMatchesArtifact"])
        self.assertEqual(result["decision"], "not-assessed")

    def test_optional_omission_is_an_explicit_unreviewed_hypothesis(self):
        expected = ["l", "e", "z", "a"]
        words = [{"phones": ["l", "e", "z"], "optional": [2]}, {"phones": ["a"]}]
        result = pronunciation.analyze(expected, words, {"phones": heard("l", "e", "a")},
                       posteriors={"phones": posterior([1, 2, 4], ["<blk>", "l", "e", "z", "a"])})
        self.assertEqual([p["phones"] for p in result["pronunciations"]], [expected, ["l", "e", "a"]])
        self.assertEqual(result["pronunciations"][1]["origin"], "g2p-optional-heuristic")
        self.assertEqual(result["pathCoverage"]["linguisticPermission"], "not-assessed")
        self.assertEqual(result["roles"]["phones"]["posterior"]["bestConstrainedPath"], "g2p-omit-2")
        # Canonical missing liaison is still visible; selecting a path never edits raw events.
        self.assertTrue(any(c["type"] == "deletion" for c in result["roles"]["phones"]["localizedCandidates"]))

    def test_unknown_phone_and_unknown_diacritic_do_not_disappear(self):
        for target in (["a", "χ"], ["ḁ"]):
            with self.subTest(target=target):
                result = pronunciation.analyze(target, [], {"phones": heard("a")},
                        posteriors={"phones": posterior([1], ["<blk>", "a"])})
                fit = result["roles"]["phones"]["posterior"]
                self.assertEqual(fit["paths"][0]["reason"], "out-of-inventory")
                self.assertFalse(fit["paths"][0]["fullInventoryCoverage"])
                self.assertIsNone(fit["bestConstrainedLogLikelihood"])
                self.assertEqual(fit["expectedWindows"], [])

    def test_base_modifier_and_combined_tokenizations_are_both_counted(self):
        vocab = ["<blk>", "ɑ", "̃", "ɑ̃"]
        values = np.log(np.array([[.1, .6, .1, .2], [.1, .1, .6, .2], [.6, .1, .1, .2]]))
        result = pronunciation.analyze(["ɑ̃"], [], {"phones": heard("ɑ̃")},
                       posteriors={"phones": {"logprobs": values, "vocab": vocab, "frameSeconds": .02}})
        fit = result["roles"]["phones"]["posterior"]["paths"][0]
        self.assertEqual(fit["tokenizations"], 2)
        mass = 0.
        for path in itertools.product(range(4), repeat=3):
            collapsed = [key for key, _ in itertools.groupby(path) if key != 0]
            if collapsed in ([1, 2], [3]):
                mass += math.exp(sum(values[i, token] for i, token in enumerate(path)))
        self.assertAlmostEqual(fit["logLikelihood"], math.log(mass), places=5)

    def test_impossible_repeated_ctc_tokens_are_unavailable(self):
        result = pronunciation.analyze(["a", "a"], [], {"phones": heard("a")},
                     posteriors={"phones": {"logprobs": np.log([[.1, .9]]),
                                            "vocab": ["<blk>", "a"], "frameSeconds": .02}})
        fit = result["roles"]["phones"]["posterior"]
        self.assertEqual(fit["paths"][0]["reason"], "ctc-impossible")
        self.assertEqual(fit["expectedWindows"], [])
        json.dumps(result, allow_nan=False)

    def test_single_witness_insertions_substitutions_and_repeats_survive_disagreement(self):
        expected = ["b", "ʁ", "a", "p"]
        result = pronunciation.analyze(expected, [], {
            "phones": heard("b", "ɹ", "a", "b", "ɹ", "a", "ə", "p"),
            "phonesB": heard(*expected)})
        candidates = result["roles"]["phones"]["localizedCandidates"]
        self.assertTrue({"insertion", "substitution", "repeat"} <= {c["type"] for c in candidates})
        self.assertTrue(all(c["evidenceStatus"] == "single-witness" for c in candidates))
        self.assertEqual(result["roles"]["phonesB"]["localizedCandidates"], [])
        self.assertEqual(result["decision"], "not-assessed")

    def test_no_posteriors_and_missing_role_are_explicit(self):
        result = pronunciation.analyze(["a"], [], {"phones": heard("a")})
        self.assertEqual(result["inputStatus"], "partial")
        self.assertEqual(result["roles"]["phones"]["posterior"]["reason"], "missing-posteriors")
        self.assertEqual(result["roles"]["phonesB"]["inputStatus"], "unavailable")

    def test_posteriors_without_greedy_artifact_still_supply_expected_windows(self):
        result = pronunciation.analyze(["a"], [], {},
                       posteriors={"phones": posterior([1], ["<blk>", "a"])})
        self.assertEqual(result["inputStatus"], "partial")
        self.assertEqual(len(result["roles"]["phones"]["posterior"]["expectedWindows"]), 1)

    def test_invalid_arrays_fail_closed_and_json_has_no_nonfinite_numbers(self):
        cases = [([], ["<blk>", "a"]), ([[0]], ["a"]), ([[0, 0]], ["<blk>", "a"]),
                 ([[float("nan"), 0]], ["<blk>", "a"]), ([[float("inf"), 0]], ["<blk>", "a"]),
                 ([[float("-inf"), float("-inf")]], ["<blk>", "a"]),
                 ([[0, -1]], ["<blk>", "<blk>"]), ([["secret invalid raw value"]], ["<blk>"])]
        for values, vocab in cases:
            with self.subTest(values=values):
                result = pronunciation.analyze(["a"], [], {"phones": heard("a")},
                             posteriors={"phones": {"logprobs": values, "vocab": vocab}})
                fit = result["roles"]["phones"]["posterior"]
                self.assertEqual(fit["inputStatus"], "unavailable")
                self.assertNotIn("secret", fit["reason"])
                json.dumps(result, allow_nan=False)

    def test_exact_zero_probabilities_are_legal(self):
        values = np.array([[-np.inf, 0.], [0., -np.inf]])
        result = pronunciation.analyze(["a"], [], {"phones": heard("a")},
                     posteriors={"phones": {"logprobs": values, "vocab": ["<blk>", "a"], "frameSeconds": .02}})
        self.assertEqual(result["roles"]["phones"]["posterior"]["paths"][0]["logLikelihood"], 0)
        self.assertEqual(len(result["roles"]["phones"]["posterior"]["expectedWindows"]), 1)
        json.dumps(result, allow_nan=False)

    def test_missing_timebase_keeps_fit_but_abstains_on_windows(self):
        data = posterior([1], ["<blk>", "a"])
        del data["frameSeconds"]
        result = pronunciation.analyze(["a"], [], {"phones": heard("a")}, posteriors={"phones": data})
        fit = result["roles"]["phones"]["posterior"]
        self.assertIsNotNone(fit["paths"][0]["logLikelihood"])
        self.assertEqual(fit["expectedWindowsReason"], "missing-or-invalid-frame-seconds")

    def test_optional_and_reviewed_path_budgets_are_reported(self):
        words = [{"phones": ["a", "b", "c", "d", "e"], "optional": [0, 1, 2, 3]}]
        result = pronunciation.analyze(words[0]["phones"], words, {}, limits={"paths": 3})
        self.assertEqual(len(result["pronunciations"]), 3)
        self.assertIn("path-budget-exceeded", result["pathCoverage"]["reasons"])
        result = pronunciation.analyze(["a"], [], {}, alternatives=[
            {"phones": [p], "reason": "reviewed"} for p in ("b", "c", "d")], limits={"paths": 2})
        self.assertEqual(len(result["pronunciations"]), 2)
        self.assertEqual(result["pathCoverage"]["inputStatus"], "partial")

    def test_tokenization_budget_never_claims_exhaustive_support(self):
        result = pronunciation.analyze(["a", "a"], [], {"phones": heard("a", "a")},
             posteriors={"phones": posterior([1, 1], ["<blk>", "a", "aa"])}, limits={"tokenizations": 1})
        fit = result["roles"]["phones"]["posterior"]
        self.assertEqual(fit["paths"][0]["reason"], "tokenization-budget-exceeded")
        self.assertIsNone(fit["bestConstrainedPath"])
        self.assertEqual(fit["expectedWindows"], [])

    def test_frame_state_and_operation_budgets_are_explicit(self):
        data = posterior([1], ["<blk>", "a"])
        result = pronunciation.analyze(["a"], [], {"phones": heard("a")},
                       posteriors={"phones": data}, limits={"frames": 1})
        self.assertEqual(result["roles"]["phones"]["posterior"]["reason"], "posterior-budget-exceeded")
        result = pronunciation.analyze(["a"] * 8, [], {"phones": heard("a")},
                       posteriors={"phones": data}, limits={"cells": 20})
        self.assertEqual(result["roles"]["phones"]["posterior"]["paths"][0]["reason"], "ctc-state-budget-exceeded")
        result = pronunciation.analyze(["a", "b"], [], {"phones": heard("c", "d")}, limits={"operations": 1})
        self.assertEqual(len(result["roles"]["phones"]["localizedCandidates"]), 1)
        self.assertEqual(result["roles"]["phones"]["reason"], "operation-budget-exceeded")

    def test_malformed_optionality_is_not_applied(self):
        for words in ([{"phones": ["a"], "optional": [1]}], [{"phones": ["b"], "optional": [0]}], [None]):
            with self.subTest(words=words):
                result = pronunciation.analyze(["a"], words, {})
                self.assertEqual(len(result["pronunciations"]), 1)
                self.assertEqual(result["pathCoverage"]["inputStatus"], "partial")

    def test_alternative_ids_cannot_shadow_canonical_or_each_other(self):
        result = pronunciation.analyze(["a"], [], {}, alternatives=[
            {"id": "canonical", "phones": ["b"], "reason": "reviewed"},
            {"id": "other", "phones": ["c"], "reason": "reviewed"},
            {"id": "other", "phones": ["d"], "reason": "reviewed"}])
        self.assertEqual([p["id"] for p in result["pronunciations"]], ["canonical", "other"])
        self.assertIn("invalid-or-duplicate-alternative-id", result["pathCoverage"]["reasons"])

    def test_existing_optional_paths_never_hide_raw_narrow_diacritics(self):
        result = pronunciation.analyze(["aː", "pʰ"], [], {
            "phones": heard("a", "p"), "phonesB": heard("aː", "pʰ")})
        self.assertEqual([c["type"] for c in result["roles"]["phones"]["localizedCandidates"]],
                         ["substitution", "substitution"])
        self.assertEqual(result["roles"]["phonesB"]["localizedCandidates"], [])

    def test_malformed_times_are_not_used_for_localization(self):
        for start, end in (("bad", .1), (float("nan"), .1), (.2, .1), (-1, .1)):
            result = pronunciation.analyze(["a"], [], {
                 "phones": {"phones": [{"phone": "b", "start": start, "end": end}]}})
            self.assertEqual(result["roles"]["phones"]["inputStatus"], "unavailable")
            self.assertEqual(result["roles"]["phones"]["localizedCandidates"], [])

    def test_missing_expected_input_and_invalid_limits(self):
        for expected in (None, [], [None], "a"):
            self.assertEqual(pronunciation.analyze(expected, [], {})["inputStatus"], "unavailable")
        for limits in ({"paths": 17}, {"frames": 0}, {"operations": True}, {"unknown": 1}):
            with self.assertRaises(ValueError):
                pronunciation.analyze(["a"], [], {}, limits=limits)


if __name__ == "__main__":
    unittest.main()
