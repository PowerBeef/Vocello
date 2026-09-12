---
status: active
owner: ios
summary: iOS physical-device testing — deterministic compile lanes, explicit on-device acceptance (smoke/benchmark/perf with the frame-health protocol), headless diagnostics, and burn-in safety.
sourceOfTruth:
  - scripts/ios_device.sh
  - scripts/ui_test.sh
  - scripts/ios_candidate_acceptance.py
  - scripts/ios_control_audit.py
  - config/ios-control-audit.json
  - scripts/check_ios_ui_perf.py
  - scripts/check_ios_model_management.py
  - scripts/voice_identity_language_reliability.py
  - config/voice-identity-language-reliability.json
---
# iOS physical-device testing

Vocello's iOS runtime and UI acceptance run on a paired physical iPhone. Simulator build, launch,
and UI automation are unsupported. XCUITest is the sole autonomous iOS app UI driver.

## Ordinary development

```sh
./scripts/check_project_inputs.sh
./scripts/build_foundation_targets.sh ios
```

The ordinary macOS deterministic lane executes the Foundation-level iOS policy assertions in
`VocelloCoreTests`. The generic physical-device SDK compile then builds both the app and a duplicate,
standalone `VocelloiOSLogicTests` policy bundle without executing that iOS bundle. Neither route
requires a connected phone, and together they are sufficient for routine commits, pushes, pull
requests, ordinary merges, and ordinary CI. Missing models, a phone, or UI results must not block
preserving and sharing development work.

### Host toolchain prerequisite

`generic/platform=iOS` does not launch or execute a Simulator. Current Xcode 26 toolchains still
require the selected Xcode installation to expose usable iOS Platform Support and a compatible iOS
runtime component before that physical-device SDK destination becomes eligible. An `iphoneos`
entry in `xcodebuild -showsdks` is not sufficient proof. Repository build routes run this read-only
check before package resolution or compilation:

```sh
python3 scripts/lib/ios_platform_preflight.py check
```

