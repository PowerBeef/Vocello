import Foundation
@preconcurrency import QwenVoiceBackendCore
@preconcurrency import VocelloQwen3Core

/// Host-boundary resolver for immutable request-local sampling policy.
/// Environment values are read only through `RuntimeDebugGate`; the resulting
/// value crosses the package boundary once and no process-global request state
/// remains in the runtime.
enum Qwen3TalkerSamplingOverride {
    static let envTemperature: Float? = floatValue("QWENVOICE_TALKER_TEMP")
    static let envTopP: Float? = floatValue("QWENVOICE_TALKER_TOPP")
    static let envTopK: Int? = intValue("QWENVOICE_TALKER_TOPK")
    static let envMinP: Float? = nonnegativeFloatValue("QWENVOICE_TALKER_MINP")
    static let envSubtalkerTemperature: Float? = floatValue("QWENVOICE_SUBTALKER_TEMP")
    static let envSubtalkerTopP: Float? = floatValue("QWENVOICE_SUBTALKER_TOPP")
    static let envSubtalkerTopK: Int? = intValue("QWENVOICE_SUBTALKER_TOPK")
    /// Talker-only repetition penalty for bench A/B against dropout counts
    /// (Stage 0.4). The subtalker remains deliberately unpenalized.
    static let envRepetitionPenalty: Float? = floatValue("QWENVOICE_TALKER_REPPEN")

    private static func floatValue(_ key: String) -> Float? {
        guard let raw = RuntimeDebugGate.value(for: key),
              let value = Float(raw), value > 0 else { return nil }
        return value
    }

    private static func nonnegativeFloatValue(_ key: String) -> Float? {
        guard let raw = RuntimeDebugGate.value(for: key),
              let value = Float(raw), value >= 0 else { return nil }
        return value
    }

    private static func intValue(_ key: String) -> Int? {
        guard let raw = RuntimeDebugGate.value(for: key),
              let value = Int(raw), value > 0 else { return nil }
        return value
    }

    static func samplingConfiguration(
        requestedSeed: UInt64?,
        variation: Qwen3SamplingVariation?
    ) -> VocelloQwen3SamplingConfiguration {
        let official = Qwen3GenerationConfiguration.officialQualityDefault
        var temperature = official.temperature
        var topP = official.topP
        switch variation {
        case .balanced:
            temperature = 0.8
            topP = 0.95
        case .consistent:
            temperature = 0.7
            topP = 0.9
        case .expressive, nil:
            break
        }
        if let envTemperature { temperature = envTemperature }
        if let envTopP { topP = envTopP }
        let talker = VocelloQwen3SamplingStage(
            temperature: temperature,
            topP: topP,
            topK: envTopK ?? official.topK,
            minP: envMinP ?? 0
        )
        let subtalker = VocelloQwen3SamplingStage(
            temperature: envSubtalkerTemperature ?? talker.temperature,
            topP: envSubtalkerTopP ?? talker.topP,
            topK: envSubtalkerTopK ?? talker.topK,
            minP: talker.minP
        )
        let effectiveSeed = requestedSeed ?? UInt64.random(in: UInt64.min ... UInt64.max)
        return VocelloQwen3SamplingConfiguration(
            algorithmVersion: VocelloQwen3SamplingConfiguration.currentAlgorithmVersion,
            effectiveSeed: effectiveSeed,
            talker: talker,
            subtalker: subtalker,
            repetitionPenalty: envRepetitionPenalty ?? official.repetitionPenalty,
            maxNewTokens: official.maxNewTokens,
            requestedSeed: requestedSeed
        )
    }
}

/// Product-side single-owner pairing of the runtime actor with its post-load
/// facts. The loaded model itself never crosses the package boundary: every
/// mutation routes through `VocelloQwen3Engine`, and only immutable metadata
/// and request bindings live here.
final class UnsafeSpeechGenerationModel: Sendable {
    /// One actor is paired with one loaded model. Request-bound wrappers share
    /// this exact authority so a generation cutover can never load or mutate a
    /// second copy of the model behind the product coordinator's back.
    let engine: VocelloQwen3Engine
    let facts: VocelloQwen3LoadedModelFacts
    private let requestSampling: VocelloQwen3SamplingConfiguration?
    private let requestMemory: VocelloQwen3MemoryConfiguration?

    init(
        engine: VocelloQwen3Engine,
        facts: VocelloQwen3LoadedModelFacts,
        requestSampling: VocelloQwen3SamplingConfiguration? = nil,
        requestMemory: VocelloQwen3MemoryConfiguration? = nil
    ) {
        self.engine = engine
        self.facts = facts
        self.requestSampling = requestSampling
        self.requestMemory = requestMemory
    }

    /// Loads the prepared bundle into a fresh actor and captures its facts.
    /// The verbose sink is the local-diagnostics load-stage channel; see
    /// `VocelloQwen3VerboseLoadDiagnosticSink` for its confinement contract.
    static func load(
        bundle: VocelloQwen3PreparedModelBundle,
        loadBehavior: VocelloQwen3LoadBehavior,
        verboseDiagnosticSink: VocelloQwen3VerboseLoadDiagnosticSink? = nil
    ) async throws -> UnsafeSpeechGenerationModel {
        let engine = VocelloQwen3Engine()
        _ = try await engine.load(
            bundle,
            behavior: loadBehavior,
            verboseDiagnosticSink: verboseDiagnosticSink
        )
        guard let facts = await engine.loadedModelFacts() else {
            throw MLXTTSEngineError.modelUnavailable(
                "The runtime actor reported no loaded model after a successful load."
            )
        }
        return UnsafeSpeechGenerationModel(engine: engine, facts: facts)
    }

