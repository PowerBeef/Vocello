---
name: refresh-docs
description: Regenerate derived documentation artifacts (indexes, roadmap render, health, catalog, facts, charts), validate documentation metadata, and handle contentDigest re-pins for deliberately edited historical docs. Use after editing docs, config contracts, roadmap.json or Sources/Resources catalogs.
allowed-tools: Bash(python3 scripts/refresh_derived_artifacts.py *) Bash(python3 scripts/doc_metadata.py *) Bash(python3 scripts/documentation_contract.py *) Bash(python3 scripts/roadmap.py *) Bash(python3 scripts/check_surface_coverage.py*) Bash(git status*) Bash(git add*) Bash(git diff*) Read Grep Edit
---

# Refresh derived documentation

Authority: `.claude/rules/derived-artifacts.md`. Generated files are never hand-edited: `docs/INDEX.md`,
`docs/INDEX.json`, `docs/ROADMAP.md`, `docs/project-health.md`, `config/derived-doc-facts.json`,
`Sources/Resources/qwenvoice_production_model_catalog.json`, `docs/charts/*.svg`, `benchmarks/HISTORY.md`.

## Steps

1. `git add -A` for new or moved tracked files first (project health counts tracked files).
2. `python3 scripts/refresh_derived_artifacts.py status`, then `refresh`, then `validate`.
3. `python3 scripts/doc_metadata.py validate` and `python3 scripts/documentation_contract.py validate`.
4. For each `contentDigest` error: ask whether the edit to that historical or superseded body was
   deliberate. If yes, recompute the digest of the body (everything after the closing `---` line) with
   `python3 -c` and SHA-256, update the `contentDigest:` line, and rerun step 3. If no, revert the edit.
5. `python3 scripts/check_surface_coverage.py`: a new gate or `config/*.json` must be named in
   `CLAUDE.md` or a `.claude/rules/*.md`, or exempted with a reason in
   `config/surface-coverage-exemptions.json`.
6. Report which artifacts were rebuilt and which docs were re-pinned.

Narrative documents (`docs/development-progress.md`, ADRs) are deliberate edits and are never rewritten
by this skill.
