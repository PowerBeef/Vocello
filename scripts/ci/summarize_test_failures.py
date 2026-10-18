#!/usr/bin/env python3
"""Name the failing tests of a CI lane in the job summary and as annotations.

A failed deterministic or TSan run used to show only its exit status in the job log;
the failing test lived in the uploaded artifact (audit W-05). This reads the
`*.test-results.json` files `scripts/lib/xctest_summary.py` writes beside each lane
log and, when a lane produced none (a build failure), the compiler's `error:` lines.
It only reports: it never changes the job's result.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

MAX_LISTED = 40
MAX_ERROR_LINES = 20


def failing_tests(root: pathlib.Path) -> tuple[list[str], list[pathlib.Path]]:
    names: list[str] = []
    result_files = sorted(root.glob("**/*.test-results.json"))
    for path in result_files:
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            names.append(f"{path.name}: unreadable test results")
            continue
        for test in data.get("tests") or []:
            if test.get("verdict") == "failed":
                names.append(f"{test.get('suite', '?')}.{test.get('test', '?')}")
        if data.get("complete") is False or data.get("consistent") is False:
            names.append(f"{path.name}: the run's results are incomplete or inconsistent")
    return names, result_files


def build_errors(root: pathlib.Path) -> list[str]:
    lines: list[str] = []
    for log in sorted(root.glob("**/*build*.log")):
        try:
            text = log.read_text(errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            if " error: " in line or line.startswith("error: "):
                lines.append(line.strip())
                if len(lines) >= MAX_ERROR_LINES:
                    return lines
    return lines


def render(lane: str, root: pathlib.Path) -> tuple[str, list[str]]:
    names, result_files = failing_tests(root)
    errors = [] if names else build_errors(root)
    if names:
        shown = names[:MAX_LISTED]
        body = [f"### {lane}: {len(names)} failing test(s)", ""] + [f"- `{n}`" for n in shown]
        if len(names) > len(shown):
            body.append(f"- … and {len(names) - len(shown)} more (see the uploaded artifact)")
        annotations = [f"::error title={lane} test failed::{n}" for n in shown]
    elif errors:
        body = [f"### {lane}: build failed", "", "```", *errors, "```"]
        annotations = [f"::error title={lane} build error::{line}" for line in errors[:10]]
    elif result_files:
        body = [f"### {lane}: no failing test was recorded; see the step log"]
        annotations = []
    else:
        body = [f"### {lane}: no test results were written; see the step log"]
        annotations = []
    return "\n".join(body) + "\n", annotations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lane", required=True, help="label shown in the summary")
    parser.add_argument("--root", default="build/artifacts/macos/tests",
                        help="directory holding the lane's run folders")
    args = parser.parse_args(argv)
    summary, annotations = render(args.lane, pathlib.Path(args.root))
    for line in annotations:
        print(line)
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(summary)
    else:
        sys.stdout.write(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
