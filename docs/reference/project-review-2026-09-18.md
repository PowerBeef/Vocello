---
status: active
owner: backend-and-platform
reviewed: 2026-09-18
summary: Independent cross-project review, revalidation of AUD-01 through AUD-12, and the initial Codex–Claude setup evidence.
sourceOfTruth:
  - config/roadmap.json
  - project.yml
  - scripts/development_workflow.py
  - scripts/tests/test_agent_hooks.py
---
# Project review and assistant handoff — September 18, 2026

## Scope and source identity

Reviewed the clean `main` baseline `e0a4631308aacd0b6b68940b96192186e7a3c58e`, then implemented the
assigned collaboration, verification-routing and documentation changes on that checkout. No
application source, persistence schema, dependency pin or runtime API changed. Claude remains the
primary developer; Codex supplies independent review and explicitly assigned implementation.

This is a risk-focused review of architecture, ownership, failure paths, test coverage and operational
contracts across the whole project. It is not a line-by-line certification of every file. It includes
native compile/test evidence, but not device behavior, native UI acceptance, model quality or release
qualification. Open-work status belongs exclusively to [the roadmap](../../config/roadmap.json).
The findings below reuse all twelve existing AUD identifiers; there is no new application defect
with sufficient independent evidence to justify another identifier in this review.

The [September 17 audit](ui-rework-audit-2026-09-17.md) is historical evidence. This revalidation
narrows several of its claims: view-created tasks are registered with a coordinator; clone requests
retain their transcript after optional priming; database deletion errors are surfaced; unverified
StoreKit transactions must not be assigned an unconditional finish policy on the current evidence.

## Architecture and ownership map

Paths below are relative to the repository. Line references describe the reviewed baseline.

| Boundary | Current owner and source | Important contract |
| --- | --- | --- |
| Native composition | `Sources/QwenVoiceCore/NativeRuntimeFactory.swift:72`; `Sources/Services/MacEngineBootstrap.swift:33`; `Sources/iOS/IOSAppBootstrap.swift:8`; `Sources/VocelloCLI/CLIRuntime.swift` | Both apps and CLI use the same native factory, registry, assets and MLX engine. macOS hosts the engine in process; old XPC architecture is not current. |
| UI generation | Shared `Sources/iOS/Studio/StudioGenerationCoordinator.swift:60`; shared store compiled by path through `project.yml`; macOS Studio views | Main-actor UI attempt identity rejects stale completion; installed tasks can be cancelled. UI state and engine actor lifecycle have separate responsibilities. AUD-03 concerns where tasks are constructed. |
| Engine lifecycle | `Sources/QwenVoiceCore/ActiveGenerationCoordinator.swift:126`; `Sources/QwenVoiceCore/MLXTTSEngine.swift`; owned `Packages/VocelloQwen3Core/Sources/VocelloQwen3Core/Engine.swift:918` | Register before start, typed cancellation, await termination, recheck identity across suspension; reservation abort joins completion before admitting another request. |
| Streaming and finalization | Owned `ClassifiedGenerationSession.swift:119` under the same package; `config/runtime-refactor-contract.json` | Audio is frame-bounded, lossless and suspending. Progress may be coalesced. Cancellation wakes suspended operations; finalization has a separate barrier/token. Do not replace this with dropping PCM buffers. |
| MLX and sampling | `Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift:4655`; `config/concurrency-safety.json`; `docs/reference/qwen3-core-maintenance.md` | Request-local randomness, isolated array ownership, registered unsafe boundaries, inventory and semantic-delta maintenance for the owned package. |
| Memory and warmup | `Sources/QwenVoiceCore/NativeMemoryPolicyResolver.swift`; `Sources/Services/MacGenerationWarmupCoordinator.swift`; `MLXTTSEngine.swift:156` | Policy varies by host tier. Prewarm shares lifecycle ownership. High-memory retention is an explicit policy gap/tradeoff, not proof of a leak. |
| Persistence | `Sources/iOSSupport/Services/DatabaseService.swift:142`; `Sources/SharedSupport/Database/LongFormHistoryAcceptance.swift:160`; saved-voice lifecycle contracts | Shared database, recovery journal and acceptance checks; preserve fail-closed recovery and idempotency when addressing contention or deletion. |
| Model publication | `Sources/QwenVoiceCore/SharedModelComponentStore.swift:577`; production receipts/catalog and download-state actors | Verify source and digest, construct/validate replica, take cross-process publication lock, verify snapshots, atomically publish. A failed staged install must preserve the old installation. |
| Audio and documents | `Sources/SharedSupport/ViewModels/{AudioPlayerViewModel,ReferenceClipRecorder,ClipReviewPlayer}.swift`; `Sources/QwenVoiceCore/DocumentIO.swift` | Shared playback/recording owners, sandbox/document access and private local files; iOS audio-session coordination still has AUD-02. |
| Purchases/export | `Sources/iOS/Commerce/IOSStoreKitClient.swift:43`; `Sources/iOSSupport/Services/IOSExportPurchaseState.swift`; export provenance policy | One StoreKit adapter, verified non-revoked entitlement only, explicit Restore sync, export checks at the shared boundary; no preference-based unlock. |
| CLI and Python | `Sources/VocelloCLI/CLIProcessSupervisor.swift:29`; `scripts/development_workflow.py`; `scripts/ci/classify_changes.py`; `config/toolchain.json` | CLI signal ingress cancels owned work and has a bounded forced-exit deadline. Python selects tests by dependency/lane; scripts own execution, evidence and caches. |
| CI and distribution | `.github/workflows/{ci,nightly,security,release}.yml`; `scripts/release_source_authority.py:99`; `config/{orchestration-contract,build-output-policy,tsan-policy}.json` | Exact-source release checks, pinned toolchain/actions, serialized owned caches, explicit signing/publication boundaries. Green aggregate CI can include skipped lanes. |
| Website | `website/CLAUDE.md`; `website/src/App.jsx`; `website/package.json`; `config/public-product-facts.json` | Independent React/Vite workflow, public claims bound to facts, production prerender/hydration and Playwright acceptance at wide/narrow widths. |

