# CLAUDE.md — Vocello website

This file adds website-specific guidance to the root `../CLAUDE.md`. The website is a React/Vite
marketing surface deployed by Vercel with `website/` as the project root. It is a non-native zone:
do not run Swift, iOS, macOS, Xcode, or native-app UI workflows for website-only changes.

## Commands

```sh
npm --prefix website run dev      # localhost:5173
npm --prefix website run lint     # site contract, ESLint (eslint.config.js), tsc --checkJs (jsconfig.json)
npm --prefix website test         # Node contract fixtures + rendered contract
npm --prefix website run build    # client + SSR + prerender -> website/dist/
npm --prefix website run check    # lint + test + build + Playwright browser tests
                                  # (needs Chromium and WebKit once: npx --prefix website playwright install --with-deps chromium webkit)
npm --prefix website run preview  # serve production build
```

Inside `website/`, omit `--prefix website`. `npm run check` is the final deterministic verdict.
The parent CI uses the Node/npm identities in `../config/toolchain.json`. Client and transient SSR
build outputs are generated; do not hand-edit them.

## Tool routing

- Read `PRODUCT.md` and `DESIGN.md` before visual or copy work.
- Use current primary React/Vite/library documentation; Context7 may assist when callable.
- For visual, responsive, interactive and accessibility inspection, drive the local dev or preview
  server with the Chrome browser tools this harness provides (Claude in Chrome or the chrome-devtools
  MCP) when they are connected; otherwise rely on Playwright output from `npm run check`. Browser
  evidence supplements rather than replaces `npm run check`. Prefer a fresh tab; reuse an existing
  signed-in tab only when that state is explicitly needed.
- Image generation is optional and only appropriate when the user requests new bitmap artwork.
- Use browser automation only for the website. Never use computer-use, Xcode, Simulator, or native UI
  automation to validate the site.

## Architecture

`src/App.jsx` is a thin page composer. Keep content in the existing boundaries:

