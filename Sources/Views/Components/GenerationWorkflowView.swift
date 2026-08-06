import QwenVoiceCore
import SwiftUI

private extension View {
    @ViewBuilder
    func optionalAccessibilityIdentifier(_ identifier: String?) -> some View {
        if let identifier {
            accessibilityIdentifier(identifier)
        } else {
            self
        }
    }
}

struct PageScaffold<Header: View, Content: View>: View {
    let accessibilityIdentifier: String?
    let fillsViewportHeight: Bool
    let contentSpacing: CGFloat
    let contentMaxWidth: CGFloat
    let topPadding: CGFloat
    let bottomPadding: CGFloat
    @ViewBuilder let header: () -> Header
    @ViewBuilder let content: () -> Content

    init(
        accessibilityIdentifier: String? = nil,
        fillsViewportHeight: Bool = false,
        contentSpacing: CGFloat = LayoutConstants.sectionSpacing,
        contentMaxWidth: CGFloat = LayoutConstants.contentMaxWidth,
        topPadding: CGFloat = 8,
        bottomPadding: CGFloat = LayoutConstants.canvasPadding,
        @ViewBuilder header: @escaping () -> Header,
        @ViewBuilder content: @escaping () -> Content
    ) {
        self.accessibilityIdentifier = accessibilityIdentifier
        self.fillsViewportHeight = fillsViewportHeight
        self.contentSpacing = contentSpacing
        self.contentMaxWidth = contentMaxWidth
        self.topPadding = topPadding
        self.bottomPadding = bottomPadding
        self.header = header
        self.content = content
    }

    var body: some View {
        GeometryReader { proxy in
            ScrollView {
                contentColumn(viewportHeight: fillsViewportHeight ? proxy.size.height : nil)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .profileBackground(Color(nsColor: .windowBackgroundColor))
        }
        .optionalAccessibilityIdentifier(accessibilityIdentifier)
    }

    @ViewBuilder
    private func contentColumn(viewportHeight: CGFloat?) -> some View {
        let column = VStack(alignment: .leading, spacing: contentSpacing) {
            header()
            content()
        }
        .padding(.horizontal, 8)
        .padding(.top, topPadding)
        .padding(.bottom, bottomPadding)
        .contentColumn(maxWidth: contentMaxWidth)

        if let viewportHeight {
            column
                .frame(
                    maxWidth: .infinity,
                    minHeight: viewportHeight,
                    alignment: .topLeading
                )
        } else {
            column
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

extension PageScaffold where Header == EmptyView {
    init(
        accessibilityIdentifier: String? = nil,
        fillsViewportHeight: Bool = false,
        contentSpacing: CGFloat = LayoutConstants.sectionSpacing,
        contentMaxWidth: CGFloat = LayoutConstants.contentMaxWidth,
        topPadding: CGFloat = 8,
        bottomPadding: CGFloat = LayoutConstants.canvasPadding,
        @ViewBuilder content: @escaping () -> Content
    ) {
        self.init(
            accessibilityIdentifier: accessibilityIdentifier,
            fillsViewportHeight: fillsViewportHeight,
            contentSpacing: contentSpacing,
            contentMaxWidth: contentMaxWidth,
            topPadding: topPadding,
            bottomPadding: bottomPadding,
            header: { EmptyView() },
            content: content
        )
    }
}

struct WorkflowReadinessNote: View {
    let isReady: Bool
    let title: String
    let detail: String
    var accentColor: Color = AppTheme.accent
    var isBusy: Bool = false
    var accessibilityIdentifier: String? = nil

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            if isBusy {
                // Static busy glyph, deliberately not an indeterminate
                // spinner: a continuously animating element above the Liquid
                // Glass stack forces full-window recomposition at display
                // rate for the whole generation, and on the 8 GB tier that
                // compositor load queues ahead of the engine's GPU work
                // (2026-07-22 pipeline-pacing diagnosis). The label text
                // carries the in-progress state.
                Image(systemName: "waveform")
                    .font(.subheadline)
                    .foregroundStyle(accentColor)
                    .frame(width: 16, height: 16)
            } else {
                // Audit Batch 5c: stronger ready vs not-ready icon
                // contrast. `checkmark.seal.fill` (sealed badge) reads
                // heavier than the plain circle; `clock` is shape-
                // distinct from a checkmark so a quick glance lands the
                // state without parsing color.
                Image(systemName: isReady ? "checkmark.seal.fill" : "clock")
                    .font(.subheadline)
                    .foregroundStyle(isReady ? accentColor : .secondary)
            }

            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.subheadline.weight(.semibold))
                Text(detail)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }

            Spacer(minLength: 0)
        }
        .padding(.vertical, 2)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(title)
        // Human-readable for VoiceOver; the XCUITest readiness wait matches
        // "Ready" (capital R — "Waiting" must never contain it).
        .accessibilityValue(isReady ? "Ready" : "Waiting")
        .optionalAccessibilityIdentifier(accessibilityIdentifier)
    }
}

