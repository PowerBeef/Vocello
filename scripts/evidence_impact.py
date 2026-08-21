#!/usr/bin/env python3
"""Validate and classify changed paths against Vocello's evidence contract."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = Path("config/evidence-impact.json")
SCHEMA_VERSION = 1
KINDS = {"deterministic", "model-dependent", "model-ui", "device-ui"}
LIST_FIELDS = (
    "mergeRequiredEvidence",
    "releaseRequiredEvidence",
    "qualityEvidence",
    "promotionRequiredEvidence",
)
CAPABILITY_FIELD = "promotionCapabilities"


class EvidenceImpactError(RuntimeError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def load_contract(root: Path = REPO_ROOT) -> dict[str, Any]:
    path = root / CONTRACT_PATH
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EvidenceImpactError(f"cannot read {path}: {error}") from error


def validate_contract(contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if contract.get("schemaVersion") != SCHEMA_VERSION:
        errors.append(f"schemaVersion must be {SCHEMA_VERSION}")
    if contract.get("ordinaryPublicationPolicy") != "deterministic-only":
        errors.append("ordinaryPublicationPolicy must remain deterministic-only")
    critical_patterns = contract.get("criticalPathPatterns")
    if (
        not isinstance(critical_patterns, list)
        or not critical_patterns
        or len(critical_patterns) != len(set(critical_patterns))
        or any(not isinstance(value, str) or not value for value in critical_patterns)
    ):
        errors.append("criticalPathPatterns must be a non-empty unique string array")

    evidence_items = contract.get("evidence")
    if not isinstance(evidence_items, list) or not evidence_items:
        return errors + ["evidence must be a non-empty array"]
    evidence: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(evidence_items):
        if not isinstance(item, dict):
            errors.append(f"evidence[{index}] must be an object")
            continue
        identity = item.get("id")
        if not isinstance(identity, str) or not identity:
            errors.append(f"evidence[{index}] has no id")
            continue
        if identity in evidence:
            errors.append(f"duplicate evidence id: {identity}")
        evidence[identity] = item
        if item.get("kind") not in KINDS:
            errors.append(f"evidence {identity} has unsupported kind {item.get('kind')!r}")
        if not isinstance(item.get("command"), str) or not item["command"]:
            errors.append(f"evidence {identity} has no command")

    classes = contract.get("pathClasses")
    if not isinstance(classes, list) or not classes:
        errors.append("pathClasses must be a non-empty array")
        classes = []
    class_ids: set[str] = set()
    for item in classes:
        identity = item.get("id") if isinstance(item, dict) else None
        if not isinstance(identity, str) or not identity:
            errors.append("path class has no id")
            continue
        if identity in class_ids:
            errors.append(f"duplicate path class id: {identity}")
        class_ids.add(identity)
        includes = item.get("include")
        if not isinstance(includes, list) or not includes or any(not isinstance(value, str) or not value for value in includes):
            errors.append(f"path class {identity} has invalid include patterns")
        errors.extend(_validate_references(item, identity, evidence))
        errors.extend(_validate_capabilities(item, identity))

    fallback = contract.get("fallbackClass")
    if not isinstance(fallback, dict) or not fallback.get("id"):
        errors.append("fallbackClass must be an object with an id")
    else:
        errors.extend(_validate_references(fallback, str(fallback["id"]), evidence))
        errors.extend(_validate_capabilities(fallback, str(fallback["id"])))

    # Ordinary merge/release evidence is deliberately deterministic. Device,
    # UI, and model-dependent checks may block an explicit public promotion,
    # but never ordinary source publication, packaging, signing, notarization,
    # candidate creation, or internal TestFlight upload.
    for item in [*classes, fallback] if isinstance(fallback, dict) else classes:
        if not isinstance(item, dict):
            continue
        for field in ("mergeRequiredEvidence", "releaseRequiredEvidence"):
            for reference in item.get(field) or []:
                if reference in evidence and evidence[reference].get("kind") != "deterministic":
                    errors.append(f"{item.get('id')}.{field} makes non-deterministic evidence {reference} blocking")
        for reference in item.get("qualityEvidence") or []:
            if reference in evidence and evidence[reference].get("kind") == "deterministic":
                errors.append(f"{item.get('id')}.qualityEvidence redundantly lists deterministic evidence {reference}")
        for reference in item.get("promotionRequiredEvidence") or []:
            if reference in evidence and evidence[reference].get("kind") == "deterministic":
                errors.append(
                    f"{item.get('id')}.promotionRequiredEvidence redundantly lists deterministic evidence {reference}"
                )
    return errors


def _validate_references(item: dict[str, Any], identity: str, evidence: dict[str, dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for field in LIST_FIELDS:
        values = item.get(field)
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            errors.append(f"{identity}.{field} must be an array of evidence ids")
            continue
        unknown = sorted(set(values) - evidence.keys())
        if unknown:
            errors.append(f"{identity}.{field} references unknown evidence: {', '.join(unknown)}")
        if len(values) != len(set(values)):
            errors.append(f"{identity}.{field} contains duplicates")
    return errors


def _validate_capabilities(item: dict[str, Any], identity: str) -> list[str]:
    values = item.get(CAPABILITY_FIELD, [])
    if (
        not isinstance(values, list)
        or any(not isinstance(value, str) or not value for value in values)
        or len(values) != len(set(values))
    ):
        return [f"{identity}.{CAPABILITY_FIELD} must be a unique string array"]
    return []


def contract_digest(contract: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(contract)).hexdigest()


def _matches(path: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(path, pattern) or (
        pattern.endswith("/**") and (path == pattern[:-3] or path.startswith(pattern[:-2]))
    )


def critical_fallback_paths(contract: dict[str, Any], paths: list[str]) -> list[str]:
    classes = contract.get("pathClasses") or []
    critical_patterns = contract.get("criticalPathPatterns") or []
    fallback_paths: list[str] = []
    for raw_path in sorted(set(paths)):
        path = raw_path.replace("\\", "/")
        while path.startswith("./"):
            path = path[2:]
        path = path.lstrip("/")
        if not any(_matches(path, pattern) for pattern in critical_patterns):
            continue
        if not any(any(_matches(path, pattern) for pattern in item["include"]) for item in classes):
            fallback_paths.append(path)
    return fallback_paths


def tracked_paths(root: Path = REPO_ROOT) -> list[str]:
    completed = subprocess.run(
        ["git", "ls-files"], cwd=root, check=False, capture_output=True, text=True
    )
    if completed.returncode != 0:
        raise EvidenceImpactError(completed.stderr.strip() or "git ls-files failed")
    return sorted(line for line in completed.stdout.splitlines() if line)


def validate_repository_coverage(contract: dict[str, Any], root: Path = REPO_ROOT) -> list[str]:
    return critical_fallback_paths(contract, tracked_paths(root))


def classify(contract: dict[str, Any], paths: list[str]) -> dict[str, Any]:
    errors = validate_contract(contract)
    if errors:
        raise EvidenceImpactError("; ".join(errors))
    unexplained = critical_fallback_paths(contract, paths)
    if unexplained:
        raise EvidenceImpactError(
            "critical paths use repository-other fallback: " + ", ".join(unexplained)
        )
    classes: list[dict[str, Any]] = contract["pathClasses"]
    fallback: dict[str, Any] = contract["fallbackClass"]
    matched_classes: dict[str, dict[str, Any]] = {}
    path_results: list[dict[str, Any]] = []
    for raw_path in sorted(set(paths)):
        path = raw_path.replace("\\", "/")
        while path.startswith("./"):
            path = path[2:]
        path = path.lstrip("/")
        matches = [item for item in classes if any(_matches(path, pattern) for pattern in item["include"])]
        if not matches:
            matches = [fallback]
        for item in matches:
            matched_classes[item["id"]] = item
        path_results.append({"path": path, "classes": sorted(item["id"] for item in matches)})

    def union(field: str) -> list[str]:
        return sorted({
            reference
            for item in matched_classes.values()
            for reference in item.get(field, [])
        })

    return {
        "schemaVersion": SCHEMA_VERSION,
        "contractDigest": contract_digest(contract),
        "paths": path_results,
        "classes": sorted(matched_classes),
        "mergeRequiredEvidence": union("mergeRequiredEvidence"),
        "releaseRequiredEvidence": union("releaseRequiredEvidence"),
        "qualityEvidence": union("qualityEvidence"),
        "promotionRequiredEvidence": union("promotionRequiredEvidence"),
        "promotionCapabilities": union(CAPABILITY_FIELD),
        "qualityEvidenceBlocksOrdinaryPublication": False,
        "promotionEvidenceBlocksPublicPromotion": True,
    }


def git_changed_paths(root: Path, base: str | None) -> list[str]:
    commands = (
        [["git", "diff", "--name-only", f"{base}...HEAD"]]
        if base
        else [["git", "diff", "--name-only"], ["git", "diff", "--cached", "--name-only"]]
    )
    paths: set[str] = set()
    for command in commands:
        completed = subprocess.run(command, cwd=root, check=False, capture_output=True, text=True)
        if completed.returncode != 0:
            raise EvidenceImpactError(completed.stderr.strip() or f"failed: {' '.join(command)}")
        paths.update(line for line in completed.stdout.splitlines() if line)
    return sorted(paths)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate")
    subparsers.add_parser("digest")
    classify_parser = subparsers.add_parser("classify")
    classify_parser.add_argument("paths", nargs="*")
    classify_parser.add_argument("--base")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        contract = load_contract(root)
        errors = validate_contract(contract)
        if errors:
            raise EvidenceImpactError("\n".join(errors))
        if args.command == "validate":
            fallback_paths = validate_repository_coverage(contract, root)
            if fallback_paths:
                raise EvidenceImpactError(
                    "tracked critical paths use repository-other fallback: "
                    + ", ".join(fallback_paths)
                )
            print(
                f"PASS: evidence impact contract {contract_digest(contract)} "
                "(0 critical fallback paths)"
            )
        elif args.command == "digest":
            print(contract_digest(contract))
        else:
            paths = args.paths or git_changed_paths(root, args.base)
            print(json.dumps(classify(contract, paths), sort_keys=True, indent=2))
    except EvidenceImpactError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