- `src/sections/`: page sections in render order, including `WhatsNew.jsx` (`#whats-new`, "What's
  new in 3.0") and `CommandLine.jsx` (`#cli`, "Command line and agents").
- `src/components/Icon.jsx`: shared SVG vocabulary and deterministic waveform-bar generator.
- `src/components/Waveform.jsx`: Listen-row waveform primitive.
- `src/data/workflows.js`: the three workflow bands.
- `src/data/samples.js`: samples, delivery labels and groups, and colors. The samples predate 3.0;
  never present them as 3.0 takes.
- `src/data/whatsnew.js`: the release's What's new entries, drawn from `../docs/releases/`.
- `src/data/cli.js`: the command line section's install, uninstall, and MCP setup commands, quoted
  from `../docs/reference/cli.md`.
- `src/data/credits.js`: technology, GitHub, release, and TestFlight URLs, plus the tagged Mac DMG,
  CLI package, CLI folder DMG, and release notes links derived from the stable tag.
- `src/data/release.js`: the stable and fallback Mac release mirror (see below).
- `src/site.css` and `src/tokens.css`: global styling and design tokens. Do not add CSS modules or
  styled-component systems without an explicit redesign request.

`App.jsx` mounts cookieless Vercel Analytics and owns scroll reveal, including immediate reveal for
anchor jumps. The privacy page must continue to disclose website analytics.

### Responsive layout

Four layout tiers, defined in `DESIGN.md` and at the top of `src/site.css`:

| Tier | Widths | Layout |
| --- | --- | --- |
| Phone | below 600 px | one column; 56 px bar |
| Small tablet | 600 to 899 px, and landscape phones | one column; side-panel menu |
| Tablet | 900 to 1199 px | two-column sections; the hero stacks |
| Desktop | 1200 px and up | full layout; a 1320 px container from 1600 px |

- Media queries use exactly `max-width: 599.98px`, `899.98px` and `1199.98px`, or `min-width:
  1200px` and `1600px`. A short landscape screen, `(orientation: landscape) and (max-height:
  500px)`, also tightens the bar and the display type, and caps screenshots at 80% of the height.
- Sizes come from the layout tokens in `src/site.css`: `--fs-hero`, `--fs-section`, `--fs-band`,
  `--fs-cta`, `--fs-quote`, `--section-y`, `--gutter`, `--nav-h` and `--tap`. Display type and
  section rhythm scale with `clamp()`, so do not add a per-tier font size or section padding.
- **The bar (`src/sections/Nav.jsx`)** is opaque. Each section link names the narrowest tier
  that shows it:

  | Tier | Bar contents |
  | --- | --- |
  | Desktop | all six section links, plus Open source from 1320 px |
  | Tablet | four links (`nav-link--tablet`), Download and the menu button |
  | Below 900 px | brand, Download and the menu button |

  The menu is a native modal `<dialog>` (`#site-menu`) listing every section. It locks the page
  and hands focus back to the menu button when it closes. The former-name clarification shows
  only from 1200 px.
- Every interactive control in the bar and the menu keeps a 44 px target (`--tap`). Hover styles
  live only inside `@media (hover: hover) and (pointer: fine)`, so a tap never leaves a control
  looking active.
- The hero and the closing call to action are the only centered blocks. Body text, lists and
  tables stay left-aligned at every width.
- `html` sets `scroll-padding-top`, so anchor jumps land below the bar. The body clips sideways
  overflow (`overflow-x: clip`), but the layout matrix measures every element regardless, so fix
  overflow where it starts.
- `tests/layout-matrix.spec.mjs` checks every page on every tier edge and three landscape sizes in
  Chromium, plus real iPhone and iPad descriptors in WebKit. It checks that no element extends past
  the viewport, the bar's items neither overlap nor escape, tap targets are 44 px, the menu behaves
  and anchor jumps land below the bar. Its widths, devices and pure checks live in
  `scripts/browser-smoke-contract.mjs`.

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
| Architecture, privacy, distribution | `../CLAUDE.md`, `../docs/ARCHITECTURE.md`, and machine-readable contracts |
| Release contents and known limitations | the tag's notes under `../docs/releases/` |
| Command line, its install, and `vocello mcp` | `../docs/reference/cli.md`, `../Sources/VocelloCLI`, and `../scripts/cli_package.py` |

Voice Cloning has no instruction channel. Its delivery banks select verified reference clips,
not engine emotion/intensity instructions. Keep public language aligned with
`../config/public-product-facts.json`; do not infer
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

- `public/assets/screens/`: product screenshots, including `ios-studio.png`. Each PNG ships with an
  AVIF sibling (`sips -s format avif -s formatOptions 80 x.png --out x.avif`) and renders through
  `src/components/Screenshot.jsx` with its pixel size; only the hero loads eagerly.
- `public/assets/voice-samples/`: WAV samples referenced by `src/data/samples.js`. When audio
  changes, regenerate waveform arrays with `website/scripts/render-waveforms.mjs`.
- `public/assets/favicon-32.png`, `apple-touch-icon.png` (180 px), `vocello-header-mark.png`, and
  `social_preview.png`: brand art. `src/data/release.js` mirrors the stable and fallback releases in
  `../config/public-product-facts.json`; download links name the stable tag.

Add assets under a category directory in `public/assets/` and reference them through the data layer, not directly
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
  contrast across all breakpoints. `npm run lint` (`scripts/site-contract.mjs`) holds every text
  token (`--fg-primary`, `--fg-secondary`, `--fg-tertiary`) at WCAG AA 4.5:1 or more on every
  surface token in both themes.
- Do not hide product limitations or replace precise copy with vague marketing language.

## Definition of done

1. Cross-check changed claims against authoritative parent-repository sources.
2. Run `npm --prefix website run check`.
3. For visual or interaction changes, run the local server and inspect a phone (390 px), a phone
   on its side (844 x 390), a tablet (1024 px) and a desktop (1440 px) with the Chrome browser
   tools when callable; the layout matrix covers every tier edge.
4. Confirm reduced motion, keyboard navigation, anchors, audio mutual exclusion, and external-link
   safety when those surfaces changed.
5. Refresh repository documentation/generated artifacts only when their registered inputs changed.
