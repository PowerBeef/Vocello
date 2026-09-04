---
status: active
owner: ios
reviewed: 2026-09-04
summary: Evidence-driven remediation plan for the generation, model-progress, accessibility, playback-performance, and XCUITest bootstrap findings from the August 2026 physical-iPhone control audit.
sourceOfTruth:
  - config/roadmap.json
  - Sources/QwenVoiceCore/GenerationOutputAdapter.swift
  - Sources/iOS/IOSSettingsViews.swift
  - Sources/iOS/App/TabDock.swift
  - Sources/SharedSupport/Services/LiveStreamingPlaybackEngine.swift
  - scripts/ios_control_audit.py
  - scripts/check_ios_model_management.py
  - scripts/ui_test.sh
---
# iOS control-audit remediation — 2026-08-29

> **Active implementation checkpoint.** This report explains the causal decisions behind
> ICA-06 through ICA-18 and the corrected-source re-closure of MD-3. `config/roadmap.json`, source, tests, and retained
> untracked run artifacts remain authoritative. It does not replace the pinned 2026-08-28 audit.

## Executive assessment

The observed symptoms have independent causes. None supports weakening audio integrity,
changing a fixed seed, raising Qwen's token budget, adding an automatic retry, hiding performance
warnings, or treating an unlaunched XCUITest as product evidence.

| Finding | First consistent boundary | Root cause | Remediation | Closure evidence |
| --- | --- | --- | --- | --- |
| ICA-06 long Chinese take | 293 decoded/published chunks before terminal | Qwen sampled no EOS before the 2,048-token ceiling; Vocello then incorrectly wrapped the post-stream terminal as startup failure | Preserve rejection, emit typed `generation.incomplete` at `streamGenerationEnded`, show an explicit new-take retry message, and treat receipt warm/cold state as observed | Deterministic terminal tests plus one exact no-retry device reproduction with no History output |
| MD-3 first progress frame | Exact durable bytes and accessibility fraction were already 20.2339% | Inherited SwiftUI width animation left the screenshot mid-transition; the validator also compared integer-rounded accessibility text rather than meaningful exact-byte movement | Disable animation on the bar transaction and require at least one percentage point of exact progress before declaring a rounded-value freeze | **Closed:** diagnose `181500` and `182031`, then acceptance `182534` |
| ICA-07 Voices tab | Correct semantic tab was found | The Button inherited label-sized activation geometry, measuring 33.68 points wide | Put minimum control geometry and the content shape on the Button after its style | **Closed:** accessibility `174031` |
| ICA-10 Studio mode selector | Root tabs passed on the corrected source; the first Studio segment measured 36.51 points high | The 36-point visual pill plus rail padding defined the semantic Button frame | Keep the pill visual at 36 points but move the 44-point activation height onto each Button inside the existing 44-point rail | **Closed:** accessibility `174031` |
| ICA-11 Dynamic Type audit | All Default geometry passed; XCTest successively attached History, Models & Files, then Studio as font experiments moved the first reported element | The harness forced `UIPreferredContentSizeCategoryName` while asking XCTest's Dynamic Type audit to vary that category | Keep four explicit category walks, but run the full unfiltered audit in a fifth launch with no content-size override; revert unnecessary product font changes | **Closed:** four walks plus unforced audit in `174031` |
| ICA-08 priority inversion | Playback cancellation reached `stopAndReset()` | MainActor synchronously waited for `AVAudioEngine.stop()`/resource teardown | Silence immediately, transfer exclusive retired-graph ownership, and stop/reset on a utility task | **Closed:** 9/9 perf `180027`, no inversion signature |
| ICA-09 bootstrap timeout | Xcode never launched a test case | Automation-session infrastructure failed before product execution; row-level composition had no run classification | Reuse the narrow zero-test bootstrap classifier and add a run-level `INFRASTRUCTURE_FAIL` while rows remain skipped | **Closed:** positive/negative fixtures, retained-run replay, and fresh no-retry smoke `184747`; no original failure rewritten |
| ICA-13 saved-voice menu reachability | The run-owned imported voice existed, but its menu exposed no valid activation point | The original failure queried an offscreen lazy row; after search-driven reachability passed on device, the next failure was a still-visible search keyboard covering the floating tab dock | Reveal the exact voice through genuine search, require semantic 44-point row/menu geometry, then submit search and prove keyboard dismissal before tab navigation | **Closed:** complete no-retry saved-voice lifecycle `164233` |
| ICA-14 generation carrier collision | Numeric token collision was guarded; the next run rejected its own second long-script row | Search tokens cannot authorize ownership, and a History row intentionally exposes only the first 60 characters | Resolve the narrowed row, open its genuine read-only player, and require the full accessible transcript to equal the frozen plan before mutation | **Closed:** contract fixtures and fresh generation `172247` with four PASS observations before the separate ICA-15 product failure |
| ICA-15 Custom sampled over-continuation | Exact request, receipt, model start, decoded chunks, and publication all matched before mandatory QC | The model emitted 373 streaming or 547 non-streaming codec frames for 28 target tokens, voluntarily ended by EOS, and encoded long silence in the trace | Preserve fail-closed rejection; retain terminal diagnostics and evaluate any bounded-continuation candidate across representative valid speech before changing production | Two independent four-cell device diagnostics reproduce every warm/cold and streaming/non-streaming failure; production mitigation remains in flight |
| ICA-16 smoke evidence collection | Three XCTest cases passed, then collection copied unrelated historical evidence for eight minutes | Smoke used the unbounded whole-mirror pull instead of the existing run-scoped collector | Pull only the run namespace with a 60-second bound and propagate copy/validation failure | **Closed:** scoped/corrupt/copy-failure fixtures and complete no-retry smoke `184747` |
| ICA-17 optional cadence statistics | Both no-marker takes passed app QC and wrote complete results | Host/schema required median/p90 fields that Swift legitimately omits when nil | Match Codable optionality while retaining required-field, type, and unknown-key rejection | **Closed:** red/green fixture, 83 adjacent tests, retained-evidence validation, and complete reverse-order device run `054340` |

