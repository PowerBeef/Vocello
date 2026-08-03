import SwiftUI
import QwenVoiceCore

// Bottom-sheet bundle from design_references/Vocello iOS/sheets.jsx. Each
// sheet wraps `IOSBottomSheet` (the shared chrome) and presents a focused
// picker / confirmation surface. Sheets are independent — call sites
// present them via `.sheet(isPresented:)` and bind the relevant state.

// MARK: - Emotion preset palette

/// Shared dot-color palette for `EmotionPreset`s, matching `tokens.css`
/// `--emotion-{name}`. Used by `IOSDeliveryPickerSheet` for per-cell
/// dots AND by the Studio's delivery setup chip so the chip's avatar
/// reflects the currently-selected preset's color identity.
enum IOSEmotionPresetPalette {
    static func dotColor(forID id: String?) -> Color {
        switch id {
        case "happy":     return Color(red: 0.95, green: 0.78, blue: 0.30)  // #F2C74D
        case "sad":       return Color(red: 0.55, green: 0.62, blue: 0.78)  // #8C9EC7
        case "angry":     return Color(red: 0.78, green: 0.32, blue: 0.20)  // #C75233
        case "fearful":   return Color(red: 0.62, green: 0.50, blue: 0.78)  // #9E80C7
        case "surprised": return Color(red: 0.38, green: 0.72, blue: 0.72)  // #61B8B8
        case "whisper":   return Color(red: 0.62, green: 0.62, blue: 0.66)  // #9E9EA8
        case "calm":      return Color(red: 0.62, green: 0.74, blue: 0.62)  // #9EBD9E
        default:          return .white.opacity(0.55)                       // neutral / unknown
        }
    }
}

// MARK: - Delivery picker

/// Preset grid (2 columns over `EmotionPreset.all`), plus an in-sheet custom-tone
/// editor surfaced by "Use a custom tone instead". Drives a
/// `DeliveryInputState`-shaped binding (selected preset id + custom text).
struct IOSDeliveryPickerSheet: View {
    @Binding var selectedPresetID: String
    @Binding var intensity: EmotionIntensity
    @Binding var customText: String
    let tint: Color
    /// Optional escape hatch: when set, a small "Use custom tone…" link sits
    /// below the intensity row. Tapping it switches the sheet to the custom-tone
    /// editor without closing the panel.
    var onUseCustomTone: (() -> Void)?
    var onDismiss: (() -> Void)?
    var presentation: IOSBottomSheetPresentationStyle = .system

    // Local source of truth for the sheet's own UI. This sheet is presented as a
    // stored `AnyView` via `appModel.presentBottomPanel`, and the host
    // (`RootView.bottomPanelOverlay`) only rebuilds that AnyView when RootView
    // itself re-renders — which it does NOT on a draft change (it observes
    // `bottomPanelItem`, not `customVoiceDraft`). So writing only through the
    // `@Binding`s left the open sheet frozen: the checkmark didn't move and the
    // Intensity row never appeared even though the model updated. Driving the UI
    // off local `@State` (and writing through to the bindings) keeps the sheet
    // reactive regardless of the host's observation path. Only the sheet's own
    // taps mutate the selection while it's open, so local state can't drift.
    @State private var localPresetID: String
    @State private var localIntensity: EmotionIntensity

    /// Tracks whether the sheet is currently showing the custom-tone editor.
    /// Toggling back to the preset grid is allowed via the editor's back button.
    @State private var isCustomToneEditorVisible = false

    @Environment(\.dismiss) private var dismiss

    init(
        selectedPresetID: Binding<String>,
        intensity: Binding<EmotionIntensity>,
        customText: Binding<String>,
        tint: Color,
        onUseCustomTone: (() -> Void)? = nil,
        onDismiss: (() -> Void)? = nil,
        presentation: IOSBottomSheetPresentationStyle = .system
    ) {
        self._selectedPresetID = selectedPresetID
        self._intensity = intensity
        self._customText = customText
        self.tint = tint
        self.onUseCustomTone = onUseCustomTone
        self.onDismiss = onDismiss
        self.presentation = presentation
        self._localPresetID = State(initialValue: selectedPresetID.wrappedValue)
        self._localIntensity = State(initialValue: intensity.wrappedValue)
    }

    private var columns: [GridItem] {
        // 2-column grid per design_references/Vocello iOS/sheets.jsx
        // DeliverySheet ("gridTemplateColumns: 'repeat(2, 1fr)'"). Each
        // cell is wide enough to carry name + description text.
        Array(repeating: GridItem(.flexible(), spacing: 10), count: 2)
    }

    private var intensityDisabled: Bool {
        localPresetID == "neutral"
    }

