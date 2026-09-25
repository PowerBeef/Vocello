#!/usr/bin/env python3
"""Pin the shared language metrics to the Swift verifier's contract and the family rule."""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import language_metrics as metrics  # noqa: E402


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def recognition(*, family: str = "whisper", audio: str = "a" * 64, script: str,
                transcript: str | None = None, language: str = "english",
                detected: str | None = None, duration: float = 2.0, **overrides) -> dict:
    entry = {
        "modelFamily": family, "audioSHA256": audio, "inputTextSHA256": sha(script),
        "status": "complete", "outputLanguage": language, "detectedLanguage": detected or language,
        "fullFileProcessed": True, "processedDurationSeconds": duration,
        "transcript": script if transcript is None else transcript,
        "provenance": {key: sha(f"{family}-{key}") for key in ("runtimeSHA256", "modelIdentitySHA256", "configSHA256")},
    }
    entry.update(overrides)
    return entry


class TokenizerAndEditDistanceTests(unittest.TestCase):
    # Fixtures mirror GenerationOutputVerifier: POSIX lowercasing, diacritic and
    # width folding, alphanumeric boundaries, and the stable tie policy.
    def test_tokens_fold_diacritics_width_and_case_like_swift(self) -> None:
        self.assertEqual(metrics.normalized_word_tokens("Élan, café — naïve!"), ["elan", "cafe", "naive"])
        self.assertEqual(metrics.normalized_word_tokens("ＡＢＣ　１２３"), ["abc", "123"])
        self.assertEqual(metrics.normalized_word_tokens("  "), [])

    def test_cjk_character_metrics_keep_dakuten_but_fold_width(self) -> None:
        self.assertEqual(metrics.normalized_word_tokens("かき", preserve_diacritics=True), ["かき"])
        self.assertEqual(metrics.normalized_word_tokens("がき", preserve_diacritics=True), ["がき"])
        _word, character = metrics.recomputed_accuracy("かきくけこ", "がきくけこ", "japanese")
        self.assertEqual(character["substitutions"], 1)
        self.assertEqual(character["errorRate"], 0.2)
        # Without diacritic preservation the two would collapse to the same token.
        self.assertEqual(metrics.normalized_word_tokens("がき"), metrics.normalized_word_tokens("かき"))

    def test_edit_metrics_keep_operation_counts_and_stable_ties(self) -> None:
        result = metrics.edit_metrics(list("kitten"), list("sitting"))
        self.assertEqual(
            (result["substitutions"], result["insertions"], result["deletions"]), (2, 1, 0)
        )
        self.assertEqual(result["referenceCount"], 6)
        self.assertEqual(result["hypothesisCount"], 7)
        self.assertAlmostEqual(result["errorRate"], 0.5)
        self.assertEqual(metrics.edit_metrics([], [])["errorRate"], 0.0)
        self.assertEqual(metrics.edit_metrics([], ["x"])["errorRate"], 1.0)
        self.assertEqual(metrics.edit_metrics(["x"], [])["deletions"], 1)

    def test_word_and_character_rates_for_a_french_script(self) -> None:
        word, character = metrics.recomputed_accuracy(
            "un deux trois quatre cinq six sept huit", "un deux trois quatre cinq six sept neuf", "french",
        )
        self.assertEqual(word["substitutions"], 1)
        self.assertEqual(word["errorRate"], 0.125)
        self.assertGreater(character["errorRate"], 0.0)
        self.assertEqual(metrics.primary_accuracy_metric("french"), "wordErrorRate")
        self.assertEqual(metrics.primary_accuracy_metric("chinese"), "characterErrorRate")

    def test_locale_matching_is_prefix_based_and_fails_closed(self) -> None:
        self.assertTrue(metrics.locale_matches_expected_language("fr-CA", "french"))
        self.assertTrue(metrics.locale_matches_expected_language("fr_FR", "french"))
        self.assertTrue(metrics.locale_matches_expected_language("ZH-Hans-CN", "chinese"))
        self.assertFalse(metrics.locale_matches_expected_language("en-US", "french"))
        self.assertFalse(metrics.locale_matches_expected_language("", "french"))
        self.assertFalse(metrics.locale_matches_expected_language("ko-KR", "korean"))
        self.assertEqual(set(metrics.LANGUAGE_LOCALE_CODES), {"english", "french", "german", "spanish", "chinese", "japanese"})

    def test_thresholds_are_the_product_gate(self) -> None:
        self.assertEqual(metrics.MAX_ACCURACY_ERROR_RATE, 0.15)
        self.assertEqual(metrics.MIN_LANGUAGE_MATCH_SCORE, 0.5)
        self.assertEqual(metrics.ACCURACY_METRIC_VERSION, "segmentation-aware-edit-rate-v2")
        self.assertEqual(metrics.LEGACY_ACCURACY_METRIC_VERSION, "normalized-edit-rate-v1")


