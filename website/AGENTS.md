# AGENTS.md — Vocello website

This file adds website-specific guidance to the root `../AGENTS.md`. The website is a React/Vite
marketing surface deployed by Vercel with `website/` as the project root. It is a non-native zone:
do not run Swift, iOS, macOS, Xcode, or native-app UI workflows for website-only changes.

## Commands

```sh
npm --prefix website run dev      # localhost:5173 (background with IsDaemon: true for browser inspection)
npm --prefix website run lint     # site contract, ESLint (eslint.config.js), tsc --checkJs (jsconfig.json)
npm --prefix website test         # Node contract fixtures + rendered contract
npm --prefix website run build    # client + SSR + prerender -> website/dist/
npm --prefix website run check    # lint + test + build + Playwright browser tests
                                  # (needs Chromium and WebKit once: npm --prefix website exec playwright install chromium webkit; Linux CI uses --with-deps)
npm --prefix website run preview  # serve production build (use port 4174 with --strictPort; 4173 stays free for Playwright)
```

Inside `website/`, omit `--prefix website`. `npm run check` is the final deterministic verdict.
The parent CI uses the Node/npm identities in `../config/toolchain.json`. Client and transient SSR
build outputs are generated; do not hand-edit them.

## Tool routing

- Read `PRODUCT.md` (brand voice, release facts, copy rules) and `DESIGN.md` (visual register, layout
  tiers, motion, visual bans) before visual or copy work.
- Use current primary React/Vite/library documentation; Context7 (`context7_context7`) may assist when callable.
- For visual, responsive, interactive and accessibility inspection, start the local dev or preview
  server (`--host 127.0.0.1 --port 5173 --strictPort`, or `4174` for preview) and delegate inspection
  to Antigravity's `browser` subagent (or `chrome-devtools` skills for Lighthouse, performance traces
  and heap snapshots); otherwise rely on Playwright output from `npm run check`. Browser evidence
  supplements rather than replaces `npm run check`. Prefer a fresh tab; reuse an existing signed-in
  tab only when that state is explicitly needed.
- Image generation is optional and only appropriate when the user requests new bitmap artwork.
- Use browser automation only for the website. Never use `cua-driver`, computer-use, Xcode, Simulator,
  or native UI automation to validate the site.
- Vercel deploys automatically from Git on push to `main`; any direct `vercel` CLI write or deployment
  requires an explicit maintainer request.

## Architecture

The site has three React pages, listed in `scripts/site-pages.mjs`:

| Page | Entry | Content |
| --- | --- | --- |
| `/` | `index.html` | the home page, for people who make voices |
| `/cli/` | `cli/index.html` | the full command line guide |
| `/engineering/` | `engineering/index.html` | engine, speed and every current limitation |

The support, privacy and terms pages (`/support/`, `/privacy/`, `/terms/`) are static HTML under `public/`, listed as
`STATIC_PAGES` in the same file; the layout matrix covers them too.

- Each entry names its page on `<div id="root" data-page="...">`. `src/App.jsx` composes the
  skip link, bar, page (`PAGES` from `src/pages/`), footer and analytics.
- `vite.config.js` builds every entry. `scripts/prerender.mjs` renders each page into its HTML.
  The site contract checks each page's head, and the rendered contract checks each page's
  landmarks.
- Home sections the other pages link to are `/#id`. Ids outlive redesigns, so old anchors still
  land: the privacy section keeps `#how-it-runs` (its comparison `#why-not-cloud-tts`), and the For
  developers tiles keep `#cli` and `#engineering`.

Keep content in the existing boundaries:

- `src/sections/`: page sections. The home page (`src/pages/HomePage.jsx`) renders, in order:
  `Hero`, `Modes` (`#workflows`, the mode switcher), `Listen`, `Privacy` (`#how-it-runs`),
  `Capabilities`, `IphoneBeta`, `WhatsNew` (`#whats-new`, `"What's new in {WHATS_NEW_VERSION}"`),
  `Developers` (the `#cli` and `#engineering` tiles), `Limitations` (`summary`) and `FinalCTA` (`#download`).
  - `CommandLine.jsx`: `CommandLineGuide` (`/cli/`);
  - `Engineering.jsx`: `EngineeringDetail` (`/engineering/`), with the HTML speed chart;
  - `Limitations.jsx`: a `summary` on the home page and the `full` list on `/engineering/`.
- `src/components/Icon.jsx`: shared SVG vocabulary and deterministic waveform-bar generator.
- `src/components/Waveform.jsx`: Listen-row waveform primitive.
- `src/data/workflows.js`: the three modes the switcher shows, with the app's short tab names.
- `src/data/samples.js`: samples, delivery labels and groups, and colors. The samples predate 3.0;
  never present them as 3.0 takes.
- `src/data/whatsnew.js`: the release's What's new entries (`WHATS_NEW_VERSION`, `HIGHLIGHTS`,
  `IPHONE_NOTE`, `UPGRADE_NOTE`, `QUALITY_NOTE`), drawn from `../docs/releases/`.
- `src/data/cli.js`: the command line section's install, uninstall, and MCP setup commands, quoted
  from `../docs/reference/cli.md`.
- `src/data/credits.js`: technology, GitHub, release, and TestFlight URLs, plus the tagged Mac DMG,
  CLI package, CLI folder DMG, and release notes links derived from the stable tag.
- `src/data/release.js`: the stable and fallback Mac release mirror (see below).
- `src/site.css` and `src/tokens.css`: global styling and design tokens. Do not add CSS modules or
  styled-component systems without an explicit redesign request.

