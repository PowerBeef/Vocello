import Foundation

/// Stable Qwen3 synthesis modes owned by Vocello.
public enum VocelloQwen3SynthesisMode: String, CaseIterable, Codable, Hashable, Sendable {
    case customVoice = "custom_voice"
    case voiceDesign = "voice_design"
    case voiceClone = "voice_clone"
}

/// Runtime features that a prepared model bundle may advertise.
public enum VocelloQwen3Capability: String, CaseIterable, Codable, Hashable, Sendable {
    case streaming
    case customVoice = "custom_voice"
    case instructionControl = "instruction_control"
    case voiceDesign = "voice_design"
    case voiceClone = "voice_clone"
    case audioOnlyClone = "audio_only_clone"
    case typedDiagnostics = "typed_diagnostics"
}

/// Ordered, deterministic capability inventory for one model bundle.
public struct VocelloQwen3CapabilitySet: Codable, Hashable, Sendable {
    public let values: [VocelloQwen3Capability]

    public init(_ values: some Sequence<VocelloQwen3Capability>) {
        self.values = Array(Set(values)).sorted { $0.rawValue < $1.rawValue }
    }

    public func contains(_ capability: VocelloQwen3Capability) -> Bool {
        values.contains(capability)
    }

    public func supports(_ mode: VocelloQwen3SynthesisMode) -> Bool {
        switch mode {
        case .customVoice: contains(.customVoice)
        case .voiceDesign: contains(.voiceDesign)
        case .voiceClone: contains(.voiceClone)
        }
    }
}

/// Immutable model and artifact identity. The prepared directory is deliberately
/// kept on `VocelloQwen3PreparedModelBundle` and out of diagnostics.
public struct VocelloQwen3ModelIdentity: Codable, Hashable, Sendable {
    public let modelID: String
    public let repositoryID: String
    public let revision: String
    public let artifactVersion: String

    public init(
        modelID: String,
        repositoryID: String,
        revision: String,
        artifactVersion: String
    ) {
        self.modelID = modelID
        self.repositoryID = repositoryID
        self.revision = revision
        self.artifactVersion = artifactVersion
    }
}

/// A verified, prepared Qwen3 bundle ready for the owned runtime loader.
public struct VocelloQwen3PreparedModelBundle: Hashable, Sendable {
    public let identity: VocelloQwen3ModelIdentity
    public let preparedDirectory: URL
    public let modelType: String?
    public let trustedPreparedCheckpoint: Bool
    public let capabilities: VocelloQwen3CapabilitySet

    public init(
        identity: VocelloQwen3ModelIdentity,
        preparedDirectory: URL,
        modelType: String? = "qwen3_tts",
        trustedPreparedCheckpoint: Bool,
        capabilities: VocelloQwen3CapabilitySet
    ) {
        self.identity = identity
        self.preparedDirectory = preparedDirectory
        self.modelType = modelType
        self.trustedPreparedCheckpoint = trustedPreparedCheckpoint
        self.capabilities = capabilities
    }
}

/// Independently configurable categorical-sampling stage.
public struct VocelloQwen3SamplingStage: Codable, Hashable, Sendable {
    public let temperature: Float
    public let topP: Float
    public let topK: Int
    public let minP: Float

    public init(temperature: Float, topP: Float, topK: Int, minP: Float = 0) {
        self.temperature = temperature
        self.topP = topP
        self.topK = topK
        self.minP = minP
    }

    func validated(named name: String) throws -> Self {
        guard temperature.isFinite, temperature >= 0 else {
            throw VocelloQwen3ContractError.invalidTemperature
        }
        guard topP.isFinite, topP > 0, topP <= 1 else {
            throw VocelloQwen3ContractError.invalidTopP
        }
        guard topK > 0 else { throw VocelloQwen3ContractError.invalidTopK }
        guard minP.isFinite, minP >= 0, minP < 1 else {
            throw VocelloQwen3ContractError.invalidMinimumProbability(name)
        }
        return self
    }
}

/// Typed, request-local Qwen3 sampling policy.
///
/// The legacy scalar fields remain source-compatible aliases for the talker
/// stage. Version 2 adds an always-present effective seed and an independently
/// configurable subtalker stage. The compatibility adapter now carries every
/// field to the owned Qwen runtime instead of rejecting top-K or seed values.
public struct VocelloQwen3SamplingConfiguration: Codable, Hashable, Sendable {
    public static let currentAlgorithmVersion = 2
    public static let compatibilityDefaultTopK = 50

    public let algorithmVersion: Int
    public let effectiveSeed: UInt64
    public let talker: VocelloQwen3SamplingStage
    public let subtalker: VocelloQwen3SamplingStage
    public let maxNewTokens: Int
    public let temperature: Float
    public let topP: Float
    public let topK: Int
    public let repetitionPenalty: Float
    public let seed: UInt64?