    var body: some View {
        IOSBottomSheetSurface(
            title: isCustomToneEditorVisible ? "Custom tone" : "Delivery",
            tint: tint,
            presentation: presentation,
            onDismiss: onDismiss,
            headerLeading: {
                if isCustomToneEditorVisible {
                    Button {
                        IOSAccessibleAnimation.perform(IOSDesignMotion.stateChange) {
                            isCustomToneEditorVisible = false
                        }
                    } label: {
                        Image(systemName: "chevron.left")
                            .font(.system(size: 18, weight: .semibold))
                            .foregroundStyle(IOSAppTheme.textPrimary)
                            .frame(width: 40, height: 40)
                            .background {
                                Circle()
                                    .fill(Color.white.opacity(0.06))
                            }
                            .overlay {
                                Circle()
                                    .stroke(Color.white.opacity(0.10), lineWidth: 0.5)
                            }
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("deliveryPickerSheet_customTone_back")
                }
            },
            headerTrailing: {
                Button {
                    closeSheet()
                } label: {
                    Text("Confirm")
                        .font(.system(size: 17, weight: .semibold))
                        .foregroundStyle(IOSAppTheme.textPrimary)
                        .padding(.horizontal, 18)
                        .frame(height: 40)
                        .background {
                            Capsule(style: .continuous)
                                .fill(tint.opacity(0.18))
                        }
                        .overlay {
                            Capsule(style: .continuous)
                                .stroke(tint.opacity(0.35), lineWidth: 0.8)
                        }
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("deliveryPicker_confirm")
            }
        ) {
            if isCustomToneEditorVisible {
                customToneEditorBody
            } else {
                presetPickerBody
            }
        }
    }

    private var presetPickerBody: some View {
        IOSScrollView(bottomFadeHeight: 0) {
            VStack(alignment: .leading, spacing: 18) {
                LazyVGrid(columns: columns, spacing: 12) {
                    ForEach(EmotionPreset.all) { preset in
                        cell(for: preset)
                    }
                }

                // Intensity row retired 2026-08-02. DP-3 measured `strong` at
                // nearly double the recognisability of `normal` and showed the
                // two tiers are not separable from each other, so every preset
                // now ships its strong copy and there is nothing to choose.
                // `intensityButton` and its identifiers are kept for the delivery
                // matrix harness and for restoring the row if that changes.

                if let onUseCustomTone {
                    Button {
                        onUseCustomTone()
                        IOSAccessibleAnimation.perform(IOSDesignMotion.stateChange) {
                            isCustomToneEditorVisible = true
                        }
                    } label: {
                        HStack(spacing: 8) {
                            Image(systemName: "slider.horizontal.3")
                                .font(.system(size: 13, weight: .semibold))
                            Text("Use a custom tone instead")
                                .font(.subheadline.weight(.medium))
                        }
                        .foregroundStyle(tint)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 12)
                        .background {
                            Capsule(style: .continuous)
                                .fill(IOSAppTheme.accentWash(tint).opacity(0.6))
                        }
                        .overlay {
                            Capsule(style: .continuous)
                                .stroke(tint.opacity(0.30), lineWidth: 0.9)
                        }
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("deliveryPickerSheet_customTone")
                }
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 24)
        }
    }

    private var customToneEditorBody: some View {
        IOSScrollView(bottomFadeHeight: 0) {
            VStack(alignment: .leading, spacing: 16) {
                composedInstructionEditor

                if DeliveryInstructionAdvisor.hasDurationDirective(customText) {
                    durationDirectiveAdvisory
                }

                customToneGuidance

                customToneExamples

                HStack {
                    Spacer(minLength: 0)
                    customToneCounter
                }
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 24)
        }
        .onChange(of: customText) { _, newValue in
            let limit = IOSGenerationTextLimitPolicy.deliveryInstructionLimit
            if newValue.count > limit {
                customText = String(newValue.prefix(limit))
            }
        }
        .onAppear {
            placeholderExampleIndex = Int.random(in: 0..<placeholderExamples.count)
        }
    }

    // MARK: - Custom tone guidance

    private let placeholderExamples: [String] = [
        "e.g. A calm narrator, warm and measured",
        "e.g. An energetic news anchor, bright and fast",
        "e.g. Whispered, close-mic and breathy",
        "e.g. Gentle, serious, and reassuring",
    ]

    @State private var placeholderExampleIndex = 0


    private var customToneGuidance: some View {
        Text("Be specific: combine emotion, pace, pitch, and timbre.")
            .font(.system(size: 13, weight: .regular))
            .foregroundStyle(IOSAppTheme.textSecondary)
            .fixedSize(horizontal: false, vertical: true)
    }

    private var durationDirectiveAdvisory: some View {
        HStack(alignment: .top, spacing: 6) {
            Image(systemName: "exclamationmark.triangle")
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(.orange)
            Text(DeliveryInstructionAdvisor.advisoryMessage)
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(IOSAppTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .accessibilityIdentifier("deliveryPickerSheet_customTone_durationAdvisory")
    }

    // MARK: - Composed instruction editor

    /// Compact editable field for the delivery instruction. Tapping it focuses
    /// the text view directly, so there is no separate disclosure or secondary
    /// editor. The field sits at the top of the sheet so the keyboard never
    /// covers it.
    private var composedInstructionEditor: some View {
        ZStack(alignment: .topLeading) {
            IOSDeliveryCustomTextEditor(
                text: $customText,
                tintColor: UIColor(tint)
            )

            if customText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                Text(placeholderExamples[placeholderExampleIndex])
                    .font(.system(size: 15, weight: .medium))
                    .foregroundStyle(IOSAppTheme.textTertiary)
                    .padding(.horizontal, 16)
                    .padding(.vertical, 14)
                    .allowsHitTesting(false)
            }
        }
        .frame(height: 120)
        .background {
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .fill(IOSAppTheme.accentWash(tint).opacity(0.22))
        }
        .overlay {
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .stroke(tint.opacity(0.32), lineWidth: 0.8)
        }
        // The inner UITextView already carries the accessibility identifier;
        // don't apply it to the wrapper to avoid a duplicate StaticText element
        // that shadows the real text view in UI tests.
    }

    private let customToneExamplesList: [String] = [
        "A calm narrator, warm and measured.",
        "An energetic news anchor, bright and fast.",
        "A whispered, close-mic and breathy tone.",
        "Gentle, serious, and reassuring.",
    ]

    private var customToneExamples: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Examples")
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(IOSAppTheme.textSecondary)

            VStack(alignment: .leading, spacing: 8) {
                ForEach(customToneExamplesList, id: \.self) { example in
                    HStack(alignment: .top, spacing: 6) {
                        Text("•")
                            .font(.system(size: 13, weight: .bold))
                            .foregroundStyle(tint)
                        Text(example)
                            .font(.system(size: 13, weight: .medium))
                            .foregroundStyle(IOSAppTheme.textSecondary)
                            .fixedSize(horizontal: false, vertical: true)
                        Spacer(minLength: 0)
                    }
                }
            }
            .padding(12)
            .background {
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .fill(IOSAppTheme.accentWash(tint).opacity(0.18))
            }
        }
        .accessibilityIdentifier("deliveryPickerSheet_customTone_examples")
    }

    private var customToneCounter: some View {
        let limit = IOSGenerationTextLimitPolicy.deliveryInstructionLimit
        let remaining = limit - customText.count
        return Text("\(customText.count)/\(limit)")
            .font(.system(size: 12, weight: .medium).monospacedDigit())
            .foregroundStyle(
                customText.count >= limit
                    ? tint
                    : remaining <= 50
                        ? .orange
                        : IOSAppTheme.textTertiary
            )
            .accessibilityIdentifier("deliveryPickerSheet_customTone_charCount")
    }

    private func closeSheet() {
        onDismiss?()
        dismiss()
    }

    /// Multi-line custom-tone editor backed by a `UITextView` with
    /// scroll-bounce disabled and focus-driven tint chrome. Mirrors
    /// `IOSBriefTextEditor` used by the Voice Design brief sheet.
    private struct IOSDeliveryCustomTextEditor: UIViewRepresentable {
        @Binding var text: String
        var tintColor: UIColor

        func makeUIView(context: Context) -> UITextView {
            let view = UITextView()
            view.delegate = context.coordinator
            view.accessibilityIdentifier = "deliveryPickerSheet_customTone_editor"
            view.backgroundColor = .clear
            view.font = .systemFont(ofSize: 16, weight: .medium)
            view.textColor = IOSAppTheme.textPrimaryUIColor
            view.tintColor = tintColor
            view.isScrollEnabled = true
            view.bounces = false
            view.alwaysBounceVertical = false
            view.showsVerticalScrollIndicator = true
            view.textContainerInset = UIEdgeInsets(top: 18, left: 16, bottom: 8, right: 16)
            view.textContainer.lineFragmentPadding = 0
            view.autocapitalizationType = .sentences
            view.autocorrectionType = .default
            view.smartQuotesType = .yes
            view.smartDashesType = .yes
            return view
        }

        func updateUIView(_ view: UITextView, context: Context) {
            if view.text != text { view.text = text }
            if view.tintColor != tintColor { view.tintColor = tintColor }
        }

        func makeCoordinator() -> Coordinator { Coordinator(self) }

        final class Coordinator: NSObject, UITextViewDelegate {
            var parent: IOSDeliveryCustomTextEditor
            init(_ parent: IOSDeliveryCustomTextEditor) { self.parent = parent }

            func textViewDidChange(_ textView: UITextView) {
                if parent.text != textView.text { parent.text = textView.text }
            }
        }
    }

    /// Two-line description per delivery preset, lifted from
    /// `design_references/Vocello iOS/data.js` `deliveries[]`. Hand-wired
    /// here instead of as a `description` field on `EmotionPreset` to
    /// keep the iOSSupport model layer untouched.
    private func description(for preset: EmotionPreset) -> String {
        switch preset.id {
        case "neutral":  return "Default, even pacing"
        case "happy":    return "Warm, bright, smiling"
        case "sad":      return "Quiet, slower, somber"
        case "angry":    return "Tense, sharp"
        case "fearful":  return "Quiet, hesitant"
        case "surprised":return "Animated, pitch jumps"
        case "whisper":  return "Soft, close-mic breath"
        case "calm":     return "Slower, reassuring"
        default:         return ""
        }
    }

    /// Mode-tinted dot color per preset. Delegates to the shared
    /// `IOSEmotionPresetPalette` so the Studio's delivery chip can pick
    /// up the same color identity.
    private func dotColor(for preset: EmotionPreset) -> Color {
        IOSEmotionPresetPalette.dotColor(forID: preset.id)
    }

    /// Per-preset 2-column delivery cell.
    /// Per `design_references/Vocello iOS/sheets.jsx` lines 124-147 +
    /// `app.css`: borderless rounded square, colored dot + name on the
    /// first line, small description text below.
    private func cell(for preset: EmotionPreset) -> some View {
        let isSelected = preset.id == localPresetID
        let dot = dotColor(for: preset)
        return Button {
            localPresetID = preset.id      // drive the sheet UI instantly
            selectedPresetID = preset.id   // write through to the draft (chip + generation)
            IOSHaptics.selection()
        } label: {
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 8) {
                    Circle()
                        .fill(dot)
                        .frame(width: 8, height: 8)
                    Text(preset.label)
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundStyle(IOSAppTheme.textPrimary)
                    Spacer(minLength: 0)
                    if isSelected {
                        Image(systemName: "checkmark")
                            .font(.system(size: 12, weight: .bold))
                            .foregroundStyle(dot)
                    }
                }

                Text(description(for: preset))
                    .font(.system(size: 12, weight: .regular))
                    .foregroundStyle(IOSAppTheme.textSecondary)
                    .multilineTextAlignment(.leading)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 12)
            .frame(maxWidth: .infinity, minHeight: 64, alignment: .topLeading)
            .background {
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .fill(
                        isSelected
                            ? dot.opacity(0.14)
                            : Color.white.opacity(0.03)
                    )
            }
            .overlay {
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .stroke(
                        isSelected ? dot.opacity(0.60) : Color.white.opacity(0.10),
                        lineWidth: 0.5
                    )
            }
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("deliveryPickerPreset_\(preset.id)")
        .accessibilityAddTraits(isSelected ? .isSelected : [])
    }

