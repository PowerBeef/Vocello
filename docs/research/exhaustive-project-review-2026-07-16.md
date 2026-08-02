---
status: historical
owner: backend-mlx
summary: QwenVoice / Vocello — Updated Exhaustive Technical Review. Imported point-in-time research snapshot. Pinned: superseded figures carry inline editor's notes; contract JSON remains status authority.
contentDigest: sha256:460a58900b43fc3924a88ab18a2a97dd0dfa481d9b63c68e2e718b81bab5bef3
---
# QwenVoice / Vocello — Updated Exhaustive Technical Review

> **Imported research snapshot (2026-07-16).** Converted 2026-07-22 from the external HTML
> report bundle into the repository so corrections and review history stay tracked. Every
> measured figure below is a point-in-time capture from on or before 2026-07-16; the
> 2026-07-22 backend refactor review counter-verified this corpus and found its measured
> claims correct at capture with several since superseded. Superseded figures carry inline
> **Editor's note** blocks; see [`docs/research/README.md`](README.md) for the verification
> summary and [`config/runtime-refactor-contract.json`](../../config/runtime-refactor-contract.json)
> for current phase status.


**Repository:** `PowerBeef/Vocello`
 **Reviewed branch:** `main`
 **Exact reviewed head:** [`bb006acc78faa741e6c2d2622ce9a507c5e95026`](https://github.com/PowerBeef/Vocello/commit/bb006acc78faa741e6c2d2622ce9a507c5e95026)
 **Tested PR head:** [`6e2060f5cf06ea94234eaf750db1cd662e625d69`](https://github.com/PowerBeef/Vocello/commit/6e2060f5cf06ea94234eaf750db1cd662e625d69) — tree-identical to the merge commit
 **Previous report head:** [`dbf51a5d01384b4a0b1a0f999b731b5a57a62b1c`](https://github.com/PowerBeef/Vocello/commit/dbf51a5d01384b4a0b1a0f999b731b5a57a62b1c)
 **Overhaul merge:** [PR #70 — Complete owned Qwen3 core overhaul and acceptance](https://github.com/PowerBeef/Vocello/pull/70)
 **Review date:** July 16, 2026
 **Review type:** exhaustive static repository, architecture, runtime, model, product, security, release, evidence, developer-experience, and continuity review
 **Public product:** Vocello
 **Repository and compatibility identity:** QwenVoice   8.8 /10 updated static engineering score   **Executive verdict.** Main now contains the complete owned-core overhaul and the strongest evidence set in the project’s history. The work since the last review fixed the Qwen clone frontend and artifact identity at a technically serious level, completed and live-qualified cross-platform model delivery, refreshed clean canonical Mac and iPhone baselines, repaired hosted CI toolchain routing, and merged the entire program into the default branch. This is a material advance—not a documentation update. The project is now close to a release-quality platform, but it is not finished: the XPC host still has a confirmed admission-ordering defect, the memory-pressure monitor still contains an unsynchronized field, the documented CLI build has a current portability failure, and the first-party facade is not yet the single lifecycle used by the product.    0critical findings 2high findings 15medium findings 7low findings 232Swift test cases inventoried 509Python test cases inventoried

>

**Interpretation.** The score rose from the previous review because the project now has current hosted CI, current canonical hardware evidence, a corrected clone feature frontend, stronger artifact identity, and live model-delivery proof. Finding counts are not a regression metric: this review removes resolved issues, preserves unresolved ones, and adds newly visible transitional or developer-experience findings.

## 1. Executive assessment

### Bottom line

Vocello has crossed an important architectural threshold. The code that began as a narrowed `mlx-audio-swift` import is now visibly and operationally a first-party runtime. The package lives inside the monorepo, application targets depend on a Vocello-owned facade, model and clone artifacts have immutable provenance, and runtime/evidence/release behavior is governed by machine-readable contracts. Main now contains the complete program rather than a recovery-only branch.

PR #70 was a substantial platform change: 21 commits, 326 changed files, 26,689 additions, and 3,271 deletions. It merged the core facade, typed generation ownership, model delivery, clone conditioning, persistence, CI, security, release evidence, hardware acceptance, and documentation in one program. Its exact head passed hosted macOS deterministic tests, iOS device-SDK app and logic-test compilation, website checks, and dependency review; the merge commit contains no file delta from that tested head.

The most important advances since the last report are:

1. **Clone conditioning is now technically credible.** The project added a Qwen-specific speaker frontend—24 kHz, 1024-point FFT, 256-sample hop, reflect padding, periodic Hann, magnitude STFT, Slaney mel scale/normalization, and natural-log features—rather than reusing a generic Whisper-style frontend. Embeddings are finite `float32 [1,D]`, mono input shapes are strict, and artifact schema 3 binds model repository, revision, artifact version, installed integrity digest, runtime profile, and feature algorithm.
2. **The clone fix is device-proven.** A two-take physical-iPhone lane passed transcript-backed and genuine sidecar-free x-vector-only conditioning with distinct identities, output/ASR, memory, correlation, crash, and cleanup checks.
3. **Cancellation is device-proven.** Visible user cancellation and typed critical-memory cancellation both completed without History publication; full unload followed memory cancellation; the same engine then generated and persisted a recovery result.
4. **Model delivery is fully qualified.** The complete six-artifact catalog now drives Mac, CLI, and iPhone. Current isolated proofs transferred exactly 2,312,057,897 payload bytes with no retry or duplicate bytes, enforced redirects, and passed final integrity.
5. **Canonical performance evidence is current.** Clean 29-take macOS and iPhone records cover the owned core with telemetry schema v8, full correlation, qualified memory, and clean crash deltas. Project health marks every runtime hardware domain fresh.
6. **Hosted CI is real, not inferred.** The tested tree passed macOS deterministic tests, iOS app and logic-test compilation, website checks, and dependency review.
7. **Release engineering is now transactional.** The repository defines clean source identity, process-bound required steps, signing/notarization, SBOMs, checksums, evidence, attestation, draft assets, redownload verification, and publish-last behavior.

The remaining risks are narrower but important:

- **XPC admission is ordered incorrectly.** A rejected second generation can cancel the accepted generation’s event forwarder.
- **A production data race remains.** `NativeMemoryPressureMonitor.currentLevel` is unsynchronized.
- **The source-build contract is not portable.** Open issue #69 exposes Python-sensitive wildcard validation and poor Xcode preflight in the documented CLI path.
- **The owned facade is transitional.** The product still bypasses its declared stable session and relies on external serialization of public model methods.
- **Released-user truth is behind source truth.** The clone issue is fixed and closed on main, while the only public DMG remains the affected 2.1.0 build.

### What impressed me most

The clone repair is the most technically meaningful improvement. It does not merely add an `xVectorOnly` Boolean. It corrects feature extraction, validates embedding shape and finiteness, version-binds the feature algorithm, includes installed-model integrity in prompt identity, rejects stale artifacts, and proves both conditioning modes on hardware.

The model-delivery pipeline is equally strong. Exact catalog identity now reaches every host; foreground metrics are attributable; background task adoption is durable; delegate ingress is bounded; URLSession finish/completion ordering is preserved across actor bridges; cancellation writes are authorization barriers; and live proofs record payload, redirect, protocol, retry, duplicate, thermal, and integrity outcomes.

The evidence system also deserves emphasis. The repository does not merely keep benchmark JSON. It distinguishes clean canonical records from dirty exploratory records, tracks direct tests and hardware freshness per critical domain, validates required-step failure injection, and refuses to let raw local artifacts masquerade as durable proof.

### What concerns me most

The project’s evidence sophistication can make static lifecycle defects easy to discount. Current canonical hardware evidence is fresh, yet H-01 and H-02 remain directly visible in source. A test matrix proves the scenarios it executes; it does not prove every adversarial interleaving.

The other concern is authority duplication. The repository now owns a stable session, product session, engine coordinator, service coordinator, prewarm gate, memory-pressure executor, model-operation gate, and platform stores. Each exists for a good reason, but the final architecture should converge them around one operation lease rather than keep adding adjacent safety layers.

## 2. Snapshot and delta since the previous report

### Exact source state

```
repository:        PowerBeef/Vocello
default branch:    main
reviewed commit:   bb006acc78faa741e6c2d2622ce9a507c5e95026
tested PR head:    6e2060f5cf06ea94234eaf750db1cd662e625d69
previous review:   dbf51a5d01384b4a0b1a0f999b731b5a57a62b1c
pre-overhaul main: 2f1391d846b2ed259db6959ca47f6129cddb58d2

```

The current merge commit is one commit ahead of the tested PR head with no changed files. This lets the hosted PR results speak to the exact merged tree even though the merge SHA itself is different.

### Work completed after the previous review

| Commit family | Change | Engineering effect |
| --- | --- | --- |
| Clone repair | Official speaker frontend, strict mono normalization, finite embedding checks, schema-3 artifact identity | Corrects the lowest-level clone-conditioning contract and invalidates incompatible prompts |
| Model metrics | Foreground request identities for Mac/CLI downloads | Makes payload metrics attributable outside iOS background sessions |
| Download terminal ordering | Serial delegate queue, bounded progress gate, staged terminal sequencer | Prevents progress-task backlogs from overtaking durable completion |
| Mac benchmark | Clean canonical 29-take owned-core record | Refreshes loading, sampling, streaming, terminal, event, memory, and XPC evidence |
| iPhone benchmark | Clean canonical 29-take physical-device record | Refreshes in-process generation, cancellation, memory, and UI evidence |
| Evidence closure | Project health and docs synchronized with accepted runs | Converts implementation work into explicit current proof |
| Hosted CI routing | Exact Xcode 26.6 path and separate native/release tool groups | Repairs runner selection and removes release-only tools from ordinary jobs |
| Merge | PR #70 into `main` | Makes the monorepo core the default project architecture |

### Updated scorecard

| Area | Score | Assessment |
| --- | --- | --- |

| Product clarity | 9.2 | A coherent local-first voice studio, honest iPhone distribution status, and strong workflow differentiation. |

| Architecture | 9.1 | The macOS XPC / iOS in-process / CLI topology remains the right Apple-platform design. |

| Owned Qwen3 core | 8.8 | Excellent lineage, facade, model identity, clone conditioning, and evidence governance; lifecycle authority is still transitional. |

| Runtime correctness | 8.0 | Cancellation, clone, and output contracts improved materially; two confirmed concurrency/control defects remain. |

| Concurrency and memory | 8.0 | Typed terminal barriers and physical-device proof are strong, but an unsynchronized pressure state and one lease gap remain. |

| Clone conditioning | 9.3 | Official Qwen speaker frontend, strict mono normalization, schema-3 artifacts, and two-mode device acceptance. |

| Model delivery | 9.6 | Complete exact catalog, redirect policy, durable iOS restoration, bounded delegate ingress, terminal sequencing, and live proofs. |

| Persistence and privacy | 8.2 | Fail-closed initial/open behavior and privacy-safe errors; post-open invalidation/reopen remains incomplete. |

| Testing and evidence | 9.5 | 232 Swift cases, 509 Python cases, forced-failure workflow coverage, fresh canonical Mac/iPhone evidence. |

| Hosted CI | 9.3 | The exact merged tree passed macOS, iOS compile, website, and dependency-review jobs at the tested PR head. |

| Release and supply chain | 9.2 | Draft-build-verify-attest-publish-last design with pinned tools; current release-domain evidence is stale after toolchain changes. |

| Security | 8.6 | Strong model/XPC/release compensating controls; unsandboxed entitlements and local-tamper assumptions still demand discipline. |

| Maintainability | 7.5 | Very good contracts around increasingly large implementation hotspots and duplicated transitional lifecycles. |

| Contributor and CLI experience | 7.0 | Clear documentation, but current issue #69 exposes a portable-validator/build-preflight defect. |

| UX and accessibility | 8.5 | Real-control XCUITest, strong recording/reference feedback, and responsible clone consent; one macOS discoverability gap remains. |

| Documentation and governance | 9.5 | Exceptional machine-readable contracts, runbooks, ADRs, project health, evidence impact, and release evidence. |

| Recovery and continuity | 9.7 | The overhaul is now on main with exact evidence and lineage; independent immutable backup remains prudent. |

### Previous findings: status now

| Earlier concern | Current status | Assessment |
| --- | --- | --- |

| Audio-only cloning | **Resolved and device-proven** | Transcript-backed and genuine x-vector-only paths are typed, independently identified, artifact-bound, and passed a two-take physical-iPhone acceptance lane. |

| Qwen speaker conditioning correctness | **Newly hardened** | The generic Whisper-style frontend was replaced by a Qwen-specific magnitude/Slaney/natural-log frontend, with finite float32 embedding validation and strict mono shapes. |

| iOS cancellation / unload sequencing | **Resolved and device-proven** | Visible user cancellation and forced memory-pressure cancellation both reached typed terminal state before full unload, followed by successful recovery generation. |

| Cross-platform model integrity | **Resolved and live-proven** | All six artifacts use one complete catalog; Mac/CLI and iPhone proofs transferred exact bytes, enforced redirect policy, and passed final integrity. |

| Download terminal ordering | **Resolved** | Delegate progress is bounded before actor ingress and terminal completion awaits durable staging in URLSession order. |

| Release publish-before-verify | **Resolved in workflow design** | Future releases build and verify a draft, generate SBOM/checksums/evidence/attestation, redownload assets, and publish last. |

| Mutable Actions and missing governance | **Resolved in repository source** | Action SHAs, toolchain groups, Dependabot, dependency review, CodeQL, CODEOWNERS, issue templates, and SECURITY.md are present. |

| Website absent from CI | **Resolved and hosted** | Website lint, tests, and production build passed on the exact tested PR head. |

| History appearing empty after initialization failure | **Resolved** | History opens fail closed with typed privacy-safe errors; destructive actions remain disabled until recovery. |

| Unbounded macOS generation events | **Resolved with bounded accounting** | Every generation owns a bounded stream and every yield is accounted as accepted, dropped, terminated, or unobserved. |

| Stale runtime evidence | **Materially resolved** | Current canonical 29-take macOS and iPhone runs make generation, clone, event, memory, model-delivery, XPC, and benchmark domains fresh. |

| Hosted verification absent | **Resolved for the merged tree** | The PR head—tree-identical to the merge commit—passed the CI and dependency-review jobs. |

## 3. Scope, method, and limitations

### Scope

This review covers the current `main` tree and the work merged through PR #70:

- public product claims and release state;
- project generation, targets, schemes, dependencies, and compatibility identities;
- the first-party `VocelloQwen3Core` facade and retained implementation modules;
- Qwen speaker feature extraction, model loading, sampling, streaming, Mimi decoding, clone prompt artifacts, and caches;
- shared engine lifecycle, XPC hosting, iOS hosting, CLI, cancellation, pressure response, event delivery, and output finalization;
- production catalog, foreground/background model delivery, restoration, metrics, retries, cancellation, redirect, verification, and atomic install;
- history persistence, privacy-safe errors, diagnostics, local storage, consent, and import/export;
- Swift, Python, shell, UI, device, benchmark, profile, project-health, and evidence-impact systems;
- hosted CI, security scanning, release evidence, signing/notarization design, SBOMs, checksums, and provenance;
- current open/closed issues, contribution experience, review process, and recovery posture.

### Method

The review used exact-ref GitHub source reads, current issue and pull-request state, workflow job results, benchmark/evidence summaries, machine-readable contracts, and control-flow analysis. The previous report was treated as a hypothesis list: every important finding was rechecked against current main rather than carried forward automatically.

Severity means:

| Severity | Meaning |
| --- | --- |
| Critical | Confirmed exploit, severe data loss, or universally release-blocking failure. |
| High | Confirmed major runtime/concurrency/security/control defect with substantial impact. |
| Medium | Material correctness, assurance, API, product, contributor, or maintainability weakness. |
| Low | Localized hardening, cleanup, migration, or documentation opportunity. |

Confidence is **confirmed**, **strong inference**, **process observation**, or a combination where impact is confirmed but the exact root cause needs reproduction.

### Limitations

This is still principally a static and evidence review. I did not independently:

- compile the Xcode project;
- execute Swift, Python, shell, XCUITest, model, benchmark, signing, or notarization commands;
- generate speech or download models;
- inspect the maintainer’s local raw WAVs, traces, `.xcresult` bundles, device state, or uncommitted files;
- inspect private GitHub rulesets, secrets, protected environments, push protection, or App Store Connect.

Hosted CI and current hardware evidence are direct repository facts. They do not replace source review, and the project-health document itself correctly says its inventory is not a release verdict.

## 4. Product and repository profile

Vocello remains a coherent local-first product rather than a generic SDK wrapper. Its three workflows map cleanly onto model capabilities:

- **Custom Voice** selects a supported built-in speaker and delivery instruction.
- **Voice Design** turns a natural-language description into a generated voice.
- **Voice Cloning** uses a permitted reference with transcript-backed or genuine x-vector-only conditioning.

The repository now contains seven major operational surfaces:

1. macOS application;
2. iPhone application;
3. CLI;
4. macOS XPC engine service;
5. shared product engine;
6. first-party Qwen3/Mimi runtime package;
7. website and evidence/release platform.

That breadth is now reflected in governance. `project.yml`, ADRs, toolchain, evidence impact, project health, runtime capabilities, semantic deltas, release evidence, debug knobs, concurrency safety, and build-output policy all function as platform contracts.

### Current public status

- Vocello 2.1.0 is the public Mac release.
- Main contains substantially newer runtime and support behavior.
- iPhone generation and acceptance are implemented, but public distribution remains pending.
- The full language matrix passed all functional gates, but its current record remains exploratory because the captured worktree was dirty.
- The current Mac performance statement is source-linked and more positive than the older baseline: Custom and Design aggregate cells reached or exceeded playback, Clone medium/long were approximately realtime or faster, and Clone short remained below realtime.

The main product-documentation risk is version clarity: users see current-source clone claims next to the 2.1.0 download.

## 5. Architecture and module topology

### Top-level topology

```
macOS
Vocello.app
  └─ QwenVoiceNative / XPC client
      └─ QwenVoiceEngineService
          └─ QwenVoiceCore / MLXTTSEngine
              └─ VocelloQwen3Core

iPhone
VocelloiOS
  └─ QwenVoiceCore / MLXTTSEngine
      └─ VocelloQwen3Core

CLI
vocello
  └─ QwenVoiceCore / MLXTTSEngine
      └─ VocelloQwen3Core

```

This remains the correct platform design:

- macOS receives crash containment and process retirement;
- iPhone keeps MLX in the entitlement-bearing app process;
- CLI stays headless and scriptable;
- product semantics remain shared;
- lower Qwen/Mimi implementation is first-party but does not depend back on UI, XPC, persistence, or product policy.

### Correct ownership boundary

**VocelloQwen3Core should own:**

- Qwen/Mimi implementation;
- model loading and compatibility;
- speaker feature extraction;
- typed clone prompt and artifact format;
- request-local model generation;
- low-level cache/memory controls;
- typed model terminal and diagnostic events.

**QwenVoiceCore should own:**

- product model selection and verified prepared bundle;
- device-class policy;
- output paths, WAV lifecycle, QC, retries, and user-visible errors;
- application generation admission;
- product telemetry and evidence;
- adaptation to XPC/iOS/CLI surfaces.

**Platform layers should own:**

- XPC versus in-process hosting;
- visible state and recovery;
- playback;
- import/export and persistence;
- app background lifecycle;
- platform release evidence.

The current code mostly follows this, but M-02 and M-03 show that lifecycle ownership has not yet fully crossed the new facade boundary.

## 6. Owned Qwen3 core

### Governance quality

The package has a rare level of derivative-software discipline:

- immutable imported origin and license digest;
- separate upstream review point;
- immutable relocation inventory;
- current retained-file inventory;
- compatibility-preserved package/products/modules;
- forbidden reverse dependencies;
- public API baseline;
- capability/evidence ledger;
- semantic delta ledger with upstream disposition and removal criteria;
- notices and model attribution.

Current benchmark-backed loading, sampling, and streaming deltas are marked verified against the new canonical Mac record. Clone artifact integrity remains static, while the new official frontend is intentionally classified as diagnostic plus direct tests and explicit hardware acceptance.

### Clone repair

The new speaker frontend is a substantive correctness fix. Qwen’s speaker encoder does not use the generic mel contract. The current source implements:

- 24 kHz input;
- 1024 FFT;
- 256 hop;
- 384 reflect padding;
- periodic Hann window;
- magnitude spectrum;
- 128 Slaney mel bands;
- Slaney normalization;
- natural logarithm;
- finite float32 embedding validation;
- canonical `[1,D]` persistence;
- strict mono input shape.

Schema 3 adds model repository, pinned revision, artifact version, installed integrity-manifest digest, runtime topology, and speaker feature version to prompt identity. A change in weights, runtime profile, or feature algorithm cannot silently reuse an old prompt.

### Core facade maturity

The facade is valuable and should remain. The next step is to narrow and strengthen it, not remove it. The current public surface still exposes direct loaded-model mutation and a second session path. Once product generation adopts the session, the lower compatibility surface can become internal and the facade can achieve its intended value: safe usage by construction.

## 7. Runtime lifecycle, cancellation, and memory

### Proven improvements

The project now has:

- one active generation coordinator in the product engine;
- typed user, memory-pressure, superseded, and shutdown reasons;
- start gates that prevent engine tasks from racing their own registration;
- terminal wait before trim/unload;
- bounded generation-scoped event streams;
- measured yield outcomes;
- store-level iPhone critical-memory ownership;
- prewarm serialization across actor suspension;
- memory boundaries in telemetry.

The physical-iPhone smoke lane is particularly strong: it exercises visible cancellation, memory-pressure cancellation, full unload ordering, and recovery generation in one acceptance program.

### Remaining lifecycle split

The engine coordinator is stronger than the XPC service coordinator’s usage. H-01 is not a failure of the active coordinator itself; it is a host-ordering bug around it. This reinforces the broader architectural recommendation: **reserve ownership before constructing side effects** at every layer.

### Pressure behavior

The shared pressure executor correctly waits for compute terminal before trim. H-02 is independent: it concerns unsynchronized observation state. M-13 is a narrower future-proofing concern: cancellation and trim should be one admission-owned operation, not merely sequential callbacks.

### Sampling and memory policy

Current application behavior assumes one model generation owner. That assumption makes process-wide variation and memory tuning workable today. The independent core should nevertheless capture these values per session so future concurrent engines, diagnostics, or hosts cannot inherit one another’s policy.

## 8. Streaming, output, and event delivery

### Product path

The product’s event architecture improved greatly:

- one stream per generation;
- no previous-generation backlog contamination;
- exact accepted/dropped/unobserved/terminated accounting;
- typed terminal event;
- preview-rich ordered stream;
- preview-stripped coalesced latest state;
- final WAV remains authoritative.

The unresolved design choice is audio backpressure. `bufferingNewest` protects memory but can sacrifice preview continuity.

### Core session

The core session makes a different trade: no silent substitution, but a full queue fails the generation. That is explicit but still undesirable for progress events. One final architecture should distinguish the delivery class of each event instead of applying one queue policy to everything.

### Output integrity

The product’s output handling remains strong:

- session directories;
- chunk WAVs;
- PCM sanitization for NaN/Inf;
- reusable buffers;
- final-barrier semantics;
- atomic publication;
- partial-output cleanup on cancellation/failure;
- audio QC and telemetry.

These details are easy to overlook and are a significant reason the project is beyond prototype quality.

## 9. Model delivery and artifact integrity

### Production catalog

Every production artifact is defined by:

- model and variant identity;
- platform eligibility;
- repository;
- immutable revision;
- artifact version;
- exact base URL;
- exact total bytes;
- exact file set;
- per-file size;
- per-file SHA-256.

Descriptor disagreement fails before transfer. Paths must remain safe. Initial and redirected URLs must remain HTTPS, credential-free, non-local, non-IP, and within the declared trusted host boundary.

### Foreground and background execution

**Mac/CLI:**

- foreground URLSession;
- exact request identity;
- bounded delegate progress ingress;
- deterministic terminal sequencing;
- final metrics;
- staged verification and atomic install.

**iPhone:**

- app-lifetime background session;
- durable schema-v2 request ledger;
- exact task adoption;
- stale/unknown/duplicate cancellation;
- durable temporary-file staging;
- background completion after postprocessing;
- monotonic restored progress;
- authorization-barrier cancellation writes.

### Current live proof

Both platform proofs transferred exactly 2,312,057,897 expected/wire bytes. iPhone recorded one accepted provider redirect, HTTP/3 plus HTTP/1.1, zero retries and duplicates, nominal thermal state, visible cleanup, and final integrity. Mac/CLI recorded zero control/duplicate bytes, zero retries, nominal thermal, final integrity, and cleanup.

### Residual security boundary

The receipt optimization is appropriate for performance. The report keeps L-06 because security documentation should state exactly what is proven: authentic expected bytes from network transfer and ordinary install lifecycle—not resilience against a malicious same-user process changing a verified file while preserving observed metadata.

## 10. Persistence, diagnostics, and privacy

### Fail-closed history

The project fixed the dangerous semantic problem: an unavailable database no longer looks like valid empty history. Typed errors preserve the user's existing database and audio. Deletion stays disabled until a real read succeeds.

M-07 concerns recovery after later CRUD failures, not the initial design. It is a smaller but real second phase.

### Failure diagnostics

Generation-failure diagnostics are privacy-reduced and bounded:

- allowlisted error code/classification;
- allowlisted stage;
- mode/model ID only where accepted;
- text length rather than text;
- no prompt, transcript, path, URL, username, stack, or arbitrary details;
- bounded entries and bytes;
- backup exclusion;
- best-effort behavior that cannot alter generation.

This is a strong implementation of local supportability without accidental content capture.

### Debug controls

Production-affecting environment variables are inventoried and require the explicit `QWENVOICE_DEBUG` master gate. Path overrides are absolute, standardized, symlink-resolved, writable, and user-owned. The remaining work is documentation accuracy and ensuring process/session overrides reset cleanly where needed.

## 11. Testing, benchmarks, and evidence

### Inventory

The tracked scorecard reports:

- 232 Swift cases in 39 files;
- 509 Python cases in 39 files;
- 55 required steps across 12 workflows, all with forced-failure fixtures;
- 50 unsafe-concurrency annotations, all registered.

The project correctly warns that inventory is not execution.

### Canonical evidence

Current canonical records:

- macOS: `macos-xcui-benchmark-20260716-181853-b4c2e299`;
- iPhone: `ios-xcui-benchmark-20260716-184106-48e3a3a6`.

Both:

- exact 29-take matrix;
- clean source;
- telemetry schema v8;
- complete layer correlation;
- memory qualified;
- crash delta clean;
- accepted soft-trim warning visible.

Current project health marks generation terminal, clone conditioning, event delivery, memory policy, model delivery, XPC transport, and benchmark validation fresh.

### Language evidence

The full physical-iPhone language plan passed:

- 19/19 hint/QC rows;
- 18/18 output rows;
- zero diagnostic failures;
- three-pass on-device ASR.

It remains exploratory because the worktree was dirty, and it retains accepted Spanish Custom written-output/dropout and soft-trim warnings. This is meaningful functional proof but should be repeated cleanly before public iPhone distribution if the ten-language claim is a launch gate.

### Hosted CI

At the tested PR head:

- macOS deterministic job passed;
- iOS app compile passed;
- iOS logic bundle compile passed;
- website deterministic job passed;
- dependency review passed;
- CodeQL was correctly skipped for the PR because the workflow runs it on main push/schedule.

The merge commit has the same file tree. This is a large improvement over the previous report’s evidence limitation.

## 12. CI, release engineering, and supply chain

### Toolchain

Current declared identities include:

- Xcode 26.6;
- Swift 6.3.3;
- XcodeGen 2.45.4;
- xcbeautify 3.2.1;
- ripgrep 15.1.0;
- ShellCheck 0.11.0;
- release `gh` 2.95.0;
- Node 24.15.0;
- npm 11.12.1;
- exact Action SHAs.

The final CI repair correctly selects `/Applications/Xcode_26.6.app` and separates release-only `gh` validation from native build tools.

M-01 shows the remaining gap: Python is a first-class governance/runtime tool but is not in this contract.

### CI shape

Ordinary CI is appropriately UI-free:

- deterministic source/project checks;
- macOS core/XPC/runtime tests;
- iOS device-SDK compilation;
- website checks.

Hardware/model/UI evidence remains explicit and proportionate. That policy is correct.

### Release transaction

The release design is one of the strongest elements in the repository:

```
protected tag
→ clean source/version identity
→ process-bound required-step ledger
→ build/sign/notarize/staple
→ app/XPC/DMG verification
→ SBOM/checksum/evidence/attestation
→ draft release and exact asset replacement
→ redownload and remote verification
→ publish last

```

M-12 exists because this exact process has not yet produced a public post-overhaul release and the final toolchain routing changed after the latest release-domain hardware evidence.

## 13. Security and trust boundaries

### Positive controls

- app/XPC code-signing identity and Team ID requirements;
- signed/notarized/stapled release;
- exact dependency and Action pins;
- complete model catalog and hashes;
- redirect restrictions;
- no executable model content;
- no arbitrary plug-ins/frameworks;
- explicit debug gate;
- user-owned path override;
- privacy-safe diagnostics;
- unsafe-concurrency inventory;
- SBOM and provenance;
- dependency review and CodeQL.

### Elevated entitlements

The Mac app remains outside App Sandbox, allows unsigned executable memory, and disables library validation. These may be necessary for the current MLX runtime, but they increase the consequence of dependency/library compromise. The hardening ADR correctly treats them as constrained exceptions rather than extension points.

Reconsider these entitlements whenever MLX packaging or Apple entitlement support changes.

### No confirmed critical security vulnerability

This review did not confirm arbitrary code execution, model-signature bypass, remote content substitution, privilege escalation, or privacy exfiltration. H-02 is a correctness/data-race issue, not a demonstrated exploit. H-01 is transport/lifecycle correctness, not an identity bypass.

## 14. Product, UX, accessibility, and supportability

### Product maturity

Vocello remains far beyond a model demo:

- local model installation and repair;
- local history;
- saved voices;
- recording/import/transcription;
- playback and live preview;
- batch generation;
- variation policy;
- export;
- CLI;
- model/device diagnostics;
- real release packaging.

### Accessibility and test integrity

The application uses stable accessibility identifiers and visible controls. Clone consent tests navigate to Settings and toggle the same state as users. Recording meters reflect real audio amplitude and remain truthful under Reduce Motion.

### Supportability gaps

The strongest immediate support gap is M-09. Source is fixed; public 2.1.0 is not. The second is issue #69: the documented CLI path currently produces repository-contract noise before explaining its Xcode requirement.

A user-facing diagnostics panel should eventually expose app/build identity, installed model/catalog identity, device tier, verification status, storage root, and privacy-reduced export preview.

## 15. Documentation, governance, and review process

The repository’s documentation system is exceptional:

- living architecture;
- current development checkpoint;
- project-health inventory;
- role playbooks;
- testing and device runbooks;
- model-delivery guide;
- telemetry/benchmark reference;
- release QA;
- App Store submission;
- ADRs;
- machine-readable contracts.

M-15 is not a criticism of solo maintenance. It is a risk observation: a 326-file overhaul spanning runtime, release, security, and evidence is too large for one undifferentiated review surface. The fact that two static defects remain despite extensive verification demonstrates why independent challenge still has value.

## 16. Continuity and recovery

Merging the overhaul into `main` materially improves recoverability. The default branch now contains:

- the first-party runtime;
- immutable lineage;
- exact dependency and toolchain identities;
- generated project inputs;
- tests and runbooks;
- current benchmark summaries;
- release evidence contracts;
- the complete accepted implementation history.

A remote branch is no longer the only source copy. Still preserve major candidates independently:

```
git fetch origin
git tag -a backup/owned-core-main-2026-07-16 bb006acc78faa741e6c2d2622ce9a507c5e95026 \
  -m "Merged owned-core overhaul checkpoint"
git push origin refs/tags/backup/owned-core-main-2026-07-16

git bundle create QwenVoice-owned-core-main-2026-07-16.bundle --all
git bundle verify QwenVoice-owned-core-main-2026-07-16.bundle
shasum -a 256 QwenVoice-owned-core-main-2026-07-16.bundle \
  > QwenVoice-owned-core-main-2026-07-16.bundle.sha256

```

A Git repository still does not preserve local models, raw device evidence, signing keys, provisioning profiles, repository settings, secrets, App Store Connect, or uncommitted work.

## 17. Detailed findings register

The findings below are ordered by severity. Current hardware evidence is acknowledged where relevant; evidence freshness does not override confirmed source defects.

### H-01 — A rejected second generation can still cancel the active generation’s event forwarder

**Severity:** High
 **Confidence:** Confirmed
 **Category:** macOS XPC / generation admission
 **Priority:** P0
 **Suggested owner:** macOS/XPC runtime

The service records request timing, cancels the existing generation-scoped event-forwarding task, starts a new forwarder, and creates the incoming engine task before ServiceActiveGenerationCoordinator decides whether the request is admitted. When registration rejects a second request, the already-running first generation can continue compute after its event drain was canceled.

**Evidence**

-

[Service coordinator rejects when a generation is active](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Sources/QwenVoiceEngineService/EngineServiceHost.swift#L17-L60)
-

[Generate mutates timing and forwarding before admission](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Sources/QwenVoiceEngineService/EngineServiceHost.swift#L349-L388)
-

[Generation-scoped engine event API](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Sources/QwenVoiceCore/TTSEngine.swift#L130-L138)

**Impact**

-

Preview audio, progress, terminal delivery, and service transport telemetry for the accepted first request can disappear.
-

The UI can appear hung or incomplete even when the engine finishes and writes valid output.
-

The rejected request is not side-effect-free, violating the admission contract.
-

The same ordering creates a narrow startup window in which service retirement and cancellation reasoning are harder to prove.

**Recommendation**

Replace register-after-start with a reservation transaction. Reserve the service slot first, create one accepted-operation object that owns request timing, task, start gate, forwarder, reply, cancellation, and terminal wait, then open the gate. A rejected request must create no stream, task, timing row, or mutation of the current operation.

**Acceptance criteria**

-

A concurrently submitted second request receives a typed busy error and has zero effect on the first request.
-

The first request still produces every expected preview chunk and exactly one terminal.
-

A rejected request leaves no timing entry, event subscription, or task.
-

Connection invalidation and shutdown during reservation have deterministic exactly-once cleanup.
-

A service integration test forces the race hundreds of times.

### H-02 — NativeMemoryPressureMonitor.currentLevel is a real cross-executor data race

**Severity:** High
 **Confidence:** Confirmed
 **Category:** Concurrency / memory pressure
 **Priority:** P0
 **Suggested owner:** Shared runtime

currentLevel is a plain mutable stored property. The private dispatch queue writes it while engine and lifecycle callers may read it from other executors. @unchecked Sendable and an 'eventually consistent' comment do not provide synchronization or a Swift memory-ordering guarantee.

**Evidence**

-

[Unsynchronized property and queue-owned writer](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Sources/QwenVoiceCore/NativeMemoryPressureMonitor.swift#L117-L200)
-

[Monitor is included in the concurrency registry](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/config/concurrency-safety.json#L120-L125)
-

[Memory-pressure runtime wiring](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Sources/QwenVoiceCore/MLXTTSEngine.swift#L556-L590)

**Impact**

-

Production code contains undefined concurrent behavior even though the observed value is only policy state.
-

Adaptive unload decisions may observe stale or torn state.
-

The machine-readable safety inventory currently describes a stronger invariant than the source implements.
-

The pattern becomes more dangerous if future fields or compound state are added.

**Recommendation**

Store the level behind Mutex, OSAllocatedUnfairLock, ManagedAtomic, or an actor and expose a synchronized snapshot. Keep DispatchSource creation, event handling, and cancellation on the monitor queue, but do not expose queue-owned mutable state directly.

**Acceptance criteria**

-

No plain mutable field is read outside its synchronization domain.
-

Thread Sanitizer and concurrent transition stress tests are clean.
-

Warning, critical, and normal transitions retain their deduplication semantics.
-

The concurrency registry names the exact primitive and test.
-

Physical memory acceptance is rerun only if behavior—not just synchronization—changes.

### M-01 — The documented CLI build can fail before compilation because Python and wildcard semantics are not controlled

**Severity:** Medium
 **Confidence:** Confirmed impact; root cause strongly inferred
 **Category:** CLI / deterministic tooling
 **Priority:** P0
 **Suggested owner:** Developer experience / release QA

Open issue #69 reports that the latest source fails in project-input validation because several semantic-delta test patterns match no files. Current main still uses terminal '/**' patterns and expands them through pathlib.Path.glob before filtering to files. Hosted CI passes, but Python is absent from the toolchain contract, making the validator sensitive to the caller's Python implementation/version. The later Xcode error on the v2.1.0 tag is expected—this CLI is an Xcode project—but the script should explain that before regeneration and contract work.

**Evidence**

-

[Open CLI build failure](https://github.com/PowerBeef/Vocello/issues/69)
-

[Semantic ledger uses Tests/Qwen3RuntimeTests/** patterns](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Packages/VocelloQwen3Core/PATCHES.json#L38-L90)
-

[Validator delegates globs to pathlib and filters files](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/scripts/vendor_runtime_contract.py#L210-L230)
-

[Live entries fail when expanded test references are empty](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/scripts/vendor_runtime_contract.py#L850-L876)
-

[Toolchain contract does not pin Python](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/config/toolchain.json#L1-L29)
-

[CLI build invokes regeneration before Xcode compilation](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/scripts/build.sh#L207-L222)
-

[README requires full Xcode 26](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/README.md#L103-L114)

**Impact**

-

A documented product surface cannot be built on at least one supported Apple Silicon/macOS setup.
-

The same checkout can pass hosted CI but fail the repository's authoritative local gate.
-

Contributors receive semantic-ledger errors before any actionable Xcode preflight.
-

The claim of deterministic tooling is weaker than the toolchain contract implies.

**Recommendation**

Make contract expansion independent of pathlib version by using explicit recursive file matching or normalizing '/**' to '/**/*'. Declare and validate a supported Python version/range in config/toolchain.json, and test the oldest supported version. Add an early build preflight that distinguishes 'full Xcode missing or not selected' from repository-contract failures. Close issue #69 with the exact fix.

**Acceptance criteria**

-

The reporter's environment and the hosted runner produce the same contract result.
-

All live patch/capability patterns match deterministically on every supported Python version.
-

scripts/build.sh cli fails immediately with an actionable Xcode-selection message when only CommandLineTools is active.
-

The CLI builds from a fresh documented checkout under the supported toolchain.
-

A regression test covers terminal recursive patterns explicitly.

### M-02 — VocelloQwen3GenerationSession is still not the lifecycle used by the shipping engine

**Severity:** Medium
 **Confidence:** Confirmed
 **Category:** Core architecture
 **Priority:** P1
 **Suggested owner:** Owned core + QwenVoiceCore

The package describes a stable first-party session with ordered events, typed cancellation, and one terminal. Product generation still flows through NativeStreamingSynthesisSession and direct per-mode stream methods on VocelloQwen3LoadedModel. Two lifecycle implementations therefore own buffering, terminal classification, cancellation, memory application, and event translation.

**Evidence**

-

[Stable facade session contract](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Packages/VocelloQwen3Core/Sources/VocelloQwen3Core/GenerationSession.swift#L97-L117)
-

[Concrete facade session](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Packages/VocelloQwen3Core/Sources/VocelloQwen3Core/GenerationSession.swift#L228-L360)
-

[Product builds direct model streams](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Sources/QwenVoiceCore/NativeStreamingSynthesisSession.swift#L350-L404)
-

[Architecture still names NativeStreamingSynthesisSession as the product executor](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/docs/ARCHITECTURE.md#L254-L266)

**Impact**

-

Facade-session tests do not directly prove the shipping lifecycle.
-

Cancellation, overflow, finish-reason, and progress semantics can drift between paths.
-

The facade can be called 'stable' while product code remains dependent on compatibility methods.
-

Future maintainers must reason about two owners for the same conceptual operation.

**Recommendation**

Adopt the facade session mode-by-mode and make the product session an output/telemetry adapter around it. Prove fixed-seed token, PCM, finish-reason, cancellation, and memory parity before each cutover. Then make direct per-mode loaded-model streams package-internal or SPI.

**Acceptance criteria**

-

Custom, Design, and Clone all run through one session abstraction.
-

The application owns output files and product telemetry, while the core owns model generation and terminal state.
-

No second cancellation or buffering implementation remains.
-

Facade tests and product integration tests exercise the same lifecycle.
-

The public API baseline shrinks after compatibility methods are internalized.

### M-03 — The facade remains safe only under external serialization and carries contradictory or heuristic policy surfaces

**Severity:** Medium
 **Confidence:** Confirmed design gap
 **Category:** Core API authority
 **Priority:** P1
 **Suggested owner:** Owned core architecture

VocelloQwen3LoadedModel publicly exposes prewarm, stream, full-generate, prompt, and diagnostic-reset operations without actor ownership. VocelloQwen3Runtime applies process-wide memory tuning. Prepared trust appears on both the bundle and optional load behavior, and typed diagnostics are inferred from compatibility action strings. Current product code serializes these paths, but the independent core does not make invalid overlap impossible.

**Evidence**

-

[Public loaded-model operations](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Packages/VocelloQwen3Core/Sources/VocelloQwen3Core/LoadedModel.swift#L318-L599)
-

[Process-wide memory application and duplicate trust inputs](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Packages/VocelloQwen3Core/Sources/VocelloQwen3Core/Runtime.swift#L49-L118)
-

[String-derived typed diagnostic mapping](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Packages/VocelloQwen3Core/Sources/VocelloQwen3Core/Runtime.swift#L121-L158)
-

[Ownership contract prevents reverse dependencies but not operation overlap](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Packages/VocelloQwen3Core/OWNERSHIP.json#L1-L41)

**Impact**

-

A future facade client can overlap prewarm, generation, prompt construction, or cache clearing incorrectly.
-

Two trust values can disagree while the lower compatibility path chooses one effective value.
-

Renaming an internal action can silently change typed diagnostic meaning.
-

Global tuning weakens request isolation when more than one engine/session exists in a process.

**Recommendation**

Introduce an actor-owned core engine that owns one loaded model and one operation lease. Move prewarm, prompt construction, session creation, memory policy, cancellation, unload, and cache clearing behind that actor. Choose one trust authority and emit typed diagnostics at source.

**Acceptance criteria**

-

Illegal overlap cannot be expressed through public API.
-

One value is authoritative for prepared-checkpoint trust.
-

Request memory/sampling policy is captured by the active session rather than mutable process state.
-

No typed diagnostic depends on substring matching.
-

Compatibility helpers become internal/SPI.

### M-04 — A slow or absent facade-session consumer can convert valid synthesis into runtime failure

**Severity:** Medium
 **Confidence:** Confirmed
 **Category:** Core streaming
 **Priority:** P1
 **Suggested owner:** Owned core streaming

The core session uses a bounded non-suspending channel and offers a progress event after every model signal. When capacity fills, offer returns overflow, the generation task catches that condition, and the terminal becomes failed(.runtime). Observer speed is therefore part of synthesis correctness.

**Evidence**

-

[Non-suspending bounded channel](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Packages/VocelloQwen3Core/Sources/VocelloQwen3Core/GenerationSession.swift#L119-L198)
-

[Audio plus progress offers on every signal](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Packages/VocelloQwen3Core/Sources/VocelloQwen3Core/GenerationSession.swift#L257-L338)
-

[Overflow is converted to failure](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Packages/VocelloQwen3Core/Sources/VocelloQwen3Core/GenerationSession.swift#L328-L348)

**Impact**

-

A correct model run can fail because telemetry or UI did not drain quickly enough.
-

Long prompts and small event capacities amplify the risk.
-

The behavior differs from the product router's drop-and-measure policy.
-

Consumers cannot opt out of progress without also risking audio.

**Recommendation**

Separate channels by delivery class: lossless audio with backpressure or disk handoff, coalesced latest progress, retained prepared state, and a guaranteed terminal. The producer should not emit redundant progress after non-progress signals.

**Acceptance criteria**

-

A maximum-length run succeeds with no progress observer.
-

Slow and fast consumers produce identical final PCM and terminal outcome.
-

Progress memory remains bounded by coalescing.
-

Terminal delivery is independent of audio/progress drainage.
-

Overflow telemetry exists without turning observer delay into model failure.

### M-05 — The product’s bufferingNewest policy can evict older live-preview audio

**Severity:** Medium
 **Confidence:** Confirmed tradeoff
 **Category:** Product streaming
 **Priority:** P1
 **Suggested owner:** Streaming / playback

MLXTTSEngine creates per-generation streams with bufferingNewest(256) on macOS and 96 on iOS. Yield accounting is excellent, but when the queue is full the newly accepted event evicts an older event. If that event is a stream chunk, final WAV correctness is preserved while live preview becomes discontinuous.

**Evidence**

-

[Platform capacities](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Sources/QwenVoiceCore/MLXTTSEngine.swift#L637-L645)
-

[bufferingNewest creation and drop accounting](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Sources/QwenVoiceCore/GenerationEventDeliveryProbe.swift#L33-L82)
-

[Dropped chunks are explicitly counted](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Sources/QwenVoiceCore/GenerationEventDeliveryProbe.swift#L181-L207)

**Impact**

-

A slow playback/transport consumer can skip preview audio even when the final output is correct.
-

Mac and iPhone have different tolerated backlogs.
-

A complete final file can coexist with an audibly discontinuous interactive experience.
-

The current canonical benchmark may not force a sufficiently slow consumer to exercise loss.

**Recommendation**

Use a lossless bounded audio queue with producer backpressure or disk-backed handoff. Coalesce only progress and snapshot state. Keep current drop telemetry during migration.

**Acceptance criteria**

-

Supported live-preview flows report zero audio-chunk drops under slow-consumer stress.
-

Final file and preview share the same ordered chunk sequence.
-

Progress remains bounded and coalesced.
-

A deliberately stalled consumer produces a defined pause/backpressure state rather than silent audio loss.

### M-06 — The stable session request’s referenceID is not bound to the separately supplied clone prompt

**Severity:** Medium
 **Confidence:** Confirmed API mismatch
 **Category:** Clone contracts
 **Priority:** P1
 **Suggested owner:** Owned core + clone runtime

Product-side clone prompt caching is now impressively bound to reference, model artifact, runtime profile, language, and speaker-feature version. The public session API still accepts .voiceClone(referenceID: String) in the request and a separate clonePrompt parameter, then validates only that a prompt exists.

**Evidence**

-

[Request carries a string reference ID](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Packages/VocelloQwen3Core/Sources/VocelloQwen3Core/Contracts.swift#L167-L223)
-

[Session only checks prompt presence](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Packages/VocelloQwen3Core/Sources/VocelloQwen3Core/GenerationSession.swift#L377-L414)
-

[Product prompt identity is strongly bound](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Sources/QwenVoiceCore/GenerationSemantics.swift#L134-L261)
-

[Product prompt resolution validates expected metadata](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Sources/QwenVoiceCore/NativeCloneSupport.swift#L276-L369)

**Impact**

-

A future facade caller can associate telemetry/request identity with the wrong prompt.
-

The stable API is weaker than the product-internal artifact contract.
-

Audio-only capability is represented on the model but not verified against the opaque prompt at session construction.
-

Prompt provenance consistency depends on caller discipline.

**Recommendation**

Replace the string-plus-prompt pair with one opaque core-created CloneConditioningHandle carrying immutable identity and mode. The request should contain that handle or its validated token; mismatches must fail before compute.

**Acceptance criteria**

-

It is impossible to pair request A with prompt B through public API.
-

Audio-only mode requires the advertised capability.
-

Model artifact and speaker-feature identity are verified at session construction.
-

Artifact compatibility remains backward-readable or transparently rebuildable.

### M-07 — Visible Retry cannot reopen many failures discovered after the database was initially opened

**Severity:** Medium
 **Confidence:** Confirmed
 **Category:** Persistence recovery
 **Priority:** P1
 **Suggested owner:** Persistence

RecoverableStoreCoordinator enters failed state only when its initialization closure throws. Later CRUD methods classify and throw errors but do not invalidate the coordinator. reopenIfNeeded returns the same available DatabaseQueue immediately, so corruption, permission loss, or durable I/O failure discovered during a read/write may not be recoverable through Retry.

**Evidence**

-

[Coordinator has only available/failed initial states](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Sources/QwenVoiceCore/RecoverableStoreCoordinator.swift#L5-L64)
-

[Database CRUD classifies errors without invalidating store](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Sources/Services/DatabaseService.swift#L57-L134)
-

[Typed persistence classifications](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Sources/SharedSupport/Database/HistoryPersistenceError.swift#L1-L112)

**Impact**

-

The UI can offer Retry while the coordinator returns the same unhealthy queue.
-

A post-open corruption or permission transition can persist across re-entry.
-

The fail-closed behavior is truthful, but recovery semantics are incomplete.
-

macOS and iOS duplicate the same limitation.

**Recommendation**

Add invalidate(with:) and an unconditional reopen operation. Define classification policy: locked/busy may retry on the existing queue; corrupt, permission, migration, and unavailable failures should invalidate and rebuild only after a complete open/migration succeeds.

**Acceptance criteria**

-

A read-discovered corruption transitions to a recoverable failed state.
-

Visible Retry opens a fresh queue and never exposes partial migration.
-

Transient lock behavior does not unnecessarily discard a healthy queue.
-

macOS and iOS share one tested database implementation with injected path.

### M-08 — Checked-in example applications reference products removed from the narrowed runtime

**Severity:** Medium
 **Confidence:** Confirmed
 **Category:** Package / developer experience
 **Priority:** P1
 **Suggested owner:** Owned core maintainers

The owned-core README says there are no checked-in STT, speech-to-speech, VAD, diarization, UI, or non-Qwen targets. Examples/VoicesApp still declares MLXAudioSTT, and Examples/SimpleChat declares MLXAudioVAD. Those products are absent from the package. PATCHES.json nevertheless classifies Examples/** as an active package surface.

**Evidence**

-

[Owned-core surface declaration](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Packages/VocelloQwen3Core/README.md#L1-L21)
-

[VoicesApp references MLXAudioSTT](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Packages/VocelloQwen3Core/Examples/VoicesApp/Package.swift#L1-L30)
-

[SimpleChat references MLXAudioVAD](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Packages/VocelloQwen3Core/Examples/SimpleChat/Package.swift#L1-L30)
-

[Examples are governed as active PKG-001 files](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Packages/VocelloQwen3Core/PATCHES.json#L38-L52)

**Impact**

-

The package's declared surface and checked-in examples disagree.
-

A developer following the examples receives build failures or missing products.
-

Unused sample voice assets add provenance and repository-size surface.
-

Static governance treats unbuilt examples as evidence-backed.

**Recommendation**

Delete the inherited examples, quarantine them as historical evidence, or replace them with small facade-only Qwen3 examples. Any retained example must build in a deterministic lane and use current package/product identities.

**Acceptance criteria**

-

Every checked-in example builds under the documented toolchain.
-

No example references removed products.
-

Retained sample media has explicit provenance.
-

PKG-001 test evidence actually exercises the declared example surface.

### M-09 — Main documents the clone repair while the only public DMG remains the affected 2.1.0 release

**Severity:** Medium
 **Confidence:** Confirmed product/support mismatch
 **Category:** Release communication
 **Priority:** P1
 **Suggested owner:** Release / support

README presents genuine audio-only cloning and links users to Vocello 2.1.0 as the current download. Issue #61 identifies 2.1.0 as affected and was closed as completed after the main-branch fix, without a public fixed release or maintainer explanation. Source truth and released-user truth are therefore different.

**Evidence**

-

[README audio-only claim and current 2.1.0 download](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/README.md#L25-L46)
-

[README public release status](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/README.md#L55-L75)
-

[Issue #61](https://github.com/PowerBeef/Vocello/issues/61)
-

[Development checkpoint says 2.1.0 remains released](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/docs/development-progress.md#L196-L208)

**Impact**

-

A user downloading the advertised current build can still encounter the closed bug.
-

Closing the issue may imply that updating or retrying 2.1.0 resolves it.
-

Support burden increases because source behavior and binary behavior differ.
-

Release notes have no migration guidance for schema-3 clone artifacts.

**Recommendation**

Comment on or temporarily reopen #61 with 'fixed on main, not yet released' and the target version. Add an explicit unreleased-development marker to source-only claims or ship a maintenance release promptly. Include schema-2-to-3 prompt rebuild behavior and workarounds in release notes.

**Acceptance criteria**

-

Every closed user-facing bug names the first fixed public version.
-

README distinguishes current source from current downloadable release where behavior differs.
-

The public fixed DMG passes transcript-backed and x-vector clone acceptance.
-

Upgrade from 2.1.0 saved voices rebuilds old prompt artifacts without data loss.

### M-10 — The dedicated iOS logic-test bundle is still compile-only in ordinary hosted CI

**Severity:** Medium
 **Confidence:** Confirmed assurance limitation
 **Category:** iOS CI
 **Priority:** P2
 **Suggested owner:** iOS + release QA

The new bundle provides valuable iOS-specific policy coverage, but CI only compiles it for the generic device SDK. Assertions do not run there. Physical diagnostics and XCUITest provide strong current evidence, yet pure policy regressions can still wait for explicit device work.

**Evidence**

-

[Development checkpoint describes compile-only behavior](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/docs/development-progress.md#L8-L18)
-

[CI compiles app and logic-test bundle](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/.github/workflows/ci.yml#L20-L112)
-

[README makes the limitation explicit](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/README.md#L118-L133)

**Impact**

-

Catalog, ledger, memory, cancellation, path, and redaction assertions do not execute on every PR.
-

Compilation cannot detect incorrect expected values or state transitions.
-

Device evidence is fresh now but is intentionally not an ordinary merge gate.
-

The test count can be misunderstood as executed coverage.

**Recommendation**

Move platform-neutral assertions into a macOS-executable shared test target. For truly iOS-only logic, add a small app-hosted simulator/device test only where MLX is not involved, or keep an explicit device lane with clear freshness policy. Continue labeling compile versus pass precisely.

**Acceptance criteria**

-

Every pure policy test executes on each PR somewhere.
-

The project-health report distinguishes compiled-only and executed cases.
-

Device-only tests remain limited to APIs that require a real iPhone.
-

No simulator claim is used as proof of MLX device behavior.

### M-11 — Settings-owned clone consent can disable Generate without participating in macOS readiness messaging

**Severity:** Medium
 **Confidence:** Confirmed UX gap
 **Category:** macOS clone UX
 **Priority:** P2
 **Suggested owner:** macOS UX

The Mac composer includes consent in the disabled predicate and silently guards generation. VoiceCloningReadiness.describe receives engine, model, reference, text, and context—but not consent. The visible readiness footer can therefore report an otherwise-ready state while Generate remains disabled.

**Evidence**

-

[Readiness omits consent](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Sources/Views/Generate/VoiceCloningView.swift#L121-L130)
-

[Generate is consent-gated](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Sources/Views/Generate/VoiceCloningView.swift#L379-L419)
-

[Consent is owned in Settings](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Sources/Views/Settings/SettingsView.swift#L30-L75)

**Impact**

-

A first-time Mac user can see a disabled action with no local explanation.
-

iOS provides a clearer Settings instruction than macOS.
-

Moving consent out of the workflow improves policy centralization but increases discoverability cost.
-

Accessibility users may need to search an unrelated section to discover the blocker.

**Recommendation**

Add a consent-required readiness state with an Open Settings action and VoiceOver announcement. Preserve the persistent Settings control as the single source of truth.

**Acceptance criteria**

-

The composer explains the exact blocker whenever consent is false.
-

A visible and accessible action navigates to the consent setting.
-

XCUITest covers first-use recovery from the disabled state.
-

No hidden test override is introduced.

### M-12 — Release-supply-chain evidence is stale after the final toolchain-routing change

**Severity:** Medium
 **Confidence:** Process observation
 **Category:** Release qualification
 **Priority:** P1 before next release
 **Suggested owner:** Release engineering

The exact merged tree passed hosted CI and dependency review, and the release workflow design is strong. Project health nevertheless marks release-supply-chain hardware evidence stale because the final CI/toolchain-routing commit came after the latest canonical Mac record. The new publication transaction has not yet produced a public release artifact.

**Evidence**

-

[Project health marks release-supply-chain stale](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/docs/project-health.md#L21-L40)
-

[Toolchain split and exact versions](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/config/toolchain.json#L1-L29)
-

[Release evidence contract](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/config/release-evidence-contract.json#L1-L77)
-

[Open release work](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/docs/development-progress.md#L196-L208)

**Impact**

-

The workflow is verified by source/tests but not yet by a complete production release transaction.
-

Signing, notarization, GitHub draft mutation, redownload, and final publication depend on external credentials/settings.
-

Administrative rulesets and environment protection remain outside public-tree proof.
-

A future release could expose integration faults not seen in deterministic tests.

**Recommendation**

Run a protected dry-run or next maintenance candidate through the complete managed release transaction. Preserve the draft on failure, verify downloaded assets, and archive the release-verification bundle. Audit actual GitHub rulesets, tag restrictions, environments, secret scanning, and push protection.

**Acceptance criteria**

-

A candidate completes the exact release step ledger under current toolchain.
-

Failure cannot create or publish an incomplete release.
-

Downloaded DMG, metadata, SBOMs, checksums, and attestation all validate.
-

Actual repository settings match a machine-readable expected policy.
-

Project health marks release-supply-chain fresh.

### M-13 — The shared pressure executor does not visibly retain one admission lease through cancel and trim

**Severity:** Medium
 **Confidence:** Strong inference
 **Category:** Memory-operation ownership
 **Priority:** P2
 **Suggested owner:** Shared runtime + platform hosts

NativeMemoryPressureResponseExecutor serializes pressure responses and waits for active generation terminal before invoking trim. The active-generation coordinator can release generation ownership before runtime.trimMemory completes, while the trim path is serialized with prewarm—not obviously with the product model-operation admission gate. The forced iPhone path passed, but a deterministic new-admission race is not evident in direct tests.

**Evidence**

-

[Pressure executor sequences cancel then trim](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Sources/QwenVoiceCore/NativeMemoryPressureMonitor.swift#L1-L97)
-

[Engine wires cancelCurrent and runtime trim as separate callbacks](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Sources/QwenVoiceCore/MLXTTSEngine.swift#L556-L590)
-

[Runtime trim owns a separate prewarm slot](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Sources/QwenVoiceCore/NativeEngineRuntime.swift#L343-L392)
-

[Physical iPhone pressure acceptance passed](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/docs/development-progress.md#L19-L33)

**Impact**

-

A new operation could theoretically enter after terminal cancellation and before hard trim completes.
-

Critical relief should be represented as one resource operation, not two adjacent callbacks.
-

The existing acceptance proves the normal forced path, not every adversarial interleaving.
-

Future proactive warm changes can reopen cache-mutation overlap.

**Recommendation**

Represent pressure relief as an exclusive runtime operation lease covering observation, proactive-work cancellation, generation cancellation, terminal wait, trim/full unload, final state publication, and release. Add a deterministic suspension point immediately after terminal cancellation to prove new admission remains blocked.

**Acceptance criteria**

-

No generation, load, prewarm, or clone prime can start between cancellation terminal and trim/unload completion.
-

The UI exposes a recovering/relieving state until the operation ends.
-

The invariant is tested in shared engine, XPC host, and iOS host.
-

Critical-pressure latency has a measured bound.

### M-14 — The overhaul improves boundaries while leaving very large implementation hotspots and duplicated platform persistence

**Severity:** Medium
 **Confidence:** Confirmed maintainability pressure
 **Category:** Code structure
 **Priority:** P2
 **Suggested owner:** Architecture / maintainers

Qwen3TTS.swift now exceeds 5,400 lines and continues to accumulate loading, sampling, clone, streaming, cache, and telemetry policy. MLXTTSEngine, NativeEngineRuntime, HuggingFaceDownloader, IOSModelDownloadCoordinator, IOSDeviceDiagnosticsRunner, and orchestration scripts are also subsystem-sized. macOS and iOS DatabaseService remain near copies.

**Evidence**

-

[Qwen3 implementation](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift)
-

[Engine runtime](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Sources/QwenVoiceCore/NativeEngineRuntime.swift)
-

[Downloader](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Sources/QwenVoiceCore/HuggingFaceDownloader.swift)
-

[macOS database](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Sources/Services/DatabaseService.swift)
-

[iOS database](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Sources/iOSSupport/Services/DatabaseService.swift)
-

[ADR explicitly defers decomposition](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/docs/decisions/owned-qwen3-runtime-monorepo.md#L38-L46)

**Impact**

-

High-churn lifecycle changes remain difficult to review locally.
-

Actor reentrancy and terminal cleanup are spread across large scopes.
-

Platform copies can diverge despite common semantics.
-

The cost of onboarding or external review remains high.

**Recommendation**

Decompose only along proven contracts: core operation actor, model lifecycle, clone conditioning, event transport, output finalizer, download planner/transfer/verifier/installer, and shared database with injected path. Add characterization tests before moving code; do not combine structural moves with performance changes.

**Acceptance criteria**

-

Each extracted component has one owner and direct tests.
-

macOS/iOS persistence shares one implementation.
-

Public API and behavior remain unchanged during structural phases.
-

Hotspot churn and review surface are measured over time.

### M-15 — A 326-file critical overhaul merged without a human review submission

**Severity:** Medium
 **Confidence:** Process observation
 **Category:** Review governance
 **Priority:** P2
 **Suggested owner:** Repository governance

PR #70 contained 21 commits, 326 changed files, 26,689 additions, and 3,271 deletions across runtime, model delivery, release, security, tests, and evidence. Hosted checks passed and Vercel commented, but no requested reviewer or review submission is recorded. This is understandable for a solo-maintainer project, yet the change exceeded a practical single-pass review surface.

**Evidence**

-

[PR #70 metadata and scope](https://github.com/PowerBeef/Vocello/pull/70)
-

[PR verification and acceptance body](https://github.com/PowerBeef/Vocello/pull/70)
-

[CODEOWNERS](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/.github/CODEOWNERS)
-

[Sensitive-path ownership map](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/docs/ARCHITECTURE.md)

**Impact**

-

Static defects such as H-01 and H-02 survived broad tests and current hardware evidence.
-

CODEOWNERS cannot supply independent challenge when the same maintainer owns every path.
-

A single giant review obscures which commits change behavior versus evidence or documentation.
-

Future forensic rollback is harder when unrelated risk domains merge together.

**Recommendation**

Keep solo ownership practical, but split future programs into reviewed phases: architecture contracts, runtime behavior, delivery, evidence, and release. Require an independent reviewer, external audit, or structured adversarial review for runtime/XPC/release changes before public release—even if ordinary source merges remain maintainer-only.

**Acceptance criteria**

-

Sensitive changes have a recorded second review or equivalent adversarial audit.
-

Behavioral commits are separable from evidence/documentation commits.
-

Release candidates include a findings-closure checklist.
-

Emergency bypass is documented and followed by retrospective review.

### L-01 — A late product-event subscriber can receive a stream that never produces or finishes

**Severity:** Low
 **Confidence:** Confirmed
 **Category:** Event API
 **Priority:** P2
 **Suggested owner:** Event delivery

After terminal delivery the router archives only a snapshot and removes the active continuation. A later stream(for:) call creates a new active continuation without consulting the completed cache, and no producer remains.

**Evidence**

-

[Stream creation ignores completed state](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Sources/QwenVoiceCore/GenerationEventDeliveryProbe.swift#L53-L83)
-

[Terminal archives snapshot and removes active stream](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Sources/QwenVoiceCore/GenerationEventDeliveryProbe.swift#L107-L167)

**Impact**

-

Future diagnostics or integrations can await indefinitely.
-

The API has no explicit late-subscription contract.

**Recommendation**

Return an immediately finished stream or retain/replay the terminal event for a bounded completed-generation cache.

**Acceptance criteria**

- A late-subscription test terminates deterministically.

### L-02 — Successful no-chunk generation can retain an acceptance-timing entry until bounded eviction

**Severity:** Low
 **Confidence:** Strong inference
 **Category:** XPC telemetry
 **Priority:** P3
 **Suggested owner:** XPC telemetry

Request timing is normally consumed by the first forwarded chunk and discarded on failure. The success path does not explicitly discard it after generation result. A nonstreaming or no-chunk success can therefore leave one of the bounded 64 entries.

**Evidence**

-

[Timing registry semantics](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Sources/QwenVoiceEngineService/EngineServiceHost.swift#L93-L122)
-

[Generate success does not discard timing](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Sources/QwenVoiceEngineService/EngineServiceHost.swift#L349-L388)

**Impact**

-

Small bounded stale telemetry state.
-

Acceptance-to-first-chunk metrics can be confused if IDs were ever reused.

**Recommendation**

Discard timing on every terminal path, including successful completion without a consumed first chunk.

**Acceptance criteria**

- Registry count returns to zero after every terminal scenario.

### L-03 — Public sampling exposes seed and arbitrary top-K values that the adapter rejects

**Severity:** Low
 **Confidence:** Confirmed
 **Category:** Facade API
 **Priority:** P3
 **Suggested owner:** Owned core

VocelloQwen3SamplingConfiguration publicly carries topK and seed. validatedForCompatibilityAdapter requires topK == 50 and seed == nil. The product still applies reproducibility outside this facade.

**Evidence**

-

[Public fields and rejection](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Packages/VocelloQwen3Core/Sources/VocelloQwen3Core/Contracts.swift#L88-L138)
-

[Loaded-model adapter uses compatibility validation](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Packages/VocelloQwen3Core/Sources/VocelloQwen3Core/LoadedModel.swift#L370-L379)

**Impact**

-

The stable API advertises policy it cannot execute.
-

Sampling ownership remains split.

**Recommendation**

Implement request-local seed/top-K in the core or remove them from the stable constructible contract until supported.

**Acceptance criteria**

- Every public sampling field is honored or impossible to set.

### L-04 — Architecture and build comments still describe superseded event/debug interfaces

**Severity:** Low
 **Confidence:** Confirmed documentation drift
 **Category:** Documentation
 **Priority:** P3
 **Suggested owner:** Documentation

The architecture reference describes TTSEngineEventStreaming as a single events property, while source uses events(for:). build.sh still mentions a hidden version-tap toggle, while DebugMode resolves only the explicit process environment gate.

**Evidence**

-

[Stale architecture wording](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/docs/ARCHITECTURE.md#L238-L266)
-

[Current generation-scoped API](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Sources/QwenVoiceCore/TTSEngine.swift#L130-L138)
-

[Build comment mentions hidden toggle](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/scripts/build.sh#L1-L10)
-

[Current DebugMode uses environment gate only](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Sources/Services/DebugMode.swift#L1-L11)

**Impact**

-

Maintainers can misunderstand the API or production debug activation.
-

Documentation-contract coverage misses semantic phrasing drift.

**Recommendation**

Generate API excerpts from source and make debug activation wording derive from the knob registry.

**Acceptance criteria**

- Every documented activation/API path exists in current source.

### L-05 — Implemented feature requests remain open while the released clone issue closed without version guidance

**Severity:** Low
 **Confidence:** Process observation
 **Category:** Issue hygiene
 **Priority:** P3
 **Suggested owner:** Project maintenance

Variation control (#47) and clear-history-without-file-deletion (#48) appear implemented but remain open. Clone issue #61 is closed despite no fixed public release or maintainer comment.

**Evidence**

-

[Issue #47](https://github.com/PowerBeef/Vocello/issues/47)
-

[Issue #48](https://github.com/PowerBeef/Vocello/issues/48)
-

[Issue #61](https://github.com/PowerBeef/Vocello/issues/61)

**Impact**

- Public backlog and support state do not accurately represent delivered versus unreleased work.

**Recommendation**

Add labels, implementation commits, validation status, and fixed release versions; close at the correct public boundary.

**Acceptance criteria**

- Every open or closed user-facing issue has a current maintainer status.

### L-06 — Same-process verified-artifact receipts are not a malicious-local tamper guarantee

**Severity:** Low
 **Confidence:** Defense-in-depth inference
 **Category:** Model integrity threat boundary
 **Priority:** P3
 **Suggested owner:** Security + model delivery

The one-hash receipt design is an excellent performance optimization and strong against network corruption and accidental mutation. Finalization later trusts path/size/time/file-identifier/process-generation metadata rather than rehashing, so a same-user local adversary is outside the strongest proof.

**Evidence**

-

[Receipt contracts](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Sources/QwenVoiceCore/ModelDownloadContracts.swift)
-

[Downloader finalization](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Sources/QwenVoiceCore/HuggingFaceDownloader.swift)
-

[Runtime hardening ADR](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/docs/decisions/runtime-hardening-and-trust-boundary.md#L23-L68)

**Impact**

-

Documentation can imply stronger local tamper resistance than implemented.
-

Unsandboxed storage raises the relevance of the boundary.

**Recommendation**

Document the threat model and optionally support descriptor-bound rename or final rehash for high-assurance installs.

**Acceptance criteria**

- Security docs distinguish transport/content integrity from same-user local compromise.

### L-07 — Schema-3 clone prompt migration should be exercised as an installed-version upgrade

**Severity:** Low
 **Confidence:** Release migration gap
 **Category:** Clone artifact upgrade
 **Priority:** P3
 **Suggested owner:** Clone runtime + release QA

The repaired clone contract intentionally rejects schema-2 artifacts and rebuilds them from reference audio. Deterministic artifact tests are strong, but a tracked upgrade acceptance from an actual 2.1.0 data tree is not identified.

**Evidence**

-

[Clone artifact format schema-3 requirements](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Packages/VocelloQwen3Core/CLONE_ARTIFACT_FORMAT.md)
-

[Clone repair commit](https://github.com/PowerBeef/Vocello/commit/2047d48556e8656ff805f493a535ed7b21d2bf9e)
-

[2.1.0 remains current release](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/README.md#L55-L75)

**Impact**

-

A one-time rebuild failure could affect saved voices only after upgrade.
-

Support needs clear expectations for latency and cache replacement.

**Recommendation**

Run an upgrade test with real 2.1.0 saved voices, old prompt artifacts, interrupted rebuild, and rollback; document automatic rebuild in release notes.

**Acceptance criteria**

- All saved voices remain usable and user audio/transcripts are preserved across upgrade.

## 18. Prioritized remediation roadmap

### Immediate stabilization · 0–7 days

-

Fix H-01 with service-level reservation-before-side-effects and adversarial XPC tests.
-

Fix H-02 with synchronized pressure state and update the concurrency contract.
-

Resolve issue #69: portable recursive matching, Python toolchain policy, and early Xcode preflight.
-

Update issue #61 and README/release messaging to distinguish fixed main from public 2.1.0.
-

Delete or repair the broken owned-core examples.

### Core convergence · 1–4 weeks

-

Introduce an actor-owned core engine/operation lease.
-

Migrate Custom, Design, and Clone to the single facade session with parity evidence.
-

Split audio, progress, prepared, terminal, and diagnostics delivery classes.
-

Bind clone request identity to one opaque conditioning handle.
-

Resolve duplicate trust authority and source-emitted typed diagnostics.
-

Add database invalidation and shared injected-path persistence.

### Qualification · 2–6 weeks

-

Rerun only behavior-affected canonical hardware lanes after correctness fixes.
-

Run one clean full language corpus-v2 acceptance before public iPhone distribution.
-

Run a real managed macOS release candidate through draft, signing, notarization, evidence, redownload, and publish-last.
-

Run the 2.1.0-to-schema-3 saved-voice upgrade matrix.
-

Execute pure iOS policy assertions on every PR through a shared or app-hosted test route.

### Sustained maintenance · 1–4 months

-

Decompose Qwen3TTS, engine lifecycle, downloader, and device diagnostics by tested responsibility.
-

Retire compatibility products and direct facade methods only through parity-gated phases.
-

Establish external/adversarial review for XPC, runtime, model, and release changes.
-

Add read-only GitHub-settings conformance reporting.
-

Maintain immutable tags and independent Git bundles for major release candidates.

## 19. Release-readiness gates

### Next macOS maintenance release

Required:

1. H-01 and H-02 fixed with direct regression tests.
2. Issue #69 resolved for a clean supported checkout.
3. Public release notes identify issue #61 and the first fixed version.
4. 2.1.0 saved-voice/schema-3 upgrade test passes.
5. Exact tagged source passes deterministic CI and required security jobs.
6. Affected canonical Mac tests are refreshed if behavior changed.
7. Release-supply-chain project-health state is fresh.
8. App/XPC Team ID, hardened runtime, entitlements, notarization, and staple pass.
9. DMG, metadata, SBOMs, checksums, evidence, and attestation validate after redownload.
10. Failure leaves only a draft/internal candidate.

### iPhone public distribution

Treat as blockers:

1. Clean full language corpus-v2 run or an explicitly narrowed language claim.
2. Current visible user-cancel and memory-pressure cancel/full-unload proof.
3. Current transcript-backed and x-vector-only clone proof.
4. Redirect-aware background model lifecycle and delete proof.
5. Low-storage, reinstall, corruption, background/foreground, sustained-load, and Jetsam review.
6. Signed archive/IPA bundle, build, identifier, arm64 UUID, signature continuity, privacy manifest, entitlements, profile, certificate, and team/App ID verification.
7. App Store Connect metadata, screenshots, support/privacy URLs, review notes, TestFlight rollout, and rollback plan.
8. Exact source/model/toolchain/hardware identities attached to acceptance.

### Core facade 1.0 gate

Before treating the facade as a stable independent runtime API:

- one canonical generation session drives all product hosts;
- public operations are actor-owned and safe by construction;
- memory/sampling policy is request/session scoped;
- clone request and prompt identity are one opaque value;
- one prepared-trust authority exists;
- typed diagnostics originate as typed events;
- audio/progress/terminal delivery contracts are distinct;
- unsupported seed/top-K fields are removed or implemented;
- direct compatibility methods are internal/SPI;
- examples build and demonstrate the supported facade only.

## 20. Recommended engineering metrics

### Reliability

-

generation success by host, mode, model, and warm state
-

XPC rejected-request side-effect count, target zero
-

terminal exactly-once rate
-

cancel acknowledgement, compute-stop, and reclamation latency
-

post-cancel chunks
-

database degraded-state and successful reopen rate
-

model transfer/adoption/repair success

### Performance

-

TTFC and RTF p50/p95
-

peak combined footprint and minimum headroom
-

model load/prewarm duration
-

audio backlog depth and audio-drop count
-

progress coalescing ratio
-

pressure signal to trim/unload completion
-

download payload/control/duplicate bytes and verification time

### Quality

-

clone output quality by transcript-backed versus x-vector mode
-

speaker-feature/artifact rebuild success
-

long-batch adjacent-segment drift
-

fixed-seed parity
-

language hint/QC/output coverage
-

ASR consensus and audio-QC warning distribution

### Assurance

-

exact-head hosted CI age
-

hardware evidence commit distance
-

required-step forced-failure coverage
-

CodeQL/dependency-review completion
-

release-evidence freshness
-

unsafe declaration count and synchronized invariant coverage
-

public issues with fixed-release attribution

### Maintainability

-

hotspot line count and churn
-

number of parallel generation lifecycles
-

duplicated platform implementation count
-

public facade surface size
-

broken example count, target zero
-

sensitive changes receiving independent review
-

recovery checkpoint age and bundle verification

## 21. Verification commands for the reviewed main checkout

Deterministic:

```
git fetch origin
git switch main
git pull --ff-only
test "$(git rev-parse HEAD)" = "bb006acc78faa741e6c2d2622ce9a507c5e95026"

git diff --check
./scripts/check_project_inputs.sh
python3 scripts/vendor_runtime_contract.py validate
python3 scripts/benchmark_history.py validate --all
scripts/macos_test.sh test
./scripts/build.sh build
./scripts/build_foundation_targets.sh ios

```

Explicit quality:

```
scripts/ui_test.sh macos smoke
scripts/ui_test.sh macos benchmark

scripts/ios_device.sh preflight
scripts/ui_test.sh ios smoke
scripts/ios_device.sh clone-conditioning
scripts/ui_test.sh ios model-download
scripts/ui_test.sh ios benchmark

```

Release candidate:

```
python3 scripts/project_health.py report --output build/artifacts/project-health/
python3 scripts/evidence_impact.py report --base <last-release-tag> --head HEAD
# Then use the protected tag/draft release workflow rather than publishing manually.

```

## 22. Evidence index

| Area | Exact source |
| --- | --- |
| Reviewed main commit | [main at `bb006acc78faa741e6c2d2622ce9a507c5e95026`](https://github.com/PowerBeef/Vocello/commit/bb006acc78faa741e6c2d2622ce9a507c5e95026) |
| Tested PR head | [`6e2060f5cf06ea94234eaf750db1cd662e625d69`](https://github.com/PowerBeef/Vocello/commit/6e2060f5cf06ea94234eaf750db1cd662e625d69) |
| Overhaul PR | [PR #70](https://github.com/PowerBeef/Vocello/pull/70) |
| Delta from previous review | [compare previous head to current main](https://github.com/PowerBeef/Vocello/compare/dbf51a5d01384b4a0b1a0f999b731b5a57a62b1c...bb006acc78faa741e6c2d2622ce9a507c5e95026) |
| Product claims | [README](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/README.md) |
| Current checkpoint | [development progress](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/docs/development-progress.md) |
| Project health | [project health](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/docs/project-health.md) |
| Architecture | [architecture reference](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/docs/ARCHITECTURE.md) |
| Owned-runtime ADR | [ADR](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/docs/decisions/owned-qwen3-runtime-monorepo.md) |
| Runtime lineage | [LINEAGE.json](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Packages/VocelloQwen3Core/LINEAGE.json) |
| Runtime ownership | [OWNERSHIP.json](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Packages/VocelloQwen3Core/OWNERSHIP.json) |
| Runtime capabilities | [RUNTIME_CAPABILITIES.json](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Packages/VocelloQwen3Core/RUNTIME_CAPABILITIES.json) |
| Semantic deltas | [PATCHES.json](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Packages/VocelloQwen3Core/PATCHES.json) |
| Clone artifact format | [CLONE_ARTIFACT_FORMAT.md](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Packages/VocelloQwen3Core/CLONE_ARTIFACT_FORMAT.md) |
| Qwen speaker frontend | [Qwen3TTSSpeakerMelFrontend.swift](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSSpeakerMelFrontend.swift) |
| Facade contracts | [Contracts.swift](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Packages/VocelloQwen3Core/Sources/VocelloQwen3Core/Contracts.swift) |
| Facade session | [GenerationSession.swift](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Packages/VocelloQwen3Core/Sources/VocelloQwen3Core/GenerationSession.swift) |
| Loaded-model facade | [LoadedModel.swift](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Packages/VocelloQwen3Core/Sources/VocelloQwen3Core/LoadedModel.swift) |
| Product engine | [MLXTTSEngine.swift](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Sources/QwenVoiceCore/MLXTTSEngine.swift) |
| Product runtime | [NativeEngineRuntime.swift](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Sources/QwenVoiceCore/NativeEngineRuntime.swift) |
| Product stream session | [NativeStreamingSynthesisSession.swift](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Sources/QwenVoiceCore/NativeStreamingSynthesisSession.swift) |
| XPC host | [EngineServiceHost.swift](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Sources/QwenVoiceEngineService/EngineServiceHost.swift) |
| Memory pressure | [NativeMemoryPressureMonitor.swift](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Sources/QwenVoiceCore/NativeMemoryPressureMonitor.swift) |
| Event delivery | [GenerationEventDeliveryProbe.swift](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Sources/QwenVoiceCore/GenerationEventDeliveryProbe.swift) |
| Clone product support | [NativeCloneSupport.swift](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Sources/QwenVoiceCore/NativeCloneSupport.swift) |
| Model catalog | [ProductionModelCatalog.swift](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Sources/QwenVoiceCore/ProductionModelCatalog.swift) |
| Downloader | [HuggingFaceDownloader.swift](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Sources/QwenVoiceCore/HuggingFaceDownloader.swift) |
| Persistence | [RecoverableStoreCoordinator.swift](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/Sources/QwenVoiceCore/RecoverableStoreCoordinator.swift) |
| Concurrency contract | [concurrency-safety.json](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/config/concurrency-safety.json) |
| Evidence impact | [evidence-impact.json](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/config/evidence-impact.json) |
| Toolchain | [toolchain.json](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/config/toolchain.json) |
| CI | [ci.yml](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/.github/workflows/ci.yml) |
| Security | [security.yml](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/.github/workflows/security.yml) |
| Release workflow | [release.yml](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/.github/workflows/release.yml) |
| Release evidence | [release-evidence-contract.json](https://github.com/PowerBeef/Vocello/blob/bb006acc78faa741e6c2d2622ce9a507c5e95026/config/release-evidence-contract.json) |
| Current CLI failure | [Issue #69](https://github.com/PowerBeef/Vocello/issues/69) |
| Released clone bug | [Issue #61](https://github.com/PowerBeef/Vocello/issues/61) |

## 23. Final assessment

The overhaul has succeeded strategically. Vocello now owns the runtime it actually maintains, in the repository where the product lives, behind a typed facade, with exact model provenance, strong clone artifact identity, robust model delivery, serious cancellation semantics, and current cross-platform evidence. The main branch is no longer merely promising this architecture; it contains it.

The next phase should be smaller and more disciplined than the overhaul:

1. remove the two confirmed source defects;
2. restore deterministic source/CLI portability;
3. converge the facade and product onto one lifecycle;
4. make core safety internal rather than caller-dependent;
5. repair the remaining persistence, event, example, and UX edges;
6. run one release transaction and one clean language acceptance;
7. ship the clone fix and reconcile issue/release truth.

The recommended posture is therefore:

- **preserve the current top-level architecture;**
- **keep the monorepo-owned core;**
- **do not undertake another broad rewrite;**
- **close correctness findings before feature expansion;**
- **split the next work into independently reviewable phases;**
- **keep evidence exact, proportionate, and source-bound.**

**Updated static score: 8.8 / 10.**
 **Critical: 0. High: 2. Medium: 15. Low: 7.**

Prepared from direct GitHub evidence at `bb006acc78faa741e6c2d2622ce9a507c5e95026`. Hosted CI applies to the tree-identical tested PR head `6e2060f5cf06ea94234eaf750db1cd662e625d69`. Static limitations and private administrative boundaries are documented above.

## Appendix A — Definition of done for the owned-core program

The program is complete when:

1. main contains the first-party runtime and immutable lineage;
2. product code imports only the intended facade;
3. one actor-owned session drives every host;
4. XPC admission is side-effect-free until reserved;
5. memory pressure state is synchronized;
6. pressure cancellation and trim/unload share one operation lease;
7. audio delivery is lossless by supported contract;
8. progress is coalesced rather than correctness-critical;
9. clone conditioning is one opaque identity-bound value;
10. schema-2 artifacts rebuild safely on upgrade;
11. every public sampling field is supported;
12. prepared trust has one authority;
13. typed diagnostics are emitted at source;
14. runtime CRUD failures can invalidate and reopen persistence;
15. every retained example builds;
16. Python and Xcode preflight are deterministic;
17. exact main/tag hosted checks pass;
18. current hardware evidence is fresh for behavior changes;
19. release-supply-chain evidence is fresh;
20. a fixed public release closes the user-facing clone bug with version attribution.

## Appendix B — Suggested canonical core shape

```
public actor VocelloQwen3Engine {
    public func load(_ bundle: PreparedModelBundle) async throws
    public func makeCloneConditioning(
        reference: CloneReferenceInput
    ) async throws -> CloneConditioningHandle
    public func start(
        _ request: SynthesisRequest
    ) throws -> any GenerationSession
    public func unload() async
}

public protocol GenerationSession: Sendable {
    var id: UUID { get }
    var audio: AsyncThrowingStream<AudioChunk, Error> { get }
    var progress: AsyncStream<ProgressSnapshot> { get }
    func cancel(reason: CancellationReason) async
    func terminal() async -> TerminalOutcome
}

```

Properties of this shape:

- the engine owns serialization;
- clone identity cannot disagree with prompt;
- audio and progress have different delivery semantics;
- terminal completion is independent of stream drainage;
- request policy is session-scoped;
- raw MLX and compatibility modules do not cross the facade;
- the product still owns output files, retries, history, and user-visible state.

## Appendix C — Threat-model summary

| Threat | Current controls | Residual boundary | Next control |
| --- | --- | --- | --- |
| Network/model substitution | exact revision, file set, size, hash, host/redirect policy, atomic install | malicious same-user post-hash modification | explicit threat statement; descriptor-bound rename or final rehash option |
| Unknown background task | encoded identity, ledger/catalog match, duplicate cancellation | storage/ledger corruption | continued fault-injection and recovery export |
| Rogue XPC client/service | bundle/team requirement, signed nested service | missing Team ID in non-release context | release assertion remains mandatory |
| XPC request race | typed wire contract, one coordinator | side effects before admission | reservation transaction |
| Memory-pressure overlap | typed cancel and terminal barrier | unsynchronized level; lease split | synchronized monitor and one pressure operation |
| Malicious audio | normalization, mono/sample-rate rules, size/duration/quality checks | decoder/framework parser surface | fuzz/oversize fixtures and strict budgets |
| Debug injection | master gate, knob registry, user-owned paths | stale documentation/session reset assumptions | source-derived docs and reset tests |
| Evidence false pass | step ledger, fault injection, exact manifests | large validator surface and Python portability | pinned Python and mutation tests |
| Release substitution | signing, notarization, checksums, SBOM, attestation, redownload | private settings/credentials | settings conformance report and protected environment |
| Voice misuse | consent, reminders, local-first storage | user-attested provenance | optional source note/export labeling and deletion UX |

## Appendix D — Current issue triage

| Issue | Interpretation | Recommended action |
| --- | --- | --- |
| #69 | Confirmed current contributor/CLI blocker; Xcode requirement also needs clearer preflight | P0 fix, reproduce reporter Python, close with exact commit/toolchain |
| #61 | Fixed and accepted on main, but no public fixed release | Add maintainer comment and fixed-version milestone before closure remains final |
| #47 | Variation control appears implemented | Verify shipped platform parity and close/narrow |
| #48 | Clear-history-without-file-deletion appears implemented | Verify macOS/iOS behavior and close/narrow |
| #55 | Speak selection/clipboard integration | Platform feature; separate from runtime overhaul |
| #54 | Segment replay/regeneration | Larger editor/history design |
| #30 | Long-batch consistency | Quality/reproducibility program with fixed seeds and adjacent-segment metrics |
| #6 | Delivery instructions in clone | Model research; avoid promising unsupported identity/style disentanglement |
| #35 | Voice swap | Separate speech-to-speech research surface |

## Appendix E — Review confidence boundary

This report can establish source architecture, control flow, contracts, issue state, hosted job results, and tracked evidence identity. It cannot independently establish:

- subjective audio quality;
- Metal/MLX behavior outside recorded scenarios;
- correctness of private signing/provisioning state;
- absence of local uncommitted work;
- real GitHub administrative protections;
- App Store review readiness.

The report therefore treats direct source defects as defects even when broad evidence is green, and treats hardware acceptance as proof only for its exact source, device, model, toolchain, and scenario.   Prepared from exact-ref GitHub repository evidence. Static limitations and private administrative boundaries are documented in the report.
