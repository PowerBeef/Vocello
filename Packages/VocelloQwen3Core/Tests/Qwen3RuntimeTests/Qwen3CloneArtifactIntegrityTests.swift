import CryptoKit
import Foundation
import MLX
@testable import MLXAudioTTS
@testable import VocelloQwen3Core
import XCTest

final class Qwen3CloneArtifactIntegrityTests: XCTestCase {
    func testNonEmptyTensorRoundTripPreservesShapeDTypeAndValues() throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let prompt = tensorPrompt(refText: "fixture")

        try prompt.write(to: directory)
        let loaded = try Qwen3TTSVoiceClonePrompt.load(from: directory)
        let manifest = try JSONDecoder().decode(
            Qwen3TTSVoiceClonePrompt.Manifest.self,
            from: Data(contentsOf: directory.appendingPathComponent("manifest.json"))
        )

        XCTAssertEqual(manifest.schemaVersion, 3)
        XCTAssertEqual(manifest.speakerFeatureVersion, "qwen-speaker-mel-v1+icl-ref-silence500ms-v2")
        XCTAssertEqual(loaded.refCodes?.shape, [1, 2, 2])
        XCTAssertEqual(loaded.refCodes?.dtype, .int32)
        XCTAssertEqual(loaded.refCodes?.asArray(Int32.self), [1, 2, 3, 4])
        XCTAssertEqual(loaded.speakerEmbedding?.shape, [1, 3])
        XCTAssertEqual(loaded.speakerEmbedding?.dtype, .float32)
        XCTAssertEqual(loaded.speakerEmbedding?.asArray(Float.self), [0.25, -0.5, 0.75])
    }

    func testAtomicReplacementPublishesOnlyCompleteNewArtifact() throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        try tensorPrompt(refText: "old").writeAtomically(to: directory)
        try tensorPrompt(refText: "new").writeAtomically(to: directory)

        let loaded = try Qwen3TTSVoiceClonePrompt.load(from: directory)
        XCTAssertEqual(loaded.refText, "new")
        XCTAssertEqual(Set(try FileManager.default.contentsOfDirectory(atPath: directory.path)), Set([
            "manifest.json", "ref_codes.safetensors", "speaker_embedding.safetensors", "integrity.json",
        ]))
    }

    func testInterruptedStagingPreservesPriorArtifactAndRemovesStaging() throws {
        enum FixtureError: Error { case interrupt }
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        try tensorPrompt(refText: "old").writeAtomically(to: directory)

        XCTAssertThrowsError(
            try tensorPrompt(refText: "new").writeAtomically(to: directory) {
                throw FixtureError.interrupt
            }
        )
        XCTAssertEqual(try Qwen3TTSVoiceClonePrompt.load(from: directory).refText, "old")
        let siblings = try FileManager.default.contentsOfDirectory(atPath: directory.deletingLastPathComponent().path)
        XCTAssertFalse(siblings.contains { $0.hasPrefix(".\(directory.lastPathComponent).staging.") })
    }

    func testStaleConditioningVersionFailsClosedAtLoad() throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        try tensorPrompt(refText: "fixture").write(to: directory)

        // A pre-silence-append artifact carries the bare mel-frontend version.
        // Rewrite the manifest to that stale identity with a re-signed
        // integrity entry so the version gate (not digest validation) decides.
        let manifestURL = directory.appendingPathComponent("manifest.json")
        var manifestJSON = try XCTUnwrap(
            JSONSerialization.jsonObject(with: Data(contentsOf: manifestURL)) as? [String: Any]
        )
        manifestJSON["speakerFeatureVersion"] = "qwen-speaker-mel-v1"
        let rewritten = try JSONSerialization.data(
            withJSONObject: manifestJSON,
            options: [.prettyPrinted, .sortedKeys]
        )
        try rewritten.write(to: manifestURL)

        let integrityURL = directory.appendingPathComponent("integrity.json")
        var integrityJSON = try XCTUnwrap(
            JSONSerialization.jsonObject(with: Data(contentsOf: integrityURL)) as? [String: Any]
        )
        var files = try XCTUnwrap(integrityJSON["files"] as? [String: [String: Any]])
        files["manifest.json"]?["byteCount"] = rewritten.count
        files["manifest.json"]?["sha256"] = SHA256.hash(data: rewritten)
            .map { String(format: "%02x", $0) }
            .joined()
        integrityJSON["files"] = files
        try JSONSerialization.data(withJSONObject: integrityJSON).write(to: integrityURL)

        XCTAssertThrowsError(try Qwen3TTSVoiceClonePrompt.load(from: directory)) { error in
            XCTAssertTrue(
                "\(error)".contains("speaker-feature version"),
                "expected the conditioning-version gate to reject the stale artifact, got: \(error)"
            )
        }
    }

    func testDigestCorruptionFailsClosed() throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        try tensorPrompt(refText: "fixture").write(to: directory)
        try Data("tampered".utf8).write(to: directory.appendingPathComponent("manifest.json"))
        XCTAssertThrowsError(try Qwen3TTSVoiceClonePrompt.load(from: directory))
    }

    func testMissingAndExtraFilesFailClosed() throws {
        let missing = temporaryDirectory()
        let extra = temporaryDirectory()
        defer {
            try? FileManager.default.removeItem(at: missing)
            try? FileManager.default.removeItem(at: extra)
        }
        try tensorPrompt(refText: "missing").write(to: missing)
        try FileManager.default.removeItem(at: missing.appendingPathComponent("ref_codes.safetensors"))
        XCTAssertThrowsError(try Qwen3TTSVoiceClonePrompt.load(from: missing))

        try tensorPrompt(refText: "extra").write(to: extra)
        try Data([0]).write(to: extra.appendingPathComponent("unexpected.bin"))
        XCTAssertThrowsError(try Qwen3TTSVoiceClonePrompt.load(from: extra))
    }

    func testShapeAndDTypeMetadataMismatchFailsClosed() throws {
        let directory = temporaryDirectory()
        let alternate = temporaryDirectory()
        defer {
            try? FileManager.default.removeItem(at: directory)
            try? FileManager.default.removeItem(at: alternate)
        }
        try tensorPrompt(refText: "fixture").write(to: directory)
        let alternatePrompt = Qwen3TTSVoiceClonePrompt(
            refCodes: MLXArray([Float(1), 2, 3, 4]).reshaped(1, 4),
            speakerEmbedding: MLXArray([Float(1)]).reshaped(1, 1),
            refText: "alternate",
            xVectorOnlyMode: false,
            iclMode: true
        )
        try alternatePrompt.write(to: alternate)
        try FileManager.default.removeItem(at: directory.appendingPathComponent("ref_codes.safetensors"))
        try FileManager.default.copyItem(
            at: alternate.appendingPathComponent("ref_codes.safetensors"),
            to: directory.appendingPathComponent("ref_codes.safetensors")
        )

        let decoder = JSONDecoder()
        let encoder = JSONEncoder()
        let original = try decoder.decode(
            Qwen3TTSVoiceClonePrompt.IntegrityManifest.self,
            from: Data(contentsOf: directory.appendingPathComponent("integrity.json"))
        )
        let replacement = try decoder.decode(
            Qwen3TTSVoiceClonePrompt.IntegrityManifest.self,
            from: Data(contentsOf: alternate.appendingPathComponent("integrity.json"))
        )
        var files = original.files
        let newFile = try XCTUnwrap(replacement.files["ref_codes.safetensors"])
        let oldFile = try XCTUnwrap(original.files["ref_codes.safetensors"])
        files["ref_codes.safetensors"] = .init(
            byteCount: newFile.byteCount,
            sha256: newFile.sha256,
            tensorKey: oldFile.tensorKey,
            shape: oldFile.shape,
            dataType: oldFile.dataType
        )
        try encoder.encode(
            Qwen3TTSVoiceClonePrompt.IntegrityManifest(schemaVersion: 1, files: files)
        ).write(to: directory.appendingPathComponent("integrity.json"))

        XCTAssertThrowsError(try Qwen3TTSVoiceClonePrompt.load(from: directory))
    }

    func testModeRequirementsRejectIncompleteArtifacts() throws {
        let xVector = temporaryDirectory()
        let icl = temporaryDirectory()
        defer {
            try? FileManager.default.removeItem(at: xVector)
            try? FileManager.default.removeItem(at: icl)
        }
        try Qwen3TTSVoiceClonePrompt(
            refCodes: nil, speakerEmbedding: nil, refText: nil,
            xVectorOnlyMode: true, iclMode: false
        ).write(to: xVector)
        try Qwen3TTSVoiceClonePrompt(
            refCodes: nil, speakerEmbedding: MLXArray([Float(1)]).reshaped(1, 1), refText: nil,
            xVectorOnlyMode: false, iclMode: true
        ).write(to: icl)
        XCTAssertThrowsError(try Qwen3TTSVoiceClonePrompt.load(from: xVector))
        XCTAssertThrowsError(try Qwen3TTSVoiceClonePrompt.load(from: icl))
    }

    func testXVectorOnlyArtifactRoundTripContainsOnlySpeakerConditioning() throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let metadata = Qwen3TTSVoiceClonePrompt.ArtifactMetadata(
            modelID: "pro_clone_speed",
            language: "english",
            sourceAudioFingerprint: "fixture-audio",
            transcriptHash: nil,
            hasTranscript: false,
            xVectorOnlyMode: true,
            qwen3RuntimeProfileSignature: "fixture-runtime"
        )
        let prompt = Qwen3TTSVoiceClonePrompt(
            refCodes: nil,
            speakerEmbedding: MLXArray([Float(0.25), -0.5, 0.75]).reshaped(1, 3),
            refText: nil,
            xVectorOnlyMode: true,
            iclMode: false,
            artifactMetadata: metadata
        )

        try prompt.write(to: directory)
        let loaded = try Qwen3TTSVoiceClonePrompt.load(
            from: directory,
            expectedMetadata: metadata
        )

        XCTAssertTrue(loaded.xVectorOnlyMode)
        XCTAssertFalse(loaded.iclMode)
        XCTAssertNil(loaded.refCodes)
        XCTAssertNil(loaded.refText)
        XCTAssertEqual(
            loaded.speakerEmbedding?.asArray(Float.self),
            [0.25, -0.5, 0.75]
        )
        XCTAssertEqual(
            Set(try FileManager.default.contentsOfDirectory(atPath: directory.path)),
            Set(["manifest.json", "speaker_embedding.safetensors", "integrity.json"])
        )
    }

    func testExpectedRuntimeContractSignatureRejectsStaleArtifact() throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let staleMetadata = Qwen3TTSVoiceClonePrompt.ArtifactMetadata(
            modelID: "pro_clone_speed",
            language: "english",
            sourceAudioFingerprint: "fixture-audio",
            transcriptHash: nil,
            hasTranscript: false,
            xVectorOnlyMode: true,
            qwen3RuntimeProfileSignature: "qv-clone-prompt-runtime-v2-stale"
        )
        let prompt = Qwen3TTSVoiceClonePrompt(
            refCodes: nil,
            speakerEmbedding: MLXArray([Float(0.25), -0.5, 0.75]).reshaped(1, 3),
            refText: nil,
            xVectorOnlyMode: true,
            iclMode: false,
            artifactMetadata: staleMetadata
        )
        try prompt.write(to: directory)

        let currentMetadata = Qwen3TTSVoiceClonePrompt.ArtifactMetadata(
            modelID: "pro_clone_speed",
            language: "english",
            sourceAudioFingerprint: "fixture-audio",
            transcriptHash: nil,
            hasTranscript: false,
            xVectorOnlyMode: true,
            qwen3RuntimeProfileSignature: "qv-clone-prompt-runtime-v2-current"
        )

        XCTAssertThrowsError(
            try Qwen3TTSVoiceClonePrompt.load(
                from: directory,
                expectedMetadata: currentMetadata
            )
        )
    }

    func testExpectedModelArtifactIdentityRejectsEachChangedField() throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let baseline = artifactMetadata()
        try Qwen3TTSVoiceClonePrompt(
            refCodes: nil,
            speakerEmbedding: MLXArray([Float(0.25), -0.5, 0.75]).reshaped(1, 3),
            refText: nil,
            xVectorOnlyMode: true,
            iclMode: false,
            artifactMetadata: baseline
        ).write(to: directory)

        let changedIdentities = [
            artifactMetadata(modelRepository: "other/model"),
            artifactMetadata(modelRevision: String(repeating: "b", count: 40)),
            artifactMetadata(modelArtifactVersion: "artifact-v2"),
            artifactMetadata(modelIntegrityManifestDigest: String(repeating: "b", count: 64)),
        ]
        for expected in changedIdentities {
            XCTAssertThrowsError(
                try Qwen3TTSVoiceClonePrompt.load(
                    from: directory,
                    expectedMetadata: expected
                )
            )
        }

        XCTAssertNoThrow(
            try Qwen3TTSVoiceClonePrompt.load(
                from: directory,
                expectedMetadata: baseline
            )
        )
    }

    func testSchemaTwoArtifactFailsClosedThroughLowLevelAndFacadeReaders() throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        try tensorPrompt(refText: "legacy").write(to: directory)

        try rewriteManifest(in: directory) { manifest in
            manifest["schemaVersion"] = 2
            manifest.removeValue(forKey: "speakerFeatureVersion")
        }

        XCTAssertThrowsError(try Qwen3TTSVoiceClonePrompt.load(from: directory))
        XCTAssertThrowsError(try VocelloQwen3ClonePrompt.load(from: directory))
    }

    func testCurrentSchemaRejectsMismatchedSpeakerFeatureVersionUnconditionally() throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        try tensorPrompt(refText: "stale-frontend").write(to: directory)

        try rewriteManifest(in: directory) { manifest in
            manifest["speakerFeatureVersion"] = "legacy-generic-mel"
        }

        XCTAssertThrowsError(try Qwen3TTSVoiceClonePrompt.load(from: directory))
        XCTAssertThrowsError(try VocelloQwen3ClonePrompt.load(from: directory))
    }

    private func tensorPrompt(refText: String) -> Qwen3TTSVoiceClonePrompt {
        Qwen3TTSVoiceClonePrompt(
            refCodes: MLXArray([Int32(1), 2, 3, 4]).reshaped(1, 2, 2),
            speakerEmbedding: MLXArray([Float(0.25), -0.5, 0.75]).reshaped(1, 3),
            refText: refText,
            xVectorOnlyMode: false,
            iclMode: true
        )
    }

    private func artifactMetadata(
        modelRepository: String = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-4bit",
        modelRevision: String = String(repeating: "a", count: 40),
        modelArtifactVersion: String = "artifact-v1",
        modelIntegrityManifestDigest: String = String(repeating: "a", count: 64)
    ) -> Qwen3TTSVoiceClonePrompt.ArtifactMetadata {
        Qwen3TTSVoiceClonePrompt.ArtifactMetadata(
            modelID: "pro_clone_speed",
            modelRepository: modelRepository,
            modelRevision: modelRevision,
            modelArtifactVersion: modelArtifactVersion,
            modelIntegrityManifestDigest: modelIntegrityManifestDigest,
            language: "english",
            sourceAudioFingerprint: "fixture-audio",
            hasTranscript: false,
            xVectorOnlyMode: true,
            qwen3RuntimeProfileSignature: "qv-clone-prompt-runtime-v2-fixture"
        )
    }

    private func rewriteManifest(
        in directory: URL,
        transform: (inout [String: Any]) -> Void
    ) throws {
        let manifestURL = directory.appendingPathComponent("manifest.json")
        var manifest = try XCTUnwrap(
            JSONSerialization.jsonObject(with: Data(contentsOf: manifestURL)) as? [String: Any]
        )
        transform(&manifest)
        let manifestData = try JSONSerialization.data(
            withJSONObject: manifest,
            options: [.prettyPrinted, .sortedKeys]
        )
        try manifestData.write(to: manifestURL, options: .atomic)

        let integrityURL = directory.appendingPathComponent(Qwen3TTSVoiceClonePrompt.integrityFilename)
        let decoder = JSONDecoder()
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        let integrity = try decoder.decode(
            Qwen3TTSVoiceClonePrompt.IntegrityManifest.self,
            from: Data(contentsOf: integrityURL)
        )
        var files = integrity.files
        files["manifest.json"] = .init(
            byteCount: manifestData.count,
            sha256: SHA256.hash(data: manifestData).map { String(format: "%02x", $0) }.joined(),
            tensorKey: nil,
            shape: nil,
            dataType: nil
        )
        try encoder.encode(
            Qwen3TTSVoiceClonePrompt.IntegrityManifest(
                schemaVersion: Qwen3TTSVoiceClonePrompt.integritySchemaVersion,
                files: files
            )
        ).write(to: integrityURL, options: .atomic)
    }

    private func temporaryDirectory() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent("qwen3-clone-integrity-\(UUID().uuidString)", isDirectory: true)
    }
}
