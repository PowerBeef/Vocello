---
name: release-evidence
description: Read-only report of release readiness for a tag — source authority (annotated tag on origin/main, exact-SHA `CI required`), quality-promotion evidence and what still blocks a public promotion. Never publishes, signs or dispatches workflows. User-invoked only.
argument-hint: "<tag, e.g. v3.0.0>"
disable-model-invocation: true
allowed-tools: Bash(python3 scripts/release_source_authority.py *) Bash(python3 scripts/quality_promotion.py validate*) Bash(python3 scripts/check_release_notes.py *) Bash(gh api *) Bash(gh run list*) Bash(gh release view*) Bash(gh release download*) Bash(git tag*) Bash(git log*) Read Grep
---

# Release evidence (read-only)

Authority: `docs/reference/quality-promotion.md`, `docs/reference/macos-release-qa.md`,
`.claude/rules/release.md`. Candidate production and public promotion are separate; neither is
authorized by this skill. Do not run `scripts/release.sh`, `gh release create|edit`, or any workflow
dispatch.

## Steps

1. Require a tag as the argument. `git tag -l "$0" -n1` and `git log -1 "$0"` to confirm it exists and
   which commit it targets.
2. The script has no network route: fetch the tag ref (`gh api repos/<owner>/<repo>/git/ref/tags/<tag>`),
   the annotated tag object it points at (`gh api repos/<owner>/<repo>/git/tags/<sha>`) and the latest
   check runs of the tagged commit (`gh api --paginate --slurp
   repos/<owner>/<repo>/commits/<sha>/check-runs?filter=latest&per_page=100`) into
   `build/scratch/transient/release-evidence/<tag>/` (the governed invocation-local scratch), then run `python3 scripts/release_source_authority.py --tag <tag> --commit <sha>
   --tag-ref <ref.json> --tag-object <tag.json> --check-runs <checks.json>`. It passes only for an
   annotated tag whose signature GitHub verified and whose latest `CI required` run succeeded; check
   containment yourself with `git tag -l <tag> --merged origin/main` (the release workflow uses
   `git merge-base --is-ancestor`). Security runs inside `release.yml`, not as a pre-existing check.
3. `python3 scripts/check_release_notes.py "$0"` for curated notes.
4. If the draft carries an exact-tag `quality-promotion.json`, download it and `release-evidence.json`
   with `gh release download <tag> --pattern ... --dir build/scratch/transient/release-evidence/<tag>/`, then run
   `python3 scripts/quality_promotion.py validate --platform macos|ios --tag <tag> --release-evidence
   <release-evidence.json> --manifest <quality-promotion.json>`; list which platform lanes and
   evidence ages block promotion.
5. `gh run list --limit 10` for the release workflows and `gh release view "$0"` for draft state.
6. Report a table: check, state, what would unblock it. End with the sentence that publication requires
   an explicit maintainer decision and `.github/workflows/promote-release.yml`.
