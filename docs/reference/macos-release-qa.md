# macOS Release QA — the desktop release gate

> Before starting a release run, confirm the active acceptance state in
> [`docs/development-progress.md`](../development-progress.md).

The standing pre-release procedure for a macOS (Vocello.app / DMG) release. First executed in full
for v2.1.0 (2026-06-09); rerun the deterministic gates for every release, run the standing
release-candidate smoke lane and record its verdict (step 2b), and use the benchmark UI lane only
when frontend acceptance is explicitly requested. If this doc disagrees with the code,
the code wins.

This is a release-only gate, not a commit, push, pull-request, ordinary-merge, or ordinary-CI
check. Missing model or XCUITest evidence never blocks a macOS package. Signing, notarization, and
upload depend on deterministic release-readiness and artifact checks.

> For the macOS testing/debugging/profile lanes + the one-command `gate`, see
> [`macos-testing.md`](macos-testing.md). For the macOS app map + test-driving, see
> [`macos-app-guide.md`](macos-app-guide.md).

## Gate sequence

1. **Static gates** (always):
   ```sh
   ./scripts/check_project_inputs.sh
   ./scripts/build.sh build
   ./scripts/build_foundation_targets.sh macos && ./scripts/build_foundation_targets.sh ios
   ```
2. **Deterministic release readiness** (always):
   ```sh
   scripts/macos_test.sh test
   scripts/macos_test.sh release-readiness
   ```
   The packaging entry point invokes `release-readiness` before signing. It must remain independent
   of installed models and XCUITest evidence.
2a. **Optional model-dependent telemetry diagnostic** (never packaging-blocking):
   ```sh
   scripts/macos_test.sh telemetry-overhead
   ```
   This is deeper engine evidence when the model fixture is available; absence of the fixture does
   not block signing, notarization, or upload. Its three mode-order rotations, raw PCM/timing
   evidence, verdict, and machine context stay local. It does not publish schema-v2 history because
   instrumenting the `off` lane would invalidate the observer-effect comparison.
2b. **Standing release-candidate UI smoke + optional benchmark** (run and record; never
   packaging-blocking):
   ```sh
   scripts/ui_test.sh macos smoke       # standing per-candidate lane; includes visible model readiness
   scripts/ui_test.sh macos benchmark   # optional explicit frontend acceptance
   ```
   Run the smoke lane for every release candidate and record its run ID and verdict — or a
   deliberate skip with the reason — in that release's `docs/releases/<version>.md` entry. The
   lane already writes `run.json` plus a per-run step ledger under the UI-test artifact tree; the
   release-notes line only references that run ID. A missing or skipped run never blocks signing,
   notarization, packaging, or upload — recording the skip keeps the omission visible instead of
   silent.
   If the visible Settings state is incomplete, run `scripts/macos_test.sh models ensure` only as
   an explicit repair/bootstrap action, then start a fresh smoke run.
   XCUITest is the sole autonomous macOS app UI driver and targets its configured native test host.
   Smoke covers sidebar navigation, visible model and clone-reference readiness, one real Custom
   generation, the completed player, and History. Benchmark owns the configurable
   Custom/Design/Clone matrix and defaults to exactly 29 takes. Both lanes fail on a new crash;
   benchmark additionally validates exact telemetry count/order, History, readable WAVs, and
   audio-QC evidence for every take. On PASS, the benchmark automatically publishes one compact
   `ui-generation` record; raw `.xcresult`, screenshots, telemetry, and WAVs stay untracked.
