import Foundation

/// The MCP server's engine requests run one at a time (RF-29): a call that
/// finds the engine busy waits its turn in arrival order, and once
/// `maxQueue` calls are waiting the next is refused as `engine_busy`, which an
/// agent retries. A waiting call that is cancelled leaves the queue.
@MainActor
final class MCPEngineGate {
    let maxQueue: Int
    private var running = false
    private var waiters: [(id: UUID, continuation: CheckedContinuation<Void, any Error>)] = []

    init(maxQueue: Int) {
        self.maxQueue = maxQueue
    }

    var isRunning: Bool { running }
    var waiting: Int { waiters.count }

    /// Takes the engine, waiting for it if needed. Each successful `enter` is
    /// paired with one `leave`.
    func enter() async throws {
        try Task.checkCancellation()
        guard running else {
            running = true
            return
        }
        guard waiters.count < maxQueue else {
            throw CLIError(
                .engineBusy, "the engine is busy and \(waiters.count) requests are waiting",
                hint: "retry when a request finishes"
            )
        }
        let id = UUID()
        try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                waiters.append((id, continuation))
            }
        } onCancel: {
            Task { @MainActor in self.withdraw(id) }
        }
        // Handed the engine just as its cancellation arrived: it passes it on unused.
        if Task.isCancelled {
            leave()
            throw CancellationError()
        }
    }

    /// Gives the engine to the next waiting call, if any.
    func leave() {
        if waiters.isEmpty {
            running = false
        } else {
            waiters.removeFirst().continuation.resume()
        }
    }

    private func withdraw(_ id: UUID) {
        guard let index = waiters.firstIndex(where: { $0.id == id }) else { return }
        waiters.remove(at: index).continuation.resume(throwing: CancellationError())
    }
}
