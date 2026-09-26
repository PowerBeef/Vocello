#!/usr/bin/env python3
"""Classify the paths a push changed into CI lanes.

Writes `<lane>=true|false` for the lanes swift, ios, python, research, website,
workflows and macos_ui to $GITHUB_OUTPUT (or stdout when unset). An empty or
unknowable diff (first push, dispatch, rewritten history) enables every lane, so
routing can only ever skip work, never invent a pass.

`macos_ui` is the macOS XCUITest bundle's own sources (PA-06). The macOS job
compiles that bundle on every run; when only `macos_ui` routes it, the job
compiles the bundle and skips the deterministic suites, and the TSan job stays
off: no deterministic bundle, sanitizer subset or app target compiles those
sources. The iOS XCUITest sources route to the iOS lane alone, whose job
compiles them.

Each lane is diffed against the last run on this branch in which that lane's
job passed (`CI_HISTORY_PATH`, written by the workflow from `gh run view`), not
against the previous push: `cancel-in-progress` drops the run of a superseded
push, and a docs-only push on top of it must still run the lanes the cancelled
run owed. A lane routing skipped inside a green run counts as proven at that
head. Only push CI's own inputs (ci.yml, its actions, this file) force every
native lane. Without history the diff falls back to $BEFORE_SHA..$HEAD_SHA.
Pull-request runs never count as history: they skip every native job, so a
skip inside one proves nothing about main.

A pull request (PA-23) is diffed against its base ($BASE_SHA..$HEAD_SHA, the
merge commit); the workflow runs only its Linux lanes whatever this reports.

Usage:
  classify_changes.py                      # route the push (GitHub push event)
  classify_changes.py --paths a b c        # classify explicit paths (tests, local use)
"""
from __future__ import annotations

import argparse
import ast
import fnmatch
import functools
import json
import os
from pathlib import Path
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]

LANES = ("swift", "ios", "python", "research", "website", "workflows", "macos_ui")
# The CI job whose success proves a lane ran; research shares the Python job and
# macos_ui the macOS job, which compiles the macOS XCUITest bundle on every run.
LANE_JOBS = {
    "swift": "macOS deterministic tests",
    "ios": "iOS compile check (device SDK)",
    "python": "Python tests (linux)",
    "research": "Python tests (linux)",
    "website": "Website deterministic checks",
    "macos_ui": "macOS deterministic tests",
}
# Jobs that route with a lane and must also have passed before its base
# advances. Without the TSan job here, a run whose deterministic tests passed
# but whose sanitizer failed would let the next unrelated push skip TSan.
# A companion absent from a run (an older workflow) does not block.
LANE_COMPANION_JOBS = {
    "swift": ("macOS ThreadSanitizer subset",),
}

# Tracked Claude Code configuration (settings, skills, subagents, rules).
CLAUDE_CONFIG_SUFFIXES = (".json", ".md", ".py", ".sh")

# Owned sources that no iOS target compiles. Anything else under Sources/ or
# Tests/ can change the device build.
MACOS_ONLY = (
    "Sources/Views/*",
    "Sources/ViewModels/*",
    "Sources/Models/*",
    "Sources/Services/*",
    "Sources/VocelloCLI/*",
    "Tests/VocelloMacUITests/*",
)

# Sources that only an XCUITest bundle compiles: no deterministic bundle, TSan
# subset or app target reads them, so they never route to the swift lane. The
# macOS bundle's sources route to macos_ui, the iOS bundles' to ios.
# Tests/UIAutomationSupport stays a swift input: VocelloCoreTests compiles part
# of it (project.yml), and it reaches both XCUITest bundles.
MACOS_UI_TEST_SOURCES = ("Tests/VocelloMacUITests/",)
IOS_UI_TEST_SOURCES = ("Tests/VocelloiOSUITests/",)
SHARED_UI_TEST_SOURCES = ("Tests/UIAutomationSupport/",)

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
SWIFT_PARITY_FIXTURES = ("scripts/tests/fixtures/language_normalization_v2.json",)
BUILD_CONFIGS = ("config/build-output-policy.json", "config/apple-platform-capability-matrix.json",
                 "config/toolchain.json")
