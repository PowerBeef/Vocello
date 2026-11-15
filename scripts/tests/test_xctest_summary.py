#!/usr/bin/env python3
"""Tests for scripts/lib/xctest_summary.py, the one test-results.json writer for every lane."""

from __future__ import annotations

import contextlib
import io
import json
import os
import pathlib
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))

import xctest_summary as summary  # noqa: E402

XCTEST_LOG = """\
Test Suite 'All tests' started at 2026-09-11 04:32:19.001.
Test Case '-[VocelloCoreTests.AlphaTests testOne]' started.
Test Case '-[VocelloCoreTests.AlphaTests testOne]' passed (0.012 seconds).
Test Case '-[VocelloCoreTests.AlphaTests testTwo]' started.
/path/AlphaTests.swift:12: error: -[VocelloCoreTests.AlphaTests testTwo] : XCTAssertEqual failed
Test Case '-[VocelloCoreTests.AlphaTests testTwo]' failed (0.300 seconds).
Test Suite 'AlphaTests' passed at 2026-09-11 04:32:19.400.
\t Executed 2 tests, with 1 failure (0 unexpected) in 0.312 (0.320) seconds
Test Suite 'All tests' failed at 2026-09-11 04:32:19.401.
\t Executed 2 tests, with 1 failure (0 unexpected) in 0.312 (0.321) seconds
"""

SWIFT_TEST_LOG = """\
Test Suite 'All tests' started at 2026-09-11 04:33:59.000.
Test Case '-[Qwen3RuntimeTests.ParityTests testFixture]' started.
/path/ParityTests.swift:20: Test skipped - fixtures unset
Test Case '-[Qwen3RuntimeTests.ParityTests testFixture]' skipped (0.001 seconds).
Test Case '-[Qwen3RuntimeTests.ParityTests testMath]' started.
Test Case '-[Qwen3RuntimeTests.ParityTests testMath]' passed (0.050 seconds).
Test Suite 'ParityTests' passed at 2026-09-11 04:34:00.000.
\t Executed 2 tests, with 1 test skipped and 0 failures (0 unexpected) in 0.051 (0.052) seconds
Test Suite 'All tests' passed at 2026-09-11 04:34:00.001.
\t Executed 2 tests, with 1 test skipped and 0 failures (0 unexpected) in 0.051 (0.053) seconds
"""


class SummarizeTests(unittest.TestCase):
    def test_xctest_log_counts_passed_and_failed_and_checks_the_trailer(self):
        payload = summary.summarize(XCTEST_LOG)
        self.assertEqual(payload["schemaVersion"], 1)
        self.assertEqual([t["test"] for t in payload["tests"]], ["testOne", "testTwo"])
        self.assertEqual(payload["counts"], {"passed": 1, "failed": 1, "skipped": 0, "total": 2})
        self.assertEqual(payload["executed"], {"total": 2, "skipped": 0, "failureAssertions": 1})
        self.assertTrue(payload["consistent"])

    def test_swift_test_log_counts_skipped_cases_from_the_skipped_clause(self):
        payload = summary.summarize(SWIFT_TEST_LOG)
        self.assertEqual(payload["counts"], {"passed": 1, "failed": 0, "skipped": 1, "total": 2})
        self.assertEqual(payload["executed"], {"total": 2, "skipped": 1, "failureAssertions": 0})
        self.assertTrue(payload["consistent"])

    def test_multi_bundle_log_sums_each_bundle_total(self):
        payload = summary.summarize(XCTEST_LOG + SWIFT_TEST_LOG)
        self.assertEqual(payload["counts"]["total"], 4)
        self.assertEqual(payload["executed"], {"total": 4, "skipped": 1, "failureAssertions": 1})
        self.assertTrue(payload["consistent"])

    def test_truncated_log_is_flagged_inconsistent(self):
        truncated = XCTEST_LOG.replace(
            "Test Case '-[VocelloCoreTests.AlphaTests testTwo]' failed (0.300 seconds).\n", "")
        payload = summary.summarize(truncated)
        self.assertFalse(payload["consistent"])

    def test_log_without_trailer_has_no_consistency_claim(self):
        payload = summary.summarize("Test Case '-[A.B c]' passed (0.100 seconds).\n")
        self.assertNotIn("consistent", payload)
        self.assertEqual(payload["counts"]["total"], 1)

    def test_strict_summary_requires_nonempty_terminal_run(self):
        for text in ("", "warning: no tests", "Test Case '-[A.B c]' passed (0.100 seconds).\n",
                     XCTEST_LOG.replace("Test Suite 'All tests' failed", "Test Suite 'Nested tests' failed"),
                     XCTEST_LOG + "Test Suite 'All tests' started at later\n"):
            with self.subTest(text=text):
                self.assertFalse(summary.summarize(text, require_complete=True)["consistent"])

    def test_strict_summary_accepts_all_selected_and_product_failure(self):
        for text in (XCTEST_LOG, SWIFT_TEST_LOG, XCTEST_LOG.replace("All tests", "Selected tests")):
            with self.subTest(text=text):
                payload = summary.summarize(text, require_complete=True)
                self.assertTrue(payload["complete"])
                self.assertTrue(payload["consistent"])


