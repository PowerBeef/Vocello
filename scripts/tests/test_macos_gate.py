#!/usr/bin/env python3
"""Outcome and ledger behaviour of `scripts/macos_test.sh gate`.

The real `cmd_gate` and `gate_finish` functions run against the real
required-step ledger and orchestration contract, with every step they call
(project inputs, the foundation build, the tests, the crash delta, the bench
preflight, the bench and history publication) replaced by a stub. Nothing
builds, loads a model or runs a lane.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "macos_test.sh"


def shell_function(text: str, name: str) -> str:
    start = text.index(f"{name}() {{\n")
    end = text.index("\n}\n", start) + 3
    return text[start:end]


class MacGateOrchestrationTests(unittest.TestCase):
    def run_gate(self, *, bench: bool = False, seed: bool = False, preflight: int = 0,
                 tests: int = 0, bench_status: int = 0,
                 real_preflight: bool = False) -> tuple[int, dict, set[str], str]:
        source = SCRIPT.read_text(encoding="utf-8")
        names = ["gate_finish", "cmd_gate"] + (["gate_bench_preflight"] if real_preflight else [])
        functions = "\n".join(shell_function(source, name) for name in names)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stubs = root / "stubs"
            stubs.mkdir()
            marks = root / "marks"
            marks.mkdir()
            for name in ("check_project_inputs.sh", "build_foundation_targets.sh"):
                stub = stubs / name
                stub.write_text(f"#!/bin/sh\ntouch {shlex.quote(str(marks / name))}\n", encoding="utf-8")
                stub.chmod(0o755)
            for name in ("publish_benchmark_history.py", "summarize_generation_telemetry.py"):
                (stubs / name).write_text(
                    "import sys\n"
                    "if '--output' in sys.argv:\n"
                    "    open(sys.argv[sys.argv.index('--output') + 1], 'w').write('{}')\n",
                    encoding="utf-8",
                )
            if real_preflight:
                # The real preflight: a quiet host, then a model helper that exits
                # the shell the way `_test_models_die` does.
                preflight_definition = (
                    "require_quiet_host() { return 0; }\n"
                    "require_mac_benchmark_models() {\n"
                    "  touch \"$MARKS/preflight\"; echo \"benchmark model missing: pro_custom_speed\"; exit 1\n"
                    "}\n"
                    "GATE_BENCH_MODEL=pro_custom_speed GATE_BENCH_MODES=custom GATE_BENCH_VARIANTS=speed\n"
                    "GATE_BENCH_LENGTHS=medium GATE_BENCH_WARM=5 GATE_BENCH_SEED=19790615\n"
                    "GATE_BENCH_BASELINE=/nonexistent GATE_BENCH_STAGED_BASELINE=/nonexistent\n"
                )
            else:
                preflight_definition = (
                    f'gate_bench_preflight() {{ touch "$MARKS/preflight"; return {preflight}; }}\n'
                )
            script = f"""
