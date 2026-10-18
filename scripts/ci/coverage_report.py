#!/usr/bin/env python3
"""Line coverage of the files the 2026-10-18 workflow audit watches, for the nightly summary.

Reads the llvm-cov export `scripts/macos_test.sh test --coverage` writes
(coverage.json) and prints a Markdown table: the total over repository sources and
each watched file. Report-only (audit P1-14): coverage is never a verdict input.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

# The engine and delivery files where the 2026-10-16 engine audit found defects behind
# thin or indirect tests (audit A-02).
WATCHED = (
    "Sources/QwenVoiceCore/NativeEngineRuntime.swift",
    "Sources/QwenVoiceCore/MLXModelLoadCoordinator.swift",
    "Sources/QwenVoiceCore/GenerationOutputAdapter.swift",
    "Sources/QwenVoiceCore/MLXTTSEngine.swift",
    "Sources/QwenVoiceCore/HuggingFaceDownloader.swift",
    "Sources/QwenVoiceCore/SharedModelComponentStore.swift",
    "Packages/VocelloQwen3Core/Sources/VocelloQwen3Core/Engine.swift",
    "Packages/VocelloQwen3Core/Sources/VocelloQwen3Core/LoadedModel.swift",
)


def summarize(data: dict, root: str) -> tuple[tuple[int, int], dict[str, tuple[int, int]]]:
    prefix = root.rstrip("/") + "/"
    total = [0, 0]
    files: dict[str, tuple[int, int]] = {}
    for item in data.get("data", []):
        for entry in item.get("files", []):
            name = entry.get("filename", "")
            if not name.startswith(prefix):
                continue
            relative = name[len(prefix):]
            if relative.startswith("build/"):
                continue
            lines = entry.get("summary", {}).get("lines", {})
            covered, count = int(lines.get("covered", 0)), int(lines.get("count", 0))
            previous = files.get(relative, (0, 0))
            # A file compiled into two binaries appears twice; keep the better-covered copy.
            files[relative] = max(previous, (covered, count))
    for covered, count in files.values():
        total[0] += covered
        total[1] += count
    return (total[0], total[1]), files


def percent(covered: int, count: int) -> str:
    return f"{100.0 * covered / count:.1f}%" if count else "n/a"


def render(data: dict, root: str) -> str:
    (covered, count), files = summarize(data, root)
    rows = ["### Nightly line coverage (report-only)", "",
            "| File | Lines | Coverage |", "|---|---|---|",
            f"| All repository sources | {covered}/{count} | {percent(covered, count)} |"]
    for path in WATCHED:
        if path in files:
            c, n = files[path]
            rows.append(f"| `{path}` | {c}/{n} | {percent(c, n)} |")
        else:
            rows.append(f"| `{path}` | not instrumented | n/a |")
    return "\n".join(rows) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("coverage_json", type=pathlib.Path)
    parser.add_argument("--root", default=os.getcwd(), help="repository root the export's paths start with")
    args = parser.parse_args(argv)
    text = render(json.loads(args.coverage_json.read_text()), args.root)
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(text)
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