class SegmentationAwareWERTests(unittest.TestCase):
    """WER v2 (audit #43): a word-boundary merge, split or moved boundary of up to
    four words per side is not an error. Parity fixtures mirror
    `testSegmentationAwareWordMetricsCreditOnlyBoundaryEdits` in Swift."""

    CASES = (
        ("Er kommt vor Mittag an und bleibt bis zum Abend",
         "Er kommt Vormittag an und bleibt biszum Abend", 0, 4, 0.0),
        ("Das Donaudampfschiff fährt", "Das Donau dampf schiff fährt", 0, 3, 0.0),
        ("ab c", "a bc", 0, 2, 0.0),
        ("the quiet garden", "the quite garden", 1, 0, 1 / 3),
        ("vor Mittag kommt er", "Vormittag kam er", 1, 2, 0.25),
        ("a b c d e", "abcde", 5, 0, 1.0),
        ("a b c d", "abcd", 0, 4, 0.0),
        ("", "x", 1, 0, 1.0),
        ("x", "", 1, 0, 1.0),
    )

    def test_parity_fixtures_with_the_swift_verifier(self) -> None:
        for reference, hypothesis, distance, credited, rate in self.CASES:
            with self.subTest(reference=reference, hypothesis=hypothesis):
                result = metrics.segmentation_aware_metrics(
                    metrics.normalized_word_tokens(reference), metrics.normalized_word_tokens(hypothesis),
                )
                self.assertEqual(result["segmentationAwareEditDistance"], distance)
                self.assertEqual(result["wordBoundaryOnlyEdits"], credited)
                self.assertAlmostEqual(result["segmentationAwareErrorRate"], rate)
        self.assertEqual(metrics.WORD_BOUNDARY_SPAN_LIMIT, 4)

    def test_the_audits_german_take_no_longer_spends_the_budget(self) -> None:
        # CER zero: every word error is a two-word merge. v1 charges four edits
        # (0.4 here); v2 charges none, and the v1 rate stays published.
        entry = recognition(script=self.CASES[0][0], transcript=self.CASES[0][1], language="german")
        v2 = metrics.score_recognition(entry, script=self.CASES[0][0], language="german")
        self.assertEqual(v2["accuracyMetricVersion"], "segmentation-aware-edit-rate-v2")
        self.assertAlmostEqual(v2["wordErrorRate"], 0.4)
        self.assertEqual(v2["segmentationAwareWordErrorRate"], 0.0)
        self.assertEqual(v2["wordBoundaryOnlyEdits"], 4)
        self.assertEqual(v2["errorRate"], 0.0)
        self.assertTrue(v2["accuracyPass"])
        v1 = metrics.score_recognition(entry, script=self.CASES[0][0], language="german",
                                       accuracy_metric_version="normalized-edit-rate-v1")
        self.assertAlmostEqual(v1["errorRate"], 0.4)
        self.assertFalse(v1["accuracyPass"])

    def test_characters_and_unknown_versions(self) -> None:
        word, character = metrics.recomputed_accuracy("今天天气很好", "今天天气很好", "chinese")
        for version in metrics.ACCURACY_METRIC_VERSIONS:
            self.assertEqual(metrics.primary_accuracy_score(word, character, "chinese", version=version), 0.0)
        with self.assertRaises(ValueError):
            metrics.primary_accuracy_score(word, character, "chinese", version="edit-rate-v9")

    def test_the_segmentation_aware_rate_never_exceeds_the_plain_rate(self) -> None:
        import random
        generator = random.Random(20260925)
        vocabulary = ["a", "b", "ab", "ba", "c", "abc", "bc"]
        for _ in range(300):
            reference = [generator.choice(vocabulary) for _ in range(generator.randint(0, 7))]
            hypothesis = [generator.choice(vocabulary) for _ in range(generator.randint(0, 7))]
            plain = metrics.edit_metrics(reference, hypothesis)
            aware = metrics.segmentation_aware_metrics(reference, hypothesis)
            plain_distance = plain["substitutions"] + plain["insertions"] + plain["deletions"]
            self.assertLessEqual(aware["segmentationAwareEditDistance"], plain_distance)
            self.assertEqual(aware["wordBoundaryOnlyEdits"], plain_distance - aware["segmentationAwareEditDistance"])
            if "".join(reference) == "".join(hypothesis) and max(len(reference), len(hypothesis)) <= 4:
                self.assertEqual(aware["segmentationAwareEditDistance"], 0)


