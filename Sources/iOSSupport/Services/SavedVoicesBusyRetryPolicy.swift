import Foundation

/// Bounded automatic retries while another Vocello process holds the Saved
/// Voice store (F-25): 1 s, 2 s, then 4 s, at most three attempts, and a fresh
/// schedule after a successful load or an explicit reset. The screens' own
/// refresh and retry controls stay available once the attempts are spent.
public struct SavedVoicesBusyRetryPolicy: Equatable, Sendable {
    public static let delays: [Duration] = [.seconds(1), .seconds(2), .seconds(4)]

    public private(set) var attemptsUsed = 0

    public init() {}

    public var maximumAttempts: Int { Self.delays.count }
    public var isExhausted: Bool { attemptsUsed >= maximumAttempts }

    /// Consumes and returns the delay before the next retry, or nil once the
    /// cap is reached.
    public mutating func nextDelay() -> Duration? {
        guard !isExhausted else { return nil }
        let delay = Self.delays[attemptsUsed]
        attemptsUsed += 1
        return delay
    }

    public mutating func reset() {
        attemptsUsed = 0
    }
}
