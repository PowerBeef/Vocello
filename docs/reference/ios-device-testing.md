---
status: active
owner: ios
summary: iOS physical-device testing — deterministic compile lanes, explicit on-device acceptance (smoke/benchmark/perf with the frame-health protocol), headless diagnostics, and burn-in safety.
sourceOfTruth:
  - scripts/ios_device.sh
  - scripts/ui_test.sh
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

The ordinary macOS deterministic lane executes the 19 Foundation-level iOS policy assertions in
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

Stage newly created owned source/test files before the final derived refresh: project-health
counts Git-tracked files. Refresh and stage the resulting summary before the exact-content commit
gate, so adding a new file does not invalidate a previously checked inventory.

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

Every lane uses the paired physical-device destination. Tests use stable accessibility identifiers,
condition-based waits, XCTest activities, screenshots, and failure attachments. Coordinate tables,
OCR taps, alternate UI drivers, and fixed sleeps are not supported — the perf scenario file is the
one recorded exemption (`scripts/check_test_workflows.sh`): its paced sleeps ARE the measured
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
`BLOCKED_PRESERVATION_POLICY`. Neither is a passing result. The complete multi-lane campaign
contract and current post-performance pause checkpoint are recorded in
[`ios-on-device-control-audit-2026-08-28.md`](ios-on-device-control-audit-2026-08-28.md). That
report lists the authoritative passing runs, source/device findings, blocked coverage, and exact
safe-resume boundary. Do not repeat completed phases merely to obtain a green aggregate, and do not
use an old resume token after a source fix changes the frozen identity. `--retain-result` writes an
untracked pin before Xcode starts, so every required multi-run member survives normal latest-pass
pruning even if its metadata is legacy-shaped. Before releasing the phone, record exact run IDs,
terminal outcomes, remaining rows, and the next valid command in the roadmap and development
checkpoint; then confirm each pin reports `explicitly-pinned` in a cleanup dry-run. Remove pins only
when the evidence set is explicitly retired.

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

