@preconcurrency import AVFoundation
import Foundation
@testable import QwenVoiceCore
import XCTest

final class CloneConditioningContractTests: XCTestCase {
    func testMissingEmptyAndWhitespaceTranscriptsUseXVectorOnly() {
        for transcript in [nil, "", "  \n\t"] as [String?] {
            let reference = CloneReference(
                audioPath: "reference.wav",
                transcript: transcript
            )
            XCTAssertEqual(reference.conditioningMode, .xVectorOnly)
            XCTAssertNil(reference.transcript)
        }
    }

    func testTranscriptBackedModeNormalizesText() {
        let reference = CloneReference(
            audioPath: "reference.wav",
            conditioningMode: .transcriptBacked("  Reference words. \n")
        )

        XCTAssertEqual(
            reference.conditioningMode,
            .transcriptBacked("Reference words.")
        )
        XCTAssertEqual(reference.transcript, "Reference words.")
    }

    func testCloneReferenceCodablePreservesModernAndLegacyWireForms() throws {
        let modern = CloneReference(
            audioPath: "reference.wav",
            conditioningMode: .xVectorOnly,
            preparedVoiceID: "fixture-voice"
        )
        let modernData = try JSONEncoder().encode(modern)
        XCTAssertEqual(try JSONDecoder().decode(CloneReference.self, from: modernData), modern)

        let legacyData = try XCTUnwrap(
            """
            {
              "audioPath": "reference.wav",
              "transcript": "Legacy transcript.",
              "preparedVoiceID": "fixture-voice"
            }
            """.data(using: .utf8)
        )
        let legacy = try JSONDecoder().decode(CloneReference.self, from: legacyData)
        XCTAssertEqual(legacy.conditioningMode, .transcriptBacked("Legacy transcript."))
    }

    func testConflictingLegacyAndTypedConditioningFailsClosed() throws {
        let data = try XCTUnwrap(
            """
            {
              "audioPath": "reference.wav",
              "transcript": "Contradictory transcript.",
              "conditioningMode": { "kind": "x_vector_only" }
            }
            """.data(using: .utf8)
        )

        XCTAssertThrowsError(try JSONDecoder().decode(CloneReference.self, from: data))
    }

    func testCloneCacheIdentityIncludesConditioningMode() {
        let xVectorKey = GenerationSemantics.cloneReferenceIdentityKey(
            modelID: "pro_clone_speed",
            refAudio: "reference.wav",
            refText: nil
        )
        let transcriptKey = GenerationSemantics.cloneReferenceIdentityKey(
            modelID: "pro_clone_speed",
            refAudio: "reference.wav",
            refText: "Reference words."
        )

        XCTAssertNotEqual(xVectorKey, transcriptKey)
        XCTAssertTrue(xVectorKey.contains("|x_vector_only|"))
        XCTAssertTrue(transcriptKey.contains("|transcript_backed|"))
    }

    func testCloneIdentityCannotAliasWhenInputsContainLegacySeparators() {
        let left = GenerationSemantics.cloneReferenceIdentity(
            modelID: "pro_clone_speed",
            refAudio: "reference|part.wav",
            refText: "spoken words"
        )
        let right = GenerationSemantics.cloneReferenceIdentity(
            modelID: "pro_clone_speed",
            refAudio: "reference",
            refText: "part.wav|spoken words"
        )

        XCTAssertEqual(left.legacyKey, right.legacyKey)
        XCTAssertNotEqual(left, right)
        XCTAssertNotEqual(left.canonicalSerialization, right.canonicalSerialization)
        XCTAssertNotEqual(left.digest, right.digest)
        XCTAssertEqual(Set([left, right]).count, 2)
    }