class WriteSummaryTests(unittest.TestCase):
    def test_write_summary_emits_sorted_json_and_exit_codes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            log = root / "core.log"
            out = root / "nested" / "core.test-results.json"
            log.write_text(XCTEST_LOG, encoding="utf-8")
            self.assertEqual(summary.write_summary(log, out, quiet=True), 0)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(payload["source"], str(log))
            self.assertEqual(payload["tests"][1]["verdict"], "failed")
            log.write_text(XCTEST_LOG.replace("Executed 2 tests, with 1 failure (0 unexpected) in 0.312 (0.321)",
                                              "Executed 3 tests, with 1 failure (0 unexpected) in 0.312 (0.321)"),
                           encoding="utf-8")
            self.assertEqual(summary.write_summary(log, out, quiet=True), 3)

    def test_main_reports_a_missing_log(self):
        with tempfile.TemporaryDirectory() as temp:
            missing = pathlib.Path(temp) / "nope.log"
            self.assertEqual(summary.main([str(missing), str(pathlib.Path(temp) / "o.json")]), 2)

    def test_cli_strict_mode_retains_partial_results_and_fails_collection(self):
        with tempfile.TemporaryDirectory() as temp:
            log, out = pathlib.Path(temp) / "partial.log", pathlib.Path(temp) / "out.json"
            log.write_text("Test Case '-[A.B c]' passed (0.100 seconds).\n", encoding="utf-8")
            self.assertEqual(summary.main([str(log), str(out), "--quiet", "--require-complete"]), 3)
            payload = json.loads(out.read_text())
            self.assertEqual(payload["counts"]["passed"], 1)
            self.assertFalse(payload["complete"])


# `swift test` of the owned package: XCTest cases, then Swift Testing's banner, verdicts and trailer.
SWIFT_TESTING_LOG = SWIFT_TEST_LOG + """↳ Testing Library Version: 2084
◇ Suite "Frames" started.
✔ Test "Sizes survive the trip" with 512 test cases passed after 0.004 seconds.
✘ Test atLeastOneFrame(seconds:) with 4 test cases failed after 0.002 seconds with 1 issue.
➜ Test "Needs fixtures" skipped: "fixtures unset"
✘ Suite "Frames" failed after 0.006 seconds with 1 issue.
✘ Test run with 3 tests in 1 suite failed after 0.006 seconds with 1 issue.
"""


class SwiftTestingTests(unittest.TestCase):
    """Swift Testing results are counted, and a run whose library started must end with its trailer."""

    def test_swift_testing_verdicts_join_the_tests(self):
        payload = summary.summarize(SWIFT_TESTING_LOG, require_complete=True)
        swift = [t for t in payload["tests"] if t["suite"] == "swift-testing"]
        self.assertEqual([(t["test"], t["verdict"]) for t in swift], [
            ("Sizes survive the trip", "passed"),
            ("atLeastOneFrame(seconds:)", "failed"),
            ("Needs fixtures", "skipped"),
        ])
        self.assertEqual(swift[0]["cases"], 512)
        self.assertEqual(payload["counts"], {"passed": 2, "failed": 1, "skipped": 2, "total": 5})
        self.assertEqual(payload["swiftTesting"], {"total": 3, "trailers": 1, "tests": 3})
        self.assertTrue(payload["complete"])
        self.assertTrue(payload["consistent"])  # XCTest's trailer still matches its own two cases

    def test_a_started_run_without_its_trailer_is_incomplete(self):
        truncated = SWIFT_TESTING_LOG.rsplit("✘ Test run with", 1)[0]
        payload = summary.summarize(truncated, require_complete=True)
        self.assertFalse(payload["complete"])
        self.assertFalse(payload["consistent"])

    def test_a_trailer_count_that_disagrees_is_inconsistent(self):
        payload = summary.summarize(SWIFT_TESTING_LOG.replace("with 3 tests in", "with 4 tests in"))
        self.assertFalse(payload["consistent"])

    def test_a_log_without_swift_testing_is_unchanged(self):
        payload = summary.summarize(SWIFT_TEST_LOG, require_complete=True)
        self.assertNotIn("swiftTesting", payload)
        self.assertTrue(payload["complete"])
        self.assertTrue(payload["consistent"])


