import Foundation

/// Fully resolved inputs for the Phase 2 product-plan shadow projection.
///
/// The mapper is deliberately pure: it does not load a model, mutate MLX,
/// create a generation task, or start a second generation. The host supplies
/// the values that the shipping path already resolved and compares the
/// resulting plan with shipping authority. Plans remain shadow-only by design
/// after the Phase 4 actor/adapter cutover.
public struct GenerationPlanShadowInputs: Sendable {
    public let request: GenerationRequest
    public let resolvedGenerationID: UUID
    public let resolvedSpokenText: String
    public let modelIdentity: CoreModelIdentity
    public let modelCapabilities: Qwen3TTSModelCapabilities
    public let nativeMemoryPolicy: NativeMemoryPolicy
    public let talkerKVGeneratedWindow: Int?
    public let chunkPolicy: StreamChunkPolicy
    public let samplingPolicy: Qwen3SamplingPolicy
    public let outputPolicy: ProductOutputPlan
    public let qualityPolicy: ProductQualityPolicy
    public let cloneConditioningDigest: String?
    public let resolvedCloneTranscript: String?
    public let speakerNativeLanguage: String?

    public init(
        request: GenerationRequest,
        resolvedGenerationID: UUID,
        resolvedSpokenText: String? = nil,
        modelIdentity: CoreModelIdentity,
        modelCapabilities: Qwen3TTSModelCapabilities,
        nativeMemoryPolicy: NativeMemoryPolicy,
        talkerKVGeneratedWindow: Int?,
        chunkPolicy: StreamChunkPolicy,
        samplingPolicy: Qwen3SamplingPolicy,
        outputPolicy: ProductOutputPlan,
        qualityPolicy: ProductQualityPolicy,
        cloneConditioningDigest: String? = nil,
        resolvedCloneTranscript: String? = nil,
        speakerNativeLanguage: String? = nil
    ) {
        self.request = request
        self.resolvedGenerationID = resolvedGenerationID
        self.resolvedSpokenText = resolvedSpokenText ?? request.text
        self.modelIdentity = modelIdentity
        self.modelCapabilities = modelCapabilities
        self.nativeMemoryPolicy = nativeMemoryPolicy
        self.talkerKVGeneratedWindow = talkerKVGeneratedWindow
        self.chunkPolicy = chunkPolicy
        self.samplingPolicy = samplingPolicy
        self.outputPolicy = outputPolicy
        self.qualityPolicy = qualityPolicy
        self.cloneConditioningDigest = cloneConditioningDigest
        self.resolvedCloneTranscript = resolvedCloneTranscript
        self.speakerNativeLanguage = speakerNativeLanguage
    }
}

/// Values independently resolved by the shipping runtime before the shadow
/// mapper runs. This local-only snapshot is deliberately not `Codable`: it
/// contains model-facing text, conditioning instructions, and output routing.
/// Comparing against it prevents the shadow plan from validating itself by
/// calling the same projection twice.
struct GenerationShippingResolutionSnapshot: Hashable, Sendable {
    let originalText: String
    let spokenText: String
    let generationID: UUID
    let mode: GenerationMode
    let modelFacingText: String
    let language: String
    let model: CoreModelIdentity
    let conditioning: CoreConditioningPlan
    let sampling: Qwen3SamplingPolicy
    let chunking: StreamChunkPolicy
    let memory: RuntimeMemoryPolicy
    let output: ProductOutputPlan
    let quality: ProductQualityPolicy
}

public enum GenerationPlanShadowMappingError: Error, Equatable, Sendable {
    case missingCloneConditioningDigest
    case unexpectedCloneConditioningDigest
    case missingResolvedConditioning(GenerationMode)
}

/// Stable field identifiers for strict shadow comparison.
///
/// These names are safe to persist in local diagnostics. The comparison never
/// exposes either value, a value hash, text, prompts, paths, or descriptions.
public enum GenerationPlanShadowField: String, Codable, Hashable, Sendable {
    case requestGenerationID = "request.generation_id"
    case requestMode = "request.mode"
    case requestModelID = "request.model_id"
    case requestSeed = "request.seed"
    case requestOutputPath = "request.output_path"
    case requestShouldStream = "request.should_stream"
    case requestBatchIndex = "request.batch_index"
    case requestBatchTotal = "request.batch_total"

