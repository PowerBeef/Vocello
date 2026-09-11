#!/usr/bin/env python3
"""Classify the paths a push changed into CI lanes.

Writes `<lane>=true|false` for the lanes swift, ios, python, research, website
and workflows to $GITHUB_OUTPUT (or stdout when unset). An empty or unknowable
diff (first push, dispatch, rewritten history) enables every lane, so routing
can only ever skip work, never invent a pass.

Usage:
  classify_changes.py                      # diff from $BEFORE_SHA..$HEAD_SHA (GitHub push event)
  classify_changes.py --paths a b c        # classify explicit paths (tests, local use)
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import subprocess
import sys

LANES = ("swift", "ios", "python", "research", "website", "workflows")

# Owned sources that no iOS target compiles. Anything else under Sources/ or
# Tests/ can change the device build.
MACOS_ONLY = (
    "Sources/Views/*",
    "Sources/ViewModels/*",
    "Sources/Models/*",
    "Sources/Services/*",
    "Sources/App/*",
    "Sources/VocelloCLI/*",
    "Sources/QwenVoiceNative/*",
    "Sources/QwenVoiceEngineService/*",
    "Sources/QwenVoiceEngineSupport/*",
    "Tests/VocelloMacUITests/*",
    "Tests/VocelloEngineIntegrationTests/*",
)

SWIFT = ("Sources/*", "Tests/*", "Packages/*", "project.yml", "*Package.resolved",
         "QwenVoice.xcodeproj/*", "config/*", "scripts/*", "benchmarks/*")
IOS_ALWAYS = ("project.yml", "*Package.resolved", "Packages/*", "Sources/Resources/*",
              "scripts/build_foundation_targets.sh", "scripts/regenerate_project.sh", "scripts/lib/*",
              "config/apple-platform-capability-matrix.json", "config/build-output-policy.json")
PYTHON = ("scripts/*", "config/*", "benchmarks/*", "Sources/Resources/*")
RESEARCH_PREFIXES = (
    "delivery_", "prosody_", "analyze_", "audio_", "ios_control_audit", "ios_startup_reliability",
    "check_language", "clone_", "emotion_", "mos_", "bench_", "run_local_delivery", "qualify_delivery",
    "prepare_delivery", "build_emotion", "separability", "characterization", "voice_identity",
    "language_bench", "angry_bilingual", "custom_delivery", "secret_sauce", "sampling_promotion",
)
RESEARCH_CONFIG = ("delivery-", "prosody-", "ios-control-audit", "ios-startup-reliability", "language-bench",
                   "voice-identity", "characterization-fixtures", "audio-cadence", "ui-perf-thresholds")


def _match(path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(path, p) for p in patterns)


def _is_research(path: str) -> bool:
    name = os.path.basename(path)
    if path.startswith("scripts/tests/"):
        name = name.removeprefix("test_")
    if path.startswith("scripts/") and any(name.startswith(p) for p in RESEARCH_PREFIXES):
        return True
    return path.startswith("config/") and any(name.startswith(p) for p in RESEARCH_CONFIG)


def classify(paths: list[str]) -> dict[str, bool]:
    if not paths:
        return {lane: True for lane in LANES}
    lanes = {lane: False for lane in LANES}
    for path in paths:
        if path.startswith(".github/"):
            lanes["workflows"] = True
            lanes["swift"] = lanes["ios"] = lanes["python"] = True
        if path.startswith("website/"):
            lanes["website"] = True
        if _match(path, SWIFT):
            lanes["swift"] = True
        if _match(path, PYTHON):
            lanes["python"] = True
        if _match(path, IOS_ALWAYS):
            lanes["ios"] = True
        elif (path.startswith("Sources/") or path.startswith("Tests/")) and not _match(path, MACOS_ONLY):
            lanes["ios"] = True
        if _is_research(path):
            lanes["research"] = True
    return lanes


def changed_paths() -> list[str] | None:
    """Paths from the push event, or None when the range cannot be trusted."""
    before = os.environ.get("BEFORE_SHA", "")
    head = os.environ.get("HEAD_SHA", "")
    if os.environ.get("EVENT_NAME") != "push" or not before or not head or set(before) == {"0"}:
        return None
    kind = subprocess.run(["git", "cat-file", "-t", before], capture_output=True, text=True).stdout.strip()
    if kind != "commit":
        return None
    diff = subprocess.run(["git", "diff", "--name-only", f"{before}..{head}"],
                          capture_output=True, text=True, check=True).stdout
    return [line for line in diff.splitlines() if line]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--paths", nargs="*", help="classify these paths instead of the push diff")
    args = parser.parse_args(argv)
    paths = args.paths if args.paths is not None else changed_paths()
    lanes = classify(paths or [])
    lines = [f"{lane}={'true' if on else 'false'}" for lane, on in lanes.items()]
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    reason = "empty or unknowable diff, every lane runs" if not paths else f"{len(paths)} changed path(s)"
    print(f"routing ({reason}): " + " ".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
