@preconcurrency import MLX
import MLXAudioCore
@preconcurrency import MLXLMCommon
#if canImport(AVFoundation)
@preconcurrency import AVFoundation
#endif

/// One independently configurable Qwen3 categorical-sampling stage.
///
/// The talker and subtalker deliberately use separate values. In particular,
/// repetition penalty belongs to the talker policy only and is never inherited
/// by the code predictor.
public struct Qwen3SamplingStage: Hashable, Sendable {
    public let temperature: Float
    public let topP: Float
    public let topK: Int
    public let minP: Float

    public init(temperature: Float, topP: Float, topK: Int, minP: Float) {
        self.temperature = temperature
        self.topP = topP
        self.topK = topK
        self.minP = minP
    }
}

/// Fully resolved request-local Qwen3 sampling policy.
///
/// Version 2 is the first policy that owns an explicit MLX random state. The
/// effective seed is always present, including for requests where the product
/// selected a random seed, so generation evidence can reproduce the take.
public struct Qwen3RequestSamplingPolicy: Hashable, Sendable {
    public static let currentAlgorithmVersion = 2

    public let algorithmVersion: Int
    public let effectiveSeed: UInt64
    public let talker: Qwen3SamplingStage
    public let subtalker: Qwen3SamplingStage
    public let repetitionPenalty: Float
    public let maximumCodecTokens: Int

    public init(
        algorithmVersion: Int = Self.currentAlgorithmVersion,
        effectiveSeed: UInt64,
        talker: Qwen3SamplingStage,
        subtalker: Qwen3SamplingStage,
        repetitionPenalty: Float,
        maximumCodecTokens: Int
    ) {
        self.algorithmVersion = algorithmVersion
        self.effectiveSeed = effectiveSeed
        self.talker = talker
        self.subtalker = subtalker
        self.repetitionPenalty = repetitionPenalty
        self.maximumCodecTokens = maximumCodecTokens
    }

    /// Run every random operation in `body` against a fresh request-local MLX
    /// state. The task-local scope is inherited by the synchronous Qwen token
    /// loop while leaving `MLXRandom.globalState` untouched.
    func runWithRandomState<T>(_ body: () throws -> T) rethrows -> T {
        try withRandomState(MLXRandom.RandomState(seed: effectiveSeed), body: body)
    }

    /// Async counterpart used by the actor-owned suspending producer. MLX's
    /// task-local random state remains installed across suspension, so every
    /// categorical draw in one request continues to use the same private state
    /// without mutating `MLXRandom.globalState`.
    func runWithRandomState<T>(_ body: () async throws -> T) async rethrows -> T {
        try await withRandomState(
            MLXRandom.RandomState(seed: effectiveSeed),
            body: body
        )
    }

    /// Caller-isolated variant used by the suspending producer. The body is
    /// Sendable because MLX's pinned task-local helper is not actor-aware; the
    /// body immediately re-enters the explicit caller isolation carried by the
    /// Qwen loop before touching any model state.
    func runWithRandomState<T: Sendable>(
        isolation: isolated (any Actor)?,
        _ body: @Sendable () async throws -> T
    ) async rethrows -> T {
        _ = isolation
        return try await withRandomState(
            MLXRandom.RandomState(seed: effectiveSeed),
            body: body
        )
    }

    static func official(
        _ parameters: GenerateParameters,
        effectiveSeed: UInt64
    ) -> Self {
        let stage = Qwen3SamplingStage(
            temperature: parameters.temperature,
            topP: parameters.topP,
            topK: 50,
            minP: 0
        )
        return Self(
            effectiveSeed: effectiveSeed,
            talker: stage,
            subtalker: stage,
            repetitionPenalty: parameters.repetitionPenalty ?? 1.05,
            maximumCodecTokens: parameters.maxTokens ?? 4_096
        )
    }
}

