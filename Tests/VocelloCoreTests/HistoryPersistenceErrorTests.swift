import Darwin
import Foundation
import GRDB
import QwenVoiceCore
import Synchronization
import XCTest

final class HistoryPersistenceErrorTests: XCTestCase {
    func testClassifiesStorageAndPermissionFailuresWithoutLeakingSourceText() {
        let full = HistoryPersistenceError.classify(
            NSError(domain: NSPOSIXErrorDomain, code: Int(ENOSPC)),
            operation: .write
        )
        XCTAssertEqual(full, HistoryPersistenceError(operation: .write, failure: .storageFull))

        let denied = HistoryPersistenceError.classify(
            NSError(
                domain: NSCocoaErrorDomain,
                code: CocoaError.Code.fileReadNoPermission.rawValue,
                userInfo: [NSLocalizedDescriptionKey: "/" + "Users/private-user/history.sqlite"]
            ),
            operation: .read
        )
        XCTAssertEqual(denied.failure, .permissionDenied)
        XCTAssertFalse(try XCTUnwrap(denied.errorDescription).contains("/" + "Users/"))
    }

    func testClassifiesSQLiteCorruptionAndLockAsTypedFailures() {
        let corrupt = HistoryPersistenceError.classify(
            NSError(
                domain: "fixture.sqlite",
                code: 11,
                userInfo: [NSLocalizedDescriptionKey: "database disk image is malformed at /private/data"]
            ),
            operation: .read
        )
        XCTAssertEqual(corrupt.failure, .corrupt)
        XCTAssertFalse(try XCTUnwrap(corrupt.errorDescription).contains("/private/data"))

        let locked = HistoryPersistenceError.classify(
            NSError(
                domain: "fixture.sqlite",
                code: 5,
                userInfo: [NSLocalizedDescriptionKey: "database is locked"]
            ),
            operation: .delete
        )
        XCTAssertEqual(locked.failure, .locked)
        XCTAssertEqual(locked.operation, .delete)
    }

    func testMigrationFailuresPreserveTypedReasonAcrossLaterOperations() {
        let migration = HistoryPersistenceError.classify(
            NSError(domain: "fixture", code: 1),
            operation: .migrate
        )
        XCTAssertEqual(migration.failure, .migrationFailed)

        let read = migration.replacingOperation(.read)
        XCTAssertEqual(read.operation, .read)
        XCTAssertEqual(read.failure, .migrationFailed)
        XCTAssertTrue(try XCTUnwrap(read.errorDescription).contains("preserved"))
    }

    // MARK: - Suspension (IOS-11)

    func testSuspensionInterruptionsAreTransientForEveryOperation() {
        // SQLITE_ABORT, SQLITE_INTERRUPT and the extended SQLITE_ABORT_ROLLBACK,
        // as GRDB's DatabaseError bridges them.
        for code in [4, 9, 516] {
            for operation in [HistoryPersistenceOperation.initialize, .migrate, .read, .write, .delete] {
                let classified = HistoryPersistenceError.classify(
                    NSError(
                        domain: HistoryPersistenceError.sqliteErrorDomain,
                        code: code,
                        userInfo: [NSLocalizedDescriptionKey: "SQLite error \(code): Database is suspended"]
                    ),
                    operation: operation
                )
                XCTAssertEqual(classified, HistoryPersistenceError(operation: operation, failure: .locked))
            }
        }
        let other = HistoryPersistenceError.classify(
            NSError(domain: HistoryPersistenceError.sqliteErrorDomain, code: 11),
            operation: .write
        )
        XCTAssertNotEqual(other.failure, .locked, "Only an interruption is transient")
    }

    func testSuspendedHistoryWriteIsTransientAndSucceedsAfterResume() throws {
        let queue = try makeSuspendableQueue()
        NotificationCenter.default.post(name: Database.suspendNotification, object: nil)
        defer { NotificationCenter.default.post(name: Database.resumeNotification, object: nil) }

        var refusal: Error?
        do {
            try queue.write { db in
                var generation = Self.generation()
                try generation.insert(db)
            }
        } catch {
            refusal = error
        }
        let error = try XCTUnwrap(refusal)
        XCTAssertEqual((error as? DatabaseError)?.isInterruptionError, true)
        for operation in [HistoryPersistenceOperation.write, .delete, .read, .migrate] {
            XCTAssertEqual(HistoryPersistenceError.classify(error, operation: operation).failure, .locked)
        }

        NotificationCenter.default.post(name: Database.resumeNotification, object: nil)
        try queue.write { db in
            var generation = Self.generation()
            try generation.insert(db)
        }
        XCTAssertEqual(try queue.read { try Generation.fetchCount($0) }, 1)
    }

    func testMigrationInterruptedBySuspensionIsTransientAndReopensAfterResume() throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("HistorySuspension-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let path = directory.appendingPathComponent("history.sqlite").path
        let suspendsDuringOpen = Mutex(true)
        // The DatabaseService open path: a failed open stays failed (fail
        // closed) until an explicit reopen.
        let coordinator = RecoverableStoreCoordinator<DatabaseQueue, HistoryPersistenceError>(
            openStore: {
                var configuration = Configuration()
                configuration.observesSuspensionNotifications = true
                let queue = try DatabaseQueue(path: path, configuration: configuration)
                if suspendsDuringOpen.withLock({ $0 }) {
                    NotificationCenter.default.post(name: Database.suspendNotification, object: nil)
                }
                do {
                    try GenerationMigrations.makeMigrator().migrate(queue)
                    return queue
                } catch {
                    throw HistoryPersistenceError.classify(error, operation: .migrate)
                }
            },
            classify: { HistoryPersistenceError.classify($0, operation: .initialize) }
        )
        defer { NotificationCenter.default.post(name: Database.resumeNotification, object: nil) }

        XCTAssertThrowsError(try coordinator.requireStore()) { error in
            XCTAssertEqual(
                (error as? HistoryPersistenceError)?.failure,
                .locked,
                "An interrupted upgrade is neither damage nor a failed migration"
            )
        }

        NotificationCenter.default.post(name: Database.resumeNotification, object: nil)
        suspendsDuringOpen.withLock { $0 = false }
        let queue = try coordinator.reopenIfNeeded()
        XCTAssertEqual(try queue.read { try Generation.fetchCount($0) }, 0)
    }

    private func makeSuspendableQueue() throws -> DatabaseQueue {
        var configuration = Configuration()
        configuration.observesSuspensionNotifications = true
        let queue = try DatabaseQueue(configuration: configuration)
        try GenerationMigrations.makeMigrator().migrate(queue)
        return queue
    }

    private static func generation() -> Generation {
        Generation(
            id: nil,
            text: "Local test sentence",
            mode: "custom",
            modelTier: "lite",
            voice: "Aiden",
            emotion: "Neutral",
            speed: 1,
            audioPath: "history-suspension-fixture.wav",
            duration: 1,
            createdAt: Date(timeIntervalSince1970: 1_700_000_000),
            longFormProjectID: nil,
            longFormRole: nil,
            seed: 42
        )
    }
}
