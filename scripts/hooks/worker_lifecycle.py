#!/usr/bin/env python3
"""Codex lifecycle adapter for host worker tracking; no raw hook input is saved."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import active_workers

payload = {}
try:
    payload = json.load(sys.stdin)
    active_workers.lifecycle(payload)
    if payload.get("hook_event_name") == "SessionStart":
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext":
              "Worker lifecycle registered for this session. For measured lanes use QVOICE_WORKER_SESSION="
              + active_workers.key(payload["session_id"]) + "; still join all known workers first."}}))
    else:
        print("{}")
except Exception as error:
    try:
        active_workers.invalidate(payload)
    except Exception:
        pass  # The visible warning and absent current receipt require lead-only fallback.
    # Hooks cannot prove activation or authorize measurement. The lane preflight
    # will require explicit lead-only execution if it cannot read live ownership.
    print(json.dumps({"systemMessage": f"Vocello worker tracking unavailable ({type(error).__name__}); "
                     "join workers before measured lanes and inspect scripts/dev.sh doctor."}))
