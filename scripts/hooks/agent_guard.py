#!/usr/bin/env python3
"""Claude Code PreToolUse guard for subagents (CLAUDE.md: Agents).

Only a subagent's hook input carries `agent_id`; the lead's never does, so lead calls
pass straight through. A subagent may read, edit its assigned files, run the
deterministic Python and lint checks and commit in its own worktree. It never pushes,
commits in the main checkout, runs native builds, tests, devices, models or measured
lanes, or edits the roadmap or the checkpoint; the lane scripts' usage text and the
reporting `xcodebuild -version` and `-showsdks` stay open (`-list` can resolve
packages), but sourcing a lane script or a `scripts/lib` library does not: it leaves
the lane's functions callable by bare name. Exit 2 with the reason on stderr blocks the call. Parser defects fail open,
like the policy guard; the lead still integrates and reviews every agent commit. Hooks run the host's bare
`python3`, often the macOS system Python 3.9: keep this file importable there. Never
execute or persist input.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agent_hook_input as adapter  # noqa: E402
import git_commands  # noqa: E402

PROTECTED_FILES = {"config/roadmap.json", "docs/development-progress.md"}
# Repository scripts that build, test, drive devices or run models or measured lanes.
LANE_SCRIPTS = {"macos_test.sh", "ui_test.sh", "ios_device.sh", "build.sh", "build_foundation_targets.sh",
                "build_ui_test_bundles.sh", "dead_code_report.sh", "release.sh", "create_dmg.sh",
                "clean_build_caches.sh", "install_pinned_tools.sh", "publish_benchmark_history.py"}
DEV_NATIVE_VERBS = {"build", "run", "ios", "test", "ci"}
# Usage text only: these scripts print it and exit before any lock, build, device or model work.
HELP_SCRIPTS = {"macos_test.sh", "ui_test.sh", "ios_device.sh", "dead_code_report.sh", "dev.sh"}
HELP_WORDS = {"help", "--help", "-h"}
# `xcodebuild` actions that only report the version, the SDKs or a project's targets and schemes.
# `-list` is not one of them: on a project with packages it can resolve them outside the native lock
# and the owned caches.
XCODEBUILD_REPORTS = {"-version", "-showsdks"}
XCODEBUILD_REPORT_VALUES = {"-sdk"}
QC_MODEL_VERBS = {"run", "language-bench"}
CLI_MODEL_VERBS = {"generate", "gen", "custom", "design", "clone", "batch", "bench", "benchmark"}
PYTHONS = re.compile(r"^python(3(\.\d+)?)?$")
RULE = "CLAUDE.md: Agents"


def _script(word: str) -> str:
    """The repository script a word names (`scripts/x.sh`, `./scripts/x.sh`, absolute), else ''."""
    parts = word.split("/")
    return parts[-1] if len(parts) >= 2 and parts[-2] == "scripts" else ""


def _sources_lane_code(word: str) -> bool:
    """A lane script or `scripts/lib` shell library: sourcing one defines `build`, `xcb_run` and the
    rest in the caller's shell, where a later bare call runs them past every check here."""
    parts = word.split("/")
    return _script(word) in LANE_SCRIPTS | HELP_SCRIPTS or (
        len(parts) >= 3 and parts[-3:-1] == ["scripts", "lib"] and word.endswith(".sh"))


def _xcodebuild_reports_only(args: list[str]) -> bool:
    """`xcodebuild -version [-sdk S]`, `-showsdks [-json]`: no action runs."""
    reports = False
    index = 0
    while index < len(args):
        word = args[index]
        if word in XCODEBUILD_REPORTS:
            reports = True
        elif word in XCODEBUILD_REPORT_VALUES and index + 1 < len(args):
            index += 1                                  # the option's value, never an action
        elif word != "-json":
            return False
        index += 1
    return reports


