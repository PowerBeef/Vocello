import Foundation
import QwenVoiceCore

@MainActor
enum IOSStudioGenerationActions {
    static func cancelGeneration(
        coordinator: StudioGenerationCoordinator,
        ttsEngine: TTSEngineStore,
        audioPlayer: AudioPlayerViewModel
    ) {
        guard let attempt = coordinator.requestCancellation() else { return }
        // Stop audible preview immediately, but keep the generation coordinator
        // nonterminal until the engine-owned cancellation barrier confirms that
        // MLX compute has exited. The matching attempt token prevents an older
        // barrier from clearing a later generation.
        audioPlayer.abortLivePreviewIfNeeded()
        Task {
            do {
                try await ttsEngine.cancelActiveGeneration()
                coordinator.completeCancellation(attempt: attempt)
            } catch {
                if coordinator.failCancellation(error, attempt: attempt) {
                    IOSHaptics.warning()
                }
            }
        }
    }
}
