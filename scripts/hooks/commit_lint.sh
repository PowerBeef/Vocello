#!/usr/bin/env bash
# Claude Code PreToolUse hook (matcher: Bash): the commit and push lint.
#
# Fired for every Bash tool call. git_commands.py lists every `git commit` and
# `git push` in the command (any global options, quoted `-C` paths, chains,
# subshells, `bash -c`) with the checkout it acts on — the payload cwd, `cd`, or
# `git -C` — not this script's location: $CLAUDE_PROJECT_DIR stays on the main
# checkout while an agent works in a worktree. Each one is judged separately; a
# target set by a variable, `pushd`, `GIT_DIR` or `--git-dir`, or one that an
# earlier `git checkout`/`switch`/`rebase` in the same command may move, fails
# closed.
#
# Commits are allowed in exactly two places: the main checkout on `main`, and a
# Claude Code agent worktree (<repo>/.claude/worktrees/<name>) on its
# `worktree-*` branch, which the lead session later integrates into main.
# Pushes are allowed only from the main checkout on `main`. Commits also need
# clean whitespace in the staged diff and no private path or credential in the
# target's staged files. It finishes in seconds and never builds or tests
# anything: CI on push is the gate.

set -euo pipefail

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
payload="$(cat)"

block() {
  echo "commit lint: BLOCKED — $1" >&2
  echo "$2" >&2
  exit 2
}

actions="$(printf '%s' "$payload" | python3 "$HOOK_DIR/agent_hook_input.py" git-actions)" \
  || block "cannot parse the git command." "Run a plain git commit or push from the checkout."
[[ -n "$actions" ]] || exit 0

tab=$'\t'
while IFS= read -r line; do
  action="${line%%"$tab"*}"
  target="${line#*"$tab"}"
  if [[ "$action" == unresolved ]]; then
    block "cannot tell which checkout this commit or push acts on: $target." \
      "Run git from the checkout itself or with a literal git -C path."
  fi

  top="$(git -C "$target" rev-parse --show-toplevel 2>/dev/null)" \
    || block "$action target is not a git checkout." "Run git from the repository checkout."
  top="$(cd "$top" && pwd -P)"
  git_dir="$(cd "$(git -C "$target" rev-parse --absolute-git-dir)" && pwd -P)"
  common_dir="$(cd "$(git -C "$target" rev-parse --path-format=absolute --git-common-dir)" && pwd -P)"
  main_root="$(dirname "$common_dir")"
  branch="$(git -C "$target" symbolic-ref --quiet --short HEAD 2>/dev/null || true)"

  in_main_checkout=0
  [[ "$git_dir" == "$common_dir" ]] && in_main_checkout=1
  in_agent_worktree=0
  if (( ! in_main_checkout )) && [[ "$(dirname "$top")" == "$main_root/.claude/worktrees" ]]; then
    in_agent_worktree=1
  fi

  if [[ "$action" == push ]]; then
    if (( in_main_checkout )) && [[ "$branch" == main ]]; then
      continue
    fi
    where="${branch:-detached HEAD}"
    if (( in_agent_worktree )); then
      where="$where, agent worktree"
    fi
    block "only main is pushed, from the main checkout (current: $where)." \
      "The lead session integrates agent branches into main (merge --ff-only or cherry-pick), then pushes main."
  fi

  if (( in_main_checkout )); then
    [[ "$branch" == main ]] || block \
      "commits in the main checkout are made directly on main (current: ${branch:-detached HEAD})." \
      "Return to main without discarding work; agent work belongs in a .claude/worktrees/<name> worktree."
  elif (( in_agent_worktree )); then
    [[ "$branch" == worktree-* ]] || block \
      "agent worktrees commit only on their worktree-* branch (current: ${branch:-detached HEAD})." \
      "Create worktrees through Agent isolation or EnterWorktree; never check out main or another branch there."
  else
    block "commits happen on main or in a Claude Code agent worktree under .claude/worktrees/ (Main only)." \
      "This checkout is a linked worktree outside .claude/worktrees/; move the work to main or an agent worktree."
  fi

  if ! git -C "$top" diff --cached --check >/dev/null 2>&1; then
    block "staged changes contain whitespace errors (git diff --cached --check)." "Fix the whitespace and re-stage."
  fi

  if ! python3 "$HOOK_DIR/../privacy_scan.py" --root "$top" --staged; then
    block "staged content contains a private path or credential-shaped token." "Remove it from the staged files."
  fi
done <<< "$actions"

exit 0
