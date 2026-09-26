"""Language-verification metrics shared by every Python consumer.

One tokenizer, one edit distance, one locale table, one threshold set and one
family-consensus rule, applied per verdict channel. `check_language_output.py`, `publish_benchmark_history.py`,
`run_local_delivery_cascade.py` and `independent_asr.py` import from here; the
Swift `GenerationOutputVerifier` keeps its own implementation as the independent
cross-check. Text normalization v2 (AQ-02) is pinned to the Swift verifier by
the shared fixtures in `scripts/tests/fixtures/language_normalization_v2.json`,
which `scripts/tests/test_language_metrics.py` and the Swift
`WordErrorRateTests` both score; the legacy v1 tokenizer keeps its own
fixtures (diacritic and width folding, alphanumeric token boundaries). Both
share the stable diagonal → deletion → insertion ties.

Thresholds are facts about the product gate, not tunables: 15 % normalized edit
rate and a 0.5 language-match score. Change them in one place, with the
threshold-change authority described in `docs/reference/audio-qc-engineering.md`.
"""

from __future__ import annotations

from collections.abc import Callable
import hashlib
import math
import re
from typing import Any
import unicodedata


MAX_ACCURACY_ERROR_RATE = 0.15
MIN_LANGUAGE_MATCH_SCORE = 0.5
# Accuracy metric versions. Each names the text normalization and the word
# rate it gates, so a record says exactly how it was scored:
# - v1 gates the plain word or character rate under text normalization v1.
# - v2 (WER v2, audit #43; decided 2026-09-25 by the audit's recommendation)
#   gates the segmentation-aware word rate, which does not charge a
#   recognizer's word-boundary choice ("vor Mittag" heard as "Vormittag"), under
#   the same normalization. The character rate is the same under v1 and v2.
# - v3 (AQ-02 phase P2a, 2026-09-25; the maintainer accepted the audio QC
#   audit's recommendations) keeps WER v2 and scores under text normalization
#   v2 (`normalized_tokens`): NFKC (NFC for Korean) and case folding, the extra
#   Latin folds, recognizer-tag stripping, English, French and Italian words
#   joined across an inner apostrophe, and Korean gated by its syllable rate.
LEGACY_ACCURACY_METRIC_VERSION = "normalized-edit-rate-v1"
SEGMENTATION_AWARE_ACCURACY_METRIC_VERSION = "segmentation-aware-edit-rate-v2"
ACCURACY_METRIC_VERSION = "normalization-v2-edit-rate-v3"
ACCURACY_METRIC_VERSIONS = (
    LEGACY_ACCURACY_METRIC_VERSION, SEGMENTATION_AWARE_ACCURACY_METRIC_VERSION, ACCURACY_METRIC_VERSION,
)
# Versions whose word gate reads the segmentation-aware rate (a tuple, so a
# malformed declared version tests false instead of raising).
SEGMENTATION_AWARE_METRIC_VERSIONS = (SEGMENTATION_AWARE_ACCURACY_METRIC_VERSION, ACCURACY_METRIC_VERSION)
TEXT_NORMALIZATION_V1 = "text-normalization-v1"
TEXT_NORMALIZATION_V2 = "text-normalization-v2"
# The text normalization each accuracy metric version scores under.
ACCURACY_METRIC_NORMALIZATIONS = {
    LEGACY_ACCURACY_METRIC_VERSION: TEXT_NORMALIZATION_V1,
    SEGMENTATION_AWARE_ACCURACY_METRIC_VERSION: TEXT_NORMALIZATION_V1,
    ACCURACY_METRIC_VERSION: TEXT_NORMALIZATION_V2,
}
# The longest run of tokens on either side of one merge or split that v2
# credits (a four-word compound and its spaced spelling). Swift mirrors it as
# `VoiceClipTranscriber.wordBoundarySpanLimit`.
WORD_BOUNDARY_SPAN_LIMIT = 4
# Warn-only (audit #84): the longest run of consecutive reference units the
# recognizer deleted, on the primary metric's units. A skipped phrase of two to
# four words stays under the 15 % gate on 17-32-unit scripts; the run exposes
# it. It never changes a verdict or the accuracy metric above.
DELETION_RUN_WARNING_LENGTH = 2

# The product's ten languages (`Qwen3SupportedLanguage` without Auto). The
# tracked corpus (`config/language-bench-corpus.json`) scripts six of them; a
# language outside this table fails closed.
LANGUAGE_LOCALE_CODES: dict[str, str] = {
    "english": "en",
    "french": "fr",
    "german": "de",
    "spanish": "es",
    "italian": "it",
    "portuguese": "pt",
    "russian": "ru",
    "chinese": "zh",
    "japanese": "ja",
    "korean": "ko",
}
PRODUCT_LANGUAGES = tuple(LANGUAGE_LOCALE_CODES)
# Character error rate is the primary metric where words are not reliably
# whitespace delimited. Korean joined at v3 (audit AQ-F21): its eojeol spacing
# is inconsistent, so it gates the syllable rate. v1 and v2 records keep the
# Chinese and Japanese set, under which Korean was word-scored.
CHARACTER_ERROR_LANGUAGES = frozenset({"chinese", "japanese", "korean"})
LEGACY_CHARACTER_ERROR_LANGUAGES = frozenset({"chinese", "japanese"})

