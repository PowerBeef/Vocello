"""Language-verification metrics shared by every Python consumer.

One tokenizer, one edit distance, one locale table, one threshold set and one
family-consensus rule, applied per verdict channel. `check_language_output.py`, `publish_benchmark_history.py`,
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
# WER v2 (audit #43; decided 2026-09-25 by the audit's recommendation): the
# word gate reads the segmentation-aware rate, which does not charge a
# recognizer's word-boundary choice ("vor Mittag" heard as "Vormittag") as
# errors. The v1 rate stays published beside it; the character rate (Chinese
# and Japanese) has no word boundaries and is the same under both versions.
LEGACY_ACCURACY_METRIC_VERSION = "normalized-edit-rate-v1"
ACCURACY_METRIC_VERSION = "segmentation-aware-edit-rate-v2"
ACCURACY_METRIC_VERSIONS = (LEGACY_ACCURACY_METRIC_VERSION, ACCURACY_METRIC_VERSION)
# The longest run of tokens on either side of one merge or split that v2
# credits (a four-word compound and its spaced spelling). Swift mirrors it as
# `VoiceClipTranscriber.wordBoundarySpanLimit`.
WORD_BOUNDARY_SPAN_LIMIT = 4
# Warn-only (audit #84): the longest run of consecutive reference units the
# recognizer deleted, on the primary metric's units. A skipped phrase of two to
# four words stays under the 15 % gate on 17-32-unit scripts; the run exposes
# it. It never changes a verdict or the accuracy metric above.
DELETION_RUN_WARNING_LENGTH = 2

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


def primary_accuracy_metric(expected_language: str) -> str:
    return "characterErrorRate" if expected_language in CHARACTER_ERROR_LANGUAGES else "wordErrorRate"


def primary_accuracy_score(
    word: dict[str, Any], character: dict[str, Any], expected_language: str,
    *, version: str = ACCURACY_METRIC_VERSION,
) -> float:
    """The gated score under one accuracy metric version.

    v1 gates the plain word or character rate; v2 gates the segmentation-aware
    word rate (characters are unchanged). An unknown version fails closed."""
    if version not in ACCURACY_METRIC_VERSIONS:
        raise ValueError(f"unknown accuracy metric version {version!r}")
    if primary_accuracy_metric(expected_language) == "characterErrorRate":
        return float(character["errorRate"])
    if version == ACCURACY_METRIC_VERSION:
        return float(word["segmentationAwareErrorRate"])
    return float(word["errorRate"])


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
) -> tuple[dict[str, int | float], dict[str, int | float]]:
    """Word and character metrics of one transcript against its script.

    The word metrics also carry the WER v2 decomposition
    (`segmentationAwareErrorRate`, `wordBoundaryOnlyEdits`)."""
    reference_words = normalized_word_tokens(reference)
    hypothesis_words = normalized_word_tokens(hypothesis)
    word = edit_metrics(reference_words, hypothesis_words)
    word.update(segmentation_aware_metrics(reference_words, hypothesis_words))
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


def score_recognition(
    recognition: dict[str, Any], *, script: str, language: str,
    accuracy_metric_version: str = ACCURACY_METRIC_VERSION,
) -> dict[str, Any]:
    """Recompute the verdict of one qualified recognition from its transcript."""
    word, character = recomputed_accuracy(script, str(recognition.get("transcript", "")), language)
    metric = primary_accuracy_metric(language)
    score = primary_accuracy_score(word, character, language, version=accuracy_metric_version)
    language_pass = recognition.get("detectedLanguage") == language
    accuracy_pass = score <= MAX_ACCURACY_ERROR_RATE
    deletion_run = (character if metric == "characterErrorRate" else word)["longestDeletionRun"]
    return {
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


def primary_deletion_run(reference: str, hypothesis: str, expected_language: str) -> int:
    """The warn-only deletion run of one transcript on its primary metric's units."""
    word, character = recomputed_accuracy(reference, hypothesis, expected_language)
    primary = character if primary_accuracy_metric(expected_language) == "characterErrorRate" else word
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
