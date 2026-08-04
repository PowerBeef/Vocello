import AppKit
import Foundation
import Observation
import QwenVoiceNative
import SwiftUI
import UniformTypeIdentifiers

/// Defensive errors thrown from inside the generate(...) Task body
/// when an invariant the sync prefix already validated turns out
/// not to hold. Routed through the existing catch path so the
/// `isGenerating = false` reset stays at the single Task exit point
/// (preventing the start-of-gen flicker bug fixed in the May 2026
/// pass).
enum VoiceCloningCoordinatorError: Error {
    case requestConstructionFailed
}

@MainActor
@Observable
final class VoiceCloningCoordinator {
    var isGenerating = false
    var errorMessage: String?
    var transcriptLoadError: String?
    var hydratedSavedVoiceID: String?
    var isDragOver = false
    var presentedSheet: VoiceCloningPresentedSheet?
    /// Non-nil when auto-transcription of a fresh reference was skipped
    /// because speech recognition is unavailable (denied, or the macOS Siri
    /// gate). Drives a hint near the transcript field; cleared once a
    /// transcript exists or transcription becomes available again.
    var transcriptionUnavailableMessage: String?
    @ObservationIgnored private var generationTask: Task<Void, Never>?
    @ObservationIgnored private var transcriptionTask: Task<Void, Never>?

    func presentBatch(draft: VoiceCloningDraft) {
        presentedSheet = .batch(.clone(draft: draft))
    }

    func presentLongFormBatch(draft: VoiceCloningDraft) {
        presentedSheet = .batch(
            .clone(
                draft: draft,
                initialText: draft.text,
                initialSegmentationMode: .longForm
            )
        )
    }

    func handleAppear(
        draft: Binding<VoiceCloningDraft>,
        pendingSavedVoiceHandoff: Binding<PendingVoiceCloningHandoff?>
    ) {
        consumePendingSavedVoiceHandoffIfNeeded(
            draft: draft,
            pendingSavedVoiceHandoff: pendingSavedVoiceHandoff
        )
    }

    func consumePendingSavedVoiceHandoffIfNeeded(
        draft: Binding<VoiceCloningDraft>,
        pendingSavedVoiceHandoff: Binding<PendingVoiceCloningHandoff?>
    ) {
        guard let handoff = pendingSavedVoiceHandoff.wrappedValue else { return }
        applyPendingSavedVoiceHandoff(handoff, draft: draft)
        pendingSavedVoiceHandoff.wrappedValue = nil
    }