class EdgeCoverageTests(unittest.TestCase):
    def test_allowance_is_fifteen_percent_clamped(self) -> None:
        self.assertEqual(metrics.edge_allowance_seconds(2.0), 1.0)
        self.assertEqual(metrics.edge_allowance_seconds(10.0), 1.5)
        self.assertEqual(metrics.edge_allowance_seconds(60.0), 2.5)

    def test_edges_covered_requires_both_ends(self) -> None:
        self.assertTrue(metrics.edges_covered(0.2, 9.0, 10.0))
        self.assertFalse(metrics.edges_covered(2.0, 9.0, 10.0))
        self.assertFalse(metrics.edges_covered(0.0, 7.0, 10.0))
        self.assertFalse(metrics.edges_covered(0.0, 0.0, 10.0))
        self.assertFalse(metrics.edges_covered(0.0, 5.0, float("nan")))


class RecognitionQualificationTests(unittest.TestCase):
    SCRIPT = "The quiet garden is open today."

    def qualify(self, entry: dict, **kwargs) -> list[str]:
        defaults = dict(audio_sha256="a" * 64, script=self.SCRIPT, script_sha256=sha(self.SCRIPT),
                        language="english", duration_seconds=2.0)
        defaults.update(kwargs)
        return metrics.recognition_issues(entry, **defaults)

    def test_bound_complete_recognition_is_qualified(self) -> None:
        self.assertEqual(self.qualify(recognition(script=self.SCRIPT)), [])

    def test_every_binding_is_checked(self) -> None:
        cases = {
            "unknown-family": recognition(script=self.SCRIPT, family="oracle"),
            "audio-digest-mismatch": recognition(script=self.SCRIPT, audio="b" * 64),
            "input-text-digest-mismatch": recognition(script=self.SCRIPT, inputTextSHA256="c" * 64),
            "incomplete": recognition(script=self.SCRIPT, status="partial"),
            "output-language-mismatch": recognition(script=self.SCRIPT, outputLanguage="french"),
            "partial-file": recognition(script=self.SCRIPT, fullFileProcessed=False),
            "processed-duration-mismatch": recognition(script=self.SCRIPT, duration=1.9),
            "provenance-incomplete": recognition(script=self.SCRIPT, provenance={"runtimeSHA256": "a" * 64}),
            "transcript-invalid": recognition(script=self.SCRIPT, transcript="   "),
        }
        for issue, entry in cases.items():
            with self.subTest(issue=issue):
                self.assertIn(issue, self.qualify(entry))
        self.assertEqual(self.qualify("not a dict"), ["not-an-object"])
        self.assertIn("script-digest-mismatch", self.qualify(recognition(script=self.SCRIPT), script="other"))
        self.assertIn("family-cannot-recognize-language", self.qualify(
            recognition(script=self.SCRIPT, family="sensevoice", language="french"), language="french"))

    def test_scores_are_recomputed_from_the_transcript_never_trusted(self) -> None:
        entry = recognition(script=self.SCRIPT, transcript="Wrong words completely replace the content.")
        entry["errorRate"] = 0.0
        verdict = metrics.score_recognition(entry, script=self.SCRIPT, language="english")
        self.assertGreater(verdict["errorRate"], metrics.MAX_ACCURACY_ERROR_RATE)
        self.assertFalse(verdict["passed"])
        self.assertTrue(verdict["languagePass"])
        exact = metrics.score_recognition(recognition(script=self.SCRIPT), script=self.SCRIPT, language="english")
        self.assertEqual(exact["errorRate"], 0.0)
        self.assertTrue(exact["passed"])
        wrong_language = metrics.score_recognition(
            recognition(script=self.SCRIPT, detected="french"), script=self.SCRIPT, language="english")
        self.assertFalse(wrong_language["languagePass"])
        self.assertFalse(wrong_language["passed"])
        self.assertEqual(metrics.score_recognition(
            recognition(script="今日は良い天気です", language="japanese"),
            script="今日は良い天気です", language="japanese")["metric"], "CER")


