import Foundation
import Observation
import QwenVoiceNative
import SwiftUI

struct VoiceDesignActionAlert: Identifiable {
    let id = UUID()
    let title: String
    let message: String
}

struct VoiceDesignSavedVoiceCandidate: Equatable {
    let audioPath: String
    let transcript: String
    let suggestedName: String
    let voiceDescription: String
    let emotion: String
    let text: String
    private(set) var savedVoiceName: String?

    var isSaved: Bool {
        savedVoiceName != nil
    }

    func matches(draft: VoiceDesignDraft) -> Bool {
        voiceDescription == draft.voiceDescription
            && emotion == draft.emotion
            && text == draft.text
    }

    mutating func markSaved(as voiceName: String) {
        savedVoiceName = voiceName
    }
}

@MainActor
@Observable
final class VoiceDesignCoordinator {
    var isGenerating = false
    var errorMessage: String?
    var presentedSheet: VoiceDesignPresentedSheet?
    var actionAlert: VoiceDesignActionAlert?
    var latestSavedVoiceCandidate: VoiceDesignSavedVoiceCandidate?
    @ObservationIgnored private var generationTask: Task<Void, Never>?

    func currentSavedVoiceCandidate(for draft: VoiceDesignDraft) -> VoiceDesignSavedVoiceCandidate? {
        guard let latestSavedVoiceCandidate,
              latestSavedVoiceCandidate.matches(draft: draft) else {
            return nil
        }
        return latestSavedVoiceCandidate
    }

    func presentBatch(draft: VoiceDesignDraft) {
        presentedSheet = .batch(.design(draft: draft))
    }

    func presentLongFormBatch(draft: VoiceDesignDraft) {
        presentedSheet = .batch(
            .design(
                draft: draft,
                initialText: draft.text,
                initialSegmentationMode: .longForm
            )
        )
    }

    func presentSavedVoiceSheet(for draft: VoiceDesignDraft) {
        guard let candidate = currentSavedVoiceCandidate(for: draft) else { return }
        presentedSheet = .saveVoice(
            .designResult(
                voiceDescription: candidate.voiceDescription,
                audioPath: candidate.audioPath,
                transcript: candidate.transcript
            )
        )
    }

    func handleSavedVoice(
        _ voice: Voice,
        draft: VoiceDesignDraft,
        savedVoicesViewModel: SavedVoicesViewModel,
        ttsEngineStore: TTSEngineStore
    ) {
        if var candidate = latestSavedVoiceCandidate, candidate.matches(draft: draft) {
            candidate.markSaved(as: voice.name)
            latestSavedVoiceCandidate = candidate
        }
        savedVoicesViewModel.insertOrReplace(voice)
        Task { @MainActor [weak savedVoicesViewModel, weak ttsEngineStore] in
            guard let savedVoicesViewModel, let ttsEngineStore else { return }
            await savedVoicesViewModel.refresh(using: ttsEngineStore)
        }
        actionAlert = VoiceDesignActionAlert(
            title: "Saved Voice Added",
            message: "\"\(voice.name)\" is ready in Saved Voices."
        )
    }

    func generate(
        draft: VoiceDesignDraft,
        activeModel: TTSModel?,
        isModelAvailable: Bool,
        ttsEngineStore: TTSEngineStore,
        audioPlayer: AudioPlayerViewModel,
        modelManager: ModelManagerViewModel
    ) {
        guard !isGenerating, !ttsEngineStore.hasActiveGeneration else { return }
        guard draft.hasText, draft.hasVoiceDescription, ttsEngineStore.isReady else { return }

        if let model = activeModel, !isModelAvailable {
            errorMessage = modelManager.recoveryDetail(for: model)
            return
        }

        if LongTextGenerationRouter.shouldRouteToLongFormBatch(draft.text) {
            presentLongFormBatch(draft: draft)
            return
        }

        isGenerating = true
        errorMessage = nil
        latestSavedVoiceCandidate = nil

        let text = draft.text
        let voiceDescription = draft.voiceDescription
        let emotion = draft.emotion

        generationTask = Task { @MainActor in
            var submittedGenerationID: UUID?
            defer {
                audioPlayer.setLivePreviewEstimate(nil)
                self.isGenerating = false
                self.generationTask = nil
            }
            do {
                guard let model = activeModel else {
                    self.errorMessage = "Model configuration not found"
                    return
                }

                let outputPath = makeOutputPath(subfolder: model.outputSubfolder, text: text)
                let generationRequest = Self.makeGenerationRequest(
                    draft: VoiceDesignDraft(
                        voiceDescription: voiceDescription,
                        emotion: emotion,
                        text: text
                    ),
                    model: model,
                    outputPath: outputPath
                )
                await AppGenerationTimeline.shared.recordSubmitted(
                    id: generationRequest.generationID,
                    mode: generationRequest.modeIdentifier
                )
                submittedGenerationID = generationRequest.generationID
                audioPlayer.setLivePreviewEstimate(
                    LivePreviewEstimate(text: text)
                )
                let result = try await ttsEngineStore.generate(generationRequest)
                var generation = Generation(
                    text: text,
                    mode: model.mode.rawValue,
                    modelTier: model.tier,
                    voice: voiceDescription,
                    emotion: emotion,
                    speed: nil,
                    audioPath: result.audioPath,
                    duration: result.durationSeconds,
                    createdAt: Date(),
                    seed: result.observedSamplingSeed.map { Int64(bitPattern: $0) }
                )

                GenerationPersistence.persistAndAutoplay(
                    generation,
                    result: result,
                    text: text,
                    audioPlayer: audioPlayer,
                    caller: "VoiceDesignCoordinator"
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
                self.latestSavedVoiceCandidate = VoiceDesignSavedVoiceCandidate(
                    audioPath: generation.audioPath,
                    transcript: text,
                    suggestedName: SavedVoiceNameSuggestion.designResultName(from: voiceDescription),
                    voiceDescription: voiceDescription,
                    emotion: emotion,
                    text: text
                )
            } catch is CancellationError {
                await AppGenerationTimeline.shared.recordFailed(
                    id: submittedGenerationID,
                    finishReason: .cancelled
                )
                GenerationTelemetryMerger.scheduleMerge(generationID: submittedGenerationID)
                audioPlayer.abortLivePreviewIfNeeded()
                self.errorMessage = nil
            } catch {
                await AppGenerationTimeline.shared.recordFailed(id: submittedGenerationID)
                GenerationTelemetryMerger.scheduleMerge(generationID: submittedGenerationID)
                audioPlayer.abortLivePreviewIfNeeded()
                self.errorMessage = error.localizedDescription
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

    nonisolated static func makeGenerationRequest(
        draft: VoiceDesignDraft,
        model: TTSModel,
        outputPath: String
    ) -> GenerationRequest {
        GenerationRequest(
            modelID: model.id,
            text: draft.text,
            outputPath: outputPath,
            shouldStream: true,
            streamingTitle: String(draft.text.prefix(40)),
            languageHint: draft.selectedLanguage.rawValue,
            payload: .design(
                voiceDescription: draft.voiceDescription,
                deliveryStyle: draft.emotion
            ),
            generationID: UUID(),
            seed: draft.pinnedSeed,
            variation: GenerationVariationPreference.requestValue()
        )
    }

}
