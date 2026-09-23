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
/// shutdown reason, then run the (deferred) runtime release, which executes
/// only after the barrier has returned.
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
        case .singleTake:
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
