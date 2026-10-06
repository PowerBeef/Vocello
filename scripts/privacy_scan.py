#!/usr/bin/env python3
"""Reject private paths and credential-shaped tokens in tracked or staged text.

Usage:
  privacy_scan.py                 scan every tracked file
  privacy_scan.py --staged        scan the files staged for commit
  privacy_scan.py --paths a b c   scan these paths (missing or binary files are skipped)

The rules are exact and few: a developer home directory (`/Users/<name>/`,
`/home/<name>/`, `C:\\Users\\<name>\\`) other than the documented `example`
placeholder, and the fixed shapes of real credentials (complete private-key PEM blocks,
AWS access keys, GitHub classic and fine-grained tokens, Hugging Face and npm tokens, Slack
tokens, App Store Connect key files). Prose
about these things is fine; the tokens themselves are not.

The scan reads repository text only. It cannot tell whether arbitrary text holds a
prompt or transcript, and it cannot see what a running app writes: runtime
diagnostics record failures through `DiagnosticPrivacy` instead
(docs/reference/privacy-storage.md, Diagnostics).
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

HOME = re.compile(r"(?:/Users/|/home/|C:\\\\Users\\\\)(?!example[/\\\\])[A-Za-z0-9._-]+[/\\\\]")
PEM_BEGIN = re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY(?: BLOCK)?-----")
PEM_END = re.compile(r"-----END (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY(?: BLOCK)?-----")
SECRETS = (
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{50,}\b"),
    re.compile(r"\bhf_[A-Za-z0-9]{34,}\b"),
    re.compile(r"\bnpm_[A-Za-z0-9]{36,}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{32,}\b"),
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{24,}"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
)
CREDENTIAL_SUFFIXES = (".p8", ".p12", ".pem", ".mobileprovision", ".keychain-db")
SELF = Path(__file__).resolve()


def _decode(data: bytes | None) -> str | None:
    if data is None or b"\0" in data[:8192]:
        return None
    return data.decode("utf-8", errors="replace")


def _working_tree(root: Path, relative: str) -> bytes | None:
    path = root / relative
    if not path.is_file():
        return None
    try:
        return path.read_bytes()
    except OSError:
        return None


class _StagedBlobs:
    """The content `git commit` will record for a path, not the working-tree copy, read
    through one `git cat-file --batch` process however many paths are staged."""

    def __init__(self, root: Path) -> None:
        self.process = subprocess.Popen(["git", "-C", str(root), "cat-file", "--batch"],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def __call__(self, root: Path, relative: str) -> bytes | None:
        if "\n" in relative or self.process.stdin is None or self.process.stdout is None:
            return None
        self.process.stdin.write(f":{relative}\n".encode("utf-8", "surrogateescape"))
        self.process.stdin.flush()
        header = self.process.stdout.readline().split()
        if len(header) != 3 or not header[2].isdigit():
            return None                                  # "<object> missing"
        data = self.process.stdout.read(int(header[2]))
        self.process.stdout.read(1)                      # the newline after the content
        return data if header[1] == b"blob" else None

    def close(self) -> None:
        if self.process.stdin is not None:
            self.process.stdin.close()
        self.process.wait()


def _worktree_paths(root: Path, pathspecs: list[str]) -> list[str]:
    """The working-tree files the pathspecs select: a named file itself (also when ignored, as
    `git add -f` takes it), and the changed or untracked files under a named directory."""
    paths = {spec for spec in pathspecs if (root / spec).is_file()}
    listed = subprocess.run(["git", "-C", str(root), "ls-files", "--modified", "--others", "--exclude-standard",
                             "-z", "--", *pathspecs], capture_output=True)
    if listed.returncode == 0:
        paths.update(p.decode("utf-8", "surrogateescape") for p in listed.stdout.split(b"\0") if p)
    return sorted(paths)


def scan(root: Path, paths: list[str], read=_working_tree) -> list[str]:
    findings: list[str] = []
    for relative in paths:
        path = root / relative
        if path.resolve() == SELF:
            continue
        if path.suffix in CREDENTIAL_SUFFIXES:
            if read(root, relative) is not None:
                findings.append(f"{relative}: credential file must never be committed")
            continue
        text = _decode(read(root, relative))
        if text is None:
            continue
        # A header alone is prose or a fixture; a header with its footer is a key.
        if PEM_BEGIN.search(text) and PEM_END.search(text):
            findings.append(f"{relative}: private key block")
        for number, line in enumerate(text.splitlines(), 1):
            if HOME.search(line):
                findings.append(f"{relative}:{number}: developer home path; use a relative or /Users/example/ path")
            if any(pattern.search(line) for pattern in SECRETS):
                findings.append(f"{relative}:{number}: credential-shaped token")
    return findings


def _git_paths(root: Path, *args: str) -> list[str]:
    out = subprocess.run(["git", "-C", str(root), *args, "-z"], capture_output=True, check=True).stdout
    return [p.decode("utf-8", "surrogateescape") for p in out.split(b"\0") if p]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--staged", action="store_true", help="the staged blobs, as a commit will record them")
    mode.add_argument("--changes", action="store_true",
                      help="working-tree files with unstaged changes, and untracked files")
    mode.add_argument("--tracked-changes", action="store_true",
                      help="working-tree files with unstaged changes (what `git commit -a` records)")
    mode.add_argument("--worktree-paths", nargs="+", metavar="PATHSPEC",
                      help="the working-tree files these literal pathspecs select, relative to --root")
    mode.add_argument("--paths", nargs="+")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    read = _working_tree
    staged: _StagedBlobs | None = None
    if args.paths:
        paths = args.paths
    elif args.staged:
        paths = _git_paths(root, "diff", "--cached", "--name-only", "--diff-filter=ACMR")
        read = staged = _StagedBlobs(root)
    elif args.changes:
        paths = sorted(set(_git_paths(root, "diff", "--name-only", "--diff-filter=ACMR"))
                       | set(_git_paths(root, "ls-files", "--others", "--exclude-standard")))
    elif args.tracked_changes:
        paths = _git_paths(root, "diff", "--name-only", "--diff-filter=ACMR")
    elif args.worktree_paths:
        paths = _worktree_paths(root, args.worktree_paths)
    else:
        paths = _git_paths(root, "ls-files")
    findings = scan(root, paths, read)
    if staged is not None:
        staged.close()
    for finding in findings:
        print(f"error: {finding}", file=sys.stderr)
    if findings:
        return 1
    print(f"privacy scan: PASS ({len(paths)} path(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
