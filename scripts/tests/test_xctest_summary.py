#!/usr/bin/env python3
"""Tests for scripts/lib/xctest_summary.py, the one test-results.json writer for every lane."""

from __future__ import annotations

import json
import os
import pathlib
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


if __name__ == "__main__":
    unittest.main()
