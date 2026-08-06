import SwiftUI

/// Draws an audio waveform from sample data, with a progress overlay.
struct WaveformView: View {
    let samples: [Float]
    var progress: Double = 0

    var body: some View {
        Canvas { context, size in
            let barWidth: CGFloat = 3
            let spacing: CGFloat = 2
            let totalBarWidth = barWidth + spacing
            let barCount = min(samples.count, max(0, Int(size.width / totalBarWidth)))
            guard barCount > 0, size.height > 0 else { return }

            let clampedProgress = max(0, min(1, progress))
            let totalWidth = CGFloat(barCount) * barWidth + CGFloat(max(barCount - 1, 0)) * spacing
            let startX = max(0, (size.width - totalWidth) / 2)

            for index in 0..<barCount {
                let sampleIndex = samples.count > barCount
                    ? index * samples.count / barCount
                    : index
                let sample = CGFloat(samples[safe: sampleIndex] ?? 0)
                let height = max(2, min(size.height, sample * size.height))
                let x = startX + CGFloat(index) * totalBarWidth
                let y = (size.height - height) / 2
                let rect = CGRect(x: x, y: y, width: barWidth, height: height)
                let progressFraction = Double(index) / Double(max(barCount - 1, 1))
                // 0.20 keeps the unplayed half legible on crushed panels
                // (TV gamma at scaled modes erased the old 0.12).
                let color = progressFraction <= clampedProgress
                    ? AppTheme.waveformColor(at: progressFraction)
                    : Color.primary.opacity(0.20)
                context.fill(
                    Path(roundedRect: rect, cornerRadius: 1.5),
                    with: .color(color)
                )
            }
        }
    }
}

// Safe array subscript
private extension Array {
    subscript(safe index: Int) -> Element? {
        indices.contains(index) ? self[index] : nil
    }
}
