---
status: active
owner: release-qa
summary: Domain rule for scripts, CI, packaging, signing, benchmarks, and release gates — build-output ownership, registry rules, release-evidence invariants, and the deterministic-only publishing posture.
sourceOfTruth:
  - scripts/check_project_inputs.sh
  - .github/workflows/ci.yml
  - .github/workflows/release.yml
  - .github/workflows/promote-release.yml
  - config/build-output-policy.json
  - config/support-contact.json
  - config/third-party-attribution-policy.json
---
# Release / QA domain rule

> Domain rule for build scripts, CI workflow, packaging, signing, notarization,
> benchmarks, UI smoke, crash/profile analysis, and release QA gates.

## Boundaries

**Owns:**
- `scripts/*.sh` and `scripts/lib/`
- `.github/workflows/ci.yml`, `.github/workflows/release.yml`,
  `.github/workflows/promote-release.yml`, and
  `.github/workflows/security.yml`
- `config/build-output-policy.json`, `config/documentation-contract.json`,
  `config/codex-session-storage-policy.json`,
  `config/public-product-facts.json`, `config/toolchain.json`,
  `config/orchestration-contract.json`, `config/evidence-impact.json`,
  `config/project-health-contract.json`, `config/release-evidence-contract.json`,
  `config/quality-promotion-contract.json`,
  `config/benchmark-baseline-migrations.json`, and `config/marking-peak-equality.json`
- App Store support, attribution, storage, account-readiness, build-collision, and model-host governance:
  `config/support-contact.json`, `config/third-party-attribution-policy.json`,
  `config/ios-storage-protection-policy.json`, `config/app-store-connect-readiness-policy.json`,
  `config/model-host-availability-policy.json`, `config/ios-release-analyzer-warning-policy.json`,
  `scripts/support_contact_contract.py`,
  `scripts/attribution_manifest.py`, `scripts/ios_storage_protection_policy.py`,
  `scripts/app_store_build_preflight.py`, `scripts/app_store_connect_readiness.py`, and
  `scripts/model_host_availability.py`; `scripts/ios_release_analyzer_warnings.py` fails closed on
  any unreviewed iOS Release static-analysis warning
- `benchmarks/` schema-v1 compatibility, schema-v2 memory-qualified, and schema-v3
  quality-identity records, generated history, and preserved reference baselines
- `docs/releases/`
- Release verification, evidence-impact, quality-promotion, required-step, project-health, supply-chain, and packaging
  scripts (`scripts/verify_*.sh`, `scripts/release_evidence.py`, `scripts/required_step_ledger.py`,
  `scripts/quality_promotion.py`, `scripts/project_health.py`, `scripts/supply_chain_contract.py`,
  `scripts/create_dmg.sh`, etc.)
- Codex task/session storage governance: `scripts/codex_session_storage.py`, its synthetic test,
  and `docs/reference/codex-session-storage.md`. Live user state remains operator-owned and outside
  repository evidence.
- Release-candidate evidence, SBOM/checksum generation, immutable Actions pins, and repository
  security/governance files
- Production-model-catalog reproducibility and activation gating. Backend owns artifact meaning and
  trusted receipts; Release/QA ensures staged state cannot become active until completeness,
  deterministic validation, and explicit delivery evidence pass.

**Does NOT own:**
- App source code (`.agents/rules/backend-mlx.md`, `.agents/rules/ios.md`, `.agents/rules/macos.md`)
- Marketing site (`website/AGENTS.md`)

**Consults:**
- `docs/reference/{macos-release-qa,telemetry-and-benchmarking,cli,macos-testing,ios-device-testing}.md`
- `docs/ARCHITECTURE.md` §12 (telemetry)
- Root `AGENTS.md` (Workflows, Commands) + [`docs/project-map.html`](../../docs/project-map.html)

## Required pre-read

