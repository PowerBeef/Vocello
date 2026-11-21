import Foundation
import QwenVoiceCore

/// What an iPhone model row shows. `IOSModelDownloadCoordinator` publishes it and
/// `IOSModelInstallerViewModel` applies it in operation-generation order.
public struct IOSModelDeliverySnapshot: Equatable, Sendable {
    public enum Phase: String, Codable, Sendable {
        case queued
        case waitingForConnectivity
        case downloading
        case retrying
        case verifying
        case installing
        case cancelling
        case installed
        case failed
        case deleting
        case deleted
    }

    public let modelID: String
    public let phase: Phase
    public let downloadedBytes: Int64
    public let totalBytes: Int64?
    public let estimatedBytes: Int64?
    public let bytesPerSecond: Int64?
    public let estimatedSecondsRemaining: Double?
    public let retryCount: Int
    public let message: String?
    /// Typed failure class populated from the underlying `Error` when `phase == .failed`
    /// so non-English locales classify `ENOSPC` / verification / network failures without
    /// relying on English-only substring matching (RB-12).
    public let failureClass: ModelUpdateFailure?
    public let operationGeneration: UInt64

    public init(
        modelID: String,
        phase: Phase,
        downloadedBytes: Int64,
        totalBytes: Int64?,
        estimatedBytes: Int64?,
        bytesPerSecond: Int64? = nil,
        estimatedSecondsRemaining: Double? = nil,
        retryCount: Int = 0,
        message: String?,
        failureClass: ModelUpdateFailure? = nil,
        operationGeneration: UInt64
    ) {
        self.modelID = modelID
        self.phase = phase
        self.downloadedBytes = downloadedBytes
        self.totalBytes = totalBytes
        self.estimatedBytes = estimatedBytes
        self.bytesPerSecond = bytesPerSecond
        self.estimatedSecondsRemaining = estimatedSecondsRemaining
        self.retryCount = retryCount
        self.message = message
        self.failureClass = failureClass
        self.operationGeneration = operationGeneration
    }
}

/// How the downloader's progress and a transfer's end reach an iPhone model row and its
/// durable ledger request (RF-19, E-02).
///
/// Only the user's Cancel records `cancelRequested`: `IOSModelDownloadCoordinator.cancel`
/// persists `userCancelIntentStatus` before any task is touched
/// (`IOSModelDownloadCancellationSequence`). The downloader also reports `.cancelling` while a
/// failed file stops its sibling transfers. That is not a cancellation, so it changes neither
/// the row nor the ledger; the run's error then shows as Failed with Retry and the next queued
/// model starts. Recording it as `cancelRequested` froze the row at Cancelling with no action,
/// kept the queue from advancing, and made the next launch discard the staged files as a
/// cancelled request.
///
/// Pure and Foundation-level, so `IOSModelDownloadProgressMappingTests` runs it in both logic
/// bundles; the coordinator stays the owner of the side effects.
public enum IOSModelDownloadProgressMapping {
    /// What one progress event changes for the model it belongs to.
    public struct Update: Equatable, Sendable {
        /// The phase the row shows.
        public let displayPhase: IOSModelDeliverySnapshot.Phase
        /// The status the ledger records (the coordinator throttles the writes); never
        /// `cancelRequested`, which only the user's Cancel writes.
        public let ledgerStatus: IOSModelDownloadLedger.Status

        public init(
            displayPhase: IOSModelDeliverySnapshot.Phase,
            ledgerStatus: IOSModelDownloadLedger.Status
        ) {
            self.displayPhase = displayPhase
            self.ledgerStatus = ledgerStatus
        }
    }

    /// How the coordinator settles a transfer that ended with an error.
    public enum RunEnd: Equatable, Sendable {
        /// Record `failed`, show Failed with Retry, and start the next queued model.
        case reportFailure
        /// Change nothing: the run was superseded, or the model's Cancel owns the outcome and
        /// tombstones the request once the transfer has drained.
        case leaveToOwner
    }

    /// The durable status of a user's cancel intent. Only the coordinator's Cancel writes it.
    public static let userCancelIntentStatus: IOSModelDownloadLedger.Status = .cancelRequested

    /// The update one progress event makes, or nil when it changes nothing.
    /// - Parameters:
    ///   - phase: the downloader's phase.
    ///   - userCancelIntent: the user's Cancel of this model is under way. It owns the row
    ///     (Cancelling) and the ledger (`cancelRequested`, then `deleted`) until it finishes,
    ///     so no progress event may weaken it.
    public static func update(
        for phase: HuggingFaceDownloader.DownloadPhase,
        userCancelIntent: Bool
    ) -> Update? {
        guard !userCancelIntent else { return nil }
        switch phase {
        case .queued:
            return Update(displayPhase: .queued, ledgerStatus: .queued)
        case .waitingForConnectivity:
            return Update(displayPhase: .waitingForConnectivity, ledgerStatus: .waitingForConnectivity)
        case .downloading:
            return Update(displayPhase: .downloading, ledgerStatus: .downloading)
        case .retrying:
            return Update(displayPhase: .retrying, ledgerStatus: .retrying)
        case .verifying:
            return Update(displayPhase: .verifying, ledgerStatus: .verifying)
        case .installing:
            return Update(displayPhase: .installing, ledgerStatus: .installing)
        case .cancelling:
            // A failed file stopping its siblings, not a cancellation: the failure the run
            // then reports is what the row shows.
            return nil
        }
    }

