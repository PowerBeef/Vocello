import SwiftUI

/// The glass-or-solid body shared by both platforms' gates. The caller owns
/// the gate decision (`isGated`: Reduce Transparency or the generation
/// performance gate); this modifier only renders it, so the visual language
/// stays identical on iOS (`IOSGatedGlassModifier`) and macOS (`GatedGlass`).
///
/// One view tree for both states (A13-52): the gate varies the glass by value
/// (`Glass.identity` applies no effect) and the solid backing by a background,
/// never by branching around `content`. A branch would give the wrapped
/// subtree a new identity on every gate flip, which happens at each generation
/// start and finish, and drop its state, focus and keyboard (a text field
/// in the subtree, or a whole sheet panel).
struct VocelloGlassSurface<S: Shape>: ViewModifier {
    let tint: Color
    let shape: S
    let interactive: Bool
    /// Painted only while gated, for surfaces whose base chrome does not
    /// already include a solid backing.
    let gatedFill: Color?
    let isGated: Bool

    func body(content: Content) -> some View {
        content
            .background {
                if isGated, let gatedFill {
                    shape.fill(gatedFill)
                }
            }
            .glassEffect(glass, in: shape)
    }

    private var glass: Glass {
        guard !isGated else { return .identity }
        let tinted = Glass.regular.tint(tint)
        return interactive ? tinted.interactive() : tinted
    }
}
