import SwiftUI

/// Deterministic hashing for visual seeds (the iOS `IOSStableVisualHash`):
/// the same string renders the same thumbnail across launches.
enum MacStableVisualHash {
    static func int(_ value: String) -> Int {
        Int(truncatingIfNeeded: fnv1a64(value))
    }

    private static func fnv1a64(_ value: String) -> UInt64 {
        var hash: UInt64 = 0xcbf2_9ce4_8422_2325
        for byte in value.utf8 {
            hash ^= UInt64(byte)
            hash &*= 0x0000_0100_0000_01B3
        }
        return hash
    }
}

/// Fixed-size list-row waveform thumbnail (the iOS
/// `IOSStaticWaveformThumbnail`): a `Canvas`, so rows avoid per-layout
/// measurement work.
struct MacStaticWaveformThumbnail: View {
    let seed: Int
    let barCount: Int
    let tint: Color

    private let barWidth: CGFloat = 2
    private let spacing: CGFloat = 1.5
    private let cornerRadius: CGFloat = 1

    var body: some View {
        Canvas { context, size in
            for index in 0..<barCount {
                let amplitude = miniAmplitude(at: index)
                let height = max(2, size.height * CGFloat(amplitude))
                let x = CGFloat(index) * (barWidth + spacing)
                let rect = CGRect(x: x, y: (size.height - height) / 2, width: barWidth, height: height)
                context.fill(
                    Path(roundedRect: rect, cornerRadius: cornerRadius, style: .continuous),
                    with: .color(tint.opacity(0.4 + amplitude * 0.5))
                )
            }
        }
    }

    private func miniAmplitude(at index: Int) -> Double {
        let i = Double(index)
        let raw = sin((Double(seed) * 13 + i * 7.31) * 1.3) * 0.4 + 0.5
        let base = abs(raw) + Double(index % 5) * 0.08
        return max(0.16, min(0.95, base))
    }
}

/// Small mode-colored dot; always paired with a textual cue.
struct MacModeDot: View {
    let tint: Color
    var diameter: CGFloat = 6

    var body: some View {
        Circle()
            .fill(tint)
            .frame(width: diameter, height: diameter)
    }
}

/// Uppercase tracked section heading (the iOS `IOSSectionHeading`).
struct MacSectionHeading: View {
    let title: String

    init(_ title: String) {
        self.title = title
    }

    var body: some View {
        Text(title.uppercased())
            .font(.system(size: 11, weight: .semibold))
            .tracking(0.88)
            .foregroundStyle(MacTheme.Text.secondary)
            .lineLimit(1)
            .padding(.horizontal, 20)
            .padding(.top, 18)
            .padding(.bottom, 6)
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// Empty, error and loading states as a quiet card (the iOS
/// `IOSEmptyStateCard`).
struct MacEmptyStateCard: View {
    let title: String
    let message: String
    let symbolName: String
    let tint: Color

    var body: some View {
        MacSurfaceCard {
            VStack(alignment: .leading, spacing: 10) {
                Image(systemName: symbolName)
                    .font(.system(size: 20, weight: .semibold))
                    .foregroundStyle(tint)
                    .accessibilityHidden(true)
                Text(title)
                    .font(.headline.weight(.semibold))
                    .foregroundStyle(MacTheme.Text.primary)
                Text(message)
                    .font(.footnote)
                    .foregroundStyle(MacTheme.Text.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: 480)
    }
}

/// Circular icon button chrome (the iOS `IOSPlayerIconButtonChrome`).
struct MacIconButton: View {
    let symbol: String
    let label: String
    let accessibilityIdentifier: String
    var isEnabled = true
    var size: CGFloat = 28
    var symbolSize: CGFloat = 12
    var help: String? = nil
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: symbol)
                .font(.system(size: symbolSize, weight: .semibold))
                .foregroundStyle(MacTheme.Text.primary)
                .frame(width: size, height: size)
                .background { Circle().fill(Color.white.opacity(0.06)) }
                .overlay { Circle().stroke(Color.white.opacity(0.10), lineWidth: 0.5) }
                .contentShape(Circle())
        }
        .buttonStyle(.plain)
        .disabled(!isEnabled)
        .opacity(isEnabled ? 1 : 0.45)
        .help(help ?? label)
        .accessibilityLabel(label)
        .accessibilityIdentifier(accessibilityIdentifier)
    }
}

/// Single-select capsule chips (the iOS `IOSFilterChipRow`). Selection is
/// brightness plus the selected trait, never color alone.
struct MacFilterChipRow<Option: Hashable & Identifiable>: View {
    let options: [Option]
    @Binding var selection: Option
    let label: (Option) -> String
    let leading: ((Option) -> AnyView)?
    let accessibilityIdentifier: (Option) -> String

    var body: some View {
        HStack(spacing: 8) {
            ForEach(options) { option in
                chip(for: option)
            }
        }
    }

    private func chip(for option: Option) -> some View {
        let isSelected = option == selection
        return Button {
            AppLaunchConfiguration.performAnimated(MacTheme.Motion.stateChange) {
                selection = option
            }
        } label: {
            HStack(spacing: 6) {
                if let leading {
                    leading(option)
                }
                Text(label(option))
                    .font(.system(size: 12, weight: .semibold))
                    .lineLimit(1)
            }
            .foregroundStyle(isSelected ? MacTheme.Text.primary : MacTheme.Text.secondary)
            .frame(minHeight: 28)
            .padding(.horizontal, 12)
            .background {
                Capsule(style: .continuous)
                    .fill(isSelected ? Color.white.opacity(0.10) : Color.white.opacity(0.03))
            }
            .overlay {
                Capsule(style: .continuous)
                    .stroke(isSelected ? Color.white.opacity(0.18) : Color.white.opacity(0.10), lineWidth: 0.5)
            }
            .contentShape(Capsule(style: .continuous))
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier(accessibilityIdentifier(option))
        .accessibilityAddTraits(isSelected ? .isSelected : [])
    }
}