    private func intensityButton(_ level: EmotionIntensity) -> some View {
        let isSelected = level == localIntensity
        return Button {
            localIntensity = level   // drive the sheet UI instantly
            intensity = level        // write through to the draft
            IOSHaptics.selection()
        } label: {
            Text(level.label)
                .font(.subheadline.weight(.medium))
                .foregroundStyle(isSelected ? IOSAppTheme.textPrimary : IOSAppTheme.textSecondary)
                .frame(maxWidth: .infinity)
                .frame(height: 36)
                .background {
                    Capsule(style: .continuous)
                        .fill(isSelected ? IOSAppTheme.accentWash(tint) : IOSAppTheme.glassSurfaceFillMuted.opacity(0.55))
                }
                .overlay {
                    Capsule(style: .continuous)
                        .stroke(isSelected ? tint.opacity(0.32) : Color.white.opacity(0.10), lineWidth: 0.8)
                }
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("deliveryPickerIntensity_\(level)")
    }
}

// MARK: - Qwen language picker

struct IOSQwenLanguagePickerSheet: View {
    @Binding var selectedLanguage: Qwen3SupportedLanguage
    let tint: Color
    var includesAuto = true
    /// Detected prompt language to float to the top + badge as recommended (`nil`/`.auto` = none).
    var recommended: Qwen3SupportedLanguage? = nil
    var onDismiss: (() -> Void)?
    var presentation: IOSBottomSheetPresentationStyle = .system

