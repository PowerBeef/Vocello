#!/usr/bin/env bash
# Claude Code PreToolUse hook (matcher: Bash): repository policy guard.
#
# Reads the hook JSON from stdin and inspects `tool_input.command`. It blocks
# (exit 2, reason on stderr) the handful of shell commands that violate a hard
# invariant in CLAUDE.md regardless of intent:
#
#   * Simulator destinations and simulator lifecycle commands (Physical iPhone only)
#   * whole build-cache deletion outside scripts/clean_build_caches.sh (Owned output)
#   * force pushes, pushes of any ref but main, hand-made branches and
#     worktrees, and ref rewrites (Main is the only published branch; agent
#     worktrees come only from Claude Code Agent isolation, EnterWorktree or a
#     desktop app session)
#   * shell writes to QwenVoice.xcodeproj/project.pbxproj (Generated project)
#
# Everything else exits 0 immediately. The Simulator and cache checks judge each
# simple command's words in agent_hook_input.py, git commands are tokenized by
# git_commands.py, and the pbxproj check is bash pattern matching (patterns live
# in variables so macOS bash 3.2 parses them). It finishes in milliseconds and
# never runs git, xcodebuild or python beyond parsing stdin.
#
# agent_hook_input.py assembles the unsupported-destination words from fragments,
# so no hook contains the literal strings that scripts/repo_invariants.sh rejects
# across the active tree.

set -euo pipefail

# Heredoc bodies are data, not commands: a commit message or a generated file that
# merely mentions a guarded pattern must not trip the guard. Every check strips
# them, except a body fed to a shell (`bash <<EOF`), which is commands; the pbxproj
# check inspects the rest of the command line verbatim.
HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
payload="$(cat)"
command_text="$(printf '%s' "$payload" | python3 "$HOOK_DIR/agent_hook_input.py" policy-command)"

[[ -n "$command_text" ]] || exit 0

block() {
  echo "policy guard: BLOCKED — $1" >&2
  echo "$2" >&2
  exit 2
}

# 1. Physical iPhone only. agent_hook_input.py judges each simple command on its own
# words: a destination, a Simulator SDK or triple, the Simulator app, a Simulator tool
# route, or any `simctl` subcommand but the maintenance ones (`list`, `runtime list`,
# `runtime delete`, `delete unavailable`, `shutdown all`). Search tools (rg, grep,
# git grep, git log), git commit/tag/merge messages and heredoc bodies are text, not use.
sim_violation="$(printf '%s' "$payload" | python3 "$HOOK_DIR/agent_hook_input.py" simulator-policy)"
if [[ -n "$sim_violation" ]]; then
  block "Simulator destinations are unsupported (CLAUDE.md: Physical iPhone only): $sim_violation." \
    "Use the paired iPhone through scripts/ui_test.sh ios <lane> or scripts/ios_device.sh, or the macOS lanes."
fi

# 2. Owned output: no whole-cache deletion. agent_hook_input.py judges each simple
# command on its words (rm, find -delete, mv), resolving paths against the
# directory it runs in; it also reports a copy onto the generated project file.
file_violation="$(printf '%s' "$payload" | python3 "$HOOK_DIR/agent_hook_input.py" file-policy)"
if [[ "$file_violation" == build ]]; then
  block "whole build-output deletion bypasses config/build-output-policy.json (CLAUDE.md: Owned output)." \
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
      block "$reason (CLAUDE.md: Main is the only published branch)." \
        "Push fast-forward commits only; CI required protects main." ;;
    push|config)
      block "$reason; only main is ever pushed (CLAUDE.md: Main is the only published branch)." \
        "Integrate agent branches into main locally, then push main; release tags are maintainer-run, and iPhone TestFlight candidates go through scripts/ios_candidate_tag.py." ;;
    *)
      block "$reason (CLAUDE.md: Main is the only published branch)." \
        "Work on main, or use a Claude Code agent worktree (Agent isolation, EnterWorktree or a desktop app session); the lead integrates it." ;;
  esac
fi

# 4. Generated project.
re_pbxproj_write='(sed[[:space:]]+-[A-Za-z]*i|perl[[:space:]]+-[A-Za-z]*i|tee[[:space:]]|>>?[[:space:]]*)[^|;&]*project\.pbxproj'
if [[ "$command_text" =~ $re_pbxproj_write ]] || [[ "$file_violation" == pbxproj ]]; then
  block "QwenVoice.xcodeproj/project.pbxproj is generated (CLAUDE.md: Generated project)." \
    "Edit project.yml and run ./scripts/regenerate_project.sh --fast."
fi

exit 0
