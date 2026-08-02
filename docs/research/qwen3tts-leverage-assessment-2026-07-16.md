---
status: historical
owner: backend-mlx
summary: Point-in-time assessment of unexploited Qwen3-TTS capability, captured 2026-07-16. Pinned snapshot: several figures were superseded and carry inline editor's notes.
contentDigest: sha256:e3c9f4bebc98353645b4ada6ef5e9ac8a5979cdd9f78bb1b4b22accc73d99d7e
---
# Vocello Backend Quality Leverage Assessment

> **Imported research snapshot (2026-07-16).** Converted 2026-07-22 from the external HTML
> report bundle into the repository so corrections and review history stay tracked. Every
> measured figure below is a point-in-time capture from on or before 2026-07-16; the
> 2026-07-22 backend refactor review counter-verified this corpus and found its measured
> claims correct at capture with several since superseded. Superseded figures carry inline
> **Editor's note** blocks; see [`docs/research/README.md`](README.md) for the verification
> summary and [`config/runtime-refactor-contract.json`](../../config/runtime-refactor-contract.json)
> for current phase status.


## Qwen3-TTS 12Hz 1.7B 4-bit Research Review

**Research bundle date:** July 16, 2026
 **Vocello repository:** `PowerBeef/Vocello`
 **Reviewed source:** [`main` at `079757abc3524ad5c0308bb1d914a9ff151c0de6`](https://github.com/PowerBeef/Vocello/commit/079757abc3524ad5c0308bb1d914a9ff151c0de6)
 **Assessment date:** July 16, 2026
 **Scope:** Qwen3-TTS 12Hz 1.7B 4-bit Base, CustomVoice, and VoiceDesign quality, accuracy, prosody, cloning, long-form, and quantization strategy  8.6/10leverage potential for Vocello **Executive verdict.** The research is valuable and should influence the Vocello backend, but not literally. The most useful findings are the evaluation protocol, deterministic multilingual text front end, acoustic-duration-aware segmentation, independent semantic/residual sampling experiments, selective candidate retry, and a model-native VoiceDesign-to-Base-clone identity lock for long-form work. The least justified immediate actions are replacing the canonical 4-bit weights, shipping the proposed sampler numbers, making non-streaming the product default, or generating four to six candidates for every interactive request. Vocello already implements many of the report’s presumed missing port fixes; the opportunity is to expose, measure, and integrate them correctly.   4initiatives worth starting now 5controlled experiments 3quantization/long-term items 10major findings already implemented 35bundle evidence entries 524current Python tests inventoried

>

**Core recommendation:** spend the next quality cycle on frontend correctness, segment planning, typed dual-stage sampler experiments, and long-form identity control. Use the existing evidence platform to prove whether a quantization redesign is still necessary afterward.

## 1. Assessment of the research itself

### Research quality scorecard

| Dimension | Score | Assessment |
| --- | --- | --- |
| Evidence discipline | 9.0 | Clear confidence labels, a 35-source evidence matrix, and a strong distinction between BF16 facts, INT4 hypotheses, and runtime defects. |
| Architecture reasoning | 8.8 | The semantic-codebook versus residual-codebook decomposition is useful and maps well to Qwen3-TTS. |
| Evaluation protocol | 9.2 | Variant/language/seed manifests, failure taxonomy, paired controls, and multidimensional metrics are immediately reusable. |
| Direct applicability to current Vocello | 6.8 | Several implementation conclusions target Blaizzy/mlx-audio 0.4.5; Vocello’s owned Swift core has already moved beyond them. |
| Sampler profile evidence | 5.5 | The profiles are sensible experimental grids but are not measured optima and conflict with Vocello’s prior finding that official defaults sounded best. |
| N-best production practicality | 6.0 | Strong reliability idea, but latency, energy, model scheduling, ASR availability, and product UX costs are underweighted. |
| Quantization recommendation confidence | 5.8 | Group-32 and protected projections are rational, but their benefits are estimated rather than demonstrated. |
| Reference scaffold quality | 6.7 | Good manifest and validation shape; CJK scoring, risky-token coverage, model identity, crossfade, and scorer implementations remain research-grade. |
| Overall research quality | 8.1 | A valuable research program and experiment generator, not a drop-in backend specification. |
| Vocello leverage potential | 8.6 | High, provided the findings are adapted to the current code rather than implemented literally. |

### What the bundle does especially well

The bundle is unusually disciplined about attribution. It does not claim that every audible defect is caused by four-bit weights. It separates baseline Qwen behavior, quantization sensitivity, tokenizer/port/runtime defects, and misuse of variant, language, text, reference, streaming, or deployment contracts.

That is the correct diagnostic frame. Official Qwen evaluation was conducted with BF16 and `max_new_tokens=2048`, with checkpoint sampling defaults; it is not direct evidence for the quality of an MLX INT4 conversion. The report states this limitation repeatedly and treats group size, protected projections, and sampler profiles as experiments rather than facts.

The architecture analysis is useful. Qwen3-TTS predicts the first, content-bearing codec stream with the main talker and predicts the remaining residual codebooks with a separate code predictor. That makes independent semantic and acoustic tuning a coherent hypothesis rather than arbitrary parameter searching.

The evaluation protocol is the strongest companion artifact. Exact model/runtime/conversion identity, five seeds, language and variant matrices, WER/CER, LID, speaker, onset, F0, energy, rate, silence, clicks, RTF, memory, hang rate, failure labels, and paired controls map naturally onto Vocello’s existing benchmark system.

### Where the bundle must be adapted

The implementation review targets a Python `mlx-audio` 0.4.5 commit. Vocello’s current backend is a first-party Swift package with additional fixes and different ownership. Independent subtalker overrides, the Qwen speaker frontend, clone artifact schema 3, exact model-artifact identity, terminal barriers, and current device evidence already exist.

The numeric profiles are plausible search points, not recommendations supported by audio results. They conflict with Vocello’s prior listening conclusion that official sampling sounded best. They should enter a controlled experiment ledger, not Settings or production defaults.

The N-best recommendation underestimates product cost. Four candidates mean approximately four sequential model runs under Vocello’s single-owner generation contract. That is acceptable for offline quality work, not for default interactive or iPhone use.

The quantization section is intellectually sound but evidentially weak. A 60–90 MiB storage estimate does not prove an audible gain or acceptable resident-memory/RTF effect on Apple Silicon.

## 2. What Vocello already implements

| Research recommendation | Current Vocello status | Analysis |
| --- | --- | --- |
| Strict variant and capability modeling | **Implemented** | Model size, family, instruction support, cloning support, tokenizer profile, generation defaults, artifact availability, variants, and exact catalog identity are typed. |
| Explicit and detected language routing | **Mostly implemented** | The UI can use Auto, while PromptLanguageDetector and GenerationSemantics resolve supported Qwen language tokens when confidence is sufficient. |
| Independent semantic/residual sampling at the hot loop | **Low-level implementation exists** | Codebook 0 uses main parameters; codebooks 1–15 can use independent subtalker temperature/top-k/top-p through debug-gated overrides. |
| Official Qwen clone speaker frontend | **Implemented and accepted** | Vocello owns the Qwen-specific magnitude/Slaney/natural-log frontend, mono shape contract, finite embedding validation, and schema-3 artifact invalidation. |
| Clean reference preparation and prompt caching | **Implemented** | Mono 24 kHz normalization, transcript-backed/x-vector modes, reference fingerprints, model/artifact/runtime identity, LRU caches, and atomic prompt persistence. |
| Bounded generation and token accounting | **Implemented** | The runtime computes an effective token ceiling, enforces EOS/token-cap semantics, and records detailed hot-loop diagnostics. |
| Streaming-first memory discipline | **Implemented and evidence-backed** | Streaming is the product path and has materially lower, length-flat memory than legacy non-streaming accumulation. |
| Shared seed across long-form segments | **Implemented** | Batch generation stamps one seed across all segments to reduce independent rerolling. |
| Audio QC, ASR/language evidence, prosody and memory validation | **Implemented as QA infrastructure** | The benchmark/evidence system already contains most components needed to evaluate the research hypotheses. |
| Complete exact model delivery | **Implemented** | All production Speed/Quality artifacts are pinned by revision, file set, sizes, SHA-256, host/redirect policy, and atomic installation. |

### Consequence

The project should not create a parallel “research backend.” The correct approach is to extend the owned core and its existing evidence contracts. Every experiment should use the current production model catalog, Qwen/Mimi implementation, streaming and terminal lifecycle, telemetry schema, canonical Mac/iPhone hardware, exact source/profile fingerprints, and PASS-only evidence model.

## 3. Leverage decision matrix

| Research idea | Decision | Potential benefit | Engineering effort | Product risk | Vocello-specific rationale |
| --- | --- | --- | --- | --- | --- |
| Typed dual-stage sampler policy | **Experiment now** | High | Low–medium | Medium | The low-level split already exists. Move it from process-global debug overrides into request/session policy, telemetry, and a controlled A/B matrix. |
| Deterministic spoken-text normalization | **Build now** | Very high | Medium | Medium | The largest unfilled accuracy layer: numbers, dates, times, units, currencies, acronyms, URLs, names, and code-switching need explicit spoken forms. |
| Language-confidence resolution | **Build next** | Medium–high | Low–medium | Low | Keep Auto UX, but resolve to an explicit Qwen token when confident and surface uncertainty for high-risk or long-form input. |
| Duration/token-aware long-form segmentation | **Build now** | Very high | Medium | Medium | Replace the 900-character heuristic with locale-aware sentence/clause boundaries, duration estimates, tokenizer budgets, and a hard codec-token ceiling. |
| VoiceDesign → Base-clone identity lock | **Experiment now** | Very high for long form | Medium | Medium | Generate/select one designed reference, convert it to a reusable Base clone prompt, and synthesize all segments from that fixed identity. |
| Selective N-best retry/reranking | **Pilot** | High on failures | Medium–high | Medium–high | Use one candidate normally, then generate one or two more only for failed/risky chunks. Do not make 4–6 candidates the interactive default. |
| Streaming/non-streaming parity diagnostic | **Add to QA** | Medium | Low | Low | Use non-streaming as a quality reference, not as the product default; compare fixed-seed code/audio behavior at 0.32 and 0.64 s. |
| Boundary-aware long-form assembly | **Pilot after segmenter** | Medium | Medium | Medium | Silence-aware loudness matching and short fades can remove clicks, but cannot repair speaker or prosody drift. |
| Reference-duration calibration | **Run experiment** | Medium–high for clone | Low–medium | Low | Resolve the 3–10 s research recommendation versus Vocello’s 10–20 s heuristic with a direct 3/5/8/10/15/20/30 s matrix. |
| Group-size 32 INT4 | **Defer to controlled model experiment** | Unknown; plausible | High | High | Architecture-derived hypothesis only. Produce a separate artifact and run the full existing evidence stack before considering catalog replacement. |
| Protected text/codec/MTP projections | **Defer to controlled model experiment** | Unknown; plausible | High | High | Potentially efficient, but the ~60 MiB estimate is not perceptual evidence and must be measured against memory, RTF, WER/CER, speaker and prosody. |
| QAT/distillation/custom four-bit training | **Long-term research** | Potentially high | Very high | Very high | Not justified until frontend, segmentation, split sampling, and candidate selection establish a trustworthy residual quantization gap. |

## 4. Highest-value opportunity: deterministic multilingual spoken text

### Why this outranks quantization

Sampling cannot reliably decide whether `03/04/2026`, `1.5 kg`, `$12.30`, `v2.1.0`, `7:05`, `2030`, `St.`, or an acronym should be spoken in a particular way. Quantization cannot repair a wrong textual interpretation either. A deterministic spoken-text plan improves the actual conditioning presented to every model variant and precision.

Vocello performs useful language detection and prompt assembly, but not a general spoken-form transformation. The new layer should be explicit and inspectable.

### Proposed contract

```
public struct SpokenTextPlan: Codable, Hashable, Sendable {
    public let originalText: String
    public let spokenText: String
    public let language: Qwen3SupportedLanguage
    public let transformations: [SpokenTextTransformation]
    public let unresolvedRisks: [SpokenTextRisk]
    public let normalizerVersion: String
}

```

`SpokenTextTransformation` should record a source range, original token, spoken replacement, category, and rule/version. `SpokenTextRisk` should identify ambiguous numerals, time/date forms, currency, units, URLs, email, version strings, acronyms, mixed scripts, and unsupported characters.

### Product behavior

- Keep the original text as the history and editing source.
- Generate from the spoken text.
- Provide a “Review spoken form” preview.
- Never silently guess genuinely ambiguous values in controlled/batch mode.
- Allow project pronunciation dictionaries for names and brands.
- Record only privacy-safe transformation counts/digests in telemetry.
- Version the normalizer so reproduced evidence knows the exact frontend.

### Implementation order

1. NFKC, quote/dash/ellipsis normalization and whitespace.
2. Locale-aware numbers, decimals, signed values, percentages and currency.
3. Dates, times and measurement units.
4. Acronyms, initialisms, URLs, email and versions.
5. Per-project pronunciation lexicon.
6. Code-switch segment detection and a visible language plan.

Start with English, Chinese, French, German, Spanish, and Japanese, then cover all ten languages before changing default behavior.

### Acceptance

- No character loss or duplication.
- Exact spoken-form fixtures for every supported language.
- 99%+ exact-match on the calibrated scripted high-risk corpus.
- Every rewrite explainable and reversible.
- No silent transformation when multiple readings are reasonable.
- Fixed-seed WER/CER improves without prosody or latency regression.

## 5. Highest-value opportunity: long-form segmentation and identity control

### Current limitation

`LongFormBatchSegmenter` uses 900 characters, paragraphs, and ASCII `. ! ?` boundaries. Character count is a poor proxy for audio duration across ten languages. It cannot reason about abbreviations, decimals, CJK punctuation, token budget, or intended pause at the join.

A better plan should target acoustic duration and model budget:

```
public struct LongFormSegmentPlan: Codable, Hashable, Sendable {
    public let index: Int
    public let sourceRange: Range<Int>
    public let spokenText: String
    public let language: Qwen3SupportedLanguage
    public let boundary: BoundaryKind
    public let estimatedTextTokens: Int
    public let estimatedAudioSeconds: Double
    public let maximumCodecTokens: Int
    public let assemblyPauseMilliseconds: Int
}

```

### Segmentation policy

Use the research’s 8–20 second range as a starting calibration, not a fixed truth. Prefer paragraph, sentence, semicolon/colon, safe clause/comma, whitespace, and finally grapheme fallback. Use `NLTokenizer` plus explicit CJK punctuation and protected patterns for decimals, abbreviations, URLs, and versions. After model load, use the actual tokenizer count to validate the plan. No segment may exceed the effective 2048 codec-token ceiling.

### Voice consistency

The existing shared seed is useful but insufficient. Same seed plus different text follows a different stochastic path. Every segment must reuse one resolved language, speaker/design/clone identity, sampler policy, reference prompt, and runtime profile.

#### VoiceDesign-to-Base-clone lock

For Mac long-form VoiceDesign:

1. Generate several short design references.
2. Select one using QC and optional speaker/prosody gates.
3. Create one Base clone prompt.
4. Generate every segment from that prompt.
5. Retain the original design description as project metadata.

This follows the official Qwen reusable-identity workflow and directly targets timbre/identity drift. It may require both VoiceDesign and Base model transitions, so it should be an explicit offline workflow.

### Assembly

A blanket crossfade is not sufficient. Use speech/silence boundary detection, punctuation-derived pause targets, short safe silence trimming, loudness matching, a 40–80 ms equal-power fade only within verified non-speech overlap, and no overlap across an intentional sentence or paragraph pause. Run final ASR and boundary continuity checks.

Crossfade repairs clicks and level discontinuity. It cannot repair voice, accent, pitch, rate, or emotional drift; those must be solved before assembly.

## 6. Highest-value experiment: typed dual-stage sampling

### Current implementation

The owned runtime already distinguishes the stages internally. The missing architecture is request-owned policy.

```
public struct Qwen3SamplerStagePolicy: Codable, Hashable, Sendable {
    public let temperature: Float
    public let topK: Int
    public let topP: Float
    public let minP: Float
}

public struct Qwen3SamplingPolicy: Codable, Hashable, Sendable {
    public let id: String
    public let main: Qwen3SamplerStagePolicy
    public let residual: Qwen3SamplerStagePolicy
    public let repetitionPenalty: Float
    public let maxNewTokens: Int
    public let seed: UInt64?
}

```

The policy should travel through `GenerationRequest`, XPC codecs, the facade, loaded model, and Qwen hot loop. Debug environment values may remain as an experiment overlay but should not be the primary production mechanism.

### First controlled matrix

| Arm | Main | Residual | Purpose |
| --- | --- | --- | --- |
| A0 | official 0.9 / 50 / 1.0 | inherit official | Current control |
| A1 | official | 0.82 / 50 / 0.98 | Test steadier acoustic codes without changing semantic sampling |
| A2 | 0.80 / 50 / 0.95 | official | Test semantic conservatism without flattening residual diversity |
| A3 | research Balanced | research Balanced residual | Test the supplied paired hypothesis |
| A4 | research Content Safe | research Content Safe residual | Stress lexical/numeral accuracy |
| A5 | current Consistent main | official residual | Compare current preference with decoupled residual diversity |

Use the same fixed seeds, text, language, model, streaming interval, reference, and hardware. Run CustomVoice, VoiceDesign, transcript-backed Clone, and x-vector Clone separately. Start with English, Chinese, German, French, Spanish, and Japanese; expand only after narrowing the grid.

### Metrics and decision

Require WER/CER and named/numeral accuracy, language drift, speaker/onset similarity, F0/energy/rate distributions, instruction adherence, EOS/repetition/reference-tail behavior, audio QC, RTF/memory, and blinded preference.

Adopt a non-official profile only if it improves a declared failure class without degrading the remainder beyond a predeclared tolerance. Keep Expressive mapped to official behavior until then.

## 7. Selective candidate generation and reranking

### Why selective

The bundle’s “four normal, six expressive” policy is an offline research setting. Vocello should use a tiered policy:

```
public enum CandidateSelectionPolicy: Codable, Hashable, Sendable {
    case single
    case retryOnFailure(maxCandidates: Int)
    case offlineBestOf(Int)
}

```

Recommended scope: interactive Mac single, iPhone single, Mac long-form retry-on-failure with maximum two, explicit Quality Assist best-of-two, and unrestricted counts only in research benchmarks.

### Gate order

1. terminal/EOS and output validity;
2. NaN/Inf/clipping/RMS/silence/click/duration checks;
3. high-risk text/language checks;
4. local ASR/LID where available;
5. speaker/onset similarity;
6. prosody/rate constraints;
7. generate another candidate only on failure.

Sequential generation preserves the one-owner MLX contract. Do not parallelize candidates inside one process or across competing Metal processes.

### Scorer requirements

A production scorer must state model/API identity, offline behavior, permissions, language assets, calibration, CJK CER, reference preprocessing, unavailable-scorer behavior, privacy, and retention. A scorer must never silently change candidate selection just because a system language asset is missing.

## 8. Reference and clone quality

Vocello already implements the important structural controls: mono 24 kHz normalization, typed transcript/x-vector modes, exact Qwen speaker features, finite embedding validation, and version-bound prompt artifacts.

The remaining question is reference selection. Official material advertises rapid cloning from about three seconds, the bundle recommends roughly 3–10 seconds, and Vocello recommends 10–20 seconds. Resolve this empirically with lengths 3, 5, 8, 10, 15, 20, and 30 seconds; transcript-backed and x-vector; clean/noisy/reverberant; native/cross-lingual; onset/full speaker similarity; WER/CER; prosody; prep latency and memory.

Calibrate warnings separately by conditioning mode. Additional useful gates include speech activity ratio, SNR, reverb, crosstalk/music, transcript alignment, leading/trailing silence, and phonetic coverage. These should guide the user rather than silently alter the source.

## 9. Streaming quality

Retain streaming as the product baseline. Use non-streaming as a controlled reference. Run exact-seed parity across full decode, 0.32 s streaming and 0.64 s streaming, with identical code input to the decoder where possible. Measure code identity, final PCM alignment, onset, boundaries, WER/CER/LID, speaker/prosody, TTFC, RTF and memory.

If code sequences match but audio differs, focus on streaming decoder context and assembly. If code sequences differ, inspect generation scheduling/evaluation semantics. Do not infer quantization damage from a streaming-only difference.

## 10. Custom INT4 program

### When it is justified

Begin only after the spoken-text layer, segment planning, split sampling, reference conditioning and streaming parity are controlled, and a residual gap remains against the same runtime’s control.

### Artifacts

| Artifact | Large matrices | Interfaces | Quantization |
| --- | --- | --- | --- |
| A0 | INT4 | canonical | affine group 64 |
| A1 | INT4 | canonical | affine group 32 |
| A2 | INT4 | text projection, semantic head, MTP bridge and residual heads protected | affine group 64 |
| A3 | INT4 | protected interfaces | affine group 32 |

Do not replace the existing Speed artifact or reuse its model ID. Each build needs source checkpoint/revision, converter version, predicate, tensor inventory, bits/group/mode per tensor, hashes/bytes, artifact version, license, catalog entry, model BOM and independent evidence identity.

### Decision gate

A custom artifact must improve at least one critical failure class and remain within declared tolerances for every mode, all ten languages, text/language correctness, speaker identity, prosody/onset, RTF/TTFC/memory/load/disk, crash/hang/EOS, and floor hardware.

## 11. Evaluation framework integration

The research protocol should become a Vocello-native quality experiment contract, not a separate Python benchmark stack.

```
{
  "schemaVersion": 1,
  "experimentID": "qwen-quality-...",
  "source": {"commit": "...", "dirty": false},
  "model": {
    "id": "...",
    "revision": "...",
    "artifactVersion": "...",
    "integrityDigest": "...",
    "quantization": {"mode": "affine", "bits": 4, "groupSize": 64}
  },
  "frontend": {
    "normalizerVersion": "...",
    "segmenterVersion": "...",
    "languagePlanDigest": "..."
  },
  "sampling": {
    "policyID": "...",
    "main": {},
    "residual": {},
    "seed": 17
  },
  "candidateSelection": {"policy": "single"},
  "streaming": {"enabled": true, "intervalSeconds": 0.32},
  "failureLabels": [],
  "metrics": {}
}

```

### Targeted hard corpus

Add numbers, dates, times, percentages, currencies, units, proper names, acronyms, URLs, versions, short onset cases, reference-tail leakage, code switching, CJK/Latin punctuation, long rate drift, joins, instruction conflicts, native/non-native presets, and both clone modes.

### Staged scale

1. Canary: six languages × three variants × twelve hard prompts × five seeds.
2. Focused: failure-heavy cells plus clone reference matrix.
3. Full: all ten languages, 100 lexical utterances/language, 30 voice/prosody samples/mode, 20 long passages/language.
4. Canonical: clean source, accepted policy/artifact, floor hardware and complete evidence.

Use automated metrics for gates and blinded listening for adoption. Listening notes do not replace exact configuration or deterministic checks.

## 12. Critique of the companion Python scaffold

### Strong elements worth porting conceptually

- strict variant/request validation;
- explicit model scope;
- stable manifest;
- deterministic seeds;
- frontend injection point;
- segment planning;
- candidate inventory;
- integrity checks;
- synthesis/scorer separation;
- fail-closed ambiguity.

### Elements that should not be copied

- model identity validated by substrings in a repository name;
- one Latin-oriented risky-token regex;
- `\\w+` WER for Chinese/Japanese;
- optional scorers with no production implementation;
- fixed hand-weighted score without calibration;
- blind overlap of every adjacent chunk;
- default non-streaming production posture;
- four to six candidates regardless of risk;
- 240/420 character boundaries as an acoustic plan;
- Python/runtime dependencies in the shipping app.

Vocello’s typed catalog, Swift core, ASR/QC evidence and lifecycle are stronger foundations.

## 13. Proposed implementation map

| Area | Current files | Proposed change |
| --- | --- | --- |
| Sampler contract | `VocelloQwen3Core/Contracts.swift`, `LoadedModel.swift`, `Qwen3TTS.swift` | Add main/residual stage policy, request-local seed/top-k, profile ID and telemetry |
| Product request | `SemanticTypes.swift`, XPC codecs | Optional quality/sampling policy with backward-compatible defaults |
| Product adapter | `UnsafeSpeechGenerationModel.swift` | Stop relying on process-global variation state; map request policy |
| Spoken frontend | new `SpokenTextNormalizer.swift` plus language rule files | Return versioned spoken plan, transformations and unresolved risks |
| Language routing | `PromptLanguageDetector.swift`, `GenerationSemantics.swift` | Confidence-aware explicit language plan and code-switch segmentation |
| Long form | `BatchGenerationRunner.swift` | Replace 900-char segmenter with locale/duration/token SegmentPlan |
| Identity lock | batch coordinator plus clone support | Optional VoiceDesign→prepared Base clone workflow |
| Candidate selection | engine/batch runner | Single/retry/best-of policy and sequential selection |
| Assembly | new `LongFormAudioAssembler.swift` | Boundary-aware pause, loudness and fade policy |
| Evidence | benchmark schemas/scripts | Quality experiment manifest, failure taxonomy and paired comparison |
| Quantization | external converter plus production catalog | Separate research artifacts and exact quantization manifests |

## 14. Phased roadmap

### Phase 0 — Baseline and contracts, 2–5 days

- Import the bundle as a design/evidence record.
- Add quality-experiment schema and failure taxonomy.
- Freeze official-sampling baseline at current main.
- Add typed sampler-stage policy behind benchmark/CLI diagnostics.
- Record main/residual settings in telemetry.
- Build the hard canary corpus.
- Preserve current long-form and variation controls as explicit baselines.

**Exit:** exact repeatable A0 runs exist on Mac and iPhone; no production behavior changes.

### Phase 1 — Frontend and segment planning, 1–3 weeks

- Implement `SpokenTextPlan`.
- Add high-risk token detection and spoken preview.
- Build deterministic rules for six priority languages, then all ten.
- Replace long-form segmentation with locale/duration/token planning.
- Add zero-loss/zero-duplication and boundary tests.
- Add continuity metrics to long-form manifests.

**Exit:** lexical accuracy and long-form metrics improve without changing weights or sampler defaults.

### Phase 2 — Sampler and identity experiments, 1–2 weeks

- Run A0–A5 dual-stage sampler matrix.
- Run direct VoiceDesign batch versus design→clone lock.
- Run the 3–30 second reference matrix.
- Run 0.32/0.64/non-streaming parity.
- Perform blinded listening on failure-heavy samples.

**Exit:** an evidence-backed policy is accepted or official defaults are retained with documented negative results.

### Phase 3 — Selective quality assist, 2–4 weeks

- Add deterministic failure-triggered retry.
- Integrate calibrated local ASR/LID where available.
- Add speaker/onset scoring.
- Pilot best-of-two for Mac long-form/export.
- Measure marginal gain per candidate and total compute/energy.

**Exit:** selective retry produces meaningful accepted-output gains at acceptable cost, or remains disabled.

### Phase 4 — Custom INT4 conversion, 3–8 weeks

- Build A1, A2 and A3 artifacts.
- Keep A0 canonical control.
- Run focused then full evidence.
- Compare memory, load, RTF, correctness, speaker, prosody, audio and stability.
- Adopt only under a new artifact version after complete gates.

**Exit:** a custom artifact earns production status or canonical INT4 remains with a documented decision.

## 15. Risks and guardrails

| Risk | Guardrail |
| --- | --- |
| Text normalizer changes meaning | Preview transformations; fail on ambiguity; keep original text |
| Per-language rules drift | Versioned fixtures and language-owner review |
| Sampler profile flattens expression | Isolate main/residual; blinded listening; official default retained |
| N-best creates unacceptable latency | Selective sequential retry; candidate cap; Mac/offline scope |
| ASR scorer rejects correct accents | Language-specific calibration and review disagreements |
| Crossfade overlaps speech | Speech/silence detection and punctuation pause policy |
| Design→clone changes intended delivery | Preserve design reference metadata and compare instruction adherence |
| Custom INT4 increases memory or slows load | Separate artifact identity and floor-device measurement |
| New profile invalidates cache identity | Include complete policy ID in session/prewarm/cache keys |
| Experiments leak into releases | Debug/benchmark gating and evidence-impact contracts |
| Metric is gamed | Multi-objective gates plus accepted/rejected sample review |
| Current evidence becomes stale | Path-based evidence impact and exact identities |

## 16. Detailed leverage findings

### A-01 — The split-sampler recommendation is already half implemented; the missing piece is typed request ownership

**Classification:** High leverage

The research’s strongest port-level recommendation is to decouple the main semantic sampler from the residual acoustic sampler. Vocello already does this inside the Qwen hot loop: codebook 0 receives the request’s main temperature/top-p plus talker top-k/min-p, while codebooks 1–15 can receive separate subtalker temperature/top-k/top-p. The current product does not expose that capability as a typed per-request policy. Instead, residual overrides are process-global, debug-gated environment values resolved once.

**Decision:** Promote the existing hook into a typed experimental policy and measure it immediately; do not reimplement the sampler split.

**Current-source references**

- [Qwen sampler overrides](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift#L296-L356)
- [Residual sampling use](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift#L3050-L3130)
- [Product main variation](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/QwenVoiceCore/UnsafeSpeechGenerationModel.swift#L8-L50)
- [Debug knob registry](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/config/runtime-debug-knobs.json#L11-L51)

### A-02 — Multilingual spoken-text normalization is the clearest unfilled accuracy layer

**Classification:** High leverage

Vocello detects language and normalizes language identifiers, but there is no general backend contract that expands ambiguous numbers, dates, times, currency, measurements, version strings, abbreviations, or URLs into deterministic spoken form. These errors cannot be reliably fixed by sampling or quantization. The normalizer must be language-aware, domain-aware, versioned, testable, and visible to the user; silent aggressive rewriting would create a different correctness failure.

**Decision:** Make a SpokenTextPlan a first-class input to generation and the top production-quality implementation project.

**Current-source references**

- [Language detector](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/QwenVoiceCore/PromptLanguageDetector.swift#L1-L36)
- [Language resolution](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/QwenVoiceCore/GenerationSemantics.swift#L654-L676)
- [Supported-language model](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/QwenVoiceCore/SemanticTypes.swift#L33-L108)

### A-03 — The 900-character long-form chunker is not aligned with acoustic duration or the 12.5 Hz token budget

**Classification:** High leverage

Long-form segmentation currently groups paragraphs and ASCII sentence punctuation until a 900-character ceiling, then falls back to whitespace splitting. That does not model language-specific speaking rate, CJK punctuation, abbreviations, decimals, codec-token budget, or intended join pauses. It can produce segments far longer than the research’s 8–20 second target and is directly relevant to open issue #30.

**Decision:** Replace the heuristic with a versioned SegmentPlan using locale-aware boundaries, estimated duration, actual tokenizer counts where available, and a hard codec-token cap.

**Current-source references**

- [Current segmenter](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/Services/BatchGenerationRunner.swift#L8-L122)
- [Shared batch seed](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/Services/BatchGenerationRunner.swift#L275-L318)
- [Issue #30](https://github.com/PowerBeef/Vocello/issues/30)

### A-04 — VoiceDesign-to-Base-clone locking may address long-form identity drift more directly than sampler tuning

**Classification:** High leverage

The official Qwen workflow recommends synthesizing a short designed reference, building a reusable Base clone prompt, and generating subsequent content from that fixed prompt. Vocello’s current VoiceDesign batch invokes VoiceDesign independently for every segment, even though it shares one seed. The text changes per segment, so identical seed alone cannot guarantee an identical designed identity. Selecting one designed reference and then cloning from it is a strong, model-native identity lock for Mac long-form work.

**Decision:** Run an A/B against direct VoiceDesign batch and, if superior, add an optional “Lock designed voice for long form” backend policy.

**Current-source references**

- [Direct VoiceDesign batch requests](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/Services/BatchGenerationRunner.swift#L391-L406)
- [Official Qwen repository](https://github.com/QwenLM/Qwen3-TTS)

### A-05 — N-best reranking should be selective, sequential, and initially Mac/offline only

**Classification:** Medium–high leverage

Generating four to six candidates for every segment can multiply latency and energy by roughly the candidate count and conflicts with Vocello’s single-owner MLX discipline. The research is strongest when reframed as selective retry: generate one candidate, run cheap deterministic gates, and create one or two additional candidates only when the segment is risky or fails. Lexical reranking requires a local ASR path; language and speaker scoring also need calibrated models and privacy/permission handling.

**Decision:** Pilot two-candidate failure-triggered selection for Mac long-form/batch. Keep interactive and iPhone generation single-candidate by default.

**Current-source references**

- [Batch runner](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/Services/BatchGenerationRunner.swift)
- [Current evidence checkpoint](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/docs/development-progress.md)
- [Project health](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/docs/project-health.md)

### A-06 — Non-streaming is useful as a reference, not as a new production default

**Classification:** Medium leverage

The bundle defaults its Python scaffold to non-streaming for quality comparison. Vocello has already shown that non-streaming accumulation can consume roughly 2.5× the memory of the streaming path, while streaming memory is comparatively flat with length. The useful action is a fixed-seed parity experiment across non-streaming, 0.32 s streaming, and 0.64 s streaming—not changing the application default.

**Decision:** Add a parity/quality diagnostic and preserve streaming-first product behavior unless matched evidence shows a meaningful quality gap.

**Current-source references**

- [Streaming interval](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/QwenVoiceCore/GenerationSemantics.swift#L451-L455)
- [Streaming memory evidence](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/benchmarks/OPTIMIZATION.md#L199-L232)

### A-07 — Group-32 and protected-projection INT4 builds are rational experiments, not established improvements

**Classification:** Experimental

The research estimates about 90 MiB extra storage for group size 32 and about 60 MiB for protecting text/codec/MTP interfaces. Those are architecture-derived storage estimates, not measured resident memory, RTF, WER/CER, speaker similarity, or listening preference. The canonical model should remain the control and every new conversion must receive a distinct model/artifact identity.

**Decision:** Defer until frontend, segmentation, and sampler experiments establish a remaining quantization-specific gap; then evaluate A0–A3 as separate research artifacts.

**Current-source references**

- [Production catalog](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/QwenVoiceCore/ProductionModelCatalog.swift)
- [Runtime capabilities](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Packages/VocelloQwen3Core/RUNTIME_CAPABILITIES.json)
- [Benchmark history](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/benchmarks/HISTORY.md)

### A-08 — The implementation notes describe a different port than current Vocello

**Classification:** Research correction

The notes target Blaizzy/mlx-audio 0.4.5 and conclude that the MLX paths share one sampler. Vocello now owns an independent Swift runtime and has already added separate residual controls, Qwen-specific speaker features, prompt schema 3, exact model-artifact identity, terminal barriers, and extensive device evidence. The report remains valuable as a hypothesis source, but its patch locations and several gap statements are outdated for this repository.

**Decision:** Translate every recommendation through a current-source parity table before implementation.

**Current-source references**

- [Owned-runtime ADR](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/docs/decisions/owned-qwen3-runtime-monorepo.md)
- [Semantic delta ledger](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Packages/VocelloQwen3Core/PATCHES.json)
- [Current Qwen source](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift)

### A-09 — The proposed sampler numbers are test points, not production defaults

**Classification:** Research correction

The bundle is candid that its content-safe, balanced, and expressive profiles are experimental. Vocello’s own June listening work found the official checkpoint defaults sounded best and deliberately describes variation as a consistency control rather than a quality ladder. The first experiment should isolate residual sampling while holding the main sampler at the official 0.9 / 50 / 1.0 / 1.05 baseline, then test main changes separately.

**Decision:** Do not remap Expressive/Balanced/Consistent or change defaults until paired, blinded, fixed-seed evidence passes.

**Current-source references**

- [Variation semantics](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/QwenVoiceCore/SemanticTypes.swift#L1337-L1375)
- [Product mapping](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/QwenVoiceCore/UnsafeSpeechGenerationModel.swift#L27-L50)
- [Historical quality decision](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/benchmarks/OPTIMIZATION.md#L63-L78)

### A-10 — The Python scaffold is a useful shape, but its scorers and assembly are not production-grade

**Classification:** Research correction

The scaffold has excellent strict request validation and manifest discipline. Its WER tokenization is not appropriate for Chinese or Japanese, ASR/LID/speaker hooks are interfaces rather than implementations, the risky-token regex is narrow and Latin-centric, model validation trusts name strings, and blanket equal-power crossfade can overlap phonemes or erase intentional pause semantics. It should inspire contracts and tests, not be ported line by line.

**Decision:** Reuse the manifest, staged-gate, and failure-taxonomy concepts inside the existing Swift/evidence system; replace the scoring and assembly algorithms.

**Current-source references**

- [Language benchmark guide](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/docs/reference/language-bench.md)
- [Current streaming/QC implementation](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/QwenVoiceCore/NativeStreamingSynthesisSession.swift)

## 17. Recommended first experiment package

### Experiment Q1 — Split sampler

- current main `079757abc3524ad5c0308bb1d914a9ff151c0de6`;
- canonical 1.7B 4-bit Speed artifacts;
- A0–A5 policies;
- six priority languages;
- all three modes;
- transcript and x-vector clone;
- five fixed seeds;
- 0.32 s streaming;
- exact current normalizer/segmenter;
- WER/CER, LID, speaker/onset, F0/energy/rate, EOS, QC, RTF, memory;
- no user-facing setting change.

### Experiment Q2 — Frontend and segmenter

- official sampling;
- raw versus spoken-normalized text;
- current 900-char versus planned 8–20 s/token-aware segments;
- direct VoiceDesign versus design→clone lock;
- issue #30 reproduction text where available;
- adjacent-segment speaker, pitch, rate and boundary metrics;
- final joined ASR.

### Experiment Q3 — Reference matrix

- 3/5/8/10/15/20/30 seconds;
- transcript-backed/x-vector;
- native/cross-lingual;
- clean/noisy/reverberant;
- onset and full speaker similarity;
- WER/CER and prosody;
- prep time, artifact size and memory.

These three experiments can determine whether custom quantization is warranted.

## 18. Final recommendation

The research should be leveraged as a **quality experiment framework**, not a patch list.

The most likely path to meaningful improvement is deterministic spoken-text correctness, better long-form segmentation, fixed long-form identity through a reusable clone prompt, typed dual-stage sampler experiments, selective retry on failures, and custom quantization only after a residual error remains.

### Approve immediately

- quality experiment contract;
- typed dual-stage sampling policy behind diagnostics;
- spoken-text normalizer architecture;
- duration/token-aware segment-plan architecture;
- VoiceDesign→clone long-form A/B;
- reference-length calibration.

### Approve as a limited pilot

- selective best-of-two for Mac long-form failures;
- boundary-aware assembly;
- streaming parity tests.

### Do not ship yet

- the bundle’s sampler numbers;
- four/six candidates by default;
- non-streaming product generation;
- group-32 or protected-projection models;
- the raw Python scaffold;
- new clone-duration warnings.

**Conclusion:** there is substantial leverage, and most of it can be realized inside the existing owned Swift backend without changing model weights. The research makes a strong case for custom INT4 experiments later, but it does not establish that quantization is the dominant remaining quality bottleneck.

## Appendix A — Research files reviewed

- `qwen3_tts_1_7b_4bit_research_report_source.md`
- `qwen3tts_1_7b_4bit_pipeline.py`
- `sampler_profiles.json`
- `implementation_notes.md`
- `evaluation_protocol.md`
- `evidence_matrix.csv`
- `SHA256SUMS`

The archive checksums were verified before analysis.

## Appendix B — Source index

| Subject | Source |
| --- | --- |
| Current Vocello source | [commit `079757abc3524ad5c0308bb1d914a9ff151c0de6`](https://github.com/PowerBeef/Vocello/commit/079757abc3524ad5c0308bb1d914a9ff151c0de6) |
| Official Qwen3-TTS | [Qwen3-TTS repository](https://github.com/QwenLM/Qwen3-TTS) |
| Project health | [docs/project-health.md](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/docs/project-health.md) |
| Development evidence | [docs/development-progress.md](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/docs/development-progress.md) |
| Qwen hot loop | [Qwen3TTS.swift](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift) |
| Qwen speaker frontend | [Qwen3TTSSpeakerMelFrontend.swift](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSSpeakerMelFrontend.swift) |
| Facade contracts | [Contracts.swift](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Packages/VocelloQwen3Core/Sources/VocelloQwen3Core/Contracts.swift) |
| Product sampler adapter | [UnsafeSpeechGenerationModel.swift](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/QwenVoiceCore/UnsafeSpeechGenerationModel.swift) |
| Product semantics | [GenerationSemantics.swift](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/QwenVoiceCore/GenerationSemantics.swift) |
| Language detection | [PromptLanguageDetector.swift](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/QwenVoiceCore/PromptLanguageDetector.swift) |
| Long-form batch | [BatchGenerationRunner.swift](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/Services/BatchGenerationRunner.swift) |
| Clone conditioning | [NativeCloneSupport.swift](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/QwenVoiceCore/NativeCloneSupport.swift) |
| Optimization history | [benchmarks/OPTIMIZATION.md](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/benchmarks/OPTIMIZATION.md) |
| Benchmark history | [benchmarks/HISTORY.md](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/benchmarks/HISTORY.md) |
| Long-form consistency issue | [Issue #30](https://github.com/PowerBeef/Vocello/issues/30) |
| Debug controls | [runtime-debug-knobs.json](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/config/runtime-debug-knobs.json) |

## Appendix C — Confidence boundary

High-confidence conclusions:

- Vocello already implements a low-level split between main and residual sampling.
- Full multilingual spoken-form normalization is not a first-class generation contract.
- The long-form segmenter is character-based and not duration/token aware.
- Direct VoiceDesign batch is not the same identity guarantee as one reusable clone prompt.
- The supplied profiles and quantization changes have not been proven by matched audio evidence.
- Non-streaming should remain a QA reference rather than replace the product path.

Medium-confidence hypotheses requiring experiments:

- residual sampler decoupling can improve timbre/prosody without lexical regression;
- design→clone locking will materially improve long-form identity;
- selective best-of-two captures a useful fraction of N-best gains;
- group-32 or protected projections improve quality.
 Prepared from the supplied research bundle and exact-ref GitHub source at 079757abc3524ad5c0308bb1d914a9ff151c0de6. Experimental recommendations remain subject to matched audio and hardware evidence.
