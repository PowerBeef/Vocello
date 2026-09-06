---
status: active
owner: backend-mlx
reviewed: 2026-09-06
summary: Source-grounded Audio QC architecture, corrected infrastructure defects, M2 resource measurements, accuracy limitations and compatibility-preserving next steps.
sourceOfTruth:
  - Sources/QwenVoiceCore/GenerationOutputAdapter.swift
  - Sources/QwenVoiceCore/GenerationQualityComposition.swift
  - Sources/SharedSupport/Services/VoiceClipTranscriber.swift
  - scripts/analyze_prosody.py
  - scripts/delivery_analysis_cache.py
  - scripts/delivery_experiment_runner.py
  - scripts/run_local_delivery_cascade.py
  - scripts/prosody_quality_gate.py
  - scripts/check_language_output.py
  - config/audio-cadence-qc-contract.json
  - config/prosody-holdout-policy.json
  - config/roadmap.json
---
# Audio QC: engineering review and consolidation

The September 6 review began at `25b305f1`. This is a living technical reference, not a
second roadmap or a new release gate. AV-07 owns acoustic calibration, AV-08 multilingual
validity, DP-28 the experimental evaluator, and RF-06 the unresolved product audio.
User-requested QC engineering does not close any of those acceptance gates.

## What exists and what each result means

| Layer | Implementation | Meaning and authority |
| --- | --- | --- |
| Product safety | `GenerationOutputAdapter.swift`, `PersistedWAVAudioQCAnalyzer`, limiter and atomic writer | Fast-QC v6 examines final marked PCM and retains pre-write instability. Hard failures prevent publication; ordinary cadence warnings remain visible. |
| Product adapters | macOS/iOS `AudioQualityGate.swift` | Both delegate to the same core analyzer. Duplicate presentation adapters, **not** separate thresholds. |
| Spoken content | `VoiceClipTranscriber.swift`, `check_language_output.py` | Three locale-locked recognitions of the exact WAV, edge evidence, WER/CER, language checks. Repeatability is not three independent ASR systems. |
| Acoustic measurement | `analyze_prosody.py` v3, `delivery_temporal_features.py` v1 | Two bounded passes each: global features and five-region contours. Measures signal properties, not listener-recognized emotion. |
| Acoustic decisions | `prosody_quality_gate.py`, `delivery_quality_gate.py`, frozen profile | Warn-first heuristics; incomplete measurement must not become PASS. AV-07's independent calibration is still missing. |
| Local research | experiment runner, analysis cache, compact adapter, resource supervisor, cascade, evaluator | Source-bound serial screening; absent calibrated heads abstain. Requested follow-up layers are **requests**, not executed ASR/UTMOS evidence. No semantic promotion authority. |
| Release composition | typed quality producer/composer, specialized benchmark and promotion validators | Required missing/warning/failure evidence remains blocking. An experimental cascade completing is not release PASS. |

The existing production safety core is already shared and file-bounded. A second Python
implementation of its thresholds would create drift, not simplification. Keep native Fast QC
on the published-byte boundary; reuse its receipts in higher-level reports.

### Scoped coverage review

- Six core quality/WAV test classes contain 54 XCTest test methods in the inspected subset.
- They execute without UI, UIKit, SwiftUI, a phone, or a model.
- Producer/composer tests distinguish warning, unavailable, missing mandatory evidence and PASS.
- Publication tests exercise persisted frames, DC offset and silence across read boundaries.
- The inspected native subset has no fixed sleeps, mutable static test state or force-cast traps.
- Python global and temporal fixtures cover synthetic pitch, noise, pauses and bounded buffers.
- Cache/cascade fixtures previously missed truncated WAVs, preprocessing-record drift and early stopping.
- Prosody gate fixtures previously exercised missing keys but not invalid numeric values.
- Independent listener-labelled multilingual accuracy is a **known coverage gap**, not established by synthetic tones.

## Confirmed defects and this implementation

