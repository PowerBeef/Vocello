import SwiftUI

/// Premium "lit tinted" pill used by the Studio setup chips: a soft tint
/// gradient fill, the app's standard glass strokes, a faint tint glow, an SF
/// Symbol, the caller's label and an upward chevron. Honors Reduce
/// Transparency (flat fill, no glow).
///
/// One chrome for both apps (UIF-02). The label is the caller's because it
/// is the one designed difference: the phone shows a two-letter code or a
/// plus glyph (`IOSSetupChipPill`), the desktop writes the value out in full
/// (`MacStudioSetupChipPill`). The desktop also insets its label by 12 pt
/// and floors the pill at `MacStudioChipMetrics.minWidth`; the phone passes
/// neither. Reduce Transparency is passed in because each platform reads it
/// from its own environment key.
struct VocelloSetupChipPill<Label: View>: View {
    let symbol: String
    let tint: Color
    let height: CGFloat
    let horizontalPadding: CGFloat
    let minWidth: CGFloat?
    /// Point size of the leading symbol. It travels with the pill's height
    /// rather than being fixed, because a glyph that stays put while its
    /// container shrinks stops reading as part of the control and starts
    /// reading as something dropped into it. 18 is the phone's, and the phone
    /// keeps it by taking the default.
    let glyphPointSize: CGFloat
    let showsChevron: Bool
    let reduceTransparency: Bool
    let label: Label

    init(
        symbol: String,
        tint: Color,
        height: CGFloat,
        horizontalPadding: CGFloat = 0,
        minWidth: CGFloat? = nil,
        glyphPointSize: CGFloat = 18,
        showsChevron: Bool = true,
        reduceTransparency: Bool,
        @ViewBuilder label: () -> Label
    ) {
        self.symbol = symbol
        self.tint = tint
        self.height = height
        self.horizontalPadding = horizontalPadding
        self.minWidth = minWidth
        self.glyphPointSize = glyphPointSize
        self.showsChevron = showsChevron
        self.reduceTransparency = reduceTransparency
        self.label = label()
    }

    var body: some View {
        HStack(spacing: VocelloTheme.Spacing.tight) {
            Image(systemName: symbol)
                .font(.system(size: glyphPointSize, weight: .semibold))
                .symbolRenderingMode(.hierarchical)
                .foregroundStyle(VocelloTheme.Text.primary)
            label
            // Trailing chevron — signals every pill is a tappable selector (opens a picker),
            // so the value pills don't read as static badges. Subtle + subordinate to the value.
            // Points UP: on the phone these pills sit in the bottom screen area and their
            // pickers are bottom sheets that slide UP; the desktop's menu keeps the same glyph.
            if showsChevron {
                Image(systemName: "chevron.up")
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(tint.opacity(0.5))
                    .accessibilityHidden(true)
            }
        }
        .padding(.horizontal, horizontalPadding)
        .frame(minWidth: minWidth, maxWidth: .infinity)
        .frame(height: height)
        .background {
            VocelloShape.pill().fill(fillStyle)
        }
        .overlay {
            VocelloShape.pill()
                .stroke(Color.white.opacity(0.12), lineWidth: 0.8)
        }
        .overlay {
            VocelloShape.pill()
                .inset(by: 0.65)
                .stroke(Color.white.opacity(0.04), lineWidth: 0.55)
        }
        .shadow(
            color: reduceTransparency ? .clear : VocelloTheme.Elevation.glowColor(tint),
            radius: VocelloTheme.Elevation.glowRadius,
            y: VocelloTheme.Elevation.glowY
        )
    }

    private var fillStyle: AnyShapeStyle {
        if reduceTransparency {
            return AnyShapeStyle(tint.opacity(0.22))
        }
        return AnyShapeStyle(
            LinearGradient(
                colors: [tint.opacity(0.30), tint.opacity(0.14)],
                startPoint: .top,
                endPoint: .bottom
            )
        )
    }
}
