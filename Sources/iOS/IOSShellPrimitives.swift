import Dispatch
import SwiftUI
import UIKit
import QwenVoiceCore

enum IOSHaptics {
    @MainActor
    static func selection() {
        UISelectionFeedbackGenerator().selectionChanged()
    }

    @MainActor
    static func impact(_ style: UIImpactFeedbackGenerator.FeedbackStyle = .medium) {
        UIImpactFeedbackGenerator(style: style).impactOccurred()
    }

    @MainActor
    static func success() {
        UINotificationFeedbackGenerator().notificationOccurred(.success)
    }

    @MainActor
    static func warning() {
        UINotificationFeedbackGenerator().notificationOccurred(.warning)
    }

    @MainActor
    static func error() {
        UINotificationFeedbackGenerator().notificationOccurred(.error)
    }
}

enum IOSTypeStyle {
    case eyebrow
    case pageTitle
    case sectionHeading
    case cardTitle
    case bodyStrong
    case body
    case subhead
    case footnote
    case caption
    case mono

    var font: Font {
        switch self {
        case .eyebrow: return .caption.weight(.semibold)
        case .pageTitle: return .system(.largeTitle, design: .default, weight: .bold)
        case .sectionHeading: return .title3.weight(.semibold)
        case .cardTitle: return .subheadline.weight(.semibold)
        case .bodyStrong: return .body.weight(.semibold)
        case .body: return .body
        case .subhead: return .subheadline
        case .footnote: return .footnote
        case .caption: return .caption
        case .mono: return .caption.monospacedDigit().weight(.medium)
        }
    }

    var defaultTracking: CGFloat {
        switch self {
        case .eyebrow: return 1.0
        default: return 0
        }
    }
}

extension View {
    func iosType(_ style: IOSTypeStyle, tracking: CGFloat? = nil) -> some View {
        self
            .font(style.font)
            .tracking(tracking ?? style.defaultTracking)
    }
}

struct IOSSubtleGlassSurfaceModifier<S: InsettableShape>: ViewModifier {
    let shape: S
    let tint: Color?
    let fill: Color
    let strokeOpacity: Double
    let interactive: Bool

    @ViewBuilder
    func body(content: Content) -> some View {
        let base = content
            .background {
                shape
                    .fill(fill)
            }
            .overlay {
                shape
                    .stroke(Color.white.opacity(strokeOpacity), lineWidth: 0.8)
                    .allowsHitTesting(false)
            }
            .overlay {
                shape
                    .inset(by: 0.65)
                    .stroke(Theme.Surface.glassInnerStroke, lineWidth: 0.55)
                    .allowsHitTesting(false)
            }

        // The gate decision lives in the shared IOSGatedGlassModifier
        // (IUI-5 D10a); `fill` above already paints the solid base, so the
        // gated branch needs no extra backing here.
        base.iosGatedGlass(
            tint: Theme.glassTint(tint, intensity: 0.9),
            in: shape,
            interactive: interactive
        )
    }
}

extension View {
    func iosSubtleGlassSurface<S: InsettableShape>(
        in shape: S,
        tint: Color? = nil,
        fill: Color = Theme.Surface.glassSurface,
        strokeOpacity: Double = 0.12,
        interactive: Bool = false
    ) -> some View {
        modifier(
            IOSSubtleGlassSurfaceModifier(
                shape: shape,
                tint: tint,
                fill: fill,
                strokeOpacity: strokeOpacity,
                interactive: interactive
            )
        )
    }
}

struct IOSScreenBackdrop: View {
    var body: some View {
        Theme.Surface.canvasBottom
        .ignoresSafeArea()
    }
}

struct IOSStatusBadge: View {
    @ScaledMetric(relativeTo: .caption) private var horizontalPadding = 10
    @ScaledMetric(relativeTo: .caption) private var verticalPadding = 5

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