Before changing scripts or CI, read:
1. The script you are modifying (header comments encode intent and env vars).
2. `.github/workflows/release.yml` and `.github/workflows/promote-release.yml` if touching release CI.
3. `docs/reference/macos-release-qa.md` for the full macOS release QA checklist.
4. `docs/reference/benchmarking-procedure.md` for the operator runbook (when to bench, platform lanes, preflight).
5. `docs/reference/telemetry-and-benchmarking.md` for benchmark/telemetry schema and knobs.

## Tools and skills

- **Shell scripts are the source of truth**; run them directly and preserve their artifacts.
- Use a GitHub integration when it is currently callable for PR, release, and Actions context;
  otherwise use `gh`. User-scoped installation state is not a repository prerequisite.
- For App Store Connect, use the guarded user-scoped `app-store-connect-cli` skill when available:
  discover current syntax, request JSON, paginate fully, resolve exact IDs, and default to read-only.
  Uploads, edits, TestFlight changes, submission, and cancellation each require explicit user
  authorization immediately before mutation. Raw account JSON stays temporary and untracked;
  repository archive and release scripts remain authoritative.
  The release workflow must run `scripts/app_store_build_preflight.py` before iOS archive creation;
  an account timeout or absent response is a failed preflight, never permission to reuse a build
  number. Read-only readiness inventories retain only digests/counts/safe state tokens, and live
  model-host evidence uses one-byte catalog-bound range probes rather than downloading weights.
- Optional skills may assist with test triage, performance, signing, packaging, or
  telemetry after their instructions are read. Start from script output and generated artifacts.
  Triage failing UI lanes with `axiom-testing` and focused repository commands, and symbolicate
  crashes with `xcsym` through `axiom-tools` before manual log digging; computer use stays assistive
  (exploratory QA/diagnosis per `docs/reference/interactive-ui-qa.md`), never a driver or gate.
- XCUITest is the sole autonomous app UI driver. It runs against the native macOS app or a paired
  physical iPhone and provides smoke and benchmark lanes; iOS adds pulled on-device
  telemetry proof.
- Development CI is deterministic-only. Commits, pushes, pull requests, and ordinary merges must
  not wait for models, a paired phone, or XCUITest results.
- Release packaging is deterministic. macOS packaging is subordinate to
  `scripts/macos_test.sh release-readiness`, which requires project-input, build,
  deterministic-test, and crash-delta checks. Model-dependent telemetry remains optional explicit
  QA. iOS archive/TestFlight first binds `scripts/macos_test.sh gate` and the generic physical-
  device SDK compile into the same release ledger, then uses its signing, archive, entitlement,
  catalog, and artifact verification. XCUITest is optional
  explicit frontend QA and never a signing, notarization, packaging, or upload prerequisite.
  Exception to "optional" in cadence only: the macOS smoke lane is a standing per-candidate step —
  run it and record the verdict (or a deliberate skip) in the release notes; it still never blocks
  packaging (`docs/reference/macos-release-qa.md` step 2b).
- Public promotion is a separate operation. Candidate builds, signing, notarization, draft upload,
  and internal TestFlight upload remain deterministic-only. A public macOS release or external
  iOS/App Review submission requires `quality-promotion.json` bound to the exact tag, release
  evidence bytes, path-classified lanes, and privacy-safe canonical hardware profiles. The
  promotion manifest is an external draft asset because recording exact-tag device evidence after
  the tag must not create a self-referential source commit.
- **Generated-output contract:** `config/build-output-policy.json` owns the persistent caches,
  scratch DerivedData, untracked evidence, current symbols, and distribution outputs. Do not add an
  ad hoc build root or allow an Xcode/SwiftPM invocation to choose its own cache. XcodeBuildMCP
  scratch trees (`build/scratch/derived-data/xcodebuildmcp/{macos,ios-device}`) stay scratch-class
  under that policy; they never become a third persistent cache or a release gate.
- **Codex task/session storage:** the separate `config/codex-session-storage-policy.json` governs
  an optional operator-local workflow. CI validates the contract and temporary fixtures only; it
  never reads or changes a real Codex home. Use the plain/compressed metadata-only inventory,
  temporary checksummed plan, exact approval, evolving non-target preservation baseline, supported
  CLI deletion, and verification sequence in
  `docs/reference/codex-session-storage.md`. This state is not repository build output.
