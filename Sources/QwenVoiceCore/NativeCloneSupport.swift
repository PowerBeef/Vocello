import CryptoKit
import AVFoundation
import Foundation
@unsafe @preconcurrency import MLX
import VocelloQwen3Core

enum ResolvedCloneTranscriptMode: String, Sendable {
    case inline
    case sidecar
    case none
}

struct NativeClonePromptCreationContract: Equatable, Sendable {
    let refText: String?
    let xVectorOnlyMode: Bool

    init(conditioningMode: CloneConditioningMode) {
        let normalized = conditioningMode.normalized
        refText = normalized.transcript
        xVectorOnlyMode = normalized.isXVectorOnly
    }
}

struct ResolvedCloneConditioning: Sendable {
    let uiIdentity: GenerationSemantics.CloneReferenceIdentity
    let internalIdentity: GenerationSemantics.CloneReferenceIdentity
    let normalizedReference: AudioNormalizationResult
    let resolvedTranscript: String?
    let transcriptMode: ResolvedCloneTranscriptMode
    let conditioningMode: CloneConditioningMode
    let referenceAudio: [Float]
    let preparedVoiceID: String?
    let cloneHandle: VocelloQwen3CloneHandle?
    let preparedCloneUsed: Bool
    let cloneCacheHit: Bool?
    let clonePromptCacheHit: Bool?
    let cloneConditioningReused: Bool
    let usedTemporaryReference: Bool
    let reusedNormalizedReference: Bool
    let reusedDecodedReference: Bool
    let referenceQualityWarnings: [String]
    var timingsMS: [String: Int]

    /// Existing UI state uses the historical human-readable key. Cache
    /// ownership uses `uiIdentity` / `internalIdentity` directly.
    var uiIdentityKey: String { uiIdentity.legacyKey }

    /// Persistent clone prompt directories intentionally retain their v1
    /// digest input; changing that is an artifact-format migration, not a
    /// cache-key hardening change.
    var internalIdentityKey: String { internalIdentity.legacyKey }

    func withCloneHandle(
        _ cloneHandle: VocelloQwen3CloneHandle,
        cacheHit: Bool,
        conditioningReused: Bool,
        timingsMS additionalTimingsMS: [String: Int] = [:]
    ) -> ResolvedCloneConditioning {
        ResolvedCloneConditioning(
            uiIdentity: uiIdentity,
            internalIdentity: internalIdentity,
            normalizedReference: normalizedReference,
            resolvedTranscript: resolvedTranscript,
            transcriptMode: transcriptMode,
            conditioningMode: conditioningMode,
            referenceAudio: referenceAudio,
            preparedVoiceID: preparedVoiceID,
            cloneHandle: cloneHandle,
            preparedCloneUsed: true,
            cloneCacheHit: cloneCacheHit,
            clonePromptCacheHit: cacheHit,
            cloneConditioningReused: conditioningReused,
            usedTemporaryReference: usedTemporaryReference,
            reusedNormalizedReference: reusedNormalizedReference,
            reusedDecodedReference: reusedDecodedReference,
            referenceQualityWarnings: referenceQualityWarnings,
            timingsMS: timingsMS.merging(additionalTimingsMS) { _, rhs in rhs }
        )
    }
}

/// A-02 (RF-52): which rotary convention this process's speech tokenizer
/// encoder uses. The package reads the same diagnostic key at load
/// (`Qwen3LoadTimeDiagnosticOverrides.encoderSplitHalfRotary`); the host folds
/// it into the clone prompt's speaker-feature version, which reaches the
/// persisted prompt's metadata, so a prompt encoded under one convention is
/// rebuilt, never adopted, under the other.
enum CloneEncoderRotary {
    static let environmentKey = "QWENVOICE_ENCODER_ROTARY"
    static let splitHalfSuffix = "+mimi-encoder-rope-split-half"

    static let speakerFeatureSuffix = speakerFeatureSuffix(
        environment: ProcessInfo.processInfo.environment,
        internalDiagnosticsAvailable: RuntimeDebugGate.internalDiagnosticsAvailable
    )

    /// Read as the package reads it: trimmed and lowercased.
    static func speakerFeatureSuffix(environment: [String: String], internalDiagnosticsAvailable: Bool) -> String {
        let requested = RuntimeDebugGate.value(
            for: environmentKey,
            environment: environment,
            internalDiagnosticsAvailable: internalDiagnosticsAvailable
        )?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return requested == "split-half" ? splitHalfSuffix : ""
    }
}

/// Every clone-conditioning diagnostic key this process honours, as the
/// suffix the clone prompt's speaker-feature version carries.
enum CloneConditioningDiagnostics {
    static let speakerFeatureSuffix = speakerFeatureSuffix(
        environment: ProcessInfo.processInfo.environment,
        internalDiagnosticsAvailable: RuntimeDebugGate.internalDiagnosticsAvailable
    )

    static func speakerFeatureSuffix(environment: [String: String], internalDiagnosticsAvailable: Bool) -> String {
        CloneEncoderRotary.speakerFeatureSuffix(
            environment: environment, internalDiagnosticsAvailable: internalDiagnosticsAvailable)
            + CloneReferencePadding.speakerFeatureSuffix(
                environment: environment, internalDiagnosticsAvailable: internalDiagnosticsAvailable)
            + CloneReferenceEdges.speakerFeatureSuffix(
                environment: environment, internalDiagnosticsAvailable: internalDiagnosticsAvailable)
    }
}

/// G-07 (RF-52): whether this process's package trims a transcript-backed clone
/// reference's silent edges and fades it before conditioning reads it (audio-only
/// prompts and production take it as given). The package reads the same key at load
/// (`Qwen3LoadTimeDiagnosticOverrides.referenceEdgesTrimmed`); the host folds it
/// into the speaker-feature version, as for the rotary and the padding.
enum CloneReferenceEdges {
    static let environmentKey = "QWENVOICE_REFERENCE_EDGES"
    static let trimmedSuffix = "+icl-ref-edges-trimmed"

    /// Read as the package reads it: trimmed and lowercased.
    static func speakerFeatureSuffix(environment: [String: String], internalDiagnosticsAvailable: Bool) -> String {
        let requested = RuntimeDebugGate.value(
            for: environmentKey,
            environment: environment,
            internalDiagnosticsAvailable: internalDiagnosticsAvailable
        )?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return requested == "trimmed" ? trimmedSuffix : ""
    }
}

