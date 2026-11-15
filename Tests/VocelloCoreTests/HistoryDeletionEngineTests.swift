import XCTest
@testable import QwenVoiceCore

/// W2-B: the delete-path sequencing rules History previously kept as
/// logic-in-view, now deterministic. Stub closures record effect order so
/// the tests can assert what was (and was NOT) touched.
final class HistoryDeletionEngineTests: XCTestCase {
    private final class EffectLog: @unchecked Sendable {
        private let lock = NSLock()
        private var entries: [String] = []

        func append(_ entry: String) {
            lock.lock()
            defer { lock.unlock() }
            entries.append(entry)
        }

        var snapshot: [String] {
            lock.lock()
            defer { lock.unlock() }
            return entries
        }
    }

    private struct StubError: LocalizedError {
        let message: String
        var errorDescription: String? { message }
    }

    private func makeEngine(
        log: EffectLog,
        deleteRecordFails: Bool = false,
        recordFails: Bool = false,
        paths: [String] = [],
        existingPaths: Set<String>? = nil,
        failingRemovals: Set<String> = []
    ) -> HistoryDeletionEngine {
        HistoryDeletionEngine(
            deleteRecord: { id in
                log.append("deleteRecord(\(id))")
                if deleteRecordFails { throw StubError(message: "db down") }
            },
            removeFile: { path in
                log.append("removeFile(\(path))")
                if failingRemovals.contains(path) { throw StubError(message: "locked: \(path)") }
            },
            fileExists: { path in
                (existingPaths ?? Set(paths)).contains(path)
            },
            recordAudioRemoval: { path in
                log.append("record(\(path))")
                if recordFails { throw StubError(message: "list unwritable") }
            },
            withdrawAudioRemoval: { path in
                log.append("withdraw(\(path))")
            }
        )
    }

    func testSingleDeleteMissingIdentifierTouchesNothing() {
        let log = EffectLog()
        let engine = makeEngine(log: log)
        let outcome = engine.deleteSingle(recordID: nil, audioPath: "/a.wav")
        XCTAssertEqual(outcome, .databaseFailure("Missing generation identifier."))
        XCTAssertEqual(log.snapshot, [])
    }

    /// The row stays, so the removal recorded for it is withdrawn.
    func testSingleDeleteDatabaseFailureAbortsBeforeFileRemoval() {
        let log = EffectLog()
        let engine = makeEngine(log: log, deleteRecordFails: true, existingPaths: ["/a.wav"])
        let outcome = engine.deleteSingle(recordID: 7, audioPath: "/a.wav")
        XCTAssertEqual(outcome, .databaseFailure("db down"))
        XCTAssertEqual(log.snapshot, ["record(/a.wav)", "deleteRecord(7)", "withdraw(/a.wav)"])
    }

    /// A2-04: the removal is recorded before the row goes, as a clear records
    /// its intent first, and withdrawn once the file is gone.
    func testSingleDeleteRecordsTheRemovalThenRemovesRowThenFile() {
        let log = EffectLog()
        let engine = makeEngine(log: log, existingPaths: ["/a.wav"])
        let outcome = engine.deleteSingle(recordID: 7, audioPath: "/a.wav")
        XCTAssertEqual(outcome, .deleted)
        XCTAssertEqual(log.snapshot, [
            "record(/a.wav)", "deleteRecord(7)", "removeFile(/a.wav)", "withdraw(/a.wav)",
        ])
    }

    /// A2-04: a removal that cannot be recorded deletes nothing.
    func testSingleDeleteThatCannotRecordTheRemovalTouchesNothing() {
        let log = EffectLog()
        let engine = makeEngine(log: log, recordFails: true, existingPaths: ["/a.wav"])
        let outcome = engine.deleteSingle(recordID: 7, audioPath: "/a.wav")
        XCTAssertEqual(outcome, .removalUnrecorded, "the database is fine; only the removal list failed")
        XCTAssertEqual(log.snapshot, ["record(/a.wav)"])
    }

    func testSingleDeleteMissingAudioSkipsRemoval() {
        let log = EffectLog()
        let engine = makeEngine(log: log, existingPaths: [])
        let outcome = engine.deleteSingle(recordID: 7, audioPath: "/gone.wav")
        XCTAssertEqual(outcome, .deleted)
        XCTAssertEqual(log.snapshot, ["deleteRecord(7)"])
    }

    /// The removal stays recorded, for a later reconcile to retry.
    func testSingleDeleteFileFailureIsWarningNotRollback() {
        let log = EffectLog()
        let engine = makeEngine(
            log: log, existingPaths: ["/a.wav"], failingRemovals: ["/a.wav"]
        )
        let outcome = engine.deleteSingle(recordID: 7, audioPath: "/a.wav")
        XCTAssertEqual(outcome, .audioCleanupFailure("locked: /a.wav"))
        XCTAssertEqual(log.snapshot, ["record(/a.wav)", "deleteRecord(7)", "removeFile(/a.wav)"])
    }

