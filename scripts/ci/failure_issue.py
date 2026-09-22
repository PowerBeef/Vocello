#!/usr/bin/env python3
"""Open or refresh one labelled issue for a failing scheduled workflow.

A workflow's `report` job passes `toJSON(needs)` as RESULTS and the run URL as
RUN_URL. When an open issue already carries the label, the run is appended as
a comment; otherwise the label is created (tolerating an existing label) and a
new issue is filed. The logic lives here, not in inline workflow Python, so a
unit test exercises it before a real failure ever needs it.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import Callable

GhRunner = Callable[[list[str]], str]


def _gh(arguments: list[str]) -> str:
    return subprocess.run(["gh", *arguments], capture_output=True, text=True, check=True).stdout


def issue_body(results_json: str, run_url: str, heading: str) -> str:
    """The issue or comment body: the run link, then each needed job's result."""
    results = json.loads(results_json)
    if not isinstance(results, dict) or not results:
        raise ValueError("RESULTS must be a non-empty JSON object of job results")
    lines = []
    for job, detail in results.items():
        result = detail.get("result") if isinstance(detail, dict) else None
        lines.append(f"- {job}: {result or 'unknown'}")
    return f"{heading}: {run_url}\n\nJob results:\n" + "\n".join(lines)


def report(repository: str, label: str, title: str, body: str, gh: GhRunner = _gh) -> str:
    """Comment on the open labelled issue, or create the label and a new issue."""
    existing = gh(["issue", "list", "--repo", repository, "--label", label, "--state", "open",
                   "--json", "number", "--jq", ".[0].number // empty"]).strip()
    if existing:
        gh(["issue", "comment", existing, "--repo", repository, "--body", body])
        return f"commented on #{existing}"
    try:
        gh(["label", "create", label, "--repo", repository, "--color", "B60205",
            "--description", f"{title} (scheduled workflow failure)"])
    except subprocess.CalledProcessError:
        pass  # the label already exists
    gh(["issue", "create", "--repo", repository, "--label", label, "--title", title, "--body", body])
    return "created an issue"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Open or refresh one labelled issue for a failing scheduled workflow.")
    parser.add_argument("--label", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--heading", required=True)
    parser.add_argument("--dry-run", action="store_true", help="print the body instead of calling gh")
    args = parser.parse_args(argv)
    try:
        body = issue_body(os.environ.get("RESULTS", ""), os.environ.get("RUN_URL", ""), args.heading)
    except (ValueError, json.JSONDecodeError) as error:
        print(f"failure_issue: {error}", file=sys.stderr)
        return 1
    if args.dry_run:
        print(body)
        return 0
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    if not repository:
        print("failure_issue: GITHUB_REPOSITORY is not set", file=sys.stderr)
        return 1
    print(report(repository, args.label, args.title, body))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
