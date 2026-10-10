import Foundation
import GRDB
import XCTest

/// Populated historical schemas are upgraded by the shipped migrator, rather
/// than recreating a current-schema database and only testing its readers.
final class GenerationMigrationUpgradeTests: XCTestCase {
    func testPopulatedV1UpgradesWithoutChangingRetainedHistory() throws {
        try assertUpgrade(from: "v1_create_generations")
    }

    func testPopulatedV2UpgradesWithoutChangingRetainedHistory() throws {
        try assertUpgrade(from: "v2_add_sortOrder")
    }

    func testPopulatedV5UpgradesWithoutChangingLongFormHistory() throws {
        try assertUpgrade(from: "v5_add_long_form_project", hasLongFormColumns: true)
    }

    func testV5UpgradePreservesDeletedAutoincrementHighWater() throws {
        let queue = try seededQueue(upTo: "v5_add_long_form_project")
        try insertAndDeleteHighWater(in: queue)

        try GenerationMigrations.makeMigrator().migrate(queue)

        try queue.write { db in
            XCTAssertEqual(try sequence(in: db), 900)
            try insertNext(in: db)
            XCTAssertEqual(db.lastInsertedRowID, 901, "Additive migrations preserve ids of deleted takes")
        }
    }

    /// Characterizes the shipped v3 rebuild; this is a documented upgrade
    /// limitation, not a claim that old deleted ids remain reserved. The
    /// rebuild retains live ids but copies no deleted sqlite_sequence bound.
    func testV3RebuildCurrentlyResetsDeletedHighWaterToLargestRetainedID() throws {
        for version in ["v1_create_generations", "v2_add_sortOrder"] {
            let queue = try seededQueue(upTo: version)
            try insertAndDeleteHighWater(in: queue)

            try GenerationMigrations.makeMigrator().migrate(queue)

            try queue.write { db in
                XCTAssertEqual(try sequence(in: db), 41, version)
                try insertNext(in: db)
                XCTAssertEqual(db.lastInsertedRowID, 42, "\(version): v3 currently loses the deleted high-water mark")
            }
        }
    }

    private func assertUpgrade(from version: String, hasLongFormColumns: Bool = false) throws {
        let queue = try seededQueue(upTo: version)
        let retainedColumns = "id, text, mode, modelTier, voice, emotion, speed, audioPath, duration, createdAt"
            + (hasLongFormColumns ? ", longFormProjectID, longFormRole" : "")
        let retainedQuery = "SELECT \(retainedColumns) FROM generations ORDER BY id"
        let before = try queue.read { try Row.fetchAll($0, sql: retainedQuery) }

        let migrator = GenerationMigrations.makeMigrator()
        try migrator.migrate(queue)

        try queue.write { db in
            XCTAssertEqual(try Row.fetchAll(db, sql: retainedQuery), before, version)
            XCTAssertEqual(Set(try db.columns(in: "generations").map(\.name)), [
                "id", "text", "mode", "modelTier", "voice", "emotion", "speed", "audioPath",
                "duration", "createdAt", "longFormProjectID", "longFormRole", "seed",
            ])
            let rows = try Generation.order(Generation.Columns.id).fetchAll(db)
            XCTAssertEqual(rows.map(\.id), [3, 41])
            XCTAssertEqual(rows.map(\.audioPath), ["/nonexistent/shared-history.wav", "/nonexistent/shared-history.wav"])
            XCTAssertTrue(rows.allSatisfy { $0.seed == nil }, "Pre-v6 seeds must remain unknown")
            XCTAssertNil(rows[0].voice)
            XCTAssertNil(rows[0].emotion)
            XCTAssertNil(rows[0].speed)
            XCTAssertNil(rows[0].duration)
            XCTAssertNil(rows[0].longFormProjectID)
            XCTAssertNil(rows[0].longFormRole)
            XCTAssertEqual(rows[1].longFormProjectID, hasLongFormColumns ? "historical-project" : nil)
            XCTAssertEqual(rows[1].longFormRole, hasLongFormColumns ? "joined" : nil)
            try assertIndexes(in: db)
            XCTAssertEqual(try sequence(in: db), 41, "Live ids survive the table rebuild")
            try insertNext(in: db)
            XCTAssertEqual(db.lastInsertedRowID, 42)
            // The signed storage bit pattern must survive a subsequent open;
            // nil stays nil for the historical row whose seed was not recorded.
            try db.execute(sql: "UPDATE generations SET seed = ? WHERE id = 41", arguments: [Int64.min])
        }

        let upgraded = try queue.read { try Generation.order(Generation.Columns.id).fetchAll($0) }
        let applied = try queue.read { try String.fetchAll($0, sql: "SELECT identifier FROM grdb_migrations ORDER BY identifier") }
        XCTAssertEqual(applied.count, 7)
        try migrator.migrate(queue)
        try queue.read { db in
            XCTAssertEqual(try Generation.order(Generation.Columns.id).fetchAll(db), upgraded, "Reopening is idempotent")
            XCTAssertEqual(try String.fetchAll(db, sql: "SELECT identifier FROM grdb_migrations ORDER BY identifier"), applied)
            XCTAssertEqual(try sequence(in: db), 42)
            XCTAssertEqual(upgraded[1].samplingSeed, UInt64(1) << 63)
            XCTAssertNil(upgraded[0].samplingSeed)
            try assertIndexes(in: db)
        }
    }

