import SwiftUI
import UIKit

// View modifiers + reusable shape helpers that build on `Theme`. Kept
// separate from `Theme.swift` so the token namespace stays scannable.

// MARK: - Gated glass (the one condition)

/// iOS twin of the macOS `GatedGlass` container in `AppTheme.swift`
/// (IUI-5 D10a): the ONE place that decides whether a Liquid Glass surface
/// may render glass. Reduce Transparency and the fixed-refresh generation
/// performance gate share the same solid-fallback branch; every glass
/// surface routes here and never hand-rolls the condition. (Replaces the
/// never-adopted `ThemeGlassSurfaceModifier` twin — the live surface chrome
/// stays with `iosSubtleGlassSurface`, which now delegates its gate here.)
struct IOSGatedGlassModifier<S: Shape>: ViewModifier {
    let tint: Color
    let shape: S
    let interactive: Bool
    /// Painted only while gated, for surfaces whose base chrome does not
    /// already include a solid backing.
    let gatedFill: Color?

    @Environment(\.iosReduceTransparencyEnabled) private var reduceTransparency
    @Environment(\.iosGenerationPerformanceGate) private var performanceGate

    @ViewBuilder
    func body(content: Content) -> some View {
        if reduceTransparency || performanceGate {
            if let gatedFill {
                content.background { shape.fill(gatedFill) }
            } else {
                content
            }
        } else if interactive {
            content.glassEffect(.regular.tint(tint).interactive(), in: shape)
        } else {
            content.glassEffect(.regular.tint(tint), in: shape)
        }
    }
}

extension View {
    /// Apply Liquid Glass through the shared gate. `tint` is the final glass
    /// tint (callers compose it from their token helpers); `gatedFill`
    /// supplies a solid backing for the gated branch when the caller's own
    /// chrome doesn't already paint one.
    func iosGatedGlass<S: Shape>(
        tint: Color,
        in shape: S,
        interactive: Bool = false,
        gatedFill: Color? = nil
    ) -> some View {
        modifier(
            IOSGatedGlassModifier(
                tint: tint,
                shape: shape,
                interactive: interactive,
                gatedFill: gatedFill
            )
        )
    }
}

// MARK: - Dynamic Type for fixed point sizes

/// Scales a fixed `.system(size:)` font with Dynamic Type, relative to a text
/// style (default `.body`). SwiftUI's `.font(.system(size:))` does not scale —
/// this restores accessibility scaling for content text while keeping the
/// design's exact base sizes. Use for Text content; leave fixed glyph/chrome
/// sizes (icons in fixed frames, decorative waveforms) as-is.
private struct IOSScaledSystemFont: ViewModifier {
    @ScaledMetric private var scaledSize: CGFloat
    private let weight: Font.Weight
    private let design: Font.Design
    private let monospacedDigit: Bool

    init(
        size: CGFloat,
        weight: Font.Weight,
        design: Font.Design,
        monospacedDigit: Bool,
        relativeTo style: Font.TextStyle
    ) {
        _scaledSize = ScaledMetric(wrappedValue: size, relativeTo: style)
        self.weight = weight
        self.design = design
        self.monospacedDigit = monospacedDigit
    }

    func body(content: Content) -> some View {
        let font = Font.system(size: scaledSize, weight: weight, design: design)
        content.font(monospacedDigit ? font.monospacedDigit() : font)
    }
}

extension View {
    /// Dynamic-Type-scaling replacement for `.font(.system(size:weight:))` on
    /// content text (X4 program: `monospacedDigit` covers the
    /// `.system(size:).monospacedDigit()` chains).
    func iosScaledFont(
        size: CGFloat,
        weight: Font.Weight = .regular,
        design: Font.Design = .default,
        monospacedDigit: Bool = false,
        relativeTo style: Font.TextStyle = .body
    ) -> some View {
        modifier(
            IOSScaledSystemFont(
                size: size,
                weight: weight,
                design: design,
                monospacedDigit: monospacedDigit,
                relativeTo: style
            )
        )
    }
}

// MARK: - Common shape factories

enum ThemeShape {
    static func card() -> RoundedRectangle {
        RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous)
    }

    static func input() -> RoundedRectangle {
        RoundedRectangle(cornerRadius: Theme.Radius.input, style: .continuous)
    }

    static func stage() -> RoundedRectangle {
        RoundedRectangle(cornerRadius: Theme.Radius.stage, style: .continuous)
    }

    static func chip() -> RoundedRectangle {
        RoundedRectangle(cornerRadius: Theme.Radius.chip, style: .continuous)
    }

    static func pill() -> Capsule {
        Capsule(style: .continuous)
    }
}

// MARK: - Accent foreground convenience

extension Color {
    /// The "ink on accent" color used for primary CTA labels.
    static var themeOnAccent: Color { Theme.Text.onAccent }
    static var themeOnAccentPressed: Color { Theme.Text.onAccentPressed }
}

// MARK: - Modern haptics (sensoryFeedback wrapper)

/// Centralized trigger keys for `.sensoryFeedback(...trigger:)`.
///
/// Per `references/latest-apis.md` (iOS 17+) views should prefer the
/// declarative `sensoryFeedback` modifier over imperative
/// `UISelectionFeedbackGenerator()` calls. Use these enum values as the
/// trigger payload so the same event fires once per state transition.
enum ThemeFeedback {
    enum Selection: Equatable { case fire(UUID) }
}
