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

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from language_bench_evidence import build_plan, write_json_atomic
from check_language_output import (
    CHINESE_SCRIPT_CONVERTER, ChineseScriptDiagnosticError, chinese_script_diagnostic,
    _pinned_chinese_script_transform, recomputed_accuracy, validate_structured_verification,
)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
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
) -> dict:
    locale = LOCALES[expected_language]
    if script is None:
        script = (
            "The train left the station at dawn."
            if expected_language == "english"
            else "Le train a quitté la gare à l'aube."
        )
    transcript = transcript_override or script
    word, character = recomputed_accuracy(script, transcript, expected_language)
    accuracy_metric = (
        "characterErrorRate" if expected_language in {"chinese", "japanese"}
        else "wordErrorRate"
    )
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
        "expectedLanguage": expected_language,
        "detectedLanguage": expected_language,
        "transcript": transcript,
        "languagePass": True,
        "accuracyPass": True,
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
        "accuracyMetricVersion": "normalized-edit-rate-v1",
        "accuracyMetric": accuracy_metric,
        "accuracyThreshold": 0.15,
        "accuracyValue": character["errorRate"] if accuracy_metric == "characterErrorRate" else word["errorRate"],
        "pass": True,
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
                expected, script=scripts[take["scriptLang"]]
            )
        with open(os.path.join(directory, "device-diagnostics-done.json"), "w", encoding="utf-8") as handle:
            json.dump(record, handle)
    return plan


class CheckLanguageOutputTests(unittest.TestCase):
    def test_cli_checks_separate_wav_duration_instead_of_trusting_pass(self) -> None:
        with tempfile.TemporaryDirectory() as diag:
            write_fixture(diag, "edge-fixture")
            path = next(Path(diag).rglob("device-diagnostics-done.json"))
            record = json.loads(path.read_text(encoding="utf-8"))
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

    def test_duration_requires_all_pass_timestamps_but_legacy_remains_valid(self) -> None:
        value = verification("french")
        self.assertEqual(validate_structured_verification(
            value, "french", "Le train a quitté la gare à l'aube.", "legacy"), [])
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
        word, character = recomputed_accuracy("かきくけこ", "がきくけこ", "japanese")
        # Compatibility WER folds diacritics, but the primary Japanese CER
        # must retain the audible dakuten distinction.
        self.assertEqual(word["errorRate"], 0.0)
        self.assertEqual(character["errorRate"], 0.2)


