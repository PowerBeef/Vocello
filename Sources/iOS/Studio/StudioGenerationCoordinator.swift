import Accessibility
import Foundation
import Observation
import QwenVoiceCore

/// Per-mode generation lifecycle state. Lifted out of the three legacy
/// per-mode views (`IOSCustomVoiceView`, `IOSVoiceDesignView`,
/// `IOSVoiceCloningView`) where it used to live as scattered `@State`.
///
/// `AppModel` owns three instances (one per `GenerationMode`). Views
/// read state via `@Environment(AppModel.self)` and mutate via the
/// attempt-scoped lifecycle methods. `start()` returns the token required by
/// every asynchronous terminal callback.
///
/// On iOS the per-mode views assemble mode-specific `GenerationRequest`
/// payloads from their drafts + speakers + delivery state and run the take
/// through `IOSSingleTakeGenerationExecutor`; on macOS the views hand an
/// immutable plan to `MacStudioGenerationActions`, whose
/// `MacStudioSingleTakeRunner` starts the take and installs its task here
/// (AUD-03). UI-visible state (`isGenerating`, `errorMessage`,
/// `lastCompletedOutput`) flows through this Observable so the unified
/// StudioScreen + StudioDock can react without per-mode branching. The
/// shared cancel paths are `IOSStudioGenerationActions.cancelGeneration`
/// and `MacStudioGenerationActions.cancelGeneration`.
@MainActor
@Observable
final class StudioGenerationCoordinator {
    let mode: GenerationMode
    private var attemptAuthority = StudioGenerationAttemptAuthority()

    /// `true` while a generation request is in flight. Drives the
    /// generating-state animation + Cancel button in the dock area.
    private(set) var isGenerating: Bool = false

    /// Last error surfaced to the user. Cleared when a fresh attempt
    /// starts.
    private(set) var errorMessage: String?

    /// The most-recently completed take, surfaced as an inline player
    /// card. Nil while no take has completed (or after Dismiss).
    private(set) var lastCompletedOutput: IOSStudioInlinePlayerItem?

    /// In-flight generation task, retained so callers can cancel it.
    private(set) var generationTask: Task<Void, Never>?

    /// Metadata for the live-preview dock card, set when a streaming attempt
    /// starts and cleared on any terminal transition. The dock shows the live
    /// card only while this is non-nil AND the shared player is actually
    /// streaming audible audio (see `studioGenState`).
    private(set) var liveItem: IOSStudioLivePreviewItem?

    /// Notice for work the foreground exit stopped (PA-15), shown once the user is back.
    private var backgroundNotice = IOSBackgroundInterruptionNoticeState()

    /// Copy in the platform's interface language: `IOSAppLanguage` on iOS,
    /// `MacInterfaceText` on macOS (PA-20).
    @ObservationIgnored private let presentation: @MainActor () -> VocelloPresentationText

    var activeAttempt: StudioGenerationAttemptToken? {
        attemptAuthority.currentToken
    }

    /// Whether `attempt` has an accepted cancellation, before or after its task is cancelled.
    func isCancellationRequested(for attempt: StudioGenerationAttemptToken) -> Bool {
        attemptAuthority.isCancelling(attempt)
    }

    /// `true` while the current attempt runs and no cancellation barrier is pending.
    var isAttemptRunning: Bool {
        guard let attempt = attemptAuthority.currentToken else { return false }
        return attemptAuthority.isRunning(attempt)
    }

    /// The foreground-exit interruption to tell the user about, once they are back.
    var backgroundInterruptionNotice: IOSBackgroundInterruption? {
        backgroundNotice.presented
    }

    /// Localized copy for `backgroundInterruptionNotice`.
    var backgroundInterruptionNoticeMessage: String? {
        switch backgroundNotice.presented {
        case .singleTakeDiscarded:
            return presentation().backgroundTakeStopped
        case .longFormStopped:
            return presentation().backgroundLongFormStopped
        case nil:
            return nil
        }
    }

    init(
        mode: GenerationMode,
        presentation: @escaping @MainActor () -> VocelloPresentationText = { IOSAppLanguage.shared.presentation }
    ) {
        self.mode = mode
        self.presentation = presentation
    }

    /// Marks a generation attempt as started. Clears any prior error.
    /// Pass `live:` to enable the live-preview dock card for streaming runs.
    @discardableResult
    func start(
        live: IOSStudioLivePreviewItem? = nil
    ) -> StudioGenerationAttemptToken? {
        guard let attempt = attemptAuthority.begin() else { return nil }
        errorMessage = nil
        backgroundNotice.clear()
        lastCompletedOutput = nil
        liveItem = live
        isGenerating = true
        StudioGenerationAnnouncer.post(presentation().announceGenerationStarted)
        return attempt
    }

    /// Installs the task only while the matching attempt is current. A task that
    /// loses the race with a terminal transition is cancelled rather than retained.
    func installGenerationTask(
        _ task: Task<Void, Never>,
        for attempt: StudioGenerationAttemptToken
    ) {
        guard attemptAuthority.isRunning(attempt) else {
            task.cancel()
            return
        }
        generationTask = task
    }

