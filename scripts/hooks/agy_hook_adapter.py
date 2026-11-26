#!/usr/bin/env python3
"""Antigravity lifecycle hook adapter for Vocello repository guards.

Translates Antigravity camelCase hook JSON on stdin into the repository's existing
guard scripts and emits Antigravity JSON decisions on stdout:
  - session-start   -> {"injectSteps": [{"systemMessage": {"systemMessage": ...}}]}
  - pre-command     -> {"decision": "allow"|"ask"|"force_ask"|"deny", "reason": ...}
  - pre-edit        -> {"decision": "allow"|"deny", "reason": ...}
  - pre-mcp         -> {"decision": "allow"|"ask"|"force_ask"|"deny", "reason": ...}
  - post-invocation -> {"injectSteps": [...], "terminationBehavior": ""} | {}
  - stop            -> {"decision": "continue", "reason": ...} | {}

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
SCRIPTS_DIR = HOOK_DIR.parent
ROOT = HOOK_DIR.parents[1]
sys.path.insert(0, str(HOOK_DIR))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
try:
    import active_workers  # noqa: E402
except ImportError:
    active_workers = None  # type: ignore[assignment]
import agent_guard  # noqa: E402
import agent_hook_input as adapter  # noqa: E402
import connector_write_guard  # noqa: E402
import git_commands  # noqa: E402

DECISION_RANK = {"allow": 0, "ask": 1, "force_ask": 2, "deny": 3}

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
HF_ASK_SUBCOMMANDS = frozenset({"download"})
HF_FORCE_ASK_SUBCOMMANDS = frozenset({
    "upload", "repos", "cp", "sync", "buckets", "jobs", "sandbox",
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


def _merge_decision(current: tuple[str, str], candidate: tuple[str, str]) -> tuple[str, str]:
    if DECISION_RANK[candidate[0]] > DECISION_RANK[current[0]]:
        return candidate
    return current


def _sync_worker_lease(event: str, payload: dict, cwd: Path) -> None:
    """Best-effort host-wide worker lease registration for Antigravity sessions and worktree workers."""
    if active_workers is None:
        return
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("QVOICE_WORKER_DIRECTORY"):
        return
    session_id = str(payload.get("conversationId") or "").strip()
    if not session_id:
        return
    in_worktree = cwd.is_absolute() and adapter.linked_worktree(cwd)
    worker_payload: dict[str, str] | None = None
    if event == "session-start":
        if in_worktree:
            worker_payload = {"hook_event_name": "SubagentStart", "session_id": session_id, "agent_id": str(cwd)}
        else:
            worker_payload = {"hook_event_name": "SessionStart", "session_id": session_id}
    elif event in ("pre-command", "pre-edit"):
        if in_worktree:
            worker_payload = {"hook_event_name": "SubagentStart", "session_id": session_id, "agent_id": str(cwd)}
    elif event == "stop":
        if in_worktree and payload.get("fullyIdle") is True:
            worker_payload = {"hook_event_name": "SubagentStop", "session_id": session_id, "agent_id": str(cwd)}
    if worker_payload is None:
        return
    try:
        active_workers.lifecycle(worker_payload)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        pass


def _check_agent_guard(internal: dict, cwd: Path, root: Path) -> str:
    """Run agent_guard in-process for linked worktrees and subagent payloads (fail-open on parser errors)."""
    if not internal.get("agent_id") and not (cwd.is_absolute() and adapter.linked_worktree(cwd)):
        return ""
    tool_input = internal.get("tool_input")
    try:
        if internal.get("tool_name") == "Bash":
            command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
            if not isinstance(command, str):
                return ""
            reason = (
                agent_guard.git_violation(command, cwd if cwd.is_absolute() else root)
                or agent_guard.command_violation(command)
                or agent_guard.roadmap_write_violation(command)
            )
        elif internal.get("tool_name") in adapter.EDIT_PATH_KEYS:
            reason = agent_guard.edit_violation(internal, root)
        else:
            return ""
    except Exception:  # noqa: BLE001 - matches agent_guard.main() fail-open parser boundary
        return ""
    if not reason:
        return ""
    return (
        f"agent guard: BLOCKED — {reason} ({agent_guard.RULE}).\n"
        "Agents and side sessions (any call from a linked worktree) report back to the lead, which works "
        "in the main checkout and owns native builds, measured lanes, pushes, the roadmap and the "
        "checkpoint."
    )


def command_policy_decision(command: str, depth: int = 0) -> tuple[str, str]:
    """Return ('deny'|'force_ask'|'ask'|'allow', reason) for authorization-bound shell commands."""
    if depth > 3 or not command.strip():
        return "allow", ""
    stripped, bodies = adapter.shell_fed_bodies(command)
    best: tuple[str, str] = ("allow", "")
    for body in bodies:
        decision = command_policy_decision(body, depth + 1)
        if decision[0] == "deny":
            return decision
        best = _merge_decision(best, decision)

    for words in adapter._simple_commands(stripped):
        while words and (
            words[0].rsplit("/", 1)[-1] in adapter.WRAPPERS | git_commands.TRANSPARENT_PREFIXES
            or git_commands.ASSIGNMENT.match(words[0])
        ):
            if words[0].rsplit("/", 1)[-1] == "sudo":
                best = _merge_decision(
                    best,
                    ("force_ask", "Privileged command (`sudo`) requires explicit maintainer confirmation."),
                )
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
                decision = command_policy_decision(args[script_idx], depth + 1)
                if decision[0] == "deny":
                    return decision
                best = _merge_decision(best, decision)
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
                    best = _merge_decision(
                        best,
                        ("ask", "Package installation (`python -m pip install`) requires explicit authorization (AGENTS.md: Specific authorization)."),
                    )
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

        # Explicit ask / force_ask rules for external writes, destructive git, installs, and downloads.
        best = _merge_decision(best, _check_ask_command(raw_head, name, args, operands))

    return best


def _check_ask_command(raw_head: str, name: str, args: list[str], operands: list[str]) -> tuple[str, str]:
    if name == "git":
        sub, sub_args = _git_subcommand_and_args(args)
        if sub == "push":
            return "force_ask", "Pushing requires an explicit maintainer request (AGENTS.md: Main is the only published branch)."
        if sub == "reset" and "--hard" in sub_args:
            return "force_ask", "`git reset --hard` discards local work; confirm before running."
        if sub == "restore":
            return "ask", "`git restore` discards uncommitted changes; confirm before running."
        if sub == "checkout" and "--" in sub_args:
            return "ask", "`git checkout --` discards uncommitted changes; confirm before running."
        if sub == "clean":
            return "force_ask", "`git clean` deletes untracked files; confirm before running."
        if sub == "branch" and "-D" in sub_args:
            return "force_ask", "`git branch -D` force-deletes a branch; confirm before running."
        if sub == "worktree" and sub_args[:1] == ["remove"] and ("--force" in sub_args or "-f" in sub_args):
            return "force_ask", "`git worktree remove --force` may discard unintegrated work; confirm before running."
        if sub == "config" and "--global" in sub_args:
            return "force_ask", "`git config --global` modifies host settings (AGENTS.md: Specific authorization)."
        return "allow", ""

    if _matches_repo_script(raw_head, "scripts/ios_candidate_tag.py"):
        if "--dry-run" in args or "--help" in args or "-h" in args:
            return "allow", ""
        return (
            "force_ask",
            "`scripts/ios_candidate_tag.py` signs and pushes a TestFlight candidate tag; confirm before running (AGENTS.md: Main is the only published branch).",
        )
    if _matches_repo_script(raw_head, "scripts/release_tag.py"):
        if "--dry-run" in args or "--help" in args or "-h" in args:
            return "allow", ""
        return (
            "force_ask",
            "`scripts/release_tag.py` signs and pushes a release tag; confirm before running (AGENTS.md: Main is the only published branch).",
        )
    if _matches_repo_script(raw_head, "scripts/macos_test.sh") and operands[:2] in (["models", "install"], ["models", "ensure"]):
        return "ask", "Model download/install requires explicit maintainer authorization (AGENTS.md: Specific authorization)."
    if _matches_repo_script(raw_head, "scripts/ui_test.sh") and "model-download" in operands:
        return "ask", "Model-download UI lane requires explicit maintainer authorization (AGENTS.md: Specific authorization)."
    if _matches_repo_script(raw_head, "scripts/clean_build_caches.sh"):
        return "ask", "`scripts/clean_build_caches.sh` removes build caches; confirm before running."
    if _matches_repo_script(raw_head, "scripts/install_pinned_tools.sh"):
        return "ask", "`scripts/install_pinned_tools.sh` downloads and installs host tools; confirm before running."
    if _matches_repo_script(raw_head, "scripts/publish_benchmark_history.py"):
        return "force_ask", "Publishing benchmark history requires explicit authorization (AGENTS.md: Specific authorization)."
    if _matches_repo_script(raw_head, "scripts/benchmark_history.py") and "record" in operands:
        return "force_ask", "Recording benchmark history requires explicit authorization (AGENTS.md: Specific authorization)."
    if _matches_repo_script(raw_head, "scripts/ci/failure_issue.py"):
        return "force_ask", "`scripts/ci/failure_issue.py` files or comments on GitHub issues; confirm before running."

    if name == "gh" and operands:
        if operands[:2] == ["workflow", "run"]:
            return "force_ask", "`gh workflow run` dispatches CI externally; confirm before running."
        if operands[0] == "pr" and len(operands) >= 2 and operands[1] in GH_PR_ASK:
            return "force_ask", f"`gh pr {operands[1]}` writes to GitHub; confirm before running."
        if operands[:2] == ["issue", "create"]:
            return "force_ask", "`gh issue create` writes to GitHub; confirm before running."
        if operands[0] == "api":
            for index, token in enumerate(args):
                if token in ("-X", "--method") and index + 1 < len(args):
                    if args[index + 1].upper() in GH_API_WRITE_METHODS:
                        return "force_ask", f"`gh api {token} {args[index + 1]}` writes to GitHub; confirm before running."
                elif token.startswith("--method="):
                    if token.split("=", 1)[1].upper() in GH_API_WRITE_METHODS:
                        return "force_ask", f"`gh api {token}` writes to GitHub; confirm before running."
                elif token.startswith("-X") and len(token) > 2:
                    if token[2:].upper() in GH_API_WRITE_METHODS:
                        return "force_ask", f"`gh api {token}` writes to GitHub; confirm before running."
        return "allow", ""

    if name == "brew" and operands[:1] in (["install"], ["upgrade"]):
        return "ask", f"`brew {operands[0]}` modifies host packages; confirm before running."
    if name in ("pip", "pip3") and operands[:1] == ["install"]:
        return "ask", f"`{name} install` modifies Python packages; confirm before running."
    if name == "npm" and "install" in operands:
        return "ask", "`npm install` modifies dependencies; confirm before running."
    if name == "swift" and operands[:2] == ["package", "update"]:
        return "ask", "`swift package update` repins Swift packages (AGENTS.md: Specific authorization)."

    if name == "hf" and operands:
        if operands[0] in HF_ASK_SUBCOMMANDS:
            return "ask", f"`hf {operands[0]}` downloads via Hugging Face; confirm before running."
        if operands[0] in HF_FORCE_ASK_SUBCOMMANDS:
            return "force_ask", f"`hf {operands[0]}` writes or runs jobs via Hugging Face; confirm before running."
        if operands[0] == "auth" and len(operands) >= 2 and operands[1] in HF_AUTH_ASK:
            return "force_ask", f"`hf auth {operands[1]}` modifies Hugging Face credentials; confirm before running."
        if operands[0] == "cache" and len(operands) >= 2 and operands[1] in HF_CACHE_ASK:
            return "force_ask", f"`hf cache {operands[1]}` modifies the Hugging Face cache; confirm before running."
        return "allow", ""
    if name == "huggingface-cli" and operands[:1] == ["download"]:
        return "ask", "`huggingface-cli download` transfers Hugging Face artifacts; confirm before running."
    if name == "huggingface-cli" and operands[:1] == ["upload"]:
        return "force_ask", "`huggingface-cli upload` uploads Hugging Face artifacts; confirm before running."

    if name == "defaults" and operands[:1] == ["write"]:
        return "force_ask", "`defaults write` modifies macOS user defaults (AGENTS.md: Specific authorization)."
    if name == "xcode-select" and any(flag in ("-s", "--switch") for flag in args):
        return "force_ask", "`xcode-select` changes host Xcode selection (AGENTS.md: Specific authorization)."
    if name == "vercel" and not (set(args) <= {"--help", "-h", "--version", "-v"}):
        return "force_ask", "`vercel` CLI actions require explicit maintainer confirmation (AGENTS.md: Specific authorization)."
    if name == "asc" and not (set(args) <= {"--help", "-h", "version", "--version"}):
        return "force_ask", "`asc` CLI actions require explicit maintainer confirmation (AGENTS.md: Specific authorization)."
    return "allow", ""


def handle_session_start(payload: dict, root: Path) -> dict:
    cwd = _resolve_cwd(payload, root)
    _sync_worker_lease("session-start", payload, cwd)
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
    _sync_worker_lease("pre-command", payload, cwd)
    internal = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(cwd),
    }

    advisories: list[str] = []
    for script_name in ("policy_guard.sh", "commit_lint.sh"):
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

    agent_block = _check_agent_guard(internal, cwd, root)
    if agent_block:
        return {"decision": "deny", "reason": agent_block}

    decision, reason = command_policy_decision(command)
    if decision == "deny":
        return {"decision": "deny", "reason": reason}
    if decision in ("ask", "force_ask"):
        combined = f"{reason}\n" + "\n".join(advisories) if advisories else reason
        return {"decision": decision, "reason": combined}
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
    _sync_worker_lease("pre-edit", payload, cwd)
    internal = {
        "hook_event_name": "PreToolUse",
        "tool_name": mapped,
        "tool_input": {"file_path": path},
        "cwd": str(cwd),
    }
    result = _run_guard("generated_file_guard.sh", internal, cwd, root)
    if result.returncode != 0:
        reason = (result.stderr or result.stdout or "generated_file_guard.sh blocked this edit").strip()
        return {"decision": "deny", "reason": reason}
    agent_block = _check_agent_guard(internal, cwd, root)
    if agent_block:
        return {"decision": "deny", "reason": agent_block}
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

    # 5. Hugging Face Space/generation tools force_ask (never cached by Always Allow).
    if server_lower == "huggingface" and (tool_lower == "dynamic_space" or tool_lower.startswith("gr")):
        if in_worktree:
            return {
                "decision": "deny",
                "reason": f"Subagents never invoke `{server}:{tool}` outside their worktree (AGENTS.md).",
            }
        return {
            "decision": "force_ask",
            "reason": f"`{server}:{tool}` runs a remote Hugging Face Space; confirm before running (AGENTS.md: Specific authorization).",
        }

    # 6. GitHub connector writes force_ask under any server name (and deny in worktrees).
    gh_write = connector_write_guard.github_write(canonical)
    if gh_write:
        if in_worktree:
            return {
                "decision": "deny",
                "reason": f"`{gh_write}` writes to GitHub; subagents never write outside their worktree (AGENTS.md).",
            }
        return {
            "decision": "force_ask",
            "reason": f"`{gh_write}` writes to GitHub through MCP (AGENTS.md: Specific authorization). Approve only an explicitly requested write.",
        }

    return {"decision": "allow"}


def handle_post_invocation(payload: dict, root: Path) -> dict:
    """Inject concise, zero-noise drift advisories on the main checkout when derived files lag."""
    cwd = _resolve_cwd(payload, root)
    if cwd.is_absolute() and adapter.linked_worktree(cwd):
        return {}
    try:
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if status.returncode != 0 or not status.stdout:
        return {}

    pbxproj_dirty = False
    swift_membership_changed = False
    roadmap_json_dirty = False
    roadmap_md_dirty = False

    for line in status.stdout.splitlines():
        if len(line) < 4:
            continue
        code = line[:2]
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        path = path.strip('"')
        if path == "QwenVoice.xcodeproj/project.pbxproj":
            pbxproj_dirty = True
        elif path.endswith(".swift") and (path.startswith("Sources/") or path.startswith("Tests/")):
            if any(flag in ("A", "D", "R", "?") for flag in code):
                swift_membership_changed = True
        elif path in ("config/roadmap.json", "config/roadmap-archive.json"):
            roadmap_json_dirty = True
        elif path == "docs/ROADMAP.md":
            roadmap_md_dirty = True

    advisories: list[str] = []
    if swift_membership_changed and not pbxproj_dirty:
        advisories.append(
            "Vocello drift notice: Swift file membership under Sources/ or Tests/ changed without updating "
            "QwenVoice.xcodeproj/project.pbxproj. Run `./scripts/regenerate_project.sh --fast` before building or committing."
        )
    if roadmap_json_dirty and not roadmap_md_dirty:
        roadmap_script = root / "scripts/roadmap.py"
        drifted = True
        if roadmap_script.is_file():
            try:
                check = subprocess.run(
                    ["python3", str(roadmap_script), "--root", str(root), "render", "--check"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                    check=False,
                )
                drifted = check.returncode != 0
            except (OSError, subprocess.SubprocessError):
                drifted = True
        if drifted:
            advisories.append(
                "Vocello drift notice: config/roadmap*.json changed without regenerating docs/ROADMAP.md. "
                "Run `python3 scripts/roadmap.py render` (or use `roadmap.py set|note|close`)."
            )

    if not advisories:
        return {}
    return {
        "injectSteps": [{"systemMessage": {"systemMessage": "\n".join(advisories)}}],
        "terminationBehavior": "",
    }


def handle_stop(payload: dict, root: Path) -> dict:
    """Release linked-worktree worker leases and catch staged whitespace/conflict errors once per turn."""
    cwd = _resolve_cwd(payload, root)
    _sync_worker_lease("stop", payload, cwd)
    if cwd.is_absolute() and adapter.linked_worktree(cwd):
        return {}
    if (
        payload.get("terminationReason") != "NO_TOOL_CALL"
        or payload.get("fullyIdle") is not True
        or payload.get("continuationActive") is True
    ):
        return {}
    try:
        check = subprocess.run(
            ["git", "-C", str(root), "diff", "--cached", "--check"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if check.returncode != 0:
        return {
            "decision": "continue",
            "reason": (
                "Staged changes contain whitespace errors or conflict markers (`git diff --cached --check` failed). "
                "Fix or unstage them before finishing."
            ),
        }
    return {}


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
    elif mode == "post-invocation":
        output = handle_post_invocation(payload, root)
    elif mode == "stop":
        output = handle_stop(payload, root)
    else:
        output = {"decision": "deny", "reason": f"agy_hook_adapter: unknown mode {mode!r}"}

    print(json.dumps(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
