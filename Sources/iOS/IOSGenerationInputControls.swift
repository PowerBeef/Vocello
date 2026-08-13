import QwenVoiceCore
import SwiftUI
import UIKit

struct IOSDeliveryPicker: View {
    @Environment(AppModel.self) private var appModel

    @Binding var delivery: DeliveryInputState
    let tint: Color
    let customAccessibilityIdentifier: String?

    @FocusState private var isCustomEditorFocused: Bool
    @ScaledMetric(relativeTo: .body) private var inlineEditorHeight = 76
    @ScaledMetric(relativeTo: .body) private var contentSpacing = 8

    init(
        delivery: Binding<DeliveryInputState>,
        tint: Color,
        customAccessibilityIdentifier: String? = nil
    ) {
        _delivery = delivery
        self.tint = tint
        self.customAccessibilityIdentifier = customAccessibilityIdentifier
    }

    private var selectionLabel: String {
        switch delivery.mode {
        case .preset:
            return delivery.selectedPresetLabel
        case .custom:
            return customSummaryText
        }
    }

    private var customSummaryText: String {
        let trimmed = delivery.customText.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? "Custom delivery…" : trimmed
    }

    private var isCustomDeliveryEnabled: Bool {
        delivery.mode == .custom
    }

    var body: some View {
        VStack(alignment: .leading, spacing: contentSpacing) {
            // Track C continuation: the preset picker now opens the bottom-
            // sheet from Track F instead of the older system Menu. Selection
            // is binding-driven, so changes flow back without manual sync.
            Button {
                delivery.mode = .preset
                presentPresetSheet()
            } label: {
                HStack(spacing: 10) {
                    Text(selectionLabel)
                        .lineLimit(1)
                        .foregroundStyle(IOSAppTheme.textPrimary)

                    Spacer(minLength: 8)

                    Image(systemName: delivery.mode == .custom ? "slider.horizontal.3" : "chevron.up.chevron.down")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(delivery.mode == .custom ? tint : IOSAppTheme.textSecondary)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .iosSelectionFieldChrome(tint: tint, isFocused: isCustomDeliveryEnabled)
            .accessibilityIdentifier(customAccessibilityIdentifier ?? "")

            ZStack(alignment: .topTrailing) {
                IOSMultilineTextView(
                    text: $delivery.customText,
                    placeholder: "Describe the delivery or emotion (optional)",
                    tint: tint,
                    isFocused: Binding(
                        get: { isCustomEditorFocused && isCustomDeliveryEnabled },
                        set: { isCustomEditorFocused = $0 }
                    ),
                    isEnabled: isCustomDeliveryEnabled,
                    accessibilityIdentifier: customEditorAccessibilityIdentifier
                )
                .frame(height: inlineEditorHeight)
                .clipped()
                .opacity(isCustomDeliveryEnabled ? 1 : 0.48)

                if !isCustomDeliveryEnabled {
                    IOSStatusBadge(text: "Custom only", tone: .muted)
                        .padding(.top, 10)
                        .padding(.trailing, 10)
                        .allowsHitTesting(false)
                        .accessibilityHidden(true)
                }
            }
            .accessibilityHint(
                isCustomDeliveryEnabled
                    ? "Custom delivery input"
                    : "Select Custom delivery to edit this field"
            )
        }
        .onChange(of: delivery.mode) { _, newMode in
            if newMode == .custom {
                DispatchQueue.main.async {
                    isCustomEditorFocused = true
                }
            } else {
                isCustomEditorFocused = false
            }
        }
    }

    private var customEditorAccessibilityIdentifier: String? {
        guard let customAccessibilityIdentifier else { return nil }
        return "\(customAccessibilityIdentifier)_editor"
    }

    private func presentPresetSheet() {
        appModel.presentBottomPanel { bottomSafeAreaInset, availableHeight, dismiss in
            AnyView(
                IOSDeliveryPickerSheet(
                    selectedPresetID: Binding(
                        get: { delivery.selectedPresetID },
                        set: { newID in
                            delivery.mode = .preset
                            delivery.selectedPresetID = newID
                        }
                    ),
                    intensity: $delivery.selectedIntensity,
                    customText: $delivery.customText,
                    tint: tint,
                    onUseCustomTone: {
                        delivery.mode = .custom
                    },
                    onDismiss: dismiss,
                    presentation: .edgeToEdge(
                        bottomSafeAreaInset: bottomSafeAreaInset,
                        height: IOSBottomSheetChrome.expandedHeight(forScreenHeight: availableHeight)
                    )
                )
            )
        }
    }
}

struct IOSMultilineTextView: UIViewRepresentable {
    @Binding var text: String

    let placeholder: String
    let tint: Color
    @Binding var isFocused: Bool
    let isEnabled: Bool
    let isScrollEnabled: Bool
    let maxCharacterCount: Int?
    let accessibilityIdentifier: String?

    init(
        text: Binding<String>,
        placeholder: String,
        tint: Color = IOSBrandTheme.accent,
        isFocused: Binding<Bool> = .constant(false),
        isEnabled: Bool = true,
        isScrollEnabled: Bool = true,
        maxCharacterCount: Int? = nil,
        accessibilityIdentifier: String? = nil
    ) {
        _text = text
        self.placeholder = placeholder
        self.tint = tint
        _isFocused = isFocused
        self.isEnabled = isEnabled
        self.isScrollEnabled = isScrollEnabled
        self.maxCharacterCount = maxCharacterCount
        self.accessibilityIdentifier = accessibilityIdentifier
    }

    func makeCoordinator() -> Coordinator {
        Coordinator(
            text: $text,
            isFocused: $isFocused,
            placeholder: placeholder,
            tint: UIColor(tint),
            maxCharacterCount: maxCharacterCount
        )
    }

    func makeUIView(context: Context) -> UITextView {
        let textView = UITextView()
        textView.font = .preferredFont(forTextStyle: .body)
        textView.backgroundColor = IOSAppTheme.fieldFillUIColor
        textView.layer.cornerRadius = 18
        textView.layer.borderWidth = 1
        textView.isEditable = isEnabled
        textView.isSelectable = isEnabled
        textView.isUserInteractionEnabled = isEnabled
        textView.isScrollEnabled = isScrollEnabled
        textView.textContainerInset = UIEdgeInsets(top: 16, left: 12, bottom: 16, right: 12)
        textView.delegate = context.coordinator
        textView.text = text.isEmpty ? placeholder : text
        textView.textColor = text.isEmpty ? IOSAppTheme.textPlaceholderUIColor : IOSAppTheme.textPrimaryUIColor
        textView.tintColor = UIColor(tint)
        textView.keyboardAppearance = textView.traitCollection.userInterfaceStyle == .dark ? .dark : .light
        textView.accessibilityIdentifier = accessibilityIdentifier
        context.coordinator.applyChrome(to: textView, isFocused: false)
        return textView
    }

    func updateUIView(_ uiView: UITextView, context: Context) {
        guard !context.coordinator.isUpdating else { return }

        uiView.backgroundColor = IOSAppTheme.fieldFillUIColor
        uiView.tintColor = UIColor(tint)
        uiView.isScrollEnabled = isScrollEnabled
        uiView.isEditable = isEnabled
        uiView.isSelectable = isEnabled
        uiView.isUserInteractionEnabled = isEnabled
        uiView.alpha = isEnabled ? 1 : 0.88
        uiView.keyboardAppearance = uiView.traitCollection.userInterfaceStyle == .dark ? .dark : .light
        uiView.accessibilityIdentifier = accessibilityIdentifier
        context.coordinator.applyChrome(to: uiView, isFocused: isEnabled && isFocused)

        if isEnabled && isFocused && !uiView.isFirstResponder {
            uiView.becomeFirstResponder()
        } else if (!isEnabled || !isFocused) && uiView.isFirstResponder {
            uiView.resignFirstResponder()
        }

        if text.isEmpty, uiView.text != placeholder, !uiView.isFirstResponder {
            uiView.text = placeholder
            uiView.textColor = IOSAppTheme.textPlaceholderUIColor
        } else if !text.isEmpty, uiView.text != text {
            uiView.text = text
            uiView.textColor = IOSAppTheme.textPrimaryUIColor
        }
    }

    final class Coordinator: NSObject, UITextViewDelegate {
        @Binding var text: String
        @Binding var isFocused: Bool

        var isUpdating = false

        private let placeholder: String
        private let tint: UIColor
        private let maxCharacterCount: Int?

        init(
            text: Binding<String>,
            isFocused: Binding<Bool>,
            placeholder: String,
            tint: UIColor,
            maxCharacterCount: Int?
        ) {
            _text = text
            _isFocused = isFocused
            self.placeholder = placeholder
            self.tint = tint
            self.maxCharacterCount = maxCharacterCount
        }

        private func currentText(for textView: UITextView) -> String {
            textView.textColor == IOSAppTheme.textPlaceholderUIColor ? "" : textView.text
        }

        private func updateBinding(with value: String) {
            isUpdating = true
            text = value
            isUpdating = false
        }

        func applyChrome(to textView: UITextView, isFocused: Bool) {
            textView.layer.borderColor = (isFocused ? tint.withAlphaComponent(0.52) : UIColor.separator.withAlphaComponent(0.18)).cgColor
            textView.layer.borderWidth = isFocused ? 1.5 : 1
            textView.layer.shadowColor = tint.withAlphaComponent(isFocused ? 0.16 : 0).cgColor
            textView.layer.shadowOpacity = isFocused ? 1 : 0
            textView.layer.shadowRadius = isFocused ? 10 : 0
            textView.layer.shadowOffset = CGSize(width: 0, height: isFocused ? 4 : 0)
        }

        func textViewDidBeginEditing(_ textView: UITextView) {
            isFocused = true
            applyChrome(to: textView, isFocused: true)
            if textView.textColor == IOSAppTheme.textPlaceholderUIColor {
                textView.text = ""
                textView.textColor = IOSAppTheme.textPrimaryUIColor
            }
        }

        func textView(_ textView: UITextView, shouldChangeTextIn range: NSRange, replacementText: String) -> Bool {
            guard let maxCharacterCount else { return true }

            let existingText = currentText(for: textView)
            guard let swiftRange = Range(range, in: existingText) else { return true }

            let proposedText = existingText.replacingCharacters(in: swiftRange, with: replacementText)
            guard proposedText.count > maxCharacterCount else { return true }

            let replacedCharacterCount = existingText[swiftRange].count
            let availableCharacterCount = maxCharacterCount - (existingText.count - replacedCharacterCount)
            guard availableCharacterCount > 0 else { return false }

            let truncatedReplacement = String(replacementText.prefix(availableCharacterCount))
            guard !truncatedReplacement.isEmpty else { return false }

            let clampedText = existingText.replacingCharacters(in: swiftRange, with: truncatedReplacement)
            textView.text = clampedText
            textView.textColor = IOSAppTheme.textPrimaryUIColor
            updateBinding(with: clampedText)

            let insertionLocation = range.location + (truncatedReplacement as NSString).length
            textView.selectedRange = NSRange(location: insertionLocation, length: 0)
            return false
        }

        func textViewDidChange(_ textView: UITextView) {
            updateBinding(with: currentText(for: textView))
        }

        func textViewDidEndEditing(_ textView: UITextView) {
            isFocused = false
            applyChrome(to: textView, isFocused: false)

            if textView.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                text = ""
                textView.text = placeholder
                textView.textColor = IOSAppTheme.textPlaceholderUIColor
            }
        }
    }
}

/// Premium "save a voice" sheet matching Vocello's custom bottom-sheet chrome (grabber, glass,
/// terracotta, header ✕). When a `clipAudioURL` is supplied it leads with a clip-review card
/// (waveform + playback + duration + quality) so the user reviews the recording before naming.
/// The keyboard is NOT opened on appear — it rises only when a field is tapped, leaving the space
/// for the clip card and a clean layout.
struct IOSSaveVoiceSheet: View {
    let title: String
    @Binding var suggestedName: String
    @Binding var transcript: String
    let errorMessage: String?
    /// When present, show the clip-review card (review the recording before saving).
    var clipAudioURL: URL? = nil
    let onCancel: () -> Void
    let onSave: () -> Void

