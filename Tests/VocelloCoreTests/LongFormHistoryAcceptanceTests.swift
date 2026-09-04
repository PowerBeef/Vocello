import Foundation
import GRDB
@testable import QwenVoiceCore
import XCTest

final class LongFormHistoryAcceptanceTests: XCTestCase {
    private struct InjectedFailure: Error {}
    private var roots: [URL] = []

    override func tearDownWithError() throws {
        for root in roots { try FileManager.default.removeItem(at: root) }
        roots.removeAll()
    }

    func testAcceptanceCommitsRowsManifestAndRetainsPriorAudio() async throws {
        let f = try fixture()
        let saved = try await f.store.commit(f.input, using: f.queue)
        XCTAssertNotNil(saved.id)
        XCTAssertEqual(try Data(contentsOf: f.input.manifestURL), try f.input.manifest.canonicalJSONData())
        XCTAssertEqual(try rowCount(f.queue), 4)
        XCTAssertTrue(FileManager.default.fileExists(atPath: f.oldJoined.path))
        XCTAssertTrue(try journalURLs(f.store).isEmpty)
    }

    func testDatabaseFailureRestoresPriorManifestAndRows() async throws {
        let f = try fixture()
        try await f.queue.write { db in
            try db.execute(sql: "CREATE TRIGGER refuse_join BEFORE INSERT ON generations WHEN NEW.longFormRole = 'joined' BEGIN SELECT RAISE(ABORT, 'fixture'); END")
        }
        do { _ = try await f.store.commit(f.input, using: f.queue); XCTFail("Expected failure") }
        catch { XCTAssertEqual(error as? LongFormAcceptanceError, .invalidCandidate) }
        XCTAssertEqual(try Data(contentsOf: f.input.manifestURL), f.oldManifest)
        XCTAssertEqual(try rowCount(f.queue), 1)
        XCTAssertTrue(FileManager.default.fileExists(atPath: f.oldJoined.path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: f.input.joined.audioPath))
        XCTAssertTrue(try journalURLs(f.store).isEmpty)
    }

    func testInterruptedBeforeCommitRollsBackOnNextHistoryReadIdempotently() throws {
        let f = try fixture()
        XCTAssertThrowsError(try f.queue.write { db in
            try f.store.prepare(f.input, in: db)
            _ = try f.store.saveRows(f.input, in: db)
            throw InjectedFailure()
        })
        XCTAssertEqual(try journalURLs(f.store).count, 1)
        try f.queue.write { db in try f.store.reconcile(in: db) }
        try f.queue.write { db in try f.store.reconcile(in: db) }
        XCTAssertEqual(try Data(contentsOf: f.input.manifestURL), f.oldManifest)
        XCTAssertEqual(try rowCount(f.queue), 1)
        XCTAssertTrue(FileManager.default.fileExists(atPath: f.input.segments[0].audioPath), "Session-owned reusable segment is not rollback trash")
    }

    func testInterruptedAfterDatabaseCommitFinishesWithoutDuplicates() throws {
        let f = try fixture()
        try f.queue.write { db in
            try f.store.prepare(f.input, in: db)
            _ = try f.store.saveRows(f.input, in: db)
        }
        try f.queue.write { db in try f.store.reconcile(in: db) }
        try f.queue.write { db in try f.store.reconcile(in: db) }
        XCTAssertTrue(try journalURLs(f.store).isEmpty)
        XCTAssertEqual(try rowCount(f.queue), 4)
        XCTAssertTrue(FileManager.default.fileExists(atPath: f.input.joined.audioPath))
        XCTAssertEqual(try Data(contentsOf: f.input.manifestURL), try f.input.manifest.canonicalJSONData())
    }

    func testCorruptionRetainsJournalAndAudioAndFailsClosed() throws {
        let f = try fixture()
        try f.queue.write { db in try f.store.prepare(f.input, in: db) }
        let journal = try XCTUnwrap(journalURLs(f.store).first)
        try Data("corrupt".utf8).write(to: journal)
        XCTAssertThrowsError(try f.queue.write { db in try f.store.reconcile(in: db) })
        XCTAssertTrue(FileManager.default.fileExists(atPath: journal.path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: f.input.joined.audioPath))
    }

    func testMissingAudioAndEncodingFailureCannotChangeAcceptedProject() async throws {
        let f = try fixture()
        try FileManager.default.removeItem(atPath: f.input.segments[0].audioPath)
        do { _ = try await f.store.commit(f.input, using: f.queue); XCTFail("Expected failure") } catch {}
        XCTAssertEqual(try Data(contentsOf: f.input.manifestURL), f.oldManifest)
        XCTAssertEqual(try rowCount(f.queue), 1)

        let bad = try fixture(nonFiniteDuration: true)
        do { _ = try await bad.store.commit(bad.input, using: bad.queue); XCTFail("Expected encoding failure") } catch {}
        XCTAssertEqual(try Data(contentsOf: bad.input.manifestURL), bad.oldManifest)
        XCTAssertEqual(try rowCount(bad.queue), 1)
    }