# Recognizer families a language verdict may cite. One family is one witness;
# `consensus` needs two independent families for a pass or a fail.
RECOGNITION_FAMILIES = ("apple-speech", "whisper", "sensevoice")
# What each family's language check observes (audit #42). Apple Speech runs
# locked to the expected locale and its languagePass is text language
# detection over that locked transcript: transcript-language consistency, close
# to unfalsifiable for an anglicized take. Whisper and SenseVoice identify the
# language from the audio. Records declare this beside their families.
LANGUAGE_CHECK_KINDS = {
    "apple-speech": "transcript-language-consistency",
    "whisper": "audio-language-identification",
    "sensevoice": "audio-language-identification",
}
SENSEVOICE_LANGUAGES = frozenset({"english", "chinese", "japanese", "korean", "cantonese"})
MAX_TEXT_CHARACTERS = 4096

# Identity of the independent (non-Apple) recognizer evidence in history records.
INDEPENDENT_OUTPUT_SCHEMA = 1
INDEPENDENT_OUTPUT_ALGORITHM = "independent-asr-output-v1"
INDEPENDENT_RECOGNITION_SCHEMA = 1
INDEPENDENT_ASR_ALGORITHM = "mlx-whisper-locked-decode-v1"
INDEPENDENT_REQUIRED_PASS_COUNT = 1

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def locale_matches_expected_language(identifier: str, expected_language: str) -> bool:
    """`fr-CA`, `fr_FR` and `fr` all match `french`; an unknown language never matches."""
    expected_code = LANGUAGE_LOCALE_CODES.get(expected_language)
    if expected_code is None or not isinstance(identifier, str) or not identifier:
        return False
    return re.split(r"[-_]", identifier, maxsplit=1)[0].lower() == expected_code


def _require_version(version: str) -> None:
    if version not in ACCURACY_METRIC_VERSIONS:
        raise ValueError(f"unknown accuracy metric version {version!r}")


def character_error_languages(version: str = ACCURACY_METRIC_VERSION) -> frozenset[str]:
    """The languages gated by their character rate under one metric version."""
    _require_version(version)
    if ACCURACY_METRIC_NORMALIZATIONS[version] == TEXT_NORMALIZATION_V1:
        return LEGACY_CHARACTER_ERROR_LANGUAGES
    return CHARACTER_ERROR_LANGUAGES


def primary_accuracy_metric(expected_language: str, *, version: str = ACCURACY_METRIC_VERSION) -> str:
    return (
        "characterErrorRate" if expected_language in character_error_languages(version)
        else "wordErrorRate"
    )


def primary_accuracy_score(
    word: dict[str, Any], character: dict[str, Any], expected_language: str,
    *, version: str = ACCURACY_METRIC_VERSION,
) -> float:
    """The gated score under one accuracy metric version.

    v1 gates the plain word or character rate; v2 and v3 gate the
    segmentation-aware word rate (characters are unchanged), and v3 gates
    Korean by its character rate. An unknown version fails closed."""
    _require_version(version)
    if primary_accuracy_metric(expected_language, version=version) == "characterErrorRate":
        return float(character["errorRate"])
    if version in SEGMENTATION_AWARE_METRIC_VERSIONS:
        return float(word["segmentationAwareErrorRate"])
    return float(word["errorRate"])


# --------------------------------------------------------------------------- #
# Text normalization v2 (AQ-02 P2a; audit AQ-F21, AQ-F24, AQ-F25)
# --------------------------------------------------------------------------- #
# Swift mirror: `VoiceClipTranscriber.normalizedWordTokens(_:language:)`. Every
# step is defined per code point from Unicode properties both runtimes expose
# (normalization forms, the full lowercase mapping, general categories), so the
# two agree by construction; the shared fixtures prove it.
#
# 1. Unicode form: NFKC, or NFC for Korean (NFKC would recompose compatibility
#    jamo into syllables the recognizer never wrote).
# 2. Recognizer tags (SenseVoice and Whisper `<|…|>`) become spaces.
# 3. Case folding: the context-free full lowercase mapping of each code point,
#    then CASE_FOLD_EXTRAS. After NFKC this equals Unicode full case folding for
#    the modern Latin, Cyrillic, kana, CJK and Hangul text of the ten languages.
# 4. Folded languages (Latin and Cyrillic, and any language outside the table):
#    NFKD, drop nonspacing marks (the v1 fold: é→e, ё→е, й→и, ñ→n), then
#    ADDITIONAL_DIACRITICS for the letters NFKD cannot decompose. Chinese and
#    Japanese keep their marks (dakuten), Korean keeps its syllables.
# 5. Tokens are runs of letters, marks and numbers (general categories L, M, N);
#    everything else, punctuation and symbols included, is a boundary. In
#    English, French and Italian an apostrophe between two word characters
#    joins them into one token instead (l'homme, dell'autunno, don't), and is
#    not itself scored: "l'homme", "l’homme" and "lhomme" are one spelling, and
#    "l homme" is a word-boundary choice WER v2 does not charge. Other
#    languages split at an apostrophe, as v1 did. Brackets are boundaries:
#    their contents stay (Qwen3-TTS speaks them), unlike Whisper's normalizers,
#    which delete bracketed text and fillers. Fillers stay words;
#    `filler_counts` counts them and the edit rate charges them.
#
# Character units are the code points of the tokens, so the character rate is
# space-free and punctuation-free; for Korean they are Hangul syllables, never
# NFKD jamo (AQ-F21).
FOLDED_PROFILE = "folded"
COMPATIBILITY_PROFILE = "compatibility"
HANGUL_PROFILE = "hangul"
NORMALIZATION_PROFILES: dict[str, str] = {
    "english": FOLDED_PROFILE,
    "french": FOLDED_PROFILE,
    "german": FOLDED_PROFILE,
    "spanish": FOLDED_PROFILE,
    "italian": FOLDED_PROFILE,
    "portuguese": FOLDED_PROFILE,
    "russian": FOLDED_PROFILE,
    "chinese": COMPATIBILITY_PROFILE,
    "japanese": COMPATIBILITY_PROFILE,
    "korean": HANGUL_PROFILE,
}
APOSTROPHE_LANGUAGES = frozenset({"english", "french", "italian"})
# U+0027, U+2019 and U+02BC (a modifier letter, so it is tested before the
# word-character rule, and never a word character). U+2018 is an opening quote
# and stays a boundary.
APOSTROPHES = frozenset({"\x27", "\u2019", "\u02bc"})
CASE_FOLD_EXTRAS = {"ß": "ss", "ς": "σ"}
# Letters NFKD leaves whole (ß is already folded by CASE_FOLD_EXTRAS; it stays
# here for the audit's table). Applied to folded languages only.
ADDITIONAL_DIACRITICS = {"ß": "ss", "æ": "ae", "œ": "oe", "ø": "o", "ł": "l"}
RECOGNIZER_TAG = re.compile(r"<\|[^|<>]*\|>")

