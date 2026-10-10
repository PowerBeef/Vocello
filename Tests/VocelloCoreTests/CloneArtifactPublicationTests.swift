import Foundation
@testable import QwenVoiceCore
import XCTest

final class CloneArtifactPublicationTests: XCTestCase {
    private enum Injected: Error { case write }

    func testDeletionWhileModelPersistenceIsSuspendedCannotRecreateVoiceArtifacts() async throws {
        let root = try makeRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let source = try makeVoice(in: root)
        let fingerprint = try NativePreparedCloneConditioningCache.stableCloneReferenceFingerprint(for: source)
        let entered = GenerationTaskStartGate()
        let resume = GenerationTaskStartGate()
        let publication = Task.detached { () async throws -> Bool in
            try await persistCloneArtifact(in: root, source: source, fingerprint: fingerprint) { staging in
                try writeArtifact(to: staging)
                await entered.open()
                await resume.wait()
            }
        }
        await entered.wait()
        let deletingProcess = repository(in: root)
        do { try await deletingProcess.delete(id: "Voice") }
        catch {
            await resume.open()
            _ = await publication.result
            throw error
        }
        await resume.open()
        let published = try await publication.value
        XCTAssertFalse(published)
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.appendingPathComponent("voices/Voice.clone_prompt").path))
        try assertNoStaging(in: root)
    }

    func testReplacementWithDifferentAudioRejectsTheOldPrompt() async throws {
        try await assertReplacementRejected(bytes: [9, 8, 7], transcript: "old")
    }

    func testReplacementWithSameAudioAndNewTranscriptRejectsTheOldPrompt() async throws {
        try await assertReplacementRejected(bytes: [1, 2, 3], transcript: "new")
    }

    func testValidSourcePublishesAndInlineTranscriptOverrideIsAllowed() async throws {
        let root = try makeRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let source = try makeVoice(in: root)
        let fingerprint = try NativePreparedCloneConditioningCache.stableCloneReferenceFingerprint(for: source)
        let published = try await persistCloneArtifact(in: root, source: source, fingerprint: fingerprint, checksTranscript: false) {
            try writeArtifact(to: $0)
        }
        XCTAssertTrue(published)
        XCTAssertEqual(try Data(contentsOf: artifact(in: root).appendingPathComponent("payload")), Data([4, 5, 6]))
        // Atomic replacement is covered as well as first publication.
        let replaced = try await persistCloneArtifact(in: root, source: source, fingerprint: fingerprint) { staging in
            try writeArtifact(to: staging, bytes: [7])
        }
        XCTAssertTrue(replaced)
        XCTAssertEqual(try Data(contentsOf: artifact(in: root).appendingPathComponent("payload")), Data([7]))
        try assertNoStaging(in: root)
    }

    func testFailedModelWriteCleansPrivateStagingAndPreservesPublishedArtifact() async throws {
        let root = try makeRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let source = try makeVoice(in: root)
        let fingerprint = try NativePreparedCloneConditioningCache.stableCloneReferenceFingerprint(for: source)
        try writeArtifact(to: artifact(in: root))
        do {
            _ = try await persistCloneArtifact(in: root, source: source, fingerprint: fingerprint) { staging in
                try writeArtifact(to: staging, bytes: [9])
                throw Injected.write
            }
            XCTFail("The original write failure must surface")
        } catch { XCTAssertTrue(error is Injected) }
        XCTAssertEqual(try Data(contentsOf: artifact(in: root).appendingPathComponent("payload")), Data([4, 5, 6]))
        try assertNoStaging(in: root)
    }

    private func assertReplacementRejected(bytes: [UInt8], transcript: String) async throws {
        let root = try makeRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let source = try makeVoice(in: root)
        let fingerprint = try NativePreparedCloneConditioningCache.stableCloneReferenceFingerprint(for: source)
        // Inject replacement at the exact production suspension, after model
        // serialization and before repository publication. No scheduler delay.
        let published = try await persistCloneArtifact(in: root, source: source, fingerprint: fingerprint) { staging in
            try writeArtifact(to: staging)
            let replacement = root.appendingPathComponent("replacement.wav")
            try Data(bytes).write(to: replacement)
            let repo = repository(in: root)
            let candidate = try await repo.prepare(name: "Voice", audioURL: replacement,
                transcript: transcript, qualityWarnings: [], replacingVoiceID: "Voice")
            _ = try await repo.commit(id: candidate.id)
        }
        XCTAssertFalse(published)
        XCTAssertFalse(FileManager.default.fileExists(atPath: artifact(in: root).path))
        try assertNoStaging(in: root)
    }

    private func makeRoot() throws -> URL {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("clone-publication-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        return root
    }

    private func makeVoice(in root: URL) throws -> URL {
        let voices = root.appendingPathComponent("voices")
        try FileManager.default.createDirectory(at: voices, withIntermediateDirectories: true)
        let source = voices.appendingPathComponent("Voice.wav")
        try Data([1, 2, 3]).write(to: source)
        try "old".write(to: voices.appendingPathComponent("Voice.txt"), atomically: true, encoding: .utf8)
        return source
    }

    private func assertNoStaging(in root: URL) throws {
        let files = try FileManager.default.contentsOfDirectory(atPath: root.appendingPathComponent("voices").path)
        XCTAssertFalse(files.contains { $0.hasPrefix(".clone-prompt-staging-") })
    }
}

private func artifact(in root: URL) -> URL {
    root.appendingPathComponent("voices/Voice.clone_prompt/model/digest", isDirectory: true)
}

private func repository(in root: URL) -> PreparedVoiceRepository {
    PreparedVoiceRepository(appSupportDirectory: root, supportedAudioExtensions: ["wav"])
}

private func writeArtifact(to url: URL, bytes: [UInt8] = [4, 5, 6]) throws {
    try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
    try Data(bytes).write(to: url.appendingPathComponent("payload"))
}

private func persistCloneArtifact(in root: URL, source: URL, fingerprint: String,
                     checksTranscript: Bool = true,
                     writer: @Sendable (URL) async throws -> Void) async throws -> Bool {
    try await NativePreparedCloneConditioningCache.persistSavedVoiceCloneArtifact(
        voicesDirectory: root.appendingPathComponent("voices"), artifactDirectory: artifact(in: root),
        voiceID: "Voice", sourceURL: source, sourceFingerprint: fingerprint,
        checksStoredTranscript: checksTranscript, expectedStoredTranscript: "old", persist: writer)
}