`App.jsx` mounts cookieless Vercel Analytics and owns scroll reveal, including immediate reveal for
anchor jumps. The privacy page must continue to disclose website analytics.

### Responsive layout implementation

Four layout tiers are owned by `DESIGN.md` and implemented at the top of `src/site.css`:

- Media queries use exactly `max-width: 599.98px`, `899.98px` and `1199.98px`, or `min-width:
  1200px` and `1600px`. A short landscape screen, `(orientation: landscape) and (max-height:
  500px)`, tightens the bar and display type and caps screenshots at 80% of the height.
- Sizes come from layout tokens in `src/site.css` (`--fs-display`, `--fs-hero`, `--fs-section`,
  `--fs-band`, `--fs-cta`, `--fs-quote`, `--section-y`, `--gutter`, `--nav-h`, `--tap`) scaled via
  `clamp()`; do not add per-tier font sizes or section padding.
- **The bar (`src/sections/Nav.jsx`)** is opaque: Desktop shows all six links (plus Open source from
  1320 px); Tablet shows four (Voices, Listen, Privacy, iPhone), Download and the menu button; below
  900 px shows brand, Download and the menu button. `#site-menu` is a native modal `<dialog>` that
  locks the page and restores focus on close; the former-name clarification shows only from 1200 px.
- Controls keep a 44 px target (`--tap`), hover styles stay inside `@media (hover: hover) and
  (pointer: fine)`, `html` sets `scroll-padding-top`, and body sets `overflow-x: clip` (fix overflow
  at its source — the layout matrix measures every element).
- Use `grid-template-columns: minmax(0, 1fr)` for narrow single-column grids so intrinsic-width
  children cannot overflow.
- `tests/layout-matrix.spec.mjs` (widths, devices and pure checks in
  `scripts/browser-smoke-contract.mjs`) checks every page across all tier edges and landscape sizes
  in Chromium plus real iPhone/iPad descriptors in WebKit.

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
| Release contents and known limitations | the tag's notes under `../docs/releases/` |
| Command line, its install, and `vocello mcp` | `../docs/reference/cli.md`, `../Sources/VocelloCLI`, and `../scripts/cli_package.py` |

Voice Cloning has no instruction channel; its delivery banks select verified reference clips. Keep
public copy aligned with `../config/public-product-facts.json`, `PRODUCT.md` (copy rules; visible
copy bans em dashes, enforced by the site contract), and `DESIGN.md` (visual bans and color/type
rules). Never infer availability from an old page or release note.

## Tokens and assets

Pass mode colors through existing CSS custom properties (`--mode-custom`, `--mode-design`,
`--mode-clone`, `--charcoal-900`, `--row-mode`, `--mode-current`); do not hard-code duplicate hex
values.

Asset ownership:

- `public/assets/screens/`: product screenshots, including `ios-studio.png`.
  - Each PNG ships with an AVIF sibling: `sips -s format avif -s formatOptions 80 x.png --out
    x.avif`.
  - A 2080 px Mac capture also ships `x-1040.avif`: `sips -Z 1040` to a temporary PNG, then the
    AVIF command; commit only the AVIF. No 1560 px copy: sips encoded that width with a structure
    Linux WebKit could not decode. The layout matrix fails on any image that does not decode.
  - Screenshots render through `src/components/Screenshot.jsx` with their pixel size and a
    srcset of those widths; only the hero loads eagerly.
- `public/assets/voice-samples/`: WAV samples referenced by `src/data/samples.js`. When audio
  changes, regenerate waveform arrays with `website/scripts/render-waveforms.mjs`.
- `public/assets/favicon-32.png`, `apple-touch-icon.png` (180 px), `vocello-header-mark.png`, and
  `social_preview.png`: brand art. `src/data/release.js` mirrors the stable and fallback releases in
  `../config/public-product-facts.json`; download links name the stable tag.

Add assets under a category directory in `public/assets/` and reference them through the data layer,
not directly from unrelated JSX.

## Interaction and accessibility

- There is no client-side router. Internal navigation uses plain hash anchors and links across the
  three React pages (`/`, `/cli/`, `/engineering/`) and three static HTML pages (`/support/`,
  `/privacy/`, `/terms/`).
- Listen uses one shared `<audio>` element with `preload="none"` and source swapping for mutual
  exclusion.
- Motion uses `panelSettle` (menu sheet, mode switcher panels) and `rise` (hero one-time entrance)
  with `--ease-standard` and staggered `--i` reveals; animate only `opacity`, `transform`,
  `border-color`, and `box-shadow`. Preserve the single `prefers-reduced-motion: reduce` block.
- Every image needs meaningful alt text or deliberate decorative handling; external `target="_blank"`
  links require `rel="noreferrer"`; internal targets must resolve.
- Maintain semantic heading order, keyboard operability, focus visibility, and contrast: `npm run
  lint` (`scripts/site-contract.mjs`) enforces WCAG AA ≥ 4.5:1 for `--fg-primary`, `--fg-secondary`,
  and `--fg-tertiary` on every surface token in both themes.
- Do not hide product limitations or replace precise copy with vague marketing language.

## Definition of done

1. Cross-check changed claims against authoritative parent-repository sources.
2. Run `npm --prefix website run check`.
3. For visual or interaction changes, run the local server and inspect a phone (390 px), a phone
   on its side (844 x 390), a tablet (1024 px) and a desktop (1440 px) using the `browser` subagent
   or `chrome-devtools` when callable; the layout matrix covers every tier edge.
4. Confirm reduced motion, keyboard navigation, anchors, audio mutual exclusion, and external-link
   safety when those surfaces changed.
5. Refresh repository documentation/generated artifacts only when their registered inputs changed.