| Finding | Evidence before repair | Correction / regression boundary |
| --- | --- | --- |
| Non-finite metrics could pass | `evaluate_metrics` only checked key presence; NaN comparisons were false, yielding no quality flag. Other types raised uncaught errors. | Require finite, non-Boolean numbers for required and supplied optional measurements. Emit existing `metrics_incomplete`, not a product-audio diagnosis. No threshold changed. |
| Cache memory grew with duration | `_canonical_pcm` retained a list of every encoded block and joined a second full copy. | Stream into an operation-owned temporary file, hash incrementally, fsync, validate source, then atomically publish. |
| Cache accepted inconsistent preprocessing | A valid record digest did not validate rate, channels, resampler version, sample count or duration. | Strict metadata/type/count validation, derivative digest check, and source rehash before publication. Old valid v1 records remain readable. |
| Truncation could yield apparently complete analysis | Cache and direct temporal analysis stopped at EOF without proving the declared frame count. | Validate counts in canonicalization and the shared block iterator used by global/temporal analysis. No accepted record for a partial file. |
| Shared neutral analysis repeated | Experiment analysis ran both two-pass analyzers for every pair, even for byte-identical controls. | A 128-entry invocation-local LRU stores summary dictionaries by verified WAV digest. Labels never enter extraction. No PCM is retained. Rehash inputs, including hits. |
| Temporal cache ignored imported implementation | Temporal identity hashed its own file while importing core pitch/frame/spectral functions from the global analyzer. | Bind shared analyzer and cache source plus Python/NumPy versions into deterministic-layer cache identity. Stale implementation causes a miss, not a reused verdict. |
| Neural work ran after failed deterministic work | Compact execution occurred inside the per-audio loop before either side's aggregate rejection. | Complete deterministic checks for **both** sides before any compact invocation. Explicit skipped layers, no expensive follow-up after rejection. |

All three initial negative fixture groups reproduced failures before repair (43 failed subcases,
10 type errors). New tests also bind eight pre-refactor derivative digests across mono/stereo,
16/24/44.1/48 kHz and block boundaries; interrupted writes, changed source, repeat-cache reuse,
imported-source drift, both-side rejection, and bounded memory are exercised.

## Actual M2 / 8 GB resource check

Four separate serial subprocesses compared baseline and current canonicalization using synthetic
10- and 60-minute PCM16/24 kHz mono input. This is cache-resource evidence, **not** generation,
neural-model, perceptual or iPhone acceptance. The existing resource supervisor enforced one
process at a time and a 1 GiB probe ceiling; no permanent memory-policy change was made.

| Synthetic duration | Old Python/NumPy traced peak | New traced peak | Old process RSS high water | New process RSS high water | Old → new conversion time |
| --- | ---: | ---: | ---: | ---: | ---: |
| 10 minutes | 40.82 MB | 4.82 MB | 89.03 MB | 43.52 MB | 0.137 → 0.142 s |
| 60 minutes | 231.75 MB | 4.82 MB | 316.98 MB | 43.22 MB | 0.741 → 0.801 s |

MB are decimal. Both lengths produced identical old/new SHA-256 and sample counts. Traced
allocations exclude the interpreter baseline; `ru_maxrss` is the process high-water measurement,
not an MLX/Metal physical-footprint claim. Four envelopes qualified: clean exits, no observed
before/after pressure warning, zero swap growth, and post-exit recovery. Existing host swap was
not zero. Sub-second timings are diagnostic observations, not a robust speed benchmark; the extra
source-integrity pass has a small cost. The measured gain is bounded memory, not faster TTS.

Raw, untracked evidence: `build/artifacts/diagnostics/audio-qc-review-20260906/cache-resource-comparison.json`
and its `profile_cache.py`. Source/probe digests and supervisor envelopes are retained there.
Probe source snapshots are retained byte-identical after collection; their original `ROOT`
calculation assumed a shallower scratch location. Resolve it to the checkout before a new replay,
and retain that replay as separate evidence rather than rewriting the captured source/report.
The normal regression suite measures 10 versus 600 seconds with `tracemalloc`, requiring less
than 8 MiB peak and less than 1 MiB growth. Synthetic data is generated blockwise and removed
after each probe. No personal audio or model was read, generated, downloaded or deleted.

## Accuracy findings: not solved by structural cleanup

### Resampling requires an explicit versioned migration

`linear-rational-v1` does not low-pass before reducing 24 kHz to 16 kHz. A synthetic 10 kHz
tone became a dominant **6 kHz alias**, with 5,164.7 PCM RMS; the installed SciPy polyphase
reference produced 9.76 RMS after edge exclusion. This demonstrates an input-preprocessing
defect; it does not quantify the effect on actual speech/model accuracy. The v1 implementation
also omits its last interpolation endpoint, including one sample at equal input/output rate.

Proper downsampling includes a low-pass stage. SciPy documents the FIR/polyphase method and its
boundary behavior. Use that as a tested reference for a bounded implementation, not independent
per-block resampling with reset filters. [SciPy resample_poly](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.resample_poly.html)

This patch intentionally preserves v1 derivative bytes and pinned model preprocessing. A v2
resampler must use a new namespace/config digest, preserve old evidence, match a whole-file
reference at block seams, specify endpoint/padding/rounding rules, and requalify affected compact
models. Do not silently interpret a formerly qualified model as qualified on different audio.

### Harmonicity and emotion claims need recalibration

