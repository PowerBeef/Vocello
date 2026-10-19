import CryptoKit
import Foundation

public enum RuntimeRefactorPlanError: Error, Equatable, Sendable {
    case emptyField(String)
    case invalidPolicy(String)
    case modeConditioningMismatch
    case invalidBatchPosition
}

/// Immutable request-local sampling values for the converged Qwen3 runtime.
///
/// Product/core plan construction remains shadow-only by design after the
/// Phase 4 mode cutover. The shipping sampling adapter already maps the
/// equivalent policy to a request-local MLX random state and does not mutate
/// global RNG state.
public struct SamplingStage: Codable, Hashable, Sendable {
    public let temperature: Double
    public let topP: Double
    public let topK: Int
    public let minP: Double

    public init(temperature: Double, topP: Double, topK: Int, minP: Double) {
        self.temperature = temperature
        self.topP = topP
        self.topK = topK
        self.minP = minP
    }

    fileprivate var identityComponents: [String] {
        [
            RuntimePlanCanonical.double(temperature),
            RuntimePlanCanonical.double(topP),
            String(topK),
            RuntimePlanCanonical.double(minP),
        ]
    }
}

public struct Qwen3SamplingPolicy: Codable, Hashable, Sendable {
    public let algorithmVersion: Int
    public let effectiveSeed: UInt64
    public let talker: SamplingStage
    public let subtalker: SamplingStage
    public let repetitionPenalty: Double
    public let maximumCodecTokens: Int

    public init(
        algorithmVersion: Int,
        effectiveSeed: UInt64,
        talker: SamplingStage,
        subtalker: SamplingStage,
        repetitionPenalty: Double,
        maximumCodecTokens: Int
    ) {
        self.algorithmVersion = algorithmVersion
        self.effectiveSeed = effectiveSeed
        self.talker = talker
        self.subtalker = subtalker
        self.repetitionPenalty = repetitionPenalty
        self.maximumCodecTokens = maximumCodecTokens
    }

    public func validated() throws -> Self {
        guard algorithmVersion > 0 else {
            throw RuntimeRefactorPlanError.invalidPolicy("sampling.algorithmVersion")
        }
        for (name, stage) in [("talker", talker), ("subtalker", subtalker)] {
            guard stage.temperature.isFinite, stage.temperature >= 0,
                  stage.topP.isFinite, stage.topP > 0, stage.topP <= 1,
                  stage.topK > 0,
                  stage.minP.isFinite, stage.minP >= 0, stage.minP < 1 else {
                throw RuntimeRefactorPlanError.invalidPolicy("sampling.\(name)")
            }
        }
        guard repetitionPenalty.isFinite, repetitionPenalty > 0 else {
            throw RuntimeRefactorPlanError.invalidPolicy("sampling.repetitionPenalty")
        }
        guard maximumCodecTokens > 0 else {
            throw RuntimeRefactorPlanError.invalidPolicy("sampling.maximumCodecTokens")
        }
        return self
    }

    fileprivate var canonicalSerialization: String {
        RuntimePlanCanonical.serialize(
            namespace: "sampling-policy",
            components: [
                String(algorithmVersion),
                String(effectiveSeed),
            ] + talker.identityComponents + subtalker.identityComponents + [
                RuntimePlanCanonical.double(repetitionPenalty),
                String(maximumCodecTokens),
            ]
        )
    }
}

public enum StreamEvaluationPolicy: String, Codable, Hashable, Sendable {
    case full
    case eosOnly = "eos_only"
    case deferred
}

public struct StreamChunkPolicy: Codable, Hashable, Sendable {
    public let firstCodecFrames: Int
    public let laterCodecFrames: Int
    public let pendingFrameLimit: Int
    public let materializationLeadSteps: Int
    public let evaluationPolicy: StreamEvaluationPolicy

    public init(
        firstCodecFrames: Int,
        laterCodecFrames: Int,
        pendingFrameLimit: Int,
        materializationLeadSteps: Int,
        evaluationPolicy: StreamEvaluationPolicy
    ) {
        self.firstCodecFrames = firstCodecFrames
        self.laterCodecFrames = laterCodecFrames
        self.pendingFrameLimit = pendingFrameLimit
        self.materializationLeadSteps = materializationLeadSteps
        self.evaluationPolicy = evaluationPolicy
    }