    case originalText = "product.original_text"
    case spokenText = "product.spoken_text"
    case generationID = "core.generation_id"
    case mode = "core.mode"
    case modelFacingText = "core.model_facing_text"
    case language = "core.language"
    case modelID = "core.model.model_id"
    case modelRepository = "core.model.repository"
    case modelRevision = "core.model.revision"
    case modelArtifactVersion = "core.model.artifact_version"
    case modelIntegrityDigest = "core.model.integrity_digest"
    case modelRuntimeProfile = "core.model.runtime_profile"
    case conditioningMode = "core.conditioning.mode"
    case conditioningPrimary = "core.conditioning.primary"
    case conditioningSecondary = "core.conditioning.secondary"
    case samplingAlgorithmVersion = "core.sampling.algorithm_version"
    case samplingEffectiveSeed = "core.sampling.effective_seed"
    case talkerTemperature = "core.sampling.talker.temperature"
    case talkerTopP = "core.sampling.talker.top_p"
    case talkerTopK = "core.sampling.talker.top_k"
    case talkerMinP = "core.sampling.talker.min_p"
    case subtalkerTemperature = "core.sampling.subtalker.temperature"
    case subtalkerTopP = "core.sampling.subtalker.top_p"
    case subtalkerTopK = "core.sampling.subtalker.top_k"
    case subtalkerMinP = "core.sampling.subtalker.min_p"
    case repetitionPenalty = "core.sampling.repetition_penalty"
    case maximumCodecTokens = "core.sampling.maximum_codec_tokens"
    case firstCodecFrames = "core.chunking.first_codec_frames"
    case laterCodecFrames = "core.chunking.later_codec_frames"
    case pendingFrameLimit = "core.chunking.pending_frame_limit"
    case materializationLeadSteps = "core.chunking.materialization_lead_steps"
    case evaluationPolicy = "core.chunking.evaluation_policy"
    case memoryTier = "core.memory.tier"
    case clearCacheOnStreamChunk = "core.memory.clear_cache_on_stream_chunk"
    case clearCacheAfterGeneration = "core.memory.clear_cache_after_generation"
    case tokenMemoryClearCadence = "core.memory.token_clear_cadence"
    case talkerKVGeneratedWindow = "core.memory.talker_kv_window"
    case retentionPolicy = "core.memory.retention_policy"
    case outputDestination = "output.destination"
    case outputShouldStream = "output.should_stream"
    case outputBatchIndex = "output.batch_index"
    case outputBatchTotal = "output.batch_total"
    case outputPublicationVersion = "output.publication_version"
    case qualityReviewPolicy = "quality.review_policy"
    case qualityAlgorithmVersion = "quality.algorithm_version"
}

public struct GenerationPlanShadowDrift: Codable, Hashable, Sendable {
    public let field: GenerationPlanShadowField

    public init(field: GenerationPlanShadowField) {
        self.field = field
    }

    public var diagnosticCode: String {
        "generation_plan_shadow_drift.\(field.rawValue)"
    }
}

public struct GenerationPlanShadowComparison: Codable, Hashable, Sendable {
    public static let schemaVersion = 1

    public let schemaVersion: Int
    public let drifts: [GenerationPlanShadowDrift]

    public init(drifts: [GenerationPlanShadowDrift]) {
        self.schemaVersion = Self.schemaVersion
        self.drifts = drifts
    }

    public var matches: Bool { drifts.isEmpty }

    public var diagnosticCodes: [String] {
        drifts.map(\.diagnosticCode)
    }
}

public struct GenerationPlanShadowProjection: Sendable {
    public let plan: ProductGenerationPlan
    public let comparison: GenerationPlanShadowComparison

    public init(
        plan: ProductGenerationPlan,
        comparison: GenerationPlanShadowComparison
    ) {
        self.plan = plan
        self.comparison = comparison
    }
}

