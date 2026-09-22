import XCTest
@testable import QwenVoiceCore

/// The prewarm slot must never stay held by a caller that has finished.
/// Everything runs on the main actor so a `release(); cancel()` pair happens
/// with no suspension point between the two calls.
@MainActor
final class PrewarmSlotGateTests: XCTestCase {
    private func waitUntilQueued(_ gate: PrewarmSlotGate, count: Int) async {
        for _ in 0..<10_000 where gate.waiterCount < count {
            await Task.yield()
        }
        XCTAssertEqual(gate.waiterCount, count, "waiter never queued")
    }

    func testAWaiterCancelledAfterTheHandOffGivesTheSlotBack() async throws {
        let gate = PrewarmSlotGate()
        let holderWait = try await gate.acquire()
        XCTAssertEqual(holderWait, 0)
        let waiter = Task { @MainActor in try await gate.acquire() }
        await waitUntilQueued(gate, count: 1)

        // The hand-off resumes the waiter, but it cannot run before the
        // cancel lands: both calls happen on the main actor back to back.
        gate.release()
        waiter.cancel()

        let result = await waiter.result
        XCTAssertThrowsError(try result.get()) { XCTAssertTrue($0 is CancellationError) }
        XCTAssertFalse(gate.isHeld, "a cancelled waiter must not keep the slot it was handed")
        // A leaked slot would make the next acquire wait forever, which is the
        // engine wedge itself; stop here instead of hanging the suite.
        guard !gate.isHeld else { return }
        let nextWait = try await gate.acquire()
        XCTAssertEqual(nextWait, 0, "the next caller must get the slot at once")
        gate.release()
    }

    func testAWaiterCancelledWhileQueuedLeavesTheHolderInPlace() async throws {
        let gate = PrewarmSlotGate()
        _ = try await gate.acquire()
        let waiter = Task { @MainActor in try await gate.acquire() }
        await waitUntilQueued(gate, count: 1)
        waiter.cancel()

        let result = await waiter.result
        XCTAssertThrowsError(try result.get())
        XCTAssertTrue(gate.isHeld, "the original holder still owns the slot")
        XCTAssertEqual(gate.waiterCount, 0)
        gate.release()
        XCTAssertFalse(gate.isHeld)
    }

    func testWaitersAreServedInArrivalOrder() async throws {
        let gate = PrewarmSlotGate()
        _ = try await gate.acquire()
        var order: [String] = []
        let first = Task { @MainActor in
            _ = try await gate.acquire()
            order.append("first")
            gate.release()
        }
        await waitUntilQueued(gate, count: 1)
        let second = Task { @MainActor in
            _ = try await gate.acquire()
            order.append("second")
            gate.release()
        }
        await waitUntilQueued(gate, count: 2)
        gate.release()
        try await first.value
        try await second.value
        XCTAssertEqual(order, ["first", "second"])
        XCTAssertFalse(gate.isHeld)
    }

    func testAnAlreadyCancelledCallerNeverTakesTheSlot() async throws {
        let gate = PrewarmSlotGate()
        // Cancelled before it can start: the main actor is busy until the await.
        let caller = Task { @MainActor in try await gate.acquire() }
        caller.cancel()
        let result = await caller.result
        XCTAssertThrowsError(try result.get())
        XCTAssertFalse(gate.isHeld)
    }
}
