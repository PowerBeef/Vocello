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
        guard let attempt = coordinator.requestCancellation() else { return }
        // Stop audible preview immediately, but keep the generation coordinator
        // nonterminal until the engine-owned cancellation barrier confirms that
        // MLX compute has exited. The matching attempt token prevents an older
        // barrier from clearing a later generation.
        audioPlayer.abortLivePreviewIfNeeded()
        Task {
            do {
                try await ttsEngine.cancelActiveGeneration(reason: reason)
                coordinator.completeCancellation(attempt: attempt)
            } catch {
                if coordinator.failCancellation(error, attempt: attempt) {
                    IOSHaptics.warning()
                }
            }
        }
    }
}
