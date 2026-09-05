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

## September 5 later physical pilot — resume checkpoint

On unchanged `main` at `1ba75045`, preflight passed and the bounded two-take pilot
`ios-xcui-control-audit-20260905-133921-8541d6f1` ran once. **XCTest passed in 792.825 s;
the complete runner failed device correlation.** No automatic retry or additional campaign
shard followed. This is development evidence, not a frozen or signed-candidate campaign.

| Take | Observed outcome |
| --- | --- |
| `custom-001` — short English / Aiden / Neutral / Balanced | 2.88 s audio, Fast-QC PASS, EOS, real Play/Pause and paused scrub, verified History ownership. |
| `custom-002` — long-corpus Chinese / Aiden / Angry / Consistent | 18.80 s audio, EOS, real Play/Pause and paused scrub, verified History ownership; Fast-QC **warning**, one excess cadence pause (5 observed / 4 expected), longest interior pause 834 ms. Not promotion-quality PASS. |

The same exact seed was retained across both requests; receipts report **cold for both** and
`retryAttempt: 0`. Both captured thermal envelopes were nominal; peak physical footprints were
1,923.690 and 2,275.940 MiB, minimum headroom 4,220.310 and 3,868.060 MiB, respectively.
Sampler memory coverage was 100% with no capture failures; the collected crash delta was empty.
No new hard whole-output QC rejection occurred. Chunk-local silence flags remain in the complete
report and must not be confused with the whole-output verdict.

Ten contiguous observation attachments include the original selections, early generation IDs,
terminal player/History evidence and final restoration. The second run-owned History row was
deleted after identity verification; the first remains an explicitly identified seed carrier.
Original Studio drafts/selections and variation were restored by the lane. This does not erase
older forensic residue or establish blanket cleanup of every prior campaign.

### Remaining RF-07 / AV-09 gaps exposed by this run

- `validate_device_evidence` requires warm coverage among ordinary rows in each invocation, so
  this two-row shard labels the cold second row `PRODUCT_FAIL` with the sole issue
  `missing_observed_warm_coverage`. This is missing coverage, not proof that synthesis failed.
  The required warm cohort is still absent; neither a PASS receipt nor row order can invent it.
- `run.json` correctly records failure/exit 1, but `control-audit-summary.json` reports a passed
  UI shard and `required-steps.json` says passed because device correlation is registered optional.
  Preserve all three originals. Make generation correlation required and keep overall, per-row
  and coverage outcomes consistent before treating another shard as qualified.
- The attachment manifest contains ten JSON observations and **no generation PNGs or WAVs**.
  `generation-custom-*` evidence labels are not screenshot files. Structured player actions are
  genuine evidence, but cannot support a screenshot/layout review or retrospective waveform/ASR
  analysis of the deleted second output. Add actual bounded checkpoint attachments and retain
  warning evidence through the existing lane; do not reconstruct missing observations.

The next bounded correction belongs to existing RF-07/ICA-18/AV-09: separate per-take agreement
from campaign warm-coverage obligations, prove a genuine warm cohort without hidden state,
retain warnings as non-promotion evidence, and enforce required correlation/artifact availability.
Use retained fixtures first; no engine memory, sampling, seed or QC change is justified here.
**Do not resume this run at `custom-003`:** its failed correlation is explicitly rejected by the
current resume validator. Both attempted rows remain represented, with **199 unscheduled**;
they are not a completed or passing 201-take campaign. RF-11 remains gated by RF-07 and RF-09.
Previously completed inventory, stateful, external, layout, performance and VLR phases were not
rerun merely to produce another green subtotal. Signed-candidate and original-script-only work
remains blocked on its existing prerequisites.

Artifacts are pinned under ignored `build/artifacts/ui-tests/ios/<run-id>/`: original `.xcresult`,
ten attachments, observations, engine/app telemetry, plan, correlation, summaries and crash delta.
Observation SHA-256: `b8fed7d82686b978da85cdc8a971574482b6600ef4684d6816ab04fbf03d8423`;
correlation SHA-256: `914e9bbc8ec18cbd9948d0b5a81367a84e247b81968cb372c444dbc03eb72eb6`.

Screen protection is separate: inspection `ios-xcui-screen-protection-20260905-133538-aa7372f6`
showed French **Jamais** and Always-On **Non**. Final enable run
`ios-xcui-screen-protection-20260905-135518-6bf1f906` passed in 32.590 s with runner collection
and retention PASS; its readback screenshot visibly confirms **3 minutes** and Always-On **Non**.
No device UI work follows that final action. At 13:59 UTC, the separate read-only CoreDevice
observation returned `passcodeRequired: true`; the phone is confirmed locked, not merely configured
to lock. Both raw lock observations remain untracked in the enable-run directory. Its retention
report confirms all three current-session bundles are explicitly pinned. AGENTS.md was reviewed;
its existing source-binding, failure-retention and screen-protection procedures remain accurate.

## September 5 ordered host follow-up

The requested five host priorities were advanced in order. **No iPhone interaction, new synthesis,
model download, account mutation, release tag, upload or publication occurred.** The phone's
previously verified French three-minute Auto-Lock setting remains untouched. RF-06/08/09/10/02
retain their independent closure gates; diagnostics and preparation are not candidate acceptance.

### 1–2. Resource measurement and independent decoder

The exact retained 1,347-frame French trace was decoded, not regenerated. The repeat Mac
experiment added Apple's exact-PID physical-footprint observations to the previous RSS-only
measurement. Peak footprint was **5.194 GiB**, versus **766 MiB RSS**; host swap grew **1.580 GiB**.
The process exited normally after 32.75 s, but resource qualification failed. RSS alone had hidden
most of the charged residency. The existing replay loads the full TTS model, not just the decoder;
this measurement does not prove an allocation leak or isolate a retaining owner. Do not change
production memory policy from this result or sum RSS and footprint.

An independent CPU implementation uses the official Qwen tokenizer source at
`022e286b98fbec7e1e916cb940cdf532cd9f488e`, the receipt's exact tokenizer weights, and the existing
operator-local PyTorch environment. It loads only decoder parameters, strictly matches the state
dictionary and computes float32 from the installed fp16 weights. Source/configuration/binary/weight,
trace, take, script and output digests are retained. No new model or runtime was acquired.

| Experiment | Resource outcome | Audio result |
| --- | --- | --- |
| Full-TTS Mac replay with footprint probes | 5.194 GiB peak footprint; swap growth; unqualified | Prior gross gap reproduced; not another generated take |
| Official CPU decoder, default 300-frame blocks | 5.720 GiB footprint observed; explicitly terminated at the provisional ceiling; no audio | Retained failure, not a completed decode |
| Official CPU decoder, 25-frame blocks / 25-frame left context | 2.034 GiB footprint, 2.096 GiB RSS, 42.95 s, no swap growth, before/after pressure clear and recovery qualified | 107.76 s decoded; **11.997 s interior gap starting at 6.053 s** |

The independent raw float output and rounded PCM16 WAV show the same 11.997 s gap. A bounded
one-second reader applies the production silence floor of 0.001; the original iPhone WAVs produce
the exact existing 12.817 s / 6.074 s measurements under that reader. This is diagnostic silence
measurement, **not a fabricated production AudioQCReport or audio PASS**. All 12 original artifacts
remain hash-identical. Official overlapping-block decoding is independent of Swift's streaming
implementation, but is not a whole-sequence decode. The substantial waveform/energy differences
remain explicit; float precision, scheduling and shared tokenizer weights are not independently
eliminated. The same codes reproduce a gross failure without iPhone UI, publication, limiter or
Swift streaming ownership. This supports preserving rejection, not a speculative source repair
or a claim that every sampled-output/quantization question is solved. RF-06 remains open.

The separate Chinese EOS/trailing-silence and long-form token-limit cases remain at their recorded
evidence gaps. They were not retried or conflated with this trace. Stop expanding this diagnostic
until a specific remaining causal question justifies another experiment.

The narrow supervisor correction enforces sampled RSS and optional exact-PID footprint ceilings,
terminates/awaits its owned child on measurement failure, and labels older RSS-only reports
distinctly. Eleven focused fixtures pass, including real child termination, missing/invalid probe
failure, exception cleanup, ceiling equality and legacy behavior. No production synthesis or
memory threshold changes. Existing cache identities bind the changed supervisor source.

Evidence roots under ignored `build/artifacts/diagnostics/macos/`:
`replay-resource-20260905-01`, `independent-codec-20260905-01` (failed default schedule), and
`independent-codec-20260905-block25`. The comparison digest is
`f8a96dcb2fbd7ef65f33baf5bebe3fecb51e7cea893ec0a8dbb05f6286d81e43`;
the successful decode's resource-report digest is
`082c077c360a2914e5d2ecd49c706dac2c0eb3bd084f896df952603aa627d36e`.
These are operator diagnostics with exact artifact binding, not promotion records. No benchmark
PASS was published. Preserve the original interrupted result as well as its host terminal summary.

### 3–4. Candidate preparation and signed-package boundary

The checked commit `a11cfa88` has successful `CI required`; Swift CodeQL/Security was still running
at the recorded read. No 3.0 tag exists. The current patch needs its own deterministic checkpoint
and exact-SHA checks before candidate freeze. The release-source validator remains fail closed.

The release-notes check first failed because `docs/releases/v3.0.0.md` did not exist. Curated
**unpublished candidate** notes now pass that check and explicitly describe delivery migration,
preservation/import/CLI changes, outstanding audio failures and unperformed candidate acceptance.
Stable public links remain 2.4.0; no new performance improvement is claimed. The CLI/package,
release-source and promotion fixture selection passes **52 tests**. Existing model-free copied-CLI
proof is retained rather than rerun as if it qualified real inference.

Local Keychain inspection found one valid identity each for Apple Development, Apple Distribution
and Developer ID Application. The retained Mac app has a Developer ID signature, but there is no
matching command-bound release-evidence/verification bundle in that distribution directory.
It is not the current qualified 3.0 candidate. RF-10 actual signed/notarized app/CLI smoke,
three-mode generation, two-item batch, cancellation and packaged coexistence await the governed
candidate. Do not generate a substitute ad-hoc package or relabel development evidence.

### 5. Apple and qualified-decision packet

The existing read-only `asc` 4.11.0 inventory authenticated successfully. Complete pagination
found no collision for **3.0.0/build 24** (not a reservation), one iOS version record and **zero
matching 3.0.0 versions**. The current localization's Support URL exactly matches the contract;
the deployed URL returns HTTP 200 with the configured contact. Support and attribution contracts
pass. App Store Connect still reports `USES_THIRD_PARTY_CONTENT` and no submitted review.
The inventory remains **INCOMPLETE**: pricing/availability is unavailable, configured-version
readiness cannot be read, and App Privacy publication, agreements/financial, DSA and regional
checks still require owner/web evidence. This is not an authentication failure or a readiness PASS.

Sanitized results are under ignored `build/artifacts/app-store/rf02-20260905-readonly/`.
The existing [content-rights packet](reference/content-rights-review.md) now consolidates provider
metadata/retention, privacy labels, content rights, age rating, export and regional decisions with
owner classes and acceptance records. Qualified decisions cannot be supplied by the agent;
ASR-02/04/08/10/11 remain authoritative. Neither existing attribution nor the truthful account
declaration is legal clearance. No automatic metadata update or agreement acceptance occurred.

Verification: the combined supervisor/account/package/source/promotion selection passed **72
tests**. `scripts/dev.sh checkpoint` passed derived refresh/validation, the full quick project-input
gate (1,506 Python tests across both discovery roots), the generic physical-iOS SDK app/logic
builds and macOS deterministic tests. Native run `mac-test-20260905-091356` passed **578 core,
19 transport and 109 runtime tests**, with two optional AudioSeal fixture tests skipped and no
failures. The fixture-generated UI/performance reports are not new live frontend evidence.
No phone, app UI campaign or release artifact qualification ran as part of that checkpoint.

Next safe work: obtain exact-SHA security/source authority and
explicit candidate workflow authorization, then qualify actual packages under RF-10. Keep the
three RF-06 audio cases open at their precise boundaries. Phone-bound RF-07/11/12 remain deferred.
AGENTS.md was reviewed; no durable workflow change is needed.

## September 5 phone-independent codec checkpoint

**No phone interaction. RF-06 remains in-flight; no production synthesis, prompt, model,
sampling, seed, token-cap or QC behavior changed.** The existing `vocello bench` diagnostic
command now replays an authenticated collected startup-reliability take on the Mac. It validates
the original take digest, trace bytes, complete 16-group code shape and contiguous chunk ranges,
then authenticates every installed file against the pinned production catalog. Source and local
installation manifests are retained as separate identities, not presumed byte-identical.

The first preflight in `codec-replay-20260905` stopped before model loading because it incorrectly
required equal installation-manifest digests. The local manifest has an older revision and
installation timestamp; all **14 actual model files match the current catalog bytes**, including
the exact receipt tokenizer. The corrected run retains both manifest identities and the catalog
binding. The failed preflight remains unchanged, not converted to PASS.

`codec-replay-20260905-catalog-bound` replayed the retained 1,347-frame French streaming trace:

| Schedule | iPhone / Mac gap | Whole-clip relative PCM RMSE |
| --- | --- | --- |
| Original incremental boundaries | 12.817 s starting at 6.074 s on both hosts | 1.23% |
| Production non-streaming, 25 frames | 12.817 s starting at 6.074 s on both hosts | 1.03% |

Both outputs are 107.76 s and fail unchanged mandatory QC. Historical `full` replay calls the
production non-streaming **chunked** decoder, not an independent decoder or whole-sequence pass.
The Mac report names this schedule explicitly. This excludes an iPhone-only origin for this gap,
not a common-decoder defect versus pathological generated codes. PCM bytes differ; equal silence
boundaries are not waveform identity. The retained warm take has identical codes/ranges and does
not count as another executed Mac take. All 12 original iPhone artifacts remain digest-identical.

The replay itself completed in **30.61 s**; its separate resource envelope **failed** because host
swap grew **1.73 GiB**. Peak sampled process RSS was 631.83 MiB, post-exit free-memory recovery
passed and before/after pressure flags were clear. RSS is not total MLX/Metal physical footprint;
these facts do not qualify generation memory or attribute all host swap to the child. The serial
runner stopped before the second distinct 571-frame trace. No hidden retry or heavy follow-on
qualification was performed. The PCM comparison uses a bounded one-second buffer and no model.