- **Evidence artifacts:** `build/artifacts/ui-tests/` owns `.xcresult` bundles and exported
  screenshots; `build/artifacts/diagnostics/` owns pulled/headless generation telemetry and crashes;
  platform gate/profile outputs remain below `build/artifacts/{macos,ios}/`; current dSYMs live
  under `build/artifacts/symbols/{macos,ios}/`. Multi-run UI campaigns use `--retain-result` before
  execution; its untracked pin outranks ordinary latest-pass pruning, including for legacy-shaped
  metadata. Verify pins with `clean_build_caches.sh --prune-ui-results --dry-run` and retire them
  only after the complete evidence set is closed.
- **Benchmark registry:** successful memory-qualified benchmark lanes publish a compact record under
  `benchmarks/runs/<kind>/` and regenerate `benchmarks/HISTORY.md`. The telemetry-overhead
  observer-effect diagnostic stays local because instrumenting its `off` lane would invalidate the
  comparison. Raw telemetry, WAVs, screenshots, `.xcresult`, and traces stay untracked. Publication
  never stages, commits, or pushes. Successful profiles are summary-only by default: the runner
  publishes the trace digest/settings/extracted evidence before deleting the raw trace. Use
  `--keep-trace` only when the raw Instruments document must be reopened.
- **Documentation and public facts:** this role owns lifecycle/index validation and public release,
  platform, support, and canonical-hardware references. Model implementation facts remain backend-owned.
- **Schema review:** telemetry or benchmark schema-version changes require backend, the affected
  platform owner, and release/QA review before publication contracts change.
- **Root Swift dependency watch:** `scripts/swift_dependency_updates.py` and
  `config/swift-dependency-update-policy.json` keep project, owned-runtime, lock, compatibility,
  and evidence surfaces coordinated. The scheduled workflow is read-only; release availability or
  an advisory proposes review but never changes exact pins or establishes compatibility.
- **macOS entitlement diff:** `scripts/entitlement_contract.py` validates exact app/XPC/framework
  allowlists on every deterministic change. Signed bundle verification must compare the emitted
  entitlements to the same policy; do not sign the engine XPC with the broader app plist.
- **TSan characterization:** `config/tsan-policy.json` owns the bounded non-blocking deadline,
  exact test subset, recorded clean runs, and maintainer-reviewed transition to blocking. Do not
  weaken ordinary deterministic or MLX runtime coverage to make the sanitizer subset pass.

## Build / test commands

