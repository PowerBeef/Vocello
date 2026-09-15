import SwiftUI

/// Generation performance gate (benchmarks/OPTIMIZATION.md §K): Liquid Glass's
/// continuous compositor work costs ~23% engine RTF on the 8 GB tier while a
/// window showing glass is visible (measured 1.37 with glass vs 1.84 with the
/// solid-fill fallback during generation). While a generation is active the
/// glass surfaces fall back to the same solid-fill design Reduce Transparency
/// uses; glass returns when the engine goes idle.
private struct GenerationPerformanceGateKey: EnvironmentKey {
    static let defaultValue = false
}

extension EnvironmentValues {
    var generationPerformanceGate: Bool {
        get { self[GenerationPerformanceGateKey.self] }
        set { self[GenerationPerformanceGateKey.self] = newValue }
    }
}

/// The one place the macOS Liquid Glass render decision lives (W1-G): glass
/// renders only on liquid builds with Reduce Transparency off and the §K
/// generation performance gate inactive; otherwise the caller's solid-fill
/// fallback. Hand-rolled copies of this condition drifted (the eight direct
/// glass sites shipped without the Reduce Transparency check until
/// 2026-08-05); routing every glass surface through this container makes the
/// invariant structural instead of remembered.
struct GatedGlass<Glass: View, Fallback: View>: View {
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Environment(\.generationPerformanceGate) private var performanceGate

    @ViewBuilder let glass: () -> Glass
    @ViewBuilder let fallback: () -> Fallback

    var body: some View {
        #if QW_UI_LIQUID
        if !reduceTransparency, !performanceGate {
            glass()
        } else {
            fallback()
        }
        #else
        fallback()
        #endif
    }
}

/// Liquid Glass through `GatedGlass`, rendered by the body both platforms
/// share (`VocelloGlassSurface`), so a macOS surface and its iOS twin are
/// the same modifier with a different gate.
private struct MacGatedGlassModifier<S: Shape>: ViewModifier {
    let tint: Color
    let shape: S
    let interactive: Bool
    let gatedFill: Color?

    func body(content: Content) -> some View {
        GatedGlass {
            content.modifier(
                VocelloGlassSurface(
                    tint: tint,
                    shape: shape,
                    interactive: interactive,
                    gatedFill: gatedFill,
                    isGated: false
                )
            )
        } fallback: {
            content.modifier(
                VocelloGlassSurface(
                    tint: tint,
                    shape: shape,
                    interactive: interactive,
                    gatedFill: gatedFill,
                    isGated: true
                )
            )
        }
    }
}

/// The iOS subtle glass surface (`iosSubtleGlassSurface`) on macOS: a solid
/// base fill, an outer and an inset hairline, then the gated glass.
private struct MacSubtleGlassSurfaceModifier<S: InsettableShape>: ViewModifier {
    let shape: S
    let tint: Color?
    let fill: Color
    let strokeOpacity: Double
    let interactive: Bool

    func body(content: Content) -> some View {
        content
            .background { shape.fill(fill) }
            .overlay {
                shape
                    .stroke(Color.white.opacity(strokeOpacity), lineWidth: 0.8)
                    .allowsHitTesting(false)
            }
            .overlay {
                shape
                    .inset(by: 0.65)
                    .stroke(MacTheme.Surface.glassInnerStroke, lineWidth: 0.55)
                    .allowsHitTesting(false)
            }
            .macGatedGlass(
                tint: MacTheme.glassTint(tint, intensity: 0.9),
                in: shape,
                interactive: interactive
            )
    }
}

extension View {
    /// Apply Liquid Glass through the macOS gate. `tint` is the final glass
    /// tint; `gatedFill` supplies a solid backing for the gated branch when
    /// the caller's own chrome does not already paint one.
    func macGatedGlass<S: Shape>(
        tint: Color,
        in shape: S,
        interactive: Bool = false,
        gatedFill: Color? = nil
    ) -> some View {
        modifier(
            MacGatedGlassModifier(
                tint: tint,
                shape: shape,
                interactive: interactive,
                gatedFill: gatedFill
            )
        )
    }

    func macSubtleGlassSurface<S: InsettableShape>(
        in shape: S,
        tint: Color? = nil,
        fill: Color = MacTheme.Surface.glassSurface,
        strokeOpacity: Double = 0.12,
        interactive: Bool = false
    ) -> some View {
        modifier(
            MacSubtleGlassSurfaceModifier(
                shape: shape,
                tint: tint,
                fill: fill,
                strokeOpacity: strokeOpacity,
                interactive: interactive
            )
        )
    }
}