## Coverage and remaining uncertainty

| Subsystem | Reviewed / verified | Not established by this review |
| --- | --- | --- |
| Engine/owned package | Actor admission/abort/finalization, task-start gate, prewarm lifecycle, bounded audio send/cancel, request sampling, unsafe registry and dependency ownership; core/runtime suites and TSan passed | Exhaustive schedules, real-model quality or throughput, long-session memory behavior; fixture-dependent runtime tests remain skipped |
| macOS/iOS | Bootstrap, generation task installation/cancellation, shared store compilation, audio category/observers, navigation/import presentation, modal focus structure, localization and export contracts; generic iOS compile passed | Phone execution, real interruptions/routes, VoiceOver behavior, native visual acceptance, StoreKit sandbox purchases or on-device logic-test execution |
| Persistence/delivery | Journal reconciliation/read visibility, deletion ordering, migrations/idempotency, saved-voice lifecycle and path/integrity contracts; staged publication snapshots/locks/atomic replacement and adversarial fixture coverage | Live network interruption/resumption, OS termination at every filesystem boundary, a production-user store migration or destructive recovery exercise |
| CLI/Python | Shared host factory, cancellation/exit path, lane selection, benchmark identity/privacy/provenance contracts and reproducible pins; configuration-only routing regression tests | Fresh model downloads, timed model benchmarks, ASR accuracy or new benchmark qualification |
| CI/release | Lane baselines/skips, blocking TSan policy, quarantine opt-in, pinned actions, cache ownership, exact-tag/security/evidence checks | A new signed archive, notarization, App Store upload, website publication, account credentials or release-tool compatibility |
| Website/docs | Public-facts/render accessibility contracts, lint/unit suite, prerender builds and actual production browser hydration/navigation at two widths; instruction and architecture cross-check | Every browser/assistive technology, real-device visual acceptance or external hosting configuration |

## Revalidated application findings

Severity is impact-based: P1 = high-impact failure path worth prioritizing, P2 = bounded defect,
reliability/architecture gap or investigation, P3 = optimization/API debt. None is a confirmed P0.
“Confirmed” below refers to the cited code property; device/user impact is separately qualified.
All corrections and regression expectations are assignments for later work, not changes made here.

