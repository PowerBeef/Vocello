import QwenVoiceCore
import XCTest

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
}
