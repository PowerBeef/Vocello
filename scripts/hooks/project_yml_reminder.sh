#!/usr/bin/env bash
# Codex PostToolUse reminder. Actual freshness is enforced by the shared signature.
#
# After project.yml changes (in the checkout or an agent worktree), remind the session that the Xcode project is
# generated and the generation stamp must be refreshed before a checkpoint.
# Advisory only: exit 0, context returned through hookSpecificOutput.

set -euo pipefail

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
file_paths="$(python3 "$HOOK_DIR/agent_hook_input.py" relative-paths)"
while IFS= read -r file_path; do
  relative="$file_path"
  if [[ "$relative" == "project.yml" || "$relative" == Sources/* || "$relative" == Tests/* ]]; then
    python3 - <<'PY'
import json
print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": (
            "Project input touched: scripts/dev.sh check checks the shared project-generation signature. "
            "Regenerate with ./scripts/regenerate_project.sh --fast when specification or file membership changes; "
            "commit the regenerated QwenVoice.xcodeproj. Content-only source edits do not require regeneration."
        ),
    }
}))
PY
    break
  fi
done <<< "$file_paths"

exit 0
