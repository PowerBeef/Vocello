import Foundation
import XCTest

@MainActor
final class GenerationHistoryEnqueueStateTests: XCTestCase {
    private struct InjectedFailure: Error {}
    private var root: URL!
    private var generation: Generation!

    private func prepareFixture() throws {
        root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let ownedRoot = root!
        addTeardownBlock { try FileManager.default.removeItem(at: ownedRoot) }
        let audio = root.appendingPathComponent("take.wav")
        try Data("persisted audio fixture".utf8).write(to: audio)
        generation = Generation(text: "Storage fixture", mode: "custom", modelTier: "speed",
            voice: nil, emotion: nil, speed: nil, audioPath: audio.path,
            duration: 1, createdAt: Date(timeIntervalSince1970: 1_700_000_000), seed: 17)
    }

    func testEnqueueFailureKeepsExactIdentityAndPlayableFileWithoutFalseSave() async throws {
        try prepareFixture()
        let state = GenerationHistoryEnqueueState()
        let bytes = try Data(contentsOf: URL(fileURLWithPath: generation.audioPath))
        let outcome = await state.persist(generation,
            enqueue: { _ in throw InjectedFailure() },
            commit: { _ in XCTFail("No entry was queued"); throw InjectedFailure() },
            onSaved: { _ in XCTFail("Cannot announce a save") })
        XCTAssertEqual(outcome, .unableToQueue)
        XCTAssertEqual(state.records[generation.audioPath], generation)
        XCTAssertEqual(state.availableAudioURLs, [URL(fileURLWithPath: generation.audioPath)])
        XCTAssertEqual(try Data(contentsOf: state.availableAudioURLs[0]), bytes)
    }

    func testRetryReusesOriginalIdentityAndQueuesOnlyOnce() throws {
        try prepareFixture()
        let state = GenerationHistoryEnqueueState()
        _ = state.enqueue(generation) { _ in throw InjectedFailure() }
        var altered = generation!
        altered.seed = 99
        _ = state.enqueue(altered) { _ in throw InjectedFailure() }
        let store = GenerationHistoryOutboxStore(rootURL: root.appendingPathComponent("outbox"))
        state.retry { try store.enqueue($0, operation: .append) }
        state.retry { _ in XCTFail("Already queued"); throw InjectedFailure() }
        XCTAssertTrue(state.records.isEmpty)
        XCTAssertEqual(store.scan().entries.count, 1)
        XCTAssertEqual(store.scan().entries.first?.generation, generation)
    }

    func testRepeatedStorageFailureDoesNotLoseOrMultiplyPendingIdentity() throws {
        try prepareFixture()
        let state = GenerationHistoryEnqueueState()
        for _ in 0..<3 { _ = state.enqueue(generation) { _ in throw InjectedFailure() } }
        state.retry { _ in throw InjectedFailure() }
        XCTAssertEqual(state.records.count, 1)
        XCTAssertEqual(state.records[generation.audioPath], generation)
    }

    func testSuccessfulCommitReturnsSavedAndAnnouncesExactDatabaseRecord() async throws {
        try prepareFixture()
        let state = GenerationHistoryEnqueueState()
        let store = GenerationHistoryOutboxStore(rootURL: root.appendingPathComponent("outbox"))
        var announced: Generation?
        let outcome = await state.persist(generation,
            enqueue: { try store.enqueue($0, operation: .append) },
            commit: { entry in
                var saved = entry.generation
                saved.id = 31
                try store.removeEntry(id: entry.id)
                return saved
            }, onSaved: { announced = $0 })
        XCTAssertEqual(outcome, .saved)
        XCTAssertEqual(announced?.id, 31)
        XCTAssertEqual(announced?.seed, 17)
        XCTAssertTrue(state.records.isEmpty)
        XCTAssertTrue(store.scan().entries.isEmpty)
        XCTAssertTrue(FileManager.default.fileExists(atPath: generation.audioPath))
    }

    func testDatabaseFailureRemainsDurablyQueuedNotUnqueued() async throws {
        try prepareFixture()
        let state = GenerationHistoryEnqueueState()
        let store = GenerationHistoryOutboxStore(rootURL: root.appendingPathComponent("outbox"))
        let outcome = await state.persist(generation,
            enqueue: { try store.enqueue($0, operation: .append) },
            commit: { _ in throw InjectedFailure() }, onSaved: { _ in XCTFail("Database failed") })
        XCTAssertEqual(outcome, .queuedForRecovery)
        XCTAssertTrue(state.records.isEmpty)
        XCTAssertEqual(store.scan().entries.first?.generation, generation)
    }

    func testMissingFileDisablesExportButKeepsVisibleRecoveryIdentity() throws {
        try prepareFixture()
        let state = GenerationHistoryEnqueueState()
        _ = state.enqueue(generation) { _ in throw InjectedFailure() }
        try FileManager.default.removeItem(atPath: generation.audioPath)
        XCTAssertTrue(state.availableAudioURLs.isEmpty)
        XCTAssertEqual(state.records.count, 1)
        let snapshot = GenerationHistoryRecoverySnapshot(pendingCount: 0, availableAudioCount: 0,
            issueCount: 0, clearRecoveryPending: false, unqueuedCount: 1)
        XCTAssertTrue(snapshot.needsAttention)
    }
}
