#!/usr/bin/env bash
# Claude Code SessionStart hook: the "Start and resume work" ritual, printed.
#
# Output goes to the session context. Read-only, bounded (< 8 s), never fails:
# each section is best-effort and a missing tool just prints a short note.
#
#   1. branch and dirty state
#   2. scripts/dev.sh status (classification, receipt state, primary plan)
#   3. the "Resume now" head of docs/development-progress.md
#   4. paired iPhone reachability and lock state (never the identifier)
#   5. TSan characterization deadline when it is close

root="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
cd "$root" 2>/dev/null || exit 0

with_deadline() {
  # perl is always present on macOS; coreutils `timeout` is not.
  perl -e 'alarm shift @ARGV; exec @ARGV' "$@" 2>/dev/null
}

echo "== Vocello session start (CLAUDE.md: Start and resume work) =="
echo
echo "-- git --"
git status --short --branch 2>/dev/null | head -n 20 || echo "(git unavailable)"
echo
echo "-- scripts/dev.sh status --"
with_deadline 6 scripts/dev.sh status 2>&1 | head -n 12 || echo "(status unavailable)"
echo
echo "-- docs/development-progress.md: Resume now --"
if [[ -f docs/development-progress.md ]]; then
  awk '
    /^## Resume now/ { on = 1; next }
    on && /^### / && seen_heading { exit }
    on && /^### / { seen_heading = 1 }
    on { print; n++ }
    n >= 18 { exit }
  ' docs/development-progress.md
else
  echo "(missing)"
fi
echo
echo "-- paired iPhone --"
probe="$(with_deadline 5 python3 scripts/lib/ios_coredevice_probe.py probe 2>/dev/null || true)"
if [[ -n "$probe" ]]; then
  printf '%s' "$probe" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    print("(probe output unreadable)"); raise SystemExit
lock = d.get("lock") or {}
name = d.get("name") or d.get("deviceName") or "paired iPhone"
state = "reachable" if d.get("reachable") else "not reachable"
locked = lock.get("deviceLocked")
lock_text = "locked" if locked is True else ("unlocked" if locked is False else "lock state unknown")
print(f"{name}: {state}, {lock_text} (device lanes need explicit consent)")
' 2>/dev/null || echo "(probe output unreadable)"
else
  echo "no paired iPhone reachable (fine for deterministic work)"
fi
echo
python3 - <<'PY' 2>/dev/null || true
import datetime, json, pathlib
try:
    policy = json.loads(pathlib.Path("config/tsan-policy.json").read_text())
    ch = policy.get("characterization", {})
    deadline = datetime.date.fromisoformat(ch["deadline"])
    days = (deadline - datetime.date.today()).days
    if days <= 30:
        print(f"-- TSan characterization -- deadline {deadline} ({days} days): "
              f"{ch.get('recordedConsecutivePasses', '?')}/{ch.get('requiredConsecutivePassesForBlockingReview', '?')} "
              "consecutive passes recorded; see config/tsan-policy.json")
except Exception:
    pass
PY
exit 0
