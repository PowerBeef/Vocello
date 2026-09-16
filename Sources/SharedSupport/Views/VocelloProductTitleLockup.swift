import SwiftUI

/// The brand lockup: the header mark beside the wordmark in SF Rounded
/// semibold, one accessibility element carrying the product name. The iOS
/// `IOSProductTitleLockup` body, moved unchanged (UIF-02); the macOS
/// `MacProductTitleLockup` twin is gone. Two parameters carry the
/// differences the twins had: the phone's header pads the lockup by half a
/// point where the desktop passes 0, and the phone sets `.tracking(0)` on the
/// wordmark where the desktop set no tracking at all. `.tracking(0)` is not
/// the same as omitting it — it overrides the SF face's own tracking table
/// instead of adding to it — so each platform keeps what it had.
struct VocelloProductTitleLockup: View {
    @ScaledMetric(relativeTo: .title3) private var markWidth = 28
    @ScaledMetric(relativeTo: .title3) private var markHeight = 24
    @ScaledMetric(relativeTo: .title3) private var lockupSpacing = 5

    let title: String
    var verticalPadding: CGFloat = 0
    /// `nil` applies no tracking modifier at all (the desktop); the phone
    /// passes 0.
    var tracking: CGFloat? = nil

    var body: some View {
        HStack(alignment: .center, spacing: lockupSpacing) {
            Image(VocelloTheme.Branding.headerMarkAssetName)
                .renderingMode(.original)
                .resizable()
                .interpolation(.high)
                .antialiased(true)
                .scaledToFit()
                .frame(width: markWidth, height: markHeight)
                .accessibilityHidden(true)

            Text(title)
                .font(.system(.title3, design: .rounded, weight: .semibold))
                .foregroundStyle(VocelloTheme.Text.primary)
                .lineLimit(1)
                // Applying `.tracking` at all changes the face's metrics, so
                // the modifier is skipped entirely when no value is given.
                .modifier(VocelloOptionalTracking(tracking: tracking))
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(title)
        .fixedSize(horizontal: true, vertical: false)
        .padding(.vertical, verticalPadding)
    }
}

/// Applies `.tracking` only when the caller supplies a value, so a platform
/// that never set tracking keeps the font's own metrics.
private struct VocelloOptionalTracking: ViewModifier {
    let tracking: CGFloat?

    func body(content: Content) -> some View {
        if let tracking {
            content.tracking(tracking)
        } else {
            content
        }
    }
}
