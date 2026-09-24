import Foundation
import QwenVoiceCore

/// What the Studio owns when the app leaves the foreground (PA-15).
///
/// iOS refuses GPU work from a suspended app, so a take cannot keep running
/// once the scene reaches `.background`. The maintainer decision (2026-09-22)
/// is to cancel through the typed barrier, keep finished long-form segments and
/// tell the user on return.
enum IOSBackgroundGenerationWork: Equatable, Sendable {
    /// No Studio attempt is running.
    case idle
    /// A short-form take is running; cancelling discards it (it never reaches History).
    case singleTake
    /// A long-form project is running; cancelling keeps its completed segments for Resume.
    case longForm
    /// One segment of a completed long-form project is being regenerated;
    /// cancelling discards the new take and keeps the completed project as it was.
    case segmentRegeneration
    /// A Studio cancellation barrier is already pending; it only has to finish.
    case cancelling
}

/// What the user is told on return after the foreground exit stopped Studio work.
enum IOSBackgroundInterruption: Equatable, Sendable {
    case singleTakeDiscarded
    case longFormStopped
}

/// The ordered foreground-exit sequence for one `.background` transition:
/// request finite background time, cancel through the typed barrier with the
/// shutdown reason, and request the runtime release only after that barrier
/// has returned (see `IOSForegroundExitState`).
struct IOSBackgroundTransitionPlan: Equatable, Sendable {
    /// Ask the system for background time so the barrier and release can
    /// finish before suspension. Ended when the release completes or expires.
    let requestsBackgroundTime: Bool
    /// Studio work to cancel through its coordinator, with the notice to show on return.
    let studioInterruption: IOSBackgroundInterruption?
    /// Engine work that no Studio attempt owns still has to stop before suspension.
    let cancelsUnownedEngineGeneration: Bool
    /// Typed reason for every cancellation this transition issues.
    let cancellationReason: GenerationCancellationReason
    /// Reason of the runtime release requested after the cancellation.
    let releaseReason: String
}

/// Pure decisions behind the iOS foreground-exit handling. The app-only scene
/// handler (`QVoiceiOSApp`) and `AppModel` apply them; tests pin them here.
enum IOSBackgroundGenerationPolicy {
    /// Runtime-release reason owned by the foreground exit.
    static let releaseReason = "background"
    /// Leaving the foreground is a shutdown of in-flight work, not a user cancel.
    static let cancellationReason: GenerationCancellationReason = .shutdown

    static func backgroundPlan(
        hasActiveGeneration: Bool,
        studioWork: IOSBackgroundGenerationWork
    ) -> IOSBackgroundTransitionPlan {
        let studioInterruption: IOSBackgroundInterruption?
        switch studioWork {
        case .singleTake, .segmentRegeneration:
            studioInterruption = .singleTakeDiscarded
        case .longForm:
            studioInterruption = .longFormStopped
        case .idle, .cancelling:
            studioInterruption = nil
        }
        return IOSBackgroundTransitionPlan(
            requestsBackgroundTime: hasActiveGeneration || studioWork != .idle,
            studioInterruption: studioInterruption,
            cancelsUnownedEngineGeneration: hasActiveGeneration && studioWork == .idle,
            cancellationReason: cancellationReason,
            releaseReason: releaseReason
        )
    }
}

/// Order of the two halves of a Studio cancellation.
///
/// The engine keeps the first typed reason it receives, and cancelling the
/// Swift task that awaits the engine reports `.user` from its cancellation
/// handler. A non-user reason (the foreground exit's `.shutdown`) therefore
/// goes through the engine barrier first; the Swift task is cancelled once the
/// barrier returns, which still stops work that had not reached the engine.
enum IOSStudioCancellationOrder: Equatable, Sendable {
    /// User Stop: cancel the Swift task immediately, then await the barrier.
    case taskThenBarrier
    /// Typed non-user reason: await the barrier, then cancel the Swift task.
    case barrierThenTask

    static func forReason(_ reason: GenerationCancellationReason) -> IOSStudioCancellationOrder {
        reason == .user ? .taskThenBarrier : .barrierThenTask
    }
}

