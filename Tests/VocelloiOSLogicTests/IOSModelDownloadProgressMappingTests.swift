import QwenVoiceCore
import XCTest
import VocelloiOSPolicies

/// RF-19 (E-02): a failed file's teardown is never recorded as a user's cancel. Recording it
/// froze the row at Cancelling, kept the queue from advancing, and made the next launch
/// discard the staged files.
final class IOSModelDownloadProgressMappingTests: XCTestCase {
    private typealias Mapping = IOSModelDownloadProgressMapping
    private typealias DownloaderPhase = HuggingFaceDownloader.DownloadPhase

    private static let everyDownloaderPhase: [DownloaderPhase] = [
        .queued, .waitingForConnectivity, .downloading, .retrying, .verifying, .installing, .cancelling,
    ]

    /// Without a user's Cancel every live phase shows and records itself.
    func testLivePhasesShowAndRecordThemselves() {
        let table: [(DownloaderPhase, IOSModelDeliverySnapshot.Phase, IOSModelDownloadLedger.Status)] = [
            (.queued, .queued, .queued),
            (.waitingForConnectivity, .waitingForConnectivity, .waitingForConnectivity),
            (.downloading, .downloading, .downloading),
            (.retrying, .retrying, .retrying),
            (.verifying, .verifying, .verifying),
            (.installing, .installing, .installing),
        ]
        for (phase, display, status) in table {
            XCTAssertEqual(
                Mapping.update(for: phase, userCancelIntent: false),
                Mapping.Update(displayPhase: display, ledgerStatus: status),
                "\(phase)"
            )
        }
    }

    /// The downloader reports `.cancelling` while a failed file stops its siblings. That is
    /// not a cancellation: neither the row nor the ledger changes.
    func testCancellingWithoutUserIntentChangesNeitherTheRowNorTheLedger() {
        XCTAssertNil(Mapping.update(for: .cancelling, userCancelIntent: false))
    }

    /// No progress event records `cancelRequested`, with or without a user's Cancel; only the
    /// user's Cancel writes it.
    func testOnlyTheUsersCancelRecordsCancelRequested() {
        for phase in Self.everyDownloaderPhase {
            for userCancelIntent in [false, true] {
                XCTAssertNotEqual(
                    Mapping.update(for: phase, userCancelIntent: userCancelIntent)?.ledgerStatus,
                    .cancelRequested,
                    "\(phase), user cancel \(userCancelIntent)"
                )
            }
        }
        XCTAssertEqual(Mapping.userCancelIntentStatus, .cancelRequested)
    }

    /// While the user's Cancel drains the transfer it owns the row and the ledger: no
    /// progress event may weaken it, not even a late `.downloading`.
    func testTheUsersCancelOwnsTheRowAndTheLedgerUntilItFinishes() {
        for phase in Self.everyDownloaderPhase {
            XCTAssertNil(Mapping.update(for: phase, userCancelIntent: true), "\(phase)")
        }
    }

    /// A failing run's events, ending in the `.cancelling` of its teardown: the ledger records
    /// only live phases, never a cancellation, and the run's error is reported as a failure
    /// (Failed with Retry, then the next queued model starts).
    func testAFailureWhileCancellingWithoutIntentWritesNoCancelAndIsReportedAsFailed() {
        let failingRun: [DownloaderPhase] = [.downloading, .retrying, .downloading, .cancelling]
        let ledgerWrites = failingRun.compactMap {
            Mapping.update(for: $0, userCancelIntent: false)?.ledgerStatus
        }
        XCTAssertEqual(ledgerWrites, [.downloading, .retrying, .downloading])
        XCTAssertFalse(ledgerWrites.contains(.cancelRequested))
        XCTAssertEqual(Mapping.runEnd(runIsCurrent: true, userCancelIntent: false), .reportFailure)
    }

    /// A user's Cancel records `cancelRequested` and owns how the run ends: the cancellation
    /// sequence drains the transfer and tombstones the request, so nothing reports a failure.
    func testAUsersCancelRecordsItsIntentAndOwnsTheRunEnd() {
        let cancelledRun: [DownloaderPhase] = [.downloading, .cancelling]
        XCTAssertTrue(cancelledRun.allSatisfy { Mapping.update(for: $0, userCancelIntent: true) == nil })
        XCTAssertEqual(Mapping.userCancelIntentStatus, .cancelRequested)
        XCTAssertEqual(Mapping.runEnd(runIsCurrent: true, userCancelIntent: true), .leaveToOwner)
    }

    /// A superseded run reports nothing for its model.
    func testASupersededRunLeavesTheOutcomeToItsOwner() {
        for userCancelIntent in [false, true] {
            XCTAssertEqual(
                Mapping.runEnd(runIsCurrent: false, userCancelIntent: userCancelIntent),
                .leaveToOwner
            )
        }
    }