class ChineseScriptDiagnosticTests(unittest.TestCase):
    # Deliberately small deterministic fixture, NOT a replacement normalization
    # table. Real conversion is optional, digest-pinned and checked separately.
    @staticmethod
    def transform(texts, _root):
        table = str.maketrans({"車": "车", "開": "开", "國": "国", "語": "语", "後": "后"})
        return tuple(text.translate(table) for text in texts)

    def diagnose(self, reference, hypothesis, language="chinese"):
        with patch("check_language_output._pinned_chinese_script_transform", side_effect=self.transform):
            return chinese_script_diagnostic(reference, hypothesis, language,
                                             audio_sha256="a" * 64, icu_root=Path("unused"))

    def test_script_equivalence_is_supplemental_and_raw_metric_is_unchanged(self):
        result = self.diagnose("中国车开", "中國車開")
        self.assertEqual(result["rawCharacterMetrics"], recomputed_accuracy("中国车开", "中國車開", "chinese")[1])
        self.assertEqual(result["rawCharacterMetrics"]["errorRate"], .75)
        self.assertEqual(result["scriptCanonicalCharacterMetrics"]["errorRate"], 0)
        self.assertFalse(result["promotionAuthority"])
        self.assertFalse(result["homophoneNormalization"])
        self.assertNotIn("pass", result)
        self.assertNotIn("中国车开", json.dumps(result, ensure_ascii=False))
        self.assertEqual(result["sourceAudioSHA256"], "a" * 64)
        self.assertEqual(result["algorithmVersion"], "chinese-script-diagnostic-v1")

    def test_real_errors_and_homophones_remain_after_script_conversion(self):
        for reference, hypothesis, counts in (
            ("车站", "車山", (1, 0, 0)),
            ("车站", "車", (0, 0, 1)),
            ("车站", "車站山", (0, 1, 0)),
            ("身后坐", "深厚做", (3, 0, 0)),
        ):
            with self.subTest(hypothesis=hypothesis):
                result = self.diagnose(reference, hypothesis)["scriptCanonicalCharacterMetrics"]
                self.assertEqual(tuple(result[key] for key in ("substitutions", "insertions", "deletions")), counts)

    def test_both_script_directions_and_punctuation_are_consistent(self):
        first = self.diagnose("中国，车开。", "中國車開")
        second = self.diagnose("中國車開", "中国，车开。")
        self.assertEqual(first["scriptCanonicalCharacterMetrics"]["errorRate"], 0)
        self.assertEqual(second["scriptCanonicalCharacterMetrics"]["errorRate"], 0)

    def test_locale_and_bad_inputs_fail_without_launching_converter(self):
        with patch("check_language_output._pinned_chinese_script_transform") as convert:
            for language, reference, audio in (("japanese", "国", "a" * 64),
                                                ("chinese", "", "a" * 64),
                                                ("chinese", "国", "invalid")):
                with self.subTest(language=language), self.assertRaises(ChineseScriptDiagnosticError):
                    chinese_script_diagnostic(reference, "國", language, audio_sha256=audio, icu_root=Path("private"))
            convert.assert_not_called()

    def test_supplement_cannot_override_governed_failure(self):
        value = verification("chinese", script="中国车开", transcript_override="中國車開")
        value["scriptDiagnostic"] = self.diagnose("中国车开", "中國車開")
        failures = validate_structured_verification(value, "chinese", "中国车开", "fixture")
        self.assertTrue(failures)
        self.assertEqual(value["characterErrorRate"], .75)

    def test_tool_missing_or_drift_fails_before_launch(self):
        with tempfile.TemporaryDirectory() as temp, patch("check_language_output.subprocess.run") as run:
            root = Path(temp)
            with self.assertRaisesRegex(ChineseScriptDiagnosticError, "converter-unavailable"):
                _pinned_chinese_script_transform(("国", "國"), root)
            (root / "bin").mkdir()
            (root / "bin/uconv").write_text("drift")
            with self.assertRaisesRegex(ChineseScriptDiagnosticError, "converter-digest-mismatch"):
                _pinned_chinese_script_transform(("国", "國"), root)
            run.assert_not_called()

    def test_pinned_converter_rechecks_files_and_scrubs_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pins = dict(CHINESE_SCRIPT_CONVERTER, files={})
            for relative in CHINESE_SCRIPT_CONVERTER["files"]:
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"fixture")
                pins["files"][relative] = hashlib.sha256(b"fixture").hexdigest()
            calls = []
            def run(command, **kwargs):
                calls.append((command, kwargs))
                if "--version" in command:
                    output = pins["version"] + "\n"
                else:
                    output = self.transform((kwargs["input"], ""), root)[0]
                return subprocess.CompletedProcess(command, 0, output, "")
            with patch("check_language_output.CHINESE_SCRIPT_CONVERTER", pins), \
                 patch("check_language_output.subprocess.run", side_effect=run):
                self.assertEqual(_pinned_chinese_script_transform(("国", "國"), root), ("国", "国"))
                self.assertEqual(len(calls), 3)
                self.assertEqual(set(calls[0][1]["env"]), {"PATH", "LANG"})
                def drift(command, **kwargs):
                    result = run(command, **kwargs)
                    (root / "lib/libicudata.78.dylib").write_bytes(b"changed")
                    return result
                with patch("check_language_output.subprocess.run", side_effect=drift), \
                     self.assertRaisesRegex(ChineseScriptDiagnosticError, "converter-digest-mismatch"):
                    _pinned_chinese_script_transform(("国", "國"), root)

    def test_cli_refuses_existing_evidence_and_redacts_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "existing.json"
            output.write_text("original")
            result = subprocess.run([
                sys.executable, CHECK, "chinese-script-diagnostic", "--reference-file", temp,
                "--transcript-file", temp, "--audio-file", temp, "--icu-root", temp,
                "--output", str(output)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(output.read_text(), "original")
            self.assertNotIn(temp, result.stderr)

    def test_converter_version_timeout_and_stderr_fail_closed(self):
        def pinned(path):
            for relative, digest in CHINESE_SCRIPT_CONVERTER["files"].items():
                if str(path).endswith(relative):
                    return digest
            self.fail("unexpected converter file")
        valid_version = subprocess.CompletedProcess([], 0, CHINESE_SCRIPT_CONVERTER["version"], "")
        cases = (
            ([subprocess.CompletedProcess([], 0, "unreviewed version", "")], "version-mismatch"),
            ([valid_version, subprocess.CompletedProcess([], 0, "国", "private text")], "output-invalid"),
            ([valid_version, subprocess.CompletedProcess([], 1, "", "private path")], "output-invalid"),
            ([subprocess.TimeoutExpired("private path", 5)], "unavailable"),
        )
        for responses, reason in cases:
            with self.subTest(reason=reason), \
                 patch("check_language_output._sha256_file", side_effect=pinned), \
                 patch("check_language_output.subprocess.run", side_effect=responses), \
                 self.assertRaisesRegex(ChineseScriptDiagnosticError, reason):
                _pinned_chinese_script_transform(("国", "國"), Path("unused"))


if __name__ == "__main__":
    unittest.main()