## Physical acceptance checkpoint

### Metadata-only History ownership (ICA-18)

The new schema-v3 control plan speaks the exact tracked language corpus. It does not append a
numeric suffix. Old v1/v2 generators and validators remain byte-exact; a deterministic fixture pins
the original ICA-15 plan, row, and script digests. Removing test metadata is not a numeric-input
product fix, and does not replace or invalidate the failed original takes.

The genuine completed player exposes a generation UUID, while History exposes a separate persisted
database row ID. The harness does not pretend these are the same identifier. Instead it records a
read-only, bounded census of matching History rows before generation, then requires exactly one
new row afterward without losing any prior row. Before every pin/delete action it opens that exact
row and compares the full accessible transcript. Existing identical user text is preserved, never
treated as stale audit state. Observations record versioned before/after/final row identities,
transcript agreement, carrier disposition, and the correlated generation UUID/seed/script digest.
Post-deletion census must equal the original baseline.

Resume validates the exact source/plan/run chain, terminal telemetry correlation and ownership
digest, then supplies the exact retained row ID to the test runner. Its visible seed must match the
recorded UInt64 before pinning. Missing, cross-run, ambiguous, or zero-observation evidence fails
closed; no text scan can adopt a different seed. Multi-shard resume checks each original run's
correlation, and explicit pin ownership preserves preexisting user pins. Only the actual final
plan shard removes carriers.
No runtime, product UI, model, prompt, sampler, or QC policy is changed. The deterministic
checkpoint, generic iOS app/logic build, macOS core/transport/runtime tests, and focused
ownership/resume fixtures pass. The final tree is revalidated before commit. Fresh physical
verification remains pending; ICA-18 and the complete generation audit remain open.

### September 4 marker-removal and validator diagnosis

The originally prepared no-marker run is complete, not pending. Exact-receipt checks confirm the
original UInt64 seed `17323406037040967292`, Eric, Calm Strong, Italian, and Consistent variation.
The 62-character input file normalizes to the intended 61-character sentence. The unrun plan's
rounded seed literals were corrected before launch using the retained control identity; no attempted
seed or prior result changed.

