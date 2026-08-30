import CryptoKit
import Foundation
@preconcurrency import VocelloQwen3Core

public enum GenerationTerminalReason: String, Hashable, Codable, Sendable {
    case eos
    case maxTokens
    case cancelled
    case failed
    case completed
    case superseded
    case unknown

    public init(compatibilityValue: String?) {
        switch compatibilityValue?.replacingOccurrences(of: "_", with: "").lowercased() {
        case "eos": self = .eos
        case "maxtokens": self = .maxTokens
        case "cancelled", "canceled": self = .cancelled
        case "failed": self = .failed
        case "completed": self = .completed
        case "superseded": self = .superseded
        default: self = .unknown
        }
    }
}

public enum GenerationCancellationState: String, Hashable, Codable, Sendable {
    case notRequested
    case requested
    case acknowledged
    case completed
}

public enum GenerationTransportState: String, Hashable, Codable, Sendable {
    case connected
    case interrupted
    case expectedRetirement
    case reconnected
}

public enum BackendTimingKey: String, Hashable, Codable, Sendable {
    case modelLoad
    case prepareGeneration
    case explicitPrewarm
    case cloneConditioning
    case generationStream
    case qualityFirstGeneration
    case tokenLoop
    case talkerForward
    case codePredictor
    case audioDecoder
    case streamStepEval
    case streamStepEOSRead
    case audioChunkEval
    case finalWAVFinish
}

public struct BackendTimingMetric: Hashable, Codable, Sendable {
    public let key: BackendTimingKey
    public let milliseconds: Double

    public init(key: BackendTimingKey, milliseconds: Double) {
        self.key = key
        self.milliseconds = milliseconds
    }
}

public enum BackendCounterKey: String, Hashable, Codable, Sendable {
    case generatedCodes
    case decoderCalls
    case chunkCount
    case pendingCodePeak
}

public struct BackendCounterMetric: Hashable, Codable, Sendable {
    public let key: BackendCounterKey
    public let value: Int

    public init(key: BackendCounterKey, value: Int) {
        self.key = key
        self.value = value
    }
}

/// Identifies the player path that accepted the first successful `play()` call.
///
/// A streaming generation can begin through queued live PCM or, for short clips
/// that finish before the live prebuffer threshold, through the finalized WAV.
/// Keeping the source typed prevents their different buffer semantics from being
/// compared as though both were AVAudioPlayerNode queues.
public enum FrontendPlaybackStartSource: String, Codable, Sendable, Hashable {
    case liveStream
    case finalFile
}

public struct FrontendGenerationMetrics: Hashable, Codable, Sendable {
    public let submitToFirstChunkMS: Int?
    /// Submission to the point where playback was scheduled. This does not claim
    /// that acoustic output was independently observed.
    public let submitToPlaybackScheduledMS: Int?
    public let submitToCompletedMS: Int?
    public let firstChunkToPlaybackScheduledMS: Int?
    /// Sampled heartbeat delays, not an exhaustive enumeration of UI stalls.
    public let delayedHeartbeatCount50: Int
    public let delayedHeartbeatCount250: Int
    public let maximumDelayedHeartbeatMS: Int
    public let scheduledHeartbeatCount: Int
    public let completedHeartbeatCount: Int
    public let heartbeatCoveragePPM: Int
    public let playbackChunksReceived: Int
    public let playbackContinuityFailures: Int
    public let playbackUnderruns: Int
    public let playbackStartSource: FrontendPlaybackStartSource?
    public let playbackStartBufferedChunks: Int?
    public let playbackStartBufferedAudioMS: Int?
    public let playbackMinimumQueuedAudioMS: Int?

    /// Schema-v6 source compatibility. v7 encodes the accurate scheduled-playback
    /// name and decodes legacy "audible" fields into that canonical value.
    @available(*, deprecated, renamed: "submitToPlaybackScheduledMS")
    public var submitToFirstAudibleMS: Int? { submitToPlaybackScheduledMS }

    @available(*, deprecated, renamed: "firstChunkToPlaybackScheduledMS")
    public var firstChunkToAudibleMS: Int? { firstChunkToPlaybackScheduledMS }

    @available(*, deprecated, renamed: "delayedHeartbeatCount50")
    public var mainThreadStallCount50MS: Int { delayedHeartbeatCount50 }

    @available(*, deprecated, renamed: "delayedHeartbeatCount250")
    public var mainThreadStallCount250MS: Int { delayedHeartbeatCount250 }

    @available(*, deprecated, renamed: "maximumDelayedHeartbeatMS")
    public var mainThreadMaximumStallMS: Int { maximumDelayedHeartbeatMS }

    public init(
        submitToFirstChunkMS: Int? = nil,
        submitToPlaybackScheduledMS: Int? = nil,
        submitToCompletedMS: Int? = nil,
        firstChunkToPlaybackScheduledMS: Int? = nil,
        delayedHeartbeatCount50: Int = 0,
        delayedHeartbeatCount250: Int = 0,
        maximumDelayedHeartbeatMS: Int = 0,
        scheduledHeartbeatCount: Int = 0,
        completedHeartbeatCount: Int = 0,
        heartbeatCoveragePPM: Int = 0,
        playbackChunksReceived: Int = 0,
        playbackContinuityFailures: Int = 0,
        playbackUnderruns: Int = 0,
        playbackStartSource: FrontendPlaybackStartSource? = nil,
        playbackStartBufferedChunks: Int? = nil,
        playbackStartBufferedAudioMS: Int? = nil,
        playbackMinimumQueuedAudioMS: Int? = nil,
        submitToFirstAudibleMS: Int? = nil,
        firstChunkToAudibleMS: Int? = nil,
        mainThreadStallCount50MS: Int? = nil,
        mainThreadStallCount250MS: Int? = nil,
        mainThreadMaximumStallMS: Int? = nil
    ) {
        self.submitToFirstChunkMS = submitToFirstChunkMS
        self.submitToPlaybackScheduledMS = submitToPlaybackScheduledMS ?? submitToFirstAudibleMS
        self.submitToCompletedMS = submitToCompletedMS
        self.firstChunkToPlaybackScheduledMS = firstChunkToPlaybackScheduledMS ?? firstChunkToAudibleMS
        self.delayedHeartbeatCount50 = mainThreadStallCount50MS ?? delayedHeartbeatCount50
        self.delayedHeartbeatCount250 = mainThreadStallCount250MS ?? delayedHeartbeatCount250
        self.maximumDelayedHeartbeatMS = mainThreadMaximumStallMS ?? maximumDelayedHeartbeatMS
        self.scheduledHeartbeatCount = scheduledHeartbeatCount
        self.completedHeartbeatCount = completedHeartbeatCount
        self.heartbeatCoveragePPM = heartbeatCoveragePPM
        self.playbackChunksReceived = playbackChunksReceived
        self.playbackContinuityFailures = playbackContinuityFailures
        self.playbackUnderruns = playbackUnderruns
        self.playbackStartSource = playbackStartSource
        self.playbackStartBufferedChunks = playbackStartBufferedChunks
        self.playbackStartBufferedAudioMS = playbackStartBufferedAudioMS
        self.playbackMinimumQueuedAudioMS = playbackMinimumQueuedAudioMS
    }

