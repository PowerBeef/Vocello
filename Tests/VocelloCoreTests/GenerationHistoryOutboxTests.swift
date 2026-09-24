import Foundation
import GRDB
import XCTest

final class GenerationHistoryOutboxTests: XCTestCase {
    private final class CommitState: @unchecked Sendable {
        private let lock = NSLock()
        private var shouldFail = false
        private var rowsByPath: [String: Generation] = [:]
        private var commitAttempts = 0
        private var deleteAttempts = 0
        /// Ids auto-increment and are never reused, like the History table's.
        private var nextID: Int64 = 0

        func setFailure(_ value: Bool) {
            lock.withLock { shouldFail = value }
        }

        func commit(_ generation: Generation) throws -> Generation {
            try lock.withLock {
                commitAttempts += 1
                if shouldFail { throw StubError() }
                if let existing = rowsByPath[generation.audioPath] { return existing }
                var saved = generation
                nextID += 1
                saved.id = nextID
                rowsByPath[generation.audioPath] = saved
                return saved
            }
        }

        func rows() -> [Generation] {
            lock.withLock { Array(rowsByPath.values) }
        }

        func delete(throughID maxRowID: Int64) throws -> [String] {
            try lock.withLock {
                deleteAttempts += 1
                if shouldFail { throw StubError() }
                let doomed = rowsByPath.values.filter { ($0.id ?? .max) <= maxRowID }
                for row in doomed { rowsByPath[row.audioPath] = nil }
                return doomed.map(\.audioPath)
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
            pendingEntryIDs: [],
            maxRowID: 1
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

    /// An unreadable removal list used to fail the clear after its rows were
    /// gone, so every later reconcile resumed the clear and deleted the takes
    /// saved since. The list is now set aside, counted, and kept.
    func testUnreadableRemovalListIsSetAsideAndNeverMakesAClearDeleteLaterTakes() async throws {
        let fixture = try makeFixture()
        let state = CommitState()
        _ = try state.commit(fixture.generation)
        let coordinator = makeCoordinator(store: fixture.store, state: state)
        let removalList = fixture.store.rootURL.appendingPathComponent("audio-removals.json")
        try Data("not-json".utf8).write(to: removalList)

        let outcome = try await coordinator.clearAll(deleteAudio: true)

        XCTAssertEqual(outcome.failedFileRemovals, 0)
        XCTAssertFalse(outcome.snapshot.clearRecoveryPending, "The clear finished")
        XCTAssertEqual(outcome.snapshot.issueCount, 1, "The unreadable list is reported")
        XCTAssertFalse(FileManager.default.fileExists(atPath: fixture.audioURL.path))
        let setAside = try FileManager.default.contentsOfDirectory(atPath: fixture.store.rootURL.path)
            .filter { $0.hasSuffix(".unreadable") }
        XCTAssertEqual(setAside.count, 1, "Its content is kept, not deleted")
        XCTAssertEqual(fixture.store.scan().issueCount, 0, "A set-aside list is not an outbox entry")

        let later = try makeAudio(in: fixture, named: "later.wav")
        _ = try state.commit(generation(fixture, audioPath: later.path))
        let deletesBefore = state.counts.deletes
        for _ in 0..<2 {
            let result = await coordinator.reconcile()
            XCTAssertFalse(result.snapshot.clearRecoveryPending)
        }
        XCTAssertEqual(state.counts.deletes, deletesBefore)
        XCTAssertEqual(state.counts.rows, 1)
        XCTAssertTrue(FileManager.default.fileExists(atPath: later.path))
    }

    /// A clear transaction resumed after its rows were deleted never deletes
    /// rows again; it only finishes the hand-off and retires.
    func testClearResumedPastRowDeletionKeepsTakesSavedSince() async throws {
        let fixture = try makeFixture()
        let state = CommitState()
        let later = try makeAudio(in: fixture, named: "later.wav")
        _ = try state.commit(generation(fixture, audioPath: later.path))
        let coordinator = makeCoordinator(store: fixture.store, state: state)
        let transaction = GenerationHistoryClearTransaction(
            deleteAudio: true,
            audioPaths: [fixture.audioURL.path],
            pendingEntryIDs: [],
            maxRowID: 0
        ).markingRowsDeleted()
        try encode(transaction).write(to: fixture.store.rootURL.appendingPathComponent("clear-transaction.json"))

        let result = await coordinator.reconcile()

        XCTAssertEqual(state.counts.deletes, 0)
        XCTAssertEqual(state.counts.rows, 1)
        XCTAssertEqual(result.snapshot, .empty)
        XCTAssertFalse(FileManager.default.fileExists(atPath: fixture.audioURL.path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: later.path))
    }

    /// A transaction written before the phase existed still deletes its rows.
    func testClearTransactionWithoutAPhaseStillDeletesItsRows() async throws {
        let fixture = try makeFixture()
        let state = CommitState()
        _ = try state.commit(fixture.generation)
        let coordinator = makeCoordinator(store: fixture.store, state: state)
        let transaction = GenerationHistoryClearTransaction(
            deleteAudio: false,
            audioPaths: [fixture.audioURL.path],
            pendingEntryIDs: [],
            maxRowID: 1
        )
        var legacy = try XCTUnwrap(
            JSONSerialization.jsonObject(with: encode(transaction)) as? [String: Any]
        )
        XCTAssertNotNil(legacy.removeValue(forKey: "rowsDeleted"))
        try JSONSerialization.data(withJSONObject: legacy)
            .write(to: fixture.store.rootURL.appendingPathComponent("clear-transaction.json"))

        let result = await coordinator.reconcile()

        XCTAssertEqual(state.counts.deletes, 1)
        XCTAssertEqual(state.counts.rows, 0)
        XCTAssertEqual(result.snapshot, .empty)
        XCTAssertTrue(FileManager.default.fileExists(atPath: fixture.audioURL.path))
    }

    /// A path retained while a retry pass awaits the database must survive
    /// that pass: the pass removes only what it resolved.
    func testPathRetainedDuringARetryPassStaysListed() async throws {
        let fixture = try makeFixture()
        let (entered, enteredContinuation) = AsyncStream<Void>.makeStream()
        let (release, releaseContinuation) = AsyncStream<Void>.makeStream()
        let coordinator = GenerationHistoryRecoveryCoordinator(
            store: fixture.store,
            commitGeneration: { _, generation in generation },
            fetchAllGenerations: { [] },
            deleteGenerationsThrough: { _ in [] },
            referencedAudioPaths: { _ in
                enteredContinuation.yield()
                for await _ in release { break }
                return []
            }
        )
        let first = try makeAudio(in: fixture, named: "first.wav")
        let second = try makeAudio(in: fixture, named: "second.wav")
        try await coordinator.retainAudioRemoval(first.path)

        let pass = Task { await coordinator.reconcile() }
        for await _ in entered { break }
        try await coordinator.retainAudioRemoval(second.path)
        releaseContinuation.yield()
        let result = await pass.value

        XCTAssertFalse(FileManager.default.fileExists(atPath: first.path), "The pass removed its own path")
        XCTAssertTrue(FileManager.default.fileExists(atPath: second.path))
        XCTAssertEqual(result.snapshot.pendingAudioRemovalCount, 1, "The retained path is still listed")
        XCTAssertEqual(try fixture.store.loadPendingAudioRemovals(), [second.path])
    }

    // MARK: - Bounded clear (AUD-05 second review)

    /// The blocking case: a clear whose row deletion failed is resumed later,
    /// after the user saved a new take. The resume deletes only the rows the
    /// clear captured; the new take and its audio survive.
    func testResumedClearNeverDeletesATakeSavedAfterIt() async throws {
        let fixture = try makeFixture()
        let state = CommitState()
        _ = try state.commit(fixture.generation)
        let coordinator = makeCoordinator(store: fixture.store, state: state)
        state.setFailure(true)
        _ = try? await coordinator.clearAll(deleteAudio: true)
        state.setFailure(false)
        let later = try makeAudio(in: fixture, named: "later.wav")
        let saved = try state.commit(generation(fixture, audioPath: later.path))

        _ = await coordinator.reconcile()

        XCTAssertEqual(state.rows().map(\.id), [saved.id], "Only the captured row is cleared")
        XCTAssertTrue(FileManager.default.fileExists(atPath: later.path), "The later take's audio stays")
        XCTAssertFalse(FileManager.default.fileExists(atPath: fixture.audioURL.path))
        XCTAssertNil(try fixture.store.loadClearTransaction())
    }

    /// A marker from before the bound existed is abandoned, never resumed
    /// unbounded: every row and its audio stay.
    func testLegacyUnboundedClearIsAbandonedWithRowsPreserved() async throws {
        let fixture = try makeFixture()
        let state = CommitState()
        _ = try state.commit(fixture.generation)
        let coordinator = makeCoordinator(store: fixture.store, state: state)
        var legacy = try JSONSerialization.jsonObject(with: encode(GenerationHistoryClearTransaction(
            deleteAudio: true,
            audioPaths: [fixture.audioURL.path],
            pendingEntryIDs: [],
            maxRowID: 1
        ))) as! [String: Any]
        legacy.removeValue(forKey: "maxRowID")
        try JSONSerialization.data(withJSONObject: legacy)
            .write(to: fixture.store.rootURL.appendingPathComponent("clear-transaction.json"))

        _ = await coordinator.reconcile()

        XCTAssertEqual(state.counts.deletes, 0)
        XCTAssertEqual(state.counts.rows, 1)
        XCTAssertTrue(FileManager.default.fileExists(atPath: fixture.audioURL.path))
        XCTAssertNil(try fixture.store.loadClearTransaction(), "The abandoned marker is gone")
    }

    /// Resuming a pending delete-audio clear from a keep-files request keeps the audio.
    func testKeepFilesClearNeverEscalatesAPendingDeleteAudioClear() async throws {
        let fixture = try makeFixture()
        let state = CommitState()
        _ = try state.commit(fixture.generation)
        let coordinator = makeCoordinator(store: fixture.store, state: state)
        state.setFailure(true)
        _ = try? await coordinator.clearAll(deleteAudio: true)
        state.setFailure(false)

        _ = try await coordinator.clearAll(deleteAudio: false)

        XCTAssertEqual(state.counts.rows, 0)
        XCTAssertTrue(FileManager.default.fileExists(atPath: fixture.audioURL.path))
    }

    /// A complete `.writing` marker is the newer state and wins over a stale final file.
    func testNewerWritingMarkerWinsOverAStaleFinalMarker() throws {
        let fixture = try makeFixture()
        let stale = GenerationHistoryClearTransaction(
            deleteAudio: true, audioPaths: [], pendingEntryIDs: [], maxRowID: 3
        )
        try encode(stale).write(to: fixture.store.rootURL.appendingPathComponent("clear-transaction.json"))
        try encode(stale.markingRowsDeleted())
            .write(to: fixture.store.rootURL.appendingPathComponent("clear-transaction.writing"))

        let loaded = try XCTUnwrap(try fixture.store.loadClearTransaction())

        XCTAssertTrue(loaded.rowsDeleted)
        XCTAssertFalse(FileManager.default.fileExists(
            atPath: fixture.store.rootURL.appendingPathComponent("clear-transaction.writing").path
        ))
    }

    /// Audio removal unlinks only a regular file: a symbolic link and a
    /// directory are left alone (and their targets untouched).
    func testAudioRemovalNeverFollowsALinkOrRecursesIntoADirectory() throws {
        let fixture = try makeFixture()
        let target = try makeAudio(in: fixture, named: "target.wav")
        let link = fixture.store.rootURL.deletingLastPathComponent().appendingPathComponent("link.wav")
        try FileManager.default.createSymbolicLink(at: link, withDestinationURL: target)
        let directory = fixture.store.rootURL.deletingLastPathComponent().appendingPathComponent("dir.wav")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)

        XCTAssertEqual(GenerationHistoryAudioFile.removeRegularFile(atPath: link.path), .absentOrNotRegular)
        XCTAssertEqual(GenerationHistoryAudioFile.removeRegularFile(atPath: directory.path), .absentOrNotRegular)
        XCTAssertTrue(FileManager.default.fileExists(atPath: target.path))
        XCTAssertEqual(GenerationHistoryAudioFile.removeRegularFile(atPath: target.path), .removed)
        XCTAssertFalse(FileManager.default.fileExists(atPath: target.path))
    }

    // MARK: - Suspension (IOS-11)

    /// A take whose database write meets a suspended History database is
    /// deferred, never dropped or reported as damage: it stays in the outbox and
    /// the reconcile after resume commits it once.
    func testSuspendedDatabaseDefersTheTakeAndTheReconcileAfterResumeCommitsIt() async throws {
        let fixture = try makeFixture()
        var configuration = Configuration()
        configuration.observesSuspensionNotifications = true
        // File-backed: GRDB never observes suspension for an in-memory queue.
        let queue = try DatabaseQueue(
            path: fixture.store.rootURL.deletingLastPathComponent().appendingPathComponent("history.sqlite").path,
            configuration: configuration
        )
        try GenerationMigrations.makeMigrator().migrate(queue)
        let coordinator = GenerationHistoryRecoveryCoordinator(
            store: fixture.store,
            commitGeneration: { _, generation in
                do {
                    return try await queue.write { db in
                        if let existing = try Generation
                            .filter(Generation.Columns.audioPath == generation.audioPath)
                            .fetchOne(db) {
                            return existing
                        }
                        var copy = generation
                        try copy.insert(db)
                        return copy
                    }
                } catch {
                    throw HistoryPersistenceError.classify(error, operation: .write)
                }
            },
            fetchAllGenerations: { try await queue.read { try Generation.fetchAll($0) } },
            deleteGenerationsThrough: { maxRowID in
                try await queue.write { db in
                    let bounded = Generation.filter(Generation.Columns.id <= maxRowID)
                    let paths = try bounded.select(Generation.Columns.audioPath, as: String.self).fetchAll(db)
                    _ = try bounded.deleteAll(db)
                    return paths
                }
            },
            referencedAudioPaths: { paths in
                let rows = try await queue.read { try Generation.fetchAll($0) }
                return Set(rows.map(\.audioPath)).intersection(paths)
            }
        )
        let entry = try fixture.store.enqueue(fixture.generation, operation: .append)

        NotificationCenter.default.post(name: Database.suspendNotification, object: nil)
        // A throwing step below must not leave every observing queue in the test process suspended.
        defer { NotificationCenter.default.post(name: Database.resumeNotification, object: nil) }
        do {
            _ = try await coordinator.commit(entry)
            XCTFail("A suspended database must refuse the write")
        } catch {
            XCTAssertEqual(error as? GenerationHistoryOutboxError, .databaseUnavailable)
        }
        XCTAssertEqual(fixture.store.scan().entries.map(\.id), [entry.id], "The take stays queued")
        let whileSuspended = await coordinator.reconcile()
        XCTAssertTrue(whileSuspended.committed.isEmpty)
        XCTAssertEqual(whileSuspended.snapshot.pendingCount, 1)
        XCTAssertEqual(whileSuspended.snapshot.issueCount, 0, "Suspension is not damage")
        NotificationCenter.default.post(name: Database.resumeNotification, object: nil)

        let resumed = await coordinator.reconcile()
        XCTAssertEqual(resumed.committed.map(\.audioPath), [fixture.generation.audioPath])
        XCTAssertEqual(resumed.snapshot, .empty)
        let rows = try await queue.read { try Generation.fetchCount($0) }
        XCTAssertEqual(rows, 1)
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
            deleteGenerationsThrough: { try state.delete(throughID: $0) },
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
