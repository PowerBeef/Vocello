import QwenVoiceCore
import SwiftUI

struct EmotionPickerView: View {
    @Binding var emotion: String
    var deliveryProfile: Binding<DeliveryProfile?>? = nil
    var title: String = "Tone"
    var accentColor: Color = AppTheme.accent
    var accessibilityPrefix: String = "delivery"
    var showsLabel: Bool = true
    /// Column layout for the merged configuration line: the tone and
    /// intensity pickers each get a caption label above them
    /// (`ConfigurationColumn`), and `leadingColumns` (e.g. the Language
    /// column) joins the same row.
    var usesColumnLabels: Bool = false
    var leadingColumns: AnyView? = nil

    @State private var selectedPreset: EmotionPreset?
    /// Every selection ships the `strong` copy. DP-3 (2026-08-02) measured it at
    /// nearly double the recognisability of `normal` — mean per-preset recall
    /// 0.278 against 0.157, chance 0.053 — and the same run showed the two tiers
    /// are not separable from each other: for five presets the nearest cell in
    /// the whole space is its own other tier, and seven of nine moved *less* at
    /// strong than at normal, with dramatic reversing outright. A control that
    /// cannot be heard is not a control.
    @State private var intensity: EmotionIntensity = .strong
    @State private var isCustomMode = false
    @State private var customText = ""

    /// The intensity control was retired 2026-08-02. Both flags are the single
    /// place the layout asks, so restoring it is a one-line change if a future
    /// measurement earns it back.
    private var showsIntensityPicker: Bool { false }

    private var reservesIntensitySlot: Bool { false }

    private var isNeutralSelected: Bool {
        selectedPreset?.id == "neutral"
    }

    private var currentToneLabel: String {
        if isCustomMode {
            return "Custom"
        }

        guard let selectedPreset else {
            return DeliveryProfile.neutralInstruction
        }

        return selectedPreset.label
    }

