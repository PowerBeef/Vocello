import AppKit
import QwenVoiceNative
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
    /// Normalized name of an existing saved voice that this enrollment
    /// is intended to replace. The duplicate-name guard ignores this
    /// name so the user can keep the same identifier; the caller is
    /// responsible for deleting the old voice after successful save.
    /// Nil for the standard add / cloneResult / designResult flows.
    let replacingNormalizedName: String?

    init(
        title: String,
        subtitle: String,
        confirmLabel: String,
        initialName: String,
        initialAudioPath: String,
        initialTranscript: String,
        replacingNormalizedName: String? = nil
    ) {
        self.title = title
        self.subtitle = subtitle
        self.confirmLabel = confirmLabel
        self.initialName = initialName
        self.initialAudioPath = initialAudioPath
        self.initialTranscript = initialTranscript
        self.replacingNormalizedName = replacingNormalizedName
    }

    static let manualAdd = SavedVoiceSheetConfiguration(
        title: "Add Voice Sample",
        subtitle: "Save a reference clip you own or have permission to use, then use it in Voice Cloning.",
        confirmLabel: "Add Saved Voice",
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
            title: "Save to Saved Voices",
            subtitle: "Keep this clone as a reusable reference for Voice Cloning when you have permission to use it.",
            confirmLabel: "Save to Saved Voices",
            initialName: suggestedName,
            initialAudioPath: audioPath,
            initialTranscript: transcript
        )
    }

    static func designResult(
        voiceDescription: String,
        audioPath: String,
        transcript: String
    ) -> SavedVoiceSheetConfiguration {
        SavedVoiceSheetConfiguration(
            title: "Save Designed Voice",
            subtitle: "Keep this designed voice as a reusable reference for Voice Cloning when you have permission to use it.",
            confirmLabel: "Save to Saved Voices",
            initialName: SavedVoiceNameSuggestion.designResultName(from: voiceDescription),
            initialAudioPath: audioPath,
            initialTranscript: transcript
        )
    }

    /// Used by the saved-voices "Replace reference" flow. Pre-fills the
    /// existing name + transcript and leaves the audio path blank so the
    /// user has to pick a new clip. The duplicate-name guard skips the
    /// existing entry (`replacingNormalizedName`) so the user can reuse
    /// the same identifier. The caller is responsible for deleting the
    /// old voice on successful completion (see
    /// `VoicesView.handleSavedVoiceSheetCompletion`).
    static func replaceReference(
        name: String,
        transcript: String
    ) -> SavedVoiceSheetConfiguration {
        SavedVoiceSheetConfiguration(
            title: "Replace Voice Reference",
            subtitle: "Pick a longer, cleaner clip (10–20 seconds works best). The existing reference will be replaced after the new one saves successfully.",
            confirmLabel: "Replace Reference",
            initialName: name,
            initialAudioPath: "",
            initialTranscript: transcript,
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

struct SavedVoiceSheet: View {
    @Environment(\.generationPerformanceGate) private var performanceGate
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @EnvironmentObject private var ttsEngineStore: TTSEngineStore
    @Environment(\.dismiss) private var dismiss

    let configuration: SavedVoiceSheetConfiguration
    let onComplete: (Voice) -> Void

    @State private var name: String
    @State private var audioPath: String
    @State private var transcript: String
    @State private var isSaving = false
    @State private var errorMessage: String?
    @State private var existingNormalizedNames: Set<String> = []
    /// When non-nil, the just-enrolled voice has quality warnings and the
    /// user is being asked whether to keep it or delete + re-record.
    /// Driven by `MLXTTSEngine.savedReferenceQualityWarnings(forAudioAt:)`
    /// at enrollment time.
    @State private var pendingVoiceForReview: Voice?
    @State private var isRecordSheetPresented = false
    @State private var isTranscribing = false
    @State private var transcriptionTask: Task<Void, Never>?
    @State private var speechAvailability: VoiceClipTranscriber.TranscriptionAvailability = .available

    init(
        configuration: SavedVoiceSheetConfiguration,
        onComplete: @escaping (Voice) -> Void
    ) {
        self.configuration = configuration
        self.onComplete = onComplete
        _name = State(initialValue: configuration.initialName)
        _audioPath = State(initialValue: configuration.initialAudioPath)
        _transcript = State(initialValue: configuration.initialTranscript)
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
            return "Enter a name with letters or numbers."
        }

        // In the replace-reference flow the user is expected to keep the
        // same identifier; only flag an existing-name collision when the
        // name belongs to a different saved voice.
        if existingNormalizedNames.contains(normalizedName)
            && normalizedName != configuration.replacingNormalizedName {
            return "A saved voice named \"\(normalizedName)\" already exists. Choose a different name."
        }

        return nil
    }

    private var canSubmit: Bool {
        !trimmedName.isEmpty
            && !audioPath.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && validationMessage == nil
            && !isSaving
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(configuration.title)
                .font(.title2.weight(.bold))

            Text(configuration.subtitle)
                .font(.callout)
                .foregroundStyle(.secondary)

            VStack(alignment: .leading, spacing: 12) {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Name")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                    TextField("Saved voice name", text: $name)
                        .textFieldStyle(.plain)
                        .focusEffectDisabled()
                        .padding(.horizontal, 8)
                        .padding(.vertical, 6)
                        .glassTextField(radius: 8)
                        .accessibilityIdentifier("voicesEnroll_nameField")
                }

                VStack(alignment: .leading, spacing: 6) {
                    Text("Audio")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)

                    HStack {
                        TextField("Reference audio file", text: $audioPath)
                            .textFieldStyle(.plain)
                            .focusEffectDisabled()
                            .padding(.horizontal, 8)
                            .padding(.vertical, 6)
                            .glassTextField(radius: 8)
                            .accessibilityIdentifier("voicesEnroll_audioPathField")

                        Button("Browse...") {
                            browseForAudio()
                        }
                        .buttonStyle(.bordered)
                        .accessibilityIdentifier("voicesEnroll_browseButton")

                        Button {
                            isRecordSheetPresented = true
                        } label: {
                            Label("Record...", systemImage: "mic.fill")
                        }
                        .buttonStyle(.bordered)
                        .accessibilityIdentifier("voicesEnroll_recordButton")
                    }
                }

                VStack(alignment: .leading, spacing: 6) {
                    HStack(spacing: 6) {
                        Text("Transcript (recommended for reusable clones)")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(.secondary)

                        if isTranscribing {
                            ProgressView()
                                .controlSize(.mini)
                            Text("Transcribing on-device…")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .accessibilityIdentifier("voicesEnroll_transcribeStatus")
                        }
                    }

                    if let issue = speechIssueMessage {
                        HStack(spacing: 6) {
                            Image(systemName: "exclamationmark.triangle.fill")
                                .font(.caption)
                                .foregroundStyle(.orange)
                            Text(issue)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                                .accessibilityIdentifier("voicesEnroll_speechUnavailable")
                            Button(speechIssueButtonLabel) {
                                openSpeechSettings()
                            }
                            .controlSize(.small)
                            .accessibilityIdentifier("voicesEnroll_speechSettingsButton")
                        }
                    }

                    TextEditor(text: $transcript)
                        .font(.body)
                        .focusEffectDisabled()
                        .frame(minHeight: 100)
                        .padding(8)
                        #if QW_UI_LIQUID
                        .background {
                            if #available(macOS 26, *), !reduceTransparency, !performanceGate {
                                RoundedRectangle(cornerRadius: 10, style: .continuous)
                                    .fill(Color(white: 0.16))
                                    .glassEffect(.regular.tint(AppTheme.smokedGlassTint), in: .rect(cornerRadius: 10))
                            } else {
                                ZStack {
                                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                                        .fill(Color(nsColor: .textBackgroundColor))
                                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                                        .stroke(AppTheme.cardStroke.opacity(0.45), lineWidth: 1)
                                }
                            }
                        }
                        #else
                        .background(
                            RoundedRectangle(cornerRadius: 10, style: .continuous)
                                .fill(Color(nsColor: .textBackgroundColor))
                        )
                        .overlay(
                            RoundedRectangle(cornerRadius: 10, style: .continuous)
                                .stroke(AppTheme.cardStroke.opacity(0.45), lineWidth: 1)
                        )
                        #endif
                        .accessibilityIdentifier("voicesEnroll_transcriptField")

                    Text("Transcript-backed voices can reuse prepared Qwen3 clone prompts; audio-only voices remain available as a lower-guidance fallback.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }

            if let activeMessage = validationMessage ?? errorMessage {
                Text(activeMessage)
                    .foregroundStyle(.red)
                    .font(.callout)
                    .accessibilityIdentifier("voicesEnroll_errorMessage")
            }

            HStack {
                Button("Cancel") {
                    dismiss()
                }
                .keyboardShortcut(.cancelAction)
                .accessibilityIdentifier("voicesEnroll_cancelButton")

                Spacer()

                Button(configuration.confirmLabel) {
                    saveVoice()
                }
                .buttonStyle(.borderedProminent)
                .disabled(!canSubmit)
                .keyboardShortcut(.defaultAction)
                .accessibilityIdentifier("voicesEnroll_confirmButton")
            }
        }
        .padding(20)
        .frame(width: 520)
        .task {
            speechAvailability = VoiceClipTranscriber.availability()
            await loadExistingVoiceNames()
        }
        .onChange(of: name) { _, _ in
            errorMessage = nil
        }
        .onChange(of: audioPath) { _, newPath in
            autoTranscribeIfNeeded(path: newPath)
        }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            // The user may have just granted speech recognition in System
            // Settings — refresh the caption and retry the auto-fill.
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
        }
        .sheet(isPresented: $isRecordSheetPresented) {
            RecordReferenceClipSheet { url in
                audioPath = url.path
            }
        }
        .alert(
            "Reference outside recommended range",
            isPresented: Binding(
                get: { pendingVoiceForReview != nil },
                set: { if !$0 { pendingVoiceForReview = nil } }
            ),
            presenting: pendingVoiceForReview
        ) { voice in
            // Hard-block tier (>60 s) hides the "Keep voice" button so
            // the user has to discard or cancel; soft-warn tier keeps
            // all three buttons.
            if !PreparedVoiceQualityWarning.isHardBlocking(voice.qualityWarnings) {
                Button("Keep voice") {
                    acceptPendingVoice()
                }
                .accessibilityIdentifier("voicesEnroll_keepDespiteWarning")
            }
            Button("Discard and re-record", role: .destructive) {
                discardPendingVoice()
            }
            .accessibilityIdentifier("voicesEnroll_discardOnWarning")
            Button("Cancel", role: .cancel) {
                pendingVoiceForReview = nil
            }
            .accessibilityIdentifier("voicesEnroll_cancelOnWarning")
        } message: { voice in
            Text(PreparedVoiceQualityWarning.summary(for: voice.qualityWarnings))
        }
    }

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

    /// Caption shown when automatic transcription can't run — silent denial
    /// was the old behavior and left users wondering why the transcript
    /// never auto-filled.
    private var speechIssueMessage: String? {
        switch speechAvailability {
        case .available, .notDetermined:
            return nil
        case .denied:
            return "Speech recognition is off for Vocello — the transcript won't auto-fill."
        case .siriDisabled:
            return "Auto-transcription needs Siri enabled (macOS requirement) — the transcript won't auto-fill."
        }
    }

    private var speechIssueButtonLabel: String {
        speechAvailability == .siriDisabled ? "Open Siri Settings" : "Open System Settings"
    }

    private func openSpeechSettings() {
        let anchor = speechAvailability == .siriDisabled
            ? "x-apple.systempreferences:com.apple.Siri-Settings.extension"
            : "x-apple.systempreferences:com.apple.preference.security?Privacy_SpeechRecognition"
        if let url = URL(string: anchor) {
            NSWorkspace.shared.open(url)
        }
    }

    /// Best-effort on-device transcription of a freshly picked/recorded clip.
    /// Only fills the transcript if the user hasn't typed one by the time the
    /// pass finishes; never blocks enrollment (degrades to nothing on failure).
    private func autoTranscribeIfNeeded(path: String) {
        speechAvailability = VoiceClipTranscriber.availability()
        transcriptionTask?.cancel()
        isTranscribing = false

        let trimmedPath = path.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedPath.isEmpty,
              transcript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              FileManager.default.fileExists(atPath: trimmedPath) else { return }

        isTranscribing = true
        transcriptionTask = Task {
            defer { isTranscribing = false }
            guard let result = await VoiceClipTranscriber.transcribe(
                url: URL(fileURLWithPath: trimmedPath)
            ) else { return }
            guard !Task.isCancelled, audioPath == path else { return }
            if transcript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                transcript = result.text
            }
        }
    }

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
                let savedVoice = try await ttsEngineStore.enrollPreparedVoice(
                    name: trimmedName,
                    audioPath: audioPath.trimmingCharacters(in: .whitespacesAndNewlines),
                    transcript: transcript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                        ? nil
                        : transcript.trimmingCharacters(in: .whitespacesAndNewlines)
                )
                let voice = Voice(preparedVoice: savedVoice)
                await MainActor.run {
                    if voice.qualityWarnings.isEmpty {
                        onComplete(voice)
                        dismiss()
                    } else {
                        // Soft warning: keep the voice on disk, but ask the
                        // user before adding it to the active selection.
                        // "Discard" deletes the just-enrolled voice; the
                        // sheet stays open so they can pick a different
                        // reference.
                        pendingVoiceForReview = voice
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

    private func acceptPendingVoice() {
        guard let voice = pendingVoiceForReview else { return }
        pendingVoiceForReview = nil
        onComplete(voice)
        dismiss()
    }

    private func discardPendingVoice() {
        guard let voice = pendingVoiceForReview else { return }
        pendingVoiceForReview = nil
        Task {
            try? await ttsEngineStore.deletePreparedVoice(id: voice.id)
        }
    }
}
