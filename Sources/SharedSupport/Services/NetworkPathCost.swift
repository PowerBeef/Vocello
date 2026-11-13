import Foundation
import Network
import Synchronization

/// RF-59: the current network's cost, for a download nobody asked for (the model update after an
/// app update from an earlier Vocello). Read once per call from a fresh path monitor.
enum NetworkPathCost {
    struct Reading: Equatable, Sendable {
        let isSatisfied: Bool
        /// A phone's hotspot or cellular data.
        let isExpensive: Bool
        /// Low Data Mode.
        let isConstrained: Bool

        /// Connected, and neither expensive nor constrained.
        var allowsAutomaticDownloads: Bool { isSatisfied && !isExpensive && !isConstrained }
    }

    private final class FirstAnswer: Sendable {
        private let taken = Mutex(false)

        /// `true` for the first caller only.
        func claim() -> Bool {
            taken.withLock { taken in
                defer { taken = true }
                return !taken
            }
        }
    }

    /// No answer within `timeout` (no path update arrived) reads as an unknown, costly network:
    /// not connected, expensive and constrained, so nothing starts on it on either platform.
    static func current(timeout: DispatchTimeInterval = .seconds(3)) async -> Reading {
        await withCheckedContinuation { (continuation: CheckedContinuation<Reading, Never>) in
            let monitor = NWPathMonitor()
            let answer = FirstAnswer()
            let queue = DispatchQueue(label: "com.qwenvoice.network-cost", qos: .utility)
            monitor.pathUpdateHandler = { path in
                guard answer.claim() else { return }
                monitor.pathUpdateHandler = nil
                monitor.cancel()
                continuation.resume(returning: Reading(
                    isSatisfied: path.status == .satisfied,
                    isExpensive: path.isExpensive,
                    isConstrained: path.isConstrained
                ))
            }
            monitor.start(queue: queue)
            queue.asyncAfter(deadline: .now() + timeout) {
                guard answer.claim() else { return }
                monitor.pathUpdateHandler = nil
                monitor.cancel()
                continuation.resume(returning: Reading(isSatisfied: false, isExpensive: true, isConstrained: true))
            }
        }
    }
}