public enum GenerationPlanShadowMapper {
    /// Builds and validates one immutable plan from already-resolved shipping
    /// inputs, then strictly compares every mapped field. This function is
    /// safe to call in production shadow mode because it has no runtime side
    /// effects and performs no model work.
    static func project(
        _ inputs: GenerationPlanShadowInputs,
        shipping: GenerationShippingResolutionSnapshot
    ) throws -> GenerationPlanShadowProjection {
        let plan = try makePlan(inputs)
        return GenerationPlanShadowProjection(
            plan: plan,
            comparison: compare(plan, against: inputs, shipping: shipping)
        )
    }

    static func makePlan(
        _ inputs: GenerationPlanShadowInputs
    ) throws -> ProductGenerationPlan {
        let prompt = GenerationSemantics.qwen3PromptAssembly(
            for: inputs.request,
            capabilities: inputs.modelCapabilities,
            resolvedCloneTranscript: inputs.resolvedCloneTranscript,
            speakerNativeLanguage: inputs.speakerNativeLanguage
        )

        let conditioning: CoreConditioningPlan
        switch inputs.request.payload {
        case .custom:
            guard let speakerID = prompt.speakerID else {
                throw GenerationPlanShadowMappingError.missingResolvedConditioning(.custom)
            }
            guard inputs.cloneConditioningDigest == nil else {
                throw GenerationPlanShadowMappingError.unexpectedCloneConditioningDigest
            }
            conditioning = .custom(
                speakerID: speakerID,
                deliveryInstruction: prompt.instruct
            )
        case .design:
            guard let instruction = prompt.instruct else {
                throw GenerationPlanShadowMappingError.missingResolvedConditioning(.design)
            }
            guard inputs.cloneConditioningDigest == nil else {
                throw GenerationPlanShadowMappingError.unexpectedCloneConditioningDigest
            }
            conditioning = .design(voiceDescription: instruction)
        case .clone:
            guard let digest = inputs.cloneConditioningDigest?
                .trimmingCharacters(in: .whitespacesAndNewlines),
                !digest.isEmpty else {
                throw GenerationPlanShadowMappingError.missingCloneConditioningDigest
            }
            conditioning = .clone(conditioningDigest: digest)
        }

        let nativeMemory = inputs.nativeMemoryPolicy
        let memory = RuntimeMemoryPolicy(
            tier: nativeMemory.deviceClass,
            clearCacheOnStreamChunk: nativeMemory.clearMLXCacheOnStreamChunkEmit,
            clearCacheAfterGeneration: nativeMemory.clearCacheAfterGeneration,
            tokenMemoryClearCadence: nativeMemory.mlxTokenMemoryClearCadence,
            talkerKVGeneratedWindow: inputs.talkerKVGeneratedWindow,
            retentionPolicy: nativeMemory.unloadAfterIdleSeconds == nil
                ? .retainUntilPressure
                : .retainUntilIdle
        )
        let core = CoreGenerationPlan(
            generationID: inputs.resolvedGenerationID,
            mode: inputs.request.mode,
            modelFacingText: prompt.text,
            language: prompt.language,
            model: inputs.modelIdentity,
            conditioning: conditioning,
            sampling: inputs.samplingPolicy,
            chunking: inputs.chunkPolicy,
            memory: memory
        )
        return try ProductGenerationPlan(
            originalText: inputs.request.text,
            spokenText: inputs.resolvedSpokenText,
            core: core,
            output: inputs.outputPolicy,
            quality: inputs.qualityPolicy
        ).validated()
    }

