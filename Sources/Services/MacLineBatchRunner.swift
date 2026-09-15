import Foundation
import Observation
import QwenVoiceCore

/// The macOS line batch: one ordinary Studio take per line, looped over the
/// shared `IOSSingleTakeGenerationExecutor` with `MacStudioSingleTakeGenerationHooks`
/// (timeline, live-preview handoff, History append, telemetry merge, cancelled
/// output removal), under one attempt of the mode's `StudioGenerationCoordinator`
/// so the canvas locks exactly as during a single take. Owned by `MacAppModel`
/// like the long-form `IOSLongFormCoordinator`; the batch sheet renders it.
/// Cancellation goes through the engine barrier the way the long-form
/// coordinator cancels: the store's typed cancellation closes the attempt.
@MainActor
@Observable
final class MacLineBatchRunner {
    typealias Item = MacLineBatchItem
    typealias Progress = MacLineBatchProgress
    typealias Outcome = MacLineBatchOutcome
    typealias Request = MacLineBatchRequest

    static let maxLines = MacLineBatchRequest.maxLines

    private(set) var isProcessing = false
    private(set) var isCancelling = false
    private(set) var progress = Progress()
    private(set) var items: [Item] = []
    private(set) var outcome: Outcome?
    /// Mode that started the current/last batch; the sheet of that mode owns it.
    private(set) var lastMode: GenerationMode?

    @ObservationIgnored private var runTask: Task<Void, Never>?
    @ObservationIgnored private var cancelTask: Task<Void, Never>?
    @ObservationIgnored private var cancellationState = MacLineBatchCancellationState()
    @ObservationIgnored private var restartFailedMessage: String?

    init() {}

    static func lines(from text: String) -> [String] {
        Request.lines(from: text)
    }

    /// A reopened sheet starts blank: clears the items and outcome of a
    /// finished batch (never touches a running one).
    func reset() {
        guard !isProcessing else { return }
        items = []
        outcome = nil
        progress = Progress()
        isCancelling = false
        restartFailedMessage = nil
    }

    /// Returns whether the batch started (false while busy, when the engine
    /// already generates, or when the attempt authority refuses the start).
    @discardableResult
    func start(
        request: Request,
        ttsEngine: TTSEngineStore,
        audioPlayer: AudioPlayerViewModel,
        studioCoordinator: StudioGenerationCoordinator
    ) -> Bool {
        guard !isProcessing, !ttsEngine.hasActiveGeneration, !request.lines.isEmpty else { return false }
        guard let attempt = studioCoordinator.start(live: nil) else { return false }
        lastMode = request.mode
        outcome = nil
        isProcessing = true
        isCancelling = false
        restartFailedMessage = nil
        cancelTask = nil
        cancellationState = MacLineBatchCancellationState()
        let cancellation = cancellationState
        items = request.lines.enumerated().map { index, line in
            Item(index: index, line: line, status: .pending)
        }
        progress = Progress(
            completedCount: 0,
            totalCount: items.count,
            activeIndex: nil,
            statusMessage: MacInterfaceText.batchPreparing
        )
        let hooks = MacStudioSingleTakeGenerationHooks(engine: ttsEngine, audioPlayer: audioPlayer)
        let task = Task { [weak self] in
            guard let self else { return }
            let (outcome, lastSaved) = await self.run(
                request: request,
                hooks: hooks,
                ttsEngine: ttsEngine,
                studioCoordinator: studioCoordinator,
                attempt: attempt,
                cancellation: cancellation
            )
            if case .cancelled = outcome, let cancelTask = self.cancelTask {
                // The barrier stamps the restart failure before the outcome shows.
                await cancelTask.value
            }
            self.finish(outcome, lastSaved: lastSaved, studioCoordinator: studioCoordinator, attempt: attempt)
        }
        runTask = task
        studioCoordinator.installGenerationTask(task, for: attempt)
        return true
    }

    func cancel(
        ttsEngine: TTSEngineStore,
        audioPlayer: AudioPlayerViewModel,
        studioCoordinator: StudioGenerationCoordinator
    ) {
        guard isProcessing, !isCancelling else { return }
        guard let attempt = studioCoordinator.requestCancellation() else { return }
        isCancelling = true
        progress.statusMessage = MacInterfaceText.batchCancelling
        let cancellation = cancellationState
        runTask?.cancel()
        audioPlayer.abortLivePreviewIfNeeded()
        cancelTask = Task { [weak self] in
            await cancellation.request()
            do {
                try await ttsEngine.cancelActiveGeneration()
                studioCoordinator.completeCancellation(attempt: attempt)
            } catch {
                self?.restartFailedMessage = MacInterfaceText.batchRestartFailed(error.localizedDescription)
                studioCoordinator.failCancellation(error, attempt: attempt)
            }
        }
    }

    /// Sheet-dismissal safety net: a batch must never keep generating behind
    /// a closed sheet (programmatic dismissal, window close).
    func cancelIfDismissedWhileProcessing(
        ttsEngine: TTSEngineStore,
        audioPlayer: AudioPlayerViewModel,
        studioCoordinator: StudioGenerationCoordinator
    ) {
        guard isProcessing else { return }
        cancel(ttsEngine: ttsEngine, audioPlayer: audioPlayer, studioCoordinator: studioCoordinator)
    }

    // MARK: - Run loop

