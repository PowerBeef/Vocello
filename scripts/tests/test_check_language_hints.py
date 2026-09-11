#!/usr/bin/env python3
"""Offline fixture tests for scripts/check_language_hints.py (no device)."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from language_bench_evidence import build_plan, write_json_atomic


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CHECK = os.path.join(ROOT, "scripts", "check_language_hints.py")
MATRIX = os.path.join(ROOT, "config", "language-bench-matrix.json")
CORPUS = os.path.join(ROOT, "config", "language-bench-corpus.json")


def write_fixture(diag: str, run_id: str) -> None:
    engine_dir = os.path.join(diag, "engine")
    os.makedirs(engine_dir, exist_ok=True)
    quick_cells = [
        ("custom-en-pinned", "custom", "english"),
        ("custom-en-auto", "custom", "english"),
        ("design-en-pinned", "design", "english"),
        ("custom-fr-pinned", "custom", "french"),
        ("custom-fr-auto", "custom", "french"),
        ("design-fr-pinned", "design", "french"),
        ("custom-fr-text-en-pinned", "custom", "english"),
    ]
    rows = []
    for cell_id, mode, hint in quick_cells:
        rows.append(
            {
                "mode": mode,
                "finishReason": "completed",
                "notes": {
                    "benchRunID": run_id,
                    "benchCell": cell_id,
                    "languageHint": hint,
                },
                "audioQC": {"verdict": "pass"},
            }
        )
    with open(os.path.join(engine_dir, "generations.jsonl"), "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def write_planned_fixture(diag: str, run_id: str, plan_path: str) -> dict:
    plan = build_plan(
        run_id=run_id,
        matrix_path=Path(MATRIX),
        corpus_path=Path(CORPUS),
        subset="quick",
        cohort_path=None,
    )
    write_json_atomic(Path(plan_path), plan)
    engine_dir = os.path.join(diag, "engine")
    os.makedirs(engine_dir, exist_ok=True)
    rows = []
    group_digests = {
        "custom-english-v1": "a" * 64,
        "custom-french-v1": "b" * 64,
    }
    for take in plan["takes"]:
        generation_id = f"generation-{take['takeIndex']}"
        child = take["childRunID"]
        directory = os.path.join(diag, "runs", child)
        os.makedirs(directory, exist_ok=True)
        group = take.get("promptEquivalenceGroup")
        prompt_digest = group_digests.get(group, "c" * 64)
        with open(os.path.join(directory, "device-diagnostics-done.json"), "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "runID": child,
                    "generationID": generation_id,
                    "mode": take["mode"],
                    "variant": take["variant"],
                    "status": "ok",
                    "seed": take["seed"],
                    "samplingVariation": take["samplingVariation"],
                    "requestedLanguageHint": take["uiHint"],
                    "languageHintSource": "auto" if take["uiHint"] == "auto" else "explicit",
                    "promptDigestScope": "resolved",
                    "resolvedPromptAssemblyDigest": prompt_digest,
                },
                handle,
            )
        rows.append(
            {
                "generationID": generation_id,
                "mode": take["mode"],
                "finishReason": "completed",
                "notes": {
                    "benchRunID": run_id,
                    "benchCell": take["cellID"],
                    "languageHint": take["expectedHint"],
                    "samplingSeed": str(take["seed"]),
                    "samplingVariation": take["samplingVariation"],
                },
                "audioQC": {"verdict": "pass"},
            }
        )
    with open(os.path.join(engine_dir, "generations.jsonl"), "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    return plan


class CheckLanguageHintsTests(unittest.TestCase):
    def run_planned_checker(
        self,
        diag: str,
        run_id: str,
        plan_path: str,
        *,
        strict_qc: bool = False,
        cohort_path: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = [
                sys.executable,
                CHECK,
                diag,
                "--run-id",
                run_id,
                "--matrix",
                MATRIX,
                "--corpus",
                CORPUS,
                "--subset",
                "quick",
                "--plan",
                plan_path,
            ]
        if strict_qc:
            command.append("--strict-qc")
        if cohort_path:
            command.extend(["--cohort", cohort_path])
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_quick_subset_passes_fixture(self) -> None:
        run_id = "fixture-run"
        with tempfile.TemporaryDirectory() as diag:
            write_fixture(diag, run_id)
            proc = subprocess.run(
                [
                    sys.executable,
                    CHECK,
                    diag,
                    "--run-id",
                    run_id,
                    "--matrix",
                    MATRIX,
                    "--corpus",
                    CORPUS,
                    "--subset",
                    "quick",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_wrong_hint_fails(self) -> None:
        run_id = "fixture-bad"
        with tempfile.TemporaryDirectory() as diag:
            write_fixture(diag, run_id)
            path = os.path.join(diag, "engine", "generations.jsonl")
            with open(path, encoding="utf-8") as fh:
                text = fh.read().replace('"languageHint": "english"', '"languageHint": "french"', 1)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            proc = subprocess.run(
                [
                    sys.executable,
                    CHECK,
                    diag,
                    "--run-id",
                    run_id,
                    "--matrix",
                    MATRIX,
                    "--corpus",
                    CORPUS,
                    "--subset",
                    "quick",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("languageHint", proc.stdout + proc.stderr)

    def test_predeclared_seed_and_generation_correlation_pass(self) -> None:
        run_id = "fixture-planned"
        with tempfile.TemporaryDirectory() as diag:
            plan_path = os.path.join(diag, "plan.json")
            write_planned_fixture(diag, run_id, plan_path)
            result = self.run_planned_checker(diag, run_id, plan_path)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_wrong_generation_fails(self) -> None:
        run_id = "fixture-wrong-generation"
        with tempfile.TemporaryDirectory() as diag:
            plan_path = os.path.join(diag, "plan.json")
            plan = write_planned_fixture(diag, run_id, plan_path)
            sentinel = os.path.join(diag, "runs", plan["takes"][0]["childRunID"], "device-diagnostics-done.json")
            with open(sentinel, encoding="utf-8") as handle:
                record = json.load(handle)
            record["generationID"] = "wrong-generation"
            with open(sentinel, "w", encoding="utf-8") as handle:
                json.dump(record, handle)
            result = self.run_planned_checker(diag, run_id, plan_path)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("wrong-generation", result.stdout + result.stderr)

    def test_missing_seed_proof_fails(self) -> None:
        run_id = "fixture-missing-seed"
        with tempfile.TemporaryDirectory() as diag:
            plan_path = os.path.join(diag, "plan.json")
            write_planned_fixture(diag, run_id, plan_path)
            engine_path = os.path.join(diag, "engine", "generations.jsonl")
            with open(engine_path, encoding="utf-8") as handle:
                rows = [json.loads(line) for line in handle]
            rows[0]["notes"].pop("samplingSeed")
            with open(engine_path, "w", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row) + "\n")
            result = self.run_planned_checker(diag, run_id, plan_path)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("samplingSeed", result.stdout + result.stderr)

    def test_requested_language_hint_tamper_fails(self) -> None:
        run_id = "fixture-requested-hint"
        with tempfile.TemporaryDirectory() as diag:
            plan_path = os.path.join(diag, "plan.json")
            plan = write_planned_fixture(diag, run_id, plan_path)
            target = next(take for take in plan["takes"] if take["uiHint"] == "auto")
            sentinel = os.path.join(
                diag, "runs", target["childRunID"], "device-diagnostics-done.json"
            )
            with open(sentinel, encoding="utf-8") as handle:
                record = json.load(handle)
            record["requestedLanguageHint"] = target["expectedHint"]
            record["languageHintSource"] = "explicit"
            with open(sentinel, "w", encoding="utf-8") as handle:
                json.dump(record, handle)
            result = self.run_planned_checker(diag, run_id, plan_path)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("requestedLanguageHint", result.stdout + result.stderr)

    def test_unrelated_stale_sentinel_is_ignored(self) -> None:
        run_id = "fixture-stale"
        with tempfile.TemporaryDirectory() as diag:
            plan_path = os.path.join(diag, "plan.json")
            write_planned_fixture(diag, run_id, plan_path)
            stale = os.path.join(diag, "stale", "older-run--custom-en-auto")
            os.makedirs(stale)
            with open(os.path.join(stale, "device-diagnostics-done.json"), "w", encoding="utf-8") as handle:
                json.dump({"runID": "older-run--custom-en-auto"}, handle)
            result = self.run_planned_checker(diag, run_id, plan_path)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_duplicate_current_sentinel_fails(self) -> None:
        run_id = "fixture-duplicate"
        with tempfile.TemporaryDirectory() as diag:
            plan_path = os.path.join(diag, "plan.json")
            plan = write_planned_fixture(diag, run_id, plan_path)
            child = plan["takes"][0]["childRunID"]
            source = os.path.join(diag, "runs", child, "device-diagnostics-done.json")
            duplicate = os.path.join(diag, "duplicate", child)
            os.makedirs(duplicate)
            shutil.copy2(source, os.path.join(duplicate, "device-diagnostics-done.json"))
            result = self.run_planned_checker(diag, run_id, plan_path)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("expected 1 sentinel, got 2", result.stdout + result.stderr)

    def test_diagnostic_cohort_rejects_qc_warning(self) -> None:
        run_id = "fixture-cohort-warning"
        with tempfile.TemporaryDirectory() as diag:
            plan = build_plan(
                run_id=run_id,
                matrix_path=Path(MATRIX),
                corpus_path=Path(CORPUS),
                subset="quick",
                cohort_path=Path(os.path.join(ROOT, "config", "language-bench-diagnostic-cohort.json")),
            )
            plan_path = os.path.join(diag, "plan.json")
            write_json_atomic(Path(plan_path), plan)
            # Reuse the planned fixture writer's shape with the cohort plan.
            engine_dir = os.path.join(diag, "engine")
            os.makedirs(engine_dir)
            rows = []
            group_digest = "b" * 64
            for take in plan["takes"]:
                child_dir = os.path.join(diag, "runs", take["childRunID"])
                os.makedirs(child_dir)
                generation = f"generation-{take['takeIndex']}"
                with open(os.path.join(child_dir, "device-diagnostics-done.json"), "w", encoding="utf-8") as handle:
                    json.dump({
                        "runID": take["childRunID"], "generationID": generation,
                        "mode": take["mode"], "variant": take["variant"], "status": "ok",
                        "seed": take["seed"], "samplingVariation": "expressive",
                        "requestedLanguageHint": take["uiHint"],
                        "languageHintSource": "auto" if take["uiHint"] == "auto" else "explicit",
                        "promptDigestScope": "resolved",
                        "resolvedPromptAssemblyDigest": group_digest,
                    }, handle)
                rows.append({
                    "generationID": generation, "mode": take["mode"], "finishReason": "completed",
                    "notes": {
                        "benchRunID": run_id, "benchCell": take["cellID"],
                        "languageHint": take["expectedHint"], "samplingSeed": str(take["seed"]),
                        "samplingVariation": "expressive",
                    },
                    "audioQC": {"verdict": "warn" if take["takeIndex"] == 1 else "pass"},
                })
            with open(os.path.join(engine_dir, "generations.jsonl"), "w", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row) + "\n")
            cohort_path = os.path.join(ROOT, "config", "language-bench-diagnostic-cohort.json")
            result = self.run_planned_checker(
                diag,
                run_id,
                plan_path,
                strict_qc=True,
                cohort_path=cohort_path,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("audioQC warn", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