    func testInternalCloneIdentityKeepsPathAndFingerprintSeparate() {
        let left = GenerationSemantics.internalCloneReferenceIdentity(
            modelID: "pro_clone_speed",
            normalizedReferencePath: "reference#part.wav",
            referenceFingerprint: "abc",
            conditioningMode: .xVectorOnly
        )
        let right = GenerationSemantics.internalCloneReferenceIdentity(
            modelID: "pro_clone_speed",
            normalizedReferencePath: "reference",
            referenceFingerprint: "part.wav#abc",
            conditioningMode: .xVectorOnly
        )

        XCTAssertEqual(left.legacyKey, right.legacyKey)
        XCTAssertNotEqual(left, right)
        XCTAssertNotEqual(left.canonicalSerialization, right.canonicalSerialization)
        XCTAssertNotEqual(left.cacheKey, right.cacheKey)
    }

    func testClonePromptIdentityInvalidatesForSpeakerFrontendAndRuntimeChanges() throws {
        let reference = GenerationSemantics.internalCloneReferenceIdentity(
            modelID: "pro_clone_speed",
            normalizedReferencePath: "reference.wav",
            referenceFingerprint: "audio-digest",
            conditioningMode: .xVectorOnly
        )
        let baseline = GenerationSemantics.ClonePromptIdentity(
            referenceIdentity: reference,
            language: "English",
            modelArtifactIdentity: try clonePromptModelArtifactIdentity(),
            qwenRuntimeProfileSignature: "runtime-a",
            speakerFeatureVersion: "qwen-speaker-mel-v1"
        )
        let changedFrontend = GenerationSemantics.ClonePromptIdentity(
            referenceIdentity: reference,
            language: "English",
            modelArtifactIdentity: try clonePromptModelArtifactIdentity(),
            qwenRuntimeProfileSignature: "runtime-a",
            speakerFeatureVersion: "qwen-speaker-mel-v2"
        )
        let changedRuntime = GenerationSemantics.ClonePromptIdentity(
            referenceIdentity: reference,
            language: "English",
            modelArtifactIdentity: try clonePromptModelArtifactIdentity(),
            qwenRuntimeProfileSignature: "runtime-b",
            speakerFeatureVersion: "qwen-speaker-mel-v1"
        )

        XCTAssertNotEqual(baseline.runtimeContractSignature, changedFrontend.runtimeContractSignature)
        XCTAssertNotEqual(baseline.runtimeContractSignature, changedRuntime.runtimeContractSignature)
        XCTAssertNotEqual(baseline.cacheKey, changedFrontend.cacheKey)
        XCTAssertNotEqual(baseline.cacheKey, changedRuntime.cacheKey)
    }

    func testClonePromptIdentityInvalidatesForEachModelArtifactField() throws {
        let reference = GenerationSemantics.internalCloneReferenceIdentity(
            modelID: "pro_clone_speed",
            normalizedReferencePath: "reference.wav",
            referenceFingerprint: "audio-digest",
            conditioningMode: .xVectorOnly
        )
        let baselineArtifact = try clonePromptModelArtifactIdentity()
        let changedArtifacts = [
            try clonePromptModelArtifactIdentity(repository: "other/model"),
            try clonePromptModelArtifactIdentity(revision: String(repeating: "b", count: 40)),
            try clonePromptModelArtifactIdentity(artifactVersion: "artifact-v2"),
            try clonePromptModelArtifactIdentity(integrityDigest: String(repeating: "b", count: 64)),
        ]
        let baseline = GenerationSemantics.ClonePromptIdentity(
            referenceIdentity: reference,
            language: "english",
            modelArtifactIdentity: baselineArtifact,
            qwenRuntimeProfileSignature: "runtime",
            speakerFeatureVersion: "qwen-speaker-mel-v1"
        )

        for changedArtifact in changedArtifacts {
            let changed = GenerationSemantics.ClonePromptIdentity(
                referenceIdentity: reference,
                language: "english",
                modelArtifactIdentity: changedArtifact,
                qwenRuntimeProfileSignature: "runtime",
                speakerFeatureVersion: "qwen-speaker-mel-v1"
            )
            XCTAssertNotEqual(baseline.runtimeContractSignature, changed.runtimeContractSignature)
            XCTAssertNotEqual(baseline.cacheKey, changed.cacheKey)
        }
    }

