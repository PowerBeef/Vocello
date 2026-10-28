---
status: active
owner: release-qa
reviewed: 2026-10-28
summary: The standing macOS release-QA checklist — deterministic gates, the per-candidate smoke step, release-notes and performance-surface obligations, packaging and verification.
sourceOfTruth:
  - scripts/release.sh
  - scripts/lib/release_signing.sh
  - scripts/sparkle_appcast.py
  - scripts/release_build_number.py
  - docs/reference/macos-app-guide.md
  - .github/workflows/release.yml
  - .github/workflows/release-rehearsal.yml
  - .github/workflows/promote-release.yml
  - scripts/macos_test.sh
  - scripts/cli_package.py
  - scripts/verify_packaged_dmg.sh
  - scripts/verify_packaged_cli.sh
---
# macOS Release QA — the desktop release gate

> Before starting a release run, confirm the active acceptance state in
> [`docs/development-progress.md`](../development-progress.md).

The standing pre-release procedure for a macOS (Vocello.app / DMG) release. Rerun the deterministic
gates for every release, run the standing release-candidate smoke lane and record its verdict (step
2b), and run the benchmark UI lane when the release or task calls for its full matrix. If this doc
disagrees with the code, the code wins.

This is a release-only gate, not a commit, push or push-CI check. Missing model or XCUITest
evidence never blocks a macOS package. Signing, notarization, and upload depend on deterministic
release-readiness and artifact checks.

