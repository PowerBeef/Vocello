import QwenVoiceCore
import SwiftUI

/// Record → name → enroll a **permanent, reusable** saved voice from the Voices tab.
/// Recordings are auto-transcribed, reuse `IOSSaveVoiceSheet` and `enrollPreparedVoice`,
/// then hand the saved voice back to Clone mode through `onEnrolled`. iPhone deliberately
/// offers no file-import path: the reference sources are the microphone or a saved
/// Voice Design voice staged through the Clone handoff.
///
/// Presented as a `.fullScreenCover`. Phase 1 renders the recorder inline; phase 2 shows a warm
/// backdrop with the naming `.sheet` on top (so we never nest two full-screen covers).
struct IOSRecordVoiceSheet: View {
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
    @State private var pendingVoiceForReview: PreparedVoice?

    private enum Phase { case recording, naming }

    init(
        onEnrolled: @escaping (Voice, String, Qwen3SupportedLanguage) -> Void,
        onDismiss: @escaping () -> Void
    ) {
        self.onEnrolled = onEnrolled
        self.onDismiss = onDismiss

        _phase = State(initialValue: .recording)
        _capturedURL = State(initialValue: nil)
        _suggestedName = State(initialValue: "")
        _transcript = State(initialValue: "")
        _detectedLanguage = State(initialValue: .auto)
        _isNamingPresented = State(initialValue: false)
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
                    IOSModeBackdrop(tint: IOSBrandTheme.clone, intensity: .warm)
                    Color(red: 13 / 255, green: 14 / 255, blue: 18 / 255).opacity(0.70)
                        .ignoresSafeArea()
                }
                .preferredColorScheme(.dark)
            }
        }
        .sheet(isPresented: $isNamingPresented) {
            IOSSaveVoiceSheet(
                title: "Save this voice",
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
            "Reference outside recommended range",
            isPresented: Binding(
                get: { pendingVoiceForReview != nil },
                set: { if !$0 { pendingVoiceForReview = nil } }
            ),
            presenting: pendingVoiceForReview
        ) { voice in
            if !PreparedVoiceQualityWarning.isHardBlocking(voice.qualityWarnings) {
                Button("Keep voice") {
                    pendingVoiceForReview = nil
                    savedVoicesViewModel.insertOrReplace(voice)
                    cleanupCapturedFile()
                    isNamingPresented = false
                    let confirmed = transcript.trimmingCharacters(in: .whitespacesAndNewlines)
                    let language = detectedLanguage
                    Task {
                        await savedVoicesViewModel.refresh(using: ttsEngine)
                        onEnrolled(voice, confirmed, language)
                    }
                }
                .accessibilityIdentifier("recordVoice_keepDespiteWarning")
            }
            Button("Discard and re-record", role: .destructive) {
                let voiceID = voice.id
                pendingVoiceForReview = nil
                Task { try? await ttsEngine.deletePreparedVoice(id: voiceID) }
                cleanupCapturedFile()
                isNamingPresented = false
                // Back to the recorder for another take.
                phase = .recording
            }
            .accessibilityIdentifier("recordVoice_discardOnWarning")
            Button("Cancel", role: .cancel) { pendingVoiceForReview = nil }
                .accessibilityIdentifier("recordVoice_cancelOnWarning")
        } message: { voice in
            Text(PreparedVoiceQualityWarning.summary(for: voice.qualityWarnings))
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
        let trimmedTranscript = transcript.trimmingCharacters(in: .whitespacesAndNewlines)
        do {
            let voice = try await ttsEngine.enrollPreparedVoice(
                name: name,
                audioPath: url.path,
                transcript: trimmedTranscript.isEmpty ? nil : trimmedTranscript
            )
            if voice.qualityWarnings.isEmpty {
                savedVoicesViewModel.insertOrReplace(voice)
                await savedVoicesViewModel.refresh(using: ttsEngine)
                cleanupCapturedFile()
                isNamingPresented = false
                onEnrolled(voice, trimmedTranscript, detectedLanguage)
            } else {
                // Soft/hard warning: the voice is on disk; let the user confirm or re-record.
                pendingVoiceForReview = voice
            }
        } catch {
            enrollError = error.localizedDescription
        }
    }

    private func cleanupCapturedFile() {
        if let url = capturedURL {
            try? FileManager.default.removeItem(at: url)
        }
        capturedURL = nil
    }
}