Retained long-form telemetry independently confirms the existing 2,048-code limit was reached.
Without that attempt's codec/WAV capture, its overrun cause remains unknown; no cap increase or
seed replacement is justified. The previous device checkpoint and its failed rows remain valid
history, not current-source acceptance.

Evidence stays ignored under `build/artifacts/diagnostics/macos/codec-replay-20260905*`: original
source snapshot, take/trace hashes, per-run resource reports, replay WAVs and
`cross-host-comparison.json`. Its replay report digest is
`5c15ad63e6bb6ee6d6ca95557485afa22186137c293d7e12749c6579e0ffedde`.
The existing replay test class now has **12 passing tests**, including three new corruption,
shape and source-binding cases; the optimized 3.0.0 CLI build passes. The coherent checkpoint
passed all **1,500 Python tests**, generic iOS app/logic SDK builds, and `mac-test-20260905-081829`:
**578 core, 19 transport and 109 runtime tests**, with the existing two optional AudioSeal skips
and no failures. The first broad gate found three freshness failures after a late evidence-link
edit made the generated roadmap stale; its log is retained, regeneration corrected the input,
and the complete unchanged-tree rerun passed. AGENTS.md remains accurate; no new durable rule
or alternate harness is needed.

Model-free copied-package follow-up uses the existing `cli_package.py` stage/seal/verify/smoke
route after the source commit, with a spaced payload path and unrelated working directory.
Its local report belongs under `build/artifacts/macos/release/host-codec-verified-20260905/`.
This is not signed-candidate or generation qualification. The diagnostic master-gate refusal
already passed without a model launch. Verification logs are retained under the existing ignored
`build/artifacts/macos/host-codec-verification-20260905/` root.

Next: retain this bounded result, investigate resource qualification before another heavy run,
and obtain an independent decoder comparison of the same codes before changing production.
RF-09 freeze, RF-10 actual signed/notarized package acceptance, account/rights decisions and
RF-11/RF-12 physical-candidate acceptance remain separate. The phone stays untouched and its
previously verified French three-minute Auto-Lock setting is unchanged.

## September 5 physical-device checkpoint

**Device work has stopped; the 201-take release campaign is not complete.** All current results
remain development evidence, not signed-candidate acceptance. `RF-06`, `RF-07`, `RF-09` and
`RF-11` retain their gates. The earlier September 4 seven correlated passes, one product failure,
and five additional unverified engine attempts are unchanged. No failed row was retried or given
a replacement seed. Failed and successful bundles are explicitly pinned under the existing
ignored artifact roots; the roadmap remains the work-status authority.

### Evidence and fixes

Run IDs below are complete and source-bound; a PASS subtotal does not qualify the whole campaign.

| Run | Result and remaining boundary |
| --- | --- |
| `ios-xcui-control-audit-20260905-075120-6f36dd81` | Two scheduled generation cells; first fully correlated PASS, second QC-passing output without qualifying playback/restoration. Failed run retained. |
| `ios-xcui-control-audit-20260905-081153-b20f419d` | Inventory: 41 PASS, one onboarding NOT_APPLICABLE; restoration and required steps pass. |
| `ios-xcui-control-audit-20260905-083404-9ce8a457` | Two scheduled cells: one PASS, one typed player PRODUCT_FAIL; restoration passes. Later failure timing is not proof the original product classification was wrong. |
| `ios-xcui-control-audit-20260905-085144-fa4e6ef1` | Two scheduled cells: first playback/History PASS, second mandatory-QC PRODUCT_FAIL; restoration passes. Chinese output reaches EOS at 98 s with 86.392 s trailing silence, not token-cap termination. |
| `ios-xcui-control-audit-20260905-090509-93f1dd47` | Stateful: seven PASS, three prerequisite blocks, two preservation-policy blocks; restoration passes. |
| `ios-xcui-control-audit-20260905-091000-5f58d6ec` | External: three PASS and one permission-preservation block; restoration passes. |
| `ios-xcui-control-audit-20260905-094217-25466c27` | Corrected layout: two aggregate PASS, restoration true, all four layout screenshots directly reviewed. |
| `ios-xcui-perf-20260905-091655-27a05a63` | Nine performance bodies, validation, crash delta, publication, retention and required steps PASS. |
| `vlr-device-20260905-closure-01`, `vlr-device-20260905-closure-02` | Two distinct 14/14 PASS closures; exact receipts and zero retries. Not calibrated pitch/identity qualification. |
| `ios-xcui-smoke-20260905-101844-8467a386` | Physical journey PASS (241.820 s), layout walk PASS (288.146 s), long-form journey FAIL (224.010 s). No full smoke PASS. |

The three generation pilots each leave **199 unscheduled cells**, plus separately classified
aggregate controls. Their seeds and source identities differ; do not merge them into one
accepted campaign. Only a short take proves all observed playback/scrub/History actions in each.
The first pilot's unproven restoration and test-owned carrier/performance fixture residue remain
explicit; no unrelated user History, Saved Voice or canonical model cleanup is authorized.

Performance probe coverage is 97.45–99.93%, with fair thermals throughout the nine scenarios.
The exploratory generation scenario has a 1,204.15 ms maximum main-loop gap; its passing lane
status is not a claim of universally smooth generation or fully qualified generation memory.
The existing synthetic History/scrubbing fixture and cleanup limitations remain explicit.

**F-23:** an explicit Play after stream finalization could follow the automatic-drain policy,
using queued duration rather than the position actually heard, and depend on Auto-play.
`AudioPlaybackResumePolicy` now owns explicit intent: resume currentTime, restart at end, reject
invalid duration. Four deterministic fixtures pass. Shared macOS/iOS implementation and short
iPhone UI proof do not replace long-clip or packaged-Mac acceptance.

**ICA-19:** the largest Settings tab displayed an ellipsis despite automated PASS in
`091306-ff4aaa5a`; adding XCTest `.textClipped` also passed in `093556-95b02139` while the visual
defect remained. `TabDock` now measures the real title width and falls back to icon-above-title.
Default, AX-L, AX-XXXL and pseudo-AX-XXXL screenshots in `094217-25466c27` are readable without
overlap. Narrow defect closed; ASR-12's complete candidate accessibility gate stays open.

**RF-06:** `ios-startup-reliability-20260905-082230-4cc4a107` is a complete **diagnosed failure**,
not audio PASS: three of three exact French attempts reject with QC. Cold/warm streaming traces
match at 1,347 frames/107.76 s; full mode produces 571 frames/45.68 s. Both replay decoders
reproduce each trace's gap. This excludes an incremental-only/UI/final-writer origin, not a
common-decoder/platform-numerics problem versus sampled codes. The modes have different text
conditioning, so differing generated codes alone do not establish RNG corruption. Twelve
artifacts were digest-verified and collected before scoped device cleanup. The earlier oversized
JSON run `ios-startup-reliability-20260905-074425-0476c238` remains failed; compact serialization
now fits the existing bound and a 240-chunk fixture verifies it. No audio/QC policy changed.

The independent Chinese pilot's rejected WAV was not mirrored under its registered iOS run ID.
Shared gated run-ID resolution now binds capture and mirroring, rejects conflicting/invalid IDs,
and has deterministic digest/corruption/retention tests. The original `not-bench` artifact is
retained, not reparented or represented as recovered evidence.

**VLR-07:** each new closure has eight transcript-backed Clone and six French Design cells.
The first twelve WER values are zero; both long Design rows have WER **0.051282** and CER
**0.034826**, within existing limits. Corresponding results match both new runs and the
September 2 closure exactly (paired delta zero). Current on-device recognition succeeds for
reference A and returns `lowConfidence` for B with permission authorized; reviewed stored
transcripts are unchanged. This does not prove the original historical recognition cause,
pitch/speaker fidelity, or resolve the old 122-row characterization/evaluator disagreements.

**Final smoke failure:** first long-form segment `22B3D434-069C-4E86-AE4B-652A87A222C2`
has a truthful Aiden/English/Consistent receipt for 859 characters. It reaches 2,048 generated
codes and 293 decoded/published chunks, then fails at 128.557 s before final audio acceptance.
Peak footprint is 2,578.534 MiB, minimum headroom 3,565.466 MiB, zero capture failures/missed
deadlines, healthy memory band, but **serious thermal state**. The grouped History and segment
regeneration assertions were never reached. Codec/WAV capture was not enabled for this attempt;
random alphabetic test ownership text and thermal load are confounders, not proven causes.
No retry, seed substitution or cap change was made. Device generation stopped at this boundary.

**AV-09/RF-07 collection repair:** the runner exited on failed XCTest before the required smoke
diagnostic pull. Supplemental telemetry was recovered separately, hashed, and its existing
memory-pressure validator passed; original failed XCTest/missing-step status is unchanged.
The production-stanza regression reproduced two missing-collection assertions. Collection now
precedes aggregate exit, preserving XCTest failure even when the diagnostic subset passes.
Six outcome combinations and all 35 adjacent tests pass. No new harness was introduced.

### Verification and safe resume

Pre-documentation source verification: `mac-test-20260905-060529` passed **575 core, 19 transport,
109 runtime** tests, with two optional AudioSeal fixture skips and no failures. The full project
gate passed **1,497 Python tests** in 121 modules; macOS app build passed. A simultaneous CLI build
timed out on the shared package-store lock held during iOS XCTest; its failure is retained.
The serial optimized CLI build subsequently passed and reports `vocello 3.0.0`. Generic iOS
app and logic SDK builds passed without contacting the phone; website contract/accessibility,
production build and both wide/narrow browser checks passed. The first post-documentation gate
caught the combined AGENTS.md size budget; duplicated wording was condensed without removing
safety rules. Surface coverage and the final full project gate pass: **1,500 Python tests** in
121 modules (107 standalone plus 1,393 discovered), zero failures. Derived artifacts validate;
the existing 64 documentation-freshness and 144 roadmap warnings remain advisory, not silently
cleared. Final source/docs bytes receive the exact-content quick commit gate. No tag, upload,
App Store change or publication is authorized by this checkpoint.

Final screen-protection run `ios-xcui-screen-protection-20260905-104057-686c28fa` passed the
French Settings route and persisted **Verrouillage auto. → 3 minutes**. Its readback screenshot
also shows **Écran toujours allumé → Non**, already configured and not changed. XCTest returned
to Home; independent CoreDevice lock-state queries report `passcodeRequired: true` while
`unlockedSinceBoot: true` (the latter is historical, not a current-unlocked indication).
No device UI runs follow final protection. Raw lock/device evidence remains untracked.
The legacy probe inferred current lock from `unlockedSinceBoot`; replaying its original mapping
against the observed field shape reproduced two false-unlocked assertions. The corrected shared
parser uses typed current `passcodeRequired`, leaves malformed/missing values unknown, and all
nine offline device-state tests pass. No additional phone interaction was needed for this fix.

Next, in order: finish the coherent host checkpoint and commit/push; inspect retained exact
French codes and long-form request evidence without speculative engine changes; require a new
source-bound bounded playback/generation pilot after thermal recovery before scheduling the
full 201-take campaign. Do not resume a historical cursor across source changes or silently
repeat its failed cell. Existing MD-3/ICI closure stays historical; no unrelated model downloads.
Signed-package, account, privacy/rights and candidate acceptance remain separate gates.

Evidence roots: `build/artifacts/ui-tests/ios/`, `build/artifacts/ios/voice-reliability/`,
`build/artifacts/diagnostics/ios/startup-reliability/`, and the untracked
`build/artifacts/diagnostics/ios-session-20260905/` supplemental/hash/resume bundle.
The final diagnostic source identity is
`1db9f37d1496f31d302348074676168fb62a06860231c043b5a396a524201e7b`;
perf uses `8946c11ba6c41b1192643df9c5db736502ca4c12e11b41ca5cd44161a7691caa`.
Neither can become final candidate evidence merely by updating this document.

## Resume here (2026-09-04)

This preserved anchor contains earlier checkpoints. The September 5 physical-device checkpoint
above and `config/roadmap.json` supersede its next-action statements.

**Latest repair (2026-09-05): profile publication and CLI Clone warm-state accounting are corrected.**
Production-producer regression fixtures reproduced the schema-v3 retention rejection before the
fix. The validator now accepts the existing v2 and v3 retention contract, preserving quality,
digest, exact-PID, path, completeness and corruption checks; no schema downgrade was introduced.
New profile `mac-cpu-profile-20260905-045133-ea3bfd91` completed two Built-in takes with QC pass,
8,349 exact-PID CPU samples and 157 correlated signposts, then published schema 3 and removed only
its own raw trace after validation. Its compact summary/record remain; the original failed
`mac-cpu-profile-20260905-035610-672805f1` is pinned and its raw digest is unchanged.

Ordinary CLI Clone now awaits model loading before its warm-only matrix, without a hidden
generation; unload failures propagate. The retained-memory protocol deliberately keeps its first
Clone take cold. Publication rejects planned/observed/backend/receipt warm-state disagreement.
Those counterexamples were also red before repair. New fixed-seed run
`clone-warm-repair-20260905-045240-e3a6fcbe` completed exactly two 7.2-second takes, with seed
19790615, zero retries, passing QC and agreement across all four warm-state surfaces. The
canonical publisher verified unchanged source; all three Speed model inventories and the copied
fixture match their before/after digests. An auxiliary post-run readback initially sought the
manifest in the wrong directory and used an unfiltered fingerprint including generated registry
files. That failure is retained separately; read-only verification of the actual frozen per-run
artifacts succeeded without repeating audio or replacing the original terminal record.

All 140 focused benchmark/profile/CLI tests pass, and the optimized CLI builds. Both new records
remain exploratory `passedWithWarnings` for the existing routine soft-trim warning, not public
promotion evidence. RF-10 retains the UI responsiveness warnings, unresolved version-to-version
speed attribution and signed-candidate work. No synthesis, marking, tokenizer, prompt, seed,
sampling, QC or memory policy changed. Raw repair evidence/readback and final verification log:
`build/artifacts/macos/benchmark-repair-20260905/`. AGENTS.md was reviewed; its durable procedure
needs no change. The performance/MLX review did not identify a justified decoder optimization;
do not describe these measurement repairs as a generation-speed improvement.