    func testClonePromptModelArtifactIdentityFailsClosedWithoutImmutableFields() {
        XCTAssertNil(GenerationSemantics.ClonePromptModelArtifactIdentity(
            repository: "mlx-community/model",
            revision: "main",
            artifactVersion: "artifact-v1",
            integrityManifestDigest: String(repeating: "a", count: 64)
        ))
        XCTAssertNil(GenerationSemantics.ClonePromptModelArtifactIdentity(
            repository: "mlx-community/model",
            revision: String(repeating: "a", count: 40),
            artifactVersion: "artifact-v1",
            integrityManifestDigest: nil
        ))
    }

    func testClonePromptIdentityNormalizesLanguageAndEmptyRuntimeSignature() throws {
        let reference = GenerationSemantics.internalCloneReferenceIdentity(
            modelID: "pro_clone_speed",
            normalizedReferencePath: "reference.wav",
            referenceFingerprint: "audio-digest",
            conditioningMode: .transcriptBacked("Reference words.")
        )
        let normalized = GenerationSemantics.ClonePromptIdentity(
            referenceIdentity: reference,
            language: " English ",
            modelArtifactIdentity: try clonePromptModelArtifactIdentity(),
            qwenRuntimeProfileSignature: " ",
            speakerFeatureVersion: " qwen-speaker-mel-v1 "
        )
        let canonical = GenerationSemantics.ClonePromptIdentity(
            referenceIdentity: reference,
            language: "english",
            modelArtifactIdentity: try clonePromptModelArtifactIdentity(),
            qwenRuntimeProfileSignature: nil,
            speakerFeatureVersion: "qwen-speaker-mel-v1"
        )

        XCTAssertEqual(normalized, canonical)
        XCTAssertEqual(normalized.cacheKey, canonical.cacheKey)
        XCTAssertTrue(normalized.runtimeContractSignature.hasPrefix("qv-clone-prompt-runtime-v2-"))
    }

    func testClonePromptIdentityIncludesLanguage() throws {
        let reference = GenerationSemantics.internalCloneReferenceIdentity(
            modelID: "pro_clone_speed",
            normalizedReferencePath: "reference.wav",
            referenceFingerprint: "audio-digest",
            conditioningMode: .xVectorOnly
        )
        let english = GenerationSemantics.ClonePromptIdentity(
            referenceIdentity: reference,
            language: "english",
            modelArtifactIdentity: try clonePromptModelArtifactIdentity(),
            qwenRuntimeProfileSignature: "runtime",
            speakerFeatureVersion: "qwen-speaker-mel-v1"
        )
        let french = GenerationSemantics.ClonePromptIdentity(
            referenceIdentity: reference,
            language: "french",
            modelArtifactIdentity: try clonePromptModelArtifactIdentity(),
            qwenRuntimeProfileSignature: "runtime",
            speakerFeatureVersion: "qwen-speaker-mel-v1"
        )

        XCTAssertNotEqual(english.cacheKey, french.cacheKey)
        XCTAssertEqual(english.runtimeContractSignature, french.runtimeContractSignature)
    }

    private func clonePromptModelArtifactIdentity(
        repository: String = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-4bit",
        revision: String = String(repeating: "a", count: 40),
        artifactVersion: String = "artifact-v1",
        integrityDigest: String = String(repeating: "a", count: 64)
    ) throws -> GenerationSemantics.ClonePromptModelArtifactIdentity {
        try XCTUnwrap(GenerationSemantics.ClonePromptModelArtifactIdentity(
            repository: repository,
            revision: revision,
            artifactVersion: artifactVersion,
            integrityManifestDigest: integrityDigest
        ))
    }

    func testPrewarmIdentityCannotAliasAcrossDelimiterContainingFields() {
        let left = GenerationSemantics.PrewarmIdentity.customRequest(
            modelID: "model|custom",
            language: "english",
            speakerID: "speaker",
            instruction: "calm"
        )
        let right = GenerationSemantics.PrewarmIdentity.customRequest(
            modelID: "model",
            language: "custom|english",
            speakerID: "speaker",
            instruction: "calm"
        )

        XCTAssertEqual(left.legacyKey, right.legacyKey)
        XCTAssertNotEqual(left, right)
        XCTAssertNotEqual(left.canonicalSerialization, right.canonicalSerialization)
        XCTAssertNotEqual(left.cacheKey, right.cacheKey)
    }