    func generate(
        draft: Binding<VoiceCloningDraft>,
        cloneModel: TTSModel?,
        isModelAvailable: Bool,
        clonePrimingRequestKey: String?,
        selectedVoice: Voice?,
        ttsEngineStore: TTSEngineStore,
        audioPlayer: AudioPlayerViewModel,
        modelManager: ModelManagerViewModel
    ) {
        // ALL precondition checks live in this sync prefix BEFORE
        // `isGenerating = true` flips. Inside the Task body we only
        // flip `isGenerating = false` on real outcomes (success,
        // error, cancellation) — never on precondition failures.
        // Otherwise SwiftUI sees `isGenerating` go true→false in
        // adjacent runloop ticks at the start of generation, which
        // causes the Script-card trailing badge AND the readiness
        // note to flicker through "Generating" before snapping back
        // to "Ready" while the engine quietly proceeded. Custom
        // Voice and Voice Design already follow this discipline; this
        // aligns Voice Cloning with them.
        guard !isGenerating, !ttsEngineStore.hasActiveGeneration else { return }
        guard draft.wrappedValue.hasText else { return }
        guard ttsEngineStore.isReady else { return }

        if let model = cloneModel, !isModelAvailable {
            errorMessage = modelManager.recoveryDetail(for: model)
            return
        }

        if LongTextGenerationRouter.shouldRouteToLongFormBatch(draft.wrappedValue.text) {
            ensureSelectedSavedVoiceHydratedIfNeeded(
                draft: draft,
                selectedVoice: selectedVoice
            )
            let currentDraft = draft.wrappedValue
            guard currentDraft.referenceAudioPath != nil else {
                errorMessage = "Select a reference audio file before generating."
                return
            }
            presentLongFormBatch(draft: currentDraft)
            return
        }

        // Hydrate first so the draft reflects the selected saved voice
        // BEFORE we read currentDraft.referenceAudioPath etc. Sync call;
        // applies the saved voice's wavPath + transcript to the draft
        // unless already hydrated (idempotent).
        ensureSelectedSavedVoiceHydratedIfNeeded(
            draft: draft,
            selectedVoice: selectedVoice
        )

        guard let model = cloneModel else {
            errorMessage = "Model configuration not found"
            return
        }

        let currentDraft = draft.wrappedValue
        guard currentDraft.hasText else {
            // Re-check after hydration; should not normally fire.
            return
        }
        guard let refPath = currentDraft.referenceAudioPath else {
            errorMessage = "Select a reference audio file before generating."
            return
        }

        // All preconditions satisfied; flip isGenerating true exactly once.
        isGenerating = true
        errorMessage = nil

        generationTask = Task { @MainActor in
            var submittedGenerationID: UUID?
            defer {
                audioPlayer.setLivePreviewEstimate(nil)
                isGenerating = false
                generationTask = nil
            }
            do {
                let primedReferenceMatches = ttsEngineStore.clonePreparationState.isPrimed
                    && ttsEngineStore.clonePreparationState.key == clonePrimingRequestKey

                if !primedReferenceMatches {
                    do {
                        try await ttsEngineStore.ensureCloneReferencePrimed(
                            modelID: model.id,
                            reference: CloneReference(
                                audioPath: refPath,
                                transcript: currentDraft.trimmedReferenceTranscript,
                                preparedVoiceID: currentDraft.selectedSavedVoiceID
                            )
                        )
                    } catch {
                        if DebugMode.isEnabled {
                            print("[Performance][VoiceCloningCoordinator] clone priming degraded: \(error.localizedDescription)")
                        }
                    }
                }

                let outputPath = makeOutputPath(
                    subfolder: model.outputSubfolder,
                    text: currentDraft.text
                )
                // Sync prefix already validated text + referenceAudioPath
                // so makeGenerationRequest can never return nil here. If
                // it does (defensive only) throw and let the catch reset
                // isGenerating cleanly via the single exit point below —
                // never flip isGenerating false inline.
                guard let generationRequest = Self.makeGenerationRequest(
                    draft: currentDraft,
                    model: model,
                    outputPath: outputPath
                ) else {
                    throw VoiceCloningCoordinatorError.requestConstructionFailed
                }
                await AppGenerationTimeline.shared.recordSubmitted(
                    id: generationRequest.generationID,
                    mode: generationRequest.modeIdentifier
                )
                submittedGenerationID = generationRequest.generationID
                audioPlayer.setLivePreviewEstimate(
                    LivePreviewEstimate(text: currentDraft.text)
                )
                let result = try await ttsEngineStore.generate(generationRequest)
                let voiceName = selectedVoice?.name
                    ?? URL(fileURLWithPath: refPath).deletingPathExtension().lastPathComponent
                var generation = Generation(
                    text: currentDraft.text,
                    mode: model.mode.rawValue,
                    modelTier: model.tier,
                    voice: voiceName,
                    emotion: nil,
                    speed: nil,
                    audioPath: result.audioPath,
                    duration: result.durationSeconds,
                    createdAt: Date(),
                    seed: result.observedSamplingSeed.map { Int64(bitPattern: $0) }
                )
                GenerationPersistence.persistAndAutoplay(
                    generation,
                    result: result,
                    text: currentDraft.text,
                    audioPlayer: audioPlayer,
                    caller: "VoiceCloningCoordinator"
                )
                // Finalize app telemetry only after the synchronous playback
                // handoff has recorded the real scheduled-playback milestone.
                await AppGenerationTimeline.shared.recordCompleted(
                    id: generationRequest.generationID,
                    mode: generationRequest.modeIdentifier,
                    usedStreaming: result.usedStreaming,
                    finishReason: result.finishReason?.rawValue,
                    summary: result.telemetrySummary
                )
                GenerationTelemetryMerger.scheduleMerge(generationID: generationRequest.generationID)
            } catch is CancellationError {
                await AppGenerationTimeline.shared.recordFailed(
                    id: submittedGenerationID,
                    finishReason: .cancelled
                )
                GenerationTelemetryMerger.scheduleMerge(generationID: submittedGenerationID)
                audioPlayer.abortLivePreviewIfNeeded()
                errorMessage = nil
            } catch {
                await AppGenerationTimeline.shared.recordFailed(id: submittedGenerationID)
                GenerationTelemetryMerger.scheduleMerge(generationID: submittedGenerationID)
                audioPlayer.abortLivePreviewIfNeeded()
                errorMessage = error.localizedDescription
            }
        }
    }

