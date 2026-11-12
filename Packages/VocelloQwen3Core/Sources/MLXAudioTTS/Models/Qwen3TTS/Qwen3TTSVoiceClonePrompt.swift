// Reference audio and the voice-clone prompt artifact of the Qwen3-TTS runtime.
// Moved out of Qwen3TTS.swift unchanged (RF-46).

import CryptoKit
import Foundation
import Hub
import HuggingFace
@preconcurrency import MLX
import MLXAudioCore
@preconcurrency import MLXLMCommon
import MLXNN
import os
import Tokenizers

enum Qwen3TTSReferenceAudio {
    /// Reference audio uses the codec's fixed 24 kHz contract.
    static let sampleRate = 24_000

    /// Trailing silence appended to the reference before codec encode on the
    /// ICL path: none since 2026-11-11, as upstream Qwen3-TTS encodes the
    /// reference as it is given. The clone screen's rule
    /// `reference-padding-none` adopted it (A-12, G-07, RF-52).
    static let codecEncodeTrailingSilenceSamples = 0

    /// The half second of zeros Vocello appended before then, its own step
    /// (added so a take would not inherit a truncated final phoneme, never
    /// measured). The gated `QWENVOICE_REFERENCE_PADDING=half-second` restores
    /// it for a screen.
    static let legacyTrailingSilenceSamples = sampleRate / 2

    /// Version token for ICL reference-encode preprocessing. It participates
    /// in the persisted clone-artifact conditioning version, so any change to
    /// how the reference is prepared for `speechTokenizer.encode` must change
    /// this string to force fail-closed artifact and cache rebuilds. v3: the
    /// reference is encoded unpadded (v2 appended half a second of zeros).
    static let codecEncodeConditioningVersion = "icl-ref-unpadded-v3"

    /// Accepts only the three mono layouts used by the Qwen clone contract and
    /// returns one canonical `[1, T]` batch. Never selects or truncates a batch
    /// or channel implicitly.
    static func canonicalMonoBatch(_ audio: MLXArray) throws -> MLXArray {
        let shape = audio.shape
        let canonical: MLXArray
        if shape.count == 1, shape[0] > 0 {
            canonical = audio.expandedDimensions(axis: 0)
        } else if shape.count == 2, shape[0] == 1, shape[1] > 0 {
            canonical = audio
        } else if shape.count == 3, shape[0] == 1, shape[1] == 1, shape[2] > 0 {
            canonical = audio.squeezed(axis: 1)
        } else {
            throw AudioGenerationError.invalidInput(
                "Qwen speaker reference audio must be mono with shape [T], [1, T], or [1, 1, T]."
            )
        }
        return canonical
    }

    /// G-07 (RF-52): a reference without its silent edges, faded in and out.
    /// Every 10 ms window whose RMS reaches 50 dB below the loudest window's
    /// (and at least -70 dBFS) counts as sound; the reference keeps everything
    /// from 100 ms before the first such window to 100 ms after the last, so
    /// soft onsets and endings stay, then fades in and out over 10 ms (half a
    /// raised cosine) so a reference that was cut mid-sound ends without a
    /// step. A reference with no sound, or shorter than two windows, is
    /// returned as given. Returns `[T']`.
    static func edgesTrimmedAndFaded(_ audio: MLXArray) throws -> MLXArray {
        let samples = try canonicalMonoBatch(audio)[0].asType(.float32).asArray(Float.self)
        return MLXArray(edgesTrimmedAndFaded(samples))
    }