    @Environment(\.dismiss) private var dismiss

    private var languages: [Qwen3SupportedLanguage] {
        includesAuto ? Qwen3SupportedLanguage.allCases : Qwen3SupportedLanguage.selectableCases
    }

    private func isRecommended(_ language: Qwen3SupportedLanguage) -> Bool {
        guard let recommended, recommended != .auto else { return false }
        return language == recommended
    }

    var body: some View {
        IOSBottomSheetSurface(
            title: "Language",
            tint: tint,
            presentation: presentation,
            onDismiss: onDismiss,
            headerTrailing: {
                Button {
                    closeSheet()
                } label: {
                    Text("Confirm")
                        .font(.system(size: 17, weight: .semibold))
                        .foregroundStyle(IOSAppTheme.textPrimary)
                        .padding(.horizontal, 18)
                        .frame(height: 40)
                        .background {
                            Capsule(style: .continuous)
                                .fill(tint.opacity(0.18))
                        }
                        .overlay {
                            Capsule(style: .continuous)
                                .stroke(tint.opacity(0.35), lineWidth: 0.8)
                        }
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("languagePicker_confirm")
            }
        ) {
            // Sheet floats above the dock — no bottom fade needed.
            IOSScrollView(bottomFadeHeight: 0) {
                LazyVStack(alignment: .leading, spacing: 4) {
                    let recommendedLanguages = languages.filter(isRecommended)
                    let others = languages.filter { !isRecommended($0) }
                    if !recommendedLanguages.isEmpty {
                        sectionHeader("Recommended")
                        ForEach(recommendedLanguages, id: \.self) { languageButton($0) }
                        sectionHeader("All languages")
                    }
                    ForEach(others, id: \.self) { languageButton($0) }
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 24)
            }
        }
    }

    private func sectionHeader(_ title: String) -> some View {
        Text(title.uppercased())
            .font(.system(size: 10, weight: .semibold))
            .tracking(0.7)
            .foregroundStyle(IOSAppTheme.textTertiary)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.top, 8)
            .padding(.bottom, 2)
    }

    /// Leading badge mirroring the voice picker's avatar: a tinted circle with the language's
    /// 2-letter code (globe for Auto).
    @ViewBuilder
    private func leadingBadge(_ language: Qwen3SupportedLanguage) -> some View {
        ZStack {
            Circle().fill(tint.opacity(0.18))
            if language == .auto {
                Image(systemName: "globe")
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(tint)
            } else {
                Text(IOSVoicePickerLanguage.tag(for: language.displayName) ?? "")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(tint)
            }
        }
        .frame(width: 44, height: 44)
    }

