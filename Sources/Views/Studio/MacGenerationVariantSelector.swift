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

    private var selectedModel: TTSModel? {
        modelManager.generationActiveVariant(for: mode)
    }

    private var availableKinds: [TTSModelVariantKind] {
        let declaredKinds = Set(modelManager.variants(for: mode).compactMap(\.variantKind))
        return TTSModelVariantKind.allCases.filter { declaredKinds.contains($0) }
    }

    var body: some View {
        HStack(alignment: .center, spacing: 8) {
            Text(MacInterfaceText.workflowModel)
                .font(.caption.weight(.semibold))
                .foregroundStyle(MacTheme.Text.secondary)
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
            HStack(spacing: 4) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.caption2)
                Text(MacInterfaceText.settingsHeavy)
                    .font(.caption2.weight(.semibold))
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
        .vocelloFocusRing(tint, radius: 8)
        .padding(3)
        .background {
            RoundedRectangle(cornerRadius: 9, style: .continuous)
                .fill(Color.white.opacity(0.04))
        }
        .overlay {
            RoundedRectangle(cornerRadius: 9, style: .continuous)
                .stroke(Color.white.opacity(0.10), lineWidth: 0.5)
        }
    }

    private func variantSegment(for kind: TTSModelVariantKind) -> some View {
        let isSelected = selectedModel?.variantKind == kind
        let isSelectable = modelManager.isGenerationVariantSelectable(for: mode, kind: kind)

        return Button {
            guard isSelectable, let model = modelManager.variant(for: mode, kind: kind) else { return }
            modelManager.use(model)
        } label: {
            Text(kind.displayName)
                .font(.caption.weight(.semibold))
                .lineLimit(1)
                .padding(.horizontal, 10)
                .frame(minWidth: 62, minHeight: 24)
                .foregroundStyle(isSelected ? MacTheme.Text.primary : MacTheme.Text.secondary)
                .background {
                    if isSelected {
                        RoundedRectangle(cornerRadius: 7, style: .continuous)
                            .fill(
                                LinearGradient(
                                    colors: [tint.opacity(0.28), tint.opacity(0.14)],
                                    startPoint: .top,
                                    endPoint: .bottom
                                )
                            )
                            .overlay {
                                RoundedRectangle(cornerRadius: 7, style: .continuous)
                                    .strokeBorder(tint.opacity(0.32), lineWidth: 1)
                            }
                    }
                }
                .contentShape(RoundedRectangle(cornerRadius: 7, style: .continuous))
        }
        .buttonStyle(.plain)
        .disabled(!(isSelectable && !isDisabled))
        .opacity(isSelectable ? 1 : 0.42)
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
