//
//  GenerationTypes.swift
//  MLXAudioCore
//
//  Common types for audio generation shared across TTS, STT, and STS models.
//

import Foundation
import MLX

// MARK: - Generation Info

/// Information about the audio generation process.
public struct AudioGenerationInfo: Sendable {
    public let promptTokenCount: Int
    public let generationTokenCount: Int
    public let prefillTime: TimeInterval
    public let generateTime: TimeInterval
    public let tokensPerSecond: Double
    public let peakMemoryUsage: Double

    public init(
        promptTokenCount: Int,
        generationTokenCount: Int,
        prefillTime: TimeInterval,
        generateTime: TimeInterval,
        tokensPerSecond: Double,
        peakMemoryUsage: Double
    ) {
        self.promptTokenCount = promptTokenCount
        self.generationTokenCount = generationTokenCount
        self.prefillTime = prefillTime
        self.generateTime = generateTime
        self.tokensPerSecond = tokensPerSecond
        self.peakMemoryUsage = peakMemoryUsage
    }

    public var summary: String {
        """
        Prompt:     \(promptTokenCount) tokens, \(String(format: "%.2f", Double(promptTokenCount) / max(prefillTime, 0.001))) tokens/s, \(String(format: "%.3f", prefillTime))s
        Generation: \(generationTokenCount) tokens, \(String(format: "%.2f", tokensPerSecond)) tokens/s, \(String(format: "%.3f", generateTime))s
        Peak Memory Usage: \(peakMemoryUsage) GB
        """
    }
}

// MARK: - Per-chunk sub-stage timings (engine probe Phase 1)

/// Diagnostic snapshot of the talker KV cache at a chunk boundary.
/// Lives in MLXAudioCore so `ChunkSubstageTimings` (which crosses the
/// `AudioGeneration` public enum) can carry it without adding a
/// Qwen3-specific dependency to unrelated consumers.
public struct KVCacheDiagnostics: Hashable, Codable, Sendable {
    public let cacheType: String
    public let effectiveSeqLength: Int
    public let layerCount: Int
    /// Attention head count (for architecture identification).
    public let headCount: Int
    /// Key/value head count — the actual tensor count used for the K/V cache.
    public let kvHeadCount: Int
    public let headDim: Int
    /// Assumed element size in bytes. This is a coarse estimate: quantized caches
    /// use fewer bits and rotating-window caches cap `effectiveSeqLength`, so the
    /// real footprint can differ. The value is intended for trend/regression
    /// analysis, not as ground-truth bytes allocated.
    public let dtypeBytes: Int
    public let estimatedFootprintMB: Double

    public init(
        cacheType: String,
        effectiveSeqLength: Int,
        layerCount: Int,
        headCount: Int,
        kvHeadCount: Int,
        headDim: Int,
        dtypeBytes: Int,
        estimatedFootprintMB: Double
    ) {
        self.cacheType = cacheType
        self.effectiveSeqLength = effectiveSeqLength
        self.layerCount = layerCount
        self.headCount = headCount
        self.kvHeadCount = kvHeadCount
        self.headDim = headDim
        self.dtypeBytes = dtypeBytes
        self.estimatedFootprintMB = estimatedFootprintMB
    }

    /// Backward-compatible decoding: rows written by the first Phase-2a commit
    /// only carried `headCount`. Fall back to `headCount` for the KV-head count
    /// so older JSONL still decodes (the footprint estimate was already using
    /// the attention-head count in that version, so the fallback is exact).
    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        self.cacheType = try container.decode(String.self, forKey: .cacheType)
        self.effectiveSeqLength = try container.decode(Int.self, forKey: .effectiveSeqLength)
        self.layerCount = try container.decode(Int.self, forKey: .layerCount)
        self.headCount = try container.decode(Int.self, forKey: .headCount)
        self.kvHeadCount = try container.decodeIfPresent(Int.self, forKey: .kvHeadCount) ?? self.headCount
        self.headDim = try container.decode(Int.self, forKey: .headDim)
        self.dtypeBytes = try container.decode(Int.self, forKey: .dtypeBytes)
        self.estimatedFootprintMB = try container.decode(Double.self, forKey: .estimatedFootprintMB)
    }
}

/// Per-frame Mimi audio-decoder step timings. Each `streamingStep` call
/// produces one set; the engine aggregates them across a chunk boundary and
/// forwards them with `ChunkSubstageTimings` so the telemetry ledger can
/// localize decoder spikes to quantizer / transformer / upsampler / conv.
public struct MimiDecoderStepTimings: Sendable, Hashable, Codable {
    public let quantizerMS: Double
    public let preConvMS: Double
    public let preTransformerMS: Double
    public let upsampleMS: Double
    public let initConvMS: Double
    public let decoderBlocksMS: Double
    public let outputSnakeMS: Double
    public let outputConvMS: Double
    public let totalMS: Double

