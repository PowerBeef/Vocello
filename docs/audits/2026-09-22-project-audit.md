---
status: historical
owner: backend-and-platform
reviewed: 2026-09-22
summary: Independent, whole-project audit of Vocello at 7e26f94 covering engine, apps, security, CI/release, tests, docs and website, with a prioritized action plan.
sourceOfTruth:
  - config/roadmap.json
---
# Vocello: comprehensive project audit, September 22, 2026

**Audited revision:** `main` at `7e26f94` ("fix(qa): bind Mac perf evidence to the tested app receipt"), 2026-09-22.
**Method:** eight parallel specialist reviews, then lead cross-verification of every High finding against source (section 2).
**Status of this document:** point-in-time evidence. Open work belongs in [`config/roadmap.json`](../../config/roadmap.json). Finding IDs here are local to this report.

## Contents

1. [Executive summary](#1-executive-summary)
2. [Scope, method and limits](#2-scope-method-and-limits)
3. [Project at a glance](#3-project-at-a-glance)
4. [Cross-cutting themes](#4-cross-cutting-themes)
5. [Engine runtime: `Packages/VocelloQwen3Core`](#5-engine-runtime-packagesvocelloqwen3core)
6. [Engine host layer: `Sources/QwenVoiceCore`](#6-engine-host-layer-sourcesqwenvoicecore)
7. [macOS app and shared UI](#7-macos-app-and-shared-ui)
8. [iOS app and commerce](#8-ios-app-and-commerce)
9. [Security, privacy and compliance](#9-security-privacy-and-compliance)
10. [Build, CI/CD and release engineering](#10-build-cicd-and-release-engineering)
11. [Testing and QA](#11-testing-and-qa)
12. [Documentation, public claims, website and repository hygiene](#12-documentation-public-claims-website-and-repository-hygiene)
13. [Status of previously tracked findings](#13-status-of-previously-tracked-findings)
14. [Prioritized action plan](#14-prioritized-action-plan)
15. [Appendix: severity scale, finding counts and evidence log](#15-appendix-severity-scale-finding-counts-and-evidence-log)

---

## 1. Executive summary

### Verdict

Vocello is an unusually ambitious and, at its core, very well-engineered local-first TTS product:
- It has its own Swift/MLX runtime.
- Model delivery is digest-pinned and atomic.
- Its streaming channel is rigorous and never drops audio.
- Its StoreKit design is minimal and correct.
- Its supply-chain hygiene is well above what most solo projects achieve.

**No Critical issues were found.** No in-app way around the paywall exists, and no secrets are exposed.

The risks are concentrated in four places the project's substantial verification machinery does not reach:

1. **Paths that rarely run are broken, and nothing notices.**
   - The release workflow will very likely fail on the next tag (CI-01).
   - The nightly failure reporter has never worked (CI-02).
   - The Swift dependency watch has failed on every run since it was added (CI-03).
   - A TSan failure is dropped after the next docs-only push (CI-06).
2. **The layer between the engine and the user is barely tested.** About 85% of app-side Swift is not compiled into any unit-test target. The real Qwen3 generate loop and the watermark transform never run in CI. The two confirmed codec fidelity defects (ENG-01, ENG-02), the prewarm deadlock (CORE-01) and most app findings sit exactly there.
3. **Platform-edge lifecycle is under-owned.** The engine core is rigorously actor-owned, but the edges are not:
   - iOS backgrounding during generation (IOS-01);
   - the audio session;
   - window closing;
   - startup recovery;
   - main-thread launch work (MAC-01).
4. **Public statements have drifted from shipped reality.**
   - The README promises an AI watermark that the 2.4.0 download doesn't have (DOC-01).
   - A voice-cloning marketing sample is live, contrary to the project's own rights review (SEC-03).
   - Several docs claim invariants the code doesn't honour.

A fifth, structural observation underlies the first two: **the tooling and process apparatus is now as large as the product.** That is roughly 125K lines of scripts, tests, contracts and workflows against 125K lines of product Swift. Section 4.2 covers it.

### Scorecard

Grades are the auditor's judgement, weighted by user impact.

| Area | Grade | One-line rationale |
|---|---|---|
| Engine architecture and concurrency | **A−** | Excellent actor, lease and lossless-channel design; the prewarm-slot leak (CORE-01) and memory-relief serialization (CORE-06) are the exceptions |
| Engine numerical fidelity | **B−** | Decoder ignores its sliding window (ENG-01); quality-first trim bug (ENG-02); the real generate loop is untested in CI |
| Model delivery and runtime security | **A** | Pinned revisions, per-file digests, host allowlist, atomic symlink-safe publication |
| Release and CI security | **C+** | Actions and tools pinned, but signing secrets have no Environment protection and share jobs with third-party code (SEC-01, SEC-02) |
| CI/CD reliability | **C** | Release path very likely broken; two scheduled workflows never worked; no pre-merge gate; `main` red on 12% of pushes |
| macOS app | **B** | Disciplined generation lifecycle; launch-time main-thread hashing (MAC-01), broken toggles, raw English errors |
| iOS app | **B−** | Exemplary commerce and export gate; background, audio-session and recoverability gaps |
| Testing strategy | **C** | Existing Swift tests are behavioural and well written; the orchestration layer, real model paths and UI are unprotected in CI |
| Accessibility | **B−** | Solid foundations; unlabelled editors (macOS), no VoiceOver announcements, fixed fonts (iOS), website contrast |
| Localization | **B−** | Complete 10-locale catalog, but computed English, raw errors and missing plurals leak through |
| Documentation accuracy | **C+** | Machinery excellent; content drifted (DOC-01, agent-workflow contradictions, a 1,115-line "start here" file) |
| Maintainability and proportionality | **C** | Tooling roughly equal to product; 51 JSON contracts; 168 environment and build knobs; research code in the product gate |
| Website | **B** | Clean code and tests; 5.6 MB first load, contrast failures, stale facts |

### Top 10 issues

| Rank | ID | Issue | Severity | Why it matters |
|---|---|---|---|---|
| 1 | CI-01 | Release jobs don't install the pytest/xdist pins they then validate | High | The 3.0 tag will very likely fail on release day |
| 2 | DOC-01 | README and website describe unreleased 3.0 features, including the AudioSeal watermark, next to the 2.4.0 download | High | Users don't get the AI-disclosure marking the README promises |
| 3 | SEC-01 | Developer ID, notary and App Store secrets are usable by any dispatched ref's edited workflow | High | Possible compromise of the code-signing identity; cheap to fix |
| 4 | ENG-01 | The speech-tokenizer decoder uses full attention instead of the reference's 72-frame sliding window | High | Output diverges from the official codec after about 6 s; memory grows with take length |
| 5 | IOS-01 | No background policy during generation; GPU work from the background likely terminates the app | High | Home, a phone call or Auto-Lock mid-take or mid-long-form loses the take |
| 6 | MAC-01 | Every macOS launch SHA-256 hashes all installed models (6–15 GB) on the main thread | High | Multi-second launch hang for every user with models installed |
| 7 | CORE-01 | A prewarm-slot leak on cancellation wedges the engine until relaunch | High | Rare, but unrecoverable without quitting |
| 8 | TEST-01/02/03 | Orchestration layer, real generate loop and watermark transform are untested in CI | High | Items 4–7 all live where the tests don't |
| 9 | SEC-03, SEC-04 | Unconsented voice-cloning sample on the website; clone consent enforced only in views (CLI bypass, issue #101) | Medium | Legal and reputational exposure for a voice-cloning product |
| 10 | CI-02 to CI-05 | Dead alerting, no PR lane, Dependabot PRs that can't pass the repository's own contract | Medium | Regressions and security updates sit unseen for weeks |

### Strengths worth protecting

- **Model trust boundary:** 40-hex revision pins, per-file SHA-256 and size, exact host and path allowlists, `O_NOFOLLOW` locks, `RENAME_SWAP` publication. A failed install always preserves the previous one.
- **Streaming engine:** the actor-owned, frame-bounded, lossless audio channel; typed, awaited cancellation; request-local sampling; lease and epoch revalidation after every suspension. Every `@unchecked Sendable` is registered.
- **Commerce:** one StoreKit owner, verified-only entitlements, revision guards against stale refunds, and a single export gate keyed on each output's recorded mode. No bypass found.
- **Publication safety:** QC runs on the exact watermarked bytes before an atomic rename; the History outbox is idempotent; saved voices are journaled.
- **Supply chain:** 100% SHA-pinned actions, SHA-verified tool binaries, exact Swift pins, lockfile installs, SBOMs, attestations, exact-SHA release authority.
- **Honesty culture:** PASS-only benchmark records with regressions kept on record; "directional" delivery presets labelled as such; a website limitations section.
- **Code hygiene:** 0 `try!` and 0 `fatalError` on reachable paths in the app and core; shellcheck clean at warning level; Python has no undefined names or bare excepts.

---

## 2. Scope, method and limits

**What was reviewed.** All 1,580 tracked files at `7e26f94`:
- Swift product code: apps, core, CLI and the owned engine package.
- Swift and Python tests.
- The 107 Python and shell scripts under `scripts/`.
- 51 JSON contracts.
- 6 workflows and 1 composite action.
- The website.
- 107 Markdown documents.
- Repository assets.

Live GitHub state was read through the API: Actions runs and job logs, issues, pull requests and releases.

**How.** Eight specialist reviewers worked in parallel, one per area: engine package, engine host layer, macOS app, iOS app, security/privacy/supply chain, build/CI/release, tests/QA, and docs/website/repository. Each traced code paths by reading the source; grep was used only to locate code. The lead auditor then re-verified every High finding, and several Medium ones, directly against source. Those include:
- ENG-01, checked against the official reference implementation;
- ENG-02, CORE-01, MAC-01, MAC-02, IOS-01, CI-01, SEC-01, SEC-02 and SEC-03;
- DOC-01, checked against the `v2.4.0` tag;
- the consent-gate scope.

Confidence labels:
- **Confirmed:** the code path was traced.
- **Likely:** the path was traced, but the runtime effect depends on platform behaviour that could not be executed.
- **Speculative:** plausible, not proven.

**What was executed**

| Check | Result |
|---|---|
| Python suite, full-history clone | 1,519 passed, 51 skipped (Darwin-only), 911 subtests |
| Contract gate (`check_project_inputs.sh --python none`) | Pass |
| `ruff` | Clean for undefined names and bare excepts; 55 unused imports (CI-09) |
| `shellcheck` | Clean at warning level |
| Website: lint, 12 unit tests, build, 2 Playwright viewports | All pass |
| `npm audit` | 0 vulnerabilities |
| Relative-link check over 804 Markdown links | 3 broken |
| Inline-Python syntax check over 29 workflow snippets | 1 error (CI-02) |
| Page-weight measurement in headless Chromium | ~5.6 MB first load (WEB-02) |
| GitHub API reads (CI history, job logs, issues, PRs, releases) | Used for the live observations in section 10 |

**Limits**
- This is a Linux container with no Xcode or Swift toolchain, so **nothing native was compiled or run**. There were no device, model, UI or benchmark lanes.
- Audible and timing impacts are therefore reasoned, not measured. They are labelled accordingly.
- GitHub repository settings (branch protection, rulesets, secret scopes) and Vercel settings were not visible.
- License conclusions rely on text in the repository; no upstream license texts were fetched.
- Line numbers refer to `7e26f94`.

---

## 3. Project at a glance

| Dimension | Measure |
|---|---|
| Product Swift (`Sources/`) | 319 files, 102.2K lines: core 38.5K, iOS 27.6K + 4.6K, macOS views/services/models ~18K, shared 9.0K, CLI 3.6K |
| Owned engine package | 17.7K source lines + 5.3K test lines; largest file `Qwen3TTS.swift` (6,154 lines; one 1,107-line function) |
| Swift tests running in CI | 837 unit tests (616 core + 96 iOS-logic hosted on macOS + 125 runtime); 55 UI tests that never run in CI |
| Python and shell tooling | 123 Python scripts (61.9K lines) + 36 shell scripts (11.2K lines); 1,550 Python tests (34.9K lines) |
| Configuration contracts | 51 JSON files (898 KB); 168 environment and build knobs |
| CI | 6 workflows, 23 jobs, 143 steps; 661 CI runs; median green run 6.2 min |
| Website | React 19 + Vite 8, ~3.7K lines; 73 KB gzipped JS; 5.6 MB first load |
| Documentation | 107 Markdown files, 27.8K lines (~264K words) |
| Repository | 1,580 tracked files; 84 MB working tree; 66 MB pack; 1,736 commits since Feb 21 (~8/day) |
| Releases | Latest public v2.4.0 (Aug 1); 3.0.0 candidate in progress; iPhone on TestFlight |
| Tracker | 6 open issues; 6 open PRs (5 Dependabot, 1 draft); 63 open roadmap items (39 parked) |
| Findings in this report | **172**: 0 Critical, 12 High, 58 Medium, 94 Low, 8 Info (section 15) |

---

## 4. Cross-cutting themes

These patterns explain most of the individual findings. Fixing the pattern prevents the next instance.

### 4.1 Verification effort points at the evidence pipeline, not at the product's orchestration layer

The project has built an exceptional evidence apparatus: PASS-only benchmark records, required-step ledgers, fixed-seed byte-identity gates, and typed quality identities.

The automated tests that run on every push are aimed elsewhere:
- 1,550 Python tests cover tooling only.
- 37% of core Swift test methods cover telemetry, diagnostics or the test harness.
- Coordinators, stores, runners and view models (about 85% of app-side Swift) have no unit tests.
- The real generate loop and the AudioSeal transform never run in CI.

Most High and Medium findings in this audit sit in exactly that untested region: ENG-01, ENG-02, CORE-01, CORE-06, MAC-01 to MAC-05, IOS-01 to IOS-07, and SEC-04.

**Recommendation:** redirect new test effort to a fake-engine seam over the orchestration layer and a tiny random-weight model test (section 11.4). Treat evidence-tooling tests as secondary.

### 4.2 The tooling mass exceeds what can be kept exercised

The measurements:
- About 125K lines of tooling (73K scripts + 35K Python tests + 15K contracts + 2K workflows) against about 125K lines of product Swift.
- 27 orchestration workflows with required-step ledgers.
- 651 KB of roadmap and progress data.
- 11.5K lines just for publishing benchmark history.
- About 37K lines of research tooling inside the product gate.
- Date-stamped one-off contracts such as `ios-control-audit-contract-20260904.json`.

`AGENTS.md` itself says to "keep tooling proportional" and to "add a check only for a demonstrated product or workflow risk". The breadth has outrun how often each path actually runs:
- The release path is broken (CI-01).
- The nightly reporter has never worked (CI-02).
- The dependency watch has never succeeded (CI-03).
- The TSan "blocking" promise has a hole (CI-06).
- Several contracts assert source *text* rather than behaviour (TEST-06).

Contracts *describe* paths; rehearsals *exercise* them.

**Recommendation:** adopt a one-in, one-out rule for contracts. Move research tooling to its own tree and environment. Spend the saved effort on rehearsals: a weekly ad-hoc-signed release dry run, and a nightly model-free UI subset.

### 4.3 Trunk-only, post-merge gating

Hooks block branches and worktrees, and CI runs only after a push to `main`. For one maintainer plus coding agents, that means no review and no verdict before landing:
- 12 of the last 100 pushes were red, with a 9-run red streak.
- Dependabot PRs pile up untested, and their action bumps *cannot* pass the repository's own contract.
- `CODEOWNERS` has no effect.

**Recommendation:** keep the fast inner loop, but land through short-lived branches with a ~5-minute Linux PR lane and auto-merge on `CI required` (CI-04, CI-05).

### 4.4 Prose claims that the code does not honour

Several documents state invariants the code doesn't implement:

| Document | Claim | Reality |
|---|---|---|
| The Mimi guide | The decoder uses a sliding window (72) | It doesn't (ENG-01) |
| Model delivery docs | Redirects are host-allowlisted | Not for iOS background sessions (SEC-08) |
| `privacy-storage.md` | Recorded clips are deleted on enroll or cancel | They aren't (MAC-25) |
| The debug-knob registry | Knobs are "unavailable without internal capability" | Three aren't (SEC-06), nor are several iOS diagnostics keys (IOS-15) |
| `Engine.swift` comment | Loads are cancellable | They aren't (ENG-09) |
| README | The watermark is shipped | Not in the downloadable release (DOC-01) |

The authority order in AGENTS.md (code → config → scripts → prose) is sound. But nothing flags prose that has stopped being true.

**Recommendation:** when a document asserts an invariant, it should name the test that proves it. Add a lightweight check that such references resolve.

### 4.5 Ownership stops at the platform edge

Inside the engine, ownership is rigorous: actors, leases, epochs, typed cancellation. At the platform edge, several concerns have no single owner:
- iOS scene phases and background execution (IOS-01, IOS-02, IOS-11).
- The audio session: 20 mutation sites (AUD-02, IOS-03, IOS-04).
- Window lifetime (MAC-05).
- Startup recovery (AUD-01, MAC-04, IOS-05, IOS-06).
- Memory relief versus proactive loads (CORE-06).
- Main-thread file work (MAC-01, CORE-16, IOS-06, IOS-23).

**Recommendation:** give each of these concerns one owner type, the way `StudioGenerationCoordinator` already owns generation attempts.

### 4.6 Things created but never cleaned up

The storage lifecycle has several one-way doors:
- Derived voice artifacts from one-off clone references, which are also backed up (CORE-05).
- Shared model components and `trash/` (CORE-07).
- Crash-orphaned staging WAVs (CORE-15).
- `tmp/voice-enroll` recordings (MAC-25).
- Orphaned iOS outputs after "Keep Audio Files" (IOS-10).
- Undeletable audio after a failed unlink (AUD-05).

**Recommendation:** each creator should register a cleanup policy (on delete, on startup sweep, or bounded cache), and `privacy-storage.md` should list every class of stored file.

### 4.7 English leaks around the localization system

The string catalog is complete in 10 locales. User-visible English still appears through three channels the literal-string contract can't see:
- computed display properties in QwenVoiceCore;
- raw `error.localizedDescription`;
- hard-coded defaults and formats.

This affects MAC-06, MAC-07, MAC-10, MAC-11 and IOS-14.

**Recommendation:** one typed-error-to-catalog mapper, and a contract rule that flags QwenVoiceCore display strings used in views.

---

## 5. Engine runtime: `Packages/VocelloQwen3Core`

**Scope:** 32 source files (17.7K lines) and 13 test files (5.3K lines, 125 tests), plus the ownership ledgers.

**Verdict:** The concurrency design is strong. The lossless audio channel removes every continuation before resuming it, and cancellation wakes blocked producers. The engine actor revalidates its lease and model epoch after every suspension. Each request owns its random state. All 15 `@unchecked Sendable` types are registered.

The problems are elsewhere:
- **Numerical fidelity to the reference codec.** The Swift decoder departs from the official implementation in two places (ENG-01, ENG-02).
- **Fail-closed loading.** Several load paths delete files, crash, or accept incomplete models.

Neither class of problem can be caught today, because the 6,154-line `Qwen3TTS.swift` generate loop never runs in CI. Every generation test uses a fake model.

| ID | Finding | Severity | Confidence |
|---|---|---|---|
| ENG-01 | Speech-tokenizer decoder ignores its 72-frame sliding window | **High** | Confirmed (divergence) / Likely (audible impact) |
| ENG-02 | Quality-first decode treats codec value 0 as padding and trims the end of the take | Medium | Confirmed |
| ENG-03 | Model loader recursively deletes the model directory it does not own | Medium | Confirmed |
| ENG-04 | Tokenizer load failures are swallowed; `load` reports success for an unusable model | Medium | Confirmed |
| ENG-05 | Malformed model state crashes the process instead of throwing | Medium | Confirmed |
| ENG-06 | Resident speech tokenizer shares one mutable decoder across engine instances, contrary to its own comment | Medium | Likely (latent) |
| ENG-07 | Conditioning-prefix cache key is case- and whitespace-folded, but the cached embedding is not | Low | Confirmed |
| ENG-08 | One-word prompts are rejected, and the error message embeds the user's text | Low | Confirmed |
| ENG-09 | Model load cannot be cancelled, contrary to the code comment | Low | Confirmed |
| ENG-10 | Long synchronous MLX work on the actor delays memory-pressure handling; clone reference length is unbounded in the package | Low | Likely |
| ENG-11 | `prime()` runs model work off the actor; `persistCloneArtifact` skips the lease | Low | Speculative race |
| ENG-12 | Frames → seconds → frames round-trip shortens some custom chunk sizes by one frame | Low | Confirmed |
| ENG-13 | Global prefix cache can pin a previous model's embedding weights after a model switch | Low | Speculative |
| ENG-14 | Ownership ledgers have drifted: `MLXAudioMark` is untracked and the validator only checks one direction | Low | Confirmed |
| ENG-15 | AudioSeal marking builds a ~90k-step lazy graph for long takes, and a length shortfall silently writes zeros | Low | Likely |
| ENG-16 | Finish reason is read back from a shared diagnostics dictionary; token counts include EOS | Low | Confirmed |
| ENG-17 | Latent hang paths: non-cancellable waits, and a reservation that is never resolved wedges the engine | Low | Likely latent |
| ENG-18 | Dead upstream code widens the surface (unpinned download path, float WAV writers, unused Mimi decoder, legacy stream APIs) | Info | Confirmed |

### ENG-01: The decoder transformer ignores its 72-frame sliding window (High)

**Evidence**
- `Qwen3TTSSpeechTokenizer.swift:490-498` always builds a full causal mask: `MultiHeadAttention.createAdditiveCausalMask(totalLen)`.
- `makeCache()` (`:506-508`) returns an unbounded `KVCacheSimple` per layer. The streaming decoder keeps it for the whole take (`transformerCache`, `:1035-1052`).
- `Qwen3TTSConfig.swift:349` decodes `sliding_window ?? 72`, but the decoder never reads it. Only the encoder does (`:897`).
- In the official reference (`QwenLM/Qwen3-TTS`, `modeling_qwen3_tts_tokenizer_v2.py`), every decoder layer is hard-wired to `attention_type = "sliding_attention"` (l.419). The model builds its mask with `create_sliding_window_causal_mask` (l.549-551).
- The project's own `docs/reference/mimi-codec-guide.md:239` and `:334` describe a sliding-window mask and a KV cache "bounded by the sliding window (72), not by utterance length". The code does neither.

**Impact**
- Every frame after frame 72 (5.76 s of audio) attends to the entire history. That is a context the codec was never trained on, so output diverges from the reference decoder on every take longer than about 6 seconds.
- The decoder KV cache grows about 32 KB per frame, roughly 120 MB for a 5-minute take.
- Each streaming step builds a `T×T` mask before slicing it. At T = 3,750 frames that is about 28 MB of work and allocation per chunk, repeated every chunk.
- The existing partition tests cannot catch this, for two reasons. Full attention is invariant to partitioning. And the test configuration sets `sliding_window: 512`.

The audible effect has not been measured. The project's QC gates pass, so the effect may be subtle, but it is a real fidelity and memory defect.

**Related:** the Mimi encoder only trims its KV cache on incremental calls (`Mimi/Transformer.swift:159-163`). A single-shot `encode` of a clone reference longer than 10 s therefore also attends past its 250-frame window. References of up to 120 s are accepted (`AudioPreparation.swift:103`).

**Recommendation**
- Apply the window in the mask: allow only `key_pos > query_pos − 72`.
- Use a rotating or trimmed KV cache.
- Add a PyTorch-reference parity fixture longer than 72 frames.
- Gate the change on the existing fixed-seed WAV/ASR/QC battery. It changes output bytes by design, so record it as a CODEC semantic delta.
- Apply the same treatment, or a length cap, to the encoder's single-shot path.
- Correct the Mimi guide.

### ENG-02: Quality-first decode trims valid audio (Medium)

**Evidence**
- `Qwen3TTS.swift:2971-2975`: `validLen = (codes[..., 0] .> 0).sum() * decodeUpsampleRate`, then `audio = audio[..<validLen]`.
- The same `> 0` test appears in replay (`:3025`) and in `Qwen3TTSSpeechTokenizer.decode` (`:1159`).
- The reference uses `(audio_codes[..., 0] > -1).sum(1)` (l.1012). There, padding is −1 and **0 is a valid code**. The sampler only suppresses IDs 2048..<3072, so 0 is a legitimate first-codebook token.

**Impact**
- Every frame whose first code is 0 removes 80 ms (1,920 samples) from the **end** of the take, which can clip the last syllable.
- On the ICL clone path the proportional reference cut (`:4146-4153`) is computed from the shortened length. That leaves a sliver of reference audio at the start of the output.
- This affects `.qualityFirst` decoding: CLI and bench `--no-stream`, and default-constructed requests (`NativeEngineRuntime.swift:1143`).

**Recommendation**
- This path never pads, so use the actual frame count.
- Cut ICL output at exactly `refLen × decodeUpsampleRate`.
- Add a test with a zero code in codebook 0.

### ENG-03 to ENG-05: Loading is not fail-closed (Medium)

**ENG-03: the loader deletes the model directory**
- `Qwen3TTS.swift:5741-5746`: if `speech_tokenizer` exists but is not a directory, the loader runs `try? fileManager.removeItem(at: modelDir)`.
- A runtime that does not own the directory thereby deletes a multi-GB install. This bypasses the host's staged, locked and atomic publication (`MLXModelLoadCoordinator.swift:709-718`).
- **Fix:** throw a typed "corrupted prepared directory" error and let the host reconcile it.

**ENG-04: tokenizer failures are logged, not thrown**
- `Qwen3TTS.swift:5582-5601` catches a text-tokenizer load failure, prints `"Warning: Could not load tokenizer: \(error)"` to stderr (which can include paths), and continues.
- A missing `speech_tokenizer/` also only warns (`:5747-5749`).
- The host then treats the model as warm, and every take fails with an opaque `.failed(.runtime)`.
- **Fix:** throw from `load` when the text tokenizer or speech decoder is missing, or the encoder for base models.

**ENG-05: malformed state crashes the process**
- **No MLX error capture.** The package never uses `withError`. In mlx-swift 0.31.6, an uncaught MLX error calls `fatalError`.
- **Trusted loads skip shape checks.** They verify with `.noUnusedKeys` only (`:5339-5347`, `:5989`). That disables both `.shapeMismatch` and `.allModelKeysSet`, so a missing tensor silently keeps its initial value.
- **Force-unwrapped config.** `config.talkerConfig!` (`:1860`, `:3126`) can crash the first take after a relaxed load.
- **Clone artifacts are not range-checked.** `refCodes` are never checked for shape or range (0..<2048) before an unchecked GPU gather (`:4279-4287`).
- **Fix:**
  - Always verify with `[.noUnusedKeys, .shapeMismatch, .allModelKeysSet]`.
  - Replace the force unwraps with a throwing guard.
  - Validate clone and AudioSeal tensors on adoption.
  - Wrap load and adopt work in `withError`.

### ENG-06: One mutable decoder is shared across engine instances (Medium, latent)

- `Qwen3TTS.swift:5654-5670` adopts a process-resident speech tokenizer and calls `decoder.resetStreamingState()` on it.
- The host creates a fresh `VocelloQwen3Engine` per load, each with its own lease (`UnsafeSpeechGenerationModel.swift:116`).
- The comment at `:438-440` says sharing "would bypass each engine's operation lease". That is exactly what happens.
- Safety depends on an undocumented host guarantee that the old engine's work never overlaps the new engine's load. If it does, the new load resets the old take's decoder mid-stream, and two actors race on `streamBuffer` and `transformerCache` behind `@unchecked Sendable`.
- **Fix:** share weights, not streaming state. Or add an owner token that refuses adoption until the previous owner releases. Record the behaviour in `SEMANTIC_DELTAS` and tighten the registry invariant.

### Lower-severity engine items

**ENG-07 (prefix cache key folding)**
- Custom Voice and Voice Design prefix cache keys are lowercased and whitespace-collapsed (`Qwen3TTS.swift:1446-1455`, `:1510`, `:1518`). The cached embedding tokenizes the case-preserving text (`:1579-1581`).
- Case or spacing variants therefore share an entry. That breaks the "same seed reproduces the take" contract depending on cache history.
- **Fix:** key the cache on exactly the tokenized string.

**ENG-08 (short prompts)**
- `guard textTokenCount >= 10` (`:4640-4644`) rejects one-token inputs. Its message interpolates the user's text (`'\(originalText)'`), which can reach logs through the prime and prewarm paths (see AUD-08).
- **Fix:** relax the guard to 9 tokens or pad short input, and use a typed error without user text.

**ENG-09 (load cancellation)**
- `Engine.swift:450-457` claims "cooperative checkpoints" during load, but the loader contains no cancellation check at all.

**ENG-10, ENG-11 (actor isolation)**
- `makeCloneHandle` and `replayCodecTrace` are synchronous whole-buffer MLX work on the engine actor. Pressure ingress queues behind them.
- `LoadedModel.generate*` wrappers are nonisolated async, so `prime()` runs MLX off the actor while holding the lease.
- `persistCloneArtifact` takes no lease.

**ENG-12 (chunk-size round trip)**
- `Contracts.swift:301-303` converts frames to seconds and `Qwen3TTS.swift:3322-3323` converts back.
- 18 frame counts come back one lower, for example 29, 57, 113 and 201. Product defaults are unaffected.

**ENG-13 (prefix cache pins old weights)**
- Prefixes are cached lazily before validation. On iOS (2 entries) and macOS (16), those unevaluated graphs can keep the previous model's text-embedding table alive after a switch.

**ENG-14 (ledger drift)**
- `MLXAudioMark` is a dependency of the facade, but is missing from `COMPATIBILITY.json`, `RUNTIME_MANIFEST.json` and `OWNERSHIP.json`.
- `qwen3_core_contract.py:1044-1047` checks only one direction.
- The `audio-converter-provider` concurrency entry cites a test that never exercises it.

**ENG-15 (AudioSeal marking)**
- `SkipLSTM` (`AudioSealGenerator.swift:83-105`) builds one lazy graph of `frames` sequential steps per layer. It recomputes `wHH.T` on every step.
- `out` starts as zeros and only `min(span, delta.count)` samples are written (`:333-351`), so a length shortfall silently zeroes audio.
- **Fix:** precompute the transpose, evaluate in chunks, and seed `out` from the input PCM.

**ENG-16 (finish reason and token count)**
- The end reason is read back from `latestPreparationStringFlags`, which a public, lease-free method can reset.
- `streamFinishReason` maps `"max_tokens"`, which the model never emits (it emits `"token_cap"`).
- `generatedTokenCount` includes the EOS token.

**ENG-17 (latent hangs)**
- `runGeneration` has two early returns that never resolve the session (`Engine.swift:1236-1241`, `:1326`).
- Three barriers use non-cancellable `withCheckedContinuation`.
- A never-resolved reservation wedges `beginOperation` permanently.
- None of these is reachable today; they need a guard for the future.

**ENG-18 (dead code)**
Delete the following, which have zero product callers:
- `TTS.loadModel(modelRepo:)` and `ModelUtils.resolveOrDownloadModel`, which download `revision: "main"` without digests (see SEC-12).
- The float32 WAV writers and resampler.
- The legacy `generate*Stream` APIs.
- `Qwen3TTSSpeechTokenizer.decode` and `chunkedDecode`.
- The Mimi `SeanetDecoder`.
- The ignored `VocelloQwen3CachePolicy`, which is the only reason the facade depends on swift-huggingface.

**AUD-11 (sampler membership) is still open:** `Qwen3TTS.swift:4710-4715` still uses a linear scan. The outer `generatedCodebookTokenIDs` set is written on every token but never read.

**Engine metrics**

| Metric | Value |
|---|---|
| Largest function | 1,107 lines (`generateVoiceDesign`, `Qwen3TTS.swift:3086-4193`) |
| Force unwraps | about 17 (2 depend on model input) |
| `withError` uses | 0 |
| Actors | 10 |
| `checkCancellation` call sites | 69 |
| Direct dependency pins | 4, all exact, and consistent with the app's `Package.resolved` |

---

## 6. Engine host layer: `Sources/QwenVoiceCore`

**Scope:** 77 files, 38.5K lines, plus `Sources/QwenVoiceBackendCore`.

**Verdict:** The trust and publication machinery here is excellent:
- The catalog requires pinned 40-character revisions, per-file SHA-256 and sizes.
- Installs are atomic `RENAME_SWAP` replacements under a cross-process lock.
- Generated audio is QC-checked on the exact watermarked bytes before an atomic rename.
- Saved voices use a journal.
- The code contains no `try!` or `fatalError`.

The findings cluster around three themes:
1. Concurrency edge cases in prewarm and memory relief (CORE-01, CORE-06).
2. Error handling by string matching (CORE-03).
3. Storage lifecycle leaks: derived voice data, shared components, overlays and temporary files (CORE-05, CORE-07, CORE-08, CORE-15).

**Size:** 10 files are over 1,000 lines. The largest are `HuggingFaceDownloader` (3,180), `GenerationOutputAdapter` (3,157), `NativeEngineRuntime` (2,320) and `MLXTTSEngine` (2,076).

| ID | Finding | Severity | Confidence |
|---|---|---|---|
| CORE-01 | Prewarm slot leaks permanently if a waiter is cancelled at the moment it receives the slot; the engine then hangs until relaunch | **High** | Confirmed path, timing-dependent trigger |
| CORE-02 | Download and hash code uses Objective-C-exception file APIs, so a full disk or I/O error crashes the process | Medium | Confirmed |
| CORE-03 | Cancellation and "retry after allocation failure" are decided by substring-matching error text | Medium | Confirmed |
| CORE-04 | Normalized clone-reference cache never hits for references that need conversion, and its telemetry says it did | Medium | Confirmed |
| CORE-05 | Voice data derived from one-off clone references (speaker embedding and codec tokens) is kept forever, backed up, and cannot be deleted | Medium (privacy) | Confirmed |
| CORE-06 | `trimMemory` and idle unload bypass the operation gate; a full unload can be undone by an in-flight load | Medium | Likely |
| CORE-07 | Shared model components (~682 MB) and `trash/` are never pruned when models are deleted | Medium | Confirmed |
| CORE-08 | The engine's own symlink overlay inside each model folder makes shared-component migrate and repair fail, which silently falls back to re-downloading | Medium | Likely |
| CORE-09 | A stray `.DS_Store` in `voice-transactions/` stops the engine from initializing (a new trigger for roadmap F-25) | Low | Confirmed |
| CORE-10 | Windows line breaks (CRLF) become paragraph breaks in long-form planning (500 ms pause instead of 80 ms) | Low | Confirmed |
| CORE-11 | Auto language detection is decided by any single CJK, kana, Hangul or Cyrillic character | Low | Confirmed |
| CORE-12 | Long-form joining can clip: segment gain is clamped to 0.75–1.25 from RMS alone, then hard-clamped to 16-bit | Low | Likely |
| CORE-13 | No cross-process lock around download staging; concurrent app and CLI installs of the same model interfere | Low | Likely |
| CORE-14 | Downloader heartbeat task and URLSession leak after an early failure; downloader instances are single-use | Low | Confirmed |
| CORE-15 | Staging WAVs and prepared-model temporary folders from crashes or jetsam kills are never swept (and are backed up on iOS) | Low | Confirmed |
| CORE-16 | Synchronous file work reachable from the main actor (reference import copies with no size cap; saved-voice listing opens every WAV) | Low | Confirmed |
| CORE-17 | Transcript sidecar import cannot work from the iOS file picker (only the audio URL gets security-scoped access) | Low | Likely |
| CORE-18 | Generation "shadow plan" check compares raw text with itself, so it cannot detect drift yet runs on every take | Low | Confirmed |
| CORE-19 | Overlong single takes fail only after spending the full 2,048-token budget | Low | Confirmed |
| CORE-20 | Dead code: `AtomicWAVGenerationOutputSink` (tests only), unused `HistoryDeletionEngine.clearAll`, 4 of 5 `QwenVoiceBackendCore` types, 332-line single-engine type eraser; ~7.9K lines of telemetry code | Info | Confirmed |
| CORE-21 | Unsalted SHA digests of prompts and transcripts in startup diagnostics can be reversed by dictionary lookup for short or common text | Info | Confirmed |
| CORE-22 | Watermark round-trip reads samples ÷32768 but writes ×32767, shifting large samples by up to 1 LSB | Info | Confirmed |

### CORE-01: Prewarm slot leak wedges the engine (High)

**Evidence.** `NativeEngineRuntime.swift:1572-1610`:
- `releasePrewarmSlot()` (`:1623-1631`) hands the slot to the first queued waiter, and resumes it normally.
- A cancelled waiter's `onCancel` handler only *spawns* `Task { await cancelPrewarmWaiter }`. If the release wins that race, the waiter resumes normally and sets `slotAcquired = true`.
- It then reaches `try Task.checkCancellation()` at `:1608`. That throws **while holding the slot**, outside the `catch` that would release it.
- Every caller registers its `defer { release }` only after a successful return (`:1431`, `:1850`, and `trimMemory` at `:438-443`).

**Impact**
- `prewarmInFlight` stays `true` with no owner. Every later Custom, Design or unprimed Clone generation and every `trimMemory` waits forever.
- The memory-pressure executor awaits that trim, so its response slot is never released. If the stuck response was critical, admission stays closed.
- `stop()` and re-`initialize()` await the stuck work, so only relaunching the app recovers.
- A plausible trigger: pressing Cancel on a generation that is queued behind a soft trim, at the moment the trim finishes.

**Recommendation**
- After acquisition, treat cancellation as "acquired, the caller will release". Delete the check at `:1608`; callers already re-check after their `defer`.
- Alternatively, release the slot before rethrowing.
- Add a deterministic race test.
- Put a time bound on the pressure executor's trim wait.

### CORE-02: The process crashes on a full disk (Medium)

**Evidence**
- These calls raise uncatchable Objective-C exceptions on failure:
  - `FileHandle.write(_:)` at `HuggingFaceDownloader.swift:1034-1040` and `:2691-2697`.
  - `readData(ofLength:)` at `HuggingFaceDownloader.swift:1287`, `SharedModelComponentStore.swift:1273`, `ModelAssets.swift:463` and `SamplingEvidence.swift:121`.
- Every file of 96 MiB or more uses the chunked path, and each weights file is 1.4–2.1 GB.
- Only iOS checks free space before downloading.

**Impact.** On a nearly full disk, the macOS app or `vocello models install` crashes instead of reporting a storage error. The sidecar keeps the download resumable.

**Recommendation**
- Use the throwing `write(contentsOf:)` and `read(upToCount:)`, which the module already uses elsewhere.
- Add a typed ENOSPC error.
- Add a free-space preflight on macOS and in the CLI.

### CORE-03: Errors are classified by text (Medium)

**Evidence**
- `NativeEngineRuntime.swift:132-144` lowercases `localizedDescription + String(reflecting: error)` and searches for "cancellationerror", "cancelled" or "canceled".
- `String(reflecting:)` of a Cocoa error includes `NSFilePath=/…`.
- `MLXTTSEngine.swift:1205-1222` and `:1276-1292` then convert the error into a silent `CancellationError`.
- `isRetryableAllocationFailure` (`:146-169`) unloads the model and regenerates whenever the text contains "memory" or "allocate" together with "mlx", "metal" or "gpu".

**Impact**
- A clone reference whose path contains "cancel" and fails to open is reported as a user cancel, so no error is shown.
- Unrelated errors trigger a full unload-and-retry.
- This contradicts ARCHITECTURE §4.2, which says cancellation is typed.

**Recommendation.** Classify by type only, using:
- `CancellationError`
- `DownloadError.cancelled`
- `AudioPreparationError.cancelled`
- `URLError.cancelled`
- the package's typed terminal outcome
- a typed allocation-failure error exposed by the package

### CORE-04 and CORE-05: The clone-reference cache misses, and derived voice data is retained (Medium)

**CORE-04: the normalized-reference cache never hits**
- Clone support names the normalized output `<stem>_<content SHA-256>.wav` (`NativeCloneSupport.swift:432-446`).
- `AudioPreparation` looks for its own path/size/mtime fingerprint in that name (`:263-272`). The two never match, so it deletes the file and converts again.
- `canReuseCachedNormalizedReference` makes the same mismatch (`:569-583`).
- The `reusedNormalizedReference` telemetry uses the other fingerprint, so it reports `true`.
- **Impact:** every MP3, M4A or 48 kHz reference is re-decoded and resampled (up to 120 s of audio) on every take.

**CORE-05: derived voice data outlives its source**
- Every clone reference without a saved-voice ID gets a persisted artifact under `voices/.qvoice_clone_prompts/<digest>/` (`NativeCloneSupport.swift:824-832`). The artifact holds the speaker embedding and codec tokens.
- Nothing lists, prunes or deletes that directory.
- The iOS storage policy backs up `voices/` recursively.
- `privacy-storage.md` does not mention these artifacts.
- **Impact:** biometric-adjacent voice data from one-off references outlives the reference and its History entry, goes into device and iCloud backups, and has no delete control. That conflicts with the product's "your voice data stays under your control" positioning.
- **Fix:**
  - Use one content fingerprint for both the name and the reuse check.
  - Keep transient artifacts in a bounded, backup-excluded `cache/`, and delete them with their source.
  - Document them in `privacy-storage.md`.

### CORE-06: Memory relief is not serialized with proactive loads (Medium)

**Evidence**
- `trimMemory` (`MLXTTSEngine.swift:1836-1859`) and idle unload (`:204-213`) neither claim the active operation nor close admission. The critical path does both.
- A `.fullUnload` can run while a prefetch, prewarm or prime is suspended inside `await modelLoader(...)`. The unload then finds nothing to reset.
- The load finishes, publishes the model, and sets `loadState` back to `.loaded`.
- iOS calls `trimMemory` directly under memory warnings (`QVoiceiOSApp.swift:319`, `TTSEngineStore.swift:420`).

**Impact.** A full unload requested under iOS memory pressure can leave a ~2 GB model resident, with a jetsam risk.

**Recommendation**
- Route hard trims, full trims and idle unload through the critical-relief admission gate.
- Make proactive work cancellable.
- Add a load epoch so a load that started before an unload cannot publish afterwards.

### CORE-07 and CORE-08: Storage lifecycle (Medium)

**CORE-07: shared components are never pruned**
- `pruneUnreferencedComponents` (`SharedModelComponentStore.swift:799-824`) has no production caller.
- The macOS, iOS and CLI delete paths remove only the model folder.
- **Impact:** the ~682 MB speech tokenizer, older component versions and `trash/` stay on disk. On iPhone that is ~0.7 GB that Delete cannot reclaim.

**CORE-08: the symlink overlay breaks migrate and repair**
- Loading a model creates `<model>/.qvoice_prepared_model/`, full of absolute symlinks (`MLXModelLoadCoordinator.swift:606-610`, `:1271-1309`).
- `hardLinkedReplica` walks hidden entries and throws `nonRegularFile` on any symlink (`SharedModelComponentStore.swift:1327-1329`).
- As a result, migrate and repair always fail once a model has been loaded. `ProductionModelCatalog.deliveryPlan` swallows the failure and silently re-downloads 1.4–2.1 GB, after first hashing the installed files.
- **Fix:**
  - Prune after each delete and at startup, and sweep `trash/`.
  - Move the overlay outside the model folder; the `hubCacheDirectory` parameter is already passed in but unused.
  - Add a migration test with a real overlay present.

### Other host-layer notes

**Previously tracked items**
- **AUD-10 is still open:** `NativeMemoryPolicyResolver.swift:62-71` sets no idle unload for `highMemoryMac`, and the pressure monitor skips that tier (`MLXTTSEngine.swift:633`).
- **AUD-08 is still open in core:** error descriptions carry absolute paths (`HuggingFaceDownloader.swift:1043`, `:1267-1277`; `AudioPreparation.swift:28-47`; `DocumentIO.swift:11-17`) into `visibleErrorMessage` and the download diagnostics (see SEC-11).
- **F-25 is still open:** `MLXTTSEngine.swift:702` has no retry; CORE-09 is another trigger.
- **F-18 is fixed in source:** publication is an atomic rename, and the destination is never used as cleanup authority.

**CORE-09 (engine init fails on a stray file)**
- `PreparedVoiceRepository.swift:125-140` throws on any plain file in the transactions directory, including Finder's `.DS_Store`.
- That throw happens inside `MLXTTSEngine.initialize`, so the engine does not start.
- **Fix:** skip hidden files and non-directories, and scope the failure to Saved Voices.

**CORE-10, CORE-11 (text handling)**
- `SpokenTextPlanning.swift:386-405` counts newlines per grapheme, so a CRLF pair counts as a paragraph break.
- `GenerationSemantics.swift:1150-1176` switches the whole take's language when it finds a single script character. For example, English text mentioning "東京" is sent as Chinese.
- **Fix:** use script proportions, or run `NLLanguageRecognizer` first.

**CORE-12 (long-form clipping)**
- Segments are limited to 0.965 of full scale (`GenerationOutputAdapter.swift:951`). A gain above about 1.036 on a near-ceiling segment therefore clips (`LongFormAssembly.swift:418-428`, `:498-506`).
- **Fix:** cap the gain at ceiling ÷ peak.

---

## 7. macOS app and shared UI

**Scope:** 131 files and 27.8K lines: `Sources/Views`, `ViewModels`, `Services`, `Models` and `SharedSupport`, plus 16 iOS files compiled into the Mac target by path.

**Verdict:** The generation lifecycle is disciplined:
- Generate is protected against double submission in three places.
- Stale attempts are rejected, and playback is scoped to the operation that started it.
- The History outbox is idempotent.
- Accessibility foundations are real: every icon button has a label, state is never shown by colour alone, and Reduce Transparency and Reduce Motion are honoured.
- The string catalog has 948 keys, complete in all 10 locales.

The findings fall into four groups:
1. A severe launch-performance defect (MAC-01).
2. Controls that don't do what they say (MAC-02, MAC-04, MAC-12).
3. A data-loss edge case (MAC-03).
4. User-visible English and raw error text that the localization contract can't see (MAC-06 to MAC-11).

| ID | Finding | Severity | Confidence |
|---|---|---|---|
| MAC-01 | Every launch SHA-256 hashes all installed model weights (GBs) **on the main thread**, before the window appears; downloads end in the same freeze | **High** | Confirmed path (duration not measured) |
| MAC-02 | Settings → "Prefer lower-memory models" has no effect on generation | Medium | Confirmed |
| MAC-03 | "Save As" onto the take's own file deletes the original; the Studio card discards the failure | Medium | Confirmed |
| MAC-04 | The Retry button on the engine-bootstrap failure screen never retries the bootstrap (macOS counterpart of AUD-01) | Medium | Confirmed |
| MAC-05 | Closing the main window loses all Studio drafts and coordinators; a running take can no longer be cancelled | Medium | Likely |
| MAC-06 | Language names, quality warnings, delivery advisories and preset names stay in English in all ten interface languages | Medium | Confirmed |
| MAC-07 | Errors reach the UI as raw English `localizedDescription`, including absolute paths and internal identifiers | Medium | Confirmed |
| MAC-08 | The script, voice-brief and batch editors have no accessibility label; their placeholder is invisible to VoiceOver | Medium | Confirmed |
| MAC-09 | OGG and WebM are advertised as import formats but probably can't be decoded; the import panel accepts any audio type; saved voices store FLAC/AIF/CAF bytes under a `.wav` name | Medium | Likely (OGG/WebM), Confirmed (rest) |
| MAC-10 | Some shared surfaces ignore the in-app language; dates and sizes follow the system locale | Low | Confirmed |
| MAC-11 | The microphone and speech permission prompts are English only (no macOS InfoPlist catalog); no plural forms in any of the 457 `vocello.mac.*` keys | Low | Confirmed |
| MAC-12 | Cancel during a saved-voice save still saves the voice | Low | Confirmed |
| MAC-13 | A deleted saved voice stays loaded and playable, and ⇧⌘R still reveals its path | Low | Confirmed |
| MAC-14 | Recording a reference doesn't pause app playback, so the take playing on the speakers is recorded into the reference | Low | Confirmed |
| MAC-15 | "Open Output Folder" and the recovery "Reveal" ignore the custom output folder | Low | Confirmed |
| MAC-16 | Output file names can contain newlines or tabs; the timestamp depends on the locale and calendar (Buddhist and Japanese calendars give different years) | Low | Confirmed |
| MAC-17 | The waveform can come from the wrong file after quick switching; each waveform reads the whole file into memory (~345 MB for a one-hour WAV) and fails on stereo | Low | Confirmed |
| MAC-18 | Live preview goes silent when the audio device changes (no `AVAudioEngineConfigurationChange` handling) | Low | Likely |
| MAC-19 | Cancelling and restarting recommended setup quickly cancels the new downloads | Low | Confirmed |
| MAC-20 | Deleting a model isn't coordinated with the engine: no active-generation guard, and no unload | Low | Confirmed |
| MAC-21 | Speech transcription keeps running after its task is cancelled; abandoned passes pile up | Low | Confirmed |
| MAC-22 | Every keystroke and every download-progress tick (10 Hz) re-renders the root view; language detection runs on the main actor over the whole script (~0.1 s per call measured) | Low | Likely |
| MAC-23 | Keyboard gaps: no shortcut cancels a generation; ⌘. stops playback, not generation; no ⌘F for History; the ⌘6 item is labelled "Models" but opens Settings | Low | Confirmed |
| MAC-24 | "Clear" wipes the script with no confirmation and no undo | Low | Likely |
| MAC-25 | Recorded clips are never deleted from `tmp/voice-enroll/`, although `privacy-storage.md:54` says they are | Low | Confirmed |
| MAC-26 | Dynamic Type / Larger Text (a PRODUCT.md commitment) isn't implemented on macOS: `MacType` uses `Font.system(size:)`, so `relativeTo:` does nothing | Low | Confirmed |

### MAC-01: Launch-time model hashing on the main thread (High)

**Evidence**
- `QwenVoiceApp.swift:15` creates `@State private var modelManager = ModelManagerViewModel()` while the App is being initialized.
- The class is `@MainActor` (`ModelManagerViewModel.swift:6`). Its `init` loops over every macOS package and calls `localModelInfo(for:)` (`:167-171`).
- For every complete install, `localModelInfo` calls `LocalModelAssetStore.deepIntegrity` (`:969`). That calls `IntegrityHashCache.cachedSHA256`, which streams and hashes the whole file (`ModelAssets.swift:376-386`, `:510-536`).
- The cache lives only as long as the process, so every cold launch hashes everything again. The code's own comment says it exists to avoid "re-hashing multi-GB model files".
- The asynchronous `performRefresh()` (`:856-862`) shows off-main verification was intended; `init` bypasses it.
- After a download, the new package is hashed on the main actor (`:725-727`).

**Impact**
- With the recommended three packages installed, each launch reads and hashes 6–8.5 GB, or about 14.6 GB with all six. The Dock icon bounces with no window for several seconds, and longer after a reboot when the files are not in the page cache.
- Every download or repair ends with a main-thread freeze.
- None of the UI-perf lanes measure launch, so this is invisible to the project's own benchmarks.

**Recommendation**
- Make `init` check file presence and size only.
- Persist install-time trust keyed by (inode, size, mtime) and the receipt digest.
- Deep-hash only on explicit Verify/Repair, or when those values change, and always off the main actor.
- Add a launch signpost to the macOS perf lane.

### MAC-02: The lower-memory setting is ignored (Medium)

**Evidence**
- The toggle (`MacSettingsScreen.swift:270-276`) only writes `QwenVoice.PreferSpeedEverywhere`. Its copy promises it "Pins every generation mode to the Speed package".
- The only reader of that key is `TTSContract.activeModel` (`TTSContract.swift:213`), reached through `TTSModel.model(for:)`. On macOS that is used only by the unused `SidebarItem.requiredModel`.
- Studio screens resolve models through `ModelManagerViewModel.generationActiveVariant` → `activeVariant(for:)` (`:226-276`), which reads only the per-mode preference.

**Impact.** A user on an 8 or 16 GB Mac enables the setting to avoid memory pressure, and still generates with Quality.

**Recommendation.** Honour the key in `activeVariant(for:)` and in the variant chip, or remove the toggle. Add a unit test.

### MAC-03: Save As can destroy the original take (Medium)

**Evidence**
- `MacHistoryFileActions.swift:12-34` suggests the source's file name in the last-used folder.
- After the Replace prompt it runs `removeItem(at: url)` and then `copyItem(at: source, to: url)`, without checking that `url` is not the source itself.
- The Studio card ignores the result (`MacStudioPlayerCard.swift:225`).

**Impact.** Takes can live in a user-visible custom output folder. Saving into that folder under the same name and confirming Replace deletes the History WAV. The copy then fails and History points at a missing file. From the Studio card, all of this is silent.

**Recommendation**
- Compare the standardized paths and file resource identifiers, and do nothing if they match.
- Copy to a temporary file, then use `replaceItemAt`.
- Surface failures on the Studio card.

### MAC-04 and MAC-05: Recovery and window lifecycle (Medium)

**MAC-04: Retry doesn't retry**
- `engineBootstrapDiagnostics` is set once and never cleared (`QwenVoiceApp.swift:23-35`, `:126-130`).
- Retry re-runs only `AppLaunchPreflight.run()`, which re-reads a `static let` (`TTSContract.swift:96`).
- **Fix:** re-run `MacEngineBootstrap.makeEngineStore()`, or replace the button with honest actions: Quit and Copy diagnostics.

**MAC-05: closing the window loses the session**
- Drafts, `MacAppModel` and the coordinators are `@State` of `ContentView` inside a `WindowGroup`.
- Pressing ⌘W and then clicking the Dock icon loses the script, brief, reference, transcript and pinned seeds.
- If a take is running, the new window shows "Generating…" with no Cancel button.
- The tab bar's "+" can open a second shell with its own coordinators.
- **Fix:** hoist that state to App level, or use a single `Window` scene. Confirm before closing during a generation.

### MAC-06 and MAC-07: English and raw error text leak through the localization system (Medium)

These strings bypass the catalog, so the literal-string baseline, which has 0 macOS entries, cannot see them. The iOS app already uses catalog keys for the same concepts.

**Computed English strings from QwenVoiceCore:**
- Speech-language names (`Qwen3SupportedLanguage.displayName`), shown in the language chip, its 11 menu rows and the reference-language picker.
- `PreparedVoiceQualityWarning.headline` and `summary`.
- `DeliveryInstructionAdvisor.advisoryMessage`.
- `EmotionPreset.label`.
- The default names `"\(voice) Sample"` and `"Designed_Voice"`.

**Raw `error.localizedDescription` in the UI (15+ sites):**
- `coordinator.fail(error.localizedDescription)` in all three Studio screens and in the batch runner.
- `AudioPreparationError` shows "Couldn't read audio file at \(path)", which leaks home-directory paths into screenshots.
- History errors tell users to "use recovery or export tools", but the card only offers Retry.
- The status strip picks its title by testing whether the English message contains "unavailable" (`MacStatusStrip.swift:54`).

This violates PRODUCT.md: errors should describe cause and fix, and should never mention "the system".

**Fix**
- Add one mapper from typed errors to catalog keys, with no paths in the text. Keep the raw detail for "Copy diagnostics".
- Extend `localization_contract.py` to flag QwenVoiceCore display strings used in views.

### MAC-08 and MAC-09 (Medium)

**MAC-08: the main text editors are unnamed for VoiceOver**
- `MacScriptTextEditor.swift:56-58` sets only an identifier. The placeholder is drawn in `draw(_:)`, so VoiceOver never sees it.
- The product's main input is therefore announced as an unnamed "text, edit text". That breaks WCAG 4.1.2 and 3.3.2, and PRODUCT.md's labelling commitment.
- **Fix:** call `setAccessibilityLabel` and `setAccessibilityPlaceholderValue`.

**MAC-09: import formats are over-advertised and not normalized**
- `VoiceCloningReferenceAudioSupport.swift:8-10` and the README both advertise OGG and WebM.
- Preparation requires `AVAudioFile(forReading:)` to succeed first (`AudioPreparation.swift:294-299`). AudioToolbox has no Ogg or WebM container support, so those imports most likely fail with "Couldn't read audio file". No test covers either format.
- The Browse panel accepts any `public.audio` type (`MacVoiceCloningScreen.swift:763-770`); only drag-and-drop checks extensions.
- Saved-voice enrollment copies unrecognized formats byte for byte to `reference.wav` (`PreparedVoiceRepository.swift:203-204`).
- **Fix:**
  - Hand-test `.ogg` and `.webm` imports.
  - Then either drop those formats from the lists or decode them through `AVAssetReader`.
  - Filter the panel to the allowed set.
  - Normalize every import to canonical WAV.

### AUD items on macOS, checked against current code

| Item | Status | Current evidence |
|---|---|---|
| **AUD-03** | Open, low risk | Views still build the generation `Task` (`MacCustomVoiceScreen.swift:348`, `MacVoiceDesignScreen.swift:388`, `MacVoiceCloningScreen.swift:964`). The coordinator still rejects stale attempts, so there is no race. |
| **AUD-05** | Open | `DatabaseService.swift:142-151` reads through `dbQueue.write`. The reconcile does filesystem work inside the transaction. History loads and stats the whole archive on every appearance. **Correction to the earlier review:** the macOS delete path does surface audio-cleanup failures. The silent `try?` unlink is iOS-only. |
| **AUD-09** | Open | `VocelloMacSmokeUITests.swift:262` still requires a saved clone voice that only the benchmark preflight ensures. |
| **AUD-10** | Open, and wider than recorded | Besides "no idle unload on the high-memory tier", switching Studio mode triggers an unload and load of a 2–2.8 GB package after 900 ms (`MacGenerationWarmupCoordinator.swift:261-281`). Each 800 ms typing pause in a Design brief starts a GPU readiness prefetch (`ContentView.swift:376-383`). |
| **AUD-04** | Same gap on macOS | `MacVoiceCloningScreen.swift:97-105`: `canGenerate` ignores `cloneContextStatus`. |

**macOS metrics**

| Measure | Value |
|---|---|
| `try?` | 74 |
| `try!` | 0 |
| `as!` | 0 |
| `.localizedDescription` | 35 (15+ reach the UI) |
| Task-creation sites | 68 |
| Files over 800 lines | 8 (`MacInterfaceText` 1,968; `AudioPlayerViewModel` 1,685; `ModelManagerViewModel` 1,249; `VoiceClipTranscriber` 1,115; `MacVoiceCloningScreen` 1,030) |
| Byte-identical duplicate source files | 1 (`WaveformService.swift` in both `Sources/Services` and `Sources/iOSSupport/Services`) |

---

## 8. iOS app and commerce

**Scope:** `Sources/iOS` (60 files, 27.6K lines) and `Sources/iOSSupport` (39 files, 4.6K lines), plus the iOS target configuration, `Info.plist`, entitlements and privacy manifest.

**Verdict:** The commerce implementation is exemplary:
- It has one StoreKit owner.
- Only verified, non-revoked purchases of the matching product unlock export.
- Revision guards stop a stale snapshot from undoing a refund.
- There is no "paid" flag in UserDefaults.
- Every outward route (player sheet, History, inline card, saved-outputs folder copy) goes through a single `IOSExportGate`, which decides by the output's recorded mode.
- Unknown modes fail closed.

**I found no in-app bypass of the Design & Clone export paywall.** The one latent route requires editing the app's preferences (IOS-16).

The weaknesses are **app lifecycle, audio-session ownership, recoverability and accessibility**. The biggest is what happens when the app goes to the background during generation.

| ID | Finding | Severity | Confidence |
|---|---|---|---|
| IOS-01 | Backgrounding during generation is unhandled. Home, a call or Auto-Lock mid-take (or mid-long-form project) likely ends in a GPU error that terminates the process | **High** | Likely (path Confirmed) |
| IOS-02 | A "background" release deferred during a take later runs in the foreground, unloading the model right after a good take | Medium | Confirmed |
| IOS-03 | The audio session is activated at launch and on every foreground, which stops Music or Podcasts; it is re-categorized under an active recording | Medium | Confirmed path / Likely effect |
| IOS-04 | Several audio players never coordinate: playback overlaps, and closing the player sheet silently kills the Studio preview | Medium | Confirmed path / Likely effect |
| IOS-05 | One malformed saved-voice transaction disables every generation mode on every launch, with only a dismissible English toast | Medium | Confirmed |
| IOS-06 | The storage-protection pass walks the whole App Group on the main thread at every launch; any single failure bricks startup (AUD-01) | Medium | Confirmed |
| IOS-07 | A failed Saved Voices load looks exactly like an empty library | Medium | Confirmed |
| IOS-08 | Model downloads are Wi-Fi-only (`allowsCellularAccess = false`), but the UI only says "Waiting for Network" | Medium | Confirmed |
| IOS-09 | Studio drafts (up to 30,000 characters) live only in memory and are lost when iOS terminates the backgrounded app | Medium | Confirmed |
| IOS-10 | "Clear History (Keep Audio Files)" leaves private audio that is unreachable on iOS but still backed up to iCloud | Medium | Confirmed |
| IOS-11 | SQLite and file locks held in the App Group container risk 0xdead10cc terminations on suspension (no background task, no GRDB suspension handling) | Medium | Likely |
| IOS-12 | VoiceOver never announces results or errors (0 accessibility notifications); banners with action buttons auto-dismiss after 4–6 s (WCAG 2.2.1) | Medium | Confirmed |
| IOS-13 | ~19 text views use fixed font sizes, including the inline player, the confirm and delete sheets and the brief editor (WCAG 1.4.4) | Medium | Confirmed |
| IOS-14 | User-visible strings bypass `IOSAppLanguage`: engine toasts, long-form labels, default voice names, download and import errors, and invented "Hi, I'm …" player transcripts | Low (Medium for the 10-language release) | Confirmed |
| IOS-15 | ~2,900 lines of device-diagnostics code ship live, read raw environment variables outside the compile gate, and link CallKit | Low | Confirmed |
| IOS-16 | Latent export route: iOS `AudioService` still honours the macOS output-folder preference, and Documents is Files-visible | Low | Confirmed (requires tampering) |
| IOS-17 | Microphone permission text says "Recordings stay on this iPhone", but `voices/` is included in iCloud backup | Low | Confirmed |
| IOS-18 | The Clone request is assembled *after* the priming `await`, so edits made during priming change the take | Low | Confirmed |
| IOS-19 | Purchase-state callers can act on a stale value after their refresh is superseded (contradictory notices; brief purchase sheet for owners) | Low | Confirmed logic |
| IOS-20 | Free space is checked only when an install starts; an unreadable or newer-schema download ledger blocks all installs permanently | Low | Confirmed |
| IOS-21 | Save Voice has no in-flight guard; a double tap shows a "save failed" alert after a successful save | Low | Confirmed |
| IOS-22 | The app-switcher privacy cover doesn't cover presented sheets (transcripts appear in the snapshot) | Low | Confirmed |
| IOS-23 | `Info.plist` claims to open any `public.audio` file, but import accepts only WAV, MP3, AIFF and M4A; the copy runs on the main thread with no size limit | Low | Confirmed |
| IOS-24 | A corrupt History database leaves all saved audio unreachable (the error promises "recovery or export tools" that don't exist on iOS) | Low | Confirmed |
| IOS-25 | Return in the Studio editor always dismisses the keyboard, so paragraphs can't be typed; the inline card's Save and Download do the same thing; saved-outputs folder failures are silent | Low | Confirmed |

### IOS-01: No background policy for active generation (High)

**Evidence**
- `QVoiceiOSApp.swift:167-172`: on `.background` the app deactivates audio and calls `releaseRuntime(reason: "background")`.
- `RuntimeReleaseCoordinator.requestRelease` defers the release when a generation is active, so the generation keeps running in the background.
- Nothing requests background execution time:
  - `beginBackgroundTask` appears only in `IOSDeviceDiagnosticsRunner.swift`.
  - `isIdleTimerDisabled` is never set during a real generation.
- MLX work is never wrapped in `withError`. In mlx-swift 0.31.6 an unhandled MLX error ends the process.
- iOS rejects Metal work submitted from a backgrounded app.
- The project's own device tooling calls backgrounding "run-dooming" (`IOSInterruptionRecorder.swift:5-7`), and device lanes require Auto-Lock set to Never.

**Impact**
- Pressing Home, taking a call, or Auto-Lock firing while a long take streams probably terminates the app.
- Long-form projects (up to 100 segments) run for minutes without touches, so Auto-Lock will almost certainly interrupt them.
- Between segments, the model is unloaded and then reloaded in the background.

**Recommendation**
- On resign-active or background, cancel through the engine's typed cancellation barrier inside a `beginBackgroundTask` window, or stop at the next segment boundary.
- Disable the idle timer while generating.
- Wrap evaluation in `withError`.
- Evaluate `BGContinuedProcessingTask` with GPU access for long-form work.
- Add Home, lock and return cases to the consented device lane.

### IOS-02 to IOS-04: Lifecycle and audio-session ownership (Medium)

These three widen AUD-02 (one audio-session owner). There are now **20 `setCategory`/`setActive` sites in 6 files**.
- **IOS-02:** the `.active` handler never clears `pendingReason`. When the take ends, `performRuntimeRelease` unloads the model and aborts the live preview while the user is reviewing the result (`QVoiceiOSApp.swift:89-93`, `:343-374`).
- **IOS-03:** `configureAudioSession` activates a non-mixable `.playback` session in `App.init` and on every `.active` (`:30`, `:159`, `:180-188`). That interrupts other apps' audio even though nothing is playing. If the app goes inactive mid-recording (Control Center), the category flips under `AVAudioRecorder`.
- **IOS-04:** expanding an autoplaying take opens `IOSPlayerSheet`, which always calls `play()` (`:801-833`), while the shared player keeps playing. Closing the sheet deactivates the shared session (`:718-724`) without updating the shared player's state. `IOSVoicePreviewPlayer` leaves `.mixWithOthers` set globally.

**Recommendation:** one playback coordinator that owns the session category and activation, pauses other players, and is the only code allowed to deactivate the session. Activate only when playback or recording actually starts.

### IOS-05 to IOS-07: Startup and store recoverability (Medium)

These extend AUD-01, which is still open: a terminal startup screen with no retry.
- **IOS-05:** `MLXTTSEngine.initialize` awaits `preparedVoiceRepository.reconcile()`. That throws on a malformed transaction and keeps the bad files for diagnosis. The engine is then never ready, so Built-in and Design are disabled too, on every launch. The only signal is a toast that auto-dismisses.
- **IOS-06:** `IOSAppBootstrap.swift:18` runs `try IOSStorageProtectionPolicy.apply(...)` synchronously on the main actor. It recursively sets attributes on every model file, output, voice and outbox file (`IOSStorageProtectionPolicy.swift:41-138`). Launch time grows with the library, and a single failure is a fatal startup error.
- **IOS-07:** `SavedVoicesViewModel.loadError` is set but never displayed on iOS.

**Recommendation**
- Keep saved-voice store failures from blocking the engine: quarantine the bad transaction and scope the error to Saved Voices.
- Make bootstrap retryable.
- Run storage protection once per schema version, off the main thread, at directory level only, with per-file failures logged and not fatal.

### IOS-08 to IOS-11: Data and connectivity expectations (Medium)

- **IOS-08:** background downloads set `allowsCellularAccess = false` (`IOSModelDownloadCoordinator.swift:606`). The only status shown is "Waiting for Network", and the string catalog contains no Wi-Fi wording. A first-time user on cellular sees a multi-GB install stall forever.
- **IOS-09:** there is no `SceneStorage` and no draft persistence. Termination in the background is routine for an app using several GB of memory.
- **IOS-10:** outputs live in the App Group container, which neither the app's UI nor Files can reach after the History rows are cleared. They are still included in iCloud backup (`IOSStorageProtectionPolicy.swift:33`). This option came over from macOS, where Finder makes it meaningful.
- **IOS-11:** the History SQLite database and two blocking file locks (model publication and the saved-voice store) live in the App Group. There is no GRDB `observesSuspensionNotifications` and no background task, which is Apple's documented cause of 0xdead10cc kills.

### IOS-12 and IOS-13: Accessibility (Medium)

- **IOS-12:** 0 `AccessibilityNotification` posts anywhere in the iOS app or SharedSupport, so a finished or failed take is silent for VoiceOver users. The "Saved voice, Use in Clone" banner contains a button and disappears after 6 s.
- **IOS-13:** fixed `.system(size:)` fonts on the inline player, the Confirm and Delete sheets and both text editors (`IOSStudioInlinePlayerCard.swift:233,367,374,501,570`; `IOSBottomSheets.swift:139,403,1430-1484`). The inline card also has a fixed height of 127 pt. ISU-5 does not cover these.
- **AUD-06 is still open:** there are 0 uses of `accessibilityHidden` for the background, `.isModal` or `accessibilityAction(.escape)`.

**Status of prior iOS items:** AUD-01, 02, 04, 05, 06, 07 and 12 are all still present in current code. AUD-07 is present by design and has no security defect. Section 13 has the details.

**iOS metrics:**
- 138 `try?`, 77 of them outside the diagnostics runners. 0 `try!`.
- About 88 unstructured `Task`s.
- 155 accessibility identifiers and 52 accessibility labels.
- 0 Now Playing or remote-command integrations.
- Largest files: `IOSDeviceDiagnosticsRunner` 2,907 lines, `IOSGenerationModeViews` 2,129, `IOSBottomSheets` 1,499, `IOSModelDownloadCoordinator` 1,408.

---

## 9. Security, privacy and compliance

**Verdict:** The product's runtime trust boundary is among the best-engineered parts of the repository:
- Every model artifact is pinned to a 40-hex commit, a per-file SHA-256 and a size.
- Downloads are restricted to an exact HTTPS host and `/<repo>/resolve/<rev>` path allowlist, with no credentials, ports or queries.
- Path components are validated and prefix-checked.
- Staging is symlink-resistant, locks use `O_NOFOLLOW`, and publication is atomic via `RENAME_SWAP`.
- SQL is parameterized.
- Speech recognition is forced on-device.
- The watermark off-switch is properly compile-gated.
- All 73 environment knobs are registered.
- 48 of 48 third-party GitHub Actions are pinned to full SHAs that match `config/toolchain.json`.
- There are no `pull_request_target` or `workflow_run` triggers and no self-hosted runners.
- The tracked tree and the 50-commit shallow history contain no secrets, UDIDs, team IDs or developer home paths.
- Benchmark records are privacy-clean.
- `npm audit` reports 0 vulnerabilities.

The weak points are **GitHub-side release authority** and several **compliance statements that shipped behaviour contradicts**.

| ID | Finding | Severity | Confidence |
|---|---|---|---|
| SEC-01 | Signing and App Store Connect secrets are plain repository secrets with no Environment protection; dispatch from any ref runs that ref's (editable) release workflow | **High** | Confirmed (GitHub-side settings not visible) |
| SEC-02 | Signing jobs run third-party build and test code with an unlocked Developer ID keychain (`security import -A`), a notary key on disk, and a prefix-keyed Actions cache restore | Medium | Likely |
| SEC-03 | A voice-cloning marketing clip of an unidentified speaker is live on the website, contrary to the project's own fail-closed rights review | Medium | Confirmed in source |
| SEC-04 | Clone consent is enforced only in SwiftUI views; the CLI clones and enrolls with no acknowledgement (issue #101, open since Sep 8) | Medium | Confirmed |
| SEC-05 | The Mac app keeps two hardened-runtime exceptions that the notarized CLI (same MLX stack) runs without; one of the two builds is misconfigured | Medium | Inconsistency Confirmed |
| SEC-06 | Three owned-runtime inference knobs (`QVOICE_TALKER_KV_QUANT`, `QWENVOICE_TOKENIZER_RESIDENCY`, `QWENVOICE_SAMPLER_COMPILE`) need only `QWENVOICE_DEBUG=1` in distributed builds, bypassing the internal-diagnostics compile gate | Low | Confirmed |
| SEC-07 | Script injection through `${{ inputs.output_name }}` in `release.yml:377-378,388` | Low | Confirmed |
| SEC-08 | The iOS background URLSession never enforces the redirect host allowlist, although the docs say it does | Low | Confirmed |
| SEC-09 | The shipped CLI can load its trust anchors (catalog, contract) from the working directory or any parent folder, then install into the store the app shares | Low | Confirmed |
| SEC-10 | AudioSeal (Meta) code and weights ship without attribution; the recorded upstream revision `cc2700db` is actually the UTMOSv2 commit | Low | Likely |
| SEC-11 | Download diagnostics are always on and redact paths only under `/Users`, `/private`, `/var` and `/tmp`; the secret scanner misses `hf_`, `github_pat_` and `npm_` tokens and `ENCRYPTED PRIVATE KEY` | Low | Confirmed |
| SEC-12 | Unused public download APIs in owned code fetch `revision: "main"`, skip digest checks, and log "catalog-authorized" | Low | Confirmed |
| SEC-13 | `PrivacyInfo.xcprivacy` lacks reason `3B52.1` for timestamps of user-selected files | Low | Confirmed |
| SEC-14 | The public privacy policy (July 28) omits StoreKit processing, the output watermark and provenance chunk, and Hugging Face request metadata (ASR-02) | Low | Confirmed |
| SEC-15 | The website sets no security headers (no `vercel.json`, no CSP or `frame-ancestors`) | Low | Confirmed |
| SEC-16 | Downloads have no in-flight size bound, so a misbehaving CDN can fill the disk before verification | Info | Confirmed |
| SEC-17 | Hygiene: Python deps pinned by version, not hash; `npm audit --audit-level=high` ignores moderates; `persist-credentials` is left on for 19 of 19 checkouts; every commit's author name is the literal string `user.email` | Info | Confirmed |

### SEC-01: Release authority lives in a workflow file anyone who can dispatch it can replace (High)

**Evidence**
- No workflow uses `environment:`.
- The `package` and `archive-ios` jobs read 13 repository secrets:
  - the Developer ID `.p12` and its password;
  - the notary `.p8`;
  - the iOS distribution certificate and provisioning profile;
  - the App Store Connect API key.
- `release.yml` also allows `workflow_dispatch` with a free-text `tag` input.
- For a dispatch, GitHub runs the workflow file **from the dispatching ref**. The signed-tag, in-`main` and exact-SHA CI checks that SECURITY.md presents as release authority are steps *inside that same file*.
- `release_source_authority.py:131-137` accepts any GitHub-verified tag signature, without pinning the signer.

**Impact.** Anyone with push and dispatch rights can push a branch with an edited `release.yml` that points `inputs.tag` at a genuine signed tag and deletes the checks. That includes a leaked PAT with `workflow` scope and a hijacked session. The edited job then holds the maintainer's Developer ID and App Store keys: it can exfiltrate them, or sign and notarize arbitrary binaries under the maintainer's Team ID.

Likelihood is low for a single-maintainer repository. The impact (code-signing identity compromise) is severe, and the fix is cheap.

**Recommendation**
1. Move all signing and App Store Connect secrets into a `release` Environment limited to `refs/tags/v*`, with a required reviewer (or a wait timer), and delete the repository-level copies.
2. Require dispatch *from* the tag ref: `if: startsWith(github.ref, 'refs/tags/v')`, and drop `inputs.tag`.
3. Pin the tag signer's key in `config/`.
4. Protect `v*` tag creation with a ruleset.

### SEC-02: Signing is not isolated from code execution (Medium)

**Evidence**
- `release.yml:296-306` imports the Developer ID identity with `-A` (any application may use the key). `set-key-partition-list` narrows this partly.
- The keychain stays unlocked for 6 hours. The notary `.p8` is written to disk (`:321-350`).
- The job then restores `actions/cache` for SwiftPM checkouts with a broad prefix `restore-keys` (`:357-364`).
- After that it runs `release.sh`, which first executes the whole release-readiness test suite and compiles every dependency from the restored cache.
- `archive-ios` repeats the cache pattern.
- No checkout sets `persist-credentials: false`.

**Impact.** Code running in any main-branch job can poison a cache entry that a later tag build restores, using publicly documented cache-token techniques. The poisoned dependency would then be compiled into a Developer ID-signed, notarized DMG. The same code could use the unlocked identity directly or read the notary key.

**Recommendation**
- Split the pipeline into:
  - a secrets-free build/test job that uploads unsigned artifacts;
  - a minimal, environment-protected sign/notarize job that runs only pinned Apple tools and never restores caches.
- Import with `-T /usr/bin/codesign`, as the iOS job already does.

### SEC-03 and SEC-04: Consent and content rights (Medium)

**SEC-03: the voice-cloning marketing clip**
- `docs/reference/content-rights-review.md:45` says of the voice-cloning marketing sample: "**Fail-closed pending** … Remove the sample until that record exists."
- `website/src/data/samples.js:38-47` still ships it: `mode: "Voice Cloning"`, "Cloned from a 12-second narration clip". The asset is committed (311 KB) and rendered by `Listen.jsx`.
- **Why it matters:** a voice-cloning product is marketing with a cloned voice whose consent is undocumented. That is the exact reputational risk the review was written to prevent.
- **Fix:** remove the entry, the WAV and the prerendered output, or replace it with a consenting voice. Add a `site-contract.mjs` rule that rejects Voice Cloning samples without a consent-decision ID.

**SEC-04: consent is a UI-only control**
- The flag lives in `@AppStorage("vocello.voiceCloningConsent.v1")` and is checked only in `MacVoiceCloningScreen.generate()` (`:908`) and `IOSGenerationModeViews.swift:1884`.
- There are 0 references in QwenVoiceCore or VocelloCLI.
- `vocello clone --reference` and `vocello voices enroll` need no acknowledgement.
- No test asserts refusal without consent (TEST-04).
- The CLI is not yet distributed. It will be, via the planned 3.0 CLI DMG, so fix this before that ships.
- **Fix:** move the decision into a core policy used by every entry point: the app coordinators, line batch, long-form, regenerate-segment, CLI clone and CLI enroll. For the CLI, use a persisted acknowledgement or a `--confirm-consent` flag. Unit-test the refusal.

### SEC-05: Hardened-runtime exceptions are inconsistent (Medium)

- `Sources/QwenVoice.entitlements` sets `cs.allow-unsigned-executable-memory` and `cs.disable-library-validation` (with the sandbox off), justified as "MLX JIT".
- The notarized CLI links the same MLX stack but is signed `--options runtime` with **no entitlements** (`scripts/release.sh:378`).
- Packaged-CLI generation has never been qualified (RF-10 is parked).
- So one of two things is true:
  - The app's exceptions are unnecessary. That leaves an unsandboxed app holding Microphone and Speech TCC grants open to library injection.
  - The exceptions are necessary, and the shipped CLI will fail the first time it generates.
- **Fix:** run `cli_package.py qualify` on the signed CLI. If it passes, remove both exceptions from the app. If it fails, give the CLI a minimal entitlement role (prefer `allow-jit`).

### Lower-severity items

**SEC-06 (debug knobs bypass the compile gate)**
- The package gate `VocelloQwen3ImplementationDebugGate` (`Packages/…/RuntimeDebugGate.swift:6-18`) checks only `QWENVOICE_DEBUG`.
- `runtime-debug-knobs.json` classes these knobs as unavailable without the internal capability.
- `runtime_security_contract.py:189-193` whitelists this gate.
- Knob provenance is recorded only when the capability is present, so distributed builds can run with altered inference and leave no trace in telemetry.
- The same pattern affects `QVOICE_IOS_DEVICE_RUN_ID` and several iOS diagnostics keys (IOS-15).
- **Fix:** resolve these knobs in the host and inject them.

**SEC-08 (iOS background redirects)**
- `willPerformHTTPRedirection` is never called for background sessions.
- Enforce the allowlist on `response.url` at completion, and when resuming from resume data.
- Byte integrity still holds through SHA-256.

**SEC-09 (CLI trust anchors)**
- `CLIRuntime.swift:86-137` falls back to `cwd/Sources/Resources/...` and `findUpwards`.
- In distributed builds, accept only the sealed catalog next to the executable, verified against a build-time digest.

**SEC-10 (AudioSeal attribution)**
- The origin line says MIT for code and weights. Meta's notice is absent from `third_party_attributions.json`, `NOTICES.md` and `ORIGINS.md`.
- `cc2700db…` is the UTMOSv2 pin in `scripts/mos_advisory.py:47`, so the recorded AudioSeal revision is almost certainly a copy error.
- Add the attribution, fix the revision, and include this in the ASR-04 counsel packet.

**SEC-11 (diagnostics and scanner)**
- Record typed error codes in `ModelDownloadDiagnosticsStore` instead of sanitized free text.
- Add the missing token patterns to `privacy_scan.py`.
- The AUD-08 `print(error.localizedDescription)` sites remain (`GenerationTelemetryMerger.swift:96-129`).

**SEC-13, SEC-14 (privacy manifest and policy)**
- Add `3B52.1` to the manifest.
- Update `website/public/privacy/` for StoreKit, the watermark and provenance chunk, and Hugging Face request metadata, then close ASR-02.
- Reword the iOS microphone text (IOS-17).

**SEC-15 (website headers)** Add `website/vercel.json` with:
- CSP (`default-src 'self'`, `frame-ancestors 'none'`);
- `X-Content-Type-Options: nosniff`;
- `Referrer-Policy`;
- `Permissions-Policy`;
- long-lived caching for the hashed assets.

---

## 10. Build, CI/CD and release engineering

**Verdict:** The supply-chain and release-integrity design is strong:
- Every action and tool binary is SHA-pinned or SHA-verified.
- Permissions are least-privilege, and every job has a timeout.
- Releases require a signed tag plus exact-SHA CI.
- Releases publish SBOMs, attestations and `SHA256SUMS`.
- Uploaded assets are re-downloaded and verified.
- A typical green CI run takes 6.2 minutes.

The paths that run only rarely are unreliable. **The release workflow very likely fails on the next tag**, and it last ran on Aug 1. Two scheduled workflows have **never** done their job. With no pre-merge lane, `main` was red on 12 of the last 100 pushes.

**Live GitHub observations** (from the Actions API, Sep 22):

| Workflow | Recent record |
|---|---|
| CI | 661 runs; last 100 pushes: 80 green, 12 red, 8 cancelled; longest red streak 9 runs; median green 6.2 min |
| Nightly | 12 runs: 11 green, 1 red. The failure-reporting job also failed, so no issue was filed |
| Swift dependency watch | **4 of 4 runs failed** (HTTP 403 reading Dependabot alerts) |
| Release | 28 runs in total; **last run 2026-08-01** (v2.4.0) |
| Dependabot PRs | 5 open, oldest #96 from Aug 10; none has ever received a CI check |

| ID | Finding | Severity | Confidence |
|---|---|---|---|
| CI-01 | The release workflow installs only numpy, yet validates the pytest/xdist pins; the next `v*` tag will very likely stop before signing | **High** | Confirmed by code (not executed) |
| CI-02 | The nightly failure reporter has a Python `SyntaxError`, so nightly failures have never opened an issue | Medium | Confirmed (production log) |
| CI-03 | Swift dependency watch has failed on all 4 runs: the default token is refused (403) for Dependabot alerts, and the script treats that feed as mandatory | Medium | Confirmed (production log) |
| CI-04 | No `pull_request` trigger: Dependabot and fork PRs get no CI; Dependabot action bumps *cannot* pass the repository's own contract (the SHAs must match `toolchain.json`) | Medium | Confirmed |
| CI-05 | Trunk-only workflow (hooks block branches and worktrees) makes post-merge CI the only gate; `main` was red on 12% of recent pushes | Medium | Confirmed |
| CI-06 | A TSan failure is forgotten after the next non-Swift push (lane "proof" counts only the macOS test job), and release readiness doesn't run TSan | Medium | Confirmed (simulated) |
| CI-07 | CI never compiles the XCUITest bundles (10.4K lines, touched by 28 of the last 50 commits); a repository invariant forbids even naming them in workflows | Medium | Confirmed |
| CI-08 | The tooling is out of proportion to the product (see section 4.2) | Medium | Numbers Confirmed / judgement |
| CI-09 | No Python static analysis runs anywhere: 41 unused imports; a one-second `ruff F,E9` check would have caught CI-02 | Low | Confirmed |
| CI-10 | Duplication: 39 local JSON loaders, 15 SHA helpers and 19 atomic writers despite `lib/jsonio`; release toolchain setup copied 3× (the root cause of CI-01) | Low | Confirmed |
| CI-11 | The weekly DerivedData cache is saved even by runs that built nothing (a 1.39 GB stale snapshot was then reused all week) | Low | Confirmed (job log) |
| CI-12 | A failing Darwin-only Python step skips the Swift test step in the same job, so that commit has no Swift verdict | Low | Confirmed |
| CI-13 | Stale references to the removed Claude setup remain in `project.yml:324`, four iOS source comments, `OPTIMIZATION.md` and `.gitignore` | Low | Confirmed |
| CI-14 | The Python interpreter is unpinned (Linux CI 3.12, macOS CI Homebrew 3.14.7); research ML dependencies are unpinned | Low | Confirmed |
| CI-15 | One quadratic test (`test_every_declared_required_step_is_failure_injected`, ~1,264 subprocesses) takes 71–84 s, about 40% of the Python suite | Low | Confirmed |
| CI-16 | Release hardening: the authority check waits on a 60–90 min CodeQL run; promotion runs on macOS unnecessarily; the TestFlight upload is outside the evidence ledger; attestations aren't verified on promotion | Low | Confirmed |
| CI-17 | Website production deploys (Vercel Git integration) aren't gated by CI | Low | Likely |
| CI-18 | The contract gate and 5 Python tests fail in shallow clones with misleading errors ("source digest is not reproducible") | Low | Confirmed |
| CI-19 | The resource supervisor marks fast successful processes as "peak-rss-unavailable" under CPU contention (97 of 120 runs), making a research test flaky | Low | Confirmed |
| CI-20 | `.xcodebuildmcp/config.yaml` enables build, run and test workflows that the development policy forbids | Info | Confirmed |
| CI-21 | 18 iOS files are compiled into the macOS app by path; ~57 product files into VocelloCoreTests; the static frameworks get build number 1, against the "one version identity" comment | Low | Confirmed |

### CI-01: The next release will very likely fail at "Install and validate pinned release tooling" (High)

**Evidence**
- Since 2026-09-16, `config/toolchain.json` lists `pytest` 9.1.1 and `pytest-xdist` 3.8.0 in its `native` group.
- The CI composite action installs both (`.github/actions/native-toolchain/action.yml:28-31`).
- The three release jobs don't use that action. Each has its own copy of the setup:
  - `release.yml:212-231` (`package`)
  - `:616-633` (`compile-ios`)
  - `:714-729` (`archive-ios`)
- Those copies install **only numpy**, then run `supply_chain_contract.py --installed native`, which checks for the pytest and xdist versions too.
- A simulation with no pytest installed fails the check.
- Release readiness (`release.sh:161` → `check_project_inputs.sh`) also needs `pytest -n auto`.
- Nothing exercises `release.yml` between releases.

**Impact.** The 3.0.0 tag stops before signing. Nothing unsafe ships, but the fix needs a new commit and a new tag. It surfaces only on release day.

**Recommendation**
- Use the composite action in all three release jobs.
- Add a secrets-free "release rehearsal" job, run weekly and when release inputs change: `release.sh --signing-mode ad-hoc` plus `verify_packaged_dmg.sh`.

### CI-02 and CI-03: Alerting that has never worked (Medium)

**CI-02: the nightly reporter**
- `nightly.yml:119` embeds `python3 -c '…f"- {k}: {v[\"result\"]}"…'`. That is a `SyntaxError` on Python 3.11, 3.12 and 3.13, and appears verbatim in the log of job 106294958394 (Sep 21).
- The nightly is the only place where these run: cold compiles, the optimized warnings-as-errors build, the complete Python suite, and cold TSan. Its failures are therefore invisible unless someone opens the Actions tab.
- **Fix:** use a heredoc or environment variables, and add a CI test that parses every inline Python snippet under `.github/`.

**CI-03: the Swift dependency watch**
- The job grants `security-events: read`. The Dependabot-alerts endpoint still returns 403 to `GITHUB_TOKEN`, and `swift_dependency_updates.py:428` treats that feed as mandatory.
- The lane exists precisely because Dependabot can't read the XcodeGen manifest (the MLX, GRDB and HuggingFace pins). It has never produced a report.
- **Fix:** degrade gracefully on 403 and still publish the release comparison, or supply a token with Dependabot-alert read access.

### CI-04 to CI-06: No pre-merge gate (Medium)

**CI-04: no PR lane**
- `ci.yml` triggers only on `push: main` and on manual dispatch.
- `supply_chain_contract.py:42-59` requires workflow SHAs to equal `toolchain.json`. A simulated Dependabot actions bump fails that contract.
- Updates therefore stall for weeks, and merging one as proposed turns `main` red. `CODEOWNERS` has no effect because nothing goes through a PR.

**CI-05: trunk-only workflow**
- `commit_lint.sh:22-27` blocks commits off `main`, and `policy_guard.sh` blocks branches and worktrees.
- Example: `bb82e20` (the Codex migration) broke the macOS job because `yaml` was missing from the runner's Python.

**CI-06: forgotten TSan failures**
- `classify_changes.py:32-38` counts the Swift lane as proven when "macOS deterministic tests" passed, even if TSan failed.
- Simulated: TSan failed on `cf373d7`, and the docs-only child commit `19992ff` routed `swift: False`, so `CI required` went green.
- `tsan-policy.json` promises "blocking-on-push-ci".

**Recommendation**
- Add a `pull_request` trigger that runs only the cheap Linux lanes: contracts, Python and website. They need no secrets and take about 5 minutes.
- Use short-lived branches that auto-merge when `CI required` passes.
- Auto-sync `toolchain.json` on Dependabot action PRs, or derive the expected SHAs from the workflows.
- Consider disabling Swift version-update PRs, since those pins move in lockstep under benchmark review anyway.
- Require the TSan job in the Swift lane's proof.

### CI-07: UI-test code is never compiled in CI (Medium)

- `repo_invariants.sh:20-43` fails if `ci.yml` or `release.yml` even mentions the UI schemes, so it forbids compiling them, not just running them.
- `development_workflow.py:166-171` records that a UI-test syntax error once surfaced only in a manual lane. The local, advisory compile added in response doesn't trigger on app-side changes such as a renamed accessibility identifier.
- **Fix:** narrow the invariant to patterns that *run* UI tests, and add a compile-only `build-for-testing` step for `VocelloMacUI`, plus iOS with signing disabled.

### Test and tool runs performed for this audit

| Check | Result |
|---|---|
| Python suite, full-history clone, `pytest -n auto` | **1,519 passed, 0 failed, 51 skipped** (Darwin-only), 911 subtests; 167 s |
| Python suite, shallow clone | 5 failures, all history-dependent (CI-18); passes with full history |
| Flake observed once | `test_delivery_compact_model_adapter` "peak-rss-unavailable" (CI-19); passed 6/6 in isolation |
| Contract gate `check_project_inputs.sh --python none` | PASS (24 s, 40 validator calls) |
| `ruff` (default rules) | 182 findings: 55 F401 unused imports, 1 F541, the rest style; no undefined names, bare excepts or mutable defaults |
| `shellcheck` 0.11.0 (36 scripts, warning level) | 0 findings |
| Inline Python in workflows (29 snippets) | 1 syntax error (CI-02) |

---

## 11. Testing and QA

**Verdict:** The Swift tests that exist are high quality, but they are concentrated in the wrong places. They are behavioural, with 4.3 assertions per test, no source-text assertions and almost no sleeps. Most of the orchestration layer that decides what the user can do, though, is never compiled into a test target. The UI suites, the only end-to-end coverage of that layer, never run and are never even compiled in CI.

### 11.1 Inventory

| Suite | Files | Test methods | Asserts per test | Where it runs |
|---|---|---|---|---|
| VocelloCoreTests (macOS unit) | 73 | 616 | 4.3 | Push CI (Swift paths), plus a blocking TSan job and a nightly TSan run |
| VocelloiOSLogicTests | 12 | 96 | 4.3 | Compiled into VocelloCoreTests and run on the macOS host; the iOS bundle itself is compile-only |
| Qwen3RuntimeTests (engine package) | 13 | 125 | 3.9 | Push CI only. Not under TSan, not nightly |
| VocelloMacUITests | 8 | 31 | 9.2 | **Never compiled or run in CI.** Manual `scripts/ui_test.sh macos` |
| VocelloiOSUITests | 13 | 24 | 25 | **Never compiled or run in CI.** Physical iPhone only |
| Python `scripts/tests` | 120 | 1,550 | — | Push (path-routed) plus a nightly full run |
| Website | 4 | 12 + 2 Playwright viewports | — | Push when `website/` changes |

- None of the 1,550 Python tests executes product code. They cover research and audio analysis (426), release and governance tooling (369), benchmark and telemetry tooling (354), device-lane tooling (208) and Swift-source contracts (188).
- About 37% of VocelloCoreTests methods (roughly 227) cover telemetry, diagnostics, evidence, benchmark metrics or the UI-test harness itself.

### 11.2 Coverage map (condensed)

| Subsystem | Rating | Notes |
|---|---|---|
| Sampler, streaming state machine, engine facade | Good (against a fake model) | `VocelloQwen3FacadeTests` (46), `ClassifiedGenerationSessionTests`, `Qwen3GenerationGateTests` |
| Real Qwen3 talker / generate loop (`Qwen3TTS.swift`, 6,154 LOC) | **None in CI** | Only test is `Qwen3TalkerReplayDiagnosticTests`, which skips without a private input |
| AudioSeal watermark (EU AI Act disclosure) | Partial | 2 of 3 parity tests skip in CI; the marking call site in `GenerationOutputAdapter` is never exercised |
| Model download policy and ledger | Good (policy), Partial (end-to-end) | No `URLProtocol`-stubbed network test |
| Installed-model integrity and cleanup (`LocalModelAssetStore`) | **None** | `deepIntegrity` and the `try? removeItem` cleanup have 0 references |
| Long-form planning and assembly, atomic WAV publication | Good | |
| Long-form project runner (`IOSLongFormProject.swift`, 1,137 LOC; shared by both apps) | **None** | |
| Engine / output orchestration (`MLXTTSEngine`, `NativeEngineRuntime`, `GenerationOutputAdapter`, `MLXModelLoadCoordinator`) | **None** (orchestration) | Only static helpers are called |
| Engine host store (`TTSEngineStore.swift`, 1,105 LOC; admission and memory guard) | **None** | |
| Saved voices (`PreparedVoiceRepository`) | Good | Includes a real cross-process lock test |
| History outbox and deletion | Good | |
| Database migrations | Partial | Migrated only from an empty database; no populated v1/v2 fixture carried to v7 |
| Memory tier policy and pressure monitor | Weak | Thresholds unasserted; `NativeMemoryPressureMonitor` has 0 references |
| macOS views, view models, warm-up coordinator | **None automated** | Manual UI lanes only |
| iOS app model, generation coordinator, download coordinator | **None automated** | |
| StoreKit purchase state machine | Good | Adapter and `IOSExportGate` untested |
| **Clone consent gate** | **None** | Every UI test enables consent first; nothing asserts refusal |
| CLI argument parsing (`Args`, dispatch, `GenerateCommand`) | **None** | |
| CLI signals and cleanup | Good | Real SIGINT/SIGTERM delivered to a child process |

### 11.3 Findings

| ID | Finding | Severity | Confidence |
|---|---|---|---|
| TEST-01 | Only ~15% of app-side Swift (9.7K of 63K lines) is compiled into any unit-test target; `TTSEngineStore`, `StudioGenerationCoordinator`, the long-form runner, `DatabaseService`, `AudioPlayerViewModel`, `ModelManagerViewModel`, `IOSExportGate` and the CLI parser have 0 test references | **High** | Confirmed |
| TEST-02 | The engine and output orchestrators (`MLXTTSEngine`, `NativeEngineRuntime`, `GenerationOutputAdapter`, `MLXModelLoadCoordinator`, `NativeAudioPreparationService`) and the real Qwen3 generate loop never run in any test | **High** | Confirmed |
| TEST-03 | The EU AI Act watermark has no CI test of its real transform (2 of 3 parity tests skip) or of its call site | **High** | Confirmed |
| TEST-04 | Nothing tests that voice cloning is refused without consent; every UI test enables consent first | High | Confirmed |
| TEST-05 | UI suites (55 methods, ~9K lines with support code) never run or compile in CI; ~89 of 154 macOS and ~46 of 121 iOS identifiers are never exercised; English-label queries remain in a 10-language app | High | Confirmed |
| TEST-06 | Python "contracts" assert exact Swift source text (15 tests on `BenchCommand.swift`; literal tokens in device eligibility, storage protection and localization contracts) and break on harmless refactors, against the runbook's own "never assert another file's wording" rule | Medium | Confirmed (scratch experiment) |
| TEST-07 | Python tests that read Swift files don't run when only Swift changes (the CI router excludes `*.swift` from the Python lane) | Medium | Confirmed |
| TEST-08 | TSan skips `Qwen3RuntimeTests`, the most concurrency-heavy suite (reservation, lease and critical-relief state machines) | Medium | Confirmed |
| TEST-09 | Installed-model integrity (`LocalModelAssetStore.deepIntegrity`) and its destructive legacy cleanup are untested; no `URLProtocol`-stubbed download test exists | Medium | Confirmed |
| TEST-10 | Database migrations are tested only on an empty database; no populated v1/v2 fixture is carried to v7 through the `v3_drop_sortOrder` table rebuild | Medium | Confirmed |
| TEST-11 | Memory-tier thresholds and the pressure monitor are essentially untested, despite an injectable `deviceClass(physicalMemoryBytes:)` | Medium | Confirmed |
| TEST-12 | Release artifacts are only smoke-tested (the app stays alive 2 s; the CLI runs `--version`, `modes`, `speakers`), recording `"generationQualification": "not-performed"` | Medium | Confirmed |
| TEST-13 | CLI argument parsing (`Args`, dispatch, `GenerateCommand` helpers) has no tests | Low | Confirmed |
| TEST-14 | ~4 s of fixed sleeps in `ModelDownloadChunkSchedulingTests` stand in for an injectable clock | Low | Confirmed |
| TEST-15 | The Swift quarantine hook `TestQuarantine.skipIfListed` has 0 call sites, so quarantine can't actually skip a Swift test | Low | Confirmed |
| TEST-16 | Code coverage is never measured; `macos_test.sh:238` still lists the retired `VocelloEngineIntegrationTests` | Low | Confirmed |
| TEST-17 | "Worker" tests return early and pass vacuously unless an environment variable is set | Low | Confirmed |
| TEST-18 | iOS-specific branches (31 `#if os(iOS)` blocks in shared layers) never execute in any automated test; no test runs optimized code | Low | Confirmed |

### 11.4 What to change

**Open a test seam over the orchestration layer (TEST-01, TEST-02, TEST-04).**
- Move `TTSEngineStore`, `StudioGenerationCoordinator`, the long-form coordinator and runner, `GenerationOutputAdapter`, `DatabaseService` and the consent decision into a testable module, or at least into the `VocelloCoreTests` sources.
- Drive them with a fake `TTSEngine`.
- The first tests to write:
  - consent refusal on every clone entry point;
  - memory admission and critical relief;
  - long-form cancel, resume and regenerate;
  - an output adapter publishing a marked WAV with its provenance chunk.

**Put the real model paths into CI (TEST-02, TEST-03, ENG-01, ENG-02).**
- Add a tiny random-weight Qwen3 configuration (2 layers, small vocabulary, generated in the test).
- Run Custom, Design and Clone through the real talker, code predictor and decoder with a fixed seed. Assert determinism, terminal events and frame counts.
- That one test would have caught ENG-01, ENG-02, ENG-07 and ENG-08.
- Add a synthetic AudioSeal fixture so the transform runs in CI.

**Get an automated UI signal without breaking the project's rules (TEST-05, CI-07).**
- Compile every UI bundle in push CI.
- Add a nightly, non-blocking, model-free macOS XCUITest subset covering navigation, Settings, the missing-model state, pseudo-localization and consent refusal.
- Publish the identifier-coverage number as a tracked metric.

**Retire the source-text contracts (TEST-06, TEST-07).**
- Replace the 15 `BenchCommand.swift` substring tests with Swift unit tests.
- Delete the literal-token checks that duplicate existing behavioural Swift tests.
- Keep the structural bans (forbidden APIs, the import graph, identifier ownership).

**Add data-safety tests (TEST-09 to TEST-11).**
- Migration fixtures at each historical schema version.
- `deepIntegrity` states and cleanup scope.
- Memory-tier boundary tables.
- An injectable clock for the download registry.

---

## 12. Documentation, public claims, website and repository hygiene

**Verdict:** The machinery behind the documentation is excellent:
- A single public-facts file with a validator.
- Generated roadmap, charts and benchmark index, each with a `--check` mode that currently passes.
- Only 3 broken relative links out of 804.
- A website with prerendering, contract tests and a Playwright smoke test at two viewports.

The content has drifted:
- **The README and website describe unreleased `main` next to a 2.4.0 download** (DOC-01).
- Agent-facing docs contradict each other after the Codex-only switch.
- The "start here" progress file has become a 1,115-line changelog.
- The repository carries about 43 MB of images, duplicates and growing benchmark records.

### 12.1 Documentation and public claims

| ID | Finding | Severity | Confidence |
|---|---|---|---|
| DOC-01 | The README describes the unreleased 3.0 candidate (AudioSeal watermark, seed pinning, the eight-preset delivery model, clone delivery banks, the in-process Mac engine, the redesigned UI screenshots) while every download link is 2.4.0, which has none of these | **High** | Confirmed against the v2.4.0 tag |
| DOC-02 | Agent-workflow docs contradict each other after the Codex-only switch: `development-progress.md` "Resume now" says "Claude remains primary"; the "active" Sep 18 review points at deleted `CLAUDE.md` and `.claude/rules/`; code comments cite deleted rule files | Medium | Confirmed |
| DOC-03 | `development-progress.md` is 1,115 lines with 29 dated sections under "Resume now", although its header says it is "not a second work ledger" | Medium | Confirmed |
| DOC-04 | 12 date-stamped one-off reports live in `docs/reference` (8 marked `active` or `current`); there is no docs index; 27 docs share one bulk review date | Medium | Confirmed |
| DOC-05 | Active docs still describe the XPC service removed on Sep 15 (`product-identity-compatibility.md:43`, `runtime-hardening-and-trust-boundary.md`, `PERFORMANCE.md:96`) | Low | Confirmed |
| DOC-06 | The README says "Speed is the recommended default"; the app recommends Quality first on Macs with 16 GB or more | Low | Confirmed |
| DOC-07 | README import and saved-voice details are inconsistent across its three mentions | Low | Confirmed |
| DOC-08 | `docs/releases/v3.0.0.md` (last reviewed Sep 7) omits the in-process engine, the UI redesign, the 8 new interface languages and the iOS purchase | Low | Confirmed |
| DOC-09 | `PRODUCT.md` references a retired "intensity" control and a missing `legacyBody` symbol; the naming record lists the repository as "QwenVoice" | Low | Confirmed |
| DOC-10 | README readability: 25.5 KB and 3,238 words, about 40% engineering internals; the second section is a $19.99 purchase for an unreleased version, and that price is not in `public-product-facts.json` | Low | Judgement |

**DOC-01 in detail**

Checked against tag `v2.4.0` (commit `4a5a905`, Aug 1):
- It contains **0 AudioSeal or marking files**.
- It still contains the XPC engine (`XPCNativeEngineClient.swift`).
- Its README said interactive takes are "not presented as seed-replayable".

The current README (`:93-94`) tells users generated audio carries "an inaudible AudioSeal watermark plus a machine-readable provenance note", next to an EU AI Act Article 50 reference. It also says "Vocello 2.4.0 is available now" (`:119`), and every download button points at the 2.4.0 DMG.

A user who downloads today does not get the AI-disclosure marking the README promises. The public-facts contract checks only version strings, so CI cannot catch this.

**Fix**
- Scope claims and screenshots to `stableMacRelease`.
- Label `main`-only features "Coming in 3.0".
- Add a candidate-only feature list to `public-product-facts.json`, and have `public_facts_contract.py` fail when the README or website mentions any of them.

### 12.2 Website

| ID | Finding | Severity | Confidence |
|---|---|---|---|
| WEB-01 | The site mixes 2.4.0 and `main` facts; the Engineering section still describes the separate-process Mac engine that 3.0 removes | Medium | Confirmed |
| WEB-02 | About 5.6 MB loads up front in 13 requests: the favicon is the 1.15 MB, 1,024 px app icon; 7 full-size PNG screenshots (4.2 MB) are preloaded; no lazy loading, dimensions, `srcset` or modern formats; 3 unused assets deployed | Medium | Confirmed (measured) |
| WEB-03 | `--fg-tertiary` text is 3.8:1 on the charcoal background (below AA's 4.5:1) in about 18 styles, including the download metadata and the macOS 26 / Apple Silicon requirement line | Medium | Confirmed (computed) |
| WEB-04 | The performance chart's screen-reader label (0.60–0.96) and cited record (`111d88c6`) don't match the plotted data (0.53–0.82, record `379db820`); the README has the same mismatch | Medium | Confirmed |
| WEB-05 | Stale copy: "three files at a time" (the code runs 6 files × 4 workers); an "Excited / Normal" label for a retired preset; the `og:description` says "Custom Voice"; "offline" and a competitor's name in the meta keywords | Low | Confirmed |
| WEB-06 | Three play buttons share the same accessible name; none has `aria-pressed`; heading levels skip from h1 to h3, and the footer uses h5 | Low | Confirmed |
| WEB-07 | "2.4.0" is hard-coded in 4 components, and the buttons link `/releases/latest` rather than the stable tag from the facts file | Low | Confirmed |
| WEB-08 | The support page and issue templates link GitHub Discussions, which are disabled; the privacy page uses the banned purple accent; no `robots.txt`, `sitemap.xml` or canonical tag on the privacy page | Low | Confirmed |

The website check passes: lint, 12/12 tests, build (JS 73 KB gzipped) and 2/2 Playwright runs, with 0 npm vulnerabilities. The findings above are about content and assets, not code quality.

### 12.3 Terminology

**UX-01: the same things have different names across surfaces.**
- The model settings section is "Model downloads" on the Mac, "Voice Models" on iOS, "Model Downloads" on the website and "Settings, Voice Models" on the support page.
- Casing varies ("Saved Voices" vs "Saved voices").
- `website/PRODUCT.md` mandates "Generation History" and "Saved Voices", but the sidebar says "History" and "Voices".
- The iPhone screenshot still shows a "Custom" mode tab.
- **Fix:** publish a short glossary, and lint the string catalog for casing.

**UX-02: spot-check of public claims against the code.**

| Claim | Result |
|---|---|
| 9 built-in speakers | ✓ |
| 10 speech languages | ✓ |
| 900-character long-form threshold | ✓ |
| iPhone is Speed-only | ✓ |
| Speed packages are ~6 GB | ✓ |
| Preset-honesty wording | ✓ |
| Mac imports OGG/WebM | Listed, but probably not decodable (MAC-09) |
| "Three files at a time" | ✗ |
| "Speed is the recommended default" | ✗ |

### 12.4 Repository hygiene

| ID | Finding | Severity | Confidence |
|---|---|---|---|
| REPO-01 | `design_references/` holds 15.6 MB in 108 files: 34 anonymous `pasted-*.png` files (8 MB), READMEs describing "Vocello 2.0", and folder names with spaces. About 20 iOS source comments cite its small `.jsx`/`.css` files as provenance | Medium | Confirmed |
| REPO-02 | `benchmarks/runs` holds 340 records (27.7 MB) and grows by ~110 records (~9 MB) a month with no retention policy; 137 records are exploratory and excluded from trends | Low | Confirmed |
| REPO-03 | 27 groups of byte-identical files waste 14.2 MB: the README banner and app icon exist in 4 copies each, screenshots are duplicated between `docs/` and `website/`, and one Swift source is duplicated | Low | Confirmed |
| REPO-04 | The product has three names in the tree: the Xcode project, scheme, targets and module are `QwenVoice`; the iOS module is `QVoiceiOS`; Mac bundle IDs are `com.qwenvoice.*`; environment variables use both `QWENVOICE_*` and `QVOICE_*`; "QwenVoice" appears 1,839 times and "QVoice" 900 times | Low | Judgement |
| REPO-05 | Contributor path: the Discussions link is dead, there's no PR CI, and there's no root `NOTICE` pointing at the third-party attributions | Low | Confirmed |

**REPO-04 in detail.** The naming record is right to freeze identifiers that touch user data: bundle IDs, the App Group, data folders and stored schemas. It also freezes build-only names (project, scheme, target and module), which could be renamed with no data migration.

**Fix**
- Split the record into "persistent, frozen" and "build-only, renameable".
- Schedule a mechanical rename after 3.0, checked by CI.
- Until then, add a name-mapping table to `CONTRIBUTING.md`.

**Repository metrics**

| Metric | Value |
|---|---|
| Tracked files | 1,580 (84.2 MB working tree) |
| Git pack, full history | 65.9 MB; 1,736 commits since 2026-02-21 |
| Largest tracked file | `Localizable.xcstrings`, 1.79 MB |
| Markdown | 107 files, 27,795 lines (~264K words); `docs/reference` alone is 48 files and 17,688 lines |

---

## 13. Status of previously tracked findings

This covers the September 18 review's AUD-01 to AUD-12, selected roadmap items, and open GitHub issues, all checked against commit `7e26f94`.

| Item | Roadmap status | Still present? | Current evidence and notes |
|---|---|---|---|
| AUD-01: iOS launch dead ends | parked | **Yes, and wider** | Terminal startup screen with no retry (`QVoiceiOSApp.swift:44-58`). The import cover can still collide with onboarding (`RootView.swift:117,138,325-342`). New triggers: IOS-05, IOS-06. macOS equivalent: MAC-04 |
| AUD-02: one iOS audio-session owner | parked | **Yes, and wider** | 20 session-mutation sites in 6 files; new facets IOS-02 to IOS-04 |
| AUD-03: Studio screens own generation Tasks | planned | Yes (low risk) | Views still construct the `Task`; the coordinator still guards stale attempts |
| AUD-04: clone readiness | parked | Yes, **on both platforms** | `canGenerate` ignores `cloneContextStatus` (iOS `:1440-1450`, macOS `:97-105`); IOS-18 is related |
| AUD-05: History persistence | planned | Yes | Reads through a write transaction; filesystem reconcile inside the transaction; unbounded reload. The iOS `try?` unlink is still silent. **The macOS delete path does surface failures** |
| AUD-06: iOS modal VoiceOver exclusion | parked | Yes | 0 `accessibilityHidden` backgrounds, `.isModal` or escape actions |
| AUD-07: unverified StoreKit recovery | parked | Present by design | No security defect; UX question only |
| AUD-08: logging privacy gate | planned | Yes | `print(error.localizedDescription)` sites remain; path-bearing errors reach UI and diagnostics (MAC-07, SEC-11) |
| AUD-09: smoke fixture prerequisite | planned | Yes | `ui_test.sh:303-307` preflights the fixture only for benchmark+clone runs |
| AUD-10: engine kept hot by browsing | planned | **Yes, and wider** | Also: a mode switch triggers a 900 ms unload/load cycle of 2–2.8 GB; a typing pause triggers a GPU prefetch |
| AUD-11: sampler membership | planned | Yes | `Qwen3TTS.swift:4710-4715`; the outer set is written but never read |
| AUD-12: deprecated interruption keys | parked | Yes | 3 sites |
| F-18: preserve destinations on failure | parked | **Fixed in source** | Atomic rename; destination never used as cleanup authority. Consider closing |
| F-25: busy Saved Voice store fatal to engine init | planned | Yes, and wider | CORE-09 (stray file) and IOS-05 (malformed transaction) are more triggers on the same fatal path |
| ASR-02: Hugging Face privacy disclosure | planned | Yes | SEC-14 |
| ASR-04: attributions and content rights | in-flight | Yes, with new gaps | SEC-03 (clone sample still live) and SEC-10 (AudioSeal attribution) |
| ASR-06: sensitive-file protection | parked | Implemented in code | IOS-06 shows its cost at launch; IOS-10 and CORE-05 show gaps in what is backed up |
| AV-13: UI identifiers never exercised | planned | Yes | About 89 macOS and 46 iOS identifiers (TEST-05) |
| Issue #101: consent gate UI-only | open | **Yes** | SEC-04 and TEST-04 |
| Issue #86: CLI reports 0.1.0 | open | **Appears fixed in source** | `Support.swift:187-189` reads `CFBundleShortVersionString` or reports "unknown". Verify and close |
| Issue #88 (draft PR, July 29) | open | n/a | Stale draft; close or land |

**Roadmap health.** The roadmap has 63 open items: 39 parked, 8 in flight, the rest planned. Most parked items wait on a physical-device window. The release plan (RF-*) is almost entirely parked, which matches CI-01: no one has exercised the release path since August.

---

## 14. Prioritized action plan

Effort is a rough estimate for one engineer who knows the codebase: **S** is under half a day, **M** is 1–3 days, **L** is a week or more.

### Now: this week, cheap and high-leverage

| # | Action | Findings | Effort |
|---|---|---|---|
| 1 | Use the native-toolchain composite action in all three release jobs; add a secrets-free, ad-hoc-signed "release rehearsal" job (weekly and on release-input changes) | CI-01, CI-10 | S–M |
| 2 | Fix the nightly reporter (heredoc); make the dependency watch tolerate the 403; add a CI check that parses inline Python in `.github/` plus `ruff --select F,E9` | CI-02, CI-03, CI-09 | S |
| 3 | Move signing and App Store Connect secrets into a tag-restricted `release` Environment with a reviewer; require dispatch from the tag ref; pass `inputs.output_name` through `env:` and validate it | SEC-01, SEC-07 | S |
| 4 | Take the voice-cloning marketing sample off the website until a consent record exists | SEC-03 | S |
| 5 | Correct the README and website: scope claims and screenshots to 2.4.0, and label 3.0 features "coming in 3.0" (watermark first); add a candidate-feature guard to the public-facts contract | DOC-01, WEB-01, DOC-08 | S–M |
| 6 | Remove the post-acquire `Task.checkCancellation()` in `acquirePrewarmSlot`, and add a race test | CORE-01 | S |
| 7 | Stop hashing models in `ModelManagerViewModel.init`; verify asynchronously off the main actor, with a persisted trust receipt | MAC-01 | M |
| 8 | Wire "Prefer lower-memory models" into `activeVariant(for:)`, or remove it | MAC-02 | S |
| 9 | Guard Save As against replacing its own source | MAC-03 | S |
| 10 | Close or update stale tracker items: issue #86 (appears fixed), roadmap F-18 (fixed), draft PR #88; triage the 5 Dependabot PRs | §13 | S |

### Before the 3.0 release

| # | Action | Findings | Effort |
|---|---|---|---|
| 11 | Restore the decoder's 72-frame sliding window, with a reference-parity fixture and the fixed-seed QC battery; fix the quality-first `> 0` trim and the ICL cut | ENG-01, ENG-02 | M |
| 12 | Add a tiny seeded random-weight Qwen3 end-to-end test to `Qwen3RuntimeTests`, and a synthetic AudioSeal fixture | TEST-02, TEST-03 | M |
| 13 | Define the iOS background policy: cancel or checkpoint through the engine barrier inside `beginBackgroundTask`; disable the idle timer while generating; `withError`; clear deferred releases on `.active` | IOS-01, IOS-02, IOS-11 | M |
| 14 | One iOS audio-session and playback coordinator | AUD-02, IOS-03, IOS-04, AUD-12 | M |
| 15 | Enforce clone consent in a core policy covering every entry point, including the CLI, and unit-test the refusal | SEC-04, TEST-04 | M |
| 16 | Make loading fail-closed: no deletes inside the loader, throw on a missing tokenizer or decoder, full weight verification, no `talkerConfig!` | ENG-03, ENG-04, ENG-05 | M |
| 17 | Make startup recoverable on both platforms: bootstrap retry; saved-voice store faults scoped to Voices; storage protection off the main thread and non-fatal | AUD-01, MAC-04, IOS-05, IOS-06, CORE-09 | M |
| 18 | Qualify the signed CLI; then either drop the app's two hardened-runtime exceptions or give the CLI its own entitlement role | SEC-05 | M |
| 19 | Isolate signing from build and test; no Actions cache in signing jobs; `-T /usr/bin/codesign` | SEC-02 | M |
| 20 | Replace string-matched cancellation and allocation-retry decisions with typed errors; use throwing file APIs and add a free-space preflight on macOS and the CLI | CORE-02, CORE-03 | M |
| 21 | Privacy and compliance: AudioSeal attribution and correct revision; `3B52.1`; privacy policy update (ASR-02); microphone copy; lifecycle for derived clone artifacts | SEC-10, SEC-13, SEC-14, IOS-17, CORE-05 | M |
| 22 | Accessibility pass: editor labels (macOS), VoiceOver announcements and modal exclusion (iOS), scalable fonts, no timed banners with actions, website contrast | MAC-08, IOS-12, IOS-13, AUD-06, WEB-03 | M |
| 23 | Localization pass: route computed English and typed errors through catalog keys; add plurals; macOS InfoPlist catalog; honour the in-app locale in formatters | MAC-06, MAC-07, MAC-10, MAC-11, IOS-14 | M–L |
| 24 | Say on iOS that model downloads need Wi-Fi; persist drafts; redefine "keep audio files" on iOS | IOS-08, IOS-09, IOS-10 | S–M |

### Next quarter: structural

| # | Action | Findings | Effort |
|---|---|---|---|
| 25 | Add a `pull_request` lane (Linux contracts, Python, website) and short-lived branches with auto-merge on `CI required`; auto-sync `toolchain.json` for Dependabot | CI-04, CI-05 | M |
| 26 | Extract a shared framework target for code now compiled by path into both apps and the tests; bring `TTSEngineStore`, the coordinators, the long-form runner and `DatabaseService` under unit test with a fake engine | TEST-01, CI-21 | L |
| 27 | Compile UI bundles in push CI; nightly model-free macOS XCUITest subset; TSan over the CPU-only runtime tests; nightly coverage trend | CI-07, TEST-05, TEST-08, TEST-16, CI-06 | M |
| 28 | Tooling diet: move research tooling to `research/` with its own pinned environment, outside the product gate; retire the 11 unused scripts and date-stamped contracts; finish the `lib/jsonio` consolidation; one-in, one-out rule for contracts | CI-08, CI-10, TEST-06 | M–L |
| 29 | Docs diet: trim "Resume now" to under 150 lines; move dated reports to `docs/reports/`; front-matter and link checks in the contracts lane; a `docs/README.md` index | DOC-02, DOC-03, DOC-04 | M |
| 30 | Repository diet: move `design_references` images out (keep the cited text files); benchmark retention policy; de-duplicate assets; website image pipeline | REPO-01, REPO-02, REPO-03, WEB-02 | M |
| 31 | Memory-relief serialization and storage lifecycle: one admission gate for all trims; load epochs; prune shared components and `trash/`; move the symlink overlay out of the model folder | CORE-06, CORE-07, CORE-08 | M |
| 32 | Post-3.0 mechanical rename of build-only `QwenVoice`/`QVoice` names | REPO-04 | L |

---

## 15. Appendix: severity scale, finding counts and evidence log

### Severity scale

| Severity | Meaning |
|---|---|
| **Critical** | Actively exploitable vulnerability, or data loss or corruption affecting typical users now. *None found.* |
| **High** | Likely user-facing failure on a common path, a release blocker, a compliance statement contradicted by shipped behaviour, or a security weakness with severe impact and a cheap fix. Address before the next release. |
| **Medium** | A real defect with bounded impact or a narrow trigger, or a significant gap in verification, recoverability, accessibility or maintainability. |
| **Low** | A minor defect, an edge case, or hygiene with a clear fix. |
| **Info** | An observation, dead code, or context for other findings. |

### Finding counts by area

| Area | Critical | High | Medium | Low | Info | Total |
|---|---|---|---|---|---|---|
| Engine runtime (ENG) | 0 | 1 | 5 | 11 | 1 | 18 |
| Engine host layer (CORE) | 0 | 1 | 7 | 11 | 3 | 22 |
| macOS app (MAC) | 0 | 1 | 8 | 17 | 0 | 26 |
| iOS app (IOS) | 0 | 1 | 12 | 12 | 0 | 25 |
| Security, privacy, compliance (SEC) | 0 | 1 | 4 | 10 | 2 | 17 |
| Build, CI/CD, release (CI) | 0 | 1 | 7 | 12 | 1 | 21 |
| Testing and QA (TEST) | 0 | 5 | 7 | 6 | 0 | 18 |
| Documentation (DOC) | 0 | 1 | 3 | 6 | 0 | 10 |
| Website (WEB) | 0 | 0 | 4 | 4 | 0 | 8 |
| Terminology (UX) | 0 | 0 | 0 | 1 | 1 | 2 |
| Repository hygiene (REPO) | 0 | 0 | 1 | 4 | 0 | 5 |
| **Total** | **0** | **12** | **58** | **94** | **8** | **172** |

Some findings describe the same root cause from two angles. For example, TEST-04 and SEC-04 both concern clone consent, and TEST-02 and ENG-01 both concern the untested decoder. They are counted separately because they need different fixes.

### Cross-reference of duplicate observations

| Topic | Primary ID | Also seen as |
|---|---|---|
| Launch-time hashing on the main thread | MAC-01 | Host-layer review; TEST-09 |
| iOS background redirect allowlist | SEC-08 | Host-layer review |
| Unpinned download APIs in owned code | SEC-12 | ENG-18; host-layer review |
| Clone consent enforced only in the UI | SEC-04 | TEST-04; issue #101 |
| Debug and diagnostics knobs outside the compile gate | SEC-06 | IOS-15; host-layer review |
| Download-diagnostics path redaction | SEC-11 | Host-layer review; AUD-08 |
| No PR CI / stalled Dependabot | CI-04 | REPO-05; SEC-17 |
| Stale Claude-era references | CI-13 | DOC-02 |
| Website security headers | SEC-15 | Website review |
| `output_name` script injection | SEC-07 | CI-16 |

### Evidence log

**Revision**
- `7e26f94b2dbba790bfcd112f57699d89847aab76` (`main`, 2026-09-22).
- The local clone was shallow (50 commits). History-dependent checks used a full clone of the same HEAD.

**GitHub Actions runs cited**

| Run or job | What it shows | Finding |
|---|---|---|
| Nightly run 35585214770, job 106294958394 | `SyntaxError` in the issue-filing step | CI-02 |
| Nightly run 35585214770, job 106286856821 | Python suite failed on a git `maintenance.lock` race, later fixed in `1337843` | — |
| Swift dependency watch runs 33435625158, 34153303882, 34887815274, 35646599774 | All fail with `HTTP Error 403: Forbidden` on `/dependabot/alerts` | CI-03 |
| CI run 35557587042 (`bb82e20`) | Codex migration broke the macOS job | CI-05 |

**Reference implementation compared (ENG-01, ENG-02).** `QwenLM/Qwen3-TTS`, `qwen_tts/core/tokenizer_12hz/modeling_qwen3_tts_tokenizer_v2.py`:
- l.419: `attention_type = "sliding_attention"`
- l.549-551: `create_sliding_window_causal_mask`
- l.1012: `(audio_codes[..., 0] > -1)`

**Release tag compared (DOC-01).** `v2.4.0` = `4a5a905`:
- 0 files matching AudioSeal, `MLXAudioMark` or `AudioPublicationMarking`.
- `Sources/QwenVoiceNative/XPCNativeEngineClient.swift` is present.

**Commands run**

| Command | Result |
|---|---|
| `python3 -m pytest -n auto` (full-history clone) | 1,519 passed, 51 skipped, 911 subtests, 167 s |
| `scripts/check_project_inputs.sh --python none` | PASS |
| `ruff check scripts` | 182 findings, mostly style |
| `ruff check scripts --select E,F,W,B,UP,SIM` | Reviewed; no real bugs beyond CI-09 |
| `shellcheck -x` on 36 scripts | 0 warnings |
| `npm --prefix website run check` | lint, 12 tests, build and 2 Playwright runs pass |
| `npm audit` | 0 vulnerabilities |
| `python3 scripts/roadmap.py render --check` | Fresh |
| `generate_readme_charts.py --check` | Fresh |
| `public_facts_contract.py` | PASS |
