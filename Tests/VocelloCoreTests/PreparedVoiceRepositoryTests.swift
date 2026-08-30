import Foundation
@testable import QwenVoiceCore
import XCTest

final class PreparedVoiceRepositoryTests: XCTestCase {
    private var root: URL!
    private let extensions: Set<String> = ["wav", "mp3", "aiff", "m4a"]

    override func setUpWithError() throws {
        root = FileManager.default.temporaryDirectory.appendingPathComponent(
            "prepared-voice-repository-tests-\(UUID().uuidString)",
            isDirectory: true
        )
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        if let root, FileManager.default.fileExists(atPath: root.path) {
            try FileManager.default.removeItem(at: root)
        }
    }

    func testPreparedCandidateIsInvisibleUntilCommit() async throws {
        let repository = makeRepository()
        try await repository.reconcile()
        let source = try writeSource(named: "source.m4a")

        let candidate = try await repository.prepare(
            name: "Review Voice",
            audioURL: source,
            transcript: "  visible only after keep  ",
            qualityWarnings: ["reference_duration_short"],
            replacingVoiceID: nil
        )

        XCTAssertEqual(candidate.name, "Review Voice")
        XCTAssertTrue(candidate.hasTranscript)
        let voicesBeforeCommit = try await repository.list()
        XCTAssertEqual(voicesBeforeCommit, [])
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.appendingPathComponent("voices/Review Voice.m4a").path))

        let committed = try await repository.commit(id: candidate.id)
        XCTAssertEqual(committed.id, "Review Voice")
        XCTAssertEqual(committed.audioURL.pathExtension, "m4a")
        XCTAssertEqual(try String(contentsOf: root.appendingPathComponent("voices/Review Voice.txt"), encoding: .utf8), "visible only after keep")
        let committedIDs = (try await repository.list()).map(\.id)
        XCTAssertEqual(committedIDs, ["Review Voice"])
    }

    func testReviewedReferenceMetadataPublishesTransactionallyAndSurvivesRelaunch() async throws {
        let repository = makeRepository()
        try await repository.reconcile()
        let source = try writeSource(named: "metadata-source.wav")
        let metadata = PreparedVoiceEnrollmentMetadata(
            referenceLanguage: .french,
            transcriptSource: .manual,
            automaticTranscriptionOutcome: "lowConfidence",
            transcriptionEvidenceDigest: String(repeating: "a", count: 64)
        )
        let candidate = try await repository.prepare(
            name: "Reviewed French",
            audioURL: source,
            transcript: "Texte corrigé manuellement.",
            qualityWarnings: [],
            enrollmentMetadata: metadata,
            replacingVoiceID: nil
        )

        XCTAssertEqual(candidate.enrollmentMetadata, metadata)
        XCTAssertFalse(FileManager.default.fileExists(
            atPath: root.appendingPathComponent("voices/Reviewed French.voice.json").path
        ))
        _ = try await repository.commit(id: candidate.id)

        let relaunched = makeRepository()
        try await relaunched.reconcile()
        let listed = try await relaunched.list()
        let voice = try XCTUnwrap(listed.first)
        XCTAssertEqual(voice.enrollmentMetadata, metadata)
        try await relaunched.delete(id: voice.id)
        XCTAssertFalse(FileManager.default.fileExists(
            atPath: root.appendingPathComponent("voices/Reviewed French.voice.json").path
        ))
    }

    func testDiscardIsIdempotentAndAllowsSameNameRetry() async throws {
        let repository = makeRepository()
        try await repository.reconcile()
        let source = try writeSource(named: "source.wav")
        let first = try await repository.prepare(
            name: "Retry Voice",
            audioURL: source,
            transcript: nil,
            qualityWarnings: ["reference_duration_excessive"],
            replacingVoiceID: nil
        )

        try await repository.discard(id: first.id)
        try await repository.discard(id: first.id)
        let voicesAfterDiscard = try await repository.list()
        XCTAssertEqual(voicesAfterDiscard, [])

        _ = try await repository.prepare(
            name: "Retry Voice",
            audioURL: source,
            transcript: nil,
            qualityWarnings: [],
            replacingVoiceID: nil
        )
    }

    func testPendingAndCommittedNamesAreReserved() async throws {
        let repository = makeRepository()
        try await repository.reconcile()
        let source = try writeSource(named: "source.wav")
        let candidate = try await repository.prepare(
            name: "Unique",
            audioURL: source,
            transcript: nil,
            qualityWarnings: [],
            replacingVoiceID: nil
        )

        await XCTAssertThrowsErrorAsync {
            _ = try await repository.prepare(
                name: "Unique",
                audioURL: source,
                transcript: nil,
                qualityWarnings: [],
                replacingVoiceID: nil
            )
        }
        _ = try await repository.commit(id: candidate.id)
        await XCTAssertThrowsErrorAsync {
            _ = try await repository.prepare(
                name: "Unique",
                audioURL: source,
                transcript: nil,
                qualityWarnings: [],
                replacingVoiceID: nil
            )
        }
    }

    func testReplacementPublishesNewVoiceAndRemovesOldAssets() async throws {
        let repository = makeRepository()
        try await repository.reconcile()
        let firstSource = try writeSource(named: "first.wav", bytes: [1, 2, 3])
        let first = try await repository.prepare(
            name: "Bank Base",
            audioURL: firstSource,
            transcript: "old",
            qualityWarnings: [],
            replacingVoiceID: nil
        )
        _ = try await repository.commit(id: first.id)
        try FileManager.default.createDirectory(
            at: root.appendingPathComponent("voices/Bank Base.clone_prompt"),
            withIntermediateDirectories: true
        )

        let replacementSource = try writeSource(named: "second.mp3", bytes: [9, 8, 7])
        let replacement = try await repository.prepare(
            name: "Renamed Base",
            audioURL: replacementSource,
            transcript: "new",
            qualityWarnings: [],
            replacingVoiceID: "Bank Base"
        )
        _ = try await repository.commit(id: replacement.id)

        let replacementIDs = (try await repository.list()).map(\.id)
        XCTAssertEqual(replacementIDs, ["Renamed Base"])
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.appendingPathComponent("voices/Bank Base.wav").path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.appendingPathComponent("voices/Bank Base.clone_prompt").path))
        XCTAssertEqual(try Data(contentsOf: root.appendingPathComponent("voices/Renamed Base.mp3")), Data([9, 8, 7]))
    }

    func testDeleteRemovesOnlySelectedVoiceAndPromptArtifacts() async throws {
        let repository = makeRepository()
        try await repository.reconcile()
        let source = try writeSource(named: "source.wav")
        for name in ["Persona", "Persona (Happy)"] {
            let candidate = try await repository.prepare(
                name: name,
                audioURL: source,
                transcript: nil,
                qualityWarnings: [],
                replacingVoiceID: nil
            )
            _ = try await repository.commit(id: candidate.id)
        }
        try FileManager.default.createDirectory(
            at: root.appendingPathComponent("voices/Persona.clone_prompt"),
            withIntermediateDirectories: true
        )

        try await repository.delete(id: "Persona")

        let remainingIDs = (try await repository.list()).map(\.id)
        XCTAssertEqual(remainingIDs, ["Persona (Happy)"])
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.appendingPathComponent("voices/Persona.clone_prompt").path))
    }

    func testReconcileExpiresCandidatesAndRemovesPartialAndDeleteTombstones() async throws {
        let createdAt = Date(timeIntervalSince1970: 1_700_000_000)
        let repository = PreparedVoiceRepository(
            appSupportDirectory: root,
            supportedAudioExtensions: extensions,
            now: { createdAt }
        )
        try await repository.reconcile()
        let source = try writeSource(named: "source.wav")
        _ = try await repository.prepare(
            name: "Expired",
            audioURL: source,
            transcript: nil,
            qualityWarnings: [],
            replacingVoiceID: nil
        )
        try FileManager.default.createDirectory(
            at: root.appendingPathComponent("voice-candidates/.partial-orphan"),
            withIntermediateDirectories: true
        )
        let deleteTombstone = root.appendingPathComponent("voice-transactions/delete-orphan")
        try FileManager.default.createDirectory(
            at: deleteTombstone,
            withIntermediateDirectories: true
        )
        try JSONSerialization.data(withJSONObject: [
            "schemaVersion": 1,
            "voiceID": "Already Removed",
        ], options: [.sortedKeys]).write(
            to: deleteTombstone.appendingPathComponent("transaction.json"),
            options: [.atomic]
        )

        let relaunched = PreparedVoiceRepository(
            appSupportDirectory: root,
            supportedAudioExtensions: extensions,
            now: { createdAt.addingTimeInterval(PreparedVoiceRepository.candidateLifetime + 1) }
        )
        try await relaunched.reconcile()

        XCTAssertTrue(try FileManager.default.contentsOfDirectory(atPath: root.appendingPathComponent("voice-candidates").path).isEmpty)
        XCTAssertTrue(try FileManager.default.contentsOfDirectory(atPath: root.appendingPathComponent("voice-transactions").path).isEmpty)
    }

    func testMalformedCandidateManifestIsRemovedDuringReconcile() async throws {
        let directory = root.appendingPathComponent("voice-candidates/not-a-uuid", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try Data(#"{"schemaVersion":1,"audioFileName":"../escape.wav"}"#.utf8)
            .write(to: directory.appendingPathComponent("manifest.json"))

        let repository = makeRepository()
        try await repository.reconcile()

        XCTAssertFalse(FileManager.default.fileExists(atPath: directory.path))
    }

    func testReconcileRollsBackInterruptedReplacementBeforeAudioPublication() async throws {
        let repository = makeRepository()
        try await repository.reconcile()
        let originalSource = try writeSource(named: "original.wav", bytes: [1, 2, 3])
        let original = try await repository.prepare(
            name: "Original",
            audioURL: originalSource,
            transcript: "old transcript",
            qualityWarnings: [],
            replacingVoiceID: nil
        )
        _ = try await repository.commit(id: original.id)

        let replacementSource = try writeSource(named: "replacement.mp3", bytes: [9, 8, 7])
        let replacement = try await repository.prepare(
            name: "Replacement",
            audioURL: replacementSource,
            transcript: "new transcript",
            qualityWarnings: [],
            replacingVoiceID: "Original"
        )
        let candidateDirectory = root.appendingPathComponent(
            "voice-candidates/\(replacement.id.uuidString.lowercased())",
            isDirectory: true
        )
        let transactionDirectory = root.appendingPathComponent(
            "voice-transactions/commit-interrupted",
            isDirectory: true
        )
        try FileManager.default.createDirectory(at: transactionDirectory, withIntermediateDirectories: true)
        try FileManager.default.moveItem(
            at: root.appendingPathComponent("voices/Original.wav"),
            to: transactionDirectory.appendingPathComponent("Original.wav")
        )
        try FileManager.default.moveItem(
            at: root.appendingPathComponent("voices/Original.txt"),
            to: transactionDirectory.appendingPathComponent("Original.txt")
        )
        try FileManager.default.moveItem(
            at: candidateDirectory.appendingPathComponent("transcript.txt"),
            to: root.appendingPathComponent("voices/Replacement.txt")
        )
        try writeTransactionManifest(
            candidateID: replacement.id,
            newAudioFileName: "Replacement.mp3",
            newTranscriptFileName: "Replacement.txt",
            to: transactionDirectory
        )

        let relaunched = makeRepository()
        try await relaunched.reconcile()

        let recoveredIDs = (try await relaunched.list()).map(\.id)
        XCTAssertEqual(recoveredIDs, ["Original"])
        XCTAssertEqual(
            try String(contentsOf: candidateDirectory.appendingPathComponent("transcript.txt"), encoding: .utf8),
            "new transcript"
        )
        XCTAssertFalse(FileManager.default.fileExists(atPath: transactionDirectory.path))

        _ = try await relaunched.commit(id: replacement.id)
        let replacementIDs = (try await relaunched.list()).map(\.id)
        XCTAssertEqual(replacementIDs, ["Replacement"])
    }

    func testReconcileCompletesInterruptedReplacementAfterAudioPublication() async throws {
        let repository = makeRepository()
        try await repository.reconcile()
        let originalSource = try writeSource(named: "original.wav", bytes: [1, 2, 3])
        let original = try await repository.prepare(
            name: "Original",
            audioURL: originalSource,
            transcript: nil,
            qualityWarnings: [],
            replacingVoiceID: nil
        )
        _ = try await repository.commit(id: original.id)

        let replacementSource = try writeSource(named: "replacement.mp3", bytes: [9, 8, 7])
        let replacement = try await repository.prepare(
            name: "Replacement",
            audioURL: replacementSource,
            transcript: nil,
            qualityWarnings: [],
            replacingVoiceID: "Original"
        )
        let candidateDirectory = root.appendingPathComponent(
            "voice-candidates/\(replacement.id.uuidString.lowercased())",
            isDirectory: true
        )
        let transactionDirectory = root.appendingPathComponent(
            "voice-transactions/commit-interrupted",
            isDirectory: true
        )
        try FileManager.default.createDirectory(at: transactionDirectory, withIntermediateDirectories: true)
        try FileManager.default.moveItem(
            at: root.appendingPathComponent("voices/Original.wav"),
            to: transactionDirectory.appendingPathComponent("Original.wav")
        )
        try FileManager.default.moveItem(
            at: candidateDirectory.appendingPathComponent("reference.mp3"),
            to: root.appendingPathComponent("voices/Replacement.mp3")
        )
        try writeTransactionManifest(
            candidateID: replacement.id,
            newAudioFileName: "Replacement.mp3",
            newTranscriptFileName: nil,
            to: transactionDirectory
        )

        let relaunched = makeRepository()
        try await relaunched.reconcile()

        let committedIDs = (try await relaunched.list()).map(\.id)
        XCTAssertEqual(committedIDs, ["Replacement"])
        XCTAssertFalse(FileManager.default.fileExists(atPath: candidateDirectory.path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: transactionDirectory.path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.appendingPathComponent("voices/Original.wav").path))
    }

    func testReconcileCompletesJournaledDeleteFromAnyMovePoint() async throws {
        let repository = makeRepository()
        try await repository.reconcile()
        let source = try writeSource(named: "source.wav")
        let candidate = try await repository.prepare(
            name: "Delete Me",
            audioURL: source,
            transcript: "delete transcript",
            qualityWarnings: [],
            replacingVoiceID: nil
        )
        _ = try await repository.commit(id: candidate.id)
        try FileManager.default.createDirectory(
            at: root.appendingPathComponent("voices/Delete Me.clone_prompt"),
            withIntermediateDirectories: true
        )

        let transactionDirectory = root.appendingPathComponent(
            "voice-transactions/delete-interrupted",
            isDirectory: true
        )
        try FileManager.default.createDirectory(at: transactionDirectory, withIntermediateDirectories: true)
        try JSONSerialization.data(withJSONObject: [
            "schemaVersion": 1,
            "voiceID": "Delete Me",
        ], options: [.sortedKeys]).write(
            to: transactionDirectory.appendingPathComponent("transaction.json"),
            options: [.atomic]
        )
        // Simulate a stop after only the transcript crossed into the tombstone.
        try FileManager.default.moveItem(
            at: root.appendingPathComponent("voices/Delete Me.txt"),
            to: transactionDirectory.appendingPathComponent("Delete Me.txt")
        )

        let relaunched = makeRepository()
        try await relaunched.reconcile()

        let remaining = try await relaunched.list()
        XCTAssertEqual(remaining, [])
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.appendingPathComponent("voices/Delete Me.wav").path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.appendingPathComponent("voices/Delete Me.clone_prompt").path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: transactionDirectory.path))
    }

    private func makeRepository() -> PreparedVoiceRepository {
        PreparedVoiceRepository(
            appSupportDirectory: root,
            supportedAudioExtensions: extensions
        )
    }

    private func writeSource(
        named name: String,
        bytes: [UInt8] = [0, 1, 2, 3]
    ) throws -> URL {
        let url = root.appendingPathComponent(name)
        try Data(bytes).write(to: url)
        return url
    }

    private func writeTransactionManifest(
        candidateID: UUID,
        newAudioFileName: String,
        newTranscriptFileName: String?,
        to directory: URL
    ) throws {
        let manifest: [String: Any] = [
            "schemaVersion": 1,
            "candidateID": candidateID.uuidString,
            "newVoiceName": "Replacement",
            "newAudioFileName": newAudioFileName,
            "newTranscriptFileName": newTranscriptFileName.map { $0 as Any } ?? NSNull(),
        ]
        try JSONSerialization.data(withJSONObject: manifest, options: [.sortedKeys])
            .write(to: directory.appendingPathComponent("transaction.json"), options: [.atomic])
    }
}

private func XCTAssertThrowsErrorAsync(
    _ expression: () async throws -> Void,
    file: StaticString = #filePath,
    line: UInt = #line
) async {
    do {
        try await expression()
        XCTFail("Expected an error", file: file, line: line)
    } catch {
        // Expected.
    }
}
