#!/usr/bin/env bash
# Claude Code SessionStart hook: branch and dirty state, open agent worktrees, dev.sh status, one cache-health
# line and the first "Resume now" checkpoint of docs/development-progress.md. Local-only, bounded, never fails.
# It runs under the macOS system bash 3.2; besides `scripts/dev.sh status` it uses only git, awk, df and perl.

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$root" 2>/dev/null || exit 0

# The checkpoint print stops near this many bytes, at a bullet or line boundary.
checkpoint_cap=4096
# Free space on the repository's volume below this many GiB is reported (audit W-13: the data volume at
# 98% preceded the loss of every Xcode build arena).
free_floor_gib=40

with_deadline() {
  # perl is always present on macOS; coreutils `timeout` is not.
  perl -e 'alarm shift @ARGV; exec @ARGV' "$@" 2>/dev/null
}

public_links() {
  # The `path` of each `publicLinks` entry in config/build-output-policy.json.
  [[ -f config/build-output-policy.json ]] || return 0
  awk '
    /"publicLinks"[ \t]*:/ { on = 1 }
    !on { next }
    {
      line = $0
      while (match(line, /"path"[ \t]*:[ \t]*"[^"]*"/)) {
        value = substr(line, RSTART, RLENGTH)
        sub(/^"path"[ \t]*:[ \t]*"/, "", value)
        sub(/"$/, "", value)
        print value
        line = substr(line, RSTART + RLENGTH)
      }
      opened += gsub(/\[/, "[")
      closed += gsub(/\]/, "]")
      if (opened > 0 && closed >= opened) exit
    }
  ' config/build-output-policy.json 2>/dev/null
}

cache_health() {
  local links link dangling="" count=0 available_kb notes=""
  links="$(public_links)"
  [[ -n "$links" ]] || links="$(printf '%s\n' build/vocello build/Vocello.app)"
  while IFS= read -r link; do
    [[ -n "$link" ]] || continue
    if [[ -L "$link" && ! -e "$link" ]]; then
      dangling="${dangling:+$dangling and }$link"
      count=$((count + 1))
    fi
  done <<EOF
$links
EOF
  if [[ -n "$dangling" ]]; then
    if (( count == 1 )); then notes="$dangling dangles"; else notes="$dangling dangle"; fi
    notes="$notes (a lost Xcode build arena: the next native build is cold, never a measurement)"
  fi
  # POSIX df output; Available is the field before the Capacity percentage, whatever the device name holds.
  available_kb="$(with_deadline 2 df -Pk . \
    | awk 'NR == 2 { for (i = 2; i <= NF; i++) if ($i ~ /^[0-9]+%$/) { print $(i - 1); exit } }')"
  case "$available_kb" in
    ''|*[!0-9]*)
      notes="${notes:+$notes; }free space unknown" ;;
    *)
      if (( available_kb < free_floor_gib * 1024 * 1024 )); then
        notes="${notes:+$notes; }$((available_kb / 1024 / 1024)) GiB free on the repository volume,"
        notes="$notes below the ${free_floor_gib} GiB floor"
      fi ;;
  esac
  if [[ -n "$notes" ]]; then
    echo "cache health: WARN $notes"
  else
    echo "cache health: ok ($((available_kb / 1024 / 1024)) GiB free; no public build link dangles)"
  fi
}

print_first_checkpoint() {
  # From the first `### ` under `## Resume now` up to the next `### ` or `## `. Over the cap, whole lines are
  # kept up to a line that starts a bullet, a blank line or a heading, then one pointer line.
  LC_ALL=C awk -v cap="$checkpoint_cap" '
    /^## Resume now/ { on = 1; next }
    !on { next }
    /^## / { exit }
    /^### / { if (seen) exit; seen = 1 }
    n == 0 && /^[ \t]*$/ { next }
    { line[++n] = $0 }
    function boundary(text) {
      return text ~ /^[ \t]*$/ || text ~ /^#/ || text ~ /^[ \t]*([-*+]|[0-9]+[.)])[ \t]/
    }
    END {
      if (!on) { print "(no Resume now section)"; exit }
      while (n > 0 && line[n] ~ /^[ \t]*$/) n--
      total = 0
      for (i = 1; i <= n; i++) total += length(line[i]) + 1
      if (total <= cap) {
        for (i = 1; i <= n; i++) print line[i]
        exit
      }
      pointer = "[cut at about " cap " bytes; the rest of this checkpoint is in docs/development-progress.md]"
      budget = cap - length(pointer) - 1
      used = 0
      fit = 0
      for (i = 1; i <= n; i++) {
        used += length(line[i]) + 1
        if (used > budget) break
        fit = i
      }
      cut = fit
      while (cut > 1 && !boundary(line[cut + 1])) cut--
      if (cut <= 1 && fit > 1 && !boundary(line[2])) cut = fit
      if (cut < 1) print substr(line[1], 1, budget)
      for (i = 1; i <= cut; i++) print line[i]
      print pointer
    }
  ' docs/development-progress.md 2>/dev/null
}

echo "== Vocello session start (CLAUDE.md: Start here) =="
echo "Repository hook reached this session. Run scripts/dev.sh doctor for configuration/trust limitations."
echo
echo "-- git --"
with_deadline 3 git status --short --branch | head -n 20 || echo "(git unavailable)"
worktrees="$(with_deadline 3 git worktree list 2>/dev/null | tail -n +2 | head -n 8)"
if [[ -n "$worktrees" ]]; then
  echo
  echo "-- agent worktrees (integrate into main or remove) --"
  printf '%s\n' "$worktrees"
fi
echo
echo "-- scripts/dev.sh status --"
with_deadline 6 scripts/dev.sh status 2>&1 | head -n 12 || echo "(status unavailable)"
echo
cache_health || echo "cache health: unavailable"
echo
echo "-- docs/development-progress.md: Resume now --"
if [[ -f docs/development-progress.md ]]; then
  print_first_checkpoint || echo "(checkpoint unavailable)"
else
  echo "(missing)"
fi
exit 0
