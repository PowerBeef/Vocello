#!/usr/bin/env python3
"""Path-aware local verification for Vocello: the inner loop and the pre-push check.

Nothing here blocks a commit; CI on push is the gate. `check` runs what the dirty
tree needs (lint, contracts, selected Python tests, the native lanes the changed
paths touch) and `--dry-run` prints that plan. Device, model, UI and release lanes
are never scheduled from here.
"""

from __future__ import annotations

import argparse
import datetime
import functools
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
# Tooling whose change means every Python test is a consumer: the shared
# libraries and fixtures, and the files pytest applies to every module.
FULL_PYTHON_PATTERNS = (
    "scripts/lib/",
    "scripts/tests/fixtures/",
    "scripts/tests/conftest.py",
    "pytest.ini",
    "config/toolchain.json",
    "config/build-output-policy.json",
)
# This selector and CI's router. A change to either always runs both suites,
# named here rather than computed, so a broken matcher cannot hide its own tests;
# their pinned selections cover every other input.
ROUTING_SOURCES = ("scripts/development_workflow.py", "scripts/ci/classify_changes.py")
ROUTING_TESTS = ("scripts/tests/test_classify_changes.py", "scripts/tests/test_development_workflow.py")
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
# `check --paths` exports its paths here, so the contract gate (scripts/lib/contract_gate.py) and the
# Python selection the gate runs plan for them instead of the whole dirty tree.
PATHS_ENV = "QVOICE_CHANGED_PATHS"


def changed_paths(since: str | None = None) -> list[str]:
    """Dirty paths, plus every path changed between `since` (or $QVOICE_CHANGED_SINCE) and HEAD.

    `$QVOICE_CHANGED_PATHS` (one path per line), set by `check --paths`, replaces the dirty tree."""
    explicit = os.environ.get(PATHS_ENV)
    if explicit is not None:
        return sorted({line.strip().removeprefix("./") for line in explicit.splitlines() if line.strip()})
    since = since or os.environ.get(SINCE_ENV) or None
    queries = [("diff", "--name-only", "-z"), ("diff", "--cached", "--name-only", "-z"),
               ("ls-files", "--others", "--exclude-standard", "-z")]
    if since:
        queries.append(("diff", "--name-only", "-z", f"{since}...HEAD"))
    paths: set[str] = set()
    for args in queries:
        paths.update(part.decode("utf-8", errors="surrogateescape") for part in _git(*args).split(b"\0") if part)
    return sorted(paths)


def normalized_path(path: str) -> str:
    """A repository-relative path, from a relative, `./` or absolute spelling inside the checkout."""
    candidate = Path(path)
    if candidate.is_absolute():
        try:
            return candidate.resolve().relative_to(ROOT.resolve()).as_posix()
        except ValueError:
            return path
    return path.removeprefix("./")


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


def _mentions(names: set[str]) -> re.Pattern[str]:
    """A file name as a whole word: `roadmap.json` matches `config/roadmap.json`, not `test-roadmap.json`."""
    return re.compile(r"(?<![\w-])(?:" + "|".join(re.escape(name) for name in sorted(names)) + r")(?![\w-])")


def _python_importers(classify_changes, root: Path) -> dict[str, set[str]]:
    """The reverse of CI's import graph (classify_changes._imported_script_modules) over scripts/."""
    importers: dict[str, set[str]] = {}
    for path in (root / "scripts").rglob("*.py"):
        if "__pycache__" in path.parts or not path.is_file():
            continue
        importer = path.relative_to(root).as_posix()
        for imported in classify_changes._imported_script_modules(path):
            importers.setdefault(imported.relative_to(classify_changes.REPO_ROOT).as_posix(), set()).add(importer)
    return importers


def _import_node(changed: str, root: Path) -> str:
    """The file CI's resolver maps imports of `changed` to.

    It resolves a package import (`from qc import store`, `qc.store`) by the
    package's top-level name, to the same-named script beside it (scripts/qc.py),
    so a module inside a package reaches every importer of that package."""
    parts = changed.split("/")
    if len(parts) > 2 and parts[0] == "scripts" and (root / "scripts" / parts[1] / "__init__.py").is_file():
        return f"scripts/{parts[1]}.py"
    return changed