```sh
# Preferred local loop: narrow repeatable checks, then one complete checkpoint.
scripts/dev.sh plan
scripts/dev.sh focused
scripts/dev.sh checkpoint

# Ordinary development / CI (no model, device, or UI prerequisite)
./scripts/check_project_inputs.sh
QVOICE_GATES=quick ./scripts/check_project_inputs.sh   # local fast loop: self-tests skipped only while scripts/ + config/ are untouched
scripts/macos_test.sh test
./scripts/build.sh build
./scripts/build_foundation_targets.sh ios

# Explicit scheduled-lane characterization; not an ordinary commit/release prerequisite.
scripts/macos_test.sh tsan

# Deterministic/runtime macOS gate (models are needed only for the optional bounded bench)
scripts/macos_test.sh models ensure   # explicit repair/bootstrap only; normal readiness is visible in Settings
scripts/macos_test.sh gate
QWENVOICE_GATE_BENCH=1 scripts/macos_test.sh gate   # optional: bounded custom/speed/medium bench + audioQC

# Explicit XCUITest evidence; never a packaging prerequisite.
scripts/ui_test.sh macos smoke
scripts/ui_test.sh macos benchmark
scripts/macos_test.sh telemetry-overhead
python3 scripts/check_macos_xpc_bench.py ~/Library/Application\ Support/QwenVoice-Debug/diagnostics \
  --run-id macos-xcui-benchmark-YYYYMMDD-HHMMSS

# Language-path verification (optional pre-release; Phases 1–3)
scripts/macos_test.sh core-test
python3 scripts/test_check_language_hints.py
python3 scripts/test_check_language_output.py
scripts/macos_test.sh lang-bench --subset quick              # Phase 2 hint gate (CLI)
scripts/ios_device.sh lang-bench --subset quick --label release-QA   # Phases 2–3 on device
# Full 19-cell iOS matrix: scripts/ios_device.sh lang-bench --subset full --label lang-full-v1
# Fixed 15-take autonomous diagnosis, never history: scripts/ios_device.sh lang-bench --diagnostic-cohort
# Phase 3 output (DE/ES/ZH/JA): language-bench.md § Phase 3 prerequisites — Speech Wi‑Fi assets
# Current acceptance state and resume commands: docs/development-progress.md

scripts/ui_test.sh ios smoke
scripts/ui_test.sh ios benchmark
scripts/ios_device.sh gate

# Model fixture helpers
scripts/macos_test.sh models check|ensure|install
# XCUITest reviews iOS model readiness visibly in Settings.

# Release packaging
./scripts/build.sh release
python3 scripts/supply_chain_contract.py
python3 scripts/release_source_authority.py --help
python3 scripts/release_evidence.py validate --output-dir build/dist/macos

# Benchmark driver (PASS publishes a registry record automatically when run in this checkout)
QWENVOICE_DEBUG=1 ./build/vocello bench --modes clone --variants speed \
  --lengths short,medium,long --warm 3 --voice <prepared-voice> \
  --label "release-QA"

# Derived catalogs (inventories / indexes CI fail-closes on)
python3 scripts/refresh_derived_artifacts.py refresh
python3 scripts/refresh_derived_artifacts.py validate

# Registry validation / reproducibility
python3 scripts/benchmark_history.py validate --all
python3 scripts/benchmark_history.py rebuild-index --check
python3 scripts/model_catalog_contract.py rebuild --check
python3 scripts/model_catalog_contract.py validate

# Optional regression compare (see macos-release-qa.md step 3)
python3 scripts/summarize_generation_telemetry.py \
  ~/Library/Application\ Support/QwenVoice-Debug/diagnostics \
  --run-id <run-id> --evidence-manifest <run-artifact-dir>/benchmark-evidence.json \
  --compare-baseline benchmarks/baselines/mac-gate-bench.json \
  --label "release-QA"

# Crash/profile (PASS-only; failed traces or generations never publish benchmark history)
scripts/macos_test.sh crashes
scripts/macos_test.sh profile [--kind cpu|memory] [--keep-trace] [spec]
scripts/macos_test.sh memory [--label ID]
scripts/ios_device.sh crashes
scripts/ios_device.sh profile [--kind cpu|memory] [--keep-trace] [spec]
scripts/ios_device.sh memory --voice-id SAVED_VOICE_ID [--label ID]
# Reads already-pulled delayed MetricKit aggregates; it does not contact the phone or publish history.
scripts/ios_device.sh memory-field-report [pulled-diagnostics]
python3 scripts/build_output_policy.py status [--json]
python3 scripts/build_output_policy.py validate
python3 scripts/codex_session_storage.py validate
python3 scripts/codex_session_storage.py status   # optional local aggregate; never CI/release input
scripts/clean_build_caches.sh --routine --dry-run
scripts/clean_build_caches.sh --routine
scripts/clean_build_caches.sh --prune-ui-results --dry-run
scripts/clean_build_caches.sh --cache macos --dry-run
scripts/clean_build_caches.sh --compact-profile-failure <run-id> --dry-run
```

The router optimizes `scripts/evidence_impact.py`; it is not another evidence authority. Focused
work may use fast regeneration, selected XCTest classes, and the governed incremental iOS cache.
Checkpoint and CI retain full deterministic coverage. See
[`development-workflow.md`](../../docs/reference/development-workflow.md). Never add inferred
UI/model, benchmark, signing, or release work.

## Invariants (do not regress)

