import Dispatch
import SwiftUI
import UIKit
import QwenVoiceCore

extension Color {
    // The app is forced to `.preferredColorScheme(.dark)` at the window level
    // (see `QVoiceiOSApp.swift`), so every theme token is defined in the dark
    // variant only. If light mode is ever supported, replace this with a
    // `UIColor { traits in ... }` dynamic initializer.
    init(dark: UIColor) {
        self.init(uiColor: dark)
    }
}

enum IOSSelectionMotion {
    static let selection = Animation.easeOut(duration: 0.14)
    static let selectorPill = Animation.snappy(duration: 0.22, extraBounce: 0)
    static let selectorLabel = Animation.easeOut(duration: 0.12)
    static let highlight = Animation.easeOut(duration: 0.10)
    static let disclosure = Animation.easeOut(duration: 0.12)
    static let floatingPanel = Animation.spring(response: 0.30, dampingFraction: 0.84, blendDuration: 0.12)
    static let press = Animation.easeOut(duration: 0.09)
    static let modeCrossfade = Animation.easeInOut(duration: 0.18)
    static let miniPlayerSlide = Animation.spring(response: 0.32, dampingFraction: 0.84, blendDuration: 0.12)
}

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

enum IOSBrandTheme {
    static let productName = "Vocello"
    static let headerMarkAssetName = "VocelloHeaderMark"

    static let deepNav = Color(dark: UIColor(red: 0.055, green: 0.063, blue: 0.078, alpha: 1))
    static let accent = Color(dark: UIColor(red: 0.93, green: 0.80, blue: 0.54, alpha: 1))
    static let purple = Color(dark: UIColor(red: 0.73, green: 0.66, blue: 0.84, alpha: 1))
    static let lavender = Color(dark: UIColor(red: 0.87, green: 0.82, blue: 0.93, alpha: 1))
    static let silver = Color(dark: UIColor(red: 0.68, green: 0.71, blue: 0.76, alpha: 1))

    static let custom = accent
    // Mode color: #BFAADC per design_references/Vocello iOS/tokens.css (--mode-design).
    // Was #BFABDB; this aligns with the iOS design reference token.
    static let design = Color(dark: UIColor(red: 0.749, green: 0.667, blue: 0.863, alpha: 1))
    // Mode color: #DBA887 per design system (--mode-cloning).
    static let clone = Color(dark: UIColor(red: 0.859, green: 0.659, blue: 0.529, alpha: 1))
    static let library = Color(dark: UIColor(red: 0.75, green: 0.74, blue: 0.71, alpha: 1))
    static let settings = silver

    // Matches design tokens.css --canvas-bg: #161823. The warm wash
    // produced by IOSModeBackdrop needs this lighter base to read; a
    // near-black canvas hides the mode tint below the threshold of
    // perception.
    static let canvasTop = Color(dark: UIColor(red: 0.086, green: 0.094, blue: 0.137, alpha: 1))
    static let canvasBottom = Color(dark: UIColor(red: 0.038, green: 0.044, blue: 0.056, alpha: 1))
    static let surface = Color(dark: UIColor(red: 0.105, green: 0.112, blue: 0.132, alpha: 0.86))
    static let surfaceMuted = Color(dark: UIColor(red: 0.145, green: 0.152, blue: 0.174, alpha: 0.74))
    static let surfaceStroke = Color(dark: UIColor(red: 0.97, green: 0.92, blue: 0.82, alpha: 0.10))
    static let inputFill = Color(dark: UIColor(red: 0.120, green: 0.126, blue: 0.148, alpha: 1))
    static let inputFillUIColor = UIColor(red: 0.120, green: 0.126, blue: 0.148, alpha: 1)
    static let primaryTextUIColor = UIColor(red: 0.95, green: 0.94, blue: 0.92, alpha: 1)
    // Lightened from (0.50,0.53,0.58) so placeholder text clears WCAG-AA 4.5:1 on the
    // input/field fills (was ~3.8–4.4:1; now ≥5.3:1). Mirrors Theme.Text.placeholderUIColor.
    static let placeholderUIColor = UIColor(red: 0.60, green: 0.63, blue: 0.68, alpha: 1)
    static let primaryText = Color(uiColor: primaryTextUIColor)
    // Warm-neutral secondary text. Drops the prior cool blue chroma so the
    // palette tints toward the Vocello gold hue per the impeccable shared
    // design law and PRODUCT.md "Warm without volume".
    static let secondaryText = Color(dark: UIColor(red: 0.78, green: 0.76, blue: 0.72, alpha: 1))
    static let mutedText = Color(dark: UIColor(red: 0.62, green: 0.60, blue: 0.55, alpha: 1))
    static let inputStroke = Color(dark: UIColor(red: 0.96, green: 0.92, blue: 0.82, alpha: 0.12))
    static let bannerFill = Color(dark: UIColor(red: 0.18, green: 0.19, blue: 0.22, alpha: 0.92))
    static let tabBarBackground = Color(dark: UIColor(red: 0.075, green: 0.083, blue: 0.102, alpha: 0.93))
    static let dockSmoke = Color(dark: UIColor(red: 0.075, green: 0.083, blue: 0.102, alpha: 0.62))
    static let dockSmokeFallback = Color(dark: UIColor(red: 0.075, green: 0.083, blue: 0.102, alpha: 0.98))
    static let modeSwitcherFill = Color(dark: UIColor(red: 0.135, green: 0.142, blue: 0.164, alpha: 0.82))
    static let modeSwitcherStroke = Color(dark: UIColor(red: 0.97, green: 0.92, blue: 0.82, alpha: 0.08))
    static let brandChipFill = Color(dark: UIColor(red: 0.14, green: 0.15, blue: 0.18, alpha: 0.94))
    static let actionGlow = Color(dark: UIColor(red: 0.93, green: 0.80, blue: 0.54, alpha: 0.12))
    static let highlightGlow = Color(dark: UIColor(red: 0.90, green: 0.84, blue: 0.72, alpha: 0.07))