**Previous follow-up (2026-09-05): the fixed-seed marking comparison is complete; retain marking and fp16.**
The existing optimized CLI ran 64/64 successful Speed/long takes across four fixed seeds and all
three modes, alternating marking-on/off order. All 32 pairs matched model-facing request identity,
token count and duration; repeated PCM was identical within each arm. Actual receipts classify
the first Clone take as cold, so it is excluded from warm statistics. Mean warm synthesis-time
changes with marking were −0.08% Built-in, +0.20% Design and +0.33% Clone; four seed blocks are
exploratory, not proof of zero overhead. Mean added completion times were 1.112/1.633/1.241 s.
Marking was 99.52% of finalization at the pooled median; final QC remained a few milliseconds.
All 32 marked takes passed the existing within-take peak check. Sampling had zero failures/missed
deadlines, nominal thermals and no non-routine memory events. The three Speed catalogs' files,
test-owned Clone fixture, frozen source and binary were verified unchanged. No production policy,
model, prompt or source change was made by this investigation, and no take was retried.

Separate CPU/signpost capture `mac-cpu-profile-20260905-035610-672805f1` completed two QC-passing
takes and validated exact-PID correlation, but the runner **failed at history publication**:
`benchmark_history.py`'s then-current retention guard accepted only schema 2 while the profile producer emitted
schema 3. Preserve the failed run; do not downgrade, replace it with PASS, or repeat the audio.
The retained capture localizes warm CPU work primarily to MLX evaluation, not WAV writing, but
does not isolate GPU decoder precision costs or justify a source optimization. It is excluded
from speed statistics. RF-10 owns the now-verified repair above and existing UI/
candidate gaps. The prior 2.4 comparison remains unmatched; this is not a new version-to-version
benchmark. Ignored report and exact evidence: `build/artifacts/macos/generation-speed-paired-20260905-033641/report.md`.
All generators/profilers exited. AGENTS.md's procedures remain accurate; no new harness or release
gate was introduced.

**Previous follow-up: the macOS editor's measured foreign-string hotspot is corrected; broader
responsiveness warnings remain open.** `ScriptTextState` materializes exact native UTF-8 once per
AppKit edit, caches the synchronized value, and keeps native binding echoes from rewriting the
editor. The coordinator refreshes its current binding; counting occurs once per render. Four new
value-boundary tests and four request-factory tests passed. No request language, delivery, seed,
model, memory/QC policy or iOS behavior changed. These fixtures do not claim full live IME coverage.

All live follow-up checks completed on one frozen working-tree source identity (not a signed
candidate): one profiled nine-scenario diagnostic, three uninstrumented nine-scenario runs
(27/27), seven smoke journeys including a 12-segment project and two-item batch, then the canonical
11-take retained-memory sequence. The profiled run is excluded from timing comparisons. Typing,
navigation and menu warnings remain 3/3, with one additional idle outlier retained. Typing median
excess main-loop time was 685.703 ms/s; its 466.996–686.755 range overlaps the prior baseline and
does not establish a short-typing improvement. Sidebar/menu CPU traces contain substantial
XCTest/AX work without a localized product-only cause, so neither a speculative rewrite nor a
threshold change was made. The long-script trace now attributes 0.006% of main-thread sample
weight to draft equality (earlier trace 29.42%); this is not an equivalent wall-time speedup.

Smoke `macos-xcui-smoke-20260905-022944-40e2d991` passed 7/7: 651.4 s joined audio in 394.0 s
generation/QC/assembly wall time, 1.65× audio/wall throughput, 2925.0 MiB diagnostic engine peak.
The synthetic entry step was 549.72 s versus 902.61 s previously, with different profiler loads;
do not present that difference as isolated production speedup. Its +248.5 MiB segment-end growth
is a duration-correlated diagnostic, not a leak finding. Segment regeneration was not invoked.
`mac-memory-qualification-20260905-025522-110bccc2` passed 11/11, retention and marking gates:
maximum within-mode growth **3.890625 MiB / 0.047493% of host RAM** versus the unchanged 5% bound.
Every take recorded zero pressure signals, memory warnings/exits and capture failures. The
`memory.pressure.soft_trim` warning remains: review of all 29 prior UI takes traced it to routine
`post_generation_cache_clear`, not an OS pressure event. No cleanup or warning was disabled.

The first smoke command rejected an unsupported `--label` before launching any test; the error
and separately corrected command remain recorded. No failed UI take was retried. Follow-up raw
evidence, source/binary hashes, per-run comparison and report are under the ignored
`build/artifacts/macos/ui-followup-20260905/`; benchmark records are repository-generated.
RF-10 remains planned for RF-09 and signed app/CLI qualification; the warnings are not waived,
and these results do not establish blanket optimization, leak freedom, French pinned-seed parity,
segment regeneration or candidate promotion. `scripts/dev.sh checkpoint` passed: derived refresh
and validation, 1,487 Python tests, generic iOS app/logic compilation, and the macOS native suites
(568 core, 19 transport, 109 runtime; zero failures, two optional AudioSeal fixtures skipped).
The optimized app also compiled for the live XCUITest runs. All test-owned app, engine and
profiler processes exited; the retained run artifacts and diagnostic History were not erased.

**Prior baseline: autonomous macOS UI/resource campaign on `14dc148c` (3.0.0/build 24).**
The requested development-build QA ran serially on the canonical M2/8 GB host, through the existing
XCUITest lanes only: standard smoke 7/7, localization/navigation 1/1, extended smoke 7/7 with a
12-segment long-form project, one excluded perf warm-up plus five counted nine-scenario runs
(54/54 interactions), and the full 29-take Custom/Design/Clone benchmark. All ten runners and
required-step ledgers passed; no failed test was automatically retried. The benchmark correlated
all 29 app/service/engine attempts, with all audio QC passing and zero transport gaps or underruns.

This is **not a clean performance verdict or signed-candidate acceptance**. Typing, sidebar
navigation and delivery menus exceeded warn-only ceilings in all five counted runs. Median
typing excess main-loop time was 622.869 ms/s (60 ceiling), navigation worst gap 768.49 ms
(340 ceiling), and menu worst gap 169.64 ms (140 ceiling). These are cadence proxies, not
compositor FPS. A valid exact-PID 20.5-second long-text Time Profiler/Hitches capture attributed
29.42% of main-thread sample weight inclusively to whole-draft equality; this localizes work to
investigate, not a completed source fix or proof for every shorter typing window. Native SwiftUI
graph captures failed bounded collection/readability checks and remain retained as failed tools.

Generation memory was `qualifiedWithWarnings`: maximum time-aligned app-plus-engine footprint
3,323.2 MiB (3.25 GiB), 100% sampler/alignment coverage, zero capture failures, application memory
warnings, pressure-signal events or exits, and nominal thermal state. Every take retained one
`memory.pressure.soft_trim` warning. The 12-segment diagnostic showed +167.6 MiB segment-end
growth, not proof of a leak. Do not waive warnings or sum independent peaks/unified-memory categories.

Privacy-safe records live in `benchmarks/runs/ui-perf/macos-xcui-perf-20260905-*.json` and
`benchmarks/runs/ui-generation/macos-xcui-benchmark-20260905-012117-0b234262.json`.
All seven records are canonical: benchmark provenance explicitly excludes generated history
records, while all other tested source stayed unchanged. The warm-up is excluded from the local
aggregate. Raw results, screenshots, failed/valid traces, five-run statistics and the complete
report remain ignored under `build/artifacts/macos/ui-audit-20260904/` and the named UI run bundles.
All test-owned app/engine/profiler processes stopped. Generated diagnostic History/audio remain
retained, Clone consent may persist, and temporary Auto-play changes are restored; this is not a
claim of complete app-state restoration. No personal voice or canonical model was deleted.

That baseline identified the typing/navigation/menu costs and soft-trim qualification for the
follow-up recorded above. RF-10 retains the residual warnings and signed-candidate gap.
French/pinned-seed UI parity, segment regeneration,
real microphone/permission recovery, broader accessibility and packaged-app proof remain untested
by the baseline campaign. No phone, production source change, release, tag, upload or publication
occurred during that baseline; the editor source change belongs to the subsequent follow-up.
AGENTS.md's durable rules remain accurate; the testing guide now states the actual retained-data
behavior instead of claiming smoke leaves no persisted state.

**Previous action: focused F-21 CLI batch-admission remediation.** The external follow-up on
`78142e07` correctly identified engine-only batch fields reaching the single-take API. Extracting
the command's actual request builder and checking all three modes against the real engine policy
reproduced **18 failed assertions across six requests** before the correction. The builder now
preserves ordinary request identity/text/mode/payload/seed/variation while batch position and
progress remain CLI bookkeeping. The engine rejection guard is unchanged, with negative controls.

- **10 CLIExecutionTests and 29 package tests pass.** Partial-result/cancellation behavior and
  legacy all-success JSON remain intact. No engine, prompt, model, sampling or QC rule changed.
- The canonical CLI builds as **3.0.0/build 24**. Its complete copied development payload passed
  discovery/integrity checks and a real **two-item batch in one process**, using seed `30000005`
  and existing Speed models, from a path with spaces and an unrelated working directory outside
  the checkout. Both outputs reached EOS, retained distinct WAVs with matching finite durations
  and valid PCM, and left no unexpected outputs/staging. No model download or personal voice was used.
- The existing opt-in package qualifier now requires that batch and emits schema-v2 reports.
  It retains raw failure rows privately and fails on missing, duplicated, reordered, malformed,
  silent, truncated or leftover outputs. Legacy batch JSON lacks per-item QC receipts; this block
  claims engine acceptance/PCM integrity, not invented strict-QC or perceptual evidence.
- Ignored evidence: `build/artifacts/macos/tests/cli-batch-*` and
  `build/artifacts/macos/release/cli-batch-regression-20260904/development-batch-proof.json`.
  The development proof explicitly records dirty-tree/base-commit and diff/binary digests; it
  cannot authorize publication or substitute for the copied **signed** candidate under RF-10.
  F-21/RF-08/RF-10 retain the work; no parallel plan or broader harness project was added.

The coherent-tree deterministic checkpoint follows this focused proof. Signed-candidate/UI
qualification, account/rights and physical-device gates remain open. AGENTS.md needs no procedural
change; that focused remediation used no UI run, device access, signing, tag, account mutation or publication.

**Previous action: phone-independent preservation and lifecycle amendment implemented and verified.** The September 4
[external audit disposition](reference/engineering-audit-grounding-2026-09-04.md) remains a review
of `75ecb740`; the current working tree implements its bounded follow-ups:

- **F-18:** only staging is removed on failure/cancellation; successful replacement is a single
  rename, and Clone reference/output aliases are refused.
- **F-01/F-22:** phase/digest-bound Saved Voice recovery retains backups through secondary faults;
  an OS-backed nonblocking lock excludes app/CLI mutation and startup reconciliation.
- **F-19:** the actual macOS executor reproduced the stale-A/new-B defect (four red assertions).
  Attempt/player ownership now guards completion and cleanup; redundant unscoped cancel is removed.
  A separate late-cancel/publication test reproduced lost History ownership (one red assertion);
  a returned completed take now persists without stealing the next take's playback.
- **F-20/F-21:** owned CLI signal cancellation, explicit forced-exit distinction and full partial-batch
  row accounting are implemented. The package qualifier no longer deletes output to manufacture a
  cleanup pass. Native SIGINT/SIGTERM and two-process Saved Voice fixtures pass; copied-candidate
  qualification remains separate.
- **F-16/F-06:** completed segments gain individual History ownership before continuing; superseded
  joined outputs remain deletable. Corrupt journals retain private export and unrelated History
  readability while ambiguous project writes stay blocked.
- **VLR-07/RF-06:** missing live WAV duration now refuses verification before Speech access. Edge
  coverage is named precisely; an interior omission must still fail WER. Historical decoding stays
  compatible. This does not resolve the retained French/device accuracy cases.

The final source checkpoint passed:

- Full project-input gate: 121 Python modules, **1,484 tests** (105 + 1,379), including negative fixtures.
- macOS `mac-test-20260904-183347`: **562 core + 19 transport + 109 runtime**, zero failures;
  two opt-in AudioSeal tests skipped because their external fixtures were absent.
- Canonical macOS app and 3.0.0 CLI builds; generic physical-iOS SDK app and logic-test builds.
- Website check, including wide/narrow production-browser smoke; 35 focused localization/package
  tests and four model-free built-CLI input/error checks also passed.

Native signal tests first exposed a Swift 6 Dispatch-callback actor trap, corrected with explicit
Sendable isolation before the passing runs. The full gate caught new recovery literals; the shared
catalog now owns them, with plural validation and no baseline exemption. The first website check
could not bind its local server inside the sandbox; the authorized outside-sandbox run passed.
Staging the new Swift files changed the tracked-file health inventory; the final freshness fixtures
caught that stale summary and required a post-staging derived refresh. That failed check is retained.
Logs remain ignored under `build/artifacts/macos/tests/rf-amendment-*`, the named macOS test run,
and `build/artifacts/foundation/rf-amendment-*`. Earlier red runs are retained, not recast as passes.
AGENTS.md was reviewed; its existing durable rules remain accurate and need no run-specific edits.
No device, model acquisition, account mutation, release tag, upload, or publication occurred.
Remaining candidate/device checks retain their original owners and gates; this is implementation
and deterministic verification, not submission readiness. Blocking CLI stdin/playback/benchmark
subprocess stages are not qualified by the task-supervisor fixtures.

**Primary roadmap: `release-first-3-0-2026-09`, RF-01 through RF-12.** It is selected by
the `primaryPlan` field in `config/roadmap.json` and appears first in the generated roadmap and status command.
RF-01 reconciliation and RF-03 source request-preservation proof are complete; RF-02 account/rights
work continues in parallel. RF-04 long-form durability and RF-05 History-save visibility have source
implementation and focused verification; their referenced defects still need corrected-candidate
acceptance. The bounded amendment above now has a fresh passing source checkpoint. The remaining
milestones are not complete. Existing subsystem records retain their technical closure authority;
older active research workstreams are not the current execution queue.

**The adopted release-first programme remains the implementation plan.** Follow the ordered
[release-first programme](reference/release-first-execution-2026-09.md): F-15 macOS Design request
capture, F-16 long-form transactions, reopened F-06 enqueue recovery, bounded ICA-18 harness repair,
and F-17 downloadable CLI packaging, plus the bounded September 4 amendment, before candidate freeze. Existing ASR/ICA/VLR items retain
their authority; research and broad harness/runtime redesign are deferred. No publication is
authorized by this implementation checkpoint.