    func cancelGeneration(
        ttsEngineStore: TTSEngineStore,
        audioPlayer: AudioPlayerViewModel
    ) {
        guard isGenerating || generationTask != nil else { return }
        // Reset state synchronously (already on MainActor) — routing it
        // through a second Task raced the generation task's own defer and
        // could null a FRESH generation's handle if the user re-generated
        // quickly, leaving its cancel button inert.
        generationTask?.cancel()
        generationTask = nil
        isGenerating = false
        errorMessage = nil
        audioPlayer.abortLivePreviewIfNeeded()
        Task { @MainActor [weak ttsEngineStore] in
            try? await ttsEngineStore?.cancelActiveGeneration()
        }
    }

    /// Cancel any in-flight auto-transcription (called from onDisappear so a
    /// navigated-away view never leaves SFSpeechRecognizer work running).
    func cancelPendingTranscription() {
        transcriptionTask?.cancel()
        transcriptionTask = nil
    }

    static func makeGenerationRequest(
        draft: VoiceCloningDraft,
        model: TTSModel,
        outputPath: String
    ) -> GenerationRequest? {
        guard let referenceAudioPath = draft.referenceAudioPath else { return nil }
        guard draft.hasText else { return nil }
        return GenerationRequest(
            modelID: model.id,
            text: draft.text,
            outputPath: outputPath,
            shouldStream: true,
            streamingTitle: String(draft.text.prefix(40)),
            languageHint: draft.selectedLanguage.rawValue,
            payload: .clone(
                reference: CloneReference(
                    audioPath: referenceAudioPath,
                    transcript: draft.trimmedReferenceTranscript,
                    preparedVoiceID: draft.selectedSavedVoiceID
                )
            ),
            generationID: UUID(),
            seed: draft.pinnedSeed,
            variation: GenerationVariationPreference.requestValue()
        )
    }

    func syncCloneReferencePriming(
        draft: VoiceCloningDraft,
        cloneModel: TTSModel?,
        isModelAvailable: Bool,
        clonePrimingRequestKey: String?,
        ttsEngineStore: TTSEngineStore
    ) async {
        // Benchmark cold-start accuracy: when proactive warmup is suppressed, skip
        // proactive clone priming too so the cold Clone generation does (and records)
        // its own model load + clone conditioning instead of being pre-primed.
        guard !MacGenerationWarmupCoordinator.isSuppressed else { return }
        guard !isGenerating, !ttsEngineStore.hasActiveGeneration else { return }
        guard let model = cloneModel,
              isModelAvailable,
              let refPath = draft.referenceAudioPath,
              let clonePrimingRequestKey else {
            await ttsEngineStore.cancelClonePreparationIfNeeded()
            return
        }

        if let selectedSavedVoiceID = draft.selectedSavedVoiceID,
           hydratedSavedVoiceID != selectedSavedVoiceID,
           transcriptLoadError == nil {
            await ttsEngineStore.cancelClonePreparationIfNeeded()
            return
        }

        do {
            try await ttsEngineStore.ensureCloneReferencePrimed(
                modelID: model.id,
                reference: CloneReference(
                    audioPath: refPath,
                    transcript: draft.trimmedReferenceTranscript,
                    preparedVoiceID: draft.selectedSavedVoiceID
                )
            )
        } catch {
            if DebugMode.isEnabled {
                print("[Performance][VoiceCloningCoordinator] clone priming failed key=\(clonePrimingRequestKey) error=\(error.localizedDescription)")
            }
        }
    }

