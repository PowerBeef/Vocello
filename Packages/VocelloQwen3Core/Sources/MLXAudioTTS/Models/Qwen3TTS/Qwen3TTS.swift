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

// mlx-swift-lm 3.x declares its own `Tokenizer`/`TokenizerError` in MLXLMCommon; this runtime
// keeps using the swift-transformers implementations, so module-scope aliases pin bare names to
// the Tokenizers module and keep every reference unambiguous.
typealias Tokenizer = Tokenizers.Tokenizer
typealias TokenizerError = Tokenizers.TokenizerError

/// TEL-001: stage signposts correlate the Qwen hot path with typed chunk timings.
private enum Qwen3Signposts {
    static let signposter = OSSignposter(
        subsystem: "com.qwenvoice.engine.qwen3",
        category: "generation"
    )
}

private func qwen3TTSLog(_ message: String) {
    FileHandle.standardError.write(Data((message + "\n").utf8))
}

/// TEL-001: estimate K+V talker cache bytes for the effective sequence length.
private func estimatedKVCacheFootprintMB(layers: Int, heads: Int, seq: Int, headDim: Int, dtypeBytes: Int) -> Double {
    let bytes = 2 * layers * heads * seq * headDim * dtypeBytes
    return Double(bytes) / Double(1_024 * 1_024)
}

final class CachedTokenizerBox: @unchecked Sendable {
    let tokenizer: Tokenizer

    init(tokenizer: Tokenizer) {
        self.tokenizer = tokenizer
    }
}

/// Phase 9 (runtime component reuse): the loaded 682 MB speech tokenizer is
/// byte-identical across every catalog artifact, so a mode switch may adopt
/// the previous model's tokenizer object instead of re-reading and
/// re-materializing it. Content identity is grounded in the shared-component
/// store's hard links (device/inode/size/mtime of the resolved weights file
/// plus the tokenizer config digest); any stat or hash failure disables
/// caching fail-safe. Ownership follows the registered lock-protected cache
/// invariant: exactly one logical user at a time — the loaded model — with
/// the cache holding the handoff reference between sequential loads.
/// `Qwen3TTSMemoryCaches.clearAll` (memory relief and explicit unload) clears
/// the slot, so pressure never retains it; only an in-process model switch
/// preserves it.
final class CachedSpeechTokenizerBox: @unchecked Sendable {
    let identityKey: String
    let includesEncoder: Bool
    let speechTokenizer: Qwen3TTSSpeechTokenizer

    init(identityKey: String, includesEncoder: Bool, speechTokenizer: Qwen3TTSSpeechTokenizer) {
        self.identityKey = identityKey
        self.includesEncoder = includesEncoder
        self.speechTokenizer = speechTokenizer
    }
}

private struct LoadedTalkerComponents: @unchecked Sendable {
    let talker: Qwen3TTSTalkerForConditionalGeneration
    let speakerEncoder: Qwen3TTSSpeakerEncoder?
    let talkerWeightLoadMS: Int
    let timingsMS: [String: Int]
    let booleanFlags: [String: Bool]
}

private struct LoadedTokenizerComponent: Sendable {
    let tokenizer: (any Tokenizer)?
    let cacheHit: Bool
    let directConfigLoadUsed: Bool
    let directConfigFallbackUsed: Bool
    let loadMS: Int
}

private struct LoadedSpeechTokenizerComponent: @unchecked Sendable {
    let speechTokenizer: Qwen3TTSSpeechTokenizer?
    let loadMS: Int
    let booleanFlags: [String: Bool]
}

private struct QwenPreparedLoadOptions: Sendable {
    var speechTokenizerContentIdentity: String? = nil
    let trustPreparedCheckpoint: Bool
    let preparedDirectoryAlreadyValidated: Bool
    let loadSpeakerEncoder: Bool?
    let loadSpeechTokenizerEncoder: Bool?
    let skipSpeechTokenizerEval: Bool
}

private enum Qwen3CustomVoicePrewarmDepth: String, Sendable {
    case full
    case skipDecoderBucket = "skip-decoder-bucket"
    case skipStreamStep = "skip-stream-step"

    static func resolve(rawValue: String?) -> Qwen3CustomVoicePrewarmDepth {
        guard let rawValue = rawValue?
                .trimmingCharacters(in: .whitespacesAndNewlines)
                .lowercased(),
              !rawValue.isEmpty else {
            return .full
        }

        return Qwen3CustomVoicePrewarmDepth(rawValue: rawValue) ?? .full
    }

    var precompileDecoderBuckets: Bool {
        self != .skipDecoderBucket
    }

    var warmsStreamStep: Bool {
        self != .skipStreamStep
    }

    var booleanFlags: [String: Bool] {
        [
            "custom_prewarm_depth_full": self == .full,
            "custom_prewarm_depth_skip_decoder_bucket": self == .skipDecoderBucket,
            "custom_prewarm_depth_skip_stream_step": self == .skipStreamStep,
        ]
    }
}

private enum Qwen3CustomVoiceGenerationProfile: String, Sendable {
    case baseline
    case balancedShort = "balanced-short"
    case conservativeShort = "conservative-short"
    case fastShort = "fast-short"

    static func resolve(
        explicitProfile: String? = nil
    ) -> Qwen3CustomVoiceGenerationProfile {
        if let explicitProfile = explicitProfile?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased(),
           !explicitProfile.isEmpty {
            return Qwen3CustomVoiceGenerationProfile(rawValue: explicitProfile) ?? .baseline
        }

        return .baseline
    }

    var maxTokenMultiplier: Int {
        switch self {
        case .baseline:
            return 6
        case .balancedShort, .fastShort:
            return 4
        case .conservativeShort:
            return 5
        }
    }

    var minimumGeneratedCodes: Int {
        switch self {
        case .baseline:
            return 75
        case .balancedShort, .conservativeShort:
            return 60
        case .fastShort:
            return 50
        }
    }

    var postFirstStreamChunkMultiplier: Int {
        switch self {
        case .baseline:
            return 1
        case .balancedShort, .conservativeShort:
            return 2
        case .fastShort:
            return 3
        }
    }

    func effectiveMaxTokens(defaultMaxTokens: Int, targetTokenCount: Int) -> Int {
        return min(
            defaultMaxTokens,
            max(minimumGeneratedCodes, targetTokenCount * maxTokenMultiplier)
        )
    }

    func postFirstStreamingChunkSize(baseChunkSize: Int) -> Int {
        max(baseChunkSize, baseChunkSize * postFirstStreamChunkMultiplier)
    }

    var booleanFlags: [String: Bool] {
        [
            "custom_profile_baseline": self == .baseline,
            "custom_profile_balanced_short": self == .balancedShort,
            "custom_profile_conservative_short": self == .conservativeShort,
            "custom_profile_fast_short": self == .fastShort,
        ]
    }
}

private struct Qwen3TokenBudgetPolicy: Sendable {
    let name: String
    let maxTokenMultiplier: Int
    let minimumGeneratedCodes: Int
    let usesDefaultMaxTokens: Bool

    init(
        name: String,
        maxTokenMultiplier: Int,
        minimumGeneratedCodes: Int,
        usesDefaultMaxTokens: Bool = false
    ) {
        self.name = name
        self.maxTokenMultiplier = maxTokenMultiplier
        self.minimumGeneratedCodes = minimumGeneratedCodes
        self.usesDefaultMaxTokens = usesDefaultMaxTokens
    }

    static let officialQuality = Qwen3TokenBudgetPolicy(
        name: "official-quality-max-new-tokens",
        maxTokenMultiplier: 0,
        minimumGeneratedCodes: 0,
        usesDefaultMaxTokens: true
    )

    func effectiveMaxTokens(defaultMaxTokens: Int, targetTokenCount: Int) -> Int {
        if usesDefaultMaxTokens {
            return defaultMaxTokens
        }
        return min(
            defaultMaxTokens,
            max(minimumGeneratedCodes, targetTokenCount * maxTokenMultiplier)
        )
    }
}

private enum Qwen3GenerationSpeedProfile: String, Sendable {
    case current
    case legacy123Memory = "legacy123-memory"
    case adaptiveFailureOnly = "adaptive-failure-only"
    case balancedAllModes = "balanced-all-modes"

    static func resolve(
        explicitProfile: String? = nil
    ) -> Qwen3GenerationSpeedProfile {
        if let explicitProfile = explicitProfile?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased(),
           !explicitProfile.isEmpty {
            return Qwen3GenerationSpeedProfile(rawValue: explicitProfile) ?? .current
        }

        return .current
    }

    func memoryClearCadence(explicitCadence: Int?) -> Int {
        if let explicitCadence {
            return max(0, explicitCadence)
        }
        switch self {
        case .current, .legacy123Memory, .adaptiveFailureOnly, .balancedAllModes:
            return 50
        }
    }

    func tokenBudgetPolicy(
        mode: Qwen3StreamingGenerationMode,
        customVoiceProfile: Qwen3CustomVoiceGenerationProfile
    ) -> Qwen3TokenBudgetPolicy {
        switch self {
        case .current:
            return .officialQuality
        case .legacy123Memory, .adaptiveFailureOnly:
            if mode == .custom {
                return Qwen3TokenBudgetPolicy(
                    name: "custom-\(customVoiceProfile.rawValue)",
                    maxTokenMultiplier: customVoiceProfile.maxTokenMultiplier,
                    minimumGeneratedCodes: customVoiceProfile.minimumGeneratedCodes
                )
            }
            return Qwen3TokenBudgetPolicy(
                name: "baseline",
                maxTokenMultiplier: 6,
                minimumGeneratedCodes: 75
            )
        case .balancedAllModes:
            if mode == .custom {
                return Qwen3TokenBudgetPolicy(
                    name: "balanced-all-modes-custom",
                    maxTokenMultiplier: Qwen3CustomVoiceGenerationProfile.balancedShort.maxTokenMultiplier,
                    minimumGeneratedCodes: Qwen3CustomVoiceGenerationProfile.balancedShort.minimumGeneratedCodes
                )
            }
            return Qwen3TokenBudgetPolicy(
                name: "balanced-all-modes-\(mode.rawValue)",
                maxTokenMultiplier: 5,
                minimumGeneratedCodes: 60
            )
        }
    }

    var booleanFlags: [String: Bool] {
        [
            "generation_speed_profile_current": self == .current,
            "generation_speed_profile_legacy123_memory": self == .legacy123Memory,
            "generation_speed_profile_adaptive_failure_only": self == .adaptiveFailureOnly,
            "generation_speed_profile_balanced_all_modes": self == .balancedAllModes,
        ]
    }
}

private enum Qwen3StreamingGenerationMode: String, Sendable {
    case custom
    case design
    case clone
    case generic

    var timingPrefix: String? {
        switch self {
        case .custom:
            return "custom"
        case .design:
            return "design"
        case .clone:
            return "clone"
        case .generic:
            return nil
        }
    }

    func postFirstStreamChunkMultiplier(customVoiceProfile: Qwen3CustomVoiceGenerationProfile) -> Int {
        switch self {
        case .custom:
            return customVoiceProfile.postFirstStreamChunkMultiplier
        case .design, .clone:
            return 2
        case .generic:
            return 1
        }
    }

    func postFirstStreamingChunkSize(
        baseChunkSize: Int,
        customVoiceProfile: Qwen3CustomVoiceGenerationProfile
    ) -> Int {
        max(
            baseChunkSize,
            baseChunkSize * postFirstStreamChunkMultiplier(customVoiceProfile: customVoiceProfile)
        )
    }
}

fileprivate enum Qwen3TextConditioningMode: String, Sendable {
    case streamingTrailingText = "streaming_trailing_text"
    case fullTextNonStreaming = "full_text_non_streaming"
}

enum Qwen3StreamStepEvalPolicy: String, Sendable {
    case full
    case pipelined
    case eosOnly = "eos-only"
    case deferred

    /// Stage 1 P2a: `.pipelined` is the production default. It submits the
    /// step graph with `asyncEval` and performs the previous chunk's
    /// materialization and channel sends before the token/EOS reads, so host
    /// and channel work overlap the in-flight GPU step. Unlike the null
    /// `.eosOnly`/`.deferred` variants (SAMPLER-001: moving the same sync to
    /// a later read with nothing in between), real work fills the gap.
    /// `.full` remains the synchronous diagnostic for exact per-stage
    /// attribution.
    static func resolve(
        explicitPolicy: String? = nil
    ) -> Qwen3StreamStepEvalPolicy {
        if let explicitPolicy = explicitPolicy?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased(),
           !explicitPolicy.isEmpty {
            return Qwen3StreamStepEvalPolicy(rawValue: explicitPolicy) ?? .pipelined
        }

        return .pipelined
    }

    var booleanFlags: [String: Bool] {
        [
            "stream_step_eval_policy_full": self == .full,
            "stream_step_eval_policy_pipelined": self == .pipelined,
            "stream_step_eval_policy_eos_only": self == .eosOnly,
            "stream_step_eval_policy_deferred": self == .deferred,
        ]
    }

    func shouldDeferAudioMaterialization(
        hasMaterializedSink: Bool,
        clearsAllocatorCacheAfterChunk: Bool
    ) -> Bool {
        self == .pipelined
            && hasMaterializedSink
            && !clearsAllocatorCacheAfterChunk
    }
}

private let talkerEvalLayerBatchSize = 4
private let speechTokenizerEvalBatchSize = 8

/// Thread-safe cache for the immutable text tokenizer only. Speech tokenizers
/// contain mutable decoder streaming state and remain owned by one loaded model;
/// sharing them across engines would bypass each engine's operation lease.
final class Qwen3TTSPreparedComponentCache: Sendable {
    private struct State {
        var tokenizersByPreparedKey: [String: CachedTokenizerBox] = [:]
        var tokenizerLRU: [String] = []
        var residentSpeechTokenizer: CachedSpeechTokenizerBox?
    }

    static let shared = Qwen3TTSPreparedComponentCache()

#if os(iOS)
    private let tokenizerLimit = 1
    /// Adaptive iOS residency (2026-08-01): the f16 codec promotion (§R) cut
    /// the resident decoder to ~218 MB, making residency a candidate on the
    /// 8 GB device class (the Mac's model-switch win is 503 → 0 ms). The
    /// device-class heuristic qualified 2026-08-02 on the paired iPhone 17
    /// Pro with this exact build in its default state:
    /// ios-memory-qualification-20260802-011251 — memoryQualified true, QC
    /// clean, and engagement proven by load-event counts (one speech-tokenizer
    /// load for the Custom→Design→Clone switch sequence instead of three;
    /// retained cost absorbed within run noise). Pressure ownership is
    /// unchanged: critical trim and full unload invalidate the resident cache
    /// regardless.
    static let iosAdaptiveResidencyQualified = true
    /// 8 GB device class; 6 GB devices stay non-resident pending the
    /// hardware-floor feasibility evidence (iphone14pro clamp profile).
    static let iosResidencyMinimumPhysicalMemoryBytes: UInt64 = 7 * 1_073_741_824
    static let speechTokenizerResidencySupported: Bool =
        iosAdaptiveResidencyQualified
            && ProcessInfo.processInfo.physicalMemory >= iosResidencyMinimumPhysicalMemoryBytes
#else
    private let tokenizerLimit = 3
    static let speechTokenizerResidencySupported = true
#endif

    /// Registered diagnostic switch for the phase 9 residency A/B (inert
    /// without the QWENVOICE_DEBUG master gate). `off`-family values disable
    /// residency anywhere; `on`-family values force-enable it — the iOS
    /// qualification lane's entry point while the adaptive heuristic is dark.
    private static let speechTokenizerResidencyOverride: String? =
        VocelloQwen3ImplementationDebugGate.value(
            for: "QWENVOICE_TOKENIZER_RESIDENCY"
        )?
        .trimmingCharacters(in: .whitespacesAndNewlines)
        .lowercased()

    private static let speechTokenizerResidencyDisabled: Bool = {
        let raw = speechTokenizerResidencyOverride
        return raw == "off" || raw == "false" || raw == "0" || raw == "no"
    }()

    private static let speechTokenizerResidencyForcedOn: Bool = {
        let raw = speechTokenizerResidencyOverride
        return raw == "on" || raw == "true" || raw == "1" || raw == "yes"
    }()

    static var speechTokenizerResidencyEnabled: Bool {
        if speechTokenizerResidencyForcedOn { return true }
        return speechTokenizerResidencySupported && !speechTokenizerResidencyDisabled
    }

    private let state = OSAllocatedUnfairLock(initialState: State())

    func cachedTokenizer(for preparedKey: String) -> CachedTokenizerBox? {
        state.withLock { value in
            guard let box = value.tokenizersByPreparedKey[preparedKey] else {
                return nil
            }
            Self.touch(preparedKey, in: &value.tokenizerLRU)
            return box
        }
    }

    func storeTokenizer(_ tokenizer: Tokenizer, for preparedKey: String) {
        let box = CachedTokenizerBox(tokenizer: tokenizer)
        state.withLock { value in
            value.tokenizersByPreparedKey[preparedKey] = box
            Self.touch(preparedKey, in: &value.tokenizerLRU)
            Self.trim(
                keys: &value.tokenizerLRU,
                values: &value.tokenizersByPreparedKey,
                limit: tokenizerLimit
            )
        }
    }

    /// Exact content identity, superset capability: a resident that carries
    /// the encoder may serve a decoder-only load (custom/design switching
    /// away from a clone model), but a decoder-only resident can never serve
    /// an encoder-needing load — that one falls through to the disk load.
    func residentSpeechTokenizer(
        identityKey: String,
        includeEncoder: Bool
    ) -> CachedSpeechTokenizerBox? {
        guard Self.speechTokenizerResidencyEnabled else { return nil }
        return state.withLock { value in
            guard let box = value.residentSpeechTokenizer,
                  box.identityKey == identityKey,
                  !includeEncoder || box.includesEncoder else {
                return nil
            }
            return box
        }
    }

    func storeResidentSpeechTokenizer(
        _ speechTokenizer: Qwen3TTSSpeechTokenizer,
        identityKey: String,
        includesEncoder: Bool
    ) {
        guard Self.speechTokenizerResidencyEnabled else { return }
        let box = CachedSpeechTokenizerBox(
            identityKey: identityKey,
            includesEncoder: includesEncoder,
            speechTokenizer: speechTokenizer
        )
        state.withLock { value in
            value.residentSpeechTokenizer = box
        }
    }

    func clear() {
        state.withLock { value in
            value.tokenizersByPreparedKey.removeAll()
            value.tokenizerLRU.removeAll()
            value.residentSpeechTokenizer = nil
        }
    }

    private static func touch(_ key: String, in keys: inout [String]) {
        keys.removeAll { $0 == key }
        keys.append(key)
    }

    private static func trim<Value>(
        keys: inout [String],
        values: inout [String: Value],
        limit: Int
    ) {
        while keys.count > limit, let evicted = keys.first {
            keys.removeFirst()
            values.removeValue(forKey: evicted)
        }
    }
}

enum Qwen3TTSReferenceAudio {
    /// Reference audio uses the codec's fixed 24 kHz contract.
    static let sampleRate = 24_000

    /// Trailing silence appended to the reference before codec encode on the
    /// ICL path, matching upstream Qwen3-TTS reference preprocessing. The
    /// padding gives the tokenizer a clean utterance boundary so clone takes
    /// stop inheriting a truncated final phoneme from the reference.
    static let codecEncodeTrailingSilenceSamples = sampleRate / 2

    /// Version token for ICL reference-encode preprocessing. It participates
    /// in the persisted clone-artifact conditioning version, so any change to
    /// how the reference is prepared for `speechTokenizer.encode` must change
    /// this string to force fail-closed artifact and cache rebuilds.
    static let codecEncodeConditioningVersion = "icl-ref-silence500ms-v2"

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

    /// Canonical `[1, 1, T + pad]` codec-encoder input with the trailing
    /// silence applied. x-vector extraction keeps the unpadded reference.
    static func encoderInputWithTrailingSilence(_ audio: MLXArray) throws -> MLXArray {
        let monoBatch = try canonicalMonoBatch(audio)
        let silence = MLXArray.zeros(
            [1, codecEncodeTrailingSilenceSamples],
            dtype: monoBatch.dtype
        )
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
    /// version with the ICL reference-encode preprocessing version, so a
    /// change to either rejects stale artifacts at load and the host rebuilds
    /// them fail-closed from the source reference.
    public static let speakerFeatureVersion =
        "\(Qwen3TTSSpeakerMelFrontend.featureVersion)+\(Qwen3TTSReferenceAudio.codecEncodeConditioningVersion)"
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

        let allFinite = isFinite(canonical).all()
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

private struct CachedConditioningPrefix: @unchecked Sendable {
    let inputPrefixEmbeds: MLXArray
    let codecLastEmbed: MLXArray
    let ttsEosEmbed: MLXArray
    let ttsPadEmbed: MLXArray
}

private final class CachedConditioningPrefixBox: @unchecked Sendable {
    let prefix: CachedConditioningPrefix

    init(prefix: CachedConditioningPrefix) {
        self.prefix = prefix
    }
}

private final class Qwen3TTSConditioningPrefixCache: @unchecked Sendable {
    static let shared = Qwen3TTSConditioningPrefixCache()

#if os(iOS)
    private let limit = 2
#else
    private let limit = 16
#endif
    private let lock = NSLock()
    private var prefixesByKey: [String: CachedConditioningPrefixBox] = [:]
    private var lruKeys: [String] = []

    func cachedPrefix(for cacheKey: String) -> CachedConditioningPrefix? {
        lock.lock()
        defer { lock.unlock() }
        guard let box = prefixesByKey[cacheKey] else {
            return nil
        }
        touch(cacheKey)
        return box.prefix
    }

    func storePrefix(_ prefix: CachedConditioningPrefix, for cacheKey: String) {
        lock.lock()
        prefixesByKey[cacheKey] = CachedConditioningPrefixBox(prefix: prefix)
        touch(cacheKey)
        trimIfNeeded()
        lock.unlock()
    }

    func clear() {
        lock.lock()
        prefixesByKey.removeAll()
        lruKeys.removeAll()
        lock.unlock()
        Memory.clearCache()
    }

    private func touch(_ cacheKey: String) {
        lruKeys.removeAll { $0 == cacheKey }
        lruKeys.append(cacheKey)
    }

    private func trimIfNeeded() {
        while lruKeys.count > limit, let evicted = lruKeys.first {
            lruKeys.removeFirst()
            prefixesByKey.removeValue(forKey: evicted)
        }
    }
}

private final class Qwen3TTSStreamingDecoderBucketCache: @unchecked Sendable {
    static let shared = Qwen3TTSStreamingDecoderBucketCache()

#if os(iOS)
    private let limit = 2
#else
    private let limit = 8
#endif
    private let lock = NSLock()
    private var warmedKeys: Set<String> = []
    private var lruKeys: [String] = []

    func contains(_ key: String) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        let contains = warmedKeys.contains(key)
        if contains {
            touch(key)
        }
        return contains
    }

    func insert(_ key: String) {
        lock.lock()
        warmedKeys.insert(key)
        touch(key)
        trimIfNeeded()
        lock.unlock()
    }

    func clear() {
        lock.lock()
        warmedKeys.removeAll()
        lruKeys.removeAll()
        lock.unlock()
        Memory.clearCache()
    }

    private func touch(_ key: String) {
        lruKeys.removeAll { $0 == key }
        lruKeys.append(key)
    }

    private func trimIfNeeded() {
        while lruKeys.count > limit, let evicted = lruKeys.first {
            lruKeys.removeFirst()
            warmedKeys.remove(evicted)
        }
    }
}

public enum Qwen3TTSMemoryCaches {
    public static func clearAll(
        isolation: isolated (any Actor)? = #isolation
    ) async {
        _ = isolation
        Qwen3TTSPreparedComponentCache.shared.clear()
        Qwen3TTSConditioningPrefixCache.shared.clear()
        Qwen3TTSStreamingDecoderBucketCache.shared.clear()
        Memory.clearCache()
    }
}

actor Qwen3TTSGenerationGate {
    private struct Waiter {
        let id: UUID
        let continuation: CheckedContinuation<Void, Error>
    }

    private var isHeld = false
    private var waiters: [Waiter] = []
    private let afterTransferHook: (@Sendable () async -> Void)?

    init(afterTransferHook: (@Sendable () async -> Void)? = nil) {
        self.afterTransferHook = afterTransferHook
    }

    func acquire() async throws {
        let id = UUID()
        try Task.checkCancellation()

        if !isHeld {
            isHeld = true
            return
        }

        var gateAcquired = false
        do {
            try await withTaskCancellationHandler {
                try await waitForTurn(id: id)
                // waitForTurn only returns if the continuation was resumed normally
                // by release(), so the gate has been transferred to us.
                gateAcquired = true
                await afterTransferHook?()
            } onCancel: {
                Task { await self.cancelWaiter(id: id) }
            }
            // Keep the post-transfer cancellation check inside the scope whose
            // catch releases ownership. A cancellation between continuation
            // resume and acquire() return must never strand the gate held.
            try Task.checkCancellation()
        } catch {
            // Only release the gate if it was actually transferred to us. If we
            // were cancelled while still queued, cancelWaiter removed us and the
            // gate is still owned by the current generation.
            if gateAcquired {
                release()
            }
            throw error
        }

    }

    func release() {
        guard !waiters.isEmpty else {
            isHeld = false
            return
        }

        let waiter = waiters.removeFirst()
        waiter.continuation.resume()
    }

    var queuedWaiterCount: Int { waiters.count }

    nonisolated func withPermit<T: Sendable>(
        _ operation: @Sendable () async throws -> T
    ) async throws -> T {
        try await acquire()
        do {
            try Task.checkCancellation()
            let result = try await operation()
            await release()
            return result
        } catch {
            await release()
            throw error
        }
    }

    private func waitForTurn(id: UUID) async throws {
        try Task.checkCancellation()
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            guard !Task.isCancelled else {
                continuation.resume(throwing: CancellationError())
                return
            }
            waiters.append(Waiter(id: id, continuation: continuation))
        }
    }

    private func cancelWaiter(id: UUID) {
        guard let index = waiters.firstIndex(where: { $0.id == id }) else {
            return
        }
        let waiter = waiters.remove(at: index)
        waiter.continuation.resume(throwing: CancellationError())
    }
}

enum Qwen3LearnedComponentWeights {
    static func requireNonEmpty(
        _ count: Int,
        component: String
    ) throws {
        guard count > 0 else {
            throw AudioGenerationError.invalidInput(
                "Requested learned component '\(component)' has no verified weights."
            )
        }
    }
}

struct Qwen3StreamChunkSchedule: Sendable {
    let firstChunkSize: Int
    let laterChunkSize: Int
    private(set) var pendingCount = 0
    private(set) var emittedChunkCount = 0
    private(set) var peakPendingCount = 0

    init(firstChunkSize: Int, laterChunkSize: Int) {
        self.firstChunkSize = max(1, firstChunkSize)
        self.laterChunkSize = max(1, laterChunkSize)
    }

    var requiredChunkSize: Int {
        emittedChunkCount == 0 ? firstChunkSize : laterChunkSize
    }

    mutating func append() -> Bool {
        pendingCount += 1
        peakPendingCount = max(peakPendingCount, pendingCount)
        return pendingCount >= requiredChunkSize
    }

    mutating func didEmit() {
        precondition(pendingCount <= requiredChunkSize, "pending stream retention exceeded its bounded schedule")
        pendingCount = 0
        emittedChunkCount += 1
    }
}

// MARK: - Qwen3TTS Model

public final class Qwen3TTSModel: Module, SpeechGenerationModel, Qwen3OptimizedSpeechGenerationModel, Qwen3PreparedQualityGenerationModel, Qwen3SuspendingSpeechGenerationModel, Qwen3CodecTraceReplayModel, Qwen3CustomVoicePrewarmDepthControlling, SpeechGenerationModelDiagnosticsProvider, @unchecked Sendable {
    private static let productionMinimumGeneratedCodeTokensBeforeEOS = 2
    private static let productionFullResultMemoryClearCadence = 0