- **Single shippable config: `Release` only.** There is no `Debug` config or generic `DEBUG` symbol.
  The ordinary app/development CLI route compiles `-Onone`; `release.sh` and the
  `build.sh cli-optimized` benchmark route compile optimized. macOS engine-performance publication
  requires the optimized CLI's hash-bound provenance sidecar. Baseline cell renames require a
  reviewed one-to-one entry in `config/benchmark-baseline-migrations.json`; missing/added cells or
  metrics otherwise fail closed.
- **XcodeGen project generation.** `project.yml` is the source of truth; never edit
  `QwenVoice.xcodeproj/project.pbxproj` directly. There are two narrow post-XcodeGen scheme
  renderers: `scripts/generate_cli_scheme.py` for the tool product and
  `scripts/generate_ios_logic_scheme.py` for the app-host-free iOS policy bundle. Both bind
  checked-in templates to generated target IDs because XcodeGen cannot render those schemes
  (verified unchanged through 2.46.0).
- **Developer ID signing + notarization.** macOS release uses Developer ID Application cert,
  hardened runtime, and `notarytool` stapling. CI uses App Store Connect API key auth.
- **Gate quick mode is local-only.** `QVOICE_GATES=quick` may skip the script self-test suite
  only while `scripts/` and `config/` have no pending changes; CI and release lanes never set it,
  so every push and package still runs the full suite. Do not widen the skip's scope.
- **CI topology.** `ci.yml`: a cheap `changes` router classifies pushed paths; the two heavy
  macos-26 jobs run only for native-surface changes (Sources/Tests/Packages/config/scripts/
  benchmarks/project files/.github), the website job for `website/` changes, and the `CI required`
  aggregator (the sole branch-protection context) passes when jobs are path-skipped. The
  lightweight `docs-contracts` job runs unconditionally on every push/PR (documentation,
  doc-metadata, surface-coverage, and roadmap validators), so a docs-only push can never green
  `CI required` without the contract suite — the T1 commit-gate hook
  (`scripts/hooks/precommit_gate.sh`, owned here) provides the same coverage locally but is
  Codex-session tooling, not a universal git hook. Both heavy macOS jobs cache SwiftPM checkouts.
- **Security timing is path-relevant and release-bound.** `security.yml` routes native and website
  changes on pushes and pull requests, runs CodeQL for either relevant surface and npm advisory
  audit for website changes, and always publishes the stable `Security required` aggregate. The
  repository deliberately retains direct-to-`main` administrator development, so live
  `enforce_admins=false` and branch-level `required_signatures=false` are an explicit residual—not
  release authority. Candidate and promotion workflows compensate by requiring a GitHub-verified
  annotated tag, containment in `origin/main`, and successful latest `CI required` plus
  `Security required` runs on the exact tagged commit.
- **Ordinary CI is deterministic-only.** GitHub CI executes the 19 platform-neutral iOS policy
  assertions inside macOS `VocelloCoreTests`, compiles the `VocelloiOS` app and duplicate standalone
  `VocelloiOSLogicTests` bundle with `generic/platform=iOS`, and never executes XCUITest. Xcode 26
  cannot execute the app-host-free tool-hosted policy bundle on a physical-device destination, so
  that duplicate target remains compile-only; device runtime proof uses the existing diagnostics
  and XCUITest lanes. Missing matching iOS Platform Support/runtime
  availability is classified as a host-toolchain readiness failure before package resolution, not
  as a source, phone, model, or UI failure. Repository automation never downloads that component.
- **Release notes are curated and fail-closed.** The GitHub Release body comes verbatim
  from `docs/releases/<tag>.md`; `--generate-notes` is banned in release lanes.
  `scripts/check_release_notes.py` gates the tag before build work: required
  dual-audience sections (What's new/Headline, Requirements, Install, TestFlight
  What-to-Test), no placeholder tokens, absolute links only. TestFlight Test Details
  are pasted from the same file's TestFlight section when distributing the build
  (ASC-API automation is a recorded enhancement). Details:
  `docs/reference/macos-release-qa.md` "Release notes are a release artifact".
