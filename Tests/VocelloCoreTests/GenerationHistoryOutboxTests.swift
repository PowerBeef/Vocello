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
    private var lockedDirectories: [URL] = []

    override func tearDownWithError() throws {
        for directory in lockedDirectories {
            try? FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: directory.path)
        }
        lockedDirectories.removeAll()
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

    // MARK: - Audio that could not be removed (AUD-05)

    func testPartialClearKeepsFailedAudioForRetryAndNeverReclearsLaterTakes() async throws {
        let fixture = try makeFixture()
        let state = CommitState()
        let locked = try makeLockableAudio(in: fixture, named: "stuck.wav")
        _ = try state.commit(generation(fixture, audioPath: locked.audio.path))
        let coordinator = makeCoordinator(store: fixture.store, state: state)
        try lock(locked.directory)

        let outcome = try await coordinator.clearAll(deleteAudio: true)

        XCTAssertEqual(outcome.failedFileRemovals, 1)
        XCTAssertFalse(outcome.snapshot.clearRecoveryPending, "The clear itself finished")
        XCTAssertEqual(outcome.snapshot.pendingAudioRemovalCount, 1)
        XCTAssertTrue(outcome.snapshot.onlyAudioRemovalsPending)
        XCTAssertEqual(state.counts.rows, 0)

        // A take saved after the clear must survive every later reconcile; a
        // retained clear transaction used to resume and delete it.
        let later = try makeAudio(in: fixture, named: "later.wav")
        _ = try state.commit(generation(fixture, audioPath: later.path))
        let deletesBefore = state.counts.deletes
        let blocked = await coordinator.reconcile()
        XCTAssertEqual(state.counts.deletes, deletesBefore)
        XCTAssertEqual(state.counts.rows, 1)
        XCTAssertEqual(blocked.snapshot.pendingAudioRemovalCount, 1)
        XCTAssertTrue(FileManager.default.fileExists(atPath: locked.audio.path))

        try unlock(locked.directory)
        let retried = await coordinator.reconcile()
        XCTAssertEqual(retried.snapshot, .empty)
        XCTAssertFalse(FileManager.default.fileExists(atPath: locked.audio.path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: later.path))
        XCTAssertEqual(state.counts.rows, 1)
    }

    func testSingleDeleteAudioThatCouldNotBeRemovedIsRetriedUntilGone() async throws {
        let fixture = try makeFixture()
        let locked = try makeLockableAudio(in: fixture, named: "single.wav")
        let coordinator = makeCoordinator(store: fixture.store, state: CommitState())
        try lock(locked.directory)

        try await coordinator.retainAudioRemoval(locked.audio.path)
        XCTAssertEqual(fixture.store.scan().issueCount, 0, "The removal list is not an outbox entry")
        let blocked = await coordinator.reconcile()
        XCTAssertEqual(blocked.snapshot.pendingAudioRemovalCount, 1)
        XCTAssertTrue(blocked.snapshot.needsAttention)
        XCTAssertTrue(FileManager.default.fileExists(atPath: locked.audio.path))

        try unlock(locked.directory)
        let retried = await coordinator.reconcile()
        XCTAssertEqual(retried.snapshot, .empty)
        XCTAssertFalse(FileManager.default.fileExists(atPath: locked.audio.path))
    }

    func testRetriedRemovalNeverDeletesReferencedQueuedOrNonFileAudio() async throws {
        let fixture = try makeFixture()
        let state = CommitState()
        let referenced = try makeAudio(in: fixture, named: "referenced.wav")
        _ = try state.commit(generation(fixture, audioPath: referenced.path))
        let queued = try makeAudio(in: fixture, named: "queued.wav")
        _ = try fixture.store.enqueue(generation(fixture, audioPath: queued.path), operation: .append)
        let directory = fixture.store.rootURL.deletingLastPathComponent()
            .appendingPathComponent("not-audio.wav", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        state.setFailure(true) // keep the queued take queued through reconcile
        let coordinator = makeCoordinator(store: fixture.store, state: state)

        for path in [referenced.path, queued.path, directory.path] {
            try await coordinator.retainAudioRemoval(path)
        }
        let result = await coordinator.reconcile()

        XCTAssertTrue(FileManager.default.fileExists(atPath: referenced.path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: queued.path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: directory.path))
        XCTAssertEqual(result.snapshot.pendingAudioRemovalCount, 0)
        XCTAssertEqual(result.snapshot.pendingCount, 1)
    }

    private func makeAudio(
        in fixture: (store: GenerationHistoryOutboxStore, generation: Generation, audioURL: URL),
        named name: String
    ) throws -> URL {
        let url = fixture.audioURL.deletingLastPathComponent().appendingPathComponent(name)
        try Data([0x52, 0x49, 0x46, 0x46]).write(to: url)
        return url
    }

    private func makeLockableAudio(
        in fixture: (store: GenerationHistoryOutboxStore, generation: Generation, audioURL: URL),
        named name: String
    ) throws -> (directory: URL, audio: URL) {
        let directory = fixture.audioURL.deletingLastPathComponent()
            .appendingPathComponent("locked-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let audio = directory.appendingPathComponent(name)
        try Data([0x52, 0x49, 0x46, 0x46]).write(to: audio)
        return (directory, audio)
    }

    /// A read-only directory refuses the unlink, as a real removal failure would.
    private func lock(_ directory: URL) throws {
        try FileManager.default.setAttributes([.posixPermissions: 0o555], ofItemAtPath: directory.path)
        lockedDirectories.append(directory)
        let probe = directory.appendingPathComponent("probe")
        if FileManager.default.createFile(atPath: probe.path, contents: Data()) {
            try? FileManager.default.removeItem(at: probe)
            throw XCTSkip("File permissions are not enforced for this user")
        }
    }

    private func unlock(_ directory: URL) throws {
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: directory.path)
    }

    private func generation(
        _ fixture: (store: GenerationHistoryOutboxStore, generation: Generation, audioURL: URL),
        audioPath: String
    ) -> Generation {
        var copy = fixture.generation
        copy.audioPath = audioPath
        return copy
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
            deleteAllGenerations: { try state.deleteAll() },
            referencedAudioPaths: { paths in
                Set(state.rows().map(\.audioPath)).intersection(paths)
            }
        )
    }

    private func encode<T: Encodable>(_ value: T) throws -> Data {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .millisecondsSince1970
        encoder.outputFormatting = [.sortedKeys]
        return try encoder.encode(value)
    }
}
