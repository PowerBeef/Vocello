import Foundation
import QwenVoiceBackendCore
import VocelloQwen3Core

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
    /// Audio QC controlled generation GEN-NOEOS (audit 2026-09-25 section 5.2):
    /// hold back the talker's first sampled EOS for this many codec frames. It
    /// exists only for controlled-generation QC experiments under
    /// `vocello batch`; 0 arms the hold at zero frames (the sham).
    static let envEOSSuppressionFrames: Int? = eosSuppressionFrames(
        RuntimeDebugGate.value(for: "QWENVOICE_TALKER_EOS_SUPPRESSION_FRAMES")
    )

    /// RF-14 reference-parity arms (`VocelloQwen3ReferenceParity`). Production
    /// samples from float32 logits (D3, maintainer decision 2026-10-13) and
    /// filters the talker's EOS like any token (D2, RF-18 follow-up screen,
    /// 2026-10-20): `QWENVOICE_SAMPLER_FLOAT32=off` reverts to the model's own
    /// precision and `QWENVOICE_TALKER_FILTER_EOS=off` re-inserts EOS after the
    /// filters. D1 `QWENVOICE_FULL_TEXT_CONDITIONING` stays off unless set `on`.
    static let envReferenceParity: VocelloQwen3ReferenceParity? = referenceParity(
        fullTextConditioning: RuntimeDebugGate.value(for: "QWENVOICE_FULL_TEXT_CONDITIONING"),
        filtersEOS: RuntimeDebugGate.value(for: "QWENVOICE_TALKER_FILTER_EOS"),
        float32Sampling: RuntimeDebugGate.value(for: "QWENVOICE_SAMPLER_FLOAT32")
    )

    /// The arms the knobs select, or nil (the production path) when they leave
    /// production unchanged. A knob set on or off overrides its arm; unset or
    /// unrecognized, the arm keeps its production value.
    static func referenceParity(
        fullTextConditioning: String?,
        filtersEOS: String?,
        float32Sampling: String?
    ) -> VocelloQwen3ReferenceParity? {
        let production = VocelloQwen3ReferenceParity.production
        let parity = VocelloQwen3ReferenceParity(
            fullTextConditioning: knob(fullTextConditioning, else: production.fullTextConditioning),
            filtersEOS: knob(filtersEOS, else: production.filtersEOS),
            float32Sampling: knob(float32Sampling, else: production.float32Sampling)
        )
        return parity == production ? nil : parity
    }

    private static func knob(_ raw: String?, else productionValue: Bool) -> Bool {
        switch raw?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
        case "1", "true", "on", "yes": true
        case "0", "false", "off", "no": false
        default: productionValue
        }
    }

    /// A whole number of codec frames within the facade's bound; anything else
    /// leaves the hold unset (the production path), so a take whose engine row
    /// does not record the hold was not held.
    static func eosSuppressionFrames(_ raw: String?) -> Int? {
        guard let raw,
              let value = Int(raw.trimmingCharacters(in: .whitespacesAndNewlines)),
              (0 ... VocelloQwen3SamplingConfiguration.maximumEOSSuppressionFrames).contains(value) else {
            return nil
        }
        return value
    }

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
        // The subtalker keeps the reference's own sampling (0.9, top-p 1.0, top-k
        // 50) whatever the variation, which shapes only the talker. Following the
        // talker down under Balanced or Consistent was the divergence ER-05 tracked
        // (model research, item 7): the RF-18 follow-up screen's pre-registered C1
        // arm cut Consistent's failed long-form projects from 9 to 2 of 56 with no
        // new failure class (2026-10-17, adopted with D2 on 2026-10-20). Expressive
        // is unchanged.
        let subtalker = VocelloQwen3SamplingStage(
            temperature: envSubtalkerTemperature ?? official.temperature,
            topP: envSubtalkerTopP ?? official.topP,
            topK: envSubtalkerTopK ?? official.topK,
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
            requestedSeed: requestedSeed,
            eosSuppressionFrames: envEOSSuppressionFrames,
            referenceParity: envReferenceParity
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
    @concurrent static func load(
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

    @concurrent func latestPreparationTimingsMS() async -> [String: Int] {
        await engine.preparationDiagnostics()?.timingsMilliseconds ?? [:]
    }

    @concurrent func latestPreparationBooleanFlags() async -> [String: Bool] {
        await engine.preparationDiagnostics()?.booleanFlags ?? [:]
    }

    @concurrent func latestPreparationStringFlags() async -> [String: String] {
        await engine.preparationDiagnostics()?.stringFlags ?? [:]
    }

    @concurrent func resetPreparationDiagnostics() async {
        await engine.resetPreparationDiagnostics()
    }

    @concurrent func replayCodecTrace(
        frames: [[Int32]],
        incrementalRanges: [StartupReliabilityCodecFrameRange],
        memory: VocelloQwen3MemoryConfiguration
    ) async throws -> StartupReliabilityCodecReplayResult {
        let replay = try await engine.replayCodecTrace(
            frames: frames,
            incrementalRanges: incrementalRanges.map {
                VocelloQwen3CodecFrameRange(start: $0.start, endExclusive: $0.endExclusive)
            },
            memory: memory
        )
        return StartupReliabilityCodecReplayResult(
            incrementalAudio: replay.incrementalAudio,
            fullAudio: replay.fullAudio,
            sampleRate: replay.sampleRate
        )
    }

    @concurrent func codecRoundTrip(
        samples: [Float],
        memory: VocelloQwen3MemoryConfiguration,
        didLoadModel: Bool
    ) async throws -> DiagnosticCodecRoundTripResult {
        let result = try await engine.codecRoundTrip(samples: samples, memory: memory)
        return DiagnosticCodecRoundTripResult(
            codes: result.codes,
            audio: result.audio,
            sampleRate: result.sampleRate,
            didLoadModel: didLoadModel
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

    @concurrent func prewarmCustomVoice(
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

    @concurrent func prewarmVoiceDesign(
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

    @concurrent func makeCloneHandle(
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

    @concurrent func prewarmVoiceClone(
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
    @concurrent func primeVoiceClone(
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