    func selectSavedVoice(
        _ voice: Voice,
        draft: Binding<VoiceCloningDraft>
    ) {
        applySavedVoice(voice, draft: draft)
    }

    func ensureSelectedSavedVoiceHydratedIfNeeded(
        draft: Binding<VoiceCloningDraft>,
        selectedVoice: Voice?
    ) {
        guard let selectedVoice else { return }
        guard draft.wrappedValue.selectedSavedVoiceID == selectedVoice.id else { return }
        guard hydratedSavedVoiceID != selectedVoice.id else { return }
        guard transcriptLoadError == nil else { return }
        applySavedVoice(selectedVoice, draft: draft)
    }

    func clearReference(draft: Binding<VoiceCloningDraft>) {
        draft.wrappedValue.clearReference()
        transcriptLoadError = nil
        hydratedSavedVoiceID = nil
    }

    func syncSavedVoiceSelectionState(
        draft: Binding<VoiceCloningDraft>,
        selectedVoice: Voice?,
        savedVoicesViewModel: SavedVoicesViewModel
    ) {
        if draft.wrappedValue.selectedSavedVoiceID != nil,
           selectedVoice == nil,
           (savedVoicesViewModel.isLoading || savedVoicesViewModel.loadError != nil) {
            return
        }

        switch SavedVoiceCloneHydration.action(
            draft: draft.wrappedValue,
            voice: selectedVoice,
            hydratedVoiceID: hydratedSavedVoiceID,
            transcriptLoadError: transcriptLoadError
        ) {
        case .none:
            break
        case .acceptCurrentDraft:
            hydratedSavedVoiceID = selectedVoice?.id
        case .applyFromDisk:
            if let selectedVoice {
                applySavedVoice(selectedVoice, draft: draft)
            }
        case .clearStaleSelection:
            clearReference(draft: draft)
        }
    }

    func handleDrop(
        _ providers: [NSItemProvider],
        draft: Binding<VoiceCloningDraft>
    ) -> Bool {
        guard let provider = providers.first else { return false }
        let allowedExtensions = VoiceCloningReferenceAudioSupport.allowedFileExtensions
        // NSItemProvider resolves on its own queue and can take seconds on
        // slow volumes — [weak self] so an in-flight drop never pins this
        // coordinator (and its tasks) past the view's life.
        provider.loadItem(forTypeIdentifier: UTType.fileURL.identifier, options: nil) { [weak self] data, _ in
            guard let data = data as? Data,
                  let url = URL(dataRepresentation: data, relativeTo: nil) else { return }
            let ext = url.pathExtension.lowercased()
            let path = url.path
            guard allowedExtensions.contains(ext) else {
                Task { @MainActor [weak self] in
                    self?.errorMessage = "Unsupported file type '.\(ext)'. Drop an audio file (\(VoiceCloningReferenceAudioSupport.supportedFormatDescription))."
                }
                return
            }

            Task { @MainActor [weak self] in
                self?.replaceReference(with: path, draft: draft)
            }
        }
        return true
    }

    func browseForAudio(draft: Binding<VoiceCloningDraft>) {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = VoiceCloningReferenceAudioSupport.openPanelContentTypes
        panel.allowsMultipleSelection = false
        if panel.runModal() == .OK, let url = panel.url {
            replaceReference(with: url.path, draft: draft)
        }
    }

