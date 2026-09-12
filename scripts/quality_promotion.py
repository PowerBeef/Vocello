#!/usr/bin/env python3
"""Create and validate source-bound quality evidence for public promotion."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any

import benchmark_history
from lib import jsonio  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = Path("config/quality-promotion-contract.json")
SCHEMA_VERSION = 2
CONTRACT_SCHEMA_VERSION = 3
MODEL_CONTRACT_PATH = Path("Sources/Resources/qwenvoice_contract.json")
DIGEST_RE = re.compile(r"[0-9a-f]{64}")
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
TAG_RE = re.compile(r"v\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?")


class PromotionError(ValueError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return jsonio.canonical_bytes(value, ascii=False, newline=True, allow_nan=True)


def digest_value(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


file_digest = jsonio.sha256_file


def read_json(path: Path) -> dict[str, Any]:
    return jsonio.load_json(path, error=PromotionError)


atomic_json = jsonio.atomic_json


def load_contract(root: Path = ROOT) -> dict[str, Any]:
    return read_json(root / CONTRACT_PATH)


def model_applicability(contract: dict[str, Any], root: Path) -> dict[str, dict[str, bool]]:
    """Validate eligibility against the source contract; no operator-authored waiver."""
    binding = contract.get("modelApplicabilitySource")
    if not isinstance(binding, dict) or set(binding) != {"path", "sha256"}:
        raise PromotionError("model applicability source binding is missing")
    if binding["path"] != MODEL_CONTRACT_PATH.as_posix():
        raise PromotionError("model applicability must use the production model contract")
    path = root / MODEL_CONTRACT_PATH
    if not path.is_file() or binding["sha256"] != file_digest(path):
        raise PromotionError("model applicability source digest differs")
    models = read_json(path).get("models")
    if not isinstance(models, list) or len(models) != 3 or {
        model.get("mode") for model in models if isinstance(model, dict)
    } != {"custom", "design", "clone"}:
        raise PromotionError("model applicability requires all three production modes")
    result: dict[str, dict[str, bool]] = {}
    for kind in ("speed", "quality"):
        eligible: dict[str, list[bool]] = {"ios": [], "macos": []}
        for model in models:
            variants = model.get("variants")
            if not isinstance(variants, list) or any(not isinstance(v, dict) for v in variants):
                raise PromotionError("model applicability variants are malformed")
            selected = [v for v in variants if v.get("kind") == kind]
            if len(selected) != 1:
                raise PromotionError(f"model applicability requires one {kind} variant per mode")
            variant = selected[0]
            platforms = variant.get("platforms")
            if (not isinstance(platforms, list) or not platforms
                    or any(not isinstance(p, str) or p not in {"iOS", "macOS"} for p in platforms)
                    or len(set(platforms)) != len(platforms)
                    or type(variant.get("iosDownloadEligible")) is not bool
                    or variant["iosDownloadEligible"] != ("iOS" in platforms)):
                raise PromotionError("model applicability platform eligibility disagrees")
            eligible["ios"].append("iOS" in platforms)
            eligible["macos"].append("macOS" in platforms)
        if any(any(values) != all(values) for values in eligible.values()):
            raise PromotionError("partial mode applicability requires an explicit coverage migration")
        result[f"{kind}-generation"] = {p: all(values) for p, values in eligible.items()}
    return result


def validate_contract(contract: dict[str, Any], *, root: Path = ROOT) -> None:
    version = contract.get("schemaVersion")
    if type(version) is not int or version not in {2, CONTRACT_SCHEMA_VERSION}:
        raise PromotionError("quality promotion contract schemaVersion must be 2 or 3")
    applicability = model_applicability(contract, root) if version == 3 else {}
    if version == 2 and "modelApplicabilitySource" in contract:
        raise PromotionError("historical contract cannot add applicability waivers")
    if contract.get("publicPromotionPolicy") != "source-bound-quality-evidence":
        raise PromotionError("public promotion policy must remain source-bound-quality-evidence")
    age = contract.get("maxEvidenceAgeSeconds")
    if not isinstance(age, int) or age <= 0:
        raise PromotionError("maxEvidenceAgeSeconds must be positive")
    warnings = contract.get("allowedWarnings")
    if not isinstance(warnings, list) or len(warnings) != len(set(warnings)) or any(
        not isinstance(item, str) or not item for item in warnings
    ):
        raise PromotionError("allowedWarnings must be a unique string array")
    definitions = contract.get("evidence")
    if not isinstance(definitions, dict) or not definitions:
        raise PromotionError("quality promotion evidence definitions are missing")
    for identity, definition in definitions.items():
        if not isinstance(identity, str) or not re.fullmatch(r"[a-z][a-z0-9-]+", identity):
            raise PromotionError(f"invalid quality evidence id: {identity!r}")
        if not isinstance(definition, dict) or definition.get("platform") not in {"macos", "ios"}:
            raise PromotionError(f"{identity} has no supported platform")
        evidence_type = definition.get("type")
        if evidence_type == "benchmark-record":
            if definition.get("kind") not in benchmark_history.V2_KINDS:
                raise PromotionError(f"{identity} has an unsupported benchmark kind")
            if definition.get("matrixScope") not in benchmark_history.MATRIX_SCOPES:
                raise PromotionError(f"{identity} has an unsupported matrix scope")
            classifications = definition.get("classifications")
            if not isinstance(classifications, list) or not classifications or set(classifications) - benchmark_history.CLASSIFICATIONS:
                raise PromotionError(f"{identity} has invalid classifications")
            coverage = definition.get("requiredTakeCoverage", {})
            if not isinstance(coverage, dict) or set(coverage) - {
                "modes", "variants", "cellPatterns", "metricKeys"
            }:
                raise PromotionError(f"{identity} has invalid requiredTakeCoverage")
            for field, values in coverage.items():
                if (
                    not isinstance(values, list)
                    or not values
                    or len(values) != len(set(values))
                    or any(not isinstance(value, str) or not value for value in values)
                ):
                    raise PromotionError(f"{identity}.{field} must be a non-empty unique string array")
        elif evidence_type == "managed-command":
            command = definition.get("command")
            if not isinstance(command, list) or not command or any(not isinstance(item, str) or not item for item in command):
                raise PromotionError(f"{identity} has an invalid managed command")
        else:
            raise PromotionError(f"{identity} has unsupported type {evidence_type!r}")
    minimum = contract.get("platformMinimumEvidence")
    if not isinstance(minimum, dict) or set(minimum) != {"macos", "ios"}:
        raise PromotionError("platformMinimumEvidence must define macos and ios")
    for platform, identities in minimum.items():
        if not isinstance(identities, list) or not identities:
            raise PromotionError(f"{platform} promotion minimum is empty")
        for identity in identities:
            if identity not in definitions or definitions[identity].get("platform") != platform:
                raise PromotionError(f"{platform} promotion minimum references invalid evidence {identity}")
    capabilities = contract.get("capabilities")
    if not isinstance(capabilities, dict) or not capabilities:
        raise PromotionError("quality promotion capabilities are missing")
    if set(applicability) - capabilities.keys():
        raise PromotionError("model generation capabilities cannot be omitted")
    for capability, definition in capabilities.items():
        if not isinstance(capability, str) or re.fullmatch(r"[a-z][a-z0-9-]+", capability) is None:
            raise PromotionError(f"invalid promotion capability id: {capability!r}")
        keys = {"evidenceByPlatform", "unsupportedDimensions"}
        if capability in applicability:
            keys.add("platformApplicability")
        if not isinstance(definition, dict) or set(definition) != keys:
            raise PromotionError(f"{capability} capability definition is malformed")
        if capability in applicability:
            declared = definition["platformApplicability"]
            if (not isinstance(declared, dict) or set(declared) != {"macos", "ios"}
                    or any(type(value) is not bool for value in declared.values())
                    or declared != applicability[capability]):
                raise PromotionError(f"{capability} platform applicability disagrees with source")
        by_platform = definition["evidenceByPlatform"]
        if not isinstance(by_platform, dict) or set(by_platform) != {"macos", "ios"}:
            raise PromotionError(f"{capability} must map evidence for macos and ios")
        for platform, identities in by_platform.items():
            applies = applicability.get(capability, {}).get(platform, True)
            if (not isinstance(identities, list)
                    or any(not isinstance(identity, str) for identity in identities)
                    or bool(identities) != applies or len(identities) != len(set(identities))):
                raise PromotionError(f"{capability}.{platform} evidence is invalid")
            for identity in identities:
                if identity not in definitions or definitions[identity].get("platform") != platform:
                    raise PromotionError(f"{capability}.{platform} references invalid evidence {identity}")
            if capability in applicability and applies:
                kind = capability.removesuffix("-generation")
                if not any(
                    set(definitions[i].get("requiredTakeCoverage", {}).get("variants", [])) == {kind}
                    and set(definitions[i].get("requiredTakeCoverage", {}).get("modes", []))
                    == {"custom", "design", "clone"}
                    for i in identities
                ):
                    raise PromotionError(f"{capability}.{platform} lacks source-applicable tier/mode coverage")
        unsupported = definition["unsupportedDimensions"]
        if (
            not isinstance(unsupported, list)
            or len(unsupported) != len(set(unsupported))
            or any(not isinstance(value, str) or not value for value in unsupported)
        ):
            raise PromotionError(f"{capability}.unsupportedDimensions is invalid")
    privacy = contract.get("privacy")
    if not isinstance(privacy, dict) or privacy.get("deviceIdentity") != "canonical-hardware-profile-only":
        raise PromotionError("quality promotion privacy policy is invalid")
    forbidden = privacy.get("forbiddenKeys")
    if not isinstance(forbidden, list) or not forbidden:
        raise PromotionError("quality promotion privacy forbiddenKeys are missing")
    routing = contract.get("promotionRouting")
    if routing is None:
        if version != 2:
            raise PromotionError("quality promotion contract v3 requires promotionRouting")
        return
    classes = routing.get("classes") if isinstance(routing, dict) else None
    if not isinstance(classes, list) or not classes:
        raise PromotionError("promotionRouting.classes must be a non-empty list")
    seen: set[str] = set()
    for item in classes:
        identity = item.get("id") if isinstance(item, dict) else None
        if not isinstance(identity, str) or not identity or identity in seen:
            raise PromotionError("promotionRouting class ids must be unique non-empty strings")
        seen.add(identity)
        for field in ("include", "exclude"):
            patterns = item.get(field, [])
            if not isinstance(patterns, list) or (field == "include" and not patterns) or any(
                not isinstance(pattern, str) or not pattern for pattern in patterns
            ):
                raise PromotionError(f"promotionRouting class {identity}.{field} must list non-empty globs")
        unknown = sorted(set(item.get("requiredEvidence", [])) - definitions.keys())
        if unknown:
            raise PromotionError(f"promotionRouting class {identity} references undefined evidence: " + ", ".join(unknown))
        unknown_capabilities = sorted(set(item.get("capabilities", [])) - capabilities.keys())
        if unknown_capabilities:
            raise PromotionError(
                f"promotionRouting class {identity} references undefined capabilities: " + ", ".join(unknown_capabilities)
            )


def git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(["git", *arguments], cwd=root, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        raise PromotionError(completed.stderr.strip() or f"git {' '.join(arguments)} failed")
    return completed.stdout.strip()


def resolve_commit(root: Path, value: str) -> str:
    commit = git(root, "rev-parse", f"{value}^{{commit}}")
    if COMMIT_RE.fullmatch(commit) is None:
        raise PromotionError(f"cannot resolve commit {value!r}")
    return commit


def parse_time(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise PromotionError(f"{label} is missing")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise PromotionError(f"{label} is invalid") from error


def privacy_scan(value: Any, contract: dict[str, Any], path: str = "manifest") -> None:
    forbidden = {str(item).casefold() for item in contract["privacy"]["forbiddenKeys"]}
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).casefold() in forbidden:
                raise PromotionError(f"quality promotion manifest contains forbidden key at {path}.{key}")
            privacy_scan(child, contract, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            privacy_scan(child, contract, f"{path}[{index}]")
    elif isinstance(value, str) and (
        re.search(r"(?:^|\s)/Users/[^/\s]+/", value)
        or re.search(r"(?:^|\s)/home/[^/\s]+/", value)
        or "file:///" in value
    ):
        raise PromotionError(f"quality promotion manifest contains an absolute user path at {path}")


def release_identity(path: Path, platform: str, tag: str, root: Path) -> tuple[dict[str, Any], str]:
    if TAG_RE.fullmatch(tag) is None:
        raise PromotionError("promotion tag is invalid")
    evidence = read_json(path)
    release = evidence.get("release")
    source = evidence.get("sourceIdentity")
    if evidence.get("schemaVersion") != 2 or not isinstance(release, dict) or not isinstance(source, dict):
        raise PromotionError("release evidence is malformed")
    if release.get("tag") != tag or release.get("platform") != platform:
        raise PromotionError("release evidence belongs to another tag or platform")
    commit = release.get("commitSHA")
    if not isinstance(commit, str) or COMMIT_RE.fullmatch(commit) is None:
        raise PromotionError("release evidence commit is invalid")
    if resolve_commit(root, tag) != commit:
        raise PromotionError("release evidence is not bound to the tag commit")
    if source.get("gitCommit") != commit or source.get("treeDirty") is not False:
        raise PromotionError("release source identity is dirty or cross-source")
    identity_digest = source.get("identityDigest")
    if not isinstance(identity_digest, str) or DIGEST_RE.fullmatch(identity_digest) is None:
        raise PromotionError("release source identity digest is invalid")
    return evidence, commit


def changed_paths(root: Path, base: str, commit: str) -> tuple[str, list[str]]:
    base_commit = resolve_commit(root, base)
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", base_commit, commit], cwd=root, check=False,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if ancestor.returncode != 0 or base_commit == commit:
        raise PromotionError("promotion base must be a distinct ancestor of the candidate")
    paths = git(root, "diff", "--name-only", f"{base_commit}..{commit}").splitlines()
    return base_commit, sorted(set(filter(None, paths)))


def _matches(path: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(path, pattern) or (
        pattern.endswith("/**") and (path == pattern[:-3] or path.startswith(pattern[:-2]))
    )


def _class_matches(path: str, item: dict[str, Any]) -> bool:
    return any(_matches(path, pattern) for pattern in item["include"]) and not any(
        _matches(path, pattern) for pattern in item.get("exclude", [])
    )


def classify_paths(contract: dict[str, Any], paths: list[str]) -> dict[str, Any]:
    """Route changed paths through the contract's own promotionRouting classes.

    The result names the classes hit, the extra evidence lanes they require and
    the capabilities whose coverage the manifest must state. A path that
    matches no class adds nothing: the platform minimum always applies.
    """
    normalized: list[str] = []
    for raw in sorted(set(paths)):
        path = raw.replace("\\", "/")
        while path.startswith("./"):
            path = path[2:]
        normalized.append(path.lstrip("/"))
    classes = (contract.get("promotionRouting") or {}).get("classes") or []
    matched = {item["id"]: item for item in classes if any(_class_matches(path, item) for path in normalized)}
    return {
        "changedPaths": normalized,
        "changedPathsDigest": digest_value(normalized),
        "classes": sorted(matched),
        "promotionRequiredEvidence": sorted({ref for item in matched.values() for ref in item.get("requiredEvidence", [])}),
        "promotionCapabilities": sorted({cap for item in matched.values() for cap in item.get("capabilities", [])}),
    }


def required_evidence(
    contract: dict[str, Any], impact_result: dict[str, Any], platform: str
) -> list[str]:
    definitions = contract["evidence"]
    identities = set(contract["platformMinimumEvidence"][platform])
    identities.update(impact_result.get("promotionRequiredEvidence") or [])
    for capability in impact_result.get("promotionCapabilities") or []:
        identities.update(contract["capabilities"][capability]["evidenceByPlatform"][platform])
    return sorted(identity for identity in identities if definitions.get(identity, {}).get("platform") == platform)


def capability_coverage(
    contract: dict[str, Any], impact_result: dict[str, Any], platform: str
) -> tuple[dict[str, Any], list[str]]:
    result: dict[str, Any] = {}
    unsupported: set[str] = set()
    for capability in sorted(impact_result.get("promotionCapabilities") or []):
        definition = contract["capabilities"][capability]
        dimensions = sorted(definition["unsupportedDimensions"])
        unsupported.update(f"{capability}:{dimension}" for dimension in dimensions)
        result[capability] = {
            "requiredEvidence": sorted(definition["evidenceByPlatform"][platform]),
            "unsupportedDimensions": dimensions,
        }
        if "platformApplicability" in definition:
            applies = definition["platformApplicability"][platform]
            result[capability]["platformApplicability"] = {
                "status": "applicable" if applies else "unsupported",
                "reason": "catalog-eligible" if applies else "no-catalog-eligible-variant",
                "sourceSHA256": contract["modelApplicabilitySource"]["sha256"],
            }
            if not applies:
                unsupported.add(f"{capability}:platform-{platform}")
    return result, sorted(unsupported)


def validate_take_coverage(identity: str, record: dict[str, Any], definition: dict[str, Any]) -> None:
    coverage = definition.get("requiredTakeCoverage") or {}
    if not coverage:
        return
    takes = record.get("takes") or []
    for field in ("modes", "variants"):
        required = set(coverage.get(field) or [])
        take_key = field[:-1]
        observed = {str(take.get(take_key)) for take in takes}
        missing = sorted(required - observed)
        if missing:
            raise PromotionError(f"{identity} lacks required {field}: {', '.join(missing)}")
    cells = [str(take.get("cell", "")) for take in takes]
    missing_patterns = [
        pattern for pattern in coverage.get("cellPatterns", [])
        if not any(fnmatch.fnmatchcase(cell, pattern) for cell in cells)
    ]
    if missing_patterns:
        raise PromotionError(
            f"{identity} lacks required cell coverage: {', '.join(missing_patterns)}"
        )
    metric_keys = set(coverage.get("metricKeys") or [])
    observed_metrics = {
        key for take in takes for key in (take.get("metrics") or {})
    }
    missing_metrics = sorted(metric_keys - observed_metrics)
    if missing_metrics:
        raise PromotionError(
            f"{identity} lacks required analyzer metrics: {', '.join(missing_metrics)}"
        )


def validate_record(
    identity: str, record: dict[str, Any], definition: dict[str, Any], release: dict[str, Any],
    commit: str, accepted_warnings: set[str], contract: dict[str, Any], now: datetime,
) -> dict[str, Any]:
    try:
        benchmark_history.validate_record(record)
    except benchmark_history.HistoryError as error:
        raise PromotionError(f"{identity} benchmark record is invalid: {error}") from error
    run = record["run"]
    source = record["source"]
    toolchain = record["toolchain"]
    if (
        run.get("platform") != definition["platform"]
        or run.get("kind") != definition["kind"]
        or run.get("matrixScope") != definition["matrixScope"]
        or run.get("classification") not in definition["classifications"]
    ):
        raise PromotionError(f"{identity} benchmark record has the wrong lane identity")
    validate_take_coverage(identity, record, definition)
    if source.get("commit") != commit or source.get("dirty") is not False or source.get("fingerprintsMatch") is not True:
        raise PromotionError(f"{identity} benchmark record is dirty or cross-source")
    if source.get("changedPaths") != []:
        raise PromotionError(f"{identity} benchmark record carries changed source paths")
    if (
        toolchain.get("appVersion") != release.get("marketingVersion")
        or toolchain.get("appBuild") != release.get("buildNumber")
        or not toolchain.get("executableHashes")
        or not toolchain.get("executableUUIDs")
    ):
        raise PromotionError(f"{identity} benchmark record differs from the release build identity")
    warnings = set(run.get("warnings") or [])
    if warnings - set(contract["allowedWarnings"]):
        raise PromotionError(f"{identity} uses warnings not allowed by the promotion contract")
    if warnings - accepted_warnings:
        raise PromotionError(f"{identity} has warnings that were not explicitly accepted")
    finished = parse_time(run.get("finishedAt"), f"{identity}.run.finishedAt")
    age = (now - finished).total_seconds()
    if age < -300 or age > contract["maxEvidenceAgeSeconds"]:
        raise PromotionError(f"{identity} benchmark record is outside the promotion freshness window")
    return {
        "type": "benchmark-record",
        "record": record,
        "recordDigest": record["digest"],
        "runID": run["id"],
        "hardwareProfileID": record["hardware"]["profileID"],
    }


def validate_receipt(
    identity: str, receipt: dict[str, Any], definition: dict[str, Any], commit: str,
    contract_digest: str, max_age_seconds: int, now: datetime,
) -> dict[str, Any]:
    expected_keys = {
        "schemaVersion", "evidenceID", "platform", "sourceCommit", "sourceDirty",
        "command", "commandDigest", "startedAt", "finishedAt", "exitCode", "outputDigest",
        "contractDigest", "digest",
    }
    if set(receipt) != expected_keys or receipt.get("schemaVersion") != 1:
        raise PromotionError(f"{identity} managed-command receipt is malformed")
    unsigned = dict(receipt)
    claimed = unsigned.pop("digest")
    if claimed != digest_value(unsigned):
        raise PromotionError(f"{identity} managed-command receipt digest is invalid")
    if (
        receipt.get("evidenceID") != identity
        or receipt.get("platform") != definition["platform"]
        or receipt.get("sourceCommit") != commit
        or receipt.get("sourceDirty") is not False
        or receipt.get("command") != definition["command"]
        or receipt.get("commandDigest") != digest_value(definition["command"])
        or receipt.get("contractDigest") != contract_digest
        or receipt.get("exitCode") != 0
        or DIGEST_RE.fullmatch(str(receipt.get("outputDigest", ""))) is None
    ):
        raise PromotionError(f"{identity} managed-command receipt is cross-source or did not pass")
    started = parse_time(receipt.get("startedAt"), f"{identity}.startedAt")
    finished = parse_time(receipt.get("finishedAt"), f"{identity}.finishedAt")
    if finished < started:
        raise PromotionError(f"{identity} managed-command receipt has reversed timestamps")
    age = (now - finished).total_seconds()
    if age < -300 or age > max_age_seconds:
        raise PromotionError(f"{identity} managed-command receipt is outside the promotion freshness window")
    return {"type": "managed-command", "receipt": receipt, "receiptDigest": receipt["digest"]}


def assignments(values: list[str], label: str) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        identity, separator, path = value.partition("=")
        if not separator or not identity or not path or identity in result:
            raise PromotionError(f"{label} must use unique evidence-id=path assignments")
        result[identity] = Path(path).resolve()
    return result


def create(args: argparse.Namespace) -> dict[str, Any]:
    root = args.root.resolve()
    contract = load_contract(root)
    validate_contract(contract, root=root)
    release_evidence, commit = release_identity(args.release_evidence.resolve(), args.platform, args.tag, root)
    base_commit, paths = changed_paths(root, args.base, commit)
    impact_result = classify_paths(contract, paths)
    required = required_evidence(contract, impact_result, args.platform)
    capabilities, unsupported_dimensions = capability_coverage(
        contract, impact_result, args.platform
    )
    record_paths = assignments(args.record, "--record")
    receipt_paths = assignments(args.receipt, "--receipt")
    supplied = set(record_paths) | set(receipt_paths)
    missing = sorted(set(required) - supplied)
    extra = sorted(supplied - set(required))
    if missing or extra:
        raise PromotionError(f"promotion evidence set differs from required set: missing={missing} extra={extra}")
    accepted = set(args.accept_warning)
    if accepted - set(contract["allowedWarnings"]):
        raise PromotionError("accepted warnings exceed the promotion allowlist")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    contract_digest = digest_value(contract)
    lanes: dict[str, Any] = {}
    for identity in required:
        definition = contract["evidence"][identity]
        if definition["type"] == "benchmark-record":
            path = record_paths.get(identity)
            if path is None:
                raise PromotionError(f"{identity} requires --record")
            lanes[identity] = validate_record(
                identity, read_json(path), definition, release_evidence["release"], commit,
                accepted, contract, now,
            )
        else:
            path = receipt_paths.get(identity)
            if path is None:
                raise PromotionError(f"{identity} requires --receipt")
            lanes[identity] = validate_receipt(
                identity, read_json(path), definition, commit, contract_digest,
                contract["maxEvidenceAgeSeconds"], now,
            )
    manifest: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "platform": args.platform,
        "tag": args.tag,
        "sourceCommit": commit,
        "baseCommit": base_commit,
        "createdAt": now.isoformat().replace("+00:00", "Z"),
        "release": {
            "marketingVersion": release_evidence["release"]["marketingVersion"],
            "buildNumber": release_evidence["release"]["buildNumber"],
            "sourceIdentityDigest": release_evidence["sourceIdentity"]["identityDigest"],
            "releaseEvidenceSHA256": file_digest(args.release_evidence.resolve()),
        },
        "contractDigest": contract_digest,
        "impact": impact_result,
        "capabilityCoverage": capabilities,
        "unsupportedDimensions": unsupported_dimensions,
        "requiredEvidence": required,
        "acceptedWarnings": sorted(accepted),
        "lanes": lanes,
        "privacy": {"containsPrivateDeviceIdentity": False, "containsAbsolutePaths": False},
    }
    manifest["digest"] = digest_value(manifest)
    privacy_scan(manifest, contract)
    return manifest


def validate_manifest(args: argparse.Namespace) -> dict[str, Any]:
    root = args.root.resolve()
    contract = load_contract(root)
    validate_contract(contract, root=root)
    manifest = read_json(args.manifest.resolve())
    expected_top_level = {
        "schemaVersion", "platform", "tag", "sourceCommit", "baseCommit", "createdAt",
        "release", "contractDigest", "impact", "requiredEvidence", "acceptedWarnings",
        "capabilityCoverage", "unsupportedDimensions", "lanes", "privacy", "digest",
    }
    if set(manifest) != expected_top_level:
        raise PromotionError("quality promotion manifest top-level fields are malformed")
    privacy_scan(manifest, contract)
    claimed_digest = manifest.get("digest")
    unsigned = dict(manifest)
    unsigned.pop("digest", None)
    if claimed_digest != digest_value(unsigned):
        raise PromotionError("quality promotion manifest digest is invalid")
    release_evidence, commit = release_identity(args.release_evidence.resolve(), args.platform, args.tag, root)
    if (
        manifest.get("schemaVersion") != SCHEMA_VERSION
        or manifest.get("platform") != args.platform
        or manifest.get("tag") != args.tag
        or manifest.get("sourceCommit") != commit
        or manifest.get("contractDigest") != digest_value(contract)
        or manifest.get("privacy") != {"containsPrivateDeviceIdentity": False, "containsAbsolutePaths": False}
    ):
        raise PromotionError("quality promotion manifest identity is malformed or cross-source")
    release = manifest.get("release")
    if not isinstance(release, dict) or release != {
        "marketingVersion": release_evidence["release"]["marketingVersion"],
        "buildNumber": release_evidence["release"]["buildNumber"],
        "sourceIdentityDigest": release_evidence["sourceIdentity"]["identityDigest"],
        "releaseEvidenceSHA256": file_digest(args.release_evidence.resolve()),
    }:
        raise PromotionError("quality promotion manifest differs from release evidence")
    base_commit, paths = changed_paths(root, str(manifest.get("baseCommit", "")), commit)
    impact_result = classify_paths(contract, paths)
    impact = manifest.get("impact")
    expected_impact = impact_result
    required = required_evidence(contract, impact_result, args.platform)
    capabilities, unsupported_dimensions = capability_coverage(contract, impact_result, args.platform)
    if (
        base_commit != manifest.get("baseCommit")
        or impact != expected_impact
        or manifest.get("requiredEvidence") != required
        or manifest.get("capabilityCoverage") != capabilities
        or manifest.get("unsupportedDimensions") != unsupported_dimensions
    ):
        raise PromotionError("quality promotion impact classification is stale or incomplete")
    accepted = manifest.get("acceptedWarnings")
    if not isinstance(accepted, list) or accepted != sorted(set(accepted)):
        raise PromotionError("quality promotion accepted warnings are malformed")
    lanes = manifest.get("lanes")
    if not isinstance(lanes, dict) or sorted(lanes) != required:
        raise PromotionError("quality promotion lane set is incomplete")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    for identity in required:
        lane = lanes[identity]
        definition = contract["evidence"][identity]
        if not isinstance(lane, dict):
            raise PromotionError(f"{identity} lane is malformed")
        if definition["type"] == "benchmark-record":
            expected = validate_record(
                identity, lane.get("record"), definition, release_evidence["release"], commit,
                set(accepted), contract, now,
            )
        else:
            expected = validate_receipt(
                identity, lane.get("receipt"), definition, commit, digest_value(contract),
                contract["maxEvidenceAgeSeconds"], now,
            )
        if lane != expected:
            raise PromotionError(f"{identity} lane wrapper differs from its evidence")
    return manifest


def capture(args: argparse.Namespace) -> dict[str, Any]:
    root = args.root.resolve()
    contract = load_contract(root)
    validate_contract(contract, root=root)
    definition = contract["evidence"].get(args.evidence_id)
    if not isinstance(definition, dict) or definition.get("type") != "managed-command":
        raise PromotionError("capture requires a managed-command evidence id")
    if args.platform != definition["platform"] or args.command != definition["command"]:
        raise PromotionError("capture command differs from the contract-bound command")
    commit = resolve_commit(root, args.tag)
    if resolve_commit(root, "HEAD") != commit or git(root, "status", "--porcelain", "--untracked-files=all"):
        raise PromotionError("managed quality capture requires a clean tag checkout")
    started = datetime.now(timezone.utc).replace(microsecond=0)
    scratch = root / "build/scratch/transient/quality-promotion"
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=scratch, prefix="capture-", delete=False) as output:
        output_path = Path(output.name)
        completed = subprocess.run(args.command, cwd=root, stdout=output, stderr=subprocess.STDOUT, check=False)
    try:
        output_digest = file_digest(output_path)
        sys.stdout.buffer.write(output_path.read_bytes())
    finally:
        output_path.unlink(missing_ok=True)
    finished = datetime.now(timezone.utc).replace(microsecond=0)
    if completed.returncode != 0:
        raise PromotionError(f"managed quality command failed with exit code {completed.returncode}")
    if git(root, "status", "--porcelain", "--untracked-files=all"):
        raise PromotionError("managed quality command changed the source tree")
    receipt: dict[str, Any] = {
        "schemaVersion": 1,
        "evidenceID": args.evidence_id,
        "platform": args.platform,
        "sourceCommit": commit,
        "sourceDirty": False,
        "command": args.command,
        "commandDigest": digest_value(args.command),
        "startedAt": started.isoformat().replace("+00:00", "Z"),
        "finishedAt": finished.isoformat().replace("+00:00", "Z"),
        "exitCode": 0,
        "outputDigest": output_digest,
        "contractDigest": digest_value(contract),
    }
    receipt["digest"] = digest_value(receipt)
    return receipt


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    commands = result.add_subparsers(dest="operation", required=True)
    commands.add_parser("validate-contract")
    classify_parser = commands.add_parser(
        "classify", help="show the lanes a candidate must prove, from the paths changed since --base"
    )
    classify_parser.add_argument("--base", required=True)
    classify_parser.add_argument("--platform", choices=("macos", "ios"))
    capture_parser = commands.add_parser("capture")
    capture_parser.add_argument("--evidence-id", required=True)
    capture_parser.add_argument("--platform", choices=("macos", "ios"), required=True)
    capture_parser.add_argument("--tag", required=True)
    capture_parser.add_argument("--output", type=Path, required=True)
    capture_parser.add_argument("command", nargs=argparse.REMAINDER)
    create_parser = commands.add_parser("create")
    create_parser.add_argument("--platform", choices=("macos", "ios"), required=True)
    create_parser.add_argument("--tag", required=True)
    create_parser.add_argument("--base", required=True)
    create_parser.add_argument("--release-evidence", type=Path, required=True)
    create_parser.add_argument("--record", action="append", default=[])
    create_parser.add_argument("--receipt", action="append", default=[])
    create_parser.add_argument("--accept-warning", action="append", default=[])
    create_parser.add_argument("--output", type=Path, required=True)
    validate_parser = commands.add_parser("validate")
    validate_parser.add_argument("--platform", choices=("macos", "ios"), required=True)
    validate_parser.add_argument("--tag", required=True)
    validate_parser.add_argument("--release-evidence", type=Path, required=True)
    validate_parser.add_argument("--manifest", type=Path, required=True)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.operation == "validate-contract":
            contract = load_contract(args.root.resolve())
            validate_contract(contract, root=args.root.resolve())
            print(f"Quality promotion contract: PASS ({digest_value(contract)})")
            return 0
        if args.operation == "classify":
            root = args.root.resolve()
            contract = load_contract(root)
            validate_contract(contract, root=root)
            _base, paths = changed_paths(root, args.base, resolve_commit(root, "HEAD"))
            result = classify_paths(contract, paths)
            platforms = [args.platform] if args.platform else ["macos", "ios"]
            result["requiredEvidenceByPlatform"] = {
                platform: required_evidence(contract, result, platform) for platform in platforms
            }
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        if args.operation == "capture":
            if args.command and args.command[0] == "--":
                args.command = args.command[1:]
            value = capture(args)
            atomic_json(args.output.resolve(), value)
        elif args.operation == "create":
            value = create(args)
            atomic_json(args.output.resolve(), value)
        else:
            value = validate_manifest(args)
        print(f"Quality promotion: PASS ({value['digest']})")
        return 0
    except (PromotionError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
