# Product

## Register

product

## Users

Mac (and iPhone) power users who create voice content for their own projects — videos, audiobooks, accessibility narration, podcasting, personal work — and value privacy enough to want generation to happen on-device instead of through a cloud TTS service. They are comfortable with native macOS conventions, likely use other Apple-native pro tools (Final Cut, Logic, Notes), and expect a Mac app to behave like a Mac app: keyboard-first, sheet-based, system materials, no novelty chrome.

The hardware floor (any Apple Silicon Mac with 8 GB / iPhone 15 Pro) intentionally widens the audience past pro-only — hobbyists creating one voice clone for a side project sit on the same surface as someone batching narration for a series. The UI must read as "competent for both" without optimizing for either.

The job: bring text, leave with audio that sounds right, in seconds, without leaving the laptop.

## Product Purpose

Vocello is a local-first text-to-speech application that runs Qwen3-TTS / MLX models entirely on-device. Three generation modes share one chrome:

- **Built-in Voice** (internal mode id `custom`) — generate with a chosen preset speaker, delivery style, and intensity. “Speed”
  names the 4-bit model variant, not a delivery control.
- **Voice Design** — describe a voice in natural language; the model produces it.
- **Voice Cloning** — provide a 10–20 s reference clip (record it in-app or import a file; the transcript can auto-fill via on-device transcription); the model speaks the user's text in that voice.

Saved Voices, Generation History, and downloaded Models are first-class library surfaces, not afterthought tabs.

Success looks like: the user opens the app, types or pastes a script, picks a voice, hits Generate, and hears the result almost immediately. They never wait for a server, never see a credit meter, never re-explain their identity. They trust the file lives on their machine.

## Brand Personality

**Warm · Premium · Native.**

Apple-native craftsmanship with a warm golden brand color (Vocello gold). Local-first is framed as quiet luxury, not as a constraint or a privacy crusade. The product reads as confident without being loud — it doesn't market itself inside its own UI. Voice and tone:

- Microcopy is direct and unceremonial. Verbs over nouns. No celebration messages, no "Awesome!", no exclamation points.
- Empty states explain what to do next in one sentence and stop.
- Errors describe the cause and the fix. They never apologize, and they never mention "the system."
- The brand defers to the output. Chrome should never compete with the audio waveform, the player, or the user's own text.

## Anti-references

- **ElevenLabs and SaaS-TTS dashboards.** Cream / light backgrounds, dense sidebars with too many dropdowns, busy "studio" panels, oversized gradient CTAs, "Try a sample" prompts, credit-meter chrome. Vocello is not a cloud TTS competitor and must not look like one.
- **Generic dev-tool dark mode.** Neon-on-near-black terminal palette, monospace headlines, GitHub-shaped chrome, "DevTools" affect. The saturated category reflex for "serious tool" — Vocello's seriousness comes from craft, not from looking like a CLI.
- **Marketing-style hero shells inside the app.** Big headline + screenshot + gradient + "Get started" CTAs, scroll-driven sections. The app surface is not a landing page.
- **Desktop-studio shell with inspector + oversized hero chrome.** Do not propose reintroducing it under any name (workbench, console, inspector, console-pane, etc.).

## Design Principles

1. **Local-first as quiet luxury.** Privacy is the product, but it's communicated through speed, fidelity, and craft, never through trust badges or marketing copy. If the user has to be told the data is local, the chrome failed.
2. **Output is the hero.** The waveform, the player, the saved voice card, the just-generated row — those are the surfaces that earn attention. Chrome supports them.
3. **Native discipline before novelty.** SwiftUI defaults are the substrate; Liquid Glass is the layer that distinguishes Vocello on top of them. New patterns earn their place by working with system materials, not by replacing them.
4. **Stability-led polish.** Cross-mode chrome stays coherent so users never relearn navigation. Layout changes ship rarely; refinements (color, weight, rhythm, copy) ship often.
5. **Warm without volume.** The Vocello gold is an accent, never the wallpaper. Mode colors (Voice Design lavender, Voice Cloning terracotta) are whisper-tinted in glass and backdrops — the user feels mode peripherally without being pushed into it.

## Accessibility & Inclusion

- **Target: WCAG 2.1 AA** on contrast, focus indication, keyboard navigation, and labeling. macOS Accessibility APIs (NSAccessibility / VoiceOver) considered first-class, not retrofit.
- **VoiceOver labels and hints on every interactive control.** Existing `accessibilityIdentifier` values (e.g. `voicesRow_*`, `voicesEnroll_*`) are load-bearing for the test harness and must remain stable as UI evolves.
- **Dynamic Type / Larger Text respected.** Layouts hold at the largest accessibility text size; truncation is allowed, but never to the point of hiding the primary action.
- **Reduce Motion honored.** All animation is gated through `appAnimation` / `AppLaunchConfiguration.performAnimated`, which defer to the system setting.
- **Reduce Transparency honored.** Liquid Glass surfaces fall back to `legacyBody` solid fills when the user has reduced transparency, so the chrome never becomes unreadable.
- **No color-only signal.** Mode color always pairs with an icon, label, or position cue. Quality warnings pair an orange triangle with a written headline.
- **Sound-aware UI.** Because the product is audio-first, never gate critical state behind audio cues alone — every audible event has a visible counterpart (caption, badge, progress, etc.).
