import Foundation
@testable import QwenVoiceCore
import XCTest

final class CloneArtifactPublicationTests: XCTestCase {
    private enum Injected: Error { case write }

    @concurrent func testDeletionWhileModelPersistenceIsSuspendedCannotRecreateVoiceArtifacts() async throws {
        let root = try makeRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let source = try makeVoice(in: root)
        let fingerprint = try NativePreparedCloneConditioningCache.stableCloneReferenceFingerprint(for: source)
        let entered = GenerationTaskStartGate()
        let resume = GenerationTaskStartGate()
        let publication = Task.detached { @concurrent () async throws -> Bool in
            try await persistCloneArtifact(in: root, source: source, fingerprint: fingerprint) { @concurrent staging in
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

    @concurrent func testReplacementWithDifferentAudioRejectsTheOldPrompt() async throws {
        try await assertReplacementRejected(bytes: [9, 8, 7], transcript: "old")
    }

    @concurrent func testReplacementWithSameAudioAndNewTranscriptRejectsTheOldPrompt() async throws {
        try await assertReplacementRejected(bytes: [1, 2, 3], transcript: "new")
    }

    @concurrent func testValidSourcePublishesAndInlineTranscriptOverrideIsAllowed() async throws {
        let root = try makeRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let source = try makeVoice(in: root)
        let fingerprint = try NativePreparedCloneConditioningCache.stableCloneReferenceFingerprint(for: source)
        let published = try await persistCloneArtifact(in: root, source: source, fingerprint: fingerprint, checksTranscript: false) { @concurrent in
            try writeArtifact(to: $0)
        }
        XCTAssertTrue(published)
        XCTAssertEqual(try Data(contentsOf: artifact(in: root).appendingPathComponent("payload")), Data([4, 5, 6]))
        // Atomic replacement is covered as well as first publication.
        let replaced = try await persistCloneArtifact(in: root, source: source, fingerprint: fingerprint) { @concurrent staging in
            try writeArtifact(to: staging, bytes: [7])
        }
        XCTAssertTrue(replaced)
        XCTAssertEqual(try Data(contentsOf: artifact(in: root).appendingPathComponent("payload")), Data([7]))
        try assertNoStaging(in: root)
    }

    /// iOS spells the App Group container /private/var/…. A new artifact beside
    /// an older one (after an MLX or model update) must still publish there
    /// (CONV-21: every take of such a voice failed on the iPhone).
    @concurrent func testPrivateSpelledContainerPublishesBesideAnOlderArtifact() async throws {
        let root = try makeRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        guard root.path.hasPrefix("/private/") else {
            throw XCTSkip("the temporary directory has no /private spelling on this host")
        }
        let source = try makeVoice(in: root)
        let older = root.appendingPathComponent("voices/Voice.clone_prompt/model/older", isDirectory: true)
        try writeArtifact(to: older, bytes: [1])
        let fingerprint = try NativePreparedCloneConditioningCache.stableCloneReferenceFingerprint(for: source)
        let published = try await persistCloneArtifact(in: root, source: source, fingerprint: fingerprint) { @concurrent in
            try writeArtifact(to: $0)
        }
        XCTAssertTrue(published)
        XCTAssertEqual(try Data(contentsOf: artifact(in: root).appendingPathComponent("payload")), Data([4, 5, 6]))
        XCTAssertTrue(FileManager.default.fileExists(atPath: older.appendingPathComponent("payload").path))
        try assertNoStaging(in: root)
    }

    /// Publication writes only inside the voice's own prompt root, through the
    /// URLs it checked: every other source, staging or destination is refused
    /// before anything moves, symbolic links and `..` included.
    @concurrent func testPublicationRefusesPathsOutsideTheVoice() async throws {
        let root = try makeRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let source = try makeVoice(in: root)
        let voices = root.appendingPathComponent("voices", isDirectory: true)
        let elsewhere = root.appendingPathComponent("elsewhere/inner", isDirectory: true)
        try FileManager.default.createDirectory(at: elsewhere, withIntermediateDirectories: true)
        try FileManager.default.createSymbolicLink(at: voices.appendingPathComponent("L"), withDestinationURL: elsewhere)
        try Data([1]).write(to: voices.appendingPathComponent("Other.wav"))
        try Data([1, 2, 3]).write(to: root.appendingPathComponent("Voice.wav"))
        let fingerprint = try NativePreparedCloneConditioningCache.stableCloneReferenceFingerprint(for: source)
        let staging = voices.appendingPathComponent(".clone-prompt-staging-test", isDirectory: true)
        let outsideStaging = root.appendingPathComponent(".clone-prompt-staging-test", isDirectory: true)
        let misnamedStaging = voices.appendingPathComponent("staging-test", isDirectory: true)
        for directory in [staging, outsideStaging, misnamedStaging] { try writeArtifact(to: directory) }
        var cases: [(label: String, staging: URL, destination: URL, source: URL)] = [
            "voices/Voice.clone_prompt/model/../../../outside/model/digest",
            "voices/Voice.clone_prompt/digest",
            "voices/Voice.clone_prompt/model/extra/digest",
            "voices/Other.clone_prompt/model/digest",
            "voices/Voice.clone_prompt/L/../model/digest",
        ].map { ("destination \($0)", staging, root.appendingPathComponent($0, isDirectory: true), source) }
        cases += [
            ("staging outside voices", outsideStaging, artifact(in: root), source),
            ("staging without the prefix", misnamedStaging, artifact(in: root), source),
            ("another voice's source", staging, artifact(in: root), voices.appendingPathComponent("Other.wav")),
            ("source outside voices", staging, artifact(in: root), root.appendingPathComponent("Voice.wav")),
            ("unsupported source", staging, artifact(in: root), voices.appendingPathComponent("Voice.txt")),
            ("source behind a link", staging, artifact(in: root), voices.appendingPathComponent("L/../Voice.wav")),
        ]
        let repo = repository(in: root)
        for item in cases {
            do {
                _ = try await repo.publishClonePromptArtifact(
                    from: item.staging, to: item.destination, voiceID: "Voice", sourceURL: item.source,
                    sourceFingerprint: fingerprint, checksStoredTranscript: false, expectedStoredTranscript: nil)
                XCTFail("\(item.label) must be refused")
            } catch PreparedVoiceRepositoryError.invalidIdentifier {
            } catch {
                XCTFail("\(item.label): \(error)")
            }
            XCTAssertTrue(FileManager.default.fileExists(atPath: item.staging.appendingPathComponent("payload").path), item.label)
        }
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.appendingPathComponent("outside").path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.appendingPathComponent("elsewhere/model").path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: artifact(in: root).path))
    }

    /// A refused publication skips the cache instead of failing the take.
    @concurrent func testRefusedPublicationSkipsTheCacheWithoutFailing() async throws {
        let root = try makeRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let source = try makeVoice(in: root)
        let fingerprint = try NativePreparedCloneConditioningCache.stableCloneReferenceFingerprint(for: source)
        let published = try await NativePreparedCloneConditioningCache.persistSavedVoiceCloneArtifact(
            voicesDirectory: root.appendingPathComponent("voices"),
            artifactDirectory: root.appendingPathComponent("voices/Other.clone_prompt/model/digest", isDirectory: true),
            voiceID: "Voice", sourceURL: source, sourceFingerprint: fingerprint,
            checksStoredTranscript: true, expectedStoredTranscript: "old"
        ) { @concurrent in
            try writeArtifact(to: $0)
        }
        XCTAssertFalse(published)
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.appendingPathComponent("voices/Other.clone_prompt").path))
        try assertNoStaging(in: root)
    }

    @concurrent func testFailedModelWriteCleansPrivateStagingAndPreservesPublishedArtifact() async throws {
        let root = try makeRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let source = try makeVoice(in: root)
        let fingerprint = try NativePreparedCloneConditioningCache.stableCloneReferenceFingerprint(for: source)
        try writeArtifact(to: artifact(in: root))
        do {
            _ = try await persistCloneArtifact(in: root, source: source, fingerprint: fingerprint) { @concurrent staging in
                try writeArtifact(to: staging, bytes: [9])
                throw Injected.write
            }
            XCTFail("The original write failure must surface")
        } catch { XCTAssertTrue(error is Injected) }
        XCTAssertEqual(try Data(contentsOf: artifact(in: root).appendingPathComponent("payload")), Data([4, 5, 6]))
        try assertNoStaging(in: root)
    }

    @concurrent private func assertReplacementRejected(bytes: [UInt8], transcript: String) async throws {
        let root = try makeRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let source = try makeVoice(in: root)
        let fingerprint = try NativePreparedCloneConditioningCache.stableCloneReferenceFingerprint(for: source)
        // Inject replacement at the exact production suspension, after model
        // serialization and before repository publication. No scheduler delay.
        let published = try await persistCloneArtifact(in: root, source: source, fingerprint: fingerprint) { @concurrent staging in
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

    /// Spelled as the device spells its container (iOS keeps the App Group under
    /// /private/var) wherever the temporary directory has that spelling.
    private func makeRoot() throws -> URL {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("clone-publication-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let privateSpelling = URL(fileURLWithPath: "/private" + root.path)
        guard !root.path.hasPrefix("/private/"), FileManager.default.fileExists(atPath: privateSpelling.path) else {
            return root
        }
        return privateSpelling
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

@concurrent private func persistCloneArtifact(in root: URL, source: URL, fingerprint: String,
                     checksTranscript: Bool = true,
                     writer: @Sendable @concurrent (URL) async throws -> Void) async throws -> Bool {
    try await NativePreparedCloneConditioningCache.persistSavedVoiceCloneArtifact(
        voicesDirectory: root.appendingPathComponent("voices"), artifactDirectory: artifact(in: root),
        voiceID: "Voice", sourceURL: source, sourceFingerprint: fingerprint,
        checksStoredTranscript: checksTranscript, expectedStoredTranscript: "old", persist: writer)
}
