---
status: active
owner: backend-and-platform
summary: The active narrative checkpoint — current resume block, per-arc history, and the phase table; cites config/roadmap.json and the runtime contract as the status authorities it never overrides.
sourceOfTruth:
  - config/roadmap.json
  - config/runtime-refactor-contract.json
---
# Vocello development checkpoint

> Current maintainer checkpoint. Confirm this summary against the checkout before acting; source,
> `project.yml`, and repository scripts remain authoritative.
>
> **One authority per fact:** convergence status lives in
> [`config/runtime-refactor-contract.json`](../config/runtime-refactor-contract.json);
> measurements live in [`benchmarks/OPTIMIZATION.md`](../benchmarks/OPTIMIZATION.md) and the
> PASS-only registry ([`benchmarks/HISTORY.md`](../benchmarks/HISTORY.md)); the staged roadmap
> and its closure evidence live in
> [`docs/reference/optimization-report-review-2026-07-25.md`](reference/optimization-report-review-2026-07-25.md);
> engine invariants live in [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) and the ADR
> [`docs/decisions/runtime-streaming-quality-convergence.md`](decisions/runtime-streaming-quality-convergence.md).
> This file is the thin checkpoint: where things stand, what to do next, and pointers.

## Runtime convergence status

Phase 4 `overallPromotion: passed` closed the cutover gate on 2026-07-20 (with Phases 0/5/6).
Phases 7, 8, and 14 closed 2026-07-23. Phase 9 closed 2026-07-26; Phase 12 ships the fast-depth
quality registry with the deep producer landed; Phase 13 (history v3) went live 2026-07-29 with
the first schema-v3 records committed, and the UI-checker fold (2026-08-01) extended v3 to ui-generation records; phases 10 and 11 closed 2026-08-01 (see the phase table), leaving phase 12's optional MOS-proxy as the block's remainder. The contract JSON is the
machine-readable status record and wins over any older prose.