- **Performance surfaces refresh with each release.** The README chart generator's
  `RTF_RECORD` and the website Engineering numbers move to the newest canonical macOS UI
  record in the same change set as the version bump (or the release notes record the
  deliberate skip). Technical sections (README "Under the hood", website Engineering)
  are maintained whole-package surfaces: a single release's optimization gets at most
  one line, never a headline or standalone chart, and the retired gate chart's record
  pair stays pinned history in prose. Details: `docs/reference/macos-release-qa.md`
  "Performance surfaces ship current numbers" and "Technical sections are maintained
  surfaces".
- **Committed benchmark records ≤256 KB.** Records use a strict privacy allowlist; raw JSONL,
  WAVs, screenshots, result bundles, and traces are gitignored. `HISTORY.md` is generated, never
  manually appended.
- **Profile storage is bounded.** A successful profile is retained as compact history plus local
  summary metadata; its raw trace is deleted only after publication succeeds unless `--keep-trace`
  was explicit. A failed lane retains at most the newest raw trace per platform/profile kind and
  requires an exact run ID before manual compaction. Inventory distinguishes automatic, blocked,
  and explicit reclamation; never reinterpret all of `build/artifacts/` as disposable.
- **Build outputs have one owner.** macOS and physical-device iOS keep exactly two persistent Xcode
  caches, package resolution uses the shared locked checkout, and release/MCP/compile-safety work is
  scratch. Release files live only under `build/dist/` and routine cleanup never removes them.
  Heavy lanes use the manifest-owned free-space preflight before work starts. Prefer one selective
  `--cache` target over `--aggressive`; successful ordinary builds remain non-destructive.
- **Codex user state remains external.** The repository tracks only the policy, helper, runbook,
  and synthetic tests. A live manifest/journal stays mode 0600 in a system temporary directory and
  never enters Git, CI, release evidence, or benchmark history. Unknown and unrelated tasks are
  protected; no subagent may select or approve deletion; no workflow edits Codex SQLite or removes
  rollout JSONL directly.
- **Memory-qualified publication is strict.** New generation/profile records require telemetry v8
  and evidence manifest v2, exact sidecar digests, ≥95% sampler coverage, zero capture failures,
  and no critical pressure, memory warning/exit, `hardTrim`, or `fullUnload`. A 95–<100% coverage
  result or guarded/soft-trim state is retained as `passedWithWarnings`; it is never silently clean.
- **Publication marking must not move the take peak.** The macOS memory-qualification lane
  fail-closes on `config/marking-peak-equality.json` (checker:
  `scripts/check_marking_peak_equality.py`): within every take, no footprint sample at or after
  the Article 50 marking interval may exceed that take's pre-marking peak beyond tolerance, and
  the marking boundaries must be present (they are captured only when marking executes, so a
  `QWENVOICE_MARKING=off` run cannot publish as marking evidence). Comparison is within-take by
  design — cross-run lifecycle-peak comparison was refuted by its own knob-off control
  (2026-08-07), which drifted hundreds of MB with host memory pressure while the marking pass
  itself measures +9 to +18 MB.
- **MetricKit field evidence stays local and delayed.** `memory-field-report` summarizes only
  already-pulled privacy-reduced aggregates. It never wakes a device, and its daily/non-run-
  correlated values cannot qualify or retroactively fail a benchmark take.
- **Audio QA is autonomous.** Require the applicable fixed-seed exact-WAV QC, three-pass
  locale-locked ASR, and prosody/delivery evidence. Listening is optional annotation and cannot
  clear a machine warning or failure.
- **Deep checkout on CI.** `fetch-depth: 0` is required so `git rev-parse HEAD` in
  `scripts/release.sh` resolves for `release-metadata.txt`.
