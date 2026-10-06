import Foundation

/// Stable identity for one visible Studio generation lifecycle.
///
/// The token is deliberately separate from engine generation identity: long-form projects own
/// several engine generations while presenting one Studio attempt. UI terminal callbacks must
/// carry this value so a delayed callback cannot mutate a newer attempt.
struct StudioGenerationAttemptToken: Hashable, Sendable {
    let rawValue: UUID

    init(rawValue: UUID = UUID()) {
        self.rawValue = rawValue
    }
}

/// Pure transition authority for the iOS Studio lifecycle.
///
/// Generation completion/failure is accepted while running or finalizing. Once cancellation is
/// requested, only the cancellation barrier may make the attempt terminal. Once the engine has
/// returned the take and its completion (History, export) has begun, the attempt is finalizing and
/// a cancellation is refused: a take the user was told is stopped must never land in History.
/// Every stale or mismatched event is rejected without changing the current attempt.
struct StudioGenerationAttemptAuthority: Sendable {
    enum Phase: String, Equatable, Sendable {
        case running
        case finalizing
        case cancelling
    }

    private(set) var currentToken: StudioGenerationAttemptToken?
    private(set) var phase: Phase?

    mutating func begin(
        token: StudioGenerationAttemptToken = StudioGenerationAttemptToken()
    ) -> StudioGenerationAttemptToken? {
        guard currentToken == nil, phase == nil else { return nil }
        currentToken = token
        phase = .running
        return token
    }

    func isCurrent(_ token: StudioGenerationAttemptToken) -> Bool {
        currentToken == token
    }

    func isRunning(_ token: StudioGenerationAttemptToken) -> Bool {
        currentToken == token && phase == .running
    }

    func isCancelling(_ token: StudioGenerationAttemptToken) -> Bool {
        currentToken == token && phase == .cancelling
    }

    mutating func requestCancellation(_ token: StudioGenerationAttemptToken) -> Bool {
        guard currentToken == token else { return false }
        switch phase {
        case .running:
            phase = .cancelling
            return true
        case .finalizing, .cancelling:
            return false
        case nil:
            return false
        }
    }

    /// The engine returned the take; its completion starts now and can no longer be cancelled.
    mutating func beginFinalization(_ token: StudioGenerationAttemptToken) -> Bool {
        guard isRunning(token) else { return false }
        phase = .finalizing
        return true
    }

    mutating func finishGeneration(_ token: StudioGenerationAttemptToken) -> Bool {
        guard currentToken == token, phase == .running || phase == .finalizing else { return false }
        clear()
        return true
    }

    mutating func completeCancellation(_ token: StudioGenerationAttemptToken) -> Bool {
        guard isCancelling(token) else { return false }
        clear()
        return true
    }

    mutating func failCancellation(_ token: StudioGenerationAttemptToken) -> Bool {
        guard isCancelling(token) else { return false }
        clear()
        return true
    }

    private mutating func clear() {
        currentToken = nil
        phase = nil
    }
}
