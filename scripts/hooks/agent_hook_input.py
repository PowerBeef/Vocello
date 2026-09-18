#!/usr/bin/env python3
"""Normalize Claude edits and Codex apply_patch input for the shared shell hooks.

Codex exposes shell and patch text as tool_input.command. Claude exposes edit
paths as tool_input.file_path (notebook_path for NotebookEdit). Print one
canonical absolute path per line, including both ends of moves. Never execute
or persist tool input. This is a guardrail adapter, not a shell/patch sandbox.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys


def edit_paths(payload: dict, root: Path) -> list[str]:
    tool_input = payload.get("tool_input", {})
    if not isinstance(tool_input, dict):
        raise ValueError("file-edit input must be an object")
    paths = []
    if payload.get("tool_name") == "apply_patch":
        patch = tool_input.get("command")
        if not isinstance(patch, str):
            raise ValueError("apply_patch input needs tool_input.command")
        lines = patch.strip().splitlines()
        if not lines or lines[0] != "*** Begin Patch" or lines[-1] != "*** End Patch":
            raise ValueError("cannot inspect malformed apply_patch boundaries")
        for line in lines[1:-1]:
            match = re.fullmatch(r"\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)", line)
            if match:
                paths.append(match[1])
        if not paths:
            raise ValueError("apply_patch contains no inspectable file paths")
    else:
        path = tool_input.get("file_path") or tool_input.get("notebook_path")
        if path:
            paths.append(path)
    cwd = Path(payload.get("cwd") or root)
    if not cwd.is_absolute():
        raise ValueError("hook cwd must be absolute")
    normalized = []
    for value in paths:
        if not isinstance(value, str) or any(c in value for c in "\n\r\0"):
            raise ValueError("file path cannot be represented safely")
        path = Path(value)
        normalized.append(str((path if path.is_absolute() else cwd / path).resolve()))
    return list(dict.fromkeys(normalized))


def main() -> int:
    mode = sys.argv[1]
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("hook payload must be an object")
    except (ValueError, TypeError):
        # Preserve the historical shell hooks' permissive handling of absent
        # input. File guards must not silently skip an unreadable edit.
        if mode != "paths":
            return 0
        print("file guard: cannot inspect malformed hook input", file=sys.stderr)
        return 2
    try:
        if mode == "paths":
            root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
            for path in edit_paths(payload, root):
                print(path)
        else:
            tool_input = payload.get("tool_input", {})
            command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
            if not isinstance(command, str):
                return 0
            if mode == "policy-command":
                command = re.sub(
                    r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?[^\n]*\n.*?\n[ \t]*\1[ \t]*(?=\n|$)",
                    "<<HEREDOC", command, flags=re.S,
                )
            print(command)
    except (ValueError, TypeError, OSError, RuntimeError) as error:
        print(f"file guard: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
