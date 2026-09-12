---
status: active
owner: backend-mlx
reviewed: 2026-09-07
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

### Default acoustic reference base

`config/delivery-acoustic-reference-base.json` freezes the 45-clip September 7 panel as the
**default descriptive reference** for `run_local_delivery_cascade.py`. The existing evaluator
contract pins its exact SHA-256. This is a numerical reference database, not a new generator,
classifier, calibration service, app dependency or release prerequisite.

The manifest retains source revisions, attribution/license URLs and source-file hashes; original
and canonical audio hashes; published label provenance; speaker/script/source groups; exact neutral
pairing; original native QC and advisory/source warnings; analyzer/preprocessing identities; and
original evidence-report hashes. Audio, transcripts and raw diagnostic reports stay untracked.
The CREMA-derived database carries its ODbL/DbCL notice; no recording is bundled in Vocello.
All rows are development-exposed. Emotion/style labels are **not good/bad speech labels** and are
not registered as speech-defect holdout truth.

Three uses remain separate:

1. **Paired English:** 24 same-speaker/same-text contrasts, six per Angry/Fearful/Happy/Sad.
   Generated instructed/neutral pairs are compared with same-language reference deltas.
2. **Unpaired German:** Angry/Surprised/Whisper style context only. No neutral or cross-language
   pairing is manufactured. Recording-level differences particularly limit these absolute values.
3. **QC disagreement specimens:** every source, advisory and native warning/failure is retained.
   Native QC stays on originals; archived reference results never override generated-output QC.

The cascade retains its original-rate global/temporal layers and native receipt review. Its
additional `acousticReference` block uses cached FIR **16 kHz mono PCM** matching the frozen
reference, without gain normalization or trimming. The bounded blind extractor receives no
requested preset/text; labels select the cohort only afterward. Neutral cache hits launch neither
extraction nor models. Temporal contours remain separate, not bandwidth-matched reference bounds.

Each feature reports observed minimum/median/maximum and within/above/below that small sample's
range—not an emotion percentage, confidence interval, quality verdict or universal target.
The complete cohort is always primary. `excludingFlaggedSensitivity` excludes pairs when **either
member** has any source/native/advisory warning, lists excluded IDs, and reports zero remaining
samples as unavailable. Only one Angry pair remains in this strict sensitivity view; it is not
a clean replacement cohort. Missing coverage, absent neutral, analyzer/preprocessing drift,
corrupt registration and unavailable measurements are explicit. None changes quality routing.

Run the existing cascade normally; tracked numerical features require no reference download.
To additionally verify all 45 retained originals, add:

```sh
--reference-audio-dir build/artifacts/diagnostics/licensed-audio-reference-20260907/audio
```

This optional audit emits no paths. Missing/changed originals disable reference comparison for
that run without substituting a reference error for product QC. To update the base, explicitly
review a newly frozen cohort/analysis and its warnings, retain previous evidence, and update the
manifest/contract digest together. Never re-pin changed analyzer code without reanalysis or
silently rebase historical results. No human/cloud review or new release gate is required.

**Integrated verification, September 7:** all 45 original hashes match. The actual cascade processed
all 64 retained August 23 takes: ten descriptive contexts (eight English emotion/neutral contrasts
and two unpaired Neutral contexts), 54 missing-coverage rows, zero unavailable reference blocks.
All 64 overall quality decisions remain inconclusive because archived evidence does not satisfy
current quality requirements. The first extraction took 85.74 s but its sandboxed RSS/swap capture
was unavailable; that resource report remains unqualified. A separate outside-sandbox cache replay
completed in 0.42 s, 45.22 MB sampled peak RSS, 512 hits/zero misses, zero swap growth, no before/after
pressure warning and clean exit/recovery. No generation/neural model ran. Reports are retained in
`build/artifacts/diagnostics/acoustic-reference-adoption-20260907/`; cached report SHA-256
`b217066bfdff06e7a7f7e7646e05e08630138a992c09813bdd289918fcbb4bfe`.
This is diagnostic integration/cache proof, not new product or current-prompt acceptance.

### Licensed acoustic reference pilot — September 7

