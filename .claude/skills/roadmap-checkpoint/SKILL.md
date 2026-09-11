---
name: roadmap-checkpoint
description: Record progress in the single work authority — update a config/roadmap.json item (status, evidence, date), add the dated narrative block to docs/development-progress.md, validate and re-render docs/ROADMAP.md. Use when an item is started, finished, declined or parked.
argument-hint: "<item-id> <planned|in-flight|done|declined|parked> [evidence refs]"
allowed-tools: Bash(python3 scripts/roadmap.py *) Bash(python3 scripts/refresh_derived_artifacts.py *) Bash(git log*) Bash(git rev-parse*) Bash(git status*) Read Grep Edit
---

# Roadmap checkpoint

Authority: `config/roadmap.json` (validated by `scripts/roadmap.py`); `docs/ROADMAP.md` is generated.
Evidence must resolve: `commit:<sha>` reachable from `main`, `file:<path>`, `doc:<path>#<anchor>`,
`benchmark:<record>`. A `done` item needs evidence; `declined` needs `reason`; `parked` needs
`unparkWhen`. The narrative checkpoint is not a second ledger.

## Current status

!`python3 scripts/roadmap.py status 2>/dev/null | head -25`

## Steps

1. Parse `$ARGUMENTS` as `<item-id> <status> [evidence...]`. Locate the item in `config/roadmap.json`.
2. Edit that item only: `status`, `updated` (today, ISO), `evidence` (append resolvable refs), and a
   one-line `notes` entry when the disposition needs a sentence. Do not rewrite other items.
3. Add a dated `###` block at the top of the "Resume now" area of `docs/development-progress.md`:
   what changed, what evidence, what is next. Keep it to a paragraph.
4. `python3 scripts/roadmap.py validate` then `scripts/dev.sh regen` (re-renders `docs/ROADMAP.md`).
5. Report the item, its new status, and any validator warnings that name it.