    private func run(
        request: Request,
        hooks: MacStudioSingleTakeGenerationHooks,
        ttsEngine: TTSEngineStore,
        studioCoordinator: StudioGenerationCoordinator,
        attempt: StudioGenerationAttemptToken,
        cancellation: MacLineBatchCancellationState
    ) async -> (Outcome, IOSStudioInlinePlayerItem?) {
        // Hold the fixed-refresh performance gate across the whole batch
        // instead of flickering per line.
        ttsEngine.beginSustainedPerformanceActivity()
        defer { ttsEngine.endSustainedPerformanceActivity() }

        var lastSaved: IOSStudioInlinePlayerItem?
        let total = items.count

        func markCancelled(startingAt index: Int) {
            for i in index..<items.count where !items[i].isSaved {
                items[i].status = .cancelled
            }
        }

        func publish(active: Int?, message: String) {
            progress = Progress(
                completedCount: items.count(where: \.isSaved),
                totalCount: total,
                activeIndex: active,
                statusMessage: message
            )
        }

        for index in items.indices {
            let line = items[index].line
            let cancellationRequested = await cancellation.wasRequested()
            if Task.isCancelled || cancellationRequested {
                markCancelled(startingAt: index)
                return (.cancelled(items: items, restartFailedMessage: nil), lastSaved)
            }

            items[index].status = .running
            publish(active: index, message: MacInterfaceText.batchGeneratingItem(String(index + 1), String(total)))
            let waveformSeed = MacStableVisualHash.int(line)
            studioCoordinator.updateLiveItem(IOSStudioLivePreviewItem(
                voiceName: request.displayVoiceName,
                modeLabel: request.modeLabel,
                mode: request.mode,
                transcript: line,
                waveformSeed: waveformSeed,
                estimatedAudioDuration: LivePreviewEstimate(text: line)?.estimatedAudioDuration ?? 0
            ), attempt: attempt)

            do {
                let outputPath = makeOutputPath(subfolder: request.outputSubfolder, text: line)
                guard let generationRequest = request.generationRequest(line: line, outputPath: outputPath) else {
                    throw MacLineBatchError.requestConstructionFailed(request.mode)
                }
                let plan = try IOSSingleTakeGenerationPlan(
                    request: generationRequest,
                    modelTier: request.modelTier,
                    historyVoice: request.historyVoice,
                    historyEmotion: request.historyEmotion,
                    displayVoiceName: request.displayVoiceName,
                    modeLabel: request.modeLabel,
                    waveformSeed: waveformSeed,
                    persistenceCaller: "MacLineBatchRunner"
                )
                let result = try await IOSSingleTakeGenerationExecutor.run(plan: plan, hooks: hooks)
                items[index].generationID = plan.generationID
                items[index].status = .saved(audioPath: result.audioPath)
                lastSaved = hooks.inlinePlayerItem(for: result, plan: plan)
                publish(active: index, message: MacInterfaceText.batchGeneratingItem(String(index + 1), String(total)))
            } catch is CancellationError {
                // The shared executor owns the cancelled take's cleanup and telemetry.
                markCancelled(startingAt: index)
                return (.cancelled(items: items, restartFailedMessage: nil), lastSaved)
            } catch {
                items[index].status = .failed(message: error.localizedDescription)
                return (.failed(items: items, message: error.localizedDescription), lastSaved)
            }
        }

        publish(active: nil, message: MacInterfaceText.done)
        return (.completed(items: items), lastSaved)
    }

    private func finish(
        _ outcome: Outcome,
        lastSaved: IOSStudioInlinePlayerItem?,
        studioCoordinator: StudioGenerationCoordinator,
        attempt: StudioGenerationAttemptToken
    ) {
        isProcessing = false
        isCancelling = false
        runTask = nil
        cancelTask = nil
        switch outcome {
        case .completed:
            self.outcome = outcome
            // The dock card mirrors what the shared player holds: the last
            // saved line, exactly like a single take.
            if let lastSaved {
                studioCoordinator.complete(lastSaved, attempt: attempt)
            } else {
                studioCoordinator.finish(attempt: attempt)
            }
        case .failed(_, let message):
            self.outcome = outcome
            studioCoordinator.fail(message, attempt: attempt)
        case .cancelled(let items, _):
            // The cancel path closed the attempt through the engine barrier.
            self.outcome = .cancelled(items: items, restartFailedMessage: restartFailedMessage)
        }
    }
}

private enum MacLineBatchError: LocalizedError {
    case requestConstructionFailed(GenerationMode)

    var errorDescription: String? {
        switch self {
        case .requestConstructionFailed(let mode):
            return mode == .clone ? MacInterfaceText.batchNeedsReference : MacInterfaceText.batchModelConfigurationMissing
        }
    }
}

actor MacLineBatchCancellationState {
    private var isRequested = false
    func request() { isRequested = true }
    func wasRequested() -> Bool { isRequested }
}

extension MacLineBatchRequest {
    /// The sheet's constructor: scalar model facts from the active package,
    /// the display name the dock shows, and the Settings variation.
    init(
        mode: GenerationMode,
        model: TTSModel,
        lines: [String],
        voice: String?,
        emotion: String?,
        deliveryInstructionCellID: String?,
        language: Qwen3SupportedLanguage,
        voiceDescription: String?,
        refAudio: String?,
        refText: String?,
        preparedVoiceID: String?,
        displayVoiceName: String
    ) {
        self.init(
            mode: mode,
            modelID: model.id,
            modelTier: model.tier,
            outputSubfolder: model.outputSubfolder,
            supportsInstructionControl: model.supportsInstructionControl,
            lines: lines,
            voice: voice,
            emotion: emotion,
            deliveryInstructionCellID: deliveryInstructionCellID,
            language: language,
            voiceDescription: voiceDescription,
            refAudio: refAudio,
            refText: refText,
            preparedVoiceID: preparedVoiceID,
            displayVoiceName: displayVoiceName,
            variation: GenerationVariationPreference.requestValue()
        )
    }
}
