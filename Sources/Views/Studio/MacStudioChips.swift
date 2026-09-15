import QwenVoiceCore
import SwiftUI

/// The chips every Studio mode shares: the delivery preset menu with its
/// Custom tone field and hint advisory, and the language menu with its
/// Recommended section. The screens keep the draft; these views own only
/// the menu presentation and the mutations that keep the stored instruction,
/// the delivery profile and the chip in step.

/// Which half of the delivery control is active: a preset (derived from the
/// stored instruction) or the Custom tone field with its own text, so an
/// empty custom field stays neutral in the request.
struct MacDeliverySelection: Equatable {
    var isCustom = false
    var customText = ""

    /// Derives the selection from a stored instruction on appearance.
    static func synced(from emotion: String) -> MacDeliverySelection {
        let trimmed = emotion.trimmingCharacters(in: .whitespacesAndNewlines)
        if EmotionPreset.matchInstruction(trimmed) != nil || DeliveryProfile.isNeutralInstruction(trimmed) {
            return MacDeliverySelection()
        }
        return MacDeliverySelection(isCustom: true, customText: trimmed)
    }

    func selectedPreset(for emotion: String) -> EmotionPreset? {
        guard !isCustom else { return nil }
        let trimmed = emotion.trimmingCharacters(in: .whitespacesAndNewlines)
        return EmotionPreset.matchInstruction(trimmed)?.preset
            ?? (DeliveryProfile.isNeutralInstruction(trimmed) ? EmotionPreset.all.first : nil)
    }

    func chipValue(for emotion: String) -> String {
        if isCustom {
            let trimmed = customText.trimmingCharacters(in: .whitespacesAndNewlines)
            return trimmed.isEmpty ? MacInterfaceText.emotionCustom : trimmed
        }
        return selectedPreset(for: emotion)?.label ?? emotion
    }
}

enum MacDeliveryMutations {
    /// A new selection always ships the preset's shipped tier (the DP-8 strong
    /// anchor; happy/angry ship normal, DP-22 branch (a)).
    @MainActor
    static func select(
        _ preset: EmotionPreset,
        selection: Binding<MacDeliverySelection>,
        emotion: Binding<String>,
        deliveryProfile: Binding<DeliveryProfile?>?
    ) {
        selection.wrappedValue = MacDeliverySelection()
        let profile = DeliveryProfile.preset(preset, intensity: preset.shippedIntensity)
        emotion.wrappedValue = profile.finalInstruction
        deliveryProfile?.wrappedValue = profile
    }

    @MainActor
    static func applyCustom(
        selection: Binding<MacDeliverySelection>,
        emotion: Binding<String>,
        deliveryProfile: Binding<DeliveryProfile?>?
    ) {
        let profile = DeliveryProfile.custom(selection.wrappedValue.customText)
        emotion.wrappedValue = profile.finalInstruction
        deliveryProfile?.wrappedValue = profile
    }
}

/// Delivery preset menu on the chip (`delivery_tonePicker`): distinct
/// deliveries first, directional hints second (the measured DP-12 split),
/// then Custom.
struct MacStudioDeliveryChip: View {
    @Binding var selection: MacDeliverySelection
    @Binding var emotion: String
    var deliveryProfile: Binding<DeliveryProfile?>? = nil
    let tint: Color
    var accessibilityIdentifier = "delivery_tonePicker"

    private var selectedPreset: EmotionPreset? { selection.selectedPreset(for: emotion) }

    var body: some View {
        MacStudioSetupChip(
            eyebrow: MacInterfaceText.delivery,
            value: selection.chipValue(for: emotion),
            leadingSymbol: "theatermasks.fill",
            tint: MacTheme.emotionColor(for: selectedPreset?.id, fallback: tint),
            accessibilityIdentifier: accessibilityIdentifier,
            accessibilityValue: emotion
        ) {
            Section(MacInterfaceText.emotionDistinctDeliveries) {
                ForEach(EmotionPreset.all.filter { !$0.isDirectionalHint }) { preset in
                    presetRow(preset)
                }
            }
            Section(MacInterfaceText.emotionDirectionalHints) {
                ForEach(EmotionPreset.all.filter(\.isDirectionalHint)) { preset in
                    presetRow(preset)
                }
            }
            Section {
                Toggle(
                    MacInterfaceText.emotionCustom,
                    isOn: Binding(
                        get: { selection.isCustom },
                        set: { _ in
                            selection.isCustom = true
                            MacDeliveryMutations.applyCustom(
                                selection: $selection, emotion: $emotion, deliveryProfile: deliveryProfile
                            )
                        }
                    )
                )
            }
        }
    }