enum StudioCardStyle {
    case standard
    case inline
}

struct StudioSectionCard<Content: View>: View {
    @Environment(\.cardGlassTint) private var cardGlassTint

    let title: String
    var detail: String? = nil
    var iconName: String? = nil
    var accentColor: Color = AppTheme.accent
    var trailingText: String? = nil
    var minHeight: CGFloat? = nil
    var fillsAvailableHeight: Bool = false
    var contentAlignment: HorizontalAlignment = .leading
    var style: StudioCardStyle = .standard
    var accessibilityIdentifier: String? = nil
    @ViewBuilder let content: () -> Content

    var body: some View {
        styledCard
            .frame(maxHeight: fillsAvailableHeight ? .infinity : nil, alignment: .topLeading)
            .accessibilityElement(children: .contain)
            .optionalAccessibilityIdentifier(accessibilityIdentifier)
    }

    private var cardContent: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                if let iconName {
                    Image(systemName: iconName)
                        .foregroundStyle(accentColor)
                }

                Text(title)
                    .font(.subheadline.weight(.semibold))

                Spacer(minLength: 8)

                if let trailingText {
                    Text(trailingText)
                        .font(.footnote.weight(.semibold))
                        .foregroundStyle(.secondary)
                }
            }

            VStack(alignment: contentAlignment, spacing: style == .inline ? 8 : 10) {
                if let detail {
                    Text(detail)
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }

                content()
            }
            .frame(
                maxWidth: .infinity,
                minHeight: minHeight,
                maxHeight: fillsAvailableHeight ? .infinity : nil,
                alignment: .topLeading
            )
        }
    }

    private var styledCard: some View {
        GatedGlass {
            cardContent
                .padding(12)
                .background(
                    RoundedRectangle(cornerRadius: 16, style: .continuous)
                        .fill(AppTheme.cardFill)
                        .overlay(
                            RoundedRectangle(cornerRadius: 16, style: .continuous)
                                .strokeBorder(
                                    cardGlassTint.map {
                                        AppTheme.accentStroke($0).opacity(0.55)
                                    } ?? AppTheme.cardStroke.opacity(AppTheme.surfaceStrokeOpacity),
                                    lineWidth: AppTheme.surfaceStrokeWidth
                                )
                        )
                )
                .glassEffect(
                    .regular.tint(
                        cardGlassTint.map {
                            AppTheme.surfaceGlassTint($0)
                        } ?? AppTheme.smokedGlassTint
                    ),
                    in: .rect(cornerRadius: 16)
                )
                .glass3DDepth(radius: 16, intensity: cardGlassTint == nil ? 1.0 : 1.15)
        } fallback: {
            legacyStyledCard
        }
    }

    private var legacyStyledCard: some View {
        cardContent
            .padding(12)
            .background(
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .fill(AppTheme.cardFill)
            )
            .overlay(
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .stroke(
                        AppTheme.cardStroke.opacity(0.12),
                        lineWidth: 1.0
                    )
            )
    }
}

struct CompactConfigurationSection<Content: View>: View {
    @Environment(\.cardGlassTint) private var cardGlassTint

    let title: String
    var detail: String? = nil
    var iconName: String? = nil
    var accentColor: Color = AppTheme.accent
    var trailingText: String? = nil
    var trailingAccessory: AnyView? = nil
    var rowSpacing: CGFloat = LayoutConstants.configurationRowSpacing
    var panelPadding: CGFloat = LayoutConstants.configurationPanelPadding
    var contentSlotHeight: CGFloat? = nil
    var accessibilityIdentifier: String? = nil
    @ViewBuilder let content: () -> Content

    private var panelCornerRadius: CGFloat {
        LayoutConstants.cardRadius
    }

