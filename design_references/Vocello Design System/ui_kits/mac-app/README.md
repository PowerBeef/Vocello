# Vocello macOS app — UI kit

A hi-fi recreation of the Vocello 2.0 macOS shell. Built by reading
[`PowerBeef/Vocello/Sources/Views/`](https://github.com/PowerBeef/Vocello/tree/main/Sources/Views)
— specifically `AppTheme.swift`, `LayoutConstants.swift`, and the four core
view trees. The kit covers the entire app surface area:

| Tab | Source view |
|---|---|
| Custom Voice | `Sources/Views/Generate/CustomVoiceView.swift` |
| Voice Design | `Sources/Views/Generate/VoiceDesignView.swift` |
| Voice Cloning | `Sources/Views/Generate/VoiceCloningView.swift` |
| History | `Sources/Views/Library/HistoryView.swift` |
| Saved Voices | `Sources/Views/Library/VoicesView.swift` |
| Settings | `Sources/Views/Settings/*` |

The shell is **macOS 26 Liquid Glass + dark canvas**, mirroring the shipped
app. Light mode tokens exist in `../../colors_and_type.css` but the index
defaults to dark — Vocello's home.

## Files

- `index.html` — interactive shell with all six tabs + a working
  "Generate" interaction that populates a player in the sidebar footer.
  Use as the front door.
- `icons.jsx` — SF Symbols → inline SVG approximations. **This is a
  substitution.** Real Vocello uses Apple's bundled SF Symbols which
  can't be embedded on the web. Stroke weight (1.6–1.8) and visual
  register match `regular` SF Symbols.
- `Card.jsx` — `GlassCard` + `SectionHead` primitives. Mirrors
  `NativeSurfaceStyle` / `StudioSectionCard` from `AppTheme.swift`.
- `Sidebar.jsx` — 200 px sidebar with brand lockup, grouped sections,
  per-mode selection rail, and footer player + engine status.
- `GenerationScreens.jsx` — Custom Voice, Voice Design, Voice Cloning.
  Each is the same two-card structure (Configuration → Script) with the
  mode tint applied through `cardGlassTint` on the cards and a top-anchor
  radial backdrop on the canvas.
- `LibraryScreens.jsx` — History (table of takes), Saved Voices (grid of
  voice cards), Settings → Model Downloads.

## Interactions wired up

- Sidebar selection — full per-mode treatment, hover state, selection rail.
- Speaker / Delivery / Intensity / Source pickers — native `<select>`
  styled to match SwiftUI's `Picker(.menu)`.
- Speed / Quality segmented toggle — works, persists across tabs.
- Voice Cloning gate — composer is disabled until a reference is added
  (matches the `WorkflowReadinessNote` gate in the codebase).
- "Generate" — fake 1.2 s render, then populates a player capsule in the
  sidebar footer with mode-aware title/subtitle. Player has working
  play/pause.

## Intentionally simplified

These are visual recreations, not production stand-ins:

- No real audio is played.
- The waveform isn't a real waveform.
- "Import reference audio…" just sets a fake filename; there's no file
  picker.
- History, Saved Voices, and Settings show fixed sample data.
- The "Batch" button is decorative.
- Reduce Transparency / Reduce Motion fall back to the same dark fills
  (the CSS `@media (prefers-reduced-motion)` is honored but there isn't
  much motion to suppress).

## How to extend

To build a new Vocello surface (a marketing page, a slide, a feature
mock), copy the relevant component files into your new file's directory
and import them the same way `index.html` does. Tokens live in
`../../colors_and_type.css` — use the semantic ones (`--bg-card`,
`--mode-clone`, etc.) rather than the raw ramps so the file ports cleanly
between light and dark.