    func testDesignConditioningIdentityCannotAliasAcrossNestedLegacyKey() {
        let left = GenerationSemantics.DesignConditioningIdentity(
            modelID: "pro_design_speed",
            language: "english|steady",
            instruction: "narrator",
            bucket: .short
        )
        let right = GenerationSemantics.DesignConditioningIdentity(
            modelID: "pro_design_speed",
            language: "english",
            instruction: "steady|narrator",
            bucket: .short
        )

        XCTAssertEqual(left.legacyKey, right.legacyKey)
        XCTAssertNotEqual(left, right)
        XCTAssertNotEqual(left.canonicalSerialization, right.canonicalSerialization)
        XCTAssertNotEqual(left.cacheKey, right.cacheKey)
    }

    func testGenerationSessionIdentityCannotAliasCustomDelimiterFields() {
        let left = GenerationSemantics.GenerationSessionIdentity.custom(
            modelID: "pro_custom_speed",
            language: "english",
            speakerID: "speaker|calm",
            deliveryStyle: "clear"
        )
        let right = GenerationSemantics.GenerationSessionIdentity.custom(
            modelID: "pro_custom_speed",
            language: "english",
            speakerID: "speaker",
            deliveryStyle: "calm|clear"
        )

        XCTAssertNotEqual(left, right)
        XCTAssertNotEqual(left.canonicalSerialization, right.canonicalSerialization)
        XCTAssertNotEqual(left.digest, right.digest)
        XCTAssertNotEqual(left.sessionKey, right.sessionKey)
        XCTAssertEqual(left.digest.count, 64)
    }

    func testGenerationSessionIdentityCannotAliasCloneDelimiterFields() {
        let left = GenerationSemantics.GenerationSessionIdentity.clone(
            modelID: "pro_clone_speed",
            language: "english",
            audioPath: "reference|words.wav",
            conditioningMode: .transcriptBacked("hello"),
            preparedVoiceID: "voice"
        )
        let right = GenerationSemantics.GenerationSessionIdentity.clone(
            modelID: "pro_clone_speed",
            language: "english",
            audioPath: "reference",
            conditioningMode: .transcriptBacked("words.wav|hello"),
            preparedVoiceID: "voice"
        )

        XCTAssertNotEqual(left, right)
        XCTAssertNotEqual(left.canonicalSerialization, right.canonicalSerialization)
        XCTAssertNotEqual(left.digest, right.digest)
        XCTAssertNotEqual(left.sessionKey, right.sessionKey)
    }

    func testGenerationSessionIdentityPreservesOptionalPresence() {
        let absent = GenerationSemantics.GenerationSessionIdentity.custom(
            modelID: "pro_custom_speed",
            language: "english",
            speakerID: "aiden",
            deliveryStyle: nil
        )
        let presentButEmpty = GenerationSemantics.GenerationSessionIdentity.custom(
            modelID: "pro_custom_speed",
            language: "english",
            speakerID: "aiden",
            deliveryStyle: ""
        )

        XCTAssertNotEqual(absent.canonicalSerialization, presentButEmpty.canonicalSerialization)
        XCTAssertNotEqual(absent.digest, presentButEmpty.digest)
        XCTAssertNotEqual(absent.sessionKey, presentButEmpty.sessionKey)
    }

    func testPromptCreationContractRoutesBothModesWithoutFallback() {
        let xVector = NativeClonePromptCreationContract(conditioningMode: .xVectorOnly)
        XCTAssertNil(xVector.refText)
        XCTAssertTrue(xVector.xVectorOnlyMode)

        let transcriptBacked = NativeClonePromptCreationContract(
            conditioningMode: .transcriptBacked("Reference words.")
        )
        XCTAssertEqual(transcriptBacked.refText, "Reference words.")
        XCTAssertFalse(transcriptBacked.xVectorOnlyMode)
    }