    @StateObject private var clipPlayer = ClipReviewPlayer()
    @FocusState private var isNameFocused: Bool
    // Real focus binding for the transcript editor — without it the field would resign first
    // responder on every parent re-render (keystroke). The coordinator keeps it in sync.
    @State private var isTranscriptFocused = false

    private let tint = IOSBrandTheme.clone
    private let transcriptHeight: CGFloat = 132

    private var trimmedName: String {
        suggestedName.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var body: some View {
        IOSBottomSheetSurface(title: title, tint: tint, presentation: .system, onDismiss: onCancel) {
            IOSScrollView(bottomFadeHeight: 0) {
                VStack(alignment: .leading, spacing: 18) {
                    if let clipAudioURL {
                        clipReviewCard(url: clipAudioURL)
                    }

                    fieldSection(label: "Name") {
                        TextField("Name this voice", text: $suggestedName)
                            .focused($isNameFocused)
                            .foregroundStyle(IOSAppTheme.textPrimary)
                            // Names are proper nouns; live autocorrection
                            // rewrites them as typed and the rewritten name is
                            // what persists (IUI-4 X2, sibling of the
                            // search-field fix).
                            .autocorrectionDisabled(true)
                            .textInputAutocapitalization(.words)
                            .submitLabel(.done)
                            .onSubmit { dismissKeyboard() }
                            .accessibilityIdentifier("saveVoice_nameField")
                            .iosSelectionFieldChrome(tint: tint, isFocused: isNameFocused)
                    }

                    fieldSection(
                        label: "What you said",
                        // Honest about what the transcript buys: it is the key
                        // to in-context prosody transfer, not a nicety
                        // (2026-08-04 delivery-control audit, F8).
                        caption: "Auto-transcribed. With it, clones carry this clip's pacing and emotion; without it, identity only."
                    ) {
                        IOSMultilineTextView(
                            text: $transcript,
                            placeholder: "What you said in the recording",
                            tint: tint,
                            isFocused: $isTranscriptFocused,
                            accessibilityIdentifier: "saveVoice_transcriptEditor"
                        )
                        .frame(height: transcriptHeight)
                    }

                    if let errorMessage {
                        Text(errorMessage)
                            .font(.footnote.weight(.medium))
                            .foregroundStyle(.red)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }

                    IOSPrimaryCTAButton(
                        title: "Save voice",
                        symbol: "checkmark",
                        tint: tint,
                        isEnabled: !trimmedName.isEmpty,
                        action: {
                            dismissKeyboard()
                            onSave()
                        }
                    )
                    .padding(.top, 4)
                    .accessibilityIdentifier("saveVoice_saveButton")
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 24)
            }
            .scrollDismissesKeyboard(.interactively)
        }
        .presentationDragIndicator(.hidden)
        .interactiveDismissDisabled(true)
        .onAppear {
            if let clipAudioURL { clipPlayer.load(url: clipAudioURL) }
        }
        .onDisappear { clipPlayer.stop() }
    }

    // MARK: - Sections

    private func fieldSection<Content: View>(
        label: String,
        caption: String? = nil,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 6) {
                Text(label)
                    .iosScaledFont(size: 13, weight: .semibold, relativeTo: .footnote)
                    .foregroundStyle(IOSAppTheme.textSecondary)
                if let caption {
                    Text(caption)
                        .font(.caption)
                        .foregroundStyle(IOSAppTheme.textTertiary)
                }
            }
            content()
        }
    }

