#!/usr/bin/env python3
"""Outcome and ledger behaviour of `scripts/macos_test.sh gate`.

The real `cmd_gate` and `gate_finish` functions run, sourced from the lane
(scripts/tests/shell_stubs.py), against the real required-step ledger and
orchestration contract, with every step they call (project inputs, the
foundation build, the tests, the crash delta, the bench preflight, the bench and
history publication) replaced by a stub. Nothing builds, loads a model or runs a
lane.
"""
from __future__ import annotations

import json
import shlex
import unittest

from shell_stubs import LaneShell, option

PUBLISHER = "scripts/publish_benchmark_history.py"
SUMMARIZER = "scripts/summarize_generation_telemetry.py"


class MacGateOrchestrationTests(unittest.TestCase):
    def run_gate(self, *, bench: bool = False, seed: bool = False, preflight: int = 0,
                 tests: int = 0, crashes: int = 0, bench_status: int = 0,
                 real_preflight: bool = False) -> tuple[int, dict, set[str], str]:
        shell = LaneShell(self, "macos_test.sh")
        stubs = shell.path / "scripts"
        marks = shell.path / "marks"
        marks.mkdir()
        for name in ("check_project_inputs.sh", "build_foundation_targets.sh"):
            shell.executable(f"scripts/{name}", f"touch {shlex.quote(str(marks / name))}")
        if real_preflight:
            # The real preflight: a quiet host, then a model helper that exits
            # the shell the way `_test_models_die` does.
            preflight_definition = (
                "require_quiet_host() { return 0; }\n"
                "require_mac_benchmark_models() {\n"
                "  touch \"$MARKS/preflight\"; echo \"benchmark model missing: pro_custom_speed\"; exit 1\n"
                "}\n"
                "GATE_BENCH_BASELINE=/nonexistent GATE_BENCH_STAGED_BASELINE=/nonexistent\n"
            )
            shell.helper(PUBLISHER, "exit 0")
        else:
            preflight_definition = f'gate_bench_preflight() {{ touch "$MARKS/preflight"; return {preflight}; }}\n'
        body = f"""
SCRIPT_DIR={shlex.quote(str(stubs))}
QVOICE_ARTIFACTS_MACOS={shlex.quote(str(shell.path / "artifacts"))}
MARKS={shlex.quote(str(marks))}
{preflight_definition}
cmd_test() {{ touch "$MARKS/tests"; return {tests}; }}
gate_crash_delta() {{ touch "$MARKS/crash-delta"; return {crashes}; }}
run_gate_bench() {{ touch "$MARKS/bench"; return {bench_status}; }}
record_benchmark_history() {{ touch "$MARKS/history"; }}
cmd_gate
"""
        environment = {}
        if bench:
            environment["QWENVOICE_GATE_BENCH"] = "1"
        if seed:
            environment["QWENVOICE_GATE_BENCH_SEED"] = "1"
        completed = shell.run(body, env=environment, timeout=120)
        [ledger_path] = list((shell.path / "artifacts" / "gates").glob("gate-*/required-steps.json"))
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        verdict = (ledger_path.parent / "verdict.txt").read_text(encoding="utf-8")
        return completed.returncode, ledger, {path.name for path in marks.iterdir()}, verdict

    def test_a_failed_bench_preflight_stops_before_any_gate_step_with_a_finalized_ledger(self) -> None:
        status, ledger, ran, verdict = self.run_gate(bench=True, preflight=1)
        self.assertEqual(status, 1)
        self.assertEqual(ran, {"preflight"})
        self.assertEqual(ledger["workflow"], "macos-gate-with-benchmark")
        self.assertEqual(ledger["status"], "failed")
        self.assertIsNotNone(ledger["completedAt"])
        self.assertEqual(ledger["results"]["benchmark-preflight"]["status"], "failed")
        self.assertIn("project-inputs", ledger["missingRequiredSteps"])
        self.assertTrue(verdict.rstrip().endswith("GATE: FAIL"))

    def test_a_missing_benchmark_model_fails_the_real_preflight_instead_of_exiting_the_gate(self) -> None:
        # The model helpers `exit 1`; run in a subshell, the preflight returns and
        # the gate still finalizes its ledger and prints a verdict (audit #53).
        status, ledger, ran, verdict = self.run_gate(bench=True, real_preflight=True)
        self.assertEqual(status, 1)
        self.assertEqual(ran, {"preflight"})
        self.assertEqual(ledger["status"], "failed")
        self.assertEqual(ledger["results"]["benchmark-preflight"]["exitCode"], 1)
        # The reason is in the verdict, not only in preflight.log.
        self.assertIn("benchmark model missing: pro_custom_speed", verdict)
        self.assertTrue(verdict.rstrip().endswith("GATE: FAIL"))

    def test_an_inconclusive_bench_is_its_own_outcome_and_publishes_nothing(self) -> None:
        status, ledger, ran, verdict = self.run_gate(bench=True, bench_status=3)
        self.assertEqual(status, 3)
        self.assertNotIn("history", ran)
        self.assertEqual(ledger["results"]["benchmark-validation"]["exitCode"], 3)
        self.assertEqual(ledger["missingRequiredSteps"], ["history-publication"])
        self.assertTrue(verdict.rstrip().endswith("GATE: INCONCLUSIVE"))

    def test_the_bench_is_skipped_after_a_failed_step_and_left_unrecorded(self) -> None:
        status, ledger, ran, _verdict = self.run_gate(bench=True, tests=1)
        self.assertEqual(status, 1)
        self.assertNotIn("bench", ran)
        self.assertNotIn("benchmark-validation", ledger["results"])
        self.assertIn("benchmark-validation", ledger["missingRequiredSteps"])

    def test_a_new_crash_report_fails_the_gate_before_its_bench_or_history(self) -> None:
        # The crash delta is the last gate step: history publishes only after it passed.
        status, ledger, ran, verdict = self.run_gate(bench=True, crashes=1)
        self.assertEqual(status, 1)
        self.assertIn("crash-delta", ran)
        self.assertNotIn("bench", ran)
        self.assertNotIn("history", ran)
        self.assertEqual(ledger["results"]["crash-delta"]["status"], "failed")
        self.assertIn("history-publication", ledger["missingRequiredSteps"])
        self.assertIn("crashes: FAIL", verdict)
        self.assertTrue(verdict.rstrip().endswith("GATE: FAIL"))

    def test_the_deterministic_gate_runs_each_test_bundle_once_and_passes(self) -> None:
        status, ledger, ran, verdict = self.run_gate()
        self.assertEqual(status, 0)
        self.assertEqual(ledger["workflow"], "macos-gate")
        self.assertEqual(ledger["status"], "passed")
        self.assertNotIn("core-tests", ledger["results"])
        self.assertEqual(
            ran, {"check_project_inputs.sh", "build_foundation_targets.sh", "tests", "crash-delta"},
        )
        self.assertTrue(verdict.rstrip().endswith("GATE: PASS"))

    def test_a_seeding_gate_runs_the_bench_and_publishes_its_history(self) -> None:
        status, ledger, ran, _verdict = self.run_gate(seed=True)
        self.assertEqual(status, 0)
        self.assertEqual(ledger["status"], "passed")
        self.assertTrue({"preflight", "bench", "history"} <= ran)


