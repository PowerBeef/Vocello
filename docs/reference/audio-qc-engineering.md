---
status: active
owner: backend-mlx
reviewed: 2026-09-27
summary: Source-grounded Audio QC architecture, corrected default preprocessing, M2 resource measurements, accuracy limitations and explicit historical replay boundaries.
sourceOfTruth:
  - Sources/QwenVoiceCore/GenerationOutputAdapter.swift
  - Sources/QwenVoiceCore/AudioQCSignalObserver.swift
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
  - scripts/independent_asr.py
  - scripts/lib/language_metrics.py
  - scripts/lib/audio_qc.py
  - scripts/lib/audio_qc_observations.py
  - scripts/derive_audio_qc_bounds.py
  - scripts/audio_qc_qualification.py
  - scripts/audio_qc_calibration_set.py
  - scripts/lib/qc_qualification/composer.py
  - scripts/audio_qc_orchestrator.py
  - scripts/audio_qc_worker.py
  - scripts/lib/qc_pipeline/admission.py
  - scripts/lib/qc_pipeline/workers.py
  - scripts/lib/qc_pipeline/layered_cache.py
  - scripts/lib/qc_pipeline/panel_engines.py
  - scripts/lib/qc_pipeline/panel_jobs.py
  - scripts/lib/qc_pipeline/panel_metrics.py
  - scripts/lib/qc_pipeline/qualification.py
  - scripts/audio_qc_panel_qualification.py
  - scripts/audio_qc_oracle_ladders.py
  - scripts/lib/qc_qualification/ladders.py
  - config/audio-qc-canary-set.json
  - scripts/acquire_audio_qc_judges.py
  - scripts/audio_qc_corpora.py
  - config/audio-qc-corpora.json
  - config/audio-qc-runtimes/
  - scripts/delivery_resource_supervisor.py
  - config/audio-qc-judges.json
  - config/audio-qc-qualification-policy.json
  - config/audio-qc-stage0-calibration.json
  - config/audio-qc-stage0-observations.json
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
One page per registry judge and detector, with generated pins, scope and measured accuracy, is in
the [audio QC reference tree](audio-qc/README.md) (AQ-09).

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
| Product adapter | `Sources/SharedSupport/Services/AudioQualityGate.swift` | One shared presentation adapter compiled into both app targets; it delegates to the core analyzer and owns no thresholds. |
| Spoken content | `VoiceClipTranscriber.swift` (Apple Speech, three locale-locked passes), `scripts/independent_asr.py` (whisper-small MLX, after the generator exits), `scripts/lib/language_metrics.py`, `check_language_output.py` | Locale-locked full-WAV recognition, edge evidence, WER/CER (0.15 threshold). One family is one witness; two families must agree for consensus. |
| Acoustic measurement | `analyze_prosody.py` v3, `delivery_temporal_features.py` v1 | Two bounded passes each: global features and five-region contours. Measures signal properties, not listener-recognized emotion. |
| Acoustic decisions | `prosody_quality_gate.py`, `delivery_quality_gate.py`, frozen profile | Warn-first heuristics; incomplete measurement must not become PASS. AV-07's independent calibration is still missing. |
| Local research | experiment runner, analysis cache, compact adapter, resource supervisor, cascade, orchestrator | Source-bound screening after the generator exits, admitted within one memory budget; native QC and independent ASR evidence compose the route (the uncalibrated heads and DistilHuBERT left QC, AQ-05). Missing/contradictory evidence abstains. Requested follow-up layers are **requests**, not executed ASR evidence. Every judge is registered in `config/audio-qc-judges.json` with its license tier; NISQA, UTMOSv2 and the speech-emotion classifier are retired (non-commercial terms). No listener-proven semantic claim. |
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
the full arm's 25-frame schedule was unchanged by that work (its valid length was later superseded by
DECODE-002: the full arm now keeps every generated frame). Each arm resets on success,
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

