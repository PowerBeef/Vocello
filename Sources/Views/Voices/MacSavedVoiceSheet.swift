import AppKit
import QwenVoiceCore
import SwiftUI
import UniformTypeIdentifiers

struct SavedVoiceSheetConfiguration: Identifiable, Sendable {
    let id = UUID()
    let title: String
    let subtitle: String
    let confirmLabel: String
    let initialName: String
    let initialAudioPath: String
    let initialTranscript: String
    let initialReferenceLanguage: Qwen3SupportedLanguage
    let initialTranscriptReadySource: ReferenceTranscriptionReviewState.ReadySource
    /// Normalized name of an existing saved voice that this enrollment
    /// replaces. The duplicate-name guard ignores this name so the user can
    /// keep the same identifier; the repository replaces the old assets in
    /// the same commit. Nil for the add, cloneResult and designResult flows.
    let replacingNormalizedName: String?

    init(
        title: String,
        subtitle: String,
        confirmLabel: String,
        initialName: String,
        initialAudioPath: String,
        initialTranscript: String,
        initialReferenceLanguage: Qwen3SupportedLanguage = .auto,
        initialTranscriptReadySource: ReferenceTranscriptionReviewState.ReadySource = .existing,
        replacingNormalizedName: String? = nil
    ) {
        self.title = title
        self.subtitle = subtitle
        self.confirmLabel = confirmLabel
        self.initialName = initialName
        self.initialAudioPath = initialAudioPath
        self.initialTranscript = initialTranscript
        self.initialReferenceLanguage = initialReferenceLanguage
        self.initialTranscriptReadySource = initialTranscriptReadySource
        self.replacingNormalizedName = replacingNormalizedName
    }

    static let manualAdd = SavedVoiceSheetConfiguration(
        title: MacInterfaceText.savedVoiceAddTitle,
        subtitle: MacInterfaceText.savedVoiceAddSubtitle,
        confirmLabel: MacInterfaceText.savedVoiceAddConfirm,
        initialName: "",
        initialAudioPath: "",
        initialTranscript: ""
    )

    static func cloneResult(
        suggestedName: String,
        audioPath: String,
        transcript: String
    ) -> SavedVoiceSheetConfiguration {
        SavedVoiceSheetConfiguration(
            title: MacInterfaceText.historySaveToSavedVoices,
            subtitle: MacInterfaceText.savedVoiceCloneSubtitle,
            confirmLabel: MacInterfaceText.historySaveToSavedVoices,
            initialName: suggestedName,
            initialAudioPath: audioPath,
            initialTranscript: transcript,
            initialReferenceLanguage: PromptLanguageDetector.detect(transcript)
        )
    }

    static func designResult(
        voiceDescription: String,
        audioPath: String,
        transcript: String
    ) -> SavedVoiceSheetConfiguration {
        SavedVoiceSheetConfiguration(
            title: MacInterfaceText.savedVoiceDesignTitle,
            subtitle: MacInterfaceText.savedVoiceDesignSubtitle,
            confirmLabel: MacInterfaceText.historySaveToSavedVoices,
            initialName: SavedVoiceNameSuggestion.designResultName(from: voiceDescription),
            initialAudioPath: audioPath,
            initialTranscript: transcript,
            initialReferenceLanguage: PromptLanguageDetector.detect(transcript)
        )
    }

    /// The Saved Voices "Replace reference" flow: the existing name and
    /// transcript are pre-filled and the audio path stays blank so the user
    /// picks a new clip. The duplicate-name guard skips the existing entry.
    static func replaceReference(
        name: String,
        transcript: String,
        referenceLanguage: Qwen3SupportedLanguage = .auto
    ) -> SavedVoiceSheetConfiguration {
        SavedVoiceSheetConfiguration(
            title: MacInterfaceText.savedVoiceReplaceTitle,
            subtitle: MacInterfaceText.savedVoiceReplaceSubtitle,
            confirmLabel: MacInterfaceText.savedVoiceReplaceConfirm,
            initialName: name,
            initialAudioPath: "",
            initialTranscript: transcript,
            initialReferenceLanguage: referenceLanguage == .auto
                ? PromptLanguageDetector.detect(transcript)
                : referenceLanguage,
            replacingNormalizedName: SavedVoiceNameSanitizer.normalizedName(name)
        )
    }
}

