import Foundation
import QwenVoiceCore

@MainActor
enum IOSStudioGenerationActions {
    /// `reason` is `.shutdown` when the app leaves the foreground (PA-15); the
    /// take is discarded exactly as for a user cancel and never reaches History.
    static func cancelGeneration(
        coordinator: StudioGenerationCoordinator,
        ttsEngine: TTSEngineStore,
        audioPlayer: AudioPlayerViewModel,
        reason: GenerationCancellationReason = .user
    ) {
        _ = startCancellation(
            coordinator: coordinator,
            ttsEngine: ttsEngine,
            audioPlayer: audioPlayer,
            reason: reason
        )
    }

    /// Starts the cancellation and returns its barrier task, which finishes once
    /// the attempt is terminal; `nil` when no running attempt accepted it.
    static func startCancellation(
        coordinator: StudioGenerationCoordinator,
        ttsEngine: TTSEngineStore,
        audioPlayer: AudioPlayerViewModel,
        reason: GenerationCancellationReason
    ) -> Task<Void, Never>? {
        let order = IOSStudioCancellationOrder.forReason(reason)
        guard let attempt = coordinator.requestCancellation(
            cancelsTask: order == .taskThenBarrier
        ) else { return nil }
        // Stop audible preview immediately, but keep the generation coordinator
        // nonterminal until the engine-owned cancellation barrier confirms that
        // MLX compute has exited. The matching attempt token prevents an older
        // barrier from clearing a later generation.
        audioPlayer.abortLivePreviewIfNeeded()
        return Task {
            do {
                try await ttsEngine.cancelActiveGeneration(reason: reason)
                // A typed reason reached the engine first; now stop any Swift
                // work that had not been admitted to the engine yet.
                coordinator.cancelGenerationTask()
                coordinator.completeCancellation(attempt: attempt)
            } catch {
                coordinator.cancelGenerationTask()
                if coordinator.failCancellation(error, attempt: attempt) {
                    IOSHaptics.warning()
                }
            }
        }
    }
}
