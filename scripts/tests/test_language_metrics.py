#!/usr/bin/env python3
"""Pin the shared language metrics to the Swift verifier's contract and the family rule."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import unicodedata
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
        # The table covers the product's ten languages (AQ-02); others fail closed.
        self.assertTrue(metrics.locale_matches_expected_language("ko-KR", "korean"))
        self.assertTrue(metrics.locale_matches_expected_language("pt-BR", "portuguese"))
        self.assertFalse(metrics.locale_matches_expected_language("ar-SA", "arabic"))
        self.assertEqual(set(metrics.LANGUAGE_LOCALE_CODES), {
            "english", "french", "german", "spanish", "italian", "portuguese", "russian",
            "chinese", "japanese", "korean",
        })
        self.assertEqual(metrics.PRODUCT_LANGUAGES, tuple(metrics.LANGUAGE_LOCALE_CODES))
        self.assertEqual(set(metrics.NORMALIZATION_PROFILES), set(metrics.PRODUCT_LANGUAGES))

    def test_thresholds_are_the_product_gate(self) -> None:
        self.assertEqual(metrics.MAX_ACCURACY_ERROR_RATE, 0.15)
        self.assertEqual(metrics.MIN_LANGUAGE_MATCH_SCORE, 0.5)
        self.assertEqual(metrics.ACCURACY_METRIC_VERSION, "normalization-v2-edit-rate-v3")
        self.assertEqual(metrics.SEGMENTATION_AWARE_ACCURACY_METRIC_VERSION, "segmentation-aware-edit-rate-v2")
        self.assertEqual(metrics.LEGACY_ACCURACY_METRIC_VERSION, "normalized-edit-rate-v1")
        self.assertEqual(
            [metrics.ACCURACY_METRIC_NORMALIZATIONS[version] for version in metrics.ACCURACY_METRIC_VERSIONS],
            ["text-normalization-v1", "text-normalization-v1", "text-normalization-v2"],
        )


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
        for version in ("segmentation-aware-edit-rate-v2", "normalization-v2-edit-rate-v3"):
            with self.subTest(version=version):
                aware = metrics.score_recognition(
                    entry, script=self.CASES[0][0], language="german", accuracy_metric_version=version)
                self.assertEqual(aware["accuracyMetricVersion"], version)
                self.assertAlmostEqual(aware["wordErrorRate"], 0.4)
                self.assertEqual(aware["segmentationAwareWordErrorRate"], 0.0)
                self.assertEqual(aware["wordBoundaryOnlyEdits"], 4)
                self.assertEqual(aware["errorRate"], 0.0)
                self.assertTrue(aware["accuracyPass"])
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


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "language_normalization_v2.json"
ROOT = Path(__file__).resolve().parents[2]
# The tracked corpora whose scripts a language verdict gates.
# `language_bench_evidence.build_plan` refuses a lint issue at plan time; this
# keeps the tracked copies clean before any run.
GATED_SCRIPT_CORPORA = (ROOT / "config" / "language-bench-corpus.json",)

# The code point sweep. Swift reads its Unicode data from the stdlib (lowercase
# mapping, general category) and Foundation (normalization forms), whose
# versions need not match Python's unicodedata, so every code point of these
# blocks is scored by both runtimes through the generated `sweep-` fixture
# cases: Basic Latin to Latin Extended-B, Latin Extended Additional, Cyrillic,
# kana, a CJK and a Hangul sample, the half- and full-width forms and the
# Hangul compatibility jamo. Regenerate with
# `python3 scripts/tests/test_language_metrics.py --write-sweep-cases`.
SWEEP_BLOCKS = ((0x20, 0x250), (0x1E00, 0x1F00), (0x400, 0x500), (0x3040, 0x3100),
                (0x4E00, 0x4F00), (0xAC00, 0xAD00), (0xFF00, 0xFFF0), (0x3130, 0x3190))
# One language per normalization profile: folded, compatibility and Hangul.
SWEEP_LANGUAGES = ("english", "japanese", "korean")
SWEEP_CASE_SIZE = 64
SWEEP_PREFIX = "sweep-"
# Code points left out of the sweep, each with the reason the two runtimes
# disagree on it. None is known: Python's Unicode 13.0 and 16.0 generate
# identical cases.
SWEEP_EXCLUSIONS: dict[int, str] = {}


def pinned_scores(reference: str, hypothesis: str, language: str) -> dict:
    """A fixture case's `expected` block, as the parity tests read it."""
    reference_tokens = metrics.normalized_tokens(reference, language)
    hypothesis_tokens = metrics.normalized_tokens(hypothesis, language)
    word, character = metrics.recomputed_accuracy(reference, hypothesis, language)
    primary = metrics.primary_accuracy_metric(language)
    counts = ("substitutions", "insertions", "deletions", "longestDeletionRun")
    return {
        "referenceTokens": reference_tokens,
        "hypothesisTokens": hypothesis_tokens,
        "referenceCharacters": "".join(metrics.character_units(reference_tokens)),
        "hypothesisCharacters": "".join(metrics.character_units(hypothesis_tokens)),
        "word": {key: word[key] for key in counts},
        "segmentationAwareEditDistance": word["segmentationAwareEditDistance"],
        "wordBoundaryOnlyEdits": word["wordBoundaryOnlyEdits"],
        "character": {key: character[key] for key in counts},
        "primaryMetric": primary,
        "primaryErrors": (
            character["substitutions"] + character["insertions"] + character["deletions"]
            if primary == "characterErrorRate" else word["segmentationAwareEditDistance"]
        ),
    }


