---
status: historical
owner: backend-and-platform
summary: Pinned privacy-safe Mac and CLI characterization of Clone identity, enrollment evidence, tokenizer availability, and French Voice Design behavior before physical-iPhone closure.
contentDigest: sha256:cd25de5db19b21e48fc677f15d66a9a53380e86695a597cc1191dcca52af8ff7
sourceOfTruth:
  - config/voice-identity-language-reliability.json
  - scripts/voice_identity_language_reliability.py
  - Sources/QwenVoiceCore/GenerationOutputAdapter.swift
  - config/roadmap.json
---
# Voice identity and language reliability — Mac/CLI checkpoint — 2026-09-01

> **Pinned historical Mac checkpoint.** This report records privacy-safe conclusions from the
> completed operator-local Mac/CLI campaign. It contains no personal voice name, transcript,
> audio, path, or device identity. It does not claim physical-iPhone closure or authorize a prompt,
> model, tokenizer, sampling, or release change. Source, machine-readable contracts, repository
> scripts, and [`config/roadmap.json`](../../config/roadmap.json) remain authoritative.

## Executive assessment

The Mac/CLI phase is complete. All 734 planned rows are represented: 364 passed, 360 were
explicitly blocked because the immutable archived-fp32 tokenizer artifact was unavailable, and 10
failed mandatory generation/audio QC. No row was retried, replaced, or assigned another seed.

The evidence does not support a tokenizer rollback or a French Voice Design prompt change. The
current fp16 tokenizer produced broad coverage, every assembled Design receipt carried the expected
French model-facing language, and the shipped Neutral arm was the strongest tested French Design
arm. The archived comparison remains honestly unavailable rather than being simulated with the
current artifact.

The affected Clone tuple was localized to deterministic model-generated leading near-silence for
one transcript-backed reference/language/seed combination. The same reference and seed passed in
audio-only conditioning, while the identical codec sequence reproduced the delayed onset in both
incremental and full replay. That invalidates the earlier allocator-cache/deferred-materialization
hypothesis. A bounded Clone-only edge gate now waits for three consecutive active 20 ms windows,
retains up to 80 ms of pre-roll, and drops only the preceding sub-floor edge. It never edits an
interior pause, changes a seed, regenerates a take, or applies to Built-in Voice or Voice Design.

Three fresh corrected-code Mac cohorts covered Auto and explicit English for the affected tuple.
All six rows passed without retry. Their analyzer results were stable: speaker similarity 0.6224
(strong advisory band), pitch shift −1.374 semitones, and pitch-range delta −0.665 semitones. The
1.444× cadence ratio remains an advisory, uncalibrated `clone_pacing_mismatch` under AV-07 and is
not hidden or treated as semantic promotion evidence.

## Source-bound evidence

| Evidence | Result |
| --- | --- |
| Bundle digest | `f7393eb33a9cd89e4e4df11a1d48ae63f5e7e65b6d9cc6512994c7da23d7cd89` |
| Full plan digest | `364661e348af027f242e3e1b3966397af69607e2612036b1fa1468d029c1e642` |
| Full plan source identity | `741541e3e9237bfadfd67fd731199f465ffc75859d6ecb298e91ab34e32da7f0` |
| Full matrix | 734 represented; 364 PASS; 360 blocked prerequisite; 10 hard failure |
| Current-fp16 rows | 374 represented; 364 PASS; 10 hard failure |
| Archived-fp32 rows | 360/360 `BLOCKED_PREREQUISITE`; no substituted artifact |
| Receipt audit | 364/364 passing receipts consistent |
| Design language routing | 0 receipt mismatches across 294 represented Design rows |
| Clone analyzer | 220 passing Clone rows analyzed serially after generator exit |
| Corrected targeted proof | Three independent two-row cohorts; 6/6 PASS; no retry |

The corrected cohorts use distinct source-bound identities:

