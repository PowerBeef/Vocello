import Foundation
import XCTest

final class GenerationHistoryOutboxTests: XCTestCase {
    private final class CommitState: @unchecked Sendable {
        private let lock = NSLock()
        private var shouldFail = false
        private var rowsByPath: [String: Generation] = [:]
        private var commitAttempts = 0
        private var deleteAttempts = 0

        func setFailure(_ value: Bool) {
            lock.withLock { shouldFail = value }
        }

        func commit(_ generation: Generation) throws -> Generation {
            try lock.withLock {
                commitAttempts += 1
                if shouldFail { throw StubError() }
                if let existing = rowsByPath[generation.audioPath] { return existing }
                var saved = generation
                saved.id = Int64(rowsByPath.count + 1)
                rowsByPath[generation.audioPath] = saved
                return saved
            }
        }

        func rows() -> [Generation] {
            lock.withLock { Array(rowsByPath.values) }
        }

        func deleteAll() throws {
            try lock.withLock {
                deleteAttempts += 1
                if shouldFail { throw StubError() }
                rowsByPath.removeAll()
            }
        }

        var counts: (commits: Int, rows: Int, deletes: Int) {
            lock.withLock { (commitAttempts, rowsByPath.count, deleteAttempts) }
        }
    }

    private struct StubError: Error {}

    private var temporaryRoots: [URL] = []

    override func tearDownWithError() throws {
        for root in temporaryRoots {
            try? FileManager.default.removeItem(at: root)
        }
        temporaryRoots.removeAll()
    }

    func testCommitClearsDurableEntryOnlyAfterDatabaseSuccess() async throws {
        let fixture = try makeFixture()
        let state = CommitState()
        let coordinator = makeCoordinator(store: fixture.store, state: state)
        let entry = try fixture.store.enqueue(fixture.generation, operation: .append)

        XCTAssertEqual(fixture.store.scan().entries.map(\.id), [entry.id])
        let saved = try await coordinator.commit(entry)

        XCTAssertEqual(saved.id, 1)
        XCTAssertTrue(fixture.store.scan().entries.isEmpty)
        XCTAssertEqual(state.counts.rows, 1)
    }

    func testDatabaseFailureRetainsEntryAndLaterReconcileCommitsIt() async throws {
        let fixture = try makeFixture()
        let state = CommitState()
        state.setFailure(true)
        let coordinator = makeCoordinator(store: fixture.store, state: state)
        let entry = try fixture.store.enqueue(fixture.generation, operation: .append)

        do {
            _ = try await coordinator.commit(entry)
            XCTFail("Expected a deferred database failure")
        } catch {
            XCTAssertEqual(error as? GenerationHistoryOutboxError, .databaseUnavailable)
        }
        XCTAssertEqual(fixture.store.scan().entries.map(\.id), [entry.id])

        state.setFailure(false)
        let result = await coordinator.reconcile()
        XCTAssertEqual(result.committed.count, 1)
        XCTAssertEqual(result.snapshot, .empty)
        XCTAssertTrue(fixture.store.scan().entries.isEmpty)
    }

    func testReplayUsesAudioIdentityWithoutCreatingDuplicateRows() async throws {
        let fixture = try makeFixture()
        let state = CommitState()
        let coordinator = makeCoordinator(store: fixture.store, state: state)
        let entry = try fixture.store.enqueue(fixture.generation, operation: .append)

        let first = try await coordinator.commit(entry)
        let replay = try await coordinator.commit(entry)

        XCTAssertEqual(first.id, replay.id)
        XCTAssertEqual(state.counts.commits, 2)
        XCTAssertEqual(state.counts.rows, 1)
    }

    func testEnqueueRejectsMissingPublishedAudio() throws {
        let fixture = try makeFixture(createAudio: false)
        XCTAssertThrowsError(try fixture.store.enqueue(fixture.generation, operation: .append)) { error in
            XCTAssertEqual(error as? GenerationHistoryOutboxError, .missingAudio)
        }
        XCTAssertTrue(fixture.store.scan().entries.isEmpty)
    }

    func testCorruptEntryIsRetainedAndCountedWithoutExposingContent() throws {
        let fixture = try makeFixture()
        let corruptURL = fixture.store.rootURL.appendingPathComponent("\(UUID().uuidString.lowercased()).json")
        try Data("not-json".utf8).write(to: corruptURL)

        let scan = fixture.store.scan()
        XCTAssertTrue(scan.entries.isEmpty)
        XCTAssertEqual(scan.issueCount, 1)
        XCTAssertTrue(FileManager.default.fileExists(atPath: corruptURL.path))
    }

    func testInterruptedEntryWriteIsPromotedOnScan() throws {
        let fixture = try makeFixture()
        let entry = GenerationHistoryOutboxEntry(
            operation: .append,
            generation: fixture.generation,
            createdAt: Date(timeIntervalSince1970: 1_700_000_000)
        )
        let writingURL = fixture.store.rootURL
            .appendingPathComponent("\(entry.id.uuidString.lowercased()).writing")
        try encode(entry).write(to: writingURL)

        let scan = fixture.store.scan()

        XCTAssertEqual(scan.entries.map(\.id), [entry.id])
        XCTAssertEqual(scan.issueCount, 0)
        XCTAssertFalse(FileManager.default.fileExists(atPath: writingURL.path))
        XCTAssertTrue(
            FileManager.default.fileExists(
                atPath: fixture.store.rootURL
                    .appendingPathComponent("\(entry.id.uuidString.lowercased()).json").path
            )
        )
    }

