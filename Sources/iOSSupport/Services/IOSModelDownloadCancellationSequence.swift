import Foundation

/// Orders a durable iOS model-download cancellation.
///
/// The cancellation intent is persisted before any task is cancelled; the `.deleted` tombstone is
/// persisted before staged files are removed or a terminal `.deleted` snapshot is published; and
/// every failed persist returns immediately, so a later launch can never undo a cancellation the
/// UI already claimed. A transfer that crossed its atomic-install boundary during the drain is
/// rolled back before the tombstone, and a failed rollback is never tombstoned.
///
/// The type owns only the order. Every step is a non-escaping closure supplied by
/// `IOSModelDownloadCoordinator`; only `drainTask` is asynchronous (it awaits the downloader
/// barrier and the task's completion). `@MainActor` for the same reason as
/// `CriticalMemoryReliefExecutor`: the coordinator's closures touch MainActor state.
///
/// `IOSModelDownloadCancellationSequenceTests` pins this order. Binding each closure to the right
/// side effect stays the coordinator's responsibility at the call site: several steps share the
/// type `() -> Void`, and no token could stop a closure body from doing the wrong work.
@MainActor
enum IOSModelDownloadCancellationSequence {
    enum PendingOutcome: Equatable {
        case deleted
        /// The `.cancelRequested` write failed: nothing was dequeued or removed.
        case intentPersistenceFailed
        /// The `.deleted` write failed: staging preserved, `.deleted` never published.
        case tombstonePersistenceFailed
    }

    enum ActiveOutcome: Equatable {
        case deleted
        /// The `.cancelRequested` write failed: the task was never cancelled or drained.
        case intentPersistenceFailed
        /// A target that completed during the drain could not be removed: never tombstoned.
        case racedInstallationRollbackFailed
        /// The `.deleted` write failed: staging preserved, `.deleted` never published.
        case tombstonePersistenceFailed
    }

    /// A queued request with no running transfer.
    /// - Parameters:
    ///   - persistIntent: durable `.cancelRequested`; `false` aborts before the queue changes.
    ///   - dequeue: removes the request from the pending queue.
    ///   - persistTombstone: durable `.deleted`; `false` aborts before staging is touched.
    ///   - discardStaging: removes the staged files.
    ///   - publishDeleted: terminal `.deleted` snapshot.
    static func cancelPending(
        persistIntent: () -> Bool,
        dequeue: () -> Void,
        persistTombstone: () -> Bool,
        discardStaging: () -> Void,
        publishDeleted: () -> Void
    ) -> PendingOutcome {
        guard persistIntent() else { return .intentPersistenceFailed }
        dequeue()
        guard persistTombstone() else { return .tombstonePersistenceFailed }
        discardStaging()
        publishDeleted()
        return .deleted
    }

    /// A request whose transfer task is running.
    /// - Parameters:
    ///   - persistIntent: durable `.cancelRequested`; `false` aborts before the task is cancelled.
    ///   - publishCancelling: visible `.cancelling` snapshot.
    ///   - drainTask: cancels the downloader and the task, awaits its completion, and forgets it.
    ///   - rollbackRacedInstallation: removes a target that completed during the drain;
    ///     `false` aborts before the tombstone.
    ///   - persistTombstone: durable `.deleted`; `false` aborts before staging is touched.
    ///   - removeStaging: removes the staging root.
    ///   - publishDeleted: terminal `.deleted` snapshot.
    static func cancelActive(
        persistIntent: () -> Bool,
        publishCancelling: () -> Void,
        drainTask: () async -> Void,
        rollbackRacedInstallation: () -> Bool,
        persistTombstone: () -> Bool,
        removeStaging: () -> Void,
        publishDeleted: () -> Void
    ) async -> ActiveOutcome {
        guard persistIntent() else { return .intentPersistenceFailed }
        publishCancelling()
        await drainTask()
        guard rollbackRacedInstallation() else { return .racedInstallationRollbackFailed }
        guard persistTombstone() else { return .tombstonePersistenceFailed }
        removeStaging()
        publishDeleted()
        return .deleted
    }
}