    var body: some View {
        VStack(alignment: .leading, spacing: rowSpacing) {
            header

            if let detail {
                Text(detail)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            panelBody
            .padding(.horizontal, panelPadding)
            .padding(.vertical, max(panelPadding - 1, 0))
            .background {
                GatedGlass {
                    RoundedRectangle(cornerRadius: panelCornerRadius, style: .continuous)
                        .fill(AppTheme.inlineFill)
                        .overlay(
                            RoundedRectangle(cornerRadius: panelCornerRadius, style: .continuous)
                                .strokeBorder(
                                    AppTheme.inlineStroke.opacity(AppTheme.surfaceStrokeOpacity),
                                    lineWidth: AppTheme.surfaceStrokeWidth
                                )
                        )
                        .glassEffect(
                            .regular.tint(
                                cardGlassTint.map {
                                    AppTheme.surfaceGlassTint($0)
                                } ?? AppTheme.smokedGlassTint
                            ),
                            in: .rect(cornerRadius: panelCornerRadius)
                        )
                        .glass3DDepth(
                            radius: panelCornerRadius,
                            intensity: cardGlassTint == nil ? 1.0 : 1.15
                        )
                } fallback: {
                    compactPanelLegacyBackground
                }
            }
        }
        .optionalAccessibilityIdentifier(accessibilityIdentifier)
    }

    @ViewBuilder
    private var header: some View {
        if let trailingAccessory {
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .center, spacing: 12) {
                    headerTitle
                    Spacer(minLength: 10)
                    trailingAccessory
                }

                VStack(alignment: .leading, spacing: 8) {
                    headerTitle
                    trailingAccessory
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        } else {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                headerTitle
                Spacer(minLength: 10)

                if let trailingText {
                    Text(trailingText)
                        .font(.footnote.weight(.semibold))
                        .foregroundStyle(.secondary)
                }
            }
        }
    }

    private var headerTitle: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            if let iconName {
                Image(systemName: iconName)
                    .font(.body.weight(.semibold))
                    .foregroundStyle(accentColor)
            }

            Text(title)
                .font(.headline.weight(.semibold))
        }
    }

    @ViewBuilder
    private var panelBody: some View {
        if let contentSlotHeight {
            VStack(alignment: .leading, spacing: 0) {
                content()
            }
            .frame(
                maxWidth: .infinity,
                minHeight: contentSlotHeight,
                maxHeight: contentSlotHeight,
                alignment: .topLeading
            )
        } else {
            VStack(alignment: .leading, spacing: 0) {
                content()
            }
        }
    }

    private var compactPanelLegacyBackground: some View {
        ZStack {
            RoundedRectangle(cornerRadius: panelCornerRadius, style: .continuous)
                .fill(AppTheme.inlineFill.opacity(0.58))
            RoundedRectangle(cornerRadius: panelCornerRadius, style: .continuous)
                .stroke(AppTheme.inlineStroke.opacity(0.08), lineWidth: 1.0)
        }
    }
}

struct GenerationSetupRow<Content: View, Supporting: View>: View {
    let label: String
    var rowVerticalPadding: CGFloat = 4
    var horizontalSpacing: CGFloat = 10
    var stackedSpacing: CGFloat = 5
    var supportingSpacing: CGFloat = 4
    var accessibilityIdentifier: String? = nil
    @ViewBuilder let content: () -> Content
    @ViewBuilder let supporting: () -> Supporting

    init(
        label: String,
        rowVerticalPadding: CGFloat = 4,
        horizontalSpacing: CGFloat = 10,
        stackedSpacing: CGFloat = 5,
        supportingSpacing: CGFloat = 4,
        accessibilityIdentifier: String? = nil,
        @ViewBuilder content: @escaping () -> Content,
        @ViewBuilder supporting: @escaping () -> Supporting
    ) {
        self.label = label
        self.rowVerticalPadding = rowVerticalPadding
        self.horizontalSpacing = horizontalSpacing
        self.stackedSpacing = stackedSpacing
        self.supportingSpacing = supportingSpacing
        self.accessibilityIdentifier = accessibilityIdentifier
        self.content = content
        self.supporting = supporting
    }

