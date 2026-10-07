import Foundation
import os

struct GenerationEventDeliverySnapshot: Equatable, Sendable {
    var subscriberPresent = false
    var yielded = 0
    var accepted = 0
    var unobserved = 0
    var droppedChunks = 0
    var droppedProgress = 0
    var droppedTerminals = 0
    var terminatedYields = 0
    var terminalYielded = 0
    var terminalEnqueued = 0
    var consumerTerminatedBeforeTerminal = false
    var minimumRemainingCapacity: Int?

    var droppedTotal: Int {
        droppedChunks + droppedProgress + droppedTerminals
    }

    var terminalDeliveryComplete: Bool {
        !subscriberPresent || (terminalEnqueued == 1 && terminatedYields == 0)
    }

    var accountingIsExact: Bool {
        yielded == accepted + terminatedYields + unobserved
    }
}

private actor BoundedGenerationEventChannel {
    private struct PendingSend {
        let id: UUID
        let event: GenerationEvent
        let continuation: CheckedContinuation<Bool, Never>
    }

    private let capacity: Int
    private var queue: [GenerationEvent] = []
    private var pendingSends: [PendingSend] = []
    private var waitingConsumer: CheckedContinuation<GenerationEvent?, Never>?
    private var terminalAccepted = false
    private var terminated = false

    init(capacity: Int) {
        self.capacity = max(1, capacity)
    }

    func send(_ event: GenerationEvent) async -> Bool {
        guard !terminated, !terminalAccepted else { return false }
        if let waitingConsumer {
            self.waitingConsumer = nil
            if event.isTerminal { terminalAccepted = true }
            waitingConsumer.resume(returning: event)
            if event.isTerminal { terminated = true }
            return true
        }
        if pendingSends.isEmpty, queue.count < capacity {
            queue.append(event)
            if event.isTerminal { terminalAccepted = true }
            return true
        }
        if event.isTerminal {
            // L13-06: a terminal carries no audio and ends the stream, so it is
            // never dropped for the producer's cancellation. A cancelled take
            // yields `.cancelled` from its own cancelled task; with the queue
            // full, the cancellable wait below would drop it and leave the
            // consumer parked forever once it drained the queue. The terminal is
            // queued past capacity (by this one event). Behind producers already
            // waiting it keeps its order, unless its own producer is cancelled:
            // then it goes first and the waiting sends end unaccepted when the
            // consumer reaches it. Only the consumer's termination refuses it.
            if pendingSends.isEmpty || Task.isCancelled {
                queue.append(event)
                terminalAccepted = true
                return true
            }
            return await withCheckedContinuation { continuation in
                pendingSends.append(PendingSend(id: UUID(), event: event, continuation: continuation))
            }
        }

        let pendingID = UUID()
        return await withTaskCancellationHandler {
            await withCheckedContinuation { continuation in
                if Task.isCancelled || terminated || terminalAccepted {
                    continuation.resume(returning: false)
                } else {
                    pendingSends.append(PendingSend(
                        id: pendingID,
                        event: event,
                        continuation: continuation
                    ))
                }
            }
        } onCancel: {
            Task { await self.cancelPendingSend(pendingID) }
        }
    }

    func next() async -> GenerationEvent? {
        if Task.isCancelled {
            terminate()
            return nil
        }
        if !queue.isEmpty {
            let event = queue.removeFirst()
            promotePendingSends()
            if event.isTerminal {
                terminate(keepingWaitingConsumer: true)
            }
            return event
        }
        if terminated { return nil }
        return await withTaskCancellationHandler {
            await withCheckedContinuation { continuation in
                if Task.isCancelled || terminated {
                    continuation.resume(returning: nil)
                } else {
                    waitingConsumer = continuation
                }
            }
        } onCancel: {
            Task { await self.cancelConsumer() }
        }
    }

    func cancelConsumer() {
        terminate()
    }

    private func cancelPendingSend(_ id: UUID) {
        guard let index = pendingSends.firstIndex(where: { $0.id == id }) else { return }
        pendingSends.remove(at: index).continuation.resume(returning: false)
    }

    private func promotePendingSends() {
        while queue.count < capacity, !pendingSends.isEmpty, !terminalAccepted, !terminated {
            let pending = pendingSends.removeFirst()
            queue.append(pending.event)
            if pending.event.isTerminal { terminalAccepted = true }
            pending.continuation.resume(returning: true)
        }
    }

    private func terminate(keepingWaitingConsumer: Bool = false) {
        guard !terminated else { return }
        terminated = true
        if !keepingWaitingConsumer {
            waitingConsumer?.resume(returning: nil)
            waitingConsumer = nil
        }
        let blocked = pendingSends
        pendingSends.removeAll(keepingCapacity: false)
        blocked.forEach { $0.continuation.resume(returning: false) }
    }
}

private extension GenerationEvent {
    var isTerminal: Bool {
        kind == .completed || kind == .cancelled || kind == .failed
    }
}