def sweep_cases() -> list[dict]:
    """The `sweep-` cases: each block's code points, space-separated,
    SWEEP_CASE_SIZE to a case, in every SWEEP_LANGUAGES profile, against their
    NFD spelling (canonically equivalent, so every edit count is zero)."""
    cases = []
    for language in SWEEP_LANGUAGES:
        for start, end in SWEEP_BLOCKS:
            code_points = [point for point in range(start, end) if point not in SWEEP_EXCLUSIONS]
            for offset in range(0, len(code_points), SWEEP_CASE_SIZE):
                chunk = code_points[offset:offset + SWEEP_CASE_SIZE]
                reference = " ".join(map(chr, chunk))
                hypothesis = unicodedata.normalize("NFD", reference)
                diagnostics = {
                    "excessFillerCount": metrics.filler_counts(reference, hypothesis, language)["excessFillerCount"],
                }
                diagnostics.update(metrics.normalization_diagnostics(reference, hypothesis, language))
                cases.append({
                    "id": f"{SWEEP_PREFIX}{language}-{chunk[0]:04x}-{chunk[-1]:04x}",
                    "language": language,
                    "reference": reference,
                    "hypothesis": hypothesis,
                    "note": f"Generated sweep of U+{chunk[0]:04X}..U+{chunk[-1]:04X} against its NFD spelling.",
                    "phase": "P2a",
                    "expected": pinned_scores(reference, hypothesis, language),
                    "pythonDiagnostics": diagnostics,
                })
    return cases


def write_sweep_cases() -> None:
    """Replace the fixture's `sweep-` cases; the authored cases stay as they are."""
    document = json.loads(FIXTURES.read_text(encoding="utf-8"))
    document["cases"] = [
        case for case in document["cases"] if not case["id"].startswith(SWEEP_PREFIX)
    ] + sweep_cases()
    text = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    # Controls, format characters, unassigned code points and spaces other than
    # U+0020 are written as escapes, so the fixture stays plain readable text.
    escaped = []
    for character in text:
        if ord(character) > 0x7E and unicodedata.category(character)[0] in "CZ":
            assert ord(character) <= 0xFFFF, "the swept blocks are in the BMP"
            escaped.append(f"\\u{ord(character):04x}")
        else:
            escaped.append(character)
    FIXTURES.write_text("".join(escaped), encoding="utf-8")


