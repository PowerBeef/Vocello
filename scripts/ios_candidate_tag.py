#!/usr/bin/env python3
"""Cut the next iPhone TestFlight candidate tag: sign it, verify it, push only it.

On the maintainer's request this is the one route by which Claude Code writes a release tag
(CLAUDE.md: Hard boundaries); every other tag stays maintainer-run. It refuses unless the
working tree is clean, HEAD is local `main` and exactly `origin/main`, the latest `CI required`
check of a push to main succeeded on that commit, and App Store Connect has no iOS build with
project.yml's build number. It then creates `v<MARKETING_VERSION>-ios.<N>` (the next free N)
as an annotated tag signed with the configured SSH key, verifies it against the allowed
signers and pushes that one ref. The push starts release.yml, whose iPhone path archives the
app, verifies the IPA and uploads it to TestFlight once the `release` environment is approved.
`--dry-run` runs every check and creates nothing.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import time

from release_evidence import project_version_from_text
from release_source_authority import _flatten_check_runs, _latest_required_check, _push_check_suites

ROOT = Path(__file__).resolve().parent.parent
BUNDLE_ID = "com.patricedery.vocello"
REQUIRED_CHECK = "CI required"
# scripts/ci/release_trigger.py IOS_CANDIDATE: the only tag shape release.yml sends to TestFlight.
IOS_CANDIDATE = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+-ios\.[1-9][0-9]*")
GITHUB_REMOTE = re.compile(r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)"
                           r"([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?")


class Refusal(ValueError):
    """A command or precondition failed. Before the push nothing is left behind; main() reports
    anything after it as pushed."""


def run(argv: list[str]) -> str:
    completed = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise Refusal(f"`{' '.join(argv[:3])}` failed: {completed.stderr.strip() or completed.stdout.strip()}")
    return completed.stdout


def next_tag(version: str, existing: list[str]) -> str:
    pattern = re.compile(rf"v{re.escape(version)}-ios\.([1-9][0-9]*)")
    numbers = [int(match.group(1)) for tag in existing if (match := pattern.fullmatch(tag))]
    return f"v{version}-ios.{max(numbers, default=0) + 1}"


def existing_tags(version: str) -> list[tuple[str, str]]:
    """Every local and remote `v<version>-ios.*` tag with the commit it names, from each side."""
    tags: list[tuple[str, str]] = []
    for line in run(["git", "tag", "--list", f"v{version}-ios.*",
                     "--format=%(refname:strip=2) %(*objectname)%(objectname)"]).splitlines():
        name, _, objects = line.partition(" ")
        tags.append((name, objects[:40]))
    # Without --refs, an annotated tag's peeled line (`^{}`) names its commit.
    for line in run(["git", "ls-remote", "--tags", "origin", f"refs/tags/v{version}-ios.*"]).splitlines():
        sha, _, ref = line.partition("\t")
        tags.append((ref.removeprefix("refs/tags/").removesuffix("^{}"), sha))
    return tags


def require_clean_main() -> str:
    if run(["git", "symbolic-ref", "--short", "HEAD"]).strip() != "main":
        raise Refusal("check out main first")
    if run(["git", "status", "--porcelain"]).strip():
        raise Refusal("the working tree has uncommitted changes")
    run(["git", "fetch", "--quiet", "origin", "main"])
    head = run(["git", "rev-parse", "HEAD"]).strip()
    if head != run(["git", "rev-parse", "refs/remotes/origin/main"]).strip():
        raise Refusal("HEAD is not exactly origin/main: push main first, or pull it")
    return head


def origin_repository() -> str:
    """owner/name of origin, the remote the tag goes to (never gh's default repository)."""
    match = GITHUB_REMOTE.fullmatch(run(["git", "remote", "get-url", "origin"]).strip())
    if match is None:
        raise Refusal("origin is not a GitHub repository")
    return match.group(1)


def require_ci(repository: str, commit: str) -> None:
    def api(path: str) -> object:
        return json.loads(run(["gh", "api", "--paginate", "--slurp", "-H", "Accept: application/vnd.github+json",
                               f"repos/{repository}/{path}"]))
    rows = _flatten_check_runs(api(f"commits/{commit}/check-runs?filter=all&per_page=100"))
    suites = _push_check_suites(api(f"actions/runs?head_sha={commit}&event=push&branch=main&per_page=100"), commit)
    try:
        _latest_required_check(rows, name=REQUIRED_CHECK, commit=commit, push_suites=suites)
    except ValueError as error:
        raise Refusal(f"CI has not passed on this commit: {error}") from error


def require_unused_build(build: str) -> None:
    listing = json.loads(run(["asc", "builds", "list", "--app", BUNDLE_ID, "--platform", "IOS",
                              "--build-number", build, "--processing-state", "all", "--output", "json"]))
    if not isinstance(listing, dict) or not isinstance(listing.get("data"), list):
        raise Refusal("App Store Connect returned no build list")
    if listing["data"]:
        raise Refusal(f"App Store Connect already has build {build}: raise CURRENT_PROJECT_VERSION in project.yml")


def require_signing() -> None:
    if run(["git", "config", "--get", "gpg.format"]).strip() != "ssh":
        raise Refusal("git signs tags with gpg.format ssh here; it is not configured")
    for key in ("user.signingkey", "gpg.ssh.allowedSignersFile"):
        value = run(["git", "config", "--get", key]).strip()
        if not value or not Path(value).expanduser().is_file():
            raise Refusal(f"git {key} does not name a readable file")


def create_and_push(tag: str, commit: str, message: str) -> None:
    if not IOS_CANDIDATE.fullmatch(tag):
        raise Refusal(f"{tag} is not a v<x.y.z>-ios.<n> candidate tag")
    ref = f"refs/tags/{tag}"
    run(["git", "tag", "-s", "-m", message, tag, commit])
    try:
        run(["git", "tag", "-v", tag])
        if run(["git", "cat-file", "-t", ref]).strip() != "tag":
            raise Refusal("the new tag is not annotated")
        if run(["git", "rev-parse", f"{ref}^{{commit}}"]).strip() != commit:
            raise Refusal("the new tag does not name the release commit")
        # Only this ref: follow-tags would also push any other unpushed annotated tag.
        run(["git", "push", "--no-follow-tags", "origin", f"{ref}:{ref}"])
    except Refusal:
        # Never pushed, so the local tag is ours to remove.
        subprocess.run(["git", "tag", "-d", tag], cwd=ROOT, capture_output=True, check=False)
        raise


def github_verification(repository: str, tag: str, attempts: int = 6, delay: float = 5.0) -> str:
    """GitHub's verdict on the pushed tag's signature, which release.yml's source authority requires."""
    reason = "unknown"
    for attempt in range(attempts):
        try:
            ref = json.loads(run(["gh", "api", f"repos/{repository}/git/ref/tags/{tag}"]))
            tag_object = json.loads(run(["gh", "api", f"repos/{repository}/git/tags/{ref['object']['sha']}"]))
            verification = tag_object.get("verification") or {}
            reason = str(verification.get("reason"))
            if verification.get("verified") is True and reason == "valid":
                return reason
        except (Refusal, ValueError, KeyError, TypeError) as error:
            # The ref can lag the push; a lookup error is retried like an unverified answer.
            reason = f"lookup failed ({type(error).__name__})"
        if attempt + 1 < attempts:
            time.sleep(delay)
    return reason


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cut the next signed iPhone TestFlight candidate tag.")
    parser.add_argument("--dry-run", action="store_true", help="run every check; create and push nothing")
    arguments = parser.parse_args(argv)
    try:
        commit = require_clean_main()
        # The commit's own project.yml, not the working tree's.
        version, build = project_version_from_text(run(["git", "show", f"{commit}:project.yml"]))
        repository = origin_repository()
        require_ci(repository, commit)
        require_unused_build(build)
        require_signing()
        tags = existing_tags(version)
        already = sorted({name for name, target in tags if target == commit})
        if already:
            raise Refusal(f"{already[-1]} already names this commit: rerun its workflow instead of a new tag")
        tag = next_tag(version, [name for name, _ in tags])
        if not IOS_CANDIDATE.fullmatch(tag):
            raise Refusal(f"{tag} is not a v<x.y.z>-ios.<n> candidate tag; check MARKETING_VERSION")
        number = tag.rsplit(".", 1)[1]
        message = f"Vocello {version} for iPhone (TestFlight candidate {number}, build {build})"
        if arguments.dry_run:
            print(f"Dry run: would sign and push {tag} at {commit[:12]} ({version}, build {build}).")
            return 0
        create_and_push(tag, commit, message)
    except (Refusal, ValueError) as error:
        print(f"ios_candidate_tag: refused, nothing pushed: {error}", file=sys.stderr)
        return 1
    # From here the tag is on origin and release.yml has started; nothing below may read as a refusal.
    print(f"Pushed {tag} at {commit[:12]} ({version}, build {build}).")
    print("release.yml now archives, verifies and uploads it; approve the `release` environment when it asks.")
    try:
        reason = github_verification(repository, tag)
    except Exception as error:  # noqa: BLE001 - any failure here is "pushed, verification unknown"
        reason = f"unknown ({type(error).__name__})"
    print(f"GitHub signature: {reason}.")
    if reason != "valid":
        print("GitHub has not verified the signature, so release.yml's source authority will refuse it.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