class DeletionRunTests(unittest.TestCase):
    """Audit #84: a skipped phrase under the edit-rate gate is reported, warn-only.

    The first test mirrors `WordErrorRateTests.testLongestDeletionRunFollowsTheAlignment`.
    """

    def run_of(self, reference: str, hypothesis: str) -> dict:
        return metrics.edit_metrics(
            metrics.normalized_word_tokens(reference), metrics.normalized_word_tokens(hypothesis))

    def test_parity_fixtures_with_the_swift_verifier(self) -> None:
        skipped = self.run_of("The quiet garden is open today", "The is open today")
        self.assertEqual((skipped["deletions"], skipped["longestDeletionRun"]), (2, 2))
        scattered = self.run_of("a b c d e", "a c e")
        self.assertEqual((scattered["deletions"], scattered["longestDeletionRun"]), (2, 1))
        merged = self.run_of("vor Mittag kommt er", "Vormittag kommt er")
        self.assertEqual((merged["substitutions"], merged["deletions"], merged["longestDeletionRun"]), (1, 1, 1))
        self.assertEqual(metrics.edit_metrics(list("kitten"), list("sitting"))["longestDeletionRun"], 0)
        self.assertEqual(self.run_of("a b c", "")["longestDeletionRun"], 3)

    def test_a_skip_that_passes_the_gate_still_warns(self) -> None:
        script = ("Each morning the quiet garden opens its gates and the old gardener "
                  "waters every rose by noon")
        transcript = script.replace("the quiet ", "")
        entry = recognition(script=script, transcript=transcript)
        verdict = metrics.score_recognition(entry, script=script, language="english")
        # 2 of 17 words: the gate passes, as the audit showed.
        self.assertAlmostEqual(verdict["errorRate"], 2 / 17)
        self.assertTrue(verdict["passed"])
        self.assertEqual(verdict["longestDeletionRun"], 2)
        self.assertTrue(verdict["deletionRunWarning"])
        clean = metrics.score_recognition(recognition(script=script), script=script, language="english")
        self.assertEqual((clean["longestDeletionRun"], clean["deletionRunWarning"]), (0, False))

    def test_character_languages_count_characters(self) -> None:
        script = "今日は良い天気です"
        verdict = metrics.score_recognition(
            recognition(script=script, transcript="今日は天気です", language="japanese"),
            script=script, language="japanese")
        self.assertEqual(verdict["metric"], "CER")
        self.assertEqual(verdict["longestDeletionRun"], 2)
        self.assertEqual(metrics.primary_deletion_run(script, "今日は天気です", "japanese"), 2)


