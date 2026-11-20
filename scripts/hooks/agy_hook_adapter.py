#!/usr/bin/env python3
"""Antigravity lifecycle hook adapter for Vocello repository guards.

Translates Antigravity camelCase hook JSON on stdin into the repository's existing
guard scripts and emits Antigravity JSON decisions on stdout:
  - session-start -> {"injectSteps": [{"systemMessage": {"systemMessage": ...}}]}
  - pre-command   -> {"decision": "allow"|"ask"|"deny", "reason": ...}
  - pre-edit      -> {"decision": "allow"|"deny", "reason": ...}
  - pre-mcp       -> {"decision": "allow"|"ask"|"deny", "reason": ...}

Hooks run under the host's bare `python3` (often macOS system Python 3.9): keep this
module and its imports compatible with Python 3.9. Never execute or persist tool input.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys

HOOK_DIR = Path(__file__).resolve().parent
ROOT = HOOK_DIR.parents[1]
sys.path.insert(0, str(HOOK_DIR))
import agent_hook_input as adapter  # noqa: E402
import connector_write_guard  # noqa: E402
import git_commands  # noqa: E402

SIM_TOOL_PATTERN = re.compile(
    r"(?:^|__)(?:.*_sims?(?:_[^_].*)?|.*_sim" + r"ulator.*|sim" + r"ulator_.*|simctl.*)(?:$|__)"
)
MOBILEBUILD_DENY_TOOLS = frozenset({
    "screenshot", "snapshot_ui", "clean", "tap", "swipe", "long_press", "touch",
    "type_text", "button", "gesture", "key_press", "key_sequence",
    "build_macos", "build_run_macos", "test_macos", "launch_mac_app", "stop_mac_app",
    "build_device", "test_device", "install_app_device", "launch_app_device", "stop_app_device",
    "attach_lldb", "detach_lldb", "manage-workflows",
})
AXIOM_DENY_AGENTS = frozenset({
    "sim" + "ulator-tester",
    "test-runner",
    "test-debugger",
})
HF_ASK_SUBCOMMANDS = frozenset({
    "download", "upload", "repos", "cp", "sync", "buckets", "jobs", "sandbox",
    "endpoints", "webhooks", "discussions", "collections", "spaces",
    "extensions", "skills", "update",
})
HF_AUTH_ASK = frozenset({"login", "logout", "switch"})
HF_CACHE_ASK = frozenset({"prune", "rm"})
GH_RELEASE_DENY = frozenset({"create", "edit", "delete", "upload"})
GH_PR_ASK = frozenset({"create", "merge"})
GH_API_WRITE_METHODS = frozenset({"POST", "PATCH", "PUT", "DELETE"})
PYTHONS = re.compile(r"^python(3(\.\d+)?)?$")

AGENT_RULES = (
    "Vocello agent rules: commit only on your own worktree's branch (subagent-*, swarm-* or worktree-*); "
    "never push; run no native builds, devices, models or measured lanes (the lead owns them); "
    "never edit config/roadmap.json or docs/development-progress.md."
)
SIDE_SESSION = (
    "This session works in a linked worktree, so it is a worker checkout, not the lead, and the "
    "agent guard holds it to the agent rules. "
)


def _root() -> Path:
    override = os.environ.get("VOCELLO_PROJECT_ROOT")
    return Path(override).resolve() if override else ROOT


def _resolve_cwd(payload: dict, root: Path) -> Path:
    raw = payload.get("cwd")
    if isinstance(raw, str) and raw:
        candidate = Path(raw)
        if candidate.is_absolute():
            return candidate
    workspaces = payload.get("workspacePaths")
    if isinstance(workspaces, list) and workspaces and isinstance(workspaces[0], str):
        candidate = Path(workspaces[0])
        if candidate.is_absolute():
            return candidate
    return root


def _norm_rel(word: str) -> str:
    cleaned = word.strip("'\"")
    if not cleaned:
        return ""
    norm = os.path.normpath(cleaned)
    if norm.startswith("./"):
        norm = norm[2:]
    return norm


def _matches_repo_script(word: str, target_rel: str) -> bool:
    norm = _norm_rel(word)
    return norm == target_rel or norm.endswith("/" + target_rel)


def _run_guard(script_name: str, payload: dict, cwd: Path, root: Path, timeout: int = 12) -> subprocess.CompletedProcess:
    script = HOOK_DIR / script_name
    interpreter = "python3" if script_name.endswith(".py") else "bash"
    env = dict(os.environ, VOCELLO_PROJECT_ROOT=str(root))
    return subprocess.run(
        [interpreter, str(script)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=str(cwd) if cwd.is_dir() else str(root),
        timeout=timeout,
        env=env,
        check=False,
    )


def _git_subcommand_and_args(args: list[str]) -> tuple[str, list[str]]:
    index = 0
    while index < len(args) and args[index].startswith("-"):
        index += 2 if args[index] in git_commands.GLOBAL_VALUE_OPTIONS else 1
    if index >= len(args):
        return "", []
    return args[index], args[index + 1:]


def command_policy_decision(command: str, depth: int = 0) -> tuple[str, str]:
    """Return ('deny'|'ask'|'allow', reason) for authorization-bound shell commands."""
    if depth > 3 or not command.strip():
        return "allow", ""
    stripped, bodies = adapter.shell_fed_bodies(command)
    ask_reason = ""
    for body in bodies:
        decision, reason = command_policy_decision(body, depth + 1)
        if decision == "deny":
            return "deny", reason
        if decision == "ask" and not ask_reason:
            ask_reason = reason

    for words in adapter._simple_commands(stripped):
        while words and (
            words[0].rsplit("/", 1)[-1] in adapter.WRAPPERS | git_commands.TRANSPARENT_PREFIXES
            or git_commands.ASSIGNMENT.match(words[0])
        ):
            if words[0].rsplit("/", 1)[-1] == "sudo" and not ask_reason:
                ask_reason = "Privileged command (`sudo`) requires explicit maintainer confirmation."
            words = words[1:]
        if not words:
            continue
        raw_head = words[0]
        name = raw_head.rsplit("/", 1)[-1]
        args = git_commands._without_redirections(words[1:])
        operands = [w for w in args if not w.startswith("-")]

        if name in git_commands.SHELLS:
            script_idx = adapter._shell_script_index(args)
            if script_idx >= 0:
                decision, reason = command_policy_decision(args[script_idx], depth + 1)
                if decision == "deny":
                    return "deny", reason
                if decision == "ask" and not ask_reason:
                    ask_reason = reason
                continue
            if not operands:
                continue
            raw_head = operands[0]
            words = args[args.index(operands[0]):]
            name, args = raw_head.rsplit("/", 1)[-1], words[1:]
            operands = [w for w in args if not w.startswith("-")]
        elif operands and (
            PYTHONS.match(name)
            or (raw_head.lstrip('"').startswith(("$(", "`")) and "python" in raw_head)
        ):
            if "-m" in args:
                m_idx = args.index("-m")
                if m_idx + 1 < len(args) and args[m_idx + 1] == "pip" and "install" in args[m_idx + 2:]:
                    if not ask_reason:
                        ask_reason = "Package installation (`python -m pip install`) requires explicit authorization (AGENTS.md: Specific authorization)."
                    continue
            raw_head = operands[0]
            words = args[args.index(operands[0]):]
            name, args = raw_head.rsplit("/", 1)[-1], words[1:]
            operands = [w for w in args if not w.startswith("-")]

        # Hard denies migrated from repository permission rules.
        if _matches_repo_script(raw_head, "scripts/release.sh"):
            return "deny", "`scripts/release.sh` is maintainer-run only (AGENTS.md: Hard boundaries)."
        if name == "gh" and len(operands) >= 2 and operands[0] == "release" and operands[1] in GH_RELEASE_DENY:
            return "deny", f"`gh release {operands[1]}` is maintainer-run only (AGENTS.md: Hard boundaries)."
        if name == "hf" and operands[:2] == ["auth", "token"]:
            return "deny", "`hf auth token` prints stored credentials and is denied (AGENTS.md: Privacy)."

        # Explicit ask rules for external writes, destructive git, installs, and downloads.
        reason = _check_ask_command(raw_head, name, args, operands)
        if reason and not ask_reason:
            ask_reason = reason

    if ask_reason:
        return "ask", ask_reason
    return "allow", ""


def _check_ask_command(raw_head: str, name: str, args: list[str], operands: list[str]) -> str:
    if name == "git":
        sub, sub_args = _git_subcommand_and_args(args)
        if sub == "push":
            return "Pushing requires an explicit maintainer request (AGENTS.md: Main is the only published branch)."
        if sub == "reset" and "--hard" in sub_args:
            return "`git reset --hard` discards local work; confirm before running."
        if sub == "restore":
            return "`git restore` discards uncommitted changes; confirm before running."
        if sub == "checkout" and "--" in sub_args:
            return "`git checkout --` discards uncommitted changes; confirm before running."
        if sub == "clean":
            return "`git clean` deletes untracked files; confirm before running."
        if sub == "branch" and "-D" in sub_args:
            return "`git branch -D` force-deletes a branch; confirm before running."
        if sub == "worktree" and sub_args[:1] == ["remove"] and ("--force" in sub_args or "-f" in sub_args):
            return "`git worktree remove --force` may discard unintegrated work; confirm before running."
        if sub == "config" and "--global" in sub_args:
            return "`git config --global` modifies host settings (AGENTS.md: Specific authorization)."
        return ""

    if _matches_repo_script(raw_head, "scripts/macos_test.sh") and operands[:2] in (["models", "install"], ["models", "ensure"]):
        return "Model download/install requires explicit maintainer authorization (AGENTS.md: Specific authorization)."
    if _matches_repo_script(raw_head, "scripts/ui_test.sh") and "model-download" in operands:
        return "Model-download UI lane requires explicit maintainer authorization (AGENTS.md: Specific authorization)."
    if _matches_repo_script(raw_head, "scripts/clean_build_caches.sh"):
        return "`scripts/clean_build_caches.sh` removes build caches; confirm before running."
    if _matches_repo_script(raw_head, "scripts/install_pinned_tools.sh"):
        return "`scripts/install_pinned_tools.sh` downloads and installs host tools; confirm before running."
    if _matches_repo_script(raw_head, "scripts/publish_benchmark_history.py"):
        return "Publishing benchmark history requires explicit authorization (AGENTS.md: Specific authorization)."
    if _matches_repo_script(raw_head, "scripts/benchmark_history.py") and "record" in operands:
        return "Recording benchmark history requires explicit authorization (AGENTS.md: Specific authorization)."
    if _matches_repo_script(raw_head, "scripts/ci/failure_issue.py"):
        return "`scripts/ci/failure_issue.py` files or comments on GitHub issues; confirm before running."

    if name == "gh" and operands:
        if operands[:2] == ["workflow", "run"]:
            return "`gh workflow run` dispatches CI externally; confirm before running."
        if operands[0] == "pr" and len(operands) >= 2 and operands[1] in GH_PR_ASK:
            return f"`gh pr {operands[1]}` writes to GitHub; confirm before running."
        if operands[:2] == ["issue", "create"]:
            return "`gh issue create` writes to GitHub; confirm before running."
        if operands[0] == "api":
            for index, token in enumerate(args):
                if token in ("-X", "--method") and index + 1 < len(args):
                    if args[index + 1].upper() in GH_API_WRITE_METHODS:
                        return f"`gh api {token} {args[index + 1]}` writes to GitHub; confirm before running."
                elif token.startswith("--method="):
                    if token.split("=", 1)[1].upper() in GH_API_WRITE_METHODS:
                        return f"`gh api {token}` writes to GitHub; confirm before running."
                elif token.startswith("-X") and len(token) > 2:
                    if token[2:].upper() in GH_API_WRITE_METHODS:
                        return f"`gh api {token}` writes to GitHub; confirm before running."
        return ""

    if name == "brew" and operands[:1] in (["install"], ["upgrade"]):
        return f"`brew {operands[0]}` modifies host packages; confirm before running."
    if name in ("pip", "pip3") and operands[:1] == ["install"]:
        return f"`{name} install` modifies Python packages; confirm before running."
    if name == "npm" and "install" in operands:
        return "`npm install` modifies dependencies; confirm before running."
    if name == "swift" and operands[:2] == ["package", "update"]:
        return "`swift package update` repins Swift packages (AGENTS.md: Specific authorization)."

    if name == "hf" and operands:
        if operands[0] in HF_ASK_SUBCOMMANDS:
            return f"`hf {operands[0]}` downloads or writes via Hugging Face; confirm before running."
        if operands[0] == "auth" and len(operands) >= 2 and operands[1] in HF_AUTH_ASK:
            return f"`hf auth {operands[1]}` modifies Hugging Face credentials; confirm before running."
        if operands[0] == "cache" and len(operands) >= 2 and operands[1] in HF_CACHE_ASK:
            return f"`hf cache {operands[1]}` modifies the Hugging Face cache; confirm before running."
        return ""
    if name == "huggingface-cli" and operands[:1] in (["download"], ["upload"]):
        return f"`huggingface-cli {operands[0]}` transfers Hugging Face artifacts; confirm before running."

    if name == "defaults" and operands[:1] == ["write"]:
        return "`defaults write` modifies macOS user defaults (AGENTS.md: Specific authorization)."
    if name == "xcode-select" and any(flag in ("-s", "--switch") for flag in args):
        return "`xcode-select` changes host Xcode selection (AGENTS.md: Specific authorization)."
    if name == "vercel" and not (set(args) <= {"--help", "-h", "--version", "-v"}):
        return "`vercel` CLI actions require explicit maintainer confirmation (AGENTS.md: Specific authorization)."
    if name == "asc" and not (set(args) <= {"--help", "-h", "version", "--version"}):
        return "`asc` CLI actions require explicit maintainer confirmation (AGENTS.md: Specific authorization)."
    return ""


def handle_session_start(payload: dict, root: Path) -> dict:
    cwd = _resolve_cwd(payload, root)
    try:
        result = subprocess.run(
            ["bash", str(HOOK_DIR / "session_start.sh")],
            capture_output=True,
            text=True,
            cwd=str(root),
            timeout=12,
            env=dict(os.environ, VOCELLO_PROJECT_ROOT=str(root)),
            check=False,
        )
        message = (result.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        message = "== Vocello session start (AGENTS.md: Start here) ==\n(session_start.sh unavailable)"
    if cwd.is_absolute() and adapter.linked_worktree(cwd):
        message = f"{SIDE_SESSION}{AGENT_RULES}\n\n{message}"
    return {"injectSteps": [{"systemMessage": {"systemMessage": message}}]}


def handle_pre_command(payload: dict, root: Path) -> dict:
    tool_call = payload.get("toolCall")
    if not isinstance(tool_call, dict):
        return {"decision": "allow"}
    args = tool_call.get("args")
    if not isinstance(args, dict):
        return {"decision": "allow"}
    command = args.get("CommandLine")
    if not isinstance(command, str) or not command.strip():
        return {"decision": "allow"}
    cwd = _resolve_cwd(payload, root)
    internal = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(cwd),
    }

    advisories: list[str] = []
    for script_name in ("policy_guard.sh", "commit_lint.sh", "agent_guard.py"):
        result = _run_guard(script_name, internal, cwd, root)
        if result.returncode != 0:
            reason = (result.stderr or result.stdout or f"{script_name} blocked this command").strip()
            return {"decision": "deny", "reason": reason}
        if script_name == "commit_lint.sh" and result.stdout.strip():
            try:
                parsed = json.loads(result.stdout)
                context = parsed.get("hookSpecificOutput", {}).get("additionalContext", "")
                if isinstance(context, str) and context.strip():
                    advisories.append(context.strip())
            except ValueError:
                pass

    decision, reason = command_policy_decision(command)
    if decision == "deny":
        return {"decision": "deny", "reason": reason}
    if decision == "ask":
        combined = f"{reason}\n" + "\n".join(advisories) if advisories else reason
        return {"decision": "ask", "reason": combined}
    if advisories:
        return {"decision": "allow", "reason": "\n".join(advisories)}
    return {"decision": "allow"}


def handle_pre_edit(payload: dict, root: Path) -> dict:
    tool_call = payload.get("toolCall")
    if not isinstance(tool_call, dict):
        return {"decision": "deny", "reason": "file guard: missing toolCall object"}
    tool_name = str(tool_call.get("name", ""))
    args = tool_call.get("args")
    if not isinstance(args, dict):
        return {"decision": "deny", "reason": "file guard: missing toolCall.args"}
    path = args.get("Path")
    if not isinstance(path, str) or not path:
        return {"decision": "deny", "reason": f"file guard: {tool_name} missing Path"}
    mapped = "Write" if tool_name == "write_file" else "Edit"
    cwd = _resolve_cwd(payload, root)
    internal = {
        "hook_event_name": "PreToolUse",
        "tool_name": mapped,
        "tool_input": {"file_path": path},
        "cwd": str(cwd),
    }
    for script_name in ("generated_file_guard.sh", "agent_guard.py"):
        result = _run_guard(script_name, internal, cwd, root)
        if result.returncode != 0:
            reason = (result.stderr or result.stdout or f"{script_name} blocked this edit").strip()
            return {"decision": "deny", "reason": reason}
    return {"decision": "allow"}


def handle_pre_mcp(payload: dict, root: Path) -> dict:
    tool_call = payload.get("toolCall")
    if not isinstance(tool_call, dict):
        return {"decision": "allow"}
    args = tool_call.get("args")
    if not isinstance(args, dict):
        return {"decision": "allow"}
    server = str(args.get("ServerName") or "").strip()
    tool = str(args.get("ToolName") or "").strip()
    mcp_args = args.get("Arguments")
    server_lower = server.lower()
    tool_lower = tool.lower()
    cwd = _resolve_cwd(payload, root)
    in_worktree = cwd.is_absolute() and adapter.linked_worktree(cwd)

    # 1. Retire computer-use / GUI driving (maintainer decision 2026-11-17).
    if "cua-driver" in server_lower:
        return {
            "decision": "deny",
            "reason": (
                "Computer use (`cua-driver`) is retired in Vocello (maintainer decision 2026-11-17): "
                "every Mac and iPhone UI check is an XCUITest lane via `scripts/ui_test.sh`, and website "
                "inspection uses the `browser` subagent."
            ),
        }

    # 2. Physical iPhone only: block Simulator tools on any MCP server.
    canonical = f"mcp__{server_lower}__{tool_lower}"
    if SIM_TOOL_PATTERN.search(canonical):
        return {
            "decision": "deny",
            "reason": "Physical iPhone only (AGENTS.md): Simulator MCP routes are unsupported; use repository device scripts.",
        }

    # 3. MobileBuildMCP: discovery and coverage reads only; never persist defaults.
    if server_lower in ("mobilebuildmcp", "xcodebuildmcp"):
        if tool_lower in MOBILEBUILD_DENY_TOOLS:
            return {
                "decision": "deny",
                "reason": (
                    f"`{server}:{tool}` is denied (AGENTS.md: Antigravity harness): repository scripts own "
                    "builds, tests, cleaning and XCUITest under the host native lock; MobileBuildMCP runs "
                    "project-discovery and coverage reads only."
                ),
            }
        if tool_lower == "session_set_defaults" and isinstance(mcp_args, dict):
            persist = mcp_args.get("persist")
            if persist is True or (isinstance(persist, str) and persist.strip().lower() == "true"):
                return {
                    "decision": "deny",
                    "reason": (
                        "Never call `session_set_defaults` with `persist: true` (.mobilebuildmcp/config.yaml): "
                        "it writes into the tracked config file and may leak a physical-device ID."
                    ),
                }

    # 4. Axiom: block xcui and Simulator/test-runner agents.
    if server_lower == "axiom":
        if "xcui" in tool_lower:
            return {
                "decision": "deny",
                "reason": "Axiom `xcui` is denied (AGENTS.md): every UI check runs through `scripts/ui_test.sh`.",
            }
        if tool_lower == "axiom_get_agent" and isinstance(mcp_args, dict):
            requested = str(mcp_args.get("name") or mcp_args.get("agent") or "").strip().lower()
            if requested in AXIOM_DENY_AGENTS:
                return {
                    "decision": "deny",
                    "reason": (
                        f"Axiom agent `{requested}` is denied (AGENTS.md): simulator and out-of-lane "
                        "test runners conflict with Vocello's physical-iPhone/XCUITest rules."
                    ),
                }

    # 5. Hugging Face Space/generation tools ask.
    if server_lower == "huggingface" and (tool_lower == "dynamic_space" or tool_lower.startswith("gr")):
        if in_worktree:
            return {
                "decision": "deny",
                "reason": f"Subagents never invoke `{server}:{tool}` outside their worktree (AGENTS.md).",
            }
        return {
            "decision": "ask",
            "reason": f"`{server}:{tool}` runs a remote Hugging Face Space; confirm before running (AGENTS.md: Specific authorization).",
        }

    # 6. GitHub connector writes ask under any server name (and deny in worktrees).
    gh_write = connector_write_guard.github_write(canonical)
    if gh_write:
        if in_worktree:
            return {
                "decision": "deny",
                "reason": f"`{gh_write}` writes to GitHub; subagents never write outside their worktree (AGENTS.md).",
            }
        return {
            "decision": "ask",
            "reason": f"`{gh_write}` writes to GitHub through MCP (AGENTS.md: Specific authorization). Approve only an explicitly requested write.",
        }

    return {"decision": "allow"}


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    root = _root()
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        if not isinstance(payload, dict):
            payload = {}
    except ValueError:
        payload = {}

    if mode == "session-start":
        output = handle_session_start(payload, root)
    elif mode == "pre-command":
        output = handle_pre_command(payload, root)
    elif mode == "pre-edit":
        output = handle_pre_edit(payload, root)
    elif mode == "pre-mcp":
        output = handle_pre_mcp(payload, root)
    else:
        output = {"decision": "deny", "reason": f"agy_hook_adapter: unknown mode {mode!r}"}

    print(json.dumps(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
