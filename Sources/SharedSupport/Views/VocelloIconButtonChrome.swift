import SwiftUI

/// Circular icon chrome for player and row controls: a semibold SF Symbol on
/// a faint white disc with a hairline. The iOS `IOSPlayerIconButtonChrome`
/// body, moved unchanged (UIF-02) with the phone's defaults (40 pt disc,
/// 16 pt glyph); the desktop `MacIconButton` wraps this chrome in a `Button`
/// at its own 28 / 12 pt and adds the help tag, label and identifier.
struct VocelloIconButtonChrome: View {
    let symbol: String
    var isActive: Bool = false
    var size: CGFloat = 40
    var symbolSize: CGFloat = 16

    var body: some View {
        Image(systemName: symbol)
            .font(.system(size: symbolSize, weight: .semibold))
            .foregroundStyle(VocelloTheme.Text.primary)
            .frame(width: size, height: size)
            .background {
                Circle()
                    .fill(Color.white.opacity(isActive ? 0.16 : 0.06))
            }
            .overlay {
                Circle()
                    .stroke(Color.white.opacity(0.10), lineWidth: 0.5)
            }
    }
}
