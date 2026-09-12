#!/usr/bin/env bash
# Claude Code PostToolUse hook (matcher: Edit|Write|MultiEdit).
#
# After project.yml changes, remind the session that the Xcode project is
# generated and the generation stamp must be refreshed before a checkpoint.
# Advisory only: exit 0, context returned through hookSpecificOutput.

set -euo pipefail

payload="$(cat 2>/dev/null || true)"
file_path="$(printf '%s' "$payload" \
  | python3 -c 'import json,sys
try:
    print(json.load(sys.stdin).get("tool_input", {}).get("file_path", ""))
except Exception:
    print("")' 2>/dev/null || true)"

case "$(basename -- "${file_path:-}")" in
  project.yml)
    python3 - <<'PY'
import json
print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": (
            "project.yml changed: run ./scripts/regenerate_project.sh --fast before verifying and commit "
            "the regenerated QwenVoice.xcodeproj; the generation stamp must match project.yml or the project gate fails."
        ),
    }
}))
PY
    ;;
esac

exit 0