# P2b (AQ-02, decision 4: package pins and downloads). The package-backed steps
# each language gains, by slot. Normalization v2 registers none of them: a
# filled slot moves what the metrics measure, so P2b registers its steps under a
# new normalization (and accuracy metric) version in NORMALIZATION_EXTENSION_STEPS
# and never changes v2. Fixtures that need a slot carry `"phase": "P2b"`.
NORMALIZATION_EXTENSION_SLOTS: dict[str, dict[str, str]] = {
    # OpenCC t2s (Apache-2.0) on both sides; never zhconv (GPL).
    "script-variant": {"chinese": "opencc-t2s"},
    # Arabic digits to spoken numerals on both sides of the primary metric.
    "digit-verbalization": {"chinese": "cn2an", "japanese": "num2words-ja"},
    # A verbalized-digit WER diagnostic beside the primary metric.
    "digit-diagnostic": {
        language: "num2words"
        for language in ("english", "french", "german", "spanish", "italian", "portuguese", "russian")
    },
    # Kana-reading CER (fugashi with unidic-lite); never pykakasi (GPL).
    "reading-diagnostic": {"japanese": "fugashi-unidic-lite"},
    # British and American spellings (Whisper's english.json, without its
    # bracket and filler steps).
    "spelling-variant": {"english": "whisper-english-spelling-map"},
}
# The steps each normalization version applies after case folding and before
# the script fold, as `step(text, language) -> text`. v2 has none.
NORMALIZATION_EXTENSION_STEPS: dict[str, tuple[Callable[[str, str], str], ...]] = {
    TEXT_NORMALIZATION_V2: (),
}


def normalization_profile(language: str) -> str:
    """A language's normalization v2 profile; unknown languages fold like Latin."""
    return NORMALIZATION_PROFILES.get(language, FOLDED_PROFILE)


def _case_fold(text: str) -> str:
    return "".join(
        CASE_FOLD_EXTRAS.get(lowered, lowered)
        for character in text for lowered in character.lower()
    )


def _is_word_character(character: str) -> bool:
    return character not in APOSTROPHES and unicodedata.category(character)[0] in "LMN"


def normalized_text(text: str, language: str, *, preserve_diacritics: bool = False) -> str:
    """Steps 1-4 of normalization v2; `preserve_diacritics` skips step 4 (a diagnostic)."""
    profile = normalization_profile(language)
    folded = unicodedata.normalize("NFC" if profile == HANGUL_PROFILE else "NFKC", text)
    folded = _case_fold(RECOGNIZER_TAG.sub(" ", folded))
    for step in NORMALIZATION_EXTENSION_STEPS[TEXT_NORMALIZATION_V2]:
        folded = step(folded, language)
    if profile == FOLDED_PROFILE and not preserve_diacritics:
        folded = "".join(
            ADDITIONAL_DIACRITICS.get(character, character)
            for character in unicodedata.normalize("NFKD", folded)
            if unicodedata.category(character) != "Mn"
        )
    return folded


def normalized_tokens(text: str, language: str, *, preserve_diacritics: bool = False) -> list[str]:
    """Normalization v2 word tokens (steps 1-5)."""
    folded = normalized_text(text, language, preserve_diacritics=preserve_diacritics)
    joins_apostrophes = language in APOSTROPHE_LANGUAGES
    tokens: list[str] = []
    current: list[str] = []
    for index, character in enumerate(folded):
        if _is_word_character(character):
            current.append(character)
        elif (
            joins_apostrophes and character in APOSTROPHES and current
            and index + 1 < len(folded) and _is_word_character(folded[index + 1])
        ):
            continue  # an intra-word apostrophe joins the word and is not scored
        elif current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    return tokens


