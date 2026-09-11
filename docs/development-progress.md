---
status: active
owner: backend-and-platform
reviewed: 2026-09-10
summary: Current release-first resume checkpoint; dated evidence lives in the pinned development history, and config/roadmap.json owns status.
sourceOfTruth:
  - config/roadmap.json
  - config/runtime-refactor-contract.json
---
# Vocello development checkpoint

Start here, then follow `config/roadmap.json`'s `primaryPlan` and the
[release-first execution plan](reference/release-first-execution-2026-09.md).
This is a narrative, not a second work ledger. Product source, contracts and scripts win.

## Resume now

### Claude Code adoption (September 11)

Claude Code replaced Codex as the development environment in six checkpointed commits on `main`
(roadmap plan `claude-code-adoption-2026-09`, CCA-01 to CCA-12, all done and the plan complete). `AGENTS.md` became a
177-line `CLAUDE.md`; the five domain rules moved to path-scoped `.claude/rules/` with a new
always-loaded `claude-tooling.md`; the nested website guidance became `website/CLAUDE.md`. Every gate that
named the old files was rewired in the same commit, the Codex hook config and session-storage tooling
were retired (runbook pinned historical), and `scripts/claude_config_contract.py` now validates the
repository-owned configuration inside the project gate. `.claude/settings.json` wires the unchanged
commit gate plus `policy_guard.sh` (Simulator destinations, whole-cache deletion, force pushes, new
branches, `project.pbxproj` writes, unacknowledged gate skips), `generated_file_guard.sh` (generated
and frozen files, pinned bodies ask first), a `project.yml` regeneration reminder and a session-start
ritual; `scripts/dev.sh status` reports branch, verification class, receipt state and primary plan.
Seven project skills and four read-mostly subagents route to the existing scripts and documents;
device, model and release lanes stay user-invoked only.

Two harness findings were recorded with evidence rather than assumed. The checkpoint receipt no longer
binds PATH membership (`local-v3`): the hook environment lacks the plugin `bin` entries the tool shell
appends, which made a fresh receipt read as stale. For CCA-09 the direct `xcrun xctest` runner stays:
bounded `xcodebuild test-without-building` trials on the same xctestrun passed one class in 4 s but
took 95 s for the full bundles and failed two tests that pass under the direct runner on every
checkpoint (`CLIExecutionTests.testRealSignalsReachNativeSupervisorAndAwaitCleanup` at 31.4 s and
`PreparedVoiceRepositoryTests.testTwoNativeProcessesExcludePreparationReplacementAndDeletion` at
45.2 s, both real native-process boundaries timing out under the xcodebuild test host). The lane now
writes `core`, `transport` and `runtime` `test-results.json` summaries through the shared
`scripts/lib/xctest_summary.py`, and `scripts/macos_test.sh test --coverage` is an opt-in,
non-blocking llvm-cov export. The Python test roots are one root (`scripts/tests/`); the
2026-08-21 omitted-tests finding was already closed, and full discovery runs every module (130 modules, 1736 declared tests; discovery ran 1736 tests in 302.029s).

Follow-ups scheduled, not started: TSan characterization before its 2026-09-30 deadline
(`config/tsan-policy.json`, one of three consecutive passes recorded) with `axiom:concurrency-auditor`
first; an `axiom:iap-auditor` pass over the iOS export unlock before RF-13; an
`axiom:accessibility-auditor` pass for ISU-4; the optional `swift-lsp` build-server setup. Product
critical path is unchanged: ISU-4 localization qualification and RF-13 remain next; the adoption track
is closed.

### September 10 bounded Settings scrolling correction

App-language run `ios-xcui-localization-20260910-165027-fa2f0c10` passed its English/French
immediate-update, relaunch and draft-preservation assertions plus Default/French-Default/AX-L
page checks, then failed before tapping App Language at AX-XXXL. The prior
`ios-xcui-localization-20260910-164426-11ab77c8` remains a separate zero-case bootstrap failure.
The measured 514-point row alternated above/below the 632-point viewport under full-window
swipes. System Default was restored in completed configurations; the final configuration failed
before mutation, and exact-PID readback confirmed app termination. Neither run is a passing lane.

Physical run `ios-xcui-localization-20260910-175737-c71a0c95` rejected the initial delta transport:
`scroll(byDeltaX:deltaY:)` requires pointer events unsupported by this iPhone. Default/French
completed; AX-L failed revealing About, and AX-XXXL/pseudo were not reached. The original System
Default selection was verified in teardown and the final app PID was independently absent.
This is a harness failure, not a product-scroll verdict; SDK compilation did not qualify touch input.

The helper now uses slow native touch swipes on small, fully visible static-text descendants of
one uniquely identified containing scroll view. It never falls back to a dock-obscured row or
full-window swipe. It remeasures each step, reduces the anchor size after reversals, records evidence
before gestures and stops on stationary/impossible geometry or absent safe anchors. Full visibility,
hittability and the separate oversized-navigation rule remain unchanged; no coordinate exception,
production UI change, or automatic retry was added. Native regressions replay the retained
geometry with several displacement gains. Focused verification is recorded in
`build/artifacts/ios/bounded-scroll-native-corrected.log` and `bounded-scroll-python.log`; the coherent
checkpoint is `bounded-scroll-checkpoint.log` (prior pointer implementation, not touch qualification).
The current repair uses `touch-scroll-native.log` and `touch-scroll-python.log`: 14 native policy
tests and 108 Python tests passed. Two subsequent containment source-contract tests passed in
`touch-scroll-containment-python.log`. Use terminal outcomes only.

Touch run `ios-xcui-localization-20260910-182012-6b1ea48d` completed Default/French and AX-L Audio/About,
then failed revealing the Clone status. The containing-scroll query ambiguously matched the
SwiftUI Label's identifier across element types. It now matches the resolved target's element type
and exact frame, retaining single-container ownership and fail-closed behavior.
Fresh run `ios-xcui-localization-20260910-183118-bfdbff01` completed Default, then encountered an
explicit `NotificationShortLookView` banner during the French-Default App Language Back tap.
The failure screenshot shows ChatGPT foreground; this is an external-interruption failure, not a
proven Back-button defect. The lane remains failed with all required steps accounted for. System
Default was observed before the interruption and remained selected in the retained app tree;
teardown could not complete its navigation, but exact-PID readback independently proved termination.
No automatic retry followed. Raw screenshots, original failures and session checkpoints remain
untracked under the two run IDs. Resume with an uninterrupted, explicitly authorized phone session;
the latest containment correction had not yet reached its physical acceptance point in that run.

After the user enabled Do Not Disturb, separately authorized ten-minute run
`ios-xcui-localization-20260910-184111-4c20b0d2` completed Default, French-Default and AX-L, including
the previously failing Clone status/Voice Models reveal. System Default restoration completed
before the AX-L app terminated. AX-XXXL had just launched when the exact owned Xcode process was
interrupted for the phone deadline; pseudo was not reached. No assertion failure preceded the
deadline stop. The runner retained available forensics and finalized its required-step ledger as
failed/incomplete, with no missing steps; the Xcode interruption/shutdown stack is not an app-crash
verdict. Exact-PID readback proved the final app absent and the phone was released before the
deadline. This is useful partial physical evidence, not a passing localization lane. AX-XXXL/pseudo
still require another authorized window; no automatic retry or further device work followed.
Fresh authorized AX-XXXL/pseudo physical qualification remains open under ISU-4; prior successful
assertions remain partial historical evidence. The eight additional translations are still pending.
The publication checkpoint log for this coherent App Language/touch-scroll tree is
`build/artifacts/ios/app-language-touch-publication-checkpoint.log`; its terminal result, not the
earlier pointer-only checkpoint, governs commit readiness. No device or release lane is part of it.

### September 10 app-language host continuation (partial implementation)

Settings now includes App Language after Audio, with System Default and the complete bundled
English/French choices. `IOSAppLanguage` owns a separate persisted UI preference; the existing
typed helpers read its explicit compiled-catalog context. No application-root identity reset,
engine/request change, StoreKit price reformatting or macOS selector is introduced. The new native
tests exercise preference/fallback, actual compiled strings and plurals, Observation updates,
regional formatting and opaque price/user-text preservation. The existing XCUI localization walk
now covers genuine selection, relaunch and draft checks, and records/restores the original choice.
No phone was contacted during this continuation.

The approved ten-language plan is **not complete**. The catalog has 491 EN/FR entries; the eight
additional locales remain absent rather than partially shipped. ASR-12 retains remaining indirect
stored-error/status review and the translation batches, after ISU-4's unresolved AX-XXXL/pseudo
navigation qualification. Physical language-switch/state/layout tests require separate approval;
the earlier device runs below do not qualify this changed source. Host verification logs are
`build/artifacts/ios/app-language-native-tests.log`, `app-language-compile.log` and
`app-language-checkpoint.log`; only terminal PASS results may be used as verification evidence.

### September 10 physical localization and local StoreKit checkpoint

The authorized device session is collected; no 201-take campaign or live transaction ran.
Each retained run owns its full-tree source identity; partial results below are not merged
into an overall localization or processed-candidate PASS.

- **Corrected product boundary:** measured AX-L frames proved the fixed Settings bottom padding
  was shorter than the actual dock. RootView now supplies measured dock height to Settings,
  Voice Models and attribution scroll content. Subsequent localization runs passed the previously
  failing AX-L About and Models routes, preserving the original strict visibility assertions.
- **Remaining harness boundary:** full-window swipes oscillate past a large row or start over the
  enlarged dock. Two bounded element-swipe experiments failed and were reverted. Run
  `ios-xcui-localization-20260910-143825-3a36824a` completed EN/FR Default and AX-L but failed
  AX-XXXL About. The original failure, one notification interruption, one zero-test compile failure,
  and both rejected experiments remain pinned. Do not repeat them or describe full accessibility
  acceptance as complete.
- **Settings stateful:** `ios-xcui-control-audit-20260910-144631-2fdbfc0e` completed in 281.5s:
  eight PASS observations, four prerequisite blocks and two preservation-policy blocks. Four
  toggles and all three variation options were exercised and restored; global History deletion
  was cancelled. Session initialization now precedes purchase presentation, and awaited XCTest
  teardown retains observed setting values for abort cleanup rather than assuming defaults.
- **Accessibility:** `ios-xcui-control-audit-20260910-145307-323ae6b2` failed pseudo-AX-XXXL
  navigation after Default/AX-L/AX-XXXL Audio captures and clipping checks. Terminal observations
  were absent, so host collection/composition correctly failed too. These captures are partial
  evidence, not an aggregate PASS or actual VoiceOver speech/rotor verification.
- **Local StoreKit:** `ios-xcui-purchase-20260910-145728-79fd9b31` passed ten lifecycle phases
  in 54.4s; `ios-xcui-purchase-20260910-150003-613fa5c8` passed all 23 lifecycle/export phases
  in 295.6s. Built-in export stays free; Design/Clone History/full-player routes follow owned
  versus revoked entitlement while internal playback stays available. Schema-3 restoration
  verifies cleared test transactions, original tab/filter and app termination. No real charge,
  external transfer, account edit, actual offline or processed-candidate proof is claimed.

All completed runner crash-delta checks are clean. Visual inspection found coherent French
Settings/model copy and default purchase presentation; larger scrolling surfaces are not fully
qualified. Fixture prices are not the release USD 19.99 price. The post-device focused suite
passed all 123 adjacent Python tests. The post-device deterministic checkpoint passed 1,720 Python
tests, 615 core, 19 transport and 125 runtime tests (three optional fixture skips), generic iOS
app/logic compilation and the macOS app build. Its retained log is
`build/artifacts/ios/localization-device-checkpoint-20260910.log`, with native results in
`mac-test-20260910-111719`. Publication verification after the documentation/index checkpoint uses
`build/artifacts/ios/localization-publication-checkpoint-20260910.log`; neither checkpoint clears
the physical navigation findings.

Next, ISU-4 owns the bounded large-text reveal repair and missing layouts; ASR-12 owns remaining
EN/FR indirect-error and candidate-wide acceptance before additional UI locales. RF-13 retains
actual offline, other outward-export routes and sandbox/processed-candidate proof. Do not run the
inventory or simple enrollment journey until they restore the observed Studio selections/draft
and consent; their current hard-coded resets are unsafe for personal state. Built-in remains
uninstalled, so normal smoke/generation/performance prerequisites are absent. Earlier isolated
model-install acceptance remains historical; no canonical model installation was changed here.

