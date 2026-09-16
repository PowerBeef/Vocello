import SwiftUI

/// Fixed-size list-row waveform thumbnail. Uses `Canvas` instead of
/// `GeometryReader` so list rows avoid per-layout measurement work. The iOS
/// `IOSStaticWaveformThumbnail` body, moved unchanged (UIF-02); the macOS
/// `MacStaticWaveformThumbnail` twin is gone. Same bar geometry (2 pt bars,
/// 1.5 pt gaps, radius 1) and the same seeded `.mini` amplitude curve as
/// `IOSWaveformBars`.
struct VocelloStaticWaveformThumbnail: View {
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
                let y = (size.height - height) / 2
                let rect = CGRect(x: x, y: y, width: barWidth, height: height)
                let path = Path(roundedRect: rect, cornerRadius: cornerRadius, style: .continuous)
                context.fill(
                    path,
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
