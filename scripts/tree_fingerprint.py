#!/usr/bin/env python3
"""Emit a content-complete, privacy-safe fingerprint of the Git worktree.

The digest binds HEAD, the final tracked worktree bytes, and the path plus bytes
of every non-ignored untracked file. Index placement is intentionally ignored:
staging an already-validated tree cannot invalidate the result. The helper
emits only the digest, so callers retain no source content.
"""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys


SCHEMA_TAG = b"vocello-tree-fingerprint-v2\0"


class FingerprintError(RuntimeError):
    pass


def _git(root: Path, *args: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", os.fspath(root), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        raise FingerprintError(message or f"git {' '.join(args)} failed")
    return completed.stdout


def _add_file(digest: "hashlib._Hash", root: Path, relative_bytes: bytes) -> None:
    relative = relative_bytes.decode("utf-8", errors="surrogateescape")
    candidate = root / relative
    digest.update(b"untracked-path\0")
    digest.update(relative_bytes)
    digest.update(b"\0")
    if candidate.is_symlink():
        digest.update(b"symlink\0")
        digest.update(os.readlink(candidate).encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        return
    if not candidate.is_file():
        raise FingerprintError(f"untracked path is not a regular file: {relative}")
    digest.update(b"file\0")
    with candidate.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    digest.update(b"\0")


def worktree_fingerprint(root: Path) -> str:
    root = root.resolve()
    digest = hashlib.sha256()
    digest.update(SCHEMA_TAG)
    digest.update(b"head\0")
    digest.update(_git(root, "rev-parse", "HEAD").strip())
    digest.update(b"\0tracked-worktree-diff\0")
    digest.update(_git(root, "diff", "HEAD", "--binary", "--no-ext-diff"))
    digest.update(b"\0")
    untracked = _git(root, "ls-files", "--others", "--exclude-standard", "-z")
    for relative in sorted(part for part in untracked.split(b"\0") if part):
        _add_file(digest, root, relative)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        print(worktree_fingerprint(args.root))
    except (OSError, FingerprintError) as error:
        print(f"error: cannot fingerprint worktree: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
