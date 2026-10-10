#!/usr/bin/env bash
# Codex PreToolUse hook (Bash): commit and push lint; --staged runs it directly.
#
# Fired for every Bash tool call. git_commands.py lists every `git commit` and
# `git push` in the command (any global options, quoted `-C` paths, chains,
# subshells, `bash -c`) with the checkout it acts on — the payload cwd, `cd`, or
# `git -C` — not this script's location: the hook may be installed on the main
# checkout while an agent works in a worktree. Each one is judged separately; a
# target set by a variable, `pushd`, `GIT_DIR` or `--git-dir`, or one that an
# earlier `git checkout`/`switch`/`rebase` in the same command may move, fails
# closed.
#
# Commits are allowed in exactly two places: the main checkout on `main`, and a
# registered linked worktree on a `codex/*` branch, which the lead integrates.
# Pushes are allowed only from the main checkout on `main`. Commits also need
# clean whitespace in the staged diff and no private path or credential in the
# staged blobs; a commit that takes more than the index holds when the hook runs
# (an earlier `git add` in the same command, `-a`, `--only`, a pathspec) is also
# checked on the working tree's changed and untracked files. It finishes in
# seconds and never builds or tests anything: CI on push is the gate.

set -euo pipefail

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" == --staged ]]; then
  payload="$(python3 -c 'import json, os; print(json.dumps({"cwd":os.getcwd(), "tool_input":{"command":"git commit"}}))')"
else
  payload="$(cat)"
fi

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
  # A commit that records more than the index holds now (an earlier `git add` in
  # the same command, `-a`, `--only`, a pathspec) is also checked on the working
  # tree, scoped to what it takes: `paths` (literal pathspecs), `tracked` changes
  # or `all` changed and untracked files.
  scope=index
  taken_paths=()
  if [[ "$action" == commit-worktree ]]; then
    IFS="$tab" read -r -a fields <<< "$line"
    action=commit
    target="${fields[1]}"
    scope="${fields[2]}"
    taken_paths=("${fields[@]:3}")
  fi
  if [[ "$action" == unresolved ]]; then
    block "cannot tell which checkout this commit or push acts on: $target." \
      "Run git from the checkout itself or with a literal git -C path."
  fi

  top="$(git -C "$target" rev-parse --show-toplevel 2>/dev/null)" \
    || block "$action target is not a git checkout." "Run git from the repository checkout."
  top="$(cd "$top" && pwd -P)"
  git_dir="$(cd "$(git -C "$target" rev-parse --absolute-git-dir)" && pwd -P)"
  common_dir="$(cd "$(git -C "$target" rev-parse --path-format=absolute --git-common-dir)" && pwd -P)"
  hook_root="$(cd "$HOOK_DIR/../.." && pwd -P)"
  hook_common="$(git -C "$hook_root" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" \
    || block "hook installation is not a repository checkout." "Use the repository's own commit check."
  hook_common="$(cd "$hook_common" && pwd -P)"
  [[ "$common_dir" == "$hook_common" ]] || block \
    "target belongs to another repository." "Use the commit check installed in that repository."
  branch="$(git -C "$target" symbolic-ref --quiet --short HEAD 2>/dev/null || true)"

  in_main_checkout=0
  [[ "$git_dir" == "$common_dir" ]] && in_main_checkout=1
  in_agent_worktree=0
  if (( ! in_main_checkout )) && [[ "$git_dir" == "$common_dir"/worktrees/* ]]; then
    # Registration, not a directory spelling, establishes linked checkout identity.
    registered="$(git -C "$target" worktree list --porcelain | sed -n 's/^worktree //p')"
    while IFS= read -r registered_root; do
      [[ "$registered_root" == "$top" ]] && in_agent_worktree=1
    done <<< "$registered"
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
      "Return to main without discarding work; agent work belongs in a Codex-managed linked worktree."
  elif (( in_agent_worktree )); then
    [[ "$branch" == codex/* ]] || block \
      "agent worktrees commit only on their codex/* branch (current: ${branch:-detached HEAD})." \
      "Use a Codex-managed worktree and a scoped codex/ branch based on the lead checkpoint."
  else
    block "commits happen on main or in a registered Codex linked worktree (AGENTS.md)." \
      "Use a registered worktree in this repository."
  fi

  if ! git -C "$top" diff --cached --check >/dev/null 2>&1; then
    block "staged changes contain whitespace errors (git diff --cached --check)." "Fix the whitespace and re-stage."
  fi

  if ! python3 "$HOOK_DIR/../privacy_scan.py" --root "$top" --staged; then
    block "staged content contains a private path or credential-shaped token." "Remove it from the staged files."
  fi

  whitespace_ok=1
  private_ok=1
  case "$scope" in
    all)
      git -C "$top" diff --check >/dev/null 2>&1 || whitespace_ok=0
      python3 "$HOOK_DIR/../privacy_scan.py" --root "$top" --changes || private_ok=0 ;;
    tracked)
      git -C "$top" diff --check >/dev/null 2>&1 || whitespace_ok=0
      python3 "$HOOK_DIR/../privacy_scan.py" --root "$top" --tracked-changes || private_ok=0 ;;
  esac
  if [[ "$scope" != index && "$scope" != all ]] && (( ${#taken_paths[@]} > 0 )); then
    git -C "$target" diff --check -- "${taken_paths[@]}" >/dev/null 2>&1 || whitespace_ok=0
    python3 "$HOOK_DIR/../privacy_scan.py" --root "$target" --worktree-paths "${taken_paths[@]}" || private_ok=0
  fi
  (( whitespace_ok )) || block \
    "working-tree changes this commit records contain whitespace errors (git diff --check)." \
    "Fix the whitespace."
  (( private_ok )) || block \
    "a working-tree file this commit records contains a private path or credential-shaped token." \
    "Remove it from the file."
done <<< "$actions"

exit 0