    private enum CodingKeys: String, CodingKey {
        case submitToFirstChunkMS
        case submitToPlaybackScheduledMS
        case submitToFirstAudibleMS
        case submitToCompletedMS
        case firstChunkToPlaybackScheduledMS
        case firstChunkToAudibleMS
        case delayedHeartbeatCount50
        case delayedHeartbeatCount250
        case maximumDelayedHeartbeatMS
        case scheduledHeartbeatCount
        case completedHeartbeatCount
        case heartbeatCoveragePPM
        case playbackChunksReceived
        case playbackContinuityFailures
        case playbackUnderruns
        case playbackStartSource
        case playbackStartBufferedChunks
        case playbackStartBufferedAudioMS
        case playbackMinimumQueuedAudioMS
        case mainThreadStallCount50MS
        case mainThreadStallCount250MS
        case mainThreadMaximumStallMS
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        self.submitToFirstChunkMS = try container.decodeIfPresent(Int.self, forKey: .submitToFirstChunkMS)
        self.submitToPlaybackScheduledMS = try container.decodeIfPresent(Int.self, forKey: .submitToPlaybackScheduledMS)
            ?? container.decodeIfPresent(Int.self, forKey: .submitToFirstAudibleMS)
        self.submitToCompletedMS = try container.decodeIfPresent(Int.self, forKey: .submitToCompletedMS)
        self.firstChunkToPlaybackScheduledMS = try container.decodeIfPresent(Int.self, forKey: .firstChunkToPlaybackScheduledMS)
            ?? container.decodeIfPresent(Int.self, forKey: .firstChunkToAudibleMS)
        self.delayedHeartbeatCount50 = try container.decodeIfPresent(Int.self, forKey: .delayedHeartbeatCount50)
            ?? container.decodeIfPresent(Int.self, forKey: .mainThreadStallCount50MS) ?? 0
        self.delayedHeartbeatCount250 = try container.decodeIfPresent(Int.self, forKey: .delayedHeartbeatCount250)
            ?? container.decodeIfPresent(Int.self, forKey: .mainThreadStallCount250MS) ?? 0
        self.maximumDelayedHeartbeatMS = try container.decodeIfPresent(Int.self, forKey: .maximumDelayedHeartbeatMS)
            ?? container.decodeIfPresent(Int.self, forKey: .mainThreadMaximumStallMS) ?? 0
        self.scheduledHeartbeatCount = try container.decodeIfPresent(Int.self, forKey: .scheduledHeartbeatCount) ?? 0
        self.completedHeartbeatCount = try container.decodeIfPresent(Int.self, forKey: .completedHeartbeatCount) ?? 0
        self.heartbeatCoveragePPM = try container.decodeIfPresent(Int.self, forKey: .heartbeatCoveragePPM) ?? 0
        self.playbackChunksReceived = try container.decodeIfPresent(Int.self, forKey: .playbackChunksReceived) ?? 0
        self.playbackContinuityFailures = try container.decodeIfPresent(Int.self, forKey: .playbackContinuityFailures) ?? 0
        self.playbackUnderruns = try container.decodeIfPresent(Int.self, forKey: .playbackUnderruns) ?? 0
        self.playbackStartSource = try container.decodeIfPresent(
            FrontendPlaybackStartSource.self,
            forKey: .playbackStartSource
        )
        self.playbackStartBufferedChunks = try container.decodeIfPresent(Int.self, forKey: .playbackStartBufferedChunks)
        self.playbackStartBufferedAudioMS = try container.decodeIfPresent(Int.self, forKey: .playbackStartBufferedAudioMS)
        self.playbackMinimumQueuedAudioMS = try container.decodeIfPresent(Int.self, forKey: .playbackMinimumQueuedAudioMS)
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encodeIfPresent(submitToFirstChunkMS, forKey: .submitToFirstChunkMS)
        try container.encodeIfPresent(submitToPlaybackScheduledMS, forKey: .submitToPlaybackScheduledMS)
        try container.encodeIfPresent(submitToCompletedMS, forKey: .submitToCompletedMS)
        try container.encodeIfPresent(firstChunkToPlaybackScheduledMS, forKey: .firstChunkToPlaybackScheduledMS)
        try container.encode(delayedHeartbeatCount50, forKey: .delayedHeartbeatCount50)
        try container.encode(delayedHeartbeatCount250, forKey: .delayedHeartbeatCount250)
        try container.encode(maximumDelayedHeartbeatMS, forKey: .maximumDelayedHeartbeatMS)
        try container.encode(scheduledHeartbeatCount, forKey: .scheduledHeartbeatCount)
        try container.encode(completedHeartbeatCount, forKey: .completedHeartbeatCount)
        try container.encode(heartbeatCoveragePPM, forKey: .heartbeatCoveragePPM)
        try container.encode(playbackChunksReceived, forKey: .playbackChunksReceived)
        try container.encode(playbackContinuityFailures, forKey: .playbackContinuityFailures)
        try container.encode(playbackUnderruns, forKey: .playbackUnderruns)
        try container.encodeIfPresent(playbackStartSource, forKey: .playbackStartSource)
        try container.encodeIfPresent(playbackStartBufferedChunks, forKey: .playbackStartBufferedChunks)
        try container.encodeIfPresent(playbackStartBufferedAudioMS, forKey: .playbackStartBufferedAudioMS)
        try container.encodeIfPresent(playbackMinimumQueuedAudioMS, forKey: .playbackMinimumQueuedAudioMS)
    }
}

/// Bounded playback-health state shared by the macOS/iOS frontend timeline.
/// Keeping the queue-minimum logic in QwenVoiceCore makes normal drain,
/// continuity failure, and underrun semantics deterministic and unit-testable.
public struct PlaybackHealthAccumulator: Hashable, Sendable {
    public private(set) var chunksReceived = 0
    public private(set) var continuityFailures = 0
    public private(set) var underruns = 0
    public private(set) var startSource: FrontendPlaybackStartSource?
    public private(set) var startBufferedChunks: Int?
    public private(set) var startBufferedAudioMS: Int?
    public private(set) var minimumQueuedAudioMS: Int?

    public init() {}

    public mutating func playbackScheduled(
        source: FrontendPlaybackStartSource,
        queuedChunks: Int,
        queuedAudioMS: Int
    ) {
        startSource = source
        startBufferedChunks = max(queuedChunks, 0)
        startBufferedAudioMS = max(queuedAudioMS, 0)
        observeQueueDepth(queuedAudioMS: queuedAudioMS)
    }

    public mutating func chunkReceived(queuedAudioMS: Int) {
        chunksReceived += 1
        observeQueueDepth(queuedAudioMS: queuedAudioMS)
    }

    public mutating func queueDrained(queuedAudioMS: Int) {
        observeQueueDepth(queuedAudioMS: queuedAudioMS)
    }

    public mutating func continuityFailed() {
        continuityFailures += 1
    }

    public mutating func underrun() {
        underruns += 1
        observeQueueDepth(queuedAudioMS: 0)
    }

    private mutating func observeQueueDepth(queuedAudioMS: Int) {
        let bounded = max(queuedAudioMS, 0)
        minimumQueuedAudioMS = min(minimumQueuedAudioMS ?? bounded, bounded)
    }
}

public struct EngineTransportCounters: Hashable, Codable, Sendable {
    public let chunksForwarded: Int
    public let chunkGaps: Int
    public let duplicateChunks: Int
    public let outOfOrderChunks: Int

    public init(
        chunksForwarded: Int = 0,
        chunkGaps: Int = 0,
        duplicateChunks: Int = 0,
        outOfOrderChunks: Int = 0
    ) {
        self.chunksForwarded = chunksForwarded
        self.chunkGaps = chunkGaps
        self.duplicateChunks = duplicateChunks
        self.outOfOrderChunks = outOfOrderChunks
    }
}

public struct EngineTransportMetrics: Hashable, Codable, Sendable {
    public let finishReason: GenerationTerminalReason
    /// Request acceptance to first forwarded chunk. nil when a legacy transport
    /// row did not capture its acceptance instant.
    public let requestToFirstChunkMS: Int?
    public let firstChunkToTerminalMS: Int?
    public let counters: EngineTransportCounters
    public let cancellation: GenerationCancellationState
    public let lifecycle: GenerationTransportState
    public let requestAccepted: Bool
    public let sessionIdentity: String?
    public let firstChunkSequence: UInt64?
    public let lastChunkSequence: UInt64?
    public let lifecycleEvents: [GenerationTransportState]