**The next release is 3.0.0, not 2.5.0**, by maintainer direction on September 4. The shared
iOS/macOS/CLI source identity is now **3.0.0/build 24**, set through `project.yml` and project
regeneration. The September 4 read-only preflight found zero matching builds with complete
pagination. This is not a reservation: repeat collision validation before archive. The live App
Store version still requires separately authorized reconciliation; no account mutation or
publication occurred.

F-15 source correction now preserves the full macOS Design draft and snapshots variation before
asynchronous startup. Production-coordinator tests and adjacent request-factory tests passed
7/7 via `scripts/macos_test.sh core-test --only VoiceDesignCoordinatorTests,MacStudioGenerationRequestFactoryTests`;
the same build-for-testing compiled the production app. The first build exposed a missing explicit
Core import, corrected before the passing run. No model or phone was used. F-15 remains in-flight
for candidate UI/engine parity; the coherent-tree checkpoint now passes.

F-16 now uses one shared bounded acceptance journal on the existing GRDB writer: unique candidate
audio, throwing manifest serialization, atomic manifest replacement, transactional project History,
and reconciliation before History reads/writes. Failed replacement preserves accepted content;
unchanged segment QC/seeds/identities survive, and iOS counts reused segments once. Long-form
continuation remains session-scoped. The 60-test focused coordinator/outbox/planning/assembly/
acceptance set passed, including pre/post-commit interruption, encoding/QC/database failure,
cleanup refusal, corruption, identity mismatch, cancellation, and old-manifest decoding.

RF-05 source work adds typed saved/queued/unable-to-queue outcomes and a visible shared Retry/Export
warning without turning successful synthesis into an engine error. Unqueued identity is explicitly
app-session memory, not claimed durable. Existing outbox recovery remains the database-failure path.
The combined 66 focused Swift tests passed, and both production apps compiled; the generic iOS
logic-test bundle also compiled. Initial enqueue fixtures incorrectly compared subsecond timestamps
against the existing outbox's ISO-8601 storage precision; fixed-time fixtures now verify exact
retained request identity. An earlier overlapping iOS compile caught new-source target membership
before regeneration; the regenerated follow-up passed. The coherent checkpoint passed all 1,436
Python tests/project inputs, generic iOS app/logic builds, and macOS core/transport/owned-runtime
suites (`mac-test-20260904-131523`). This is not candidate proof. The original numeric-dropout v2 plan and row digests remain unchanged using
a digest-pinned historical control contract; tampered/self-rehashed rows still fail validation. No physical
device or model run was started. RF-06 retained-audio review localizes custom-008's low energy
before the WAV writer. Three later fresh-process Mac reproductions of the exact request/seed all
pass: the streaming path repeats at 199 codec frames and 15.92 seconds, while non-streaming uses
325 frames and 26.00 seconds; the failed iPhone row had 1,347 frames and 107.76 seconds. The missing
device codec/WAV still prevents splitting iPhone sampling from decoding, so no prompt/QC/token-cap
change is justified.

The retained French Design long reject is now localized separately. Independent cached full-file
ASR recovered the complete French content at 3/39 normalized word edits (WER 0.077), while all
three Apple Speech passes had consistently omitted 0–8.16 seconds and
reported WER 0.565. Live verification now binds recognition timing to WAV duration and reports
`speech_recognition_incomplete_temporal_coverage` without scoring a partial transcript; the VLR
composer owns that as a harness-inconclusive result. The same serial offline full-file pass covered
all 14 successful-audio verifier problems: 12/14 meet WER 0.15 (both shipped Neutral rows, all four
no-delivery rows, and six of eight Calm rows); only two short Calm controls remain at WER 0.167.
Four of the 12 original numeric rejects have incomplete Apple edge coverage; eight have full
coverage and retain their original outcome pending evaluator resolution. Fresh current-source Mac
regeneration of the exact short and long shipped-Neutral requests passed Fast-QC, receipt parity,
and diagnostic full-file WER 0.000 for both rows. Focused Swift and Python tests pass. This does not
rewrite old results, promote diagnostic ASR, or substitute Mac evidence for device acceptance.
RF-06 remains open for exact iPhone codec capture/replay, the shipped Neutral short-row
Apple/Whisper disagreement, and fixed-source physical-device confirmation; RF-07's physical pilot
also remains.

The coherent RF-06 source checkpoint passed the full project-input gate (121 Python modules and
1,468 declared tests), generic physical-iOS SDK app and logic-test builds, and all deterministic
macOS core, transport, and owned-runtime suites (`mac-test-20260904-145600`). No physical phone or
release operation was involved.

RF-02's fresh read-only account/signing checkpoint succeeded without mutation. The local keychain
has usable Development, Distribution, and Developer ID identities; the exact remote App ID exposes
App Groups and Increased Memory Limit; and one matching active iOS App Store profile expires in
2027. The profile payload and emitted candidate entitlements still require archive/IPA verification.
The guarded inventory also confirms the existing third-party-content declaration and readable
app/version/review/age-rating surfaces. It remains incomplete because pricing/availability is not
initialized/readable, accessibility declarations are empty, and App Privacy publication,
agreements/tax/banking, DSA, regional compliance, and qualified privacy/rights decisions require
owner/web review. The formerly configured 2.4.0/build 23 is not reusable. RF-09 now selects
3.0.0/build 24 with a passing read-only collision check. Raw account responses and identifiers
remain untracked.

RF-07 now has source implementation of immediate sequenced stage attachments, explicit encoding
failure, early player identity, separately observed selections, pause/play/scrub proof, History
keyboard readiness, default five-take shards, and final ledgers on failed as well as successful
exits. Shard success is separate from whole-campaign completion. Unrepresented in-flight stages
or missing restoration stop resume instead of guessing ownership. New failure fixtures and the
generic device-SDK XCUITest build-for-testing passed (`rf07-ui-compile.log` under foundation
artifacts). This compile does not execute a test; physical pilot acceptance remains pending.
No device was contacted. RF-08's source mechanism is now implemented below; RF-09 host candidate
preparation is the current phone-independent step.

**Release-first source checkpoint:** commit `089328d3` passed the guarded project gate with all
1,450 Python tests and was pushed to `origin/main`. This records the product repairs and RF-07;
it is not exact-SHA candidate CI, signed packaging, physical acceptance, or publication evidence.

RF-08 now extends the existing release workflow with an optimized, separately signed/notarized
CLI DMG, source-bound catalogs, dependency bundles and governed notices. The managed artifact step
checks the copied folder and binds its exact DMG/source/version/build report into release evidence,
checksums, attestations and the remote asset set; historical app-only evidence stays valid.
The fresh optimized **development** CLI build and real model-free relocation smoke passed at
configured version 2.4.0/build 23: 32 inventoried files, paths with spaces, unrelated cwd,
embedded identity, JSON modes/speakers and usage failure. The first real attempt exposed absent
tool-product catalog copies; the packager now explicitly supplies the source-bound JSON and rejects
any stale built copy. The next attempt exposed normal zero-length ad-hoc signature placeholders;
only those exact resource signature paths may be empty, never shaders or required data.
The successful local report is `cli-packaging-local-20260904.json` under ignored macOS release
artifacts and explicitly cannot authorize release. Temporary payload/runtime directories were removed.
The subsequent complete ad-hoc DMG round trip also passed: the 11,969,269-byte artifact
(`ad109cb15c610d8964fc3429daac46fab9622ca2e9816b9fd2fc95b88816ca69`) mounted read-only,
copied to a path with spaces, validated 32 files/identity/linkage, ran discovery, detached cleanly,
and retained its untracked report under `rf08-cli-dmg-roundtrip-20260904`. It remains unsigned-
distribution/development evidence and performed no generation.

The same copied payload then passed the new opt-in serial generation qualifier using existing local
Speed models: Built-in English (3.28 s), French Design (7.68 s), and English Clone (4.08 s) all
returned the exact model/language identity and strict audio-QC PASS. Cancellation was issued only
after a real generation-start event and exited 130; the public invalid-mode/unknown-command exits
remained 1/2. The privacy-safe ignored report records output digests rather than paths, audio, text,
or transcripts and has no publication authority. This was the ad-hoc 2.4.0/build 23 artifact at
source `089328d3`, not a signed/notarized 3.0.0 candidate. RF-08/F-17 therefore remain in-flight for
the candidate repetition under RF-10, while the package-generation mechanism is now live-proven.
No model was downloaded or changed, and no phone, App Store mutation, signing credential,
notarization service, or publication was used.
The coherent RF-08 qualification checkpoint passed all project-input checks and 1,472 Python tests,
including 21 focused CLI-package tests plus runtime-security and supply-chain rules. The run refreshed
and revalidated the derived catalogs before recording the exact-tree commit-gate PASS marker.

The resumed qualifier now uses audio-only Clone unless supplied the actual reference transcript;
the earlier hardcoded transcript is removed. That historical Clone result proves execution/QC,
not perceptual reference fidelity. Current reports label seed/streaming as requested, require
normal EOS, preserve WAVs and atomic partial results on failure, refuse overwrite, and terminate/
await process groups on timeout. Newline-free progress cannot stall cancellation. All 25 focused
package fixtures pass. RF-09 now prepares the shared 3.0.0/build 24 identity; the full host
checkpoint and signed-candidate qualification are separate milestones. The iPhone remains unused.

**RF-09 host verification passed:** full project inputs and 1,481 Python tests (105 + 1,376),
all macOS core/transport/owned-runtime suites (`mac-test-20260904-160540`), macOS app build,
generic iOS app and logic-target builds, CLI build with `vocello 3.0.0`, and website check including
both production-browser layouts. Logs are retained under ignored macOS release artifacts in
`rf09-host-checkpoint-20260904`. The initial gate caught stable-versus-candidate identity,
version-bound attribution, and guidance-budget issues; all were corrected without weakening gates.
Existing advisory documentation/roadmap currency warnings remain, not hidden or called closed.
Public download facts remain 2.4.0; candidate identity is separately validated and unpublished.
The prepared [candidate notes](reference/release-3-0-candidate-notes.md) pass the release-notes
structure check but are not an announcement or signed-candidate proof.

**Next boundary:** commit/push the verified source/documentation checkpoint, then observe exact-SHA
CI and Security. A verified tag/signed-candidate workflow and live App Store version reconciliation
need explicit authorization; RF-02's qualified rights/account decisions remain external. After
candidate production, RF-10 qualifies the signed desktop/CLI. The next phone session starts with
RF-06 scoped codec/rejected-audio collection and RF-07's small physical pilot, not an inherited
201-take cursor. RF-11/RF-12 and the original failed/unverified device evidence remain unchanged.

**Later same-source device evidence supersedes the earlier unrun checkpoint below.** The
`065457-e2ec8911` campaign retained seven correlated passes and marker-free `custom-008`
PRODUCT_FAIL. Successor `151935-164b4ee3` failed History keyboard focus and retained five new
engine attempts without accepted UI observations. Those are attempted/unverified, not unattempted
or passing; 193 generation cells remain unvalidated. Both full run IDs and the preserved boundary
are in the programme. The failed run cannot safely resume or inherit an earlier cursor. Original
results, Staging, and 1710 exported attachments remain pinned. No phone work is active.

### Earlier September 4 source checkpoint

**ICA-18 implements metadata-only History ownership.** New schema-v3 control plans keep the
tracked corpus text unchanged; v1/v2 generation and validation remain available for immutable
historical evidence, including the exact ICA-15 numeric regression. The test compares bounded,
read-only History censuses before and after generation, requires exactly one new persisted row,
then verifies its full player transcript before pinning or deleting. Versioned observations bind
that row to the completed generation UUID, script digest, seed, and cleanup baseline. Resume uses
host-validated exact carrier metadata, never a text-only match or a new seed. Ordinary existing
History is not normalized. The deterministic checkpoint, generic iOS app/logic compilation, and
macOS core/transport/runtime tests pass; six focused ownership/resume fixtures also cover the
final multi-run and preexisting-pin safeguards. New physical proof is pending. Freeze
the final committed source before starting generation at row 1; previous-source shards cannot
resume. ICA-15 stays open, and accepted smoke/saved-voice coverage is not being blindly repeated.

**The prepared marker-removal diagnostic has now run.** With the original exact seed, Eric,
Calm Strong, Italian, and Consistent variation, all four marker-free observations pass Fast-QC:
streaming is 8.72 seconds with a 267 ms longest interior pause and 65 ms terminal silence;
non-streaming is 7.52 seconds with 140 ms and 44 ms respectively. The reverse-order confirmation
proves the same codec digest for each mode in cold and warm execution (109 streaming / 94
non-streaming frames, voluntary EOS). There was no allocation retry, crash delta, model change,
prompt change, or threshold change. This localizes a text interaction, not a general perceptual fix.

Run `ios-startup-reliability-20260904-053757-ed201aef` passed both app takes but exposed ICA-17:
the host/schema required optional cadence quantiles that Swift omits when no qualifying pause
exists. Its original runner remains failed. Corrected validation of the immutable evidence and
separate exact-run cleanup pass. Independent reverse-order confirmation
`ios-startup-reliability-20260904-054340-c307ab41` passes the entire runner, both takes, crash
collection, validation, and cleanup. The two quantiles are now optional; required fields and numeric
validation remain strict. All 83 adjacent startup/control-audit/smoke fixtures pass. A rounded seed
in the unrun preparation was restored to the original UInt64 before launch; receipts prove the
exact value, and a new fixture covers full-width launch transport.

**The same-build marker control reproduces the original failure.** Run
`ios-startup-reliability-20260904-054601-0770b988` retains both QC failures at the exact original
71-character model-facing text and seed: streaming has a 1.851-second interior gap and 11.096-second
tail; non-streaming has an 8.206-second interior gap. Its 373/547-frame traces match the historical
controls, and incremental/full replays reproduce the failures. The diagnostic runner completes
successfully with the honest `diagnosed_failure` result, no crash delta, and verified cleanup.
All six new takes are represented across three pinned local bundles; no device run remains active.