| Plan phase | Current state |
| --- | --- |
| 0 — Characterization | Closed 2026-07-20. Clean-tree Mac CLI/UI and iPhone UI controls bound in `config/characterization-fixtures.json` (`status: closed`, `controlSessions` recorded). |
| 1 — Correctness prerequisites | Shipping: XPC reserves before side effects, synchronized pressure snapshots, continuous critical-relief admission. |
| 2 — Plans and actor | The actor is the shipping generation-mutation authority and, since 14b, owns every product-reachable runtime lifecycle operation (loading, facts, diagnostics, priming, schema-3 clone artifacts). Immutable plans stay in shadow comparison. Invariant detail: ADR + `.agents/rules/backend-mlx.md`. |
| 3 — Classified sessions | Shipping through Phase 4: `[Float]` materialized before the awaited frame-bounded single-consumer channel send; typed terminal outcomes; stale-safe product finalization. |
| 4 — Product adapter and mode cutover | Closed 2026-07-20 (`overallPromotion: passed`). `GenerationOutputAdapter` is the shipping product session. |
| 5 — Request-local sampling | Closed 2026-07-20. Fail-closed promotion packaging (`samplingPromotionPackaged=true`) live on the shipping path. |
| 6 — Telemetry v9 | Closed 2026-07-20: complete v9 sidecars are the history authority; the JSONL envelope remains schema v8. |
| 7 — UI-context gap | Closed 2026-07-23 in two acts (OPTIMIZATION.md §J/§K): XCUITest screen recording was the canonical decline (fixed via `preferredScreenCaptureFormat: screenshots`); the honest residual was Liquid Glass compositor work, shipped as the generation performance gate (macOS; iOS applies it on fixed-refresh displays only). XPC topology itself measures ~3%. |
| 8 — Shared component storage | Closed 2026-07-23 with live all-artifact validation on both canonical platforms (exact reuse, single tokenizer inode; `docs/reference/model-delivery.md`). |
| 9 — Runtime component reuse | Closed 2026-07-26. Speech-tokenizer residency ships on macOS behind host-attested content identity; byte-identical fixed-seed switch A/B, adoption probe 503→0 ms, retained-memory qualification PASS on the 8 GB floor (`mac-memory-qualification-20260726-115343-5a1c8a85`). iOS went adaptive-LIVE 2026-08-02: the device-class gate (8 GB minimum) ships enabled after the default-state on-device qualification passed (`ios-memory-qualification-20260802-011251`; engagement proven by load-event counts — one tokenizer load across the mode-switch sequence instead of three). `QWENVOICE_TOKENIZER_RESIDENCY` is a two-way debug switch (`off` disables anywhere, `on` force-enables). 6 GB devices stay non-resident regardless. |
| 10 — Spoken-text planning | Closed 2026-08-01: every take now speaks the conservatively normalized script at the engine entry (prompt assembly, language detection, QC pause budget, and telemetry evidence all see the same spoken text; transformed takes record `spokenTextTransformations` + digest). The fixed bench corpus is normalization-invariant by a standing core test, and the fixed-seed A/B on the medium corpus text was byte-identical across the change. Long-form/batch upstream planning passes through unchanged (idempotent). |
| 11 — Long-form v4 | Stages A–E shipping on both platforms: planner-owned segmentation with per-segment sub-seeds, sequential streaming execution, bounded assembly, manifest v4, resume, grouped History projects. macOS acceptance 2026-07-23 (`macos-xcui-smoke-20260723-195700-ab46482a`); iPhone acceptance 2026-07-24 (`ios-xcui-smoke-20260724-183626-f9961535`). iOS single-segment regeneration device-accepted 2026-08-01 (smoke run `ios-xcui-smoke-20260801-142416-79615150`: the retained project's segments chip opens a confirmation dialog, segment 1 regenerates with a fresh recorded seed, the joined output reassembles, and History keeps the lineage searchable — longFormV4 residual closed); line batch stays removed from iOS by design; legacy XPC `generateBatch` retired 2026-07-24. |
| 12 — Bounded analysis and unified quality | Fast-depth registry shipping 2026-07-26 (typed `GenerationQualityReport` + fail-closed `QualityGateRegistry` verdict in telemetry notes on every finalization, live-verified). Same-day additions: the standard/canonical `deepReport` producer, per-take prosody gate verdicts on the bench sidecar (folded into history warnings), typed `languageASR` and `longFormContinuity` gates, and the advisory speaker-similarity dev metric. Composed standard-depth verdicts went live on the delivery bench 2026-08-01 (`bench-quality-composed.json`, proof run `macos-engine-20260801-010135-6607009f`): the sidecar prosody gate folds into `deepReport` with a fast-consistency guard and fail-closed missing analyzers. Canonical depth followed the same day: the promoted delivery-adherence rule v1 (per-preset signed expectations + intensity scaling in prosody profile v2, warn-first) emits a real `.delivery` gate per delivery take, the publisher banks the paired neutral-vs-instructed deltas, and the first canonical proof run (`macos-engine-20260801-024556-e826c4ec`, 18 delivery cells, seed 20260801) composed 3 pass / 15 warning / 0 fail across all seven gates. Threshold recalibration from the banked seed matrix landed 2026-08-05 (DP-21, gate algorithm v2): magnitudes and tiers calibrated from 272 paired rows, fearful's arousal direction corrected to its instruction semantics, whisper breathiness/sad variation/angry-happy tension bound as new expectations, and genuine adherence misses (surprised pitch rise, fearful fast-pacing) deliberately kept warning at seed values — see the delivery-harness results ledger. Remaining open: optional MOS-proxy. |
| 13 — Benchmark/history v3 | Live 2026-07-29: the first schema-v3 records are committed (three clean `phase0-cli-control-*` engine records plus one exploratory run that also exposed and fixed the summarizer's v3 pin). `benchmarks/schema-v3.json` adds the typed quality identity to generation takes (pass/warning only, five fast gates required, machine-code issues); v1/v2 records stay valid immutable history; the publisher stamps v3 only when every take carries the identity. The UI benchmark checkers folded the same identity 2026-08-01: ui-generation records now publish v3 (first: the focused `v3-fold-proof` record `macos-xcui-benchmark-20260801-003208-403989cf`); the canonical iOS matrix published its first v3 record 2026-08-01 (`ios-xcui-benchmark-20260801-132415-abbec96b`). |
| 14 — Organization and retirement | Closed 2026-07-23 (14a + 14b): compatibility SPI retired, actor-owned loading/metadata/priming/clone artifacts, clone conditioning epoch-bound end to end. |

## Resume here (2026-08-22)

**DP-27 foundation completed and DP-28/DP-30 screening underway; production copy unchanged
(2026-08-22, macOS/CLI):** the pinned primary-source report confirms that Vocello's
CustomVoice path matches upstream ChatML and sends the resolved delivery instruction, while
VoiceDesign combines identity and delivery and Base cloning has no supported instruction channel.
Official 1.7B CustomVoice English instruction-following scores (77.3 APS / 77.1 description /
63.7 role play) and the local DP-26 null prompt comparison establish probabilistic adherence rather
than a missing wire or a universal wording fix. A versioned experiment contract now compiles six
attributable prompt arms, English/Mandarin wording, five independent talker/subtalker sampler
combinations, VAD/acoustic expectations, contradiction checks and stable digests. The split-safe
corpus covers nine native speaker-language cells plus four cross-language sentinels across three
lengths and neutral/congruent/conflicting text; non-English copy is explicitly provisional pending
fluent review.

The new serial CLI runner binds every experiment to the binary, exact shipped instruction, script,
speaker, seed, model variant, sampler, receipt and audio digest, retains failures, resumes safely,
and never publishes. CLI generation JSON now exposes the exact instruction character count and
digest used by the request. An actual built-binary plan smoke produced the expected 936 paired
rows for one seed (648 native and 288 sentinel). Its first one-row run exposed a false green: a
managed-sandbox model abort was retained in state but the command exited success. The runner now
fails on any failed/blocked row or zero completions; the approved native-MLX retry passed in 11.9
seconds with an exact instruction receipt, paired neutral reference, WAV digests, and acoustic
layer. The layered local evaluator composes deterministic
acoustics, ASR, identity, relative UTMOS, full SER posterior and a grouped-validation dimensional
model with uncertainty/abstention; listener cohorts and the fail-closed promotion decision add
paired bootstrap, Holm correction, locale fluency and speaker/script distribution rules. Focused
Swift compilation and 131 Python tests passed while landing this foundation. DP-28 through DP-32
retain the blinded calibration, fluent corpus review, real factorial screens, untouched
Speed/Quality listening, and any qualifying prompt promotion. No iPhone work is required for this
macOS/CLI arc. See
[`qwen3-tts-emotion-tone-research-2026-08-22.md`](reference/qwen3-tts-emotion-tone-research-2026-08-22.md)
and the authoritative roadmap.

The screened runner now seals the CLI plus runner/analyzer/gate/profile source bytes, allows only
named development subsets, refuses every confirmation subset, summarizes one controlled factor,
and retains privacy-safe failure classes. A blinded calibration-session tool randomizes audio and
withholds speaker, script, preset, seed and features; the evaluator accepts dimensional labels only
from complete cohorts of at least three independent listeners with fluent-language coverage and
measured inter-rater concordance. Real DP-30 screens rejected two tempting global changes. Across
Ryan and three English sentinel voices, shipped prompt copy achieved 10/24 advisory acoustic passes
versus 5/24 for the official-minimal arm. Across three Aiden seeds, sampler rankings changed by seed:
consistent-matched led the two-seed extension at 10/12, three alternatives reached 9/12, and the
first seed had a three-way 4/6 tie. Happy and Surprised remained the recurrent weak cells. This is
enough to preserve the shipped prompts and Expressive default and move to per-preset,
speaker-diverse screens; it is not enough to promote any change or close DP-28/DP-30.
The first blinded DP-28 packet is also generated locally: 27/27 instructed clips and all nine
paired neutral references completed across Aiden, Ryan and Vivian, three script lengths, and
Happy/Angry/Sad. Its public manifest exposes no requested label or speaker/script/seed identity.
It remains intentionally unqualified until three independent listeners supply complete ratings;
no synthetic or requested-preset labels can substitute for that evidence.

**DP-26 Custom Voice delivery screen completed; QC fixed, prompt candidate rejected
(2026-08-22, macOS/CLI):** the new resumable matrix exercised every checked-in Built-in
Voice speaker (9) against every shipped delivery preset/tier (8) over five fixed seeds,
for 360 instructed attempts. Exact telemetry digests matched every requested instruction,
proving the macOS/CLI product path sends the selected delivery text into the engine. The
baseline accepted 169/360 product takes; analysis of preserved rejected WAVs measured
182/360 acoustic-adherence passes and held-one-speaker-out UAR 0.342. The gap exposed an
independent Fast-QC defect: 29 delivery and 9 neutral-reference clips were rejected because
ordinary 350 ms cadence pauses exceeded a punctuation-derived count, even though none had
an analyzer pause of at least 1.2 seconds and 13 rejected deliveries otherwise passed the
delivery gate. Audio QC algorithm v4 now reports excess ordinary cadence as a warning and
retains hard failure for repeated suspicious-scale gaps or a context-sensitive egregious
gap (1.2/2.0 seconds). The exact previously failing Uncle Fu reference seed passed live.

A debug-only `candidate-v2` prompt set then ran the identical 360 cells. It cleared every
neutral reference and left only two genuine Sad clips with approximately two-second gaps,
but did not improve acoustic adherence (182/360 in both arms) and reduced held-speaker UAR
from 0.342 to 0.306. The candidate is therefore rejected and all shipped instructions stay
unchanged. `surprised.strong` was the only exploratory cell to improve both adherence
(+4/45) and held-speaker recall (+0.200), with paired exact p=0.289; it may only advance
through a fresh pre-registered holdout. The harness now distinguishes product acceptance
from acoustic diagnostics, preserves every typed failure in the denominator, validates
speaker/seed/instruction identity, records speaker-balanced and held-speaker results, and
emits paired comparison artifacts. Its deterministic PCM/F0/pause contracts pass, but the
screen is Speed-only, one English medium script, and predicts request labels rather than
human-recognized emotion. AV-07 remains open for an independently labelled, frozen
multi-speaker/script/language holdout before the analyzer can become promotion authority.
See [`docs/reference/delivery-harness.md`](reference/delivery-harness.md) and DP-26 in the
authoritative roadmap.

**MD-3 progress rendering and observer races isolated on the physical iPhone (2026-08-22):** a
complete Custom cancel/restart/relaunch-adoption/Ready/remove diagnostic first proved exact
determinate measurements at 19%, 36%, 50%, 82%, and 96%, about 12:1 fill/track contrast, stable
900×18-pixel crops, clean deletion, and no lifecycle divergence. A subsequent run exposed a real
rendering edge case: at 99.95% exact bytes, a six-point rounded capsule was pixel-indistinguishable
from full. `IOSModelProgressPresentation` now reserves one rail-thickness segment at the trailing
edge until byte completion, while the accessibility value and copy continue to report the exact
fraction. Host analysis compares pixels against raw-byte fraction, rejects a visually full
incomplete bar, and handles rounded capsule caps rather than averaging them into the background.
Later run `ios-xcui-model-download-20260822-065527-14a7597e` again completed cancellation,
adoption, authenticated installation, removal, and relaunch persistence with four accurate visual
samples; its journal proved durable progress jumped from 94.06% directly to 100%, so the original
strict at-or-above-95 capture rule correctly produced `missing-progress-milestones`. The procedure
now records the first exact incomplete sample in the five-point band below 95 instead of inventing
an intermediate value. Run `ios-xcui-model-download-20260822-071543-b7080a04` then exposed an
XCUITest-only observer race when one 71.98% sample crossed two thresholds and the row became Ready
between repeated mutable-element queries. Crossed milestones now reuse one immutable byte/frame/
accessibility/action/screenshot sample. The phone became temporarily unavailable while failure
forensics were being collected, so no run from this refinement sequence counts toward the final
two-consecutive-diagnose plus acceptance gate. Focused host contracts, Swift parsing, and shell
validation pass; MD-3 remains open pending the physical-device sequence.

**MD-3 autonomous model-management diagnostics implemented and first live divergence isolated
(2026-08-21, desk + physical iPhone):** the opt-in physical-iPhone lane now has `diagnose`,
`queue`, `acceptance`, `soak`, and
`recover` scenarios over one bounded isolated root. A debug-gated schema-v1 journal correlates
URLSession adoption and completion parking, logical request and operation generations, verified
files, staging/ledger/publication state, model-manager refreshes, deletion, and five-second
heartbeats across app relaunches. Transfer progress now uses stable whole-file/range slots, so a
replacement task cannot double-count retried bytes; the visible custom bar renders the exact
logical byte fraction, then switches to honest indeterminate finalization, verification, and
installation activity. XCUITest captures row and bar milestones, and the host emits a correlated
timeline, first-divergence diagnosis, quantitative visual measurements, and contact sheet even
after failure. The first correlated device run,
`ios-xcui-model-download-20260821-184903-1b372030`, collected 786 cross-layer events and proved the
first divergence at the coordinator: after visible removal, the new logical request recorded zero
durable bytes but its first queued snapshot reused the deleted tombstone's complete
1,708,583,689-byte count. The network transfer, all 14 verifications, atomic publication, installed
ledger, and installed view-model snapshot subsequently completed; the test nonetheless waited for
a determinate bar that was correctly absent at the falsely reported 100% and failed to emit a
structured timeout observation. The fix now starts a new zero-byte logical request after deleted,
cancel-requested, or installed terminal ledger state while preserving resumable evidence for
interrupted/failed work. The test uses the specified 300-second no-advance bound, records the row
before failing, returns immediately to preserve the exact isolated state, and the host no longer
infers a Ready failure without a post-install UI observation. Mac deterministic tests, generic iOS
compilation, the full quick gate, and the correlated host replay pass. No second phone run was
started after the maintainer took the device. MD-3 remains planned; closure still requires two
consecutive diagnostic passes and one complete three-model acceptance pass.

**Autonomous-validation remediation first pass closed five items (2026-08-21, desk):** AV-01,
AV-02, AV-03, AV-04, and AV-11 are now done in the roadmap. Python T1/T2 execution is recursive
and discovery-complete (with a structural zero-test/free-function contract); designated critical
paths can no longer fall through to `repository-other`; promotion schema v2 derives exact
platform evidence from Speed, Quality, mode, language, delivery, and lifecycle capabilities and
labels unsupported combinations; baseline comparison fails on added/removed cells and one-sided
metrics unless a reviewed versioned migration maps them; and marking-equality runs warning-strict
with context-managed sidecars. AV-05 implementation also landed: every macOS CLI benchmark path
builds whole-module `-O`, and publication verifies a hash-bound optimized-build sidecar while
history comparisons remain optimization-specific. The new route was live-built successfully on
the canonical Mac, its provenance resolved to `-O`, and its embedded version check returned exactly
`vocello 2.4.0`; AV-05 stays open until a clean focused benchmark record is captured because the
current checkout also contains the retained Settings work. AV-06 through AV-10 also remain open because their gates
require repeated clean trend records, independently labeled holdout/cohort evidence, isolated
physical-device reruns, or a new real-browser CI lane; none was relabeled complete from source-only
work. The authoritative plan is `autonomous-validation-remediation-2026-08` in
`config/roadmap.json`. The final full project-input run passed both recursive Python roots (105 +
908 tests; 1,013 declarations reconciled by the inventory), all governance/benchmark-history
validators, and the XCUITest workflow contract.

**Autonomous-validation audit completed and remediation registered (2026-08-21, desk):** the
repository-wide source/fixture/live review is pinned at
[`docs/reference/autonomous-validation-audit-2026-08-21.md`](reference/autonomous-validation-audit-2026-08-21.md).
It inventories the complete test, benchmark, voice-analysis, promotion, website, and release
evidence chain and records an aggregate 82/100 assessment with no P0. The three P1 roots are an
incomplete curated Python lane (78 unittest cases omitted plus one pytest-only module that
unittest discovers as zero; direct pytest reproduced 3 stale-test failures), broad critical-path
fallback to `repository-other` in evidence-impact routing, and promotion minima narrower than the
Quality/language/delivery/analyzer capabilities they can sometimes authorize. Six P2 and two P3
roots cover baseline completeness, shipping optimization identity, trend fragmentation, prosody
holdout validity, multilingual cohort breadth, stateful device-lane isolation, real-browser web
coverage, and one resource leak. `config/roadmap.json` now owns AV-01..AV-11 under
`autonomous-validation-remediation-2026-08`; existing F-03, F-05, and F-14 are cross-referenced
rather than duplicated. Full project inputs (906 curated tests), macOS deterministic tests/build,
generic iPhoneOS app/logic compilation, and website checks pass. The native routes required their
normal SwiftPM/Clang cache and Xcode runtime-service access outside the managed sandbox; no cache,
dependency, model, device state, benchmark history, product source, or uncommitted Settings work
was changed by the audit.

**Voice Models lifecycle controls made explicit (2026-08-21, desk):** the dedicated model
destination now leads with an `N of 3 ready` overview beside the managed storage total. Each model
uses one compact text-and-symbol status, then exposes only the actions valid for that state:
Install, Update plus Remove, Repair plus Remove, Retry, Cancel download, or direct Remove for a
ready package. Removal no longer requires discovering an ellipsis menu; the visible destructive
action still opens the existing named confirmation. Controls retain 44-point targets, reflow at
accessibility sizes, and preserve all lifecycle identifiers and model-operation behavior. The
source contract, model-download XCUITest, iOS app guide, and UI reference were updated together.
The targeted 16-test Settings contract and generic iPhoneOS app/logic compilation pass on the
final source.

**Voice Models density and progress truthfulness refined (2026-08-21, desk + paired iPhone):** screenshot review
showed that the first explicit-action layout still stacked the status and every action vertically,
and that an adopted transfer could render a full bar while remaining non-terminal. Ordinary text
sizes now keep a sole state-valid action beside the icon/name/metadata/status summary; only
two-action and accessibility layouts stack controls. The overview drops its redundant multi-line
helper, while ordinary-size actions share one 112-point capsule width and retain 44-point hit
regions. The initial progress refinement reserved symbolic lifecycle fractions below Ready; the
subsequent MD-3 diagnostic work above supersedes that presentation with exact determinate transfer
bytes and indeterminate finalization phases. Only `Ready` is terminal, and MD-3 remains open until
adopted background work publishes the authenticated payload and reaches it.
The physical-device Settings layout walk passed at Default, AX-L, and AX-XXXL and captured both
Settings surfaces; its Default Voice Models evidence fits all three rows in one viewport and shows
logical transfer completion at the staged 90% `Finishing` state. The encompassing smoke run's
Settings walk and long-form journey passed, while its general journey remained red when the known
MD-3 adopted Design transfer moved from `Finishing` to `Retry Needed` (`NSURLErrorDomain -999`)
before a later launch restored all three rows to Ready.

**Redesigned Voice Models device procedure exercised; adoption/finalization stall reproduced
(2026-08-21, physical iPhone):** the dedicated lane now normalizes stale isolated state through the
current visible Cancel/Retry/Remove controls, verifies each textual status has exactly its valid
action, and adds a real cancel-confirm-restart journey before background/process relaunch. Run
`ios-xcui-model-download-20260821-154031-2a32aa4c` passed navigation, stale Custom removal,
Not Installed/Install, Downloading/Cancel, cancellation confirmation, clean restart, and relaunch
adoption. It then stalled after retry with ledger bytes equal to the 1,708,583,689-byte total and all
14 identities recorded as verified, but without the 1.33 GB payload in staging or a terminal
diagnostic. Two read-only device snapshots showed no movement for more than ten minutes, so the run
was stopped as a live-reproduced failure rather than left in its previous one-hour blind poll. The
XCUITest now fails after five minutes without visible progress, captures the stalled row, visibly
normalizes the isolated root, and restores the canonical snapshot. Follow-up run
`ios-xcui-model-download-20260821-161217-41fab182` compiled and exercised that revised procedure on
the paired phone: after the 300-second no-advance verdict at visible progress `1.0`, it confirmed
Cancel Download, returned the isolated Custom row to Install, relaunched without the test root, and
verified all three canonical rows still Ready before emitting the expected failure. The full
three-model install/reuse/delete acceptance remains red under MD-3 pending the delivery
finalization fix and a fresh PASS.

**iOS Settings information architecture rebuilt and visually compacted (2026-08-20; focused device
acceptance PASS):** the title-free landing page keeps the task-first Audio, Models & Files,
Accessibility, Privacy, and About organization, but a screenshot-driven follow-up removed the
oversized system-list presentation. Settings now follows the same compact hierarchy as Voices and
History: tracked 11-point section eyebrows, 36-point tinted utility tiles, subheadline labels,
caption details and values, 52-point minimum rows, quiet single-layer panels, and the shared floating
dock. Real semantic `Toggle` controls use branded 44-by-26-point switch chrome inside 44-point hit
regions; variation remains a menu-style `Picker` with a verified 44-point target. The compact
version/build row replaces the old oversized logo footer. Model lifecycle management lives behind
the readiness summary in a dedicated Voice Models destination with a circular 44-point Back control,
accurate managed-byte storage, wrapping metadata/progress, one non-color-dependent `Ready` status,
and accessible 44-point lifecycle actions. Landing values and
model controls reflow at accessibility Dynamic Type sizes, bottom clearance derives from the shared
dock metric, and Clone guidance points to Settings → Privacy. Source/XCUITest contracts, the iOS app
guide, and the UI reference were updated together. The targeted 16-test Settings contract and generic
iPhoneOS app/logic compile pass. Physical-device smoke run
`ios-xcui-smoke-20260820-175509-27fb5f81` captured the compact landing, About/dock-clearance, and
Voice Models screens at Default, AX-L, and AX-XXXL sizes; the focused Settings layout walk passed in
179.020 seconds and the long-form journey passed in 288.487 seconds. The broader smoke journey's
Settings traversal also passed, but that method later failed because the phone did not contain its
required saved clone fixture `A_warm_elderly_woman` (2/3 methods passed; the lane therefore remains
red). The earlier performance lane `ios-xcui-perf-20260820-171602-051a70d8` passed all 9 scenarios,
including Settings scrolling and active on-device generation. The earlier isolated model-download lane
`ios-xcui-model-download-20260820-171400-5d11dc29` reached Voice Models, then failed closed before
deletion because its fixed test-owned support root already contained Custom; no model was removed.
The updated procedure now visibly normalizes that fixed root instead of requiring it to be empty;
the subsequent 2026-08-21 live result and remaining blocker are recorded above.

**Engineering-review remediation is now tracked in the roadmap (2026-08-19, desk):**
`config/roadmap.json` is the sole status authority for the 14 findings in
`VOCELLO_ENGINEERING_REVIEW_2026-08-19.md`. F-01, F-04, and F-11 are closed by the current tree;
eleven items remain: F-02, F-03, F-05, F-06, F-07, F-08, F-09, F-10, F-12, F-13, and F-14. Each
roadmap item records the current source evidence and a concrete closure gate. F-05 is the remaining
packaged-macOS release blocker. F-13 is continuous entitlement-risk hardening rather than a newly
discovered runtime defect. The external review stays descriptive and does not override the
roadmap, source, contracts, or release gates.

**F-01 closed — saved-voice review is transactional and iOS deletion ships (2026-08-20,
desk + phone):** `PreparedVoiceRepository` now owns a private 24-hour candidate tree, a committed voice
tree, and journaled commit/replacement/delete transactions. Interactive macOS and iOS flows prepare
an opaque candidate before review; Keep/Save commits it, while Discard, Cancel, and outside
dismissal remove it without publishing a catalog voice. Startup reconciliation expires incomplete
candidates, rolls a replacement interrupted before audio publication back to the old voice, and
finishes commits that crossed the audio publication boundary. Individual iOS saved rows now expose
an accessible, named delete confirmation; deletion stops a matching preview, clears runtime prompt
caches and matching Studio draft/handoff state, and leaves sibling voice-bank members untouched.
The wire schema is v2 with explicit prepare/commit/discard commands. Core recovery tests, XPC wire
tests, the saved-voice lifecycle machine contract, the full macOS deterministic test route, macOS
Release build, generic iOS device-SDK compile, and generic-device UI-test-bundle compile are the
closure evidence. The dedicated `scripts/ui_test.sh ios saved-voice-lifecycle` lane subsequently
passed on the paired phone (`ios-xcui-saved-voice-lifecycle-20260820-061924-73065027`, one test,
82.362 s): the genuine picker flow imported the staged reference, previewed the committed voice,
handed it to Clone, deleted the exact named row, and proved the matching Studio state was cleared.
Source provenance, crash baseline, XCUITest, crash delta, and result retention all passed. This
phone lane remains explicit QA rather than a deterministic publishing prerequisite.

**F-04 closed in governance; fresh release evidence remains candidate-bound work (2026-08-19,
desk):** release candidate production and public promotion are now separate. `release.yml` always
stops at a deterministically verified, signed, notarized, attested draft; candidate packaging and
internal TestFlight upload still never depend on models, XCUITest, or a paired phone. The new
`quality-promotion.json` contract binds public macOS publication and external iOS/App Review
submission to the exact tag, release-evidence bytes, changed-path classification, clean benchmark
record digests, build identity, canonical hardware profile, toolchain, executable hashes/UUIDs, and
explicit warning acceptance. `promote-release.yml` is the sole GitHub draft-to-public action and
revalidates both evidence layers. Project health now selects `ui-generation`,
`memory-qualification`, and `ui-perf` per domain instead of treating one generation matrix as proof
for memory, UI performance, model delivery, and supply-chain code. The next public candidate must
still run its exact-source lanes; this implementation does not relabel the August 1 records as
fresh.

**F-11 closed — CLI version identity is single-sourced (2026-08-19, desk):** the `VocelloCLI`
tool now embeds `project.yml`'s marketing version and build number in its Mach-O Info.plist section,
so all three version aliases report the product version instead of the retired `0.1.0` fallback.
A deterministic source-and-binary contract guards the target settings and exact output locally and
in macOS CI; unsupported bare `swiftc` builds report `unknown`. GitHub issue #86 remains
maintainer-owned and was not changed automatically.

**Development workflow is now strictly `main`-only (2026-08-19):** root and backend guidance no
longer permit alternate local development branches. Every agent task begins by proving the local
symbolic branch is `main`, and the trusted Codex pre-commit hook rejects commits from any other
branch before the deterministic gate runs. The emergency gate-skip flag cannot bypass this branch
check; pull-request and detached GitHub CI refs remain valid execution contexts only.

**ICI-2 closed — import restore device-accepted; `ios-clone-import-2026-08`
complete (2026-08-15, evening phone window):** the restored Files-import
flow passed end to end on the paired iPhone. At that checkpoint the benchmark voice
already existed and iOS did not yet ship saved-voice deletion (the gap later closed by F-01), so a
one-off test variant drove the full flow with a distinctly
named staged copy: picker → "Import voice" sheet with name and sidecar
transcript prefilled ("Good length" review card) → save → saved-voice row
(PASS, 47 s, screenshots local-only). The shipped
`ui_test.sh ios enroll-clone-fixture` lane passed via its idempotent exit
on the real fixture (`ios-xcui-enroll-clone-fixture-20260816-000822-4871903c`)
and smoke passed first try
(`ios-xcui-smoke-20260816-001059-4be45687`, both journeys, memory-pressure
sentinel clean) on the build carrying the import restore and the Built-in
Voice rename. The open-from-Files route remains a manual maintainer
spot-check. The saved-voice deletion backlog addition from that session is closed by F-01.

**Custom Voice renamed to Built-in Voice in all user-facing copy
(2026-08-15, maintainer call, desk):** the mode was named after upstream's
CustomVoice checkpoint and confused end users; it speaks with the built-in
speakers, so the label is now "Built-in Voice" (full name) and "Built-in"
in the iOS mode selection bar. **Every internal identity is unchanged**:
mode rawValue `custom`, model ID `pro_custom`, bench cells `custom:*`,
telemetry `mode: custom`, accessibility identifiers
(`generateSection_custom`, `sidebar_customVoice`, `iosModelStatus_pro_*`),
the CLI `vocello custom` subcommand, and benchmark history. Surfaces
updated: both apps' labels and error strings, the contract JSON model
display name (catalog rebuilt), CLI help text, README, website copy plus
its stale ten-preset delivery claim (corrected to the measured 8-preset
roster), README chart labels (regenerated), and every active doc;
`qwen3-tts-guide.md` keeps upstream checkpoint terminology with a naming
note. Verified: core-test, macOS build, iOS device-SDK compile, website
check, full deterministic gate.

**iOS clone-reference file import restored (2026-08-15, maintainer call,
desk):** the full route removed on 2026-08-01 for review-posture caution is
back — the Voices-tab "Import audio file" row (`voices_importAudioFile`,
`fileImporter` for WAV/MP3/AIFF/M4A), the open-from-Files document route
(`RootView.onOpenURL` + restored `public.audio` document type and
in-place-opening Info.plist keys), and the `IOSRecordVoiceSheet` import mode
(name from filename stem, transcript from the `.txt` sidecar). The backend
seam never left (`importReferenceAudio` / `LocalDocumentIO`). Restored with
recorded improvements: imports with no sidecar now auto-transcribe on-device
(macOS parity), a friendly duplicate-name pre-check before enrollment, the
cleanup guard that must not delete fingerprinted cache entries, and the
conditional discard label for the import-only >60 s hard-block alert. The
`ui_test.sh ios enroll-clone-fixture` opt-in UI lane and its
`VocelloiOSFixtureEnrollmentUITests` returned (the orchestration-contract
workflow entry had never been removed); the headless
`ios_device.sh enroll-clone-fixture` stays as the wipe-recovery route.
**Device acceptance pending the next phone window:** run the restored
enroll-clone-fixture UI lane end to end plus an `ios smoke` pass; the
open-from-Files route is a manual maintainer spot-check.

**DP-24 shipped — per-preset delivery tiers (2026-08-15, maintainer call,
desk):** the intensity selector stays retired on both platforms (as it has
been since 2026-08-02), and each preset now ships its measured-best tier:
`happy` and `angry` ship their `normal` copy — executing DP-22's
pre-registered branch (a), the only channel ever measured to carry the
happy/angry distinction (acoustic UAR 0.765 p=0.007 replicating the blind
2AFC 0.75) — while everything else keeps the DP-8 `strong` anchor.
`EmotionPreset.shippedIntensity` is the single source of truth; fresh picks
resolve it on both platforms; legacy drafts keep resolving exactly what
they stored. Known caveats recorded in DP-24's notes: the channel is
4-bit-specific (no expected audible gain on Quality), and DP-23's informal
happy-vs-Surprised listening check is recommended before the next release.
Dispositions: DP-9 and DP-23 **declined** with reasons (no deletion — the
tier machinery is the lever and the measurement surface; the cross-tier
candidate is moot under both-at-normal); **DP-25 registered** (measured
normal-tier gate floors, prosody profile v4, from DP-22's banked rows —
desk work). Core resolution tests cover the mapping; both platform
compiles and core-test green.

**DG-4 closed — the `doc-governance-2026-08` plan is complete (2026-08-15,
desk):** all 39 remaining documents were read and annotated in one
maintainer-directed sweep (5 domain rules, 8 ADRs, 26 reference/narrative
docs) — standing policies and living authorities are `active` with honest
`sourceOfTruth` bindings, decided ADRs and completed experiment records are
sealed `historical`, and the completed 2026-08 working order is
`superseded` → the rendered roadmap. Coverage: 88 annotated, 0 unannotated.
The sweep also cleared the two live freshness warnings by fixing real drift
(`benchmarking-procedure.md` still described the iOS perf lane as
pre-IUI-6 local-only; `macos-testing.md` gained the platform-aware
`ui-perf` note), and re-confirmed IUI-1–4 against today's script changes.
Five of seven roadmap plans are now complete; `delivery-prompting-2026-08`
holds only parked items.

**IUI-6 closed — the `ios-ui-2026-08` plan is complete (2026-08-15, same
day, second phone window):** the `ui-perf` registry kind is platform-aware
(one kind, per-platform scenario tables in `benchmark_history.py`), iOS
warn-only ceilings live in `config/ui-perf-thresholds-ios.json` (derived
from the three counted sessions, tightened so the P4 regression must
breach), and the `ios perf` lane publishes on a canonical-iPhone PASS
through the existing publication block. The frame probe gained a one-time
privacy-safe device-environment snapshot row (the registry's hardware
block needs device-truth load/storage/uptime) with a fail-closed stale-app
guard — found live when the first publication attempt failed on exactly
those schema fields. Warn path proven live
(`ios-xcui-perf-20260815-170208-89766d44` reported `passedWithWarnings` on
a real ceiling breach) and offline (checker self-tests). The first mint
was honestly flagged dirty-source/exploratory (publication code
necessarily uncommitted); the clean-source follow-up on the committed arc
is the canonical record:
`benchmarks/runs/ui-perf/ios-xcui-perf-20260815-173719-6e425c28.json`,
270-record registry validates. The iOS UI arc is done end to end:
instrument → baseline → audit → two measured fix waves (one revert by
measurement) → formalized registry. **Next: maintainer's call** — backlog
holds model-hoisted per-tab state, the long-form silent-reset UX gap, the
AX-XXXL cosmetic findings, P11, and UIKit text-editor `UIFontMetrics`
scaling; release timing stays an explicit maintainer decision.

**IUI-5 closed — wave 2 measured at baseline on the committed fix
(2026-08-15, phone window):** the counted chain restarted clean per the
recorded resume protocol — warm-up discarded, five counted `ios perf` runs
in one sitting (`ios-xcui-perf-20260815-150607-5bcff66e` …
`-154816-52e87368`, zero threshold warnings, thermals nominal; one
excluded transient on-device generation failure before run 1, engine-side,
healthy memory). Every confirmatory scenario holds the IUI-2 baseline
(settings-scroll −16%; the generation-active exploratory deltas match the
same-day pre-wave control from the part-1 bisect — cross-sitting drift,
not wave effect). Wave-level smoke passed first try
(`ios-xcui-smoke-20260815-155935-0de9a61f`, both journeys). Checklist
closed: the X4 large-type spot-check passed at AX-L and AX-XXXL via a
one-off XCUITest walk (clean at AX-L; four cosmetic extreme-size findings
recorded to backlog, headlined by the Generate capsule slipping behind the
grown dock at AX-XXXL), the `scrollsToTop` question dissolved with the P4
revert, and the D10b shipped-truth glance confirmed no visible delta.
Full after-table and reading in `docs/reference/ios-ui-refresh-2026-08.md`.
**Next: IUI-6 registry formalization — pure desk work** (platform-aware
`ui-perf` kind in `benchmark_history.py`, iOS thresholds contract,
harness-hash source list, warn-path exercise).

**IUI-4 closed — wave 1 measured on device (2026-08-13, phone window):**
smoke passed cleanly (`ios-xcui-smoke-20260813-170127-e0f9c5be`; the
pause-time abort was confirmed as the locked-phone biometry cancel, not a
code failure), then five counted `ios perf` runs
(`ios-xcui-perf-20260813-171216-3dba81a4` … `-175056-d09be357`) ran
back-to-back with nominal thermals and every report copied out between runs.
Against the IUI-2 baseline: the P1 target moved (sheet-present worst gap
178 → 159 ms, −11%, on a ≤3 ms-IQR metric), composer typing −11% and
settings scroll −9% hitch, tab-navigation worst gap −12%; history scroll was
an honest null (flat within IQR — the remaining row cost is wave-2 P2
scope); exploratory scenarios stayed within their designated variance. Full
table and reading in `docs/reference/ios-ui-refresh-2026-08.md`.

**Same day, continued: IUI-5 sub-wave A landed (2026-08-13, second phone
window).** The three core re-engineering mechanisms are in: P2 (flip-scoped
`IOSGenerationPerformanceGateModel`; `RootView` fully non-observing), P4
(stable-identity tab container — visited tabs keep their state; the new
`\.iosTabIsActive` environment replaces remount-teardown semantics), P3
(player per-tick publication split into a playback clock and a
boundary-rate karaoke clock), plus design pick D6. The two-lens adversarial
review confirmed P2/P3 clean and caught the P4 keep-alive inline-player
major (invisible audio + display-link leak after tab switch) before device
time; smoke passed on both the pre-fix and fixed builds
(`ios-xcui-smoke-20260813-182434-cb1e0832`,
`…-183632-cbbd2bb7`). Sub-wave B followed the same day at the desk: P6
catalog memo, P7 scroll-indicator task churn, X3 root environment moved
outermost (all bottom chrome and presentations now honor reduce-motion,
reduce-transparency, and the generation glass gate), X6 VoiceOver-adjustable
inline scrub; P11 deferred with its recorded downgrade reason; two review
minors fixed in-change. Sub-wave C (same day, desk): all seven small design
picks D1–D5/D7/D8 landed with a stale-copy sweep and a five-finding review
fixed in-change. Sub-wave D (same day, desk): D10a glass-gate unification
(the shared `IOSGatedGlassModifier` is now the sole `glassEffect` site;
parity verified in all four gate states) and the X4+D9 Dynamic Type program
(50 of 132 fixed-size sites adopted, ~80 kept fixed with recorded reasons,
karaoke scales base + active-word run together). Sub-wave E (2026-08-14,
desk): D10b token-namespace unification — all five legacy namespaces
(`IOSBrandTheme`, `IOSAppTheme`, `IOSCornerRadius`, `IOSDesignMotion`,
`IOSSelectionMotion`) absorbed into the canonical `Theme`; ~440 call sites
rewritten by a deterministic token map, value-identical by construction
(the feared drift lived only in never-shipped aspirational tokens, now
re-pointed to shipped truth with recorded deltas). The two-lens review
mechanically reproduced all 401 hunks under the map — zero rendered
deltas.

**Wave-2 close, part 1 (2026-08-14, phone window): the counted
measurement caught a wholesale regression and a same-day device bisect
attributed all of it to P4's keep-alive tab container** (+56% on the
tab-navigation scenario it targeted, +161% voices-scroll, generation-active
doubled; the wrapper taxed even single-mounted-tab scenarios; pre-wave
control reproduced baseline, container-only revert restored control
everywhere — full diagnostic table in the authority doc). **P4 is reverted
(`a7f22ad`)** per the wave's measured-delta discipline; state preservation
is re-scoped as model-hoisted state on the backlog. Two fixed-build counted
runs confirm recovery to baseline. Also recorded: the long-form runner's
silent-project-reset on an environmental mid-segment memory-pressure
cancellation (pre-existing UX gap, backlog) surfaced by the first smoke
run; the rerun passed. **Resume here: at the next phone window restart the
counted chain clean on the committed fix (one warm-up + five counted, one
sitting), then wave-level smoke plus the large-type / scrollsToTop /
D10b-confirmation spot-checks — that completes the wave-2 after-table and
closes IUI-5; IUI-6 (registry formalization) is desk work.**

**IUI-1 + IUI-2 closed — iOS frame-health instrument live with a measured
baseline (2026-08-12, phone window):** the acceptance run
`ios-xcui-perf-20260812-145449-41b82c87` passed 9/9 on the canonical iPhone
(idle sentinel 60.0 Hz at 0.006 ms/s — the pin holds and the probe is
near-silent at rest) and the three fail-closed refusals were demonstrated
against doctored copies of its real pulled evidence; five counted baseline
runs followed in the same sitting, all 9/9 with nominal thermals and tight
spread (sheet-dismiss 99.9 ±0.4 ms/s IQR). The baseline table and its
provenance live in `docs/reference/ios-ui-refresh-2026-08.md`. Standout
targets for the IUI-3 audit: sheet present/dismiss (~100 ms/s, repeatable
178 ms presentation stall), player scrub (~107 ms/s), history scroll
(~80 ms/s @ 400 rows), tab navigation (76.5 ±1.5 ms/s — consistent with the
unported macOS root-shell observation finding), and generation-active's
engine/UI contention (132 ms worst gaps). Two device-window lessons recorded:
the seeded-history sentinel keyboard race (fixed, `c0dba9c`) and the
copy-reports-out retention protocol step.

**Same day, continued: IUI-3 closed and IUI-4 wave 1 landed (2026-08-12).**
The four-lens audit ranked 30 verified findings into the maintainer
pick-list (authority doc has the table); the maintainer gave wave 1 the go
as proposed and approved all four design groups for wave 2. All ten wave-1
fixes landed in `2f76b8a` (P1 sheet-stall rework with an activation-epoch
session guard, P5 lazy History menus, P8/P9/P10 dead-wiring removals,
X1/X2/X5/X7/X8 input + VoiceOver one-liners), adversarially reviewed, both
iOS compiles and the UI test bundle green. The device close-out (smoke +
five counted after-runs, reports copied out between runs) completed
2026-08-13 — see the newest block above. Wave 2 (IUI-5) follows: core
re-engineering P2/P3/P4 + P6/P7/P11 + X3/X6 plus the approved design picks
(D1–D10, Dynamic Type program X4+D9, theme unification D10).

**IUI-1 authored — iOS frame-health harness (2026-08-12, desk work):** the
`ios-ui-2026-08` arc's instrument is fully authored and wired: `IOSUIPerfFrameProbe`
(CADisplayLink pinned to the app's 60 Hz cap, per-tick observed expectations, 500 ms
JSONL blocks into the devicectl-pullable caches tree), `IOSUIPerfHistorySeeder`
(production-model GRDB seeding, 30 s scrubbable fixture WAV), the nine-scenario
`VocelloiOSPerfUITests` class, `scripts/check_ios_ui_perf.py` (structural gate +
fail-closed 55–65 Hz cadence band + canonical-iPhone proof; no thresholds or registry
publication until IUI-6) with offline self-tests, the `ui_test.sh ios perf` lane +
`ui-ios-perf` workflow entry, and the MetricKit animation/responsiveness advisory
aggregates. Pre-arc housekeeping registered the missing `ui-ios-delivery-cohort`
workflow (the lane died at ledger init). **Next phone window (window 1): IUI-1 device
acceptance (one clean 9/9 PASS + three scripted fail-closed refusals) back-to-back
with the IUI-2 baseline (1 discarded warm-up + 5 counted runs).** IUI-3's audit is
desk work and can start meanwhile. Authority: `docs/reference/ios-ui-refresh-2026-08.md`.

**iOS chunked delivery + compliance close (2026-08-11, phone window):** both remaining
arcs closed in one sitting. **MD-2 landed and default-flipped** (commit `f497fb8`): task
identities are schema v2 with byte-range qualification (v1 fails decode closed),
reconciliation/parking/adoption key per range slot, background sessions fan chunk tasks
to the daemon up front at 128 MiB, and a completed-range sidecar makes the sparse
partial crash-resumable. A 3-lens/16-agent adversarial review confirmed 12 findings
(terminal-adoption hang, cancel leaving daemon tasks streaming, sparse-partial 416
dead-end, identity-exact claims, diagnostics retention sized for per-range metrics) —
all fixed with regression tests in the same commit; 373-test suite green. The iOS
default flip is an explicit maintainer call recorded in `model-delivery.md` as a
deviation from the pre-registered lane A/B (evidence: the macOS 87.1% controlled
comparison on the identical code path plus same-day live canonical delivery — the
legacy 2–6 MB/s crawl versus chunked multi-gigabyte installs in minutes on the same
phone). **CP-2 closed — marking is proven live on both shipping platforms**: the
re-pinned 2026.08.06.1 catalog delivered all three Speed artifacts to the iPhone
through the fail-closed chunked path; headless marking acceptance passed (run
`ios-engine-20260811-180909-307642b3`); the pulled shipping WAV carries the full
provenance chunk (ISFT `Vocello 2.4.0`; ICMT with `version=2.4.0` and
`marking=AudioSeal:0x56C0`) and the pinned reference detector reads prob 1.0000
decoding `0x56C0`; the deterministic device gate passed
(`ios-gate-20260811-141259`). Plans `model-delivery-2026-08` and `compliance-2026-08`
are complete; the roadmap CP-2/MD-2 gates are the detailed authority. Paid-launch
gates (C2PA, Code of Practice, legal review) remain recorded, not scheduled.

**Download-throughput fix (2026-08-08, maintainer-requested investigation):** the
"speeds all over the place, always slowing to a crawl" report root-caused to Hugging
Face's CDN shaping throughput per connection (~20 MB/s burst then 2-6 MB/s sustained,
measured live) while every file rode one URLSession stream; the old dead chunk path's
`max(64 MiB, size/6)` split — six ~355 MB chunks with a lone straggler — explains the
2026-06 "tapering" revert. The chunked work-queue mechanism (64 MiB ranges + quarter-size
tail, bounded workers, per-chunk retry, active sibling cancellation, largest-first
dispatch, session-namespaced task keys with an optional per-worker-session mode) landed
with twelve deterministic tests, then the tuning-policy controlled comparison (interleaved
n=6/arm, `docs/reference/model-delivery.md` Tuning policy) measured **median 232.6 s →
30.0 s (87.1% improvement, ~57 MB/s)** with zero retries/duplicates and run-to-run
variance collapsed from ~100 s to ~2 s, so the macOS/CLI defaults flipped in the same
arc. Chunk transfer metrics now attribute bytes to their file, keeping `wireBytes`
delivery evidence exact under chunking. Speed-display fixes rode along (skipped files no
longer inject fake speed spikes; the long-pole SHA pass shows a visible verifying status
instead of freezing). iPhone keeps chunking off pending a range-qualified task-identity
schema, reconciler update, and its own device A/B at a future phone window.

