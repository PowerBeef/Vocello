import Foundation

/// AUD-01: startup is one owned, retryable operation. A pass begins from idle
/// or after a failure, never while one is running or once the dependencies
/// exist, and only the running pass may finish. `IOSAppDependenciesContainer`
/// drives it; its Retry button begins the next pass.
struct IOSStartupAttempt: Equatable {
    enum Phase: Equatable {
        case idle
        case starting
        /// The last pass failed; the container shows its error with Retry.
        case failed
        case ready
    }

    private(set) var phase: Phase = .idle

    var isStarting: Bool { phase == .starting }

    /// Starts a pass when one may run; false leaves the state unchanged.
    mutating func begin() -> Bool {
        switch phase {
        case .idle, .failed:
            phase = .starting
            return true
        case .starting, .ready:
            return false
        }
    }

    /// Ends the running pass: ready on success, failed (and retryable) otherwise.
    mutating func finish(succeeded: Bool) {
        guard phase == .starting else { return }
        phase = succeeded ? .ready : .failed
    }
}

/// AUD-01: a file the system opens into Vocello waits here until the app can
/// show its import: the root view is on screen (startup finished) and the
/// first-run onboarding is gone, so the import cover never competes with the
/// onboarding cover and a cold-launch open is not lost while startup runs. One
/// import cover shows at a time, so a later open replaces one still waiting,
/// and each file is handed out once.
struct IOSExternalImportQueue: Equatable {
    private(set) var pending: URL?

    mutating func enqueue(_ url: URL) {
        pending = url
    }

    /// The waiting file, removed from the queue, when its import can be shown now.
    mutating func take(onboardingIsPresented: Bool) -> URL? {
        guard !onboardingIsPresented, let url = pending else { return nil }
        pending = nil
        return url
    }
}
