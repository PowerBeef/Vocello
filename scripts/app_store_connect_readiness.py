#!/usr/bin/env python3
"""Create a privacy-safe, read-only App Store Connect readiness inventory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import app_store_build_preflight  # noqa: E402
import asc_readonly  # noqa: E402


ROOT = SCRIPTS.parent


class ReadinessError(ValueError):
    pass


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReadinessError(f"cannot read {path.name}: {error}") from error
    if not isinstance(value, dict):
        raise ReadinessError(f"{path.name} must contain an object")
    return value


def validate_policy(root: Path = ROOT) -> dict[str, Any]:
    policy = _load(root / "config/app-store-connect-readiness-policy.json")
    if policy.get("schemaVersion") != 1 or policy.get("platform") != "IOS":
        raise ReadinessError("readiness policy must be schema v1 for IOS")
    reads = policy.get("reads")
    forbidden = policy.get("forbiddenCommandTokens")
    if not isinstance(reads, list) or not reads or not isinstance(forbidden, list):
        raise ReadinessError("readiness policy reads and forbidden tokens are required")
    seen: set[str] = set()
    for row in reads:
        if not isinstance(row, dict):
            raise ReadinessError("readiness read must be an object")
        identifier = row.get("id")
        arguments = row.get("arguments")
        if not isinstance(identifier, str) or identifier in seen or not re.fullmatch(r"[a-z0-9-]+", identifier):
            raise ReadinessError("readiness read IDs must be unique stable tokens")
        seen.add(identifier)
        if not isinstance(arguments, list) or not arguments or any(not isinstance(item, str) for item in arguments):
            raise ReadinessError(f"{identifier}: arguments must be strings")
        if any(token in forbidden for token in arguments):
            raise ReadinessError(f"{identifier}: mutation-capable token is forbidden")
        if "--output" not in arguments or "json" not in arguments:
            raise ReadinessError(f"{identifier}: explicit JSON output is required")
        if arguments[:2] in (["versions", "list"], ["apps", "list"]) and "--paginate" not in arguments:
            raise ReadinessError(f"{identifier}: list reads require complete pagination")
        placeholders = set(re.findall(r"\{([A-Za-z]+)\}", " ".join(arguments)))
        if not placeholders <= {"appID", "marketingVersion"}:
            raise ReadinessError(f"{identifier}: unsupported placeholder")
        if not isinstance(row.get("required"), bool):
            raise ReadinessError(f"{identifier}: required must be boolean")
    owner_checks = policy.get("webOrOwnerOnlyChecks")
    if not isinstance(owner_checks, list) or not owner_checks:
        raise ReadinessError("webOrOwnerOnlyChecks must remain explicit")
    return policy


def _default_runner(arguments: Sequence[str], profile: str, timeout: int) -> dict[str, Any]:
    try:
        return asc_readonly.run_json(arguments, profile, timeout)
    except asc_readonly.ASCReadError as error:
        raise ReadinessError(str(error)) from error


def _rows(value: dict[str, Any]) -> list[dict[str, Any]]:
    data = value.get("data")
    if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
        raise ReadinessError("app lookup did not return a paginated document")
    return data


def _tokens(value: Any) -> list[str]:
    safe_keys = {
        "status": "status",
        "state": "state",
        "platform": "platform",
        "appStoreState": "appStoreState",
        "app_store_state": "appStoreState",
        "processingState": "processingState",
        "processing_state": "processingState",
        "submissionState": "submissionState",
        "submission_state": "submissionState",
        "reviewState": "reviewState",
        "review_state": "reviewState",
        "contentRightsDeclaration": "contentRightsDeclaration",
        "content_rights_declaration": "contentRightsDeclaration",
        "severity": "severity",
        "result": "result",
        "category": "category",
        "code": "code",
    }
    found: list[str] = []

    def walk(node: Any, key: str = "") -> None:
        if isinstance(node, dict):
            for child_key, child in node.items():
                walk(child, child_key)
        elif isinstance(node, list):
            for child in node:
                walk(child, key)
        elif key in safe_keys and isinstance(node, (str, bool, int)):
            text = str(node)
            if len(text) <= 80 and re.fullmatch(r"[A-Za-z0-9_.:-]+", text):
                found.append(f"{safe_keys[key]}={text}")

    walk(value)
    return sorted(set(found))


def _resource_counts(value: Any) -> dict[str, int]:
    types: Counter[str] = Counter()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            resource_type = node.get("type")
            if isinstance(resource_type, str) and re.fullmatch(r"[A-Za-z0-9_-]+", resource_type):
                types[resource_type] += 1
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return dict(sorted(types.items()))


def _summary(identifier: str, payload: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    data = payload.get("data")
    return {
        "id": identifier,
        "status": "READ",
        "responseSHA256": hashlib.sha256(encoded).hexdigest(),
        "topLevelDataCount": len(data) if isinstance(data, list) else None,
        "resourceTypeCounts": _resource_counts(payload),
        "safeStateTokens": _tokens(payload),
    }


def inventory(
    *,
    root: Path = ROOT,
    profile: str | None = None,
    runner: Callable[[Sequence[str], str, int], dict[str, Any]] = _default_runner,
) -> dict[str, Any]:
    policy = validate_policy(root)
    identity = app_store_build_preflight.project_identity(root)
    selected_profile = profile or policy["profile"]
    lookup = runner(
        ["apps", "list", "--bundle-id", identity["bundleIdentifier"], "--paginate", "--output", "json"],
        selected_profile,
        policy["timeoutSeconds"],
    )
    exact = [
        row for row in _rows(lookup)
        if isinstance(row.get("attributes"), dict)
        and row["attributes"].get("bundleId") == identity["bundleIdentifier"]
        and isinstance(row.get("id"), str)
        and row["id"]
    ]
    if len(exact) != 1:
        raise ReadinessError("bundle identifier must resolve to exactly one app")
    substitutions = {"appID": exact[0]["id"], "marketingVersion": identity["marketingVersion"]}
    reads = [_summary("app-lookup", lookup)]
    required_failures = 0
    for specification in policy["reads"]:
        arguments = [item.format(**substitutions) for item in specification["arguments"]]
        try:
            reads.append(_summary(specification["id"], runner(arguments, selected_profile, policy["timeoutSeconds"])))
        except ReadinessError as error:
            if specification["required"]:
                required_failures += 1
            reads.append(
                {
                    "id": specification["id"],
                    "status": "UNAVAILABLE",
                    "required": specification["required"],
                    "reason": str(error),
                }
            )
    return {
        "schemaVersion": 1,
        "status": "PASS" if required_failures == 0 else "INCOMPLETE",
        "checkedAtUTC": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "platform": "IOS",
        "appIdentityDigest": hashlib.sha256(identity["bundleIdentifier"].encode()).hexdigest(),
        "marketingVersion": identity["marketingVersion"],
        "buildNumber": identity["buildNumber"],
        "readOnly": True,
        "mutationPerformed": False,
        "requiredReadFailures": required_failures,
        "reads": reads,
        "externalChecks": [
            {"id": item, "status": "PENDING_OWNER_OR_WEB_REVIEW"}
            for item in policy["webOrOwnerOnlyChecks"]
        ],
    }


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, indent=2, sort_keys=True).encode() + b"\n"
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "inventory"))
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--profile")
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    try:
        if arguments.command == "validate":
            policy = validate_policy(arguments.root.resolve())
            print(f"App Store Connect readiness contract: PASS ({len(policy['reads'])} read-only checks)")
            return 0
        if not arguments.output:
            raise ReadinessError("inventory requires --output")
        result = inventory(root=arguments.root.resolve(), profile=arguments.profile)
        _atomic_json(arguments.output.resolve(), result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["status"] == "PASS" else 1
    except (OSError, ReadinessError) as error:
        print(f"App Store Connect readiness: FAIL\n{error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
