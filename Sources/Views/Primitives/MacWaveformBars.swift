import SwiftUI

/// The iOS player waveform (`IOSWaveformBars`, `.player` style) drawn from the
/// real sample envelope the macOS player already computes: played bars carry
/// the tint gradient, the unplayed tail stays a quiet white. While a live
/// stream has no envelope yet, a deterministic pattern stands in so the card
/// never shows an empty slot. One `Canvas` draw, no per-frame work.
struct MacWaveformBars: View {
    let samples: [Float]
    let progress: Double
    let tint: Color
    var barCount: Int = 38
    var unplayedColor: Color = Color.white.opacity(0.18)

    private static let spacing: CGFloat = 2.0
    private static let cornerRadius: CGFloat = 1.5
    private static let minimumBarWidth: CGFloat = 2.0
    private static let minimumAmplitude: Double = 0.12
    private static let maximumAmplitude: Double = 0.96

    var body: some View {
        Canvas { context, size in
            guard barCount > 0, size.height > 0 else { return }
            let totalSpacing = Self.spacing * CGFloat(barCount - 1)
            let barWidth = max(Self.minimumBarWidth, (size.width - totalSpacing) / CGFloat(barCount))
            let totalWidth = CGFloat(barCount) * barWidth + totalSpacing
            let startX = max(0, (size.width - totalWidth) / 2)
            let playhead = min(max(progress, 0), 1)
            let playheadIndex = Int((Double(barCount) * playhead).rounded())

            for index in 0..<barCount {
                let amplitude = amplitude(at: index)
                let height = max(2, size.height * CGFloat(amplitude))
                let x = startX + CGFloat(index) * (barWidth + Self.spacing)
                let rect = CGRect(x: x, y: (size.height - height) / 2, width: barWidth, height: height)
                let path = Path(roundedRect: rect, cornerRadius: Self.cornerRadius, style: .continuous)
                if index < playheadIndex {
                    context.fill(
                        path,
                        with: .linearGradient(
                            Gradient(colors: [tint, tint.opacity(0.70)]),
                            startPoint: CGPoint(x: rect.midX, y: rect.minY),
                            endPoint: CGPoint(x: rect.midX, y: rect.maxY)
                        )
                    )
                } else {
                    context.opacity = 0.55
                    context.fill(path, with: .color(unplayedColor))
                    context.opacity = 1
                }
            }
        }
    }

    private func amplitude(at index: Int) -> Double {
        let raw: Double
        if samples.isEmpty {
            raw = abs(sin((11 + Double(index) * 6.7) * 1.6) * 0.45 + 0.5)
        } else {
            let sampleIndex = samples.count > barCount
                ? index * samples.count / barCount
                : min(index, samples.count - 1)
            raw = Double(samples[sampleIndex])
        }
        return max(Self.minimumAmplitude, min(Self.maximumAmplitude, raw))
    }
}
