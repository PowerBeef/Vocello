# Vocello Website Product Context

## Register
Brand

## Product Purpose
Vocello is a local-first Mac voice studio for Apple Silicon. The website exists to help creators, indie developers, and Mac-native tool users understand the product quickly, trust the local generation model, hear the shape of the workflows, and download the current Vocello stable release.

## Audience
- Mac users who care about privacy, local software, and native craft.
- Creators who need spoken lines without a cloud subscription or usage meter.
- Open-source users who want to inspect releases, model requirements, and underlying technology.

## Brand Voice
Warm, clear, confident, and human. Vocello explains local AI generation plainly. It should feel premium and private, not like a SaaS dashboard or an AI hype page.

## Copy Rules
- Say local, not offline or on-device, unless the technical distinction matters.
- Say generate, voice, script, Voice brief, Speed, Quality, Saved Voices, Generation History, and Model Downloads consistently.
- Avoid celebration copy, emoji, hype claims, and first-person plural.
- Use sentence case. Reserve all caps for tiny labels only when they are truly needed.
- Do not use em dashes in visible copy.
- Keep public model messaging on the active 1.7B surface: Speed is 1.7B 4-bit, Quality is 1.7B 8-bit. The 0.6B variant is ruled out (2026-07-02 maintainer decision — Voice Design requires 1.7B); never mention it in public copy.
- Do not publish third-party Vocello timing or clone-prompt performance claims unless they have been reproduced locally with the maintained QwenVoice benchmark harness.
- Describe Voice Cloning as strongest when a Saved Voice is transcript-backed and can reuse a prepared Qwen3 clone prompt. Transcriptless or audio-only references are supported as lower-guidance fallbacks, not errors.
- For transcript auto-fill, say "transcribe locally" or "local transcription," following the local-not-on-device rule. Avoid bare "speech recognition" (too broad) and avoid naming Siri in copy (an Apple system detail; the app handles setup guidance in context).

## Strategic Principles
- Privacy is the architecture, not a badge.
- The Mac app is the hero. Product screenshots and concrete workflows should carry trust.
- The page should feel calm, polished, and Apple-native, with quiet motion and no decorative excess.
- The primary CTA is Vocello 2.2.2 for macOS 26 and Apple Silicon (stable). QwenVoice 1.2.3 remains the stable fallback for macOS 15, and the iPhone app is a public TestFlight beta with its own visible entry point.
- Performance claims cite the canonical Mac mini M2 (8 GB) and trace to tracked records in benchmarks/HISTORY.md; never quote a number the repository cannot reproduce.
- The site should acknowledge the QwenVoice rebrand quietly (inline "formerly QwenVoice" by the wordmark, the v1.2.3 fallback line, and the GitHub repo name). It is not a hero moment.
