"""`qc.py models prune`: remove the cache of models the registry no longer lists.

Under `build/cache/qc` it removes `models/<id>/` and `results/<id>/` for every id not in
`config/qc/models.json`, and the runtimes no registered model uses any more (`RETIRED_RUNTIMES`).
It never touches a registered model's files or results, the G2P text cache (`results/g2p`, the
default cache of `qc.runners.espeak_g2p`), `work/`, the kept runtimes or the pinned interpreter.

`--dry-run` lists each path with its bytes and the bytes its removal frees (files with no other
hard link); `--yes` removes them while holding `build/cache/qc/run.lock`, so it refuses while a
`qc.py run` holds it. A candidate that is a symbolic link, or that resolves outside its parent
directory, is refused, and then nothing is removed.
"""

from __future__ import annotations

import os
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from qc import runtime
from qc.store import Layout

# Results directories that are not a model id: the G2P text cache (`espeak_g2p.G2P_CACHE_DIR`).
TEXT_CACHES = frozenset({"g2p"})
# Runtimes (and their setup staging directories) that no registered model uses any more.
RETIRED_RUNTIMES = ("llamacpp", "llamacpp.staging")


class PruneError(RuntimeError):
    """A candidate is unsafe to remove, or another run holds the lock."""


@dataclass(frozen=True)
class Target:
    path: Path
    reason: str
    bytes: int
    freed: int
    refused: str | None = None


def _sizes(path: Path) -> tuple[int, int]:
    """Bytes of the regular files under `path` (links not followed, each file once), and the bytes
    removing them frees: files with no hard link outside `path`."""

    inodes: dict[tuple[int, int], list[int]] = {}  # (device, inode) -> [size, links, links seen here]
    for directory, _subdirectories, files in os.walk(path, followlinks=False):
        for name in files:
            try:
                info = os.lstat(Path(directory) / name)
            except OSError:
                continue
            if stat.S_ISREG(info.st_mode):
                entry = inodes.setdefault((info.st_dev, info.st_ino), [info.st_size, info.st_nlink, 0])
                entry[2] += 1
    total = sum(size for size, _, _ in inodes.values())
    freed = sum(size for size, links, seen in inodes.values() if seen >= links)
    return total, freed


def _target(root: Path, entry: Path, reason: str) -> Target:
    if entry.is_symlink():
        return Target(entry, reason, 0, 0, refused="a symbolic link")
    if entry.resolve().parent != root.resolve():
        return Target(entry, reason, 0, 0, refused="resolves outside its directory")
    if not entry.is_dir():
        return Target(entry, reason, 0, 0, refused="not a directory")
    total, freed = _sizes(entry)
    return Target(entry, reason, total, freed)


def targets(layout: Layout, models: Iterable[dict[str, Any]]) -> list[Target]:
    """What `prune` removes, in path order."""

    registered = {model["id"] for model in models}
    found: list[Target] = []
    for root, kind, keep in ((layout.models, "model", registered),
                             (layout.results, "results", registered | TEXT_CACHES)):
        if root.is_symlink():
            raise PruneError(f"{root} is a symbolic link")
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            if entry.name not in keep and not entry.name.startswith("."):
                found.append(_target(root, entry, f"{kind} not in the registry"))
    for name in RETIRED_RUNTIMES:
        entry = layout.runtimes / name
        if entry.exists() or entry.is_symlink():
            found.append(_target(layout.runtimes, entry, "retired runtime"))
    return found


def prune(layout: Layout, models: Iterable[dict[str, Any]], *, dry_run: bool) -> list[Target]:
    """List (`dry_run`) or remove the targets. Refuses, removing nothing, when any target is unsafe
    or, for a removal, while another `qc.py run` holds the run lock."""

    found = targets(layout, models)
    refused = [target for target in found if target.refused]
    if refused:
        raise PruneError("; ".join(f"{target.path}: {target.refused}" for target in refused))
    if dry_run or not found:
        return found
    try:
        with runtime.run_lock(layout):
            for target in targets(layout, models):  # listed again under the lock
                if target.refused:
                    raise PruneError(f"{target.path}: {target.refused}")
                shutil.rmtree(target.path)
    except runtime.LockBusy as error:
        raise PruneError(str(error)) from None
    return found


def report_lines(layout: Layout, found: list[Target], *, dry_run: bool) -> list[str]:
    verb = "would remove" if dry_run else "removed"
    lines = []
    for target in found:
        lines.append(f"{verb} {target.path.relative_to(layout.root)} ({target.reason}): "
                     f"{target.bytes} bytes, {target.freed} freed")
    total = sum(target.bytes for target in found)
    freed = sum(target.freed for target in found)
    lines.append(f"qc prune: {len(found)} paths, {total} bytes ({total / 1024**3:.2f} GB), "
                 f"{freed} bytes ({freed / 1024**3:.2f} GB) freed")
    return lines
