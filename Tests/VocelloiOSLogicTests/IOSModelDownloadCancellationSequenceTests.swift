import XCTest

@MainActor
final class IOSModelDownloadCancellationSequenceTests: XCTestCase {
    private enum Step: Equatable {
        case persistIntent
        case keepCancellable
        case publishCancelling
        case drainStarted
        case drainFinished
        case rollbackRacedInstallation
        case persistTombstone
        case removeStaging
        case publishDeleted
        case dequeue
        case discardStaging
    }

    private func runActive(
        intent: Bool = true,
        rollback: Bool = true,
        tombstone: Bool = true
    ) async -> (IOSModelDownloadCancellationSequence.ActiveOutcome, [Step]) {
        var steps: [Step] = []
        let outcome = await IOSModelDownloadCancellationSequence.cancelActive(
            persistIntent: { steps.append(.persistIntent); return intent },
            keepCancellable: { steps.append(.keepCancellable) },
            publishCancelling: { steps.append(.publishCancelling) },
            drainTask: {
                steps.append(.drainStarted)
                await Task.yield()
                steps.append(.drainFinished)
            },
            rollbackRacedInstallation: { steps.append(.rollbackRacedInstallation); return rollback },
            persistTombstone: { steps.append(.persistTombstone); return tombstone },
            removeStaging: { steps.append(.removeStaging) },
            publishDeleted: { steps.append(.publishDeleted) }
        )
        return (outcome, steps)
    }

    private func runPending(
        intent: Bool = true,
        tombstone: Bool = true
    ) -> (IOSModelDownloadCancellationSequence.PendingOutcome, [Step]) {
        var steps: [Step] = []
        let outcome = IOSModelDownloadCancellationSequence.cancelPending(
            persistIntent: { steps.append(.persistIntent); return intent },
            keepCancellable: { steps.append(.keepCancellable) },
            dequeue: { steps.append(.dequeue) },
            persistTombstone: { steps.append(.persistTombstone); return tombstone },
            discardStaging: { steps.append(.discardStaging) },
            publishDeleted: { steps.append(.publishDeleted) }
        )
        return (outcome, steps)
    }

    /// Intent is durable before the task is cancelled; a late atomic install is rolled back
    /// after the task fully drained; the tombstone is durable before staging is removed and
    /// before `.deleted` is published.
    func testActiveCancelPersistsIntentBeforeDrainAndTombstoneBeforeStagingRemoval() async {
        let (outcome, steps) = await runActive()
        XCTAssertEqual(outcome, .deleted)
        XCTAssertEqual(steps, [
            .persistIntent,
            .publishCancelling,
            .drainStarted,
            .drainFinished,
            .rollbackRacedInstallation,
            .persistTombstone,
            .removeStaging,
            .publishDeleted,
        ])
    }

    /// A failed intent write stops before the downloader or task is touched. The transfer keeps
    /// running, so it is shown again as running, with its Cancel control: a failure row would
    /// offer only Retry, which cannot act on a download still in flight (A5-03).
    func testActiveIntentPersistenceFailureStopsBeforeTheTaskIsCancelledAndStaysCancellable() async {
        let (outcome, steps) = await runActive(intent: false)
        XCTAssertEqual(outcome, .intentPersistenceFailed)
        XCTAssertEqual(steps, [.persistIntent, .keepCancellable])
    }

    /// A target that completed during cancellation and could not be rolled back is never
    /// tombstoned, and its staging is never removed.
    func testActiveRacedInstallRollbackFailureNeverTombstones() async {
        let (outcome, steps) = await runActive(rollback: false)
        XCTAssertEqual(outcome, .racedInstallationRollbackFailed)
        XCTAssertEqual(steps, [
            .persistIntent, .publishCancelling, .drainStarted, .drainFinished, .rollbackRacedInstallation,
        ])
    }

    /// A failed tombstone write preserves the staged files and never claims `.deleted`.
    func testActiveTombstoneFailurePreservesStagingAndNeverClaimsDeleted() async {
        let (outcome, steps) = await runActive(tombstone: false)
        XCTAssertEqual(outcome, .tombstonePersistenceFailed)
        XCTAssertEqual(steps.last, .persistTombstone)
        XCTAssertFalse(steps.contains(.removeStaging))
        XCTAssertFalse(steps.contains(.publishDeleted))
    }

    func testPendingCancelPersistsIntentBeforeDequeueAndTombstoneBeforeDiscard() {
        let (outcome, steps) = runPending()
        XCTAssertEqual(outcome, .deleted)
        XCTAssertEqual(steps, [.persistIntent, .dequeue, .persistTombstone, .discardStaging, .publishDeleted])
    }

    /// The request stays queued, so it is shown queued again, with Cancel (A5-03).
    func testPendingIntentPersistenceFailureLeavesTheQueueUntouchedAndStaysCancellable() {
        let (outcome, steps) = runPending(intent: false)
        XCTAssertEqual(outcome, .intentPersistenceFailed)
        XCTAssertEqual(steps, [.persistIntent, .keepCancellable])
    }

    /// Only an intent that could not be recorded restores the cancellable state; every later
    /// failure has already stopped or dequeued the request.
    func testOnlyAFailedIntentWriteRestoresTheCancellableState() async {
        for (_, steps) in [
            await runActive(), await runActive(rollback: false), await runActive(tombstone: false),
        ] {
            XCTAssertFalse(steps.contains(.keepCancellable))
        }
        for (_, steps) in [runPending(), runPending(tombstone: false)] {
            XCTAssertFalse(steps.contains(.keepCancellable))
        }
    }

    /// A5-04: cancelling a queued model never stops the heartbeat of the download in flight;
    /// only that download's own cancellation does.
    func testOnlyTheTransferThatOwnsTheHeartbeatStopsIt() {
        var heartbeat = IOSModelDownloadHeartbeatOwnership()
        heartbeat.claim(for: "pro_custom")

        XCTAssertFalse(heartbeat.release(for: "pro_design"), "A queued model's cancellation")
        XCTAssertEqual(heartbeat.modelID, "pro_custom")

        XCTAssertTrue(heartbeat.release(for: "pro_custom"))
        XCTAssertNil(heartbeat.modelID)
        XCTAssertFalse(heartbeat.release(for: "pro_custom"), "Already stopped")

        heartbeat.claim(for: "pro_design")
        XCTAssertEqual(heartbeat.modelID, "pro_design", "The next transfer takes it over")
    }

    func testPendingTombstoneFailurePreservesStagingAndNeverClaimsDeleted() {
        let (outcome, steps) = runPending(tombstone: false)
        XCTAssertEqual(outcome, .tombstonePersistenceFailed)
        XCTAssertEqual(steps, [.persistIntent, .dequeue, .persistTombstone])
    }
}