    /// One checkable menu row; macOS renders Menu `Toggle`s as checkmarked
    /// items and the setter only ever selects.
    private func presetRow(_ preset: EmotionPreset) -> some View {
        Toggle(
            preset.label,
            isOn: Binding(
                get: { !selection.isCustom && selectedPreset?.id == preset.id },
                set: { _ in
                    MacDeliveryMutations.select(
                        preset, selection: $selection, emotion: $emotion, deliveryProfile: deliveryProfile
                    )
                }
            )
        )
    }
}

/// Rows under the chips for the delivery control: the Custom tone field with
/// its duration advisory, or the directional-hint advisory.
struct MacStudioDeliveryFooter: View {
    @Binding var selection: MacDeliverySelection
    @Binding var emotion: String
    var deliveryProfile: Binding<DeliveryProfile?>? = nil
    let tint: Color
    var accessibilityPrefix = "delivery"

    private let customToneCharacterLimit = GenerationTextLimitPolicy.deliveryInstructionLimit

    var body: some View {
        if selection.isCustom {
            VStack(alignment: .leading, spacing: 6) {
                TextField(MacInterfaceText.emotionCustomTonePlaceholder, text: $selection.customText)
                    .textFieldStyle(.plain)
                    .font(.callout)
                    .foregroundStyle(MacTheme.Text.primary)
                    .vocelloFocusRing(tint, radius: 10)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
                    .background {
                        RoundedRectangle(cornerRadius: MacTheme.Radius.input, style: .continuous)
                            .fill(MacTheme.Surface.field)
                    }
                    .overlay {
                        RoundedRectangle(cornerRadius: MacTheme.Radius.input, style: .continuous)
                            .stroke(MacTheme.Surface.fieldStroke, lineWidth: 0.5)
                    }
                    .accessibilityLabel(MacInterfaceText.emotionCustomTone)
                    .accessibilityIdentifier("\(accessibilityPrefix)_toneField")
                    .onChange(of: selection.customText) { _, newValue in
                        if newValue.count > customToneCharacterLimit {
                            selection.customText = String(newValue.prefix(customToneCharacterLimit))
                        }
                        MacDeliveryMutations.applyCustom(
                            selection: $selection, emotion: $emotion, deliveryProfile: deliveryProfile
                        )
                    }

                if DeliveryInstructionAdvisor.hasDurationDirective(selection.customText) {
                    Label(DeliveryInstructionAdvisor.advisoryMessage, systemImage: "exclamationmark.triangle")
                        .font(.caption2)
                        .foregroundStyle(MacTheme.Status.guarded)
                        .accessibilityIdentifier("\(accessibilityPrefix)_durationAdvisory")
                }
            }
        } else if selection.selectedPreset(for: emotion)?.isDirectionalHint == true {
            Label(EmotionPreset.directionalHintAdvisory, systemImage: "wand.and.sparkles")
                .font(.caption2)
                .foregroundStyle(MacTheme.Text.secondary)
                .accessibilityIdentifier("\(accessibilityPrefix)_hintAdvisory")
        }
    }
}

/// Language menu on the chip (`<prefix>_languagePicker`): the detected
/// language in a Recommended section, Auto follows detection.
struct MacStudioLanguageChip: View {
    @Binding var selectedLanguage: Qwen3SupportedLanguage
    let detectedLanguage: Qwen3SupportedLanguage
    let tint: Color
    let accessibilityIdentifier: String

    private var isFollowingDetection: Bool {
        LanguageSelectionPresentation.isFollowingDetection(selected: selectedLanguage, detected: detectedLanguage)
    }