    func testDatabaseFirstClearPreservesRowsAudioAndOutboxWhenDatabaseFails() async throws {
        let fixture = try makeFixture()
        let state = CommitState()
        _ = try state.commit(fixture.generation)
        state.setFailure(true)
        let coordinator = makeCoordinator(store: fixture.store, state: state)
        let entry = try fixture.store.enqueue(fixture.generation, operation: .append)

        do {
            _ = try await coordinator.clearAll(deleteAudio: true)
            XCTFail("Expected clear to fail closed")
        } catch {
            XCTAssertEqual(error as? GenerationHistoryOutboxError, .clearUnavailable)
        }

        XCTAssertTrue(FileManager.default.fileExists(atPath: fixture.audioURL.path))
        XCTAssertEqual(fixture.store.scan().entries.map(\.id), [entry.id])
        let snapshot = await coordinator.snapshot()
        XCTAssertTrue(snapshot.clearRecoveryPending)
        XCTAssertEqual(state.counts.rows, 1)
    }

    func testStartupReconcileResumesClearBeforeAnyPendingAppend() async throws {
        let fixture = try makeFixture()
        let state = CommitState()
        _ = try state.commit(fixture.generation)
        state.setFailure(true)
        let coordinator = makeCoordinator(store: fixture.store, state: state)
        _ = try fixture.store.enqueue(fixture.generation, operation: .append)
        _ = try? await coordinator.clearAll(deleteAudio: true)
        let commitsBeforeRecovery = state.counts.commits

        state.setFailure(false)
        let result = await coordinator.reconcile()

        XCTAssertTrue(result.committed.isEmpty)
        XCTAssertEqual(state.counts.commits, commitsBeforeRecovery)
        XCTAssertEqual(state.counts.rows, 0)
        XCTAssertFalse(FileManager.default.fileExists(atPath: fixture.audioURL.path))
        XCTAssertEqual(result.snapshot, .empty)
    }

    func testInterruptedClearMarkerIsRecoveredAndKeepAudioCompletes() async throws {
        let fixture = try makeFixture()
        let state = CommitState()
        _ = try state.commit(fixture.generation)
        let coordinator = makeCoordinator(store: fixture.store, state: state)
        let transaction = GenerationHistoryClearTransaction(
            deleteAudio: false,
            audioPaths: [fixture.audioURL.path],
            pendingEntryIDs: []
        )
        let writingURL = fixture.store.rootURL.appendingPathComponent("clear-transaction.writing")
        try encode(transaction).write(to: writingURL)

        let result = await coordinator.reconcile()

        XCTAssertTrue(result.committed.isEmpty)
        XCTAssertEqual(result.snapshot, .empty)
        XCTAssertEqual(state.counts.rows, 0)
        XCTAssertTrue(FileManager.default.fileExists(atPath: fixture.audioURL.path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: writingURL.path))
    }

    func testCorruptClearMarkerFailsClosedAndSurfacesRecoveryIssue() async throws {
        let fixture = try makeFixture()
        try Data("invalid".utf8).write(
            to: fixture.store.rootURL.appendingPathComponent("clear-transaction.writing")
        )
        let coordinator = makeCoordinator(store: fixture.store, state: CommitState())

        let result = await coordinator.reconcile()

        XCTAssertTrue(result.committed.isEmpty)
        XCTAssertEqual(result.snapshot.issueCount, 1)
        XCTAssertTrue(result.snapshot.clearRecoveryPending)
    }

    private func makeFixture(createAudio: Bool = true) throws -> (
        store: GenerationHistoryOutboxStore,
        generation: Generation,
        audioURL: URL
    ) {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("GenerationHistoryOutboxTests-\(UUID().uuidString)", isDirectory: true)
        temporaryRoots.append(root)
        let storeRoot = root.appendingPathComponent("outbox", isDirectory: true)
        try FileManager.default.createDirectory(at: storeRoot, withIntermediateDirectories: true)
        let audioURL = root.appendingPathComponent("take.wav")
        if createAudio {
            try Data([0x52, 0x49, 0x46, 0x46]).write(to: audioURL)
        }
        let generation = Generation(
            id: nil,
            text: "Local test sentence",
            mode: "custom",
            modelTier: "lite",
            voice: "Aiden",
            emotion: "Neutral",
            speed: 1,
            audioPath: audioURL.path,
            duration: 1,
            createdAt: Date(timeIntervalSince1970: 1_700_000_000),
            longFormProjectID: nil,
            longFormRole: nil,
            seed: 42
        )
        return (GenerationHistoryOutboxStore(rootURL: storeRoot), generation, audioURL)
    }

    private func makeCoordinator(
        store: GenerationHistoryOutboxStore,
        state: CommitState
    ) -> GenerationHistoryRecoveryCoordinator {
        GenerationHistoryRecoveryCoordinator(
            store: store,
            commitGeneration: { _, generation in try state.commit(generation) },
            fetchAllGenerations: { state.rows() },
            deleteAllGenerations: { try state.deleteAll() }
        )
    }

    private func encode<T: Encodable>(_ value: T) throws -> Data {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .millisecondsSince1970
        encoder.outputFormatting = [.sortedKeys]
        return try encoder.encode(value)
    }
}