def character_units(tokens: list[str]) -> list[str]:
    """The space-free code points of normalized tokens."""
    return [character for token in tokens for character in token]


def scoring_units(text: str, language: str, *, version: str = ACCURACY_METRIC_VERSION) -> tuple[list[str], list[str]]:
    """The word tokens and character units one metric version scores."""
    _require_version(version)
    if ACCURACY_METRIC_NORMALIZATIONS[version] == TEXT_NORMALIZATION_V1:
        preserve = language in LEGACY_CHARACTER_ERROR_LANGUAGES
        return (
            normalized_word_tokens(text),
            list("".join(normalized_word_tokens(text, preserve_diacritics=preserve))),
        )
    tokens = normalized_tokens(text, language)
    return tokens, character_units(tokens)


# Fillers (audit AQ-F25) stay in both transcripts, and the edit rate charges
# them; they are also counted, because a filler the script does not contain can
# be a real TTS defect (babble, hesitation). Surface forms go through the same
# normalization as the texts. Word languages count whole tokens; Chinese and
# Japanese, which have no word boundaries, count occurrences in the character
# units, longest form first.
FILLER_WORDS: dict[str, tuple[str, ...]] = {
    "english": ("uh", "um", "uhm", "umm", "erm", "hmm", "mhm"),
    "french": ("euh", "heu", "hum", "hmm"),
    "german": ("äh", "ähm", "öhm", "hmm", "mhm"),
    "spanish": ("eh", "ehm", "em", "mmm", "hmm"),
    "italian": ("ehm", "uhm", "mmm", "hmm"),
    "portuguese": ("hã", "ahn", "hum", "hmm", "uhm"),
    "russian": ("э", "ээ", "эм", "мм", "ммм", "хм"),
    "chinese": ("嗯", "呃"),
    "japanese": ("えーと", "えっと", "あのー", "うーん", "えー"),
    "korean": ("음", "으음", "어", "흠"),
}


def _normalized_fillers(language: str) -> tuple[str, ...]:
    forms = {
        "".join(character_units(normalized_tokens(word, language)))
        for word in FILLER_WORDS.get(language, ())
    }
    return tuple(sorted((form for form in forms if form), key=lambda form: (-len(form), form)))


def filler_count(tokens: list[str], language: str) -> int:
    """How many fillers normalized tokens hold (0 for a language without a lexicon)."""
    fillers = _normalized_fillers(language)
    if not fillers:
        return 0
    if language in ("chinese", "japanese"):
        units = "".join(character_units(tokens))
        count = 0
        index = 0
        while index < len(units):
            match = next((form for form in fillers if units.startswith(form, index)), None)
            if match is None:
                index += 1
            else:
                count += 1
                index += len(match)
        return count
    return sum(1 for token in tokens if token in fillers)


def filler_counts(reference: str, hypothesis: str, language: str) -> dict[str, int]:
    """Fillers in each text, and the hypothesis fillers the script does not hold."""
    reference_count = filler_count(normalized_tokens(reference, language), language)
    hypothesis_count = filler_count(normalized_tokens(hypothesis, language), language)
    return {
        "referenceFillerCount": reference_count,
        "hypothesisFillerCount": hypothesis_count,
        "excessFillerCount": max(0, hypothesis_count - reference_count),
    }


# Diacritic-preserving WER is a diagnostic for the folded Latin languages
# (section 6 of the audit): the gate folds accents, the diagnostic shows what
# the fold forgave.
DIACRITIC_DIAGNOSTIC_LANGUAGES = frozenset({"french", "german", "spanish", "italian", "portuguese"})


def normalization_diagnostics(reference: str, hypothesis: str, language: str) -> dict[str, float]:
    """Normalization v2 diagnostics that never gate: Korean jamo CER and
    diacritic-preserving WER (both scored beside the primary metric)."""
    diagnostics: dict[str, float] = {}
    if language == "korean":
        reference_jamo = list(unicodedata.normalize("NFD", "".join(character_units(
            normalized_tokens(reference, language)))))
        hypothesis_jamo = list(unicodedata.normalize("NFD", "".join(character_units(
            normalized_tokens(hypothesis, language)))))
        diagnostics["jamoCharacterErrorRate"] = float(edit_metrics(reference_jamo, hypothesis_jamo)["errorRate"])
    if language in DIACRITIC_DIAGNOSTIC_LANGUAGES:
        reference_words = normalized_tokens(reference, language, preserve_diacritics=True)
        hypothesis_words = normalized_tokens(hypothesis, language, preserve_diacritics=True)
        diagnostics["diacriticPreservingWordErrorRate"] = float(
            segmentation_aware_metrics(reference_words, hypothesis_words)["segmentationAwareErrorRate"]
        )
    return diagnostics


