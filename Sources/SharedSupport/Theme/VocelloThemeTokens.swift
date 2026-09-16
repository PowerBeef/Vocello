import QwenVoiceCore
import SwiftUI

/// The one design-token namespace shared by the iOS and macOS apps (plan
/// `macos-ios-convergence-2026-09`, CONV-10). The values are the shipped iOS
/// values from `Sources/iOS/Theme/Theme.swift`, which forwards to this type;
/// the macOS screens read them through `MacTheme`. One dark palette on both
/// platforms; a light sibling would be added here, never in a parallel enum.
enum VocelloTheme {
    // MARK: - Brand

    enum Brand {
        /// Vocello primary — warm golden.
        static let gold = Color(red: 0.929, green: 0.800, blue: 0.541)
        /// 18% wash of the brand color used for chip / tab tints.
        static let goldSoft = gold.opacity(0.18)
        static let modeCustom = gold
        static let modeDesign = Color(red: 0.749, green: 0.667, blue: 0.863)
        static let modeClone = Color(red: 0.859, green: 0.659, blue: 0.529)
        /// Neutral silver used for the settings destination.
        static let silver = Color(red: 0.68, green: 0.71, blue: 0.76)
        /// Warm neutral used for the library (Voices) destination.
        static let library = Color(red: 0.75, green: 0.74, blue: 0.71)
        /// 12% gold glow behind primary actions.
        static let goldGlow = gold.opacity(0.12)
        /// 7% warm-white sheen for highlighted chrome.
        static let highlightGlow = Color(red: 0.90, green: 0.84, blue: 0.72, opacity: 0.07)

        static func modeColor(_ mode: GenerationMode) -> Color {
            switch mode {
            case .custom: return modeCustom
            case .design: return modeDesign
            case .clone: return modeClone
            }
        }
    }

    // MARK: - Surfaces (dark ramp)

    enum Surface {
        static let canvas = Color(red: 0.086, green: 0.094, blue: 0.137)
        static let canvasBottom = Color(red: 0.038, green: 0.044, blue: 0.056)
        static let stage = Color(red: 0.110, green: 0.118, blue: 0.149)
        static let card = Color(red: 0.051, green: 0.055, blue: 0.071)
        static let inline = Color(red: 0.067, green: 0.075, blue: 0.102)
        static let field = Color(red: 0.120, green: 0.126, blue: 0.148)
        static let fieldStroke = Color(red: 0.96, green: 0.92, blue: 0.82, opacity: 0.12)
        static let panel = Color(red: 0.105, green: 0.112, blue: 0.132, opacity: 0.86)
        static let panelMuted = Color(red: 0.145, green: 0.152, blue: 0.174, opacity: 0.74)
        static let panelStroke = Color(red: 0.97, green: 0.92, blue: 0.82, opacity: 0.10)
        static let banner = Color(red: 0.18, green: 0.19, blue: 0.22, opacity: 0.92)
        static let selector = Color(red: 0.135, green: 0.142, blue: 0.164, opacity: 0.82)
        static let selectorStroke = Color(red: 0.97, green: 0.92, blue: 0.82, opacity: 0.08)
        static let glassSurface = panel.opacity(0.82)
        static let glassSurfaceMuted = panelMuted.opacity(0.74)
        static let dock = Color(red: 0.075, green: 0.083, blue: 0.102, opacity: 0.93)
        static let glassFloating = dock.opacity(0.66)
        static let hairline = Color.white.opacity(0.08)
        static let glassOuterStroke = Color.white.opacity(0.12)
        static let glassInnerStroke = Color.white.opacity(0.04)
    }

    // MARK: - Text

    enum Text {
        static let primary = Color(red: 0.95, green: 0.94, blue: 0.92)
        static let secondary = Color(red: 0.78, green: 0.76, blue: 0.72)
        static let tertiary = Color(red: 0.62, green: 0.60, blue: 0.55)
        /// Cool-gray placeholder text; clears WCAG-AA 4.5:1 on every surface.
        static let placeholder = Color(red: 0.60, green: 0.63, blue: 0.68)
        static let onAccent = Color(red: 0.10, green: 0.085, blue: 0.055, opacity: 0.82)
        static let onAccentPressed = Color(red: 0.10, green: 0.085, blue: 0.055, opacity: 0.74)
    }

    // MARK: - Status

    enum Status {
        static let healthy = Color(red: 0.55, green: 0.70, blue: 0.55)
        static let guarded = Color(red: 0.85, green: 0.70, blue: 0.45)
        static let critical = Color(red: 0.85, green: 0.50, blue: 0.50)
    }

    // MARK: - Accent helpers

    static func accentSurface(_ tint: Color) -> Color { tint.opacity(0.10) }
    static func accentStroke(_ tint: Color) -> Color { tint.opacity(0.34) }
    static func accentWash(_ tint: Color) -> Color { tint.opacity(0.20) }

    static func glassTint(_ tint: Color? = nil, intensity: Double = 1.0) -> Color {
        let base = tint ?? Brand.silver
        let opacity = (tint == nil) ? 0.10 : 0.14
        return base.opacity(opacity * intensity)
    }

