#!/usr/bin/env python3
"""Emit a content-complete, privacy-safe fingerprint of the Git worktree.

The digest binds HEAD, the final tracked worktree bytes, and the path plus bytes
of every non-ignored untracked file. Index placement is intentionally ignored:
staging an already-validated tree cannot invalidate the result. The helper
emits only the digest, so callers retain no source content.

`--build-inputs` emits the narrower identity the macOS UI build skip keys on
(audit #75): the same content binding, minus paths no build reads (published
benchmark records and their index, docs, the website and the roadmap
bookkeeping), and keyed on the content of what remains rather than on the
commit, so a publication or roadmap commit alone never forces a rebuild while
any source, project or test edit still does.
"""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys


SCHEMA_TAG = b"vocello-tree-fingerprint-v2\0"
BUILD_INPUTS_SCHEMA_TAG = b"vocello-build-inputs-fingerprint-v1\0"
# Paths no native build reads: evidence publication, generated docs, the
# website and roadmap bookkeeping (audit #75). Everything else stays bound.
NON_BUILD_PATHS = (
    "benchmarks/runs",
    "benchmarks/HISTORY.md",
    "docs",
    "website",
    "config/roadmap.json",
    "config/roadmap-archive.json",
)


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


def _worktree_blob(root: Path, relative: str) -> tuple[str, str] | None:
    """(git mode, git blob ID) of a worktree path's current bytes; None when absent."""
    candidate = root / relative
    if candidate.is_symlink():
        data = os.readlink(candidate).encode("utf-8", errors="surrogateescape")
        mode = "120000"
    elif candidate.is_file():
        data = candidate.read_bytes()
        mode = "100755" if os.access(candidate, os.X_OK) else "100644"
    elif candidate.exists():
        raise FingerprintError(f"path is not a regular file: {relative}")
    else:
        return None
    blob = hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()
    return mode, blob


def build_inputs_fingerprint(root: Path, excluded: tuple[str, ...] = NON_BUILD_PATHS) -> str:
    """The content identity of every path a build may read (audit #75).

    Each included path is bound by its git mode and blob ID: HEAD's for an
    unchanged tracked file, the worktree bytes' for a changed or untracked one
    (never an ignored file). The listing is the same for the same content
    whatever the commit, the index or the excluded paths hold."""
    root = root.resolve()
    pathspec = [".", *(f":(exclude){path}" for path in excluded)]
    prefixes = tuple(excluded)

    def included(path: str) -> bool:
        return not any(path == prefix or path.startswith(prefix + "/") for prefix in prefixes)

    entries: dict[str, tuple[str, str]] = {}
    # `ls-tree` takes no exclude pathspec; its entries are filtered here.
    for entry in _git(root, "ls-tree", "-r", "-z", "--full-tree", "HEAD").split(b"\0"):
        if not entry:
            continue
        metadata, path_bytes = entry.split(b"\t", 1)
        path = path_bytes.decode("utf-8", errors="surrogateescape")
        if included(path):
            mode, _kind, obj = metadata.decode("ascii").split(" ")
            entries[path] = (mode, obj)
    changed = _git(root, "diff", "HEAD", "--name-only", "--no-renames", "-z", "--", *pathspec)
    untracked = _git(root, "ls-files", "--others", "--exclude-standard", "-z", "--", *pathspec)
    for part in [*changed.split(b"\0"), *untracked.split(b"\0")]:
        if not part:
            continue
        path = part.decode("utf-8", errors="surrogateescape")
        current = _worktree_blob(root, path)
        if current is None:
            entries.pop(path, None)
        else:
            entries[path] = current
    digest = hashlib.sha256()
    digest.update(BUILD_INPUTS_SCHEMA_TAG)
    for path in sorted(entries):
        mode, obj = entries[path]
        digest.update(path.encode("utf-8", errors="surrogateescape"))
        digest.update(f"\0{mode}\0{obj}\0".encode("ascii"))
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--build-inputs", action="store_true",
        help="the build-input identity (no commit ID; publication, docs, website and roadmap paths left out)",
    )
    args = parser.parse_args(argv)
    try:
        print(build_inputs_fingerprint(args.root) if args.build_inputs else worktree_fingerprint(args.root))
    except (OSError, FingerprintError) as error:
        print(f"error: cannot fingerprint worktree: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