Final screen-protection run `ios-xcui-screen-protection-20260910-150637-33b6b221` passed the
French three-minute Auto-Lock readback and complete runner ledger. The second independent
CoreDevice readback confirmed current `passcodeRequired=true`, not merely historical unlocking.
Private readbacks and the full session ledger remain untracked in
`build/artifacts/ios/localization-device-session-20260910.json`. No device UI follows protection.
The dated migration sections below describe earlier host-only continuations, not the current
device session.

### September 10 English/French localization — expanded interface migration

The main catalog now has 488 manually owned English/French entries, plus the two iOS system
permission entries. The expanded batch migrates recording/enrollment review and quality warnings,
History filters/actions and recovery, player controls, delivery/reference sheets, language/preset
display names, download transfer detail, long-form status and additional VoiceOver labels.
Complete-message formatting preserves counts, byte totals and substituted user content; plural
forms cover count-sensitive messages. This is presentation work, not a generation, sampling,
quality-policy, saved-data or purchase-eligibility change.

The maintainer chose Simplified Chinese (`zh-Hans`) and Brazilian Portuguese (`pt-BR`) for later
batches. Shipping resources still contain only the maintained English/French UI, not ten locales.
Canonical starter briefs remain model content; original license bodies, stored names/transcripts
and diagnostic/system error details are not translated by blind substitution. Indirect shared
error presentation and physical EN/FR review remain open under ASR-12; ISU-4 owns the retained
Settings reveal failures. The later physical checkpoint above records the measured AX-L correction
and the still-unqualified larger layouts; qualify those before expanding locales.

The first expanded generic iOS app/logic compile passed. Fifteen focused localization tests pass,
including production typed-key/default-to-catalog binding. The 120-test adjacent Python run found
one old source assertion expecting a literal Clear search label; the correction checks its typed
binding and exact English/French labels while preserving query, geometry and clearing assertions.
The new native fixtures cover exact percent/64-bit counts, project-not-yet-saved wording and
verbatim substituted content. The first native run caught the new fixture expecting ungrouped
byte counts although Foundation correctly applies the host's numeric region; the expectation
now uses independently formatted locale-aware counts without changing production behavior.
The failed native run is retained as `mac-test-20260910-092713`. Final coherent-tree verification is recorded in the untracked
`localization-expanded-*-20260910.log` artifacts; a compile is not device acceptance.
No device, account, purchase or release operation ran in this continuation. The phone remains
in its last verified protected state; request availability/unlock before the next physical run.

### September 10 English/French localization — first migration batch

The approved order is English/French completion, the existing large-text Settings defect,
bounded additional-language batches, then separate App Store materials. ASR-12 owns candidate
acceptance and ISU-4 retains the navigation defect; neither is closed by translation work.
The missing 53 French translations in the existing main catalog are filled, and 38 typed
onboarding/tab/Studio entries plus two system permission entries have English/French copy.
Source-language wording, user data, generation prompts, enum/model identities, purchase state
and StoreKit pricing remain unchanged. Existing Settings/install work is preserved.

The localization contract now checks French presence, translated units, plural structure and
format-argument parity; purpose-string English must match Info.plist and resource inclusion is
explicit. The existing Settings reveal helper records bounded sampled frames/hittability only
on failure, retaining the unchanged visibility predicates and swipe budget. The French walk
asserts the genuine dock labels as well as the existing Settings checks.

This is not complete app localization: secondary sheets, recording/quality warnings, History
controls, transfer detail and other indirect/accessibility copy still require migration. The
AX-L About failure needs a new authorized physical observation before a causal fix. No additional
language is advertised, no App Store record changed, and the locked phone remains untouched.
See [localization](reference/localization.md) for migration boundaries and remaining order.

Focused verification: all 38 localization/Settings acceptance contract tests pass. The generic
iOS app and logic targets compile, and the updated XCUITest bundle passes build-for-testing
without launching on a device. The built English/French resources match all 440 expected string
and permission values. Derived-artifact validation passes. These checks prove resource delivery
and compilation, not rendered layout, translation quality across every screen or device acceptance.
The first full Python checkpoint found two stale source assertions for the reveal predicate after
its result was named for diagnostics. Updated assertions retain geometry plus hittability and
verify the failure attachment; no visibility rule changed. The initial failure remains recorded,
and a fresh deterministic checkpoint is required for the corrected test tree.

### September 10 physical Settings and Studio-install acceptance

The source stayed frozen through this authorized device session. The isolated all-mode install
lane `ios-xcui-model-download-20260910-064334-5a13c126` passed in 395.0 seconds: each Studio
Install CTA reached Voice Models and started its exact mode, all three models reached Ready,
Built-in cancellation/restart/background adoption passed, isolated files were removed, and the
canonical model-state comparison passed. Host diagnostics correlated 21 UI observations with
1,148 delivery events; integrity, progress visualization, crash delta and the required-step ledger
passed. This qualifies the installation shortcut, not generation or App Store candidate behavior.

`ios-xcui-localization-20260910-063837-775e6e5a` failed at 230.2 seconds on the existing AX-L
About navigation reveal assertion. English and French Default Audio/About/Voice Models checks,
French title/variation assertions and AX-L Audio completed. Ten named captures are retained;
reviewed French layouts wrap cleanly and show the new translated model copy. AX-L About/models,
AX-XXXL and pseudo-AX-XXXL remain unverified. The failure screenshot shows About above the dock,
but the exported partial accessibility snapshot does not establish its queried frame/hittability.
Next capture those values at the existing helper's failure boundary and correct only the proven
cause; do not weaken full-visibility assertions or automatically repeat the failed run.

The first screen-protection inspection failed before any test launched
(`ios-xcui-screen-protection-20260910-063514-6013d066`); its formal bootstrap classification is
retained. After explicit XCUITest unlock, a separate inspection passed. Final protection run
`ios-xcui-screen-protection-20260910-065150-43ca99c2` passed, selecting three-minute Auto-Lock
and verifying the persisted French Settings value before returning Home. Independent CoreDevice
readback confirmed the phone locked (`passcodeRequired: true`); no Vocello/test-runner process
remained. The raw readbacks and final resume checkpoint are retained untracked. No further
device UI follows that protection operation. No purchase transaction, account edit or release ran.
The initial stale preserved dSYM was replaced by the canonical runner's matching build symbols;
subsequent device preflight passed. ISU-4 stays in flight for the remaining layout/accessibility work.

### September 10 Settings review polish — implementation checkpoint

Applied the supplied review as a bounded continuation of ISU-4: compact localized Settings title,
context on Models & Files and Accessibility, trailing values with accessibility-size reflow,
compact About identity using the actual bundle version/build, and softer Back fills retaining
44-point targets. The unchanged cloning disclosure now sits outside the consent card. English/
French catalog entries cover Settings variation names and model names/actions/statuses; preference
raw values, model IDs, consent, download ownership and purchase/export behavior remain unchanged.
The existing localization walk retains all four layout configurations and adds French-Default
title/variation assertions. Existing lifecycle assertions now explicitly select English through
process-local launch arguments; this does not change the phone's saved language, and the French
walk overrides it. The Studio install shortcut is preserved.

The September 9 physical shortcut attempt `ios-xcui-model-download-20260909-184917-6c9a0b0a`
failed at automation-mode bootstrap: zero test cases launched, no model transfer started. The
failed xcresult/logs, formal bootstrap classification and safe-stop checkpoint remain untracked.
No automatic retry occurred; the requested fresh attempt could not fit the remaining phone window.
This is infrastructure failure, not product acceptance. ISU-4 remains in flight pending a freshly
authorized shortcut run and Settings visual/layout acceptance on the updated source. No phone,
transaction, account or release operation is part of this polish checkpoint.

Focused verification: 33 Settings/localization Python tests pass; the iOS app and logic target
compile with the generic physical-device SDK, and the actual app plus updated XCUITest bundle
pass build-for-testing. A direct comparison of the compiled app's English and French string tables
matches all 53 reviewed keys against the source catalog. Raw logs are retained under the governed
foundation/iOS artifact roots with the `settings-polish` prefix. One test-build invocation was
stopped after an incorrect cache variable selected Xcode's default location; the successful
replacement uses the validated repository-owned cache. No existing cache was deleted. These
results establish source/build coverage, not visual or interactive device acceptance. The local
project-input gate passed, including 122 plus 1,590 Python tests (1,712 total); localization,
control inventory and derived-artifact validation passed. No full native macOS suite, purchase
transaction or device execution was rerun for this presentation-only continuation.

### September 9 Studio install shortcut — source implementation

The missing-model button now captures the current mode's model, opens Settings → Models & Files
→ Voice Models and requests installation through the existing app-lifetime installer. It does not
change Studio drafts or start generation; ordinary Settings navigation and Back never replay the
request. All existing model-delivery checks, queueing, progress, cancellation and error UI remain.

Native routing fixtures cover every mode and navigation without repeated installation. Source-bound
tests cover the actual three CTA callbacks, root path and installer connection. The existing isolated
model-download acceptance scenario now begins each of its three model installations from Studio;
it retains cancellation, adoption, removal and canonical-state restoration checks. No physical run
or real model download was authorized or claimed by that implementation-only checkpoint; the later
authorized bootstrap failure is recorded above. Focused verification passed: 105
Python navigation/control tests and two native routing tests. The actual iOS app and updated
XCUITest bundle passed generic physical-device-SDK build-for-testing without installation or
execution. Compile evidence is retained as `ios-studio-install-uitest-build.log` in the foundation
artifact root; the coherent repository checkpoint is retained as
`studio-install-checkpoint-20260909.log` in the macOS artifact root.
ISU-4 remains in flight: this shortcut needs live acceptance, and the separate retained
AX-L About reveal failure still needs diagnosis. No durable AGENTS.md procedure changes are needed.

### September 9 publication checkpoint

Committed and pushed the complete Settings/purchase/credential-hygiene patch as `3247b566` on
`main`. The resumed deterministic checkpoint passed: 122 focused plus 1,588 full-discovery Python
tests, all native core/transport/runtime suites, generic iOS app/logic compilation and macOS app
build. The interruption's missing completion receipt was not treated as PASS; a complete replacement
checkpoint is retained untracked as `commit-checkpoint-20260909.log` in the macOS artifact root.
GitHub exact-SHA CI/Security completion is not established by this local checkpoint or push.

ISU-4 and RF-13 stay in flight. The next bounded task is the AX-L About reveal boundary and then
the missing Settings layouts; actual offline, remaining export surfaces and processed-candidate
purchase acceptance remain separate. The roadmap update follows publication; existing device
evidence keeps its original source identity. No phone, account or release operation was performed.

### September 9 follow-up physical QA — local purchases PASS; Settings still incomplete

The authorized two-hour session ended well before its deadline. Source and documentation stayed
frozen through both independent runs; no automatic retry or production change occurred.

- `ios-xcui-localization-20260909-170023-1a55e996` failed after 146.7 seconds. Default
  Audio/About/Voice Models and AX-L Audio assertions completed; AX-L About navigation failed in
  the shared reveal helper. Six named captures and the actual final hub screenshot remain retained.
  The About row appears visible above the dock, but exact row/dock query frames were not retained:
  a geometry-boundary explanation is a hypothesis, not a proven product defect. AX-L About/models,
  AX-XXXL and pseudo-AX-XXXL remain unverified. Crash collection and source checks passed.
- `ios-xcui-purchase-20260909-170541-2f432ab1` passed all 23 local StoreKit phases in
  295.8 seconds. The corrected owned/product-unavailable guidance is visible and asserted;
  owned/revoked History and full-player routes passed for all three modes. Complete runner ledger,
  source, crash delta and schema-3 restoration passed. Test transactions were cleared, original
  History filter/tab restored and Vocello terminated. No real charge, transfer or generation occurred.

Visual inspection confirms clearer icon/Back sizing on Default screens and vertical switch reflow
on AX-L Audio, plus consistent ordinary-size purchase messaging. It does not establish larger-size
or comprehensive bilingual acceptance. The extended unavailable-product text scrolls; complete
footer visibility was not independently exercised. Raw screenshots may contain personal History
and remain untracked. Local fixture pricing is not the live product price. Actual offline,
App Store sandbox and processed-candidate purchase acceptance remain separate open requirements.

