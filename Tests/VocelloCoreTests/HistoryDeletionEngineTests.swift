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
        XCTAssertEqual(outcome, .databaseFailure("list unwritable"))
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
}
