import SwiftUI

/// Empty, error and loading states as a quiet surface card: a 20 pt tinted
/// symbol, a headline and a footnote. The iOS `IOSEmptyStateCard` body, moved
/// unchanged (UIF-02); the macOS `MacEmptyStateCard` twin is gone. The two
/// desktop differences are parameters with the phone's values as defaults:
/// the Mac caps the card at `MacShellMetrics.emptyStateCardMaxWidth` and
/// hides the symbol from accessibility; the phone does neither.
struct VocelloEmptyStateCard: View {
    let title: String
    let message: String
    let symbolName: String
    let tint: Color
    let maxWidth: CGFloat?
    let symbolIsDecorative: Bool

    init(
        title: String,
        message: String,
        symbolName: String,
        tint: Color,
        maxWidth: CGFloat? = nil,
        symbolIsDecorative: Bool = false
    ) {
        self.title = title
        self.message = message
        self.symbolName = symbolName
        self.tint = tint
        self.maxWidth = maxWidth
        self.symbolIsDecorative = symbolIsDecorative
    }

    var body: some View {
        if let maxWidth {
            card.frame(maxWidth: maxWidth)
        } else {
            card
        }
    }

    private var card: some View {
        VocelloSurfaceCard(tint: tint) {
            VStack(alignment: .leading, spacing: 10) {
                symbol
                Text(title)
                    .font(.headline.weight(.semibold))
                    .foregroundStyle(VocelloTheme.Text.primary)
                Text(message)
                    .font(.footnote)
                    .foregroundStyle(VocelloTheme.Text.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    @ViewBuilder
    private var symbol: some View {
        let image = Image(systemName: symbolName)
            .font(.system(size: 20, weight: .semibold))
            .foregroundStyle(tint)
        if symbolIsDecorative {
            image.accessibilityHidden(true)
        } else {
            image
        }
    }
}