    let config: Qwen3TTSModelConfig
    let talker: Qwen3TTSTalkerForConditionalGeneration
    var speakerEncoder: Qwen3TTSSpeakerEncoder?
    var speechTokenizer: Qwen3TTSSpeechTokenizer?
    var tokenizer: Tokenizer?
    private var preparedKey: String?
    private let diagnosticsLock = NSLock()
    private var storedLoadTimingsMS: [String: Int] = [:]
    private var storedLoadBooleanFlags: [String: Bool] = [:]
    private var storedPreparationTimingsMS: [String: Int] = [:]
    private var storedPreparationBooleanFlags: [String: Bool] = [:]
    private var storedPreparationStringFlags: [String: String] = [:]
    private let generationGate = Qwen3TTSGenerationGate()

    public var sampleRate: Int { config.sampleRate }
    public var loadTimingsMS: [String: Int] {
        diagnosticsLock.lock()
        defer { diagnosticsLock.unlock() }
        return storedLoadTimingsMS
    }

    public var loadBooleanFlags: [String: Bool] {
        diagnosticsLock.lock()
        defer { diagnosticsLock.unlock() }
        return storedLoadBooleanFlags
    }

    public var latestPreparationTimingsMS: [String: Int] {
        diagnosticsLock.lock()
        defer { diagnosticsLock.unlock() }
        return storedPreparationTimingsMS
    }

    public var latestPreparationBooleanFlags: [String: Bool] {
        diagnosticsLock.lock()
        defer { diagnosticsLock.unlock() }
        return storedPreparationBooleanFlags
    }

    public var latestPreparationStringFlags: [String: String] {
        diagnosticsLock.lock()
        defer { diagnosticsLock.unlock() }
        return storedPreparationStringFlags
    }

    public func resetPreparationDiagnostics() {
        diagnosticsLock.lock()
        storedPreparationTimingsMS = [:]
        storedPreparationBooleanFlags = [:]
        storedPreparationStringFlags = [:]
        diagnosticsLock.unlock()
    }

    public var defaultGenerationParameters: GenerateParameters {
        GenerateParameters(
            maxTokens: 2048,
            temperature: 0.9,
            topP: 1.0,
            repetitionPenalty: 1.05
        )
    }

    private var supportsCustomInstructionControl: Bool {
        !(config.ttsModelSize == "0b6" && config.ttsModelType == "custom_voice")
    }

    private func trimmedInstruction(_ instruct: String?) -> String? {
        guard let instruct else { return nil }
        let trimmed = instruct.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }

    private func customVoiceInstruction(_ instruct: String?) -> String? {
        guard supportsCustomInstructionControl else { return nil }
        return trimmedInstruction(instruct)
    }

    private func normalizedConditioningCacheKeyText(_ text: String) -> String {
        text
            .replacingOccurrences(
                of: #"\s+"#,
                with: " ",
                options: .regularExpression
            )
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
    }

    private func conditioningCacheKey(for mode: String) -> String? {
        guard let preparedKey else { return nil }
        return "\(preparedKey)|\(mode)"
    }

    private func decoderBucketCacheKey() -> String? {
        guard let preparedKey else { return nil }
        return "\(preparedKey)|decoder_buckets|4,1,2,3"
    }

    private func decoderBucketCacheHit() -> Bool {
        guard let cacheKey = decoderBucketCacheKey() else { return false }
        return Qwen3TTSStreamingDecoderBucketCache.shared.contains(cacheKey)
    }

    private func resolvedLanguageIdentifier(language: String, speaker: String? = nil) -> Int? {
        guard let talkerConfig = config.talkerConfig else { return nil }

        let normalizedLanguage = language.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let normalizedSpeaker = speaker?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()

        if (normalizedLanguage == "auto" || normalizedLanguage == "chinese"),
           let normalizedSpeaker,
           let dialect = talkerConfig.spkIsDialect?[normalizedSpeaker],
           let dialectLanguageID = talkerConfig.codecLanguageId?[dialect] {
            return dialectLanguageID
        }

        guard normalizedLanguage != "auto" else {
            return nil
        }
        return talkerConfig.codecLanguageId?[normalizedLanguage]
    }

    private func speakerTokenEmbeddings(for speaker: String?) throws -> MLXArray? {
        guard let talkerConfig = config.talkerConfig else { return nil }
        guard let speaker else { return nil }

        let normalizedSpeaker = speaker.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !normalizedSpeaker.isEmpty else { return nil }
        guard let speakerIDs = talkerConfig.spkId?[normalizedSpeaker], !speakerIDs.isEmpty else {
            throw AudioGenerationError.modelNotInitialized(
                "Unsupported Qwen3 speaker '\(speaker)'"
            )
        }

        let tokenIDs = MLXArray(speakerIDs.map(Int32.init)).reshaped(1, -1)
        return talker.getInputEmbeddings()(tokenIDs)
    }

    private func prefixCacheKeyForCustomVoice(language: String, speaker: String, instruct: String?) -> String? {
        let normalizedLanguage = language.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let normalizedSpeaker = speaker.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let normalizedInstruction = trimmedInstruction(instruct)?.lowercased() ?? ""
        return conditioningCacheKey(
            for: "custom|\(normalizedLanguage)|\(normalizedSpeaker)|\(normalizedInstruction)"
        )
    }

    private func prefixCacheKeyForVoiceDesign(language: String, voiceDescription: String) -> String? {
        let normalizedLanguage = language.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let normalizedDescription = normalizedConditioningCacheKeyText(voiceDescription)
        return conditioningCacheKey(
            for: "design|\(normalizedLanguage)|\(normalizedDescription)"
        )
    }

    private func buildConditioningPrefix(
        language: String,
        speaker: String?,
        instruct: String?,
        cacheKey: String?
    ) throws -> (CachedConditioningPrefix, Bool, Int, Int) {
        let prefixCache = Qwen3TTSConditioningPrefixCache.shared
        if let cacheKey,
           let cachedPrefix = prefixCache.cachedPrefix(for: cacheKey) {
            return (cachedPrefix, true, 0, 0)
        }

        guard let tokenizer, let talkerConfig = config.talkerConfig else {
            throw AudioGenerationError.modelNotInitialized("Tokenizer/config not loaded")
        }

        let prefixTokenizeStartedAt = ContinuousClock.now

        let ttsTokens = MLXArray(
            [Int32(config.ttsBosTokenId), Int32(config.ttsEosTokenId), Int32(config.ttsPadTokenId)]
        ).reshaped(1, 3)
        let ttsEmbeds = talker.textProjection(talker.getTextEmbeddings()(ttsTokens))
        let ttsBosEmbed = ttsEmbeds[0..., 0 ..< 1, 0...]
        let ttsEosEmbed = ttsEmbeds[0..., 1 ..< 2, 0...]
        let ttsPadEmbed = ttsEmbeds[0..., 2 ..< 3, 0...]

        let languageId = resolvedLanguageIdentifier(language: language, speaker: speaker)
        let codecPrefill: [Int32] = if let languageId {
            [
                Int32(talkerConfig.codecThinkId),
                Int32(talkerConfig.codecThinkBosId),
                Int32(languageId),
                Int32(talkerConfig.codecThinkEosId),
            ]
        } else {
            [
                Int32(talkerConfig.codecNothinkId),
                Int32(talkerConfig.codecThinkBosId),
                Int32(talkerConfig.codecThinkEosId),
            ]
        }

        var codecPrefixEmbed = talker.getInputEmbeddings()(MLXArray(codecPrefill).reshaped(1, -1))
        let codecPrefixSuffix = talker.getInputEmbeddings()(
            MLXArray([Int32(talkerConfig.codecPadId), Int32(talkerConfig.codecBosId)]).reshaped(1, 2)
        )
        if let speakerEmbeds = try speakerTokenEmbeddings(for: speaker) {
            codecPrefixEmbed = concatenated([codecPrefixEmbed, speakerEmbeds, codecPrefixSuffix], axis: 1)
        } else {
            codecPrefixEmbed = concatenated([codecPrefixEmbed, codecPrefixSuffix], axis: 1)
        }

        let assistantPrefix = "<|im_start|>assistant\n"
        let assistantPrefixIDs = MLXArray(tokenizer.encode(text: assistantPrefix).map(Int32.init)).reshaped(1, -1)
        let instructIDs: MLXArray?
        if let instruct = trimmedInstruction(instruct) {
            let instructText = "<|im_start|>user\n\(instruct)<|im_end|>\n"
            instructIDs = MLXArray(tokenizer.encode(text: instructText).map(Int32.init)).reshaped(1, -1)
        } else {
            instructIDs = nil
        }
        let prefixTokenizeMS = prefixTokenizeStartedAt.elapsedMilliseconds

        let prefixEmbedBuildStartedAt = ContinuousClock.now
        let roleEmbed = talker.textProjection(talker.getTextEmbeddings()(assistantPrefixIDs))

        let padCount = codecPrefixEmbed.dim(1) - 2
        let padEmbeds = broadcast(ttsPadEmbed, to: [1, padCount, ttsPadEmbed.dim(-1)])
        var combinedEmbed = concatenated([padEmbeds, ttsBosEmbed], axis: 1)
        combinedEmbed = combinedEmbed + codecPrefixEmbed[0..., ..<(-1), 0...]

        let instructEmbed: MLXArray?
        if let instructIDs {
            instructEmbed = talker.textProjection(talker.getTextEmbeddings()(instructIDs))
        } else {
            instructEmbed = nil
        }

        let inputPrefixEmbeds = if let instructEmbed {
            concatenated([instructEmbed, roleEmbed, combinedEmbed], axis: 1)
        } else {
            concatenated([roleEmbed, combinedEmbed], axis: 1)
        }
        let codecLastEmbed = codecPrefixEmbed[0..., (-1)..., 0...]
        let prefix = CachedConditioningPrefix(
            inputPrefixEmbeds: inputPrefixEmbeds,
            codecLastEmbed: codecLastEmbed,
            ttsEosEmbed: ttsEosEmbed,
            ttsPadEmbed: ttsPadEmbed
        )
        if let cacheKey {
            prefixCache.storePrefix(prefix, for: cacheKey)
        }
        return (prefix, false, prefixTokenizeMS, prefixEmbedBuildStartedAt.elapsedMilliseconds)
    }

    private func prepareInputs(
        text: String,
        prefix: CachedConditioningPrefix
    ) throws -> (
        inputEmbeds: MLXArray,
        trailingTextHidden: MLXArray,
        ttsPadEmbed: MLXArray,
        textPrepareMS: Int,
        targetTokenCount: Int
    ) {
        guard let tokenizer else {
            throw AudioGenerationError.modelNotInitialized("Tokenizer not loaded")
        }

        let textPrepareStartedAt = ContinuousClock.now
        let targetTokenCount = tokenizer.encode(text: text).count
        let chatText = "<|im_start|>assistant\n\(text)<|im_end|>\n<|im_start|>assistant\n"
        let inputIds = MLXArray(tokenizer.encode(text: chatText).map(Int32.init)).reshaped(1, -1)
        let textEmbed = talker.textProjection(talker.getTextEmbeddings()(inputIds))
        try validateOptimizedCustomVoiceTextEmbeddingLength(
            textTokenCount: textEmbed.dim(1),
            originalText: text
        )

        let firstTextEmbed = textEmbed[0..., 3 ..< 4, 0...] + prefix.codecLastEmbed
        let trailingTextHidden = concatenated(
            [textEmbed[0..., 4 ..< (textEmbed.dim(1) - 5), 0...], prefix.ttsEosEmbed],
            axis: 1
        )
        let inputEmbeds = concatenated([prefix.inputPrefixEmbeds, firstTextEmbed], axis: 1)
        return (
            inputEmbeds,
            trailingTextHidden,
            prefix.ttsPadEmbed,
            textPrepareStartedAt.elapsedMilliseconds,
            targetTokenCount
        )
    }

    private func prepareFullTextNonStreamingInputs(
        text: String,
        prefix: CachedConditioningPrefix
    ) throws -> (
        inputEmbeds: MLXArray,
        trailingTextHidden: MLXArray,
        ttsPadEmbed: MLXArray,
        textPrepareMS: Int,
        targetTokenCount: Int
    ) {
        guard let tokenizer, let talkerConfig = config.talkerConfig else {
            throw AudioGenerationError.modelNotInitialized("Tokenizer/config not loaded")
        }

        let textPrepareStartedAt = ContinuousClock.now
        let targetTokenCount = tokenizer.encode(text: text).count
        let chatText = "<|im_start|>assistant\n\(text)<|im_end|>\n<|im_start|>assistant\n"
        let inputIds = MLXArray(tokenizer.encode(text: chatText).map(Int32.init)).reshaped(1, -1)
        let textEmbed = talker.textProjection(talker.getTextEmbeddings()(inputIds))
        try validateOptimizedCustomVoiceTextEmbeddingLength(
            textTokenCount: textEmbed.dim(1),
            originalText: text
        )

        let targetTextEmbed = concatenated(
            [textEmbed[0..., 3 ..< (textEmbed.dim(1) - 5), 0...], prefix.ttsEosEmbed],
            axis: 1
        )
        let codecPadIDs = MLXArray(
            Array(
                repeating: Int32(talkerConfig.codecPadId),
                count: targetTextEmbed.dim(1)
            )
        ).reshaped(1, -1)
        let fullTextOverlay = targetTextEmbed + talker.getInputEmbeddings()(codecPadIDs)
        let codecBosOverlay = prefix.ttsPadEmbed + prefix.codecLastEmbed
        let inputEmbeds = concatenated(
            [prefix.inputPrefixEmbeds, fullTextOverlay, codecBosOverlay],
            axis: 1
        )

        return (
            inputEmbeds,
            prefix.ttsPadEmbed,
            prefix.ttsPadEmbed,
            textPrepareStartedAt.elapsedMilliseconds,
            targetTokenCount
        )
    }

    private func prepareCustomVoiceInputs(
        text: String,
        language: String,
        speaker: String,
        instruct: String?,
        textConditioningMode: Qwen3TextConditioningMode = .streamingTrailingText
    ) throws -> (
        inputEmbeds: MLXArray,
        trailingTextHidden: MLXArray,
        ttsPadEmbed: MLXArray,
        prefixCacheHit: Bool,
        timingsMS: [String: Int],
        targetTokenCount: Int
    ) {
        let resolvedInstruct = customVoiceInstruction(instruct)
        let prefixPrepareStartedAt = ContinuousClock.now
        let cacheKey = prefixCacheKeyForCustomVoice(
            language: language,
            speaker: speaker,
            instruct: resolvedInstruct
        )
        let (prefix, cacheHit, prefixTokenizeMS, prefixEmbedBuildMS) = try buildConditioningPrefix(
            language: language,
            speaker: speaker,
            instruct: resolvedInstruct,
            cacheKey: cacheKey
        )
        let prepared: (
            inputEmbeds: MLXArray,
            trailingTextHidden: MLXArray,
            ttsPadEmbed: MLXArray,
            textPrepareMS: Int,
            targetTokenCount: Int
        )
        switch textConditioningMode {
        case .streamingTrailingText:
            prepared = try prepareInputs(text: text, prefix: prefix)
        case .fullTextNonStreaming:
            prepared = try prepareFullTextNonStreamingInputs(text: text, prefix: prefix)
        }
        let customTimingsMS = [
            "custom_prefix_prepare": prefixPrepareStartedAt.elapsedMilliseconds,
            "custom_prefix_tokenize_ms": prefixTokenizeMS,
            "custom_prefix_embed_build_ms": prefixEmbedBuildMS,
            "custom_text_prepare_ms": prepared.textPrepareMS,
        ]
        return (
            prepared.inputEmbeds,
            prepared.trailingTextHidden,
            prepared.ttsPadEmbed,
            cacheHit,
            customTimingsMS,
            prepared.targetTokenCount
        )
    }

    private func prepareVoiceDesignInputs(
        text: String,
        language: String,
        voiceDescription: String,
        textConditioningMode: Qwen3TextConditioningMode = .streamingTrailingText
    ) throws -> (
        inputEmbeds: MLXArray,
        trailingTextHidden: MLXArray,
        ttsPadEmbed: MLXArray,
        prefixCacheHit: Bool,
        timingsMS: [String: Int],
        targetTokenCount: Int
    ) {
        let prefixPrepareStartedAt = ContinuousClock.now
        let cacheKey = prefixCacheKeyForVoiceDesign(
            language: language,
            voiceDescription: voiceDescription
        )
        let (prefix, cacheHit, prefixTokenizeMS, prefixEmbedBuildMS) = try buildConditioningPrefix(
            language: language,
            speaker: nil,
            instruct: voiceDescription,
            cacheKey: cacheKey
        )
        let prepared: (
            inputEmbeds: MLXArray,
            trailingTextHidden: MLXArray,
            ttsPadEmbed: MLXArray,
            textPrepareMS: Int,
            targetTokenCount: Int
        )
        switch textConditioningMode {
        case .streamingTrailingText:
            prepared = try prepareInputs(text: text, prefix: prefix)
        case .fullTextNonStreaming:
            prepared = try prepareFullTextNonStreamingInputs(text: text, prefix: prefix)
        }
        let designTimingsMS = [
            "design_prefix_prepare": prefixPrepareStartedAt.elapsedMilliseconds,
            "design_prefix_tokenize_ms": prefixTokenizeMS,
            "design_prefix_embed_build_ms": prefixEmbedBuildMS,
            "design_text_prepare_ms": prepared.textPrepareMS,
        ]
        return (
            prepared.inputEmbeds,
            prepared.trailingTextHidden,
            prepared.ttsPadEmbed,
            cacheHit,
            designTimingsMS,
            prepared.targetTokenCount
        )
    }

    private func warmPreparedInputs(
        _ inputEmbedsInit: MLXArray,
        trailingTextHidden: MLXArray? = nil,
        ttsPadEmbed: MLXArray? = nil,
        inputPreparationMS: Int,
        booleanFlags: [String: Bool] = [:],
        additionalTimingsMS: [String: Int] = [:],
        preparationEvalTimingKey: String? = nil,
        streamStepEvalTimingKey: String? = nil,
        streamStepWarmBooleanFlag: String? = nil,
        precompileDecoderBuckets: Bool = true,
        memoryPolicy: Qwen3RequestMemoryPolicy = .compatibilityDefault,
        isolation: isolated (any Actor)? = #isolation
    ) async throws {
        _ = isolation
        guard let speechTokenizer else {
            throw AudioGenerationError.modelNotInitialized("Speech tokenizer not loaded")
        }
        defer {
            Memory.clearCache()
        }

        let cache: [any KVCache]
        if let talkerKVWindow = memoryPolicy.talkerKVGeneratedWindow {
            // Sliding-window talker KV (constrained tiers): keep = the conditioning
            // prefill length (control + full text, always at the front of the
            // sequence), so only old generated audio-codec tokens rotate out.
            cache = talker.makeRotatingCache(
                keep: inputEmbedsInit.dim(1), window: talkerKVWindow
            )
        } else {
            cache = talker.makeCache()
        }
        let codeCache = talker.codePredictor.makeCache()
        let (logits, hidden) = talker(inputEmbedsInit, cache: cache)
        let nextToken = argMax(
            logits[0..., (-1)..., 0...].squeezed(axis: 1),
            axis: -1,
            keepDims: true
        )
        let talkerConfig = config.talkerConfig!
        let eosTokenArray = MLXArray([Int32(talkerConfig.codecEosTokenId)]).reshaped(1, 1)
        let isEOS = nextToken .== eosTokenArray

        let codeHidden = hidden[0..., (-1)..., 0...]
        var codeTokens = [nextToken]

        for layerCache in codeCache {
            _ = layerCache.trim(layerCache.offset)
        }

        if talkerConfig.numCodeGroups > 1 {
            for codeIdx in 0 ..< talkerConfig.numCodeGroups - 1 {
                let codeInput: MLXArray
                if codeIdx == 0 {
                    let code0Embed = talker.getInputEmbeddings()(nextToken)
                    codeInput = concatenated([codeHidden, code0Embed], axis: 1)
                } else {
                    codeInput = talker.codePredictor.codecEmbedding[codeIdx - 1](codeTokens.last!)
                }

                let (codeLogits, _, _) = talker.codePredictor(
                    codeInput,
                    cache: codeCache,
                    generationStep: codeIdx
                )
                let nextCode = argMax(
                    codeLogits[0..., (-1)..., 0...].squeezed(axis: 1),
                    axis: -1,
                    keepDims: true
                )
                codeTokens.append(nextCode)
            }
        }

        let allCodes = concatenated(codeTokens, axis: 1)
        let codesChunk = stacked([allCodes], axis: 1)
        let codesForDecoder = codesChunk.transposed(0, 2, 1)
        let decoderStartedAt = ContinuousClock.now
        let decoded = speechTokenizer.decoder.streamingStep(codesForDecoder).squeezed(axis: 1)
        let firstDecoderStepMS = decoderStartedAt.elapsedMilliseconds
        var preparationBooleanFlags = booleanFlags
        let decoderBucketWarmStartedAt = ContinuousClock.now
        let decoderBucketCacheHit: Bool
        let decoderBucketWarmMS: Int
        if precompileDecoderBuckets {
            decoderBucketCacheHit = try precompileStreamingDecoderBuckets(with: codesForDecoder)
            decoderBucketWarmMS = decoderBucketCacheHit ? 0 : decoderBucketWarmStartedAt.elapsedMilliseconds
        } else {
            decoderBucketCacheHit = self.decoderBucketCacheHit()
            decoderBucketWarmMS = 0
            preparationBooleanFlags["decoder_bucket_precompile_skipped"] = true
        }
        preparationBooleanFlags["decoder_bucket_cache_hit"] = decoderBucketCacheHit
        speechTokenizer.decoder.resetStreamingState()
        let preparationEvalStartedAt = ContinuousClock.now
        eval(logits, hidden, allCodes, codesForDecoder, decoded)
        var timingsMS = [
            "prepare_inputs": inputPreparationMS,
            "first_decoder_step": firstDecoderStepMS,
            "decoder_bucket_warm": decoderBucketWarmMS,
        ].merging(additionalTimingsMS) { _, rhs in rhs }
        if let preparationEvalTimingKey {
            timingsMS[preparationEvalTimingKey] = preparationEvalStartedAt.elapsedMilliseconds
        }
        if let streamStepEvalTimingKey,
           let trailingTextHidden,
           let ttsPadEmbed
        {
            let nextTextEmbed: MLXArray
            if trailingTextHidden.dim(1) > 0 {
                nextTextEmbed = trailingTextHidden[0..., 0 ..< 1, 0...]
            } else {
                nextTextEmbed = ttsPadEmbed
            }

            var codecEmbed = talker.getInputEmbeddings()(nextToken)
            for (index, code) in codeTokens.dropFirst().enumerated() {
                codecEmbed = codecEmbed + talker.codePredictor.codecEmbedding[index](code)
            }

            let nextInputEmbeds = nextTextEmbed + codecEmbed
            let streamStepWarmStartedAt = ContinuousClock.now
            eval(nextInputEmbeds, isEOS)
            timingsMS[streamStepEvalTimingKey] = streamStepWarmStartedAt.elapsedMilliseconds
            if let streamStepWarmBooleanFlag {
                preparationBooleanFlags[streamStepWarmBooleanFlag] = true
            }
        }
        storePreparationTimingsMS(timingsMS)
        mergePreparationBooleanFlags(preparationBooleanFlags)
    }

    @discardableResult
    private func precompileStreamingDecoderBuckets(with codesForDecoder: MLXArray) throws -> Bool {
        guard let speechTokenizer else {
            throw AudioGenerationError.modelNotInitialized("Speech tokenizer not loaded")
        }

        if let cacheKey = decoderBucketCacheKey(),
           Qwen3TTSStreamingDecoderBucketCache.shared.contains(cacheKey) {
            speechTokenizer.decoder.resetStreamingState()
            return true
        }

        for bucketSize in [4, 1, 2, 3] {
            speechTokenizer.decoder.resetStreamingState()
            let bucketCodes = concatenated(
                Array(repeating: codesForDecoder, count: bucketSize),
                axis: 2
            )
            let decoded = speechTokenizer.decoder.streamingStep(bucketCodes)
            eval(bucketCodes, decoded)
        }
        speechTokenizer.decoder.resetStreamingState()
        if let cacheKey = decoderBucketCacheKey() {
            Qwen3TTSStreamingDecoderBucketCache.shared.insert(cacheKey)
        }
        return false
    }

    public func prepareCustomVoice(
        text: String,
        language: String,
        speaker: String,
        instruct: String?,
        generationParameters: GenerateParameters,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        isolation: isolated (any Actor)? = #isolation
    ) async throws {
        try await prepareCustomVoice(
            text: text,
            language: language,
            speaker: speaker,
            instruct: instruct,
            generationParameters: generationParameters,
            memoryPolicy: memoryPolicy,
            customPrewarmDepth: nil,
            isolation: isolation
        )
    }

    public func prepareCustomVoice(
        text: String,
        language: String,
        speaker: String,
        instruct: String?,
        generationParameters: GenerateParameters,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        customPrewarmDepth: String?,
        isolation: isolated (any Actor)? = #isolation
    ) async throws {
        try await withGenerationGate(isolation: isolation) {
        guard speechTokenizer != nil else {
            throw AudioGenerationError.modelNotInitialized("Speech tokenizer not loaded")
        }
        guard tokenizer != nil else {
            throw AudioGenerationError.modelNotInitialized("Text tokenizer not loaded")
        }

        let startedAt = ContinuousClock.now
        let (inputEmbedsInit, trailingTextHidden, ttsPadEmbed, prefixCacheHit, customPrefixPrepareMS, _) = try prepareCustomVoiceInputs(
            text: text,
            language: language,
            speaker: speaker,
            instruct: instruct
        )
        let prewarmDepth = Qwen3CustomVoicePrewarmDepth.resolve(rawValue: customPrewarmDepth)
        try await warmPreparedInputs(
            inputEmbedsInit,
            trailingTextHidden: trailingTextHidden,
            ttsPadEmbed: ttsPadEmbed,
            inputPreparationMS: startedAt.elapsedMilliseconds,
            booleanFlags: [
                "prefix_cache_hit": prefixCacheHit,
                "custom_prefix_cache_hit": prefixCacheHit,
                "custom_speaker_conditioning_used": true,
            ].merging(prewarmDepth.booleanFlags) { _, rhs in rhs },
            additionalTimingsMS: customPrefixPrepareMS,
            preparationEvalTimingKey: "custom_prewarm_eval_ms",
            streamStepEvalTimingKey: prewarmDepth.warmsStreamStep ? "custom_stream_step_warm_ms" : nil,
            streamStepWarmBooleanFlag: "custom_stream_step_prewarmed",
            precompileDecoderBuckets: prewarmDepth.precompileDecoderBuckets,
            memoryPolicy: memoryPolicy,
            isolation: isolation
        )
        }
    }