/// Fully resolved request-local Qwen3 memory policy.
///
/// These values used to be read from mutable process-wide state in the token
/// loop. Keeping them in an immutable value prevents one request from changing
/// the cache cadence or KV retention of another request while preserving the
/// existing defaults and chunk schedule.
public struct Qwen3RequestMemoryPolicy: Hashable, Sendable {
    public static let compatibilityDefault = Self(
        clearCacheOnStreamChunkEmit: true,
        tokenMemoryClearCadence: 50,
        talkerKVGeneratedWindow: nil
    )

    public let clearCacheOnStreamChunkEmit: Bool
    public let tokenMemoryClearCadence: Int
    public let talkerKVGeneratedWindow: Int?

    public init(
        clearCacheOnStreamChunkEmit: Bool,
        tokenMemoryClearCadence: Int,
        talkerKVGeneratedWindow: Int?
    ) {
        precondition(tokenMemoryClearCadence > 0, "Memory clear cadence must be positive.")
        precondition(
            talkerKVGeneratedWindow.map { $0 > 0 } ?? true,
            "Talker KV generated window must be positive when present."
        )
        self.clearCacheOnStreamChunkEmit = clearCacheOnStreamChunkEmit
        self.tokenMemoryClearCadence = tokenMemoryClearCadence
        self.talkerKVGeneratedWindow = talkerKVGeneratedWindow
    }
}

public protocol SpeechGenerationModel: AnyObject {
    var sampleRate: Int { get }
    var defaultGenerationParameters: GenerateParameters { get }

    func prepareForGeneration(
        text: String,
        voice: String?,
        refAudio: MLXArray?,
        refText: String?,
        language: String?,
        generationParameters: GenerateParameters
    ) async throws

    func generate(
        text: String,
        voice: String?,
        refAudio: MLXArray?,
        refText: String?,
        language: String?,
        generationParameters: GenerateParameters
    ) async throws -> MLXArray

    func generateStream(
        text: String,
        voice: String?,
        refAudio: MLXArray?,
        refText: String?,
        language: String?,
        generationParameters: GenerateParameters
    ) -> AsyncThrowingStream<AudioGeneration, Error>

    func generateStream(
        text: String,
        voice: String?,
        refAudio: MLXArray?,
        refText: String?,
        language: String?,
        generationParameters: GenerateParameters,
        streamingInterval: Double
    ) -> AsyncThrowingStream<AudioGeneration, Error>
}

public enum AudioGenerationFinishReason: String, Sendable {
    case eos
    case maxTokens = "max_tokens"
    case cancelled
    case failed
}

public struct AudioGenerationCompletion: Sendable {
    public let audio: MLXArray
    public let info: AudioGenerationInfo?
    public let finishReason: AudioGenerationFinishReason

    public init(
        audio: MLXArray,
        info: AudioGenerationInfo?,
        finishReason: AudioGenerationFinishReason
    ) {
        self.audio = audio
        self.info = info
        self.finishReason = finishReason
    }
}

/// Materialized, task-safe events emitted by the suspending Qwen3 producer.
///
/// Unlike `AudioGeneration`, this boundary never contains `MLXArray`. The
/// Qwen token/decode task evaluates and copies each waveform to `[Float]`
/// before awaiting the sink, keeping lazy MLX graphs inside their owning task.
public enum Qwen3MaterializedGenerationEvent: Sendable {
    /// Input preparation and immutable policy resolution have completed. This
    /// event is emitted from the caller-isolated model loop, never speculatively
    /// by a host before the model has actually reached the prepared boundary.
    case prepared
    case token(Int)
    /// One fully materialized codec group for diagnostics-only replay.
    /// The producer emits this only when the request explicitly enables the
    /// bounded trace; normal generation performs no additional materialization.
    case codecFrame([Int32])
    case info(AudioGenerationInfo)
    case audio([Float])
    case chunkTimings(ChunkSubstageTimings)
}

public typealias Qwen3MaterializedGenerationSink = @Sendable (
    Qwen3MaterializedGenerationEvent
) async throws -> Void

public typealias Qwen3CodecTraceSink = @Sendable ([Int32]) async throws -> Void

