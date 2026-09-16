import SwiftUI

/// Flat capsule badge with a stroke (no glass), so badges contrast with the
/// glassy cards behind them. The iOS `IOSStatusBadge` body and palette,
/// moved unchanged (UIF-02); the macOS `MacStatusBadge` twin is gone.
///
/// The padding is passed in rather than owned here because the two platforms
/// resolve it differently: the phone scales 10 / 5 with Dynamic Type
/// (`@ScaledMetric` in the `IOSStatusBadge` forward) while the Mac passes a
/// fixed 9 / 4 and caps the text at one line. The palette is the phone's:
/// the retired Mac twin mapped `.success` / `.warning` to
/// `Status.healthy` / `Status.guarded`, but its only call site renders
/// `.muted`, which is identical on both.
struct VocelloStatusBadge: View {
    enum Tone {
        case accent(Color)
        case success
        case warning
        case muted

        var fill: Color {
            switch self {
            case .accent(let color):
                return color.opacity(0.16)
            case .success:
                return Color.green.opacity(0.16)
            case .warning:
                return Color.orange.opacity(0.16)
            case .muted:
                return Color.secondary.opacity(0.12)
            }
        }

        var foreground: Color {
            switch self {
            case .accent(let color):
                return color
            case .success:
                return .green
            case .warning:
                return .orange
            case .muted:
                return .secondary
            }
        }
    }

    let text: String
    let tone: Tone
    let horizontalPadding: CGFloat
    let verticalPadding: CGFloat
    let lineLimit: Int?

    init(
        text: String,
        tone: Tone,
        horizontalPadding: CGFloat,
        verticalPadding: CGFloat,
        lineLimit: Int? = nil
    ) {
        self.text = text
        self.tone = tone
        self.horizontalPadding = horizontalPadding
        self.verticalPadding = verticalPadding
        self.lineLimit = lineLimit
    }

    var body: some View {
        let shape = Capsule(style: .continuous)

        Text(text)
            .font(.caption.weight(.semibold))
            .foregroundStyle(tone.foreground)
            .lineLimit(lineLimit)
            .padding(.horizontal, horizontalPadding)
            .padding(.vertical, verticalPadding)
            .background {
                shape.fill(tone.fill)
            }
            .overlay {
                shape.stroke(tone.foreground.opacity(0.30), lineWidth: 0.75)
            }
    }
}
