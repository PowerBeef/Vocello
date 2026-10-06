import Foundation

/// Orders a durable iOS model-download cancellation.
///
/// The cancellation intent is persisted before any task is cancelled; the `.deleted` tombstone is
/// persisted before staged files are removed or a terminal `.deleted` snapshot is published; and
/// every failed persist returns immediately, so a later launch can never undo a cancellation the
/// UI already claimed. A transfer that crossed its atomic-install boundary during the drain is
/// rolled back before the tombstone, and a failed rollback is never tombstoned. An intent that
/// could not be recorded changed nothing, so the request is shown again as it still is, with its
/// Cancel control, rather than as a failure whose Retry would only start what is running (A5-03).
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
        /// The `.cancelRequested` write failed: nothing was dequeued or removed, and the
        /// request was shown as still queued.
        case intentPersistenceFailed
        /// The `.deleted` write failed: staging preserved, `.deleted` never published.
        case tombstonePersistenceFailed
    }

    enum ActiveOutcome: Equatable {
        case deleted
        /// The `.cancelRequested` write failed: the task was never cancelled or drained, and the
        /// transfer was shown as still running.
        case intentPersistenceFailed
        /// A target that completed during the drain could not be removed: never tombstoned.
        case racedInstallationRollbackFailed
        /// The `.deleted` write failed: staging preserved, `.deleted` never published.
        case tombstonePersistenceFailed
    }

    /// A queued request with no running transfer.
    /// - Parameters:
    ///   - persistIntent: durable `.cancelRequested`; `false` aborts before the queue changes.
    ///   - keepCancellable: after a failed intent write only: shows the request as still queued,
    ///     with Cancel and the reason.
    ///   - dequeue: removes the request from the pending queue.
    ///   - persistTombstone: durable `.deleted`; `false` aborts before staging is touched.
    ///   - discardStaging: removes the staged files.
    ///   - publishDeleted: terminal `.deleted` snapshot.
    static func cancelPending(
        persistIntent: () -> Bool,
        keepCancellable: () -> Void,
        dequeue: () -> Void,
        persistTombstone: () -> Bool,
        discardStaging: () -> Void,
        publishDeleted: () -> Void
    ) -> PendingOutcome {
        guard persistIntent() else {
            keepCancellable()
            return .intentPersistenceFailed
        }
        dequeue()
        guard persistTombstone() else { return .tombstonePersistenceFailed }
        discardStaging()
        publishDeleted()
        return .deleted
    }

    /// A request whose transfer task is running.
    /// - Parameters:
    ///   - persistIntent: durable `.cancelRequested`; `false` aborts before the task is cancelled.
    ///   - keepCancellable: after a failed intent write only: shows the transfer as still
    ///     running, with Cancel and the reason.
    ///   - publishCancelling: visible `.cancelling` snapshot.
    ///   - drainTask: cancels the downloader and the task, awaits its completion, and forgets it.
    ///   - rollbackRacedInstallation: removes a target that completed during the drain;
    ///     `false` aborts before the tombstone.
    ///   - persistTombstone: durable `.deleted`; `false` aborts before staging is touched.
    ///   - removeStaging: removes the staging root.
    ///   - publishDeleted: terminal `.deleted` snapshot.
    static func cancelActive(
        persistIntent: () -> Bool,
        keepCancellable: () -> Void,
        publishCancelling: () -> Void,
        drainTask: () async -> Void,
        rollbackRacedInstallation: () -> Bool,
        persistTombstone: () -> Bool,
        removeStaging: () -> Void,
        publishDeleted: () -> Void
    ) async -> ActiveOutcome {
        guard persistIntent() else {
            keepCancellable()
            return .intentPersistenceFailed
        }
        publishCancelling()
        await drainTask()
        guard rollbackRacedInstallation() else { return .racedInstallationRollbackFailed }
        guard persistTombstone() else { return .tombstonePersistenceFailed }
        removeStaging()
        publishDeleted()
        return .deleted
    }
}

/// The coordinator's one diagnostics heartbeat belongs to the transfer that started it (A5-04).
/// Only a cancellation of that model stops it: cancelling a model still waiting in the queue
/// never silences the heartbeat of the download in flight.
struct IOSModelDownloadHeartbeatOwnership: Equatable, Sendable {
    private(set) var modelID: String?

    init() {}

    /// The heartbeat now follows this model's transfer.
    mutating func claim(for modelID: String) {
        self.modelID = modelID
    }

    /// Whether the heartbeat should stop for this model's cancellation: only when it owns it.
    mutating func release(for modelID: String) -> Bool {
        guard self.modelID == modelID else { return false }
        self.modelID = nil
        return true
    }
}