    /// Requests cancellation and returns the token owned by the engine barrier.
    /// The coordinator deliberately remains nonterminal until that barrier reports.
    /// Pass `cancelsTask: false` when a typed non-user reason must reach the
    /// engine barrier before the Swift task is cancelled (`IOSStudioCancellationOrder`);
    /// the caller then calls `cancelGenerationTask()` once the barrier returns.
    @discardableResult
    func requestCancellation(cancelsTask: Bool = true) -> StudioGenerationAttemptToken? {
        guard let attempt = attemptAuthority.currentToken,
              attemptAuthority.requestCancellation(attempt) else { return nil }
        if cancelsTask {
            generationTask?.cancel()
        }
        return attempt
    }

    /// Cancels the retained Swift generation task (see `requestCancellation(cancelsTask:)`).
    func cancelGenerationTask() {
        generationTask?.cancel()
    }

    /// Marks a normally finishing in-flight attempt as terminal. Generation task
    /// completion cannot clear an attempt whose cancellation barrier is pending.
    @discardableResult
    func finish(attempt: StudioGenerationAttemptToken) -> Bool {
        guard attemptAuthority.finishGeneration(attempt) else { return false }
        clearTerminalState()
        return true
    }

    /// Applies a live-preview update only to the current running attempt.
    @discardableResult
    func updateLiveItem(
        _ item: IOSStudioLivePreviewItem?,
        attempt: StudioGenerationAttemptToken
    ) -> Bool {
        guard attemptAuthority.isRunning(attempt) else { return false }
        liveItem = item
        return true
    }

    /// Completes a requested cancellation (user or foreground exit) after the engine terminal barrier.
    @discardableResult
    func completeCancellation(attempt: StudioGenerationAttemptToken) -> Bool {
        guard attemptAuthority.completeCancellation(attempt) else { return false }
        errorMessage = nil
        clearTerminalState()
        StudioGenerationAnnouncer.post(presentation().announceGenerationStopped)
        return true
    }

    /// Surfaces a cancellation barrier failure. The engine store keeps its own
    /// active-generation ownership, so subsequent generation remains gated there.
    @discardableResult
    func failCancellation(
        _ error: any Error,
        attempt: StudioGenerationAttemptToken
    ) -> Bool {
        guard attemptAuthority.failCancellation(attempt) else { return false }
        // The error explains the failed barrier; a background notice claiming
        // the work stopped cleanly would contradict it.
        backgroundNotice.clear()
        let message = presentation().cancellationCouldNotFinish(
            details: presentation().generationFailureMessage(error)
        )
        errorMessage = message
        clearTerminalState()
        StudioGenerationAnnouncer.post(presentation().announceGenerationFailed(message))
        return true
    }

    /// Presents a synchronous validation/precondition error when no attempt exists.
    func rejectStart(_ message: String) {
        guard attemptAuthority.currentToken == nil else { return }
        errorMessage = message
    }

    private func clearTerminalState() {
        isGenerating = false
        generationTask = nil
        liveItem = nil
    }

    /// Surfaces a completed take to the dock area + clears in-flight.
    @discardableResult
    func complete(
        _ item: IOSStudioInlinePlayerItem,
        attempt: StudioGenerationAttemptToken
    ) -> Bool {
        guard attemptAuthority.finishGeneration(attempt) else { return false }
        lastCompletedOutput = item
        clearTerminalState()
        StudioGenerationAnnouncer.post(presentation().announceTakeReady)
        return true
    }

    /// Sets an error and clears the in-flight flag.
    @discardableResult
    func fail(
        _ message: String,
        attempt: StudioGenerationAttemptToken
    ) -> Bool {
        guard attemptAuthority.finishGeneration(attempt) else { return false }
        errorMessage = message
        clearTerminalState()
        StudioGenerationAnnouncer.post(presentation().announceGenerationFailed(message))
        return true
    }

    /// Clears the inline player (user dismissed it).
    func dismissInlinePlayer() {
        lastCompletedOutput = nil
    }

    // MARK: - Foreground exit (PA-15)

    /// Records that the foreground exit cancelled this coordinator's attempt.
    /// The notice stays hidden until `presentBackgroundInterruptionNoticeIfPending()`.
    func recordBackgroundInterruption(_ interruption: IOSBackgroundInterruption) {
        backgroundNotice.record(interruption)
    }

    /// Called when the scene is active again: surfaces a recorded interruption.
    func presentBackgroundInterruptionNoticeIfPending() {
        backgroundNotice.presentOnReturn()
    }

    /// The user acknowledged the notice.
    func dismissBackgroundInterruptionNotice() {
        backgroundNotice.clear()
    }
}

/// VoiceOver announcements for Studio generation state changes (PA-20, IOS-12):
/// one per transition of an attempt (started, take ready, failed, stopped),
/// never for progress, so a long take or project is not narrated. Focus stays
/// where it is; the announcement tells a VoiceOver user what changed off-screen.
@MainActor
enum StudioGenerationAnnouncer {
    static func post(_ message: String) {
        guard !message.isEmpty else { return }
        AccessibilityNotification.Announcement(message).post()
    }
}
