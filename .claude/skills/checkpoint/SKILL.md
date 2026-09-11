---
name: checkpoint
description: Run the repository's deterministic verification for the current dirty tree (plan, focused, checkpoint) and then commit on main. Use before any commit, or when asked to "verify", "run the gate", "checkpoint" or "commit".
argument-hint: "[--full] [commit subject]"
allowed-tools: Bash(scripts/dev.sh *) Bash(./scripts/dev.sh *) Bash(git status*) Bash(git diff*) Bash(git add*) Bash(git commit*) Bash(git log*) Bash(python3 scripts/refresh_derived_artifacts.py *) Bash(./scripts/regenerate_project.sh*) Read Grep
---

# Checkpoint and commit

Authority: `docs/reference/development-workflow.md`. The commit hook accepts only a receipt for the exact
tree and toolchain; any edit after the checkpoint invalidates it. Never set `QVOICE_SKIP_COMMIT_GATE`.

## Current tree

!`git status --short --branch | head -40`

## Steps

1. Require branch `main`. If not on `main`, stop and report; never create a branch.
2. If `project.yml` changed, run `./scripts/regenerate_project.sh --fast` first.
3. `git add -A` for files that belong to this change (generated artifacts count tracked files), then
   `scripts/dev.sh plan` and show the classification and the commands it will run.
4. `scripts/dev.sh focused` while iterating; when the tree is coherent run
   `scripts/dev.sh checkpoint $ARGUMENTS` (pass `--full` for tooling, config or governance changes, or
   when the plan says "full").
5. On failure: quote the failing `==> [dev N/M] <command>` line and the first relevant error lines, fix
   the cause, and rerun. Do not weaken a gate, add an exemption or bypass the hook to get green.
6. On PASS: `git add -A`, then `git commit` with a subject in the repository style (imperative, ≤ 72
   chars) and the attribution trailer the session provides. Do not push unless asked.
7. Report: what was verified (commands), the elapsed time, and the commit hash.

For a long checkpoint, delegate the run to the `gate-runner` subagent so only failures return to the
main context.
