# Vocello Website Design Context

## Visual Register
Dark-first premium brand site for a native Mac app. The page should feel like a refined extension of the app, not a separate marketing dashboard.

## Color
- Canonical canvas: charcoal and smoked-glass dark surfaces.
- Primary accent: Vocello gold, used sparingly for selection, primary actions, and emphasis.
- Secondary mode tints: lavender for Voice Design, terracotta for Voice Cloning.
- Status colors stay tiny. Avoid neon and blue-purple SaaS gradients.
- A soft, blurred aura of the mode colors may sit behind a product stage (the hero, the selected
  mode's screenshot, the iPhone, the download icon). Never on text, buttons or cards.

## Type
- Use the system stack: SF Pro Text for body, SF Pro Rounded for the wordmark, New York or a system serif only for large brand display moments.
- Body copy should stay readable, usually under 75 characters per line.
- Hierarchy should come from scale, weight, and spacing before ornament.

## Layout
- Keep the app screenshot visible early. The product is the proof.
- Use 16px cards and 22px stage surfaces, but avoid repeated identical card grids.
- Prefer bands, comparison surfaces, and product-led modules over generic card rows.
- Mobile should preserve rhythm: avoid turning every section into the same long stack.
- Four layout tiers:

  | Tier | Widths |
  | --- | --- |
  | Phone | below 600 px |
  | Small tablet and landscape phone | 600 to 899 px |
  | Tablet | 900 to 1199 px |
  | Desktop | 1200 px and up |

  Display type and section spacing scale fluidly between them. A short landscape screen
  tightens the bar and the type and keeps screenshots within its height.
- Alignment: the hero and the closing call to action center, and so may a short section intro
  (a note, a headline, one sentence) set over a centered control or grid. Everything else,
  headings included, is left-aligned at every width; centered paragraphs read with two ragged
  edges.
- The home page speaks to people who make voices. Developer detail lives on /cli/ and
  /engineering/, reached from the For developers tiles.
- The bar is opaque and never lets page text show through it. Below the desktop tier, a menu
  button opens a sheet with every section; links never float alone in the bar.
- Touch: every control has a 44 px target, and hover styling exists only for fine pointers.

## Motion
- Quiet and purposeful. Waveform and tab transitions may move, but nothing should bounce, shimmer, or pulse for decoration.
- The hero rises in once on load; sections fade up as they enter view, and their facts follow in
  turn. The mode switcher settles its panel the way the menu sheet does.
- Respect `prefers-reduced-motion`.

## Bans
- No gradient text.
- No side-stripe card accents.
- No emoji.
- No decorative glassmorphism as a default.
- No repeated uppercase eyebrow scaffolding.