### AUD-01 — P1: startup recovery; competing import/onboarding presentations

**Confirmed:** `Sources/iOS/QVoiceiOSApp.swift:44–58` presents a terminal startup-error screen;
`IOSAppBootstrap.swift:8–38` constructs immutable dependencies/error once. A recoverable initialization
failure has no in-app retry. `Sources/iOS/App/RootView.swift:117,138,325–341` can request the import
cover while onboarding is active. **Hypothesis:** SwiftUI loses the imported-file handoff in that
state; no phone reproduction was attempted.

**Correction/test:** make bootstrap retry an owned operation with an injected failing dependency;
queue and consume external imports after onboarding. Prove failed-then-successful startup and exactly
one preserved import; use the consented phone lane for presentation acceptance. A permanent underlying
filesystem fault cannot be promised away by adding a Retry button.

### AUD-02 — P1: recording changes a session the shared player does not restore

**Confirmed:** `ReferenceClipRecorder.swift:145–146,250,279` selects `.record`/`.measurement` and later
deactivates the session. `AudioPlayerViewModel.swift` does not set its playback category; compare
`ClipReviewPlayer.swift:53–60`, which does. `IOSPlayerSheet.swift:769` and
`IOSStudioInlinePlayerCard.swift:662` contain other player owners without their own interruption/route
observers. The shared AudioPlayerViewModel **does** observe interruptions/routes (`:331` onward).
**Impact requiring device proof:** record-then-play silence or stale state after a call/headset change.

**Correction/test:** centralize audio-session policy and restore the appropriate category/activation
at each transition. Exercise record → stop/cancel → playback, interruptions, route removal and recovery;
test state transitions with an injected session and audibility on the phone.

### AUD-03 — P2: view-created tasks violate the ownership rule

**Confirmed policy inconsistency:** generation tasks originate in `MacCustomVoiceScreen.swift:337`,
`MacVoiceDesignScreen.swift:351` and `MacVoiceCloningScreen.swift:948`. However, all three install them
into the coordinator (`:358`, `:380`, `:983`). `StudioGenerationCoordinator.swift:60–118` gates attempts,
cancels the registered task and controls terminal cleanup. This is not evidence that cancellation is
unowned or a critical race exists.

**Correction/test:** move task creation to the coordinator/service boundary required by
`.claude/rules/native.md`, preserving request snapshots and stale-attempt guards. Cover rapid
start/cancel/restart and late completion; retain the separately consented native smoke acceptance.

### AUD-04 — P2: clone readiness/error policy needs a defined outcome

**Confirmed:** `Sources/iOS/IOSGenerationModeViews.swift:1391–1414` computes clone context separately
from `canGenerate`; `:1900–1908` discards optional prime errors. **Earlier claim not established:**
silent conversion to audio-only cloning. `:1426–1455` already displays preparation/fallback copy,
and `:1924–1937` still passes the requested transcript and prepared-voice identity into generation.
`Sources/QwenVoiceCore/NativeCloneSupport.swift:658` resolves transcript input rather than inherently
dropping it because optional warmup failed.

**Correction/test:** define which readiness states permit on-demand preparation and which require an
error; report terminal failures without conflating opportunistic warmup with required conditioning.
Inject hydration/prime failures and assert the final reference/transcript payload and visible outcome.
Retain a device check for the actual readiness UI. Do not blindly disable valid on-demand generation.

### AUD-05 — P1 for deletion outcome, P2 for scaling/queue contention

**Confirmed:** `DatabaseService.swift:142–149` reads history through a write transaction;
`LongFormHistoryAcceptance.swift:160–200` reconciles filesystem state there; `:207–214` fetches all
history. `Sources/iOS/History/HistoryScreen.swift:587–600` deletes the database row before a `try?`
audio unlink. A failed unlink is silent and may strand private audio. Database deletion errors are
already caught and displayed; they must not be described as swallowed. The indexed idempotency key
and off-main macOS delete were previously repaired and are not reopened.

