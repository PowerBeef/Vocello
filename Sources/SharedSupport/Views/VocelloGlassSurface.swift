import SwiftUI

/// The glass-or-solid body shared by both platforms' gates. The caller owns
/// the gate decision (`isGated`: Reduce Transparency or the generation
/// performance gate); this modifier only renders one of the two branches, so
/// the visual language stays identical on iOS (`IOSGatedGlassModifier`) and
/// macOS (`GatedGlass`).
struct VocelloGlassSurface<S: Shape>: ViewModifier {
    let tint: Color
    let shape: S
    let interactive: Bool
    /// Painted only while gated, for surfaces whose base chrome does not
    /// already include a solid backing.
    let gatedFill: Color?
    let isGated: Bool

    @ViewBuilder
    func body(content: Content) -> some View {
        if isGated {
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