    public init(
        finishReason: GenerationTerminalReason,
        requestToFirstChunkMS: Int? = nil,
        firstChunkToTerminalMS: Int? = nil,
        counters: EngineTransportCounters,
        cancellation: GenerationCancellationState = .notRequested,
        lifecycle: GenerationTransportState = .connected,
        requestAccepted: Bool = false,
        sessionIdentity: String? = nil,
        firstChunkSequence: UInt64? = nil,
        lastChunkSequence: UInt64? = nil,
        lifecycleEvents: [GenerationTransportState] = [.connected]
    ) {
        self.finishReason = finishReason
        self.requestToFirstChunkMS = requestToFirstChunkMS
        self.firstChunkToTerminalMS = firstChunkToTerminalMS
        self.counters = counters
        self.cancellation = cancellation
        self.lifecycle = lifecycle
        self.requestAccepted = requestAccepted
        self.sessionIdentity = sessionIdentity
        self.firstChunkSequence = firstChunkSequence
        self.lastChunkSequence = lastChunkSequence
        self.lifecycleEvents = lifecycleEvents
    }
}

public struct BackendGenerationMetrics: Hashable, Codable, Sendable {
    public let finishReason: GenerationTerminalReason
    public let warmState: EngineWarmState?
    public let usedStreaming: Bool?
    public let stages: [NativeTelemetryStageMark]
    public let timings: [BackendTimingMetric]
    public let counters: [BackendCounterMetric]
    public let finalChunkBarrierObserved: Bool?

    public init(
        finishReason: GenerationTerminalReason,
        warmState: EngineWarmState?,
        usedStreaming: Bool?,
        stages: [NativeTelemetryStageMark],
        timings: [BackendTimingMetric],
        counters: [BackendCounterMetric],
        finalChunkBarrierObserved: Bool? = nil
    ) {
        self.finishReason = finishReason
        self.warmState = warmState
        self.usedStreaming = usedStreaming
        self.stages = stages
        self.timings = timings
        self.counters = counters
        self.finalChunkBarrierObserved = finalChunkBarrierObserved
    }
}

/// Stable, typed identity for the runtime selected for one generation.
/// Contract revision/artifact/integrity fields are joined by the benchmark
/// exporter; this payload keeps validators from guessing the active profile or
/// fixture from legacy free-form dictionaries.
public struct ModelRuntimeIdentity: Hashable, Codable, Sendable {
    public let resolvedModelID: String
    public let modelVariant: String?
    public let modelRepository: String?
    public let huggingFaceRevision: String?
    public let artifactVersion: String?
    public let quantization: String?
    public let integrityManifestDigest: String?
    public let speechTokenizerDigest: String?
    public let runtimeProfileSignature: String?
    public let nativeLoadCapabilityProfile: String?
    public let fixtureDigest: String?

    public init(
        resolvedModelID: String,
        modelVariant: String? = nil,
        modelRepository: String? = nil,
        huggingFaceRevision: String? = nil,
        artifactVersion: String? = nil,
        quantization: String? = nil,
        integrityManifestDigest: String? = nil,
        speechTokenizerDigest: String? = nil,
        runtimeProfileSignature: String? = nil,
        nativeLoadCapabilityProfile: String? = nil,
        fixtureDigest: String? = nil
    ) {
        self.resolvedModelID = resolvedModelID
        self.modelVariant = modelVariant
        self.modelRepository = modelRepository
        self.huggingFaceRevision = huggingFaceRevision
        self.artifactVersion = artifactVersion
        self.quantization = quantization
        self.integrityManifestDigest = integrityManifestDigest
        self.speechTokenizerDigest = speechTokenizerDigest
        self.runtimeProfileSignature = runtimeProfileSignature
        self.nativeLoadCapabilityProfile = nativeLoadCapabilityProfile
        self.fixtureDigest = fixtureDigest
    }
}

public struct GenerationOutputMetrics: Hashable, Codable, Sendable {
    public let durationSeconds: Double?
    public let readableWAV: Bool?
    public let atomicallyPublished: Bool?
    public let audioQC: AudioQCReport?

    public init(
        durationSeconds: Double? = nil,
        readableWAV: Bool? = nil,
        atomicallyPublished: Bool? = nil,
        audioQC: AudioQCReport? = nil
    ) {
        self.durationSeconds = durationSeconds
        self.readableWAV = readableWAV
        self.atomicallyPublished = atomicallyPublished
        self.audioQC = audioQC
    }
}

public enum GenerationTelemetryCompatibilityAdapter {
    public static func frontend(
        timingsMS: [String: Int],
        counters: [String: Int],
        playbackStartSource: FrontendPlaybackStartSource? = nil
    ) -> FrontendGenerationMetrics {
        FrontendGenerationMetrics(
            submitToFirstChunkMS: timingsMS["submitToFirstChunkMS"],
            submitToPlaybackScheduledMS: timingsMS["submitToPlaybackScheduledMS"]
                ?? timingsMS["submitToFirstAudibleMS"],
            submitToCompletedMS: timingsMS["submitToCompletedMS"],
            firstChunkToPlaybackScheduledMS: timingsMS["firstChunkToPlaybackScheduledMS"]
                ?? timingsMS["firstChunkToAudibleMS"]
                ?? timingsMS["chunkForwardingSpanMS"],
            delayedHeartbeatCount50: counters["delayedHeartbeatCount50"] ?? counters["uiStallCount50"] ?? 0,
            delayedHeartbeatCount250: counters["delayedHeartbeatCount250"] ?? counters["uiStallCount250"] ?? 0,
            maximumDelayedHeartbeatMS: counters["maximumDelayedHeartbeatMS"] ?? counters["uiMaxStallMS"] ?? 0,
            scheduledHeartbeatCount: counters["heartbeatScheduledCount"] ?? 0,
            completedHeartbeatCount: counters["heartbeatCompletedCount"] ?? counters["uiHeartbeats"] ?? 0,
            heartbeatCoveragePPM: counters["heartbeatCoveragePPM"] ?? 0,
            playbackChunksReceived: counters["playbackChunksReceived"] ?? 0,
            playbackContinuityFailures: counters["playbackContinuityFailures"] ?? 0,
            playbackUnderruns: counters["playbackUnderruns"] ?? 0,
            playbackStartSource: playbackStartSource,
            playbackStartBufferedChunks: counters["playbackStartBufferedChunks"],
            playbackStartBufferedAudioMS: timingsMS["playbackStartBufferedAudioMS"],
            playbackMinimumQueuedAudioMS: timingsMS["playbackMinimumQueuedAudioMS"]
        )
    }

    public static func transport(
        finishReason: String?,
        timingsMS: [String: Int],
        counters: [String: Int]
    ) -> EngineTransportMetrics {
        EngineTransportMetrics(
            finishReason: GenerationTerminalReason(compatibilityValue: finishReason),
            requestToFirstChunkMS: timingsMS["requestToFirstChunkMS"],
            firstChunkToTerminalMS: timingsMS["chunkForwardingSpanMS"],
            counters: EngineTransportCounters(
                chunksForwarded: counters["chunksForwarded"] ?? 0,
                chunkGaps: counters["chunkGaps"] ?? 0,
                duplicateChunks: counters["duplicateChunks"] ?? 0,
                outOfOrderChunks: counters["outOfOrderChunks"] ?? 0
            ),
            cancellation: GenerationTerminalReason(compatibilityValue: finishReason) == .cancelled
                ? .completed : .notRequested,
            requestAccepted: counters["chunksForwarded", default: 0] > 0
        )
    }