    static func edgesTrimmedAndFaded(_ samples: [Float]) -> [Float] {
        let window = sampleRate / 100
        let margin = sampleRate / 10
        let fade = sampleRate / 100
        guard samples.count >= 2 * window else {
            return samples
        }
        var levels: [Float] = []
        levels.reserveCapacity(samples.count / window + 1)
        var start = 0
        while start < samples.count {
            let end = min(samples.count, start + window)
            var energy: Float = 0
            for index in start ..< end {
                energy += samples[index] * samples[index]
            }
            levels.append((energy / Float(end - start)).squareRoot())
            start = end
        }
        guard let loudest = levels.max(), loudest > 0 else {
            return samples
        }
        let threshold = max(loudest * Float(pow(10.0, -50.0 / 20.0)), Float(pow(10.0, -70.0 / 20.0)))
        guard let first = levels.firstIndex(where: { $0 >= threshold }),
              let last = levels.lastIndex(where: { $0 >= threshold })
        else {
            return samples
        }
        let lower = max(0, first * window - margin)
        let upper = min(samples.count, (last + 1) * window + margin)
        var kept = Array(samples[lower ..< upper])
        let ramp = min(fade, kept.count / 2)
        for index in 0 ..< ramp {
            let gain = 0.5 - 0.5 * cos(Float.pi * Float(index) / Float(ramp))
            kept[index] *= gain
            kept[kept.count - 1 - index] *= gain
        }
        return kept
    }

    /// Canonical `[1, 1, T + pad]` codec-encoder input with a chosen amount of
    /// trailing silence; zero, the production value, encodes the reference as
    /// it is, as upstream does (A-12, RF-52). x-vector extraction never takes
    /// this padding. Both read the same reference, edge-trimmed or as given
    /// (`Qwen3TTSModel.conditioningReference`).
    static func encoderInput(_ audio: MLXArray, trailingSilenceSamples: Int) throws -> MLXArray {
        let monoBatch = try canonicalMonoBatch(audio)
        guard trailingSilenceSamples > 0 else {
            return monoBatch.expandedDimensions(axis: 1)
        }
        let silence = MLXArray.zeros([1, trailingSilenceSamples], dtype: monoBatch.dtype)
        return concatenated([monoBatch, silence], axis: 1).expandedDimensions(axis: 1)
    }
}

public struct Qwen3TTSVoiceClonePrompt: @unchecked Sendable {
    public struct ArtifactMetadata: Codable, Hashable, Sendable {
        public let modelID: String?
        public let modelRepository: String?
        public let modelRevision: String?
        public let modelArtifactVersion: String?
        public let modelIntegrityManifestDigest: String?
        public let language: String?
        public let sourceAudioFingerprint: String?
        public let transcriptHash: String?
        public let hasTranscript: Bool?
        public let xVectorOnlyMode: Bool?
        public let qwen3RuntimeProfileSignature: String?
        public let createdAt: String?

        public init(
            modelID: String? = nil,
            modelRepository: String? = nil,
            modelRevision: String? = nil,
            modelArtifactVersion: String? = nil,
            modelIntegrityManifestDigest: String? = nil,
            language: String? = nil,
            sourceAudioFingerprint: String? = nil,
            transcriptHash: String? = nil,
            hasTranscript: Bool? = nil,
            xVectorOnlyMode: Bool? = nil,
            qwen3RuntimeProfileSignature: String? = nil,
            createdAt: String? = nil
        ) {
            self.modelID = modelID
            self.modelRepository = modelRepository
            self.modelRevision = modelRevision
            self.modelArtifactVersion = modelArtifactVersion
            self.modelIntegrityManifestDigest = modelIntegrityManifestDigest
            self.language = language
            self.sourceAudioFingerprint = sourceAudioFingerprint
            self.transcriptHash = transcriptHash
            self.hasTranscript = hasTranscript
            self.xVectorOnlyMode = xVectorOnlyMode
            self.qwen3RuntimeProfileSignature = qwen3RuntimeProfileSignature
            self.createdAt = createdAt
        }