# Corpus lint (audit section 6 and AQ-F23): a gated script holds only words a
# recognizer writes one way. Digits (every recognizer writes some numbers as
# digits and others as words, and Russian numerals inflect), brackets (the
# model may or may not speak their contents), symbols and spoken punctuation,
# and abbreviations (all-capital acronyms, dotted forms such as "z.B." and the
# language's short forms in ABBREVIATIONS) are refused.
# `language_bench_evidence.build_plan` refuses a corpus with any issue, and the
# tracked gated corpora are linted by the Python suite.
SPOKEN_PUNCTUATION = frozenset("@#%&*/\\§¶‰‱†‡′″")
_DOTTED_ABBREVIATION = re.compile(r"(?<![^\W\d_])[^\W\d_]\.[^\W\d_]")
_LETTER_RUN = re.compile(r"[^\W\d_]+")
# Titles and short forms a recognizer expands, keeps or drops at will, by
# language, as lowercase letter runs: `always` forms are refused wherever they
# stand (no word of the language is spelled so: "Mme", "Mr Smith", "usw."),
# `dotted` forms only before a full stop (bare, they are words or letters:
# French "M." for Monsieur, Russian "т. е."). A script in a language outside
# the table is linted against every language's forms.
ABBREVIATIONS: dict[str, dict[str, frozenset[str]]] = {
    "english": {
        "always": frozenset({"mr", "mrs", "ms", "dr", "st", "jr", "vs", "etc"}),
        "dotted": frozenset(),
    },
    "french": {
        "always": frozenset({"mme", "mmes", "mlle", "mlles", "mm", "dr", "cf", "etc"}),
        "dotted": frozenset({"m"}),
    },
    "german": {
        "always": frozenset({"dr", "nr", "usw", "bzw", "ca", "str", "evtl", "ggf", "inkl", "etc"}),
        "dotted": frozenset({"z", "d", "u"}),  # z. B., d. h., u. a.
    },
    "spanish": {
        "always": frozenset({"sr", "sra", "srta", "dr", "dra", "ud", "uds", "etc"}),
        "dotted": frozenset(),
    },
    "italian": {
        "always": frozenset({"sig", "sigg", "dott", "dr", "ecc", "etc"}),
        "dotted": frozenset(),
    },
    "portuguese": {
        "always": frozenset({"sr", "sra", "srta", "dr", "dra", "etc"}),
        "dotted": frozenset(),
    },
    "russian": {
        "always": frozenset({"ул", "тыс", "млн", "млрд", "руб", "коп", "см", "стр", "др"}),
        "dotted": frozenset({"г", "гг", "т", "д", "п"}),  # г., т. е., т. д., т. п.
    },
    "chinese": {"always": frozenset(), "dotted": frozenset()},
    "japanese": {"always": frozenset(), "dotted": frozenset()},
    "korean": {"always": frozenset(), "dotted": frozenset()},
}


def _abbreviation_forms(language: str | None) -> tuple[frozenset[str], frozenset[str]]:
    tables = [ABBREVIATIONS[language]] if language in ABBREVIATIONS else list(ABBREVIATIONS.values())
    return (
        frozenset().union(*(table["always"] for table in tables)),
        frozenset().union(*(table["dotted"] for table in tables)),
    )


def script_lint_issues(script: str, language: str | None = None) -> list[str]:
    """Why a script may not be gated (empty when it may). Codes are sorted.

    `language` selects its ABBREVIATIONS; None, or a language outside the
    table, applies every language's."""
    issues: set[str] = set()
    text = unicodedata.normalize("NFKC", script)
    for character in script + text:
        category = unicodedata.category(character)
        # Every number: Nd, Nl and No (1, ２, ², ½, ①, Ⅻ, 〇); recognizers
        # write "二〇二六年" as "2026年". Han numerals such as 二 are letters
        # this lint cannot tell from words, so gated scripts spell no numbers.
        if category[0] == "N":
            issues.add("digit")
        elif category in ("Ps", "Pe"):
            issues.add("bracket")
        elif category[0] == "S" or character in SPOKEN_PUNCTUATION:
            issues.add("symbol")
    always, dotted = _abbreviation_forms(language)
    for match in _LETTER_RUN.finditer(text):
        run = match.group()
        form = run.lower()
        if (
            (len(run) >= 2 and run.isupper())
            or form in always
            or (form in dotted and text.startswith(".", match.end()))
        ):
            issues.add("abbreviation")
    if _DOTTED_ABBREVIATION.search(text):
        issues.add("abbreviation")
    return sorted(issues)


def normalized_word_tokens(text: str, *, preserve_diacritics: bool = False) -> list[str]:
    """The v1 tokenizer (accuracy metric versions v1 and v2): fold, lowercase,
    split on non-alphanumerics. Kept byte-for-byte so legacy records rescore."""
    if preserve_diacritics:
        # CJK CER must distinguish Japanese dakuten/handakuten while still
        # normalizing full-width compatibility forms.
        folded = unicodedata.normalize("NFKC", text)
    else:
        folded = unicodedata.normalize("NFKD", text)
        folded = "".join(
            character for character in folded
            if unicodedata.category(character) != "Mn"
        )
    folded = folded.lower()
    tokens: list[str] = []
    current: list[str] = []
    for character in folded:
        if character.isalnum():
            current.append(character)
        elif current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    return tokens