    private func seededQueue(upTo version: String) throws -> DatabaseQueue {
        let queue = try DatabaseQueue()
        try GenerationMigrations.makeMigrator().migrate(queue, upTo: version)
        try queue.write { db in
            try db.execute(sql: """
                INSERT INTO generations (id, text, mode, modelTier, voice, emotion, speed, audioPath, duration, createdAt)
                VALUES (3, 'older retained take', 'custom', 'speed', NULL, NULL, NULL,
                        '/nonexistent/shared-history.wav', NULL, '2025-01-01 12:00:00'),
                       (41, 'newer retained take', 'design', 'quality', 'narrator', 'calm', 0.9,
                        '/nonexistent/shared-history.wav', 2.5, '2025-02-01 12:00:00')
                """)
            if version == "v2_add_sortOrder" {
                try db.execute(sql: "UPDATE generations SET sortOrder = CASE id WHEN 41 THEN 0 ELSE 1 END")
            }
            if version == "v5_add_long_form_project" {
                try db.execute(sql: """
                    UPDATE generations SET longFormProjectID = 'historical-project', longFormRole = 'joined' WHERE id = 41
                    """)
            }
        }
        return queue
    }

    private func insertAndDeleteHighWater(in queue: DatabaseQueue) throws {
        try queue.write { db in
            try db.execute(sql: """
                INSERT INTO generations (id, text, mode, modelTier, audioPath)
                VALUES (900, 'deleted take', 'custom', 'speed', '/nonexistent/deleted-history.wav')
                """)
            try db.execute(sql: "DELETE FROM generations WHERE id = 900")
            XCTAssertEqual(try sequence(in: db), 900)
        }
    }

    private func sequence(in db: Database) throws -> Int64? {
        try Int64.fetchOne(db, sql: "SELECT seq FROM sqlite_sequence WHERE name = 'generations'")
    }

    private func insertNext(in db: Database) throws {
        try db.execute(sql: """
            INSERT INTO generations (text, mode, modelTier, audioPath)
            VALUES ('post-upgrade take', 'custom', 'speed', '/nonexistent/post-upgrade.wav')
            """)
    }

    private func assertIndexes(in db: Database) throws {
        let indexes = try db.indexes(on: "generations")
        XCTAssertEqual(Dictionary(uniqueKeysWithValues: indexes.map { ($0.name, $0.columns) }), [
            "idx_generations_createdAt": ["createdAt"],
            "idx_generations_longFormProjectID": ["longFormProjectID"],
            "idx_generations_audioPath": ["audioPath"],
        ])
        XCTAssertFalse(try XCTUnwrap(indexes.first { $0.name == "idx_generations_audioPath" }).isUnique,
                       "Multiple takes can legitimately reference the same audio")
    }
}

/// PA-19: the History database service both apps share, opened on a private
/// directory through its root-directory seam. The page query, the long-form
/// acceptance journal and error classification have their own suites; these
/// tests hold the service's own CRUD, idempotence, supersession and fail-closed
/// open behavior against real SQLite.
final class DatabaseServiceTests: XCTestCase {
    private func makeRoot(creatingDirectory: Bool = true) throws -> URL {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("DatabaseService-\(UUID().uuidString)", isDirectory: true)
        if creatingDirectory {
            try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        }
        addTeardownBlock { try? FileManager.default.removeItem(at: root) }
        return root
    }

    private func makeService() throws -> DatabaseService {
        DatabaseService(rootDirectory: try makeRoot())
    }