ICA-15 remains open for the original marker-bearing sampled-output failure. ICA-18 owns the
harness-only implementation and verification of metadata-based History ownership while
retaining the exact numeric failures as separate immutable stress cases. Never
strip digits from user input, replace these failures, or change production sampling/QC. The complete
generation audit has not restarted; prior shards cannot resume across source changes. Do not
repeat accepted smoke or saved-voice coverage or convert this bounded experiment into a full audit
PASS. The active [remediation report](reference/ios-control-audit-remediation-2026-08-29.md) and
`config/roadmap.json` retain the current experiment results and next boundary.

## Previous checkpoint (2026-09-03)

**Phone released before the ten-minute deadline; device work is paused.** Final smoke run
`ios-xcui-smoke-20260903-184747-dc032d1b` passed all three cases: primary journey (239.819 s),
Settings accessibility (288.281 s), and long-form with segment regeneration (336.142 s). Crash
delta passed at 19:02:42 UTC and scoped diagnostics at 19:02:44 UTC, including memory-pressure
cancellation, full unload, and successful recovery. The final required-step ledger passed with no
missing steps. Test teardown terminated Vocello; no Xcode test or device-collection process
remained when the phone was released. Remaining retention/checkpoint work was host-only.
The cleanup dry-run confirmed explicit pins for the saved-voice, generation, interrupted-smoke,
and final-smoke bundles. ICA-09, ICA-14, and ICA-16 now meet their individual closure gates;
ICA-04/ICA-05 and ICA-15 remain open. These separate-source runs are not a complete current-source
control-audit PASS.

**Smoke collection is now bounded to the current run.** Earlier run
`ios-xcui-smoke-20260903-181935-a051e519` passed all three XCTest cases (standard,
Settings accessibility, and long-form), then its legacy whole-mirror collector transferred over
365 MB of unrelated historical diagnostics and was deliberately stopped after eight minutes.
The original runner remains failed/unqualified. Its already-collected 1.6 MB current-run subtree
independently passes the unchanged memory cancellation/unload/reuse checker; this does not rewrite
the runner result. ICA-16 replaces the whole-mirror pull with the existing run-scoped, 60-second
collector. Focused fixtures prove acceptance equivalence, rejection of malformed current evidence,
historical isolation, and copy-failure propagation. The separate `184747` run supplies complete
no-retry device acceptance without rewriting the interrupted run.

**The latest current-source generation attempt is retained as a product-safety diagnosis, not a
partial audit pass.** Run `ios-xcui-control-audit-20260903-172247-b8fc963e` completed four Custom
takes and then correctly rejected `custom-005` before History publication. The exact failing cell
was Eric, Calm Strong, Italian, Consistent, with the frozen 71-character script and seed
`17323406037040967292`; Fast-QC measured a 1.851-second interior gap followed by 11.096 seconds of
terminal silence. The control-audit composer therefore reports four `PASS`, one `PRODUCT_FAIL`, and
199 `SKIPPED_AFTER_FAILURE`. No failed row was retried or assigned another seed.

Two separate four-cell physical-iPhone diagnostics preserve the failure across streaming,
non-streaming, warm, and forced-unload/cold execution. Run
`ios-startup-reliability-20260903-174346-f3006528` first exposed that the host validator had not yet
adopted Fast-QC v6 cadence and trailing-silence fields. The backward-compatible validator/schema
correction now accepts that complete retained result. Corrected-source run
`ios-startup-reliability-20260903-180139-ecb380f1` then reproduced all four failures with healthy
memory, no crash delta, complete AudioQC, and finalized model-terminal evidence. Warm/cold
streaming traces are byte-identical to each other, as are the two non-streaming traces; both the
incremental and full Mimi decoder replays reproduce their respective gaps. The 28-target-token
request ended by model EOS rather than the 2,048-token cap after 373 streaming or 547
non-streaming codec frames. The first divergent layer is therefore the sampled CustomVoice codec
sequence/continuation, not UI request assembly, memory admission, chunk publication, incremental
decode, WAV persistence, or History.

Production behavior remains deliberately unchanged: invalid audio is discarded with an explicit
retry path. Trimming, hidden regeneration, seed substitution, prompt/sampling changes, or weaker
QC would conceal rather than repair the deterministic failure. ICA-15 now owns a bounded
continuation-policy experiment that must demonstrate safety across representative valid speech
before any production budget changes. Because the diagnostic source and governed documentation
changed after the failed audit run, no retained generation shard is resumable. The next complete
control-audit generation campaign must start at row 1 on a newly frozen committed source identity.

Retained QC-PASS `custom-002` (Aiden/Chinese) used 331 codec frames for 49 target tokens; restoring
the former six-times budget would stop it at 294. A blanket rollback is therefore unsafe. The audit
also appends an eight-digit spoken History marker. A two-take marker-removal ablation is validated
and retained under ignored `build/artifacts/diagnostics/ios/startup-reliability/ica15-marker-ablation-pending`,
and was **unrun at that pause**; the September 4 checkpoint above supersedes this boundary. It keeps the failing speaker, delivery, language, seed, and variation
while changing only the marker-bearing text. It is an independent localization probe, not a retry
or replacement of the failed audit row and not evidence for a production change.

**The September 3 device continuation is preserved at its exact evidence boundaries.** Preflight
passed on the paired iPhone. Two initial runs stopped before any test launched while Xcode enabled
automation and remain separate infrastructure evidence. After unlock, saved-voice run `162649`
proved the corrected lazy-row/menu path, then exposed a harness-owned search keyboard covering the
floating tab dock. The semantic keyboard-dismissal correction was followed by complete no-retry run
`ios-xcui-saved-voice-lifecycle-20260903-164233-e71568b3`: import, automatic transcription,
enrollment, exact Clone selection, one Clone generation, saved-row preview, deletion, draft
clearing, cleanup, and runner diagnostics all passed. ICA-13 is closed.

Generation run `ios-xcui-control-audit-20260903-164806-affcc06a` then completed the first two
visible Custom takes but stopped at the ownership guard before any History mutation. The guard
compared the second long frozen script against the row's deliberate 60-character preview, so a
genuine audit row produced a false harness rejection. The corrected guard derives the narrowed row
identifier, opens the genuine read-only player, and compares its full accessible transcript exactly
to the frozen plan before cleanup, pinning, restoration, or deletion. Focused contract tests pass;
the retained failed run has no terminal observation stream and is not resumable after this source
change.

The first post-checkpoint device preflight also exposed a build-workflow ordering defect: the
incremental generic iOS build replaced the shared app binary after the earlier project-input gate
had validated its preserved dSYM, leaving the final binary and retained symbols at different UUIDs.
The incremental foundation route now preserves and UUID-validates the final sibling dSYM after both
app and logic-test builds. Its focused contract, a real incremental build, and the immediately
following device preflight all pass without cache deletion.

The next command recorded at the September 3 pause was the prepared independent diagnostic
(now completed; do not launch it again merely to update this checkpoint):

```sh
scripts/ios_device.sh preflight
scripts/ios_device.sh delivery-reliability \
  --plan build/artifacts/diagnostics/ios/startup-reliability/ica15-marker-ablation-pending/plan.json \
  --script-file build/artifacts/diagnostics/ios/startup-reliability/ica15-marker-ablation-pending/script.txt
```

Then compare retained codec/QC evidence and qualify any causal remediation before restarting the
complete generation campaign with `scripts/ui_test.sh ios control-audit --scenario generation --retain-result`.
That campaign starts from row 1 with a new schema-v2 plan on the final frozen committed tree.
Do not merge or relabel prior failures, use a cross-source resume token, repeat accepted phases
merely for a green aggregate, or remove bounded test-owned carriers without exact ownership proof.
Remaining device work includes the untested generation rows, ICA-06 exact-seed confirmation,
final cleanup/restoration, preservation-blocked recording permissions, and VLR-07's separately
governed accuracy/inconclusive evidence. Smoke and saved-voice closure no longer need a blind rerun.

**The audited macOS Clone/language parity gap is closed under VLR-10.** Saved Voices now uses
the same operation-generation transcription-review state and privacy-safe evidence builder as
iPhone, including an honest awaiting-audio state, explicit audio-only confirmation, and separate
reference-language confirmation. That metadata crosses the existing versioned XPC candidate
command, survives prepared-voice reload/replacement, and never selects the language of a later
Clone output. The macOS Clone and Voice Design coordinators now delegate request assembly to one
pure boundary whose deterministic tests prove Auto target-text routing, explicit-language
precedence, exact reference transcript/ID, prompt, seed, variation, and generation identity. No
model, prompt copy, sampling default, quality threshold, or engine behavior changed. The shared
lifecycle contract, focused Swift tests, generic iOS compile, full macOS deterministic suites, and
the quick project gate are the closure evidence; native macOS XCUITest remains explicit frontend
acceptance rather than an ordinary publication prerequisite.

**The seven-item phone-independent remediation block is complete and deterministically green.**
ICA-14 now uses source-bound schema-v2 History narrowing tokens and requires the exact full
plan-bound script plus labeled row action before any cleanup, pin, restore, or delete operation;
the exact ICA-09 schema-v1 plan retains a digest-allowlisted, byte-exact replay path. ICA-13 now reveals the exact
run-owned voice through the genuine Voices search field and requires finite, hittable, at-least
44-by-44-point row/menu geometry before activation. The retained pre-test XCUITest automation-mode
timeout was replayed as one run-level infrastructure failure with 42 skipped rows and no false
product finding. Focused fixtures and generic iOS compilation pass for all three corrections.

The retained VLR characterization is now classified at the actual evidence boundary: its 14
successful but non-accepted French rows comprise 12 product-owned output-accuracy rejections with
consistent French recognition and WER above the governed 0.15 threshold, plus two harness-owned
inconclusive rows with missing or inconsistent ASR evidence. No threshold, seed, prompt, or result
was changed. A fresh read-only App Store Connect inventory and build-number preflight again stopped
at their bounded Keychain/private-key timeouts, made no account mutation, and left no child process.
The exact working tree then passed 1,311 Python tests, generic iOS app and logic-test compilation,
all macOS deterministic suites, derived validation, and the complete quick project gate.

The subsequent September 3 device window supplied the previously missing saved-voice,
full-transcript ownership, fresh-bootstrap, and complete smoke closure evidence listed above.
The current resume sequence supersedes the earlier pre-documentation `/tmp` plan. Generation and
VLR accuracy closure remain separate, and no historical 204-row shard becomes a current-source PASS.

**The preceding one-hour physical-iPhone window closed with all device processes stopped.** Preflight
passed, then current-source inventory run
`ios-xcui-control-audit-20260902-180938-42d76c39` completed with 41 `PASS`, one explicit
`NOT_APPLICABLE`, zero failures, and zero skips. This closes the earlier voice-picker dismissal
evidence gap. Saved-voice run `ios-xcui-saved-voice-lifecycle-20260902-181739-713b7367` then
failed before preview because the run-owned imported voice row menu had an invalid activation frame
and no suggested hit point. ICA-13 now owns that unresolved harness/UI-geometry boundary. Preserve
the run; it is not a saved-voice acceptance pass.

Generation run `ios-xcui-control-audit-20260902-181849-9ea76d5a` reached its fail-closed History
correlation guard, which found reserved token `28400003` on a non-audit History row. The run emitted
no terminal observations, its summary honestly retains all 204 composed rows as
`SKIPPED_AFTER_FAILURE`, and it has no usable resume state. This is a harness-integrity finding, not
voice-output evidence. Do not resume or merge it. Localize the token collision, then start a fresh
201-take generation campaign on one new frozen tree identity. ICA-14 owns the collision-proof
History-carrier remediation and its deterministic fixtures.

Smoke run `ios-xcui-smoke-20260902-182906-25dc08ce` passed all three XCTest cases: the primary
cancellation/memory-recovery/Custom-History journey, Settings accessibility layout walk, and
long-form project journey. The maintainer's deadline arrived during the subsequent diagnostics
pull, which was cancelled immediately. The runner therefore remains overall failed/unqualified;
the XCTest result is useful partial evidence but does not substitute for the missing post-test
memory/crash diagnostics gate. The next phone window must rerun smoke to completion after fixing
the two harness blockers above. All four runs are explicitly retained, no device automation remains
active, and this documentation checkpoint requires new source-bound run IDs.

**The physical-iPhone control audit is paused at a clean pre-row boundary.** On the maintainer's
request, generation shard `ios-xcui-control-audit-20260902-153340-9092ff5d` was interrupted during
initial Studio state capture on source `c5d435ee`. Xcode and XCUITest exited, the runner completed
forensic collection, the bundle is explicitly pinned, and no generation row or audit observation
was produced. Its composed result is therefore 204 `SKIPPED_AFTER_FAILURE` rows with zero PASS,
product, harness, or infrastructure finding. It is pause evidence, not a failed product test and
not a usable row-level resume token. No device automation remains active and Auto-Lock was not
changed.

The September 2 generation attempts remain pinned and separate by source identity. Run
`ios-xcui-control-audit-20260902-141800-7d51bfe9` passed `custom-001` through `custom-003`, then
safely rejected `custom-004` for a 2.085-second interior silent gap. Run
`ios-xcui-control-audit-20260902-151248-90976475` passed `custom-001`, then safely rejected
`custom-002` for a 25.446-second interior silent gap. Neither invalid take entered History, and
neither was retried or assigned another seed. Intermediate shards isolated and corrected seed-
carrier lookup, state-aware scrubber movement, and stale History-row validation; the separate
mode-setup interruption coincided with the maintainer's phone call and is not product evidence.
Because this documentation checkpoint changes the frozen tree identity, the next phone window must
start a fresh `control-audit --scenario generation --retain-result` campaign from row 1. Do not
resume or merge these historical shards. ICA-04/ICA-05 remain in flight until all 201 takes, final
cleanup/restoration, and the required recapture phases are represented.

The same-day non-generation evidence is also retained. Stateful run `121158` completed with seven
PASS observations, three explicit delegated prerequisites, and one preservation-policy block;
external run `121608` completed three handoffs with the permission-preservation block; accessibility
run `121855` passed both required groups. Model-management diagnose `122641`, queue `123230`, and
acceptance `123603` all passed with no finding and preserved canonical model state. Inventory run
`120801` did not emit observations after its voice picker failed to dismiss, and saved-voice run
`122245` reached the preview action but never presented the player sheet; neither is acceptance
evidence. The next campaign must re-evidence inventory, diagnose the saved-voice preview boundary,
complete generation, and prove final cleanup/restoration. All named bundles survived a retention
cleanup dry run as `explicitly-pinned`.