    static let memoryHealthy = Color(dark: UIColor(red: 0.55, green: 0.70, blue: 0.55, alpha: 1))
    static let memoryGuarded = Color(dark: UIColor(red: 0.85, green: 0.70, blue: 0.45, alpha: 1))
    static let memoryCritical = Color(dark: UIColor(red: 0.85, green: 0.50, blue: 0.50, alpha: 1))
    static let primaryActionGradient = LinearGradient(
        colors: [accent, accent.opacity(0.78)],
        startPoint: .topLeading,
        endPoint: .bottomTrailing
    )
    static let designAccentGradient = LinearGradient(
        colors: [design, lavender],
        startPoint: .topLeading,
        endPoint: .bottomTrailing
    )
    static let cloneAccentGradient = LinearGradient(
        colors: [accent, clone],
        startPoint: .topLeading,
        endPoint: .bottomTrailing
    )

    static func softGradient(for tint: Color) -> LinearGradient {
        LinearGradient(
            colors: [tint.opacity(0.92), tint.opacity(0.62)],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
    }

    static func modeColor(for mode: GenerationMode) -> Color {
        switch mode {
        case .custom:
            return custom
        case .design:
            return design
        case .clone:
            return clone
        }
    }
}

enum IOSAppTheme {
    static let backgroundTop = IOSBrandTheme.canvasTop
    static let backgroundBottom = IOSBrandTheme.canvasBottom
    static let surfacePrimary = IOSBrandTheme.surface
    static let surfaceSecondary = IOSBrandTheme.surfaceMuted
    static let surfaceStroke = IOSBrandTheme.surfaceStroke
    static let fieldFill = IOSBrandTheme.inputFill
    static let fieldFillUIColor = IOSBrandTheme.inputFillUIColor
    static let fieldStroke = IOSBrandTheme.inputStroke
    static let textPrimary = IOSBrandTheme.primaryText
    static let textSecondary = IOSBrandTheme.secondaryText
    static let textTertiary = IOSBrandTheme.mutedText
    static let textPrimaryUIColor = IOSBrandTheme.primaryTextUIColor
    static let textPlaceholderUIColor = IOSBrandTheme.placeholderUIColor
    static let tabBarBackground = IOSBrandTheme.tabBarBackground
    static let selectorFill = IOSBrandTheme.modeSwitcherFill
    static let selectorStroke = IOSBrandTheme.modeSwitcherStroke
    static let bannerFill = IOSBrandTheme.bannerFill
    static let accentGlow = IOSBrandTheme.actionGlow
    static let highlightGlow = IOSBrandTheme.highlightGlow
    static let glassClusterSpacing: CGFloat = 18
    static let glassSurfaceFill = IOSBrandTheme.surface.opacity(0.82)
    static let glassSurfaceFillMuted = IOSBrandTheme.surfaceMuted.opacity(0.74)
    static let glassFloatingFill = IOSBrandTheme.tabBarBackground.opacity(0.66)
    static let glassOuterStroke = Color.white.opacity(0.12)
    static let glassInnerStroke = Color.white.opacity(0.04)
    static let cardCornerRadius: CGFloat = 16
    static let cardShadowRadius: CGFloat = 8
    static let cardShadowOffset: CGFloat = 3