    /// W1-F: one deterministic width signal decides side-by-side vs stacked,
    /// and `AnyLayout` preserves child identity across the flip. The previous
    /// `ViewThatFits` built the content twice per pass and REMOUNTED it on
    /// breakpoint changes — text fields inside (Clone transcript, Design
    /// brief) lost first-responder mid-typing when a window resize crossed
    /// the threshold. Width 0 (pre-first-layout) renders side-by-side, which
    /// matches every default-window row.
    @State private var availableWidth: CGFloat = 0

    private var usesSideBySideLayout: Bool {
        availableWidth == 0
            || availableWidth >= LayoutConstants.configurationLabelWidth
                + horizontalSpacing
                + LayoutConstants.configurationControlMinWidth
                + 40
    }

    private var rowLayout: AnyLayout {
        usesSideBySideLayout
            ? AnyLayout(HStackLayout(alignment: .center, spacing: horizontalSpacing))
            : AnyLayout(VStackLayout(alignment: .leading, spacing: stackedSpacing))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: supportingSpacing) {
            rowLayout {
                labelView
                    .frame(
                        width: usesSideBySideLayout
                            ? LayoutConstants.configurationLabelWidth : nil,
                        alignment: .leading
                    )

                content()
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .onGeometryChange(for: CGFloat.self) { proxy in
                proxy.size.width
            } action: { width in
                availableWidth = width
            }

            supporting()
        }
        .padding(.vertical, rowVerticalPadding)
        .accessibilityElement(children: .contain)
        .optionalAccessibilityIdentifier(accessibilityIdentifier)
    }

    private var labelView: some View {
        Text(label)
            .font(.callout.weight(.semibold))
            .foregroundStyle(.primary)
    }
}

extension GenerationSetupRow where Supporting == EmptyView {
    init(
        label: String,
        rowVerticalPadding: CGFloat = 4,
        horizontalSpacing: CGFloat = 10,
        stackedSpacing: CGFloat = 5,
        supportingSpacing: CGFloat = 4,
        accessibilityIdentifier: String? = nil,
        @ViewBuilder content: @escaping () -> Content
    ) {
        self.init(
            label: label,
            rowVerticalPadding: rowVerticalPadding,
            horizontalSpacing: horizontalSpacing,
            stackedSpacing: stackedSpacing,
            supportingSpacing: supportingSpacing,
            accessibilityIdentifier: accessibilityIdentifier,
            content: content
        ) {
            EmptyView()
        }
    }
}

struct GenerationSetupHint: View {
    let message: String
    var accessibilityIdentifier: String? = nil

    var body: some View {
        Text(message)
            .font(.caption)
            .foregroundStyle(.secondary)
            .fixedSize(horizontal: false, vertical: true)
            .optionalAccessibilityIdentifier(accessibilityIdentifier)
    }
}

struct GenerationSetupNotice: View {
    let message: String
    var iconName: String = "info.circle"
    var accentColor: Color = AppTheme.accent
    var accessibilityIdentifier: String? = nil

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 6) {
            Image(systemName: iconName)
                .font(.caption.weight(.semibold))
                .foregroundStyle(accentColor)

            Text(message)
                .font(.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.vertical, 4)
        .accessibilityElement(children: .combine)
        .optionalAccessibilityIdentifier(accessibilityIdentifier)
    }
}

struct GenerationVariantSelector: View {
    let mode: GenerationMode
    var modelManager: ModelManagerViewModel
    var accentColor: Color = AppTheme.accent
    var accessibilityPrefix: String
    var isDisabled: Bool = false

    // W1-E: the segment used to be a hard 62x24 that clipped its caption
    // at larger system text sizes.
    @ScaledMetric(relativeTo: .caption) private var segmentWidth: CGFloat = 62
    @ScaledMetric(relativeTo: .caption) private var segmentHeight: CGFloat = 24

    private var selectedModel: TTSModel? {
        modelManager.generationActiveVariant(for: mode)
    }

    private var selectedKind: TTSModelVariantKind {
        selectedModel?.variantKind
            ?? modelManager.recommendedVariant(for: mode)?.variantKind
            ?? .speed
    }

    private var availableKinds: [TTSModelVariantKind] {
        let declaredKinds = Set(modelManager.variants(for: mode).compactMap(\.variantKind))
        return TTSModelVariantKind.allCases.filter { declaredKinds.contains($0) }
    }

    var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack(alignment: .center, spacing: 8) {
                variantLabel
                variantControl
                heavyBadge
            }

