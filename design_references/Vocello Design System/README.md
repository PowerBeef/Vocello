# Vocello Design System

<p align="center">
  <img src="assets/readme-banner.png" alt="Vocello — abstract voice waves and the Vocello wordmark on a dark canvas" width="100%">
</p>

> Premium, local-first Mac voice studio. Calm, polished, private, and
> creator-friendly. Apple-native SwiftUI with soft Liquid Glass surfaces,
> a warm golden brand, and quiet motion.

This design system covers **Vocello 2.0** — the macOS 26 release of what used to
ship as QwenVoice. The product is a native, on-device text-to-speech app for
Apple Silicon Macs. It has three generation workflows (Custom Voice, Voice
Design, Voice Cloning) and three library/settings surfaces (History, Saved
Voices, Settings). Everything lives in one SwiftUI window with one persistent
sidebar — no separate web app, no marketing dashboard inside the app.

## Source materials

This system was built by reading:

- **GitHub:** [`PowerBeef/Vocello`](https://github.com/PowerBeef/Vocello) — the live Swift codebase (Apple Silicon, MLX backend). Specifically:
  - [`Sources/Views/Components/AppTheme.swift`](https://github.com/PowerBeef/Vocello/blob/main/Sources/Views/Components/AppTheme.swift) — every color, glass tint, and surface treatment in this system traces back here.
  - [`Sources/Views/Components/LayoutConstants.swift`](https://github.com/PowerBeef/Vocello/blob/main/Sources/Views/Components/LayoutConstants.swift) — spacing, radii, content widths.
  - [`Sources/Views/Sidebar/SidebarView.swift`](https://github.com/PowerBeef/Vocello/blob/main/Sources/Views/Sidebar/SidebarView.swift) — sidebar lockup + row treatment.
  - [`Sources/Views/Generate/`](https://github.com/PowerBeef/Vocello/tree/main/Sources/Views/Generate) — the three generation screens.
  - [`PRODUCT.md`](https://github.com/PowerBeef/Vocello/blob/main/PRODUCT.md) — brand personality and anti-references.
  - [`docs/qwen_tone.md`](https://github.com/PowerBeef/Vocello/blob/main/docs/qwen_tone.md) — prompt-writing tone (for product voice and microcopy).
- **Uploaded brand assets:** the 1024 app icon, the sidebar header mark, the launch logo, and the README banner are all in `assets/`.
- **Live screenshots** of the four core surfaces (Custom Voice, Voice Design, Voice Cloning, Settings → Model Downloads), in `assets/screens/`.

If you have access to the GitHub repo, **read it before extending this kit** — the
Swift source is the canonical truth, and this system intentionally compresses it
into web-friendly tokens. Use the `/Sources/Views/` tree to verify spacing,
copy, and behavior of any component you're building on.

---

## Content fundamentals

Vocello's voice is **warm, clear, confident, and human**. The product explains
on-device AI generation in plain language and never sounds like a SaaS
dashboard. Microcopy is the discipline most likely to break the brand, so this
section is exhaustive.

### Casing
- **Sentence case** everywhere. Buttons, section headers, sidebar items, sheet
  titles. ("Voice Design", "Saved Voices", "Add a script", "Generate locally".)
- **Title Case** only for proper nouns: the three workflows (Custom Voice,
  Voice Design, Voice Cloning), Saved Voices, Speed / Quality, the wordmark.
- **UPPERCASE** is reserved for the AppTheme `toolbarRow` micro-label and
  small eyebrow categories. Don't use it for buttons or section heads.

### Person
- **Second person.** "Choose the built-in speaker that should deliver this line."
- **Imperatives for primary actions.** "Generate." "Save to Saved Voices."
  "Add a reference."
- **First-person plural ("we") is banned in product copy.** The brand defers to
  the user's work — not "we generate", but "Generate locally".

### Verbs over nouns
Prefer verbs in actions: "Generate", "Save", "Manage", "Import reference audio…",
"Reveal in Finder". Avoid noun-blob CTAs ("Generation", "Voice Settings").

### Rules — borrowed straight from `PRODUCT.md`
- **No celebration messages.** No "Awesome!", no "🎉", no exclamation points
  in success states. The result lands in the player; that's the celebration.
- **Empty states explain what to do next in one sentence, then stop.**
  Example: *"Speaker and delivery are set. Add a line to generate."* Not a
  paragraph, not a hero illustration with a CTA.
- **Errors describe the cause and the fix.** They never apologize, never
  blame "the system", never say "Oops". They are not red walls.
  *"Install Custom Voice (Speed) in Models to enable generation."* is a good
  error — it names the missing thing and the surface that fixes it.
- **No marketing copy inside the app.** No trust badges, no "Try a sample",
  no "Get started" hero. Privacy is the product but it is communicated
  through speed and fidelity, never through a banner.

### Vocabulary
- **Local, not "on-device" or "offline".** "Generate locally", "saved locally".
- **Generate**, never "synthesize" or "produce".
- **Voice**, never "speaker model" or "TTS persona" in user-facing copy.
- **Script**, not "prompt" or "text". (The "prompt" lives in *Voice Design*
  as the "Voice brief".)
- **Speed / Quality** for the 4-bit / 8-bit model variants. Capitalized.
- **Saved Voices**, **Generation History**, **Model Downloads** are proper
  surface names — keep them stable.

### Examples
- Empty Custom Voice composer: *"Add a script — Speaker and delivery are set. Add a line to generate."*
- Voice Cloning gate: *"Add a reference clip to unlock the script composer and generation."*
- Settings header: *"Recommended models ready"*
- Error: *"Engine needs attention — \[short, specific cause]"*. No "Sorry".
- Status pill: *"Ready"*, *"Heavy"*, *"Recommended"*, *"Preparing"*, *"Generating"*. Single words.

### Emoji
**Never in product UI.** Vocello uses SF Symbols glyphs for iconography
(see `ICONOGRAPHY` below). Emoji read as marketing affect inside an
Apple-native app.

---

## Visual foundations

### Color
The system is **dark-first**. Dark is the canonical canvas; light values exist
to honor system appearance and for any web/marketing surface.

- **Vocello gold** (`#EDCC8A` dark / `#B5832E` light) is the singular brand
  accent. It marks the selected sidebar row, the active state on Speed/Quality
  pills, the icon outline on Custom Voice, and the gold-tinted radial backdrop
  behind the Custom Voice page. It is *never* a button fill bigger than a chip,
  *never* a background wash bigger than a panel, and *never* used to imply
  status (Vocello has no "primary CTA glow").
- **Mode tints** sit beside gold without competing: lavender (`#BFAADB`) for
  Voice Design, terracotta (`#DBA887`) for Voice Cloning. Each mode also
  injects a top-anchor radial gradient behind the canvas
  (`modeCanvasBackdrop` in the source), so Liquid Glass has a colored
  refraction without the page looking tinted.
- **Surfaces** climb in tiny increments through the charcoal ramp:
  canvas `#16181E` → rail `#171920` → stage `#1C1E26` → card `#0D0E12`
  (card is *darker* than canvas — cards read as a recessed glass well, not a
  floating element). Field fill goes brighter (`#2A2C36`) so text inputs read
  as input wells rather than panels.
- **No vibrant accents.** Greens (`#4CC38A`) and oranges (`#E8943A`) appear
  only in tiny status labels ("Ready", "Heavy") in Settings. Red is reserved
  for destructive errors. There is no purple/blue gradient brand color, no
  neon, no terminal-green.
- **Emotion palette** (delivery chips) sits in the same midtone OKLCH band so
  no chip looks like a sticker on a card: warm gold-yellow, slate-blue, deep
  rust, quiet violet, cool gray, mauve, sage, warm orange. (Source: the
  `emotionColor(for:)` switch in `AppTheme.swift` — kept unified after the
  May 2026 "Batch 4 colorize" audit.)

### Type
- **SF Pro Text** is the primary face. SwiftUI semantic sizes:
  `.title2` (22 px) for page titles, `.headline` (17 px) for card titles,
  `.subheadline` (13 px / semibold) for row labels, `.body` (15 px) for
  paragraph copy, `.footnote` (12 px) for detail lines, `.caption2` (10 px)
  for the toolbar-row eyebrow.
- **SF Pro Rounded** is reserved for the sidebar wordmark ("Vocello", 18 px
  semibold). Its slightly soft terminals are the warmth carrier in the
  chrome — the brand never feels too clinical despite the dark palette.
- **New York / serif** appears only in the launch logo and marketing banner.
  Do not use it for body copy or section headers.
- **SF Mono** is used in benchmark JSON and any code surface (rare).
- Casing/weight/color, not size, is the primary hierarchy lever. Secondary
  text drops to `var(--fg-secondary)` rather than getting smaller.

### Spacing and layout
- 4-pt grid. Most spacing comes from
  `LayoutConstants.{compactGap=8, sectionSpacing=12, shellPadding=12,
  canvasPadding=18}`.
- **Sidebar is 200 px wide and fixed.** Brand lockup pinned to the top via a
  safe-area inset. Player + engine status pinned to the bottom.
- **Content max-width is 960 px** in the canvas; 980 px on the three
  generation screens. Everything is centered.
- **Generation pages are two stacked cards**: Configuration on top
  (fixed-height slot, 184 px), Script below (fills available height,
  `layoutPriority(1)`).
- Hover and selection are *full-bleed within the row* — never an outline that
  hugs the icon only.

### Cards
- 16 px radius for cards, 22 px for the stage / canvas, 8 px for chips and
  buttons.
- Cards in Liquid Glass mode are a stack of: opaque dark fill (`--bg-card`)
  + a `glassEffect` tint + a hairline white stroke (`--stroke-card`,
  `0.75 px`) + a 3D depth modifier (top highlight gradient + soft
  drop shadow).
- Legacy fallback (Reduce Transparency on, or pre-macOS 26) drops the glass
  material and shows the flat opaque fill — depth comes from the stroke only.
- **No left-border accent stripes.** Identity is carried by the icon color,
  the gold trailing label, or the radial backdrop — never by a colored bar
  glued to the side of a card.

### Backgrounds
- The canvas is a **subtle vertical aurora** from `#0F1014` to `#1A1C22`
  (Aurora component in AppTheme). On a generation screen it is overlaid with
  a single radial wash of the mode color anchored to the top-center.
- **No full-bleed imagery, no patterns, no grain.** The banner is a
  marketing-only treatment (waves + sparkles); inside the app the canvas is
  always quiet.
- Light mode swaps the aurora for warm whites (`#FAFBFE → #ECEFF5`) and uses
  the cooler stroke set; the mode color radial stays.

### Borders and strokes
- Hairlines (`0.5–0.75 px` dark / `1 px` light) on every card and field.
- Stroke alpha is the depth lever — `0.16` for normal cards in dark mode,
  rising to `0.42` when a card has a mode tint applied.
- Focus rings are not the bright SwiftUI default. Focused fields take a
  mode-colored stroke at `~0.40` alpha; nothing animates in.

### Shadow / elevation
- Dark mode shadows are tiny (`y=2`, blur `2`, alpha `0.20`) — they're
  there to anchor the card, not float it.
- Light mode shadows are larger and softer
  (`y=2`, blur `5.5`, alpha `0.045`).
- Popovers and sheets pick up a heavier shadow (`y=12`, blur `36`, alpha
  `0.40` dark).

### Capsules vs cards
- **Pills** (chips, status labels, mode badges, the Speed/Quality toggle)
  are 8 px capsules. Selected = mode-color wash fill + mode-color hairline
  stroke. Unselected = inline fill + neutral hairline.
- After the May 2026 "Batch 2 — quieter" audit, **chips no longer use Liquid
  Glass**. Glass is reserved for the panels and the primary CTA, so chips
  read as quieter elements *inside* a glass surface.
- Badges (the small `Ready`, `Heavy`, `Recommended` labels) are flat capsules
  with a 0.5 px stroke.

### Transparency and blur
- Liquid Glass is **only** used on:
  1. Cards (Configuration panel, Script panel, Settings sections).
  2. The sidebar selection / hover row background.
  3. The primary "Generate" button (`GlowingGradientButtonStyle`).
- Everything else (chips, badges, text fields) is solid. This is the rule
  that keeps the chrome feeling intentional rather than glassy-everywhere.
- `Reduce Transparency` is honored — glass falls back to opaque fills.

### Motion
- Quiet. `easeInOut` 0.15 s for state changes; 0.14 s for sidebar
  hover/selection; 0.20 s for sheet reveals. No springs, no bounces.
- All animation routes through `appAnimation` / `performAnimated`, so
  Reduce Motion disables it entirely.
- The brand has **no idle motion** — no breathing logos, no shimmering text,
  no animated gradients. The waveform is the only living element on the
  screen, and even it animates only during playback.

### Hover, press, focus
- **Hover (sidebar / buttons)**: a faint fill + thin stroke appear; nothing
  scales. 0.14 s ease-out.
- **Press (buttons)**: opacity drops to `0.75`. No scale-down, no color shift.
- **Selection (sidebar row)**: a 3 × 16 capsule "rail indicator" in the mode
  color appears on the leading edge; the row background goes to
  `--sidebar-select-fill`; the icon picks up the mode color.
- **Focus (fields)**: stroke color swaps to the mode color at ~0.40 alpha.
- No glow effects, no shadows-on-hover, no shrinking primary CTAs.

### Iconography
Vocello uses **SF Symbols** exclusively in the app. See `ICONOGRAPHY` below.

### Cards versus panels — the cheat sheet
| Surface | Radius | Glass? | Stroke | Use |
|---|---|---|---|---|
| Stage / canvas frame | 22 px | – | hairline `--stroke-stage` | wraps a whole page region |
| Card (Configuration, Script) | 16 px | ✅ tinted | `--stroke-card` | the two big SwiftUI panels per screen |
| Inline panel | 16 px | ❌ flat | `--stroke-inline` | secondary nested panel |
| Text field | 10 px | ❌ flat | `--stroke-field` (mode color on focus) | inputs |
| Chip / pill | 8 px | ❌ flat | `--accent-stroke` when selected | toggles, emotions, mode badges |
| Sidebar row | 8 px | ✅ tinted on select/hover | mode color on select | nav |

---

## Iconography

Vocello is an Apple-native app: it uses **SF Symbols** end to end. Some of the
symbols in the real Swift source, observed in screenshots and code:

| Surface | Symbol |
|---|---|
| Sidebar — Custom Voice | `person.wave.2` |
| Sidebar — Voice Design | `bubble.left.and.text.bubble.right` (chat-like) |
| Sidebar — Voice Cloning | `waveform.badge.plus` |
| Sidebar — History | `clock` (arrow-counterclockwise variant) |
| Sidebar — Saved Voices | `person.2.wave.2` |
| Sidebar — Settings | `gearshape` |
| Configuration card | `slider.horizontal.3` |
| Script card | `text.alignleft` |
| Sidebar toggle (titlebar) | `sidebar.left` |
| Import reference audio | `waveform.badge.plus` |
| Warning (Heavy model) | `exclamationmark.triangle` |
| Engine ready dot | a small filled circle (status) |

In the **HTML preview, slides, and any web/marketing surface**, we substitute
SF Symbols with **hand-authored inline SVG approximations** — same stroke
weight (1.6–1.8, matching `regular` SF Symbols) and visual register, no
external dependency. They live in `ui_kits/mac-app/icons.jsx`. *This is a
substitution; please confirm with the team and ideally provide PDF exports of
the actual SF Symbols used if you want pixel parity for marketing artifacts.*

No emoji. No PNG icons. No Material/Fluent/Carbon icon sets. Unicode "•" and
"·" appear only inside the wordmark eyebrow ("AI·TTS").

### Logos and brand assets
All in `assets/`:
- `app-icon-1024.png` — 1024² App Store icon. Dark squircle, three-layered
  V (white → cream → lavender), gentle highlight.
- `vocello-header-mark@3x.png` — the small "V" mark used in the sidebar
  lockup. Same V, smaller.
- `vocello-launch-logo@3x.png` — V mark + serif "Vocello" wordmark.
  Used in the launch / about / marketing splash.
- `readme-banner.png` — the marketing banner: V mark + serif Vocello over
  abstract gold + lavender wave geometry on near-black.
- `logo-square.png` — the docs-repo logo (V on dark, 256²-ish).

---

## Repository index

```
assets/                       Brand marks + reference screenshots
  app-icon-1024.png           macOS icon (1024²)
  vocello-header-mark@3x.png  Sidebar V mark
  vocello-launch-logo@3x.png  V + serif "Vocello"
  readme-banner.png           Marketing banner
  logo-square.png             Docs logo
  screens/                    Real screenshots from the macOS app
    custom-voice.png
    voice-design.png
    voice-cloning.png
    model-downloads.png

colors_and_type.css           Color tokens + semantic typography
README.md                     This file
SKILL.md                      Agent-Skill manifest

preview/                      Design-system review cards
  brand-mark.html             V mark + wordmark lockups
  brand-launch.html           Launch + marketing wordmark
  app-icon.html               App Store icon
  color-brand.html            Gold, lavender, terracotta
  color-surfaces-dark.html    Surface ramp (dark)
  color-surfaces-light.html   Surface ramp (light)
  color-emotion.html          8-emotion delivery palette
  color-status.html           Status colors (Ready / Heavy / Danger)
  type-scale.html             SwiftUI semantic scale
  type-specimens.html         Hierarchy in context
  type-wordmark.html          Wordmark anatomy
  spacing-grid.html           4-pt grid + spacing tokens
  spacing-radii.html          Radii (chip → stage)
  spacing-elevation.html      Stroke + shadow elevation
  components-buttons.html     Buttons & primary CTA
  components-chips.html       Chip / pill states
  components-fields.html      Text fields + picker
  components-card.html        Card / panel anatomy
  components-sidebar-row.html Sidebar row states
  components-status.html      Status pills & badges

ui_kits/
  mac-app/                    The macOS app — UI kit
    README.md                 Kit overview + per-file map
    index.html                Interactive prototype (all six tabs + Generate)
    icons.jsx                 SF Symbols → inline SVG approximations
    Card.jsx                  GlassCard + SectionHead primitives
    Sidebar.jsx               200-px sidebar + brand lockup + footer player
    GenerationScreens.jsx     Custom Voice / Voice Design / Voice Cloning
    LibraryScreens.jsx        History / Saved Voices / Settings
```

---

## Substitutions and flags

- **Fonts.** The Vocello app uses system SF Pro Text, SF Pro Rounded, and
  New York. We rely on the platform stack (`-apple-system`,
  `ui-rounded`, `ui-serif`). On non-Apple platforms the closest Google Fonts
  matches are **Inter** (text), **Nunito** (rounded), and **Newsreader**
  (serif). Production marketing surfaces should embed actual Apple fonts
  via the Apple Developer site rather than substituting.
- **Icons.** SF Symbols can't be embedded on the web; hand-authored inline SVG
  approximations are the substitute (`ui_kits/mac-app/icons.jsx`). See `ICONOGRAPHY`.
- **Glass.** The CSS approximations of Liquid Glass in `colors_and_type.css`
  use `backdrop-filter: blur` + a tint layer. Real Liquid Glass in macOS 26
  refracts a live aurora behind the canvas; the CSS version is a static
  shorthand.

If you find a Vocello surface this kit can't reproduce, please flag it and
we'll either add the token or document the gap explicitly.
