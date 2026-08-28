#!/usr/bin/env python3
"""Plan and run Vocello's path-aware development feedback loops.

This helper deliberately separates the edit loop from the checkpoint gate. It
never weakens CI or release evidence: `focused` runs only inferred local checks,
while `checkpoint` refreshes derived state and executes every merge-required
deterministic lane reported by the authoritative evidence-impact contract.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
TEST_CLASS_PATTERN = re.compile(
    r"\b(?:final\s+)?class\s+([A-Za-z_][A-Za-z0-9_]*)\s*:\s*XCTestCase\b"
)
EVIDENCE_COMMANDS: dict[str, list[str]] = {
    "macos-deterministic-tests": ["scripts/macos_test.sh", "test"],
    "ios-device-sdk-compile": [
        "./scripts/build_foundation_targets.sh",
        "ios",
        "--incremental",
    ],
    "website-check": ["npm", "--prefix", "website", "run", "check"],
}


class WorkflowError(RuntimeError):
    pass


def _git(*args: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", os.fspath(ROOT), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise WorkflowError(
            completed.stderr.decode("utf-8", errors="replace").strip()
            or f"git {' '.join(args)} failed"
        )
    return completed.stdout


def changed_paths() -> list[str]:
    paths: set[str] = set()
    for args in (
        ("diff", "--name-only", "-z"),
        ("diff", "--cached", "--name-only", "-z"),
        ("ls-files", "--others", "--exclude-standard", "-z"),
    ):
        paths.update(
            part.decode("utf-8", errors="surrogateescape")
            for part in _git(*args).split(b"\0")
            if part
        )
    return sorted(paths)


def _python_module(path: str) -> str:
    return path[:-3].replace("/", ".")


def adjacent_python_tests(paths: list[str]) -> list[str]:
    tests: set[str] = set()
    for relative in paths:
        path = ROOT / relative
        if relative.endswith(".py") and Path(relative).name.startswith("test_"):
            tests.add(relative)
            continue
        if not (relative.startswith("scripts/") and relative.endswith(".py")):
            continue
        stem = path.stem
        for candidate in (
            ROOT / "scripts" / f"test_{stem}.py",
            ROOT / "scripts" / "tests" / f"test_{stem}.py",
        ):
            if candidate.is_file():
                tests.add(candidate.relative_to(ROOT).as_posix())
    return sorted(tests)


def changed_swift_test_classes(paths: list[str]) -> list[str]:
    classes: set[str] = set()
    roots = ("Tests/VocelloCoreTests/", "Tests/VocelloiOSLogicTests/")
    for relative in paths:
        if not relative.endswith(".swift") or not relative.startswith(roots):
            continue
        path = ROOT / relative
        if path.is_file():
            classes.update(TEST_CLASS_PATTERN.findall(path.read_text(encoding="utf-8")))
    return sorted(classes)


def evidence_impact(paths: list[str]) -> dict:
    command = [sys.executable, "scripts/evidence_impact.py", "classify", *paths]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise WorkflowError(completed.stderr.strip() or "evidence-impact classification failed")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise WorkflowError("evidence-impact classification returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise WorkflowError("evidence-impact classification returned a non-object")
    return payload


def workflow_plan(paths: list[str]) -> dict:
    focused: list[list[str]] = []
    if "project.yml" in paths:
        focused.append(["./scripts/regenerate_project.sh", "--fast"])

    python_tests = adjacent_python_tests(paths)
    if python_tests:
        focused.append([sys.executable, "-m", "unittest", *map(_python_module, python_tests)])

    swift_tests = changed_swift_test_classes(paths)
    if swift_tests:
        focused.append(
            ["scripts/macos_test.sh", "core-test", "--only", ",".join(swift_tests)]
        )
    focused.append(["git", "diff", "--check"])

    impact = evidence_impact(paths)
    required = impact.get("mergeRequiredEvidence")
    if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
        raise WorkflowError("evidence-impact result lacks mergeRequiredEvidence")

    checkpoint: list[list[str]] = [
        [sys.executable, "scripts/refresh_derived_artifacts.py", "refresh"],
        [sys.executable, "scripts/refresh_derived_artifacts.py", "validate"],
        ["env", "QVOICE_GATES=quick", "./scripts/check_project_inputs.sh"],
    ]
    for evidence in required:
        command = EVIDENCE_COMMANDS.get(evidence)
        if command is not None:
            checkpoint.append(command)
    if any(path.startswith("website/") for path in paths):
        website = EVIDENCE_COMMANDS["website-check"]
        if website not in checkpoint:
            checkpoint.append(website)

    return {
        "schemaVersion": 1,
        "changedPaths": paths,
        "classes": impact.get("classes", []),
        "mergeRequiredEvidence": required,
        "focusedCommands": focused,
        "checkpointCommands": checkpoint,
        "explicitAcceptance": (
            "Native XCUITest, model, benchmark, signing, and release lanes remain explicit; "
            "this helper never schedules them."
        ),
    }


def _display(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def print_plan(plan: dict, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(plan, indent=2, sort_keys=True))
        return
    paths = plan["changedPaths"]
    print(f"Changed paths: {len(paths)}")
    print("Edit loop:")
    for command in plan["focusedCommands"]:
        print(f"  {_display(command)}")
    print("Checkpoint (run once per coherent change):")
    for command in plan["checkpointCommands"]:
        print(f"  {_display(command)}")
    print(f"Explicit acceptance: {plan['explicitAcceptance']}")


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
    print(f"==> [dev] workflow completed in {time.monotonic() - started:.1f}s", flush=True)


def record_commit_gate_pass() -> None:
    marker_root = os.environ.get("QVOICE_SCRATCH_GATE_FINGERPRINT")
    if not marker_root:
        raise WorkflowError("QVOICE_SCRATCH_GATE_FINGERPRINT is not exported")
    marker_dir = Path(marker_root).resolve()
    build_root = (ROOT / "build").resolve()
    if build_root not in marker_dir.parents:
        raise WorkflowError("commit-gate marker escapes the governed build root")
    spec = importlib.util.spec_from_file_location(
        "tree_fingerprint", ROOT / "scripts/tree_fingerprint.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fingerprint = module.worktree_fingerprint(ROOT)
    marker_dir.mkdir(parents=True, exist_ok=True)
    next_marker = marker_dir / f"last-pass.next.{os.getpid()}"
    next_marker.write_text(fingerprint + "\n", encoding="utf-8")
    next_marker.replace(marker_dir / "last-pass")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--json", action="store_true")
    subparsers.add_parser("focused")
    subparsers.add_parser("checkpoint")
    args = parser.parse_args(argv)

    try:
        plan = workflow_plan(changed_paths())
        if args.command == "plan":
            print_plan(plan, as_json=args.json)
        elif args.command == "focused":
            run_commands(plan["focusedCommands"])
        else:
            run_commands(plan["checkpointCommands"])
            record_commit_gate_pass()
            print("==> [dev] exact-tree commit-gate PASS marker recorded")
    except (OSError, WorkflowError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
