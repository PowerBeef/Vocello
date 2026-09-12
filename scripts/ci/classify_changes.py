#!/usr/bin/env python3
"""Classify the paths a push changed into CI lanes.

Writes `<lane>=true|false` for the lanes swift, ios, python, research, website
and workflows to $GITHUB_OUTPUT (or stdout when unset). An empty or unknowable
diff (first push, dispatch, rewritten history) enables every lane, so routing
can only ever skip work, never invent a pass.

Each lane is diffed against the last run on this branch in which that lane's
job passed (`CI_HISTORY_PATH`, written by the workflow from `gh run view`), not
against the previous push: `cancel-in-progress` drops the run of a superseded
push, and a docs-only push on top of it must still run the lanes the cancelled
run owed. Without history the diff falls back to $BEFORE_SHA..$HEAD_SHA.

Usage:
  classify_changes.py                      # route the push (GitHub push event)
  classify_changes.py --paths a b c        # classify explicit paths (tests, local use)
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import subprocess
import sys

LANES = ("swift", "ios", "python", "research", "website", "workflows")
# The CI job whose success proves a lane ran; research shares the Python job.
LANE_JOBS = {
    "swift": "macOS deterministic tests",
    "ios": "iOS compile check (device SDK)",
    "python": "Python tests (linux)",
    "research": "Python tests (linux)",
    "website": "Website deterministic checks",
}

# Owned sources that no iOS target compiles. Anything else under Sources/ or
# Tests/ can change the device build.
MACOS_ONLY = (
    "Sources/Views/*",
    "Sources/ViewModels/*",
    "Sources/Models/*",
    "Sources/Services/*",
    "Sources/App/*",
    "Sources/VocelloCLI/*",
    "Sources/QwenVoiceNative/*",
    "Sources/QwenVoiceEngineService/*",
    "Sources/QwenVoiceEngineSupport/*",
    "Tests/VocelloMacUITests/*",
    "Tests/VocelloEngineIntegrationTests/*",
)

SWIFT = ("Sources/*", "Tests/*", "Packages/*", "project.yml", "*Package.resolved",
         "QwenVoice.xcodeproj/*", "config/*", "scripts/*", "benchmarks/*")
IOS_ALWAYS = ("project.yml", "*Package.resolved", "Packages/*", "Sources/Resources/*",
              "scripts/build_foundation_targets.sh", "scripts/regenerate_project.sh", "scripts/lib/*",
              "config/apple-platform-capability-matrix.json", "config/build-output-policy.json")
PYTHON = ("scripts/*", "config/*", "benchmarks/*", "Sources/Resources/*")
RESEARCH_PREFIXES = (
    "delivery_", "prosody_", "analyze_", "audio_", "ios_control_audit", "ios_startup_reliability",
    "check_language", "clone_", "emotion_", "mos_", "bench_", "run_local_delivery", "qualify_delivery",
    "prepare_delivery", "build_emotion", "separability", "voice_identity",
    "language_bench", "angry_bilingual", "custom_delivery", "independent_asr",
)
RESEARCH_CONFIG = ("delivery-", "prosody-", "ios-control-audit", "ios-startup-reliability", "language-bench",
                   "voice-identity", "characterization-fixtures", "ui-perf-thresholds")


def _match(path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(path, p) for p in patterns)


def _is_research(path: str) -> bool:
    name = os.path.basename(path)
    if path.startswith("scripts/tests/"):
        name = name.removeprefix("test_")
    if path.startswith("scripts/") and any(name.startswith(p) for p in RESEARCH_PREFIXES):
        return True
    return path.startswith("config/") and any(name.startswith(p) for p in RESEARCH_CONFIG)


def classify(paths: list[str]) -> dict[str, bool]:
    if not paths:
        return {lane: True for lane in LANES}
    lanes = {lane: False for lane in LANES}
    for path in paths:
        if path.startswith(".github/"):
            lanes["workflows"] = True
            lanes["swift"] = lanes["ios"] = lanes["python"] = True
        if path.startswith("website/"):
            lanes["website"] = True
        if _match(path, SWIFT):
            lanes["swift"] = True
        if _match(path, PYTHON):
            lanes["python"] = True
        if _match(path, IOS_ALWAYS):
            lanes["ios"] = True
        elif (path.startswith("Sources/") or path.startswith("Tests/")) and not _match(path, MACOS_ONLY):
            lanes["ios"] = True
        if _is_research(path):
            lanes["research"] = True
    return lanes


def _git(*arguments: str, cwd: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *arguments], capture_output=True, text=True, cwd=cwd)


def is_ancestor_commit(sha: str, head: str, cwd: str | None = None) -> bool:
    if not sha or set(sha) == {"0"}:
        return False
    if _git("cat-file", "-t", sha, cwd=cwd).stdout.strip() != "commit":
        return False
    return _git("merge-base", "--is-ancestor", sha, head, cwd=cwd).returncode == 0


def diff_paths(base: str, head: str, cwd: str | None = None) -> list[str]:
    result = _git("diff", "--name-only", f"{base}..{head}", cwd=cwd)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git diff failed")
    return [line for line in result.stdout.splitlines() if line]


def load_history(path: str | None) -> list[dict] | None:
    """Recent runs of this workflow on this branch: [{headSha, jobs: {name: conclusion}}]."""
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            history = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return history if isinstance(history, list) else None


def lane_bases(history: list[dict], head: str, cwd: str | None = None) -> dict[str, str | None]:
    """Per lane, the newest run head (an ancestor of `head`) whose job succeeded."""
    bases: dict[str, str | None] = {lane: None for lane in LANE_JOBS}
    for run in history:
        sha = str(run.get("headSha") or "")
        jobs = run.get("jobs") or {}
        if not isinstance(jobs, dict) or sha == head:
            continue
        for lane, job in LANE_JOBS.items():
            if bases[lane] is None and jobs.get(job) == "success" and is_ancestor_commit(sha, head, cwd):
                bases[lane] = sha
    return bases


def route_push(head: str, before: str, history: list[dict] | None, cwd: str | None = None) -> tuple[dict[str, bool], str]:
    """Lanes for a push and the reason, using per-lane green bases when known."""
    if history:
        bases = lane_bases(history, head, cwd)
        lanes = {lane: False for lane in LANES}
        reasons = []
        for lane, base in bases.items():
            if base is None:
                lanes[lane] = True
                reasons.append(f"{lane}: no prior green run, runs")
                continue
            paths = diff_paths(base, head, cwd)
            verdict = classify(paths)
            lanes[lane] = verdict[lane]
            if verdict["workflows"]:
                lanes["workflows"] = True
            reasons.append(f"{lane}: {len(paths)} path(s) since {base[:8]}")
        if lanes["workflows"]:
            lanes["swift"] = lanes["ios"] = lanes["python"] = True
        return lanes, "; ".join(reasons)
    if is_ancestor_commit(before, head, cwd):
        paths = diff_paths(before, head, cwd)
        return classify(paths), f"{len(paths)} changed path(s) since the previous push"
    return classify([]), "empty or unknowable diff, every lane runs"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--paths", nargs="*", help="classify these paths instead of the push diff")
    args = parser.parse_args(argv)
    if args.paths is not None:
        lanes = classify(args.paths)
        reason = f"{len(args.paths)} explicit path(s)" if args.paths else "no paths, every lane runs"
    elif os.environ.get("EVENT_NAME") == "push" and os.environ.get("HEAD_SHA"):
        lanes, reason = route_push(
            os.environ["HEAD_SHA"], os.environ.get("BEFORE_SHA", ""),
            load_history(os.environ.get("CI_HISTORY_PATH")),
        )
    else:
        lanes, reason = classify([]), "not a push, every lane runs"
    lines = [f"{lane}={'true' if on else 'false'}" for lane, on in lanes.items()]
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    print(f"routing ({reason}): " + " ".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