Next under ISU-4: retain the failure, capture actual row/dock geometry at the existing navigation
boundary, correct demonstrated reachability and then run the incomplete layout configurations with
fresh authorization. Preserve strict full-layout assertions. RF-13 retains the remaining purchase
acceptance surfaces. Initial preflight's stale preserved dSYM was re-synced with the existing
UUID-validating helper; no cache purge or product change was needed. This post-collection narrative
changes full-tree identity and does not relabel either run as future candidate evidence.
No AGENTS.md change is needed. Device work has stopped; the phone may be taken or locked.

### September 9 focused Settings follow-up — implementation, not renewed device acceptance

The bounded QA findings are corrected in source: decorative icons fit their slots, Back chevrons
fit existing 44-point controls, and accessibility-size switches reflow vertically without capping
text. Purchase notices now distinguish unavailable product information from an existing verified
export unlock, with English/French copy; entitlement and export decisions are unchanged.

The unchanged dock now exposes its real containing accessibility frame. Shared Settings reveal and
layout assertions use that whole boundary with four-point clearance, not the lower Settings button.
Only explicit oversized navigation may use a safely visible central 44-point band plus hittability;
ordinary controls and layout checks retain full-frame visibility. Native geometry fixtures include
the previously false-passing two-row dock, oversized navigation versus layout, boundary and invalid
frames. The physical layout walk now checks and captures Auto-play clearance before variation;
the purchase lane asserts owned/unavailable wording without rerunning any transaction here.

Focused verification passed: 123 Python tests and nine native geometry/presentation tests, with
zero failures. The complete `scripts/dev.sh checkpoint` then passed: 1,710 Python tests, 611 core,
19 transport and 125 runtime tests (three optional fixture-dependent skips), project contracts,
derived validation, macOS app build and generic iOS app/logic compilation. The updated iOS XCUITest
bundle separately passed generic device-SDK `build-for-testing` without installation or execution.
Native evidence remains under `mac-test-20260909-124931`; the compile log is retained in the governed
foundation artifacts. Existing advisory documentation/roadmap freshness warnings remain; this is
not a warning-free global audit. This final narrative update is documentation-only.
No phone run, real transaction, account change or release operation is part of this patch.
ISU-4 remains in flight pending fresh authorized visual/device acceptance;
the failed/partial Settings runs and prior 23-phase local purchase PASS below retain their original
source identities. No AGENTS.md change is needed for this scoped implementation.

### September 9 repaired-source device QA — purchase PASS, Settings stress failure

The maintainer paused `ios-xcui-localization-20260909-155529-2eeb7f10` after the Default
captures, then explicitly resumed after enabling Do Not Disturb. That partial run remains failed
and retained. No purchase test started before the pause; no original evidence was overwritten.

New `ios-xcui-localization-20260909-160056-aecc5f90` completed Default, AX-L and AX-XXXL
Audio/About/Voice Models assertions. Pseudo-AX-XXXL reached Audio and About, then failed revealing
Models & Files at 417.4 seconds. Eleven named PNGs plus the actual last-observed hub screenshot
remain untracked. The expanded row exceeds the visible viewport, while the helper requires its
entire frame above the dock: the failure does not establish that a user cannot tap the visible row.
Crash collection passed; no automatic retry followed.

Visual review additionally found real large-text defects: decorative symbols overlap labels
(already apparent at AX-L), the Back chevron outgrows its circle at AX-XXXL, and the Audio switch
column leaves excessive text wrapping. Default-size surfaces are restrained and readable.
The existing dock assertion and shared reveal use the Settings button's top, which is in the
second dock row at accessibility sizes; the AX-XXXL About version value is visibly obscured by
the dock despite completed assertions. Fix this verification false positive against the whole
dock boundary while distinguishing genuinely oversized rows from unsafe taps. The shared purchase sheet is clear
in its ordinary states, but owned access plus a product-loading failure shows conflicting guidance
about whether audio can leave Vocello. ISU-4 owns these bounded presentation corrections;
entitlement/export behavior must remain unchanged. Oversized-row actionability and actual layout
clearance need separate assertions, not an unexplained weaker PASS rule.

Independent `ios-xcui-purchase-20260909-160916-be0d2715` passed all 23 local StoreKit observations
in 294.6 seconds. Schema 3 verified transaction deletion, the observed original History filter and
tab restored, and app termination/Home. Runner source, crash, purchase-validation and retention
steps all passed. Owned/revoked History and full-player export routes passed for Built-in, Design
and Clone, with sharing cancelled and internal playback retained. No real charge, account edit,
outward transfer, model installation, generation or personal-data deletion occurred.

Both completed runs used HEAD `d7efc09f` plus the preserved uncommitted patch; the purchase source
receipt records matching before/after fingerprint
`114eb6d1c2551ddab240e0f44a1f0100f15ba7cf8fb5c4ba27aab392a7480e78`.
This is local StoreKit on a development build, not actual offline, sandbox or processed-candidate
acceptance. Tests have stopped. The documentation checkpoint after collection changes full-tree
identity; retained results remain bound to their original receipt, not a future candidate.
Remaining visual gaps include full English/French hub/category coverage, purchase accessibility
sizes, measured contrast, VoiceOver and reduced effects. Two independent source/screenshot reviews
inform the findings but do not substitute for those tests. No production fixes were made during QA.

### September 9 Settings and purchase device tests — partial, stopped

Separate device authorization followed the source-only handoff. The first localization run
`ios-xcui-localization-20260909-145907-475352f1` failed automation bootstrap with no launched case.
After explicit readiness, `ios-xcui-localization-20260909-150453-f2271f1e` ran for 258.8 seconds:
Default and AX-L assertions completed; AX-XXXL Audio/About completed, then Models & Files navigation
failed. The hub retained its bottom scroll position after Back, while `openSettingsPage` asked the
shared helper to swipe only upward for a row above it. Source and the last observed screenshot
confirm a harness reachability defect, not a product navigation verdict. Pseudo-AX-XXXL was not reached.
The final failure image was listed but not materialized by attachment export; the preceding actual
hub screenshot and original xcresult remain retained. Do not invent the missing image.

Independent `ios-xcui-purchase-20260909-151016-dd80ec09` ran for 97.6 seconds and recorded 11 local
StoreKit phases: environment, initial lock, restore-not-owned, cancellation, purchase, relaunch
entitlement, restore, revocation, pending, approval, and owned product-unavailability. It then timed
out selecting a History filter; the retained failure screenshot shows Messages foreground. The
exact trigger is unknown. This is an interrupted launched test, not bootstrap failure or evidence
of a purchase-policy defect. Export checks did not complete. Product-unavailability was simulated,
not actual offline access. No real purchase or account mutation occurred.

The local transaction cleanup and app termination checks passed; however, the background-app path
skipped original-tab restoration, so the result's cleanup flag does not establish full UI restoration.
Both runs remain FAIL and separate from historical passes. Private screenshots, observations, logs,
and xcresults remain untracked; no automatic retry was made. Device testing is stopped.
ISU-4's follow-up repair now uses one shared geometry-directed Settings reveal for layout and purchase
tests, including retained scroll positions and a bounded fallback for missing frames. Fully visible,
hittable controls and the four-point dock clearance remain required. RF-13 cleanup now records each
restoration dimension, restores the observed original History filter rather than assuming All, and
reports skipped-background restoration as incomplete without taking over another foreground app.
Current schema 3 and the runner reject aggregate cleanup claims without observed restoration;
historical schema 1/2 remains readable but cannot qualify new runs. This changes only test support
and evidence validation, not Settings or purchase behavior. Native policy regressions and host
collector fixtures cover direction, exhaustion, missing frames and false-success restoration.
Verification: 56 focused Python tests passed; all five `UIInteractionPolicyTests` executed and passed
on macOS. The actual `VocelloiOSUI` target passed generic physical-device-SDK `build-for-testing`
with signing disabled, using the governed iOS cache and package lock; no phone test was launched.
These results establish source/fixture correctness, not a physical navigation or purchase PASS.
The first full checkpoint caught one older control-audit assertion bound to the moved private
helper; it now verifies the shared call path and the same complete dock-clearance requirement.
Fresh physical layout and export runs remain required. English/French,
remaining layouts, VoiceOver/reduced-effects and live/processed purchase acceptance remain open.

### September 9 Settings handoff — source refinement, physical acceptance pending

ISU-4 reopens the existing Settings plan for the requested six-entry hub and shared purchase-sheet
refinement. Five destinations retain the original bindings and navigation stack; Models and licenses
now return through Models & Files and About. All original controls retain their identifiers, with
explicit category/header/Back ownership added to the existing smoke/control-audit helpers. Folder
selection, consent, generation, commerce ownership and output-provenance policy are unchanged.
New Settings/purchase copy has English/French catalog coverage; Buy uses only StoreKit's price.

The supplied brief and all seven reference images were reviewed; decorative mockup details and
placeholder prices were not adopted. Earlier credential-hardening and local purchase-acceptance
work in the checkout was preserved. Generic iOS app/logic compilation passed; `scripts/dev.sh focused`
passed 123 tests plus project regeneration and whitespace validation. Settings/navigation,
localization and purchase-state checks precede `scripts/dev.sh checkpoint`; its exact-tree receipt
and full logs remain in the existing untracked development output, not physical acceptance evidence.
At this source-only checkpoint no phone UI, transaction, account operation or release action was performed. Current-layout visual,
VoiceOver, English/French, accessibility-size and reduced-effects acceptance remains separately
authorized work under ISU-4/RF-13. September 8 purchase results below remain historical evidence,
not a claim that this changed UI has passed physical acceptance.


September 7 **release-forward decision:** the maintainer has deferred further English long-form
causal research. RF-06 remains a **known limitation, open and not fixed**. Its original failed
audio/code trace, exact seed/receipts, independent-decoder reproduction and inconclusive generating
cause remain retained below. No cap, seed, model, prompt, retry or QC policy changes follow.
The remaining French/Chinese findings are separate; none is cleared by this scheduling decision.

The retained joined-History mismatch is resolved as fixture-only trailing whitespace. The separately
authorized clean-source smoke `225523-62a57c2f` now passes recovery, all four layouts and long-form
regeneration. The prior notification-interrupted run remains FAIL with its two whole-output warnings;
the later PASS does not erase those attempts or establish the cause of their audio defects.
Exact hard-QC-error recovery and complete byte-level accepted-output preservation remain partially verified.
Use the required 201-take campaign for incidence/workflow impact, not another research matrix.
RF-09's unexpected tensor-transfer Analyze warning is corrected; exact-source candidate freeze
still precedes the full campaign. Development recovery tests do not substitute for that candidate gate.
The iOS one-time Design/Clone export unlock now has source implementation under RF-13, before RF-09
freeze. Finish physical StoreKit/sandbox purchase/export acceptance and RF-02's remaining metadata/account work
before creating the final candidate or starting its 201-take campaign. Generation,
listening and internal History remain free in all modes; Built-in output export remains free.
Finish independent submission-material preparation through the existing RF-02 packet. Unresolved
required failures still block clean promotion; accepting a shipping risk requires a separate
documented decision, not relabeling the failure or declaring this issue resolved.

### September 8 physical export access — History/player PASS

The authorized extended local StoreKit scenario is `scripts/ui_test.sh ios purchase --scenario
exports --retain-result`. It reuses existing History clips without generation, editing, saving,
deletion or outward transfer. One visible-provenance row per mode is reused for the owned/revoked
comparison. Twelve checks cover History-menu and full-player sharing for Built-in, Design and Clone:
owned sharing reaches the real system sheet; after revocation only Built-in remains free and the
paid modes show the purchase sheet. Every share sheet is cancelled, and internal playback/pause
remains available in both states. A simulated Apple product-loading network error additionally
proves owned access survives relaunch without product availability. This is **not actual offline**
or App Store sandbox evidence.

Run `ios-xcui-purchase-20260908-182510-490db279` retained the product-unavailable PASS but failed
before route checks because SwiftUI propagated the History container identifier to each filter.
Run `ios-xcui-purchase-20260908-182939-20a4ccb2` then reached the real share sheet but failed on
its French Close label; the modal also prevented tab restoration, so aggregate cleanup remained
failed despite app termination/Home. Both are preserved as failed harness evidence. Queries now
bind each filter's observed identifier plus unique English app label and the system share sheet's
language-independent `header.closeButton`. Cleanup closes modals and verifies the original tab.
No production UI, purchase, export, network setting or account behavior changed.