    /// RB-12: delivery snapshots carry typed `failureClass` so non-English localized error
    /// descriptions (e.g. French `ENOSPC`) preserve `.space` for Make Room recovery.
    func testDeliverySnapshotPreservesTypedFailureClassAcrossNonEnglishMessages() {
        let snapshot = IOSModelDeliverySnapshot(
            modelID: "pro_custom",
            phase: .failed,
            downloadedBytes: 0,
            totalBytes: 2_000_000_000,
            estimatedBytes: 2_000_000_000,
            message: "Espace libre insuffisant.",
            failureClass: .space,
            operationGeneration: 7
        )
        XCTAssertEqual(snapshot.failureClass, .space)
        XCTAssertEqual(
            ModelUpdateFailure.classify(description: snapshot.message ?? ""),
            .other,
            "English-only substring classifier alone would misclassify non-English ENOSPC"
        )
        XCTAssertEqual(
            ModelUpdateFailure.classify(
                IOSModelDeliveryError.insufficientDiskSpace(requiredBytes: 4_000_000_000, availableBytes: 500_000_000)
            ),
            .space
        )
        XCTAssertEqual(
            ModelUpdateFailure.classify(IOSModelDeliveryError.fileHashMismatch(relativePath: "model.safetensors")),
            .verification
        )
        XCTAssertEqual(
            ModelUpdateFailure.classify(IOSModelDeliveryError.httpError(statusCode: 503)),
            .network
        )
    }

    /// RB-08: verifies `IOSBackgroundSessionCompletionCoordinator` closes Race A (wake before
    /// initial restore), Race B (`beginDownload` -> unstructured `Task { runDownload }` handoff
    /// and Model 1 -> Model 2 queue handoff), suspended-in-memory wakes, and mid-model rollovers
    /// without double-flushing UIKit's background completion handler.
    func testBackgroundSessionCompletionCoordinatorPreventsPrematureFlushRaces() {
        // Race A: background wake arrives before `restoreInFlightDownloadsIfNeeded()` starts.
        var raceA = IOSBackgroundSessionCompletionCoordinator()
        XCTAssertFalse(
            raceA.sessionDidFinishEvents(hasPendingOrInFlightWork: false),
            "must never flush before initial restore runs"
        )
        XCTAssertTrue(raceA.eventsFinished)
        XCTAssertFalse(
            raceA.canCompleteIdleWake(hasLedgerActiveWork: false, hasCoordinatorWork: false),
            "idle wake reconciliation must wait for initial restore"
        )
        raceA.beginPostprocessing()
        XCTAssertTrue(
            raceA.endInitialRestore(hasWork: false),
            "flushes once initial restore finishes with no restored work"
        )
        XCTAssertFalse(raceA.eventsFinished)
        XCTAssertTrue(
            raceA.canCompleteIdleWake(hasLedgerActiveWork: false, hasCoordinatorWork: false),
            "idle wake after initial restore completes immediately"
        )

        // Race B: `beginDownload` -> `runDownload` Task hop + Model 1 -> Model 2 handoff.
        var raceB = IOSBackgroundSessionCompletionCoordinator()
        raceB.beginPostprocessing() // restoreInFlightDownloadsIfNeeded
        raceB.beginPostprocessing() // beginDownload(model1)
        XCTAssertFalse(raceB.sessionDidFinishEvents(hasPendingOrInFlightWork: true))
        raceB.beginPostprocessing() // claimRunSubmissionHold(model1) BEFORE spawning Task
        XCTAssertFalse(raceB.endPostprocessing(), "beginDownload(model1) exit must not flush")
        XCTAssertFalse(raceB.endInitialRestore(hasWork: true), "restore exit must not flush while model1 hold is live")
        XCTAssertEqual(raceB.postprocessingDepth, 1)

        // Model 1 drains parked completions, writes terminal ledger, and hands off to Model 2.
        raceB.beginPostprocessing() // post-transfer hold in runDownload(model1)
        XCTAssertFalse(raceB.endPostprocessing(), "releasing model1 submission hold stays held by post-transfer hold")
        raceB.beginPostprocessing() // beginDownload(model2)
        raceB.beginPostprocessing() // claimRunSubmissionHold(model2)
        XCTAssertFalse(raceB.endPostprocessing(), "beginDownload(model2) exit must not flush")
        XCTAssertFalse(raceB.endPostprocessing(), "runDownload(model1) exit must not flush before model2 submits tasks")
        XCTAssertEqual(raceB.postprocessingDepth, 1)

        // Model 2 submits its live URLSessionDownloadTasks to nsurlsessiond -> flushes once.
        XCTAssertTrue(raceB.endPostprocessing(), "flushes promptly once model2 submits live tasks")
        XCTAssertEqual(raceB.postprocessingDepth, 0)
        XCTAssertFalse(raceB.flushIfReadyAfterTaskSubmission(), "never double-flushes")

        // Suspended-in-memory wake on Model 1 completion while inflight is still active.
        XCTAssertFalse(
            raceB.sessionDidFinishEvents(hasPendingOrInFlightWork: true),
            "must latch while inflight transfer is still verifying/installing"
        )
        raceB.beginPostprocessing() // post-transfer hold after downloadFiles returns
        XCTAssertTrue(raceB.endPostprocessing(), "flushes once terminal ledger write settles with no queued model")

        // Mid-model rollover (files 7+ submitted after files 1-6 finished while suspended).
        XCTAssertFalse(raceB.sessionDidFinishEvents(hasPendingOrInFlightWork: true))
        XCTAssertTrue(raceB.flushIfReadyAfterTaskSubmission(), "flushes once rollover tasks are submitted")
        XCTAssertFalse(raceB.flushIfReadyAfterTaskSubmission(), "never double-flushes rollover")
    }
}