/// A-12 (RF-52): whether this process's package encodes a clone reference
/// with the half second of trailing zeros it appended before 2026-11-11
/// (production now encodes it as it is, as upstream). The package reads the
/// same key at load (`Qwen3LoadTimeDiagnosticOverrides.referenceTrailingSilenceSamples`);
/// the host folds it into the speaker-feature version, as for the rotary.
public enum CloneReferencePadding {
    static let environmentKey = "QWENVOICE_REFERENCE_PADDING"
    static let halfSecondSuffix = "+icl-ref-silence500ms"

    /// How the codec encoder's input was made in this process, for evidence
    /// that records it (`vocello bench --codec-roundtrip`, reference-primed
    /// replay).
    public static var encoderInputLabel: String {
        speakerFeatureSuffix.isEmpty
            ? "clone_reference_encoder_input_unpadded"
            : "clone_reference_encoder_input_trailing_silence_500ms"
    }

    static let speakerFeatureSuffix = speakerFeatureSuffix(
        environment: ProcessInfo.processInfo.environment,
        internalDiagnosticsAvailable: RuntimeDebugGate.internalDiagnosticsAvailable
    )

    /// Read as the package reads it: trimmed and lowercased.
    static func speakerFeatureSuffix(environment: [String: String], internalDiagnosticsAvailable: Bool) -> String {
        let requested = RuntimeDebugGate.value(
            for: environmentKey,
            environment: environment,
            internalDiagnosticsAvailable: internalDiagnosticsAvailable
        )?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return requested == "half-second" ? halfSecondSuffix : ""
    }
}

