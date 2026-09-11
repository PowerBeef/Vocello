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


if __name__ == "__main__":
    unittest.main()
