#!/usr/bin/env python3
"""One line per finished lane run: what ran, on which commit, how long, and why it failed.

62% of retained UI-lane minutes went to failed runs, and run.json records only a status
and an exit code, so infrastructure failures could not be told from product failures
(workflow audit W-03, P1-1). Each finished run directory is classified by the same
read-only triage `scripts/dev.sh triage` uses (scripts/workflow_diagnostics.py) and
appended to build/artifacts/diagnostics/lane-ledger.jsonl, an untracked, policy-owned
file. run.json's schema is untouched. Recording never fails the lane that calls it.

    python3 scripts/lane_ledger.py record RUN_DIR --lane NAME
    python3 scripts/lane_ledger.py backfill          # classify retained runs not yet recorded
    python3 scripts/lane_ledger.py kpi [--days N] [--json]
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = Path("build/artifacts/diagnostics/lane-ledger.jsonl")
RUN_ROOTS = ("build/artifacts/ui-tests/macos", "build/artifacts/ui-tests/ios", "build/artifacts/macos/tests")
STAMP = re.compile(r"(\d{8})-(\d{6})")
# Signatures of failures that are the host's or the device's, not the product's, as they
# appear in a UI lane's xcodebuild.log. The first match names the run's infrastructure cause.
INFRASTRUCTURE = (
    ("automation-mode", re.compile(r"Timed out while enabling automation mode", re.I)),
    ("device-locked", re.compile(r"device (?:is|was) (?:passcode )?(?:locked|protected)|Unlock .* to continue", re.I)),
    ("install-or-launch", re.compile(r"Failed to (?:install|launch)|Could not (?:install|launch)", re.I)),
    ("test-runner-lost", re.compile(r"Lost connection to the test manager|test runner (?:exited|crashed) "
                                    r"unexpectedly|Early unexpected exit", re.I)),
    ("developer-mode", re.compile(r"Developer Mode (?:is )?disabled", re.I)),
    ("signing", re.compile(r"No signing certificate|requires a provisioning profile|Code Signing Error", re.I)),
)


def _triage(run_dir: Path) -> dict:
    spec = importlib.util.spec_from_file_location("workflow_diagnostics", ROOT / "scripts/workflow_diagnostics.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.triage(run_dir)


def _iso(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _stamp_time(name: str) -> dt.datetime | None:
    match = STAMP.search(name)
    if not match:
        return None
    # Run directory names carry the host's local time.
    return dt.datetime.strptime("".join(match.groups()), "%Y%m%d%H%M%S").astimezone()


def lane_name(run_dir: Path, metadata: dict | None) -> str:
    if metadata and metadata.get("platform") and metadata.get("lane"):
        name = f"{metadata['platform']}-ui-{metadata['lane']}"
        return f"{name}:{metadata['scenario']}" if metadata.get("scenario") else name
    if run_dir.name.startswith("tsan-"):
        return "macos-tsan"
    if run_dir.name.startswith("mac-test-"):
        return "macos-deterministic"
    if run_dir.name.startswith("mac-shipped-"):
        return "macos-shipped-config"
    return run_dir.parent.name


def entry_for(run_dir: Path, lane: str | None = None, sha: str | None = None) -> dict:
    run_dir = run_dir.resolve()
    metadata = None
    run_json = run_dir / "run.json"
    if run_json.is_file():
        try:
            metadata = json.loads(run_json.read_text(encoding="utf-8"))
        except ValueError:
            metadata = None
    report = _triage(run_dir)
    started = _iso((metadata or {}).get("startedAt")) or _stamp_time(run_dir.name)
    finished = _iso((metadata or {}).get("finishedAt"))
    if finished is None:
        terminal = [run_dir / name for name in ("verdict.txt", "run.json", "required-steps.json") if (run_dir / name).exists()]
        if terminal:
            finished = dt.datetime.fromtimestamp(max(p.stat().st_mtime for p in terminal)).astimezone()
    duration = (finished - started).total_seconds() if started and finished and finished >= started else None
    try:
        relative = run_dir.relative_to(ROOT).as_posix()
    except ValueError:
        relative = run_dir.as_posix()
    infrastructure = None
    log = run_dir / "xcodebuild.log"
    if report["verdict"] != "PASS" and log.is_file():
        text = log.read_text(encoding="utf-8", errors="replace")[-2_000_000:]
        infrastructure = next((name for name, pattern in INFRASTRUCTURE if pattern.search(text)), None)
    return {
        "schemaVersion": 1,
        "runDirectory": relative,
        "infrastructure": infrastructure,
        "lane": lane or lane_name(run_dir, metadata),
        "verdict": report["verdict"],
        "failedTests": len(report["failedTests"]),
        "failedSteps": [step.get("step") for step in report["failedSteps"]][:10],
        "exitCode": (metadata or {}).get("exitCode"),
        "startedAt": started.isoformat() if started else None,
        "durationSeconds": round(duration, 1) if duration is not None else None,
        "commit": sha,
    }


def _ledger_path(root: Path) -> Path:
    return root / LEDGER


def recorded(root: Path) -> list[dict]:
    path = _ledger_path(root)
    if not path.is_file():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entries.append(json.loads(line))
        except ValueError:
            continue
    return entries


def append(root: Path, entry: dict) -> bool:
    if any(existing.get("runDirectory") == entry["runDirectory"] for existing in recorded(root)):
        return False
    path = _ledger_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")
    return True


def _head(root: Path) -> str | None:
    result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return None
    dirty = subprocess.run(["git", "-C", str(root), "status", "--porcelain"], capture_output=True, text=True, check=False)
    return result.stdout.strip() + ("-dirty" if dirty.stdout.strip() else "")


def run_directories(root: Path) -> list[Path]:
    found = []
    for base in RUN_ROOTS:
        directory = root / base
        if directory.is_dir():
            found += sorted(child for child in directory.iterdir() if child.is_dir() and STAMP.search(child.name))
    return found


def kpi(entries: list[dict], days: int, now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now().astimezone()
    lanes: dict[str, dict] = {}
    for entry in entries:
        started = _iso(entry.get("startedAt"))
        if started and (now - started).total_seconds() > days * 86400:
            continue
        lane = lanes.setdefault(entry["lane"], {"runs": 0, "passed": 0, "minutes": 0.0, "failedMinutes": 0.0,
                                                 "verdicts": {}})
        lane["runs"] += 1
        minutes = (entry.get("durationSeconds") or 0) / 60
        lane["minutes"] += minutes
        if entry["verdict"] == "PASS":
            lane["passed"] += 1
        else:
            lane["failedMinutes"] += minutes
        lane["verdicts"][entry["verdict"]] = lane["verdicts"].get(entry["verdict"], 0) + 1
        if entry.get("infrastructure"):
            causes = lane.setdefault("infrastructure", {})
            causes[entry["infrastructure"]] = causes.get(entry["infrastructure"], 0) + 1
    for lane in lanes.values():
        lane["passRate"] = round(lane["passed"] / lane["runs"], 3) if lane["runs"] else None
        lane["failedMinuteShare"] = round(lane["failedMinutes"] / lane["minutes"], 3) if lane["minutes"] else None
        lane["minutes"] = round(lane["minutes"], 1)
        lane["failedMinutes"] = round(lane["failedMinutes"], 1)
    return {"days": days, "lanes": dict(sorted(lanes.items()))}


def print_kpi(summary: dict) -> None:
    print(f"Lane runs in the last {summary['days']} days (classified by scripts/workflow_diagnostics.py triage):")
    for name, lane in summary["lanes"].items():
        share = "n/a" if lane["failedMinuteShare"] is None else f"{lane['failedMinuteShare']:.0%}"
        classes = ", ".join(f"{verdict} {count}" for verdict, count in sorted(lane["verdicts"].items()))
        infrastructure = ", ".join(f"{cause} {count}" for cause, count in sorted(lane.get("infrastructure", {}).items()))
        print(f"  {name}: {lane['passed']}/{lane['runs']} passed, {lane['minutes']:.0f} min, "
              f"failed-minute share {share} ({classes})"
              + (f"; infrastructure: {infrastructure}" if infrastructure else ""))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=ROOT)
    sub = parser.add_subparsers(dest="command", required=True)
    record = sub.add_parser("record", help="classify and append one finished run directory")
    record.add_argument("run_directory", type=Path)
    record.add_argument("--lane")
    sub.add_parser("backfill", help="classify retained run directories that are not recorded yet")
    summary = sub.add_parser("kpi", help="pass rate and failed-minute share per lane")
    summary.add_argument("--days", type=int, default=30)
    summary.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.command == "record":
        try:
            entry = entry_for(args.run_directory, args.lane, _head(root))
            print(f"lane ledger: {entry['lane']} {entry['verdict']}"
                  f"{'' if append(root, entry) else ' (already recorded)'}")
        except Exception as error:  # noqa: BLE001 - recording never fails the lane that calls it
            print(f"lane ledger: not recorded ({error})", file=sys.stderr)
        return 0
    if args.command == "backfill":
        added = 0
        for run_dir in run_directories(root):
            try:
                added += append(root, entry_for(run_dir))
            except Exception as error:  # noqa: BLE001
                print(f"lane ledger: skipped {run_dir.name} ({error})", file=sys.stderr)
        print(f"lane ledger: {added} retained run(s) added -> {LEDGER}")
        return 0
    result = kpi(recorded(root), args.days)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print_kpi(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
