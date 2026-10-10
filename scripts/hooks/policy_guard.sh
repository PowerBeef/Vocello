#!/usr/bin/env bash
# Codex PreToolUse hook (matcher: Bash): repository policy guard.
#
# Reads the hook JSON from stdin and inspects `tool_input.command`. It blocks
# (exit 2, reason on stderr) the handful of shell commands that violate a hard
# invariant in AGENTS.md regardless of intent:
#
#   * Simulator destinations and simulator lifecycle commands (Physical iPhone only)
#   * whole build-cache deletion outside scripts/clean_build_caches.sh (Owned output)
#   * force pushes, pushes of any ref but main, hand-made branches and
#     worktrees, and ref rewrites (Main is the only published branch; agent
#     worktrees come only from Codex managed-worktree tools)
#   * shell writes to QwenVoice.xcodeproj/project.pbxproj (Generated project)
#
# Everything else exits 0 immediately. The Simulator, cache and pbxproj checks
# are bash pattern matching (patterns live in variables so macOS bash 3.2 parses
# them); git commands are tokenized by git_commands.py. It finishes in
# milliseconds and never runs git, xcodebuild or python beyond parsing stdin.
#
# The unsupported-destination words are assembled from fragments so this file
# never contains the literal strings that scripts/repo_invariants.sh
# rejects across the active tree.

set -euo pipefail

# Heredoc bodies are data, not commands: a commit message or a generated file that
# merely mentions a guarded pattern must not trip the guard. They are stripped
# before matching, except a body fed to a shell (`bash <<EOF`), which is commands;
# everything else in the command line is inspected verbatim.
HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
payload="$(cat)"
command_text="$(printf '%s' "$payload" | python3 "$HOOK_DIR/agent_hook_input.py" policy-command)"

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
# A pattern never reaches across a command separator or a line.
nl=$'\n'
same_command="[^;&|${nl}]*"
re_sim_destination="platform=(ios|watchos|tvos|visionos|xros)\\\\?[[:space:]]*${lower_sim}"
re_sim_sdk="(iphone${lower_sim}|apple-(ios|watchos|tvos|xros)[0-9.]*-${lower_sim}([^a-z]|$))"
re_sim_app="open[[:space:]]${same_command}(-[a-z]*a[[:space:]]+[\"']?([^[:space:]]*/)?${lower_sim}|${lower_sim}\\.app|core${lower_sim})"
re_simctl_lifecycle="simctl[[:space:]]+(${same_command}[[:space:]])?(boot|bootstatus|create|erase|launch|install|uninstall|shutdown|spawn|openurl|io|delete|clone|terminate)([[:space:]]|$)"
re_sim_tools="(build_run|test|launch|boot|install_app)${sim_suffix}([^a-z_]|$)"
if [[ "$lower_command" =~ $re_sim_destination ]] \
  || [[ "$lower_command" =~ $re_sim_sdk ]] \
  || [[ "$lower_command" =~ $re_sim_app ]] \
  || [[ "$lower_command" =~ $re_simctl_lifecycle ]] \
  || [[ "$lower_command" =~ $re_sim_tools ]]; then
  block "Simulator destinations are unsupported (AGENTS.md: Physical iPhone only)." \
    "Use the paired iPhone through scripts/ui_test.sh ios <lane> or scripts/ios_device.sh, or the macOS lanes."
fi

# 2. Owned output: no whole-cache deletion. agent_hook_input.py judges each simple
# command on its words (rm, find -delete, mv), resolving paths against the
# directory it runs in; it also reports a copy onto the generated project file.
file_violation="$(printf '%s' "$payload" | python3 "$HOOK_DIR/agent_hook_input.py" file-policy)"
if [[ "$file_violation" == build ]]; then
  block "whole build-output deletion bypasses config/build-output-policy.json (AGENTS.md: Owned output)." \
    "Use scripts/clean_build_caches.sh with one selective --cache target, or the retention pruning it owns."
fi

# 3. Main is the only published branch. Git commands are judged on their tokens
# (global options, quoted -C paths, chains, subshells, bash -c) by git_commands.py.
git_violation="$(printf '%s' "$payload" | python3 "$HOOK_DIR/agent_hook_input.py" git-policy)"
if [[ -n "$git_violation" ]]; then
  tab=$'\t'
  category="${git_violation%%"$tab"*}"
  reason="${git_violation#*"$tab"}"
  case "$category" in
    force)
      block "$reason (AGENTS.md: Main is the only published branch, Git/release)." \
        "Push fast-forward commits only; CI required protects main." ;;
    push|config)
      block "$reason; only main is ever pushed (AGENTS.md: Main is the only published branch)." \
        "Integrate agent branches into main locally, then push main; release tags are maintainer-run." ;;
    *)
      block "$reason (AGENTS.md: Main is the only published branch)." \
        "Work on main, or use a Codex-managed worktree and codex/ branch; the lead integrates it." ;;
  esac
fi

# 4. Generated project.
re_pbxproj_write='(sed[[:space:]]+-[A-Za-z]*i|perl[[:space:]]+-[A-Za-z]*i|tee[[:space:]]|>>?[[:space:]]*)[^|;&]*project\.pbxproj'
if [[ "$command_text" =~ $re_pbxproj_write ]] || [[ "$file_violation" == pbxproj ]]; then
  block "QwenVoice.xcodeproj/project.pbxproj is generated (AGENTS.md: Generated project)." \
    "Edit project.yml and run ./scripts/regenerate_project.sh --fast."
fi

exit 0
