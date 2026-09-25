import Foundation
import GRDB
import QwenVoiceCore

/// Manages SQLite database for generation history.
///
/// Intentionally not `@MainActor`-isolated. `DatabaseQueue` is GRDB's
/// thread-safe queue primitive; all read/write operations route through
/// it. A lock-protected coordinator owns the queue and allows only an explicit
/// UI Retry to replace a failed initial open/migration with a fully opened
/// queue. Non-isolation lets `GenerationPersistence` schedule writes
/// via `Task.detached` so they don't block the UI's main run loop —
/// previously the synchronous save on `@MainActor` introduced a 5-30ms
/// hitch right after every generation completed.
///
/// This is the iOS copy (mirrors `Sources/Services/DatabaseService.swift`); it
/// resolves its database file under the iOS App Group container via `AppPaths`,
/// which is itself platform-specific.
final class DatabaseService: @unchecked Sendable {
    /// Process-wide singleton. GRDB serializes queue access and the coordinator
    /// serializes the explicit reopen transition.
    static let shared = DatabaseService()

    private let store: RecoverableStoreCoordinator<DatabaseQueue, HistoryPersistenceError>
    private let longFormAcceptance = LongFormHistoryAcceptanceStore(
        rootURL: AppPaths.appSupportDir.appendingPathComponent("history-outbox/long-form", isDirectory: true)
    )

    private init() {
        let dbPath = AppPaths.appSupportDir.appendingPathComponent("history.sqlite").path
        self.store = RecoverableStoreCoordinator(
            openStore: { try Self.openQueue(at: dbPath) },
            classify: { HistoryPersistenceError.classify($0, operation: .initialize) }
        )
    }

    static func makeMigrator() -> DatabaseMigrator {
        GenerationMigrations.makeMigrator()
    }

    private static func openQueue(at path: String) throws -> DatabaseQueue {
        // IOS-11: on iPhone the database lives in the App Group container, and
        // iOS terminates an app that is suspended while holding a lock on a
        // shared file (0xDEAD10CC). The app suspends the queue just before it can
        // be suspended itself (`suspendForAppSuspension()`); a write that meets
        // the suspension rolls back with a transient `.locked` failure, and a
        // short-form take stays in the outbox until the reconcile after resume
        // commits it. macOS never posts the notifications.
        var configuration = Configuration()
        configuration.observesSuspensionNotifications = true
        let queue: DatabaseQueue
        do {
            queue = try DatabaseQueue(path: path, configuration: configuration)
        } catch {
            throw HistoryPersistenceError.classify(error, operation: .initialize)
        }
        do {
            try makeMigrator().migrate(queue)
            return queue
        } catch {
            throw HistoryPersistenceError.classify(error, operation: .migrate)
        }
    }

    func reopenIfNeeded() throws {
        _ = try store.reopenIfNeeded()
    }

    /// IOS-11: History stops taking SQLite locks and interrupts a running
    /// statement. Posted only when the app is about to be suspended.
    static func suspendForAppSuspension() {
        NotificationCenter.default.post(name: Database.suspendNotification, object: nil)
    }

    /// The app is active again; History may take locks again.
    static func resumeAfterAppSuspension() {
        NotificationCenter.default.post(name: Database.resumeNotification, object: nil)
    }

    // MARK: - CRUD

    func acceptLongFormProject(_ input: LongFormHistoryAcceptance) async throws -> Generation {
        try await longFormAcceptance.commit(input, using: requireQueue(for: .write))
    }

    /// Synchronous variant. Kept for legacy / migration call sites that
    /// can't be moved to async (e.g. from `@MainActor` synchronous
    /// contexts during init). New off-main callers should prefer
    /// `saveGenerationAsync(_:)` which uses GRDB's async write.
    func saveGeneration(_ generation: inout Generation) throws {
        let dbQueue = try requireQueue(for: .write)
        do {
            try dbQueue.write { db in
                try longFormAcceptance.reconcile(in: db)
                try generation.save(db)
            }
        } catch {
            throw HistoryPersistenceError.classify(error, operation: .write)
        }
    }

    /// Async variant — call from a detached Task to keep the SQLite
    /// write off the main run loop. GRDB's `DatabaseQueue.write` has an
    /// async overload that bridges to its internal write queue;
    /// returning the persisted Generation lets callers obtain the
    /// auto-assigned `id` without an `inout` parameter (unsendable in
    /// async contexts).
    func saveGenerationAsync(_ generation: Generation) async throws -> Generation {
        try await saveGenerationIfMissingAsync(generation)
    }

    func saveGenerationIfMissingAsync(_ generation: Generation) async throws -> Generation {
        let dbQueue = try requireQueue(for: .write)
        do {
            return try await dbQueue.write { db in
                try self.longFormAcceptance.reconcile(in: db)
                if let existing = try Generation
                    .filter(Generation.Columns.audioPath == generation.audioPath)
                    .fetchOne(db) {
                    return existing
                }
                var copy = generation
                try copy.save(db)
                return copy
            }
        } catch {
            throw HistoryPersistenceError.classify(error, operation: .write)
        }
    }

    /// Retains older joined outputs as individually deletable History rows, then
    /// saves the new accepted output — one current joined record per project.
    func replaceLongFormJoinedGenerationAsync(_ generation: Generation) async throws -> Generation {
        try await replaceLongFormJoinedGenerationIfMissingAsync(generation)
    }

