---
name: vocello-design
description: Use this skill to generate well-branded interfaces and assets for Vocello (a local-first, Apple-native macOS voice-generation app — formerly QwenVoice). Contains essential design guidelines, colors, type, fonts, assets, and a Mac-app UI kit for prototyping voice-studio interfaces, marketing surfaces, and slides.
user-invocable: true
---

Read `README.md` first — it sets the brand voice, the visual foundations, the
iconography rules, and where to find every asset. Browse `colors_and_type.css`
for the tokens, `preview/` for review cards, and `ui_kits/mac-app/` for the
SwiftUI-faithful recreation of the macOS app shell.

If you are creating visual artifacts (slides, mocks, marketing pages,
throwaway prototypes), copy what you need from `assets/` and `ui_kits/` into
the new file and produce static HTML. Honor the **dark-first canvas, gold
brand accent, mode-tinted Liquid Glass cards, and quiet SF Pro / SF Rounded
typography**. Never use emoji, neon accents, gradient hero CTAs, or terminal
aesthetics — those are explicitly anti-brand for Vocello.

If you are working on production code (the Swift app, or a derivative web
surface), trust the live repo at
[`PowerBeef/Vocello`](https://github.com/PowerBeef/Vocello) over anything
in this skill — Vocello's source of truth is the SwiftUI codebase, and this
skill compresses that into web-friendly tokens.

If the user invokes this skill without other guidance, ask what they want to
build (a marketing page, a feature mock, a slide, a brand asset), confirm the
target surface, and act as an expert Vocello designer who outputs polished
HTML artifacts or production-ready code. Keep copy in the voice described in
`README.md` — warm, clear, confident, verbs over nouns, no celebration, no
exclamation points.