    public init(
        maxNewTokens: Int,
        temperature: Float,
        topP: Float,
        topK: Int,
        repetitionPenalty: Float,
        seed: UInt64? = nil
    ) {
        let talker = VocelloQwen3SamplingStage(
            temperature: temperature,
            topP: topP,
            topK: topK
        )
        self.algorithmVersion = Self.currentAlgorithmVersion
        self.effectiveSeed = seed ?? UInt64.random(in: UInt64.min ... UInt64.max)
        self.talker = talker
        self.subtalker = talker
        self.maxNewTokens = maxNewTokens
        self.temperature = temperature
        self.topP = topP
        self.topK = topK
        self.repetitionPenalty = repetitionPenalty
        self.seed = seed
    }

    public init(
        algorithmVersion: Int = Self.currentAlgorithmVersion,
        effectiveSeed: UInt64,
        talker: VocelloQwen3SamplingStage,
        subtalker: VocelloQwen3SamplingStage,
        repetitionPenalty: Float,
        maxNewTokens: Int,
        requestedSeed: UInt64? = nil
    ) {
        self.algorithmVersion = algorithmVersion
        self.effectiveSeed = effectiveSeed
        self.talker = talker
        self.subtalker = subtalker
        self.maxNewTokens = maxNewTokens
        self.temperature = talker.temperature
        self.topP = talker.topP
        self.topK = talker.topK
        self.repetitionPenalty = repetitionPenalty
        self.seed = requestedSeed
    }

    public func validated() throws -> Self {
        guard algorithmVersion == Self.currentAlgorithmVersion else {
            throw VocelloQwen3ContractError.invalidSamplingAlgorithmVersion
        }
        guard maxNewTokens > 0 else { throw VocelloQwen3ContractError.invalidMaxNewTokens }
        _ = try talker.validated(named: "talker")
        _ = try subtalker.validated(named: "subtalker")
        guard temperature == talker.temperature,
              topP == talker.topP,
              topK == talker.topK else {
            throw VocelloQwen3ContractError.inconsistentTalkerAliases
        }
        guard repetitionPenalty > 0 else { throw VocelloQwen3ContractError.invalidRepetitionPenalty }
        return self
    }

    func validatedForCompatibilityAdapter() throws -> Self {
        try validated()
    }
}

/// Per-request memory policy resolved by the host before it crosses the facade.
public struct VocelloQwen3MemoryConfiguration: Codable, Hashable, Sendable {
    /// Compatibility behavior used only by legacy callers that have not yet
    /// supplied an explicit host-resolved tier policy.
    public static let compatibilityDefault = Self(
        clearCacheOnStreamChunk: true,
        tokenMemoryClearCadence: 50,
        talkerKVGeneratedWindow: nil
    )

    public let clearCacheOnStreamChunk: Bool
    public let tokenMemoryClearCadence: Int
    public let talkerKVGeneratedWindow: Int?

    public init(
        clearCacheOnStreamChunk: Bool,
        tokenMemoryClearCadence: Int,
        talkerKVGeneratedWindow: Int? = nil
    ) {
        self.clearCacheOnStreamChunk = clearCacheOnStreamChunk
        self.tokenMemoryClearCadence = tokenMemoryClearCadence
        self.talkerKVGeneratedWindow = talkerKVGeneratedWindow
    }

    public func validated() throws -> Self {
        guard tokenMemoryClearCadence > 0 else {
            throw VocelloQwen3ContractError.invalidMemoryClearCadence
        }
        if let talkerKVGeneratedWindow, talkerKVGeneratedWindow <= 0 {
            throw VocelloQwen3ContractError.invalidTalkerKVWindow
        }
        return self
    }
}

public enum VocelloQwen3StreamEvaluationPolicy: String, Codable, Hashable, Sendable {
    case full
    case eosOnly = "eos_only"
    case deferred
}

/// Explicit codec-frame schedule carried by every actor-owned request.
///
/// The compatibility Qwen loop currently derives its first chunk from a
/// 12.5-Hz interval and preserves the established mode-specific later-chunk
/// multiplier. Keeping the exact frame counts in the request prevents an
/// actor cutover from silently substituting a generic interval.
public struct VocelloQwen3StreamChunkConfiguration: Codable, Hashable, Sendable {
    public let firstCodecFrames: Int
    public let laterCodecFrames: Int
    public let pendingFrameLimit: Int
    public let materializationLeadSteps: Int
    public let evaluationPolicy: VocelloQwen3StreamEvaluationPolicy

    public init(
        firstCodecFrames: Int,
        laterCodecFrames: Int,
        pendingFrameLimit: Int,
        materializationLeadSteps: Int = 0,
        evaluationPolicy: VocelloQwen3StreamEvaluationPolicy = .full
    ) {
        self.firstCodecFrames = firstCodecFrames
        self.laterCodecFrames = laterCodecFrames
        self.pendingFrameLimit = pendingFrameLimit
        self.materializationLeadSteps = materializationLeadSteps
        self.evaluationPolicy = evaluationPolicy
    }