        public func matches(_ expected: ArtifactMetadata) -> Bool {
            if let expectedModelID = expected.modelID, modelID != expectedModelID { return false }
            if let expectedRepository = expected.modelRepository,
               modelRepository != expectedRepository {
                return false
            }
            if let expectedRevision = expected.modelRevision,
               modelRevision != expectedRevision {
                return false
            }
            if let expectedArtifactVersion = expected.modelArtifactVersion,
               modelArtifactVersion != expectedArtifactVersion {
                return false
            }
            if let expectedManifestDigest = expected.modelIntegrityManifestDigest,
               modelIntegrityManifestDigest != expectedManifestDigest {
                return false
            }
            if let expectedLanguage = expected.language, language != expectedLanguage { return false }
            if let expectedFingerprint = expected.sourceAudioFingerprint,
               sourceAudioFingerprint != expectedFingerprint {
                return false
            }
            if let expectedTranscriptHash = expected.transcriptHash,
               transcriptHash != expectedTranscriptHash {
                return false
            }
            if let expectedHasTranscript = expected.hasTranscript,
               hasTranscript != expectedHasTranscript {
                return false
            }
            if let expectedXVectorOnlyMode = expected.xVectorOnlyMode,
               xVectorOnlyMode != expectedXVectorOnlyMode {
                return false
            }
            if let expectedRuntimeSignature = expected.qwen3RuntimeProfileSignature,
               qwen3RuntimeProfileSignature != expectedRuntimeSignature {
                return false
            }
            return true
        }

        public func fillingCreatedAtIfNeeded() -> ArtifactMetadata {
            guard createdAt == nil else { return self }
            return ArtifactMetadata(
                modelID: modelID,
                modelRepository: modelRepository,
                modelRevision: modelRevision,
                modelArtifactVersion: modelArtifactVersion,
                modelIntegrityManifestDigest: modelIntegrityManifestDigest,
                language: language,
                sourceAudioFingerprint: sourceAudioFingerprint,
                transcriptHash: transcriptHash,
                hasTranscript: hasTranscript,
                xVectorOnlyMode: xVectorOnlyMode,
                qwen3RuntimeProfileSignature: qwen3RuntimeProfileSignature,
                createdAt: ISO8601DateFormatter().string(from: Date())
            )
        }
    }

    public struct Manifest: Codable, Sendable {
        public let schemaVersion: Int
        public let speakerFeatureVersion: String
        public let refText: String?
        public let xVectorOnlyMode: Bool
        public let iclMode: Bool
        public let artifactMetadata: ArtifactMetadata?
    }

    public struct ArtifactFileIntegrity: Codable, Hashable, Sendable {
        public let byteCount: Int
        public let sha256: String
        public let tensorKey: String?
        public let shape: [Int]?
        public let dataType: String?
    }

    public struct IntegrityManifest: Codable, Hashable, Sendable {
        public let schemaVersion: Int
        public let files: [String: ArtifactFileIntegrity]
    }

    /// Schema 3 makes the speaker-feature algorithm part of every persisted
    /// artifact, including low-level loads without app-owned metadata.
    public static let schemaVersion = 3
    /// Conditioning-pipeline identity persisted in the manifest's
    /// speaker-feature field. It composes the speaker mel-frontend algorithm
    /// version, the ICL reference-encode preprocessing version and the MLX
    /// build that computed the stored tensors, so a change to any of them
    /// rejects stale artifacts at load and the host rebuilds them fail-closed
    /// from the source reference.
    public static let speakerFeatureVersion =
        "\(Qwen3TTSSpeakerMelFrontend.featureVersion)+\(Qwen3TTSReferenceAudio.codecEncodeConditioningVersion)"
            + "+\(mlxNumericsVersion)"
    /// F-06 (engine audit 2026-10-16): the MLX build behind stored speaker
    /// embeddings and reference codes. An MLX move can change their numerics,
    /// so artifacts built on another one rebuild once instead of being
    /// reused. It names the exact mlx-swift pin and moves with it;
    /// `scripts/qwen3_core_contract.py` checks it against COMPATIBILITY.json.
    static let mlxNumericsVersion = "mlx-swift-0.32.3"
    public static let integritySchemaVersion = 1
    public static let integrityFilename = "integrity.json"
    public let refCodes: MLXArray?
    public let speakerEmbedding: MLXArray?
    public let refText: String?
    public let xVectorOnlyMode: Bool
    public let iclMode: Bool
    public let artifactMetadata: ArtifactMetadata?