    static func compare(
        _ plan: ProductGenerationPlan,
        against inputs: GenerationPlanShadowInputs,
        shipping: GenerationShippingResolutionSnapshot
    ) -> GenerationPlanShadowComparison {
        var fields = Set<GenerationPlanShadowField>()

        func check<Value: Equatable>(
            _ field: GenerationPlanShadowField,
            _ expectedValue: Value,
            _ actualValue: Value
        ) {
            if expectedValue != actualValue {
                fields.insert(field)
            }
        }

        // Source coherence checks ensure that a caller cannot construct a
        // self-consistent plan from resolved values that drifted from the
        // accepted GenerationRequest.
        if let requestGenerationID = inputs.request.generationID {
            check(.requestGenerationID, requestGenerationID, inputs.resolvedGenerationID)
        }
        check(.requestMode, inputs.request.mode, inputs.request.payload.shadowMode)
        check(.requestModelID, inputs.request.modelID, inputs.modelIdentity.modelID)
        if let requestSeed = inputs.request.seed {
            check(.requestSeed, requestSeed, inputs.samplingPolicy.effectiveSeed)
        }
        check(.requestOutputPath, inputs.request.outputPath, inputs.outputPolicy.destinationPath)
        check(.requestShouldStream, inputs.request.shouldStream, inputs.outputPolicy.shouldStream)
        check(.requestBatchIndex, inputs.request.batchIndex, inputs.outputPolicy.batchIndex)
        check(.requestBatchTotal, inputs.request.batchTotal, inputs.outputPolicy.batchTotal)

        check(.originalText, shipping.originalText, plan.originalText)
        check(.spokenText, shipping.spokenText, plan.spokenText)
        check(.generationID, shipping.generationID, plan.core.generationID)
        check(.mode, shipping.mode, plan.core.mode)
        check(.modelFacingText, shipping.modelFacingText, plan.core.modelFacingText)
        check(.language, shipping.language, plan.core.language)
        compareModel(shipping.model, plan.core.model, check: check)
        compareConditioning(shipping.conditioning, plan.core.conditioning, check: check)
        compareSampling(shipping.sampling, plan.core.sampling, check: check)
        compareChunking(shipping.chunking, plan.core.chunking, check: check)
        compareMemory(shipping.memory, plan.core.memory, check: check)
        compareOutput(shipping.output, plan.output, check: check)
        check(.qualityReviewPolicy, shipping.quality.reviewPolicyID, plan.quality.reviewPolicyID)
        check(.qualityAlgorithmVersion, shipping.quality.algorithmVersion, plan.quality.algorithmVersion)

        return GenerationPlanShadowComparison(
            drifts: fields
                .sorted { $0.rawValue < $1.rawValue }
                .map(GenerationPlanShadowDrift.init(field:))
        )
    }

    private static func compareModel(
        _ expected: CoreModelIdentity,
        _ actual: CoreModelIdentity,
        check: (GenerationPlanShadowField, String, String) -> Void
    ) {
        check(.modelID, expected.modelID, actual.modelID)
        check(.modelRepository, expected.repository, actual.repository)
        check(.modelRevision, expected.revision, actual.revision)
        check(.modelArtifactVersion, expected.artifactVersion, actual.artifactVersion)
        check(.modelIntegrityDigest, expected.integrityManifestDigest, actual.integrityManifestDigest)
        check(.modelRuntimeProfile, expected.runtimeProfileSignature, actual.runtimeProfileSignature)
    }

    private static func compareConditioning(
        _ expected: CoreConditioningPlan,
        _ actual: CoreConditioningPlan,
        check: (GenerationPlanShadowField, String, String) -> Void
    ) {
        check(.conditioningMode, expected.mode.rawValue, actual.mode.rawValue)
        let expectedValues = expected.shadowValues
        let actualValues = actual.shadowValues
        check(.conditioningPrimary, expectedValues.primary, actualValues.primary)
        check(.conditioningSecondary, expectedValues.secondary, actualValues.secondary)
    }

    private static func compareSampling(
        _ expected: Qwen3SamplingPolicy,
        _ actual: Qwen3SamplingPolicy,
        check: (GenerationPlanShadowField, String, String) -> Void
    ) {
        check(.samplingAlgorithmVersion, String(expected.algorithmVersion), String(actual.algorithmVersion))
        check(.samplingEffectiveSeed, String(expected.effectiveSeed), String(actual.effectiveSeed))
        compareStage(expected.talker, actual.talker, prefix: .talker, check: check)
        compareStage(expected.subtalker, actual.subtalker, prefix: .subtalker, check: check)
        check(.repetitionPenalty, expected.repetitionPenalty.shadowBits, actual.repetitionPenalty.shadowBits)
        check(.maximumCodecTokens, String(expected.maximumCodecTokens), String(actual.maximumCodecTokens))
    }

    private enum StagePrefix { case talker, subtalker }

