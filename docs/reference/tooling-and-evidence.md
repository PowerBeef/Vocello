---
status: active
owner: release-qa
summary: Tooling, CI, packaging, benchmark and evidence rule; Claude Code loads it through .claude/rules/tooling.md when matching files are touched.
paths:
  - "scripts/**"
  - ".github/**"
  - "config/**"
  - "benchmarks/**"
  - ".claude/**"
  - "CLAUDE.md"
---
# Release / QA rule — scripts, CI, packaging, benchmarks, evidence

References, read only what the change needs: `docs/reference/development-workflow.md` (local loop and
CI), `docs/reference/testing-runbook.md` (which lane), `docs/reference/macos-release-qa.md` and
`docs/reference/ios-appstore-submission.md` (release steps), `docs/reference/telemetry-and-benchmarking.md`
(schemas), `docs/reference/ios-device-testing.md` (device procedure).

## How verification is organised

- `scripts/dev.sh check` is the local loop; nothing local blocks a commit except the commit lint. CI on
  `main` is the gate. `scripts/dev.sh ci` runs every gate it runs, serially, without routing.
- `./scripts/check_project_inputs.sh` is the deterministic contract gate: product contracts,
  `scripts/repo_invariants.sh` (exact greps for product invariants), `scripts/privacy_scan.py`, the
  roadmap validator and the Python suite (`pytest -n auto`, on Linux and macOS alike; the `research`
  lane by marker in `scripts/tests/conftest.py`). `scripts/lib/contract_gate.py` runs the validators in
  parallel with grouped output and declares the inputs each reads. `--local` skips a validator none of
  whose inputs the dirty tree touches (one that depends on every tracked file, git history or the date
  declares none and always runs), selects Python tests from the dirty tree and is refused in CI, where
  every validator runs; `--python all|selected|none` picks the lane; `QVOICE_GATES=quick` skips the full
  suite locally while `scripts/` and `config/` are clean. Add a check only when it protects a product
  invariant, with its inputs in `contract_gate.py`; never a check that asserts the wording of another
  script or workflow, except an exact check in `repo_invariants.sh` for an invariant that lives in a
  phone- or UI-only lane no test can run (each such check says so). Lane behaviour is tested by
  running the shipped shell over the recorded stand-ins in `scripts/tests/shell_stubs.py`.
- `ci.yml`: pushes to `main` gate; `pull_request` (never `pull_request_target`) runs only the Linux jobs
  for Dependabot and outside PRs with a read-only token, and their runs never become a lane's green base.
  `scripts/ci/classify_changes.py` routes pushes into lanes, diffing each lane against the last
  run in which that lane's job passed (a cancelled superseded run cannot leave a lane unrun); `macos-tests` and `ios-compile`
  restore the persistent DerivedData caches from `config/build-output-policy.json`
  (`scripts/ci/restore_mtimes.py` first); `contracts` and `python` run on ubuntu, and `contracts` also
  runs shellcheck, ruff, SwiftLint and Pyright over the whole tree, failing only on findings absent from
  `config/lint-baseline/` (`scripts/lint_baseline.py`; a baseline only shrinks); `CI required` is the
  only branch-protection context and passes when jobs are path-skipped. The shared toolchain step is
  `.github/actions/native-toolchain`; `macos-tsan` runs the ThreadSanitizer subset with the Swift lane
  (blocking since 2026-09-14, `config/tsan-policy.json`). `nightly.yml` runs a cold TSan pass, the complete Python suite and cold
  compiles (the macOS app also optimized with warnings as errors) and keeps one open issue labelled
  `nightly`, refreshed rather than duplicated; its report-only jobs (coverage, migrate-mode warnings,
  a Periphery dead-code scan of the macOS app, CLI and iOS app, `scripts/dead_code_report.sh`, and the
  deterministic suites in the shipped configuration, `scripts/macos_test.sh test --shipped-config`)
  file no issue and gate nothing; `security.yml` runs weekly, on dispatch and inside `release.yml` on
  the tagged commit.
