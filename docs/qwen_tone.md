---
status: active
owner: backend-mlx
summary: App-facing quick guide to tone and emotion control; the sourced qwen3-tts-prompting-guide wins on any disagreement.
sourceOfTruth:
  - Sources/QwenVoiceCore/EmotionPreset.swift
---
# Tone and Emotion in Vocello

_Last reviewed: 2026-06-11. Provenance pass 2026-08-02._

> **Where the sourced version lives.** [`reference/qwen3-tts-prompting-guide.md`](reference/qwen3-tts-prompting-guide.md)
> is the primary-source reference: it labels every claim `OFFICIAL` / `RESEARCH` / `MEASURED-HERE` /
> `COMMUNITY` / `UNVERIFIED` and cites upstream directly. This file stays as the app-facing quick
> guide. Where the two disagree, the prompting guide wins — several rules below were traced in
> August 2026 to no source at all, and are flagged inline.

> **Roster change (editor's note, 2026-08-04; tier note updated 2026-08-15).** The delivery
> preset roster changed after this guide was written: `excited` was folded into `happy` and
> `dramatic` dropped on 2026-08-03, and the user-facing intensity tiers were retired on
> 2026-08-02. The current roster is 8 presets, each shipping its per-preset measured-best tier
> (`EmotionPreset.shippedIntensity`): the `strong` anchor, except `happy` and `angry`, which ship
> their `normal` copy (DP-22 branch (a), maintainer call 2026-08-15). Preset references below
> predate that change; see
> [`reference/qwen3-tts-prompting-guide.md`](reference/qwen3-tts-prompting-guide.md) and
> [`reference/delivery-control-audit-2026-08.md`](reference/delivery-control-audit-2026-08.md)
> for the corrected record.

This guide is a supplemental prompt-writing reference for the shipped macOS app. It is supplemental and may lag shipped behavior — when in doubt, trust the sources listed below before this guide.

For current repo truth about app structure, workflows, or supported behavior, trust:

1. `README.md`
2. `CLAUDE.md` (repo guide: architecture, build, conventions)

## What the App Exposes

Vocello controls tone and emotion through natural-language instructions, not SSML and not explicit sampling sliders.

Current app behavior:

- **Custom Voice** uses one of the shipped speakers plus an optional delivery instruction prompt
- **Voice Design** has its own generation screen and prompt flow using a natural-language voice/design instruction
- **Voice Cloning** uses reference audio and can optionally use a transcript for better preparation quality, but it does not expose a separate instruction-only tone surface
- single generations produce a complete final take, and the app does not expose temperature or max-token controls
- **Neutral** is a real instructed preset since 2026-08-01 (`EmotionPreset.neutralPresetInstruction`), not an absent instruction — see the sourced guide's §6.3. Only the typed-synonym path ("neutral", "default") drops the instruction entirely. Custom Voice and Voice Design prompts use direct natural language rather than `Delivery style:` fields.

Useful instruction patterns:

- emotional delivery: `calm and reassuring`, `frustrated but controlled`, `nervous and unsure`
- vocal behavior: `gentle smile in the voice`, `sharp emphasis without shouting`, `breathy but clear`
- pacing and cadence: `slow, deliberate pace`, `quick but clear`, `measured pauses`
- character and timbre: `warm documentary narrator`, `dry late-night radio host`, `soft-spoken teacher`

## Practical Guidance

- Be specific: combine voice character, emotional state, pacing, and clarity in one instruction.
- Be multidimensional: combine **emotion + pace + pitch + timbre** rather than a single dimension — `bright energy and a slightly lifted pitch` beats `happy`. (Officially sourced: Alibaba's "be multi-dimensional, not one-dimensional". Volume and speed are scored dimensions too.)
- Keep requests concrete: `calm middle-aged narrator with steady pacing` works better than `make it better`. Measured adherence is highest for concrete acoustic wording and lowest for persona-only briefs ("like a detective") — describe the sound, not just the character.
- Prefer short, direct performance direction over one-word labels; Qwen3-TTS follows natural-language delivery instructions. 1–3 dense sentences is a reasonable target for a **voice description**; for a **delivery instruction** the official examples are three to nine words, so the sweet spot there is untested. Repeated intensifiers (`very, very deep`) add nothing, but a single one is fine — upstream's own examples are `Very happy.` and `Say it in a very angry and disappointed tone`.
- **Voice Design briefs especially: name the gender and a concrete pitch register.** Voice Design invents a brand-new voice each call (no fixed speaker), so an under-specified brief lets it sample a higher or different-gender voice — a gender-less `deep narrator` can come out high-pitched. Write `a deep, low-pitched male narrator, bass-resonant` rather than `deep narrator`.
- **Negative constraints are unverified, not officially endorsed** (corrected 2026-08-02 — the earlier "officially endorsed" claim had no source). The *symptom* is community-reported: high-arousal instructions like `very happy` can trigger literal laughter. The *remedy* — adding `but without laughing` / `no added sounds` — is what nothing supports, and the nearest published ablation found bare paralinguistic tags reduced adherence. The then-shipped Happy/Excited Strong presets carried the clause (Excited was retired 2026-08-03; the surviving Happy copy still carries it); whether it earns its place is an open experiment.
- Keep strong emotions intelligible: add constraints like `while keeping words clear`, `without shouting`, or `still understandable`.
- For whisper delivery, say `whisper` explicitly. Generic `soft and quiet` wording can produce soft-spoken delivery instead of an actual whisper.
- Phrase instructions as **descriptions, not requests**: a conversational instruction ("Could you read this like…") can leak a spoken "OK" acknowledgment into the audio.
- Write the instruction in **English or Chinese** regardless of the output language — those are the trained instruction languages; the spoken-text language is controlled separately (the Language picker / auto-detection).
- **Don't expect dialect or accent switching from instructions** — emotion and style follow, but `speak in a Sichuan dialect` yields standard Mandarin. Dialects come from the dialect speakers (Dylan — Beijing, Eric — Sichuan) or from cloning an accented reference.
- **Speakers carry baked-in delivery biases**: Ryan is inherently expressive and resists a flat newscast read; for neutral delivery start from a calmer voice (Aiden, Serena) instead of fighting the timbre with instructions.
- Iterate wording: instruction following is probabilistic, so small prompt changes can materially change the result.
- Use Voice Design when you want a reusable prompt-driven voice shape, and use Voice Cloning when you want a specific reference identity from audio. Cloned voices cannot take delivery instructions on the current checkpoints — the delivery must live in the reference clip. A single saved Voice Design take is usually not enough (measured 2026-08-04: three of four single-shot references failed to carry their emotion); use the curated design-then-clone bank pipeline instead ([emotion reference banks](reference/emotion-reference-banks.md)), which verifies each per-emotion reference before enrolling it.
- **Long scripts drift**: very long single generations tend to speed up and compress pauses toward the end. Break long material into paragraph-sized generations (each re-asserts the delivery instruction) for steadier pacing.

## Pauses in the Spoken Text

Qwen3-TTS does not parse SSML or explicit pause markers. Pauses come from the natural punctuation and line structure of the input:

- **Period** — sentence-end pause (longest within a paragraph).
- **Comma / semicolon / colon** — short pause.
- **Blank line** between paragraphs — paragraph-level pause.
- **Question mark / exclamation mark** — sentence-end pause with the matching prosody.

Things that are **not** reliable pause cues:

- Ellipsis (`...`) — read as text, not as a long pause.
- Hyphens or dashes — usually treated as continuation, not pause.
- Repeated commas or extra spaces — collapsed; they don't lengthen the pause.

If you need a longer beat, end the sentence with a period and start a new one. For an explicit paragraph break, add a blank line.

## Examples

Custom Voice:

> Calm, soothing, and reassuring, with smooth pacing and gentle confidence.

Custom Voice, strong emotion (historical example — this is the then-shipped Excited Strong preset copy; the Excited preset was retired 2026-08-03, so this survives only as a wording pattern, not current preset copy):

> Very excited and animated, energetic and anticipatory, with lively emphasis, controlled pacing, and clear pronunciation.

Custom Voice, whisper:

> Subtle audible whisper, close-mic and quiet, with gentle breath, hushed tone, and clear words.

Voice Design:

> A composed documentary narrator with a low, warm voice, deliberate pacing, crisp diction, and gentle emphasis on key phrases.

Voice Cloning support text:

> Use a clean 10–20 second reference clip and include the transcript if possible.

## Source References

- [Qwen3-TTS README](https://github.com/QwenLM/Qwen3-TTS/blob/main/README.md)
- [Qwen3-TTS Hugging Face model card](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice)
- [Qwen3-TTS Technical Report](https://arxiv.org/abs/2601.15621)

## Related Docs

- [`../README.md`](../README.md)
- [`../CLAUDE.md`](../CLAUDE.md) — repo architecture, build, and conventions
- [`reference/qwen3-tts-prompting-guide.md`](reference/qwen3-tts-prompting-guide.md) — the sourced prompting reference this file defers to
- `Sources/QwenVoiceCore/EmotionPreset.swift` — the shipped 8 preset instructions (roster cut from ten on 2026-08-03; the user-facing intensity control was retired 2026-08-02; every preset ships its per-preset measured-best tier — the `strong` anchor, except `happy`/`angry` at `normal` since 2026-08-15 — and both tiers survive for the delivery matrix harness) (single source for macOS + iOS + the CLI's `bench --delivery` cells); `Sources/QwenVoiceCore/GenerationSemantics.swift` assembles the Voice Design "Voice character / Delivery" framing.