    private func row(
        _ audioPath: String,
        text: String = "PA-19 fixture take",
        at seconds: TimeInterval,
        projectID: String? = nil,
        role: String? = nil
    ) -> Generation {
        Generation(
            id: nil,
            text: text,
            mode: "custom",
            modelTier: "speed",
            voice: "Aiden",
            emotion: nil,
            speed: nil,
            audioPath: audioPath,
            duration: 1.5,
            createdAt: Date(timeIntervalSince1970: 1_700_000_000 + seconds),
            longFormProjectID: projectID,
            longFormRole: role,
            seed: 42
        )
    }

    func testSavedRowsReadBackNewestFirstAndPageThroughTheService() throws {
        let service = try makeService()
        XCTAssertEqual(try service.fetchAllGenerations(), [])

        var saved: [Generation] = []
        for index in 0..<3 {
            var generation = row("/nonexistent/take-\(index).wav", text: "take \(index)", at: Double(index))
            try service.saveGeneration(&generation)
            XCTAssertNotNil(generation.id, "The insert assigns the row id")
            saved.append(generation)
        }

        XCTAssertEqual(try service.fetchAllGenerations().map(\.text), ["take 2", "take 1", "take 0"])
        XCTAssertEqual(try service.fetchAllGenerations().first?.id, saved[2].id)

        let page = try service.fetchGenerationPage(GenerationHistoryPageRequest(limit: 2))
        XCTAssertEqual(page.rows.map(\.text), ["take 2", "take 1"])
        XCTAssertTrue(page.hasMore)
        XCTAssertEqual(page.archiveCount, 3)
    }

    func testSaveIfMissingIsIdempotentByAudioPath() async throws {
        let service = try makeService()
        let first = try await service.saveGenerationIfMissingAsync(row("/nonexistent/same.wav", text: "original", at: 0))
        let firstID = try XCTUnwrap(first.id)

        // A retried outbox commit for the same audio returns the stored row unchanged.
        let retried = try await service.saveGenerationAsync(row("/nonexistent/same.wav", text: "retried", at: 5))
        XCTAssertEqual(retried.id, firstID)
        XCTAssertEqual(retried.text, "original")

        let other = try await service.saveGenerationAsync(row("/nonexistent/other.wav", at: 10))
        XCTAssertNotEqual(other.id, firstID)
        XCTAssertEqual(try service.fetchAllGenerations().count, 2)
    }

    func testReplacingTheJoinedOutputSupersedesOnlyThatProjectsJoinedRow() async throws {
        let service = try makeService()
        _ = try await service.saveGenerationAsync(
            row("/nonexistent/p-segment.wav", at: 0, projectID: "project-p", role: "segment")
        )
        let firstJoined = try await service.replaceLongFormJoinedGenerationAsync(
            row("/nonexistent/p-joined-1.wav", at: 1, projectID: "project-p", role: "joined")
        )
        let otherProject = try await service.replaceLongFormJoinedGenerationAsync(
            row("/nonexistent/q-joined.wav", at: 2, projectID: "project-q", role: "joined")
        )

        let replacement = try await service.replaceLongFormJoinedGenerationIfMissingAsync(
            row("/nonexistent/p-joined-2.wav", at: 3, projectID: "project-p", role: "joined")
        )
        var roles = Dictionary(
            uniqueKeysWithValues: try service.fetchAllGenerations().map { ($0.audioPath, $0.longFormRole) }
        )
        XCTAssertEqual(roles["/nonexistent/p-joined-1.wav"], "superseded", "The older joined output stays deletable")
        XCTAssertEqual(roles["/nonexistent/p-joined-2.wav"], "joined")
        XCTAssertEqual(roles["/nonexistent/p-segment.wav"], "segment", "Segments are untouched")
        XCTAssertEqual(roles["/nonexistent/q-joined.wav"], "joined", "Another project's joined output is untouched")
        XCTAssertNotEqual(replacement.id, firstJoined.id)
        XCTAssertNotNil(otherProject.id)

        // Replaying the accepted replacement is a no-op: it returns the stored row.
        let replayed = try await service.replaceLongFormJoinedGenerationAsync(
            row("/nonexistent/p-joined-2.wav", at: 4, projectID: "project-p", role: "joined")
        )
        XCTAssertEqual(replayed.id, replacement.id)
        roles = Dictionary(
            uniqueKeysWithValues: try service.fetchAllGenerations().map { ($0.audioPath, $0.longFormRole) }
        )
        XCTAssertEqual(roles["/nonexistent/p-joined-2.wav"], "joined")
        XCTAssertEqual(try service.fetchAllGenerations().count, 4)
    }