            VStack(alignment: .leading, spacing: 5) {
                variantLabel
                HStack(alignment: .center, spacing: 8) {
                    variantControl
                    heavyBadge
                }
            }
        }
        .fixedSize(horizontal: true, vertical: false)
        .help("Choose the Qwen3-TTS package for \(mode.displayName). Current status: \(statusCaption).")
    }

    // The memory-risk signal used to live only in this control's hover
    // tooltip (the visible "Heavy" badge existed only in Settings), so an
    // 8 GB user could switch to a risky package with no visible warning.
    // Icon + label pairing keeps the no-color-only rule.
    @ViewBuilder
    private var heavyBadge: some View {
        if let selectedModel,
           modelManager.isHardwareRisky(selectedModel),
           case .ready = modelManager.packagePresentation(for: selectedModel).kind {
            HStack(spacing: 4) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.caption2)
                Text("Heavy")
                    .font(.caption2.weight(.semibold))
            }
            .foregroundStyle(.orange)
            .help("This package is heavy for this Mac's memory. Generation may be slow or unstable under pressure.")
            .accessibilityElement(children: .combine)
            .accessibilityLabel("Heavy on this Mac")
            .accessibilityIdentifier("\(accessibilityPrefix)_heavyBadge")
        }
    }

    private var variantLabel: some View {
        Text("Model")
            .font(.caption.weight(.semibold))
            .foregroundStyle(.secondary)
    }

    private var variantControl: some View {
        HStack(spacing: 3) {
            ForEach(availableKinds, id: \.self) { kind in
                variantSegment(for: kind)
            }
        }
        // Match the rest of the app's pickers (EmotionPickerView,
        // VoiceCloningView transcript + source): keyboard focus shows the
        // mode-accent ring; the system blue ring stays suppressed inside
        // the modifier so the segment cannot render a stray selection halo
        // on first appearance under Full Keyboard Access.
        .vocelloFocusRing(accentColor, radius: 8)
        .padding(3)
        .background(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(AppTheme.inlineFill.opacity(0.72))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(AppTheme.inlineStroke.opacity(0.18), lineWidth: 1.0)
        )
    }

    private func variantSegment(for kind: TTSModelVariantKind) -> some View {
        let isSelected = selectedModel?.variantKind == kind
        let isSelectable = modelManager.isGenerationVariantSelectable(for: mode, kind: kind)
        let isEnabled = isSelectable && !isDisabled

        return Button {
            guard isSelectable,
                  let model = modelManager.variant(for: mode, kind: kind) else {
                return
            }
            modelManager.use(model)
        } label: {
            Text(kind.displayName)
                .font(.caption.weight(.semibold))
                .lineLimit(1)
                .frame(width: segmentWidth, height: segmentHeight)
                .foregroundStyle(segmentForeground(isSelected: isSelected, isSelectable: isSelectable))
                .background { segmentBackground(isSelected: isSelected) }
        }
        .buttonStyle(.plain)
        .disabled(!isEnabled)
        .opacity(isSelectable ? 1 : 0.42)
        .accessibilityLabel("\(kind.displayName), \(variantAccessibilityStatus(for: kind))")
        .accessibilityAddTraits(isSelected ? .isSelected : [])
        .accessibilityIdentifier("\(accessibilityPrefix)_\(kind.rawValue)VariantButton")
        .help(variantHelp(for: kind))
    }

    private func segmentForeground(isSelected: Bool, isSelectable: Bool) -> Color {
        if !isSelectable {
            return .secondary
        }
        return isSelected ? .primary : .secondary
    }

    @ViewBuilder
    private func segmentBackground(isSelected: Bool) -> some View {
        let radius: CGFloat = 8
        if isSelected {
            RoundedRectangle(cornerRadius: radius, style: .continuous)
                .fill(
                    LinearGradient(
                        colors: [
                            accentColor.opacity(0.20),
                            accentColor.opacity(0.12),
                        ],
                        startPoint: .top,
                        endPoint: .bottom
                    )
                )
                .overlay(
                    RoundedRectangle(cornerRadius: radius, style: .continuous)
                        .strokeBorder(accentColor.opacity(0.30), lineWidth: 1.0)
                )
        } else {
            RoundedRectangle(cornerRadius: radius, style: .continuous)
                .fill(Color.clear)
        }
    }

    private var statusCaption: String {
        guard let selectedModel else { return "No model" }
        var parts: [String] = []
        if let bitDepth = selectedModel.variantKind?.bitDepthLabel {
            parts.append(bitDepth)
        }
        if !selectedModel.supportsInstructionControl {
            parts.append("No delivery control")
        }
        if modelManager.isHardwareRisky(selectedModel),
           case .ready = modelManager.packagePresentation(for: selectedModel).kind {
            parts.append("Heavy on this Mac")
        } else {
            parts.append(modelManager.generationVariantStatusLabel(for: selectedModel))
        }
        return parts.joined(separator: " · ")
    }

    private func variantAccessibilityStatus(for kind: TTSModelVariantKind) -> String {
        guard let model = modelManager.variant(for: mode, kind: kind) else {
            return "unavailable"
        }
        let status = modelManager.generationVariantStatusLabel(for: model)
        switch modelManager.packagePresentation(for: model).kind {
        case .ready:
            return "\(kind.bitDepthLabel), ready"
        case .notInstalled:
            return "\(kind.bitDepthLabel), not installed"
        case .needsRepair:
            return "\(kind.bitDepthLabel), needs repair"
        case .updateAvailable:
            return "\(kind.bitDepthLabel), update available"
        case .checking, .downloading:
            return "\(kind.bitDepthLabel), \(status)"
        }
    }

    private func variantHelp(for kind: TTSModelVariantKind) -> String {
        guard modelManager.isGenerationVariantSelectable(for: mode, kind: kind) else {
            return "\(mode.displayName) \(kind.displayName) is not installed. Open Settings to manage model downloads."
        }
        guard let model = modelManager.variant(for: mode, kind: kind) else {
            return "\(mode.displayName) \(kind.displayName) is unavailable."
        }
        var details = "Use the \(kind.displayName) model for \(mode.displayName)."
        if !model.supportsInstructionControl {
            details += " Delivery controls are disabled for this Qwen3 family."
        }
        return details
    }

}