    // MARK: - The player's file among the deleted audio

    /// A deleted row's audio leaves the player, whether or not its file could
    /// be removed; a delete that deleted nothing leaves the player alone.
    func testAOneRowDeleteRemovesThePlayersFileOnlyWhenTheRowWent() {
        let gone: [HistoryDeletionEngine.SingleOutcome] = [.deleted, .audioCleanupFailure("locked")]
        for outcome in gone {
            let result = HistoryDeletionResult(single: outcome, recordID: 7, audioPath: "/a.wav")
            XCTAssertEqual(result.deletedAudioPaths, ["/a.wav"], "\(outcome)")
            XCTAssertTrue(result.removesAudio(heldByPlayerAt: "/a.wav"), "\(outcome)")
            XCTAssertFalse(result.removesAudio(heldByPlayerAt: "/b.wav"), "\(outcome)")
            XCTAssertFalse(result.removesAudio(heldByPlayerAt: nil), "\(outcome)")
        }
        let kept: [HistoryDeletionEngine.SingleOutcome] = [.databaseFailure("db down"), .removalUnrecorded]
        for outcome in kept {
            let result = HistoryDeletionResult(single: outcome, recordID: 7, audioPath: "/a.wav")
            XCTAssertEqual(result.deletedAudioPaths, [], "\(outcome)")
            XCTAssertFalse(result.removesAudio(heldByPlayerAt: "/a.wav"), "\(outcome)")
        }
    }

    /// A project's delete covers the joined output and every segment, so the
    /// player is dismissed whichever of them it holds. The path is compared
    /// exactly, as the app compares the player's file everywhere else.
    func testAProjectDeleteRemovesThePlayersFileWhicheverRowItHolds() {
        let log = EffectLog()
        let engine = makeEngine(
            log: log, existingPaths: ["/joined.wav", "/s1.wav", "/s2.wav"], failingRemovals: ["/s1.wav"]
        )
        let result = engine.deleteUnit(rows: projectRows, deleteRecords: { _ in })
        for path in ["/joined.wav", "/s1.wav", "/s2.wav"] {
            XCTAssertTrue(result.removesAudio(heldByPlayerAt: path), path)
        }
        XCTAssertFalse(result.removesAudio(heldByPlayerAt: "/other.wav"))
        XCTAssertFalse(result.removesAudio(heldByPlayerAt: "/S1.wav"), "The exact path, never a folded one")
        XCTAssertFalse(result.removesAudio(heldByPlayerAt: "/./s1.wav"), "The exact path, never a resolved one")
        XCTAssertFalse(result.removesAudio(heldByPlayerAt: nil), "A player holding no file")

        let refused = engine.deleteUnit(rows: projectRows, deleteRecords: { _ in throw StubError(message: "db down") })
        XCTAssertFalse(refused.removesAudio(heldByPlayerAt: "/joined.wav"), "Nothing was deleted")
    }

    // MARK: - Long-form project as a unit (A4)

    /// A project's joined row and its two segments.
    private let projectRows = [
        HistoryDeletionRow(id: 9, audioPath: "/joined.wav"),
        HistoryDeletionRow(id: 7, audioPath: "/s1.wav"),
        HistoryDeletionRow(id: 8, audioPath: "/s2.wav"),
    ]

    /// Every removal is recorded before any row goes, the rows go in one
    /// call, and each record is withdrawn once its file is gone.
    func testUnitDeleteRecordsEveryRemovalThenDeletesTheRowsOnceThenRemovesTheFiles() {
        let log = EffectLog()
        let engine = makeEngine(log: log, existingPaths: ["/joined.wav", "/s1.wav", "/s2.wav"])
        let result = engine.deleteUnit(rows: projectRows, deleteRecords: { log.append("deleteRecords(\($0))") })
        XCTAssertEqual(
            result,
            HistoryDeletionResult(
                outcome: .deleted,
                deletedRowIDs: [9, 7, 8],
                deletedAudioPaths: ["/joined.wav", "/s1.wav", "/s2.wav"],
                unremovedAudioPaths: []
            )
        )
        XCTAssertEqual(log.snapshot, [
            "record(/joined.wav)", "record(/s1.wav)", "record(/s2.wav)",
            "deleteRecords([9, 7, 8])",
            "removeFile(/joined.wav)", "withdraw(/joined.wav)",
            "removeFile(/s1.wav)", "withdraw(/s1.wav)",
            "removeFile(/s2.wav)", "withdraw(/s2.wav)",
        ])
        XCTAssertFalse(log.snapshot.contains { $0.hasPrefix("deleteRecord(") }, "No row is deleted on its own")
    }