set -euo pipefail
ROOT_DIR={shlex.quote(str(REPO))}
. "$ROOT_DIR/scripts/lib/shared.sh"
. "$ROOT_DIR/scripts/lib/required_steps.sh"
SCRIPT_DIR={shlex.quote(str(stubs))}
QVOICE_ARTIFACTS_MACOS={shlex.quote(str(root / "artifacts"))}
MARKS={shlex.quote(str(marks))}
{preflight_definition}
cmd_test() {{ touch "$MARKS/tests"; return {tests}; }}
gate_crash_delta() {{ touch "$MARKS/crash-delta"; }}
run_gate_bench() {{ touch "$MARKS/bench"; return {bench_status}; }}
record_benchmark_history() {{ touch "$MARKS/history"; }}
{functions}
cmd_gate
"""
            environment = {
                key: value for key, value in os.environ.items()
                if not key.startswith(("QWENVOICE_", "QVOICE_"))
            }
            if bench:
                environment["QWENVOICE_GATE_BENCH"] = "1"
            if seed:
                environment["QWENVOICE_GATE_BENCH_SEED"] = "1"
            completed = subprocess.run(
                ["bash", "-c", script], text=True, capture_output=True, env=environment,
                check=False, timeout=120,
            )
            [ledger_path] = list((root / "artifacts" / "gates").glob("gate-*/required-steps.json"))
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


class MacGateBenchWiringTests(unittest.TestCase):
    """The real `run_gate_bench` with the gate's own matrix settings, over a
    stub CLI and stub summarizers that record how they were called."""

    def run_bench(self, *, seeding: bool) -> tuple[int, list[str], list[list[str]], str]:
        source = SCRIPT.read_text(encoding="utf-8")
        settings = "\n".join(
            line for line in source.splitlines() if line.startswith("GATE_BENCH_")
        )
        functions = "\n".join(
            shell_function(source, name) for name in ("gate_bench_seed_hint", "run_gate_bench")
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scripts = root / "scripts"
            scripts.mkdir()
            calls = root / "calls.jsonl"
            build = scripts / "build.sh"
            build.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            build.chmod(0o755)
            recorder = (
                "import json, sys\n"
                f"open({str(calls)!r}, 'a').write(json.dumps(sys.argv) + '\\n')\n"
            )
            for name in ("publish_benchmark_history.py", "summarize_generation_telemetry.py"):
                (scripts / name).write_text(recorder, encoding="utf-8")
            build_root = root / "build"
            build_root.mkdir()
            vocello = build_root / "vocello"
            vocello.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, sys\n"
                f"open({str(calls)!r}, 'a').write(json.dumps(sys.argv) + '\\n')\n"
                "diagnostics = os.path.join(sys.argv[sys.argv.index('--data-dir') + 1], 'diagnostics')\n"
                "os.makedirs(os.path.join(diagnostics, 'engine'))\n"
                "open(os.path.join(diagnostics, 'engine', 'generations.jsonl'), 'w')"
                ".write(json.dumps({'generationID': 'g', 'audioQC': {'verdict': 'pass'}}) + '\\n')\n"
                "open(os.path.join(diagnostics, 'bench-results.json'), 'w').write('{}')\n",
                encoding="utf-8",
            )
            vocello.chmod(0o755)
            gate_dir = root / "gate"
            gate_dir.mkdir()
            script = f"""
set -euo pipefail
. {shlex.quote(str(REPO / "scripts" / "lib" / "shared.sh"))}
ROOT_DIR={shlex.quote(str(root))}
SCRIPT_DIR="$ROOT_DIR/scripts"
QVOICE_BUILD_ROOT={shlex.quote(str(build_root))}
QVOICE_ARTIFACTS_MACOS={shlex.quote(str(root / "artifacts"))}
{settings}
GATE_BENCH_BASELINE="$ROOT_DIR/no-committed-baseline.json"
gate_bench_quiet_host() {{ return 0; }}
require_mac_benchmark_models() {{ return 0; }}
debug_models_dir() {{ echo "$ROOT_DIR/models"; }}
capture_benchmark_source() {{ return 0; }}
{functions}
run_gate_bench {shlex.quote(str(gate_dir))} {1 if seeding else 0}
"""
            environment = {
                key: value for key, value in os.environ.items()
                if not key.startswith(("QWENVOICE_", "QVOICE_"))
            }
            completed = subprocess.run(
                ["bash", "-c", script], text=True, capture_output=True, env=environment,
                check=False, timeout=60,
            )
            recorded = [
                json.loads(line) for line in calls.read_text(encoding="utf-8").splitlines()
            ] if calls.exists() else []
            [bench] = [call for call in recorded if Path(call[0]).name == "vocello"]
            summaries = [
                call for call in recorded if Path(call[0]).name == "summarize_generation_telemetry.py"
            ]
            log = (gate_dir / "bench.log").read_text(encoding="utf-8")
            return completed.returncode, bench, summaries, log

    @staticmethod
    def option(arguments: list[str], name: str) -> str:
        return arguments[arguments.index(name) + 1]

    def test_the_gate_bench_runs_five_seeded_warm_takes(self) -> None:
        status, bench, _summaries, log = self.run_bench(seeding=False)
        self.assertEqual(status, 0, log)
        self.assertEqual(self.option(bench, "--warm"), "5")
        self.assertEqual(self.option(bench, "--seed"), "19790615")
        # Without a committed baseline the printed seed command asks for the same count.
        self.assertIn("--seed-minimum-takes 5", log)

    def test_seeding_requires_every_warm_cell_to_carry_the_gates_take_count(self) -> None:
        status, bench, summaries, log = self.run_bench(seeding=True)
        self.assertEqual(status, 0, log)
        [seed] = [call for call in summaries if "--seed-baseline" in call]
        self.assertEqual(self.option(seed, "--seed-minimum-takes"), self.option(bench, "--warm"))
        self.assertIn("BASELINE SEEDED", log)


if __name__ == "__main__":
    unittest.main()
