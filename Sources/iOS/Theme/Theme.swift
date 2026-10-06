import SwiftUI
import UIKit
import QwenVoiceCore

/// Canonical iOS design tokens for the Vocello iOS app.
///
/// Since 2026-09-15 the color, radius, spacing and motion values live in the
/// shared `VocelloTheme` (`Sources/SharedSupport/Theme`), which both apps
/// read; this namespace forwards to it so every iOS call site keeps its name
/// and the `UIColor` twins the UIKit bridges need stay here. The values
/// derive from `design_references/Vocello iOS/tokens.css`; where a shipped
/// value diverged from tokens.css, the shipped value wins and the token's
/// comment records the delta. The legacy `IOSBrandTheme`, `IOSAppTheme`,
/// `IOSCornerRadius`, `IOSDesignMotion`, and `IOSSelectionMotion`
/// namespaces were absorbed here (IUI-5 D10b); this is the ONE iOS token
/// namespace — add new tokens here, never a parallel enum.
///
/// The app is forced to `.preferredColorScheme(.dark)` at the window
/// level, so all tokens are dark-mode variants. If light mode is ever
/// supported, replace the `UIColor` initializers with dynamic
/// `UIColor { traits in ... }` providers and add light siblings.
enum Theme {
    // MARK: - Brand

    enum Brand {
        /// Vocello primary — warm golden. `--vocello-gold` in tokens.css.
        static let gold = VocelloTheme.Brand.gold

        /// 18% wash of the brand color used for chip / tab tints.
        static let goldSoft = VocelloTheme.Brand.goldSoft

        /// Per-mode hues.
        static let modeCustom = gold
        /// `#BFAADC` — `--mode-design`.
        static let modeDesign = VocelloTheme.Brand.modeDesign
        /// `#DBA887` — `--mode-cloning`.
        static let modeClone = VocelloTheme.Brand.modeClone

        /// Neutral silver used for the settings tab.
        static let silver = VocelloTheme.Brand.silver

        /// Warm neutral used for the library (Voices) tab.
        static let library = VocelloTheme.Brand.library

        /// 12% gold glow behind primary actions.
        static let goldGlow = VocelloTheme.Brand.goldGlow

        /// 7% warm-white sheen for highlighted chrome.
        static let highlightGlow = VocelloTheme.Brand.highlightGlow

        static func modeColor(_ mode: GenerationMode) -> Color {
            switch mode {
            case .custom: return modeCustom
            case .design: return modeDesign
            case .clone: return modeClone
            }
        }
    }

    // MARK: - Surfaces (dark-mode ramp)

    enum Surface {
        /// `#161823` — the app's underlay. `--canvas-bg`.
        static let canvas = VocelloTheme.Surface.canvas

        /// Slightly darker base for screen bottoms. Matches the existing
        /// `IOSBrandTheme.canvasBottom` gradient end-point.
        static let canvasBottom = VocelloTheme.Surface.canvasBottom

        /// `#1C1E26` — stage holds the configuration panel area.
        static let stage = VocelloTheme.Surface.stage

        /// `#0D0E12` — darker recess inside the stage. `--card-fill`.
        static let card = VocelloTheme.Surface.card

        /// `#11131A` — recessed surface between card + field. `--inline-fill`.
        static let inline = VocelloTheme.Surface.inline

        /// Text input fill. Shipped truth (D10b): the app has always rendered
        /// this darker fill (was `IOSBrandTheme.inputFill`); the tokens.css
        /// `--field-fill` value `#2A2C36` never shipped. Changing it is a
        /// deliberate design decision, not a cleanup.
        static let field = VocelloTheme.Surface.field
        static let fieldUIColor = UIColor(red: 0.120, green: 0.126, blue: 0.148, alpha: 1)

        /// Warm hairline stroke on input fields (was `IOSBrandTheme.inputStroke`).
        static let fieldStroke = VocelloTheme.Surface.fieldStroke

        /// Elevated panel fill for cards over the canvas (was `IOSBrandTheme.surface`).
        static let panel = VocelloTheme.Surface.panel

        /// Muted sibling of `panel` (was `IOSBrandTheme.surfaceMuted`).
        static let panelMuted = VocelloTheme.Surface.panelMuted

        /// Warm hairline stroke on panels (was `IOSBrandTheme.surfaceStroke`).
        static let panelStroke = VocelloTheme.Surface.panelStroke

        /// Opaque banner / toast fill (was `IOSBrandTheme.bannerFill`).
        static let banner = VocelloTheme.Surface.banner

        /// Mode-switcher pill fill (was `IOSBrandTheme.modeSwitcherFill`).
        static let selector = VocelloTheme.Surface.selector

        /// Warm hairline on the mode-switcher pill (was `IOSBrandTheme.modeSwitcherStroke`).
        static let selectorStroke = VocelloTheme.Surface.selectorStroke