**CP-1 close (2026-08-08, plan `compliance-2026-08`):** the Article 50 posture item is done
as far as it reaches before the paid launch. Option A verified complete after adding the
generator version to the provenance chunk (`version=` ICMT field, `Vocello <version>` ISFT,
bundle-resolved and omitted when unresolvable). Option D landed: the disclosure sentence
("If you publish audio of a cloned real voice, disclose that it is AI-generated. EU law may
require this.") sits beside the consent gate on both platforms, plus a README
Local-first-privacy bullet pair and a website Limitations "AI disclosure" entry (user duty
only there: shipping 2.4.0 predates the marking seam). The App Store submission runbook
gained its Article 50 checklist row beside the EU DSA row and DG-4 frontmatter. B (C2PA),
E (Code of Practice), and the real legal review stay paid-launch-gated, recorded in the
CP-1 gate. The same day, on the maintainer's go, all six CP-2 marking-weight uploads
landed and the contract, receipts, and iOS catalog re-pinned to the marked revisions at
`artifactVersion 2026.08.06.1` (production catalog validates complete). The Mac
post-change delivery evidence passed the same day: an isolated root installed
`pro_custom_speed` at the new 1,708,583,689-byte plan with the marking file byte-exact
against its pinned digest, verify + install clean, zero retries. CP-2's remaining tail is
iOS device acceptance plus the iOS delivery evidence at the next phone window.

**Article 50 marking arc (2026-08-06/07, plan `compliance-2026-08`, CP-2 stage 2 piece 3):**
every published WAV now carries both marks — the AudioSeal watermark (fixed payload
`0x56C0`, owned MLX port) embeds and the `LIST`/`INFO` provenance chunk appends at the
`GenerationOutputAdapter` publication seam, after staging finalization and before Fast QC,
flipping together as one byte-identity discontinuity. The registered `QWENVOICE_MARKING`
knob is the sole off-switch, and marking telemetry boundaries exist only when the pass
executes. The zero-peak promise is enforced by a **within-take** fail-closed gate in the
memory-qualification lane (`config/marking-peak-equality.json`); its originally designed
cross-run form was refuted by its own knob-off control — host-pressure drift of hundreds of
MB across back-to-back runs on the 8 GB canonical Mac — while the marking pass itself
measures +9 to +18 MB. Evidence, all clean-tree: canonical
`mac-memory-qualification-20260807-022819-3eb4d25b` (11/11 takes, marking interval 500–1100
MB under each take's peak), fixed-seed QC-neutrality pair
`macos-engine-20260807-023057-5275b724` / `-023242-fce41fcb` (8/8 verdict parity), and a
shipping CLI WAV the pinned reference detector scores 1.0000 with `0x56C0` decoding exactly
(knob-off outputs: 0.011–0.034, no chunk). The roadmap CP-2 gate is the detailed authority.
The maintainer-gated rollout completed 2026-08-08 (see the CP-1 close entry above); what
remains is iOS marking device acceptance plus the iOS post-change delivery evidence at the
next phone window.

**macOS UI arc (2026-08-04/05, plan `macos-ui-2026-08`):** the SwiftUI frame-health
lane `scripts/ui_test.sh macos perf` landed and proved itself (`9d283a9`; nine
scenarios, structural gate, fail-closed refusals), the five-counted-run baseline and
the four-audit review are recorded in
[`docs/reference/macos-ui-refresh-2026-08.md`](reference/macos-ui-refresh-2026-08.md)
(the plan's authority — History pipeline and root-shell invalidation are the measured
top costs), and the approved safe fixes shipped (`99d746d`: −615 dead UI lines,
Reduce Transparency at all 8 direct glass sites, 7/7 smoke green). **Refinement wave 1
landed the same day on the maintainer's go** (`4e0c7cf`..`20e14b2`: warm ink ramp,
motion family, mode-tinted focus rings, flip-scoped gate + History cache, ScaledMetric
adoption, AnyLayout field stability, the shared GatedGlass container; UI-5 done) with a
full before/after perf session — settings-scroll −19%, composer-typing −16%, and the
honest finding that History's ~3.1 s stall is per-row List materialization — which
**wave 2 then overturned with a Time Profiler sample**: the stall was the harness's
own accessibility queries on the app main thread; the History scenarios are now
exploratory and the app-real scroll cost is ~210 ms/s. **Wave 2 shipped the same day
(UI-6 done)**: store `@Observable` migration (sidebar-navigation 131→119 ms/s),
core-tested HistoryDeletionEngine, GenerationLifecycleExecutor dedup, and the
LiveStreamingPlaybackEngine player extraction — full deterministic suite, both
compiles, 7/7 smoke, and a clean 5-run baseline-v2 (settings-scroll measured a
verified-genuine 0.0 ms/s). **UI-7 then closed the plan the same day**: `ui-perf` is a
registered PASS-only benchmark kind with warn-only baseline-v2-derived ceilings
(`config/ui-perf-thresholds.json`), canonical-hardware-gated publication from the lane,
five offline self-tests, and a first live record. Baseline session 2 (2026-08-05
evening) then published six canonical ui-perf records through the live path — all
confirmatory scenarios consistent with baseline-v2, session two of the ~three the
hard-ceiling promotion rule asks for. The `macos-ui-2026-08` plan is
**complete**; History row thinning proceeds via Instruments whenever wanted.

The pre-UI-arc checkpoint (2026-08-01) follows.

Stages 0–3 of the adopted roadmap are complete (the 2.2 artifact promotion included);
Stage 4 closed with the kept 0.31.6 pin bump. **v2.3.0 was cut 2026-07-31 and v2.4.0 on
2026-08-01** (both explicit maintainer calls): 2.4.0 shipped the delivery-preset rework
(verified rewrites, Neutral as a real preset), iPhone long-form segment regeneration,
spoken-text normalization, and the runtime refresh — macOS published, iOS build 23
distributed to both TestFlight groups with review submitted. The f16 codec promotion
(artifactVersion 2026.08.01.1) landed post-release; users receive it when the next app
release bundles the new catalog. Its fixture rebind and memory re-qualification closed
2026-08-06 (finding 27, CM-5); the promotion's own delivery evidence is recorded in §R. The battery on the 2026.07.26.1 artifacts is more than
half banked, and its device lanes surfaced and shipped real fixes along the way:

- **Banked (committed, PASS):** three clean CLI engine controls (the first schema-v3
  records), three macOS UI controls, two clean iOS UI controls
  (`phase0-ios-control-1..2`; the wiped phone's benchmark clone voice was re-enrolled with
  the new opt-in `scripts/ui_test.sh ios enroll-clone-fixture` lane), the canonical
  29-take macOS matrix (`passedWithWarnings`, schema v2 pending the UI-checker
  quality-identity fold), and retained-memory qualification on both canonical platforms —
  the memory re-qualification predates the artifact re-pin and rides the deferred
  remainder below.
- **Fixes shipped by the battery:** the summarizer's v3 schema pin; the ui-lane long-form
  probe silently killing non-long-form runs; the iOS download-ledger artifact-update brick;
  clone priming on voice selection; a completed model load no longer discarded on late task
  cancellation (`VocelloQwen3Core`); the clone prime rerouted from a memory-spiking bounded
  completion (~2.0→5.1 GB resident on iPhone) to the ordinary prewarm; the project-health
  inventory now counts only git-tracked files. Model delivery additionally gained
  Wi-Fi-pinned downloads (`allowsCellularAccess=false`, retiring the Wi-Fi Assist LTE
  reroute that collapsed downloads to sub-MB/s), a pullable download-diagnostics mirror,
  and an autonomous transfer-health verdict in the opt-in
  `scripts/ui_test.sh ios model-download` lane (live PASS: 6.6/6.3/5.7 MB/s, zero retries,
  exact shared-component reuse).

The working order now lives in the adopted
[2026-08 roadmap](reference/roadmap-2026-08.md) (interleave-by-cost: Tier 1 no-phone
residuals plus the study's Gate 0 micro-benchmark, Tier 2 phone window, Tier 3 gated
performance block after the fixture rebind, Tier 4 carryover). Immediate specifics:

1. **Battery remainder completed 2026-08-01** (Tier-2 phone window): control 3 re-ran
   clean (`ios-xcui-benchmark-20260801-130748-c3630f44`, first schema-v3 iOS UI record),
   the canonical 29-take matrix published as the first canonical iOS v3 record
   (`ios-xcui-benchmark-20260801-132415-abbec96b`), both control evaluators PASS over
   the current-artifact trio, and `config/characterization-fixtures.json` is rebound to
   the 2026.07.26.1 identities with the mid-battery caveat recorded in its
   `rebindNotes`. Memory qualification on both platforms was already banked 2026-07-29
   against these artifacts (the only later memory-relevant change — the clone-prime
   reroute — strictly removes a transient spike, so the banked evidence stays
   conservative-valid; the task checkpoint is authoritative over the roadmap's
   redundant re-qual listing). Every take carries only the familiar
   `memory.pressure.soft_trim` advisory plus one warn-level design-short dropout,
   consistent with the R2a boundary finding. Tier-2 riders also closed: the
   iPhone-15-Pro floor-profile diagnostic (custom 2380 MB / design 2878 MB peak
   against the clamped 5000 MB budget — over 2.1 GB headroom, healthy pressure;
   exploratory-only by policy) and the iOS studio marketing recapture (README +
   website now show the completed-player state via the new opt-in
   `VocelloiOSMarketingCaptureUITests`). Desktop fixture staging is cleaned up;
   the two 656 KB staged reference files in the phone's app Documents were
   later found gone with the rest of the app container (finding 27) — that
   cleanup rider is moot.
2. **v2.3.0 released 2026-07-31** (maintainer call): the combined 2.2-promotion + Stage 1
   story is the headline (up to ~10% faster warm, ~280 MB less memory, ~1 GB smaller Speed
   footprint); notes in [`docs/releases/v2.3.0.md`](releases/v2.3.0.md) with the standing
   smoke-lane ledger. iOS build 22 ships the clone-prime and Wi-Fi-pin fixes that build 21
   carried as exposures.
3. **Delivery/clone fidelity verification program complete (2026-08-01):** the
   maintainer's preset-adherence and clone-tone complaints are now measured
   rather than perceived — see
   [`docs/reference/delivery-fidelity-report-2026-08-01.md`](reference/delivery-fidelity-report-2026-08-01.md)
   and OPTIMIZATION.md §P. The promoted delivery gate is calibrated from a
   banked 7-seed × 18-cell paired matrix (canonical composed depth live on the
   delivery bench), neutral cross-seed wander is quantified as by-construction
   (2.7 st / 2.0 Hz at shipping defaults; cohort bounds sit above baseline),
   clone identity measures strong (ECAPA 0.81–0.87 vs 0.10–0.39 negative
   controls), and the SER advisory + clone-fidelity lanes are standing tools.
   Product follow-ups recorded: dramatic/surprised instruction rewrites;
   optional engine-level neutral stabilization experiment. The adopted
   remediation tracks (R1 preset rewrites → R2 defect sweeps → R3 gated
   neutral experiment → R4 process riders) live in
   [`docs/reference/delivery-remediation-plan-2026-08.md`](reference/delivery-remediation-plan-2026-08.md).
4. **Tier 1 is complete (2026-08-01):** the UI-checker v3 fold, quality-report
   consolidation (composed standard verdicts on delivery benches), single-take
   normalization, and the iOS segment-regeneration implementation half all landed with
   evidence; Gate 0 ran and returned **no-go** (`benchmarks/OPTIMIZATION.md` §O — MPP
   never beats MLX on the floor and batch-1 is inexpressible at parallel scope), which
   withdraws the conditional fused-kernel Gate 2 from Tier 3. The optional delivery-chip
   audio rider was skipped.
5. **Tier 3 is complete (2026-08-01):** the sanctioned pin bump to
   mlx-swift 0.31.6 + mlx-swift-lm 3.31.4 passed its same-day A/B (warm RTF
   noise-band, QC identical, sampling byte-stable; swift-transformers 1.1.9
   became a direct dependency after the lm 2→3 Hub/Tokenizers
   externalization) and was the kept state — superseded 2026-08-05 by the
   governed swift-transformers 1.1.9 → 1.3.3 bump (PR #94, `f72bdb3`): full
   pin contract set, the §9.3 battery, and a 48/48 byte-identical paired
   seed×cell delivery A/B against the DP-18 baseline; the codec-bf16 revival probe came
   back negative (conv µ-throughput unchanged across pins — §N 2.3 stays
   parked with only the device-measurement path open); P1b re-tested null —
   a paired 6-seed soak resolved the initial cross-run read to +0.74% slower
   on medium (6/6 seeds), maintainer-ratified do-NOT, branch preserved; F7
   was not triggered, so the 26.0 floors stand. Full record:
   `benchmarks/OPTIMIZATION.md` §Q. With Gate 2 withdrawn by Gate 0, the
   2026-08 performance block is closed.
6. **Codec f16 promotion (2026-08-01, maintainer-approved, §R):** the speech
   tokenizer ships at half precision on both platforms as artifactVersion
   2026.08.01.1 — −234 MB resident during every generation, −341 MB installed,
   ~5% warm RTF cost accepted, waveform SNR 55-58 dB vs fp32, QC clean. All six
   repos re-pinned, catalog complete, URLs live-verified. Public disk-size copy
   and the update-available user path ride the next app release (bundled
   catalog); fixture rebind + memory re-qual ride that release's battery.

7. **Brand + iPhone clone-surface change (2026-08-01, post-2.4.0):** the public surfaces
   (README, website hero) feature the slogan "Premium voice studio. Proven performance.
   Private by design." The iPhone app deliberately dropped its Files-import and
   open-from-Files clone-reference paths (App Store review-risk posture; microphone
   recording and saved Voice Design references remain; the Mac app keeps file import).
   Benchmark clone-fixture enrollment moved from the retired
   `ui_test.sh ios enroll-clone-fixture` UI lane to the headless
   `scripts/ios_device.sh enroll-clone-fixture` diagnostics command
   (`QVOICE_IOS_DEVICE_ENROLL_VOICE_NAME`, registered knob; staged inputs are deleted
   after a clean enrollment). Ships in the next TestFlight build cut after 23 (no bump
   exists yet as of 2026-08-04 — build numbers are a maintainer call); build 23 in
   review still carries the import UI. **Reversed 2026-08-15 (maintainer call):** the
   full import route returned — the review-risk concern never materialized (build 23,
   carrying the import UI, passed beta review and remains the approved TestFlight
   build). The headless fixture command stays as the wipe-recovery route. See the
   resume block for the restore details.
8. **Intensity tiers collapsed to two (2026-08-01, maintainer decision):** "subtle"
   retired — its calibrated delivery-gate minimum effect was zero (below the prosody
   noise floor), an unverifiable control. Normal/strong remain (both ≥0.85 adherence,
   ~15% measured separation). Legacy subtle drafts degrade losslessly to custom text;
   decision record in `docs/reference/delivery-remediation-plan-2026-08.md`.
9. **R3 rate-only option parked (2026-08-01, maintainer decision):** the neutral
   sampling profile's rate half is not adopted standalone (register wander stays
   floored; failed gates do not ship by halves). Three unpark triggers recorded in
   the remediation plan; the Tier-4 long-form fixtures are the designated
   re-evaluation point. Tier 4 (long-form text-context carryover, design pass
   first) is now the active roadmap work.
10. **Tier 4 text-first landed (2026-08-01):** long-form planner v2 — R-tail orphan
   rebalancing keeps the final segment from becoming a pacing-visible orphan, never
   degrades boundary kinds, and never trades a paragraph pause away. Version-bumped
   identity (new plans re-derive segment IDs/sub-seeds; retained projects replay
   recorded plans), fixtures-first with self-calibrating estimates; the design pass
   removed one proposed rule (R-pull) as dead by construction before it shipped.
   Design: `docs/decisions/long-form-context-planning-v2.md`. The stage-2
   acoustic-carryover probe closed the same day as a pre-registered do-NOT (join
   pitch −16.4%, under gate; rate −54%; identity intact) — the second independent
   experiment pointing at missing register conditioning as the sole blocker
   (`docs/decisions/long-form-acoustic-carryover-experiment.md`). The 2026-08
   roadmap's substantive tiers are now all closed; opportunistic riders (MOS-proxy
   advisory, 60 Hz glass-gate measurement) and parked items remain.

