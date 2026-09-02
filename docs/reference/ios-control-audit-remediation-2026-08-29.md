---
status: active
owner: ios
reviewed: 2026-09-02
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
> ICA-06 through ICA-14 and the corrected-source re-closure of MD-3. `config/roadmap.json`, source, tests, and retained
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
| ICA-09 bootstrap timeout | Xcode never launched a test case | Automation-session infrastructure failed before product execution; row-level composition had no run classification | Reuse the narrow zero-test bootstrap classifier and add a run-level `INFRASTRUCTURE_FAIL` while rows remain skipped | Positive/negative fixtures, retained-run replay, and one fresh no-retry device bootstrap |
| ICA-13 saved-voice menu reachability | The run-owned imported voice existed, but its menu exposed no valid activation point | Current ownership is not yet localized between production accessibility geometry and XCUITest query timing | Prove the semantic menu owns a stable 44-point activation frame and make the lifecycle wait for that exact control without coordinate fallback | Deterministic geometry/query coverage plus one complete no-retry saved-voice lifecycle run |
| ICA-14 generation carrier collision | No generation row started; reserved token `28400003` matched an unrelated History row | Numeric substring search is not sufficient proof of run-owned carrier identity | Bind lookup to immutable plan/run script identity and the labeled row action; reject collisions without touching user data | Collision fixtures plus a fresh source-bound generation campaign with terminal observations |

## Physical acceptance checkpoint

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