3. **Engine regression net** (when any engine/Sources change since the last green bench):
   ```sh
   # Explicit model-dependent engine QA; repair fixtures only when this optional run is requested.
   QWENVOICE_DEBUG=1 ./build/vocello bench --modes custom,design,clone \
     --variants speed --lengths short,medium,long \
     --warm 3 --voice A_warm_elderly_woman --label "release-QA"
   ```
   Full procedure: [`benchmarking-procedure.md`](benchmarking-procedure.md) §4.1.
   Gate: clean audioQC on all required cells; RTF within noise of the latest
   `benchmarks/HISTORY.md` rows; fixed-seed evidence and any applicable automated
   language/prosody checks pass. Human listening is optional annotation.
   Optional regression compare against a committed baseline:
   ```sh
   python3 scripts/summarize_generation_telemetry.py \
     ~/Library/Application\ Support/QwenVoice-Debug/diagnostics \
     --run-id <run-id> --evidence-manifest <run-artifact-dir>/benchmark-evidence.json \
     --compare-baseline benchmarks/baselines/mac-gate-bench.json \
     --label "release-QA"
   ```
   Investigate any highlighted cell before shipping.
   Successful in-repository benchmarks publish a privacy-safe `engine-generation` record and
   regenerate `benchmarks/HISTORY.md`; do not append to that generated file manually. An optional
   subjective listening note may be added later with `scripts/benchmark_history.py annotate`.
4. **Static audits** (release-sized changesets): use the relevant installed Codex macOS skills
   plus direct code review for SwiftUI architecture/performance, memory, concurrency, signing,
   and security/privacy. Scope findings to changed surfaces; fix or explicitly defer them.
5. **Version bump**: `MARKETING_VERSION` + `CURRENT_PROJECT_VERSION` in `project.yml` (shared by
   the two user-facing targets) → `./scripts/regenerate_project.sh`.
6. **Local package verification**:
   ```sh
   ./scripts/release.sh --preflight full --signing-mode developer-id --signing-identity "<Developer ID Application: …>"
   scripts/verify_release_bundle.sh   # invoked by release.sh; rerun standalone if needed
   ```
   The release runner requires 20 GiB of host free space before readiness work and checks again
   before its isolated build. If it stops, inspect `python3 scripts/build_output_policy.py status`
   and apply only the bounded cleanup it reports; never delete `build/dist/` or the canonical
   development caches merely to satisfy the release lane.
   Release builds use isolated `build/scratch/derived-data/release-macos/` state and place the
   signed app, metadata, and DMG under `build/dist/macos/`; they never invalidate the persistent
   development cache. Routine cleanup does not remove these distribution outputs.
   An attended launch or generation pass can be performed when models are available, but it is not
   part of the packaging gate.
   (No `--notarize` locally unless the API key env vars are present.)
7. **Atomic Release candidate**: push the protected version tag or dispatch `release.yml` with the
   exact existing tag. CI verifies tag/source/version identity, builds, signs, notarizes, staples,
   verifies (`verify_packaged_dmg.sh`), emits SPDX and CycloneDX inventories, writes
   `SHA256SUMS` plus `release-evidence.json`, and attests the DMG. Only then does it create or reuse
   a draft GitHub Release, upload the candidate, download every asset, and verify the digests.
   Reusing a draft first removes every prior asset; the workflow then requires the remote asset-name
   set to match the current candidate exactly before downloading and validating it. Publication is
   the final step. A failure leaves only an Actions artifact or draft Release, never a public
   placeholder or a stale extra asset.

   `release-evidence.json` is schema v2. It embeds a clean full-tree source identity and hashes a
   `release-verification.json` bundle containing the platform required-step ledger and its individual
   manifests. Required steps are accepted only when the release runner launched them as managed
   subprocesses in the same invocation, all digests match the captured source, and completion is
   within the contract's six-hour freshness window. A manually written PASS file, stale ledger,
   missing step, changed untracked source file, or mixed invocation fails before publication.

## Release notes are a release artifact (both stores, fail-closed)

`docs/releases/<tag>.md` is the single source of truth for user-facing release
communication, written for both non-technical and technical readers:

- The release workflow validates it **before any build work**
  (`python3 scripts/check_release_notes.py <tag>`) and sources the GitHub Release body
  from it verbatim on both draft creation and draft reuse — `--generate-notes` stubs
  are banned. The gate requires real substance (a What's new/Headline section,
  Requirements, Install, and a TestFlight What-to-Test section), rejects placeholder
  tokens (PENDING/TBD/TODO/FIXME), and rejects relative markdown links: the file
  renders on the release page too, so links must be absolute.
