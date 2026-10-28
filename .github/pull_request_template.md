## Summary

Describe the user-visible or maintainer-visible outcome.

`main` is the only published branch. A pull request runs only `ci.yml`'s Linux jobs (contracts,
Python, website) with a read-only token; the macOS lanes and the `CI required` verdict a release
relies on come from the maintainer's push to `main`.

## Verification

- [ ] Relevant deterministic repository checks pass.
- [ ] Generated project or indexes were regenerated and checked when their inputs changed.
- [ ] Model-, device-, and UI-dependent QA is listed separately, not required for an ordinary commit/push or candidate build. Public promotion still requires its applicable source-bound acceptance gates.

## Documentation impact

- [ ] Active docs and role guidance still match source, `project.yml`, scripts, and machine-readable contracts.
- [ ] Owned-runtime changes (`Packages/VocelloQwen3Core`) update its `RUNTIME_MANIFEST.json`, `SEMANTIC_DELTAS.json`, tests, and current guidance as applicable.
- [ ] Telemetry or benchmark schema changes received backend, affected-platform, and release/QA review.
- [ ] Public product claims were checked against `config/public-product-facts.json`, the model contract, hardware profiles, and tracked benchmark evidence.
- [ ] Historical snapshots remain clearly labelled and were not rewritten as active runbooks.