/// Caption-above-control column for the merged configuration line —
/// the same label idiom as the Delivery panel's "Custom tone" field
/// (footnote semibold, secondary; tertiary when the control is dimmed).
struct ConfigurationColumn<Content: View>: View {
    let label: String
    var isEnabled: Bool = true
    /// Optional quiet suffix after the caption (e.g. "· Auto" while the
    /// language selector follows detection) — tertiary so it reads as state,
    /// not as part of the label.
    var detail: String? = nil
    @ViewBuilder let content: () -> Content

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 4) {
                Text(label)
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(isEnabled ? AppTheme.textSecondary : AppTheme.textMuted)
                if let detail {
                    Text(detail)
                        .font(.footnote.weight(.medium))
                        .foregroundStyle(AppTheme.textMuted)
                }
            }

            content()
        }
    }
}

struct DeliveryControlsView: View {
    @Binding var emotion: String
    var deliveryProfile: Binding<DeliveryProfile?>? = nil
    var accentColor: Color = AppTheme.accent
    var accessibilityPrefix: String = "delivery"
    var isCompact: Bool = false
    var showsLabel: Bool = true
    var usesColumnLabels: Bool = false
    var leadingColumns: AnyView? = nil

    var body: some View {
        EmotionPickerView(
            emotion: $emotion,
            deliveryProfile: deliveryProfile,
            accentColor: accentColor,
            accessibilityPrefix: accessibilityPrefix,
            showsLabel: showsLabel,
            usesColumnLabels: usesColumnLabels,
            leadingColumns: leadingColumns
        )
        .optionalAccessibilityIdentifier(isCompact ? nil : "\(accessibilityPrefix)_toneCard")
    }
}

/// The bare Qwen language menu picker, shared by `QwenLanguagePickerRow`
/// (side-label form row) and the merged Language / Delivery / Intensity
/// configuration line (caption-above column).
struct QwenLanguagePicker: View {
    @Binding var selectedLanguage: Qwen3SupportedLanguage
    var accentColor: Color = AppTheme.accent
    var accessibilityPrefix: String = "qwenLanguage"
    var includesAuto = true
    /// Language detected from the typed prompt (`PromptLanguageDetector`).
    /// When confident (non-`.auto`): the closed control shows the plain
    /// effective name ("French" — the caption above carries the "· Auto"
    /// state, so the bar never widens), and the open menu tags the detected
    /// language "— Detected" in a "Recommended for your script" section.
    /// Picking the tagged row pins the language; picking Auto resumes
    /// following. A custom `Menu` (not `Picker`) because a native picker's
    /// button always mirrors the selected row's text — the compact button
    /// label needs to be independent of the row labels.
    var recommended: Qwen3SupportedLanguage? = nil
    var minWidth: CGFloat = LayoutConstants.configurationControlMinWidth
    var maxWidth: CGFloat = 220