    private var selectedOptionID: Binding<String> {
        Binding(
            get: {
                if isCustomMode {
                    return "custom"
                }
                return selectedPreset?.id ?? "neutral"
            },
            set: { newValue in
                if newValue == "custom" {
                    enterCustomMode()
                } else if let preset = EmotionPreset.all.first(where: { $0.id == newValue }) {
                    selectPreset(preset)
                }
            }
        )
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if showsLabel {
                LabeledContent(title) {
                    toneControlRow
                }
            } else {
                toneControlRow
            }

            if !isCustomMode, selectedPreset?.isDirectionalHint == true {
                Label(EmotionPreset.directionalHintAdvisory, systemImage: "wand.and.sparkles")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .accessibilityIdentifier("\(accessibilityPrefix)_hintAdvisory")
            }

            customToneField
        }
        .onAppear {
            syncSelectionFromText()
        }
    }

    private var tonePicker: some View {
        // The measured split (DP-12): distinct deliveries first, directional
        // hints second, so the menu itself tells the truth about what each
        // half can promise.
        Picker(title, selection: selectedOptionID) {
            Section("Distinct deliveries") {
                ForEach(EmotionPreset.all.filter { !$0.isDirectionalHint }) { preset in
                    Text(preset.label)
                        .tag(preset.id)
                }
            }

            Section("Directional hints") {
                ForEach(EmotionPreset.all.filter(\.isDirectionalHint)) { preset in
                    Text(preset.label)
                        .tag(preset.id)
                }
            }

            Section {
                Text("Custom")
                    .tag("custom")
            }
        }
        .labelsHidden()
        .pickerStyle(.menu)
        .vocelloFocusRing(accentColor, radius: 6)
        .frame(
            minWidth: usesColumnLabels ? 110 : LayoutConstants.configurationControlMinWidth,
            maxWidth: 240,
            alignment: .leading
        )
        .accessibilityValue(emotion)
        .accessibilityIdentifier("\(accessibilityPrefix)_tonePicker")
    }

    @ViewBuilder
    private var toneControlRow: some View {
        if usesColumnLabels {
            columnToneRow
        } else {
            inlineToneRow
        }
    }

    private var inlineToneRow: some View {
        ViewThatFits(in: .horizontal) {
            HStack(alignment: .center, spacing: 12) {
                tonePicker

                if reservesIntensitySlot {
                    intensityInlineSlot
                }
            }

            VStack(alignment: .leading, spacing: 8) {
                tonePicker

                if reservesIntensitySlot {
                    intensityInlineSlot
                }
            }
        }
    }

    /// Merged configuration line: leading columns (e.g. Language) + Delivery
    /// + Intensity share one row, each with a caption label above its
    /// control. The stacked variant is a safety net for extreme cases
    /// (large accessibility type) — the single line fits at every legal
    /// window/sidebar combination.
    private var columnToneRow: some View {
        ViewThatFits(in: .horizontal) {
            HStack(alignment: .top, spacing: 12) {
                deliveryColumns
            }

            VStack(alignment: .leading, spacing: 8) {
                if let leadingColumns {
                    leadingColumns
                }

                HStack(alignment: .top, spacing: 12) {
                    ConfigurationColumn(label: "Delivery") { tonePicker }

                    if reservesIntensitySlot {
                        ConfigurationColumn(label: "Intensity", isEnabled: showsIntensityPicker) {
                            intensityPicker
                        }
                    }
                }
            }
        }
    }

    @ViewBuilder
    private var deliveryColumns: some View {
        if let leadingColumns {
            leadingColumns
        }

        ConfigurationColumn(label: "Delivery") { tonePicker }

        if reservesIntensitySlot {
            ConfigurationColumn(label: "Intensity", isEnabled: showsIntensityPicker) {
                intensityPicker
            }
        }
    }

    private var intensityInlineSlot: some View {
        HStack(alignment: .center, spacing: 10) {
            Text("Intensity")
                .font(.footnote.weight(.semibold))
                .foregroundStyle(showsIntensityPicker ? AppTheme.textSecondary : AppTheme.textMuted)

            intensityPicker
        }
    }

    private var intensityPicker: some View {
        Picker("Intensity", selection: $intensity) {
            ForEach(EmotionIntensity.allCases) { level in
                Text(level.label).tag(level)
            }
        }
        .labelsHidden()
        .pickerStyle(.menu)
        .vocelloFocusRing(accentColor, radius: 6)
        .frame(minWidth: 112, maxWidth: 152, alignment: .leading)
        .tint(showsIntensityPicker ? AppTheme.emotionColor(for: selectedPreset?.id ?? "neutral") : .secondary)
        .opacity(showsIntensityPicker ? 1 : 0.6)
        .disabled(!showsIntensityPicker)
        .appAnimation(AppTheme.Motion.standard, value: showsIntensityPicker)
        .accessibilityIdentifier("\(accessibilityPrefix)_intensityPicker")
        .onChange(of: intensity) { _, _ in
            if selectedPreset != nil {
                applyCurrentSelection()
            }
        }
    }

    private let customToneCharacterLimit = 500

    private var customToneField: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Custom tone")
                .font(.footnote.weight(.semibold))
                .foregroundStyle(isCustomMode ? AppTheme.textSecondary : AppTheme.textMuted)

            TextField("e.g. whispered, close-mic and breathy", text: $customText)
                .textFieldStyle(.plain)
                .vocelloFocusRing(accentColor, radius: 8)
                .padding(.horizontal, 8)
                .padding(.vertical, 6)
                .frame(minWidth: LayoutConstants.configurationControlMinWidth, maxWidth: .infinity, alignment: .leading)
                .glassTextField(radius: 8)
                .opacity(isCustomMode ? 1 : 0.6)
                .disabled(!isCustomMode)
                .accessibilityIdentifier("\(accessibilityPrefix)_toneField")
                .onChange(of: customText) { _, newValue in
                    if newValue.count > customToneCharacterLimit {
                        customText = String(newValue.prefix(customToneCharacterLimit))
                    }
                    if isCustomMode {
                        applyCurrentSelection()
                    }
                }

            if isCustomMode, DeliveryInstructionAdvisor.hasDurationDirective(customText) {
                Label(
                    DeliveryInstructionAdvisor.advisoryMessage,
                    systemImage: "exclamationmark.triangle"
                )
                .font(.caption2)
                .foregroundStyle(.orange)
                .accessibilityIdentifier("\(accessibilityPrefix)_durationAdvisory")
            }
        }
    }

    private func selectPreset(_ preset: EmotionPreset) {
        selectedPreset = preset
        // A new selection always ships the strong copy (DP-8). Without this
        // reset, a `.normal` tier synced from an older draft leaked into every
        // subsequent pick (2026-08-04 audit, F4).
        intensity = .strong
        isCustomMode = false
        customText = ""
        applyCurrentSelection()
    }

    private func enterCustomMode() {
        selectedPreset = nil
        isCustomMode = true
        applyCurrentSelection()
    }

    private func syncSelectionFromText() {
        let trimmedEmotion = emotion.trimmingCharacters(in: .whitespacesAndNewlines)

        // Strong-first resolution: identical tier strings (Neutral) must sync
        // as `.strong`. A legacy draft that stored a genuine `.normal` string
        // keeps resolving to exactly what it stored (same contract as iOS
        // `DeliveryInputState(legacyEmotion:)`); the `selectPreset` reset is
        // what guarantees every *new* pick ships strong.
        if let match = EmotionPreset.matchInstruction(trimmedEmotion) {
            selectedPreset = match.preset
            intensity = match.intensity
            isCustomMode = false
            customText = ""
            applyCurrentSelection()
            return
        }

        if !DeliveryProfile.isNeutralInstruction(trimmedEmotion) {
            isCustomMode = true
            customText = trimmedEmotion
            selectedPreset = nil
            applyCurrentSelection()
        } else {
            selectedPreset = EmotionPreset.all.first
            isCustomMode = false
            customText = ""
            intensity = .strong
            applyCurrentSelection()
        }
    }

    private func applyCurrentSelection() {
        let profile: DeliveryProfile

        if isCustomMode {
            profile = .custom(customText)
        } else if let selectedPreset {
            profile = .preset(selectedPreset, intensity: intensity)
        } else {
            profile = .neutral
        }

        emotion = profile.finalInstruction
        deliveryProfile?.wrappedValue = profile
    }
}