    /// Shadow representation of the shipping 8 GB Mac/iPhone defaults.
    ///
    /// `NativeMemoryPolicyResolver` floors the interval at 0.6 seconds on
    /// constrained tiers, and this mapper truncates `0.6 * 12.5` to seven codec
    /// frames (`currentShippingDefault` below). Its baseline Custom profile
    /// remains seven frames; Design and Clone use the existing post-first
    /// multiplier of two.
    public static func currentConstrainedTierDefault(for mode: GenerationMode) -> Self {
        let firstFrames = 7
        let laterFrames = mode == .custom ? firstFrames : firstFrames * 2
        return Self(
            firstCodecFrames: firstFrames,
            laterCodecFrames: laterFrames,
            pendingFrameLimit: laterFrames,
            materializationLeadSteps: 0,
            evaluationPolicy: .full
        )
    }

    /// Shadow representation of the shipping Qwen codec-frame schedule for an
    /// already-resolved streaming interval. Qwen emits at 12.5 codec frames per
    /// second, and currently keeps Custom's later chunk equal to the first while
    /// Design/Clone double it. The truncation here is the shipping policy and must
    /// stay: `0.6 * 12.5` is exactly 7.5 in Double, so rounding would move the
    /// constrained tier from 7 to 8 frames. The owned runtime converts the frames
    /// it receives back exactly (`compatibilityStreamingInterval` and
    /// `Qwen3StreamChunkSchedule.codecFrames`, engine audit A-15).
    public static func currentShippingDefault(
        for mode: GenerationMode,
        effectiveStreamingInterval: Double
    ) -> Self {
        let firstFrames = max(1, Int(effectiveStreamingInterval * 12.5))
        let laterFrames = mode == .custom ? firstFrames : firstFrames * 2
        return Self(
            firstCodecFrames: firstFrames,
            laterCodecFrames: laterFrames,
            pendingFrameLimit: laterFrames,
            materializationLeadSteps: 0,
            evaluationPolicy: .full
        )
    }

    public func validated() throws -> Self {
        guard firstCodecFrames > 0, laterCodecFrames > 0,
              pendingFrameLimit >= max(firstCodecFrames, laterCodecFrames),
              materializationLeadSteps >= 0 else {
            throw RuntimeRefactorPlanError.invalidPolicy("chunking")
        }
        return self
    }

    fileprivate var canonicalSerialization: String {
        RuntimePlanCanonical.serialize(
            namespace: "stream-chunk-policy",
            components: [
                String(firstCodecFrames),
                String(laterCodecFrames),
                String(pendingFrameLimit),
                String(materializationLeadSteps),
                evaluationPolicy.rawValue,
            ]
        )
    }
}

public enum RuntimeRetentionPolicy: String, Codable, Hashable, Sendable {
    case retainUntilIdle = "retain_until_idle"
    case releaseAfterGeneration = "release_after_generation"
    case retainUntilPressure = "retain_until_pressure"
}

public struct RuntimeMemoryPolicy: Codable, Hashable, Sendable {
    public let tier: NativeDeviceMemoryClass
    public let clearCacheOnStreamChunk: Bool
    public let clearCacheAfterGeneration: Bool
    public let tokenMemoryClearCadence: Int
    public let talkerKVGeneratedWindow: Int?
    public let retentionPolicy: RuntimeRetentionPolicy

    public init(
        tier: NativeDeviceMemoryClass,
        clearCacheOnStreamChunk: Bool,
        clearCacheAfterGeneration: Bool,
        tokenMemoryClearCadence: Int,
        talkerKVGeneratedWindow: Int?,
        retentionPolicy: RuntimeRetentionPolicy
    ) {
        self.tier = tier
        self.clearCacheOnStreamChunk = clearCacheOnStreamChunk
        self.clearCacheAfterGeneration = clearCacheAfterGeneration
        self.tokenMemoryClearCadence = tokenMemoryClearCadence
        self.talkerKVGeneratedWindow = talkerKVGeneratedWindow
        self.retentionPolicy = retentionPolicy
    }

    public func validated() throws -> Self {
        guard tokenMemoryClearCadence > 0,
              talkerKVGeneratedWindow.map({ $0 > 0 }) ?? true else {
            throw RuntimeRefactorPlanError.invalidPolicy("memory")
        }
        return self
    }

    fileprivate var canonicalSerialization: String {
        RuntimePlanCanonical.serialize(
            namespace: "runtime-memory-policy",
            components: [
                tier.rawValue,
                String(clearCacheOnStreamChunk),
                String(clearCacheAfterGeneration),
                String(tokenMemoryClearCadence),
                talkerKVGeneratedWindow.map(String.init) ?? "",
                retentionPolicy.rawValue,
            ]
        )
    }
}

/// Exact learned-artifact and runtime-profile identity used by a core plan.
/// Local filesystem paths intentionally do not participate.
public struct CoreModelIdentity: Codable, Hashable, Sendable {
    public let modelID: String
    public let repository: String
    public let revision: String
    public let artifactVersion: String
    public let integrityManifestDigest: String
    public let runtimeProfileSignature: String