class MacReleaseReadinessTests(unittest.TestCase):
    """The real `cmd_release_readiness`: every declared step lands in the ledger, and
    RELEASE READINESS: PASS is printed only after the ledger finalized."""

    def release_readiness(self, *, build: int = 0, crashes: int = 0):
        shell = LaneShell(self, "macos_test.sh")
        shell.executable("scripts/check_project_inputs.sh")
        shell.executable("scripts/build.sh", f"exit {build}")
        body = f'SCRIPT_DIR="$QV_SANDBOX/scripts"\nqv_stub cmd_test\nqv_stub gate_crash_delta {crashes}\n'
        completed = shell.run(body + "cmd_release_readiness\n")
        [out] = list((shell.build / "artifacts/macos/release-readiness").iterdir())
        return completed, shell, out

    def test_readiness_passes_only_through_a_finalized_ledger_of_every_step(self) -> None:
        completed, shell, out = self.release_readiness()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        order = [shell.index("scripts/check_project_inputs.sh"), shell.index("scripts/build.sh", "build"),
                 shell.index("cmd_test"), shell.index("gate_crash_delta")]
        self.assertEqual(order, sorted(order))
        ledger = json.loads((out / "required-steps.json").read_text(encoding="utf-8"))
        self.assertEqual((ledger["workflow"], ledger["status"]), ("macos-release-readiness", "passed"))
        self.assertEqual((out / "verdict.txt").read_text(encoding="utf-8"), "RELEASE READINESS: PASS\n")

    def test_a_failed_step_never_announces_readiness(self) -> None:
        for failure in ({"build": 65}, {"crashes": 1}):
            with self.subTest(failure=failure):
                completed, _shell, out = self.release_readiness(**failure)
                self.assertNotEqual(completed.returncode, 0)
                self.assertNotIn("RELEASE READINESS: PASS", completed.stdout)
                self.assertFalse((out / "verdict.txt").exists())


