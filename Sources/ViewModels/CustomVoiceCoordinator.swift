import Foundation
import Observation
import QwenVoiceCore
import QwenVoiceNative
import SwiftUI

@MainActor
@Observable
final class CustomVoiceCoordinator {
    var isGenerating = false
    var errorMessage: String?
    var presentedSheet: CustomVoicePresentedSheet?
    @ObservationIgnored private var generationTask: Task<Void, Never>?

    func presentBatch(draft: CustomVoiceDraft) {
        presentedSheet = .batch(.custom(draft: draft))
    }

    func presentLongFormBatch(draft: CustomVoiceDraft) {
        presentedSheet = .batch(
            .custom(
                draft: draft,
                initialText: draft.text,
                initialSegmentationMode: .longForm
            )
        )
    }

    func generate(
        draft: CustomVoiceDraft,
        activeModel: TTSModel?,
        isModelAvailable: Bool,
        ttsEngineStore: TTSEngineStore,
        audioPlayer: AudioPlayerViewModel,
        modelManager: ModelManagerViewModel
    ) {
        guard !isGenerating, !ttsEngineStore.hasActiveGeneration else { return }
        guard draft.hasText, ttsEngineStore.isReady else { return }

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

                let outputPath = makeOutputPath(subfolder: model.outputSubfolder, text: draft.text)
                let generationRequest = Self.makeGenerationRequest(
                    draft: draft,
                    model: model,
                    outputPath: outputPath
                )
                await AppGenerationTimeline.shared.recordSubmitted(
                    id: generationRequest.generationID,
                    mode: generationRequest.modeIdentifier
                )
                submittedGenerationID = generationRequest.generationID
                audioPlayer.setLivePreviewEstimate(
                    LivePreviewEstimate(text: draft.text)
                )
                let result = try await ttsEngineStore.generate(generationRequest)
                var generation = Generation(
                    text: draft.text,
                    mode: model.mode.rawValue,
                    modelTier: model.tier,
                    voice: draft.selectedSpeaker,
                    emotion: draft.emotion,
                    speed: nil,
                    audioPath: result.audioPath,
                    duration: result.durationSeconds,
                    createdAt: Date(),
                    seed: result.observedSamplingSeed.map { Int64(bitPattern: $0) }
                )

                GenerationPersistence.persistAndAutoplay(
                    generation,
                    result: result,
                    text: draft.text,
                    audioPlayer: audioPlayer,
                    caller: "CustomVoiceCoordinator"
                )
                // Keep the frontend timeline open through the genuine player
                // handoff. Short clips can complete before live playback has
                // started, in which case final-file autoplay is the first real
                // playback-scheduled event.
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
        draft: CustomVoiceDraft,
        model: TTSModel,
        outputPath: String
    ) -> GenerationRequest {
        GenerationRequest(
            modelID: model.id,
            text: draft.text,
            outputPath: outputPath,
            shouldStream: true,
            streamingInterval: QwenVoiceCore.GenerationSemantics.appStreamingInterval,
            streamingTitle: Swift.String(draft.text.prefix(40)),
            languageHint: draft.selectedLanguage.rawValue,
            payload: .custom(
                speakerID: draft.selectedSpeaker,
                deliveryStyle: model.supportsInstructionControl ? draft.emotion : nil
            ),
            generationID: UUID(),
            seed: draft.pinnedSeed,
            variation: GenerationVariationPreference.requestValue()
        )
    }

}
