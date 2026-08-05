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
        deleteAllFails: Bool = false,
        paths: [String] = [],
        existingPaths: Set<String>? = nil,
        failingRemovals: Set<String> = []
    ) -> HistoryDeletionEngine {
        HistoryDeletionEngine(
            deleteRecord: { id in
                log.append("deleteRecord(\(id))")
                if deleteRecordFails { throw StubError(message: "db down") }
            },
            deleteAllRecords: {
                log.append("deleteAllRecords")
                if deleteAllFails { throw StubError(message: "db down") }
            },
            audioPathsForAllRecords: {
                log.append("fetchPaths")
                return paths
            },
            removeFile: { path in
                log.append("removeFile(\(path))")
                if failingRemovals.contains(path) { throw StubError(message: "locked: \(path)") }
            },
            fileExists: { path in
                (existingPaths ?? Set(paths)).contains(path)
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

    func testSingleDeleteDatabaseFailureAbortsBeforeFileRemoval() {
        let log = EffectLog()
        let engine = makeEngine(log: log, deleteRecordFails: true, existingPaths: ["/a.wav"])
        let outcome = engine.deleteSingle(recordID: 7, audioPath: "/a.wav")
        XCTAssertEqual(outcome, .databaseFailure("db down"))
        XCTAssertEqual(log.snapshot, ["deleteRecord(7)"])
    }

    func testSingleDeleteRemovesRowThenFile() {
        let log = EffectLog()
        let engine = makeEngine(log: log, existingPaths: ["/a.wav"])
        let outcome = engine.deleteSingle(recordID: 7, audioPath: "/a.wav")
        XCTAssertEqual(outcome, .deleted)
        XCTAssertEqual(log.snapshot, ["deleteRecord(7)", "removeFile(/a.wav)"])
    }

    func testSingleDeleteMissingAudioSkipsRemoval() {
        let log = EffectLog()
        let engine = makeEngine(log: log, existingPaths: [])
        let outcome = engine.deleteSingle(recordID: 7, audioPath: "/gone.wav")
        XCTAssertEqual(outcome, .deleted)
        XCTAssertEqual(log.snapshot, ["deleteRecord(7)"])
    }

    func testSingleDeleteFileFailureIsWarningNotRollback() {
        let log = EffectLog()
        let engine = makeEngine(
            log: log, existingPaths: ["/a.wav"], failingRemovals: ["/a.wav"]
        )
        let outcome = engine.deleteSingle(recordID: 7, audioPath: "/a.wav")
        XCTAssertEqual(outcome, .audioCleanupFailure("locked: /a.wav"))
        XCTAssertEqual(log.snapshot, ["deleteRecord(7)", "removeFile(/a.wav)"])
    }

    func testClearAllSweepsFromDatabaseCountsFailuresAndStillWipesRows() throws {
        let log = EffectLog()
        let engine = makeEngine(
            log: log,
            paths: ["/a.wav", "/b.wav", "/c.wav"],
            existingPaths: ["/a.wav", "/b.wav"],
            failingRemovals: ["/b.wav"]
        )
        let outcome = try engine.clearAll(deleteAudio: true)
        XCTAssertEqual(outcome, HistoryDeletionEngine.ClearAllOutcome(failedFileRemovals: 1))
        XCTAssertEqual(
            log.snapshot,
            ["fetchPaths", "removeFile(/a.wav)", "removeFile(/b.wav)", "deleteAllRecords"]
        )
    }

    func testClearAllKeepFilesSkipsSweep() throws {
        let log = EffectLog()
        let engine = makeEngine(log: log, paths: ["/a.wav"])
        let outcome = try engine.clearAll(deleteAudio: false)
        XCTAssertEqual(outcome.failedFileRemovals, 0)
        XCTAssertEqual(log.snapshot, ["deleteAllRecords"])
    }

    func testClearAllDatabaseFailureSurfacesAfterSweep() {
        let log = EffectLog()
        let engine = makeEngine(log: log, deleteAllFails: true, paths: ["/a.wav"])
        XCTAssertThrowsError(try engine.clearAll(deleteAudio: true)) { error in
            XCTAssertEqual(error as? HistoryDeletionEngine.ClearAllError, .database("db down"))
        }
        XCTAssertEqual(log.snapshot, ["fetchPaths", "removeFile(/a.wav)", "deleteAllRecords"])
    }
}