# A `vocello bench` that leaves one audio-QC-passing telemetry row and its results.
VOCELLO_BENCH = '''
data=""
for ((index = 1; index <= $#; index++)); do
  if [[ "${!index}" == --data-dir ]]; then next=$((index + 1)); data="${!next}"; fi
done
mkdir -p "$data/diagnostics/engine"
printf '{"generationID": "g", "audioQC": {"verdict": "pass"}}\\n' >"$data/diagnostics/engine/generations.jsonl"
printf '{}' >"$data/diagnostics/bench-results.json"
'''


class MacGateBenchWiringTests(unittest.TestCase):
    """The real `run_gate_bench` with the gate's own matrix settings, over a
    stub CLI and stub summarizers that record how they were called."""

    def run_bench(self, *, seeding: bool) -> tuple[int, list[str], list[list[str]], str]:
        shell = LaneShell(self, "macos_test.sh")
        shell.executable("scripts/build.sh")
        shell.executable("build/vocello", VOCELLO_BENCH)
        for helper in (PUBLISHER, SUMMARIZER):
            shell.helper(helper, "exit 0")
        gate_dir = shell.path / "gate"
        gate_dir.mkdir()
        body = f"""
ROOT_DIR="$QV_SANDBOX"
SCRIPT_DIR="$ROOT_DIR/scripts"
GATE_BENCH_BASELINE="$ROOT_DIR/no-committed-baseline.json"
gate_bench_quiet_host() {{ return 0; }}
require_mac_benchmark_models() {{ return 0; }}
debug_models_dir() {{ echo "$ROOT_DIR/models"; }}
capture_benchmark_source() {{ return 0; }}
run_gate_bench {shlex.quote(str(gate_dir))} {1 if seeding else 0}
"""
        completed = shell.run(body)
        [bench] = shell.calls_to("build/vocello")
        summaries = shell.calls_to(SUMMARIZER)
        log = (gate_dir / "bench.log").read_text(encoding="utf-8")
        return completed.returncode, bench, summaries, log

    def test_the_gate_bench_runs_five_seeded_warm_takes(self) -> None:
        status, bench, _summaries, log = self.run_bench(seeding=False)
        self.assertEqual(status, 0, log)
        self.assertEqual(option(bench, "--warm"), "5")
        self.assertEqual(option(bench, "--seed"), "19790615")
        # Without a committed baseline the printed seed command asks for the same count.
        self.assertIn("--seed-minimum-takes 5", log)

    def test_seeding_requires_every_warm_cell_to_carry_the_gates_take_count(self) -> None:
        status, bench, summaries, log = self.run_bench(seeding=True)
        self.assertEqual(status, 0, log)
        [seed] = [call for call in summaries if "--seed-baseline" in call]
        self.assertEqual(option(seed, "--seed-minimum-takes"), option(bench, "--warm"))
        self.assertIn("BASELINE SEEDED", log)


if __name__ == "__main__":
    unittest.main()