    public func prepareVoiceDesign(
        text: String,
        language: String,
        voiceDescription: String,
        generationParameters _: GenerateParameters,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        isolation: isolated (any Actor)? = #isolation
    ) async throws {
        try await withGenerationGate(isolation: isolation) {
        guard speechTokenizer != nil else {
            throw AudioGenerationError.modelNotInitialized("Speech tokenizer not loaded")
        }
        guard tokenizer != nil else {
            throw AudioGenerationError.modelNotInitialized("Text tokenizer not loaded")
        }

        let startedAt = ContinuousClock.now
        let (inputEmbedsInit, trailingTextHidden, ttsPadEmbed, prefixCacheHit, designPrefixPrepareMS, _) = try prepareVoiceDesignInputs(
            text: text,
            language: language,
            voiceDescription: voiceDescription
        )
        try await warmPreparedInputs(
            inputEmbedsInit,
            trailingTextHidden: trailingTextHidden,
            ttsPadEmbed: ttsPadEmbed,
            inputPreparationMS: startedAt.elapsedMilliseconds,
            booleanFlags: [
                "prefix_cache_hit": prefixCacheHit,
                "design_prefix_cache_hit": prefixCacheHit,
            ],
            additionalTimingsMS: designPrefixPrepareMS,
            preparationEvalTimingKey: "design_prewarm_eval_ms",
            streamStepEvalTimingKey: "design_stream_step_warm_ms",
            streamStepWarmBooleanFlag: "design_stream_step_prewarmed",
            memoryPolicy: memoryPolicy,
            isolation: isolation
        )
        }
    }

    public func createVoiceClonePrompt(
        refAudio: MLXArray,
        refText: String?,
        xVectorOnlyMode: Bool
    ) throws -> Qwen3TTSVoiceClonePrompt {
        guard config.ttsModelType == "base" else {
            throw AudioGenerationError.modelNotInitialized(
                "Qwen3 clone prompt creation requires the base model."
            )
        }

        let normalizedRefText = refText?.trimmingCharacters(in: .whitespacesAndNewlines)
        let iclMode = !xVectorOnlyMode
        if iclMode, normalizedRefText?.isEmpty ?? true {
            throw AudioGenerationError.modelNotInitialized(
                "Qwen3 clone prompt creation requires a transcript when x_vector_only_mode is false."
            )
        }

        let speakerEmbedding = try extractSpeakerEmbedding(refAudio)
        if xVectorOnlyMode, speakerEmbedding == nil {
            throw AudioGenerationError.modelNotInitialized(
                "Qwen3 x-vector clone prompt creation requires an initialized speaker encoder."
            )
        }
        let refCodes: MLXArray?
        if iclMode {
            guard let speechTokenizer, speechTokenizer.hasEncoder else {
                throw AudioGenerationError.modelNotInitialized(
                    "Qwen3 clone prompt creation requires an initialized speech tokenizer encoder."
                )
            }
            let refAudioForEncoder = try Qwen3TTSReferenceAudio.encoderInputWithTrailingSilence(refAudio)
            refCodes = try speechTokenizer.encode(refAudioForEncoder)
        } else {
            refCodes = nil
        }

        return Qwen3TTSVoiceClonePrompt(
            refCodes: refCodes,
            speakerEmbedding: speakerEmbedding,
            refText: normalizedRefText,
            xVectorOnlyMode: xVectorOnlyMode,
            iclMode: iclMode
        )
    }

    public func prepareVoiceClone(
        text: String,
        language: String,
        voiceClonePrompt: Qwen3TTSVoiceClonePrompt,
        generationParameters _: GenerateParameters,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        isolation: isolated (any Actor)? = #isolation
    ) async throws {
        try await withGenerationGate(isolation: isolation) {
        guard speechTokenizer != nil else {
            throw AudioGenerationError.modelNotInitialized("Speech tokenizer not loaded")
        }
        guard tokenizer != nil else {
            throw AudioGenerationError.modelNotInitialized("Text tokenizer not loaded")
        }

        let startedAt = ContinuousClock.now
        let inputEmbedsInit = try prepareVoiceCloneInputs(
            text: text,
            voiceClonePrompt: voiceClonePrompt,
            language: language
        ).inputEmbeds
        try await warmPreparedInputs(
            inputEmbedsInit,
            inputPreparationMS: startedAt.elapsedMilliseconds,
            booleanFlags: [
                "clone_prompt_used": true,
            ],
            memoryPolicy: memoryPolicy,
            isolation: isolation
        )
        }
    }

    public func prepareForGeneration(
        text: String,
        voice: String?,
        refAudio: MLXArray?,
        refText: String?,
        language: String?,
        generationParameters: GenerateParameters
    ) async throws {
        try await withGenerationGate {
        guard let speechTokenizer else {
            throw AudioGenerationError.modelNotInitialized("Speech tokenizer not loaded")
        }
        guard tokenizer != nil else {
            throw AudioGenerationError.modelNotInitialized("Text tokenizer not loaded")
        }

        let instruct = voice
        let lang = language ?? "auto"
        let inputPreparationStartedAt = ContinuousClock.now

        let inputEmbedsInit: MLXArray
        let preparationBooleanFlags: [String: Bool]
        let additionalPreparationTimingsMS: [String: Int]
        if let refAudio,
           let refText,
           speechTokenizer.hasEncoder
        {
            let speakerEmbedding = try extractSpeakerEmbedding(refAudio)
            inputEmbedsInit = try prepareICLGenerationInputs(
                text: text,
                refAudio: refAudio,
                refText: refText,
                speakerEmbedding: speakerEmbedding,
                language: lang
            ).inputEmbeds
            preparationBooleanFlags = [:]
            additionalPreparationTimingsMS = [:]
        } else {
            let prepared = try prepareVoiceDesignInputs(
                text: text,
                language: lang,
                voiceDescription: instruct ?? ""
            )
            inputEmbedsInit = prepared.inputEmbeds
            preparationBooleanFlags = [
                "prefix_cache_hit": prepared.prefixCacheHit,
                "design_prefix_cache_hit": prepared.prefixCacheHit,
            ]
            additionalPreparationTimingsMS = prepared.timingsMS
        }

        try await warmPreparedInputs(
            inputEmbedsInit,
            inputPreparationMS: inputPreparationStartedAt.elapsedMilliseconds,
            booleanFlags: preparationBooleanFlags,
            additionalTimingsMS: additionalPreparationTimingsMS,
            preparationEvalTimingKey: preparationBooleanFlags["design_prefix_cache_hit"] == true || !additionalPreparationTimingsMS.isEmpty
                ? "design_prewarm_eval_ms"
                : nil
        )
        }
    }

    convenience init(config: Qwen3TTSModelConfig) {
        let talkerConfig = config.talkerConfig ?? {
            let json = "{}".data(using: .utf8)!
            return try! JSONDecoder().decode(Qwen3TTSTalkerConfig.self, from: json)
        }()
        self.init(
            config: config,
            talker: Qwen3TTSTalkerForConditionalGeneration(config: talkerConfig),
            speakerEncoder: config.ttsModelType == "base"
                ? Qwen3TTSSpeakerEncoder(config: config.speakerEncoderConfig)
                : nil
        )
    }

    init(
        config: Qwen3TTSModelConfig,
        talker: Qwen3TTSTalkerForConditionalGeneration,
        speakerEncoder: Qwen3TTSSpeakerEncoder?
    ) {
        self.config = config
        self.talker = talker
        self.speakerEncoder = speakerEncoder
    }

    private func withGenerationGate<T: Sendable>(
        isolation: isolated (any Actor)? = #isolation,
        _ operation: () async throws -> T
    ) async throws -> T {
        _ = isolation
        try await generationGate.acquire()
        do {
            try Task.checkCancellation()
            let result = try await operation()
            await generationGate.release()
            return result
        } catch {
            await generationGate.release()
            throw error
        }
    }

    // MARK: - SpeechGenerationModel protocol

    public func generate(
        text: String,
        voice: String?,
        refAudio: MLXArray?,
        refText: String?,
        language: String?,
        generationParameters: GenerateParameters
    ) async throws -> MLXArray {
        try await withGenerationGate {
        guard speechTokenizer != nil else {
            throw AudioGenerationError.modelNotInitialized("Speech tokenizer not loaded")
        }
        guard tokenizer != nil else {
            throw AudioGenerationError.modelNotInitialized("Text tokenizer not loaded")
        }

        // VoiceDesign: voice parameter is the instruct (voice description)
        let instruct = voice

        let samplingPolicy = Qwen3RequestSamplingPolicy.official(
            generationParameters,
            effectiveSeed: UInt64.random(in: UInt64.min ... UInt64.max)
        )
        let audio = try await samplingPolicy.runWithRandomState {
            try await generateVoiceDesign(
                text: text,
                instruct: instruct,
                language: language ?? "auto",
                refAudio: refAudio,
                refText: refText,
                samplingPolicy: samplingPolicy,
                memoryPolicy: .compatibilityDefault,
                memoryClearCadence: Self.productionFullResultMemoryClearCadence
            )
        }
        return audio
        }
    }

    public func generateStream(
        text: String,
        voice: String?,
        refAudio: MLXArray?,
        refText: String?,
        language: String?,
        generationParameters: GenerateParameters
    ) -> AsyncThrowingStream<AudioGeneration, Error> {
        generateStream(
            text: text,
            voice: voice,
            refAudio: refAudio,
            refText: refText,
            language: language,
            generationParameters: generationParameters,
            streamingInterval: 2.0
        )
    }

    public func generateStream(
        text: String,
        voice: String?,
        refAudio: MLXArray?,
        refText: String?,
        language: String?,
        generationParameters: GenerateParameters,
        streamingInterval: Double,
        enableChunkTimings: Bool = false
    ) -> AsyncThrowingStream<AudioGeneration, Error> {
        let (stream, continuation) = AsyncThrowingStream<AudioGeneration, Error>.makeStream()
        let producerTask = Task { @Sendable [weak self] in
            guard let self else { return }
            do {
                try await withGenerationGate {
                try Task.checkCancellation()
                guard speechTokenizer != nil else {
                    throw AudioGenerationError.modelNotInitialized("Speech tokenizer not loaded")
                }
                guard tokenizer != nil else {
                    throw AudioGenerationError.modelNotInitialized("Text tokenizer not loaded")
                }

                // VoiceDesign: voice parameter is the instruct (voice description)
                let instruct = voice
                let lang = language ?? "auto"
                let samplingPolicy = Qwen3RequestSamplingPolicy.official(
                    generationParameters,
                    effectiveSeed: UInt64.random(in: UInt64.min ... UInt64.max)
                )
                _ = try await samplingPolicy.runWithRandomState {
                    try await generateVoiceDesign(
                        text: text,
                        instruct: instruct,
                        language: lang,
                        refAudio: refAudio,
                        refText: refText,
                        samplingPolicy: samplingPolicy,
                        memoryPolicy: .compatibilityDefault,
                        streamingInterval: streamingInterval,
                        streamStepEvalPolicy: nil,
                        generationSpeedProfile: nil,
                        memoryClearCadence: nil,
                        onToken: { tokenId in
                            guard !Task.isCancelled else { return }
                            continuation.yield(.token(tokenId))
                        },
                        onInfo: { info in
                            guard !Task.isCancelled else { return }
                            continuation.yield(.info(info))
                        },
                        onAudioChunk: { chunk in
                            guard !Task.isCancelled else { return }
                            continuation.yield(.audio(chunk))
                        },
                        onAudioChunkTimings: enableChunkTimings ? { timings in
                            guard !Task.isCancelled else { return }
                            continuation.yield(.chunkTimings(timings))
                        } : nil
                    )
                }
                }
                continuation.finish()
            } catch {
                continuation.finish(throwing: error)
            }
        }
        continuation.onTermination = { @Sendable _ in
            producerTask.cancel()
        }
        return stream
    }

    public func generateCustomVoice(
        text: String,
        language: String,
        speaker: String,
        instruct: String?,
        generationParameters: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy
    ) async throws -> AudioGenerationCompletion {
        try await generateCustomVoiceQualityFirst(
            text: text,
            language: language,
            speaker: speaker,
            instruct: instruct,
            generationParameters: generationParameters,
            samplingPolicy: samplingPolicy,
            memoryPolicy: memoryPolicy,
            onPrepared: {},
            codecTraceSink: nil,
            isolation: #isolation
        )
    }

    public func generateCustomVoiceQualityFirst(
        text: String,
        language: String,
        speaker: String,
        instruct: String?,
        generationParameters _: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        onPrepared: @escaping @Sendable () async throws -> Void,
        codecTraceSink: Qwen3CodecTraceSink?,
        isolation: isolated (any Actor)?
    ) async throws -> AudioGenerationCompletion {
        try await withGenerationGate(isolation: isolation) {
        let generationInfo = OSAllocatedUnfairLock<AudioGenerationInfo?>(initialState: nil)
        let audio = try await samplingPolicy.runWithRandomState(isolation: isolation) {
            try await generateVoiceDesign(
                text: text,
                instruct: instruct,
                language: language,
                speaker: speaker,
                refAudio: nil,
                refText: nil,
                samplingPolicy: samplingPolicy,
                memoryPolicy: memoryPolicy,
                textConditioningMode: .fullTextNonStreaming,
                customVoiceProfile: nil,
                streamStepEvalPolicy: nil,
                generationSpeedProfile: nil,
                memoryClearCadence: Self.productionFullResultMemoryClearCadence,
                onInfo: { info in generationInfo.withLock { $0 = info } },
                codecTraceSink: codecTraceSink,
                onPrepared: onPrepared,
                isolation: isolation
            )
        }
        return AudioGenerationCompletion(
            audio: audio,
            info: generationInfo.withLock { $0 },
            finishReason: latestAudioGenerationFinishReason()
        )
        }
    }

    public func generateVoiceDesign(
        text: String,
        language: String,
        voiceDescription: String,
        generationParameters: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy
    ) async throws -> AudioGenerationCompletion {
        try await generateVoiceDesignQualityFirst(
            text: text,
            language: language,
            voiceDescription: voiceDescription,
            generationParameters: generationParameters,
            samplingPolicy: samplingPolicy,
            memoryPolicy: memoryPolicy,
            onPrepared: {},
            codecTraceSink: nil,
            isolation: #isolation
        )
    }

    public func generateVoiceDesignQualityFirst(
        text: String,
        language: String,
        voiceDescription: String,
        generationParameters _: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        onPrepared: @escaping @Sendable () async throws -> Void,
        codecTraceSink: Qwen3CodecTraceSink?,
        isolation: isolated (any Actor)?
    ) async throws -> AudioGenerationCompletion {
        try await withGenerationGate(isolation: isolation) {
        let generationInfo = OSAllocatedUnfairLock<AudioGenerationInfo?>(initialState: nil)
        let audio = try await samplingPolicy.runWithRandomState(isolation: isolation) {
            try await generateVoiceDesign(
                text: text,
                instruct: voiceDescription,
                language: language,
                refAudio: nil,
                refText: nil,
                samplingPolicy: samplingPolicy,
                memoryPolicy: memoryPolicy,
                textConditioningMode: .fullTextNonStreaming,
                customVoiceProfile: nil,
                streamStepEvalPolicy: nil,
                generationSpeedProfile: nil,
                memoryClearCadence: Self.productionFullResultMemoryClearCadence,
                onInfo: { info in generationInfo.withLock { $0 = info } },
                codecTraceSink: codecTraceSink,
                onPrepared: onPrepared,
                isolation: isolation
            )
        }
        return AudioGenerationCompletion(
            audio: audio,
            info: generationInfo.withLock { $0 },
            finishReason: latestAudioGenerationFinishReason()
        )
        }
    }

    public func generateVoiceClone(
        text: String,
        language: String,
        voiceClonePrompt: Qwen3TTSVoiceClonePrompt,
        generationParameters: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy
    ) async throws -> AudioGenerationCompletion {
        try await generateVoiceCloneQualityFirst(
            text: text,
            language: language,
            voiceClonePrompt: voiceClonePrompt,
            generationParameters: generationParameters,
            samplingPolicy: samplingPolicy,
            memoryPolicy: memoryPolicy,
            onPrepared: {},
            codecTraceSink: nil,
            isolation: #isolation
        )
    }

    public func generateVoiceCloneQualityFirst(
        text: String,
        language: String,
        voiceClonePrompt: Qwen3TTSVoiceClonePrompt,
        generationParameters _: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        onPrepared: @escaping @Sendable () async throws -> Void,
        codecTraceSink: Qwen3CodecTraceSink?,
        isolation: isolated (any Actor)?
    ) async throws -> AudioGenerationCompletion {
        try await withGenerationGate(isolation: isolation) {
        let generationInfo = OSAllocatedUnfairLock<AudioGenerationInfo?>(initialState: nil)
        let audio = try await samplingPolicy.runWithRandomState(isolation: isolation) {
            try await generateVoiceDesign(
                text: text,
                instruct: nil,
                language: language,
                speaker: nil,
                refAudio: nil,
                refText: nil,
                voiceClonePrompt: voiceClonePrompt,
                samplingPolicy: samplingPolicy,
                memoryPolicy: memoryPolicy,
                textConditioningMode: .fullTextNonStreaming,
                customVoiceProfile: nil,
                streamStepEvalPolicy: nil,
                generationSpeedProfile: nil,
                memoryClearCadence: Self.productionFullResultMemoryClearCadence,
                onInfo: { info in generationInfo.withLock { $0 = info } },
                codecTraceSink: codecTraceSink,
                onPrepared: onPrepared,
                isolation: isolation
            )
        }
        return AudioGenerationCompletion(
            audio: audio,
            info: generationInfo.withLock { $0 },
            finishReason: latestAudioGenerationFinishReason()
        )
        }
    }

    private func latestAudioGenerationFinishReason() -> AudioGenerationFinishReason {
        switch latestPreparationStringFlags["generation_end_reason"] {
        case "eos":
            return .eos
        case "token_cap":
            return .maxTokens
        case "failed":
            return .failed
        default:
            return .failed
        }
    }

    public func generateCustomVoiceStream(
        text: String,
        language: String,
        speaker: String,
        instruct: String?,
        generationParameters _: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        streamingInterval: Double,
        customVoiceProfile: String?,
        streamStepEvalPolicy: String?,
        generationSpeedProfile: String?,
        memoryClearCadence: Int?,
        enableChunkTimings: Bool = false
    ) -> AsyncThrowingStream<AudioGeneration, Error> {
        let (stream, continuation) = AsyncThrowingStream<AudioGeneration, Error>.makeStream()
        let producerTask = Task { @Sendable [weak self] in
            guard let self else { return }
            do {
                try await withGenerationGate {
                try Task.checkCancellation()
                _ = try await samplingPolicy.runWithRandomState {
                    try await generateVoiceDesign(
                        text: text,
                        instruct: instruct,
                        language: language,
                        speaker: speaker,
                        refAudio: nil,
                        refText: nil,
                        samplingPolicy: samplingPolicy,
                        memoryPolicy: memoryPolicy,
                        streamingInterval: streamingInterval,
                        customVoiceProfile: customVoiceProfile,
                        streamStepEvalPolicy: streamStepEvalPolicy,
                        generationSpeedProfile: generationSpeedProfile,
                        memoryClearCadence: memoryClearCadence,
                        onToken: {
                            guard !Task.isCancelled else { return }
                            continuation.yield(.token($0))
                        },
                        onInfo: {
                            guard !Task.isCancelled else { return }
                            continuation.yield(.info($0))
                        },
                        onAudioChunk: {
                            guard !Task.isCancelled else { return }
                            continuation.yield(.audio($0))
                        },
                        onAudioChunkTimings: enableChunkTimings ? {
                            guard !Task.isCancelled else { return }
                            continuation.yield(.chunkTimings($0))
                        } : nil
                    )
                }
                }
                continuation.finish()
            } catch {
                continuation.finish(throwing: error)
            }
        }
        continuation.onTermination = { @Sendable _ in
            producerTask.cancel()
        }
        return stream
    }

    public func generateVoiceDesignStream(
        text: String,
        language: String,
        voiceDescription: String,
        generationParameters _: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        streamingInterval: Double,
        streamStepEvalPolicy: String?,
        generationSpeedProfile: String?,
        memoryClearCadence: Int?,
        enableChunkTimings: Bool = false
    ) -> AsyncThrowingStream<AudioGeneration, Error> {
        let (stream, continuation) = AsyncThrowingStream<AudioGeneration, Error>.makeStream()
        let producerTask = Task { @Sendable [weak self] in
            guard let self else { return }
            do {
                try await withGenerationGate {
                try Task.checkCancellation()
                _ = try await samplingPolicy.runWithRandomState {
                    try await generateVoiceDesign(
                        text: text,
                        instruct: voiceDescription,
                        language: language,
                        refAudio: nil,
                        refText: nil,
                        samplingPolicy: samplingPolicy,
                        memoryPolicy: memoryPolicy,
                        streamingInterval: streamingInterval,
                        streamStepEvalPolicy: streamStepEvalPolicy,
                        generationSpeedProfile: generationSpeedProfile,
                        memoryClearCadence: memoryClearCadence,
                        onToken: {
                            guard !Task.isCancelled else { return }
                            continuation.yield(.token($0))
                        },
                        onInfo: {
                            guard !Task.isCancelled else { return }
                            continuation.yield(.info($0))
                        },
                        onAudioChunk: {
                            guard !Task.isCancelled else { return }
                            continuation.yield(.audio($0))
                        },
                        onAudioChunkTimings: enableChunkTimings ? {
                            guard !Task.isCancelled else { return }
                            continuation.yield(.chunkTimings($0))
                        } : nil
                    )
                }
                }
                continuation.finish()
            } catch {
                continuation.finish(throwing: error)
            }
        }
        continuation.onTermination = { @Sendable _ in
            producerTask.cancel()
        }
        return stream
    }

    public func generateVoiceCloneStream(
        text: String,
        language: String,
        voiceClonePrompt: Qwen3TTSVoiceClonePrompt,
        generationParameters _: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        streamingInterval: Double,
        streamStepEvalPolicy: String?,
        generationSpeedProfile: String?,
        memoryClearCadence: Int?,
        enableChunkTimings: Bool = false
    ) -> AsyncThrowingStream<AudioGeneration, Error> {
        let (stream, continuation) = AsyncThrowingStream<AudioGeneration, Error>.makeStream()
        let producerTask = Task { @Sendable [weak self] in
            guard let self else { return }
            do {
                try await withGenerationGate {
                try Task.checkCancellation()
                _ = try await samplingPolicy.runWithRandomState {
                    try await generateVoiceDesign(
                        text: text,
                        instruct: nil,
                        language: language,
                        speaker: nil,
                        refAudio: nil,
                        refText: nil,
                        voiceClonePrompt: voiceClonePrompt,
                        samplingPolicy: samplingPolicy,
                        memoryPolicy: memoryPolicy,
                        streamingInterval: streamingInterval,
                        streamStepEvalPolicy: streamStepEvalPolicy,
                        generationSpeedProfile: generationSpeedProfile,
                        memoryClearCadence: memoryClearCadence,
                        onToken: {
                            guard !Task.isCancelled else { return }
                            continuation.yield(.token($0))
                        },
                        onInfo: {
                            guard !Task.isCancelled else { return }
                            continuation.yield(.info($0))
                        },
                        onAudioChunk: {
                            guard !Task.isCancelled else { return }
                            continuation.yield(.audio($0))
                        },
                        onAudioChunkTimings: enableChunkTimings ? {
                            guard !Task.isCancelled else { return }
                            continuation.yield(.chunkTimings($0))
                        } : nil
                    )
                }
                }
                continuation.finish()
            } catch {
                continuation.finish(throwing: error)
            }
        }
        continuation.onTermination = { @Sendable _ in
            producerTask.cancel()
        }
        return stream
    }

    // MARK: - Suspending materialized generation

    /// Runs Custom Voice generation in the caller's task. Audio is evaluated
    /// and copied to `[Float]` before the sink is awaited, so backpressure from
    /// the facade's frame-bounded channel suspends this actual token/decode
    /// producer without transferring an `MLXArray` to another task.
    public func produceCustomVoice(
        text: String,
        language: String,
        speaker: String,
        instruct: String?,
        generationParameters _: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        streamingInterval: Double,
        customVoiceProfile: String?,
        streamStepEvalPolicy: String?,
        generationSpeedProfile: String?,
        memoryClearCadence: Int?,
        enableChunkTimings: Bool,
        enableCodecTrace: Bool,
        sink: @escaping Qwen3MaterializedGenerationSink,
        isolation: isolated (any Actor)? = #isolation
    ) async throws -> AudioGenerationFinishReason {
        try await withGenerationGate(isolation: isolation) {
            try Task.checkCancellation()
            let finishReason = try await samplingPolicy.runWithRandomState(isolation: isolation) {
                _ = try await generateVoiceDesign(
                    text: text,
                    instruct: instruct,
                    language: language,
                    speaker: speaker,
                    refAudio: nil,
                    refText: nil,
                    samplingPolicy: samplingPolicy,
                    memoryPolicy: memoryPolicy,
                    streamingInterval: streamingInterval,
                    customVoiceProfile: customVoiceProfile,
                    streamStepEvalPolicy: streamStepEvalPolicy,
                    generationSpeedProfile: generationSpeedProfile,
                    memoryClearCadence: memoryClearCadence,
                    materializedEventSink: sink,
                    emitMaterializedChunkTimings: enableChunkTimings,
                    emitMaterializedCodecTrace: enableCodecTrace,
                    isolation: isolation
                )
                return latestAudioGenerationFinishReason()
            }
            try Task.checkCancellation()
            return finishReason
        }
    }

    public func produceVoiceDesign(
        text: String,
        language: String,
        voiceDescription: String,
        generationParameters _: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        streamingInterval: Double,
        streamStepEvalPolicy: String?,
        generationSpeedProfile: String?,
        memoryClearCadence: Int?,
        enableChunkTimings: Bool,
        enableCodecTrace: Bool,
        sink: @escaping Qwen3MaterializedGenerationSink,
        isolation: isolated (any Actor)? = #isolation
    ) async throws -> AudioGenerationFinishReason {
        try await withGenerationGate(isolation: isolation) {
            try Task.checkCancellation()
            let finishReason = try await samplingPolicy.runWithRandomState(isolation: isolation) {
                _ = try await generateVoiceDesign(
                    text: text,
                    instruct: voiceDescription,
                    language: language,
                    refAudio: nil,
                    refText: nil,
                    samplingPolicy: samplingPolicy,
                    memoryPolicy: memoryPolicy,
                    streamingInterval: streamingInterval,
                    streamStepEvalPolicy: streamStepEvalPolicy,
                    generationSpeedProfile: generationSpeedProfile,
                    memoryClearCadence: memoryClearCadence,
                    materializedEventSink: sink,
                    emitMaterializedChunkTimings: enableChunkTimings,
                    emitMaterializedCodecTrace: enableCodecTrace,
                    isolation: isolation
                )
                return latestAudioGenerationFinishReason()
            }
            try Task.checkCancellation()
            return finishReason
        }
    }

    public func produceVoiceClone(
        text: String,
        language: String,
        voiceClonePrompt: Qwen3TTSVoiceClonePrompt,
        generationParameters _: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        streamingInterval: Double,
        streamStepEvalPolicy: String?,
        generationSpeedProfile: String?,
        memoryClearCadence: Int?,
        enableChunkTimings: Bool,
        enableCodecTrace: Bool,
        sink: @escaping Qwen3MaterializedGenerationSink,
        isolation: isolated (any Actor)? = #isolation
    ) async throws -> AudioGenerationFinishReason {
        try await withGenerationGate(isolation: isolation) {
            try Task.checkCancellation()
            let finishReason = try await samplingPolicy.runWithRandomState(isolation: isolation) {
                _ = try await generateVoiceDesign(
                    text: text,
                    instruct: nil,
                    language: language,
                    speaker: nil,
                    refAudio: nil,
                    refText: nil,
                    voiceClonePrompt: voiceClonePrompt,
                    samplingPolicy: samplingPolicy,
                    memoryPolicy: memoryPolicy,
                    streamingInterval: streamingInterval,
                    streamStepEvalPolicy: streamStepEvalPolicy,
                    generationSpeedProfile: generationSpeedProfile,
                    memoryClearCadence: memoryClearCadence,
                    materializedEventSink: sink,
                    emitMaterializedChunkTimings: enableChunkTimings,
                    emitMaterializedCodecTrace: enableCodecTrace,
                    isolation: isolation
                )
                return latestAudioGenerationFinishReason()
            }
            try Task.checkCancellation()
            return finishReason
        }
    }