- **Release publication is the final transaction.** A GitHub-verified annotated `v*` tag or
  explicit existing tag starts the workflow. Before any platform job, `release_source_authority.py`
  proves that the tag targets the exact checked-out commit, that the commit belongs to
  `origin/main`, and that its latest `CI required` and `Security required` check runs completed
  successfully. Lightweight/unsigned tags, cross-SHA checks, missing rows, and incomplete check-run
  pagination fail closed. Source/tag/version identity, signing, notarization, package verification,
  SPDX/CycloneDX generation, checksums, and provenance all pass before a draft Release exists.
  Schema-v2 release evidence accepts only a clean full-tree source identity and fresh same-invocation
  required-step manifests produced by the managed release subprocess. Every release step must match
  its `config/orchestration-contract.json` command template, and declared outputs are hashed at step
  completion and rechecked during evidence creation; handwritten, substituted-command, replaced-
  output, or stale PASS artifacts are never authoritative. iOS additionally requires
  `verify_ios_release_artifacts.py` to prove archive/IPA identity, entitlements, root privacy
  manifest, locally trusted and profile-authorized signing, and Mach-O UUID plus
  signature-normalized code continuity
  before evidence or attestation. Archive signing may be development or distribution; the exported
  IPA alone must satisfy the App Store distribution profile and `get-task-allow` policy.
  Reused drafts are emptied before upload, then their exact remote asset-name set and digests are
  verified before publication. Never restore a
  `release.published` trigger.
- **Action and toolchain identities are immutable inputs.** Every external Action uses the full SHA
  recorded in `config/toolchain.json`; native, release-publication, and website runners validate
  exact tool versions. The native deterministic-tool group includes NumPy because the bounded
  prosody analyzer and its mutation fixtures are part of project-input validation; this remains a
  development/QA dependency and is never shipped in Vocello. Keep publication-only tools out of
  compile/test jobs.
  Dependabot may propose updates, but the manifest and adjacent version comment change together.
  Runner-image drift is not trusted for the drifting tools: xcodegen and ripgrep install from the
  SHA-pinned release artifacts recorded in `config/toolchain.json` `artifactPins` via
  `scripts/install_pinned_tools.sh` (in both native CI jobs and Swift CodeQL); bump the version,
  URL, and digest together with the local `.tool-versions` pin.
- **Catalog activation is fail closed.** All six Speed/Quality identities are exact and the generated
  production catalog is complete. macOS/CLI use the bundled `downloadFiles` route; never restore
  live repository enumeration, infer a digest, or accept a partial catalog. Deterministic
  `model_catalog_contract.py validate --require-complete` and explicit post-change delivery evidence
  remain distinct proofs.
- **Burn-in-safe iOS testing.** Headless generation, profiling, logs, and device diagnostics go
  through `scripts/ios_device.sh`; physical-device UI acceptance goes through `scripts/ui_test.sh`.
- **macOS real-generation acceptance needs model fixtures.** XCUITest verifies readiness in Settings;
  run `scripts/macos_test.sh models ensure` only to repair/bootstrap the debug link and clone voice. See [`scripts/lib/test_models.sh`](../../scripts/lib/test_models.sh) and
  [`docs/reference/testing-runbook.md`](../../docs/reference/testing-runbook.md) "Model readiness".
- **Single XCUITest stack.** Keep shared waits, fixtures, evidence export, and benchmark contracts
  common across the macOS and physical-iPhone targets. Do not add coordinate hooks, hidden marker
  catalogs, or a second UI driver.

## Common mistakes

- Adding a Debug configuration or generic `#if DEBUG` behavior fork. Use runtime diagnostics or a
  narrowly named test-target compilation condition instead.
- Running iOS UI work in the Simulator or expecting ordinary CI to drive the UI. Use the physical-
  iPhone XCUITest lanes for explicit frontend acceptance, never as an archive/TestFlight or
  development-publishing prerequisite.
- Committing raw `.jsonl` telemetry to `benchmarks/`.
- Editing `benchmarks/HISTORY.md` by hand or treating a failed/incomplete run as publishable.
- Assuming preserved-dSYM drift needs a manual rebuild: the build-output policy check re-syncs
  `build/artifacts/symbols/{macos,ios}` from the dSYM beside the current product when its UUIDs
  prove identity, and fails only when no matching local dSYM exists.
- Changing signing/notarization env vars without updating the workflow secret docs.
