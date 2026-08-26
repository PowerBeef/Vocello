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
/// Generation completion/failure is accepted only while running. Once cancellation is requested,
/// only the cancellation barrier may make the attempt terminal. Every stale or mismatched event is
/// rejected without changing the current attempt.
struct StudioGenerationAttemptAuthority: Sendable {
    enum Phase: String, Equatable, Sendable {
        case running
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
        case .cancelling:
            return false
        case nil:
            return false
        }
    }

    mutating func finishGeneration(_ token: StudioGenerationAttemptToken) -> Bool {
        guard isRunning(token) else { return false }
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