**The corrected-source physical-iPhone VLR campaign is complete and honestly non-green.** The
read-only shared-model metadata bootstrap defect is fixed and committed. New source-bound runs
`vlr-device-20260902-closure-fixed-01` and `-02` each passed 14/14 without retry; the complete
`vlr-device-20260902-characterization-fixed-01` represented 122/122 rows with 106 PASS, two
mandatory product-QC rejections, 12 product-owned output-accuracy rejections, and two harness-owned
inconclusive verifier cases. The affected Clone Auto and explicit tuple passed in all three runs,
and its eight-seed Auto cohort passed, closing VLR-08.
Fast-QC v6 rejected the former take-112 shape before publication with the same 109.471-second
terminal tail in live, full-replay, and incremental-replay output, closing VLR-09. VLR-07 remains
open for generation/intelligibility investigation of the 12 measured rejects, decision-capable
evidence for the two inconclusive rows, and two deterministic invalid diagnostic-arm outputs. Do
not weaken the 0.15 WER rule or rerun/relabel the completed evidence merely to obtain a green count. The
privacy-safe checkpoint is pinned in
[`voice-identity-language-reliability-ios-2026-09-02.md`](reference/voice-identity-language-reliability-ios-2026-09-02.md).

**Shipping-optimization benchmark provenance and the first stable trend pair are closed.**
The governed baseline format now binds hardware, optimization, matrix, corpus, model artifact,
telemetry schema, and QC identity, and the gate rejects the former provenance-free legacy array.
Clean canonical M2/8 GB records `mac-gate-bench-20260902-013854-f39c1c91` and
`mac-gate-bench-20260902-015022-591814fe` share one comparison key; the second names the first as
its baseline and contains complete per-cell deltas with no regression. Both passed deterministic
preflight, optimized executable identity, QC, memory qualification, nominal thermals, and crash
checks. AV-05 and AV-06 are closed; their explicit soft trims remain visible in history.

**App Store installation eligibility now matches the runtime hardware floor.** Before the first
public version, the built iOS bundle began requiring exactly `arm64` and Apple's documented
`iphone-performance-gaming-tier`, while the defense-in-depth runtime guard moved to the shared
`IOSDeviceEligibilityPolicy`. Host tests, generic-iOS compilation, a retained built-plist readback,
the source contract, and signed archive/export verification all reject disagreement. ASR-01 is
closed; this deterministic evidence does not substitute for the still-pending signed archive or
physical-device candidate acceptance.

**Every phone-independent validation item has now reached its honest evidence boundary.** AV-07
has a frozen, project-gated calibration/holdout contract that binds audio and split metadata,
rejects speaker/script/translation leakage, requires multilingual length/severity coverage, and
reports 95% Wilson uncertainty; it remains open for a real independently labelled corpus. DP-28's
complete local evaluator stack and 65 focused fixtures pass, but it still has no qualified listener
labels. DP-29/AV-08 gained a clean 19/19 Mac language cohort across six languages and both Custom
Voice and Voice Design; that single cohort cannot substitute for fluent review or independent
multi-script/multi-seed uncertainty. ISR-04's 18/18 Mac/CLI sentinel matrix is complete, leaving
only exact-script and physical-iPhone arms.

Model-host evidence is stronger without overstating geography. North America downloaded and
SHA-256 verified the three largest pinned iOS files (4,024,541,635 bytes total) in constant memory;
the closure composer rejects locally relabelled regions and requires qualified fresh Europe and
East Asia executions. App Store Connect reads now run in isolated process groups that are killed
completely on timeout. The local `primary` profile still cannot perform an unattended private-key
operation, so no live account field was inferred. Read-only signing inspection found usable Apple
Development and Distribution identities and two matching development profiles, but no App Store
distribution profile for Vocello; ASR-10 therefore remains archive-pending.

**The phone-independent App Store and validation sprint is source-complete and its governed
deterministic checkpoint passed.** The exact tree passed the complete discovery-bound Python suite, generic iOS app and
logic-test compilation, all macOS deterministic suites, a production website build, and two
wide/narrow real-browser journeys. The website now has a pinned Playwright/Chromium production-build lane:
12 contract tests plus two wide/narrow real-browser journeys pass hydration, keyboard progression,
skip navigation, internal targets, and clean console/page behavior. AV-10 is closed; CI installs the
same pinned browser runtime only for website changes.

ASR-06 through ASR-09 and ASR-11 now have enforceable source-side boundaries. Eleven iOS storage
classes are machine-readable and bootstrap-applied with CompleteUntilFirstUserAuthentication;
regenerable delivery/cache/diagnostic and enrollment-transaction data is backup-excluded, while
outputs, committed voices, History, and its recovery outbox remain backup-eligible. The release
artifact verifier rejects script payloads, unexpected executables, diagnostic/developer strings,
dynamic loading, unsafe symlinks, absent third-party privacy manifests, and dSYM/UUID drift. The
iOS release workflow installs digest-pinned `asc` 4.11.0 and performs a required exact
bundle/version/build collision read before archive creation; it never invents a build number.

Anonymous North America range and full-content probes passed all three pinned iOS Speed artifacts
with exact remote catalog totals, SHA-256 identity, and allowlisted redirects. Europe and East Asia remain required before
ASR-09 closes. The reviewer notes now state exact model bytes, Wi-Fi/free-space requirements,
cancellation/relaunch/finalization behavior, offline use, and the no-substitution outage posture.
The complete App Store Connect inventory has a mutation-free, redacted nine-read contract. Its
shared runner now terminates the entire CLI process group on timeout, preventing a blocked Keychain
child from surviving the parent. The unattended `primary` profile still timed out before its first
authenticated response; no account response was retained and ASR-11 remains open alongside its
web/owner/legal checks.

The generic iOS Release Analyze also succeeds. Every application-source warning found in the first
pass was corrected. A new fail-closed policy recognizes exactly 19 remaining diagnostics in six
reviewed classes: MLXArray values confined to the governed single-owner generation domain, empty
non-iOS dependency shims, and the expected no-App-Intents metadata notice. Any new warning or count
growth now fails validation; the signed archive/export remains the ASR-07 closure boundary.

**No physical-iPhone evidence was run or substituted in this sprint.** ASR-06 still needs signed-
device attribute/backup/locked-relaunch proof; ASR-05 needs accepted-size candidate screenshots;
ASR-07/ASR-10 need a qualified App Store profile, signed archive, and exported IPA; ASR-09 needs the two remaining regions;
ASR-11 needs an authenticated account window; ASR-12 and VLR corrected-source closure remain the
next phone session. DP-31/DP-32, AV-07, and AV-08 retain their human/fluent-listener and independent-
holdout authority rather than being auto-closed from acoustic proxies.

**The Mac/CLI Voice identity/language phase is complete; the corrected-source phone phase has not
started.** The 734-row Mac plan represented every row: 364 PASS, 360 explicit archived-fp32
prerequisite blocks, and 10 hard failures, with no retry or seed replacement. The generator exited
before serial analysis. All 364 passing request receipts were consistent, all 294 Design rows used
the expected model-facing French language, and 220 passing Clone rows completed bounded prosody
plus advisory speaker-similarity analysis. The immutable archived artifact was unavailable, so no
current-runtime substitution or tokenizer rollback was accepted. The privacy-safe details are
pinned in
[`voice-identity-language-reliability-macos-2026-09-01.md`](reference/voice-identity-language-reliability-macos-2026-09-01.md).

The complete Mac matrix localizes one repeated Clone root condition to the second private alias,
transcript-backed English, and seed `32060821`; audio-only conditioning for the same reference and
seed passed. Exact incremental and full codec replay reproduce the delayed onset, disproving the
earlier deferred-MLX-materialization hypothesis. That speculative runtime change was reverted.
VLR-08 now uses a bounded Clone-only leading-edge gate: three active 20 ms windows open it, up to
80 ms of pre-roll is retained, memory remains duration-independent, and Built-in/Design plus all
interior pauses remain untouched. Three fresh corrected-code Auto/explicit cohorts passed 6/6
without retries. Advisory similarity remained strong at 0.6224; the stable 1.444× pacing flag is
retained as an AV-07 calibration limitation rather than hidden.

The French Design evidence rejects language routing and shipped Neutral copy as the first
divergence. Current Neutral remains the strongest tested arm, all Mac model-facing language
receipts match French, and no prompt or delivery copy changed; DP-31/DP-32 retain semantic
promotion authority. VLR-09's v6 gate still rejects the previously observed egregious open terminal
tail without changing interior-pause thresholds, seeds, prompts, or retry behavior.

The historical iPhone runs remain immutable: focused 20/26 PASS, the intentionally paused August 31
characterization at 114 terminal rows plus one interrupted launch, and the separate complete
September 1 characterization at 103 PASS, three product-QC failures, and 16 locale-verification
failures. None is corrected-source closure and none may be resumed, merged, renamed, or overwritten.
Raw audio, aliases, transcripts, traces, and device evidence remain untracked.

**Next phone window:** from the exact committed tree, run `scripts/ios_device.sh preflight`, then two
distinct 14-row `closure` plans and one 122-row `characterization` plan with newly bound private
maps. The closure profile contains production Clone and current-Neutral Design cells only;
experimental no-delivery/Calm arms remain diagnostic. VLR-07, VLR-08, and VLR-09 stay open until
that no-retry physical evidence passes. No iPhone command was run for this Mac checkpoint.

**The causal control-audit remediations now have corrected-source device evidence.** Accessibility
run `ios-xcui-control-audit-20260829-174031-cae15a02` passed Default, AX-L, AX-XXXL,
pseudo-AX-XXXL, and a separate unforced XCTest accessibility audit, closing ICA-07 and ICA-10
through ICA-12. Performance run `ios-xcui-perf-20260829-180027-45adde8a` passed all nine governed
scenarios with no priority-inversion, Thread Performance Checker, engine-stop/reset, QoS-wait, or
semaphore-wait signature, closing ICA-08. Its compact PASS record is in benchmark history.

MD-3 re-closed after the progress-presentation correction. Consecutive diagnoses
`ios-xcui-model-download-20260829-181500-8b1428c9` and
`ios-xcui-model-download-20260829-182031-207e8a83`, followed by acceptance
`ios-xcui-model-download-20260829-182534-91d70526`, passed exact-byte progress, installation,
relaunch adoption, shared-component reuse, removal of all three models, task/crash cleanup, and
canonical-state preservation. Across the acceptance run's 15 visual samples, maximum fill error
was 1.06 percentage points and minimum contrast was 8.80:1.

The `custom-002` long-Chinese result is a valid safety rejection after 293 published chunks, not an
engine-start failure: Qwen exhausted its unchanged 2,048-token ceiling without EOS. Vocello now
emits typed `generation.incomplete` at `streamGenerationEnded`, states that incomplete audio was
not saved, and preserves explicit user-controlled retry. The request, seed, sampling, prompt, token
limit, QC, and one-take policy remain unchanged. Matrix rows no longer infer warm state from order;
the engine receipt is authoritative and each mode must prove at least one genuinely warm row.

The Voices tab Button now owns 44-point minimum geometry and full-width content shape. Playback
graph disposal no longer synchronously calls `AVAudioEngine.stop()` on the MainActor: exclusive
retired graph ownership moves to a registered utility task. A pre-test XCUITest timeout can produce
one run-level `INFRASTRUCTURE_FAIL` only with zero-test proof. A separate narrow classifier covers a
launched test interrupted by a proven SpringBoard notification banner. Run
`ios-xcui-control-audit-20260829-174356-664034d5` is retained under that classification: its log
identified `NotificationShortLookView`, and the maintainer confirmed Facebook Messenger was the
source. It is not product evidence, every unexecuted row stays skipped, and a later manual run has a
distinct identity rather than overwriting it. The decision record and closure evidence are in
[`ios-control-audit-remediation-2026-08-29.md`](reference/ios-control-audit-remediation-2026-08-29.md).

Generation run `ios-xcui-control-audit-20260829-174603-80b1fa0a` used a new source identity and a
different product-selected seed. Its first row passed; its long Chinese row safely rejected a
12.407-second interior silence with the correct QC message and no saved take. That is valid audio-QC
behavior, not a reproduction of the earlier no-EOS terminal. The original seed
`1051465817978323110` has been recovered from retained telemetry, but the production UI has no
arbitrary-seed entry and the failed take created no pinnable History row. ICA-06 therefore remains
in flight rather than adding hidden seeded state or substituting another seed. ICA-04/ICA-05 still
require the remaining source-frozen generation rows, restoration proof, and a re-pinned final report.
Actual VoiceOver/rotor behavior, conditional Update/Repair, authorized permission denial/recovery,
three-repeat stress, and exact signed-candidate ASR-12 acceptance remain separate gaps.

The authoritative earlier runs remain recorded in
[`ios-on-device-control-audit-2026-08-28.md`](reference/ios-on-device-control-audit-2026-08-28.md):
performance `ios-xcui-perf-20260828-172155-32e5b71e` passed 9/9 with explicit warnings; direct
Clone lifecycle `ios-xcui-saved-voice-lifecycle-20260828-143515-86a2b339` and smoke
`ios-xcui-smoke-20260828-165939-d9d57039` passed. The new-source device runs must be retained with
`--retain-result` where supported.

**The development loop is now path-aware and cache-preserving (2026-08-27):**
`scripts/dev.sh plan|focused|checkpoint` separates repeated edit feedback from one coherent-tree
checkpoint while keeping `scripts/evidence_impact.py`, the full project gate, native deterministic
tests, and CI authoritative. Fast project regeneration measured 0.29 seconds; the focused 12-test
transcription/import state suite measured 7.3 seconds warm; and the generic iOS app plus logic
compile measured 12.5 seconds warm after one clean 239-second dependency-cache transition. Target-
scoped diagnostic flags no longer invalidate every Swift package, full Xcode logs remain governed
artifacts instead of flooding the task, and the commit cache binds exact final content while
allowing staging of identical bytes. See
[`development-workflow.md`](reference/development-workflow.md); DWF-05 awaits the final checkpoint
and current explicit device acceptance.