    // MARK: - Decode chunk helper

    /// Decode a chunk of codec codes to audio waveform.
    /// - Parameters:
    ///   - codes: Codec codes [1, time, numCodeGroups]
    ///   - chunkTokens: Tokens per decode chunk (controls decode granularity)
    /// - Returns: Decoded audio waveform (1D)
    /// Full-text conditioning still decodes through Mimi incrementally. Keep
    /// the decoder partition small enough for constrained unified-memory
    /// devices; decoder partition invariance is covered by
    /// `Qwen3DecoderPartitionTests`.
    static let qualityFirstDecoderChunkFrames = 25

    private func decodeChunk(
        _ codes: MLXArray,
        chunkTokens: Int = Qwen3TTSModel.qualityFirstDecoderChunkFrames
    ) -> MLXArray {
        guard let speechTokenizer else { return MLXArray.zeros([1]) }

        var audioChunks = [MLXArray]()
        for chunk in speechTokenizer.streamingDecode(codes, chunkTokens: chunkTokens) {
            audioChunks.append(chunk)
        }
        var audio = concatenated(audioChunks, axis: -1)[0]

        let validLen = Int((codes[0..., 0..., 0] .> 0).sum().item(Int32.self))
            * speechTokenizer.decodeUpsampleRate
        if validLen > 0, validLen < audio.dim(0) {
            audio = audio[..<validLen]
        }

        eval(audio)
        return audio
    }

    public func replayCodecTrace(
        frames: [[Int32]],
        incrementalRanges: [Qwen3CodecFrameRange]
    ) throws -> Qwen3CodecReplayResult {
        guard let speechTokenizer else {
            throw AudioGenerationError.modelNotInitialized("Speech tokenizer not loaded")
        }
        guard !frames.isEmpty, frames.count <= 8_192,
              let groupCount = frames.first?.count,
              groupCount > 0, groupCount <= 64,
              frames.allSatisfy({ $0.count == groupCount }) else {
            throw AudioGenerationError.invalidInput("Invalid bounded codec trace")
        }
        guard !incrementalRanges.isEmpty,
              incrementalRanges.first?.start == 0,
              incrementalRanges.last?.endExclusive == frames.count else {
            throw AudioGenerationError.invalidInput("Codec replay ranges are incomplete")
        }
        var expectedStart = 0
        for range in incrementalRanges {
            guard range.start == expectedStart,
                  range.endExclusive > range.start,
                  range.endExclusive <= frames.count else {
                throw AudioGenerationError.invalidInput("Codec replay ranges are not contiguous")
            }
            expectedStart = range.endExclusive
        }

        let flatCodes = frames.flatMap { $0 }
        let codes = MLXArray(flatCodes).reshaped([1, frames.count, groupCount])

        speechTokenizer.decoder.resetStreamingState()
        var incrementalChunks: [[Float]] = []
        incrementalChunks.reserveCapacity(incrementalRanges.count)
        defer { speechTokenizer.decoder.resetStreamingState() }
        for range in incrementalRanges {
            let decoderCodes = codes[0..., range.start ..< range.endExclusive, 0...]
                .transposed(0, 2, 1)
            let decoded = speechTokenizer.decoder.streamingStep(decoderCodes)[0, 0]
            eval(decoded)
            incrementalChunks.append(decoded.asArray(Float.self))
        }
        speechTokenizer.decoder.resetStreamingState()
        let full = decodeChunk(codes)
        eval(full)
        let fullAudio = full.asArray(Float.self)
        speechTokenizer.decoder.resetStreamingState()

        return Qwen3CodecReplayResult(
            incrementalAudio: incrementalChunks.flatMap { $0 },
            fullAudio: fullAudio,
            sampleRate: sampleRate
        )
    }

    // MARK: - VoiceDesign generation

