import QwenVoiceCore
import SwiftUI

/// Speed / Quality package switch of a Studio mode (the desktop's own
/// feature: the iOS catalog carries the Speed packages only). Same
/// `<prefix>_speedVariantButton`, `<prefix>_qualityVariantButton` and
/// `<prefix>_heavyBadge` identifiers as the legacy control, in the shared
/// segmented chrome.
struct MacGenerationVariantSelector: View {
    @Environment(ModelManagerViewModel.self) private var modelManager

    let mode: GenerationMode
    let tint: Color
    let accessibilityPrefix: String
    var isDisabled = false
    /// The window toolbar has little room and its position already says what
    /// the control is, so the caption is dropped there.
    var showsLabel = true

    private var selectedModel: TTSModel? {
        modelManager.generationActiveVariant(for: mode)
    }

    private var availableKinds: [TTSModelVariantKind] {
        let declaredKinds = Set(modelManager.variants(for: mode).compactMap(\.variantKind))
        return TTSModelVariantKind.allCases.filter { declaredKinds.contains($0) }
    }

    var body: some View {
        HStack(alignment: .center, spacing: MacTheme.Spacing.sm) {
            if showsLabel {
                Text(MacInterfaceText.workflowModel)
                    .macType(.captionEmphasis)
                    .foregroundStyle(MacTheme.Text.secondary)
            }
            variantControl
            heavyBadge
        }
        .fixedSize(horizontal: true, vertical: false)
        .help(MacInterfaceText.workflowPackageHelp(MacInterfaceText.modeName(mode), statusCaption))
    }

    /// Icon + label pairing keeps the no-color-only rule: an 8 GB user sees
    /// the memory-risk signal beside the switch, not only in Settings.
    @ViewBuilder
    private var heavyBadge: some View {
        if let selectedModel,
           modelManager.isHardwareRisky(selectedModel),
           case .ready = modelManager.packagePresentation(for: selectedModel).kind {
            HStack(spacing: MacTheme.Spacing.xs) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .macType(.badge)
                Text(MacInterfaceText.settingsHeavy)
                    .macType(.badge)
                    .lineLimit(1)
            }
            .foregroundStyle(MacTheme.Status.guarded)
            .help(MacInterfaceText.workflowHeavyHelp)
            .accessibilityElement(children: .combine)
            .accessibilityLabel(MacInterfaceText.settingsHeavyOnThisMac)
            .accessibilityIdentifier("\(accessibilityPrefix)_heavyBadge")
        }
    }

    private var variantControl: some View {
        HStack(spacing: 3) {
            ForEach(availableKinds, id: \.self) { kind in
                variantSegment(for: kind)
            }
        }
        .vocelloFocusRing(tint, radius: MacTheme.Radius.chip)
        .padding(segmentInset)
        .background {
            VocelloShape.chip()
                .fill(Color.white.opacity(0.04))
        }
        .overlay {
            VocelloShape.chip()
                .stroke(Color.white.opacity(0.10), lineWidth: VocelloTheme.Stroke.hairline)
        }
    }

    /// How far the segments sit inside the track. The segment's corner radius
    /// is the track's less this, which is what keeps the two concentric.
    private let segmentInset: CGFloat = 3

    private func variantSegment(for kind: TTSModelVariantKind) -> some View {
        let isSelected = selectedModel?.variantKind == kind
        let isSelectable = modelManager.isGenerationVariantSelectable(for: mode, kind: kind)

        return Button {
            guard isSelectable, let model = modelManager.variant(for: mode, kind: kind) else { return }
            modelManager.use(model)
        } label: {
            Text(kind.displayName)
                .macType(.buttonLabel)
                .lineLimit(1)
                .padding(.horizontal, MacTheme.Spacing.snug)
                .frame(minWidth: 62, minHeight: MacControl.badge.height)
                .foregroundStyle(isSelected ? MacTheme.Text.primary : MacTheme.Text.secondary)
                .background {
                    if isSelected {
                        // Concentric with the track: the segment sits inside the
                        // control's 3 pt inset, so its corner is the track's
                        // radius less that inset. Equal radii read as two
                        // curves fighting each other.
                        VocelloShape.chip(inset: segmentInset)
                            .fill(
                                LinearGradient(
                                    colors: [tint.opacity(0.28), tint.opacity(0.14)],
                                    startPoint: .top,
                                    endPoint: .bottom
                                )
                            )
                            .overlay {
                                VocelloShape.chip(inset: segmentInset)
                                    .strokeBorder(tint.opacity(0.32), lineWidth: VocelloTheme.Stroke.standard)
                            }
                    }
                }
                .contentShape(VocelloShape.chip(inset: segmentInset))
        }
        .buttonStyle(.plain)
        .disabled(!(isSelectable && !isDisabled))
        .opacity(isSelectable ? 1 : VocelloTheme.Opacity.disabled)
        .accessibilityLabel(String("\(kind.displayName), \(variantAccessibilityStatus(for: kind))"))
        .accessibilityAddTraits(isSelected ? .isSelected : [])
        .accessibilityIdentifier("\(accessibilityPrefix)_\(kind.rawValue)VariantButton")
        .help(variantHelp(for: kind))
    }

    private var statusCaption: String {
        guard let selectedModel else { return MacInterfaceText.workflowNoModel }
        var parts: [String] = []
        if let bitDepth = selectedModel.variantKind?.bitDepthLabel {
            parts.append(bitDepth)
        }
        if !selectedModel.supportsInstructionControl {
            parts.append(MacInterfaceText.workflowNoDeliveryControl)
        }
        if modelManager.isHardwareRisky(selectedModel),
           case .ready = modelManager.packagePresentation(for: selectedModel).kind {
            parts.append(MacInterfaceText.workflowHeavyOnThisMac)
        } else {
            parts.append(modelManager.generationVariantStatusLabel(for: selectedModel))
        }
        return parts.joined(separator: " · ")
    }

    private func variantAccessibilityStatus(for kind: TTSModelVariantKind) -> String {
        guard let model = modelManager.variant(for: mode, kind: kind) else {
            return MacInterfaceText.workflowVariantUnavailable
        }
        let status = modelManager.generationVariantStatusLabel(for: model)
        switch modelManager.packagePresentation(for: model).kind {
        case .ready:
            return MacInterfaceText.workflowVariantReady(kind.bitDepthLabel)
        case .notInstalled:
            return MacInterfaceText.workflowVariantNotInstalled(kind.bitDepthLabel)
        case .needsRepair:
            return MacInterfaceText.workflowVariantNeedsRepair(kind.bitDepthLabel)
        case .updateAvailable:
            return MacInterfaceText.workflowVariantUpdateAvailable(kind.bitDepthLabel)
        case .checking, .downloading:
            return "\(kind.bitDepthLabel), \(status)"
        }
    }

    private func variantHelp(for kind: TTSModelVariantKind) -> String {
        guard modelManager.isGenerationVariantSelectable(for: mode, kind: kind) else {
            return MacInterfaceText.workflowVariantNotInstalledHelp(MacInterfaceText.modeName(mode), kind.displayName)
        }
        guard let model = modelManager.variant(for: mode, kind: kind) else {
            return MacInterfaceText.workflowVariantUnavailableHelp(MacInterfaceText.modeName(mode), kind.displayName)
        }
        var details = MacInterfaceText.workflowUseVariantHelp(kind.displayName, MacInterfaceText.modeName(mode))
        if !model.supportsInstructionControl {
            details += " " + MacInterfaceText.workflowDeliveryDisabledFamily
        }
        return details
    }
}
