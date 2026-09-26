#!/usr/bin/env python3
"""Offline fixture tests for scripts/check_language_output.py (no device)."""

import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from language_bench_evidence import build_plan, write_json_atomic
from check_language_output import recomputed_accuracy, validate_structured_verification
from lib.language_metrics import primary_accuracy_metric

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CHECK = os.path.join(ROOT, "scripts", "check_language_output.py")
MATRIX = os.path.join(ROOT, "config", "language-bench-matrix.json")
CORPUS = os.path.join(ROOT, "config", "language-bench-corpus.json")

with open(MATRIX, encoding="utf-8") as handle:
    QUICK_CELLS = tuple(
        cell
        for cell in json.load(handle)["cells"]
        if cell.get("quick") and not cell.get("skipOutputVerification")
    )
LOCALES = {
    "english": "en-US",
    "chinese": "zh-CN",
    "german": "de-DE",
    "french": "fr-FR",
    "russian": "ru-RU",
    "portuguese": "pt-BR",
    "spanish": "es-ES",
    "italian": "it-IT",
    "japanese": "ja-JP",
    "korean": "ko-KR",
}


def verification(
    expected_language: str,
    *,
    script: str | None = None,
    transcript_override: str | None = None,
    inconsistent: bool = False,
    missing_metrics: bool = False,
    failing: bool = False,
    accuracy_metric_version: str = "normalized-edit-rate-v1",
) -> dict:
    """A structured verification; `failing` renders the negative control's
    genuine outcome (English-locked recognition of a French take: wrong words,
    accuracy failed, verdict false). Its counts and rates are scored under
    `accuracy_metric_version` (v1 by default: the app evidence published
    before WER v2, which must keep validating)."""
    locale = LOCALES[expected_language]
    if failing and transcript_override is None:
        transcript_override = "the train has quit the guard a lobe"
    if script is None:
        script = (
            "The train left the station at dawn."
            if expected_language == "english"
            else "Le train a quitté la gare à l'aube."
        )
    transcript = transcript_override or script
    word, character = recomputed_accuracy(
        script, transcript, expected_language, version=accuracy_metric_version,
    )
    accuracy_metric = primary_accuracy_metric(expected_language, version=accuracy_metric_version)
    repetitions = []
    for index in (1, 2, 3):
        pass_transcript = transcript
        if inconsistent and index == 3:
            pass_transcript = "Different transcript"
        repetitions.append(
            {
                "passIndex": index,
                "localeIdentifier": locale,
                "authorizationStatus": "authorized",
                "recognizerAvailable": True,
                "supportsOnDeviceRecognition": True,
                "finalResultStatus": "finalResult",
                "recognitionDurationSeconds": 0.25,
                "transcript": pass_transcript,
                "segmentCount": 7,
                "segmentStartSeconds": 0.0,
                "segmentEndSeconds": 1.5,
                "timingCoverageSeconds": 1.5,
                "averageConfidence": 0.9,
                "minimumConfidence": 0.8,
            }
        )
    value = {
        "schemaVersion": 3,
        "algorithmVersion": "language-output-verifier-v3",
        "sourceAudioDurationSeconds": 1.5,
        "expectedLanguage": expected_language,
        "detectedLanguage": expected_language,
        "transcript": transcript,
        "languagePass": True,
        "accuracyPass": not failing,
        "languageMatchScore": 1.0,
        "wordErrorRate": word["errorRate"],
        "characterErrorRate": character["errorRate"],
        "referenceTokenCount": word["referenceCount"],
        "hypothesisTokenCount": word["hypothesisCount"],
        "referenceCharacterCount": character["referenceCount"],
        "hypothesisCharacterCount": character["hypothesisCount"],
        "substitutions": word["substitutions"],
        "insertions": word["insertions"],
        "deletions": word["deletions"],
        "characterSubstitutions": character["substitutions"],
        "characterInsertions": character["insertions"],
        "characterDeletions": character["deletions"],
        "accuracyMetricVersion": accuracy_metric_version,
        "accuracyMetric": accuracy_metric,
        "accuracyThreshold": 0.15,
        "accuracyValue": character["errorRate"] if accuracy_metric == "characterErrorRate" else word["errorRate"],
        "pass": not failing,
        "recognition": {
            "schemaVersion": 2,
            "algorithmVersion": "apple-speech-file-consensus-v2",
            "expectedLanguage": expected_language,
            "selectedLocaleIdentifier": locale,
            "authorizationStatus": "authorized",
            "recognizerAvailable": True,
            "supportsOnDeviceRecognition": True,
            "requiredPassCount": 3,
            "recognitionDurationSeconds": 0.75,
            "repetitions": repetitions,
            "evidenceConsistency": not inconsistent,
            "consensusStatus": "inconsistent" if inconsistent else "consistent",
            "transcript": None if inconsistent else transcript,
        },
    }
    if missing_metrics:
        value.pop("wordErrorRate")
        value.pop("substitutions")
    return value