    fileprivate func generateVoiceDesign(
        text: String,
        instruct: String?,
        language: String,
        speaker: String? = nil,
        refAudio: MLXArray?,
        refText: String?,
        voiceClonePrompt: Qwen3TTSVoiceClonePrompt? = nil,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        streamingInterval: Double = 2.0,
        textConditioningMode: Qwen3TextConditioningMode = .streamingTrailingText,
        customVoiceProfile explicitCustomVoiceProfile: String? = nil,
        streamStepEvalPolicy explicitStreamStepEvalPolicy: String? = nil,
        generationSpeedProfile explicitGenerationSpeedProfile: String? = nil,
        memoryClearCadence _: Int? = nil,
        onToken: ((Int) -> Void)? = nil,
        onInfo: ((AudioGenerationInfo) -> Void)? = nil,
        onAudioChunk: ((MLXArray) -> Void)? = nil,
        onAudioChunkTimings: ((ChunkSubstageTimings) -> Void)? = nil,
        materializedEventSink: Qwen3MaterializedGenerationSink? = nil,
        emitMaterializedChunkTimings: Bool = false,
        emitMaterializedCodecTrace: Bool = false,
        codecTraceSink: Qwen3CodecTraceSink? = nil,
        onPrepared: (@Sendable () async throws -> Void)? = nil,
        isolation: isolated (any Actor)? = #isolation
    ) async throws -> MLXArray {
        _ = isolation
        guard let speechTokenizer, tokenizer != nil else {
            throw AudioGenerationError.modelNotInitialized("Speech tokenizer or text tokenizer not loaded")
        }

        let temperature = samplingPolicy.talker.temperature
        let topK = samplingPolicy.talker.topK
        let topP = samplingPolicy.talker.topP
        let repetitionPenalty = samplingPolicy.repetitionPenalty
        let minP = samplingPolicy.talker.minP
        let maxTokens = samplingPolicy.maximumCodecTokens
        let subtalkerSampling = samplingPolicy.subtalker

        let talkerConfig = config.talkerConfig!
        let isPureVoiceDesign = speaker == nil && refAudio == nil && voiceClonePrompt == nil
        let isDedicatedCustomVoice = speaker != nil && refAudio == nil && voiceClonePrompt == nil
        let isVoiceCloneGeneration = voiceClonePrompt != nil || refAudio != nil
        let streamingGenerationMode: Qwen3StreamingGenerationMode = {
            if isDedicatedCustomVoice {
                return .custom
            } else if isPureVoiceDesign {
                return .design
            } else if isVoiceCloneGeneration {
                return .clone
            }
            return .generic
        }()

        // Prepare inputs
        let inputEmbedsInit: MLXArray
        let trailingTextHidden: MLXArray
        let ttsPadEmbed: MLXArray
        let refCodes: MLXArray?
        let preparationBooleanFlags: [String: Bool]
        let preparationTimingsMS: [String: Int]
        let preparedTargetTokenCount: Int

        if let voiceClonePrompt {
            let prepared = try prepareVoiceCloneInputs(
                text: text,
                voiceClonePrompt: voiceClonePrompt,
                language: language
            )
            inputEmbedsInit = prepared.inputEmbeds
            trailingTextHidden = prepared.trailingTextHidden
            ttsPadEmbed = prepared.ttsPadEmbed
            refCodes = prepared.refCodes
            preparedTargetTokenCount = prepared.targetTokenCount
            preparationBooleanFlags = [
                "clone_prompt_used": true,
                "decoder_bucket_cache_hit": decoderBucketCacheHit(),
            ]
            preparationTimingsMS = [:]
        } else if let refAudio,
           let refText,
           speechTokenizer.hasEncoder {
            let speakerEmbedding = try extractSpeakerEmbedding(refAudio)
            let prepared = try prepareICLGenerationInputs(
                text: text,
                refAudio: refAudio,
                refText: refText,
                speakerEmbedding: speakerEmbedding,
                language: language
            )
            inputEmbedsInit = prepared.inputEmbeds
            trailingTextHidden = prepared.trailingTextHidden
            ttsPadEmbed = prepared.ttsPadEmbed
            refCodes = prepared.refCodes
            preparedTargetTokenCount = prepared.targetTokenCount
            preparationBooleanFlags = [:]
            preparationTimingsMS = [:]
        } else if let speaker {
            let prepared = try prepareCustomVoiceInputs(
                text: text,
                language: language,
                speaker: speaker,
                instruct: instruct,
                textConditioningMode: textConditioningMode
            )
            inputEmbedsInit = prepared.inputEmbeds
            trailingTextHidden = prepared.trailingTextHidden
            ttsPadEmbed = prepared.ttsPadEmbed
            refCodes = nil
            preparedTargetTokenCount = prepared.targetTokenCount
            preparationBooleanFlags = [
                "prefix_cache_hit": prepared.prefixCacheHit,
                "custom_prefix_cache_hit": prepared.prefixCacheHit,
                "custom_speaker_conditioning_used": true,
                "decoder_bucket_cache_hit": decoderBucketCacheHit(),
            ]
            preparationTimingsMS = prepared.timingsMS
        } else {
            let prepared = try prepareVoiceDesignInputs(
                text: text,
                language: language,
                voiceDescription: instruct ?? "",
                textConditioningMode: textConditioningMode
            )
            inputEmbedsInit = prepared.inputEmbeds
            trailingTextHidden = prepared.trailingTextHidden
            ttsPadEmbed = prepared.ttsPadEmbed
            refCodes = nil
            preparedTargetTokenCount = prepared.targetTokenCount
            preparationBooleanFlags = [
                "prefix_cache_hit": prepared.prefixCacheHit,
                "design_prefix_cache_hit": prepared.prefixCacheHit,
                "decoder_bucket_cache_hit": decoderBucketCacheHit(),
            ]
            preparationTimingsMS = prepared.timingsMS
        }
        storePreparationBooleanFlags(preparationBooleanFlags)
        mergePreparationTimingsMS(preparationTimingsMS)
        storePreparationStringFlags([
            "text_conditioning_mode": textConditioningMode.rawValue,
        ])

        // Cap max tokens based on text length
        let customVoiceProfile = isDedicatedCustomVoice
            ? Qwen3CustomVoiceGenerationProfile.resolve(explicitProfile: explicitCustomVoiceProfile)
            : .baseline
        let generationSpeedProfile = Qwen3GenerationSpeedProfile.resolve(
            explicitProfile: explicitGenerationSpeedProfile
        )
        let tokenBudgetPolicy = generationSpeedProfile.tokenBudgetPolicy(
            mode: streamingGenerationMode,
            customVoiceProfile: customVoiceProfile
        )
        let effectiveMaxTokens = tokenBudgetPolicy.effectiveMaxTokens(
            defaultMaxTokens: maxTokens,
            targetTokenCount: preparedTargetTokenCount
        )
        let memoryClearCadence = memoryPolicy.tokenMemoryClearCadence
        let streamStepEvalPolicy = Qwen3StreamStepEvalPolicy.resolve(
            explicitPolicy: explicitStreamStepEvalPolicy
        )
        // A constrained-tier cache clear invalidates the optimization's safety
        // premise: the pending MLXArray would otherwise survive an allocator
        // cache clear and materialize on the next token iteration. Materialize
        // synchronously on that path; higher-memory tiers keep the pipeline.
        let deferStreamChunkMaterialization = streamStepEvalPolicy.shouldDeferAudioMaterialization(
            hasMaterializedSink: materializedEventSink != nil,
            clearsAllocatorCacheAfterChunk: memoryPolicy.clearCacheOnStreamChunkEmit
        )
        mergePreparationBooleanFlags(streamStepEvalPolicy.booleanFlags)
        mergePreparationBooleanFlags([
            "stream_audio_materialization_deferred": deferStreamChunkMaterialization,
            "stream_audio_materialization_eager":
                materializedEventSink != nil && !deferStreamChunkMaterialization,
        ])
        mergePreparationBooleanFlags(generationSpeedProfile.booleanFlags)
        mergePreparationStringFlags([
            "generation_speed_profile": generationSpeedProfile.rawValue,
            "stream_step_eval_policy": streamStepEvalPolicy.rawValue,
            "token_budget_policy": tokenBudgetPolicy.name,
        ])
        if let timingPrefix = streamingGenerationMode.timingPrefix {
            mergePreparationTimingsMS([
                "\(timingPrefix)_target_token_count": preparedTargetTokenCount,
                "\(timingPrefix)_effective_max_tokens": effectiveMaxTokens,
                "\(timingPrefix)_generation_profile_multiplier": tokenBudgetPolicy.maxTokenMultiplier,
                "\(timingPrefix)_generation_profile_min_tokens": tokenBudgetPolicy.minimumGeneratedCodes,
                "memory_clear_cadence": memoryClearCadence,
            ])
        } else {
            mergePreparationTimingsMS([
                "memory_clear_cadence": memoryClearCadence,
            ])
        }
        if isDedicatedCustomVoice {
            mergePreparationTimingsMS([
                "custom_post_first_stream_chunk_multiplier": customVoiceProfile.postFirstStreamChunkMultiplier,
            ])
            mergePreparationBooleanFlags(customVoiceProfile.booleanFlags)
            mergePreparationStringFlags([
                "custom_voice_profile": customVoiceProfile.rawValue,
            ])
        }

        if let materializedEventSink {
            try Task.checkCancellation()
            try await materializedEventSink(.prepared)
            try Task.checkCancellation()
        }
        if let onPrepared {
            try Task.checkCancellation()
            try await onPrepared()
            try Task.checkCancellation()
        }

        // Initialize cache and timing
        let startTime = Date()
        let cache: [any KVCache]
        if let talkerKVWindow = memoryPolicy.talkerKVGeneratedWindow {
            // Sliding-window talker KV (constrained tiers): keep = the conditioning
            // prefill length (control + full text, always at the front of the
            // sequence), so only old generated audio-codec tokens rotate out.
            cache = talker.makeRotatingCache(
                keep: inputEmbedsInit.dim(1), window: talkerKVWindow
            )
        } else {
            cache = talker.makeCache()
        }
        let isStreaming = onAudioChunk != nil || materializedEventSink != nil
        // Quality-first generation must not retain one lazy MLX graph per
        // sampled codec frame. On iOS a 280-character request accumulated the
        // graphs until final decode and crossed the process limit. Store only
        // materialized codec IDs; full-text conditioning remains unchanged.
        var generatedCodecFrames = [[Int32]]()
        if !isStreaming {
            generatedCodecFrames.reserveCapacity(effectiveMaxTokens)
        }
        var pendingStreamCodes = [MLXArray]()
        var generatedCodebookTokenIDs = Set<Int>()
        generatedCodebookTokenIDs.reserveCapacity(effectiveMaxTokens)
        var generatedCodeCount = 0
        let eosTokenId = talkerConfig.codecEosTokenId

        // Suppress special tokens
        let suppressTokens = (talkerConfig.vocabSize - 1024 ..< talkerConfig.vocabSize)
            .filter { $0 != eosTokenId }

        // Streaming decode state
        let codecTokenRateHz = 12.5
        let streamingChunkSize = max(1, Int(streamingInterval * codecTokenRateHz))
        let postFirstStreamingChunkSize = streamingGenerationMode.postFirstStreamingChunkSize(
            baseChunkSize: streamingChunkSize,
            customVoiceProfile: customVoiceProfile
        )
        var streamChunkSchedule = Qwen3StreamChunkSchedule(
            firstChunkSize: streamingChunkSize,
            laterChunkSize: postFirstStreamingChunkSize
        )
        /// Cumulative codec frames already emitted as streaming PCM chunks.
        var emittedCodecFrameCount: UInt64 = 0
        if isStreaming {
            pendingStreamCodes.reserveCapacity(max(streamingChunkSize, postFirstStreamingChunkSize))
        }
        var tokenLoopTotalMS = 0
        var talkerForwardTotalMS = 0
        var sampleFirstCodebookTotalMS = 0
        var codePredictorTotalMS = 0
        var codePredictorStepTotalMS = 0
        var samplePredictedCodebookTotalMS = 0
        var codecEmbeddingAssemblyTotalMS = 0
        var streamingDecoderTotalMS = 0
        var streamingDecoderCallCount = 0
        var mimiDecoderBreakdownTotal = MimiDecoderStepTimings()
        // Snapshot of the cumulative `*TotalMS` accumulators at the
        // moment of the previous chunk's emit, so the per-chunk
        // sub-stage delta passed to `onAudioChunkTimings` reflects ONLY
        // the work done since the previous chunk (or since generation
        // start for the first chunk).
        var lastChunkTalkerForwardMS = 0
        var lastChunkCodePredictorMS = 0
        var lastChunkStreamingDecoderMS = 0
        var lastChunkMimiDecoderBreakdown = MimiDecoderStepTimings()
        // TEL-001: mode-agnostic counters feed one per-chunk delta path.
        var streamStepEvalTotalMS = 0
        var streamStepEvalEnqueueTotalMS = 0
        var streamStepEvalWaitTotalMS = 0
        var streamStepEOSReadTotalMS = 0
        var audioChunkEvalTotalMS = 0
        var lastChunkStreamStepEvalMS = 0
        var lastChunkStreamStepEvalEnqueueMS = 0
        var lastChunkStreamStepEvalWaitMS = 0
        var lastChunkStreamStepEOSReadMS = 0
        var lastChunkAudioChunkEvalMS = 0
        // TEL-001: track peak KV-cache footprint across the generation.
        var peakKVCacheSeqLength = 0
        var peakKVCacheFootprintMB = 0.0
        var kvCacheTypeAtPeak = talker.model.latestCreatedCacheType
        var designStreamStepEvalTotalMS = 0
        var designStreamStepEOSReadTotalMS = 0
        var designAudioChunkEvalTotalMS = 0
        var designGenerationStepsBeforeFirstChunk: Int?
        var designFirstChunkDecoderTokens: Int?
        var customStreamStepEvalTotalMS = 0
        var customStreamStepEOSReadTotalMS = 0
        var customAudioChunkEvalTotalMS = 0
        var customGenerationStepsBeforeFirstChunk: Int?
        var customFirstChunkDecoderTokens: Int?
        var cloneStreamStepEvalTotalMS = 0
        var cloneStreamStepEOSReadTotalMS = 0
        var cloneAudioChunkEvalTotalMS = 0
        var cloneGenerationStepsBeforeFirstChunk: Int?
        var cloneFirstChunkDecoderTokens: Int?
        var generationEndReason = "token_cap"
        var cacheClearCount = 0
        func qwenTokenLoopUnattributedMS() -> Int {
            let attributedMS = talkerForwardTotalMS
                + sampleFirstCodebookTotalMS
                + codePredictorTotalMS
                + codecEmbeddingAssemblyTotalMS
                + streamStepEvalTotalMS
                + streamStepEOSReadTotalMS
                + streamingDecoderTotalMS
                + audioChunkEvalTotalMS
            return max(0, tokenLoopTotalMS - attributedMS)
        }

        func qwenHotLoopTimingsMS() -> [String: Int] {
            var timings: [String: Int] = [
                "qwen_token_loop_total": tokenLoopTotalMS,
                "qwen_talker_forward_total": talkerForwardTotalMS,
                "qwen_sample_first_codebook_total": sampleFirstCodebookTotalMS,
                "qwen_code_predictor_total": codePredictorTotalMS,
                "qwen_code_predictor_step_total": codePredictorStepTotalMS,
                "qwen_sample_predicted_codebook_total": samplePredictedCodebookTotalMS,
                "qwen_codec_embedding_assembly_total": codecEmbeddingAssemblyTotalMS,
                "qwen_stream_step_eval_total": streamStepEvalTotalMS,
                "qwen_stream_step_eval_enqueue_total": streamStepEvalEnqueueTotalMS,
                "qwen_stream_step_eval_wait_total": streamStepEvalWaitTotalMS,
                "qwen_stream_step_eos_read_total": streamStepEOSReadTotalMS,
                "qwen_token_loop_unattributed": qwenTokenLoopUnattributedMS(),
                "qwen_stream_decoder_total": streamingDecoderTotalMS,
                "qwen_stream_decoder_calls": streamingDecoderCallCount,
                "qwen_generated_code_count": generatedCodeCount,
                "qwen_talker_kv_cache_offset": cache.first?.offset ?? 0,
                "cache_clear_count": cacheClearCount,
                "memory_clear_cadence": memoryClearCadence,
            ]
            // Only emit peak KV-cache keys when the peak tracker was actually
            // updated (i.e., telemetry was active). Prevents false-zero readings.
            if peakKVCacheSeqLength > 0 {
                timings["qwen_talker_kv_cache_peak_seq"] = peakKVCacheSeqLength
                timings["qwen_talker_kv_cache_peak_mb"] = Int(peakKVCacheFootprintMB)
            }
            return timings
        }

        // Phase 2a: build a per-chunk KV-cache diagnostic snapshot and keep
        // running peak totals for the final hot-loop summary.
        //
        // NOTE: the footprint is a dense bfloat16 estimate. Quantized KV caches
        // (e.g. 4-bit) and rotating-window caches are NOT reflected in the byte
        // count, so treat this as a coarse trend/regression signal, not exact
        // allocated bytes.
        func makeChunkKVCacheDiagnostics() -> KVCacheDiagnostics? {
            let effectiveSeqLength = cache.first?.offset ?? 0
            let layerCount = talkerConfig.numHiddenLayers
            let headCount = talkerConfig.numAttentionHeads
            let kvHeadCount = talkerConfig.numKeyValueHeads
            let headDim = talkerConfig.headDim
            let dtypeBytes = 2
            let footprintMB = estimatedKVCacheFootprintMB(
                layers: layerCount,
                heads: kvHeadCount,
                seq: effectiveSeqLength,
                headDim: headDim,
                dtypeBytes: dtypeBytes
            )
            if footprintMB > peakKVCacheFootprintMB {
                peakKVCacheFootprintMB = footprintMB
                peakKVCacheSeqLength = effectiveSeqLength
                kvCacheTypeAtPeak = talker.model.latestCreatedCacheType
            }
            return KVCacheDiagnostics(
                cacheType: talker.model.latestCreatedCacheType,
                effectiveSeqLength: effectiveSeqLength,
                layerCount: layerCount,
                headCount: headCount,
                kvHeadCount: kvHeadCount,
                headDim: headDim,
                dtypeBytes: dtypeBytes,
                estimatedFootprintMB: footprintMB
            )
        }

        func clearGenerationCache() {
            Memory.clearCache()
            cacheClearCount += 1
        }
        if let timingPrefix = streamingGenerationMode.timingPrefix {
            let postFirstMultiplier = streamingGenerationMode.postFirstStreamChunkMultiplier(
                customVoiceProfile: customVoiceProfile
            )
            mergePreparationTimingsMS([
                "\(timingPrefix)_initial_stream_chunk_size": streamingChunkSize,
                "\(timingPrefix)_post_first_stream_chunk_size": postFirstStreamingChunkSize,
                "\(timingPrefix)_post_first_stream_chunk_multiplier": postFirstMultiplier,
            ])
            mergePreparationBooleanFlags([
                "\(timingPrefix)_stream_chunk_growth_enabled": postFirstStreamingChunkSize > streamingChunkSize,
            ])
        }

        var trailingIdx = 0
        var inputEmbeds = inputEmbedsInit
        let eosTokenArray = MLXArray([Int32(eosTokenId)]).reshaped(1, 1)
        // Per-generation CP execution state: the compiled per-pass plan and
        // its baked pass-0 mask replace the eager per-frame graph rebuild
        // (Stage 1 P3); the plan owns its K/V buffers, so no KVCacheSimple is
        // allocated for the streaming CP.
        let codePredictorStepConstants = CodePredictorStepConstants()

        if isStreaming {
            speechTokenizer.decoder.resetStreamingState()
        }
        defer {
            if isStreaming {
                speechTokenizer.decoder.resetStreamingState()
            }
        }

        let suppressTokensWithEOS = suppressTokens + [eosTokenId]
        let samplerScratch = Qwen3SamplerScratch(vocabSize: talkerConfig.vocabSize)
        samplerScratch.prepareSuppressPairs(
            base: suppressTokens,
            withEOS: suppressTokensWithEOS,
            dtype: .float32
        )
        // Separate scratch for the code-predictor sampler (different vocab; no
        // suppress pairs prepared, so suppression stays disabled there exactly
        // as before — this only caches the arange/zeros/-inf rows that were
        // re-allocated 14× per frame). Sized lazily from the first CP logits.
        var codePredictorScratch: Qwen3SamplerScratch?

        // Stage 1 P2a (`.pipelined` policy, materialized-sink path only): a
        // stream chunk's compute is submitted with asyncEval at assembly and
        // its materialization + channel sends run at the top of the NEXT token
        // step, after that step's graph is submitted — so the host/channel
        // work overlaps in-flight GPU compute. The flush point precedes the
        // next `.token` read, so the event order on the channel is exactly the
        // pre-pipelining order, and materialization still happens in this task
        // before the awaited send (lossless-channel contract unchanged).
        struct PendingMaterializedStreamChunk {
            let audioChunk: MLXArray
            let timings: ChunkSubstageTimings?
        }
        var pendingMaterializedChunk: PendingMaterializedStreamChunk?
        func flushPendingMaterializedChunk() async throws {
            guard let pending = pendingMaterializedChunk else { return }
            pendingMaterializedChunk = nil
            guard let materializedEventSink else { return }
            let flushEvalStartedAt = ContinuousClock.now
            eval(pending.audioChunk)
            // Flush wait lands in the running audio-chunk-eval totals (its
            // chunk's own delta closed at assembly; this shifts attribution by
            // at most one chunk in the diagnostic breakdown).
            let flushElapsed = flushEvalStartedAt.elapsedMilliseconds
            audioChunkEvalTotalMS += flushElapsed
            if isPureVoiceDesign {
                designAudioChunkEvalTotalMS += flushElapsed
            } else if isDedicatedCustomVoice {
                customAudioChunkEvalTotalMS += flushElapsed
            } else if isVoiceCloneGeneration {
                cloneAudioChunkEvalTotalMS += flushElapsed
            }
            try Task.checkCancellation()
            let materializedSamples = pending.audioChunk.asArray(Float.self)
            if let timings = pending.timings {
                try await materializedEventSink(.chunkTimings(timings))
                try Task.checkCancellation()
            }
            try await materializedEventSink(.audio(materializedSamples))
            try Task.checkCancellation()
        }

        for _ in 0 ..< effectiveMaxTokens {
            try Task.checkCancellation()
            let tokenLoopStartedAt = ContinuousClock.now
            defer {
                tokenLoopTotalMS += tokenLoopStartedAt.elapsedMilliseconds
            }

            // Forward pass through talker
            let talkerForwardStartedAt = ContinuousClock.now
            let talkerSignpost = Qwen3Signposts.signposter.beginInterval("Talker Forward")
            let (logits, hidden) = talker(inputEmbeds, cache: cache)
            Qwen3Signposts.signposter.endInterval("Talker Forward", talkerSignpost)
            talkerForwardTotalMS += talkerForwardStartedAt.elapsedMilliseconds

            let allowsEOS = generatedCodeCount >= Self.productionMinimumGeneratedCodeTokensBeforeEOS

            // Sample first codebook token
            let sampleFirstCodebookStartedAt = ContinuousClock.now
            let sampleFirstCodebookSignpost =
                Qwen3Signposts.signposter.beginInterval("Sample First Codebook")
            let nextToken = sampleToken(
                logits,
                temperature: temperature,
                topP: topP,
                topK: topK,
                repetitionPenalty: repetitionPenalty,
                eosTokenId: allowsEOS ? eosTokenId : nil,
                minP: minP,
                scratch: samplerScratch,
                allowsEOS: allowsEOS
            )
            Qwen3Signposts.signposter.endInterval(
                "Sample First Codebook",
                sampleFirstCodebookSignpost
            )
            sampleFirstCodebookTotalMS += sampleFirstCodebookStartedAt.elapsedMilliseconds

            // Defer sync to the eval boundary with inputEmbeds.
            let isEOS = nextToken .== eosTokenArray
            // Measured do-NOT (2026-07-26): submitting the talker+sampling
            // subgraph here with asyncEval to overlap the CP-loop graph build
            // regressed warm RTF (custom/long −3.9%) — the extra command
            // buffer + fusion break cost more launches than the overlap
            // saved. Record `stage1-p2aii-early-submit`
            // (macos-engine-20260726-060659-99b59f93).

            // Generate remaining codebook tokens with code predictor. Stage 1
            // P3: the streaming path replays per-pass compiled functions (the
            // per-frame position sequence is identical, so pass-indexed
            // traces are exact); the compiled plan owns its K/V buffers, so
            // the eager codeCache is neither written nor trimmed here.
            var codeTokens = [nextToken]
            let codeHidden = hidden[0..., (-1)..., 0...]
            let codePredictorPlan = codePredictorStepConstants.compiledPlan(
                for: talker.codePredictor,
                dtype: codeHidden.dtype
            )

            let codePredictorStartedAt = ContinuousClock.now
            let codePredictorSignpost = Qwen3Signposts.signposter.beginInterval("Code Predictor Loop")
            for codeIdx in 0 ..< talkerConfig.numCodeGroups - 1 {
                let codePredictorStepStartedAt = ContinuousClock.now
                let codePredictorStepSignpost =
                    Qwen3Signposts.signposter.beginInterval("Code Predictor Step")
                let codeLogits: MLXArray
                if codeIdx == 0 {
                    let code0Embed = talker.getInputEmbeddings()(nextToken)
                    codeLogits = codePredictorPlan.run(
                        pass: 0, codeHidden: codeHidden, code0Embed: code0Embed, token: nil
                    )
                } else {
                    codeLogits = codePredictorPlan.run(
                        pass: codeIdx, codeHidden: nil, code0Embed: nil, token: codeTokens.last!
                    )
                }
                Qwen3Signposts.signposter.endInterval(
                    "Code Predictor Step",
                    codePredictorStepSignpost
                )
                codePredictorStepTotalMS += codePredictorStepStartedAt.elapsedMilliseconds

                let samplePredictedCodebookStartedAt = ContinuousClock.now
                let samplePredictedCodebookSignpost =
                    Qwen3Signposts.signposter.beginInterval("Sample Predicted Codebook")
                if codePredictorScratch == nil {
                    codePredictorScratch = Qwen3SamplerScratch(vocabSize: codeLogits.dim(-1))
                }
                // Subtalker (code-predictor) sampling is explicitly request
                // owned. It defaults to the talker stage, but may vary without
                // inheriting the talker's repetition penalty.
                let nextCode = sampleToken(
                    codeLogits,
                    temperature: subtalkerSampling.temperature,
                    topP: subtalkerSampling.topP,
                    topK: subtalkerSampling.topK,
                    minP: subtalkerSampling.minP,
                    scratch: codePredictorScratch
                )
                Qwen3Signposts.signposter.endInterval(
                    "Sample Predicted Codebook",
                    samplePredictedCodebookSignpost
                )
                samplePredictedCodebookTotalMS += samplePredictedCodebookStartedAt.elapsedMilliseconds
                codeTokens.append(nextCode)
            }
            Qwen3Signposts.signposter.endInterval("Code Predictor Loop", codePredictorSignpost)
            codePredictorTotalMS += codePredictorStartedAt.elapsedMilliseconds

            let allCodes = concatenated(codeTokens, axis: 1) // [1, num_code_groups]
            // Prepare next input
            let textEmbed: MLXArray
            if trailingIdx < trailingTextHidden.dim(1) {
                textEmbed = trailingTextHidden[0..., trailingIdx ..< (trailingIdx + 1), 0...]
                trailingIdx += 1
            } else {
                textEmbed = ttsPadEmbed
            }

            // Sum all code embeddings for next step
            let codecEmbeddingStartedAt = ContinuousClock.now
            let codecEmbeddingSignpost =
                Qwen3Signposts.signposter.beginInterval("Codec Embedding Assembly")
            var codecEmbed = talker.getInputEmbeddings()(nextToken)
            for (i, code) in codeTokens.dropFirst().enumerated() {
                codecEmbed = codecEmbed + talker.codePredictor.codecEmbedding[i](code)
            }

            inputEmbeds = textEmbed + codecEmbed
            Qwen3Signposts.signposter.endInterval(
                "Codec Embedding Assembly",
                codecEmbeddingSignpost
            )
            codecEmbeddingAssemblyTotalMS += codecEmbeddingStartedAt.elapsedMilliseconds
            let streamStepEvalStartedAt = ContinuousClock.now
            let stepEvalSignpost = Qwen3Signposts.signposter.beginInterval("Step Eval Flush")
            switch streamStepEvalPolicy {
            case .full:
                eval(inputEmbeds, isEOS)
            case .pipelined:
                asyncEval(inputEmbeds, isEOS)
            case .eosOnly:
                eval(isEOS)
            case .deferred:
                break
            }
            Qwen3Signposts.signposter.endInterval("Step Eval Flush", stepEvalSignpost)
            let streamStepEvalElapsed = streamStepEvalStartedAt.elapsedMilliseconds
            streamStepEvalTotalMS += streamStepEvalElapsed
            // TEL-001: synchronous eval attributes total wall time to enqueue; wait is zero.
            streamStepEvalEnqueueTotalMS += streamStepEvalElapsed
            streamStepEvalWaitTotalMS += 0
            if isPureVoiceDesign {
                designStreamStepEvalTotalMS += streamStepEvalElapsed
            } else if isDedicatedCustomVoice {
                customStreamStepEvalTotalMS += streamStepEvalElapsed
            } else if isVoiceCloneGeneration {
                cloneStreamStepEvalTotalMS += streamStepEvalElapsed
            }

            // The previous chunk's materialization and sends run while this
            // step's submitted graph computes; they precede this step's
            // `.token` send, so channel event order is unchanged.
            try await flushPendingMaterializedChunk()

            let tokenId = Int(nextToken[0, 0].item(Int32.self))
            if let materializedEventSink {
                try Task.checkCancellation()
                try await materializedEventSink(.token(tokenId))
                try Task.checkCancellation()
            } else {
                onToken?(tokenId)
            }
            let eosReadStartedAt = ContinuousClock.now
            let eosReadSignpost = Qwen3Signposts.signposter.beginInterval("EOS Read")
            let reachedEOS = isEOS.item(Bool.self)
            Qwen3Signposts.signposter.endInterval("EOS Read", eosReadSignpost)
            let eosReadElapsed = eosReadStartedAt.elapsedMilliseconds
            streamStepEOSReadTotalMS += eosReadElapsed
            if isPureVoiceDesign {
                designStreamStepEOSReadTotalMS += eosReadElapsed
            } else if isDedicatedCustomVoice {
                customStreamStepEOSReadTotalMS += eosReadElapsed
            } else if isVoiceCloneGeneration {
                cloneStreamStepEOSReadTotalMS += eosReadElapsed
            }
            if reachedEOS {
                generationEndReason = "eos"
                break
            }
            let materializedCodeFrame: [Int32]?
            if emitMaterializedCodecTrace || codecTraceSink != nil || !isStreaming {
                materializedCodeFrame = allCodes.asArray(Int32.self)
            } else {
                materializedCodeFrame = nil
            }
            if emitMaterializedCodecTrace,
               let materializedEventSink,
               let materializedCodeFrame {
                try Task.checkCancellation()
                try await materializedEventSink(.codecFrame(materializedCodeFrame))
                try Task.checkCancellation()
            } else if let codecTraceSink, let materializedCodeFrame {
                try Task.checkCancellation()
                try await codecTraceSink(materializedCodeFrame)
                try Task.checkCancellation()
            }
            generatedCodebookTokenIDs.insert(tokenId)
            samplerScratch.appendRepetitionTokenID(tokenId)
            generatedCodeCount += 1
            if isStreaming {
                pendingStreamCodes.append(allCodes)
                _ = streamChunkSchedule.append()
            } else if let materializedCodeFrame {
                generatedCodecFrames.append(materializedCodeFrame)
            }

            // Streaming: decode and yield audio chunks during generation
            if isStreaming {
                let requiredStreamChunkSize = streamChunkSchedule.requiredChunkSize
                if pendingStreamCodes.count >= requiredStreamChunkSize {
                    try Task.checkCancellation()
                    let codesChunk = stacked(pendingStreamCodes, axis: 1)
                    let codesForDecoder = codesChunk.transposed(0, 2, 1)
                    if isPureVoiceDesign, designGenerationStepsBeforeFirstChunk == nil {
                        designGenerationStepsBeforeFirstChunk = generatedCodeCount
                        designFirstChunkDecoderTokens = codesForDecoder.dim(2)
                    } else if isDedicatedCustomVoice, customGenerationStepsBeforeFirstChunk == nil {
                        customGenerationStepsBeforeFirstChunk = generatedCodeCount
                        customFirstChunkDecoderTokens = codesForDecoder.dim(2)
                    } else if isVoiceCloneGeneration, cloneGenerationStepsBeforeFirstChunk == nil {
                        cloneGenerationStepsBeforeFirstChunk = generatedCodeCount
                        cloneFirstChunkDecoderTokens = codesForDecoder.dim(2)
                    }
                    let streamDecoderStartedAt = ContinuousClock.now
                    let decoderSignpost = Qwen3Signposts.signposter.beginInterval("Audio Decoder")
                    // Measured do-NOT (2026-07-26): building this decode graph
                    // on a dedicated stream (Stream.withNewDefaultStream)
                    // regressed warm RTF on every cell (−0.4% to −4.3%) — the
                    // per-chunk stream + cross-stream event sync cost more
                    // than overlapping a ~5 ms decode buys on this
                    // launch-bound loop. Record `stage1-p5b-codec-stream`
                    // (macos-engine-20260726-070148-150cc5e8).
                    let decoded: MLXArray
                    if onAudioChunkTimings != nil || emitMaterializedChunkTimings {
                        let decodedWithTimings = speechTokenizer.decoder.streamingStepWithTimings(codesForDecoder)
                        decoded = decodedWithTimings.audio.squeezed(axis: 1)
                        mimiDecoderBreakdownTotal = mimiDecoderBreakdownTotal.adding(decodedWithTimings.timings)
                    } else {
                        decoded = speechTokenizer.decoder.streamingStep(codesForDecoder)
                    }
                    Qwen3Signposts.signposter.endInterval("Audio Decoder", decoderSignpost)
                    streamingDecoderTotalMS += streamDecoderStartedAt.elapsedMilliseconds
                    streamingDecoderCallCount += 1
                    let audioChunk = decoded[0]
                    let audioChunkEvalStartedAt = ContinuousClock.now
                    let audioChunkEvalSignpost = Qwen3Signposts.signposter.beginInterval("Audio Chunk Eval")
                    // STREAM-001: non-final chunks evaluate asynchronously so decoding can
                    // overlap the next token loop on the compatibility path. The suspending
                    // actor path materializes in this task before it awaits its sink, so an
                    // MLX value never crosses a task or actor boundary.
                    asyncEval(audioChunk)
                    Qwen3Signposts.signposter.endInterval("Audio Chunk Eval", audioChunkEvalSignpost)
                    let audioChunkEvalElapsed = audioChunkEvalStartedAt.elapsedMilliseconds
                    audioChunkEvalTotalMS += audioChunkEvalElapsed
                    if isPureVoiceDesign {
                        designAudioChunkEvalTotalMS += audioChunkEvalElapsed
                    } else if isDedicatedCustomVoice {
                        customAudioChunkEvalTotalMS += audioChunkEvalElapsed
                    } else if isVoiceCloneGeneration {
                        cloneAudioChunkEvalTotalMS += audioChunkEvalElapsed
                    }

                    let chunkCodecStart = emittedCodecFrameCount
                    let chunkCodecEnd = chunkCodecStart + UInt64(pendingStreamCodes.count)
                    pendingStreamCodes.removeAll(keepingCapacity: true)
                    streamChunkSchedule.didEmit()
                    emittedCodecFrameCount = chunkCodecEnd
                    // `.pipelined`: leave the chunk lazily submitted and flush
                    // it at the top of the next token step. The flush point
                    // runs before every assembly, so at most one chunk is ever
                    // pending.
                    let deferChunkMaterialization = deferStreamChunkMaterialization
                    assert(pendingMaterializedChunk == nil)
                    let materializedSamples: [Float]?
                    if materializedEventSink != nil, !deferChunkMaterialization {
                        eval(audioChunk)
                        try Task.checkCancellation()
                        materializedSamples = audioChunk.asArray(Float.self)
                    } else {
                        materializedSamples = nil
                    }
                    var deferredChunkTimings: ChunkSubstageTimings?
                    if onAudioChunkTimings != nil || emitMaterializedChunkTimings {
                        let kvDiagnostics = makeChunkKVCacheDiagnostics()
                        let chunkMimiBreakdown = mimiDecoderBreakdownTotal.subtracting(lastChunkMimiDecoderBreakdown)
                        let timings = ChunkSubstageTimings(
                            talkerForwardMS: Double(talkerForwardTotalMS - lastChunkTalkerForwardMS),
                            codePredictorMS: Double(codePredictorTotalMS - lastChunkCodePredictorMS),
                            audioDecoderMS: Double(streamingDecoderTotalMS - lastChunkStreamingDecoderMS),
                            streamStepEvalMS: Double(streamStepEvalTotalMS - lastChunkStreamStepEvalMS),
                            streamStepEvalEnqueueMS: Double(streamStepEvalEnqueueTotalMS - lastChunkStreamStepEvalEnqueueMS),
                            streamStepEvalWaitMS: Double(streamStepEvalWaitTotalMS - lastChunkStreamStepEvalWaitMS),
                            streamStepEOSReadMS: Double(streamStepEOSReadTotalMS - lastChunkStreamStepEOSReadMS),
                            audioChunkEvalMS: Double(audioChunkEvalTotalMS - lastChunkAudioChunkEvalMS),
                            kvCacheDiagnostics: kvDiagnostics,
                            mimiDecoderBreakdownMS: chunkMimiBreakdown,
                            codecStartFrame: chunkCodecStart,
                            codecEndFrameExclusive: chunkCodecEnd
                        )
                        lastChunkTalkerForwardMS = talkerForwardTotalMS
                        lastChunkCodePredictorMS = codePredictorTotalMS
                        lastChunkStreamingDecoderMS = streamingDecoderTotalMS
                        lastChunkStreamStepEvalMS = streamStepEvalTotalMS
                        lastChunkStreamStepEvalEnqueueMS = streamStepEvalEnqueueTotalMS
                        lastChunkStreamStepEvalWaitMS = streamStepEvalWaitTotalMS
                        lastChunkStreamStepEOSReadMS = streamStepEOSReadTotalMS
                        lastChunkAudioChunkEvalMS = audioChunkEvalTotalMS
                        lastChunkMimiDecoderBreakdown = mimiDecoderBreakdownTotal
                        if deferChunkMaterialization {
                            deferredChunkTimings = timings
                        } else if let materializedEventSink {
                            try Task.checkCancellation()
                            try await materializedEventSink(.chunkTimings(timings))
                            try Task.checkCancellation()
                        } else {
                            onAudioChunkTimings?(timings)
                        }
                    }
                    try Task.checkCancellation()
                    if deferChunkMaterialization {
                        pendingMaterializedChunk = PendingMaterializedStreamChunk(
                            audioChunk: audioChunk,
                            timings: deferredChunkTimings
                        )
                    } else if let materializedEventSink, let materializedSamples {
                        try await materializedEventSink(.audio(materializedSamples))
                        try Task.checkCancellation()
                    } else {
                        onAudioChunk?(audioChunk)
                    }
                    if memoryPolicy.clearCacheOnStreamChunkEmit {
                        clearGenerationCache()
                    }
                }
            }

            if memoryClearCadence > 0,
               generatedCodeCount > 0,
               generatedCodeCount.isMultiple(of: memoryClearCadence) {
                clearGenerationCache()
            }

        }

        // A chunk stashed in the final token step (EOS or token cap) flushes
        // here, before the info event and the tail chunk — the same relative
        // audio/info order as the synchronous path.
        try await flushPendingMaterializedChunk()

        guard generatedCodeCount > 0 else {
            generationEndReason = "failed"
            mergePreparationBooleanFlags([
                "generation_ended_by_eos": false,
                "generation_hit_token_cap": false,
            ])
            mergePreparationStringFlags([
                "generation_end_reason": generationEndReason,
            ])
            if let timingPrefix = streamingGenerationMode.timingPrefix {
                mergePreparationBooleanFlags([
                    "\(timingPrefix)_generation_ended_by_eos": false,
                    "\(timingPrefix)_generation_hit_token_cap": false,
                ])
                mergePreparationStringFlags([
                    "\(timingPrefix)_generation_end_reason": generationEndReason,
                ])
            }
            return MLXArray.zeros([1])
        }

        // Emit generation info
        let generateTime = Date().timeIntervalSince(startTime)
        let tokenCount = generatedCodeCount
        let info = AudioGenerationInfo(
            promptTokenCount: 0, // Not tracked for VoiceDesign
            generationTokenCount: tokenCount,
            prefillTime: 0, // Included in generateTime
            generateTime: generateTime,
            tokensPerSecond: Double(tokenCount) / generateTime,
            peakMemoryUsage: Double(Memory.peakMemory) / 1e9
        )
        if let materializedEventSink {
            try Task.checkCancellation()
            try await materializedEventSink(.info(info))
            try Task.checkCancellation()
        } else {
            onInfo?(info)
        }
        mergePreparationBooleanFlags([
            "generation_ended_by_eos": generationEndReason == "eos",
            "generation_hit_token_cap": generationEndReason == "token_cap",
        ])
        mergePreparationStringFlags([
            "generation_end_reason": generationEndReason,
        ])
        if let timingPrefix = streamingGenerationMode.timingPrefix {
            mergePreparationBooleanFlags([
                "\(timingPrefix)_generation_ended_by_eos": generationEndReason == "eos",
                "\(timingPrefix)_generation_hit_token_cap": generationEndReason == "token_cap",
            ])
            mergePreparationStringFlags([
                "\(timingPrefix)_generation_end_reason": generationEndReason,
            ])
        }

        // Streaming path: yield remaining tokens and return early
        if isStreaming {
            if !pendingStreamCodes.isEmpty {
                try Task.checkCancellation()
                let codesChunk = stacked(pendingStreamCodes, axis: 1)
                let codesForDecoder = codesChunk.transposed(0, 2, 1)
                let streamDecoderStartedAt = ContinuousClock.now
                let decoded: MLXArray
                if onAudioChunkTimings != nil || emitMaterializedChunkTimings {
                    let decodedWithTimings = speechTokenizer.decoder.streamingStepWithTimings(codesForDecoder)
                    decoded = decodedWithTimings.audio.squeezed(axis: 1)
                    mimiDecoderBreakdownTotal = mimiDecoderBreakdownTotal.adding(decodedWithTimings.timings)
                } else {
                    decoded = speechTokenizer.decoder.streamingStep(codesForDecoder)
                }
                streamingDecoderTotalMS += streamDecoderStartedAt.elapsedMilliseconds
                streamingDecoderCallCount += 1
                let audioChunk = decoded[0]
                if isPureVoiceDesign, designGenerationStepsBeforeFirstChunk == nil {
                    designGenerationStepsBeforeFirstChunk = generatedCodeCount
                    designFirstChunkDecoderTokens = codesForDecoder.dim(2)
                } else if isDedicatedCustomVoice, customGenerationStepsBeforeFirstChunk == nil {
                    customGenerationStepsBeforeFirstChunk = generatedCodeCount
                    customFirstChunkDecoderTokens = codesForDecoder.dim(2)
                } else if isVoiceCloneGeneration, cloneGenerationStepsBeforeFirstChunk == nil {
                    cloneGenerationStepsBeforeFirstChunk = generatedCodeCount
                    cloneFirstChunkDecoderTokens = codesForDecoder.dim(2)
                }
                let audioChunkEvalStartedAt = ContinuousClock.now
                // STREAM-001: the final chunk is a synchronous completion barrier. Returning
                // before materialization can race playback handoff and truncate the preview.
                eval(audioChunk)
                let audioChunkEvalElapsed = audioChunkEvalStartedAt.elapsedMilliseconds
                audioChunkEvalTotalMS += audioChunkEvalElapsed
                if isPureVoiceDesign {
                    designAudioChunkEvalTotalMS += audioChunkEvalElapsed
                } else if isDedicatedCustomVoice {
                    customAudioChunkEvalTotalMS += audioChunkEvalElapsed
                } else if isVoiceCloneGeneration {
                    cloneAudioChunkEvalTotalMS += audioChunkEvalElapsed
                }
                let materializedSamples: [Float]?
                if materializedEventSink != nil {
                    try Task.checkCancellation()
                    materializedSamples = audioChunk.asArray(Float.self)
                } else {
                    materializedSamples = nil
                }
                let chunkCodecStart = emittedCodecFrameCount
                let chunkCodecEnd = chunkCodecStart + UInt64(pendingStreamCodes.count)
                emittedCodecFrameCount = chunkCodecEnd
                if onAudioChunkTimings != nil || emitMaterializedChunkTimings {
                    let kvDiagnostics = makeChunkKVCacheDiagnostics()
                    let chunkMimiBreakdown = mimiDecoderBreakdownTotal.subtracting(lastChunkMimiDecoderBreakdown)
                    let timings = ChunkSubstageTimings(
                        talkerForwardMS: Double(talkerForwardTotalMS - lastChunkTalkerForwardMS),
                        codePredictorMS: Double(codePredictorTotalMS - lastChunkCodePredictorMS),
                        audioDecoderMS: Double(streamingDecoderTotalMS - lastChunkStreamingDecoderMS),
                        streamStepEvalMS: Double(streamStepEvalTotalMS - lastChunkStreamStepEvalMS),
                        streamStepEvalEnqueueMS: Double(streamStepEvalEnqueueTotalMS - lastChunkStreamStepEvalEnqueueMS),
                        streamStepEvalWaitMS: Double(streamStepEvalWaitTotalMS - lastChunkStreamStepEvalWaitMS),
                        streamStepEOSReadMS: Double(streamStepEOSReadTotalMS - lastChunkStreamStepEOSReadMS),
                        audioChunkEvalMS: Double(audioChunkEvalTotalMS - lastChunkAudioChunkEvalMS),
                        kvCacheDiagnostics: kvDiagnostics,
                        mimiDecoderBreakdownMS: chunkMimiBreakdown,
                        codecStartFrame: chunkCodecStart,
                        codecEndFrameExclusive: chunkCodecEnd
                    )
                    lastChunkTalkerForwardMS = talkerForwardTotalMS
                    lastChunkCodePredictorMS = codePredictorTotalMS
                    lastChunkStreamingDecoderMS = streamingDecoderTotalMS
                    lastChunkStreamStepEvalMS = streamStepEvalTotalMS
                    lastChunkStreamStepEvalEnqueueMS = streamStepEvalEnqueueTotalMS
                    lastChunkStreamStepEvalWaitMS = streamStepEvalWaitTotalMS
                    lastChunkStreamStepEOSReadMS = streamStepEOSReadTotalMS
                    lastChunkAudioChunkEvalMS = audioChunkEvalTotalMS
                    lastChunkMimiDecoderBreakdown = mimiDecoderBreakdownTotal
                    if let materializedEventSink {
                        try Task.checkCancellation()
                        try await materializedEventSink(.chunkTimings(timings))
                        try Task.checkCancellation()
                    } else {
                        onAudioChunkTimings?(timings)
                    }
                }
                try Task.checkCancellation()
                if let materializedEventSink, let materializedSamples {
                    try await materializedEventSink(.audio(materializedSamples))
                    try Task.checkCancellation()
                } else {
                    onAudioChunk?(audioChunk)
                }
                streamChunkSchedule.didEmit()
                // Capture final KV-cache footprint before clearing; when the
                // chunk-timing callback is not registered this is the only
                // update the peak trackers get.
                if onAudioChunkTimings != nil {
                    _ = makeChunkKVCacheDiagnostics()
                }
                clearGenerationCache()
            }
            mergePreparationStringFlags([
                "qwen_talker_kv_cache_type": kvCacheTypeAtPeak,
            ])
            var mergedTimingsMS = qwenHotLoopTimingsMS()
                .merging(preparationTimingsMS) { _, rhs in rhs }
            if isPureVoiceDesign {
                mergedTimingsMS["design_stream_step_eval_total_ms"] = designStreamStepEvalTotalMS
                mergedTimingsMS["design_stream_step_eos_read_total_ms"] = designStreamStepEOSReadTotalMS
                mergedTimingsMS["design_audio_chunk_eval_total_ms"] = designAudioChunkEvalTotalMS
                if let designGenerationStepsBeforeFirstChunk {
                    mergedTimingsMS["design_generation_steps_before_first_chunk"] = designGenerationStepsBeforeFirstChunk
                }
                if let designFirstChunkDecoderTokens {
                    mergedTimingsMS["design_first_chunk_decoder_tokens"] = designFirstChunkDecoderTokens
                }
            } else if isDedicatedCustomVoice {
                mergedTimingsMS["custom_stream_step_eval_total_ms"] = customStreamStepEvalTotalMS
                mergedTimingsMS["custom_stream_step_eos_read_total_ms"] = customStreamStepEOSReadTotalMS
                mergedTimingsMS["custom_audio_chunk_eval_total_ms"] = customAudioChunkEvalTotalMS
                if let customGenerationStepsBeforeFirstChunk {
                    mergedTimingsMS["custom_generation_steps_before_first_chunk"] = customGenerationStepsBeforeFirstChunk
                }
                if let customFirstChunkDecoderTokens {
                    mergedTimingsMS["custom_first_chunk_decoder_tokens"] = customFirstChunkDecoderTokens
                }
                mergedTimingsMS["custom_generation_ended_by_eos"] = generationEndReason == "eos" ? 1 : 0
                mergedTimingsMS["custom_generation_hit_token_cap"] = generationEndReason == "token_cap" ? 1 : 0
                mergePreparationBooleanFlags([
                    "custom_generation_ended_by_eos": generationEndReason == "eos",
                    "custom_generation_hit_token_cap": generationEndReason == "token_cap",
                ])
                mergePreparationStringFlags([
                    "custom_generation_end_reason": generationEndReason,
                ])
            } else if isVoiceCloneGeneration {
                mergedTimingsMS["clone_stream_step_eval_total_ms"] = cloneStreamStepEvalTotalMS
                mergedTimingsMS["clone_stream_step_eos_read_total_ms"] = cloneStreamStepEOSReadTotalMS
                mergedTimingsMS["clone_audio_chunk_eval_total_ms"] = cloneAudioChunkEvalTotalMS
                if let cloneGenerationStepsBeforeFirstChunk {
                    mergedTimingsMS["clone_generation_steps_before_first_chunk"] = cloneGenerationStepsBeforeFirstChunk
                }
                if let cloneFirstChunkDecoderTokens {
                    mergedTimingsMS["clone_first_chunk_decoder_tokens"] = cloneFirstChunkDecoderTokens
                }
            }
            mergePreparationTimingsMS(mergedTimingsMS)
            // Streaming chunks already yielded; return empty (caller uses chunks)
            return MLXArray.zeros([1])
        }

        // Non-streaming path: full decode (existing behavior)
        guard let codeGroupCount = generatedCodecFrames.first?.count,
              codeGroupCount > 0,
              generatedCodecFrames.allSatisfy({ $0.count == codeGroupCount }) else {
            throw AudioGenerationError.audioDecodingFailed(
                "Quality-first generation produced invalid codec frames"
            )
        }
        let codes = MLXArray(generatedCodecFrames.flatMap { $0 })
            .reshaped([1, generatedCodecFrames.count, codeGroupCount])

        var decodeCodes = codes
        if let refCodes {
            let refCodesT = refCodes.transposed(0, 2, 1)
            decodeCodes = concatenated([refCodesT, codes], axis: 1)
        }

        var audio = decodeChunk(decodeCodes)

        if let refCodes {
            let refLen = refCodes.dim(2)
            let totalLen = decodeCodes.dim(1)
            let cut = Int(Double(refLen) / Double(max(totalLen, 1)) * Double(audio.dim(0)))
            if cut > 0, cut < audio.dim(0) {
                audio = audio[cut...]
            }
        }

        let finalDecodeEvalStartedAt = ContinuousClock.now
        eval(audio)
        // Capture final KV-cache footprint for non-streaming runs (no chunk
        // boundaries fired, so the peak trackers haven't been updated) BEFORE
        // clearing the generation cache, which resets the KV-cache offset.
        if onAudioChunkTimings != nil {
            _ = makeChunkKVCacheDiagnostics()
        }
        mergePreparationStringFlags([
            "qwen_talker_kv_cache_type": kvCacheTypeAtPeak,
        ])
        clearGenerationCache()
        var mergedTimingsMS = qwenHotLoopTimingsMS()
            .merging(preparationTimingsMS) { _, rhs in rhs }
        if isPureVoiceDesign {
            mergedTimingsMS["design_stream_step_eval_total_ms"] = designStreamStepEvalTotalMS
            mergedTimingsMS["design_stream_step_eos_read_total_ms"] = designStreamStepEOSReadTotalMS
            mergedTimingsMS["design_final_decode_eval_ms"] = finalDecodeEvalStartedAt.elapsedMilliseconds
        } else if isDedicatedCustomVoice {
            mergedTimingsMS["custom_stream_step_eval_total_ms"] = customStreamStepEvalTotalMS
            mergedTimingsMS["custom_stream_step_eos_read_total_ms"] = customStreamStepEOSReadTotalMS
            mergedTimingsMS["custom_audio_chunk_eval_total_ms"] = customAudioChunkEvalTotalMS
            mergedTimingsMS["custom_generation_ended_by_eos"] = generationEndReason == "eos" ? 1 : 0
            mergedTimingsMS["custom_generation_hit_token_cap"] = generationEndReason == "token_cap" ? 1 : 0
            mergePreparationBooleanFlags([
                "custom_generation_ended_by_eos": generationEndReason == "eos",
                "custom_generation_hit_token_cap": generationEndReason == "token_cap",
            ])
            mergePreparationStringFlags([
                "custom_generation_end_reason": generationEndReason,
            ])
        } else if isVoiceCloneGeneration {
            mergedTimingsMS["clone_stream_step_eval_total_ms"] = cloneStreamStepEvalTotalMS
            mergedTimingsMS["clone_stream_step_eos_read_total_ms"] = cloneStreamStepEOSReadTotalMS
            mergedTimingsMS["clone_audio_chunk_eval_total_ms"] = cloneAudioChunkEvalTotalMS
        }
        mergePreparationTimingsMS(mergedTimingsMS)
        return audio
    }

