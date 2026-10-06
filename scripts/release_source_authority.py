#!/usr/bin/env python3
"""Fail-closed validation for signed, exact-SHA GitHub release authority.

The network boundary stays in the workflow's authenticated ``gh api`` calls.
This module consumes those untracked responses, rejects lightweight or
unverified tags, and requires the latest named GitHub Actions checks for the
tagged commit to have completed successfully. Only checks of a push run on main
count: ci.yml also names its pull-request aggregate `CI required`, and that run
checks the Linux lanes alone. Raw signatures and payloads are never copied into
the privacy-safe result.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


SHA = re.compile(r"[0-9a-f]{40}")
TAG = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+(?:[+-][0-9A-Za-z.-]+)?")
# `CI required` is the only per-push aggregate. Security analysis runs inside the
# release workflow on the tagged commit and gates it by job dependency.
DEFAULT_REQUIRED_CHECKS = ("CI required",)


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read JSON from {path}: {error}") from error


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _flatten_check_runs(value: Any) -> list[dict[str, Any]]:
    pages = value if isinstance(value, list) else [value]
    if not pages:
        raise ValueError("check-run response contains no pages")
    runs: dict[int, dict[str, Any]] = {}
    advertised = 0
    for index, raw_page in enumerate(pages):
        page = _object(raw_page, f"check-run page {index}")
        total = page.get("total_count")
        rows = page.get("check_runs")
        if not isinstance(total, int) or total < 0 or not isinstance(rows, list):
            raise ValueError(f"check-run page {index} has an invalid result envelope")
        advertised = max(advertised, total)
        for row in rows:
            item = _object(row, "check run")
            identifier = item.get("id")
            if not isinstance(identifier, int) or identifier <= 0:
                raise ValueError("check run has an invalid id")
            runs[identifier] = item
    if len(runs) < advertised:
        raise ValueError(
            f"check-run response is incomplete ({len(runs)} collected, {advertised} advertised)"
        )
    return list(runs.values())


CI_WORKFLOW_PATH = ".github/workflows/ci.yml"


def _push_check_suites(value: Any, commit: str) -> set[int]:
    """Check-suite ids of the CI workflow's push runs on main for the commit (`actions/runs` pages)."""
    pages = value if isinstance(value, list) else [value]
    if not pages:
        raise ValueError("workflow-run response contains no pages")
    suites: set[int] = set()
    collected: set[int] = set()
    advertised = 0
    for index, raw_page in enumerate(pages):
        page = _object(raw_page, f"workflow-run page {index}")
        total = page.get("total_count")
        rows = page.get("workflow_runs")
        if not isinstance(total, int) or total < 0 or not isinstance(rows, list):
            raise ValueError(f"workflow-run page {index} has an invalid result envelope")
        advertised = max(advertised, total)
        for row in rows:
            run = _object(row, "workflow run")
            identifier = run.get("id")
            if not isinstance(identifier, int) or identifier <= 0:
                raise ValueError("workflow run has an invalid id")
            collected.add(identifier)
            suite = run.get("check_suite_id")
            if (run.get("event") == "push" and run.get("head_branch") == "main"
                    and run.get("head_sha") == commit and run.get("path") == CI_WORKFLOW_PATH
                    and isinstance(suite, int)):
                suites.add(suite)
    if len(collected) < advertised:
        raise ValueError(
            f"workflow-run response is incomplete ({len(collected)} collected, {advertised} advertised)"
        )
    return suites


def _latest_required_check(
    rows: list[dict[str, Any]],
    *,
    name: str,
    commit: str,
    push_suites: set[int],
) -> dict[str, Any]:
    candidates = []
    for row in rows:
        app = row.get("app")
        suite = row.get("check_suite")
        if (
            row.get("name") == name
            and row.get("head_sha") == commit
            and isinstance(app, dict)
            and app.get("slug") == "github-actions"
            and isinstance(suite, dict)
            and suite.get("id") in push_suites
        ):
            candidates.append(row)
    if not candidates:
        raise ValueError(f"missing exact-SHA GitHub Actions check {name!r} from a push to main")
    latest = max(
        candidates,
        key=lambda row: (
            str(row.get("completed_at") or row.get("started_at") or row.get("created_at") or ""),
            int(row["id"]),
        ),
    )
    if latest.get("status") != "completed" or latest.get("conclusion") != "success":
        raise ValueError(
            f"latest exact-SHA check {name!r} is "
            f"{latest.get('status')}/{latest.get('conclusion')}"
        )
    return latest


