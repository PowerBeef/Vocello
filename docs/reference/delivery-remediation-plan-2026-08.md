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

**Intensity-ladder gate (added 2026-08-01, maintainer-approved).** The
calibration matrix showed the shipped intensity ladder is non-monotone for
about half the presets (angry, excited, surprised, whisper produce a weaker
or opposite effect at `strong` than at `normal`), and `subtle` has never been
measured. R1 therefore:

1. **Measures the subtle baseline first** — one calibration pass over the 9
   `.subtle` cells with the current instructions, completing the three-tier
   picture before any rewrite.
2. **Extends the rewrite scope** beyond dramatic/surprised to the inverted
   `strong` phrasings (angry, excited, whisper) and the weak `normal`
   phrasings (happy, excited).
3. **Adds a pre-registered ladder gate:** for each rewritten preset,
   `strong ≥ normal ≥ subtle` on its required features in ≥75% of seeds.
4. **Collapse decision rule:** if the best candidates cannot make the ladder
   monotone for a clear majority of presets, the intensity tiers are
   collapsed to a single well-tuned instruction per preset (UI + draft-state
   change, its own follow-up) — the removal question is answered by this
   measured outcome, not by taste.

**Acceptance (pre-registered):** rewritten presets reach ≥0.85 direction
win-rate on at least one required feature across ≥7 seeds AND pass the
ladder gate; unchanged presets keep their banked data (per-preset
instructions are independent, so no cross-preset re-run is required); all
takes Fast-QC clean; fixed-seed neutral pairs byte-identical (instruction
text does not touch the neutral path).

**Non-goals:** angry keeps its measured pitch-raising behavior — the
calibrated gate already encodes it; only its `strong` tier's inverted dose
is in scope. UI preset labels/descriptions are unchanged; sad is untouched
so the pinned seed-20260802 `sad.strong` reproduction stays valid for R2a.

**R1 OUTCOME (executed 2026-08-01) — ACCEPTED, tiers kept.** Two candidate
iterations (8 rewritten strings across 6 presets; whisper.strong and
surprised.strong re-iterated once) validated over 7 seeds
(delivery-r1c1/r1c2/r1final records; subtle baseline delivery-cal-subtle-s*):

- Every rewritten preset cleared the ≥0.85 acceptance bar: angry.strong
  0.86/0.86 (inversion cured, pitch var. 6.7 → 13.2), excited.strong
  0.86/0.86 (3.2 → 9.75), dramatic.normal 0.86/0.86 (pitch var. +0.4 → +5.3,
  finally a real preset), happy.normal arousal 0.86, surprised 0.86 on pitch
  shift at both tiers, whisper.strong 1.00/1.00 (flattening −0.5 → −10.8
  after the c2 re-iteration; the c1 "slow" phrasing had regressed it).
  Delivery-gate warn-rates fell from 0.86–1.00 to 0.29–0.57.
- **Ladder verdict:** subtle→normal is monotone in ≥75% of seeds for 5/6
  rewritten presets; normal→strong saturates at parity for the hot emotions
  (angry, excited, surprised) — no inverted cells remain anywhere. Whisper
  saturates at the floor from `subtle` up. Per the collapse rule this is
  neither a clean full-chain pass nor the harmful inversion that motivated
  removal: **recommendation — keep the three tiers** (subtle is a real
  lighter dose; strong guarantees ceiling), with the normal≈strong ceiling
  for hot emotions documented rather than hidden. Collapse remains available
  as its own follow-up if the maintainer prefers one honest control.
- Gate expectations re-derived: dramatic and surprised promoted back to
  magnitude-bearing required features on the shipping text.

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

**R2 OUTCOME (executed 2026-08-01).**

- **R2a — no engine fix warranted.** Incidence 1/11 seeds (only the pinned
  20260802; ten fresh seeds pass clean), fourth byte-identical reproduction.
  Root cause localized: the pipeline is healthy (all 20 chunks produced,
  memory/thermal nominal) — the finalized audio itself carries three interior
  silence gaps at this seed, i.e. `sad.strong`'s pause-heavy delivery landing
  on the wrong side of the Fast-QC pause-vs-dropout boundary. Fail-closed
  behavior already protects users. Banked scan: 0 QC flags across all 2,048
  published takes. Recorded option if incidence ever grows: sharpen the
  dropout classifier's edge discrimination so breathy pauses stop counting.
