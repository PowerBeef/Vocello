#!/usr/bin/env python3
"""What scripts/ui_test.sh requires of a passing run, run from the shipped shell (RF-61).

The functions are loaded from the lane script and executed over the real
scripts/lib/xctest_summary.py and config/ui-lane-tests.json (scripts/tests/shell_stubs.py);
nothing builds, launches the app or publishes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
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


CHECKER = "scripts/check_macos_ui_bench.py"
SUMMARIZER = "scripts/summarize_generation_telemetry.py"
REFUSED_LINE = "REFUSED 1 take(s): take 13 (design/short/warm#1)"


class RefusedTakeLaneTests(unittest.TestCase):
    """audit T5: a benchmark whose XCUITest passed around a refused take reaches the
    checker with its log, and the lane's last line names what was refused."""

    def validate(self, gate_output: str, *, checker_status: int = 0):
        """`validate_macos_benchmark` and the lane's last line, over a checker that prints `gate_output`."""
        shell = UIFunctionShell(self)
        shell.helper(CHECKER, f"cat <<'GATE'\n{gate_output}\nGATE\nexit {checker_status}")
        shell.helper(SUMMARIZER, "echo summary")
        out = shell.path / "run"
        out.mkdir()
        (out / "xcodebuild.log").write_text(
            'VOCELLO_BENCH_TAKE_PHASES={"cell":"design/short/warm#1","refused":true,"takeIndex":13}\n',
            encoding="utf-8",
        )
        completed = shell.run(
            ("validate_macos_benchmark", "benchmark_refused_suffix"),
            f"ROOT_DIR={quote(shell.path)}\nout={quote(out)}\nplatform=macos\nlane=benchmark\n"
            "NUMPY_PYTHON=python3\nrun_id=fixture-run\nmodes=custom,design,clone\nlengths=short,medium,long\n"
            "warm=3\nlabel=\nseed_policy=cell-hash-v2\nmatrix_allocation=\nmatrix_version=\n"
            "bench_playback_capture_dir=\nstatus=0\n"
            "validate_macos_benchmark || status=$?\n"
            'echo "validation=$status"\n'
            # The lane's last line, as its PASS branch composes it.
            'echo "$platform $lane PASS$(benchmark_refused_suffix) · $out"\n',
        )
        return shell, out, completed

    def test_the_checker_reads_the_runs_log_and_the_last_line_names_the_refused_cells(self) -> None:
        shell, out, completed = self.validate(
            f"macOS UI bench gate: expected=29 engine=29 app=29 merged=29\n{REFUSED_LINE}\nPASS")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("validation=0", completed.stdout)
        (call,) = shell.calls_to(CHECKER)
        self.assertEqual(call[call.index("--xcodebuild-log") + 1], str(out / "xcodebuild.log"))
        self.assertIn(REFUSED_LINE, (out / "benchmark-gate.txt").read_text(encoding="utf-8"))
        # The refused take's phases line is kept with the others.
        self.assertIn('"refused":true', (out / "take-phases.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(
            completed.stdout.strip().splitlines()[-1],
            f"macos benchmark PASS · {REFUSED_LINE} · exploratory record, never canonical · {out}",
        )

    def test_a_run_without_a_refused_take_ends_as_it_always_did(self) -> None:
        _, out, completed = self.validate("macOS UI bench gate: expected=29 engine=29 app=29 merged=29\nPASS")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip().splitlines()[-1], f"macos benchmark PASS · {out}")

    def test_a_refusal_the_checker_fails_still_fails_the_lane(self) -> None:
        # Above the allowance, or a marked take without its audio-check evidence.
        shell, _, completed = self.validate(f"{REFUSED_LINE}\nFAIL:\n  - 2 take(s) refused", checker_status=1)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("validation=1", completed.stdout)
        self.assertEqual(shell.calls_to(SUMMARIZER), [])

    def test_only_the_macos_benchmark_names_refused_takes(self) -> None:
        shell = UIFunctionShell(self)
        out = shell.path / "run"
        out.mkdir()
        (out / "benchmark-gate.txt").write_text(f"{REFUSED_LINE}\nPASS\n", encoding="utf-8")
        for platform, lane, expected in (
            ("macos", "benchmark", f" · {REFUSED_LINE} · exploratory record, never canonical"),
            ("ios", "benchmark", ""),
            ("macos", "perf", ""),
            ("macos", "smoke", ""),
        ):
            with self.subTest(platform=platform, lane=lane):
                completed = shell.run(
                    ("benchmark_refused_suffix",),
                    f"out={quote(out)}\nplatform={platform}\nlane={lane}\n"
                    'echo "[$(benchmark_refused_suffix)]"\n',
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(completed.stdout.strip(), f"[{expected}]")


class MacCrashDeltaTests(unittest.TestCase):
    """audit step 45: the crash delta reads the app's crash, hang and spin reports,
    and waits a short settle time before the read that decides."""

    ARMED_AT = 1_800_000_000

    def sandbox(self):
        shell = UIFunctionShell(self)
        out = shell.path / "run"
        out.mkdir()
        user = shell.home / "Library/Logs/DiagnosticReports"
        user.mkdir(parents=True)
        system = shell.path / "system-reports"
        system.mkdir()
        marker = out / ".mac-crash-marker"
        marker.write_text("", encoding="utf-8")
        os.utime(marker, (self.ARMED_AT, self.ARMED_AT))
        return shell, out, user, system

    def report(self, directory: Path, name: str, *, seconds_after_arming: int = 10) -> Path:
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("stand-in report", encoding="utf-8")
        os.utime(path, (self.ARMED_AT + seconds_after_arming, self.ARMED_AT + seconds_after_arming))
        return path

    def delta(self, shell, out: Path, system: Path, *, settle: str = "0", before: str = ""):
        (out / "new-crashes.txt").unlink(missing_ok=True)
        completed = shell.run(
            ("check_mac_crash_delta",),
            f"out={quote(out)}\nmac_crash_marker={quote(out / '.mac-crash-marker')}\nstatus=0\n{before}"
            'check_mac_crash_delta || status=$?\necho "status=$status"\n',
            env={"QVOICE_CRASH_DELTA_SETTLE_SECONDS": settle, "QVOICE_SYSTEM_DIAGNOSTIC_REPORTS": str(system)},
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        new = out / "new-crashes.txt"
        return int(completed.stdout.strip().rsplit("status=", 1)[1]), (
            new.read_text(encoding="utf-8").splitlines() if new.exists() else None)

    def test_the_delta_holds_crash_hang_and_spin_reports_of_the_app_only(self) -> None:
        shell, out, user, system = self.sandbox()
        # Reports from before the run, of other processes and of other kinds never count.
        self.report(user, "Vocello-2026-11-01-090000.ips", seconds_after_arming=-60)
        self.report(system, "Vocello_2026-11-01-090000_host.hang", seconds_after_arming=-60)
        self.report(user, "VocelloMacUITests-Runner-2026-11-15-101501.ips")
        self.report(user, "Safari_2026-11-15-101506_host.hang")
        self.report(system, "Vocello_2026-11-15-101505_host.cpu_resource.diag")
        self.assertEqual(self.delta(shell, out, system), (0, None))
        expected = [
            self.report(user, "Vocello-2026-11-15-101500.ips"),
            self.report(user, "Retired/Vocello_2026-11-15-101504_host.crash"),
            self.report(user, "Vocello_2026-11-15-101503_host.spin"),
            self.report(system, "Vocello_2026-11-15-101502_host.hang"),
        ]
        status, new = self.delta(shell, out, system)
        self.assertEqual(status, 1)
        self.assertEqual(sorted(new or []), sorted(str(path) for path in expected))

    def test_each_report_kind_fails_the_delta_by_itself(self) -> None:
        for directory, name in (
            ("user", "Vocello-2026-11-15-101500.ips"),
            ("user", "Vocello_2026-11-15-101503_host.hang"),
            ("system", "Vocello_2026-11-15-101502_host.hang"),
            ("system", "Vocello_2026-11-15-101503_host.spin"),
        ):
            with self.subTest(directory=directory, name=name):
                shell, out, user, system = self.sandbox()
                report = self.report(user if directory == "user" else system, name)
                self.assertEqual(self.delta(shell, out, system), (1, [str(report)]))

    def test_a_report_that_lands_after_the_run_is_caught_by_the_settled_read(self) -> None:
        shell, out, user, system = self.sandbox()
        late = user / "Vocello-2026-11-15-101510.ips"
        # macOS writes the report a moment after the process died: here, one second in.
        write_late = f"( sleep 1; touch {quote(late)} ) &\n"
        os.utime(out / ".mac-crash-marker", None)        # armed now, so the late report is newer
        self.assertEqual(self.delta(shell, out, system, settle="3", before=write_late), (1, [str(late)]))
        # The same report with no settle time is missed: the read came before it landed.
        late.unlink()
        self.assertEqual(self.delta(shell, out, system, settle="0", before=write_late), (0, None))

    def test_a_delta_that_cannot_be_read_fails_closed(self) -> None:
        shell, out, user, system = self.sandbox()
        (out / ".mac-crash-marker").unlink()
        self.assertEqual(self.delta(shell, out, system), (1, ["crash marker was never armed"]))
        shell, out, user, system = self.sandbox()
        user.rmdir()
        self.assertEqual(self.delta(shell, out, system), (1, ["could not inspect macOS crash reports"]))
        # The system directory is read when it is there; its absence is not a failure.
        shell, out, user, system = self.sandbox()
        system.rmdir()
        self.assertEqual(self.delta(shell, out, system), (0, None))


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


class MacLaneSigningTests(unittest.TestCase):
    """BKL-19: the macOS lanes sign their app with the development identity, so a Speech
    Recognition grant survives rebuilds, and a run that would be signed ad hoc and reaches
    that prompt stops before its build with the cause named."""

    FUNCTIONS = ("mac_lane_signing_identity", "mac_lane_requests_speech_recognition", "mac_ui_preflight")
    # The preflight's other probes, answered as a Mac with nothing to report would.
    PROBES = (
        "automationmodetool() { :; }\nioreg() { :; }\nplutil() { :; }\nsqlite3() { return 1; }\n"
    )

    def preflight(self, identity: str, lane: str, scenario: str = "", *, env: dict[str, str] | None = None):
        shell = UIFunctionShell(self)
        return shell.run(
            self.FUNCTIONS,
            f"resolve_dev_signing_identity() {{ printf '%s\\n' {quote(identity)}; }}\n" + self.PROBES
            + f"lane={quote(lane)}\nscenario_argument={quote(scenario)}\n"
            'echo "identity=$(mac_lane_signing_identity)"\nmac_ui_preflight\necho preflight-passed\n',
            env=env,
        )

    def test_the_lane_signs_with_the_development_identity_and_falls_back_to_ad_hoc(self) -> None:
        completed = self.preflight("Apple Development: Fixture (ABCDE12345)", "smoke")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("identity=Apple Development: Fixture (ABCDE12345)", completed.stdout)
        self.assertIn("preflight-passed", completed.stdout)
        self.assertNotIn("ad hoc", completed.stderr)
        # A resolver that answers nothing (a stand-in, a broken keychain) is ad hoc, never empty.
        completed = self.preflight("", "perf")
        self.assertIn("identity=-", completed.stdout)

    def test_an_ad_hoc_run_that_reaches_speech_recognition_stops_with_the_cause(self) -> None:
        for scenario in ("", "design-enrollment", "clone-reference"):
            with self.subTest(scenario=scenario):
                completed = self.preflight("-", "smoke", scenario)
                self.assertNotEqual(completed.returncode, 0)
                self.assertNotIn("preflight-passed", completed.stdout)
                self.assertIn("no Apple Development signing identity", completed.stderr)
                self.assertIn("Speech Recognition", completed.stderr)
                self.assertIn("QVOICE_UI_ALLOW_ADHOC_SIGNING=1", completed.stderr)

    def test_an_ad_hoc_run_elsewhere_or_attended_only_warns(self) -> None:
        cases = (
            ("perf", "", None), ("benchmark", "", None), ("smoke", "layout", None), ("smoke", "long-form", None),
            ("smoke", "", {"QVOICE_UI_ALLOW_ADHOC_SIGNING": "1"}),
        )
        for lane, scenario, env in cases:
            with self.subTest(lane=lane, scenario=scenario, attended=env is not None):
                completed = self.preflight("-", lane, scenario, env=env)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertIn("preflight-passed", completed.stdout)
                self.assertIn("signed ad hoc and its privacy grants last one build", completed.stderr)


class MacBuildLogTests(unittest.TestCase):
    """A failed macOS build-for-testing retains raw xcodebuild output in xcodebuild-build.log
    and mirrors it into xcodebuild.log so triage and lane_ledger can classify build failures."""

    def test_failed_macos_build_retains_build_log_mirrors_xcodebuild_log_and_keeps_exit_code(self) -> None:
        sandbox = ui_lane_sandbox(self)
        (sandbox.root / "QwenVoice.xcodeproj").mkdir()
        sandbox.helper(PUBLISHER, "exit 0")
        sandbox.helper("scripts/lane_ledger.py", "exit 0")
        sandbox.helper("scripts/tree_fingerprint.py", "echo fixture-fingerprint")
        sandbox.helper(
            "scripts/lib/ui_lane_data.py",
            f'if [[ "$1" == "virtual-mic" ]]; then exit 0; fi\n'
            f'exec "$QV_REAL_PYTHON" {quote(ROOT / "scripts/lib/ui_lane_data.py")} "$@"\n',
        )
        sandbox.executable("scripts/clean_build_caches.sh")
        sandbox.tool("pgrep", "exit 1")
        sandbox.tool("automationmodetool", "exit 0")
        sandbox.tool("ioreg", "exit 0")
        sandbox.tool("plutil", "exit 0")
        sandbox.tool("sqlite3", "exit 1")
        sandbox.tool("xcodebuild", "echo 'Xcode 27.2'")
        sandbox.tool("rm", 'case "$*" in *vocello-bench-current-take*) exit 0 ;; esac\nexec /bin/rm "$@"')
        (sandbox.root / "scripts/lib/build_cache.sh").write_text(
            f". {quote(sandbox.record)}\n"
            + "".join(f"qv_stub {name}\n" for name in (
                "require_build_free_space", "require_ios_xcode_platform", "ensure_project_regenerated",
                "ensure_spm_resolved", "write_build_provenance", "warn_if_storage_bloated",
            ))
            + 'xcb_run() { qv_record xcb_run "$@"; echo "CodeSign Sparkle.framework/Versions/B failed" >&2; return 65; }\n',
            encoding="utf-8",
        )
        completed = sandbox.run_script("macos", "smoke", "--scenario", "layout")
        self.assertEqual(completed.returncode, 65, completed.stderr)
        runs = list((sandbox.build / "qvoice_artifacts_ui_tests/macos").glob("macos-xcui-smoke-*"))
        self.assertEqual(len(runs), 1, runs)
        run_dir = runs[0]
        build_log = run_dir / "xcodebuild-build.log"
        xcode_log = run_dir / "xcodebuild.log"
        self.assertTrue(build_log.is_file(), sorted(p.name for p in run_dir.iterdir()))
        self.assertTrue(xcode_log.is_file(), sorted(p.name for p in run_dir.iterdir()))
        self.assertIn("CodeSign Sparkle.framework/Versions/B failed", build_log.read_text(encoding="utf-8"))
        self.assertEqual(xcode_log.read_text(encoding="utf-8"), build_log.read_text(encoding="utf-8"))
        self.assertIn("macOS UI build-for-testing failed", completed.stderr)
        self.assertIn("xcodebuild-build.log", completed.stderr)
        self.assertIn("CodeSign Sparkle.framework/Versions/B failed", completed.stderr)


if __name__ == "__main__":
    unittest.main()
