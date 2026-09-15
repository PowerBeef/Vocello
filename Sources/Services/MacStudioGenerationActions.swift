import Foundation
import QwenVoiceCore

/// The shared cancel path of the Studio screens (the iOS
/// `IOSStudioGenerationActions` without haptics): audible preview stops at
/// once, the coordinator stays nonterminal until the engine-owned
/// cancellation barrier confirms that MLX compute has exited, and the
/// attempt token keeps an older barrier from clearing a later generation.
@MainActor
enum MacStudioGenerationActions {
    static func cancelGeneration(
        coordinator: StudioGenerationCoordinator,
        ttsEngine: TTSEngineStore,
        audioPlayer: AudioPlayerViewModel
    ) {
        guard let attempt = coordinator.requestCancellation() else { return }
        audioPlayer.abortLivePreviewIfNeeded()
        Task {
            do {
                try await ttsEngine.cancelActiveGeneration()
                coordinator.completeCancellation(attempt: attempt)
            } catch {
                coordinator.failCancellation(error, attempt: attempt)
            }
        }
    }
}
