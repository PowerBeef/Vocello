---
status: active
owner: backend-mlx
summary: The design-then-clone workflow — build curated emotion reference banks with the pipeline script, how curation scores and honestly refuses candidates, and how banks present as personas with a delivery choice in both apps.
sourceOfTruth:
  - scripts/build_emotion_reference_bank.py
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
> Decision record: [`delivery-control-audit-2026-08.md`](delivery-control-audit-2026-08.md)
> (F8/R3) and `docs/development-progress.md` findings 13–15.

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

```sh
.venv/bin/python3 scripts/build_emotion_reference_bank.py build \
    --persona "Warm Narrator" \
    --brief "A warm, calm middle-aged male narrator with a clear, measured pace." \
    --work-dir "$HOME/Library/Application Support/QwenVoice-Debug/emotion-banks/warm-narrator"
```

Two strictly ordered phases (8 GB rule — the engine and the ML scorers never
run concurrently):

1. **Generate.** A neutral anchor take plus N candidates per emotion
   (default 4 × happy/sad/angry/whisper), same brief, same neutral-content
   transcript (~20 s — an emotional transcript would leak semantics into the
   conditioning), distinct fixed seeds, streaming (matches the app's chunk
   path; also the route that stayed correct while CM-7 — fixed 2026-08-04 —
   made `--no-stream` publish nothing). Audio QC is fail-closed inside the
   engine; a QC casualty
   costs one candidate, never the build.
2. **Score and select.** Per candidate: the pinned SER advisory
   (`scripts/emotion_advisory.py` checkpoint), ECAPA identity cosine against
   the anchor (`scripts/clone_speaker_similarity.py` backend), and prosody
   deltas versus the anchor. Eligibility is the emotion criterion — SER top-1
   agreement, or for whisper (which abstains from SER) a voiced-fraction drop
   of at least 0.05 against the anchor. Among eligible candidates the winner
   is the one **nearest the anchor in speaker identity**, never the most
   extreme take: overshoot and identity drift are the documented
   reference-bank failure modes, and each VoiceDesign call re-invents the
   voice, so identity cohesion across the bank must be selected for, not
   assumed.

Winners and the anchor are enrolled (replace-on-rebuild), and a
`bank-manifest.json` records every candidate's scores, the selection reasons,
and the pinned scorer identities so a selection can be re-litigated. An
emotion with no eligible candidate is reported loudly and left out — a partial
bank is honest; a padded one is not.

## Advisory posture

SER agreement and ECAPA cosine remain **advisory** instruments: never CI,
never a packaging input, never benchmark history. The builder uses them the
one way the audit's judge review endorsed — ranking our own candidates against
each other under a pinned model identity — and everything it decides is
recorded in the manifest. Absolute SER rates on synthesized speech stay
uninterpretable; relative comparisons within one build are the signal.

## Known limits

- Banks are **designed personas**. Building an emotion bank for a
  user-recorded voice would need the user to record emotional reference clips
  of themselves; the pipeline scores and enrolls such clips fine, but nothing
  generates them.
- The reference transcript is required (in-context conditioning). Both apps
  now say so: a reference without a transcript clones identity only, and the
  clone readiness line and the iOS save-voice sheet state it plainly.
- Emotion in the reference competes with identity stability: the selection
  trades expressiveness for anchor similarity by design. If an emotion keeps
  failing curation, raise `--candidates` before touching the criterion.
- Whisper is the hard case: the first real build (Warm Narrator, 2026-08-04)
  produced no eligible whisper — its candidates measured *more* voiced than
  the anchor, meaning VoiceDesign rendered soft-but-voiced speech rather than
  whisper phonation, and the voiced-fraction criterion also entangles pause
  structure (its denominator is the whole take). A breathiness criterion
  (HNR/CPP deltas from the analyzer's voice-quality block) is the recorded
  follow-up before whisper joins a bank.
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
