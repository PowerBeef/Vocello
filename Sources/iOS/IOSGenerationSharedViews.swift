import SwiftUI
import UIKit

struct IOSGenerateModeViewport<Custom: View, Design: View, Clone: View>: View {
    let selection: IOSGenerationSection
    let custom: () -> Custom
    let design: () -> Design
    let clone: () -> Clone

    init(
        selection: IOSGenerationSection,
        @ViewBuilder custom: @escaping () -> Custom,
        @ViewBuilder design: @escaping () -> Design,
        @ViewBuilder clone: @escaping () -> Clone
    ) {
        self.selection = selection
        self.custom = custom
        self.design = design
        self.clone = clone
    }

    var body: some View {
        Group {
            switch selection {
            case .custom:
                layer(custom())
            case .design:
                layer(design())
            case .clone:
                layer(clone())
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .clipped()
        .iosAppAnimation(IOSSelectionMotion.modeCrossfade, value: selection)
    }

    private func layer<Content: View>(_ content: Content) -> some View {
        content
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }
}

struct IOSComposerCardAction: View {
    let title: String
    let systemImage: String
    let tint: Color
    let accessibilityIdentifier: String?
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Label(title, systemImage: systemImage)
                .font(.footnote.weight(.semibold))
                .lineLimit(1)
        }
        .iosAdaptiveUtilityButtonStyle(tint: tint)
        .accessibilityIdentifier(accessibilityIdentifier ?? "")
    }
}

struct IOSStudioComposerCard<Accessory: View, Setup: View>: View {
    @ScaledMetric(relativeTo: .body) private var sharedPromptLineCount = 3
    @ScaledMetric(relativeTo: .body) private var contentPadding = 12
    @ScaledMetric(relativeTo: .body) private var headerSpacing = 0
    @ScaledMetric(relativeTo: .body) private var titleSpacing = 6
    @ScaledMetric(relativeTo: .body) private var setupTopSpacing = 8
    @ScaledMetric(relativeTo: .body) private var sectionSpacing = 8
    @ScaledMetric(relativeTo: .body) private var sectionHeaderBottomSpacing = 4

    let title: String?
    let subtitle: String
    let promptSectionTitle: String
    let setupSectionTitle: String
    let tint: Color
    let helper: String?
    @Binding var text: String
    let placeholder: String
    @Binding var isFocused: Bool
    let accessibilityIdentifier: String
    let counterText: String
    let counterTone: Color
    let helperTone: Color
    let notice: String?
    let noticeTint: Color?
    let maxCharacterCount: Int?
    let accessory: Accessory
    let setup: Setup

    init(
        title: String? = nil,
        subtitle: String,
        promptSectionTitle: String = "Prompt",
        setupSectionTitle: String,
        tint: Color,
        helper: String?,
        text: Binding<String>,
        placeholder: String,
        isFocused: Binding<Bool>,
        accessibilityIdentifier: String,
        counterText: String,
        counterTone: Color,
        helperTone: Color,
        notice: String? = nil,
        noticeTint: Color? = nil,
        maxCharacterCount: Int? = nil,
        @ViewBuilder accessory: () -> Accessory,
        @ViewBuilder setup: () -> Setup
    ) {
        self.title = title
        self.subtitle = subtitle
        self.promptSectionTitle = promptSectionTitle
        self.setupSectionTitle = setupSectionTitle
        self.tint = tint
        self.helper = helper
        _text = text
        self.placeholder = placeholder
        _isFocused = isFocused
        self.accessibilityIdentifier = accessibilityIdentifier
        self.counterText = counterText
        self.counterTone = counterTone
        self.helperTone = helperTone
        self.notice = notice
        self.noticeTint = noticeTint
        self.maxCharacterCount = maxCharacterCount
        self.accessory = accessory()
        self.setup = setup()
    }

    private var editorHeight: CGFloat {
        let bodyLineHeight = UIFont.preferredFont(forTextStyle: .body).lineHeight
        let verticalInsets: CGFloat = 32
        return ceil((bodyLineHeight * sharedPromptLineCount) + verticalInsets)
    }

