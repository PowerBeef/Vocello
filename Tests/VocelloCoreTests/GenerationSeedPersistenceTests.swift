import Foundation
import GRDB
import XCTest

/// DP-15: the History schema records each take's effective sampling seed so
/// "pin this take's seed" can reproduce it later. Pins the v6 migration and
/// the UInt64 ↔ Int64 bit-pattern round trip, including the top-bit range a
/// naive signed store would corrupt or reject.
final class GenerationSeedPersistenceTests: XCTestCase {
    private func makeMigratedQueue() throws -> DatabaseQueue {
        let queue = try DatabaseQueue()
        try GenerationMigrations.makeMigrator().migrate(queue)
        return queue
    }

    func testMigratorAddsNullableSeedColumn() throws {
        let queue = try makeMigratedQueue()
        try queue.read { db in
            let columns = try db.columns(in: "generations")
            guard let seedColumn = columns.first(where: { $0.name == "seed" }) else {
                return XCTFail("v6 must add the seed column")
            }
            XCTAssertFalse(seedColumn.isNotNull, "pre-v6 rows keep NULL — their seeds were never recorded")
        }
    }

    func testSeedRoundTripsIncludingTopBitRange() throws {
        let queue = try makeMigratedQueue()
        // 0x8000… exercises the UInt64 half that only survives via the
        // Int64 bit-pattern store; UInt64.max is the boundary.
        for seedValue: UInt64 in [0, 1, 20_260_804, UInt64(1) << 63, UInt64.max] {
            var generation = Generation(
                text: "seed round trip",
                mode: "custom",
                modelTier: "pro",
                voice: "aiden",
                emotion: nil,
                speed: nil,
                audioPath: "/tmp/seed-\(seedValue).wav",
                duration: 1.0,
                createdAt: Date(),
                seed: Int64(bitPattern: seedValue)
            )
            try queue.write { db in
                try generation.insert(db)
            }
            let fetched = try queue.read { db in
                try Generation.fetchOne(db, key: generation.id)
            }
            XCTAssertEqual(fetched?.samplingSeed, seedValue)
        }
    }

    func testRowWithoutSeedReadsAsNil() throws {
        let queue = try makeMigratedQueue()
        var generation = Generation(
            text: "legacy row",
            mode: "design",
            modelTier: "pro",
            voice: nil,
            emotion: nil,
            speed: nil,
            audioPath: "/tmp/legacy.wav",
            duration: nil,
            createdAt: Date()
        )
        try queue.write { db in
            try generation.insert(db)
        }
        let fetched = try queue.read { db in
            try Generation.fetchOne(db, key: generation.id)
        }
        XCTAssertNotNil(fetched)
        XCTAssertNil(fetched?.seed)
        XCTAssertNil(fetched?.samplingSeed)
    }
}