    // MARK: - Prepare generation inputs

    func prepareICLGenerationInputs(
        text: String,
        refAudio: MLXArray,
        refText: String,
        speakerEmbedding: MLXArray?,
        language: String
    ) throws -> (
        inputEmbeds: MLXArray,
        trailingTextHidden: MLXArray,
        ttsPadEmbed: MLXArray,
        refCodes: MLXArray,
        targetTokenCount: Int
    ) {
        let refAudioForEncoder = try Qwen3TTSReferenceAudio.encoderInputWithTrailingSilence(refAudio)
        guard let speechTokenizer else {
            throw AudioGenerationError.modelNotInitialized("Speech tokenizer not loaded")
        }
        let refCodes = try speechTokenizer.encode(refAudioForEncoder) // [1, num_code_groups, ref_time]
        return try prepareICLGenerationInputs(
            text: text,
            refCodes: refCodes,
            refText: refText,
            speakerEmbedding: speakerEmbedding,
            language: language
        )
    }

    func prepareICLGenerationInputs(
        text: String,
        refCodes: MLXArray,
        refText: String,
        speakerEmbedding: MLXArray?,
        language: String
    ) throws -> (
        inputEmbeds: MLXArray,
        trailingTextHidden: MLXArray,
        ttsPadEmbed: MLXArray,
        refCodes: MLXArray,
        targetTokenCount: Int
    ) {
        guard let tokenizer, let talkerConfig = config.talkerConfig else {
            throw AudioGenerationError.modelNotInitialized("Tokenizer/config not loaded")
        }

        // Reference text and target text tokenization
        let targetTokenCount = tokenizer.encode(text: text).count
        let refChatText = "<|im_start|>assistant\n\(refText)<|im_end|>\n"
        let refIds = MLXArray(tokenizer.encode(text: refChatText).map { Int32($0) }).reshaped(1, -1)
        let refCount = refIds.dim(1)
        let refStart = min(3, refCount)
        let refEnd = max(refStart, refCount - 2)
        let refTextIds = refIds[0..., refStart ..< refEnd]

        // The tokenizer is ByteLevel BPE with add_prefix_space:false, and `combinedTextIds` below
        // concatenates ref + target tokens with no separator. Without a leading space the first
        // target token lacks its word-boundary marker and glues to the reference transcript, so the
        // model drops short first words (e.g. FR "Ce"). Normalize exactly one leading space so the
        // first target token is word-boundary-marked (idempotent if the caller already added one).
        let boundaryMarkedText = " " + text.drop(while: { $0.isWhitespace })
        let targetChatText = "<|im_start|>assistant\n\(boundaryMarkedText)<|im_end|>\n<|im_start|>assistant\n"
        let targetIds = MLXArray(tokenizer.encode(text: targetChatText).map { Int32($0) }).reshaped(1, -1)
        let targetCount = targetIds.dim(1)
        let targetStart = min(3, targetCount)
        let targetEnd = max(targetStart, targetCount - 5)
        let targetTextIds = targetIds[0..., targetStart ..< targetEnd]

        // TTS special tokens
        let ttsTokens = MLXArray(
            [Int32(config.ttsBosTokenId), Int32(config.ttsEosTokenId), Int32(config.ttsPadTokenId)]
        ).reshaped(1, 3)
        let ttsEmbeds = talker.textProjection(talker.getTextEmbeddings()(ttsTokens))
        let ttsBosEmbed = ttsEmbeds[0..., 0 ..< 1, 0...]
        let ttsEosEmbed = ttsEmbeds[0..., 1 ..< 2, 0...]
        let ttsPadEmbed = ttsEmbeds[0..., 2 ..< 3, 0...]

        // Build text embeddings for ref+target
        let combinedTextIds = concatenated([refTextIds, targetTextIds], axis: 1)
        var textEmbed = talker.textProjection(talker.getTextEmbeddings()(combinedTextIds))
        textEmbed = concatenated([textEmbed, ttsEosEmbed], axis: 1)
        let textLen = textEmbed.dim(1)

        // Build codec embeddings from reference codes: codec_bos + sum of all codebook embeddings
        let firstCbCodes = refCodes[0..., 0, 0...]
        var refCodecEmbed = talker.getInputEmbeddings()(firstCbCodes)
        if talkerConfig.numCodeGroups > 1 {
            for i in 0 ..< (talkerConfig.numCodeGroups - 1) {
                let codeIdx = i + 1
                if codeIdx >= refCodes.dim(1) { break }
                let cbCodes = refCodes[0..., codeIdx, 0...]
                refCodecEmbed = refCodecEmbed + talker.codePredictor.codecEmbedding[i](cbCodes)
            }
        }

        let codecBosEmbed = talker.getInputEmbeddings()(
            MLXArray([Int32(talkerConfig.codecBosId)]).reshaped(1, 1)
        )
        let codecEmbedIcl = concatenated([codecBosEmbed, refCodecEmbed], axis: 1)

        // Non-streaming overlay of text and codec contexts
        let codecPadEmbed = talker.getInputEmbeddings()(MLXArray([Int32(talkerConfig.codecPadId)]).reshaped(1, 1))
        let textWithCodecPad = textEmbed + broadcast(
            codecPadEmbed,
            to: [1, textLen, codecPadEmbed.dim(-1)]
        )
        let codecWithTextPad = codecEmbedIcl + broadcast(
            ttsPadEmbed,
            to: [1, codecEmbedIcl.dim(1), ttsPadEmbed.dim(-1)]
        )

        let iclInputEmbed = concatenated([textWithCodecPad, codecWithTextPad], axis: 1)
        let trailingTextHidden = ttsPadEmbed

        // Language ID
        var languageId: Int?
        if language.lowercased() != "auto", let langMap = talkerConfig.codecLanguageId {
            languageId = langMap[language.lowercased()]
        }

        let codecPrefill: [Int32] = if let langId = languageId {
            [
                Int32(talkerConfig.codecThinkId),
                Int32(talkerConfig.codecThinkBosId),
                Int32(langId),
                Int32(talkerConfig.codecThinkEosId)
            ]
        } else {
            [
                Int32(talkerConfig.codecNothinkId),
                Int32(talkerConfig.codecThinkBosId),
                Int32(talkerConfig.codecThinkEosId)
            ]
        }

        var codecPrefixEmbed = talker.getInputEmbeddings()(MLXArray(codecPrefill).reshaped(1, -1))
        let codecPrefixSuffix = talker.getInputEmbeddings()(
            MLXArray([Int32(talkerConfig.codecPadId), Int32(talkerConfig.codecBosId)]).reshaped(1, 2)
        )
        if let speakerEmbedding {
            let canonicalSpeakerEmbedding = try Qwen3TTSVoiceClonePrompt.validateSpeakerEmbedding(
                speakerEmbedding,
                expectedDimension: talkerConfig.hiddenSize,
                allowOfficialVectorShape: true
            )
            let speakerEmbed = canonicalSpeakerEmbedding
                .asType(codecPrefixEmbed.dtype)
                .reshaped(1, 1, talkerConfig.hiddenSize)
            codecPrefixEmbed = concatenated([codecPrefixEmbed, speakerEmbed, codecPrefixSuffix], axis: 1)
        } else {
            codecPrefixEmbed = concatenated([codecPrefixEmbed, codecPrefixSuffix], axis: 1)
        }

        // Role embedding
        let roleEmbed = talker.textProjection(talker.getTextEmbeddings()(targetIds[0..., 0 ..< 3]))

        // Build prefix: text side overlayed with codec prefix
        let padCount = codecPrefixEmbed.dim(1) - 2
        let padEmbeds = broadcast(ttsPadEmbed, to: [1, padCount, ttsPadEmbed.dim(-1)])
        var combinedPrefix = concatenated([padEmbeds, ttsBosEmbed], axis: 1)
        combinedPrefix = combinedPrefix + codecPrefixEmbed[0..., 0 ..< (codecPrefixEmbed.dim(1) - 1), 0...]

        // Full input embedding
        let inputEmbeds = concatenated([roleEmbed, combinedPrefix, iclInputEmbed], axis: 1)

        return (inputEmbeds, trailingTextHidden, ttsPadEmbed, refCodes, targetTokenCount)
    }

    func prepareVoiceCloneInputs(
        text: String,
        voiceClonePrompt: Qwen3TTSVoiceClonePrompt,
        language: String
    ) throws -> (
        inputEmbeds: MLXArray,
        trailingTextHidden: MLXArray,
        ttsPadEmbed: MLXArray,
        refCodes: MLXArray?,
        targetTokenCount: Int
    ) {
        if voiceClonePrompt.iclMode {
            guard let refCodes = voiceClonePrompt.refCodes,
                  let refText = voiceClonePrompt.refText,
                  !refText.isEmpty else {
                throw AudioGenerationError.modelNotInitialized(
                    "Qwen3 clone prompt in ICL mode is missing required reference codes or transcript."
                )
            }
            let prepared = try prepareICLGenerationInputs(
                text: text,
                refCodes: refCodes,
                refText: refText,
                speakerEmbedding: voiceClonePrompt.speakerEmbedding,
                language: language
            )
            return (
                prepared.inputEmbeds,
                prepared.trailingTextHidden,
                prepared.ttsPadEmbed,
                prepared.refCodes,
                prepared.targetTokenCount
            )
        }

        let prepared = try prepareVoiceCloneFromSpeakerOnly(
            text: text,
            language: language,
            voiceClonePrompt: voiceClonePrompt
        )
        return (
            prepared.inputEmbeds,
            prepared.trailingTextHidden,
            prepared.ttsPadEmbed,
            nil,
            prepared.targetTokenCount
        )
    }

    private func prepareVoiceCloneFromSpeakerOnly(
        text: String,
        language: String,
        voiceClonePrompt: Qwen3TTSVoiceClonePrompt
    ) throws -> (
        inputEmbeds: MLXArray,
        trailingTextHidden: MLXArray,
        ttsPadEmbed: MLXArray,
        prefixCacheHit: Bool,
        targetTokenCount: Int
    ) {
        guard let speakerEmbedding = voiceClonePrompt.speakerEmbedding else {
            throw AudioGenerationError.modelNotInitialized(
                "Qwen3 speaker-only clone prompt is missing a speaker embedding."
            )
        }

        let (prefix, cacheHit) = try buildSpeakerConditioningPrefix(
            language: language,
            speakerEmbedding: speakerEmbedding
        )
        let prepared = try prepareInputs(text: text, prefix: prefix)
        return (
            prepared.inputEmbeds,
            prepared.trailingTextHidden,
            prepared.ttsPadEmbed,
            cacheHit,
            prepared.targetTokenCount
        )
    }

    private func buildSpeakerConditioningPrefix(
        language: String,
        speakerEmbedding: MLXArray
    ) throws -> (CachedConditioningPrefix, Bool) {
        guard let tokenizer, let talkerConfig = config.talkerConfig else {
            throw AudioGenerationError.modelNotInitialized("Tokenizer/config not loaded")
        }

        let ttsTokens = MLXArray(
            [Int32(config.ttsBosTokenId), Int32(config.ttsEosTokenId), Int32(config.ttsPadTokenId)]
        ).reshaped(1, 3)
        let ttsEmbeds = talker.textProjection(talker.getTextEmbeddings()(ttsTokens))
        let ttsBosEmbed = ttsEmbeds[0..., 0 ..< 1, 0...]
        let ttsEosEmbed = ttsEmbeds[0..., 1 ..< 2, 0...]
        let ttsPadEmbed = ttsEmbeds[0..., 2 ..< 3, 0...]

        let languageId = resolvedLanguageIdentifier(language: language)
        let codecPrefill: [Int32] = if let languageId {
            [
                Int32(talkerConfig.codecThinkId),
                Int32(talkerConfig.codecThinkBosId),
                Int32(languageId),
                Int32(talkerConfig.codecThinkEosId),
            ]
        } else {
            [
                Int32(talkerConfig.codecNothinkId),
                Int32(talkerConfig.codecThinkBosId),
                Int32(talkerConfig.codecThinkEosId),
            ]
        }

        var codecPrefixEmbed = talker.getInputEmbeddings()(MLXArray(codecPrefill).reshaped(1, -1))
        let codecPrefixSuffix = talker.getInputEmbeddings()(
            MLXArray([Int32(talkerConfig.codecPadId), Int32(talkerConfig.codecBosId)]).reshaped(1, 2)
        )
        let canonicalSpeakerEmbedding = try Qwen3TTSVoiceClonePrompt.validateSpeakerEmbedding(
            speakerEmbedding,
            expectedDimension: talkerConfig.hiddenSize,
            allowOfficialVectorShape: true
        )
        let speakerSlot = canonicalSpeakerEmbedding
            .asType(codecPrefixEmbed.dtype)
            .reshaped(1, 1, talkerConfig.hiddenSize)
        codecPrefixEmbed = concatenated([codecPrefixEmbed, speakerSlot, codecPrefixSuffix], axis: 1)

        let assistantPrefix = "<|im_start|>assistant\n"
        let assistantTokens = tokenizer.encode(text: assistantPrefix)
        guard assistantTokens.count == 3 else {
            throw AudioGenerationError.modelNotInitialized(
                "Qwen assistant prefix tokenization no longer matches the pinned three-token contract."
            )
        }
        let assistantPrefixIDs = MLXArray(assistantTokens.map(Int32.init)).reshaped(1, -1)
        let roleEmbed = talker.textProjection(talker.getTextEmbeddings()(assistantPrefixIDs))

        let padCount = codecPrefixEmbed.dim(1) - 2
        let padEmbeds = broadcast(ttsPadEmbed, to: [1, padCount, ttsPadEmbed.dim(-1)])
        var combinedEmbed = concatenated([padEmbeds, ttsBosEmbed], axis: 1)
        combinedEmbed = combinedEmbed + codecPrefixEmbed[0..., ..<(-1), 0...]

        let inputPrefixEmbeds = concatenated([roleEmbed, combinedEmbed], axis: 1)
        let codecLastEmbed = codecPrefixEmbed[0..., (-1)..., 0...]
        let prefix = CachedConditioningPrefix(
            inputPrefixEmbeds: inputPrefixEmbeds,
            codecLastEmbed: codecLastEmbed,
            ttsEosEmbed: ttsEosEmbed,
            ttsPadEmbed: ttsPadEmbed
        )
        return (prefix, false)
    }

    func extractSpeakerEmbedding(_ refAudio: MLXArray) throws -> MLXArray? {
        guard let speakerEncoder else { return nil }

        let rawAudio = try Qwen3TTSReferenceAudio.canonicalMonoBatch(refAudio)

        guard speakerEncoder.config.sampleRate == Qwen3TTSSpeakerMelFrontend.sampleRate,
              speakerEncoder.config.melDim == Qwen3TTSSpeakerMelFrontend.melBinCount else {
            throw AudioGenerationError.modelNotInitialized(
                "Qwen speaker encoder configuration does not match the owned speaker-feature frontend."
            )
        }
        if let talkerConfig = config.talkerConfig,
           speakerEncoder.config.encDim != talkerConfig.hiddenSize {
            throw AudioGenerationError.modelNotInitialized(
                "Qwen speaker embedding dimension does not match the talker hidden size."
            )
        }

        let features = try Qwen3TTSSpeakerMelFrontend()(rawAudio)
        let embedding = speakerEncoder(features).asType(.float32)
        return try Qwen3TTSVoiceClonePrompt.validateSpeakerEmbedding(
            embedding,
            expectedDimension: speakerEncoder.config.encDim,
            allowOfficialVectorShape: true
        )
    }

    func prepareGenerationInputs(
        text: String,
        language: String,
        instruct: String?
    ) throws -> (MLXArray, MLXArray, MLXArray) {
        guard let tokenizer, let talkerConfig = config.talkerConfig else {
            throw AudioGenerationError.modelNotInitialized("Tokenizer/config not loaded")
        }

        // Tokenize text with ChatML template
        let chatText = "<|im_start|>assistant\n\(text)<|im_end|>\n<|im_start|>assistant\n"
        let inputIds = MLXArray(tokenizer.encode(text: chatText).map { Int32($0) }).reshaped(1, -1)

        // Get text embeddings
        let textEmbed = talker.textProjection(talker.getTextEmbeddings()(inputIds))
        try validateOptimizedCustomVoiceTextEmbeddingLength(
            textTokenCount: textEmbed.dim(1),
            originalText: text
        )

        // TTS special tokens
        let ttsTokens = MLXArray(
            [Int32(config.ttsBosTokenId), Int32(config.ttsEosTokenId), Int32(config.ttsPadTokenId)]
        ).reshaped(1, 3)
        let ttsEmbeds = talker.textProjection(talker.getTextEmbeddings()(ttsTokens))
        let ttsBosEmbed = ttsEmbeds[0..., 0 ..< 1, 0...]
        let ttsEosEmbed = ttsEmbeds[0..., 1 ..< 2, 0...]
        let ttsPadEmbed = ttsEmbeds[0..., 2 ..< 3, 0...]

        // Language ID
        var languageId: Int?
        if language.lowercased() != "auto", let langMap = talkerConfig.codecLanguageId {
            languageId = langMap[language.lowercased()]
        }

        // Build codec prefix
        let codecPrefill: [Int32] = if let langId = languageId {
            [
                Int32(talkerConfig.codecThinkId),
                Int32(talkerConfig.codecThinkBosId),
                Int32(langId),
                Int32(talkerConfig.codecThinkEosId)
            ]
        } else {
            [
                Int32(talkerConfig.codecNothinkId),
                Int32(talkerConfig.codecThinkBosId),
                Int32(talkerConfig.codecThinkEosId)
            ]
        }

        var codecEmbed = talker.getInputEmbeddings()(MLXArray(codecPrefill).reshaped(1, -1))
        let codecEmbedSuffix = talker.getInputEmbeddings()(
            MLXArray([Int32(talkerConfig.codecPadId), Int32(talkerConfig.codecBosId)]).reshaped(1, 2)
        )
        codecEmbed = concatenated([codecEmbed, codecEmbedSuffix], axis: 1)

        // Instruct embedding
        var instructEmbed: MLXArray?
        if let instruct, !instruct.isEmpty {
            let instructText = "<|im_start|>user\n\(instruct)<|im_end|>\n"
            let instructIds = MLXArray(tokenizer.encode(text: instructText).map { Int32($0) }).reshaped(1, -1)
            instructEmbed = talker.textProjection(talker.getTextEmbeddings()(instructIds))
        }

        // Role embedding (first 3 tokens: <|im_start|>assistant\n)
        let roleEmbed = textEmbed[0..., ..<3, 0...]

        // Build pad/bos prefix
        let padCount = codecEmbed.dim(1) - 2
        let padEmbeds = broadcast(ttsPadEmbed, to: [1, padCount, ttsPadEmbed.dim(-1)])
        var combinedEmbed = concatenated([padEmbeds, ttsBosEmbed], axis: 1)
        combinedEmbed = combinedEmbed + codecEmbed[0..., ..<(-1), 0...]

        // Full input embedding
        var inputEmbeds: MLXArray = if let instructEmbed {
            concatenated([instructEmbed, roleEmbed, combinedEmbed], axis: 1)
        } else {
            concatenated([roleEmbed, combinedEmbed], axis: 1)
        }

        // Add first text token (index 3) + last codec embed
        let firstTextEmbed = textEmbed[0..., 3 ..< 4, 0...] + codecEmbed[0..., (-1)..., 0...]
        inputEmbeds = concatenated([inputEmbeds, firstTextEmbed], axis: 1)

        // Trailing text (tokens 4 to -5, plus EOS)
        let trailingTextHidden = concatenated(
            [textEmbed[0..., 4 ..< (textEmbed.dim(1) - 5), 0...], ttsEosEmbed],
            axis: 1
        )

        return (inputEmbeds, trailingTextHidden, ttsPadEmbed)
    }

    private func validateOptimizedCustomVoiceTextEmbeddingLength(
        textTokenCount: Int,
        originalText: String
    ) throws {
        guard textTokenCount >= 10 else {
            throw AudioGenerationError.invalidInput(
                "Optimized Qwen3 custom voice requires a longer tokenized prompt. " +
                "The current text produced only \(textTokenCount) chat tokens for '\(originalText)'."
            )
        }
    }

    // MARK: - Token sampling

    private final class Qwen3SamplerScratch {
        let vocabSize: Int
        let negInfScalar: MLXArray
        let arangeIndices: MLXArray

        private var suppressBaseArr: MLXArray?
        private var suppressBaseNegInf: MLXArray?
        private var suppressWithEOSArr: MLXArray?
        private var suppressWithEOSNegInf: MLXArray?

        var repetitionTokenIDsBuffer: [Int32] = []
        private var repetitionTokenIDsMLX: MLXArray?

        init(vocabSize: Int) {
            self.vocabSize = vocabSize
            negInfScalar = MLXArray(-Float.infinity)
            arangeIndices = MLXArray(0 ..< vocabSize).reshaped(1, -1).asType(Int32.self)
        }

        func prepareSuppressPairs(base: [Int], withEOS: [Int], dtype: DType) {
            if base.isEmpty {
                suppressBaseArr = nil
                suppressBaseNegInf = nil
            } else {
                suppressBaseArr = MLXArray(base.map { Int32($0) }).reshaped(1, -1)
                suppressBaseNegInf = MLXArray.full(
                    [1, base.count],
                    values: negInfScalar,
                    dtype: dtype
                )
            }
            if withEOS.isEmpty {
                suppressWithEOSArr = nil
                suppressWithEOSNegInf = nil
            } else {
                suppressWithEOSArr = MLXArray(withEOS.map { Int32($0) }).reshaped(1, -1)
                suppressWithEOSNegInf = MLXArray.full(
                    [1, withEOS.count],
                    values: negInfScalar,
                    dtype: dtype
                )
            }
        }

        func suppressArrays(allowsEOS: Bool) -> (MLXArray, MLXArray)? {
            // When EOS is *allowed*, we must not include it in the suppress list,
            // otherwise the model can never terminate and runs to maxTokens.
            if allowsEOS {
                guard let suppressBaseArr, let suppressBaseNegInf else { return nil }
                return (suppressBaseArr, suppressBaseNegInf)
            }
            guard let suppressWithEOSArr, let suppressWithEOSNegInf else { return nil }
            return (suppressWithEOSArr, suppressWithEOSNegInf)
        }

        func appendRepetitionTokenID(_ tokenID: Int) {
            let value = Int32(tokenID)
            guard !repetitionTokenIDsBuffer.contains(value) else { return }
            repetitionTokenIDsBuffer.append(value)
            repetitionTokenIDsMLX = nil
        }

        func repetitionTokenMLXArray(vocabUpperBound: Int) -> MLXArray? {
            guard !repetitionTokenIDsBuffer.isEmpty else { return nil }
            if repetitionTokenIDsMLX == nil {
                let filtered = repetitionTokenIDsBuffer.filter { Int($0) < vocabUpperBound }
                guard !filtered.isEmpty else { return nil }
                repetitionTokenIDsMLX = MLXArray(filtered).reshaped(1, -1)
            }
            return repetitionTokenIDsMLX
        }

        // Single-slot/per-count caches below: sampler shapes are constant for a
        // whole generation (batch 1, fixed vocab, fixed topK), so the per-token
        // rebuilds were pure allocator + graph-build churn. All consumers
        // (putAlong/which/takeAlong) are functional — cached inputs are never
        // mutated.
        private var zerosCache: MLXArray?
        private var zerosCacheShape: [Int] = []

        func zerosInt32(matching shape: [Int]) -> MLXArray {
            if shape == zerosCacheShape, let zerosCache { return zerosCache }
            let zeros = MLXArray.zeros(shape, type: Int32.self)
            zerosCache = zeros
            zerosCacheShape = shape
            return zeros
        }

        private var negInfRowCache: [Int: MLXArray] = [:]
        private var negInfRowDType: DType?

        /// `[1, count]` of -inf in the logits dtype (topK mask block / topP full row).
        func negInfRow(count: Int, dtype: DType) -> MLXArray {
            if negInfRowDType != dtype {
                negInfRowCache.removeAll()
                negInfRowDType = dtype
            }
            if let cached = negInfRowCache[count] { return cached }
            let row = MLXArray.full([1, count], values: negInfScalar, dtype: dtype)
            negInfRowCache[count] = row
            return row
        }

        private var eosIndexCache: MLXArray?
        private var eosIndexValue: Int = .min

        func eosIndex(_ tokenID: Int) -> MLXArray {
            if tokenID == eosIndexValue, let eosIndexCache { return eosIndexCache }
            let index = MLXArray([Int32(tokenID)]).reshaped(1, 1)
            eosIndexCache = index
            eosIndexValue = tokenID
            return index
        }
    }