**Correction/test:** surface/recover audio deletion failures, bound displayed pages while preserving
access to the full archive, and shorten database-held filesystem work without weakening journal
atomicity. Inject unlink and database failures, interrupt recovery, test idempotence and page through
a large archive. The prior audit's UI-query timeout is historical evidence, not a reproduced result here.

### AUD-06 — P2: custom modal background lacks accessibility exclusion

**Confirmed structural gap:** `Sources/iOS/App/RootView.swift:95–102,253–307,413` dims/blurs the
background for custom panels but does not explicitly exclude its controls from accessibility.
The privacy-cover accessibility modifier elsewhere is a different surface.
**Hypothesis:** VoiceOver can focus and activate obscured controls; phone validation remains necessary.

**Correction/test:** apply modal focus/background exclusion consistently; verify focus enters the
panel, cannot reach the underlying controls, and returns predictably after dismissal with VoiceOver.

### AUD-07 — P2 investigation: unverified purchase recovery, not unconditional finish

**Confirmed intended security behavior:** `IOSStoreKitClient.swift:43–60` only retains verified
eligible transactions for finishing. `IOSExportPurchaseState.swift:125–148` rejects an unverified
transaction and displays `.unverified`. `Tests/VocelloiOSLogicTests/IOSExportPurchaseTests.swift:61–93`
explicitly expects no entitlement and no finish. **Not proven:** permanent redelivery on each launch,
Restore being unable to recover, or unconditional finishing being the correct remedy.

Apple's [PurchaseResult documentation](https://developer.apple.com/documentation/storekit/product/purchaseresult)
demonstrates verification and delivery before finishing a verified transaction; it leaves handling
verification failure to the business model. It does not justify the earlier roadmap gate. This review
therefore reframes that item, preserving its identifier and parked status.

**Correction/test:** reproduce verification failure and recovery in an explicitly authorized StoreKit
lane; specify the retry/Restore message and transaction handling from that evidence. Retain tests
that unverified, revoked and wrong-product transactions cannot unlock export, plus delayed/repeated
updates. Do not discard an unfulfilled purchase merely to suppress an alleged redelivery loop.

### AUD-08 — P2: source scanning cannot prove runtime-log privacy

**Confirmed enforcement/documentation gap:** `scripts/privacy_scan.py:23–32,46–66` checks known literal
patterns, not runtime values. `GenerationTelemetryMerger.swift:107–129` and
`IOSGenerationModeViews.swift:1992` interpolate error descriptions; filesystem errors can carry paths.
No real private log was collected or published. User-requested CLI output paths are not automatically
the same defect as diagnostic telemetry.

**Setup correction made:** CLAUDE.md and privacy-storage.md now describe the lexical gate's actual
scope. **Remaining correction/test:** audit error-to-log boundaries and use typed safe classifications;
inject synthetic path/prompt-bearing errors and assert prohibited content never enters retained logs.
Keep the existing allowlisted failure-support schema and privacy scan; narrowing prose alone does not
prove runtime redaction.

### AUD-09 — P2: smoke depends on an undeclared saved-voice prerequisite

**Confirmed:** `VocelloMacSmokeUITests.swift:97–112` calls `assertSavedCloneVoice`; the helper in
`VocelloMacUITestCase.swift:205` expects the benchmark voice. `scripts/ui_test.sh:293` preflights that
fixture for the clone benchmark, not smoke. The smoke journey does not create it. A fresh store can
fail for absent test data rather than the behavior under test. “Leaves no persisted state” can still
be true for a read-only journey that requires existing state; the old audit's logical contradiction
was overstated.

**Correction/test:** declare and verify the prerequisite with an actionable preflight, or enroll and
restore a fixture through genuine UI under the consented runner. Test absent/present prerequisite
behavior and preserve unrelated user data. No smoke lane was run for this review.

### AUD-10 — P2 policy decision: high-memory warmup has no idle/pressure retirement