| Run ID | Plan digest | Result |
| --- | --- | --- |
| `vlr-mac-edge-proof-20260901-01` | `6dc46d4617a70019f3d45ed0a42c293dc9497771a178e7c0182653ca2d41ee26` | 2/2 PASS |
| `vlr-mac-edge-proof-20260901-02` | `12e51fe44264f2aceb3e13cf6efffc2d95010c0de6146ee2d2dec3f6de9474e0` | 2/2 PASS |
| `vlr-mac-edge-proof-20260901-03` | `c11624c365dd118800c600fb1c9ec34f764b50cc60ad5bb8a5d20d5df5f0d895` | 2/2 PASS |

Raw audio, manifests containing private byte identities, transcripts, observations, and analyzer
take IDs remain untracked. The table exposes only governed digests, aggregate counts, and stable
aliases.

## Clone characterization

| Reference alias | Analyzed | Prosody-clean | Advisory speaker median | Weak speaker rows | Main advisory flags |
| --- | ---: | ---: | ---: | ---: | --- |
| `control-english` | 14 | 6 | 0.7708 | 0 | 8 expressiveness |
| `control-french` | 14 | 14 | 0.7309 | 0 | none |
| `user-reference-a` | 98 | 78 | 0.6622 | 0 | 12 pacing, 4 pitch register, 4 voicing |
| `user-reference-b` | 94 | 62 | 0.6397 | 0 | 22 pacing, 6 pitch register, 4 expressiveness |

These bounds are analyzer observations, not reference acceptance or semantic judgments. The English
control itself triggers eight expressiveness mismatches, which is direct evidence that the current
prosody thresholds must remain advisory until AV-07 closes. No personal reference is silently
rewritten, normalized, or rejected from these measurements.

The four duplicate Clone failures in the full plan represent two language-selection paths crossed
with reviewed and corrected transcript arms whose bytes were identical. They are one independent
root condition, not four independent defects. Audio-only conditioning for that reference/seed
passed, demonstrating a transcript-conditioned interaction rather than a general reference or
tokenizer failure.

## French Voice Design

All 294 Design rows carried the expected model-facing French language in the assembled request
receipt. The 10 full-matrix hard failures comprise four duplicate Clone rows and six experimental
Calm rows. Shipped French Neutral rows passed on Mac; the earlier physical-device matrix also ranked
current Neutral above no-delivery and Calm. Auto and explicit French resolve to the same engine
language identity.

Acoustic analysis cannot prove that generated words are semantically correct French. Locale-locked
on-device ASR remains required for the final phone campaign. The Mac evidence nevertheless rejects
language-routing and production-Neutral copy as the first divergence, so production delivery copy
remains unchanged and DP-31/DP-32 retain any semantic prompt-promotion authority.

## Remediation and non-changes

Implemented:

- Bounded Clone-only leading-edge conditioning with deterministic memory and edge-preservation
  fixtures.
- Contiguous published transport sequencing when raw decoder chunks are consumed before onset.
- Privacy-safe terminal metrics for algorithm version, opened state, trimmed frames, retained
  pre-roll, and maximum buffered frames.
- A 14-row `closure` phone profile containing only production Clone and current-Neutral Design
  cells; experimental prompt arms remain in `focused` and `characterization` diagnostics.

Not changed:

- Qwen weights, tokenizer artifact, speaker/reference data, transcript bytes, language contract,
  prompt copy, delivery preset, seed, sampling defaults, retry policy, or audio-QC thresholds.
- The owned Qwen runtime's pipelined materialization policy; the prior speculative change was
  reverted after replay evidence disproved that hypothesis.
- Automatic best-of-N generation or hidden seed substitution.

## Remaining physical-device acceptance

Mac closure does not substitute for physical-iPhone evidence. The next device window requires two
distinct no-retry 14-row `closure` runs followed by one complete 122-row `characterization` run on
the exact committed source. The closure profile verifies both private aliases, English/French
target scripts, Auto/explicit ownership, and all short/medium/long production-Neutral Design cells
without allowing known experimental arms to make production acceptance impossible.

VLR-07, VLR-08, and VLR-09 remain open until those runs prove output-language ASR, the affected
Clone tuple, terminal-silence rejection, receipt parity, and cleanup on the physical iPhone. No
phone command was run while producing this Mac checkpoint.