    public static func backend(
        finishReason: String?,
        warmState: EngineWarmState?,
        usedStreaming: Bool?,
        stages: [NativeTelemetryStageMark],
        timingsMS: [String: Int],
        counters: [String: Int],
        notes: [String: String]
    ) -> BackendGenerationMetrics {
        let timingKeys: [(BackendTimingKey, [String])] = [
            (.modelLoad, ["native_model_load_ms"]),
            (.prepareGeneration, ["native_prepare_generation_ms"]),
            (.explicitPrewarm, ["native_explicit_prewarm_ms"]),
            (.cloneConditioning, ["native_clone_conditioning_ms"]),
            (.generationStream, ["native_generation_stream_ms"]),
            (.qualityFirstGeneration, ["native_quality_first_generation_ms"]),
            (.tokenLoop, ["qwen_token_loop_total"]),
            (.talkerForward, ["qwen_talker_forward_total"]),
            (.codePredictor, ["qwen_code_predictor_total"]),
            (.audioDecoder, ["qwen_stream_decoder_total"]),
            (.streamStepEval, ["qwen_stream_step_eval_total"]),
            (.streamStepEOSRead, ["qwen_stream_step_eos_read_total"]),
            (.audioChunkEval, ["qwen_audio_chunk_eval_total"]),
            (.finalWAVFinish, ["native_final_wav_finish_ms"]),
        ]
        let typedTimings = timingKeys.compactMap { key, compatibilityKeys -> BackendTimingMetric? in
            guard let value = compatibilityKeys.lazy.compactMap({ timingsMS[$0] }).first else { return nil }
            return BackendTimingMetric(key: key, milliseconds: Double(value))
        }
        let counterKeys: [(BackendCounterKey, [String])] = [
            (.generatedCodes, ["qwen_generated_code_count", "generatedCodeCount"]),
            (.decoderCalls, ["qwen_stream_decoder_calls", "decoderCalls"]),
            (.chunkCount, ["chunkCount"]),
            (.pendingCodePeak, ["pendingCodePeak"]),
        ]
        let typedCounters = counterKeys.compactMap { key, compatibilityKeys -> BackendCounterMetric? in
            guard let value = compatibilityKeys.lazy.compactMap({ counters[$0] ?? timingsMS[$0] }).first else { return nil }
            return BackendCounterMetric(key: key, value: value)
        }
        return BackendGenerationMetrics(
            finishReason: GenerationTerminalReason(compatibilityValue: finishReason),
            warmState: warmState,
            usedStreaming: usedStreaming,
            stages: stages,
            timings: typedTimings,
            counters: typedCounters,
            finalChunkBarrierObserved: notes["finalChunkBarrierObserved"].flatMap(Bool.init)
        )
    }

    public static func output(
        notes: [String: String],
        audioQC: AudioQCReport?
    ) -> GenerationOutputMetrics {
        GenerationOutputMetrics(
            durationSeconds: audioQC?.durationSeconds,
            readableWAV: notes["outputReadableWAV"].flatMap(Bool.init),
            atomicallyPublished: notes["outputAtomicallyPublished"].flatMap(Bool.init),
            audioQC: audioQC
        )
    }
}

public enum GenerationTelemetryPrivacy {
    /// Converts a potentially path- or content-bearing runtime failure into bounded,
    /// correlation-safe metadata. Call only while telemetry is enabled.
    public static func failureNotes(message: String) -> [String: String] {
        let digest = SHA256.hash(data: Data(message.utf8))
            .map { String(format: "%02x", $0) }
            .joined()
        return [
            "failureMessageLength": String(message.count),
            "failureMessageDigest": digest,
        ]
    }
}

public enum GenerationMemoryEventKind: String, Hashable, Codable, Sendable {
    case pressureSignal = "pressure-signal"
    case applicationWarning = "application-warning"
    case budgetTransition = "budget-transition"
    case trimAction = "trim-action"
    case unload
    /// Delayed MetricKit exit aggregates are not generation-correlated, but use
    /// the same stable vocabulary in their local privacy-reduced document.
    case memoryExit = "memory-exit"
}

/// Typed, privacy-safe memory lifecycle evidence derived from stage marks. It
/// retains only code-owned enum values and a bounded reason code.
public struct GenerationMemoryEvent: Hashable, Codable, Sendable {
    public let tMS: Int
    public let tNS: UInt64?
    public let sequence: Int?
    public let kind: GenerationMemoryEventKind
    public let source: NativeMemoryEventSource
    public let trimLevel: NativeMemoryTrimLevel?
    public let previousPressureBand: IOSMemoryPressureBand?
    public let currentPressureBand: IOSMemoryPressureBand?
    public let reasonCode: String?

    public init(
        tMS: Int,
        tNS: UInt64?,
        sequence: Int?,
        kind: GenerationMemoryEventKind,
        source: NativeMemoryEventSource,
        trimLevel: NativeMemoryTrimLevel? = nil,
        previousPressureBand: IOSMemoryPressureBand? = nil,
        currentPressureBand: IOSMemoryPressureBand? = nil,
        reasonCode: String? = nil
    ) {
        self.tMS = tMS
        self.tNS = tNS
        self.sequence = sequence
        self.kind = kind
        self.source = source
        self.trimLevel = trimLevel
        self.previousPressureBand = previousPressureBand
        self.currentPressureBand = currentPressureBand
        self.reasonCode = reasonCode.map { String($0.prefix(64)) }
    }

    static func derive(from stageMarks: [NativeTelemetryStageMark]) -> [GenerationMemoryEvent] {
        stageMarks.sorted(by: NativeTelemetryStageMark.chronologicallyPrecedes).compactMap { mark in
            if mark.stage == MemoryPressureMetadata.stage,
               let metadata = mark.typedMetadata(as: MemoryPressureMetadata.self) {
                return GenerationMemoryEvent(
                    tMS: mark.tMS,
                    tNS: mark.tNS,
                    sequence: mark.sequence,
                    kind: .pressureSignal,
                    source: metadata.source,
                    trimLevel: metadata.level
                )
            }
            if mark.stage == MemoryWarningMetadata.stage,
               let metadata = mark.typedMetadata(as: MemoryWarningMetadata.self) {
                return GenerationMemoryEvent(
                    tMS: mark.tMS,
                    tNS: mark.tNS,
                    sequence: mark.sequence,
                    kind: .applicationWarning,
                    source: metadata.source,
                    reasonCode: metadata.reason
                )
            }
            if mark.stage == MemoryBudgetTransitionMetadata.stage,
               let metadata = mark.typedMetadata(as: MemoryBudgetTransitionMetadata.self) {
                return GenerationMemoryEvent(
                    tMS: mark.tMS,
                    tNS: mark.tNS,
                    sequence: mark.sequence,
                    kind: .budgetTransition,
                    source: metadata.source,
                    previousPressureBand: metadata.previousBand,
                    currentPressureBand: metadata.currentBand,
                    reasonCode: metadata.reason
                )
            }
            if mark.stage == MemoryTrimMetadata.stage,
               let metadata = mark.typedMetadata(as: MemoryTrimMetadata.self) {
                return GenerationMemoryEvent(
                    tMS: mark.tMS,
                    tNS: mark.tNS,
                    sequence: mark.sequence,
                    kind: .trimAction,
                    source: metadata.source,
                    trimLevel: metadata.level,
                    reasonCode: metadata.reason
                )
            }
            if mark.stage == MemoryUnloadMetadata.stage,
               let metadata = mark.typedMetadata(as: MemoryUnloadMetadata.self) {
                return GenerationMemoryEvent(
                    tMS: mark.tMS,
                    tNS: mark.tNS,
                    sequence: mark.sequence,
                    kind: .unload,
                    source: metadata.source,
                    reasonCode: metadata.reason
                )
            }
            return nil
        }
    }
}

/// Typed headline memory evidence for validators and history exporters. Raw
/// process samples and the full per-stage MLX map remain in their existing
/// fields; this payload makes coverage/events/cumulative MLX peaks explicit.
public struct GenerationMemoryMetrics: Hashable, Codable, Sendable {
    public let processRole: TelemetryProcessRole?
    public let captureCoverage: TelemetryCaptureCoverage?
    public let boundaryCoverage: TelemetryBoundaryCoverage?
    public let worstPressureBand: IOSMemoryPressureBand?
    public let events: [GenerationMemoryEvent]
    public let mlxCumulativePeakMB: Double?
    public let mlxActivePeakMB: Double?
    public let mlxCachePeakMB: Double?
    public let mlxStageCount: Int
    public let mlxStageNames: [String]

