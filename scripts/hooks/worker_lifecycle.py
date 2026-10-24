#!/usr/bin/env python3
"""Claude Code lifecycle adapter for host worker tracking; no raw hook input is saved.

Hooks run the host's bare `python3`, often the macOS system Python 3.9: keep this
file and what it imports importable there.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import active_workers
import agent_hook_input

AGENT_RULES = ("Vocello agent rules: commit only on your own worktree's branch (worktree-* or claude/*); "
               "never push; run no native builds, devices, models or measured lanes (the lead owns them); "
               "never edit config/roadmap.json or docs/development-progress.md.")
SIDE_SESSION = ("This session works in a linked worktree, so it is a side session, not the lead, and the "
                "agent guard holds it to the agent rules. ")


def session_export(env_file: str | None, session_key: str) -> bool:
    """Expose this session's opaque marker to later Bash calls (SessionStart only)."""
    if not env_file:
        return False
    try:
        with open(env_file, "a", encoding="utf-8") as stream:
            stream.write(f"export QVOICE_WORKER_SESSION={session_key}\n")
    except OSError:
        return False  # Registration stands; the context below still names the marker.
    return True


def subagent_context() -> str:
    return AGENT_RULES


def side_session(cwd: object) -> bool:
    """A session started in a linked worktree (a desktop app side session) is never the lead."""
    # linked_worktree never raises, so this context line cannot invalidate the receipt just written.
    return isinstance(cwd, str) and Path(cwd).is_absolute() and agent_hook_input.linked_worktree(Path(cwd))


def response(payload: dict) -> dict:
    event = payload.get("hook_event_name")
    if event == "SessionStart":
        session_key = active_workers.key(payload["session_id"])
        exported = session_export(os.environ.get("CLAUDE_ENV_FILE"), session_key)
        context = ("Worker lifecycle registered for this session. For measured lanes use QVOICE_WORKER_SESSION="
                   + session_key + (" (already exported to Bash)" if exported else "")
                   + "; still join all known workers first.")
        if side_session(payload.get("cwd")):
            context = SIDE_SESSION + AGENT_RULES + " " + context
        return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}
    if event == "SubagentStart":
        return {"hookSpecificOutput": {"hookEventName": "SubagentStart", "additionalContext": subagent_context()}}
    return {}


def main() -> None:
    payload = {}
    try:
        payload = json.load(sys.stdin)
        active_workers.lifecycle(payload)
        print(json.dumps(response(payload)))
    except Exception as error:
        try:
            active_workers.invalidate(payload)
        except Exception:
            pass  # The visible warning and absent current receipt require lead-only fallback.
        # Hooks cannot prove activation or authorize measurement. The lane preflight
        # will require explicit lead-only execution if it cannot read live ownership.
        print(json.dumps({"systemMessage": f"Vocello worker tracking unavailable ({type(error).__name__}); "
                         "join workers before measured lanes and inspect scripts/dev.sh doctor."}))


if __name__ == "__main__":
    main()