def _with_importers(files: set[str], importers, root: Path) -> set[str]:
    """`files` and every file importing one of them, transitively (`importers` builds the graph on demand)."""
    affected = set(files)
    pending = [node for path in files if path.endswith(".py") for node in (path, _import_node(path, root))]
    graph = importers() if pending else {}
    while pending:
        for importer in graph.get(pending.pop(), ()):
            if importer not in affected:
                affected.add(importer)
                pending.append(importer)
    return affected


def _test_consumers(affected: set[str], test_texts: dict[str, str]) -> set[str]:
    """The test modules among `affected`, and those naming another of its files.

    Test modules are consumers, never subjects: one naming another (a routing
    example, a fixture path) is not its consumer."""
    tests = affected & test_texts.keys()
    if names := {Path(p).name for p in affected - tests}:
        pattern = _mentions(names)
        tests |= {p for p, text in test_texts.items() if pattern.search(text)}
    return tests


def python_test_selection(paths: list[str], *, root: Path | None = None) -> dict:
    """Test modules that import a changed module, or name a changed or importing file.

    A Python input reaches the files that import it, transitively, through CI's
    own import graph. A test module is selected when it is one of them, or when it
    names (by file name or repository path) the changed file or one of them:
    tests load scripts by path and drive shell scripts and config by name. Name
    matching is one step deep, never iterated: only when nothing imports or names
    an input do the scripts that name it stand in for it, one step further. When
    an input still has no test consumer, or tooling everything depends on changed,
    the whole suite runs.
    """
    root = root or ROOT
    classify_changes = _load("scripts/ci/classify_changes.py")
    agent_inputs = [p for p in paths if (p.startswith(classify_changes.AGENT_CONFIG_PREFIXES)
                                         and p.endswith(classify_changes.AGENT_CONFIG_SUFFIXES))
                    or p in classify_changes.RULE_SOURCES]
    # Top-level benchmark contracts (record schemas, hardware profiles) are read
    # by the registry tests through benchmark_history.py, and those tests do not
    # name them; published records under benchmarks/runs/ are not tooling inputs.
    contracts = [p for p in paths if p.startswith("benchmarks/") and p.count("/") == 1 and p.endswith(".json")]
    inputs = [p for p in paths if p.startswith(("scripts/", "config/"))
              or p in {"project.yml", "Package.resolved"}] + contracts + agent_inputs
    if any(p.startswith(FULL_PYTHON_PATTERNS) for p in paths):
        return {"mode": "full", "tests": [], "reason": "shared tooling changed"}
    if not inputs:
        return {"mode": "none", "tests": [], "reason": "no tooling inputs changed"}
    test_texts = {p.relative_to(root).as_posix(): p.read_text(encoding="utf-8")
                  for p in sorted(root.glob("scripts/tests/**/test_*.py"))}

    @functools.cache
    def importers() -> dict[str, set[str]]:
        return _python_importers(classify_changes, root)

    @functools.cache
    def script_texts() -> dict[str, str]:
        return {p.relative_to(root).as_posix(): p.read_text(encoding="utf-8", errors="replace")
                for p in (root / "scripts").rglob("*") if p.suffix in {".py", ".sh"} and p.is_file()
                and "__pycache__" not in p.parts and not p.relative_to(root).as_posix().startswith("scripts/tests/")}

    selected: set[str] = set()
    if agent_inputs:
        selected.add("scripts/tests/test_agent_hooks.py")
    for changed in inputs:
        if changed in agent_inputs:
            continue  # Additions, modifications and deletions all use behavioral hook tests.
        if not (root / changed).is_file():
            return {"mode": "full", "tests": [], "reason": "deleted or missing tooling input"}
        # The selector loads the router at run time, so their consumers are shared.
        seeds = set(ROUTING_SOURCES) if changed in ROUTING_SOURCES else {changed}
        tests = _test_consumers(_with_importers(seeds, importers, root), test_texts)
        if not tests:
            pattern = _mentions({Path(changed).name})
            if readers := {p for p, text in script_texts().items() if p != changed and pattern.search(text)}:
                tests = _test_consumers(_with_importers(readers, importers, root), test_texts)
        if changed in ROUTING_SOURCES:
            tests.update(ROUTING_TESTS)
        if changed in contracts:
            tests.add("scripts/tests/test_benchmark_history.py")
        if not tests:
            return {"mode": "full", "tests": [], "reason": "no known test consumer for changed input"}
        selected.update(tests)
    return {"mode": "selected", "tests": sorted(selected), "reason": "importing and naming test consumers"}


