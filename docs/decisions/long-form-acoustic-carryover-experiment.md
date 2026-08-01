# Long-form acoustic carryover — stage-2 experiment pre-registration

- **Status:** pre-registered 2026-08-01 (Tier-4 stage 2, maintainer-directed); probe
  results recorded below after the runs. Nothing here is a product change; adoption
  has its own gates and open design questions listed at the end.
- **Hypothesis (MagpieTTS-LF-shaped, inference-time only):** conditioning segment N on
  a bounded acoustic window of segment N−1 (audio + its exact text, through the
  existing clone ICL path) reduces the audible prosody/voice discontinuity at
  long-form segment joins, at an acceptable cost in per-segment prefill time and
  memory, without degrading speaker identity.

## Mechanism under test

The shipping clone path already accepts a raw reference (`vocello clone
--reference <wav> --transcript <text>`): reference audio is codec-encoded and
interleaved with its transcript as an ICL prefix before the target text. The probe
reuses it verbatim as a *continuation* mechanism: segment N's "reference" is segment
N−1's own output. No engine, prompt-assembly, or product code changes are involved in
the probe.

## Probe protocol (macOS, canonical M2, fixed seeds, exploratory-only)

- **Text:** adjacent narration segments A (~2 sentences ≈ 10 s, inside the clone
  reference 10–20 s guidance band) and B (~3 sentences). A's full audio + full text
  form the perfectly aligned conditioning window — no forced alignment needed.
- **Arms per seed** (A generated once per seed, byte-identical across arms):
  - **control:** B via `custom` with the same built-in speaker (today's long-form
    behavior — fresh context per segment).
  - **carry:** B via `clone --reference A.wav --transcript <A text>`.
- **Seeds:** 4 fixed (1001–1004), sequential generation, analysis strictly after
  (8 GB rule).
- **Measures (existing tools only):**
  1. **Join prosody:** boundary-local deltas — pitch median and syllable rate of the
     last 3 s of A vs the first 3 s of B (stdlib WAV slicing +
     `scripts/analyze_delivery.py` per slice). Primary metric: |Δf0| semitones and
     |Δrate| Hz at the join, carry vs control.
  2. **Identity:** ECAPA cosine between A and B per arm
     (`scripts/clone_speaker_similarity.py` embeddings). Carry must not sit
     measurably below control — continuation must not drift the voice.
  3. **QC:** engine Fast QC must pass every take (fail-closed already).
  4. **Cost:** B's wall time per arm (clone prefill overhead) from CLI timing.
- **Probe verdicts (pre-registered):**
  - **Signal:** mean |Δf0| at the join improves ≥ 25% in carry with rate no worse,
    ECAPA(carry) ≥ ECAPA(control) − 0.05, all QC pass → the mechanism graduates to a
    full experiment design (engine-integrated, knob-gated, §K soak, memory
    qualification, iOS posture decision).
  - **Null/negative:** anything less → recorded do-NOT for clone-ICL continuation;
    stage 2 falls back to parked until a different conditioning mechanism exists.

## Known risks the probe is designed to expose

- **Identity drift:** cloning your own output re-estimates the voice from 10 s of
  synthetic audio; custom-speaker identity may soften (ECAPA catches it).
- **Register lock-in vs continuity trade:** carry may inherit A's exact register
  (good at the join) at the cost of B's natural prosody range (delivery analyzer's
  within-take spread on B shows it).
- **Cost:** clone prefill on every continuation segment raises per-segment TTFC; the
  probe quantifies it before any product design.

## Out of scope for the probe (adoption-gate territory, listed so they are not lost)

- **Regeneration semantics:** carryover makes segment N depend on N−1's audio;
  single-segment regeneration must choose between replaying recorded conditioning
  (stable, possible joint mismatch), cascading (expensive), or context-free
  regeneration (simple, loses the benefit locally). A manifest v5 with per-segment
  conditioning evidence would be required.
- **Memory budgets:** the ICL prefix adds prompt/KV tokens; product adoption requires
  telemetry-v8 memory qualification on both platforms and an explicit iOS posture
  (default-off like speech-tokenizer residency is the expected starting point).
- **Custom/design prompt-shape work:** if clone-ICL continuation wins but softens
  identity, a speaker-conditioned variant (custom speaker token + acoustic prefix)
  would need real prompt-assembly design — engine territory with its own gates.

## Probe results (2026-08-01) — pre-registered signal NOT met; recorded do-NOT

Run: 4 seeds × (A + B-control + B-carry), macOS canonical M2, artifacts
`build/artifacts/macos/carryover-probe/20260801-224954` (local-only), all takes
engine-QC clean.

| metric (mean, 4 seeds) | control | carry | read |
| --- | --- | --- | --- |
| join \|Δf0\| (st, A-tail vs B-head) | 3.848 | 3.218 | −16.4%, **below the ≥25% gate** |
| join \|Δrate\| (Hz) | 1.083 | 0.500 | −54%, well under the no-worse bound |
| ECAPA A↔B cosine | 0.8301 | 0.8502 | identity not degraded |
| B wall seconds | 13.36 | 13.58 | prefill cost negligible at this length |

**Verdict: do-NOT for clone-ICL acoustic continuation as a join-quality fix.** The
result is mechanistically consistent with R3's neutral-stabilization finding: pacing
continuity responds strongly (−54% at joins here, −53% cross-seed there), but
pitch-register placement is set by early-token dynamics that neither sampling shaping
nor a 10-second aligned acoustic prefix constrains (−16%, under gate). Two
independent experiments now point at the same missing mechanism —
register/pitch-target conditioning — which is model-research territory, not an
inference-time lever this codebase can add. Stage 2 is **parked** with that single
unpark condition; the rate-side wins accumulate as evidence for the (also parked)
R3 rate-profile option, whose unpark trigger (b) explicitly references these
fixtures.

Probe tooling (`scripts/longform_carryover_probe.py`, exploratory-only, ECAPA phase
requires the `.venv` ML environment per `docs/reference/testing-runbook.md`) remains
standing for any future conditioning mechanism to re-run against the same
pre-registered gates.