> For the macOS testing/debugging/profile lanes and the one-command `gate`, see
> [`macos-testing.md`](macos-testing.md#platform-gate-scriptsmacos_testsh-gate). For the macOS app
> map + test-driving, see [`macos-app-guide.md`](macos-app-guide.md).

## Gate sequence

1. **Deterministic gate** (always): exactly what push CI runs, serially.
   ```sh
   scripts/dev.sh ci
   ```
2. **Deterministic release readiness** (always):
   ```sh
   ./scripts/build.sh build
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
   evidence, verdict, and machine context stay local. It does not publish benchmark history (schema
   v3) because instrumenting the `off` lane would invalidate the observer-effect comparison.
2b. **Standing release-candidate UI smoke + optional benchmark** (run and record; never
   packaging-blocking):
   ```sh
   scripts/ui_test.sh macos smoke       # standing per-candidate lane; includes visible model readiness
   scripts/ui_test.sh macos benchmark   # optional explicit frontend acceptance
   ```
   Run the smoke lane for every release candidate and record its run ID and verdict — or a
   deliberate skip with the reason — in that release's `<version>.md` entry under `docs/releases/`. The
   lane already writes `run.json` plus a per-run step ledger under the UI-test artifact tree; the
   release-notes line only references that run ID. A missing or skipped run never blocks signing,
   notarization, packaging, or upload — recording the skip keeps the omission visible instead of
   silent.
   If the visible Settings state is incomplete, run `scripts/macos_test.sh models ensure` only as
   an explicit repair/bootstrap action, then start a fresh smoke run.
   XCUITest is the only automated UI evidence and targets its configured native test host; computer
   use, between lanes, covers what it cannot (`/vocello-ui-autonomy`). What smoke's fifteen
   journeys (about 11 minutes) and the 29-take benchmark prove is in
   [`macos-testing.md`](macos-testing.md#explicit-xcuitest-lanes). Both lanes fail on a new crash.
   On PASS, the benchmark publishes one compact `ui-generation` record; raw `.xcresult`,
   screenshots, telemetry, and WAVs stay untracked.
3. **Engine regression net** (when any engine/Sources change since the last green bench):
   ```sh
   # Explicit model-dependent engine QA; repair fixtures only when this optional run is requested.
   QWENVOICE_DEBUG=1 ./build/vocello bench --modes custom,design,clone \
     --variants speed --lengths short,medium,long \
     --warm 3 --voice A_warm_elderly_woman --label "release-QA"
   ```
   Full procedure: [`telemetry-and-benchmarking.md`](telemetry-and-benchmarking.md) §4.1.
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
4. **Static audits** (release-sized changesets): use the relevant installed macOS skills (Axiom auditors, the
   `vocello-swift-review` subagent) plus direct code review for SwiftUI architecture/performance, memory, concurrency, signing,
   and security/privacy. Scope findings to changed surfaces; fix or explicitly defer them.
5. **Version bump**: `MARKETING_VERSION` + `CURRENT_PROJECT_VERSION` in `project.yml`'s project-level
   `settings.base` (shared by every generated target) → `./scripts/regenerate_project.sh`.
   `CURRENT_PROJECT_VERSION` (the app's CFBundleVersion, Sparkle's `sparkle:version`) must be greater
   than at the previous `v*` tag in version order, or installed copies are never offered the update;
   `release.yml` checks it before signing (`scripts/release_build_number.py check --tag <tag>`). The
   rule does not depend on Sparkle: v2.4.0 shipped build 23 without it, and 3.0.0 shipped build 24. With no
   earlier `v*` tag the check passes; an earlier tag whose `project.yml` cannot be read fails it.
6. **Local package verification**:
   ```sh
   ./scripts/release.sh --preflight full --signing-mode developer-id \
     --signing-identity "<Developer ID Application: …>" \
     --installer-identity "<Developer ID Installer: … (TEAMID)>"
   scripts/verify_release_bundle.sh   # invoked by release.sh; rerun standalone if needed
   ```
   Developer ID mode needs both identities of the release Team ID (`APPLE_TEAM_ID`); the
   installer identity may also come from `APPLE_DEV_ID_INSTALLER`, and one whose name does not end
   in `(<release Team ID>)` is refused before any work starts. Ad-hoc mode leaves the CLI
   installer package unsigned.
   The release runner requires 20 GiB of host free space before readiness work and checks again
   before its isolated build. If it stops, inspect `python3 scripts/build_output_policy.py status`
   and apply only the bounded cleanup it reports; never delete `build/dist/` or the canonical
   development caches merely to satisfy the release lane.
   Release builds use isolated `build/scratch/derived-data/release-macos/` state and place the
   signed app, metadata, desktop DMG, separate CLI DMG, CLI installer package
   (`<output>-cli.pkg`) and its `cli-pkg-verification.json` under `build/dist/macos/`; they never invalidate the persistent
   development cache. Routine cleanup does not remove these distribution outputs.
   `verify_packaged_dmg.sh … --include-cli --include-pkg <pkg>` installs into `/usr/local` with
   `sudo`, so locally it refuses with exit 2; run it without `--include-pkg`, and `release.sh`'s
   root-free `pkg-verify` covers the package.
   An attended launch or generation pass can be performed when models are available, but it is not
   part of the packaging gate.
   (No `--notarize` locally unless the API key env vars are present.)
7. **Atomic Release candidate**: first push the release commit to `main` and wait for its latest
   `CI required` check run to complete successfully (Security runs inside `release.yml`). Create an annotated,
   cryptographically signed version tag at that exact commit (for example
   `git tag -s vX.Y.Z <commit>`), push the tag, or dispatch the tag's own workflow with
   `gh workflow run release.yml --ref vX.Y.Z -f tag=vX.Y.Z` (the `release-trigger` job refuses a
   dispatch from any other ref, because a dispatch runs the workflow file of the ref it came from).
   The `package` and `sparkle-feed` jobs use the tag-restricted `release` environment (with a
   required reviewer, each asks for approval). GitHub must report the annotated tag object's signature as verified with reason `valid`;
   a lightweight, unsigned, invalid, or differently targeted tag cannot build a candidate. The
   source-authority job also proves that the tag commit is contained in `origin/main` and that both
   required checks belong to that exact SHA before any platform job starts. The `package` job then
   verifies tag/source/version identity and that the build number grew, builds, signs, notarizes,
   staples and verifies both DMGs and the CLI installer package (`verify_packaged_dmg.sh …
   --include-cli --include-pkg <output>-cli.pkg`, which also installs, upgrades and uninstalls the
   package on the runner; see [CLI distribution](#cli-distribution-and-qualification)) with a
   read-only token, and hands the DMG on with its SHA-256. The `sparkle-feed` job signs that DMG and `appcast.xml` on a fresh
   runner (see [Sparkle updates](#sparkle-updates-rf-23)). The `draft-release` job, the only one
   with `contents: write` and holding no secret, checks both digests, re-verifies the feed, emits
   SPDX and CycloneDX inventories, writes `SHA256SUMS` plus `release-evidence.json` (the appcast,
   the CLI installer package and its `cli-pkg-verification.json` are among its artifacts), and
   attests both DMGs and the CLI installer package. The CLI report is a required,
   hashed output of the managed artifact-verification step and binds the exact CLI DMG and
   source/version/build; `release.sh`'s package report binds the exact package to the same sealed
   folder. Only then does it create or reuse
   a draft GitHub Release, upload the candidate, download every asset, and verify the digests.
   Reusing a draft first removes every prior asset; the workflow then requires the remote asset-name
   set to match the current candidate exactly before downloading and validating it. The workflow
   always stops at that verified draft. A failure leaves only an Actions artifact or draft Release,
   never a public placeholder or a stale extra asset. The repository retains direct administrator
   development on `main`; that bypass is explicitly not release authority, and no manual rerun can
   substitute missing exact-SHA checks or an unverified tag.

   `release-evidence.json` is schema v2. It embeds a clean full-tree source identity and hashes a
   `release-verification.json` bundle containing the platform required-step ledger and its individual
   manifests. Required steps are accepted only when the release runner launched them as managed
   subprocesses in the same invocation, all digests match the captured source, and completion is
   within the contract's six-hour freshness window. A manually written PASS file, stale ledger,
   missing step, changed untracked source file, or mixed invocation fails before publication.

8. **Source-bound public promotion**: follow
   [`quality-promotion.md`](quality-promotion.md) on the clean tag checkout. Produce the canonical
   Mac generation matrix and every path-classified engine, retained-memory, UI-performance, or
   model-delivery lane; assemble and validate `quality-promotion.json`; then upload it to the draft.
   Dispatch `promote-release.yml` from the tag itself (`gh workflow run promote-release.yml --ref
   <tag> -f tag=<tag>`; any other ref is refused). It runs under the reviewer-gated `release`
   environment, verifies every DMG and installer package the release evidence names (both DMGs and
   the CLI package) against its build attestation from `release.yml`, requires
   the release evidence to name the checked-out commit and carry its contracts, and revalidates the
   promotion manifest before changing the draft to public. Device
   or model availability can delay public promotion, but never candidate building, signing,
   notarization, attestation, or draft upload. The maintainer published Mac and CLI 3.0.0 on
   2026-10-23 without a promotion record; RF-10 records that exception and its open lanes.

## Sparkle updates (RF-23)

The Mac app updates itself with Sparkle 2. Its `SUFeedURL` reads `appcast.xml` from the latest
published Release (`releases/latest/download/appcast.xml`), and its `SUPublicEDKey` is the public
half of the EdDSA key held only as the `release` environment secret `SPARKLE_ED_PRIVATE_KEY`.
Promotion with `--latest` is therefore what offers an update to installed copies; a draft or a
prerelease offers nothing.

- **Signing the bundle.** `release.sh` re-signs every embedded framework inside-out
  (`scripts/lib/release_signing.sh`): the code nested in it first, then the framework, then the
  app. For Sparkle that is `Autoupdate`, then `Updater.app`, then `Sparkle.framework`, each with
  the release identity, a secure timestamp, the hardened runtime and no entitlements. The app is
  not sandboxed, so Sparkle's XPC services (`Installer.xpc`, `Downloader.xpc`, which only
  sandboxed hosts use) are removed before signing; the app must not set
  `SUEnableInstallerLauncherService` or `SUEnableDownloaderService`. Any other Mach-O nested in a
  framework is signed the same way, never left ad hoc.
- **Verifying the bundle.** `verify_release_bundle.sh` fails when `Sparkle.framework` still holds
  `XPCServices`, and in signed mode checks every Mach-O under `Contents` except the app's own
  executable (each framework's binary, `Autoupdate`, `Updater.app` through its executable, and any
  helper, plug-in or library elsewhere in the bundle) for the release Team ID, the hardened runtime
  and an empty entitlement set (`entitlement_contract.py verify-bundle --role macos-framework`);
  the app's executable is held to the app allowlist (`--role macos-app`).
- **Where the key lives.** Only `release.yml`'s `sparkle-feed` job receives
  `SPARKLE_ED_PRIVATE_KEY`, and only in its signing step. That job runs on a fresh runner after
  `package`, with a read-only token: it downloads the DMG `package` uploaded, refuses it unless
  its SHA-256 matches the one `package` recorded after verification, and installs nothing but
  `sign_update` from the SHA-pinned `Sparkle-2.10.0.tar.xz` (`config/toolchain.json`
  `artifactPins.sparkle`, digest checked before extraction; it moves with the Sparkle package
  pin, and `scripts/supply_chain_contract.py` fails when the two versions differ). It builds,
  tests and pip-installs nothing and restores no cache, so no third-party code from the build can
  share a runner with the key. The job that writes the draft (`draft-release`) holds no secret.
- **The feed.** `python3 -I -S scripts/sparkle_appcast.py create` (standard library only) reads
  the feed's values from the app users install: it attaches the DMG read-only (`hdiutil attach
  -readonly -nobrowse -noautoopen`), reads `CFBundleVersion`, `CFBundleShortVersionString`,
  `LSMinimumSystemVersion`, `SUPublicEDKey` and `SUFeedURL` from the one app at its top level, and
  detaches. It calls `sign_update` by absolute path with only `PATH=/usr/bin:/bin` in its
  environment and an empty working directory; the key reaches it only on standard input, and the
  tool's output is withheld on failure because it echoes a key it cannot decode. The DMG's
  signature must verify against the app's own `SUPublicEDKey` (RFC 8032 Ed25519), so a secret
  that is not the app's pair fails the run. The helper then renders a one-item RSS feed:
  `sparkle:version` (CFBundleVersion), `sparkle:shortVersionString`,
  `sparkle:minimumSystemVersion` (LSMinimumSystemVersion, 26.0), the enclosure URL
  `…/releases/download/<tag>/<dmg>`, its length and `sparkle:edSignature`, a `pubDate` from the
  tagged commit's time, and the Releases page as the item link and `sparkle:fullReleaseNotesLink`.
  No inline release notes are published.
- **The signed feed.** The app requires a signed feed (`SURequireSignedFeed`, with
  `SUVerifyUpdateBeforeExtraction`), so the helper has `sign_update --ed-key-file -
  --disable-signing-warning` sign `appcast.xml` too. Sparkle 2.9 and later embed that signature
  as a trailing `<!-- sparkle-signatures: edSignature … length … -->` comment over the bytes
  before it, which installed copies verify against `SUPublicEDKey` before they read the feed (the
  signing warning is disabled because adding it makes `sign_update` reserialize the XML). The
  helper writes `appcast.xml` only after that signature verifies against the same key and covers
  exactly the feed it rendered. Any later change to the file, even whitespace, needs a new
  signature, so never edit a published `appcast.xml` by hand.
- **The draft.** `draft-release` checks the DMG and `appcast.xml` against the digests the earlier
  jobs recorded, re-runs the secret-free `sparkle_appcast.py verify` (feed signature, versions
  against the DMG's app, enclosure URL, length and signature over the DMG's bytes), then writes the
  evidence. `appcast.xml` is a release-evidence artifact, so `SHA256SUMS` covers it, the draft
  carries it beside the DMG, and promotion's exact-asset check accepts it.
- **Rehearsal.** `release-rehearsal.yml` mirrors the three jobs (`macos-package`, `sparkle-feed`,
  `evidence`) with an ephemeral key and verifies against that key's public half (`--public-key`);
  it still requires the app's `SUPublicEDKey` and an `SUFeedURL` that names `appcast.xml`.
- **Order matters.** The signature covers the stapled DMG's bytes, so nothing may modify the DMG
  after `package` records its digest; the later jobs check that digest and the evidence then binds
  both files.

## Attended walk of the converged screens (per candidate, ten minutes)

Since the macOS app adopted the iOS screens (plan `macos-ios-convergence-2026-09`, closed
2026-09-15), the smoke lane proves the journeys and this walk catches what a lane does not see:
copy, spacing and French. Run it on the candidate build with the interface language set to
French once and to System Default once (Settings, `settings_appLanguage`); the app is dark-only.

1. **Sidebar and status**: brand lockup, then the four destinations (Studio, Voices, History, Settings); the inline
   player card and the status strip under it (`sidebar_backendStatus`, `sidebar_generationStatus`)
   reflect the engine's load state; ⌘1–⌘6 switch screens.
2. **Built-in Voice**: composer with the character count, the speaker, delivery, language and seed
   chips as menus on pills, the readiness line, the Generate CTA in the dock; generate one take and
   confirm the live card's Cancel, then the completed card's Retry, Save As, Reveal and dismiss.
3. **Voice Design**: the brief editor above the composer with its starters menu and character
   count; a completed take offers Save as voice; the saved voice appears in Saved Voices.
4. **Voice Cloning**: the reference chip lists saved voices (persona rows for emotion banks) with
   Import, Record and Clear inside; drop an unsupported file and confirm the footer warning; the
   transcript field, the one-time consent and the readiness line read correctly.
5. **Batch and long-form**: the Batch toggle selects line-by-line and Generate then opens the sheet in line mode; a script over 900
   characters routes Generate to long form; run a two-line batch, cancel a long-form project and
   resume it, regenerate one segment; the dock behind the sheet shows the live card.
6. **History, Saved Voices, Settings**: sort and search in the toolbar, the long-form segments
   toggle, Save As and Reveal; the enroll and record sheets; the recommended-setup summary, the
   per-mode Speed and Quality rows with their actions, prefer-speed, variation, the output folder,
   Application data and clone consent; Cmd+, opens the same screen in its own window.

Anything that reads wrong in French is a catalog fix (`MacInterfaceText` + `Localizable.xcstrings`),
never a code-side literal; see [`localization.md`](localization.md).

## CLI distribution and qualification

The same `release.sh` invocation builds optimized arm64 `VocelloCLI` without internal diagnostic
capabilities. It stages the executable with source-bound catalogs, dependency resource bundles,
MLX metallib, project license, and notices rendered from `third_party_attributions.json`.
No model weights or Python are bundled. The entire `Vocello CLI` folder must remain together.
The executable is signed with hardened runtime and no entitlements (the `macos-cli` entitlement
role). The sealed folder then ships twice from the same bytes:

- **The installer package `<output>-cli.pkg`** (step 6/8), the primary form. `cli_package.py pkg`
  builds it from the sealed folder (installed at `/usr/local/lib/vocello`, receipt
  `com.qwenvoice.cli`, links `/usr/local/bin/vocello` and the zsh completion; the shipped
  `uninstall.sh` removes them and never the data store). In developer-id mode `productsign
  --timestamp` signs it with the Developer ID Installer identity, which must name the release
  Team ID; the signed package's signer must be exactly that identity. It is notarized and stapled
  through the same `release_notarize` function as both DMGs (`scripts/lib/release_signing.sh`),
  then expanded with `pkgutil --expand-full` and checked by `cli_package.py pkg-verify
  --root-free-install` against the sealed manifest digest, with the signature and notarization it
  claims (`developer-id-installer`/`stapled` for a release, `unsigned`/`not-performed` in ad-hoc
  mode, where the package keeps the same name). The report is `cli-pkg-verification.json`;
  `release-metadata.txt` names both as `cli_pkg_name` and `cli_pkg_verification`.
- **The DMG folder `<output>-cli.dmg`**, which stays the fallback for anyone who cannot or will not
  use an administrator password: copy the folder anywhere and run it in place. It follows the same
  Developer ID notarization and stapling sequence as the app.

A staging failure does not replace any accepted user installation; temporary payloads and the
expanded package are removed at exit.

**The install test.** `verify_packaged_cli.sh --include-pkg <pkg>` (from `verify_packaged_dmg.sh
… --include-cli --include-pkg`, in the managed artifact-verification step of `release.yml` and of
the rehearsal) checks that the package is the one the metadata names and `release.sh`'s report
binds; for a signed release, its Developer ID Installer signature of the release team, its stapled
ticket and Gatekeeper's install assessment; that its payload holds the sealed manifest and a
`vocello` with the `macos-cli` entitlement set. Then, on the runner, it runs `sudo installer -pkg …
-target /`, checks the receipt version, the two relative links resolving into
`/usr/local/lib/vocello` and the installed manifest, smokes the CLI through `/usr/local/bin/vocello`,
installs again over a planted stale file that must disappear, runs `sudo sh
/usr/local/lib/vocello/uninstall.sh`, and requires the receipt, folder and links gone and
`~/Library/Application Support/QwenVoice` unchanged. It runs only on an ephemeral GitHub-hosted runner
(`CI=true`, `GITHUB_ACTIONS=true`, `RUNNER_ENVIRONMENT=github-hosted` and passwordless `sudo`); anywhere
else it refuses with exit 2 before invoking `sudo`. The package scripts refuse a `/usr/local` or
`/usr/local/lib` that anyone but root can change, so the first rehearsal also confirms the runner's
`/usr/local` ownership. The
rehearsal installs the unsigned package. The install test is recorded by the step's ledger and
command template, not by `cli-pkg-verification.json`, whose `installTest` stays `not-performed`.

**Maintainer setup.** Two secrets in the tag-restricted `release` environment hold the Developer
ID Installer certificate of the release team: `APPLE_DEV_ID_INSTALLER_P12_BASE64` (the certificate
and its private key exported from Keychain Access as a `.p12`, then `base64 -i installer.p12`) and
`APPLE_DEV_ID_INSTALLER_P12_PASSWORD`. `release.yml` imports it into the same temporary keychain as
the Developer ID Application identity and removes both with that keychain. The current certificate
was issued on 2026-10-23 and expires on 2027-11-22; renew it and replace both secrets before then.

The copied-package verifier checks content digests, arm64-only architecture, system-only dynamic
linkage, embedded version/build, JSON mode/speaker discovery, and invalid-command exit status
from a working directory outside the checkout. Missing or newly dynamic non-system dependencies
fail closed and must be deliberately packaged and verified before release. No resource lookup
rewrite was needed by the initial relocation proof.

This deterministic smoke does not run synthesis. `cli_package.py qualify` additionally qualifies
all three modes, French Design with a pinned seed, Clone, one two-item batch in a single process,
cancellation, generation-error exit status, and resource loading during real inference on the
copied **signed candidate** ([CLI reference](cli.md#build--run)); the shipped 3.0.0 CLI passed it
(RF-10, still in flight for its remaining lanes). Record those results separately; neither a
development CLI smoke nor a valid manifest closes RF-10 or authorizes publication.
Cancellation qualification requires the command's cleanup acknowledgement, exit 130, and absence
of both the cancelled destination and its UUID staging WAV. A forced exit or host-side deletion
cannot produce PASS. Keep failed output and the partial report for investigation. Native signal
and shared-store subprocess fixtures are deterministic prerequisites, not a substitute for this
copied-candidate run.

The schema-v2 qualifier records batch order, distinct WAV digests/durations, EOS, PCM integrity,
and absence of unexpected output/staging. Legacy batch success JSON remains unchanged and lacks
per-item QC receipts; do not represent the batch block as strict-QC or perceptual evidence.
Failure retains raw batch rows alongside the ignored WAVs, never in the privacy-safe summary.

## Release notes are a release artifact (both stores, fail-closed)

The `<tag>.md` file under `docs/releases/` is the single source of truth for user-facing release
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
- Published notes (v3.0.0 and earlier) stay as published; a later release writes its own
  file.
- Write dual-audience: lead each item with the user-visible change in plain language,
  then the technical grounding. The 2.2.0 notes are the reference standard; the
  v2.3.0 auto-generated stub (caught and fixed post-publication 2026-07-31) is the
  failure mode this section exists to prevent.

## Performance surfaces ship current numbers (standing per-release step)

The README charts and the website Performance section publish measured numbers; a release
must not ship while they describe a superseded build. In the same change set as the
version bump:

- Regenerate the charts (`python3 scripts/generate_readme_charts.py`; its `--check`
  fail-closes on stale SVGs and README alt text). The chart anchors on the newest
  canonical macOS UI matrix record and pools the warm takes of up to five canonical
  records that share its comparison key, app version and build, and dependency lock;
  a lineage change or a new build resets the pool, so it never spans builds.
- Update `website/src/sections/Engineering.jsx`: the `MODES` medians and the
  provenance line (the generator prints both), and the aria-label ranges. The
  provenance line mirrors the chart footer: "Record <anchor>" for a pool of one,
  "Median of N records through <anchor>" when N > 1.
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

The README's "For developers" section (chiefly "Engineering highlights") and the website Engineering
section (`website/src/sections/Engineering.jsx`) are long-term whole-package surfaces: they
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

Since 2026-09-12 every surface — release notes in `docs/releases/`, the GitHub Release body, the
README, the website, telemetry, benchmark records, `benchmarks/HISTORY.md` and baseline
comparisons — uses the **standard real-time factor**: seconds of generation per second of audio,
lower is faster, below 1.0 is faster than real time ("RTF 0.60"). Define it inline the first time
it appears in public prose, and when a speed multiple helps the reader give it as a companion
("RTF 0.60, about 1.7× real time"), never as the headline. The decode-loop speedup that older
records stored under `rtf` is `decodeSpeedupX` and is never called RTF. Generation records are
schema v3 and `ui-perf` records schema v2; every RTF-bearing record published since 2026-09-12 declares
`run.rtfDefinition: "wall/audio"` (`scripts/benchmark_history.py validate` rejects a newer record
without it; `ui-perf` records carry no RTF and no declaration), and pre-cutover records never share a comparison key with a new one, so a promotion or release-QA
comparison against a pre-cutover `rtf` is not a like-for-like comparison. The README chart and its
alt text are generated by `scripts/generate_readme_charts.py` from the canonical records pooled
behind the newest one (`--check` fails on stale charts); update the website chart's medians and
provenance line in the same change.

## Known-cosmetic non-bugs (do not file)

- Post-retirement readiness note briefly shows "Preparing Built-in Voice" (§G residual; no connection
  is made and generation is unaffected).
- Enroll sheet: the first click on "Record…" immediately after typing in the Name field can be
  consumed by the field's focus-commit — a second click opens the sheet (observed v2.1.0 QA).