**Confirmed:** `NativeMemoryPolicyResolver.swift:62–70` gives the high-memory Mac tier no idle unload;
`MLXTTSEngine.swift:630–634` excludes that tier from its pressure monitor, and `:156` returns when the idle delay is nil.
`MacGenerationWarmupCoordinator.swift` can warm on navigation. **Impact:** potentially long-lived
resident weights after browsing. This is an intentional latency/memory tradeoff; explicit unload,
model replacement and process exit still exist. It is not demonstrated unbounded growth.

**Correction/test:** choose an idle/pressure retirement policy for that tier, preserve serialized
prewarm and active-generation ownership, and test policy transitions deterministically. Real model
memory/latency qualification remains a separately requested benchmark, not a unit-test inference.

### AUD-11 — P3: avoid linear sampler membership work; measure benefit

**Confirmed optimization opportunity:** owned `Qwen3TTS.swift:4710–4725` uses array `.contains` for
repetition IDs and invalidates/rebuilds its MLX cache when a new ID is appended. An outer set exists at
`:3312,3766`; it is not used to make the scratch buffer's membership test constant-time. The rebuild
does not happen for every repeated token, contrary to the earlier wording. Timing impact is unmeasured.

**Correction/test:** retain deterministic insertion order and array/MLX isolation while using set
membership where appropriate; document the package semantic delta and refresh owned inventory.
Require seeded token/PCM parity and a separately authorized benchmark before claiming a speedup.

### AUD-12 — P3: audio interruption API migration

**Confirmed API debt:** recorder, shared player and review player use
`AVAudioSessionInterruptionTypeKey`. The installed Xcode 27 SDK's AVAudioSessionTypes.h marks it and
the interruption type deprecated for iOS 27 in favor of the inactive/resumption notification model.
**Refuted build-blocker claim:** this review's generic iOS compile with project warning policy passed.

**Correction/test:** availability-gate the new notification model while preserving deployment-target
behavior. Exercise interrupted recording and playback, route changes, cancellation and user-initiated
resume on the phone. Do not perform this behavior change as an untested symbol rename.

## Collaboration fixes delivered

- Thin root and website `AGENTS.md` entry points route to existing shared/domain instructions.
- One hook implementation serves both clients. `agent_hook_input.py` accepts Claude file/notebook
  edits and Codex patch text, inspecting add/update/delete and both rename paths, canonicalizing paths
  and rejecting unreadable patches. Generated outputs and the root-project regeneration reminder
  retain their existing policy. Shell guards retain branch/worktree, force-push, Simulator and cache rules.
- Settings-only changes now select both hook test modules locally and the CI Python lane; `.codex`
  configuration and instruction entry points participate in the relevant repository invariant scan.
- Seven local project actions use existing commands; setup is empty. No new runtime, dependency,
  automatic assistant delegation, global installation or task database was introduced.
- The development guide now specifies assignment, baseline, one editor/native lane at a time,
  evidence and ownership transfer. Unexpected changes require reconciliation before overlapping edits.

Behavioral fixtures cover multi-file patches, moves, generated-file rejection, ordinary edits,
Claude parity, root/website paths, symlinks, malformed input, reminder output and configured commands.
They exercise the real guard scripts rather than assert documentation wording. Hooks remain
best-effort tooling safeguards, not comprehensive security enforcement.

## Documentation inconsistencies

Corrected the development guide's stale assertion that local `dev.sh check` never compiles UI-test
bundles: `development_workflow.py:175–210` already selects build-only bundle checks. Corrected the
privacy gate's overclaim and the audit/roadmap interpretations above.

Two source comments remain misleading but do not change runtime behavior:
`Sources/iOSSupport/Services/DatabaseService.swift:16` describes an iOS copy of a removed macOS file,
although this service is now shared; the trailing comment in owned `GenerationSession.swift:190`
describes a non-suspending session, unlike the classified channel's current implementation. Read the
compiled graph and classified channel as authority. These are documentation follow-ups within the
existing owning work, not new application defects or reasons to alter the owned package in this setup.

## Verification evidence and environment

All paths in this section are local, ignored artifacts, not published diagnostics. Local run labels
use UTC and may differ from the workstation's calendar date. Source was the baseline plus the
collaboration patch; native application inputs were unchanged.

