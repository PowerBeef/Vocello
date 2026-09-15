import SwiftUI

/// The brand lockup of the iOS Studio header (`IOSProductTitleLockup`): the
/// header mark beside the wordmark in SF Rounded semibold. One accessibility
/// element carrying the product name.
struct MacProductTitleLockup: View {
    @ScaledMetric(relativeTo: .title3) private var markWidth = 28
    @ScaledMetric(relativeTo: .title3) private var markHeight = 24
    @ScaledMetric(relativeTo: .title3) private var lockupSpacing = 5

    let title: String

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
                .foregroundStyle(MacTheme.Text.primary)
                .lineLimit(1)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(title)
        .fixedSize(horizontal: true, vertical: false)
    }
}