/// One contiguous codec-frame range observed at a production streaming
/// decoder call. Diagnostics replay the captured codes with these exact
/// boundaries instead of guessing the chunk schedule.
public struct Qwen3CodecFrameRange: Codable, Hashable, Sendable {
    public let start: Int
    public let endExclusive: Int

    public init(start: Int, endExclusive: Int) {
        self.start = start
        self.endExclusive = endExclusive
    }
}

/// Materialized PCM from the same captured codec sequence decoded through the
/// production incremental schedule and the quality-first full-sequence path.
public struct Qwen3CodecReplayResult: Sendable {
    public let incrementalAudio: [Float]
    public let fullAudio: [Float]
    public let sampleRate: Int

    public init(incrementalAudio: [Float], fullAudio: [Float], sampleRate: Int) {
        self.incrementalAudio = incrementalAudio
        self.fullAudio = fullAudio
        self.sampleRate = sampleRate
    }
}

/// Diagnostics-only codec replay surface. Implementations must reset mutable
/// decoder state before and after each arm and remain inside the loaded-model
/// isolation domain.
public protocol Qwen3CodecTraceReplayModel: AnyObject {
    func replayCodecTrace(
        frames: [[Int32]],
        incrementalRanges: [Qwen3CodecFrameRange]
    ) throws -> Qwen3CodecReplayResult
}

/// Async, backpressure-capable Qwen3 production surface.
///
/// The legacy stream protocol remains source-compatible for shipping callers
/// during staged cutover. The converged engine uses this interface so its
/// frame-bounded channel can suspend the actual token/decode producer rather
/// than a downstream `AsyncThrowingStream` proxy.
public protocol Qwen3SuspendingSpeechGenerationModel: AnyObject {
    func produceCustomVoice(
        text: String,
        language: String,
        speaker: String,
        instruct: String?,
        generationParameters: GenerateParameters,
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
        isolation: isolated (any Actor)?
    ) async throws -> AudioGenerationFinishReason

    func produceVoiceDesign(
        text: String,
        language: String,
        voiceDescription: String,
        generationParameters: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        streamingInterval: Double,
        streamStepEvalPolicy: String?,
        generationSpeedProfile: String?,
        memoryClearCadence: Int?,
        enableChunkTimings: Bool,
        enableCodecTrace: Bool,
        sink: @escaping Qwen3MaterializedGenerationSink,
        isolation: isolated (any Actor)?
    ) async throws -> AudioGenerationFinishReason

    func produceVoiceClone(
        text: String,
        language: String,
        voiceClonePrompt: Qwen3TTSVoiceClonePrompt,
        generationParameters: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        streamingInterval: Double,
        streamStepEvalPolicy: String?,
        generationSpeedProfile: String?,
        memoryClearCadence: Int?,
        enableChunkTimings: Bool,
        enableCodecTrace: Bool,
        sink: @escaping Qwen3MaterializedGenerationSink,
        isolation: isolated (any Actor)?
    ) async throws -> AudioGenerationFinishReason
}

public protocol Qwen3OptimizedSpeechGenerationModel: AnyObject {
    func prepareCustomVoice(
        text: String,
        language: String,
        speaker: String,
        instruct: String?,
        generationParameters: GenerateParameters,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        isolation: isolated (any Actor)?
    ) async throws

    func generateCustomVoiceStream(
        text: String,
        language: String,
        speaker: String,
        instruct: String?,
        generationParameters: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        streamingInterval: Double,
        customVoiceProfile: String?,
        streamStepEvalPolicy: String?,
        generationSpeedProfile: String?,
        memoryClearCadence: Int?,
        enableChunkTimings: Bool
    ) -> AsyncThrowingStream<AudioGeneration, Error>

    func generateCustomVoice(
        text: String,
        language: String,
        speaker: String,
        instruct: String?,
        generationParameters: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy
    ) async throws -> AudioGenerationCompletion

    func prepareVoiceDesign(
        text: String,
        language: String,
        voiceDescription: String,
        generationParameters: GenerateParameters,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        isolation: isolated (any Actor)?
    ) async throws

