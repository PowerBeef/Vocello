import SwiftUI

/// Circular gradient avatar for saved voices (the iOS `IOSVoiceAvatar`): the
/// hue derives from the voice id so the same voice renders the same gradient
/// everywhere.
struct MacVoiceAvatar: View {
    let seed: String
    let initials: String
    let diameter: CGFloat

    init(seed: String, initials: String, diameter: CGFloat = 44) {
        self.seed = seed
        let parts = initials.split(separator: " ")
        if parts.count >= 2 {
            self.initials = parts.prefix(2).map { String($0.prefix(1)) }.joined().uppercased()
        } else {
            self.initials = String(initials.prefix(1)).uppercased()
        }
        self.diameter = diameter
    }

    var body: some View {
        let hue = MacStableVisualHash.normalized(seed)
        let topColor = Color(hue: hue, saturation: 0.45, brightness: 0.78)
        let bottomColor = Color(hue: hue, saturation: 0.55, brightness: 0.52)

        return ZStack {
            Circle()
                .fill(
                    LinearGradient(
                        colors: [topColor, bottomColor],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )
            Circle()
                .stroke(Color.white.opacity(0.10), lineWidth: 0.75)
            Text(initials)
                .font(.system(size: diameter * 0.36, weight: .semibold, design: .rounded))
                .foregroundStyle(MacTheme.Text.primary)
        }
        .frame(width: diameter, height: diameter)
        .accessibilityHidden(true)
    }
}

/// The iOS primary call to action (`IOSPrimaryCTAButton`): a tinted capsule
/// with an optional leading symbol, solid under Reduce Transparency.
struct MacPrimaryCTAButton: View {
    /// `.dock` is the Studio's Generate button: the phone's full-width 56 pt
    /// capsule with its sheen and glow, which is what anchors the canvas.
    /// `.compact` is the sheet button that hugs its label.
    enum Size {
        case dock
        case compact

        var height: CGFloat { self == .dock ? 56 : 34 }
        var horizontalPadding: CGFloat { self == .dock ? 20 : 18 }
        var spansWidth: Bool { self == .dock }
    }

    let title: String
    let symbol: String?
    let tint: Color
    let isEnabled: Bool
    let size: Size
    let action: () -> Void

    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency

    init(
        title: String,
        symbol: String? = nil,
        tint: Color,
        isEnabled: Bool = true,
        size: Size = .compact,
        action: @escaping () -> Void
    ) {
        self.title = title
        self.symbol = symbol
        self.tint = tint
        self.isEnabled = isEnabled
        self.size = size
        self.action = action
    }

    private var backgroundFill: AnyShapeStyle {
        if reduceTransparency {
            return AnyShapeStyle(tint.mix(with: .black, by: isEnabled ? 0.42 : 0.70, in: .perceptual))
        }
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
        Button {
            if isEnabled { action() }
        } label: {
            HStack(alignment: .center, spacing: 8) {
                if let symbol {
                    Image(systemName: symbol)
                        .font(.system(size: size == .dock ? 18 : 14, weight: .semibold))
                        .symbolRenderingMode(.hierarchical)
                }
                Text(title)
                    .font(size == .dock ? .headline : .system(size: 13, weight: .semibold))
                    .tracking(size == .dock ? -0.17 : 0)
                    .lineLimit(1)
            }
            .foregroundStyle(isEnabled ? MacTheme.Text.primary : MacTheme.Text.secondary)
            .padding(.horizontal, size.horizontalPadding)
            .frame(maxWidth: size.spansWidth ? .infinity : nil)
            .frame(height: size.height)
            .background { Capsule(style: .continuous).fill(backgroundFill) }
            .overlay { Capsule(style: .continuous).stroke(strokeColor, lineWidth: size == .dock ? 0.8 : 0.75) }
            .overlay { if size == .dock { innerStroke } }
            .overlay { if size == .dock { topSheen } }
            .shadow(color: glowColor, radius: 16, y: 4)
            .shadow(color: size == .dock ? Color.black.opacity(0.22) : .clear, radius: 10, y: 6)
            .contentShape(Capsule(style: .continuous))
        }
        .buttonStyle(.plain)
        .disabled(!isEnabled)
    }

    private var strokeColor: Color {
        size == .dock ? Color.white.opacity(0.16) : tint.opacity(isEnabled ? 0.45 : 0.18)
    }

    /// The dock button's glow is what lifts it off the canvas; it goes with
    /// Reduce Transparency, like every other tinted bloom in the app.
    private var glowColor: Color {
        guard size == .dock, isEnabled, !reduceTransparency else { return .clear }
        return tint.opacity(0.35)
    }

    private var innerStroke: some View {
        Capsule(style: .continuous)
            .inset(by: 0.65)
            .stroke(Color.white.opacity(0.06), lineWidth: 0.55)
    }

    private var topSheen: some View {
        Capsule(style: .continuous)
            .stroke(Color.white.opacity(0.22), lineWidth: 0.6)
            .mask {
                LinearGradient(
                    colors: [.white, .clear],
                    startPoint: .top,
                    endPoint: .center
                )
            }
    }
}

/// Scrolling microphone-level meter driven by the real input (the iOS
/// `IOSLiveLevelMeter`): newest sample on the right, so it visibly rises when
/// the user speaks. Data-driven, no decorative animation, so it stays truthful
/// under Reduce Motion; one `Canvas` draw per sample tick.
struct MacLiveLevelMeter: View {
    let levels: [Double]
    let tint: Color
    var isActive: Bool = true

    private let barCount = 48
    private let spacing: CGFloat = 3

    var body: some View {
        Canvas { context, size in
            let barWidth = max(2.5, (size.width - spacing * CGFloat(barCount - 1)) / CGFloat(barCount))
            for index in 0..<barCount {
                let level = sample(at: index)
                let height = max(3, size.height * CGFloat(0.04 + 0.96 * level))
                let x = CGFloat(index) * (barWidth + spacing)
                let rect = CGRect(x: x, y: (size.height - height) / 2, width: barWidth, height: height)
                let alpha = opacity(at: index)
                context.fill(
                    Path(roundedRect: rect, cornerRadius: barWidth / 2),
                    with: .linearGradient(
                        Gradient(colors: [tint.opacity(alpha), tint.opacity(0.55 * alpha)]),
                        startPoint: CGPoint(x: rect.midX, y: rect.minY),
                        endPoint: CGPoint(x: rect.midX, y: rect.maxY)
                    )
                )
            }
        }
    }

    private func sample(at index: Int) -> Double {
        let offsetFromNewest = (barCount - 1) - index
        let sourceIndex = levels.count - 1 - offsetFromNewest
        guard sourceIndex >= 0, sourceIndex < levels.count else { return 0 }
        return min(1, max(0, levels[sourceIndex]))
    }

    private func opacity(at index: Int) -> Double {
        guard isActive else { return 0.3 }
        let t = Double(index) / Double(max(1, barCount - 1))
        return 0.4 + 0.6 * t
    }
}

extension MacStableVisualHash {
    static func normalized(_ value: String) -> Double {
        Double(UInt64(bitPattern: Int64(int(value))) % 10_000) / 10_000.0
    }
}
