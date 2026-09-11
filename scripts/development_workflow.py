#!/usr/bin/env python3
"""Plan and run Vocello's path-aware development feedback loops.

This helper deliberately separates the edit loop from the checkpoint gate. It
never weakens CI or release evidence: `focused` runs only inferred local checks,
while `checkpoint` selects conservative local evidence. CI and release retain
their complete deterministic contracts; a local marker cannot authorize release.
"""

from __future__ import annotations

import argparse
import fnmatch
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
    "macos-app-build": ["./scripts/build.sh", "build"],
    "macos-deterministic-tests": ["scripts/macos_test.sh", "test"],
    "ios-device-sdk-compile": [
        "./scripts/build_foundation_targets.sh",
        "ios",
        "--incremental",
    ],
    "website-check": ["npm", "--prefix", "website", "run", "check"],
}
DOCUMENTATION_COMMANDS = [
    ["python3", "scripts/documentation_contract.py", "validate"],
    ["python3", "scripts/doc_metadata.py", "validate"],
    ["python3", "scripts/roadmap.py", "validate"],
    ["python3", "scripts/check_surface_coverage.py"],
]


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
        if path.is_file() and relative.endswith(".py") and Path(relative).name.startswith("test_"):
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


def local_policy() -> dict:
    payload = json.loads((ROOT / "config/evidence-impact.json").read_text())
    policy = payload.get("localVerification", {})
    if policy.get("version") != 1:
        raise WorkflowError("unsupported/missing local verification policy")
    for key in ("documentationOnlyPatterns", "fullTestPatterns", "macosOnlyPatterns"):
        values = policy.get(key)
        if not isinstance(values, list) or not values or any(not isinstance(v, str) or not v for v in values):
            raise WorkflowError(f"invalid local verification {key}")
    return policy


def matches_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def ios_source_roots(project: str) -> list[str]:
    """Conservative XcodeGen source membership, including shared frameworks.

    This handles only the checked-in target form. Unknown form fails closed
    to both platforms, rather than trusting a stale macOS-only path list.
    """
    if "targets:\n" not in project:
        return [""]
    blocks = re.split(r"(?m)^  [A-Za-z_][A-Za-z0-9_-]*:\s*$", project.split("targets:\n", 1)[1])
    roots = []
    for block in blocks:
        if re.search(r"(?:platform: iOS|supportedDestinations:.*\biOS\b)", block):
            paths = re.findall(r"(?m)^      - path: ([^\n#]+)", block)
            if not paths:
                return [""]
            roots.extend(p.strip().strip("\"'").rstrip("/") for p in paths)
    return roots or [""]


def is_ios_source(path: str, roots: list[str]) -> bool:
    return any(not root or path == root or path.startswith(root + "/") for root in roots)


def python_test_selection(paths: list[str], *, root: Path | None = None) -> dict:
    """Local feedback only; full discovery remains the CI/release authority.

    Walk reverse literal dependencies (imports, subprocess paths, config names)
    transitively, not just test-file adjacency. Basename matching deliberately
    over-selects. An unrepresented input, deletion, or routing change selects
    full discovery; no empty selection can stand in for an unknown dependency.
    """
    root = root or ROOT
    policy = local_policy()
    inputs = [p for p in paths if p.startswith(("scripts/", "config/", ".github/", ".claude/")) or p in {"project.yml", "Package.resolved"}]
    if any(matches_any(p, policy["fullTestPatterns"]) for p in paths):
        return {"mode": "full", "tests": [], "reason": "verification/build authority changed"}
    modules = sorted([*root.glob("scripts/test_*.py"), *root.glob("scripts/tests/test_*.py")])
    test_paths = {p.relative_to(root).as_posix() for p in modules}
    texts = {
        p.relative_to(root).as_posix(): p.read_text(encoding="utf-8")
        for p in (root / "scripts").rglob("*.py") if p.is_file()
        and "__pycache__" not in p.parts
    }
    selected: set[str] = set()
    for changed in inputs:
        if not (root / changed).is_file():
            return {"mode": "full", "tests": [], "reason": "deleted or missing test input"}
        affected = {changed}
        while True:
            tokens = {Path(p).name for p in affected} | {Path(p).stem for p in affected if p.endswith(".py")}
            pattern = re.compile(r"(?<![\w-])(?:" + "|".join(re.escape(t) for t in sorted(tokens)) + r")(?![\w-])")
            expanded = affected | {p for p, text in texts.items() if pattern.search(text)}
            if expanded == affected:
                break
            affected = expanded
        tests = affected & test_paths
        if not tests:
            return {"mode": "full", "tests": [], "reason": "no known test consumer for changed input"}
        selected.update(tests)
    return {"mode": "selected", "tests": sorted(selected), "reason": "transitive local test consumers" if inputs else "no tooling inputs changed"}