    private var hasSubtitle: Bool {
        !subtitle.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private var hasTitle: Bool {
        if let title {
            return !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        }
        return false
    }

    var body: some View {
        VStack(alignment: .leading, spacing: sectionSpacing) {
            if hasTitle || hasSubtitle {
                HStack(alignment: .top, spacing: 12) {
                    VStack(alignment: .leading, spacing: headerSpacing) {
                        if let title, hasTitle {
                            Text(title)
                                .font(.subheadline.weight(.semibold))
                                .tracking(0.05)
                                .foregroundStyle(IOSAppTheme.textPrimary)
                                .lineLimit(1)
                                .minimumScaleFactor(0.8)
                                .fixedSize(horizontal: false, vertical: true)

                            if hasSubtitle {
                                Text(subtitle)
                                    .font(.caption)
                                    .foregroundStyle(IOSAppTheme.textSecondary)
                                    .lineLimit(2)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        } else if hasSubtitle {
                            Text(subtitle)
                                .font(.headline.weight(.semibold))
                                .foregroundStyle(IOSAppTheme.textPrimary)
                                .lineLimit(2)
                                .fixedSize(horizontal: false, vertical: true)

                            if let helper, !helper.isEmpty, text.isEmpty {
                                Text(helper)
                                    .font(.footnote)
                                    .foregroundStyle(helperTone)
                                    .lineLimit(2)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        }
                    }
                    .layoutPriority(1)

                    Spacer(minLength: 8)

                    accessory
                }
            } else {
                accessory
                    .frame(maxWidth: .infinity, alignment: .trailing)
            }

            if let notice, !notice.isEmpty, let noticeTint {
                IOSCompactInlineNotice(
                    message: notice,
                    symbolName: "exclamationmark.triangle.fill",
                    tint: noticeTint
                )
            }

            VStack(alignment: .leading, spacing: titleSpacing) {
                IOSComposerSectionHeader(title: promptSectionTitle)

                IOSMultilineTextView(
                    text: $text,
                    placeholder: placeholder,
                    tint: tint,
                    isFocused: $isFocused,
                    maxCharacterCount: maxCharacterCount,
                    accessibilityIdentifier: accessibilityIdentifier
                )
                .frame(height: editorHeight)
                .clipped()

                HStack(alignment: .firstTextBaseline, spacing: 10) {
                    if let helper, !helper.isEmpty, !text.isEmpty {
                        Text(helper)
                            .font(.caption)
                            .foregroundStyle(helperTone)
                            .lineLimit(2)
                            .accessibilityIdentifier(IOSAccessibilityIdentifier.TextInput.limitMessage)
                    }

                    Spacer(minLength: 8)

                    Text(counterText)
                        .font(.caption2.monospacedDigit().weight(.semibold))
                        .foregroundStyle(counterTone)
                        .accessibilityIdentifier(IOSAccessibilityIdentifier.TextInput.lengthCount)
                }
            }

            VStack(alignment: .leading, spacing: 8) {
                IOSComposerSectionHeader(title: setupSectionTitle)
                    .padding(.bottom, sectionHeaderBottomSpacing)

                setup
            }
            .padding(.top, setupTopSpacing)
        }
        .padding(contentPadding)
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityIdentifier(IOSAccessibilityIdentifier.TextInput.lengthStatus)
    }
}

private struct IOSComposerSectionHeader: View {
    let title: String

    var body: some View {
        Text(title.uppercased())
            .font(.caption2.weight(.semibold))
            .tracking(0.8)
            .foregroundStyle(IOSAppTheme.textSecondary.opacity(0.95))
            .frame(maxWidth: .infinity, alignment: .leading)
            .accessibilityLabel(title)
            .accessibilityAddTraits(.isHeader)
    }
}

struct IOSCompactPromptCard: View {
    let title: String
    let helper: String?
    @Binding var text: String
    let placeholder: String
    let tint: Color
    @Binding var isFocused: Bool
    let accessibilityIdentifier: String
    let counterText: String
    let counterTone: Color
    let helperTone: Color

    var body: some View {
        IOSSurfaceCard(tint: tint) {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Text(title)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(IOSAppTheme.textPrimary)

                Spacer(minLength: 8)

                Text(counterText)
                    .font(.caption2.monospacedDigit().weight(.semibold))
                    .foregroundStyle(counterTone)
                    .accessibilityIdentifier(IOSAccessibilityIdentifier.TextInput.lengthCount)
            }

            if let helper, !helper.isEmpty {
                Text(helper)
                    .font(.caption)
                    .foregroundStyle(helperTone)
                    .lineLimit(2)
                    .accessibilityIdentifier(IOSAccessibilityIdentifier.TextInput.limitMessage)
            }

            IOSMultilineTextView(
                text: $text,
                placeholder: placeholder,
                tint: tint,
                isFocused: $isFocused,
                accessibilityIdentifier: accessibilityIdentifier
            )
            .frame(maxHeight: .infinity)
            .clipped()
        }
        .frame(maxHeight: .infinity, alignment: .top)
        .accessibilityIdentifier(IOSAccessibilityIdentifier.TextInput.lengthStatus)
    }
}

struct IOSCompactInlineNotice: View {
    let message: String
    let symbolName: String
    let tint: Color

    @Environment(\.iosReduceTransparencyEnabled) private var reduceTransparency

    var body: some View {
        let shape = RoundedRectangle(cornerRadius: 14, style: .continuous)

        HStack(spacing: 8) {
            Image(systemName: symbolName)
                .font(.caption2.weight(.semibold))
                .foregroundStyle(tint)

            Text(message)
                .font(.caption)
                .foregroundStyle(IOSAppTheme.textSecondary)
                .lineLimit(2)

            Spacer(minLength: 0)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 7)
        .background {
            // Solid-fill backing painted unconditionally so Reduce
            // Transparency sees a real surface instead of a transparent gap.
            shape.fill(tint.opacity(reduceTransparency ? 0.18 : 0.06))
        }
        .iosGatedGlass(tint: tint.opacity(0.06), in: shape)
        .overlay {
            shape
                .stroke(Color.white.opacity(0.14), lineWidth: 0.75)
        }
    }
}

private struct IOSGenerateMiniPlayerTimeline: View {
    @EnvironmentObject private var playbackProgress: AudioPlayerViewModel.PlaybackProgress

    @ScaledMetric(relativeTo: .caption2) private var itemSpacing = 8
    @ScaledMetric(relativeTo: .caption2) private var railMinWidth = 92

    let canSeek: Bool
    let durationText: String
    let onSeek: (Double) -> Void

    var body: some View {
        HStack(alignment: .center, spacing: itemSpacing) {
            Text(playbackProgress.formattedCurrentTime)
                .font(.caption2.monospacedDigit().weight(.medium))
                .foregroundStyle(IOSAppTheme.textSecondary)
                .contentTransition(.numericText())

            IOSGenerateMiniPlayerProgressRail(
                canSeek: canSeek,
                durationText: durationText,
                onSeek: onSeek
            )
            .frame(minWidth: railMinWidth)

            Text(durationText)
                .font(.caption2.monospacedDigit().weight(.medium))
                .foregroundStyle(IOSAppTheme.textTertiary)
                .contentTransition(.numericText())
        }
    }
}

private struct IOSGenerateMiniPlayerProgressRail: View {
    @EnvironmentObject private var playbackProgress: AudioPlayerViewModel.PlaybackProgress
    @GestureState private var dragFraction: Double?

    @ScaledMetric(relativeTo: .caption2) private var railHeight = 4

    let canSeek: Bool
    let durationText: String
    let onSeek: (Double) -> Void

    private var displayedProgress: Double {
        dragFraction ?? playbackProgress.progress
    }

    var body: some View {
        GeometryReader { proxy in
            let rail = railBody(width: proxy.size.width)

            if canSeek {
                rail
                    .gesture(dragGesture(width: proxy.size.width))
            } else {
                rail
            }
        }
        .frame(height: railHeight)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(canSeek ? "Preview playback progress" : "Live preview progress")
        .accessibilityValue("\(playbackProgress.formattedCurrentTime) of \(durationText)")
        .accessibilityIdentifier("generate_miniPlayer_seekRail")
        .accessibilityAdjustableAction { direction in
            guard canSeek else { return }
            let step = 0.05
            let baseProgress = dragFraction ?? playbackProgress.progress
            switch direction {
            case .increment:
                onSeek(min(baseProgress + step, 1))
            case .decrement:
                onSeek(max(baseProgress - step, 0))
            @unknown default:
                break
            }
        }
    }

    private func railBody(width: CGFloat) -> some View {
        let progress = max(0, min(displayedProgress, 1))
        let fillWidth = width * progress

        return ZStack(alignment: .leading) {
            Capsule(style: .continuous)
                .fill(Color.white.opacity(0.12))

            Capsule(style: .continuous)
                .fill(
                    LinearGradient(
                        colors: [
                            Color.white.opacity(0.88),
                            IOSBrandTheme.silver.opacity(0.62)
                        ],
                        startPoint: .leading,
                        endPoint: .trailing
                    )
                )
                .frame(width: progress > 0 ? max(fillWidth, railHeight) : railHeight)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .contentShape(Rectangle())
    }

    private func dragGesture(width: CGFloat) -> some Gesture {
        DragGesture(minimumDistance: 0)
            .updating($dragFraction) { value, state, _ in
                state = normalizedFraction(for: value.location.x, width: width)
            }
            .onEnded { value in
                onSeek(normalizedFraction(for: value.location.x, width: width))
            }
    }

    private func normalizedFraction(for locationX: CGFloat, width: CGFloat) -> Double {
        guard width > 0 else { return 0 }
        let clampedX = min(max(locationX, 0), width)
        return Double(clampedX / width)
    }
}

private struct IOSGenerateMiniPlayerButtonChrome: View {
    @ScaledMetric(relativeTo: .caption) private var controlSize = 40
    @ScaledMetric(relativeTo: .caption) private var symbolSize = 16

    let symbolName: String

    var body: some View {
        IOSPlayerIconButtonChrome(
            symbol: symbolName,
            size: controlSize,
            symbolSize: symbolSize
        )
    }
}

private struct IOSGenerateMiniPlayerProgressChrome: View {
    @ScaledMetric(relativeTo: .caption) private var controlSize = 40

    var body: some View {
        ProgressView()
            .progressViewStyle(.circular)
            .tint(IOSBrandTheme.silver)
            .frame(width: controlSize, height: controlSize)
            .background {
                Circle()
                    .fill(Color.white.opacity(0.06))
            }
            .overlay {
                Circle()
                    .stroke(Color.white.opacity(0.10), lineWidth: 0.5)
            }
            .accessibilityLabel("Preparing preview")
    }
}