def edit_metrics(reference: list[Any], hypothesis: list[Any]) -> dict[str, int | float]:
    """Levenshtein with retained operation counts.

    Ties resolve diagonal (match/substitution), then deletion, then insertion,
    exactly as `VoiceClipTranscriber`; keeping the counts lets a consumer refuse
    an aggregate error rate that does not match its own edits. Each cell also
    carries the deletion run along its chosen path (a match, substitution or
    insertion ends a run), so ``longestDeletionRun`` describes the same
    alignment the counts do.
    """
    # (substitutions, insertions, deletions, current deletion run, longest run)
    previous: list[tuple[int, int, int, int, int]] = [
        (0, index, 0, 0, 0) for index in range(len(hypothesis) + 1)
    ]
    for left_index, left in enumerate(reference):
        current: list[tuple[int, int, int, int, int]] = [
            (0, 0, left_index + 1, left_index + 1, left_index + 1)
        ]
        for right_index, right in enumerate(hypothesis):
            substitutions, insertions, deletions, _run, longest = previous[right_index]
            best = (substitutions + (left != right), insertions, deletions, 0, longest)
            substitutions, insertions, deletions, run, longest = previous[right_index + 1]
            candidate = (substitutions, insertions, deletions + 1, run + 1, max(longest, run + 1))
            if sum(candidate[:3]) < sum(best[:3]):
                best = candidate
            substitutions, insertions, deletions, _run, longest = current[right_index]
            candidate = (substitutions, insertions + 1, deletions, 0, longest)
            if sum(candidate[:3]) < sum(best[:3]):
                best = candidate
            current.append(best)
        previous = current
    substitutions, insertions, deletions, _run, longest_run = previous[-1]
    distance = substitutions + insertions + deletions
    rate = (distance / len(reference)) if reference else (0.0 if not hypothesis else 1.0)
    return {
        "substitutions": substitutions,
        "insertions": insertions,
        "deletions": deletions,
        "referenceCount": len(reference),
        "hypothesisCount": len(hypothesis),
        "errorRate": rate,
        "longestDeletionRun": longest_run,
    }


def segmentation_aware_distance(reference: list[str], hypothesis: list[str]) -> int:
    """Word edit distance that does not charge word-boundary placement (WER v2).

    Levenshtein over the tokens plus one more operation at no cost: a block of
    one to WORD_BOUNDARY_SPAN_LIMIT reference tokens aligns with a block of one
    to WORD_BOUNDARY_SPAN_LIMIT hypothesis tokens when both spell the same
    characters and one side has two or more tokens (a merge, a split or a moved
    boundary). The minimum is unique, so the Swift mirror needs only the same
    operation set, not the same traversal, to agree exactly.
    """
    if not reference:
        return len(hypothesis)
    if not hypothesis:
        return len(reference)
    # Every hypothesis block, by spelling: the block ending at `end` of `length` tokens.
    blocks: dict[str, list[tuple[int, int]]] = {}
    for end in range(1, len(hypothesis) + 1):
        spelling = ""
        for length in range(1, min(WORD_BOUNDARY_SPAN_LIMIT, end) + 1):
            spelling = hypothesis[end - length] + spelling
            blocks.setdefault(spelling, []).append((end, length))
    table = [list(range(len(hypothesis) + 1))]
    for row in range(1, len(reference) + 1):
        credited = [math.inf] * (len(hypothesis) + 1)
        spelling = ""
        for length in range(1, min(WORD_BOUNDARY_SPAN_LIMIT, row) + 1):
            spelling = reference[row - length] + spelling
            for end, hypothesis_length in blocks.get(spelling, ()):
                if length == 1 and hypothesis_length == 1:
                    continue
                credited[end] = min(credited[end], table[row - length][end - hypothesis_length])
        current = [row]
        previous = table[row - 1]
        for column in range(1, len(hypothesis) + 1):
            current.append(int(min(
                previous[column - 1] + (reference[row - 1] != hypothesis[column - 1]),
                previous[column] + 1,
                current[column - 1] + 1,
                credited[column],
            )))
        table.append(current)
    return table[-1][-1]


def segmentation_aware_metrics(reference: list[str], hypothesis: list[str]) -> dict[str, int | float]:
    """The WER v2 decomposition: v2 distance, its rate and the credited boundary edits."""
    legacy = edit_metrics(reference, hypothesis)
    distance = segmentation_aware_distance(reference, hypothesis)
    legacy_distance = int(legacy["substitutions"]) + int(legacy["insertions"]) + int(legacy["deletions"])
    rate = (distance / len(reference)) if reference else (0.0 if not hypothesis else 1.0)
    return {
        "segmentationAwareEditDistance": distance,
        "segmentationAwareErrorRate": rate,
        "wordBoundaryOnlyEdits": legacy_distance - distance,
    }


def recomputed_accuracy(
    reference: str, hypothesis: str, expected_language: str,
    *, version: str = ACCURACY_METRIC_VERSION,
) -> tuple[dict[str, int | float], dict[str, int | float]]:
    """Word and character metrics of one transcript against its script.

    Scored under the text normalization of `version` (v1 and v2: the v1
    tokenizer; v3: normalization v2). The word metrics also carry the WER v2
    decomposition (`segmentationAwareErrorRate`, `wordBoundaryOnlyEdits`)."""
    reference_words, reference_characters = scoring_units(reference, expected_language, version=version)
    hypothesis_words, hypothesis_characters = scoring_units(hypothesis, expected_language, version=version)
    word = edit_metrics(reference_words, hypothesis_words)
    word.update(segmentation_aware_metrics(reference_words, hypothesis_words))
    character = edit_metrics(reference_characters, hypothesis_characters)
    return word, character


def edge_allowance_seconds(duration_seconds: float) -> float:
    """The shipping edge-coverage tolerance: 15 % of the clip, clamped to 1–2.5 s."""
    return min(2.5, max(1.0, duration_seconds * 0.15))


