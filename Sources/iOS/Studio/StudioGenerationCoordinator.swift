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
/// The actual `await ttsEngine.generate(...)` call deliberately lives
/// in the per-mode views (final architecture, not a TODO) — they
/// assemble mode-specific `GenerationRequest` payloads from their
/// drafts + speakers + delivery state and the environment-owned engine
/// stores — while UI-visible state (`isGenerating`, `errorMessage`,
/// `lastCompletedOutput`) flows through this Observable so the unified
/// StudioScreen + StudioDock can react without per-mode branching. The
/// shared cancel path is `IOSStudioGenerationActions.cancelGeneration`.
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

    var activeAttempt: StudioGenerationAttemptToken? {
        attemptAuthority.currentToken
    }

    init(mode: GenerationMode) {
        self.mode = mode
    }

    /// Marks a generation attempt as started. Clears any prior error.
    /// Pass `live:` to enable the live-preview dock card for streaming runs.
    @discardableResult
    func start(
        live: IOSStudioLivePreviewItem? = nil
    ) -> StudioGenerationAttemptToken? {
        guard let attempt = attemptAuthority.begin() else { return nil }
        errorMessage = nil
        lastCompletedOutput = nil
        liveItem = live
        isGenerating = true
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
    @discardableResult
    func requestCancellation() -> StudioGenerationAttemptToken? {
        guard let attempt = attemptAuthority.currentToken,
              attemptAuthority.requestCancellation(attempt) else { return nil }
        generationTask?.cancel()
        return attempt
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

    /// Completes the user-requested cancellation after the engine terminal barrier.
    @discardableResult
    func completeCancellation(attempt: StudioGenerationAttemptToken) -> Bool {
        guard attemptAuthority.completeCancellation(attempt) else { return false }
        errorMessage = nil
        clearTerminalState()
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
        errorMessage = VocelloPresentationText.cancellationCouldNotFinish(
            details: error.localizedDescription
        )
        clearTerminalState()
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
        return true
    }

    /// Clears the inline player (user dismissed it).
    func dismissInlinePlayer() {
        lastCompletedOutput = nil
    }
}