    public init(
        summary: TelemetrySummary?,
        stageMarks: [NativeTelemetryStageMark],
        mlxMemoryByStage: [String: NativeMLXMemorySnapshot]?
    ) {
        self.processRole = summary?.processRole
        self.captureCoverage = summary?.captureCoverage
        self.boundaryCoverage = summary?.boundaryCoverage
        self.worstPressureBand = Self.worstPressureBand(for: summary)
        self.events = GenerationMemoryEvent.derive(from: stageMarks)
        let snapshots = mlxMemoryByStage.map { Array($0.values) } ?? []
        self.mlxCumulativePeakMB = snapshots.compactMap(\.peakMB).max()
        self.mlxActivePeakMB = snapshots.compactMap(\.activeMB).max()
        self.mlxCachePeakMB = snapshots.compactMap(\.cacheMB).max()
        self.mlxStageNames = Array((mlxMemoryByStage?.keys.sorted() ?? []).prefix(64))
        self.mlxStageCount = mlxMemoryByStage?.count ?? 0
    }

    /// The shipping pressure bands are an iOS process-budget policy. macOS
    /// retains the same raw footprint and Metal metrics, but must not be judged
    /// against iPhone absolute limits.
    static func worstPressureBand(for summary: TelemetrySummary?) -> IOSMemoryPressureBand? {
        #if os(iOS)
        IOSMemoryBudgetPolicy.iPhoneShippingDefault.worstBand(
            headroomMinMB: summary?.headroomMinMB,
            physFootprintPeakMB: summary?.physFootprintPeakMB,
            gpuWorkingSetUsageRatioPeak: summary?.gpuWorkingSetUsageRatioPeak
        )
        #else
        nil
        #endif
    }
}

/// One durable telemetry row for a single generation, written by one layer.
///
/// Every layer (engine / engine-service / app) emits its own
/// record keyed by the same `generationID` (threaded app → engine, see
/// `NativeEngineRuntime`), so the per-layer JSONL streams join cleanly into the
/// unified `generations-merged.jsonl` (`layer == "merged"`).
///
/// Naming note: deliberately avoids the `Probe`/`Benchmark` tokens banned by
/// `scripts/check_project_inputs.sh`.
public struct GenerationTelemetryRecord: Hashable, Codable, Sendable {
    public enum Layer: String, Hashable, Codable, Sendable {
        case engine
        case engineService = "engine-service"
        case app
        case merged
    }

    /// v2 added the backend-optimization payload: `derivedMetrics` (RTF, tokens/sec),
    /// `mlxMemoryByStage` (per-stage MLX GPU memory), and `chunkTimeline` (per-chunk
    /// decode substage breakdown). v3 added `modelID` + `warmState` so each row
    /// self-identifies its benchmark cell (model variant × cold/warm). v4 added
    /// `audioQC` (reference-free output-quality verdict + defect flags). v5 added
    /// high-resolution `mach_absolute_time` nanoseconds (`clockSource`, stage-mark
    /// `tNS`/`sequence`, sample `tNS`/`actualElapsedNS`, chunk `arrivalNS`). v6
    /// added typed frontend/transport/backend/output payloads. v7 adds explicit
    /// sampler scheduling/capture accuracy, process resource deltas, merge
    /// completeness, and accurate playback-scheduled frontend naming. v8 splits
    /// memory/thread/resource capture coverage, adds cross-process uptime and
    /// process roles, aligned iOS budget/Metal evidence, lifecycle-boundary
    /// coverage, and typed memory events/MLX peaks. All new payload fields remain
    /// optional or compatibility-decoded so v7 rows remain readable.
    public static let currentSchemaVersion = 8

    public let clockSource: String?

    public let schemaVersion: Int
    public let generationID: String
    public let layer: Layer
    public let processName: String
    public let processIdentifier: Int32
    public let recordedAt: String
    public let mode: String?
    /// The resolved model id for this generation (variant-specific — distinguishes
    /// Speed 4-bit vs Quality 8-bit). Lets a benchmark attribute the row to its cell.
    public let modelID: String?
    /// Whether the model was loaded by THIS generation (`.cold`) or reused from a
    /// prior one (`.warm`). The benchmark's cold/warm axis.
    public let warmState: EngineWarmState?
    public let usedStreaming: Bool?
    public let finishReason: String?
    public let stageMarks: [NativeTelemetryStageMark]
    /// Raw integer timings. For the engine layer this carries the full MLX decode
    /// breakdown (talker forward, code predictor, decoder, stream-step eval/EOS,
    /// token-loop total, unattributed) + counters (generated codes, decoder calls),
    /// re-read from the model AFTER the decode loop so the hot-loop totals are final.
    public let timingsMS: [String: Int]
    public let counters: [String: Int]
    public let notes: [String: String]
    public let summary: TelemetrySummary?
    public let thermalState: ThermalStateSnapshot?
    /// Headline derived throughput KPIs (engine layer): `audioSeconds`,
    /// `decodeWallSeconds`, `audioSecondsPerWallSecond` (>1 = faster than realtime),
    /// `tokensPerSecond`, `generatedTokenCount`. nil when not computed.
    public let derivedMetrics: [String: Double]?
    /// Per-stage MLX GPU memory (active/cache/peak MB) — e.g. before_stream,
    /// first_chunk, after_stream, after_generation_trim. nil when not collected.
    public let mlxMemoryByStage: [String: NativeMLXMemorySnapshot]?
    /// Per-chunk decode substage breakdown for streaming runs (cold-start vs
    /// steady-state, stall localization). nil for non-streaming / when gated off.
    public let chunkTimeline: [GenerationChunkTelemetry]?
    /// Reference-free audio-quality verdict for this take (defect detection on the
    /// final PCM — NaN/clip/click/dropout/level). The objective regression tripwire
    /// for backend changes; nil when not computed. This catches gross defects rather
    /// than subjective naturalness; autonomous promotion combines it with the
    /// applicable fixed-seed ASR, prosody, and delivery evidence.
    public let audioQC: AudioQCReport?
    /// Typed v6+ payloads. The legacy dictionaries above remain encoded for
    /// historical tools; new validators use these stable fields.
    public let frontendMetrics: FrontendGenerationMetrics?
    public let transportMetrics: EngineTransportMetrics?
    public let backendMetrics: BackendGenerationMetrics?
    public let outputMetrics: GenerationOutputMetrics?
    public let modelRuntimeIdentity: ModelRuntimeIdentity?
    public let memoryMetrics: GenerationMemoryMetrics?
    /// Schema-v9 streaming transition evidence nested inside the shipping
    /// schema-v8 row. This keeps benchmark-history schema v2 compatible while
    /// making unavailable actor/session observations explicit instead of zero.
    public let streamingTelemetryV9: GenerationStreamingTelemetryTransitionV9?
    /// Privacy-safe startup/request identity. Optional so every historical
    /// schema-v1...v8 row remains decodable without migration.
    public let requestReceipt: GenerationRequestReceipt?