    func testContractExplicitlyDeclaresXVectorSupportOnlyForCloneModels() throws {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let registry = try ContractBackedModelRegistry(
            manifestURL: root.appendingPathComponent("Sources/Resources/qwenvoice_contract.json")
        )

        for model in registry.models {
            let capabilities = try XCTUnwrap(model.qwen3Capabilities)
            XCTAssertEqual(
                capabilities.supportsXVectorOnlyClone,
                model.mode == .clone,
                "unexpected x-vector-only capability for \(model.id)"
            )
            for variant in model.variants {
                let variantCapabilities = try XCTUnwrap(variant.qwen3Capabilities)
                XCTAssertEqual(
                    variantCapabilities.supportsXVectorOnlyClone,
                    model.mode == .clone,
                    "unexpected x-vector-only capability for \(model.id)/\(variant.id)"
                )
            }
        }
    }

    /// PA-22 / CORE-04: a reference that needs conversion (here 48 kHz) is
    /// normalized once. The output is named by source content, and both the
    /// in-memory entry and the on-disk output are reused by that same
    /// fingerprint, so `reusedNormalizedReference` reports the reuse that
    /// actually happened.
    func testConvertedCloneReferenceReusesItsContentNamedOutput() async throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("vocello-clone-reuse-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let source = root.appendingPathComponent("reference.wav")
        try Self.writeSineWAV(sampleRate: 48_000, seconds: 1, to: source)
        let normalizedDirectory = root.appendingPathComponent("normalized", isDirectory: true)
        let counter = PreparationCallCounter()
        let service = CountingAudioPreparationService(
            base: NativeAudioPreparationService(),
            counter: counter
        )
        let reference = CloneReference(audioPath: source.path)
        func resolve(
            with cache: NativePreparedCloneConditioningCache
        ) async throws -> ResolvedCloneConditioning {
            try await cache.resolve(
                modelID: "clone-fixture",
                reference: reference,
                sampleRate: 24_000,
                audioPreparationService: service,
                normalizedCloneReferenceDirectory: normalizedDirectory
            )
        }

        let first = try await resolve(with: NativePreparedCloneConditioningCache(capacity: 4))
        XCTAssertFalse(first.normalizedReference.wasAlreadyCanonical)
        XCTAssertFalse(first.reusedNormalizedReference)
        let output = first.normalizedReference.normalizedURL
        let contentFingerprint = try NativePreparedCloneConditioningCache.stableCloneReferenceFingerprint(
            for: source
        )
        XCTAssertTrue(output.lastPathComponent.contains(contentFingerprint))

        // Age the output so a re-conversion (which rewrites it) is observable.
        let aged = Date(timeIntervalSince1970: 1_000_000_000)
        try FileManager.default.setAttributes([.modificationDate: aged], ofItemAtPath: output.path)

        // A fresh cache (next launch, or after a trim) reuses the file on disk.
        let second = try await resolve(with: NativePreparedCloneConditioningCache(capacity: 4))
        XCTAssertTrue(second.reusedNormalizedReference)
        XCTAssertEqual(second.normalizedReference.normalizedPath, output.path)
        let secondModified = try XCTUnwrap(
            FileManager.default.attributesOfItem(atPath: output.path)[.modificationDate] as? Date
        )
        XCTAssertEqual(secondModified.timeIntervalSince1970, aged.timeIntervalSince1970, accuracy: 1)
        let callsAfterSecond = await counter.count
        XCTAssertEqual(callsAfterSecond, 2)

        // One cache instance reuses its in-memory entry without preparing again.
        let cache = NativePreparedCloneConditioningCache(capacity: 4)
        _ = try await resolve(with: cache)
        let callsBeforeRepeat = await counter.count
        let repeated = try await resolve(with: cache)
        let callsAfterRepeat = await counter.count
        XCTAssertEqual(callsAfterRepeat, callsBeforeRepeat)
        XCTAssertTrue(repeated.reusedNormalizedReference)
        XCTAssertEqual(repeated.normalizedReference.normalizedPath, output.path)
    }

