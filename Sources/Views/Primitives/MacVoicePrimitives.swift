import SwiftUI

/// The shared primary call to action (`VocelloPrimaryCTAButton`, UIF-02) on
/// the desktop: `Traits.desktop`, the `.compact` sheet size and the trailing
/// key-equivalent hint, with Reduce Transparency from the macOS environment.
struct MacPrimaryCTAButton: View {
    typealias Size = VocelloPrimaryCTAButton.Size

    let title: String
    let symbol: String?
    let tint: Color
    let isEnabled: Bool
    let size: Size
    let shortcutHint: String?
    let action: () -> Void

    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency

    init(
        title: String,
        symbol: String? = nil,
        tint: Color,
        isEnabled: Bool = true,
        size: Size = .compact,
        shortcutHint: String? = nil,
        action: @escaping () -> Void
    ) {
        self.title = title
        self.symbol = symbol
        self.tint = tint
        self.isEnabled = isEnabled
        self.size = size
        self.shortcutHint = shortcutHint
        self.action = action
    }

    var body: some View {
        VocelloPrimaryCTAButton(
            title: title,
            symbol: symbol,
            tint: tint,
            isEnabled: isEnabled,
            size: size,
            shortcutHint: shortcutHint,
            traits: .desktop,
            reduceTransparency: reduceTransparency,
            action: action
        )
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
