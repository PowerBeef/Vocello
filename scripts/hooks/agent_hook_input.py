#!/usr/bin/env python3
"""Normalize Claude Code hook input for the repository shell hooks.

Bash calls expose the shell text as tool_input.command. File-edit tools expose
their target as tool_input.file_path (Edit, Write, MultiEdit) or
tool_input.notebook_path (NotebookEdit). Print one canonical absolute path per
line. Never execute or persist tool input. This is a guardrail adapter, not a
sandbox.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys

EDIT_PATH_KEYS = {
    "Edit": "file_path",
    "Write": "file_path",
    "MultiEdit": "file_path",
    "NotebookEdit": "notebook_path",
}


def edit_paths(payload: dict, root: Path) -> list[str]:
    tool_input = payload.get("tool_input", {})
    if not isinstance(tool_input, dict):
        raise ValueError("file-edit input must be an object")
    tool_name = str(payload.get("tool_name"))
    key = EDIT_PATH_KEYS.get(tool_name)
    if key is None:
        raise ValueError(f"cannot inspect tool {tool_name!r}")
    value = tool_input.get(key)
    if not isinstance(value, str) or not value or any(c in value for c in "\n\r\0"):
        raise ValueError(f"{tool_name} input needs a representable tool_input.{key}")
    cwd = Path(payload.get("cwd") or root)
    if not cwd.is_absolute():
        raise ValueError("hook cwd must be absolute")
    path = Path(value)
    return [str((path if path.is_absolute() else cwd / path).resolve())]


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
