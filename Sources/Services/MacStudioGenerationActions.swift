import Foundation
import QwenVoiceCore

/// The shared start and cancel path of the Studio screens (the iOS
/// `IOSStudioGenerationActions` without haptics), bound to the engine store on
/// `MacStudioSingleTakeRunner`. A screen validates its draft, builds the
/// immutable plan and calls `startSingleTake`; the runner owns the task and the
/// mode's `StudioGenerationCoordinator` retains it, so no view starts or holds
/// a generation task. Cancellation stops audible preview at once, keeps the
/// coordinator nonterminal until the engine-owned cancellation barrier confirms
/// that MLX compute has exited, and the attempt token keeps an older barrier
/// from clearing a later generation.
@MainActor
enum MacStudioGenerationActions {
    /// Starts one take through the shared executor with the macOS hooks.
    /// `clonePriming` primes the clone reference on demand when the screen's
    /// proactive priming has not prepared it; `onCompleted` runs only for a
    /// take the coordinator accepted. Returns `false` when the coordinator
    /// refuses the start.
    @discardableResult
    static func startSingleTake(
        _ plan: IOSSingleTakeGenerationPlan,
        coordinator: StudioGenerationCoordinator,
        ttsEngine: TTSEngineStore,
        audioPlayer: AudioPlayerViewModel,
        clonePriming: MacStudioClonePriming? = nil,
        onCompleted: @escaping @MainActor @Sendable (GenerationResult) -> Void = { _ in }
    ) -> Bool {
        MacStudioSingleTakeRunner.start(
            plan: plan,
            estimatedAudioDuration: LivePreviewEstimate(text: plan.request.text)?.estimatedAudioDuration ?? 0,
            coordinator: coordinator,
            hooks: MacStudioSingleTakeGenerationHooks(engine: ttsEngine, audioPlayer: audioPlayer),
            prepare: {
                if let clonePriming {
                    await Self.primeCloneReferenceIfNeeded(clonePriming, ttsEngine: ttsEngine)
                }
            },
            onCompleted: onCompleted
        )
    }

    static func cancelGeneration(
        coordinator: StudioGenerationCoordinator,
        ttsEngine: TTSEngineStore,
        audioPlayer: AudioPlayerViewModel
    ) {
        MacStudioSingleTakeRunner.cancel(
            coordinator: coordinator,
            stopLivePreview: { audioPlayer.abortLivePreviewIfNeeded() },
            barrier: { try await ttsEngine.cancelActiveGeneration() }
        )
    }

    /// Stop (⌘.) while a take runs (MAC-23): the line batch and the long-form
    /// project cancel through their own runners, as their sheet's Cancel does,
    /// and a single take through its mode's coordinator, as the Studio's Cancel
    /// does. Returns whether anything was running.
    @discardableResult
    static func cancelActiveGeneration(
        appModel: MacAppModel,
        ttsEngine: TTSEngineStore,
        audioPlayer: AudioPlayerViewModel
    ) -> Bool {
        if appModel.lineBatch.isProcessing, let mode = appModel.lineBatch.lastMode {
            appModel.lineBatch.cancel(
                ttsEngine: ttsEngine,
                audioPlayer: audioPlayer,
                studioCoordinator: appModel.coordinator(for: mode)
            )
            return true
        }
        if appModel.longForm.isProcessing, let mode = appModel.longForm.lastMode {
            return appModel.longForm.cancel(
                ttsEngine: ttsEngine,
                audioPlayer: audioPlayer,
                studioCoordinator: appModel.coordinator(for: mode)
            )
        }
        var cancelled = false
        for mode in GenerationMode.allCases where appModel.coordinator(for: mode).isGenerating {
            cancelGeneration(coordinator: appModel.coordinator(for: mode), ttsEngine: ttsEngine, audioPlayer: audioPlayer)
            cancelled = true
        }
        return cancelled
    }

    private static func primeCloneReferenceIfNeeded(
        _ priming: MacStudioClonePriming,
        ttsEngine: TTSEngineStore
    ) async {
        guard !priming.isSatisfied(by: ttsEngine.clonePreparationState) else { return }
        do {
            try await ttsEngine.ensureCloneReferencePrimed(modelID: priming.modelID, reference: priming.reference)
        } catch {
            if DebugMode.isEnabled {
                print("[Performance][MacStudioGenerationActions] clone priming degraded: \(DiagnosticPrivacy.summary(of: error))")
            }
        }
    }
}
