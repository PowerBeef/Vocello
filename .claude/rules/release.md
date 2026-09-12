---
paths:
  - "scripts/**"
  - ".github/**"
  - "config/**"
  - "benchmarks/**"
  - "docs/**"
  - ".claude/**"
---
# Release / QA rule — scripts, CI, packaging, benchmarks, evidence

References, read only what the change needs: `docs/reference/development-workflow.md` (local loop and
CI), `docs/reference/testing-runbook.md` (which lane), `docs/reference/macos-release-qa.md` and
`docs/reference/ios-appstore-submission.md` (release steps), `docs/reference/telemetry-and-benchmarking.md`
(schemas), `docs/reference/ios-device-testing.md` (device procedure).

## How verification is organised

- `scripts/dev.sh check` is the local loop; nothing local blocks a commit except the commit lint. CI on
  `main` is the gate. `scripts/dev.sh ci` reproduces it serially.
- `./scripts/check_project_inputs.sh` is the deterministic contract gate: product contracts,
  `scripts/repo_invariants.sh` (exact greps for product invariants), `scripts/privacy_scan.py`, the
  roadmap validator and the Python suite (`pytest -n auto`; `research` and `darwin_only` lanes by marker
  in `scripts/tests/conftest.py`). Add a check only when it protects a product invariant; never a check
  that asserts the wording of another script or workflow.
- `ci.yml`: `scripts/ci/classify_changes.py` routes pushes into lanes, diffing each lane against the last
  run in which that lane's job passed (a cancelled superseded run cannot leave a lane unrun); `macos-tests` and `ios-compile`
  restore the persistent DerivedData caches from `config/build-output-policy.json`
  (`scripts/ci/restore_mtimes.py` first); `contracts` and `python` run on ubuntu; `CI required` is the
  only branch-protection context and passes when jobs are path-skipped. The shared toolchain step is
  `.github/actions/native-toolchain`. `nightly.yml` runs TSan, the complete Python suite and cold
  compiles; `security.yml` runs weekly, on dispatch and inside `release.yml` on the tagged commit.
- Ordinary CI never executes XCUITest, a model or a device; it compiles `VocelloiOS` and the
  policy-test bundle for `generic/platform=iOS` and runs the macOS deterministic bundles with the direct
  `xcrun xctest` runner.
- Generated files (`docs/ROADMAP.md`, the production model catalog, the owned-package inventories,
  `docs/charts/*.svg`, `benchmarks/HISTORY.md`) are regenerated with `scripts/dev.sh regen` in the same
  change as their inputs; the generated-file guard refuses hand edits.

## Invariants (do not regress)

- **Release-only.** One shippable `Release` configuration; the app and development CLI compile `-Onone`,
  `release.sh` and `build.sh cli-optimized` compile optimized. No Debug configuration or `DEBUG` symbol.
- **Generated project.** `project.yml` is the source; `scripts/generate_cli_scheme.py` and
  `scripts/generate_ios_logic_scheme.py` render the two schemes XcodeGen cannot.
- **Build outputs have one owner.** `config/build-output-policy.json` registers the macOS, macOS TSan and
  iOS device caches, scratch trees, artifacts and `build/dist`. No ad hoc DerivedData; prefer one
  selective `clean_build_caches.sh --cache` over `--aggressive`; routine cleanup never removes
  distribution outputs.
- **Action and toolchain identities are pinned.** Every action uses the full SHA in
  `config/toolchain.json`; xcodegen, ripgrep, xcbeautify and shellcheck install from SHA-pinned release
  artifacts; numpy, pytest and pytest-xdist pip-pin to the manifest. Dependabot proposes, the manifest
  and comment change together.
- **Exact-source releases.** `release_source_authority.py` proves a GitHub-verified annotated `v*` tag on
  the checked-out commit, containment in `origin/main` and a successful latest `CI required` run; the
  release workflow runs Security on that commit first. Lightweight tags, cross-SHA checks and incomplete
  check-run pagination fail closed. Every release step matches its `config/orchestration-contract.json`
  template; schema-v2 release evidence accepts only a clean full-tree identity and same-invocation step
  manifests. Never restore a `release.published` trigger; `--generate-notes` is banned and
  `scripts/check_release_notes.py` gates `docs/releases/<tag>.md`.
- **Separate public promotion.** A public macOS release or external TestFlight/App Review needs
  exact-tag `quality-promotion.json` validated by `scripts/quality_promotion.py`; candidate production
  never waits for device availability.
- **Evidence retention.** Only qualified privacy-safe PASS records enter `benchmarks/runs/` (≤ 256 KB
  each, strict allowlist), then `benchmarks/HISTORY.md` is regenerated. Raw JSONL, WAV, screenshots,
  xcresult and traces stay untracked; publication never stages, commits or pushes. Successful profiles
  publish their digest and summary before the raw trace is deleted (`--keep-trace` is explicit).
- **Records measure what they claim.** `rtf` is wall ÷ audio (lower is faster) and every record since
  2026-09-12 declares `run.rtfDefinition`; legacy records are never rewritten and never share a comparison
  key with new ones. `toolchain.optimization` comes from the build receipt (`last-build.json`, executable
  digest bound) via `scripts/lib/build_provenance.py`; the gate bench compares medians of three warm takes
  and reports a loaded or throttled host as inconclusive (exit 3), never as pass or fail.
- **Memory-qualified publication.** Telemetry v8, manifest v2, exact sidecar digests, ≥95% coverage, zero
  capture failures, no critical pressure, warning, `hardTrim` or `fullUnload`; 95–<100% coverage is
  `passedWithWarnings`. Marking evidence keeps the take peak (`config/marking-peak-equality.json`).
- **Audio QA is autonomous.** Fixed seeds, byte-bound PCM QC, locale-locked full-WAV ASR and
  prosody/delivery evidence are required; listening is optional and never clears a machine failure.
  Prompt comparisons use a run-time frozen holdout judged by `scripts/delivery_promotion_decision.py`.
- **Consent-bound lanes.** `scripts/ui_test.sh`, `scripts/ios_device.sh`, `scripts/macos_test.sh
  memory|lang-bench` and `release.yml` run only on explicit request. Runner PASS requires diagnostics,
  crash deltas and restoration; no retries; a failed run keeps its artifacts; changed source needs new
  run IDs. XCUITest is never a packaging, notarization or upload prerequisite.
- **TSan.** `config/tsan-policy.json` names the subset and the tests that skip under the sanitizer;
  the nightly lane runs it; never weaken deterministic or MLX runtime coverage to make it pass.
- **Claude Code state stays external.** Sessions, memory and `settings.local.json` never enter Git,
  CI or evidence; the repository tracks only `.claude/settings.json`, rules, skills and subagents.

## Common mistakes

- Adding a validator that greps another script's text, or a Python test of a Python gate.
- Committing raw telemetry, editing `benchmarks/HISTORY.md` or `docs/ROADMAP.md` by hand.
- Running iOS UI work in the Simulator or making ordinary CI wait for a phone, a model or XCUITest.
- Clearing caches to evade SwiftPM lock contention instead of serializing native commands.