PYTEST = [sys.executable, "-m", "pytest", "-n", "auto"]


def python_test_commands(selection: dict) -> list[list[str]]:
    if selection["mode"] == "full":
        return [[*PYTEST]]
    if not selection["tests"]:
        return []
    return [[*PYTEST, *selection["tests"]]]


# Test sources whose XCTestCase classes `core-test --only` runs (VocelloCoreTests
# compiles the iOS logic tests too).
CORE_TEST_SOURCES = ("Tests/VocelloCoreTests/", "Tests/VocelloiOSLogicTests/")


def changed_swift_test_classes(paths: list[str]) -> list[str]:
    classes: set[str] = set()
    for relative in paths:
        if relative.endswith(".swift") and relative.startswith(CORE_TEST_SOURCES):
            path = ROOT / relative
            if path.is_file():
                classes.update(TEST_CLASS_PATTERN.findall(path.read_text(encoding="utf-8")))
    return sorted(classes)


# ---------------------------------------------------------------- command builders

def lint_commands(paths: list[str], *, scoped: bool = False) -> list[list[str]]:
    """`scoped` (check --paths) limits `git diff --check` to the given paths too."""
    present = [p for p in paths if (ROOT / p).exists()]  # a committed range can include deletions
    # Scoped, every given path stays in the pathspec (a deleted one matches nothing); an empty pathspec
    # after `--` would check the whole tree.
    commands: list[list[str]] = [["git", "diff", "--check", "--", *paths] if scoped and paths
                                 else ["git", "diff", "--check"]]
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


MACOS_TESTS = ("scripts/macos_test.sh", "test")


def _swift_data_input(path: str, classify_changes) -> bool:
    """A record or fixture Swift tests read, as opposed to a compile, build or lane input.

    Every other non-Swift swift-lane input (lane scripts and their imports,
    scripts/lib, the build and toolchain configs, resources, schemes, the
    project and workflow files) runs the whole lane."""
    if path in classify_changes.SWIFT_PARITY_FIXTURES:
        return True
    if path in classify_changes.BUILD_CONFIGS or path.startswith("config/xcode-schemes/"):
        return False
    return path.startswith(("config/", "Tests/"))


def swift_test_readers(names: list[str]) -> dict[str, list[str] | None]:
    """Per file name, the XCTestCase classes whose test sources name it.

    None when only the whole lane covers it: no class names it, a helper without
    a class does (its callers are unknown), or the owned runtime package's tests
    do (`macos_test.sh test` is their only runner). XCUITest-only sources never run here."""
    sources = [*ROOT.glob("Tests/**/*.swift"), *ROOT.glob("Packages/VocelloQwen3Core/Tests/**/*.swift")]
    texts = {p.relative_to(ROOT).as_posix(): p.read_text(encoding="utf-8") for p in sources if p.is_file()}
    readers: dict[str, list[str] | None] = {}
    for name in names:
        pattern = _mentions({name})
        classes: set[str] = set()
        whole_lane = False
        for relative, text in texts.items():
            if relative.startswith(UI_TEST_ONLY_SOURCES) or not pattern.search(text):
                continue
            found = TEST_CLASS_PATTERN.findall(text) if relative.startswith(CORE_TEST_SOURCES) else []
            whole_lane = whole_lane or not found
            classes.update(found)
        readers[name] = None if whole_lane or not classes else sorted(classes)
    return readers