The current normalized Hann-window correlation is reused in `10 log10(r/(1-r))` without
window-bias correction. Three noiseless 40 ms sine frames measured **0.51, 6.99 and 13.29 dB**
at 80/150/300 Hz respectively. This is a pitch-dependent harmonicity **proxy**, not calibrated
physical HNR. CPP and frame-level jitter/shimmer are likewise implementation-specific, not clinical
voice measures. The source documentation now says so; frozen v3 arithmetic is unchanged.

Praat documents a distinct autocorrelation method and window/period sensitivity. Its pitch guide
also explains octave errors and why filtered autocorrelation is preferred for intonation. Those
are reference implementations to compare, not evidence that switching algorithms alone will
improve emotion recognition. [Praat harmonicity](https://fon.hum.uva.nl/praat/manual/Sound__To_Harmonicity__ac____.html),
[Praat pitch methods](https://fon.hum.uva.nl/praat/manual/how_to_choose_a_pitch_analysis_method.html)

Current F0 is constrained to 70–400 Hz; synthetic accuracy inside that band does not qualify
children, extreme pitch, cross-language speech or whisper. Whisper may have no periodic F0.
Five-region maxima are coarse regional contours, not sample-accurate peak localization. Syllable
rate is an envelope-peak proxy, not phoneme/syllable alignment. Neither these features nor a
categorical SER label proves emotion meaning or speaker fidelity.

### Language and naturalness remain separate

Three Apple Speech passes test repeatability of one recognizer. Edge timestamps reject one-utterance
partial returns but do not prove the interior was fully transcribed. Word/character scoring is
useful only against correctly normalized, reviewed text. Script variants, homophones and recognizer
errors require separate diagnostics; do not turn consensus or Chinese script conversion into an
intelligibility waiver. Research illustrates WER's sensitivity to reference/scoring choices.
[ASR benchmark scoring study](https://www.isca-archive.org/interspeech_2022/faria22_interspeech.html)

Keep UTMOS as a relative finalist-only signal. Published TTS evaluation shows weaker correlation
out of domain; it is not a universal MOS oracle. Keep frozen speaker similarity separate from
pitch/cadence and transcript accuracy. [SpeechBERTScore evaluation](https://www.isca-archive.org/interspeech_2024/saeki24_interspeech.pdf)

### Legacy and orchestration debt

`analyze_delivery.py` still materializes a full index/frame matrix and `frames ** 2`, with
duration-times-window memory growth. Its callers are the legacy `delivery_adherence.py` and
`longform_carryover_probe.py`, not the current bench/cascade. Do not use it for long recordings.
Replacing it with a view alone does not make downstream arithmetic bounded; NumPy documents the
cost of sliding-window work. [NumPy sliding windows](https://numpy.org/doc/stable/reference/generated/numpy.lib.stride_tricks.sliding_window_view.html)

Global and temporal extraction still perform four total passes for a unique WAV. This is bounded
and compatible; fuse them only after exact-output fixtures establish an unchanged numerical path.
The main runner and cascade have separate caches; do not reuse their result files merely because
field names match. Cache entries are measurements, not cross-run evidence or completed Fast QC.
The cascade's `audioQC` block now explicitly identifies canonical PCM integrity only.

## Efficient next implementation order

1. **Completed:** repair invalid-input rejection, stream canonical writes, validate identity,
   reuse neutral summaries and stop before unnecessary neural work. Preserve production Fast QC.
2. **AV-07 / DP-28:** version anti-aliased preprocessing; test impulses, tones, chirps, stereo,
   odd lengths and block seams against a pinned reference; prove constant working memory.
   Requalify the existing adapters twice serially before adoption. No new weights needed.
3. **AV-07:** add corrected harmonicity/pitch candidates in an explicit analyzer version;
   characterize frequency, SNR, voicing and noise. Calibrate only on the calibration partition;
   compare on the untouched labelled holdout. Until then retain advisory v3 interpretation.
4. **AV-07 / DP-28:** move the two legacy callers through an explicit compatibility adapter
   to the bounded analyzer, with frozen old reports retained. Share/fuse measurement passes only
   when profiling justifies it; preserve source dependency closure and neutral/control identity.
5. **AV-08 / RF-06:** use independent full-WAV ASR only for ambiguous production findings;
   keep failure, evaluator-unavailable and disagreement separate. No repeated identical recognizer
   runs beyond the existing contract, no fresh large model campaign for this refactor.

A clean end state has one native product-QC authority, one bounded blind acoustic engine, one
versioned derivative cache, the existing serial neural supervisor, and explicit per-dimension
decisions. Human calibration remains necessary for semantic promotion—not for ordinary code checks.
No new aggregate score, hidden retry, model/prompt/seed change, QC relaxation, or parallel harness.