    public init(
        quantizerMS: Double = 0,
        preConvMS: Double = 0,
        preTransformerMS: Double = 0,
        upsampleMS: Double = 0,
        initConvMS: Double = 0,
        decoderBlocksMS: Double = 0,
        outputSnakeMS: Double = 0,
        outputConvMS: Double = 0,
        totalMS: Double = 0
    ) {
        self.quantizerMS = quantizerMS
        self.preConvMS = preConvMS
        self.preTransformerMS = preTransformerMS
        self.upsampleMS = upsampleMS
        self.initConvMS = initConvMS
        self.decoderBlocksMS = decoderBlocksMS
        self.outputSnakeMS = outputSnakeMS
        self.outputConvMS = outputConvMS
        self.totalMS = totalMS
    }

    /// Add two timing snapshots (useful for aggregating multiple decoder
    /// steps inside one emitted chunk).
    public func adding(_ other: MimiDecoderStepTimings) -> MimiDecoderStepTimings {
        MimiDecoderStepTimings(
            quantizerMS: quantizerMS + other.quantizerMS,
            preConvMS: preConvMS + other.preConvMS,
            preTransformerMS: preTransformerMS + other.preTransformerMS,
            upsampleMS: upsampleMS + other.upsampleMS,
            initConvMS: initConvMS + other.initConvMS,
            decoderBlocksMS: decoderBlocksMS + other.decoderBlocksMS,
            outputSnakeMS: outputSnakeMS + other.outputSnakeMS,
            outputConvMS: outputConvMS + other.outputConvMS,
            totalMS: totalMS + other.totalMS
        )
    }

    /// Subtract `other` from this snapshot (useful for computing per-chunk
    /// deltas from cumulative accumulators).
    public func subtracting(_ other: MimiDecoderStepTimings) -> MimiDecoderStepTimings {
        MimiDecoderStepTimings(
            quantizerMS: quantizerMS - other.quantizerMS,
            preConvMS: preConvMS - other.preConvMS,
            preTransformerMS: preTransformerMS - other.preTransformerMS,
            upsampleMS: upsampleMS - other.upsampleMS,
            initConvMS: initConvMS - other.initConvMS,
            decoderBlocksMS: decoderBlocksMS - other.decoderBlocksMS,
            outputSnakeMS: outputSnakeMS - other.outputSnakeMS,
            outputConvMS: outputConvMS - other.outputConvMS,
            totalMS: totalMS - other.totalMS
        )
    }
}

/// Wall-clock breakdown of the inference work that produced ONE audio
/// chunk during streaming. Emitted by `Qwen3TTS` immediately before
/// each `.audio(...)` chunk event so consumers can correlate each
/// audio packet with the engine work that produced it.
///
/// All values are millisecond deltas from the previous chunk's emit
/// boundary (or from generation start for the first chunk).
///
/// Lives in MLXAudioCore so it can be referenced by the public
/// `AudioGeneration` enum without forcing a Qwen3-specific dependency
/// onto unrelated consumers.
public struct ChunkSubstageTimings: Sendable, Hashable {
    /// LLM forward pass time (`talker(...)` per token) for this chunk.
    public let talkerForwardMS: Double
    /// Multi-codebook code-predictor loop time for this chunk.
    public let codePredictorMS: Double
    /// Streaming audio decoder time (codec → waveform) for this chunk.
    public let audioDecoderMS: Double
    /// Time spent in `eval(...)` after each forward step (deferred GPU
    /// dispatch flushing). Phase 2a addition — Phase 1's three stages
    /// summed to only 18-26 % of `inferMS`; this and the next two
    /// fields chase the missing 74-82 %.
    public let streamStepEvalMS: Double
    /// Phase 2a split of `streamStepEvalMS`: wall time from when the
    /// eval work was enqueued until it was issued to the GPU. In the
    /// current synchronous eval path this equals `streamStepEvalMS`;
    /// future async instrumentation will populate `streamStepEvalWaitMS`
    /// separately.
    public let streamStepEvalEnqueueMS: Double
    /// Phase 2a split of `streamStepEvalMS`: wall time spent waiting for
    /// the GPU command buffer to drain. Currently 0 because the eval
    /// path is synchronous; reserved for future async instrumentation.
    public let streamStepEvalWaitMS: Double
    /// Time spent reading the EOS (end-of-speech) flag each forward
    /// step. Lives inside the per-token loop alongside the talker
    /// forward + code predictor; broken out separately because EOS
    /// reads can be a non-trivial GPU sync.
    public let streamStepEOSReadMS: Double
    /// Time spent in `eval(audioChunk)` immediately after each
    /// streaming decoder run — flushes the decoded waveform onto the
    /// CPU side so the chunk can be yielded. Distinct from the
    /// `audioDecoderMS` measurement which times the decoder kernel.
    public let audioChunkEvalMS: Double
    /// Snapshot of the talker KV cache at this chunk boundary (shape,
    /// effective sequence length, estimated footprint). nil when not
    /// available or when telemetry is gated off.
    public let kvCacheDiagnostics: KVCacheDiagnostics?
    /// Phase 4 addition: per-frame Mimi decoder step breakdown for this
    /// chunk (aggregated if the chunk spanned multiple decoder steps).
    /// nil when the decoder does not support step-level timings or when
    /// telemetry is gated off.
    public let mimiDecoderBreakdownMS: MimiDecoderStepTimings?
    /// Exact codec-frame range decoded into this chunk's PCM. Optional so
    /// legacy timing emitters remain valid; both bounds are present or both nil.
    public let codecStartFrame: UInt64?
    public let codecEndFrameExclusive: UInt64?