Run `ios-xcui-purchase-20260908-183242-f3b9c6e4` **passed** all 23 ordered observations in 305.2 s,
with full runner result validation, crash delta, retention and cleanup. The next session's empty
transaction baseline independently confirmed no prior local transactions remained. Test-owned
transactions were removed, History filter reset, original tab read back selected, Vocello stopped
and Home restored. Raw screenshots/History content and all original results remain untracked.
Schema 2 is selected explicitly by the exports scenario; schema 1 lifecycle results remain valid
only for that earlier scope. Neither schema grants offline/live or complete export-surface authority.

RF-13 remains open for real disconnected-device entitlement behavior; Studio inline Save/Download,
automatic Files-folder copies, individual long-form segments, generated Saved Voice and original
reference recovery, and failed-storage exports on test-owned fixtures. These require preserved
draft/folder/reference setup rather than changing personal content or fabricating History. RF-02
retains missing IAP metadata/availability/agreements and sandbox-account setup; RF-12 retains the
separately authorized signed/uploaded processed candidate. No qualified archive/IPA evidence was
found in the local release-output locations inspected. Do not replace those gates with this local PASS.

### September 8 local physical purchase lane — lifecycle PASS

Added the explicitly authorized `scripts/ui_test.sh ios purchase --retain-result` route to the
existing XCUITest stack. Apple StoreKitTest and the TEST fixture live only in the UI-test target;
no production unlock, live transaction, account change or shipping resource was added. The lane
checks local environment/price and ordered purchase lifecycle observations, with test-owned
transaction cleanup, app termination and strict result validation. It does not qualify sandbox,
TestFlight, offline access or every paid/free export route.

The focused Python checks passed (38 tests), and the iPhone app/test bundle compiled and signed.
Physical run `ios-xcui-purchase-20260908-172652-033d58e4` failed while Xcode enabled automation mode,
before any test case launched. The existing classifier confirmed `infrastructure_bootstrap_failure`
with zero launched cases; the runner-level failed entry is not a purchase failure. Source receipt,
failed xcresult, log, required-step ledger and clean crash delta remain retained and untracked.
No transaction or purchase-sheet action executed in that first run. Two earlier host-only invocations refused the
new lane's missing storage registration before build/device launch; registration and its regression
test are now complete. No automatic retry occurred.

After the maintainer manually unlocked XCUITest, run `ios-xcui-purchase-20260908-173201-30e6025b`
proved local environment, initial lock, restore without ownership and simulated cancellation.
The following positive purchase failed after clearing the injected cancellation. Retained screenshot
and accessibility evidence show the safe failure message; cleanup passed. The isolated follow-up
reads back the cleared error and resets Apple's session options between fault and success arms.
No production StoreKit/state/export code was changed.

Run `ios-xcui-purchase-20260908-173442-91a8ea73` then **passed** all ten ordered observations:
local environment, initial lock, restore without ownership, cancellation, purchase, relaunch
entitlement, restore, revocation, pending approval and approval delivery. The native XCUITest took
58.7 seconds. The full runner passed result validation, crash delta, dSYM retention and the required
step ledger. All test transactions were removed, the original tab was tapped, Vocello terminated
and Home restored; the phone is no longer in use. The built application contains no StoreKit fixture.
Every original failed run remains retained separately; this is **local StoreKit on physical hardware**,
not an App Store sandbox charge, processed-candidate acceptance or proof of offline/all export routes.
The bounded comparison implicates test-session fault isolation; it does not establish a production
purchase defect. RF-13 remains in flight for remaining route/offline/sandbox coverage, with RF-12
owning processed-candidate purchase proof. No real charge, account mutation or personal-data deletion.

### September 8 credential hygiene hardening

The scoped credential review found no exposed credentials among 1,526 tracked files and 12,504
reachable historical blobs across 1,537 commits; common-signature matches were fixtures, environment
references and ordinary text. GitHub reported secret scanning/push protection enabled and no alerts.
This does not cover secrets concealed in images/encoded content, deleted remote history or every
published artifact; no credential rotation was indicated by that review.

The two identified prevention gaps are corrected: credential-file ignore patterns and owner-only
creation/failure cleanup in the existing macOS/iOS release workflow. Setup refuses existing target
files, records cleanup ownership before side effects and handles partial import/copy/cancellation;
final cleanup attempts remaining paths even after a deletion failure. Existing supply-chain tests
now execute the workflow blocks with dummy credentials and stubbed Apple tools, including deliberate
permission/trap regressions. No real credentials, Keychain, account, signing, release or phone operation
was used. Exact-tree checkpoint evidence owns the final verification; RF-02/RF-13 purchase and
submission dependencies remain open. The earlier uncommitted open-source documentation is preserved.

### September 8 open-source purchase decision

The maintainer approved retaining MIT source and the official iOS-only StoreKit export unlock,
accepting that self-built forks can change local checks. README and the iOS guide now explain the
free/paid and official/self-built boundaries; SECURITY.md owns credential separation and the explicit
local-client threat boundary. No license, product behavior, backend, obfuscation, account setting or
phone state changed. Inspection of the existing adapter/state and export contract confirms the current
architecture already fits this decision; this is not a repository-wide secret audit or purchase proof.
RF-13 remains in flight for physical StoreKit/sandbox acceptance and RF-12 for processed-candidate proof.

### September 8 approved purchase and regional pricing setup

With explicit maintainer authorization, created the non-consumable **Design & Clone Export** using
`com.patricedery.vocello.design_clone_export`. Apple rejected the earlier hyphenated identifier;
the empty inventory was verified before the corrected, separately approved creation. Source and
the non-shipping TEST fixture now use the valid identifier, with a format regression assertion.

Readback confirmed the USA/USD base, one manual **19.99** base price and Apple-managed automatic
price schedules for 174 other territories (178 schedule records, including dated transitions).
No regional override, app download price, availability, agreement, submission or phone state was
changed. Family Sharing was not enabled; its field is omitted by the API readback and remains a
UI verification detail. Raw account receipts remain private/untracked. Product state is
**MISSING_METADATA**, not reviewed or purchase-qualified. RF-02 retains localized metadata,
availability, agreements and qualified decisions; RF-13/RF-12 retain physical/processed purchase proof.
The TEST fixture price remains deliberately separate from the live offer; production shows StoreKit's
localized price, never a hard-coded currency conversion.

### September 7 phone-independent export purchase implementation (historical)

RF-13 now has one StoreKit adapter, one observable purchase-state owner and one outward export
boundary. Studio/full-player/History/segment sharing and automatic folder copies use the finished
output's mode. New Design-derived Saved Voices retain their origin in additive enrollment metadata.
Original and legacy unclassified references remain freely recoverable; actual storage-failure
recovery does not demand payment. No voices, clips, preferences, models or phone state were changed.
Generation/playback/internal History and Built-in exports remain free; macOS/CLI are unrestricted.

The proposed ID is `com.patricedery.vocello.design-clone-export`. The unactivated, non-bundled
StoreKit fixture's TEST name/price are not a live offer or a maintainer-approved price. RF-02 still
owns final ID/name/price/Family Sharing, live setup and account/privacy decisions. No ASC call,
purchase, account edit, signing operation or device test was performed for this patch.

Deterministic purchase/provenance tests and route-wiring fixtures are implemented; generic iOS app
and logic-target builds pass. The coherent checkpoint must be current before publication.
The stateful control audit now inspects/dismisses purchase options but records transaction actions
as blocked until separately authorized StoreKit/sandbox acceptance. RF-13 remains in flight, not
purchase-qualified. Its physical export/purchase tests precede RF-09 freeze and the 201-take run;
RF-12 additionally requires processed-candidate proof. Earlier audio findings and device evidence
remain unchanged and are not acceptance for this new source.

### September 7 passing smoke and monetization scheduling (historical)

Clean `3272d17e5e008ab5c1a09304a18917efb9d68659` passed the explicitly authorized smoke
`ios-xcui-smoke-20260907-225523-62a57c2f`, with matching full-tree fingerprints
`9183d03b65c16b41030977a98d53fe2777fcd45e6f0fa0aa2f2f36d3e5df0dc9`.
The complete runner and required-step ledger pass with no failed or missing steps. Raw results,
audio and observations remain in the pinned untracked run bundle; this documentation checkpoint
changes tree identity and does not relabel that evidence as a new candidate run.

- Recovery PASS, 249.407 s: user cancellation, ordered forced-memory cancellation/unload,
  subsequent completed generation and one completed History entry; cancelled requests absent.
- Four layouts PASS, 288.442 s: default, AX-L, AX-XXXL and pseudo-AX-XXXL.
- Long-form/regeneration UI PASS, 622.986 s: grouped segments, exact initial/replacement
  transcripts and retention of the prior joined History IDs. Not every old audio byte or
  injected failure-path recovery was tested by this journey.
- Seven engine attempts: two cancellations and five EOS/published outputs. Durations are
  4.96 s for recovery, 55.84 / 50.00 / 27.44 s for initial segments, and 54.00 s for replacement.
  All five whole-WAV/written-output QC verdicts pass with cadence `withinFastGate`.
  Thirteen chunk warnings remain (seven `low_level`, six `cadence:excess1(1/0)`); this is not
  independent ASR, semantic promotion or a claim of warning-free audio.
- Crash snapshots match; independent post-collection process inspection found no Vocello or
  test-runner process. Focus preparation was user-confirmed, not independently read back.
  No agent screen/notification mutation, automatic retry or 201-take cell occurred.

