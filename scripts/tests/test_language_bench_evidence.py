#!/usr/bin/env python3
"""Offline tests for immutable language plans and run-scoped collection."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from language_bench_evidence import (
    EvidenceError,
    build_plan,
    canonical_digest,
    collect,
    validate_plan_against_sources,
    write_json_atomic,
)


ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "config" / "language-bench-matrix.json"
CORPUS = ROOT / "config" / "language-bench-corpus.json"
COHORT = ROOT / "config" / "language-bench-diagnostic-cohort.json"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_source(root: Path, plan: dict, *, stale: bool = False) -> None:
    engine = root / "engine"
    app = root / "app"
    engine.mkdir(parents=True)
    app.mkdir(parents=True)
    engine_rows = []
    app_rows = []
    for take in plan["takes"]:
        child = take["childRunID"]
        generation = f"generation-{take['takeIndex']}"
        run_dir = root / child
        run_dir.mkdir()
        output_path = run_dir / "output.wav"
        with wave.open(str(output_path), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(24000)
            stream.writeframes(b"\x00\x00" * 30000)
        wav = output_path.read_bytes()
        sentinel = {
            "schemaVersion": 2,
            "runID": child,
            "generationID": generation,
            "mode": take["mode"],
            "variant": take["variant"],
            "status": "ok",
            "seed": take["seed"],
            "samplingVariation": take["samplingVariation"],
            "requestedLanguageHint": take["uiHint"],
            "languageHintSource": "auto" if take["uiHint"] == "auto" else "explicit",
            "customSpeakerID": take.get("customSpeakerID"),
            "fixtureDigest": take.get("designInstructionDigest"),
            "outputEvidence": {
                "artifactRelativePath": "output.wav",
                "sha256": sha256(wav),
                "byteCount": len(wav),
                "durationSeconds": 1.25,
                "sampleRate": 24000.0,
                "channelCount": 1,
                "frameCount": 30000,
            },
        }
        (run_dir / "device-diagnostics-done.json").write_text(
            json.dumps(sentinel), encoding="utf-8"
        )
        engine_rows.append(
            {
                "schemaVersion": 7,
                "generationID": generation,
                "layer": "engine",
                "mode": take["mode"],
                "finishReason": "completed",
                "notes": {
                    "benchRunID": plan["runID"],
                    "benchCell": take["cellID"],
                    "samplingSeed": str(take["seed"]),
                    "samplingVariation": take["samplingVariation"],
                },
            }
        )
        app_rows.append(
            {
                "schemaVersion": 7,
                "generationID": generation,
                "layer": "app",
                "mode": take["mode"],
                "finishReason": "completed",
                "notes": {
                    "benchRunID": plan["runID"],
                    "benchCell": take["cellID"],
                },
                "timingsMS": {"submitToCompletedMS": 100},
                "frontendMetrics": {"submitToCompletedMS": 100},
            }
        )
    (engine / "generations.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in engine_rows), encoding="utf-8"
    )
    (app / "generations.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in app_rows), encoding="utf-8"
    )
    if stale:
        stale_dir = root / "old-run--custom-en-auto"
        stale_dir.mkdir()
        (stale_dir / "device-diagnostics-done.json").write_text(
            json.dumps({"runID": "old-run--custom-en-auto"}), encoding="utf-8"
        )
        (root / "unrelated-history.txt").write_text("must not be copied", encoding="utf-8")


class LanguageBenchEvidenceTests(unittest.TestCase):
    def test_optional_language_gate_arrays_are_safe_under_bash_nounset(self) -> None:
        script = (ROOT / "scripts" / "ios_device.sh").read_text(encoding="utf-8")
        start = script.index("cmd_lang_bench() {")
        end = script.index("\ncmd_bench() {", start)
        body = script[start:end]
        self.assertNotIn('\n    "${cohort_args[@]}"', body)
        self.assertNotIn('\n    "${hint_gate_args[@]}"', body)
        self.assertEqual(
            body.count('${cohort_args[@]+"${cohort_args[@]}"}'),
            3,
        )
        self.assertEqual(
            body.count('${hint_gate_args[@]+"${hint_gate_args[@]}"}'),
            1,
        )

    def test_cohort_control_flow_cannot_publish_history(self) -> None:
        script = (ROOT / "scripts" / "ios_device.sh").read_text(encoding="utf-8")
        start = script.index("cmd_lang_bench() {")
        end = script.index("\ncmd_bench() {", start)
        body = script[start:end]
        failure_gate = body.index("if (( cell_fail > 0 || collect_st != 0")
        cohort_return = body.index(
            'note "lang-bench diagnostic cohort PASS · all $cell_count predeclared takes passed · no history record created"'
        )
        cohort_return = body.index("return 0", cohort_return)
        publisher = body.index("publish_benchmark_history.py")
        recorder = body.index("record_benchmark_history")
        self.assertLess(failure_gate, cohort_return)
        self.assertLess(cohort_return, publisher)
        self.assertLess(publisher, recorder)
        self.assertNotIn("publish_benchmark_history.py", body[:cohort_return])
        self.assertNotIn("record_benchmark_history", body[:cohort_return])

    def test_default_plan_is_deterministic_seeded_and_pairs_pinned_auto(self) -> None:
        first = build_plan(
            run_id="plan-fixture",
            matrix_path=MATRIX,
            corpus_path=CORPUS,
            subset="quick",
            cohort_path=None,
        )
        second = build_plan(
            run_id="plan-fixture",
            matrix_path=MATRIX,
            corpus_path=CORPUS,
            subset="quick",
            cohort_path=None,
        )
        self.assertEqual(first, second)
        self.assertEqual(first["takeCount"], 7)
        self.assertTrue(all(isinstance(take["seed"], int) for take in first["takes"]))
        self.assertTrue(all(take["samplingVariation"] == "expressive" for take in first["takes"]))
        by_cell = {take["cellID"]: take for take in first["takes"]}
        self.assertEqual(by_cell["custom-en-pinned"]["seed"], by_cell["custom-en-auto"]["seed"])
        self.assertEqual(by_cell["custom-fr-pinned"]["seed"], by_cell["custom-fr-auto"]["seed"])
        self.assertEqual(by_cell["custom-en-pinned"]["customSpeakerID"], "aiden")
        self.assertEqual(by_cell["design-en-pinned"]["uiHint"], "english")
        self.assertIsNone(by_cell["design-en-pinned"]["customSpeakerID"])
        self.assertRegex(by_cell["design-en-pinned"]["designInstructionDigest"], r"^[0-9a-f]{64}$")
        full = build_plan(
            run_id="full-fixture",
            matrix_path=MATRIX,
            corpus_path=CORPUS,
            subset="full",
            cohort_path=None,
        )
        self.assertEqual(
            len({
                take["designInstructionDigest"]
                for take in full["takes"]
                if take["mode"] == "design"
            }),
            1,
        )

    def test_plan_rejects_short_scripts_and_auto_design_language(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            corpus_path = root / "corpus.json"
            matrix_path = root / "matrix.json"
            corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
            matrix = json.loads(MATRIX.read_text(encoding="utf-8"))

            corpus["languages"][0]["script"] = "Too short for promotion."
            write_json_atomic(corpus_path, corpus)
            write_json_atomic(matrix_path, matrix)
            with self.assertRaisesRegex(EvidenceError, "requires at least 15"):
                build_plan(
                    run_id="short-script-fixture",
                    matrix_path=matrix_path,
                    corpus_path=corpus_path,
                    subset="quick",
                    cohort_path=None,
                )

            corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
            design = next(cell for cell in matrix["cells"] if cell["mode"] == "design")
            design["uiHint"] = "auto"
            write_json_atomic(corpus_path, corpus)
            write_json_atomic(matrix_path, matrix)
            with self.assertRaisesRegex(EvidenceError, "explicit target language"):
                build_plan(
                    run_id="auto-design-fixture",
                    matrix_path=matrix_path,
                    corpus_path=corpus_path,
                    subset="quick",
                    cohort_path=None,
                )

            corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
            matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
            corpus["languages"][0]["customSpeakerID"] = "unknown_speaker"
            write_json_atomic(corpus_path, corpus)
            write_json_atomic(matrix_path, matrix)
            with self.assertRaisesRegex(EvidenceError, "absent from qwenvoice_contract"):
                build_plan(
                    run_id="unknown-speaker-fixture",
                    matrix_path=matrix_path,
                    corpus_path=corpus_path,
                    subset="quick",
                    cohort_path=None,
                )

            corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
            matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
            corpus["languages"][1]["designInstruction"] = (
                "A distinctly different fixture that would confound language comparisons."
            )
            write_json_atomic(corpus_path, corpus)
            write_json_atomic(matrix_path, matrix)
            with self.assertRaisesRegex(EvidenceError, "share one corpus-owned instruction"):
                build_plan(
                    run_id="mixed-design-fixture",
                    matrix_path=matrix_path,
                    corpus_path=corpus_path,
                    subset="quick",
                    cohort_path=None,
                )

    def test_diagnostic_cohort_has_all_fifteen_predeclared_takes(self) -> None:
        plan = build_plan(
            run_id="cohort-fixture",
            matrix_path=MATRIX,
            corpus_path=CORPUS,
            subset="quick",
            cohort_path=COHORT,
        )
        self.assertEqual(plan["kind"], "diagnosticCohort")
        self.assertEqual(plan["takeCount"], 15)
        self.assertEqual(
            [take["seed"] for take in plan["takes"][:3]],
            [104729, 104729, 104729],
        )
        self.assertEqual(len({take["childRunID"] for take in plan["takes"]}), 15)

    def test_rehashed_seed_tamper_still_fails_tracked_input_reconstruction(self) -> None:
        plan = build_plan(
            run_id="tamper-fixture",
            matrix_path=MATRIX,
            corpus_path=CORPUS,
            subset="quick",
            cohort_path=None,
        )
        plan["takes"][0]["seed"] += 1
        unsigned = dict(plan)
        unsigned.pop("planDigest")
        plan["planDigest"] = canonical_digest(unsigned)
        with self.assertRaisesRegex(EvidenceError, "does not match its tracked"):
            validate_plan_against_sources(
                plan,
                matrix_path=MATRIX,
                corpus_path=CORPUS,
                subset="quick",
                cohort_path=None,
            )

    def test_wrong_cohort_config_identity_is_rejected(self) -> None:
        plan = build_plan(
            run_id="cohort-identity-fixture",
            matrix_path=MATRIX,
            corpus_path=CORPUS,
            subset="quick",
            cohort_path=COHORT,
        )
        with self.assertRaisesRegex(EvidenceError, "does not match its tracked"):
            validate_plan_against_sources(
                plan,
                matrix_path=MATRIX,
                corpus_path=CORPUS,
                subset="full",
                cohort_path=COHORT,
            )

    def test_collector_copies_only_current_run_and_exact_wavs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            output = root / "output"
            plan_path = root / "plan.json"
            plan = build_plan(
                run_id="collect-fixture",
                matrix_path=MATRIX,
                corpus_path=CORPUS,
                subset="quick",
                cohort_path=None,
            )
            write_json_atomic(plan_path, plan)
            build_source(source, plan, stale=True)
            manifest = collect(source, plan_path, output)
            self.assertEqual(manifest["takeCount"], 7)
            self.assertFalse((output / "unrelated-history.txt").exists())
            self.assertFalse(any("old-run" in str(path) for path in output.rglob("*")))
            for take in plan["takes"]:
                self.assertTrue((output / "runs" / take["childRunID"] / "output.wav").is_file())
            selected_rows = (output / "engine" / "generations.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(selected_rows), 7)
            app_rows = (output / "app" / "generations.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(app_rows), 7)

    def test_missing_app_layer_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            output = root / "output"
            plan_path = root / "plan.json"
            plan = build_plan(
                run_id="missing-app-fixture",
                matrix_path=MATRIX,
                corpus_path=CORPUS,
                subset="quick",
                cohort_path=None,
            )
            write_json_atomic(plan_path, plan)
            build_source(source, plan)
            shutil.rmtree(source / "app")
            with self.assertRaisesRegex(EvidenceError, "missing app/generations.jsonl"):
                collect(source, plan_path, output)

    def test_duplicate_app_generation_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            output = root / "output"
            plan_path = root / "plan.json"
            plan = build_plan(
                run_id="duplicate-app-fixture",
                matrix_path=MATRIX,
                corpus_path=CORPUS,
                subset="quick",
                cohort_path=None,
            )
            write_json_atomic(plan_path, plan)
            build_source(source, plan)
            app_path = source / "app" / "generations.jsonl"
            first = app_path.read_text(encoding="utf-8").splitlines()[0]
            with app_path.open("a", encoding="utf-8") as handle:
                handle.write(first + "\n")
            with self.assertRaisesRegex(EvidenceError, "expected 1 row, got 2"):
                collect(source, plan_path, output)

    def test_wrong_app_layer_or_missing_completion_is_rejected(self) -> None:
        for name, mutate, message in (
            (
                "wrong-layer",
                lambda row: row.__setitem__("layer", "engine"),
                "declares layer 'engine'",
            ),
            (
                "missing-completion",
                lambda row: row.pop("frontendMetrics"),
                "positive submitToCompletedMS",
            ),
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / "source"
                output = root / "output"
                plan_path = root / "plan.json"
                plan = build_plan(
                    run_id=f"{name}-fixture",
                    matrix_path=MATRIX,
                    corpus_path=CORPUS,
                    subset="quick",
                    cohort_path=None,
                )
                write_json_atomic(plan_path, plan)
                build_source(source, plan)
                app_path = source / "app" / "generations.jsonl"
                rows = [json.loads(line) for line in app_path.read_text().splitlines()]
                mutate(rows[0])
                app_path.write_text(
                    "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
                )
                with self.assertRaisesRegex(EvidenceError, message):
                    collect(source, plan_path, output)

    def test_requested_language_hint_identity_is_rejected_when_tampered(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            output = root / "output"
            plan_path = root / "plan.json"
            plan = build_plan(
                run_id="requested-hint-fixture",
                matrix_path=MATRIX,
                corpus_path=CORPUS,
                subset="quick",
                cohort_path=None,
            )
            write_json_atomic(plan_path, plan)
            build_source(source, plan)
            target = plan["takes"][1]
            sentinel = source / target["childRunID"] / "device-diagnostics-done.json"
            record = json.loads(sentinel.read_text())
            self.assertEqual(target["uiHint"], "auto")
            record["requestedLanguageHint"] = "english"
            record["languageHintSource"] = "explicit"
            sentinel.write_text(json.dumps(record), encoding="utf-8")
            with self.assertRaisesRegex(EvidenceError, "requested language hint"):
                collect(source, plan_path, output)

    def test_mode_fixture_identity_is_rejected_when_tampered(self) -> None:
        for mode, field, message in (
            ("custom", "customSpeakerID", "Custom speaker"),
            ("design", "fixtureDigest", "Design instruction"),
        ):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / "source"
                output = root / "output"
                plan_path = root / "plan.json"
                plan = build_plan(
                    run_id=f"{mode}-fixture-identity",
                    matrix_path=MATRIX,
                    corpus_path=CORPUS,
                    subset="quick",
                    cohort_path=None,
                )
                write_json_atomic(plan_path, plan)
                build_source(source, plan)
                target = next(take for take in plan["takes"] if take["mode"] == mode)
                sentinel_path = source / target["childRunID"] / "device-diagnostics-done.json"
                sentinel = json.loads(sentinel_path.read_text(encoding="utf-8"))
                sentinel[field] = "tampered"
                sentinel_path.write_text(json.dumps(sentinel), encoding="utf-8")
                with self.assertRaisesRegex(EvidenceError, message):
                    collect(source, plan_path, output)

    def test_unexpected_current_run_app_generation_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            output = root / "output"
            plan_path = root / "plan.json"
            plan = build_plan(
                run_id="unexpected-app-fixture",
                matrix_path=MATRIX,
                corpus_path=CORPUS,
                subset="quick",
                cohort_path=None,
            )
            write_json_atomic(plan_path, plan)
            build_source(source, plan)
            unexpected = {
                "schemaVersion": 7,
                "generationID": "unexpected-generation",
                "mode": "custom",
                "finishReason": "completed",
                "notes": {
                    "benchRunID": plan["runID"],
                    "benchCell": "unexpected-cell",
                },
            }
            with (source / "app" / "generations.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(unexpected) + "\n")
            with self.assertRaisesRegex(EvidenceError, "unexpected current-run generation"):
                collect(source, plan_path, output)

    def test_duplicate_sentinel_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            output = root / "output"
            plan_path = root / "plan.json"
            plan = build_plan(
                run_id="duplicate-fixture",
                matrix_path=MATRIX,
                corpus_path=CORPUS,
                subset="quick",
                cohort_path=None,
            )
            write_json_atomic(plan_path, plan)
            build_source(source, plan)
            child = plan["takes"][0]["childRunID"]
            duplicate = source / "duplicate" / child
            duplicate.mkdir(parents=True)
            shutil.copy2(
                source / child / "device-diagnostics-done.json",
                duplicate / "device-diagnostics-done.json",
            )
            with self.assertRaisesRegex(EvidenceError, "expected 1 sentinel, got 2"):
                collect(source, plan_path, output)

    def test_wrong_generation_and_output_digest_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            output = root / "output"
            plan_path = root / "plan.json"
            plan = build_plan(
                run_id="corrupt-fixture",
                matrix_path=MATRIX,
                corpus_path=CORPUS,
                subset="quick",
                cohort_path=None,
            )
            write_json_atomic(plan_path, plan)
            build_source(source, plan)
            child = plan["takes"][0]["childRunID"]
            sentinel_path = source / child / "device-diagnostics-done.json"
            sentinel = json.loads(sentinel_path.read_text(encoding="utf-8"))
            sentinel["outputEvidence"]["sha256"] = "0" * 64
            sentinel_path.write_text(json.dumps(sentinel), encoding="utf-8")
            with self.assertRaisesRegex(EvidenceError, "SHA-256 mismatch"):
                collect(source, plan_path, output)

            sentinel["outputEvidence"]["sha256"] = sha256((source / child / "output.wav").read_bytes())
            sentinel["generationID"] = "wrong-generation"
            sentinel_path.write_text(json.dumps(sentinel), encoding="utf-8")
            with self.assertRaisesRegex(EvidenceError, "unexpected current-run generation"):
                collect(source, plan_path, output)


if __name__ == "__main__":
    unittest.main()