class NegativeControlScoringTests(unittest.TestCase):
    """Audit #42: what each channel of the negative control can and cannot show."""

    FRENCH = ("un deux trois quatre cinq six sept huit neuf dix onze douze treize "
              "quatorze quinze seize")

    def test_english_locked_whisper_fails_the_control_on_accuracy_alone(self) -> None:
        # English hint over a French script, as the matrix's control cell pins it.
        # Whisper hears English (p = 0.893 in the audit's take), so its language
        # check passes; only the edit rate against the French script rejects it.
        # Nine of sixteen words differ ("six" is spelled alike in both languages).
        transcript = ("one two three four five six seven eight nine ten onze douze treize "
                      "quatorze quinze seize")
        entry = recognition(script=self.FRENCH, transcript=transcript, language="english",
                            detected="english", languageMatchScore=0.893)
        verdict = metrics.score_recognition(entry, script=self.FRENCH, language="english")
        self.assertAlmostEqual(verdict["errorRate"], 0.5625)
        self.assertTrue(verdict["languagePass"])
        self.assertFalse(verdict["accuracyPass"])
        self.assertFalse(verdict["passed"])

    def test_a_french_detection_fails_the_control_on_both_channels(self) -> None:
        entry = recognition(script=self.FRENCH, language="english", detected="french")
        verdict = metrics.score_recognition(entry, script=self.FRENCH, language="english")
        self.assertFalse(verdict["languagePass"])
        # The transcript is the French script itself: the edit rate is zero, so
        # the language channel alone carries this failure.
        self.assertTrue(verdict["accuracyPass"])
        self.assertFalse(verdict["passed"])


class ConsensusTests(unittest.TestCase):
    def test_one_family_is_one_witness(self) -> None:
        result = metrics.consensus({"whisper": [True]})
        self.assertEqual(result["status"], "inconclusive")
        self.assertEqual(result["reasons"], ["independent-full-file-asr-missing"])

    def test_two_agreeing_families_decide(self) -> None:
        self.assertEqual(metrics.consensus({"whisper": [True], "apple-speech": [True]})["status"], "pass")
        failure = metrics.consensus({"whisper": [False], "apple-speech": [False]})
        self.assertEqual(failure["status"], "fail")
        self.assertIn("independent-asr-content-failure", failure["reasons"])

    def test_disagreement_never_lets_either_family_win(self) -> None:
        split = metrics.consensus({"whisper": [True], "apple-speech": [False]})
        self.assertEqual(split["status"], "inconclusive")
        self.assertIn("independent-asr-disagreement", split["reasons"])
        flaky = metrics.consensus({"whisper": [True, False], "apple-speech": [True]})
        self.assertEqual(flaky["status"], "inconclusive")
        self.assertIn("asr-repeatability-disagreement", flaky["reasons"])
        self.assertEqual(metrics.consensus({"whisper": [], "apple-speech": [True]})["status"], "inconclusive")


