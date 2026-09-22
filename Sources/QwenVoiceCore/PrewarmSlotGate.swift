import Foundation
import os

/// The single slot that serializes MLX prewarm bodies (and memory trims) in
/// `NativeEngineRuntime`. The actor mutex alone is not enough: a prewarm body
/// suspends inside MLX, and the actor may start another prewarm meanwhile.
///
/// Contract: when `acquire()` returns, the caller holds the slot and must call
/// `release()` exactly once; when it throws, the caller does not hold it. A
/// waiter cancelled after `release()` has already handed it the slot gives the
/// slot back before throwing, so a finished caller can never leave the gate
/// held forever.
final class PrewarmSlotGate: Sendable {
    private struct Waiter {
        let id: UUID
        let continuation: CheckedContinuation<Void, any Error>
    }

    private struct State {
        var isHeld = false
        var waiters: [Waiter] = []
    }

    private enum Admission {
        case acquired
        case queued
        case refused
    }

    private let storage = OSAllocatedUnfairLock(initialState: State())

    var isHeld: Bool { storage.withLock { $0.isHeld } }
    var waiterCount: Int { storage.withLock { $0.waiters.count } }

    /// Waits until no other holder remains, then takes the slot. Returns the
    /// milliseconds spent queued (`0` when the slot was free). Runs on the
    /// caller's actor, so a free slot is taken without a suspension point.
    func acquire(isolation: isolated (any Actor)? = #isolation) async throws -> Int {
        try Task.checkCancellation()
        let startedAt = ContinuousClock.now
        let takenImmediately = storage.withLock { state -> Bool in
            guard !state.isHeld else { return false }
            state.isHeld = true
            return true
        }
        if takenImmediately { return 0 }

        let id = UUID()
        try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, any Error>) in
                // Cancellation sets the flag before its handler runs, and the
                // handler takes the same lock, so checking the flag here closes
                // the window between queueing and a cancel that found no waiter.
                let admission = storage.withLock { state -> Admission in
                    if Task.isCancelled { return .refused }
                    if !state.isHeld {
                        state.isHeld = true
                        return .acquired
                    }
                    state.waiters.append(Waiter(id: id, continuation: continuation))
                    return .queued
                }
                switch admission {
                case .acquired: continuation.resume()
                case .refused: continuation.resume(throwing: CancellationError())
                case .queued: break
                }
            }
        } onCancel: {
            let removed = storage.withLock { state -> CheckedContinuation<Void, any Error>? in
                guard let index = state.waiters.firstIndex(where: { $0.id == id }) else { return nil }
                return state.waiters.remove(at: index).continuation
            }
            removed?.resume(throwing: CancellationError())
        }

        // The slot is ours now. A cancellation that arrived after the hand-off
        // must give it back before throwing: callers only register their
        // release once acquire returns.
        if Task.isCancelled {
            release()
            throw CancellationError()
        }
        return startedAt.elapsedMilliseconds
    }

    /// Frees the slot, or hands it directly to the oldest waiter.
    func release() {
        let next = storage.withLock { state -> CheckedContinuation<Void, any Error>? in
            guard !state.waiters.isEmpty else {
                state.isHeld = false
                return nil
            }
            state.isHeld = true
            return state.waiters.removeFirst().continuation
        }
        next?.resume()
    }
}