def validate(
    *,
    tag: str,
    commit: str,
    tag_ref: Any,
    tag_object: Any,
    check_runs: Any,
    push_runs: Any,
    required_checks: tuple[str, ...] = DEFAULT_REQUIRED_CHECKS,
) -> dict[str, Any]:
    if TAG.fullmatch(tag) is None:
        raise ValueError("release tag is invalid")
    if SHA.fullmatch(commit) is None:
        raise ValueError("release commit must be a lowercase 40-character Git SHA")
    if not required_checks or len(set(required_checks)) != len(required_checks):
        raise ValueError("required checks must be non-empty and unique")

    reference = _object(tag_ref, "tag ref")
    reference_object = _object(reference.get("object"), "tag ref object")
    annotated = _object(tag_object, "annotated tag")
    target = _object(annotated.get("object"), "annotated tag target")
    verification = _object(annotated.get("verification"), "tag verification")

    if reference.get("ref") != f"refs/tags/{tag}":
        raise ValueError("GitHub tag ref identity does not match the requested tag")
    if reference_object.get("type") != "tag":
        raise ValueError("release tag must be an annotated signed tag, not a lightweight tag")
    if reference_object.get("sha") != annotated.get("sha"):
        raise ValueError("tag ref does not resolve to the supplied annotated tag object")
    if annotated.get("tag") != tag:
        raise ValueError("annotated tag identity does not match the requested tag")
    if target.get("type") != "commit" or target.get("sha") != commit:
        raise ValueError("signed tag does not target the release commit")
    if verification.get("verified") is not True or verification.get("reason") != "valid":
        raise ValueError(
            f"GitHub did not verify the release tag signature: {verification.get('reason')!r}"
        )
    for field in ("signature", "payload", "verified_at"):
        if not isinstance(verification.get(field), str) or not verification[field]:
            raise ValueError(f"verified tag response is missing {field}")

    rows = _flatten_check_runs(check_runs)
    push_suites = _push_check_suites(push_runs, commit)
    checks: dict[str, dict[str, Any]] = {}
    for name in required_checks:
        row = _latest_required_check(rows, name=name, commit=commit, push_suites=push_suites)
        checks[name] = {
            "id": row["id"],
            "completedAt": row.get("completed_at"),
            "detailsURL": row.get("details_url"),
        }

    return {
        "schemaVersion": 1,
        "status": "passed",
        "tag": tag,
        "commit": commit,
        "tagVerification": {
            "reason": "valid",
            "verifiedAt": verification["verified_at"],
        },
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--tag-ref", type=Path, required=True)
    parser.add_argument("--tag-object", type=Path, required=True)
    parser.add_argument("--check-runs", type=Path, required=True)
    parser.add_argument("--push-runs", type=Path, required=True,
                        help="actions/runs?head_sha=<commit>&event=push&branch=main pages")
    parser.add_argument("--required-check", action="append", dest="required_checks")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        result = validate(
            tag=args.tag,
            commit=args.commit,
            tag_ref=_load_json(args.tag_ref),
            tag_object=_load_json(args.tag_object),
            check_runs=_load_json(args.check_runs),
            push_runs=_load_json(args.push_runs),
            required_checks=tuple(args.required_checks or DEFAULT_REQUIRED_CHECKS),
        )
        encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.write_text(encoded, encoding="utf-8")
        print(encoded, end="")
        return 0
    except (OSError, ValueError) as error:
        print(f"release source authority: FAIL — {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
