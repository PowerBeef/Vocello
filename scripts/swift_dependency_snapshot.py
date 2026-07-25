#!/usr/bin/env python3
"""Render a privacy-safe GitHub dependency snapshot from tracked SwiftPM locks."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlsplit


DETECTOR_NAME = "qwenvoice-swift-package-resolved"
DETECTOR_VERSION = "1"
DETECTOR_URL = "https://github.com/PowerBeef/Vocello/blob/main/scripts/swift_dependency_snapshot.py"
JOB_CORRELATOR = "qwenvoice-swift-package-resolved-v1"


@dataclass(frozen=True)
class ManifestSpec:
    correlator: str
    name: str
    lock_path: Path
    declaration_path: Path
    direct_source_loader: Callable[[Path], set[str]]


@dataclass(frozen=True)
class SwiftSource:
    canonical: str
    host: str
    namespace: tuple[str, ...]
    name: str


ROOT_LOCK = Path("QwenVoice.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved")
OWNED_CORE_LOCK = Path("Packages/VocelloQwen3Core/Package.resolved")


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode("utf-8")


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{path}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _swift_source(location: str) -> SwiftSource:
    """Normalize a public HTTPS Swift source without retaining URL secrets."""

    parsed = urlsplit(location)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError(f"Swift package source must be an HTTPS repository URL: {location!r}")
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.port:
        raise ValueError(f"Swift package source contains unsupported private URL components: {location!r}")
    segments = [segment for segment in parsed.path.split("/") if segment]
    if len(segments) < 2:
        raise ValueError(f"Swift package source must contain a namespace and repository: {location!r}")
    if any(segment in (".", "..") or "%" in segment for segment in segments):
        raise ValueError(f"Swift package source contains an ambiguous path: {location!r}")
    name = segments[-1]
    if name.endswith(".git"):
        name = name[:-4]
    if not name:
        raise ValueError(f"Swift package source has an empty repository name: {location!r}")
    namespace = tuple(segments[:-1])
    host = parsed.hostname.lower()
    canonical = "/".join((host, *(segment.casefold() for segment in namespace), name.casefold()))
    return SwiftSource(canonical=canonical, host=host, namespace=namespace, name=name)


def _direct_sources_from_project(path: Path) -> set[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ValueError(f"{path}: {error}") from error
    in_packages = False
    locations: set[str] = set()
    for line in lines:
        if not in_packages:
            if line == "packages:":
                in_packages = True
            continue
        if line and not line[0].isspace() and not line.lstrip().startswith("#"):
            break
        match = re.match(r"^\s+url:\s*(.+?)\s*$", line)
        if not match:
            continue
        value = match.group(1).split(" #", 1)[0].strip().strip("'\"")
        locations.add(_swift_source(value).canonical)
    if not in_packages or not locations:
        raise ValueError(f"{path}: could not derive direct remote Swift packages")
    return locations


def _direct_sources_from_package_swift(path: Path) -> set[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError(f"{path}: {error}") from error
    locations = {
        _swift_source(value).canonical
        for value in re.findall(r"\.package\s*\(\s*url\s*:\s*\"([^\"]+)\"", text, re.DOTALL)
    }
    if not locations:
        raise ValueError(f"{path}: could not derive direct remote Swift packages")
    return locations


MANIFEST_SPECS = (
    ManifestSpec(
        correlator="qwenvoice-root-xcode-workspace-v1",
        name="QwenVoice Xcode workspace SwiftPM resolution",
        lock_path=ROOT_LOCK,
        declaration_path=Path("project.yml"),
        direct_source_loader=_direct_sources_from_project,
    ),
    ManifestSpec(
        correlator="qwenvoice-owned-qwen3-core-v1",
        name="Vocello owned Qwen3 core SwiftPM resolution",
        lock_path=OWNED_CORE_LOCK,
        declaration_path=Path("Packages/VocelloQwen3Core/Package.swift"),
        direct_source_loader=_direct_sources_from_package_swift,
    ),
)


def _purl(source: SwiftSource, version: str) -> str:
    safe = "-._~"
    namespace = "/".join(quote(value, safe=safe) for value in (source.host, *source.namespace))
    return f"pkg:swift/{namespace}/{quote(source.name, safe=safe)}@{quote(version, safe=safe)}"


def _manifest(root: Path, spec: ManifestSpec) -> dict[str, Any]:
    lock_path = root / spec.lock_path
    declaration_path = root / spec.declaration_path
    lock = _read_json_object(lock_path)
    pins = lock.get("pins")
    if lock.get("version") not in (2, 3) or not isinstance(pins, list):
        raise ValueError(f"{spec.lock_path}: unsupported Package.resolved schema")
    direct_sources = spec.direct_source_loader(declaration_path)
    resolved: dict[str, Any] = {}
    for raw_pin in pins:
        if not isinstance(raw_pin, dict):
            raise ValueError(f"{spec.lock_path}: pin must be an object")
        identity = raw_pin.get("identity")
        state = raw_pin.get("state")
        location = raw_pin.get("location")
        if not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9._-]+", identity):
            raise ValueError(f"{spec.lock_path}: invalid package identity")
        if identity in resolved:
            raise ValueError(f"{spec.lock_path}: duplicate package identity: {identity}")
        if raw_pin.get("kind") != "remoteSourceControl" or not isinstance(location, str):
            raise ValueError(f"{spec.lock_path}: {identity} is not a remote source-control pin")
        if not isinstance(state, dict):
            raise ValueError(f"{spec.lock_path}: {identity} has no resolved state")
        revision = state.get("revision")
        if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError(f"{spec.lock_path}: {identity} has an invalid revision")
        version_value = state.get("version") or state.get("branch") or revision
        if not isinstance(version_value, str) or not version_value or any(char.isspace() for char in version_value):
            raise ValueError(f"{spec.lock_path}: {identity} has an invalid version")
        source = _swift_source(location)
        resolved[identity] = {
            "package_url": _purl(source, version_value),
            "relationship": "direct" if source.canonical in direct_sources else "indirect",
            "scope": "runtime",
            "metadata": {"revision": revision},
        }

    origin_hash = lock.get("originHash", "")
    if origin_hash and (not isinstance(origin_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", origin_hash)):
        raise ValueError(f"{spec.lock_path}: invalid originHash")
    metadata: dict[str, Any] = {
        "correlator": spec.correlator,
        "declaration": spec.declaration_path.as_posix(),
        "lockfile_sha256": hashlib.sha256(lock_path.read_bytes()).hexdigest(),
        "lockfile_version": lock["version"],
    }
    if origin_hash:
        metadata["origin_hash"] = origin_hash
    return {
        "name": spec.name,
        "file": {"source_location": spec.lock_path.as_posix()},
        "metadata": metadata,
        "resolved": dict(sorted(resolved.items())),
    }


def _validated_scanned(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("scanned must be an RFC 3339 timestamp") from error
    if parsed.tzinfo is None:
        raise ValueError("scanned must include a timezone")
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_snapshot(
    root: Path,
    *,
    sha: str,
    ref: str,
    job_id: str,
    scanned: str,
    job_url: str | None = None,
) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("sha must be a lowercase 40-character Git commit")
    if not ref.startswith("refs/") or any(char.isspace() for char in ref):
        raise ValueError("ref must be a full Git ref")
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", job_id):
        raise ValueError("job-id must be a privacy-safe external identifier")
    job: dict[str, str] = {"id": job_id, "correlator": JOB_CORRELATOR}
    if job_url:
        parsed = urlsplit(job_url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "github.com"
            or parsed.username
            or parsed.password
            or parsed.port
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("job-url must be an HTTPS github.com URL")
        job["html_url"] = job_url
    manifests = {spec.correlator: _manifest(root, spec) for spec in MANIFEST_SPECS}
    return {
        "version": 0,
        "sha": sha,
        "ref": ref,
        "job": job,
        "detector": {
            "name": DETECTOR_NAME,
            "version": DETECTOR_VERSION,
            "url": DETECTOR_URL,
        },
        "metadata": {"format": "swift-package-resolved-v3", "manifest_count": len(manifests)},
        "scanned": _validated_scanned(scanned),
        "manifests": manifests,
    }


def _git(root: Path, *arguments: str) -> str:
    try:
        return subprocess.check_output(["git", "-C", str(root), *arguments], text=True).strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise ValueError(f"could not resolve Git metadata: {error}") from error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--sha")
    parser.add_argument("--ref")
    parser.add_argument("--job-id")
    parser.add_argument("--job-url")
    parser.add_argument("--scanned")
    args = parser.parse_args()
    root = args.root.resolve()
    sha = args.sha or os.environ.get("GITHUB_SHA") or _git(root, "rev-parse", "HEAD")
    ref = args.ref or os.environ.get("GITHUB_REF") or f"refs/heads/{_git(root, 'branch', '--show-current')}"
    run_id = os.environ.get("GITHUB_RUN_ID")
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    job_id = args.job_id or (f"{run_id}-{attempt}" if run_id else sha)
    scanned = args.scanned or _git(root, "show", "-s", "--format=%cI", sha)
    job_url = args.job_url
    if not job_url and run_id and os.environ.get("GITHUB_REPOSITORY"):
        job_url = f"https://github.com/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{run_id}"
    try:
        snapshot = build_snapshot(
            root,
            sha=sha,
            ref=ref,
            job_id=job_id,
            scanned=scanned,
            job_url=job_url,
        )
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    sys.stdout.buffer.write(canonical_bytes(snapshot))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
