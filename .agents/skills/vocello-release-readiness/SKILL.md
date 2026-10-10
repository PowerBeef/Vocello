---
name: vocello-release-readiness
description: Read-only assessment of a tag or candidate against exact-source CI, release source authority and quality-promotion evidence; never publishes or dispatches.
---

# Release readiness (read-only)

Read docs/reference/quality-promotion.md, docs/reference/macos-release-qa.md, docs/reference/ios-appstore-submission.md and
tooling-and-evidence.md. Require/infer the exact tag or candidate; inspect existing Git metadata,
GitHub checks and release assets through read-only tools. Candidate production and public promotion
are separate decisions; this skill authorizes neither. No release.sh, workflow dispatch, signing,
upload, metadata change, push, deployment or App Store write.
Validate existing source-authority inputs with `python3 scripts/release_source_authority.py` and
quality evidence with `python3 scripts/quality_promotion.py validate`; consult --help for required
arguments. Curated notes use `python3 scripts/check_release_notes.py <tag>`. Read-only GitHub GETs
may save fetched JSON to governed scratch, never into frozen evidence. Check annotated verified
tag, origin/main containment, exact tagged-SHA push CI, platform/lane completeness, evidence age
and compatible source/build/device identities. Missing evidence is a blocker, never an inferred PASS.
Report each check and what would unblock it. Publication requires a specific maintainer request.
