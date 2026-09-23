#!/usr/bin/env python3
"""Supply-chain contract: immutable action pins, Dependabot coverage, pinned tool versions.

Every `uses:` in every workflow must reference a full 40-hex commit SHA that matches
`config/toolchain.json`; Dependabot must watch the three ecosystems the repository
consumes; the website keeps its deterministic npm scripts; and `--installed <group>`
checks that the tools on this host report the pinned version components: `2.46.0` is
exact, while a major-only pin such as the website's Node `24` accepts any 24.x.

`--sync-actions` copies the workflows' action SHAs and their `# vX.Y.Z` comments into
`config/toolchain.json`. A Dependabot action bump changes only the workflows, so the
contract fails on its pull request until the manifest moves in the same PR: run this on
the Dependabot branch and push the result there (pull-request CI has a read-only token
and never writes back).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path


ACTION = re.compile(
    r"^\s*(?:-\s+)?uses:\s*([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(?:/[A-Za-z0-9_./-]+)?@([^\s#]+)",
    re.MULTILINE,
)
# The same references with their trailing version comment (`@<sha> # v7.0.1`).
ACTION_WITH_VERSION = re.compile(ACTION.pattern + r"(?:[ \t]+#[ \t]*(\S+))?", re.MULTILINE)
SYNC_HINT = (
    "run `python3 scripts/supply_chain_contract.py --sync-actions` and commit "
    "config/toolchain.json in the same change"
)


def _tool_output(command: list[str]) -> str:
    try:
        return subprocess.check_output(command, stderr=subprocess.STDOUT, text=True)
    except (OSError, subprocess.CalledProcessError) as error:
        raise ValueError(f"could not execute {' '.join(command)}: {error}") from error


def validate(root: Path, installed: str | None = None) -> list[str]:
    errors: list[str] = []
    manifest_path = root / "config/toolchain.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [f"config/toolchain.json: {error}"]
    if manifest.get("schemaVersion") != 1:
        errors.append("config/toolchain.json: unsupported schemaVersion")

    configured_actions = manifest.get("actions", {})
    workflows_dir = root / ".github/workflows"
    workflows = sorted(workflows_dir.glob("*.yml")) if workflows_dir.is_dir() else []
    used_actions: set[str] = set()
    for workflow in workflows:
        text = workflow.read_text(encoding="utf-8")
        for repository, reference in ACTION.findall(text):
            used_actions.add(repository)
            if not re.fullmatch(r"[0-9a-f]{40}", reference):
                errors.append(
                    f"{workflow.relative_to(root)}: action is not pinned to a full SHA: {repository}@{reference}"
                )
                continue
            configured = configured_actions.get(repository)
            if not configured:
                errors.append(
                    f"{workflow.relative_to(root)}: action is absent from config/toolchain.json: "
                    f"{repository} ({SYNC_HINT})"
                )
            elif configured.get("sha") != reference:
                errors.append(
                    f"{workflow.relative_to(root)}: {repository} SHA differs from config/toolchain.json ({SYNC_HINT})"
                )
    for repository in sorted(set(configured_actions) - used_actions):
        errors.append(f"config/toolchain.json: configured action is unused: {repository}")

    dependabot_path = root / ".github/dependabot.yml"
    dependabot = dependabot_path.read_text(encoding="utf-8") if dependabot_path.is_file() else ""
    for ecosystem in ("github-actions", "npm", "swift"):
        if f'package-ecosystem: "{ecosystem}"' not in dependabot:
            errors.append(f"Dependabot does not cover {ecosystem}")
    if 'directory: "/Packages/VocelloQwen3Core"' not in dependabot:
        errors.append("Dependabot's swift ecosystem must watch the owned package at /Packages/VocelloQwen3Core")

    package_path = root / "website/package.json"
    if package_path.is_file():
        package = json.loads(package_path.read_text(encoding="utf-8"))
        scripts = package.get("scripts", {})
        for command in ("lint", "test", "build", "check"):
            if not scripts.get(command):
                errors.append(f"website/package.json is missing the deterministic {command} script")

    if installed:
        groups = ("native", "release", "website") if installed == "all" else (installed,)
        for group in groups:
            for name, spec in manifest.get(group, {}).items():
                command = spec.get("versionCommand")
                expected = spec.get("version")
                if not isinstance(command, list) or not expected:
                    errors.append(f"config/toolchain.json: invalid {group}.{name} entry")
                    continue
                try:
                    output = _tool_output(command)
                except ValueError as error:
                    errors.append(str(error))
                    continue
                if not re.search(rf"(?<![0-9.]){re.escape(str(expected))}(?![0-9])", output):
                    first = output.splitlines()[0] if output.splitlines() else "<empty>"
                    errors.append(f"{name}: expected {expected}, observed {first}")
    return errors


def sync_actions(root: Path) -> tuple[list[str], list[str]]:
    """Point config/toolchain.json's actions at the SHAs and version comments the workflows use.

    Returns (changes, errors) and writes the manifest only when there are changes and no
    errors. Entries no workflow uses stay for `validate` to report, never deleted silently.
    """
    manifest_path = root / "config/toolchain.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    actions = manifest.setdefault("actions", {})
    pins: dict[str, set[tuple[str, str]]] = {}
    errors: list[str] = []
    workflows_dir = root / ".github/workflows"
    workflows = sorted(workflows_dir.glob("*.yml")) if workflows_dir.is_dir() else []
    for workflow in workflows:
        for repository, reference, version in ACTION_WITH_VERSION.findall(workflow.read_text(encoding="utf-8")):
            if not re.fullmatch(r"[0-9a-f]{40}", reference):
                errors.append(f"{workflow.relative_to(root)}: {repository}@{reference} is not a full SHA; pin it first")
                continue
            pins.setdefault(repository, set()).add((reference, version))
    changes: list[str] = []
    for repository in sorted(pins):
        shas = {sha for sha, _ in pins[repository]}
        versions = {version for _, version in pins[repository] if version}
        if len(shas) != 1 or len(versions) > 1:
            errors.append(
                f"workflows pin {repository} inconsistently (SHAs {sorted(shas)}, versions {sorted(versions)}); "
                "align them first"
            )
            continue
        sha = shas.pop()
        current = actions.get(repository, {})
        version = versions.pop() if versions else current.get("version")
        if not version:
            errors.append(f"{repository}@{sha} carries no `# <version>` comment and the manifest has no version")
            continue
        if current.get("sha") != sha or current.get("version") != version:
            changes.append(f"{repository}: {current.get('version', '(new)')} -> {version} ({sha})")
            actions[repository] = {**current, "version": version, "sha": sha}
    if changes and not errors:
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return changes, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--installed", choices=("native", "release", "website", "all"))
    parser.add_argument(
        "--sync-actions", action="store_true",
        help="copy the workflows' action SHAs and version comments into config/toolchain.json, then validate",
    )
    args = parser.parse_args()
    if args.sync_actions:
        changes, errors = sync_actions(args.root.resolve())
        for error in errors:
            print(f"error: {error}")
        if errors:
            return 1
        for change in changes:
            print(f"synced {change}")
        if not changes:
            print("config/toolchain.json already matches the workflows' action pins")
    errors = validate(args.root.resolve(), args.installed)
    if errors:
        for error in errors:
            print(f"error: {error}")
        return 1
    print("Supply-chain contract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
