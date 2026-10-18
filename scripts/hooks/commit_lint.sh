#!/usr/bin/env bash
# Claude Code PreToolUse hook (Bash): commit and push lint; --staged runs it directly.
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
# registered linked worktree on a `worktree-*` branch (a Claude Code agent
# worktree under .claude/worktrees), which the lead integrates.
# Pushes are allowed only from the main checkout on `main`. Commits also need
# clean whitespace in the staged diff and no private path or credential in the
# staged blobs; a commit that takes more than the index holds when the hook runs
# (an earlier `git add` in the same command, `-a`, `--only`, a pathspec) is also
# checked on the working tree's changed and untracked files. It finishes in
# seconds and never builds or tests anything: CI on push is the gate.
#
# One check only advises. A commit that records behaviour-bearing Swift sources
# (Sources/QwenVoiceCore, Sources/iOS, Sources/Services, Sources/ViewModels,
# Packages/*/Sources) while its message lacks the `Reviewed-by:
# vocello-swift-review` trailer gets a warning as the hook's additionalContext,
# never a block. A message the hook cannot read (an editor, a substitution, a
# parser error) skips the warning.

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

REVIEW_TRAILER="Reviewed-by: vocello-swift-review"
REVIEW_SOURCES='^(Sources/(QwenVoiceCore|iOS|Services|ViewModels)|Packages/[^/]+/Sources)/.+[.]swift$'

# The behaviour-bearing Swift sources a commit records: the index, plus what its
# scope takes from the working tree. Arguments: top, target, scope, paths...
review_sources() {
  local top="$1" target="$2" scope="$3"
  shift 3
  {
    git -C "$top" diff --cached --name-only
    case "$scope" in
      all) git -C "$top" diff --name-only
           git -C "$top" ls-files --others --exclude-standard ;;
      tracked) git -C "$top" diff --name-only ;;
    esac
    if [[ "$scope" != index && "$scope" != all ]] && (( $# > 0 )); then
      git -C "$target" diff --name-only -- "$@"
      git -C "$target" ls-files --full-name --others --exclude-standard -- "$@"
    fi
  } 2>/dev/null | grep -E "$REVIEW_SOURCES" | sort -u || true
}

# Whether the commit messages carry the review trailer: `present`, `absent` (every
# message is readable and lacks it) or `unknown`; any error is `unknown`. A message
# is read from the command text (-m, a heredoc, --trailer), an -F file, the commit
# that -C/-c reuses or, for --amend without a new message, HEAD.
review_trailer_state() {
  REVIEW_PAYLOAD="$payload" python3 - "$HOOK_DIR" <<'PY' 2>/dev/null || echo unknown
import json
import os
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, sys.argv[1])
import git_commands  # noqa: E402

TRAILER = re.compile(r"(?i)\breviewed-by[ \t]*[:=][ \t]*vocello-swift-review\b")
LONG = ("--message", "--file", "--reuse-message", "--reedit-message", "--fixup", "--squash", "--amend")
SHORT = {"m": "--message", "F": "--file", "C": "--reuse-message", "c": "--reedit-message"}


def options(args):
    """(option, value) for each commit option, long names completed, values attached."""
    index = 0
    while index < len(args):
        argument = args[index]
        index += 1
        if argument == "--":
            return
        if argument.startswith("--"):
            name, has_value, value = argument.partition("=")
            name = git_commands._long(name, *LONG) or name
            if name in git_commands.COMMIT_VALUE_OPTIONS and not has_value:
                value = args[index] if index < len(args) else ""
                index += 1
            yield name, value
        elif argument.startswith("-") and len(argument) > 1:
            for position, letter in enumerate(argument[1:], 1):
                if letter in "Su":
                    break                                # `-S<keyid>`, `-u<mode>`
                if letter in git_commands.COMMIT_VALUE_SHORT:
                    value = argument[position + 1:]
                    if not value:
                        value = args[index] if index < len(args) else ""
                        index += 1
                    yield SHORT.get(letter, "-" + letter), value
                    break


def revision_message(directory, revision):
    if directory is None or not revision or revision.startswith("-"):
        return None
    result = subprocess.run(["git", "-C", str(directory), "log", "-1", "--format=%B", revision, "--"],
                            capture_output=True, text=True, timeout=5, check=False)
    return result.stdout if result.returncode == 0 else None


def file_message(directory, value):
    if directory is None or not value or "$" in value or "`" in value:
        return None
    try:
        return (directory / value).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def message(invocation, heredoc):
    """The texts a commit's message holds beyond the command text, or None when unreadable."""
    texts, known, amend = [], False, False
    for option, value in options(invocation.args):
        if option == "--amend":
            amend = True
        elif option in ("--fixup", "--squash"):
            return None
        elif option == "--message":
            # A computed message is unreadable; a `$(cat <<EOF ...)` body is in the command text.
            if "`" in value or ("$" in value and "<<HEREDOC" not in value):
                return None
            known = True
        elif option == "--file":
            text = ("" if heredoc else None) if value == "-" else file_message(invocation.directory, value)
            if text is None:
                return None
            texts.append(text)
            known = True
        elif option in ("--reuse-message", "--reedit-message"):
            text = revision_message(invocation.directory, value)
            if text is None:
                return None
            texts.append(text)
            known = True
    if amend and not known:
        text = revision_message(invocation.directory, "HEAD")
        return None if text is None else [text]
    return texts if known else None