    static func accentGradient(_ tint: Color) -> LinearGradient {
        LinearGradient(colors: [tint, tint.opacity(0.78)], startPoint: .topLeading, endPoint: .bottomTrailing)
    }

    static func softGradient(for tint: Color) -> LinearGradient {
        LinearGradient(colors: [tint.opacity(0.92), tint.opacity(0.62)], startPoint: .topLeading, endPoint: .bottomTrailing)
    }

    // MARK: - Corner radii, spacing, motion

    enum Radius {
        static let chip: CGFloat = 8
        static let input: CGFloat = 10
        /// Rows and row-sized tiles: the list language, distinct from a
        /// card's 16. Already the de facto value at eight macOS sites before
        /// it had a name.
        static let row: CGFloat = 12
        static let card: CGFloat = 16
        static let stage: CGFloat = 22
        static let sheetGrabber: CGFloat = 3
    }

    /// Border widths. Three steps, because a surface either whispers its
    /// edge, states it, or is focused. Before these existed the app drew
    /// hairlines at 0.5, 0.55, 0.7, 0.75 and 0.8, so a chip could carry a
    /// heavier outline than the card containing it.
    enum Stroke {
        static let hairline: CGFloat = 0.5
        static let standard: CGFloat = 1
        static let focus: CGFloat = 2
    }

    /// The four shadows the apps actually use, named so a surface picks a tier
    /// instead of inventing a recipe.
    enum Elevation {
        /// A card lifted off the canvas.
        static let cardColor = Color.black.opacity(0.22)
        static let cardRadius: CGFloat = 5
        static let cardY: CGFloat = 2

        /// A tinted control's bloom (chips, the Batch square).
        static func glowColor(_ tint: Color) -> Color { tint.opacity(0.28) }
        static let glowRadius: CGFloat = 8
        static let glowY: CGFloat = 1

        /// The primary call to action: a tint bloom over a dark drop.
        static func ctaGlowColor(_ tint: Color) -> Color { tint.opacity(0.35) }
        static let ctaGlowRadius: CGFloat = 16
        static let ctaGlowY: CGFloat = 4
        static let ctaDropColor = Color.black.opacity(0.22)
        static let ctaDropRadius: CGFloat = 10
        static let ctaDropY: CGFloat = 6

        /// Chrome floating over content: the dock, a popover.
        static let floatingColor = Color.black.opacity(0.40)
        static let floatingRadius: CGFloat = 18
        static let floatingY: CGFloat = 14
    }

    /// Dimming, which the app previously expressed with six values (0.42, 0.45,
    /// 0.5, 0.55, 0.62, 0.7) for three ideas.
    enum Opacity {
        /// A control that cannot be used.
        static let disabled: Double = 0.45
        /// A value standing in for one the user has not chosen yet.
        static let placeholder: Double = 0.55
        /// Live content held back while something else has the focus.
        static let dimmed: Double = 0.5
    }

    enum Spacing {
        static let xs: CGFloat = 4
        /// Glyph to label inside a control. Off the 4 pt layout grid on
        /// purpose: controls have their own rhythm, and 6 was already the
        /// app's most common intra-control gap.
        static let tight: CGFloat = 6
        /// A row's internal gaps. Likewise off-grid and likewise already
        /// dominant, at 33 uses before it had a name.
        static let snug: CGFloat = 10
        static let sm: CGFloat = 8
        static let md: CGFloat = 12
        static let lg: CGFloat = 16
        static let xl: CGFloat = 20
        static let xxl: CGFloat = 24
        static let xxxl: CGFloat = 32
    }

    enum Motion {
        static let stateChange = Animation.easeOut(duration: 0.15)
        static let easeOut = Animation.timingCurve(0.22, 1.0, 0.36, 1.0, duration: 0.22)
        static let modePillSlide = Animation.timingCurve(0.22, 1.0, 0.36, 1.0, duration: 0.32)
        static let sheetSlideUp = Animation.timingCurve(0.22, 1.0, 0.36, 1.0, duration: 0.36)
        static let playerSheetSlideUp = Animation.timingCurve(0.22, 1.0, 0.36, 1.0, duration: 0.42)
        static let miniPlayerSlide = Animation.spring(response: 0.32, dampingFraction: 0.84, blendDuration: 0.12)
        static let press = Animation.easeOut(duration: 0.09)
        static let selection = Animation.easeOut(duration: 0.14)
        static let selectorPill = Animation.snappy(duration: 0.22, extraBounce: 0)
        static let selectorLabel = Animation.easeOut(duration: 0.12)
        static let highlight = Animation.easeOut(duration: 0.10)
        static let disclosure = Animation.easeOut(duration: 0.12)
        static let floatingPanel = Animation.spring(response: 0.30, dampingFraction: 0.84, blendDuration: 0.12)
        static let modeCrossfade = Animation.easeInOut(duration: 0.18)
    }

    enum Branding {
        static let productName = "Vocello"
        static let headerMarkAssetName = "VocelloHeaderMark"
    }
}