    private static func compareStage(
        _ expected: SamplingStage,
        _ actual: SamplingStage,
        prefix: StagePrefix,
        check: (GenerationPlanShadowField, String, String) -> Void
    ) {
        let fields: (
            GenerationPlanShadowField,
            GenerationPlanShadowField,
            GenerationPlanShadowField,
            GenerationPlanShadowField
        ) = prefix == .talker
            ? (.talkerTemperature, .talkerTopP, .talkerTopK, .talkerMinP)
            : (.subtalkerTemperature, .subtalkerTopP, .subtalkerTopK, .subtalkerMinP)
        check(fields.0, expected.temperature.shadowBits, actual.temperature.shadowBits)
        check(fields.1, expected.topP.shadowBits, actual.topP.shadowBits)
        check(fields.2, String(expected.topK), String(actual.topK))
        check(fields.3, expected.minP.shadowBits, actual.minP.shadowBits)
    }

    private static func compareChunking(
        _ expected: StreamChunkPolicy,
        _ actual: StreamChunkPolicy,
        check: (GenerationPlanShadowField, String, String) -> Void
    ) {
        check(.firstCodecFrames, String(expected.firstCodecFrames), String(actual.firstCodecFrames))
        check(.laterCodecFrames, String(expected.laterCodecFrames), String(actual.laterCodecFrames))
        check(.pendingFrameLimit, String(expected.pendingFrameLimit), String(actual.pendingFrameLimit))
        check(
            .materializationLeadSteps,
            String(expected.materializationLeadSteps),
            String(actual.materializationLeadSteps)
        )
        check(.evaluationPolicy, expected.evaluationPolicy.rawValue, actual.evaluationPolicy.rawValue)
    }

    private static func compareMemory(
        _ expected: RuntimeMemoryPolicy,
        _ actual: RuntimeMemoryPolicy,
        check: (GenerationPlanShadowField, String, String) -> Void
    ) {
        check(.memoryTier, expected.tier.rawValue, actual.tier.rawValue)
        check(
            .clearCacheOnStreamChunk,
            String(expected.clearCacheOnStreamChunk),
            String(actual.clearCacheOnStreamChunk)
        )
        check(
            .clearCacheAfterGeneration,
            String(expected.clearCacheAfterGeneration),
            String(actual.clearCacheAfterGeneration)
        )
        check(
            .tokenMemoryClearCadence,
            String(expected.tokenMemoryClearCadence),
            String(actual.tokenMemoryClearCadence)
        )
        check(
            .talkerKVGeneratedWindow,
            expected.talkerKVGeneratedWindow.map(String.init) ?? "none",
            actual.talkerKVGeneratedWindow.map(String.init) ?? "none"
        )
        check(.retentionPolicy, expected.retentionPolicy.rawValue, actual.retentionPolicy.rawValue)
    }

    private static func compareOutput(
        _ expected: ProductOutputPlan,
        _ actual: ProductOutputPlan,
        check: (GenerationPlanShadowField, String, String) -> Void
    ) {
        check(.outputDestination, expected.destinationPath, actual.destinationPath)
        check(.outputShouldStream, String(expected.shouldStream), String(actual.shouldStream))
        check(
            .outputBatchIndex,
            expected.batchIndex.map(String.init) ?? "none",
            actual.batchIndex.map(String.init) ?? "none"
        )
        check(
            .outputBatchTotal,
            expected.batchTotal.map(String.init) ?? "none",
            actual.batchTotal.map(String.init) ?? "none"
        )
        check(
            .outputPublicationVersion,
            String(expected.publicationPolicyVersion),
            String(actual.publicationPolicyVersion)
        )
    }
}

private extension GenerationRequest.Payload {
    var shadowMode: GenerationMode {
        switch self {
        case .custom: .custom
        case .design: .design
        case .clone: .clone
        }
    }
}

private extension CoreConditioningPlan {
    var shadowValues: (primary: String, secondary: String) {
        switch self {
        case .custom(let speakerID, let deliveryInstruction):
            (speakerID, deliveryInstruction ?? "none")
        case .design(let voiceDescription):
            (voiceDescription, "none")
        case .clone(let conditioningDigest):
            (conditioningDigest, "none")
        }
    }
}

private extension Double {
    var shadowBits: String { String(bitPattern, radix: 16) }
}