    public init(
        talkerForwardMS: Double,
        codePredictorMS: Double,
        audioDecoderMS: Double,
        streamStepEvalMS: Double = 0,
        streamStepEvalEnqueueMS: Double = 0,
        streamStepEvalWaitMS: Double = 0,
        streamStepEOSReadMS: Double = 0,
        audioChunkEvalMS: Double = 0,
        kvCacheDiagnostics: KVCacheDiagnostics? = nil,
        mimiDecoderBreakdownMS: MimiDecoderStepTimings? = nil,
        codecStartFrame: UInt64? = nil,
        codecEndFrameExclusive: UInt64? = nil
    ) {
        self.talkerForwardMS = talkerForwardMS
        self.codePredictorMS = codePredictorMS
        self.audioDecoderMS = audioDecoderMS
        self.streamStepEvalMS = streamStepEvalMS
        self.streamStepEvalEnqueueMS = streamStepEvalEnqueueMS
        self.streamStepEvalWaitMS = streamStepEvalWaitMS
        self.streamStepEOSReadMS = streamStepEOSReadMS
        self.audioChunkEvalMS = audioChunkEvalMS
        self.kvCacheDiagnostics = kvCacheDiagnostics
        self.mimiDecoderBreakdownMS = mimiDecoderBreakdownMS
        self.codecStartFrame = codecStartFrame
        self.codecEndFrameExclusive = codecEndFrameExclusive
    }
}

// MARK: - Generation Events

/// Events emitted during audio generation.
public enum AudioGeneration: Sendable {
    /// A generated token ID
    case token(Int)
    /// Generation statistics
    case info(AudioGenerationInfo)
    /// Final generated audio
    case audio([Float])

    /// Evaluate and copy on the producer before publishing across a task boundary.
    /// The event retains only PCM values, never the tensor or its lazy graph.
    public static func audio(materializing waveform: MLXArray) -> Self {
        .audio(waveform.asArray(Float.self))
    }
    /// Per-chunk sub-stage timing breakdown. Always emitted
    /// immediately before the corresponding `.audio(...)` chunk so
    /// consumers can stash it and bind to the next audio event.
    /// Backward compatibility: legacy consumers can ignore via a
    /// `@unknown default` branch — adding a new case is non-breaking.
    case chunkTimings(ChunkSubstageTimings)
}

// MARK: - Generation Errors

/// Errors that can occur during audio generation.
public enum AudioGenerationError: Error, LocalizedError {
    case modelNotInitialized(String)
    case generationFailed(String)
    case invalidInput(String)
    case audioDecodingFailed(String)
    case audioEncodingFailed(String)

    public var errorDescription: String? {
        switch self {
        case .modelNotInitialized(let message):
            return "Model not initialized: \(message)"
        case .generationFailed(let message):
            return "Generation failed: \(message)"
        case .invalidInput(let message):
            return "Invalid input: \(message)"
        case .audioDecodingFailed(let message):
            return "Audio decoding failed: \(message)"
        case .audioEncodingFailed(let message):
            return "Audio encoding failed: \(message)"
        }
    }
}

// MARK: - Token Configuration Protocol

/// Protocol for model-specific token configuration.
public protocol AudioTokenConfiguration {
    /// Token ID for start of speech
    var startOfSpeech: Int { get }
    /// Token ID for end of speech
    var endOfSpeech: Int { get }
    /// Token ID for end of text
    var endOfText: Int { get }
    /// Offset added to audio token indices
    var audioTokensStart: Int { get }
    /// Pad token ID
    var padTokenId: Int { get }
}

// MARK: - Generation Parameters

/// Parameters for controlling audio generation.
public struct AudioGenerateParameters: Sendable {
    public let maxTokens: Int
    public let temperature: Float
    public let topP: Float
    public let repetitionPenalty: Float
    public let repetitionContextSize: Int

    public init(
        maxTokens: Int = 1200,
        temperature: Float = 0.6,
        topP: Float = 0.8,
        repetitionPenalty: Float = 1.3,
        repetitionContextSize: Int = 20
    ) {
        self.maxTokens = maxTokens
        self.temperature = temperature
        self.topP = topP
        self.repetitionPenalty = repetitionPenalty
        self.repetitionContextSize = repetitionContextSize
    }
}