**ICI-3 is implemented; direct Clone-import device acceptance is ICI-4 (2026-08-27):** Studio
Clone's reference panel now offers `referenceClip_importAudioFile` beside Record new clip. The
custom panel dismisses before the native Files picker, and WAV/MP3/AIFF/M4A selection preserves the
original security-scoped URL into the same `importReferenceAudio` materializer used by Voices and
Open in Vocello. Every direct import enters the existing permanent enrollment transaction: a
neighboring `.txt` sidecar wins; otherwise `VoiceClipTranscriber` runs on device, exposes
`saveVoice_transcriptionStatus`, keeps Save disabled while unresolved, and requires manual text or
the explicit `saveVoice_useAudioOnlyButton` when recognition is unavailable. A generation-bound
review state prevents cancelled or delayed recognition from overwriting a newer file or manual
edit. Confirmed Save publishes one Saved Voice and hands its exact voice ID, WAV, reviewed
transcript, and detected language back to Clone; cancellation/failure/discard leaves the catalog
and existing draft unchanged. The obsolete unused session-only Add Audio card is removed.

Twelve focused state/policy tests pass in the hosted core suite, and both the full generic iPhoneOS
app and platform-neutral iOS logic bundle compile successfully. ICI-4 closed on 2026-08-28:
`ios-xcui-saved-voice-lifecycle-20260828-143515-86a2b339` started in Studio Clone, selected the
staged no-sidecar `ICI Direct Clone Import.wav`, received and edited automatic transcription,
saved it, completed one Clone take, previewed and deleted the exact throwaway voice, and proved the
matching draft cleared. After governed restoration of the canonical clone fixture, distinct run
`ios-xcui-smoke-20260828-165939-d9d57039` passed all three smoke tests without automatic retry.

**ASR-03 is closed; ASR-04 has an exact qualified-review boundary (2026-08-27):**
`config/support-contact.json` owns Vocello's public support URL, monitored address, and response
owner. The unauthenticated support page, privacy contact, website footer, and iOS Settings
destination are checked together by `scripts/support_contact_contract.py`, including negative
fixtures for placeholders, URL drift, absent ownership, and false response-time promises. The
production HTTPS route returned 200 with the expected contact/owner/privacy surfaces, and the sole
iOS 1.0 App Store Connect localization (`en-US`) read back the exact governed Support URL. Raw
deployment and account responses remain untracked.

The exact 17-package application resolution, owned Qwen3 runtime license/NOTICE/origin records, and
six catalog-pinned downloadable model identities now generate
`Sources/Resources/third_party_attributions.json`. Settings pushes an accessible offline software/model
license browser; release artifact verification requires the archive and IPA to contain the exact source
manifest. App Store Connect now declares `USES_THIRD_PARTY_CONTENT`, with exact post-mutation readback.
That truthful account declaration is not a rights grant: ASR-04 remains open for qualified review of
model license delivery/NOTICE/trademark obligations, Qwen output and built-in-speaker presentation,
the voice-clone marketing source, other marketing audio/scripts, and artwork provenance. The
decision-ready evidence and fail-closed alternatives are in
[`content-rights-review.md`](reference/content-rights-review.md).

The guarded user-scoped App Store Connect CLI profile is authenticated. Only the explicitly
authorized Support URL and third-party-content declaration were mutated; both were resolved through
the exact app/version/localization identity and read back successfully. ASR-11 remains planned
because categories, availability, screenshots, reviewer metadata, privacy/export/age/DSA/regional
answers, agreements, financial readiness, and all build states have not yet received the required
complete read-only audit. No raw account response or credential entered the repository.

**Repository guidance and roadmap currency pass complete (2026-08-27):** all 52 completed roadmap
items flagged by newer source-authority revisions were re-reviewed against their closure gates; none
required reopening. The 20 active documents carrying freshness signals were reconciled with current
source, contracts, testing lanes, support/attribution governance, and App Store state. Root guidance
now routes guarded App Store Connect work through the optional user-scoped CLI skill while preserving
repository scripts as authority, and the root-plus-website instruction chain remains below 30 KiB.

**The iOS App Store readiness audit is pinned and the submission verdict is not ready
(2026-08-26):** the generic arm64/iOS 26 Release build and Xcode analysis pass, downloaded models are
digest-pinned data rather than executable code, required-reason privacy declarations exist, and the
release workflow has strong source/signature/profile/entitlement/UUID/SBOM verification. Those passes
do not substitute for the twelve `ASR-*` closure gates now owned by `config/roadmap.json`.

The remaining source-proven P1 gaps are the unsupported “Data Not Collected” instruction while Hugging Face
receives model-download request metadata and qualified content-rights/redistribution decisions beyond
the now-complete support and bundled-attribution source work. Reviewer notes/screenshots, sensitive-file protection, release
logging/API hygiene, build-number collision prevention, and model-host reviewer availability also need
closure. A fresh signed archive/exported IPA, read-only App Store Connect audit, qualified legal/privacy
decisions, and exact-candidate physical-device/accessibility acceptance remain explicitly pending. See
[`ios-app-store-readiness-audit-2026-08-26.md`](reference/ios-app-store-readiness-audit-2026-08-26.md);
no build upload, TestFlight change, submission, or release was performed. The two controlled
metadata mutations are recorded above and in the authoritative roadmap.

**F-03 deterministic iOS policy assertions now execute in ordinary CI, F-06 History durability
is closed, F-07 release-source authority is fail-closed, and F-08 Studio terminal ownership is
attempt-scoped (2026-08-26):** the 24 app-host-free
catalog, URL, ledger, managed-path,
memory-band, cancellation, redaction, and Studio-attempt assertions compile into both the generic iOS policy
target and `VocelloCoreTests`. Ordinary macOS CI now executes them without claiming that Xcode's
tool-hosted generic-device bundle can run, while the generic physical-device SDK compile remains
the platform proof and physical-device lifecycle/UI acceptance remains unchanged.

Every atomically published macOS or iOS take is now queued in a schema-v1 local History outbox
before its idempotent `audioPath`-bound SQLite write. Startup and History entry reconcile pending
work, and visible recovery offers Retry plus platform-appropriate Reveal or Export. Clear-all
persists a resumable transaction and deletes database rows before pending entries or requested
audio, so a database failure cannot leave live rows pointing to files already removed. The
deterministic suite covers commit/removal ordering, failed-database replay, duplicate identity,
missing audio, corrupt and interrupted records, and interrupted clear recovery. F-03 and F-06 are
`done` in `config/roadmap.json`.

The repository keeps its maintainer-required direct-to-`main` development workflow, so the live
administrator bypass is recorded rather than misrepresented as closed by branch settings. Release
source authority now compensates at the publication boundary: candidates and promotion require an
annotated GitHub-verified version tag contained in `origin/main` plus successful latest
`CI required` and `Security required` check runs on the exact commit. Path-relevant CodeQL and npm
advisory checks run for pull requests as well as main pushes, and the stable security aggregate is
the exact-SHA release verdict. F-07 is `done`; no live GitHub setting was changed by this source
work.

Every iOS Studio start now owns an opaque attempt token. Single-take and long-form live updates,
success, failure, deferred cleanup, and cancellation-barrier completion mutate visible terminal
state only when that token remains current. Overlapping starts and duplicate cancellation requests
are rejected, stale callbacks cannot clear a newer take, and cancellation-barrier errors are
surfaced instead of swallowed. Five pure transition tests cover the rapid cancel/restart boundary;
the macOS core-test lane and generic iOS app/policy build pass. F-08 is `done`.

F-09's first characterized extraction now gives all three short-form Studio modes one typed
submit/generate/cancel/telemetry/persistence/export authority. The view retains mode-specific
request construction, Clone priming, Design save-sheet state, and attempt-scoped UI completion;
the shared executor owns materialized-output cancellation cleanup and normalizes wrapped engine
cancellation without parsing error text. Five deterministic ordering/failure tests execute in the
hosted core suite and compile with the generic iOS policy target. `IOSGenerationModeViews.swift`
fell from 97,588 to 85,406 bytes, and the full generic iOS app build passes. F-09 is `done`; F-10's
localization architecture is now also `done`.

F-10 established the pre-translation boundary without claiming broad language support: one owned
String Catalog, translator context, typed dynamic presentation keys, plural rules, and a
content-addressed incremental guard against new direct unlocalized presentation literals. Seven
Python contract fixtures and three Swift presentation tests pass. Focused native acceptance also
passed outside the managed sandbox: `macos-xcui-localization-20260826-173053-a9e0d9d6` exercised
the pseudo-localized readiness path, while
`ios-xcui-localization-20260826-173528-7744c05b` walked Settings and Voice Models at Default,
AX-L, AX-XXXL, and Pseudo-AX-XXXL on the paired physical iPhone. The focused lanes generated no
audio and did not change installed-model state.

F-12 now closes the root Xcode Swift dependency blind spot without floating any package. A weekly
and manual read-only workflow validates five exact direct/runtime pins, compares stable GitHub
releases and open Dependabot alerts, and retains a coordinated 14-day proposal covering
`project.yml`, both applicable locks, the owned-runtime compatibility matrix, governance, and the
required evidence battery. Pin drift, incomplete feeds, write-capable workflow permissions, and
partial MLX proposals fail closed; availability explicitly does not establish compatibility.

F-13 now constrains the accepted unsandboxed macOS architecture per code role. The app retains its
documented five capabilities, the engine XPC now signs with the pre-existing two-key embedded-runtime
plist instead of inheriting audio-input and user-file access, and frameworks must carry no
entitlements. A deterministic source/project/release contract plus signed-bundle verification rejects
any added, missing, or changed key and scans owned Swift for arbitrary executable-code loading APIs.
The two MLX hardened-runtime exceptions are bound to the exact reviewed MLX pins, so the next MLX
upgrade cannot pass without a new need/removal review.

F-14 closes the concurrency-debt governance gap without pretending one sanitizer run is permanent
proof. Registry schema v2 requires every owned `@unchecked Sendable` and `nonisolated(unsafe)`
exception to carry a current review date and substantive removal condition, and rejects unreviewed
growth beyond the measured 40/9 declaration budgets. The new weekly/manual `macos-26` lane runs the
460-test deterministic core plus 18 injectable XPC transport tests under ThreadSanitizer, retains
failed evidence without retry, and is time-bounded as non-blocking through 2026-09-30. Its first
corrected isolated-cache physical-host run (`tsan-20260826-142440`) passed with no sanitizer warning or race
summary. This records one of three consecutive clean runs; making the lane blocking still requires
the remaining runs and explicit maintainer review.

**F-05 packaged-startup source remediation is complete but awaits external candidate evidence
(2026-08-26):** the release workflow now runs on `macos-26`, verifies both the staged app and the
app extracted from the DMG, and cannot use `QWENVOICE_SKIP_LAUNCH_SMOKE` in CI. Supply-chain
fixtures reject a runner downgrade or weakened launch proof, and a local external launch of the
built app passed. F-05 deliberately remains `planned` until the next explicitly requested signed
candidate records the hosted `macos-26` proof; no tag or release was created merely to close the
roadmap row.

**F-02 distribution boundary closed (2026-08-26):** behavior-changing runtime overrides now
require two independent conditions: a repository-owned `VOCELLO_INTERNAL_DIAGNOSTICS` build and
the explicit `QWENVOICE_DEBUG` process gate. Local build/test/UI/device-diagnostics routes opt in;
macOS and iOS distribution routes are machine-checked to omit the capability. Consequently,
process environment alone can no longer disable Article 50 publication marking, redirect storage
or catalogs, or alter sampling, lifecycle, memory, or delivery policy in a distributed binary.
`config/runtime-debug-knobs.json` schema v2 classifies behavior mutation separately from bounded
observability, and generation telemetry records active override key names plus a digest of the
values without retaining raw launch input. Swift branch/provenance tests, route-leakage fixtures,
the runtime security contract, and the complete macOS deterministic suite pass. F-02 is done in
`config/roadmap.json`.

**MD-3 iOS model-management delivery and progress closed on physical iPhone (2026-08-26):**
two consecutive `diagnose` runs
(`ios-xcui-model-download-20260826-141408-dd2a4575` and
`ios-xcui-model-download-20260826-142022-902b5d25`) passed before the definitive
`acceptance` run `ios-xcui-model-download-20260826-144618-6274d157`. Acceptance exercised a
real Custom cancellation, process termination and background-task adoption, authenticated Ready
for Custom, Design, and Clone, shared-component reuse, visible removal of all three isolated
models, relaunch persistence, and exact preservation of the canonical model surface. The
fail-closed host validator correlated 1,783 journal events and 21 immutable UI observations with
no lifecycle or visual finding. All three artifacts satisfied
`wire + reused verified = catalog + duplicate` with zero duplicate bytes; reused bytes were at
least the catalog shared component. Every sampled bar was leading-edge anchored, stable at
900×18 pixels, above 8.8:1 contrast, and within 0.35 percentage points of its exact catalog-byte
fraction. This also closes the final harness accounting gap: success records now distinguish
wire bytes from verified reused bytes, and forensic collection cannot swallow a validator
failure. Raw `.xcresult`, screenshots, journals, ledgers, and filesystem inventories remain
untracked under the build-output policy; `config/roadmap.json` records MD-3 as done.

**Angry Normal bilingual routing promoted after a 36/36 hard-safety screen (2026-08-26,
macOS/CLI):** `angry.normal` alone now uses the maintainer-directed
`angry-bilingual-v3` English copy. Its Strong tier and all other preset/tier digests are unchanged.
Canonical preset selections now carry an optional wire-compatible delivery-cell identity through
macOS, iOS, CLI, batch, long-form, benchmark, warmup, and startup diagnostics. The engine resolves
Mandarin only for CustomVoice `angry.normal` when `qwenvoice_contract.json` marks the speaker as
Chinese-native and the resolved output is Chinese; every fallback uses English, while custom and
legacy raw strings remain verbatim. Mismatched cell/copy identity is rejected before prewarm or
generation, and session/prewarm identities bind the final model-facing instruction.

The candidate first ran as a debug-only arm across four fixed seeds, all five contract-derived
Chinese-native speakers, Aiden/Ryan English, Aiden/Chinese fallback, and Vivian/English fallback.
The final source-bound rerun completed after that prewarm-identity alignment. All 36 serial Speed
rows produced audio with exact cell/language/final-instruction receipts and no hard generation or
mandatory audio-QC failure; Vivian/Chinese seed `32060828` passed. This is a
maintainer-directed copy checkpoint and routing-safety result, not evidence of listener-perceived
improvement. DP-31 and DP-32 remain open. The requested roadmap identifier DP-33 was already owned
by the preserved cadence-calibration decision, so this work is recorded as DP-34 rather than
overwriting history.

