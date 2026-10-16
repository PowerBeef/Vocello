---
status: active
owner: backend-and-platform
reviewed: 2026-10-16
summary: Exhaustive read-only audit of the engine runtime (numerics and reference parity, lifecycle, output path and Fast QC, performance, delivery and persistence, dependencies, the clone pipeline) with adversarial verification, and the approved remediation plan — pre-freeze release items RF-18, RF-19, BG-01 and the MLX refresh (CONV-21), the engine-remediation-2026-10 programme (ER-01…ER-13) and the Qwen3-TTS reference-documentation overhaul.
sourceOfTruth:
  - config/roadmap.json
  - Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift
  - Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSSpeechTokenizer.swift
  - Packages/VocelloQwen3Core/Sources/VocelloQwen3Core/Engine.swift
  - Sources/QwenVoiceCore/MLXTTSEngine.swift
  - Sources/QwenVoiceCore/NativeEngineRuntime.swift
  - Sources/QwenVoiceCore/GenerationOutputAdapter.swift
  - Sources/QwenVoiceCore/LongFormPlanning.swift
  - Sources/iOS/IOSModelDownloadCoordinator.swift
  - Sources/SharedSupport/Services/VoiceClipTranscriber.swift
---
# Engine runtime audit and remediation plan

**Date:** October 16, 2026. **Baseline:** `a31f2f0b`. This audit is read-only: the auditors built,
ran and measured nothing; every timing quoted comes from retained evidence named in the text. The
plan below was approved by the maintainer on October 16, 2026. Open work lives in
[`config/roadmap.json`](../../config/roadmap.json): the release plan for the pre-freeze items and
`engine-remediation-2026-10` for the programme.

## Context

The maintainer asked for an in-depth, exhaustive audit of the Vocello backend runtime and engine
(bugs, issues, inefficiencies) and a complete step-by-step remediation plan, merging related
post-3.0 backlog items. The phone is unavailable and the maintainer is away.

The audit builds on the 2026-10-06 deep audit and the 2026-10-13 core engine review, whose findings
are parked as BKL-02…BKL-11, DA-04…DA-06, PA-16 and PA-33; it does not repeat them. Engine code is
unchanged since the 2026-10-13 baseline except the F-01/F-16 fixes.

**Method.** Eight read-only auditors:

| Auditor | Area |
|---|---|
| A | Model numerics, compared against QwenLM/Qwen3-TTS, HF Mimi and mlx-audio |
| B | Runtime and lifecycle |
| C | Output path, Fast QC and long-form |
| D | Performance, using measured iPhone 17 Pro (iOS 27) and M6 evidence |
| E | Delivery, storage and persistence |
| F | Dependencies and toolchain |
| G | Clone pipeline |
| V | A blind refuter |

The lead verified the top claims in code and upstream, and a planning agent designed the
remediation. No code was built or run. The findings appendix below is the evidence.

## Decisions recorded (maintainer, 2026-10-16)