/// Sequencing of one foreground exit and its background-time grant.
///
/// Each `.background` transition opens an exit epoch. The runtime release is
/// requested only after that exit's cancellation barrier returned while the app
/// is still in the background, and the grant ends only when no exit is still
/// waiting on its barrier and no release is running, queued or pending for the
/// foreground exit, so an earlier release can never end a newer grant.
struct IOSForegroundExitState: Equatable, Sendable {
    private(set) var epoch: UInt64 = 0
    private(set) var isBackgrounded = false
    /// The current exit's barrier has not returned, so its release is not requested yet.
    private(set) var awaitsBarrier = false

    /// Starts an exit and returns its epoch.
    mutating func enterBackground() -> UInt64 {
        epoch &+= 1
        isBackgrounded = true
        awaitsBarrier = true
        return epoch
    }

    /// The exit's cancellation barrier returned. `true` when the release must be
    /// requested now; `false` when the user came back (or a newer exit began).
    mutating func barrierReturned(for exitEpoch: UInt64) -> Bool {
        guard isBackgrounded, exitEpoch == epoch else { return false }
        awaitsBarrier = false
        return true
    }

    /// The scene is active again; any in-flight exit is superseded.
    mutating func returnToForeground() {
        epoch &+= 1
        isBackgrounded = false
        awaitsBarrier = false
    }

    /// A runtime release finished. `true` when the background-time grant may end.
    func endsBackgroundTime(
        followUpReleaseExecutes: Bool,
        pendingReleaseReason: String?
    ) -> Bool {
        !awaitsBarrier
            && !followUpReleaseExecutes
            && pendingReleaseReason != IOSBackgroundGenerationPolicy.releaseReason
    }
}

/// When the History database may hold SQLite locks (IOS-11).
///
/// History lives in the App Group container, and iOS terminates an app that is
/// suspended while holding a lock on a shared file (0xDEAD10CC). The database is
/// suspended only once the app is about to be suspended: it left the foreground
/// without a background-time grant, or that grant ended (completed or expired)
/// while the app is still in the background. Work the grant covers, such as a
/// long-form acceptance awaited by the cancellation barrier, finishes first. The
/// database resumes as soon as the scene is active again, and the app then
/// reconciles History so a write the suspension deferred commits.
struct IOSHistoryDatabaseSuspensionState: Equatable, Sendable {
    enum Transition: Equatable, Sendable {
        case suspend
        case resume
    }

    private(set) var isSuspended = false

    /// The scene left the foreground; `holdsBackgroundTime` is whether a grant is running.
    mutating func enterBackground(holdsBackgroundTime: Bool) -> Transition? {
        holdsBackgroundTime ? nil : suspend()
    }

    /// The background-time grant ended. Suspends only while still backgrounded.
    mutating func backgroundTimeEnded(isBackgrounded: Bool) -> Transition? {
        isBackgrounded ? suspend() : nil
    }

    /// The scene is active again.
    mutating func returnToForeground() -> Transition? {
        guard isSuspended else { return nil }
        isSuspended = false
        return .resume
    }

    private mutating func suspend() -> Transition? {
        guard !isSuspended else { return nil }
        isSuspended = true
        return .suspend
    }
}

/// Keeps the screen awake while a generation runs, without taking over an
/// idle-timer hold someone else (the headless diagnostics runner) placed.
///
/// `update` returns the value to assign to `UIApplication.isIdleTimerDisabled`,
/// or `nil` when it must be left alone.
struct IOSGenerationScreenAwakeHold: Equatable, Sendable {
    /// True only while this hold is the one that disabled the idle timer.
    private(set) var ownsIdleTimerHold = false

    mutating func update(isGenerating: Bool, idleTimerDisabled: Bool) -> Bool? {
        if isGenerating {
            guard !idleTimerDisabled else { return nil }
            ownsIdleTimerHold = true
            return true
        }
        guard ownsIdleTimerHold else { return nil }
        ownsIdleTimerHold = false
        return false
    }
}

/// Per-coordinator notice state: recorded when the foreground exit stops an
/// attempt, shown only once the user is back, cleared on dismissal, a new
/// attempt or a failed cancellation (which surfaces its own error).
struct IOSBackgroundInterruptionNoticeState: Equatable, Sendable {
    private(set) var pending: IOSBackgroundInterruption?
    private(set) var presented: IOSBackgroundInterruption?

    mutating func record(_ interruption: IOSBackgroundInterruption) {
        pending = interruption
        presented = nil
    }

    mutating func presentOnReturn() {
        guard let pending else { return }
        presented = pending
        self.pending = nil
    }

    mutating func clear() {
        pending = nil
        presented = nil
    }
}