**DP-30 automatic evaluation corrected and all six retained screens recomposed; no candidate
advances (2026-08-26, macOS/CLI):** the scoring audit found two material v1 weaknesses: any positive
signed feature movement received full credit, and absolute target/competitor distance discarded
which preset actually ranked higher. Schema v2 now uses bounded magnitude bands reproduced from an
independent 64-row pre-candidate acoustic cohort and reports signed target-minus-competitor margin,
wrong-order rate, tiny-movement rejection, and overdrive penalties. Completed rows missing analysis
still fail closed; genuinely failed planned rows remain zero in the denominator under the existing
completion and hard-failure rules. Explicit source-bound legacy recomposition preserves the v1
files and cannot be invoked through ordinary `decide`.

The same retained plans/WAVs/acoustic layers were recomposed without new generation. Happy acoustic
is regression because its +0.019584 bounded gain misses the floor and Happy still ranks below
Surprised at the median; Happy emotion+acoustic and Angry are regressions because each has one new
hard row, even though Angry now has a positive signed margin and a positive score interval. Fearful
urgent is inconclusive with +0.003339 score gain; Fearful structured remains out-of-distribution and
regresses; Surprised onset has no measured improvement and lower adherence. No result is
`automatic_acoustic_improvement`, so the contract still keeps script-interaction, powered, and
untouched variant stages closed. Production instructions remain unchanged. These automatic metrics
calibrate acoustics only: DP-28 and DP-31 remain open because human-labelled, speaker/script/language-
distributed evidence is still required for semantic tone-delivery authority. See
[`delivery-harness.md`](reference/delivery-harness.md) §2.6–§2.7 and the authoritative roadmap.

**Happy, Angry, Fearful, and Surprised have a maintainer-directed production-copy checkpoint
awaiting semantic confirmation (2026-08-25, macOS/CLI):** the 2026-08-24 engineering handout
supplied replacement normal/strong instructions for those delivery presets. The change targets clearer
valence, dominance, and temporal contour; it does not claim measured improvement. Stable presets,
experimental arms, preset IDs/order, shipped tiers, sampling, models, runtime, and QC remain
unchanged. The text contract now has no acknowledged conflict, focused core tests pin tier
distinctness and English-diction append parity. The source-bound Aiden/English/Speed smoke then
completed 4/4 generation rows and 4/4 deterministic analyses with exact current-arm receipts, no
hard QC failure, and no identity mismatch. Repository split policy rejected the handout's
out-of-range `42060824` development seed, so the run used compliant fresh seed `32060824` without
changing the seed contract. All four single-seed comparisons retained advisory acoustic misses;
that does not block the receipt/QC smoke and is not evidence of semantic improvement. The completed
DP-30 screen above rejected every pre-registered replacement arm; DP-31/DP-32 still require
speaker/script-distributed and untouched blinded evidence before any future semantic promotion
claim.

**iOS Built-in Voice startup evidence localized a false-startup label; exact-script closure remains
open (2026-08-24):** the governed physical-device runner and visible XCUITest parity lane are now
live-proven with the 285-character screenshot reconstruction. Vivian / Calm Strong / English UI and
engine receipts matched. Five fixed-seed cold takes and ten same-process warm takes passed. Across
seeds `38112001` through `38112008`, six passed and two reached model tokens, decoded audio, and
published chunks before deterministic dropout QC rejection (`2725 ms` and `14992 ms`). Neither used
allocation recovery. An immediate production-state retry after the first failing seed stayed alive
and produced the same represented QC result.

That evidence exposed a source-proven presentation defect: `MLXTTSEngine`'s outer catch relabeled
downstream mandatory audio-QC failures as “could not start audio generation.” Typed runtime errors
now preserve their owning stage. A rejected dropout remains `stream_failed` /
`audio.quality_rejected`, retains only its allowlisted QC flag, tells the user the generated take had
an unusable silent gap, and is still not saved. Generic startup failures and allocation-retry
wording remain unchanged. The focused core tests, generic iOS build, and physical failing-seed proof
pass this contract.

One separate diagnostics-only forced-unload successor exited after an iOS memory warning without a
terminal take or new retained crash record. The host now checks the exact CoreDevice launch PID,
stops within one polling interval, and performs final evidence collection rather than waiting the
one-hour run timeout. That preparation-arm memory behavior remains open and cannot be promoted into
a product defect without further evidence. ISR-01 through ISR-03 and ISR-05 are implemented; ISR-04
and ISR-06 remain open because the original script bytes, remaining preparation/predecessor/platform
arms, and complete closure matrix are still outstanding. No prompt, sampling default, model pin,
retry count, or audio-QC acceptance rule changed. See
[`ios-built-in-startup-reliability.md`](reference/ios-built-in-startup-reliability.md) and the
authoritative roadmap.

The result-v2 diagnostic expansion is now exercised on the physical iPhone. For streaming seed
`38112006`, live output, exact-range incremental replay, and full replay preserve the same roughly
`980 ms` silence and `cadence:excess11(17/6)` warning. The unusual word spacing is therefore already
encoded in the sampled codec sequence; it is not introduced by Mimi incremental state, chunk
publication, or WAV persistence. Vocello preserves the warning and explicit user retry—there is no
silent seed mutation, hidden regeneration, prompt/sampling change, or relaxed QC.

That first replay used the tracked 280-character sentinel. A later run used the screenshot-derived
285-character request (digest `f946d050…7204b`) and exposed the request-specific severity that the
sentinel could not represent. Seed `38112001` passed the mandatory v4 boundary but v5 classified its
cadence as unusual (14 observed pauses versus 4 punctuation-derived expectations, p90 `1.013 s`).
Seed `38112006` failed the unchanged hard gate with a `14.992 s` interior dropout, and both full and
incremental replay preserved the gross gap. The real visible Studio flow then assembled Vivian,
Calm Strong, English, Balanced, streaming exactly, but its fresh generated seed
`9407571633493666194` also failed hard QC with a `13.993 s` gap. No cadence warning was expected for
either severe take because rejected audio never reaches the completed player; physical visual
acceptance of the advisory state therefore remains open rather than being inferred from a failure.

The visible-UI run also reproduced Xcode's pre-test “Timed out while enabling automation mode”
condition. `xcresulttool` counts that generated runner error as one failed test even though no test
case launched. The classifier now proves the runner-only shape from the missing test URL, zero
passed/skipped tests, and allowlisted bootstrap error; it continues to reject any launched test or
product assertion and never retries automatically. A separate run ID entered the test and its real
audio-QC failure remained a failure.

Fast QC v5 now makes that pacing decision inspectable without changing the v4 acceptance boundary.
Every completed result can carry bounded typed cadence evidence: expected/observed/excess pause
counts, suspicious-gap count, pause durations, cumulative silence, median/p90, and cadence ratio.
An accepted unusual take stays playable and saved on iOS, where the completed player presents a
non-color-only “Unusual pacing detected” notice and an explicit visible-settings “Generate again”
control; severe gross gaps remain rejected before publication. On 2026-08-25 the maintainer accepted
that fail-closed product behavior as sufficient and closed the cadence issue. DP-33 therefore records
the additional independently labelled multilingual threshold-calibration and advisory-visual-
acceptance program as declined, not as a passed gate; no threshold, retry, seed, prompt, or sampling
behavior was changed to manufacture closure. Broader evaluator calibration remains separately owned
by AV-07.

The same run series localized the earlier non-streaming process exit. Quality-first generation had
retained every lazy codec-frame `MLXArray` and then materialized a 300-frame decode graph, reaching
`6292.85 MiB`, zero headroom, critical pressure, and process termination. Codec frames now
materialize as compact `Int32` values and decode through waveform-invariant 25-frame partitions.
Two fresh cold controls completed at `2923.55` and `3023.69 MiB` peak footprint with over `3.1 GiB`
headroom, nominal thermals, complete startup boundaries, identical incremental/full replay, and no
system-crash delta. Diagnostics evidence cleanup also runs before engine initialization so a
validated run is not stranded by unrelated runtime startup. The affected-seed repetition matrix
remains open.

The tracked sentinel has since completed five full warm-generation/unload/quiescence/cold-reload
cycles in one physical-device process. All 10 quality-first takes were represented and passed; warm
and cold engine receipts matched the requested preparation, every post-clear/pre-request snapshot
was violation-free, per-take footprint peaks stayed between `2778.30` and `3185.05 MiB`, minimum
headroom stayed above `2958.95 MiB`, and there were no capture failures or system-crash delta. The
host also received the terminal evidence-cleanup acknowledgement. Equivalent original-script cycles
remain blocked on the unavailable bytes.

The phone-independent macOS CLI control now covers the tracked 280-character sentinel with Vivian,
Calm Strong, English, Expressive sampling, and seeds `38112001`, `38112004`, and `38112006` in both
streaming and non-streaming execution. All 18 fresh-process takes passed mandatory QC with the exact
shipped instruction digest; each seed's per-mode duration was stable across its three repetitions.
Streaming/non-streaming durations nevertheless differed materially for every seed. Fresh on-device
codec evidence now resolves the decoder side for the sampled sequence above, while output-mode RNG
identity, full quiescence cycles, and the remaining matrix still require controlled repetitions.
The original 285-character bytes remain unavailable and exact-script closure is still blocked.

**DP-28 live evaluator infrastructure and calibration audio are complete; human evidence is next
(2026-08-23, macOS/CLI research tooling):** the exact contract-pinned SenseVoiceSmall Q8 and
DistilHuBERT assets now live only under the operator-local build cache. Both passed two cache-cold
probes on the attested Mac14,3 / 8 GiB host with zero swap growth, no pressure warning and clean
post-exit recovery. SenseVoice peaked at 275-293 MB RSS; DistilHuBERT peaked at 677-874 MB. They
remain unadopted until a qualified untouched human holdout improves over ridge-v1.

The accepted balanced calibration run completed 64/64 instructed rows and eight reusable neutral
controls across all eight presets, eight speakers, six scripts/three translation groups and
English, Chinese and Japanese. Its bounded acoustic/temporal analysis and both 64-row compact
cascades passed with valid source/report digests; every cascade row honestly abstains because no
human-calibrated tiny head exists. A prior seed block is retained but excluded in full: one take
repeatedly produced a genuine 4.613-second dropout and failed mandatory Fast QC. No row was silently
dropped or substituted.

The listener packet is ready with 64 label-blind dimensional trials, 56 meaningful non-neutral
target-vs-neutral pairs, three multilingual attention anchors, per-listener deterministic order,
12.5% repeats and per-response atomic resume. Its zero-response readiness report is explicitly
INCOMPLETE. Remaining DP-28 work is human rather than implementation inference: three independent
complete sessions with English/Chinese/Japanese fluency coverage and qualification floors, then
calibration-only challenger preselection, a separately generated untouched confirmation cohort,
and the ridge-v1 comparison. No production delivery instruction or `EmotionPreset` changed;
automatic layers still cannot authorize semantic promotion. See
[`docs/reference/delivery-harness.md`](reference/delivery-harness.md) §2.3.

**Historical DP-27 checkpoint: DP-28/DP-30 screening underway; production copy unchanged
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
speaker-diverse screens; at that checkpoint it was not enough to promote any change or close
DP-28/DP-30. The later per-preset DP-30 outcome is recorded in the current resume block above.
The first blinded DP-28 packet is also generated locally: 27/27 instructed clips and all nine
paired neutral references completed across Aiden, Ryan and Vivian, three script lengths, and
Happy/Angry/Sad. Its public manifest exposes no requested label or speaker/script/seed identity.
It remains intentionally unqualified until three independent listeners supply complete ratings;
no synthetic or requested-preset labels can substitute for that evidence.

A subsequent source-bound DP-30 screen focused on the recurrent Happy and Surprised weaknesses.
Across Aiden, Ryan, Vivian-English and Sohee-English and two fresh development seeds, all 48 takes
completed. Acoustic-only, shipped and constrained-scene prompts scored 10/16, 9/16 and 8/16 on the
advisory gate. The new paired summary showed acoustic-only improved two shipped failures but
regressed one shipped pass overall (`p=1.0`); its two gains were both Happy (`2-0`, `p=0.5`) while
Surprised regressed `0-1`. The constrained arm improved one and regressed two. No global prompt
change advances. Acoustic-only is retained only as an exploratory Happy-specific candidate for a
larger development screen; Surprised and all production copy remain unchanged.

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
knob is the sole internal-diagnostics off-switch and is unavailable in distributed builds;
marking telemetry boundaries exist only when the pass executes. The zero-peak promise is enforced
by a **within-take** fail-closed gate in the
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

- Engineering-review item F-03 closed on 2026-08-26. The 19 deterministic, Foundation-level iOS
  policy assertions now execute in ordinary macOS `VocelloCoreTests` while the exact same test and
  service sources remain compiled in the standalone app-host-free `VocelloiOSLogicTests` target for
  `generic/platform=iOS`. The host suite passed 437 tests including all 19 shared assertions, and
  the generic iOS app plus policy-bundle compile passed outside the managed sandbox. Physical
  runtime and UI acceptance remain exclusively in the headless device and XCUITest lanes.
- Native app UI acceptance uses one shared XCUITest stack: `macos smoke|benchmark` on the native
  Mac host and `ios smoke|benchmark` on a paired physical iPhone.
- UI execution is explicit frontend QA. It is not required to commit, push, open or merge a pull
  request, run ordinary CI, package a release, or create an iOS archive.
- The ordinary macOS lane executes 19 shared iOS policy assertions covering catalog/ledger, memory
  policy, cancellation, storage-path gating, diagnostic redaction, and exact download-progress
  presentation. The ordinary iOS compile lane also typechecks those exact sources in a standalone
  app-host-free XCTest bundle for the generic physical-device SDK. Xcode 26 rejects tool-hosted
  app-free XCTest execution on physical-device destinations, so the duplicate iOS target remains
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
  (`config/runtime-debug-knobs.json` compile-capability-plus-master-gated overrides;
  `config/concurrency-safety.json`
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