ROOT = pathlib.Path(__file__).resolve().parents[2]
LANE_CONFIG = ROOT / "config" / "ui-lane-tests.json"
MAC_UI_TESTS = ROOT / "Tests" / "VocelloMacUITests"
# The XCTest class each lane of config/ui-lane-tests.json runs in full (scripts/ui_test.sh).
LANE_CLASSES = {
    "macos-smoke": "VocelloMacSmokeUITests",
    "macos-perf": "VocelloMacPerfUITests",
    "macos-benchmark": "VocelloMacBenchmarkUITests",
}
SWIFT_TYPE = re.compile(r"^(?:[a-z@()]+\s+)*(?:class|extension|struct|enum|actor|protocol)\s+(\w+)")
SWIFT_TEST_METHOD = re.compile(r"^\s+func (test\w*)\s*\(\s*\)")


def swift_test_methods(directory: pathlib.Path) -> dict[str, list[str]]:
    """The `test…()` methods of each top-level type, its extensions included."""
    methods: dict[str, list[str]] = {}
    for path in sorted(directory.glob("*.swift")):
        current = None
        for line in path.read_text(encoding="utf-8").splitlines():
            if match := SWIFT_TYPE.match(line):
                current = match.group(1)
            elif current and (match := SWIFT_TEST_METHOD.match(line)):
                methods.setdefault(current, []).append(match.group(1))
    return methods


def lane_log(cases: list[tuple[str, str]]) -> str:
    """A complete `Selected tests` log of (Suite/method, verdict) cases."""
    lines = ["Test Suite 'Selected tests' started at 2026-11-15 10:00:00.000."]
    for identifier, verdict in cases:
        suite, test = identifier.split("/")
        lines.append(f"Test Case '-[VocelloMacUITests.{suite} {test}]' started.")
        lines.append(f"Test Case '-[VocelloMacUITests.{suite} {test}]' {verdict} (1.000 seconds).")
    skipped = sum(1 for _, verdict in cases if verdict == "skipped")
    failed = sum(1 for _, verdict in cases if verdict == "failed")
    skipped_clause = f"{skipped} test{'s' if skipped != 1 else ''} skipped and " if skipped else ""
    lines.append(f"Test Suite 'Selected tests' {'failed' if failed else 'passed'} at 2026-11-15 10:30:00.000.")
    lines.append(
        f"\t Executed {len(cases)} tests, with {skipped_clause}{failed} failures (0 unexpected) in 1.0 (1.1) seconds"
    )
    return "\n".join(lines) + "\n"