    func generateVoiceDesignStream(
        text: String,
        language: String,
        voiceDescription: String,
        generationParameters: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        streamingInterval: Double,
        streamStepEvalPolicy: String?,
        generationSpeedProfile: String?,
        memoryClearCadence: Int?,
        enableChunkTimings: Bool
    ) -> AsyncThrowingStream<AudioGeneration, Error>

    func generateVoiceDesign(
        text: String,
        language: String,
        voiceDescription: String,
        generationParameters: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy
    ) async throws -> AudioGenerationCompletion

    func createVoiceClonePrompt(
        refAudio: MLXArray,
        refText: String?,
        xVectorOnlyMode: Bool
    ) throws -> Qwen3TTSVoiceClonePrompt

    func prepareVoiceClone(
        text: String,
        language: String,
        voiceClonePrompt: Qwen3TTSVoiceClonePrompt,
        generationParameters: GenerateParameters,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        isolation: isolated (any Actor)?
    ) async throws

    func generateVoiceCloneStream(
        text: String,
        language: String,
        voiceClonePrompt: Qwen3TTSVoiceClonePrompt,
        generationParameters: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        streamingInterval: Double,
        streamStepEvalPolicy: String?,
        generationSpeedProfile: String?,
        memoryClearCadence: Int?,
        enableChunkTimings: Bool
    ) -> AsyncThrowingStream<AudioGeneration, Error>

    func generateVoiceClone(
        text: String,
        language: String,
        voiceClonePrompt: Qwen3TTSVoiceClonePrompt,
        generationParameters: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy
    ) async throws -> AudioGenerationCompletion
}

/// Quality-first generation with an exact producer-prepared boundary.
///
/// The callback is separate from the materialized streaming sink so using it
/// does not switch the Qwen implementation into streaming text conditioning
/// or chunked decoder behavior.
public protocol Qwen3PreparedQualityGenerationModel: AnyObject {
    func generateCustomVoiceQualityFirst(
        text: String,
        language: String,
        speaker: String,
        instruct: String?,
        generationParameters: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        onPrepared: @escaping @Sendable () async throws -> Void,
        codecTraceSink: Qwen3CodecTraceSink?,
        isolation: isolated (any Actor)?
    ) async throws -> AudioGenerationCompletion

    func generateVoiceDesignQualityFirst(
        text: String,
        language: String,
        voiceDescription: String,
        generationParameters: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        onPrepared: @escaping @Sendable () async throws -> Void,
        codecTraceSink: Qwen3CodecTraceSink?,
        isolation: isolated (any Actor)?
    ) async throws -> AudioGenerationCompletion

    func generateVoiceCloneQualityFirst(
        text: String,
        language: String,
        voiceClonePrompt: Qwen3TTSVoiceClonePrompt,
        generationParameters: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        onPrepared: @escaping @Sendable () async throws -> Void,
        codecTraceSink: Qwen3CodecTraceSink?,
        isolation: isolated (any Actor)?
    ) async throws -> AudioGenerationCompletion
}

public protocol Qwen3CustomVoicePrewarmDepthControlling: AnyObject {
    func prepareCustomVoice(
        text: String,
        language: String,
        speaker: String,
        instruct: String?,
        generationParameters: GenerateParameters,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        customPrewarmDepth: String?,
        isolation: isolated (any Actor)?
    ) async throws
}

public extension SpeechGenerationModel {
    func prepareForGeneration(
        text: String,
        voice: String?,
        refAudio: MLXArray?,
        refText: String?,
        language: String?,
        generationParameters: GenerateParameters
    ) async throws {
        let warmupMaxTokens = min(generationParameters.maxTokens ?? 1, 1)
        _ = try await generate(
            text: text,
            voice: voice,
            refAudio: refAudio,
            refText: refText,
            language: language,
            generationParameters: GenerateParameters(
                maxTokens: warmupMaxTokens,
                temperature: 0,
                topP: 1.0,
                repetitionPenalty: 1.0
            )
        )
    }

    func generate(
        text: String,
        voice: String?,
        refAudio: MLXArray?,
        refText: String?,
        language: String?,
        generationParameters: GenerateParameters? = nil
    ) async throws -> MLXArray {
        try await generate(text: text, voice: voice, refAudio: refAudio, refText: refText, language: language, generationParameters: generationParameters ?? defaultGenerationParameters)
    }

