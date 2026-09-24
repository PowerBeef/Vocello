import Foundation
import QwenVoiceCore

/// The side effects of one macOS Studio take: the shared executor's hooks plus
/// the dock card a completed take publishes. `MacStudioSingleTakeGenerationHooks`
/// is the production adapter; deterministic tests substitute a fake engine.
@MainActor
protocol MacStudioSingleTakeHooks: IOSSingleTakeGenerationExecutionHooks, Sendable {
    func inlinePlayerItem(
        for result: GenerationResult,
        plan: IOSSingleTakeGenerationPlan
    ) -> IOSStudioInlinePlayerItem
}

/// The on-demand clone priming a Voice Cloning take runs before its request
/// when the screen's proactive priming has not already prepared this exact
/// reference. A failed pass degrades to unprimed generation, never a failure.
struct MacStudioClonePriming: Sendable {
    let modelID: String
    let reference: CloneReference
    /// The preparation key the screen's proactive priming targets.
    let expectedKey: String?

    /// Whether the engine already holds the primed reference the take expects.
    func isSatisfied(by state: ClonePreparationState) -> Bool {
        state.isPrimed && state.key == expectedKey
    }
}

/// The owner of the macOS Studio take lifecycle (AUD-03): the Studio screens
/// hand over an immutable plan and never construct or hold a generation task.
/// The take runs under one attempt of the mode's `StudioGenerationCoordinator`,
/// which retains the task, rejects stale terminal callbacks and owns
/// cancellation; `IOSSingleTakeGenerationExecutor` runs the take, honouring a
/// cancellation the coordinator accepted before the task itself is cancelled
/// (PA-15). `MacStudioGenerationActions` binds it to the engine store.
@MainActor
enum MacStudioSingleTakeRunner {
    /// Starts `plan` as the coordinator's next attempt and installs its task.
    /// The live card carries the plan's voice, mode, transcript and waveform
    /// seed, so the final card keeps its shape. `prepare` runs inside the
    /// attempt before the executor (clone priming); `onCompleted` runs only
    /// when the coordinator accepted the completed take. Returns `false` when
    /// the attempt authority refuses the start (an attempt still runs or is
    /// cancelling); the caller holds nothing either way.
    @discardableResult
    static func start(
        plan: IOSSingleTakeGenerationPlan,
        estimatedAudioDuration: TimeInterval,
        coordinator: StudioGenerationCoordinator,
        hooks: any MacStudioSingleTakeHooks,
        prepare: @escaping @MainActor @Sendable () async -> Void = {},
        onCompleted: @escaping @MainActor @Sendable (GenerationResult) -> Void = { _ in }
    ) -> Bool {
        guard let attempt = coordinator.start(live: IOSStudioLivePreviewItem(
            voiceName: plan.displayVoiceName,
            modeLabel: plan.modeLabel,
            mode: plan.request.mode,
            transcript: plan.request.text,
            waveformSeed: plan.waveformSeed,
            estimatedAudioDuration: estimatedAudioDuration
        )) else { return false }

        let task = Task { @MainActor in
            defer { coordinator.finish(attempt: attempt) }
            do {
                await prepare()
                let result = try await IOSSingleTakeGenerationExecutor.run(
                    plan: plan,
                    hooks: hooks,
                    isCancellationRequested: { coordinator.isCancellationRequested(for: attempt) }
                )
                if coordinator.complete(hooks.inlinePlayerItem(for: result, plan: plan), attempt: attempt) {
                    onCompleted(result)
                }
            } catch is CancellationError {
                // The shared executor owns cancellation cleanup and telemetry.
            } catch {
                coordinator.fail(error.localizedDescription, attempt: attempt)
            }
        }
        coordinator.installGenerationTask(task, for: attempt)
        return true
    }

    /// Cancels the coordinator's running attempt: audible preview stops at
    /// once, the coordinator stays nonterminal until `barrier` (the engine's
    /// cancellation barrier) confirms that compute has exited, and the attempt
    /// token keeps an older barrier from clearing a later take. Returns the
    /// barrier task, or `nil` when no running attempt accepted the request.
    @discardableResult
    static func cancel(
        coordinator: StudioGenerationCoordinator,
        stopLivePreview: () -> Void,
        barrier: @escaping @MainActor @Sendable () async throws -> Void
    ) -> Task<Void, Never>? {
        guard let attempt = coordinator.requestCancellation() else { return nil }
        stopLivePreview()
        return Task { @MainActor in
            do {
                try await barrier()
                coordinator.completeCancellation(attempt: attempt)
            } catch {
                coordinator.failCancellation(error, attempt: attempt)
            }
        }
    }
}