# Validated on Linux by the contracts job; the macOS gate does not need them.
ROADMAP_FILES = ("config/roadmap.json", "config/roadmap-archive.json")
# The macOS job runs the compile, the deterministic bundles, the CLI identity
# step and the UI-test bundle compile, nothing else: the contract gate (MV-04)
# and every Python test, benchmark evidence and its validator included, run on
# Linux. So only these drivers, and the scripts/ modules their Python imports
# (followed by `python_import_closure`), are its inputs. The build-output
# policy is loaded by every native build through scripts/lib/build_paths.sh,
# which is how a shared library such as scripts/lib/jsonio.py reaches it.
MACOS_LANE_SCRIPTS = ("scripts/macos_test.sh", "scripts/build.sh", "scripts/regenerate_project.sh",
                      "scripts/generate_cli_scheme.py", "scripts/generate_ios_logic_scheme.py",
                      "scripts/build_output_policy.py", "scripts/cli_version_contract.py",
                      "scripts/ci/restore_mtimes.py", "scripts/lib/xctest_summary.py",
                      "scripts/lib/storage_preflight.py", "scripts/build_ui_test_bundles.sh")
# Inputs of the iOS generic compile (and its UI-test bundle) besides the sources themselves.
IOS_BUILD_SCRIPTS = ("scripts/build_foundation_targets.sh", "scripts/regenerate_project.sh",
                     "scripts/generate_cli_scheme.py", "scripts/generate_ios_logic_scheme.py",
                     "scripts/lib/ios_platform_preflight.py", "scripts/lib/storage_preflight.py",
                     "scripts/build_output_policy.py", "scripts/build_ui_test_bundles.sh")
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


