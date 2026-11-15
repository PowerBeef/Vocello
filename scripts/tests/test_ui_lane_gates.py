#!/usr/bin/env python3
"""What scripts/ui_test.sh requires of a passing run, run from the shipped shell (RF-61).

The functions are loaded from the lane script and executed over the real
scripts/lib/xctest_summary.py and config/ui-lane-tests.json (scripts/tests/shell_stubs.py);
nothing builds, launches the app or publishes.
"""

from __future__ import annotations

import json
from typing import Any
import unittest

from shell_stubs import ROOT, UIFunctionShell, quote, ui_lane_sandbox
from test_xctest_summary import LANE_CONFIG, lane_log

SMOKE = json.loads(LANE_CONFIG.read_text(encoding="utf-8"))["lanes"]["macos-smoke"]


class ExpectedLaneTestsWiring(unittest.TestCase):
    """audit T10: a full macOS smoke, perf or benchmark run checks which tests ran."""

    def summarize(self, cases: list[tuple[str, str]], *, platform: str = "macos", lane: str = "smoke",
                  scenario: str = "", final: bool = True) -> tuple[int, dict]:
        """Run `write_test_summary` as the lane's last summary (`final`) or as a collector."""
        shell = UIFunctionShell(self)
        out = shell.path / "run"
        out.mkdir()
        (out / "xcodebuild.log").write_text(lane_log(cases), encoding="utf-8")
        completed = shell.run(
            ("write_test_summary", "expected_test_lane"),
            f"ROOT_DIR={quote(ROOT)}\nout={quote(out)}\nplatform={quote(platform)}\nlane={quote(lane)}\n"
            f"scenario_argument={quote(scenario)}\nstatus=0\n"
            f"write_test_summary {'--expect-lane-tests' if final else ''} >/dev/null 2>&1 || status=$?\n"
            'echo "status=$status"\n',
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        status = int(completed.stdout.strip().rsplit("status=", 1)[1])
        return status, json.loads((out / "test-results.json").read_text(encoding="utf-8"))

    def test_a_full_smoke_run_without_one_journey_cannot_pass(self) -> None:
        complete = [(name, "passed") for name in SMOKE]
        status, results = self.summarize(complete)
        self.assertEqual((status, results["expected"]["lane"], results["expected"]["met"]), (0, "macos-smoke", True))
        status, results = self.summarize(complete[:-1])
        self.assertEqual(status, 4)
        self.assertEqual(results["expected"]["missing"], [SMOKE[-1]])
        skipped = [(name, "skipped" if name == SMOKE[4] else "passed") for name in SMOKE]
        status, results = self.summarize(skipped)
        self.assertEqual((status, results["expected"]["skipped"]), (4, [SMOKE[4]]))

    def test_perf_and_benchmark_runs_name_their_own_lane(self) -> None:
        lanes = json.loads(LANE_CONFIG.read_text(encoding="utf-8"))["lanes"]
        for lane in ("perf", "benchmark"):
            with self.subTest(lane=lane):
                expected = lanes[f"macos-{lane}"]
                status, results = self.summarize([(name, "passed") for name in expected], lane=lane)
                self.assertEqual((status, results["expected"]["lane"]), (0, f"macos-{lane}"))
                # The smoke journeys are not this lane's tests.
                status, results = self.summarize([(name, "passed") for name in SMOKE], lane=lane)
                self.assertEqual((status, results["expected"]["missing"]), (4, expected))

    def test_a_scenario_run_and_the_other_lanes_check_nothing(self) -> None:
        one_journey = [(SMOKE[0], "passed")]
        focused_runs: tuple[dict[str, Any], ...] = (
            {"scenario": "layout"},                      # a focused macOS smoke run
            {"lane": "localization"},                    # test01 alone, by design
            {"lane": "auto-language"},
            {"platform": "ios"},                         # the iPhone lanes list nothing yet
        )
        for arguments in focused_runs:
            with self.subTest(**arguments):
                status, results = self.summarize(one_journey, **arguments)
                self.assertEqual(status, 0)
                self.assertNotIn("expected", results)

    def test_the_collectors_of_a_failed_run_never_apply_the_expectation(self) -> None:
        # A failed or interrupted run legitimately lacks tests; its summary stays evidence.
        status, results = self.summarize([(SMOKE[0], "failed")], final=False)
        self.assertEqual(status, 0)
        self.assertNotIn("expected", results)


HISTORY = "scripts/benchmark_history.py"
PUBLISHER = "scripts/publish_benchmark_history.py"
TAKE_FILE = "/tmp/vocello-bench-current-take.json"


class PublicationTests(unittest.TestCase):
    """audit B4: the benchmark and perf lanes say when they will publish, and --no-publish
    keeps the run and its verdict without touching benchmarks/."""

    def lane(self, *arguments: str):
        """The real script up to its first missing input (the sandbox has no Xcode project)."""
        sandbox = ui_lane_sandbox(self)
        sandbox.helper(PUBLISHER, "exit 0")        # verify-hardware: the canonical Mac
        return sandbox, sandbox.run_script(*arguments)

    def test_a_publishing_run_says_so_before_it_does_anything_else(self) -> None:
        for arguments, target in (
            (("macos", "benchmark"), "a passing macos benchmark writes a tracked record"),
            (("ios", "benchmark"), "a passing ios benchmark writes a tracked record"),
            (("macos", "perf"), "a passing macos perf run on the canonical hardware profile writes a tracked record"),
            (("ios", "perf"), "a passing ios perf run on the canonical hardware profile writes a tracked record"),
        ):
            with self.subTest(arguments=arguments):
                sandbox, completed = self.lane(*arguments)
                self.assertEqual(completed.returncode, 1)
                self.assertIn("QwenVoice.xcodeproj", completed.stderr)   # it went on toward the build
                self.assertEqual(completed.stderr.count("this run will publish"), 1)
                self.assertIn(target, completed.stderr)
                self.assertIn("benchmarks/HISTORY.md", completed.stderr)
                # Said before the first preflight, so it is on screen whatever stops the run.
                self.assertLess(
                    completed.stderr.index("this run will publish"), completed.stderr.index("QwenVoice.xcodeproj"))
                self.assertIn("require_build_free_space", sandbox.names())

    def test_no_publish_is_announced_and_only_the_publishing_lanes_accept_it(self) -> None:
        for arguments in (("macos", "benchmark"), ("macos", "perf"), ("ios", "benchmark"), ("ios", "perf")):
            with self.subTest(arguments=arguments):
                _, completed = self.lane(*arguments, "--no-publish")
                self.assertEqual(completed.returncode, 1)
                self.assertIn("QwenVoice.xcodeproj", completed.stderr)
                self.assertNotIn("this run will publish", completed.stderr)
                self.assertIn(
                    f"--no-publish: this {arguments[0]} {arguments[1]} run keeps its artifacts and verdict "
                    "and writes no tracked record", completed.stderr)
        for arguments in (("macos", "smoke"), ("ios", "smoke"), ("macos", "localization"), ("macos", "auto-language")):
            with self.subTest(arguments=arguments):
                sandbox, completed = self.lane(*arguments)
                self.assertNotIn("publish", completed.stderr)              # nothing to announce
                sandbox, completed = self.lane(*arguments, "--no-publish")
                self.assertEqual(completed.returncode, 1)
                self.assertIn("--no-publish is accepted only by the benchmark and perf lanes", completed.stderr)
                # Refused while reading the arguments: no preflight, project or run directory.
                self.assertNotIn("require_build_free_space", sandbox.names())
                self.assertFalse(list(sandbox.build.rglob("run.json")))

    def test_the_usage_text_documents_the_flag(self) -> None:
        completed = ui_lane_sandbox(self).run_script()
        self.assertEqual(completed.returncode, 2)
        for line in ("macos benchmark", "macos perf", "ios benchmark", "ios perf"):
            usage = next(text for text in completed.stderr.splitlines() if f"ui_test.sh {line}" in text)
            self.assertIn("[--no-publish]", usage)
        self.assertIn("`--no-publish` (benchmark and perf, both platforms)", completed.stderr)

    def publish(self, lane: str, *, no_publish: bool, evidence: bool = True):
        """`publish_lane_history` of a passed run, over a recorder that would publish."""
        shell = UIFunctionShell(self)
        shell.helper(HISTORY, "echo benchmarks/runs/fixture/record.json")
        out = shell.path / "run"
        out.mkdir()
        if evidence:
            (out / "benchmark-evidence.json").write_text("{}", encoding="utf-8")
        completed = shell.run(
            ("record_publication_skipped", "publish_lane_history"),
            f"ROOT_DIR={quote(shell.path)}\nout={quote(out)}\nplatform=macos\nlane={quote(lane)}\n"
            f"step_ledger={quote(out / 'required-steps.json')}\nno_publish={int(no_publish)}\n"
            'required_step_run() { qv_record required_step_run "$2"; shift 2; "$@"; }\n'
            "publish_lane_history\n",
        )
        return shell, out, completed

    def test_a_passed_run_publishes_through_the_history_recorder(self) -> None:
        for lane, kind in (("benchmark", "benchmark"), ("perf", "ui-perf")):
            with self.subTest(lane=lane):
                shell, out, completed = self.publish(lane, no_publish=False)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(shell.calls_to(HISTORY), [["record", "--artifact-dir", str(out)]])
                self.assertEqual(shell.calls_to("required_step_run"), [["history-publication"]])
                self.assertIn(f"tracked {kind} record → benchmarks/runs/fixture/record.json", completed.stderr)
                self.assertFalse((out / "publication-skipped.json").exists())

    def test_no_publish_never_calls_the_history_recorder(self) -> None:
        for lane in ("benchmark", "perf"):
            with self.subTest(lane=lane):
                shell, out, completed = self.publish(lane, no_publish=True)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(shell.calls_to(HISTORY), [])
                self.assertEqual(
                    json.loads((out / "publication-skipped.json").read_text(encoding="utf-8")),
                    {"schemaVersion": 1, "published": False, "reason": "--no-publish"},
                )
                self.assertIn("not published (--no-publish)", completed.stderr)
                # The run can still be published by hand from its retained artifacts.
                self.assertIn(f"benchmark_history.py record --artifact-dir '{out}'", completed.stderr)
                # The benchmark workflows require the step, so it runs and records the skip;
                # the perf workflows leave it optional and unrecorded.
                self.assertEqual(
                    shell.calls_to("required_step_run"), [["history-publication"]] if lane == "benchmark" else [])

    def test_a_perf_run_without_evidence_publishes_nothing_either_way(self) -> None:
        # A non-canonical host: the checker emitted no evidence manifest.
        for no_publish in (False, True):
            with self.subTest(no_publish=no_publish):
                shell, out, completed = self.publish("perf", no_publish=no_publish, evidence=False)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(shell.names(), [])
                self.assertFalse((out / "publication-skipped.json").exists())

    def test_a_failed_publication_still_fails_the_run(self) -> None:
        shell = UIFunctionShell(self)                    # the guarded recorder refuses
        out = shell.path / "run"
        out.mkdir()
        completed = shell.run(
            ("record_publication_skipped", "publish_lane_history"),
            f"ROOT_DIR={quote(shell.path)}\nout={quote(out)}\nplatform=macos\nlane=benchmark\n"
            'step_ledger=ledger\nno_publish=0\nrequired_step_run() { shift 2; "$@"; }\npublish_lane_history\n',
        )
        self.assertEqual(completed.returncode, 1)
        self.assertIn("benchmark lane passed, but history publication failed", completed.stderr)


class BenchContextFileTests(unittest.TestCase):
    """audit E11: the app reads the benchmark's current-take file in any telemetry build,
    so the perf lane clears a stale one before its first launch, as the benchmark does."""

    def run_until_preflight(self, lane: str, *arguments: str):
        """The real script up to its UI preflight. `rm` and `pgrep` are stand-ins, so the
        host's rendezvous file and processes are never touched."""
        sandbox = ui_lane_sandbox(self)
        (sandbox.root / "QwenVoice.xcodeproj").mkdir()
        sandbox.helper(PUBLISHER, "exit 0")              # verify-hardware and the provenance snapshot
        sandbox.tool("pgrep", "exit 1")                  # no app to retire
        sandbox.tool("rm", 'case "$*" in *vocello-bench-current-take*) exit 0 ;; esac\nexec /bin/rm "$@"')
        (sandbox.root / "scripts/lib/required_steps.sh").write_text(
            f". {quote(sandbox.record)}\n"
            'required_steps_init() { qv_record required_steps_init "$@"; }\n'
            # Stop where the lane would start driving the app.
            'required_step_run() { qv_record required_step_run "$2"; [[ "$2" != ui-preflight ]] || exit 9; '
            'shift 2; "$@"; }\n'
            'required_step_record() { qv_record required_step_record "$2" "$3"; }\n'
            "required_steps_finalize() { qv_record required_steps_finalize; }\n",
            encoding="utf-8",
        )
        completed = sandbox.run_script("macos", lane, *arguments)
        self.assertEqual(completed.returncode, 9, completed.stderr)
        return sandbox

    def cleared_before_preflight(self, sandbox) -> bool:
        clears = [
            position for position, call in enumerate(sandbox.calls())
            if call == ["rm", "-f", TAKE_FILE, f"{TAKE_FILE}.next"]
        ]
        self.assertTrue(clears, sandbox.calls())         # the run's cleanup clears it at the end
        return clears[0] < sandbox.index("required_step_run", "ui-preflight")

    def test_the_perf_lane_clears_a_stale_current_take_file_at_its_start(self) -> None:
        self.assertTrue(self.cleared_before_preflight(self.run_until_preflight("perf")))
        # The benchmark lane's own clearing, which the perf lane now matches.
        self.assertTrue(self.cleared_before_preflight(self.run_until_preflight("benchmark")))
        # A lane that generates outside the benchmark's cells only clears it on the way out.
        self.assertFalse(self.cleared_before_preflight(self.run_until_preflight("smoke", "--scenario", "layout")))


if __name__ == "__main__":
    unittest.main()