    public init(
        modelID: String,
        repository: String,
        revision: String,
        artifactVersion: String,
        integrityManifestDigest: String,
        runtimeProfileSignature: String
    ) {
        self.modelID = modelID
        self.repository = repository
        self.revision = revision
        self.artifactVersion = artifactVersion
        self.integrityManifestDigest = integrityManifestDigest
        self.runtimeProfileSignature = runtimeProfileSignature
    }

    public func validated() throws -> Self {
        for (name, value) in [
            ("model.modelID", modelID),
            ("model.repository", repository),
            ("model.revision", revision),
            ("model.artifactVersion", artifactVersion),
            ("model.integrityManifestDigest", integrityManifestDigest),
            ("model.runtimeProfileSignature", runtimeProfileSignature),
        ] where value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            throw RuntimeRefactorPlanError.emptyField(name)
        }
        return self
    }

    fileprivate var canonicalSerialization: String {
        RuntimePlanCanonical.serialize(
            namespace: "core-model-identity",
            components: [
                modelID,
                repository,
                revision,
                artifactVersion,
                integrityManifestDigest,
                runtimeProfileSignature,
            ]
        )
    }
}

/// App-private conditioning values. This type is deliberately not `Codable`:
/// descriptions and speaker instructions must never enter durable telemetry
/// or benchmark evidence through a generic encoder.
public enum CoreConditioningPlan: Hashable, Sendable {
    case custom(speakerID: String, deliveryInstruction: String?)
    case design(voiceDescription: String)
    case clone(conditioningDigest: String)

    public var mode: GenerationMode {
        switch self {
        case .custom: .custom
        case .design: .design
        case .clone: .clone
        }
    }

    fileprivate var canonicalSerialization: String {
        switch self {
        case .custom(let speakerID, let deliveryInstruction):
            RuntimePlanCanonical.serialize(
                namespace: "conditioning-custom",
                components: [speakerID, deliveryInstruction ?? ""]
            )
        case .design(let voiceDescription):
            RuntimePlanCanonical.serialize(
                namespace: "conditioning-design",
                components: [voiceDescription]
            )
        case .clone(let conditioningDigest):
            RuntimePlanCanonical.serialize(
                namespace: "conditioning-clone",
                components: [conditioningDigest]
            )
        }
    }
}

/// The model-facing request boundary. It contains no destination path or
/// product publication policy.
/// App-private model-facing request. Deliberately not `Codable`; only
/// `GenerationEvidenceIdentity` is a durable serialization boundary.
public struct CoreGenerationPlan: Hashable, Sendable {
    public static let schemaVersion = 1

    public let generationID: UUID
    public let mode: GenerationMode
    public let modelFacingText: String
    public let language: String
    public let model: CoreModelIdentity
    public let conditioning: CoreConditioningPlan
    public let sampling: Qwen3SamplingPolicy
    public let chunking: StreamChunkPolicy
    public let memory: RuntimeMemoryPolicy

    public init(
        generationID: UUID,
        mode: GenerationMode,
        modelFacingText: String,
        language: String,
        model: CoreModelIdentity,
        conditioning: CoreConditioningPlan,
        sampling: Qwen3SamplingPolicy,
        chunking: StreamChunkPolicy,
        memory: RuntimeMemoryPolicy
    ) {
        self.generationID = generationID
        self.mode = mode
        self.modelFacingText = modelFacingText
        self.language = language
        self.model = model
        self.conditioning = conditioning
        self.sampling = sampling
        self.chunking = chunking
        self.memory = memory
    }

    public func validated() throws -> Self {
        guard mode == conditioning.mode else {
            throw RuntimeRefactorPlanError.modeConditioningMismatch
        }
        for (name, value) in [
            ("core.modelFacingText", modelFacingText),
            ("core.language", language),
        ] where value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            throw RuntimeRefactorPlanError.emptyField(name)
        }
        switch conditioning {
        case .custom(let speakerID, _):
            guard !speakerID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                throw RuntimeRefactorPlanError.emptyField("conditioning.speakerID")
            }
        case .design(let description):
            guard !description.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                throw RuntimeRefactorPlanError.emptyField("conditioning.voiceDescription")
            }
        case .clone(let digest):
            guard !digest.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                throw RuntimeRefactorPlanError.emptyField("conditioning.conditioningDigest")
            }
        }
        _ = try model.validated()
        _ = try sampling.validated()
        _ = try chunking.validated()
        _ = try memory.validated()
        return self
    }
}

