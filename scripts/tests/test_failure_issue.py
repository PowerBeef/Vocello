"""Scheduled-workflow failure reporter (scripts/ci/failure_issue.py)."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/ci/failure_issue.py"
SPEC = importlib.util.spec_from_file_location("failure_issue", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

# The exact shape GitHub renders for toJSON(needs), as seen in the nightly log.
NEEDS = json.dumps({
    "tsan": {"result": "success", "outputs": {}},
    "python-full": {"result": "failure", "outputs": {}},
    "foundation-cold": {"result": "skipped", "outputs": {}},
})


class FakeGh:
    def __init__(self, existing: str = "", label_exists: bool = False) -> None:
        self.calls: list[list[str]] = []
        self.existing = existing
        self.label_exists = label_exists

    def __call__(self, arguments: list[str]) -> str:
        self.calls.append(arguments)
        if arguments[:2] == ["issue", "list"]:
            return self.existing + "\n"
        if arguments[:2] == ["label", "create"] and self.label_exists:
            raise subprocess.CalledProcessError(1, ["gh", *arguments])
        return ""


class IssueBodyTests(unittest.TestCase):
    def test_body_lists_every_needed_job_in_order(self) -> None:
        body = MODULE.issue_body(NEEDS, "https://example.invalid/run/1", "Nightly run failed")
        self.assertEqual(body, "Nightly run failed: https://example.invalid/run/1\n\nJob results:\n"
                               "- tsan: success\n- python-full: failure\n- foundation-cold: skipped")

    def test_missing_result_reads_unknown(self) -> None:
        body = MODULE.issue_body(json.dumps({"tsan": {}}), "u", "h")
        self.assertIn("- tsan: unknown", body)

    def test_malformed_results_fail_closed(self) -> None:
        for value in ("", "not json", "[]", "{}", "3"):
            with self.subTest(value=value):
                with self.assertRaises((ValueError, json.JSONDecodeError)):
                    MODULE.issue_body(value, "u", "h")


class ReportTests(unittest.TestCase):
    def test_an_open_issue_gets_a_comment_and_nothing_is_created(self) -> None:
        gh = FakeGh(existing="42")
        self.assertEqual(MODULE.report("o/r", "nightly", "Nightly lane failing", "body", gh=gh), "commented on #42")
        self.assertEqual([call[:2] for call in gh.calls], [["issue", "list"], ["issue", "comment"]])
        self.assertIn("42", gh.calls[1])

    def test_without_an_open_issue_the_label_and_issue_are_created(self) -> None:
        gh = FakeGh()
        self.assertEqual(MODULE.report("o/r", "nightly", "Nightly lane failing", "body", gh=gh), "created an issue")
        self.assertEqual([call[:2] for call in gh.calls],
                         [["issue", "list"], ["label", "create"], ["issue", "create"]])
        create = gh.calls[-1]
        self.assertEqual(create[create.index("--label") + 1], "nightly")
        self.assertEqual(create[create.index("--title") + 1], "Nightly lane failing")

    def test_an_existing_label_is_tolerated(self) -> None:
        gh = FakeGh(label_exists=True)
        self.assertEqual(MODULE.report("o/r", "nightly", "t", "b", gh=gh), "created an issue")


class CommandLineTests(unittest.TestCase):
    def run_cli(self, results: str, *extra: str) -> subprocess.CompletedProcess:
        env = dict(os.environ, RESULTS=results, RUN_URL="https://example.invalid/run/7")
        env.pop("GITHUB_REPOSITORY", None)
        return subprocess.run([sys.executable, str(SCRIPT), "--label", "nightly", "--title", "t",
                               "--heading", "Nightly run failed", *extra],
                              capture_output=True, text=True, env=env, timeout=30)

    def test_dry_run_prints_the_body_without_gh(self) -> None:
        result = self.run_cli(NEEDS, "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("- python-full: failure", result.stdout)

    def test_malformed_results_exit_nonzero(self) -> None:
        result = self.run_cli("{", "--dry-run")
        self.assertEqual(result.returncode, 1)
        self.assertIn("failure_issue:", result.stderr)

    def test_a_missing_repository_refuses_to_call_gh(self) -> None:
        result = self.run_cli(NEEDS)
        self.assertEqual(result.returncode, 1)
        self.assertIn("GITHUB_REPOSITORY", result.stderr)


if __name__ == "__main__":
    unittest.main()
