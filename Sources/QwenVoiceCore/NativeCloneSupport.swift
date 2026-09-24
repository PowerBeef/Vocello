import CryptoKit
@preconcurrency import AVFoundation
import Foundation
@preconcurrency import MLX
@preconcurrency import VocelloQwen3Core

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

struct ResolvedCloneConditioning: @unchecked Sendable {
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

actor NativePreparedCloneConditioningCache {
    private let capacity: Int

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

    init(capacity: Int = NativeMemoryPolicyResolver.cloneCacheCapacity()) {
        self.capacity = max(capacity, 0)
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
        Memory.clearCache()
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
        Memory.clearCache()
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
            using: audioPreparationService,
            normalizedCloneReferenceDirectory: normalizedCloneReferenceDirectory
        )
        let normalizationDurationMS = normalizationStartedAt.elapsedMilliseconds
        let normalizedReference = normalizedReferenceOutcome.result
        let referenceQualityWarnings = Self.referenceQualityWarnings(for: normalizedReference)
        let transcriptResolution = try Self.resolveTranscript(
            requestedTranscript: requestedTranscript,
            normalizedAudioURL: normalizedReference.normalizedURL
        )
        let conditioningMode = CloneConditioningMode(
            transcript: transcriptResolution.transcript
        )
        let uiIdentity = GenerationSemantics.cloneReferenceIdentity(
            modelID: modelID,
            refAudio: reference.audioPath,
            refText: requestedTranscript
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
                normalizedReference: cached.normalizedReference,
                resolvedTranscript: cached.resolvedTranscript,
                transcriptMode: cached.transcriptMode,
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

    func resolveVoiceClonePrompt(
        for conditioning: ResolvedCloneConditioning,
        modelID: String,
        model: UnsafeSpeechGenerationModel,
        voicesDirectory: URL?,
        language: String? = nil,
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
        let promptIdentity = GenerationSemantics.ClonePromptIdentity(
            referenceIdentity: conditioning.internalIdentity,
            language: language,
            modelArtifactIdentity: modelArtifactIdentity,
            qwenRuntimeProfileSignature: modelRuntimeIdentity.runtimeProfileSignature,
            speakerFeatureVersion: VocelloQwen3CloneArtifactSchema.speakerFeatureVersion
        )
        let artifactMetadata = clonePromptArtifactMetadata(
            modelID: modelID,
            conditioning: conditioning,
            language: language,
            xVectorOnlyMode: creationContract.xVectorOnlyMode,
            modelArtifactIdentity: modelArtifactIdentity,
            clonePromptRuntimeSignature: promptIdentity.runtimeContractSignature
        )
        let artifactDirectory = clonePromptArtifactDirectory(
            voicesDirectory: voicesDirectory,
            preparedVoiceID: conditioning.preparedVoiceID,
            modelID: modelID,
            conditioning: conditioning,
            language: language
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
            try await model.engine.persistCloneArtifact(
                handle,
                to: artifactDirectory,
                metadata: artifactMetadata.fillingCreatedAtIfNeeded()
            )
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
            Memory.clearCache()
        }
    }

    private func touch(_ key: GenerationSemantics.CloneReferenceIdentity) {
        lruKeys.removeAll { $0 == key }
        lruKeys.append(key)
    }

    private func normalizeCloneReference(
        _ sourceURL: URL,
        referenceFingerprint: String,
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
            try Self.mirrorTranscriptSidecarIfNeeded(from: sourceURL, to: cachedResult.normalizedURL)
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
        try Self.mirrorTranscriptSidecarIfNeeded(from: sourceURL, to: result.normalizedURL)
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
            Memory.clearCache()
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
        guard let channel = buffer.floatChannelData?[0] else {
            throw AudioPreparationError.conversionFailed(
                "Could not decode normalized clone reference samples."
            )
        }
        return Array(UnsafeBufferPointer(start: channel, count: Int(buffer.frameLength)))
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
            Memory.clearCache()
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

    static func referenceQualityWarnings(for result: AudioNormalizationResult) -> [String] {
        var warnings: [String] = []
        // Duration tiers (see PreparedVoiceQualityWarning.summary doc for
        // the source of these thresholds — Alibaba Cloud Model Studio's
        // hosted Qwen-TTS API guidance, not a documented Qwen3-TTS cliff):
        //   <10 s            → short (likely insufficient speaker info)
        //   10–30 s          → no warning (10–20 s is the sweet spot)
        //   30–60 s          → long (outside sweet spot, soft warn)
        //   >60 s            → excessive (hard cap, blocks Keep voice)
        if result.durationSeconds < 10 {
            warnings.append("reference_duration_short")
        } else if result.durationSeconds > 60 {
            warnings.append("reference_duration_excessive")
        } else if result.durationSeconds > 30 {
            warnings.append("reference_duration_long")
        }
        if abs(result.sampleRate - 24_000) > 0.001 {
            warnings.append("reference_sample_rate_noncanonical")
        }
        if result.channelCount != 1 {
            warnings.append("reference_channels_noncanonical")
        }

        guard let audioStats = try? referenceAudioStats(at: result.normalizedURL) else {
            warnings.append("reference_quality_unreadable")
            return warnings
        }
        if audioStats.rms < 0.0005 {
            warnings.append("reference_near_silence")
        }
        if audioStats.peak >= 0.98 {
            warnings.append("reference_possible_clipping")
        }
        return warnings
    }

    private static func referenceAudioStats(at url: URL) throws -> (peak: Float, rms: Float) {
        let file = try AVAudioFile(forReading: url)
        guard let format = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: file.processingFormat.sampleRate,
            channels: file.processingFormat.channelCount,
            interleaved: false
        ) else {
            throw AudioPreparationError.conversionFailed("Could not create analysis format for clone reference.")
        }
        let maxFrames = min(file.length, AVAudioFramePosition(24_000 * 30))
        guard maxFrames > 0,
              let buffer = AVAudioPCMBuffer(
                  pcmFormat: format,
                  frameCapacity: AVAudioFrameCount(maxFrames)
              ) else {
            return (0, 0)
        }
        try file.read(into: buffer, frameCount: AVAudioFrameCount(maxFrames))
        let frames = Int(buffer.frameLength)
        let channels = Int(buffer.format.channelCount)
        guard frames > 0, channels > 0 else {
            return (0, 0)
        }

        var peak: Float = 0
        var sumSquares: Double = 0
        var sampleCount = 0
        for channel in 0..<channels {
            guard let samples = buffer.floatChannelData?[channel] else { continue }
            for frame in 0..<frames {
                let value = samples[frame]
                let magnitude = abs(value)
                peak = max(peak, magnitude)
                sumSquares += Double(value * value)
                sampleCount += 1
            }
        }
        guard sampleCount > 0 else { return (0, 0) }
        return (peak, Float((sumSquares / Double(sampleCount)).squareRoot()))
    }

    private static func resolveTranscript(
        requestedTranscript: String?,
        normalizedAudioURL: URL
    ) throws -> (transcript: String?, mode: ResolvedCloneTranscriptMode) {
        if let requestedTranscript {
            return (requestedTranscript, .inline)
        }

        let sidecarURL = normalizedAudioURL.deletingPathExtension().appendingPathExtension("txt")
        guard FileManager.default.fileExists(atPath: sidecarURL.path) else {
            return (nil, .none)
        }

        let text = try String(contentsOf: sidecarURL, encoding: .utf8)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return text.isEmpty ? (nil, .none) : (text, .sidecar)
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

    static func normalizedTranscript(_ transcript: String?) -> String? {
        guard let transcript else { return nil }
        let trimmed = transcript.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
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
        return digest.map { String(format: "%02x", $0) }.joined()
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
        conditioning: ResolvedCloneConditioning? = nil,
        language: String? = nil
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
                clonePromptArtifactDigest(
                    modelID: modelID,
                    conditioning: conditioning,
                    language: language
                ),
                isDirectory: true
            )
        }
        guard let conditioning else { return nil }
        let digest = clonePromptArtifactDigest(
            modelID: modelID,
            conditioning: conditioning,
            language: language
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

    private func clonePromptArtifactDigest(
        modelID: String,
        conditioning: ResolvedCloneConditioning,
        language: String?
    ) -> String {
        let normalizedLanguage = (language ?? "auto")
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
        let identity = [
            modelID,
            conditioning.internalIdentityKey,
            normalizedLanguage.isEmpty ? "auto" : normalizedLanguage,
        ].joined(separator: "|")
        let digest = SHA256.hash(data: Data(identity.utf8))
            .prefix(16)
            .map { String(format: "%02x", $0) }
            .joined()
        return digest
    }

    private func clonePromptArtifactMetadata(
        modelID: String,
        conditioning: ResolvedCloneConditioning,
        language: String?,
        xVectorOnlyMode: Bool,
        modelArtifactIdentity: GenerationSemantics.ClonePromptModelArtifactIdentity,
        clonePromptRuntimeSignature: String
    ) -> VocelloQwen3CloneArtifactMetadata {
        let normalizedLanguage = Self.normalizedClonePromptLanguage(language)
        return VocelloQwen3CloneArtifactMetadata(
            modelID: modelID,
            modelRepository: modelArtifactIdentity.repository,
            modelRevision: modelArtifactIdentity.revision,
            modelArtifactVersion: modelArtifactIdentity.artifactVersion,
            modelIntegrityManifestDigest: modelArtifactIdentity.integrityManifestDigest,
            language: normalizedLanguage,
            sourceAudioFingerprint: conditioning.normalizedReference.fingerprint,
            transcriptHash: conditioning.resolvedTranscript.map(Self.sha256Hex(text:)),
            hasTranscript: conditioning.resolvedTranscript != nil,
            xVectorOnlyMode: xVectorOnlyMode,
            runtimeProfileSignature: clonePromptRuntimeSignature
        )
    }

    private static func normalizedClonePromptLanguage(_ language: String?) -> String {
        let normalized = (language ?? "auto")
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
        return normalized.isEmpty ? "auto" : normalized
    }

    private static func sha256Hex(text: String) -> String {
        SHA256.hash(data: Data(text.utf8))
            .map { String(format: "%02x", $0) }
            .joined()
    }

}

enum NativeSavedVoiceNaming {
    static func normalizedName(_ rawName: String) -> String {
        rawName
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .replacingOccurrences(
                of: #"[\\/:*?"<>|\p{Cc}]"#,
                with: "",
                options: .regularExpression
            )
    }
}