    // Foreground ink for text sitting on top of accent-tinted fills.
    static let accentForeground = Color(dark: UIColor(red: 0.10, green: 0.085, blue: 0.055, alpha: 0.82))
    static let accentForegroundPressed = Color(dark: UIColor(red: 0.10, green: 0.085, blue: 0.055, alpha: 0.74))
    // Subtle separator between rows on dark surfaces.
    static let hairlineDivider = Color.white.opacity(0.08)

    static func accentSurface(_ tint: Color) -> Color {
        tint.opacity(0.10)
    }

    // Strong mode-tinted stroke. Matches macOS accentStroke (34% dark / 28%
    // light); iOS is dark-only so we land at 34%.
    static func accentStroke(_ tint: Color) -> Color {
        tint.opacity(0.34)
    }

    // Whisper accent wash for selected chips and pills. Matches macOS
    // accentWash (20% dark). Used by the mode selector and emotion chips.
    static func accentWash(_ tint: Color) -> Color {
        tint.opacity(0.20)
    }

    static func accentFill(_ tint: Color) -> LinearGradient {
        LinearGradient(
            colors: [tint.opacity(0.96), tint.opacity(0.82)],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
    }

    static func mutedFill(for colorScheme: ColorScheme) -> Color {
        Color.white.opacity(0.05)
    }

    // Mode-aware glass tint. Matches macOS surfaceGlassTint (14% dark) when
    // a tint is supplied; falls back to a neutral smoked glass at 10% dark
    // when nil. Tunes "warm without volume" per PRODUCT.md.
    static func subtleGlassTint(_ tint: Color? = nil, intensity: Double = 1.0) -> Color {
        let base = tint ?? IOSBrandTheme.silver
        let opacity = (tint == nil) ? 0.10 : 0.14
        return base.opacity(opacity * intensity)
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
                    .stroke(IOSAppTheme.glassInnerStroke, lineWidth: 0.55)
                    .allowsHitTesting(false)
            }

        // The gate decision lives in the shared IOSGatedGlassModifier
        // (IUI-5 D10a); `fill` above already paints the solid base, so the
        // gated branch needs no extra backing here.
        base.iosGatedGlass(
            tint: IOSAppTheme.subtleGlassTint(tint, intensity: 0.9),
            in: shape,
            interactive: interactive
        )
    }
}

extension View {
    func iosSubtleGlassSurface<S: InsettableShape>(
        in shape: S,
        tint: Color? = nil,
        fill: Color = IOSAppTheme.glassSurfaceFill,
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
        IOSBrandTheme.canvasBottom
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
        let shape = RoundedRectangle(cornerRadius: IOSAppTheme.cardCornerRadius, style: .continuous)

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
                .foregroundStyle(IOSAppTheme.textSecondary)
            if let subtitle, !subtitle.isEmpty {
                Text(subtitle)
                    .font(.caption)
                    .foregroundStyle(IOSAppTheme.textSecondary)
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
                    .foregroundStyle(IOSAppTheme.textPrimary)

                Spacer(minLength: 8)

                if let badgeText, let badgeTone {
                    IOSStatusBadge(text: badgeText, tone: badgeTone)
                }
            }

            if let message, !message.isEmpty {
                Text(message)
                    .font(.caption2)
                    .foregroundStyle(IOSAppTheme.textSecondary)
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
                        .foregroundStyle(IOSAppTheme.textPrimary)
                        .multilineTextAlignment(.leading)
                    Text(subtitle)
                        .font(.body)
                        .foregroundStyle(IOSAppTheme.textSecondary)
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
                        .foregroundStyle(IOSAppTheme.textPrimary)
                        .lineLimit(1)
                        .minimumScaleFactor(0.9)

                    Text(subtitle)
                        .font(.subheadline)
                        .foregroundStyle(IOSAppTheme.textSecondary)
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
            .foregroundStyle(IOSAppTheme.textPrimary)
            .padding(.horizontal, 10)
            .padding(.vertical, 5)
            .iosSubtleGlassSurface(
                in: shape,
                tint: tint,
                fill: IOSAppTheme.glassSurfaceFillMuted.opacity(0.52),
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
                    .foregroundStyle(IOSAppTheme.textSecondary.opacity(subtitleProminence))
                    .lineLimit(1)
                    .truncationMode(.tail)
                    .layoutPriority(0.5)
            }

            if let trailingAccessory {
                trailingAccessory
                    .layoutPriority(0.75)
            }

            if let runtimeLabel, !runtimeLabel.isEmpty {
                IOSStudioHeaderChip(title: runtimeLabel, tint: IOSBrandTheme.accent)
            }

            if let modelLabel, !modelLabel.isEmpty {
                IOSStudioHeaderChip(title: modelLabel, tint: IOSBrandTheme.library)
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
                .foregroundStyle(IOSAppTheme.textPrimary)
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
            Image(IOSBrandTheme.headerMarkAssetName)
                .renderingMode(.original)
                .resizable()
                .interpolation(.high)
                .antialiased(true)
                .scaledToFit()
                .frame(width: markWidth, height: markHeight)
                .accessibilityHidden(true)

            Text(title)
                .font(.system(.title3, design: .rounded, weight: .semibold))
                .foregroundStyle(IOSAppTheme.textPrimary)
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
        tint: Color = IOSBrandTheme.accent
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
                    .foregroundStyle(IOSAppTheme.textPrimary)

                if let message, !message.isEmpty {
                    Text(message)
                        .font(.caption)
                        .foregroundStyle(IOSAppTheme.textSecondary)
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
            fill: IOSAppTheme.glassSurfaceFillMuted,
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
        tint: Color = IOSBrandTheme.accent
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
                    .foregroundStyle(IOSAppTheme.textPrimary)
                Text(message)
                    .font(.subheadline)
                    .foregroundStyle(IOSAppTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(verticalPadding)
        .iosSubtleGlassSurface(
            in: shape,
            tint: tint,
            fill: IOSAppTheme.glassSurfaceFill,
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
                .foregroundStyle(state.isOverLimit ? .orange : IOSAppTheme.textSecondary)
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
                    IOSAppTheme.backgroundTop.opacity(0.96),
                    IOSAppTheme.backgroundTop.opacity(0.90),
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
                tint: IOSBrandTheme.accent,
                fill: IOSAppTheme.glassFloatingFill,
                strokeOpacity: 0.14
            )
            .shadow(color: IOSAppTheme.accentGlow.opacity(0.10), radius: 12, x: 0, y: 6)
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
                    .foregroundStyle(IOSAppTheme.textPrimary)
                Text(message)
                    .font(.footnote)
                    .foregroundStyle(IOSAppTheme.textSecondary)
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
                .foregroundStyle(IOSAppTheme.textSecondary.opacity(0.92))
            Spacer()
            Text(value)
                .font(.subheadline)
                .foregroundStyle(IOSAppTheme.textPrimary)
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
            ? IOSAppTheme.glassSurfaceFillMuted.opacity(0.90)
            : IOSAppTheme.glassSurfaceFillMuted.opacity(0.74)

        content
            .frame(minHeight: minimumHeight)
            .padding(.horizontal, horizontalPadding)
            .padding(.vertical, verticalPadding)
            .iosSubtleGlassSurface(
                in: shape,
                tint: isFocused ? tint : IOSBrandTheme.silver,
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
            .iosAppAnimation(IOSSelectionMotion.highlight, value: isFocused)
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
            ? IOSAppTheme.glassSurfaceFillMuted.opacity(0.72)
            : IOSAppTheme.glassSurfaceFillMuted.opacity(0.56)
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
            .iosAppAnimation(IOSSelectionMotion.highlight, value: isFocused)
    }
}

private struct IOSCompactTextProminentUtilityButtonStyle: ButtonStyle {
    @ScaledMetric(relativeTo: .body) private var horizontalPadding = 16
    @ScaledMetric(relativeTo: .body) private var verticalPadding = 8

    let tint: Color

    func makeBody(configuration: Configuration) -> some View {
        let shape = Capsule(style: .continuous)
        let foreground = configuration.isPressed ? IOSAppTheme.accentForegroundPressed : IOSAppTheme.accentForeground

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
            .iosAppAnimation(IOSSelectionMotion.press, value: configuration.isPressed)
    }
}

extension View {
    func iosFieldChrome(isFocused: Bool = false, tint: Color = IOSBrandTheme.accent) -> some View {
        modifier(IOSFieldChromeModifier(isFocused: isFocused, tint: tint))
    }

    func iosSelectionFieldChrome(
        tint: Color = IOSBrandTheme.accent,
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
                        tint: tint ?? IOSBrandTheme.accent
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
                        IOSAppTheme.backgroundBottom.opacity(0.56),
                        IOSAppTheme.backgroundBottom.opacity(0.94)
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
            fill: IOSAppTheme.glassFloatingFill.opacity(0.68),
            strokeOpacity: 0.12,
            interactive: true
        )
    }

    func iosSectionGlass(tint: Color, cornerRadius: CGFloat = 24) -> some View {
        let shape = RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
        return self.iosSubtleGlassSurface(
            in: shape,
            tint: tint,
            fill: IOSAppTheme.glassSurfaceFill.opacity(0.58),
            strokeOpacity: 0.10
        )
    }

    // R2 cleanup (2026-05-21): `iosSelectorPillGlass(tint:)` and
    // `iosSelectorRailGlass(tint:)` were inlined into `IOSCapsuleSelector`
    // when its rail / pill recipe was rewritten to match the design's
    // `.vc-mode-segmented` spec. They had no other callers and have been
    // removed.
}