No reference-free MOS judge runs today. UTMOSv2 and NISQA were retired on 2026-09-25 because they
train on, or ship as, non-commercial material (`config/audio-qc-judges.json`); published TTS
evaluation also shows weak out-of-domain correlation, so neither was a MOS oracle. A relative
quality column returns only as the audio QC audit's composite, after its ladder test (AQ-08). Keep
frozen speaker similarity separate from pitch/cadence and transcript accuracy. [SpeechBERTScore evaluation](https://www.isca-archive.org/interspeech_2024/saeki24_interspeech.pdf)

### Legacy and orchestration debt

`analyze_delivery.py` is now a small **deliveryAnalysisVersion 2** projection of the existing
bounded v3 engine; `longform_carryover_probe.py` records that version. The standalone adherence
bench was removed on 2026-09-12: `vocello bench --delivery` plus `bench_delivery_prosody.py` own
paired adherence, and `prosody_profile.py` owns the prosody-effect and arousal weights.
Legacy keys remain, including raw-voiced RMS/count measured during the shared anchor pass, and the
delivery records' `deliveryProsodyEffect`: on every record that carries it, it is the instructed
take's absolute expressiveness (the prosody-effect formula over its own metrics), not an effect
against the paired neutral. The paired effect, the same formula over the published `deliveryD*`
deltas, is `deliveryPairedProsodyEffect` (records since 2026-09-25) and is what the quality
promotion contract requires (audit #9).
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
the `qualification.json` files in the `sensevoice-qualified/` and `distilhubert-qualified/` directories; earlier development
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

Reports are `qualification.json` under `sensevoice/` and `distilhubert/`. All four
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

### The plosive-onset step cluster (MV-05, judged 2026-09-14)

`stepBurstPeakCount` / `stepBurstPeakStartMS` record the densest 20 ms window of sample-to-sample
steps above a quarter of full scale. On the clone short cell the generator places such a cluster
150 to 250 ms into the take (8 to 32 steps in 11 of 88 fixed-seed takes on artifactVersion
2026.09.14.1; a count above zero in 63 of 88); it is model-intrinsic (present under either codec
and in the 2.4.0 binary, sample-identically). The NISQA clip-quality judge (MV-06) did not
register it: full-clip MOS of the 11 cluster takes had median 4.82 against 4.90 for the 52 clean
takes (rank AUC 0.54, Spearman with the count 0.00), and a 300 ms onset window moved only modestly
(median 3.29 against 3.72, AUC 0.71, Spearman −0.18) inside a range clean takes also cover. The
four takes below the warn floor in that set all carried counts of one or two. The judgement
recorded then: the cluster is a measured, monitored artefact with a minor perceptual footprint,
not a QC defect; QC v7 keeps counting it. No onset-window warning was added because the window
does not separate the classes. The Python detector in `lib/playback_capture.py` matches the
Swift count within ±1 on 60 of 60 takes (54 exact), a windowing boundary difference.

That judgement rested on NISQA, which was retired on 2026-09-25: its weights are CC BY-NC-SA 4.0,
and it was never qualified on clean TTS. The audio QC audit reopens the cluster (AQ-F12) as a
signal-class and identity-onset qualification under AQ-07; until then no clip-quality gate exists
for a reproduction to pass, and the cluster stays counted and unjudged.

### Speaking-rate plausibility (QC v8, audit #10, 2026-09-25)

Every other Fast-QC measure reads amplitude or waveform shape, so a take that runs on or repeats
itself well past its script passed: two canonical macOS UI takes of the medium script ran 14.96 s
and 15.12 s against a usual 6.5 s. QC v8 (`AudioSpeakingRateQC` in `GenerationOutputAdapter.swift`)
relates the take's duration to its spoken request text as `secondsPerTextUnit`, a unit being one
letter or digit (one character in Chinese or Japanese, one syllable block in Korean). The text's
own script picks the band, so Auto requests are covered; texts under 20 alphabetic or 8 CJK units
are reported but not judged. Above 0.145 s per unit (alphabetic), 0.45 (Chinese) or 0.40
(Japanese, and Korean until it has evidence) the take gains the warn-only `speaking_rate_slow`
flag on its instability verdict. The value is published as the take metric `secondsPerTextUnit`
(`scripts/lib/audio_qc.py`).

The bands were seeded offline from 3,724 committed benchmark takes, mapped to their benchmark
texts by cell (records carry no prompt text; language takes use their own
`referenceCharacterCount`, and 14 macOS language takes recorded before the July 14 corpus
calibration were skipped). Alphabetic text runs at a median 0.076 s per unit (p99.5 0.126), Chinese
at 0.26 s and Japanese at 0.22 s per character. Replayed against those takes the rule flags 8
(0.21%): the four run-ons the audit named (the two canonical medium takes above, and the September 2
macOS lang-bench German take at 19.36 s and Chinese take at 17.28 s) and four Design takes at 1.8x
to 2.6x their cell's median. No failing bound exists; one needs the authority below.

**Failing bound: screened, not qualified (2026-09-25).** The maintainer delegated the decision to
the audit's recommendation (#10: set any fail bound under this authority), so the bound was screened
offline with `scripts/derive_audio_qc_bounds.py speaking-rate`, which replays the committed records
read-only against the replay constants below. It reproduces the seeding
(3,725 takes before the QC v8 commit, the same 8 warned takes) and splits off the 24 takes
published since (the M6 gate records), none warned. The evidence does not qualify a failing bound:
the warned takes are not separated from ordinary ones (the slowest unwarned alphabetic take is 0.140
s per unit, the fastest warned 0.146); the two canonical run-ons (0.164 and 0.166) sit below even
1.25x the band (0.181), which a slow Design take (0.206) exceeds, so any bound that fails the
run-ons also fails Design deliveries; the replay's only run-on label is the duration the bound
reads, so there is no independent reference evidence; and the untouched split holds no run-on at
all. `speaking_rate_slow` therefore stays warn-only. A qualifying change needs an untouched
confirmation cohort of at least 60 run-on and 60 ordinary takes whose labels come from independent
evidence (for example a two-family transcript that shows the repeated or extra words), then a
reviewed Swift edit; the tool never reports a bound as qualified.

### Clustered click events (audit #85, 2026-09-25)

The click bound counts slew-limited samples as a fraction of the take (warn above 0.05 %, fail
above 0.5 %), which at 24 kHz is 12 and 120 clamped samples per second, so its tolerance grows with
take length and a seam that clamps several samples counts several times. The limiter
(`PCM16StreamLimiter`) now also clusters clamped samples into events (samples at most 10 ms apart are one event), counts the
events that start while the input envelope (about a 10 ms mean absolute level) sits below 0.02
(about -34 dBFS) as low-energy, and reports `clickEventCount`, `lowEnergyClickEventCount` and
`clickEventsPerSecond`, published as take metrics. They join QC algorithm v8 additively (their
presence marks them): the version is part of the gate's baseline identity, so a bump for fields that
move no verdict would force a consent-bound re-seed of the M6 gate baseline. They are observational: no flag reads them and
the per-sample fraction stays the only click bound, as the audit recommends until the events are
calibrated on the retained codec A/B takes (the decision was delegated to that recommendation on
2026-09-25). `scripts/derive_audio_qc_bounds.py clicks` replays the committed records (273 of 3,778
takes clamp at all; clamped samples per second median 0.74, p99 20.0, max 25.0) and runs WAV files,
such as the retained A/B takes with a `--labels` file, through a mirror of the counter to screen
per-second candidates; the result feeds this authority, never a bound directly.

**Replay constants.** `derive_audio_qc_bounds.py` never reads Swift source. It mirrors these
Swift-owned values, and `scripts/tests/test_derive_audio_qc_bounds.py` pins the mirror to them; a
qualified change edits the Swift source, this list and the mirror together:

- speaking-rate warn bands (`AudioSpeakingRateQC`): 0.145 s per unit alphabetic, 0.45 Chinese,
  0.40 Japanese and Korean; judged from 20 alphabetic or 8 CJK units;
- benchmark text units (letters and digits): short 28, medium 91, long 278 (`BenchMatrixSpec`,
  also the macOS UI bench), iOS UI long 126;
- click counter (`PCM16StreamLimiter`, 24 kHz): slew clamp 0.42, events at most 240 samples apart,
  envelope coefficient 1/240, low-energy envelope 0.02; the per-sample click bound warns above a
  0.0005 and fails above a 0.005 fraction of the take.

The whole Fast QC v8 has one more mirror, `FASTQC_V8` with `fast_qc_v8()` in
`scripts/lib/audio_qc.py`, which the qualification engine runs over constructed fixtures. It mirrors
the values above plus the rest of `PCM16StreamLimiter` and `makeAudioQCReport`. Both sides are
pinned to one calibration record, `config/audio-qc-stage0-calibration.json` (algorithm v8,
`legacy-unqualified`, audit section 5.5): the Swift `AudioQCStage0CalibrationTests` asserts the
limiter constants, `StreamingExecutionContext.AudioQCThresholds` and the speaking-rate bands equal it,
and `scripts/tests/test_audio_qc.py` asserts `FASTQC_V8` does, so neither reads the other's source.
The values: ceiling 0.965 with a 0.002 per-sample gain release;
step bursts of steps above 0.25 in 480 samples, warning `onset_step_burst` from 3 steps starting
in the first 50 ms; silence below 0.001, interior runs recorded from 2,400 samples (at most 256);
`near_silent` below -60 dBFS and `low_level` below -45 dBFS; clipping failing above a 0.001
fraction and warning on any sample beyond full scale; `hot` above a 0.02 fraction; DC warning
above 0.05 and failing above 0.20; the pause budget from the text's punctuation runs, a cadence
pause of 350 ms (600 ms from 45 s), an egregious gap of 1,200 ms without a declared pause and
2,000 ms with one or from 45 s, and a suspicious single pause of 900, 1,200 or 1,500 ms. One known
difference: both sides write PCM16 at x 32767, but the mirror reads the persisted PCM16 back at
1/32767 while the engine's `AVAudioFile` float processing format converts at Core Audio's 1/32768.
The persisted pass supplies only the output sums and silence runs, so RMS and DC differ by a factor
of 32767/32768 (-0.00027 dB), no PCM16 value changes side of the 0.001 silence floor, and a
persisted-pass step can clamp differently only within one LSB of the 0.42 slew bound.

### Stage 0 observational measures and engine introspection (AQ-04, 2026-09-26)

Fast QC reads amplitude and waveform shape only (audit AQ-F08). AQ-04 adds the audit's Stage 0
candidates (section 4.5) as observations: no flag, verdict or Fast QC version reads them, they join
QC v8 additively like the clustered click events (decision 8(a): the M6 gate baseline binds v8),
and a measure gates only after a qualified record under the authority below.

**Signal measures** (`AudioQCSignalObserver`, `AudioQCReport.signal`, own `algorithmVersion` 1).
The persisted-WAV pass feeds the observer the exact blocks it verifies, so every published take
(the streaming adapter and the atomic WAV sink) carries them; streamed takes pass the frame offsets
where one published chunk ends and the next begins.

- BS.1770-4 loudness of the mono take: K-weighting designed at the take's rate from the analog
  prototype (libebur128's design; at 48 kHz it reproduces the published coefficients), integrated
  loudness over 400 ms blocks every 100 ms gated at -70 LUFS and -10 LU, the maximum 3 s short-term
  loudness every 100 ms, and the EBU Tech 3342 loudness range (3 s every second, -70 LUFS and
  -20 LU, 10th to 95th percentile). A -20 dBFS 997 Hz tone reads -22.98 LUFS at 24 kHz.
- 4x true peak (dBTP) through a 49-tap Hann-windowed sinc (libebur128's design; phase 0 is the input).
- Noise floor: the nearest-rank 10th percentile of 10 ms frame levels, floored at -120 dBFS.
- WADA-SNR (Kim and Stern 2008) over the nonzero samples: the paper's 1e-10 floor would read any take
  with digital silence as the table's 100 dB ceiling. The Gamma (alpha 0.4) table is derived by
  quadrature of the paper's model (`wada_gamma_table`, within 0.0053 of the published simulation)
  and stored in the record. A pure tone reads the table floor, -20 dB.
- Effective bandwidth: the highest bin of the active frames' long-term spectrum (Hann 512 at 24 kHz,
  10 ms hop, frames at or above -60 dBFS) within 50 dB of its maximum.
- Spectral-flux events per second: frames whose mean positive dB rise per bin over the previous
  frame reaches 10 dB; rises within 50 ms are one event. Speech onsets count as well as clicks.
- Codec-frame modulation index: 2 |DFT at 12.5 Hz| / sum of the 10 ms RMS envelope over whole
  periods (the tokenizer frame rate is exactly 8 frames).
- Seam discontinuity: at each streaming seam, the first difference against the 10 ms either side,
  (d - mean) / max(std, 1 LSB); the maximum and where it starts.
- Repetition stripe: 40 ms frames of 16 mean-removed log band levels; the longest run along one lag
  (200 ms to 15 s) of active frames with cosine at least 0.95 that holds two or more spectral changes
  (so a steady tone forms none), its lag, and the count of runs of 600 ms or more.

Eleven of them reach the tracked take as `audioQC.metrics` (`QC_SIGNAL_METRIC_MAP`: the three
loudness values, true peak, noise floor, WADA-SNR, bandwidth, flux events per second, modulation
index, seam maximum z and the longest stripe), which answers AQ-F11's "loudness never reaches
history". Cost: fixed scratch per take, per-block temporaries and one scalar per 10 ms frame,
100 ms loudness block and 40 ms feature frame, well under 1 MB for a two-minute take; the FFT,
K-weighting and true-peak filters run in Accelerate and the stripe search is linear in take length
(at most 375 lags). Estimated at a few milliseconds per 10 s take in an optimized build; the
development build's scalar loops cost more. The time falls inside the request window, so it is
product work that RTF deltas measure; what the engine-generation kind measures does not change, and
its measurement version stays 2.

**Engine introspection** (`Qwen3GenerationIntrospector`, the facade's
`VocelloQwen3GenerationIntrospection`, the engine row's `engineIntrospection`, own version 1). The
generate loop builds two lazy scalars from the talker logits it already holds, the entropy and EOS
probability of the distribution over the codec codebook and EOS before suppression, penalty,
temperature or truncation, through a graph compiled once per generation, and evaluates them with
the step's own graph, so the reads after the token read add no synchronization and sampling never
sees them. The diagnostic `.deferred` step policy, which evaluates nothing with the step, skips them.
The added GPU work is a few fused kernels per step; its RTF cost is for the gate bench to measure. Per step it updates fixed state
allocated once: a 32-token ring with 32 run counters (the longest exact cycle of period 2 to 32,
ties to the shortest period, so a stuck token counts as a run), a 1/32-nat entropy histogram (mean,
nearest-rank p95, the longest run at or above 4 nats), the EOS maximum, final value, first step at
or above 0.5 and the steps at or above 0.5 that did not stop, and at most 256 seam frames. The loop
takes no lock and formats no string per token; the summary is stored once, when the loop exits,
cancelled or not.

**Parity.** Swift owns every constant; `config/audio-qc-stage0-observations.json` pins both sides
(`AudioQCSignalObservationTests`, `Qwen3GenerationIntrospectionTests`,
`scripts/tests/test_audio_qc_observations.py`), and the shared fixtures
`scripts/tests/fixtures/audio_qc_stage0_observations.json` (tones, silence, clicks, repeated
segments, 12.5 Hz modulation, seams, token loops and step trajectories) hold the expected values of
the float64 mirror `scripts/lib/audio_qc_observations.py`: integers must match exactly, reals within
one four-decimal rounding step. `fast_qc_v8()` adds the `signal` block unless asked not to; the
qualification engine's M1 skips it because it scores only the v8 flags.

### Threshold-change authority

The Fast-QC cadence and dropout boundaries (`makeAudioQCReport`, algorithm v8; v7 added only the
warn-only `onset_step_burst` flag and v8 only the warn-only `speaking_rate_slow` flag, and the
observational clustered click events joined v8 additively; no cadence, dropout or click boundary
moved) change only under
this policy, carried over verbatim on 2026-09-12 from the retired cadence contract,
`audio-cadence-qc-contract.json` (in git history):

- an untouched confirmation cohort is required (`requiresUntouchedConfirmation`);
- independent reference evidence is required, independent human labels are not
  (`requiresIndependentReferenceEvidence`, `requiresIndependentHumanLabels: false`);
- automatic metrics may screen candidates only, never qualify a change
  (`automaticMetricsMayScreenOnly`);
- a source change requires an explicit review (`sourceChangeRequiresExplicitReview`);
- the current boundary remains authoritative until a change is qualified
  (`currentBoundaryRemainsUntilQualified`).

**Qualification policy (decision 7, adopted 2026-09-25).** The maintainer accepted every
recommendation of the audio QC audit (`docs/audits/2026-09-25-audio-qc-speech-analysis-audit.md`,
section 5.6). `config/audio-qc-qualification-policy.json` carries the five rules verbatim and adds
A1-A10: scope-bound status, in-domain FAR on N2, detection on two construction mechanisms, matched
shams, pre-registration by digest with one confirmation, no same-lineage labels, automatic
de-qualification, status-specific operating points, heard defects entering as shadow detectors, and
the existing Fast QC fail bounds kept as `legacy-unqualified` until a qualified successor replaces
them. Its operating points are decision 5: warn at the 60/60/60 floor (FAR at most 0.10 pooled);
fail at a one-sided Clopper-Pearson FAR of at most 1% pooled and 5% per language on N2 (1,240 N2 and
600 N3 negatives, 60 positives per subtype, severity and mechanism) for any product-affecting fail,
with 2% pooled and 10% per language accepted for evidence-lane gating only. A per-language bound is
a simultaneous claim over the languages it covers, so it holds at the Bonferroni confidence the
policy states per operating point: 0.995 over the ten fail languages, about 0.983 over warn's three.
At 0.995 the evidence-lane floor is 51 N2 negatives per language (510 pooled), since 29 bound the
per-language FAR only at 0.167; the fail floor of 124 per language holds (104 needed with zero
alarms). The N3 flag-rate bound is pooled over the 600 N3 negatives; the 60 per language are
coverage. Every rate counts source families, not clips. New claims use one-sided Clopper-Pearson;
the Wilson figures above stay for legacy records.
`scripts/audio_qc_qualification.py validate-policy` runs in the contract gate: it recomputes the
sample-size table, refuses a floor that cannot meet its own bound with zero errors at the confidence
that bound is claimed at, requires fail to be stricter than warn, and holds the verdict vocabulary and
lane gating sets to the composer's.

### Qualification engine and the first measurement of Fast QC v8 (AQ-03, 2026-09-25)

The engine lives in `scripts/lib/qc_qualification/`: exact one-sided Clopper-Pearson bounds and
rates at a declared operating point, counted per source family, an abstention on a positive being a
miss (`stats`); a cluster bootstrap that draws whole source families (`resampling`); the
correlated-failure audit between two judges, with phi and conditional failure rates per unit and the
joint failure bound per family (`correlation`); and threshold derivation from clean negatives only
(`thresholds`). A derivation reads its plan back from a committed plan file
(`config/audio-qc-preregistrations/<detector id@version>.json`, one plan per detector version,
which must exist at HEAD unmodified), so a plan held only in memory is refused (A5); it takes one
score per family, by the split-conformal quantile or fixed-sequence Learn-then-Test; the
calibration and confirmation cohorts are split by connected component of family, speaker and
script, so they share none of the three, or declared as two pinned cohort manifests (the FLEURS
split, below); and the one confirmation per plan checks every requirement of the chosen operating
point (pooled and per-language N2 FAR, the pooled N3 flag rate, clean abstention, detection per
severity cell on two mechanisms, the minimum units and a matched sham per mechanism, A4) and records
its outcome, qualified or refused, in a ledger file created exclusively beside the plan, so no
process can confirm the plan again. The rest: procedural speech-like sources and the abstention fixtures (`fixtures`); the T1
injector catalog (`injectors`); the Stage 3 composer (`composer`); and the policy validator
(`policy`). No WAV is committed: fixtures are generated from seeds, and randomness comes from
`PCG64.random_raw()` words, the part of NumPy's random API that stays stable across releases.
Fixture version 2 band-limits the fricative and aspiration noise around 6 kHz, with nulls at DC and
Nyquist; version 1's first difference put the noise energy, and the largest sample-to-sample steps,
at Nyquist.

The version 2 T1 catalog has 17 families: clicks, dropouts, clipping, DC, level, additive noise
and hum, leading or terminal silence, truncation, run-on, repetition, word deletion and insertion by
splicing, octave jumps, pitch breaks, tempo change, pitch-and-formant shift and an identity swap that
splices a second voice rendering the same script. Each is a pure function of source, parameters and
seed with a golden PCM16 digest per variant (`scripts/tests/test_qc_qualification_injectors.py`),
a zero-magnitude sham that draws the same positions as its positives, a mild, moderate and severe
sweep, and a labeled interval covering every sample the injection changed. Controls are matched
processings that are not identities: the natural-pause control re-times a source's declared
punctuation pause to the dropout's length and runs only on sources that declare one; the
peak-normalization control of the clipping family is a whole-file gain to full scale that clips
nothing. Clipping (v2) flattens or soft-knee squashes the loudest fraction of samples with no gain,
so its label is exactly the changed samples; its over-range variant is the gain that drives that
fraction beyond full scale, labeled as the whole take. Pitch and tempo use a windowed-sinc resampler
and plain overlap-add, so they are signal-level constructions, not natural prosody.

**Catalog version 3 (2026-09-29)** adds the positives classes A, E, F and J were waiting for, and
leaves every version 2 output byte-identical (the version 2 goldens are unchanged; the new variants
have their own):

- **SIG-BAND** (A): a zero-phase 511-tap Blackman-windowed-sinc low-pass at 0.7, 0.5 or 0.3 of the
  source's measured effective bandwidth (Stage 0's definition, at the injector's own constants), so
  it cuts content the source has whether it is FLEURS-derived N2 (about 8 kHz) or a natural take
  (about 11.5 kHz). It refuses a source with no active frame, a cutoff below 1 kHz, and a low-pass
  that leaves the measured bandwidth unchanged. Sham: the same low-pass at 1.1 of the bandwidth
  (at most 0.99 of Nyquist), which keeps the measured band. The label is the whole take.
- **PRS-ERRATIC** (F): the take cut into seeded 150-300 ms spans, each shifted by a seeded sign of
  2, 4 or 7 semitones through PRS-OCT's shifter, length kept and neighbours crossfaded over 5 ms. It
  needs no word interval, so it runs on N3. Sham: 0 st through the same path.
- **IDN-ONSET** (E): another voice over the first 0.3, 1.0 or 1.5 s of speech from the first word.
- **SEAM-DISC** (J): 1, 5 or 20 ms removed right after a seeded long-form seam, with no crossfade;
  sham: nothing removed. **SEAM-VOICE** (J): the segment after a seeded seam in another voice, for
  1 s, 2 s or the whole segment. Both act at the seams a source declares (`Fixture.seams`; a
  long-form take's `seamSamples`) and refuse a source without one; every output carries its own
  seams, moved by the edit.
- **Speaker donors.** On procedural sources, IDN-ONSET and SEAM-VOICE splice a time-aligned
  re-render by a close voice, as IDN-SWAP does (sham: the source's own render; control: a same-speaker
  re-render). On a speaker-labelled recording, IDN-SWAP, IDN-ONSET and SEAM-VOICE gain `take-*`
  variants that splice a *donor* recording's opening words over the source's words at aligned word
  boundaries (or from the seam), level-matched: another speaker of the source's language and gender
  for the positives, another utterance of the source speaker for the sham, so the two differ only
  in who speaks. **IDN-IMPOSTOR** (E, `T1-parallel-corpus`,
  `lib/qc_qualification/speaker_donors.py`) presents another same-language, same-gender speaker's
  recording as it is, with its own text, as the source speaker against the source take as the
  reference clip; its sham is another utterance of the source speaker. Donors come from the same
  cohort manifest, never from another split.

A set records its catalog version, and `verify` refuses a set of any other version whole, naming it.
The 11 AQ-07 warn plans bind injector catalog version 2, so their confirmation set stays the one
built with version 2, verified by the code of that version.

The composer is pure and never cached. It emits `pass`, `warn`, `fail`, `inconclusive` (a gating
abstention), `uncalibrated` or `unavailable`, in that corrected precedence: fail, unavailable,
abstain, warn, uncalibrated, pass. A verdict with no calibration record composes as `uncalibrated`,
one outside its record's scope as an abstention (A1), and a legacy bound keeps its verdict (A10). The
orchestrator (AQ-05, below) composes every take with it beside the lanes' own verdicts, which it
replays unchanged; no lane gates on it until its detectors qualify (AQ-07).
Swift gained the matching `GenerationQualityOutcome.abstained`: it ranks 3 with `fail` and
`unavailable`, above the unchanged pass 0, uncalibrated 1 and warning 2, and the registry reports it
distinctly unless a gate failed or was unavailable. No producer emits it yet.

**M1, "measure the present".** `python3 scripts/audio_qc_qualification.py meta-evaluation` runs the
v8 mirror over clean procedural sources (60 modal, 30 each quiet, breathy, long-pause and high-F0),
every injector variant of the 60 modal sources and the 12 abstention fixtures, and replays the
committed benchmark records read-only. It writes `meta-evaluation.json` and `meta-evaluation.md` to
`build/artifacts/diagnostics/audio-qc-meta-evaluation/` in about 30 s. The output is untracked and
deterministic for a given tree, so it is not a registered `scripts/dev.sh regen` artifact; publishing
it as a tracked `qc-calibration` record needs that record kind first. It is report-only:
procedural sources are T1 construction, neither N1 nor N2, so under A2 they never qualify a fail
bound, and a rate on them describes the fixtures as much as the detector. The run of 2026-09-25
(seed 7, injector catalog 2, fixtures 2) measured:

- clean modal speech: 0 of 60 alarms (at most 0.049 on these fixtures); every alarm on clean speech
  (17 of 180) was a `dropout` warning in the long-pause stratum, whose declared pauses of 0.9-1.5 s
  straddle v8's 1.2 s bound for a declared pause by construction;
- clicks: 0 of 60 detected at 0.2 FS once per second or 0.5 FS five times per second, 60 of 60 at
  full scale 50 times per second, the per-sample fraction bound growing with take length as audit
  #85 found;
- dropouts: 0 of 60 at 150 ms inside a word, 22 of 60 (a cadence warning) at 600 ms, 60 of 60 failed
  at 2 s; terminal silence: 9 of 60 at 1 s, 60 of 60 from 2.5 s; 2.5 s of leading silence never reads
  as silence (16 of 60 warned only through the speaking rate);
- clipping: flattening or soft-knee squashing up to 5% of samples below full scale raised nothing
  (0 of 60 at every severity), since v8's clipping flag counts float samples beyond full scale and
  flat tops below full scale have none; driving 1% of samples beyond full scale failed 60 of 60;
- run-on: 0 of 60 at 0.5 s, 1 of 60 at 1.5 s and 49 of 60 at 4 s of repeated tail speech, the
  speaking-rate warning firing only once a take nearly doubles; a 0.7x tempo never reaches it;
- no v8 detector for additive noise, truncation, word deletion, octave jumps, pitch breaks, pitch and
  formant shift or an identity swap: 0 of 60 alarms at severe for each, except white noise at 0 dB
  SNR, which trips `clicks` incidentally;
- shams and controls, compared under A4 on each family's own target flags with the clean rate on the
  same sources: none departs (0 of 12 with a v8 detector). The shams are identities (the clipping
  sham included), and the natural-pause control raised nothing on the 51 sources that declare a
  pause. The peak-normalization control (a labeled control, not a sham) raised no clipping or `hot`
  flag but raised `clicks` on 31 of 60; all 4,042 clamped samples lie in the fixtures' fricative-noise
  bursts driven to full scale, so it measures that construction, not a false-alarm rate on speech;
  whether natural speech at full scale trips the 0.42 slew clamp needs N1 or N2 (A2);
- abstention fixtures: v8 passes 6 of 12 (a chord, a clip under 1 s, a 64 s take, whisper phonation,
  a 650 Hz F0 and a repeated-word script), as an amplitude-only gate that cannot abstain;
- committed evidence, counted per family (a seeded cell, seed and model, else one take, with families
  that share a published WAV digest merged): 3,817 takes with audio QC in 349 records, published PASS
  or WARN only, so a fail rate there bounds nothing; QC v3 warned on 49 of 2,930 families (3,287
  takes), and the 63 QC v8 takes (23 families) carry no warning. The v8 bound replay sees only each
  take's longest silence, never its pause budget or pause count, so its dropout column misses v8's
  0.9-1.2 s warnings without a declared pause, its excess-pause fails and its cadence warnings.

**AQ-07 calibration set, M2 on natural takes.** `python3 scripts/audio_qc_calibration_set.py inject
--takes <manifest> --output <dir>` applies the T1 catalog to every generated take of an
`audio-qc-calibration-takes` manifest (population N3): the class A, C and signal-level F injectors at
sham, mild, moderate and severe, about 40 clips per take, each seeded from the source WAV digest, the
injector and the catalog seed. A recorded take has no word intervals, declared pauses, script or
render voice (`scripts/lib/qc_qualification/recordings.py`), so `injectors.inject` refuses every
variant that needs one with `InjectorNotApplicable`, counted with its reason in
`injection-set.json`. SIG-CLIP refuses the same way a source already flat at its peak, whose loudest
fraction shares one magnitude so that nothing lies above the clip level (first met on the N2
confirmation cohort, 2026-09-29; every other output is byte-identical). Word-free recording variants (`take-*`) stand in: clicks anywhere, a
dropout centred on the take, noise against the whole take's RMS, a cut at 80, 65 or 50% of the take
(which may remove only the trailing pause) and a run-on of a middle span appended after the take's
end. The catalog variants and their goldens are unchanged. Octave jumps and pitch breaks stay not
applicable, content (B) and identity (E) injectors are out of scope, and identity swaps from donor
pairs are deferred: the donor take has its own timing, not the time-aligned re-render the swap
splices. `verify` replays every recipe from the source WAVs; `score` runs the v8 mirror and the
Stage 0 observations over the takes, shams and positives and writes `measurements.json` (ids and
digests only), `report.json` and `report.md`: per-family CP bounds per flag, A4 sham overlaps, TPR
per injector and severity, per-language rows and the worst stratum. It is report-only: N3 carries
no labels (FAR <= f / (1 - pi_max)) and T1 on N3 qualifies nothing (A2, A5). On synthetic 6 s takes
with six jobs, 40 takes took about 1.5 s to inject, 1.2 s to verify and 14 s to score, and wrote
about 12 MB of WAV per take. `inject` and `verify` also take an N1 cohort manifest of FLEURS human
recordings (`scripts/audio_qc_n1_corpus.py`, [language-bench.md](language-bench.md#human-recordings-n1-aq-07)),
eligible recordings only. Each 16 kHz recording is resampled to 24 kHz with the Kaiser-5 polyphase
design of `polyphase-kaiser5-v2` (`lib.playback_capture.resample`) before any injector runs, because
click widths, cluster spacing and the overlap-add window are counted in 24 kHz samples and `score`
and `verify` read 24 kHz; every recipe records it as `sourceResampling`. `score` also scores an N1
or N2 cohort, labeling its clean recordings N1 or N2 (see "Injections on N2" below).

### Staged pipeline, workers and admission (AQ-05, 2026-09-26)

`scripts/audio_qc_orchestrator.py` is the one orchestrator for Stages 1-3 after the generator exits
(audit sections 3.1-3.6). It loads no model. A manifest (`manifest --from-independent-asr-manifest`
for the language lane, `--from-cascade-input` for the delivery lane) must declare
`generationProcessExited`, and every take is bound to its WAV digest before anything runs.

- **One host-wide lock root.** `delivery-analysis-supervisor.lock` and the admission ledger live
  under `hostAnalysisLock` in `config/build-output-policy.json`
  (`~/Library/Caches/Vocello/delivery-analysis-lock`), never beside a cache root: every generator,
  standalone analyzer, qualification probe and orchestrator on the host contends on one lock and
  spends one budget, whatever its checkout, worktree, `--cache-root` or
  `QVOICE_DELIVERY_ANALYSIS_CACHE`. No tool takes a `--lock-root`; `QVOICE_DELIVERY_ANALYSIS_LOCK_ROOT`
  overrides the root for tests only (the Python suite gives each test process its own).
- **Admission (decision 9a).** A generator and every standalone analyzer still hold the lock
  exclusively. An orchestrator run holds it shared and admits each worker against
  `config/audio-qc-judges.json#admission`: a 10 GiB budget (16 GiB less about 4.5 GiB for macOS and
  tooling and a 1.5 GiB margin, provisional until AQ-06 measures it), one MLX GPU worker at a time
  beside at most two CPU workers, and each judge at its ceiling (its calibrated `ceilingBytes` once
  AQ-06 promoted it, else its provisional ceiling; the qualification run alone measures a
  provisional judge under the budget less the orchestrator reservation instead). The supervisor
  (`owned-process-probe-v5`) samples the worker's whole process group every 50 ms and enforces the
  same ceiling live on the group's summed resident memory and footprint, so a native judge binary
  the worker runs is stopped while it runs, not after it exits; it refuses a child above its ticket. An absent footprint from a child that is exiting waits
  up to 2 s for the exit to become observable before it counts as a probe failure (v5: in v4 that
  race failed finished MLX workers and discarded every row they had emitted). The ticket learns the child's PID inside the
  supervision's `try`, so a failed ledger write (a full disk, an unreadable ledger) still terminates
  and reaps the child, and a ticket is released only once its child is gone. The ledger records each
  owner and child by PID and process start time, so a reused PID never pins a stale entry; a live
  child keeps its budget even if its orchestrator died. `admission-status` prints the ledger. The
  registry's admission validator runs when the registry or the policy loads, so an invalid or
  unevidenced admission block is refused, not applied.
- **One persistent worker per judge per run.** `scripts/audio_qc_worker.py` loads its model once,
  warms it and streams the job's rows in job order as JSON lines (`whisper-mlx` wraps
  `independent_asr_worker.py`'s recognizer; `native-command` runs the pinned SenseVoice binary per
  row, whose model reload per invocation stays, and also reports each invocation's `wait4` peak as a
  second, per-row check). The protocol owns stdout alone: the worker keeps a private duplicate of
  its stdout for the JSON lines and points descriptor 1 at stderr before any library loads, so a
  banner a library prints (FunASR's, a loader's progress line), from Python or native code, lands on
  stderr. A launch's timeout is a start-up allowance (900 s) plus a per-row budget for
  each row it holds (900 s by default, the old per-clip allowance; the orchestrator's
  `--timeout-seconds` and the compact batch path's `timeout_seconds` set it per row). A worker that
  ends abnormally keeps the rows it emitted; the row in flight is retried alone once, then the rest
  continue in a fresh worker, each recorded as its own launch. Only a row that ends two workers
  abnormally is `unavailable` (`crash`, `timeout` or `envelope-breach`), so one bad row never costs
  the rows after it; a worker that fails before it is ready is retried once with all its rows. A
  failed host condition (pressure, swap, recovery) accepts nothing and retries nothing. Each judge's
  thread count is declared in the registry, fixed in the worker's environment before it starts (the
  worker refuses a mismatch) and part of its output identity. The delivery cascade's compact layer
  uses the same worker once per run (`run_compact_adapter_batch`), keys its entries on the worker
  host's source too, and caches only clips from a qualified launch.
- **L0-L2 cache.** L0 is the canonical 16 kHz derivative; L1 a judge's raw output, keyed by the
  L0 digests, the judge's output identity (never the supervisor) and the request (a recognizer's
  locked language); its wall time rides beside it as the measurement's `wallSeconds`, never inside
  it. L2 is the metrics, keyed by the L1 key, the metric definition's version, the digest of every
  source that shapes the value (a declared list per judge: `lib/language_metrics.py`,
  `lib/qc_pipeline/verdicts.py` and `independent_asr.py` for a recognizer, whose detected language
  `_recognition` maps; the compact adapter and `verdicts.py` for SenseVoice's tags) and the scoring
  inputs (script digest, language). A Stage 1 DSP judge's raw output is its metric vector, so its L2
  is its L1. Verdicts are never cached. Orchestrators share the cache: rows are re-checked after
  admission and one another run stored meanwhile is adopted rather than launched, a stored entry
  that differs from this run's (a nondeterministic judge) is adopted rather than failing the take,
  and each judge's rows are stored as its worker finishes, so a judge whose admission times out
  (`admission-timeout`, unavailable) discards no other judge's results.
- **L0 and Stage 1 hold a slot.** An orchestrator's in-process canonicalization and Stage 1 DSP
  take a `dsp` slot of the ledger (their memory stays inside the orchestrator's reservation); while
  the whole-host recovery rule binds, that slot counts against the one-worker cap, so no admitted
  worker's envelope overlaps another orchestrator's DSP.
- **Stage 3.** Today's verdicts are replayed from L2 through the unchanged code: the language lane's
  `witness_verdict` and the cascade's `review_automated_audio` and `compose_route`, each given a
  scorer that rebuilds `score_recognition`'s result from the cached metrics and today's thresholds.
  Beside them the composer emits content (class B) and language (class D) detector verdicts,
  Fast QC's (class A, stage 0; v8 cites its legacy-unqualified Stage 0 record) and canonical
  integrity's (class A, stage 1). None has a qualified record, so a language take composes as
  `uncalibrated` at best; a judge the run lost makes its detectors `unavailable`.
- **Evidence.** Each take gets a `vocello.audioqc.take-evidence/1` record: digests, flat metrics,
  the composer's verdicts and the replayed ones, validated to carry no transcript, text or path. The
  private bundle (`build/artifacts/macos/audio-qc/<run>/`, untracked) holds `bundle.json` with every
  worker launch and resource envelope, the records, and per-take private files (audio path,
  reference text, transcripts); failing takes are named in it, never committed as audio. A take
  whose manifest ID is not a safe token is named by its digest in both its record and its private
  file (the manifest ID stays in the private file). `validate-bundle` re-hashes and re-validates it
  and refuses one inside tracked paths.

**Replay.** `replay --manifest … --bundle …` reruns Stage 3 from the cache and refuses if any model
would have to run; `replay-records` runs the same Stage 3 functions over the committed language
records. Offline tests (`scripts/tests/test_audio_qc_orchestrator.py`) prove, with a fixture worker
under the real supervisor and admission: the orchestrator's language verdicts equal
`witness_verdict`'s over the same recognitions for pass, fail, one-witness, two-family, disagreeing,
unqualified, Korean and out-of-scope takes; its delivery routes and automated reviews equal
`run_cascade`'s for clean, native-failure, content-failure, disagreeing and silent pairs; a second
run launches nothing and reproduces every record exactly; and a metric-definition change recomputes
L2 from L1 without a model. Over the committed records, accuracy is recomputed for all 45 takes that
carry recognition metrics (5 of 8 records), the language channel for 31 (Apple Speech's match score;
whisper's detected language, which the newest whisper record carries; the other 14 use the
recorded channel), and every take's expectation and each record's `outputCellsPassed` and
`negativeControlsConfirmed` match.

**Recovery-rule switch.** `delivery_resource_supervisor.run_supervised(recovery_rule=…)` makes the
child-attributed rule (`attributed-post-exit-recovery-v2`) binding in place of the whole-host rule;
each envelope keeps the whole-host outcome (`wholeHostRecoveryFailures`) either way. The switch is
`admission.recoveryRule.candidateBinding` in the registry, `false` today: report-only, and while
the whole-host rule binds, admission caps the host at one supervised worker (L0 and Stage 1
included), since one worker's post-exit drop cannot be told apart from another's allocation. Each
envelope names its session (the orchestrator run, or the standalone process) and its hardware
profile (`hostProfileID`, matched from `benchmarks/hardware-profiles.json`). `recovery-report`
counts an admitted envelope as serial only when its admission capped the host at one worker with
Stage 1 counted (`serialScope`), and reports `overlapPossibleEnvelopes`, `serialByJudge`, the
`sessionIDs` and the `hostProfileIDs`. The registry validator, which also runs whenever the registry
or the admission policy loads, accepts `true` only when `promotion.evidence` cites at least two
`recovery-report` files committed to the repository by path, file SHA-256 and date; it reads the
counts from each committed file, never from the registry: the canonical profile only, every
envelope with a session and a host, no session shared between reports, serial envelopes of every
orchestrated GPU and CPU judge, `overlapPossibleEnvelopes` 0,
`serialCandidateWouldQualifyBindingFailure` 0 (with nothing else running, the candidate never
blamed a drop on another allocator) and `unattributed` 0. An uncommitted or edited report, or a
local flip without evidence, is refused. Flipping it lifts the cap to the lane limits.

**Retired from QC.** DistilHuBERT (`compact.distilhubert@1`) and the fitted ridge, elastic-net and
PLS heads (`delivery.fitted-heads@2`) are retired as measurands (audit sections 4.9 and 7.1): the
cascade takes no evaluator model and requests no `tiny-local-heads` layer, DistilHuBERT left the
candidate order, the adapter and the preparation tool, and both sit on the exclusion list. Their
licenses stay recorded as permissive. `delivery_evaluator.py` keeps the heads' fitting commands as
research tooling outside every QC path.

### Judge panel acquisition (AQ-06, prepared 2026-09-26)

The audit's panel (section 4) is registered in `config/audio-qc-judges.json` as `candidate` judges.
Each is pinned to every file it fetches at its revision, with the size. A Hugging Face file pins its
LFS SHA-256, or, for a small non-LFS file, its git blob ID; the pins were read from the Hub's tree
metadata on 2026-09-26, and nothing was downloaded. DNSMOS is the one GitHub-sourced snapshot: each
file pins its size, content SHA-256 and git blob ID at a commit. Each judge also records its license
tier, its voting role, its output identity, and a ceiling and thread count marked `provisional`.
These are audit estimates; the two clean M6 runs replace each ceiling with the larger measured peak
× 1.2 (`ceilingStatus: calibrated`). The estimates never bound the measurement: the qualification run
admits a provisional judge at the budget less the orchestrator reservation, the largest ceiling
admission can grant one worker, so a judge it stops could never be admitted at all.

| Judge | Repository @ revision | GB | Stage | Tier | Votes | Status |
|---|---|---|---|---|---|---|
| `asr.whisper-large-v3@1` | `mlx-community/whisper-large-v3-mlx@49e6aa28` | 3.08 | 1 | B | yes | candidate |
| `asr.parakeet-tdt-0.6b-v3@1` | `mlx-community/parakeet-tdt-0.6b-v3@ed2b7e8c` | 2.51 | 1 | B | yes | candidate |
| `asr.paraformer-zh@1` | `funasr/paraformer-zh@d7811ee3` | 0.89 | 1 | A | yes | candidate |
| `asr.sensevoice-small-f16@1` | `FunAudioLLM/SenseVoiceSmall-GGUF@90c1c619` (f16 file only) | 0.47 | 1 | A | yes | candidate |
| `lid.voxlingua107-ecapa@1` | `speechbrain/lang-id-voxlingua107-ecapa@0253049a` | 0.09 | 1 | B | yes | candidate |
| `speaker.campplus-voxceleb@1` | `Wespeaker/wespeaker-voxceleb-campplus-LM@c5e01c6f` (ONNX only) | 0.03 | 1 | B | yes | candidate |
| `pitch.pyin@1` | librosa 0.11.0, no weights | 0 | 1 | A | no | candidate |
| `asr.qwen3-asr-1.7b@1` | `mlx-community/Qwen3-ASR-1.7B-bf16@e1f6c266` | 4.08 | 2 | A | no (same lab) | candidate |
| `align.qwen3-forcedaligner-0.6b@1` | `mlx-community/Qwen3-ForcedAligner-0.6B-bf16@53c8c0e4` | 1.84 | 2 | A | no (same lab) | candidate |
| `speaker.resnet293-voxceleb@1` | `Wespeaker/wespeaker-voxceleb-resnet293-LM@6e6bffe5` (ONNX only) | 0.11 | 2 | B | no (until the correlated-failure audit) | candidate |
| `quality.audiobox-aesthetics@1` | `facebook/audiobox-aesthetics@9b1dd8e5` (safetensors only) | 0.42 | 2 | A | no (advisory) | candidate |
| `quality.dnsmos-p835@1` | GitHub `microsoft/DNS-Challenge@591184a9` (`DNSMOS/DNSMOS/sig_bak_ovr.onnx`, `model_v8.onnx`) | 0.001 | 2 | B | no (advisory) | candidate |

Nothing is quarantined or listed in `acquisitionBlocked`. Two maintainer decisions of 2026-09-26,
recorded in each entry's `licenseDecision`, cleared the earlier holds:

- **ResNet293.** The CC BY 4.0 license its card declares at the pinned revision is accepted (the
  audit had recorded Apache-2.0). It stays tier B, internal evaluation only. It is a stage 2
  candidate that does not vote: it shares CAM++'s VoxCeleb training data, so it votes only after the
  correlated-failure audit (audit section 5) passes (`votingGate`).
- **DNSMOS P.835.** It is accepted as an advisory, non-voting screen under the CC BY 4.0 license of
  `microsoft/DNS-Challenge`, pinned at commit `591184a9fcb2cbdec02520fed81a32bbbf9d73ff`. The audit
  rated it A with its training-data terms still to confirm. The repository lists its corpora under
  their original terms, VoxCeleb2 among them, so it is recorded as tier B like every VoxCeleb-trained
  judge. Its engine (`dnsmos-onnx`) ports `DNSMOS/dnsmos_local.py` at that commit (blob `e32032e9`,
  MIT): 16 kHz mono, the clip tiled to at least one 9.01 s window, 1 s hops with the reference's
  float truncation (which skips some windows, for example those starting at 7-23 s), the P.808
  log-mel features with librosa's reflect padding (the reference pinned librosa 0.8.1), and the
  non-personalized polynomial mapping of SIG, BAK and OVRL, averaged over the scored windows.

**Attribution for evaluation-only assets.** `scripts/attribution_manifest.py` and
`config/third-party-attribution-policy.json` cover only what ships in the apps (resolved packages
and production catalog models), so evaluation-only judges keep their credits in the registry's
`license.notices` and here. None of them ships or is redistributed.

- ResNet293-LM: CC BY 4.0, WeSpeaker (wenet-e2e/wespeaker; Wang et al., ICASSP 2023), trained on
  VoxCeleb (CC BY 4.0; the audio's copyright stays with its owners).
- DNSMOS P.835: CC BY 4.0, Microsoft (microsoft/DNS-Challenge; Reddy, Gopal and Cutler, ICASSP 2022).
  The ported scoring in `panel_engines.py` credits `dnsmos_local.py`, MIT, Copyright (c) Microsoft
  Corporation.
- Audiobox Aesthetics: CC BY 4.0, Meta (Tjandra et al., 2025).

**Runtimes.** Each judge runs in the venv of its runtime family, built from a committed hash lock
(`config/audio-qc-runtimes/<family>.txt`). The nine locks target CPython 3.14.4 on macOS arm64 and
come from PyPI metadata alone. The registry records each lock's digest, and the validator refuses a
drifted lock, a judge pin that differs from its lock, and any locked package on the exclusion list.

- torch is held at 2.11.0 to match torchaudio 2.11.0, its newest release, whose wheels declare no
  torch pin.
- The FunASR lock builds four pure-Python sdists (jieba, oss2, crcmod, antlr4) from hash-pinned
  sources, after the lock's own setuptools.
- soxr, which librosa requires, is LGPL-2.1-or-later. It is recorded as a notice.
- `onnx-librosa` (DNSMOS) is its own family: the librosa-dsp pins plus onnx-cpu's onnxruntime,
  flatbuffers and protobuf, so the stage 1 onnx-cpu and librosa-dsp venvs keep their locks.
- SenseVoice f16 reuses the pinned llama.cpp runtime v0.1.9. Its command line has no language, ITN
  or thread option, so the audit's ja/ko lock and `use_itn=False` cannot be set. The judge's
  `decodeOptions` say so, and a take whose emitted language differs from the expected one abstains.

**Maintainer commands.** Run these from the main checkout. `fetch` is the only step that downloads.

```sh
python3 scripts/acquire_audio_qc_judges.py plan              # judges, bytes, destinations, disk needed; no network
python3 scripts/acquire_audio_qc_judges.py fetch --stage 1   # then: fetch --stage 2 (ResNet293, DNSMOS, ...)
python3 scripts/acquire_audio_qc_judges.py verify            # offline re-check of every receipt
python3 scripts/acquire_audio_qc_judges.py fetch --judge lid.voxlingua107-ecapa@1  # refreshes its receipt
```

The last line is needed once if VoxLingua was fetched before its `hyperparams.yaml` pin gained a
content SHA-256: `verify` then reports that its registry entry changed, and `fetch` re-verifies the
files already on disk and rewrites the receipt without downloading them again.

**Disk.** The models take 13.52 GB: stage 1 is 7.07 GB (the six current languages' voters, LID,
CAM++ and pYIN) and stage 2 is 6.45 GB (the adjudicator, the aligner, ResNet293, Audiobox and
DNSMOS). The runtimes add about 1.31 GB of wheels across nine venvs, about 4.6 GB once installed
(est.: wheel bytes × 3.5, the upper end of the earlier 3-4 GB for 1.19 GB), plus an 18 MB
interpreter. Everything lands under `build/cache/delivery-analysis/external-models/`, the
`delivery-analysis-cache` entry of the build-output policy. Before a fetch starts, the whole
selection must fit: its remaining model bytes, each venv still to build at that estimate and the
interpreter, plus a 2 GiB margin (`plan` prints the figure; a clean `--all` needs about 20.4 GB).

**What `fetch` and `verify` guarantee.**

- **Files.** Each file downloads into `.partial/` and resumes by HTTP range, from the Hub or, for a
  GitHub snapshot, from `raw.githubusercontent.com/<repo>/<commit>/<path>`. It moves into
  `<judge directory>/<revision>/` only once its size and every digest its pin records match. A
  mismatch is discarded, and a checksum is never inferred. File keys are relative paths that never
  climb, and a path that resolves outside the model root is refused before anything is written.
- **Transport.** Every download is https, and a redirect is followed only to https on
  huggingface.co, `*.hf.co`, `*.huggingface.co`, github.com, its release asset hosts and
  `raw.githubusercontent.com`. An https-to-http redirect, or one to any other host, fails the fetch.
- **Pins.** Repositories read `owner/name`; every file pin records its size; a git blob ID (SHA-1)
  pins only a small non-LFS file (at most 10 MB), and a panel weight file is pinned by SHA-256.
  VoxLingua's `hyperparams.yaml`, which SpeechBrain instantiates, pins its content SHA-256 beside
  its blob ID.
- **Interpreter and native runtime.** The python-build-standalone 3.14.4 archive and the SenseVoice
  runtime are verified by SHA-256. `verify` re-hashes the interpreter archive and compares every
  extracted file with it (bytecode under `__pycache__` is skipped and counted); `fetch` re-extracts
  an interpreter that no longer matches.
- **Venvs.** Each venv installs with `pip --isolated --require-hashes --no-deps --only-binary :all:`
  and `PIP_CONFIG_FILE=/dev/null`, so no pip configuration file is read. It must then equal its lock
  exactly, every installed file must match the SHA-256 its distribution's RECORD lists (entries
  without a hash, such as RECORD itself and bytecode, are counted), and an offline import probe must
  pass. `fetch` reuses an existing venv only while all of that holds, and rebuilds it otherwise.
- **Receipts.** A per-judge `receipt.json`, written last, records every digest, with names relative
  to the model root. It binds the registry entry's acquisition digest: the entry without its
  qualification state (`status`, `resources`, `determinismClass`, `canary`, `calibration`, `voting`,
  `votingGate`), so a promotion never makes a fetched judge stale. A receipt written before AQ-06 P8
  bound the whole entry; it stays current until the entry changes, and `fetch` of the judge rewrites
  it without downloading anything.
- **Workers.** The worker engines (`lib/qc_pipeline/panel_engines.py`, reached through
  `audio_qc_worker.py`) set the hubs offline and point `HF_HOME`, `HF_HUB_CACHE`, `TORCH_HOME`,
  `MODELSCOPE_CACHE` and `XDG_CACHE_HOME` into an empty directory created for the run, so a model
  cached anywhere else on the host can never load. Before anything loads, each runs the registry's
  load gate, which refuses an excluded installed package, and verifies every pinned file; a
  symbolic link anywhere inside a panel snapshot refuses the load. The weightless pYIN judge runs
  `require_runnable` instead of the file check.

### Panel jobs and qualification (AQ-06 P8 tooling, 2026-09-27)

**Orchestrator jobs.** `audio_qc_orchestrator.py run|replay` takes `--judge ID` (repeatable) or
`--panel` beside `--judge-config`, and `--model-root` (default: the owned `external-models` root).
Each panel judge runs from its receipt (`acquire_audio_qc_judges.worker_launch`): one persistent,
supervised worker per run, admitted at its registry ceiling, lane and thread count, with the
physical footprint measured. `lib/qc_pipeline/panel_jobs.py` shapes its rows and L1 key: Whisper,
Parakeet, Paraformer and SenseVoice read the ISO code and the Qwen3 engines the language name; the
aligner also reads the script (its digest is in the key); LID, speaker, pitch and quality judges ask
nothing, so identical audio shares one entry. A judge whose `panel.languages` omit a take's language
leaves it out of scope. Its output identity is the entry's acquisition digest, its runtime (lock or
native binary, and the interpreter), its worker sources, the host and its threads.
`lib/qc_pipeline/panel_metrics.py` reduces each family to L2 metrics:

| Family | Metrics |
|---|---|
| Recognizers | Normalization-v3 WER/CER from `score_recognition` (with a script); the detected language where the judge identifies it (Whisper, SenseVoice); the transcript stays private |
| VoxLingua107 | The posterior over the ten product languages plus `other`, the expected share, the top language and the margin |
| CAM++, ResNet293 | With a reference clip (a take's `referenceAudioPath`, clone lane): whole-take and per-window cosine; without one, no metric |
| pYIN | Voiced fraction, F0 median, mean, 5th and 95th percentiles, range and spread in semitones |
| Audiobox, DNSMOS | CE, CU, PC, PQ; SIG, BAK, OVRL and P.808 |
| Aligner | Units aligned of units expected, aligned span over the take, end gaps |

Every panel verdict is `reportOnly`: the composer lists it (`uncalibrated`, or `unavailable`) and
never gates on it, so a take's verdict is what it is without the panel. A judge votes only when the
registry says it votes and it has reached `warn`; the same-lab judges and ResNet293 never do. A
take without a script gets no language witness verdict (`no-reference-text`) instead of failing the
run, and an admission timeout composes as `timeout`.

**Qualification.** `scripts/audio_qc_panel_qualification.py` runs the AQ-06 gate. `run` renders the
committed canary set (`config/audio-qc-canary-set.json`: nine procedural takes from
`lib/qc_qualification/fixtures.py`, pinned by golden PCM digest, three with a reference clip), joins
the latest language-bench takes and runs every judge twice. Each run is its own orchestrator session
with a fresh cache, so every row runs a model. Everything stays in the untracked session directory
(`build/artifacts/diagnostics/audio-qc-panel-qualification/<session>/`). Per judge it records:

- **Resources.** Per launch: the ceiling it ran under and why, the sampled peak RSS and physical
  footprint, the reaped `ru_maxrss`, the child-attributed peak, a native binary's own peak and the
  failure codes. Per run: the largest of those peaks, wall time, model load, warm-up and threads.
  A provisional judge runs under the measurement ceiling (the admission budget less the orchestrator
  reservation), never its estimate.
- **A clean run.** Every envelope qualified on `mac-mini-m6-16gb`, no retry, no unavailable row and a
  quiet host (`require_quiet_host`).
- **Determinism.** The two runs' raw outputs compared row by row: D0 is bit-exact; D1 equals every
  discrete output, with the largest score difference as its measured tolerance; D2 is anything
  else.
- **The canary record.** Digests and flat metrics per canary take, never text or paths.
- **Private diagnostics.** `diagnostics.json` in the session directory names why each run was not
  clean: per launch its failure codes, probe and shutdown failures, whether a failed host condition
  discarded its rows, the reason its unresolved rows were given, its peaks against its ceiling and
  the tail of its stderr (`run-N/worker-stderr.json`). It is never published.

Each run also gets a `recovery-report`, the evidence the recovery-rule switch reads. With
whisper-small in the session, the flip analysis lists the language and accuracy verdicts that flip
against large-v3 on the speech takes. A judge passes with two clean runs, D0 or D1, and a peak whose
ceiling (x 1.2) fits the budget. `publish` copies the passing judges' canary records, the session
record, the flip analysis and both recovery reports to
`benchmarks/audio-qc-qualification/<session>/`; a failing judge's record stays private.
`validate` (in the contract gate) checks every committed record.

`promote` edits the registry for each passing candidate, and only from committed records:

- the status becomes `shadow`;
- `determinismClass` becomes the measured class;
- `canonicalHostPeakBytes` becomes the measured peak (the larger of the two runs), `ceilingBytes`
  that peak x 1.2, `ceilingStatus` `calibrated` and `ceilingSession` the session id; every later run
  admits the judge at that ceiling;
- `canary` cites the record by path, SHA-256 and output identity.

It rewrites only those values, and the registry must still validate. The registry then requires,
for every shadow or higher panel judge, a committed canary record whose judge, output identity,
registry-entry digest, class and peak match, and a calibrated ceiling must be the one that record
derived in the session it names. A warn or gating judge's record must also match
today's worker sources and runtime. `--bind-recovery-rule` cites the two recovery reports and flips
`candidateBinding`, and only when they meet its promotion. That needs whisper-small and SenseVoice
Q8 in the session too.

**Lead commands (consent-bound session on a quiet M6; no agent or native build alongside).**

```sh
python3 scripts/acquire_audio_qc_judges.py verify              # every receipt still verifies
python3 scripts/prepare_delivery_compact_model_config.py whisper-small-mlx \
  --output build/cache/delivery-analysis/whisper-small-mlx.json
python3 scripts/prepare_delivery_compact_model_config.py sensevoice-small-q8 \
  --output build/cache/delivery-analysis/sensevoice-small-q8.json   # only for the recovery-rule evidence
python3 scripts/audio_qc_panel_qualification.py plan \
  --manifest build/artifacts/macos/language/<latest lang-bench run>/independent-asr-manifest.json \
  --judge-config asr.whisper-small@1=build/cache/delivery-analysis/whisper-small-mlx.json \
  --judge-config compact.sensevoice-small-q8@1=build/cache/delivery-analysis/sensevoice-small-q8.json
python3 scripts/audio_qc_panel_qualification.py run  <the same arguments>
python3 scripts/audio_qc_panel_qualification.py publish build/artifacts/diagnostics/audio-qc-panel-qualification/<session>
# review, commit benchmarks/audio-qc-qualification/<session>/, then:
python3 scripts/audio_qc_panel_qualification.py promote benchmarks/audio-qc-qualification/<session> [--bind-recovery-rule]
```

Every backend's own library calls run for the first time in `run` (`parakeet_mlx.from_pretrained`,
FunASR's `AutoModel`, mlx-audio's `load_model`, SpeechBrain's `from_hparams`, the DNSMOS ONNX
sessions, the Qwen3 language names). A judge whose worker fails is `unavailable` and stays a
candidate, while the other judges' results stand. Its engine is corrected in a follow-up change and
the session rerun. The offline tests (`test_audio_qc_panel_orchestration.py`,
`test_audio_qc_panel_qualification.py`) drive the same code over fixture workers under the real
supervisor and admission.

**Full-cohort ceiling recalibration.** The 28-row canary session under-measures a real run. MLX
workers grow with every row, and row length varies. On the first full cohort (791 natural takes,
2026-09-27), Parakeet peaked at 5.44 GiB against its 5.04 GiB ceiling, and whisper-small at 2.68 GiB
against its 2.50 GiB provisional ceiling. Even in 64-row chunks (`ROWS_PER_LAUNCH`), two Parakeet
chunks reached 5.05-5.06 GiB. `run --recalibrate` runs a `ceiling-recalibration` session over a
full-cohort manifest. It runs twice, like qualification, but every judge, calibrated ones included,
runs under the measurement ceiling (`recalibration-measurement-budget`), and no flip analysis is
made. Each judge gets a ceiling record (`vocello.audioqc.qc-ceiling/1`) with the canary record's
identity, both runs' resources and the determinism class. Its take rows are kept as a count and a
digest, so a record stays under 256 KB. `publish` copies every judge's record, passed or not.
`recalibrate` changes only `resources`, and only for a shadow-or-later judge whose record measured
the output identity its canary cites:

- `canonicalHostPeakBytes` becomes the larger clean-run peak;
- `ceilingBytes` becomes that peak x 1.2;
- `ceilingSession` becomes the new session;
- `ceilingHistory` gains the replaced ceiling, with its session and date.

It refuses an unclean or off-host run, a candidate, another identity, and a ceiling that the
admission budget less the orchestrator reservation cannot hold. It also refuses a lower ceiling
unless `--allow-lower` is given. The registry then requires a recalibrated ceiling to be its
committed ceiling record's, with the history starting at the canary session. Legacy judges
(whisper-small, SenseVoice Q8) are measured but never edited; their provisional ceilings are
changed by hand. With every judge reserving the measurement ceiling, workers run one at a time. The
791-take panel's worker time (about 85 minutes), plus chunk reloads, puts each run at about
1.5-2 hours, so a session takes 3-4 hours.

```sh
python3 scripts/audio_qc_orchestrator.py manifest \
  --from-calibration-takes build/artifacts/macos/audio-qc/<qc-takes run>/takes-manifest.json \
  --output build/artifacts/macos/audio-qc/<qc-takes run>/panel-manifest.json
python3 scripts/audio_qc_panel_qualification.py plan --recalibrate \
  --manifest build/artifacts/macos/audio-qc/<qc-takes run>/panel-manifest.json \
  --judge-config asr.whisper-small@1=build/cache/delivery-analysis/whisper-small-mlx.json
python3 scripts/audio_qc_panel_qualification.py run --recalibrate <the same arguments>
python3 scripts/audio_qc_panel_qualification.py publish build/artifacts/diagnostics/audio-qc-panel-qualification/<session>
# review, commit benchmarks/audio-qc-qualification/<session>/, then:
python3 scripts/audio_qc_panel_qualification.py recalibrate benchmarks/audio-qc-qualification/<session> --dry-run
python3 scripts/audio_qc_panel_qualification.py recalibrate benchmarks/audio-qc-qualification/<session>
```

### Natural calibration takes (AQ-07 N3, 2026-09-27)

Population N3 is natural Vocello takes over one split of the CC0 script pool
(`config/audio-qc-script-pool.json`). `config/audio-qc-calibration-takes.json` fixes the take
plan. Each language has three voices per split: two Built-in speakers, a male and a female with
the native speaker where one exists, and one Voice Design brief. The calibration split uses the
corpus's calm narrator and the confirmation split a contrasting brief, and no speaker serves both
splits in any language (§5.5 step 1; policy version 2, below). Takes use the Speed variant, the
expressive variation and Auto language per text. Since policy version 2 they also carry the apps'
default delivery (`generation.delivery: app-default`; the lane passes `vocello batch
--app-delivery`): Custom and Design send the Neutral preset instruction that a new Studio draft
sends. The 2026-09-27 cohort was generated uninstructed, which the Neutral preset exists to avoid
(sending nothing measured 2.70 st of cross-seed pitch wander, `EmotionPreset.neutralPresetInstruction`), so its Design and Custom figures overstate
what the apps produce.

Each script gets one primary voice, rotating over the three voices. A stratified donor subset of
20 scripts per language also gets the next voice, which gives same-script, different-voice pairs
for class E constructions. `vocello batch --seed` applies one seed to a whole batch, so the seed
belongs to one (split, language, mode, voice) batch, derived by SHA-256 like the language
benchmark's seed identity. A family is still script × voice × seed. The calibration split plans
800 takes: 10 languages × (60 + 20).

`scripts/audio_qc_calibration_takes.py` works in four steps:

- `plan` writes an immutable plan bound to the pool and policy digests.
- `batch-files` writes one line file per batch.
- `manifest` binds each batch's `--json` output to the plan by item index, checking each item's
  text. It moves every WAV to `wav/<takeID>.wav`. A take the engine's mandatory Fast QC refused is
  `rejected`, with the flag families the engine recorded (from the run's collected engine
  diagnostics, by generation id); another engine failure is `failed` with its code; a planned take
  with no output is `missing` with its reason.
- `validate-manifest` recomputes the digests and checks the manifest against the plan.

The consent-bound lane `scripts/macos_test.sh qc-takes [--split calibration|confirmation]
[--languages a,b] [--cells …] [--label L]` runs these steps around one `vocello batch` per batch on
a quiet host. The artifacts go to `build/artifacts/macos/audio-qc/qc-takes-<run>/` and stay untracked.
`vocello batch` stops at its first failed item, so the lane resumes the batch after that item in a
new segment (`<batchID>@<offset>`, `next-offset`): the seed is the batch's, and each item's sampling
depends only on the seed and its text. A rejected take is an outcome that N3 flag rates must count
(`audio_qc_calibration_set.py score` counts it as a v8 fail without audio); any failed or missing
take fails the lane. The lane publishes nothing and writes no benchmark history. `audio_qc_orchestrator.py manifest --from-calibration-takes` turns the
takes manifest, an injection-set manifest or an N1 cohort manifest into a language-lane manifest for
the panel judges; it skips and counts missing takes and ineligible N1 recordings.

### Take plan version 2: clone, cross-lingual and long-form cells (2026-09-30)

The maintainer hears three defects the version 1 plan could not measure: erratic pitch in Voice
Clone takes, seams in long-form projects, and English-accented French from Built-in and Voice
Design voices. Version 2 of `config/audio-qc-calibration-takes.json` groups the takes in cells, one
per generation path; `plan --cells` (and the lane's `--cells`) picks them, `standard` by default.

| Cell | Per split | What it measures |
|---|---|---|
| `standard` | 800 takes, 30 batches | The version 1 layout and seed identity. |
| `clone` | 800 takes, 160 batches | Voice Clone on human reference clips: per language 60 scripts by 12 primary references (same-language where a speaker corpus covers the language, cross-language for Japanese and Russian) and 20 by 4 cross-language references. |
| `cross-lingual` | 800 takes, 69 or 39 batches | Every Built-in speaker of the split that the standard cell does not pair with the language, the split's brief translated into the language, and two English briefs; 60 scripts plus 20 donors per language. |
| `long-form` | 80 projects, 30 batches | 8 projects per language, pool scripts joined above the planner's 300-unit limit (330 to 480 units, about 30 to 110 s), spoken by the standard voices. |

Every take records its `cell` and `voiceLanguage` (a Built-in speaker's native language from the
speaker contract, a brief's language, a reference's language) beside its target `language`, so a
French take by an English brief or an English-native speaker is one filter away. Long-form takes are
the n3-long-form cohort, so a plan holds them alone. Each cell keeps at least 60 families per
language per split (80 planned; long-form pools 80 over ten languages).

- **Speakers.** The qualification driver refuses two cohorts that share a speaker in any language
  (`check_cohort_disjointness` over voice keys), which version 1 broke: vivian and serena spoke
  calibration in some languages and confirmation in others. `speakerPartition` gives each Built-in
  speaker to one split. Calibration keeps the six speakers of the 2026-09-27 cohort (its batches are
  unchanged); confirmation, never generated, now pairs ryan, dylan and eric, all male, so its brief
  became female and its female voices are that brief, the cross-lingual briefs and clone references.
  A brief and its translations belong to one split.
- **Clone references.** `plan` reads the extracted speaker corpora (`audio_qc_corpora.py
  extract`: LibriTTS-R, Multilingual LibriSpeech, Emozionalmente, the AISHELL-3 subset and
  Zeroth-Korean; CREMA-D carries no transcript). A clip is eligible with a speaker, a one-line
  transcript, 5 to 30 s of audio and a neutral emotion where the corpus labels one; each speaker's
  reference is its lowest-hash clip, among the clips of at least 10 s when it has any. Speakers are
  split by a hash over their whole source, alternate female and male where labelled, and serve one
  reference per split. `batch-files` copies each reference to `references/<key>.wav` and verifies
  its digest; the lane passes it with its transcript and `--confirm-consent`, and each clone take
  records `reference` (path relative to the manifest, digest, corpus, speaker), which the
  orchestrator hands to the speaker judges.
- **Long-form.** `vocello batch --long-form` (`Sources/VocelloCLI/BatchCommand.swift`) runs each
  line the way the apps' long-form runner does: `SpokenTextPlanner` and `LongFormPlanner` at the
  shipping token limit (`--seed` is the base seed, each segment samples its subseed), one streaming
  take per segment at the app cadence, `BoundedLongFormAssembler` for the join. Its JSON adds each
  project's segment takes and `LongFormAssemblyEvidence`. `manifest` refuses evidence whose output
  digest is not the take's WAV, records the `longForm` block and `longFormSegments`, and binds each
  segment's introspection by its WAV digest (the joined WAV has no engine row).
- **Engine rows.** The engine front-trims each diagnostics log at 8 MB (about 300 rows), so the
  2026-09-27 run bound only 251 of its 791 takes' introspection. The lane now marks the rows present
  before it starts (`collect-diagnostics --baseline`), copies each segment's new rows, reduced to
  generation id, WAV digest, Fast QC flag names, failure code and introspection numbers, into
  `diagnostics/` after every `vocello batch`, raises the cap with the registered
  bounded-observability knob `QWENVOICE_DIAGNOSTICS_MAX_MB=64`, and binds the manifest against its
  own copy. `verdict.txt` reports the bound count.
- **The 2026-09-27 cohort** still validates and shares no speaker with the new confirmation split.
  It was planned from script pool version 1, whose ids are ranks: 176 of its 600 script ids name
  confirmation scripts of the current pool, although only 7 of its texts moved split. The driver
  compares script ids, so pair it with a new confirmation cohort only through its texts
  ([language-bench.md](language-bench.md), "Versions and cohorts"), or regenerate the standard
  calibration cell (about 19 minutes).

How the lead runs it. The clone cell first needs the speaker corpora (maintainer-run, network); a
dry `plan` shows the allocation without a model. The lanes are consent-bound and run one at a time
(each builds the CLI, so the `--long-form` change is compiled in):

```sh
python3 scripts/audio_qc_corpora.py fetch --group speaker && python3 scripts/audio_qc_corpora.py extract --group speaker
python3 scripts/audio_qc_calibration_takes.py plan --split calibration --cells standard,clone,cross-lingual \
  --run-id dry-run --output build/artifacts/macos/audio-qc/plan-dry-run.json
scripts/macos_test.sh qc-takes --split calibration --cells standard,clone,cross-lingual --label aq07-calibration-v2
scripts/macos_test.sh qc-takes --split calibration --cells long-form --label aq07-long-form-calibration-v2
scripts/macos_test.sh qc-takes --split confirmation --cells standard,clone,cross-lingual --label aq07-confirmation-v2
scripts/macos_test.sh qc-takes --split confirmation --cells long-form --label aq07-long-form-confirmation-v2
```

To keep the 2026-09-27 cohort as the standard calibration data instead, drop `standard` from the
first calibration run.

Time. The 2026-09-27 run spent 0.27 s of batch wall time per second of audio (1,131 s for 4,151 s
over 39 invocations, model loads included; 19 minutes end to end). Per split, from the plans'
conservative token estimates at that run's seconds per unit: standard and cross-lingual about
4,100 s of audio each (about 19 minutes each), clone about 4,100 s over 160 model loads (reference
prefill unmeasured: 30 to 40 minutes), long-form about 5,650 s of streaming segments (unmeasured:
25 to 35 minutes). About 1 hour 45 minutes per split, 3.5 hours for both.

The detector registry now describes these cells as they are (2026-09-30):

- `n3-clone-takes`: the clone cell's takes are negatives, erratic ones included, since N3 carries no
  labels.
- `n3-long-form-cell`: class J's cohorts are the long-form cell, and role set `n3-long-form` names
  them.
- `introspection-rows-kept`: the lane keeps its diagnostics rows, and a take without its row abstains.
- `long-form-block`: the manifest records each long-form take's assembly as its `longForm` block.

These entries replace `n3-no-clone-takes`, `long-form-takes-pending`, `introspection-not-carried` and
`long-form-evidence-not-carried`.

### Codec resynthesis (N2, audit P9)

Population N2 is N1 resynthesized through the Qwen3-TTS speech tokenizer at all 16 codebooks. A2
confirms a fail bound's false-alarm rate on it: the recordings stay human, and the audio now carries
the codec every take is decoded through. Every production artifact shares one tokenizer (catalog
`speech_tokenizer/model.safetensors`), but only the Base (Voice Cloning) model loads its encoder, so
the round trip runs on the installed Voice Cloning Speed model.

The facade's `VocelloQwen3Engine.codecRoundTrip(samples:memory:)` runs under an operation lease. It
takes mono 24 kHz Float PCM of at most 60 s. It builds the clone path's encoder input, with the
0.5 s trailing silence (`encoderInputWithTrailingSilence`), and keeps every codebook. It decodes the
codes on the production non-streaming 25-frame schedule and sample window of the replay's
`fullAudio`. A model without an encoder fails with `speechTokenizerEncoderUnavailable`.

- **Trim.** The decode covers the input plus the silence, so it is cut to the input's sample count.
  An N2 file is exactly as long as its 24 kHz input.
- **Output.** Each file is plain PCM16 (x 32767, clamped to ±1, with the clamps counted), without
  the production output limiter. QC's limiter pass measures clicks and the ceiling on an engine's
  raw output, so N2 must stand where that output stands, as N1 does. A pre-limited file would hide
  the very events whose FAR N2 bounds. The replay's WAVs, by contrast, do pass the limiter.

`scripts/audio_qc_n2_resynthesis.py` works in three steps:

- `plan` reads an `audio-qc-n1-cohort` manifest and keeps its eligible takes. It resamples each
  from 16 kHz to 24 kHz with the `polyphase-kaiser5-v2` design of `scripts/audio_resampling.py`
  (Kaiser-5, ten zero crossings, SciPy's `resample_poly`, here up 3/down 2), quantized like L0
  (round half to even, clip). A subclass only changes the output rate, so the L0 cache identity
  (that file's digest) does not move. It writes `inputs/`, the text-free CLI job `n2-job.json` and
  the immutable `n2-plan.json`.
- `manifest` binds the CLI result into `n2-manifest.json` (kind `audio-qc-n2-cohort`). Each take
  keeps its N1 `family`, `scriptID`, language and text, and adds `population: "N2"`, its
  `n1TakeID` and the resynthesis `wavPath`/`wavSHA256`. It also binds the codec identity: the
  tokenizer SHA-256, the model id and revision, and the codes SHA-256.
- `validate-manifest` recomputes every digest and checks the plan binding.

The CLI branch is `vocello bench --codec-roundtrip <n2-job.json> --output-dir <new directory>`.
It needs an internal-diagnostics build (`build.sh cli` and `cli-optimized` both define
`VOCELLO_INTERNAL_DIAGNOSTICS`; the lane builds `cli-optimized`) and `QWENVOICE_DEBUG=1`.

1. It verifies every input's digest and format before loading anything, then binds the model to
   the pinned catalog bytes, as the codec replay does.
2. It creates the output directory exclusively, then runs the whole job on one model load.
3. It writes `<id>.wav` and `<id>.codes.bin` (the codec-trace v1 binary the replay reads) for each
   item, plus `codec-roundtrip-result.json` (per-item status and digests, no text).
4. It unloads the model.

The consent-bound lane runs the three steps around one CLI run on a quiet host:

```sh
scripts/macos_test.sh qc-n2 --n1-manifest <n1-cohort-manifest.json> [--label L]
```

Its artifacts go to `build/artifacts/macos/audio-qc/qc-n2-<run>/` and stay untracked. It publishes
nothing and writes no benchmark history.

### Detector qualification at warn (AQ-07, 2026-09-29)

**Registry.** `config/audio-qc-detectors.json` declares each detector as `id@version`: class and
stage; its score, read from a Fast QC v8 or Stage 0 field of `measurements.json`, from panel judge
metrics, or from a judge's private transcript aligned against the reference; the combination
(`single`; `consensus-min`, direction above, and `consensus-max`, direction below, over two
independent voting families per language, so both must alarm; `consensus-mean` over the same pairs,
since 2026-09-30, so their joint evidence alarms; or `difference`); its strata; its
language scope with a declared reason per exclusion; the injectors and severities its detection
rate is measured on with their matched shams; and its population roles. The contract gate's
`audio_qc_detector_calibration.py validate` checks it against `config/audio-qc-judges.json`: a
consensus family must vote, be of another family than its partner, not share the generator's lab
(Qwen3-ASR and the aligner never vote, A6), and cover the group's languages; the aligner may only
time a `difference` whose group requires both content voters to have completed. A plan binds the
entry's digest, so any change needs a new version (A7). The v1 set:

| Detector | Class | Score | Direction |
|---|---|---|---|
| `signal.clicks@1` | A | Fast QC `clickEventsPerSecond` | above |
| `signal.dropout@1` | A | Fast QC `longestSilenceMS` (interior) | above |
| `signal.terminal-silence@1` | A | Fast QC `trailingSilenceMS` | above |
| `signal.dc-offset@1` | A | \|Fast QC `dcOffset`\| | above |
| `signal.level@1` | A | Fast QC `rmsDBFS` | below |
| `signal.clipping@1` | A | Fast QC `hotSamples` (above 0.965; blind below it) | above |
| `signal.noise@1` | A | Stage 0 `wadaSNRDB` | below |
| `signal.band-limit@1` | A | Stage 0 `effectiveBandwidthHz` (SIG-BAND since catalog v3) | below |
| `content.consensus-error@1` | B | min of Whisper large-v3 and Parakeet (zh Paraformer, ja/ko SenseVoice) `errorRate` | above |
| `boundary.truncation@1` | C | min of the same pairs' trailing unmatched fraction | above |
| `boundary.run-on@1` | C | Whisper last segment end minus the aligner's script end (not ko) | above |
| `language.consensus-lid@1` | D | max of Whisper's expected-language probability and VoxLingua's posterior | below |

Truncation compares each private transcript with its reference on `language_metrics`' primary units
and edit costs and counts the reference units after the last matched one, anchored as early as any
minimum-cost alignment that matches a unit allows (the whole script when none does). The definition
is over the set of optimal alignments, not a backtrace, so a truncated take whose last heard word
recurs later in the script is not pinned to the later occurrence ("the cat sat on the" against a
nine-word script scores 4/9, not 1/9), while a complete take scores 0. It resolves ties only: a
spurious late word that matches a later script unit (a hallucination at the end of the audio)
lowers the cost and still anchors the tail there. Only the fraction leaves the bundle. Run-on subtracts the aligner's script end from Whisper's last segment end because neither
works against the file end on FLEURS: Whisper's end follows the speech, so an inserted run-on leaves
duration minus it unchanged, and the aligner's tail gap carries the natural trailing silence (clean
N2 95th percentile 3.8 s, against 0.7 s for the difference). Every v1 detector declares per-language
strata: on the calibration cohort a pooled threshold already puts 27% of clean English above the
run-on bound, 20% of German below the language bound and 13% of Japanese above the content bound,
where warn allows 20% per language. The registry records the declared risks (SenseVoice's codec
degradation in ja and ko, VoxLingua's weakness in de and ru, Parakeet's Whisper label lineage).

**Classes E, F, I and J (registered @1, not yet planned).** The next classes of audit section 5.7
are registered at warn. None has a plan yet, and the entries' `limitations` and `risks` say what each
still lacks. An entry can still change in place until a plan binds its digest. Catalog version 3
builds every T1 construction these detectors name (IDN-IMPOSTOR, the recorded IDN-SWAP splice,
IDN-ONSET, PRS-ERRATIC, SEAM-DISC, SEAM-VOICE). Take plan version 2 adds the clone and long-form cells,
and the qc-takes lane keeps its diagnostics rows. The last column is the state on 2026-09-30.

| Detector | Class | Score | Direction | Still needs |
|---|---|---|---|---|
| `identity.clone-similarity@1` | E | CAM++ `cosine` of the take to its same-speaker reference clip | below | The speaker-labelled N2 corpus (a maintainer decision: role set `speaker-labeled-n2` is pending) and reference clips in the panel manifest |
| `identity.window-drift@1` | E | CAM++ `cosine` minus its lowest 2 s window cosine | above | The same corpus |
| `identity.onset-drift@1` | E | CAM++ `cosine` minus its first 2 s window cosine | above | The same corpus; the pYIN register and envelope parts of the joint onset rule |
| `prosody.pitch-break@1` | F | Largest F0 change between pYIN voiced frames at most 50 ms apart (semitones) | above | pYIN on both FLEURS reserve panels, its frame track exported per take; pYIN's oracle ladder recorded |
| `prosody.octave-jump@1` | F | Longest run of voiced frames 9 semitones or more from the take's median F0 (seconds) | above | As pitch-break |
| `prosody.pitch-instability@1` | F | pYIN jumps per voiced second: F0 changes faster than 150 semitones per second between voiced frames at most 50 ms apart | above | pYIN and its frame track on both N3 splits of take plan version 2 (standard, clone and cross-lingual cells) |
| `introspection.token-loop@1` | I | Span of the longest exact codebook-0 cycle of period 2-32, in codec frames (0 without one) | above | COD-LOOP (T2): a mutation-recipe replay mode for the codec trace |
| `introspection.high-entropy@1` | I | Longest run of steps with at least 4 nats of talker entropy | above | GEN-NOEOS (T3), a registered EOS-suppression knob |
| `introspection.eos-overrun@1` | I | Steps with EOS probability 0.5 or more that did not stop | above | As high-entropy |
| `long-form.seam-discontinuity@1` | J | Stage 0 `seamDiscontinuityMaxZ` | above | The long-form cell's takes of both splits (the calibration set reads their seams from the `longForm` block) |
| `long-form.seam-jump@1` | J | The assembler's `maximumSegmentBoundaryJump` (PCM16 units) | above | As seam-discontinuity; a SEAM-DISC clip is measured at the seams its entry records |
| `long-form.seam-identity@1` | J | Lowest CAM++ cosine between the 2 s windows either side of a seam | below | SEAM-VOICE positives, which natural long-form takes cannot build (no procedural script, no speaker label); CAM++ windows exported with the seam times |

Class E reads CAM++ alone: ResNet293 votes only after its correlated-failure audit, and the
two-family rule is a new version then. A panel judge whose registry entry lists no languages
(the speaker families, pYIN) runs on every take, so the validator counts it as covering every
language. Its role set `speaker-labeled-n2` names pending corpora: FLEURS has no speaker ids, so
the fit and confirmation cohorts wait for a maintainer decision on a speaker-labeled corpus whose
terms allow speaker verification (not Common Voice), with two or more utterances per speaker,
resynthesized to N2. Each language stratum needs 60 scored calibration families and 60
confirmation negative families from at least 3 speakers, disjoint by family, speaker and script,
plus 60 families per severe cell and per sham. Once the role set names the corpus instead of
`pending-...`, `plan` reads its split, corpus name and speaker labels from the N1 manifest each N2
cohort pins (`--calibration-n1-manifest`, `--confirmation-n1-manifest`) and checks speaker
disjointness beside family and script. Both cohorts name one corpus (speakers are digests of corpus
and label, so two corpora would compare nothing), and the role set names it `<corpus>-calibration`
and `<corpus>-confirmation`. A take (or an impostor positive) names its reference clip
(`reference`: WAV path and digest); `audio_qc_orchestrator.py manifest --from-calibration-takes`
passes it to the speaker judges, the take's private record names its digest, and `scores` refuses
evidence measured against another clip than the declared one.

Class F reads a new source, `raw-output`: `detectors.py` reduces a panel judge's raw (L1) output,
which the bundle does not keep, and `score_take(..., raw={judge: output})` takes it once the judge's
measurement completed. pYIN's HMM caps a transition at 4.3 semitones per 10 ms frame, so the step
measure compares voiced frames up to 50 ms apart. pYIN does not vote, but as a DSP instrument with
no learned weights its raw output may score a `single` detector alone if it is not from the
generator's lab and is at least shadow; its L2 metrics through a `panel` component still may not.
Class F fits on an N2 calibration cohort, now the FLEURS reserve's (`fleurs-reserve-n2`: the v1
confirmation cohort already holds bundles, so `plan` refuses it, A5), and PRS-BRK and PRS-OCT
already run on N2 with the aligner's intervals (not in Korean). A plan still needs pYIN on both
panels and its frame track exported per take (`audio_qc_calibration_set.py raw-outputs --judge
pitch.pyin@1`, rebuilt from the panel's own cache root, `--cache-root` required, like `alignments`,
and passed to `scores --raw-outputs`; a take whose entry the cache no longer holds is an evidence
gap). The pitch-instability detector answers
the maintainer's report of Voice Clone takes whose pitch is all over the place: a take-level rate
of jumps no voice makes (about twice the fastest F0 change a speaker produces), so expressive
intonation that glides stays a negative. It therefore fits and confirms on natural takes (role set
`n3-takes`, FLEURS read speech informational) and a construction that shifts many short spans
(PRS-ERRATIC, catalog version 3); take plan version 2's clone cell brings Voice Clone takes into both
splits, as negatives (`n3-clone-takes`). Window drift is the identity half of the
same complaint. Creak is not registered: catalog v2 has no
creak construction (the audit builds one with WORLD, which the catalog lacks), and no voice-quality
measure has passed its oracle ladder.

Class I reads a third new source, `introspection`: a clip's `introspection` block in
measurements.json, the engine's Stage 0 summary (the same fields as
`audio_qc_observations.introspection_summary`). A summary without an exact cycle scores a loop of 0
frames, not an abstention. The talker runs only in natural takes (a codec round trip samples no
token), so class I fits and confirms on the N3 splits of the take plan: at least 60 scored families
per language in each (the calibration split plans 80), which `plan` checks disjoint by family,
speaker (a Built-in speaker or a Voice Design brief) and script. Its role sets `n3-codec-trace` (P2)
and `n3-controlled-generation` (P3) name declared constructions: `scores` reads P2 and P3 entries
with their provenance (T2 trace, recipe and decoder digests; T3 knob and recipe) and builds none,
and `plan` binds the construction catalog version the lead declares (`--injection-catalog-version`;
a second tier beside the role set's, such as a fail point's T2 next to T1, `--tier-catalog-version
T2=N`, checked against each tier's entries).
`audio_qc_calibration_takes.py manifest --diagnostics` binds each take to the engine row whose
`samplingWAVDigest` is its WAV digest and carries that row's `engineIntrospection`, and `score`
copies it into each clip (a T2 or T3 entry carries its own; a T1 construction none), refusing a
summary bound to another WAV than the clip's. The engine front-trims its diagnostics log at its cap,
so the qc-takes lane keeps its rows: it raises the cap to 64 MB, copies each batch's new rows and
binds the manifest against its copy (`introspection-rows-kept`). A take without its row abstains.

Class J reads the Stage 0 seam z-score, a fourth new source, `longform` (a clip's `longForm` block:
the long-form assembly evidence), and the `raw-output` seam measure, which also takes the take's
seam times (`score_take(..., seams=[...])`, abstaining `no-seams` without one). Its role set
`n3-long-form` names the take plan's long-form cell: 80 projects per split (one pooled threshold,
the warn floor 60, over at least 3 languages, speakers and scripts), each with at least one seam. A
long-form take carries a `longForm` block (`audio_qc_calibration_takes.long_form_block`: the
assembled frame count, the assembler's boundary jump and each seam's output frame); `score` passes
its seams to the Stage 0 seam z-score and measures each clip's jump on its own PCM (a clean take's
must equal the assembler's; a T1 construction that keeps the length keeps the seams; a SEAM-DISC
clip, which removed samples after a seam, is described at the seams its entry records), and `scores`
passes the seams to the seam-identity measure with the exported CAM++ windows. A single-segment
take's `seamDiscontinuityMaxZ` stays null. SEAM-VOICE needs a procedural script or a speaker label,
which natural long-form takes lack, so seam-identity has no positives on the long-form cell
(`seam-constructions`). Seam-identity uses `raw-output` from class F, so its commit comes after F's.

**Plan, derive, confirm.** FLEURS dev (N2 calibration) fits and FLEURS test (N2 confirmation)
confirms; they are disjoint by family and script (checked on the ids at plan and confirm time). A
plan declares its cohorts (`CohortSplit`: both manifests by kind and digest, `disjointBy`, the
limitations) instead of a hash salt; the component-hash plans' digests are unchanged. FLEURS
publishes no speaker ids, so units carry the speaker `<language>:fleurs-unidentified`, a lower
bound: warn's three speakers are met only by covering three languages, and the record says so.
`scores` writes per-unit scores (ids, digests, components, abstentions; no text or path) under
`build/`, with the digest of the scoring code (`detectors.py`, `language_metrics.py` and its
normalization data) and the evidence identity: the bundles' orchestrator source digest, each consumed
judge's L2 metric definition and sources digest (the header's `judgeMetrics`), and the metric
versions the panel records (`accuracyMetricVersion`, `textNormalization`).

*Evidence is bound to the cohort.* A cohort manifest must match its own `manifestDigest`. A panel
bundle must match its `bundleDigest`, and every evidence record must carry its take's audio digest
(the cohort's or the injection entry's `wavSHA256`), text digest and language; a private reference
text must be the manifest's. `measurements.json` must match its `clipsSHA256`, name the cohort
manifest (`takesManifestSHA256`) and, for positives, the injection set (`entriesSHA256`), and each
clip must carry its take's audio digest. An injection set must match its `entriesSHA256` and name
the cohort manifest it was built on; that check never skips. Positives are the injection set's
entries, so `--positive-bundle` and `--positive-measurements` need `--injection-set`. An in-scope
unit whose evidence is absent abstains as `no-evidence` (a consumed judge not run on it, as
`not-measured`); one whose consumed judge's row failed (`unavailable`: an admission or row timeout,
a crash, an envelope breach) abstains as `judge-unavailable`, the run's failure rather than the
detector's. The driver checks each T1 entry's own catalog version, but not that the set is complete
(every sampled family and scheduled variant present): run `audio_qc_calibration_set.py verify` on
the confirmation set before scoring it.

*A5 is enforced, not a convention.* An N2 cohort names its split through the N1 manifest it
pins by `n1ManifestSHA256` (`scores --n1-manifest`, `plan --confirmation-n1-manifest`); an N3 takes
manifest names its take-plan split. The calibration and informational roles refuse every
confirmation split (FLEURS test, the confirmation take split, a labelled corpus's confirmation
split), whatever the detector's role set, and any cohort a plan in the store names as confirmation
or N3 bound; a plan refuses a confirmation cohort that is not its role set's split, a cohort already
scored as confirmation evidence (the confirmation or N3 cohort of a confirmed plan, or a record's
informational N3 cohort, which the record pins), a calibration
cohort another plan confirms on and a confirmation cohort another plan fits on. The plan also binds
the confirmation-side construction: the injection set's catalog seed, sample seed, sample per cell
and classes (`--injection-catalog-seed`, `--injection-sample-seed`, `--injection-sample-per-cell`,
`--injection-classes`) and the injector catalog version. `confirm` (and `scores --role
confirmation`, earlier) refuses an injection set built otherwise. Every confirmation panel bundle,
the cohort's and the positives', must be computed from scratch after the plan was committed. Its
`startedAt` must be later than the last commit touching the plan file (so the plan lands on main,
never amended, rebased or cherry-picked afterwards, before any panel runs), it must have started on an
empty cache root (`cacheRootEmptyAtStart`), and it must show no L1 hit and no adoption. So each
confirmation panel runs with its own new, empty `--cache-root`. L2 hits inside such a run are its
own: identical audio under one request (an identity sham of two injectors, a language swap's donor)
shares one L1 row and is reduced once. The orchestrator stamps both fields in the bundle header
only, outside any judge's identity. The directory scan at `plan` stays as a convenience. Stage 0
`measurements.json` stamps its own `startedAt` (outside `clipsSHA256`), held to the same rule.

*A7 covers what shapes a score.* The plan binds the scoring-code digest and the digest of the
calibration evidence identity; `confirm` requires both cohorts' judge output identities, scoring
code and evidence identity to be equal and to match the plan. An orchestrator, metric-reduction or
metric-version change between the panels, or any edit to `detectors.py` or `language_metrics.py`
after the plan, therefore refuses the confirmation. Since the confirmation panels run the current
code, `plan` refuses calibration evidence the current code would not reproduce (another
orchestrator, reduction or metric version), so no plan is dead on arrival. Write the calibration
bundle again with the current orchestrator first (its L1 entries may be reused), and freeze the
orchestrator, the panel's metric sources, `detectors.py` and `language_metrics.py` from the
calibration panel to the confirmation.

`plan` writes `config/audio-qc-preregistrations/<id>.json` (split-conformal, alpha below the warn
FAR bound, bindings to the definition, the calibration scores, the policy, the scoring code, the
evidence identity and the injection construction). It refuses calibration scores with missing
evidence or with fewer than `warn.minimumUnits.calibration` (60) scored families in any stratum,
and a confirmation cohort that already holds a panel bundle, measurements or scores. `derive`
returns one split-conformal threshold per stratum from clean calibration families, none for a
stratum below that floor, and refuses a plan not committed at HEAD. `confirm` runs once per plan
digest. Before anything is recorded it checks the bindings, the identities above, the construction,
the panels' freshness, the declared split, and that every expected unit is present with its
evidence and no failed judge row (rerun that panel on a new cache root). The warn minimum units are
counted on scored units only: 60 negative families, 3 languages,
speakers and scripts, 60 families per severe cell, and a sham cell per injector with 60 families.
So a detector that (nearly) always abstains refuses to start instead of recording a refusal. Its
`--n3-scores` must be the same detector's informational N3 scores under the same definition,
scoring code and judge identities. Then `evaluate_confirmation` at warn tests each injector's sham
alone (A4), so one injector's sham never stands in for another's. A sham cell whose every clip is
clean cohort audio (LNG-SWAP's same-language donor, or an identity sham whose output PCM is its
source's) cannot depart from the negatives; it is kept and recorded as uninformative (`a4`,
`rates.shams.<injector>.informative`). The ledger entry is written beside the plan with the tracked
record `benchmarks/audio-qc-calibration/<id>/record-<plan digest 16>.json`: digests, the evidence
block, counts, rates with Clopper-Pearson bounds, thresholds, scope, limitations, the phi audit of
each consensus pair and the verdict. `validate` ties every record to its plan and ledger entry. It
fails a plan or record whose registry entry changed in place without a version bump, a ledger
entry without its record, and any plan, ledger entry or record that a later commit deleted,
modified or renamed: they are written once, so an unconfirmed plan cannot be dropped to plan the
same confirmation cohort again.

*Fail* (decision 5, operating point `fail` or the evidence-lane-only `evidenceLaneFail`). A fail
plan is its own plan beside the warn plan of the same version (`<id>.fail.json`; warn plans keep
their names) and is confirmed once on its own. `plan --operating-point fail --alpha A --n3-cohort
MANIFEST` refuses a definition that cannot qualify: FAR confirmed on another population than N2
(the N3 role sets of classes I and J, A2), fewer than ten languages in scope, or fewer than two
construction mechanisms declaring severe and moderate cells (A3), which no v1 detector declares
yet, so a fail plan needs a new detector version first. Alpha lies below 0.01, the calibration
cohort meets the confirmation's N2 floor per stratum (1,240 pooled, 124 per language), and the plan
binds the N3 cohort its flag rate is bounded on (`n3CohortDigest`), which must hold no scores,
bundle or measurements yet and no confirmation may have scored; a fail detector whose second
mechanism is another tier binds that tier's catalog (`--tier-catalog-version T2=N`). That cohort is scored after the plan under `scores --role bound
--operating-point fail` (fresh panels and measurements, like a confirmation); `confirm
--operating-point fail --n3-scores` requires it complete, then 1,240 N2 families (124 in each of ten
languages), 60 families per severe and moderate cell of each mechanism and per sham, and 60 N3
families per language, and evaluates the fail point: FAR <= 1% pooled and <= 5% per language, the
N3 flag rate <= 5%, detection >= 0.90 severe and >= 0.70 moderate on two mechanisms, clean
abstention <= 5% and the shams. Positives of a second tier (T2 P2 beside T1 P1) are read when the
detector declares that mechanism. The record's `level` is `fail`, it pins the N3 cohort and
scores (`cohorts.n3`) and carries the bound (`rates.n3`), and the lane gates accept it for fail and
warn gates (an `evidenceLaneFail` record never backs a product lane). The policy's
`physicalEventsT1Only` exception (clipping, DC, digital silence and non-finite samples may qualify on
T1 alone) is not wired: it needs the registry to mark those detectors, a new version of each.

The lead's sequence (all 11 plans before any confirmation panel or score, since a plan refuses a
scored confirmation cohort). `signal.band-limit@1` gets no plan: without an injector its
confirmation cannot start, and a write-once plan would bind this cohort for good. It waits for a
new confirmation cohort (catalog version 3 adds SIG-BAND). The confirmation panels run the
six judges the detectors read (Whisper large-v3, Parakeet, Paraformer, SenseVoice, VoxLingua and
the aligner) rather than the whole panel:

```sh
CAL=build/artifacts/macos/audio-qc/qc-n2-mac-qc-n2-20260929-082348-92817b0c
CON=build/artifacts/macos/audio-qc/qc-n2-mac-qc-n2-20260929-163642-8035d59e
OUT=build/artifacts/macos/audio-qc/detector-scores
N1CAL=<N1 dev manifest $CAL pins>; N1CON=<N1 test manifest $CON pins>
Q="python3 scripts/audio_qc_detector_calibration.py"
# 1. Calibration scores: panel detectors from the bundle (written by the current orchestrator),
#    class A from the cohort's Stage 0 measurements (audio_qc_calibration_set.py score).
$Q scores --detector content.consensus-error@1 --role calibration --cohort $CAL/n2-manifest.json \
  --n1-manifest $N1CAL --bundle $CAL/panel-bundle-v2 --output $OUT/calibration/content.consensus-error@1.json
$Q scores --detector signal.level@1 --role calibration --cohort $CAL/n2-manifest.json --n1-manifest $N1CAL \
  --measurements <calibration measurements.json> --output $OUT/calibration/signal.level@1.json
# 2. Plans, once the confirmation manifest exists and before anything scores it; review, then commit
#    on main. The injection flags declare how the confirmation injection set will be built.
$Q plan --detector content.consensus-error@1 --calibration-cohort $CAL/n2-manifest.json \
  --confirmation-cohort $CON/n2-manifest.json --confirmation-n1-manifest $N1CON \
  --calibration-scores $OUT/calibration/content.consensus-error@1.json --alpha 0.05 \
  --injection-catalog-seed 7 --injection-sample-seed 1 --injection-sample-per-cell 150 \
  --injection-classes A,B,C,D,F
# 3. Preview the thresholds (calibration data only).
$Q derive --detector content.consensus-error@1 --calibration-scores $OUT/calibration/content.consensus-error@1.json
# 4. After the plans are committed, in this order: the cohort panel on its own new, empty cache root
#    (J = the six --judge flags); its word intervals; the injection set as planned, verified complete;
#    Stage 0 over the cohort and the set; the positives panel on another new cache root; the scores.
python3 scripts/audio_qc_orchestrator.py run --manifest <CON orchestrator manifest> $J \
  --cache-root build/cache/delivery-analysis/confirmation/cohort --bundle $CON/panel-bundle-v2
python3 scripts/audio_qc_calibration_set.py alignments --takes $CON/n2-manifest.json --bundle $CON/panel-bundle-v2 \
  --cache-root build/cache/delivery-analysis/confirmation/cohort --output <CON alignments.json>
python3 scripts/audio_qc_calibration_set.py inject --takes $CON/n2-manifest.json --output <set> \
  --alignments <CON alignments.json> --catalog-seed 7 --sample-seed 1 --sample-per-cell 150 --classes A,B,C,D,F
python3 scripts/audio_qc_calibration_set.py verify --set <set>/injection-set.json --takes $CON/n2-manifest.json \
  --alignments <CON alignments.json>
python3 scripts/audio_qc_calibration_set.py score --takes $CON/n2-manifest.json --set <set>/injection-set.json \
  --output <CON measurements>   # both --measurements and --positive-measurements of class A
python3 scripts/audio_qc_orchestrator.py manifest --from-calibration-takes <set>/injection-set.json \
  --output <set>/panel-manifest.json
python3 scripts/audio_qc_orchestrator.py run --manifest <set>/panel-manifest.json $J \
  --cache-root build/cache/delivery-analysis/confirmation/positives --bundle <set panel bundle>
$Q scores --detector content.consensus-error@1 --role confirmation --cohort $CON/n2-manifest.json \
  --n1-manifest $N1CON --bundle $CON/panel-bundle-v2 --injection-set <set>/injection-set.json \
  --positive-bundle <set panel bundle> --output $OUT/confirmation/content.consensus-error@1.json
# 5. Confirm once; commit the ledger entry and the record; summarize.
$Q confirm --detector content.consensus-error@1 \
  --calibration-scores $OUT/calibration/content.consensus-error@1.json \
  --confirmation-scores $OUT/confirmation/content.consensus-error@1.json
$Q report --scores $OUT/calibration/*.json
```

The confirmation cache roots are replay inputs until the records are committed and dead weight
after. `scripts/clean_build_caches.sh --prune-confirmation-caches --dry-run`, then without
`--dry-run`, removes each root under `build/cache/delivery-analysis/confirmation/` untouched for
24 hours (`--older-than-hours` overrides; `childRetention.analysisConfirmation` in
`config/build-output-policy.json`), only while no orchestrator, generator or analyzer holds the
host analysis lock and no process has a file open under it; the shared cache's `audio`, `layers`
and `external-models` are never touched. Prune only after the records are committed: the
`alignments` and `raw-outputs` exports hold the lock shared (a prune refuses mid-export), and they
refuse a root without analysis layers or any complete measurement without its L1 entry, so an
early prune fails loudly instead of exporting around the gap.

**Injections on N2 (AQ-07 positives).** `scripts/audio_qc_calibration_set.py` reads an N2 cohort as
an injection source: every take is an eligible, generated 24 kHz resynthesis whose family is its N1
recording. Four additions serve warn-level qualification:

- **Sampling.** Injecting every variant into every recording would write about 80 GB, so `inject
  --sample-per-cell N --sample-seed S` draws N source families per injector. The draw is stratified
  by language as evenly as the eligible pool allows, by a seeded SHA-256 rank, and recorded in the
  set; `verify` redraws it. The injector's sham and every severity share the same families. N2
  defaults to 150 per cell (N1 and N3 keep every source). At 150 on the 1,888-take calibration
  cohort that is 9,300 clips from 1,369 source takes: 15 T1 injectors x 4 variants x 150, plus 300
  language swaps. They take about 5.2 GB of WAV, 0.16 GB of it the swaps' copies.
- **Word intervals.** The panel's forced aligner left its raw units and intervals in the
  orchestrator's L1 cache; the bundle keeps only reduced metrics. `alignments` rebuilds each take's
  L1 key as the orchestrator computed it. The key combines the evidence's audio and canonical
  digests, the aligner's output identity from the evidence, its registry pins, and the request of
  `panel_jobs.panel_request`. The export writes takeID -> intervals in seconds, with unit texts as
  SHA-256 only. With `inject --alignments`, `recordings.word_alignment` turns each positive-length
  interval into a 24 kHz word interval and each gap over 0.2 s into a declared pause. A zero-length
  interval is a unit the aligner squeezed at its 80 ms resolution, not a word. It refuses an
  alignment that overlaps, overruns the take by more than one frame, has fewer than 5 words, or
  squeezes more than 20% of its units. The catalog variants of CNT-DEL, CNT-REP, CNT-INS, PRS-OCT,
  PRS-BRK and BND-TRUNC's word cuts then run on the usable takes. CNT-INS's donor words come from
  the same recording, so it needs no donor voice. On the calibration cohort 1,727 of 1,888 takes
  are usable. Korean (157) is outside the aligner's scope, and 4 squeeze too many units.
- **Language swaps (class D, `T1-parallel-corpus`).** A source's FLoRes sentence (`scriptID`) is
  presented with the source's language and text. For the positive it is read by a recording in
  another language; for the sham, by another recording in the source's language. The clip is a
  byte copy of the donor's file (never a hard link, which would share the cohort's own audio), and
  its family is the donor recording's. Donors come from the same cohort
  manifest, so from the same split. `lib/qc_qualification/language_swap.py` holds the construction.
- **Speaker donors and seams (classes E and J, catalog version 3).** On a cohort whose takes name
  their `speaker` and `gender`, `inject --classes E,J` chooses donors from the same manifest as
  LNG-SWAP does (lowest seeded SHA-256 rank per injector and relation among donors not yet drawn,
  `--sample-seed`): another speaker of the source's language and gender for a positive, another
  utterance of the source speaker for a sham, a splice's donors only among takes with a usable
  alignment. Each entry records its donor (take, family, speaker, relation, WAV and PCM digests,
  alignment) and `verify` re-derives and replays it; the sample draws only sources with both donors.
  A take without a speaker label, or without both donors, is not applicable with that reason, and so
  is every identity positive on FLEURS, which has no speaker ids. Long-form takes may declare
  `seamSamples`; the seam injectors draw only from them, each entry carries its output's seams, and
  `score` passes them to the Stage 0 seam z-score.
- **Text.** N1 and N2 sets carry each entry's text (for a swap, the expected text) bound by
  `textSHA256`. N3 sets carry it only with `--embed-text`, so their bytes stay as before.
  `audio_qc_orchestrator.py manifest --from-calibration-takes` reads a set's `entries`, checks
  `entriesSHA256`, and expects `fail` for a positive and `pass` for a sham. `score` labels the
  clean recordings N2 (or N1), and it scores them alone when `--set` is omitted. Their flag rate
  bounds FAR directly, with no f / (1 - pi_max) framing.

```sh
D=build/artifacts/macos/audio-qc/qc-n2-<run>
python3 scripts/audio_qc_calibration_set.py alignments --takes $D/n2-manifest.json \
  --bundle $D/panel-bundle-v2 --output $D/alignments.json
python3 scripts/audio_qc_calibration_set.py inject --takes $D/n2-manifest.json \
  --alignments $D/alignments.json --output $D/injection-set   # A,B,C,D,F; 150 per cell
python3 scripts/audio_qc_calibration_set.py verify --set $D/injection-set/injection-set.json \
  --takes $D/n2-manifest.json --alignments $D/alignments.json
python3 scripts/audio_qc_calibration_set.py score --takes $D/n2-manifest.json \
  --set $D/injection-set/injection-set.json --output $D/injection-score
python3 scripts/audio_qc_orchestrator.py manifest \
  --from-calibration-takes $D/injection-set/injection-set.json \
  --output $D/injection-panel-manifest.json
```

### Detector v2 designs after the first warn confirmation (AQ-07, 2026-09-30)

The first warn confirmation refused `content.consensus-error@1`, `boundary.run-on@1` and
`signal.clipping@1` (A3), and the app's own takes showed that the per-language thresholds of
`signal.dc-offset@1`, `signal.dropout@1` and `signal.terminal-silence@1` encode FLEURS's per-locale
recording conditions. The successors are new registry versions; every v1 entry, plan and record stays
as it was (A7). Their designs were chosen on the spent AQ-07 data only: the calibration cohort
(FLEURS dev N2, 1,888 families), the spent confirmation cohort (FLEURS test N2, 3,718 families, with
its injection set) and the 791 N3 takes of 2026-09-27. Those cohorts are spent for pre-registration,
so every number below is design evidence: each v2 is planned and confirmed once on a fresh FLEURS
reserve cohort (`config/audio-qc-corpora.json`) under the usual A5 rules. Unless a table says
otherwise, thresholds are fitted on the dev N2 families and counted on the test N2 families, the
worst language's FAR bound is at the Bonferroni confidence 0.995, and detection counts the spent
injection set's 150 families per cell.

**PCM shape measures.** Three of the v2 scores need a quantity no Fast QC v8 field or Stage 0
observation carries. `scripts/lib/qc_qualification/pcm_measures.py` measures them over each clip's
PCM16 integers, and `audio_qc_calibration_set.py score` keeps them as the clip's `pcmMeasures` block
beside Fast QC, read by the registry's `pcm` source: sign-symmetric flat tops (runs of at least two
equal samples within 1% of the take's peak, on both polarities), exact digital silence (PCM16 zeros)
inside, after and before the take, and the end of its last active span (10 ms frames at most 35 dB
below its loud level and at least 10 dB above its floor, spans of 150 ms or more). Each block carries
the digest of the code that measured it, the detector library refuses a block measured by other code,
and the module is a scoring source, so a plan binds it (A7). A clip without the block is an evidence
gap. The measures run in Python only: the app's takes carry no such field until a Swift mirror joins
the Stage 0 observations, so these detectors serve the evidence lanes.

**Signal chain, not language (`signal.dc-offset@2`, `signal.dropout@2`,
`signal.terminal-silence@2`).** Generated audio's recording conditions do not vary by language, so
each v2 fits one threshold pooled over the ten languages, and where the v1 quantity itself followed
the recording (Fast QC's 0.001 silence floor counts a quiet room as silence) the v2 reads a quantity
that does not: exact digital silence, which room tone and codec output never reach for long. The
per-language FAR bound still applies to every language, and the pooled threshold concentrates
FLEURS's false alarms in its outlying locales, so these plans take alpha 0.01 (at 0.05 the worst
language's bound was 0.354, 0.283 and 0.265, above the 0.20 limit).

| Detector | v1 N3 flag rate (the v1 record's per-language thresholds) | v2 score | v2 at alpha 0.01: threshold; N2 FAR pooled; worst language | Detection (moderate, severe) | v2 N3 flag rate |
|---|---|---|---|---|---|
| `signal.dc-offset@2` | fr 80/80, en 78/80, ru 63/79, ko 10/78, 0-3% elsewhere | \|Fast QC `dcOffset`\|, pooled | 2.7e-3; 27/3718 (upper 0.010); de 22/560 (upper 0.066) | SIG-DC 150/150, 150/150 (mild 150/150) | 0/791 |
| `signal.dropout@2` | pt 73/77, de 10/80, fr and ja 4/80, 0-1% elsewhere | `longestInteriorDigitalSilenceMS`, pooled | 402 ms; 33/3718 (upper 0.012); zh 29/602 (upper 0.075) | SIG-DROP 150/150, 150/150 (mild 150 ms: 2/150) | 0/791 |
| `signal.terminal-silence@2` | pt 73/77, de 13/80, fr 3/80, 0-1% elsewhere | `trailingDigitalSilenceMS`, pooled | 11.9 ms; 31/3718 (upper 0.011); en 7/236 (upper 0.071) | SIG-SIL 150/150, 150/150 (mild 150/150) | 0/791 |

The app's DC offset is about 1.6e-4 in every language and voice (N3 95th percentile 2.2e-4 to
2.9e-4 per language); v1 flagged it wherever FLEURS's own offset was smaller (4.2e-5 in fr, 8.7e-5 in
en). No N3 take holds more than 1 ms of digital silence, while FLEURS N2 holds exact-zero spans up to
0.88 s inside zh, es and ru recordings and 17 ms at the end of zh and en ones: they set the pooled
thresholds, so a 150 ms digital dropout goes undetected. A quiet generated pause or tail that runs
long is outside these detectors (`digital-silence-only`); the legacy Fast QC v8 flags keep reporting
it (A10). The shams alarmed on 0, 2 and 1 of 150 families.

**Clipping below full scale (`signal.clipping@2`).** v1 counted samples above Fast QC's 0.965
ceiling, and SIG-CLIP flattens at the source's own level, so it detected none of them. v2 scores
sign-symmetric flat tops: the smaller of the positive and negative counts of samples held on runs of
equal PCM16 values within 1% of the take's own peak, over the take's samples. A clipping stage holds
both polarities at the level it limits to, whether it clips hard or through a knee below full scale
or writes an over-range signal to PCM16, while speech reaches its peak on isolated samples. The
measure is relative to the take's peak, so a gain change moves nothing. The one-sided count was
weaker: its Japanese FAR bound was 0.216 at alpha 0.05, because the N2 round trip clamps some loud
FLEURS recordings at full scale on one side. The two-sided threshold is 0 at every alpha (99% of dev
families hold no two-sided flat top), so any two-sided flat top alarms.

| Population (spent AQ-07 data) | Alarms |
|---|---|
| FLEURS test N2 | 16/3718 (upper 0.007); ja 15/357 (upper 0.077), ko 1/245, 0 elsewhere |
| SIG-CLIP hard mild, moderate, severe | 140/149 (lower 0.897), 150/150, 150/150 (lower 0.980) |
| SIG-CLIP soft-knee and over-range at moderate, built in memory on the same 150 sources | 149/150 (lower 0.969), 150/150 |
| SIG-CLIP sham; peak-normalization control | 1/150; 1/150 (the same source's clamp) |
| N3 takes of 2026-09-27 | 0/791 |

Schedule version 2 of the injection set (below) draws the soft-knee and over-range clips at moderate on
the hard sweep's families, so the confirmation set holds all three constructions. A warn confirmation
gates on severe cells only, where clipping is hard, so their detection is measured per unit and judged
only at a fail point (`clip-variants-moderate`). A soft knee leaves a flat top only where it saturates,
as speech's crest factor makes it do; a smooth procedural waveform barely above the knee is compressed
without one (`soft-knee-saturation`).

**Injection schedule, version 2.** The version 1 schedule drew each injector's sham, mild, moderate and
severe variants and nothing else, so a successor's cell could miss a construction of the defect it
claims. `audio_qc_calibration_set.py` now records the schedule a set drew (`schedule.version`). Version 2
also draws `SCHEDULE_EXTRAS`, the catalog's extra variants at a severity an unplanned detector targets,
on the same sampled families. An extra variant never changes the draw, and one that needs words is not
applicable, with its reason, on a take without a usable alignment.

| Injector | Extra variant | Drawn? | Why |
|---|---|---|---|
| SIG-CLIP | `soft-knee-moderate`, `over-range-moderate` | yes | `signal.clipping@2` reads flat tops at any knee |
| BND-RUNON | `reversed-moderate` | yes | `boundary.run-on@2` reads speech-level audio after the script, whatever it says |
| SIG-DROP | `attenuated-ramped` | no | `signal.dropout@2` scores exact digital silence (`digital-silence-only`) |
| SIG-SIL | `leading-moderate` | no | `signal.terminal-silence@2` scores the trailing silence only |

A test keeps this table and the registry in step: every extra variant at a severity an unplanned detector
targets is drawn or excluded with a reason. `verify` replays any set by the plan rows it recorded, so a
set without `schedule` (version 1) still verifies. A P1 plan binds the version it expects
(`injectionSchedule`). A plan without the binding, as every committed v1 plan is, expects version 1, and
`scores` and `confirm` refuse a set that drew another schedule (A5). The catalog version stays 3: no
injector's output changed.

**Content: insertions and repetitions (`content.consensus-error@2`).** v1 took the smaller of the
two families' error rates, so a take alarmed only when both families heard the defect, and Whisper
large-v3 smooths repetitions away. On the spent CNT-REP severe positives in scope, Whisper
transcribed none of the repeated units on 73 of 133 while the literal family (Parakeet; Paraformer
in zh) heard at least three on 125. No per-family measure can lift a minimum above the weaker
family's hearing. v2 changes the score and the combination:

- **Score per family: the insertion-deletion rate.** It counts the units heard beyond the script
  plus the script's units not heard, over the script's length (`transcript-edit`, measure
  `insertionDeletionRate`). The counts come from the minimum-cost alignment that has the fewest of
  them, so a pair read either way counts as a substitution, a recognizer's own kind of error.
  Insertions minus deletions is the length difference, so the counts do not depend on tie order.
- **`consensus-mean`: the two families' mean.** It still needs two independent voting families
  (A6) and records their phi audit. Each family's evidence counts at half weight, so one family
  alarms alone only with twice the threshold's evidence (`one-family-alarm`).

Japanese and Korean leave the scope (`sensevoice-codec-failures`): SenseVoice's outright failures on
codec audio put the Japanese threshold of the mean at 0.5. Substitutions no longer count
(`substitutions-not-scored`). Per-language thresholds on the eight languages in scope:

| Rule (alpha 0.05 unless noted) | N2 FAR pooled; worst language | DEL / INS / REP severe | Shams DEL / INS / REP | N3 flag rate |
|---|---|---|---|---|
| v1: min of error rates | 180/3116 (upper 0.065); fr 32/286 (upper 0.166) | 114/134 (lower 0.791), 91/134 (0.606), 66/133 (0.422) | 7, 8, 9 of 134, 134, 133 | 90/633 |
| min of insertion-deletion rates | 156/3116 (0.057); en 26/236 (0.171) | 131/134 (0.943), 91/134 (0.606), 67/133 (0.429) | 7, 8, 10 | 54/633 |
| mean of error rates | 186/3116 (0.067); fr 39/286 (0.195) | 107/134 (0.733), 103/134 (0.701), 126/133 (0.903) | 8, 7, 12 | 116/633 |
| v2: mean of insertion-deletion rates | 164/3116 (0.060); it 31/351 (0.133) | 132/134 (0.954), 120/134 (0.841), 127/133 (0.913) | 7, 8, 14 | 98/633 |
| v2 at alpha 0.03 | 104/3116 (0.039); it 29/351 (0.126) | 123/134 (0.868), 117/134 (0.816), 127/133 (0.913) | 4, 4, 9 | 84/633 |

CNT-REP's sham, a splice at the same boundary with nothing repeated, raises both families'
insertion-deletion rate. At alpha 0.05 its 14 of 133 alarms do not overlap the clean N2 interval, and
A4 would refuse the detector; at alpha 0.03 the two overlap narrowly (`splice-sham-content-errors`).
Plan v2 at alpha 0.03. CNT-INS stays the hardest cell: on 11 of 134 severe positives neither family
heard an inserted unit. The app takes at alpha 0.03 flag 29 of 80 in French and 13 to 14 of about
80 in Italian and Spanish (Serena 31 of 107), much as v1 flags them. French recognition of the
app's French is itself poor (see the nativeness detector below).

**Run-on (`boundary.run-on@2`).** v1 subtracted the aligner's script end from Whisper large-v3's
last segment end, and Whisper ignores most material after the script: on the spent BND-RUNON severe
positives its end sat a median 0.04 s past the aligner's, so v1 detected 43 of 135. The recognizers'
transcripts do no better: neither family's trailing insertions exceed 0 at the median of the severe
cell. v2 reads the audio itself. The end of the take's last active span (`pcmMeasures`
`lastActiveSeconds`) minus the aligner's script end measures the seconds of speech-level audio after
the script. It is gated on both content voters, as v1 was, and keeps language strata: the aligner's
end and FLEURS's post-speech sounds differ by language (dev 95th percentile 0.09 s in es to 3.2 s in
ja).

| Alpha (per language) | N2 FAR pooled; worst language | BND-RUNON mild / moderate / severe | Sham | N3 flag rate |
|---|---|---|---|---|
| 0.05 | 135/3473 (upper 0.045); zh 31/602 (0.079) | 105, 120, 125 of 135 (severe lower 0.878) | 11/135 (lower 0.046: departs, A4) | 20/713 |
| 0.02 | 60/3473 (upper 0.021); pt 10/359 (0.058) | 72, 113, 123 of 135 (moderate lower 0.776, severe 0.860) | 1/135 | 3/713 |

The sham appends 300 ms of -80 dBFS room tone. On noisy recordings that lowers the frame floor, and
the noise after the last word can then form an active span (`noisy-tail-activity`), so plan v2 at
alpha 0.02. Of the 12 severe positives missed at 0.02, 7 appended copies of a quiet span from the
take's middle. That is a limit of the recording variant, which repeats a 0.5 s span it cannot place
on words (`runon-quiet-span`). The other 5 are Japanese takes whose aligner covered 42-61% of the
units.

**Nativeness (`language.nativeness@1`, class D, warn).** The maintainer hears a Voice Design voice
read French like an English speaker. `language.consensus-lid@1` takes the larger of the two
classifiers' expected-language confidences, so both must be low, and the audit counts accented
speech as a language-ID negative (section 4.2). It therefore catches only the severe cases. The
nativeness detector scores the mean of Whisper large-v3's expected-language probability and
VoxLingua107's expected-language posterior (`consensus-mean`). It fits per-language thresholds on
native read speech (N2 FLEURS), direction below. An accent pulls both confidences down while both
still identify the language. Native FLEURS French scores a VoxLingua posterior of 0.999 at the
median (10th percentile 0.990) and a Whisper probability of 0.99 at the 10th percentile; the app's
French from Serena scores 0.39 and 0.97 at the median.

| Language | Native N2 FAR at alpha 0.05 (threshold) | App takes flagged, by voice (N3 of 2026-09-27) |
|---|---|---|
| French | 25/286 (upper 0.139; 0.978) | Serena 19/27, Aiden 13/26, Design 9/27 |
| Spanish | (0.932) | Aiden 18/26, Design 17/27, Serena 13/26 |
| Italian | (0.930) | Vivian 13/27, Design 8/26, Aiden 2/26 |
| Portuguese | (0.881) | Aiden 5/26, Design 4/24, Serena 2/27 |
| Chinese, Japanese, Korean | (0.995, 0.983, 0.997) | 7/79, 5/80, 4/78 |
| English | (0.899) | Serena 3/27, Aiden 1/26, Design 0/27 |
| German, Russian | (0.487, 0.516: VoxLingua is weak on native speech) | 0/80, 1/79 |
| All ten | 151/3718 (upper 0.046) | 144/791 |

On the same takes consensus-lid@1 flags 27 of 80 French takes, 1 of the 27 by the Design voice. The
nativeness score flags 41, 9 of them by the Design voice: an accent that leaves the language
identifiable is what it adds. N3 carries no labels, so these rates describe how often the app's
voices sound foreign to two classifiers, not how often a native listener would agree
(`accent-by-voice`).

*Natural labelled positives.* No construction produces an accent, so the qualification path is
English only. Its positives are speechocean762 utterances, English read by Mandarin-L1 speakers,
whose published expert accuracy score is 4 of 10 or less (severe; 5-6 moderate). The corpora
registry pins them, and they must be resynthesized to N2 like the negatives. The driver now takes
such a population:

- **Role set.** `accent-natural-n2`'s positives are P4 of mechanism `T4-natural-labelled` and
  declare their label tier, source, field and rules.
- **Plan.** `plan --natural-positives` binds the corpus's cohort, its confirmation split, and the
  label rule. It refuses a cohort that shares a speaker, family or script with either FLEURS cohort,
  and it plans no injection set.
- **Scores.** `scores --role confirmation --natural-positives --natural-bundle` reads each take's
  label from its N1 recording and keeps the takes the rule selects. It scores them from their own
  panel, fresh after the plan; they have no sham, and the record pins their cohort.

Two maintainer decisions of 2026-09-30 make the path plannable, and the role set now names the
corpus `speechocean762-confirmation`. The negatives come from the FLEURS reserve cohorts, as for
`fleurs-reserve-n2`.

- **Policy (`accent-labels-exception`).** The policy's `labelTierExceptions` admits speechocean762's
  expert accuracy (T4) as P4 labels for `language.nativeness@1`, in English only. The entry cites its
  dated decision, which the policy records in `decisions`. Every other detector keeps T4 for
  negatives only. The driver refuses natural positives at plan and at scoring time unless an
  exception names the detector, the corpus, the label field and every language of the positives.
- **Data (`accent-single-l1`).** `audio_qc_corpora.py cohort --source speechocean762 --split
  confirmation` builds the N1 cohort from the corpus extraction:
  - speakers are split by a seeded SHA-256, the confirmation share recorded (`--confirmation-share`,
    default 0.5), so the two splits share no speaker;
  - every utterance keeps its speaker, its accuracy, completeness, fluency, prosodic and total scores
    and its text;
  - an utterance without text, speaker or a numeric accuracy, or one longer than 60 s, is ineligible
    with its reason.

  The builder counts each split's eligible utterances per severity of the role set's rule (accuracy
  4 or less severe, 5-6 moderate). It warns when the confirmation split holds fewer severe utterances
  than the warn floor of 60, since how many score that low is not known before the extraction. It
  refuses a missing or stale extraction. The qc-n2 lane resynthesizes the cohort like a FLEURS one.
  The natural positives must be the corpus split the role set names, and the plan binds it
  (`naturalPositivesSource`), so a confirmation spends it whichever resynthesis a later plan names.

The detector combines its two classifiers by their mean, which by the other decision of 2026-09-30
qualifies at warn only (`mean-consensus-warn-only`, beside `content.consensus-error@2`). Each fail
operating point lists it in `refusedCombinations`. `plan` refuses a fail plan of either detector, and
`validate` refuses any fail plan or record of a combination the point refuses. A fail level keeps
strict two-family consensus.

The other nine languages keep thresholds that bound their FAR on native speech, but their
sensitivity is unmeasured (`accent-positives-english-only`): a lane should read them as report-only.

### Oracle ladders for pYIN, HNR and the quality composite (AQ-08, 2026-09-29)

Audit section 4.4 makes pYIN and the window-corrected HNR measurands only "once oracle ladders
pass", and section 4.6 lets the Audiobox and DNSMOS composite serve as a DP-31/DP-32 guardrail
column only after a ladder test. `scripts/lib/qc_qualification/ladders.py` defines three ladders
whose truth is known by construction (T1; no judge labels anything), and
`scripts/audio_qc_oracle_ladders.py` builds, scores and records them. No WAV is committed: each
ladder is pinned by a golden digest over every clip's PCM16 digest and truth.

| Ladder | Clips | Construction | Scored from |
|---|---|---|---|
| `pyin` | 48, 80.5 s at 16 kHz | Steady harmonic tones 55-950 Hz, formant-shaped vowels, exponential glides, vibrato, octave jumps, voiced/unvoiced alternation over silence or fricative noise, white noise at 30-0 dB SNR. Truth per 10 ms frame on the registry's pYIN grid; frames within 52 ms of a voicing change, F0 jump or clip edge are not scored | `pitch.pyin@1` through the orchestrator; per-frame F0 from the run's L1 entries (the bundle keeps statistics only), keyed as `audio_qc_calibration_set.py alignments` keys the aligner's |
| `hnr` | 39, 58.5 s at 24 kHz | Noiseless sines at 80, 150 and 300 Hz; formant-shaped harmonic sources at 100-300 Hz with white noise scaled to an exact 0-40 dB ratio (one scaled draw per source), plus the noiseless rung | In-process, no model: the Stage 1 `prosody@3` proxy (`voice_hnr_db_mean`) and the window-corrected candidate (`audio_phonation.py`) |
| `quality` | 92, 5.6 min at 24 kHz | Four procedural speech sources (or up to eight lead-supplied recordings, `--quality-sources`), each with five rungs of white noise (40-0 dB SNR), hard clipping (0.2-20% of samples), a zero-phase low-pass (7-1.5 kHz) and mu-law quantization (8-3 bits), plus shams (noise at 80 dB SNR, low-pass at 11.9 kHz) | Audiobox PQ and DNSMOS OVRL through the orchestrator; the composite is section 4.6's z(PQ) + z(OVRL) - z(WER), duration regressed out, the WER term only where every rung has `--wer-judge`'s error rate (never on procedural pseudo-text) |

**Criteria.** Each names its source. From the audit: HNR at least 37 dB on noiseless sines and
within 1 dB of Parselmouth on the SNR rungs (4.4), readings monotone in the constructed ratio and a
composite whose Spearman correlation with severity is -0.9 or lower on every ladder (5.8's
"monotonically with severity, Spearman >= 0.9"; quality falls). Provisional, because the audit
states none: every pYIN limit (per group GPE, the share of jointly voiced frames more than 20% off,
of 0.02 on clean in-range signals, 0.05 on the 50-70 and 400-1,000 Hz extensions, 0.03 at 20 dB SNR
or better and 0.05 at 10 dB; RMS fine error of 20, 25, 25 and 35 cents; voicing decision error of
0.05, 0.10, 0.08 and 0.15; the 5 and 0 dB rungs are reported only), the composite's step tolerance
(a rung may exceed the milder one by 0.10 z-units) and sham tolerance (0.25), and HNR within 1 dB of
the constructed ratio up to 30 dB, which stands in for the Parselmouth comparison until an oracle
file is supplied (a tracker at the 37 dB floor adds at most 0.79 dB there). A ladder is `pass` only
when every gating criterion is the audit's and was evaluated, `pass-provisional` when a provisional
criterion gates or an audit criterion was not evaluated, `fail` on any failed gating criterion and
`incomplete` when a clip has no measurement.

**First in-process result (HNR, no model).** The `prosody@3` proxy fails: it reads 0.50, 6.99 and
13.29 dB on the noiseless sines (AQ-F16) and is up to 27.2 dB below the constructed ratio, though
monotone. The window-corrected candidate is `pass-provisional`: at least 56.7 dB on the noiseless
sines, within 0.23 dB of the constructed ratio from 0 to 30 dB, and monotone. The Parselmouth
criterion awaits an isolated reference run (`--oracle-hnr`, a `vocello.audioqc.hnr-oracle/1` file of
per-clip readings; Parselmouth is never linked or run from the repository).

The pYIN and quality ladders run models, so the lead runs them like any orchestrator panel; both
are short (est.: pYIN about a minute with its worker start, the quality pair two to three minutes). Pass
`evaluate --cache-root` when the run used a non-default cache root. Every output stays under the
build root; the report holds clip ids, digests and numbers only and passes the evidence privacy
walker.

```sh
L=build/artifacts/diagnostics/audio-qc-oracle-ladders
B=build/artifacts/macos/audio-qc
O=scripts/audio_qc_oracle_ladders.py
python3 $O build                                   # all three ladders under $L
python3 $O evaluate --ladder hnr                   # in-process DSP; add --oracle-hnr <file> when one exists
python3 scripts/audio_qc_orchestrator.py run --manifest $L/pyin/manifest.json \
  --judge pitch.pyin@1 --bundle $B/oracle-ladder-pyin-<date>
python3 $O evaluate --ladder pyin --bundle $B/oracle-ladder-pyin-<date>
python3 scripts/audio_qc_orchestrator.py run --manifest $L/quality/manifest.json \
  --judge quality.audiobox-aesthetics@1 --judge quality.dnsmos-p835@1 --bundle $B/oracle-ladder-quality-<date>
python3 $O evaluate --ladder quality --bundle $B/oracle-ladder-quality-<date>
python3 $O report --evaluation $L/pyin/evaluation.json --evaluation $L/hnr/evaluation.json \
  --evaluation $L/quality/evaluation.json --output $L/report.json
```

### Corpora for the next qualification round

`config/audio-qc-corpora.json` pins the lean set the maintainer chose on 2026-09-29, rendered with
its licenses, labels and caveats in [audio-qc/corpora.md](audio-qc/corpora.md). Four groups: FLEURS
train as new, never-scored N1 reserve cohorts (N2 resynthesizes them); speaker-labelled speech for
class E (CREMA-D, LibriTTS-R dev.clean and test.clean, Multilingual LibriSpeech de, fr, es, it and
pt, Zeroth-Korean, an AISHELL-3 test subset, Emozionalmente); acted emotion for class H (Thorsten
emotional v2, EmoDB, JVNV, emoUERJ, RESD, with CREMA-D and Emozionalmente shared); accented English
for class D (speechocean762). The maintainer runs, in order:

```sh
python3 scripts/audio_qc_corpora.py plan --set lean      # bytes, destination, free space; no network
python3 scripts/audio_qc_corpora.py runtime              # the pinned Parquet runtime (PyPI, once)
python3 scripts/audio_qc_corpora.py fetch --set lean && python3 scripts/audio_qc_corpora.py extract --set lean
python3 scripts/audio_qc_corpora.py verify --set lean    # offline re-check of downloads, runtime, extractions
```

- **Size.** 9,037 files, 28.96 GB to download (plus 7 MB of N1 dev and test TSVs the reserve reads);
  about 13.6 GB of WAVs once extracted, since Multilingual LibriSpeech, Zeroth-Korean and
  LibriTTS-R keep 20 utterances per speaker (a seeded per-speaker cap; about 34 GB uncapped); the
  FLEURS reserve cohorts (5.4 GB) and MLS (3.1 GB) are the largest. `plan` compares the need, with
  the 2 GiB margin, to the free space; `fetch` refuses a selection that does not fit, and each
  extraction checks its own need first. `--group` and `--source` narrow any command.
- **Pins and hosts.** Hugging Face files by LFS SHA-256 or git blob SHA-1 at a pinned revision
  (unofficial mirrors accepted that way, licenses cited from the official source), GitHub LFS
  content by SHA-256 (the 7,442 CREMA-D WAVs, `config/audio-qc-corpora/crema-d.tsv`), a GitHub
  source's plain git metadata file by git blob SHA-1 at its pinned commit (CREMA-D's
  VideoDemographics.csv), Zenodo archives by the publisher's MD5 and exact size. Downloads reach
  only huggingface.co and its CDNs, media.githubusercontent.com, raw.githubusercontent.com (a
  blob-pinned metadata file only) and zenodo.org, resume with range requests where the host
  honours them, and move into place only once verified. `corpora-fetch-receipt.json` records each
  file's SHA-256; for an MD5-pinned file it is recorded on the first verified fetch and checked on
  every later run.
- **Speaker gender.** The class E impostor, identity-swap, onset and seam-voice injectors draw
  same-language, same-gender donors, so they use only clips that carry a speaker and a gender.
  Multilingual LibriSpeech takes it from each language's `data/mls_<language>/metainfo.txt` (the
  OpenSLR metadata the mirror carries, pinned by git blob SHA-1, `F`/`M` joined by speaker id
  within that language), CREMA-D from the `Sex` column of VideoDemographics.csv joined by actor id
  (its age, race and ethnicity columns are never read into a manifest or record), AISHELL-3 from
  `spk-info.txt` and Emozionalmente from its `users.csv`. A speaker whose rows disagree keeps no
  gender, never a guess. LibriTTS-R and Zeroth-Korean carry none: their mirrors have no speaker
  table and no pinnable source was found on the allowed hosts.
- **AISHELL-3 subset.** A seeded rule over the pinned test listing: the 76 speakers with at least
  100 WAVs, 20 WAVs each (lowest SHA-256 of seed and path), resolved to explicit per-WAV pins in
  `config/audio-qc-corpora/aishell3-test-subset.tsv` by `audio_qc_corpora.py resolve-subset`.
- **Parquet runtime.** `config/audio-qc-runtimes/corpora-parquet.txt` pins pyarrow, soundfile (its
  libsndfile decodes the FLAC and Opus cells) and their dependencies with PyPI hashes for CPython
  3.14 on macOS arm64. It is not a judge runtime: `runtime` builds it with the judge acquisition's
  own interpreter, hash-locked pip install, RECORD check and import probe, under the same
  `external-models` root, and `extract` runs `scripts/audio_qc_corpora_worker.py` inside it,
  offline. The system interpreter needs neither package.
- **Extraction.** Every clip becomes mono PCM16 WAV at its source's output rate, 16 or 24 kHz (the
  rates the recording adapter reads): channels averaged, other rates (AISHELL-3 44.1 kHz, JVNV
  48 kHz, Thorsten 22.05 kHz, part of RESD) resampled with the Kaiser-5 polyphase design of
  `lib.playback_capture.resample`. Each source gets an untracked `audio-qc-corpus` manifest under
  `<source>/<revision>/extracted/`: per clip its speaker, gender, emotion (the corpus's label and a
  canonical name where the registry maps one), accent, pronunciation scores and text where the
  corpus has them, duration and digests. Metadata tables (archive members, or pinned files beside
  WAV files or Parquet shards) are joined by key after decoding, outside the Parquet worker; the
  manifest's `metadata` counts each table's rows, unjoined clips and any conflicting keys.
  Identical PCM is kept once with its duplicates listed (the
  MLS 1-hour set shares speakers with the 9-hour set and may repeat its clips); an undecodable clip
  is listed as skipped with its reason.
- **FLEURS reserve cohorts.** Per language, the train recordings the N1 rules mark eligible (a
  FLoRes sentence id also read in dev or test counts as shared, so it is ineligible) are grouped by
  sentence; the sentences, in the order of a seeded SHA-256, fill cohort 1 to 400 recordings, then
  cohort 2 and cohort 3, a sentence belonging to one cohort only. The cohorts are therefore
  disjoint by sentence from each other and from dev and test (speaker disjointness stays the
  declared FLEURS limitation). Only the sampled members of each `train.tar.gz` are decoded
  (`audio_qc_n1_corpus.extract_members`). Each cohort is an `audio-qc-n1-cohort` manifest, split
  `reserve-<k>`, at `fleurs/<revision>/reserve/<sampling digest>/cohort-<k>/manifest.json`, which
  the N2 plan and the calibration set take as they take the dev and test cohorts. A language that
  cannot fill every cohort is reported, not padded.

**Which reserve cohort does what.** FLEURS test is spent: the v1 warn plans confirmed on it. Role set
`fleurs-reserve-n2` of `config/audio-qc-detectors.json` fixes the rule: reserve-1 fits, reserve-2
confirms at warn, and reserve-3 (`failCorpus`) is held back for a fail point. A later requalification
at warn needs a registry change that names reserve-3, or new reserve cohorts. `accent-natural-n2`
takes its negatives from the same cohorts. Every unplanned FLEURS detector names this role set: the
six v2 detectors, `signal.band-limit@1`, `prosody.pitch-break@1` and `prosody.octave-jump@1`. The
eleven planned v1 detectors keep `fleurs-n2`, and their plans, ledger entries and records are
unchanged. `audio_qc_detector_calibration.py` enforces the rule:

- It reads a reserve cohort's split from its N1 manifest: `split` `reserve-<k>`, which the `reserve`
  block must confirm, with FLEURS split train.
- It never scores a reserve cohort past the first for calibration or information.
- It refuses, as any new plan's confirmation, a FLEURS corpus that a confirmed plan scored
  (`spentSources`), whichever N2 resynthesis of it the plan names.

The reserve cohorts are grouped by sentence, not by speaker, so the calibration and confirmation cohorts
likely share speakers (`fleurs-reserve-no-speaker-ids`).

**Long-form cohorts.** Role set `n3-long-form` names the take plan's long-form cell
(`vocello-long-form-calibration` and `-confirmation`). A long-form take records its seams in its
`longForm` block, not as `seamSamples`, and the calibration set now reads them there (`take_seams`),
so SEAM-DISC and SEAM-VOICE draw from those takes.

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

The blinded listening-session scripts were removed on 2026-09-12 (git history retains them); only
`delivery_promotion_decision.py` schema 1 still reads historical listener results. The template
above is an annotation data contract for optionally imported listener evidence, not a claim that
any listening session exists or was run. No independent reviewers or labels were fabricated.

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
  digests. WER/CER is recomputed with the shared language metrics and unchanged 0.15 threshold;
  supplied scores are ignored. The word rate is WER v2 since 2026-09-25, which moves pass/fail
  under the same evidence policy, so each review and the report record `accuracyMetricVersion`,
  and `reviewDependencies` binds `lib/language_metrics.py`. These processing receipts are evidence from trusted producers,
  not cryptographic proof that a recognizer actually listened to every word.
- At least two distinct supported ASR families must agree. Three Whisper/Apple repetitions are
  repeatability, not independent consensus. Wrong-language/partial/missing/drifted receipts or
  disagreement are inconclusive; unanimous valid content rejection is a measured failure.
  SenseVoice cannot judge French. No new recognizer was acquired.
- Optional compact features do not create a mandatory listener dependency. Semantic delivery is
  reported **unmeasured**: the fitted heads that estimated it were never calibrated and left QC
  with DistilHuBERT (AQ-05). Uncertainty never requests a human as the only continuation; bounded
  automatic evidence collection or a recorded inconclusive decision replaces manual-listening
  routing. Requested ASR layers are not automatically launched by this composer. Neural work runs
  after TTS exits, one persistent worker per run under the supervisor; cache hits do not launch
  models; no retired judge (NISQA, UTMOSv2, the SER, DistilHuBERT, the fitted heads) is requested
  or run.
- `delivery_promotion_decision.py` schema 2 requires a frozen named metric/protocol, complete
  untouched holdout, independent-reference qualification, independent judge families, consistent
  reverse-order judgments, paired improvement/2AFC, distributed gains and unchanged quality/runtime
  guardrails. The relative-UTMOS guardrail is retired: a legacy input that carries it is reported
  under `retiredGuardrails` and never gates. It can qualify **measured automatic improvement**,
  never listener-proven emotion.
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
versioned derivative cache, one orchestrator admitting supervised workers within a measured budget,
and explicit per-dimension decisions. Listening is optional. Frozen independent-reference qualification supports named measured
improvements, not listener-proven semantic claims; unmeasured dimensions remain explicit.
No new aggregate score, hidden retry, model/prompt/seed change, QC relaxation, or parallel harness.
