#!/usr/bin/env python3
"""Summarize an XCTest or `swift test` log into the repository's test-results.json shape.

One writer for every lane. `scripts/ui_test.sh` used to carry this parser inline
and `scripts/macos_test.sh` had none, so the macOS unit lane produced plain logs
only. Both now call this module, and triage tooling reads one format:

    {"schemaVersion": 1, "tests": [{"test": "...", "verdict": "passed|failed|skipped", "seconds": 0.0}, ...],
     "counts": {"passed": N, "failed": N, "skipped": N, "total": N}, "source": "<log path>"}

`counts` and `source` are additive; schemaVersion 1 readers that only know
`tests` keep working. XCTest's "Test Case '-[Suite test]' passed|failed|skipped (0.123
seconds)" lines are parsed and its "Executed N tests" trailer is cross-checked when
present. Swift Testing, which only `swift test` runs here (the owned package; the raw
xctest runner of the Xcode bundles never runs it), prints one "✔ Test ... passed" or
"✘ Test ... failed" line per test (a parametrized test's cases share one line) and a
"Test run with N tests" trailer: those tests join `tests` with suite "swift-testing",
`swiftTesting` carries their trailer, and a run whose Swift Testing library started but
never printed its trailer is incomplete.

Usage:
    python3 scripts/lib/xctest_summary.py LOG OUT.json [--quiet]
    exit 0 when the log parsed (even with failures); 3 when the trailer count
    disagrees with the parsed cases, or --require-complete lacks terminal evidence.
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
    r"Test Suite '(?:All|Selected) tests' (?:passed|failed) at [^\n]*\n[ \t]*Executed (\d+) tests?, with (?:(\d+) tests? skipped and )?(\d+) failures?"
)
BUNDLE_START = re.compile(r"Test Suite '(?:All|Selected) tests' started at")
# Swift Testing: one terminal line per test, the run trailer, and the banner it prints first.
ST_TEST = re.compile(
    r'^[✔✘] Test (?!run with )(?:"(?P<display>[^"]+)"|(?P<name>\S.*?))'
    r'(?: with (?P<cases>\d+) test cases?)? (?P<verdict>passed|failed) after (?P<seconds>\d+(?:\.\d+)?) seconds',
    re.M,
)
ST_SKIPPED = re.compile(r'^➜ Test (?:"(?P<display>[^"]+)"|(?P<name>\S.*?)) skipped', re.M)
ST_RUN = re.compile(r"^[✔✘] Test run with (\d+) tests? in \d+ suites? (passed|failed)", re.M)
ST_STARTED = re.compile(r"^↳ Testing Library Version:", re.M)


def summarize(log_text: str, source: str = "", *, require_complete: bool = False) -> dict:
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
    xctest_cases = len(tests)
    swift_testing = [
        {
            "suite": "swift-testing",
            "test": m.group("display") or m.group("name"),
            "verdict": m.group("verdict"),
            "seconds": float(m.group("seconds")),
            **({"cases": int(m.group("cases"))} if m.group("cases") else {}),
        }
        for m in ST_TEST.finditer(log_text)
    ] + [
        {"suite": "swift-testing", "test": m.group("display") or m.group("name"), "verdict": "skipped", "seconds": 0.0}
        for m in ST_SKIPPED.finditer(log_text)
    ]
    tests += swift_testing
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
        xctest_skipped = sum(1 for t in tests[:xctest_cases] if t["verdict"] == "skipped")
        payload["consistent"] = executed == xctest_cases and skipped_trailer == xctest_skipped
    st_runs = ST_RUN.findall(log_text)
    st_started = bool(ST_STARTED.search(log_text)) or bool(swift_testing)
    if st_started:
        payload["swiftTesting"] = {"total": sum(int(total) for total, _ in st_runs),
                                   "trailers": len(st_runs), "tests": len(swift_testing)}
        st_consistent = bool(st_runs) and payload["swiftTesting"]["total"] == len(swift_testing)
        payload["consistent"] = bool(payload.get("consistent", True) and st_consistent)
    if require_complete:
        # A partial case list or a nested-suite trailer cannot certify a run.
        # Selected XCTest invocations have the same terminal contract as All tests;
        # a Swift Testing run that started must have printed its trailer.
        payload["complete"] = bool(tests[:xctest_cases] and bundle_totals
                                   and len(BUNDLE_START.findall(log_text)) == len(bundle_totals)
                                   and (not st_started or st_runs))
        payload["consistent"] = bool(payload.get("consistent") and payload["complete"])
    return payload


def write_summary(log_path: pathlib.Path, out_path: pathlib.Path, *, quiet: bool = False,
                  require_complete: bool = False) -> int:
    text = log_path.read_text(encoding="utf-8", errors="replace")
    payload = summarize(text, source=str(log_path), require_complete=require_complete)
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
    parser.add_argument("--require-complete", action="store_true",
                        help="require a nonempty, complete All/Selected tests run")
    args = parser.parse_args(argv)
    if not args.log.is_file():
        print(f"xctest_summary: missing log {args.log}", file=sys.stderr)
        return 2
    return write_summary(args.log, args.out, quiet=args.quiet, require_complete=args.require_complete)


if __name__ == "__main__":
    raise SystemExit(main())