    /// A run that is still current and that no Cancel owns reports how it ended as a
    /// failure, a `.cancelled` the coordinator never asked for included.
    public static func runEnd(runIsCurrent: Bool, userCancelIntent: Bool) -> RunEnd {
        runIsCurrent && !userCancelIntent ? .reportFailure : .leaveToOwner
    }
}

/// Coordinates UIKit background `URLSession` completion-handler flushing across launch
/// restore, coordinator postprocessing (`beginDownload` → `runDownload` → terminal ledger
/// write → `startPendingDownloads`), and live task submission to `nsurlsessiond` (RB-08).
///
/// Prevents both premature-flush races:
/// - **Race A (wake before initial restore):** `urlSessionDidFinishEvents` and idle-wake
///   reconciliation never flush while `hasCompletedInitialRestore == false`.
/// - **Race B (`beginDownload` → unstructured `Task { runDownload }` handoff):** `beginDownload`
///   synchronously claims a submission hold before spawning `runDownload`, so `postprocessingDepth`
///   never drops to 0 across the task boundary or during Model 1 → Model 2 handoff. Once live
///   tasks are submitted to `nsurlsessiond` (or postprocessing settles with no further work),
///   the latched wake flushes promptly instead of hanging UIKit across a multi-minute transfer.
public struct IOSBackgroundSessionCompletionCoordinator: Equatable, Sendable {
    public private(set) var hasCompletedInitialRestore = false
    public private(set) var postprocessingDepth = 0
    public private(set) var eventsFinished = false

    public init() {}

    /// Records `urlSessionDidFinishEvents(forBackgroundURLSession:)`.
    /// Returns `true` only when initial restore has completed, no postprocessing hold is active,
    /// and no queued/in-flight work owns pending verification or queue handoff.
    public mutating func sessionDidFinishEvents(hasPendingOrInFlightWork: Bool) -> Bool {
        eventsFinished = true
        guard hasCompletedInitialRestore, postprocessingDepth == 0, !hasPendingOrInFlightWork else {
            return false
        }
        eventsFinished = false
        return true
    }

    /// Claims a synchronous postprocessing or task-submission hold.
    public mutating func beginPostprocessing() {
        postprocessingDepth += 1
    }

    /// Releases one postprocessing or task-submission hold. Returns `true` when depth reaches 0,
    /// initial restore has finished, and a latched wake event is ready to flush.
    public mutating func endPostprocessing() -> Bool {
        postprocessingDepth = max(0, postprocessingDepth - 1)
        guard hasCompletedInitialRestore, postprocessingDepth == 0, eventsFinished else {
            return false
        }
        eventsFinished = false
        return true
    }

    /// Ends the initial restore's postprocessing hold and marks initial restore complete.
    /// Returns `true` to flush when no postprocessing hold remains and either a wake event was
    /// latched (`eventsFinished`) or no work remains active (`!hasWork`).
    public mutating func endInitialRestore(hasWork: Bool) -> Bool {
        hasCompletedInitialRestore = true
        postprocessingDepth = max(0, postprocessingDepth - 1)
        guard postprocessingDepth == 0 else { return false }
        if eventsFinished || !hasWork {
            eventsFinished = false
            return true
        }
        return false
    }

    /// Flushes a latched background-wake event once live rollover tasks are submitted to
    /// `nsurlsessiond` and no coordinator postprocessing hold is active.
    public mutating func flushIfReadyAfterTaskSubmission() -> Bool {
        guard hasCompletedInitialRestore, postprocessingDepth == 0, eventsFinished else {
            return false
        }
        eventsFinished = false
        return true
    }

    /// Whether an idle `resumeBackgroundEventsIfNeeded()` wake may flush immediately.
    /// Never flushes before `hasCompletedInitialRestore` so Race A cannot suspend the app before
    /// `restoreInFlightDownloadsIfNeeded()` runs.
    public mutating func canCompleteIdleWake(
        hasLedgerActiveWork: Bool,
        hasCoordinatorWork: Bool
    ) -> Bool {
        guard hasCompletedInitialRestore, postprocessingDepth == 0,
              !hasLedgerActiveWork, !hasCoordinatorWork else {
            return false
        }
        eventsFinished = false
        return true
    }
}