def python_test_commands(selection: dict) -> list[list[str]]:
    if selection["mode"] == "full":
        return [["python3", "-m", "unittest", "discover", "-s", root, "-p", "test_*.py"]
                for root in ("scripts", "scripts/tests")]
    if not selection["tests"]:
        return []
    return [["python3", "-m", "unittest", *map(_python_module, selection["tests"])]]


def validate_optional_assists(root: Path) -> None:
    """Opt-in, configuration-only check; never accesses a device or Keychain."""
    path = root / ".xcodebuildmcp/config.yaml"
    if not path.exists():
        print("XcodeBuildMCP: not configured (optional)")
        return
    text = path.read_text(encoding="utf-8")
    if re.search(r"simulator|ui-automation|ios-sim|^\s*(?:deviceId|device_id|udid):", text, re.I | re.M):
        raise WorkflowError("optional Xcode configuration contains a forbidden destination or device identity")
    for profile in ("macos", "ios-device"):
        if not re.search(rf"^  {profile}:$", text, re.M) or f"build/scratch/derived-data/xcodebuildmcp/{profile}" not in text:
            raise WorkflowError(f"optional Xcode profile {profile} must use governed scratch output")
    print("XcodeBuildMCP: configured physical-device/macOS paths pass (tool availability not asserted)")


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