def swift_test_commands(paths: list[str], *, everything: bool = False) -> list[list[str]]:
    """The macOS test command the swift-lane inputs among `paths` need, or [] when none does.

    Changed test classes run alone; a data input runs the classes whose sources
    name it; any other swift-lane input runs the whole lane (never TSan, which
    push CI runs)."""
    if everything or any(p.startswith(CORE_SWIFT_PREFIXES) for p in paths):
        return [[*MACOS_TESTS]]
    classes = set(changed_swift_test_classes(paths))
    product = [p for p in paths if p.startswith(("Sources/", "Tests/")) and p.endswith(".swift")
               and not p.startswith((*CORE_TEST_SOURCES, *UI_TEST_ONLY_SOURCES))]
    if product:
        return [[*MACOS_TESTS]]
    classify_changes = _load("scripts/ci/classify_changes.py")
    data: list[str] = []
    for path in paths:
        if path.endswith(".swift") or not classify_changes.classify([path])["swift"]:
            continue
        if not _swift_data_input(path, classify_changes):
            return [[*MACOS_TESTS]]
        data.append(Path(path).name)
    for readers in (swift_test_readers(sorted(set(data))) if data else {}).values():
        if readers is None:
            return [[*MACOS_TESTS]]
        classes.update(readers)
    if classes:
        return [["scripts/macos_test.sh", "core-test", "--only", ",".join(sorted(classes))]]
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


LINEAGE_IDENTITY = "scripts/lib/lineage_identity.py"


def lineage_review_paths(paths: list[str]) -> list[str]:
    """Changed files on a benchmark kind's lineage path list while the lineage identity is unchanged.

    Advisory: a change to one of them that moves what a kind measures bumps that
    kind's measurement version in the same change (release.md "Records measure
    what they claim"); nothing else would separate the lineages."""
    if LINEAGE_IDENTITY in paths or not (ROOT / LINEAGE_IDENTITY).is_file():
        return []
    watched = {path for group in _load(LINEAGE_IDENTITY).LINEAGE_PATHS.values() for path in group}
    return sorted(set(paths) & watched)


def project_generation_status(paths: list[str]) -> dict | None:
    generation = _load("scripts/project_generation.py")
    if not generation.relevant_paths(paths, ROOT):
        return None
    return generation.status(ROOT)


def check_plan(paths: list[str], *, scoped: bool = False) -> dict:
    lanes = lanes_for(paths)
    commands: list[list[str]] = []
    generation = project_generation_status(paths)
    if generation and generation["needsRegeneration"]:
        commands.append(["./scripts/regenerate_project.sh", "--fast"])
    commands.extend(lint_commands(paths, scoped=scoped))
    commands.append(["./scripts/check_project_inputs.sh", "--local"])
    if lanes["swift"]:
        # A swift lane that schedules nothing verifies nothing: fall back to the whole lane.
        commands.extend(swift_test_commands(paths) or [[*MACOS_TESTS]])
    if lanes["ios"]:
        commands.append(["./scripts/build_foundation_targets.sh", "ios", "--incremental"])
    if lanes["website"]:
        commands.append(["npm", "--prefix", "website", "run", "check"])
    bundles = ui_bundle_mode(paths)
    if bundles:
        commands.append(["./scripts/build_ui_test_bundles.sh", bundles])
    return {"changedPaths": paths, "lanes": lanes, "commands": commands,
            "lineageReviewPaths": lineage_review_paths(paths), "projectGeneration": generation}


