#!/usr/bin/env bash
# Codex PreToolUse hook: the fast T1 receipt check.
#
# Fired for every Bash tool call; exits instantly unless the command contains
# `git commit`. For commits it first requires the symbolic branch to be exactly
# `main`, then requires a completed path-aware local checkpoint receipt.
# Either violation blocks the commit. Run the checkpoint outside this hook:
# builds can exceed the host hook timeout, which is not a validation result.
# A fingerprint of the current tree state is cached under
# build/scratch/gate-fingerprint (scratch-class output) so repeat commits on
# an already-validated tree are a no-op.
#
# Escape hatch (emergencies only): QVOICE_SKIP_COMMIT_GATE=1 skips validation
# for that one invocation, but never bypasses the main-branch requirement. CI
# never uses this hook; the full suite on GitHub remains the backstop for every
# push.

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

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

current_branch="$(git symbolic-ref --quiet --short HEAD 2>/dev/null || true)"
if [[ "$current_branch" != "main" ]]; then
  branch_label="${current_branch:-detached HEAD}"
  echo "commit gate: BLOCKED — development commits must be made directly on main (current: $branch_label)." >&2
  echo "Return to main without discarding work; do not continue implementation on another branch." >&2
  exit 2
fi

if [[ "${QVOICE_SKIP_COMMIT_GATE:-0}" == "1" ]]; then
  echo "commit gate: skipped once (QVOICE_SKIP_COMMIT_GATE=1)" >&2
  exit 0
fi

marker_dir="build/scratch/gate-fingerprint"
marker="$marker_dir/last-pass"

# Content-complete tree fingerprint: final tracked worktree bytes and every
# non-ignored untracked path/byte are bound. Re-editing an already-dirty file
# cannot reuse a stale PASS marker, while staging the exact same bytes can.
if ! fingerprint="$(python3 scripts/tree_fingerprint.py --root "$ROOT_DIR" --checkpoint 2>/dev/null)"; then
  echo "commit gate: BLOCKED — unable to verify the checkpoint identity." >&2
  echo "Run scripts/dev.sh checkpoint and resolve its errors before committing." >&2
  exit 2
fi

if [[ -f "$marker" && "$(cat "$marker" 2>/dev/null)" == "$fingerprint" ]]; then
  exit 0
fi

echo "commit gate: BLOCKED — completed checkpoint receipt is missing or stale." >&2
echo "Run scripts/dev.sh checkpoint outside the hook, inspect its result, then commit the validated tree." >&2
exit 2
