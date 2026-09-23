import QwenVoiceCore
import UIKit

/// App-lifetime owner of the iOS foreground-exit side effects (PA-15): the
/// finite background-time grant, the Studio cancellation and its return notice,
/// and the screen-awake hold while generating. The decisions live in
/// `IOSBackgroundGenerationPolicy` and `IOSForegroundExitState`; this type only
/// applies them to UIKit and to the Studio's `AppModel`, which
/// `QVoiceiOSRootView` attaches once its state is installed.
@MainActor
final class IOSBackgroundGenerationController {
    private weak var appModel: AppModel?
    private var backgroundTask: UIBackgroundTaskIdentifier = .invalid
    private var screenAwakeHold = IOSGenerationScreenAwakeHold()
    private var exitState = IOSForegroundExitState()

    func attach(_ appModel: AppModel) {
        self.appModel = appModel
    }

    var studioWork: IOSBackgroundGenerationWork {
        appModel?.activeStudioWork ?? .idle
    }

    // MARK: - Foreground exit sequencing

    /// Opens a foreground exit and, when asked, requests background time so the
    /// cancellation barrier and the runtime release can finish before suspension.
    func beginForegroundExit(requestsBackgroundTime: Bool) -> UInt64 {
        let epoch = exitState.enterBackground()
        if requestsBackgroundTime {
            beginBackgroundTime()
        }
        return epoch
    }

    /// The exit's barrier returned; `true` when its release must be requested now.
    func foregroundExitBarrierReturned(_ epoch: UInt64) -> Bool {
        exitState.barrierReturned(for: epoch)
    }

    /// The scene is active again: supersede any in-flight exit and give the grant back.
    func returnToForeground() {
        exitState.returnToForeground()
        endBackgroundTime()
    }

    /// A runtime release finished; ends the grant only when nothing of the
    /// foreground exit is still waiting, queued or pending.
    func runtimeReleaseCompleted(
        followUpReleaseExecutes: Bool,
        pendingReleaseReason: String?
    ) {
        guard exitState.endsBackgroundTime(
            followUpReleaseExecutes: followUpReleaseExecutes,
            pendingReleaseReason: pendingReleaseReason
        ) else { return }
        endBackgroundTime()
    }

    private func beginBackgroundTime() {
        guard backgroundTask == .invalid else { return }
        backgroundTask = UIApplication.shared.beginBackgroundTask(
            withName: "vocello.generation.foreground-exit"
        ) { [weak self] in
            // Expiration: give the grant back; suspension proceeds.
            self?.endBackgroundTime()
        }
    }

    private func endBackgroundTime() {
        guard backgroundTask != .invalid else { return }
        let task = backgroundTask
        backgroundTask = .invalid
        UIApplication.shared.endBackgroundTask(task)
    }

    // MARK: - Studio

    /// Cancels the Studio's running attempt through its typed barrier, records
    /// the notice for return and returns once that barrier has finished.
    /// Returns `false` when no attempt accepted the cancellation.
    func interruptStudio(
        _ interruption: IOSBackgroundInterruption,
        reason: GenerationCancellationReason,
        ttsEngine: TTSEngineStore,
        audioPlayer: AudioPlayerViewModel
    ) async -> Bool {
        guard let appModel else { return false }
        return await appModel.interruptStudioGeneration(
            interruption,
            reason: reason,
            ttsEngine: ttsEngine,
            audioPlayer: audioPlayer
        )
    }

    func presentNoticesOnReturn() {
        appModel?.presentBackgroundInterruptionNotices()
    }

    /// Keeps the screen awake while generating (single take or a whole long-form run).
    func updateScreenAwake(isGenerating: Bool) {
        let application = UIApplication.shared
        if let disabled = screenAwakeHold.update(
            isGenerating: isGenerating,
            idleTimerDisabled: application.isIdleTimerDisabled
        ) {
            application.isIdleTimerDisabled = disabled
        }
    }
}