def edges_covered(first_start: float, last_end: float, duration_seconds: float) -> bool:
    """True when recognized speech reaches both ends of the file within the allowance.

    This is evidence that the whole file was read, not that its interior is
    complete; interior content is what WER/CER measure.
    """
    if not all(math.isfinite(value) for value in (first_start, last_end, duration_seconds)):
        return False
    if duration_seconds <= 0 or first_start < 0 or last_end <= first_start:
        return False
    allowance = edge_allowance_seconds(duration_seconds)
    return first_start <= allowance and last_end >= duration_seconds - allowance


def recognition_issues(
    recognition: Any, *, audio_sha256: str, script: Any, script_sha256: Any,
    language: str, duration_seconds: float,
) -> list[str]:
    """Why one recognition entry may not act as a witness (empty = qualified).

    The entry must be bound to the exact audio bytes and script, declare a
    complete full-file read of the same duration, name a known family and carry
    three digests of provenance. A supplied score is never trusted: consumers
    recompute WER/CER from the transcript with `score_recognition`.
    """
    if not isinstance(recognition, dict):
        return ["not-an-object"]
    issues: list[str] = []
    family = recognition.get("modelFamily")
    if family not in RECOGNITION_FAMILIES:
        issues.append("unknown-family")
    if recognition.get("audioSHA256") != audio_sha256:
        issues.append("audio-digest-mismatch")
    if not isinstance(script, str) or not 0 < len(script.strip()) <= MAX_TEXT_CHARACTERS:
        issues.append("script-invalid")
    elif text_sha256(script) != script_sha256:
        issues.append("script-digest-mismatch")
    if recognition.get("inputTextSHA256") != script_sha256:
        issues.append("input-text-digest-mismatch")
    if recognition.get("status") != "complete":
        issues.append("incomplete")
    if recognition.get("outputLanguage") != language:
        issues.append("output-language-mismatch")
    if recognition.get("fullFileProcessed") is not True:
        issues.append("partial-file")
    processed = recognition.get("processedDurationSeconds")
    if (isinstance(processed, bool) or not isinstance(processed, (int, float))
            or not math.isfinite(processed)
            or abs(processed - duration_seconds) > max(0.001, duration_seconds * 0.001)):
        issues.append("processed-duration-mismatch")
    provenance = recognition.get("provenance")
    if (not isinstance(provenance, dict)
            or set(provenance) != {"runtimeSHA256", "modelIdentitySHA256", "configSHA256"}
            or not all(is_sha256(provenance[key]) for key in provenance)):
        issues.append("provenance-incomplete")
    transcript = recognition.get("transcript")
    if not isinstance(transcript, str) or not 0 < len(transcript.strip()) <= MAX_TEXT_CHARACTERS:
        issues.append("transcript-invalid")
    # SenseVoice's language set cannot be enlarged by an input attestation.
    if family == "sensevoice" and language not in SENSEVOICE_LANGUAGES:
        issues.append("family-cannot-recognize-language")
    return issues


def score_recognition(
    recognition: dict[str, Any], *, script: str, language: str,
    accuracy_metric_version: str = ACCURACY_METRIC_VERSION,
) -> dict[str, Any]:
    """Recompute the verdict of one qualified recognition from its transcript.

    Under normalization v2 (v3) the verdict also counts fillers (never gated)
    and carries the normalization diagnostics (never gated)."""
    transcript = str(recognition.get("transcript", ""))
    word, character = recomputed_accuracy(script, transcript, language, version=accuracy_metric_version)
    metric = primary_accuracy_metric(language, version=accuracy_metric_version)
    score = primary_accuracy_score(word, character, language, version=accuracy_metric_version)
    language_pass = recognition.get("detectedLanguage") == language
    accuracy_pass = score <= MAX_ACCURACY_ERROR_RATE
    deletion_run = (character if metric == "characterErrorRate" else word)["longestDeletionRun"]
    normalization = ACCURACY_METRIC_NORMALIZATIONS[accuracy_metric_version]
    extra: dict[str, Any] = {}
    if normalization == TEXT_NORMALIZATION_V2:
        extra = {
            **filler_counts(script, transcript, language),
            "diagnostics": normalization_diagnostics(script, transcript, language),
        }
    return {
        "textNormalization": normalization,
        **extra,
        "modelFamily": recognition.get("modelFamily"),
        "metric": "CER" if metric == "characterErrorRate" else "WER",
        "accuracyMetric": metric,
        "accuracyMetricVersion": accuracy_metric_version,
        "accuracyThreshold": MAX_ACCURACY_ERROR_RATE,
        "errorRate": score,
        "wordErrorRate": word["errorRate"],
        "segmentationAwareWordErrorRate": word["segmentationAwareErrorRate"],
        "wordBoundaryOnlyEdits": word["wordBoundaryOnlyEdits"],
        "characterErrorRate": character["errorRate"],
        "word": word,
        "character": character,
        "languagePass": language_pass,
        "accuracyPass": accuracy_pass,
        "passed": language_pass and accuracy_pass,
        "longestDeletionRun": deletion_run,
        "deletionRunWarning": deletion_run >= DELETION_RUN_WARNING_LENGTH,
    }


