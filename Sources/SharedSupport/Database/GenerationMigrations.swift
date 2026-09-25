import Foundation
import GRDB

enum GenerationMigrations {
    static func makeMigrator() -> DatabaseMigrator {
        var migrator = DatabaseMigrator()

        migrator.registerMigration("v1_create_generations") { db in
            try db.create(table: "generations") { t in
                t.autoIncrementedPrimaryKey("id")
                t.column("text", .text).notNull()
                t.column("mode", .text).notNull()
                t.column("modelTier", .text).notNull()
                t.column("voice", .text)
                t.column("emotion", .text)
                t.column("speed", .double)
                t.column("audioPath", .text).notNull()
                t.column("duration", .double)
                t.column("createdAt", .datetime).notNull().defaults(sql: "CURRENT_TIMESTAMP")
            }
        }

        migrator.registerMigration("v2_add_sortOrder") { db in
            try db.alter(table: "generations") { t in
                t.add(column: "sortOrder", .integer).defaults(to: 0)
            }
            let rows = try Row.fetchAll(db, sql: "SELECT id FROM generations ORDER BY createdAt DESC")
            for (index, row) in rows.enumerated() {
                let id: Int64 = row["id"]
                try db.execute(sql: "UPDATE generations SET sortOrder = ? WHERE id = ?", arguments: [index, id])
            }
        }

        migrator.registerMigration("v3_drop_sortOrder") { db in
            try db.create(table: "generations_v3") { t in
                t.autoIncrementedPrimaryKey("id")
                t.column("text", .text).notNull()
                t.column("mode", .text).notNull()
                t.column("modelTier", .text).notNull()
                t.column("voice", .text)
                t.column("emotion", .text)
                t.column("speed", .double)
                t.column("audioPath", .text).notNull()
                t.column("duration", .double)
                t.column("createdAt", .datetime).notNull().defaults(sql: "CURRENT_TIMESTAMP")
            }

            try db.execute(sql: """
                INSERT INTO generations_v3 (id, text, mode, modelTier, voice, emotion, speed, audioPath, duration, createdAt)
                SELECT id, text, mode, modelTier, voice, emotion, speed, audioPath, duration, createdAt
                FROM generations
                ORDER BY createdAt DESC
                """)

            try db.drop(table: "generations")
            try db.rename(table: "generations_v3", to: "generations")
        }

        migrator.registerMigration("v4_index_generations_createdAt") { db in
            try db.create(
                index: "idx_generations_createdAt",
                on: "generations",
                columns: ["createdAt"]
            )
        }

        migrator.registerMigration("v5_add_long_form_project") { db in
            try db.alter(table: "generations") { t in
                // Nullable additive columns: rows outside a long-form project
                // keep NULL and all existing readers are unaffected.
                t.add(column: "longFormProjectID", .text)
                t.add(column: "longFormRole", .text)
            }
            try db.create(
                index: "idx_generations_longFormProjectID",
                on: "generations",
                columns: ["longFormProjectID"]
            )
        }

        migrator.registerMigration("v6_add_seed") { db in
            try db.alter(table: "generations") { t in
                // Nullable additive column: the engine's effective sampling
                // seed (UInt64 stored as its Int64 bit pattern). Rows from
                // before this migration keep NULL — their seeds were never
                // recorded and cannot be recovered (DP-15).
                t.add(column: "seed", .integer)
            }
        }

        migrator.registerMigration("v7_index_generations_audioPath") { db in
            // `audioPath` is the idempotency key: every save first asks whether
            // a row with this path already exists, which is what makes a
            // retried write safe. Without an index that question was a full
            // table scan, and it runs on the path a generation completes on --
            // the one place a stall is most visible -- against a table that
            // only ever grows. Not unique: two rows may legitimately share a
            // path after a long-form join supersedes an earlier take.
            try db.create(
                index: "idx_generations_audioPath",
                on: "generations",
                columns: ["audioPath"]
            )
        }

        return migrator
    }
}

/// Clear-all's row deletion (AUD-05). The `generations` id is AUTOINCREMENT
/// from v1 on (v3 rebuilds the table with it and SQLite keeps the sequence
/// across the rename), so ids are never reused: a take saved after a clear
/// captured its bound has a larger id and survives the clear.
enum GenerationHistoryBoundedDelete {
    /// Deletes the rows whose id is at most `maxRowID` and returns their
    /// audio paths. Runs inside the caller's write.
    static func deleteRows(throughID maxRowID: Int64, in db: Database) throws -> [String] {
        let bounded = Generation.filter(Generation.Columns.id <= maxRowID)
        let paths = try bounded.select(Generation.Columns.audioPath, as: String.self).fetchAll(db)
        _ = try bounded.deleteAll(db)
        return paths
    }
}