    var body: some View {
        let shape = Capsule(style: .continuous)

        // Flat fill + stroke. Chips on iOS now mirror the macOS chip audit
        // (May 2026): no glass on badges, so they contrast with the glassy
        // cards behind them and don't collapse the hierarchy.
        Text(text)
            .font(.caption.weight(.semibold))
            .foregroundStyle(tone.foreground)
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

struct IOSSurfaceCard<Content: View>: View {
    let tint: Color?
    let content: Content

    init(tint: Color? = nil, @ViewBuilder content: () -> Content) {
        self.tint = tint
        self.content = content()
    }

    var body: some View {
        let shape = RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous)

        VStack(alignment: .leading, spacing: contentSpacing) {
            content
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background { shape.fill(Color.white.opacity(0.04)) }
        .overlay { shape.stroke(Color.white.opacity(0.08), lineWidth: 0.5) }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var contentSpacing: CGFloat { 8 }
}

struct IOSSectionHeading: View {
    let title: String
    let subtitle: String?

    init(_ title: String, subtitle: String? = nil) {
        self.title = title
        self.subtitle = subtitle
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title.uppercased())
                .iosScaledFont(size: 11, weight: .semibold, relativeTo: .caption2)
                .tracking(0.88)
                .foregroundStyle(Theme.Text.secondary)
            if let subtitle, !subtitle.isEmpty {
                Text(subtitle)
                    .font(.caption)
                    .foregroundStyle(Theme.Text.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.horizontal, 20)
        .padding(.top, 20)
        .padding(.bottom, 6)
    }
}

struct IOSCompactCardHeader: View {
    let title: String
    let message: String?
    let badgeText: String?
    let badgeTone: IOSStatusBadge.Tone?

    init(
        title: String,
        message: String? = nil,
        badgeText: String? = nil,
        badgeTone: IOSStatusBadge.Tone? = nil
    ) {
        self.title = title
        self.message = message
        self.badgeText = badgeText
        self.badgeTone = badgeTone
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Text(title)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(Theme.Text.primary)

                Spacer(minLength: 8)

                if let badgeText, let badgeTone {
                    IOSStatusBadge(text: badgeText, tone: badgeTone)
                }
            }

            if let message, !message.isEmpty {
                Text(message)
                    .font(.caption2)
                    .foregroundStyle(Theme.Text.secondary)
                    .lineLimit(1)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}

struct IOSPageHeader: View {
    @ScaledMetric(relativeTo: .title2) private var verticalSpacing = 6
    @ScaledMetric(relativeTo: .body) private var titleSpacing = 3
    @ScaledMetric(relativeTo: .body) private var accessorySpacing = 10

    let eyebrow: String?
    let title: String
    let subtitle: String
    let tint: Color
    let badgeText: String?
    let badgeTone: IOSStatusBadge.Tone?

    init(
        eyebrow: String? = nil,
        title: String,
        subtitle: String,
        tint: Color,
        badgeText: String? = nil,
        badgeTone: IOSStatusBadge.Tone? = nil
    ) {
        self.eyebrow = eyebrow
        self.title = title
        self.subtitle = subtitle
        self.tint = tint
        self.badgeText = badgeText
        self.badgeTone = badgeTone
    }

    var body: some View {
        VStack(alignment: .leading, spacing: verticalSpacing) {
            if let eyebrow, !eyebrow.isEmpty {
                Text(eyebrow.uppercased())
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(tint)
                    .tracking(1.0)
            }

            HStack(alignment: .top, spacing: accessorySpacing) {
                VStack(alignment: .leading, spacing: titleSpacing) {
                    Text(title)
                        .font(.system(.largeTitle, design: .default, weight: .bold))
                        .foregroundStyle(Theme.Text.primary)
                        .multilineTextAlignment(.leading)
                    Text(subtitle)
                        .font(.body)
                        .foregroundStyle(Theme.Text.secondary)
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                }

                Spacer(minLength: 8)

                if let badgeText, let badgeTone {
                    IOSStatusBadge(text: badgeText, tone: badgeTone)
                }
            }
        }
    }
}

struct IOSCompactPageHeader: View {
    @ScaledMetric(relativeTo: .title2) private var verticalSpacing = 3
    @ScaledMetric(relativeTo: .body) private var titleSpacing = 2
    @ScaledMetric(relativeTo: .body) private var accessorySpacing = 10

    let eyebrow: String?
    let title: String
    let subtitle: String
    let tint: Color
    let badgeText: String?
    let badgeTone: IOSStatusBadge.Tone?

    init(
        eyebrow: String? = nil,
        title: String,
        subtitle: String,
        tint: Color,
        badgeText: String? = nil,
        badgeTone: IOSStatusBadge.Tone? = nil
    ) {
        self.eyebrow = eyebrow
        self.title = title
        self.subtitle = subtitle
        self.tint = tint
        self.badgeText = badgeText
        self.badgeTone = badgeTone
    }

    var body: some View {
        VStack(alignment: .leading, spacing: verticalSpacing) {
            if let eyebrow, !eyebrow.isEmpty {
                Text(eyebrow.uppercased())
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(tint)
                    .tracking(0.8)
            }

            HStack(alignment: .top, spacing: accessorySpacing) {
                VStack(alignment: .leading, spacing: titleSpacing) {
                    Text(title)
                        .font(.system(.title2, design: .default, weight: .bold))
                        .foregroundStyle(Theme.Text.primary)
                        .lineLimit(1)
                        .minimumScaleFactor(0.9)

                    Text(subtitle)
                        .font(.subheadline)
                        .foregroundStyle(Theme.Text.secondary)
                        .lineLimit(1)
                        .fixedSize(horizontal: false, vertical: true)
                }

                Spacer(minLength: 6)

                if let badgeText, let badgeTone {
                    IOSStatusBadge(text: badgeText, tone: badgeTone)
                }
            }
        }
    }
}

struct IOSStudioHeaderChip: View {
    let title: String
    let tint: Color

    var body: some View {
        let shape = Capsule(style: .continuous)

        Text(title)
            .font(.caption2.weight(.medium))
            .foregroundStyle(Theme.Text.primary)
            .padding(.horizontal, 10)
            .padding(.vertical, 5)
            .iosSubtleGlassSurface(
                in: shape,
                tint: tint,
                fill: Theme.Surface.glassSurfaceMuted.opacity(0.52),
                strokeOpacity: 0.10
            )
    }
}

struct IOSStudioUtilityHeader: View {
    enum TitleRole {
        case productBrand
        case section
    }

    let title: String
    let subtitle: String?
    let runtimeLabel: String?
    let modelLabel: String?
    let subtitleProminence: Double
    let titleRole: TitleRole
    let trailingAccessory: AnyView?

    init(
        title: String,
        subtitle: String?,
        runtimeLabel: String?,
        modelLabel: String?,
        subtitleProminence: Double = 1.0,
        titleRole: TitleRole = .section,
        trailingAccessory: AnyView? = nil
    ) {
        self.title = title
        self.subtitle = subtitle
        self.runtimeLabel = runtimeLabel
        self.modelLabel = modelLabel
        self.subtitleProminence = subtitleProminence
        self.titleRole = titleRole
        self.trailingAccessory = trailingAccessory
    }

    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            titleView

            Spacer(minLength: 12)

            if let subtitle, !subtitle.isEmpty {
                Text(subtitle)
                    .font(.footnote)
                    .foregroundStyle(Theme.Text.secondary.opacity(subtitleProminence))
                    .lineLimit(1)
                    .truncationMode(.tail)
                    .layoutPriority(0.5)
            }

            if let trailingAccessory {
                trailingAccessory
                    .layoutPriority(0.75)
            }

            if let runtimeLabel, !runtimeLabel.isEmpty {
                IOSStudioHeaderChip(title: runtimeLabel, tint: Theme.Brand.gold)
            }

            if let modelLabel, !modelLabel.isEmpty {
                IOSStudioHeaderChip(title: modelLabel, tint: Theme.Brand.library)
            }
        }
    }

    @ViewBuilder
    private var titleView: some View {
        switch titleRole {
        case .productBrand:
            IOSProductTitleLockup(title: title)
                .layoutPriority(1)
        case .section:
            Text(title)
                .font(titleFont)
                .foregroundStyle(Theme.Text.primary)
                .lineLimit(1)
                .tracking(titleTracking)
        }
    }

    private var titleFont: Font {
        switch titleRole {
        case .productBrand:
            // Mirror macOS sidebar wordmark (Sources/Views/Sidebar/SidebarView.swift):
            // SF Rounded semibold. Was .serif previously — drifted from the
            // macOS lockup. Aligning here so iPhone and Mac read as the same brand.
            return .system(.title3, design: .rounded, weight: .semibold)
        case .section:
            return .system(.title3, design: .default, weight: .bold)
        }
    }

    private var titleTracking: CGFloat {
        switch titleRole {
        case .productBrand:
            return 0
        case .section:
            return 0
        }
    }
}

struct IOSProductTitleLockup: View {
    @ScaledMetric(relativeTo: .title3) private var markWidth = 28
    @ScaledMetric(relativeTo: .title3) private var markHeight = 24
    @ScaledMetric(relativeTo: .title3) private var lockupSpacing = 5

    let title: String

    var body: some View {
        HStack(alignment: .center, spacing: lockupSpacing) {
            Image(Theme.Branding.headerMarkAssetName)
                .renderingMode(.original)
                .resizable()
                .interpolation(.high)
                .antialiased(true)
                .scaledToFit()
                .frame(width: markWidth, height: markHeight)
                .accessibilityHidden(true)

            Text(title)
                .font(.system(.title3, design: .rounded, weight: .semibold))
                .foregroundStyle(Theme.Text.primary)
                .lineLimit(1)
                .tracking(0)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(title)
        .fixedSize(horizontal: true, vertical: false)
        .padding(.vertical, 0.5)
    }
}


struct IOSStatusStrip: View {
    @ScaledMetric(relativeTo: .subheadline) private var verticalPadding = 9
    @ScaledMetric(relativeTo: .subheadline) private var horizontalPadding = 12
    @ScaledMetric(relativeTo: .subheadline) private var symbolSize = 14
    @ScaledMetric(relativeTo: .subheadline) private var cornerRadius = 16

    let title: String
    let message: String?
    let symbolName: String
    let tint: Color

    init(
        title: String,
        message: String? = nil,
        symbolName: String = "info.circle.fill",
        tint: Color = Theme.Brand.gold
    ) {
        self.title = title
        self.message = message
        self.symbolName = symbolName
        self.tint = tint
    }

    var body: some View {
        let shape = RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)

        HStack(alignment: .top, spacing: 8) {
            Image(systemName: symbolName)
                .font(.system(size: symbolSize, weight: .semibold))
                .foregroundStyle(tint)
                .frame(width: 24, height: 24)

            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(Theme.Text.primary)

                if let message, !message.isEmpty {
                    Text(message)
                        .font(.caption)
                        .foregroundStyle(Theme.Text.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }

            Spacer(minLength: 0)
        }
        .padding(.horizontal, horizontalPadding)
        .padding(.vertical, verticalPadding)
        .iosSubtleGlassSurface(
            in: shape,
            tint: tint,
            fill: Theme.Surface.glassSurfaceMuted,
            strokeOpacity: 0.16
        )
    }
}

struct IOSInfoBanner: View {
    @ScaledMetric(relativeTo: .subheadline) private var verticalPadding = 14
    @ScaledMetric(relativeTo: .subheadline) private var cornerRadius = 18

    let title: String
    let message: String
    let symbolName: String
    let tint: Color

    init(
        title: String,
        message: String,
        symbolName: String = "info.circle.fill",
        tint: Color = Theme.Brand.gold
    ) {
        self.title = title
        self.message = message
        self.symbolName = symbolName
        self.tint = tint
    }

    var body: some View {
        let shape = RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)

        HStack(alignment: .top, spacing: 12) {
            Image(systemName: symbolName)
                .font(.headline)
                .foregroundStyle(tint)
                .padding(.top, 2)

            VStack(alignment: .leading, spacing: 6) {
                Text(title)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(Theme.Text.primary)
                Text(message)
                    .font(.subheadline)
                    .foregroundStyle(Theme.Text.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(verticalPadding)
        .iosSubtleGlassSurface(
            in: shape,
            tint: tint,
            fill: Theme.Surface.glassSurface,
            strokeOpacity: 0.16
        )
    }
}

struct IOSScriptLengthStatusRow: View {
    let state: IOSGenerationTextLimitPolicy.State
    let tint: Color

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            Text(state.helperMessage)
                .font(.caption)
                .foregroundStyle(state.isOverLimit ? .orange : Theme.Text.secondary)
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityIdentifier(IOSAccessibilityIdentifier.TextInput.limitMessage)

            Spacer(minLength: 8)

            Text(state.counterText)
                .font(.caption.monospacedDigit().weight(.semibold))
                .foregroundStyle(state.isOverLimit ? .orange : tint)
                .accessibilityIdentifier(IOSAccessibilityIdentifier.TextInput.lengthCount)
        }
        .accessibilityIdentifier(IOSAccessibilityIdentifier.TextInput.lengthStatus)
    }
}

struct IOSFloatingTopBar<Content: View>: View {
    @ScaledMetric(relativeTo: .body) private var horizontalPadding = 16
    @ScaledMetric(relativeTo: .body) private var topPadding = 4
    @ScaledMetric(relativeTo: .body) private var bottomPadding = 4

    let content: Content

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    var body: some View {
        VStack(spacing: 0) {
            content
                .padding(.horizontal, horizontalPadding)
                .padding(.top, topPadding)
                .padding(.bottom, bottomPadding)
        }
        .background(
            LinearGradient(
                colors: [
                    Theme.Surface.canvas.opacity(0.96),
                    Theme.Surface.canvas.opacity(0.90),
                    .clear
                ],
                startPoint: .top,
                endPoint: .bottom
            )
            .ignoresSafeArea(edges: .top)
        )
    }
}

struct IOSStickyActionBar<Content: View>: View {
    @ScaledMetric(relativeTo: .body) private var horizontalPadding = 16
    @ScaledMetric(relativeTo: .body) private var topPadding = 8
    @ScaledMetric(relativeTo: .body) private var bottomPadding = 12
    @ScaledMetric(relativeTo: .body) private var contentSpacing = 10

    let content: Content

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    var body: some View {
        let shape = RoundedRectangle(cornerRadius: 24, style: .continuous)

        VStack(spacing: 0) {
            VStack(spacing: contentSpacing) {
                content
            }
            .padding(.horizontal, horizontalPadding)
            .padding(.top, topPadding)
            .padding(.bottom, bottomPadding)
            .iosSubtleGlassSurface(
                in: shape,
                tint: Theme.Brand.gold,
                fill: Theme.Surface.glassFloating,
                strokeOpacity: 0.14
            )
            .shadow(color: Theme.Brand.goldGlow.opacity(0.10), radius: 12, x: 0, y: 6)
        }
        .padding(.horizontal, 12)
        .padding(.top, 6)
        .background(Color.clear)
    }
}

struct IOSEmptyStateCard: View {
    let title: String
    let message: String
    let symbolName: String
    let tint: Color

    init(
        title: String,
        message: String,
        symbolName: String,
        tint: Color
    ) {
        self.title = title
        self.message = message
        self.symbolName = symbolName
        self.tint = tint
    }

    var body: some View {
        IOSSurfaceCard(tint: tint) {
            VStack(alignment: .leading, spacing: 10) {
                Image(systemName: symbolName)
                    .font(.system(size: 20, weight: .semibold))
                    .foregroundStyle(tint)
                Text(title)
                    .font(.headline.weight(.semibold))
                    .foregroundStyle(Theme.Text.primary)
                Text(message)
                    .font(.footnote)
                    .foregroundStyle(Theme.Text.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}

struct IOSHeaderMetricRow: View {
    let label: String
    let value: String

    var body: some View {
        HStack(alignment: .top, spacing: 16) {
            Text(label)
                .font(.subheadline.weight(.medium))
                .foregroundStyle(Theme.Text.secondary.opacity(0.92))
            Spacer()
            Text(value)
                .font(.subheadline)
                .foregroundStyle(Theme.Text.primary)
                .multilineTextAlignment(.trailing)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.vertical, 5)
    }
}

private struct IOSFieldChromeModifier: ViewModifier {
    @ScaledMetric(relativeTo: .body) private var horizontalPadding = 11
    @ScaledMetric(relativeTo: .body) private var verticalPadding = 6
    @ScaledMetric(relativeTo: .body) private var minimumHeight = 36

    let isFocused: Bool
    let tint: Color

    func body(content: Content) -> some View {
        let shape = RoundedRectangle(cornerRadius: 16, style: .continuous)
        let strokeColor = isFocused ? Color.white.opacity(0.30) : Color.white.opacity(0.16)
        let strokeWidth = isFocused ? 1.0 : 0.8
        let fill = isFocused
            ? Theme.Surface.glassSurfaceMuted.opacity(0.90)
            : Theme.Surface.glassSurfaceMuted.opacity(0.74)

        content
            .frame(minHeight: minimumHeight)
            .padding(.horizontal, horizontalPadding)
            .padding(.vertical, verticalPadding)
            .iosSubtleGlassSurface(
                in: shape,
                tint: isFocused ? tint : Theme.Brand.silver,
                fill: fill,
                strokeOpacity: isFocused ? 0.18 : 0.12,
                interactive: true
            )
            .overlay {
                shape
                    .stroke(
                        strokeColor,
                        lineWidth: strokeWidth
                    )
                    .allowsHitTesting(false)
            }
            .iosAppAnimation(Theme.Motion.highlight, value: isFocused)
    }
}

private struct IOSSelectionFieldChromeModifier: ViewModifier {
    @ScaledMetric(relativeTo: .body) private var horizontalPadding = 11
    @ScaledMetric(relativeTo: .body) private var verticalPadding = 6
    @ScaledMetric(relativeTo: .body) private var minimumHeight = 36

    let isFocused: Bool
    let tint: Color

    func body(content: Content) -> some View {
        let shape = RoundedRectangle(cornerRadius: 15, style: .continuous)
        let fill = isFocused
            ? Theme.Surface.glassSurfaceMuted.opacity(0.72)
            : Theme.Surface.glassSurfaceMuted.opacity(0.56)
        let outerStroke = isFocused ? Color.white.opacity(0.20) : Color.white.opacity(0.10)
        let accentStroke = isFocused ? tint.opacity(0.22) : tint.opacity(0.10)

        content
            .frame(minHeight: minimumHeight)
            .padding(.horizontal, horizontalPadding)
            .padding(.vertical, verticalPadding)
            .iosSubtleGlassSurface(
                in: shape,
                tint: tint,
                fill: fill,
                strokeOpacity: isFocused ? 0.18 : 0.12,
                interactive: true
            )
            .overlay {
                shape
                    .stroke(outerStroke, lineWidth: isFocused ? 0.95 : 0.8)
                    .allowsHitTesting(false)
            }
            .overlay {
                shape
                    .inset(by: 1)
                    .stroke(accentStroke, lineWidth: isFocused ? 0.7 : 0.45)
                    .blendMode(.plusLighter)
                    .allowsHitTesting(false)
            }
            .overlay {
                shape
                    .fill(
                        LinearGradient(
                            colors: [
                                Color.white.opacity(isFocused ? 0.12 : 0.08),
                                Color.white.opacity(0.02),
                                .clear
                            ],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                    .mask(shape)
                    .allowsHitTesting(false)
            }
            .shadow(color: tint.opacity(isFocused ? 0.12 : 0.05), radius: isFocused ? 14 : 10, x: 0, y: 4)
            .iosAppAnimation(Theme.Motion.highlight, value: isFocused)
    }
}

private struct IOSCompactTextProminentUtilityButtonStyle: ButtonStyle {
    @ScaledMetric(relativeTo: .body) private var horizontalPadding = 16
    @ScaledMetric(relativeTo: .body) private var verticalPadding = 8

    let tint: Color

    func makeBody(configuration: Configuration) -> some View {
        let shape = Capsule(style: .continuous)
        let foreground = configuration.isPressed ? Theme.Text.onAccentPressed : Theme.Text.onAccent

        return configuration.label
            .foregroundStyle(foreground)
            .padding(.horizontal, horizontalPadding)
            .padding(.vertical, verticalPadding)
            .iosSubtleGlassSurface(
                in: shape,
                tint: tint,
                fill: tint.opacity(configuration.isPressed ? 0.18 : 0.15),
                strokeOpacity: configuration.isPressed ? 0.26 : 0.20,
                interactive: true
            )
            .overlay {
                shape
                    .stroke(tint.opacity(configuration.isPressed ? 0.34 : 0.28), lineWidth: 0.9)
            }
            .opacity(configuration.isPressed ? 0.96 : 1.0)
            .iosAppAnimation(Theme.Motion.press, value: configuration.isPressed)
    }
}

extension View {
    func iosFieldChrome(isFocused: Bool = false, tint: Color = Theme.Brand.gold) -> some View {
        modifier(IOSFieldChromeModifier(isFocused: isFocused, tint: tint))
    }

    func iosSelectionFieldChrome(
        tint: Color = Theme.Brand.gold,
        isFocused: Bool = false
    ) -> some View {
        modifier(
            IOSSelectionFieldChromeModifier(
                isFocused: isFocused,
                tint: tint
            )
        )
    }

    func iosAdaptiveUtilityButtonStyle(prominent: Bool = false, tint: Color? = nil) -> some View {
        iosAdaptiveUtilityButtonStyle(
            prominent: prominent,
            compactTextProminent: false,
            tint: tint
        )
    }

    func iosAdaptiveUtilityButtonStyle(
        prominent: Bool = false,
        compactTextProminent: Bool = false,
        tint: Color? = nil
    ) -> some View {
        Group {
            if compactTextProminent {
                self.buttonStyle(
                    IOSCompactTextProminentUtilityButtonStyle(
                        tint: tint ?? Theme.Brand.gold
                    )
                )
            } else if prominent {
                self.buttonStyle(.glassProminent)
            } else {
                self.buttonStyle(.glass)
            }
        }
        .tint(tint)
    }
}

struct IOSBottomPrimaryActionInset<Accessory: View, Content: View>: View {
    @ScaledMetric(relativeTo: .body) private var horizontalPadding = 16
    @ScaledMetric(relativeTo: .body) private var defaultAccessorySpacing = 10
    @ScaledMetric(relativeTo: .body) private var accessoryPresentSpacing = 8
    @ScaledMetric(relativeTo: .body) private var defaultTopPadding = 8
    @ScaledMetric(relativeTo: .body) private var accessoryPresentTopPadding = 8
    @ScaledMetric(relativeTo: .body) private var defaultBottomPadding = 10
    @ScaledMetric(relativeTo: .body) private var accessoryPresentBottomPadding = 22

    let showsAccessory: Bool

    let accessory: Accessory
    let content: Content

    init(
        showsAccessory: Bool = false,
        @ViewBuilder accessory: () -> Accessory,
        @ViewBuilder content: () -> Content
    ) {
        self.showsAccessory = showsAccessory
        self.accessory = accessory()
        self.content = content()
    }

    private var accessorySpacing: CGFloat {
        showsAccessory ? accessoryPresentSpacing : defaultAccessorySpacing
    }

    private var topPadding: CGFloat {
        showsAccessory ? accessoryPresentTopPadding : defaultTopPadding
    }

    private var bottomPadding: CGFloat {
        showsAccessory ? accessoryPresentBottomPadding : defaultBottomPadding
    }

    var body: some View {
        VStack(spacing: 0) {
            VStack(spacing: accessorySpacing) {
                accessory
                content
            }
                .padding(.horizontal, horizontalPadding)
                .padding(.top, topPadding)
                .padding(.bottom, bottomPadding)
        }
        .background(
            ZStack {
                LinearGradient(
                    colors: [
                        .clear,
                        Theme.Surface.canvasBottom.opacity(0.56),
                        Theme.Surface.canvasBottom.opacity(0.94)
                    ],
                    startPoint: .top,
                    endPoint: .bottom
                )
            }
            .ignoresSafeArea(edges: .bottom)
        )
    }
}

extension IOSBottomPrimaryActionInset where Accessory == EmptyView {
    init(@ViewBuilder content: () -> Content) {
        self.showsAccessory = false
        self.accessory = EmptyView()
        self.content = content()
    }
}

// Shared wrappers so the studio dock / section group / capsule selector do not
// each re-declare their glass parameters. All of these route through
// `iosSubtleGlassSurface` so material tuning stays in one place.
extension View {
    func iosDockGlass(tint: Color, cornerRadius: CGFloat = 30) -> some View {
        let shape = RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
        return self.iosSubtleGlassSurface(
            in: shape,
            tint: tint,
            fill: Theme.Surface.glassFloating.opacity(0.68),
            strokeOpacity: 0.12,
            interactive: true
        )
    }

    func iosSectionGlass(tint: Color, cornerRadius: CGFloat = 24) -> some View {
        let shape = RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
        return self.iosSubtleGlassSurface(
            in: shape,
            tint: tint,
            fill: Theme.Surface.glassSurface.opacity(0.58),
            strokeOpacity: 0.10
        )
    }

    // R2 cleanup (2026-05-21): `iosSelectorPillGlass(tint:)` and
    // `iosSelectorRailGlass(tint:)` were inlined into `IOSCapsuleSelector`
    // when its rail / pill recipe was rewritten to match the design's
    // `.vc-mode-segmented` spec. They had no other callers and have been
    // removed.
}