    private func sampleToken(
        _ logits: MLXArray,
        temperature: Float = 0.9,
        topP: Float = 1.0,
        topK: Int = 50,
        repetitionPenalty: Float = 1.0,
        generatedTokenIDs: Set<Int>? = nil,
        suppressTokens: [Int]? = nil,
        eosTokenId: Int? = nil,
        minP: Float = 0.0,
        scratch: Qwen3SamplerScratch? = nil,
        allowsEOS: Bool = true
    ) -> MLXArray {
        var logitsSlice = logits[0..., (-1)..., 0...].squeezed(axis: 1) // [batch, vocab_size]

        // Suppress tokens by setting to -inf
        if let scratch {
            if let (suppressArr, negInf) = scratch.suppressArrays(allowsEOS: allowsEOS) {
                logitsSlice = putAlong(logitsSlice, suppressArr, values: negInf, axis: -1)
            }
        } else if let suppress = suppressTokens, !suppress.isEmpty {
            let suppressArr = MLXArray(suppress.map { Int32($0) }).reshaped(1, -1)
            let negInf = MLXArray.full(
                [1, suppress.count],
                values: MLXArray(-Float.infinity),
                dtype: logitsSlice.dtype
            )
            logitsSlice = putAlong(logitsSlice, suppressArr, values: negInf, axis: -1)
        }

        // Repetition penalty
        if repetitionPenalty != 1.0 {
            let tokenIds: MLXArray?
            if let scratch {
                tokenIds = scratch.repetitionTokenMLXArray(vocabUpperBound: logitsSlice.dim(-1))
            } else if let tokenIDs = generatedTokenIDs, !tokenIDs.isEmpty {
                let unique = tokenIDs.filter { $0 < logitsSlice.dim(-1) }
                tokenIds = unique.isEmpty
                    ? nil
                    : MLXArray(unique.map { Int32($0) }).reshaped(1, -1)
            } else {
                tokenIds = nil
            }
            if let tokenIds {
                let selected = takeAlong(logitsSlice, tokenIds, axis: -1)
                let penalized = which(
                    selected .< 0,
                    selected * repetitionPenalty,
                    selected / repetitionPenalty
                )
                logitsSlice = putAlong(logitsSlice, tokenIds, values: penalized, axis: -1)
            }
        }

        // Greedy if temperature 0
        if temperature <= 0 {
            return argMax(logitsSlice, axis: -1, keepDims: true)
        }

        // Sampling-order fix (ported from upstream mlx-audio a730a68, #735):
        // scale by temperature BEFORE the truncation filters so top-p/min-p
        // operate on the tempered distribution that is actually sampled.
        // Filtering raw logits and dividing by temperature only at the final
        // categorical() made the nucleus temperature-blind — wrong (too
        // narrow/wide) truncation for any temperature ≠ 1 once topP < 1 or
        // minP > 0 is in play. top-k is rank-based and unaffected either way.
        // The final categorical() therefore samples at T = 1.0 below.
        if temperature != 1.0 {
            logitsSlice = logitsSlice / temperature
        }

        // Preserve EOS logit so top-k/top-p/min-p do not permanently suppress it.
        let eosLogit: MLXArray? = if let eosTokenId, eosTokenId >= 0, eosTokenId < logitsSlice.dim(-1) {
            logitsSlice[0..., eosTokenId ..< (eosTokenId + 1)]
        } else {
            nil
        }

        // Apply top-k filtering (match mlx_lm.apply_top_k ordering and masking semantics)
        var filteredLogits = logitsSlice
        let vocabSize = logitsSlice.dim(-1)
        if topK > 0, topK < vocabSize {
            let kth = min(topK - 1, max(vocabSize - 1, 0))
            if kth >= 0 {
                let maskIdx = argPartition(-logitsSlice, kth: kth, axis: -1)[0..., topK...]
                let negInf: MLXArray
                if let scratch, maskIdx.dim(0) == 1 {
                    negInf = scratch.negInfRow(count: maskIdx.dim(-1), dtype: logitsSlice.dtype)
                } else {
                    negInf = MLXArray.full(
                        maskIdx.shape,
                        values: scratch?.negInfScalar ?? MLXArray(-Float.infinity),
                        dtype: logitsSlice.dtype
                    )
                }
                filteredLogits = putAlong(filteredLogits, maskIdx, values: negInf, axis: -1)
            }
        }

        // Apply top-p (nucleus) sampling
        if topP > 0, topP < 1.0 {
            let probs = softmax(filteredLogits, axis: -1)

            // Sort in ASCENDING order (like Python)
            let sortedIndices = argSort(filteredLogits, axis: -1)
            let sortedProbs = takeAlong(probs, sortedIndices, axis: -1)

            // Cumulative probabilities
            let cumProbs = cumsum(sortedProbs, axis: -1)

            // Rearrange cumulative probs back to original order
            // Create inverse index mapping using putAlong
            let sortedVocabSize = sortedIndices.dim(-1)
            let arangeIndices = scratch?.arangeIndices[0..., 0 ..< sortedVocabSize]
                ?? MLXArray(0 ..< sortedVocabSize).reshaped(1, -1).asType(Int32.self)
            let zeros = scratch?.zerosInt32(matching: sortedIndices.shape)
                ?? MLXArray.zeros(sortedIndices.shape, type: Int32.self)
            let inverseIndices = putAlong(zeros, sortedIndices, values: arangeIndices, axis: -1)
            let cumProbsOrigOrder = takeAlong(cumProbs, inverseIndices, axis: -1)

            // Mask tokens where cumulative prob > (1 - top_p)
            // Keep tokens that are in the top_p nucleus
            let threshold = 1.0 - topP
            let mask = cumProbsOrigOrder .> threshold
            let negInf: MLXArray
            if let scratch, filteredLogits.dim(0) == 1 {
                negInf = scratch.negInfRow(count: filteredLogits.dim(-1), dtype: filteredLogits.dtype)
            } else {
                negInf = MLXArray.full(
                    filteredLogits.shape,
                    values: scratch?.negInfScalar ?? MLXArray(-Float.infinity),
                    dtype: filteredLogits.dtype
                )
            }
            filteredLogits = which(mask, filteredLogits, negInf)
        }

        // Apply min-p sampling behavior (default kept at 0.0 for now)
        if minP > 0.0 {
            let scaledMinP = Float(log(Double(minP)))
            // Indices sorted in descending order (like Python `argsort(-logits)`)
            let sortedIndices = argSort(-filteredLogits, axis: -1)
            let sortedLogits = takeAlong(filteredLogits, sortedIndices, axis: -1)
            let topLogits = sortedLogits[0..., 0 ..< 1]
            let scaledMinPArray = MLXArray.full(
                topLogits.shape,
                values: MLXArray(scaledMinP),
                dtype: sortedLogits.dtype
            ) + topLogits
            let removeMask = sortedLogits .< scaledMinPArray
            let negInf = MLXArray.full(
                sortedLogits.shape,
                values: scratch?.negInfScalar ?? MLXArray(-Float.infinity),
                dtype: sortedLogits.dtype
            )
            let filteredSortedLogits = which(removeMask, negInf, sortedLogits)

            let invArange = scratch?.arangeIndices
                ?? MLXArray(0 ..< vocabSize).reshaped(1, -1).asType(Int32.self)
            let inverseIndices = putAlong(
                scratch?.zerosInt32(matching: sortedIndices.shape)
                    ?? MLXArray.zeros(sortedIndices.shape, type: Int32.self),
                sortedIndices,
                values: invArange,
                axis: -1
            )
            filteredLogits = takeAlong(filteredSortedLogits, inverseIndices, axis: -1)
        }

        if let eosLogit, let eosTokenId {
            let eosIdx = scratch?.eosIndex(eosTokenId) ?? MLXArray([Int32(eosTokenId)]).reshaped(1, 1)
            filteredLogits = putAlong(filteredLogits, eosIdx, values: eosLogit, axis: -1)
        }

        // Logits are already temperature-scaled above — sample at T = 1.0.
        let token = categorical(filteredLogits)
        return token.reshaped(1, 1)
    }

    private static let samplerCompileEnabled: Bool = {
        let raw = VocelloQwen3ImplementationDebugGate.value(
            for: "QWENVOICE_SAMPLER_COMPILE"
        )?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
        return raw == "on" || raw == "true" || raw == "1" || raw == "yes"
    }()

    // MARK: - fromPretrained

    public static func preparePreparedDirectory(_ modelDir: URL) throws {
        try ensureTokenizerJSON(in: modelDir)
    }

    public static func fromPretrained(
        _ modelRepo: String,
        cache: HubCache = .default,
        revision: String = "main",
        isolation: isolated (any Actor)? = #isolation
    ) async throws -> Qwen3TTSModel {
        let repoID = Repo.ID(rawValue: modelRepo)!
        let modelDir = try await ModelUtils.resolveOrDownloadModel(
            repoID: repoID,
            requiredExtension: "safetensors",
            revision: revision,
            cache: cache
        )
        return try await fromPreparedDirectory(
            modelDir,
            modelRepo: modelRepo,
            isolation: isolation
        )
    }

    public static func fromPreparedDirectory(
        _ modelDir: URL,
        modelRepo _: String,
        loadBehavior: QwenPreparedLoadBehavior = .fullCapabilities,
        diagnosticEventSink: (@Sendable (String, [String: String]) async -> Void)? = nil,
        isolation: isolated (any Actor)? = #isolation
    ) async throws -> Qwen3TTSModel {
        await emitPreparedLoadDiagnostic(
            diagnosticEventSink,
            action: "qwen-load-before-prepare-prepared-directory",
            details: diagnosticDetails(
                modelDir: modelDir,
                loadOptions: QwenPreparedLoadOptions(
                    trustPreparedCheckpoint: loadBehavior.trustPreparedCheckpoint,
                    preparedDirectoryAlreadyValidated: loadBehavior.preparedDirectoryAlreadyValidated,
                    loadSpeakerEncoder: loadBehavior.loadSpeakerEncoder,
                    loadSpeechTokenizerEncoder: loadBehavior.loadSpeechTokenizerEncoder,
                    skipSpeechTokenizerEval: loadBehavior.skipSpeechTokenizerEval
                )
            )
        )
        if !loadBehavior.preparedDirectoryAlreadyValidated {
            try preparePreparedDirectory(modelDir)
        }
        await emitPreparedLoadDiagnostic(
            diagnosticEventSink,
            action: "qwen-load-after-prepare-prepared-directory",
            details: diagnosticDetails(
                modelDir: modelDir,
                loadOptions: QwenPreparedLoadOptions(
                    trustPreparedCheckpoint: loadBehavior.trustPreparedCheckpoint,
                    preparedDirectoryAlreadyValidated: loadBehavior.preparedDirectoryAlreadyValidated,
                    loadSpeakerEncoder: loadBehavior.loadSpeakerEncoder,
                    loadSpeechTokenizerEncoder: loadBehavior.loadSpeechTokenizerEncoder,
                    skipSpeechTokenizerEval: loadBehavior.skipSpeechTokenizerEval
                )
            )
        )
        return try await loadModelContents(
            modelDir: modelDir,
            loadOptions: QwenPreparedLoadOptions(
                speechTokenizerContentIdentity: loadBehavior.speechTokenizerContentIdentity,
                trustPreparedCheckpoint: loadBehavior.trustPreparedCheckpoint,
                preparedDirectoryAlreadyValidated: loadBehavior.preparedDirectoryAlreadyValidated,
                loadSpeakerEncoder: loadBehavior.loadSpeakerEncoder,
                loadSpeechTokenizerEncoder: loadBehavior.loadSpeechTokenizerEncoder,
                skipSpeechTokenizerEval: loadBehavior.skipSpeechTokenizerEval
            ),
            diagnosticEventSink: diagnosticEventSink,
            isolation: isolation
        )
    }

    private static func loadModelContents(
        modelDir: URL,
        loadOptions: QwenPreparedLoadOptions,
        diagnosticEventSink: (@Sendable (String, [String: String]) async -> Void)?,
        isolation: isolated (any Actor)?
    ) async throws -> Qwen3TTSModel {
        _ = isolation
        await emitPreparedLoadDiagnostic(
            diagnosticEventSink,
            action: "qwen-load-before-config-read",
            details: diagnosticDetails(
                modelDir: modelDir,
                loadOptions: loadOptions
            )
        )
        let configData = try Data(contentsOf: modelDir.appendingPathComponent("config.json"))
        let config = try JSONDecoder().decode(Qwen3TTSModelConfig.self, from: configData)
        await emitPreparedLoadDiagnostic(
            diagnosticEventSink,
            action: "qwen-load-after-config-read",
            details: diagnosticDetails(
                modelDir: modelDir,
                loadOptions: loadOptions,
                extra: [
                    "ttsModelType": config.ttsModelType,
                    "speakerCount": "\(config.talkerConfig?.spkId?.count ?? 0)",
                ]
            )
        )
        let preparedKey = preparedDirectoryKey(for: modelDir)

        let componentCache = Qwen3TTSPreparedComponentCache.shared
        async let tokenizerComponent = loadTokenizerComponent(
            modelDir: modelDir,
            preparedKey: preparedKey,
            componentCache: componentCache
        )
        await emitPreparedLoadDiagnostic(
            diagnosticEventSink,
            action: "qwen-load-before-talker",
            details: diagnosticDetails(
                modelDir: modelDir,
                loadOptions: loadOptions,
                extra: [
                    "ttsModelType": config.ttsModelType,
                    "preparedKey": preparedKey,
                ]
            )
        )
        let talkerComponents = try await loadTalkerComponents(
            modelDir: modelDir,
            config: config,
            loadOptions: loadOptions,
            diagnosticEventSink: diagnosticEventSink,
            isolation: isolation
        )
        await emitPreparedLoadDiagnostic(
            diagnosticEventSink,
            action: "qwen-load-after-talker",
            details: diagnosticDetails(
                modelDir: modelDir,
                loadOptions: loadOptions,
                extra: [
                    "ttsModelType": config.ttsModelType,
                    "preparedKey": preparedKey,
                    "speakerEncoderLoaded": talkerComponents.speakerEncoder == nil ? "false" : "true",
                ]
            )
        )

        let model = Qwen3TTSModel(
            config: config,
            talker: talkerComponents.talker,
            speakerEncoder: talkerComponents.speakerEncoder
        )
        model.preparedKey = preparedKey

        await emitPreparedLoadDiagnostic(
            diagnosticEventSink,
            action: "qwen-load-before-tokenizer-await",
            details: diagnosticDetails(
                modelDir: modelDir,
                loadOptions: loadOptions,
                extra: [
                    "ttsModelType": config.ttsModelType,
                    "preparedKey": preparedKey,
                ]
            )
        )
        let tokenizerResult = await tokenizerComponent
        await emitPreparedLoadDiagnostic(
            diagnosticEventSink,
            action: "qwen-load-after-tokenizer-await",
            details: diagnosticDetails(
                modelDir: modelDir,
                loadOptions: loadOptions,
                extra: [
                    "ttsModelType": config.ttsModelType,
                    "preparedKey": preparedKey,
                    "tokenizerCacheHit": tokenizerResult.cacheHit ? "true" : "false",
                    "tokenizerDirectConfigLoadUsed": tokenizerResult.directConfigLoadUsed ? "true" : "false",
                    "tokenizerDirectConfigFallbackUsed": tokenizerResult.directConfigFallbackUsed ? "true" : "false",
                    "tokenizerLoaded": tokenizerResult.tokenizer == nil ? "false" : "true",
                ]
            )
        )
        model.tokenizer = tokenizerResult.tokenizer
        Memory.clearCache()

        await emitPreparedLoadDiagnostic(
            diagnosticEventSink,
            action: "qwen-load-before-speech-tokenizer",
            details: diagnosticDetails(
                modelDir: modelDir,
                loadOptions: loadOptions,
                extra: [
                    "ttsModelType": config.ttsModelType,
                    "preparedKey": preparedKey,
                ]
            )
        )
        let speechTokenizerResult = try await loadSpeechTokenizerComponent(
            modelDir: modelDir,
            preparedKey: preparedKey,
            loadOptions: loadOptions,
            includeEncoder: loadOptions.loadSpeechTokenizerEncoder ?? (config.ttsModelType == "base"),
            diagnosticEventSink: diagnosticEventSink,
            isolation: isolation
        )
        await emitPreparedLoadDiagnostic(
            diagnosticEventSink,
            action: "qwen-load-after-speech-tokenizer",
            details: diagnosticDetails(
                modelDir: modelDir,
                loadOptions: loadOptions,
                extra: [
                    "ttsModelType": config.ttsModelType,
                    "preparedKey": preparedKey,
                    "speechTokenizerCacheHit": "false",
                    "speechTokenizerModelLocal": "true",
                    "speechTokenizerDecoderLoaded": speechTokenizerResult.speechTokenizer == nil ? "false" : "true",
                    "speechTokenizerEncoderLoaded": (speechTokenizerResult.booleanFlags[
                        "speech_tokenizer_encoder_loaded"
                    ] ?? false) ? "true" : "false",
                ]
            )
        )
        model.speechTokenizer = speechTokenizerResult.speechTokenizer
        model.speechTokenizer?.decoder.resetStreamingState()

        var loadTimingsMS = talkerComponents.timingsMS
        loadTimingsMS["talker_weight_load"] = talkerComponents.talkerWeightLoadMS
        loadTimingsMS["tokenizer_load"] = tokenizerResult.loadMS
        loadTimingsMS["speech_tokenizer_load"] = speechTokenizerResult.loadMS
        model.storeLoadTimingsMS(loadTimingsMS)

        var loadBooleanFlags = talkerComponents.booleanFlags
        loadBooleanFlags["trusted_prepared_checkpoint"] = loadOptions.trustPreparedCheckpoint
        loadBooleanFlags["prepared_directory_already_validated"] = loadOptions.preparedDirectoryAlreadyValidated
        loadBooleanFlags["tokenizer_cache_hit"] = tokenizerResult.cacheHit
        loadBooleanFlags["tokenizer_direct_config_load"] = tokenizerResult.directConfigLoadUsed
        loadBooleanFlags["tokenizer_direct_config_fallback"] = tokenizerResult.directConfigFallbackUsed
        // Retain the old key as an explicit false compatibility projection.
        // Mutable decoder state is never shared between loaded model instances.
        loadBooleanFlags["speech_tokenizer_cache_hit"] = false
        loadBooleanFlags["speech_tokenizer_model_local"] = true
        loadBooleanFlags["speech_tokenizer_encoder_loaded"] = speechTokenizerResult.booleanFlags[
            "speech_tokenizer_encoder_loaded"
        ] ?? false
        loadBooleanFlags["speech_tokenizer_eval_skipped"] = loadOptions.skipSpeechTokenizerEval
        loadBooleanFlags["custom_instruction_control_supported"] = model.supportsCustomInstructionControl
        for (key, value) in speechTokenizerResult.booleanFlags {
            loadBooleanFlags[key] = value
        }
        model.storeLoadBooleanFlags(loadBooleanFlags)
        qwen3TTSLog("Loaded Qwen3-TTS model (\(config.ttsModelType))")
        return model
    }

    private static func loadTalkerComponents(
        modelDir: URL,
        config: Qwen3TTSModelConfig,
        loadOptions: QwenPreparedLoadOptions,
        diagnosticEventSink: (@Sendable (String, [String: String]) async -> Void)?,
        isolation: isolated (any Actor)?
    ) async throws -> LoadedTalkerComponents {
        _ = isolation
        let talkerConfig = config.talkerConfig ?? {
            let json = "{}".data(using: .utf8)!
            return try! JSONDecoder().decode(Qwen3TTSTalkerConfig.self, from: json)
        }()
        let shouldLoadSpeakerEncoder = loadOptions.loadSpeakerEncoder ?? (config.ttsModelType == "base")
        await emitPreparedLoadDiagnostic(
            diagnosticEventSink,
            action: "qwen-talker-before-weight-load",
            details: diagnosticDetails(
                modelDir: modelDir,
                loadOptions: loadOptions,
                extra: [
                    "ttsModelType": config.ttsModelType,
                    "speakerCount": "\(talkerConfig.spkId?.count ?? 0)",
                    "speakerEncoderRequested": shouldLoadSpeakerEncoder ? "true" : "false",
                ]
            )
        )
        let talker = Qwen3TTSTalkerForConditionalGeneration(config: talkerConfig)
        let speakerEncoder = shouldLoadSpeakerEncoder
            ? Qwen3TTSSpeakerEncoder(config: config.speakerEncoderConfig)
            : nil

        let talkerWeightLoadStartedAt = ContinuousClock.now
        var talkerWeights = [String: MLXArray]()
        var talkerTimingsMS: [String: Int] = [:]

        let talkerIOStartedAt = ContinuousClock.now
        var talkerSourceWeights = try loadWeights(
            from: modelDir,
            directSafetensorsFileName: "model.safetensors"
        )
        await emitPreparedLoadDiagnostic(
            diagnosticEventSink,
            action: "qwen-talker-after-weight-load",
            details: diagnosticDetails(
                modelDir: modelDir,
                loadOptions: loadOptions,
                extra: [
                    "ttsModelType": config.ttsModelType,
                    "sourceWeightCount": "\(talkerSourceWeights.count)",
                ]
            )
        )
        talkerTimingsMS["talker_safetensors_io"] = talkerIOStartedAt.elapsedMilliseconds

        let talkerSanitizeStartedAt = ContinuousClock.now
        for (key, value) in talkerSourceWeights where key.hasPrefix("talker.") {
            let sanitizedKey = String(key.dropFirst("talker.".count))
            talkerWeights[sanitizedKey] = value
        }

        if talkerWeights.isEmpty {
            talkerWeights = Qwen3TTSTalkerForConditionalGeneration.sanitize(
                weights: talkerSourceWeights
            )
        }
        await emitPreparedLoadDiagnostic(
            diagnosticEventSink,
            action: "qwen-talker-after-sanitize",
            details: diagnosticDetails(
                modelDir: modelDir,
                loadOptions: loadOptions,
                extra: [
                    "ttsModelType": config.ttsModelType,
                    "talkerWeightCount": "\(talkerWeights.count)",
                    "speakerWeightCount": shouldLoadSpeakerEncoder ? "\(talkerSourceWeights.count)" : "0",
                ]
            )
        )
        talkerTimingsMS["talker_weight_sanitize"] = talkerSanitizeStartedAt.elapsedMilliseconds
        var talkerPairs = talkerWeights.map { ($0.key, $0.value) }

        let talkerQuantizeStartedAt = ContinuousClock.now
        if config.quantization != nil || config.perLayerQuantization != nil {
            quantize(model: talker) { path, _ in
                guard talkerWeights["\(path).scales"] != nil else {
                    return nil
                }

                if let perLayerQuant = config.perLayerQuantization,
                   let layerQuant = perLayerQuant.quantization(layer: path) {
                    return layerQuant.asTuple
                }

                return config.quantization?.asTuple
            }
        }
        talkerTimingsMS["talker_quantize_prepare"] = talkerQuantizeStartedAt.elapsedMilliseconds

        await emitPreparedLoadDiagnostic(
            diagnosticEventSink,
            action: "qwen-talker-before-update",
            details: diagnosticDetails(
                modelDir: modelDir,
                loadOptions: loadOptions,
                extra: [
                    "ttsModelType": config.ttsModelType,
                    "talkerPairCount": "\(talkerPairs.count)",
                    "verifyMode": loadOptions.trustPreparedCheckpoint ? "no_unused_keys" : "all",
                ]
            )
        )
        let talkerVerifyMode: Module.VerifyUpdate = loadOptions.trustPreparedCheckpoint
            ? .noUnusedKeys
            : .all

        let talkerUpdateStartedAt = ContinuousClock.now
        try talker.update(
            parameters: ModuleParameters.unflattened(talkerPairs),
            verify: talkerVerifyMode
        )
        await emitPreparedLoadDiagnostic(
            diagnosticEventSink,
            action: "qwen-talker-after-update",
            details: diagnosticDetails(
                modelDir: modelDir,
                loadOptions: loadOptions,
                extra: [
                    "ttsModelType": config.ttsModelType,
                    "talkerPairCount": "\(talkerPairs.count)",
                ]
            )
        )
        talkerTimingsMS["talker_parameter_update"] = talkerUpdateStartedAt.elapsedMilliseconds
        talkerPairs.removeAll(keepingCapacity: false)
        talkerWeights.removeAll(keepingCapacity: false)
        Memory.clearCache()

        await emitPreparedLoadDiagnostic(
            diagnosticEventSink,
            action: "qwen-talker-before-eval",
            details: diagnosticDetails(
                modelDir: modelDir,
                loadOptions: loadOptions,
                extra: [
                    "ttsModelType": config.ttsModelType,
                ]
            )
        )
        let talkerEvalStartedAt = ContinuousClock.now
        talkerTimingsMS.merge(
            evaluateTalkerParametersInBatches(talker),
            uniquingKeysWith: { _, rhs in rhs }
        )
        await emitPreparedLoadDiagnostic(
            diagnosticEventSink,
            action: "qwen-talker-after-eval",
            details: diagnosticDetails(
                modelDir: modelDir,
                loadOptions: loadOptions,
                extra: [
                    "ttsModelType": config.ttsModelType,
                ]
            )
        )
        talkerTimingsMS["talker_parameter_eval"] = talkerEvalStartedAt.elapsedMilliseconds

        let talkerBooleanFlags: [String: Bool] = [
            "talker_verify_relaxed": loadOptions.trustPreparedCheckpoint,
            "talker_eval_chunked": true,
            "speaker_encoder_requested": shouldLoadSpeakerEncoder,
        ]

        if let speakerEncoder, shouldLoadSpeakerEncoder {
            var speakerWeights = try speakerEncoderWeightsForLoading(talkerSourceWeights)
            talkerSourceWeights.removeAll(keepingCapacity: false)
            Memory.clearCache()
            var speakerPairs = speakerWeights.map { ($0.key, $0.value) }
            let speakerUpdateStartedAt = ContinuousClock.now
            try speakerEncoder.update(
                parameters: ModuleParameters.unflattened(speakerPairs),
                verify: .all
            )
            talkerTimingsMS["speaker_encoder_update"] = speakerUpdateStartedAt.elapsedMilliseconds
            speakerPairs.removeAll(keepingCapacity: false)
            speakerWeights.removeAll(keepingCapacity: false)
            Memory.clearCache()

            let speakerEvalStartedAt = ContinuousClock.now
            eval(speakerEncoder.parameters())
            talkerTimingsMS["speaker_encoder_eval"] = speakerEvalStartedAt.elapsedMilliseconds
            qwen3TTSLog("Loaded speaker encoder")
            Memory.clearCache()
        } else if shouldLoadSpeakerEncoder {
            talkerSourceWeights.removeAll(keepingCapacity: false)
            Memory.clearCache()
            throw AudioGenerationError.invalidInput(
                "Requested learned component 'speaker_encoder' has no configuration."
            )
        } else {
            talkerSourceWeights.removeAll(keepingCapacity: false)
            Memory.clearCache()
        }

        return LoadedTalkerComponents(
            talker: talker,
            speakerEncoder: speakerEncoder,
            talkerWeightLoadMS: talkerWeightLoadStartedAt.elapsedMilliseconds,
            timingsMS: talkerTimingsMS,
            booleanFlags: talkerBooleanFlags
        )
    }

    private static func emitPreparedLoadDiagnostic(
        _ diagnosticEventSink: (@Sendable (String, [String: String]) async -> Void)?,
        action: String,
        details: [String: String]
    ) async {
        guard let diagnosticEventSink else {
            return
        }
        await diagnosticEventSink(action, details)
    }