    public init(
        generationID: String,
        layer: Layer,
        recordedAt: String,
        mode: String? = nil,
        modelID: String? = nil,
        warmState: EngineWarmState? = nil,
        usedStreaming: Bool? = nil,
        finishReason: String? = nil,
        stageMarks: [NativeTelemetryStageMark] = [],
        summary: TelemetrySummary? = nil,
        thermalState: ThermalStateSnapshot? = nil,
        timingsMS: [String: Int] = [ :],
        counters: [String: Int] = [:],
        notes: [String: String] = [:],
        derivedMetrics: [String: Double]? = nil,
        mlxMemoryByStage: [String: NativeMLXMemorySnapshot]? = nil,
        chunkTimeline: [GenerationChunkTelemetry]? = nil,
        audioQC: AudioQCReport? = nil,
        frontendMetrics: FrontendGenerationMetrics? = nil,
        transportMetrics: EngineTransportMetrics? = nil,
        backendMetrics: BackendGenerationMetrics? = nil,
        outputMetrics: GenerationOutputMetrics? = nil,
        modelRuntimeIdentity: ModelRuntimeIdentity? = nil,
        memoryMetrics: GenerationMemoryMetrics? = nil,
        streamingTelemetryV9: GenerationStreamingTelemetryTransitionV9? = nil,
        requestReceipt: GenerationRequestReceipt? = nil,
        clockSource: String? = "mach_absolute_time",
        schemaVersion: Int = GenerationTelemetryRecord.currentSchemaVersion,
        processName: String = ProcessInfo.processInfo.processName,
        processIdentifier: Int32 = ProcessInfo.processInfo.processIdentifier
    ) {
        self.clockSource = clockSource
        self.schemaVersion = schemaVersion
        self.generationID = generationID
        self.layer = layer
        self.processName = processName
        self.processIdentifier = processIdentifier
        self.recordedAt = recordedAt
        self.mode = mode
        self.modelID = modelID
        self.warmState = warmState
        self.usedStreaming = usedStreaming
        self.finishReason = finishReason
        self.stageMarks = stageMarks
        self.summary = summary
        self.thermalState = thermalState
        self.timingsMS = timingsMS
        self.counters = counters
        self.notes = notes
        self.derivedMetrics = derivedMetrics
        self.mlxMemoryByStage = mlxMemoryByStage
        self.chunkTimeline = chunkTimeline
        self.audioQC = audioQC
        self.frontendMetrics = frontendMetrics ?? (layer == .app
            ? GenerationTelemetryCompatibilityAdapter.frontend(timingsMS: timingsMS, counters: counters)
            : nil)
        self.transportMetrics = transportMetrics ?? (layer == .engineService
            ? GenerationTelemetryCompatibilityAdapter.transport(
                finishReason: finishReason,
                timingsMS: timingsMS,
                counters: counters
            )
            : nil)
        self.backendMetrics = backendMetrics ?? (layer == .engine
            ? GenerationTelemetryCompatibilityAdapter.backend(
                finishReason: finishReason,
                warmState: warmState,
                usedStreaming: usedStreaming,
                stages: stageMarks,
                timingsMS: timingsMS,
                counters: counters,
                notes: notes
            )
            : nil)
        self.outputMetrics = outputMetrics ?? (layer == .engine
            ? GenerationTelemetryCompatibilityAdapter.output(notes: notes, audioQC: audioQC)
            : nil)
        self.modelRuntimeIdentity = modelRuntimeIdentity ?? (
            layer == .engine && modelID != nil
                ? ModelRuntimeIdentity(
                    resolvedModelID: modelID!,
                    modelVariant: notes["modelVariant"],
                    modelRepository: notes["modelRepository"],
                    huggingFaceRevision: notes["huggingFaceRevision"],
                    artifactVersion: notes["modelArtifactVersion"],
                    quantization: notes["modelQuantization"],
                    integrityManifestDigest: notes["modelIntegrityManifestDigest"],
                    speechTokenizerDigest: notes["speechTokenizerDigest"],
                    runtimeProfileSignature: notes["qwen3RuntimeProfileSignature"],
                    nativeLoadCapabilityProfile: notes["nativeLoadCapabilityProfile"],
                    fixtureDigest: notes["fixtureDigest"]
                )
                : nil
        )
        self.memoryMetrics = memoryMetrics ?? (
            summary != nil || mlxMemoryByStage != nil || stageMarks.contains(where: {
                $0.stage == MemoryPressureMetadata.stage
                    || $0.stage == MemoryWarningMetadata.stage
                    || $0.stage == MemoryBudgetTransitionMetadata.stage
                    || $0.stage == MemoryTrimMetadata.stage
                    || $0.stage == MemoryUnloadMetadata.stage
            })
                ? GenerationMemoryMetrics(
                    summary: summary,
                    stageMarks: stageMarks,
                    mlxMemoryByStage: mlxMemoryByStage
                )
                : nil
        )
        self.streamingTelemetryV9 = streamingTelemetryV9
            ?? GenerationStreamingTelemetryV9Bridge.make(
                generationID: generationID,
                layer: layer,
                notes: notes,
                frontend: self.frontendMetrics,
                transport: self.transportMetrics
            )
        self.requestReceipt = requestReceipt
    }
}

/// Reference-free audio-quality verdict for one generated take, derived from the
/// `PCM16StreamLimiter` per-sample pass (no stored golden, no model). The objective
/// half of the quality gate: it catches gross defects (unstable model output,
/// clipping, chunk-boundary clicks/discontinuities, mid-utterance dropouts, dead
/// output). It deliberately does NOT claim subjective naturalness. Autonomous
/// promotion combines it with the applicable ASR, prosody, and delivery gates;
/// optional listening remains annotation only. Thresholds are conservative +
/// tunable (see the builder in `GenerationOutputAdapter`).
public struct AudioCadenceQCReport: Hashable, Codable, Sendable {
    public enum Classification: String, Hashable, Codable, Sendable {
        /// The bounded amplitude-only gate found no cadence anomaly. This is not
        /// a semantic naturalness claim; the delivery evaluator owns that decision.
        case withinFastGate
        /// The take remains usable, but its pause pattern warrants an explicit
        /// user notice and downstream inspection.
        case unusual
        /// The existing gross-defect policy rejected the take before product
        /// publication. This classification never creates a new hard threshold.
        case severe
    }

    public enum Reason: String, Hashable, Codable, Sendable {
        case excessCadencePauses = "excess_cadence_pauses"
        case singleSuspiciousPause = "single_suspicious_pause"
        case repeatedSuspiciousPauses = "repeated_suspicious_pauses"
        case egregiousInteriorSilence = "egregious_interior_silence"
    }

    public let classification: Classification
    public let reasons: [Reason]
    public let expectedPauseCount: Int
    public let cadencePauseThresholdMS: Int
    public let suspiciousPauseThresholdMS: Int
    public let observedCadencePauseCount: Int
    public let excessCadencePauseCount: Int
    public let suspiciousPauseCount: Int
    /// Every bounded interior pause retained by the fast analyzer, in close order.
    /// Values contain no prompt text or audio and remain capped by the limiter.
    public let recordedInteriorPausesMS: [Int]
    public let totalInteriorSilenceMS: Int
    public let totalCadenceSilenceMS: Int
    public let medianCadencePauseMS: Int?
    public let p90CadencePauseMS: Int?
    public let cadenceSilenceRatio: Double

    public init(
        classification: Classification,
        reasons: [Reason],
        expectedPauseCount: Int,
        cadencePauseThresholdMS: Int,
        suspiciousPauseThresholdMS: Int,
        observedCadencePauseCount: Int,
        excessCadencePauseCount: Int,
        suspiciousPauseCount: Int,
        recordedInteriorPausesMS: [Int],
        totalInteriorSilenceMS: Int,
        totalCadenceSilenceMS: Int,
        medianCadencePauseMS: Int?,
        p90CadencePauseMS: Int?,
        cadenceSilenceRatio: Double
    ) {
        self.classification = classification
        self.reasons = reasons
        self.expectedPauseCount = expectedPauseCount
        self.cadencePauseThresholdMS = cadencePauseThresholdMS
        self.suspiciousPauseThresholdMS = suspiciousPauseThresholdMS
        self.observedCadencePauseCount = observedCadencePauseCount
        self.excessCadencePauseCount = excessCadencePauseCount
        self.suspiciousPauseCount = suspiciousPauseCount
        self.recordedInteriorPausesMS = recordedInteriorPausesMS
        self.totalInteriorSilenceMS = totalInteriorSilenceMS
        self.totalCadenceSilenceMS = totalCadenceSilenceMS
        self.medianCadencePauseMS = medianCadencePauseMS
        self.p90CadencePauseMS = p90CadencePauseMS
        self.cadenceSilenceRatio = cadenceSilenceRatio
    }
}

public struct AudioQCReport: Hashable, Codable, Sendable {
    /// v2 fixed cross-chunk interior-silence localization. v3 derives the
    /// written-output verdict from the atomically published WAV frames rather
    /// than assuming the pre-write limited buffer and persisted file agree. v4
    /// separates ordinary cadence warnings from repeated suspicious-scale or
    /// context-sensitive egregious dead-air failures. v5 retains those exact
    /// verdict boundaries and adds a structured, bounded cadence report.
    public static let currentAlgorithmVersion = 5

    public enum Verdict: String, Hashable, Codable, Sendable {
        case pass
        case warn
        case fail
    }