    func generateSamplesStream(
        text: String,
        voice: String?,
        refAudio: MLXArray?,
        refText: String?,
        language: String?,
        generationParameters: GenerateParameters? = nil,
        streamingInterval: Double = 2.0
    ) -> AsyncThrowingStream<[Float], Error> {
        let stream = generateStream(
            text: text,
            voice: voice,
            refAudio: refAudio,
            refText: refText,
            language: language,
            generationParameters: generationParameters ?? defaultGenerationParameters,
            streamingInterval: streamingInterval
        )
        return proxyAudioStream(stream, extract: {
            guard case .audio(let samples) = $0 else { return nil }
            return samples.asArray(Float.self)
        })
    }

#if canImport(AVFoundation)
    @MainActor
    func generatePCMBufferStream(
        text: String,
        voice: String?,
        refAudio: MLXArray?,
        refText: String?,
        language: String?,
        generationParameters: GenerateParameters? = nil,
        streamingInterval: Double = 2.0
    ) -> AsyncThrowingStream<AVAudioPCMBuffer, Error> {
        let sampleStream = generateSamplesStream(
            text: text,
            voice: voice,
            refAudio: refAudio,
            refText: refText,
            language: language,
            generationParameters: generationParameters,
            streamingInterval: streamingInterval
        )

        let (stream, continuation) = AsyncThrowingStream<AVAudioPCMBuffer, Error>.makeStream()
        let sampleRate = self.sampleRate

        let producerTask = Task { @MainActor in
            do {
                for try await samples in sampleStream {
                    try Task.checkCancellation()
                    let buffer = try makePCMBuffer(samples: samples, sampleRate: sampleRate)
                    try Task.checkCancellation()
                    continuation.yield(buffer)
                }
                continuation.finish()
            } catch is CancellationError {
                continuation.finish(throwing: CancellationError())
            } catch {
                continuation.finish(throwing: error)
            }
        }
        continuation.onTermination = { @Sendable _ in producerTask.cancel() }

        return stream
    }
#endif

    func generateStream(
        text: String,
        voice: String?,
        refAudio: MLXArray?,
        refText: String?,
        language: String?,
        generationParameters: GenerateParameters,
        streamingInterval: Double = 2.0
    ) -> AsyncThrowingStream<AudioGeneration, Error> {
        _ = streamingInterval
        return generateStream(
            text: text,
            voice: voice,
            refAudio: refAudio,
            refText: refText,
            language: language,
            generationParameters: generationParameters
        )
    }
}

private func proxyAudioStream<T: Sendable, U: Sendable>(
    _ upstream: AsyncThrowingStream<T, Error>,
    extract: @Sendable @escaping (T) -> U?
) -> AsyncThrowingStream<U, Error> {
    AsyncThrowingStream<U, Error> { continuation in
        let task = Task { @Sendable in
            do {
                for try await value in upstream {
                    guard let extracted = extract(value) else { continue }
                    continuation.yield(extracted)
                }
                continuation.finish()
            } catch is CancellationError {
                continuation.finish(throwing: CancellationError())
            } catch {
                continuation.finish(throwing: error)
            }
        }
        continuation.onTermination = { @Sendable _ in task.cancel() }
    }
}

#if canImport(AVFoundation)
@MainActor
private func makePCMBuffer(samples: [Float], sampleRate: Int) throws -> AVAudioPCMBuffer {
    let frameCount = AVAudioFrameCount(samples.count)
    guard
        let format = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: Double(sampleRate),
            channels: 1,
            interleaved: false
        ),
        let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frameCount),
        let channel = buffer.floatChannelData?[0]
    else {
        throw AudioGenerationError.audioDecodingFailed("Failed to create AVAudioPCMBuffer")
    }

    buffer.frameLength = frameCount
    for i in 0 ..< samples.count {
        channel[i] = samples[i]
    }
    return buffer
}
#endif