    func testManifestWriteFailureLeavesPriorDatabaseAndRecoverableJournal() async throws {
        let f = try fixture()
        try FileManager.default.removeItem(at: f.input.manifestURL)
        try FileManager.default.createDirectory(at: f.input.manifestURL, withIntermediateDirectories: false)
        do { _ = try await f.store.commit(f.input, using: f.queue); XCTFail("Expected write failure") } catch {}
        XCTAssertEqual(try rowCount(f.queue), 1)
        XCTAssertTrue(FileManager.default.fileExists(atPath: f.oldJoined.path))
    }

    func testFailedSegmentQCCannotBeAccepted() async throws {
        let f = try fixture(qcPassed: false)
        do { _ = try await f.store.commit(f.input, using: f.queue); XCTFail("Expected QC refusal") } catch {}
        XCTAssertEqual(try Data(contentsOf: f.input.manifestURL), f.oldManifest)
        XCTAssertEqual(try rowCount(f.queue), 1)
    }

    func testFailedJoinedQCCannotBeAccepted() async throws {
        let f = try fixture(joinedQCPassed: false)
        do { _ = try await f.store.commit(f.input, using: f.queue); XCTFail("Expected joined-QC refusal") } catch {}
        XCTAssertEqual(try Data(contentsOf: f.input.manifestURL), f.oldManifest)
        XCTAssertEqual(try rowCount(f.queue), 1)
    }

    func testExactRetryIsIdempotentButChangedIdentityAtSamePathIsRejected() async throws {
        let f = try fixture()
        let first = try await f.store.commit(f.input, using: f.queue)
        let second = try await f.store.commit(f.input, using: f.queue)
        XCTAssertEqual(first.id, second.id)
        XCTAssertEqual(try rowCount(f.queue), 4)
        var different = f.input.joined
        different.seed = 99
        let bad = LongFormHistoryAcceptance(manifestURL: f.input.manifestURL, manifest: f.input.manifest,
            segments: f.input.segments, joined: different, joinedQCPassed: true, ownedAudioURLs: f.input.ownedAudioURLs)
        do { _ = try await f.store.commit(bad, using: f.queue); XCTFail("Cross-request identity accepted") } catch {}
        XCTAssertTrue(FileManager.default.fileExists(atPath: f.input.joined.audioPath))
        XCTAssertEqual(try rowCount(f.queue), 4)
    }

    func testUnrelatedManifestEditIsNeverOverwrittenByRecovery() throws {
        let f = try fixture()
        try f.queue.write { db in try f.store.prepare(f.input, in: db) }
        let unrelated = Data("another accepted identity".utf8)
        try unrelated.write(to: f.input.manifestURL)
        XCTAssertThrowsError(try f.queue.write { db in try f.store.reconcile(in: db) })
        XCTAssertEqual(try Data(contentsOf: f.input.manifestURL), unrelated)
        XCTAssertEqual(try journalURLs(f.store).count, 1)
    }

    func testReusedSegmentWithDifferentIdentityCannotBeAccepted() async throws {
        let f = try fixture()
        try await f.queue.write { db in
            var conflicting = f.input.segments[0]
            conflicting.seed = 42
            try conflicting.insert(db)
        }
        do { _ = try await f.store.commit(f.input, using: f.queue); XCTFail("Expected identity refusal") }
        catch { XCTAssertEqual(error as? LongFormAcceptanceError, .invalidCandidate) }
        XCTAssertEqual(try rowCount(f.queue), 2)
        XCTAssertEqual(try Data(contentsOf: f.input.manifestURL), f.oldManifest)
        XCTAssertTrue(FileManager.default.fileExists(atPath: f.input.segments[0].audioPath))
    }

    func testCleanupRefusalRetainsRecoveryJournalAndAcceptedState() throws {
        let f = try fixture()
        try f.queue.write { db in try f.store.prepare(f.input, in: db) }
        // Simulate a replacement at an operation-owned path. Recovery must not
        // recurse into or remove an unexpected directory as though it were audio.
        let audio = URL(fileURLWithPath: f.input.joined.audioPath)
        try FileManager.default.removeItem(at: audio)
        try FileManager.default.createDirectory(at: audio, withIntermediateDirectories: false)
        XCTAssertThrowsError(try f.queue.write { db in try f.store.reconcile(in: db) })
        XCTAssertEqual(try journalURLs(f.store).count, 1)
        XCTAssertEqual(try Data(contentsOf: f.input.manifestURL), f.oldManifest)
        XCTAssertEqual(try rowCount(f.queue), 1)
        XCTAssertTrue(FileManager.default.fileExists(atPath: audio.path))
    }

