---
status: active
owner: backend-mlx
reviewed: 2026-10-01
summary: The design-then-clone workflow — what a curated emotion reference bank is, how curation selects and honestly refuses candidates, and how banks present as personas with a delivery choice in both apps.
sourceOfTruth:
  - Sources/QwenVoiceCore/VoiceBankCatalog.swift
---
# Emotion reference banks (design-then-clone, curated)

> The delivery mechanism the 2026-08-04 calibration session proved out: emotion
> travels through the clone path's in-context reference conditioning, not
> through instruction text — the session's listener heard anger *only* through
> a clone-transfer clip (0.667 recall vs 0/11 for the instructed preset). The
> same session showed where naive banks fail: three of four single-shot
> VoiceDesign references never audibly carried their emotion, so their clones
> read as neutral. The lossy hop is instruct→reference; curation closes it.
> Decision record: the August 2026 delivery-control audit (F8/R3), now in git history.

## What a bank is

A **persona** (one VoiceDesign brief) plus a set of curated, per-emotion
reference clips of that persona, each enrolled as an ordinary saved voice:

- `Warm Narrator` — the neutral anchor (the persona's base voice)
- `Warm Narrator (Angry)`, `Warm Narrator (Sad)`, … — emotion references

Because bank entries are plain saved voices with transcripts, **every existing
clone surface uses them today with no engine changes**: pick the entry that
carries the delivery you want, write the line, generate. The clone request
machinery already conditions on the reference clip's full codec-token sequence
(in-context mode — the transcript is what unlocks it), so the entry's pacing
and emotion carry into the take.

## Building a bank

The bank builder script and its scorers were retired with the v1 audio QC stack on 2026-10-01.
Existing banks are ordinary saved voices and keep working. The curation method stays the reference
for any rebuild, which scores with the QC v2 speaker and pitch runners ([`qc.md`](qc.md)):

1. **Generate.** A neutral anchor take plus several candidates per emotion from one VoiceDesign
   brief, with a neutral-content transcript (about 20 s; an emotional transcript would leak
   semantics into the conditioning) and distinct fixed seeds. Mandatory audio QC stays fail-closed
   inside the engine; a QC casualty costs one candidate, never the bank.
2. **Score and select, after the generator exits.** Each candidate's speaker identity against the
   anchor, and its paired delivery deltas against the neutral anchor. Among the candidates that
   carry the emotion, the winner is the one **nearest the anchor in speaker identity**, never the
   most extreme take: overshoot and identity drift are the documented reference-bank failure
   modes, and each VoiceDesign call re-invents the voice, so identity cohesion across the bank must
   be selected for, not assumed.

Winners and the anchor are enrolled, and a manifest records every candidate's scores and the
selection reasons so a selection can be re-litigated. An emotion with no eligible candidate is
reported and left out: a partial bank is honest; a padded one is not. These scores rank our own
candidates against each other; they are never CI, a packaging input or benchmark history.

## Known limits

- Banks are **designed personas**. Building an emotion bank for a
  user-recorded voice would need the user to record emotional reference clips
  of themselves; such clips enroll as ordinary saved voices, but nothing
  generates them.
- The reference transcript is required (in-context conditioning). Both apps
  now say so: a reference without a transcript clones identity only, and the
  clone readiness line and the iOS save-voice sheet state it plainly.
- Emotion in the reference competes with identity stability: the selection
  trades expressiveness for anchor similarity by design. If an emotion keeps
  failing curation, generate more candidates before touching the criterion.
- Whisper is the hard case: the first real build (Warm Narrator, 2026-08-04)
  produced no eligible whisper — its candidates measured *more* voiced than
  the anchor, meaning VoiceDesign rendered soft-but-voiced speech rather than
  whisper phonation, and the voiced-fraction criterion also entangles pause
  structure (its denominator is the whole take). The breathiness criterion
  prototype (DP-17, measured 2026-08-04 on those same candidates) sharpened
  the diagnosis: whisper candidates run *more harmonic* than the anchor
  (ΔHNR +1.0..+1.4 dB) while sad shows the bank's most negative deltas — the
  HNR/CPP axis works as an instrument, but no criterion can rescue candidates
  that contain no breathiness. The registered recipe exploration (DP-17,
  closed 2026-08-04) then exhausted the VoiceDesign channel: six
  brief/instruction variants all produced candidates MORE harmonic than the
  anchor, so this checkpoint's design channel cannot render whisper phonation
  no matter where the request lives, and a bank honestly has no whisper
  entry. The one remaining path is cloning a genuinely whispered human
  reference (record a 10-20 s whispered clip, enroll it, judge it with the
  validated HNR/CPP-delta criterion); any such lane also needs a
  whisper-aware audio-QC posture first, because the fast QC's dropout
  detector fails low-energy breathy takes before they reach scoring.
- Both apps present a bank as one persona with a delivery choice (DP-16,
  2026-08-04). Grouping is resolved from the naming convention alone by
  `VoiceBankCatalog` in QwenVoiceCore — a base-named voice plus at least one
  "(Suffix)" sibling whose suffix matches a live preset; anything else stays
  a standalone voice. On macOS the clone source picker collapses members to
  one "· voice bank" row and adds a Delivery menu
  (`voiceCloning_bankDeliveryPicker`); on iOS the clone composer gains a
  Delivery chip (`studioChip_bankDelivery`) with a member sheet, while the
  Voices library and reference sheet keep every member listed (each has its
  own preview-worthy clip) under truthful "Voice bank · <Delivery>" captions.
  Every selection resolves to a concrete member voice through the ordinary
  saved-voice path — the bank layer owns no clone state.