| Run / observation | Actual residency | Fast-QC | Duration | Longest interior / terminal silence | Codec frames |
| --- | --- | --- | --- | --- | --- |
| `053757-ed201aef` / streaming | Cold | PASS | 8.72 s | 267 / 65 ms | 109 |
| `053757-ed201aef` / non-streaming | Warm | PASS | 7.52 s | 140 / 44 ms | 94 |
| `054340-c307ab41` / non-streaming | Cold | PASS | 7.52 s | 140 / 44 ms | 94 |
| `054340-c307ab41` / streaming | Warm | PASS | 8.72 s | 267 / 65 ms | 109 |

Full run IDs begin `ios-startup-reliability-20260904-`. Each mode's cold/warm codec digest is
identical; all four takes end by model EOS at retry attempt zero. The complete receipts, QC,
codec binaries, build provenance, and cleanup acknowledgements are retained under the ignored
startup-reliability artifact root. WAV digests are not equated across generation-scoped publication
metadata. These are bounded integrity/cadence observations, not ASR, semantic delivery, or general
numeric-input acceptance.

**ICA-17 is a separate, corrected host defect.** The first run's app result was PASS but its runner
failed because `medianCadencePauseMS` and `p90CadencePauseMS` were incorrectly required by the
host/schema. Swift's source declares them optional and omits them when nil. The correction accepts
omission or null and continues rejecting missing required fields, unknown keys, and malformed
numbers. A red/green fixture reproduces the shape; all 83 adjacent fixtures pass. Corrected
validation of the original bytes and a separate exact-run cleanup pass, without rewriting the
original failed runner. The reverse-order confirmation passes its full runner, crash checks, and
cleanup, closing ICA-17. No production source or audio-QC threshold changed.

**Current-build paired control:** `ios-startup-reliability-20260904-054601-0770b988` restores the
exact original 71-character normalized script, including its original marker, at the same seed and
request settings. Both takes fail QC: streaming is 29.84 seconds with 1,851 ms interior and
11,096 ms terminal silence; non-streaming is 43.76 seconds with 8,206 ms interior silence. The
373/547-frame codec digests match the historical controls, and both incremental and full decoder
replays fail in the same intervals. Receipts preserve exact text identity and retry attempt zero.
The runner exits successfully with `diagnosed_failure`, no crash delta, and verified cleanup; this
is successful diagnosis of failed audio, not successful generation acceptance.

The six observations establish an interaction with this exact text/suffix/seed under both modes.
They do not prove that all numeric text fails or that emotion/language fidelity is solved. ICA-15
remains open. The next harness work should move ordinary History ownership to existing visible
generation metadata without contaminating spoken scripts, retaining the original numeric cases
as immutable stress evidence. That work must preserve exact ownership, ambiguity rejection,
source-bound resume, user-data protection, and the original failures. It must never strip digits
from production input or substitute a fresh seed. The full control campaign remains unrun on a new
final frozen source; earlier accepted smoke/saved-voice phases need no blind rerun.

### September 3 retained checkpoint

Smoke run `ios-xcui-smoke-20260903-181935-a051e519` passed all three XCTest cases but its
legacy post-test collector then copied more than 365 MB of historical diagnostics. After eight
minutes the redundant copy was deliberately terminated, preserving the failed runner rather than
claiming XCTest-only acceptance. Its 1.6 MB current-run subtree independently passes the existing
memory-pressure checker. ICA-16 uses the already-established run-scoped collector with a 60-second
timeout and leaves every acceptance requirement unchanged. Fixtures cover equivalent scoped
evidence, historical corruption isolation, and copy-failure propagation. Fresh no-retry smoke
`ios-xcui-smoke-20260903-184747-dc032d1b` subsequently passed the primary journey (239.819 s),
Settings accessibility (288.281 s), and long-form plus segment regeneration (336.142 s). Crash
delta passed at 19:02:42 UTC; scoped collection and memory cancellation/full-unload/recovery
validation passed at 19:02:44 UTC. The final required-step ledger and host retention phase passed.
Test teardown terminated the app, and device execution/collection ended before the maintainer's
deadline. This closes ICA-16 and the fresh-bootstrap portion of ICA-09. All prior interrupted
results remain unqualified and pinned; these separate-source results do not close the full audit.

