---
name: checkpoint
description: Run the repository's local verification for the current dirty tree (scripts/dev.sh check) and then commit on main. Use before any commit, or when asked to "verify", "run the gate", "checkpoint" or "commit".
argument-hint: "[commit subject]"
allowed-tools: Bash(scripts/dev.sh *) Bash(./scripts/dev.sh *) Bash(git status*) Bash(git diff*) Bash(git add*) Bash(git commit*) Bash(git log*) Bash(python3 scripts/refresh_derived_artifacts.py *) Bash(./scripts/regenerate_project.sh*) Read Grep
---

# Verify and commit

Authority: `docs/reference/development-workflow.md`. Nothing blocks a commit except the commit lint hook
(branch `main`, clean whitespace, no private path or credential in staged files). CI on `main` is the gate.

## Current tree

!`git status --short --branch | head -40`

## Steps

1. Require branch `main`. If not on `main`, stop and report; never create a branch.
2. If `project.yml` changed, run `./scripts/regenerate_project.sh --fast` first.
3. `git add -A` for files that belong to this change, then `scripts/dev.sh check --dry-run` and show the
   lanes and commands it will run.
4. `scripts/dev.sh check`. For a long run, delegate it to the `gate-runner` subagent so only failures
   return to the main context.
5. On failure: quote the failing `==> [dev N/M] <command>` line and the first relevant error lines, fix
   the cause, and rerun. Do not weaken a gate or add an exemption to get green.
6. On success: `git add -A`, then `git commit` with a subject in the repository style (imperative, ≤ 72
   chars) and the attribution trailer the session provides. Do not push unless asked.
7. Report: what was verified (commands), the elapsed time, and the commit hash.