/// App-private output routing. Local destination paths are intentionally not
/// encodable and cannot be passed to generic telemetry/history serializers.
public struct ProductOutputPlan: Hashable, Sendable {
    public let destinationPath: String
    public let shouldStream: Bool
    public let batchIndex: Int?
    public let batchTotal: Int?
    public let publicationPolicyVersion: Int

    public init(
        destinationPath: String,
        shouldStream: Bool,
        batchIndex: Int?,
        batchTotal: Int?,
        publicationPolicyVersion: Int
    ) {
        self.destinationPath = destinationPath
        self.shouldStream = shouldStream
        self.batchIndex = batchIndex
        self.batchTotal = batchTotal
        self.publicationPolicyVersion = publicationPolicyVersion
    }

    public func validated() throws -> Self {
        guard !destinationPath.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw RuntimeRefactorPlanError.emptyField("output.destinationPath")
        }
        guard publicationPolicyVersion > 0 else {
            throw RuntimeRefactorPlanError.invalidPolicy("output.publicationPolicyVersion")
        }
        switch (batchIndex, batchTotal) {
        case (nil, nil):
            break
        case let (index?, total?) where index > 0 && total > 0 && index <= total:
            break
        default:
            throw RuntimeRefactorPlanError.invalidBatchPosition
        }
        return self
    }

    fileprivate var canonicalSerialization: String {
        RuntimePlanCanonical.serialize(
            namespace: "product-output-plan",
            components: [
                RuntimePlanCanonical.digest(destinationPath),
                String(shouldStream),
                batchIndex.map(String.init) ?? "",
                batchTotal.map(String.init) ?? "",
                String(publicationPolicyVersion),
            ]
        )
    }
}

public struct ProductQualityPolicy: Codable, Hashable, Sendable {
    public let reviewPolicyID: String
    public let algorithmVersion: Int

    public init(reviewPolicyID: String, algorithmVersion: Int) {
        self.reviewPolicyID = reviewPolicyID
        self.algorithmVersion = algorithmVersion
    }

    public func validated() throws -> Self {
        guard !reviewPolicyID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw RuntimeRefactorPlanError.emptyField("quality.reviewPolicyID")
        }
        guard algorithmVersion > 0 else {
            throw RuntimeRefactorPlanError.invalidPolicy("quality.algorithmVersion")
        }
        return self
    }

    fileprivate var canonicalSerialization: String {
        RuntimePlanCanonical.serialize(
            namespace: "product-quality-policy",
            components: [reviewPolicyID, String(algorithmVersion)]
        )
    }
}

/// App-private plan. Original/spoken text and the local output path are
/// intentionally not encodable. Tracked or durable evidence must use the
/// allowlisted `evidenceIdentity` projection instead.
public struct ProductGenerationPlan: Hashable, Sendable {
    public static let schemaVersion = 1

    public let originalText: String
    public let spokenText: String
    public let core: CoreGenerationPlan
    public let output: ProductOutputPlan
    public let quality: ProductQualityPolicy

    public init(
        originalText: String,
        spokenText: String,
        core: CoreGenerationPlan,
        output: ProductOutputPlan,
        quality: ProductQualityPolicy
    ) {
        self.originalText = originalText
        self.spokenText = spokenText
        self.core = core
        self.output = output
        self.quality = quality
    }

