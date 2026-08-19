---
target: Vocello macOS app UI
total_score: 31
max_score: 40
na_heuristics:
p0_count: 0
p1_count: 3
timestamp: 2026-08-06T15-07-34Z
slug: sources-contentview-swift
---
Method: dual-agent (A: design review · B: detector/evidence)

# Vocello macOS UI — Design Critique (2026-08-06)

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 4 | Best-in-class readiness grammar; unexplained glass→solid flip at generation start |
| 2 | Match System / Real World | 3 | Jargon leaks: "Reusable Qwen3 clone prompt", "1.7B 4-bit"; Speed vs Delivery collision |
| 3 | User Control and Freedom | 3 | Cancel/retake/cancel-download strong; deletes confirm-only, no undo |
| 4 | Consistency and Standards | 2 | ControlGroup discards the designed Generate CTA; gold vs system-blue accent schism; two focus-ring languages |
| 5 | Error Prevention | 4 | Consent gate, requirement-gated Generate, recording duration gate, pre-generation quality warnings |
| 6 | Recognition Rather Than Recall | 3 | Seed pinning hidden in context menu; icon-only History toolbar menus |
| 7 | Flexibility and Efficiency | 3 | ⌘1–6, ⌘Return, transport keys, batch, drag-drop; no History bulk actions |
| 8 | Aesthetic and Minimalist Design | 3 | "Ready" ×3 in one panel; per-row repeated jargon in Voices; "AI·TTS" self-label |
| 9 | Error Recovery | 3 | Model-store copy excellent; raw localizedDescription in delete/export alerts |
| 10 | Help and Documentation | 3 | Dense .help tooltips; no task-level help (acceptable) |
| **Total** | | **31/40** | **Good — solid foundation, address weak areas** |

## Design Specificity Verdict
Authored-for-this-product (mode-color system in glass/backdrop/focus/CTA; emotion palette with written rationale; §K performance gate as brand principle in the render pipeline; product-specific readiness grammar). Slips: system-blue toolbar button/focus rings, stock empty states, underscored voice names.

Deterministic scan: detect.mjs exit 0 with 0 files scanned — Swift is outside its scannable extensions; honestly inapplicable. Mechanical evidence came from a code scan + 11 smoke screenshots instead: 10+ unscaled font literals, 0.5/0.75-pt hairlines across AppTheme with zero backingScaleFactor handling anywhere, uncapped Library/Settings widths, 150-pt search field clipping its own text (screenshot-confirmed), tier labels truncating with free space remaining, one out-of-theme color literal (SavedVoiceSheet Color(white:0.16)), vocelloGold defined as four independent literals, tracking(1.4) fixed.

## Priority Issues
- [P1-A] ControlGroup collapses the Generate CTA into an unlabeled icon sliver (TextInputView.swift:63-96). Code declares borderedProminent + gold + label + minWidth 100; shipped UI shows "Batch | waveform-glyph". Confirmed in code, smoke screenshots, and live capture. Cancel likely same. Fix: replace ControlGroup with HStack.
- [P1-B] First-run cloning dead-ends into Settings for consent (VoiceCloningView.swift:44-45; SettingsView.swift:60-71). Fix: inline one-time acknowledgment in the cloning readiness footer writing the same key.
- [P1-C] Accent schism: untinted borderedProminent "Add Voice Sample" renders system blue (ContentView.swift:650-657); blue system focus rings in sheets/toolbar vs custom gold vocelloFocusRing in canvas. Fix: tint + one focus-ring policy.
- [P2-D] "Ready" stated three ways simultaneously in one panel (CustomVoiceView.swift:65-71 + card badge). Trim.
- [P2-E] Library sprawl: History/Voices/Settings uncapped width (generation screens cap at 980); repeated per-row jargon; underscored display names; search field fixed 150 pt clips text.

## Scaled-Display Findings (systemic)
Depth model rides on 0.5–0.75-pt hairlines + 3–4% luminance deltas; no backing-scale awareness anywhere. At 1x backing (More Space on 4K) hairlines round to 0 or dither; TV gamma crushes the fill deltas. Generation screens hold (980-pt cap); Library sprawls. ~10 fixed font literals ignore Larger Text; fixed sheets (480/520 pt) and popovers (340/360 pt) squeeze at max text sizes. Waveform unplayed bars at opacity 0.12 vanish on crushed panels. defaultSize 720×560 is a postage stamp on 4K. Banding risk in modeCanvasBackdrop radial. 60 Hz motion tokens safe; §K full-chrome flip is the most visible motion event and is unstyled.

## Persona Red Flags
- Alex: Generate reachable visibly only via mystery glyph; ⌘Return hidden (opacity-0.001 bridge, no menu presence); seed pinning context-menu-only; no bulk History ops; 150-pt search field.
- Sam: WorkflowReadinessNote announces literal "ready=true" debug token (GenerationWorkflowView.swift:150); sidebar waveform seek click-only (no adjustableAction/keyboard); player dismiss xmark has no accessibilityLabel; batch editor never shows focus stroke (isFocused .constant(false)); dark-only pin + faint strokes hurt low-vision users.
- Robin (8 GB privacy creator): Quality-tier memory risk visible only in hover tooltip on generation screens ("Heavy" badge exists only in Settings); no affirmative "file is on your machine" surface post-take.

## Minor Observations
"Vocello" ×3 simultaneously; Settings header over Settings row; duration placeholder "-"; raw error passthrough; HistoryRowActions also uses ControlGroup (verify rendering); inert Custom tone field at 0.6 opacity in non-custom delivery; batch gold seal near celebration ceiling; blue search focus ring against gold row in one frame.

## Questions to Consider
1. Where does the hero take a bow? (Finished take lands in a 24-pt sidebar strip, maximum distance from the Generate gesture.)
2. Is dark-only a brand decision or a scope decision?
3. Can "Speed/Quality" survive sitting next to "Delivery"? ("Compact/Full" + inline memory cost would end the collision.)
4. Could the §K glass flip become a styled gesture instead of reading as a glitch?
