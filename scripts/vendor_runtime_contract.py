#!/usr/bin/env python3
"""Validate Vocello's owned Qwen3 Core lineage, boundaries, and capabilities."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path


RUNTIME_RELATIVE = Path("Packages/VocelloQwen3Core")
# Compatibility for existing repository tooling that imports this module.
VENDOR_RELATIVE = RUNTIME_RELATIVE
MANIFEST_NAME = "VENDOR_MANIFEST.json"
BASELINE_NAME = "UPSTREAM_BASELINE.json"
CURRENT_INVENTORY_NAME = "CURRENT_INVENTORY.json"
RELOCATION_INVENTORY_NAME = "RELOCATION_INVENTORY.json"
FACADE_API_BASELINE_NAME = "FACADE_API_BASELINE.json"
PATCHES_NAME = "PATCHES.json"
LINEAGE_NAME = "LINEAGE.json"
COMPATIBILITY_NAME = "COMPATIBILITY.json"
CAPABILITIES_NAME = "RUNTIME_CAPABILITIES.json"
OWNERSHIP_NAME = "OWNERSHIP.json"
BASELINE_SCOPE = (".gitignore", "Package.swift", "Sources/**", "Tests/**", "Examples/**")
IMPLEMENTATION_SCOPE = ("Package.swift", "Sources/**")
RUNTIME_IMPACT_SCOPE = ("Package.swift", "Package.resolved", "Sources/**")
LEGACY_RUNTIME_RELATIVE = Path("third_party_patches/mlx-audio-swift")
ALLOWED_UPSTREAM_STATUSES = {"identical", "modified", "added"}
EXPECTED_PATCH_STATES = {
    "active",
    "diagnostic",
    "dormant",
    "rejected",
    "shared",
    "superseded",
    "removed",
}
EXPECTED_UPSTREAM_DISPOSITIONS = {
    "local-only",
    "upstreamable",
    "upstreamed",
    "equivalent",
    "blocked",
    "obsolete",
    "shared-upstream",
}
EXPECTED_EVIDENCE_CLASSES = {"static", "benchmark", "diagnostic", "historical", "unmeasured"}
EXPECTED_BENCHMARK_EVIDENCE_STATUSES = {"verified", "diagnostic", "unverified"}
EXPECTED_CAPABILITY_STATES = {"production", "diagnostic", "internal", "retired"}
PRODUCTION_FACADE_CAPABILITY_ID = "owned-facade"
PRODUCTION_FACADE_SOURCES = frozenset({
    "Sources/VocelloQwen3Core/CompatibilityExports.swift",
    "Sources/VocelloQwen3Core/Contracts.swift",
    "Sources/VocelloQwen3Core/LoadedModel.swift",
    "Sources/VocelloQwen3Core/Runtime.swift",
})
SHIPPING_ACTOR_CAPABILITY_ID = "actor-classified-generation"
SHIPPING_ACTOR_SOURCES = frozenset({
    "Sources/VocelloQwen3Core/ClassifiedGenerationSession.swift",
    "Sources/VocelloQwen3Core/Engine.swift",
    "Sources/VocelloQwen3Core/GenerationSession.swift",
    "Sources/VocelloQwen3Core/ProductOutputAdapter.swift",
})
FACADE_SOURCE_RELATIVE = Path("Sources/VocelloQwen3Core")
FORBIDDEN_FACADE_API_TYPES = re.compile(
    r"\b(?:MLX|MLX[A-Z][A-Za-z0-9_]*|Qwen3TTS[A-Za-z0-9_]*|GenerateParameters|HubCache|HuggingFace)\b"
)
LEGACY_COMPATIBILITY_SPI = "VocelloQwen3LegacyCompatibility"
LEGACY_COMPATIBILITY_SPI_ATTRIBUTE = f"@_spi({LEGACY_COMPATIBILITY_SPI})"
LEGACY_COMPATIBILITY_SPI_ATTRIBUTE_PATTERN = re.compile(
    rf"@_spi\(\s*{re.escape(LEGACY_COMPATIBILITY_SPI)}\s*\)"
)
LEGACY_COMPATIBILITY_DECLARATION = re.compile(
    r"\bpublic\s+(?:"
    r"(?:enum|protocol|struct|actor|(?:final\s+)?class)\s+(?:"
    r"VocelloQwen3GenerationEvent|"
    r"VocelloQwen3GenerationSession|"
    r"VocelloQwen3ModelGenerationSession|"
    r"VocelloQwen3GenerationSignal|"
    r"VocelloQwen3GenerationCompletion|"
    r"VocelloQwen3ClonePrompt|"
    r"VocelloQwen3CompatibilityDiagnostics|"
    r"VocelloQwen3LoadedModel"
    r")\b|"
    r"extension\s+VocelloQwen3LoadedModel\b|"
    # clearRuntimeCaches is a sanctioned public lifecycle API since Phase 14b;
    # only public prepared-model loading remains forbidden outside the actor.
    r"(?:nonisolated\s+)?static\s+func\s+loadPreparedModel\b"
    r")"
)
VOCELLO_QWEN3_CORE_IMPORT = re.compile(r"\bimport\s+VocelloQwen3Core\b")
# Phase 14b (2026-07-23) retired the legacy compatibility SPI: loading,
# metadata, priming, and clone-artifact adoption are actor-owned, and the
# previously SPI-gated symbols are internal to the package. The empty sets keep
# the fail-closed checks alive so no consumer or surface can silently return.
LEGACY_COMPATIBILITY_SPI_CONSUMERS: frozenset[str] = frozenset()
LEGACY_COMPATIBILITY_SPI_SURFACES: frozenset[str] = frozenset()
RELOCATION_POST_PATHS = {
    CURRENT_INVENTORY_NAME,
    RELOCATION_INVENTORY_NAME,
    FACADE_API_BASELINE_NAME,
    "Sources/MLXAudioTTS/RuntimeDebugGate.swift",
}
LIVE_PATCH_STATES = {"active", "diagnostic", "dormant", "shared"}
PATCH_STATE_DISPOSITIONS = {
    "active": {"local-only", "upstreamable", "blocked"},
    "diagnostic": {"local-only", "upstreamable", "blocked"},
    "dormant": {"local-only", "upstreamable", "blocked"},
    "rejected": {"blocked", "obsolete"},
    "shared": {"upstreamed", "equivalent", "shared-upstream"},
    "superseded": {"upstreamed", "equivalent", "obsolete", "shared-upstream"},
    "removed": {"upstreamed", "equivalent", "obsolete", "shared-upstream"},
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def resolved_pin_descriptors(payload: bytes | str | dict) -> dict[str, dict] | None:
    try:
        if isinstance(payload, bytes):
            document = json.loads(payload.decode("utf-8"))
        elif isinstance(payload, str):
            document = json.loads(payload)
        else:
            document = payload
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    pins = document.get("pins") if isinstance(document, dict) else None
    if not isinstance(pins, list):
        return None
    descriptors: dict[str, dict] = {}
    for pin in pins:
        identity = pin.get("identity") if isinstance(pin, dict) else None
        kind = pin.get("kind") if isinstance(pin, dict) else None
        location = pin.get("location") if isinstance(pin, dict) else None
        state = pin.get("state") if isinstance(pin, dict) else None
        if (
            not isinstance(identity, str)
            or not identity
            or not isinstance(kind, str)
            or not kind
            or not isinstance(location, str)
            or not location
            or not isinstance(state, dict)
        ):
            return None
        if identity in descriptors:
            return None
        descriptors[identity] = {
            "kind": kind,
            "location": location,
            "state": state,
        }
    return descriptors


def benchmark_neutral_dependency_errors(
    package_contract: dict,
    pin_descriptors: dict[str, dict] | None,
) -> list[str]:
    neutral = package_contract.get("benchmarkNeutralResolvedDependencies", {})
    if not isinstance(neutral, dict):
        return ["COMPATIBILITY benchmark-neutral dependency contract must be an object"]
    if pin_descriptors is None:
        return ["owned runtime Package.resolved is invalid"]
    errors: list[str] = []
    direct = set(package_contract.get("directDependencies", {}))
    for identity, reason in neutral.items():
        if not isinstance(identity, str) or not identity:
            errors.append("benchmark-neutral dependency identity must be non-empty")
            continue
        if identity not in pin_descriptors:
            errors.append(f"benchmark-neutral dependency is absent from the lock: {identity}")
        if identity in direct:
            errors.append(f"direct runtime dependency cannot be benchmark-neutral: {identity}")
        if not isinstance(reason, str) or not reason.strip():
            errors.append(f"benchmark-neutral dependency requires a reason: {identity}")
    return errors


def benchmark_dependency_projection(
    package_contract: dict,
    pin_descriptors: dict[str, dict] | None,
) -> dict[str, dict] | None:
    if pin_descriptors is None:
        return None
    neutral = package_contract.get("benchmarkNeutralResolvedDependencies", {})
    if not isinstance(neutral, dict):
        return None
    projection: dict[str, dict] = {}
    for identity in sorted(pin_descriptors):
        descriptor = pin_descriptors[identity]
        projection[identity] = (
            {
                "kind": descriptor["kind"],
                "location": descriptor["location"],
            }
            if identity in neutral
            else descriptor
        )
    return projection


def scoped_files(root: Path, patterns: tuple[str, ...] = BASELINE_SCOPE) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and matches(path.relative_to(root).as_posix(), list(patterns))
        and path.name not in {"Package.resolved", ".DS_Store"}
        and ".swiftpm" not in path.parts
    )


def all_runtime_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.name != ".DS_Store"
        and ".swiftpm" not in path.parts
    )


def baseline_hashes(baseline: dict) -> dict[str, str]:
    return {
        str(entry["path"]): str(entry["sha256"])
        for entry in baseline.get("entries", [])
        if isinstance(entry, dict) and entry.get("path") and entry.get("sha256")
    }


def make_current_inventory(runtime: Path, baseline: dict, component_id: str) -> dict:
    upstream = baseline_hashes(baseline)
    entries: list[dict[str, str]] = []
    counts = {"identical": 0, "modified": 0, "added": 0}
    current_paths: set[str] = set()
    for path in scoped_files(runtime):
        relative = path.relative_to(runtime).as_posix()
        current_paths.add(relative)
        digest = sha256(path)
        upstream_digest = upstream.get(relative)
        status = (
            "added"
            if upstream_digest is None
            else "identical"
            if digest == upstream_digest
            else "modified"
        )
        counts[status] += 1
        entries.append({"path": relative, "sha256": digest, "upstreamStatus": status})
    removed = sorted(set(upstream) - current_paths)
    return {
        "schemaVersion": 1,
        "componentID": component_id,
        "upstreamBaselineSHA256": sha256(runtime / BASELINE_NAME),
        "scope": list(BASELINE_SCOPE),
        "summary": {
            "retained": len(entries),
            "identical": counts["identical"],
            "modified": counts["modified"],
            "added": counts["added"],
            "removed": len(removed),
        },
        "removedBaselinePaths": removed,
        "entries": entries,
    }


def without_swift_comments(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", " ", source, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", source)


SWIFT_DECLARATION_ATTRIBUTE = re.compile(
    r"@[A-Za-z_][A-Za-z0-9_]*(?:\([^\n]*\))?"
)


def swift_spi_declaration_start(source: str, declaration_start: int) -> int:
    """Include the contiguous attribute block only when it carries the legacy SPI."""
    line_start = source.rfind("\n", 0, declaration_start) + 1
    inline_prefix = source[line_start:declaration_start]
    inline_attributes = re.search(
        rf"(?P<attributes>(?:{SWIFT_DECLARATION_ATTRIBUTE.pattern}[ \t]+)+)$",
        inline_prefix,
    )
    if inline_attributes is not None:
        start = line_start + inline_attributes.start("attributes")
        attributes = source[start:declaration_start]
        return (
            start
            if LEGACY_COMPATIBILITY_SPI_ATTRIBUTE_PATTERN.search(attributes)
            else declaration_start
        )

    start = declaration_start
    cursor = line_start
    while cursor > 0:
        previous_end = cursor - 1
        previous_start = source.rfind("\n", 0, previous_end) + 1
        previous_line = source[previous_start:previous_end]
        stripped = previous_line.strip()
        if SWIFT_DECLARATION_ATTRIBUTE.fullmatch(stripped) is None:
            break
        start = previous_start + len(previous_line) - len(previous_line.lstrip())
        cursor = previous_start
    attributes = source[start:declaration_start]
    return (
        start
        if LEGACY_COMPATIBILITY_SPI_ATTRIBUTE_PATTERN.search(attributes)
        else declaration_start
    )


def canonical_public_declarations(path: Path) -> list[str]:
    source = without_swift_comments(path.read_text(encoding="utf-8"))
    declarations: list[str] = []
    for match in re.finditer(r"\bpublic\b", source):
        public_start = match.start()
        start = swift_spi_declaration_start(source, public_start)
        parentheses = 0
        brackets = 0
        end = len(source)
        for index in range(public_start, len(source)):
            character = source[index]
            if character == "(":
                parentheses += 1
            elif character == ")":
                parentheses = max(0, parentheses - 1)
            elif character == "[":
                brackets += 1
            elif character == "]":
                brackets = max(0, brackets - 1)
            elif character == "{" and parentheses == 0 and brackets == 0:
                end = index
                break
            elif character == "\n" and parentheses == 0 and brackets == 0:
                end = index
                break
        declaration = " ".join(source[start:end].split())
        if declaration:
            declarations.append(declaration)
    return declarations


def legacy_compatibility_declaration_errors(declarations: list[str]) -> list[str]:
    errors: list[str] = []
    for declaration in declarations:
        if LEGACY_COMPATIBILITY_SPI_ATTRIBUTE_PATTERN.search(declaration):
            errors.append(
                f"the retired {LEGACY_COMPATIBILITY_SPI} SPI may not reappear: {declaration}"
            )
        elif LEGACY_COMPATIBILITY_DECLARATION.search(declaration):
            errors.append(
                "VocelloQwen3Core exposes a retired public loaded-model, cache-mutation, "
                f"or combined-session declaration: {declaration}"
            )
    return errors


def legacy_compatibility_spi_consumers(repo_root: Path) -> set[str]:
    consumers: set[str] = set()
    source_root = repo_root / "Sources"
    for path in sorted(source_root.rglob("*.swift")):
        source = without_swift_comments(path.read_text(encoding="utf-8"))
        if (
            LEGACY_COMPATIBILITY_SPI_ATTRIBUTE_PATTERN.search(source)
            and VOCELLO_QWEN3_CORE_IMPORT.search(source)
        ):
            consumers.add(path.relative_to(repo_root).as_posix())
    return consumers


def legacy_compatibility_consumer_errors(observed: set[str]) -> list[str]:
    errors: list[str] = []
    for path in sorted(observed - LEGACY_COMPATIBILITY_SPI_CONSUMERS):
        errors.append(
            f"unapproved {LEGACY_COMPATIBILITY_SPI} product consumer: {path}"
        )
    for path in sorted(LEGACY_COMPATIBILITY_SPI_CONSUMERS - observed):
        errors.append(
            f"stale {LEGACY_COMPATIBILITY_SPI} product consumer registration: {path}"
        )
    return errors


def legacy_compatibility_metadata_errors(compatibility: dict) -> list[str]:
    source_compatibility = compatibility.get("sourceCompatibility", {})
    errors: list[str] = []
    if "temporaryLegacySPI" in source_compatibility:
        errors.append("COMPATIBILITY must not reintroduce the temporary legacy SPI record")
    metadata = source_compatibility.get("retiredLegacySPI", {})
    if metadata.get("name") != LEGACY_COMPATIBILITY_SPI:
        errors.append("COMPATIBILITY retired SPI name differs from the enforced boundary")
    if metadata.get("status") != "retired-2026-07-23-phase14b-actor-owned-loading":
        errors.append("COMPATIBILITY retired SPI status token drifted")
    if set(metadata.get("surfaces", [])) != LEGACY_COMPATIBILITY_SPI_SURFACES:
        errors.append("COMPATIBILITY retired SPI surface inventory must stay empty")
    if set(metadata.get("consumerAllowlist", [])) != LEGACY_COMPATIBILITY_SPI_CONSUMERS:
        errors.append("COMPATIBILITY retired SPI consumer allowlist must stay empty")
    return errors


def facade_capability_boundary_errors(capabilities: dict) -> list[str]:
    by_id = {
        str(item.get("id")): item
        for item in capabilities.get("capabilities", [])
        if isinstance(item, dict)
    }
    errors: list[str] = []
    production = by_id.get(PRODUCTION_FACADE_CAPABILITY_ID, {})
    if production.get("state") != "production" or set(
        production.get("sourcePatterns", [])
    ) != PRODUCTION_FACADE_SOURCES:
        errors.append(
            "RUNTIME_CAPABILITIES production facade must cover only shipping facade sources"
        )
    actor_generation = by_id.get(SHIPPING_ACTOR_CAPABILITY_ID, {})
    if actor_generation.get("state") != "production" or set(
        actor_generation.get("sourcePatterns", [])
    ) != SHIPPING_ACTOR_SOURCES:
        errors.append(
            "RUNTIME_CAPABILITIES shipping actor/session capability is missing or stale"
        )
    return errors


def make_facade_api_baseline(runtime: Path) -> dict:
    source_root = runtime / FACADE_SOURCE_RELATIVE
    sources = []
    declarations = []
    for path in sorted(source_root.glob("*.swift")):
        relative = path.relative_to(runtime).as_posix()
        sources.append({"path": relative, "sha256": sha256(path)})
        declarations.extend(
            f"{relative}::{declaration}"
            for declaration in canonical_public_declarations(path)
        )
    return {
        "schemaVersion": 1,
        "componentID": "vocello-qwen3-core",
        "module": "VocelloQwen3Core",
        "sourceRoot": FACADE_SOURCE_RELATIVE.as_posix(),
        "sourceFiles": sources,
        "publicDeclarations": declarations,
    }


def matches(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def safe_contract_reference(reference: str) -> bool:
    candidate = Path(reference)
    return bool(reference) and not candidate.is_absolute() and ".." not in candidate.parts


def expanded(root: Path, patterns: list[str]) -> list[Path]:
    found: set[Path] = set()
    for pattern in patterns:
        if not safe_contract_reference(pattern):
            continue
        if any(character in pattern for character in "*?["):
            # A trailing "**" matches files only on Python 3.13+; "**/*" resolves
            # to the same file set on every supported runtime (issue #69).
            if pattern.endswith("**"):
                pattern += "/*"
            found.update(path for path in root.glob(pattern) if path.is_file())
        else:
            path = root / pattern
            if path.is_file():
                found.add(path)
    return sorted(found)


def patch_state_disposition_valid(state: str, disposition: str) -> bool:
    return disposition in PATCH_STATE_DISPOSITIONS.get(state, set())


def git_checkout_is_clean(root: Path) -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and not result.stdout.strip()


def benchmark_records(repo_root: Path) -> dict[str, dict]:
    records: dict[str, dict] = {}
    for path in (repo_root / "benchmarks/runs").glob("*/*.json"):
        if path.is_file():
            records[path.stem] = load_json(path)
    return records


def git_blob(repo_root: Path, commit: str, relative: Path) -> bytes | None:
    result = subprocess.run(
        ["git", "show", f"{commit}:{relative.as_posix()}"],
        cwd=repo_root,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    return result.stdout if result.returncode == 0 else None


def git_tree_relative_paths(repo_root: Path, commit: str, root: Path) -> set[str]:
    result = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", commit, root.as_posix()],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return set()
    prefix = f"{root.as_posix()}/"
    return {
        line.removeprefix(prefix)
        for line in result.stdout.splitlines()
        if line.startswith(prefix)
    }


def canonical_record_digest(record: dict) -> str:
    unsigned = dict(record)
    unsigned.pop("digest", None)
    encoded = json.dumps(
        unsigned,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def benchmark_record_is_eligible(record: dict) -> bool:
    run = record.get("run", {})
    evidence = record.get("evidence", {})
    # Schema v3 (2026-08-01 UI records) keeps every field this check reads
    # with identical shape and meaning; v1 records predate the evidence block.
    return (
        record.get("schemaVersion") in {2, 3}
        and record.get("digest") == canonical_record_digest(record)
        and run.get("status") in {"passed", "passedWithWarnings"}
        and run.get("classification") == "canonical"
        and run.get("matrixScope") == "canonical"
        and evidence.get("validatorPassed") is True
        and evidence.get("crashDeltaPassed") is True
        and evidence.get("memoryQualified") is True
    )


def make_relocation_inventory(
    repo_root: Path,
    runtime: Path,
    base_commit: str,
    excluded_paths: set[str],
) -> dict:
    source_paths = git_tree_relative_paths(repo_root, base_commit, LEGACY_RUNTIME_RELATIVE)
    current = {
        path.relative_to(runtime).as_posix(): path
        for path in all_runtime_files(runtime)
        if path.relative_to(runtime).as_posix() not in excluded_paths
    }
    entries = []
    counts = {"identical": 0, "modified": 0, "added": 0}
    for relative, path in sorted(current.items()):
        source = git_blob(repo_root, base_commit, LEGACY_RUNTIME_RELATIVE / relative)
        destination_digest = sha256(path)
        source_digest = hashlib.sha256(source).hexdigest() if source is not None else None
        status = (
            "added"
            if source_digest is None
            else "identical"
            if source_digest == destination_digest
            else "modified"
        )
        counts[status] += 1
        entries.append(
            {
                "path": relative,
                "status": status,
                "sourceSHA256": source_digest,
                "destinationSHA256AtContractCapture": destination_digest,
            }
        )
    removed = sorted(source_paths - set(current))
    return {
        "schemaVersion": 1,
        "componentID": "vocello-qwen3-core",
        "sourceRoot": LEGACY_RUNTIME_RELATIVE.as_posix(),
        "destinationRoot": RUNTIME_RELATIVE.as_posix(),
        "comparisonBaseCommit": base_commit,
        "captureSemantics": (
            "Historical relocation classification captured after semantic follow-up edits; "
            "post-relocation files are explicitly excluded."
        ),
        "postRelocationExcludedPaths": sorted(excluded_paths),
        "summary": {
            "identical": counts["identical"],
            "modified": counts["modified"],
            "added": counts["added"],
            "removed": len(removed),
        },
        "removedSourcePaths": removed,
        "entries": entries,
    }


def benchmark_record_matches_sources(
    repo_root: Path,
    runtime: Path,
    source_patterns: list[str],
    record: dict,
) -> bool:
    """Return whether a clean record commit contains today's exact capability sources.

    Records from before the monorepo relocation are compared at the former package-relative path.
    This keeps a path move from pretending to be performance evidence while allowing byte-identical
    sources to remain comparable when no runtime-impacting implementation changed.
    """
    if not benchmark_record_is_eligible(record):
        return False
    source = record.get("source", {})
    commit = source.get("commit")
    if (
        not isinstance(commit, str)
        or not commit
        or source.get("dirty") is not False
        or source.get("fingerprintsMatch") is not True
    ):
        return False
    impact_patterns = list(dict.fromkeys([*source_patterns, "Package.swift"]))
    paths = [
        path
        for path in expanded(runtime, impact_patterns)
        if matches(path.relative_to(runtime).as_posix(), list(RUNTIME_IMPACT_SCOPE))
    ]
    if not paths:
        return False
    current_relatives = {path.relative_to(runtime).as_posix() for path in paths}
    historical_relatives = {
        relative
        for root in (RUNTIME_RELATIVE, LEGACY_RUNTIME_RELATIVE)
        for relative in git_tree_relative_paths(repo_root, commit, root)
        if matches(relative, impact_patterns)
        and matches(relative, list(RUNTIME_IMPACT_SCOPE))
    }
    if current_relatives != historical_relatives:
        return False
    for current in paths:
        relative = current.relative_to(runtime)
        candidates = (
            RUNTIME_RELATIVE / relative,
            LEGACY_RUNTIME_RELATIVE / relative,
        )
        historical = next(
            (
                blob
                for candidate in candidates
                if (blob := git_blob(repo_root, commit, candidate)) is not None
            ),
            None,
        )
        if historical is None or historical != current.read_bytes():
            return False
    package_contract = load_json(runtime / COMPATIBILITY_NAME).get("package", {})
    current_pin_descriptors = resolved_pin_descriptors(
        (runtime / "Package.resolved").read_bytes()
    )
    historical_lock = next(
        (
            blob
            for candidate in (
                RUNTIME_RELATIVE / "Package.resolved",
                LEGACY_RUNTIME_RELATIVE / "Package.resolved",
            )
            if (blob := git_blob(repo_root, commit, candidate)) is not None
        ),
        None,
    )
    if historical_lock is None:
        return False
    current_projection = benchmark_dependency_projection(
        package_contract,
        current_pin_descriptors,
    )
    historical_projection = benchmark_dependency_projection(
        package_contract,
        resolved_pin_descriptors(historical_lock),
    )
    return (
        current_projection is not None
        and historical_projection is not None
        and current_projection == historical_projection
    )


def capability_benchmark_is_fresh(
    repo_root: Path,
    runtime: Path,
    capability: dict,
    records: dict[str, dict],
    patches_by_id: dict[str, dict] | None = None,
) -> bool:
    impact_patterns = list(capability.get("sourcePatterns", []))
    if patches_by_id is not None:
        for patch_id in capability.get("upstreamDeltaIDs", []):
            patch = patches_by_id.get(str(patch_id))
            if patch is not None:
                impact_patterns.extend(patch.get("files", []))
    return any(
        benchmark_record_matches_sources(
            repo_root,
            runtime,
            list(dict.fromkeys(impact_patterns)),
            records[record_id],
        )
        for record_id in capability.get("benchmarkRecordIDs", [])
        if record_id in records
    )


def capability_benchmark_evidence_errors(
    repo_root: Path,
    runtime: Path,
    capability: dict,
    records: dict[str, dict],
    allowed_statuses: set[str],
    patches_by_id: dict[str, dict] | None = None,
) -> list[str]:
    capability_id = capability.get("id", "<missing>")
    status = capability.get("benchmarkEvidenceStatus")
    record_ids = list(capability.get("benchmarkRecordIDs", []))
    errors: list[str] = []
    if status not in allowed_statuses:
        errors.append(f"{capability_id}: benchmark evidence status is missing or invalid")
    if status != "unverified" and not record_ids:
        errors.append(f"{capability_id}: {status} benchmark evidence requires a record")
    fresh = capability_benchmark_is_fresh(
        repo_root,
        runtime,
        capability,
        records,
        patches_by_id,
    )
    if status == "verified" and not fresh:
        errors.append(
            f"{capability_id}: current runtime-impacting sources differ from every "
            "benchmark record; evidence must be diagnostic or unverified"
        )
    if status in {"diagnostic", "unverified"} and not str(
        capability.get("benchmarkEvidenceReason", "")
    ).strip():
        errors.append(f"{capability_id}: non-verified benchmark evidence requires a reason")
    return errors


def swift_imports(root: Path) -> set[str]:
    imports: set[str] = set()
    pattern = re.compile(
        r"^\s*(?:@preconcurrency\s+)?import\s+([A-Za-z_][A-Za-z0-9_]*)\b",
        re.MULTILINE,
    )
    for path in root.rglob("*.swift"):
        imports.update(pattern.findall(path.read_text(encoding="utf-8")))
    return imports


def package_target_blocks(package: str) -> dict[str, str]:
    """Return balanced PackageDescription target declarations keyed by target name."""
    blocks: dict[str, str] = {}
    marker = re.compile(r"\.(?:target|testTarget)\s*\(")
    for match in marker.finditer(package):
        depth = 0
        end = match.end()
        for index in range(match.end() - 1, len(package)):
            character = package[index]
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth == 0:
                    end = index + 1
                    break
        block = package[match.start():end]
        name = re.search(r'\bname:\s*"([A-Za-z_][A-Za-z0-9_]*)"', block)
        if name:
            blocks[name.group(1)] = block
    return blocks


def validate(repo_root: Path) -> list[str]:
    runtime = repo_root / RUNTIME_RELATIVE
    errors: list[str] = []
    required = [
        runtime / MANIFEST_NAME,
        runtime / LINEAGE_NAME,
        runtime / COMPATIBILITY_NAME,
        runtime / CAPABILITIES_NAME,
        runtime / OWNERSHIP_NAME,
        runtime / BASELINE_NAME,
        runtime / CURRENT_INVENTORY_NAME,
        runtime / RELOCATION_INVENTORY_NAME,
        runtime / FACADE_API_BASELINE_NAME,
        runtime / PATCHES_NAME,
        runtime / "ORIGINS.md",
        runtime / "NOTICES.md",
        runtime / "LICENSE",
    ]
    for path in required:
        if not path.is_file():
            errors.append(f"missing owned-runtime contract: {path.relative_to(repo_root)}")
    legacy_path = repo_root / LEGACY_RUNTIME_RELATIVE
    if legacy_path.exists():
        errors.append("legacy owned-runtime path still exists: third_party_patches/mlx-audio-swift")
    if errors:
        return errors

    manifest = load_json(runtime / MANIFEST_NAME)
    lineage = load_json(runtime / LINEAGE_NAME)
    compatibility = load_json(runtime / COMPATIBILITY_NAME)
    capabilities = load_json(runtime / CAPABILITIES_NAME)
    ownership = load_json(runtime / OWNERSHIP_NAME)
    baseline = load_json(runtime / BASELINE_NAME)
    current_inventory = load_json(runtime / CURRENT_INVENTORY_NAME)
    relocation_inventory = load_json(runtime / RELOCATION_INVENTORY_NAME)
    facade_api_baseline = load_json(runtime / FACADE_API_BASELINE_NAME)
    delta_ledger = load_json(runtime / PATCHES_NAME)

    expected_versions = {
        MANIFEST_NAME: (manifest, 3),
        LINEAGE_NAME: (lineage, 2),
        COMPATIBILITY_NAME: (compatibility, 1),
        CAPABILITIES_NAME: (capabilities, 2),
        OWNERSHIP_NAME: (ownership, 1),
        BASELINE_NAME: (baseline, 2),
        CURRENT_INVENTORY_NAME: (current_inventory, 1),
        RELOCATION_INVENTORY_NAME: (relocation_inventory, 1),
        FACADE_API_BASELINE_NAME: (facade_api_baseline, 1),
        PATCHES_NAME: (delta_ledger, 2),
    }
    for name, (document, version) in expected_versions.items():
        if document.get("schemaVersion") != version:
            errors.append(f"{name} must use schemaVersion {version}")

    component_id = manifest.get("componentID")
    if component_id != "vocello-qwen3-core":
        errors.append("VENDOR_MANIFEST componentID must be vocello-qwen3-core")
    for name, document in (
        (LINEAGE_NAME, lineage),
        (COMPATIBILITY_NAME, compatibility),
        (CAPABILITIES_NAME, capabilities),
        (OWNERSHIP_NAME, ownership),
        (BASELINE_NAME, baseline),
        (CURRENT_INVENTORY_NAME, current_inventory),
        (RELOCATION_INVENTORY_NAME, relocation_inventory),
        (PATCHES_NAME, delta_ledger),
        (FACADE_API_BASELINE_NAME, facade_api_baseline),
    ):
        if document.get("componentID") != component_id:
            errors.append(f"{name} componentID differs from VENDOR_MANIFEST")
    if manifest.get("path") != RUNTIME_RELATIVE.as_posix():
        errors.append("VENDOR_MANIFEST path differs from the owned runtime path")
    if manifest.get("maintenanceModel") != "owned-monorepo-runtime":
        errors.append("VENDOR_MANIFEST must classify the runtime as owned-monorepo-runtime")

    project = (repo_root / "project.yml").read_text(encoding="utf-8")
    if "path: Packages/VocelloQwen3Core" not in project:
        errors.append("project.yml does not route MLXAudio to Packages/VocelloQwen3Core")
    project_file = (repo_root / "QwenVoice.xcodeproj/project.pbxproj").read_text(encoding="utf-8")
    if "Packages/VocelloQwen3Core" not in project_file:
        errors.append("generated Xcode project does not route the owned runtime package")
    dependabot = (repo_root / ".github/dependabot.yml").read_text(encoding="utf-8")
    if 'directory: "/Packages/VocelloQwen3Core"' not in dependabot:
        errors.append("Dependabot does not cover the owned runtime package root")
    codeowners = (repo_root / ".github/CODEOWNERS").read_text(encoding="utf-8")
    if "/Packages/VocelloQwen3Core/" not in codeowners:
        errors.append("CODEOWNERS does not cover the owned runtime package root")

    expected_contracts = {
        "lineage": LINEAGE_NAME,
        "compatibility": COMPATIBILITY_NAME,
        "capabilities": CAPABILITIES_NAME,
        "ownership": OWNERSHIP_NAME,
        "currentInventory": CURRENT_INVENTORY_NAME,
        "relocationInventory": RELOCATION_INVENTORY_NAME,
        "facadeAPIBaseline": FACADE_API_BASELINE_NAME,
        "semanticDeltas": PATCHES_NAME,
        "origins": "ORIGINS.md",
        "notices": "NOTICES.md",
    }
    if manifest.get("contracts") != expected_contracts:
        errors.append("VENDOR_MANIFEST contract index is missing or stale")
    if manifest.get("historicalEvidence") != {"upstreamBaseline": BASELINE_NAME}:
        errors.append("VENDOR_MANIFEST historical evidence must contain only the immutable baseline")
    expected_facade_api = make_facade_api_baseline(runtime)
    if facade_api_baseline != expected_facade_api:
        errors.append(
            "FACADE_API_BASELINE is stale; run "
            "python3 scripts/vendor_runtime_contract.py rebuild-facade-api-baseline"
        )
    declarations = facade_api_baseline.get("publicDeclarations", [])
    if not declarations:
        errors.append("FACADE_API_BASELINE must contain public declarations")
    leaked_types = [
        declaration
        for declaration in declarations
        if FORBIDDEN_FACADE_API_TYPES.search(str(declaration))
    ]
    if leaked_types:
        errors.append(
            "VocelloQwen3Core public API exposes raw MLX/MLXAudio implementation types: "
            f"{leaked_types}"
        )
    errors.extend(legacy_compatibility_declaration_errors(declarations))
    errors.extend(legacy_compatibility_metadata_errors(compatibility))
    errors.extend(
        legacy_compatibility_consumer_errors(
            legacy_compatibility_spi_consumers(repo_root)
        )
    )

    origin = lineage.get("origin", {})
    if lineage.get("lineagePolicy") != "immutable-import-separate-upstream-review":
        errors.append("LINEAGE must keep immutable import identity separate from upstream reviews")
    if baseline.get("upstreamCommit") != origin.get("commit"):
        errors.append("UPSTREAM_BASELINE commit differs from immutable LINEAGE origin")
    baseline_inventory = lineage.get("baselineInventory", {})
    if baseline_inventory.get("path") != BASELINE_NAME:
        errors.append("LINEAGE baseline inventory path is stale")
    if baseline_inventory.get("sha256") != sha256(runtime / BASELINE_NAME):
        errors.append("LINEAGE baseline inventory digest differs from UPSTREAM_BASELINE")
    relocation = lineage.get("monorepoRelocation", {})
    relocation_base = "2f1391d846b2ed259db6959ca47f6129cddb58d2"
    if (
        relocation.get("from") != LEGACY_RUNTIME_RELATIVE.as_posix()
        or relocation.get("to") != RUNTIME_RELATIVE.as_posix()
        or relocation.get("comparisonBaseCommit") != relocation_base
        or relocation.get("classification") != "semantic-move-with-modifications-and-additions"
    ):
        errors.append("LINEAGE monorepo relocation identity is missing or stale")
    relocation_reference = relocation.get("inventory", {})
    if relocation_reference.get("path") != RELOCATION_INVENTORY_NAME:
        errors.append("LINEAGE relocation inventory path is stale")
    if relocation_reference.get("sha256") != sha256(runtime / RELOCATION_INVENTORY_NAME):
        errors.append("LINEAGE relocation inventory digest is stale")
    if (
        relocation_inventory.get("componentID") != component_id
        or relocation_inventory.get("sourceRoot") != LEGACY_RUNTIME_RELATIVE.as_posix()
        or relocation_inventory.get("destinationRoot") != RUNTIME_RELATIVE.as_posix()
        or relocation_inventory.get("comparisonBaseCommit") != relocation_base
        or not str(relocation_inventory.get("captureSemantics", "")).strip()
    ):
        errors.append("RELOCATION_INVENTORY identity or capture semantics are stale")
    relocation_entries = relocation_inventory.get("entries", [])
    relocation_paths = [entry.get("path") for entry in relocation_entries]
    if len(relocation_paths) != len(set(relocation_paths)) or any(
        not isinstance(path, str) or not safe_contract_reference(path) for path in relocation_paths
    ):
        errors.append("RELOCATION_INVENTORY requires unique safe relative paths")
    relocation_counts = {"identical": 0, "modified": 0, "added": 0}
    for entry in relocation_entries:
        status = entry.get("status")
        source_digest = entry.get("sourceSHA256")
        destination_digest = entry.get("destinationSHA256AtContractCapture")
        if not isinstance(destination_digest, str) or re.fullmatch(r"[0-9a-f]{64}", destination_digest) is None:
            errors.append(f"RELOCATION_INVENTORY {entry.get('path')}: invalid destination digest")
            continue
        expected_status = (
            "added"
            if source_digest is None
            else "identical"
            if source_digest == destination_digest
            else "modified"
        )
        if status != expected_status or status not in relocation_counts:
            errors.append(f"RELOCATION_INVENTORY {entry.get('path')}: invalid classification")
            continue
        relocation_counts[status] += 1
        if source_digest is not None:
            source_blob = git_blob(
                repo_root,
                relocation_base,
                LEGACY_RUNTIME_RELATIVE / str(entry.get("path")),
            )
            if source_blob is None or hashlib.sha256(source_blob).hexdigest() != source_digest:
                errors.append(f"RELOCATION_INVENTORY {entry.get('path')}: source digest is not reproducible")
    source_paths = git_tree_relative_paths(repo_root, relocation_base, LEGACY_RUNTIME_RELATIVE)
    removed_paths = sorted(source_paths - set(relocation_paths))
    derived_relocation_summary = {
        **relocation_counts,
        "removed": len(removed_paths),
    }
    if relocation_inventory.get("removedSourcePaths") != removed_paths:
        errors.append("RELOCATION_INVENTORY removed-source inventory is stale")
    if set(relocation_inventory.get("postRelocationExcludedPaths", [])) != RELOCATION_POST_PATHS:
        errors.append("RELOCATION_INVENTORY post-relocation exclusions are stale")
    if relocation_inventory.get("summary") != derived_relocation_summary:
        errors.append("RELOCATION_INVENTORY summary is not derived from its entries")
    if relocation.get("fileComparison") != derived_relocation_summary:
        errors.append("LINEAGE relocation comparison differs from its immutable inventory")
    if derived_relocation_summary != {"identical": 65, "modified": 11, "added": 12, "removed": 0}:
        errors.append(
            "relocation inventory must prove 65 identical, 11 modified, 12 added, and zero "
            "removed files; the move was not pure byte parity"
        )
    if origin.get("license") != "MIT" or origin.get("licenseFile") != "LICENSE":
        errors.append("LINEAGE must retain the imported MIT license identity")
    if origin.get("licenseSHA256") != sha256(runtime / "LICENSE"):
        errors.append("LINEAGE license digest differs from the retained imported license")

    backend = (repo_root / "Sources/QwenVoiceBackendCore/QwenVoiceBackendCore.swift").read_text(encoding="utf-8")
    for field in ("repository", "tag", "commit"):
        value = origin.get(field)
        if not isinstance(value, str) or value not in backend:
            errors.append(f"BackendCore provenance differs from LINEAGE origin {field}")

    package_contract = compatibility.get("package", {})
    package = (runtime / "Package.swift").read_text(encoding="utf-8")
    tools = re.search(r"swift-tools-version:\s*([0-9.]+)", package)
    if not tools or tools.group(1) != package_contract.get("swiftToolsVersion"):
        errors.append("Package.swift tools version differs from COMPATIBILITY")
    if f'name: "{package_contract.get("name")}"' not in package:
        errors.append("Package.swift package name differs from COMPATIBILITY")
    for dependency, version in package_contract.get("directDependencies", {}).items():
        if dependency not in package or f'"{version}"' not in package:
            errors.append(f"Package.swift dependency pin missing or stale: {dependency} {version}")
    errors.extend(
        benchmark_neutral_dependency_errors(
            package_contract,
            resolved_pin_descriptors((runtime / "Package.resolved").read_bytes()),
        )
    )
    for product in package_contract.get("products", []):
        if f'.library(name: "{product}"' not in package:
            errors.append(f"Package.swift product missing: {product}")
    for target in package_contract.get("targets", []):
        declaration = ".testTarget(" if target.endswith("Tests") else ".target("
        if declaration not in package or f'name: "{target}"' not in package:
            errors.append(f"Package.swift target missing: {target}")
    if manifest.get("products") != package_contract.get("products"):
        errors.append("VENDOR_MANIFEST products differ from COMPATIBILITY")
    if manifest.get("targets") != package_contract.get("targets"):
        errors.append("VENDOR_MANIFEST targets differ from COMPATIBILITY")

    target_contracts = ownership.get("targets", {})
    if set(target_contracts) != set(package_contract.get("products", [])):
        errors.append("OWNERSHIP target inventory must cover every production product target")
    forbidden = set(ownership.get("forbiddenRepositoryImports", [])) | set(
        ownership.get("forbiddenFrameworkImports", [])
    )
    forbidden_manifest_dependencies = sorted(module for module in forbidden if module in package)
    if forbidden_manifest_dependencies:
        errors.append(
            f"Package.swift declares forbidden repository or UI dependencies "
            f"{forbidden_manifest_dependencies}"
        )
    package_blocks = package_target_blocks(package)
    runtime_target_names = set(target_contracts)
    for target, contract in target_contracts.items():
        source_reference = str(contract.get("sourceRoot", ""))
        if not safe_contract_reference(source_reference):
            errors.append(f"OWNERSHIP {target}: sourceRoot must be a safe relative path")
            continue
        source_root = runtime / source_reference
        if not source_root.is_dir():
            errors.append(f"OWNERSHIP {target}: sourceRoot does not resolve")
            continue
        actual_imports = swift_imports(source_root)
        allowed_imports = set(contract.get("allowedImports", []))
        unexpected = sorted(actual_imports - allowed_imports)
        if unexpected:
            errors.append(f"OWNERSHIP {target}: undeclared imports {unexpected}")
        prohibited = sorted(actual_imports & forbidden)
        if prohibited:
            errors.append(f"OWNERSHIP {target}: forbidden imports {prohibited}")
        block = package_blocks.get(target)
        if block is None:
            errors.append(f"OWNERSHIP {target}: Package.swift target declaration does not resolve")
            continue
        actual_internal_dependencies = {
            candidate
            for candidate in runtime_target_names
            if candidate != target and f'"{candidate}"' in block
        }
        allowed_internal_dependencies = set(contract.get("allowedRuntimeTargetDependencies", []))
        if actual_internal_dependencies != allowed_internal_dependencies:
            errors.append(
                f"OWNERSHIP {target}: runtime target dependencies "
                f"{sorted(actual_internal_dependencies)} differ from declared "
                f"{sorted(allowed_internal_dependencies)}"
            )

    patches = delta_ledger.get("patches", [])
    patch_id_list = [item.get("id") for item in patches]
    patch_ids = {item.get("id") for item in patches if item.get("id")}
    patches_by_id = {str(item.get("id")): item for item in patches if item.get("id")}
    if len(patch_id_list) != len(patch_ids) or any(not value for value in patch_id_list):
        errors.append("PATCHES entries require unique non-empty ids")
    if delta_ledger.get("status") != "active-semantic-delta-ledger":
        errors.append("PATCHES must be classified as the active semantic delta ledger")
    patch_states = set(delta_ledger.get("allowedStates", []))
    patch_dispositions = set(delta_ledger.get("allowedUpstreamDispositions", []))
    patch_evidence_classes = set(delta_ledger.get("allowedEvidenceClasses", []))
    benchmark_statuses = set(delta_ledger.get("allowedBenchmarkEvidenceStatuses", []))
    if patch_states != EXPECTED_PATCH_STATES:
        errors.append("PATCHES allowedStates differs from the controlled vocabulary")
    if patch_dispositions != EXPECTED_UPSTREAM_DISPOSITIONS:
        errors.append("PATCHES allowedUpstreamDispositions differs from the controlled vocabulary")
    if patch_evidence_classes != EXPECTED_EVIDENCE_CLASSES:
        errors.append("PATCHES allowedEvidenceClasses differs from the controlled vocabulary")
    if benchmark_statuses != EXPECTED_BENCHMARK_EVIDENCE_STATUSES:
        errors.append("PATCHES benchmark evidence statuses differ from the controlled vocabulary")
    known_records = benchmark_records(repo_root)
    patch_patterns: list[str] = []
    for item in patches:
        patch_id = item.get("id", "<missing>")
        patterns = list(item.get("files", []))
        tests = list(item.get("tests", []))
        documentation = list(item.get("documentation", []))
        patch_patterns.extend(patterns)
        for label, references in (
            ("implementation", patterns),
            ("test", tests),
            ("documentation", documentation),
        ):
            unsafe = [value for value in references if not safe_contract_reference(str(value))]
            if unsafe:
                errors.append(f"{patch_id}: unsafe {label} references {unsafe}")
        if item.get("state") not in patch_states:
            errors.append(f"{patch_id}: invalid patch state {item.get('state')!r}")
        disposition = item.get("upstreamDisposition")
        if disposition not in patch_dispositions:
            errors.append(f"{patch_id}: invalid upstream disposition {disposition!r}")
        if not patch_state_disposition_valid(str(item.get("state")), str(disposition)):
            errors.append(
                f"{patch_id}: patch state {item.get('state')!r} is incompatible with "
                f"upstream disposition {disposition!r}"
            )
        equivalent = item.get("upstreamEquivalentCommit")
        if disposition in {"upstreamed", "equivalent", "shared-upstream"} and not (
            isinstance(equivalent, str) and re.fullmatch(r"[0-9a-f]{40}", equivalent)
        ):
            errors.append(f"{patch_id}: upstream disposition requires a 40-character equivalent commit")
        if disposition not in {"upstreamed", "equivalent", "shared-upstream"} and equivalent is not None:
            errors.append(f"{patch_id}: upstream equivalent commit must be null for {disposition!r}")
        evidence_class = item.get("evidenceClass")
        if evidence_class not in patch_evidence_classes:
            errors.append(f"{patch_id}: invalid evidence class {evidence_class!r}")
        if item.get("state") in LIVE_PATCH_STATES:
            if not expanded(runtime, patterns):
                errors.append(f"{patch_id}: implementation patterns match no files")
            if not expanded(runtime, tests):
                errors.append(f"{patch_id}: test references match no files")
            if not expanded(runtime, documentation):
                errors.append(f"{patch_id}: documentation references match no files")
        if not str(item.get("removalCriteria", "")).strip():
            errors.append(f"{patch_id}: removal criteria are required")
        record_ids = list(item.get("benchmarkRecordIDs", []))
        missing_records = sorted(set(record_ids) - set(known_records))
        if missing_records:
            errors.append(f"{patch_id}: missing benchmark records {missing_records}")
        if evidence_class == "benchmark":
            status = item.get("benchmarkEvidenceStatus")
            if status not in benchmark_statuses:
                errors.append(f"{patch_id}: benchmark evidence status is missing or invalid")
            if status != "unverified" and not record_ids:
                errors.append(f"{patch_id}: {status} benchmark evidence requires a record")
            if status in {"diagnostic", "unverified"} and not str(
                item.get("benchmarkEvidenceReason", "")
            ).strip():
                errors.append(f"{patch_id}: non-verified benchmark evidence requires a reason")
            patch_fresh = any(
                benchmark_record_matches_sources(
                    repo_root,
                    runtime,
                    patterns,
                    known_records[record_id],
                )
                for record_id in record_ids
                if record_id in known_records
            )
            if status == "verified" and not patch_fresh:
                errors.append(
                    f"{patch_id}: current semantic-delta sources differ from every benchmark "
                    "record; evidence must be diagnostic or unverified"
                )

    capability_items = capabilities.get("capabilities", [])
    capability_ids = [item.get("id") for item in capability_items]
    if len(capability_ids) != len(set(capability_ids)) or any(not value for value in capability_ids):
        errors.append("RUNTIME_CAPABILITIES entries require unique non-empty ids")
    allowed_states = set(capabilities.get("allowedStates", []))
    capability_evidence_classes = set(capabilities.get("allowedEvidenceClasses", []))
    capability_benchmark_statuses = set(capabilities.get("allowedBenchmarkEvidenceStatuses", []))
    if allowed_states != EXPECTED_CAPABILITY_STATES:
        errors.append("RUNTIME_CAPABILITIES allowedStates differs from the controlled vocabulary")
    if capability_evidence_classes != EXPECTED_EVIDENCE_CLASSES:
        errors.append(
            "RUNTIME_CAPABILITIES allowedEvidenceClasses differs from the controlled vocabulary"
        )
    if capability_benchmark_statuses != EXPECTED_BENCHMARK_EVIDENCE_STATUSES:
        errors.append(
            "RUNTIME_CAPABILITIES benchmark evidence statuses differ from the controlled vocabulary"
        )
    errors.extend(facade_capability_boundary_errors(capabilities))
    covered_patterns: list[str] = []
    referenced_patch_ids: set[str] = set()
    for item in capability_items:
        capability_id = item.get("id", "<missing>")
        patterns = list(item.get("sourcePatterns", []))
        tests = list(item.get("testPatterns", []))
        documentation = list(item.get("documentation", []))
        covered_patterns.extend(patterns)
        for label, references in (
            ("source", patterns),
            ("test", tests),
            ("documentation", documentation),
        ):
            unsafe = [value for value in references if not safe_contract_reference(str(value))]
            if unsafe:
                errors.append(f"{capability_id}: unsafe {label} references {unsafe}")
        if item.get("state") not in allowed_states:
            errors.append(f"{capability_id}: invalid capability state {item.get('state')!r}")
        evidence_class = item.get("evidenceClass")
        if evidence_class not in capability_evidence_classes:
            errors.append(f"{capability_id}: invalid evidence class {evidence_class!r}")
        if not expanded(runtime, patterns):
            errors.append(f"{capability_id}: source patterns match no files")
        if not expanded(runtime, tests):
            errors.append(f"{capability_id}: test patterns match no files")
        if not expanded(runtime, documentation):
            errors.append(f"{capability_id}: documentation patterns match no files")
        records = list(item.get("benchmarkRecordIDs", []))
        missing_records = sorted(set(records) - set(known_records))
        if missing_records:
            errors.append(f"{capability_id}: missing benchmark records {missing_records}")
        if evidence_class == "benchmark":
            errors.extend(
                capability_benchmark_evidence_errors(
                    repo_root,
                    runtime,
                    item,
                    known_records,
                    capability_benchmark_statuses,
                    patches_by_id,
                )
            )
        delta_ids = set(item.get("upstreamDeltaIDs", []))
        referenced_patch_ids.update(delta_ids)
        unknown_deltas = sorted(delta_ids - patch_ids)
        if unknown_deltas:
            errors.append(f"{capability_id}: unknown semantic delta IDs {unknown_deltas}")
    unreferenced_patches = sorted(patch_ids - referenced_patch_ids)
    if unreferenced_patches:
        errors.append(f"semantic patch entries lack capability ownership: {unreferenced_patches}")

    baseline_entries = baseline.get("entries", [])
    baseline_paths = [entry.get("path") for entry in baseline_entries]
    if len(baseline_paths) != len(set(baseline_paths)) or any(not value for value in baseline_paths):
        errors.append("UPSTREAM_BASELINE requires unique non-empty paths")
    if any(
        not isinstance(entry.get("sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", entry.get("sha256", "")) is None
        for entry in baseline_entries
    ):
        errors.append("UPSTREAM_BASELINE entries require immutable non-null SHA-256 values")
    if baseline.get("scope") != list(BASELINE_SCOPE):
        errors.append("UPSTREAM_BASELINE scope differs from the governed retained scope")

    expected_inventory = make_current_inventory(runtime, baseline, component_id)
    if current_inventory != expected_inventory:
        errors.append(
            "CURRENT_INVENTORY is stale; run "
            "python3 scripts/vendor_runtime_contract.py rebuild-current-inventory"
        )
    current_entries = current_inventory.get("entries", [])
    current_paths = [entry.get("path") for entry in current_entries]
    if len(current_paths) != len(set(current_paths)) or any(not value for value in current_paths):
        errors.append("CURRENT_INVENTORY requires unique non-empty paths")
    if any(entry.get("upstreamStatus") not in ALLOWED_UPSTREAM_STATUSES for entry in current_entries):
        errors.append("CURRENT_INVENTORY contains an invalid upstream status")

    changed_or_added_implementation = sorted(
        str(entry["path"])
        for entry in current_entries
        if entry.get("upstreamStatus") in {"modified", "added"}
        and matches(str(entry.get("path", "")), list(IMPLEMENTATION_SCOPE))
    )
    missing_capability = sorted(
        path for path in changed_or_added_implementation if not matches(path, covered_patterns)
    )
    if missing_capability:
        errors.append(
            f"changed or added implementation files lack capability coverage: {missing_capability}"
        )
    missing_patch = sorted(
        path for path in changed_or_added_implementation if not matches(path, patch_patterns)
    )
    if missing_patch:
        errors.append(
            f"changed or added implementation files lack semantic patch coverage: {missing_patch}"
        )
    missing_linked_semantics = []
    for path in changed_or_added_implementation:
        linked = any(
            matches(path, list(capability.get("sourcePatterns", [])))
            and any(
                patch_id in patches_by_id
                and matches(path, list(patches_by_id[patch_id].get("files", [])))
                for patch_id in capability.get("upstreamDeltaIDs", [])
            )
            for capability in capability_items
        )
        if not linked:
            missing_linked_semantics.append(path)
    if missing_linked_semantics:
        errors.append(
            "changed or added implementation files lack linked capability/patch ownership: "
            f"{missing_linked_semantics}"
        )

    risk = load_json(repo_root / "config/backend-risk-spine.json")
    capability_id_set = set(capability_ids)
    for item in risk.get("items", []):
        if str(item.get("source", "")).startswith(RUNTIME_RELATIVE.as_posix()):
            link = item.get("runtimeCapabilityID")
            if link not in capability_id_set:
                errors.append(
                    f"backend-risk-spine {item.get('id')}: invalid or missing runtimeCapabilityID"
                )

    return sorted(set(errors))


def make_baseline(
    upstream: Path,
    runtime: Path,
    commit: str,
    component_id: str,
    retained_paths: list[str] | None = None,
) -> dict:
    entries = []
    candidates = (
        retained_paths
        if retained_paths is not None
        else [path.relative_to(runtime).as_posix() for path in scoped_files(runtime)]
    )
    for relative in sorted(candidates):
        upstream_path = upstream / relative
        if not upstream_path.is_file():
            if retained_paths is not None:
                raise ValueError(f"immutable upstream baseline path is missing: {relative}")
            continue
        entries.append(
            {
                "path": relative,
                "sha256": sha256(upstream_path),
            }
        )
    return {
        "schemaVersion": 2,
        "componentID": component_id,
        "upstreamCommit": commit,
        "scope": list(BASELINE_SCOPE),
        "entries": entries,
    }


def write_atomic(path: Path, payload: dict) -> None:
    temporary = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1], help=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("validate")
    rebuild = subparsers.add_parser("rebuild-baseline")
    rebuild.add_argument("--upstream-dir", type=Path, required=True)
    subparsers.add_parser("rebuild-current-inventory")
    subparsers.add_parser("rebuild-facade-api-baseline")
    arguments = parser.parse_args(argv)
    root = arguments.repo_root.resolve()

    if arguments.command in (None, "validate"):
        errors = validate(root)
        if errors:
            print("\n".join(f"error: {error}" for error in errors), file=sys.stderr)
            return 1
        print("Owned Qwen3 runtime contract: PASS")
        return 0

    runtime = root / RUNTIME_RELATIVE
    lineage = load_json(runtime / LINEAGE_NAME)
    manifest = load_json(runtime / MANIFEST_NAME)
    commit = lineage["origin"]["commit"]
    component_id = manifest["componentID"]
    if arguments.command == "rebuild-baseline":
        upstream = arguments.upstream_dir.resolve()
        if not (upstream / "Package.swift").is_file():
            print("error: --upstream-dir is not an mlx-audio-swift checkout", file=sys.stderr)
            return 1
        upstream_head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=upstream,
            check=False,
            capture_output=True,
            text=True,
        )
        if upstream_head.returncode != 0 or upstream_head.stdout.strip() != commit:
            print(
                f"error: --upstream-dir must be checked out exactly at immutable origin {commit}",
                file=sys.stderr,
            )
            return 1
        if not git_checkout_is_clean(upstream):
            print(
                "error: --upstream-dir must be a clean checkout; refusing to hash modified, "
                "staged, or untracked files into the immutable baseline",
                file=sys.stderr,
            )
            return 1
        existing_baseline = load_json(runtime / BASELINE_NAME)
        try:
            rebuilt_baseline = make_baseline(
                upstream,
                runtime,
                commit,
                component_id,
                [str(entry["path"]) for entry in existing_baseline.get("entries", [])],
            )
        except ValueError as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
        write_atomic(runtime / BASELINE_NAME, rebuilt_baseline)
        print(
            "Rebuilt the immutable import baseline. Update LINEAGE.json baselineInventory.sha256 "
            "only when an explicitly approved lineage change is intended, then rebuild the "
            "current inventory."
        )
        return 0

    if arguments.command == "rebuild-facade-api-baseline":
        write_atomic(runtime / FACADE_API_BASELINE_NAME, make_facade_api_baseline(runtime))
        print("Rebuilt the canonical VocelloQwen3Core public declaration inventory.")
        return 0

    baseline = load_json(runtime / BASELINE_NAME)
    write_atomic(
        runtime / CURRENT_INVENTORY_NAME,
        make_current_inventory(runtime, baseline, component_id),
    )
    print("Rebuilt the derived current retained inventory and upstream delta classification.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
