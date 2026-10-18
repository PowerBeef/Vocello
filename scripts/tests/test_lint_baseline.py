"""The lint baseline fails only on new findings and only ever shrinks."""
from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("lint_baseline", ROOT / "scripts/lint_baseline.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE  # dataclasses resolve string annotations through sys.modules
SPEC.loader.exec_module(MODULE)


def shellcheck_output(*comments: tuple[str, int, int, str]) -> str:
    """shellcheck -f json1, as 0.11.0 prints it."""
    return json.dumps({"comments": [
        {"file": file, "line": line, "endLine": line, "column": 1, "endColumn": 5, "level": "warning",
         "code": code, "message": message, "fix": None}
        for file, line, code, message in comments
    ]})


def ruff_output(root: Path, *items: tuple[str, int, str | None, str]) -> str:
    """ruff check --output-format json, as 0.17.1 prints it (absolute filenames)."""
    return json.dumps([
        {"cell": None, "code": code, "end_location": {"column": 9, "row": row}, "filename": str(root / file),
         "fix": None, "location": {"column": 8, "row": row}, "message": message, "noqa_row": row, "url": None}
        for file, row, code, message in items
    ])


class LintBaselineTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="vocello lint ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.write("scripts/a.sh", "#!/usr/bin/env bash\nunused=1\necho hi\n")
        self.write("scripts/b.py", "import os\nimport sys\n\nprint(sys.argv)\n")

    def write(self, relative: str, text: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def main(self, *argv: str, output: str | None = None, env: dict[str, str] | None = None) -> tuple[int, str, str]:
        args = [*argv, "--root", str(self.root)]
        if output is not None:
            args += ["--input", str(self.write("build/tool-output.json", output))]
        stdout, stderr = io.StringIO(), io.StringIO()
        environment = {"GITHUB_ACTIONS": "", "CI": "", **(env or {})}  # local unless a test says otherwise
        with mock.patch.dict("os.environ", environment), redirect_stdout(stdout), redirect_stderr(stderr):
            code = MODULE.main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def baseline(self, tool: str) -> dict:
        return json.loads((self.root / f"config/lint-baseline/{tool}.json").read_text(encoding="utf-8"))

    def seed_shellcheck(self) -> None:
        code, _, _ = self.main("shellcheck", "--seed", output=shellcheck_output(("scripts/a.sh", 2, 2034, "unused")))
        self.assertEqual(code, 0)

    def test_parses_both_tools_with_repository_relative_paths(self) -> None:
        shell = MODULE.parse_findings("shellcheck", shellcheck_output(("scripts/a.sh", 2, 2034, "m")), self.root)
        self.assertEqual(shell, [MODULE.Finding("scripts/a.sh", 2, 1, "SC2034", "m")])
        python = MODULE.parse_findings("ruff", ruff_output(self.root, ("scripts/b.py", 1, "F401", "unused"),
                                                           ("scripts/b.py", 3, None, "SyntaxError")), self.root)
        self.assertEqual([(f.file, f.line, f.code) for f in python],
                         [("scripts/b.py", 1, "F401"), ("scripts/b.py", 3, "invalid-syntax")])
        self.assertEqual(MODULE.parse_findings("shellcheck", "", self.root), [])
        with self.assertRaises(MODULE.LintBaselineError):
            MODULE.parse_findings("ruff", "not json", self.root)
        with self.assertRaises(MODULE.LintBaselineError):
            MODULE.parse_findings("ruff", json.dumps([{"code": "F401"}]), self.root)

    def test_seed_writes_once_and_an_identical_run_passes(self) -> None:
        self.seed_shellcheck()
        self.assertEqual(self.baseline("shellcheck")["findings"], [{
            "file": "scripts/a.sh", "code": "SC2034", "fingerprint": MODULE.fingerprint("unused=1"), "count": 1,
        }])
        code, _, stderr = self.main("shellcheck", "--seed", output=shellcheck_output())
        self.assertEqual(code, 2)
        self.assertIn("may only shrink", stderr)
        self.assertEqual(len(self.baseline("shellcheck")["findings"]), 1)
        code, stdout, _ = self.main("shellcheck", output=shellcheck_output(("scripts/a.sh", 2, 2034, "unused")))
        self.assertEqual(code, 0, stdout)
        self.assertIn("0 new", stdout)

    def test_moved_or_reindented_findings_keep_their_key(self) -> None:
        self.seed_shellcheck()
        self.write("scripts/a.sh", "#!/usr/bin/env bash\n# a new comment\nif true; then\n    unused=1\nfi\necho hi\n")
        code, stdout, _ = self.main("shellcheck", output=shellcheck_output(("scripts/a.sh", 4, 2034, "unused")))
        self.assertEqual(code, 0, stdout)

    def test_a_new_finding_fails_and_is_printed(self) -> None:
        self.seed_shellcheck()
        self.write("scripts/a.sh", "#!/usr/bin/env bash\nunused=1\nother=2\n")
        code, stdout, _ = self.main("shellcheck", output=shellcheck_output(
            ("scripts/a.sh", 2, 2034, "unused appears unused"), ("scripts/a.sh", 3, 2034, "other appears unused")))
        self.assertEqual(code, 1)
        self.assertIn("scripts/a.sh:3:1: SC2034 other appears unused", stdout)
        self.assertNotIn("scripts/a.sh:2:", stdout)
        self.assertIn("1 new", stdout)
        # Editing the line that carries a baselined finding makes it new.
        self.write("scripts/a.sh", "#!/usr/bin/env bash\nunused=12\n")
        code, stdout, _ = self.main("shellcheck", output=shellcheck_output(("scripts/a.sh", 2, 2034, "unused")))
        self.assertEqual(code, 1, stdout)

    def test_a_second_identical_occurrence_is_new(self) -> None:
        self.seed_shellcheck()
        self.write("scripts/a.sh", "#!/usr/bin/env bash\nunused=1\nunused=1\n")
        code, stdout, _ = self.main("shellcheck", output=shellcheck_output(
            ("scripts/a.sh", 2, 2034, "unused"), ("scripts/a.sh", 3, 2034, "unused")))
        self.assertEqual(code, 1)
        self.assertIn("1 of 2 identical findings on this line text are new", stdout)

    def test_fixed_entries_are_reported_and_update_only_removes(self) -> None:
        output = ruff_output(self.root, ("scripts/b.py", 1, "F401", "`os` imported but unused"))
        self.assertEqual(self.main("ruff", "--seed", output=output)[0], 0)
        before = (self.root / "config/lint-baseline/ruff.json").read_text(encoding="utf-8")
        code, stdout, _ = self.main("ruff", output=ruff_output(self.root))
        self.assertEqual(code, 0)
        self.assertIn("1 baseline finding(s) no longer occur", stdout)
        self.assertIn("scripts/b.py F401", stdout)
        self.assertEqual((self.root / "config/lint-baseline/ruff.json").read_text(encoding="utf-8"), before)
        # A fixed finding and a new one: --update drops the first, never records the second.
        self.write("scripts/b.py", "import sys\nimport json\n\nprint(sys.argv)\n")
        code, stdout, _ = self.main("ruff", "--update", output=ruff_output(
            self.root, ("scripts/b.py", 2, "F401", "`json` imported but unused")))
        self.assertEqual(code, 1)
        self.assertIn("scripts/b.py:2:8: F401 `json` imported but unused", stdout)
        self.assertEqual(self.baseline("ruff")["findings"], [])
        self.assertEqual(self.baseline("ruff")["tool"], "ruff")

    def test_update_lowers_counts_without_dropping_live_entries(self) -> None:
        self.write("scripts/a.sh", "#!/usr/bin/env bash\nunused=1\nunused=1\nkept=1\n")
        self.main("shellcheck", "--seed", output=shellcheck_output(
            ("scripts/a.sh", 2, 2034, "u"), ("scripts/a.sh", 3, 2034, "u"), ("scripts/a.sh", 4, 2034, "k")))
        self.assertEqual(sorted(entry["count"] for entry in self.baseline("shellcheck")["findings"]), [1, 2])
        code, _, _ = self.main("shellcheck", "--update", output=shellcheck_output(
            ("scripts/a.sh", 2, 2034, "u"), ("scripts/a.sh", 4, 2034, "k")))
        self.assertEqual(code, 0)
        self.assertEqual(sorted(entry["count"] for entry in self.baseline("shellcheck")["findings"]), [1, 1])

    def test_invalid_or_missing_baselines_have_no_verdict(self) -> None:
        code, _, stderr = self.main("ruff", output=ruff_output(self.root))
        self.assertEqual(code, 2)
        self.assertIn("--seed", stderr)
        path = self.root / "config/lint-baseline/ruff.json"
        path.parent.mkdir(parents=True)
        entry ={"file": "scripts/b.py", "code": "F401", "fingerprint": "0" * 16, "count": 1}
        for payload in (
            {"schemaVersion": 1, "tool": "shellcheck", "findings": []},
            {"schemaVersion": 2, "tool": "ruff", "findings": []},
            {"schemaVersion": 1, "tool": "ruff", "findings": [entry, entry]},
            {"schemaVersion": 1, "tool": "ruff", "findings": [{**entry, "count": 0}]},
            {"schemaVersion": 1, "tool": "ruff", "findings": [{**entry, "count": True}]},
        ):
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(MODULE.LintBaselineError, msg=payload):
                MODULE.load_baseline(path, "ruff")

    def test_github_annotations_escape_their_values(self) -> None:
        self.main("ruff", "--seed", output=ruff_output(self.root))
        code, stdout, _ = self.main("ruff", output=ruff_output(
            self.root, ("scripts/b.py", 1, "F401", "50% of\nit")), env={"GITHUB_ACTIONS": "true"})
        self.assertEqual(code, 1)
        self.assertIn("::error file=scripts/b.py,line=1,col=8,title=ruff F401::50%25 of%0Ait", stdout)

    def test_tracked_files_select_each_tools_sources(self) -> None:
        self.write("scripts/lib/python-bin/python3", "#!/usr/bin/env bash\nexec python3 \"$@\"\n")
        self.write("scripts/tool", "#!/usr/bin/env python3\nprint(1)\n")
        self.write("scripts/z", "#!/bin/zsh\necho\n")
        self.write("LICENSE", "MIT\n")
        listing = "\0".join(["scripts/a.sh", "scripts/b.py", "scripts/lib/python-bin/python3", "scripts/tool",
                             "scripts/z", "LICENSE", "scripts/deleted.sh"]) + "\0"
        completed = subprocess.CompletedProcess([], 0, stdout=listing.encode(), stderr=b"")
        with mock.patch.object(MODULE.subprocess, "run", return_value=completed):
            self.assertEqual(MODULE.tracked_files(self.root, "shellcheck"),
                             ["scripts/a.sh", "scripts/lib/python-bin/python3"])
            self.assertEqual(MODULE.tracked_files(self.root, "ruff"), ["scripts/b.py"])

    def test_tool_errors_are_not_findings(self) -> None:
        def fake_run(command, **_):
            return subprocess.CompletedProcess(command, 2, stdout="", stderr="cannot read file")
        with mock.patch.object(MODULE.subprocess, "run", side_effect=fake_run):
            with self.assertRaisesRegex(MODULE.LintBaselineError, "exited 2"):
                MODULE.run_tool(self.root, "shellcheck", ["scripts/a.sh"])
        with mock.patch.object(MODULE.subprocess, "run", side_effect=FileNotFoundError("ruff")):
            with self.assertRaisesRegex(MODULE.LintBaselineError, "install_pinned_tools.sh ruff"):
                MODULE.run_tool(self.root, "ruff", ["scripts/b.py"])

    def test_shellcheck_runs_per_file_and_findings_merge(self) -> None:
        def fake_run(command, **_):
            file = command[-1]
            return subprocess.CompletedProcess(command, 1, stdout=shellcheck_output((file, 2, 2034, "u")), stderr="")
        with mock.patch.object(MODULE.subprocess, "run", side_effect=fake_run):
            outputs = MODULE.run_tool(self.root, "shellcheck", ["scripts/a.sh", "scripts/c.sh"])
        files = [f.file for output in outputs for f in MODULE.parse_findings("shellcheck", output, self.root)]
        self.assertEqual(files, ["scripts/a.sh", "scripts/c.sh"])

    def test_version_drift_fails_in_ci_and_warns_locally(self) -> None:
        self.write("config/toolchain.json", json.dumps({"artifactPins": {"ruff": {"version": "0.17.1"}}}))
        completed = subprocess.CompletedProcess([], 0, stdout="ruff 0.16.0\n", stderr="")
        with mock.patch.object(MODULE.subprocess, "run", return_value=completed):
            with mock.patch.dict("os.environ", {"CI": "true"}):
                with self.assertRaisesRegex(MODULE.LintBaselineError, "not the pinned 0.17.1"):
                    MODULE.check_version(self.root, "ruff")
            stderr = io.StringIO()
            with mock.patch.dict("os.environ", {"CI": "", "GITHUB_ACTIONS": ""}), redirect_stderr(stderr):
                MODULE.check_version(self.root, "ruff")
            self.assertIn("warning: ruff 0.16.0 is not the pinned 0.17.1", stderr.getvalue())
        pinned = subprocess.CompletedProcess([], 0, stdout="ruff 0.17.1\n", stderr="")
        with mock.patch.object(MODULE.subprocess, "run", return_value=pinned), \
                mock.patch.dict("os.environ", {"CI": "true"}):
            MODULE.check_version(self.root, "ruff")

    def test_committed_baselines_are_valid(self) -> None:
        for tool in MODULE.TOOLS:
            MODULE.load_baseline(ROOT / f"config/lint-baseline/{tool}.json", tool)


if __name__ == "__main__":
    unittest.main()