1. **Before the RF-09 freeze (it stays Oct 23):**
   - RF-19, iPhone install dead ends (a new release blocker);
   - RF-18, long-form pacing (RF-15's failing row);
   - BG-01, hardening;
   - **the MLX dependency refresh (CONV-21), pulled into the release plan.** Choosing it is the
     authorization the repin needs; it is still reviewed with the gate benchmark.

   Clone conditioning is not a pre-freeze item.
2. **The engine remediation programme starts now.** It is recorded as an active plan, not parked.
   Until the freeze, its items join the release plan as they start. At the freeze, unfinished items
   pause until 3.0 is submitted, so any re-cut candidate stays clean, then resume immediately.
3. **Mac model runs are authorized now** (`vocello` CLI and the `qc-takes` lane, no UI automation).
   No macOS XCUITest runs today.
4. **Qwen3-TTS model research and reference-documentation overhaul** (requested mid-planning): Part
   C, run in parallel with Part A.
5. **The iPhone is unavailable.** Work focuses on the macOS side: Mac lanes, the `vocello` CLI,
   deterministic tests and the generic iOS compile. Every device proof below is queued for the next
   iPhone window the maintainer announces; none is scheduled by date. macOS XCUITest lanes resume
   once the maintainer confirms the earlier pause ("the next few hours") is over.
6. **Calls made in this plan,** approved by approving it:
   - Accept MLX's new sampler (F-02): seeds change, with a release-note line. D3, and D1 if adopted,
     change 3.0's seeds anyway.
   - Programme items that land before the freeze must be identity-safe, test-only or doc-only.
   - `focusLock.maxInFlight` is 4 until the freeze (one per lane: Mac screen, worktree agent, lead,
     MLX refresh) and returns to 2 at the freeze.

## Audit summary

About 200 findings: A 32, B 36, C 37, D 11, E 18, F 25 and G 27, plus status for every known ID.
The refuter refuted none of the 12 claims it checked. Most Oct 13 items are still open. What
matters most:

1. **Long-form fails in ordinary use.** This is RF-15's long-form row (C-01).
   - Streamed takes feed one text token per codec frame (A-01, the D1 divergence), so a
     60 s segment runs out of text at about 16 s.
   - The planner fills every segment to about 60 s (C-02).
   - The phone's persisted Consistent variation amplifies it (C-03).
2. **iPhone model installs can dead-end.**
   - A failed file is recorded as a user cancel: the row freezes at "Cancelling" and the next launch
     silently deletes the staged gigabytes (E-02).
   - A TLS reset counts as permanent (NET-3).
   - Two quick taps wedge both installs (E-01).
3. **BG-1's crash class.**
   - The pinned MLX aborts on a refused Metal command buffer. mlx-swift 0.32.3 makes it a typed error
     (DEP-1), except where clone-artifact validation runs unscoped (F-01).
   - The app keeps submitting proactive GPU work after leaving the foreground (B-01).
4. **Clone correctness.**
   - The Mimi encoder uses the wrong RoPE convention (A-02, confirmed by mlx-audio's own fix).
   - Enrollment accepts partial transcripts (G-01).
   - "Use audio only" is ignored for saved voices (G-02).
5. **Mac.**
   - Typing in Design unloads the model on every warm cancel (B-02).
   - Quitting mid-take tears MLX down under live GPU work (B-03).
6. **The largest user-visible performance costs.**
   - The live-preview prebuffer delays audible start by 0.7–3.8 s (D-01).
   - Marking takes 2–3.4 s per 60 s take (C-06).
   - The first take after an iPhone launch pays an extra 0.2 s for the decoder (D-02).
   - Weights are re-hashed: 2–2.8 GB once per install (B-07), and up to 14.6 GB on every Mac launch
     (E-15).

## Part A — before the freeze (release plan, Oct 16–23)

Every item gets:
- deterministic tests first;
- `scripts/dev.sh check` before each commit;
- `vocello-swift-review` for Swift;
- `/code-review` for the ledger and persistence;
- `./scripts/regenerate_project.sh --fast` when files are added.

### A1. RF-19: an iPhone install never wedges or silently discards data (release blocker, due Oct 21)

Four commits. NET-1 and E-02 must ship together, or failed installs restart on every launch.

1. **NET-3.** `Sources/QwenVoiceCore/ModelDownloadContracts.swift` (`dispositionForFoundationError`,
   ~540-576):
   - transient: -1200, -1011, -1014, -1017, -996 (and BackgroundSessionWasDisconnected);
   - certificate errors stay permanent; the retry bound is unchanged.
2. **E-02.** The ledger records `.cancelRequested` only from the coordinator's own durable cancel
   intent, never from a downloader `.cancelling` progress event.
   - Put the phase-to-display/ledger mapping in a new value type,
     `Sources/iOSSupport/Services/IOSModelDownloadProgressMapping.swift`.
   - List it under both test targets in `project.yml` and in the `promotionRouting` class of
     `config/quality-promotion-contract.json`.
   - The existing failure branch then publishes Failed + Retry and starts the next queued model.
3. **NET-1.** A pure `restoreAction(...)` in `Sources/QwenVoiceCore/IOSModelDownloadLedger.swift`:
   - `.failed` stays failed, keeping its staging for Retry;
   - `.cancelRequested` and `.deleted` discard;
   - live states requeue.

   `IOSModelDownloadCoordinator.restoreInFlightDownloadsIfNeeded` (~359-410) applies it.
4. **E-01.** A synchronous `startingModelIDs` claim, counted against `maxConcurrentModels`, taken
   before `fetchCatalog` and the plan hash and released on insert or error. It lives in a new value
   type, `Sources/iOSSupport/Services/IOSModelDownloadAdmission.swift`, wired like step 2.

**Tests:**
- `ModelDownloadLifecycleTests`: a disposition table per code and attempt; a restore table.
- New `IOSModelDownloadProgressMappingTests`: a failure while `.cancelling` without intent writes no
  cancel.
- New `IOSModelDownloadAdmissionTests`: two interleaved starts leave one pending; a failure releases
  the claim.

**Device proof:** queued for the next announced iPhone window; formally, RF-15's onboarding/download
row. Before the freeze, the table tests carry the failure paths, because they cannot be injected on
a device. An optional download-race scenario needs a separate go for multi-GB downloads.

### A2. RF-18: long-form pacing (due Oct 22)

1. **C-03 (test only, regardless of the outcome).**
   - `testZLongFormProjectJourney` pins Take variation = Expressive through `iosSettings_variationRow`
     and restores it, reusing the control audit's select/restore helpers moved into
     `Tests/UIAutomationSupport`.
   - Add `scripts/ui_test.sh ios smoke --scenario long-form` (allowlist, step workflow,
     `-only-testing`) so the journey runs alone in about 15 minutes.
2. **The machine screen** (Mac, now; no listening; `qc-takes` is the agents-allowed non-timing lane).
   - Arms: D1 off/on × Expressive/Consistent:
     ```sh
     QWENVOICE_FULL_TEXT_CONDITIONING={off,on} [QWENVOICE_TALKER_TEMP=0.7 QWENVOICE_TALKER_TOPP=0.9] \
       scripts/macos_test.sh qc-takes --cells long-form --languages english,french --label d1{off,on}-{expressive,consistent}
     ```
   - Plus the RF-15 fixture stratum, run as `QWENVOICE_DEBUG=1 build/vocello batch --long-form
     --file build/private/qc/rf15-longform/fixture.txt --mode custom --variant speed --app-delivery
     --seed N --json` with seeds 1–8 per arm (untracked under `build/private/qc/`).
   - Pre-registered metrics, written down before the run:
     - each segment's Fast QC verdict (dropout ≥2 s, cadence severe) and its longest interior
       silence;
     - how the take ended (EOS vs the token cap);
     - codebook-0 cycles;
     - the better ASR family's edit rate (gross above 0.30);
     - the language check.
   - Time to first chunk via `vocello bench --ttfc` (exploratory).
   - **Decision rule:** adopt D1 if D1-on fails ≤1 of ≥24 segments of 45 s or more, against ≥3 for
     D1-off, with no new gross-failure class. Otherwise record the known limitation, naming
     Consistent.
   - **Result (2026-10-16): D1 is not adopted.** The Mac M6 ran the release CLI built at 18:47
     (lanes `mac-qc-takes-20261016-224715-51137966` and `-225256-3ccd01fa`). Outputs are untracked
     under `build/private/qc/rf18-screen/`.

     | Stratum (variation) | D1 off: failed / long (all segments) | D1 on |
     |---|---|---|
     | qc-takes long-form cells, English and French (Expressive) | 0 / 3 (32) | 0 / 3 (32) |
     | The same cells replayed through the CLI (Consistent) | 2 / 8 (31) | 2 / 6 (29) |
     | RF-15 fixture, seeds 1–8 (Consistent) | 0 / 16 (24) | 1 / 14 (21) |
     | **Pooled** | **2 / 27** | **3 / 23** |

     - **The rule fails on both sides.** D1-on failed 3 long segments (the rule allows 1), and
       D1-off failed only 2 (the rule needs 3). D1-on also had more dropouts overall, 4 against 1.
       No take hit the token cap, and no new failure class appeared.
     - **Every failure ran under Consistent.**
       - Two were mid-take dropouts: 11.4 s with D1 off and 2.3 s with D1 on.
       - One take per arm never reached end of speech and ended in 98 s and 59 s of trailing
         silence (repeat runs of 1,064 and 649 frames).
       - Fast QC refused all of them.
     - **The knob applied.**
       - No D1-off/D1-on pair produced identical PCM.
       - A rerun of fixture seed 1 with D1 off reproduced its PCM byte for byte. Seeded takes are
         therefore deterministic, and the differences come from D1.
     - **The Mac did not reproduce the phone's failure rate** on the RF-15 fixture: 0 of 16 long
       segments failed with D1 off.
     - **Not run:** the ASR edit rate and the language check were not computed, because the Fast QC
       criterion already decided the rule; time to first chunk was not measured either.
     - **Decision.**
       - The defect is recorded as a 3.0 known limitation naming Consistent.
       - C-03 lands.
       - C-02 goes back to the maintainer. Every D1-off failure was in a segment of 45 s or more,
         which argues for shorter segments, but C-02 changes every long-form plan and needs its
         own screen.
3. **D1 adoption (if the rule passes).**
   - Flip both `.production` constants together: `Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Generation.swift`
     45-49 and `Packages/VocelloQwen3Core/Sources/VocelloQwen3Core/Contracts.swift` 122.
   - Update the knob purpose in `config/runtime-debug-knobs.json`, the comment in
     `UnsafeSpeechGenerationModel.swift` 28-54, and the seed and long-form text in
     `docs/releases/v3.0.0.md`.
   - Tests: in `Qwen3TalkerGenerateLoopTests`, production streamed Custom/Design equal the
     quality-first frames, the knob-off arm stays streaming, and clone labels are unchanged. Also
     update `VocelloQwen3FacadeTests` and `RequestLocalSamplingPolicyTests`.
4. **C-02, only if D1 alone is not enough.**
   - Lower `deliveryValidatedBudget` from 300 to 200 (`LongFormPlanning.swift` 128-133), with C-04's
     merge of unspeakable segments.
   - In the same commit: the `LongFormPlanningTests` and runner tests, the long-form cell in
     `config/audio-qc-calibration-takes.json` with its Python mirror, and the Mac
     `--long-form-segments` expectations.

**macOS proof before the freeze:** the screen itself (Mac CLI and `qc-takes`), plus the Mac
long-form journeys `scripts/ui_test.sh macos smoke --scenario long-form` (test06) and
`--scenario long-form-recovery` once Mac XCUITest is allowed again. **Device proof:** the new iOS
`--scenario long-form`, queued for the next announced window; formally, RF-15's long-form row.

### A3. BG-01 re-gated: GPU work cannot outlive the foreground (due Oct 22; no output change)

1. **Foreground permit for proactive model work.**
   - `QVoiceiOSApp.swift`'s scenePhase handler: `.inactive`/`.background` turn the permit off;
     `.active` turns it on.
   - `TTSEngineStore.allowsProactiveWarmOperations` refuses with `not_foreground`.
   - Losing active calls `cancelClonePreparationIfNeeded()` and a new `cancelProactiveModelWork()`.
   - The prompt-prebuild Task in `MLXTTSEngine.swift` 2323-2348 gets a stored handle and is
     cancelled.
   - Plumb it through `TTSEngine.swift`, `AnyTTSEngineBackend.swift` and the test fakes.
2. **Path d.** `try Task.checkCancellation()` before marking (`GenerationOutputAdapter.swift` ~2129).
3. **F-01, B-14 and F-07.**
   - Run `validateSpeakerEmbedding`'s finite check on the CPU stream (`Qwen3TTS.swift` ~1010-1012).
   - Wrap `adoptCloneArtifact`, `persistCloneArtifact` and `replayCodecTrace` in
     `VocelloQwen3MLXErrorScope().capture` and mark the runtime failure (`Engine.swift` 703-731,
     892-917).
   - Add `eval(refCodes)` inside `createVoiceClonePrompt` (`Qwen3TTS.swift` ~2164).
   - Update `Runtime.swift` 149-160.

**Tests:**
- `TTSEngineStoreTests`: inactive refuses and cancels; returning restores the band gate.
- An engine test that cancels a suspended prebuild.
- Adapter choreography: a cancel after staging skips marking.
- `Qwen3CloneArtifactIntegrityTests`: NaN/Inf rejected.
- `RuntimeFailureCaptureTests`: a forced error in adopt or persist gives a typed failure and an
  unload.

Background-time grants stay unchanged (risk 5).

**Device proof:** `scripts/ui_test.sh ios smoke --scenario background-warmup` (paths a and c),
queued for the next announced window. Before the freeze, the deterministic tests above are the
evidence. The change only refuses or cancels proactive work and adds error scopes, so it changes no
output.

### A4. CONV-21 re-homed: the MLX dependency refresh (due Oct 22)

**Prerequisites, in order:**
1. A3's error scopes (F-01).
2. F-03 readback probes: a failure check between `eval` and `asArray` at `Qwen3TTS.swift`
   3772, 4136-4138, 4328 and `LoadedModel.swift` 255, with a forced-allocation-failure test.
3. F-20: a golden seeded-sampling canary recorded on the current pin, pinning token digests for
   fixed `[1,V]` logits (`Qwen3RequestSamplingTests`).
4. F-06: the MLX/runtime version joins the clone-artifact identity
   (`Qwen3TTSRuntimeProfile.swift` 202-213), so artifacts rebuild once.
5. F-11: depend on the `Tokenizers` product only (`Package.swift` 106).

**Repin, as one change:**
- mlx-swift 0.32.3 (never 0.32.2), mlx-swift-lm 3.32.3, swift-transformers 1.3.5,
  swift-huggingface 1.0.0 (F-19 coupling, recorded in `config/swift-dependency-update-policy.json`);
- in `Packages/VocelloQwen3Core/Package.swift`, both `Package.resolved` files and `project.yml`;
- regenerate attributions and the project.

**In the same change or right after:**
- prewarm covers the runtime-compiled gemv shapes and the new sampler path (F-04/F-05);
- the canary is re-recorded on purpose (F-02 accepted);
- F-08 docs;
- F-10 `@concurrent` on `GenerationOutputAdapter.swift` 249, 333, 1613.

**Re-baseline on macOS, before the freeze:**
1. A clean unit lane, TSan and `scripts/dev.sh ci`.
2. `scripts/dev.sh ios` (the generic iOS SDK compile with the new pins).
3. The gate bench: three seeded runs on one clean commit start the new pool; compare medians of five
   warm takes.
4. Mac memory qualification.
5. A `qc-takes` screen with standard, clone and long-form cells, including D1 if adopted.
6. Once Mac XCUITest is allowed: `scripts/ui_test.sh macos smoke` and its long-form scenarios.

**Queued for the next announced iPhone window:** iPhone smoke, `background-warmup` (a refusal now
arrives as a typed error) and an iPhone memory benchmark.

**Exit:** CONV-21's gate is met.

### Part A timeline

| When | Work |
|---|---|
| Oct 16–17 | Commit the audit report and the roadmap. Start A2's screen on the Mac (background). A1 in a worktree agent. A3 by the lead. Part C research agents (at most 3 subagents active). |
| Oct 18–19 | A2's decision and D1 commit. Integrate A1 and A3. A4's prerequisites 2–5. The Part C research report and docs pass 1. |
| Oct 20–21 | The repin and the Mac re-baseline. The final screen with D1 and the bump. |
| Oct 21–22 | Mac validation of the combined tree (Mac smoke lanes once allowed). Part C docs pass 2. |
| Next announced iPhone window | The queued device checks: iOS smoke with `--scenario long-form`, `background-warmup`, iPhone memory benchmark. |
| Oct 23 | RF-09 freeze. A Part A item that misses it waits for 3.0.1; the freeze date does not move. |

## Part B — the engine remediation programme (`engine-remediation-2026-10`, active)

**Start-now rule.** Until Oct 23, programme items that are identity-safe, test-only or doc-only may
be started; each is re-homed into the release plan while it is worked. At the freeze, unfinished
items return to the programme plan, paused until the 3.0 submission. They then resume in graph
order.

**Dependency graph.**

```
ER-01 → ER-02 → (CONV-21, done in Part A) → ER-03 · PA-16 · ER-04 · ER-05 → ER-09
ER-01 → ER-07 · ER-08 → ER-09
host track, parallel: ER-06 → PA-33 · ER-10 · ER-11 (never inside a screen window) · ER-12
```

**Ordering traps:**
- G-13 lands before G-06, G-07 and G-16.
- E-03 lands before any catalog layout change.
- PA-16 lands before the decoder performance levers.
- The D1 decision comes before any talker KV window (A-05).
- A-02 ships together with G-03's version bump.

| Item | Goal and key contents | Absorbs |
|---|---|---|
| **ER-01** Measurement and test scaffolding | **Canaries and fixtures:** F-20–F-25 (golden sampling, parity fixtures for the Mimi/speaker encoders, decoder and exact compiled predictor, error-scope tests on every facade entry, leak canaries, cancellation inside load/warm/marking); B-30 `MLXModelLoadCoordinator` tests; URLProtocol-stubbed downloader suite; History wiring (TEST P1.3/P1.4). **Measurement:** `profile --kind metal`; launch-to-Studio-ready; audible-start trend; marking split; iPhone per-chunk-clear knob; F-14/F-17/F-18. **Baselines:** iPhone benchmark, 8 GB Mac, iPhone long-form timing, cold-reload frequency; the D-04 and D-09 diagnoses | BKL-11, PA-19 |
| **ER-02** Crash and hang class | CONC-1/B-04 checkpoints in loader, warm and hashing; BG-1 remainder (marking window probe, prebuild and marking diagnostics events); B-03 Mac quit barrier; B-12 CLI `_exit`; E-07 App Group lock; DB-3/E-11; C-13; A-15; A-20/A-21 | BG-01 remainder |
| **ER-03** Long-form and text conditioning | D1 follow-ups; the speaker-only clone layout decided by screen (G-14); planner v3 (C-02 balanced segments, C-04); C-15–C-17 transcript, fades and join pauses; A-23 natural fixture; ICA-06/ICA-15/RF-06 re-measured under D1 | — |
| **PA-16** (re-homed) | 72-frame decoder window, bounded KV and the A-27 mask; encoder window; parity fixture against the official 300/25 decode | — |
| **ER-04** Clone pipeline parity | G-13 first; then: A-02 + G-03; G-01 (later a SpeechAnalyzer `DictationTranscriber` with time ranges); G-02 three transcript states; G-04/G-05 untrusted transcripts; G-06/G-07/G-16–G-21 audio preparation; G-08–G-12; G-14/G-15; A-04 + A-26 primed decoder history; A-11/A-12; G-22–G-27 | — |
| **ER-05** Sampling and input parity | D2 and D6 decided by screen; subtalker independence for non-default variations; A-17 single-reduction sum; A-18 NFC; A-10 content-keyed caches | BKL-01 |
| **ER-06** Lifecycle, cancellation, memory | **Lifecycle:** B-02 (warm cancel never unloads); B-10, B-11, B-13, B-15. **Memory and caches:** B-05/E2-01 and E2-02; MEM-1–6 (A-08) and C-12; D-04, D-05; B-16–B-18 clone prompt cache redesign. **Concurrency:** CONC-2–7, B-20–B-25, B-28/B-29, B-33/B-34; A-13/A-14. **Files:** C-14/E-08 stream-session sweeper | BKL-02, BKL-03, DA-05, DA-06 |
| **PA-33** (re-homed) | Engine-side deletion lease (B-06) | — |
| **ER-07** iPhone memory budget from measured limits | D-06: bands derived from the measured process limit on 8 and 12 GB phones under iOS 26 and 27. Four coupled files: `IOSMemorySnapshot.swift` 425-431, `config/ios-memory-budget-policy.json`, `scripts/benchmark_memory.py`, the pinning test. Also EN-6 idle-unload policy and D-09 (8 GB Mac) | — |
| **ER-08** Identity-safe performance (each byte-identical, with dispatch counts and the gate bench) | D-01 speed-aware prebuffer; D-02 (Custom); B-07/E-15/D-07 hash elimination; B-08; E-16/D-03; D-08; B-09/C-06/PERF-9 marking; PERF-2–6; PERF-10 with A-16; A-29–A-31; B-17–B-19; C-20–C-25; E-17/E-18; F-16; PERF-11 | BKL-07 |
| **ER-09** Numerically shifting performance (each with a screen) | PERF-1; A-27/A-28; D-10/D-11; PERF-7; a talker KV window only with the full-text layout (A-05) | — |
| **ER-10** Delivery, storage, persistence | Downloader root cause (a failure never publishes `.cancelling`); NET-2/4–10; E-03 (before any layout change); E-04, E-05, E-06, E-09–E-14; STOR-1–6 janitor plus a hidden-name contract test; DB-1–6; SER-3–9; DA-14; F-06's durable unqueued marker | BKL-04, BKL-05, BKL-06, BKL-10, BKL-14 |
| **ER-11** Fast QC and output-path hygiene (ships with QC-08) | C-05, C-07, C-08, C-09, C-11, C-18/C-19, C-22, C-26, C-29–C-32, calibrated on QC v2's human controls, with mirrors and lineage updated | — |
| **ER-12** Tests, dead code, docs, registry | A-19, A-22, C-27/C-28, F-12/F-13 dead fork code; C-10/EN-5, F-08/F-09; B-20 (registry 33→32); ARCHITECTURE §4.5/§4.8; PA-26 B6; E6-02 | — |
| **ER-13** Qwen3-TTS model research and reference docs | Part C (below): sourced research report plus the reference-doc overhaul in two passes. Doc-only, so it may run before the freeze. | — |

## Part C — Qwen3-TTS model research and reference-documentation overhaul (requested 2026-10-16)

**Goal.** An exhaustive, sourced understanding of the Qwen3-TTS models Vocello ships, so that the
reference documentation becomes accurate, current and verified against code, and so that every
claim about the model rests on an upstream source or on this repository's own evidence.

The shipped checkpoints are `PowerBeef02/Qwen3-TTS-12Hz-1.7B-{CustomVoice,VoiceDesign,Base}`:
4-bit (Speed) and 8-bit (Quality) MLX conversions of `Qwen/Qwen3-TTS-12Hz-1.7B-*`, with the shared
12 Hz speech tokenizer.

### C1. Research

Read-only; it runs in parallel with Part A, with two or three research agents plus the lead's
verification. Web and Hugging Face reads only, no downloads.

1. **Upstream family and provenance.**
   - The Qwen3-TTS technical report and papers.
   - The official model cards, configs and `generation_config.json` for every variant (0.6B/1.7B;
     12 Hz and 25 Hz tokenizers; Base, CustomVoice, VoiceDesign).
   - Licenses, release history and anything released since the September pins (new checkpoints,
     tokenizers, fixes).
   - Training languages, the 9 speakers and their dialects, and the published evaluations.
2. **Architecture as implemented upstream** (QwenLM/Qwen3-TTS `qwen_tts`, transformers 4.57.x):
   - talker, code predictor (MTP), and the chat template and special tokens;
   - think/nothink language tokens, instruct and brief formats;
   - the streaming vs non-streaming text layouts per mode (A-01, G-14);
   - ICL clone construction;
   - the speaker encoder;
   - the 12 Hz tokenizer: Mimi-derived encoder (RoPE convention, A-02), split RVQ, decoder windows
     and chunked decode (A-03).
3. **Inference guidance and behaviour.**
   - Official sampling defaults and token limits; streaming latency claims.
   - Known failure modes from upstream issues and discussions (#68, #80, #134, #151, #181, #239,
     #288, #305, #337, #341, #359, #362, #371 and anything newer).
   - SFT/LoRA guidance; the reference recommendations for references and transcripts.
4. **Ecosystem.** Blaizzy/mlx-audio (Python) and mlx-audio-swift implementations, and their fixes
   and divergences; other ports (vLLM-omni, transformers integration). What changed upstream since
   Vocello forked (compare with `Packages/VocelloQwen3Core/UPSTREAM.md` and `ORIGINS.md`).
5. **Vocello's own artifacts.**
   - The conversion and quantization recipe: 4-bit, group 64, 8-bit text embedding, fp32 codec.
   - Receipts, digests and artifact versions (`config/model-artifact-receipts.json`, the generated
     catalog, `Sources/Resources/qwenvoice_contract.json`).
   - Every place Vocello deliberately diverges, cross-checked against the audit's parity table.

**Output:** `docs/audits/2026-10-17-qwen3-tts-model-research.md`. Every claim is sourced (URL plus
line, or a repository file). It includes a "verified against Vocello code" column and a list of
open questions.

### C2. Documentation overhaul (doc-only, so allowed before the freeze under the start-now rule)

| Doc | Change |
|---|---|
| `docs/reference/qwen3-tts-guide.md` | Rewrite as the model reference: family and shipped checkpoints, architecture, modes, languages and speakers, generation semantics, limitations. Add a **parity ledger** (D1–D6, A-01–A-12, G-14) with each item's status and decision |
| `docs/reference/qwen3-tts-prompting-guide.md` | Update the wire format, text layouts, ICL layout, transcript rules (G-01/G-02/G-12/G-15) and sampling |
| `docs/reference/mimi-codec-guide.md` | Make it the 12 Hz tokenizer reference: encoder RoPE convention, windows, chunked decode, artifact versioning (G-03/G-13) |
| `docs/reference/mlx-guide.md` | Error-handling semantics (#3523), `compile` pitfalls (A-16), KV-cache trim, sampler and seed behaviour (F-02), byte-identity claims (F-15), the MRoPE correction (A-19); rewritten for mlx-swift 0.32.3 after the repin |
| `docs/reference/ios-engine-optimization.md` | The iOS 27 8 GB limit (D-06) and measured budgets (section D) |
| Package docs | `README`, `UPSTREAM`, `ORIGINS`, `PERFORMANCE`, `CLONE_ARTIFACT_FORMAT` refreshed |
| `docs/ARCHITECTURE.md` | Engine sections (§4.5/§4.8 stale cache docs, B-16), the take lifecycle, error scopes |
| Other docs that repeat model facts (`qwen3-core-maintenance.md`, `instruction-language-research-2026-09-21.md`, `docs/qwen_tone.md`, `cli.md`, `model-delivery.md`) | Reconcile, or replace repeated facts with links (one owner per fact) |

**Two passes:**
- Pass 1 (Oct 18–20): facts that don't depend on pending decisions.
- Pass 2 (Oct 22): after RF-18's D1 decision and the repin land, so the docs describe the 3.0
  runtime exactly.

**Rules for every change:**
- each doc gets `reviewed: 2026-10-xx` and accurate `sourceOfTruth` front matter;
- no private paths;
- dated research docs stay linked;
- run `scripts/dev.sh check` (docs lint, link and privacy checks).

**Roadmap:** new item **ER-13**, "Qwen3-TTS model research and reference-documentation overhaul",
in the programme plan, re-homed into the release plan while it is worked before the freeze.

## Roadmap recording (the first commit after approval)

1. **Rewrite `focusLock` in `config/roadmap.json`** (decided 2026-10-16). It records:
   - the pre-freeze items;
   - the start-now rule, with programme items re-homed into the release plan while worked;
   - `maxInFlight` 4 until the freeze, then 2.
2. **Update the release plan:**
   - new RF-18 and RF-19 with the gates above;
   - BG-01 re-gated to A3;
   - CONV-21 re-homed from the backlog with A4's extended gate;
   - add RF-18, RF-19 and CONV-21 to RF-09's `blockedBy` (BG-01 per its classification);
   - a note on RF-15 (root cause, the Consistent pin).
3. **Create the `engine-remediation-2026-10` plan** with ER-01…ER-13, each parked with `unparkWhen`:
   "re-homed into the release plan when started before the freeze, otherwise after the 3.0
   submission". Re-home PA-16 and PA-33 into it.
4. **Supersede** (status `superseded` plus `supersededBy`, moved to the archive; the winners carry
   `legacyIds`):

   | Superseded | By |
   |---|---|
   | BKL-01 | ER-05 |
   | BKL-02, BKL-03, DA-05, DA-06 | ER-06 |
   | BKL-04, BKL-05, BKL-06, BKL-10, BKL-14 | ER-10 |
   | BKL-07 | ER-08 |
   | BKL-11, PA-19 | ER-01 |

5. **Add cross-reference notes** to the items kept: RF-06, ICA-06, ICA-15, QC-08, F-06, F-18, F-20,
   F-21, DA-13, DA-14, PA-26, BT-01, BT-06, AUD-11, BKL-08 and BKL-09.
6. **Save the audit report** as `docs/audits/2026-10-16-engine-runtime-audit.md`:
   - audit front matter;
   - the summary, decisions and plan;
   - this appendix, with repository-relative paths only (the privacy scan rejects home paths);
   - linked from the new plan's `sourceOfTruth` and from the checkpoint.

   Then the "Resume now" entry in `docs/development-progress.md`, `roadmap.py validate`/`render`,
   `scripts/dev.sh check`, and one docs/config commit. Push on your request.

## Verification

- **Per change:**
  - named deterministic tests (above);
  - `scripts/dev.sh test --only …`, then `scripts/dev.sh check`;
  - `scripts/dev.sh ios` for iOS sources;
  - `vocello-swift-review`.
- **Output-changing changes (D1, the repin):**
  - a pre-registered `qc-takes` machine screen, with no listening;
  - the golden canary re-recorded on purpose;
  - the gate bench against a re-pooled seeded baseline;
  - a release-note seed line.
- **macOS:**
  - `scripts/dev.sh check` and `ci`;
  - `scripts/dev.sh ios`;
  - the gate bench;
  - Mac memory qualification;
  - `qc-takes` screens;
  - Mac smoke lanes once Mac XCUITest is allowed again.
- **Device:**
  - the queued checks (smoke with `--scenario long-form`, `background-warmup`, iPhone memory
    benchmark) run in the next window you announce;
  - the formal proof is RF-15 on the processed TestFlight build.
- **Freeze:** RF-09's gate checklist, with exact-SHA CI and Security green.

## Risks and sequencing traps

1. **Seed lineage.** D1 and the repin both change seeded output. Bundle them before one baseline
   re-pool. "Pin seed" will not reproduce pre-3.0 takes; say so in the release notes.
2. **No iPhone before the freeze.** The repin, D1 and the BG-01 change would ship in the 3.0
   candidate on macOS evidence and the generic iOS compile alone. A device-only regression (the
   runtime-compiled gemv's time to first chunk, iOS 27 memory) could then surface first in RF-15
   and force a re-cut candidate.
   - Mitigation: run the queued device checks in the first window you announce, even after the
     freeze.
   - Before tagging the freeze, the lead flags whether those checks have run, so you can decide
     with that knowledge whether to keep the repin in 3.0.
3. **Pinning Expressive in the smoke hides Consistent's failure rate.** The screen and any
   limitation text must cover Consistent.
4. **E-02 without NET-1** turns failed installs into a restart loop on every launch.
5. **Background-time grants stay unchanged until the repin lands.** A grant keeps the process alive
   while a refused buffer still aborts on the old MLX.
6. **Never enable a talker KV window with the streaming text layout** (A-05).
7. **No Fast QC change inside a screen window,** so the comparison is not confounded.
8. **After Oct 23, every commit names a release item.** Programme work pauses until the submission.

## Appendix — findings by area

All findings, with severities, file references and verification status. S1 = crash, hang, data loss
or defective output in ordinary use; S2 = real defect, bounded; S3 = latent or hygiene; PERF-H/M/L =
efficiency lever.

- **DEP-1.** The pinned mlx-swift 0.31.6 bundles MLX `ce45c525`, 152 commits before
  ml-explore/mlx#3523 ("Catch error in CommandBuffer and poison the events", merged 2026-06-13).
  Today a refused (background) or out-of-memory command buffer aborts the process (BG-1's
  mechanism; upstream mlx-swift#407).
  - mlx-swift 0.32.3 bundles MLX `1f8e74e3`, which contains the fix.
  - Never use 0.32.2: it crashes at launch below iOS 26.4.
- **DEP-2.** mlx-swift#461 (in 0.32.x) fixes a lock-order deadlock between compiled functions and
  `evalLock`. It is not reachable today (F-09).

### A — Model numerics and reference parity (auditor A; lead verified A-02)

Compared against QwenLM/Qwen3-TTS (`qwen_tts`, transformers 4.57.3), HF Mimi, Blaizzy/mlx-audio and
mlx-audio-swift.

| ID | Sev | Finding | Where (Q = Qwen3TTS.swift, ST = Qwen3TTSSpeechTokenizer.swift) |
|---|---|---|---|
| A-01 | S1 | **D1 refined.** Every streamed take uses streaming text input: Studio, all long-form segments and speaker-only clones. Text enters at 12.5 tokens/s against about 4–5 spoken, so an ~860-char segment's text is used up by about 16 s and the talker then sees only `tts_pad` (the end-of-utterance cue) for about 40 s. Upstream defaults Custom and Design to non-streaming; upstream PR #362/#239 report rate drift and "long silences and bursts". Leading cause candidate for C-01. Fix: `production.fullTextConditioning = true` with the streaming decoder kept, at the cost of tens of ms of time to first chunk. | Generation.swift 45-49; Q 3228, 1684-1689, 3926-3932, 4720-4749 |
| A-02 | S1 | **NEW. The Mimi (clone-reference) encoder uses the wrong RoPE convention:** `RoPE(traditional: true)` on HF-format q/k/v weights, which were permuted for rotate_half. mlx-audio fixed the same port with `rope_traditional=False` (6549fc2, "silence in VC"). Every transcript-backed clone gets reference codes that differ from the official tokenizer's; persisted clone artifacts hold them. Fix: a convention flag set false for Qwen, and bump `codecEncodeConditioningVersion` so artifacts and caches rebuild fail-closed. | Mimi/Transformer.swift 129-131; ST 1372-1385, 1503-1507; Q 602 |
| A-03 | S2 | PA-16 refined: the decoder never applies its 72-frame window (the reference decodes 300-frame chunks with 25 context); its fp32 KV grows for the whole take (64 KiB/frame, about 48 MiB at 60 s, 128 MiB at the cap). The encoder window only applies under FlashAttention-2 upstream. | ST 483-498, 1035-1037; Config 349 |
| A-04 | S2 | D5 refined: streamed clones decode from a cold decoder; reference history exists only in quality-first. Fix together with A-26. | Q 3713-3715, 4058-4060, 4447-4458 |
| A-05 | S2 | NEW (latent): a talker KV window would evict the unspoken script in the streaming layout (the prefill holds one text token). Production has no window, but the Oct 13 review proposes one for iPhone. Allow a window only with full-text layouts. | Q 3446-3456, 1885-1895 |
| A-06/07 | S2 | D2 (EOS re-inserted: can truncate, cannot create interior silence) and D6 (Custom falls back to English) still open | Q 5205-5212, 5305-5308; GenerationSemantics 852-876 |
| A-08 | S2 | MEM-1 still open: the encoder KV is kept, and a longer input concatenates onto the stale buffer | ST 854, 923-928 |
| A-09 | S2 | ICA-06/ICA-15/RF-06 share A-01's mechanism (Chinese reaches the post-text regime almost immediately; RF-06's replay showed the model "stuck" in silence: p≈0.94 silence, EOS ≈ 2e-7) | — |
| A-10 | S3 | Conditioning-prefix and text-tokenizer caches are keyed by install path and survive Mac unload, delete and update: stale embeddings after an in-session model update | Q 1487-1490, 1547-1564, 6238-6240; NativeEngineRuntime 2345-2353 |
| A-11/12 | S3 | ICL target text always gets a leading space (changes the first CJK tokens); ICL references get +0.5 s silence, with a comment wrongly claiming upstream parity | Q 4558-4564, 592-602 |
| A-13/14 | S3 | CONC-3 (shared mutable decoder) and E1-03 (legacy producers never finish) still open | Q 6018-6098, 2389-2790 |
| A-15 | S3 | Latent: frames → seconds → frames loses a frame for 37 of chunk sizes 1–512 (today's 7 and 4 are exact) | Contracts 343-345; Q 3475 |
| A-16 | S3 | The compiled code-predictor plan bakes weights at trace time; reusing it across takes (PERF-10) must declare `inputs:` or key by epoch | CodePredictorCompiled 91-105; Q 3681 |
| A-17/18 | S3 | Codec-embedding sums are 15–16 serial bf16 adds (the reference uses one reduction); briefs and instructions are not NFC-normalized | Q 3937-3940; Q 6462 |
| A-19/20/21 | S3 | Stale docs (iOS residency qualified with the withdrawn f16 codec; mlx-guide's MRoPE claim); trusted loads check only unused keys; no finite checks on logits or decoder PCM | Q 468-479, 5697-5705, 5313-5320 |
| A-22 | S3 | Dead code ships: the legacy `decode` with the DECODE-002 bug pattern, `prepareGenerationInputs`, AudioUtils, most of DSP, Seanet/Conv/Transformer extras, `primeVoiceClone` | various |
| A-23 | S3 | The long-form smoke fixture is one paragraph repeated 5×, adversarial for text alignment; may overstate the real-script dropout rate | VocelloiOSSmokeUITests 787-800 |
| A-26 | PERF-M | Quality-first clones re-decode the whole reference every take (+65% decoder work for a 20 s reference on a 30 s take); cache the primed decoder state per clone prompt (also fixes A-04) | Q 4447-4458 |
| A-27/28 | PERF-M | Decoder builds an (offset+n)² mask per chunk (16.8 MB at the cap) and keeps n rows; the SEANet encoder runs on the whole reference (about 126 MB per activation for 20 s, 740 MB for a 120 s Mac reference) | ST 490-498, 926-931 |
| A-29/30/31 | PERF-L | Depthwise conv built from 7 slices; decoder warm-up shapes (1–4 frames) miss production chunks (7, 14); introspection recompiled per take and prewarm never exercises the compiled predictor | ST 192-234; Q 1492-1495, 3698-3707 |
| A-32 | PERF | PERF-1…PERF-10 all still open (none landed) | see the Oct 13 review |
| — | FIXED | D3 (float32 sampling on every path), E4-01, E4-02, E4-03, AUD-11 (Set-backed) | Q 5143-5145, 4942-4958 |

**Parity divergences that change output:** text layout (A-01); Mimi RoPE (A-02); decoder window
(A-03); streaming clone history (A-04); ICL leading space and reference padding (A-11/12); EOS
re-insertion (D2); Custom English fallback (D6); subtalker sampling copying the talker's values
for non-default variations (the reference keeps 0.9/top-k 50/top-p 1.0 independent). Everything
else matched: chat template, talker, code predictor, sampler order, streaming decoder conv state,
codec math, speaker encoder, and quantized load.

### B — Runtime orchestration, lifecycle, concurrency, memory policy (auditor B; lead verified B-02, B-03)

No known runtime item is fixed in code. BG-1, CONC-1/2/4–7, MEM-2–6, E1-02, E2-01/02, E3-01,
E3-04, DA-05/06, PA-33, AUD-03, PA-19 and F-20 are all still open; F-21's source repair holds.

| ID | Sev | Finding | Where (NER = NativeEngineRuntime, MLC = MLXModelLoadCoordinator, GOA = GenerationOutputAdapter) |
|---|---|---|---|
| B-01 | S1 | BG-1 still open, unchanged: proactive load/prime and the prompt prebuild have no handle and get no grant; marking runs after the last cancel check | IOSBackgroundGenerationPolicy 70; QVoiceiOSApp 237-278; IOSGenerationModeViews 2361-2382; MLXTTSEngine 2323-2348 |
| B-02 | S2 | **E1-02 refined: ordinary Mac typing unloads the model.** Every warm intent change (Design brief keystroke after 800 ms, speaker, delivery) cancels the dispatched warm; NER's warm catch unloads on any error, `CancellationError` included, so the 1.3–2.1 GB model reloads cold each time; the cancelled-take path then publishes `.loaded` with nothing resident. The test fake throws before the warm body, so the suite stays green. | NER 1780-1843, 2190-2230; MacGenerationWarmupCoordinator 215-224; MLXTTSEngine 1531, 1613 |
| B-03 | S2 | NEW: quitting the Mac app mid-take tears MLX down under live GPU work (`exit()` runs `~Device`/`~Scheduler` while the token loop or marking runs: crash report or hang at quit). No `applicationShouldTerminate` and no `.shutdown` barrier on the Mac. | AppStateRestorationPolicy 49-53; mlx scheduler.h 140-153 |
| B-04 | S2 | CONC-1 refined: cancel and relief wait out load, warm, trust hashing and marking; the load-epoch veto has no production trigger; `Engine.swift`'s comment still promises "the loader's own cooperative checkpoints" | Engine 553-563; MLC 370-462; MLXTTSEngine 2420-2429 |
| B-05/06 | S2 | E2-01 (Mac unloads keep the process-global Qwen3 caches, also at the critical band) and PA-33 (no engine-side deletion lease; the deletion gate trusts a load state B-02 can make stale) still open | NER 2345-2353; ModelDeletionSequence 44-106 |
| B-07 | PERF-M | NEW: the first load after an install re-hashes 2.0–2.8 GB of weights synchronously inside the take (about 1–3 s, uncancellable; the shared tokenizer is hashed once per model: 3× on iPhone, 6× on Mac) although the integrity manifest already holds verified digests | MLC 417-422, 987-1266 |
| B-08 | PERF-M | NEW: iOS `App.init` sets `Memory.cacheLimit`, which initializes MLX's Metal device and library on the main thread before the first frame; every load re-applies the policy anyway | QVoiceiOSApp 43, 413-421 |
| B-09 | PERF-L | Marking clears the MLX buffer cache 3× per take and reloads 29 MB of AudioSeal weights on every tier (16/32 GB Macs start every take cold) | GOA 2129-2155; AudioMarking 37-45 |
| B-10 | S3 | `cancelClonePreparationIfNeeded` rewrites a running take's state to `.loaded` (leaving Clone mid-take shows "ready") | MLXTTSEngine 1273-1279 |
| B-11 | S3 | Queued stale kernel-pressure events act after pressure clears: a stale hard trim cancels a new take as `.memoryPressure` | NativeMemoryPressureMonitor 107-143 |
| B-12 | S3 | F-20 refined: the CLI's forced exit runs MLX static destructors under live work; use `_exit` after `stopAll()` | CLIProcessSupervisor 20-97 |
| B-13 | S3 | The batch memory policy is unreachable (`isBatch` always false); CLI and Mac line batches run single-take policy | MLXTTSEngine 816-819; NativeMemoryPolicyResolver 46-55 |
| B-14 | S3 | Clone-artifact adoption (`eval`) and persistence (`MLX.save`) run outside any MLX error scope, so an MLX error reaches mlx-swift's `fatalError` | Engine 703-731; NativeCloneSupport 350-421 |
| B-15 | S3 | Latent: `VocelloQwen3Engine.prime` runs the model off the actor's executor (no caller) | Engine 816-888 |
| B-16 | PERF-L | Clone prompt caching is mostly dead weight: every Clone take re-adopts the prompt from disk (SHA-256, `loadArrays`, eval) before the in-memory cache is consulted; the host LRU (8/16) can only hold handles the actor (capacity 1) already evicted; eviction "clears" free no MLX memory; docs stale | NativeCloneSupport 350-655; ARCHITECTURE §4.5, §4.8 |
| B-17/18/19 | PERF-L | About 10 prompt assemblies (full-script language detection) per take, half for discarded diagnostics; the clone reference is SHA-256'd 2–3× per take; progress/prepared/diagnostic publications have no reader (an actor hop per frame) | NER 893-2458; NativeCloneSupport 175, 876-891; Engine 1606-1721 |
| B-20/21 | S3 | `ResolvedCloneConditioning`'s `@unchecked Sendable` is unnecessary (budget 33→32); CONC-7 `PCM16ScratchBuffer` has no lock (safe only by single-flight) | NativeCloneSupport 24-42; GOA 856-905 |
| B-22–25 | S3 | E2-02 (16 direct `Memory.clearCache()` + 6 direct policy applies), MEM-2 (relief API unused), CONC-2, CONC-4/MEM-4/E3-01 (reachable only via `stop()`, latent) | various |
| B-26/27 | S3 | E3-04 harmless under the shipping `.pcmPreview` policy; MEM-3 narrowed by marking's pre-clear | GOA 272-275, 2111-2136 |
| B-28/29 | S3 | CONC-5 plus a new detail: commit opens an `AVAudioFile` on the MainActor; CONC-6 audio-preparation queue uncancellable | MLXTTSEngine 2166, 2274-2363; AudioPreparation 129-163 |
| B-30 | S3 | `MLXModelLoadCoordinator` has no direct tests (prepared cache, trust hashing, epoch veto), although its loader is injectable | MLC 225-241 |
| B-31/32/35/36 | S3 | AUD-03 (views build generation Tasks), F-21 (qualification pending), MEM-5/MEM-6, PERF-7 also on 8/16 GB Macs | various |
| B-33/34 | S3 | `ensureModelLoadedIfNeeded` lacks the initialized/proactive-warm checks; the F-01 review sweep fails a save on any removal error (use `try?` and count) | MLXTTSEngine 1100-1120; PreparedVoiceRepository 269-272, 720-731 |

Checked and clean (B): the engine lease/reservation machine, the lossless PCM channel,
cancellation ingress, `ActiveGenerationCoordinator`, cancel-safe waiters, all three prewarm-slot
pairings, the event router's single terminal, the `runReservedTake` choreography, model switching
(no double residency), no lock across an await, no deprecated wired-limit API and no production
`Memory.memoryLimit`, idle-unload re-arming, store admission order, the iOS foreground-exit barrier
(BG-1 aside), the F-01 review-owner liveness, privacy of engine errors, and the CLI supervisor's
signal handling. All 33 `@unchecked Sendable` and 6 `nonisolated(unsafe)` entries match the
registry; one claim is stale (B-20), one is false but safe by single-flight (CONC-7).

### V — Adversarial verification (blind refuter over 12 claims; the lead verified 10 more directly)

The lead verified A-01's mechanism, A-02 (plus upstream mlx-audio 6549fc2), B-02, B-03, C-02,
C-03, D-01, E-02, E-05 and G-01. The refuter's 12 claims: 6 confirmed, 6 partly confirmed, 0
refuted.

| Claim | Verdict | Correction |
|---|---|---|
| E-01 | Confirmed, S2 | Worse than stated: the second model's tasks are also cancelled and wedge; progress and verified files are attributed to `inflight.values.first`; the window is widest once the shared component exists (682 MB re-hash) |
| E-03 | Confirmed, S3 latent | Today only orphan files; an integrity bypass only if a future artifact replaces `model.safetensors` with shards |
| E-04 | Partly, S3 | Rollback on non-suspension errors is documented design; SQLITE_BUSY is unreachable (one queue, no extensions); in a main run only the joined WAV is lost and Resume re-joins. Real loss: the **regenerated take** on SQLITE_FULL/IOERR. |
| C-04 | Confirmed, S3 | — |
| B-07 | Confirmed, PERF | Once per install; the hash runs after the load timings are recorded, so it is invisible in telemetry |
| B-11 | Confirmed, S3 | Narrower on iPhone: Generate is disabled while admission is closed |
| B-14 / F-01 | Partly, S3 | `MLX.save`/`loadArrays` wrap their own C calls (they throw, not crash); the crash surface is `validateSpeakerEmbedding`'s unscoped `eval`/`item` (8 KB) |
| D-02 | Partly | Custom confirmed (+211–229 ms first take after launch); **Design refuted** (`warmPreparedInputs` precompiles the decoder) |
| D-04 | Partly | The 309 MiB snapshot is real; the cited ordering is wrong (the cache is cleared after `loadedModel = nil`); the late holder is unidentified, so measure first |
| D-06 | Partly | 8,192 MB is verified. The ~6 GiB assumption lives in `IOSMemoryBudgetPolicy.ShippingBandMiB` (fixed 4,500/5,200 MiB footprint bands → trips at ~55%/63% of the real limit); `NativeMemoryPolicyResolver` has one fixed iPhone tier |
| A-05 | Confirmed, S3 latent | Debug-knob only today |
| C-09 | Partly, S3 doc | Pre-marking counters are documented intent; the defect is the wording in AudioPublicationMarking 9-11, and clipping introduced by marking goes unjudged |

### G — Host-side clone pipeline (auditor G; lead verified G-01)

Clean: the speaker and codec encoders receive the same normalized 24 kHz mono samples; the mel
front end matches upstream; over-long input is rejected, never truncated; clone language handling
and prompt slicing match upstream; prompt caches are content-keyed and fail closed; review-state
staleness and audio-only confirmation are sound.

| ID | Sev | Finding | Where |
|---|---|---|---|
| G-01 | S1 | **NEW: saved-voice enrollment accepts a partial recognition transcript** (e.g. only sentence 2 of a 16 s clip, the repo's own retained fixture `WordErrorRateTests.swift:750-790`, consistent across 3 passes). Enrollment never applies the edge-coverage rule the output verifier uses, so it reaches `.ready(.automatic)` with Save enabled, and every ICL take of that voice runs on a truncated `ref_text`: the known ICL collapse mode (mlx-audio #921). Fix: reject a winner without edge coverage (`.partialCoverage` → review required); later, SpeechAnalyzer `DictationTranscriber` with time ranges and punctuation. | VoiceClipTranscriber 444-519, 714-744, 1256-1258 |
| G-02 | S2 | "Use audio only" on a saved voice with a transcript still conditions on the stored transcript (a nil transcript means "read the `.txt`"); the user's remedy for bad ICL output silently does nothing. Needs three explicit request states. | NativeCloneSupport 779-793; GenerationDrafts 184-206 |
| G-03 | S2 | Refines A-02: nothing versions the encoder implementation, so after the RoPE fix every saved voice keeps adopting its persisted wrong codes forever; add an encoder version to `speakerFeatureVersion`, pinned by a golden-codes test | Q 598-602, 762-771, 924-928 |
| G-04 | S2 | Mac History "Save to Saved Voices" for a Clone take enrolls the requested script as the transcript (Save enabled, recognition skipped); the design flow's own comment calls that "intent, not evidence" | SavedVoiceSheetConfiguration 58-87 |
| G-05 | S2 | iPhone import trusts a neighbouring `.txt` as a reviewed transcript (the engine itself refuses unreviewed one-off sidecars, P12-09) | IOSRecordVoiceSheet 65-138, 469-474 |
| G-06 | S2 | Stereo/multichannel → mono is implicit (`AVNumberOfChannelsKey: 1` on the reader; undocumented mix vs remap) and untested; upstream averages. Risk of a silent or wrong-speaker reference for one-sided stereo. | AudioPreparation 455-463, 492 |
| G-07 | S2 | References end abruptly (hard stop at 20.4 s or Stop, no trim, no fade, then 0.5 s of zeros appended to a non-zero last sample): the documented onset-echo trigger (#341) | ReferenceClipRecorder 206, 432-436; Q 626-633 |
| G-08–11 | S3 | An unreadable reference can be kept (soft warning only); sample-rate/channel checks run on the already-normalized output so they never fire, and silence/clipping warnings reach only telemetry (8 kHz phone audio enrolls silently); iPhone Stop bypasses the 10 s minimum (the Mac enforces it); Mac one-off references skip all duration policy (0–120 s straight into ICL) | SemanticTypes 862; NativeCloneSupport 712-729; IOSRecordingOverlay 232-273; MacVoiceCloningScreen 838-867 |
| G-12/13 | S3 | Stored transcripts keep newlines: the CLI `--voice` path and the prompt prebuild read `.txt` verbatim, so the prebuild never matches Studio takes; audio preparation has no version, so fixes (G-06/07/16) never reach cached references or prompts | PreparedVoiceRepository 288-308; NativeCloneSupport 859-865, 1026-1046 |
| G-14/15 | S3 | The ICL layout always uses upstream's non-streaming clone layout, while upstream's clone default overlays text (the 10-12 research doc says otherwise; no parity switch); recognized transcripts carry no punctuation and skip the text planner the target uses | Q 4603-4615; VoiceClipTranscriber 1256 |
| G-16–21 | S3 | Implicit resampling quality and int16 hard clipping; Ogg offered via an AudioToolbox check but decoded by AVAssetReader; long voice names exceed the file-name limit in conversion temp names; cross-language references not flagged (#80); transcripts bound to a path, not content (TOCTOU); decoded bytes copied without checking format or length | AudioPreparation 425-563 |
| G-22/23 | S3 | Any adoption error deletes the persisted prompt (also transient read and lock errors), without the store lock; crash-left clone-prompt staging (speaker embeddings) is never swept | NativeCloneSupport 372-374, 451-452, 971-976 |
| G-24–27 | PERF | Speech recognition (up to 10 language passes × 45 s) runs before any duration check; absolute paths inside the clone identity orphan prompts on container moves; saved-voice prompt folders accumulate per transcript edit; each take re-analyzes the reference even when cached | various |

### F — Dependencies, toolchain, API surface, engine test gaps (auditor F)

**Verdict on DEP-1:** mlx-swift 0.32.3 turns BG-1's abort into a typed failure only in part.

| GPU path | Outcome after the bump |
|---|---|
| Load, prewarm, prime, the clone speaker path, generation, decode, marking | Recoverable |
| Clone-artifact adoption and persistence (BG-1 paths a and b) | Still crash: no error scope, so mlx-swift falls back to `fatalError` |
| Codec replay | Still crashes |

The bump also changes every seeded take. No API change breaks the build, and no
`Stream`/`Device` semantics change matters (Vocello uses one global GPU stream). `KVCacheSimple`
is unchanged. The #461 deadlock is not reachable today: every MLX caller is single-flight, and
marking uses no compiled functions.

| ID | Sev | Finding | Where |
|---|---|---|---|
| F-01 | S1 | Refines BG-1 and confirms B-14: `adoptCloneArtifact`, `persistCloneArtifact` and `replayCodecTrace` run GPU validation (`isFinite…all`, `eval`, `item`) with no MLX error scope. Even after the bump, BG-1 paths a and b and any allocation failure there crash, and the raw `MLXError` skips `recordRuntimeFailure`. Wrap them in `VocelloQwen3MLXErrorScope().capture`, or validate the 1×D vector on `.cpu`. | Engine 703-731, 892-917; Q 812-817, 950-954, 1010-1012 |
| F-02 | S2 | The MLX bump changes every seeded take: MLX #4177's inverse-CDF categorical applies to Vocello's `[1,V]` logits. "Pin seed" stops reproducing older takes, and byte-identity gates cannot pass. Option: sample from 1-D logits to keep the Gumbel path, or accept and document. | Q 5140, 5313-5321 |
| F-03 | S2 | Reading an array back after a captured allocation failure crashes (`asArray` builds a nil-base buffer: `memmove(NULL)`) before the sink's check or the allocation-retry path can run. Add a failure probe between `eval` and `asArray` at chunk boundaries. | Q 4136-4138, 3772, 4328; LoadedModel 255 |
| F-04/05 | PERF-M | After the bump: the new sampler path adds about 80 launches per frame (16 draws × 5); gemv becomes runtime-compiled (first-take TTFC risk unless prewarm covers the shapes) | Q 3807-3916 |
| F-06 | S3 | The bump needs a numerics and memory re-baseline; clone artifacts carry no MLX version, so stale embeddings are reused across versions | Qwen3TTSRuntimeProfile 202-213; Q 770-771 |
| F-07 | S3 | The ICL reference encode is lazy: it escapes `makeCloneHandle`'s scope and lease and is evaluated later inside `MLX.save` (persist) or the first take; it keeps MEM-1's encoder KV alive. Fix: `eval(refCodes)` in `createVoiceClonePrompt`. | Q 2164-2165; ST 926-937, 1144-1151 |
| F-08 | S3 | Error-scope docs will be wrong after the bump; EN-5 still open | Runtime 149-160; AudioMarking 11-12 |
| F-09 | S3 | DEP-2 not reachable, but every take opens the window (15 cold traces with nested compiled `silu`); the comment "nested compiled function is avoided" is false. Keep the single-flight invariant documented. | CodePredictorCompiled 91-105, 182-187 |
| F-10 | S3 | Not ready for `NonisolatedNonsendingByDefault`: marking, QC, WAV write and SHA would move onto the main thread; mark the three adapter entry points `@concurrent` | GOA 249, 333, 1613 |
| F-11 | S3 | swift-transformers' `Transformers` umbrella links Core ML model/generation code into an MLX-only app; depend on `Tokenizers` only | Package.swift 106 |
| F-12/13 | S3 | SEC-3 refined: the HuggingFace dependency serves only dead code and an unused parameter; about 1.9k unreachable fork lines (~10% of the package) ship, incl. a `Task { @MainActor }` MLX producer; the test-only output adapter/sink are listed as shipping sources | Runtime 12-24; TTSModel 79-180; ModelUtils 35-160; Generation 627-798 |
| F-14 | S3 | The iPhone benchmark build (`--optimized`, incremental) is not the shipped build (Release, `wholemodule`) despite the comment | ios_device.sh 449-498 |
| F-15 | S3 | The compiled code predictor's "byte-identical" claim is tested only at `accuracy: 2e-6` on a tiny fp32 model | CodePredictorCompiled 24-26; mlx-guide 360-362 |
| F-16 | PERF-L | Blocking MLX evaluation occupies Swift cooperative threads for seconds (load batches, marking, persist); give the facade engine a `DispatchSerialQueue` executor (as mlx-swift-lm #611 did) | Engine 311 |
| F-17/18 | S3 | Runtime tests disable TF32 (production NAX path untested); no TSan over the facade actor, session or error scope | macos_test.sh 1509; tsan-policy.json |
| F-19 | S3 | swift-huggingface 1.0 is coupled to swift-transformers 1.3.5 (<1.0 cap in 1.3.3); the update policy does not record it | Package@swift-6.1 |
| F-20–25 | S3 | Test gaps: no golden seeded-sampling canary (would have caught #4177); no reference-parity fixture for talker/code predictor in CI; no Mimi/speaker encoder tests; error-scope tests stop at prewarm/prime/producer; no MLX leak canary; no cancellation test inside load/warm/marking | various |

### D — Performance and memory, quantified (auditor D; lead verified D-01)

**Measured budgets.** iPhone 17 Pro (iOS 27.0.1, Speed 4-bit) from the Oct 14/16 smoke diagnostics;
the M6 from the Oct 7 benchmark.

| | iPhone 17 Pro | Mac M6 16 GB |
|---|---|---|
| Model load | 0.84–0.89 s cold pages, 0.30 s hot (0.14 s of it waiting on a 0.25 s tokenizer parse); first load after install ≈2.4 s (weight re-hash) | 0.28 s (app) |
| Engine first chunk | 0.39–0.41 s warm (Clone 0.44–0.49); +0.21–0.23 s on the first take after launch (codec decoder never warmed) | 0.15–0.27 s warm |
| **Audible start** | **1.1–2.1 s warm; long-form first segment 5.2 s**: the prebuffer adds 0.7–3.8 s | **0.95–2.35 s warm** (prebuffer +0.6–2.1 s) |
| Token loop | 24.7 tok/s ≈ 2× real time, RTF 0.55–0.59; per-frame cost rises 29 → 35 ms over 700 frames; decode 15–16% of the loop | 50–52 tok/s, RTF 0.27; decode ≈4% |
| AudioSeal marking | 38–55 ms per audio second: 0.24 s for 7 s, 2.1–3.4 s for 56–62 s (96–98% of finalization) | ≈20 ms per audio second |
| Memory | Resident model 1.36–1.40 GB; peak 2.1–2.6 GB of an **8,192 MB** iOS 27 limit (32%); cache pinned at 128 MiB with 113–126 clears per long take | physical 2.5–3.2 GB |

| ID | Sev | Finding | Where |
|---|---|---|---|
| D-01 | PERF-H | NEW: the live-preview prebuffer ignores generation speed: `max(3.25 s, min(8 s, 0.35 × estimate))`. Every warm take sounds 0.7–2.1 s later than the engine allows (0 underruns in 58 measured takes); the long-form first segment waits 3.8 s. A speed-aware buffer is bit-identical for the output. | LivePreviewEstimate 16-28; AudioPlaybackResumePolicy 85-117; AudioPlayerViewModel 109-131 |
| D-02 | PERF-M | iPhone Custom/Design never warm the codec decoder: +0.21–0.23 s on the first take after every launch (also the 8 GB Mac Custom path) | IOSAppBootstrap 194-201; MLXTTSEngine 2541-2549 |
| D-03 | PERF-M | Same as E-16: the iPhone launch protection pass rewrites metadata on every file, growing launch time with History size (launch → store ready 1.9–2.6 s; 3.3–4.6 s after install) | IOSAppBootstrap 63-84 |
| D-04 | S3 | A full unload left 309 MiB in MLX's buffer cache (2.4× the iPhone cap): the cache is cleared before the last holder releases the model | MLXModelLoadCoordinator 459-503; NER 520-524 |
| D-05 | PERF-L | Every iPhone reload re-parses the text tokenizer (+135 ms wall per reload after idle or background) | NER 2345-2353 |
| D-06 | PERF-M | The iPhone memory policy assumes a 6 GB budget, but iOS 27 grants 8 GB on the 12 GB iPhone 17 Pro: a 30 s idle unload, per-chunk cache clears and a 128 MiB cache cost reloads and allocator churn the app does not need; docs say "~6 GB" | NativeMemoryPolicyResolver 84-100; ios-engine-optimization §2.1 |
| D-07 | PERF-M | Same as E-15 (Mac launch re-hash of 2–14.65 GB), and it also holds back the first warm-up | ContentView 173, 378-382 |
| D-08 | PERF-L | Rejected takes pay the full marking pass before Fast QC rejects them (2.1–3.4 s per rejected 60 s segment); add a reject-only gross check before marking | GOA 2129-2186 |
| D-09 | PERF-M | Needs measurement: the in-process Mac app on the 8 GB floor ran at 4.5–5.1 GB, with about 2 GB of Metal allocation MLX does not account for (Sept 15–16 records) | benchmarks/runs/ui-generation/macos-xcui-benchmark-20260915-* |
| D-10/11 | PERF-L | iPhone decode is 15–16% of the loop and its per-frame cost grows +8–21% over a take; a 3–4-frame first chunk would cut about 0.1 s (partition invariance holds only within tolerance) | — |

**Measurement gaps** (all consent-bound lanes except 4–5):
1. No iPhone benchmark since Aug 11 (iOS 26.6).
2. No lane records Metal dispatch counts; add a `metal` profile kind.
3. No launch-to-Studio-ready metric.
4. Audible start is recorded but not trended.
5. Finalization is not split into marking and the rest.
6. Cold-reload frequency per real session is unmeasured.
7. Post-unload memory has no retained result.
8. No knob to A/B the per-chunk clear on iPhone.
9. No 8 GB hardware records since Sept 19.
10. No completed iPhone long-form timing.

### E — Model delivery, storage, persistence (auditor E; lead verified E-05)

Of the Oct 13 items, NET-1…10, STOR-1…6, DB-1…6, SER-3…9, E5-02/04/05, F-06, PA-33, BKL-14 and
DA-14 are all still open. F-18 is fixed in source with qualification pending; DA-13 is partial;
NET-9 and STOR-5 are refined below.

| ID | Sev | Finding | Where (IMDC = IOSModelDownloadCoordinator, HFD = HuggingFaceDownloader, SMCS = SharedModelComponentStore) |
|---|---|---|---|
| E-01 | S2 | NET-9 refined: two iPhone installs can run at once. The slot is claimed only after the awaited delivery plan, which hashes the 682 MB tokenizer; the second run's `resetForNewRepositoryDownload` drops the first's continuations unresumed. The first install hangs at "Cancelling" until relaunch, with two writers on one staging tree. | IMDC 159-215, 432-508; HFD 502-549, 1575-1586 |
| E-02 | S2 | NEW: any file failure calls `requestCancellation()`; `.cancelling` is persisted as `.cancelRequested`. The row freezes at "Cancelling" with no actions, queued models never start, and the next launch **silently deletes the staged gigabytes**. On the Mac a peer's `.cancelled` hides the failure reason. | HFD 653-659, 1628-1631; IMDC 576-580, 732-733, 952-979 |
| E-03 | S2 | NEW: staged files the current plan does not list are hard-linked into the installed model (staging keyed by model, not artifact version), so after a catalog layout change stale weights can load with a new config | SMCS 614-624, 1497-1534; HFD 3178-3325 |
| E-04 | S3 | NEW: a transient SQLITE_FULL/BUSY/IOERR during long-form acceptance rolls the journal back and **deletes the joined output and regenerated segments**. `busyMode` is `.immediateError`. | LongFormHistoryAcceptance 112-223, 510-523; DatabaseService 60-64 |
| E-05 | S3 | F-16 follow-up: one undecodable set-aside journal or outbox record makes `setAsideAudioPaths()` return nil, so the iPhone leftover-audio review is disabled forever. Safe, but a permanent storage leak in the backed-up `outputs/`. Fix: recover the absolute audio paths from the damaged file's raw bytes. | GenerationHistoryOutbox 650-664; LongFormHistoryAcceptance 443-468 |
| E-06 | S3 | E5-03 only half fixed: the downloader still accepts a file on size alone when its digest is nil or malformed (no production caller today) | HFD 1459, 2047, 2139, 3279-3286 |
| E-07 | S3 | The shared store takes a blocking `flock` in the iPhone App Group container on the MainActor (delete, install, engine-start reclaim); the downloader avoids exactly this for 0xDEAD10CC | SMCS 1230-1248 |
| E-08 | S3 | Streamed chunk directories have no sweeper (raw chunk copies can outlive History deletion; process-local request IDs reuse `session_%04d`) | NER 443, 2368-2371; GOA 538-543 |
| E-09 | S3 | A CLI-only Mac install leaves the 682 MB shared blob store in Time Machine (only the app excludes `models/`) | AppStartupCoordinator 26; SMCS 1224-1228 |
| E-10/11/12 | S3 | NET-5 refined (a failed restart after a background relaunch never releases the completion handler); DB-3 refined (background-URLSession relaunches open and reconcile History while backgrounded); SER-6 refined (a failed restore cancels every live background transfer at every launch) | IMDC 404-430, 1354-1361; QVoiceiOSApp 77-80 |
| E-13/14 | S3 | NET-7 refined (a stale chunk record after an update forces single-stream downloads); the iPhone catalog URL check fails open to the generic resolve URL (bytes still SHA-verified) | HFD 1158-1165, 2351-2364; IMDC 813-826 |
| E-15 | PERF-M | The Mac re-hashes every installed model at every launch (2.0–2.8 GB each, up to about 14.6 GB; the cache is in-memory and keyed by path; the shared tokenizer is re-hashed per model) | ModelManagerViewModel 987-1002; ModelAssets 399-405, 523-563 |
| E-16 | PERF-M | STOR-1 refined: the iPhone launch protection pass rewrites protection, backup and chmod attributes on every file under outputs/models/downloads/cache on the awaited startup path (an estimated 50–200 ms with thousands of files, and the ctime bump that defeats reclamation). Write only on mismatch. | IOSAppBootstrap 68-81; IOSStorageProtectionPolicy 61-182 |
| E-17/18 | PERF-L | The 682 MB shared component is hashed up to 5× per install; History search runs a Swift/ICU contains per row per keystroke on the single queue (delaying commits), re-registers its function per search, and counts per page (FTS5 or a folded column) | IMDC 171, 447; GenerationHistoryPage 197-291 |

Checked and clean (E): host and redirect allowlists, Range/206 handling, same-process receipts,
chunk assembly, store publication under lock with rollback, pinned catalog revisions and digests,
the ledger, the outbox publish/scan races and idempotent commit, journal bounds, diagnostics
privacy, Mac single-volume links, and draft persistence.

### C — Output path, Fast QC, long-form, text planning (auditor C; lead verified C-03)

**RF-15 silent gap, explained.** It is generator pacing drift inside one long take; Fast QC
behaved as specified.
- The same text boundaries pause about 0.7 s early in the ~60 s segment and 1.6–2.4 s some 30–40 s
  in.
- The gaps are true model near-silence (−72 dBFS) and not chunk-aligned; the Oct 14 gap holds a
  period-3 token cycle at codec frame 514. No words are dropped.
- Amplifiers:
  - Both runs used the phone's persisted **consistent** variation (T 0.7, top-p 0.9) on all 8 takes;
    the default is expressive, and the smoke never pins it (lead-verified).
  - The Neutral preset's "steady measured pacing" instruction, adopted 2026-08-01.
  - The planner fills every segment greedily to the 300-unit ceiling (867 chars, about 60 s).

| ID | Sev | Finding | Where |
|---|---|---|---|
| C-01 | S1 | ~60 s single takes drift into ≥2 s silences late in the take; long-form fails in ordinary use (2 of the last 3 full smokes) | GenerationOutputAdapter 3146-3161; LongFormPlanning 128-133 |
| C-02 | S2 | Planner fills each segment to the 300-unit ceiling; CJK segments reach about 70–78 s | LongFormPlanning 441-452, 670-708 |
| C-03 | S2 | iPhone smoke not hermetic: variation not pinned (both failures ran on "consistent") | VocelloiOSSmokeUITests 771-809 |
| C-04 | S2 | A symbol-only paragraph ("* * *") becomes its own segment; the project fails on every Resume | LongFormPlanning 219-231, 408-452 |
| C-05 | S2 | The per-sample silence floor sits at the codec noise floor, so dropout verdicts are unstable (refines QC-08) | GenerationOutputAdapter 1140, 1200-1222 |
| C-06 | PERF-H | AudioSeal marking is about 95% of end-of-take latency (3.4 s for a 62 s take): about 220k tiny dispatches; generator weights load and drop every take (refines PERF-9) | AudioSealGenerator 87-109, 340-345; AudioMarking 29-46 |
| C-07 | S3 | Expected-pause model ignores paragraph breaks and dashes, and counts decimals, "Dr.", "U.S.", times and URLs | GenerationOutputAdapter 3380-3400; SpokenTextPlanning 403-410 |
| C-08 | S3 | Leading silence is never judged for Custom and Design | GenerationOutputAdapter 1200-1206, 1529 |
| C-09 | S3 | Instability counters come from pre-marking audio ("QC judges what the user receives" is violated); the onset rule is masked by later bursts | GenerationOutputAdapter 3009-3018, 1246-1256 |
| C-10 | S3 | EN-5 still open: docs say marking is CPU-scoped | AudioMarking 11-12; AudioPublicationMarking 12-13 |
| C-11 | S3 | fsync and finalize errors are swallowed: a full disk reads as a QC failure; no directory fsync | GenerationOutputAdapter 1343-1346, 1447-1451, 646-658 |
| C-12 | S3 | MEM-3 is mostly mitigated by marking's clears; still open for pre-marking exits | GenerationOutputAdapter 2193-2228 |
| C-13/14 | S3 | E3-03 (`removeFirst` trap above 102.4 kHz) and E3-04 (app/CLI stream-session collision, empty dirs by default) still open | AudioQCSignalObserver 444-456; GenerationOutputAdapter 519-543 |
| C-15 | S3 | The joined History transcript is not the user's script; segments can start with a stray closing quote | IOSLongFormProject 399-413; LongFormPlanning 421-422 |
| C-16 | S3 | The assembler trims edges ≤ −44.6 dBFS (up to 500 ms) without a fade: clipped soft onsets and tails, and steps at joins | LongFormAssembly 426-521 |
| C-17 | S3 | Joins insert 300 ms against 0.6–1.1 s in-segment pauses; the joined QC can refuse segments that all passed, and Resume rebuilds the same join | LongFormPlanning 38-47; LongFormAssembly 243-263 |
| C-18/19 | S3 | Cadence evidence truncates at 256 runs on long joined outputs; the record floor is 2,400 samples, not 100 ms | GenerationOutputAdapter 1141-1147 |
| C-20–25 | PERF-L | Long-form repeats Fast QC per segment; the signal observer, shadow plan and 3–4 language detections run with telemetry off; about 7 full-file passes at take end; O(window) step-burst bookkeeping; MainActor planning with quadratic risk mapping | various |
| C-22 | S3 | The shadow plan digest binds the raw script, not the normalized model-facing text | NativeEngineRuntime 1128-1139, 1379-1393 |
| C-26 | S3 | The delivery receipt records the requested style, not the instruction sent; `promptDigest` is an unsalted SHA-256 (guessable for short scripts; telemetry only) | SemanticTypes 1492-1499 |
| C-27/28 | S3 | A second output pipeline exists only in tests (AtomicWAVGenerationOutputSink, ProductOutputAdapter); dead code (pcmSamples, previewTitle, validatePromptText, unused script scalars, test-only sub-seed derivation) | various |
| C-29–32 | S3 | WAV-layout doc drift (44-byte claim against AVAudioFile's JUNK/FLLR layout); marking fails open if its configuration resolves to nil; planning errors reach the UI as raw enum text; a throwing finalization acknowledgement after rename leaves an unowned published WAV | various |
| C-33 | S3 | D6 still by design: Custom under Auto falls back to English plus the English diction instruction | GenerationSemantics 852-878 |
| — | FIXED | SER-1/F-16 (journal exits), E7-02 (adapter choreography tests), E4-01 (chat-template minimum, in code) | — |
| — | OPEN | BKL-01, BKL-14 unchanged | — |

Checked and clean (C): atomic publisher and staging sweep, incremental WAV writer lifecycle,
Float→Int16 and the limiter, RIFF/LIST handling, SHA-256 over the published bytes, windowed
watermark embedder, persisted-QC reads, planner protected spans and deterministic IDs, the bounded
assembler, runner cancellation and resume seeds, F-16 journals, the single-take executor ordering,
control-token neutralization, and the privacy of failure telemetry.
