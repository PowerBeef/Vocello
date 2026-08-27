#!/usr/bin/env python3
"""Build and validate Vocello's offline third-party attribution manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
POLICY = Path("config/third-party-attribution-policy.json")
RESOLVED = Path("QwenVoice.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved")
OWNED_RESOLVED = Path("Packages/VocelloQwen3Core/Package.resolved")
CATALOG = Path("Sources/Resources/qwenvoice_production_model_catalog.json")
OUTPUT = Path("Sources/Resources/third_party_attributions.json")


class ContractError(ValueError):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_bytes(root: Path, relative: str | Path) -> bytes:
    path = root / relative
    try:
        return path.read_bytes()
    except OSError as error:
        raise ContractError(f"cannot read {relative}: {error}") from error


def read_json(root: Path, relative: str | Path) -> dict:
    try:
        value = json.loads(read_bytes(root, relative))
    except json.JSONDecodeError as error:
        raise ContractError(f"invalid JSON in {relative}: {error}") from error
    if not isinstance(value, dict):
        raise ContractError(f"{relative} must contain an object")
    return value


def unique_map(rows: object, key: str, label: str) -> dict[str, dict]:
    if not isinstance(rows, list):
        raise ContractError(f"{label} must be an array")
    result: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get(key), str) or not row[key]:
            raise ContractError(f"{label} contains an invalid {key}")
        if row[key] in result:
            raise ContractError(f"duplicate {label} {key}: {row[key]}")
        result[row[key]] = row
    return result


def https_url(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{label} must be a URL")
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ContractError(f"{label} must be a public HTTPS URL")
    return value


def resolved_pins(document: dict, label: str) -> dict[str, dict]:
    if document.get("version") != 3:
        raise ContractError(f"{label} must use Package.resolved schema 3")
    pins = unique_map(document.get("pins"), "identity", f"{label} pins")
    for identity, pin in pins.items():
        state = pin.get("state")
        if not isinstance(state, dict) or not isinstance(state.get("revision"), str):
            raise ContractError(f"{label} pin {identity} has no revision")
    return pins


def build(root: Path) -> dict:
    policy_bytes = read_bytes(root, POLICY)
    policy = json.loads(policy_bytes)
    if policy.get("schemaVersion") != 1:
        raise ContractError("attribution policy schemaVersion must be 1")

    license_paths = policy.get("licenses")
    if not isinstance(license_paths, dict) or set(license_paths) != {"Apache-2.0", "MIT"}:
        raise ContractError("attribution policy must define Apache-2.0 and MIT license sources")
    licenses: dict[str, dict] = {}
    for identifier, relative in sorted(license_paths.items()):
        if not isinstance(relative, str):
            raise ContractError(f"license path for {identifier} is invalid")
        body = read_bytes(root, relative)
        licenses[identifier] = {
            "id": identifier,
            "sha256": digest(body),
            "text": body.decode("utf-8"),
        }

    resolved_bytes = read_bytes(root, RESOLVED)
    resolved = resolved_pins(json.loads(resolved_bytes), "application resolution")
    owned_bytes = read_bytes(root, OWNED_RESOLVED)
    owned = resolved_pins(json.loads(owned_bytes), "owned-runtime resolution")
    unexpected_owned = sorted(set(owned) - set(resolved))
    if unexpected_owned:
        raise ContractError(f"owned runtime introduces unregistered resolution pins: {unexpected_owned}")
    for identity in sorted(owned):
        if owned[identity]["state"] != resolved[identity]["state"]:
            raise ContractError(f"owned-runtime pin drifts from application resolution: {identity}")

    package_policy = unique_map(policy.get("packages"), "identity", "package policy")
    if set(package_policy) != set(resolved):
        missing = sorted(set(resolved) - set(package_policy))
        extra = sorted(set(package_policy) - set(resolved))
        raise ContractError(f"package policy does not match resolved graph; missing={missing}, extra={extra}")

    components: list[dict] = []
    for identity in sorted(resolved):
        pin = resolved[identity]
        rule = package_policy[identity]
        state = pin["state"]
        license_id = rule.get("licenseID")
        if license_id not in licenses:
            raise ContractError(f"package {identity} has unsupported licenseID")
        upstream_digest = rule.get("upstreamLicenseSHA256")
        if not isinstance(upstream_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", upstream_digest):
            raise ContractError(f"package {identity} lacks an exact upstream license digest")
        notice = None
        notice_path = rule.get("noticePath")
        if notice_path is not None:
            if not isinstance(notice_path, str):
                raise ContractError(f"package {identity} noticePath is invalid")
            notice_bytes = read_bytes(root, notice_path)
            expected = rule.get("upstreamNoticeSHA256")
            if digest(notice_bytes) != expected:
                raise ContractError(f"package {identity} NOTICE digest drift")
            notice = notice_bytes.decode("utf-8")
        components.append({
            "id": identity,
            "displayName": rule.get("displayName"),
            "version": state.get("version") or "revision",
            "revision": state["revision"],
            "sourceURL": https_url(rule.get("sourceURL"), f"package {identity} sourceURL"),
            "licenseID": license_id,
            "upstreamLicenseSHA256": upstream_digest,
            "copyrightNotice": rule.get("copyrightNotice"),
            "notice": notice,
            "scope": "application" if identity not in owned else "application-and-owned-runtime",
        })

    owned_policy = unique_map(policy.get("ownedComponents"), "identity", "owned components")
    marketing_match = re.search(
        r"^\s*MARKETING_VERSION:\s*[\"']?([^\"'\s]+)",
        read_bytes(root, "project.yml").decode("utf-8"),
        re.MULTILINE,
    )
    if not marketing_match:
        raise ContractError("project.yml has no MARKETING_VERSION")
    for identity in sorted(owned_policy):
        rule = owned_policy[identity]
        if identity == "vocello" and rule.get("version") != marketing_match.group(1):
            raise ContractError("Vocello owned-component version drifts from project.yml")
        license_path = rule.get("licensePath")
        license_bytes = read_bytes(root, license_path)
        notice = None
        if rule.get("noticePath"):
            notice = read_bytes(root, rule["noticePath"]).decode("utf-8")
        origins = None
        if rule.get("originsPath"):
            origins = read_bytes(root, rule["originsPath"]).decode("utf-8")
        components.append({
            "id": identity,
            "displayName": rule.get("displayName"),
            "version": rule.get("version"),
            "revision": None,
            "sourceURL": https_url(rule.get("sourceURL"), f"owned component {identity} sourceURL"),
            "licenseID": rule.get("licenseID"),
            "upstreamLicenseSHA256": digest(license_bytes),
            "copyrightNotice": rule.get("copyrightNotice"),
            "notice": notice,
            "origins": origins,
            "scope": "owned",
            "licenseTextOverride": license_bytes.decode("utf-8"),
        })

    catalog_bytes = read_bytes(root, CATALOG)
    catalog = json.loads(catalog_bytes)
    artifacts = catalog.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ContractError("production model catalog has no artifacts")
    model_policy = unique_map(policy.get("modelCards"), "repo", "model-card policy")
    catalog_repos = {row.get("repo") for row in artifacts if isinstance(row, dict)}
    if set(model_policy) != catalog_repos:
        raise ContractError("model-card policy does not exactly cover the production catalog")
    models: list[dict] = []
    for artifact in sorted(artifacts, key=lambda row: (row["modelID"], row["variantID"])):
        rule = model_policy[artifact["repo"]]
        readmes = [row for row in artifact.get("files", []) if row.get("relativePath") == "README.md"]
        if len(readmes) != 1:
            raise ContractError(f"model {artifact['repo']} must have exactly one README.md receipt")
        if rule.get("licenseID") not in licenses:
            raise ContractError(f"model {artifact['repo']} has unsupported license")
        models.append({
            "id": f"{artifact['modelID']}-{artifact['variantID']}",
            "displayName": artifact["folder"],
            "modelID": artifact["modelID"],
            "variantID": artifact["variantID"],
            "repo": artifact["repo"],
            "revision": artifact["revision"],
            "modelCardSHA256": readmes[0]["sha256"],
            "licenseID": rule["licenseID"],
            "baseRepo": rule.get("baseRepo"),
            "baseRevision": rule.get("baseRevision"),
            "redistributionDecision": rule.get("redistributionDecision"),
            "sourceURL": f"https://huggingface.co/{artifact['repo']}/tree/{artifact['revision']}",
        })

    rights = policy.get("contentRights")
    unique_map(rights, "id", "content-rights records")
    for row in rights:
        if row.get("status") not in {
            "source-proven-not-redistributed",
            "pending-qualified-review",
            "pending-account-and-qualified-review",
            "pending-qualified-review-account-declaration-verified",
        }:
            raise ContractError(f"invalid content-rights status for {row.get('id')}")

    return {
        "schemaVersion": 1,
        "generatedFrom": {
            "applicationPackageResolutionSHA256": digest(resolved_bytes),
            "ownedRuntimePackageResolutionSHA256": digest(owned_bytes),
            "productionModelCatalogSHA256": digest(catalog_bytes),
            "policySHA256": digest(policy_bytes),
        },
        "summary": {
            "componentCount": len(components),
            "modelArtifactCount": len(models),
            "pendingContentRightsCount": sum(1 for row in rights if row["status"].startswith("pending")),
        },
        "licenses": [licenses[key] for key in sorted(licenses)],
        "components": sorted(components, key=lambda row: row["displayName"].lower()),
        "modelArtifacts": models,
        "contentRights": rights,
    }


def encoded(value: dict) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("rebuild", "validate"))
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        expected = encoded(build(root))
        output = root / OUTPUT
        if args.command == "validate" or args.check:
            actual = output.read_bytes()
            if actual != expected:
                raise ContractError(f"{OUTPUT} is stale; run scripts/attribution_manifest.py rebuild")
        else:
            output.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as temporary:
                temporary.write(expected)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            os.replace(temporary_path, output)
    except (ContractError, OSError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"Attribution manifest {args.command}: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