- **R2b — no mitigation promoted; lane monitoring stands.** Pooled drift
  incidence ≤12.5%: 1/8 expressiveness flags on the human-reference fixture
  voice, 0/8 on a genuinely distinct male-register fixture ("R2b Ryan
  Fixture", enrolled from a fresh self-generated reference after the saved
  "Warm storyteller" voice proved to be a duplicate enrollment of the same
  fixture clip — identical reference digest; fixed-seed determinism made the
  duplicate visible as byte-identical takes). ECAPA separation re-confirmed:
  clones 0.81–0.88 vs cross-speaker controls 0.02–0.39.

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

**R3 OUTCOME (executed 2026-08-01) — keep-gate NOT met; nothing promoted.**
The experiment needed no new code: the registered `QWENVOICE_TALKER_TEMP` /
`QWENVOICE_TALKER_TOPP` knobs already provide request-local sampling
overrides behind the debug gate. Four 8-seed Aiden neutral cohorts on the
fixed medium sentence (baseline arms banked earlier the same day):

| arm | pitch spread (st) | rate spread (Hz) | monotone/flat flags |
| --- | --- | --- | --- |
| shipping default (expressive) | 2.70 | 1.97 | 0 |
| temp 0.5 / topP 0.8 | 2.15 | 1.20 | 0 |
| temp 0.3 / topP 0.7 | 2.43 | 1.01 | 0 |
| steadying instruction + temp 0.5/0.8 | 2.37 | **0.92** | 0 |

Rate wander is fixable (−53% at best, comfortably under the 1.5 Hz bound,
with zero over-stabilization flags). **Pitch-register wander is not**: it
floors at ~2.1–2.4 st against the ≤1.8 st bound in every treatment arm, is
non-monotone in temperature, and the levers do not stack — the cross-seed
register is chosen by early-token mode structure that instruction text and
sampling shaping both fail to constrain. Recorded do-NOT: do not ship a
neutral sampling profile as a wander fix — it purchases rate stability only.
A genuine fix would need a different mechanism (register/pitch-target
conditioning), which is model-research territory beyond a sampling knob.
Maintainer options if neutral variance should still shrink: accept the
partial rate-only win as a default (quantified above), or park until a
conditioning-level mechanism exists. Nothing auto-adopted.

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

**R4 OUTCOME (executed 2026-08-01):** items 1 and 2 landed
(`benchmarking-procedure.md` §4.6b promotion fidelity lanes;
`testing-runbook.md` ML-backed QA analyzers section with the 8 GB
sequential rule and pinned model identities). Item 3 skipped per the plan's
allowance.

## R5 — Neutral becomes a real preset (maintainer-directed, 2026-08-01)

**Decision:** treat Neutral like every other preset — a slightly monotone,
emotion-free delivery target — instead of the absence of an instruction
(the root cause of finding F4's unconstrained wander). Adopted text
(`EmotionPreset.neutralPresetInstruction`): "Speak in an even, level tone,
slightly monotone, with steady measured pacing and no noticeable emotion;
plain and matter-of-fact throughout."

**Scope:** the preset catalog (all three neutral tiers, tier-less UI
semantics preserved), the macOS draft defaults and both platforms'
long-form nil-fallbacks now carry the instructed neutral; typed neutral
synonyms in custom text still drop; **programmatic/CLI requests with no
delivery style remain uninstructed** (bench plain takes keep historical
fixed-seed comparability — proven byte-identical pre/post). The bench
accepts `neutral` delivery cells as first-class paired measurements and the
profile carries a neutral expectation (steadied direction, supporting).

**Text selection (three candidates, 8-seed cohorts each):** stronger
monotone phrasing flattens more but destabilizes the cross-seed register
("flat, even monotone": f0-std −15% but 4.8 st spread, cohort flag), while
soft steadying stabilizes register without flattening (+13% f0-std). The
adopted text is the balanced middle: f0-std −5%, best rate spread of any
arm (1.56 Hz vs 1.97 plain), zero prosody/cohort flags, register spread
2.98 st inside the 4.5 bound. Cross-seed register spread itself remains the
R3-documented limitation no instruction fixes.

**Proof:** plain-path invariance byte-identical at fixed seed; the first
neutral bench cell composes canonical depth and passes its delivery gate
(arousal −1.21 vs plain, record `macos-engine-20260801-051412-c02b8396`).
iOS device acceptance rides the Tier-2 window; the Neutral preset now
counts as a meaningful delivery wherever `isMeaningful` gates behavior.

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
