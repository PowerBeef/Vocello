---
name: release-evidence
description: Read-only report of release readiness for a tag — source authority (tag, exact-SHA CI and Security checks), quality-promotion evidence and what still blocks a public promotion. Never publishes, signs or dispatches workflows. User-invoked only.
argument-hint: "<tag, e.g. v3.0.0>"
disable-model-invocation: true
allowed-tools: Bash(python3 scripts/release_source_authority.py *) Bash(python3 scripts/quality_promotion.py validate*) Bash(python3 scripts/check_release_notes.py *) Bash(gh run list*) Bash(gh release view*) Bash(git tag*) Bash(git log*) Read Grep
---

# Release evidence (read-only)

Authority: `docs/reference/quality-promotion.md`, `docs/reference/macos-release-qa.md`,
`.claude/rules/release-qa.md`. Candidate production and public promotion are separate; neither is
authorized by this skill. Do not run `scripts/release.sh`, `gh release create|edit`, or any workflow
dispatch.

## Steps

1. Require a tag as the argument. `git tag -l "$0" -n1` and `git log -1 "$0"` to confirm it exists and
   which commit it targets.
2. `python3 scripts/release_source_authority.py --help` then run its validation for the tag: the tag must
   be annotated, on `origin/main`, with the latest exact-SHA `CI required` and `Security required` green.
3. `python3 scripts/check_release_notes.py "$0"` for curated notes.
4. `python3 scripts/quality_promotion.py validate` for the exact-tag `quality-promotion.json` if one
   exists; list which platform lanes and evidence ages block promotion.
5. `gh run list --limit 10` for the release workflows and `gh release view "$0"` for draft state.
6. Report a table: check, state, what would unblock it. End with the sentence that publication requires
   an explicit maintainer decision and `.github/workflows/promote-release.yml`.
