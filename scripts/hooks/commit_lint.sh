#!/usr/bin/env bash
# Claude Code PreToolUse hook (matcher: Bash): the commit lint.
#
# Fired for every Bash tool call; exits instantly unless the command contains
# `git commit`. For commits it requires the symbolic branch to be exactly `main`,
# clean whitespace in the staged diff, and no private path or credential in the
# staged files. It finishes in seconds and never builds or tests anything: CI on
# push is the gate.

set -euo pipefail

payload="$(cat 2>/dev/null || true)"
command_text="$(printf '%s' "$payload" \
  | python3 -c 'import json,sys
try:
    print(json.load(sys.stdin).get("tool_input", {}).get("command", ""))
except Exception:
    print("")' 2>/dev/null || true)"

case "$command_text" in
  *"git commit"*) ;;
  *) exit 0 ;;
esac

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${CLAUDE_PROJECT_DIR:-$(cd "$HOOK_DIR/../.." && pwd)}"
cd "$ROOT_DIR"

current_branch="$(git symbolic-ref --quiet --short HEAD 2>/dev/null || true)"
if [[ "$current_branch" != "main" ]]; then
  echo "commit lint: BLOCKED — commits are made directly on main (current: ${current_branch:-detached HEAD})." >&2
  echo "Return to main without discarding work; do not continue on another branch." >&2
  exit 2
fi

if ! git diff --cached --check >/dev/null 2>&1; then
  echo "commit lint: BLOCKED — staged changes contain whitespace errors (git diff --cached --check)." >&2
  exit 2
fi

if ! python3 "$HOOK_DIR/../privacy_scan.py" --root "$ROOT_DIR" --staged; then
  echo "commit lint: BLOCKED — staged content contains a private path or credential-shaped token." >&2
  exit 2
fi

exit 0
