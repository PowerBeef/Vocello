#!/usr/bin/env python3
"""Validate the iOS backup and file-protection contract against product source."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
POLICY = ROOT / "config/ios-storage-protection-policy.json"
SOURCE = ROOT / "Sources/iOSSupport/Services/IOSStorageProtectionPolicy.swift"
BOOTSTRAP = ROOT / "Sources/iOS/IOSAppBootstrap.swift"
PROJECT = ROOT / "project.yml"

EXPECTED_IDS = {
    "application-support-root",
    "models",
    "downloads",
    "cache",
    "diagnostics",
    "outputs",
    "voices",
    "voice-candidates",
    "voice-transactions",
    "history-outbox",
    "history",
}
EXCLUDED_IDS = {
    "models", "downloads", "cache", "diagnostics", "voice-candidates", "voice-transactions"
}
INCLUDED_IDS = {"outputs", "voices", "history-outbox", "history"}


class PolicyError(ValueError):
    pass


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PolicyError(f"cannot read policy: {path.name}") from error


def validate(root: Path = ROOT) -> dict[str, object]:
    payload = _read_json(root / POLICY.relative_to(ROOT))
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
        raise PolicyError("policy schemaVersion must be 1")
    if payload.get("platform") != "iOS":
        raise PolicyError("policy platform must be iOS")
    if payload.get("defaultProtection") != "completeUntilFirstUserAuthentication":
        raise PolicyError("unsupported default protection class")

    rows = payload.get("paths")
    if not isinstance(rows, list) or not rows:
        raise PolicyError("policy paths must be a non-empty array")
    if any(not isinstance(row, dict) for row in rows):
        raise PolicyError("every path policy must be an object")
    ids = [row.get("id") for row in rows]
    if len(ids) != len(set(ids)):
        raise PolicyError("path policy identifiers must be unique")
    if set(ids) != EXPECTED_IDS:
        raise PolicyError("path policy must cover every governed iOS data class")

    paths: set[str] = set()
    for row in rows:
        identifier = row.get("id")
        relative = row.get("relativePath")
        if not isinstance(relative, str) or not relative or relative.startswith("/") or ".." in relative.split("/"):
            raise PolicyError(f"{identifier}: relativePath must stay beneath the app-support root")
        if relative in paths:
            raise PolicyError(f"duplicate relativePath: {relative}")
        paths.add(relative)
        if row.get("protection") != payload["defaultProtection"]:
            raise PolicyError(f"{identifier}: protection must match the governed default")
        if row.get("backup") not in {"inherited", "included", "excluded"}:
            raise PolicyError(f"{identifier}: invalid backup disposition")
        if not isinstance(row.get("purpose"), str) or not row["purpose"].strip():
            raise PolicyError(f"{identifier}: purpose is required")
        if row.get("kind") not in {"directory", "file-family"}:
            raise PolicyError(f"{identifier}: invalid kind")
        if not isinstance(row.get("recursive"), bool):
            raise PolicyError(f"{identifier}: recursive must be boolean")

    by_id = {row["id"]: row for row in rows}
    if any(by_id[identifier]["backup"] != "excluded" for identifier in EXCLUDED_IDS):
        raise PolicyError("regenerable model/download/cache/diagnostic data must be backup-excluded")
    if any(by_id[identifier]["backup"] != "included" for identifier in INCLUDED_IDS):
        raise PolicyError("History, its outbox, outputs, and saved voices must remain backup-eligible")
    if by_id["history"].get("pathPrefix") != "history.sqlite":
        raise PolicyError("History policy must include SQLite sidecars")

    source = (root / SOURCE.relative_to(ROOT)).read_text(encoding="utf-8")
    source_ids = set(re.findall(r'Entry\(id: "([^"]+)"', source))
    if source_ids != EXPECTED_IDS:
        raise PolicyError("Swift policy entries differ from the machine-readable contract")
    if "FileProtectionType.completeUntilFirstUserAuthentication" not in source:
        raise PolicyError("Swift policy does not apply the governed protection class")
    if ".protectionKey: protectionClass" not in source:
        raise PolicyError("Swift policy does not write NSFileProtectionKey")
    if "values.isExcludedFromBackup = entry.backup == .excluded" not in source:
        raise PolicyError("Swift policy does not enforce backup disposition")
    if "withMetadataWriteAccess(at: url" not in source:
        raise PolicyError("Swift policy does not reconcile immutable model-file metadata safely")
    if source.count(".posixPermissions: NSNumber(value: mode") != 2:
        raise PolicyError("Swift policy must open and restore immutable model-file permissions")

    bootstrap = (root / BOOTSTRAP.relative_to(ROOT)).read_text(encoding="utf-8")
    if "try IOSStorageProtectionPolicy.apply(at: AppPaths.appSupportDir)" not in bootstrap:
        raise PolicyError("iOS bootstrap does not apply storage protection before opening stores")
    project = (root / PROJECT.relative_to(ROOT)).read_text(encoding="utf-8")
    if project.count("Sources/iOSSupport/Services/IOSStorageProtectionPolicy.swift") != 2:
        raise PolicyError("storage policy must compile in both host and generic-iOS logic-test targets")

    return {
        "schemaVersion": 1,
        "status": "PASS",
        "pathCount": len(rows),
        "backupExcluded": sorted(EXCLUDED_IDS),
        "backupIncluded": sorted(INCLUDED_IDS),
        "protection": payload["defaultProtection"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate",))
    parser.add_argument("--root", type=Path, default=ROOT)
    arguments = parser.parse_args()
    try:
        result = validate(arguments.root.resolve())
    except (OSError, PolicyError) as error:
        print(f"iOS storage protection policy: FAIL\n{error}")
        return 1
    print(
        "iOS storage protection policy: PASS "
        f"({result['pathCount']} classes; {result['protection']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
