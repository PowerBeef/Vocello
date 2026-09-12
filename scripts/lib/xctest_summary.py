#!/usr/bin/env python3
"""Summarize an XCTest or `swift test` log into the repository's test-results.json shape.

One writer for every lane. `scripts/ui_test.sh` used to carry this parser inline
and `scripts/macos_test.sh` had none, so the macOS unit lane produced plain logs
only. Both now call this module, and triage tooling reads one format:

    {"schemaVersion": 1, "tests": [{"test": "...", "verdict": "passed|failed|skipped", "seconds": 0.0}, ...],
     "counts": {"passed": N, "failed": N, "skipped": N, "total": N}, "source": "<log path>"}

`counts` and `source` are additive; schemaVersion 1 readers that only know
`tests` keep working. Both XCTest and swift-testing-on-XCTest logs use the same
"Test Case '-[Suite test]' passed|failed|skipped (0.123 seconds)" line, which is parsed;
an "Executed N tests" trailer is cross-checked when present.

Usage:
    python3 scripts/lib/xctest_summary.py LOG OUT.json [--quiet]
    exit 0 when the log parsed (even with failures); 3 when the trailer count
    disagrees with the parsed cases, which means the log is truncated or foreign.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

CASE = re.compile(r"Test Case '-\[([\w.]+) (\w+)\]' (passed|failed|skipped) \((\d+\.\d+) seconds\)")
EXECUTED = re.compile(r"Executed (\d+) tests?, with (?:(\d+) tests? skipped and )?(\d+) failures?")
# A whole-bundle total follows the "All tests" suite verdict; a log that ran several
# bundles (one xcodebuild invocation, or concatenated runs) has one per bundle.
BUNDLE_TOTAL = re.compile(
    r"Test Suite 'All tests' (?:passed|failed) at [^\n]*\n[ \t]*Executed (\d+) tests?, with (?:(\d+) tests? skipped and )?(\d+) failures?"
)


def summarize(log_text: str, source: str = "") -> dict:
    tests = [
        {
            # "Module.Suite" as XCTest prints it; the bare suite is the last component.
            "suite": m.group(1).rsplit(".", 1)[-1],
            "test": m.group(2),
            "verdict": m.group(3),
            "seconds": float(m.group(4)),
        }
        for m in CASE.finditer(log_text)
    ]
    passed = sum(1 for t in tests if t["verdict"] == "passed")
    failed = sum(1 for t in tests if t["verdict"] == "failed")
    skipped = sum(1 for t in tests if t["verdict"] == "skipped")
    payload = {
        "schemaVersion": 1,
        "tests": tests,
        "counts": {"passed": passed, "failed": failed, "skipped": skipped, "total": len(tests)},
    }
    if source:
        payload["source"] = source
    bundle_totals = BUNDLE_TOTAL.findall(log_text)
    trailers = EXECUTED.findall(log_text)
    if bundle_totals:
        executed = sum(int(t[0]) for t in bundle_totals)
        skipped_trailer = sum(int(t[1] or 0) for t in bundle_totals)
        failures = sum(int(t[2]) for t in bundle_totals)
    elif trailers:
        # No "All tests" verdict (truncated log): the final trailer is the best total.
        executed, skipped_trailer, failures = (int(x or 0) for x in trailers[-1])
    if bundle_totals or trailers:
        # "failures" in the trailer counts failed assertions, not failed tests, so it is
        # reported but never compared against the per-test verdict count.
        payload["executed"] = {"total": executed, "skipped": skipped_trailer, "failureAssertions": failures}
        payload["consistent"] = executed == len(tests) and skipped_trailer == skipped
    return payload


def write_summary(log_path: pathlib.Path, out_path: pathlib.Path, *, quiet: bool = False) -> int:
    text = log_path.read_text(encoding="utf-8", errors="replace")
    payload = summarize(text, source=str(log_path))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not quiet:
        for r in payload["tests"]:
            print(f"  {r['verdict']:>6}  {r['seconds']:8.1f}s  {r['suite']}/{r['test']}")
        c = payload["counts"]
        print(f"  {c['passed']} passed, {c['failed']} failed, {c['skipped']} skipped, {c['total']} total -> {out_path}")
    return 0 if payload.get("consistent", True) else 3


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("log", type=pathlib.Path)
    parser.add_argument("out", type=pathlib.Path)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    if not args.log.is_file():
        print(f"xctest_summary: missing log {args.log}", file=sys.stderr)
        return 2
    return write_summary(args.log, args.out, quiet=args.quiet)


if __name__ == "__main__":
    raise SystemExit(main())
