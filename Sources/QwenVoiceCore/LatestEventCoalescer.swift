import Foundation
import os

/// Thread-safe coalescing slot for stripped `GenerationEvent` snapshots.
/// The MLX producer may call `push` from a background executor; a single
/// long-lived MainActor drain task observes updates without allocating
/// one `Task { @MainActor }` per streamed chunk.
final class LatestEventCoalescer: @unchecked Sendable {
    private struct State {
        var pending: GenerationEvent?
        var waiter: CheckedContinuation<Void, Never>?
    }

    private let lock = OSAllocatedUnfairLock(initialState: State())

    func push(_ event: GenerationEvent) {
        lock.withLock { state in
            state.pending = event
            state.waiter?.resume()
            state.waiter = nil
        }
    }

    func take() -> GenerationEvent? {
        lock.withLock { state in
            let event = state.pending
            state.pending = nil
            return event
        }
    }

    @concurrent func waitForUpdate() async {
        let shouldResumeImmediately = lock.withLock { state -> Bool in
            if state.pending != nil {
                return true
            }
            return false
        }
        if shouldResumeImmediately {
            return
        }

        await withTaskCancellationHandler { @concurrent in
            await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
                let resumedImmediately = lock.withLock { state -> Bool in
                    if state.pending != nil {
                        return true
                    }
                    state.waiter = continuation
                    return false
                }
                if resumedImmediately {
                    continuation.resume()
                }
            }
        } onCancel: {
            // Wake a suspended drain so its `while !Task.isCancelled` loop can
            // exit, instead of leaking the task + continuation if the owner is
            // torn down without a matching `clear()`. All resume sites nil the
            // waiter under the lock, so there is no double-resume.
            lock.withLock { state in
                state.waiter?.resume()
                state.waiter = nil
            }
        }
    }

    func clear() {
        lock.withLock { state in
            state.pending = nil
            state.waiter?.resume()
            state.waiter = nil
        }
    }
}