    public init(
        refCodes: MLXArray?,
        speakerEmbedding: MLXArray?,
        refText: String?,
        xVectorOnlyMode: Bool,
        iclMode: Bool,
        artifactMetadata: ArtifactMetadata? = nil
    ) {
        self.refCodes = refCodes
        self.speakerEmbedding = speakerEmbedding
        self.refText = refText
        self.xVectorOnlyMode = xVectorOnlyMode
        self.iclMode = iclMode
        self.artifactMetadata = artifactMetadata
    }

    public func withArtifactMetadata(_ metadata: ArtifactMetadata?) -> Qwen3TTSVoiceClonePrompt {
        Qwen3TTSVoiceClonePrompt(
            refCodes: refCodes,
            speakerEmbedding: speakerEmbedding,
            refText: refText,
            xVectorOnlyMode: xVectorOnlyMode,
            iclMode: iclMode,
            artifactMetadata: metadata
        )
    }

    public func write(to directory: URL, artifactMetadata: ArtifactMetadata? = nil) throws {
        let fileManager = FileManager.default
        try fileManager.createDirectory(at: directory, withIntermediateDirectories: true)

        let validatedSpeakerEmbedding: MLXArray? = if let speakerEmbedding {
            try Self.validateSpeakerEmbedding(
                speakerEmbedding,
                expectedDimension: speakerEmbedding.ndim == 2 ? speakerEmbedding.dim(1) : -1,
                allowOfficialVectorShape: false
            )
        } else {
            nil
        }

        let metadata = (artifactMetadata ?? self.artifactMetadata)?.fillingCreatedAtIfNeeded()
        let manifest = Manifest(
            schemaVersion: Self.schemaVersion,
            speakerFeatureVersion: Self.speakerFeatureVersion,
            refText: refText,
            xVectorOnlyMode: xVectorOnlyMode,
            iclMode: iclMode,
            artifactMetadata: metadata
        )
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        try encoder.encode(manifest).write(
            to: directory.appendingPathComponent("manifest.json"),
            options: .atomic
        )

        let refCodesURL = directory.appendingPathComponent("ref_codes.safetensors")
        let speakerEmbeddingURL = directory.appendingPathComponent("speaker_embedding.safetensors")

        if let refCodes {
            try MLX.save(arrays: ["ref_codes": refCodes], url: refCodesURL)
        } else if fileManager.fileExists(atPath: refCodesURL.path) {
            try fileManager.removeItem(at: refCodesURL)
        }

        if let validatedSpeakerEmbedding {
            try MLX.save(arrays: ["speaker_embedding": validatedSpeakerEmbedding], url: speakerEmbeddingURL)
        } else if fileManager.fileExists(atPath: speakerEmbeddingURL.path) {
            try fileManager.removeItem(at: speakerEmbeddingURL)
        }

        var integrityFiles: [String: ArtifactFileIntegrity] = [:]
        integrityFiles["manifest.json"] = try Self.integrity(for: directory.appendingPathComponent("manifest.json"))
        if let refCodes {
            integrityFiles["ref_codes.safetensors"] = try Self.integrity(
                for: refCodesURL,
                tensorKey: "ref_codes",
                array: refCodes
            )
        }
        if let validatedSpeakerEmbedding {
            integrityFiles["speaker_embedding.safetensors"] = try Self.integrity(
                for: speakerEmbeddingURL,
                tensorKey: "speaker_embedding",
                array: validatedSpeakerEmbedding
            )
        }
        let integrityManifest = IntegrityManifest(
            schemaVersion: Self.integritySchemaVersion,
            files: integrityFiles
        )
        try encoder.encode(integrityManifest).write(
            to: directory.appendingPathComponent(Self.integrityFilename),
            options: .atomic
        )
    }

