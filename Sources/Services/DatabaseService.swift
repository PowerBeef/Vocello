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
final class DatabaseService: @unchecked Sendable {
    /// Process-wide singleton. The class is explicitly Sendable and all
    /// database access remains serialized by `DatabaseQueue`.
    static let shared = DatabaseService()

    private let store: RecoverableStoreCoordinator<DatabaseQueue, HistoryPersistenceError>
    private let longFormAcceptance = LongFormHistoryAcceptanceStore(
        rootURL: AppPaths.appSupportDir.appendingPathComponent("history-outbox/long-form", isDirectory: true)
    )

    private init() {
        let dbPath = QwenVoiceApp.appSupportDir.appendingPathComponent("history.sqlite").path
        self.store = RecoverableStoreCoordinator(
            openStore: { try Self.openQueue(at: dbPath) },
            classify: { HistoryPersistenceError.classify($0, operation: .initialize) }
        )
    }

    static func makeMigrator() -> DatabaseMigrator {
        GenerationMigrations.makeMigrator()
    }

    private static func openQueue(at path: String) throws -> DatabaseQueue {
        let queue: DatabaseQueue
        do {
            queue = try DatabaseQueue(path: path)
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

    /// Explicit recovery boundary used by the visible History reload/retry.
    /// Normal CRUD remains fail-closed after an initialization failure.
    func reopenIfNeeded() throws {
        _ = try store.reopenIfNeeded()
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

    /// Idempotent outbox commit. Audio publication owns a stable final path,
    /// so replay after a database commit but before sidecar removal returns
    /// the existing row instead of inserting a duplicate.
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

    /// Deletes any existing joined-output row for the generation's long-form
    /// project, then saves the new one — one joined record per project.
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
                        sql: "DELETE FROM generations WHERE longFormProjectID = ? AND longFormRole = 'joined'",
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

    func fetchAllGenerations() throws -> [Generation] {
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

    func deleteAllGenerations() throws {
        let dbQueue = try requireQueue(for: .delete)
        do {
            try dbQueue.write { db in
                try longFormAcceptance.reconcile(in: db)
                _ = try Generation.deleteAll(db)
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