class ChannelConsensusTests(unittest.TestCase):
    """Audit #42: each verdict channel is voted separately, and the negative
    control is an accuracy control."""

    PASS = {"language": True, "accuracy": True}

    def test_two_families_passing_both_channels_meet_a_pass(self) -> None:
        result = metrics.channel_consensus(
            {"apple-speech": self.PASS, "whisper": self.PASS}, expect_failure=False)
        self.assertEqual(result["statuses"], {"language": "pass", "accuracy": "pass"})
        self.assertEqual(result["outcome"], "met")
        self.assertEqual(result["algorithm"], metrics.CHANNEL_CONSENSUS_ALGORITHM)

    def test_failures_for_different_reasons_are_not_agreement(self) -> None:
        # Combined votes (both families "failed") would read as a consensus
        # failure; per channel each channel is split, so nothing is agreed.
        result = metrics.channel_consensus({
            "apple-speech": {"language": False, "accuracy": True},
            "whisper": {"language": True, "accuracy": False},
        }, expect_failure=True)
        self.assertEqual(result["statuses"], {"language": "inconclusive", "accuracy": "inconclusive"})
        self.assertEqual(result["outcome"], "inconclusive")

    def test_the_accuracy_control_constrains_accuracy_only(self) -> None:
        # The audit's control take: whisper hears English (language passes) and
        # both families fail on accuracy; Apple's locked language check fails.
        result = metrics.channel_consensus({
            "apple-speech": {"language": False, "accuracy": False},
            "whisper": {"language": True, "accuracy": False},
        }, expect_failure=True)
        self.assertEqual(result["statuses"], {"language": "inconclusive", "accuracy": "fail"})
        self.assertEqual(result["expected"], {"accuracy": "fail"})
        self.assertEqual(result["outcome"], "met")
        # A control both families transcribe correctly contradicts its expectation.
        contradicted = metrics.channel_consensus(
            {"apple-speech": self.PASS, "whisper": self.PASS}, expect_failure=True)
        self.assertEqual(contradicted["outcome"], "contradicted")

    def test_a_split_language_channel_leaves_a_pass_inconclusive(self) -> None:
        result = metrics.channel_consensus({
            "apple-speech": self.PASS, "whisper": {"language": False, "accuracy": True},
        }, expect_failure=False)
        self.assertEqual(result["statuses"], {"language": "inconclusive", "accuracy": "pass"})
        self.assertEqual(result["outcome"], "inconclusive")
        agreed_fail = metrics.channel_consensus({
            "apple-speech": {"language": False, "accuracy": True},
            "whisper": {"language": False, "accuracy": True},
        }, expect_failure=False)
        self.assertEqual(agreed_fail["outcome"], "contradicted")

    def test_one_family_is_never_consensus(self) -> None:
        result = metrics.channel_consensus({"whisper": self.PASS}, expect_failure=False)
        self.assertEqual(result["statuses"], {"language": "inconclusive", "accuracy": "inconclusive"})
        self.assertEqual(result["outcome"], "inconclusive")
        self.assertTrue(metrics.single_family_meets_expectation(True, True, expect_failure=False))
        self.assertFalse(metrics.single_family_meets_expectation(False, True, expect_failure=False))
        self.assertTrue(metrics.single_family_meets_expectation(True, False, expect_failure=True))
        self.assertFalse(metrics.single_family_meets_expectation(False, True, expect_failure=True))

    def test_run_verdicts_follow_the_takes(self) -> None:
        passing = {"language": "pass", "accuracy": "pass"}
        control = {"language": "inconclusive", "accuracy": "fail"}
        self.assertEqual(
            metrics.run_channel_verdicts([(passing, False), (passing, False), (control, True)]),
            {"language": "pass", "accuracy": "pass"},
        )
        self.assertEqual(
            metrics.run_channel_verdicts([(passing, False), ({"language": "inconclusive", "accuracy": "pass"}, False)]),
            {"language": "inconclusive", "accuracy": "pass"},
        )
        self.assertEqual(
            metrics.run_channel_verdicts([(passing, False), ({"language": "pass", "accuracy": "pass"}, True)]),
            {"language": "pass", "accuracy": "fail"},
        )
        # Only the control constrains nothing on the language channel.
        self.assertEqual(metrics.run_channel_verdicts([(control, True)])["language"], "inconclusive")


if __name__ == "__main__":
    unittest.main()
