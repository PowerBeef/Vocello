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

        return migrator
    }
}
