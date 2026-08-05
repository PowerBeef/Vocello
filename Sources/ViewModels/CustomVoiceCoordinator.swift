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

        generationTask = GenerationLifecycleExecutor.run(
            ttsEngineStore: ttsEngineStore,
            audioPlayer: audioPlayer,
            setErrorMessage: { [weak self] message in self?.errorMessage = message },
            onFinish: { [weak self] in
                self?.isGenerating = false
                self?.generationTask = nil
            }
        ) { [weak self] in
            guard let model = activeModel else {
                self?.errorMessage = "Model configuration not found"
                return nil
            }
            let outputPath = makeOutputPath(subfolder: model.outputSubfolder, text: draft.text)
            return GenerationLifecycleExecutor.PreparedTake(
                request: Self.makeGenerationRequest(
                    draft: draft,
                    model: model,
                    outputPath: outputPath
                ),
                text: draft.text,
                persistCaller: "CustomVoiceCoordinator",
                makeGeneration: { result in
                    Generation(
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
                }
            )
        }
    }

    func cancelGeneration(
        ttsEngineStore: TTSEngineStore,
        audioPlayer: AudioPlayerViewModel
    ) {
        GenerationLifecycleExecutor.cancelActiveWork(
            generationTask: &generationTask,
            isGenerating: &isGenerating,
            errorMessage: &errorMessage,
            ttsEngineStore: ttsEngineStore,
            audioPlayer: audioPlayer
        )
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