    public let algorithmVersion: Int
    /// Instability detected at the model/limiter input (non-finite values,
    /// clipping, excessive discontinuities, or sustained over-ceiling samples).
    public let instabilityVerdict: Verdict
    /// Quality of the frames re-read from the atomically published WAV (level,
    /// dropout, and DC-offset checks). `verdict` remains the worst of these two.
    public let writtenOutputVerdict: Verdict
    public let verdict: Verdict
    /// Human-readable defect tags that tripped (e.g. "nonfinite", "clipping",
    /// "clicks", "dropout:240ms", "near_silent"). Empty on a clean pass.
    public let flags: [String]
    /// Whole-clip RMS in dBFS (nil = total silence).
    public let rmsDBFS: Double?
    /// Mean of the limited output samples. Values far from zero indicate DC bias.
    public let dcOffset: Double?
    public let peak: Double
    /// Samples that exceeded unit range (true digital clipping, pre-limiter).
    public let clippedSamples: Int
    /// Samples above the limiter ceiling (hot but not hard-clipped).
    public let hotSamples: Int
    /// Non-finite (NaN/Inf) input samples scrubbed by the limiter — model instability.
    public let nonFiniteSamples: Int
    /// Slew-limited steps: sample-to-sample jumps beyond the click ceiling
    /// (chunk-boundary clicks / decoder discontinuities).
    public let clickEvents: Int
    /// Longest interior near-silent run (mid-utterance dropout), in milliseconds.
    public let longestSilenceMS: Int
    /// Absolute sample index of the first non-finite sample, or nil if none.
    public let firstNonFiniteSample: Int?
    /// Absolute sample index of the first sample outside the digital unit range,
    /// or nil if none.
    public let firstClipSample: Int?
    /// Start time of the longest interior near-silent run, in milliseconds since
    /// the start of the clip, or nil if none.
    public let longestSilenceStartMS: Int?
    public let durationSeconds: Double
    /// Schema-versioned cadence evidence. Optional for v1-v4 telemetry.
    public let cadence: AudioCadenceQCReport?
    /// Optional per-chunk QC snapshots (verbose mode only). nil when not computed.
    public let chunkQC: [AudioQCChunkReport]?

    public init(
        algorithmVersion: Int = AudioQCReport.currentAlgorithmVersion,
        instabilityVerdict: Verdict? = nil,
        writtenOutputVerdict: Verdict? = nil,
        verdict: Verdict,
        flags: [String],
        rmsDBFS: Double?,
        dcOffset: Double? = nil,
        peak: Double,
        clippedSamples: Int,
        hotSamples: Int,
        nonFiniteSamples: Int,
        clickEvents: Int,
        longestSilenceMS: Int,
        durationSeconds: Double,
        firstNonFiniteSample: Int? = nil,
        firstClipSample: Int? = nil,
        longestSilenceStartMS: Int? = nil,
        cadence: AudioCadenceQCReport? = nil,
        chunkQC: [AudioQCChunkReport]? = nil
    ) {
        self.algorithmVersion = algorithmVersion
        self.instabilityVerdict = instabilityVerdict ?? verdict
        self.writtenOutputVerdict = writtenOutputVerdict ?? verdict
        self.verdict = verdict
        self.flags = flags
        self.rmsDBFS = rmsDBFS
        self.dcOffset = dcOffset
        self.peak = peak
        self.clippedSamples = clippedSamples
        self.hotSamples = hotSamples
        self.nonFiniteSamples = nonFiniteSamples
        self.clickEvents = clickEvents
        self.longestSilenceMS = longestSilenceMS
        self.durationSeconds = durationSeconds
        self.firstNonFiniteSample = firstNonFiniteSample
        self.firstClipSample = firstClipSample
        self.longestSilenceStartMS = longestSilenceStartMS
        self.cadence = cadence
        self.chunkQC = chunkQC
    }

    /// Backward-compatible decoding: older JSONL rows written before Phase 4
    /// lack the localization fields and per-chunk QC. Defaults keep them decodeable.
    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        self.algorithmVersion = try container.decodeIfPresent(Int.self, forKey: .algorithmVersion) ?? 1
        self.verdict = try container.decode(Verdict.self, forKey: .verdict)
        self.instabilityVerdict = try container.decodeIfPresent(Verdict.self, forKey: .instabilityVerdict) ?? verdict
        self.writtenOutputVerdict = try container.decodeIfPresent(Verdict.self, forKey: .writtenOutputVerdict) ?? verdict
        self.flags = try container.decode([String].self, forKey: .flags)
        self.rmsDBFS = try container.decodeIfPresent(Double.self, forKey: .rmsDBFS)
        self.dcOffset = try container.decodeIfPresent(Double.self, forKey: .dcOffset)
        self.peak = try container.decode(Double.self, forKey: .peak)
        self.clippedSamples = try container.decode(Int.self, forKey: .clippedSamples)
        self.hotSamples = try container.decode(Int.self, forKey: .hotSamples)
        self.nonFiniteSamples = try container.decode(Int.self, forKey: .nonFiniteSamples)
        self.clickEvents = try container.decode(Int.self, forKey: .clickEvents)
        self.longestSilenceMS = try container.decode(Int.self, forKey: .longestSilenceMS)
        self.durationSeconds = try container.decode(Double.self, forKey: .durationSeconds)
        self.firstNonFiniteSample = try container.decodeIfPresent(Int.self, forKey: .firstNonFiniteSample)
        self.firstClipSample = try container.decodeIfPresent(Int.self, forKey: .firstClipSample)
        self.longestSilenceStartMS = try container.decodeIfPresent(Int.self, forKey: .longestSilenceStartMS)
        self.cadence = try container.decodeIfPresent(AudioCadenceQCReport.self, forKey: .cadence)
        self.chunkQC = try container.decodeIfPresent([AudioQCChunkReport].self, forKey: .chunkQC)
    }
}

/// Reference-free audio-quality snapshot for one streaming chunk. Computed in
/// verbose mode so engineers can localize early corruption, chunk-boundary
/// clicks, or drift before the final clip is assembled. All sample indices are
/// absolute from the start of the generation.
public struct AudioQCChunkReport: Hashable, Codable, Sendable {
    public let chunkIndex: Int
    public let frameOffset: Int
    public let frameCount: Int
    public let verdict: AudioQCReport.Verdict
    public let flags: [String]
    public let rmsDBFS: Double?
    public let peak: Double
    public let clippedSamples: Int
    public let hotSamples: Int
    public let nonFiniteSamples: Int
    public let clickEvents: Int
    public let longestSilenceMS: Int
    public let firstNonFiniteSample: Int?
    public let firstClipSample: Int?
    public let longestSilenceStartMS: Int?
    public let durationSeconds: Double

    public init(
        chunkIndex: Int,
        frameOffset: Int,
        frameCount: Int,
        verdict: AudioQCReport.Verdict,
        flags: [String],
        rmsDBFS: Double?,
        peak: Double,
        clippedSamples: Int,
        hotSamples: Int,
        nonFiniteSamples: Int,
        clickEvents: Int,
        longestSilenceMS: Int,
        durationSeconds: Double,
        firstNonFiniteSample: Int? = nil,
        firstClipSample: Int? = nil,
        longestSilenceStartMS: Int? = nil
    ) {
        self.chunkIndex = chunkIndex
        self.frameOffset = frameOffset
        self.frameCount = frameCount
        self.verdict = verdict
        self.flags = flags
        self.rmsDBFS = rmsDBFS
        self.peak = peak
        self.clippedSamples = clippedSamples
        self.hotSamples = hotSamples
        self.nonFiniteSamples = nonFiniteSamples
        self.clickEvents = clickEvents
        self.longestSilenceMS = longestSilenceMS
        self.durationSeconds = durationSeconds
        self.firstNonFiniteSample = firstNonFiniteSample
        self.firstClipSample = firstClipSample
        self.longestSilenceStartMS = longestSilenceStartMS
    }
}