def write_fixture(
    diag: str,
    run_id: str,
    *,
    mismatch: bool = False,
    inconsistent: bool = False,
    missing_metrics: bool = False,
) -> None:
    with open(CORPUS, encoding="utf-8") as handle:
        scripts = {entry["id"]: entry["script"] for entry in json.load(handle)["languages"]}
    for index, cell in enumerate(QUICK_CELLS):
        cell_id = cell["id"]
        expected_language = cell["expectedHint"]
        directory = os.path.join(diag, cell_id)
        os.makedirs(directory, exist_ok=True)
        if mismatch and index == 0:
            expected_language = "french"
        record = {
            "runID": f"{run_id}--{cell_id}",
            "status": "ok",
            "outputVerification": verification(
                expected_language,
                script=scripts[cell["scriptLang"]],
                inconsistent=inconsistent and index == 0,
                missing_metrics=missing_metrics and index == 0,
                failing=cell.get("expectedOutcome") == "fail",
            ),
        }
        with open(os.path.join(directory, "device-diagnostics-done.json"), "w", encoding="utf-8") as fh:
            json.dump(record, fh)


def write_planned_fixture(diag: str, run_id: str, plan_path: str) -> dict:
    plan = build_plan(
        run_id=run_id,
        matrix_path=Path(MATRIX),
        corpus_path=Path(CORPUS),
        subset="quick",
        cohort_path=None,
    )
    write_json_atomic(Path(plan_path), plan)
    group_digests = {
        "custom-english-v1": "a" * 64,
        "custom-french-v1": "b" * 64,
    }
    with open(CORPUS, encoding="utf-8") as handle:
        scripts = {entry["id"]: entry["script"] for entry in json.load(handle)["languages"]}
    for take in plan["takes"]:
        directory = os.path.join(diag, "runs", take["childRunID"])
        os.makedirs(directory, exist_ok=True)
        expected = take["expectedHint"]
        record = {
            "runID": take["childRunID"],
            "generationID": f"generation-{take['takeIndex']}",
            "mode": take["mode"],
            "variant": take["variant"],
            "status": "ok",
            "seed": take["seed"],
            "samplingVariation": take["samplingVariation"],
            "requestedLanguageHint": take["uiHint"],
            "languageHintSource": "auto" if take["uiHint"] == "auto" else "explicit",
            "promptDigestScope": "resolved",
            "resolvedPromptAssemblyDigest": group_digests.get(
                take.get("promptEquivalenceGroup"), "c" * 64
            ),
        }
        if not take.get("skipOutputVerification"):
            record["outputVerification"] = verification(
                expected, script=scripts[take["scriptLang"]],
                failing=take.get("expectedOutcome") == "fail",
            )
        with open(os.path.join(directory, "device-diagnostics-done.json"), "w", encoding="utf-8") as handle:
            json.dump(record, handle)
    return plan


