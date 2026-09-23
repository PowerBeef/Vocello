#!/usr/bin/env python3
"""Normalize Claude Code hook input for the repository shell hooks.

Bash calls expose the shell text as tool_input.command. File-edit tools expose
their target as tool_input.file_path (Edit, Write, MultiEdit) or
tool_input.notebook_path (NotebookEdit). Print one canonical absolute path per
line. The git-actions mode prints every `git commit`/`git push` with the
directory it runs in (the payload cwd, which follows an agent worktree unlike
$CLAUDE_PROJECT_DIR, then `cd`, subshells and `git -C`); git-policy prints the
first forbidden git invocation. Both use git_commands.py. Never execute or
persist tool input. This is a guardrail adapter, not a sandbox.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import git_commands  # noqa: E402

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


def git_actions(payload: dict, root: Path) -> list[str]:
    """One `commit|push<TAB>directory` line per commit or push, or `unresolved<TAB>reason`."""
    cwd = Path(payload.get("cwd") or root)
    if not cwd.is_absolute():
        raise ValueError("hook cwd must be absolute")
    tool_input = payload.get("tool_input", {})
    command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
    if not isinstance(command, str):
        return []
    lines = []
    branch_changed = ""
    for invocation in git_commands.git_invocations(command, cwd):
        if git_commands.changes_branch(invocation):
            branch_changed = branch_changed or f"git {invocation.subcommand}"
        if invocation.subcommand not in ("commit", "push"):
            continue
        if branch_changed:
            lines.append(f"unresolved\t`{branch_changed}` earlier in the command may change the branch; "
                         "run it separately first")
        elif invocation.unsafe:
            lines.append(f"unresolved\t`{invocation.unsafe}` redirects git to another repository")
        elif invocation.directory is None:
            lines.append(f"unresolved\tthe {invocation.subcommand} runs in a directory set by a variable, "
                         "pushd or ~user")
        else:
            lines.append(f"{invocation.subcommand}\t{invocation.directory}")
    return lines


def git_policy(payload: dict, root: Path) -> str:
    """`category<TAB>reason` for the first forbidden git invocation, else empty."""
    cwd = Path(payload.get("cwd") or root)
    tool_input = payload.get("tool_input", {})
    command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
    if not isinstance(command, str):
        return ""
    try:
        invocations = git_commands.git_invocations(command, cwd if cwd.is_absolute() else root)
        for invocation in invocations:
            category, reason = git_commands.policy_violation(invocation)
            if category:
                return f"{category}\t{reason}"
    except Exception as error:  # noqa: BLE001 - a parser defect must not block every Bash call
        print(f"policy guard: git parser error ignored: {error!r}", file=sys.stderr)
    return ""


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
        root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
        if mode == "paths":
            for path in edit_paths(payload, root):
                print(path)
        elif mode == "git-actions":
            for line in git_actions(payload, root):
                print(line)
        elif mode == "git-policy":
            violation = git_policy(payload, root)
            if violation:
                print(violation)
        else:
            tool_input = payload.get("tool_input", {})
            command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
            if not isinstance(command, str):
                return 0
            if mode == "policy-command":
                command = git_commands.strip_heredocs(command)[0]
            print(command)
    except (ValueError, TypeError, OSError, RuntimeError) as error:
        print(f"file guard: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
