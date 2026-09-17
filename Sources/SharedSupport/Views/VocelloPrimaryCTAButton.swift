import SwiftUI

/// Primary CTA "glass hero" button (Studio Generate/Install, Onboarding,
/// Recording overlay, sheet Install). Built from the same lit-tint material as
/// the selector pills (`VocelloSetupChipPill`) — a translucent tint gradient,
/// hairline white strokes, a mode-tinted glow — but dialed up to be the
/// brightest, largest member of the family so it reads as the primary action
/// while staying cohesive with the surrounding glass UI. Tints to whatever
/// color the caller passes (Studio = per-mode gold/lavender/terracotta).
/// Respects Reduce Transparency with an opaque deep-tint fill (no glow).
///
/// One body for both apps (UIF-02). The phone's `IOSPrimaryCTAButton` is
/// exactly `.dock` with `Traits.phone`; the desktop's `MacPrimaryCTAButton`
/// adds the `.compact` sheet size, the trailing key-equivalent hint and
/// `Traits.desktop`. Reduce Transparency is passed in because each platform
/// reads it from its own environment key (`iosReduceTransparencyEnabled`,
/// `accessibilityReduceTransparency`), as `VocelloModeBackdrop` does.
struct VocelloPrimaryCTAButton: View {
    /// `.dock` is the Studio's Generate button: the full-width capsule with its
    /// sheen and glow, which is what anchors the canvas. `.compact` is the
    /// desktop sheet button that hugs its label.
    ///
    /// The dock capsule's height and symbol are **not** here. They are the one
    /// pair of numbers the two apps no longer agree on, so they live in
    /// `Traits` beside the other per-platform chrome: the phone's 56 pt is
    /// right next to a 56 pt tab bar, and the desktop's is not, next to a 40 pt
    /// sidebar row. `.compact` is desktop-only and keeps its numbers here.
    enum Size {
        case dock
        case compact

        static let compactHeight: CGFloat = 34
        static let compactSymbolPointSize: CGFloat = 14

        var spansWidth: Bool { self == .dock }
        var titleFont: Font { self == .dock ? .headline : .system(size: 13, weight: .semibold) }
        var titleTracking: CGFloat { self == .dock ? -0.17 : 0 }
        var strokeLineWidth: CGFloat { self == .dock ? 0.8 : 0.75 }
    }

    /// The chrome details on which the two apps still differ. Recorded here
    /// as the pure move's inventory (UIF-02) so a later decision can converge
    /// them in one place; each platform passes its own preset and nothing
    /// rendered changes.
    struct Traits {
        /// Horizontal inset of the label inside the capsule. The phone's
        /// full-width button centres its label with no inset.
        var dockHorizontalPadding: CGFloat
        var compactHorizontalPadding: CGFloat
        /// The desktop caps the title at one line; the phone does not.
        var titleLineLimit: Int?
        /// The phone keeps the tinted glow on a disabled button (over the
        /// dimmer fill); the desktop drops it with the enabled state.
        var glowsWhenDisabled: Bool
        /// The desktop hit-tests the capsule; the phone hit-tests the frame.
        var hitTestsCapsule: Bool
        /// Height of the dock capsule and the point size of the symbol inside
        /// it. The phone's 56/18 is the original and is the reference; the
        /// desktop sits one step lower because its own control ladder does
        /// (`MacControl.primary`), and a button 16 pt taller than the sidebar
        /// row beside it read as belonging to another application.
        var dockHeight: CGFloat
        var dockSymbolPointSize: CGFloat

        static let phone = Traits(
            dockHorizontalPadding: 0,
            compactHorizontalPadding: 0,
            titleLineLimit: nil,
            glowsWhenDisabled: true,
            hitTestsCapsule: false,
            dockHeight: 56,
            dockSymbolPointSize: 18
        )

        static let desktop = Traits(
            dockHorizontalPadding: 20,
            compactHorizontalPadding: 18,
            titleLineLimit: 1,
            glowsWhenDisabled: false,
            hitTestsCapsule: true,
            dockHeight: 48,
            dockSymbolPointSize: 16
        )

        func horizontalPadding(for size: Size) -> CGFloat {
            size == .dock ? dockHorizontalPadding : compactHorizontalPadding
        }

        func height(for size: Size) -> CGFloat {
            size == .dock ? dockHeight : Size.compactHeight
        }

        func symbolPointSize(for size: Size) -> CGFloat {
            size == .dock ? dockSymbolPointSize : Size.compactSymbolPointSize
        }
    }

    let title: String
    let symbol: String?
    let tint: Color
    let isEnabled: Bool
    let size: Size
    /// A desktop nicety the phone cannot offer: the key equivalent, drawn at
    /// the trailing edge of a `.dock` button ("⌘↩" on Generate).
    let shortcutHint: String?
    let traits: Traits
    let reduceTransparency: Bool
    let action: () -> Void