GitHub [CI](https://github.com/PowerBeef/Vocello/actions/runs/34167970141) and
[Security](https://github.com/PowerBeef/Vocello/actions/runs/34167970151) both completed successfully
for `3272d17e`. This is exact-commit evidence, not CI for subsequent edits. Read-only candidate
preparation confirms source 3.0.0/build 24, available iOS platform support and one valid local
identity each for Development, Distribution and Developer ID. The platform query required the
normal outside-sandbox route; the initial sandbox runtime-service error is not a product defect.
The quality-promotion contract validates. Profile payload/emitted entitlements, unused build number,
signed archive/IPA and processed candidate remain unverified. No API-key access or account mutation
was needed; defer the fresh collision/account check until actual archive preparation rather than
pretending build 24 is reserved. No candidate tag, signing or upload occurred.

The maintainer's intended iOS business model is one non-consumable purchase unlocking export of
Voice Design and Voice Clone output, with all other functionality free. RF-13 now owns implementation
and focused verification; RF-02 owns product/account setup and RF-12 processed purchase acceptance.
Price, final product identifier, purchase display name and Family Sharing choice remain to be set.
This checkpoint records the scope, not purchase implementation or authorization to create products,
change prices or accept agreements. The maintainer explicitly confirmed iOS-only monetization and
App Store submission; macOS remains distributed through GitHub Releases with unrestricted exports,
and the CLI gains no paywall. Shared export code must preserve that platform boundary. The subsequent
implementation checkpoint above supersedes this planning-only state; existing audio limitations stay open.

### September 7 transcript and Analyze corrections

- Read-only XCUITest `214509-5facda49` opened the exact retained test-owned History row without
  synthesis. Its 2,130-character value matches the earlier 2,131-character fixture **exactly after
  removing its final ASCII space** (SHA-256
  `305f0baad162d0c60a148237419c772638f1c4854fe77b94ebc22d8e8068f000`). No words were lost.
  The new focused observation route uses the existing smoke runner and leaves raw text untracked;
  its verdict is observed, not full smoke or audio acceptance. The original failed run is retained.
- The fixture now trims its final separator before entry; observed History values still require
  exact equality. The existing Clear-button helper also handles empty searches without relying on
  caret placement or placeholder values. Mismatches retain the actual value before player dismissal.
  Twenty planner tests pass, including joined-word/punctuation preservation versus trailing whitespace.
- Compatibility `AudioGeneration.audio` now owns materialized `[Float]`; all four Qwen producers
  materialize before yielding, and the sample proxy no longer evaluates transferred MLX tensors.
  The native production-constructor/proxy/task-transfer regression passes. Shipping actor-owned
  synthesis, sampling, model pins and QC are unchanged; no Sendable suppression was added.
- Release Analyze recompiled the changed boundary successfully: its enum warning disappeared.
  It exposed an unassigned PNG identical to the assigned 1024px icon. The redundant catalog copy
  was moved to untracked evidence; the assigned icon is unchanged and Git retains its history.
  Asset-inventory/negative-warning tests pass. The subsequent incremental Analyze and warning
  gate pass with zero emitted warnings; this is not a claim that all 19 reviewed compatibility/tool
  warnings disappeared from a fresh full rebuild. Exact signed-artifact verification stays pending.

Physical smoke `220711-845f7f36` retained a matching pre/post source fingerprint
`b2dfcb64b2fad0c39d80533fb57918cb304ee9b85ca376e1f4c92f2dcb5246ad`:

| Case | Result and boundary |
| --- | --- |
| Recovery | FAIL, 181.231 s. Visible cancellation completed. SpringBoard recorded a notification banner interrupting the editor tap; typing then failed without keyboard focus. Forced-memory generation and post-pressure reuse were not reached. This is an interruption-affected test, not bootstrap or audio-engine failure. |
| Four layouts | PASS, 294.167 s: default, AX-L, AX-XXXL and pseudo-AX-XXXL. |
| Long-form/regeneration | UI PASS, 595.369 s: joined completion, exact transcript, grouped segments, one explicit regeneration, exact replacement transcript and retained prior joined History IDs. This does not prove every old audio byte or failure-path restoration. |

Collected engine evidence represents one cancelled request and four EOS outputs. Initial segments
are **53.76 / 55.84 / 27.84 s**; the explicit replacement is **60.96 s**. First/third segments have
persisted-WAV QC PASS. The second and replacement retain **1,628 / 1,878 ms dropout warnings**
and `unusual` cadence (`single_suspicious_pause`); both were published under the unchanged warning
policy. No hard QC rejection occurred, but these warnings block a clean audio-promotion claim.
Record them under RF-06; no retry, seed substitution, new causal conclusion or broad research follows.

The overall runner and terminal ledger remain **FAIL** (`xcuitest`, `smoke-diagnostics` failed;
no missing required steps). Diagnostics correctly reject the absent forced-pressure event instead
of fabricating it. Crash hashes match; a post-collection process query found no Vocello/test-runner
process. Raw results/diagnostics are pinned and untracked. No screen settings changed. No 201-take
cell, candidate tag/archive/upload or submission ran. AGENTS.md's durable procedures remain accurate.

The exact-tree `scripts/dev.sh checkpoint` receipt owns the deterministic verdict for that patch.
The later separately authorized uninterrupted recovery run is recorded above. Keep this aggregate
failed run and its warnings historical; the new PASS does not change its verdict.

### September 7 physical recovery checkpoint

All runs used the canonical physical-iPhone smoke lane and retain their own source fingerprints,
logs, result bundles, diagnostics and terminal required-step ledgers. They are separate attempts,
not an automatically retried or combined PASS:

| Run suffix (all September 7) | Outcome |
| --- | --- |
| `201825-9356e2d1` | Automation bootstrap failure; zero real test cases launched. |
| `202239-b4e9b670` | After explicit user unlock: recovery and four layouts passed; long-form stopped before Generate because caret-dependent search clearing left old text. |
| `204407-d88669f8` | First helper correction wrongly required a readable value for an empty field: two harness failures, layout PASS. Retained, not erased by the next correction. |
| `205513-1be7eb7e` | Corrected search: recovery PASS (249.395 s), four layouts PASS (287.741 s); long-form completed audio but failed the joined-History transcript comparison (424.580 s). Segment regeneration not reached. |

The final helper uses the genuine search-only Clear button and waits for its conditional
disappearance before typing once. Exact query equality remains required. Its 82 focused Python
checks pass, and the final physical run proves short and 2,131-character query replacement.
The final frozen run fingerprint is
`92b6295239e856925675caf217bca4a788cd5b787437e44f892a8718f5db3af3`;
these subsequent documentation edits are a new checkpoint, not identical campaign source.

The three long-form segments reached EOS, with durations **52.24 / 50.72 / 25.04 seconds**,
persisted-WAV QC PASS and cadence `withinFastGate`. The joined player appeared and before/after
History censuses preserved prior matching IDs. This is not full-WAV ASR/prosody qualification or
a fixed-seed confirmation of the original RF-06 failure. The original evidence remains unchanged.
At that checkpoint the full-player comparison did not retain its observed value, and trailing
fixture whitespace was only a hypothesis. The later read-only observation above proves that
explanation without regenerating the retained output; the original run still remains failed.

The final runner remains **FAIL**, with only `xcuitest` failed and no missing required step.
Recovery diagnostics pass; their intentionally forced critical-memory/full-unload event is not
clean memory-promotion evidence. Before/after collected crash hashes match. A successful read-only
process query after collection found no Vocello or test-runner process. Personal models/voices were
not deliberately removed; this smoke lane does not establish byte-for-byte restoration of all
personal state. No screen settings changed, as requested for this session.

No full-campaign cell ran: the prepared 201-row snapshot (91 Built-in, 80 Design, 30 Clone) is
preparation only and must be regenerated after RF-09 freeze. RF-02's existing consolidated packet,
support/attribution contracts and release notes were reviewed; qualified decisions, account changes,
candidate authorization and signed/processed-candidate evidence remain outstanding. No account
mutation, upload, release or submission occurred.

### Completed sampler investigation

September 7 **production sampler / predictor follow-up** completed the two bounded Mac experiments
recommended after the external review. No phone was used. Diagnostic allocator setup now consumes
a digest-bound export from the actual host `NativeMemoryPolicyResolver` before model load and
restores prior limits after model ownership ends. This is a diagnostic correction, not an audio fix.

- **Experiment A:** the same original request/seed through the production producer, once without
  and once with internal sampling observation. All **600 × 16 codes match** between these two arms.
  The new Mac trace first differs from the original iPhone trace at zero-based **frame 1, codebook 8**
  (predictor pass 7), well before the old silence. No Talker processed row contains NaN; EOS has
  nonzero probability after its two-frame minimum. The longest new first-codebook run is four
  frames, not the original sustained collapse. Both captures deliberately stop at 600 frames;
  neither is EOS, complete synthesis, PCM acceptance or proof the original issue is fixed.
- **Experiment B:** teacher-force the new history at frames 0–2 through all 15 predictor passes
  using shipping quantized weights/bfloat16 activations. All **45 complete logit comparisons are
  exactly equal** eager versus compiled and versus the captured production values. No predictor
  arithmetic/cache correction is supported at this early boundary. This remains a shared-weights,
  same-platform comparison, not independent Talker or original-device numerical parity.
- **Resources:** all three processes exited and stayed below 5 GiB (about 2.94 GiB sampled peak
  physical footprint). Observed and predictor arms pass their supervised resource envelopes.
  Baseline remains **unqualified** for a probe failure and +117,702,656 bytes host swap growth;
  retain that failure, not a claimed all-runs memory PASS. Inspected original/model files and
  full-tree source stayed unchanged during each run. Mac cache policy is 256 MiB, not the original
  phone's 128 MiB; platform/setup differences remain explicit.
- **Capture correction:** first-frame raw statistics accidentally flattened the whole prompt.
  Retained raw arrays allow a separately digest-bound last-position correction without replacing
  or regenerating either capture. New diagnostic records declare schema 2, raw shape and last
  position; a negative fixture covers this error and incomplete-frame classification.

The private `sampler-transition-20260907/` bundle under RF-06 recovery retains inputs, actual consumed
keys, full checkpoint logits, original outputs, resource failures and `analysis.json`. Nothing raw
is published. Production-sampler arithmetic/scratch/observer tests, deterministic overlapping async
request scopes (including exact keys), and all-pass fp32/fp16/bfloat16 predictor cache tests passed:
18 focused tests, one explicit model-dependent skip, zero failures. The earlier coherent native run
also passed. The final tree uses `scripts/dev.sh checkpoint`; its exact-source receipt, not these
diagnostic results, owns deterministic verification. No candidate acceptance is claimed.

**Investigation checkpoint (research now deferred):** RF-06 stays open. Stop after these two experiments; no sampling, cap, EOS,
prompt, model, decoder or QC policy change is justified. Missing original device distributions/keys
cannot be reconstructed. The next useful comparison needs matched conditioning/weight representation
and an independent Talker or bounded device-side early-decision capture; a new Mac take alone cannot
explain the old phone decision. French interior gaps, French recognition disagreement and Chinese
trailing silence/cadence remain separate blockers, not cleared by these English diagnostics.

### Earlier Talker replay

September 7 **Talker replay follow-up** inspected 600 original code frames without resampling,
decoding audio or using the phone. All inspected last-step logits were finite. At seven fixed
checkpoints, recomputing the identical complete history from a fresh cache also ranked the recorded
first-codebook value first. Inside the gap (frame 475), its raw probability is 94.394% cached versus
94.686% fresh; raw EOS probability is approximately 2.63e-7 versus 2.22e-7. The bad history already
strongly favors the repetitive continuation; gross incremental-cache corruption is not supported
at these checkpoints. This does **not** identify the earlier generation/sampling divergence that
entered that state, or prove intrinsic official-model failure. Raw logits precede sampling filters.

The opt-in `Qwen3TalkerReplayDiagnosticTests` uses production conditioning through internal access;
no new public API, product behavior, model, prompt or QC change. Model execution skips without
explicit private input. Parser/probability and adjacent sampler/compiled-predictor checks: nine
deterministic passes, one explicit model-dependent skip. Full candidate verification is not claimed.

The first diagnostic preflight failed before prediction: an inferred prefix length of 55 was wrong.
The corrected expectation is **56**: initial prefix = final KV offset minus (forward count minus one).
Independent tokenization and both original Mac/iPhone offsets agree. The failed preflight remains
separate; the corrected run took 27.74s at 3,147,828,128 bytes sampled peak footprint (2.93 GiB),
exit 0 and confirmed process exit. **Resource-unqualified:** probe failure and +390,133,186 bytes
swap growth; no resource PASS. Both runs preserved 12 original evidence files and 34 canonical
model files, plus unchanged full-tree identity during execution. Private evidence is retained under
`talker-replay-20260907/` and `talker-replay-20260907-corrected-prefix/` in the RF-06 recovery bundle.

**Then-planned follow-up (completed above):** inspect the earlier real generation/sampling transition, with bounded raw/post-filter
first-codebook and EOS evidence and request-local randomness identity against a matched control.
Original device probabilities/keys are missing. Do not change sampling or repeat decoder studies
on this conditional replay. RF-06 remains open; no new TTS or phone campaign was run.

### Earlier independent decoder localization

September 7 long-form gap localization is complete at the **generated-code boundary**, not a
production correction or full generator root cause. Two predeclared retained-code experiments used
the cached, pinned official Qwen CPU decoder; no new synthesis or phone work occurred.

- Complete trace, exact current weights: raw float reproduces an 18.475s gap at 33.488s versus the
  iPhone's 16.680s at 33.483s. Independent implementation/overlapping blocks reproduce the gross
  failure; exact durations and waveforms differ.
- Fixed direct-forward windows: frames 475–525 are entirely below the existing 0.001 floor with
  both current fp16 and archived fp32 weights (-73.66/-73.65 dBFS). The preceding speech window
  remains approximately -31.86 dBFS in both. Resetting context or removing fp16 rounding does not
  recover speech. Later repetition is also near-silent in both arms.
- The trace has no dropped/all-zero frames or adjacent duplicated complete frames, but its first
  codebook later repeats for 610 frames (48.8s) and for the final 570 frames (45.6s). Other groups
  continue varying. The gap/collapse precedes the token cap; raising the cap is not a supported fix.

**Then-planned follow-up (partially completed above):** inspect generation-side conditioning, finite logits, EOS probability and sampling around
the first collapse with exact request/seed identity and a matched control. Retained evidence lacks
those probability/state observations, so intrinsic model behavior versus a generation implementation
defect remains unresolved. Do not repeat platform/decoder/precision permutations, change prompts,
revert tokenizer weights, trim silence or waive QC from this finding. RF-06 remains in flight.

The three serial decoder processes took 67.11/8.10/8.70s; sampled footprint peaks were
2,207,762,664 / 1,934,149,672 / 1,695,057,768 bytes. All produced complete outputs and exit code 0,
with process exit confirmed, no pre/post pressure warning and no swap growth. **None is resource
qualified:** all failed host free-memory recovery; the fp32 window run additionally retained a
footprint-probe error and denied process-group signal (`cleanExit=false`, despite return code 0).
Its sampled peak is not a qualified whole-run maximum. Do not replace these failures with PASS.
All 12 inspected original device-evidence files and in-run full-tree identity remained unchanged. Evidence, hashes, synthetic
measurement checks and limitations are in `gap-localization-20260907/` under the existing RF-06
long-form recovery bundle. Production source and all previous attempts are untouched.

### Earlier corrected-memory confirmation

September 7 authorized corrected-memory confirmation is complete, **not an aggregate PASS**.
One same-code Mac replay completed both arms in 57.35 seconds at 3,970,451,736 bytes peak physical
footprint (3.70 GiB), below the unchanged 5 GiB ceiling. Exit was clean and independently confirmed;
455 footprint samples had no probe failure, pressure stayed clean before/after, and swap decreased
by 357,365,187 bytes. All 70 bounded allocator records validate the before-load 256 MiB policy and
zero cached bytes at every sampled post-clear boundary.

Resource qualification nevertheless fails `post-exit-memory-recovery-unqualified`: host free memory
was 69% before and 62% after 30 recovery snapshots/15.22 seconds, outside the existing five-point
tolerance. A later 63% reading is annotation only, not replacement evidence. This host-wide deficit
does not identify an allocation owner or prove a leak in the exited CLI. No threshold or observation
window changed, and no automatic second run was launched.

Both 163.84-second replay WAVs fail QC with the same 16.680-second gap at 33.483 seconds as the
original iPhone arms. All output hashes, source receipt, trace/tokenizer identity and partitions
authenticate. The Mac arms differ at only 1,320 PCM16 samples, by at most one quantization step;
Mac/iPhone waveforms are not byte-identical but the severe gap matches. This excludes an iPhone-only
or output-mode-only explanation, **not** the common decoder. Generated-code versus shared-decoder
causation remains the next audio decision; do not repeat the excluded platform-only comparison.

Evidence: `memory-policy-confirmation-20260907/` under the existing RF-06 long-form recovery bundle
(preregistration, resource/allocator records, WAVs, assessment and preservation proof). All 27 original
iPhone files and 291 prior Mac evidence files preserve bytes/mtimes; source stayed frozen during
the run. The phone was untouched. RF-06 remains in flight for unresolved audio and full memory
qualification; the 5 GiB replay-ceiling failure did not recur in this confirmation.

### Earlier implementation checkpoint

September 7 replay-memory correction is implemented and deterministically verified.
Cold replay applies the existing host allocator policy before model load (256 MiB cache on the
8 GB Mac), and passes that same policy through the facade to both replay arms. Each materialized
chunk becomes CPU samples before policy-owned cache clearing; decoder context and original/25-frame
partitions are preserved. Cancellation and observation failures reset decoder state. Bounded,
timestamped `codec_replay_memory` stderr records expose load boundaries and both arms' MLX
active/cache/peak counters; they are not physical-footprint measurements. The supervisor ceiling
stays 5 GiB. No new replay or phone run is part of this implementation checkpoint; a separately
identified supervised same-code confirmation is still needed before claiming memory qualification.

Verification passed: 32 focused host tests; the quick project-input gate (1,556 Python tests);
587 core, 19 transport and 113 runtime tests (two optional AudioSeal fixture skips, no failures);
CLI build/version validation; generic iOS app/logic compilation. The four new runtime tests cover
cache-on/off waveform parity at original-style and 25-frame partitions, bounded observations,
capture-failure cleanup, and mid-replay cancellation/reset. Artifacts: `mac-test-20260907-125419`
and `replay-memory-{cli,ios}-build.log` under the governed macOS test artifacts. Derived runtime
inventory/API baseline, roadmap and documentation were refreshed. No commit or push was requested.

September 7 host-contract follow-up is implemented: pause-list validation/schema now match the
native 256-entry bound; receipt v2 compares the plan with `storedLanguageSelection` while preserving
the resolved language and rejecting explicit-language drift. Legacy receipt v1 keeps its original
comparison. `validate-result --read-only` revalidated the complete retained iPhone bundle as
`diagnosed_failure` (1/1 represented, one failed), without rewriting its original runner failure.
All 27 original run files retain their bytes and modification times. The 63 focused host/cadence/
resource tests and refreshed CLI build passed; the new negative fixtures reproduced both defects
before repair. No native synthesis, decoding or audio-QC threshold changed in this follow-up.

The authorized single same-code Mac replay **did not complete**. The existing CLI verified the
source take/trace and pinned model files, loaded the model, then exceeded the supervisor's provisional
5 GiB physical-footprint ceiling: 5,390,092,808 bytes, with 2,118,186,434 bytes of swap growth, after
33.60 seconds. The supervisor terminated the owned process; exit is confirmed, post-exit free-memory
recovery passed, and resource qualification failed. Neither replay WAV was completed. Its retained
CLI report remains `started`; the external supervisor report owns the terminated outcome. This is
not evidence for either cross-platform audio branch, not a Jetsam diagnosis and not an automatic
retry. The full-tree fingerprint was unchanged during execution. No phone was used or unlocked.

Evidence is in the existing long-form recovery bundle's `host-contract-replay-20260907/` (read-only
revalidation, preregistration, resource report, 278 exact-PID footprint samples and preservation
proof). Allocation review found the cold replay's host-policy bypass and missing chunk cache clears;
the diagnostic-only correction is described above. Do not raise the ceiling or launch another
attempt automatically. RF-06
remains open for the cutoff/severe continuation and the unresolved French/Chinese findings.

September 7 corrected-source physical diagnostic is complete, **not an aggregate PASS**.
Run `ios-startup-reliability-20260907-154111-6a16585e` represented its sole planned cold take,
without retry: original input/seed/instruction/tokenizer receipts match, thermals stayed nominal,
memory pressure stayed healthy, and no system crash report appeared. Generation again stopped at
2,048 codes without EOS. Both original diagnostic-record defects are verified fixed on-device:
the take contains `audioQC: null`, and codec metadata survives into telemetry and the result.
The `post_generation_failure` classification is correct. All three collected artifact hashes
validate; the new producer-bound trace matches the earlier orphan's bytes. Historical records
remain unchanged and are not retroactively promoted.

Incremental and production non-streaming replay completed, each producing 163.84 seconds of audio
with the same severe 16.680-second interior gap starting at 33.483 seconds. These are replay QC
failures, not a final QC report for the incomplete original; common decoding versus generated-code
causation is still unresolved. Host validation then failed because `recordedInteriorPausesMS`
allows only 64 entries while the native producer is bounded at 256; replay records contain 159
and 158 entries. That host defect and the subsequently exposed Auto-language comparison are now
corrected and read-only revalidation is recorded above. Preserve the failed runner outcome;
structural validity does not clear the cutoff or severe silence. RF-06 remains open.

The exact diagnostic process was independently confirmed absent. Device evidence remains retained
because the failed-validation guard withheld artifact cleanup; personal data was not targeted.
The source fingerprint stayed unchanged throughout the diagnostic and screen-protection runs.
Registration, assessment and logs are under the existing long-form recovery bundle's
`record-fix-acceptance-20260907/`. French-compatible screen-protection inspection and three-minute
enable lanes passed; CoreDevice independently confirmed current `passcodeRequired: true` afterward.
No device UI followed final protection. No broader campaign
or automatic follow-on generation was started.

September 7 diagnostic-record remediation is implemented and deterministically verified.
The startup result encoder emits explicit null for absent final QC, adapter failures preserve codec
metadata, and the runner reuses shared artifact/classification interpretation. Token-limit failures
are distinguished from QC rejections. The existing device/CLI replay paths now support complete
captured token-limit traces without fabricated QC; portable replay requires receipt-bound text when
no recorded cadence expectation exists. The original failed run below is unchanged and still lacks
producer-authenticated codec identity. No phone, synthesis, prompt, cap, model or QC threshold change
is part of this repair. RF-06 stays open; see the
[record/replay procedure](reference/audio-qc-engineering.md#token-limit-diagnostic-records-and-replay).

Verification: 28 focused Python tests and 38 focused native tests passed, including the actual
Swift record encoder consumed by the Python host validator. The coherent-tree `scripts/dev.sh
checkpoint` passed: 1,552 Python tests, 587 core tests, 19 transport tests, and 109 runtime tests
(two optional AudioSeal fixture tests skipped; no failures), generic iOS app/logic compilation,
and the macOS app build. The separate CLI build and binary-version contract also passed.
Native artifacts: `mac-test-20260907-112538`; CLI log: `diagnostic-record-cli-build.log` under the
governed macOS test artifacts. Original take/result/codec hashes were rechecked unchanged.
The separately authorized corrected-source capture/replay is now recorded above. Do not
retry the historical row or claim product acceptance from these deterministic tests.

September 7 physical-phone RF-06 follow-up: exactly one separately authorized cold take reproduced
the original long-form cutoff at 2,048 code frames without EOS. Original text/instruction/seed,
English routing and tokenizer receipts match; thermal state stayed nominal, memory pressure was
healthy, retry attempt was zero and the system crash delta was empty. Thus the original serious
thermal state and long-form UI are not necessary conditions for this symptom. This is not a fix.
Run `ios-startup-reliability-20260907-145015-63ba20fb` retains a 2,048-frame/16-group codec binary
with zero reported drops, but the runner failed schema validation: absent final QC is omitted by
Swift while the host requires the key. The streaming failure path also loses the already-persisted
codec metadata from telemetry, leaving the take's artifact list empty; authenticated replay remains
blocked. Do not invent QC, rewrite this failure as PASS, or silently regenerate it.
The exact diagnostic process was terminated. Guarded device-evidence cleanup did not run after
validation failure; retain that evidence. No broader campaign or further generation was started.
Source fingerprints before/after match. The original September 6 experiment/resource stop remains
unchanged; the new registration and assessment are under the existing long-form recovery bundle's
`iphone-followup-20260907/`. The evidence-path corrections and regression fixtures are now
verified above; the historical binary still lacks producer binding. RF-06 remains open.

September 7 RF-06 follow-up: corrected an evidence-classification defect in the shared native
language-quality adapter and VLR host composer. Incomplete/inconsistent/invalid recognition is now
unavailable evidence, not a measured speech rejection; required acceptance still fails closed.
Native tests reproduced 22 failing assertions before repair; Python reproduced six incorrect-owner
subcases. Verifier records and edit metrics stay v3/unchanged; only new gate composition identifies
the corrected interpretation as algorithm 4. Original evidence is never rewritten.
The 14 retained French clips were rechecked without new recognition/generation: eight measured
rejections, six inconclusive, zero promoted; all 30 inspected original files retain their hashes.
See [the bounded follow-up](reference/audio-qc-engineering.md#retained-audio-failure-follow-up--september-7).
At that checkpoint the phone was unavailable. RF-06 was still blocked on the matched original-seed
iPhone long-form comparison and unresolved severe French/Chinese output plus cadence/recognition evidence. No
production audio change, expanded decoder study, campaign resume or release authorization occurred.
Focused verification passes: 55 native verifier/quality-registry tests and 40 Python VLR/language
tests. The before-fix native failure and after-fix PASS logs are retained with the reinspection.

September 7 follow-up: the 45-clip numerical panel is now the cascade's default, digest-pinned
descriptive reference base. Same-language English neutral deltas, unpaired German context and QC
disagreement specimens remain separate; full-cohort and explicitly flagged-exclusion sensitivity
views preserve every warning. No audio/model download is needed to consume the tracked features.
All 45 local original hashes reverified. The actual existing cascade processed all 64 historical
August 23 takes: ten matched reference contexts, 54 explicit missing-coverage rows, and **64 unchanged
inconclusive quality outcomes**, not acceptance passes. A separate cache-hit replay took 0.42 s,
45.22 MB sampled RSS, 512 hits/zero misses, zero swap growth and clean exit/recovery. The first
85.74 s extraction run remains retained with unqualified RSS/swap capture inside the sandbox.
Evidence is `build/artifacts/diagnostics/acoustic-reference-adoption-20260907/`; procedures and
limitations are in [the default-reference section](reference/audio-qc-engineering.md#default-acoustic-reference-base).
Production QC/prompt/model/seed behavior, speech-defect holdout approval and release requirements
are unchanged. AV-07 remains open for actual quality calibration; no new work authority was added.
The 22 focused reference/cascade tests pass, including integrity, warning retention, missing coverage,
source drift, genuine 24→16 kHz extraction, cache reuse and unchanged quality routes. The initial
checkpoint caught a missing AGENTS surface registration; the exact manifest/helper pointers were added.

September 7: the separately authorized licensed acoustic-reference pilot is complete. Thirty
English CREMA-D clips (six actors, audio-only votes) and 15 German Thorsten clips were analyzed
through existing local global/temporal/phonation, native PCM QC and common-bandwidth comparison.
Native results: 39 pass, three warn, three fail; five separate advisory rushed flags. Every original
and failure is retained. Thorsten's actual emotional subset has no Neutral rows and all selected
clips have source cut-off warnings, so it cannot establish clean paired Whisper/Surprised bounds.
Sixteen retained English Vocello takes were compared without new generation; they remain historical,
not current-prompt acceptance. Four serial analysis processes stayed below 48 MB sampled RSS with
clean exit/recovery and zero swap growth. Forty-six focused tests pass. Methods, license pins,
acoustic findings, limitations and the untracked bundle are in
[Audio QC engineering](reference/audio-qc-engineering.md#licensed-acoustic-reference-pilot--september-7).
No new profile, threshold, model, cloud judge, listener requirement or phone work was introduced.
This provides development reference points, not AV-07 quality calibration or RF-06 closure.

The September 7 phone diagnostics above are finished; no further device campaign is scheduled.
No acceptance campaign is currently frozen.
The approved priority is iOS 3.0, retaining all modes, long-form and all 201 campaign takes.
Mac/CLI-only qualification and broad evaluator/prompt research remain off that critical path.

The separately requested Audio QC review and autonomous follow-up are recorded in
[Audio QC engineering](reference/audio-qc-engineering.md). Anti-alias preprocessing is now the
default for new cache/cascade/compact-model qualification; historical linear replay requires explicit
selection and never silently follows an old config. Source-bound integration tests cover actual
model-input PCM, cache reuse, config mismatch and legacy compatibility. The
experimental corrected phonation, bounded legacy projection, model resource requalification and
blind calibration preparation are implemented. Human listening is now optional by explicit
maintainer decision. No product-QC threshold, model, prompt, seed or iOS acceptance changed.
AV-07/DP-28 retain independent-reference calibration/adoption requirements;
RF-06 remains a separate unresolved product-audio blocker.

The next Audio QC measurement step is now complete: analytic signals plus all nine public voice
previews were compared with pinned local Praat/Parselmouth. A reproduced lag-rounding defect
discarded valid 70 Hz pitches and aliased 400 Hz to 200 Hz; interpolation-before-filtering repairs
it, with source-bound optional reports and bounded-memory regressions. Eight focused tests pass.
Across 3,095 preview frames, 62 large pitch disagreements and 2.28–5.06 dB per-preview median HNR
disagreement remain after repair. This is not calibrated semantic/quality evidence. Four serial
before/after processes qualified below 119 MB sampled RSS; the initial invalid Praat-window setup
and red regressions remain recorded, not overwritten. Detailed methods, digests, limitations and
the next AV-07 calibration boundary are in the Audio QC reference; no phone work occurred.

Speech/defect preparation now corrects the underpowered old minimum: zero false alarms in 30 good
clips cannot meet the 95% upper-bound gate; the predeclared starting design is 60 calibration plus
60-good/60-bad holdout recordings. The existing validator now rejects impossible sample floors,
duplicate PCM/source families, examined holdout material and missing/mismatched independent
reference evidence. A bounded read-only inventory found 2,918 WAVs, 2,915 readable files and 1,145 unique
PCM streams, with three unavailable cases retained. These are **not** 1,145 qualified independent
speech observations: groups, languages, exposure and reference labels remain unverified. Everything
discovered stays development-only. The anonymous inventory, separate private path map, unanswered
annotation template and remaining-data counts are retained in
`build/artifacts/diagnostics/audio-qc-calibration-preparation-20260906/`.
Next: reconcile exact source metadata, predeclare an unexamined confirmation pool and bind
independent reference evidence, fit calibration only and qualify once. New listeners are not needed.
The validator can verify controlled PCM changes and pinned external label catalogs. None is
currently approved as general speech-quality calibration; synthetic detection is not perceptual
truth. No profile, production threshold, phone or neural model was used/changed. AV-07 remains open.
The complete focused prosody suite passes 32 tests, including existing profile/calibration consumers;
no app/phone acceptance or completed speech-defect listening session is implied.

### Automated-review correction — September 6

The existing cascade now consumes native Fast-QC receipts preserved by the experiment runner,
uses recomputed WER/CER from independent full-file ASR evidence, and retains cached global/temporal
features. Hard failures dominate; missing, partial, wrong-language, repeated-family, warning and
contradictory evidence cannot become PASS. Optional compact heads no longer force a listener
dependency: unmeasured semantic delivery is explicit, with no mandatory manual-listening route.
The named policy is `automated-evidence-1`; ASR/UTMOS execution requests are not executed results.

Current candidate decisions use schema 2: frozen automatic metrics, independent/reverse-order
judges, complete untouched paired coverage and unchanged statistical/quality/runtime guardrails.
They qualify measured improvements only. Historical listener/annotation readers remain optional,
strict and unchanged in meaning. AV-07, DP-28, DP-31 and DP-32 have updated closure gates; none is
marked complete merely because the human prerequisite was removed. Production prompts, thresholds,
release approval and the 201-take campaign remain unchanged. No cloud or model acquisition occurred.

A read-only replay of 32 retained completed takes produced 32 abstentions, zero screening accepts
and zero measured rejections: the older run did not retain native-QC/independent-ASR receipts.
The new review is retained at
`build/artifacts/diagnostics/audio-review-automated-20260906/retained-screen-review.json`;
it is not new generation, current-source acceptance or a semantic calibration pass. Regression
fixtures exercise native failure precedence, exact audio/text/source bindings, recognizer
independence, full-file coverage, warning/disagreement abstention, reference-label provenance,
severity consistency and unchanged CLI-to-cascade native receipts.
Focused verification passes all 80 tests across the eight affected Python modules, plus the
whitespace/diff check. No native/app source changed, so no new device or native-build result is claimed.

The evidence-led replacement/retirement policy now applies to every testing surface, not just
Audio QC. DWF-06 records the guidance update; [the procedure](reference/repository-self-verification.md#replace-and-retire-tests-and-harnesses)
requires an independent expectation, real integration boundaries and finite compatibility/retirement
criteria. This adopts a policy, not a completed repository-wide test audit or changed quality gate.

| Work | Existing owner | Next boundary |
| --- | --- | --- |
| Documentation/workflow cleanup | RF-01 / DWF-06 | Local workflow implemented; coherent deterministic checkpoint, no product acceptance inferred |
| Privacy/IP/account/signing decisions | RF-02 | Use the existing consolidated decision packet; no repeated account polling |
| Unresolved long-form/French/Chinese audio | RF-06 | English causal research deferred; verify recovery and measure incidence in required acceptance; retain separate French/Chinese findings |
| Static-analysis legacy tensor transfer warning | RF-09 / ASR-10 | Correct the isolated adapter contract, then native tests and Release Analyze before freeze |
| Targeted device acceptance, then 201 takes | RF-11 | Start only after release-blocking product decisions and exact-source freeze |
| Processed candidate and submission material | RF-12 | Separate candidate/upload authority, qualified decisions and actual candidate proof |

RF-03/04/05/07 remain implementation-complete, not independently candidate-qualified.
RF-08/RF-10 stay parked with their original unpark conditions. No issue or acceptance gate was
closed by this documentation cleanup. The exact outstanding decisions and gates live in the
[generated roadmap](ROADMAP.md), not the older dated checkpoints below.

During a frozen campaign, use pinned **untracked** run checkpoints. Do not edit this file or
the roadmap between shards. At a deliberate source checkpoint, incorporate results and acknowledge
the new full-tree identity; historical passes cannot qualify changed source.
The [device pause/resume procedure](reference/ios-device-testing.md#pause-and-resume) owns the steps.

## September 6 accelerated iOS submission implementation

The approved accelerated plan now governs the existing primary roadmap. RF-03/04/05/07 stay
implementation-complete; RF-08/RF-10 are parked off the iOS critical path with explicit unpark
conditions, not waived acceptance. The active release-first reference maps the ten execution
steps and four work classes to existing owners/gates. AGENTS.md now carries the durable iOS-first,
two-experiment decision boundary and source/documentation-freeze rules. The consolidated RF-02
packet identifies outstanding owner/privacy/IP/signing decisions and regional providers; no
account mutation, legal approval, candidate operation or device run has occurred.

**Implemented verification gaps:** promotion contract v3 derives Speed/Quality applicability from
the digest-bound production model contract. iOS retains all applicable Speed requirements;
unsupported Quality is explicit, while macOS Quality and historical v2 semantics remain intact.
The existing UI runner now has a standalone, preinstalled-candidate navigation route: it validates
command-bound release evidence and installed identity before/after, installs only the test runner,
uses destination artifacts, and collects crashes/attachments without debug inputs or private app
container access. Deterministic refusal tests and generic SDK compilation are not proof of a
processed TestFlight candidate; full distribution acceptance remains pending.

**Bounded RF-06 result:** the original 859-character first segment and UInt64 seed were recovered
against the recorded text digest. One fresh-process Mac take reached EOS with 54.8 seconds of audio,
98 chunks and Fast-QC PASS. The engine receipt is **warm**, whereas the failed iPhone receipt is
cold. Repository revision, Speed variant, tokenizer digest, instruction, text and seed match, but
installed integrity-manifest digest, load profile, platform and thermal state differ (Mac nominal;
original iPhone serious). This is an unmatched diagnostic comparison, not a planner fix or iOS
acceptance. Original WAV/codec evidence is unavailable; the new CLI capture has typed boundaries,
not a binary codec trace. No production prompt/model/planner/cap/QC change is justified.

The supervisor confirmed clean process exit, a 2,834,646,936-byte physical-footprint peak, no
before/after pressure warning and memory recovery, but **460,985,466 bytes of swap growth** made
the run unqualified. It stopped before experiment two; neither take was retried. The later host
read showed 68% free memory and no pressure warning, permitting serial deterministic builds only;
it does not retroactively qualify that run. The untracked decision is
`build/artifacts/diagnostics/macos/rf06-longform-recovery-20260906/decision.json`, SHA-256
`3bc5f46f2a8920cde6584dbcb4153300e5e2f5996e5cfa86e73776e09b1d38a9`.

The long-form XCUITest now speaks deterministic natural text and owns outputs through visible
History row IDs/transcript checks, preserving previous joined outputs across regeneration. Removing
the fixture's random spoken marker does not close the original failure. The first divergent product
layer remains unproven; RF-06 and the 201-take campaign remain blocked. No source freeze,
candidate operation, phone run, legal approval or submission-ready verdict is claimed.

Resume with the bounded original-seed iOS long-form comparison only after preflight/receipt identity
and existing codec capture are confirmed. Do not repeat excluded French/Chinese decoder variants.
Independent full-WAV recognition/cadence evidence and the severe gaps remain separate blockers.
The RF-02 packet needs qualified owner decisions; RF-12 needs an authorized processed candidate.
**Verification:** the coherent `scripts/dev.sh checkpoint` passed all 1,567 Python tests,
582 core, 19 transport and 109 owned-runtime tests (two optional AudioSeal fixture skips),
and generic iOS app/logic compilation. The optimized CLI, macOS app, ordinary iOS UI target
and standalone candidate UI target built successfully. Website checks passed lint, 12 tests,
rendered accessibility, production build and two browser sizes. Evidence is retained under
`build/artifacts/ios/candidate-route-20260906` and native run `mac-test-20260906-145620`.

**Additional pre-freeze blocker (RF-09/ASR-10):** Release Analyze completed, but the unchanged
warning policy rejected `AudioGeneration.audio(MLXArray)` claiming `Sendable`. Nineteen other
warnings matched the six existing bounded classes; this twentieth warning is not waived.
The shipping `Qwen3MaterializedGenerationEvent` already transports `[Float]`. Removing the legacy
conformance alone fails compilation at `generateSamplesStream` → `proxyAudioStream`'s Sendable
input requirement, so that attempted patch was reverted completely. The failed compile and original
warning report remain retained; no production/runtime change or new concurrency exemption landed.
Next action: correct the legacy adapter's tensor-transfer contract without weakening isolation or
changing the shipping PCM boundary, then pass native regressions and Release Analyze before freeze.
The normal deterministic checkpoint PASS does **not** replace this failed candidate-warning gate.


## Audio QC review and first cleanup — September 6

Source review reproduced non-finite prosody inputs passing, cache preprocessing/count drift being
accepted, and truncated audio being treated as complete. Corrected those fail-closed boundaries,
streamed canonical writes instead of collecting the full output, bound imported analyzer/runtime
identity into cache keys, reused digest-verified neutral summaries, and prevented neural launches
until both sides pass deterministic screening. Existing valid derivative bytes and score algorithms
remain unchanged; eight pre-refactor byte digests now have regression coverage.
The final focused run passed 57 Python tests in 7.79 seconds, including cache-schema drift,
shared-control reuse, malformed numeric values, truncation, bounded memory and early-stop fixtures.

Four serial synthetic cache probes qualified on the M2/8 GB host: for 60-minute audio, traced peak
fell from 231.75 MB to 4.82 MB and process RSS high water from 316.98 MB to 43.22 MB. No swap growth,
before/after pressure warning or unrecovered process was recorded. This is not neural or perceptual
qualification. Raw evidence remains under `build/artifacts/diagnostics/audio-qc-review-20260906`.

The audit also measured linear-resampler aliasing and pitch-dependent HNR-proxy bias. Their
correction requires explicit preprocessing/analyzer versions and affected-model/profile
requalification; it is not silently included in a memory refactor. Legacy full-frame analysis and
four-pass global/temporal fusion have a bounded migration plan. AV-07/AV-08/DP-28 stay open.

## Autonomous Audio QC follow-up — September 6

Implemented optional `polyphase-kaiser5-v2` bounded FIR preprocessing with frozen SciPy 1.18.0
reference fixtures and cache/config source binding. Historical/default v1 bytes remain unchanged.
The opt-in `window-corrected-ac-v1` phonation block passes synthetic frequency/SNR/noise tests but
has no calibrated threshold or semantic authority. Both legacy callers now use a versioned bounded
projection, and adherence reuses its global extraction. Missing/invalid calibration or holdout
metrics fail closed. Existing preparation tooling emits a blind, byte-bound protocol with explicit
missing-data counts; it neither invents labels nor opens a holdout.

Nine serial synthetic resource probes qualified: one-hour v2 resampling used 3.29 MB traced memory;
120-second legacy analysis fell from 207.41 MB to 0.86 MB, while processing time rose from 2.32 to
7.71 seconds. The shared v3 computation is more expensive than the narrow old analyzer; no TTS
speedup is claimed. Global/temporal fusion stays deferred after profiling (2.85 s for 20 s audio
under instrumentation). An initial stdlib-shadowing probe failure is retained separately.

The installed, pinned SenseVoice and DistilHuBERT models each passed two final-source serial CPU
probes with v2 preprocessing, zero swap growth, no before/after pressure warning, confirmed exits
and memory recovery. This is short-clip resource qualification only; both remain unadopted.
The single predeclared independent Chinese comparison returned 1/59 strict character differences
and detected Chinese. Because that binary cannot locale-lock or prove interior coverage, original
Whisper scores, the 834 ms pause and cadence warning remain unchanged. French Apple/Whisper
disagreement remains open; no invalid French compact-model test or new download was substituted.

Ignored evidence is under `build/artifacts/diagnostics/audio-qc-v2-20260906/`; numerical methods,
report references, resource caveats and repeatable commands are in the engineering reference.
Independent calibration labels and untouched human confirmation remain external dependencies,
not incomplete autonomous coding tasks. No phone, native app UI, generator, production asset,
threshold, prompt, account, release operation or personal data was changed.

Final focused verification passed 79 tests in 7.40 seconds, including v2 derivative-source drift.
Final two-run model report digests are `58b095ae...653eeb2` (SenseVoice) and
`5063b8cf...42ab2` (DistilHuBERT), in the `*-qualified` evidence folders. Earlier development
qualification sets are retained separately, not merged. That implementation added no new gate;
the existing source-binding, serial-workload and promotion boundaries apply.
No phone, new weights, generation, personal audio, account or candidate operation was involved.

## Project-wide test and harness evolution — September 6

Extended the requested forward-looking approach to unit/integration/CLI tests, native UI runners,
audio evaluators, performance tools and build/CI/release validators. AGENTS.md and the existing
testing router point to one replacement/retirement procedure in repository self-verification.
Neither legacy output, snapshots nor newer tooling is treated as correctness authority. Changes
must protect independently established behavior, exercise real connections, demonstrate defect
detection and consider measured cost. Compatibility requires identified consumers and a retirement
condition; historical interpretation can be corrected without rewriting original evidence.

DWF-06 owns this guidance checkpoint and RF-01 cross-references it. No new framework, gate,
mandatory audit campaign, status ledger or product change was introduced. No test implementation
was retired in this guidance-only change. Existing failures and calibration gaps remain open;
the phone, release campaign and publication operations remain untouched. Concrete migrations
belong to existing subsystem items, with release-blocking work first.

## Audio QC current-path migration — September 6

Completed the resampler migration rather than leaving the corrected implementation optional:
new cache, cascade, config preparation and compact qualification use anti-aliased FIR by default.
Historical linear processing is an explicit replay path; old configs cannot silently select it,
change their pins or masquerade as new preprocessing. Existing derivative namespaces and eight
legacy digest fixtures remain intact. Malformed/truncated FIR inputs now return a typed cache
failure without accepted metadata. Cascade and qualification reports expose actual method/source
identity. No product-QC threshold or generation behavior changed.

Two regressions reproduced before the fix. All 47 focused tests pass in 4.17 seconds, including
the production config → cache → WAV writer → compact adapter → cascade connection. The fixture
inspects actual model-input bytes and requires zero launches for cached neutral reuse. Only the
external process is substituted in that deterministic test; separate subprocess tests remain.

Two new cache-cold CPU probes per installed compact model passed via default commands, serially
on the M2/8 GB host. Highest sampled RSS: SenseVoice 277.68 MB, DistilHuBERT 572.87 MB. Every
process exited cleanly and recovered memory; no swap growth or before/after pressure warning.
New source-bound reports/configs are retained separately under
`build/artifacts/diagnostics/audio-qc-current-default-20260906/`; exact digests and limitations are
in the engineering reference. Earlier reports are historical, never overwritten or merged.

DP-28 records this current-path implementation; it is not model adoption. AV-07 still owns the
next independent phonation/profile calibration boundary. Original HNR proxies are not gold
standards; the corrected candidate requires real-speech comparison and an explicitly migrated
consumer before its measurements can drive decisions. RF-06, the phone wait and release gates
remain unchanged. No new schema generation, framework or gate was added for this wiring change.

## Codex workflow streamlining

DWF-06 extends the existing development-workflow plan; the release-first queue remains primary.
Known prose and roadmap edits use documentation/fact/evidence checks. Tooling uses all static
contracts plus transitive local Python selection, with full discovery for unknown/deleted inputs or
verification-authority changes. Native applicability follows the actual source surface, with
`project.yml` protecting shared/iOS membership. Full CI and release checks remain independent.

Removed duplicate inline documentation validators and the duplicate 80-file inventory; HTML-link,
baseline-argument and private-path protections now have one tested owner in the documentation
validator. Four parent/child validators execute once. Optional Xcode assist configuration has an
explicit opt-in command. Instructions now require task-relevant reading and cross-boundary review,
not simulated role approvals or repeated narrative updates after every edit.

Local PASS reuse is versioned separately from release fingerprints and binds tools/environment as
well as source bytes. Refresh is followed by reclassification; concurrent edits prevent PASS.
Focused fixtures cover real routing, transitive consumers, mixed/unknown changes, preserved v1
semantics, missing optional tools, corruption/privacy failures and cache invalidation. The initial
full checkpoint passed; the final hook-hosted recheck for 7887bfda ended before its last build
completed and is not accepted as a completed checkpoint. The follow-up makes the hook receipt-only:
missing/stale/unreadable receipts block immediately, and full checks run directly outside the hook.
The retained interrupted logs remain distinct from completed direct-run evidence.
The representative documentation-route commands passed in 24.3 seconds with unchanged source;
this timing is not a substitute for full-patch verification. Final review also covered inherited
quick-mode refusal for `checkpoint --full` and mixed package-prose/tooling routing.
No device, model, account, release or paused product investigation was started. The 201-take gate,
all audio/privacy/preservation rules and outstanding release blockers remain unchanged.

## Documentation cleanup checkpoint

The documentation audit was performed against `bfef8e2e`. This cleanup corrects unsafe or stale
guidance, reconciles catalog lifecycle with frontmatter, and shortens the mandatory reading path.
It does not change engine behavior, model artifacts, private voice data, test evidence or the
release queue. Verification is recorded with the completed coherent patch, not inferred here.

The original development checkpoint, device/testing runbooks and release-first execution guide
are preserved as digest-pinned historical snapshots. Their bodies remain intact after an added
historical notice. Active guides
describe repeatable procedures, not which dated run to resume. No pinned research/acceptance body
has been rewritten, and no review date was mass-bumped to hide source-drift warnings.

## Authority and evidence

- Work: [config/roadmap.json](../config/roadmap.json); [runtime convergence contract](../config/runtime-refactor-contract.json).
- Architecture/invariants: [ARCHITECTURE.md](ARCHITECTURE.md).
- Measurements: [benchmark history](../benchmarks/HISTORY.md) and [optimization evidence](../benchmarks/OPTIMIZATION.md).
- Current inventories: [project health](project-health.md), [documentation index](INDEX.md).
- The production model catalog is complete. Artifact availability does not establish acceptance.
- A clean canonical macOS schema-v2 baseline exists in tracked history. Each record remains
  bound to its own source/model/hardware, not the current candidate.
- Full pre-cleanup narrative: [development history](development-history-2026-09-06.md).
- Procedure-history snapshots: [device testing](reference/ios-device-testing-history-2026-09-06.md),
  [testing runbook](reference/testing-runbook-history-2026-09-06.md) and
  [release execution](reference/release-first-execution-history-2026-09-06.md).

## Historical checkpoint links

These compatibility headings retain existing incoming links. They are historical evidence,
**not current resume instructions**. Use “Resume now” above for current work.

## September 6 evaluator corrections and product priority

Historical only: [preserved checkpoint](development-history-2026-09-06.md#september-6-evaluator-corrections-and-product-priority).

## September 6 Chinese intelligibility and pause alignment

Historical only: [preserved checkpoint](development-history-2026-09-06.md#september-6-chinese-intelligibility-and-pause-alignment).

## September 6 independent Chinese decoder comparison

Historical only: [preserved checkpoint](development-history-2026-09-06.md#september-6-independent-chinese-decoder-comparison).

## September 6 phase 4 Chinese cadence diagnostic

Historical only: [preserved checkpoint](development-history-2026-09-06.md#september-6-phase-4-chinese-cadence-diagnostic).

## September 5 host follow-up completed — phone approval pending

Historical only: [preserved checkpoint](development-history-2026-09-06.md#september-5-host-follow-up-completed--phone-approval-pending).

## September 5 bounded audio localization and host-verifier correction

Historical only: [preserved checkpoint](development-history-2026-09-06.md#september-5-bounded-audio-localization-and-host-verifier-correction).

## September 5 correlation and capture correction — verified

Historical only: [preserved checkpoint](development-history-2026-09-06.md#september-5-correlation-and-capture-correction--verified).

## September 5 later physical pilot — resume checkpoint

Historical only: [preserved checkpoint](development-history-2026-09-06.md#september-5-later-physical-pilot--resume-checkpoint).

## September 5 ordered host follow-up

Historical only: [preserved checkpoint](development-history-2026-09-06.md#september-5-ordered-host-follow-up).

## September 5 phone-independent codec checkpoint

Historical only: [preserved checkpoint](development-history-2026-09-06.md#september-5-phone-independent-codec-checkpoint).

## September 5 physical-device checkpoint

Historical only: [preserved checkpoint](development-history-2026-09-06.md#september-5-physical-device-checkpoint).

## Resume here (2026-09-04)

Historical only: [preserved checkpoint](development-history-2026-09-06.md#resume-here-2026-09-04).
