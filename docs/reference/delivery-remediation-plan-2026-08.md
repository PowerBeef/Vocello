# Delivery/clone fidelity remediation plan (2026-08)

> Follow-up to [`delivery-fidelity-report-2026-08-01.md`](delivery-fidelity-report-2026-08-01.md)
> (findings F1–F6) and OPTIMIZATION.md §P. Each track carries a pre-registered
> acceptance gate measured by the standing harness — no listening verdicts.
> Ordered by yield-per-cost; R1 and R2 are ungated and phone-free, R3 is a
> gated engine experiment, R4 is process hardening. No release is implied;
> preset-instruction changes reach iOS through shared `QwenVoiceCore` and ride
> the existing Tier-2 device-acceptance window.

## R1 — Preset instruction remediation (text-only, highest yield) [F1/F3]

**Target:** the two measurably weak presets — **dramatic** (0.64 win-rate,
negative median pitch shift at normal) and **surprised** (0.64–0.71) — plus a
normal-intensity strengthening pass where strong reliably lands but normal
does not (excited, happy).

**Method:** rewrite the instruction strings in
`Sources/QwenVoiceCore/EmotionPreset.swift` under the existing canon
(imperative verbs, emotion + pace + pitch + timbre, negative constraints,
≤500 chars). Up to three candidate phrasings per preset, each verified by one
paired calibration bench run (`vocello bench --delivery`, fixed seeds from the
banked ladder, ~7 min per iteration); adopt the best. The delivery gate's
expectations for the rewritten presets are then re-derived from the winning
candidate's distributions and promoted from direction-only back to
magnitude-bearing required features.

**Acceptance (pre-registered):** rewritten presets reach ≥0.85 direction
win-rate on at least one required feature across ≥7 seeds; no other preset's
win-rates regress; all takes Fast-QC clean; fixed-seed neutral pairs
byte-identical (instruction text does not touch the neutral path).

**Non-goals:** angry keeps its measured pitch-raising behavior — the
calibrated gate already encodes it; its instruction text is only touched if a
rewrite is otherwise happening. UI preset labels/descriptions are unchanged.

## R2 — Defect diagnosis sweeps (evidence before fixes) [F5/F6]

**R2a — `sad.strong` dropout (seed 20260802).** Reproduce under
`QWENVOICE_DEBUG` with chunk-timeline capture; localize the dropout (token
loop silence run vs codec chunk boundary vs assembler). Then measure
incidence: a 10-seed `sad.strong` sweep plus a scan of all banked QC warnings
for dropout frequency by preset. Output: a root-cause note and a go/no-go on
an engine fix (any engine-loop change inherits the §K 12-seed soak rule).
The pinned reproduction stays the regression test either way.

**R2b — clone expressiveness drift incidence.** The 1-of-6 overshoot may be
noise. Run the clone-fidelity lane at scale: 2–3 saved voices × 8 fixed
seeds (plus negative controls). If drift incidence is ≥ ~20% on any voice,
candidate mitigations enter R3 scope (clone-mode default variation, or a
reference-conditioned expressiveness constraint); below that, the per-release
lane monitoring stands as the remedy.

**Cost:** ~30–40 min machine time total; no phone; no code changes.

## R3 — Neutral stabilization experiment (engine, knob-gated) [F4]

**Hypothesis:** a neutral-specific sampling preset (applied only when no
instruct turn is present — e.g. reduced talker temperature/top-p) shrinks
cross-seed delivery wander without flattening prosody within a take.

**Method:** registered debug knob (`config/runtime-debug-knobs.json`, inert
without `QWENVOICE_DEBUG`) selecting the neutral sampling profile;
request-local per Algorithm v2 (no process-global sampling state). Compare
8-seed Aiden neutral cohorts knob-off vs knob-on (the banked baseline arms
are the control), plus the full §K 12-seed fixed-seed QC soak required of
every engine-loop change.

**Keep-gate (pre-registered):** cohort pitch spread ≤1.8 st (~33% under the
2.70 st baseline) AND rate spread ≤1.5 Hz, with 12/12 soak clean, no
increase in prosody-gate monotone/flat flag rates (the failure mode of
over-stabilizing), and warm RTF unchanged. Promotion to default-on is a
separate maintainer decision with its own fixed-seed A/B, because it changes
the shipping neutral sound.

**Fallback decision point:** if the sampling lever under-delivers, the
explicit-steadying-instruction default (arm C: pitch −21%, rate worse) is the
remaining product option — maintainer call, not auto-adopted.

**Standing do-NOTs:** no process-global sampling override, no new public
mutation surface, sampling changes ship only on deterministic-QC wins.

## R4 — Process and tooling hardening (riders)

1. **Promotion battery wiring (docs/policy):** add the delivery gate, neutral
   cohort check, and clone-fidelity lane to the engine/artifact promotion
   checklist in `docs/reference/benchmarking-procedure.md` so every future
   promotion runs them by default.
2. **ML QA environment note:** document the one-time `.venv` install
   (torch/transformers/speechbrain), the pinned model revisions, and the
   8 GB sequential-only rule in `docs/reference/testing-runbook.md`.
3. **Optional:** an `--advisory` flag on the bench delivery lane that invokes
   the SER column automatically after generation exits; skip freely.

## Sequencing and dependencies

R1 → R2a/R2b (any order, all phone-free) → R3. R2b's outcome can append to
R3's scope. R1's re-derived expectations land before R3 so the neutral
experiment's prosody-gate control uses final thresholds. iOS device
acceptance for R1's instruction changes rides the existing Tier-2 phone
window (no new device dependency). Machine-time budget: R1 ≤ ~30 min,
R2 ≤ ~40 min, R3 ≈ 1.5–2 h including the soak — all idle-Mac lanes,
generation never concurrent with ML analysis.

## Verification (every track)

Deterministic suites (`check_project_inputs.sh` full tier when `scripts/` or
`config/` change, core tests for Swift changes, both foundation compiles),
PASS-only publication for any banked evidence, fixed-seed comparisons for
anything quality-affecting, contract-token/narrative sync in the same change
where applicable, and OPTIMIZATION.md records numbers for kept AND declined
outcomes.
