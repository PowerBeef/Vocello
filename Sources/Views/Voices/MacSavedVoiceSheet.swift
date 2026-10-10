import AppKit
import QwenVoiceCore
import SwiftUI
import UniformTypeIdentifiers

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
    /// PA-17: the store refuses enrollment until the one-time consent is recorded,
    /// so the sheet offers the same inline acknowledgment as Voice Cloning up front
    /// and keeps Confirm disabled until it is on.
    @AppStorage(VoiceCloningConsentPolicy.recordedConsentDefaultsKey, store: AppDefaults.store)
    private var cloneConsentAcknowledged = false

    let configuration: SavedVoiceSheetConfiguration
    let onComplete: (Voice) -> Void

    @State private var name: String
    @State private var audioPath: String
    @State private var transcript: String
    @State private var referenceLanguageSelection: ReferenceLanguageSelection
    @State private var transcriptionReview: ReferenceTranscriptionReviewState
    @State private var transcriptionEvidence: VoiceClipTranscriber.EnrollmentEvidence?
    @State private var isSaving = false
    /// The candidate is being committed: Cancel waits for the brief commit
    /// rather than claim to stop a voice that is already landing (MAC-12).
    @State private var isCommitting = false
    @State private var saveCancellation = SavedVoiceSaveCancellation()
    /// Clips recorded in this sheet, removed when it closes (MAC-25).
    @State private var recordedClips = ReferenceClipStashTracker()
    @State private var errorMessage: String?
    /// The store IDs of the saved voices, for the duplicate-name check.
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
        _referenceLanguageSelection = State(
            initialValue: ReferenceLanguageSelection(initialLanguage: configuration.initialReferenceLanguage)
        )
        _transcriptionReview = State(
            initialValue: ReferenceTranscriptionReviewState(
                initialTranscript: configuration.initialTranscript,
                readySource: configuration.initialTranscriptReadySource,
                transcriptClip: configuration.initialTranscriptClip
            )
        )
        _transcriptionEvidence = State(initialValue: nil)
    }

    private var trimmedName: String {
        name.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// In the store's own normalization (U16); in the replace-reference flow
    /// the user keeps the same identifier, and only a different saved voice's
    /// name is a collision.
    private var validationMessage: String? {
        switch SavedVoiceSheetConfiguration.nameIssue(
            for: trimmedName,
            existingVoiceIDs: existingNormalizedNames,
            replacingVoiceID: configuration.replacingVoiceID
        ) {
        case nil:
            return nil
        case .needsCharacters:
            return MacInterfaceText.savedVoiceNameNeedsCharacters
        case .exists(let storeID):
            return MacInterfaceText.savedVoiceNameExists(storeID)
        }
    }

    private var canSubmit: Bool {
        cloneConsentAcknowledged
            && !trimmedName.isEmpty
            && !audioPath.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && validationMessage == nil
            && !isSaving
            && transcriptionReview.allowsSave(transcript: transcript)
            && !requiresReferenceLanguageConfirmation
    }

    /// The Voice Cloning screen's inline one-time consent: the Settings toggle stays
    /// the persistent record; this writes the same stored key before the user
    /// names, records or reviews anything.
    private var inlineConsent: some View {
        VStack(alignment: .leading, spacing: VocelloTheme.Spacing.xs) {
            Text(MacInterfaceText.cloningConsentRequiredToSaveVoice)
                .macType(.caption)
                .foregroundStyle(MacTheme.Text.secondary)
                .fixedSize(horizontal: false, vertical: true)
            HStack(alignment: .center, spacing: MacTheme.Spacing.snug) {
                Button {
                    cloneConsentAcknowledged = true
                } label: {
                    Label(MacInterfaceText.settingsCloneConsent, systemImage: "checkmark.circle")
                }
                .buttonStyle(MacSettingsActionButtonStyle(tint: tint, prominence: .primary))
                .accessibilityIdentifier("voicesEnroll_inlineConsent")
                Text(MacInterfaceText.cloningConsentOneTime)
                    .macType(.caption)
                    .foregroundStyle(MacTheme.Text.secondary)
                    .lineLimit(2)
            }
        }
    }

    private var referenceLanguage: Qwen3SupportedLanguage {
        referenceLanguageSelection.language
    }

    private var referenceLanguageBinding: Binding<Qwen3SupportedLanguage> {
        Binding(
            get: { referenceLanguage },
            set: { referenceLanguageSelection.select($0) }
        )
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

            if !cloneConsentAcknowledged {
                inlineConsent
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
                Picker(VocelloPresentationText.referenceLanguageTitle, selection: referenceLanguageBinding) {
                    Text(VocelloPresentationText.referenceLanguagePlaceholder)
                        .tag(Qwen3SupportedLanguage.auto)
                    ForEach(Qwen3SupportedLanguage.selectableCases, id: \.self) { language in
                        Text(MacInterfaceText.languageName(language)).tag(language)
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
                    // MAC-12: a save still staging its candidate discards it
                    // instead of committing a voice the user cancelled.
                    if isSaving { saveCancellation.isCancelled = true }
                    dismiss()
                }
                .buttonStyle(.bordered)
                .disabled(isCommitting)
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
                referenceClipChanged(to: newPath)
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
            recordedClips.close()
        }
        .sheet(isPresented: $isRecordSheetPresented) {
            MacRecordVoiceSheet { url in
                recordedClips.record(url.path)
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

    /// A new clip (recorded, browsed, typed, or after Discard and re-record):
    /// the transcript of another recording is cleared with its evidence and
    /// recognition runs for this one, so Save waits for it (U15). A path that
    /// names no file yet (typing in progress) changes nothing.
    private func referenceClipChanged(to path: String) {
        let trimmedPath = path.trimmingCharacters(in: .whitespacesAndNewlines)
        guard FileManager.default.fileExists(atPath: trimmedPath) else { return }
        if transcriptionReview.referenceClipChanged(to: trimmedPath) {
            transcriptionTask?.cancel()
            transcriptionTask = nil
            transcriptionEvidence = nil
            transcript = ""
            referenceLanguageSelection.referenceClipChanged()
        }
        autoTranscribeIfNeeded(path: path)
    }

    /// The clip the field's text now describes: the chosen file, if there is one.
    private var currentClip: String? {
        let trimmedPath = audioPath.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedPath.isEmpty, FileManager.default.fileExists(atPath: trimmedPath) else { return nil }
        return trimmedPath
    }

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
                    transcriptionReview.bindTranscript(to: trimmedPath)
                    referenceLanguageSelection.applyDetectedLanguage(result.language)
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
        transcriptionReview.bindTranscript(to: currentClip)
        referenceLanguageSelection.applyDetectedLanguage(PromptLanguageDetector.detect(newValue))
    }

    private func confirmAudioOnly() {
        transcriptionTask?.cancel()
        transcriptionTask = nil
        transcript = ""
        transcriptionReview.confirmAudioOnly()
        transcriptionReview.bindTranscript(to: currentClip)
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

    /// The formats Voice Cloning imports (MAC-09): no catch-all audio type.
    private func browseForAudio() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = VoiceCloningReferenceAudioSupport.openPanelContentTypes
        if panel.runModal() == .OK, let url = panel.url {
            audioPath = url.path
        }
    }

    private func saveVoice() {
        guard validationMessage == nil else { return }

        isSaving = true
        errorMessage = nil
        // Reference types the running save keeps even after the sheet closes:
        // Cancel's flag, and the recorded clips it may still be reading.
        let cancellation = saveCancellation
        cancellation.isCancelled = false
        let clips = recordedClips
        clips.beginUse()

        Task {
            defer {
                isSaving = false
                isCommitting = false
                clips.endUse()
            }
            do {
                let candidate = try await ttsEngineStore.preparePreparedVoiceCandidate(
                    name: trimmedName,
                    audioPath: audioPath.trimmingCharacters(in: .whitespacesAndNewlines),
                    transcript: transcript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                        ? nil
                        : transcript.trimmingCharacters(in: .whitespacesAndNewlines),
                    replacingVoiceID: configuration.replacingVoiceID,
                    enrollmentMetadata: try VoiceClipTranscriber.preparedVoiceEnrollmentMetadata(
                        referenceLanguage: referenceLanguage,
                        reviewState: transcriptionReview,
                        evidence: transcriptionEvidence
                    )
                )
                // MAC-12: Cancel arrived while the candidate was being staged.
                // It is private and expires on its own, but it is discarded now.
                if cancellation.isCancelled {
                    try? await ttsEngineStore.discardPreparedVoiceCandidate(id: candidate.id)
                    return
                }
                pendingVoiceForReview = candidate.qualityWarnings.isEmpty ? nil : candidate
                guard candidate.qualityWarnings.isEmpty else { return }
                isCommitting = true
                do {
                    let savedVoice = try await ttsEngineStore.commitPreparedVoiceCandidate(id: candidate.id)
                    onComplete(savedVoice)
                    dismiss()
                } catch {
                    pendingVoiceForReview = candidate
                    errorMessage = MacInterfaceText.presentation.savedVoiceErrorMessage(error)
                }
            } catch {
                errorMessage = MacInterfaceText.presentation.savedVoiceErrorMessage(error)
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
                errorMessage = MacInterfaceText.presentation.savedVoiceErrorMessage(error)
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
                errorMessage = MacInterfaceText.presentation.savedVoiceErrorMessage(error)
            }
            isReviewDecisionInFlight = false
        }
    }

    private var reviewAlertTitle: String {
        errorMessage == nil ? MacInterfaceText.voicesReferenceOutsideRange : MacInterfaceText.savedVoiceSaveFailedTitle
    }

    private func reviewAlertMessage(for candidate: PreparedVoiceCandidate) -> String {
        errorMessage ?? MacInterfaceText.qualityWarningSummary(tokens: candidate.qualityWarnings)
    }
}

/// Cancel's request to a save that is still staging its candidate (MAC-12);
/// a reference type so the running save sees it after the sheet has closed.
@MainActor
private final class SavedVoiceSaveCancellation {
    var isCancelled = false
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
