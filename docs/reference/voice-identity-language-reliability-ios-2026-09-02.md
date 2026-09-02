---
status: historical
owner: backend-and-platform
summary: Pinned privacy-safe physical-iPhone checkpoint for corrected-source Clone, transcription, and French Voice Design reliability.
contentDigest: sha256:a868ce4acacc1e63d0123e07c5f8efb05e68624a940136da9c7eea40667be010
sourceOfTruth:
  - config/voice-identity-language-reliability.json
  - scripts/voice_identity_language_reliability.py
  - Sources/QwenVoiceCore/GenerationOutputAdapter.swift
  - config/roadmap.json
---
# Voice identity and language reliability — physical-iPhone checkpoint — 2026-09-02

> **Pinned historical device checkpoint.** This report records privacy-safe conclusions from three
> completed, source-bound physical-iPhone runs. It contains no personal voice name, transcript,
> audio, private path, or device identity. It does not authorize a prompt, model, tokenizer,
> sampling, QC-threshold, or release change. Source, machine-readable contracts, repository scripts,
> and [`config/roadmap.json`](../../config/roadmap.json) remain authoritative.

## Executive assessment

The requested corrected-source campaign ran to completion without resuming, merging, retrying, or
substituting a planned take. Both production-focused 14-row closure runs passed. The complete
122-row characterization represented every planned row but failed its aggregate gate: 106 rows
passed, two diagnostic French Voice Design rows were correctly rejected by production audio QC,
12 otherwise successful French Design generations were consistently recognized as French but
failed the governed intelligibility threshold, and two successful generations lacked usable ASR
evidence.

The device evidence closes the two bounded source remediations:

- The Clone-only leading-edge gate passed the affected Auto and explicit tuple in three independent
  device runs. The characterization's complete eight-seed Auto cohort also passed without a hard
  failure. This closes VLR-08 without changing seed, sampling, tokenizer, model, reference,
  transcript, or QC policy.
- Fast-QC algorithm v6 rejected the former take-112 terminal-silence shape before publication. The
  generated output and both codec replays independently measured the same 109.471-second terminal
  run. This closes VLR-09 without weakening interior-pause policy or adding a retry.

VLR-07 remains open. The two closure runs prove the production-focused path, but a complete
characterization cannot be called clean while two deterministic sampled-output defects, 12
output-accuracy rejections, and two inconclusive verifier cases remain. Those findings are retained
as evidence, not converted into passes or hidden behind another seed.

## Source-bound evidence

All three runs bind source identity
`34352e5632150fce737d3646b8dd3ae6fbda13f6466687b079c78666e1d34439`.

| Run | Profile | Plan digest | Result |
| --- | --- | --- | --- |
| `vlr-device-20260902-closure-fixed-01` | closure | `b7cd0b21af295b3e2e5c06440446d027c3ca2e49eb2084aef7935eb0f920301f` | 14/14 PASS |
| `vlr-device-20260902-closure-fixed-02` | closure | `c0e00e4323f13bbe6fec1b8913a9f3f7849d11f282ebe972cb027c4a4cb195d5` | 14/14 PASS |
| `vlr-device-20260902-characterization-fixed-01` | characterization | `a5eb871a086a30295b84ad1d1cf3fb8079f7e70a2633ff3c70049f58492ed119` | 106 PASS; 2 product QC rejects; 12 product accuracy rejects; 2 inconclusive verifier cases |

The untracked run bundles retain their complete plan, append-only launch ledger, typed summaries,
request receipts, codec traces for rejected output, crash baselines, and transcription evidence.
Only aggregate counts and non-sensitive governed identities are recorded here.

## Clone acceptance

The previously affected second-reference English tuple passed in both Auto and explicit selection
paths in each closure run and again in characterization: six independent targeted rows, all PASS.
The characterization additionally exercised the Auto path at all eight frozen seeds; all eight
passed, with seven producing zero locale-locked WER and one producing WER 0.0588 / CER 0.0123.

This is the required physical-device proof that the bounded leading-edge correction does not merely
pass one seed or one language-selection route. The gate remains Clone-only, retains bounded pre-roll,
and does not modify interior pauses or other generation modes.

## Typed transcription result

Both closure runs reproduced the same typed enrollment evidence:

- Private reference A: on-device French recognition completed with average confidence 0.619 and a
  near-certain French language score; a stored reviewed transcript was present.
- Private reference B: French and English attempts returned empty results; a later German candidate
  was low-confidence (0.069) with language score zero. The terminal automatic outcome was therefore
  `lowConfidence`, while the stored manually reviewed transcript remained present and authoritative.

The result confirms the original transcription symptom precisely. It was not permission denial,
recognizer unavailability, or missing manual data, and the delayed automatic result did not replace
the reviewed transcript.

## French Voice Design findings

The two product-owned failures occurred only in experimental diagnostic arms, not the production
closure profile:

1. A long Auto/no-delivery row at seed `32060828` was rejected for a 2.831-second interior dropout.
   Full and incremental replay of the identical codec trace reproduced approximately 3.220 seconds
   of silence at the same location. This is deterministic sampled output, not a stream writer or
   incremental-decoder divergence.
2. A long Auto/Calm-strong row at seed `32060822` was rejected for 109.471 seconds of terminal
   silence after audible speech. Live output, full replay, and incremental replay all failed Fast-QC
   v6 with the same terminal-run length. No invalid WAV was published.

Fourteen successful generations did not satisfy locale-locked output verification. Twelve had
internally consistent three-pass on-device recognition, were identified as French, and contained
measurable WER/CER above the configured 0.15 WER acceptance rule, ranging from WER 0.1667 to
0.5897. Those are product-owned `output-accuracy-verification-rejected` outcomes: they are evidence
of insufficient generated-output intelligibility under the governed rule, not verifier crashes or
language-routing failures. The remaining two rows had no decision-capable ASR evidence—one
`transcription_failed` and one `speech_recognition_inconsistent`—and are retained as harness-owned
`output-verification-inconclusive` outcomes. The affected rows span one production-Neutral row,
three no-delivery rows, and ten Calm-strong rows. Successful generation alone does not prove
acceptable language delivery, while absent or contradictory measurements cannot prove a product
failure.

This pattern continues to rank shipped Neutral above the experimental alternatives, but it does
not prove that all French delivery is acceptable. The two product QC rejects are valid protective
behavior; the 12 output-accuracy rejects require generation/intelligibility investigation, and the
two inconclusive rows require verifier-evidence repair. None is reclassified as a product crash.

## Decision and remaining gate

Closed from this campaign:

- VLR-08: three consecutive physical-device passes for the affected Auto and explicit Clone paths,
  plus an eight-seed Auto Clone cohort without regression.
- VLR-09: the former take-112 terminal-silence shape is rejected before publication with exact live
  and replay evidence.

Still required for VLR-07:

- Investigate the 12 consistently measured output-accuracy rejections without relaxing the 0.15
  WER rule, changing seeds, or relabelling them as harness failures.
- Repair or re-run only the two rows with missing or inconsistent ASR evidence; keep their current
  outcome inconclusive until decision-capable evidence exists.
- Decide how deterministic invalid output in diagnostic prompt arms is represented in the final
  characterization acceptance contract without weakening mandatory QC or silently retrying.
- Run only the focused evidence needed by those proven gaps; the two completed closure runs and the
  122-row characterization remain immutable and must not be repeated merely to obtain a green count.

No production prompt, model artifact, tokenizer, reference, transcript, seed, sampling default,
retry behavior, or quality threshold changed as a result of this report.