- The file's `## TestFlight — What to Test (build N)` section is the paste source for
  the build's Test Details in App Store Connect at distribution time. Automating that
  through the ASC API after upload is a recorded enhancement; until it lands, the
  paste is a required step of TestFlight distribution, not an optional nicety.
- Write dual-audience: lead each item with the user-visible change in plain language,
  then the technical grounding. The 2.2.0 notes are the reference standard; the
  v2.3.0 auto-generated stub (caught and fixed post-publication 2026-07-31) is the
  failure mode this section exists to prevent.

## Performance surfaces ship current numbers (standing per-release step)

The README charts and the website Performance section publish measured numbers; a release
must not ship while they describe a superseded build. In the same change set as the
version bump:

- Re-point `RTF_RECORD` in `scripts/generate_readme_charts.py` to the newest canonical
  macOS UI matrix record and regenerate (`python3 scripts/generate_readme_charts.py`;
  its `--check` already fail-closes on stale SVGs), then update the README `<img alt>`
  ranges to match.
- Update `website/src/sections/Engineering.jsx`: the `MODES` medians, the aria-label
  ranges, and the provenance record ID, all from the same record.
- The retired gate chart's same-day A/B pair is pinned history (see "Technical sections
  are maintained surfaces" below); it is never re-pointed, re-measured, or re-promoted
  to a chart.
- If no newer canonical record exists at release time (for example a docs-only patch
  release), record that explicitly in the release notes Evidence section instead —
  the same visible-skip discipline as the smoke lane.
- Which record is "the newest canonical" is a judgment the registry supports
  (clean-source, canonical classification, `passed`/`passedWithWarnings`); dirty-source
  exploratory records never back public numbers.

## Technical sections are maintained surfaces (standing per-release step)

README "Under the hood" and the website Engineering section
(`website/src/sections/Engineering.jsx`) are long-term whole-package surfaces: they
present the owned-runtime derivation, the host architecture, the
streaming/memory/determinism discipline, and the benchmark rigor as one curated story.

- Each release folds durable new results from `benchmarks/OPTIMIZATION.md` and the
  `Packages/VocelloQwen3Core/` ledgers into that story and retires superseded facts;
  the sections are refreshed in the same change set as the version bump.
- A single release's optimization gets **at most one line** inside the broader story:
  never a headline, a standalone chart, or a stat panel. The 2.2 UI-transparency gate,
  demoted on 2026-07-31 after briefly serving as a headline, is the recorded precedent.
- The retired gate chart's A/B record pair (`…-9b6f267b` / `…-083313-d02005ae`) is
  pinned history in prose and `benchmarks/HISTORY.md`; it is never re-measured or
  re-promoted to a chart.
- Every technical subsection and ledger row leads with the plain-language user
  consequence before the technical grounding: the same dual-audience rule as release
  notes.

## Outward-facing performance terminology

Public prose — release notes in `docs/releases/`, the GitHub Release body, the README, and the
website — states generation throughput as a **speed multiple of realtime**: "1.8× realtime",
"past 1.0× realtime", higher is faster. Do not present a bare "RTF" number on those surfaces.
Much of the TTS ecosystem defines RTF as wall-clock time ÷ audio duration (lower is better),
the inverse of this repository's `audioSecondsPerWallSecond`, so an unglossed "RTF 1.1" reads
as slower than realtime to outside readers. If "RTF" must appear in public prose, define it
inline as audio seconds per wall-clock second. Internal surfaces are unchanged: the telemetry
key `audioSecondsPerWallSecond`, benchmark-record `rtf` fields, `benchmarks/HISTORY.md`, and
baseline comparisons keep the higher-is-better metric and name.

## Known-cosmetic non-bugs (do not file)

- Post-retirement readiness note briefly shows "Preparing Custom Voice" (§G residual; no connection
  is made and generation is unaffected).
- Enroll sheet: the first click on "Record…" immediately after typing in the Name field can be
  consumed by the field's focus-commit — a second click opens the sheet (observed v2.1.0 QA).