    /// The rows stay, so every removal recorded for them is withdrawn and no
    /// file is touched.
    func testUnitDeleteDatabaseFailureWithdrawsEveryRecordAndRemovesNoFile() {
        let log = EffectLog()
        let engine = makeEngine(log: log, existingPaths: ["/joined.wav", "/s1.wav", "/s2.wav"])
        let result = engine.deleteUnit(rows: projectRows, deleteRecords: { _ in throw StubError(message: "db down") })
        XCTAssertEqual(
            result,
            HistoryDeletionResult(
                outcome: .databaseFailure("db down"), deletedRowIDs: [], deletedAudioPaths: [], unremovedAudioPaths: []
            )
        )
        XCTAssertEqual(log.snapshot, [
            "record(/joined.wav)", "record(/s1.wav)", "record(/s2.wav)",
            "withdraw(/joined.wav)", "withdraw(/s1.wav)", "withdraw(/s2.wav)",
        ])
    }

    /// One removal that cannot be recorded deletes nothing, and the removals
    /// recorded before it are withdrawn.
    func testUnitDeleteThatCannotRecordARemovalDeletesNothing() {
        let log = EffectLog()
        let engine = HistoryDeletionEngine(
            deleteRecord: { log.append("deleteRecord(\($0))") },
            removeFile: { log.append("removeFile(\($0))") },
            fileExists: { _ in true },
            recordAudioRemoval: { path in
                log.append("record(\(path))")
                if path == "/s1.wav" { throw StubError(message: "list unwritable") }
            },
            withdrawAudioRemoval: { log.append("withdraw(\($0))") }
        )
        let result = engine.deleteUnit(rows: projectRows, deleteRecords: { log.append("deleteRecords(\($0))") })
        XCTAssertEqual(
            result,
            HistoryDeletionResult(
                outcome: .removalUnrecorded, deletedRowIDs: [], deletedAudioPaths: [], unremovedAudioPaths: []
            )
        )
        XCTAssertEqual(log.snapshot, ["record(/joined.wav)", "record(/s1.wav)", "withdraw(/joined.wav)"])
    }

    /// The rows are gone; the file that stayed keeps its removal recorded and
    /// is named in the result, and the other files are still removed.
    func testUnitDeleteFileFailureIsAWarningAndNamesTheFileThatStayed() {
        let log = EffectLog()
        let engine = makeEngine(
            log: log, existingPaths: ["/joined.wav", "/s1.wav", "/s2.wav"], failingRemovals: ["/s1.wav"]
        )
        let result = engine.deleteUnit(rows: projectRows, deleteRecords: { log.append("deleteRecords(\($0))") })
        XCTAssertEqual(
            result,
            HistoryDeletionResult(
                outcome: .audioCleanupFailure("locked: /s1.wav"),
                deletedRowIDs: [9, 7, 8],
                deletedAudioPaths: ["/joined.wav", "/s1.wav", "/s2.wav"],
                unremovedAudioPaths: ["/s1.wav"]
            )
        )
        XCTAssertEqual(log.snapshot, [
            "record(/joined.wav)", "record(/s1.wav)", "record(/s2.wav)",
            "deleteRecords([9, 7, 8])",
            "removeFile(/joined.wav)", "withdraw(/joined.wav)",
            "removeFile(/s1.wav)",
            "removeFile(/s2.wav)", "withdraw(/s2.wav)",
        ])
    }

    /// Audio that is already gone is skipped, and a path two rows share is
    /// handled once; every row still goes.
    func testUnitDeleteSkipsMissingAudioAndHandlesASharedPathOnce() {
        let log = EffectLog()
        let engine = makeEngine(log: log, existingPaths: ["/joined.wav", "/s1.wav"])
        let rows = projectRows + [HistoryDeletionRow(id: 10, audioPath: "/s1.wav")]
        let result = engine.deleteUnit(rows: rows, deleteRecords: { log.append("deleteRecords(\($0))") })
        XCTAssertEqual(
            result,
            HistoryDeletionResult(
                outcome: .deleted,
                deletedRowIDs: [9, 7, 8, 10],
                // The audio of every row that went, the missing file's too.
                deletedAudioPaths: ["/joined.wav", "/s1.wav", "/s2.wav"],
                unremovedAudioPaths: []
            )
        )
        XCTAssertEqual(log.snapshot, [
            "record(/joined.wav)", "record(/s1.wav)",
            "deleteRecords([9, 7, 8, 10])",
            "removeFile(/joined.wav)", "withdraw(/joined.wav)",
            "removeFile(/s1.wav)", "withdraw(/s1.wav)",
        ])
    }
}