    func bound(
        to sampling: VocelloQwen3SamplingConfiguration,
        memory: VocelloQwen3MemoryConfiguration
    ) -> UnsafeSpeechGenerationModel {
        UnsafeSpeechGenerationModel(
            engine: engine,
            facts: facts,
            requestSampling: sampling,
            requestMemory: memory
        )
    }

    var samplingConfiguration: VocelloQwen3SamplingConfiguration {
        requestSampling ?? Qwen3TalkerSamplingOverride.samplingConfiguration(
            requestedSeed: nil,
            variation: nil
        )
    }

    var memoryConfiguration: VocelloQwen3MemoryConfiguration {
        requestMemory ?? .compatibilityDefault
    }

    var sampleRate: Int { facts.sampleRate }
    var loadDiagnosticsTimingsMS: [String: Int] { facts.loadDiagnostics.timingsMilliseconds }
    var loadDiagnosticBooleanFlags: [String: Bool] { facts.loadDiagnostics.booleanFlags }

    func latestPreparationTimingsMS() async -> [String: Int] {
        await engine.preparationDiagnostics()?.timingsMilliseconds ?? [:]
    }

    func latestPreparationBooleanFlags() async -> [String: Bool] {
        await engine.preparationDiagnostics()?.booleanFlags ?? [:]
    }

    func latestPreparationStringFlags() async -> [String: String] {
        await engine.preparationDiagnostics()?.stringFlags ?? [:]
    }

    func resetPreparationDiagnostics() async {
        await engine.resetPreparationDiagnostics()
    }

    func replayCodecTrace(
        frames: [[Int32]],
        incrementalRanges: [StartupReliabilityCodecFrameRange]
    ) async throws -> StartupReliabilityCodecReplayResult {
        let replay = try await engine.replayCodecTrace(
            frames: frames,
            incrementalRanges: incrementalRanges.map {
                VocelloQwen3CodecFrameRange(start: $0.start, endExclusive: $0.endExclusive)
            }
        )
        return StartupReliabilityCodecReplayResult(
            incrementalAudio: replay.incrementalAudio,
            fullAudio: replay.fullAudio,
            sampleRate: replay.sampleRate
        )
    }

    var supportsDedicatedCustomVoice: Bool { facts.capabilities.contains(.customVoice) }
    var supportsOptimizedCustomVoice: Bool { facts.capabilities.contains(.customVoice) }
    var supportsOptimizedVoiceDesign: Bool { facts.capabilities.contains(.voiceDesign) }
    var supportsOptimizedVoiceClone: Bool { facts.capabilities.contains(.voiceClone) }

    private func request(
        text: String,
        language: String,
        input: VocelloQwen3SynthesisInput
    ) -> VocelloQwen3SynthesisRequest {
        VocelloQwen3SynthesisRequest(
            generationID: UUID(),
            text: text,
            language: language,
            input: input,
            sampling: samplingConfiguration,
            memory: memoryConfiguration
        )
    }

    func prewarmCustomVoice(
        text: String,
        language: String,
        speaker: String,
        instruct: String?,
        customPrewarmDepth: String? = nil
    ) async throws {
        try await engine.prewarm(
            request: request(
                text: text,
                language: language,
                input: .customVoice(speakerID: speaker, deliveryInstruction: instruct)
            ),
            customDepth: customPrewarmDepth
        )
    }

    func prewarmVoiceDesign(
        text: String,
        language: String,
        voiceDescription: String
    ) async throws {
        try await engine.prewarm(
            request: request(
                text: text,
                language: language,
                input: .voiceDesign(description: voiceDescription)
            )
        )
    }

    func makeCloneHandle(
        refAudio: [Float],
        refText: String?,
        xVectorOnlyMode: Bool,
        conditioningDigest: String
    ) async throws -> VocelloQwen3CloneHandle {
        try await engine.makeCloneHandle(
            referenceSamples: refAudio,
            referenceText: refText,
            xVectorOnlyMode: xVectorOnlyMode,
            conditioningDigest: conditioningDigest
        )
    }

    func prewarmVoiceClone(
        text: String,
        language: String,
        cloneHandle: VocelloQwen3CloneHandle
    ) async throws {
        try await engine.prewarm(
            request: request(
                text: text,
                language: language,
                input: .voiceClone(referenceID: cloneHandle.conditioningDigest)
            ),
            cloneHandle: cloneHandle
        )
    }

    /// Bounded actor-owned priming generation; audio never crosses the
    /// boundary. Returns the produced frame count for the host's non-empty
    /// guard.
    func primeVoiceClone(
        text: String,
        language: String,
        cloneHandle: VocelloQwen3CloneHandle
    ) async throws -> Int {
        try await engine.prime(
            request: request(
                text: text,
                language: language,
                input: .voiceClone(referenceID: cloneHandle.conditioningDigest)
            ),
            cloneHandle: cloneHandle
        ).audioFrameCount
    }
}
