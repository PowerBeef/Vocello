#!/usr/bin/env bash
# Claude Code PostToolUse hook (matcher: Edit|Write|MultiEdit).
#
# After project.yml changes (in the checkout or an agent worktree), remind the session that the Xcode project is
# generated and the generation stamp must be refreshed before a checkpoint.
# Advisory only: exit 0, context returned through hookSpecificOutput.

set -euo pipefail

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
file_paths="$(python3 "$HOOK_DIR/agent_hook_input.py" paths)"
root="$(cd "$HOOK_DIR/../.." && pwd)"
root="$(cd "$root" && pwd -P)"
while IFS= read -r file_path; do
  relative="${file_path#"$root"/}"
  if [[ "$relative" == .claude/worktrees/*/project.yml && "$relative" != .claude/worktrees/*/*/* ]]; then
    relative="project.yml"
  fi
  if [[ "$relative" == "project.yml" ]]; then
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
    break
  fi
done <<< "$file_paths"

exit 0