enum SavedVoiceNameSanitizer {
    static func normalizedName(_ rawName: String) -> String {
        rawName
            .replacingOccurrences(
                of: #"[^\w\s-]"#,
                with: "",
                options: .regularExpression
            )
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .replacingOccurrences(of: " ", with: "_")
    }
}

enum SavedVoiceNameSuggestion {
    static let designedVoiceFallback = "Designed_Voice"

    static func designResultName(
        from voiceDescription: String,
        fallback: String = designedVoiceFallback,
        maxLength: Int = 36
    ) -> String {
        let normalized = SavedVoiceNameSanitizer.normalizedName(voiceDescription)
        guard !normalized.isEmpty else { return fallback }
        guard normalized.count > maxLength else { return normalized }

        let components = normalized.split(separator: "_")
        var shortened = ""
        for component in components {
            let separator = shortened.isEmpty ? "" : "_"
            let candidate = shortened + separator + component
            if candidate.count > maxLength {
                break
            }
            shortened = candidate
        }

        if shortened.isEmpty {
            shortened = String(normalized.prefix(maxLength))
                .trimmingCharacters(in: CharacterSet(charactersIn: "_-"))
        }

        return shortened.isEmpty ? fallback : shortened
    }
}

/// The saved-voice enrollment sheet in the iOS save-voice language
/// (`IOSSaveVoiceSheet`): labeled field sections on the dark canvas, the
/// transcription review status with its audio-only confirmation, the
/// reference-language picker, and one primary capsule action. The candidate
/// lifecycle is unchanged: Confirm stages a private candidate, a clean one
/// commits, a warned one waits for Keep, and Discard, Cancel or outside
/// dismissal discards it. Every `voicesEnroll_*` identifier is the lane and
/// contract surface.
struct MacSavedVoiceSheet: View {
    @EnvironmentObject private var ttsEngineStore: TTSEngineStore
    @Environment(\.dismiss) private var dismiss

    let configuration: SavedVoiceSheetConfiguration
    let onComplete: (Voice) -> Void

    @State private var name: String
    @State private var audioPath: String
    @State private var transcript: String
    @State private var referenceLanguage: Qwen3SupportedLanguage
    @State private var transcriptionReview: ReferenceTranscriptionReviewState
    @State private var transcriptionEvidence: VoiceClipTranscriber.EnrollmentEvidence?
    @State private var isSaving = false
    @State private var errorMessage: String?
    @State private var existingNormalizedNames: Set<String> = []
    /// When non-nil, the staged voice has quality warnings and the user is
    /// being asked whether to publish it or discard the private candidate.
    @State private var pendingVoiceForReview: PreparedVoiceCandidate?
    @State private var isReviewDecisionInFlight = false
    @State private var isRecordSheetPresented = false
    @State private var transcriptionTask: Task<Void, Never>?
    @State private var speechAvailability: VoiceClipTranscriber.TranscriptionAvailability = .available
    @FocusState private var isNameFocused: Bool
    @FocusState private var isAudioPathFocused: Bool
    @FocusState private var isTranscriptFocused: Bool

    private let tint = MacTheme.Brand.modeClone

    init(
        configuration: SavedVoiceSheetConfiguration,
        onComplete: @escaping (Voice) -> Void
    ) {
        self.configuration = configuration
        self.onComplete = onComplete
        _name = State(initialValue: configuration.initialName)
        _audioPath = State(initialValue: configuration.initialAudioPath)
        _transcript = State(initialValue: configuration.initialTranscript)
        _referenceLanguage = State(initialValue: configuration.initialReferenceLanguage)
        _transcriptionReview = State(
            initialValue: ReferenceTranscriptionReviewState(
                initialTranscript: configuration.initialTranscript,
                readySource: configuration.initialTranscriptReadySource
            )
        )
        _transcriptionEvidence = State(initialValue: nil)
    }