    func testReferencedAudioPathsReachEveryQueryChunk() throws {
        let service = try makeService()
        XCTAssertEqual(try service.referencedAudioPaths(among: []), [])

        let candidates = (0..<1_203).map { "/nonexistent/candidate-\($0).wav" }
        let referenced: Set<String> = [candidates[0], candidates[499], candidates[500], candidates[1_202]]
        for (offset, path) in referenced.sorted().enumerated() {
            var generation = row(path, at: Double(offset))
            try service.saveGeneration(&generation)
        }
        var unrelated = row("/nonexistent/not-a-candidate.wav", at: 100)
        try service.saveGeneration(&unrelated)

        // 1 203 paths query in three 500-path chunks.
        XCTAssertEqual(try service.referencedAudioPaths(among: candidates), referenced)
    }

    func testDeletesRemoveOneRowOrABoundedClear() throws {
        let service = try makeService()
        var ids: [Int64] = []
        for index in 0..<3 {
            var generation = row("/nonexistent/delete-\(index).wav", at: Double(index))
            try service.saveGeneration(&generation)
            ids.append(try XCTUnwrap(generation.id))
        }

        try service.deleteGeneration(id: ids[1])
        XCTAssertEqual(
            try service.fetchAllGenerations().map(\.audioPath),
            ["/nonexistent/delete-2.wav", "/nonexistent/delete-0.wav"]
        )
        try service.deleteGeneration(id: ids[1])
        XCTAssertEqual(try service.fetchAllGenerations().count, 2, "Deleting a missing row is harmless")

        // Clear-all is bounded by the newest id it saw: it removes those rows,
        // reports their audio, and keeps a take saved after the bound (AUD-05).
        let bound = ids[2]
        var later = row("/nonexistent/delete-later.wav", at: 10)
        try service.saveGeneration(&later)
        let removed = try service.deleteGenerations(throughID: bound)
        XCTAssertEqual(Set(removed), ["/nonexistent/delete-0.wav", "/nonexistent/delete-2.wav"])
        XCTAssertEqual(try service.fetchAllGenerations().map(\.audioPath), ["/nonexistent/delete-later.wav"])
        XCTAssertEqual(try service.deleteGenerations(throughID: bound), [], "A resumed clear deletes nothing twice")
    }

    // MARK: - Long-form recovery (PA-30)

    private struct InjectedFailure: Error {}

    /// A long-form acceptance a suspended History interrupted, prepared under the
    /// service's root with its journal marked resumable.
    private func interruptedAcceptance(in root: URL) throws -> LongFormHistoryAcceptanceTests.Fixture {
        let f = try LongFormHistoryAcceptanceTests.makeFixture(
            in: root,
            journalRoot: root.appendingPathComponent("history-outbox/long-form", isDirectory: true)
        )
        XCTAssertThrowsError(try f.queue.write { db in
            try f.store.prepare(f.input, in: db)
            throw InjectedFailure()
        })
        XCTAssertTrue(try f.store.markResumable(f.input))
        return f
    }

    func testLongFormRecoveryCompletesAnInterruptedAcceptanceInOneCall() throws {
        let root = try makeRoot().resolvingSymlinksInPath()
        let f = try interruptedAcceptance(in: root)
        let service = DatabaseService(rootDirectory: root)

        try service.reconcileLongFormRecovery()

        XCTAssertFalse(f.store.hasPendingRecovery, "The rows commit, then the journal retires, in one call")
        let rows = try service.fetchAllGenerations()
        XCTAssertEqual(rows.count, 4, "The prior joined output, both segments and the new joined output")
        XCTAssertEqual(rows.filter { $0.longFormRole == "joined" }.map(\.audioPath), [f.input.joined.audioPath])
        XCTAssertEqual(rows.filter { $0.longFormRole == "superseded" }.map(\.audioPath), [f.oldJoined.path])
        XCTAssertTrue(FileManager.default.fileExists(atPath: f.input.joined.audioPath), "The audio is kept")
        XCTAssertNotEqual(try Data(contentsOf: f.input.manifestURL), f.oldManifest, "The new manifest stays")
        XCTAssertNoThrow(try service.reconcileLongFormRecovery(), "Nothing is left to settle")
        XCTAssertEqual(try service.fetchAllGenerations().count, 4)
    }