class ExpectedLaneTests(unittest.TestCase):
    """RF-61, audit T10: a lane's full run must contain the lane's tests, none skipped."""

    def run_summary(self, cases, *arguments: str) -> tuple[int, dict | None, str]:
        with tempfile.TemporaryDirectory() as temp:
            log, out = pathlib.Path(temp) / "xcodebuild.log", pathlib.Path(temp) / "test-results.json"
            log.write_text(lane_log(cases), encoding="utf-8")
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                status = summary.main([str(log), str(out), "--quiet", "--require-complete", *arguments])
            payload = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else None
            return status, payload, stderr.getvalue()

    def test_the_config_lists_exactly_the_test_methods_in_the_swift_sources(self):
        """A renamed, added or deleted journey must change config/ui-lane-tests.json with it."""
        config = json.loads(LANE_CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(config["schemaVersion"], 1)
        self.assertEqual(set(config["lanes"]), set(LANE_CLASSES))
        methods = swift_test_methods(MAC_UI_TESTS)
        for lane, suite in LANE_CLASSES.items():
            with self.subTest(lane=lane):
                self.assertTrue(methods.get(suite), f"no test methods found for {suite}")
                self.assertEqual(config["lanes"][lane], [f"{suite}/{name}" for name in sorted(methods[suite])])
                self.assertEqual(summary.expected_tests(LANE_CONFIG, lane), config["lanes"][lane])
        # The parser reads one class's methods, not its neighbours in the same file.
        self.assertEqual(methods["VocelloMacAutoLanguageUITests"], ["testAutoLanguageReachesTheEngine"])
        self.assertEqual(len(config["lanes"]["macos-smoke"]), 16)
        self.assertEqual(config["lanes"]["macos-benchmark"], ["VocelloMacBenchmarkUITests/testOrderedConfigurableMatrix"])

    def test_a_full_run_of_every_expected_test_passes(self):
        for lane in LANE_CLASSES:
            with self.subTest(lane=lane):
                expected = summary.expected_tests(LANE_CONFIG, lane)
                status, payload, stderr = self.run_summary(
                    [(name, "passed") for name in expected], "--expect-lane", lane)
                self.assertEqual((status, stderr), (0, ""))
                self.assertEqual(payload["expected"], {
                    "lane": lane, "count": len(expected), "missing": [], "skipped": [], "met": True})

    def test_a_missing_journey_fails_the_lane(self):
        expected = summary.expected_tests(LANE_CONFIG, "macos-smoke")
        deleted = "VocelloMacSmokeUITests/test15_ModelUpdateFromAnEarlierVocello"
        cases = [(name, "passed") for name in expected if name != deleted]
        status, payload, stderr = self.run_summary(cases, "--expect-lane", "macos-smoke")
        # The log is complete and consistent; only the expectation fails it.
        self.assertTrue(payload["consistent"])
        self.assertEqual(status, summary.EXIT_EXPECTED_TESTS)
        self.assertEqual((payload["expected"]["missing"], payload["expected"]["skipped"]), ([deleted], []))
        self.assertFalse(payload["expected"]["met"])
        self.assertIn(f"expected macos-smoke test missing: {deleted}", stderr)
        # A renamed journey is a missing one too.
        renamed = [*cases, ("VocelloMacSmokeUITests/test15_ModelUpdate", "passed")]
        self.assertEqual(self.run_summary(renamed, "--expect-lane", "macos-smoke")[0], summary.EXIT_EXPECTED_TESTS)

    def test_a_skipped_journey_fails_the_lane(self):
        expected = summary.expected_tests(LANE_CONFIG, "macos-perf")
        skipped = expected[3]
        cases = [(name, "skipped" if name == skipped else "passed") for name in expected]
        status, payload, stderr = self.run_summary(cases, "--expect-lane", "macos-perf")
        self.assertTrue(payload["consistent"])
        self.assertEqual(status, summary.EXIT_EXPECTED_TESTS)
        self.assertEqual((payload["expected"]["missing"], payload["expected"]["skipped"]), ([], [skipped]))
        self.assertIn(f"expected macos-perf test skipped: {skipped}", stderr)

    def test_a_failed_test_ran_and_a_focused_run_checks_nothing(self):
        expected = summary.expected_tests(LANE_CONFIG, "macos-smoke")
        # A failing journey is the run's own failure, not a missing test.
        cases = [(name, "failed" if index == 2 else "passed") for index, name in enumerate(expected)]
        status, payload, _ = self.run_summary(cases, "--expect-lane", "macos-smoke")
        self.assertEqual((status, payload["expected"]["met"]), (0, True))
        # `--scenario layout` runs one journey; without --expect-lane it stays a pass.
        status, payload, _ = self.run_summary([(expected[0], "passed")])
        self.assertEqual(status, 0)
        self.assertNotIn("expected", payload)
        # The same subset is refused as a full run.
        self.assertEqual(
            self.run_summary([(expected[0], "passed")], "--expect-lane", "macos-smoke")[0],
            summary.EXIT_EXPECTED_TESTS,
        )

    def test_an_inconsistent_log_keeps_its_own_exit_code(self):
        expected = summary.expected_tests(LANE_CONFIG, "macos-benchmark")
        with tempfile.TemporaryDirectory() as temp:
            log, out = pathlib.Path(temp) / "xcodebuild.log", pathlib.Path(temp) / "out.json"
            # Truncated before the trailer, and the expected test never reported.
            log.write_text("Test Suite 'Selected tests' started at 2026-11-15 10:00:00.000.\n", encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                status = summary.main([str(log), str(out), "--quiet", "--require-complete",
                                       "--expect-lane", "macos-benchmark"])
            self.assertEqual(status, summary.EXIT_INCONSISTENT)
            self.assertEqual(json.loads(out.read_text())["expected"]["missing"], expected)

    def test_an_unknown_lane_or_a_malformed_config_is_refused(self):
        cases = [("VocelloMacBenchmarkUITests/testOrderedConfigurableMatrix", "passed")]
        status, payload, stderr = self.run_summary(cases, "--expect-lane", "macos-marketing")
        self.assertEqual((status, payload), (2, None))
        self.assertIn("lists no lane 'macos-marketing'", stderr)
        with tempfile.TemporaryDirectory() as temp:
            config = pathlib.Path(temp) / "lanes.json"
            for text in (
                "{not json",
                json.dumps({"schemaVersion": 2, "lanes": {"lane": ["A/b"]}}),
                json.dumps({"schemaVersion": 1, "lanes": {"lane": []}}),
                json.dumps({"schemaVersion": 1, "lanes": {"lane": ["A/b", "A/b"]}}),
                json.dumps({"schemaVersion": 1, "lanes": {"lane": ["no-suite"]}}),
            ):
                config.write_text(text, encoding="utf-8")
                with self.subTest(text=text):
                    status, payload, _ = self.run_summary(
                        cases, "--expect-lane", "lane", "--expect-config", str(config))
                    self.assertEqual((status, payload), (2, None))
            self.assertEqual(self.run_summary(
                cases, "--expect-lane", "lane", "--expect-config", str(config.with_name("absent.json")))[0], 2)


if __name__ == "__main__":
    unittest.main()
