import AVFoundation
import Foundation
import CryptoKit
import VocelloQwen3Core
@testable import QwenVoiceCore
import XCTest

final class CloneConditioningContractTests: XCTestCase {
    @concurrent func testCachedConditioningKeepsCurrentTranscriptOwnership() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let source = root.appendingPathComponent("Voice.wav")
        try Self.writeSineWAV(sampleRate: 24_000, seconds: 1, to: source)
        try "Same words".write(to: source.deletingPathExtension().appendingPathExtension("txt"),
                               atomically: true, encoding: .utf8)
        let cache = NativePreparedCloneConditioningCache(capacity: 4)
        for (text, expectedMode) in [("Same words", ResolvedCloneTranscriptMode.inline),
                                     (nil, .sidecar), ("Same words", .inline)] as [(String?, ResolvedCloneTranscriptMode)] {
            let resolved = try await cache.resolve(modelID: "clone", reference:
                CloneReference(audioPath: source.path, transcript: text, preparedVoiceID: "Voice"),
                sampleRate: 24_000, audioPreparationService: NativeAudioPreparationService(),
                normalizedCloneReferenceDirectory: root.appendingPathComponent("normalized"))
            XCTAssertEqual(resolved.transcriptMode, expectedMode)
            XCTAssertEqual(resolved.normalizedReference.sourceURL, source)
            XCTAssertEqual(resolved.resolvedTranscript, "Same words")
            if expectedMode == .sidecar {
                XCTAssertEqual(resolved.cloneCacheHit, true, "Exercise the shared conditioning cache")
            }
        }
    }

    func testPromptIdentityUsesHistoricalAutoArtifactWithoutWeakeningProvenance() throws {
        let reference = GenerationSemantics.internalCloneReferenceIdentity(
            modelID: "pro_clone_speed", normalizedReferencePath: "reference.wav",
            referenceFingerprint: "audio-digest", conditioningMode: .transcriptBacked("Words."))
        let artifact = try XCTUnwrap(GenerationSemantics.ClonePromptModelArtifactIdentity(
            repository: "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-4bit",
            revision: String(repeating: "a", count: 40), artifactVersion: "artifact-v1",
            integrityManifestDigest: String(repeating: "a", count: 64)))
        let identity = NativePreparedCloneConditioningCache.clonePromptIdentity(
            referenceIdentity: reference, modelArtifactIdentity: artifact, runtimeProfileSignature: "runtime")
        let historical = GenerationSemantics.ClonePromptIdentity(
            referenceIdentity: reference, language: "auto", modelArtifactIdentity: artifact,
            qwenRuntimeProfileSignature: "runtime", speakerFeatureVersion: VocelloQwen3CloneArtifactSchema.speakerFeatureVersion)
        XCTAssertEqual(identity, historical)
        XCTAssertNotEqual(identity, NativePreparedCloneConditioningCache.clonePromptIdentity(
            referenceIdentity: reference, modelArtifactIdentity: artifact, runtimeProfileSignature: "new-runtime"))
        let digest = NativePreparedCloneConditioningCache.clonePromptArtifactDigest(
            modelID: "pro_clone_speed", internalIdentityKey: reference.legacyKey)
        let previousPrimeDigest = SHA256.hash(data: Data("pro_clone_speed|\(reference.legacyKey)|auto".utf8))
            .prefix(16).map { unsafe String(format: "%02x", $0) }.joined()
        XCTAssertEqual(digest, previousPrimeDigest)
    }

    func testRawSidecarIsIgnoredWhileSavedVoiceAndExplicitTranscriptAreUsed() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let audio = root.appendingPathComponent("reference.wav")
        try "Unreviewed notes".write(to: audio.deletingPathExtension().appendingPathExtension("txt"),
                                    atomically: true, encoding: .utf8)
        let raw = CloneReference(audioPath: audio.path)
        let saved = CloneReference(audioPath: audio.path, preparedVoiceID: "Voice")
        for (reference, expected) in [(raw, nil), (saved, "Unreviewed notes")] as [(CloneReference, String?)] {
            let result = try NativePreparedCloneConditioningCache.resolveTranscript(
                requestedTranscript: nil, normalizedAudioURL: audio,
                readsSavedVoiceSidecar: NativePreparedCloneConditioningCache.readsTranscriptSidecar(for: reference))
            XCTAssertEqual(result.transcript, expected)
            XCTAssertEqual(NativePreparedCloneConditioningCache.anticipatedConditioningMode(for: reference).usesTranscript,
                           expected != nil)
        }
        let explicit = try NativePreparedCloneConditioningCache.resolveTranscript(
            requestedTranscript: "Corrected words", normalizedAudioURL: audio, readsSavedVoiceSidecar: true)
        XCTAssertEqual(explicit.transcript, "Corrected words")
        XCTAssertEqual(explicit.mode, .inline)
        let prebuild = MLXTTSEngine.savedVoicePrebuildReference(for:
            PreparedVoice(id: "Voice", name: "Voice", audioPath: audio.path, hasTranscript: true))
        XCTAssertNil(prebuild.transcript, "Stored text must not masquerade as a caller override")
        let storedPrebuild = try NativePreparedCloneConditioningCache.resolveTranscript(
            requestedTranscript: prebuild.transcript, normalizedAudioURL: audio,
            readsSavedVoiceSidecar: NativePreparedCloneConditioningCache.readsTranscriptSidecar(for: prebuild))
        XCTAssertEqual(storedPrebuild.transcript, "Unreviewed notes")
        XCTAssertEqual(storedPrebuild.mode, .sidecar)
    }

    /// G-02 through the resolver itself: on one cache, the stored-transcript
    /// request and the audio-only request for the same saved voice resolve to
    /// different conditioning, in either order, and each publishes its state
    /// under the key the Studio computes for it.
    @concurrent func testTheResolverConditionsAStatedAudioOnlyRequestOnAudioAlone() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let source = root.appendingPathComponent("Voice.wav")
        try Self.writeSineWAV(sampleRate: 24_000, seconds: 1, to: source)
        try "Stored words".write(to: source.deletingPathExtension().appendingPathExtension("txt"),
                                 atomically: true, encoding: .utf8)
        let cache = NativePreparedCloneConditioningCache(capacity: 4)
        let stored = CloneReference(audioPath: source.path, preparedVoiceID: "Voice")
        let audioOnly = CloneReference(audioPath: source.path, preparedVoiceID: "Voice", ignoresStoredTranscript: true)
        for (reference, transcript, mode) in [
            (stored, "Stored words", ResolvedCloneTranscriptMode.sidecar),
            (audioOnly, nil, ResolvedCloneTranscriptMode.none),
            (stored, "Stored words", ResolvedCloneTranscriptMode.sidecar),
        ] as [(CloneReference, String?, ResolvedCloneTranscriptMode)] {
            let resolved = try await cache.resolve(
                modelID: "clone", reference: reference, sampleRate: 24_000,
                audioPreparationService: NativeAudioPreparationService(),
                normalizedCloneReferenceDirectory: root.appendingPathComponent("normalized"))
            XCTAssertEqual(resolved.resolvedTranscript, transcript)
            XCTAssertEqual(resolved.transcriptMode, mode)
            XCTAssertEqual(resolved.conditioningMode.usesTranscript, transcript != nil)
            XCTAssertEqual(resolved.uiIdentityKey,
                           GenerationSemantics.clonePreparationKey(modelID: "clone", reference: reference))
            // The audio-only prompt is published without comparing a stored
            // transcript it never read; the stored-transcript one still compares.
            XCTAssertEqual(
                NativePreparedCloneConditioningCache.comparesStoredTranscriptBeforePublication(resolved),
                transcript != nil)
        }
        XCTAssertNotEqual(GenerationSemantics.clonePreparationKey(modelID: "clone", reference: stored),
                          GenerationSemantics.clonePreparationKey(modelID: "clone", reference: audioOnly))
        // The warm identity separates them too.
        func warm(_ reference: CloneReference) -> GenerationSemantics.PrewarmIdentity {
            GenerationSemantics.prewarmIdentity(for: GenerationRequest(
                modelID: "clone", text: "Hello.", outputPath: "/tmp/out.wav",
                payload: .clone(reference: reference)))
        }
        XCTAssertNotEqual(warm(stored), warm(audioOnly))
    }

    /// G-02: "Use audio only" on a saved voice is a request state of its own.
    /// The stored transcript the voice was saved with must not come back in
    /// its place, while requests that never stated it keep reading it.
    func testAStatedAudioOnlyRequestNeverReadsTheSavedVoicesStoredTranscript() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let audio = root.appendingPathComponent("reference.wav")
        try "Stored words".write(to: audio.deletingPathExtension().appendingPathExtension("txt"),
                                 atomically: true, encoding: .utf8)

        let stored = CloneReference(audioPath: audio.path, preparedVoiceID: "Voice")
        let audioOnly = CloneReference(audioPath: audio.path, preparedVoiceID: "Voice", ignoresStoredTranscript: true)
        XCTAssertFalse(stored.bypassesStoredTranscript)
        XCTAssertTrue(audioOnly.isExplicitlyAudioOnly)
        XCTAssertTrue(audioOnly.bypassesStoredTranscript)

        for (reference, expected, mode) in [
            (stored, "Stored words", ResolvedCloneTranscriptMode.sidecar),
            (audioOnly, nil, ResolvedCloneTranscriptMode.none),
        ] as [(CloneReference, String?, ResolvedCloneTranscriptMode)] {
            let result = try NativePreparedCloneConditioningCache.resolveTranscript(
                requestedTranscript: reference.transcript, normalizedAudioURL: audio,
                readsSavedVoiceSidecar: NativePreparedCloneConditioningCache.readsTranscriptSidecar(for: reference))
            XCTAssertEqual(result.transcript, expected)
            XCTAssertEqual(result.mode, mode)
            XCTAssertEqual(
                NativePreparedCloneConditioningCache.anticipatedConditioningMode(for: reference).usesTranscript,
                expected != nil)
        }

        // An inline transcript still wins: the flag only decides the empty case.
        let inline = CloneReference(audioPath: audio.path, transcript: "Typed words", preparedVoiceID: "Voice",
                                    ignoresStoredTranscript: true)
        XCTAssertFalse(inline.isExplicitlyAudioOnly)
        XCTAssertFalse(inline.bypassesStoredTranscript)
        XCTAssertEqual(inline.transcript, "Typed words")
    }

    /// The two requests resolve to different conditioning, so they never share
    /// a preparation key; every request that existed before keeps its key.
    func testAudioOnlyForASavedVoiceHasItsOwnKeyAndEveryOtherKeyIsUnchanged() {
        let stored = CloneReference(audioPath: "/voices/a.wav", preparedVoiceID: "Voice")
        let audioOnly = CloneReference(audioPath: "/voices/a.wav", preparedVoiceID: "Voice", ignoresStoredTranscript: true)
        let storedKey = GenerationSemantics.clonePreparationKey(modelID: "clone", reference: stored)
        let audioOnlyKey = GenerationSemantics.clonePreparationKey(modelID: "clone", reference: audioOnly)
        XCTAssertEqual(storedKey, "clone|clone|x_vector_only|/voices/a.wav|")
        XCTAssertEqual(audioOnlyKey, "clone|clone|x_vector_only|/voices/a.wav||stored-transcript-bypassed")
        XCTAssertNotEqual(
            GenerationSemantics.cloneReferenceIdentity(modelID: "clone", refAudio: "/voices/a.wav", refText: nil),
            GenerationSemantics.cloneReferenceIdentity(modelID: "clone", refAudio: "/voices/a.wav", refText: nil,
                                                       storedTranscriptBypassed: true))

        // Unchanged: a one-off reference and any inline transcript, flag or not.
        for (plain, flagged) in [
            (CloneReference(audioPath: "/tmp/one-off.wav"),
             CloneReference(audioPath: "/tmp/one-off.wav", ignoresStoredTranscript: true)),
            (CloneReference(audioPath: "/voices/a.wav", transcript: "Typed", preparedVoiceID: "Voice"),
             CloneReference(audioPath: "/voices/a.wav", transcript: "Typed", preparedVoiceID: "Voice",
                            ignoresStoredTranscript: true)),
        ] {
            XCTAssertEqual(GenerationSemantics.clonePreparationKey(modelID: "clone", reference: plain),
                           GenerationSemantics.clonePreparationKey(modelID: "clone", reference: flagged))
        }
        // A transcript-backed identity can never carry the bypass.
        XCTAssertFalse(GenerationSemantics.cloneReferenceIdentity(
            modelID: "clone", refAudio: "/voices/a.wav", refText: "Typed", storedTranscriptBypassed: true
        ).storedTranscriptBypassed)
    }

    /// Payloads written before G-02 decode with the stored transcript in
    /// force, and a request that does not set the flag encodes as it always did.
    func testTheAudioOnlyFlagIsAbsentFromEarlierPayloadsAndWrittenOnlyWhenSet() throws {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        let stored = CloneReference(audioPath: "/voices/a.wav", preparedVoiceID: "Voice")
        let storedJSON = try XCTUnwrap(String(data: encoder.encode(stored), encoding: .utf8))
        XCTAssertFalse(storedJSON.contains("ignoresStoredTranscript"))
        let legacy = Data(#"{"audioPath":"/voices/a.wav","conditioningMode":{"kind":"x_vector_only"},"preparedVoiceID":"Voice"}"#.utf8)
        let decoded = try JSONDecoder().decode(CloneReference.self, from: legacy)
        XCTAssertFalse(decoded.ignoresStoredTranscript)
        XCTAssertEqual(decoded, stored)

        let audioOnly = CloneReference(audioPath: "/voices/a.wav", preparedVoiceID: "Voice", ignoresStoredTranscript: true)
        let roundTrip = try JSONDecoder().decode(CloneReference.self, from: encoder.encode(audioOnly))
        XCTAssertEqual(roundTrip, audioOnly)
        XCTAssertTrue(roundTrip.ignoresStoredTranscript)
        XCTAssertNotEqual(roundTrip, stored)
    }

    func testPrimedCachePermitsIdleUnloadButPreparationKeepsItsModel() {
        for phase in [ClonePreparationPhase.idle, .primed] {
            XCTAssertTrue(MLXTTSEngine.idleUnloadAllowed(loadState: .loaded(modelID: "clone"), modelID: "clone",
                hasActiveModelOperation: false, clonePreparationPhase: phase))
            XCTAssertFalse(MLXTTSEngine.idleUnloadAllowed(loadState: .loaded(modelID: "clone"), modelID: "clone",
                hasActiveModelOperation: true, clonePreparationPhase: phase))
        }
        XCTAssertFalse(MLXTTSEngine.idleUnloadAllowed(loadState: .loaded(modelID: "clone"), modelID: "clone",
            hasActiveModelOperation: false, clonePreparationPhase: .preparing))
        XCTAssertEqual(MLXTTSEngine.loadCapabilityProfile(for: .clone), .cloneOnly)
        XCTAssertEqual(MLXTTSEngine.loadCapabilityProfile(for: .design), .designOnly)
        XCTAssertEqual(MLXTTSEngine.loadCapabilityProfile(for: .custom), .customOnly)
        XCTAssertEqual(MLXTTSEngine.loadCapabilityProfile(for: nil), .fullCapabilities)
    }

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

    /// G-12 and A-18: one shape for a transcript, whichever surface supplied it.
    func testEveryTranscriptSourceTakesOneConditioningShape() {
        let shaped = "First line. Second line, after a tab and a wide space."
        let raw = "  First line.\nSecond line,\tafter a tab\u{00A0}and a wide\u{3000}space. \r\n"
        XCTAssertEqual(CloneConditioningMode.conditioningText(raw), shaped)
        XCTAssertEqual(CloneConditioningMode(transcript: raw), .transcriptBacked(shaped))
        XCTAssertEqual(CloneConditioningMode.transcriptBacked(raw).transcript, shaped)
        XCTAssertEqual(NativePreparedCloneConditioningCache.normalizedTranscript(raw), shaped)
        XCTAssertEqual(ReferenceTranscriptionReviewState.conditioningLine(raw), shaped)
        for empty in [nil, "", " \n\t ", "\u{3000}"] as [String?] {
            XCTAssertNil(CloneConditioningMode.conditioningText(empty))
            XCTAssertEqual(CloneConditioningMode(transcript: empty), .xVectorOnly)
        }
        // Text already in that shape is returned scalar for scalar.
        XCTAssertEqual(
            Array(CloneConditioningMode.conditioningText(shaped)!.unicodeScalars),
            Array(shaped.unicodeScalars))
        // Decomposed text is composed, as the reference tokenizer composes it.
        // Swift compares strings by canonical equivalence, so compare scalars.
        let decomposed = "Cafe\u{301} de\u{301}ja\u{300} vu"
        XCTAssertEqual(
            Array(CloneConditioningMode.conditioningText(decomposed)!.unicodeScalars),
            Array("Caf\u{E9} d\u{E9}j\u{E0} vu".unicodeScalars))
    }

    /// G-12: a stored transcript with line breaks used to reach the CLI's
    /// `--voice` take and the prebuilt prompt verbatim, so they conditioned on
    /// different text than the Studio's take from the same voice.
    @concurrent func testAStoredTranscriptConditionsLikeTheStudiosFieldForTheSameWords() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let source = root.appendingPathComponent("Voice.wav")
        try Self.writeSineWAV(sampleRate: 24_000, seconds: 1, to: source)
        try "Stored words,\n  on two lines.\n".write(
            to: source.deletingPathExtension().appendingPathExtension("txt"), atomically: true, encoding: .utf8)
        let cache = NativePreparedCloneConditioningCache(capacity: 4)
        @concurrent func resolve(_ reference: CloneReference) async throws -> ResolvedCloneConditioning {
            try await cache.resolve(
                modelID: "clone", reference: reference, sampleRate: 24_000,
                audioPreparationService: NativeAudioPreparationService(),
                normalizedCloneReferenceDirectory: root.appendingPathComponent("normalized"))
        }
        // The CLI's `--voice` and the prebuild: the stored transcript is read.
        let stored = try await resolve(CloneReference(audioPath: source.path, preparedVoiceID: "Voice"))
        // The Studio: the field's text, shaped by the draft.
        let field = VoiceCloningDraft(
            selectedSavedVoiceID: "Voice", referenceAudioPath: source.path,
            referenceTranscript: "Stored words,\n  on two lines.\n")
        let studio = try await resolve(field.cloneReference(audioPath: source.path))
        XCTAssertEqual(stored.resolvedTranscript, "Stored words, on two lines.")
        XCTAssertEqual(studio.resolvedTranscript, stored.resolvedTranscript)
        XCTAssertEqual(studio.conditioningMode, stored.conditioningMode)
        XCTAssertEqual(studio.internalIdentity, stored.internalIdentity)
        XCTAssertEqual(
            NativePreparedCloneConditioningCache.anticipatedConditioningMode(
                for: CloneReference(audioPath: source.path, preparedVoiceID: "Voice")),
            stored.conditioningMode)
    }

    /// G-13: the reference's fingerprint carries the preparation version, and
    /// version 1 is the content digest earlier builds used.
    func testTheReferenceFingerprintCarriesThePreparationVersion() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let file = root.appendingPathComponent("reference.wav")
        try Data("abc".utf8).write(to: file)
        let contentDigest = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        XCTAssertEqual(NativeAudioPreparationService.cloneReferencePreparationVersion, 1)
        XCTAssertEqual(
            try NativePreparedCloneConditioningCache.stableCloneReferenceFingerprint(for: file), contentDigest)
        typealias Cache = NativePreparedCloneConditioningCache
        XCTAssertEqual(Cache.preparationFingerprint(contentDigest: contentDigest, version: 1), contentDigest)
        let second = Cache.preparationFingerprint(contentDigest: contentDigest, version: 2)
        XCTAssertNotEqual(second, contentDigest)
        XCTAssertEqual(second.count, 64)
        XCTAssertEqual(second, Cache.preparationFingerprint(contentDigest: contentDigest, version: 2))
        XCTAssertNotEqual(second, Cache.preparationFingerprint(contentDigest: contentDigest, version: 3))
        // A new version names a new prepared file, so the old one is never reused.
        XCTAssertNotEqual(
            Cache.stableNormalizedCloneReferenceFileName(for: file, referenceFingerprint: second),
            Cache.stableNormalizedCloneReferenceFileName(for: file, referenceFingerprint: contentDigest))
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
    @concurrent func testConvertedCloneReferenceReusesItsContentNamedOutput() async throws {
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
        @concurrent func resolve(
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
    func testStartupSweepRemovesOnlyAbandonedConversionTemporaries() throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("vocello-sweep-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let abandoned = directory.appendingPathComponent(".ref.converting-\(UUID().uuidString).wav")
        let live = directory.appendingPathComponent(".ref.converting-\(UUID().uuidString).wav")
        let output = directory.appendingPathComponent("ref.wav")
        for url in [abandoned, live, output] {
            XCTAssertTrue(FileManager.default.createFile(atPath: url.path, contents: Data([1])))
        }
        let old = Date().addingTimeInterval(-7200)
        try FileManager.default.setAttributes([.modificationDate: old], ofItemAtPath: abandoned.path)
        try FileManager.default.setAttributes([.modificationDate: old], ofItemAtPath: output.path)

        MLXTTSEngine.sweepAbandonedConversionTemporaries(in: directory)

        XCTAssertFalse(FileManager.default.fileExists(atPath: abandoned.path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: live.path), "a live conversion is kept")
        XCTAssertTrue(FileManager.default.fileExists(atPath: output.path), "completed outputs are never swept")
    }

    @concurrent func testPartialNormalizedReferenceIsNotReused() async throws {
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
                beforeConversionLoop: { @concurrent in
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
            let artifact = unsafe transientRoot.appendingPathComponent(
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
        XCTAssertEqual(remaining, (2..<10).map { unsafe String(format: "artifact-%02d", $0) })
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
              let channel = unsafe buffer.floatChannelData?.pointee else {
            throw CocoaError(.fileWriteUnknown)
        }
        buffer.frameLength = frames
        for index in 0..<Int(frames) {
            unsafe channel[index] = Float(0.2 * sin(2.0 * .pi * 220.0 * Double(index) / sampleRate))
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

    @concurrent func normalizeAudio(_ request: AudioPreparationRequest) async throws -> AudioNormalizationResult {
        await counter.increment()
        return try await base.normalizeAudio(request)
    }
}