Completed the maintainer-requested bounded reference comparison on source `a359c514` without
new generation, a neural judge, a listener session or product changes. This is descriptive
development evidence, not threshold calibration, an untouched holdout or release acceptance.

- **CREMA-D:** 30 English recordings, six actors, three distinct sentences, with one complete
  five-emotion sentence per actor. Selected in deterministic actor/sentence order using the
  published **audio-only VoiceVote** matching the intended Angry/Fearful/Happy/Sad/Neutral label;
  ties and mismatches did not qualify. This is a selected clear-label cohort, not representative
  accuracy evidence or proof of defect-free audio. No acoustic score selected the clips.
  Revision `1658cd342dff90010aa843eaeebd53610a08b1dc`; database ODbL-1.0, contents DbCL-1.0.
  Attribution: Cheyney Computer Science / CREMA-D contributors. Preserve the source notices and
  applicable attribution/database share-alike terms when reusing or distributing derivatives.
  [Source and license](https://github.com/CheyneyComputerScience/CREMA-D),
  [ODbL](https://opendatacommons.org/licenses/odbl/1-0/),
  [DbCL](https://opendatacommons.org/licenses/dbcl/1-0/).
- **Thorsten-Voice:** 15 German recordings, one speaker, five identical texts across Angry,
  Surprised and Whisper. Revision `2b61b98fa8f99abd1ce1587b4bf413d6ebc217d5` declares CC0-1.0.
  Attribution: Thorsten Müller and dataset contributors. Actual emotional files contain **no
  Neutral rows**, despite that style appearing in the card; no other-session neutral was substituted.
  Every selected row carries `end might be cut off early`. The card also declares denoising,
  -24 dB normalization and edge trimming: these are not clean-speech, recording-level or edge-silence
  standards. The older Zenodo package declares CC BY 4.0; its terms were not silently replaced by
  the current HF card. Only the pinned HF release was acquired.
  [Pinned dataset card](https://huggingface.co/datasets/Thorsten-Voice/TV-44kHz-Full/blob/2b61b98fa8f99abd1ce1587b4bf413d6ebc217d5/README.md).

Metadata discovery reduced the proposed sample before audio examination: only three CREMA actors
supported two fully matched sentences under the selection rule; six actors with one sentence each
were retained instead. Thorsten's missing neutral reduced its panel to three styles. All 45 selected
originals remain unchanged, including flagged examples. Calm, French and native East Asian emotional
references remain uncovered; sleepy/amused labels were not renamed to fill gaps.

**Execution:** label-blind global, five-region temporal and optional corrected-phonation extraction
on original WAVs; the existing FIR cache additionally supplies 16 kHz mono PCM for bandwidth-matched
comparisons. No new gain normalization, trimming or denoising. A small untracked Swift caller invokes
the existing cached framework's `PersistedWAVAudioQCAnalyzer` v6 on original WAVs, with source-text
punctuation budgets. Its binary/framework hashes are retained; this is not a fresh candidate build
or pre-limiter generation telemetry. No native threshold was reimplemented in Python.

| Native PCM QC | Count | Advisory prosody QC | Count |
| --- | ---: | --- | ---: |
| Pass | 39 | No flags | 40 |
| Warn | 3 | Rushed | 5 |
| Fail | 3 | Other flags | 0 |

All six native non-passes are CREMA click flags. The three failures contain 716–1,327 raw adjacent
sample jumps above 0.42 full scale and 72–269 samples at a PCM16 endpoint. Native `clippedSamples=0`
does not prove a recording was never clipped before quantization. These are signal observations,
not confirmed audible clicks or a measured false-positive rate. The five advisory rushed flags
occur on three Sad and two Neutral clips. Emotion votes do not adjudicate these quality warnings.
All 15 cut-off-warning German clips pass native QC, illustrating that signal PASS cannot establish
linguistic completeness. No ASR/content-consensus pass was inferred or produced by this pilot.

Twenty-four same-speaker/same-text English contrasts produced these descriptive medians:

| Label | Pitch shift from Neutral (semitones) | Duration / Neutral duration |
| --- | ---: | ---: |
| Angry | +5.08 | 1.265 |
| Fearful | +4.32 | 1.072 |
| Happy | +1.73 | 1.075 |
| Sad | +1.33 | 1.271 |

Six contrasts per label; the sample is small, selected and script-imbalanced. All Sad clips were
longer, but all had higher **estimated** median pitch. Do not encode universal lower-pitch Sad or
faster Angry rules. Whisper receives 0.378–0.498 apparent voiced fraction from the original-rate
legacy tracker; periodicity/F0 estimates cannot by themselves prove voiced speech or whisper fidelity.
HNR/CPP, spectral features and syllable-rate proxies retain the limitations documented below.

All 16 English rows (Aiden/Ryan, eight presets) from the retained August 23 balanced-v4 cohort were
also reanalyzed with original audio hashes verified and original neutral pairing preserved. They
are **historical prompts/settings, not current production acceptance**. Bandwidth-matched examples:
Angry pitch shift +10.96/+7.98 semitones; Happy +3.55/-2.71; Sad duration ratio 0.943/1.242.
This illustrates speaker-dependent acoustic response, not an emotion accuracy score or a prompt
promotion decision. Eighteen distinct retained TTS WAVs plus 45 references share the same 16 kHz
comparison preprocessing; original-rate and canonical reports remain separate.

**Resources/verification:** original reference extraction 23.33 s / 47.17 MB sampled peak RSS;
native QC 1.04 s / 24.18 MB; historical TTS analysis 7.77 s / 40.08 MB; common-bandwidth comparison
8.81 s / 42.81 MB. Processes ran serially, exited cleanly, recovered memory, showed zero swap growth
and no before/after pressure warning. These are sampled RSS/snapshots, not continuous host-pressure
or GPU-footprint proof. The 46 existing focused global/temporal/phonation/prosody/cache tests pass.
Original-byte, upstream LFS shard, count/duration, label/plan and self-delta checks pass. Initial
metadata/wrapper/link setup failures and the invalid container-equality assumption are recorded as
operator setup failures, not audio failures. HF strict-extra verification rejected its own local
cache metadata; verifying the three requested source files succeeds and both LFS hashes match.

Evidence: `build/artifacts/diagnostics/licensed-audio-reference-20260907/` contains frozen `plan.json`,
source licenses/cards, `provenance.json`, 45 WAVs (8.2 MiB disk usage), original/canonical features,
paired deltas, native QC, retained-TTS comparisons, resource envelopes and integrity verification.
Original summary SHA-256: `f95266e09f56733dc854da460059122938ca9f1ea9756c4662d1b9a8bfc64880`.
The one-shot operator scripts remain with the untracked bundle; no parallel production harness,
new CI dependency or downloaded model was added. The 748 MB HF emotional shards are retained for
reproducibility; other HF subsets/video were not downloaded. All examined rows are development-only.

**Decision:** use the panel as acoustic reference points and QC disagreement examples, not as
automatic accept/reject limits or good/bad calibration labels. No external annotation catalog was
approved for general speech quality, no holdout was consumed, and AV-07/DP-28 remain open. Production
QC, prompts, models, seeds, personal data and the release queue are unchanged.

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

### Retained audio-failure follow-up — September 7

The shared verifier-to-quality-registry adapter incorrectly mapped incomplete/inconsistent ASR,
recognition errors and invalid timing evidence to a measured `.fail`. The VLR host classifier also
mistook the verifier's placeholder `languagePass=false` for a product rejection when a `skipReason`
was present alongside consistent recognition. Native negative fixtures reproduced 22 assertions;
six Python subcases independently reproduced incorrect product ownership.

Current composition marks these cases `.unavailable` / harness-inconclusive, including unknown
skip reasons. Valid scored language/accuracy rejection remains `.fail`; both outcomes still block
required acceptance. Only the persisted **gate composition** identifier advances to 4. Verifier v3
records, edit metrics, PCM/cadence thresholds and retained reports are unchanged. Recomposition is
new evidence, never an overwrite of historical results.
Focused verification passes 55 native verifier/quality-registry tests and 40 Python VLR/language
tests, including measured-failure preservation, unavailable-gate blocking and private-error redaction.

Authenticated reinspection of the 14 retained French WAV/sentinel pairs preserved all 30 checked
files: eight measured single-family rejections and six inconclusive cases (four incomplete edges,
two inconsistent/incomplete recognitions). No new recognizer or generator ran and no row became
PASS. The cross-family disagreements still prevent speech-defect closure. Evidence is retained in
`build/artifacts/diagnostics/macos/rf06-classification-remediation-20260907/`.

RF-06 remains open: the separately authorized September 7 cold iPhone comparison reproduced the
2,048-code/no-EOS stop with the original text/instruction/seed and nominal thermals throughout.
Memory pressure was healthy; no allocation retry or system crash delta occurred. The original
hot-device condition and long-form UI are therefore not necessary for the reproduced symptom.
The collected binary has 2,048 frames, 16 groups each and zero reported drops, but its producer
digest was lost from failure telemetry and the terminal validator rejects the omitted optional
`audioQC` key. Keep the run failed and the orphan trace unqualified for authenticated replay;
repair the narrow producer/consumer evidence path before further generation, never fabricate QC
or rewrite the historical result. Source-bound registration/assessment live in the existing
`rf06-longform-recovery-20260906/iphone-followup-20260907/` bundle; device run is
`ios-startup-reliability-20260907-145015-63ba20fb`. The process was stopped and device artifacts
retained because guarded cleanup follows successful validation. The severe French generated-code gap and distinct Chinese trailing silence are not
repaired by this classification fix. The 834 ms Chinese pause remains a cadence warning. Do not
repeat excluded decoder variants or infer Chinese/French acceptance from the English/German
reference panel. No speculative generator, planner, prompt, token-cap or threshold change is made.

### Token-limit diagnostic records and replay

The September 7 repair keeps result schema v2: `audioQC` is explicitly `null` when final
QC never ran, while absent QC still cannot qualify a passing take or a QC rejection.
The device runner's existing wire records now live in `IOSStartupReliabilityRecord`, shared
with host tests; no second producer or device harness was added. All adapter failure calls
must forward their owned diagnostic notes. Codec artifact parsing uses the existing shared
`GenerationTerminalDiagnosticEvidence` parser, and failures after decoded audio use its
`post_generation_failure` classification rather than pretending final QC rejected them.
That classification is accepted by result v2 only; historical v1/v2 meanings remain readable.

A complete captured token-limit trace can now enter the existing diagnostic replay path without
a final QC report. Portable CLI replay retains all original take/trace/model checks:

```sh
QWENVOICE_DEBUG=1 ./build/vocello bench \
  --codec-replay <original-take.json> --take-sha256 <original-take-sha256> \
  --codec-trace <original-codec-trace.bin> --script-file <untracked-model-facing-text.txt> \
  --output-dir <new-untracked-directory>
```

For a no-QC take, `generation.incomplete` and a receipt-matching model-facing text digest/length
are required. Script input is bounded at 64 KiB, remains local, and supplies only the existing
analyzer's pause expectation. QC-bearing historical inputs can still use their recorded cadence
expectation without a script; contradictory script/QC expectations are rejected. Replay computes
new reports for replayed PCM, never invents a report for the failed original. "Full" retains its
existing meaning: the production non-streaming 25-frame schedule, not an independent decoder.

The original September 7 binary remains an orphan with no producer-recorded digest in the
collected bundle. A hash computed afterward does not replace that missing receipt. Its original
take, result and audio/code bytes stay unchanged and unqualified; this repair does not recover
authenticated replay eligibility for that historical take or fix the long-form cutoff. Native
producer-to-Python validation and negative fixtures qualify the record correction without a phone;
new physical capture/replay remains a separate, explicitly scheduled diagnostic step.

The later authorized September 7 capture (`ios-startup-reliability-20260907-154111-6a16585e`)
verified explicit-null QC, codec metadata retention and post-generation classification on the
physical iPhone. Its producer-bound trace matches the earlier orphan's bytes; both replay schedules
complete but fail QC with a 16.680-second gap starting at 33.483 seconds. The aggregate runner still
failed: native pause capture permits 256 entries, whereas the host/schema permitted only 64; the
replay reports contain 159/158. The corrected host/schema now accept the producer's bounded list,
with 64/65/256/257 boundary fixtures. No list is truncated and no QC threshold changes.
The same revalidation exposed a second host defect: receipt v2's resolved `language` was compared
with the plan's requested `auto`. Compare `storedLanguageSelection` with the plan instead, require
explicit selections to agree with the final language, and retain v1's historical comparison.
Both language identities remain stable across allocation retry.

Use the existing validator's read-only route for retained bundles:

```sh
python3 scripts/ios_startup_reliability.py validate-result \
  --plan <original-plan.json> --artifact-dir <collected-artifacts> \
  --run-id <original-run-id> --read-only
```

It prints the summary without writing into the source bundle. Successful validation establishes
record integrity, not successful synthesis: the September 7 run validates as `diagnosed_failure`,
with one represented failed take. All 27 original files retain bytes and modification times;
the original runner failure and withheld device cleanup remain recorded.

The separately authorized same-code Mac replay used `BenchCodecReplay` and the existing serial
resource supervisor, with exact take/trace/tokenizer binding and isolated app data. It exceeded the
provisional 5 GiB physical-footprint ceiling after 33.60 seconds (5,390,092,808 bytes; swap growth
2,118,186,434 bytes) and was terminated before either WAV was completed. Exit and post-exit free-memory
recovery are confirmed; resource qualification fails. The external resource report records the
termination even though the interrupted CLI report remains `started`. Do not treat it as a clean
exit, a completed cross-platform comparison or a product Jetsam event. Retain the failed attempt;
inspect replay allocation ownership before any newly authorized bounded-memory follow-up. Evidence
is `host-contract-replay-20260907/` under the existing RF-06 long-form recovery bundle. The phone
was untouched. None of these harness corrections fixes the 2,048-code cutoff or silent continuation.

The subsequent source review identified a cold replay policy bypass: CLI bootstrap initializes the
engine but does not apply generation's host cache policy. Replay now applies
`NativeMemoryPolicyResolver` before loading and carries its immutable chunk-clear setting into both
decoder arms. Temporary GPU output arrays are released after CPU materialization, with cache clears
at policy-owned boundaries; live decoder context remains intact. The original recorded ranges and
the full arm's 25-frame schedule/valid-length semantics are unchanged. Each arm resets on success,
cancellation, or observation failure. No attention-mask, model, precision or production decoder
change is included.

Explicit replay emits privacy-safe, timestamped JSON `codec_replay_memory` lines to retained stderr:
before/after load, arm start/finish, and before/after cache policy at at most 17 chunks per arm
(at most 74 records including load boundaries). Fields are arm/stage, completed-frame count,
MLX active/cache/peak bytes and cache-limit bytes; no audio, codec IDs, prompts or paths. Capture
failure aborts replay rather than silently omitting evidence. These allocator counters supplement,
not replace, the exact-PID physical-footprint supervisor. A killed process can still leave the CLI
report `started`; the external resource report remains terminal authority. Preserve the original
failed attempt and use a new run identity for any authorized same-code memory confirmation with
the unchanged 5 GiB ceiling. Deterministic parity tests do not establish real-model memory fit.

The subsequently authorized `memory-policy-confirmation-20260907` completed both arms in 57.35s,
peak footprint 3,970,451,736 bytes (3.70 GiB), with 455 exact-PID samples, clean exit, no probe failure,
clean pre/post host pressure and decreasing swap. Seventy bounded allocator records confirm the
256 MiB limit before loading and zero cached bytes after all observed policy clears. This resolves
the ceiling breach for this one trace, not general memory qualification: the supervisor retains
`post-exit-memory-recovery-unqualified` because host free memory fell from 69% to 62% after its
original 15.22-second recovery window (five-point tolerance). The exited process was independently
absent; the host-wide deficit's allocation owner is not established. A later snapshot is annotation,
never a rewritten PASS or permission to relax the gate.

Both authenticated Mac WAVs are 163.84s and fail with the same 16.680s gap at 33.483s as the original
iPhone replays. Mac-arm differences are at most one PCM16 quantization step; Mac/iPhone bytes are
not identical. The comparison excludes an iPhone-only/output-mode-only cause, not shared decoding
versus sampled codes. All original evidence and in-run source identity are preserved. RF-06 remains
open; do not rerun this excluded platform hypothesis or waive QC. The untracked assessment in that
existing recovery bundle records exact hashes, waveform differences and the separate resource failure.

The subsequent `gap-localization-20260907` investigation used the pinned official Qwen CPU decoder
on the same 2,048-frame trace, not another generated take. Its bounded 25-frame/25-left-context
schedule reproduced an 18.475s raw-float gap at 33.488s. Three fixed 50-frame direct-forward windows
then compared current fp16 with archived fp32 tokenizer weights: the four-second interior-gap
window was entirely below 0.001 with both, while preceding speech remained audible-level. The
trace contains no dropped/all-zero frames or adjacent identical complete frames; first-codebook
diversity collapses and later repeats last 610 and 570 frames. These observations localize the
immediate defect to the generated sequence and exclude a required Swift-only, publication,
long-lived decoder-state or fp16-rounding cause for these windows. They do not prove whether the
generator's collapse originates in model behavior or generation implementation/numerics; no
per-step logits/EOS probabilities were retained. Do not raise caps or alter the decoder from this.

All outputs are diagnostic, not promotion evidence. Sampled footprints stayed below 5 GiB, but all
three processes failed host free-memory recovery; the fp32 window run also retained a resource
probe/process-group-signal failure despite complete output and exit code 0. Source/weight/trace/output
digests, unchanged originals, failed resource envelopes, one-second bounded signal measurements and
synthetic measurement checks remain untracked in that existing recovery bundle. The next causal
comparison belongs at generation-side conditioning/logit/EOS/sampling, not another decoder replay.

**September 7 Talker follow-up:** opt-in `Qwen3TalkerReplayDiagnosticTests` teacher-forces at most
600 retained frames through the production CustomVoice conditioning and Talker, without sampling
or decoder forward. Private input must bind model/config/tokenizer files, text, instruction, trace
and expected token lengths; ordinary deterministic tests skip the model-dependent method without
`VOCELLO_TEST_TALKER_REPLAY_INPUT`. This key is read only by the test target, not a product override.
Use the existing external resource supervisor; never run it as a normal CI/model prerequisite.
At most eight fixed checkpoints recompute the same full history using a fresh cache. Observations
are bounded, atomic, digest-bound and untracked; no raw text or code IDs enter report JSON.
The lower runtime exposes conditioning internally for this purpose, not through its public facade.

The corrected run inspected 600 finite last-step logit vectors and retained 59 observations.
At all seven fresh-prefix checkpoints the recorded first code remains top-ranked in both methods.
Inside the gap at frame 475, raw selected probability is .94394/.94686 and raw EOS is
2.63e-7/2.22e-7 (cached/fresh). This supports a model continuation strongly conditioned on the
already-bad history, not gross incremental-cache corruption at those checkpoints. Absolute logit
differences up to .375 remain; there is no byte-equivalence or new numeric tolerance claim.
Raw probabilities precede the sampler filters; the original device probabilities and random keys
remain absent. The earlier transition into the bad history is unresolved. No source fix is justified.

Retain the preceding failed diagnostic preflight: it inferred a 55-position prefix instead of 56.
The first forward consumes the whole prefix, so subtract **forward count minus one** from final KV
offset; account for an EOS forward separately. Both historical traces and independent tokenization
agree. The corrected run is separate, not a regenerated audio take. It exited 0 in 27.74s at sampled
2.93 GiB footprint but remains resource-unqualified (probe failure and swap growth). All 12 original
evidence files and 34 canonical model files were unchanged. Evidence/limitations are in the RF-06
`talker-replay-20260907-corrected-prefix/` bundle; work status remains solely in the roadmap.

### Bounded production sampler and predictor diagnosis

The same opt-in test now requires `allocatorPolicyPath` and `allocatorPolicySHA256`. Export the
actual Mac host policy with `DiagnosticMemoryPolicyExportTests`, setting its test-only
`VOCELLO_TEST_MEMORY_POLICY_OUTPUT` to a new private output; bind that file's SHA in the private
input. It invokes `NativeMemoryPolicyResolver`, not a duplicated tier table. Older retained inputs
need this explicit addition before re-execution; their outputs remain historical evidence, never
silently requalified. The diagnostic verifies/applies limits before load and restores the previous
settings after releasing model ownership, including cancellation and observer-error paths. Keep the
existing external supervisor's 5 GiB ceiling, pressure/probe/swap/recovery checks and serial process
exit requirement; allocator configuration alone is not resource qualification.

Optional `productionCapture` runs the actual CustomVoice producer with the exact receipt's seed,
talker/subtalker settings, repetition penalty, streaming interval and unchanged 2,048-code cap.
`frameLimit` remains at most 600; at most 16 `inspectFrames` retain full logit vectors. Run an
unobserved control and observed arm as separately identified attempts, verify every emitted code
and input/source identity before using the observations. The internal observer resolves the exact
single key consumed by categorical, without an additional RNG advance. It retains at most one
frame's tensor handles and reads them only after the producer's normal materialization boundary.
Per-frame records are atomic and private; the explicit `diagnostic_frame_bound_not_eos` terminal
is neither a cap failure nor successful finished audio. No observer is configured by product hosts.

Optional `predictorFrames` (at most four) compares all 15 eager/compiled residual passes under
identical teacher-forced codes and hidden inputs, with one evaluation boundary per selected frame.
Do not independently sample arms and interpret later divergent audio as a numeric regression.
Production-dtype comparisons do not inherit fp32 toy tolerances. Ordinary tests exercise sampler
suppression/penalty/filter order/EOS, scratch parity, observer key/sequence identity, truly overlapping
async scopes and all-pass cache reuse across projection and dtype variants without model weights.

**September 7 decision checkpoint:** two experiments completed. Observer on/off codes match at all
600 frames, but first differ from the original phone at frame 1/codebook 8. The new first-codebook
sequence repeats at most four consecutive frames within this bound. All 45 shipping-weight
bfloat16 predictor logit comparisons at frames 0–2 match exactly eager/compiled/captured production.
This does not reproduce the original decision, validate cross-platform seed identity or clear RF-06.
No generator correction follows. Original keys/logits are unavailable; an independent matched Talker
or early device-decision comparison is the remaining discriminating boundary, not another decoder
study. Stop here for a decision rather than expanding the campaign automatically.

Raw schema-absent first-frame capture statistics initially included the whole 56-position prompt;
predictor pass-zero raw arrays also include both input positions. Preserve those originals. The
separate `analysis.json` binds the original arrays and extracts the final vocabulary row (first-frame
selected raw probability .99999901, not the invalid flattened probability). Diagnostic schema 2
now records `rawShape`, `rawPosition: last` and only that last raw row; a synthetic mismatched-position
fixture rejects the former interpretation. Processed distributions and all code comparisons were
unaffected. Never combine old flattened arrays with new last-position arrays without this explicit
interpretation. Evidence lives in RF-06 `sampler-transition-20260907/`, untracked.

All three processes exited below 5 GiB (~2.94 GiB sampled peak). Baseline remains resource-unqualified
for probe failure/swap growth; observed and predictor envelopes qualify. Preserved originals and
model files/source are verified separately. Mac 256 MiB cache versus original iPhone 128 MiB,
different platform/build setup and a deliberate 600-frame stop preclude product/release acceptance.

### Earlier analyzer corrections

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
bounded v3 engine; `longform_carryover_probe.py` records that version. The standalone adherence
bench was removed on 2026-09-12: `vocello bench --delivery` plus `bench_delivery_prosody.py` own
paired adherence, and `prosody_profile.py` owns the prosody-effect and arousal weights.
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

### Threshold-change authority

The Fast-QC cadence and dropout boundaries (`makeAudioQCReport`, algorithm v6) change only under
this policy, carried over verbatim from the retired `config/audio-cadence-qc-contract.json` on
2026-09-12:

- an untouched confirmation cohort is required (`requiresUntouchedConfirmation`);
- independent reference evidence is required, independent human labels are not
  (`requiresIndependentReferenceEvidence`, `requiresIndependentHumanLabels: false`);
- automatic metrics may screen candidates only, never qualify a change
  (`automaticMetricsMayScreenOnly`);
- a source change requires an explicit review (`sourceChangeRequiresExplicitReview`);
- the current boundary remains authoritative until a change is qualified
  (`currentBoundaryRemainsUntilQualified`).

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