| Check | Result / evidence |
| --- | --- |
| Baseline exact-commit CI | [Run 35259883779](https://github.com/PowerBeef/Vocello/actions/runs/35259883779): native, Python and contracts passed; website skipped. This is baseline evidence, not CI for the setup patch. |
| Deterministic native | `scripts/dev.sh test`: 691 core passed; owned runtime 122 passed, 3 skipped. `build/artifacts/macos/tests/mac-test-20260918-033920/` contains verdict and structured counts. |
| TSan | `scripts/macos_test.sh tsan`: 689 passed, 2 skipped; `build/artifacts/macos/tests/tsan-20260918-034351/`. This is the configured core lane, not sanitizer coverage of every dependency/MLX kernel. |
| Generic iOS | `scripts/dev.sh ios`: app and app-host-free iOS logic bundle compiled; logs under `build/artifacts/foundation/`. Compilation is not execution of iOS tests. |
| Hook/router tests | Targeted Claude/Codex hooks, development router and CI classifier: 58 passed, 74 subtests passed; changed shell hooks passed shellcheck. |
| Full Python suite | `scripts/dev.sh py --all`: 1,566 passed, 940 subtests passed; includes product, research and Darwin-marked tests on this host. |
| Final repository check | `scripts/dev.sh check`: PASS in 146.6 seconds, including all project contracts/invariants, privacy/whitespace/shell lint, full Python suite, generic iOS compile and full website check. No native UI runs were selected. |
| Website | Full `npm --prefix website run check` passed inside the final repository check: lint, 12 tests, rendered accessibility, client/SSR/prerender builds and both Playwright cases. Earlier browser stage was sandbox-blocked; its isolated rerun also passed. |
| Instruction discovery | Fresh `codex debug prompt-input` from root included root guidance; from website included both root and website guidance. No model was invoked and rendered private context was not retained. |
| Hook loader / trust | Local Codex 0.154.0 `hooks/list` discovered all five project hooks with correct events/matchers, no warnings/errors; all five reported **untrusted**. Passing script fixtures does not establish automatic execution. |
| Project actions | TOML parsed; every action entry point resolves; supported icon values checked against installed editor. Build/run actions were not invoked merely to test a button. |

The first native attempt (`mac-test-20260918-033612`) failed due to sandbox compiler-cache permissions;
its artifacts remain. The successful run used normal host build access without changing caches or
product settings. The website's initial local-listener denial was also environmental, and its
production-browser rerun passed. These failures must not be rewritten as successful first attempts.

The three runtime skips require AudioSeal export fixtures (two) and a private retained-code replay
input (one). TSan skips the real-process CLI signal and cross-process prepared-voice locking cases
under the existing sanitizer policy; both passed in the ordinary core lane. No test was newly
quarantined, disabled or relaxed for this work.

Installed Xcode **27.0 / Swift 6.4** differs from pinned **26.6 / 6.3.3**. The release audit also found
GitHub CLI **2.92.0 vs 2.96.0** and App Store Connect CLI **0.18.2 vs 4.11.0**. Other audited native,
Python and website tool versions matched their relevant pins. `supply_chain_contract.py --installed
all` therefore reports drift; this does not prevent ordinary development. Pins and global installations
were preserved. Local compatibility is not a substitute for the pinned CI verdict.

## Handoff and activation limitation

The existing primary roadmap remains authoritative; this setup does not reprioritize UI work or
authorize application remediation. Claude should inspect the actual commit/diff and dirty tree before
taking ownership, then select the next assigned roadmap item.

**Required platform step:** review/trust the five project hooks in Codex's hook UI, then start a fresh
session. Confirm the session summary and run a harmless allowed tool call. Exercise a synthetic
generated-path rejection and project.yml reminder through the fixture suite; do not attempt a real
forbidden command or mutate a generated file just to prove a guard. Automatic lifecycle dispatch
after trust still needs a fresh-session smoke check; the current session cannot certify it while the
loader reports untrusted. This limitation follows the
[official hook trust contract](https://learn.chatgpt.com/docs/hooks), not an extra repository approval rule.

Device runs, native UI acceptance, model benchmarks, signing, releases and publication remain
separate explicit assignments. No such action was taken during this review.
