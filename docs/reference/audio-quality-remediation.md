---
status: active
owner: release-qa
reviewed: 2026-10-10
summary: Ordered implementation and evidence requirements for automatic audio-defect detection and generation remediation.
sourceOfTruth:
  - scripts/qc.py
  - scripts/qc/qualification.py
  - config/roadmap.json
---
# Audio quality remediation implementation

This implements the October 10 follow-up to the
[retained candidate regression](../audits/2026-10-10-local-audio-candidate-implementation.md).
QC-06 owns detection/causal follow-ups, QC-08 owns finishing, and RF-14 owns the release quality
decision. These items stay open until their evidence gates are met. Implementation completion does
not establish detector accuracy. Phone-dependent acceptance remains deferred.

## 1. Independent review authoring and provenance

Preserve the historical labeling protocol. Add a separate versioned local-review protocol defining
phonation, false starts, boundary pronunciation, Clone register and accent mismatch, including
exclusions for intended whispering, expressive prosody and valid regional French. Prepare private
blinded drafts from retained runs with exact audio/reference and source receipts. Leave class
coverage, leakage groups, reviewer competence and pronunciation alternatives unreviewed.

Validate independently authored reviews: multiple localized events, complete negatives versus
positive-only coverage, explicit uncertainty, duration bounds, request-relative target variety and
reviewer attestation. Bind actual protocol, run, review and audio bytes. Revisions get new identities.
Export reviewed pronunciation alternatives only when canonical phone/word map, audio and review
receipt agree. Generated drafts never claim human listening or independent truth.

Test tampered protocol/review/WAV/reference, group/timing/path errors and immutable revisions.
Unknown labels cannot become negatives; historical labels keep their original meaning.

## 2. Actual failures and reproducible generation bundles

Inventory retained Clone/reference and French Design evidence without logging private text.
Add a private case verifier around existing generation receipts and codec replay, binding request,
source/build/model identities, reference preparation, conditioning, seed/sampling and stage artifacts.
Missing historical inputs stay unknown. Synthetic pitch controls are not actual failing pairs.

Use paired arms with one declared intervention and unchanged controls. Reuse installed assets and
existing replay entry points; retain partial/failing evidence. Do not add a second native runner.
Exact reported failing pairs and matched acceptable controls are inputs the assistant cannot invent.

## 3. Protected qualification

Reuse the existing event matching/coverage evaluator. Bind actual review/protocol bytes, an explicit
reviewed observation-to-semantic mapping, and a frozen policy before protected evaluation. Partition
speaker/reference/source/prompt/derivatives, including cross-role identical audio. Exposed Dylan
stays in training; historical protected confirmations stay excluded. Record exposure and reuse.

Report misses, false alarms per minute, clean-clip false alarms, abstentions and support. Freeze
settings before evaluation; never tune on protected results. Language recognition cannot qualify
native accent. Independent positives and complete negatives are required. No automatic promotion.

## 4. Causal generation remediation

Compare verified paired bundles for reference preparation, conditioning, sampling, codec decoding and
final output separately. Reject confounded/incomplete causal comparisons. Inspect already integrated
fixes before editing production. Change a shipping stage only after a reproduced defect identifies it;
verify deterministic/native contracts and the smallest seeded model/performance lane on a checkpoint.

Missing failing pairs or stages block attribution, not remaining tooling. Do not pitch-shift voices,
strip user accent intent, regenerate automatically, or activate unqualified rejection thresholds.

## 5. Fast QC finishing, separate from identity/accent

Implement a bounded offline study of 20 ms relative frame silence, short ending fades, fixed tails
and bounded loudness gain. Bind original PCM, settings, source and summaries; preserve originals.
Measure installed human controls before choosing thresholds. Use the existing K-weighted loudness
observer; never call RMS LUFS. Disclose unsupported short/silent inputs and speech-loss risks.

Keep shipping v8, existing calibration and benchmark lineage until QC-08's gate is met. Production
v9 needs a new calibration record, Swift/Python parity and reseeded lineage together. Finishing
cannot repair French phonology, Clone identity or a false-start token sequence.

## Integration and completion

Proceed in this order with scoped commits and targeted checks. Review privacy/provenance changes
independently. Run routed checks over the batch; native checks only when native code is affected.
Source-bound cache analysis uses record-only posture with joined workers and no native-lock conflict.
Preserve prior regression/failures. Update the existing roadmap/checkpoint with capabilities and gaps.
No push, download, publication or release is implicit. Final reporting separates implemented tools,
executed evidence, missing independent review/data and shipping behavior changes.

## Verified implementation seams at the pause

The read-only investigations finished before implementation began:

- `qc/label.py` already provides private blinded listening, per-rater append-only labels and coarse
  timed legacy classes. Preserve that protocol; add strict local review around it rather than rewriting
  old labels. Current labels lack complete per-class negatives and source-audio byte binding.
- `qc/qualification.py` already verifies exact audio/reference bytes, sample-exact duration, scoring
  and runner identities, class coverage, group leakage and one-to-one event matching. Extend its
  source receipt checks; do not create a second evaluator. Its protocol hash currently checks syntax
  without resolving actual protocol bytes. Human-observed origin remains caller asserted.
- `qc/boundary.py` validates local full-path alternatives, but its provenance is caller asserted.
  `qc/evidence.py` forwards take hypotheses directly. The review workflow must bind actual annotation
  bytes, canonical phone/word map and audio before exporting hypotheses. Observation classes must
  never silently become semantic ground truth.
- `GenerationRequestReceipt` schema 3 and `BenchCodecReplay.swift` already bind Clone conditioning
  reference, original output and codec trace. Replay has four cold/primed incremental/production
  schedule arms with immutable outputs and partial evidence. Reuse these. The retained successful
  English example is not the missing actual failing Clone pair and does not justify decoder changes.
- Fast QC remains v8 and its calibration is `legacy-unqualified`. Existing
  `scripts/lib/audio_qc_observations.py` supplies K-weighted loudness/true-peak observations. QC v2's
  25 ms frame profile is not QC-08's proposed 20 ms frame silence. Keep that distinction explicit.
- `scripts/clone_fidelity_lane.py` has stale introductory prose claiming missing qualification passes;
  its implementation already correctly returns strict NOT_ASSESSED 4. Correct the prose when that
  file is next included in the scoped implementation.

No source, tests, contracts or shipping behavior changed during these investigations. Outstanding
optional inputs are the intended French variety and identification of an actual retained failing Clone
pair. Current product policy accepts native French varieties unless the request specifies otherwise.
