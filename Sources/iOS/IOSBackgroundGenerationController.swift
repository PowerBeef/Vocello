import QwenVoiceCore
import UIKit

/// App-lifetime owner of the iOS foreground-exit side effects (PA-15): the
/// finite background-time grant, the Studio cancellation and its return notice,
/// and the screen-awake hold while generating. The decisions live in
/// `IOSBackgroundGenerationPolicy`; this type only applies them to UIKit and
/// to the Studio's `AppModel`, which `QVoiceiOSRootView` attaches once its
/// state is installed.
@MainActor
final class IOSBackgroundGenerationController {
    private weak var appModel: AppModel?
    private var backgroundTask: UIBackgroundTaskIdentifier = .invalid
    private var screenAwakeHold = IOSGenerationScreenAwakeHold()

    func attach(_ appModel: AppModel) {
        self.appModel = appModel
    }

    var studioWork: IOSBackgroundGenerationWork {
        appModel?.activeStudioWork ?? .idle
    }

    /// Requests background time so the cancellation barrier and the runtime
    /// release can finish before suspension. Idempotent while a grant is held.
    func beginBackgroundTime() {
        guard backgroundTask == .invalid else { return }
        backgroundTask = UIApplication.shared.beginBackgroundTask(
            withName: "vocello.generation.foreground-exit"
        ) { [weak self] in
            // Expiration: give the grant back; suspension proceeds.
            self?.endBackgroundTime()
        }
    }

    func endBackgroundTime() {
        guard backgroundTask != .invalid else { return }
        let task = backgroundTask
        backgroundTask = .invalid
        UIApplication.shared.endBackgroundTask(task)
    }

    /// Cancels the Studio's running attempt through its typed barrier and records
    /// the notice for return. Returns `false` when no attempt accepted it.
    @discardableResult
    func interruptStudio(
        _ interruption: IOSBackgroundInterruption,
        reason: GenerationCancellationReason,
        ttsEngine: TTSEngineStore,
        audioPlayer: AudioPlayerViewModel
    ) -> Bool {
        appModel?.interruptStudioGeneration(
            interruption,
            reason: reason,
            ttsEngine: ttsEngine,
            audioPlayer: audioPlayer
        ) ?? false
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