- Ordinary CI never executes XCUITest, a model or a device; it compiles `VocelloiOS` and the
  policy-test bundle for `-destination generic/platform=iOS`, runs the macOS deterministic bundles with the direct
  `xcrun xctest` runner, and compiles both XCUITest bundles (`build_ui_test_bundles.sh --gate`,
  build-for-testing in the deterministic arenas). `repo_invariants.sh` check 2 forbids execution in any
  workflow (`test-without-building`, `scripts/ui_test.sh`, an `xcodebuild`/`xcb_run` `test` action), not
  compilation.
- Generated files (`docs/ROADMAP.md`, the production model catalog, the owned-package inventory and
  facade baseline, `docs/charts/*.svg`, `Sources/Resources/third_party_attributions.json`, the Swift
  copy of the Chinese fold table `Sources/SharedSupport/Services/HantHansFoldTable.swift`) are
  regenerated with `scripts/dev.sh regen` (`scripts/refresh_derived_artifacts.py`, which validates
  every artifact it registers) in the same change as their inputs; the attributions follow
  `NOTICES.md`, license inputs, `Package.resolved` and the attribution policy
  (`scripts/attribution_manifest.py rebuild`). `benchmarks/HISTORY.md` is regenerated by `python3
  scripts/benchmark_history.py rebuild-index` (publication does it automatically; the gate runs
  `rebuild-index --check`). The generated-file guard refuses hand edits.

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
  artifacts (gh, swiftlint, ruff, periphery and Sparkle's `sign_update` on demand, the last only
  in the macOS release and rehearsal jobs; the Linux contracts job installs the
  `-linux-x86_64` shellcheck, ruff and swiftlint entries); numpy, pytest and pytest-xdist pip-pin to
  the manifest and Pyright npm-pins to its `npmPins` entry; the website's Node and npm pin only their major version (24 / 11). Dependabot proposes, the manifest and comment change together:
  on a Dependabot action PR run `python3 scripts/supply_chain_contract.py --sync-actions` and push the
  manifest to its branch; CI never writes back.
- **Exact-source releases.** `release_source_authority.py` proves a GitHub-verified annotated `v*` tag on
  the checked-out commit, containment in `origin/main` and a successful latest `CI required` run of a
  push to main; the release workflow runs Security on that commit first, and every later job builds
  that authorized commit, never the tag ref again. Promotion runs from the tag under the `release`
  environment and verifies each DMG's build attestation from `release.yml`. Lightweight tags, cross-SHA checks and incomplete
  check-run pagination fail closed. Every release step matches its `config/orchestration-contract.json`
  template; schema-v2 release evidence accepts only a clean full-tree identity and same-invocation step
  manifests. Never restore a `release.published` trigger; `--generate-notes` is banned and
  `scripts/check_release_notes.py` gates the tag's curated notes under `docs/releases/`.
- **Separate public promotion.** A public macOS release or external TestFlight/App Review needs
  exact-tag `quality-promotion.json` validated by `scripts/quality_promotion.py`; candidate production
  never waits for device availability.
- **Evidence retention.** Only qualified privacy-safe PASS records enter `benchmarks/runs/` (≤ 256 KB
  each, strict allowlist), then `benchmarks/HISTORY.md` is regenerated. Raw JSONL, WAV, screenshots,
  xcresult and traces stay untracked; publication never stages, commits or pushes. Successful profiles
  publish their digest and summary first; a CPU profile's raw trace is then deleted (`--keep-trace` is
  explicit), while a memory profile keeps its trace by default (`keptByDefault`).
