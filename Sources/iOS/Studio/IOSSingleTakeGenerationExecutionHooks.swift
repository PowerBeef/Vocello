import Foundation
import QwenVoiceCore

/// Production adapter for `IOSSingleTakeGenerationExecutor`.
///
/// This is the only short-form Studio owner of frontend timeline completion,
/// cancelled-output cleanup, final playback handoff, History persistence, and
/// optional Files export. Views retain only mode-specific preparation and the
/// attempt-scoped UI terminal transition.
@MainActor
final class IOSStudioSingleTakeGenerationHooks: IOSSingleTakeGenerationExecutionHooks {
    private let engine: TTSEngineStore
    private let audioPlayer: AudioPlayerViewModel

    init(
        engine: TTSEngineStore,
        audioPlayer: AudioPlayerViewModel
    ) {
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

    func generationCompleted(
        _ result: GenerationResult,
        plan: IOSSingleTakeGenerationPlan
    ) async {
        // Playback handoff precedes telemetry finalization so a short take's
        // genuine scheduling event is part of the durable app-layer row.
        audioPlayer.completeStreamingPreview(
            result: result,
            title: String(plan.request.text.prefix(40)),
            shouldAutoPlay: AudioService.shouldAutoPlay
        )
        await AppGenerationTimeline.shared.recordCompleted(
            id: plan.generationID,
            mode: plan.request.mode.rawValue,
            usedStreaming: result.usedStreaming,
            finishReason: result.finishReason?.rawValue,
            summary: result.telemetrySummary
        )
        IOSPullableDiagnosticsMirror.syncGenerationTelemetryIfEnabled(
            generationID: plan.generationID,
            publishedAudioURL: URL(fileURLWithPath: result.audioPath)
        )

        await GenerationPersistence.persist(
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
            ),
            caller: plan.persistenceCaller
        )
        IOSSavedOutputsDestination.exportIfConfigured(internalAudioPath: result.audioPath)
    }

    func generationCancelled(
        materializedResult: GenerationResult?,
        plan: IOSSingleTakeGenerationPlan
    ) async {
        await AppGenerationTimeline.shared.recordFailed(
            id: plan.generationID,
            finishReason: .cancelled
        )
        IOSPullableDiagnosticsMirror.syncGenerationTelemetryIfEnabled(
            generationID: plan.generationID
        )
        if let materializedResult {
            try? FileManager.default.removeItem(atPath: materializedResult.audioPath)
        }
        audioPlayer.abortLivePreviewIfNeeded()
    }

    func generationFailed(_ plan: IOSSingleTakeGenerationPlan) async {
        await AppGenerationTimeline.shared.recordFailed(
            id: plan.generationID,
            finishReason: .failed
        )
        IOSPullableDiagnosticsMirror.syncGenerationTelemetryIfEnabled(
            generationID: plan.generationID
        )
        audioPlayer.abortLivePreviewIfNeeded()
    }

    func inlinePlayerItem(
        for result: GenerationResult,
        plan: IOSSingleTakeGenerationPlan
    ) -> IOSStudioInlinePlayerItem {
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
}
