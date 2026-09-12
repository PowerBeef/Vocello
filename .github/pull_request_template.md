## Summary

Describe the user-visible or maintainer-visible outcome.

Development is main-only: `ci.yml` has no pull-request trigger, so the `CI required` verdict is produced by a maintainer's push to `main`.

## Verification

- [ ] Relevant deterministic repository checks pass.
- [ ] Generated project or indexes were regenerated and checked when their inputs changed.
- [ ] Model-, device-, and UI-dependent QA is listed separately, not required for an ordinary commit/push or candidate build. Public promotion still requires its applicable source-bound acceptance gates.

## Documentation impact

- [ ] Active docs and role guidance still match source, `project.yml`, scripts, and machine-readable contracts.
- [ ] Vendor-runtime changes update `VENDOR_MANIFEST.json`, `PATCHES.json`, tests, and current guidance as applicable.
- [ ] Telemetry or benchmark schema changes received backend, affected-platform, and release/QA review.
- [ ] Public product claims were checked against `config/public-product-facts.json`, the model contract, hardware profiles, and tracked benchmark evidence.
- [ ] Historical snapshots remain clearly labelled and were not rewritten as active runbooks.
