#!/usr/bin/env python3
"""Generate deterministic SPDX and CycloneDX inventories from committed lock files."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote


SWIFT_LOCK = Path("QwenVoice.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved")
NPM_LOCK = Path("website/package-lock.json")


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode("utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _npm_name(path: str, payload: dict[str, Any]) -> str:
    if payload.get("name"):
        return str(payload["name"])
    marker = "node_modules/"
    name = path.rsplit(marker, 1)[-1]
    return name or path


def dependencies(root: Path) -> list[dict[str, Any]]:
    swift_path = root / SWIFT_LOCK
    npm_path = root / NPM_LOCK
    if not swift_path.is_file() or not npm_path.is_file():
        missing = [str(path.relative_to(root)) for path in (swift_path, npm_path) if not path.is_file()]
        raise ValueError(f"missing dependency lock file(s): {', '.join(missing)}")

    result: list[dict[str, Any]] = []
    swift = json.loads(swift_path.read_text(encoding="utf-8"))
    for pin in swift.get("pins", []):
        state = pin.get("state", {})
        name = str(pin.get("identity", "")).strip()
        revision = str(state.get("revision", "")).strip()
        version = str(state.get("version") or state.get("branch") or revision).strip()
        if not name or not version:
            raise ValueError("Swift Package.resolved contains an incomplete pin")
        result.append({
            "ecosystem": "swift",
            "name": name,
            "version": version,
            "revision": revision,
            "source": str(pin.get("location", "NOASSERTION")),
            "license": "NOASSERTION",
            "purl": f"pkg:swift/{quote(name)}@{quote(version)}",
        })

    npm = json.loads(npm_path.read_text(encoding="utf-8"))
    for package_path, payload in npm.get("packages", {}).items():
        if not package_path or not package_path.startswith("node_modules/"):
            continue
        name = _npm_name(package_path, payload)
        version = str(payload.get("version", "")).strip()
        if not name or not version:
            raise ValueError(f"npm lock entry is incomplete: {package_path}")
        result.append({
            "ecosystem": "npm",
            "name": name,
            "version": version,
            "revision": "",
            "source": str(payload.get("resolved", "NOASSERTION")),
            "integrity": str(payload.get("integrity", "")),
            "license": str(payload.get("license", "NOASSERTION")),
            "purl": f"pkg:npm/{quote(name, safe='@/')}@{quote(version)}",
        })

    unique: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in result:
        unique[(item["ecosystem"], item["name"], item["version"])] = item
    return [unique[key] for key in sorted(unique)]


def _hashes(item: dict[str, Any]) -> list[dict[str, str]]:
    if item["ecosystem"] == "swift" and re.fullmatch(r"[0-9a-fA-F]{40}", item.get("revision", "")):
        return [{"alg": "SHA-1", "content": item["revision"].lower()}]
    integrity = item.get("integrity", "")
    if integrity.startswith("sha512-"):
        try:
            raw = base64.b64decode(integrity.split("-", 1)[1], validate=True)
        except (ValueError, base64.binascii.Error):
            return []
        if len(raw) != 64:
            return []
        decoded = raw.hex()
        return [{"alg": "SHA-512", "content": decoded}]
    return []


def render(root: Path, commit: str, source_date_epoch: int) -> tuple[dict[str, Any], dict[str, Any]]:
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("commit must be a lowercase 40-character Git SHA")
    deps = dependencies(root)
    created = datetime.fromtimestamp(source_date_epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    identity = hashlib.sha256(canonical_bytes(deps)).hexdigest()

    spdx_packages = []
    relationships = []
    components = []
    for item in deps:
        suffix = hashlib.sha256(f"{item['ecosystem']}:{item['name']}:{item['version']}".encode()).hexdigest()[:16]
        spdx_id = f"SPDXRef-Package-{suffix}"
        checksums = [
            {"algorithm": value["alg"].replace("-", ""), "checksumValue": value["content"]}
            for value in _hashes(item)
        ]
        package = {
            "SPDXID": spdx_id,
            "name": item["name"],
            "versionInfo": item["version"],
            "downloadLocation": item["source"],
            "filesAnalyzed": False,
            "licenseConcluded": "NOASSERTION",
            "licenseDeclared": item["license"],
            "externalRefs": [{
                "referenceCategory": "PACKAGE-MANAGER",
                "referenceType": "purl",
                "referenceLocator": item["purl"],
            }],
        }
        if checksums:
            package["checksums"] = checksums
        spdx_packages.append(package)
        relationships.append({
            "spdxElementId": "SPDXRef-DOCUMENT",
            "relationshipType": "DESCRIBES",
            "relatedSpdxElement": spdx_id,
        })
        component: dict[str, Any] = {
            "type": "library",
            "bom-ref": item["purl"],
            "name": item["name"],
            "version": item["version"],
            "purl": item["purl"],
            "properties": [{"name": "vocello:ecosystem", "value": item["ecosystem"]}],
        }
        if item["license"] != "NOASSERTION":
            component["licenses"] = [{"expression": item["license"]}]
        hashes = _hashes(item)
        if hashes:
            component["hashes"] = hashes
        components.append(component)

    spdx = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"Vocello-{commit[:12]}",
        "documentNamespace": f"https://github.com/PowerBeef/Vocello/sbom/{commit}/{identity}",
        "creationInfo": {"created": created, "creators": ["Tool: Vocello-release-sbom/1"]},
        "packages": spdx_packages,
        "relationships": relationships,
    }
    cdx = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, identity)}",
        "version": 1,
        "metadata": {
            "timestamp": created,
            "tools": {"components": [{"type": "application", "name": "Vocello release SBOM", "version": "1"}]},
            "component": {"type": "application", "name": "Vocello", "version": commit[:12]},
        },
        "components": components,
    }
    return spdx, cdx


def generate(root: Path, output_dir: Path, commit: str, source_date_epoch: int, prefix: str) -> tuple[Path, Path]:
    spdx, cdx = render(root, commit, source_date_epoch)
    output_dir.mkdir(parents=True, exist_ok=True)
    spdx_path = output_dir / f"{prefix}.spdx.json"
    cdx_path = output_dir / f"{prefix}.cdx.json"
    spdx_path.write_bytes(canonical_bytes(spdx))
    cdx_path.write_bytes(canonical_bytes(cdx))
    return spdx_path, cdx_path


def _git_value(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--commit")
    parser.add_argument("--source-date-epoch", type=int)
    parser.add_argument("--prefix", default="vocello")
    args = parser.parse_args()
    root = args.root.resolve()
    commit = args.commit or _git_value(root, "rev-parse", "HEAD")
    epoch = args.source_date_epoch or int(_git_value(root, "show", "-s", "--format=%ct", commit))
    paths = generate(root, args.output_dir.resolve(), commit, epoch, args.prefix)
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
