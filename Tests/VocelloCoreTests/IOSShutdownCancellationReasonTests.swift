import XCTest
@testable import QwenVoiceCore

/// PA-15: the foreground exit's `.shutdown` must reach the engine's terminal
/// cancellation summary. `MLXTTSEngine.generate` registers a cancel closure
/// that requests the typed reason on its ingress, while cancelling the Swift
/// task that awaits the engine requests `.user` from its cancellation handler;
/// the ingress keeps the first reason and the terminal summary reads
/// `ingress.reason ?? coordinatorReason`. This reproduces that wiring with the
/// real ingress and coordinator and drives it in `IOSStudioCancellationOrder`.
final class IOSShutdownCancellationReasonTests: XCTestCase {
    func testShutdownReachesTheTerminalReasonWhenTheBarrierRunsFirst() async throws {
        let order = IOSStudioCancellationOrder.forReason(.shutdown)
        XCTAssertEqual(order, .barrierThenTask)
        let terminal = try await terminalReason(order: order, reason: .shutdown)
        XCTAssertEqual(terminal, .shutdown)
    }

    func testCancellingTheSwiftTaskFirstWouldReportUser() async throws {
        // Why the order matters: the task-first path loses the typed reason.
        let terminal = try await terminalReason(order: .taskThenBarrier, reason: .shutdown)
        XCTAssertEqual(terminal, .user)
    }

    func testUserStopStillReportsUser() async throws {
        let terminal = try await terminalReason(
            order: IOSStudioCancellationOrder.forReason(.user),
            reason: .user
        )
        XCTAssertEqual(terminal, .user)
    }

    private func terminalReason(
        order: IOSStudioCancellationOrder,
        reason: GenerationCancellationReason
    ) async throws -> GenerationCancellationReason? {
        let coordinator = ActiveGenerationCoordinator()
        let ingress = GenerationCancellationIngress()
        let worker = Task {
            try? await Task.sleep(for: .seconds(30))
        }
        let registration = try await coordinator.register(
            cancel: { typedReason in
                ingress.request(typedReason)
                worker.cancel()
            },
            waitForTermination: { _ = await worker.result }
        )
        // The Swift task's `withTaskCancellationHandler` in `MLXTTSEngine.generate`.
        let cancelSwiftTask: @Sendable () -> Void = { _ = ingress.request(.user) }

        switch order {
        case .taskThenBarrier:
            cancelSwiftTask()
            await coordinator.cancelCurrent(reason: reason)
        case .barrierThenTask:
            await coordinator.cancelCurrent(reason: reason)
            cancelSwiftTask()
        }

        let coordinatorReason = await coordinator.finish(registration)
        return ingress.reason ?? coordinatorReason
    }
}
