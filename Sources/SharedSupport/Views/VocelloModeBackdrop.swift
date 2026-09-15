import SwiftUI

/// Warm mode-tinted wash behind the Studio surfaces on both platforms: the
/// canvas colour with a radial tint anchored to the top edge, fading to clear
/// by mid-screen. It is what gives each mode its identity before any control
/// is drawn, so the two apps share one recipe rather than two gradients that
/// drift. Mirrors `.vc-mode-backdrop`, including the CSS `mix-blend-mode:
/// plus-lighter` semantics via `.blendMode(.plusLighter)`.
///
/// Reduce Transparency is passed in rather than read from the environment:
/// iOS resolves it through its own `iosReduceTransparencyEnabled` key and
/// macOS through `accessibilityReduceTransparency`, and each platform's
/// wrapper keeps its own source.
struct VocelloModeBackdrop: View {
    let tint: Color
    let intensity: Intensity
    let reduceTransparency: Bool

    enum Intensity {
        case whisper
        case warm
        case loud

        /// Top-edge opacity for the tint stop in the gradient. Calibrated
        /// against the reference image: at 0.45 (warm) the tint reads as a
        /// subtle wash over the top quarter, fading to dark grey by
        /// mid-screen against the `#161823` canvas base.
        var topOpacity: Double {
            switch self {
            case .whisper: return 0.25
            case .warm:    return 0.45
            case .loud:    return 0.70
            }
        }
    }

    init(tint: Color, intensity: Intensity = .warm, reduceTransparency: Bool) {
        self.tint = tint
        self.intensity = intensity
        self.reduceTransparency = reduceTransparency
    }

    var body: some View {
        if reduceTransparency {
            // Flat fallback — the design system requires opaque alternatives.
            VocelloTheme.Surface.canvas
                .ignoresSafeArea()
        } else {
            GeometryReader { proxy in
                let radius = max(proxy.size.width * 0.72, proxy.size.height * 0.52)

                ZStack {
                    VocelloTheme.Surface.canvas
                    RadialGradient(
                        stops: [
                            .init(color: tint.opacity(intensity.topOpacity), location: 0.0),
                            .init(color: tint.opacity(intensity.topOpacity * 0.42), location: 0.34),
                            .init(color: .clear, location: 0.62)
                        ],
                        center: UnitPoint(x: 0.5, y: 0.0),
                        startRadius: 0,
                        endRadius: radius
                    )
                    .scaleEffect(x: 1.55, y: 0.92, anchor: .top)
                    .blendMode(.plusLighter)
                    .allowsHitTesting(false)
                }
            }
            .ignoresSafeArea()
        }
    }
}
