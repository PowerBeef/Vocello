"""Deterministic word-join mapping, provenance and abstention coverage."""
from __future__ import annotations

import copy
import json
import unittest

from qc import boundary, pronunciation


def heard(items):
    return {"phones": [{"phone": p, "start": i * .1, "end": (i + 1) * .1}
                       for i, p in enumerate(items)]}


def evidence(expected, recognized, second=None):
    outputs = {"phones": heard(recognized)}
    if second is not None:
        outputs["phonesB"] = heard(second)
    return pronunciation.analyze(expected, [], outputs)


def reviewed(path, join=3):
    return [{"id": "comparison-a", "boundaryIndex": join, "phones": path,
             "reason": "Independent reviewed pronunciation comparison, not an acceptance label",
             "provenance": {"kind": "human-reviewed", "sourceSHA256": "a" * 64,
                            "annotationId": "annotation-a", "reviewerId": "reviewer-a",
                            "targetVariety": "fr-comparison"}}]


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.expected = ["ɔ", "ʁ", "m", "a", "b", "a", "t", "y"]
        self.words = [{"phones": self.expected[:3]}, {"phones": self.expected[3:]}]
        self.extra = self.expected[:3] + ["ə"] + self.expected[3:]

    def analyze(self, data=None, **kwargs):
        return boundary.analyze(self.expected, self.words, data if data is not None else
                                evidence(self.expected, self.extra), duration_seconds=2, **kwargs)

    def test_exact_join_single_witness_survives_second_recognizer_disagreement(self):
        result = self.analyze(evidence(self.expected, self.extra, self.expected))
        self.assertEqual(result["inputStatus"], "complete")
        self.assertEqual(len(result["candidates"]), 1)
        candidate = result["candidates"][0]
        self.assertEqual(candidate["expectedGapIndex"], 3)
        self.assertEqual(candidate["boundaries"][0]["boundaryIndex"], 3)
        self.assertEqual(candidate["phone"], "ə")
        self.assertAlmostEqual(candidate["start"], .3)
        self.assertEqual(candidate["source"], "phones")
        self.assertEqual(candidate["evidenceStatus"], "single-witness")
        self.assertEqual(candidate["class"], "boundary-pronunciation")
        self.assertEqual(candidate["status"], "candidate")
        self.assertEqual(result["decision"], "not-assessed")
        self.assertEqual(result["nativeAccentDecision"], "not-assessed")
        self.assertTrue(result["reportOnly"])
        json.dumps(result, allow_nan=False)

    def test_correct_join_internal_insertion_and_consonant_insertion_do_not_nominate(self):
        for recognized in (self.expected, self.expected[:1] + ["ə"] + self.expected[1:],
                           self.expected[:3] + ["z"] + self.expected[3:]):
            with self.subTest(recognized=recognized):
                self.assertEqual(self.analyze(evidence(self.expected, recognized))["candidates"], [])

    def test_near_join_nonoptional_phone_is_not_generic_internal_error_alias(self):
        recognized = self.expected[:2] + ["ə"] + self.expected[2:]
        self.assertEqual(self.analyze(evidence(self.expected, recognized))["candidates"], [])

    def test_optional_suffix_widens_location_without_licensing_liaison(self):
        expected = ["ɔ", "ʁ", "m", "z", "a"]
        words = [{"phones": expected[:4], "optional": [3]}, {"phones": ["a"]}]
        result = boundary.analyze(expected, words, evidence(expected, expected[:3] + ["ə"] + expected[3:]))
        candidate = result["candidates"][0]
        self.assertEqual(candidate["expectedGapIndex"], 3)
        self.assertTrue(candidate["boundaries"][0]["optionalSuffixHeuristic"])
        self.assertEqual(result["settings"]["linguisticPermission"], "not-assessed")

    def test_multi_base_raw_token_indices_map_to_flattened_narrow_join(self):
        expected, words = ["tʃ", "a", "b"], [{"phones": ["tʃ"]}, {"phones": ["a", "b"]}]
        result = boundary.analyze(expected, words, evidence(expected, ["t", "ʃ", "ə", "a", "b"]))
        self.assertEqual(result["candidates"][0]["expectedGapIndex"], 2)
        self.assertEqual(result["candidates"][0]["boundaries"][0]["boundaryIndex"], 2)

    def test_nasal_vowel_is_retained_narrowly(self):
        result = self.analyze(evidence(self.expected, self.expected[:3] + ["ɑ̃ː"] + self.expected[3:]))
        self.assertEqual(result["candidates"][0]["phone"], "ɑ̃ː")

    def test_reviewed_alternative_match_preserves_candidate_and_provenance(self):
        result = self.analyze(reviewed_boundaries=reviewed(self.extra))
        self.assertEqual(result["candidates"][0]["reviewedAlternativeMatches"], ["comparison-a"])
        self.assertEqual(result["reviewedHypotheses"][0]["provenance"]["sourceSHA256"], "a" * 64)
        self.assertEqual(result["decision"], "not-assessed")
        self.assertEqual(result["qualification"], "uncalibrated")
        result = self.analyze(reviewed_boundaries=reviewed(self.expected))
        self.assertEqual(result["candidates"][0]["reviewedAlternativeMatches"], [])

    def test_reviewed_omission_nominates_canonical_optional_vowel_without_permission(self):
        expected = ["l", "e", "z", "ɔ", "ʁ", "m", "ə", "z", "a", "b", "a", "t", "y"]
        words = [{"phones": expected[:3], "optional": [2]},
                 {"phones": expected[3:8], "optional": [3, 4]}, {"phones": expected[8:]}]
        data = evidence(expected, expected, expected)
        unreviewed = boundary.analyze(expected, words, data)
        self.assertEqual(unreviewed["candidates"], [])
        self.assertEqual(unreviewed["coverage"]["reviewedComparisonStatus"], "unavailable")
        hypotheses = reviewed(expected[:6] + expected[7:], join=8)
        result = boundary.analyze(expected, words, data, reviewed_boundaries=hypotheses)
        self.assertEqual(len(result["candidates"]), 2)
        for candidate in result["candidates"]:
            self.assertEqual(candidate["candidateType"], "reviewed-boundary-vowel-disagreement")
            self.assertEqual(candidate["expectedIndex"], 6)
            self.assertEqual(candidate["boundaryIndices"], [8])
            self.assertEqual(candidate["reviewedHypotheses"], ["comparison-a"])
            self.assertIn("realized-vowel-is-not-wrong-liaison-proof", candidate["uncertainty"])
        self.assertEqual(result["decision"], "not-assessed")
        self.assertEqual(result["settings"]["linguisticPermission"], "not-assessed")

    def test_reviewed_omission_matching_heard_path_does_not_nominate_vowel(self):
        expected = ["l", "e", "z", "ɔ", "ʁ", "m", "ə", "z", "a", "b", "a", "t", "y"]
        alternative = expected[:6] + expected[7:]
        words = [{"phones": expected[:3]}, {"phones": expected[3:8]}, {"phones": expected[8:]}]
        result = boundary.analyze(expected, words, evidence(expected, alternative),
                                  reviewed_boundaries=reviewed(alternative, join=8))
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["coverage"]["roles"]["phones"]["reviewedAlternativeMatches"], ["comparison-a"])

    def test_reviewed_unrelated_consonant_omission_cannot_become_vowel_candidate(self):
        result = self.analyze(evidence(self.expected, self.expected),
                              reviewed_boundaries=reviewed(self.expected[:2] + self.expected[3:]))
        self.assertEqual(result["candidates"], [])

    def test_missing_reviewed_vowel_timing_abstains_instead_of_using_annotation_span(self):
        data = evidence(self.expected, self.expected)
        # First /a/ is immediately after the actual word join.
        operation = data["roles"]["phones"]["narrowAlignment"][3]
        operation.update(start=None, end=None)
        result = self.analyze(data, reviewed_boundaries=reviewed(self.expected[:3] + self.expected[4:]))
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["coverage"]["roles"]["phones"]["untimedReviewedVowelDisagreements"], 1)
        self.assertEqual(result["inputStatus"], "partial")

    def test_invalid_reviewed_hypothesis_abstains_without_inventing_permission(self):
        mutations = [lambda h: h.pop("provenance"), lambda h: h.update(boundaryIndex=1),
                     lambda h: h["provenance"].update(sourceSHA256="missing"),
                     lambda h: h["provenance"].update(kind="model-generated"),
                     lambda h: h["provenance"].pop("targetVariety"),
                     lambda h: h.update(phones=["z"] + self.extra[1:]),
                     lambda h: h.update(reason=" "), lambda h: h.update(id="")]
        for mutate in mutations:
            hypothesis = reviewed(self.extra)
            mutate(hypothesis[0])
            with self.subTest(hypothesis=hypothesis):
                result = self.analyze(reviewed_boundaries=hypothesis)
                self.assertEqual(result["inputStatus"], "unavailable")
                self.assertEqual(result["candidates"], [])
        self.assertEqual(self.analyze(reviewed_boundaries=reviewed(self.extra) * 17)["inputStatus"], "unavailable")
        self.assertEqual(self.analyze(reviewed_boundaries=reviewed(self.extra) * 2)["inputStatus"], "unavailable")

    def test_missing_or_invalid_timing_never_invents_event_span(self):
        for start, end in ((None, None), (.4, .3), (float("nan"), .4), (.3, float("inf")),
                           (True, .4), (-.1, .4), (.3, 2.1)):
            data = evidence(self.expected, self.extra)
            operation = next(op for op in data["roles"]["phones"]["narrowAlignment"] if op["op"] == "ins")
            operation.update(start=start, end=end)
            with self.subTest(start=start, end=end):
                result = self.analyze(data)
                self.assertEqual(result["candidates"], [])
                self.assertNotEqual(result["inputStatus"], "complete")
                json.dumps(result, allow_nan=False)

    def test_missing_or_mismatched_words_and_streamed_inputs_abstain(self):
        cases = [None, [], [{"phones": self.expected}], [{"phones": ["a"]}, {"phones": ["b"]}],
                 [{"phones": self.expected[:3], "optional": [9]}, self.words[1]],
                 [{"phones": self.expected[:3], "optional": (x for x in ())}, self.words[1]],
                 (word for word in self.words)]
        for words in cases:
            with self.subTest(words=words):
                result = boundary.analyze(self.expected, words, evidence(self.expected, self.extra))
                self.assertEqual(result["inputStatus"], "unavailable")
                self.assertEqual(result["candidates"], [])
        self.assertEqual(boundary.analyze((p for p in self.expected), self.words, {})["inputStatus"], "unavailable")
        oversized = ["a"] * 513
        self.assertEqual(boundary.analyze(oversized, [], {})["inputStatus"], "unavailable")
        self.assertEqual(boundary.analyze(["a" * 64] * 9, [], {})["inputStatus"], "unavailable")

    def test_mismatched_truncated_or_corrupted_alignments_abstain(self):
        cases = []
        data = evidence(self.expected, self.extra)
        for field, value in (("expectedIndex", 99), ("recognizedIndex", 99), ("expectedIndex", True),
                             ("expected", "z"), ("op", "other")):
            mutated = copy.deepcopy(data)
            mutated["roles"]["phones"]["narrowAlignment"][0][field] = value
            cases.append(mutated)
        mutated = copy.deepcopy(data)
        mutated["roles"]["phones"]["narrowAlignment"].pop()
        cases.append(mutated)
        mutated = copy.deepcopy(data)
        mutated["roles"]["phones"]["narrowAlignment"] *= 30
        cases.append(mutated)
        mutated = copy.deepcopy(data)
        mutated["expectedTokens"] = ["a"]
        cases.append(mutated)
        for mutated in cases:
            result = self.analyze(mutated)
            self.assertEqual(result["candidates"], [])
            self.assertEqual(result["inputStatus"], "unavailable")

    def test_deletions_and_substitutions_preserve_expected_cursor_mapping(self):
        expected = ["ɔ", "ʁ", "m", "z", "a", "b"]
        words = [{"phones": expected[:4]}, {"phones": expected[4:]}]
        # Removing the first phone and changing /ʁ/ must not shift the actual join.
        data = evidence(expected, ["r", "m", "z", "ə", "a", "b"])
        result = boundary.analyze(expected, words, data)
        self.assertEqual(result["candidates"][0]["expectedGapIndex"], 4)

    def test_global_candidate_budget_is_bounded_and_partial_not_silently_complete(self):
        expected, words = ["a", "b"], [{"phones": ["a"]}, {"phones": ["b"]}]
        recognized = ["a"] + ["ə"] * 250 + ["b"]
        result = boundary.analyze(expected, words, evidence(expected, recognized, recognized), duration_seconds=30)
        self.assertEqual(len(result["candidates"]), 256)
        self.assertEqual(result["inputStatus"], "partial")
        self.assertEqual(result["coverage"]["roles"]["phonesB"]["reason"], "candidate-budget-exceeded")
        json.dumps(result, allow_nan=False)

    def test_reordered_recognizer_times_abstain_before_nominating_insertions(self):
        data = evidence(self.expected, self.extra)
        data["roles"]["phones"]["narrowAlignment"][-1].update(start=.1, end=.2)
        result = self.analyze(data)
        self.assertEqual(result["inputStatus"], "unavailable")
        self.assertEqual(result["candidates"], [])

    def test_missing_role_remains_partial_and_unknown_duration_is_explicit(self):
        result = boundary.analyze(self.expected, self.words, evidence(self.expected, self.extra))
        self.assertEqual(result["inputStatus"], "partial")
        self.assertFalse(result["coverage"]["durationVerified"])
        self.assertEqual(result["coverage"]["roles"]["phonesB"]["inputStatus"], "unavailable")
        for duration in (0, -1, float("inf"), True, 121):
            result = boundary.analyze(self.expected, self.words, {}, duration_seconds=duration)
            self.assertEqual(result["inputStatus"], "unavailable")


if __name__ == "__main__":
    unittest.main()
