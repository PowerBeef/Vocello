---
status: active
owner: backend-mlx
reviewed: 2026-09-06
summary: Source-grounded Audio QC architecture, corrected default preprocessing, M2 resource measurements, accuracy limitations and explicit historical replay boundaries.
sourceOfTruth:
  - Sources/QwenVoiceCore/GenerationOutputAdapter.swift
  - Sources/QwenVoiceCore/GenerationQualityComposition.swift
  - Sources/SharedSupport/Services/VoiceClipTranscriber.swift
  - scripts/analyze_prosody.py
  - scripts/audio_phonation.py
  - scripts/audio_resampling.py
  - scripts/delivery_analysis_cache.py
  - scripts/delivery_experiment_runner.py
  - scripts/run_local_delivery_cascade.py
  - scripts/prosody_quality_gate.py
  - scripts/check_language_output.py
  - config/audio-cadence-qc-contract.json
  - config/prosody-holdout-policy.json
  - scripts/prosody_corpus_inventory.py
  - scripts/prosody_holdout_validation.py
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
| Local research | experiment runner, analysis cache, compact adapter, resource supervisor, cascade, evaluator | Source-bound serial screening; native QC and independent ASR evidence compose separately from optional heads. Missing/contradictory evidence abstains. Requested follow-up layers are **requests**, not executed ASR/UTMOS evidence. No listener-proven semantic claim. |
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

### Corrected resampling is now the default

`linear-rational-v1` does not low-pass before reducing 24 kHz to 16 kHz. A synthetic 10 kHz
tone became a dominant **6 kHz alias**, with 5,164.7 PCM RMS; the installed SciPy polyphase
reference produced 9.76 RMS after edge exclusion. This demonstrates an input-preprocessing
defect; it does not quantify the effect on actual speech/model accuracy. The v1 implementation
also omits its last interpolation endpoint, including one sample at equal input/output rate.

Proper downsampling includes a low-pass stage. SciPy documents the FIR/polyphase method and its
boundary behavior. Use that as a tested reference for a bounded implementation, not independent
per-block resampling with reset filters. [SciPy resample_poly](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.resample_poly.html)

New cache, cascade, prepared-config and qualification runs default to `polyphase-kaiser5-v2`,
a bounded, delay-compensated rational FIR: Kaiser beta 5,
10 zero crossings, zero extension, Float64 mono mixing/filtering, nearest-even PCM16 quantization,
and `ceil(inputFrames * 16000 / sourceRate)` output frames. Unlike v1, equal-rate input includes
its final sample. New derivatives occupy a separate versioned cache namespace. Prepared model
configs bind the selected resampler and both implementation digests; mismatched configs/cache
versions fail before model launch. The v2 derivative metadata also binds the implementation and
rejects drift instead of silently reusing old bytes. Missing config identity decodes as historical
v1; null/malformed identities are rejected. An old config never silently selects the execution
method or gets upgraded. Either prepare a new source-bound config for current analysis or explicitly
select `--resampler linear-rational-v1` to replay historical measurements. Config/cache mismatch
fails before extraction or model launch. Existing cache namespaces and original reports are preserved.

The linear implementation is retained solely for explicit legacy config/cache consumers, not as a
quality reference or normal analysis path. Retire its execution path once active retained-config
consumers have migrated and remaining historical replay is served by the archived source; reading
original reports does not require keeping the old algorithm in current execution. No arbitrary date
or automatic cache deletion is implied. New calibration must bind the current preprocessing identity;
old model/score qualification is not silently transferred to it.

The frozen SciPy **1.18.0** reference fixture needs no SciPy installation in CI. Impulses/edges,
tones, chirps, stereo, odd lengths, single frames, block seams, source truncation, interrupted
publication and corruption have deterministic coverage. An additional installed-reference check
at 8/16/22.05/24/44.1/48/96/192 kHz matched Float64 output within `2.7e-15`.
The 24→16 kHz 10 kHz alias probe is suppressed below 0.003 RMS while the 1 kHz passband remains
within 0.003 RMS of its expected value. This qualifies preprocessing mathematics, not emotion.
The default-selection and silent-legacy-selection regressions both failed before this migration.
The integration fixture now passes a production-prepared config through the real cache, compact
adapter and cascade, inspecting the exact model-input WAV and its final sample. Only the external
model process is a fixture; cache reuse must perform no launch. Explicit legacy digests, invalid
identity, truncated PCM, source drift and interrupted writes remain covered. Invalid FIR input now
returns the cache's typed error and leaves no accepted derivative or metadata.

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