11. **iPhone 6 GB floor step 1 green + adaptive residency LIVE (2026-08-02):** the
   f16 promotion reopened both questions and the phone window settled them. The
   clamped matrix (3,600 MB `iphone14pro` profile, fp32-conservative) passed all
   three modes with ~1 GB margin (peaks 2,109–2,372 MB vs the ≤3,300 bound) — the
   memory dimension of the 6 GB floor is green; the floor still moves only after
   real-A16 validation (step 2 needs hardware). Adaptive speech-tokenizer
   residency qualified the same night and ships enabled on the 8 GB device class:
   default-state retained-memory run PASS with engagement proven by load-event
   counts (one tokenizer load across the mode-switch sequence instead of three).
   Evidence + methodology notes: `docs/decisions/ios-6gb-floor-feasibility.md`.

12. **Delivery roster cut to eight (2026-08-03, maintainer decision on DP-10):**
   `excited` folded into `happy`, `dramatic` dropped. The shipped configuration was
   re-measured after the intensity control was retired — 18 seeds, one cell per
   preset — and gave cross-preset separability of UAR 0.311 against a 0.100 chance
   floor. Both retired presets recorded 0.056 recall (read at the time as below the
   floor; finding 13 corrects this — the interval contains the floor). Scoring the
   high-arousal cluster (`happy`/`excited`/`surprised`/`dramatic`) against only each
   other gave UAR 0.278 against a 0.250 floor (read at the time as 1.11× chance;
   corrected in finding 13 to "no detectable separability"). Rewriting the copy is
   ruled out by the same run: mean prosodic effect ran 6.5–9.5 across all ten presets
   and was **uncorrelated with separability**, so these instructions were not
   under-driving; every preset moves prosody hard and they all move it along the
   arousal axis (the "~91% vs ~55%" figures previously cited here are untraceable
   and retracted — finding 13). Same test that retired the intensity
   tier, now with a measurement behind it. Two related facts worth carrying forward:
   the directional delivery gate and separability **disagree** (`fearful` passes the
   gate on 1 take in 18 and has the best recall at 0.500), and `surprised` survives on
   probation at 0.222. Full record: `docs/reference/qwen3-tts-prompting-guide.md` §4.3
   and the removal note in `Sources/QwenVoiceCore/EmotionPreset.swift`.

