#!/usr/bin/env python3
"""GitHub MCP connector write classification helper for `agy_hook_adapter.py`.

GitHub connector tools can reach a session under client-chosen server names (for example
`github` or a per-install UUID, BKL-62). `github_write()` judges the tool's own name (the
segment after the last `__`) so `agy_hook_adapter.py` enforces `force_ask` (or `deny` in a
linked worktree) regardless of server naming. Reads (`get_*`, `list_*`, `search_*`, `*_read`)
return `""`.

Hooks run under the host's bare `python3` (often macOS system Python 3.9): keep this module
importable there. Never execute or persist input.
"""

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


def github_write(tool_name: str) -> str:
    """The tool's own name when it is a GitHub connector write, under any server name, else ''."""
    parts = tool_name.split("__")
    if len(parts) < 3 or parts[0] != "mcp":
        return ""
    tool = parts[-1].lower()
    return tool if tool in GITHUB_WRITE_TOOLS or tool.endswith("_write") else ""