actor NativePreparedCloneConditioningCache {
    private let capacity: Int
    private var sourceQualityWarningsByFileState: [String: [String]] = [:]

    private struct NormalizedCloneReferenceOutcome {
        let result: AudioNormalizationResult
        let reusedExistingOutput: Bool
    }

    private struct DecodedReferenceAudio {
        let referenceAudio: [Float]
    }

    private struct CachedCloneHandle {
        let handle: VocelloQwen3CloneHandle
    }

    private struct NormalizedReferenceIdentity: Hashable {
        let fingerprint: String
    }

    private struct DecodedReferenceIdentity: Hashable {
        let normalizedPath: String
        let referenceFingerprint: String
        let sampleRate: Int
    }

    struct CachedConditioning {
        let internalIdentity: GenerationSemantics.CloneReferenceIdentity
        let normalizedReference: AudioNormalizationResult
        let resolvedTranscript: String?
        let transcriptMode: ResolvedCloneTranscriptMode
        let conditioningMode: CloneConditioningMode
        let referenceAudio: [Float]
    }

    private var cachedValues: [GenerationSemantics.CloneReferenceIdentity: CachedConditioning] = [:]
    private var lruKeys: [GenerationSemantics.CloneReferenceIdentity] = []
    private var normalizedReferenceCache: [NormalizedReferenceIdentity: AudioNormalizationResult] = [:]
    private var normalizedReferenceLRUKeys: [NormalizedReferenceIdentity] = []
    private var decodedReferenceAudioCache: [DecodedReferenceIdentity: DecodedReferenceAudio] = [:]
    private var decodedReferenceAudioLRUKeys: [DecodedReferenceIdentity] = []
    private var voiceClonePromptCache: [GenerationSemantics.ClonePromptIdentity: CachedCloneHandle] = [:]
    private var voiceClonePromptLRUKeys: [GenerationSemantics.ClonePromptIdentity] = []

    /// MLX's allocator, injected so deterministic tests stay off Metal (`.inert`).
    private let allocatorControl: NativeMLXAllocatorControl

    init(
        capacity: Int = NativeMemoryPolicyResolver.cloneCacheCapacity(),
        allocatorControl: NativeMLXAllocatorControl = .live
    ) {
        self.capacity = max(capacity, 0)
        self.allocatorControl = allocatorControl
    }

    func clear() {
        cachedValues.removeAll()
        lruKeys.removeAll()
        normalizedReferenceCache.removeAll()
        normalizedReferenceLRUKeys.removeAll()
        decodedReferenceAudioCache.removeAll()
        decodedReferenceAudioLRUKeys.removeAll()
        voiceClonePromptCache.removeAll()
        voiceClonePromptLRUKeys.removeAll()
        allocatorControl.clearCache()
    }

    func softTrim(retainingMostRecent retainedCount: Int = 1) {
        let keepCount = max(retainedCount, 0)
        trimCache(
            &cachedValues,
            lruKeys: &lruKeys,
            retainingMostRecent: keepCount
        )
        trimCache(
            &decodedReferenceAudioCache,
            lruKeys: &decodedReferenceAudioLRUKeys,
            retainingMostRecent: keepCount
        )
        trimCache(
            &voiceClonePromptCache,
            lruKeys: &voiceClonePromptLRUKeys,
            retainingMostRecent: keepCount
        )
        trimCache(
            &normalizedReferenceCache,
            lruKeys: &normalizedReferenceLRUKeys,
            retainingMostRecent: keepCount
        )
        allocatorControl.clearCache()
    }

    func resolve(
        modelID: String,
        reference: CloneReference,
        sampleRate: Int,
        audioPreparationService: any AudioPreparationService,
        normalizedCloneReferenceDirectory: URL
    ) async throws -> ResolvedCloneConditioning {
        let requestedTranscript = Self.normalizedTranscript(reference.transcript)
        let referenceFingerprint = try Self.stableCloneReferenceFingerprint(for: reference.audioURL)
        let normalizationStartedAt = ContinuousClock.now
        let normalizedReferenceOutcome = try await normalizeCloneReference(
            reference.audioURL,
            referenceFingerprint: referenceFingerprint,
            mirrorsTranscriptSidecar: Self.readsTranscriptSidecar(for: reference),
            using: audioPreparationService,
            normalizedCloneReferenceDirectory: normalizedCloneReferenceDirectory
        )
        let normalizationDurationMS = normalizationStartedAt.elapsedMilliseconds
        let normalizedReference = normalizedReferenceOutcome.result
        let referenceQualityWarnings = await sourceQualityWarnings(for: reference.audioURL)
        try Self.requireUsableOneOffReference(reference, warnings: referenceQualityWarnings)
        let transcriptResolution = try Self.resolveTranscript(
            requestedTranscript: requestedTranscript,
            normalizedAudioURL: normalizedReference.normalizedURL,
            readsSavedVoiceSidecar: Self.readsTranscriptSidecar(for: reference)
        )
        let conditioningMode = CloneConditioningMode(
            transcript: transcriptResolution.transcript
        )
        let uiIdentity = GenerationSemantics.cloneReferenceIdentity(
            modelID: modelID,
            refAudio: reference.audioPath,
            refText: requestedTranscript,
            storedTranscriptBypassed: reference.bypassesStoredTranscript
        )
        let internalIdentity = GenerationSemantics.internalCloneReferenceIdentity(
            modelID: modelID,
            normalizedReferencePath: normalizedReference.normalizedPath,
            referenceFingerprint: referenceFingerprint,
            conditioningMode: conditioningMode
        )

        if let cached = cachedValues[internalIdentity] {
            touch(internalIdentity)
            return ResolvedCloneConditioning(
                uiIdentity: uiIdentity,
                internalIdentity: internalIdentity,
                normalizedReference: normalizedReference,
                resolvedTranscript: cached.resolvedTranscript,
                // Equal conditioning text can originate from an explicit
                // override or the store. Publication ownership is per request.
                transcriptMode: transcriptResolution.mode,
                conditioningMode: cached.conditioningMode,
                referenceAudio: cached.referenceAudio,
                preparedVoiceID: reference.preparedVoiceID,
                cloneHandle: nil,
                preparedCloneUsed: true,
                cloneCacheHit: true,
                clonePromptCacheHit: nil,
                cloneConditioningReused: true,
                usedTemporaryReference: cached.normalizedReference.normalizedPath
                    != cached.normalizedReference.sourcePath,
                reusedNormalizedReference: normalizedReferenceOutcome.reusedExistingOutput,
                reusedDecodedReference: true,
                referenceQualityWarnings: referenceQualityWarnings,
                timingsMS: [
                    "reference_normalize": normalizationDurationMS,
                    "reference_decode": 0,
                ]
            )
        }

        let decodeStartedAt = ContinuousClock.now
        let (referenceAudio, reusedDecodedReference) = try resolveDecodedReferenceAudio(
            normalizedReference: normalizedReference,
            referenceFingerprint: referenceFingerprint,
            sampleRate: sampleRate
        )
        let decodeDurationMS = decodeStartedAt.elapsedMilliseconds
        let cached = CachedConditioning(
            internalIdentity: internalIdentity,
            normalizedReference: normalizedReference,
            resolvedTranscript: transcriptResolution.transcript,
            transcriptMode: transcriptResolution.mode,
            conditioningMode: conditioningMode,
            referenceAudio: referenceAudio
        )
        insert(cached)
        return ResolvedCloneConditioning(
            uiIdentity: uiIdentity,
            internalIdentity: internalIdentity,
            normalizedReference: normalizedReference,
            resolvedTranscript: transcriptResolution.transcript,
            transcriptMode: transcriptResolution.mode,
            conditioningMode: conditioningMode,
            referenceAudio: referenceAudio,
            preparedVoiceID: reference.preparedVoiceID,
            cloneHandle: nil,
            preparedCloneUsed: false,
            cloneCacheHit: false,
            clonePromptCacheHit: nil,
            cloneConditioningReused: false,
            usedTemporaryReference: normalizedReference.normalizedPath != normalizedReference.sourcePath,
            reusedNormalizedReference: normalizedReferenceOutcome.reusedExistingOutput,
            reusedDecodedReference: reusedDecodedReference,
            referenceQualityWarnings: referenceQualityWarnings,
            timingsMS: [
                "reference_normalize": normalizationDurationMS,
                "reference_decode": decodeDurationMS,
            ]
        )
    }

    /// The language component every clone prompt is keyed and persisted under.
    ///
    /// A clone prompt holds the reference's codec codes, its speaker embedding
    /// and its transcript; `makeCloneHandle` takes no language, so one prompt
    /// serves a take in every target language (U17). Priming and the saved-voice
    /// prebuild have no script to resolve a language from, and keying the prompt
    /// by the take's language made the first take after a prime miss both the
    /// in-memory prompt and its artifact and rebuild it on the critical path.
    /// The constant is the historical "auto" component, so the artifacts primes
    /// and prebuilds already persisted stay adoptable; artifacts an earlier take
    /// persisted under a concrete language are no longer adopted (a saved voice's
    /// go with the voice, transient ones age out of their retention window).
    static let clonePromptLanguageKey = "auto"

    /// The in-memory identity of the prompt built from `referenceIdentity`;
    /// it carries no target language (see `clonePromptLanguageKey`).
    static func clonePromptIdentity(
        referenceIdentity: GenerationSemantics.CloneReferenceIdentity,
        modelArtifactIdentity: GenerationSemantics.ClonePromptModelArtifactIdentity,
        runtimeProfileSignature: String?,
        diagnosticSuffix: String = CloneConditioningDiagnostics.speakerFeatureSuffix
    ) -> GenerationSemantics.ClonePromptIdentity {
        GenerationSemantics.ClonePromptIdentity(
            referenceIdentity: referenceIdentity,
            language: clonePromptLanguageKey,
            modelArtifactIdentity: modelArtifactIdentity,
            qwenRuntimeProfileSignature: runtimeProfileSignature,
            speakerFeatureVersion: VocelloQwen3CloneArtifactSchema.speakerFeatureVersion + diagnosticSuffix
        )
    }

    func resolveVoiceClonePrompt(
        for conditioning: ResolvedCloneConditioning,
        modelID: String,
        model: UnsafeSpeechGenerationModel,
        voicesDirectory: URL?,
        modelRuntimeIdentity: ModelRuntimeIdentity
    ) async throws -> ResolvedCloneConditioning {
        guard model.supportsOptimizedVoiceClone,
              conditioning.cloneHandle == nil else {
            return conditioning
        }

        let conditioningMode = conditioning.conditioningMode.normalized
        let creationContract = NativeClonePromptCreationContract(
            conditioningMode: conditioningMode
        )
        guard let modelArtifactIdentity = GenerationSemantics.ClonePromptModelArtifactIdentity(
            modelRuntimeIdentity: modelRuntimeIdentity
        ) else {
            throw MLXTTSEngineError.modelUnavailable(
                "The selected model is missing immutable clone-prompt artifact provenance."
            )
        }
        let promptIdentity = Self.clonePromptIdentity(
            referenceIdentity: conditioning.internalIdentity,
            modelArtifactIdentity: modelArtifactIdentity,
            runtimeProfileSignature: modelRuntimeIdentity.runtimeProfileSignature
        )
        let artifactMetadata = clonePromptArtifactMetadata(
            modelID: modelID,
            conditioning: conditioning,
            xVectorOnlyMode: creationContract.xVectorOnlyMode,
            modelArtifactIdentity: modelArtifactIdentity,
            clonePromptRuntimeSignature: promptIdentity.runtimeContractSignature
        )
        let artifactDirectory = clonePromptArtifactDirectory(
            voicesDirectory: voicesDirectory,
            preparedVoiceID: conditioning.preparedVoiceID,
            modelID: modelID,
            conditioning: conditioning
        )
        let resolveStartedAt = ContinuousClock.now
        if let artifactDirectory,
           FileManager.default.fileExists(atPath: artifactDirectory.path) {
            let artifactLoadStartedAt = ContinuousClock.now
            do {
                let handle = try await model.engine.adoptCloneArtifact(
                    from: artifactDirectory,
                    expectedMetadata: artifactMetadata,
                    conditioningDigest: conditioning.internalIdentity.digest
                )
                if conditioning.preparedVoiceID == nil {
                    Self.markTransientClonePromptArtifactUsed(artifactDirectory)
                }
                cacheCloneHandle(handle, for: promptIdentity)
                return conditioning.withCloneHandle(
                    handle,
                    cacheHit: true,
                    conditioningReused: true,
                    timingsMS: [
                        "clone_prompt_artifact_load": artifactLoadStartedAt.elapsedMilliseconds,
                        "clone_prompt_resolve": resolveStartedAt.elapsedMilliseconds,
                    ]
                )
            } catch {
                try? FileManager.default.removeItem(at: artifactDirectory)
            }
        }

        if let cached = voiceClonePromptCache[promptIdentity] {
            if await model.engine.isCloneHandleValid(cached.handle) {
                touchVoiceClonePrompt(promptIdentity)
                return conditioning.withCloneHandle(
                    cached.handle,
                    cacheHit: true,
                    conditioningReused: true,
                    timingsMS: [
                        "clone_prompt_resolve": resolveStartedAt.elapsedMilliseconds,
                    ]
                )
            }
            // The actor invalidated this record (model reload, critical trim,
            // or full unload); drop the stale entry and rebuild below.
            voiceClonePromptCache.removeValue(forKey: promptIdentity)
            voiceClonePromptLRUKeys.removeAll { $0 == promptIdentity }
        }

        let promptBuildStartedAt = ContinuousClock.now
        let handle = try await model.makeCloneHandle(
            refAudio: conditioning.referenceAudio,
            refText: creationContract.refText,
            xVectorOnlyMode: creationContract.xVectorOnlyMode,
            conditioningDigest: conditioning.internalIdentity.digest
        )
        let promptBuildMS = promptBuildStartedAt.elapsedMilliseconds
        cacheCloneHandle(handle, for: promptIdentity)
        if let artifactDirectory {
            let metadata = artifactMetadata.fillingCreatedAtIfNeeded()
            if let voiceID = conditioning.preparedVoiceID, let voicesDirectory,
               let sourceFingerprint = conditioning.internalIdentity.referenceFingerprint {
                _ = try await Self.persistSavedVoiceCloneArtifact(
                    voicesDirectory: voicesDirectory,
                    artifactDirectory: artifactDirectory,
                    voiceID: voiceID,
                    sourceURL: conditioning.normalizedReference.sourceURL,
                    sourceFingerprint: sourceFingerprint,
                    checksStoredTranscript: Self.comparesStoredTranscriptBeforePublication(conditioning),
                    expectedStoredTranscript: conditioning.resolvedTranscript
                ) { @concurrent staging in
                    try await model.engine.persistCloneArtifact(handle, to: staging, metadata: metadata)
                }
            } else if conditioning.preparedVoiceID == nil {
                try await model.engine.persistCloneArtifact(handle, to: artifactDirectory, metadata: metadata)
            }
            if conditioning.preparedVoiceID == nil, let voicesDirectory {
                Self.pruneTransientClonePromptArtifacts(in: voicesDirectory)
            }
        }
        return conditioning.withCloneHandle(
            handle,
            cacheHit: false,
            conditioningReused: conditioning.cloneConditioningReused,
            timingsMS: [
                "clone_prompt_build": promptBuildMS,
                "clone_prompt_resolve": resolveStartedAt.elapsedMilliseconds,
            ]
        )
    }

    /// Model work writes privately, then the repository validates source
    /// ownership and publishes under the delete/replacement lock. A concurrent
    /// deletion may discard persistence without invalidating this take's handle.
    @discardableResult
    @concurrent static func persistSavedVoiceCloneArtifact(
        voicesDirectory: URL,
        artifactDirectory: URL,
        voiceID: String,
        sourceURL: URL,
        sourceFingerprint: String,
        checksStoredTranscript: Bool,
        expectedStoredTranscript: String?,
        persist: @Sendable @concurrent (URL) async throws -> Void
    ) async throws -> Bool {
        let staging = voicesDirectory.appendingPathComponent(".clone-prompt-staging-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: staging) }
        try await persist(staging)
        let repository = PreparedVoiceRepository(
            appSupportDirectory: voicesDirectory.deletingLastPathComponent(),
            supportedAudioExtensions: MLXTTSEngine.supportedSavedVoiceAudioExtensions
        )
        do {
            return try await repository.publishClonePromptArtifact(
                from: staging, to: artifactDirectory, voiceID: voiceID,
                sourceURL: sourceURL, sourceFingerprint: sourceFingerprint,
                checksStoredTranscript: checksStoredTranscript,
                expectedStoredTranscript: expectedStoredTranscript
            )
        } catch PreparedVoiceRepositoryError.storeBusy, PreparedVoiceRepositoryError.invalidIdentifier {
            // A prompt is a rebuildable cache; never delay a take or hold an
            // executor while another process owns the saved-voice transaction,
            // and never fail a take whose handle is built because publication
            // refused its paths (CONV-21): nothing was published, staging goes.
            return false
        }
    }

    /// Whether publishing a saved voice's prompt first compares the stored
    /// transcript with the one the prompt was built from. An inline transcript
    /// is the caller's own. A request that states audio-only never read the
    /// stored transcript (G-02), so there is none to compare: its prompt lives
    /// under the audio-only identity, which no transcript-backed request
    /// resolves to.
    static func comparesStoredTranscriptBeforePublication(_ conditioning: ResolvedCloneConditioning) -> Bool {
        conditioning.transcriptMode != .inline && !conditioning.uiIdentity.storedTranscriptBypassed
    }

    /// Only a saved voice reads the transcript sidecar beside its reference
    /// (P12-09). A one-off reference is used in place, so a same-stem `.txt`
    /// next to it is whatever the user keeps there (notes, a whole-episode
    /// transcript), not a transcript anyone reviewed for this clip; without an
    /// inline transcript it conditions audio-only, as the Studio shows it.
    ///
    /// A request that states audio-only (`ignoresStoredTranscript`, G-02) never
    /// reads it either: the user's choice in the Studio is not replaced by the
    /// transcript the voice was saved with.
    static func readsTranscriptSidecar(for reference: CloneReference) -> Bool {
        reference.preparedVoiceID != nil && !reference.ignoresStoredTranscript
    }

    private func insert(_ conditioning: CachedConditioning) {
        cachedValues[conditioning.internalIdentity] = conditioning
        touch(conditioning.internalIdentity)
        var evicted = false
        while lruKeys.count > capacity {
            let evictedKey = lruKeys.removeFirst()
            cachedValues.removeValue(forKey: evictedKey)
            evicted = true
        }
        if evicted {
            allocatorControl.clearCache()
        }
    }

    private func touch(_ key: GenerationSemantics.CloneReferenceIdentity) {
        lruKeys.removeAll { $0 == key }
        lruKeys.append(key)
    }

    private func normalizeCloneReference(
        _ sourceURL: URL,
        referenceFingerprint: String,
        mirrorsTranscriptSidecar: Bool,
        using audioPreparationService: any AudioPreparationService,
        normalizedCloneReferenceDirectory: URL
    ) async throws -> NormalizedCloneReferenceOutcome {
        let cacheKey = normalizedReferenceCacheKey(referenceFingerprint: referenceFingerprint)
        if let cachedResult = normalizedReferenceCache[cacheKey],
           Self.canReuseCachedNormalizedReference(
               cachedResult,
               for: sourceURL,
               referenceFingerprint: referenceFingerprint
           ) {
            touchNormalizedReference(cacheKey)
            if mirrorsTranscriptSidecar {
                try Self.mirrorTranscriptSidecarIfNeeded(from: sourceURL, to: cachedResult.normalizedURL)
            }
            return NormalizedCloneReferenceOutcome(
                result: cachedResult,
                reusedExistingOutput: true
            )
        }

        let normalizationRequest: AudioPreparationRequest
        let reusedExistingOutput: Bool
        if NativeAudioPreparationService.isCanonicalWAV(at: sourceURL) {
            normalizationRequest = AudioPreparationRequest(inputURL: sourceURL)
            reusedExistingOutput = false
        } else {
            let outputURL = normalizedCloneReferenceDirectory.appendingPathComponent(
                Self.stableNormalizedCloneReferenceFileName(
                    for: sourceURL,
                    referenceFingerprint: referenceFingerprint
                )
            )
            // The output is named by source content, so reuse is decided by
            // that same fingerprint here and inside the preparation service;
            // the reported reuse is the reuse that happens.
            normalizationRequest = AudioPreparationRequest(
                inputURL: sourceURL,
                outputURL: outputURL,
                outputReuseFingerprint: referenceFingerprint
            )
            reusedExistingOutput = NativeAudioPreparationService.canReuseExistingNormalizedOutput(
                at: outputURL,
                fingerprint: referenceFingerprint
            )
        }

        let result = try await audioPreparationService.normalizeAudio(normalizationRequest)
        if mirrorsTranscriptSidecar {
            try Self.mirrorTranscriptSidecarIfNeeded(from: sourceURL, to: result.normalizedURL)
        }
        normalizedReferenceCache[cacheKey] = result
        touchNormalizedReference(cacheKey)
        while normalizedReferenceLRUKeys.count > capacity {
            let evictedKey = normalizedReferenceLRUKeys.removeFirst()
            normalizedReferenceCache.removeValue(forKey: evictedKey)
        }
        return NormalizedCloneReferenceOutcome(
            result: result,
            reusedExistingOutput: reusedExistingOutput
        )
    }

    private func touchNormalizedReference(_ key: NormalizedReferenceIdentity) {
        normalizedReferenceLRUKeys.removeAll { $0 == key }
        normalizedReferenceLRUKeys.append(key)
    }

    private func resolveDecodedReferenceAudio(
        normalizedReference: AudioNormalizationResult,
        referenceFingerprint: String,
        sampleRate: Int
    ) throws -> (referenceAudio: [Float], reusedDecodedReference: Bool) {
        let key = decodedReferenceAudioCacheKey(
            normalizedPath: normalizedReference.normalizedPath,
            referenceFingerprint: referenceFingerprint,
            sampleRate: sampleRate
        )
        if let cached = decodedReferenceAudioCache[key] {
            touchDecodedReferenceAudio(key)
            return (cached.referenceAudio, true)
        }

        let referenceAudio = try Self.loadCanonicalReferenceSamples(
            from: normalizedReference.normalizedURL,
            expectedSampleRate: sampleRate
        )
        decodedReferenceAudioCache[key] = DecodedReferenceAudio(referenceAudio: referenceAudio)
        touchDecodedReferenceAudio(key)
        var evicted = false
        while decodedReferenceAudioLRUKeys.count > capacity {
            let evictedKey = decodedReferenceAudioLRUKeys.removeFirst()
            decodedReferenceAudioCache.removeValue(forKey: evictedKey)
            evicted = true
        }
        if evicted {
            allocatorControl.clearCache()
        }
        return (referenceAudio, false)
    }

    /// Clone normalization already guarantees mono 24 kHz PCM. Decode that
    /// owned product artifact with AVFoundation so no MLXAudio utility or
    /// tensor-shaped type crosses the `VocelloQwen3Core` facade boundary.
    private static func loadCanonicalReferenceSamples(
        from url: URL,
        expectedSampleRate: Int
    ) throws -> [Float] {
        let file = try AVAudioFile(forReading: url)
        let format = file.processingFormat
        guard Int(format.sampleRate.rounded()) == expectedSampleRate,
              format.channelCount == 1 else {
            throw AudioPreparationError.conversionFailed(
                "Normalized clone reference does not match the model sample-rate contract."
            )
        }
        let frameCount = AVAudioFrameCount(file.length)
        guard frameCount > 0,
              let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frameCount) else {
            throw AudioPreparationError.conversionFailed(
                "Could not allocate the normalized clone reference buffer."
            )
        }
        try file.read(into: buffer)
        guard let channel = unsafe buffer.floatChannelData?[0] else {
            throw AudioPreparationError.conversionFailed(
                "Could not decode normalized clone reference samples."
            )
        }
        return unsafe Array(UnsafeBufferPointer(start: channel, count: Int(buffer.frameLength)))
    }

    private func touchDecodedReferenceAudio(_ key: DecodedReferenceIdentity) {
        decodedReferenceAudioLRUKeys.removeAll { $0 == key }
        decodedReferenceAudioLRUKeys.append(key)
    }

    private func cacheCloneHandle(
        _ handle: VocelloQwen3CloneHandle,
        for key: GenerationSemantics.ClonePromptIdentity
    ) {
        voiceClonePromptCache[key] = CachedCloneHandle(handle: handle)
        touchVoiceClonePrompt(key)
        var evicted = false
        while voiceClonePromptLRUKeys.count > capacity {
            let evictedKey = voiceClonePromptLRUKeys.removeFirst()
            voiceClonePromptCache.removeValue(forKey: evictedKey)
            evicted = true
        }
        if evicted {
            allocatorControl.clearCache()
        }
    }

    private func touchVoiceClonePrompt(_ key: GenerationSemantics.ClonePromptIdentity) {
        voiceClonePromptLRUKeys.removeAll { $0 == key }
        voiceClonePromptLRUKeys.append(key)
    }

    private func trimCache<Key: Hashable, Value>(
        _ cache: inout [Key: Value],
        lruKeys: inout [Key],
        retainingMostRecent retainedCount: Int
    ) {
        guard retainedCount < lruKeys.count else { return }
        let retainedKeys = Set(lruKeys.suffix(retainedCount))
        cache = cache.filter { retainedKeys.contains($0.key) }
        lruKeys = lruKeys.filter { retainedKeys.contains($0) }
    }

    /// The in-memory entry is keyed by the source's content fingerprint, and a
    /// converted output is named by it, so the on-disk check uses that same
    /// fingerprint. The result's own path/size/mtime fingerprint must still
    /// match the source so the metadata it carries (clone-artifact
    /// `sourceAudioFingerprint`) is what a fresh preparation would report.
    static func canReuseCachedNormalizedReference(
        _ result: AudioNormalizationResult,
        for sourceURL: URL,
        referenceFingerprint: String
    ) -> Bool {
        guard result.sourceURL.standardizedFileURL == sourceURL.standardizedFileURL,
              result.fingerprint == NativeAudioPreparationService.fileFingerprint(for: sourceURL) else {
            return false
        }
        if result.wasAlreadyCanonical {
            return NativeAudioPreparationService.isCanonicalWAV(at: sourceURL)
        }
        return NativeAudioPreparationService.canReuseExistingNormalizedOutput(
            at: result.normalizedURL,
            fingerprint: referenceFingerprint
        )
    }

    /// The reference's warnings, measured from the clip as the user gave it
    /// (the header is the source's own, so a narrow-band source is seen before
    /// its resampling hides it, G-09). Kept per file state, so a take, a
    /// long-form segment or a batch line after the first costs one `stat`.
    func sourceQualityWarnings(for sourceURL: URL) async -> [String] {
        let key = NativeAudioPreparationService.fileFingerprint(for: sourceURL)
        if let known = sourceQualityWarningsByFileState[key] {
            return known
        }
        let warnings = await CloneReferenceQuality.measuredWarnings(forReferenceAt: sourceURL)
        if sourceQualityWarningsByFileState.count >= Self.sourceQualityCacheLimit {
            sourceQualityWarningsByFileState.removeAll(keepingCapacity: true)
        }
        sourceQualityWarningsByFileState[key] = warnings
        return warnings
    }

    private static let sourceQualityCacheLimit = 64

    /// A one-off reference never passed enrollment's review, so the engine
    /// applies the same refusal there (G-11): every host, the CLI included,
    /// gets one policy. A saved voice was accepted when it was enrolled and
    /// keeps working.
    static func requireUsableOneOffReference(
        _ reference: CloneReference,
        warnings: [String]
    ) throws {
        guard reference.preparedVoiceID == nil else { return }
        let blocking = PreparedVoiceQualityWarning.blockingTokens(in: warnings)
        guard blocking.isEmpty else {
            throw CloneReferenceQuality.Rejection(tokens: blocking)
        }
    }

    /// The refusal the runtime asks for before it loads a model (S2 of the
    /// RF-51 review): a clip that is too long or silent is refused without
    /// paying for a load. A clip that cannot be opened is left to the
    /// pipeline, which names a missing or unsupported file more exactly.
    func requireUsableOneOffReferenceBeforeLoad(_ reference: CloneReference) async throws {
        guard reference.preparedVoiceID == nil else { return }
        let warnings = await sourceQualityWarnings(for: reference.audioURL)
        guard warnings != [CloneReferenceQuality.unreadableToken] else { return }
        try Self.requireUsableOneOffReference(reference, warnings: warnings)
    }

    static func resolveTranscript(
        requestedTranscript: String?,
        normalizedAudioURL: URL,
        readsSavedVoiceSidecar: Bool
    ) throws -> (transcript: String?, mode: ResolvedCloneTranscriptMode) {
        if let requestedTranscript {
            return (requestedTranscript, .inline)
        }
        guard readsSavedVoiceSidecar else {
            return (nil, .none)
        }

        let sidecarURL = normalizedAudioURL.deletingPathExtension().appendingPathExtension("txt")
        guard FileManager.default.fileExists(atPath: sidecarURL.path) else {
            return (nil, .none)
        }

        guard let text = normalizedTranscript(try String(contentsOf: sidecarURL, encoding: .utf8)) else {
            return (nil, .none)
        }
        return (text, .sidecar)
    }

    private static func mirrorTranscriptSidecarIfNeeded(from sourceURL: URL, to normalizedURL: URL) throws {
        let fileManager = FileManager.default
        let sourceSidecarURL = sourceURL.deletingPathExtension().appendingPathExtension("txt")
        let normalizedSidecarURL = normalizedURL.deletingPathExtension().appendingPathExtension("txt")

        guard fileManager.fileExists(atPath: sourceSidecarURL.path) else {
            if normalizedSidecarURL.standardizedFileURL != sourceSidecarURL.standardizedFileURL,
               fileManager.fileExists(atPath: normalizedSidecarURL.path) {
                try? fileManager.removeItem(at: normalizedSidecarURL)
            }
            return
        }

        if normalizedSidecarURL.standardizedFileURL == sourceSidecarURL.standardizedFileURL {
            return
        }

        try fileManager.createDirectory(
            at: normalizedSidecarURL.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        if fileManager.fileExists(atPath: normalizedSidecarURL.path) {
            try fileManager.removeItem(at: normalizedSidecarURL)
        }
        try fileManager.copyItem(at: sourceSidecarURL, to: normalizedSidecarURL)
    }

    /// `CloneConditioningMode.conditioningText`: a request's transcript and a
    /// stored one take the same shape, so a saved voice conditions the CLI's
    /// `--voice` take and the prebuilt prompt exactly as it does a Studio take
    /// (G-12).
    static func normalizedTranscript(_ transcript: String?) -> String? {
        CloneConditioningMode.conditioningText(transcript)
    }

    /// Resolves the contract far enough to reject an unsupported clone mode
    /// before model loading. Full resolution still happens after reference
    /// normalization, where the mirrored sidecar is authoritative.
    static func anticipatedConditioningMode(
        for reference: CloneReference
    ) -> CloneConditioningMode {
        if reference.conditioningMode.usesTranscript {
            return reference.conditioningMode.normalized
        }
        guard readsTranscriptSidecar(for: reference) else {
            return .xVectorOnly
        }

        let sidecarURL = reference.audioURL
            .deletingPathExtension()
            .appendingPathExtension("txt")
        guard let sidecar = try? String(contentsOf: sidecarURL, encoding: .utf8) else {
            return .xVectorOnly
        }
        return CloneConditioningMode(transcript: sidecar)
    }

    static func stableNormalizedCloneReferenceFileName(for sourceURL: URL) throws -> String {
        let fingerprint = try stableCloneReferenceFingerprint(for: sourceURL)
        return stableNormalizedCloneReferenceFileName(
            for: sourceURL,
            referenceFingerprint: fingerprint
        )
    }

    static func stableNormalizedCloneReferenceFileName(
        for sourceURL: URL,
        referenceFingerprint: String
    ) -> String {
        let stem = sanitizedStem(for: sourceURL)
        return "\(stem)_\(referenceFingerprint).wav"
    }

    private static func sanitizedStem(for sourceURL: URL) -> String {
        let raw = sourceURL.deletingPathExtension().lastPathComponent
        let sanitized = raw
            .replacingOccurrences(of: #"[^\w\s-]"#, with: "", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .replacingOccurrences(of: " ", with: "_")
        return sanitized.isEmpty ? "reference" : sanitized
    }

    static func stableCloneReferenceFingerprint(for sourceURL: URL) throws -> String {
        preparationFingerprint(
            contentDigest: try cloneReferenceContentDigest(for: sourceURL),
            version: NativeAudioPreparationService.cloneReferencePreparationVersion
        )
    }

    /// The reference's fingerprint under every preparation version there has
    /// been, newest last: a prepared copy made by an earlier build is found
    /// by the name that build gave it.
    static func cloneReferenceFingerprintsOfEveryPreparationVersion(for sourceURL: URL) throws -> [String] {
        let contentDigest = try cloneReferenceContentDigest(for: sourceURL)
        return (1...NativeAudioPreparationService.newestCloneReferencePreparationVersion).map {
            preparationFingerprint(contentDigest: contentDigest, version: $0)
        }
    }

    static func cloneReferenceContentDigest(for sourceURL: URL) throws -> String {
        let resolvedURL = URL(fileURLWithPath: sourceURL.resolvingSymlinksInPath().path)
        let fileHandle = try FileHandle(forReadingFrom: resolvedURL)
        defer { try? fileHandle.close() }

        var hasher = SHA256()
        while true {
            guard let chunk = try fileHandle.read(upToCount: 1024 * 1024),
                  !chunk.isEmpty else {
                break
            }
            hasher.update(data: chunk)
        }
        let digest = hasher.finalize()
        return digest.map { unsafe String(format: "%02x", $0) }.joined()
    }

    /// The reference's identity under one version of audio preparation (G-13).
    /// Everything made from a reference is keyed by this value: the prepared
    /// file's name, the decoded-audio and prompt caches, and the persisted
    /// clone prompt. Version 1 is the content digest itself, so nothing made
    /// by an earlier build is invalidated; a later version gives every
    /// reference a new identity, and each prompt is rebuilt once from its
    /// reference.
    static func preparationFingerprint(contentDigest: String, version: Int) -> String {
        guard version != 1 else { return contentDigest }
        return sha256Hex(text: "clone-reference-preparation-v\(version)|\(contentDigest)")
    }

    private func decodedReferenceAudioCacheKey(
        normalizedPath: String,
        referenceFingerprint: String,
        sampleRate: Int
    ) -> DecodedReferenceIdentity {
        DecodedReferenceIdentity(
            normalizedPath: normalizedPath,
            referenceFingerprint: referenceFingerprint,
            sampleRate: sampleRate
        )
    }

    private func normalizedReferenceCacheKey(
        referenceFingerprint: String
    ) -> NormalizedReferenceIdentity {
        NormalizedReferenceIdentity(fingerprint: referenceFingerprint)
    }

    static func preparedVoiceClonePromptRootDirectory(
        in voicesDirectory: URL,
        voiceID: String
    ) -> URL {
        voicesDirectory.appendingPathComponent("\(voiceID).clone_prompt", isDirectory: true)
    }

    private func clonePromptArtifactDirectory(
        voicesDirectory: URL?,
        preparedVoiceID: String?,
        modelID: String,
        conditioning: ResolvedCloneConditioning? = nil
    ) -> URL? {
        guard let voicesDirectory else { return nil }
        if let preparedVoiceID {
            let root = Self.preparedVoiceClonePromptRootDirectory(
                in: voicesDirectory,
                voiceID: preparedVoiceID
            )
            let modelRoot = root.appendingPathComponent(modelID, isDirectory: true)
            guard let conditioning else { return modelRoot }
            return modelRoot.appendingPathComponent(
                Self.clonePromptArtifactDigest(
                    modelID: modelID,
                    internalIdentityKey: conditioning.internalIdentityKey
                ),
                isDirectory: true
            )
        }
        guard let conditioning else { return nil }
        let digest = Self.clonePromptArtifactDigest(
            modelID: modelID,
            internalIdentityKey: conditioning.internalIdentityKey
        )
        return Self.transientClonePromptRootDirectory(in: voicesDirectory)
            .appendingPathComponent(digest, isDirectory: true)
    }

    /// Clone prompts derived from a one-off reference (no saved voice) hold a
    /// speaker embedding and codec tokens, so they are transient rather than
    /// kept forever: only the most recently used few stay on disk. A saved
    /// voice's prompts live under its own `<id>.clone_prompt` directory and are
    /// deleted with the voice. Where this directory sits for backup purposes is
    /// ASR-06's classification, not this lifecycle.
    static let transientClonePromptArtifactRetentionLimit = 8

    static func transientClonePromptRootDirectory(in voicesDirectory: URL) -> URL {
        voicesDirectory.appendingPathComponent(".qvoice_clone_prompts", isDirectory: true)
    }

    /// Keeps the `limit` most recently used transient artifacts and removes the
    /// rest. Hidden entries (in-flight atomic-publication staging) are left
    /// alone. Best effort: a directory another process removes first, or one
    /// that cannot be removed, is skipped; a pruned artifact is rebuilt from its
    /// reference on the next take that needs it.
    static func pruneTransientClonePromptArtifacts(
        in voicesDirectory: URL,
        retaining limit: Int = transientClonePromptArtifactRetentionLimit,
        fileManager: FileManager = .default
    ) {
        let keys: [URLResourceKey] = [.isDirectoryKey, .isSymbolicLinkKey, .contentModificationDateKey]
        guard let entries = try? fileManager.contentsOfDirectory(
            at: transientClonePromptRootDirectory(in: voicesDirectory),
            includingPropertiesForKeys: keys,
            options: [.skipsHiddenFiles]
        ) else {
            return
        }
        let artifacts = entries.compactMap { url -> (url: URL, lastUsed: Date)? in
            guard let values = try? url.resourceValues(forKeys: Set(keys)),
                  values.isDirectory == true,
                  values.isSymbolicLink != true else {
                return nil
            }
            return (url, values.contentModificationDate ?? .distantPast)
        }
        guard artifacts.count > max(limit, 0) else { return }
        let newestFirst = artifacts.sorted {
            $0.lastUsed == $1.lastUsed
                ? $0.url.lastPathComponent < $1.url.lastPathComponent
                : $0.lastUsed > $1.lastUsed
        }
        for artifact in newestFirst.dropFirst(max(limit, 0)) {
            try? fileManager.removeItem(at: artifact.url)
        }
    }

    /// Adoption counts as use, so the retention order is least recently used.
    private static func markTransientClonePromptArtifactUsed(_ directory: URL) {
        try? FileManager.default.setAttributes(
            [.modificationDate: Date()],
            ofItemAtPath: directory.path
        )
    }

    /// The artifact directory name of a prompt: the v1 digest input of model,
    /// reference identity and the language component, which is always
    /// `clonePromptLanguageKey` (U17), so a prime, a prebuild and a take in any
    /// language name the same directory.
    static func clonePromptArtifactDigest(
        modelID: String,
        internalIdentityKey: String
    ) -> String {
        let identity = [
            modelID,
            internalIdentityKey,
            clonePromptLanguageKey,
        ].joined(separator: "|")
        let digest = SHA256.hash(data: Data(identity.utf8))
            .prefix(16)
            .map { unsafe String(format: "%02x", $0) }
            .joined()
        return digest
    }

    private func clonePromptArtifactMetadata(
        modelID: String,
        conditioning: ResolvedCloneConditioning,
        xVectorOnlyMode: Bool,
        modelArtifactIdentity: GenerationSemantics.ClonePromptModelArtifactIdentity,
        clonePromptRuntimeSignature: String
    ) -> VocelloQwen3CloneArtifactMetadata {
        VocelloQwen3CloneArtifactMetadata(
            modelID: modelID,
            modelRepository: modelArtifactIdentity.repository,
            modelRevision: modelArtifactIdentity.revision,
            modelArtifactVersion: modelArtifactIdentity.artifactVersion,
            modelIntegrityManifestDigest: modelArtifactIdentity.integrityManifestDigest,
            language: Self.clonePromptLanguageKey,
            sourceAudioFingerprint: conditioning.normalizedReference.fingerprint,
            transcriptHash: conditioning.resolvedTranscript.map(Self.sha256Hex(text:)),
            hasTranscript: conditioning.resolvedTranscript != nil,
            xVectorOnlyMode: xVectorOnlyMode,
            runtimeProfileSignature: clonePromptRuntimeSignature
        )
    }

    private static func sha256Hex(text: String) -> String {
        SHA256.hash(data: Data(text.utf8))
            .map { unsafe String(format: "%02x", $0) }
            .joined()
    }

}

/// The saved-voice store's ID for a name: the name without path and control
/// characters. Public so the macOS sheet checks names exactly as the store
/// will (U16).
public enum NativeSavedVoiceNaming {
    public static func normalizedName(_ rawName: String) -> String {
        rawName
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .replacingOccurrences(
                of: #"[\\/:*?"<>|\p{Cc}]"#,
                with: "",
                options: .regularExpression
            )
    }
}
