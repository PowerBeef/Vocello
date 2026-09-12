"""Language-verification metrics shared by every Python consumer.

One tokenizer, one edit distance, one locale table, one threshold set and one
family-consensus rule. `check_language_output.py`, `publish_benchmark_history.py`,
`run_local_delivery_cascade.py` and `independent_asr.py` import from here; the
Swift `GenerationOutputVerifier` keeps its own implementation as the independent
cross-check, and the fixtures in `scripts/tests/test_language_metrics.py` pin the
two to the same contract (diacritic and width folding under `en_US_POSIX`,
alphanumeric token boundaries, stable diagonal → deletion → insertion ties).

Thresholds are facts about the product gate, not tunables: 15 % normalized edit
rate and a 0.5 language-match score. Change them in one place, with the
threshold-change authority described in `docs/reference/audio-qc-engineering.md`.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any
import unicodedata


MAX_ACCURACY_ERROR_RATE = 0.15
MIN_LANGUAGE_MATCH_SCORE = 0.5
ACCURACY_METRIC_VERSION = "normalized-edit-rate-v1"

# The tracked corpus (`config/language-bench-corpus.json`) covers exactly these
# languages; a cell in another language fails closed until the table grows.
LANGUAGE_LOCALE_CODES: dict[str, str] = {
    "english": "en",
    "french": "fr",
    "german": "de",
    "spanish": "es",
    "chinese": "zh",
    "japanese": "ja",
}
# Character error rate is the primary metric where words are not whitespace
# delimited; the same set that keeps dakuten/handakuten distinct while folding.
CHARACTER_ERROR_LANGUAGES = frozenset({"chinese", "japanese"})

# Recognizer families a language verdict may cite. One family is one witness;
# `consensus` needs two independent families for a pass or a fail.
RECOGNITION_FAMILIES = ("apple-speech", "whisper", "sensevoice")
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


def primary_accuracy_metric(expected_language: str) -> str:
    return "characterErrorRate" if expected_language in CHARACTER_ERROR_LANGUAGES else "wordErrorRate"


def normalized_word_tokens(text: str, *, preserve_diacritics: bool = False) -> list[str]:
    """Mirror the Swift tokenizer: fold, lowercase, split on non-alphanumerics."""
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
    an aggregate error rate that does not match its own edits.
    """
    previous: list[tuple[int, int, int]] = [(0, index, 0) for index in range(len(hypothesis) + 1)]
    for left_index, left in enumerate(reference):
        current: list[tuple[int, int, int]] = [(0, 0, left_index + 1)]
        for right_index, right in enumerate(hypothesis):
            substitutions, insertions, deletions = previous[right_index]
            best = (substitutions + (left != right), insertions, deletions)
            substitutions, insertions, deletions = previous[right_index + 1]
            candidate = (substitutions, insertions, deletions + 1)
            if sum(candidate) < sum(best):
                best = candidate
            substitutions, insertions, deletions = current[right_index]
            candidate = (substitutions, insertions + 1, deletions)
            if sum(candidate) < sum(best):
                best = candidate
            current.append(best)
        previous = current
    substitutions, insertions, deletions = previous[-1]
    distance = substitutions + insertions + deletions
    rate = (distance / len(reference)) if reference else (0.0 if not hypothesis else 1.0)
    return {
        "substitutions": substitutions,
        "insertions": insertions,
        "deletions": deletions,
        "referenceCount": len(reference),
        "hypothesisCount": len(hypothesis),
        "errorRate": rate,
    }


def recomputed_accuracy(
    reference: str, hypothesis: str, expected_language: str,
) -> tuple[dict[str, int | float], dict[str, int | float]]:
    """Word and character metrics of one transcript against its script."""
    word = edit_metrics(normalized_word_tokens(reference), normalized_word_tokens(hypothesis))
    preserve = expected_language in CHARACTER_ERROR_LANGUAGES
    reference_characters = "".join(normalized_word_tokens(reference, preserve_diacritics=preserve))
    hypothesis_characters = "".join(normalized_word_tokens(hypothesis, preserve_diacritics=preserve))
    character = edit_metrics(list(reference_characters), list(hypothesis_characters))
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


def score_recognition(recognition: dict[str, Any], *, script: str, language: str) -> dict[str, Any]:
    """Recompute the verdict of one qualified recognition from its transcript."""
    word, character = recomputed_accuracy(script, str(recognition.get("transcript", "")), language)
    metric = primary_accuracy_metric(language)
    score = (character if metric == "characterErrorRate" else word)["errorRate"]
    language_pass = recognition.get("detectedLanguage") == language
    accuracy_pass = score <= MAX_ACCURACY_ERROR_RATE
    return {
        "modelFamily": recognition.get("modelFamily"),
        "metric": "CER" if metric == "characterErrorRate" else "WER",
        "accuracyMetric": metric,
        "accuracyThreshold": MAX_ACCURACY_ERROR_RATE,
        "errorRate": score,
        "wordErrorRate": word["errorRate"],
        "characterErrorRate": character["errorRate"],
        "word": word,
        "character": character,
        "languagePass": language_pass,
        "accuracyPass": accuracy_pass,
        "passed": language_pass and accuracy_pass,
    }


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
