#!/usr/bin/env python3
"""Build and validate Vocello's immutable production model catalog.

The bundled iPhone catalog owns the three Speed receipts and the repository
receipt document owns the three macOS Quality receipts. This tool projects
those exact per-file sizes and SHA-256 digests onto the cross-platform model
contract without inventing values. ``--require-complete`` fails closed if a
production artifact ever loses its exact identity.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit


REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = Path("Sources/Resources/qwenvoice_contract.json")
IOS_CATALOG_PATH = Path("Sources/Resources/qwenvoice_ios_model_catalog.json")
PRODUCTION_CATALOG_PATH = Path("Sources/Resources/qwenvoice_production_model_catalog.json")
SCHEMA_PATH = Path("config/model-catalog-schema-v2.json")
RECEIPTS_PATH = Path("config/model-artifact-receipts.json")
SCHEMA_VERSION = 2
ALLOWED_HOSTS = ("huggingface.co",)
ALLOWED_REDIRECT_HOST_SUFFIXES = ("huggingface.co", "hf.co")
HEX_40 = re.compile(r"^[0-9a-f]{40}$")
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
MARKING_REQUIRED_PATH = "marking/audioseal_wm16_generator_fp16.safetensors"
SHARED_COMPONENT_ID = "qwen3-speech-tokenizer-v1"
SHARED_COMPONENT_ROOT = "speech_tokenizer"
SHARED_COMPONENT_PATHS = (
    "speech_tokenizer/config.json",
    "speech_tokenizer/configuration.json",
    "speech_tokenizer/model.safetensors",
    "speech_tokenizer/preprocessor_config.json",
)
SHARED_COMPONENT_SOURCE_ORDER = (
    "pro_custom:speed",
    "pro_design:speed",
    "pro_clone:speed",
    "pro_custom:quality",
    "pro_design:quality",
    "pro_clone:quality",
)


class CatalogContractError(RuntimeError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def pretty_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_identity_digest(domain: str, fields: list[str]) -> str:
    hasher = hashlib.sha256()
    for field in [domain, *fields]:
        encoded = field.encode("utf-8")
        hasher.update(struct.pack(">Q", len(encoded)))
        hasher.update(encoded)
    return hasher.hexdigest()


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CatalogContractError(f"cannot read {path}: {error}") from error


def is_safe_relative_path(value: object) -> bool:
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    if "\\" in value or any(ord(character) < 32 for character in value):
        return False
    decoded = unquote(value)
    if decoded != value or decoded.startswith("/"):
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and all(part not in {"", ".", ".."} for part in path.parts)


def parse_base_url(value: object, allowed_hosts: set[str]) -> tuple[str, str]:
    if not isinstance(value, str):
        raise CatalogContractError("artifact baseURL must be a string")
    parsed = urlsplit(value)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in allowed_hosts or parsed.port not in {None, 443}:
        raise CatalogContractError(f"artifact baseURL is outside the HTTPS host policy: {value}")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise CatalogContractError(f"artifact baseURL contains prohibited URL components: {value}")
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    if len(parts) != 4 or parts[2] != "resolve" or not all(is_safe_relative_path(part) for part in parts):
        raise CatalogContractError(f"artifact baseURL is not a pinned Hugging Face resolve URL: {value}")
    repo = f"{parts[0]}/{parts[1]}"
    revision = parts[3]
    if not HEX_40.fullmatch(revision):
        raise CatalogContractError(f"artifact baseURL revision is not an immutable commit: {value}")
    return repo, revision


def validate_file_url(
    value: object,
    *,
    repo: str,
    revision: str,
    relative_path: str,
    allowed_hosts: set[str],
) -> None:
    if not isinstance(value, str):
        raise CatalogContractError("artifact file URL must be a string")
    parsed = urlsplit(value)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in allowed_hosts or parsed.port not in {None, 443}:
        raise CatalogContractError(f"artifact file URL is outside the HTTPS host policy: {value}")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise CatalogContractError(f"artifact file URL contains prohibited URL components: {value}")
    decoded_path = unquote(parsed.path).lstrip("/")
    expected_path = f"{repo}/resolve/{revision}/{relative_path}"
    if decoded_path != expected_path:
        raise CatalogContractError(f"artifact file URL identity mismatch: {value}")


def production_descriptors(contract: dict[str, Any]) -> list[dict[str, Any]]:
    models = contract.get("models")
    if not isinstance(models, list) or not models:
        raise CatalogContractError("qwenvoice contract has no models")

    descriptors: list[dict[str, Any]] = []
    for model in models:
        variants = model.get("variants") or []
        if not variants:
            variants = [{
                "id": "default",
                "platforms": ["macOS"] + (["iOS"] if model.get("iosDownloadEligible") else []),
                "folder": model.get("folder"),
                "huggingFaceRepo": model.get("huggingFaceRepo"),
                "huggingFaceRevision": model.get("huggingFaceRevision"),
                "artifactVersion": model.get("artifactVersion"),
                "estimatedDownloadBytes": model.get("estimatedDownloadBytes"),
                "requiredRelativePaths": model.get("requiredRelativePaths"),
            }]
        for variant in variants:
            platforms = sorted(set(variant.get("platforms") or []))
            descriptor = {
                "modelID": model.get("id"),
                "variantID": variant.get("id"),
                "platforms": platforms,
                "folder": variant.get("folder"),
                "repo": variant.get("huggingFaceRepo"),
                "revision": variant.get("huggingFaceRevision"),
                "artifactVersion": variant.get("artifactVersion"),
                "estimatedDownloadBytes": variant.get("estimatedDownloadBytes"),
                "requiredRelativePaths": variant.get("requiredRelativePaths") or [],
            }
            identity = artifact_identity(descriptor)
            if not all(isinstance(descriptor[key], str) and descriptor[key] for key in (
                "modelID", "variantID", "folder", "repo", "artifactVersion"
            )):
                raise CatalogContractError(f"production descriptor {identity} has incomplete identity")
            if not isinstance(descriptor["revision"], str) or not HEX_40.fullmatch(descriptor["revision"]):
                raise CatalogContractError(f"production descriptor {identity} lacks an immutable revision")
            if not platforms or any(platform not in {"iOS", "macOS"} for platform in platforms):
                raise CatalogContractError(f"production descriptor {identity} has invalid platforms")
            paths = descriptor["requiredRelativePaths"]
            if not paths or len(paths) != len(set(paths)) or not all(is_safe_relative_path(path) for path in paths):
                raise CatalogContractError(f"production descriptor {identity} has unsafe required paths")
            descriptors.append(descriptor)

    identities = [artifact_identity(item) for item in descriptors]
    if len(identities) != len(set(identities)):
        raise CatalogContractError("qwenvoice contract contains duplicate production artifact identities")
    return sorted(descriptors, key=artifact_identity)


def artifact_identity(descriptor: dict[str, Any]) -> str:
    return f"{descriptor.get('modelID', '?')}:{descriptor.get('variantID', '?')}"


def receipt_artifacts(document: dict[str, Any], descriptors: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    models = document.get("models")
    if not isinstance(models, list):
        raise CatalogContractError("artifact receipt source has no models array")
    allowed_hosts = set(ALLOWED_HOSTS)
    results: dict[str, dict[str, Any]] = {}
    for entry in models:
        repo, revision = parse_base_url(entry.get("baseURL"), allowed_hosts)
        matches = [descriptor for descriptor in descriptors if (
            descriptor["modelID"] == entry.get("modelID")
            and descriptor["artifactVersion"] == entry.get("artifactVersion")
            and descriptor["repo"] == repo
            and descriptor["revision"] == revision
        )]
        if len(matches) != 1:
            raise CatalogContractError(
                f"artifact receipt {entry.get('modelID')}@{entry.get('artifactVersion')} "
                f"matches {len(matches)} production descriptors"
            )
        descriptor = matches[0]
        identity = artifact_identity(descriptor)
        if identity in results:
            raise CatalogContractError(f"duplicate artifact receipt for {identity}")
        files = entry.get("files")
        if not isinstance(files, list) or not files:
            raise CatalogContractError(f"artifact receipt {identity} has no files")
        normalized_files = []
        seen_paths: set[str] = set()
        total = 0
        for file in files:
            path = file.get("relativePath")
            size = file.get("sizeBytes")
            digest = file.get("sha256")
            if not is_safe_relative_path(path) or path in seen_paths:
                raise CatalogContractError(f"artifact receipt {identity} has an unsafe or duplicate path")
            if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
                raise CatalogContractError(f"artifact receipt {identity} lacks an exact size for {path}")
            if not isinstance(digest, str) or not HEX_64.fullmatch(digest):
                raise CatalogContractError(f"artifact receipt {identity} lacks an exact SHA-256 for {path}")
            if file.get("url") is not None:
                validate_file_url(
                    file["url"],
                    repo=repo,
                    revision=revision,
                    relative_path=path,
                    allowed_hosts=allowed_hosts,
                )
            seen_paths.add(path)
            total += size
            normalized_files.append({"relativePath": path, "sha256": digest, "sizeBytes": size})
        required = set(descriptor["requiredRelativePaths"])
        if seen_paths != required:
            missing = sorted(required - seen_paths)
            extra = sorted(seen_paths - required)
            raise CatalogContractError(f"artifact receipt {identity} path mismatch: missing={missing}, extra={extra}")
        if entry.get("totalBytes") != total or descriptor["estimatedDownloadBytes"] != total:
            raise CatalogContractError(f"artifact receipt {identity} byte count disagrees with its contract")
        results[identity] = {
            "modelID": descriptor["modelID"],
            "variantID": descriptor["variantID"],
            "platforms": descriptor["platforms"],
            "folder": descriptor["folder"],
            "repo": repo,
            "revision": revision,
            "artifactVersion": descriptor["artifactVersion"],
            "baseURL": entry["baseURL"],
            "totalBytes": total,
            "files": sorted(normalized_files, key=lambda item: item["relativePath"]),
            "sharedComponentIDs": [SHARED_COMPONENT_ID],
        }
    return results


def shared_component(artifacts_by_identity: dict[str, dict[str, Any]]) -> dict[str, Any]:
    source_order = (
        SHARED_COMPONENT_SOURCE_ORDER
        if set(SHARED_COMPONENT_SOURCE_ORDER) == set(artifacts_by_identity)
        else tuple(sorted(artifacts_by_identity))
    )
    baseline = artifacts_by_identity[source_order[0]]
    baseline_files = {item["relativePath"]: item for item in baseline["files"]}
    if set(SHARED_COMPONENT_PATHS) - set(baseline_files):
        raise CatalogContractError("baseline artifact lacks the speech_tokenizer component")

    files: list[dict[str, Any]] = []
    for path in SHARED_COMPONENT_PATHS:
        expected = baseline_files[path]
        for identity in source_order[1:]:
            candidate = {
                item["relativePath"]: item
                for item in artifacts_by_identity[identity]["files"]
            }.get(path)
            if candidate != expected:
                raise CatalogContractError(
                    f"shared component {path} differs in artifact {identity}"
                )
        files.append({
            "relativePath": path,
            "byteCount": expected["sizeBytes"],
            "sha256": expected["sha256"],
        })

    fields = [
        field
        for file in files
        for field in (file["relativePath"], str(file["byteCount"]), file["sha256"])
    ]
    content_digest = canonical_identity_digest(
        "vocello.shared-component.content.v1",
        fields,
    )
    component_schema_version = 1
    loader_abi = "vocello-qwen3-speech-tokenizer-v1"
    runtime_profile = "qwen3-tts-12hz-1.7b"
    encoder_capability = "encoderAndDecoder"
    compatibility_digest = canonical_identity_digest(
        "vocello.shared-component.compatibility.v1",
        [
            content_digest,
            str(component_schema_version),
            loader_abi,
            runtime_profile,
            encoder_capability,
        ],
    )
    return {
        "id": SHARED_COMPONENT_ID,
        "relativeRoot": SHARED_COMPONENT_ROOT,
        "contentIdentity": {
            "schemaVersion": 1,
            "digest": content_digest,
            "files": files,
        },
        "compatibilityIdentity": {
            "schemaVersion": 1,
            "digest": compatibility_digest,
            "contentDigest": content_digest,
            "componentSchemaVersion": component_schema_version,
            "loaderABI": loader_abi,
            "runtimeProfileSignature": runtime_profile,
            "encoderCapability": encoder_capability,
        },
        "sourceArtifactIdentities": list(source_order),
    }


def build_catalog(root: Path = REPO_ROOT) -> dict[str, Any]:
    contract_path = root / CONTRACT_PATH
    ios_catalog_path = root / IOS_CATALOG_PATH
    schema_path = root / SCHEMA_PATH
    receipts_path = root / RECEIPTS_PATH
    contract = load_json(contract_path)
    ios_catalog = load_json(ios_catalog_path)
    schema = load_json(schema_path)
    receipts = load_json(receipts_path)
    if schema.get("$id") != "https://vocello.app/schemas/model-catalog-v2.json":
        raise CatalogContractError("model catalog schema has an unexpected identity")
    if receipts.get("schemaVersion") != 1 or not isinstance(receipts.get("artifacts"), list):
        raise CatalogContractError("model artifact receipts have an unsupported schema")
    descriptors = production_descriptors(contract)
    combined_receipts = {
        "models": [*(ios_catalog.get("models") or []), *receipts["artifacts"]]
    }
    artifacts_by_identity = receipt_artifacts(combined_receipts, descriptors)
    missing = [artifact_identity(item) for item in descriptors if artifact_identity(item) not in artifacts_by_identity]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "catalogSchema": str(SCHEMA_PATH),
        "activationState": "complete" if not missing else "staged",
        "allowedArtifactHosts": list(ALLOWED_HOSTS),
        "allowedRedirectHostSuffixes": list(ALLOWED_REDIRECT_HOST_SUFFIXES),
        "sourceDigests": {
            str(CONTRACT_PATH): sha256_bytes(contract_path.read_bytes()),
            str(IOS_CATALOG_PATH): sha256_bytes(ios_catalog_path.read_bytes()),
            str(SCHEMA_PATH): sha256_bytes(schema_path.read_bytes()),
            str(RECEIPTS_PATH): sha256_bytes(receipts_path.read_bytes()),
        },
        "artifacts": [artifacts_by_identity[key] for key in sorted(artifacts_by_identity)],
        "sharedComponents": [shared_component(artifacts_by_identity)] if not missing else [],
        "missingArtifactIdentities": missing,
    }


def validate_catalog(root: Path = REPO_ROOT, require_complete: bool = False) -> dict[str, Any]:
    expected = build_catalog(root)
    catalog_path = root / PRODUCTION_CATALOG_PATH
    actual = load_json(catalog_path)
    errors: list[str] = []
    if actual != expected:
        errors.append(f"{PRODUCTION_CATALOG_PATH} is stale; run model_catalog_contract.py rebuild")
    if actual.get("schemaVersion") != SCHEMA_VERSION:
        errors.append("production catalog schemaVersion is unsupported")
    artifacts = actual.get("artifacts")
    if not isinstance(artifacts, list):
        errors.append("production catalog artifacts must be an array")
        artifacts = []
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            errors.append("production catalog artifact must be an object")
            continue
        try:
            parse_base_url(artifact.get("baseURL"), set(actual.get("allowedArtifactHosts") or []))
        except CatalogContractError as error:
            errors.append(str(error))
        files = artifact.get("files")
        if not isinstance(files, list) or not files or any(
            not isinstance(file, dict)
            or
            not is_safe_relative_path(file.get("relativePath"))
            or not isinstance(file.get("sizeBytes"), int)
            or isinstance(file.get("sizeBytes"), bool)
            or file.get("sizeBytes") <= 0
            or not isinstance(file.get("sha256"), str)
            or not HEX_64.fullmatch(file.get("sha256"))
            for file in files
        ):
            errors.append(f"production catalog artifact {artifact_identity(artifact)} lacks exact file evidence")
    components = actual.get("sharedComponents")
    if actual.get("activationState") == "complete" and (
        not isinstance(components, list) or len(components) != 1
    ):
        errors.append("production catalog must contain one shared speech_tokenizer component")
    # CP-2 marking weights (Article 50): shipped as a required UNIFORM
    # artifact file rather than a store shared component (the delivery
    # planner and installed-model manifest are single-component by design).
    # The check is conditional so pre-rollout catalogs stay valid: once any
    # artifact carries the file, every artifact must carry it at one digest.
    marking_files = {
        artifact_identity(artifact): file
        for artifact in artifacts
        for file in artifact.get("files", [])
        if isinstance(file, dict) and file.get("relativePath") == MARKING_REQUIRED_PATH
    }
    if marking_files:
        missing_marking = sorted(
            artifact_identity(artifact)
            for artifact in artifacts
            if artifact_identity(artifact) not in marking_files
        )
        if missing_marking:
            errors.append(
                "marking weights must be uniform across every artifact; missing from: "
                + ", ".join(missing_marking)
            )
        identities = {
            (file.get("sha256"), file.get("sizeBytes")) for file in marking_files.values()
        }
        if len(identities) > 1:
            errors.append("marking weights differ across artifacts; one exact digest is required")
    missing = actual.get("missingArtifactIdentities")
    if not isinstance(missing, list) or any(not isinstance(item, str) for item in missing):
        errors.append("production catalog missingArtifactIdentities must be an array of strings")
        missing = []
    complete = actual.get("activationState") == "complete" and missing == []
    if require_complete and not complete:
        errors.append(f"production catalog is not complete: missing {', '.join(missing or [])}")
    return {
        "ok": not errors,
        "complete": complete,
        "catalog": str(PRODUCTION_CATALOG_PATH),
        "catalogDigest": sha256_bytes(canonical_bytes(actual)),
        "coveredArtifacts": len(artifacts),
        "missingArtifactIdentities": missing or [],
        "errors": errors,
    }


def command_rebuild(root: Path, check: bool) -> int:
    destination = root / PRODUCTION_CATALOG_PATH
    desired = pretty_bytes(build_catalog(root))
    if check:
        current = destination.read_bytes() if destination.exists() else b""
        if current != desired:
            print(f"error: {PRODUCTION_CATALOG_PATH} is stale", file=sys.stderr)
            return 1
        print(f"PASS: {PRODUCTION_CATALOG_PATH} is reproducible")
        return 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_bytes(desired)
    temporary.replace(destination)
    print(destination)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--require-complete", action="store_true")
    validate_parser.add_argument("--json", action="store_true")
    rebuild_parser = subparsers.add_parser("rebuild")
    rebuild_parser.add_argument("--check", action="store_true")
    subparsers.add_parser("status")
    args = parser.parse_args(argv)

    try:
        if args.command == "rebuild":
            return command_rebuild(args.root.resolve(), args.check)
        result = validate_catalog(args.root.resolve(), require_complete=getattr(args, "require_complete", False))
    except CatalogContractError as error:
        result = {"ok": False, "complete": False, "errors": [str(error)]}

    if args.command == "validate" and not args.json:
        if result["ok"]:
            state = "complete" if result["complete"] else "staged"
            print(f"PASS: production model catalog is valid ({state})")
            if result.get("missingArtifactIdentities"):
                print("pending exact digests: " + ", ".join(result["missingArtifactIdentities"]))
        else:
            for error in result["errors"]:
                print(f"error: {error}", file=sys.stderr)
    else:
        print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