    private var options: [Qwen3SupportedLanguage] {
        includesAuto ? Qwen3SupportedLanguage.allCases : Qwen3SupportedLanguage.selectableCases
    }

    private var recommendedOption: Qwen3SupportedLanguage? {
        guard let recommended, recommended != .auto, options.contains(recommended) else { return nil }
        return recommended
    }

    private var effectiveLabel: String {
        LanguageSelectionPresentation.buttonLabel(
            selected: selectedLanguage,
            detected: recommendedOption ?? .auto
        )
    }

    private var isFollowingDetection: Bool {
        LanguageSelectionPresentation.isFollowingDetection(
            selected: selectedLanguage,
            detected: recommendedOption ?? .auto
        )
    }

    /// One checkable menu row. macOS renders Menu `Toggle`s as native
    /// checkmarked items; the binding's setter only ever selects (menus
    /// dismiss on tap, so "unchecking" just re-selects the same language).
    private func languageRow(_ language: Qwen3SupportedLanguage, title: String? = nil) -> some View {
        Toggle(
            title ?? language.displayName,
            isOn: Binding(
                get: { selectedLanguage == language },
                set: { _ in selectedLanguage = language }
            )
        )
    }

    var body: some View {
        Menu {
            if let recommendedOption {
                Section("Recommended for your script") {
                    languageRow(recommendedOption, title: "\(recommendedOption.displayName) — Detected")
                }
                Section("All languages") {
                    ForEach(options.filter { $0 != recommendedOption }, id: \.self) { language in
                        languageRow(language)
                    }
                }
            } else {
                ForEach(options, id: \.self) { language in
                    languageRow(language)
                }
            }
        } label: {
            // A single concatenated Text so the bordered button style cannot
            // decompose the label and move the chevron to the leading edge
            // (it reorders HStack{Text, Image} labels); per-segment color
            // keeps the chevron quiet like the native picker's.
            (Text(effectiveLabel)
                + Text("  ")
                + Text(Image(systemName: "chevron.up.chevron.down"))
                    .font(.caption2.weight(.semibold))
                    .foregroundColor(.secondary))
                .lineLimit(1)
                .padding(.horizontal, 3)
                .padding(.vertical, 1)
        }
        .menuStyle(.button)
        .buttonStyle(.bordered)
        .menuIndicator(.hidden)
        .vocelloFocusRing(accentColor, radius: 6)
        .frame(minWidth: minWidth, maxWidth: maxWidth, alignment: .leading)
        .tint(accentColor)
        .accessibilityValue(isFollowingDetection ? "\(effectiveLabel), auto" : effectiveLabel)
        .accessibilityIdentifier("\(accessibilityPrefix)_languagePicker")
    }
}

struct QwenLanguagePickerRow: View {
    @Binding var selectedLanguage: Qwen3SupportedLanguage
    var accentColor: Color = AppTheme.accent
    var accessibilityPrefix: String = "qwenLanguage"
    var includesAuto = true
    var hint: String?
    var showsDefaultHelp = true
    var recommended: Qwen3SupportedLanguage? = nil

    var body: some View {
        GenerationSetupRow(
            label: "Language",
            accessibilityIdentifier: "\(accessibilityPrefix)_languageSetup"
        ) {
            QwenLanguagePicker(
                selectedLanguage: $selectedLanguage,
                accentColor: accentColor,
                accessibilityPrefix: accessibilityPrefix,
                includesAuto: includesAuto,
                recommended: recommended
            )
        } supporting: {
            if let hint, !hint.isEmpty {
                GenerationSetupHint(
                    message: hint,
                    accessibilityIdentifier: "\(accessibilityPrefix)_languageHint"
                )
            } else if showsDefaultHelp {
                GenerationSetupHint(
                    message: "Choose Auto or one of Qwen3-TTS's supported languages.",
                    accessibilityIdentifier: "\(accessibilityPrefix)_languageHelp"
                )
            }
        }
    }
}