    public func validated() throws -> Self {
        for (name, value) in [
            ("product.originalText", originalText),
            ("product.spokenText", spokenText),
        ] where value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            throw RuntimeRefactorPlanError.emptyField(name)
        }
        _ = try core.validated()
        _ = try output.validated()
        _ = try quality.validated()
        return self
    }

    public var dependencyIdentities: GenerationPlanDependencyIdentities {
        let modelPreparation = RuntimePlanCanonical.digest(
            RuntimePlanCanonical.serialize(
                namespace: "model-preparation-dependency",
                components: [core.model.canonicalSerialization]
            )
        )
        let conditioning = RuntimePlanCanonical.digest(
            RuntimePlanCanonical.serialize(
                namespace: "conditioning-dependency",
                components: [modelPreparation, core.conditioning.canonicalSerialization]
            )
        )
        let sampling = RuntimePlanCanonical.digest(core.sampling.canonicalSerialization)
        let chunking = RuntimePlanCanonical.digest(core.chunking.canonicalSerialization)
        let memory = RuntimePlanCanonical.digest(core.memory.canonicalSerialization)
        let outputIdentity = RuntimePlanCanonical.digest(output.canonicalSerialization)
        let qualityIdentity = RuntimePlanCanonical.digest(quality.canonicalSerialization)
        let complete = RuntimePlanCanonical.digest(
            RuntimePlanCanonical.serialize(
                namespace: "complete-product-plan",
                components: [
                    String(Self.schemaVersion),
                    core.generationID.uuidString.lowercased(),
                    core.mode.rawValue,
                    RuntimePlanCanonical.digest(originalText),
                    RuntimePlanCanonical.digest(spokenText),
                    RuntimePlanCanonical.digest(core.modelFacingText),
                    core.language,
                    modelPreparation,
                    conditioning,
                    sampling,
                    chunking,
                    memory,
                    outputIdentity,
                    qualityIdentity,
                ]
            )
        )
        return GenerationPlanDependencyIdentities(
            modelPreparation: modelPreparation,
            conditioning: conditioning,
            sampling: sampling,
            chunking: chunking,
            memory: memory,
            output: outputIdentity,
            quality: qualityIdentity,
            complete: complete
        )
    }

    /// Privacy-safe projection suitable for telemetry and tracked benchmark
    /// evidence. It contains no text, prompt, description, or path.
    public var evidenceIdentity: GenerationEvidenceIdentity {
        GenerationEvidenceIdentity(
            schemaVersion: 1,
            generationID: core.generationID,
            mode: core.mode,
            modelID: core.model.modelID,
            originalTextUTF8ByteCount: originalText.utf8.count,
            spokenTextUTF8ByteCount: spokenText.utf8.count,
            modelFacingTextUTF8ByteCount: core.modelFacingText.utf8.count,
            samplingAlgorithmVersion: core.sampling.algorithmVersion,
            dependencyIdentities: dependencyIdentities
        )
    }
}

public struct GenerationPlanDependencyIdentities: Codable, Hashable, Sendable {
    public let modelPreparation: String
    public let conditioning: String
    public let sampling: String
    public let chunking: String
    public let memory: String
    public let output: String
    public let quality: String
    public let complete: String

    public init(
        modelPreparation: String,
        conditioning: String,
        sampling: String,
        chunking: String,
        memory: String,
        output: String,
        quality: String,
        complete: String
    ) {
        self.modelPreparation = modelPreparation
        self.conditioning = conditioning
        self.sampling = sampling
        self.chunking = chunking
        self.memory = memory
        self.output = output
        self.quality = quality
        self.complete = complete
    }
}

public struct GenerationEvidenceIdentity: Codable, Hashable, Sendable {
    public let schemaVersion: Int
    public let generationID: UUID
    public let mode: GenerationMode
    public let modelID: String
    public let originalTextUTF8ByteCount: Int
    public let spokenTextUTF8ByteCount: Int
    public let modelFacingTextUTF8ByteCount: Int
    public let samplingAlgorithmVersion: Int
    public let dependencyIdentities: GenerationPlanDependencyIdentities

    public init(
        schemaVersion: Int,
        generationID: UUID,
        mode: GenerationMode,
        modelID: String,
        originalTextUTF8ByteCount: Int,
        spokenTextUTF8ByteCount: Int,
        modelFacingTextUTF8ByteCount: Int,
        samplingAlgorithmVersion: Int,
        dependencyIdentities: GenerationPlanDependencyIdentities
    ) {
        self.schemaVersion = schemaVersion
        self.generationID = generationID
        self.mode = mode
        self.modelID = modelID
        self.originalTextUTF8ByteCount = originalTextUTF8ByteCount
        self.spokenTextUTF8ByteCount = spokenTextUTF8ByteCount
        self.modelFacingTextUTF8ByteCount = modelFacingTextUTF8ByteCount
        self.samplingAlgorithmVersion = samplingAlgorithmVersion
        self.dependencyIdentities = dependencyIdentities
    }

    /// Stable JSON for local telemetry/manifest projection. This is separate
    /// from the length-framed dependency identities so encoder changes cannot
    /// alter cache or plan invalidation boundaries.
    public func canonicalJSONData() throws -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        return try encoder.encode(self)
    }

    public func canonicalDigest() throws -> String {
        RuntimePlanCanonical.digest(try canonicalJSONData())
    }
}

private enum RuntimePlanCanonical {
    static func serialize(namespace: String, components: [String]) -> String {
        ([namespace] + components).map { component in
            "\(component.utf8.count):\(component)"
        }.joined()
    }

    static func digest(_ value: String) -> String {
        digest(Data(value.utf8))
    }

    static func digest(_ data: Data) -> String {
        SHA256.hash(data: data).map { unsafe String(format: "%02x", $0) }.joined()
    }

    static func double(_ value: Double) -> String {
        String(value.bitPattern, radix: 16)
    }
}