    func testLongFormRecoveryWithNothingPendingMakesNoWrite() throws {
        // No database can be opened under a missing directory, so any write
        // would throw: with nothing pending the service never reaches one.
        let root = try makeRoot(creatingDirectory: false)
        let service = DatabaseService(rootDirectory: root)
        XCTAssertNoThrow(try service.reconcileLongFormRecovery())
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.path))
    }

    func testLongFormRecoveryFailsClosedOnAnUnreadableJournal() throws {
        let root = try makeRoot()
        let service = DatabaseService(rootDirectory: root)
        var standalone = row("/nonexistent/standalone.wav", at: 0)
        try service.saveGeneration(&standalone)
        let journals = root.appendingPathComponent("history-outbox/long-form", isDirectory: true)
        try FileManager.default.createDirectory(at: journals, withIntermediateDirectories: true)
        let journal = journals.appendingPathComponent(String(repeating: "0", count: 64) + ".json")
        let damaged = Data("damaged fixture journal".utf8)
        try damaged.write(to: journal)

        // The first pass throws, so the call ends there rather than retrying.
        XCTAssertThrowsError(try service.reconcileLongFormRecovery()) { error in
            XCTAssertEqual((error as? HistoryPersistenceError)?.operation, .write)
        }
        XCTAssertEqual(try Data(contentsOf: journal), damaged, "The journal stays for Retry or export")
        XCTAssertEqual(
            try service.fetchAllGenerations().map(\.audioPath),
            ["/nonexistent/standalone.wav"],
            "Unrelated History stays readable"
        )
    }

    /// A2-01: a restore or device migration moves the container, and the rows
    /// still name the old one.
    func testRowsUnderARootThatMovedAreRebasedWhenHistoryOpens() throws {
        let oldRoot = try makeRoot()
        let fileManager = FileManager.default
        let takes = oldRoot.appendingPathComponent("outputs/CustomVoice", isDirectory: true)
        try fileManager.createDirectory(at: takes, withIntermediateDirectories: true)
        let moved = takes.appendingPathComponent("take.wav")
        try Data("RIFF".utf8).write(to: moved)
        // A folder that still exists must keep its rows: a custom output folder, a diagnostics root.
        let elsewhere = try makeRoot().appendingPathComponent("outputs/kept.wav")
        try fileManager.createDirectory(at: elsewhere.deletingLastPathComponent(), withIntermediateDirectories: true)

        do {
            let service = DatabaseService(rootDirectory: oldRoot)
            // The last row sits under a root that is gone and whose audio did not come along
            // (an unmounted volume): it must not be rewritten.
            let paths = [moved.path, elsewhere.path, "/nonexistent/take.wav", "/unmounted-volume/outputs/kept.wav"]
            for (index, path) in paths.enumerated() {
                var generation = row(path, at: Double(index))
                try service.saveGeneration(&generation)
            }
        }

        let newRoot = fileManager.temporaryDirectory
            .appendingPathComponent("DatabaseService-\(UUID().uuidString)", isDirectory: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: newRoot) }
        try fileManager.moveItem(at: oldRoot, to: newRoot)

        let reopened = DatabaseService(rootDirectory: newRoot)
        let paths = Set(try reopened.fetchAllGenerations().map(\.audioPath))
        let rebased = newRoot.path + "/outputs/CustomVoice/take.wav"
        XCTAssertEqual(
            paths,
            [rebased, elsewhere.path, "/nonexistent/take.wav", "/unmounted-volume/outputs/kept.wav"]
        )
        XCTAssertTrue(fileManager.fileExists(atPath: rebased), "The rebased row reaches the audio that moved with it")

        // Opening again changes nothing.
        let again = DatabaseService(rootDirectory: newRoot)
        XCTAssertEqual(Set(try again.fetchAllGenerations().map(\.audioPath)), paths)
    }

    func testAFailedOpenStaysFailedUntilAnExplicitReopen() throws {
        // The directory does not exist yet, so SQLite cannot create the database.
        let root = try makeRoot(creatingDirectory: false)
        let service = DatabaseService(rootDirectory: root)

        XCTAssertThrowsError(try service.fetchAllGenerations()) { error in
            XCTAssertEqual((error as? HistoryPersistenceError)?.operation, .read)
        }
        var generation = row("/nonexistent/blocked.wav", at: 0)
        XCTAssertThrowsError(try service.saveGeneration(&generation)) { error in
            XCTAssertEqual((error as? HistoryPersistenceError)?.operation, .write)
        }
        XCTAssertThrowsError(try service.deleteGenerations(throughID: 1)) { error in
            XCTAssertEqual((error as? HistoryPersistenceError)?.operation, .delete)
        }

        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        XCTAssertThrowsError(try service.fetchAllGenerations(), "The failure is kept until the user retries")

        try service.reopenIfNeeded()
        XCTAssertEqual(try service.fetchAllGenerations(), [])
        try service.saveGeneration(&generation)
        XCTAssertEqual(try service.fetchAllGenerations().map(\.audioPath), ["/nonexistent/blocked.wav"])
    }
}
