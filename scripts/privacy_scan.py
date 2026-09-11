#!/usr/bin/env python3
"""Reject private paths and credential-shaped tokens in tracked or staged text.

Usage:
  privacy_scan.py                 scan every tracked file
  privacy_scan.py --staged        scan the files staged for commit
  privacy_scan.py --paths a b c   scan these paths (missing or binary files are skipped)

The rules are exact and few: a developer home directory (`/Users/<name>/`,
`/home/<name>/`, `C:\\Users\\<name>\\`) other than the documented `example`
placeholder, and the fixed shapes of real credentials (complete private-key PEM blocks,
AWS access keys, GitHub tokens, Slack tokens, App Store Connect key files). Prose
about these things is fine; the tokens themselves are not.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

HOME = re.compile(r"(?:/Users/|/home/|C:\\\\Users\\\\)(?!example[/\\\\])[A-Za-z0-9._-]+[/\\\\]")
PEM_BEGIN = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----")
PEM_END = re.compile(r"-----END (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----")
SECRETS = (
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{32,}\b"),
)
CREDENTIAL_SUFFIXES = (".p8", ".p12", ".pem", ".mobileprovision", ".keychain-db")
SELF = Path(__file__).resolve()


def _text(path: Path) -> str | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:8192]:
        return None
    return data.decode("utf-8", errors="replace")


def scan(root: Path, paths: list[str]) -> list[str]:
    findings: list[str] = []
    for relative in paths:
        path = root / relative
        if path.resolve() == SELF or not path.is_file():
            continue
        if path.suffix in CREDENTIAL_SUFFIXES:
            findings.append(f"{relative}: credential file must never be committed")
            continue
        text = _text(path)
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
    mode.add_argument("--staged", action="store_true")
    mode.add_argument("--paths", nargs="+")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.paths:
        paths = args.paths
    elif args.staged:
        paths = _git_paths(root, "diff", "--cached", "--name-only", "--diff-filter=ACMR")
    else:
        paths = _git_paths(root, "ls-files")
    findings = scan(root, paths)
    for finding in findings:
        print(f"error: {finding}", file=sys.stderr)
    if findings:
        return 1
    print(f"privacy scan: PASS ({len(paths)} path(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
