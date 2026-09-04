import Foundation
import QwenVoiceCore
import QwenVoiceNative

/// Shared single-take generation lifecycle (W2-C, 2026-08 UI review): the
/// three mode coordinators previously triplicated this Task body — timeline
/// submit, live-preview estimate, engine call, persist + autoplay,
/// completion/cancellation/failure telemetry with merge scheduling, and the
/// single-exit state reset — plus a byte-identical cancel. The sync start
/// discipline stays in each coordinator: every precondition is checked
/// BEFORE `isGenerating` flips (the May 2026 flicker fix), and `prepare`
/// runs inside the task only for work that is already allowed to flip state
/// (for example Clone's reference priming).
@MainActor
enum GenerationLifecycleExecutor {
    final class Authority { var current: UUID? }
    private static var previewOwners: [ObjectIdentifier: UUID] = [:]
    struct PreparedTake {
        /// The fully built engine request.
        let request: GenerationRequest
        /// Draft text driving the live-preview estimate and persistence.
        let text: String
        /// Coordinator name recorded by persistence diagnostics.
        let persistCaller: String
        /// Builds the History row from the engine result.
        let makeGeneration: @MainActor (GenerationResult) -> Generation
        /// Runs after persistence + completion telemetry (for example Voice
        /// Design's saved-voice candidate capture).
        var onSuccess: (@MainActor (Generation, GenerationResult) -> Void)? = nil
    }

    /// Starts the generation task. `prepare` returning nil aborts silently
    /// (it has already surfaced any message); a `prepare` throw routes
    /// through the ordinary failure path. `onFinish` is the single exit
    /// point that resets `isGenerating`/task state — it runs on every
    /// terminal path via the task's defer, after the estimate clears.
    static func run(
        authority: Authority,
        ttsEngineStore: TTSEngineStore,
        audioPlayer: AudioPlayerViewModel,
        setErrorMessage: @escaping @MainActor (String?) -> Void,
        onFinish: @escaping @MainActor () -> Void,
        prepare: @escaping @MainActor () async throws -> PreparedTake?
    ) -> Task<Void, Never> {
        let token = UUID()
        authority.current = token
        let playerID = ObjectIdentifier(audioPlayer)
        previewOwners[playerID] = token
        return Task { @MainActor in
            var submittedGenerationID: UUID?
            defer {
                if previewOwners[playerID] == token {
                    previewOwners.removeValue(forKey: playerID)
                    audioPlayer.setLivePreviewEstimate(nil)
                }
                if authority.current == token {
                    authority.current = nil
                    onFinish()
                }
            }
            do {
                try Task.checkCancellation()
                guard let prepared = try await prepare() else { return }
                try Task.checkCancellation()

                await AppGenerationTimeline.shared.recordSubmitted(
                    id: prepared.request.generationID,
                    mode: prepared.request.modeIdentifier
                )
                submittedGenerationID = prepared.request.generationID
                try Task.checkCancellation()
                audioPlayer.setLivePreviewEstimate(
                    LivePreviewEstimate(text: prepared.text)
                )
                let result = try await ttsEngineStore.generate(prepared.request)
                // A returned result has already crossed audio publication. A
                // late cancellation revokes presentation, not History ownership.
                let generation = prepared.makeGeneration(result)
                if !Task.isCancelled, previewOwners[playerID] == token {
                    await GenerationPersistence.persistAndAutoplay(
                        generation, result: result, text: prepared.text,
                        audioPlayer: audioPlayer, caller: prepared.persistCaller
                    )
                } else {
                    await GenerationPersistence.persist(generation, caller: prepared.persistCaller)
                }
                // Keep the frontend timeline open through the genuine player
                // handoff: short clips can complete before live playback has
                // started, in which case final-file autoplay is the first
                // real playback-scheduled event.
                await AppGenerationTimeline.shared.recordCompleted(
                    id: prepared.request.generationID,
                    mode: prepared.request.modeIdentifier,
                    usedStreaming: result.usedStreaming,
                    finishReason: result.finishReason?.rawValue,
                    summary: result.telemetrySummary
                )
                GenerationTelemetryMerger.scheduleMerge(
                    generationID: prepared.request.generationID
                )
                if !Task.isCancelled, authority.current == token {
                    prepared.onSuccess?(generation, result)
                }
            } catch is CancellationError {
                await AppGenerationTimeline.shared.recordFailed(
                    id: submittedGenerationID,
                    finishReason: .cancelled
                )
                GenerationTelemetryMerger.scheduleMerge(generationID: submittedGenerationID)
                if previewOwners[playerID] == token { audioPlayer.abortLivePreviewIfNeeded() }
                if authority.current == token { setErrorMessage(nil) }
            } catch {
                await AppGenerationTimeline.shared.recordFailed(
                    id: submittedGenerationID, finishReason: Task.isCancelled ? .cancelled : .failed
                )
                GenerationTelemetryMerger.scheduleMerge(generationID: submittedGenerationID)
                if previewOwners[playerID] == token { audioPlayer.abortLivePreviewIfNeeded() }
                if !Task.isCancelled, authority.current == token { setErrorMessage(error.localizedDescription) }
            }
        }
    }

    /// The shared cancel: state resets synchronously (already on MainActor) —
    /// routing it through a second Task raced the generation task's own
    /// defer and could null a FRESH generation's handle if the user
    /// re-generated quickly, leaving its cancel button inert.
    static func cancelActiveWork(
        authority: Authority,
        generationTask: inout Task<Void, Never>?,
        isGenerating: inout Bool,
        errorMessage: inout String?,
        ttsEngineStore: TTSEngineStore,
        audioPlayer: AudioPlayerViewModel
    ) {
        guard isGenerating || generationTask != nil else { return }
        let token = authority.current
        authority.current = nil
        generationTask?.cancel()
        generationTask = nil
        isGenerating = false
        errorMessage = nil
        let playerID = ObjectIdentifier(audioPlayer)
        if let token, previewOwners[playerID] == token {
            previewOwners.removeValue(forKey: playerID)
            audioPlayer.setLivePreviewEstimate(nil)
            audioPlayer.abortLivePreviewIfNeeded()
        }
        // Cancelling the owning task already invokes the XPC request's scoped
        // cancellation handler. A second asynchronous cancel can target B.
    }
}
