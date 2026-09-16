import SwiftUI

/// Uppercase tracked section heading (11 pt semibold, 0.88 tracking, 20 pt
/// gutters, 6 pt below) with an optional caption subtitle. The iOS
/// `IOSSectionHeading` body, moved unchanged (UIF-02); the macOS
/// `MacSectionHeading` twin is gone.
///
/// The title size is passed in because the phone scales it with Dynamic Type
/// (`@ScaledMetric` in the `IOSSectionHeading` forward) and the Mac draws a
/// fixed 11. The remaining desktop differences are parameters with the
/// phone's values as defaults: the Mac pads 18 above (the phone 20), caps the
/// title at one line and stretches the heading across its list section.
struct VocelloSectionHeading: View {
    let title: String
    let subtitle: String?
    let titleFontSize: CGFloat
    let topPadding: CGFloat
    let titleLineLimit: Int?
    let expandsWidth: Bool

    init(
        _ title: String,
        subtitle: String? = nil,
        titleFontSize: CGFloat,
        topPadding: CGFloat,
        titleLineLimit: Int? = nil,
        expandsWidth: Bool = false
    ) {
        self.title = title
        self.subtitle = subtitle
        self.titleFontSize = titleFontSize
        self.topPadding = topPadding
        self.titleLineLimit = titleLineLimit
        self.expandsWidth = expandsWidth
    }

    var body: some View {
        if expandsWidth {
            heading.frame(maxWidth: .infinity, alignment: .leading)
        } else {
            heading
        }
    }

    private var heading: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title.uppercased())
                .font(.system(size: titleFontSize, weight: .semibold))
                .tracking(0.88)
                .foregroundStyle(VocelloTheme.Text.secondary)
                .lineLimit(titleLineLimit)
            if let subtitle, !subtitle.isEmpty {
                Text(subtitle)
                    .font(.caption)
                    .foregroundStyle(VocelloTheme.Text.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.horizontal, 20)
        .padding(.top, topPadding)
        .padding(.bottom, 6)
    }
}