def state():
    payload = json.loads(os.environ["REVIEW_PAYLOAD"])
    command = payload["tool_input"]["command"]
    if TRAILER.search(command):
        return "present"
    heredoc = bool(git_commands.strip_heredocs(command)[1])
    cwd = Path(payload.get("cwd") or os.getcwd())
    messages = [message(invocation, heredoc) for invocation in git_commands.git_invocations(command, cwd)
                if invocation.subcommand == "commit"]
    if not messages or any(texts is None for texts in messages):
        return "unknown"
    if any(TRAILER.search(text) for texts in messages for text in texts):
        return "present"
    return "absent"


try:
    print(state())
except Exception:  # noqa: BLE001 - the advice is optional; a parser defect never blocks a commit
    print("unknown")
PY
}

# The advisory, as PreToolUse additionalContext on stdout and as text on stderr.
review_advice() {
  local more=""
  if (( $2 > 1 )); then
    more=" and $(( $2 - 1 )) more"
  fi
  local text="commit lint: advisory — this commit changes behaviour-bearing Swift ($1$more) but its message has no \`$REVIEW_TRAILER\` trailer. Run the vocello-swift-review agent on the diff, test-adequacy checks included, and record the review with \`git commit --trailer '$REVIEW_TRAILER'\`. Nothing is blocked."
  echo "$text" >&2
  REVIEW_TEXT="$text" python3 -c 'import json, os; print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "PreToolUse", "additionalContext": os.environ["REVIEW_TEXT"]}}))' 2>/dev/null || true
}

actions="$(printf '%s' "$payload" | python3 "$HOOK_DIR/agent_hook_input.py" git-actions)" \
  || block "cannot parse the git command." "Run a plain git commit or push from the checkout."
[[ -n "$actions" ]] || exit 0

tab=$'\t'
reviewed_sources=()
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
      "Return to main without discarding work; agent work belongs in a Claude Code agent worktree (.claude/worktrees/<name>)."
  elif (( in_agent_worktree )); then
    [[ "$branch" == worktree-* ]] || block \
      "agent worktrees commit only on their worktree-* branch (current: ${branch:-detached HEAD})." \
      "Create agent worktrees through Agent isolation or EnterWorktree; the lead integrates them."
  else
    block "commits happen on main or in a registered Claude Code agent worktree (CLAUDE.md: Main is the only published branch)." \
      "Use a registered worktree in this repository."
  fi

  if ! git -C "$top" diff --cached --check >/dev/null 2>&1; then
    block "staged changes contain whitespace errors (git diff --cached --check)." "Fix the whitespace and re-stage."
  fi

  # The scans' PASS lines go to stderr: the hook's stdout carries only its JSON advice.
  if ! python3 "$HOOK_DIR/../privacy_scan.py" --root "$top" --staged >&2; then
    block "staged content contains a private path or credential-shaped token." "Remove it from the staged files."
  fi

  whitespace_ok=1
  private_ok=1
  case "$scope" in
    all)
      git -C "$top" diff --check >/dev/null 2>&1 || whitespace_ok=0
      python3 "$HOOK_DIR/../privacy_scan.py" --root "$top" --changes >&2 || private_ok=0 ;;
    tracked)
      git -C "$top" diff --check >/dev/null 2>&1 || whitespace_ok=0
      python3 "$HOOK_DIR/../privacy_scan.py" --root "$top" --tracked-changes >&2 || private_ok=0 ;;
  esac
  if [[ "$scope" != index && "$scope" != all ]] && (( ${#taken_paths[@]} > 0 )); then
    git -C "$target" diff --check -- "${taken_paths[@]}" >/dev/null 2>&1 || whitespace_ok=0
    python3 "$HOOK_DIR/../privacy_scan.py" --root "$target" --worktree-paths "${taken_paths[@]}" >&2 \
      || private_ok=0
  fi
  (( whitespace_ok )) || block \
    "working-tree changes this commit records contain whitespace errors (git diff --check)." \
    "Fix the whitespace."
  (( private_ok )) || block \
    "a working-tree file this commit records contains a private path or credential-shaped token." \
    "Remove it from the file."

  while IFS= read -r source; do
    if [[ -n "$source" ]]; then
      reviewed_sources+=("$source")
    fi
  done <<<"$(review_sources "$top" "$target" "$scope" ${taken_paths[@]+"${taken_paths[@]}"})"
done <<< "$actions"

# Advisory only: every block above has passed, and nothing here changes the exit status.
if (( ${#reviewed_sources[@]} > 0 )) && [[ "$(review_trailer_state)" == absent ]]; then
  review_advice "${reviewed_sources[0]}" "${#reviewed_sources[@]}"
fi

exit 0