    private static func diagnosticDetails(
        modelDir: URL,
        loadOptions: QwenPreparedLoadOptions,
        extra: [String: String] = [:]
    ) -> [String: String] {
        var details: [String: String] = [
            "modelDirectory": modelDir.path,
            "trustPreparedCheckpoint": loadOptions.trustPreparedCheckpoint ? "true" : "false",
            "preparedDirectoryAlreadyValidated": loadOptions.preparedDirectoryAlreadyValidated ? "true" : "false",
            "loadSpeakerEncoder": loadOptions.loadSpeakerEncoder.map { $0 ? "true" : "false" } ?? "auto",
            "loadSpeechTokenizerEncoder": loadOptions.loadSpeechTokenizerEncoder.map { $0 ? "true" : "false" } ?? "auto",
            "skipSpeechTokenizerEval": loadOptions.skipSpeechTokenizerEval ? "true" : "false",
        ]
        for (key, value) in extra {
            details[key] = value
        }
        return details
    }

    private static func evaluateTalkerParametersInBatches(
        _ talker: Qwen3TTSTalkerForConditionalGeneration
    ) -> [String: Int] {
        var timingsMS: [String: Int] = [:]

        let talkerCoreStartedAt = ContinuousClock.now
        var talkerCoreArrays: [MLXArray] = []
        talkerCoreArrays.append(
            contentsOf: flattenedParameterArrays(from: talker.model.codecEmbedding.parameters())
        )
        talkerCoreArrays.append(
            contentsOf: flattenedParameterArrays(from: talker.model.textEmbedding.parameters())
        )
        talkerCoreArrays.append(
            contentsOf: flattenedParameterArrays(from: talker.model.norm.parameters())
        )
        talkerCoreArrays.append(
            contentsOf: flattenedParameterArrays(from: talker.textProjection.parameters())
        )
        talkerCoreArrays.append(
            contentsOf: flattenedParameterArrays(from: talker.codecHead.parameters())
        )
        evalIfNeeded(talkerCoreArrays)
        timingsMS["talker_core_eval"] = talkerCoreStartedAt.elapsedMilliseconds

        let talkerLayerStartedAt = ContinuousClock.now
        evalLayerBatches(talker.model.layers, batchSize: talkerEvalLayerBatchSize)
        timingsMS["talker_decoder_layers_eval"] = talkerLayerStartedAt.elapsedMilliseconds

        let codePredictorCoreStartedAt = ContinuousClock.now
        var codePredictorCoreArrays: [MLXArray] = []
        if let projection = talker.codePredictor.projection {
            codePredictorCoreArrays.append(
                contentsOf: flattenedParameterArrays(from: projection.parameters())
            )
        }
        for embedding in talker.codePredictor.codecEmbedding {
            codePredictorCoreArrays.append(
                contentsOf: flattenedParameterArrays(from: embedding.parameters())
            )
        }
        codePredictorCoreArrays.append(
            contentsOf: flattenedParameterArrays(from: talker.codePredictor.model.norm.parameters())
        )
        for lmHead in talker.codePredictor.lmHead {
            codePredictorCoreArrays.append(
                contentsOf: flattenedParameterArrays(from: lmHead.parameters())
            )
        }
        evalIfNeeded(codePredictorCoreArrays)
        timingsMS["talker_code_predictor_core_eval"] = codePredictorCoreStartedAt.elapsedMilliseconds

        let codePredictorLayerStartedAt = ContinuousClock.now
        evalLayerBatches(talker.codePredictor.model.layers, batchSize: talkerEvalLayerBatchSize)
        timingsMS["talker_code_predictor_layers_eval"] = codePredictorLayerStartedAt.elapsedMilliseconds

        return timingsMS
    }

    private static func evalLayerBatches<Layer: Module>(
        _ layers: [Layer],
        batchSize: Int
    ) {
        guard batchSize > 0 else { return }

        for startIndex in stride(from: 0, to: layers.count, by: batchSize) {
            let endIndex = min(startIndex + batchSize, layers.count)
            var arrays: [MLXArray] = []
            for layer in layers[startIndex ..< endIndex] {
                arrays.append(contentsOf: flattenedParameterArrays(from: layer.parameters()))
            }
            evalIfNeeded(arrays)
        }
    }

    private static func flattenedParameterArrays(
        from parameters: ModuleParameters
    ) -> [MLXArray] {
        parameters.flattened().map(\.1)
    }

    private static func evalParameterArraysInBatches(
        _ arrays: [MLXArray],
        batchSize: Int
    ) {
        guard !arrays.isEmpty else { return }
        let resolvedBatchSize = max(batchSize, 1)
        var startIndex = 0
        while startIndex < arrays.count {
            let endIndex = min(startIndex + resolvedBatchSize, arrays.count)
            evalIfNeeded(Array(arrays[startIndex..<endIndex]))
            Memory.clearCache()
            startIndex = endIndex
        }
    }

    private static func evalIfNeeded(_ arrays: [MLXArray]) {
        guard !arrays.isEmpty else { return }
        eval(arrays)
    }

    private static func loadTokenizerComponent(
        modelDir: URL,
        preparedKey: String,
        componentCache: Qwen3TTSPreparedComponentCache
    ) async -> LoadedTokenizerComponent {
        let tokenizerLoadStartedAt = ContinuousClock.now
        var cacheHit = false
        var directConfigLoadUsed = false
        var directConfigFallbackUsed = false
        var tokenizer: (any Tokenizer)?

        do {
            if let cachedTokenizer = componentCache.cachedTokenizer(for: preparedKey) {
                tokenizer = cachedTokenizer.tokenizer
                cacheHit = true
            } else {
                do {
                    tokenizer = try loadTokenizerDirectly(from: modelDir)
                    directConfigLoadUsed = true
                } catch {
                    directConfigFallbackUsed = true
                    tokenizer = try await AutoTokenizer.from(modelFolder: modelDir)
                }

                if let tokenizer {
                    componentCache.storeTokenizer(tokenizer, for: preparedKey)
                }
            }
        } catch {
            qwen3TTSLog("Warning: Could not load tokenizer: \(error)")
        }

        return LoadedTokenizerComponent(
            tokenizer: tokenizer,
            cacheHit: cacheHit,
            directConfigLoadUsed: directConfigLoadUsed,
            directConfigFallbackUsed: directConfigFallbackUsed,
            loadMS: tokenizerLoadStartedAt.elapsedMilliseconds
        )
    }

    private static func loadTokenizerDirectly(from modelDir: URL) throws -> any Tokenizer {
        let tokenizerDataURL = modelDir.appendingPathComponent("tokenizer.json")
        let tokenizerConfigURL = modelDir.appendingPathComponent("tokenizer_config.json")
        guard FileManager.default.fileExists(atPath: tokenizerDataURL.path),
              FileManager.default.fileExists(atPath: tokenizerConfigURL.path) else {
            throw TokenizerError.missingConfig
        }

        let hub = HubApi.shared
        let tokenizerConfig = try hub.configuration(fileURL: tokenizerConfigURL)
        let tokenizerData = try hub.configuration(fileURL: tokenizerDataURL)
        return try PreTrainedTokenizer(
            tokenizerConfig: tokenizerConfig,
            tokenizerData: tokenizerData,
            strict: true
        )
    }

    private static func loadSpeechTokenizerComponent(
        modelDir: URL,
        preparedKey: String,
        loadOptions: QwenPreparedLoadOptions,
        includeEncoder: Bool,
        diagnosticEventSink: (@Sendable (String, [String: String]) async -> Void)?,
        isolation: isolated (any Actor)?
    ) async throws -> LoadedSpeechTokenizerComponent {
        _ = isolation
        let speechTokenizerPath = modelDir.appendingPathComponent("speech_tokenizer")
        var isDirectory: ObjCBool = false
        let speechTokenizerLoadStartedAt = ContinuousClock.now
        let fileManager = FileManager.default
        var speechTokenizer: Qwen3TTSSpeechTokenizer?
        var reusedResidentSpeechTokenizer = false

        if fileManager.fileExists(atPath: speechTokenizerPath.path, isDirectory: &isDirectory),
           isDirectory.boolValue {
            // Phase 9: adopt the previous model's identical tokenizer object
            // instead of re-materializing 682 MB. Exact content identity only;
            // any identity failure falls through to the ordinary disk load.
            // The host-attested trust identity (weights + config digests) is
            // preferred; the hard-link inode identity is the fallback for
            // loads without a trusted-checkpoint marker.
            let residencyIdentity = loadOptions.speechTokenizerContentIdentity
                .map { "trust:\($0)" }
                ?? speechTokenizerComponentIdentity(
                    at: speechTokenizerPath,
                    includeEncoder: includeEncoder
                )
            if let residencyIdentity,
               let residentBox = Qwen3TTSPreparedComponentCache.shared.residentSpeechTokenizer(
                   identityKey: residencyIdentity,
                   includeEncoder: includeEncoder
               ) {
                // Fresh-load parity: the encoder trims its cache per encode
                // call; the decoder's streaming state resets here and again at
                // every streaming generation start.
                residentBox.speechTokenizer.decoder.resetStreamingState()
                speechTokenizer = residentBox.speechTokenizer
                reusedResidentSpeechTokenizer = true
                await emitPreparedLoadDiagnostic(
                    diagnosticEventSink,
                    action: "qwen-speech-tokenizer-component-resident-reuse",
                    details: diagnosticDetails(
                        modelDir: modelDir,
                        loadOptions: loadOptions,
                        extra: [
                            "preparedKey": preparedKey,
                            "includeEncoder": includeEncoder ? "true" : "false",
                        ]
                    )
                )
            } else {
            do {
                await emitPreparedLoadDiagnostic(
                    diagnosticEventSink,
                    action: "qwen-speech-tokenizer-component-before-load",
                    details: diagnosticDetails(
                        modelDir: modelDir,
                        loadOptions: loadOptions,
                        extra: [
                            "preparedKey": preparedKey,
                            "includeEncoder": includeEncoder ? "true" : "false",
                        ]
                    )
                )
                speechTokenizer = try await loadSpeechTokenizer(
                    path: speechTokenizerPath,
                    trustPreparedCheckpoint: loadOptions.trustPreparedCheckpoint,
                    includeEncoder: includeEncoder,
                    skipSpeechTokenizerEval: loadOptions.skipSpeechTokenizerEval,
                    diagnosticEventSink: diagnosticEventSink,
                    isolation: isolation
                )
                await emitPreparedLoadDiagnostic(
                    diagnosticEventSink,
                    action: "qwen-speech-tokenizer-component-after-load",
                    details: diagnosticDetails(
                        modelDir: modelDir,
                        loadOptions: loadOptions,
                        extra: [
                            "preparedKey": preparedKey,
                            "includeEncoder": includeEncoder ? "true" : "false",
                        ]
                    )
                )
            } catch {
                await emitPreparedLoadDiagnostic(
                    diagnosticEventSink,
                    action: "qwen-speech-tokenizer-component-load-failed",
                    details: diagnosticDetails(
                        modelDir: modelDir,
                        loadOptions: loadOptions,
                        extra: [
                            "preparedKey": preparedKey,
                            "includeEncoder": includeEncoder ? "true" : "false",
                            "error": String(reflecting: error),
                        ]
                    )
                )
                throw error
            }
            if let residencyIdentity, let loaded = speechTokenizer {
                Qwen3TTSPreparedComponentCache.shared.storeResidentSpeechTokenizer(
                    loaded,
                    identityKey: residencyIdentity,
                    includesEncoder: includeEncoder
                )
            }
            }
        } else if fileManager.fileExists(atPath: speechTokenizerPath.path) {
            qwen3TTSLog("speech_tokenizer is not a directory (stale cache), clearing model cache...")
            try? fileManager.removeItem(at: modelDir)
            throw AudioGenerationError.modelNotInitialized(
                "Model cache was corrupted (speech_tokenizer). It has been cleared. Please try loading again."
            )
        } else {
            qwen3TTSLog("Warning: speech_tokenizer directory not found, speech decoding unavailable")
        }

        return LoadedSpeechTokenizerComponent(
            speechTokenizer: speechTokenizer,
            loadMS: speechTokenizerLoadStartedAt.elapsedMilliseconds,
            booleanFlags: [
                "speech_tokenizer_verify_relaxed": loadOptions.trustPreparedCheckpoint,
                "speech_tokenizer_encoder_loaded": includeEncoder,
                "speech_tokenizer_component_reused": reusedResidentSpeechTokenizer,
            ]
        )
    }

    /// Content identity for the on-disk speech tokenizer component, grounded
    /// in the shared-component store's hard links: the resolved weights
    /// file's device/inode/size/mtime plus the tokenizer config digest and
    /// the encoder inclusion. Copies that bypass the store simply never
    /// share an inode and miss the cache; any stat/read failure returns nil
    /// and disables residency for this load (the disk load proceeds).
    static func speechTokenizerComponentIdentity(
        at speechTokenizerPath: URL,
        includeEncoder: Bool
    ) -> String? {
        let weightsURL = speechTokenizerPath
            .appendingPathComponent("model.safetensors")
            .resolvingSymlinksInPath()
        guard let attributes = try? FileManager.default.attributesOfItem(atPath: weightsURL.path),
              let inode = (attributes[.systemFileNumber] as? NSNumber)?.uint64Value,
              let device = (attributes[.systemNumber] as? NSNumber)?.int64Value,
              let size = (attributes[.size] as? NSNumber)?.uint64Value,
              let modified = attributes[.modificationDate] as? Date else {
            return nil
        }
        let configURL = speechTokenizerPath.appendingPathComponent("config.json")
        guard let configData = try? Data(contentsOf: configURL) else {
            return nil
        }
        let configDigest = SHA256.hash(data: configData)
            .map { String(format: "%02x", $0) }
            .joined()
        _ = includeEncoder // capability is matched by the cache's superset rule, not the key
        return "st-v1:\(device):\(inode):\(size):\(modified.timeIntervalSince1970):\(configDigest)"
    }

    private func storeLoadTimingsMS(_ timings: [String: Int]) {
        diagnosticsLock.lock()
        storedLoadTimingsMS = timings
        diagnosticsLock.unlock()
    }

    private func storeLoadBooleanFlags(_ flags: [String: Bool]) {
        diagnosticsLock.lock()
        storedLoadBooleanFlags = flags
        diagnosticsLock.unlock()
    }

    private func storePreparationTimingsMS(_ timings: [String: Int]) {
        diagnosticsLock.lock()
        storedPreparationTimingsMS = timings
        diagnosticsLock.unlock()
    }

    private func mergePreparationTimingsMS(_ timings: [String: Int]) {
        diagnosticsLock.lock()
        storedPreparationTimingsMS.merge(timings) { _, rhs in rhs }
        diagnosticsLock.unlock()
    }

    private func storePreparationBooleanFlags(_ flags: [String: Bool]) {
        diagnosticsLock.lock()
        storedPreparationBooleanFlags = flags
        diagnosticsLock.unlock()
    }

    private func mergePreparationBooleanFlags(_ flags: [String: Bool]) {
        diagnosticsLock.lock()
        storedPreparationBooleanFlags.merge(flags) { _, rhs in rhs }
        diagnosticsLock.unlock()
    }

    private func storePreparationStringFlags(_ flags: [String: String]) {
        diagnosticsLock.lock()
        storedPreparationStringFlags = flags
        diagnosticsLock.unlock()
    }

    private func mergePreparationStringFlags(_ flags: [String: String]) {
        diagnosticsLock.lock()
        storedPreparationStringFlags.merge(flags) { _, rhs in rhs }
        diagnosticsLock.unlock()
    }

    private static func ensureTokenizerJSON(in modelDir: URL) throws {
        let fm = FileManager.default
        let tokenizerJsonPath = modelDir.appendingPathComponent("tokenizer.json")
        guard !fm.fileExists(atPath: tokenizerJsonPath.path) else {
            return
        }

        let vocabPath = modelDir.appendingPathComponent("vocab.json")
        let mergesPath = modelDir.appendingPathComponent("merges.txt")
        let hasVocab = fm.fileExists(atPath: vocabPath.path)
        let hasMerges = fm.fileExists(atPath: mergesPath.path)

        guard hasVocab, hasMerges else {
            qwen3TTSLog("Warning: Cannot generate tokenizer.json — vocab.json: \(hasVocab), merges.txt: \(hasMerges)")
            return
        }

        do {
            try generateTokenizerJson(
                vocabPath: vocabPath,
                mergesPath: mergesPath,
                tokenizerConfigPath: modelDir.appendingPathComponent("tokenizer_config.json"),
                outputPath: tokenizerJsonPath
            )
            qwen3TTSLog("Generated tokenizer.json from vocab.json + merges.txt")
        } catch {
            qwen3TTSLog("Warning: Failed to generate tokenizer.json: \(error)")
        }
    }

    private static func preparedDirectoryKey(for modelDir: URL) -> String {
        modelDir.standardizedFileURL.resolvingSymlinksInPath().path
    }

    private static func loadWeights(
        from directory: URL,
        directSafetensorsFileName: String
    ) throws -> [String: MLXArray] {
        let directWeightsURL = directory.appendingPathComponent(directSafetensorsFileName)
        if FileManager.default.fileExists(atPath: directWeightsURL.path) {
            return try MLX.loadArrays(url: directWeightsURL)
        }

        var mergedWeights = [String: MLXArray]()
        let files = try FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil)
        for file in files where file.pathExtension == "safetensors" {
            let weights = try MLX.loadArrays(url: file)
            mergedWeights.merge(weights) { _, new in new }
        }
        return mergedWeights
    }

    static func speakerEncoderWeightsForLoading(
        _ sourceWeights: [String: MLXArray]
    ) throws -> [String: MLXArray] {
        let weights = Qwen3TTSSpeakerEncoder.sanitize(weights: sourceWeights)
        try Qwen3LearnedComponentWeights.requireNonEmpty(
            weights.count,
            component: "speaker_encoder"
        )
        return weights
    }

    static func loadSpeechTokenizer(
        path: URL,
        trustPreparedCheckpoint: Bool,
        includeEncoder: Bool,
        skipSpeechTokenizerEval: Bool,
        diagnosticEventSink: (@Sendable (String, [String: String]) async -> Void)?,
        isolation: isolated (any Actor)? = #isolation
    ) async throws -> Qwen3TTSSpeechTokenizer {
        _ = isolation
        await emitPreparedLoadDiagnostic(
            diagnosticEventSink,
            action: "qwen-speech-tokenizer-load-start",
            details: [
                "path": path.path,
                "trustPreparedCheckpoint": trustPreparedCheckpoint ? "true" : "false",
                "includeEncoder": includeEncoder ? "true" : "false",
            ]
        )
        // Load config — fall back to defaults if config.json is missing
        let tokenizerConfig: Qwen3TTSTokenizerConfig
        let configPath = path.appendingPathComponent("config.json")
        if let configData = try? Data(contentsOf: configPath) {
            tokenizerConfig = try JSONDecoder().decode(Qwen3TTSTokenizerConfig.self, from: configData)
        } else {
            qwen3TTSLog("Warning: speech_tokenizer/config.json not found, using defaults")
            let defaultJson = "{}".data(using: .utf8)!
            tokenizerConfig = try JSONDecoder().decode(Qwen3TTSTokenizerConfig.self, from: defaultJson)
        }
        if let validationFailure = tokenizerConfig.qwen3TTS12HzValidationFailure(includeEncoder: includeEncoder) {
            throw AudioGenerationError.invalidInput(
                "Qwen3-TTS speech tokenizer contract mismatch: \(validationFailure)"
            )
        }
        await emitPreparedLoadDiagnostic(
            diagnosticEventSink,
            action: "qwen-speech-tokenizer-after-config",
            details: [
                "path": path.path,
                "trustPreparedCheckpoint": trustPreparedCheckpoint ? "true" : "false",
                "includeEncoder": includeEncoder ? "true" : "false",
                "inputSampleRate": "\(tokenizerConfig.inputSampleRate)",
                "outputSampleRate": "\(tokenizerConfig.outputSampleRate)",
                "frameRateHz": "12.5",
                "encoderValidNumQuantizers": "\(tokenizerConfig.encoderValidNumQuantizers)",
                "decoderNumQuantizers": "\(tokenizerConfig.decoderConfig?.numQuantizers ?? 0)",
                "encoderConfiguredNumQuantizers": "\(tokenizerConfig.encoderConfig?.numQuantizers ?? 0)",
                "decoderCodebookSize": "\(tokenizerConfig.decoderConfig?.codebookSize ?? 0)",
                "decoderSemanticCodebookSize": "\(tokenizerConfig.decoderConfig?.semanticCodebookSize ?? 0)",
            ]
        )

        let speechTokenizer = Qwen3TTSSpeechTokenizer(
            config: tokenizerConfig,
            includeEncoder: includeEncoder
        )

        // Load weights
        var tokenizerWeights = try loadWeights(
            from: path,
            directSafetensorsFileName: "model.safetensors"
        )

        try Qwen3LearnedComponentWeights.requireNonEmpty(
            tokenizerWeights.count,
            component: "speech_tokenizer"
        )

        if !tokenizerWeights.isEmpty {
            if !includeEncoder {
                tokenizerWeights = tokenizerWeights.filter { key, _ in
                    !key.hasPrefix("encoder_model.")
                        && !key.hasPrefix("speech_tokenizer.encoder_model.")
                        && !key.contains(".encoder_model.")
                }
            }
            var sanitized = Qwen3TTSSpeechTokenizer.sanitize(weights: tokenizerWeights)
            tokenizerWeights.removeAll(keepingCapacity: false)
            if !includeEncoder {
                sanitized = sanitized.filter { key, _ in
                    !key.hasPrefix("encoder_model.")
                }
            }
            var pairs = sanitized.map { ($0.key, $0.value) }
            try speechTokenizer.update(
                parameters: ModuleParameters.unflattened(pairs),
                verify: trustPreparedCheckpoint ? .noUnusedKeys : .all
            )
            pairs.removeAll(keepingCapacity: false)
            sanitized.removeAll(keepingCapacity: false)
            Memory.clearCache()
            await emitPreparedLoadDiagnostic(
                diagnosticEventSink,
                action: "qwen-speech-tokenizer-after-update",
                details: [
                    "path": path.path,
                    "trustPreparedCheckpoint": trustPreparedCheckpoint ? "true" : "false",
                    "includeEncoder": includeEncoder ? "true" : "false",
                    "parameterPairCount": "\(speechTokenizer.parameters().flattened().count)",
                ]
            )
            if skipSpeechTokenizerEval {
                await emitPreparedLoadDiagnostic(
                    diagnosticEventSink,
                    action: "qwen-speech-tokenizer-eval-skipped",
                    details: [
                        "path": path.path,
                        "includeEncoder": includeEncoder ? "true" : "false",
                        "parameterArrayCount": "0",
                        "reason": "skipSpeechTokenizerEval",
                    ]
                )
            } else {
                let parameterArrays = flattenedParameterArrays(from: speechTokenizer.parameters())
                await emitPreparedLoadDiagnostic(
                    diagnosticEventSink,
                    action: "qwen-speech-tokenizer-before-eval",
                    details: [
                        "path": path.path,
                        "includeEncoder": includeEncoder ? "true" : "false",
                        "parameterArrayCount": "\(parameterArrays.count)",
                        "evalBatchSize": "\(speechTokenizerEvalBatchSize)",
                    ]
                )
                evalParameterArraysInBatches(parameterArrays, batchSize: speechTokenizerEvalBatchSize)
                await emitPreparedLoadDiagnostic(
                    diagnosticEventSink,
                    action: "qwen-speech-tokenizer-after-eval",
                    details: [
                        "path": path.path,
                        "includeEncoder": includeEncoder ? "true" : "false",
                        "parameterArrayCount": "\(parameterArrays.count)",
                    ]
                )
            }
            Memory.clearCache()
        }

        speechTokenizer.decoder.resetStreamingState()
        qwen3TTSLog("Loaded speech tokenizer decoder")
        return speechTokenizer
    }

    // MARK: - Generate tokenizer.json from vocab.json + merges.txt

    /// Qwen3-TTS repos ship with a slow tokenizer (vocab.json + merges.txt) but
    /// swift-transformers requires tokenizer.json (fast tokenizer format). This
    /// generates the fast tokenizer JSON from the available files.
    private static func generateTokenizerJson(
        vocabPath: URL,
        mergesPath: URL,
        tokenizerConfigPath: URL,
        outputPath: URL
    ) throws {
        // Read vocab
        let vocabData = try Data(contentsOf: vocabPath)
        let vocabDict = try JSONSerialization.jsonObject(with: vocabData) as? [String: Int] ?? [:]

        // Read merges (skip header line "#version: ...")
        let mergesText = try String(contentsOf: mergesPath, encoding: .utf8)
        let mergeLines = mergesText.components(separatedBy: .newlines)
            .filter { !$0.isEmpty && !$0.hasPrefix("#") }

        // Read added_tokens from tokenizer_config.json
        var addedTokens = [[String: Any]]()
        if let configData = try? Data(contentsOf: tokenizerConfigPath),
           let configDict = try? JSONSerialization.jsonObject(with: configData) as? [String: Any],
           let addedTokensDecoder = configDict["added_tokens_decoder"] as? [String: [String: Any]] {
            for (idStr, tokenInfo) in addedTokensDecoder {
                guard let tokenId = Int(idStr),
                      let content = tokenInfo["content"] as? String else { continue }
                let entry: [String: Any] = [
                    "id": tokenId,
                    "content": content,
                    "single_word": tokenInfo["single_word"] as? Bool ?? false,
                    "lstrip": tokenInfo["lstrip"] as? Bool ?? false,
                    "rstrip": tokenInfo["rstrip"] as? Bool ?? false,
                    "normalized": tokenInfo["normalized"] as? Bool ?? false,
                    "special": tokenInfo["special"] as? Bool ?? true
                ]
                addedTokens.append(entry)
            }
            addedTokens.sort { ($0["id"] as? Int ?? 0) < ($1["id"] as? Int ?? 0) }
        }

        // Build tokenizer.json
        // Qwen2 uses ByteLevel BPE with a GPT-2-style regex pre-tokenizer
        let tokenizerJson: [String: Any] = [
            "version": "1.0",
            "truncation": NSNull(),
            "padding": NSNull(),
            "added_tokens": addedTokens,
            "normalizer": NSNull(),
            "pre_tokenizer": [
                "type": "Sequence",
                "pretokenizers": [
                    [
                        "type": "Split",
                        "pattern": [
                            "Regex": "(?i:'s|'t|'re|'ve|'m|'ll|'d)|[^\\r\\n\\p{L}\\p{N}]?\\p{L}+|\\p{N}{1,3}| ?[^\\s\\p{L}\\p{N}]+[\\r\\n]*|\\s*[\\r\\n]+|\\s+(?!\\S)|\\s+"
                        ],
                        "behavior": "Isolated",
                        "invert": false
                    ] as [String: Any],
                    [
                        "type": "ByteLevel",
                        "add_prefix_space": false,
                        "trim_offsets": true,
                        "use_regex": false
                    ] as [String: Any]
                ] as [[String: Any]]
            ] as [String: Any],
            "post_processor": NSNull(),
            "decoder": [
                "type": "ByteLevel",
                "add_prefix_space": true,
                "trim_offsets": true,
                "use_regex": true
            ] as [String: Any],
            "model": [
                "type": "BPE",
                "dropout": NSNull(),
                "unk_token": NSNull(),
                "continuing_subword_prefix": "",
                "end_of_word_suffix": "",
                "fuse_unk": false,
                "byte_fallback": false,
                "ignore_merges": false,
                "vocab": vocabDict,
                "merges": mergeLines
            ] as [String: Any]
        ]

        let jsonData = try JSONSerialization.data(withJSONObject: tokenizerJson, options: [.sortedKeys])
        try jsonData.write(to: outputPath)
    }
}

private extension ContinuousClock.Instant {
    var elapsedMilliseconds: Int {
        duration(to: .now).roundedMilliseconds
    }
}

private extension Duration {
    var roundedMilliseconds: Int {
        let components = components
        let secondsMS = Double(components.seconds) * 1_000
        let attosecondsMS = Double(components.attoseconds) / 1_000_000_000_000_000
        return Int((secondsMS + attosecondsMS).rounded())
    }
}