    private var trimmedName: String {
        name.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private var normalizedName: String {
        SavedVoiceNameSanitizer.normalizedName(trimmedName)
    }

    private var validationMessage: String? {
        guard !trimmedName.isEmpty else { return nil }

        if normalizedName.isEmpty {
            return MacInterfaceText.savedVoiceNameNeedsCharacters
        }

        // In the replace-reference flow the user keeps the same identifier;
        // only a different saved voice's name is a collision.
        if existingNormalizedNames.contains(normalizedName)
            && normalizedName != configuration.replacingNormalizedName {
            return MacInterfaceText.savedVoiceNameExists(normalizedName)
        }

        return nil
    }

    private var canSubmit: Bool {
        !trimmedName.isEmpty
            && !audioPath.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && validationMessage == nil
            && !isSaving
            && transcriptionReview.allowsSave(transcript: transcript)
            && !requiresReferenceLanguageConfirmation
    }

    private var requiresReferenceLanguageConfirmation: Bool {
        !transcript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && referenceLanguage == .auto
    }

    private var transcriptBinding: Binding<String> {
        Binding(
            get: { transcript },
            set: { newValue in
                transcript = newValue
                handleTranscriptEdit(newValue)
            }
        )
    }

    var body: some View {
        VStack(alignment: .leading, spacing: VocelloTheme.Spacing.xl) {
            VStack(alignment: .leading, spacing: VocelloTheme.Spacing.xs) {
                Text(configuration.title)
                    .macType(.sheetTitle)
                    .foregroundStyle(MacTheme.Text.primary)
                Text(configuration.subtitle)
                    .macType(.rowMeta)
                    .foregroundStyle(MacTheme.Text.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            fieldSection(label: MacInterfaceText.savedVoiceNameSection) {
                TextField(MacInterfaceText.savedVoiceNamePlaceholder, text: $name)
                    .textFieldStyle(.plain)
                    .focused($isNameFocused)
                    .autocorrectionDisabled(true)
                    .modifier(MacFieldChrome(tint: tint, isFocused: isNameFocused))
                    .accessibilityIdentifier("voicesEnroll_nameField")
            }

            fieldSection(label: MacInterfaceText.savedVoiceAudioSection) {
                HStack(spacing: VocelloTheme.Spacing.sm) {
                    TextField(MacInterfaceText.savedVoiceAudioPlaceholder, text: $audioPath)
                        .textFieldStyle(.plain)
                        .focused($isAudioPathFocused)
                        .modifier(MacFieldChrome(tint: tint, isFocused: isAudioPathFocused))
                        .accessibilityIdentifier("voicesEnroll_audioPathField")

                    Button(MacInterfaceText.savedVoiceBrowse) {
                        browseForAudio()
                    }
                    .buttonStyle(.bordered)
                    .accessibilityIdentifier("voicesEnroll_browseButton")

                    Button {
                        isRecordSheetPresented = true
                    } label: {
                        Label(MacInterfaceText.savedVoiceRecord, systemImage: "mic.fill")
                    }
                    .buttonStyle(.bordered)
                    .accessibilityIdentifier("voicesEnroll_recordButton")
                }
            }

            fieldSection(label: MacInterfaceText.savedVoiceTranscriptSection, caption: MacInterfaceText.savedVoiceTranscriptHelp) {
                if let issue = speechIssueMessage {
                    HStack(spacing: VocelloTheme.Spacing.tight) {
                        Image(systemName: "exclamationmark.triangle.fill")
                            .macType(.badge)
                            .foregroundStyle(MacTheme.Status.guarded)
                        Text(issue)
                            .macType(.caption)
                            .foregroundStyle(MacTheme.Text.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                            .accessibilityIdentifier("voicesEnroll_speechUnavailable")
                        Button(speechIssueButtonLabel) {
                            openSpeechSettings()
                        }
                        .controlSize(.small)
                        .accessibilityIdentifier("voicesEnroll_speechSettingsButton")
                    }
                }

                TextEditor(text: transcriptBinding)
                    .macType(.body)
                    .scrollContentBackground(.hidden)
                    .focused($isTranscriptFocused)
                    .frame(minHeight: 96)
                    .padding(VocelloTheme.Spacing.tight)
                    .modifier(MacFieldChrome(tint: tint, isFocused: isTranscriptFocused))
                    .accessibilityIdentifier("voicesEnroll_transcriptField")

                transcriptionStatus

                if transcriptionReview.offersAudioOnlyConfirmation {
                    Button {
                        confirmAudioOnly()
                    } label: {
                        Label(VocelloPresentationText.useAudioOnly, systemImage: "waveform")
                            .macType(.buttonLabel)
                            .foregroundStyle(tint)
                            .padding(.horizontal, VocelloTheme.Spacing.md)
                            .frame(minHeight: MacControl.icon.height)
                            .background { VocelloShape.pill().fill(tint.opacity(0.12)) }
                            .overlay { VocelloShape.pill().stroke(tint.opacity(0.35), lineWidth: VocelloTheme.Stroke.hairline) }
                            .contentShape(VocelloShape.pill())
                    }
                    .buttonStyle(.plain)
                    .accessibilityHint(VocelloPresentationText.useAudioOnlyHint)
                    .accessibilityIdentifier("voicesEnroll_useAudioOnlyButton")
                }
            }

            fieldSection(
                label: VocelloPresentationText.referenceLanguageTitle,
                caption: requiresReferenceLanguageConfirmation
                    ? VocelloPresentationText.referenceLanguageConfirmation
                    : VocelloPresentationText.referenceLanguageDetail,
                captionTint: requiresReferenceLanguageConfirmation ? MacTheme.Status.guarded : nil
            ) {
                Picker(VocelloPresentationText.referenceLanguageTitle, selection: $referenceLanguage) {
                    Text(VocelloPresentationText.referenceLanguagePlaceholder)
                        .tag(Qwen3SupportedLanguage.auto)
                    ForEach(Qwen3SupportedLanguage.selectableCases, id: \.self) { language in
                        Text(language.displayName).tag(language)
                    }
                }
                .labelsHidden()
                .frame(maxWidth: 240, alignment: .leading)
                .accessibilityIdentifier("voicesEnroll_referenceLanguagePicker")
            }

            if let activeMessage = validationMessage ?? errorMessage {
                Text(activeMessage)
                    .macType(.captionEmphasis)
                    .foregroundStyle(MacTheme.Status.critical)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("voicesEnroll_errorMessage")
            }

            HStack {
                Button(MacInterfaceText.cancel) {
                    dismiss()
                }
                .buttonStyle(.bordered)
                .keyboardShortcut(.cancelAction)
                .accessibilityIdentifier("voicesEnroll_cancelButton")

                Spacer()

                MacPrimaryCTAButton(
                    title: configuration.confirmLabel,
                    symbol: "checkmark",
                    tint: tint,
                    isEnabled: canSubmit
                ) {
                    saveVoice()
                }
                .keyboardShortcut(.defaultAction)
                .accessibilityIdentifier("voicesEnroll_confirmButton")
            }
        }
        .padding(VocelloTheme.Spacing.xl)
        // Min instead of fixed: a fixed width squeezed content at large
        // accessibility text sizes.
        .frame(minWidth: 520, maxWidth: 600)
        .background(MacTheme.canvasGradient)
        .task {
            speechAvailability = VoiceClipTranscriber.availability()
            await loadExistingVoiceNames()
        }
        .onChange(of: name) { _, _ in
            errorMessage = nil
        }
        .onChange(of: audioPath) { _, newPath in
            let trimmedPath = newPath.trimmingCharacters(in: .whitespacesAndNewlines)
            if trimmedPath.isEmpty {
                transcriptionTask?.cancel()
                transcriptionTask = nil
                transcriptionEvidence = nil
                if transcript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    transcriptionReview.awaitAudio()
                }
            } else {
                autoTranscribeIfNeeded(path: newPath)
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            // The user may have just granted speech recognition in System
            // Settings; refresh the caption and retry the auto-fill.
            let refreshed = VoiceClipTranscriber.availability()
            if refreshed != speechAvailability {
                speechAvailability = refreshed
                if refreshed == .available {
                    autoTranscribeIfNeeded(path: audioPath)
                }
            }
        }
        .onDisappear {
            transcriptionTask?.cancel()
            transcriptionReview.invalidate()
        }
        .sheet(isPresented: $isRecordSheetPresented) {
            MacRecordVoiceSheet { url in
                audioPath = url.path
            }
        }
        .alert(
            reviewAlertTitle,
            isPresented: Binding(
                get: { pendingVoiceForReview != nil && !isReviewDecisionInFlight },
                set: { isPresented in
                    if !isPresented,
                       !isReviewDecisionInFlight,
                       let candidate = pendingVoiceForReview {
                        discardPendingVoice(candidate)
                    }
                }
            ),
            presenting: pendingVoiceForReview
        ) { candidate in
            // The hard-block tier (>60 s) hides "Keep voice" so the user has to
            // discard or cancel; the soft-warn tier keeps all three buttons.
            if !PreparedVoiceQualityWarning.isHardBlocking(candidate.qualityWarnings) {
                Button(MacInterfaceText.savedVoiceKeepVoice) {
                    acceptPendingVoice(candidate)
                }
                .accessibilityIdentifier("voicesEnroll_keepDespiteWarning")
            }
            Button(MacInterfaceText.savedVoiceDiscardAndReRecord, role: .destructive) {
                discardPendingVoice(candidate)
            }
            .accessibilityIdentifier("voicesEnroll_discardOnWarning")
            Button(MacInterfaceText.cancel, role: .cancel) {
                discardPendingVoice(candidate)
            }
            .accessibilityIdentifier("voicesEnroll_cancelOnWarning")
        } message: { candidate in
            Text(reviewAlertMessage(for: candidate))
        }
    }

    // MARK: - Sections

    private func fieldSection<Content: View>(
        label: String,
        caption: String? = nil,
        captionTint: Color? = nil,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: VocelloTheme.Spacing.sm) {
            VStack(alignment: .leading, spacing: VocelloTheme.Spacing.xs) {
                Text(label)
                    .macType(.rowTitle)
                    .foregroundStyle(MacTheme.Text.secondary)
                if let caption {
                    Text(caption)
                        .macType(.caption)
                        .foregroundStyle(captionTint ?? MacTheme.Text.tertiary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            content()
        }
    }

    @ViewBuilder
    private var transcriptionStatus: some View {
        let status = transcriptionReview.status
        HStack(alignment: .firstTextBaseline, spacing: VocelloTheme.Spacing.sm) {
            if status.showsProgress {
                ProgressView()
                    .controlSize(.mini)
                    .accessibilityHidden(true)
            } else {
                Image(systemName: status.symbolName)
                    .macType(.badge)
                    .foregroundStyle(tint)
                    .accessibilityHidden(true)
            }
            Text(status.message)
                .macType(.caption)
                .foregroundStyle(MacTheme.Text.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(status.message)
        .accessibilityIdentifier("voicesEnroll_transcriptionStatus")
    }

    // MARK: - Speech availability

    private func loadExistingVoiceNames() async {
        do {
            let voices = try await ttsEngineStore.listPreparedVoices()
            await MainActor.run {
                existingNormalizedNames = Set(voices.map(\.id))
            }
        } catch {
            await MainActor.run {
                existingNormalizedNames = []
            }
        }
    }

    /// Caption shown when automatic transcription cannot run; silent denial
    /// left users wondering why the transcript never auto-filled.
    private var speechIssueMessage: String? {
        switch speechAvailability {
        case .available, .notDetermined:
            return nil
        case .denied:
            return MacInterfaceText.savedVoiceSpeechDenied
        case .siriDisabled:
            return MacInterfaceText.savedVoiceSiriDisabled
        }
    }

    private var speechIssueButtonLabel: String {
        speechAvailability == .siriDisabled
            ? MacInterfaceText.savedVoiceOpenSiriSettings
            : MacInterfaceText.recordOpenSystemSettings
    }

    private func openSpeechSettings() {
        let anchor = speechAvailability == .siriDisabled
            ? "x-apple.systempreferences:com.apple.Siri-Settings.extension"
            : "x-apple.systempreferences:com.apple.preference.security?Privacy_SpeechRecognition"
        if let url = URL(string: anchor) {
            NSWorkspace.shared.open(url)
        }
    }

    // MARK: - Transcription review

    /// Starts the on-device transcriber and binds its result to one operation
    /// generation; cancellation is cooperative, so the generation check is the
    /// final authority.
    private func autoTranscribeIfNeeded(path: String) {
        speechAvailability = VoiceClipTranscriber.availability()
        transcriptionTask?.cancel()

        let trimmedPath = path.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedPath.isEmpty,
              transcript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              FileManager.default.fileExists(atPath: trimmedPath) else { return }

        transcriptionEvidence = nil
        let generation = transcriptionReview.beginAutomaticTranscription()
        transcriptionTask = Task { @MainActor in
            let result = await VoiceClipTranscriber.enrollmentResult(
                url: URL(fileURLWithPath: trimmedPath)
            )
            guard !Task.isCancelled, audioPath == path else { return }
            transcriptionEvidence = result.evidence

            if let recognizedText = result.text {
                let applied = transcriptionReview.acceptAutomaticTranscript(
                    recognizedText,
                    generation: generation,
                    currentTranscript: transcript
                )
                if applied {
                    transcript = recognizedText
                    if referenceLanguage == .auto {
                        referenceLanguage = result.language
                    }
                }
            } else {
                transcriptionReview.finishWithoutTranscript(
                    reason: unavailableReason(for: result.evidence),
                    generation: generation,
                    currentTranscript: transcript
                )
            }

            if transcriptionReview.isCurrent(generation: generation) {
                transcriptionTask = nil
            }
        }
    }

    private func handleTranscriptEdit(_ newValue: String) {
        transcriptionTask?.cancel()
        transcriptionTask = nil
        transcriptionReview.userEditedTranscript(newValue)
        if referenceLanguage == .auto {
            referenceLanguage = PromptLanguageDetector.detect(newValue)
        }
    }

    private func confirmAudioOnly() {
        transcriptionTask?.cancel()
        transcriptionTask = nil
        transcript = ""
        transcriptionReview.confirmAudioOnly()
    }

    private func unavailableReason(
        for evidence: VoiceClipTranscriber.EnrollmentEvidence
    ) -> ReferenceTranscriptionReviewState.UnavailableReason {
        if evidence.authorizationStatus == .siriDisabled {
            return .siriDisabled
        }
        switch evidence.outcome {
        case .permissionDenied, .authorizationTimedOut:
            return .permissionDenied
        case .noCandidateLocales, .recognizerUnavailable:
            return .recognizerUnavailable
        case .onDeviceRecognitionUnsupported:
            return .onDeviceRecognitionUnsupported
        case .recognitionTimedOut:
            return .recognitionTimedOut
        case .recognitionFailed:
            return .recognitionFailed
        case .emptyResult:
            return .emptyResult
        case .lowConfidence:
            return .lowConfidence
        case .success:
            return .emptyResult
        }
    }

    // MARK: - Actions

    private func browseForAudio() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.audio, .wav, .mp3, .aiff]
        if panel.runModal() == .OK, let url = panel.url {
            audioPath = url.path
        }
    }

    private func saveVoice() {
        guard validationMessage == nil else { return }

        isSaving = true
        errorMessage = nil

        Task {
            do {
                let candidate = try await ttsEngineStore.preparePreparedVoiceCandidate(
                    name: trimmedName,
                    audioPath: audioPath.trimmingCharacters(in: .whitespacesAndNewlines),
                    transcript: transcript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                        ? nil
                        : transcript.trimmingCharacters(in: .whitespacesAndNewlines),
                    replacingVoiceID: configuration.replacingNormalizedName,
                    enrollmentMetadata: try VoiceClipTranscriber.preparedVoiceEnrollmentMetadata(
                        referenceLanguage: referenceLanguage,
                        reviewState: transcriptionReview,
                        evidence: transcriptionEvidence
                    )
                )
                await MainActor.run {
                    pendingVoiceForReview = candidate.qualityWarnings.isEmpty ? nil : candidate
                }
                if candidate.qualityWarnings.isEmpty {
                    do {
                        let savedVoice = try await ttsEngineStore.commitPreparedVoiceCandidate(id: candidate.id)
                        await MainActor.run {
                            onComplete(savedVoice)
                            dismiss()
                        }
                    } catch {
                        await MainActor.run {
                            pendingVoiceForReview = candidate
                            errorMessage = error.localizedDescription
                        }
                    }
                }
            } catch {
                await MainActor.run {
                    errorMessage = error.localizedDescription
                }
            }
            await MainActor.run {
                isSaving = false
            }
        }
    }

    private func acceptPendingVoice(_ candidate: PreparedVoiceCandidate) {
        guard !isReviewDecisionInFlight else { return }
        isReviewDecisionInFlight = true
        Task {
            do {
                let savedVoice = try await ttsEngineStore.commitPreparedVoiceCandidate(id: candidate.id)
                pendingVoiceForReview = nil
                isReviewDecisionInFlight = false
                onComplete(savedVoice)
                dismiss()
            } catch {
                errorMessage = error.localizedDescription
                isReviewDecisionInFlight = false
            }
        }
    }

    private func discardPendingVoice(_ candidate: PreparedVoiceCandidate) {
        guard !isReviewDecisionInFlight else { return }
        isReviewDecisionInFlight = true
        Task {
            do {
                try await ttsEngineStore.discardPreparedVoiceCandidate(id: candidate.id)
                pendingVoiceForReview = nil
            } catch {
                errorMessage = error.localizedDescription
            }
            isReviewDecisionInFlight = false
        }
    }

    private var reviewAlertTitle: String {
        errorMessage == nil ? MacInterfaceText.voicesReferenceOutsideRange : MacInterfaceText.savedVoiceSaveFailedTitle
    }

    private func reviewAlertMessage(for candidate: PreparedVoiceCandidate) -> String {
        errorMessage ?? PreparedVoiceQualityWarning.summary(for: candidate.qualityWarnings)
    }
}

/// Field chrome of the iOS sheets (`iosSelectionFieldChrome`): a muted glass
/// surface with a focus-aware hairline.
struct MacFieldChrome: ViewModifier {
    let tint: Color
    let isFocused: Bool
    var radius: CGFloat = VocelloTheme.Radius.input

    func body(content: Content) -> some View {
        let shape = RoundedRectangle(cornerRadius: radius, style: .continuous)
        content
            .padding(.horizontal, VocelloTheme.Spacing.snug)
            .padding(.vertical, VocelloTheme.Spacing.sm)
            .macSubtleGlassSurface(
                in: shape,
                tint: isFocused ? tint : MacTheme.Brand.silver,
                fill: MacTheme.Surface.glassSurfaceMuted.opacity(isFocused ? 0.72 : 0.56),
                strokeOpacity: isFocused ? 0.18 : 0.12,
                interactive: true
            )
            .overlay {
                shape
                    .stroke(
                        isFocused ? tint.opacity(0.35) : Color.white.opacity(0.06),
                        lineWidth: isFocused ? VocelloTheme.Stroke.standard : VocelloTheme.Stroke.hairline
                    )
                    .allowsHitTesting(false)
            }
            .appAnimation(MacTheme.Motion.highlight, value: isFocused)
    }
}
