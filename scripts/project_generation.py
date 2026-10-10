#!/usr/bin/env python3
"""Shared XcodeGen freshness: specifications, renderers, templates and path membership.

Source/resource bytes are deliberately excluded: Xcode's incremental build owns
content changes. Membership is conservative (including excluded non-hidden files),
so an exclusion can cause extra regeneration but cannot hide an added source.
No third-party YAML dependency or Xcode invocation is needed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAMP_NAME = "project-generation.sha256"
GENERATORS = ("scripts/project_generation.py", "scripts/generate_cli_scheme.py", "scripts/generate_ios_logic_scheme.py")
OUTPUTS = ("QwenVoice.xcodeproj/project.pbxproj",
           "QwenVoice.xcodeproj/xcshareddata/xcschemes/VocelloCLI.xcscheme",
           "QwenVoice.xcodeproj/xcshareddata/xcschemes/VocelloiOSLogic.xcscheme")


def _scalar(value: str) -> str:
    value = value.strip()
    if value.startswith('"'):
        return json.JSONDecoder().raw_decode(value)[0]
    if value.startswith("'"):
        match = re.match(r"'((?:[^']|'')*)'", value)
        if not match:
            raise ValueError("unterminated single-quoted path in project spec")
        return match[1].replace("''", "'")
    return value.split(" #", 1)[0].strip()


def _entries(text: str, sections: tuple[str, ...]) -> list[str]:
    """Read block-list paths in XcodeGen sources/resources/include sections."""
    result: list[str] = []
    active: int | None = None
    list_indent: int | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        if active is not None and indent <= active:
            active = None
            list_indent = None
        match = re.match(r"([\w]+):\s*(.*)$", line)
        if match and match[1] in sections:
            if match[2] and match[2] != "[]":
                if match[2].startswith(("[", "{", "*", "&", "!")):
                    raise ValueError(f"use block-list paths for {match[1]} in project specs")
                result.append(_scalar(match[2]))
            active = indent
            list_indent = None
            continue
        if active is not None:
            match = re.match(r"-\s+(?:path:\s*)?(.+)$", line)
            if match:
                if list_indent is None:
                    list_indent = indent
                if indent == list_indent:
                    if match[1].startswith(("[", "{", "*", "&", "!")):
                        raise ValueError("use scalar or path: entries in project spec lists")
                    result.append(_scalar(match[1]))
    return result


def inputs(root: Path) -> dict:
    root = root.resolve()
    specs: set[Path] = set()
    source_paths: set[Path] = set()

    def read_spec(path: Path) -> None:
        path = path.resolve()
        path.relative_to(root)
        if path in specs:
            return
        specs.add(path)
        text = path.read_text(encoding="utf-8")
        for relative in _entries(text, ("include",)):
            read_spec(path.parent / relative)
        for relative in _entries(text, ("sources", "resources")):
            source = (path.parent / relative).resolve()
            source.relative_to(root)
            source_paths.add(source)

    read_spec(root / "project.yml")
    content_paths = specs | {root / p for p in GENERATORS} | set((root / "config/xcode-schemes").glob("*.template"))
    content = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
               for p in sorted(content_paths)}
    membership: set[str] = set()
    for path in sorted(source_paths):
        relative = path.relative_to(root).as_posix()
        membership.add(("directory:" if path.is_dir() else "file:" if path.exists() else "missing:") + relative)
        if path.is_dir():
            for directory, children, files in os.walk(path):
                children[:] = sorted(name for name in children if not name.startswith("."))
                for name in children + sorted(name for name in files if not name.startswith(".")):
                    child = Path(directory) / name
                    membership.add(("directory:" if child.is_dir() else "file:") + child.relative_to(root).as_posix())
    return {"version": 1, "content": content, "membership": sorted(membership),
            "sourceRoots": sorted(path.relative_to(root).as_posix() for path in source_paths)}


def relevant_paths(paths: list[str], root: Path = ROOT) -> bool:
    inventory = inputs(root)
    return any(path in inventory["content"] or path.startswith("config/xcode-schemes/")
               or any(path == source or path.startswith(source + "/") for source in inventory["sourceRoots"])
               for path in paths)


def signature(root: Path = ROOT) -> str:
    return hashlib.sha256(json.dumps(inputs(root), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def stamp_path(root: Path = ROOT) -> Path:
    packages = os.environ.get("QVOICE_XCODE_SOURCE_PACKAGES")
    if not packages:
        policy = json.loads((root / "config/build-output-policy.json").read_text(encoding="utf-8"))
        packages = next(entry["path"] for entry in policy["entries"] if entry["id"] == "xcode-source-packages")
    return root / packages / ".qwenvoice-cache" / STAMP_NAME


def status(root: Path = ROOT, stamp: Path | None = None) -> dict:
    current = signature(root)
    stamp = stamp or stamp_path(root)
    cached = stamp.read_text(encoding="utf-8").strip() if stamp.is_file() else None
    missing = [relative for relative in OUTPUTS if not (root / relative).is_file()]
    return {"signature": current, "cachedSignature": cached, "stamp": os.fspath(stamp),
            "missingOutputs": missing, "needsRegeneration": current != cached or bool(missing)}


def record(root: Path, stamp: Path, expected_signature: str | None = None) -> None:
    missing = [relative for relative in OUTPUTS if not (root / relative).is_file()]
    if missing:
        raise ValueError(f"cannot record generation with missing outputs: {', '.join(missing)}")
    current = signature(root)
    if expected_signature is not None and current != expected_signature:
        raise ValueError("generation inputs changed while XcodeGen ran; no freshness stamp was published")
    stamp.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=stamp.name + ".next.", dir=stamp.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(current + "\n")
        os.replace(temporary, stamp)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("digest", "status", "record", "check"))
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--stamp", type=Path)
    parser.add_argument("--expected-signature", help="record only if inputs still match this pre-generation digest")
    args = parser.parse_args(argv)
    try:
        if args.command == "digest":
            print(signature(args.root))
        elif args.command == "record":
            record(args.root, args.stamp or stamp_path(args.root), args.expected_signature)
        else:
            result = status(args.root, args.stamp)
            if args.command == "check":
                return int(result["needsRegeneration"])
            print(json.dumps(result, indent=2))
    except (OSError, ValueError, KeyError, StopIteration) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
