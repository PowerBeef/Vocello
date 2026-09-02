#!/usr/bin/env python3
"""Validate and apply the fail-closed iOS Release analyzer warning policy."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config/ios-release-analyzer-warning-policy.json"
WARNING_RE = re.compile(r"^(?P<prefix>.*?)(?::|\]) warning: (?P<message>.*)$")


def load_policy(path: Path = POLICY_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_policy(policy: dict) -> list[str]:
    errors: list[str] = []
    if policy.get("schemaVersion") != 1:
        errors.append("schemaVersion must be 1")
    if policy.get("owner") != "apple-platform-release":
        errors.append("owner must be apple-platform-release")
    try:
        reviewed = date.fromisoformat(policy.get("reviewedAt", ""))
        if reviewed > date.today():
            errors.append("reviewedAt cannot be in the future")
    except ValueError:
        errors.append("reviewedAt must be an ISO date")
    rows = policy.get("allowedWarnings")
    if not isinstance(rows, list) or not rows:
        return errors + ["allowedWarnings must be a non-empty array"]
    seen: set[str] = set()
    for index, row in enumerate(rows):
        label = f"allowedWarnings[{index}]"
        if not isinstance(row, dict):
            errors.append(f"{label} must be an object")
            continue
        warning_id = row.get("id")
        if not isinstance(warning_id, str) or not warning_id:
            errors.append(f"{label} requires id")
        elif warning_id in seen:
            errors.append(f"duplicate warning id: {warning_id}")
        else:
            seen.add(warning_id)
        source = row.get("source")
        if not isinstance(source, str) or not source:
            errors.append(f"{label} requires source")
        elif source.startswith(("Sources/", "Packages/")) and not (ROOT / source).is_file():
            errors.append(f"{label} source does not resolve: {source}")
        elif not source.startswith(("Sources/", "Packages/", "tool:")):
            errors.append(f"{label} source must be repository-relative or tool-scoped")
        message = row.get("messageContains")
        if not isinstance(message, str) or len(message) < 12:
            errors.append(f"{label} requires a substantive messageContains")
        maximum = row.get("maximumCount")
        if not isinstance(maximum, int) or maximum < 1:
            errors.append(f"{label} maximumCount must be positive")
        for field in ("reason", "removalCondition"):
            if not isinstance(row.get(field), str) or len(row[field].strip()) < 24:
                errors.append(f"{label} requires substantive {field}")
    return errors


def normalize_source(prefix: str) -> str:
    for marker in ("Packages/", "Sources/"):
        marker_index = prefix.find(marker)
        if marker_index >= 0:
            candidate = prefix[marker_index:]
            match = re.match(r"([^:]+)(?::\d+){0,2}$", candidate)
            return match.group(1) if match else candidate.split(":", 1)[0]
    if prefix.startswith("libtool"):
        return "tool:libtool"
    if "appintentsmetadataprocessor" in prefix:
        return "tool:appintentsmetadataprocessor"
    return "tool:unknown"


def analyze_log(text: str, policy: dict) -> dict:
    rows = policy["allowedWarnings"]
    counts = {row["id"]: 0 for row in rows}
    unexpected: list[dict[str, str]] = []
    total = 0
    for raw_line in text.splitlines():
        match = WARNING_RE.match(raw_line)
        if match is None:
            continue
        total += 1
        source = normalize_source(match.group("prefix"))
        message = match.group("message")
        matched = next(
            (
                row for row in rows
                if row["source"] == source and row["messageContains"] in message
            ),
            None,
        )
        if matched is None:
            unexpected.append({"source": source, "message": message})
        else:
            counts[matched["id"]] += 1
    exceeded = [
        {
            "id": row["id"],
            "observed": counts[row["id"]],
            "maximum": row["maximumCount"],
        }
        for row in rows
        if counts[row["id"]] > row["maximumCount"]
    ]
    return {
        "schemaVersion": 1,
        "status": "PASS" if not unexpected and not exceeded else "FAIL",
        "warningCount": total,
        "registeredCounts": counts,
        "unexpected": unexpected,
        "exceeded": exceeded,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate")
    check = subparsers.add_parser("check")
    check.add_argument("--log", type=Path, required=True)
    args = parser.parse_args()

    policy = load_policy()
    errors = validate_policy(policy)
    if errors:
        for error in errors:
            print(f"iOS analyzer warning policy error: {error}", file=sys.stderr)
        return 1
    if args.command == "validate":
        print(f"iOS analyzer warning policy: PASS ({len(policy['allowedWarnings'])} classes)")
        return 0
    result = analyze_log(args.log.read_text(encoding="utf-8", errors="replace"), policy)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
