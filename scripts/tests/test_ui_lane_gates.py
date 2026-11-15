#!/usr/bin/env python3
"""What scripts/ui_test.sh requires of a passing run, run from the shipped shell (RF-61).

The functions are loaded from the lane script and executed over the real
scripts/lib/xctest_summary.py and config/ui-lane-tests.json (scripts/tests/shell_stubs.py);
nothing builds, launches the app or publishes.
"""

from __future__ import annotations

import json
import unittest

from shell_stubs import ROOT, UIFunctionShell, quote
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
        for arguments in (
            {"scenario": "layout"},                      # a focused macOS smoke run
            {"lane": "localization"},                    # test01 alone, by design
            {"lane": "auto-language"},
            {"platform": "ios"},                         # the iPhone lanes list nothing yet
        ):
            with self.subTest(**arguments):
                status, results = self.summarize(one_journey, **arguments)
                self.assertEqual(status, 0)
                self.assertNotIn("expected", results)

    def test_the_collectors_of_a_failed_run_never_apply_the_expectation(self) -> None:
        # A failed or interrupted run legitimately lacks tests; its summary stays evidence.
        status, results = self.summarize([(SMOKE[0], "failed")], final=False)
        self.assertEqual(status, 0)
        self.assertNotIn("expected", results)


if __name__ == "__main__":
    unittest.main()