The September 3 continuation preserves three new bundles. Saved-voice run
`ios-xcui-saved-voice-lifecycle-20260903-162036-6f4e3996` and generation run
`ios-xcui-control-audit-20260903-162348-77a58a4e` both stopped before launching a test while Xcode
enabled automation. They remain separate `INFRASTRUCTURE_FAIL` evidence and contain no product
observation. After the maintainer unlocked the phone, saved-voice run
`ios-xcui-saved-voice-lifecycle-20260903-162649-37ad8335` launched, revealed the exact run-owned
voice through the real search field, activated its semantic menu, and completed deletion. It then
failed because the software keyboard remained over the floating dock after search text was cleared,
making `rootTab_settings` non-hittable. The shared test helper now submits the search field and
condition-polls for keyboard absence before tab navigation. Focused and exact-tree checkpoint gates
passed, followed by complete no-retry run
`ios-xcui-saved-voice-lifecycle-20260903-164233-e71568b3`. The full import, automatic
transcription, enrollment, Clone selection/generation, preview, deletion, draft cleanup, and runner
diagnostics journey passed; ICA-13 is closed.

Generation run `ios-xcui-control-audit-20260903-164806-affcc06a` then completed its first two
visible Custom takes and stopped before History mutation because the second long frozen script did
not equal the row's intentional 60-character preview. That is a harness identity defect, not a
product-generation failure. The corrected guard opens the genuine read-only player and requires its
full accessible transcript to equal the frozen plan before any cleanup, pin, restore, or delete
action. The failed bundle is preserved and cannot resume after this source change.

The next current-source run, `ios-xcui-control-audit-20260903-172247-b8fc963e`, passed four Custom
rows and then correctly rejected `custom-005` before History publication. That cell is Eric, Calm
Strong, Italian, Consistent, seed `17323406037040967292`; Fast-QC measured a 1.851-second interior
gap followed by 11.096 seconds of terminal silence. Diagnostic runs
`ios-startup-reliability-20260903-174346-f3006528` and
`ios-startup-reliability-20260903-180139-ecb380f1` independently reproduced the failure in all four
streaming/non-streaming and warm/forced-unload cells. The retained warm/cold trace in each output
mode is byte-identical, and both incremental and full Mimi replay reproduce the gaps. The corrected
second run also retains finalized model evidence: 28 target tokens, a 2,048 effective budget,
voluntary EOS rather than token-cap termination, and 373 or 547 codec frames. Memory stayed
healthy, no crash delta appeared, and invalid output never entered History. This localizes the first
divergence to sampled CustomVoice continuation. ICA-15 owns the remaining bounded-policy research;
no trimming, hidden retry, seed change, prompt/sampling change, or QC weakening was applied.