def command_violation(command: str, depth: int = 0) -> str:
    """Why a subagent may not run this shell text, else ''."""
    if depth > 3:
        return ""
    stripped, bodies = adapter.shell_fed_bodies(command)
    for body in bodies:
        reason = command_violation(body, depth + 1)
        if reason:
            return reason
    for words in adapter._simple_commands(stripped):
        while words and (words[0].rsplit("/", 1)[-1] in adapter.WRAPPERS | git_commands.TRANSPARENT_PREFIXES
                         or git_commands.ASSIGNMENT.match(words[0])):
            words = words[1:]
        if not words:
            continue
        name = words[0].rsplit("/", 1)[-1]
        args = git_commands._without_redirections(words[1:])
        operands = [word for word in args if not word.startswith("-")]
        if name in git_commands.SHELLS:
            if "-c" in args and args.index("-c") + 1 < len(args):
                reason = command_violation(args[args.index("-c") + 1], depth + 1)
                if reason:
                    return reason
                continue
            if not operands:
                continue
            words = args[args.index(operands[0]):]       # the script and all its arguments, flags included
            name, args = operands[0].rsplit("/", 1)[-1], words[1:]
            operands = [word for word in args if not word.startswith("-")]
        elif operands and (PYTHONS.match(name) or (words[0].lstrip('"').startswith(("$(", "`"))
                                                   and "python" in words[0])):
            # `python3 scripts/x.py ...` or `"$(python3 scripts/select_python.py)" scripts/x.py ...`
            words = args[args.index(operands[0]):]
            name, args = operands[0].rsplit("/", 1)[-1], words[1:]
            operands = [word for word in args if not word.startswith("-")]
        script = _script(words[0])
        verb = operands[0] if operands else ""
        if name in ("source", ".") and operands and _sources_lane_code(operands[0]):
            return f"sourcing `{operands[0]}` defines its build, test and device functions in this shell"
        if name == "xcb_run":
            return "`xcb_run` is a native build"
        if script in HELP_SCRIPTS and args[:1] and args[0] in HELP_WORDS:
            continue
        if script in LANE_SCRIPTS:
            return f"`{script}` builds, tests, drives devices or runs models or measured lanes"
        if script == "dev.sh" and (verb in DEV_NATIVE_VERBS or (verb == "check" and "--dry-run" not in args)):
            return f"`scripts/dev.sh {verb}` can run native builds or tests"
        if script == "qc.py" and verb in QC_MODEL_VERBS:
            return f"`scripts/qc.py {verb}` runs scoring models"
        if name == "xcodebuild" and not _xcodebuild_reports_only(args):
            return "`xcodebuild` is a native build"
        if name == "xcrun" and operands:
            tool = operands[0]
            if tool == "xcodebuild" and _xcodebuild_reports_only(args[args.index(tool) + 1:]):
                continue
            if tool in ("xcodebuild", "xctest"):
                return f"`xcrun {tool}` is a native build or test"
            if tool == "devicectl" and operands[1:2] != ["list"]:
                return "`xcrun devicectl` drives a device"
        if name == "swift" and verb in ("build", "test", "run"):
            return f"`swift {verb}` is a native build or test"
        if name == "vocello" and (verb in CLI_MODEL_VERBS or operands[:2] == ["models", "install"]):
            return f"`vocello {' '.join(operands[:2]) if verb == 'models' else verb}` loads or downloads models"
    return ""


def _is_main_checkout(directory: Path) -> bool:
    def metadata(flag: str) -> str:
        return subprocess.check_output(["git", "-C", str(directory), "rev-parse", "--path-format=absolute", flag],
                                       text=True, stderr=subprocess.DEVNULL).strip()
    return Path(metadata("--absolute-git-dir")).resolve() == Path(metadata("--git-common-dir")).resolve()


def git_violation(command: str, cwd: Path) -> str:
    for invocation in git_commands.git_invocations(command, cwd):
        if invocation.subcommand == "push":
            return "agents never push; the lead integrates and pushes main"
        if invocation.subcommand == "commit" and invocation.directory is not None:
            try:
                in_main = _is_main_checkout(invocation.directory)
            except (OSError, subprocess.SubprocessError):
                continue  # The commit lint judges unresolvable targets.
            if in_main:
                return "agents commit only in their own worktree, never in the main checkout"
    return ""


def edit_violation(payload: dict, root: Path) -> str:
    for path in adapter.edit_paths(payload, root):
        parent = Path(path).parent
        while not parent.exists() and parent != parent.parent:
            parent = parent.parent
        relative = os.path.relpath(path, adapter.checkout_root(parent, root))
        if relative in PROTECTED_FILES:
            return f"agents never edit `{relative}`; the lead owns the roadmap and checkpoint"
    return ""


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(payload, dict) or not payload.get("agent_id"):
        return 0
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
    cwd = Path(payload.get("cwd") or root)
    tool_input = payload.get("tool_input")
    try:
        if payload.get("tool_name") == "Bash":
            command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
            if not isinstance(command, str):
                return 0
            reason = git_violation(command, cwd if cwd.is_absolute() else root) or command_violation(command)
        elif payload.get("tool_name") in adapter.EDIT_PATH_KEYS:
            reason = edit_violation(payload, root)
        else:
            return 0
    except Exception as error:  # noqa: BLE001 - a parser defect must not block every agent call
        print(f"agent guard: parser error ignored: {error!r}", file=sys.stderr)
        return 0
    if reason:
        print(f"agent guard: BLOCKED — {reason} ({RULE}).", file=sys.stderr)
        print("Report back to the lead, which owns native builds, measured lanes, pushes, the roadmap and the "
              "checkpoint.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
