# AGENTS.md — Vocello website

This file adds website-specific guidance to the root `../AGENTS.md`. The website is a React/Vite
marketing surface deployed by Vercel with `website/` as the project root. It is a non-native zone:
do not run Swift, iOS, macOS, Xcode, or native-app UI workflows for website-only changes.

## Commands

```sh
npm --prefix website run dev      # localhost:5173
npm --prefix website run lint     # source, metadata, accessibility, copy contract
npm --prefix website test         # Node contract fixtures + rendered contract
npm --prefix website run build    # client + SSR + prerender -> website/dist/
npm --prefix website run check    # lint + test + build
npm --prefix website run preview  # serve production build
```

Inside `website/`, omit `--prefix website`. `npm run check` is the final deterministic verdict.
The parent CI uses the Node/npm identities in `../config/toolchain.json`. Client and transient SSR
build outputs are generated; do not hand-edit them.

## Tool routing

- Read `PRODUCT.md` and `DESIGN.md` before visual or copy work.
- Use current primary React/Vite/library documentation; Context7 may assist when callable.
- Use `browser:control-in-app-browser` against the local dev or preview server for visual,
  responsive, interactive, and accessibility inspection. Browser evidence supplements rather
  than replaces `npm run check`.
- Use Chrome only when existing signed-in browser state is explicitly needed.
- Image generation is optional and only appropriate when the user requests new bitmap artwork.
- Never use computer-use, Xcode, Simulator, or native UI automation to validate the site.

## Architecture

`src/App.jsx` is a thin page composer. Keep content in the existing boundaries:

- `src/sections/`: page sections in render order.
- `src/components/Icon.jsx`: shared SVG vocabulary and deterministic waveform-bar generator.
- `src/components/Waveform.jsx`: Listen-row waveform primitive.
- `src/data/workflows.js`: the three workflow bands.
- `src/data/samples.js`: samples, delivery labels, and colors.
- `src/data/credits.js`: technology, GitHub, release, and TestFlight URLs.
- `src/site.css` and `src/tokens.css`: global styling and design tokens. Do not add CSS modules or
  styled-component systems without an explicit redesign request.

`App.jsx` mounts cookieless Vercel Analytics and owns scroll reveal, including immediate reveal for
anchor jumps. The privacy page must continue to disclose website analytics.

### Responsive layout

- Below 1100 px, the hero stacks copy before the Mac window.
- Below 900 px, bands, samples, specs, and CTA layouts stack; nav links hide and content centers.
- Below 600 px, padding and CTA sizing tighten and the former-name clarification hides.

Use `grid-template-columns: minmax(0, 1fr)` for narrow single-column grids. A bare `1fr` allows
intrinsic-width children such as max-content point lists to overflow.

## Content accuracy

Existing copy is not evidence. Verify every product claim against the parent repository:

| Claim | Authority |
| --- | --- |
| Release, beta status, platform support, minimum hardware | `../config/public-product-facts.json` and `../project.yml` |
| Models, variants, speakers, languages, revisions | `../Sources/Resources/qwenvoice_contract.json` and the complete production model catalog |
| Delivery presets and measured-best tiers | `../Sources/QwenVoiceCore/EmotionPreset.swift` |
| Canonical performance hardware | `../benchmarks/hardware-profiles.json` |
| Performance statements | compatible clean records under `../benchmarks/runs/` and generated `../benchmarks/HISTORY.md` |
| Architecture, privacy, distribution | `../AGENTS.md`, `../docs/ARCHITECTURE.md`, and machine-readable contracts |

Voice Cloning has no controllable delivery. Do not imply emotion or intensity controls on that
engine path. Keep public language aligned with `../config/public-product-facts.json`; do not infer
availability from an old page or release note.

## Brand and copy rules

`PRODUCT.md` owns brand voice and `DESIGN.md` owns visual constraints.

- Say *local*, not *offline* or *on-device*, unless the technical distinction matters.
- Use sentence case. All caps are reserved for tiny labels.
- Visible copy contains no em dash character. Use commas, colons, semicolons, periods, or
  parentheses. The website contract enforces this.
- No emoji, celebration copy, hype, unsupported superlatives, or first-person-plural voice.
- No gradient text, decorative glassmorphism, repetitive identical-card grids, repeated uppercase
  eyebrow scaffolding, or card side stripes wider than 1 px.
- Performance claims require compatible repository evidence and must keep their hardware/context
  qualification.

## Design tokens and assets

- Built-in Voice/custom: gold (`--mode-custom`).
- Voice Design: lavender (`--mode-design`).
- Voice Cloning: terracotta (`--mode-clone`).
- Canvas: charcoal (`--charcoal-900`).
- Type: SF Pro Text for body, SF Pro Rounded for the wordmark, and New York/system serif for large
  editorial display moments.

Pass mode colors through existing CSS custom properties such as `--row-mode` and `--mode-current`;
do not hard-code duplicate hex values.

Asset ownership:

- `public/assets/screens/`: product screenshots, including `ios-studio.png`.
- `public/assets/voice-samples/`: WAV samples referenced by `src/data/samples.js`. When audio
  changes, regenerate waveform arrays with `website/scripts/render-waveforms.mjs`.
- `public/assets/app-icon-1024.png`, `vocello-header-mark.png`, and `social_preview.png`: brand art.

Add assets under `public/assets/<category>/` and reference them through the data layer, not directly
from unrelated JSX.

## Interaction and accessibility

- There is no client-side router. Internal navigation uses plain hash anchors.
- Listen uses one shared `<audio>` element with `preload="none"` and source swapping for mutual
  exclusion.
- Reuse the existing `panelSettle` motion and easing. Animate only opacity, transform,
  border-color, and box-shadow, never layout properties.
- Preserve the single `prefers-reduced-motion: reduce` block.
- Every image needs meaningful alt text or deliberate decorative handling.
- External `target="_blank"` links require `rel="noreferrer"`; internal targets must resolve.
- Maintain semantic heading order, keyboard-operable controls, focus visibility, and sufficient
  contrast across all breakpoints.
- Do not hide product limitations or replace precise copy with vague marketing language.

## Definition of done

1. Cross-check changed claims against authoritative parent-repository sources.
2. Run `npm --prefix website run check`.
3. For visual or interaction changes, run the local server and inspect desktop, 900 px, and 600 px
   boundaries with the in-app browser when callable.
4. Confirm reduced motion, keyboard navigation, anchors, audio mutual exclusion, and external-link
   safety when those surfaces changed.
5. Refresh repository documentation/generated artifacts only when their registered inputs changed.
