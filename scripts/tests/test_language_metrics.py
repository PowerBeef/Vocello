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
        self.assertEqual(metrics.ACCURACY_METRIC_VERSION, "normalized-edit-rate-v1")


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


if __name__ == "__main__":
    unittest.main()