    private func applyPendingSavedVoiceHandoff(
        _ handoff: PendingVoiceCloningHandoff,
        draft: Binding<VoiceCloningDraft>
    ) {
        draft.wrappedValue.applySavedVoiceSelection(
            id: handoff.savedVoiceID,
            wavPath: handoff.wavPath,
            transcript: handoff.transcript
        )
        transcriptLoadError = handoff.transcriptLoadError
        hydratedSavedVoiceID = handoff.savedVoiceID
    }

    private func applySavedVoice(
        _ voice: Voice,
        draft: Binding<VoiceCloningDraft>
    ) {
        do {
            let transcript = try SavedVoiceCloneHydration.loadTranscript(for: voice)
            draft.wrappedValue.applySavedVoice(voice, transcript: transcript)
            transcriptLoadError = nil
        } catch {
            draft.wrappedValue.applySavedVoice(voice, transcript: "")
            transcriptLoadError = "Couldn't load the saved transcript for \"\(voice.name)\". You can still clone from the audio file alone."
        }
        hydratedSavedVoiceID = voice.id
    }

    func replaceReference(
        with path: String,
        draft: Binding<VoiceCloningDraft>
    ) {
        // A transcript hydrated from a saved voice belongs to the OLD audio —
        // keep it and the clone would be guided by mismatched text. Clear it
        // so auto-transcription can fill the one matching the new clip.
        // Hand-typed transcripts (no saved-voice selection) are preserved.
        if draft.wrappedValue.selectedSavedVoiceID != nil {
            draft.wrappedValue.referenceTranscript = ""
        }
        draft.wrappedValue.referenceAudioPath = path
        draft.wrappedValue.selectedSavedVoiceID = nil
        transcriptLoadError = nil
        hydratedSavedVoiceID = nil
        autoTranscribeReference(path: path, draft: draft)
    }

    /// Best-effort on-device transcription of a freshly imported/recorded
    /// reference clip (saved-voice selection already hydrates the sidecar
    /// transcript, so this only runs on the fresh-file path). Fills the
    /// transcript only if it's still empty when the pass finishes, and
    /// auto-sets the language only from `.auto` — never overwriting user
    /// input. Mirrors the iOS record→enroll contract (`onEnrolled`).
    private func autoTranscribeReference(
        path: String,
        draft: Binding<VoiceCloningDraft>
    ) {
        transcriptionTask?.cancel()
        let trimmed = draft.wrappedValue.referenceTranscript
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.isEmpty else { return }
        switch VoiceClipTranscriber.availability() {
        case .denied:
            transcriptionUnavailableMessage =
                "Speech recognition is off for Vocello — type the transcript or enable it in System Settings → Privacy & Security."
            return
        case .siriDisabled:
            transcriptionUnavailableMessage =
                "Auto-transcription needs Siri enabled (macOS requirement) — type the transcript or enable Siri in System Settings."
            return
        case .available, .notDetermined:
            transcriptionUnavailableMessage = nil
        }
        transcriptionTask = Task { @MainActor [weak self] in
            guard self != nil else { return }
            guard let result = await VoiceClipTranscriber.transcribe(
                url: URL(fileURLWithPath: path)
            ) else { return }
            guard !Task.isCancelled else { return }
            // The reference may have changed while transcribing.
            guard draft.wrappedValue.referenceAudioPath == path else { return }
            if draft.wrappedValue.referenceTranscript
                .trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                draft.wrappedValue.referenceTranscript = result.text
            }
            if draft.wrappedValue.selectedLanguage == .auto, result.language != .auto {
                draft.wrappedValue.selectedLanguage = result.language
            }
        }
    }

    /// Re-evaluate the transcription hint after the user returns from System
    /// Settings (and retry the auto-fill when access was just granted).
    func refreshTranscriptionAvailability(draft: Binding<VoiceCloningDraft>) {
        guard transcriptionUnavailableMessage != nil else { return }
        switch VoiceClipTranscriber.availability() {
        case .available, .notDetermined:
            transcriptionUnavailableMessage = nil
            if let path = draft.wrappedValue.referenceAudioPath {
                autoTranscribeReference(path: path, draft: draft)
            }
        case .denied, .siriDisabled:
            break
        }
    }
}