    /// Publishes a complete artifact directory with atomic replacement semantics.
    /// A failed staging write never mutates the previously published artifact.
    public func writeAtomically(
        to directory: URL,
        artifactMetadata: ArtifactMetadata? = nil,
        beforePublish: (() throws -> Void)? = nil
    ) throws {
        let fileManager = FileManager.default
        let parent = directory.deletingLastPathComponent()
        try fileManager.createDirectory(at: parent, withIntermediateDirectories: true)
        let staging = parent.appendingPathComponent(
            ".\(directory.lastPathComponent).staging.\(UUID().uuidString)",
            isDirectory: true
        )
        defer { try? fileManager.removeItem(at: staging) }
        try write(to: staging, artifactMetadata: artifactMetadata)
        try beforePublish?()

        if fileManager.fileExists(atPath: directory.path) {
            _ = try fileManager.replaceItemAt(
                directory,
                withItemAt: staging,
                backupItemName: nil,
                options: []
            )
        } else {
            try fileManager.moveItem(at: staging, to: directory)
        }
    }

    public static func load(
        from directory: URL,
        expectedMetadata: ArtifactMetadata? = nil
    ) throws -> Qwen3TTSVoiceClonePrompt {
        let integrity = try Self.validateIntegrity(in: directory)
        let manifestURL = directory.appendingPathComponent("manifest.json")
        let manifest = try JSONDecoder().decode(
            Manifest.self,
            from: Data(contentsOf: manifestURL)
        )
        guard manifest.schemaVersion == schemaVersion else {
            throw AudioGenerationError.modelNotInitialized(
                "Unsupported Qwen3 clone prompt artifact version: \(manifest.schemaVersion)"
            )
        }
        guard manifest.speakerFeatureVersion == speakerFeatureVersion else {
            throw AudioGenerationError.modelNotInitialized(
                "Qwen3 clone prompt speaker-feature version no longer matches the runtime."
            )
        }
        if let expectedMetadata,
           manifest.artifactMetadata?.matches(expectedMetadata) != true {
            throw AudioGenerationError.modelNotInitialized(
                "Qwen3 clone prompt artifact metadata no longer matches the selected model/reference."
            )
        }

        let refCodesURL = directory.appendingPathComponent("ref_codes.safetensors")
        let speakerEmbeddingURL = directory.appendingPathComponent("speaker_embedding.safetensors")

        let refCodes = try Self.loadSingleArray(
            named: "ref_codes",
            from: refCodesURL,
            expected: integrity.files["ref_codes.safetensors"]
        )
        let loadedSpeakerEmbedding = try Self.loadSingleArray(
            named: "speaker_embedding",
            from: speakerEmbeddingURL,
            expected: integrity.files["speaker_embedding.safetensors"]
        )
        let speakerEmbedding: MLXArray? = if let loadedSpeakerEmbedding {
            try Self.validateSpeakerEmbedding(
                loadedSpeakerEmbedding,
                expectedDimension: loadedSpeakerEmbedding.ndim == 2 ? loadedSpeakerEmbedding.dim(1) : -1,
                allowOfficialVectorShape: false
            )
        } else {
            nil
        }

        if manifest.xVectorOnlyMode, speakerEmbedding == nil {
            throw AudioGenerationError.modelNotInitialized(
                "Qwen3 clone prompt x-vector mode requires a speaker embedding."
            )
        }
        if manifest.iclMode {
            guard refCodes != nil,
                  manifest.refText?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty == false else {
                throw AudioGenerationError.modelNotInitialized(
                    "Qwen3 clone prompt ICL mode requires reference codes and reference text."
                )
            }
        }

        return Qwen3TTSVoiceClonePrompt(
            refCodes: refCodes,
            speakerEmbedding: speakerEmbedding,
            refText: manifest.refText,
            xVectorOnlyMode: manifest.xVectorOnlyMode,
            iclMode: manifest.iclMode,
            artifactMetadata: manifest.artifactMetadata
        )
    }

