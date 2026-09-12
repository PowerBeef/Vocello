import XCTest

@MainActor
final class IOSModelDownloadCancellationSequenceTests: XCTestCase {
    private enum Step: Equatable {
        case persistIntent
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

    /// A failed intent write stops before the downloader or task is touched, so the caller can
    /// publish the failure against the still-recoverable generation.
    func testActiveIntentPersistenceFailureStopsBeforeTheTaskIsCancelled() async {
        let (outcome, steps) = await runActive(intent: false)
        XCTAssertEqual(outcome, .intentPersistenceFailed)
        XCTAssertEqual(steps, [.persistIntent])
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

    func testPendingIntentPersistenceFailureLeavesTheQueueUntouched() {
        let (outcome, steps) = runPending(intent: false)
        XCTAssertEqual(outcome, .intentPersistenceFailed)
        XCTAssertEqual(steps, [.persistIntent])
    }

    func testPendingTombstoneFailurePreservesStagingAndNeverClaimsDeleted() {
        let (outcome, steps) = runPending(tombstone: false)
        XCTAssertEqual(outcome, .tombstonePersistenceFailed)
        XCTAssertEqual(steps, [.persistIntent, .dequeue, .persistTombstone])
    }
}
