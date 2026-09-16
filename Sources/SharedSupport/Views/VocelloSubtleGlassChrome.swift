import SwiftUI

/// The solid part of the subtle glass surface both apps draw under their
/// Liquid Glass gate: a base fill, a 0.8 pt white hairline at the caller's
/// opacity and a 0.55 pt inner hairline inset by 0.65 pt. The recipe was two
/// identical copies (`iosSubtleGlassSurface`, `macSubtleGlassSurface`) that
/// differed only by the `Theme` / `MacTheme` prefix; since UIF-02 each
/// platform's modifier applies this chrome and then its own gated glass
/// (`iosGatedGlass` / `macGatedGlass`), so the gate stays per platform and
/// the material stays in one place.
struct VocelloSubtleGlassChrome<S: InsettableShape>: ViewModifier {
    let shape: S
    let fill: Color
    let strokeOpacity: Double

    func body(content: Content) -> some View {
        content
            .background {
                shape
                    .fill(fill)
            }
            .overlay {
                shape
                    .stroke(Color.white.opacity(strokeOpacity), lineWidth: 0.8)
                    .allowsHitTesting(false)
            }
            .overlay {
                shape
                    .inset(by: 0.65)
                    .stroke(VocelloTheme.Surface.glassInnerStroke, lineWidth: 0.55)
                    .allowsHitTesting(false)
            }
    }
}

enum VocelloSubtleGlass {
    /// The glass tint laid over `VocelloSubtleGlassChrome` on both platforms:
    /// the mode-aware glass tint at 0.9 intensity.
    static func glassTint(_ tint: Color?) -> Color {
        VocelloTheme.glassTint(tint, intensity: 0.9)
    }
}

extension View {
    func vocelloSubtleGlassChrome<S: InsettableShape>(
        in shape: S,
        fill: Color,
        strokeOpacity: Double
    ) -> some View {
        modifier(VocelloSubtleGlassChrome(shape: shape, fill: fill, strokeOpacity: strokeOpacity))
    }
}
