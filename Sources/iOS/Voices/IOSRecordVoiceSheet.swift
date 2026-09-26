import QwenVoiceCore
import SwiftUI

/// Record or import → name → enroll a **permanent, reusable** saved voice from Voices or
/// Studio Clone.
/// Recordings are auto-transcribed; imported clips preserve a neighboring `.txt` sidecar when
/// `LocalDocumentIO` materializes one, and are auto-transcribed when no sidecar arrived
/// (macOS `SavedVoiceSheet` parity — the transcriber decodes any AVFoundation-readable format).
/// Both sources reuse `IOSSaveVoiceSheet` and the transactional candidate lifecycle, then hand the saved voice
/// back to Clone mode through `onEnrolled`.
///
/// Presented as a `.fullScreenCover`. Phase 1 renders the recorder inline; phase 2 shows a warm
/// backdrop with the naming `.sheet` on top (so we never nest two full-screen covers).
struct IOSRecordVoiceSheet: View {
    /// A Files import already materialized inside the app sandbox. Nil starts the recorder.
    let importedReference: ImportedReferenceAudio?
    /// Called once the voice is enrolled with the confirmed (possibly empty) transcript and its
    /// separately reviewed reference language. The latter is conditioning metadata; it never
    /// selects the language of a future Clone output.
    var onEnrolled: (Voice, String, Qwen3SupportedLanguage) -> Void
    var onDismiss: () -> Void

    @EnvironmentObject private var ttsEngine: TTSEngineStore
    @EnvironmentObject private var savedVoicesViewModel: SavedVoicesViewModel
    /// PA-17: saving needs the Settings acknowledgment; the recorder names it before
    /// the take and `IOSSaveVoiceSheet` keeps Save disabled until it is on.
    @AppStorage(VoiceCloningConsentPolicy.recordedConsentDefaultsKey) private var cloneConsentAcknowledged = false

    @State private var phase: Phase
    @State private var capturedURL: URL?
    @State private var suggestedName: String
    @State private var transcript: String
    @State private var detectedLanguage: Qwen3SupportedLanguage
    @State private var isNamingPresented: Bool
    @State private var enrollError: String?
    @State private var pendingVoiceForReview: PreparedVoiceCandidate?
    @State private var isReviewDecisionInFlight = false
    /// IOS-21: one enrollment at a time; a second Save tap is ignored.
    @State private var isSaving = false
    @State private var transcriptionReview: ReferenceTranscriptionReviewState
    @State private var transcriptionEvidence: VoiceClipTranscriber.EnrollmentEvidence?
    @State private var transcriptionTask: Task<Void, Never>?
    /// MAC-25 on the iPhone: the stash copies this flow recorded. They go when the
    /// flow closes, or when a save still reading one ends; the private candidate
    /// holds its own copy.
    @State private var recordedClips = ReferenceClipStashTracker { path in
        ReferenceClipRecordingStash.discard(path)
        // A clip whose stash copy failed is the recorder's own capture.
        ReferenceClipRecordingStash.discard(path, in: ReferenceClipRecordingStash.captureDirectory)
    }

    private enum Phase { case recording, naming }

    init(
        importedReference: ImportedReferenceAudio? = nil,
        onEnrolled: @escaping (Voice, String, Qwen3SupportedLanguage) -> Void,
        onDismiss: @escaping () -> Void
    ) {
        self.importedReference = importedReference
        self.onEnrolled = onEnrolled
        self.onDismiss = onDismiss

        let importedTranscript = Self.transcript(from: importedReference)
        _phase = State(initialValue: importedReference == nil ? .recording : .naming)
        _capturedURL = State(initialValue: importedReference?.materializedURL)
        _suggestedName = State(initialValue: Self.suggestedName(from: importedReference))
        _transcript = State(initialValue: importedTranscript)
        _detectedLanguage = State(
            initialValue: importedTranscript.isEmpty
                ? .auto
                : PromptLanguageDetector.detect(importedTranscript)
        )
        _isNamingPresented = State(initialValue: importedReference != nil)
        _enrollError = State(initialValue: nil)
        _pendingVoiceForReview = State(initialValue: nil)
        _transcriptionReview = State(
            initialValue: ReferenceTranscriptionReviewState(
                initialTranscript: importedTranscript
            )
        )
        _transcriptionTask = State(initialValue: nil)
        _transcriptionEvidence = State(initialValue: nil)
    }

