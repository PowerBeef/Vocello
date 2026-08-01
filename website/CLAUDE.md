# CLAUDE.md — website

This file provides guidance to AI coding agents when working on the website in this repository.

## What this is

A marketing site for **Vocello** (formerly QwenVoice), a local-first Mac TTS app. Single-page React + Vite. This directory lives inside the QwenVoice monorepo at `website/` and is deployed by Vercel with `website/` as the project root. The site is the brand surface for the app in the parent repo — see "Content accuracy" below. For repo-wide conventions, the app engine, and the source-of-truth order, see the root [`../CLAUDE.md`](../CLAUDE.md); this file is scoped to the website only.

## Commands

```sh
npm --prefix website run dev      # from repo root: vite dev server on localhost:5173
npm --prefix website run lint     # deterministic source/metadata/accessibility contract
npm --prefix website test         # dependency-free Node contract fixtures
npm --prefix website run build    # from repo root: production build -> website/dist/
npm --prefix website run check    # lint + test + build
npm --prefix website run preview  # from repo root: serve the production build
```

When already inside `website/`, omit `--prefix website` from the same commands.

The dependency-free Node contract checks metadata, public release identity, internal anchors,
image alt text, safe external links, assets, visible punctuation, and unqualified performance
claims. The parent `.github/workflows/ci.yml` runs those checks plus the Vite production build with
the exact Node/npm identities from `config/toolchain.json`. Browser review remains useful for visual
behavior; Vercel owns deployment for this directory.

## Tooling for this directory

- This is a **non-app, non-native zone** — do not run Swift/iOS/macOS skills or audits here.
- For React, Vite, or library API questions, use authoritative current documentation and a docs or
  library MCP when callable.
- For UI/UX/visual passes, read `PRODUCT.md` and `DESIGN.md` first, then use a browser MCP when it
  is currently available against the running dev/preview server. Otherwise use the same local
  server for attended browser verification and record unreachable states.
- Run `npm`/`node` commands through the shell.

## Architecture

`src/App.jsx` is a **thin composer** (~73 lines). All UI is split across:

- `src/sections/` — one file per page section, in render order: `Nav`, `Hero`, `WorkflowBand` (rendered 3× from data), `Listen`, `Capabilities`, `WhyCloud`, `HowItRuns`, `IphoneBeta`, `Engineering`, `Limitations`, `FinalCTA`, `Footer`.
- `src/components/` — two shared primitives:
  - `Icon.jsx` — single switch over an 18-case SVG vocabulary. Also exports `makeWaveBars` (deterministic bar-height generator).
  - `Waveform.jsx` — bar waveform for Listen rows.
- `src/data/` — **single sources of truth**:
  - `workflows.js` (`WORKFLOWS`): the three voice workflow bands' copy + screenshot paths.
  - `samples.js` (`SAMPLES`, `DELIVERIES`, `DELIVERY_COLORS`): Listen samples (with `src` paths into `public/assets/voice-samples/`) + the delivery chip vocabulary.
  - `credits.js` (`CREDITS`, `REPO`, `RELEASE_LATEST`, `RELEASE_V1`, `TESTFLIGHT`): "Built on" tech list + GitHub/TestFlight URLs. Used by `FinalCTA.jsx` for the closing credits roll and by `Hero`/`IphoneBeta` for the beta link.
- `src/site.css` + `src/tokens.css` — single global stylesheet (tokens.css is imported from site.css). No CSS modules, no styled components.
- `App.jsx` also mounts the `@vercel/analytics` `<Analytics />` component (cookieless page views; the website section of `public/privacy/index.html` discloses it) and owns the scroll-reveal hook, including the instant reveal for in-page anchor jumps.

### Responsive breakpoints

Three breakpoints in `site.css`, applied universally:

- `<1100px` — hero stacks (copy first, then Mac window).
- `<900px` — workflow bands stack, listen rows stack, runs spec collapses to single column, try-inner stacks, nav-links hide, **all content text-aligns center** (text blocks added `margin-inline: auto` to center as blocks, not just inner text).
- `<600px` — container padding tightens, `formerly QwenVoice` clarifier hides, CTA shrinks.

When changing grid layouts at narrow breakpoints, **use `grid-template-columns: minmax(0, 1fr)` instead of `1fr`** — grid items default to `min-width: auto` which equals content's intrinsic width, and several children (e.g., `.workflow-band-points` with `width: max-content`) force columns wider than the container. Every narrow-breakpoint grid in this file already uses `minmax(0, …)` for this reason.

## Content accuracy (required reading)

Two design-context files in this directory encode the website's rules:

