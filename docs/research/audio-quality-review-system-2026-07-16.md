---
status: historical
owner: backend-mlx
summary: Vocello Audio Quality Review System. Imported point-in-time research snapshot. Pinned: superseded figures carry inline editor's notes; contract JSON remains status authority.
contentDigest: sha256:ed1d71a600db7c54e5d01ef9a817ee824a0faeb376e6d4d2d30cc75418701150
---
# Vocello Audio Quality Review System

> **Imported research snapshot (2026-07-16).** Converted 2026-07-22 from the external HTML
> report bundle into the repository so corrections and review history stay tracked. Every
> measured figure below is a point-in-time capture from on or before 2026-07-16; the
> 2026-07-22 backend refactor review counter-verified this corpus and found its measured
> claims correct at capture with several since superseded. Superseded figures carry inline
> **Editor's note** blocks; see [`docs/research/README.md`](README.md) for the verification
> summary and [`config/runtime-refactor-contract.json`](../../config/runtime-refactor-contract.json)
> for current phase status.


**Document class:** Authoritative design and implementation reference
 **Recommended repository path:** `docs/reference/audio-quality-review-system.md`
 **Reviewed source:** [`main` at `079757abc3524ad5c0308bb1d914a9ff151c0de6`](https://github.com/PowerBeef/Vocello/commit/079757abc3524ad5c0308bb1d914a9ff151c0de6)
 **Reference date:** July 16, 2026
 **Target development hardware:** Mac mini M2, 8 GB unified memory
 **Applies to:** Qwen3-TTS 12Hz 1.7B Speed/Quality; Custom Voice, Voice Design and Voice Cloning
 **Primary objective:** Improve output correctness, voice consistency, delivery adherence and acoustic reliability without requiring routine human listening   3 modes fast · standard · canonical   **System contract.** Vocello quality review is a layered, deterministic and resource-aware evidence system. It never treats one opaque “quality score” as proof. It first establishes lifecycle and file correctness, then evaluates signal integrity, lexical and language accuracy, prosody, delivery, speaker identity, streaming boundaries, long-form continuity and resource behavior. Expensive checks are scheduled sequentially and only when required. Candidate regeneration is selective, never the default.    1MLX model resident at a time 0required human listens 9quality layers 3review depths 2maximum automatic candidates <512MB analyzer working-set target

>

This document specifies the target system. Current Vocello already implements substantial parts: persisted-WAV signal QC, three-pass on-device Speech verification, low-memory prosody analysis, paired delivery testing, exact model/evidence identity and a strong benchmark publication system. The remaining work is to unify those pieces and add codec diagnostics, critical-token accuracy, speaker identity, streaming-boundary analysis, long-form consistency and resource-aware candidate selection.

## 1. Purpose

The Audio Quality Review System answers five separate questions:

1.

**Did generation complete correctly?**
 The request must have one terminal outcome, valid output, no cancellation/failure ambiguity and no token-cap truncation.
2.

**Is the produced waveform technically valid?**
 The WAV must be readable, finite, non-empty, correctly formatted and free of unacceptable clipping, clicks, DC offset, dropouts and silence anomalies.
3.

**Did it say the intended content in the intended language?**
 Automated transcription, language checks and critical-token alignment must verify words, numbers, names, dates, units and other high-consequence spans.
4.

**Did it preserve the intended voice and delivery?**
 Speaker/onset similarity, F0, rate, pause and energy evidence must show that the requested identity and delivery remained coherent.
5.

**Is it acceptable as part of the surrounding product workflow?**
 Streaming must not damage chunk continuity; long-form segments must remain consistent; memory and latency must stay within platform policy.

No single metric can answer all five questions. A waveform may be clean but say the wrong number. It may have low WER but use the wrong voice. It may preserve voice identity while ignoring a delivery instruction. The system therefore uses independent gates and a structured verdict.

### Non-goals

The system does not claim to prove:

- universal beauty or artistic preference;
- that every listener will prefer one valid take;
- emotional truth beyond measurable delivery dimensions;
- absence of every rare model failure;
- equivalence to a large human MOS panel.

Human listening may be retained as optional research annotation. It cannot waive a machine failure and is not required for ordinary development, benchmark promotion or release qualification.

## 2. Design principles

### 2.1 Correctness before preference

The decision order is:

```
terminal and output validity
→ lexical and critical-token correctness
→ language
→ speaker identity
→ requested delivery
→ prosody naturalness
→ signal cleanliness
→ performance and memory

```

A candidate with a lower WER always outranks a candidate with prettier pitch dynamics when the latter says the wrong content.

### 2.2 Independent gates, not one blended score

The top-level verdict is one of:

```
public enum QualityVerdict: String, Codable, Sendable {
    case pass
    case warn
    case fail
    case notEvaluated = "not_evaluated"
}

```

A failure cannot be canceled by positive results in another layer. Weighted scores may be used only to rank candidates that already pass every mandatory gate.

### 2.3 Version every algorithm and threshold profile

Every report records:

- source commit and dirty state;
- model repository/revision/artifact version/integrity digest;
- request and sampling policy identity;
- spoken-text and segment-plan versions;
- analyzer algorithm versions;
- threshold/profile versions;
- review mode;
- hardware and toolchain where required.

A changed algorithm invalidates only the evidence domains that use it.

### 2.4 Fail closed for required evidence

If a required canonical check is unavailable, the result is not a pass. Examples:

- inconsistent ASR repetitions;
- unavailable locale asset;
- unreadable WAV;
- missing speaker evaluator for a required clone gate;
- incomplete streaming sequence;
- missing source/model identity.

Exploratory and standard modes may report `unavailable` as a warning when the check is optional.

### 2.5 Resource policy is part of correctness

The 8 GB Mac mini constraint is not a testing inconvenience. It is an architectural requirement:

- one MLX model resident at a time;
- no parallel TTS candidate generation;
- no heavy neural quality judge beside the TTS model;
- sequential ASR and speaker analysis after generation;
- bounded frame processing;
- digest-keyed result caches;
- no retained raw analysis arrays in durable evidence.

### 2.6 The immutable final WAV is authoritative

Live preview is a product feature. Quality review operates on the persisted final WAV and uses streaming metadata only to verify how that WAV was produced.

## 3. Existing Vocello foundation

| Capability | Current implementation | Reference |
| --- | --- | --- |
| Persisted-WAV signal QC | Readability, duration, peak, clipped/hot/non-finite samples, clicks, longest silence, RMS and DC offset | [AudioQualityGate.swift](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/Services/AudioQualityGate.swift#L6-L87) |
| Canonical ASR verification | Three repetitions of one immutable WAV, exact consensus, language score and WER/CER | [GenerationOutputVerifier.swift](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/SharedSupport/Services/GenerationOutputVerifier.swift#L6-L166) |
| Language-specific edit metric | CER for Chinese/Japanese; WER for remaining supported languages | [metric selection](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/SharedSupport/Services/GenerationOutputVerifier.swift#L208-L214) |
| Low-memory prosody | NumPy/stdlib F0, rate, pause and energy features; one WAV at a time; no model | [analyze_prosody.py](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/scripts/analyze_prosody.py#L3-L17) |
| Reference-free prosody gate | Monotone, rushed, flat and pause anomalies | [prosody_quality_gate.py](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/scripts/prosody_quality_gate.py#L3-L76) |
| Versioned prosody profile | Conservative threshold and delivery-weight schema | [prosody_profile.py](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/scripts/prosody_profile.py#L3-L53) |
| Paired delivery adherence | Neutral and instructed takes use the same seed, speaker and text | [delivery_adherence.py](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/scripts/delivery_adherence.py#L4-L20) |
| Detailed Qwen runtime metrics | EOS, token cap, code count, hot-loop timing, codec and cache diagnostics | [Qwen3TTS.swift](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift#L2820-L3030) |
| Long-form manifest | Segment text, path, stats, QC and completion state | [BatchGenerationRunner.swift](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/Services/BatchGenerationRunner.swift#L124-L155) |
| Current evidence governance | Critical-domain freshness, direct tests and canonical Mac/iPhone runs | [project-health.md](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/docs/project-health.md#L3-L42) |

### Gap summary

Current checks are individually strong, but they do not yet produce one unified report or one deterministic selection policy. The most important missing components are:

- codec-token anomaly summaries;
- critical-token lexical accuracy;
- semitone-normalized and profile-calibrated prosody;
- delivery-family expectations;
- speaker and onset identity;
- streaming boundary continuity;
- adjacent-segment consistency;
- resource-aware selective retry;
- one schema and one gate registry.

## 4. Review modes

### 4.1 Fast mode

**Purpose:** every focused backend development run and cheap batch triage.

**Required layers:**

- source/model/request identity;
- terminal and token-cap correctness;
- codec repetition/collapse summaries;
- final-WAV readability and format;
- signal QC;
- reference-free prosody;
- chunk/stream sequence checks when streaming;
- RTF and memory summary.

**Resource rule:** no additional model and no ASR.

**Expected cost:** small relative to generation; target analyzer working set below 256 MB for a typical clip and below 512 MB for long clips.

### 4.2 Standard mode

**Purpose:** relevant pull requests, focused experiments, quality-assisted long-form work.

Includes Fast mode plus:

- one-pass local ASR;
- language and WER/CER;
- critical-token accuracy;
- speaker/onset identity when the evaluator is already available or the workflow explicitly requests it;
- adjacent-segment analysis for long form.

**Resource rule:** generation completes first. TTS may be unloaded before an evaluator model is loaded.

### 4.3 Canonical mode

**Purpose:** benchmark history, model/sampler promotion, release qualification and public quality claims.

Includes Standard mode plus:

- three-pass exact-consensus ASR;
- full language-appropriate WER/CER evidence;
- paired same-seed delivery controls;
- complete speaker/onset evaluation where applicable;
- long-form joined-output verification;
- robust calibrated outlier profiles;
- exact hardware/toolchain/source/model identities;
- evidence manifest and freshness validation.

**Resource rule:** all model-dependent phases execute sequentially. No candidate generation runs in parallel.

### Mode matrix

| Layer | Fast | Standard | Canonical |
| --- | --- | --- | --- |
| Terminal / EOS / token cap | Required | Required | Required |
| Codec anomaly summaries | Required | Required | Required |
| Persisted-WAV signal QC | Required | Required | Required |
| Reference-free prosody | Required | Required | Required |
| Streaming continuity | When streaming | When streaming | Required when streaming |
| ASR | — | One pass | Three-pass consensus |
| Critical-token accuracy | — | Required when text contains risks | Required |
| Language | Prompt plus optional ASR | Required | Required |
| Speaker identity | Workflow-dependent | Optional/required for clone | Required for clone/preset claims |
| Delivery adherence | — | Focused A/B | Required for delivery promotion |
| Long-form consistency | Basic | Required for batch | Required |
| Candidate retry | — | Max 2, failure-triggered | Experiment-defined |
| Hardware/evidence identity | Basic | Exact source/model | Complete canonical |

## 5. Unified report contract

The canonical report is `GenerationQualityReport`. The companion JSON Schema in this deliverable is a draft implementation artifact.

```
public struct GenerationQualityReport: Codable, Sendable {
    public let schemaVersion: Int
    public let algorithmBundleVersion: String

    public let generationID: UUID
    public let audioSHA256: String
    public let reviewMode: QualityReviewMode

    public let source: QualitySourceIdentity
    public let model: QualityModelIdentity
    public let request: QualityRequestIdentity

    public let terminal: TerminalQualityReport
    public let codec: CodecQualityReport?
    public let signal: SignalQualityReport
    public let accuracy: AccuracyQualityReport?
    public let language: LanguageQualityReport?
    public let prosody: ProsodyQualityReport?
    public let delivery: DeliveryQualityReport?
    public let speaker: SpeakerQualityReport?
    public let streaming: StreamingQualityReport?
    public let longForm: LongFormQualityReport?
    public let resources: ResourceQualityReport?

    public let verdict: QualityVerdict
    public let failures: [QualityFinding]
    public let warnings: [QualityFinding]
}

```

### Required identity

The report must never be accepted without:

- generation UUID;
- final WAV SHA-256;
- exact source commit and dirty state;
- model ID, artifact version and installed integrity digest;
- mode and resolved language;
- text digest and length;
- sampling-policy ID and seed when available;
- analyzer bundle version;
- review mode.

### Privacy

Durable reports should contain:

- text digest and length, not raw text;
- critical-token category counts, not token content, unless retained in an explicitly private local bundle;
- model and configuration identities;
- metrics, flags and algorithm versions;
- relative or opaque artifact identifiers instead of user paths.

Raw transcripts, prompt text, reference paths and audio remain local and untracked.

## 6. Verdict and gate semantics

### 6.1 Gate states

Every layer returns:

```
public enum QualityGateStatus: String, Codable, Sendable {
    case pass
    case warn
    case fail
    case unavailable
    case notEvaluated = "not_evaluated"
}

```

### 6.2 Final verdict

```
fail:
  any required gate failed
  OR a required gate was unavailable
  OR identity/evidence was incomplete

warn:
  no required failure
  AND one or more allowed warning conditions

pass:
  every required gate passed
  AND no warning condition remained

not_evaluated:
  report could not establish the minimum fast-mode contract

```

### 6.3 Candidate comparison

Do not sum every metric into one score. Rank passing candidates lexicographically:

1. terminal validity;
2. critical-token error count;
3. language-specific WER/CER;
4. language score;
5. speaker/onset similarity;
6. delivery-direction agreement;
7. prosody anomaly count and robust distance;
8. signal warnings;
9. latency and memory.

Only compare values produced by the same algorithm/profile version.

## 7. Layer 1 — Terminal and generation integrity

### Required checks

- exactly one terminal event;
- terminal generation ID matches request and output;
- finish reason is EOS for a successful full output;
- token cap is not treated as success;
- no output is promoted after cancellation or failure;
- generated-code count is positive and plausible for the text;
- output file exists only after finalization;
- partial/session artifacts are cleaned or explicitly marked incomplete;
- telemetry and final result agree on finish reason.

### Failure codes

```
terminal_missing
terminal_duplicate
terminal_identity_mismatch
unexpected_cancelled
generation_failed
token_cap_reached
empty_generation
output_missing
partial_output_published
terminal_telemetry_disagreement

```

### Expected-duration sanity

Maintain a broad, language- and mode-specific duration-per-token or duration-per-character envelope. This is not a speech-rate quality score; it is a truncation/runaway detector.

A single outlier should warn. Extreme under-duration, over-duration or a mismatch with generated codec count should fail.

## 8. Layer 2 — Codec-token diagnostics

The Qwen loop already has the semantic token, residual codebook outputs, EOS state and generated-code count. Add streaming summaries without retaining raw sequences by default.

### Metrics

```
semantic_unique_token_ratio
semantic_bigram_repeat_rate
semantic_trigram_repeat_rate
semantic_longest_repeat_run
semantic_eos_position_ratio

codec_frame_count
codec_identical_frame_run_max
codec_unique_frame_ratio

residual_codebook_entropy_min
residual_codebook_entropy_mean
residual_codebook_occupancy_min
residual_collapsed_codebook_count

generated_codes_per_text_token
generated_codes_per_character

```

### Detection goals

- semantic repetition and stuck phrases;
- repeated codec frames;
- residual-codebook collapse;
- premature EOS;
- unusually late EOS;
- output length inconsistent with input;
- abnormal behavior after a sampler or quantization change.

### Resource implementation

Use integer counts and small hash maps. Do not retain all 16-codebook frames in the final report. A rolling n-gram detector and per-codebook histogram are sufficient.

### Proposed status policy

- repeated terminal-size runs or near-zero residual occupancy: fail;
- abnormal but non-catastrophic repetition: warn;
- profile outlier without audible/ASR consequence: warn;
- values inside calibrated peer distribution: pass.

## 9. Layer 3 — Persisted-WAV signal quality

The existing persisted-WAV analyzer remains the canonical signal layer.

### Required metrics

- readability;
- sample rate, channel count and sample format;
- duration;
- peak;
- RMS dBFS;
- clipped samples;
- hot samples;
- non-finite samples before PCM conversion where observable;
- DC offset;
- click/discontinuity events;
- longest interior silence;
- punctuation-aware long-pause budget;
- leading and trailing silence;
- all-zero or near-silent output.

### Hard failures

- unreadable or empty WAV;
- wrong format for the generated contract;
- non-finite values;
- severe clipping;
- severe DC offset;
- click/discontinuity above the canonical threshold;
- egregious unexplained silence;
- output duration inconsistent with frames;
- all-silent output.

### Warnings

- hot samples below the failure threshold;
- long but punctuation-compatible pauses;
- unusually low or high RMS;
- leading/trailing silence outside the preferred envelope;
- one mild discontinuity.

Thresholds remain owned by the versioned `AudioQCReport` algorithm. This document does not duplicate those numeric values.

## 10. Layer 4 — Lexical accuracy and language

### 10.1 ASR evidence

Canonical mode uses the existing three-pass exact-consensus policy on the same immutable WAV. Standard mode may use one pass.

Required evidence:

- recognizer locale;
- authorization and asset state;
- repetition count;
- final-result status;
- consensus status;
- transcript digest;
- WER and CER;
- language score;
- algorithm and normalization version.

### 10.2 Metric selection

- Chinese and Japanese: CER is the primary gate.
- Korean: report WER and character/syllable-block error; calibrate the primary gate.
- English, German, French, Russian, Portuguese, Spanish and Italian: WER is primary; CER remains diagnostic.
- Auto is never a canonical expected language.

### 10.3 Critical-token accuracy

Before generation, build a `SpokenTextPlan` and classify high-risk spans:

```
number
decimal
percentage
currency
date
time
measurement
proper_name
acronym
initialism
URL
email
version
mixed_script
custom_lexicon_entry

```

After ASR alignment, report:

```
critical_token_count
critical_substitutions
critical_insertions
critical_deletions
number_accuracy
date_time_accuracy
currency_accuracy
unit_accuracy
proper_name_accuracy
first_content_span_present
last_content_span_present

```

Canonical policy should normally require zero errors for explicitly marked high-consequence numbers, dates, currencies and units.

### 10.4 Spoken text is the reference

Accuracy must compare recognition against the expected spoken form, not necessarily the user’s original typography. The report records both text digests and the normalizer version without persisting private content in tracked evidence.

## 11. Layer 5 — Reference-free prosody

The current low-memory analyzer is the correct foundation. Upgrade its speaker independence and calibration.

### 11.1 Feature set

Retain:

- voiced fraction;
- median and range of F0;
- turning points;
- rising/falling behavior;
- estimated syllable rate;
- local-rate variability;
- pause count, duration and ratio;
- energy dynamics and roughness.

Add:

- F0 in semitones relative to the clip median;
- smoothed contour slope and phrase-final rise/fall;
- voicing transition rate;
- periodicity/HNR proxy;
- punctuation-aligned pause classification;
- phrase-level rate and energy features;
- first/last phrase statistics.

### 11.2 Semitone normalization

```
f0_semitones = 12 × log2(f0 / median_f0)

```

Use semitone standard deviation and p10–p90 range rather than absolute-Hz thresholds when comparing different speakers.

### 11.3 Profile selectors

A prosody profile is selected by:

```
mode
language
speaker or voice identity
delivery family
length bucket
model variant

```

Each profile stores robust median and median absolute deviation for the feature vector.

### 11.4 Robust anomaly policy

Initial recommended policy:

- one feature beyond the warning envelope: warn;
- multiple orthogonal features beyond the warning envelope: warn or fail according to profile;
- one feature beyond the severe envelope plus a corroborating metric: fail;
- no global threshold may hard-fail all voices and languages without calibration.

Use profile-defined bounds; do not bake the existing Hz thresholds into the permanent cross-speaker contract.

## 12. Layer 6 — Delivery adherence

Delivery is evaluated as a paired same-seed comparison against a neutral control.

### 12.1 Required control identity

The instructed and neutral takes must match on:

- model artifact;
- source commit;
- speaker/voice/reference;
- text and spoken-text plan;
- language;
- seed;
- main/residual sampler policy;
- streaming policy;
- runtime profile.

Only the instruction/delivery changes.

### 12.2 Delivery expectation vectors

Every delivery family declares expected directions:

| Family | Pitch median | Pitch range/dynamics | Rate | Pause ratio | Energy dynamics | Duration |
| --- | --- | --- | --- | --- | --- | --- |
| Excited / energetic | ↑ | ↑ | ↑ | ↓ | ↑ | ↓ |
| Calm / gentle | neutral/↓ | ↓ | ↓ | ↑ | ↓ | ↑ |
| Sad / somber | ↓ | neutral/↓ | ↓ | ↑ | ↓ | ↑ |
| Authoritative | neutral/↓ | controlled | slight ↓ | deliberate ↑ | stable | slight ↑ |
| Surprised | onset ↑ | ↑ | variable ↑ | ↓ | sharp onset ↑ | neutral/↓ |
| Whisper / breathy | unreliable F0 | profile-specific | often ↓ | neutral/↑ | ↓ | ↑ |

### 12.3 Metrics

```
direction_agreement
normalized_effect_magnitude
seed_consistency
accuracy_delta
speaker_similarity_delta
prosody_effect
arousal_effect

```

A delivery fails when it significantly harms lexical accuracy or speaker identity, even if the acoustic effect moves in the expected direction.

### 12.4 Abstract adjectives

Terms such as “warm,” “cinematic,” “luxurious” or “friendly” are not directly provable without a trained and calibrated semantic judge. The system reports measurable axes and labels the abstract interpretation as not evaluated.

## 13. Layer 7 — Speaker and onset identity

### 13.1 Evaluation strategy

Reuse the Qwen speaker encoder rather than adding a second large external model.

For Clone:

- compare generated output with the exact reference;
- evaluate the first 1.5–2.0 seconds and the full clip;
- compare transcript-backed and x-vector-only modes independently;
- check drift from beginning to end.

For Custom Voice:

- build accepted neutral centroids for each built-in speaker;
- compare the output with the requested centroid;
- compare against other speaker centroids;
- require the requested identity to be the nearest accepted prototype.

For Voice Design:

- use a selected identity anchor;
- for long form, prefer one reusable Base-clone prompt when the workflow requests identity locking.

### 13.2 Metrics

```
full_speaker_cosine
onset_speaker_cosine
ending_speaker_cosine
onset_to_full_delta
requested_centroid_margin
nearest_impostor_id
nearest_impostor_margin

```

### 13.3 Threshold calibration

Do not use one universal cosine value.

For each evaluator/model/profile:

- collect positive same-identity pairs;
- collect negative different-identity pairs;
- calculate distributions;
- choose a threshold with a safety margin around the equal-error region;
- version the evaluator and threshold profile.

### 13.4 Resource schedule

```
generate clips
→ unload TTS
→ clear MLX cache
→ load Base/speaker evaluator once
→ evaluate all clips sequentially
→ cache embeddings by WAV SHA-256
→ unload evaluator

```

No speaker model and TTS model should be resident concurrently on the 8 GB development machine unless an explicit memory-qualified experiment proves it safe.

## 14. Layer 8 — Streaming continuity

### Required checks

- chunk sequence is monotonic and complete;
- frame offsets are contiguous;
- no duplicate or missing frame ranges;
- preview PCM and final WAV agree on frame identity;
- final chunk and terminal ordering are correct;
- boundary amplitude discontinuity is below threshold;
- boundary derivative discontinuity is below threshold;
- local RMS and spectral change do not indicate a click;
- no unexplained silence is inserted at a non-punctuation boundary;
- no duplicated waveform occurs around a join.

### Boundary windows

Use short windows around known frame offsets, for example 50–100 ms per side. Avoid full-file spectral processing.

### Product policy

Streaming remains the production baseline. Non-streaming is an explicit reference lane for fixed-seed parity, not the default quality mode.

## 15. Layer 9 — Long-form continuity

### 15.1 Segment-plan identity

Every segment records:

- source range;
- spoken text digest;
- language;
- boundary type;
- estimated text tokens;
- estimated audio duration;
- maximum codec tokens;
- intended pause;
- shared identity/sampler policy.

### 15.2 Adjacent-segment metrics

```
speaker_cosine
onset_speaker_cosine
median_f0_delta_semitones
f0_range_delta
speaking_rate_delta
local_rate_cv_delta
pause_ratio_delta
rms_delta_db
duration_per_word_delta
boundary_click_score
boundary_silence_error

```

### 15.3 Batch-level robust profile

Calculate median and MAD across all segments. Report each segment’s robust distance. A segment can fail even when its individual signal QC passes if it is an identity or prosody outlier relative to the rest of the batch.

### 15.4 Joined-output verification

After assembly:

- rerun signal QC;
- transcribe the joined output or a boundary-focused sample plan;
- confirm no text loss/duplication;
- verify intended pause boundaries;
- verify no new clicks;
- record final duration and segment map.

### 15.5 Identity lock

For Voice Design long form, evaluate direct per-segment VoiceDesign against:

```
one designed reference
→ one Base clone conditioning handle
→ every segment synthesized from that handle

```

The better policy is determined by identity, accuracy, delivery and resource evidence.

## 16. Resource-aware execution scheduler

### 16.1 Default sequence

```
Phase A — Generate
  load one TTS model
  generate required clips serially
  collect terminal, codec, streaming and resource summaries

Phase B — Cheap CPU review
  persisted-WAV QC
  prosody
  boundary and long-form statistics
  token/codec summaries
  unload TTS if no further immediate generation is needed

Phase C — Accuracy
  run local ASR serially
  one pass for standard, three-pass consensus for canonical
  cache transcript evidence by audio digest + locale + algorithm

Phase D — Identity
  load speaker evaluator only when required
  calculate embeddings sequentially
  cache embeddings by audio digest + evaluator identity
  unload evaluator

Phase E — Selective repair
  identify failures
  reload TTS once
  regenerate only failed/risky candidates
  repeat required review for replacements

Phase F — Publish
  write one report and evidence manifest
  discard raw transient arrays

```

### 16.2 Memory budgets

| Component | Target |
| --- | --- |
| Non-model analyzer working set | under 512 MB |
| Concurrent WAVs held in memory | 1 |
| Concurrent ASR requests | 1 |
| Concurrent MLX generations | 1 |
| Resident MLX models | 1 |
| Candidate generation concurrency | 1 |
| Retained raw frame arrays | none after report |
| Retained speaker embeddings | compact vectors only |

These are design budgets, not current measured guarantees. Instrument and enforce them in canonical mode.

### 16.3 CPU policy

- default analyzer workers: 1;
- optional 2-worker CPU analysis only after TTS unload and memory check;
- use `float32` where numerically sufficient;
- stream/block long files;
- downsample pitch-analysis copies where validated;
- avoid full-file spectrogram retention.

## 17. Selective candidate generation

### Policy

```
public enum CandidateSelectionPolicy: Codable, Hashable, Sendable {
    case single
    case retryOnFailure(maxCandidates: Int)
    case offlineBestOf(Int)
}

```

Recommended defaults:

| Workflow | Policy |
| --- | --- |
| Interactive Mac | Single |
| iPhone | Single |
| Normal batch | Single |
| Failed long-form segment | Retry on failure, maximum 2 |
| Explicit Mac Quality Assist | Best of 2 |
| Research benchmark | Configurable |

### Candidate workflow

1. Generate candidate 1.
2. Run Fast checks.
3. If it fails a cheap gate, generate candidate 2 without running expensive evaluators first.
4. When generation is complete, run required ASR and speaker evaluation sequentially.
5. Select only among candidates that pass every mandatory gate.
6. Persist why the winner was selected.
7. Retain rejected artifacts only in an explicit diagnostic directory.

### No parallel candidate generation

Parallel Metal generations are outside the supported resource and lifecycle contract.

## 18. Calibration without routine human listening

Automated gates require a labelled corpus. Build it from accepted current outputs and deterministic mutations.

### 18.1 Positive corpus

Use clean canonical outputs across:

- all three modes;
- Speed and Quality where supported;
- all ten languages;
- representative speakers and voices;
- neutral and instructed delivery;
- short, medium and long;
- multiple seeds;
- transcript-backed and x-vector clone.

A positive corpus is source/model/profile bound. It is not automatically carried to a changed analyzer.

### 18.2 Synthetic negative mutations

| Mutation | Required detector |
| --- | --- |
| Hard clipping | Signal QC |
| DC offset | Signal QC |
| Non-finite samples before conversion | Output sanitization |
| 300/600/1,200 ms mid-word silence | Dropout and alignment |
| Equivalent sentence-boundary pause | Must not hard-fail |
| Join spike | Boundary click |
| Remove first word | ASR deletion / first-span |
| Remove final phrase | ASR deletion / last-span |
| Duplicate phrase | ASR insertion / repetition |
| Repeat codec/audio window | Codec repetition / ASR |
| Time stretch ±15–25% | Rate anomaly |
| Flatten F0 | Monotone |
| Pitch shift | Speaker/prosody |
| Flatten energy envelope | Flat delivery |
| Substitute another built-in speaker | Identity gate |
| Prepend reference audio | Clone leakage |
| Replace with another language | Language gate |

### 18.3 Calibration rules

- severe mutations must fail;
- mild mutations may warn;
- punctuation-compatible pauses should pass;
- current positives must not develop unexpected hard failures;
- threshold tuning uses a training partition;
- final performance is reported on held-out prompts and speakers;
- no threshold is tuned against the same candidate being promoted.

### 18.4 Robust baseline profiles

For each profile selector, store median and MAD. Use drift reports to identify whether a code/model change shifts the distribution even when individual gates pass.

## 19. Shipping boundary versus QA boundary

### Always-on shipping safeguards

Appropriate in normal generation:

- terminal and token-cap correctness;
- output existence and atomic finalization;
- finite/format/readability checks;
- severe signal QC;
- lightweight token/codec anomaly summaries;
- streaming sequence integrity;
- privacy-safe failure diagnostics.

### Optional product quality assist

Appropriate for Mac batch/export when explicitly enabled:

- Fast review;
- failure-triggered second candidate;
- one-pass ASR where permission/assets are available;
- joined long-form checks.

### Development and release QA only

- three-pass ASR;
- full speaker evaluator pass;
- paired neutral/instructed delivery matrix;
- robust baseline generation;
- synthetic mutation suite;
- non-streaming parity;
- full canonical hardware matrix;
- custom quantization/model comparisons.

No Python runtime or local server is added to the shipping app. Python remains development/evidence tooling.

## 20. Repository integration

### Proposed source and tooling changes

| Area | Proposed change |
| --- | --- |
| `Sources/QwenVoiceCore` | Add report identities, terminal/codec summaries and quality result types |
| `NativeStreamingSynthesisSession.swift` | Emit codec, stream-boundary and final-output evidence |
| `GenerationOutputVerifier.swift` | Add critical-token alignment, first/last span checks and standard/canonical modes |
| `AudioQualityGate.swift` | Remain adapter to the canonical persisted-WAV analyzer |
| `scripts/analyze_prosody.py` | Add semitone, phrase, voicing and block-processing features |
| `scripts/prosody_profile.py` | Add schema 2 selectors, median/MAD baselines and delivery expectations |
| `scripts/prosody_quality_gate.py` | Use profile-calibrated robust decisions |
| `scripts/delivery_adherence.py` | Style-specific direction agreement, accuracy delta and identity delta |
| `BatchGenerationRunner.swift` | Add SegmentPlan, adjacent consistency and selective retry |
| `NativeCloneSupport.swift` | Expose evaluator identity/reference embedding where safe |
| New `QualityReviewCoordinator` | Schedule Fast/Standard/Canonical phases without overlapping models |
| New `LongFormAudioAssembler` | Boundary-aware pause, loudness and fade policy |
| Benchmark schemas/scripts | Add unified report and quality experiment evidence |

### Proposed configuration files

```
config/quality-review-contract.json
config/quality-gate-registry.json
config/prosody-profiles/
config/delivery-expectations.json
config/quality-mutation-fixtures.json
config/spoken-text-normalizer.json

```

### Project-health integration

Track:

- direct test cases by quality layer;
- last canonical evidence by layer;
- analyzer/profile versions;
- stale domains after changed paths;
- synthetic mutation detection rate;
- canonical positive false-failure rate;
- candidate retry acceptance gain;
- analyzer memory/time overhead.

## 21. CLI and automation interface

Proposed commands:

```
# Fast signal/prosody/codec review
build/vocello quality inspect output.wav   --manifest request.json   --mode fast   --json

# Standard accuracy review
build/vocello quality inspect output.wav   --manifest request.json   --mode standard   --expected-text expected-spoken.txt   --language english   --json

# Paired delivery review
build/vocello quality compare   --neutral neutral.wav   --candidate excited.wav   --delivery excited.normal   --manifest pair.json

# Long-form continuity
build/vocello quality batch   --manifest long-form-manifest.json   --mode standard

# Canonical benchmark integration
build/vocello bench   --quality-review canonical   --quality-profile release-v1

```

Development scripts may call the same underlying report builder. Standard output remains machine-readable; progress and diagnostics use standard error.

## 22. Test strategy

### Unit tests

- report schema encoding/decoding;
- verdict aggregation;
- lexicographic candidate ranking;
- critical-token classification/alignment;
- semitone conversion;
- robust median/MAD profile logic;
- delivery expectation directions;
- token repetition and codebook occupancy;
- boundary window metrics;
- long-form outlier detection;
- resource scheduler state transitions.

### Fixture tests

- known-good WAVs;
- every synthetic mutation;
- language-specific normalization;
- CJK CER;
- Korean dual metric;
- speaker same/different pairs;
- delivery neutral/instructed pairs;
- streaming/final parity;
- long-form segment joins.

### Integration tests

- one complete Fast report;
- Standard report with one-pass ASR;
- Canonical three-pass consensus;
- TTS unload before speaker evaluator;
- selective retry only after failure;
- no concurrent MLX models;
- report and evidence identity;
- privacy redaction.

### Hardware tests

- M2 8 GB analyzer working set;
- canonical Mac timing/overhead;
- iPhone Standard subset where supported;
- long-form memory and cleanup;
- candidate-2 reload sequence;
- no regression to TTS RTF outside declared tolerance.

## 23. Acceptance criteria

The first complete implementation is accepted when:

1. One report schema covers every quality layer.
2. Existing signal QC, ASR and prosody evidence are represented without losing detail.
3. Fast mode adds negligible model memory and remains bounded on long files.
4. Standard and Canonical phases never overlap two MLX models.
5. Severe synthetic defects are detected.
6. Punctuation-compatible pauses do not become false failures.
7. Critical numeric/date/unit errors hard-fail.
8. CJK uses CER and Korean reports an additional character-level metric.
9. Speaker thresholds are calibrated from positive and negative distributions.
10. Delivery expectations are style-specific.
11. Long-form reports identify injected speaker/rate/pitch discontinuities.
12. Streaming-boundary defects are detected from known offsets.
13. Selective retry never exceeds two candidates by default.
14. Candidate ranking never prefers lower lexical correctness.
15. Every result is source/model/request/analyzer bound.
16. Tracked evidence contains no prompt, transcript, reference path or raw user audio.
17. Project health reports quality-layer coverage and freshness.
18. Canonical current outputs do not experience unacceptable false failures.
19. Analyzer overhead is measured and remains within the 8 GB machine budget.
20. Documentation and configuration versions are synchronized.

## 24. Rollout plan

### Phase 0 — Contract and unification

- Add report schema and gate registry.
- Adapt current signal QC, output verifier and prosody report.
- Add Fast/Standard/Canonical modes.
- Add digest-keyed report caching.
- Add current canonical outputs as positive fixtures.

### Phase 1 — Accuracy and codec evidence

- Add codec-token summaries.
- Add spoken-text/critical-token plan.
- Add first/last content coverage.
- Add Korean character metric.
- Add synthetic lexical and codec mutations.

### Phase 2 — Prosody and delivery calibration

- Add semitone features.
- Add profile selectors and robust baselines.
- Add style-specific delivery expectations.
- Add paired accuracy and identity deltas.
- Calibrate on held-out positives/mutations.

### Phase 3 — Speaker and long form

- Add sequential Qwen speaker evaluation.
- Build speaker centroids.
- Add onset/full/ending similarity.
- Add SegmentPlan and adjacent consistency.
- Test VoiceDesign-to-clone identity lock.

### Phase 4 — Selective Quality Assist

- Add failure-triggered candidate 2.
- Add Mac long-form selection.
- Measure accepted-output gain, latency, energy and memory.
- Keep iPhone and interactive generation single-candidate by default.

### Phase 5 — Release qualification

- Run full canonical current-source matrix.
- Publish versioned profile/evidence.
- Mark quality-review domain fresh.
- Use the system for model, sampler and quantization promotion.

## 25. Risks and guardrails

| Risk | Guardrail |
| --- | --- |
| ASR rejects a correct accent or name | Critical-token lexicon, language calibration, warnings for ambiguous scorer output |
| Prosody thresholds penalize natural voice differences | Semitone features and speaker/language/delivery-specific profiles |
| Automated system optimizes toward one metric | Independent mandatory gates and lexicographic ranking |
| Speaker evaluator consumes too much memory | Sequential model load and digest-cached embeddings |
| Candidate retry doubles latency | Failure-triggered maximum 2; never default for interactive/iPhone |
| Crossfade masks real segment drift | Identity/prosody checks precede assembly; fade only inside non-speech |
| Synthetic calibration misses real defects | Maintain issue-derived fixtures and robust peer outlier detection |
| Canonical positives become the only accepted style | Multiple speakers, deliveries, languages and seeds in the positive corpus |
| User content leaks into evidence | Digests/counts only; raw data local and untracked |
| Analyzer behavior changes silently | Algorithm/profile versions in every report |
| QA tools alter product behavior | Separate review modes, explicit gates and evidence-impact rules |
| 8 GB machine thrashes | One model at a time, bounded arrays, sequential phases and working-set telemetry |

## 26. Source references

| Subject | Current source |
| --- | --- |
| Reviewed source | [commit `079757abc3524ad5c0308bb1d914a9ff151c0de6`](https://github.com/PowerBeef/Vocello/commit/079757abc3524ad5c0308bb1d914a9ff151c0de6) |
| Persisted-WAV signal QC | [AudioQualityGate.swift](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/Services/AudioQualityGate.swift) |
| ASR accuracy and language | [GenerationOutputVerifier.swift](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/SharedSupport/Services/GenerationOutputVerifier.swift) |
| Low-memory prosody analyzer | [analyze_prosody.py](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/scripts/analyze_prosody.py) |
| Prosody gate | [prosody_quality_gate.py](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/scripts/prosody_quality_gate.py) |
| Prosody profiles | [prosody_profile.py](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/scripts/prosody_profile.py) |
| Delivery adherence | [delivery_adherence.py](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/scripts/delivery_adherence.py) |
| Prosody research | [prosody-qa-research.md](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/docs/reference/prosody-qa-research.md) |
| Qwen token loop | [Qwen3TTS.swift](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift) |
| Product generation semantics | [GenerationSemantics.swift](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/QwenVoiceCore/GenerationSemantics.swift) |
| Long-form batch | [BatchGenerationRunner.swift](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/Services/BatchGenerationRunner.swift) |
| Project health | [project-health.md](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/docs/project-health.md) |
| Current implementation status | [development-progress.md](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/docs/development-progress.md) |

## Appendix A — Example report

```
{
  "schemaVersion": 1,
  "algorithmBundleVersion": "vocello-quality-v1",
  "generationID": "00000000-0000-0000-0000-000000000001",
  "audioSHA256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "reviewMode": "standard",
  "source": {
    "commit": "079757abc3524ad5c0308bb1d914a9ff151c0de6",
    "dirty": false,
    "toolchainDigest": "..."
  },
  "model": {
    "modelID": "custom-speed",
    "variant": "speed",
    "repository": "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
    "revision": "...",
    "artifactVersion": "...",
    "integrityDigest": "..."
  },
  "request": {
    "mode": "custom",
    "language": "english",
    "speakerOrVoiceID": "aiden",
    "conditioningMode": null,
    "deliveryProfile": "calm.normal",
    "samplingPolicyID": "official",
    "seed": 17,
    "textDigest": "...",
    "textLength": 143,
    "spokenTextPlanVersion": "spoken-v1",
    "segmentPlanVersion": null
  },
  "terminal": {
    "finishReason": "eos",
    "exactlyOnce": true,
    "tokenCapReached": false,
    "generatedCodeCount": 211,
    "codecFrameCount": 211
  },
  "codec": {
    "algorithmVersion": "codec-qc-v1",
    "status": "pass",
    "metrics": {
      "semantic_bigram_repeat_rate": 0.01,
      "residual_collapsed_codebook_count": 0
    },
    "flags": []
  },
  "signal": {
    "algorithmVersion": "persisted-wav-qc-v4",
    "status": "pass",
    "metrics": {
      "duration_seconds": 16.4,
      "peak": 0.81,
      "clipped_samples": 0,
      "click_events": 0
    },
    "flags": []
  },
  "accuracy": {
    "algorithmVersion": "language-output-verifier-v3",
    "status": "pass",
    "metrics": {
      "word_error_rate": 0.02,
      "critical_token_errors": 0
    },
    "flags": []
  },
  "language": {
    "algorithmVersion": "language-match-v1",
    "status": "pass",
    "metrics": {
      "language_match_score": 0.98
    },
    "flags": []
  },
  "prosody": {
    "algorithmVersion": "prosody-v2",
    "status": "pass",
    "metrics": {
      "f0_std_semitones": 2.2,
      "rate_syllables_per_second": 4.1,
      "pause_ratio": 0.14
    },
    "flags": []
  },
  "delivery": null,
  "speaker": null,
  "streaming": {
    "algorithmVersion": "stream-continuity-v1",
    "status": "pass",
    "metrics": {
      "missing_chunks": 0,
      "duplicate_chunks": 0,
      "boundary_clicks": 0
    },
    "flags": []
  },
  "longForm": null,
  "resources": {
    "algorithmVersion": "resource-v1",
    "status": "pass",
    "metrics": {
      "rtf": 1.03,
      "peak_physical_mb": 2980,
      "analyzer_peak_mb": 124
    },
    "flags": []
  },
  "verdict": "pass",
  "failures": [],
  "warnings": []
}

```

## Appendix B — Glossary

**Canonical:** clean, exact-source, exact-model, hardware-bound evidence eligible for trend comparison or release claims.

**Critical token:** a text span whose substitution or deletion has disproportionate correctness impact, such as a number, date, measurement or proper name.

**Delivery adherence:** measurable change between same-seed neutral and instructed output in the direction expected by the requested delivery.

**Fast mode:** model-free post-generation review suitable for routine development.

**MAD:** median absolute deviation, a robust measure of feature spread.

**Onset identity:** speaker similarity calculated from the beginning of the generated output, useful for detecting wrong-speaker starts or reference leakage.

**Spoken text plan:** deterministic, versioned representation of what the model is expected to say after locale-aware normalization.

**Standard mode:** focused review with one-pass ASR and optional identity/long-form checks.

**Canonical mode:** strict review with consensus ASR, complete identity/delivery evidence and exact publication metadata.   Repository-ready design reference aligned with QwenVoice main at 079757abc3524ad5c0308bb1d914a9ff151c0de6. Numeric thresholds remain owned by versioned analyzer/profile contracts.