13. **Delivery-control audit (2026-08-04, DP-11):** a full-codebase analysis plus a
   21-agent primary-source research sweep adversarially re-examined the DP-1..DP-10
   record. Corrections: the 10-way UAR 0.311 is decisively real (permutation
   p < 0.001, z = 8.7), but the high-arousal-cluster "1.11× chance" figure was an
   ordinary null draw (permutation p = 0.28, underpowered below ~1.5× chance) and the
   excited/dramatic "below chance" recall was a post-hoc selection artifact — the
   roster cut is sustained as a product decision with its statistical justification
   corrected. The "~91% vs ~55%" arousal/valence figures cited in earlier prose are
   untraceable to any source and retracted; the literature puts prosody-only valence
   at roughly a third of arousal's recoverability — a bottleneck, not a wall. New
   defects found: macOS silently ships the `.normal` tier through an
   `EmotionPickerView` state-sync bug (iOS correct; DP-8's ship-strong decision never
   actually took effect on macOS, and the aborted 2026-08-02 blind A/B may have
   auditioned the wrong tier), and the bench's fixed per-cell filenames overwrote the
   DP-10 evidence WAVs (one seed per cell survives). The built free-identification and
   2AFC human instruments were never run on real audio; running one ~30-minute
   calibration session is the audit's first recommendation, followed by productizing
   design-then-clone per-emotion reference banks (the strongest measured lever,
   corroborated externally) and reframing presets as stochastic delivery hints with
   pinned seeds. Full report, adjudications, and the week-one runbook:
   `docs/reference/delivery-control-audit-2026-08.md`.