    public static func currentConstrainedDefault(
        for mode: VocelloQwen3SynthesisMode
    ) -> Self {
        let first = 7
        return Self(
            firstCodecFrames: first,
            laterCodecFrames: mode == .customVoice ? first : first * 2,
            pendingFrameLimit: mode == .customVoice ? first : first * 2
        )
    }

    public func validated(for mode: VocelloQwen3SynthesisMode) throws -> Self {
        let expectedLater = mode == .customVoice
            ? firstCodecFrames
            : firstCodecFrames * 2
        // The Phase 3 direct producer currently forwards the first-frame
        // interval and preserves the established later-frame multiplier. The
        // remaining controls are carried for the converged contract but are
        // not yet wired to Qwen. Reject non-control values instead of silently
        // accepting policy that the runtime would ignore.
        guard firstCodecFrames > 0,
              laterCodecFrames == expectedLater,
              pendingFrameLimit == max(firstCodecFrames, laterCodecFrames),
              materializationLeadSteps == 0,
              evaluationPolicy == .full else {
            throw VocelloQwen3ContractError.invalidChunkConfiguration
        }
        return self
    }

    var compatibilityStreamingInterval: Double {
        Double(firstCodecFrames) / 12.5
    }
}

public enum VocelloQwen3SynthesisInput: Codable, Hashable, Sendable {
    case customVoice(speakerID: String, deliveryInstruction: String?)
    case voiceDesign(description: String)
    case voiceClone(referenceID: String)

    public var mode: VocelloQwen3SynthesisMode {
        switch self {
        case .customVoice: .customVoice
        case .voiceDesign: .voiceDesign
        case .voiceClone: .voiceClone
        }
    }
}

/// Selects the owned model execution path without changing product output
/// policy. Quality-first requests still drain through the mandatory product
/// adapter, but the model emits one complete materialized payload and the
/// product suppresses preview publication.
public enum VocelloQwen3ExecutionStyle: String, Codable, Hashable, Sendable {
    case streaming
    case qualityFirst = "quality_first"
}

/// Product request boundary. Reference audio/tensors are resolved separately by
/// the host so this value remains portable and deterministic.
public struct VocelloQwen3SynthesisRequest: Codable, Hashable, Sendable {
    public let generationID: UUID
    public let text: String
    public let language: String
    public let input: VocelloQwen3SynthesisInput
    public let sampling: VocelloQwen3SamplingConfiguration
    public let memory: VocelloQwen3MemoryConfiguration
    public let chunking: VocelloQwen3StreamChunkConfiguration
    public let executionStyle: VocelloQwen3ExecutionStyle
    /// Gated diagnostic capture only; never enabled by normal product requests.
    public let captureCodecTrace: Bool

    public init(
        generationID: UUID,
        text: String,
        language: String,
        input: VocelloQwen3SynthesisInput,
        sampling: VocelloQwen3SamplingConfiguration,
        memory: VocelloQwen3MemoryConfiguration,
        chunking: VocelloQwen3StreamChunkConfiguration? = nil,
        executionStyle: VocelloQwen3ExecutionStyle = .streaming,
        captureCodecTrace: Bool = false
    ) {
        self.generationID = generationID
        self.text = text
        self.language = language
        self.input = input
        self.sampling = sampling
        self.memory = memory
        self.chunking = chunking ?? .currentConstrainedDefault(for: input.mode)
        self.executionStyle = executionStyle
        self.captureCodecTrace = captureCodecTrace
    }

    public var mode: VocelloQwen3SynthesisMode { input.mode }