    /// PA-22 / CORE-04: conversion used to write the content-named output in
    /// place, so an interrupted conversion left a canonical header without
    /// frames (or an empty file) that the name-based reuse accepted for good.
    /// Such a file is not reused, and a conversion lands through a hidden
    /// temporary file renamed into place, leaving no temporary behind.
    func testPartialNormalizedReferenceIsNotReused() async throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("vocello-clone-partial-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let source = root.appendingPathComponent("reference.wav")
        try Self.writeSineWAV(sampleRate: 48_000, seconds: 1, to: source)
        let normalizedDirectory = root.appendingPathComponent("normalized", isDirectory: true)
        try FileManager.default.createDirectory(at: normalizedDirectory, withIntermediateDirectories: true)
        let fingerprint = try NativePreparedCloneConditioningCache.stableCloneReferenceFingerprint(for: source)
        let output = normalizedDirectory.appendingPathComponent(
            NativePreparedCloneConditioningCache.stableNormalizedCloneReferenceFileName(
                for: source,
                referenceFingerprint: fingerprint
            )
        )

        try Self.writeCanonicalHeaderOnlyWAV(to: output)
        XCTAssertTrue(NativeAudioPreparationService.isCanonicalWAV(at: output), "the header alone is canonical")
        XCTAssertFalse(NativeAudioPreparationService.canReuseExistingNormalizedOutput(
            at: output,
            fingerprint: fingerprint
        ))
        try Data().write(to: output)
        XCTAssertFalse(NativeAudioPreparationService.canReuseExistingNormalizedOutput(
            at: output,
            fingerprint: fingerprint
        ))

        let resolved = try await NativePreparedCloneConditioningCache(capacity: 4).resolve(
            modelID: "clone-fixture",
            reference: CloneReference(audioPath: source.path),
            sampleRate: 24_000,
            audioPreparationService: NativeAudioPreparationService(),
            normalizedCloneReferenceDirectory: normalizedDirectory
        )
        XCTAssertFalse(resolved.reusedNormalizedReference)
        XCTAssertEqual(resolved.normalizedReference.normalizedPath, output.path)
        XCTAssertGreaterThan(try AVAudioFile(forReading: output).length, 0)
        XCTAssertTrue(NativeAudioPreparationService.canReuseExistingNormalizedOutput(
            at: output,
            fingerprint: fingerprint
        ))
        // A conversion interrupted after its writer opened never exposes a
        // partial file at the output path, and leaves no temporary behind.
        let interruptedOutput = normalizedDirectory.appendingPathComponent("interrupted.wav")
        let interrupting = NativeAudioPreparationService(
            testingHooks: AudioPreparationTestingHooks(
                beforeWriterCreation: nil,
                beforeConversionLoop: {
                    if FileManager.default.fileExists(atPath: interruptedOutput.path) {
                        throw PartialOutputVisible()
                    }
                    throw CancellationError()
                }
            )
        )
        do {
            _ = try await interrupting.normalizeAudio(
                AudioPreparationRequest(inputURL: source, outputURL: interruptedOutput)
            )
            XCTFail("the interrupted conversion must not complete")
        } catch {
            guard case AudioPreparationError.cancelled = error else {
                return XCTFail("the output path held a partial file mid-conversion: \(error)")
            }
        }
        XCTAssertFalse(FileManager.default.fileExists(atPath: interruptedOutput.path))
        let hiddenLeftovers = try FileManager.default.contentsOfDirectory(atPath: normalizedDirectory.path)
            .filter { $0.hasPrefix(".") }
        XCTAssertEqual(hiddenLeftovers, [])
    }

    private struct PartialOutputVisible: Error {}

