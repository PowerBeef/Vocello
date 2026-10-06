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

import fnmatch
import json
import os
from pathlib import Path
import re
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
    selection = Selection()
    for invocation in git_commands.git_invocations(command, cwd):
        if git_commands.changes_branch(invocation):
            branch_changed = branch_changed or f"git {invocation.subcommand}"
        if invocation.subcommand in git_commands.ADD_COMMANDS:
            selection.include(*git_commands.add_selection(invocation))
        elif invocation.subcommand in git_commands.INDEX_REWRITERS:
            selection.include("all", [])
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
        elif invocation.subcommand == "commit":
            # The index this hook sees is not all the commit will record: an earlier
            # `git add` in the same command, `-a`, `--only` or a pathspec adds to it.
            taken = Selection(selection.mode, list(selection.paths))
            taken.include(*git_commands.commit_selection(invocation))
            if taken.mode == "index":
                lines.append(f"commit\t{invocation.directory}")
            else:
                lines.append("\t".join(["commit-worktree", str(invocation.directory), taken.mode, *taken.paths]))
        else:
            lines.append(f"{invocation.subcommand}\t{invocation.directory}")
    return lines


class Selection:
    """Working-tree content a commit may record: `index` (none), literal `paths`, `tracked`
    changes (optionally with paths), or `all` changed and untracked files."""

    ORDER = ("index", "paths", "tracked", "all")

    def __init__(self, mode: str = "index", paths: list[str] | None = None) -> None:
        self.mode = mode
        self.paths = paths or []

    def include(self, mode: str, paths: list[str]) -> None:
        if self.ORDER.index(mode) > self.ORDER.index(self.mode):
            self.mode = mode
        self.paths = [] if self.mode == "all" else [*self.paths, *(p for p in paths if p not in self.paths)]


def shell_fed_bodies(command: str) -> tuple[str, list[str]]:
    """The command with heredoc bodies stripped, and the bodies fed to a shell as its script
    (`bash <<EOF`, `sh -s <<EOF`): those are commands. A heredoc on a shell that has a script
    operand, or `bash -n`, is that script's input."""
    stripped, heredocs = git_commands.strip_heredocs(command)
    bodies = []
    for prefix, body in heredocs:
        words = git_commands._tokens(prefix)
        if (words and words[0].rsplit("/", 1)[-1] in git_commands.SHELLS
                and all(word.startswith("-") and word not in ("-n", "-c") for word in words[1:])):
            bodies.append(body)
    return stripped, bodies


WRAPPERS = {"sudo", "command", "exec", "nohup", "time", "env", "builtin"}
FIND_FILTERS = {"-name", "-iname", "-path", "-ipath", "-regex", "-iregex", "-newer", "-mtime", "-mmin", "-atime",
                "-ctime", "-size", "-empty", "-user", "-group", "-perm"}
COPY_COMMANDS = {"cp", "mv", "install", "ln", "rsync", "ditto"}
BRACES = re.compile(r"^(.*)\{([^{}]*)\}(.*)$")


def _simple_commands(text: str):
    """Each simple command's words, in order; quoted words keep their spaces, comments are dropped."""
    text = git_commands.join_quoted_newlines(text.replace("$(pwd)", "$PWD"))
    for line in text.splitlines():
        tokens = git_commands._tokens(line)
        for index, token in enumerate(tokens):
            if token.startswith("#"):
                tokens = tokens[:index]
                break
        words: list[str] = []
        for token in [*tokens, ";"]:
            if token in git_commands.SEPARATORS | {"(", ")"}:
                if words:
                    yield words
                words = []
            else:
                words.append(token)


