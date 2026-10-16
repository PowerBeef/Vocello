import Foundation
import QwenVoiceCore

/// What an iPhone model row shows. `IOSModelDownloadCoordinator` publishes it and
/// `IOSModelInstallerViewModel` applies it in operation-generation order.
struct IOSModelDeliverySnapshot: Equatable, Sendable {
    enum Phase: String, Codable, Sendable {
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

    let modelID: String
    let phase: Phase
    let downloadedBytes: Int64
    let totalBytes: Int64?
    let estimatedBytes: Int64?
    let bytesPerSecond: Int64?
    let estimatedSecondsRemaining: Double?
    let retryCount: Int
    let message: String?
    let operationGeneration: UInt64

    init(
        modelID: String,
        phase: Phase,
        downloadedBytes: Int64,
        totalBytes: Int64?,
        estimatedBytes: Int64?,
        bytesPerSecond: Int64? = nil,
        estimatedSecondsRemaining: Double? = nil,
        retryCount: Int = 0,
        message: String?,
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
enum IOSModelDownloadProgressMapping {
    /// What one progress event changes for the model it belongs to.
    struct Update: Equatable, Sendable {
        /// The phase the row shows.
        let displayPhase: IOSModelDeliverySnapshot.Phase
        /// The status the ledger records (the coordinator throttles the writes); never
        /// `cancelRequested`, which only the user's Cancel writes.
        let ledgerStatus: IOSModelDownloadLedger.Status
    }

    /// How the coordinator settles a transfer that ended with an error.
    enum RunEnd: Equatable, Sendable {
        /// Record `failed`, show Failed with Retry, and start the next queued model.
        case reportFailure
        /// Change nothing: the run was superseded, or the model's Cancel owns the outcome and
        /// tombstones the request once the transfer has drained.
        case leaveToOwner
    }

    /// The durable status of a user's cancel intent. Only the coordinator's Cancel writes it.
    static let userCancelIntentStatus: IOSModelDownloadLedger.Status = .cancelRequested

    /// The update one progress event makes, or nil when it changes nothing.
    /// - Parameters:
    ///   - phase: the downloader's phase.
    ///   - userCancelIntent: the user's Cancel of this model is under way. It owns the row
    ///     (Cancelling) and the ledger (`cancelRequested`, then `deleted`) until it finishes,
    ///     so no progress event may weaken it.
    static func update(
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
    static func runEnd(runIsCurrent: Bool, userCancelIntent: Bool) -> RunEnd {
        runIsCurrent && !userCancelIntent ? .reportFailure : .leaveToOwner
    }
}