# Mirrors .github/workflows/ci.yml: contracts, routing-independent lanes, then
# the three native/website lanes. Order follows the workflow's job graph.
CI_COMMANDS: list[list[str]] = [
    # The Linux contracts job is the whole gate (--python none there; the Python
    # suite runs in the python job); locally one gate call covers both.
    ["./scripts/regenerate_project.sh", "--fast"],
    ["./scripts/check_project_inputs.sh"],
    # The contracts job's lint gates: new findings against config/lint-baseline/ fail.
    ["python3", "scripts/lint_baseline.py", "shellcheck"],
    ["python3", "scripts/lint_baseline.py", "ruff"],
    ["python3", "scripts/lint_baseline.py", "swiftlint"],
    ["python3", "scripts/lint_baseline.py", "pyright"],
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
        if command[:4] == PYTEST[:4]:
            diagnostics = _load("scripts/workflow_diagnostics.py")
            problems = diagnostics.python_dependency_problems(ROOT)
            if problems:
                raise WorkflowError("selected Python test dependencies: " + "; ".join(problems)
                                    + ". Select an installed environment with VOCELLO_PYTHON; no packages were installed")
        completed = subprocess.run(command, cwd=ROOT, check=False)
        elapsed = time.monotonic() - command_started
        print(f"==> [dev] completed in {elapsed:.1f}s (exit {completed.returncode})", flush=True)
        if completed.returncode != 0:
            raise WorkflowError(f"command failed: {_display(command)}")
    print(f"==> [dev] done in {time.monotonic() - started:.1f}s", flush=True)


def primary_plan_lines(data: dict, archived_ids: set[str], today: datetime.date) -> list[str]:
    """The primary plan at a glance: its live work, the focus lock and what can start next.

    Every session opens on this, so the next unblocked items are listed by due date
    rather than leaving the next step to be re-derived from the whole roadmap. Blocker
    and date semantics come from scripts/roadmap.py, the validator that owns them.
    """
    roadmap = _load("scripts/roadmap.py")
    primary = data.get("primaryPlan")
    items = {item.get("id"): item for item in data.get("items", [])}
    live = [item for item in items.values()
            if item.get("plan") == primary and item.get("status") in roadmap.LIVE_STATUSES]

    def unblocked(item: dict) -> bool:
        for blocker in item.get("blockedBy", []):
            other = items.get(blocker)
            if other is None:
                if blocker not in archived_ids:
                    return False
            elif other.get("status") not in roadmap.TERMINAL:
                return False
        return True

    def due(item: dict) -> datetime.date | None:
        return roadmap.parse_date(str(item["due"])) if "due" in item else None

    ready = sorted((item for item in live if unblocked(item)),
                   key=lambda item: (item.get("status") != "in-flight", due(item) or datetime.date.max, item["id"]))
    lines = [f"primaryPlan: {primary} — {len(live)} open, {len(ready)} unblocked"]
    lock = data.get("focusLock")
    if isinstance(lock, dict) and lock.get("plan") == primary:
        lines.append(f"focusLock: since {lock.get('decided')}; live work only in {primary}, "
                     f"at most {lock.get('maxInFlight')} in flight")
    if ready:
        shown = [f"{item['id']} ({item['status']}" + (f", due {due(item).isoformat()}" if due(item) else "") + ")"
                 for item in ready[:5]]
        lines.append("next: " + ", ".join(shown) + (" …" if len(ready) > 5 else ""))
    overdue = sorted(item["id"] for item in live if due(item) and due(item) < today)
    if overdue:
        lines.append("overdue: " + ", ".join(overdue)
                     + " (cut scope, move the date with a recorded decision, or close it)")
    return lines


def print_status() -> None:
    branch = _git("symbolic-ref", "--quiet", "--short", "HEAD").decode().strip() or "detached HEAD"
    paths = changed_paths()
    lanes = [name for name, on in lanes_for(paths).items() if on]
    print(f"branch: {branch}")
    print(f"dirty: {len(paths)} path(s)")
    print(f"lanes: {', '.join(lanes) or 'none'} (scripts/dev.sh check --dry-run for the commands)")
    if (ROOT / "config/roadmap.json").is_file():
        # SessionStart prints this; a half-edited roadmap must not turn it into a traceback.
        roadmap = _load("scripts/roadmap.py")
        try:
            data = roadmap.load(ROOT)
        except (ValueError, roadmap.RoadmapError) as error:
            print(f"primaryPlan: unreadable config/roadmap.json ({error}); run python3 scripts/roadmap.py validate")
            return
        archived = {item.get("id") for item in roadmap.load_archive(ROOT).get("items", [])}
        for line in primary_plan_lines(data, archived, datetime.date.today()):
            print(line)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="lint, contracts, selected tests and the native lanes the dirty tree touches")
    check.add_argument("--dry-run", action="store_true", help="print the commands without running them")
    check.add_argument("--json", action="store_true", help="emit structured planning data (requires --dry-run)")
    check.add_argument("--paths", nargs="+", help="plan, lint and gate only these paths instead of the dirty tree")
    check.add_argument("--since", metavar="REF",
                       help="also plan for everything committed since REF (for example origin/main): "
                            "verifies an unpushed batch after its commits leave the tree clean")
    sub.add_parser("lint", help="git diff --check, privacy scan, shellcheck on changed shell, swiftlint on changed Swift")
    sub.add_parser("contracts", help="product and repository contracts (check_project_inputs.sh --local)")
    py = sub.add_parser("py", help="Python tests: changed consumers (default), --all, --lane, or explicit modules")
    py.add_argument("--all", action="store_true")
    py.add_argument("--lane", choices=("product", "research"), help="product = not research")
    py.add_argument("tests", nargs="*")
    test = sub.add_parser("test", help="macOS XCTest bundles: changed classes, --only, or --all")
    test.add_argument("--only", help="comma-separated XCTestCase classes")
    test.add_argument("--all", action="store_true")
    test.add_argument("--repeat", type=int, metavar="N",
                      help="with --only: run the selection up to N times, stopping at the first failure")
    sub.add_parser("ios", help="generic device-SDK compile (incremental)")
    sub.add_parser("build", help="dev-signed macOS app build (for running, not verification)")
    sub.add_parser("run", help="build and launch the macOS app")
    sub.add_parser("regen", help="regenerate derived artifacts and stale project inputs or membership")
    sub.add_parser("ci", help="every gate push CI runs, serially (no lane skipped by routing)")
    status_parser = sub.add_parser("status", help="branch, dirty paths, lanes, primary plan")
    status_parser.add_argument("--kpi", action="store_true",
                               help="also print lane pass rates and failed-minute shares from the lane ledger")
    doctor_parser = sub.add_parser("doctor", help="read-only prerequisite and optional capability inventory")
    doctor_parser.add_argument("--json", action="store_true")
    triage_parser = sub.add_parser("triage", help="read retained run evidence without rerunning or rewriting it")
    triage_parser.add_argument("run_directory", type=Path)
    triage_parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "check" and args.json and not args.dry_run:
        parser.error("check --json requires --dry-run")

    try:
        command = args.command
        if command in {"doctor", "triage"}:
            diagnostics = _load("scripts/workflow_diagnostics.py")
            report = diagnostics.doctor(ROOT) if command == "doctor" else diagnostics.triage(args.run_directory)
            if args.json:
                print(json.dumps(report, indent=2))
            else:
                diagnostics.print_report(report)
        elif command == "status":
            print_status()
            if args.kpi:
                ledger = _load("scripts/lane_ledger.py")
                ledger.print_kpi(ledger.kpi(ledger.recorded(ROOT), 30))
        elif command == "check":
            if args.since:
                _git("rev-parse", "--verify", "--quiet", f"{args.since}^{{commit}}")
                os.environ[SINCE_ENV] = args.since
            if args.paths:
                args.paths = sorted({normalized_path(path) for path in args.paths})
                os.environ[PATHS_ENV] = "\n".join(args.paths)
            plan = check_plan(args.paths or changed_paths(args.since), scoped=bool(args.paths))
            if not plan["changedPaths"]:
                hint = (f"clean tree and nothing committed since {args.since}: no lane to run" if args.since
                        else "clean tree: no lane to run; `check --since origin/main` plans for committed work")
                print(f"==> [dev] {hint}", file=sys.stderr, flush=True)
            if review := plan["lineageReviewPaths"]:
                print(
                    f"==> [dev] {len(review)} changed file(s) sit on a benchmark kind's lineage path list "
                    f"({', '.join(review[:3])}{', …' if len(review) > 3 else ''}): if the change moves what "
                    f"a kind measures, bump its LINEAGE_MEASUREMENT_VERSIONS entry in {LINEAGE_IDENTITY}",
                    file=sys.stderr, flush=True,
                )
            if args.dry_run and args.json:
                print(json.dumps(plan, indent=2))
            elif args.dry_run:
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
                marker = {"product": "not research", "research": "research"}[args.lane]
                run_commands([[*PYTEST, "-m", marker]])
            elif args.tests:
                run_commands([[*PYTEST, *args.tests]])
            else:
                selection = python_test_selection(changed_paths())
                print(f"==> Python tests: {selection['mode']} ({selection['reason']})", flush=True)
                run_commands(python_test_commands(selection))
        elif command == "test":
            if args.repeat is not None and not args.only:
                parser.error("test --repeat needs --only: repeat a focused selection, not the suite")
            if args.only:
                repeat = ["--repeat", str(args.repeat)] if args.repeat is not None else []
                run_commands([["scripts/macos_test.sh", "core-test", "--only", args.only, *repeat]])
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
            if _load("scripts/project_generation.py").status(ROOT)["needsRegeneration"]:
                commands.insert(0, ["./scripts/regenerate_project.sh", "--fast"])
            run_commands(commands)
        elif command == "ci":
            run_commands(CI_COMMANDS)
    except (OSError, ValueError, WorkflowError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
