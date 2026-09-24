#!/usr/bin/env python3
"""Path-aware local verification for Vocello: the inner loop and the pre-push check.

Nothing here blocks a commit; CI on push is the gate. `check` runs what the dirty
tree needs (lint, contracts, selected Python tests, the native lanes the changed
paths touch) and `--dry-run` prints that plan. Device, model, UI and release lanes
are never scheduled from here.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEST_CLASS_PATTERN = re.compile(r"\b(?:final\s+)?class\s+([A-Za-z_][A-Za-z0-9_]*)\s*:\s*XCTestCase\b")
# Tooling whose change means every Python test is a consumer.
FULL_PYTHON_PATTERNS = (
    "scripts/development_workflow.py",
    "scripts/lib/",
    "scripts/tests/fixtures/",
    "config/toolchain.json",
    "config/build-output-policy.json",
)
# Owned Swift that every test bundle links; a change here runs the whole macOS lane.
CORE_SWIFT_PREFIXES = ("Sources/QwenVoiceCore/", "Sources/SharedSupport/", "Packages/", "project.yml")


class WorkflowError(RuntimeError):
    pass


def _git(*args: str) -> bytes:
    completed = subprocess.run(["git", "-C", os.fspath(ROOT), *args], stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, check=False)
    if completed.returncode != 0:
        raise WorkflowError(completed.stderr.decode("utf-8", errors="replace").strip() or f"git {' '.join(args)} failed")
    return completed.stdout


# `check --since REF` exports this so the contract gate's Python selection (a
# child process) plans for the same committed-plus-dirty path set.
SINCE_ENV = "QVOICE_CHANGED_SINCE"


def changed_paths(since: str | None = None) -> list[str]:
    """Dirty paths, plus every path changed between `since` (or $QVOICE_CHANGED_SINCE) and HEAD."""
    since = since or os.environ.get(SINCE_ENV) or None
    queries = [("diff", "--name-only", "-z"), ("diff", "--cached", "--name-only", "-z"),
               ("ls-files", "--others", "--exclude-standard", "-z")]
    if since:
        queries.append(("diff", "--name-only", "-z", f"{since}...HEAD"))
    paths: set[str] = set()
    for args in queries:
        paths.update(part.decode("utf-8", errors="surrogateescape") for part in _git(*args).split(b"\0") if part)
    return sorted(paths)


def _load(relative: str):
    spec = importlib.util.spec_from_file_location(Path(relative).stem, ROOT / relative)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def lanes_for(paths: list[str]) -> dict[str, bool]:
    """Same routing CI uses (scripts/ci/classify_changes.py), except for an empty path set.

    CI treats an empty diff as unknowable and runs every lane; locally it is a
    clean tree, which has nothing to verify (`check --since REF` plans for
    committed work).
    """
    classify_changes = _load("scripts/ci/classify_changes.py")
    if not paths:
        return {lane: False for lane in classify_changes.LANES}
    return classify_changes.classify(paths)


def python_test_selection(paths: list[str], *, root: Path | None = None) -> dict:
    """Reverse literal dependencies (imports, subprocess paths, config names), transitively.

    Basename matching deliberately over-selects. When an input has no known test
    consumer, or tooling everything depends on changed, the whole suite runs.
    """
    root = root or ROOT
    agent_inputs = [p for p in paths if p.startswith(".claude/")
                    and p.endswith((".json", ".md", ".py", ".sh"))]
    inputs = [p for p in paths if p.startswith(("scripts/", "config/"))
              or p in {"project.yml", "Package.resolved"}] + agent_inputs
    if any(p.startswith(FULL_PYTHON_PATTERNS) for p in paths):
        return {"mode": "full", "tests": [], "reason": "shared tooling changed"}
    modules = sorted(root.glob("scripts/tests/**/test_*.py"))
    test_paths = {p.relative_to(root).as_posix() for p in modules}
    texts = {p.relative_to(root).as_posix(): p.read_text(encoding="utf-8")
             for p in (root / "scripts").rglob("*.py") if p.is_file() and "__pycache__" not in p.parts}
    selected: set[str] = set()
    if agent_inputs:
        selected.update({"scripts/tests/test_agent_hooks.py"})
    for changed in inputs:
        if not (root / changed).is_file():
            return {"mode": "full", "tests": [], "reason": "deleted or missing tooling input"}
        affected = {changed}
        while True:
            tokens = {Path(p).name for p in affected} | {Path(p).stem for p in affected if p.endswith(".py")}
            pattern = re.compile(r"(?<![\w-])(?:" + "|".join(re.escape(t) for t in sorted(tokens)) + r")(?![\w-])")
            expanded = affected | {p for p, text in texts.items() if pattern.search(text)}
            if expanded == affected:
                break
            affected = expanded
        tests = affected & test_paths
        if not tests and changed in agent_inputs:
            continue  # Claude settings, skill, subagent and rule metadata are covered above
        if not tests:
            return {"mode": "full", "tests": [], "reason": "no known test consumer for changed input"}
        selected.update(tests)
    if not inputs:
        return {"mode": "none", "tests": [], "reason": "no tooling inputs changed"}
    return {"mode": "selected", "tests": sorted(selected), "reason": "transitive local test consumers"}


PYTEST = ["python3", "-m", "pytest", "-n", "auto"]


def python_test_commands(selection: dict) -> list[list[str]]:
    if selection["mode"] == "full":
        return [[*PYTEST]]
    if not selection["tests"]:
        return []
    return [[*PYTEST, *selection["tests"]]]


def changed_swift_test_classes(paths: list[str]) -> list[str]:
    classes: set[str] = set()
    for relative in paths:
        if relative.endswith(".swift") and relative.startswith(("Tests/VocelloCoreTests/", "Tests/VocelloiOSLogicTests/")):
            path = ROOT / relative
            if path.is_file():
                classes.update(TEST_CLASS_PATTERN.findall(path.read_text(encoding="utf-8")))
    return sorted(classes)


# ---------------------------------------------------------------- command builders

def lint_commands(paths: list[str]) -> list[list[str]]:
    commands: list[list[str]] = [["git", "diff", "--check"]]
    present = [p for p in paths if (ROOT / p).exists()]  # a committed range can include deletions
    if present:
        commands.append(["python3", "scripts/privacy_scan.py", "--paths", *present])
    shell = [p for p in paths if p.endswith(".sh") and (ROOT / p).is_file()]
    if shell and _which("shellcheck"):
        commands.append(["shellcheck", "-x", "-S", "warning", *shell])
    elif shell:
        print(
            f"==> [dev] shellcheck is not on PATH; {len(shell)} changed shell script(s) are not linted "
            "(config/toolchain.json pins the version; scripts/install_pinned_tools.sh installs it)",
            file=sys.stderr, flush=True,
        )
    swift = [p for p in paths if p.endswith(".swift") and (ROOT / p).is_file()
             and p.startswith(("Sources/", "Tests/"))]
    if swift and _which("swiftlint"):
        commands.append(["swiftlint", "lint", "--quiet", "--strict", "--config", ".swiftlint.yml", *swift])
        pinned, installed = _pinned_version("swiftlint"), _installed_version(["swiftlint", "version"])
        if pinned and installed != pinned:
            print(
                f"==> [dev] swiftlint {installed or 'of unknown version'} is not the pinned {pinned}; its "
                "advisory findings can differ (scripts/install_pinned_tools.sh swiftlint installs the pin)",
                file=sys.stderr, flush=True,
            )
    elif swift:
        print(
            f"==> [dev] swiftlint is not on PATH; {len(swift)} changed Swift file(s) are not linted "
            "(config/toolchain.json pins the version; scripts/install_pinned_tools.sh swiftlint installs it)",
            file=sys.stderr, flush=True,
        )
    return commands


def _pinned_version(tool: str) -> str | None:
    """The release-artifact version config/toolchain.json pins for `tool`, if any."""
    try:
        manifest = json.loads((ROOT / "config/toolchain.json").read_text(encoding="utf-8"))
        return str(manifest["artifactPins"][tool]["version"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _installed_version(command: list[str]) -> str | None:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    lines = completed.stdout.strip().splitlines()
    return lines[0].strip() if completed.returncode == 0 and lines else None


# XCUITest-only sources: no deterministic macOS bundle compiles them, so they
# never make a Swift change "product" (their bundles compile via ui_bundle_mode).
UI_TEST_ONLY_SOURCES = ("Tests/VocelloMacUITests/", "Tests/VocelloiOSUITests/")


def swift_test_commands(paths: list[str], *, everything: bool = False) -> list[list[str]]:
    if everything or any(p.startswith(CORE_SWIFT_PREFIXES) for p in paths):
        return [["scripts/macos_test.sh", "test"]]
    classes = changed_swift_test_classes(paths)
    product = [p for p in paths if p.startswith(("Sources/", "Tests/")) and p.endswith(".swift")
               and not p.startswith(("Tests/VocelloCoreTests/", "Tests/VocelloiOSLogicTests/",
                                     *UI_TEST_ONLY_SOURCES))]
    if product:
        return [["scripts/macos_test.sh", "test"]]
    if classes:
        return [["scripts/macos_test.sh", "core-test", "--only", ",".join(classes)]]
    return []


# The app-target builds do not include the XCUITest bundles, so until
# 2026-09-17 a syntax error in the code that drives every acceptance lane
# reached a human only when someone ran a lane by hand. The local check compiles
# them in their lanes' arenas; push CI compiles them with `--gate` after the
# deterministic builds (PA-24). Nothing here or in CI executes them
# (repo_invariants.sh check #2).
UI_BUNDLE_SOURCES = (
    "Tests/UIAutomationSupport/",
    "Tests/VocelloMacUITests/",
    "Tests/VocelloiOSUITests/",
    "Tests/VocelloiOSCandidateUITests/",
)


def ui_bundle_mode(paths: list[str]) -> str | None:
    """Which UI-test bundles the dirty tree can break, or None."""
    touched = [p for p in paths if p.startswith(UI_BUNDLE_SOURCES) or p == "project.yml"]
    if not touched:
        return None
    # The shared helper module and the project file reach both targets.
    if any(p.startswith(("Tests/UIAutomationSupport/",)) or p == "project.yml" for p in touched):
        return "all"
    if any(p.startswith("Tests/VocelloMacUITests/") for p in touched):
        return "macos"
    return "ios"


def check_plan(paths: list[str]) -> dict:
    lanes = lanes_for(paths)
    commands: list[list[str]] = []
    if "project.yml" in paths:
        commands.append(["./scripts/regenerate_project.sh", "--fast"])
    commands.extend(lint_commands(paths))
    commands.append(["./scripts/check_project_inputs.sh", "--local"])
    if lanes["swift"]:
        commands.extend(swift_test_commands(paths))
    if lanes["ios"]:
        commands.append(["./scripts/build_foundation_targets.sh", "ios", "--incremental"])
    if lanes["website"]:
        commands.append(["npm", "--prefix", "website", "run", "check"])
    bundles = ui_bundle_mode(paths)
    if bundles:
        commands.append(["./scripts/build_ui_test_bundles.sh", bundles])
    return {"changedPaths": paths, "lanes": lanes, "commands": commands}


# Mirrors .github/workflows/ci.yml: contracts, routing-independent lanes, then
# the three native/website lanes. Order follows the workflow's job graph.
CI_COMMANDS: list[list[str]] = [
    # The Linux contracts job is the whole gate (--python none there; the Python
    # suite runs in the python job); locally one gate call covers both.
    ["./scripts/regenerate_project.sh", "--fast"],
    ["./scripts/check_project_inputs.sh"],
    ["scripts/macos_test.sh", "test"],
    ["scripts/macos_test.sh", "tsan"],
    ["./scripts/build.sh", "cli", "--version"],
    ["./scripts/build_foundation_targets.sh", "ios", "--incremental"],
    # After both deterministic builds, in their arenas: only the UI-test targets compile.
    ["./scripts/build_ui_test_bundles.sh", "all", "--gate"],
    ["python3", "scripts/supply_chain_contract.py", "--installed", "website"],
    ["npm", "--prefix", "website", "run", "check"],
]

REGEN_COMMANDS: list[list[str]] = [
    ["python3", "scripts/refresh_derived_artifacts.py", "refresh"],
    ["python3", "scripts/refresh_derived_artifacts.py", "validate"],
]


def _which(name: str) -> bool:
    from shutil import which
    return which(name) is not None


def _display(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def run_commands(commands: list[list[str]]) -> None:
    started = time.monotonic()
    for index, command in enumerate(commands, start=1):
        print(f"==> [dev {index}/{len(commands)}] {_display(command)}", flush=True)
        command_started = time.monotonic()
        completed = subprocess.run(command, cwd=ROOT, check=False)
        elapsed = time.monotonic() - command_started
        print(f"==> [dev] completed in {elapsed:.1f}s (exit {completed.returncode})", flush=True)
        if completed.returncode != 0:
            raise WorkflowError(f"command failed: {_display(command)}")
    print(f"==> [dev] done in {time.monotonic() - started:.1f}s", flush=True)


def print_status() -> None:
    branch = _git("symbolic-ref", "--quiet", "--short", "HEAD").decode().strip() or "detached HEAD"
    paths = changed_paths()
    lanes = [name for name, on in lanes_for(paths).items() if on]
    print(f"branch: {branch}")
    print(f"dirty: {len(paths)} path(s)")
    print(f"lanes: {', '.join(lanes) or 'none'} (scripts/dev.sh check --dry-run for the commands)")
    roadmap_path = ROOT / "config/roadmap.json"
    if roadmap_path.is_file():
        roadmap = json.loads(roadmap_path.read_text(encoding="utf-8"))
        primary = roadmap.get("primaryPlan")
        items = [item for item in roadmap.get("items", []) if item.get("plan") == primary]
        open_items = [item["id"] for item in items if item.get("status") in ("in-flight", "planned")]
        print(f"primaryPlan: {primary} — {len(open_items)} open: {', '.join(open_items[:6])}"
              + (" …" if len(open_items) > 6 else ""))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="lint, contracts, selected tests and the native lanes the dirty tree touches")
    check.add_argument("--dry-run", action="store_true", help="print the commands without running them")
    check.add_argument("--paths", nargs="+", help="plan for these paths instead of the dirty tree")
    check.add_argument("--since", metavar="REF",
                       help="also plan for everything committed since REF (for example origin/main): "
                            "verifies an unpushed batch after its commits leave the tree clean")
    sub.add_parser("lint", help="git diff --check, privacy scan, shellcheck on changed shell, swiftlint on changed Swift")
    sub.add_parser("contracts", help="product and repository contracts (check_project_inputs.sh --local)")
    py = sub.add_parser("py", help="Python tests: changed consumers (default), --all, --lane, or explicit modules")
    py.add_argument("--all", action="store_true")
    py.add_argument("--lane", choices=("product", "research", "darwin"), help="product = not research and not darwin_only")
    py.add_argument("tests", nargs="*")
    test = sub.add_parser("test", help="macOS XCTest bundles: changed classes, --only, or --all")
    test.add_argument("--only", help="comma-separated XCTestCase classes")
    test.add_argument("--all", action="store_true")
    sub.add_parser("ios", help="generic device-SDK compile (incremental)")
    sub.add_parser("build", help="dev-signed macOS app build (for running, not verification)")
    sub.add_parser("run", help="build and launch the macOS app")
    sub.add_parser("regen", help="regenerate derived artifacts (and the project if project.yml changed)")
    sub.add_parser("ci", help="exactly what push CI runs, serially")
    sub.add_parser("status", help="branch, dirty paths, lanes, primary plan")
    args = parser.parse_args(argv)

    try:
        command = args.command
        if command == "status":
            print_status()
        elif command == "check":
            if args.since:
                _git("rev-parse", "--verify", "--quiet", f"{args.since}^{{commit}}")
                os.environ[SINCE_ENV] = args.since
            plan = check_plan(args.paths or changed_paths(args.since))
            if not plan["changedPaths"]:
                hint = (f"clean tree and nothing committed since {args.since}: no lane to run" if args.since
                        else "clean tree: no lane to run; `check --since origin/main` plans for committed work")
                print(f"==> [dev] {hint}", file=sys.stderr, flush=True)
            if args.dry_run:
                lanes = ", ".join(k for k, v in plan["lanes"].items() if v) or "none"
                print(f"Changed paths: {len(plan['changedPaths'])}; lanes: {lanes}")
                for entry in plan["commands"]:
                    print(f"  {_display(entry)}")
            else:
                run_commands(plan["commands"])
        elif command == "lint":
            run_commands(lint_commands(changed_paths()))
        elif command == "contracts":
            run_commands([["./scripts/check_project_inputs.sh", "--local"]])
        elif command == "py":
            if args.all:
                run_commands(python_test_commands({"mode": "full", "tests": []}))
            elif args.lane:
                marker = {"product": "not research and not darwin_only", "research": "research", "darwin": "darwin_only"}[args.lane]
                run_commands([[*PYTEST, "-m", marker]])
            elif args.tests:
                run_commands([[*PYTEST, *args.tests]])
            else:
                selection = python_test_selection(changed_paths())
                print(f"==> Python tests: {selection['mode']} ({selection['reason']})", flush=True)
                run_commands(python_test_commands(selection))
        elif command == "test":
            if args.only:
                run_commands([["scripts/macos_test.sh", "core-test", "--only", args.only]])
            else:
                run_commands(swift_test_commands(changed_paths(), everything=args.all) or [["scripts/macos_test.sh", "test"]])
        elif command == "ios":
            run_commands([["./scripts/build_foundation_targets.sh", "ios", "--incremental"]])
        elif command == "build":
            run_commands([["./scripts/build.sh", "build"]])
        elif command == "run":
            run_commands([["./scripts/build.sh", "run"]])
        elif command == "regen":
            commands = list(REGEN_COMMANDS)
            if "project.yml" in changed_paths():
                commands.insert(0, ["./scripts/regenerate_project.sh", "--fast"])
            run_commands(commands)
        elif command == "ci":
            run_commands(CI_COMMANDS)
    except (OSError, WorkflowError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
