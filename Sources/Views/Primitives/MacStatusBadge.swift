import SwiftUI

/// The iOS status badge (`IOSStatusBadge`): a flat capsule with a stroke, so
/// badges contrast with the glassy cards behind them. Single-line by design;
/// long translations truncate rather than wrap.
struct MacStatusBadge: View {
    enum Tone {
        case accent(Color)
        case success
        case warning
        case muted

        var fill: Color {
            switch self {
            case .accent(let color): color.opacity(0.16)
            case .success: MacTheme.Status.healthy.opacity(0.16)
            case .warning: MacTheme.Status.guarded.opacity(0.16)
            case .muted: Color.secondary.opacity(0.12)
            }
        }

        var foreground: Color {
            switch self {
            case .accent(let color): color
            case .success: MacTheme.Status.healthy
            case .warning: MacTheme.Status.guarded
            case .muted: .secondary
            }
        }
    }

    let text: String
    let tone: Tone

    var body: some View {
        let shape = Capsule(style: .continuous)
        Text(text)
            .font(.caption.weight(.semibold))
            .foregroundStyle(tone.foreground)
            .lineLimit(1)
            .padding(.horizontal, 9)
            .padding(.vertical, 4)
            .background { shape.fill(tone.fill) }
            .overlay { shape.stroke(tone.foreground.opacity(0.30), lineWidth: 0.75) }
    }
}