    func testCancelledAcceptanceDoesNotPublish() async throws {
        let f = try fixture()
        let task = Task {
            withUnsafeCurrentTask { $0?.cancel() }
            return try await f.store.commit(f.input, using: f.queue)
        }
        do { _ = try await task.value; XCTFail("Expected cancellation") }
        catch { XCTAssertTrue(error is CancellationError) }
        XCTAssertEqual(try Data(contentsOf: f.input.manifestURL), f.oldManifest)
        XCTAssertEqual(try rowCount(f.queue), 1)
    }

    func testOldManifestDecodesAndNewReceiptFieldsRoundTrip() throws {
        let f = try fixture()
        let data = try f.input.manifest.canonicalJSONData()
        let decoded = try JSONDecoder().decode(LongFormManifestV4.self, from: data)
        XCTAssertEqual(decoded, f.input.manifest)
        let oldSegment = Data(#"{"index":1,"segmentID":"old","generated":true,"qcWarnings":[],"qcRequiredFailures":[]}"#.utf8)
        let old = try JSONDecoder().decode(LongFormSegmentExecutionEvidence.self, from: oldSegment)
        XCTAssertNil(old.generationID)
        XCTAssertNil(old.effectiveSeed)
    }

    func testCorruptJournalAllowsOnlyUnrelatedReadAndBoundedPrivateExport() throws {
        let f = try fixture()
        var standalone = f.input.segments[0]
        standalone.longFormProjectID = nil
        standalone.longFormRole = nil
        try f.queue.write { db in
            try standalone.insert(db)
            try f.store.prepare(f.input, in: db)
        }
        let journal = try XCTUnwrap(journalURLs(f.store).first)
        let corrupt = Data("corrupt fixture with private text".utf8)
        try corrupt.write(to: journal)
        let readable = try f.queue.write { try f.store.readableHistory(in: $0) }
        XCTAssertEqual(readable.map(\.audioPath), [standalone.audioPath])
        XCTAssertTrue(f.store.hasPendingRecovery)
        XCTAssertEqual(try f.store.recoveryExportURLs(), [journal])
        XCTAssertEqual(try Data(contentsOf: journal), corrupt)
        XCTAssertThrowsError(try f.queue.write { try f.store.reconcile(in: $0) })
        XCTAssertEqual(try rowCount(f.queue), 2)
        try FileManager.default.removeItem(at: journal)
        try FileManager.default.createSymbolicLink(at: journal, withDestinationURL: f.oldJoined)
        XCTAssertThrowsError(try f.store.recoveryExportURLs(), "Never export a redirected private file")
    }

    func testRetainedSegmentsSurviveJoinFailureAndSupersededOutputRemainsOwned() async throws {
        let f = try fixture()
        try await f.queue.write { db in
            for var segment in f.input.segments { try segment.insert(db) }
        }
        let rejected = LongFormHistoryAcceptance(manifestURL: f.input.manifestURL, manifest: f.input.manifest,
            segments: f.input.segments, joined: f.input.joined, joinedQCPassed: false,
            ownedAudioURLs: f.input.ownedAudioURLs)
        do { _ = try await f.store.commit(rejected, using: f.queue); XCTFail("Joined QC must reject acceptance") }
        catch {}
        let retained = try await f.queue.read { try Generation.fetchAll($0) }
        XCTAssertEqual(Set(retained.map(\.audioPath)), Set(f.input.segments.map(\.audioPath) + [f.oldJoined.path]))
        XCTAssertEqual(try Data(contentsOf: f.input.manifestURL), f.oldManifest)
        for segment in f.input.segments {
            XCTAssertEqual(try Data(contentsOf: URL(fileURLWithPath: segment.audioPath)), Data("fixture audio".utf8))
        }
        let saved = try await f.store.commit(f.input, using: f.queue)
        XCTAssertNotNil(saved.id)
        let rows = try await f.queue.read { try Generation.fetchAll($0) }
        XCTAssertEqual(rows.count, 4)
        XCTAssertEqual(rows.first { $0.audioPath == f.oldJoined.path }?.longFormRole, "superseded")
        XCTAssertEqual(rows.filter { $0.longFormRole == "joined" }.count, 1)
        XCTAssertEqual(Set(rows.map(\.audioPath)), Set(f.input.segments.map(\.audioPath) + [f.input.joined.audioPath, f.oldJoined.path]))
        XCTAssertNoThrow(try GenerationHistoryPersistenceOutcome.saved.requireSavedLongFormSegment())
        XCTAssertThrowsError(try GenerationHistoryPersistenceOutcome.queuedForRecovery.requireSavedLongFormSegment())
        XCTAssertThrowsError(try GenerationHistoryPersistenceOutcome.unableToQueue.requireSavedLongFormSegment())
    }

    private struct Fixture: Sendable {
        let store: LongFormHistoryAcceptanceStore
        let queue: DatabaseQueue
        let input: LongFormHistoryAcceptance
        let oldJoined: URL
        let oldManifest: Data
    }

    private func rowCount(_ queue: DatabaseQueue) throws -> Int {
        try queue.read { try Generation.fetchCount($0) }
    }

    private func journalURLs(_ store: LongFormHistoryAcceptanceStore) throws -> [URL] {
        guard FileManager.default.fileExists(atPath: store.rootURL.path) else { return [] }
        return try FileManager.default.contentsOfDirectory(at: store.rootURL, includingPropertiesForKeys: nil)
    }

    private func fixture(qcPassed: Bool = true, nonFiniteDuration: Bool = false, joinedQCPassed: Bool = true) throws -> Fixture {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString).resolvingSymlinksInPath()
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        roots.append(root)
        let queue = try DatabaseQueue()
        try GenerationMigrations.makeMigrator().migrate(queue)
        let plan = try LongFormPlanner.plan(
            spokenTextPlan: SpokenTextPlanner.plan(originalText: "First sentence. Second sentence."),
            configuration: LongFormPlanningConfiguration(runtimeTokenLimit: 8, baseSeed: 17))
        var records: [Generation] = []
        for segment in plan.segments {
            let audio = root.appendingPathComponent("segment_\(segment.index).wav")
            try Data("fixture audio".utf8).write(to: audio)
            records.append(Generation(text: segment.spokenText, mode: "custom", modelTier: "speed", voice: nil,
                                      emotion: nil, speed: nil, audioPath: audio.path, duration: 1,
                                      createdAt: Date(timeIntervalSince1970: 1_700_000_000.123456),
                                      longFormProjectID: plan.evidence.planDigest, longFormRole: "segment"))
        }
        let joinedURL = root.appendingPathComponent("new_joined.wav")
        try Data("new joined audio".utf8).write(to: joinedURL)
        var joined = records[0]
        joined.audioPath = joinedURL.path
        joined.longFormRole = "joined"
        let oldJoined = root.appendingPathComponent("old_joined.wav")
        try Data("old accepted audio".utf8).write(to: oldJoined)
        var old = joined
        old.audioPath = oldJoined.path
        try queue.write { db in try old.insert(db) }
        let manifestURL = root.appendingPathComponent("manifest.json")
        let oldManifest = Data("prior accepted manifest".utf8)
        try oldManifest.write(to: manifestURL)
        let execution = LongFormExecutionEvidence(generatedAtUTC: "2026-09-04T00:00:00Z", streamingExecution: true,
            segments: plan.segments.map {
                LongFormSegmentExecutionEvidence(index: $0.index, segmentID: $0.segmentID, generated: true,
                    audioDurationSeconds: nonFiniteDuration ? .nan : 1, qcPassed: qcPassed,
                    generationID: UUID(), effectiveSeed: $0.evidence.effectiveSubseed)
            })
        let assembly = LongFormAssemblyEvidence(schemaVersion: 1, algorithmVersion: 1, sampleRate: 24_000,
            blockFrames: 4_096, segmentCount: plan.segments.count, outputFrameCount: 48_000,
            workingSetFrameUpperBound: 4_096, outputDigest: String(repeating: "0", count: 64), outputReadable: true,
            maximumSegmentBoundaryJump: 0, advisoryWarnings: nil,
            segments: plan.segments.map {
                LongFormSegmentOutputFrameMap(segmentID: $0.segmentID, lineage: $0.evidence.lineage,
                    boundary: $0.evidence.boundary, sourceFrameCount: 24_000, trimmedLeadingFrames: 0,
                    trimmedTrailingFrames: 0, contentOutputRange: .init(lowerBound: 0, upperBound: 24_000),
                    insertedPauseOutputRange: .init(lowerBound: 24_000, upperBound: 24_000), sourceRMS: 0.1,
                    appliedGain: 1, verifiedNonSpeechFadeInFrames: 0, verifiedNonSpeechFadeOutFrames: 0)
            })
        return Fixture(store: .init(rootURL: root.appendingPathComponent("journal")), queue: queue,
            input: .init(manifestURL: manifestURL, manifest: .init(plan: plan.evidence, execution: execution, assembly: assembly),
                         segments: records, joined: joined, joinedQCPassed: joinedQCPassed, ownedAudioURLs: [joinedURL]),
            oldJoined: oldJoined, oldManifest: oldManifest)
    }
}