    var body: some View {
        let options = Qwen3SupportedLanguage.allCases
        let recommended: Qwen3SupportedLanguage? = detectedLanguage == .auto ? nil : detectedLanguage
        let label = LanguageSelectionPresentation.buttonLabel(selected: selectedLanguage, detected: detectedLanguage)
        MacStudioSetupChip(
            eyebrow: isFollowingDetection ? MacInterfaceText.languageAutoDetail : MacInterfaceText.sectionLanguage,
            value: label,
            leadingSymbol: "globe",
            tint: tint,
            accessibilityIdentifier: accessibilityIdentifier,
            accessibilityValue: isFollowingDetection ? "\(label), auto" : label
        ) {
            if let recommended {
                Section(MacInterfaceText.recommendedForScript) {
                    languageRow(recommended, title: MacInterfaceText.workflowDetectedLanguage(recommended.displayName))
                }
                Section(MacInterfaceText.workflowAllLanguages) {
                    ForEach(options.filter { $0 != recommended }, id: \.self) { language in
                        languageRow(language)
                    }
                }
            } else {
                ForEach(options, id: \.self) { language in
                    languageRow(language)
                }
            }
        }
    }

    private func languageRow(_ language: Qwen3SupportedLanguage, title: String? = nil) -> some View {
        Toggle(
            title ?? language.displayName,
            isOn: Binding(
                get: { selectedLanguage == language },
                set: { _ in selectedLanguage = language }
            )
        )
    }
}

/// The legacy container identifiers stay on a genuine parent of a chip, never
/// on the chip's own node, so the picker identifier keeps resolving.
struct MacStudioChipContainer<Chip: View>: View {
    let accessibilityIdentifier: String
    @ViewBuilder let chip: () -> Chip

    var body: some View {
        HStack(spacing: 0) {
            chip()
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier(accessibilityIdentifier)
    }
}

/// The desktop's Batch entry as a chip (`textInput_batchButton`).
struct MacStudioBatchChip: View {
    let tint: Color
    let isEnabled: Bool
    let action: () -> Void

    var body: some View {
        MacStudioActionChip(
            eyebrow: MacInterfaceText.studioChipBatch,
            value: MacInterfaceText.textInputBatch,
            leadingSymbol: "list.bullet.rectangle",
            tint: tint,
            isEnabled: isEnabled,
            accessibilityIdentifier: "textInput_batchButton",
            action: action
        )
        .frame(maxWidth: 160)
    }
}

/// Lays the setup chips out in rows: a chip that no longer fits the column
/// starts a new row instead of pushing the column past the viewport (an
/// `HStack` of pills never compresses, so on a 720 pt window it overflowed and
/// the pinned canvas clipped both edges of the composer and the chips).
struct MacChipFlow: Layout {
    var spacing: CGFloat = 8
    var rowSpacing: CGFloat = 8

    private struct Row {
        var indices: [Int] = []
        var width: CGFloat = 0
        var height: CGFloat = 0
    }

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width.flatMap { $0.isFinite ? $0 : nil }
        let rows = arrange(subviews, width: width ?? .infinity)
        let height = rows.map(\.height).reduce(0, +) + rowSpacing * CGFloat(max(rows.count - 1, 0))
        let widest = rows.map(\.width).max() ?? 0
        return CGSize(width: width ?? widest, height: height)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var y = bounds.minY
        for row in arrange(subviews, width: bounds.width) {
            var x = bounds.minX
            for index in row.indices {
                let size = subviews[index].sizeThatFits(.unspecified)
                subviews[index].place(
                    at: CGPoint(x: x, y: y + (row.height - size.height) / 2),
                    proposal: ProposedViewSize(size)
                )
                x += size.width + spacing
            }
            y += row.height + rowSpacing
        }
    }

    private func arrange(_ subviews: Subviews, width: CGFloat) -> [Row] {
        var rows: [Row] = []
        var current = Row()
        for index in subviews.indices {
            let size = subviews[index].sizeThatFits(.unspecified)
            let proposedWidth = current.indices.isEmpty ? size.width : current.width + spacing + size.width
            if !current.indices.isEmpty, proposedWidth > width {
                rows.append(current)
                current = Row()
            }
            current.indices.append(index)
            current.width = current.indices.count == 1 ? size.width : current.width + spacing + size.width
            current.height = max(current.height, size.height)
        }
        if !current.indices.isEmpty { rows.append(current) }
        return rows
    }
}
