#!/usr/bin/env python3
"""Upload a validated `quality-promotion.json` manifest to an existing draft GitHub Release.

On explicit maintainer request (and behind Antigravity's `force_ask` hook), this is the
sanctioned route for Antigravity to attach a validated macOS quality-promotion manifest to
an existing draft Release ahead of `promote-release.yml` (AGENTS.md: Hard boundaries).
Raw `gh release create|edit|delete|upload` commands remain hard-denied by
`agy_hook_adapter.py`.

It refuses before writing anything unless:
  * `--tag` is a public `v<major>.<minor>.<patch>` release tag;
  * `--manifest` exists and is named exactly `quality-promotion.json` (never a binary or DMG);
  * `scripts/quality_promotion.py validate --platform macos` passes on `--manifest` against
    `--release-evidence` for `--tag`;
  * `origin` names the GitHub repository and GitHub currently has a **draft** Release
    (`draft: true`) for `--tag` (published releases are refused).

`--dry-run` runs every check and uploads nothing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
RELEASE_TAG = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+")
GITHUB_REMOTE = re.compile(
    r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)"
    r"([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?"
)
DEFAULT_MANIFEST = Path("build/artifacts/quality-promotion/quality-promotion.json")
DEFAULT_EVIDENCE = Path("build/artifacts/quality-promotion/release/release-evidence.json")


class Refusal(ValueError):
    """A precondition or command failed before uploading anything."""


def run(argv: list[str]) -> str:
    completed = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise Refusal(f"`{' '.join(argv[:3])}` failed: {completed.stderr.strip() or completed.stdout.strip()}")
    return completed.stdout


def origin_repository() -> str:
    """owner/name of origin, the remote that owns the draft Release."""
    match = GITHUB_REMOTE.fullmatch(run(["git", "remote", "get-url", "origin"]).strip())
    if match is None:
        raise Refusal("origin is not a GitHub repository")
    return match.group(1)


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else (ROOT / path)


def require_manifest_file(manifest: Path) -> tuple[int, str]:
    if manifest.name != "quality-promotion.json":
        raise Refusal(f"manifest must be named quality-promotion.json, not {manifest.name!r}")
    if not manifest.is_file():
        raise Refusal(f"manifest not found: {manifest}")
    data = manifest.read_bytes()
    return len(data), hashlib.sha256(data).hexdigest()


def require_valid_manifest(tag: str, evidence: Path, manifest: Path) -> None:
    if not evidence.is_file():
        raise Refusal(f"release evidence not found: {evidence}")
    run([
        sys.executable,
        str(ROOT / "scripts/quality_promotion.py"),
        "validate",
        "--platform", "macos",
        "--tag", tag,
        "--release-evidence", str(evidence),
        "--manifest", str(manifest),
    ])


def find_draft_release(repository: str, tag: str) -> dict[str, object]:
    """Return the draft Release object for `tag`, or refuse if absent or already published."""
    raw = run([
        "gh", "api", "--paginate", "--slurp",
        "-H", "Accept: application/vnd.github+json",
        f"repos/{repository}/releases?per_page=100",
    ])
    try:
        pages = json.loads(raw)
    except json.JSONDecodeError as error:
        raise Refusal(f"GitHub releases response was not valid JSON: {error}") from error
    if not isinstance(pages, list):
        raise Refusal("GitHub releases response had an unexpected shape")
    for page in pages:
        if not isinstance(page, list):
            raise Refusal("GitHub releases page had an unexpected shape")
        for release in page:
            if not isinstance(release, dict):
                raise Refusal("GitHub release entry had an unexpected shape")
            if release.get("tag_name") == tag:
                if release.get("draft") is not True:
                    raise Refusal(f"GitHub Release {tag} is already published; never modify a published release")
                return release
    raise Refusal(f"no draft GitHub Release found for {tag} on {repository}")


def verify_uploaded_asset(repository: str, tag: str, expected_size: int) -> None:
    release = find_draft_release(repository, tag)
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise Refusal(f"draft Release {tag} returned no asset list after upload")
    for asset in assets:
        if isinstance(asset, dict) and asset.get("name") == "quality-promotion.json":
            observed_size = asset.get("size")
            if observed_size != expected_size:
                raise Refusal(
                    f"uploaded quality-promotion.json size mismatch: remote {observed_size} != local {expected_size}"
                )
            return
    raise Refusal(f"quality-promotion.json not listed on draft Release {tag} after upload")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Upload a validated quality-promotion.json manifest to an existing draft GitHub Release."
    )
    parser.add_argument("--tag", required=True, help="public release tag (v<major>.<minor>.<patch>)")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="path to validated quality-promotion.json",
    )
    parser.add_argument(
        "--release-evidence",
        type=Path,
        default=DEFAULT_EVIDENCE,
        help="path to downloaded draft release-evidence.json",
    )
    parser.add_argument("--dry-run", action="store_true", help="run every check; upload nothing")
    arguments = parser.parse_args(argv)
    try:
        if not RELEASE_TAG.fullmatch(arguments.tag):
            raise Refusal(f"{arguments.tag!r} is not a v<major>.<minor>.<patch> release tag")
        manifest = resolve_path(arguments.manifest)
        evidence = resolve_path(arguments.release_evidence)
        size, digest = require_manifest_file(manifest)
        require_valid_manifest(arguments.tag, evidence, manifest)
        repository = origin_repository()
        find_draft_release(repository, arguments.tag)
        if arguments.dry_run:
            print(
                f"Dry run: would upload quality-promotion.json ({size} bytes, sha256 {digest[:12]}) "
                f"to draft Release {arguments.tag} on {repository}."
            )
            return 0
        run([
            "gh", "release", "upload", arguments.tag, str(manifest),
            "--clobber", "--repo", repository,
        ])
    except (Refusal, ValueError, OSError) as error:
        print(f"upload_promotion_manifest: refused, nothing uploaded: {error}", file=sys.stderr)
        return 1
    try:
        verify_uploaded_asset(repository, arguments.tag, size)
    except (Refusal, ValueError) as error:
        print(f"upload_promotion_manifest: uploaded, post-upload verification failed: {error}", file=sys.stderr)
        return 1
    print(
        f"Uploaded quality-promotion.json ({size} bytes, sha256 {digest[:12]}) "
        f"to draft Release {arguments.tag} on {repository}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
