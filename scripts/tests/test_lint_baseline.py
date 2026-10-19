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


def swiftlint_output(root: Path, *items: tuple[str, int | None, int | None, str, str]) -> str:
    """swiftlint lint --reporter json, as 0.65.1 prints it (absolute files; `character` may be null)."""
    return json.dumps([
        {"character": character, "file": str(root / file), "line": line, "reason": reason, "rule_id": rule,
         "severity": "Warning", "type": rule.replace("_", " ").title()}
        for file, line, character, rule, reason in items
    ], indent=2)


def pyright_output(root: Path, *items: tuple[str, int, int, str, str | None]) -> str:
    """pyright --outputjson, as 1.1.414 prints it (absolute files, zero-based positions)."""
    diagnostics = []
    for file, line, character, severity, rule in items:
        diagnostic = {"file": str(root / file), "severity": severity, "message": f"{rule} here\n  detail",
                      "range": {"start": {"line": line, "character": character},
                                "end": {"line": line, "character": character + 3}}}
        if rule:
            diagnostic["rule"] = rule
        diagnostics.append(diagnostic)
    return json.dumps({"version": "1.1.414", "generalDiagnostics": diagnostics,
                       "summary": {"filesAnalyzed": 2, "errorCount": len(diagnostics)}})


SWIFTLINT_CONFIG = """# Lint scope (a comment)
only_rules:
  - empty_count
  - trailing_whitespace
included:
- Sources
  - "Tests/"
excluded:
  - Packages  # the owned package
  - 'Sources/Generated'
  - Tests/**/Fixtures
"""


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

    def test_swiftlint_findings_parse_with_repository_relative_paths(self) -> None:
        output = swiftlint_output(self.root, ("Sources/A.swift", 4, 6, "empty_count", "Prefer `isEmpty`"),
                                  ("Sources/B.swift", None, None, "file_length", "too long"))
        self.assertEqual(MODULE.parse_findings("swiftlint", output, self.root), [
            MODULE.Finding("Sources/A.swift", 4, 6, "empty_count", "Prefer `isEmpty`"),
            MODULE.Finding("Sources/B.swift", 0, 0, "file_length", "too long"),
        ])
        # A clean run prints an empty array; an empty stdout is no findings too.
        self.assertEqual(MODULE.parse_findings("swiftlint", "[\n\n]\n", self.root), [])
        self.assertEqual(MODULE.parse_findings("swiftlint", "", self.root), [])
        with self.assertRaises(MODULE.LintBaselineError):
            MODULE.parse_findings("swiftlint", json.dumps([{"file": "x.swift", "line": 1}]), self.root)

    def test_swiftlint_lints_the_tracked_swift_files_its_configuration_covers(self) -> None:
        self.write(".swiftlint.yml", SWIFTLINT_CONFIG)
        self.assertEqual(MODULE.swiftlint_scope(self.root),
                         (("Sources", "Tests"), ("Packages", "Sources/Generated", "Tests/**/Fixtures")))
        sources = ["Sources/App.swift", "Sources/Generated/Table.swift", "Tests/CoreTests/A.swift",
                   "Tests/Core/Fixtures/F.swift", "Packages/Core/Sources/X.swift", "scripts/tool.swift",
                   "Sources/Notes.md", "SourcesExtra/Y.swift"]
        for source in sources:
            self.write(source, "let x = 1\n")
        listing = "\0".join([*sources, "Sources/Deleted.swift"]) + "\0"
        completed = subprocess.CompletedProcess([], 0, stdout=listing.encode(), stderr=b"")
        with mock.patch.object(MODULE.subprocess, "run", return_value=completed):
            self.assertEqual(MODULE.tracked_files(self.root, "swiftlint"),
                             ["Sources/App.swift", "Tests/CoreTests/A.swift"])
        # Without `included`, every tracked Swift file outside `excluded` is in scope.
        self.write(".swiftlint.yml", "excluded:\n  - Packages\n")
        with mock.patch.object(MODULE.subprocess, "run", return_value=completed):
            self.assertEqual(MODULE.tracked_files(self.root, "swiftlint"), [
                "Sources/App.swift", "Sources/Generated/Table.swift", "SourcesExtra/Y.swift",
                "Tests/Core/Fixtures/F.swift", "Tests/CoreTests/A.swift", "scripts/tool.swift",
            ])

    def test_swiftlint_scope_refuses_forms_it_does_not_read(self) -> None:
        with self.assertRaisesRegex(MODULE.LintBaselineError, ".swiftlint.yml"):
            MODULE.swiftlint_scope(self.root)  # no configuration at all
        for text in ("excluded: [Packages]\n", "excluded:\n  Packages: true\n", "included:\n  -\n"):
            self.write(".swiftlint.yml", text)
            with self.assertRaises(MODULE.LintBaselineError, msg=text):
                MODULE.swiftlint_scope(self.root)

    def test_swiftlint_gates_new_findings_against_its_own_baseline(self) -> None:
        self.write("Sources/A.swift", "let values = [1]\nlet empty = values.count == 0\n")
        finding = ("Sources/A.swift", 2, 13, "empty_count", "Prefer checking `isEmpty`")
        self.assertEqual(self.main("swiftlint", "--seed", output=swiftlint_output(self.root, finding))[0], 0)
        baseline = self.baseline("swiftlint")
        self.assertIn("(DW-03)", baseline["description"])
        self.assertEqual(baseline["findings"], [{
            "file": "Sources/A.swift", "code": "empty_count",
            "fingerprint": MODULE.fingerprint("let empty = values.count == 0"), "count": 1,
        }])
        code, stdout, _ = self.main("swiftlint", output=swiftlint_output(self.root, finding))
        self.assertEqual(code, 0, stdout)
        self.write("Sources/A.swift",
                   "let values = [1]\nlet empty = values.count == 0\nlet none = values.count == 0 \n")
        code, stdout, _ = self.main("swiftlint", output=swiftlint_output(
            self.root, finding, ("Sources/A.swift", 3, 12, "empty_count", "Prefer checking `isEmpty`"),
            ("Sources/A.swift", 3, 30, "trailing_whitespace", "Lines should not have trailing whitespace")))
        self.assertEqual(code, 1)
        self.assertIn("Sources/A.swift:3:12: empty_count Prefer checking `isEmpty`", stdout)
        self.assertIn("Sources/A.swift:3:30: trailing_whitespace", stdout)
        self.assertNotIn("Sources/A.swift:2:", stdout)
        self.assertIn("2 new", stdout)

    def test_swiftlint_error_severity_findings_are_not_a_tool_error(self) -> None:
        output = swiftlint_output(self.root, ("Sources/A.swift", 2, 13, "empty_count", "Prefer `isEmpty`"))
        commands = []

        def fake_run(command, **_):
            commands.append(command)
            return subprocess.CompletedProcess(command, 2, stdout=output, stderr="")
        with mock.patch.object(MODULE.subprocess, "run", side_effect=fake_run):
            self.assertEqual(MODULE.run_tool(self.root, "swiftlint", ["Sources/A.swift", "Tests/B.swift"]),
                             [output])
        # One invocation for every file: SwiftLint lints in parallel itself.
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0][:2], ["swiftlint", "lint"])
        self.assertIn("--force-exclude", commands[0])
        self.assertEqual(commands[0][-2:], ["Sources/A.swift", "Tests/B.swift"])

        def failing_run(command, **_):
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="Error: No lintable files found")
        with mock.patch.object(MODULE.subprocess, "run", side_effect=failing_run):
            with self.assertRaisesRegex(MODULE.LintBaselineError, "exited 1"):
                MODULE.run_tool(self.root, "swiftlint", ["Sources/A.swift"])

    def test_pyright_findings_skip_import_resolution_and_information(self) -> None:
        output = pyright_output(self.root, ("scripts/b.py", 3, 4, "error", "reportOptionalMemberAccess"),
                                ("scripts/b.py", 0, 7, "error", "reportMissingImports"),
                                ("scripts/b.py", 1, 0, "warning", "reportMissingModuleSource"),
                                ("scripts/b.py", 2, 0, "information", "reportUnusedVariable"),
                                ("scripts/c.py", 9, 0, "error", None))
        self.assertEqual(MODULE.parse_findings("pyright", output, self.root), [
            MODULE.Finding("scripts/b.py", 4, 5, "reportOptionalMemberAccess", "reportOptionalMemberAccess here"),
            MODULE.Finding("scripts/c.py", 10, 1, "pyright", "None here"),
        ])
        self.assertEqual(MODULE.parse_findings("pyright", "", self.root), [])
        with self.assertRaises(MODULE.LintBaselineError):
            MODULE.parse_findings("pyright", json.dumps({"generalDiagnostics": [{"file": "x.py"}]}), self.root)

    def test_pyright_counts_a_repeated_diagnostic_at_one_position_once(self) -> None:
        output = pyright_output(self.root, ("scripts/b.py", 3, 4, "error", "reportArgumentType"),
                                ("scripts/b.py", 3, 4, "error", "reportArgumentType"),
                                ("scripts/b.py", 5, 4, "error", "reportArgumentType"))
        self.assertEqual([(finding.line, finding.column) for finding in
                          MODULE.parse_findings("pyright", output, self.root)], [(4, 5), (6, 5)])

    def test_pyright_checks_scripts_once_against_an_empty_interpreter(self) -> None:
        listing = "\0".join(["scripts/b.py", "website/x.py", "tools/y.py", "scripts/a.sh"]) + "\0"
        completed = subprocess.CompletedProcess([], 0, stdout=listing.encode(), stderr=b"")
        with mock.patch.object(MODULE.subprocess, "run", return_value=completed):
            self.assertEqual(MODULE.tracked_files(self.root, "pyright"), ["scripts/b.py"])
        calls: list[list[str]] = []

        def fake_run(command, **_):
            calls.append(list(command))
            if command[1:3] == ["-m", "venv"]:
                return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")
            interpreter = Path(command[command.index("--pythonpath") + 1])
            self.assertEqual(interpreter.name, "python")
            return subprocess.CompletedProcess(command, 1, stdout=pyright_output(
                self.root, ("scripts/b.py", 0, 0, "error", "reportCallIssue")), stderr="")
        with mock.patch.object(MODULE.subprocess, "run", side_effect=fake_run):
            outputs = MODULE.run_tool(self.root, "pyright", ["scripts/b.py", "scripts/c.py"])
        self.assertEqual([call[1:4] for call in calls if "venv" in call], [["-m", "venv", "--without-pip"]])
        pyright_calls = [call for call in calls if call[0] == "pyright"]
        self.assertEqual(len(pyright_calls), 1)
        self.assertEqual(pyright_calls[0][-2:], ["scripts/b.py", "scripts/c.py"])
        self.assertEqual([f.code for output in outputs for f in MODULE.parse_findings("pyright", output, self.root)],
                         ["reportCallIssue"])

    def test_pyright_version_comes_from_the_npm_pin(self) -> None:
        self.write("config/toolchain.json", json.dumps({"npmPins": {"pyright": {"version": "1.1.414"}},
                                                        "artifactPins": {}}))
        drifted = subprocess.CompletedProcess([], 0, stdout="pyright 1.1.400\n", stderr="")
        with mock.patch.object(MODULE.subprocess, "run", return_value=drifted), \
                mock.patch.dict("os.environ", {"CI": "true"}):
            with self.assertRaisesRegex(MODULE.LintBaselineError, "npm install --global pyright@1.1.414"):
                MODULE.check_version(self.root, "pyright")

    def test_committed_baselines_are_valid(self) -> None:
        for tool in MODULE.TOOLS:
            MODULE.load_baseline(ROOT / f"config/lint-baseline/{tool}.json", tool)


if __name__ == "__main__":
    unittest.main()
