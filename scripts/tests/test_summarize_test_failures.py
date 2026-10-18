"""CI failing-test reporter (scripts/ci/summarize_test_failures.py)."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/ci/summarize_test_failures.py"
SPEC = importlib.util.spec_from_file_location("summarize_test_failures", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def write_results(run: Path, name: str, tests: list[dict], *, complete: bool = True) -> None:
    run.mkdir(parents=True, exist_ok=True)
    (run / f"{name}.test-results.json").write_text(json.dumps({
        "complete": complete, "consistent": True, "schemaVersion": 1, "tests": tests,
    }))


class SummarizeTestFailuresTests(unittest.TestCase):
    def test_names_each_failing_test(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "mac-test-1"
            write_results(run, "core", [
                {"suite": "StoreTests", "test": "testA", "verdict": "passed"},
                {"suite": "StoreTests", "test": "testB", "verdict": "failed"},
            ])
            summary, annotations = MODULE.render("macOS deterministic", Path(tmp))
        self.assertIn("1 failing test(s)", summary)
        self.assertIn("`StoreTests.testB`", summary)
        self.assertEqual(annotations, ["::error title=macOS deterministic test failed::StoreTests.testB"])

    def test_incomplete_results_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_results(Path(tmp) / "run", "runtime", [], complete=False)
            summary, _ = MODULE.render("lane", Path(tmp))
        self.assertIn("incomplete or inconsistent", summary)

    def test_build_errors_when_no_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "run"
            run.mkdir()
            (run / "xcode-test-build.log").write_text(
                "CompileSwift\n/src/A.swift:3:1: error: cannot find 'x' in scope\n")
            summary, annotations = MODULE.render("lane", Path(tmp))
        self.assertIn("build failed", summary)
        self.assertIn("cannot find 'x' in scope", summary)
        self.assertEqual(len(annotations), 1)

    def test_nothing_written_is_said_plainly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary, annotations = MODULE.render("lane", Path(tmp))
        self.assertIn("no test results were written", summary)
        self.assertEqual(annotations, [])

    def test_long_lists_are_capped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests = [{"suite": "S", "test": f"t{i}", "verdict": "failed"} for i in range(55)]
            write_results(Path(tmp) / "run", "core", tests)
            summary, annotations = MODULE.render("lane", Path(tmp))
        self.assertIn("55 failing test(s)", summary)
        self.assertIn("and 15 more", summary)
        self.assertEqual(len(annotations), MODULE.MAX_LISTED)


if __name__ == "__main__":
    unittest.main()