        /// Solid base under glassy card surfaces (was `IOSAppTheme.glassSurfaceFill`).
        static let glassSurface = VocelloTheme.Surface.glassSurface

        /// Muted sibling for secondary glass surfaces (was `IOSAppTheme.glassSurfaceFillMuted`).
        static let glassSurfaceMuted = VocelloTheme.Surface.glassSurfaceMuted

        /// Tab bar / dock smoke. Shipped truth (D10b): the app has always used
        /// this darker smoke (was `IOSBrandTheme.tabBarBackground`); the
        /// tokens.css `--rail-bg` value `#171A1F` never shipped.
        static let dock = VocelloTheme.Surface.dock

        /// Glassy floating panel fill (was `IOSAppTheme.glassFloatingFill`).
        static let glassFloating = VocelloTheme.Surface.glassFloating

        /// Hairline divider between rows on dark surfaces.
        static let hairline = VocelloTheme.Surface.hairline

        /// Outer stroke on glassy cards.
        static let glassOuterStroke = VocelloTheme.Surface.glassOuterStroke
        static let glassInnerStroke = VocelloTheme.Surface.glassInnerStroke
    }

    // MARK: - Text colors

    enum Text {
        /// `#F2F0EB` — primary text on dark canvas.
        static let primary = VocelloTheme.Text.primary
        static let primaryUIColor = UIColor(red: 0.95, green: 0.94, blue: 0.92, alpha: 1)

        /// `#C7C2B8` — warm-tinted secondary text.
        static let secondary = VocelloTheme.Text.secondary

        /// `#9E998C` — warm-tinted tertiary text (placeholders, eyebrows).
        static let tertiary = VocelloTheme.Text.tertiary
        /// Cool-gray placeholder text. Lightened from (0.50,0.53,0.58) so it clears
        /// WCAG-AA 4.5:1 on every surface incl. the lightest field fill (was 3.84:1
        /// on `Surface.field`; now ≥5.3:1) while staying clearly dimmer than entered text.
        static let placeholderUIColor = UIColor(red: 0.60, green: 0.63, blue: 0.68, alpha: 1)

        /// Foreground ink on accent-filled buttons. Warm near-black.
        static let onAccent = VocelloTheme.Text.onAccent
        static let onAccentPressed = VocelloTheme.Text.onAccentPressed
    }

    // MARK: - Status / health

    enum Status {
        static let healthy = VocelloTheme.Status.healthy
        static let guarded = VocelloTheme.Status.guarded
        static let critical = VocelloTheme.Status.critical
    }

    // MARK: - Accent helpers

    /// Accent surface fill (10% opacity tint).
    static func accentSurface(_ tint: Color) -> Color { VocelloTheme.accentSurface(tint) }

    /// Strong mode-tinted stroke. 34% per the May 2026 macOS chip audit.
    static func accentStroke(_ tint: Color) -> Color { VocelloTheme.accentStroke(tint) }

    /// Accent wash for selected chips / pills. 20% per the audit.
    static func accentWash(_ tint: Color) -> Color { VocelloTheme.accentWash(tint) }

    /// Mode-aware glass tint. 14% for tinted, 10% for neutral.
    static func glassTint(_ tint: Color? = nil, intensity: Double = 1.0) -> Color {
        VocelloTheme.glassTint(tint, intensity: intensity)
    }

    static func accentGradient(_ tint: Color) -> LinearGradient {
        VocelloTheme.accentGradient(tint)
    }

    static func softGradient(for tint: Color) -> LinearGradient {
        VocelloTheme.softGradient(for: tint)
    }

    // MARK: - Shared scales (A13-04: forwarded, never re-declared)

    /// Corner radii (matches tokens.css), incl. the shared `row`.
    typealias Radius = VocelloTheme.Radius
    /// Border widths.
    typealias Stroke = VocelloTheme.Stroke
    /// Named shadow tiers.
    typealias Elevation = VocelloTheme.Elevation
    /// Dimming levels.
    typealias Opacity = VocelloTheme.Opacity

    // MARK: - Hit targets

    enum HitTarget {
        /// Apple's minimum comfortable touch target, and the size the app's
        /// own controls already use in 42 other places. It is named here
        /// because four close and back buttons did not: they were sized to
        /// their 40 pt circle, and a control's drawn size and its touchable
        /// size are not the same decision.
        static let minimum: CGFloat = 44
    }

    /// Spacing on the 4-pt grid, plus the shared off-grid `tight` and `snug`.
    typealias Spacing = VocelloTheme.Spacing

    /// Motion curves (cubic-bezier 0.22, 1, 0.36, 1): state changes, sheets,
    /// the selector pill and the selection micro-motion absorbed from
    /// `IOSSelectionMotion` (D10b).
    typealias Motion = VocelloTheme.Motion

    typealias Branding = VocelloTheme.Branding
}