    private func languageButton(_ language: Qwen3SupportedLanguage) -> some View {
        let isSelected = selectedLanguage == language
        return Button {
            selectedLanguage = language
            IOSHaptics.selection()
        } label: {
            HStack(alignment: .center, spacing: 12) {
                leadingBadge(language)

                VStack(alignment: .leading, spacing: 1) {
                    // While a language is detected, the Auto row reads
                    // "French (Auto)" — Auto keeps meaning "follow detection".
                    // (The Studio chip stays compact with just the effective
                    // name; this full-width row has the room to spell out the
                    // state.) The detected row itself is tagged via its
                    // subtitle.
                    Text(autoRowTitle(language))
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(IOSAppTheme.textPrimary)
                    Text(rowSubtitle(language))
                        .font(.caption)
                        .foregroundStyle(IOSAppTheme.textSecondary)
                        .lineLimit(1)
                }

                Spacer(minLength: 8)

                // Recommendation is conveyed by the "Recommended" section header + top placement
                // (no per-row badge — it duplicated the header and truncated on narrow rows).

                // Always reserve the checkmark slot (invisible when unselected) so rows stay aligned.
                Image(systemName: "checkmark")
                    .font(.system(size: 14, weight: .bold))
                    .foregroundStyle(tint)
                    .opacity(isSelected ? 1 : 0)
                    .frame(width: 18)
                    .accessibilityHidden(true)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 10)
            .contentShape(Rectangle())
            .background {
                RoundedRectangle(cornerRadius: IOSCornerRadius.card, style: .continuous)
                    .fill(isSelected ? IOSAppTheme.accentWash(tint) : Color.clear)
            }
            .overlay(alignment: .bottom) {
                Rectangle()
                    .fill(Color.white.opacity(0.06))
                    .frame(height: 0.5)
            }
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("languagePicker_\(language.rawValue)")
    }

    private func autoRowTitle(_ language: Qwen3SupportedLanguage) -> String {
        guard language == .auto, let recommended, recommended != .auto else {
            return language.displayName
        }
        return "\(recommended.displayName) (Auto)"
    }

    private func rowSubtitle(_ language: Qwen3SupportedLanguage) -> String {
        if language == .auto {
            return "Infer from script or transcript."
        }
        if isRecommended(language) {
            return "Detected from your text."
        }
        return "Use Qwen3's \(language.displayName) path."
    }

    private func closeSheet() {
        onDismiss?()
        dismiss()
    }
}

// MARK: - Voice picker

/// Speaker picker for Custom mode. Caller passes the available speaker
/// catalog (id + display name + optional language tag) and a selection
/// binding. Optional recent-voices carousel sits above the alphabetical
/// list.
struct IOSVoicePickerSheet: View {
    let speakers: [IOSVoicePickerOption]
    @Binding var selectedID: String
    let tint: Color
    var onDismiss: (() -> Void)?
    var presentation: IOSBottomSheetPresentationStyle = .system

    @Environment(\.dismiss) private var dismiss
    @State private var search: String = ""
    @StateObject private var previewer = IOSVoicePreviewPlayer()
    /// Local provisional selection. The binding is only committed when the
    /// user taps the Confirm header button.
    @State private var pendingSelectedID: String
    /// R3-FU G.2.1 (2026-05-21): selected language tag, or
    /// `IOSVoicePickerSheet.allFilterID` for "show everything". Matches
    /// the design's filter-chip behaviour where the first chip ("All")
    /// is a sentinel value and the rest are concrete language tags.
    @State private var selectedFilter: String = IOSVoicePickerSheet.allFilterID

    init(
        speakers: [IOSVoicePickerOption],
        selectedID: Binding<String>,
        tint: Color,
        onDismiss: (() -> Void)? = nil,
        presentation: IOSBottomSheetPresentationStyle = .system
    ) {
        self.speakers = speakers
        self._selectedID = selectedID
        self.tint = tint
        self.onDismiss = onDismiss
        self.presentation = presentation
        self._pendingSelectedID = State(initialValue: selectedID.wrappedValue)
    }

    /// Sentinel id for the "All" chip. Real language tags are short
    /// uppercase strings ("EN", "ZH", …) so any non-matching marker
    /// works; using a leading "*" keeps it grep-friendly and impossible
    /// to collide with a future tag.
    private static let allFilterID = "*all"

    /// Distinct language tags present in the speakers list, sorted in
    /// stable order. Drives the filter chip row so the sheet
    /// self-extends when the contract gets a new language.
    private var distinctLanguageTags: [String] {
        var seen = Set<String>()
        var ordered: [String] = []
        for option in speakers {
            guard let tag = option.languageTag, !tag.isEmpty else { continue }
            if seen.insert(tag).inserted {
                ordered.append(tag)
            }
        }
        return ordered.sorted()
    }

    /// Filter chip row, including the leading "All" chip.
    private var availableFilters: [(id: String, label: String)] {
        var out: [(id: String, label: String)] = [(IOSVoicePickerSheet.allFilterID, "All")]
        for tag in distinctLanguageTags {
            out.append((tag, IOSVoicePickerSheet.label(for: tag)))
        }
        return out
    }

    private static func label(for tag: String) -> String {
        switch tag {
        case "EN":    return "English"
        case "EN-UK": return "British"
        case "ZH":    return "Chinese"
        case "JA":    return "Japanese"
        case "KO":    return "Korean"
        case "ES":    return "Spanish"
        case "FR":    return "French"
        case "DE":    return "German"
        case "IT":    return "Italian"
        case "PT":    return "Portuguese"
        default:      return tag    // unknown tag → render verbatim
        }
    }

    private var filtered: [IOSVoicePickerOption] {
        let q = search.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return speakers.filter { option in
            if selectedFilter != IOSVoicePickerSheet.allFilterID,
               option.languageTag != selectedFilter {
                return false
            }
            if !q.isEmpty {
                return option.name.lowercased().contains(q)
                    || (option.subtitle ?? "").lowercased().contains(q)
            }
            return true
        }
    }