- **`PRODUCT.md`** (i.e. `website/PRODUCT.md`, the brand doc — distinct from the repo-root `PRODUCT.md` app-product doc) — brand voice, register (`brand`, not product), copy rules. Required by the `impeccable` skill when that skill is available. Key constraints:
  - Say *local*, not *offline* or *on-device*, unless the technical distinction matters.
  - Sentence case. Reserve all caps for tiny labels only.
  - **No em dashes in visible copy.** Use commas, colons, semicolons, periods, or parentheses.
    After any copy change, scan visible text for the em-dash character; the repository
    documentation contract enforces this policy.
  - No emoji, no celebration copy, no hype claims, no first-person plural.
- **`DESIGN.md`** — color strategy, typography rules, motion rules, bans. Specifically: no gradient text, no side-stripe borders >1px on cards, no decorative glassmorphism, no identical card grids, no repeated uppercase eyebrow scaffolding.

The product's ground truth lives in the parent QwenVoice app repo. When making product claims on the site (model variants, hardware requirements, emotion presets, speaker names, OS requirements), cross-reference:

- `../CLAUDE.md` — repo facts: model variant policy, architecture, distribution.
- `../config/public-product-facts.json` — public release, platform status, minimum support, and
  canonical benchmark-profile references.
- `../Sources/Resources/qwenvoice_contract.json` — model registry, speakerMetadata, Hugging Face revisions.
- `../Sources/QwenVoiceCore/EmotionPreset.swift` — actual emotion presets (9 non-Neutral × 2 intensities, normal/strong, + Neutral = 10 total).
- Voice Cloning has no controllable delivery — the engine path doesn't accept emotion/intensity for clone.

The site has drifted from ground truth multiple times during iteration. Don't trust the existing copy — verify against the upstream.

| Website claim | Authoritative source |
| --- | --- |
| Current/fallback Mac release, public iPhone status, minimum support | `../config/public-product-facts.json` plus `../project.yml` |
| Model names, variants, speakers, languages, revisions | `../Sources/Resources/qwenvoice_contract.json` |
| Delivery styles and intensity | `../Sources/QwenVoiceCore/EmotionPreset.swift` |
| Canonical performance hardware | `../benchmarks/hardware-profiles.json` |
| Performance statements | Compatible clean records in `../benchmarks/runs/` and generated `../benchmarks/HISTORY.md` |

## Brand tokens (in `tokens.css`)

- **Gold** = Custom Voice (`--gold-300: #EDCC8A`, `--mode-custom`).
- **Lavender** = Voice Design (`--lavender-300: #BFAADB`, `--mode-design`).
- **Terracotta** = Voice Cloning (`--terracotta-300: #DBA887`, `--mode-clone`).
- **Canvas** = charcoal (`--charcoal-900: #16181E`).
- Type stack: SF Pro Text (body), SF Pro Rounded (wordmark), New York / system serif (large display + editorial moments).

Mode colors are referenced via CSS custom properties: rows pass them through `--row-mode`, `--mode-current`, etc. New mode-aware elements should follow this pattern, not hard-code hex values.

## Assets

- `public/assets/screens/` — six Mac app screenshots (`custom-voice.png`, `voice-design.png`, `voice-cloning.png`, `model-downloads.png`, `delivery-presets.png`, `history.png`) plus the iPhone shot `ios-studio.png` used by `IphoneBeta`.
- `public/assets/voice-samples/` — five WAV clips for the Listen rows; filenames match the `SAMPLES[*].src` field in `data/samples.js`. Regenerate the `wave` arrays with `website/scripts/render-waveforms.mjs` whenever a WAV changes.
- `public/assets/app-icon-1024.png`, `vocello-header-mark.png`, `social_preview.png` — brand artwork.

When adding new audio/image assets, drop them under `public/assets/<category>/` and reference via the data layer, not from JSX directly.

## Conventions worth knowing

- **No client-side router.** Internal links use hash anchors (`#workflows`, `#listen`, `#how-it-runs`, `#iphone`, `#download`) on plain `<a>` tags. The nav scroll-progress hairline reads `scrollTop / scrollHeight`.
- **Animations** use the existing `panelSettle` keyframe and `cubic-bezier(0.32, 0.08, 0.24, 1)` ease. Only animate `opacity`, `transform`, `border-color`, and `box-shadow` — never layout properties. `prefers-reduced-motion: reduce` is honored in a single block at the end of `site.css`.
- **Audio playback** in Listen uses one shared `<audio ref>` element with `preload="none"` and src-swap on click for mutual exclusion. See `Listen.jsx`.