/// One bounded, suspending stream per generation. A previous generation can
/// never occupy the next generation's buffer, audio-bearing events are never
/// evicted, and the product producer backpressures until its sole consumer
/// advances. Every producer send is accounted as accepted, terminated, or
/// unobserved; there is no dropping policy.
final class GenerationScopedEventRouter: @unchecked Sendable {
    private struct ActiveSubscription {
        var channel: BoundedGenerationEventChannel?
        var snapshot: GenerationEventDeliverySnapshot
        var producerStarted = false
        var terminalYielded = false
    }

    private struct State {
        var active: [UUID: ActiveSubscription] = [:]
        var completed: [UUID: GenerationEventDeliverySnapshot] = [:]
        var completedOrder: [UUID] = []
    }

    private let lock = OSAllocatedUnfairLock(initialState: State())

    func stream(for generationID: UUID, capacity: Int) -> AsyncStream<GenerationEvent> {
        precondition(capacity > 0)
        let channel = BoundedGenerationEventChannel(capacity: capacity)
        let accepted = lock.withLock { state -> Bool in
            if let current = state.active[generationID], current.channel != nil {
                return false
            }
            var subscription = state.active[generationID] ?? ActiveSubscription(
                channel: nil,
                snapshot: GenerationEventDeliverySnapshot(),
                producerStarted: false,
                terminalYielded: false
            )
            subscription.channel = channel
            subscription.snapshot.subscriberPresent = true
            state.active[generationID] = subscription
            return true
        }
        guard accepted else {
            return AsyncStream(unfolding: { nil })
        }
        return AsyncStream(
            unfolding: { await channel.next() },
            onCancel: { [weak self] in
                self?.consumerTerminated(generationID: generationID)
                Task { await channel.cancelConsumer() }
            }
        )
    }

    func beginGeneration(_ generationID: UUID) {
        lock.withLock { state in
            state.completed.removeValue(forKey: generationID)
            state.completedOrder.removeAll { $0 == generationID }
            if var subscription = state.active[generationID] {
                subscription.snapshot = GenerationEventDeliverySnapshot(
                    subscriberPresent: subscription.channel != nil
                )
                subscription.producerStarted = true
                subscription.terminalYielded = false
                state.active[generationID] = subscription
            } else {
                state.active[generationID] = ActiveSubscription(
                    channel: nil,
                    snapshot: GenerationEventDeliverySnapshot(),
                    producerStarted: true,
                    terminalYielded: false
                )
            }
        }
    }

    func yield(_ event: GenerationEvent, for generationID: UUID) async {
        let channel = lock.withLock { state -> BoundedGenerationEventChannel? in
            if state.active[generationID] == nil {
                state.active[generationID] = ActiveSubscription(
                    channel: nil,
                    snapshot: GenerationEventDeliverySnapshot(),
                    producerStarted: true,
                    terminalYielded: false
                )
            }
            state.active[generationID]?.snapshot.yielded += 1
            return state.active[generationID]?.channel
        }

        let accepted = await channel?.send(event)
        lock.withLock { state in
            guard var subscription = state.active[generationID] else { return }
            if channel == nil {
                subscription.snapshot.unobserved += 1
            } else if accepted == true {
                subscription.snapshot.accepted += 1
                subscription.snapshot.minimumRemainingCapacity = 0
                if event.isTerminal {
                    subscription.snapshot.terminalEnqueued += 1
                }
            } else {
                subscription.snapshot.terminatedYields += 1
            }

            if event.isTerminal {
                subscription.snapshot.terminalYielded += 1
                subscription.terminalYielded = true
                Self.archive(subscription.snapshot, generationID: generationID, state: &state)
                state.active.removeValue(forKey: generationID)
            } else {
                state.active[generationID] = subscription
            }
        }
    }

    func snapshot(for generationID: UUID, consuming: Bool = false) -> GenerationEventDeliverySnapshot {
        lock.withLock { state in
            let snapshot = state.active[generationID]?.snapshot
                ?? state.completed[generationID]
                ?? GenerationEventDeliverySnapshot()
            if consuming {
                state.completed.removeValue(forKey: generationID)
                state.completedOrder.removeAll { $0 == generationID }
            }
            return snapshot
        }
    }

    private func consumerTerminated(generationID: UUID) {
        lock.withLock { state in
            guard var subscription = state.active[generationID] else { return }
            subscription.channel = nil
            if subscription.producerStarted && !subscription.terminalYielded {
                subscription.snapshot.consumerTerminatedBeforeTerminal = true
            }
            state.active[generationID] = subscription
        }
    }

    private static func archive(
        _ snapshot: GenerationEventDeliverySnapshot,
        generationID: UUID,
        state: inout State
    ) {
        state.completed[generationID] = snapshot
        state.completedOrder.removeAll { $0 == generationID }
        state.completedOrder.append(generationID)
        while state.completedOrder.count > 16 {
            state.completed.removeValue(forKey: state.completedOrder.removeFirst())
        }
    }
}