    static func validateSpeakerEmbedding(
        _ embedding: MLXArray,
        expectedDimension: Int,
        allowOfficialVectorShape: Bool
    ) throws -> MLXArray {
        guard expectedDimension > 0 else {
            throw AudioGenerationError.invalidInput(
                "Qwen speaker embedding dimension must be positive."
            )
        }
        guard embedding.dtype == .float32 else {
            throw AudioGenerationError.invalidInput(
                "Qwen speaker embedding must use float32 storage."
            )
        }

        let canonical: MLXArray
        if embedding.shape == [1, expectedDimension] {
            canonical = embedding
        } else if allowOfficialVectorShape, embedding.shape == [expectedDimension] {
            canonical = embedding.reshaped(1, expectedDimension)
        } else {
            throw AudioGenerationError.invalidInput(
                "Qwen speaker embedding must have shape [1, \(expectedDimension)]."
            )
        }

        // BG-01 / F-01: a 1 x D check needs no Metal work. On the CPU stream,
        // adopting a stored artifact (where this eval also loads the embedding
        // from disk) submits no command buffer iOS could refuse in the background.
        let allFinite = isFinite(canonical, stream: .cpu).all(stream: .cpu)
        eval(canonical, allFinite)
        guard allFinite.item(Bool.self) else {
            throw AudioGenerationError.invalidInput(
                "Qwen speaker embedding contains a non-finite value."
            )
        }
        return canonical
    }

    private static func loadSingleArray(
        named key: String,
        from url: URL,
        expected: ArtifactFileIntegrity?
    ) throws -> MLXArray? {
        guard FileManager.default.fileExists(atPath: url.path) else {
            guard expected == nil else {
                throw AudioGenerationError.modelNotInitialized("Qwen3 clone prompt artifact is missing \(url.lastPathComponent).")
            }
            return nil
        }
        let arrays = try MLX.loadArrays(url: url)
        guard arrays.count == 1, let array = arrays[key] else {
            throw AudioGenerationError.modelNotInitialized(
                "Qwen3 clone prompt artifact \(url.lastPathComponent) must contain only tensor '\(key)'."
            )
        }
        if let expected {
            guard expected.tensorKey == key,
                  expected.shape == array.shape,
                  expected.dataType == String(describing: array.dtype) else {
                throw AudioGenerationError.modelNotInitialized(
                    "Qwen3 clone prompt tensor metadata does not match \(url.lastPathComponent)."
                )
            }
        }
        return array
    }

    private static func integrity(
        for url: URL,
        tensorKey: String? = nil,
        array: MLXArray? = nil
    ) throws -> ArtifactFileIntegrity {
        let data = try Data(contentsOf: url, options: [.mappedIfSafe])
        return ArtifactFileIntegrity(
            byteCount: data.count,
            sha256: SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined(),
            tensorKey: tensorKey,
            shape: array?.shape,
            dataType: array.map { String(describing: $0.dtype) }
        )
    }

    private static func validateIntegrity(in directory: URL) throws -> IntegrityManifest {
        let integrityURL = directory.appendingPathComponent(Self.integrityFilename)
        let integrity = try JSONDecoder().decode(
            IntegrityManifest.self,
            from: Data(contentsOf: integrityURL)
        )
        guard integrity.schemaVersion == Self.integritySchemaVersion else {
            throw AudioGenerationError.modelNotInitialized(
                "Unsupported Qwen3 clone prompt integrity version: \(integrity.schemaVersion)"
            )
        }
        let actualFiles = Set(
            try FileManager.default.contentsOfDirectory(atPath: directory.path)
                .filter { $0 != Self.integrityFilename }
        )
        guard actualFiles == Set(integrity.files.keys) else {
            throw AudioGenerationError.modelNotInitialized(
                "Qwen3 clone prompt artifact contains a missing or unexpected file."
            )
        }
        for (filename, expected) in integrity.files {
            let actual = try Self.integrity(for: directory.appendingPathComponent(filename))
            guard actual.byteCount == expected.byteCount,
                  actual.sha256 == expected.sha256 else {
                throw AudioGenerationError.modelNotInitialized(
                    "Qwen3 clone prompt artifact failed integrity verification for \(filename)."
                )
            }
        }
        return integrity
    }
}