`analyze_prosody.py --experimental-phonation` now appends a separate
`experimentalPhonation` block (`window-corrected-ac-v1`). It shares the bounded PCM/frame reader,
uses 100 ms Hann windows / 10 ms hops, FFT autocorrelation divided by window autocorrelation,
local-peak interpolation and an explicit 0.01 octave cost. Periodicity-derived HNR is capped at
60 dB; unvoiced/short input abstains with null values. Synthetic 80–395 Hz, phase, harmonic-mixture,
10/20/30 dB SNR, noise, local-contour and tremor fixtures pass. Existing v3 output is identical
with the optional block removed. No existing profile consumes the new block. This is not Praat
equivalence, a clinical HNR measurement, a calibrated pitch tracker, or an emotion verdict.

#### Independent measurement comparison — September 6

Two bounded experiments compared the candidate with analytic signal truth and the independently
installed **Parselmouth 0.4.7 / Praat 6.1.38** implementation: known-frequency/noise frames, then
all nine checked-in public voice previews. This is raw autocorrelation, **not** modern Praat
filtered-autocorrelation intonation tracking. The isolated GPL-3.0-or-later reference tool is local
only: no source copied, app dependency, bundled tool, model download or CI prerequisite.
[Parselmouth documentation](https://parselmouth.readthedocs.io/en/stable/),
[raw autocorrelation](https://praat.org/manual/Sound__To_Pitch__raw_autocorrelation____.html).

The original harmonicity setup failed before producing measurements: 4.5 periods at the 70 Hz
floor required a longer input than each 100 ms frame. That failed process and original probe are
retained. The corrected comparison explicitly uses three periods, rather than silently accepting
a fallback. Consequently its HNR differences are descriptive, **not** equivalence against Praat's
recommended 4.5-period speech setting. Both tools receive identical frames, but their effective
windowing and voicing definitions differ. Each preview is analyzed frame-by-frame; this does not
qualify whole-utterance pitch tracking, and overlapping frames are not independent observations.

**Proven defect and correction:** integer-lag filtering discarded valid 70 Hz peaks and selected
200 Hz for an analytic 400 Hz input at 44.1 kHz. Interpolation could also escape the declared
range. The new regressions produced 41 failing assertions before repair. Candidate peaks now
include both integer neighbours, are interpolated before range filtering, and preserve the existing
ranking among valid peaks. Estimates within 0.001 Hz of an endpoint snap to the inclusive
70–400 Hz range; that numerical tolerance is not a physiological range extension. Analytic
boundaries and adjacent frequencies pass across 8/16/22.05/24/44.1/48/96/192 kHz and three phases.
Praat itself sometimes aliases an exact boundary tone, illustrating why agreement alone is not
ground truth. The optional report now binds the estimator, shared frame reader and NumPy identity;
the algorithm family/schema remain unchanged, but old source results are not silently upgraded.

| Public-preview comparison | Before repair | After repair |
| --- | ---: | ---: |
| Complete overlapping frames | 3,095 | 3,095 |
| Frames both tools call voiced | 2,301 | 2,300 |
| Absolute pitch disagreement above 600 cents, among jointly voiced frames | 67 | 62 |
| Voiced/unvoiced disagreements | 299 | 298 |
| Per-preview median absolute pitch disagreement | 8.33–31.19 cents | 8.33–31.19 cents |
| Per-preview median absolute HNR disagreement | 2.28–5.06 dB | 2.28–5.06 dB |

This is not a validated speech-improvement claim. A bounded autocorrelation search can report an
in-range subharmonic of an out-of-range tone; both tools did so for 450/600 Hz examples. The
candidate's fixed energy floor also abstains on the deliberately tiny unit-amplitude inputs.
Neither behavior establishes reliable out-of-domain detection. The old Hann-biased proxy is not a
gold standard, and the replacement is not ready to inherit its profile thresholds.

Evidence remains untracked in
`build/artifacts/diagnostics/audio-phonation-reference-20260906/`: predeclared `plan.json`,
original setup/probe, `baseline-synthetic-resources.json` (failed setup), `regression-before.log`,
and `comparison-*` / `corrected-*` reports and resource envelopes. The pinned arm64 wheel SHA-256
is `998138bf2acb15ae329caa217d523965b897417a1a2df130a2ecf41b664bfbf1`;
the imported reference binary is `c9d907cd7365906e853e5d89fa5203efce40da6733cf7ba3ba20e6c35c538da8`.
Corrected synthetic report digest:
`75b22e3c216b6850610f21919e7412a56d2d28fc1ea465cf86e59b24685bb5f6`;
corrected speech report digest:
`a3a04a23d34716b1389c40426bd79a0653a700a859113e3e319a273a72d89687`.
Four successful before/after processes ran serially below a 1 GiB ceiling. Maximum sampled RSS
was **118.31 MB**, corrected speech elapsed **4.42 s**; clean exits, post-exit recovery, zero
swap growth and no before/after pressure warning were observed. These snapshots do not prove
continuous absence of pressure. The deterministic 12/24-second fixture fills the streaming read
buffer and verifies an unchanged managed-memory estimate and bounded traced allocation; it is
not a host-footprint benchmark.

**Decision:** keep the numerical repair, retain the experimental block without promotion authority,
and stop this comparison here. AV-07 next requires independent real-speech/defect annotations and
source-bound calibration before changing any feature consumer or retiring the biased proxy. No
new framework, model, production QC threshold, prompt, seed, or release gate was introduced.

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

`analyze_delivery.py` is now a small **deliveryAnalysisVersion 2** projection of the existing
bounded v3 engine. Both `delivery_adherence.py` and `longform_carryover_probe.py` record that version.
The adherence caller reuses one extraction for both projections instead of analyzing each WAV twice.
Legacy keys remain, including raw-voiced RMS/count measured during the shared anchor pass.
Histogram percentiles and the shared cadence definition are explicitly versioned changes, not
byte-equivalent old scores. Original v1 reports and baseline source remain historical; the resource
bundle retains before/after reports from `917856c3`. No full frame matrix remains in either caller.

Global and temporal extraction still perform four total passes for a unique WAV. This is bounded
and compatible; fuse them only after exact-output fixtures establish an unchanged numerical path.
The main runner and cascade have separate caches; do not reuse their result files merely because
field names match. Cache entries are measurements, not cross-run evidence or completed Fast QC.
The cascade's `audioQC` block now explicitly identifies canonical PCM integrity only.

## Follow-up resource evidence and remaining boundaries

All new raw evidence stays in `build/artifacts/diagnostics/audio-qc-v2-20260906/`.
Nine serial synthetic probes qualified under the existing supervisor with a temporary 1 GiB
probe ceiling, zero swap growth, clean exits, recovered memory and no before/after pressure warning.
An initial **probe failure**, caused by naming its script `profile.py` and shadowing Python's
stdlib module, is retained in `resource-profile.json` and `profile-initial-failure/`. It preceded
measurement and is not a product failure. Corrected results are `resource-profile-v2.json`.

| Probe | Duration | Traced peak | Process RSS high water | Conversion/analysis time |
| --- | ---: | ---: | ---: | ---: |
| Legacy full-matrix adapter | 20 / 120 s | 34.53 / 207.41 MB | 74.58 / 252.79 MB | 0.40 / 2.32 s |
| Bounded compatibility adapter | 20 / 120 s | 0.86 / 0.86 MB | 38.49 / 38.34 MB | 1.30 / 7.71 s |
| Anti-aliased v2 derivative | 10 / 60 min | 3.29 / 3.29 MB | 42.91 / 43.88 MB | 1.98 / 11.81 s |
| Corrected phonation candidate | 20 / 120 s | 0.89 / 0.89 MB | 38.19 / 38.29 MB | 0.35 / 2.06 s |

Decimal MB; traced memory excludes interpreter/runtime baseline. Timing includes profiler overhead,
not repeated benchmark uncertainty. The compatibility adapter is slower because it computes shared
two-pass v3 features; its improvement is bounded memory and one implementation, not TTS speed.
The 20-second global+temporal profile took 2.85 seconds under instrumentation; raw autocorrelation
consumed 1.12 seconds across 7,988 calls. Four passes remain. Fusion is deliberately deferred:
neutral reuse already avoids repeated whole-file work, and changing the established numerical path
for this small absolute saving would add acceptance work without resolving a release blocker.

Each already-installed, contract-pinned compact model passed **two cache-cold serial probes** on
public English/Chinese preview audio with finalized v2 preprocessing. Separate final reports are
`sensevoice-qualified/qualification.json` and `distilhubert-qualified/qualification.json`; earlier development
probes are retained, not merged. Resource envelopes include RSS, clean exit, pressure snapshots,
swap deltas and post-exit recovery. This is CPU/RSS short-clip bake-off qualification, not continuous
pressure sampling, physical-footprint qualification, long-form neural memory bounds, calibrated
human agreement, or adoption. No new weights, package versions or production assets were acquired.

After making FIR the default, the same two public preview inputs were requalified through the
normal no-`--resampler` preparation/qualification commands, with newly source-bound configs. The
four new cache-cold processes ran serially; their reports explicitly name the actual preprocessing.
Evidence stays separate in `build/artifacts/diagnostics/audio-qc-current-default-20260906/`:

| Installed analyzer | Two sampled peak RSS values | Two process wall times | Report digest |
| --- | --- | --- | --- |
| SenseVoiceSmall Q8 | 277.68 / 272.96 MB | 0.269 / 0.192 s | `a58b480543c6f38b7210a1dc433a1285890e7f467485adca13cff90103d7d5df` |
| DistilHuBERT | 572.87 / 562.99 MB | 2.834 / 2.172 s | `2138f39fad780c50182ae3c4e08decec74eced05c1b588b70d16f974fe4eecfc` |

Reports are `sensevoice/qualification.json` and `distilhubert/qualification.json`. All four
envelopes passed with confirmed clean exit and post-exit recovery; SenseVoice swap delta was zero,
DistilHuBERT's was negative, and before/after pressure warnings were false. Existing swap was
nonzero. These short, warm-host observations are not a speed benchmark, continuous pressure
monitor or neural long-form memory bound. No new model/download/generation or promotion occurred.

### Independent recognition: one additional observation, no waiver

The predeclared `chinese-plan.json` binds the original 18.8-second iPhone WAV and permits one
independent SenseVoice run, with expected text read only after extraction. It detects `zh` and
returns **1 substitution / 59 characters (1.695%), no insertions/deletions** under the unchanged
strict scoring. Resource RSS peaked at 329.12 MB, runtime was 1.16 seconds, with a qualified
envelope. `chinese-comparison.json` binds the private output, input and plan by digest.

This is independent of the earlier Whisper model, but the pinned binary has **no locale-lock
option** and emits no time-aligned interior coverage. Complete WAV input is not proof of complete
correct speech. Preserve the prior 25/59 strict Whisper result, the 834 ms interior pause, cadence
warning and all original failures. The new result supports a recognizer/orthography disagreement;
it does not authorize script conversion, a quality PASS, or RF-06 closure. No TTS take was repeated.
The 14 retained French Design comparisons already include independent Apple/Whisper evidence.
SenseVoice does not support French and DistilHuBERT does not transcribe; running either as a French
judge would be invalid. French disagreement remains open; no extra recognizer was downloaded.

### Speech/defect calibration: independent references, no required listening

**Current maintainer decision (September 6): human listening is optional throughout automated
review, calibration and candidate comparison.** Earlier listener-packet results below remain
historical evidence, not unfinished tasks that require a person. Removing the prerequisite does
not turn an unlabelled inventory into truth, change production QC thresholds or resolve RF-06.

The existing `prosody_holdout_validation.py` route now offers **inventory → prepare → evaluate**;
`prosody_corpus_inventory.py` is its standard-library, read-only inventory helper, not another
evaluator. None of these preparation steps runs a model, generates speech or assigns quality labels.
Signal correctness, speech usability, and semantic emotion/fidelity are separate claims.

**Sampling correction.** The current minimum is **60 calibration + 60 good / 60 bad holdout
recordings**. At the previous 30-good floor, even zero errors gives a 95% Wilson false-positive
upper bound of 0.113513, which cannot meet the unchanged 0.10 limit. At 60 it is 0.060172. Policy
validation now rejects floors incapable of meeting either confusion bound even with perfect
results. These are starting floors, not a power guarantee or permission to collect until PASS.
Freeze the sampling/analysis plan before fitting; if underpowered, report inconclusive and
predeclare a new independent study instead of repeatedly opening or topping up the same holdout.

**Actual retained inventory, September 6.** Explicit diagnostics/macOS roots yielded 2,918 WAVs:
2,915 readable PCM files, 1,967 unique containers, **1,145 unique format-bound PCM streams**, and
three unavailable metadata cases. The walk visited 27,900 entries and explicitly skipped 139
symlinks. File/PCM hashes reveal copies and differently tagged containers; they do not establish
independent speakers, scripts, seeds, source families, real speech, or human quality labels.
All discovered material is development-only. It has no inferred labels or promotion authority.
The untracked bundle is `build/artifacts/diagnostics/audio-qc-calibration-preparation-20260906/`:
`inventory.json` is sanitized; `private-map.json` is private and must never be published;
`preparation-final.json` reports the still-missing qualified 60/120 corpus and unanswered annotation
template; the initial `preparation.json` is preserved. Inventory digest:
`e80b59e11e0de0684667a5ea56f21166d6fcebe2d39aa2da44cbaecf85208eff`.

**Corpus preparation order.**

1. Reconcile source metadata from exact receipts/manifests, never file names or prior QC verdicts.
   Include good speech and real retained defects; stratify language, speaker, script/translation
   family, duration, phonation and defect severity. Include quiet/whispered but usable speech and
   natural punctuation pauses as negative controls. Synthetic corruptions are useful measurement
   fixtures, not independent perceptual ground truth.
2. Declare `sourceGroup` for the original recording family: copies, crops, replay outputs and
   altered derivatives stay together. Calibration and holdout must also separate speaker, script
   and translated-equivalent groups. Select one predeclared primary observation per holdout source
   family. Different hashes do not prove independent sampling. Wilson bounds here describe the
   sampled clip cohort; they do not prove per-language or unseen-speaker generalization. Record
   group-level results and declare insufficient coverage rather than imply that broader claim.
3. Predeclare the untouched pool with genuinely unexamined recordings/groups and attest exposure
   as `untouched`. Previously listened-to/analyzed previews or known failures may inform development,
   never confirmation. Prepare accepts explicit `calibration`/`holdout` splits and rejects examined
   holdout rows, duplicate PCM, source/group overlap and any extra requested/scored label fields.
   Freeze primary selections independently of detector scores. Do not run feature extraction on
   the confirmation pool before freezing the profile.
4. Bind independent reference evidence: an exact byte-verified controlled PCM transformation or
   a locally available, digest-pinned external annotation catalog. No new listening responses are
   required. Unknown/disputed rows stay in the accounting; do not substitute the detector's own
   verdict as its training label. Existing human annotations may optionally be reused unchanged.
5. Fit on calibration only, bind the exact feature/preprocessing source and profile, then run the
   frozen holdout once. Inspect false alarms, misses and uncertain strata. AV-07 remains open until
   representative independent evidence qualifies the actual feature consumer. Retire the old
   proxy only after that switch is justified; old output equality is not an acceptance target.

**Optional historical annotation protocol** is `annotationProtocol` in
`config/prosody-holdout-policy.json`. These requirements apply only when choosing to import
listener evidence, not to the automatic reference route:

- At least three independently responding reviewers per clip, with at least one fluent in its
  language. Use anonymous reviewer digests, retain every response and record language fluency.
- Hide source names, requested presets, prior QC, split membership, metrics and expected defects.
  Randomize presentation per reviewer. The original PCM amplitude and time origin must remain
  intact: no gain normalization, silence trimming, denoising or time stretching for defect review.
- Record `acceptable`, `objectionable` or `uncertain`, finite confidence 0–1, and each audible
  defect's type, start/end in original-WAV seconds, and mild/moderate/severe severity. The rubric
  separates audibility from impact; none means no identified defect, not correct emotion.
  Keep optional free-text notes private and separate from machine reports. Do not show desired
  speech text before a free intelligibility/language judgment; a separate alignment review may
  use a verified transcript and must be identified as such.
- Retain approximately 10–15% exact presentation repeats for reviewer consistency checks, but
  never count those repeats as independent corpus rows. Listen before discussing other votes.
  The validator binds responses to WAV bytes, requires distinct reviewer IDs and fluent coverage,
  validates finite interval/confidence fields, and checks severity against observations. Any
  disagreement/uncertainty requires a separate fluent adjudicator bound to the original response
  set. Reviewer independence/fluency are operator attestations, not cryptographically proven facts.
- Private labeled JSONL rows add `annotations` to the existing calibration input. Each response
  uses the emitted template (`protocolID`, `source`, `audioSHA256`, `reviewerID`, `fluentLanguages`,
  `decision`, `confidence`, `defects`). A needed `adjudication` uses the same fields plus
  `responseSetSHA256` (SHA-256 of `json.dumps(annotations, sort_keys=True).encode()`). It must come
  from another reviewer; original votes remain unchanged. Final `label` maps acceptable→good and
  objectionable→bad. `defectSeverity` is the maximum resolved interval severity, or none.

The optional existing delivery listening session remains a **dimensional/emotion** tool: it requires
completed generations and asks VAD/2AFC questions. It does **not** collect defect intervals or accept
failed generations as a defect study, and is not silently repurposed as one. The new template is
an annotation data contract, not a claim that a graphical/interactive defect-listening session has
been built or completed. No independent reviewers or labels were fabricated.

**Compatibility.** Existing JSONL/profile readers and historical result files remain readable.
New qualification requires source-family/exposure provenance and bound independent reference
evidence; old anonymous good/bad strings alone cannot authorize a current PASS. Supply real
provenance or keep those files historical—never invent source IDs or reviewer votes. New reports
include policy, evidence digests and qualification scopes. Controlled fixtures can qualify signal
detection only (`promotionAuthority: false`); an external dataset qualifies only its documented
label definition/cohort, not all speech or emotion. Product QC thresholds remain unchanged.

Verification: 32 prosody tests pass, including actual CLI inventory/overwrite refusal, duplicate
container-versus-PCM identity, truncated input, symlink/traversal bounds, original-byte preservation,
duration-bounded read memory (one versus 600 seconds), impossible sample floors, split/source reuse,
per-listener/adjudication drift, and refusal before analyzer launch when annotations are missing.
This proves preparation/validation behavior, not that the unlabelled corpus is calibrated.

### Current automated review and measured-claim decisions

The existing `run_local_delivery_cascade.py` route uses `automated-evidence-1`. No parallel
generator, evaluator service, cloud processing or evaluator bundled into the app was added.

- The experiment runner now retains the CLI's **native `audioQC` receipt** alongside the actual
  WAV digest. The cascade consumes it instead of reproducing Swift Fast-QC thresholds in Python.
  Native failure wins over all other scores. Warning, absent/current-version mismatch, invalid
  duration or contradictory receipt stays inconclusive. Historical runs without receipts remain
  usable for acoustic analysis, but cannot receive a retrospectively invented safety PASS.
- Original/canonical integrity, cached global and temporal analysis continue. The existing
  prosody gate consumes the already extracted features; its warnings remain advisory/unresolved,
  never calibrated emotion labels. No extra audio frame matrix or model residency is introduced.
- `--review-evidence` optionally supplies **executed**, run-bound recognition receipts. It must
  cover exactly the plan's generation IDs. Each role binds the original WAV and script digest,
  full processed duration, locked and detected language, transcript, and runtime/model/config
  digests. WER/CER is recomputed with the existing language checker and unchanged 0.15 threshold;
  supplied scores are ignored. These processing receipts are evidence from trusted producers,
  not cryptographic proof that a recognizer actually listened to every word.
- At least two distinct supported ASR families must agree. Three Whisper/Apple repetitions are
  repeatability, not independent consensus. Wrong-language/partial/missing/drifted receipts or
  disagreement are inconclusive; unanimous valid content rejection is a measured failure.
  SenseVoice cannot judge French; DistilHuBERT cannot transcribe. No new recognizer was acquired.
- Optional compact features and fitted heads do not create a mandatory listener dependency.
  Missing heads report semantic delivery **unmeasured**. Their uncertainty never requests a human
  as the only continuation; bounded automatic evidence collection or a recorded inconclusive
  decision replaces manual-listening routing. Requested ASR/UTMOS layers are not automatically
  launched by this composer. Neural execution stays serial under the existing supervisor after
  TTS exits; cache hits do not launch models; UTMOS is finalist-only.
- `delivery_promotion_decision.py` schema 2 requires a frozen named metric/protocol, complete
  untouched holdout, independent-reference qualification, independent judge families, consistent
  reverse-order judgments, paired improvement/2AFC, distributed gains and unchanged quality/runtime
  guardrails. It can qualify **measured automatic improvement**, never listener-proven emotion.
  Schema 1 preserves the optional historical listening interpretation. Neither authorizes release,
  edits production copy, or waives the iOS acceptance campaign.

Reference input formats (private JSONL, existing calibration/holdout commands):

- `referenceEvidence.kind: controlled-pcm`: `audioSHA256`, `referenceWAV`, `referenceSHA256`,
  `operation: unchanged|mute-interval`; mute additionally declares integer `startFrame/endFrame`.
  The validator streams both PCM16 files, verifies equal formats/counts, exact unchanged bytes
  outside the interval and zero samples inside it, and rechecks identities. An unchanged control
  means **no injected defect**, not generally acceptable speech. Severity is a declared fixture
  stratum, not a measured perceptual severity. Derivatives must retain their source family.
- `referenceEvidence.kind: published-label`: `audioSHA256`, `annotationFile`,
  `annotationFileSHA256`. The bounded local catalog has `kind: external-reference-labels`,
  HTTPS `source`, immutable `revision`, `license`, `labelDefinition`,
  `derivedFromVocelloEvaluator: false`, and exactly one matching row with `audioSHA256`, `label`
  and `defectSeverity`. Its digest must also be in the policy's `approvedExternalCatalogSHA256`;
  the current list is empty, so an arbitrary local file cannot qualify itself. Verify actual source/licensing before acquisition; these declarations
  are provenance to audit, not legal clearance or self-label permission. No downloads occur.
- Cadence schema-2 rows replace `humanLabel/listenerCount/labelAgreement` with `referenceLabel`
  and `referenceInput` (the bound private row above). Emitted reports exclude private inputs.
  Optional schema-1 listener cohorts keep their original validation and meaning.

ASR evidence format: `{policyID: automated-evidence-1, executionPlanDigest, rows: {generationID:
{instructed: [...], neutral: [...]}}}`. Each recognition contains `modelFamily`
(`apple-speech|whisper|sensevoice`), `audioSHA256`, `inputTextSHA256`, `status: complete`,
`outputLanguage`, `detectedLanguage`, `fullFileProcessed: true`, `processedDurationSeconds`,
private `transcript` and `provenance` (`runtimeSHA256`, `modelIdentitySHA256`, `configSHA256`).
Optional missing inputs never become empty-success votes. Reports contain metrics/digests only.
The current bounded comparison accepts at most 4,096 characters per text; longer evidence is
explicitly unqualified rather than silently truncated. This route does not replace existing
release-safe language verification or reinterpret past product failures.

Operator commands (corrected FIR is the default; old configs require explicit historical replay):

```sh
python3 scripts/delivery_analysis_cache.py canonicalize <wav>
python3 scripts/analyze_prosody.py <wav> --experimental-phonation --json
python3 scripts/prepare_delivery_compact_model_config.py sensevoice-small-q8 \
  --output <new-untracked-config.json>
python3 scripts/prosody_holdout_validation.py prepare --output <untracked-preparation.json>
# Explicit roots only; both outputs must be new and untracked.
python3 scripts/prosody_holdout_validation.py inventory \
  --audio-root build/artifacts/diagnostics --audio-root build/artifacts/macos \
  --output <untracked-inventory.json> --private-map <private-path-map.json>
```

Regenerate local configs after source changes; do not overwrite the retained evidence's configs.
Cascade and qualification reports include their actual canonicalization method and source digests.
The optional corrected phonation block still needs independent real-speech calibration before any
profile consumes it. Making FIR current does not repair the old HNR proxy, calibrate emotion heads,
adopt a model, change production Fast QC, or close RF-06's product-audio findings.

A clean end state has one native product-QC authority, one bounded blind acoustic engine, one
versioned derivative cache, the existing serial neural supervisor, and explicit per-dimension
decisions. Listening is optional. Frozen independent-reference qualification supports named measured
improvements, not listener-proven semantic claims; unmeasured dimensions remain explicit.
No new aggregate score, hidden retry, model/prompt/seed change, QC relaxation, or parallel harness.
