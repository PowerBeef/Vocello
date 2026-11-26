#!/usr/bin/env python3
"""Cut a signed public release tag (`v<major>.<minor>.<patch>`): sign it, verify it, push only it.

On explicit maintainer request (and behind Antigravity's `force_ask` hook), this is the
sanctioned route for Antigravity to sign and push a public `v<major>.<minor>.<patch>` release
tag (AGENTS.md: Hard boundaries). Raw `git tag` / `git push` of tags remains blocked by
`policy_guard.sh`, and iPhone TestFlight candidates stay on `scripts/ios_candidate_tag.py`.

It refuses before writing or deleting anything unless:
  * the working tree is clean, HEAD is local `main` and equals `origin/main`;
  * `project.yml` at HEAD declares a `MAJOR.MINOR.PATCH` `MARKETING_VERSION` whose
    `CURRENT_PROJECT_VERSION` strictly exceeds the previous release tag's build number;
  * `docs/releases/v<version>.md` at HEAD passes `check_release_notes.py`;
  * the latest `CI required` check of a push to `main` succeeded on HEAD;
  * SSH tag signing is configured (`gpg.format=ssh`, readable signing key and allowedSignersFile);
  * either `v<version>` does not exist locally or on `origin`, OR `--replace-unpublished` is
    explicitly passed, `origin`'s tag does not already point to HEAD, and GitHub has zero
    draft or published Releases for `v<version>`.

`--dry-run` runs every check and writes or deletes nothing.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import time

from check_release_notes import validate_notes
from release_build_number import check as check_build_number
from release_evidence import project_version_from_text
from release_source_authority import _flatten_check_runs, _latest_required_check, _push_check_suites

ROOT = Path(__file__).resolve().parent.parent
PROJECT_SPEC = "project.yml"
REQUIRED_CHECK = "CI required"
RELEASE_TAG = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+")
GITHUB_REMOTE = re.compile(
    r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)"
    r"([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?"
)


class Refusal(ValueError):
    """A precondition or command failed before remote state changed."""


class RemoteMutationError(RuntimeError):
    """A failure happened after deleting the old remote tag ref."""


def run(argv: list[str]) -> str:
    completed = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise Refusal(f"`{' '.join(argv[:3])}` failed: {completed.stderr.strip() or completed.stdout.strip()}")
    return completed.stdout


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
        return json.loads(
            run([
                "gh", "api", "--paginate", "--slurp",
                "-H", "Accept: application/vnd.github+json",
                f"repos/{repository}/{path}",
            ])
        )

    rows = _flatten_check_runs(api(f"commits/{commit}/check-runs?filter=all&per_page=100"))
    suites = _push_check_suites(api(f"actions/runs?head_sha={commit}&event=push&branch=main&per_page=100"), commit)
    try:
        _latest_required_check(rows, name=REQUIRED_CHECK, commit=commit, push_suites=suites)
    except ValueError as error:
        raise Refusal(f"CI has not passed on this commit: {error}") from error


def require_build_number(tag: str) -> None:
    try:
        check_build_number(ROOT, tag)
    except (OSError, ValueError) as error:
        raise Refusal(str(error)) from error


def require_release_notes(commit: str, tag: str) -> None:
    notes_rel = f"docs/releases/{tag}.md"
    try:
        notes_text = run(["git", "show", f"{commit}:{notes_rel}"])
    except Refusal as error:
        raise Refusal(f"{notes_rel} is missing from {commit[:12]}: author curated release notes first") from error
    failures = validate_notes(notes_text)
    if failures:
        raise Refusal(f"{notes_rel} failed release-notes gate: {'; '.join(failures)}")


def require_signing() -> None:
    if run(["git", "config", "--get", "gpg.format"]).strip() != "ssh":
        raise Refusal("git signs tags with gpg.format ssh here; it is not configured")
    for key in ("user.signingkey", "gpg.ssh.allowedSignersFile"):
        value = run(["git", "config", "--get", key]).strip()
        if not value or not Path(value).expanduser().is_file():
            raise Refusal(f"git {key} does not name a readable file")


def existing_tag_state(tag: str) -> tuple[str | None, str | None]:
    """Return `(local_object_sha, remote_commit_sha)` for `tag`, or None where absent."""
    local_object: str | None = None
    local_out = run([
        "git", "tag", "--list", tag, "--format=%(objectname)",
    ]).strip()
    if local_out:
        local_object = local_out.splitlines()[0].strip() or None

    remote_raw: str | None = None
    remote_peeled: str | None = None
    ls_out = run([
        "git", "ls-remote", "--tags", "origin", f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}",
    ])
    for line in ls_out.splitlines():
        sha, _, ref = line.partition("\t")
        if ref == f"refs/tags/{tag}^{{}}":
            remote_peeled = sha.strip()
        elif ref == f"refs/tags/{tag}":
            remote_raw = sha.strip()
    remote_target = remote_peeled or remote_raw
    return local_object, remote_target


def require_no_github_release(repository: str, tag: str) -> None:
    """Refuse if GitHub has any draft or published Release for `tag` (fails closed)."""
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
                state = "draft" if release.get("draft") else "published"
                raise Refusal(
                    f"GitHub already has a {state} Release for {tag}: "
                    "never replace a drafted or published release tag"
                )


def create_and_push(
    tag: str,
    commit: str,
    message: str,
    *,
    replace_local: str | None = None,
    replace_remote: bool = False,
) -> None:
    if not RELEASE_TAG.fullmatch(tag):
        raise Refusal(f"{tag} is not a v<major>.<minor>.<patch> release tag")
    ref = f"refs/tags/{tag}"
    if replace_local is not None:
        run(["git", "tag", "-d", tag])
    remote_deleted = False
    try:
        run(["git", "tag", "-s", "-m", message, tag, commit])
        run(["git", "tag", "-v", tag])
        if run(["git", "cat-file", "-t", ref]).strip() != "tag":
            raise Refusal("the new tag is not annotated")
        if run(["git", "rev-parse", f"{ref}^{{commit}}"]).strip() != commit:
            raise Refusal("the new tag does not name the release commit")
        if replace_remote:
            run(["git", "push", "--no-follow-tags", "origin", f":{ref}"])
            remote_deleted = True
        # Only this ref: follow-tags would also push any other unpushed annotated tag.
        run(["git", "push", "--no-follow-tags", "origin", f"{ref}:{ref}"])
    except Refusal as error:
        if remote_deleted:
            raise RemoteMutationError(
                f"deleted old remote {tag} on origin, then pushing the replacement failed: {error}"
            ) from error
        subprocess.run(["git", "tag", "-d", tag], cwd=ROOT, capture_output=True, check=False)
        if replace_local is not None:
            subprocess.run(["git", "update-ref", ref, replace_local], cwd=ROOT, capture_output=True, check=False)
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
            reason = f"lookup failed ({type(error).__name__})"
        if attempt + 1 < attempts:
            time.sleep(delay)
    return reason


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cut a signed public release tag (v<major>.<minor>.<patch>).")
    parser.add_argument("--dry-run", action="store_true", help="run every check; create, delete, and push nothing")
    parser.add_argument(
        "--replace-unpublished",
        action="store_true",
        help="replace an existing tag only when GitHub has no draft or published Release for it",
    )
    arguments = parser.parse_args(argv)
    try:
        commit = require_clean_main()
        version, build = project_version_from_text(run(["git", "show", f"{commit}:{PROJECT_SPEC}"]))
        tag = f"v{version}"
        if not RELEASE_TAG.fullmatch(tag):
            raise Refusal(f"{tag} is not a v<major>.<minor>.<patch> release tag; check MARKETING_VERSION")
        repository = origin_repository()
        require_ci(repository, commit)
        require_build_number(tag)
        require_release_notes(commit, tag)
        require_signing()
        local_object, remote_target = existing_tag_state(tag)
        if local_object is not None or remote_target is not None:
            if not arguments.replace_unpublished:
                where = "origin and locally" if (local_object and remote_target) else (
                    "origin" if remote_target else "locally"
                )
                raise Refusal(
                    f"{tag} already exists {where}; pass --replace-unpublished only if no draft or "
                    "published GitHub Release exists"
                )
            if remote_target == commit:
                raise Refusal(f"{tag} on origin already names {commit[:12]}: rerun release.yml instead")
            require_no_github_release(repository, tag)
        message = f"Vocello {version} (build {build})"
        action = "replace unpublished and push" if (local_object or remote_target) else "sign and push"
        if arguments.dry_run:
            print(f"Dry run: would {action} {tag} at {commit[:12]} ({version}, build {build}).")
            return 0
        create_and_push(
            tag,
            commit,
            message,
            replace_local=local_object,
            replace_remote=remote_target is not None,
        )
    except RemoteMutationError as error:
        print(f"release_tag: partial remote mutation: {error}", file=sys.stderr)
        return 1
    except (Refusal, ValueError) as error:
        print(f"release_tag: refused, nothing pushed: {error}", file=sys.stderr)
        return 1
    # From here the tag is on origin and release.yml has started; nothing below may read as a refusal.
    print(f"Pushed {tag} at {commit[:12]} ({version}, build {build}).")
    print("release.yml now runs Security and waits for `release` environment approval on `package` and `sparkle-feed`.")
    try:
        reason = github_verification(repository, tag)
    except Exception as error:  # noqa: BLE001 - any failure here is "pushed, verification unknown"
        reason = f"unknown ({type(error).__name__})"
    print(f"GitHub signature: {reason}.")
    if reason != "valid":
        print(
            "GitHub has not verified the signature, so release.yml's source authority will refuse it.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
