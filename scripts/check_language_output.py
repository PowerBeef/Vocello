#!/usr/bin/env python3
"""Gate language-bench output verification (Phase 3 — in-app Speech round-trip).

Reads device-diagnostics sentinels stamped with `outputVerification` and checks:
  - three consistent, locale-locked recognitions of the exact immutable WAV;
  - structured verification metrics present and pass=true;
  - expectedLanguage matches matrix expectedHint;
  - no skipReason (Speech permission must be granted on device once).

Usage:
  scripts/check_language_output.py <diagnostics-dir> \\
      --run-id ios-lang-bench-20260706-110143 \\
      --matrix config/language-bench-matrix.json \\
      [--subset quick|full]
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import sys
from typing import Any
import unicodedata

sys.path.insert(0, os.path.dirname(__file__))
from check_language_hints import load_json, select_cells
from language_bench_evidence import (
    expected_language_hint_source,
    exact_sentinels,
    load_json as load_evidence_json,
    validate_plan_against_sources,
)


MAX_ACCURACY_ERROR_RATE = 0.15
MIN_LANGUAGE_MATCH_SCORE = 0.5
LANGUAGE_LOCALE_CODES = {
    "english": "en",
    "chinese": "zh",
    "german": "de",
    "french": "fr",
    "russian": "ru",
    "portuguese": "pt",
    "spanish": "es",
    "italian": "it",
    "japanese": "ja",
    "korean": "ko",
}


def find_sentinels(diag: str, run_id: str) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for root, _dirs, files in os.walk(diag):
        if "device-diagnostics-done.json" not in files:
            continue
        path = os.path.join(root, "device-diagnostics-done.json")
        try:
            with open(path, encoding="utf-8") as handle:
                record = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        if record.get("runID", "").startswith(f"{run_id}--"):
            cell_id = record["runID"][len(run_id) + 2 :]
            out.setdefault(cell_id, []).append(record)
    return out


def finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def locale_matches_expected_language(identifier: str, expected_language: str) -> bool:
    expected_code = LANGUAGE_LOCALE_CODES.get(expected_language)
    if expected_code is None:
        return False
    base_code = re.split(r"[-_]", identifier, maxsplit=1)[0].lower()
    return base_code == expected_code


def normalized_word_tokens(text: str, *, preserve_diacritics: bool = False) -> list[str]:
    # Swift uses diacritic+width folding with en_US_POSIX, lowercase, then
    # Unicode CharacterSet.alphanumerics boundaries. NFKD + mark removal and
    # Unicode isalnum reproduce that contract for this tracked corpus.
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


def edit_metrics(reference: list[str], hypothesis: list[str]) -> dict[str, int | float]:
    # Match the Swift stable tie policy: diagonal/substitution, then deletion,
    # then insertion. Retaining operation counts prevents a forged aggregate WER.
    previous = [
        {"substitutions": 0, "insertions": index, "deletions": 0}
        for index in range(len(hypothesis) + 1)
    ]
    for left_index, left in enumerate(reference):
        current = [{"substitutions": 0, "insertions": 0, "deletions": left_index + 1}]
        for right_index, right in enumerate(hypothesis):
            diagonal = dict(previous[right_index])
            if left != right:
                diagonal["substitutions"] += 1
            deletion = dict(previous[right_index + 1])
            deletion["deletions"] += 1
            insertion = dict(current[right_index])
            insertion["insertions"] += 1

            def distance(value: dict[str, int]) -> int:
                return value["substitutions"] + value["insertions"] + value["deletions"]

            best = diagonal
            if distance(deletion) < distance(best):
                best = deletion
            if distance(insertion) < distance(best):
                best = insertion
            current.append(best)
        previous = current
    final = previous[-1]
    distance = final["substitutions"] + final["insertions"] + final["deletions"]
    rate = (distance / len(reference)) if reference else (0.0 if not hypothesis else 1.0)
    return {
        **final,
        "referenceCount": len(reference),
        "hypothesisCount": len(hypothesis),
        "errorRate": rate,
    }


def recomputed_accuracy(
    reference: str, hypothesis: str, expected_language: str
) -> tuple[dict[str, int | float], dict[str, int | float]]:
    reference_words = normalized_word_tokens(reference)
    hypothesis_words = normalized_word_tokens(hypothesis)
    word = edit_metrics(reference_words, hypothesis_words)
    preserve_diacritics = expected_language in {"chinese", "japanese"}
    reference_characters = "".join(
        normalized_word_tokens(reference, preserve_diacritics=preserve_diacritics)
    )
    hypothesis_characters = "".join(
        normalized_word_tokens(hypothesis, preserve_diacritics=preserve_diacritics)
    )
    character = edit_metrics(list(reference_characters), list(hypothesis_characters))
    return word, character


def audio_edge_evidence_issues(
    verification: dict[str, Any], *, output_evidence: Any = None,
) -> list[str]:
    """Mirror VoiceClipTranscriber's existing edge rule, not speech coverage.

    Legacy reports without either duration retain their historical validation.
    A supplied duration may never be ignored, including null/nonfinite values.
    When available, bind the declared duration to the separate WAV evidence.
    This check cannot establish interior completeness or waive WER/CER.
    """
    duration = None
    if "sourceAudioDurationSeconds" in verification:
        duration = finite_number(verification["sourceAudioDurationSeconds"])
        if duration is None or duration <= 0:
            return ["output-audio-duration-invalid"]
    if output_evidence is not None:
        observed = finite_number(output_evidence.get("durationSeconds")) if isinstance(output_evidence, dict) else None
        if observed is None or observed <= 0:
            return ["output-audio-duration-invalid"]
        if duration is not None and not math.isclose(duration, observed, rel_tol=1e-9, abs_tol=1e-6):
            return ["output-audio-duration-mismatch"]
        duration = observed
    if duration is None:
        return []
    recognition = verification.get("recognition")
    repetitions = recognition.get("repetitions") if isinstance(recognition, dict) else None
    if not isinstance(repetitions, list) or len(repetitions) != 3:
        return ["output-audio-edge-evidence-missing"]
    # Same min/max/proportion and end tolerance as the shipping Swift policy.
    allowance = min(2.5, max(1.0, duration * 0.15))
    for repetition in repetitions:
        if not isinstance(repetition, dict):
            return ["output-audio-edge-evidence-missing"]
        start = finite_number(repetition.get("segmentStartSeconds"))
        end = finite_number(repetition.get("segmentEndSeconds"))
        if start is None or end is None or start < 0 or end <= start:
            return ["output-audio-edge-evidence-missing"]
        if start > allowance or end < max(0, duration - allowance) or end > duration + 0.25:
            return ["output-audio-edge-coverage-incomplete"]
    return []


def validate_structured_verification(
    verification: dict[str, Any], expected_language: str, expected_script: str, identity: str,
    *, output_evidence: Any = None,
) -> list[str]:
    failures: list[str] = []
    failures.extend(f"{identity}: {issue}" for issue in audio_edge_evidence_issues(
        verification, output_evidence=output_evidence))
    schema = verification.get("schemaVersion")
    if schema != 3:
        failures.append(f"{identity}: outputVerification schemaVersion must be 3")
    algorithm = verification.get("algorithmVersion")
    if algorithm != "language-output-verifier-v3":
        failures.append(f"{identity}: unexpected output verification algorithmVersion")
    if verification.get("expectedLanguage") != expected_language:
        failures.append(
            f"{identity}: expectedLanguage {verification.get('expectedLanguage')!r} "
            f"!= matrix {expected_language!r}"
        )
    if verification.get("skipReason") is not None:
        failures.append(f"{identity}: output verification contains a skipReason")

    recognition = verification.get("recognition")
    if not isinstance(recognition, dict):
        failures.append(f"{identity}: missing structured recognition evidence")
        return failures
    if recognition.get("schemaVersion") != 2:
        failures.append(f"{identity}: recognition schemaVersion must be 2")
    if recognition.get("algorithmVersion") != "apple-speech-file-consensus-v2":
        failures.append(f"{identity}: unexpected recognition algorithmVersion")
    if recognition.get("expectedLanguage") != expected_language:
        failures.append(f"{identity}: recognizer expectedLanguage mismatch")
    locale = recognition.get("selectedLocaleIdentifier")
    if (
        not isinstance(locale, str)
        or not locale
        or locale != locale.strip()
        or locale.lower() == "auto"
    ):
        failures.append(f"{identity}: missing exact recognizer locale")
    elif not locale_matches_expected_language(locale, expected_language):
        failures.append(f"{identity}: recognizer locale does not match expectedLanguage")
    if recognition.get("authorizationStatus") != "authorized":
        failures.append(f"{identity}: Speech authorization is not authorized")
    if recognition.get("recognizerAvailable") is not True:
        failures.append(f"{identity}: recognizer was unavailable")
    if recognition.get("supportsOnDeviceRecognition") is not True:
        failures.append(f"{identity}: recognizer lacks on-device support")
    total_duration = finite_number(recognition.get("recognitionDurationSeconds"))
    if total_duration is None or total_duration <= 0:
        failures.append(f"{identity}: invalid total recognition duration")
    required_passes = recognition.get("requiredPassCount")
    repetitions = recognition.get("repetitions")
    if required_passes != 3:
        failures.append(f"{identity}: recognition must predeclare exactly 3 passes")
    if not isinstance(repetitions, list) or len(repetitions) != 3:
        failures.append(f"{identity}: expected exactly 3 recognition repetitions")
        repetitions = []
    indexes: list[int] = []
    transcripts: list[str] = []
    repetition_durations: list[float] = []
    for position, repetition in enumerate(repetitions):
        if not isinstance(repetition, dict):
            failures.append(f"{identity}: recognition repetition {position} is malformed")
            continue
        index = repetition.get("passIndex")
        if nonnegative_int(index) is None:
            failures.append(f"{identity}: recognition repetition {position} lacks an index")
        else:
            indexes.append(index)
        if repetition.get("localeIdentifier") != locale:
            failures.append(
                f"{identity}: recognition repetition {position} locale differs from the pinned locale"
            )
        if repetition.get("authorizationStatus") != "authorized":
            failures.append(f"{identity}: recognition repetition {position} was unauthorized")
        if repetition.get("recognizerAvailable") is not True:
            failures.append(f"{identity}: recognition repetition {position} recognizer was unavailable")
        if repetition.get("supportsOnDeviceRecognition") is not True:
            failures.append(f"{identity}: recognition repetition {position} was not on-device")
        if repetition.get("finalResultStatus") != "finalResult":
            failures.append(
                f"{identity}: recognition repetition {position} "
                f"status={repetition.get('finalResultStatus')!r}"
            )
        transcript = repetition.get("transcript")
        if not isinstance(transcript, str) or not transcript.strip():
            failures.append(f"{identity}: recognition repetition {position} lacks a transcript")
        elif transcript != transcript.strip():
            failures.append(f"{identity}: recognition repetition {position} transcript is not trimmed")
        else:
            transcripts.append(transcript)
        duration = finite_number(repetition.get("recognitionDurationSeconds"))
        if duration is None or duration <= 0:
            failures.append(f"{identity}: recognition repetition {position} has invalid duration")
        else:
            repetition_durations.append(duration)
        segment_count = nonnegative_int(repetition.get("segmentCount"))
        if segment_count is None or segment_count <= 0:
            failures.append(f"{identity}: recognition repetition {position} lacks segments")
        coverage = finite_number(repetition.get("timingCoverageSeconds"))
        if coverage is None or coverage <= 0:
            failures.append(f"{identity}: recognition repetition {position} has invalid timing coverage")
        start = finite_number(repetition.get("segmentStartSeconds"))
        end = finite_number(repetition.get("segmentEndSeconds"))
        if start is None or end is None or start < 0 or end <= start:
            failures.append(f"{identity}: recognition repetition {position} has invalid segment bounds")
        elif coverage is not None and not math.isclose(
            coverage, end - start, rel_tol=1e-9, abs_tol=1e-9
        ):
            failures.append(f"{identity}: recognition repetition {position} timing coverage is inconsistent")
        confidences: dict[str, float] = {}
        for key in ("averageConfidence", "minimumConfidence"):
            confidence = finite_number(repetition.get(key))
            if confidence is None or not 0 <= confidence <= 1:
                failures.append(f"{identity}: recognition repetition {position} has invalid {key}")
            else:
                confidences[key] = confidence
        if (
            "minimumConfidence" in confidences
            and "averageConfidence" in confidences
            and confidences["minimumConfidence"] > confidences["averageConfidence"]
        ):
            failures.append(f"{identity}: recognition repetition {position} confidence bounds are inconsistent")
        if repetition.get("errorDomain") is not None or repetition.get("errorCode") is not None:
            failures.append(f"{identity}: successful recognition repetition contains an error")
    if indexes and indexes != [1, 2, 3]:
        failures.append(f"{identity}: recognition repetition indexes are not ordered 1,2,3")
    if recognition.get("evidenceConsistency") is not True:
        failures.append(f"{identity}: repeated recognition evidence is inconsistent")
    if recognition.get("consensusStatus") != "consistent":
        failures.append(f"{identity}: recognition consensus is not consistent")
    if total_duration is not None and len(repetition_durations) == 3 and not math.isclose(
        total_duration, sum(repetition_durations), rel_tol=1e-9, abs_tol=1e-9
    ):
        failures.append(f"{identity}: total recognition duration does not match its repetitions")
    consensus = recognition.get("transcript")
    if not isinstance(consensus, str) or not consensus.strip():
        failures.append(f"{identity}: recognition consensus transcript is missing")
    elif consensus != consensus.strip():
        failures.append(f"{identity}: recognition consensus transcript is not trimmed")
    if transcripts and (len(set(transcripts)) != 1 or consensus != transcripts[0]):
        failures.append(f"{identity}: recognition transcripts do not exactly agree")
    if verification.get("transcript") != consensus:
        failures.append(f"{identity}: scored transcript differs from recognition consensus")

    recomputed_word: dict[str, int | float] | None = None
    recomputed_character: dict[str, int | float] | None = None
    if isinstance(consensus, str) and consensus.strip():
        recomputed_word, recomputed_character = recomputed_accuracy(
            expected_script, consensus, expected_language
        )

    for key in (
        "referenceTokenCount",
        "hypothesisTokenCount",
        "referenceCharacterCount",
        "hypothesisCharacterCount",
        "substitutions",
        "insertions",
        "deletions",
        "characterSubstitutions",
        "characterInsertions",
        "characterDeletions",
    ):
        if nonnegative_int(verification.get(key)) is None:
            failures.append(f"{identity}: missing nonnegative {key}")
    wer = finite_number(verification.get("wordErrorRate"))
    cer = finite_number(verification.get("characterErrorRate"))
    if wer is None or wer < 0:
        failures.append(f"{identity}: missing finite wordErrorRate")
    if cer is None or cer < 0:
        failures.append(f"{identity}: missing finite characterErrorRate")
    if verification.get("accuracyPass") not in (True, False):
        failures.append(f"{identity}: accuracyPass is absent or non-boolean")
    language_score = finite_number(verification.get("languageMatchScore"))
    if language_score is None or not 0 <= language_score <= 1:
        failures.append(f"{identity}: invalid languageMatchScore")
    if verification.get("languagePass") is not True or (
        language_score is not None and language_score < MIN_LANGUAGE_MATCH_SCORE
    ):
        failures.append(f"{identity}: structured language verdict does not pass its threshold")
    if verification.get("pass") is not True:
        failures.append(f"{identity}: structured output verdict is not true")
    if recomputed_word is not None and recomputed_character is not None:
        expected_counts = {
            "referenceTokenCount": recomputed_word["referenceCount"],
            "hypothesisTokenCount": recomputed_word["hypothesisCount"],
            "referenceCharacterCount": recomputed_character["referenceCount"],
            "hypothesisCharacterCount": recomputed_character["hypothesisCount"],
            "substitutions": recomputed_word["substitutions"],
            "insertions": recomputed_word["insertions"],
            "deletions": recomputed_word["deletions"],
            "characterSubstitutions": recomputed_character["substitutions"],
            "characterInsertions": recomputed_character["insertions"],
            "characterDeletions": recomputed_character["deletions"],
        }
        for key, expected_value in expected_counts.items():
            if verification.get(key) != expected_value:
                failures.append(f"{identity}: {key} does not match the consensus transcript")
        if wer is None or not math.isclose(wer, float(recomputed_word["errorRate"]), rel_tol=1e-9, abs_tol=1e-12):
            failures.append(f"{identity}: WER does not match the consensus transcript")
        if cer is None or not math.isclose(cer, float(recomputed_character["errorRate"]), rel_tol=1e-9, abs_tol=1e-12):
            failures.append(f"{identity}: CER does not match the consensus transcript")

        expected_metric = (
            "characterErrorRate" if expected_language in {"chinese", "japanese"}
            else "wordErrorRate"
        )
        expected_score = cer if expected_metric == "characterErrorRate" else wer
        if verification.get("accuracyMetricVersion") != "normalized-edit-rate-v1":
            failures.append(f"{identity}: wrong accuracy metric version")
        if verification.get("accuracyMetric") != expected_metric:
            failures.append(f"{identity}: wrong primary accuracy metric")
        threshold = finite_number(verification.get("accuracyThreshold"))
        if threshold is None or not math.isclose(threshold, MAX_ACCURACY_ERROR_RATE, abs_tol=1e-12):
            failures.append(f"{identity}: wrong primary accuracy threshold")
        recomputed_pass = expected_score is not None and expected_score <= MAX_ACCURACY_ERROR_RATE
        accuracy_value = finite_number(verification.get("accuracyValue"))
        if expected_score is None or accuracy_value is None or not math.isclose(
            accuracy_value, expected_score, rel_tol=1e-9, abs_tol=1e-12
        ):
            failures.append(f"{identity}: accuracyValue does not match the primary metric")
        if verification.get("accuracyPass") is not recomputed_pass:
            failures.append(f"{identity}: accuracyPass contradicts the recomputed primary metric")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Gate language-bench output verification")
    parser.add_argument("diag", help="diagnostics dir (pulled app container mirror)")
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--matrix",
        default=os.path.join(os.path.dirname(__file__), "..", "config", "language-bench-matrix.json"),
    )
    parser.add_argument(
        "--corpus",
        default=os.path.join(os.path.dirname(__file__), "..", "config", "language-bench-corpus.json"),
    )
    parser.add_argument("--subset", choices=("quick", "full"), default="full")
    parser.add_argument(
        "--plan",
        help="immutable language-run plan; enables generation/seed-level correlation",
    )
    parser.add_argument("--cohort", help="tracked diagnostic-cohort config used to create the plan")
    args = parser.parse_args()

    matrix = load_json(args.matrix)
    corpus = load_json(args.corpus)
    corpus_by_id = {
        entry.get("id"): entry.get("script")
        for entry in (corpus.get("languages") or [])
        if isinstance(entry, dict) and isinstance(entry.get("id"), str)
        and isinstance(entry.get("script"), str)
    }
    cells = select_cells(matrix, args.subset)
    legacy_sentinels = find_sentinels(args.diag, args.run_id) if not args.plan else {}
    planned_takes: list[dict[str, Any]] | None = None
    exact: dict[str, tuple[Path, dict[str, Any]]] = {}
    plan_failure: str | None = None
    if args.plan:
        try:
            plan = load_evidence_json(Path(args.plan))
            planned_takes = validate_plan_against_sources(
                plan,
                matrix_path=Path(args.matrix),
                corpus_path=Path(args.corpus),
                subset=args.subset,
                cohort_path=Path(args.cohort) if args.cohort else None,
            )
            if plan.get("runID") != args.run_id:
                raise ValueError("run plan belongs to another run ID")
            exact = exact_sentinels(Path(args.diag), plan)
        except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
            planned_takes = []
            plan_failure = str(error)
    expected = planned_takes if planned_takes is not None else cells
    output_cells = [c for c in expected if not c.get("skipOutputVerification")]

    failures: list[str] = []
    print(
        f"language-output gate: runID={args.run_id} subset={args.subset} "
        f"expected={len(output_cells)} sentinels={len(exact) if args.plan else sum(map(len, legacy_sentinels.values()))}"
    )

    if plan_failure:
        failures.append(f"invalid run plan/evidence: {plan_failure}")

    equivalence: dict[tuple[str, int | None], list[tuple[str, str]]] = {}
    for cell in expected:
        cell_id = cell.get("cellID", cell.get("id"))
        identity = cell.get("childRunID", cell_id)
        expected_hint = cell["expectedHint"]
        expected_script = corpus_by_id.get(cell.get("scriptLang"))
        if not isinstance(expected_script, str):
            failures.append(f"{identity}: corpus lacks scriptLang {cell.get('scriptLang')!r}")
            continue
        if cell.get("skipOutputVerification"):
            print(f"  {cell_id:<28} (output skipped — hint-only cell)")
            continue
        if planned_takes is not None:
            pair = exact.get(identity)
            record = pair[1] if pair else None
        else:
            matched = legacy_sentinels.get(cell_id, [])
            if len(matched) > 1:
                failures.append(f"{cell_id}: duplicate device-diagnostics sentinels")
            record = matched[0] if len(matched) == 1 else None
        if record is None:
            failures.append(f"{identity}: missing device-diagnostics sentinel")
            continue
        if record.get("status") != "ok":
            failures.append(f"{identity}: device-diagnostics status={record.get('status')!r}")
            continue
        if planned_takes is not None:
            if record.get("generationID") is None:
                failures.append(f"{identity}: missing generationID")
            if record.get("seed") != cell.get("seed"):
                failures.append(f"{identity}: sentinel seed does not match the run plan")
            if record.get("samplingVariation") != cell.get("samplingVariation"):
                failures.append(f"{identity}: sentinel sampling variation does not match the run plan")
            requested_hint = cell.get("uiHint", "auto")
            if record.get("requestedLanguageHint") != requested_hint:
                failures.append(f"{identity}: requestedLanguageHint does not match the run plan")
            if record.get("languageHintSource") != expected_language_hint_source(requested_hint):
                failures.append(f"{identity}: languageHintSource does not match the run plan")
            group = cell.get("promptEquivalenceGroup")
            if isinstance(group, str) and group:
                prompt_digest = record.get("resolvedPromptAssemblyDigest")
                if record.get("promptDigestScope") != "resolved":
                    failures.append(f"{identity}: promptDigestScope must be 'resolved'")
                if not isinstance(prompt_digest, str) or len(prompt_digest) != 64:
                    failures.append(f"{identity}: missing resolved prompt-assembly digest")
                else:
                    equivalence.setdefault((group, cell.get("seed")), []).append(
                        (identity, prompt_digest)
                    )
        verification = record.get("outputVerification")
        if not isinstance(verification, dict):
            failures.append(
                f"{identity}: missing outputVerification "
                "(set QVOICE_IOS_DEVICE_DIAGNOSTICS_VERIFY_OUTPUT=1)"
            )
            continue
        failures.extend(
            validate_structured_verification(
                verification, expected_hint, expected_script, identity,
                output_evidence=record.get("outputEvidence"),
            )
        )
        if not verification.get("languagePass"):
            failures.append(
                f"{identity}: languagePass=false score={verification.get('languageMatchScore')}"
            )
        if verification.get("accuracyPass") is not True:
            failures.append(
                f"{identity}: accuracyPass={verification.get('accuracyPass')!r} "
                f"{verification.get('accuracyMetric')}={verification.get('accuracyValue')}"
            )
        passed = verification.get("pass")
        if passed is None:
            passed = (
                verification.get("languagePass")
                and verification.get("accuracyPass")
                and not verification.get("skipReason")
            )
        if not passed:
            failures.append(f"{identity}: pass=false")
        print(
            f"  {cell_id:<28} lang={verification.get('languagePass')} "
            f"locale={(verification.get('recognition') or {}).get('selectedLocaleIdentifier')} "
            f"accuracy={verification.get('accuracyMetric')}:{verification.get('accuracyValue')} "
            f"score={verification.get('languageMatchScore')} "
            f"pass={passed}"
        )

    for (group, seed), members in sorted(equivalence.items()):
        if len(members) < 2:
            failures.append(f"prompt equivalence group {group} seed {seed} has fewer than two takes")
            continue
        if len({digest for _identity, digest in members}) != 1:
            failures.append(
                f"prompt equivalence group {group} seed {seed} differs across "
                + ", ".join(identity for identity, _digest in members)
            )

    if failures:
        print("FAIL:")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
