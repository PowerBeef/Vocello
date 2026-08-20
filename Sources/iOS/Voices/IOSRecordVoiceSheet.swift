import QwenVoiceCore
import SwiftUI

/// Record or import → name → enroll a **permanent, reusable** saved voice from the Voices tab.
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
    /// Called once the voice is enrolled with the confirmed (possibly empty) `transcript` and the
    /// detected reference `language` (`.auto` if undetected) to pre-set the Clone language.
    var onEnrolled: (Voice, String, Qwen3SupportedLanguage) -> Void
    var onDismiss: () -> Void

    @EnvironmentObject private var ttsEngine: TTSEngineStore
    @EnvironmentObject private var savedVoicesViewModel: SavedVoicesViewModel

    @State private var phase: Phase
    @State private var capturedURL: URL?
    @State private var suggestedName: String
    @State private var transcript: String
    @State private var detectedLanguage: Qwen3SupportedLanguage
    @State private var isNamingPresented: Bool
    @State private var enrollError: String?
    @State private var pendingVoiceForReview: PreparedVoiceCandidate?
    @State private var isReviewDecisionInFlight = false

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
    }

    var body: some View {
        ZStack {
            switch phase {
            case .recording:
                IOSRecordingOverlay(
                    onComplete: { url in
                        // The recorder deletes its temp WAV on `.onDisappear` (stopWithoutSaving),
                        // which fires the moment we switch to `.naming`. Copy it out FIRST so the
                        // file still exists when the user taps Save.
                        let stable = ReferenceClipRecordingStash.copyToStableTemp(url) ?? url
                        capturedURL = stable
                        suggestedName = ""
                        transcript = ""
                        enrollError = nil
                        phase = .naming
                        isNamingPresented = true
                        Task { await autoTranscribe(stable) }
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
        // on-device transcription (transcript stays optional either way — an empty
        // field enrolls in the audio-only x-vector conditioning mode).
        .task {
            if let materializedURL = importedReference?.materializedURL,
               transcript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                await autoTranscribe(materializedURL)
            }
        }
        .sheet(isPresented: $isNamingPresented) {
            IOSSaveVoiceSheet(
                title: importedReference == nil ? "Save this voice" : "Import voice",
                suggestedName: $suggestedName,
                transcript: $transcript,
                errorMessage: enrollError,
                clipAudioURL: capturedURL,
                onCancel: {
                    isNamingPresented = false
                    cleanupCapturedFile()
                    onDismiss()
                },
                onSave: { Task { await performEnroll() } }
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
                Button("Keep voice") {
                    commitPendingCandidate(candidate)
                }
                .accessibilityIdentifier("recordVoice_keepDespiteWarning")
            }
            Button(importedReference == nil ? "Discard and re-record" : "Discard imported voice", role: .destructive) {
                discardPendingCandidate(candidate, closesFlow: true)
            }
            .accessibilityIdentifier("recordVoice_discardOnWarning")
            Button("Cancel", role: .cancel) {
                discardPendingCandidate(candidate, closesFlow: false)
            }
                .accessibilityIdentifier("recordVoice_cancelOnWarning")
        } message: { candidate in
            Text(reviewAlertMessage(for: candidate))
        }
    }

    // MARK: - Actions

    /// On-device best-effort transcription + language detection across all Qwen languages; only
    /// fills the field/language if the user hasn't already provided one.
    private func autoTranscribe(_ url: URL) async {
        guard let result = await VoiceClipTranscriber.transcribe(url: url) else { return }
        await MainActor.run {
            if transcript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                transcript = result.text
            }
            if detectedLanguage == .auto {
                detectedLanguage = result.language
            }
        }
    }

    private func performEnroll() async {
        guard let url = capturedURL else { return }
        let name = suggestedName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else { return }
        enrollError = nil
        // Friendly duplicate pre-check (macOS SavedVoiceSheet parity): filename-stem
        // defaults make collisions likely for imports. The engine's normalized-name
        // duplicate guard remains the authoritative backstop.
        if savedVoicesViewModel.voices.contains(where: {
            $0.name.caseInsensitiveCompare(name) == .orderedSame
        }) {
            enrollError = "A saved voice named \(name) already exists. Choose another name."
            return
        }
        let trimmedTranscript = transcript.trimmingCharacters(in: .whitespacesAndNewlines)
        do {
            let candidate = try await ttsEngine.preparePreparedVoiceCandidate(
                name: name,
                audioPath: url.path,
                transcript: trimmedTranscript.isEmpty ? nil : trimmedTranscript,
                replacingVoiceID: nil
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
        isNamingPresented = false
        Task {
            await savedVoicesViewModel.refresh(using: ttsEngine)
            onEnrolled(voice, confirmed, language)
        }
    }

    private var reviewAlertTitle: String {
        enrollError == nil ? "Reference outside recommended range" : "Couldn't save voice"
    }

    private func reviewAlertMessage(for candidate: PreparedVoiceCandidate) -> String {
        enrollError ?? PreparedVoiceQualityWarning.summary(for: candidate.qualityWarnings)
    }

    private func cleanupCapturedFile() {
        // Imported references live in the shared cache and may also back an in-progress Clone
        // draft. Enrollment copies them into Saved Voices, but this flow must not invalidate
        // another consumer of the same fingerprinted cache entry.
        guard importedReference == nil else {
            capturedURL = nil
            return
        }
        if let url = capturedURL {
            try? FileManager.default.removeItem(at: url)
        }
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