def workflow_plan(paths: list[str], *, full: bool = False) -> dict:
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

    policy = local_policy()
    # Prose is cheap only when the authoritative classifier agrees. A new
    # README inside a resource tree, a NOTICE, or an unknown path stays broad.
    docs_only = bool(paths) and all(
        matches_any(p, policy["documentationOnlyPatterns"]) for p in paths
    ) and set(impact.get("classes", [])) <= {"documentation-and-governance", "repository-validation-surface"}
    docs_only = docs_only and not any(matches_any(p, policy["fullTestPatterns"]) for p in paths)
    checkpoint: list[list[str]] = [
        [sys.executable, "scripts/refresh_derived_artifacts.py", "refresh"],
        [sys.executable, "scripts/refresh_derived_artifacts.py", "validate"],
    ]
    if full:
        checkpoint.append(["env", "-u", "QVOICE_GATES", "./scripts/check_project_inputs.sh"])
    elif docs_only:
        checkpoint.extend(DOCUMENTATION_COMMANDS)
    else:
        checkpoint.append(["./scripts/check_project_inputs.sh", "--local"])
    # Local native applicability is intentionally separate from promotion and
    # historical release evidence. Tooling does not rebuild unchanged Swift.
    prose = {row["path"] for row in impact.get("paths", [])
             if row.get("classes") == ["documentation-and-governance"]}
    native = [p for p in paths if p.startswith(("Sources/", "Packages/", "Tests/")) and p not in prose]
    broad = full or "repository-other" in impact.get("classes", []) or any(matches_any(p, policy["fullTestPatterns"]) for p in paths)
    native_lanes = []
    if native or broad:
        ios_roots = ios_source_roots((ROOT / "project.yml").read_text())
        native_lanes.append("macos-deterministic-tests")
        if broad or any(not matches_any(p, policy["macosOnlyPatterns"]) or is_ios_source(p, ios_roots) for p in native):
            native_lanes.append("ios-device-sdk-compile")
        if broad or any(not p.startswith(("Sources/iOS/", "Sources/iOSSupport/", "Tests/VocelloiOS")) for p in native):
            native_lanes.append("macos-app-build")
    for evidence in native_lanes:
        checkpoint.append(EVIDENCE_COMMANDS[evidence])
    if full or (not docs_only and any(path.startswith("website/") for path in paths)):
        website = EVIDENCE_COMMANDS["website-check"]
        if website not in checkpoint:
            checkpoint.append(website)

    return {
        "schemaVersion": 1,
        "changedPaths": paths,
        "classes": impact.get("classes", []),
        "mergeRequiredEvidence": required,
        "localVerification": "full" if full else "documentation" if docs_only else "affected",
        "localNativeEvidence": native_lanes,
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
    print(f"Local verification: {plan['localVerification']} (CI/release coverage remains separate)")
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


def receipt_state() -> str:
    """fresh | stale | missing: does the commit-gate receipt match this tree and toolchain?"""
    marker_root = os.environ.get("QVOICE_SCRATCH_GATE_FINGERPRINT") or str(ROOT / "build/scratch/gate-fingerprint")
    marker = Path(marker_root) / "last-pass"
    if not marker.is_file():
        return "missing"
    try:
        from tree_fingerprint import checkpoint_fingerprint
        current = checkpoint_fingerprint(ROOT)
    except Exception:  # noqa: BLE001 - status is advisory
        return "unverifiable"
    return "fresh" if marker.read_text(encoding="utf-8").strip() == current else "stale"


def print_status() -> None:
    """One screen for a session start: branch, dirty paths, verification class, receipt, primary plan."""
    branch = _git("symbolic-ref", "--quiet", "--short", "HEAD").decode().strip() or "detached HEAD"
    paths = changed_paths()
    try:
        plan = workflow_plan(paths)
        verification = plan["localVerification"]
        lanes = ", ".join(plan["localNativeEvidence"]) or "none"
    except (OSError, WorkflowError) as error:
        verification, lanes = f"unavailable ({error})", "?"
    print(f"branch: {branch}")
    print(f"dirty: {len(paths)} path(s)")
    print(f"verification: {verification}; native lanes: {lanes}")
    print(f"receipt: {receipt_state()} (scripts/dev.sh checkpoint writes it)")
    roadmap_path = ROOT / "config/roadmap.json"
    if roadmap_path.is_file():
        roadmap = json.loads(roadmap_path.read_text(encoding="utf-8"))
        primary = roadmap.get("primaryPlan")
        items = [item for item in roadmap.get("items", []) if item.get("plan") == primary]
        done = sum(1 for item in items if item.get("status") == "done")
        open_items = [item["id"] for item in items if item.get("status") in ("in-flight", "planned")]
        print(f"primaryPlan: {primary} — {done}/{len(items)} done; open: {', '.join(open_items[:6])}"
              + (" …" if len(open_items) > 6 else ""))
    else:
        print("primaryPlan: (config/roadmap.json missing)")


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
    fingerprint = module.checkpoint_fingerprint(ROOT)
    marker_dir.mkdir(parents=True, exist_ok=True)
    next_marker = marker_dir / f"last-pass.next.{os.getpid()}"
    next_marker.write_text(fingerprint + "\n", encoding="utf-8")
    next_marker.replace(marker_dir / "last-pass")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--json", action="store_true")
    plan_parser.add_argument("--paths", nargs="+", help="preview representative paths; never executes or records PASS")
    plan_parser.add_argument("--full", action="store_true")
    subparsers.add_parser("focused")
    subparsers.add_parser("checkpoint").add_argument("--full", action="store_true")
    subparsers.add_parser("python-tests")
    subparsers.add_parser("assists")
    subparsers.add_parser("status")
    args = parser.parse_args(argv)

    try:
        if args.command == "assists":
            validate_optional_assists(ROOT)
            return 0
        if args.command == "status":
            print_status()
            return 0
        if args.command == "python-tests":
            if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
                raise WorkflowError("selective Python tests are local-only")
            selection = python_test_selection(changed_paths())
            print(f"==> local Python tests: {selection['mode']} ({selection['reason']})", flush=True)
            run_commands(python_test_commands(selection))
            return 0
        paths = getattr(args, "paths", None) or changed_paths()
        full = getattr(args, "full", False)
        if args.command == "checkpoint" and (os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS")) and not full:
            raise WorkflowError("CI must use full deterministic verification")
        plan = workflow_plan(paths, full=full)
        if args.command == "plan":
            print_plan(plan, as_json=args.json)
        elif args.command == "focused":
            run_commands(plan["focusedCommands"])
        else:
            # Derived refresh can add/change inputs. Reclassify after refresh,
            # then refuse concurrent edits instead of blessing untested bytes.
            run_commands(plan["checkpointCommands"][:2])
            plan = workflow_plan(changed_paths(), full=full)
            from tree_fingerprint import checkpoint_fingerprint
            before = checkpoint_fingerprint(ROOT)
            run_commands(plan["checkpointCommands"][2:])
            if before != checkpoint_fingerprint(ROOT):
                raise WorkflowError("tree changed during verification; no PASS recorded")
            record_commit_gate_pass()
            print("==> [dev] exact-tree commit-gate PASS marker recorded")
    except (OSError, WorkflowError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
