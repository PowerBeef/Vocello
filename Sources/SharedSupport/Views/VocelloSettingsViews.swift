import SwiftUI

/// Common Settings surfaces; platform adapters retain controls and navigation ownership.
struct VocelloSettingsGroup<Content: View>: View {
    var accent: Color?
    @ViewBuilder let content: Content

    var body: some View {
        let shape = VocelloShape.card()
        VStack(alignment: .leading, spacing: 0) { content }
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(accent?.opacity(0.06) ?? Color.white.opacity(0.035), in: shape)
            .overlay {
                shape.strokeBorder(accent?.opacity(0.18) ?? VocelloTheme.Surface.panelStroke,
                                   lineWidth: VocelloTheme.Stroke.hairline)
            }
    }
}

/// A compact destination label with its current value beneath the title.
/// Text can grow vertically without squeezing a trailing value against the chevron.
struct VocelloSettingsNavigationRow: View {
    let symbol: String
    let title: String
    let subtitle: String?
    var value = ""
    var tint: Color = VocelloTheme.Brand.silver
    var showsChevron = true
    var titleFont: Font = .subheadline.weight(.semibold)
    var detailFont: Font = .footnote
    var verticalInset: CGFloat = 12

    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            Image(systemName: symbol)
                .font(.system(size: 17, weight: .medium))
                .foregroundStyle(tint)
                .frame(width: 30, height: 30)
                .background(tint.opacity(0.08), in: RoundedRectangle(cornerRadius: 9))
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(titleFont)
                    .foregroundStyle(VocelloTheme.Text.primary)
                if let subtitle, !subtitle.isEmpty {
                    Text(subtitle)
                        .font(detailFont)
                        .foregroundStyle(VocelloTheme.Text.secondary)
                }
                if !value.isEmpty {
                    Text(value)
                        .font(detailFont)
                        .foregroundStyle(VocelloTheme.Text.secondary)
                }
            }
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
            if showsChevron {
                Image(systemName: "chevron.right")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(VocelloTheme.Text.tertiary)
                    .accessibilityHidden(true)
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, verticalInset)
        .frame(maxWidth: .infinity, minHeight: 52, alignment: .leading)
        .contentShape(Rectangle())
    }
}
