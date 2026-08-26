#!/usr/bin/env python3
"""Validate exact Swift pins and render a read-only release/advisory proposal."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_POLICY = Path("config/swift-dependency-update-policy.json")
SEMVER = re.compile(r"^v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:[-+].*)?$")
SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")
SAFE_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class PolicyError(ValueError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode("utf-8")


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PolicyError(f"{path}: {error}") from error
    if not isinstance(value, dict):
        raise PolicyError(f"{path}: expected a JSON object")
    return value


def _repo_from_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname != "github.com":
        raise PolicyError(f"unsupported Swift package repository URL: {value!r}")
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.port:
        raise PolicyError(f"private or ambiguous Swift package repository URL: {value!r}")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2:
        raise PolicyError(f"unsupported Swift package repository path: {value!r}")
    parts[-1] = parts[-1].removesuffix(".git")
    repository = "/".join(parts)
    if not SAFE_REPOSITORY.fullmatch(repository):
        raise PolicyError(f"invalid Swift package repository: {repository!r}")
    return repository.casefold()


def _project_versions(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    in_packages = False
    current_url: str | None = None
    result: dict[str, str] = {}
    for line in lines:
        if not in_packages:
            if line == "packages:":
                in_packages = True
            continue
        if line and not line[0].isspace() and not line.lstrip().startswith("#"):
            break
        url_match = re.match(r"^\s+url:\s*([^#]+?)\s*$", line)
        if url_match:
            current_url = url_match.group(1).strip().strip("'\"")
            continue
        version_match = re.match(r"^\s+exactVersion:\s*([^#]+?)\s*$", line)
        if version_match and current_url:
            repository = _repo_from_url(current_url)
            version = version_match.group(1).strip().strip("'\"")
            if repository in result:
                raise PolicyError(f"{path}: duplicate exact package declaration for {repository}")
            result[repository] = version
            current_url = None
    return result


def _package_swift_versions(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    result: dict[str, str] = {}
    pattern = re.compile(
        r"\.package\s*\(\s*url\s*:\s*\"([^\"]+)\"\s*,\s*exact\s*:\s*\"([^\"]+)\"\s*\)",
        re.DOTALL,
    )
    for url, version in pattern.findall(text):
        repository = _repo_from_url(url)
        if repository in result:
            raise PolicyError(f"{path}: duplicate exact package declaration for {repository}")
        result[repository] = version
    return result


def _lock_versions(path: Path) -> dict[str, str]:
    lock = _read_object(path)
    pins = lock.get("pins")
    if lock.get("version") not in (2, 3) or not isinstance(pins, list):
        raise PolicyError(f"{path}: unsupported Package.resolved schema")
    result: dict[str, str] = {}
    for pin in pins:
        if not isinstance(pin, dict) or not isinstance(pin.get("identity"), str):
            raise PolicyError(f"{path}: invalid package pin")
        identity = pin["identity"]
        state = pin.get("state")
        if not isinstance(state, dict) or not isinstance(state.get("version"), str):
            raise PolicyError(f"{path}: {identity} is not an exact version pin")
        if identity in result:
            raise PolicyError(f"{path}: duplicate package pin: {identity}")
        result[identity] = state["version"]
    return result


def _compatibility_versions(path: Path) -> dict[str, str]:
    value = _read_object(path)
    package = value.get("package")
    dependencies = package.get("directDependencies") if isinstance(package, dict) else None
    if not isinstance(dependencies, dict) or not all(
        isinstance(key, str) and isinstance(version, str) for key, version in dependencies.items()
    ):
        raise PolicyError(f"{path}: missing package.directDependencies")
    return dependencies


def _paths(value: Any, *, field: str, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise PolicyError(f"{field} must be a {'possibly empty ' if allow_empty else 'non-empty '}list")
    result: list[str] = []
    for raw in value:
        if not isinstance(raw, str) or not raw or raw.startswith("/") or ".." in Path(raw).parts:
            raise PolicyError(f"{field} contains an unsafe repository path")
        result.append(raw)
    if len(result) != len(set(result)):
        raise PolicyError(f"{field} contains duplicates")
    return result


def load_policy(root: Path, policy_path: Path = DEFAULT_POLICY) -> tuple[dict[str, Any], bytes]:
    absolute = policy_path if policy_path.is_absolute() else root / policy_path
    raw = absolute.read_bytes()
    policy = _read_object(absolute)
    if policy.get("schemaVersion") != 1:
        raise PolicyError("swift dependency update policy has an unsupported schemaVersion")
    if policy.get("workflow") != ".github/workflows/swift-dependency-watch.yml":
        raise PolicyError("swift dependency update policy has an unexpected workflow")
    governance = _paths(policy.get("governanceSurfaces"), field="governanceSurfaces")
    packages = policy.get("packages")
    if not isinstance(packages, list) or not packages:
        raise PolicyError("swift dependency update policy packages must be non-empty")
    identities: set[str] = set()
    repositories: set[str] = set()
    for index, package in enumerate(packages):
        if not isinstance(package, dict):
            raise PolicyError(f"packages[{index}] must be an object")
        identity = package.get("identity")
        repository = package.get("repository")
        group = package.get("group")
        if not isinstance(identity, str) or not SAFE_ID.fullmatch(identity):
            raise PolicyError(f"packages[{index}].identity is invalid")
        if not isinstance(repository, str) or not SAFE_REPOSITORY.fullmatch(repository):
            raise PolicyError(f"packages[{index}].repository is invalid")
        if not isinstance(group, str) or not SAFE_ID.fullmatch(group):
            raise PolicyError(f"packages[{index}].group is invalid")
        if identity in identities or repository.casefold() in repositories:
            raise PolicyError("swift dependency update policy has duplicate package identity or repository")
        identities.add(identity)
        repositories.add(repository.casefold())
        for field in ("declarations", "locks", "requiredEvidence"):
            _paths(package.get(field), field=f"packages[{index}].{field}")
        _paths(package.get("compatibility"), field=f"packages[{index}].compatibility", allow_empty=True)
    for path in [policy["workflow"], *governance]:
        if not (root / path).is_file():
            raise PolicyError(f"policy surface is missing: {path}")
    return policy, raw


def validate_pins(root: Path, policy: dict[str, Any]) -> dict[str, str]:
    declaration_cache: dict[str, dict[str, str]] = {}
    lock_cache: dict[str, dict[str, str]] = {}
    compatibility_cache: dict[str, dict[str, str]] = {}
    current: dict[str, str] = {}
    for package in policy["packages"]:
        identity = package["identity"]
        repository = package["repository"].casefold()
        observed: list[tuple[str, str]] = []
        for relative in package["declarations"]:
            path = root / relative
            if not path.is_file():
                raise PolicyError(f"declared dependency surface is missing: {relative}")
            if relative not in declaration_cache:
                declaration_cache[relative] = (
                    _project_versions(path) if path.name == "project.yml" else _package_swift_versions(path)
                )
            version = declaration_cache[relative].get(repository)
            if not version:
                raise PolicyError(f"{relative}: missing exact declaration for {package['repository']}")
            observed.append((relative, version))
        for relative in package["locks"]:
            path = root / relative
            if not path.is_file():
                raise PolicyError(f"dependency lock is missing: {relative}")
            if relative not in lock_cache:
                lock_cache[relative] = _lock_versions(path)
            version = lock_cache[relative].get(identity)
            if not version:
                raise PolicyError(f"{relative}: missing pin for {identity}")
            observed.append((relative, version))
        for relative in package["compatibility"]:
            path = root / relative
            if relative not in compatibility_cache:
                compatibility_cache[relative] = _compatibility_versions(path)
            version = compatibility_cache[relative].get(identity)
            if not version:
                raise PolicyError(f"{relative}: missing compatibility pin for {identity}")
            observed.append((relative, version))
        versions = {version for _, version in observed}
        if len(versions) != 1:
            details = ", ".join(f"{path}={version}" for path, version in observed)
            raise PolicyError(f"{identity}: exact pins disagree: {details}")
        version = versions.pop()
        if not SEMVER.fullmatch(version):
            raise PolicyError(f"{identity}: current pin is not a semantic version: {version}")
        current[identity] = version
    return current


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = SEMVER.fullmatch(value)
    if not match:
        raise PolicyError(f"invalid semantic version tag: {value!r}")
    return tuple(int(match.group(index)) for index in range(1, 4))  # type: ignore[return-value]


def _stable_versions(rows: Any) -> list[str]:
    if not isinstance(rows, list):
        raise PolicyError("release feed entry must be a list")
    versions: set[str] = set()
    for row in rows:
        if isinstance(row, str):
            tag, draft, prerelease = row, False, False
        elif isinstance(row, dict):
            tag = row.get("tag_name") or row.get("name")
            draft = row.get("draft", False)
            prerelease = row.get("prerelease", False)
        else:
            raise PolicyError("release feed row must be a string or object")
        if not isinstance(tag, str) or not isinstance(draft, bool) or not isinstance(prerelease, bool):
            raise PolicyError("release feed row has invalid fields")
        if draft or prerelease or "-" in tag.removeprefix("v"):
            continue
        if SEMVER.fullmatch(tag):
            versions.add(tag.removeprefix("v"))
    return sorted(versions, key=_version_tuple)


def _advisories(rows: Any, identities: set[str]) -> dict[str, list[dict[str, str]]]:
    if not isinstance(rows, list):
        raise PolicyError("advisory feed must be a list")
    result: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if not isinstance(row, dict) or row.get("state", "open") != "open":
            continue
        dependency = row.get("dependency")
        package = dependency.get("package") if isinstance(dependency, dict) else None
        name = package.get("name") if isinstance(package, dict) else None
        advisory = row.get("security_advisory")
        ghsa = advisory.get("ghsa_id") if isinstance(advisory, dict) else None
        severity = advisory.get("severity") if isinstance(advisory, dict) else None
        if not isinstance(name, str) or name not in identities:
            continue
        if not isinstance(ghsa, str) or not re.fullmatch(r"GHSA-[A-Za-z0-9-]+", ghsa):
            raise PolicyError(f"advisory for {name} has an invalid GHSA identifier")
        if severity not in {"low", "moderate", "high", "critical"}:
            raise PolicyError(f"advisory for {name} has an invalid severity")
        result[name].append({"id": ghsa, "severity": severity})
    for rows_for_package in result.values():
        rows_for_package.sort(key=lambda row: (row["severity"], row["id"]))
    return result


def build_report(
    policy: dict[str, Any],
    policy_raw: bytes,
    current: dict[str, str],
    release_feed: dict[str, Any],
    advisory_feed: list[Any],
    *,
    generated_at: str,
) -> dict[str, Any]:
    try:
        parsed_time = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise PolicyError("generated-at must be an RFC 3339 timestamp") from error
    if parsed_time.tzinfo is None:
        raise PolicyError("generated-at must include a timezone")
    timestamp = parsed_time.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    advisories = _advisories(advisory_feed, set(current))
    package_rows: list[dict[str, Any]] = []
    group_candidates: dict[str, bool] = defaultdict(bool)
    for package in policy["packages"]:
        repository = package["repository"]
        if repository not in release_feed:
            raise PolicyError(f"release feed is missing repository: {repository}")
        stable = _stable_versions(release_feed[repository])
        latest = stable[-1] if stable else None
        installed = current[package["identity"]]
        update = latest is not None and _version_tuple(latest) > _version_tuple(installed)
        alerts = advisories.get(package["identity"], [])
        group_candidates[package["group"]] = group_candidates[package["group"]] or update or bool(alerts)
        package_rows.append({
            "identity": package["identity"],
            "repository": repository,
            "group": package["group"],
            "currentVersion": installed,
            "latestStableVersion": latest,
            "releaseStatus": "update-available" if update else ("current" if latest else "no-stable-release"),
            "advisories": alerts,
        })
    proposals: list[dict[str, Any]] = []
    for group in sorted(group_candidates):
        if not group_candidates[group]:
            continue
        members = [package for package in policy["packages"] if package["group"] == group]
        proposals.append({
            "group": group,
            "members": [package["identity"] for package in members],
            "reviewSurfaces": sorted({
                *policy["governanceSurfaces"],
                *(path for package in members for field in ("declarations", "locks", "compatibility") for path in package[field]),
            }),
            "requiredEvidence": sorted({item for package in members for item in package["requiredEvidence"]}),
            "compatibilityDecision": "maintainer-review-required",
        })
    return {
        "schemaVersion": 1,
        "generatedAt": timestamp,
        "policySHA256": hashlib.sha256(policy_raw).hexdigest(),
        "readOnly": True,
        "compatibilityInferred": False,
        "packages": package_rows,
        "proposals": proposals,
        "summary": {
            "packageCount": len(package_rows),
            "updateCount": sum(row["releaseStatus"] == "update-available" for row in package_rows),
            "advisoryCount": sum(len(row["advisories"]) for row in package_rows),
            "proposalCount": len(proposals),
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Swift dependency watch",
        "",
        f"Generated: `{report['generatedAt']}`",
        "",
        "> Read-only signal. Availability and advisories do not prove Vocello compatibility and do not change pins.",
        "",
        "| Package | Pinned | Latest stable | Release | Open advisories |",
        "| --- | ---: | ---: | --- | ---: |",
    ]
    for row in report["packages"]:
        lines.append(
            f"| `{row['identity']}` | `{row['currentVersion']}` | "
            f"`{row['latestStableVersion'] or 'unknown'}` | {row['releaseStatus']} | {len(row['advisories'])} |"
        )
    if report["proposals"]:
        lines.extend(["", "## Coordinated review proposals", ""])
        for proposal in report["proposals"]:
            lines.extend([
                f"### `{proposal['group']}`",
                "",
                f"Members: {', '.join(f'`{item}`' for item in proposal['members'])}",
                "",
                "Decision: maintainer review required; this report does not infer compatibility.",
                "",
                "Review together:",
                "",
                *(f"- `{path}`" for path in proposal["reviewSurfaces"]),
                "",
                "Required evidence before retaining any pin change:",
                "",
                *(f"- `{command}`" for command in proposal["requiredEvidence"]),
                "",
            ])
    else:
        lines.extend(["", "No coordinated review is currently proposed.", ""])
    return "\n".join(lines).rstrip() + "\n"


def _github_json(path: str, token: str) -> Any:
    if not path.startswith("/") or ".." in path:
        raise PolicyError("unsafe GitHub API path")
    request = urllib.request.Request(
        "https://api.github.com" + path,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2026-03-10",
            "User-Agent": "vocello-swift-dependency-watch-v1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except (urllib.error.URLError, json.JSONDecodeError) as error:
        raise PolicyError(f"GitHub API request failed for {path}: {error}") from error


def _online_feeds(policy: dict[str, Any], repository: str, token: str) -> tuple[dict[str, Any], list[Any]]:
    if not SAFE_REPOSITORY.fullmatch(repository):
        raise PolicyError("repository must be an owner/name GitHub repository")
    releases = {
        package["repository"]: _github_json(
            f"/repos/{package['repository']}/releases?per_page=100", token
        )
        for package in policy["packages"]
    }
    advisories = _github_json(f"/repos/{repository}/dependabot/alerts?state=open&per_page=100", token)
    return releases, advisories


def _write(path: Path | None, content: bytes) -> None:
    if path is None:
        sys.stdout.buffer.write(content)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate")
    report_parser = subparsers.add_parser("report")
    report_parser.add_argument("--repository")
    report_parser.add_argument("--github-token-env", default="GITHUB_TOKEN")
    report_parser.add_argument("--release-feed", type=Path)
    report_parser.add_argument("--advisory-feed", type=Path)
    report_parser.add_argument("--generated-at", required=True)
    report_parser.add_argument("--json-out", type=Path)
    report_parser.add_argument("--markdown-out", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        policy, policy_raw = load_policy(root, args.policy)
        current = validate_pins(root, policy)
        if args.command == "validate":
            print(f"Swift dependency update policy: PASS ({len(current)} exact pins)")
            return 0
        offline = args.release_feed is not None or args.advisory_feed is not None
        if offline:
            if args.release_feed is None or args.advisory_feed is None:
                raise PolicyError("offline report requires both --release-feed and --advisory-feed")
            release_feed = _read_object(args.release_feed)
            advisory_value = json.loads(args.advisory_feed.read_text(encoding="utf-8"))
            if not isinstance(advisory_value, list):
                raise PolicyError("advisory feed must be a JSON array")
        else:
            token = os.environ.get(args.github_token_env, "")
            if not token or not args.repository:
                raise PolicyError("online report requires --repository and the configured GitHub token")
            release_feed, advisory_value = _online_feeds(policy, args.repository, token)
        report = build_report(
            policy,
            policy_raw,
            current,
            release_feed,
            advisory_value,
            generated_at=args.generated_at,
        )
        _write(args.json_out, canonical_bytes(report))
        if args.markdown_out:
            _write(args.markdown_out, render_markdown(report).encode("utf-8"))
        return 0
    except (OSError, json.JSONDecodeError, PolicyError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