    var body: some View {
        ZStack {
            switch phase {
            case .recording:
                IOSRecordingOverlay(
                    notice: cloneConsentAcknowledged
                        ? nil
                        : IOSAppLanguage.shared.presentation.cloningConsentRequiredToSaveVoice,
                    onComplete: { url in
                        // Copy the capture into the stash so the file the user
                        // reviews and saves is this flow's own, then remove the
                        // capture: the overlay keeps a handed-off clip on
                        // `.onDisappear`, so nothing else would delete it.
                        let stable = ReferenceClipRecordingStash.copyToStableTemp(url) ?? url
                        if stable != url {
                            ReferenceClipRecordingStash.discard(
                                url.path,
                                in: ReferenceClipRecordingStash.captureDirectory
                            )
                        }
                        recordedClips.record(stable.path)
                        capturedURL = stable
                        suggestedName = ""
                        transcript = ""
                        transcriptionReview = ReferenceTranscriptionReviewState(
                            initialTranscript: ""
                        )
                        enrollError = nil
                        phase = .naming
                        isNamingPresented = true
                        startAutomaticTranscription(stable)
                    },
                    onCancel: { onDismiss() }
                )
            case .naming:
                ZStack {
                    IOSModeBackdrop(tint: Theme.Brand.modeClone, intensity: .warm)
                    Color(red: 13 / 255, green: 14 / 255, blue: 18 / 255).opacity(0.70)
                        .ignoresSafeArea()
                }
                .preferredColorScheme(.dark)
            }
        }
        // Imported clips with no `.txt` sidecar still get the recorder's best-effort
        // on-device transcription. If recognition cannot provide text, the user must
        // explicitly confirm audio-only enrollment before Save becomes available.
        .task {
            if let materializedURL = importedReference?.materializedURL,
               transcript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                startAutomaticTranscription(materializedURL)
            }
        }
        .sheet(isPresented: $isNamingPresented) {
            IOSSaveVoiceSheet(
                title: importedReference == nil ? IOSInterfaceText.saveThisVoice : IOSInterfaceText.importVoice,
                suggestedName: $suggestedName,
                transcript: $transcript,
                transcriptionReview: transcriptionReview,
                referenceLanguage: $detectedLanguage,
                requiresReferenceLanguageConfirmation: requiresReferenceLanguageConfirmation,
                errorMessage: enrollError,
                // A save or a Keep/Discard decision in flight holds the sheet
                // open: Cancel would otherwise delete the clip under the save
                // and close a flow that still enrolls the voice.
                isSaving: isSaving || isReviewDecisionInFlight,
                clipAudioURL: capturedURL,
                onTranscriptEdited: handleTranscriptEdit,
                onUseAudioOnly: confirmAudioOnly,
                onCancel: {
                    guard !isSaving, !isReviewDecisionInFlight else { return }
                    cancelTranscription()
                    isNamingPresented = false
                    cleanupCapturedFile()
                    recordedClips.close()
                    onDismiss()
                },
                onSave: {
                    // Claimed synchronously at the tap, before the task runs.
                    guard !isSaving else { return }
                    isSaving = true
                    Task {
                        await performEnroll()
                        isSaving = false
                    }
                }
            )
        }
        .alert(
            reviewAlertTitle,
            isPresented: Binding(
                get: { pendingVoiceForReview != nil && !isReviewDecisionInFlight },
                set: { isPresented in
                    if !isPresented,
                       !isReviewDecisionInFlight,
                       let candidate = pendingVoiceForReview {
                        discardPendingCandidate(candidate, closesFlow: false)
                    }
                }
            ),
            presenting: pendingVoiceForReview
        ) { candidate in
            if !PreparedVoiceQualityWarning.isHardBlocking(candidate.qualityWarnings) {
                Button(IOSInterfaceText.keepVoice) {
                    commitPendingCandidate(candidate)
                }
                .accessibilityIdentifier("recordVoice_keepDespiteWarning")
            }
            Button(importedReference == nil ? IOSInterfaceText.discardRecord : IOSInterfaceText.discardImport, role: .destructive) {
                discardPendingCandidate(candidate, closesFlow: true)
            }
            .accessibilityIdentifier("recordVoice_discardOnWarning")
            Button(IOSInterfaceText.cancel, role: .cancel) {
                discardPendingCandidate(candidate, closesFlow: false)
            }
                .accessibilityIdentifier("recordVoice_cancelOnWarning")
        } message: { candidate in
            Text(reviewAlertMessage(for: candidate))
        }
        .onDisappear {
            cancelTranscription()
            // However the flow closes (a host dismissal included), its clips go
            // once no save still reads them.
            recordedClips.close()
        }
    }

    // MARK: - Actions

    /// Starts the one existing on-device transcriber and binds its result to an operation
    /// generation. Cancellation is cooperative, so the generation check is the final authority.
    private func startAutomaticTranscription(_ url: URL) {
        transcriptionTask?.cancel()
        let generation = transcriptionReview.beginAutomaticTranscription()
        transcriptionTask = Task { @MainActor in
            let result = await VoiceClipTranscriber.enrollmentResult(url: url)
            guard !Task.isCancelled else { return }
            transcriptionEvidence = result.evidence

            if let recognizedText = result.text {
                let applied = transcriptionReview.acceptAutomaticTranscript(
                    recognizedText,
                    generation: generation,
                    currentTranscript: transcript
                )
                if applied {
                    transcript = recognizedText
                    if detectedLanguage == .auto {
                        detectedLanguage = result.language
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

    private func handleTranscriptEdit(_ newValue: String) {
        transcriptionTask?.cancel()
        transcriptionTask = nil
        transcriptionReview.userEditedTranscript(newValue)
        if detectedLanguage == .auto {
            detectedLanguage = PromptLanguageDetector.detect(newValue)
        }
    }

    private func confirmAudioOnly() {
        transcriptionTask?.cancel()
        transcriptionTask = nil
        transcript = ""
        transcriptionReview.confirmAudioOnly()
    }

    private func cancelTranscription() {
        transcriptionTask?.cancel()
        transcriptionTask = nil
        transcriptionReview.invalidate()
    }

    private var requiresReferenceLanguageConfirmation: Bool {
        !transcript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && detectedLanguage == .auto
    }

    private func performEnroll() async {
        guard let url = capturedURL else { return }
        let name = suggestedName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else { return }
        guard transcriptionReview.allowsSave(transcript: transcript) else { return }
        enrollError = nil
        // Friendly duplicate pre-check (macOS SavedVoiceSheet parity): filename-stem
        // defaults make collisions likely for imports. The engine's normalized-name
        // duplicate guard remains the authoritative backstop.
        if savedVoicesViewModel.voices.contains(where: {
            $0.name.caseInsensitiveCompare(name) == .orderedSame
        }) {
            enrollError = IOSInterfaceText.duplicateVoice(name)
            return
        }
        let trimmedTranscript = transcript.trimmingCharacters(in: .whitespacesAndNewlines)
        // The candidate copies the clip; until then the clip must outlive a close.
        recordedClips.beginUse()
        defer { recordedClips.endUse() }
        do {
            let candidate = try await ttsEngine.preparePreparedVoiceCandidate(
                name: name,
                audioPath: url.path,
                transcript: trimmedTranscript.isEmpty ? nil : trimmedTranscript,
                replacingVoiceID: nil,
                enrollmentMetadata: try VoiceClipTranscriber.preparedVoiceEnrollmentMetadata(
                    referenceLanguage: detectedLanguage,
                    reviewState: transcriptionReview,
                    evidence: transcriptionEvidence
                )
            )
            if candidate.qualityWarnings.isEmpty {
                do {
                    let voice = try await ttsEngine.commitPreparedVoiceCandidate(id: candidate.id)
                    completeEnrollment(voice)
                } catch {
                    pendingVoiceForReview = candidate
                    enrollError = error.localizedDescription
                }
            } else {
                // Soft/hard warnings remain private candidates until Keep.
                pendingVoiceForReview = candidate
            }
        } catch {
            enrollError = error.localizedDescription
        }
    }

    private func commitPendingCandidate(_ candidate: PreparedVoiceCandidate) {
        guard !isReviewDecisionInFlight else { return }
        isReviewDecisionInFlight = true
        Task {
            do {
                let voice = try await ttsEngine.commitPreparedVoiceCandidate(id: candidate.id)
                pendingVoiceForReview = nil
                isReviewDecisionInFlight = false
                completeEnrollment(voice)
            } catch {
                enrollError = error.localizedDescription
                isReviewDecisionInFlight = false
            }
        }
    }

    private func discardPendingCandidate(
        _ candidate: PreparedVoiceCandidate,
        closesFlow: Bool
    ) {
        guard !isReviewDecisionInFlight else { return }
        isReviewDecisionInFlight = true
        Task {
            do {
                try await ttsEngine.discardPreparedVoiceCandidate(id: candidate.id)
                pendingVoiceForReview = nil
                isReviewDecisionInFlight = false
                guard closesFlow else { return }
                cleanupCapturedFile()
                isNamingPresented = false
                if importedReference == nil {
                    phase = .recording
                } else {
                    onDismiss()
                }
            } catch {
                enrollError = error.localizedDescription
                isReviewDecisionInFlight = false
            }
        }
    }

    private func completeEnrollment(_ voice: PreparedVoice) {
        let confirmed = transcript.trimmingCharacters(in: .whitespacesAndNewlines)
        let language = detectedLanguage
        savedVoicesViewModel.insertOrReplace(voice)
        cleanupCapturedFile()
        recordedClips.close()
        isNamingPresented = false
        Task {
            await savedVoicesViewModel.refresh(using: ttsEngine)
            onEnrolled(voice, confirmed, language)
        }
    }

    private var reviewAlertTitle: String {
        enrollError == nil ? IOSInterfaceText.referenceRange : IOSInterfaceText.saveVoiceFailed
    }

    private func reviewAlertMessage(for candidate: PreparedVoiceCandidate) -> String {
        enrollError ?? IOSInterfaceText.qualitySummary(candidate.qualityWarnings)
    }

    private func cleanupCapturedFile() {
        // Imported references live in the shared cache and may also back an in-progress Clone
        // draft. Enrollment copies them into Saved Voices, but this flow must not invalidate
        // another consumer of the same fingerprinted cache entry. A recording is this flow's
        // own stash copy: `recordedClips` removes it when the flow closes, never under a
        // save that is still copying it.
        capturedURL = nil
    }

    private static func suggestedName(from importedReference: ImportedReferenceAudio?) -> String {
        guard let importedReference else { return "" }
        return importedReference.originalURL.deletingPathExtension().lastPathComponent
    }

    private static func transcript(from importedReference: ImportedReferenceAudio?) -> String {
        guard let sidecarURL = importedReference?.transcriptSidecarURL,
              let contents = try? String(contentsOf: sidecarURL, encoding: .utf8)
        else { return "" }
        return contents.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
