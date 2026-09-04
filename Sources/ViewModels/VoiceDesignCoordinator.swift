import Foundation
import Observation
import QwenVoiceCore
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
    @ObservationIgnored private let generationAuthority = GenerationLifecycleExecutor.Authority()

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
        // Capture the full request before the executor can suspend. Rebuilding a
        // partial draft here silently reset language and the pinned seed to Auto/nil.
        let variation = GenerationVariationPreference.requestValue()

        generationTask = GenerationLifecycleExecutor.run(
            authority: generationAuthority,
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
            let outputPath = makeOutputPath(subfolder: model.outputSubfolder, text: text)
            return GenerationLifecycleExecutor.PreparedTake(
                request: Self.makeGenerationRequest(
                    draft: draft,
                    model: model,
                    outputPath: outputPath,
                    variation: variation
                ),
                text: text,
                persistCaller: "VoiceDesignCoordinator",
                makeGeneration: { result in
                    Generation(
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
                },
                onSuccess: { generation, _ in
                    self?.latestSavedVoiceCandidate = VoiceDesignSavedVoiceCandidate(
                        audioPath: generation.audioPath,
                        transcript: text,
                        suggestedName: SavedVoiceNameSuggestion.designResultName(from: voiceDescription),
                        voiceDescription: voiceDescription,
                        emotion: emotion,
                        text: text
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
            authority: generationAuthority,
            generationTask: &generationTask,
            isGenerating: &isGenerating,
            errorMessage: &errorMessage,
            ttsEngineStore: ttsEngineStore,
            audioPlayer: audioPlayer
        )
    }

    nonisolated static func makeGenerationRequest(
        draft: VoiceDesignDraft,
        model: TTSModel,
        outputPath: String,
        variation: Qwen3SamplingVariation?
    ) -> GenerationRequest {
        MacStudioGenerationRequestFactory.voiceDesign(
            modelID: model.id,
            text: draft.text,
            outputPath: outputPath,
            language: draft.selectedLanguage,
            voiceDescription: draft.voiceDescription,
            deliveryStyle: draft.emotion,
            seed: draft.pinnedSeed,
            variation: variation
        )
    }

}