def _imported_script_modules(path: Path) -> set[Path]:
    """The scripts/ and scripts/lib/ files one Python file imports.

    Scripts reach their helpers as `from lib import jsonio`, `lib.jsonio` or,
    after putting scripts/lib on sys.path, a bare `import jsonio`; imports
    inside `try` blocks and functions count too."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return set()
    scripts = REPO_ROOT / "scripts"
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module == "lib":
                names.extend(f"lib.{alias.name}" for alias in node.names)
            else:
                names.append(node.module)
    found: set[Path] = set()
    for name in names:
        parts = name.split(".")
        if parts[0] == "lib" and len(parts) > 1:
            candidates = [scripts / "lib" / f"{parts[1]}.py"]
        else:
            candidates = [scripts / f"{parts[0]}.py", scripts / "lib" / f"{parts[0]}.py"]
        found.update(candidate for candidate in candidates if candidate.is_file())
    return found


@functools.lru_cache(maxsize=None)
def python_import_closure(entry_points: tuple[str, ...]) -> frozenset[str]:
    """Repository-relative Python files the entry points load, themselves included."""
    pending = [REPO_ROOT / entry for entry in entry_points if entry.endswith(".py")]
    seen: set[Path] = set()
    while pending:
        current = pending.pop()
        if current in seen or not current.is_file():
            continue
        seen.add(current)
        pending.extend(_imported_script_modules(current) - seen)
    return frozenset(path.relative_to(REPO_ROOT).as_posix() for path in seen)


def _is_swift(path: str) -> bool:
    """Inputs of the macOS job: the compile and its own driver scripts with their imports."""
    if path.startswith(MACOS_UI_TEST_SOURCES + IOS_UI_TEST_SOURCES):
        return False
    if path.startswith(("Sources/", "Tests/", "QwenVoice.xcodeproj/", "config/xcode-schemes/")):
        return True
    if path == "project.yml" or path.endswith("Package.resolved"):
        return True
    if path.startswith("Packages/"):
        return "/Sources/" in path or path.endswith(PACKAGE_MANIFESTS)
    # Swift tests pin the shipping iPhone memory bands (V-4) and the Fast QC
    # Stage 0 constants (audio QC audit 5.5) to these records.
    if path in (*BUILD_CONFIGS, "config/test-quarantine.json", "config/ios-memory-budget-policy.json",
                "config/audio-qc-stage0-calibration.json"):
        return True
    # Parity fixtures a Swift test scores beside its Python mirror (AQ-02).
    if path in SWIFT_PARITY_FIXTURES:
        return True
    if path in MACOS_LANE_SCRIPTS or path in python_import_closure(MACOS_LANE_SCRIPTS):
        return True
    return path.startswith("scripts/lib/") and path.endswith(".sh")


def _is_ios(path: str) -> bool:
    """Inputs of the generic device-SDK compile."""
    if path in ("project.yml", *IOS_BUILD_SCRIPTS, *BUILD_CONFIGS) or path.endswith("Package.resolved"):
        return True
    if path in python_import_closure(IOS_BUILD_SCRIPTS):
        return True
    if path.startswith("QwenVoice.xcodeproj/") or (path.startswith("scripts/lib/") and path.endswith(".sh")):
        return True
    if path.startswith("Packages/"):
        return "/Sources/" in path or path.endswith(PACKAGE_MANIFESTS)
    if path.startswith("Sources/Resources/"):
        return path.endswith(".xcstrings")
    return (path.startswith("Sources/") or path.startswith("Tests/")) and not _match(path, MACOS_ONLY)


def _is_macos_ui(path: str) -> bool:
    """Sources of the macOS XCUITest bundle that are not already swift-lane compile inputs."""
    return path.startswith(MACOS_UI_TEST_SOURCES + SHARED_UI_TEST_SOURCES)


def _is_python(path: str) -> bool:
    # Claude Code settings, skills, subagents and rule frontmatter execute or
    # route repository code; config-only changes must exercise the hook adapter
    # and wiring tests even when no script changed.
    if path.startswith(".claude/"):
        return path.endswith(CLAUDE_CONFIG_SUFFIXES)
    if path.startswith("scripts/"):
        return not path.endswith(".md")
    if path.startswith("Packages/"):
        # Governance JSON is read by the contract tests; sources are compile inputs.
        return path.endswith(".json")
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
    # Shared libraries (jsonio, language_metrics, audio_qc, ...) are imported by
    # research tooling under names the prefixes cannot see; the local check
    # already selects their research consumers, so CI runs them too.
    if path.startswith("scripts/lib/") and path.endswith(".py"):
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
        if _is_macos_ui(path):
            lanes["macos_ui"] = True
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
        if not isinstance(jobs, dict) or sha == head or run.get("event") == "pull_request":
            continue
        run_passed = run.get("conclusion") == "success"
        def job_proven(conclusion: object) -> bool:
            # A job routing skipped inside a run that passed is proven at that
            # head too; a skip inside a failed or cancelled run proves nothing.
            return conclusion == "success" or (conclusion == "skipped" and run_passed)

        for lane, job in LANE_JOBS.items():
            proven = job_proven(jobs.get(job)) and all(
                companion not in jobs or job_proven(jobs[companion])
                for companion in LANE_COMPANION_JOBS.get(lane, ())
            )
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


def route_pull_request(head: str, base: str, cwd: str | None = None) -> tuple[dict[str, bool], str]:
    """Lanes for a pull request: its merge commit against the base it targets."""
    if is_ancestor_commit(base, head, cwd):
        paths = diff_paths(base, head, cwd)
        return classify(paths), f"{len(paths)} changed path(s) against the pull request base"
    return classify([]), "pull request base unknown, every lane runs"


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
    elif os.environ.get("EVENT_NAME") == "pull_request" and os.environ.get("HEAD_SHA"):
        lanes, reason = route_pull_request(os.environ["HEAD_SHA"], os.environ.get("BASE_SHA", ""))
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
