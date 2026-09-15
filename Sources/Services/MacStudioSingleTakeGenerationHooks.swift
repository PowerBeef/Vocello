import Foundation
import QwenVoiceCore

/// macOS adapter for the shared `IOSSingleTakeGenerationExecutor`: the one
/// short-form Studio owner of the frontend timeline, the live-preview
/// estimate, the final playback handoff with autoplay, History persistence
/// and the two-layer telemetry merge. The iOS adapter adds the pullable
/// diagnostics mirror and Files export, which have no desktop counterpart. A
/// cancelled take never lands in History on either platform: a result that
/// materialized after the cancellation is removed, as the iOS hooks do.
@MainActor
final class MacStudioSingleTakeGenerationHooks: IOSSingleTakeGenerationExecutionHooks {
    private let engine: TTSEngineStore
    private let audioPlayer: AudioPlayerViewModel

    init(engine: TTSEngineStore, audioPlayer: AudioPlayerViewModel) {
        self.engine = engine
        self.audioPlayer = audioPlayer
    }

    func generationSubmitted(_ plan: IOSSingleTakeGenerationPlan) async {
        audioPlayer.setLivePreviewEstimate(LivePreviewEstimate(text: plan.request.text))
        await AppGenerationTimeline.shared.recordSubmitted(
            id: plan.generationID,
            mode: plan.request.mode.rawValue
        )
    }

    func generate(_ request: GenerationRequest) async throws -> GenerationResult {
        try await engine.generate(request)
    }

    func generationCompleted(_ result: GenerationResult, plan: IOSSingleTakeGenerationPlan) async {
        // Playback handoff precedes telemetry finalization so a short take's
        // genuine scheduling event is part of the durable app-layer row.
        await GenerationPersistence.persistAndAutoplay(
            makeGeneration(result, plan: plan),
            result: result,
            text: plan.request.text,
            audioPlayer: audioPlayer,
            caller: plan.persistenceCaller
        )
        await AppGenerationTimeline.shared.recordCompleted(
            id: plan.generationID,
            mode: plan.request.mode.rawValue,
            usedStreaming: result.usedStreaming,
            finishReason: result.finishReason?.rawValue,
            summary: result.telemetrySummary
        )
        GenerationTelemetryMerger.scheduleMerge(generationID: plan.generationID)
        audioPlayer.setLivePreviewEstimate(nil)
    }

    func generationCancelled(materializedResult: GenerationResult?, plan: IOSSingleTakeGenerationPlan) async {
        if let materializedResult {
            try? FileManager.default.removeItem(atPath: materializedResult.audioPath)
        }
        await AppGenerationTimeline.shared.recordFailed(id: plan.generationID, finishReason: .cancelled)
        GenerationTelemetryMerger.scheduleMerge(generationID: plan.generationID)
        audioPlayer.setLivePreviewEstimate(nil)
        audioPlayer.abortLivePreviewIfNeeded()
    }

    func generationFailed(_ plan: IOSSingleTakeGenerationPlan) async {
        await AppGenerationTimeline.shared.recordFailed(id: plan.generationID, finishReason: .failed)
        GenerationTelemetryMerger.scheduleMerge(generationID: plan.generationID)
        audioPlayer.setLivePreviewEstimate(nil)
        audioPlayer.abortLivePreviewIfNeeded()
    }

    /// The completed take as the Studio dock shows it; the shared player
    /// already owns its playback (live preview → final file), so the card
    /// mirrors it instead of starting a second player.
    func inlinePlayerItem(for result: GenerationResult, plan: IOSSingleTakeGenerationPlan) -> IOSStudioInlinePlayerItem {
        IOSStudioInlinePlayerItem(
            generationID: plan.generationID,
            audioURL: URL(fileURLWithPath: result.audioPath),
            voiceName: plan.displayVoiceName,
            modeLabel: plan.modeLabel,
            mode: plan.request.mode,
            transcript: plan.request.text,
            waveformSeed: plan.waveformSeed,
            autoplay: false,
            cadenceNotice: IOSStudioCadenceNotice(audioQC: result.audioQC),
            ownedBySharedPlayer: true
        )
    }

    private func makeGeneration(_ result: GenerationResult, plan: IOSSingleTakeGenerationPlan) -> Generation {
        Generation(
            text: plan.request.text,
            mode: plan.request.mode.rawValue,
            modelTier: plan.modelTier,
            voice: plan.historyVoice,
            emotion: plan.historyEmotion,
            speed: nil,
            audioPath: result.audioPath,
            duration: result.durationSeconds,
            createdAt: Date(),
            seed: result.observedSamplingSeed.map { Int64(bitPattern: $0) }
        )
    }
}
