# Delivery fidelity and clone fidelity — autonomous diagnosis (2026-08-01)

> Answers the maintainer's two reported gaps with measured evidence, no human
> listening: (1) Custom-mode delivery presets "don't seem properly applied"
> (e.g. Aiden + Neutral producing takes all over the place); (2) cloned voices
> "don't always match the reference clip's tone/delivery". Method: the new
> layered verification harness — deterministic paired prosody deltas with a
> promoted per-preset delivery gate, cohort consistency checks, ECAPA speaker
> identity, clone prosody-fidelity distances, and an advisory SER emotion
> cross-check. All evidence is fixed-seed and machine-scored on the canonical
> Mac mini M2 8 GB floor with the 2026.07.26.1 artifacts.

## Evidence base

- **Paired preset matrix:** 7 seeds × 18 delivery cells (9 presets ×
  normal/strong) with same-seed neutral pairs, banked as committed records
  `delivery-cal-s1..s8` (126 delivery takes). Seed 20260802 is excluded: its
  `sad.strong` take reproducibly fails Fast QC with `dropout:excess2` (twice,
  identically) — finding F5.
- **Neutral cohorts:** 3 arms × 8 seeds of Aiden on the bench medium sentence
  (shipping expressive variation; consistent variation; expressive plus an
  explicit steadying instruction).
- **Clone lane:** 6 fixed-seed clone takes of the canonical fixture voice vs
  its reference clip, plus 2 different-speaker negative controls
  (`build/artifacts/macos/clone-fidelity/clone-fidelity-v1-20260731-231309`).

## Findings — delivery presets (Custom mode)

**F1. Presets do steer prosody, but reliability is preset- and
intensity-dependent.** Measured direction win-rates over 14 takes per preset:
angry (pitch +1.00, arousal +0.93), sad (arousal −0.86), happy (arousal
+0.86), fearful (arousal −0.86), whisper (pitch-variation −0.93) are strongly
directional; calm (−0.86 pitch) is solid; **surprised (0.64–0.71) and
dramatic (0.64) barely move prosody** — at normal intensity dramatic's median
pitch shift is actually negative. Strong intensity generally lands the
intended effect; normal intensity is where "not properly applied" lives
(e.g. excited.strong median pitch shift +0.2 st vs +1.3 st at normal —
whole-preset medians swing seed to seed).

**F2. Two seeded expectations were factually wrong and are now corrected by
data.** The model expresses *angry* by raising pitch (+3.2 st median, 100%
consistent) despite the instruction's "lower clipped tone", and *fearful* as
low-arousal (slower, more pauses, less pitch variation) rather than
shaky-variable. The delivery gate's expectations were recalibrated from the
banked matrix (required = ≥0.85 measured win-rate; magnitudes ≈ half the
median effect); dramatic and surprised carry direction-only supporting
expectations until the presets themselves improve.

**F3. The instruction-strength lever, not the pipeline, is the gap.** The
instruct turn demonstrably reaches the prompt (100%-consistent angry/whisper
effects prove the path), so weak presets are a prompt-engineering/product
question: dramatic and surprised instructions are candidates for rewriting
under the EmotionPreset canon, verified against the now-standing calibration
lane rather than by ear.

## Findings — Neutral wander (the Aiden complaint)

**F4. Neutral cross-seed delivery variance is real, quantified, and
by-construction.** The Neutral preset deliberately sends *no* instruct turn
(`DeliveryProfile.isNeutralInstruction` drops it), so nothing constrains
delivery across seeds. Across 8 seeds of identical text, shipping-default
neutral Aiden spans **2.70 semitones of median pitch and 1.97 Hz of speech
rate**. The `consistent` variation tier does not help across seeds (3.99 st /
2.2 Hz — it stabilizes within-request behavior only), and an explicit
steadying instruction narrows pitch spread ~21% (2.13 st) but worsens rate
spread (2.5 Hz) — a partial lever, not a fix. Real mitigation would need an
engine-level mechanism (e.g. delivery-conditioned sampling or a
neutral-specific sampling preset), which is future experiment territory, not
this block. The `neutral_consistency` bounds now sit just above this
measured baseline (4.5 st / 2.75 Hz) so the cohort gate flags regressions
beyond today's behavior instead of always warning.

**F5. One reproducible hard defect surfaced:** seed 20260802 × `sad.strong`
on the medium corpus sentence produces dropout audio that Fast QC correctly
rejects, identically on repeat. Kept as a pinned reproduction for future
engine-loop work; PASS-only publication kept it out of history.

## Findings — clone fidelity

**F6. Clone identity is strong; the tone complaint is occasional
expressiveness drift, not identity.** ECAPA cosine similarity for 6
fixed-seed takes vs the reference: **0.814–0.871** (median 0.847), against
0.103/0.390 for different-speaker negative controls — a wide measured margin
that validates the advisory bands (strong ≥ 0.60). Prosody fidelity: 5/6
takes inside all reference-distance bounds; one take exceeded the
expressiveness band (pitch-range delta > 4 st). SER cross-check: 5/6 takes
match the reference clip's top emotion. Verdict: the pipeline preserves the
speaker; per-take expressiveness occasionally overshoots, which the new lane
now measures per release instead of per ear.

## Advisory SER notes

The first candidate checkpoint (ehcalabres XLSR) silently loads a randomly
initialized classifier head via the standard API — predictions were garbage;
the loader now fails closed on missing checkpoint keys. The pinned
replacement (`firdhokk/…wav2vec2-large-xlsr-53`, Apache-2.0, revision
`611e6db8…`) behaves like a real advisory: sad→sad p=0.93, fearful.strong→
fearful p=0.99, and it independently corroborates F2 (angry.normal reads as
"happy" — bright, raised pitch). Aggregate preset agreement is 0.29 —
single-model SER on synthetic speech stays advisory-only, never a gate.
Measured peak RSS 2.4 GB, run strictly after generation per the 8 GB rule.

## Standing tooling (how to reproduce)

| Layer | Entry point |
| --- | --- |
| Paired preset matrix + canonical composed verdicts | `vocello bench --delivery <preset.intensity,…> --seed S` (sidecar `bench-prosody.json`, verdicts `bench-quality-composed.json`) |
| Per-preset expectations / cohort bounds / clone bounds | `scripts/prosody_profile.py` (schema v2, digest-chained) |
| Delivery verdict + neutral cohort | `scripts/delivery_quality_gate.py` (`--instructed/--neutral/--delivery`, `--cohort`) |
| Clone lane (identity + prosody + SER) | `.venv/bin/python3 scripts/clone_fidelity_lane.py --voice <saved-voice>` |
| SER advisory column | `.venv/bin/python3 scripts/emotion_advisory.py --sidecar … --outputs-dir …` |

## Recommendations

1. **Product:** rewrite the dramatic and surprised instructions (weakest
   measured presets) and re-verify with one calibration bench run; consider
   whether normal intensity should inherit stronger phrasing, since strong
   reliably lands.
2. **Engine (future experiment):** a neutral-stabilization mechanism if
   cross-seed neutral wander should shrink below the measured baseline;
   neither the variation tier nor instruction text achieves it today.
3. **Process:** the delivery gate, cohort check, and clone lane run on every
   future artifact/engine promotion; thresholds recalibrate from banked
   records, never by ear.
