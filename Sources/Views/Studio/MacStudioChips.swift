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
            VStack(alignment: .leading, spacing: MacTheme.Spacing.tight) {
                TextField(MacInterfaceText.emotionCustomTonePlaceholder, text: $selection.customText)
                    .textFieldStyle(.plain)
                    .macType(.body)
                    .foregroundStyle(MacTheme.Text.primary)
                    .vocelloFocusRing(tint, radius: MacTheme.Radius.input)
                    .padding(.horizontal, MacTheme.Spacing.md)
                    .padding(.vertical, MacTheme.Spacing.sm)
                    .background {
                        VocelloShape.input()
                            .fill(MacTheme.Surface.field)
                    }
                    .overlay {
                        VocelloShape.input()
                            .stroke(MacTheme.Surface.fieldStroke, lineWidth: VocelloTheme.Stroke.hairline)
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
                        .macType(.caption)
                        .foregroundStyle(MacTheme.Status.guarded)
                        .accessibilityIdentifier("\(accessibilityPrefix)_durationAdvisory")
                }
            }
        } else if selection.selectedPreset(for: emotion)?.isDirectionalHint == true {
            Label(EmotionPreset.directionalHintAdvisory, systemImage: "wand.and.sparkles")
                .macType(.caption)
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

/// The phone's chip row: every chip takes an equal share of the width, so the
/// row spans exactly the Generate button beneath it and no chip hugs its
/// label. Where the phone can rely on a plain `HStack` — three chips always
/// fit a phone — a Mac window can be narrowed until equal shares would be
/// unreadable, so the chips then wrap onto further rows instead of pushing the
/// column past the viewport (an `HStack` of pills never compresses, and the
/// pinned canvas would clip both edges of the composer and the chips).
struct MacChipFlow: Layout {
    var spacing: CGFloat = MacTheme.Spacing.sm
    var rowSpacing: CGFloat = MacTheme.Spacing.sm
    /// Narrowest a chip may become before the row breaks.
    var minimumChipWidth: CGFloat = MacStudioChipMetrics.minWidth

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        guard !subviews.isEmpty else { return .zero }
        let width = proposal.width.flatMap { $0.isFinite ? $0 : nil }
        let rowHeight = subviews.map { $0.sizeThatFits(.unspecified).height }.max() ?? 0
        guard let width else {
            // Unconstrained: report the ideal single row.
            let ideal = subviews.reduce(CGFloat(0)) { $0 + $1.sizeThatFits(.unspecified).width }
                + spacing * CGFloat(subviews.count - 1)
            return CGSize(width: ideal, height: rowHeight)
        }
        let rows = rowCount(for: subviews.count, width: width)
        return CGSize(
            width: width,
            height: rowHeight * CGFloat(rows) + rowSpacing * CGFloat(max(rows - 1, 0))
        )
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        guard !subviews.isEmpty else { return }
        let rowHeight = subviews.map { $0.sizeThatFits(.unspecified).height }.max() ?? 0
        let perRow = chipsPerRow(for: subviews.count, width: bounds.width)
        var index = 0
        var y = bounds.minY

        // Equal shares, like `.frame(maxWidth: .infinity)` inside the phone's
        // HStack. One share for every row, so a trailing row that holds fewer
        // chips lines up under the row above instead of stretching its last
        // chip across the whole width.
        let fullRowAvailable = bounds.width - spacing * CGFloat(perRow - 1)
        let share = (fullRowAvailable / CGFloat(perRow)).rounded(.down)

        while index < subviews.count {
            let count = min(perRow, subviews.count - index)
            let isFullRow = count == perRow
            var x = bounds.minX

            for offset in 0..<count {
                // The last chip of a full row absorbs the rounding remainder so
                // the row ends exactly on the container's trailing edge.
                let width = (isFullRow && offset == count - 1) ? bounds.maxX - x : share
                subviews[index + offset].place(
                    at: CGPoint(x: x, y: y),
                    anchor: .topLeading,
                    proposal: ProposedViewSize(width: width, height: rowHeight)
                )
                x += width + spacing
            }

            index += count
            y += rowHeight + rowSpacing
        }
    }

    private func chipsPerRow(for count: Int, width: CGFloat) -> Int {
        guard count > 0, width.isFinite, width > 0 else { return max(count, 1) }
        let fitting = Int(((width + spacing) / (minimumChipWidth + spacing)).rounded(.down))
        return max(1, min(count, fitting))
    }

    private func rowCount(for count: Int, width: CGFloat) -> Int {
        let perRow = chipsPerRow(for: count, width: width)
        return Int((Double(count) / Double(perRow)).rounded(.up))
    }
}
