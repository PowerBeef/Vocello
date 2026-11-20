#!/usr/bin/env python3
"""Claude Code PreToolUse hook (matcher: ^mcp__): a GitHub connector write asks, whatever its server name.

The GitHub connector's tools reach a session under a server name the client chooses: `claude_ai_Github`
in the CLI, a per-install UUID in the desktop app, which can change (BKL-62, audit 2026-11-09 G-1). A
permission rule names a server, so this hook judges the tool's own name, the part after the last `__`.
A GitHub write (create, update, delete, push, merge, fork, comment, review, workflow runs, any
consolidated `*_write` tool) asks the maintainer through Claude Code's permission prompt, and a
subagent's is refused, since agents never write outside their worktree (CLAUDE.md: Agents and side
sessions). Reads (`get_*`, `list_*`, `search_*`, `*_read`) pass untouched. The settings' `mcp__*__<tool>`
ask rules name the writes too; this hook does not depend on how a rule's wildcard meets a server name.

A guardrail, not a sandbox: a tool another server names the same way asks too, which is the safe side.
Malformed input passes (the permission rules still apply). Hooks run the host's bare `python3`, often
the macOS system Python 3.9: keep this file importable there. Never execute or persist input.
"""
import json
import sys

# github-mcp-server's writing tools, consolidated and legacy names, plus every `*_write` tool.
GITHUB_WRITE_TOOLS = frozenset({
    "add_comment_to_pending_review", "add_issue_comment", "add_project_item",
    "add_reply_to_pull_request_comment", "add_sub_issue", "assign_copilot_to_issue",
    "cancel_workflow_run", "create_and_submit_pull_request_review", "create_branch", "create_gist",
    "create_issue", "create_or_update_file", "create_pending_pull_request_review", "create_pull_request",
    "create_pull_request_with_copilot", "create_repository", "delete_file",
    "delete_pending_pull_request_review", "delete_project_item", "delete_workflow_run_logs",
    "dismiss_notification", "fork_repository", "manage_notification_subscription",
    "manage_repository_notification_subscription", "mark_all_notifications_read", "merge_pull_request",
    "push_files", "remove_sub_issue", "reprioritize_sub_issue", "request_copilot_review",
    "rerun_failed_jobs", "rerun_workflow_run", "run_workflow", "star_repository",
    "submit_pending_pull_request_review", "unstar_repository", "update_gist", "update_issue",
    "update_issue_comment", "update_project_item", "update_pull_request", "update_pull_request_branch",
})
RULE = "AGENTS.md: Antigravity harness, every write through an optional tool needs an explicit request"


def github_write(tool_name: str) -> str:
    """The tool's own name when it is a GitHub connector write, under any server name, else ''."""
    parts = tool_name.split("__")
    if len(parts) < 3 or parts[0] != "mcp":
        return ""
    tool = parts[-1].lower()
    return tool if tool in GITHUB_WRITE_TOOLS or tool.endswith("_write") else ""


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        tool = github_write(str(payload.get("tool_name", "")))
    except (ValueError, TypeError, AttributeError):
        return 0
    if not tool:
        return 0
    if payload.get("agent_id"):
        print(f"connector guard: BLOCKED — `{tool}` writes to GitHub; agents never write outside their "
              "worktree (CLAUDE.md: Agents and side sessions). Report back to the lead.", file=sys.stderr)
        return 2
    reason = (f"`{tool}` writes to GitHub through the connector ({RULE}). Approve only a write the "
              "maintainer asked for.")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                             "permissionDecisionReason": reason}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