    var body: some View {
        IOSBottomSheetSurface(
            title: "Voice",
            tint: tint,
            presentation: presentation,
            onDismiss: onDismiss,
            headerTrailing: {
                Button {
                    confirmSelection()
                } label: {
                    Text("Confirm")
                        .font(.system(size: 17, weight: .semibold))
                        .foregroundStyle(IOSAppTheme.textPrimary)
                        .padding(.horizontal, 18)
                        .frame(height: 40)
                        .background {
                            Capsule(style: .continuous)
                                .fill(tint.opacity(0.18))
                        }
                        .overlay {
                            Capsule(style: .continuous)
                                .stroke(tint.opacity(0.35), lineWidth: 0.8)
                        }
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("voicePicker_confirm")
            }
        ) {
            VStack(alignment: .leading, spacing: 14) {
                IOSSearchField(text: $search, placeholder: "Search voices")
                    .padding(.horizontal, 20)

                if availableFilters.count > 1 {
                    filterChipRow
                        .padding(.horizontal, 20)
                }

                IOSScrollView(bottomFadeHeight: 0) {
                    LazyVStack(alignment: .leading, spacing: 4) {
                        let recommended = filtered.filter(\.isRecommended)
                        let others = filtered.filter { !$0.isRecommended }
                        if !recommended.isEmpty {
                            sectionHeader("Recommended")
                            ForEach(recommended) { row(for: $0) }
                            if !others.isEmpty { sectionHeader("All voices") }
                        }
                        ForEach(others) { row(for: $0) }
                    }
                    .padding(.horizontal, 20)
                    .padding(.bottom, 24)
                }
            }
        }
        // Phase 3 (2026-05-21): stop any in-flight preview when the
        // sheet dismisses or a voice is selected. Without this the
        // preview audio would keep playing under the studio screen.
        .onDisappear {
            previewer.stop()
        }
        .onAppear {
            pendingSelectedID = selectedID
        }
        .onChange(of: selectedID) { _, newID in
            pendingSelectedID = newID
        }
    }

    /// Horizontal filter chip row matching `app.css .vc-filter-row` +
    /// `.vc-filter-chip` styling (32pt capsule pills, neutral inactive
    /// surface, white-elevated active surface).
    private var filterChipRow: some View {
        HStack(spacing: 8) {
            ForEach(availableFilters, id: \.id) { filter in
                IOSVoicePickerFilterChip(
                    label: filter.label,
                    isActive: selectedFilter == filter.id,
                    action: {
                        selectedFilter = filter.id
                        IOSHaptics.selection()
                    }
                )
            }
        }
    }

    private func sectionHeader(_ title: String) -> some View {
        Text(title.uppercased())
            .font(.system(size: 10, weight: .semibold))
            .tracking(0.7)
            .foregroundStyle(IOSAppTheme.textTertiary)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.top, 8)
            .padding(.bottom, 2)
    }

