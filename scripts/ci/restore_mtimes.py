#!/usr/bin/env python3
"""Give every tracked file the modification time of its last commit.

A fresh checkout stamps every file with "now", so a restored DerivedData cache
sees every owned source as newer than its object file and recompiles all of it.
Xcode's task signatures compare input stat data, so setting mtimes from git
history makes an unchanged file look unchanged. One `git log` walk covers the
whole tree; the first commit that names a path is its latest change.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time


def main() -> int:
    started = time.monotonic()
    tracked = set(
        subprocess.run(["git", "ls-files", "-z"], capture_output=True, check=True)
        .stdout.decode("utf-8", "surrogateescape").split("\0")
    )
    tracked.discard("")
    log = subprocess.run(
        ["git", "log", "--format=%x00%ct", "--name-only", "--no-renames"],
        capture_output=True, check=True,
    ).stdout.decode("utf-8", "surrogateescape")
    stamped: dict[str, int] = {}
    timestamp = 0
    for line in log.splitlines():
        if line.startswith("\0"):
            timestamp = int(line[1:])
            continue
        if line and line in tracked and line not in stamped:
            stamped[line] = timestamp
            if len(stamped) == len(tracked):
                break
    touched = 0
    for path, when in stamped.items():
        try:
            os.utime(path, (when, when), follow_symlinks=False)
            touched += 1
        except OSError:
            continue
    print(f"restore_mtimes: {touched}/{len(tracked)} tracked files stamped in {time.monotonic() - started:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
