#!/usr/bin/env python3
"""A release's build number is greater than the previous release tag's (RF-23).

Sparkle offers an update only when the feed's `sparkle:version` (CFBundleVersion, which is
project.yml's CURRENT_PROJECT_VERSION) is newer than the installed copy's, so a release whose
build number did not move would never reach installed copies; App Store Connect refuses a
reused build number too. `check --tag <tag>` compares the checked-out project.yml with
project.yml at the previous `v*` tag in version order (a prerelease sorts before its release,
`v1.2` equals `v1.2.0`) and fails unless the build number is strictly greater.

The comparison does not depend on Sparkle: v2.4.0 (build 23) shipped without it and 3.0.0
(build 24) must still be greater. With no earlier `v*` tag there is nothing to compare and the
check passes, saying so. An earlier tag whose project.yml cannot be read fails the check
instead of being skipped. Build numbers are one to three period-separated integers, compared
numerically.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys

from release_evidence import project_version_from_text

ROOT = Path(__file__).resolve().parent.parent
TAG = re.compile(r"v([0-9]+)\.([0-9]+)(?:\.([0-9]+))?(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?")
BUILD = re.compile(r"[0-9]+(?:\.[0-9]+){0,2}")

# A tag's precedence: (major, minor, patch, release-after-prerelease, prerelease identifiers).
TagKey = tuple[int, int, int, int, tuple[tuple[int, int, str], ...]]


def tag_key(tag: str) -> TagKey | None:
    """Semantic-version precedence of a `v*` tag, or None when it is not a version tag."""
    match = TAG.fullmatch(tag)
    if match is None:
        return None
    major, minor, patch, prerelease = match.groups()
    identifiers: tuple[tuple[int, int, str], ...] = ()
    if prerelease is not None:
        # Numeric identifiers sort numerically and before alphanumeric ones.
        identifiers = tuple((0, int(part), "") if part.isdigit() else (1, 0, part) for part in prerelease.split("."))
    return (int(major), int(minor), int(patch or 0), 0 if prerelease is not None else 1, identifiers)


def previous_tag(tags: list[str], current: str) -> str | None:
    """The highest version tag strictly below `current`; ties and non-version tags are ignored.

    A Mac release never follows an iPhone TestFlight candidate (`-ios.<n>`, which App Store
    Connect numbers on its own), so a Mac release at its candidate's build still passes."""
    current_key = tag_key(current)
    if current_key is None:
        raise ValueError(f"release tag {current!r} is not a vMAJOR.MINOR[.PATCH][-PRERELEASE] tag")
    if "-ios" not in current.lower():
        tags = [tag for tag in tags if "-ios" not in tag.lower()]
    earlier = [(key, tag) for tag in tags if (key := tag_key(tag)) is not None and key < current_key]
    return max(earlier)[1] if earlier else None


def build_number(value: str, label: str) -> tuple[int, int, int]:
    if not BUILD.fullmatch(value):
        raise ValueError(f"{label} CURRENT_PROJECT_VERSION {value!r} is not one to three period-separated integers")
    parts = [int(part) for part in value.split(".")] + [0, 0]
    return parts[0], parts[1], parts[2]


def _git(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(root), *arguments], capture_output=True, text=True, check=False)


def check(root: Path, tag: str) -> str:
    """Why `tag`'s build number may be released; raises ValueError when it may not."""
    if tag_key(tag) is None:
        raise ValueError(f"release tag {tag!r} is not a vMAJOR.MINOR[.PATCH][-PRERELEASE] tag")
    _, current = project_version_from_text((root / "project.yml").read_text(encoding="utf-8"))
    current_number = build_number(current, f"{tag}'s")
    listing = _git(root, "tag", "--list", "v*")
    if listing.returncode != 0:
        raise ValueError(f"cannot list the v* tags: {listing.stderr.strip()}")
    previous = previous_tag(listing.stdout.split(), tag)
    if previous is None:
        return f"no v* tag precedes {tag}: build {current} is the first and needs no comparison"
    shown = _git(root, "show", f"refs/tags/{previous}^{{commit}}:project.yml")
    if shown.returncode != 0:
        raise ValueError(f"cannot read project.yml at the previous release tag {previous}: {shown.stderr.strip()}")
    _, earlier = project_version_from_text(shown.stdout)
    if current_number <= build_number(earlier, f"{previous}'s"):
        raise ValueError(
            f"{tag} declares build {current}, which is not greater than {previous}'s build {earlier}: "
            "raise CURRENT_PROJECT_VERSION in project.yml, or installed copies are never offered this update"
        )
    return f"{tag} build {current} is greater than {previous}'s build {earlier}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    check_parser = commands.add_parser("check", help="fail unless the build number exceeds the previous tag's")
    check_parser.add_argument("--tag", required=True, help="the release tag being built (v<MARKETING_VERSION>...)")
    check_parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        print(check(args.root, args.tag))
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
