#!/usr/bin/env python3
"""Which newer build settings the selected Xcode defines, for the nightly summary.

The 2026-10-18 workflow audit (P1-14) plans strictness and build-speed settings that
exist in the local Xcode 27.1 but may not in CI's pinned Xcode; Xcode ignores an
unknown setting without a warning, so a setting it lacks would silently do nothing.
This reads the build-system specifications inside the selected Xcode and reports each
setting as defined or absent. Report-only.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import re
import subprocess
import sys

SETTINGS = (
    "SWIFT_WARNINGS_AS_ERRORS_GROUPS",
    "SWIFT_WARNINGS_AS_WARNINGS_GROUPS",
    "SWIFT_STRICT_MEMORY_SAFETY",
    "SWIFT_UPCOMING_FEATURE_INFER_ISOLATED_CONFORMANCES",
    "SWIFT_UPCOMING_FEATURE_NONISOLATED_NONSENDING_BY_DEFAULT",
    "SWIFT_UPCOMING_FEATURE_MEMBER_IMPORT_VISIBILITY",
    "SWIFT_APPROACHABLE_CONCURRENCY",
    "SWIFT_DEFAULT_ACTOR_ISOLATION",
    "COMPILATION_CACHE_ENABLE_CACHING",
    "ENABLE_ENHANCED_SECURITY",
    "DEAD_CODE_STRIPPING",
    "ENABLE_USER_SCRIPT_SANDBOXING",
)


def spec_texts(developer_dir: pathlib.Path) -> str:
    """Concatenated .xcspec contents under the Xcode that owns developer_dir."""
    app = developer_dir.parents[1] if developer_dir.name == "Developer" else developer_dir
    texts = []
    for spec in app.rglob("*.xcspec"):
        try:
            texts.append(spec.read_text(errors="replace"))
        except OSError:
            continue
    return "\n".join(texts)


def probe(text: str, settings: tuple[str, ...] = SETTINGS) -> dict[str, bool]:
    return {name: re.search(rf"\b{re.escape(name)}\b", text) is not None for name in settings}


def render(version: str, found: dict[str, bool]) -> str:
    rows = [f"### Build settings defined by {version}", "", "| Setting | Defined |", "|---|---|"]
    rows += [f"| `{name}` | {'yes' if ok else '**no**'} |" for name, ok in found.items()]
    return "\n".join(rows) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--developer-dir", type=pathlib.Path,
                        help="defaults to `xcode-select -p`")
    args = parser.parse_args(argv)
    developer_dir = args.developer_dir or pathlib.Path(
        subprocess.run(["xcode-select", "-p"], capture_output=True, text=True, check=True).stdout.strip())
    version = subprocess.run(["xcodebuild", "-version"], capture_output=True, text=True,
                             check=False).stdout.splitlines()[:1] or ["the selected Xcode"]
    text = render(version[0], probe(spec_texts(developer_dir)))
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(text)
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