    init(
        title: String,
        symbol: String? = nil,
        tint: Color,
        isEnabled: Bool = true,
        size: Size = .dock,
        shortcutHint: String? = nil,
        traits: Traits,
        reduceTransparency: Bool,
        action: @escaping () -> Void
    ) {
        self.title = title
        self.symbol = symbol
        self.tint = tint
        self.isEnabled = isEnabled
        self.size = size
        self.shortcutHint = shortcutHint
        self.traits = traits
        self.reduceTransparency = reduceTransparency
        self.action = action
    }

    // Warm off-white label, legible on the translucent tinted fill (matches the
    // app text-primary). Under Reduce Transparency the fill is a deep opaque
    // tint, so the same off-white stays legible.
    private var foregroundInk: Color {
        isEnabled ? VocelloTheme.Text.primary : VocelloTheme.Text.secondary
    }

    private var backgroundFill: AnyShapeStyle {
        if reduceTransparency {
            // Opaque deep-tint fill so the off-white label keeps contrast.
            return AnyShapeStyle(
                tint.mix(with: .black, by: isEnabled ? 0.42 : 0.70, in: .perceptual)
            )
        }

        // Same recipe as the selector pills (tint gradient over the dark
        // canvas), brighter (0.46→0.24 vs the pills' 0.30→0.14) so the CTA is
        // the standout tinted surface while staying the same translucent glass.
        return AnyShapeStyle(
            LinearGradient(
                colors: isEnabled
                    ? [tint.opacity(0.46), tint.opacity(0.24)]
                    : [tint.opacity(0.14), tint.opacity(0.08)],
                startPoint: .top,
                endPoint: .bottom
            )
        )
    }

    var body: some View {
        Button(action: {
            if isEnabled { action() }
        }) {
            label
        }
        .buttonStyle(.plain)
        // Keep disabled copy readable and expose the state semantically. Dimming the
        // complete control made the label fail contrast while still presenting an
        // apparently enabled Button to assistive technologies.
        .disabled(!isEnabled)
    }

    @ViewBuilder
    private var label: some View {
        if traits.hitTestsCapsule {
            chrome.contentShape(VocelloShape.pill())
        } else {
            chrome
        }
    }

    private var chrome: some View {
        HStack(alignment: .center, spacing: VocelloTheme.Spacing.sm) {
            if let symbol {
                Image(systemName: symbol)
                    .font(.system(size: traits.symbolPointSize(for: size), weight: .semibold))
                    .symbolRenderingMode(.hierarchical)
                    // White glyph, matching the label so icon + text read as one unit.
                    .foregroundStyle(foregroundInk)
            }
            Text(title)
                .font(size.titleFont)
                .tracking(size.titleTracking)
                .foregroundStyle(foregroundInk)
                .lineLimit(traits.titleLineLimit)
        }
        .padding(.horizontal, traits.horizontalPadding(for: size))
        .frame(maxWidth: size.spansWidth ? .infinity : nil)
        .frame(height: traits.height(for: size))
        .overlay(alignment: .trailing) {
            if size == .dock, let shortcutHint {
                Text(verbatim: shortcutHint)
                    .font(.caption2.monospaced())
                    .foregroundStyle(VocelloTheme.Text.secondary.opacity(isEnabled ? 0.8 : 0.5))
                    .padding(.trailing, 18)
                    .accessibilityHidden(true)
            }
        }
        .background {
            VocelloShape.pill()
                .fill(backgroundFill)
        }
        .overlay {
            VocelloShape.pill()
                .stroke(strokeColor, lineWidth: size.strokeLineWidth)
        }
        .overlay {
            if size == .dock {
                VocelloShape.pill()
                    .inset(by: 0.65)
                    .stroke(Color.white.opacity(0.06), lineWidth: 0.55)
            }
        }
        .overlay(alignment: .top) {
            if size == .dock {
                // Lit top edge — sheen masked to the upper half.
                VocelloShape.pill()
                    .stroke(Color.white.opacity(0.22), lineWidth: 0.6)
                    .mask(
                        LinearGradient(
                            colors: [.white, .clear],
                            startPoint: .top,
                            endPoint: .center
                        )
                    )
            }
        }
        // Mode-colored hero glow (stronger than the pills' 0.28 @ r8) +
        // a faint ambient shadow for grounding. Glow drops under RT.
        .shadow(
            color: glowColor,
            radius: VocelloTheme.Elevation.ctaGlowRadius,
            x: 0,
            y: VocelloTheme.Elevation.ctaGlowY
        )
        .shadow(
            color: size == .dock ? VocelloTheme.Elevation.ctaDropColor : .clear,
            radius: VocelloTheme.Elevation.ctaDropRadius,
            x: 0,
            y: VocelloTheme.Elevation.ctaDropY
        )
    }

    private var strokeColor: Color {
        size == .dock ? Color.white.opacity(0.16) : tint.opacity(isEnabled ? 0.45 : 0.18)
    }

    /// The dock button's glow is what lifts it off the canvas; it goes with
    /// Reduce Transparency, like every other tinted bloom in the app.
    private var glowColor: Color {
        guard size == .dock, !reduceTransparency, isEnabled || traits.glowsWhenDisabled else { return .clear }
        return VocelloTheme.Elevation.ctaGlowColor(tint)
    }
}