    private func clipReviewCard(url: URL) -> some View {
        HStack(spacing: 14) {
            Button {
                IOSHaptics.selection()
                clipPlayer.toggle()
            } label: {
                ZStack {
                    Circle().fill(tint.opacity(0.2))
                    Image(systemName: clipPlayer.isPlaying ? "pause.fill" : "play.fill")
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(tint)
                }
                .frame(width: 44, height: 44)
            }
            .buttonStyle(.plain)
            .accessibilityLabel(clipPlayer.isPlaying ? "Pause" : "Play recording")

            VStack(alignment: .leading, spacing: 8) {
                IOSWaveformBars(
                    seed: abs(url.lastPathComponent.hashValue),
                    barCount: 28,
                    tint: tint,
                    progress: clipPlayer.progress,
                    isAnimating: false,
                    unplayedColor: tint.opacity(0.30),
                    style: .player
                )
                .frame(height: 26)

                HStack(spacing: 8) {
                    Text(durationLabel(clipPlayer.duration))
                        .font(.caption.weight(.medium))
                        .monospacedDigit()
                        .foregroundStyle(IOSAppTheme.textSecondary)
                    Spacer(minLength: 8)
                    let hint = clipQualityHint(duration: clipPlayer.duration)
                    IOSStatusBadge(text: hint.label, tone: hint.tone)
                }
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
        .frame(maxWidth: .infinity)
        .background {
            RoundedRectangle(cornerRadius: IOSCornerRadius.card, style: .continuous)
                .fill(IOSAppTheme.glassSurfaceFillMuted.opacity(0.6))
        }
        .overlay {
            RoundedRectangle(cornerRadius: IOSCornerRadius.card, style: .continuous)
                .stroke(Color.white.opacity(0.08), lineWidth: 0.8)
        }
    }

    // MARK: - Helpers

    private func dismissKeyboard() {
        isNameFocused = false
        isTranscriptFocused = false
    }

    private func durationLabel(_ seconds: TimeInterval) -> String {
        guard seconds.isFinite, seconds > 0 else { return "0:00" }
        let total = Int(seconds.rounded())
        return String(format: "%d:%02d", total / 60, total % 60)
    }

    /// Pre-save quality hint from the clip length, aligned with the clone-reference window
    /// (10–20 s sweet spot, acceptable to ~30 s). The recorder caps at 20 s, so recorded clips
    /// read "Good length"; this mainly informs imported / generated clips.
    private func clipQualityHint(duration: TimeInterval) -> (label: String, tone: IOSStatusBadge.Tone) {
        guard duration > 0 else { return ("Ready", .muted) }
        switch duration {
        case ..<10: return ("A bit short", .warning)
        case 10...30: return ("Good length", .success)
        default: return ("A bit long", .warning)
        }
    }
}