def file_policy(command: str, cwd: Path, root: Path, depth: int = 0) -> str:
    """`build` when a simple command deletes or moves away `build/` or `build/cache` (`rm` with a
    recursive flag, `find ... -delete` or `-exec rm` without a filter, `mv`), `pbxproj` when one
    copies onto the generated project file, else empty. Paths are resolved against the directory
    the command runs in, following literal `cd`s."""
    if depth > 3:
        return ""
    root_path = os.path.realpath(root)
    build = os.path.join(root_path, "build")
    cache = os.path.join(build, "cache")
    stripped, bodies = shell_fed_bodies(command)
    for body in bodies:
        violation = file_policy(body, cwd, root, depth + 1)
        if violation:
            return violation

    def resolve(base: str | None, word: str) -> str | None:
        for name, value in (("${PWD}", base), ("$PWD", base), ("${CLAUDE_PROJECT_DIR}", root_path),
                            ("$CLAUDE_PROJECT_DIR", root_path)):
            if word == name or word.startswith(name + "/"):
                if value is None:
                    return None
                word = value + word[len(name):]
        if word == "~" or word.startswith("~/"):
            word = str(Path.home()) + word[1:]
        if "$" in word or "`" in word:
            return None
        if not os.path.isabs(word):
            if base is None:
                return None
            word = os.path.join(base, word)
        return os.path.realpath(os.path.normpath(word))

    def expanded(words: list[str]) -> list[str]:
        result = []
        for word in words:
            match = BRACES.match(word)
            result.extend(f"{match.group(1)}{part}{match.group(3)}" for part in match.group(2).split(",")) \
                if match else result.append(word)
        return result

    def is_build_output(base: str | None, word: str) -> bool:
        name = os.path.basename(word.rstrip("/"))
        if any(char in name for char in "*?["):          # judge a glob by what it can reach
            parent = resolve(base, os.path.dirname(word.rstrip("/")) or ".")
            if parent is None:
                return False
            return (parent == build and fnmatch.fnmatch("cache", name)) or parent == cache \
                or parent.startswith(cache + os.sep)
        resolved = resolve(base, word)
        return resolved is not None and (resolved in (build, cache) or resolved.startswith(cache + os.sep))

    base: str | None = os.path.realpath(cwd)
    for words in _simple_commands(stripped):
        while words and (words[0].rsplit("/", 1)[-1] in WRAPPERS
                         or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0])):
            words = words[1:]
        if not words:
            continue
        name = words[0].rsplit("/", 1)[-1]
        args = git_commands._without_redirections(words[1:])
        operands = expanded([word for word in args if not word.startswith("-")])
        if name == "cd":
            base = resolve(base, operands[0]) if operands else str(Path.home())
            continue
        if name in ("pushd", "popd"):
            base = None
            continue
        if name in git_commands.SHELLS and "-c" in args and args.index("-c") + 1 < len(args):
            violation = file_policy(args[args.index("-c") + 1], Path(base) if base else cwd, root, depth + 1)
            if violation:
                return violation
            continue
        if name == "rm":
            recursive = any(word == "--recursive" or (word.startswith("-") and not word.startswith("--")
                                                      and ("r" in word or "R" in word)) for word in args)
            if recursive and any(is_build_output(base, word) for word in operands):
                return "build"
        elif name == "find":
            roots = []
            for word in args:
                if word.startswith("-") or word in ("!", "\\(", "\\)"):
                    break
                roots.append(word)
            deletes = "-delete" in args or any(
                word in ("-exec", "-execdir") and index + 1 < len(args)
                and args[index + 1].rsplit("/", 1)[-1] == "rm" for index, word in enumerate(args))
            if deletes and not any(word in FIND_FILTERS for word in args) \
                    and any(is_build_output(base, word) for word in roots):
                return "build"
        elif name == "mv" and len(operands) >= 2 and any(is_build_output(base, word) for word in operands[:-1]):
            return "build"
        if name in COPY_COMMANDS and len(operands) >= 2:
            destination = operands[-1].rstrip("/")
            if os.path.basename(destination) == "project.pbxproj" or destination.endswith(".xcodeproj"):
                return "pbxproj"
        if name == "dd" and any(word.startswith("of=") and word.endswith("project.pbxproj") for word in args):
            return "pbxproj"
    return ""


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
            if mode == "file-policy":
                cwd = Path(payload.get("cwd") or root)
                try:
                    violation = file_policy(command, cwd if cwd.is_absolute() else root, root)
                except Exception as error:  # noqa: BLE001 - a parser defect must not block every Bash call
                    print(f"policy guard: file parser error ignored: {error!r}", file=sys.stderr)
                    violation = ""
                if violation:
                    print(violation)
                return 0
            if mode == "policy-command":
                # Heredoc bodies are data, except a body fed to a shell as its script.
                command, bodies = shell_fed_bodies(command)
                for body in bodies:
                    command += "\n" + git_commands.strip_heredocs(body)[0]
            print(command)
    except (ValueError, TypeError, OSError, RuntimeError) as error:
        print(f"file guard: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