The [later September 5 pilot checkpoint](../development-progress.md#september-5-later-physical-pilot--resume-checkpoint)
records an unresolved exception in the current runner: device correlation fails on missing warm
coverage while its required-step entry is optional and the UI-only summary says the shard passed.
Use `run.json` plus the correlation and all underlying observations, never the ledger subtotal alone.
That failed run cannot resume. Its generation evidence labels have no corresponding PNGs; do not
claim screenshot acceptance from the structured player observations. RF-07/AV-09 own the bounded
correction; the warm cohort and promotion treatment of cadence warnings remain required.

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
never authorizes an automatic retry. Retained pre-test run
`ios-xcui-control-audit-20260829-152245-bbe90762` was replayed on 2026-09-02 as exactly one
run-level `INFRASTRUCTURE_FAIL` plus 42 `SKIPPED_AFTER_FAILURE` rows, with zero product/harness rows;
the 2026-08-29 Messenger-interrupted run is the distinct post-launch proof. Fresh no-retry smoke
`ios-xcui-smoke-20260903-184747-dc032d1b` subsequently launched all three tests and passed its full
ledger, closing ICA-09's remaining bootstrap observation. This does not guarantee that Xcode
bootstrap cannot fail again or reclassify any original failure.
See [`ios-control-audit-remediation-2026-08-29.md`](ios-control-audit-remediation-2026-08-29.md).

### Control-audit continuation — 2026-09-03

Preflight passed on the paired iPhone. Saved-voice run
`ios-xcui-saved-voice-lifecycle-20260903-162036-6f4e3996` and generation run
`ios-xcui-control-audit-20260903-162348-77a58a4e` each stopped before any test case launched with
the Xcode automation-mode bootstrap timeout. Preserve both bundles independently: they are
infrastructure evidence, contain no product observation, and never authorize an automatic retry or
a merged PASS.

After the maintainer manually unlocked the phone, distinct saved-voice run
`ios-xcui-saved-voice-lifecycle-20260903-162649-37ad8335` launched normally. It used the real Voices
search field to reveal `ICI Direct Clone Import`, proved the semantic row/menu was hittable, and
completed its visible delete confirmation. The run then stopped when the cleared search field left
the software keyboard covering the root tab dock, preventing `rootTab_settings` from becoming
hittable. This is a harness cleanup failure after the original row-menu boundary, not a product
voice-lifecycle failure.

Any XCUITest journey leaving an active search surface for the floating root dock must dismiss the
keyboard semantically and condition-poll for keyboard absence before selecting a tab. The shared
helper now submits the genuine search field and enforces that condition. Fresh no-retry run
`ios-xcui-saved-voice-lifecycle-20260903-164233-e71568b3` subsequently passed the complete import,
automatic transcription, enrollment, Clone selection/generation, preview, deletion, draft cleanup,
and runner-diagnostics journey. ICA-13 is closed.

Fresh generation run `ios-xcui-control-audit-20260903-164806-affcc06a` completed two visible Custom
takes, then stopped at the identity guard because a long exact script cannot equal the History
row's intentional 60-character preview. No History mutation followed the mismatch, no terminal
observation stream was retained, and the run cannot resume after the source correction. The guard
now opens each narrowed row's genuine read-only player and requires its full accessible transcript
to equal the frozen plan before cleanup, pinning, restoration, or deletion.

Corrected-source generation `ios-xcui-control-audit-20260903-172247-b8fc963e` then emitted four
`PASS` observations and one independently diagnosed `PRODUCT_FAIL` at `custom-005`, leaving 199
composed rows skipped. Full-transcript ownership passed through the long scripts, closing ICA-14;
the Eric/Calm Strong/Italian sampled-output failure belongs to ICA-15. Two separate four-cell
diagnostics (`174346` and `180139`) preserve its warm/cold and streaming/non-streaming failures,
codec replay, exact seed, healthy memory, and absence from History. Do not silently retry that row.

Final smoke `ios-xcui-smoke-20260903-184747-dc032d1b` passed all three tests and its entire runner
ledger. Crash delta and scoped diagnostics completed at 19:02:42/19:02:44 UTC, before the phone
deadline; teardown terminated Vocello. The host-only retention phase also passed. The earlier
`181935` run remains failed/unqualified after its whole-mirror collection was stopped. ICA-16 is
closed by the fresh run, not by relabelling the older test-only success. All named bundles remain
explicitly pinned; do not repeat accepted smoke or saved-voice phases solely to obtain green counts.

The probe prepared at that pause is retained in the ignored directory below. It was executed on
September 4; these commands are historical reproduction instructions, not an outstanding run:

```sh
scripts/ios_device.sh preflight
scripts/ios_device.sh delivery-reliability \
  --plan build/artifacts/diagnostics/ios/startup-reliability/ica15-marker-ablation-pending/plan.json \
  --script-file build/artifacts/diagnostics/ios/startup-reliability/ica15-marker-ablation-pending/script.txt
```

This independent two-take diagnostic removes the spoken numeric History marker while holding
the failing speaker, preset, language, variation, and seed fixed. The host revalidates exact script
bytes before launch. The initial two takes and a separate reverse-order confirmation all pass
on-device QC, with identical per-mode cold/warm codec traces. The initial host runner remains
failed because of ICA-17's now-corrected optional cadence-quantile mismatch; its retained bytes
validate after correction. Run `ios-startup-reliability-20260904-054340-c307ab41` independently
passes the entire runner, crash collection, and cleanup. See the active remediation report for
exact observations. These probes cannot replace the failed original-text row or qualify a
production change by themselves.
The current-build marker control `ios-startup-reliability-20260904-054601-0770b988` reproduces both
historical codec digests and QC rejections; its complete runner reports `diagnosed_failure` and
cleans up successfully. All six new takes remain represented. Next separate ordinary audit History
identity from spoken text, keeping the exact numeric failures as independent stress cases; do not
strip digits from product input or silently replace a failed matrix row.
After localization and any qualifying remediation, freeze the final committed source and use
`scripts/ui_test.sh ios control-audit --scenario generation --retain-result` from row 1 on a new
schema-v3 plan. No September 2/3 shard may resume across this checkpoint's source change.
ICA-04/ICA-05 retain generation, final restoration/reporting, and preservation-blocked coverage;
ICA-06 still needs its exact-seed confirmation. VLR-07 retains its separate accuracy/ASR closure.

Diagnostic plan preparation must preserve UInt64 seeds exactly. Do not round-trip them through
JavaScript Number or another floating-point JSON parser. Compare with the retained exact integer
using integer-preserving tooling before launch, then verify receipt parity. Optional Swift Codable
fields may be absent when nil: cadence median/p90 remain optional in result-v2 validation, while
all required fields, numeric types, and unknown-key rejection remain enforced. A corrected validator
may recheck retained immutable evidence but never rewrite the original runner outcome.

### Control-audit one-hour continuation — 2026-09-02

The next one-hour device window ran on source identity
`ee2e7d4e245bd8d95b47fa0cc0064783fd9d4be7edc5ef8211728d017d45996e`. Preflight passed and
inventory run `ios-xcui-control-audit-20260902-180938-42d76c39` completed with 41 `PASS`, one
explicit `NOT_APPLICABLE`, zero failures, and zero skipped rows. It supersedes the earlier
zero-observation inventory attempt for active coverage purposes without rewriting that historical
bundle.

Two short journeys then exposed harness/reachability gaps. Saved-voice run
`ios-xcui-saved-voice-lifecycle-20260902-181739-713b7367` found the run-owned imported voice but
could not activate `voicesRowMenu_ICI Direct Clone Import`: its accessibility frame produced no
valid activation or suggested hit point. Generation run
`ios-xcui-control-audit-20260902-181849-9ea76d5a` stopped at its intended History-integrity guard
because reserved token `28400003` matched a non-audit History row. No generation observation was
written, all 204 composed rows remain `SKIPPED_AFTER_FAILURE`, and no row-level resume state exists.
Neither failure is product-generation evidence, and neither authorizes an automatic retry. The
phone-independent remediation now reveals the exact run-owned voice through the genuine Voices
search field and requires the row/menu to be enabled, hittable, finite, and at least 44 by 44 points
before activation. It also replaces fixed sequential tokens for new plans with schema-v2
source-bound tokens and requires the exact full script/row identifier before every History action.
Focused fixtures and generic iOS compilation pass; physical closure remains outstanding.

Smoke run `ios-xcui-smoke-20260902-182906-25dc08ce` passed all three XCTest cases, including the
primary cancellation/memory-recovery/Custom-History journey, the Settings accessibility layout
walk, and the long-form project journey. The one-hour deadline arrived during the later diagnostics
pull. That pull was cancelled, so the overall runner remains failed and the XCTest-only result is
not a qualified smoke PASS. At the deadline, all test processes were stopped and the four run
bundles remained explicitly pinned.

Committing this checkpoint changes the full-tree identity. The next phone window must not resume
`181849`. Generate a fresh schema-v2 plan after the final commit, then use new run IDs:

```sh
scripts/ios_device.sh preflight
scripts/ui_test.sh ios saved-voice-lifecycle --retain-result
scripts/ui_test.sh ios control-audit --scenario generation --retain-result
scripts/ui_test.sh ios smoke --retain-result
```

The generation campaign starts at row 1. Preserve the historical silent-gap findings, do not merge
source identities, and complete cleanup/restoration only from the final source-bound shard.

### Earlier control-audit pause boundary — 2026-09-02

The latest generation shard, `ios-xcui-control-audit-20260902-153340-9092ff5d`, was stopped at the
maintainer's request while the test was capturing initial Studio state. It emitted zero control
observations and began no generation row. The retained summary consequently carries all 204
composed controls/takes as `SKIPPED_AFTER_FAILURE`; that is an honest incomplete-run result, not a
product, harness, or infrastructure classification. The `.xcresult`, log, plan, summary, crash
delta, attachment manifest, exact rerun command, and explicit retention pin remain in the untracked
run bundle. Xcode and XCUITest were confirmed stopped after collection.

There is no row-level resume state to consume from that empty shard. Moreover, recording this
checkpoint changes the full-tree source identity. At the next device window, run preflight and
start a new frozen generation campaign from row 1:

```sh
scripts/ios_device.sh preflight
scripts/ui_test.sh ios control-audit --scenario generation --retain-result
```

Do not pass `--resume` with the `153340` run ID and do not merge its empty summary with earlier
source identities. The September 2 shards remain forensic inputs: `141800` passed three rows and
then rejected the German Calm/strong row for a 2.085-second interior gap; `151248` passed one row
and rejected the Chinese Angry/normal row for a 25.446-second interior gap. Both rejections were
product-output audio-QC safety outcomes with no History publication, automatic retry, or seed
substitution; one observation per cell is not a repeatability claim. Runs between them drove three
harness corrections; the phone-call-affected
mode-setup run remains non-product evidence. `config/roadmap.json` is the current status authority.

The earlier September 2 phases remain independently useful but do not form a single-source final
campaign. Stateful `121158` completed with explicit prerequisite/preservation limitations,
external `121608` completed with the permission-preservation block, and accessibility `121855`
passed. Isolated model diagnose `122641`, queue `123230`, and acceptance `123603` passed with no
finding. Inventory `120801` stopped with zero observations after the voice picker did not dismiss;
saved-voice lifecycle `122245` reached its preview action but never observed the player sheet. Those
two incomplete journeys require ownership diagnosis and fresh evidence. The cleanup dry run reports
every named bundle as `explicitly-pinned`; no raw evidence needs to be moved or rewritten.

The model-delivery runner always exports the `.xcresult`, attachments, diagnostics journal,
delivery summaries, ledger copy, sanitized storage inventories, crash delta, and host diagnosis even
when XCTest fails. Determinate bar observations include raw and total bytes, expected and
accessibility fractions, visible copy, status, phase, action set, frames, and screenshot names.
The SwiftUI progress rail disables inherited animation so a captured frame represents the same
exact durable-byte fraction exposed through accessibility. An unchanged integer accessibility
percentage is not a freeze unless exact progress advances by at least one percentage point; tiny
byte changes below the rounded display resolution remain valid. Rendered-width error, monotonicity,
leading-edge anchoring, geometry, and 3:1 contrast checks remain fail-closed.
The 95% visual checkpoint is an honest late-transfer band: the first exact incomplete sample from
90% through under 100% is used because durable catalog-byte progress can jump directly from 94% to
complete. Crossed milestones share one immutable UI sample and screenshot, preventing Ready or
finalization from removing controls while the evidence is being serialized. A completed diagnostic
that isolates a defect is retained and labelled `diagnosedFailure`; only a clean diagnosis counts
toward MD-3 closure. After the August 29 animation correction, consecutive diagnoses
`ios-xcui-model-download-20260829-181500-8b1428c9` and
`ios-xcui-model-download-20260829-182031-207e8a83` plus acceptance
`ios-xcui-model-download-20260829-182534-91d70526` re-closed the gate. The acceptance run installed,
adopted after relaunch, reused shared components, and visibly removed all three models with no
finding; its 15 visual samples stayed within 1.06 percentage points and above 8.80:1 contrast. This
procedure remains the fail-closed regression protocol.
`scripts/check_ios_model_management.py` identifies the first inconsistent layer and emits a timeline,
machine-readable diagnosis/summary, visual measurements, and a milestone contact sheet. A failed
isolated root remains available to the next `diagnose` or `recover` run; ordinary app data and
canonical model state are never used as the test root.

The smoke runner pulls only `Library/Caches/Vocello/diagnostics/<run-id>` through the shared
60-second bounded collector; it never copies the complete historical mirror. Copy failure remains
fatal even when XCTest passed, and a separate later inspection cannot rewrite that failed run.
The unchanged acceptance checker fails unless the one-shot event sequence is
`debug_force_critical_once` → `critical_memory_action` → typed `memory_pressure` cancellation →
`fullUnload`, followed by a successful generation from the same relaunched app process.

Benchmark accepts `--modes`, `--lengths`, `--warm`, and `--label`. Filters are explicit diagnostic
runs; invoking the command without filters is the canonical 29-take matrix on the tracked iPhone 17
Pro `iPhone18,1` profile. Dirty-source successes are exploratory even on that hardware.

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
`IOSDeviceDiagnosticsRunner` through purpose-specific `QVOICE_IOS_*` environment contracts.
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

### Retained pause boundary — 2026-08-31

Characterization run `vlr-device-20260831-characterization-04` is intentionally incomplete and
immutable. It is bound to plan digest
`c1c0593ee49ee39dedff156dfb47a97282edbc08f431927631373c7b0c5eecfb` and retained terminal
sentinels for takes 1–114: 98 PASS, three product QC failures, and 13 locale-verification failures.
Take 115 is a ledgered, sentinel-less interruption; takes 116–122 were not launched. Its untracked
artifact root contains `device-plan.json`, `launch-ledger.jsonl`,
`voice-reliability-partial-summary.json`, and `pause-checkpoint.json`, plus per-take evidence.

Do not use `--resume` for that run after the 2026-08-31 tracked checkpoint: committing changes the
full-tree source identity, and cross-source resume correctly fails closed. Do not delete, overwrite,
or rename the retained artifact root, and do not convert its missing rows into PASS. At the next
phone window, create a new plan and private map with a new run ID against the then-current source and
run the complete characterization. The old 114 terminal rows remain valid historical
characterization; they cannot be merged with the new run to satisfy a complete-run gate.

### Corrected-source resume boundary — 2026-09-01

Run `vlr-device-20260901-characterization-01` is a separate complete 122-row characterization
bound to plan digest `3926f6c1383d24f9268aa056017f49400d3b16f0c4383815aac59fe096c75d53`
and source identity `ed3b9febae572683d295c9d5aebecaaa18838f2d66e230fe2d4e139e3c17c656`.
It retained 103 PASS rows, three mandatory product-QC failures, and 16 successful-generation
locale-verification failures. Keep that run and the August 31 partial run immutable and distinct.

Replay subsequently disproved the first VLR-08 hypothesis: incremental and full decoding reproduce
the delayed onset, so the allocator-cache workaround was reverted. The corrected source instead
uses a bounded Clone-only leading-edge gate that preserves 80 ms of pre-roll and never edits an
interior pause. VLR-09 Fast-QC v6 adds bounded terminal-silence evidence and rejects an egregious
open tail without changing interior-pause thresholds. The completed Mac/CLI matrix and targeted
three-cohort proof are pinned in the VLR Mac report. The phone has not run this corrected source, so
neither fix has physical-device acceptance.

At the next phone window, first run `scripts/ios_device.sh preflight`. Generate new closure and
characterization plans/private maps from the exact committed tree; do not resume either historical
run. VLR-07 requires two distinct clean 14-row closure runs and one complete characterization. A failure
remains terminal and gets no automatic retry, seed substitution, or cross-run merge.

### Storage-policy startup interruption — 2026-09-02

Preflight passed with the paired phone unlocked, but the first attempted corrected-source private
export never wrote its terminal sentinel and launched zero generation rows. The visible app failed
during initialization because recursive storage-policy metadata could not be saved on the
read-only `speech_tokenizer/model.safetensors` hard link. Preserve the failed export attempt and
its empty source-bound plan as infrastructure/product-startup evidence; it is not a VLR closure
run and must not be resumed, relabelled, or counted.

The source correction preserves shared-component immutability by temporarily adding only owner
write access while applying data-protection/backup metadata, then restoring the exact prior mode
on both success and failure. After its deterministic checkpoint and commit, generate entirely new
run IDs, plans, and private maps for both 14-row closure passes and the 122-row characterization.

F-01/ICI-4 saved-voice and direct Clone-import acceptance is separately opt-in:

```sh
scripts/ui_test.sh ios saved-voice-lifecycle
```

Before running it, stage `ICI Direct Clone Import.wav` **without** a matching `.txt` sidecar in the
app's Documents directory. The XCUITest uses only visible production controls: Studio Clone opens
`referenceClip_importAudioFile`, Files selects the staged WAV, the enrollment sheet exposes
`saveVoice_transcriptionStatus`, on-device recognition supplies a nonempty editable transcript,
and Save resolves any genuine soft warning. The test then proves the exact voice is selected in
`studioChip_reference`, completes one Clone take, previews the durable Saved Voice, confirms the
exact named deletion, verifies the row disappears, and verifies the matching Studio draft is
cleared. When the run-owned row is outside the lazy viewport, the test uses the genuine Voices
search field to reveal its exact name, then requires the row and menu to be enabled, hittable,
finite, and at least 44 by 44 points before activation. The separate `enroll-clone-fixture` lane
retains sidecar-prefilled coverage. Neither lane runs in smoke, benchmark, CI, or release.

Built-in Voice startup reliability is a separate compile-gated diagnostic, not an ordinary
benchmark or release lane. The headless route consumes a schema-v1 ordered plan plus an exact
untracked UTF-8 script; retained results contain only its SHA-256 and character count:

```sh
scripts/ios_device.sh delivery-reliability \
  --plan <plan.json> \
  --script-file <untracked-exact-script.txt>

scripts/ui_test.sh ios startup-parity \
  --script-file <untracked-exact-script.txt>
```

The app records a privacy-safe request receipt and one-shot startup boundaries, represents every
planned take, preserves allocation attempts zero/one with the same request and seed, and writes the
terminal sentinel last. Result schema v2 retains complete final and chunk QC, and, only for the
gated diagnostic request, a bounded generation-scoped rejected WAV plus codec trace. The same
loaded Mimi decoder replays that trace both incrementally at the captured production chunk ranges
and as one full decode; both replay WAVs receive ordinary persisted-WAV QC. No path, script, codec
ID, or raw error enters retained JSON.

The diagnostic writer and iOS pullable mirror share one validated capture run ID from the
registered device and benchmark keys. UI-only runs use their device run ID without needing
benchmark metadata. Missing, unsafe, anonymous, or conflicting identities refuse artifact capture;
they never fall back to a shared `not-bench` directory. Older misplaced artifacts remain failed
collection evidence and must not be relabelled or deleted as though successfully collected.

Post-generation rejection evidence must use the terminal model-diagnostic snapshot, not the
pre-loop timing snapshot. It therefore retains the final target-token and effective-token-budget
counters, bounded hot-loop timings, allowlisted EOS/token-cap flags, chunk/channel state, and the
model-versus-product terminal timeline alongside Fast-QC. Result schema v2 accepts the complete
Fast-QC v6 trailing-silence and cadence block while keeping earlier v2 result bytes valid. A host
validator that predates a producer's registered optional QC fields is a harness failure; update and
revalidate the retained bytes rather than relabelling the take.

When one codec trace reproduces the same defect through incremental and full Mimi decoding, that
excludes incremental scheduling, UI publication, and the final writer as necessary causes. It
does **not** distinguish invalid sampled codes from a defect shared by both decoder paths or
platform numerics. Voluntary EOS excludes a token-cap termination, not a common decoder defect.
Keep the cause qualified until independent code/decoder evidence distinguishes those branches.
Keep the ordinary fail-closed publication decision and explicit
user-controlled retry. Do not trim around interior silence, retry invisibly, mutate the seed,
weaken QC, or infer that a lower token budget is safe from one failing sample. Any continuation
budget candidate needs a pre-registered representative matrix showing that it prevents the
pathology without truncating valid speech or converting good rows into incomplete-output failures.

Full-unload preparation records memory before unload, after owned references release and MLX cache
clearing, immediately before a request, and after reload. A request starts only after three stable
one-second samples prove no active generation/operation/reservation/model, a cleared MLX cache, at
least 768 MiB process headroom, and footprint below the existing 4.5 GiB guard. The host polls the
exact PID returned by CoreDevice and immediately enters forensic collection if it exits before
terminal evidence; a process-query failure remains unknown rather than being treated as an exit.
Partial evidence is composed into explicit `process_terminated` and
`not_started_after_process_exit` rows, while CoreDevice `systemCrashLogs` are retained untracked and
reduced to an allowlisted termination summary.

The XCUITest route selects Vivian, Calm Strong, and English through genuine visible controls and
correlates the completed generation UUID with the engine receipt. An automation-session bootstrap
timeout is classified as infrastructure only when the `.xcresult` proves zero launched test cases
and the log contains no app assertion, generation, crash, or QC outcome. It is never retried
automatically; a manual rerun has a new run ID and separate evidence. Both routes are
physical-iPhone-only, publish nothing, and are documented in
[`ios-built-in-startup-reliability.md`](ios-built-in-startup-reliability.md).

Successful startup-reliability evidence is removed through a second narrowly gated launch. That
cleanup executes before native-engine initialization, writes a pullable acknowledgement only after
removing the run-scoped app/App-Group evidence, and never converts a generation result. If cleanup
fails, the already-collected run remains valid but the command fails and retains the artifact for
forensics; do not automatically rerun the generation.

**Bench spec syntax:** the `ios_device.sh bench` positional argument is the full
`mode:variant:text` spec; a bare argument is treated as *text* (wrapped as
`custom:speed:<arg>`), so `bench custom` generates the literal word "custom" — a
six-character prompt that mandatory Fast QC rejects at generation startup. Always pass
the full spec; a startup failure with healthy memory and a tiny `promptCharacters` in
the sentinel is this mistake.

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
