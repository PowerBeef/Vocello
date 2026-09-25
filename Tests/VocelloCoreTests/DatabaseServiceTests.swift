import Foundation
import GRDB
import XCTest

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
