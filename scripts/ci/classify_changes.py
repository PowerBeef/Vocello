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
run owed. A lane routing skipped inside a green run counts as proven at that
head. Only push CI's own inputs (ci.yml, its actions, this file) force every
native lane. Without history the diff falls back to $BEFORE_SHA..$HEAD_SHA.

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
    "Sources/VocelloCLI/*",
    "Sources/QwenVoiceNative/*",
    "Sources/QwenVoiceEngineService/*",
    "Sources/QwenVoiceEngineSupport/*",
    "Tests/VocelloMacUITests/*",
    "Tests/VocelloEngineIntegrationTests/*",
)

# Push CI's own inputs: when they change, every native lane reruns. Other
# workflows (nightly, release, security, promotion, dependabot) and the
# templates change nothing push CI executes; their action pins are checked by
# the supply-chain tests on the Python lane and by the contracts job.
WORKFLOW_INPUTS = (".github/workflows/ci.yml", "scripts/ci/classify_changes.py")
WORKFLOW_PREFIXES = (".github/actions/",)
NATIVE_LANES = ("swift", "ios", "python")

# Under Packages/ the iOS compile reads the package sources and manifests; the
# governance JSON is a contract-gate input (macOS job) and the markdown is prose.
PACKAGE_MANIFESTS = ("Package.swift", "Package.resolved")
BUILD_CONFIGS = ("config/build-output-policy.json", "config/apple-platform-capability-matrix.json",
                 "config/toolchain.json")
# Validated on Linux by the contracts job; the macOS gate does not need them.
ROADMAP_FILES = ("config/roadmap.json", "config/roadmap-archive.json")
# The macOS job runs only the darwin-only pytest lane (test_benchmark_history)
# plus the contract gate; every other test module runs on Linux.
DARWIN_TEST_INPUTS = ("scripts/tests/test_benchmark_history.py", "scripts/tests/conftest.py")
# Inputs of the iOS generic compile besides the sources themselves.
IOS_BUILD_SCRIPTS = ("scripts/build_foundation_targets.sh", "scripts/regenerate_project.sh",
                     "scripts/generate_cli_scheme.py", "scripts/generate_ios_logic_scheme.py",
                     "scripts/lib/ios_platform_preflight.py", "scripts/lib/storage_preflight.py",
                     "scripts/build_output_policy.py")
BENCHMARK_EVIDENCE_PREFIXES = ("benchmarks/runs/", "benchmarks/baselines/")
BENCHMARK_EVIDENCE_FILES = ("benchmarks/HISTORY.md", "benchmarks/hardware-profiles.json")
RESEARCH_PREFIXES = (
    "delivery_", "prosody_", "analyze_", "audio_", "ios_control_audit", "ios_startup_reliability",
    "check_language", "clone_", "emotion_", "mos_", "bench_", "run_local_delivery", "qualify_delivery",
    "prepare_delivery", "build_emotion", "voice_identity",
    "language_bench", "angry_bilingual", "custom_delivery", "independent_asr",
)
RESEARCH_CONFIG = ("delivery-", "prosody-", "ios-control-audit", "ios-startup-reliability", "language-bench",
                   "voice-identity", "ui-perf-thresholds")


def _match(path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(path, p) for p in patterns)


def _is_workflow_input(path: str) -> bool:
    return path in WORKFLOW_INPUTS or path.startswith(WORKFLOW_PREFIXES)


def _is_benchmark_evidence(path: str) -> bool:
    return (path.startswith(BENCHMARK_EVIDENCE_PREFIXES) or path in BENCHMARK_EVIDENCE_FILES
            or (path.startswith("benchmarks/schema-") and path.endswith(".json")))


def _is_swift(path: str) -> bool:
    """Inputs of the macOS job: the compile, the contract gate and the darwin-only pytest lane."""
    if path.startswith(("Sources/", "Tests/", "QwenVoice.xcodeproj/", "config/xcode-schemes/")):
        return True
    if path in ("project.yml", "README.md", "website/PRODUCT.md") or path.endswith("Package.resolved"):
        return True
    if path.startswith("Packages/"):
        return not path.endswith(".md")
    if path.startswith("config/"):
        return path not in ROADMAP_FILES
    if path.startswith("scripts/tests/"):
        return path in DARWIN_TEST_INPUTS or path.startswith("scripts/tests/fixtures/")
    if path.startswith("scripts/"):
        return not (path.startswith("scripts/hooks/") or path.endswith(".md") or _is_workflow_input(path))
    return _is_benchmark_evidence(path)


def _is_ios(path: str) -> bool:
    """Inputs of the generic device-SDK compile."""
    if path in ("project.yml", *IOS_BUILD_SCRIPTS, *BUILD_CONFIGS) or path.endswith("Package.resolved"):
        return True
    if path.startswith("QwenVoice.xcodeproj/") or (path.startswith("scripts/lib/") and path.endswith(".sh")):
        return True
    if path.startswith("Packages/"):
        return "/Sources/" in path or path.endswith(PACKAGE_MANIFESTS)
    if path.startswith("Sources/Resources/"):
        return path.endswith(".xcstrings")
    return (path.startswith("Sources/") or path.startswith("Tests/")) and not _match(path, MACOS_ONLY)


def _is_python(path: str) -> bool:
    if path.startswith("scripts/"):
        return not path.endswith(".md")
    if path.startswith("benchmarks/"):
        return not path.endswith(".md") or path == "benchmarks/HISTORY.md"
    return (path.startswith(("config/", "Sources/Resources/", ".github/workflows/"))
            or path in ("project.yml", "pytest.ini"))


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
        if _is_workflow_input(path):
            lanes["workflows"] = True
            lanes["swift"] = lanes["ios"] = lanes["python"] = True
        if path.startswith("website/"):
            lanes["website"] = True
        if _is_swift(path):
            lanes["swift"] = True
        if _is_python(path):
            lanes["python"] = True
        if _is_ios(path):
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
        run_passed = run.get("conclusion") == "success"
        for lane, job in LANE_JOBS.items():
            conclusion = jobs.get(job)
            # A job routing skipped inside a run that passed is proven at that
            # head too; a skip inside a failed or cancelled run proves nothing.
            proven = conclusion == "success" or (conclusion == "skipped" and run_passed)
            if bases[lane] is None and proven and is_ancestor_commit(sha, head, cwd):
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
            # classify() already folds a workflow change into the native lanes
            # of the diff it is given; only those lanes' own diffs may report
            # it, or a lane whose green base predates an old workflow change
            # (the rarely run website lane) would rerun every native lane.
            if lane in NATIVE_LANES and verdict["workflows"]:
                lanes["workflows"] = True
            reasons.append(f"{lane}: {len(paths)} path(s) since {base[:8]}")
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