    public func validated(for capabilities: VocelloQwen3CapabilitySet) throws -> Self {
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw VocelloQwen3ContractError.emptyText
        }
        guard !language.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw VocelloQwen3ContractError.emptyLanguage
        }
        guard capabilities.supports(mode) else {
            throw VocelloQwen3ContractError.unsupportedMode(mode)
        }
        _ = try sampling.validatedForCompatibilityAdapter()
        _ = try memory.validated()
        _ = try chunking.validated(for: mode)
        return self
    }

    private enum CodingKeys: String, CodingKey {
        case generationID, text, language, input, sampling, memory, chunking, executionStyle,
            captureCodecTrace
    }

    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let input = try container.decode(VocelloQwen3SynthesisInput.self, forKey: .input)
        self.generationID = try container.decode(UUID.self, forKey: .generationID)
        self.text = try container.decode(String.self, forKey: .text)
        self.language = try container.decode(String.self, forKey: .language)
        self.input = input
        self.sampling = try container.decode(
            VocelloQwen3SamplingConfiguration.self,
            forKey: .sampling
        )
        self.memory = try container.decode(
            VocelloQwen3MemoryConfiguration.self,
            forKey: .memory
        )
        self.chunking = try container.decodeIfPresent(
            VocelloQwen3StreamChunkConfiguration.self,
            forKey: .chunking
        ) ?? .currentConstrainedDefault(for: input.mode)
        self.executionStyle = try container.decodeIfPresent(
            VocelloQwen3ExecutionStyle.self,
            forKey: .executionStyle
        ) ?? .streaming
        self.captureCodecTrace = try container.decodeIfPresent(
            Bool.self,
            forKey: .captureCodecTrace
        ) ?? false
    }

    public func encode(to encoder: any Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(generationID, forKey: .generationID)
        try container.encode(text, forKey: .text)
        try container.encode(language, forKey: .language)
        try container.encode(input, forKey: .input)
        try container.encode(sampling, forKey: .sampling)
        try container.encode(memory, forKey: .memory)
        try container.encode(chunking, forKey: .chunking)
        try container.encode(executionStyle, forKey: .executionStyle)
        try container.encode(captureCodecTrace, forKey: .captureCodecTrace)
    }
}

public enum VocelloQwen3CancellationReason: String, Codable, Hashable, Sendable {
    case user
    case memoryPressure = "memory_pressure"
    case superseded
    case shutdown
}

public enum VocelloQwen3FinishReason: String, Codable, Hashable, Sendable {
    case endOfSequence = "end_of_sequence"
    case maximumTokens = "maximum_tokens"
}

public enum VocelloQwen3FailureCode: String, Codable, Hashable, Sendable {
    case contractViolation = "contract_violation"
    case incompatibleModel = "incompatible_model"
    case memoryPressure = "memory_pressure"
    case runtime
    case unknown
}

public enum VocelloQwen3TerminalOutcome: Codable, Hashable, Sendable {
    case completed(VocelloQwen3FinishReason)
    case cancelled(VocelloQwen3CancellationReason)
    case failed(VocelloQwen3FailureCode)
}

public enum VocelloQwen3DiagnosticPhase: String, Codable, Hashable, Sendable {
    case modelPreparation = "model_preparation"
    case modelLoad = "model_load"
    case prewarm
    case synthesis
    case decode
    case finalization
}

public enum VocelloQwen3DiagnosticDisposition: String, Codable, Hashable, Sendable {
    case began
    case completed
    case cancelled
    case failed
    case observed
}

/// Privacy-safe typed runtime evidence. It intentionally has no raw message,
/// path, prompt, transcript, URL, or arbitrary metadata dictionary.
public struct VocelloQwen3DiagnosticEvent: Codable, Hashable, Sendable {
    public let generationID: UUID?
    public let phase: VocelloQwen3DiagnosticPhase
    public let disposition: VocelloQwen3DiagnosticDisposition
    public let elapsedMilliseconds: Int?
    public let generatedTokenCount: Int?
    public let audioFrameCount: Int?
    public let peakMemoryBytes: UInt64?
    public let failureCode: VocelloQwen3FailureCode?

    public init(
        generationID: UUID? = nil,
        phase: VocelloQwen3DiagnosticPhase,
        disposition: VocelloQwen3DiagnosticDisposition,
        elapsedMilliseconds: Int? = nil,
        generatedTokenCount: Int? = nil,
        audioFrameCount: Int? = nil,
        peakMemoryBytes: UInt64? = nil,
        failureCode: VocelloQwen3FailureCode? = nil
    ) {
        self.generationID = generationID
        self.phase = phase
        self.disposition = disposition
        self.elapsedMilliseconds = elapsedMilliseconds
        self.generatedTokenCount = generatedTokenCount
        self.audioFrameCount = audioFrameCount
        self.peakMemoryBytes = peakMemoryBytes
        self.failureCode = failureCode
    }
}

public typealias VocelloQwen3DiagnosticSink = @Sendable (VocelloQwen3DiagnosticEvent) async -> Void

public enum VocelloQwen3ContractError: Error, Equatable, Sendable {
    case incompatibleLoadedModel
    case missingClonePrompt
    case emptyText
    case emptyLanguage
    case unsupportedMode(VocelloQwen3SynthesisMode)
    case invalidMaxNewTokens
    case invalidTemperature
    case invalidTopP
    case invalidTopK
    case invalidMinimumProbability(String)
    case invalidSamplingAlgorithmVersion
    case inconsistentTalkerAliases
    case invalidRepetitionPenalty
    // Retained for source/decoding compatibility with pre-v2 callers. The v2
    // adapter no longer emits these failures because both values are carried.
    case unsupportedRequestTopK(Int)
    case unsupportedRequestSeed
    case invalidMemoryClearCadence
    case invalidTalkerKVWindow
    case invalidChunkConfiguration
}