The first four accepted rows also rule out a blanket rollback to the former six-times target-token
budget: QC-PASS `custom-002` (Aiden/Chinese) used 331 codec frames for 49 target tokens, exceeding
the hypothetical 294-frame cap. The audit appends an eight-digit spoken History marker; a two-take
marker-removal ablation was prepared at that pause. Its September 4 execution and reverse-order
confirmation are recorded above; neither replaces the original failed control.
The exact original-text failures remain immutable controls. Upstream `non_streaming_mode` also
changes text conditioning, so unequal cross-mode traces alone are not proof of RNG corruption;
see the [official inference source](https://github.com/QwenLM/Qwen3-TTS/blob/main/qwen_tts/inference/qwen3_tts_model.py).

The September 2 one-hour continuation adds four current-source bundles. Inventory run
`ios-xcui-control-audit-20260902-180938-42d76c39` completed with 41 `PASS`, one explicit
`NOT_APPLICABLE`, and no failures or skips, closing the earlier picker-dismissal recapture gap.
Saved-voice run `ios-xcui-saved-voice-lifecycle-20260902-181739-713b7367` failed when the
run-owned imported voice row menu exposed an invalid activation frame. Generation run
`ios-xcui-control-audit-20260902-181849-9ea76d5a` stopped before any terminal observation when its
guard proved reserved token `28400003` belonged to a non-audit History row; all 204 composed rows
therefore remain skipped and the run has no valid resume token. Smoke run
`ios-xcui-smoke-20260902-182906-25dc08ce` passed all three XCTest cases, but its post-test
diagnostics pull was cancelled at the maintainer's one-hour deadline, so it remains unqualified.
These results localize two harness blockers without changing product behavior. The next campaign
must use a new frozen tree identity after correcting them.

Corrected-source run `ios-xcui-control-audit-20260829-174031-cae15a02` passed Default, AX-L,
AX-XXXL, pseudo-AX-XXXL, and the separate unforced unfiltered XCTest accessibility audit without
retry. It closes ICA-07, ICA-10, ICA-11, and ICA-12. The iterative first divergences also corrected
the UIKit editor's missing description, setup-chip abbreviation contrast, and disabled Generate
semantics/contrast rather than excluding those audit categories.

Run `ios-xcui-perf-20260829-180027-45adde8a` passed all nine performance scenarios, the governed
frame gate, crash-delta validation, and offline history publication. Its current-source logs contain
no priority-inversion, Thread Performance Checker, engine-stop/reset, QoS-wait, or semaphore-wait
signature. This closes ICA-08 without changing scenario designations or thresholds.

MD-3 re-closed on the corrected source. Consecutive diagnose runs
`ios-xcui-model-download-20260829-181500-8b1428c9` and
`ios-xcui-model-download-20260829-182031-207e8a83` passed with no finding. Acceptance run
`ios-xcui-model-download-20260829-182534-91d70526` then passed all three models with 1,288 events,
21 observations, and 15 visual samples. The maximum fill-versus-byte error was 1.06 percentage
points, minimum contrast was 8.80:1, and installation, shared reuse, removal, relaunch persistence,
task/crash cleanup, and canonical-state preservation all passed.

Generation run `ios-xcui-control-audit-20260829-174356-664034d5` is not product evidence: the log
proves a SpringBoard `NotificationShortLookView` banner interrupted a mode-selection tap, and the
maintainer identified Facebook Messenger as its source. It is retained as `INFRASTRUCTURE_FAIL`.
The later manual run has a distinct run ID and does not overwrite it.

## Research basis

Apple's SwiftUI transaction API explicitly permits disabling animations for state changes; the
progress rail therefore owns an animation-free transaction rather than trying to predict or wait
out an inherited animation. [SwiftUI `Transaction.disablesAnimations`](https://developer.apple.com/documentation/swiftui/transaction/disablesanimations)
and [SwiftUI animations](https://developer.apple.com/documentation/swiftui/animations) are the
platform authority.

Apple's interface guidance uses a 44-by-44-point iOS interaction target. The fix expands the
semantic Button itself rather than padding only its visual label. See
[Accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility) and
[Buttons](https://developer.apple.com/design/human-interface-guidelines/buttons).

Apple defines a priority inversion as higher-priority work waiting on lower-priority work and
recommends removing synchronous dependencies from interactive paths. `AVAudioEngine.stop()` stops
the engine and attached audio hardware; it is not required to remain on the MainActor once the
retired graph has exclusive ownership. See
[Diagnosing performance issues early](https://developer.apple.com/documentation/xcode/diagnosing-performance-issues-early)
and [`AVAudioEngine.stop()`](https://developer.apple.com/documentation/avfaudio/avaudioengine/stop()).

Upstream Qwen3-TTS exposes `max_new_tokens = 2048` in its inference implementation and uses the
same bound in official evaluation examples. A reported upstream failure mode also reaches the
limit without EOS on occasional sampled requests. This supports classifying the retained take as
a valid sampled-output rejection, not silently changing the seed or claiming a decoder/startup
failure. Sources: [official repository](https://github.com/QwenLM/Qwen3-TTS),
[inference implementation](https://github.com/QwenLM/Qwen3-TTS/blob/main/qwen_tts/inference/qwen3_tts_model.py),
and [upstream issue 118](https://github.com/QwenLM/Qwen3-TTS/issues/118). The issue report is
corroborating field evidence, not a product contract.

## Implementation plan and current state

### 1. Generation terminal correctness — ICA-06

`GenerationOutputAdapter` now maps token exhaustion before EOS to the shared typed native-runtime
error. Its stage is `streamGenerationEnded`, its failure code is `generation.incomplete`, and its
message states that incomplete audio was not saved and the user may generate a new take. Diagnostic
classification records a model terminal rather than startup.

The request, seed, maximum-token policy, sampling distribution, prompt, and audio-QC rules remain
unchanged. Incomplete audio remains absent from product History. A reproduced failure is acceptable
closure evidence only when all these safety and messaging properties hold.

The prior plan also labeled every post-sentinel row warm. That inference was invalid because the
iPhone idle-unload policy can expire during intervening visible UI work. The plan now enforces the
first row as cold, records other rows as observed, and requires at least one receipt-authoritative
warm row per mode.

### 2. Exact progress presentation — MD-3

The retained observation recorded 345,713,491 of 1,708,583,689 durable bytes (20.2339220%). Its
accessibility value was already 20%, but the first screenshot caught roughly 1% rendered fill and
1.10:1 contrast. One second later, after only 127 more bytes, the screenshot measured 20.22% and
12:1 contrast. This is the signature of a view animation, not byte-accounting divergence.

`IOSModelTransferProgressBar` now disables inherited animation at its transaction boundary. The
host validator continues to compare reported fraction and rendered width, but an unchanged rounded
accessibility percentage is considered frozen only when exact progress advances by at least one
percentage point. The five-percentage-point rendering tolerance and 3:1 contrast requirement are
unchanged.

The corrected-source two-diagnose-plus-acceptance sequence listed above passed. Across both Custom
diagnoses, maximum visual error was 0.65 percentage points and minimum contrast was 12.02:1. The
three-model acceptance stayed within 1.06 points and above 8.80:1, with no lifecycle finding.

### 3. Root-tab activation geometry — ICA-07

Every tab Button now owns flexible width, a 44-point minimum height, and a rectangular content
shape after applying its plain style. Visual alignment and the shared floating dock metrics remain
unchanged. Run `ios-xcui-control-audit-20260829-174031-cae15a02` passed every required text size
and the unforced system audit.

### 3a. Studio selector activation geometry — ICA-10

The first corrected device run advanced through all four root tabs, then found
`generateSection_custom` at 36.51 points high. The 36-point capsule is an intentional visual inset,
but the interactive Button had inherited that visual height. Each selector Button now owns a
44-point semantic frame and rectangular content shape; the rail keeps its existing 44-point total
height by retaining only horizontal outer padding. Built-in, Design, and Clone share this primitive.

### 3b. Dynamic Type audit isolation — ICA-11

Three runs passed the explicit Default geometry assertions, while XCTest successively attached
History, “MODELS & FILES,” and Studio as two font experiments changed which element it reported
first. The common factor was the launch argument: the app was pinned to
`UICTContentSizeCategoryL` while XCTest's Dynamic Type audit attempted to vary the category. That
test configuration makes every text element appear non-adjustable.

The compact product fonts remain backed by the repository's `ScaledMetric` modifier and the two
unnecessary visual changes are reverted. Default, AX-L, AX-XXXL, and pseudo-AX-XXXL remain four
explicit geometry/reflow launches. A fifth launch carries no content-size override and runs the
complete unfiltered XCTest accessibility audit. Thus Dynamic Type is tested instead of excluded,
without allowing a forced test setting to invalidate its own measurement.

### 3c. Studio selector Dynamic Type — ICA-12

With that harness conflict removed, run `ios-xcui-control-audit-20260829-164205-f76dc89f`
completed all four explicit-size walks and the separate unforced audit identified one genuine
failure: `generateSection_clone` used a fixed 15-point system font, and XCTest reported that the
user could not change its size. The shared selector title now keeps the same 15-point base design
through the repository's `ScaledMetric`-backed modifier relative to `.subheadline`, so Built-in,
Design, and Clone respond together to Dynamic Type. The first scalable-font run then exposed the
rail's former intrinsic-width policy at AX-L: `generateSection_custom` began 30.67 points outside
the screen. The primitive now gives each segment an equal flexible share, removes the forced
horizontal ideal size, and reduces only its decorative horizontal inset at accessibility sizes.
Text remains scalable; the rail remains 44 points high and inside the viewport.

The next run passed all four geometry/reflow configurations, then the unforced system audit
attached the bottom Studio label as only partially adjustable. The custom point-size scaler was
visually responsive but did not provide the semantic style metadata XCTest requires. The stable
Studio surface now uses native semantic text styles at equivalent base sizes: dock labels,
mode titles, composer placeholder and metadata, setup-chip values, and conditional generation
messages. The bridged `UITextView` uses `UIFontMetrics` and enables
`adjustsFontForContentSizeCategory`. Decorative SF Symbols retain their fixed glyph sizes.
The following unforced audit then identified the shared primary CTA's fixed 17-point title; it now
uses semantic `.headline`, which has the same ordinary-size weight and point size.
Once those labels scaled semantically, the audit correctly reported the four-across dock as only
partially supported: its enlarged “History” label eventually exceeded one quarter of the rail.
The ordinary dock remains unchanged. At accessibility sizes it reflows to a 2-by-2 grid with each
icon and label arranged horizontally; Studio raises its bottom reservation to match the taller
dock so generation controls remain unobstructed.
The next unforced audit reached the composer metadata and found the mode label clipped beside its
character counter. At accessibility sizes that row now becomes a two-line composition: the mode
label receives the full width, with clear/count controls beneath. Ordinary sizes retain the compact
single-row treatment.
With metadata fixed, the audit reached the mode selector at its largest size and found “Design”
clipped. The selector now mirrors the dock's adaptive approach: it remains a compact three-way
horizontal rail at ordinary sizes, and reflows to three full-width 44-point rows at accessibility
sizes. Selection traits, tint, and the moving selected surface remain unchanged.

### 4. Playback graph retirement — ICA-08

`stopAndReset()` now stops the player node immediately and clears product state without making the
MainActor synchronously stop the audio engine. When a graph is discarded, an immutable registered
`@unchecked Sendable` retirement owner receives exclusive engine ownership; a utility detached task
then performs `stop()` and `reset()` and releases the graph. Replacement configuration retires the
old graph before publishing a new one.

The concurrency exception is bounded in `config/concurrency-safety.json`. It is not a general
permission to pass mutable AVFoundation state across isolation domains: product code relinquishes
all references before the transfer.

The nine-scenario closure run `ios-xcui-perf-20260829-180027-45adde8a` passed, published its
source-bound history record, and emitted none of the priority-inversion signatures searched by the
remediation gate.

### 5. Automation bootstrap truthfulness — ICA-09

The runner reuses the existing startup-reliability bootstrap classifier. It may classify a
control-audit run only when retained evidence proves zero launched test cases and no app assertion,
generation, crash, QC result, or observation. The composed summary records a run-level
`INFRASTRUCTURE_FAIL`; control rows remain `SKIPPED_AFTER_FAILURE` because they were never tested.

No automatic retry is added. A later manual run has a distinct run ID and cannot overwrite the
first failed result.

A second narrow classifier handles a different infrastructure boundary: a launched test may be
classified `infrastructure_external_interruption` only when the log proves a SpringBoard banner,
the `.xcresult` proves exactly one identified launched-test timeout, and no product, crash, or
harness failure evidence coexists. It does not reuse the zero-test bootstrap classification. The
Messenger-interrupted run `174356` replays through this classifier and remains failed with every
unexecuted row skipped.

## Verification state and remaining sequence

The accessibility, model-delivery, and performance portions completed on the corrected source:

```sh
# Passed: ios-xcui-control-audit-20260829-174031-cae15a02
# Passed: ios-xcui-model-download-20260829-181500-8b1428c9
# Passed: ios-xcui-model-download-20260829-182031-207e8a83
# Passed: ios-xcui-model-download-20260829-182534-91d70526
# Passed: ios-xcui-perf-20260829-180027-45adde8a
```

The remaining device work is generation-only. The original no-EOS seed was recovered as
`1051465817978323110`, but the production UI exposes only ordinary random generation and History
pinning; the rejected take created no History row. The harness must not add hidden seeded state to
force a reproduction. If a genuine visible path becomes available, ICA-06 accepts correct safe
rejection, terminal message, exact receipt, and absence from History—not forcing the take to become
valid. The broader generation campaign then resumes on one frozen source identity.

The completed model runs retained MD-3's quantitative thresholds. The completed perf rerun remained
governed by the existing scenario classifications; exploratory player scrubbing was not promoted to
a confirmatory claim.

### September 2 generation checkpoint

Before generation, source-bound stateful run `121158`, external run `121608`, and accessibility run
`121855` completed with only their contract-declared prerequisite and preservation-policy limits.
Model-management diagnose `122641`, queue `123230`, and acceptance `123603` passed without a
finding. Inventory run `120801` stopped before observations when the voice-picker confirmation did
not disappear, and saved-voice lifecycle run `122245` reached its preview action but never observed
the player sheet. They remain unresolved evidence gaps, not PASS results.

The next source-bound attempts advanced harness truthfulness but did not complete the matrix:

- `ios-xcui-control-audit-20260902-141800-7d51bfe9` passed `custom-001` through
  `custom-003`; `custom-004` then produced a 27.28-second Dylan/German/Calm-strong take with a
  2.085-second interior gap and was correctly rejected before History publication at frozen seed
  `14590678627036013466`.
- Subsequent shards exposed three independent harness defects: resume looked for an unlabeled row
  container instead of the labeled seed-carrier action, player scrubbing always moved right even
  when playback was already near the end, and stale audit-row cleanup searched a static label
  instead of the row's labeled action. Each correction has focused deterministic coverage.
- `ios-xcui-control-audit-20260902-151039-2607ad43` stopped during mode setup while the maintainer
  received a phone call. It has no control observation and is not product evidence.
- `ios-xcui-control-audit-20260902-151248-90976475` passed `custom-001`; `custom-002` then
  produced a 67.84-second Aiden/Chinese/Angry-normal take with a 25.446-second interior gap and was
  correctly rejected before History publication at frozen seed `2247811184622560891`.
- The final current-source shard `ios-xcui-control-audit-20260902-153340-9092ff5d` was stopped on
  explicit maintainer request during initial state capture. It produced zero observations, started
  no generation row, and retains all 204 composed rows as `SKIPPED_AFTER_FAILURE`. Xcode and
  XCUITest exited and the complete available forensic bundle is pinned.

These runs are immutable evidence, not a mergeable campaign: their full-tree fingerprints differ.
The last shard has no valid row-level resume boundary, and committing this checkpoint changes source
identity again. The next phone session must start a fresh retained generation run from row 1, then
continue source-bound shards only through the harness's governed resume path. ICA-04 remains open
for all 201 generation takes plus final cleanup/restoration; ICA-05 remains open for the final
deliberately re-pinned findings report. The two new silent-gap cells are retained product findings,
not permission to weaken QC, change seeds, or add retries.

## Non-goals and remaining authority

- No seed mutation, best-of-N, hidden retry, prompt rewrite, token-limit increase, or QC weakening.
- No conversion of infrastructure or blocked rows into product PASS results.
- No Simulator or alternate UI driver.
- No closure of ICA-04/ICA-05 until every required row is represented and restoration is proven.
- No release authority follows from these remediations; App Store readiness remains governed by
  the independent ASR plan.