def primary_deletion_run(
    reference: str, hypothesis: str, expected_language: str, *, version: str = ACCURACY_METRIC_VERSION,
) -> int:
    """The warn-only deletion run of one transcript on its primary metric's units."""
    word, character = recomputed_accuracy(reference, hypothesis, expected_language, version=version)
    primary = (
        character if primary_accuracy_metric(expected_language, version=version) == "characterErrorRate"
        else word
    )
    return int(primary["longestDeletionRun"])


def consensus(family_votes: dict[str, list[bool]]) -> dict[str, Any]:
    """The family rule: one family is one witness, two agreeing families decide.

    Returns `status` pass|fail|inconclusive with typed `reasons`. A family whose
    own repetitions disagree cannot vote; families that disagree with each other
    leave the verdict inconclusive rather than letting either win.
    """
    reasons: list[str] = []
    status = "inconclusive"
    if len(family_votes) < 2:
        reasons.append("independent-full-file-asr-missing")
    elif not all(votes and len(set(votes)) == 1 for votes in family_votes.values()):
        reasons.append("asr-repeatability-disagreement")
    elif all(all(votes) for votes in family_votes.values()):
        status = "pass"
    elif all(not any(votes) for votes in family_votes.values()):
        status = "fail"
        reasons.append("independent-asr-content-failure")
    else:
        reasons.append("independent-asr-disagreement")
    return {"status": status, "families": sorted(family_votes), "reasons": reasons}


# Per-channel consensus (audit #42; decided 2026-09-25 by the audit's
# recommendation). A language verdict has two channels that the families
# observe differently: `language` (Apple Speech's transcript-language
# consistency, whisper's audio language identification; LANGUAGE_CHECK_KINDS)
# and `accuracy` (the edit rate of each family's own transcript). Each channel
# is voted separately through `consensus`, so two families that fail a take for
# different reasons no longer read as agreement, and families that disagree on
# a channel leave that channel inconclusive.
LANGUAGE_CHANNELS = ("language", "accuracy")
CHANNEL_CONSENSUS_ALGORITHM = "per-channel-family-consensus-v1"
CHANNEL_STATUSES = frozenset({"pass", "fail", "inconclusive"})
# The negative control (a pinned hint over a script in another language) is an
# accuracy control: it proves the accuracy channel sees wrong output. It no
# longer claims to prove the language channel, which an English-locked whisper
# passes on the anglicized control take; each family's detected language is
# published beside it (`detectedLanguages`) and its language channel is
# reported only.
NEGATIVE_CONTROL_KIND = "accuracy-control"


def expected_channel_outcomes(expect_failure: bool) -> dict[str, str]:
    """The channels a take's declared outcome constrains, and their expected status."""
    return {"accuracy": "fail"} if expect_failure else {"language": "pass", "accuracy": "pass"}


def single_family_meets_expectation(
    language_pass: bool, accuracy_pass: bool, *, expect_failure: bool,
) -> bool:
    """One witness against the take's declared outcome, channel by channel.

    The accuracy control must fail on accuracy; its language check is reported
    only. A take that must pass needs both channels."""
    if expect_failure:
        return accuracy_pass is False
    return language_pass is True and accuracy_pass is True


def channel_consensus(
    family_channels: dict[str, dict[str, bool]], *, expect_failure: bool,
) -> dict[str, Any]:
    """Vote each channel through the family rule and judge the take's expectation.

    `family_channels` maps a family to its `{"language": bool, "accuracy": bool}`
    verdicts. `outcome` is `met` when every constrained channel reached its
    expected status by consensus, `contradicted` when one reached the opposite
    status, and `inconclusive` otherwise (one family, or disagreement).
    """
    channels: dict[str, dict[str, Any]] = {}
    for channel in LANGUAGE_CHANNELS:
        votes = {
            family: [bool(verdicts[channel])]
            for family, verdicts in sorted(family_channels.items())
        }
        channels[channel] = consensus(votes)
    expected = expected_channel_outcomes(expect_failure)
    statuses = {channel: channels[channel]["status"] for channel in LANGUAGE_CHANNELS}
    if all(statuses[channel] == status for channel, status in expected.items()):
        outcome = "met"
    elif any(statuses[channel] not in {status, "inconclusive"} for channel, status in expected.items()):
        outcome = "contradicted"
    else:
        outcome = "inconclusive"
    return {
        "algorithm": CHANNEL_CONSENSUS_ALGORITHM,
        "families": sorted(family_channels),
        "channels": channels,
        "statuses": statuses,
        "expected": expected,
        "outcome": outcome,
    }


def run_channel_verdicts(takes: list[tuple[dict[str, str], bool]]) -> dict[str, str]:
    """The run's verdict per channel from each take's channel statuses.

    `takes` holds `(statuses, expect_failure)` per scored take. A channel is
    `pass` when every take that constrains it reached its expected status,
    `fail` when one reached the opposite status, and `inconclusive` otherwise
    (or when no take constrains it)."""
    verdicts: dict[str, str] = {}
    for channel in LANGUAGE_CHANNELS:
        observed = [
            (statuses.get(channel), expected_channel_outcomes(expect_failure)[channel])
            for statuses, expect_failure in takes
            if channel in expected_channel_outcomes(expect_failure)
        ]
        if observed and all(status == expected for status, expected in observed):
            verdicts[channel] = "pass"
        elif any(status not in {expected, "inconclusive"} for status, expected in observed):
            verdicts[channel] = "fail"
        else:
            verdicts[channel] = "inconclusive"
    return verdicts