14. **Move 1 of the audit runbook landed (2026-08-04, DP-12):** fix-then-listen.
   The macOS `.normal`-tier state-sync defect is fixed — instruction-string
   resolution moved into `EmotionPreset.matchInstruction` with strong-first
   tie-breaking (regression-pinned by
   `Tests/VocelloCoreTests/EmotionPresetResolutionTests.swift`), and every new
   preset pick resets to the strong tier; the CLI's bare `--delivery` names and
   default set now ship strong too, and its error copy no longer offers the
   deleted `subtle` tier. Bench evidence is retention-hardened: every delivery
   run archives its WAVs, manifest, and sidecars under
   `outputs/bench-archive/<runID>` (the fixed per-cell filenames that destroyed
   DP-10's audio keep overwrite semantics only in the live outputs dir), the
   manifest echoes each delivery cell's exact instruction, and the prosody
   sidecar fails closed unless the engine's own `promptChars` prove the
   instructed prompt outgrew its paired neutral. `scripts/delivery_separability.py`
   is algorithm v2: computed chance floors, Wilson recall intervals ("below
   chance" now requires the whole interval under the floor), an optional
   label-permutation null band with a p-value, fold-grouping honesty (the
   generation-ID fallback is reported as leave-one-take-out), and an
   exploratory/confirmatory designation. The blind listening session the audit
   ranked first is staged end to end by `scripts/delivery_listening_session.py`
   (build/run/score through the existing identification and 2AFC instruments,
   pre-registered exact-binomial decision rules, clone-transfer rows in the
   key); DP-12 completes when the maintainer's ~30-minute session is scored.
   Deferred deliberately: the dead intensity plumbing (DP-9 owns it) and the
   clone-transcript UI disclosure (Move 2 reworks that flow). Generating the
   session clips also surfaced a new engine defect, recorded as CM-7:
   `vocello generate --no-stream` reports success and prints an output path
   while publishing no WAV anywhere (the streaming path publishes correctly) —
   which also silently breaks the clone-fixture bootstrap in
   `scripts/lib/test_models.sh` if it ever needs to regenerate. The session
   clips were produced with streaming as the workaround.

15. **The calibration session ran and was scored (2026-08-04, DP-12 done):**
   146 blind trials, one listener (the maintainer; non-native English, so
   positives are read as solid and nulls as provisional). Pooled preset
   identification 26/88 = 0.295 against a 0.125 floor (exact binomial
   p = 2e-05) — the presets are perceptibly categorical, and the perceptible
   half matches the acoustic study's winners exactly: `calm` 0.55 and
   `whisper` 0.55 (p = .001), `neutral` 0.36 and `sad` 0.36 (p = .039). The
   high-arousal trio fails as identities: `angry` was never once named Angry
   (0/11, mostly Unsure), `happy` reads as Surprised, `surprised` reads as
   Unsure; `fearful` reads as **Sad** (6/11) — human confirmation of F2's
   low-arousal fearful rendering, and of the listener's own mid-session
   report that angry-group pairs sounded like "angry versus sad". The 2AFC
   block was engaged (anchors 4/4) and returned
   `no_measured_strong_tier_collapse`: the "at strong it all sounds angry"
   claim that emotionally drove the intensity retirement does not replicate.
   Sharper still: angry-group discrimination is above chance overall (0.75
   [0.551, 0.88]; one declared mis-keystroke on trial 141 was corrected from
   the listener's stated intent before unsealing any additional analysis) —
   anger is *distinguishable when named* while never being *identified
   unprompted*, the audit's "difference is not identity" made audible. The
   angry-vs-happy pairing (the canonical same-arousal/opposite-valence pair
   the literature predicts to be hardest) sits at chance at the strong tier
   and 0.75 at normal (n=4 each), and the angry group's strong-minus-normal
   drop is borderline (−0.33 [−0.61, 0.02]) — a hint, short of the
   pre-registered bar, that the strong angry copy is *harder* to pick out
   than the normal copy. Control pairs were **more** discriminable at strong
   (+0.50 [0.001, 0.812]), perceptually supporting ship-strong. The
   clone-transfer rows split decisively: `angry.clone` hit 0.667 — the only
   route through which the listener ever heard anger — while
   happy/sad/whisper clones read neutral-ish because their single-shot
   VoiceDesign references never audibly carried the emotion; the lossy hop is
   instruct→reference, not reference→clone, so Move 2's reference banks need
   curation (generate candidates, keep the ones that audibly land), exactly
   the pitfall the audit's prior-art review flagged. Listener self-agreement
   on exact repeats was 0.333, which caps the agreement any automated judge
   can ever reach with this ear. Decision consequences: the 8-preset roster
   splits into a perceptible half worth featuring and a decorative half to
   reframe as hints; the angry/happy/surprised nulls await the optional
   crowd panel before any further roster surgery.

16. **Move 2 landed: curated emotion reference banks (2026-08-04, DP-13):**
   `scripts/build_emotion_reference_bank.py` turns the session's lesson into a
   pipeline — generate N VoiceDesign candidates per emotion against a neutral
   anchor, score with the pinned SER advisory plus ECAPA identity-to-anchor
   plus prosody deltas (strictly after generation; 8 GB rule), select the
   emotion-passing candidate *nearest the anchor's identity*, and enroll
   winners as ordinary saved voices — banks work in every existing clone
   surface today with zero engine changes. The first real bank (Warm
   Narrator) enrolled SER-verified happy/sad/angry references and honestly
   refused whisper (VoiceDesign rendered soft-but-voiced speech, not whisper
   phonation; a breathiness criterion is the recorded follow-up). The
   end-to-end proof: clone identity 0.81–0.89 throughout; **sad 3/3 and
   angry 3/3 SER-categorical** — against the session's uncurated 0/3 sad —
   while happy's clones read angry despite a happy-verified reference: the
   arousal survives the clone hop, the valence did not (per an instrument
   with a measured angry-bias on this voice, so audition owns the final
   word on Happy). The silent x-vector fallback is now disclosed on both
   platforms ("Ready — identity only" on macOS; the iOS save-voice caption
   states that the transcript is what carries pacing and emotion).
   Follow-ups recorded in DP-13: the grouped persona/delivery picker UI and
   the whisper breathiness criterion. Reference:
   `docs/reference/emotion-reference-banks.md`. **Closed by ear the same
   day:** the maintainer auditioned the bank in the freshly built app
   (informal, sighted) and reports the voices sound as intended — including
   Happy, resolving the proof run's one open case in the bank's favor (the
   SER angry-reading on Happy clones stands as an instrument caveat only).
   First real use also surfaced one more status/control disagreement: the
   clone readiness note said "Ready to generate" beside a Generate button
   disabled by the one-time cloning consent. The readiness descriptor is now
   consent-aware on both platforms, so the note and the button agree.

17. **Move 3 landed: the delivery UI tells the measured truth (2026-08-04,
   DP-14):** the roster split from the calibration session is now data with
   provenance — `EmotionPreset.distinctDeliveryIDs` holds the four presets
   the listener identified above chance (neutral, calm, whisper, sad), the
   other four are directional hints, and a Core test pins the split as an
   exact partition of the live roster. The macOS delivery menu is sectioned
   (Distinct deliveries / Directional hints / Custom) and shows a shared
   advisory whenever a hint is selected; the iOS sheet gets the same
   sections, the advisory as the hints footer, and honest per-preset copy
   that names the measured confusions (happy "can read as surprise",
   fearful "can read as sad"). Preset ordering in `EmotionPreset.all` is
   untouched, so bench cells and harness identities are unaffected. The R6
   remainder — regenerate-with-new-seed and pin-this-seed as first-class
   take controls — is scoped and parked as DP-15: the request plumbing
   exists, but persisting a take's seed needs a History schema migration,
   which earns its own arc. With this, all three moves of the
   delivery-control audit are complete.

18. **Bank picker UX landed: personas with a delivery choice (2026-08-04,
   DP-16):** emotion reference banks now present as what they are — one
   voice with curated deliveries — instead of flat name-suffixed list
   entries. `VoiceBankCatalog` (QwenVoiceCore) resolves grouping from the
   enrollment naming convention alone (base name + "(Suffix)" siblings whose
   suffix matches a live preset; everything else stays standalone), with ten
   Core tests pinning the contract. macOS collapses bank members to one
   "· voice bank" row in the clone source picker and adds a Delivery menu;
   iOS shows the persona on the reference chip and adds a Delivery chip with
   a member sheet, while the Voices library keeps every member listed under
   truthful "Voice bank · <Delivery>" captions (each member's reference clip
   is individually previewable). Every selection resolves to a concrete
   member voice through the ordinary saved-voice path, so the bank layer
   owns no clone state and cannot desynchronize hydration, priming, or
   consent gating.

19. **Sync audit + CM-7 fixed (2026-08-04):** a full roadmap-versus-tree
   audit (three exploration passes plus adversarial cross-checks) found no
   false done claims anywhere; the drift was in connective tissue and was
   corrected in one currency pass — the release section said 2.3.0, the
   contract said benchmark history v2 and lacked phase 9's iOS
   adaptive-residency go-live, one roadmap evidence pointer was broken, the
   doc-governance plan cited the wrong authority, and one live doc's example
   named a retired preset. DP-9 was parked on the maintainer's call (DP-12's
   session contradicts its premise), and the audit's untracked follow-ups
   became items DP-17..DP-20. CM-7 then fell to root cause: the generation
   exit path's cleanup defer coupled the final WAV's fate to
   streaming-session retention, so every completed non-streaming take wrote
   its file, deleted it, and returned the path. The exit path now decides
   per artifact through the pure `terminalCleanup` table (a completed take
   always keeps its WAV), pinned by `GenerationTerminalCleanupTests`, and
   the CLI fails closed at the product boundary — generate and batch refuse
   to claim success when no file exists at the reported path. Live proof:
   `--no-stream` published a valid WAV matching its reported duration; the
   streaming control still publishes. The clone-fixture bootstrap in
   `scripts/lib/test_models.sh` works again unchanged.

20. **Seed retry/pin shipped (2026-08-04, DP-15):** the stochastic-with-retry
   norm, with the local advantage that fixed seeds genuinely reproduce a
   take. History schema v6 records every take's observed effective sampling
   seed (nullable; pre-v6 rows honestly stay blank), and both apps expose
   the two controls the audit's R6 called for: a History row's "Pin seed N
   for new takes" pins that take's seed into its mode's draft and lands you
   in that mode, and the composer shows the pinned state — a chip beside
   Generate on macOS, a studio Seed chip with an unpin confirmation on
   iPhone. While pinned, every take reproduces the seed with identical
   settings; unpinned stays the default fresh-seed-per-take, so plain
   Generate remains the regenerate-with-new-seed action.
   `GenerationSeedPersistenceTests` pins the migration and the full-range
   bit-pattern round trip. Long-form's plan-scoped per-segment sub-seeds are
   untouched.

21. **DP-18's first live run caught a fixture-true, live-false guard
   (2026-08-04):** Move 1's fail-closed delivery-provenance check compared
   `promptChars` between an instructed take and its neutral pair — but
   `promptChars` counts only the script text, which never includes the
   delivery instruction, so the instructed-longer premise could never pass
   outside its synthetic fixtures (no `bench --delivery` had run since the
   guard landed). The pre-registered DP-18 sweep tripped it on every cell
   before any data was scored. Replaced with a genuine end-to-end proof: the
   engine stamps an instruction receipt (`instructChars` + `instructDigest`
   from the request payload) on every instructed row, and the sidecar fails
   closed unless the receipt exists, its digest matches the manifest's
   instruction echo, and the paired neutral reference carries none.
   Twenty-two harness tests pin the new semantics; the DP-18 registration
   carries the amendment note and the sweep restarted with hypotheses,
   seeds, and decision rules unchanged.

22. **The confirmatory delivery sweep ran both arms (2026-08-04, DP-18
   done):** the audit's R4, pre-registered and executed the same day.
   Eight-way preset separability replicates on fresh seeds in both arms
   (4-bit UAR 0.477, 8-bit 0.375, chance 0.125, permutation p=0.001 each),
   and every distinct-set cell (neutral/calm/whisper/sad) clears FDR in
   both — DP-10's cut and DP-14's split now rest on confirmatory statistics
   rather than exploratory ones. The pre-registered happy-vs-angry 2-way
   sits at chance in both arms (p=0.43/0.24): the valence bottleneck is now
   a confirmed result, not a hypothesis — the instruct channel moves
   arousal, not valence, and `happy` fails FDR in both arms with angry as
   its top confusion every time. The 8-bit arm separates no better than
   4-bit, retiring quantization as a suspected adherence bottleneck. Angry
   and fearful meet the registered two-arm acoustic eligibility bar for
   promotion, but acoustic separability is not listener recognizability
   (the session heard angry 0/11), so the hint/distinct split stands until
   a listening probe on fresh takes — a maintainer call either way.
   Coverage: 16/18 seeds banked at 4-bit (two deterministic dropout-QC
   casualties), 18/18 at 8-bit; the runs published 34 PASS registry
   records, committed with this closure.

23. **The text-decoration valence route closed (2026-08-04, DP-19 done):**
   pre-registered same-day and run to a clean twin verdict. Decorating the
   script with interjections and terminal punctuation did not raise SER
   target-emotion probability for happy (p=0.52) or angry (p=0.27,
   directionally negative), and while the decorated arm's happy-vs-angry
   discriminant cleared its permutation null, so did the plain internal
   control — decoration added roughly 0.04 UAR over baseline, nothing like
   a lever. Per the registered decision rule the route closes; the valence
   answer now rests entirely with the external levers DP-20 watches. One
   analysis amendment is recorded in the gate (the scorer's power rail
   refused the raw 55-feature space; the structural 21-feature harness-axis
   subset was applied to both arms before any result was seen), along with
   the raw-vs-delta measurement note explaining why the plain control can
   exceed chance here without contradicting DP-18.

24. **The VoiceDesign whisper route closed (2026-08-04, DP-17 done):** six
   registered brief/instruction recipes, four seeds each, judged against
   the digest-verified Warm Narrator anchor on the validated HNR/CPP
   breathiness criterion. Every surviving candidate measured MORE harmonic
   than the anchor (delta HNR up to +2.9 dB against a -2 dB pass bar) —
   this checkpoint's design channel renders "whisper" as soft-but-voiced
   speech no matter where the request lives, so the bank builder keeps
   refusing whisper honestly. Side-finding: five takes fell to the fast
   audio QC's dropout detector, concentrated in whisper-adjacent
   generations — a future whisper lane needs a whisper-aware QC posture
   before its takes can even reach scoring. The one remaining path is
   cloning a genuinely whispered human reference (needs a recorded clip),
   with the HNR/CPP criterion as its acceptance gate.

25. **The delivery-adherence gate was calibrated from its banked matrix
   (2026-08-05, DP-21 done):** 272 banked paired rows recalibrated every
   expectation — required floors at the measured noise decile, supporting
   floors at |q10|, fearful's arousal direction corrected to its own
   `.strong` instruction semantics, and new binds the analyzer already
   computed (whisper breathiness posRate 0.97, sad variation collapse 0.94,
   angry/happy vocal tension). Genuine adherence misses keep warning at
   seed values. Gate algorithm v2 skips optional-analyzer features on
   pre-v3 pairs instead of failing. Bank replay: 181 pass / 91 warn
   (seeds scored 128/144). Ledger: `docs/reference/delivery-harness.md`.

26. **The normal tier carries the happy/angry distinction the strong tier
   lacks (2026-08-05, DP-22 done; DP-23 probed and re-parked 2026-08-06):**
   the pre-registered normal-tier arm replicated DP-12's perceptual lead
   acoustically — angry-vs-happy UAR 0.765 (perm p=0.007) in the 4-bit arm
   at the `.normal` copies, against DP-18's strong-tier null — so DP-9
   (EmotionIntensity removal) stays parked on measured product value. The
   follow-up cross-tier shipping candidate (angry.strong vs happy.normal)
   missed its registered confirmatory bar on fresh seeds (4-bit UAR 0.639,
   p=0.12; the descriptive 8-bit arm's clearance was not promoted) and
   re-parked pending a new lead. Measured along the way: normal-tier
   effects are weak-to-absent for the hint presets while whisper/sad stay
   solid at any tier, doubly refuting the 1.15 intensity scale; fearful's
   two tier copies render different emotions (anxious-slow vs panic-fast),
   not scaled intensity.

27. **The f16 evidence battery closed in one phone sitting (2026-08-06, CM-5
   done; plan `convergence-metal4-stage4-2026-08` complete):** the control
   lanes re-ran against the 2026.08.01.1 artifacts on the canonical
   iPhone 17 Pro (iOS 26.6) — CLI control trio
   (`macos-engine-20260806-142908/143035/143201`), iOS control 3 and the
   canonical filter-free matrix (`ios-xcui-benchmark-20260806-135457`,
   `ios-xcui-benchmark-20260806-141150`, both schema v3, soft-trim-only),
   and the macOS retained-memory re-qualification
   (`mac-memory-qualification-20260806-143414`, PASS; iOS memory evidence
   stands on the 2026-08-02 f16 runs). Both control evaluators PASS over
   the five records, and `config/characterization-fixtures.json` is
   rebound to 2026.08.01.1 with same-day cross-platform digests. The
   sitting kept the battery tradition of surfacing real defects: the
   headless `enroll-clone-fixture` lane shipped 2026-08-01 with its
   environment key missing from `IOSDeviceDiagnosticsRunner.isRequested`,
   so its first live run could never enter the enrollment branch — fixed
   and live-proven in the same window (the fixture voice re-enrolled at
   the exact banked `fixtureDigest`, keeping clone identity continuous).
   Honest device finding: the phone's app container had been reset since
   2026-08-02 (Clone Speed package, enrolled voice, and the two staged
   reference files all gone — that cleanup rider is moot); recovery used
   the product's own download path plus the fixed headless enrollment,
   and the new delivery/bank UI was observed by both UI lanes as the
   2026-08-04 surface note anticipated.

28. **Dual-agent UI critique → maintainer-approved polish pass
   (2026-08-06):** an isolated design-director review plus a mechanical
   detector/evidence pass scored the shipped macOS UI 31/40
   (product-authored; retained as a local critique snapshot) and surfaced
   one real regression-class defect: the composer's `ControlGroup`
   collapsed the designed gold Generate/Cancel CTA into an unlabeled icon
   sliver on macOS 26 — confirmed in code, smoke screenshots, and a live
   capture, and fixed by replacing the group with a plain HStack. The
   same-day polish landed the full approved scope: gold/blue accent
   unification, a 1 pt boundary-stroke floor with opacity-carried
   quietness plus Library/Settings content-width caps and Larger-Text
   scaling for ~10 fixed font literals (scaled-external-display
   robustness), inline one-time cloning consent in the composer footer
   (Settings toggle stays the persistent record), a visible "Heavy"
   memory badge on the generation screens' model control, VoiceOver
   dignity fixes (human "Ready"/"Waiting" readiness values with the test
   helper updated in the same change, a labeled player close button, an
   adjustable waveform seek), the Custom-tone field shown only in Custom
   delivery, and repetition/copy trims. Verified by the deterministic
   suite and a 7/7 smoke acceptance run
   (`macos-xcui-smoke-20260806-155739-34f0be6e`); the two failed smoke
   iterations before it caught a real constraint now encoded in code
   comments — flexible or generous toolbar frames push the History
   trailing group into the overflow chevron at compact widths. Four
   design-direction questions are parked maintainer-gated in
   `docs/reference/macos-ui-refresh-2026-08.md` (hero handoff, dark-only
   posture, Speed/Quality naming, styling the §K glass flip).

29. **Maintainer-driven layout follow-up (2026-08-06, same-day):** live
   iteration with the maintainer on the generation cards and Settings.
   One alignment grid per card: setup-row labels moved to first-baseline,
   the merged Language/Delivery line joins the label-column rail via an
   empty-label row, and a phantom-width bug died — the language menu's
   flexible frame claimed layout space its hugging button never drew,
   splitting the columns with dead space. The language control now draws
   its own fixed-width pill (bordered menu styles size strictly from label
   text and reorder structural children — width and a trailing chevron are
   only reachable by owning the drawing), sharing one
   `configurationColumnControlWidth` (150 pt; 160 overflowed the
   default-window card and collapsed the row to its stacked fallback) with
   the delivery and bank pickers. Clone's compact Source fallback became a
   designed stack; the Design brief footer split into caption + actions
   lines. Settings: sections reordered by job (Model downloads first,
   consent record last, with a `VocelloUIScroll.intoView` helper keeping
   the below-fold toggle test-reachable), tier rows collapsed to one line
   ("Speed · 4-bit"; size/capability stated once per mode; "Recommended"
   quieted so install state owns the only green), fixed 92 pt button slots
   ending per-row Manage/Download width drift, and the Variation segmented
   control tinted gold (the last system-blue holdout). Verified by build
   plus a 7/7 smoke acceptance (`macos-xcui-smoke-20260806-234647`).

## Staged roadmap state

Stage-by-stage details, closure evidence, and falsifiability criteria live in the
[roadmap review doc](reference/optimization-report-review-2026-07-25.md); measurements in
`benchmarks/OPTIMIZATION.md` §L–§N. Summary:

1. ~~Stage 0 — near-free quality wins~~ **completed 2026-07-26** (clone reference silence
   append with versioned conditioning identity, warn-first long-form boundary advisory,
   duration-directive delivery advisory, repetition-penalty A/B kept 1.05) → §L.
2. ~~Stage 1 — launch-bound attack~~ **completed 2026-07-26** at net **+11% warm RTF,
   byte-identical** (P2a-i + P3 landed; P2a-ii, P5b, P1b measured and declined with do-NOT
   records; stage-exit GPU busy ~47% — still launch-bound, so quant/speculative stays
   parked) → §M.
3. ~~Stage 2 — memory program~~ **completed 2026-07-26, including the 2.2 promotion**
   (phase 9 closed; six converted artifacts on public `PowerBeef02/<folder>` repos, catalog
   artifactVersion **2026.07.26.1** with fail-closed validation, isolated delivery proof,
   the canonical Mac install upgraded in place, stale-artifact update detection shipped
   end to end — Core probe, CLI `models status/install`, macOS `settings_update_<id>`, iOS
   `iosModelUpdate_<id>`; 2.3 codec conversion parked on a dtype-independent conv
   regression; 2.4 declined with M5b's premise corrected) → §N.
4. ~~Stage 3 — quality harness~~ **completed 2026-07-26** (phase 12/13 rows above; MOS-proxy
   and composed lane emission deliberately deferred).
5. **Stage 4 — gated migrations/research**: mlx pin bump to the newest lockstep pair
   (mlx-swift 0.31.6-era; the old 0.31.3 target is stale — see the
   [Metal 4 tensor feasibility study](reference/metal4-tensor-feasibility-2026-07-31.md),
   which also adds a cheap pre-registered MPP-on-M2 micro-benchmark rider, parks any
   custom fused tensor kernel behind P1b, and records the adopted OS-floor policy: hold
   26.0 with runtime-gated capability ladders; the first pin bump vendoring mlx core
   ≥ 0.32.0 triggers the 26.2 floor raise, per the study's F7), with all work performed directly on
   `main` under explicit maintainer authorization; long-form carryover (text context first), with
   speculative/PCG, CFG, and KV quantization parked. Working order and dependency rules:
   [roadmap-2026-08](reference/roadmap-2026-08.md).
6. **Smaller open threads**: a 60 Hz-device measurement of the iOS fixed-refresh glass
   gate if such hardware becomes available. (The other threads once listed here closed:
   iOS single-segment regeneration parity and the iPhone-15-Pro memory-profile diagnostic
   on 2026-08-01 — finding 1; single-take spoken-text normalization shipped 2026-08-01 as
   phase 10.)
7. ~~iOS 900-character single-take limit~~ **shipped 2026-07-24**
   (`IOSGenerationTextLimitPolicy.sharedScriptLimit` 150 → 900, memory-qualified on-device
   proof `ios-engine-20260724-060000-1cc8ef23`; the iOS UI-benchmark `long` cell keeps its
   fixed 150-character text for history comparability).

Status report: [`docs/reference/runtime-refactor-status-report.md`](reference/runtime-refactor-status-report.md).

## Historical milestones (compressed; details in the cited authorities)

- **2026-07-20 — cutover gate closed.** Phase 0 characterization controls, fixed-seed
  equal/diverge pairs, secret-sauce cells, nested-v9 producers, promotion packaging, v9
  sidecar authority, and clean canonical 29-take matrices on both platforms
  (`macos-xcui-benchmark-20260720-172920-591696d1`,
  `ios-xcui-benchmark-20260720-174441-16fc128c`) → `overallPromotion: passed`. Control and
  fixture identities: `config/characterization-fixtures.json`; records in the registry.
- **2026-07-22 — backend review + characterization gate + amendment.** Five external research
  documents counter-verified (~90 claims, staleness only) and imported under
  [`docs/research/`](research/); the R1 gate localized the post-cutover macOS UI decline to
  the delivery topology, endorsed as `amendment20260722` (phase 7 rescope, UI-context cell
  required in promotion matrices, phase 14 pulled forward). Same day: gates tiered
  (T0–T3, hook-enforced T1, path-aware CI, sole `CI required` context), trunk-based flow
  adopted, and xcodegen/ripgrep pinned to SHA-verified release artifacts after a runner-image
  roll flapped the toolchain gate.
- **2026-07-22 — UI QA architecture round trip.** Computer-use vision driving trialed and
  retired the same day; XCUITest returned as the sole autonomous driver in a ground-up v2
  stack (typed scoped queries, on-failure evidence, obstruction preflight, interruption
  sentinel, virtual-mic fixture, two-phase build/test). v2 acceptance passed on both
  platforms (`macos-xcui-benchmark-20260722-172102-48c4a193`). Computer use stays assistive
  ([`reference/interactive-ui-qa.md`](reference/interactive-ui-qa.md)).
- **2026-07-23 — the macOS UI decline resolved as a benchmark observer effect** (§J):
  XCUITest's automatic screen recording video-encoded every UI take; disabling it recovered
  the lane, engine code exonerated by flat interleaved CLI A/B. Phase 7 then closed via the
  generation performance gate (§K). Pre-2026-07-23 UI records carry the recording overhead
  and are not baselines. Fresh canonical gated matrices landed 2026-07-23 (macOS custom
  1.68–1.83 / design 1.78–1.94 / clone 1.49–1.84; iOS 1.86–2.03).
- **2026-07-24 — §H P0 GPU-busy re-capture completed** on the shipping runtime:
  whole-generation GPU busy ~47%, still launch-bound (§H P0 addendum).
- **2026-07-25 — optimization report counter-verified; staged plan adopted** (the roadmap
  review doc above). Same day: macOS 2.2.0 released and the repository renamed
  `PowerBeef/QwenVoice` → `PowerBeef/Vocello` (see Open release work).
- **2026-07-26 — Stages 0–3 executed and closed**, including the 2.2 artifact promotion and
  the benchmark-registry supersession rule (immutable records with a strictly older
  artifactVersion stay valid; new publications fail closed on current pins).
- **2026-07-28 — TestFlight public beta live; marketing surfaces grounded and refreshed.**
  Apple approved the Public Beta group (build 21, v2.2.2) and the public link went live. A
  commissioned promotion report was counter-verified against the tree and its repo-facing
  items landed in one arc: current repo description, a curated `good first issue` on-ramp
  (#86 CLI version fallback, #87 shell completion), README conversion pass (privacy hook,
  "Not a Python wrapper" block, CLI debug-RTF reproducibility caveat, coding-agents
  authorship line), website TestFlight front door (hero link, `#iphone` band with the
  cleaned `ios-studio.png`, nav/FinalCTA links), a factual local-versus-cloud comparison
  table in WhyCloud, two new Listen samples (Japanese preset take, 31 s calm narration),
  cookieless Vercel Web Analytics with the privacy policy scoped to disclose it, the page
  title retargeted to Mac + iPhone, and an instant-reveal fix for in-page anchor jumps.
  Outreach and social items from the report stay maintainer-owned outside the repository.
- **2026-07-31 — v2.3.0 released (macOS DMG + iOS TestFlight build 22)** on an explicit
  maintainer call, shipping the 2026.07.26.1 artifact generation, the Stage 1 warm-speed
  wins, delivery hardening, and the clone-prime/Wi-Fi-pin fixes. The evidence battery was
  deliberately paused mid-flight for the release window (deterministic publishing rule);
  its banked lanes, the aborted iOS control 3, and the exact remainder are itemized in
  Resume here. Same day: the public RTF wording was reframed as a realtime multiple
  (PRs #89/#90) and the wiped phone's clone fixture was re-enrolled via the new opt-in
  `enroll-clone-fixture` UI lane.

## Current implementation

- Native app UI acceptance uses one shared XCUITest stack: `macos smoke|benchmark` on the native
  Mac host and `ios smoke|benchmark` on a paired physical iPhone.
- UI execution is explicit frontend QA. It is not required to commit, push, open or merge a pull
  request, run ordinary CI, package a release, or create an iOS archive.
- The ordinary iOS compile lane typechecks both the app and a standalone app-host-free policy
  XCTest bundle for the generic physical-device SDK. It covers catalog/ledger, memory policy,
  cancellation, storage-path gating, and diagnostic redaction without a phone. Xcode 26 rejects
  tool-hosted app-free XCTest execution on physical-device destinations, so this target remains
  compile-only and device runtime proof stays in the headless diagnostics and XCUITest lanes.
- The physical-iPhone smoke contract covers two distinct cancellation paths (visible Cancel, then
  the registered one-shot critical-memory diagnostic requiring typed `memory_pressure`
  cancellation before `fullUnload`, then a completed recovery generation). Proven by
  `ios-xcui-smoke-20260716-172350-2c6828e1`.
- Generation ownership is explicit across all hosts. Final core audio uses the actor-owned,
  frame-bounded suspending channel. Frontend preview/status events use a separate per-generation,
  bounded suspending router, so audio-bearing preview events are never evicted by a
  `bufferingNewest` policy. `ActiveGenerationCoordinator` admits one active product
  task, carries typed user, memory-pressure, superseded, or shutdown cancellation, and awaits both
  model terminal and product cleanup/finalization before trim, unload, or ownership release.
- The shipping generation path is `VocelloQwen3Engine`, its classified session, and
  QwenVoiceCore's `GenerationOutputAdapter` for Custom, Design, and Clone; the actor owns every
  product-reachable runtime lifecycle operation, clone conditioning stays tensor-opaque behind
  epoch-bound handles, and sampling algorithm v2 plus the request-owned memory policy are
  shipping contracts (every request has its own seed and `MLXRandom.RandomState`). Invariant
  detail: the ADR, `docs/ARCHITECTURE.md` §4, and `.agents/rules/backend-mlx.md`.
- Clone conditioning is typed as transcript-backed or genuine audio-only x-vector. Both apps own
  the visible `voiceCloning_consentAcknowledgment` in Settings, persist the choice locally, and
  keep Clone Generate disabled until consent is acknowledged. Smoke and benchmark enable it through
  that real Settings control for later testing; there is no hidden test-state override. The two
  conditioning modes retain distinct cache and artifact identities. The compile-gated
  `scripts/ios_device.sh clone-conditioning` lane proved both modes in one device process
  (`ios-clone-conditioning-20260716-162518-ea8e8989`, local-only evidence).
- History persistence fails closed with typed privacy-safe errors. An unavailable database is
  never presented as an empty library and destructive actions remain disabled; iOS exposes a Retry
  control, while macOS retries on reload or re-entry.
- Headless iOS generation, language, profiling, crash, and memory diagnostics use
  `IOSDeviceDiagnosticsRunner` through `scripts/ios_device.sh` — a non-UI diagnostic lane, not a
  second app driver. The diagnostic Clone path requires the exact prepared voice ID (canonical
  fixture: a transcript-backed Voice Design reference).
- No preview/browser-mirror route, invisible accessibility state marker, alternate UI driver,
  coordinate bridge, or hidden UI bootstrap belongs in the shippable app.
- Model delivery uses one shared integrity/atomic-install implementation. iPhone owns one
  bundle-aware app-lifetime background session plus an atomic schema-v2 request ledger, exact task
  adoption, cancellation barriers (ledger writes are authorization barriers), durable delegate
  staging, and bounded privacy-safe diagnostics. macOS and CLI retain foreground delivery with
  terminal session teardown. Cancel discards staging; Retry reuses verified files. The isolated
  `scripts/ui_test.sh ios model-download` lifecycle proof is explicit QA only; the standing proofs
  are recorded in [`docs/reference/model-delivery.md`](reference/model-delivery.md)
  (e.g. `ios-xcui-model-download-20260716-163359-61377762`, exact wire bytes, zero retries).
- The generated cross-platform production model catalog (schema v2) is complete for all six
  Speed/Quality artifacts with exact pinned identities and the shared `speech_tokenizer`
  component; all hosts resolve the same delivery plan; reconciliation authenticates every catalog
  file before reuse and failed checks grant no bytes. Since 2026-08-01 the pins are the
  `PowerBeef02` artifacts at **2026.08.01.1** (8-bit talker embedding + f16 speech
  tokenizer, §R); installed models carry
  stale-artifact update detection with visible Update states on both platforms (repair runs
  through the ordinary authenticated delivery path). Live delivery validation: 2026-07-23
  six-artifact isolated Mac run + three-artifact iPhone lane; 2026-07-26 isolated Mac proof from
  the new pins.
- Benchmark evidence uses collision-resistant run IDs, atomic run-scoped manifests, and a
  privacy-safe PASS-only registry; `benchmarks/HISTORY.md` is generated from canonical records.
  Canonical comparison hardware is the Mac mini `Mac14,3` (M2, 8 GB) and iPhone 17 Pro
  (`iPhone18,1`); focused/dirty/instrumented classes never silently mix into canonical trends.
  Telemetry schema v8 + evidence manifest v2 make RAM/pressure evidence a publication contract
  (exact sidecars, ≥95% coverage, zero capture failures; critical pressure/`hardTrim`/
  `fullUnload` fail publication). History schema v3 adds the typed quality identity (phase 13
  row above). Records with a strictly older pinned artifactVersion remain valid immutable
  history after a catalog re-pin; new publications fail closed on current pins.
- CPU and memory Instruments lanes use exact-PID attachment; successful profiles publish digest/
  settings/summary then discard the raw trace unless `--keep-trace` was explicit. The `memory`
  lanes run the versioned retained-memory sequence; `memory-field-report` reads already-pulled
  delayed MetricKit aggregates only. The telemetry-overhead observer-effect diagnostic stays
  local by design.
- Generated output is classified by `config/build-output-policy.json` (two persistent platform
  caches, one shared package checkout, ephemeral scratch, bounded evidence/symbols, release-only
  `build/dist/`). Storage inventory distinguishes automatically eligible, blocked, and explicitly
  acknowledged reclamation; manifest-owned free-space preflights stop heavy lanes early. Codex
  task/session storage is a separate optional operator workflow (policy + synthetic fixtures in
  CI; live state never becomes repository evidence).
- The Qwen3/Mimi implementation is the owned monorepo package `Packages/VocelloQwen3Core` behind
  the typed `VocelloQwen3Core` facade; immutable lineage/compatibility/ownership/capability
  contracts replace patch-stack governance. Runtime trust boundaries are machine-readable
  (`config/runtime-debug-knobs.json` master-gated overrides; `config/concurrency-safety.json`
  concurrency exceptions), and release-candidate evidence is schema-v2 fail-closed
  (process- and command-bound; iOS adds the non-device archive/IPA verifier).
- The physical-iPhone language lane predeclares a one-based fixed-seed run plan, requires
  three-pass locale-locked on-device Speech consensus, and offers a retry-free diagnostic cohort
  that never publishes history. Its version-2 corpus enforces minimum script lengths and pins
  Design to the known language. The all-iOS platform preflight
  (`scripts/lib/ios_platform_preflight.py check`) runs read-only before any iOS build route and
  never authorizes Simulator execution.

## Publishing boundary

Routine verification is deterministic:

```sh
./scripts/check_project_inputs.sh
scripts/macos_test.sh test
./scripts/build.sh build
./scripts/build_foundation_targets.sh ios
```

Stop there for ordinary development publishing. A model download, paired phone, or UI result is
required only for the explicit quality task that needs it. Audio promotion quality is decided by
deterministic QC, fixed-seed evidence, ASR/prosody gates, and telemetry; listening is optional
annotation rather than a prerequisite.

## Explicit frontend acceptance

```sh
scripts/ui_test.sh macos smoke
scripts/ui_test.sh macos benchmark

scripts/ios_device.sh preflight
scripts/ui_test.sh ios smoke
scripts/ui_test.sh ios benchmark
```

Generation UI tests visibly require Custom, Design, and Clone Speed to be ready, Generate to be
enabled, and the prepared Clone voice to exist before the first take. Use `models ensure` only as an
explicit macOS fixture repair/bootstrap step. XCUITest is the sole autonomous app UI driver
(v2 stack since 2026-07-22 — see Historical milestones); computer use stays assistive per
[`reference/interactive-ui-qa.md`](reference/interactive-ui-qa.md).

## Open release work

- **macOS 2.4.0 is the released version** (2026-08-01; notes under
  [`docs/releases/`](releases/)) — the verified delivery-preset rework with Neutral as a
  real preset, iPhone long-form segment regeneration, spoken-text normalization, and the
  mlx 0.31.6 runtime refresh. Before it, 2.3.0 (2026-07-31) shipped the 2026.07.26.1
  artifact generation, Stage 1 warm-speed wins, delivery hardening, and the
  clone-prime/Wi-Fi-pin fixes, cut with the evidence battery deliberately mid-flight per
  the deterministic publishing rule; 2.2.0 → 2.2.1 → 2.2.2 landed in one day on 2026-07-25. The 2.2.0 arc hardened the
  pipeline (SHA-pinned
  tooling in release jobs, nested-framework signing with an explicit notarization verdict check,
  self-diagnosing dirty-tree evidence errors) and renamed the repository
  `PowerBeef/QwenVoice` → `PowerBeef/Vocello` before tagging; old URLs redirect and the old name
  must never be re-occupied. macOS 2.1.0 was released 2026-06-12. Future releases start from a
  protected version tag; the workflow verifies identity, signs/notarizes, emits SBOMs/checksums/
  evidence/provenance, and verifies draft assets before the separate source-bound promotion step.
- **First TestFlight build is uploaded**: the v2.2.2 dispatch (run `30177386286`) went green
  end-to-end on 2026-07-25 — archive, export, IPA verification, schema-v2 evidence, provenance
  attestation, TestFlight upload — making Vocello 2.2.2 (build 21) the first uploaded build.
  2.2.1/2.2.2 packaged the two App Store Connect binary rejections (opaque iOS icons;
  framework `CFBundleShortVersionString` inheritance) and an artifact-verifier inheritance fix.
  On 2026-07-27 the maintainer opened TestFlight distribution: beta Test Information completed,
  an Internal group (maintainer) received build 21 immediately, and a **Public Beta external
  group** was submitted to Beta App Review with the public link
  `https://testflight.apple.com/join/Cvp6yCv7` (open to everyone, no tester cap). Apple approved
  the build and the **public link went live 2026-07-28** — the README, repo description, and
  website all link it. Public App Store distribution additionally needs metadata, screenshots,
  and submission.
- **GitLab mirror exists** (2026-07-28, single-point-of-failure insurance): public project
  `gitlab.com/VocelloApp/vocello`, imported with full history and all tags, plus a
  `Vocello 2.2.2 (mirror)` release entry carrying the published SHA-256 digests, the release
  identity, and a link to the canonical GitHub DMG. Canonical development stays on GitHub; the
  mirror has no automatic sync yet (gitlab.com pull mirroring is a paid feature), so re-sync is
  currently a manual push and the mirror may lag main. The DMG binary itself still needs a
  one-time manual attach on the GitLab release.
- **Language-path acceptance state**: Speech assets for `de_DE`/`es_ES`/`ja_JP`/`zh_CN` verified
  2026-07-16; the corpus-v2/matrix arc closed with full run
  `ios-lang-bench-20260716-164248-1ecf8361` — 19/19 hint/QC, 18/18 output-gated, three-pass
  locale-locked ASR, `passedWithWarnings` (accepted Spanish Custom warning + soft trims),
  tracked `exploratory` because the worktree was dirty. It proves its exact fingerprint and is
  excluded from clean trends. Earlier failed/interrupted attempts correctly published no history.
- **Canonical UI evidence state**: the current clean canonical baselines are
  `macos-xcui-benchmark-20260801-182943-b0b5a448` (schema v3, captured on the 2.4.0
  release tree on main; also the vendor drift-test anchor) and
  `ios-xcui-benchmark-20260801-132415-abbec96b` (the first canonical iOS schema-v3
  record, 2026.07.26.1 artifacts). In immutable pre-convergence history a
  clean canonical macOS schema-v2 baseline exists
  (`macos-xcui-benchmark-20260716-181853-b4c2e299`) alongside its iPhone pair
  (`ios-xcui-benchmark-20260716-184106-48e3a3a6`), each bound to its recorded source
  identity. Clean post-cutover matrices closed promotion 2026-07-20; the
  observer-effect correction re-baselined 2026-07-23 (fresh gated canonical matrices; macOS
  custom 1.68–1.83 / design 1.78–1.94 / clone 1.49–1.84, iOS 1.86–2.03). Physical-iPhone
  telemetry-v8/evidence-v2 acceptance is complete (canonical matrix, retained-memory
  qualification, exact-PID memory profile). Pre-2026-07-23 UI records are not baselines for
  post-change comparisons; every tracked record binds to its exact source/toolchain/model/
  hardware identities; the 2026.07.26.1 fixture rebind completed 2026-08-01
  (`config/characterization-fixtures.json` `rebindNotes`).

## Resume rule

Review `git status`, read the applicable role playbook, and run verification proportional to the
change. Do not rely on a dated local `.xcresult`, telemetry directory, or device state as proof for a
new checkout. A tracked record proves only its exact source/toolchain/model/hardware identities;
produce fresh evidence only when that acceptance surface is explicitly requested.