    private func row(for option: IOSVoicePickerOption) -> some View {
        let isSelected = option.id == pendingSelectedID
        let isPreviewing = previewer.currentlyPlayingID == option.id
        // Two SIBLING Buttons (select + preview) — never nested. Nesting a Button inside
        // another Button's label is a SwiftUI hit-testing trap that swallowed the row's
        // select tap; siblings each consume their own taps. The leading select Button
        // marks the provisional choice (the binding is committed by the Confirm header);
        // the trailing preview Button previews WITHOUT selecting/closing. Each carries a
        // stable accessibilityIdentifier so the UI loop can drive them independently.
        return HStack(alignment: .center, spacing: 12) {
            Button {
                previewer.stop()
                pendingSelectedID = option.id
                IOSHaptics.selection()
            } label: {
                HStack(alignment: .center, spacing: 12) {
                    IOSVoiceAvatar(seed: option.id, initials: option.initials, diameter: 44)

                    VStack(alignment: .leading, spacing: 1) {
                        Text(option.name)
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(IOSAppTheme.textPrimary)
                        if let subtitle = option.subtitle {
                            Text(subtitle)
                                .font(.caption)
                                .foregroundStyle(IOSAppTheme.textSecondary)
                                .lineLimit(1)
                        }
                    }

                    Spacer(minLength: 8)

                    // R3 G.2 (2026-05-21): per design_references/Vocello iOS/
                    // sheets.jsx VoicePickerSheet row, the trailing cluster
                    // carries a small uppercase language pill so users can
                    // tell English / British / Japanese voices apart at a
                    // glance. Nil tag hides the pill.
                    // Recommendation is conveyed by the "Recommended" section header + top
                    // placement; rows keep their language pill (no per-row "Recommended" badge).
                    if let tag = option.languageTag, !tag.isEmpty {
                        Text(tag.uppercased())
                            .font(.system(size: 10, weight: .semibold))
                            .tracking(0.4)
                            .foregroundStyle(IOSAppTheme.textSecondary)
                            .padding(.horizontal, 8)
                            .padding(.vertical, 4)
                            .background {
                                Capsule(style: .continuous)
                                    .fill(Color.white.opacity(0.08))
                            }
                    }
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("\(option.name)\(option.subtitle.map { ", \($0)" } ?? "")")
            .accessibilityAddTraits(isSelected ? [.isButton, .isSelected] : .isButton)
            .accessibilityIdentifier("voicePickerRow_\(option.id)")

            // Phase 3 G.2.3 (2026-05-21): per-row preview play button — a sibling Button,
            // so it previews without triggering the select Button beside it.
            Button {
                previewer.toggle(voiceID: option.id)
                IOSHaptics.selection()
            } label: {
                IOSPlayerIconButtonChrome(
                    symbol: isPreviewing ? "pause.fill" : "play.fill",
                    isActive: isPreviewing,
                    size: 40,
                    symbolSize: 16
                )
            }
            .buttonStyle(.plain)
            .accessibilityLabel(isPreviewing ? "Stop preview" : "Preview voice")
            .accessibilityIdentifier("voicePickerPreview_\(option.id)")

            // Always reserve the checkmark slot (invisible when unselected) so the play button +
            // badge/pill stay aligned across selected and unselected rows.
            Image(systemName: "checkmark")
                .font(.system(size: 14, weight: .bold))
                .foregroundStyle(tint)
                .opacity(isSelected ? 1 : 0)
                .frame(width: 18)
                .accessibilityHidden(true)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .background {
            RoundedRectangle(cornerRadius: IOSCornerRadius.card, style: .continuous)
                .fill(isSelected ? IOSAppTheme.accentWash(tint) : Color.clear)
        }
        .overlay(alignment: .bottom) {
            Rectangle()
                .fill(Color.white.opacity(0.06))
                .frame(height: 0.5)
        }
    }

    private func confirmSelection() {
        previewer.stop()
        selectedID = pendingSelectedID
        IOSHaptics.selection()
        closeSheet()
    }

    private func closeSheet() {
        onDismiss?()
        dismiss()
    }
}

/// Filter chip used inside the voice picker sheet's language row.
/// Mirrors `app.css .vc-filter-chip` styling: 32pt capsule, neutral
/// background when inactive, white-elevated background when active.
private struct IOSVoicePickerFilterChip: View {
    let label: String
    let isActive: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(label)
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(isActive ? IOSAppTheme.textPrimary : IOSAppTheme.textSecondary)
                .lineLimit(1)
                .padding(.horizontal, 12)
                .frame(height: 32)
                .frame(maxWidth: .infinity)
                .background {
                    Capsule(style: .continuous)
                        .fill(isActive ? Color.white.opacity(0.10) : Color.white.opacity(0.03))
                }
                .overlay {
                    Capsule(style: .continuous)
                        .stroke(
                            isActive ? Color.white.opacity(0.18) : Color.white.opacity(0.10),
                            lineWidth: 0.5
                        )
                }
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("voicePickerFilterChip_\(label)")
        .accessibilityAddTraits(isActive ? .isSelected : [])
    }
}

/// Maps the contract's `nativeLanguage` strings ("English", "Chinese", …)
/// to the short uppercase tags the picker pill renders. Adding a new
/// language to the contract should add a case here.
enum IOSVoicePickerLanguage {
    static func tag(for nativeLanguage: String?) -> String? {
        guard let nativeLanguage, !nativeLanguage.isEmpty else { return nil }
        switch nativeLanguage.lowercased() {
        case "english":       return "EN"
        case "british":       return "EN-UK"
        case "japanese":      return "JA"
        case "chinese":       return "ZH"
        case "korean":        return "KO"
        case "spanish":       return "ES"
        case "french":        return "FR"
        case "german":        return "DE"
        case "italian":       return "IT"
        case "portuguese":    return "PT"
        default:
            // Fall back: first 2 letters uppercased ("Hindi" → "HI").
            return String(nativeLanguage.prefix(2)).uppercased()
        }
    }
}

struct IOSVoicePickerOption: Identifiable, Equatable {
    let id: String
    let name: String
    let subtitle: String?
    /// Optional 2-3 character language tag rendered as a pill in the row's
    /// trailing cluster. Per `design_references/Vocello iOS/sheets.jsx`
    /// VoicePickerSheet row: `<span class="vc-pill">{v.lang}</span>`.
    /// Caller passes "EN" / "EN-UK" / "JA" / "ZH" / "Saved" etc. Nil hides
    /// the pill.
    let languageTag: String?
    /// Highlighted as recommended for the typed prompt's detected language.
    var isRecommended: Bool

    init(
        id: String,
        name: String,
        subtitle: String?,
        languageTag: String? = nil,
        isRecommended: Bool = false
    ) {
        self.id = id
        self.name = name
        self.subtitle = subtitle
        self.languageTag = languageTag
        self.isRecommended = isRecommended
    }

    var initials: String {
        let words = name.split(separator: " ")
        if words.count >= 2 {
            return "\(words[0].prefix(1))\(words[1].prefix(1))"
        }
        return String(name.prefix(2))
    }
}

// MARK: - Reference clip picker

/// Sources for a clone reference clip: record on-device or pick a saved voice.
struct IOSReferenceClipSheet: View {
    let savedVoices: [IOSVoicePickerOption]
    @Binding var selectedSavedVoiceID: String?
    var onRequestRecord: () -> Void
    var onDismiss: (() -> Void)?
    var presentation: IOSBottomSheetPresentationStyle = .system

    var body: some View {
        IOSBottomSheetSurface(
            title: "Reference clip",
            tint: IOSBrandTheme.clone,
            presentation: presentation,
            onDismiss: onDismiss
        ) {
            IOSScrollView(bottomFadeHeight: 0) {
                VStack(alignment: .leading, spacing: 14) {
                    sourcePicker

                    if !savedVoices.isEmpty {
                        let recommended = savedVoices.filter(\.isRecommended)
                        let others = savedVoices.filter { !$0.isRecommended }
                        if recommended.isEmpty {
                            savedVoicesHeader("Saved voices")
                            ForEach(others) { row(for: $0) }
                        } else {
                            savedVoicesHeader("Recommended")
                            ForEach(recommended) { row(for: $0) }
                            if !others.isEmpty {
                                savedVoicesHeader("All voices")
                                ForEach(others) { row(for: $0) }
                            }
                        }
                    }
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 24)
            }
        }
    }

    private var sourcePicker: some View {
        sourceRow(
            symbol: "mic.fill",
            title: "Record new clip",
            detail: "Capture a 10-20 second sample on this iPhone.",
            action: onRequestRecord
        )
    }

    private func sourceRow(
        symbol: String,
        title: String,
        detail: String,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            HStack(alignment: .center, spacing: 14) {
                ZStack {
                    Circle()
                        .fill(IOSBrandTheme.clone.opacity(0.2))
                    Image(systemName: symbol)
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundStyle(IOSBrandTheme.clone)
                }
                .frame(width: 40, height: 40)

                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(IOSAppTheme.textPrimary)
                    Text(detail)
                        .font(.caption)
                        .foregroundStyle(IOSAppTheme.textSecondary)
                }

                Spacer(minLength: 8)

                Image(systemName: "chevron.right")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(IOSAppTheme.textTertiary)
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background {
                RoundedRectangle(cornerRadius: IOSCornerRadius.card, style: .continuous)
                    .fill(IOSAppTheme.glassSurfaceFillMuted.opacity(0.6))
            }
            .overlay {
                RoundedRectangle(cornerRadius: IOSCornerRadius.card, style: .continuous)
                    .stroke(Color.white.opacity(0.08), lineWidth: 0.8)
            }
        }
        .buttonStyle(.plain)
    }

    private func savedVoicesHeader(_ title: String) -> some View {
        Text(title.uppercased())
            .font(.system(size: 10, weight: .semibold))
            .tracking(0.7)
            .foregroundStyle(IOSAppTheme.textTertiary)
            .padding(.top, 6)
    }

    private func row(for option: IOSVoicePickerOption) -> some View {
        let isSelected = option.id == selectedSavedVoiceID
        return Button {
            selectedSavedVoiceID = option.id
            IOSHaptics.selection()
        } label: {
            HStack(alignment: .center, spacing: 12) {
                IOSVoiceAvatar(seed: option.id, initials: option.initials, diameter: 36)

                VStack(alignment: .leading, spacing: 1) {
                    Text(option.name)
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(IOSAppTheme.textPrimary)
                    if let subtitle = option.subtitle {
                        Text(subtitle)
                            .font(.caption)
                            .foregroundStyle(IOSAppTheme.textSecondary)
                    }
                }

                Spacer(minLength: 8)

                // Recommendation is conveyed by the "Recommended" section header + top placement.

                // Always reserve the checkmark slot (invisible when unselected) so recommended
                // rows stay aligned across selected and unselected rows.
                Image(systemName: "checkmark.circle.fill")
                    .font(.system(size: 16))
                    .foregroundStyle(IOSBrandTheme.clone)
                    .opacity(isSelected ? 1 : 0)
                    .frame(width: 20)
                    .accessibilityHidden(true)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 9)
            .background {
                RoundedRectangle(cornerRadius: IOSCornerRadius.card, style: .continuous)
                    .fill(isSelected ? IOSAppTheme.accentWash(IOSBrandTheme.clone) : Color.clear)
            }
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("referenceClipRow_\(option.id)")
    }
}

// MARK: - Delete model sheet

/// Destructive-confirmation sheet for removing an installed model.
/// Matches the reference's compact model row + red destructive CTA.
struct IOSDeleteModelSheet: View {
    let modelName: String
    let sizeLabel: String
    var presentation: IOSBottomSheetPresentationStyle = .system
    var onConfirm: () -> Void
    var onCancel: () -> Void

    static let detentHeight: CGFloat = 300

    var body: some View {
        IOSBottomSheetSurface(
            title: "Delete model?",
            tint: destructiveRed,
            presentation: presentation,
            onDismiss: onCancel
        ) {
            sheetContent
        }
    }

    private var sheetContent: some View {
        VStack(alignment: .leading, spacing: 0) {
            modelSummary
                .padding(.top, 4)
                .padding(.bottom, 20)

            VStack(spacing: 10) {
                deleteButton
                cancelButton
            }
            .padding(.bottom, 8)
        }
        .padding(.horizontal, 20)
        .padding(.bottom, 20)
    }

    private var destructiveRed: Color {
        Color(red: 255 / 255, green: 69 / 255, blue: 58 / 255)
    }

    private var destructiveRedDark: Color {
        Color(red: 197 / 255, green: 37 / 255, blue: 26 / 255)
    }

    private var modelSummary: some View {
        HStack(alignment: .center, spacing: 14) {
            ZStack {
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .fill(destructiveRed.opacity(0.12))
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .stroke(destructiveRed.opacity(0.32), lineWidth: 0.5)
                Image(systemName: "trash")
                    .font(.system(size: 19, weight: .semibold))
                    .foregroundStyle(destructiveRed)
            }
            .frame(width: 44, height: 44)

            VStack(alignment: .leading, spacing: 2) {
                Text(modelName)
                    .font(.system(size: 16, weight: .semibold))
                    .tracking(-0.08)
                    .foregroundStyle(IOSAppTheme.textPrimary)
                    .lineLimit(1)

                Text("Frees \(sizeLabel). You can reinstall later from Settings.")
                    .font(.system(size: 13, weight: .regular))
                    .foregroundStyle(IOSAppTheme.textSecondary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.82)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var deleteButton: some View {
        Button {
            IOSHaptics.warning()
            onConfirm()
        } label: {
            HStack(spacing: 8) {
                Image(systemName: "trash")
                    .font(.system(size: 17, weight: .semibold))
                Text("Delete model")
                    .font(.system(size: 17, weight: .semibold))
            }
            .foregroundStyle(.white)
            .frame(maxWidth: .infinity)
            .frame(height: 56)
            .background {
                Capsule(style: .continuous)
                    .fill(
                        LinearGradient(
                            colors: [destructiveRed, destructiveRedDark],
                            startPoint: .top,
                            endPoint: .bottom
                        )
                    )
            }
            .overlay {
                Capsule(style: .continuous)
                    .stroke(Color.white.opacity(0.18), lineWidth: 0.5)
            }
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("deleteModelSheet_confirm")
    }

    private var cancelButton: some View {
        Button {
            onCancel()
        } label: {
            Text("Cancel")
                .font(.system(size: 17, weight: .semibold))
                .foregroundStyle(IOSAppTheme.textPrimary)
                .frame(maxWidth: .infinity)
                .frame(height: 56)
                .background {
                    Capsule(style: .continuous)
                        .fill(Color.white.opacity(0.05))
                }
                .overlay {
                    Capsule(style: .continuous)
                        .stroke(Color.white.opacity(0.14), lineWidth: 0.5)
                }
        }
        .buttonStyle(.plain)
    }
}
