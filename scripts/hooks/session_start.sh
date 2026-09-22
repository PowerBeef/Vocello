#!/usr/bin/env bash
# Claude Code SessionStart hook: branch and dirty state, dev.sh status, the "Resume now"
# head of docs/development-progress.md. Local-only, bounded, never fails.

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$root" 2>/dev/null || exit 0

with_deadline() {
  # perl is always present on macOS; coreutils `timeout` is not.
  perl -e 'alarm shift @ARGV; exec @ARGV' "$@" 2>/dev/null
}

echo "== Vocello session start (CLAUDE.md: Start here) =="
echo
echo "-- git --"
with_deadline 3 git status --short --branch | head -n 20 || echo "(git unavailable)"
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
exit 0
