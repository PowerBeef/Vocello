#!/usr/bin/env python3
"""Validate that the backend risk spine points at executable repository evidence.

Each item is `implemented` (named tests pin it, nothing remains), `partial` (named tests pin
part of it and `remaining` says what they leave unpinned) or `uncovered` (no test pins it and
`reason` says why: an open finding, or a fix that landed without one). Every named test must
exist; an uncovered item names none rather than inventing one. Items mapped from an audit cite
it (`audit`) with the finding's severity. `--report` lists every item that is not implemented.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path


# A target's classes, by the source trees project.yml compiles into it: VocelloCoreTests also
# hosts the iOS logic tests, which the compile-only VocelloiOSLogicTests bundle never runs.
TEST_ROOTS = {
    "Qwen3RuntimeTests": (Path("Packages/VocelloQwen3Core/Tests/Qwen3RuntimeTests"),),
    "VocelloCoreTests": (Path("Tests/VocelloCoreTests"), Path("Tests/VocelloiOSLogicTests")),
}
RUNTIME_CHECKS = {
    "telemetry-overhead": (Path("scripts/macos_test.sh"), re.compile(r"^\s*telemetry-overhead\)" , re.MULTILINE)),
}
STATUSES = ("implemented", "partial", "uncovered")
SEVERITIES = {"S1", "S2", "S3"}
# A test class at any depth, or a top-level struct (a Swift Testing suite), after any attributes
# (`@MainActor`, `@Suite("...")`). A nested struct is a helper inside a test class and must not
# end that class's region; `class func` and `class var` declare members, not classes.
ATTRIBUTES = r"(?:@[A-Za-z_][A-Za-z0-9_.]*(?:\([^)\n]*\))?\s+)*"
DECLARATION = re.compile(
    rf"(?m)^(?:\s*{ATTRIBUTES}(?:(?:final|private|fileprivate|internal|public|open)\s+)*class"
    rf"|{ATTRIBUTES}(?:(?:private|fileprivate|internal|public)\s+)*struct)"
    r"\s+(?!(?:func|var|let|subscript)\b)([A-Za-z_][A-Za-z0-9_]*)\b"
)


def _swift_sources(path: Path) -> list[Path]:
    return sorted(path.rglob("*.swift")) if path.is_dir() else []


def _class_contains_test(text: str, class_name: str, test_name: str) -> bool:
    declarations = list(DECLARATION.finditer(text))
    for index, declaration in enumerate(declarations):
        if declaration.group(1) != class_name:
            continue
        end = declarations[index + 1].start() if index + 1 < len(declarations) else len(text)
        class_region = text[declaration.start():end]
        if re.search(rf"\bfunc\s+{re.escape(test_name)}\s*\(", class_region):
            return True
    return False


def _commit_is_reachable(root: Path, commit: str) -> bool:
    if not (root / ".git").exists():
        return True
    result = subprocess.run(
        ["git", "-C", str(root), "cat-file", "-e", f"{commit}^{{commit}}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def _nonempty_strings(value: object) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(v, str) and v.strip() for v in value)


def validate(root: Path, config_path: Path) -> list[str]:
    errors: list[str] = []
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot read {config_path}: {exc}"]

    if data.get("schemaVersion") != 3:
        errors.append("schemaVersion must be 3")
    if data.get("referenceFormat") != "target/class/test":
        errors.append("referenceFormat must be target/class/test")

    evidence = data.get("evidence")
    if not isinstance(evidence, dict):
        errors.append("evidence must be an object")
    else:
        report_dir = evidence.get("reportDirectory")
        if not isinstance(report_dir, str) or not (root / report_dir).is_dir():
            errors.append(f"evidence.reportDirectory does not resolve: {report_dir!r}")
        commit = evidence.get("reportCommit")
        if not isinstance(commit, str) or re.fullmatch(r"[0-9a-f]{40}", commit) is None:
            errors.append("evidence.reportCommit must be a full lowercase Git SHA")
        elif not _commit_is_reachable(root, commit):
            errors.append(f"evidence.reportCommit is not a reachable commit: {commit}")

    items = data.get("items")
    if not isinstance(items, list) or not items:
        errors.append("items must be a non-empty array")
        items = []

    seen_ids: set[str] = set()
    source_cache: dict[str, list[str]] = {}
    for index, item in enumerate(items):
        prefix = f"items[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id:
            errors.append(f"{prefix}.id must be a non-empty string")
        elif item_id in seen_ids:
            errors.append(f"duplicate item id: {item_id}")
        else:
            seen_ids.add(item_id)
            prefix = f"{prefix} ({item_id})"

        source = item.get("source")
        if not isinstance(source, str) or not (root / source).is_file():
            errors.append(f"{prefix}.source does not resolve: {source!r}")

        if "audit" in item or "severity" in item:
            audit = item.get("audit")
            if not isinstance(audit, str) or not (root / audit).is_file():
                errors.append(f"{prefix}.audit does not resolve: {audit!r}")
            if item.get("severity") not in SEVERITIES:
                errors.append(f"{prefix}.severity must be one of {sorted(SEVERITIES)}")

        status = item.get("status")
        remaining = item.get("remaining", [])
        tests = item.get("tests")
        if not isinstance(tests, list):
            errors.append(f"{prefix}.tests must be an array")
            tests = []
        if status not in STATUSES:
            errors.append(f"{prefix}.status must be one of {list(STATUSES)}")
        elif status == "implemented":
            if not tests:
                errors.append(f"{prefix}.tests must name the tests that pin implemented evidence")
            if remaining != []:
                errors.append(f"{prefix}.remaining must be empty for implemented evidence")
        elif status == "partial":
            if not tests:
                errors.append(f"{prefix}.tests must name the tests that pin part of a partial item")
            if not _nonempty_strings(remaining):
                errors.append(f"{prefix}.remaining must say what a partial item's tests leave unpinned")
        else:
            if tests:
                errors.append(f"{prefix}.tests must be empty for an uncovered item; name no test")
            reason = item.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                errors.append(f"{prefix}.reason must say why an uncovered item has no test")
            if remaining != []:
                errors.append(f"{prefix}.remaining is for partial items; an uncovered item gives a reason")

        for reference in tests:
            if not isinstance(reference, str) or reference.count("/") != 2:
                errors.append(f"{prefix} has malformed test reference: {reference!r}")
                continue
            target, class_name, test_name = reference.split("/")
            relative_roots = TEST_ROOTS.get(target)
            if relative_roots is None:
                errors.append(f"{prefix} uses unsupported test target: {target}")
                continue
            sources = source_cache.get(target)
            if sources is None:
                sources = [path.read_text(encoding="utf-8")
                           for relative in relative_roots for path in _swift_sources(root / relative)]
                source_cache[target] = sources
            if not any(_class_contains_test(text, class_name, test_name) for text in sources):
                errors.append(f"{prefix} test reference does not resolve: {reference}")

        runtime_checks = item.get("runtimeChecks", [])
        if not isinstance(runtime_checks, list):
            errors.append(f"{prefix}.runtimeChecks must be an array")
            runtime_checks = []
        for check in runtime_checks:
            contract = RUNTIME_CHECKS.get(check)
            if contract is None:
                errors.append(f"{prefix} has unsupported runtime check: {check!r}")
                continue
            script, pattern = contract
            script_path = root / script
            if not script_path.is_file() or pattern.search(script_path.read_text(encoding="utf-8")) is None:
                errors.append(f"{prefix} runtime check does not resolve: {check}")

    deferred = data.get("deferredMatrix")
    if not isinstance(deferred, dict):
        errors.append("deferredMatrix must be an object")
    else:
        source = deferred.get("source")
        # The deferred matrix may cite a tracked file or a document that now lives only in
        # git history ("git history: <path> at <sha>"); either way the policy text is what binds.
        historical = isinstance(source, str) and source.startswith("git history: ")
        if not isinstance(source, str) or not (historical or (root / source).is_file()):
            errors.append(f"deferredMatrix.source does not resolve: {source!r}")

    return errors


def summary(config_path: Path, *, report: bool = False) -> list[str]:
    """Counts by status, the ids that are not implemented and, with `report`, why."""
    items = [item for item in json.loads(config_path.read_text(encoding="utf-8"))["items"]]
    lines = [", ".join(f"{sum(item['status'] == status for item in items)} {status}" for status in STATUSES)]
    for status in STATUSES[1:]:
        ids = [item["id"] for item in items if item["status"] == status]
        if ids:
            lines.append(f"{status}: {', '.join(ids)}")
    if report:
        for item in items:
            if item["status"] == "implemented":
                continue
            severity = f" {item['severity']}" if "severity" in item else ""
            detail = item.get("reason") or " ".join(item.get("remaining", []))
            lines.append(f"- {item['id']}{severity} {item['status']}: {detail}")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--config", type=Path)
    parser.add_argument("--report", action="store_true",
                        help="also list every partial and uncovered item with what it leaves unpinned")
    args = parser.parse_args()
    root = args.root.resolve()
    config = args.config or root / "config/backend-risk-spine.json"
    errors = validate(root, config)
    if errors:
        for error in errors:
            print(f"error: {error}")
        return 1
    lines = summary(config, report=args.report)
    print(f"backend risk spine: PASS ({lines[0]})")
    for line in lines[1:]:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
