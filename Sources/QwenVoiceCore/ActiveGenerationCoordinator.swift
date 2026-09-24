import Foundation
import os

/// Synchronous first-reason ingress shared by the product admission owner and
/// the runtime output adapter.
///
/// `Task.cancel()` carries no typed reason. The admission coordinator records
/// that reason before cancellation and this bridge delivers it to the
/// classified runtime session, including when cancellation wins before the
/// adapter has installed its handler.
final class GenerationCancellationIngress: Sendable {
    private struct State {
        var reason: GenerationCancellationReason?
        var handler: (@Sendable (GenerationCancellationReason) -> Void)?
    }

    private let storage = OSAllocatedUnfairLock(initialState: State())

    var reason: GenerationCancellationReason? {
        storage.withLock { $0.reason }
    }

    @discardableResult
    func request(_ reason: GenerationCancellationReason) -> Bool {
        let decision = storage.withLock { state -> (
            accepted: Bool,
            handler: (@Sendable (GenerationCancellationReason) -> Void)?
        ) in
            guard state.reason == nil else { return (false, nil) }
            state.reason = reason
            return (true, state.handler)
        }
        decision.handler?(reason)
        return decision.accepted
    }

    func install(
        _ handler: @escaping @Sendable (GenerationCancellationReason) -> Void
    ) {
        let pending = storage.withLock { state -> GenerationCancellationReason? in
            state.handler = handler
            return state.reason
        }
        if let pending {
            handler(pending)
        }
    }

    func checkCancellation() throws {
        if reason != nil || Task.isCancelled {
            throw CancellationError()
        }
    }
}

/// Main-actor admission latch shared by every memory relief that can release
/// model state: kernel critical relief, caller-requested hard trims and full
/// unloads, and idle unload.
///
/// Model-operation ownership also lives on `MLXTTSEngine`'s main-actor
/// isolation domain. Keeping the latch there makes "gate is open" and
/// "operation became active" one atomic, non-suspending decision. An actor
/// hop here would leave a check-then-enter race between those two states.
///
/// Reliefs may overlap (a caller's full unload while a kernel critical trim is
/// still running), so the latch counts its holders: each `close()` is paired
/// with exactly one `reopen()`, and admission resumes only when the last
/// holder reopens. One relief finishing can never readmit work while another
/// is still releasing state.
@MainActor
final class CriticalMemoryReliefAdmission {
    private struct Waiter {
        let id: UUID
        let continuation: CheckedContinuation<Void, Never>
    }

    private var holderCount = 0
    private var waiters: [Waiter] = []

    var isClosed: Bool {
        holderCount > 0
    }

    var allowsProactiveOperation: Bool {
        !isClosed
    }

    func close() {
        holderCount += 1
    }

    func waitUntilOpen() async throws {
        try Task.checkCancellation()
        while isClosed {
            let waiterID = UUID()
            await withTaskCancellationHandler {
                await withCheckedContinuation { continuation in
                    if Task.isCancelled || !isClosed {
                        continuation.resume()
                    } else {
                        waiters.append(
                            Waiter(id: waiterID, continuation: continuation)
                        )
                    }
                }
            } onCancel: {
                Task { @MainActor in
                    self.cancelWaiter(id: waiterID)
                }
            }
            try Task.checkCancellation()
        }
    }

    func reopen() {
        guard holderCount > 0 else { return }
        holderCount -= 1
        guard holderCount == 0 else { return }
        let pending = waiters
        waiters.removeAll(keepingCapacity: false)
        pending.forEach { $0.continuation.resume() }
    }

    private func cancelWaiter(id: UUID) {
        guard let index = waiters.firstIndex(where: { $0.id == id }) else {
            return
        }
        let waiter = waiters.remove(at: index)
        waiter.continuation.resume()
    }
}

/// Owns the one task that may currently execute model generation.
///
/// Callers register the task's cancellation and terminal wait operations as
/// one unit. `cancelCurrent` does not release ownership until the task has
/// actually terminated, which is the barrier required before a hard trim or
/// model unload can safely begin.
actor ActiveGenerationCoordinator {
    struct Registration: Sendable {
        let id: UUID
    }

    private struct Active: Sendable {
        let id: UUID
        let cancel: @Sendable (GenerationCancellationReason) -> Void
        let waitForTermination: @Sendable () async -> Void
    }

    private var active: Active?
    private var cancellationReason: GenerationCancellationReason?
    private var completedCancellationReasons: [UUID: GenerationCancellationReason] = [:]

    var hasActiveGeneration: Bool {
        active != nil
    }

    func register(
        cancel: @escaping @Sendable (GenerationCancellationReason) -> Void,
        waitForTermination: @escaping @Sendable () async -> Void
    ) throws -> Registration {
        guard active == nil else {
            throw TTSEngineError.generationFailed(
                "The engine is already generating audio. Wait for it to finish or cancel it before starting another generation."
            )
        }
        let id = UUID()
        active = Active(
            id: id,
            cancel: cancel,
            waitForTermination: waitForTermination
        )
        cancellationReason = nil
        return Registration(id: id)
    }

    /// Releases generation ownership and atomically returns the reason that
    /// requested cancellation, if any. The owner must take the reason before
    /// this call clears coordinator state so an early-cancel terminal event
    /// cannot silently fall back to `.user`.
    @discardableResult
    func finish(_ registration: Registration) -> GenerationCancellationReason? {
        if active?.id == registration.id {
            let terminalCancellationReason = cancellationReason
            active = nil
            cancellationReason = nil
            return terminalCancellationReason
        }
        return completedCancellationReasons.removeValue(forKey: registration.id)
    }

    /// Cancels and awaits the current task. Ownership remains active during
    /// the wait, so a concurrent unload cannot mistake cancellation request
    /// acknowledgement for actual compute termination.
    func cancelCurrent(reason: GenerationCancellationReason) async {
        guard let current = active else { return }
        if cancellationReason == nil {
            cancellationReason = reason
            current.cancel(reason)
        }
        await current.waitForTermination()
        if active?.id == current.id {
            if let cancellationReason {
                completedCancellationReasons[current.id] = cancellationReason
            }
            active = nil
            cancellationReason = nil
        }
    }

    func reason(for registration: Registration) -> GenerationCancellationReason? {
        if active?.id == registration.id {
            return cancellationReason
        }
        return completedCancellationReasons[registration.id]
    }

    var currentCancellationReason: GenerationCancellationReason? {
        cancellationReason
    }
}

/// Prevents a newly created unstructured task from entering the runtime until
/// its cancellation and terminal-wait closures are durably registered.
actor GenerationTaskStartGate {
    private var isOpen = false
    private var waiters: [CheckedContinuation<Void, Never>] = []

    func wait() async {
        guard !isOpen else { return }
        await withCheckedContinuation { continuation in
            waiters.append(continuation)
        }
    }

    func open() {
        guard !isOpen else { return }
        isOpen = true
        let pending = waiters
        waiters.removeAll(keepingCapacity: false)
        pending.forEach { $0.resume() }
    }
}