/// Per-chunk decode substage timing for one streaming audio chunk — a Codable,
/// persistence-safe mirror of the owned Qwen3 chunk timings plus the chunk
/// index and wall-clock arrival (ms since the generation's telemetry start clock).
/// All substage values are millisecond deltas since the previous chunk boundary.
public struct GenerationChunkTelemetry: Hashable, Codable, Sendable {
    public let chunkIndex: Int
    public let arrivalMS: Int
    /// High-resolution arrival timestamp in nanoseconds since the generation's
    /// shared telemetry clock start (v5). nil for older rows.
    public let arrivalNS: UInt64?
    public let talkerForwardMS: Double
    public let codePredictorMS: Double
    public let audioDecoderMS: Double
    public let streamStepEvalMS: Double
    /// Phase 2a split of `streamStepEvalMS`: enqueued eval work wall time.
    public let streamStepEvalEnqueueMS: Double
    /// Phase 2a split of `streamStepEvalMS`: GPU drain wait time.
    public let streamStepEvalWaitMS: Double
    public let streamStepEOSReadMS: Double
    public let audioChunkEvalMS: Double
    /// Phase 2a KV-cache diagnostic snapshot at this chunk boundary.
    public let kvCacheDiagnostics: VocelloQwen3KVCacheDiagnostics?
    /// Phase 4 per-frame Mimi decoder step breakdown for this chunk.
    public let mimiDecoderBreakdownMS: VocelloQwen3MimiDecoderTimings?

    public init(
        chunkIndex: Int,
        arrivalMS: Int,
        arrivalNS: UInt64? = nil,
        talkerForwardMS: Double,
        codePredictorMS: Double,
        audioDecoderMS: Double,
        streamStepEvalMS: Double,
        streamStepEvalEnqueueMS: Double,
        streamStepEvalWaitMS: Double,
        streamStepEOSReadMS: Double,
        audioChunkEvalMS: Double,
        kvCacheDiagnostics: VocelloQwen3KVCacheDiagnostics? = nil,
        mimiDecoderBreakdownMS: VocelloQwen3MimiDecoderTimings? = nil
    ) {
        self.chunkIndex = chunkIndex
        self.arrivalMS = arrivalMS
        self.arrivalNS = arrivalNS
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
    }

    /// Backward-compatible decoding: older JSONL rows written before Phase 2a
    /// lack `streamStepEvalEnqueueMS`, `streamStepEvalWaitMS`, and
    /// `kvCacheDiagnostics`; v5 rows add `arrivalNS`; v5+ adds
    /// `mimiDecoderBreakdownMS`. Defaults keep them decodeable.
    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        self.chunkIndex = try container.decode(Int.self, forKey: .chunkIndex)
        self.arrivalMS = try container.decode(Int.self, forKey: .arrivalMS)
        self.arrivalNS = try container.decodeIfPresent(UInt64.self, forKey: .arrivalNS)
        self.talkerForwardMS = try container.decode(Double.self, forKey: .talkerForwardMS)
        self.codePredictorMS = try container.decode(Double.self, forKey: .codePredictorMS)
        self.audioDecoderMS = try container.decode(Double.self, forKey: .audioDecoderMS)
        self.streamStepEvalMS = try container.decode(Double.self, forKey: .streamStepEvalMS)
        self.streamStepEvalEnqueueMS = try container.decodeIfPresent(Double.self, forKey: .streamStepEvalEnqueueMS) ?? 0
        self.streamStepEvalWaitMS = try container.decodeIfPresent(Double.self, forKey: .streamStepEvalWaitMS) ?? 0
        self.streamStepEOSReadMS = try container.decode(Double.self, forKey: .streamStepEOSReadMS)
        self.audioChunkEvalMS = try container.decode(Double.self, forKey: .audioChunkEvalMS)
        self.kvCacheDiagnostics = try container.decodeIfPresent(
            VocelloQwen3KVCacheDiagnostics.self,
            forKey: .kvCacheDiagnostics
        )
        self.mimiDecoderBreakdownMS = try container.decodeIfPresent(
            VocelloQwen3MimiDecoderTimings.self,
            forKey: .mimiDecoderBreakdownMS
        )
    }
}

/// The unified per-generation record produced by `GenerationTelemetryMerger`,
/// joining each layer's row under one `generationID`.
public struct MergedGenerationTelemetry: Hashable, Codable, Sendable {
    public static let currentSchemaVersion = 2

    public let schemaVersion: Int
    public let generationID: String
    public let recordedAt: String
    public let app: GenerationTelemetryRecord?
    public let engineService: GenerationTelemetryRecord?
    public let engine: GenerationTelemetryRecord?
    /// Explicit completeness prevents a timed-out partial merge from looking like
    /// authoritative joined evidence. The macOS merger requires all three layers.
    public let requiredLayers: [GenerationTelemetryRecord.Layer]
    public let missingLayers: [GenerationTelemetryRecord.Layer]
    public let complete: Bool

    public init(
        generationID: String,
        recordedAt: String,
        app: GenerationTelemetryRecord?,
        engineService: GenerationTelemetryRecord?,
        engine: GenerationTelemetryRecord?,
        requiredLayers: [GenerationTelemetryRecord.Layer] = [.app, .engineService, .engine],
        schemaVersion: Int = MergedGenerationTelemetry.currentSchemaVersion
    ) {
        self.schemaVersion = schemaVersion
        self.generationID = generationID
        self.recordedAt = recordedAt
        self.app = app
        self.engineService = engineService
        self.engine = engine
        self.requiredLayers = requiredLayers
        let presentLayers = Self.presentLayers(app: app, engineService: engineService, engine: engine)
        self.missingLayers = requiredLayers.filter { !presentLayers.contains($0) }
        self.complete = missingLayers.isEmpty
    }

    private enum CodingKeys: String, CodingKey {
        case schemaVersion
        case generationID
        case recordedAt
        case app
        case engineService
        case engine
        case requiredLayers
        case missingLayers
        case complete
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        self.schemaVersion = try container.decodeIfPresent(Int.self, forKey: .schemaVersion) ?? 1
        self.generationID = try container.decode(String.self, forKey: .generationID)
        self.recordedAt = try container.decode(String.self, forKey: .recordedAt)
        self.app = try container.decodeIfPresent(GenerationTelemetryRecord.self, forKey: .app)
        self.engineService = try container.decodeIfPresent(GenerationTelemetryRecord.self, forKey: .engineService)
        self.engine = try container.decodeIfPresent(GenerationTelemetryRecord.self, forKey: .engine)
        self.requiredLayers = try container.decodeIfPresent(
            [GenerationTelemetryRecord.Layer].self,
            forKey: .requiredLayers
        ) ?? [.app, .engineService, .engine]
        let presentLayers = Self.presentLayers(app: app, engineService: engineService, engine: engine)
        self.missingLayers = try container.decodeIfPresent(
            [GenerationTelemetryRecord.Layer].self,
            forKey: .missingLayers
        ) ?? requiredLayers.filter { !presentLayers.contains($0) }
        self.complete = try container.decodeIfPresent(Bool.self, forKey: .complete)
            ?? missingLayers.isEmpty
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(schemaVersion, forKey: .schemaVersion)
        try container.encode(generationID, forKey: .generationID)
        try container.encode(recordedAt, forKey: .recordedAt)
        try container.encodeIfPresent(app, forKey: .app)
        try container.encodeIfPresent(engineService, forKey: .engineService)
        try container.encodeIfPresent(engine, forKey: .engine)
        try container.encode(requiredLayers, forKey: .requiredLayers)
        try container.encode(missingLayers, forKey: .missingLayers)
        try container.encode(complete, forKey: .complete)
    }

    private static func presentLayers(
        app: GenerationTelemetryRecord?,
        engineService: GenerationTelemetryRecord?,
        engine: GenerationTelemetryRecord?
    ) -> Set<GenerationTelemetryRecord.Layer> {
        var layers: Set<GenerationTelemetryRecord.Layer> = []
        if app != nil { layers.insert(.app) }
        if engineService != nil { layers.insert(.engineService) }
        if engine != nil { layers.insert(.engine) }
        return layers
    }
}