If it reports `blocked-toolchain-component`, install or enable the matching iOS component in
Xcode → Settings → Components. Apple also exposes the attended command
`xcodebuild -downloadPlatform iOS -architectureVariant arm64`. This can be a multi-gigabyte
operation, so repository scripts never invoke it automatically. Installing the component is a host
toolchain repair; it does not authorize Simulator builds, launches, tests, or UI automation. See
[Apple's additional Xcode components guide](https://developer.apple.com/documentation/xcode/downloading-and-installing-additional-xcode-components).

Those shared sources and assertions cover catalog and delivery-ledger validation, memory policy,
cancellation semantics, app-support path gating, and privacy-safe diagnostics. Xcode
26 reports tool-hosted testing as unavailable for physical-device destinations, so the repository
does not expose a device execution command for this target. Physical runtime assurance remains in
the existing headless diagnostics and genuine XCUITest lanes; no Simulator substitute is used.

## Device preparation

### Inspect a retained long-form transcript without regenerating

For the deterministic harbor smoke fixture, first resolve the exact test-owned History ID from
the retained run, then use the existing smoke runner's focused observation scenario:

```sh
scripts/ui_test.sh ios smoke --scenario history-transcript --history-row-id generation-N --retain-result
```

This opens that row through genuine History controls, attaches its complete transcript before
closing the player, clears the test search, returns to Studio and terminates the test session.
It neither generates audio nor deletes/pins History. The private attachment remains untracked;
`history-transcript-summary.json` contains only identities, digests and length. The collector rejects
missing, duplicate, malformed or cross-run attachments. Its result is **observed**, not full smoke,
audio-quality, restoration or candidate acceptance. The separate required-step workflow preserves
source identity, XCUITest status and crash collection without requiring a fabricated pressure event.
It is unavailable in preinstalled-candidate mode. Normal smoke remains unchanged.

The long-form acceptance fixture removes its final separator space before entry so exact joined
History comparisons use canonical input. Do not normalize the observed player value or ignore
missing words/punctuation. On mismatch, the shared verifier retains the actual value before dismissal;
keep the original failure and compare it with planner behavior before regenerating any output.

### Already installed distribution candidate

After separately authorized signing/upload and installation, use:

```sh
scripts/ui_test.sh ios smoke --preinstalled-candidate <verified-release-directory> --retain-result
```

This is a **black-box navigation route proof**, not the instrumented smoke suite or complete
processed-candidate acceptance. The helper validates command-bound iOS release evidence and requires
the exact clean source commit. CoreDevice must identify exactly one matching bundle/version/build
with `isBuiltByDeveloper == false`, before and after testing; unknown origin fails closed. This
binds the unique version/build to approved IPA evidence but does **not** claim to measure the
installed TestFlight binary's digest.

The standalone `VocelloiOSCandidateUI` scheme has no production-app dependency. Only its test runner
is built and installed. Xcode's documented `UseDestinationArtifacts` mode prevents installation
during `test-without-building`. Runner configuration rejects target-app build products and removes
all app launch arguments/overrides. It never pulls the distribution app's private data container.
The genuine tab and Settings-version journey retains screenshots and its candidate identity,
restores the original tab, terminates the app and returns Home. A missing/failed/duplicate test or
missing identity attachment fails the route. Collection of post-run identity, attachments and
system-crash deltas is attempted even after failure/interruption; new system reports require review.

Keep this evidence separate from instrumented engine receipts and the 201-take campaign. Full
downloads/generation/enrollment/long-form/permission/upgrade acceptance must still be performed on
the processed candidate. Do not uninstall or bypass onboarding here: fresh-install acceptance needs
verified recovery and immediate maintainer approval. Finish authorized device work with the screen
protection procedure below, not an implicit global Settings mutation.

### Development-device preflight

```sh
scripts/ios_device.sh preflight
scripts/ios_device.sh device-state
```

`preflight` and `device-state` verify the paired CoreDevice identity and reachability; preflight
also checks the selected Xcode's iOS Platform Support, signing, and the existing app-build and dSYM
readiness. Signing readiness means a currently valid **Apple Development certificate and its
private key** for the selected team—not merely a team environment value, an expired certificate,
or an Apple Distribution identity. The privacy-safe
`scripts/lib/ios_signing_identity.py` helper distinguishes expiration, a missing private key,
team mismatch, and a missing certificate before package resolution or compilation. Repair an
expired/missing identity in Xcode → Settings → Accounts → Manage Certificates; do not revoke or
regenerate unrelated distribution identities. `device-state` treats
reachability as its only blocker. The XCUITest runner independently rejects a phone that
CoreDevice reports as locked before invoking `xcodebuild`. Install or repair iOS models through the
visible Settings → Voice models section; neither device scripts nor normal UI tests install them.
The sole exception is the separately selected `scripts/ui_test.sh ios model-download` lifecycle
diagnostic, which uses an isolated app-support root and is never part of smoke or benchmark.

### Explicit screen protection after device work

When the maintainer authorizes Auto-Lock restoration, use the existing physical-device XCUITest
runner to inspect the real Settings route before unattended work, then enable the timer after
all device work and collection have ended:

```sh
scripts/ui_test.sh ios screen-protection --scenario inspect --retain-result
scripts/ui_test.sh ios screen-protection --scenario enable --retain-result
```

The default is read-only `inspect`. Only explicit `enable` chooses **3 minutes** and verifies the
persisted value on the parent Settings row. English and French Settings are supported, including
**Luminosité et affichage → Verrouillage automatique**; an unknown, restricted, or unavailable
control fails rather than claiming protection. No other setting or Vocello data is changed.
The test returns to Home; its retained `screen-protection.json` and screenshots distinguish
route inspection from a verified timer change. It never runs implicitly during another lane.
Auto-Lock readback is not proof the screen is already locked or that Always-On Display is off.
Confirm the eventual lock separately with the read-only CoreDevice `device info lockState`
command using the device identifier resolved by preflight and an untracked JSON output file.
Use the raw current `passcodeRequired` field; `unlockedSinceBoot` describes historical unlocking,
not whether the device is currently unlocked. The corrected probe derives `deviceLocked` only
from a typed current `passcodeRequired` value; missing or malformed values stay unknown. Older
probe outputs using historical unlock state are not protection evidence. Retain raw readbacks
privately. `scripts/ios_device.sh device-state` proves reachability, not lock state. Do not start
another device lane after final protection. If this route fails, stop unattended device work and
report that protection still requires operator action.

## Explicit XCUITest lanes

Shared `VocelloiOSUITestCase` journeys select English using process-local launch arguments so
exact model-status assertions do not depend on the phone's language. They first observe the saved
App Language choice through its genuine picker, temporarily select System Default, and restore
the original choice during session cleanup. They never write global `AppleLanguages` preferences.
The Settings `localization` walk explicitly overrides the process language for French-Default
(including translated title and variation-value assertions), in addition to Default, AX-L,
AX-XXXL and pseudo-AX-XXXL. Keep each layout's full-visibility assertions and retained captures;
neither a default-language pass nor a compile substitutes for bilingual device acceptance.

Smoke diagnostics are collected before the aggregate failure exit, including when XCTest fails.
A passing memory-pressure diagnostic subset cannot override a failed UI or long-form test.
If an older runner omitted collection, preserve its failed ledger and put any recovered telemetry
in a separate supplemental bundle with original run identity and digests; never rewrite the run
as PASS. The September 5 production-stanza fixtures cover failed XCTest, failed collection,
both failures, success, and non-smoke routes without rerunning device work.

Serialize macOS and iOS `xcodebuild` commands: the governed shared SwiftPM-store lock is held
throughout XCTest, not just build/package resolution. Concurrent native commands can time out
waiting for that lock. Run read-only analysis or Python fixtures alongside a device lane instead;
do not bypass the lock or clear a cache to resolve legitimate contention.

Index membership and derived-refresh ordering follow [development-workflow.md](development-workflow.md).

```sh
scripts/ui_test.sh ios smoke
scripts/ui_test.sh ios localization
scripts/ui_test.sh ios benchmark
# Filtered benchmark example:
scripts/ui_test.sh ios benchmark --modes custom --lengths short --warm 1 --label "focused"

# Source-bound exhaustive control and pairwise-generation audit:
scripts/ui_test.sh ios control-audit --scenario inventory --retain-result
scripts/ui_test.sh ios control-audit --scenario stateful --retain-result
scripts/ui_test.sh ios control-audit --scenario external --retain-result
scripts/ui_test.sh ios control-audit --scenario accessibility --retain-result
scripts/ui_test.sh ios control-audit --scenario generation --take-limit 5 --retain-result
scripts/ui_test.sh ios control-audit --scenario all --retain-result
scripts/ui_test.sh ios control-audit --scenario all --resume RUN_ID --retain-result

# UI-performance frame-health lane (ios-ui-2026-08):
scripts/ui_test.sh ios perf [--label RUN_ID]

# Explicit isolated background-transfer diagnostics, not a normal UI lane:
scripts/ui_test.sh ios model-download --scenario diagnose
scripts/ui_test.sh ios model-download --scenario queue
scripts/ui_test.sh ios model-download --scenario acceptance
scripts/ui_test.sh ios model-download --scenario soak --iterations 3
scripts/ui_test.sh ios model-download --scenario recover
```

The iPhone matrix keeps the shared short/medium/long ordering; its long script is the historical
150-character text from the era of the 150-character limit, kept fixed for benchmark-history
comparability (the shipping single-take limit is 900, memory-qualified 2026-07-24). macOS retains
the extended >220-character long corpus; the iPhone lane never bypasses the user-facing limit.

| Lane | Scope |
| --- | --- |
| Smoke | Two journeys. Standard: exact app launch, Studio mode and tab navigation, visible model and clone-reference readiness, one visible user cancellation, one run-scoped critical-memory cancellation with cancel-before-unload diagnostics, post-pressure engine reuse, no cancelled History rows, and one real completed Custom History row. Long-form: a >2,000-character script routes to a project, streams every segment with live narration, surfaces the joined output in the inline player, and History shows search-flattened rows plus the grouped project with its expandable per-segment map |
| Benchmark | Ordered, configurable Studio matrix with pulled telemetry, readable audio, audio QC, thermal and timing evidence; the default is exactly 29 takes |
| Control audit | Source-bound inventory, stateful, external-system, accessibility, and 201-row all-pairs generation scenarios. Schema-v3 plans speak the exact tracked corpus without ownership markers. Bounded read-only before/after History censuses must prove exactly one new persisted row, followed by exact full-player transcript verification before pin/delete. Versioned observations bind row ID, generation UUID, script digest, exact seed, and preserved cleanup baseline. Existing identical user text is never normalized away. Host validation preserves byte-exact v1/v2 historical plans, including original numeric stress failures. One verified History carrier per mode freezes the normally obtained seed; test-runner-only resume metadata identifies that exact row and requires visible seed agreement before pinning. Resume rejects changed source, build, device, plan, uncorrelated ownership, or zero observations. Final-plan cleanup removes only verified carriers and the plan-owned Clone fixture. Clone has no fabricated delivery dimension. Missing, blocked, infrastructure, harness, and product outcomes remain distinct; global destruction is cancelled, never counted as exercised. |
| Model delivery | Fixed test-owned root normalized through visible state-appropriate controls. `diagnose` covers Custom cancel/restart/process adoption/Ready/remove; `queue` proves independent active/queued cancellation; `acceptance` adds Design/Clone shared-component reuse and all-model removal; `soak` repeats the lifecycle; `recover` inspects and visibly clears retained failure state without starting a transfer. Every transfer records exact logical bytes, milestone row/bar screenshots, phase activity, action exclusivity, five-minute advancement bounds, correlated delivery events, and exact canonical-state preservation |
| Perf | Nine frame-health scenarios (`Tests/VocelloiOSUITests/VocelloiOSPerfUITests.swift`), each a fresh app launch with the in-app `CADisplayLink` probe pinned to the app's 60 Hz cap and one marked wall-clock window; `scripts/check_ios_ui_perf.py` joins windows to the pulled 500 ms probe rows |

The control-audit accessibility lane checks targets and `.textClipped` at Default, AX-L,
AX-XXXL, and pseudo-AX-XXXL, then runs the complete system audit without a forced size. The system
clipping audit can pass an ellipsized label whose accessibility name is complete. Inspect the
retained screenshots as well; automatic PASS alone does not establish untruncated visual reflow.

The stateful lane registers observed original toggle/variation values before mutation and awaits
its session cleanup through XCTest teardown, including after assertion aborts. Failed or skipped
restoration remains failure; never replace an unknown original value with a default. The inventory
and simple saved-voice enrollment journeys still need equivalent preservation of Studio selections,
draft and consent before use against personal state; do not infer that protection from the stateful
lane. See the current checkpoint for this explicit acceptance limitation.

Settings reveal uses the shared test-only `VocelloUISettingsReveal` helper. It preserves full
visibility and whole-dock clearance while issuing slow native touch swipes on small static-text
descendants of one genuine containing scroll view, not full-window swipes. Pointer-based
`scroll(byDeltaX:deltaY:)` is not supported on the touch-only iPhone. Missing/ambiguous containers,
an unsafe container center or no wholly visible small anchor fail closed. Each accessibility snapshot
determines the desired movement and bounds the anchor size; velocity is not a distance guarantee.
Direction reversal reduces the anchor bound, unchanged frames stop the search, and oversized full-visibility
requirements remain failures. The separate navigation-only band is not layout acceptance. Retained
pre-gesture and failure attachments include sampled frames and desired movement. Host geometry tests do not
prove actual UIKit scrolling; new physical AX-XXXL/pseudo acceptance is required after changes.

Every lane uses the paired physical-device destination. Tests use stable accessibility identifiers,
condition-based waits, XCTest activities, screenshots, and failure attachments. Coordinate tables,
OCR taps, alternate UI drivers, and fixed sleeps are not supported — the perf scenario file is the
one recorded exemption (`scripts/repo_invariants.sh`): its paced sleeps ARE the measured
workload, and its sweep gestures anchor on the application root so deep per-event accessibility
re-queries stay out of the measured windows.

The control-audit plan is generated before Xcode contacts the phone:

```sh
python3 scripts/ios_control_audit.py validate
python3 scripts/ios_control_audit.py generate-plan \
  --source-identity SOURCE_ID \
  --output /tmp/vocello-ios-control-plan.json
```

The raw plan, JSONL observations, `.xcresult`, screenshots, logs, device state, crash delta, and
cleanup proof stay untracked below the run artifact directory. The composer validates run and
source identity and assigns only the terminal vocabulary in
`config/ios-control-audit.json`. A required row without an observation becomes
`SKIPPED_AFTER_FAILURE`; permission or destructive work that cannot be restored becomes
`BLOCKED_PRESERVATION_POLICY`. Neither is a passing result. The campaign contract is `config/ios-control-audit.json`; the
[current checkpoint](../development-progress.md) routes to the primary roadmap.
Do not repeat completed phases merely for a green aggregate or reuse a token after source changes.
`--retain-result` pins the bundle before Xcode starts, including legacy-shaped metadata.

## Pause and resume

1. Set the phone deadline before starting; reserve at least 20 minutes for collection/restoration.
   The release-first campaign starts with five takes, then may use up to 20 per invocation only
   after correlation and preservation succeed, splitting at mode boundaries and deadlines.
2. Stop between terminal, fully collected shards. If interruption is necessary, stop only the
   exact owned process and preserve the failed/partial run; never convert it to PASS.
3. Verify diagnostics, crash delta, observations, artifact digests, cleanup/restoration, and
   test-owned app termination. Run `scripts/clean_build_caches.sh --prune-ui-results --dry-run`
   and confirm required runs are `explicitly-pinned`. Retire pins only after explicit closure.
4. **Frozen source:** record run IDs, source/build/device/plan identities, outcomes, remaining
   rows and the validated next command in the existing untracked run checkpoints. Do not edit
   the roadmap, this guide, AGENTS, or any tracked file between shards.
5. **Deliberate source checkpoint:** incorporate collected results into `config/roadmap.json`
   and the current narrative. A changed full-tree identity requires new acceptance identity;
   previous results remain history, never merged current-source PASS.
6. Before resume, use the runner's schema/identity/artifact validation. Never guess a cursor,
   retry a failed cell, replace a seed, or infer restoration from a green XCTest counter.
7. If authorized, finish with the screen-protection procedure and independent lock readback.
   No further device UI follows final protection.

The RF-07 runner defaults generation/all to **five takes per invocation**; `--take-limit 1..201`
sets an explicit bounded shard and `--resume` selects its source-bound start. The immutable plan
still contains all 201 rows. The summary separates `shard.result` from the campaign `result`, lists
`unscheduledTakeIDs`/`remainingTakeCount`, and preserves prior failures. A passing shard is never a
passing campaign; missing observations *inside* the scheduled range remain failures.

Observation schema v2 flushes each request-prepared, player-visible, terminal, and final-restoration
event immediately as a retained XCTest attachment, with a run-local contiguous sequence. Collection
rejects missing/corrupt bytes, mixed runs, duplicate/gapped sequences, and does not replace existing
output on failure. Nonterminal stages retain early identity but cannot manufacture a terminal PASS.
Legacy plan fields in each row describe the expectation; `observedSelections` separately records
selected UI IDs. `playerEvidence` requires Play/Pause transitions and a changed scrub position while
paused, so missing controls or natural playback advance cannot qualify as successful scrubbing.
Playback probes preserve a typed failure and the generation identity before further navigation;
their predicate timeout must not bypass restoration via XCTest's stop-on-failure exception.
XCTest teardown always ends the audit's app session, but session termination alone cannot supply
a missing restoration observation or qualify an interrupted shard. Failed playback outputs stay
retained; no unobserved History-row identity grants permission to delete them.
History text entry waits for the real field and keyboard before one replacement, then verifies its
value. No automatic test/generation retry is added. These source repairs require a physical pilot.
Runner PASS is written only after required-step finalization; failure exits also finalize the ledger.

Historical pilot failures, including missing warm/capture evidence, are in git
history. Never infer a PASS from an
optional ledger subtotal when mandatory correlation or artifact evidence fails.

New generation/all runs declare `controlEvidenceVersion: 2`. Their dedicated
`ui-ios-control-audit-generation` required-step workflow makes device correlation mandatory.
Correlation schema v2 overrides UI-only row PASS on missing or divergent evidence; missing
evidence is a harness failure, not a synthetic product defect. Warm coverage is evaluated across
the source-bound campaign chain: incomplete shards may leave it PENDING, but complete campaigns
must prove genuine warm receipts in every mode. Row order never establishes warm state.
Whole-output quality warnings remain explicit `passedWithWarnings` shard outcomes and cannot
authorize promotion or a clean complete campaign.

Each completed take requires real request/player/controls PNGs (CRC and raster checked) and the
published PCM WAV matching the engine's existing `samplingWAVDigest`. The diagnostics-only mirror
copies audio before run-owned History cleanup, never moves the accepted output, and bounds each
run to 201 files / 256 MiB, with a 64 MiB per-file ceiling. These private copies stay in the app's
purgeable Caches diagnostics root and the ignored, pinned host run bundle; capture failure fails
host qualification rather than synthesis. Retain failed/warning evidence for investigation.
Resume validates correlation/observation digests and all retained artifact bytes before selecting
the next row. Original schema-v1 reports remain historical evidence; do not upgrade or rewrite them.

For a time-limited phone window, set the stop deadline before launching a lane and reserve time
for its diagnostics and teardown. Do not launch work that cannot fit the remaining window.
Finish device collection and confirm test-owned app termination before releasing the phone;
documentation, deterministic checks, and publication can continue on the host afterward. If work
must be interrupted, stop only the exact owned process, preserve its failure/partial evidence,
and record the last terminal observation plus unattempted work. A passing XCTest counter alone
cannot authorize a passing lane or a resume token.

Lane qualification is deliberately stricter than the XCTest counter. The `ui_test.sh` terminal
status is authoritative because it also owns post-test diagnostics, crash deltas, artifact
composition, policy validators, and cleanup. If those required phases are stopped after all XCTest
cases pass, the `.xcresult` remains useful partial evidence but the lane remains failed and must be
rerun with a new ID. Never relabel the retained bundle or cite its test count as a complete PASS.

Generation resume state is schema-versioned and fail-closed. A failed take that already emitted a
terminal `PRODUCT_FAIL`, `HARNESS_FAIL`, or `INFRASTRUCTURE_FAIL` observation remains represented,
and the next run starts at the immediately following unattempted row. In legacy observation streams, if the process failed without
a terminal observation for its in-flight row, that row is recorded as `SKIPPED_AFTER_FAILURE` and
is not retried automatically. Version-2 state carries every such skip across multi-failure resume
chains; version-1 retained state remains readable. A gap that is neither observed nor explicitly
carried as a skip rejects the resume instead of silently losing matrix coverage.
New observation-v2 runs additionally require collected restoration and a terminal observation for
each staged take. An interrupted stage cannot be skipped by guessing: retain it for forensic
reconciliation. A clean, fully represented shard boundary never skips the next take merely because
later host finalization failed. Zero-observation and cross-source resumes remain forbidden.

A pre-observation failure has no row-level resume boundary. Schema-v3 ownership requires one new
persisted History row relative to the complete pre-generation census and an exact full-player
transcript match. Search text only narrows the list; identical preexisting user rows grant no
ownership. The optional observation block records before/after/final row IDs, transcript agreement,
and whether the row remains a seed carrier, alongside the genuine completed generation UUID.
Missing, duplicate, or inconsistent identities stop before mutation or seed adoption.
After a source correction, preserve the failed bundle and begin again at row 1 with a new frozen
identity. Generate that plan only after the final tracked commit, because documentation and contract
changes also change the full-tree identity.

A visible generation failure has only a production Retry action. The audit therefore records the
failed request and ends that XCUITest shard without pressing Retry; a separately invoked,
source-bound resume continues at the next row. The shard keeps its first successful run-owned
History row for each reached mode instead of deleting it. The host validates the exact prior
run/source/plan chain and telemetry correlation, including the ownership digest, before passing
carrier metadata to the test runner. The resumed launch locates that exact row ID, proves its full
transcript and recorded UInt64 seed, and invokes that row's visible Pin seed action before
continuing. The final shard removes every carrier, any plan-bound imported Clone fixture, and every
audit-owned seed pin. `pinOwnedByAudit` preserves seed pins that predated the campaign; resume
checks every carried row against its original run's correlation, not only the latest shard's report.
A failed or interrupted shard retains those bounded artifacts as forensic and
resume state; it never falls back to a new session seed or recreates the Clone identity silently.

Warm/cold lifecycle state is always taken from the engine request receipt. The first row per mode
is an enforced cold sentinel; ordinary rows declare their state as observed, and composition
requires at least one genuinely warm receipt per mode. Row order is not residency evidence because
visible UI setup can outlast the iPhone idle-unload policy. A fixed-seed request that publishes
audio but reaches the model token ceiling before EOS is a post-generation incomplete take: it must
be discarded, absent from History, and surfaced as `generation.incomplete`, never described as a
startup failure or silently retried.

An automation-session bootstrap timeout becomes a run-level `INFRASTRUCTURE_FAIL` only when the
retained `.xcresult` and log prove zero launched test cases and there are no app observations,
assertions, generation requests, crashes, or QC results. Every unexecuted control remains
`SKIPPED_AFTER_FAILURE`; a manual rerun receives a new run ID and cannot overwrite the first run.
After a test has launched, a separate classifier may report `infrastructure_external_interruption`
only when the retained log proves a SpringBoard notification banner and
`NotificationShortLookView`, the `.xcresult` proves exactly one identified wait timeout, and no
product, harness, crash, generation, or QC failure coexists. It never turns the run into PASS and
never authorizes an automatic retry. See the
[historical infrastructure findings](ios-control-audit-remediation-2026-08-29.md); their dated
runs do not qualify new source or guarantee Xcode bootstrap reliability.

### UI-performance lane (`ios perf`)

The probe writes `frames-<launchEpochMS>-<scenario>.jsonl` to the devicectl-pullable
`Library/Caches/Vocello/diagnostics/ui-perf/` tree; markers travel through the on-device test
runner's stdout into `xcodebuild.log`, so marker and probe share the device clock. The
`perf-validation` step pulls diagnostics and runs `scripts/check_ios_ui_perf.py`, which
fail-closes on a missing/duplicate scenario, probe coverage below 90% of a marked window,
non-monotonic blocks, and non-canonical hardware (run-scoped device manifest + live `devicectl`
inventory must resolve to the canonical iPhone profile). The 55–65 Hz median-block-cadence band
fail-closes on `ios-idle-baseline` only — the quiet sentinel where cadence isolates whether the
pinned 60 Hz link was honored (Low Power Mode, thermal caps, idle throttling); both Low Power
Mode off and nominal thermals are run preconditions. On interactive scenarios an out-of-band
cadence is recorded as a `uiperf.cadence:*` warning (`passedWithWarnings`), never a failure:
block cadence there conflates system re-pacing with the main-thread stalls the lane exists to
measure (the macOS history-scroll baseline of 456 ms/s hitch — ~33 Hz effective — is the
canonical example). Artifacts: `ui-perf-report.json` and `ui-perf-gate.txt` under the run
directory, probe JSONL under `diagnostics/ui-perf/`. **Copy
`ui-perf-report.json` out of the run directory after any counted baseline that did not use
`--retain-result`. For a multi-run campaign, prefer `--retain-result`: it preserves the complete
run bundle until the evidence set closes, while compact PASS history remains the durable tracked
record. Warn-only ceilings live in
`config/ui-perf-thresholds-ios.json` (IUI-6, derived from the three counted
sessions; a breach marks the scenario and run `passedWithWarnings`, never
failed), and on the canonical iPhone profile a PASS emits registry evidence
and publishes a platform-`ios` `ui-perf` record — the macOS UI-7 twin
([`ios-ui-refresh-2026-08.md`](ios-ui-refresh-2026-08.md)).

## Headless device diagnostics

`bench`, `lang-bench`, `speech-assets`, `profile`, `memory`, and the deliberate crash diagnostic launch
`IOSDeviceDiagnosticsRunner` through purpose-specific `QVOICE_IOS_*` environment contracts. `bench`
builds the app with `build --optimized` (`-O`, the shipped topology); every build writes a receipt
naming the app executable and its digest, and publication binds `toolchain.optimization` to that
receipt instead of a literal. While a headless take runs, the host copies only the run's completion
sentinel from the device every ten seconds and pulls the full diagnostics tree once it appears.
Generation lanes write `device-diagnostics-done.json`; `speech-assets` writes its distinct
`speech-assets-done.json` completion barrier. The runner never drives or inspects the app UI. Clone
diagnostics require the exact prepared voice ID, and `--memory-profile` can apply a
smaller-device memory budget while retaining the connected phone's real GPU and thermals. These
operations are diagnostics, not a second frontend acceptance stack.

`speech-assets` is an explicit, non-generation bootstrap for the language-output prerequisite. It
resolves `de_DE`, `es_419`, `ja_JP`, and `zh_CN` through
`DictationTranscriber.supportedLocale(equivalentTo:)`, creates one module per resolved locale,
checks each status, performs one combined AssetInventory download/install request, and then requires
every module to report installed. Its local sentinel also records a fresh
`SFSpeechRecognizer.supportsOnDeviceRecognition` read and Vocello's deterministic legacy locale
selection. Modern installation and legacy readiness are separate verdicts; the command publishes no
benchmark history and performs no generation.

`lang-bench` declares an immutable one-based run plan before generation and passes an explicit
UInt64 seed plus sampling variation to every take. Its schema-v2 sentinel is published last and
binds the resolved language, prompt-assembly digest, exact output-WAV digest/metadata, generation
telemetry identity, and structured three-pass on-device Speech evidence. The collector retains only
those plan-selected rows and files. Corpus v2 requires at least 15 normalized words for alphabetic
scripts and 24 normalized characters for Chinese/Japanese, freezes the Custom speaker and shared
Design instruction in the plan, and sends the known language explicitly for Design. Custom pinned/Auto
pairs share the exact fixture and prove language-hint equivalence rather than independent audio
quality; three transcription passes prove recognizer reproducibility rather than statistical
independence. `--diagnostic-cohort` runs the fixed 15-take English-Design and
French pinned/Auto regression cohort without retries or history publication. Language acceptance is
fully autonomous; listening is optional annotation only. Its primary accuracy metric is WER for
word-delimited languages and CER for Chinese/Japanese, both at the versioned 0.15 threshold; the
Python validator and publisher recompute the edit evidence from the corpus rather than trusting the
app's aggregate score.

## Model readiness

Before generation, XCUITest visibly requires Custom, Design, and Clone Speed to report ready,
Generate to be enabled, and the required clone voice to exist. iOS has no command-line model
ensure/install path: repair missing models in the visible Settings → Voice models section, then restart the
UI lane. Device scripts retain headless engine diagnostics, but normal acceptance never substitutes
a headless inventory for the visible Settings state.

When a device wipe removes the benchmark clone voice,
`scripts/ios_device.sh enroll-clone-fixture --wav A_warm_elderly_woman.wav --transcript A_warm_elderly_woman.txt`
re-enrolls it through the headless diagnostics runner. (The visible Files-import flow returned
2026-08-15 and has its own opt-in `scripts/ui_test.sh ios enroll-clone-fixture` UI lane; the
headless command remains the no-UI, hash-pinned wipe-recovery route.)
The command stages the exact WAV plus the mandatory `.txt` transcript sidecar (from the macOS
fixture store `~/Library/Application Support/QwenVoice-Debug/voices/`) into the app's Documents,
launches with `QVOICE_IOS_DEVICE_ENROLL_VOICE_NAME`, and validates the enrollment sentinel
(staged digests, voice ID, quality warnings). The runner deletes the staged inputs after a clean
enrollment. The command is opt-in and never runs in smoke, benchmark, CI, or release.

Clone identity, enrollment-transcription, and French Voice Design reliability use a separate
source-bound diagnostic that extends the same headless runner. It is read-only with respect to the
saved-voice catalog: the untracked private map resolves the two stable aliases to exact existing
saved-voice IDs, while the tracked plan and retained reports contain aliases only.

When a previous VLR summary already binds both aliases to their reference-audio digests, recover
the map without enumerating or copying unrelated saved voices. The export matches those exact
digests inside the diagnostics-only app, copies only the two matching WAV/transcript pairs into an
untracked host directory, validates the copied bytes, writes `private-map.json`, and removes the
temporary device-side export after collection:

```sh
scripts/ios_device.sh voice-reliability-export \
  --plan /private/tmp/vlr-device-plan.json \
  --evidence build/artifacts/ios/voice-reliability/<prior-run>/voice-reliability-summary.json \
  --output /private/tmp/vlr-private-export
```

This route never exports by voice name or copies the whole App Group. A missing or ambiguous digest
fails closed and leaves the bounded diagnostic export available for forensic recovery.

```sh
python3 scripts/voice_identity_language_reliability.py device-plan \
  --run-id <new-run-id> \
  --profile closure \
  --output /private/tmp/vlr-device-plan.json
python3 scripts/voice_identity_language_reliability.py validate-device-plan \
  --plan /private/tmp/vlr-device-plan.json \
  --private-map /private/tmp/vlr-private-map.json
scripts/ios_device.sh voice-reliability \
  --plan /private/tmp/vlr-device-plan.json \
  --private-map /private/tmp/vlr-private-map.json
# Resume the exact same plan after interruption without repeating any launched row:
scripts/ios_device.sh voice-reliability \
  --plan /private/tmp/vlr-device-plan.json \
  --private-map /private/tmp/vlr-private-map.json \
  --resume
```

The private map is schema 1, binds the plan digest, and contains exactly
`user-reference-a` and `user-reference-b` mapped to their existing saved IDs. Never place voice
names, IDs, transcripts, or paths in a tracked file or task log. The command first runs the genuine
on-device enrollment transcriber against each stored reference without writing its result back; it
retains only typed authorization, locale-attempt, availability, on-device-support, confidence, and
digest evidence. The production `closure` profile executes exactly 14 no-retry current-fp16 rows:
eight Clone target-language ownership cells and six French Design Auto/explicit ×
short/medium/long current-Neutral controls. The 26-row `focused` profile retains the no-delivery and
Calm experimental arms for diagnosis; it is not the production closure gate. Every terminal
sentinel must expose a schema-2 actor-owned receipt, exact tokenizer,
target-text and instruction identities, mandatory QC, and locale-locked output verification. A
failed schema-3 row additionally retains the actor receipt, complete QC, run-scoped rejected-audio
and codec-trace identities, and incremental/full decoder replay. The host report assigns one root
failure and records missing evidence separately.

These device plans are not the 734-row Mac/CLI tokenizer/reference matrix and cannot prove an
fp16/fp32 cause. Run the production `closure` profile only after Mac/CLI localization, twice with
distinct run IDs for VLR-07.
It installs no models, edits no transcript or reference metadata, creates no History row, and never
retries or substitutes a failed seed. Missing Speech assets, missing model readiness, absent private
references, source drift, or an unverifiable output are explicit failures rather than skipped proof.

For causal localization before closure, generate the bounded eight-seed profile with
`--profile characterization`. It contains 122 current-fp16 rows: 38 Clone cells across both private
aliases, English/French scripts, Auto core seeds, explicit parity, and Expressive sentinels; plus 84
French Design cells across short/medium/long, Neutral/no-delivery/Calm, Auto core seeds, explicit
parity, and Expressive sentinels. It remains below the 128-take runner bound. The append-only launch
ledger prevents `--resume` from retrying either a terminal failure or a prior launch that exited
without a sentinel. A new run ID is required to repeat evidence.

## Deterministic evidence retained

The benchmark result is joined with exact device/app identity, current-run engine and app telemetry,
History/database correlation, readable WAV validation, audio QC, crash deltas, thermal state,
matrix ordering, and take counts. The app mints the generation UUID across Custom, Design, and Clone
and writes its frontend row durably before only the matching run rows/verbose sidecars are mirrored.
The fixed 150-character case remains explicitly `long`; no prompt-length inference is used.
Smoke asserts visible active-cancellation recovery, absence of a cancelled History row, subsequent
completion and History persistence, plus the runner's device/crash checks. It does not claim the
benchmark's per-take telemetry matrix or synthesize an operating-system pressure event. Headless `bench`, `lang-bench`, `profile`,
`crashes`, logs, and console operations remain supported physical-device diagnostics.

Profile commands launch or attach to the exact target PID, record CPU Profiler and `os_signpost`
rows in one trace, require a successful tracer exit, and verify the trace using exported
table-of-contents data plus non-empty performance-row and correlated-signpost exports. Traces remain local; a successful profile
publishes only its digest, capture settings, CPU/data-row summary, and sanitized artifact reference as
an `instrument-profile` record. CoreDevice and Instruments use different runtime identifiers for the
same phone; the profile lane resolves the Instruments UDID from CoreDevice JSON and fails before
installing or launching the app unless `xcrun xctrace list devices` reports that phone in its online
`Devices` section. Tracer startup is bounded by xctrace's own `Starting recording` output rather than
the unreliable physical-device Darwin-notification callback. Any target suspended by a later failure
is terminated automatically.

For allocation and VM evidence, use the Instruments memory profile:

```sh
scripts/ios_device.sh profile --kind memory custom:speed:

# Retain the raw trace only when it must be reopened in Instruments.
scripts/ios_device.sh profile --kind memory --keep-trace custom:speed:
```

This keeps CPU Profiler and correlated `os_signpost` data while adding Allocations and VM Tracker in
the same exact-PID trace, and forces verbose run-scoped samples. New publishable device runs require
telemetry schema v8 and evidence manifest v2: exact start/periodic/boundary/stop sidecars, summary
agreement, zero capture failures, and at least 95% sampler coverage. Critical pressure, an app memory
warning/exit, `hardTrim`, or `fullUnload` fails publication; guarded pressure, `softTrim`, or 95–<100%
coverage is explicit warning evidence. The record retains footprint/resident start, end, delta, and
peak; compressed/GPU peaks; minimum headroom and peak process-budget utilization; sampler coverage;
and pressure/trim/warning/exit counters. iPhone admission is also strict: physical footprint ≥5.2
GB, minimum headroom <384 MB, or Metal working-set ratio ≥0.8 fails; footprint ≥4.5 GB or
headroom <768 MB warns. The lane requires 15 GiB free before device launch. After validation and
history publication, the raw trace is discarded by default while its digest/settings/extracted
summary and retention status remain in compact evidence; `--keep-trace` opts into local retention.
Raw traces and sample rows remain untracked.

Device builds require 10 GiB of host free space before compilation. Language, generation benchmark,
memory, clone-conditioning, and gate lanes require 15 GiB; UI smoke, benchmark, and isolated model
download require 12, 15, and 18 GiB respectively. These host-side checks run before adding another
cache/result tree and do not contact, pair, or alter the phone. The exact-PID profile lane retains
its separate tracer-stage 5/15 GiB CPU/memory check. Because every profile rebuilds the exact app,
the full CPU-profile command is also subject to the 10 GiB device-build floor; memory remains
15 GiB.

Retained-memory qualification is separate from Instruments:

```sh
scripts/ios_device.sh memory --voice-id <exact-prepared-saved-voice-id> --label retained-check
```

One persistent app/engine process executes three medium Speed takes for Custom, then Design, then
Clone (nine total). The terminal sentinel is written only after all output/QC/telemetry proofs pass.
Policy `retained-memory-v1` compares first-to-last retained-take footprint growth within each mode and allows
at most 5% of physical RAM; cross-mode residency is diagnostic because different models are
intentionally loaded. A PASS creates `memory-qualification`, while any generation, memory,
retention, output, or crash failure leaves tracked history unchanged.

### Clone-conditioning semantic acceptance

```sh
scripts/ios_device.sh clone-conditioning --label focused-clone-proof
```

This compile-gated physical-device lane runs exactly two Clone Speed generations in one app/engine
process. It verifies the canonical saved Voice Design reference and transcript digests, then uses an
exact purpose-owned copy without a `.txt` sidecar or prepared voice ID for the x-vector-only take.
Both takes must pass typed conditioning flags, distinct prompt identities, strict output/ASR,
telemetry-v8 memory coverage, app/engine correlation, crash delta, and interruption checks. The
runner removes the audio-only scratch copy before PASS. It writes only local untracked validation
evidence and never creates or repairs benchmark history; XCUITest remains the visible UI proof.

MetricKit supplies a complementary delayed field view, not per-take benchmark attribution. After a
normal explicit pull, summarize only the already-local privacy-reduced aggregate with:

```sh
scripts/ios_device.sh memory-field-report build/artifacts/diagnostics/ios
```

The command never resolves, wakes, pulls from, or otherwise contacts an iPhone. MetricKit delivery
may take a day or longer; no payload reports `notYetDelivered` with success status and cannot qualify
or retroactively fail a benchmark run.

The validator atomically writes an untracked `benchmark-evidence.json` with the exact ordered
generation IDs/cells and verdicts. A PASS publishes one privacy-safe record under
`benchmarks/runs/ui-generation/` and regenerates `benchmarks/HISTORY.md`. Raw pulled JSONL, WAVs,
screenshots, traces, and `.xcresult` stay untracked; publication never stages, commits, or pushes.

Physical-iPhone acceptance of telemetry v8/evidence v2 is complete for the clean canonical
[29-take UI matrix](../../benchmarks/runs/ui-generation/ios-xcui-benchmark-20260716-184106-48e3a3a6.json),
[retained-memory qualification](../../benchmarks/runs/memory-qualification/ios-memory-qualification-20260714-112536-32554d95.json),
and the exact-PID [memory profile](../../benchmarks/runs/instrument-profile/ios-memory-profile-20260714-112759-9a573224.json).
Each record proves only its exact source, toolchain, model, and hardware identities; repository
contract tests and Simulator results never substitute for fresh physical-device evidence after a
relevant change.

## Generated-output ownership

Physical-device development and UI lanes reuse only `build/cache/xcode/ios-device/`; Xcode package
checkouts are shared under `build/cache/xcode/source-packages/`. Pulled diagnostics, UI results,
profiles, gates, and current UUID-matched symbols live under `build/artifacts/`, never inside the
incremental cache. Archive/export products live only under `build/dist/ios/`. Local release
DerivedData is isolated under `build/scratch/derived-data/release-ios/`; CI uses its
own `build/scratch/derived-data/ci/ios-archive/` leaf. See the authoritative owner/lifetime table in
[`privacy-storage.md`](privacy-storage.md).

## Release boundary

An iOS archive/TestFlight candidate uses deterministic signing, entitlement, catalog, archive, and
artifact checks. Physical-device smoke and benchmark results are independent frontend QA artifacts
and never an archive, upload, or Git-publishing prerequisite.

See also [`testing-runbook.md`](testing-runbook.md) and
[`benchmarking-procedure.md`](benchmarking-procedure.md).

## Historical checkpoint references

Dated run logs, through the 2026-09-02 control-audit continuation, live in git history. They are
evidence, not the next commands to execute.