    /// PA-22 / CORE-05 (lifecycle half): prompts derived from one-off
    /// references are transient; only the most recently used few are kept.
    /// In-flight staging and saved-voice prompts are never touched.
    func testTransientClonePromptArtifactsKeepOnlyTheMostRecentlyUsed() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("vocello-transient-prompts-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let voices = root.appendingPathComponent("voices", isDirectory: true)
        let transientRoot = NativePreparedCloneConditioningCache.transientClonePromptRootDirectory(in: voices)
        let savedVoicePrompts = NativePreparedCloneConditioningCache.preparedVoiceClonePromptRootDirectory(
            in: voices,
            voiceID: "saved-voice"
        )
        let staging = transientRoot.appendingPathComponent(".artifact-new.staging.fixture", isDirectory: true)
        for directory in [savedVoicePrompts, staging] {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        }
        let base = Date(timeIntervalSince1970: 1_700_000_000)
        for index in 0..<10 {
            let artifact = transientRoot.appendingPathComponent(
                String(format: "artifact-%02d", index),
                isDirectory: true
            )
            try FileManager.default.createDirectory(at: artifact, withIntermediateDirectories: true)
            try Data("{}".utf8).write(to: artifact.appendingPathComponent("manifest.json"))
            try FileManager.default.setAttributes(
                [.modificationDate: base.addingTimeInterval(Double(index))],
                ofItemAtPath: artifact.path
            )
        }
        try FileManager.default.setAttributes(
            [.modificationDate: base.addingTimeInterval(-3_600)],
            ofItemAtPath: staging.path
        )

        NativePreparedCloneConditioningCache.pruneTransientClonePromptArtifacts(in: voices, retaining: 8)
        NativePreparedCloneConditioningCache.pruneTransientClonePromptArtifacts(in: voices, retaining: 8)

        let remaining = try FileManager.default.contentsOfDirectory(atPath: transientRoot.path)
            .filter { !$0.hasPrefix(".") }
            .sorted()
        XCTAssertEqual(remaining, (2..<10).map { String(format: "artifact-%02d", $0) })
        XCTAssertTrue(FileManager.default.fileExists(atPath: staging.path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: savedVoicePrompts.path))
    }

    /// A canonical (24 kHz mono 16-bit) WAV header with no audio frames: what an
    /// in-place conversion interrupted right after creating its writer left.
    private static func writeCanonicalHeaderOnlyWAV(to url: URL) throws {
        let settings: [String: Any] = [
            AVFormatIDKey: Int(kAudioFormatLinearPCM),
            AVSampleRateKey: NativeAudioPreparationService.canonicalSampleRate,
            AVNumberOfChannelsKey: Int(NativeAudioPreparationService.canonicalChannelCount),
            AVLinearPCMBitDepthKey: NativeAudioPreparationService.canonicalBitDepth,
            AVLinearPCMIsBigEndianKey: false,
            AVLinearPCMIsFloatKey: false,
        ]
        _ = try AVAudioFile(forWriting: url, settings: settings)
    }

    private static func writeSineWAV(sampleRate: Double, seconds: Double, to url: URL) throws {
        let settings: [String: Any] = [
            AVFormatIDKey: Int(kAudioFormatLinearPCM),
            AVSampleRateKey: sampleRate,
            AVNumberOfChannelsKey: 1,
            AVLinearPCMBitDepthKey: 16,
            AVLinearPCMIsBigEndianKey: false,
            AVLinearPCMIsFloatKey: false,
        ]
        let file = try AVAudioFile(forWriting: url, settings: settings)
        let frames = AVAudioFrameCount(sampleRate * seconds)
        guard let buffer = AVAudioPCMBuffer(pcmFormat: file.processingFormat, frameCapacity: frames),
              let channel = buffer.floatChannelData?.pointee else {
            throw CocoaError(.fileWriteUnknown)
        }
        buffer.frameLength = frames
        for index in 0..<Int(frames) {
            channel[index] = Float(0.2 * sin(2.0 * .pi * 220.0 * Double(index) / sampleRate))
        }
        try file.write(from: buffer)
    }
}

private actor PreparationCallCounter {
    private(set) var count = 0

    func increment() {
        count += 1
    }
}

private struct CountingAudioPreparationService: AudioPreparationService {
    let base: NativeAudioPreparationService
    let counter: PreparationCallCounter

    func normalizeAudio(_ request: AudioPreparationRequest) async throws -> AudioNormalizationResult {
        await counter.increment()
        return try await base.normalizeAudio(request)
    }
}
