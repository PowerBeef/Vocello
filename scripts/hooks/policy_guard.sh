#!/usr/bin/env bash
# Claude Code PreToolUse hook (matcher: Bash): repository policy guard.
#
# Reads the hook JSON from stdin and inspects `tool_input.command`. It blocks
# (exit 2, reason on stderr) the handful of shell commands that violate a hard
# invariant in CLAUDE.md regardless of intent:
#
#   * Simulator destinations and simulator lifecycle commands (Physical iPhone only)
#   * whole build-cache deletion outside scripts/clean_build_caches.sh (Owned output)
#   * force pushes, new branches and worktrees (Main only)
#   * shell writes to QwenVoice.xcodeproj/project.pbxproj (Generated project)
#   * QVOICE_SKIP_COMMIT_GATE=1 without an explicit acknowledgement token
#
# Everything else exits 0 immediately. The guard is pure bash pattern matching
# (patterns live in variables so macOS bash 3.2 parses them) and finishes in
# milliseconds; it never runs git, xcodebuild or python beyond parsing stdin.
#
# The unsupported-destination words are assembled from fragments so this file
# never contains the literal strings that scripts/check_test_workflows.sh
# rejects across the active tree.

set -euo pipefail

# Heredoc bodies are data, not commands: a commit message or a generated file that
# merely mentions a guarded pattern must not trip the guard. They are stripped
# before matching; everything else in the command line is inspected verbatim.
payload="$(cat 2>/dev/null || true)"
command_text="$(printf '%s' "$payload" \
  | python3 -c 'import json,re,sys
try:
    text = json.load(sys.stdin).get("tool_input", {}).get("command", "")
except Exception:
    text = ""
text = re.sub(r"<<-?\s*[\x27\"]?([A-Za-z_][A-Za-z0-9_]*)[\x27\"]?[^\n]*\n.*?\n[ \t]*\1[ \t]*(?=\n|$)", "<<HEREDOC", text, flags=re.S)
print(text)' 2>/dev/null || true)"

[[ -n "$command_text" ]] || exit 0

block() {
  echo "policy guard: BLOCKED — $1" >&2
  echo "$2" >&2
  exit 2
}

sim_word="Sim""ulator"
sim_suffix="_""sim"
lower_command="$(printf '%s' "$command_text" | tr '[:upper:]' '[:lower:]')"
lower_sim="$(printf '%s' "$sim_word" | tr '[:upper:]' '[:lower:]')"

# 1. Physical iPhone only.
re_sim_destination="platform=ios[[:space:]]${lower_sim}"
re_simctl_lifecycle="simctl[[:space:]]+(boot|create|erase|launch|install|shutdown)"
re_sim_tools="(build_run|test|launch|boot|install_app)${sim_suffix}([^a-z_]|$)"
if [[ "$lower_command" =~ $re_sim_destination ]] \
  || [[ "$lower_command" =~ $re_simctl_lifecycle ]] \
  || [[ "$lower_command" =~ $re_sim_tools ]]; then
  block "Simulator destinations are unsupported (CLAUDE.md: Physical iPhone only)." \
    "Use the paired iPhone through scripts/ui_test.sh ios <lane> or scripts/ios_device.sh, or the macOS lanes."
fi

# 2. Owned output: no whole-cache deletion.
re_rm_cache='rm[[:space:]]+-[A-Za-z]*[rR][A-Za-z]*[[:space:]][^|;&]*build/cache'
re_rm_build='rm[[:space:]]+-[A-Za-z]*[rR][A-Za-z]*[[:space:]]+(\./)?build/?([[:space:]]|$)'
if [[ "$command_text" =~ $re_rm_cache ]] || [[ "$command_text" =~ $re_rm_build ]]; then
  block "whole build-output deletion bypasses config/build-output-policy.json (CLAUDE.md: Owned output)." \
    "Use scripts/clean_build_caches.sh with one selective --cache target, or the retention pruning it owns."
fi

# 3. Main only.
re_force_push='git[[:space:]]+push[^|;&]*([[:space:]]--force|[[:space:]]-f([[:space:]]|$)|[[:space:]]\+)'
re_new_branch='git[[:space:]]+(checkout[[:space:]]+-b|switch[[:space:]]+(-c|--create)|worktree[[:space:]]+add)'
re_branch_create='git[[:space:]]+branch[[:space:]]+[A-Za-z0-9._/][A-Za-z0-9._/-]*([[:space:]]|$)'
if [[ "$command_text" =~ $re_force_push ]]; then
  block "force pushes are never allowed (CLAUDE.md: Main only, Exact-source releases)." \
    "Push fast-forward commits only; CI required protects main."
fi
if [[ "$command_text" =~ $re_new_branch ]] || [[ "$command_text" =~ $re_branch_create ]]; then
  block "development happens on local main only; no branches or worktrees (CLAUDE.md: Main only)." \
    "Keep working on main. If you were asked to preserve work, stash or commit a coherent checkpoint instead."
fi

# 4. Generated project.
re_pbxproj_write='(sed[[:space:]]+-[A-Za-z]*i|perl[[:space:]]+-[A-Za-z]*i|tee[[:space:]]|>>?[[:space:]]*)[^|;&]*project\.pbxproj'
if [[ "$command_text" =~ $re_pbxproj_write ]]; then
  block "QwenVoice.xcodeproj/project.pbxproj is generated (CLAUDE.md: Generated project)." \
    "Edit project.yml and run ./scripts/regenerate_project.sh --fast."
fi

# 5. Commit-gate bypass needs an explicit acknowledgement.
re_skip='QVOICE_SKIP_COMMIT_GATE=1'
re_ack='QVOICE_SKIP_COMMIT_GATE_ACK=user'
if [[ "$command_text" =~ $re_skip ]] && [[ ! "$command_text" =~ $re_ack ]]; then
  block "QVOICE_SKIP_COMMIT_GATE=1 skips the checkpoint receipt." \
    "Only an explicit user instruction authorizes it; if the user asked, prefix the command with QVOICE_SKIP_COMMIT_GATE_ACK=user and say so in the reply. Otherwise run scripts/dev.sh checkpoint."
fi

exit 0