class CheckLanguageOutputTests(unittest.TestCase):
    def test_negative_control_must_run_and_fail(self) -> None:
        """The pinned-English-over-French cell is evidence only when its
        verification ran and failed; a pass, or a skip, fails the gate."""
        run_id = "fixture-negative-control"
        with tempfile.TemporaryDirectory() as diag:
            plan_path = os.path.join(diag, "plan.json")
            plan = write_planned_fixture(diag, run_id, plan_path)
            control = next(take for take in plan["takes"] if take.get("expectedOutcome") == "fail")
            sentinel = os.path.join(diag, "runs", control["childRunID"], "device-diagnostics-done.json")
            command = [
                sys.executable, CHECK, diag, "--run-id", run_id, "--plan", plan_path,
                "--matrix", MATRIX, "--corpus", CORPUS, "--subset", "quick",
            ]
            baseline = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(baseline.returncode, 0, baseline.stdout + baseline.stderr)
            self.assertIn("expected failure confirmed", baseline.stdout)
            self.assertIn("negativeControls=1", baseline.stdout)

            with open(sentinel, encoding="utf-8") as handle:
                record = json.load(handle)
            with open(CORPUS, encoding="utf-8") as handle:
                scripts = {entry["id"]: entry["script"] for entry in json.load(handle)["languages"]}
            # The control unexpectedly passing (the model obeyed the pinned hint) is a gate failure.
            record["outputVerification"] = verification("english", script=scripts["french"])
            with open(sentinel, "w", encoding="utf-8") as handle:
                json.dump(record, handle)
            passed = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertNotEqual(passed.returncode, 0)
            self.assertIn("negative control", (passed.stdout + passed.stderr).lower())
            # A skipped verification is not a confirmed control either.
            record["outputVerification"] = {"schemaVersion": 3, "skipReason": "source_audio_duration_unavailable", "pass": False}
            with open(sentinel, "w", encoding="utf-8") as handle:
                json.dump(record, handle)
            skipped = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertNotEqual(skipped.returncode, 0)

    def test_wer_v2_does_not_charge_word_boundary_merges(self) -> None:
        """Audit #43: a v2 verification gates the segmentation-aware word rate,
        recomputed here; a v1 verification keeps gating the plain rate."""
        script = "Er kommt vor Mittag an und bleibt bis zum Abend"
        merged = "Er kommt Vormittag an und bleibt biszum Abend"
        v1 = verification("german", script=script, transcript_override=merged)
        v1.update({"accuracyValue": 0.4, "accuracyPass": False, "pass": False})
        self.assertIn(
            "german: structured output verdict is not true",
            validate_structured_verification(v1, "german", script, "german"),
        )
        v2 = dict(v1)
        v2.update({
            "accuracyMetricVersion": "segmentation-aware-edit-rate-v2",
            "accuracyValue": 0.0, "segmentationAwareWordErrorRate": 0.0, "wordBoundaryOnlyEdits": 4,
            "accuracyPass": True, "pass": True,
        })
        self.assertEqual(validate_structured_verification(v2, "german", script, "german"), [])
        self.assertAlmostEqual(v2["wordErrorRate"], 0.4)
        for key, value, message in (
            ("wordBoundaryOnlyEdits", 3, "wordBoundaryOnlyEdits does not match"),
            ("segmentationAwareWordErrorRate", 0.1, "segmentation-aware WER does not match"),
            ("accuracyValue", 0.4, "accuracyValue does not match the primary metric"),
        ):
            tampered = dict(v2, **{key: value})
            with self.subTest(key=key):
                self.assertTrue(any(
                    message in failure
                    for failure in validate_structured_verification(tampered, "german", script, "german")
                ))

    def test_negative_control_is_an_accuracy_control(self) -> None:
        """Audit #42: the control must fail on accuracy; a control that fails
        only its (locked, near-unfalsifiable) language check is not confirmed,
        and one that passes the language check while failing accuracy is."""
        with open(CORPUS, encoding="utf-8") as handle:
            scripts = {entry["id"]: entry["script"] for entry in json.load(handle)["languages"]}
        failing = verification("english", script=scripts["french"], failing=True)
        self.assertTrue(failing["languagePass"])
        self.assertEqual(validate_structured_verification(
            failing, "english", scripts["french"], "control", expect_failure=True,
        ), [])
        language_only = verification("english", script=scripts["french"])
        language_only.update({"languagePass": False, "languageMatchScore": 0.1, "pass": False})
        failures = validate_structured_verification(
            language_only, "english", scripts["french"], "control", expect_failure=True,
        )
        self.assertEqual(failures, ["control: accuracy control did not fail on accuracy"])


    def test_cli_checks_separate_wav_duration_instead_of_trusting_pass(self) -> None:
        with tempfile.TemporaryDirectory() as diag:
            write_fixture(diag, "edge-fixture")
            path = next(Path(diag).rglob("device-diagnostics-done.json"))
            record = json.loads(path.read_text(encoding="utf-8"))
            # The verifier and the separate WAV evidence agree on a 16 s file,
            # but the passes only covered its first 1.5 s.
            record["outputVerification"]["sourceAudioDurationSeconds"] = 16.0
            record["outputEvidence"] = {"durationSeconds": 16.0}
            path.write_text(json.dumps(record), encoding="utf-8")
            result = self.run_checker(diag, "edge-fixture")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("audio-edge-coverage-incomplete", result.stdout + result.stderr)

    def test_separate_wav_evidence_binds_duration_and_cannot_waive_accuracy(self) -> None:
        for declared, observed, issue in (
            (1.5, 1.5, None),
            (1.5, 16.0, "audio-duration-mismatch"),
            (1.5, 0.0, "audio-duration-invalid"),
        ):
            with self.subTest(declared=declared, observed=observed):
                value = verification("french")
                value["sourceAudioDurationSeconds"] = declared
                failures = validate_structured_verification(
                    value, "french", "Le train a quitté la gare à l'aube.", "fixture",
                    output_evidence={"durationSeconds": observed})
                if issue is None:
                    self.assertEqual(failures, [])
                else:
                    self.assertTrue(any(issue in f for f in failures), failures)
        value = verification("french", transcript_override="Bonjour.")
        failures = validate_structured_verification(
            value, "french", "Le train a quitté la gare à l'aube.", "fixture",
            output_evidence={"durationSeconds": 1.5})
        self.assertTrue(failures, "Full edge coverage must never waive word errors")

    def test_schema_three_report_must_bind_its_duration_and_every_pass_timestamp(self) -> None:
        value = verification("french")
        self.assertEqual(validate_structured_verification(
            value, "french", "Le train a quitté la gare à l'aube.", "bound"), [])
        # A schema-3 report that omits the WAV duration would silently bypass the
        # edge-coverage check; the live verifier always binds it, so its absence fails.
        value.pop("sourceAudioDurationSeconds")
        failures = validate_structured_verification(
            value, "french", "Le train a quitté la gare à l'aube.", "missing")
        self.assertTrue(any("audio-duration-missing" in f for f in failures), failures)
        value["sourceAudioDurationSeconds"] = 1.5
        value["recognition"]["repetitions"][1].pop("segmentEndSeconds")
        failures = validate_structured_verification(
            value, "french", "Le train a quitté la gare à l'aube.", "fixture")
        self.assertTrue(any("audio-edge-evidence-missing" in f for f in failures), failures)

    def test_declared_wav_duration_rejects_partial_edge_pass(self) -> None:
        value = verification("french")
        value["sourceAudioDurationSeconds"] = 16.0
        for repetition in value["recognition"]["repetitions"]:
            repetition.update(segmentStartSeconds=8.16, segmentEndSeconds=15.9,
                              timingCoverageSeconds=7.74)
        failures = validate_structured_verification(
            value, "french", "Le train a quitté la gare à l'aube.", "fixture")
        self.assertTrue(any("audio-edge-coverage-incomplete" in f for f in failures), failures)

    def test_invalid_declared_wav_duration_fails_closed(self) -> None:
        for duration in (None, True, 0, -1, float("nan"), float("inf"), "16"):
            with self.subTest(duration=duration):
                value = verification("french")
                value["sourceAudioDurationSeconds"] = duration
                failures = validate_structured_verification(
                    value, "french", "Le train a quitté la gare à l'aube.", "fixture")
                self.assertTrue(any("audio-duration-invalid" in f for f in failures), failures)

    def test_audio_edge_allowance_matches_existing_app_boundaries(self) -> None:
        for duration, start, end, accepted in (
            (1.5, 0.0, 1.5, True),
            (16.0, 2.4, 13.6, True),
            (16.0, 2.40001, 13.6, False),
            (16.0, 0.0, 13.59999, False),
            (16.0, 0.0, 16.25, True),
            (16.0, 0.0, 16.25001, False),
            (100.0, 2.5, 97.5, True),
            (100.0, 2.50001, 97.5, False),
        ):
            with self.subTest(duration=duration, start=start, end=end):
                value = verification("french")
                value["sourceAudioDurationSeconds"] = duration
                for repetition in value["recognition"]["repetitions"]:
                    repetition.update(segmentStartSeconds=start, segmentEndSeconds=end,
                                      timingCoverageSeconds=end - start)
                failures = validate_structured_verification(
                    value, "french", "Le train a quitté la gare à l'aube.", "fixture")
                self.assertEqual(not failures, accepted, failures)

    def run_checker(self, diag: str, run_id: str, plan_path: str | None = None) -> subprocess.CompletedProcess[str]:
        command = [
                sys.executable,
                CHECK,
                diag,
                "--run-id",
                run_id,
                "--matrix",
                MATRIX,
                "--subset",
                "quick",
            ]
        if plan_path:
            command.extend(["--plan", plan_path])
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_quick_subset_passes_fixture(self) -> None:
        run_id = "fixture-output"
        with tempfile.TemporaryDirectory() as diag:
            write_fixture(diag, run_id)
            result = self.run_checker(diag, run_id)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_expected_language_mismatch_fails(self) -> None:
        run_id = "fixture-output-mismatch"
        with tempfile.TemporaryDirectory() as diag:
            write_fixture(diag, run_id, mismatch=True)
            result = self.run_checker(diag, run_id)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("expectedLanguage", result.stdout + result.stderr)

    def test_inconsistent_repeated_asr_fails_conservatively(self) -> None:
        run_id = "fixture-output-inconsistent"
        with tempfile.TemporaryDirectory() as diag:
            write_fixture(diag, run_id, inconsistent=True)
            result = self.run_checker(diag, run_id)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("inconsistent", (result.stdout + result.stderr).lower())

    def test_missing_structured_metrics_fails(self) -> None:
        run_id = "fixture-output-missing-metrics"
        with tempfile.TemporaryDirectory() as diag:
            write_fixture(diag, run_id, missing_metrics=True)
            result = self.run_checker(diag, run_id)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("wordErrorRate", result.stdout + result.stderr)

    def test_duplicate_sentinel_fails_instead_of_overwriting(self) -> None:
        run_id = "fixture-output-duplicate"
        with tempfile.TemporaryDirectory() as diag:
            write_fixture(diag, run_id)
            first_cell_id = QUICK_CELLS[0]["id"]
            source = os.path.join(diag, first_cell_id, "device-diagnostics-done.json")
            duplicate_dir = os.path.join(diag, "duplicate", first_cell_id)
            os.makedirs(duplicate_dir)
            with open(source, encoding="utf-8") as handle:
                record = json.load(handle)
            with open(os.path.join(duplicate_dir, "device-diagnostics-done.json"), "w", encoding="utf-8") as handle:
                json.dump(record, handle)
            result = self.run_checker(diag, run_id)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("duplicate", (result.stdout + result.stderr).lower())

    def test_planned_output_evidence_passes(self) -> None:
        run_id = "fixture-output-plan"
        with tempfile.TemporaryDirectory() as diag:
            plan_path = os.path.join(diag, "plan.json")
            write_planned_fixture(diag, run_id, plan_path)
            result = self.run_checker(diag, run_id, plan_path)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_planned_prompt_equivalence_mismatch_fails(self) -> None:
        run_id = "fixture-output-prompt-mismatch"
        with tempfile.TemporaryDirectory() as diag:
            plan_path = os.path.join(diag, "plan.json")
            plan = write_planned_fixture(diag, run_id, plan_path)
            target = next(take for take in plan["takes"] if take["cellID"] == "custom-fr-auto")
            sentinel = os.path.join(diag, "runs", target["childRunID"], "device-diagnostics-done.json")
            with open(sentinel, encoding="utf-8") as handle:
                record = json.load(handle)
            record["resolvedPromptAssemblyDigest"] = "f" * 64
            with open(sentinel, "w", encoding="utf-8") as handle:
                json.dump(record, handle)
            result = self.run_checker(diag, run_id, plan_path)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("prompt equivalence", (result.stdout + result.stderr).lower())

    def test_planned_requested_language_hint_tamper_fails(self) -> None:
        run_id = "fixture-output-requested-hint"
        with tempfile.TemporaryDirectory() as diag:
            plan_path = os.path.join(diag, "plan.json")
            plan = write_planned_fixture(diag, run_id, plan_path)
            target = next(
                take
                for take in plan["takes"]
                if take["uiHint"] == "auto" and not take.get("skipOutputVerification")
            )
            sentinel = os.path.join(
                diag, "runs", target["childRunID"], "device-diagnostics-done.json"
            )
            with open(sentinel, encoding="utf-8") as handle:
                record = json.load(handle)
            record["requestedLanguageHint"] = target["expectedHint"]
            record["languageHintSource"] = "explicit"
            with open(sentinel, "w", encoding="utf-8") as handle:
                json.dump(record, handle)
            result = self.run_checker(diag, run_id, plan_path)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("requestedLanguageHint", result.stdout + result.stderr)

    def test_tampered_scores_fail_independent_recomputation(self) -> None:
        value = verification("french")
        value["wordErrorRate"] = 0.1
        failures = validate_structured_verification(
            value,
            "french",
            "Le train a quitté la gare à l'aube.",
            "tampered",
        )
        self.assertTrue(any("WER does not match" in failure for failure in failures), failures)

    def test_app_deletion_run_must_match_the_python_mirror(self) -> None:
        """Audit #84: the warn-only run is optional in the app's report, but never wrong."""
        script = "Le train a quitté la gare à l'aube."
        value = verification("french")
        self.assertEqual(validate_structured_verification(value, "french", script, "absent"), [])
        value["longestDeletionRun"] = 0
        self.assertEqual(validate_structured_verification(value, "french", script, "agrees"), [])
        value["longestDeletionRun"] = 3
        self.assertNotEqual(validate_structured_verification(value, "french", script, "tampered"), [])

    def test_language_score_above_one_is_rejected(self) -> None:
        value = verification("chinese", script="火车在黎明时分离开了车站。")
        value["languageMatchScore"] = 1.000_000_000_184_127_2
        failures = validate_structured_verification(
            value,
            "chinese",
            "火车在黎明时分离开了车站。",
            "score",
        )
        self.assertTrue(any("invalid languageMatchScore" in failure for failure in failures), failures)

    def test_recognizer_locale_must_match_expected_language(self) -> None:
        script = "火车在黎明时分离开了车站。"
        value = verification("chinese", script=script)
        value["recognition"]["selectedLocaleIdentifier"] = "fr-FR"
        for repetition in value["recognition"]["repetitions"]:
            repetition["localeIdentifier"] = "fr-FR"
        failures = validate_structured_verification(value, "chinese", script, "locale")
        self.assertTrue(any("locale does not match" in failure for failure in failures), failures)

    def test_success_requires_null_skip_reason_and_trimmed_consensus(self) -> None:
        script = "The train left the station at dawn."
        skipped = verification("english", script=script)
        skipped["skipReason"] = ""
        failures = validate_structured_verification(skipped, "english", script, "skip")
        self.assertTrue(any("skipReason" in failure for failure in failures), failures)

        padded = verification("english", script=script)
        transcript = f" {padded['transcript']} "
        padded["transcript"] = transcript
        padded["recognition"]["transcript"] = transcript
        for repetition in padded["recognition"]["repetitions"]:
            repetition["transcript"] = transcript
        failures = validate_structured_verification(padded, "english", script, "trim")
        self.assertTrue(any("not trimmed" in failure for failure in failures), failures)

    def test_cjk_uses_recomputed_character_error_rate(self) -> None:
        script = "火车在黎明时分离开了车站。"
        # One character differs: WER is 1.0 because the unspaced sentence is one
        # word token, while CER remains below 0.15 and is the locked CJK metric.
        value = verification("chinese", script=script, transcript_override="火車在黎明时分离开了车站。")
        failures = validate_structured_verification(value, "chinese", script, "cjk")
        self.assertEqual(failures, [])
        self.assertEqual(value["accuracyMetric"], "characterErrorRate")
        self.assertEqual(value["wordErrorRate"], 1.0)
        self.assertLess(value["characterErrorRate"], 0.15)

    def test_japanese_dakuten_is_preserved_by_cer(self) -> None:
        # The primary Japanese CER retains the audible dakuten distinction.
        # v1 words folded it away; normalization v2 keeps it in words too.
        word, character = recomputed_accuracy(
            "かきくけこ", "がきくけこ", "japanese", version="normalized-edit-rate-v1",
        )
        self.assertEqual((word["errorRate"], character["errorRate"]), (0.0, 0.2))
        word, character = recomputed_accuracy("かきくけこ", "がきくけこ", "japanese")
        self.assertEqual((word["errorRate"], character["errorRate"]), (1.0, 0.2))

    def test_normalization_v2_verification_is_recomputed_under_its_own_version(self) -> None:
        """AQ-02: a v3 verification is rescored under normalization v2, so a
        French elision the app heard split and Korean eojeol spacing cost
        nothing, and Korean gates its syllable rate."""
        v3 = "normalization-v2-edit-rate-v3"
        script = "L'homme arrive à l'heure aujourd'hui avec le train du matin."
        split = "l homme arrive a l'heure aujourd'hui avec le train du matin"
        french = verification("french", script=script, transcript_override=split, accuracy_metric_version=v3)
        french.update({"segmentationAwareWordErrorRate": 0.0, "wordBoundaryOnlyEdits": 2, "accuracyValue": 0.0})
        self.assertEqual(validate_structured_verification(french, "french", script, "fr"), [])
        korean_script = "기차는 조용한 역을 제시간에 떠났습니다"
        korean = verification(
            "korean", script=korean_script, transcript_override="기차는 조용한역을 제 시간에 떠났습니다",
            accuracy_metric_version=v3,
        )
        korean.update({"segmentationAwareWordErrorRate": 0.0, "wordBoundaryOnlyEdits": 3})
        self.assertEqual(korean["accuracyMetric"], "characterErrorRate")
        self.assertEqual((korean["referenceCharacterCount"], korean["accuracyValue"]), (17, 0.0))
        self.assertEqual(validate_structured_verification(korean, "korean", korean_script, "ko"), [])
        # The same app evidence declared under v2 is rescored under v1
        # tokens and a word gate, and no longer matches.
        failures = validate_structured_verification(
            dict(korean, accuracyMetricVersion="segmentation-aware-edit-rate-v2"), "korean", korean_script, "ko",
        )
        self.assertTrue(any("wrong primary accuracy metric" in failure for failure in failures), failures)


if __name__ == "__main__":
    unittest.main()
