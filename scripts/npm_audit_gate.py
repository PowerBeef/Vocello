#!/usr/bin/env python3
"""The website npm advisory audit that security.yml runs (and release.yml before every candidate).

Runs `npm --prefix website audit --package-lock-only --json` and fails on every advisory of high or
critical severity, as `--audit-level=high` did, except an advisory that
config/npm-audit-exceptions.json names with an unexpired, maintainer-dated exception. It fails closed
on unreadable audit output, a malformed exception file, an exception that runs longer than 30 days
past its decision, and an expired exception, which must be renewed by a new decision or removed.

Usage:
  python3 scripts/npm_audit_gate.py
  python3 scripts/npm_audit_gate.py --audit-json PATH [--exceptions PATH] [--today YYYY-MM-DD]

Exit status: 0 pass, 1 an advisory or exception fails the audit, 2 the audit or exception file
cannot be read.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EXCEPTIONS_PATH = ROOT / "config" / "npm-audit-exceptions.json"
FAILING_SEVERITIES = {"high", "critical"}
KNOWN_SEVERITIES = {"info", "low", "moderate", "high", "critical"}
ADVISORY_ID = re.compile(r"GHSA(?:-[23456789cfghjmpqrvwx]{4}){3}")
MAX_EXCEPTION_DAYS = 30


class Unreadable(Exception):
    """The audit or the exception file cannot be read; the gate fails closed (exit 2)."""


def run_audit() -> dict[str, Any]:
    completed = subprocess.run(
        ["npm", "--prefix", str(ROOT / "website"), "audit", "--package-lock-only", "--json"],
        capture_output=True, text=True, check=False,
    )
    # npm exits 1 whenever it finds a vulnerability, so only its JSON decides.
    return parse_audit(completed.stdout, source="npm audit")


def parse_audit(text: str, *, source: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise Unreadable(f"{source} printed no JSON report ({error})") from error
    if not isinstance(payload, dict) or "error" in payload or not isinstance(payload.get("vulnerabilities"), dict):
        raise Unreadable(f"{source} returned no vulnerability report: {str(payload)[:300]}")
    return payload


def advisories(report: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Every advisory the report names, by GHSA id, with its severity, package and title.

    A package's own entries in `via` are advisories (objects); a string `via` is a dependency path
    whose advisories are listed under that package, so every advisory is found exactly once."""
    found: dict[str, dict[str, str]] = {}
    for package, entry in report["vulnerabilities"].items():
        for via in entry.get("via") or []:
            if not isinstance(via, dict):
                continue
            match = ADVISORY_ID.search(str(via.get("url") or ""))
            if not match:
                raise Unreadable(f"an advisory on {package} has no GitHub advisory id: {via.get('url')!r}")
            severity = str(via.get("severity") or "")
            if severity not in KNOWN_SEVERITIES:
                raise Unreadable(f"{match.group(0)} on {package} has an unknown severity: {severity!r}")
            found[match.group(0)] = {
                "severity": severity,
                "package": str(via.get("name") or package),
                "title": str(via.get("title") or ""),
            }
    return found


def load_exceptions(path: Path, today: dt.date) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Valid exceptions by advisory id, and the problems that fail the gate."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise Unreadable(f"{path.name} cannot be read: {error}") from error
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 1 or not isinstance(payload.get("exceptions"), list):
        raise Unreadable(f"{path.name} must be schema version 1 with an exceptions list")
    valid: dict[str, dict[str, Any]] = {}
    problems: list[str] = []
    for index, item in enumerate(payload["exceptions"]):
        label = f"exception {index + 1}"
        if not isinstance(item, dict):
            problems.append(f"{label} is not an object")
            continue
        advisory = str(item.get("advisory") or "")
        if not ADVISORY_ID.fullmatch(advisory):
            problems.append(f"{label} names no GitHub advisory id: {advisory!r}")
            continue
        try:
            decided = dt.date.fromisoformat(str(item.get("decided")))
            expires = dt.date.fromisoformat(str(item.get("expires")))
        except ValueError:
            problems.append(f"{advisory}: decided and expires must be YYYY-MM-DD dates")
            continue
        if not str(item.get("reason") or "").strip() or not str(item.get("package") or "").strip():
            problems.append(f"{advisory}: an exception needs its package and the reason it is safe")
            continue
        if decided > today:
            problems.append(f"{advisory}: decided on {decided}, a date still to come")
            continue
        if expires < decided or (expires - decided).days > MAX_EXCEPTION_DAYS:
            problems.append(f"{advisory}: an exception expires within {MAX_EXCEPTION_DAYS} days of its decision "
                            f"(decided {decided}, expires {expires})")
            continue
        if today > expires:
            problems.append(f"{advisory}: the exception expired on {expires}; renew it by a new decision or remove it")
            continue
        if advisory in valid:
            problems.append(f"{advisory}: listed twice")
            continue
        valid[advisory] = item
    return valid, problems


def evaluate(report: dict[str, Any], exceptions_path: Path, today: dt.date) -> tuple[int, list[str]]:
    found = advisories(report)
    excepted, problems = load_exceptions(exceptions_path, today)
    lines: list[str] = []
    failing = []
    for advisory, detail in sorted(found.items()):
        if detail["severity"] not in FAILING_SEVERITIES:
            continue
        exception = excepted.get(advisory)
        if exception is not None and str(exception["package"]) != detail["package"]:
            failing.append(advisory)
            lines.append(f"error: {advisory} {detail['severity']} in {detail['package']}: its exception names "
                         f"{exception['package']}, so it does not cover this package")
        elif exception is not None:
            lines.append(f"excepted: {advisory} {detail['severity']} in {detail['package']} "
                         f"until {exception['expires']} ({detail['title']})")
        else:
            failing.append(advisory)
            lines.append(f"error: {advisory} {detail['severity']} in {detail['package']}: {detail['title']}")
    for advisory in sorted(set(excepted) - set(found)):
        lines.append(f"notice: {advisory} no longer appears in the audit; remove its exception")
    lines.extend(f"error: {problem}" for problem in problems)
    status = 1 if failing or problems else 0
    counts = (report.get("metadata") or {}).get("vulnerabilities") or {}
    lines.append(f"npm advisory audit: {'FAIL' if status else 'PASS'} "
                 f"({len(failing)} unexcepted high or critical advisories; npm counts {counts or 'none'})")
    return status, lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--audit-json", type=Path, help="read a saved `npm audit --json` report instead of running npm")
    parser.add_argument("--exceptions", type=Path, default=EXCEPTIONS_PATH)
    parser.add_argument("--today", type=dt.date.fromisoformat, default=None, help="the date to judge expiry by (UTC today)")
    args = parser.parse_args(argv)
    today = args.today or dt.datetime.now(dt.timezone.utc).date()
    try:
        report = (parse_audit(args.audit_json.read_text(encoding="utf-8"), source=str(args.audit_json))
                  if args.audit_json else run_audit())
        status, lines = evaluate(report, args.exceptions, today)
    except (Unreadable, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    for line in lines:
        print(line, file=sys.stderr if line.startswith("error:") else sys.stdout)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
