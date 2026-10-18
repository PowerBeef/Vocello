#!/usr/bin/env python3
"""Offline tests for immutable language plans and run-scoped collection."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex
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
from shell_stubs import LaneShell, quote  # noqa: E402


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


LANGUAGE_EVIDENCE = "scripts/language_bench_evidence.py"
PUBLISHER = "scripts/publish_benchmark_history.py"
HISTORY = "scripts/benchmark_history.py"
SUMMARIZER = "scripts/summarize_generation_telemetry.py"
GATES = ("scripts/check_language_hints.py", "scripts/check_language_output.py")

# The phone's side of one take: the sentinel of take `failed_take` (1-based) reports a
# failed generation, every other one ok.
SENTINEL_STAND_IN = r'''
wait_device_diagnostics_sentinel() {
  qv_record wait_device_diagnostics_sentinel "$1"
  local status=ok
  (( $(grep -c "^wait_device_diagnostics_sentinel" "$QV_CALLS") != FAILED_TAKE )) || status=failed
  mkdir -p "$3/$1"
  printf '{"status": "%s"}\n' "$status" >"$3/$1/device-diagnostics-done.json"
  printf '%s\n' "$3/$1/device-diagnostics-done.json"
}
'''


class IOSLanguageBenchLaneTests(unittest.TestCase):
    """The shipped iPhone `lang-bench` (scripts/ios_device.sh cmd_lang_bench), run end to end
    over recorded stand-ins (scripts/tests/shell_stubs.py): the phone, the build and every
    gate and publisher are shims; the immutable plan is the real one. On macOS this runs
    under the lane's own Bash 3.2, where an empty optional array would break `set -u`."""

    def lang_bench(self, *arguments: str, failed_take: int = 0):
        shell = LaneShell(self, "ios_device.sh")
        real_evidence = quote(ROOT / LANGUAGE_EVIDENCE)
        shell.helper(LANGUAGE_EVIDENCE, f'[[ "$1" != plan ]] || exec "$QV_REAL_PYTHON" {real_evidence} "$@"')
        for gate in GATES:
            shell.helper(gate, "exit 0")
        shell.helper("scripts/qc.py",
                     'case "$1" in run) echo qc-run-fixture ;; language-bench) echo "spoken content PASS" ;; esac')
        for helper in (PUBLISHER, SUMMARIZER, HISTORY):
            shell.helper(helper, "exit 0")
        body = (
            "qv_stub require_team\nqv_stub cmd_build\nqv_stub cmd_install\nqv_stub capture_benchmark_source\n"
            "require_qc_python() { QC_PYTHON=python3; }\n"
            'cmd_launch() { qv_record cmd_launch "$@" "telemetry=${QWENVOICE_NATIVE_TELEMETRY_MODE:-}"; }\n'
            + SENTINEL_STAND_IN.replace("FAILED_TAKE", str(failed_take))
            + f"cmd_lang_bench {shlex.join(arguments)}\n"
        )
        return shell.run(body), shell

    def test_a_benchmark_run_gates_without_cohort_arguments_then_publishes(self) -> None:
        completed, shell = self.lang_bench("--subset", "quick")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        launches = shell.calls_to("cmd_launch")
        self.assertEqual(len(launches), 7)
        self.assertEqual({launch[-1] for launch in launches}, {"telemetry=verbose"})
        [collected] = shell.calls_to(LANGUAGE_EVIDENCE, "collect")
        self.assertNotIn("--cohort", collected)
        for gate in GATES:
            [arguments] = shell.calls_to(gate)
            self.assertNotIn("--cohort", arguments)
            self.assertNotIn("--strict-qc", arguments)
        [published] = shell.calls_to(PUBLISHER, "language")
        self.assertEqual(published[published.index("--output-gate") + 1], "pass")
        self.assertLess(max(shell.index(gate) for gate in GATES), shell.index(PUBLISHER, "language"))
        self.assertLess(shell.index(PUBLISHER, "language"), shell.index(HISTORY, "record"))

    def test_a_diagnostic_cohort_gates_strictly_and_never_publishes(self) -> None:
        completed, shell = self.lang_bench("--subset", "quick", "--diagnostic-cohort")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("no history record created", completed.stderr)
        self.assertEqual(len(shell.calls_to("cmd_launch")), 15)
        [collected] = shell.calls_to(LANGUAGE_EVIDENCE, "collect")
        self.assertEqual(collected[collected.index("--cohort") + 1], str(COHORT))
        [hints] = shell.calls_to(GATES[0])
        self.assertIn("--strict-qc", hints)
        self.assertEqual(hints[hints.index("--cohort") + 1], str(COHORT))
        for helper in (PUBLISHER, SUMMARIZER, HISTORY):
            self.assertEqual(shell.calls_to(helper), [], helper)

    def assert_failed_before_publishing(self, *arguments: str) -> None:
        completed, shell = self.lang_bench(*arguments, failed_take=2)
        self.assertEqual(completed.returncode, 1)
        self.assertIn("lang-bench FAIL", completed.stderr)
        self.assertNotIn("no history record created", completed.stderr)
        for helper in (PUBLISHER, HISTORY):
            self.assertEqual(shell.calls_to(helper), [], helper)

    def test_a_failed_take_fails_a_benchmark_run_before_it_publishes(self) -> None:
        self.assert_failed_before_publishing("--subset", "quick")

    def test_a_failed_take_fails_a_cohort_instead_of_reporting_it_passed(self) -> None:
        self.assert_failed_before_publishing("--subset", "quick", "--diagnostic-cohort")


class LanguageBenchEvidenceTests(unittest.TestCase):
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
        # Seed identity v2 (audit #86 part 2): an Auto take is an independent
        # sample with its own seed; the pinned take keeps its v1 seed, and the
        # plan declares the v2 policy.
        self.assertEqual(first["seedPolicy"], "sha256-v2-mode-script-language-auto-63bit")
        self.assertNotEqual(by_cell["custom-en-pinned"]["seed"], by_cell["custom-en-auto"]["seed"])
        self.assertNotEqual(by_cell["custom-fr-pinned"]["seed"], by_cell["custom-fr-auto"]["seed"])
        v1_identity = hashlib.sha256(b"language-bench-seed-v1|custom|english").digest()[:8]
        self.assertEqual(
            by_cell["custom-en-pinned"]["seed"], int.from_bytes(v1_identity, "big") & ((1 << 63) - 1),
        )
        self.assertEqual(
            by_cell["custom-en-pinned"]["promptEquivalenceGroup"],
            by_cell["custom-en-auto"]["promptEquivalenceGroup"],
        )
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

    def test_plan_refuses_a_script_that_fails_the_corpus_lint(self) -> None:
        # AQ-02: digits, brackets and abbreviations never reach a gated script.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            corpus_path = root / "corpus.json"
            for index, (script_edit, code) in enumerate((
                (lambda script: script.replace("on time", "at 9"), "digit"),
                (lambda script: script.replace("the quiet station", "the (quiet) station"), "bracket"),
                (lambda script: script.replace("The morning train", "Mr. Smith's train"), "abbreviation"),
            )):
                corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
                english = next(entry for entry in corpus["languages"] if entry["id"] == "english")
                english["script"] = script_edit(english["script"])
                write_json_atomic(corpus_path, corpus)
                with self.subTest(code=code), self.assertRaisesRegex(EvidenceError, f"corpus lint: {code}"):
                    build_plan(
                        run_id=f"lint-fixture-{index}",
                        matrix_path=MATRIX,
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