    func replaceLongFormJoinedGenerationIfMissingAsync(_ generation: Generation) async throws -> Generation {
        let dbQueue = try requireQueue(for: .write)
        do {
            return try await dbQueue.write { db in
                try self.longFormAcceptance.reconcile(in: db)
                if let existing = try Generation
                    .filter(Generation.Columns.audioPath == generation.audioPath)
                    .fetchOne(db) {
                    return existing
                }
                if let projectID = generation.longFormProjectID {
                    try db.execute(
                        sql: "UPDATE generations SET longFormRole = 'superseded' WHERE longFormProjectID = ? AND longFormRole = 'joined'",
                        arguments: [projectID]
                    )
                }
                var copy = generation
                try copy.save(db)
                return copy
            }
        } catch {
            throw HistoryPersistenceError.classify(error, operation: .write)
        }
    }

    /// Every row, newest first. Screens page instead (`fetchGenerationPage`);
    /// clear-all reads through `fetchAllGenerationsForClear()`.
    func fetchAllGenerations() throws -> [Generation] {
        let dbQueue = try requireQueue(for: .read)
        do {
            // AUD-05: the writer and the journal work only while a long-form
            // journal is pending; otherwise a read transaction suffices (see
            // `LongFormHistoryAcceptanceStore.reconcile`).
            guard longFormAcceptance.hasPendingRecovery else {
                return try dbQueue.read { db in
                    try Generation.order(Generation.Columns.createdAt.desc).fetchAll(db)
                }
            }
            return try dbQueue.write { db in
                return try longFormAcceptance.readableHistory(in: db)
            }
        } catch {
            throw HistoryPersistenceError.classify(error, operation: .read)
        }
    }

    /// Every row for clear-all, read on the writer after long-form
    /// reconciliation. While a journal needs recovery it throws instead of
    /// withholding project rows, so a clear's bound never covers a row it did
    /// not capture (AUD-05).
    func fetchAllGenerationsForClear() throws -> [Generation] {
        let dbQueue = try requireQueue(for: .read)
        do {
            return try dbQueue.write { db in
                try longFormAcceptance.reconcile(in: db)
                return try Generation.order(Generation.Columns.createdAt.desc).fetchAll(db)
            }
        } catch {
            throw HistoryPersistenceError.classify(error, operation: .read)
        }
    }

    /// One bounded page of History (AUD-05); filter and search reach every row.
    func fetchGenerationPage(_ request: GenerationHistoryPageRequest) throws -> GenerationHistoryPage {
        let dbQueue = try requireQueue(for: .read)
        do {
            guard longFormAcceptance.hasPendingRecovery else {
                return try dbQueue.read { db in
                    try GenerationHistoryPageQuery.fetch(request, includesLongFormProjects: true, in: db)
                }
            }
            return try dbQueue.write { db in
                let reconciled = try longFormAcceptance.reconcileBeforeReading(in: db)
                return try GenerationHistoryPageQuery.fetch(
                    request,
                    includesLongFormProjects: reconciled,
                    in: db
                )
            }
        } catch {
            throw HistoryPersistenceError.classify(error, operation: .read)
        }
    }

    /// The subset of `audioPaths` that History rows still reference, so a
    /// retried audio removal never deletes audio a row points at.
    func referencedAudioPaths(among audioPaths: [String]) throws -> Set<String> {
        guard !audioPaths.isEmpty else { return [] }
        let dbQueue = try requireQueue(for: .read)
        do {
            return try dbQueue.read { db in
                var referenced: Set<String> = []
                var start = audioPaths.startIndex
                while start < audioPaths.endIndex {
                    let end = audioPaths.index(start, offsetBy: 500, limitedBy: audioPaths.endIndex) ?? audioPaths.endIndex
                    let chunk = Array(audioPaths[start..<end])
                    let found = try String.fetchSet(
                        db,
                        sql: "SELECT audioPath FROM generations WHERE audioPath IN (\(databaseQuestionMarks(count: chunk.count)))",
                        arguments: StatementArguments(chunk)
                    )
                    referenced.formUnion(found)
                    start = end
                }
                return referenced
            }
        } catch {
            throw HistoryPersistenceError.classify(error, operation: .read)
        }
    }

    func deleteGeneration(id: Int64) throws {
        let dbQueue = try requireQueue(for: .delete)
        do {
            try dbQueue.write { db in
                try longFormAcceptance.reconcile(in: db)
                _ = try Generation.deleteOne(db, id: id)
            }
        } catch {
            throw HistoryPersistenceError.classify(error, operation: .delete)
        }
    }

    /// Deletes the rows whose id is at most `maxRowID` and returns their audio
    /// paths, in one write (`GenerationHistoryBoundedDelete`, AUD-05).
    func deleteGenerations(throughID maxRowID: Int64) throws -> [String] {
        let dbQueue = try requireQueue(for: .delete)
        do {
            return try dbQueue.write { db in
                try longFormAcceptance.reconcile(in: db)
                return try GenerationHistoryBoundedDelete.deleteRows(throughID: maxRowID, in: db)
            }
        } catch {
            throw HistoryPersistenceError.classify(error, operation: .delete)
        }
    }

    private func requireQueue(
        for operation: HistoryPersistenceOperation
    ) throws -> DatabaseQueue {
        do {
            return try store.requireStore()
        } catch {
            throw HistoryPersistenceError.classify(error, operation: operation)
        }
    }
}