- **Records measure what they claim.** `rtf` is wall ÷ audio (lower is faster) and every RTF-bearing record
  since 2026-09-12 declares `run.rtfDefinition` (`ui-perf` publishes no RTF); legacy records are never rewritten and never share a comparison
  key with new ones. A comparison key names what its kind measures (`scripts/lib/lineage_identity.py`: the
  project.yml build settings its lane builds, the take topology and a reviewed per-kind measurement version
  beside hardware, OS, toolchain, matrix, corpus, models, evidence and memory contracts and metric
  definitions; contract 2 adds a forced or emulated memory tier, the run's seed policy and the cell
  aggregate version, and keeps the contract-1 key at their defaults; never engine sources or pins), and
  legacy and contract-1 keys stay byte-identical. Once a record of a kind
  carries the lineage stamp, a change that moves what that kind measures (an in-window driver step, a
  probe, the metric mapping or aggregation) bumps its measurement version in the same change
  (`scripts/dev.sh check` names changed files on a kind's path list); changing what the key reads bumps
  `LINEAGE_CONTRACT_VERSION` and never edits a published version's key. `toolchain.optimization` comes
  from the build receipt (`last-build.json`, executable digest bound) via
  `scripts/lib/build_provenance.py`; the gate bench is seeded, compares medians of five
  warm takes against a baseline pooled from at least three seeded runs on one clean commit (thresholds
  floored by the between-run spread and printed), and reports a loaded, throttled or low-power host as
  inconclusive (`GATE: INCONCLUSIVE`, exit 3), never as pass or fail. A timing take whose own one-minute
  load exceeded the core count marks its engine or UI benchmark record (macOS or iPhone) exploratory.
- **Memory-qualified publication.** Telemetry schema v8 or newer (records are v8; streaming v9 is a
  digest-bound sidecar), manifest v2, exact sidecar digests, memory contract v2 (one series per
  process; no gap between samples above `unobservedGapBound` in
  `config/memory-qualification-policy.json`, twice the cadence with a 500 ms floor, calibrated on the
  M6 on 2026-09-25, and a 1,000 ms floor on the iPhone and 8 GB Mac until a record of theirs
  calibrates it; each take's sampled peaks published against the exact high-water marks,
  MLX's per-request peak and the kernel footprint ledger when sampled, a ledger below a sample
  failing), zero capture failures, no critical pressure, warning, `hardTrim` or `fullUnload`;
  contract-v1 records keep their ≥95% coverage rule. Marking evidence keeps the take peak
  (`config/marking-peak-equality.json`).
- **Audio QA: Fast QC gates, QC v2 reports, no automated score is a quality verdict
  (`docs/reference/qc.md`).** For 3.0 nobody listens (maintainer decision 2026-10-13): RF-14 and RF-15
  use a machine screen for gross failures only (Fast QC, end of take, the better ASR family's edit rate
  and the language check), and subtle defects ship as the documented known limitation.
  Fixed seeds and byte-bound PCM Fast QC stay mandatory; Fast QC thresholds stay in Swift. QC v2 is
  a report-only diagnostic: some detectors have historical human-recording calibration (`qc.py controls`,
  `qc.py calibrate`), while current acceptance requires complete inputs and qualified scoring/runner
  identities; strict `gate` exits 4 (`NOT_ASSESSED`) when required coverage is unqualified or stale. The 39
  blind confirmations by ear (`qc.py confirm`, 2026-10-06) did not establish useful defect
  discrimination. Historical warnings mean unusual, not defective; they do not fail a lane or
  justify a release decision. A qualified defect still fails the strict gate even if another
  dimension is incomplete. Thresholds freeze in
  `config/qc/thresholds-v<N>.json`, bound to the scoring code and norms, and are committed before
  `qc.py eval` sets their levels; a model, feature or threshold change is a new version. A listening
  verdict never clears a machine failure. Language verdicts name their recognizer families (Apple
  Speech in the iPhone app, QC v2's two ASR families on the Mac); one family is one witness, two must
  agree for consensus, and shared metrics live in `scripts/lib/language_metrics.py` and
  `scripts/lib/audio_qc.py`. Labels, transcripts and take paths stay under `build/private/qc`; Git
  holds aggregates and digests. Every QC model's weights carry a commercial-use license
  (`config/qc/models.json`).
- **UI timing gates are declared.** The macOS UI benchmark's stall gate takes its statistic, limit and
  calibration profile from `config/macos-ui-stall-gate.json`; a provisional limit only reports, and only
  a contract calibrated with its run IDs fails a run. ui-perf ceilings stay warn-only; a
  recalibration derives them from the run-to-run spread of at least three counted runs with a 1.25-1.3x
  floor, and a run off the contract's calibration profile or refresh interval, or under a contract
  marked `calibrationStale` after its scenarios changed meaning, carries `uiperf.uncalibrated:<profile>`
  instead of ceiling verdicts.
- **Targeted local acceptance.** Local device/UI/model/benchmark validation is authorized at coherent
  checkpoints. Choose the smallest relevant existing lane; full matrices remain task/release-specific.
  Run source-bound measurements on committed checkpoints in the lead session after joining workers.
  The existing non-timing audio-QC exception may use `agents-allowed`; native serialization, load and
  memory checks still apply. `require_quiet_host` uses live worker leases, not Git worktree locks.
  Cache-only analysis of existing audio/results uses `check_cache_only_host`: load and pressure are
  recorded without refusal. Worker ownership and native serialization still apply; this mode makes
  no timing/memory qualification claim and does not authorize inference or native generation.
  Unavailable tracking requires explicit `QVOICE_LEAD_ONLY=1` after joining workers; unknown ownership
  blocks even exploratory overrides. `QVOICE_ALLOW_BUSY_HOST=1` preserves exploratory classification,
  never publication authority. Runner PASS requires diagnostics, crash deltas and restoration.
  Preserve failures; a justified rerun gets a new ID and explanation. Source changes need new IDs.
  XCUITest is never a packaging/notarization/upload prerequisite. Releases and external writes require
  a specific request; pushes require an explicit request.
- **TSan.** `config/tsan-policy.json` names the subset, the tests that skip under the sanitizer and the
  blocking decision; push CI and the nightly run it; never weaken deterministic or MLX runtime coverage
  to make it pass, and never relax the status without a new dated decision.
- **Assistant state stays external.** Sessions, memory, credentials and personal settings never enter
  Git, CI or evidence. Track only shared instructions, reviewed hooks, rules, skills and subagents.
  Claude Code settings, skill and subagent metadata and rule front matter are executable
  configuration: their changes route to the existing Python tests (`test_agent_hooks.py`).

## Common mistakes

- Adding a validator that greps another script's text, or a Python test of a Python gate.
- Committing raw telemetry, editing `benchmarks/HISTORY.md` or `docs/ROADMAP.md` by hand.
- Running iOS UI work in the Simulator or making ordinary CI wait for a phone, a model or XCUITest.
- Clearing caches to evade native-lock contention instead of serializing native commands, or running
  native builds outside the host-wide lock (MobileBuildMCP/XcodeBuildMCP builds bypass it).
- Editing, committing or integrating agent work while a UI or benchmark lane runs: publication compares
  the pre- and post-run tree fingerprints, and a mismatch demotes the record to exploratory.
- Publishing a canonical macOS UI benchmark record without, in the same commit, running
  `generate_readme_charts.py` (public medians pool the warm takes of up to five canonical records of the
  newest record's lineage and build, a new lineage or build starting a pool of one, never repinned to one
  record) and updating the website medians and provenance line; the chart check fails otherwise. New
  records store `comparison.deltaMetrics: trend-v1` to stay under the 256 KiB cap.
- Leaving a dated doc orphaned or stubbed: delete an unlinked dated doc, mark a linked one
  `status: historical`, and never leave "(removed …)" stubs.
- Bumping a roadmap item's `updated` without a status, gate or evidence change, or superseding without
  `supersededBy` on the loser and `legacyIds` on the winner. Park device-blocked work with a precise
  `unparkWhen`; change items with `roadmap.py set`, `note` and `close` (one validated call that also
  re-renders), and end any hand edit with `roadmap.py validate` and `render`.
- Starting work outside the focus plan while `focusLock` holds, or moving `primaryPlan` without rewriting
  `focusLock` as a new dated decision. After `focusLock.freeze` names the freeze commit, every later commit
  names an item of the focus plan in its subject; a slipped commit is accepted only through
  `freeze.exceptions` (full sha and reason). Treat a
  passed `due` as a decision (cut, move with a reason, or close), never a silent extension.