class NormalizationV2ParityTests(unittest.TestCase):
    """AQ-02 P2a: text normalization v2 on the fixtures the Swift verifier's
    `WordErrorRateTests.testNormalizationV2ParityFixtures` scores too."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.document = json.loads(FIXTURES.read_text(encoding="utf-8"))
        cls.cases = cls.document["cases"]

    def test_the_fixtures_name_the_current_versions_and_cover_every_language(self) -> None:
        self.assertEqual(self.document["normalizationVersion"], metrics.TEXT_NORMALIZATION_V2)
        self.assertEqual(self.document["accuracyMetricVersion"], metrics.ACCURACY_METRIC_VERSION)
        identifiers = [case["id"] for case in self.cases]
        self.assertEqual(len(identifiers), len(set(identifiers)))
        covered = {case["language"] for case in self.cases if case["phase"] == "P2a"}
        self.assertLessEqual(set(metrics.PRODUCT_LANGUAGES), covered)

    def test_every_case_scores_exactly_as_pinned(self) -> None:
        for case in self.cases:
            with self.subTest(case=case["id"]):
                language, reference, hypothesis = case["language"], case["reference"], case["hypothesis"]
                expected = case["expected"]
                reference_tokens = metrics.normalized_tokens(reference, language)
                hypothesis_tokens = metrics.normalized_tokens(hypothesis, language)
                self.assertEqual(reference_tokens, expected["referenceTokens"])
                self.assertEqual(hypothesis_tokens, expected["hypothesisTokens"])
                self.assertEqual("".join(metrics.character_units(reference_tokens)), expected["referenceCharacters"])
                self.assertEqual("".join(metrics.character_units(hypothesis_tokens)), expected["hypothesisCharacters"])
                word, character = metrics.recomputed_accuracy(reference, hypothesis, language)
                for key, value in expected["word"].items():
                    self.assertEqual(word[key], value, key)
                self.assertEqual(word["segmentationAwareEditDistance"], expected["segmentationAwareEditDistance"])
                self.assertEqual(word["wordBoundaryOnlyEdits"], expected["wordBoundaryOnlyEdits"])
                for key, value in expected["character"].items():
                    self.assertEqual(character[key], value, key)
                primary = metrics.primary_accuracy_metric(language)
                self.assertEqual(primary, expected["primaryMetric"])
                units = len(expected["referenceCharacters"] if primary == "characterErrorRate"
                            else expected["referenceTokens"])
                self.assertAlmostEqual(
                    metrics.primary_accuracy_score(word, character, language), expected["primaryErrors"] / units)
                diagnostics = case["pythonDiagnostics"]
                self.assertEqual(
                    metrics.filler_counts(reference, hypothesis, language)["excessFillerCount"],
                    diagnostics["excessFillerCount"],
                )
                computed = metrics.normalization_diagnostics(reference, hypothesis, language)
                self.assertEqual(set(computed), set(diagnostics) - {"excessFillerCount"})
                for key, value in computed.items():
                    self.assertAlmostEqual(value, diagnostics[key], msg=key)

    def test_p2b_cases_name_a_slot_normalization_v2_leaves_empty(self) -> None:
        self.assertEqual(metrics.NORMALIZATION_EXTENSION_STEPS[metrics.TEXT_NORMALIZATION_V2], ())
        pending = [case for case in self.cases if case["phase"] == "P2b"]
        self.assertTrue(pending)
        for case in self.cases:
            with self.subTest(case=case["id"]):
                if case["phase"] == "P2b":
                    self.assertIn(case["language"], metrics.NORMALIZATION_EXTENSION_SLOTS[case["slot"]])
                    self.assertIn("expectedAfterP2b", case)
                else:
                    self.assertEqual(case["phase"], "P2a")
                    self.assertNotIn("slot", case)
                    self.assertNotIn("expectedAfterP2b", case)

    def test_the_generated_sweep_scores_every_swept_code_point(self) -> None:
        # Swift scores the same cases in WordErrorRateTests.testNormalizationV2ParityFixtures.
        generated = [case for case in self.cases if case["id"].startswith(SWEEP_PREFIX)]
        self.assertEqual(generated, sweep_cases(), "regenerate with --write-sweep-cases")
        swept = {point for start, end in SWEEP_BLOCKS for point in range(start, end)}
        for point, reason in SWEEP_EXCLUSIONS.items():
            self.assertIn(point, swept, hex(point))
            self.assertTrue(reason.strip(), hex(point))
        for language in SWEEP_LANGUAGES:
            with self.subTest(language=language):
                scored = {
                    ord(character) for case in generated if case["language"] == language
                    for character in case["reference"]
                }
                self.assertEqual(scored, swept - set(SWEEP_EXCLUSIONS))

    def test_case_folding_equals_unicode_folding_for_the_ten_languages(self) -> None:
        for start, end in SWEEP_BLOCKS:
            for code_point in range(start, end):
                character = unicodedata.normalize("NFKC", chr(code_point))
                self.assertEqual(
                    unicodedata.normalize("NFC", metrics._case_fold(character)),
                    unicodedata.normalize("NFC", character.casefold()),
                    hex(code_point),
                )

    def test_legacy_versions_keep_the_v1_tokenizer(self) -> None:
        # Legacy records rescore exactly as published: Korean was word-gated
        # over NFKD jamo, tags were words and ß stayed a letter.
        legacy = metrics.SEGMENTATION_AWARE_ACCURACY_METRIC_VERSION
        self.assertEqual(metrics.primary_accuracy_metric("korean", version=legacy), "wordErrorRate")
        self.assertEqual(metrics.primary_accuracy_metric("korean"), "characterErrorRate")
        _word, legacy_characters = metrics.recomputed_accuracy("가다", "거다", "korean", version=legacy)
        _word, characters = metrics.recomputed_accuracy("가다", "거다", "korean")
        self.assertEqual((legacy_characters["referenceCount"], characters["referenceCount"]), (4, 2))
        for reference, hypothesis in (("the train left", "<|en|>the train left"), ("Straße", "strasse")):
            legacy_word, _ = metrics.recomputed_accuracy(reference, hypothesis, "english", version=legacy)
            word, _ = metrics.recomputed_accuracy(reference, hypothesis, "english")
            self.assertEqual((legacy_word["segmentationAwareEditDistance"], word["segmentationAwareEditDistance"]), (1, 0))
        with self.assertRaises(ValueError):
            metrics.recomputed_accuracy("a", "a", "english", version="edit-rate-v9")

    def test_v3_verdicts_count_fillers_and_carry_diagnostics_that_never_gate(self) -> None:
        script = "The train left the station"
        entry = recognition(script=script, transcript="The um train uh left the station")
        verdict = metrics.score_recognition(entry, script=script, language="english")
        self.assertEqual(verdict["textNormalization"], "text-normalization-v2")
        self.assertEqual((verdict["hypothesisFillerCount"], verdict["excessFillerCount"]), (2, 2))
        self.assertAlmostEqual(verdict["errorRate"], 0.4)
        korean = metrics.score_recognition(
            recognition(script="가다", transcript="거다", language="korean"), script="가다", language="korean")
        self.assertEqual((korean["metric"], korean["errorRate"]), ("CER", 0.5))
        self.assertEqual(korean["diagnostics"], {"jamoCharacterErrorRate": 0.25})
        legacy = metrics.score_recognition(
            entry, script=script, language="english",
            accuracy_metric_version=metrics.SEGMENTATION_AWARE_ACCURACY_METRIC_VERSION)
        self.assertEqual(legacy["textNormalization"], "text-normalization-v1")
        self.assertNotIn("excessFillerCount", legacy)
        self.assertNotIn("diagnostics", legacy)


class CorpusLintTests(unittest.TestCase):
    """Gated scripts hold no digits, brackets, symbols or abbreviations (AQ-02)."""

    def test_each_refusal_has_its_code(self) -> None:
        cases = {
            "The twelve trains leave at 9": ["digit"],
            "Le train ２ part": ["digit"],
            "Sie fährt ½ Stunde": ["digit", "symbol"],  # NFKC: 1, U+2044, 2
            "Le train (rouge) part": ["bracket"],
            "列車は「のぞみ」です": ["bracket"],
            "The fare is €5": ["digit", "symbol"],
            "Rock & roll tonight": ["symbol"],
            "One in 100% of cases": ["digit", "symbol"],
            "The BBC reported it": ["abbreviation"],
            "Wir fahren z.B. heute": ["abbreviation"],
            "Приехал из США вчера": ["abbreviation"],
            # A letter number is a number: recognizers write this year as 2026年.
            "二〇二六年，火车准时开往远处的城市。": ["digit"],
        }
        for script, issues in cases.items():
            with self.subTest(script=script):
                self.assertEqual(metrics.script_lint_issues(script), issues)

    def test_each_language_refuses_its_short_forms(self) -> None:
        cases = (
            ("english", "Mr. Smith took the morning train."),
            ("english", "Mr Smith took the morning train."),
            ("english", "Trains, buses, ferries, etc. left on time."),
            ("german", "Dr. Weber fährt heute nach Hause."),
            ("german", "Züge, Busse, Fähren usw. fahren heute."),
            ("german", "Der Zug Nr. sieben fährt heute."),
            ("german", "Wir fahren z. B. heute nach Hause."),
            ("spanish", "El Sr. García llegó a la estación."),
            ("french", "M. Dupont arrive à la gare."),
            ("french", "Mme Dupont arrive à la gare."),
            ("french", "Des trains, des bus, etc. partent."),
            ("italian", "Il sig. Rossi arriva alla stazione."),
            ("portuguese", "A Sra. Silva chegou cedo."),
            ("russian", "Поезд ушёл, т. е. мы опоздали."),
            ("russian", "Он живёт на ул. Ленина."),
        )
        for language, script in cases:
            with self.subTest(language=language, script=script):
                self.assertEqual(metrics.script_lint_issues(script, language), ["abbreviation"])
                # Without a language, every language's forms apply.
                self.assertEqual(metrics.script_lint_issues(script), ["abbreviation"])

    def test_words_and_letters_that_share_a_short_form_pass(self) -> None:
        # French m' is M. without its full stop; "No." (number) is not listed,
        # because "no." ends English sentences; one-letter words are not initials.
        for language, script in (
            ("french", "Il m'a vu à la gare."),
            ("english", "The answer was no."),
            ("russian", "Мы шли к дому, и я увидел поезд."),
        ):
            with self.subTest(language=language):
                self.assertEqual(metrics.script_lint_issues(script, language), [])

    def test_spelled_scripts_pass(self) -> None:
        for language, script in (
            ("english", "The morning train left the quiet station on time."),
            ("spanish", "¿Dónde está la estación? ¡Aquí!"),
            ("french", "L'homme arrive à l'heure, n'est-ce pas ?"),
            ("german", "Viele Menschen sehen Häuser, Straßen und Bäume."),
            ("chinese", "今天天气很好，火车准时开往远处的城市。"),
            ("japanese", "今日は天気がよく、赤い列車が駅を出発します。"),
            ("korean", "아침 열차는 조용한 역을 제시간에 떠났습니다."),
            ("russian", "Утренний поезд вовремя покинул тихую станцию."),
            ("portuguese", "A estação não fica longe."),
            ("italian", "Il treno del mattino arriva in orario."),
        ):
            with self.subTest(script=script):
                self.assertEqual(metrics.script_lint_issues(script, language), [])
                self.assertEqual(metrics.script_lint_issues(script), [])

    def test_the_tracked_gated_corpora_are_clean(self) -> None:
        for corpus_path in GATED_SCRIPT_CORPORA:
            corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
            for entry in corpus["languages"]:
                with self.subTest(corpus=corpus_path.name, language=entry["id"]):
                    self.assertIn(entry["id"], metrics.PRODUCT_LANGUAGES)
                    self.assertEqual(metrics.script_lint_issues(entry["script"], entry["id"]), [])


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
    if sys.argv[1:] == ["--write-sweep-cases"]:
        write_sweep_cases()
    else:
        unittest.main()
