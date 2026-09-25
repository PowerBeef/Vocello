import Foundation

/// Privacy-safe, typed streaming evidence for the actor/session convergence.
///
/// This is the complete schema-v9 contract. The shipping schema-v8 JSONL envelope
/// carries a nested partial transition projection until every producer can
/// populate this complete document without inferred fields.
public struct GenerationStreamingTelemetryV9: Hashable, Codable, Sendable {
    public static let currentSchemaVersion = 9
    public static let maximumChunkCount = 4_096
    public static let maximumTransportObservationCount = 4_096
    public static let maximumFrontendEventCount = 256

    public let schemaVersion: Int
    public let generationID: UUID
    public let identities: GenerationStreamingIdentityV9
    public let terminals: GenerationTerminalTimelineV9
    public let frameFlow: CodecFrameFlowV9
    public let audioChannel: AudioChannelSummaryV9
    public let chunks: [StreamingChunkRangeV9]
    public let interarrival: ChunkInterarrivalStatisticsV9
    public let transport: XPCTransportSummaryV9?
    public let frontend: FrontendStreamingSummaryV9?

    public init(
        generationID: UUID,
        identities: GenerationStreamingIdentityV9,
        terminals: GenerationTerminalTimelineV9,
        frameFlow: CodecFrameFlowV9,
        audioChannel: AudioChannelSummaryV9,
        chunks: [StreamingChunkRangeV9],
        interarrival: ChunkInterarrivalStatisticsV9? = nil,
        transport: XPCTransportSummaryV9? = nil,
        frontend: FrontendStreamingSummaryV9? = nil,
        schemaVersion: Int = Self.currentSchemaVersion
    ) throws {
        self.schemaVersion = schemaVersion
        self.generationID = generationID
        self.identities = identities
        self.terminals = terminals
        self.frameFlow = frameFlow
        self.audioChannel = audioChannel
        self.chunks = chunks
        self.interarrival = interarrival ?? ChunkInterarrivalStatisticsV9(materializationTimesNS: chunks.map(\.materializedAtNS))
        self.transport = transport
        self.frontend = frontend
        try validate()
    }

    public func validate() throws {
        guard schemaVersion == Self.currentSchemaVersion else {
            throw TelemetryV9ValidationError.unsupportedSchema(schemaVersion)
        }
        guard chunks.count <= Self.maximumChunkCount else {
            throw TelemetryV9ValidationError.collectionLimitExceeded("chunks")
        }
        try identities.validate()
        try terminals.validate()
        try frameFlow.validate()
        try audioChannel.validate()

        var expectedCodecStartFrame: UInt64 = 0
        var expectedAudioStartFrame: UInt64 = 0
        var materializedCodecFrames: UInt64 = 0
        var materializedAudioFrames: UInt64 = 0
        var writtenAudioFrames: UInt64 = 0
        var previewPublishedAudioFrames: UInt64 = 0
        var previousMaterializedAtNS: UInt64?
        for (expectedIndex, chunk) in chunks.enumerated() {
            try chunk.validate(
                expectedIndex: expectedIndex,
                expectedCodecStartFrame: expectedCodecStartFrame,
                expectedAudioStartFrame: expectedAudioStartFrame
            )
            if let previousMaterializedAtNS, chunk.materializedAtNS < previousMaterializedAtNS {
                throw TelemetryV9ValidationError.invalidOrdering("chunk-interarrival")
            }
            previousMaterializedAtNS = chunk.materializedAtNS
            expectedCodecStartFrame = chunk.codecEndFrameExclusive
            expectedAudioStartFrame = chunk.audioEndFrameExclusive
            materializedCodecFrames += chunk.codecFrameCount
            materializedAudioFrames += chunk.audioFrameCount
            if chunk.writtenAtNS != nil { writtenAudioFrames += chunk.audioFrameCount }
            if chunk.previewPublishedAtNS != nil {
                previewPublishedAudioFrames += chunk.audioFrameCount
            }
        }
        guard frameFlow.codecFramesMaterialized == materializedCodecFrames else {
            throw TelemetryV9ValidationError.inconsistentFrameCount("codecFramesMaterialized")
        }
        guard frameFlow.audioFramesMaterialized == materializedAudioFrames else {
            throw TelemetryV9ValidationError.inconsistentFrameCount("audioFramesMaterialized")
        }
        guard frameFlow.audioFramesWritten == writtenAudioFrames else {
            throw TelemetryV9ValidationError.inconsistentFrameCount("audioFramesWritten")
        }
        guard frameFlow.audioFramesPreviewPublished == previewPublishedAudioFrames else {
            throw TelemetryV9ValidationError.inconsistentFrameCount("audioFramesPreviewPublished")
        }
        if terminals.productOutcome == .completed {
            guard terminals.modelTerminalAtNS != nil,
                  terminals.productTerminalAtNS != nil,
                  terminals.modelOutcome == .eos,
                  writtenAudioFrames == materializedAudioFrames else {
                throw TelemetryV9ValidationError.incompleteCompletedGeneration
            }
        }

        let derivedInterarrival = ChunkInterarrivalStatisticsV9(
            materializationTimesNS: chunks.map(\.materializedAtNS)
        )
        guard interarrival == derivedInterarrival else {
            throw TelemetryV9ValidationError.inconsistentInterarrivalStatistics
        }
        if let transport {
            guard transport.observedSequences.count <= Self.maximumTransportObservationCount else {
                throw TelemetryV9ValidationError.collectionLimitExceeded("transport.observedSequences")
            }
            try transport.validate()
        }
        if let frontend {
            guard frontend.events.count <= Self.maximumFrontendEventCount,
                  frontend.previewQueueDepth.count <= Self.maximumFrontendEventCount else {
                throw TelemetryV9ValidationError.collectionLimitExceeded("frontend")
            }
            try frontend.validate()
        }
    }

    private enum CodingKeys: String, CodingKey {
        case schemaVersion
        case generationID
        case identities
        case terminals
        case frameFlow
        case audioChannel
        case chunks
        case interarrival
        case transport
        case frontend
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(
            generationID: values.decode(UUID.self, forKey: .generationID),
            identities: values.decode(GenerationStreamingIdentityV9.self, forKey: .identities),
            terminals: values.decode(GenerationTerminalTimelineV9.self, forKey: .terminals),
            frameFlow: values.decode(CodecFrameFlowV9.self, forKey: .frameFlow),
            audioChannel: values.decode(AudioChannelSummaryV9.self, forKey: .audioChannel),
            chunks: values.decode([StreamingChunkRangeV9].self, forKey: .chunks),
            interarrival: values.decode(ChunkInterarrivalStatisticsV9.self, forKey: .interarrival),
            transport: values.decodeIfPresent(XPCTransportSummaryV9.self, forKey: .transport),
            frontend: values.decodeIfPresent(FrontendStreamingSummaryV9.self, forKey: .frontend),
            schemaVersion: values.decode(Int.self, forKey: .schemaVersion)
        )
    }

    public func encode(to encoder: Encoder) throws {
        var values = encoder.container(keyedBy: CodingKeys.self)
        try values.encode(schemaVersion, forKey: .schemaVersion)
        try values.encode(generationID, forKey: .generationID)
        try values.encode(identities, forKey: .identities)
        try values.encode(terminals, forKey: .terminals)
        try values.encode(frameFlow, forKey: .frameFlow)
        try values.encode(audioChannel, forKey: .audioChannel)
        try values.encode(chunks, forKey: .chunks)
        try values.encode(interarrival, forKey: .interarrival)
        try values.encodeIfPresent(transport, forKey: .transport)
        try values.encodeIfPresent(frontend, forKey: .frontend)
    }
}

public enum TelemetryV9ValidationError: Error, Equatable, Sendable {
    case unsupportedSchema(Int)
    case invalidDigest(String)
    case invalidVersion(String)
    case invalidOrdering(String)
    case invalidRange(String)
    case invalidCapacity
    case inconsistentFrameCount(String)
    case inconsistentInterarrivalStatistics
    case inconsistentTransportSummary
    case incompleteCompletedGeneration
    case incompleteRenderObservation
    case collectionLimitExceeded(String)
    case invalidCompatibilityIdentifier
}

/// A lowercase SHA-256 digest. The wrapper prevents paths, user text, URLs, or
/// arbitrary labels from entering identity fields that are safe to persist.
public struct TelemetrySHA256Digest: Hashable, Codable, Sendable {
    public let rawValue: String

    public init(rawValue: String) throws {
        guard rawValue.utf8.count == 64,
              rawValue.utf8.allSatisfy({ byte in
                  (48...57).contains(byte) || (97...102).contains(byte)
              }) else {
            throw TelemetryV9ValidationError.invalidDigest("sha256-lowercase-hex")
        }
        self.rawValue = rawValue
    }

    public init(from decoder: Decoder) throws {
        try self.init(rawValue: decoder.singleValueContainer().decode(String.self))
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        try container.encode(rawValue)
    }
}

public struct VersionedTelemetryDigestV9: Hashable, Codable, Sendable {
    public let version: Int
    public let digest: TelemetrySHA256Digest

    public init(version: Int, digest: TelemetrySHA256Digest) throws {
        guard version > 0 else {
            throw TelemetryV9ValidationError.invalidVersion("policy")
        }
        self.version = version
        self.digest = digest
    }
}

public struct GenerationStreamingIdentityV9: Hashable, Codable, Sendable {
    public let plan: VersionedTelemetryDigestV9
    public let sampling: VersionedTelemetryDigestV9
    public let chunk: VersionedTelemetryDigestV9
    public let memory: VersionedTelemetryDigestV9
    public let session: VersionedTelemetryDigestV9
    public let outputAdapter: VersionedTelemetryDigestV9
    public let quality: VersionedTelemetryDigestV9

    public init(
        plan: VersionedTelemetryDigestV9,
        sampling: VersionedTelemetryDigestV9,
        chunk: VersionedTelemetryDigestV9,
        memory: VersionedTelemetryDigestV9,
        session: VersionedTelemetryDigestV9,
        outputAdapter: VersionedTelemetryDigestV9,
        quality: VersionedTelemetryDigestV9
    ) {
        self.plan = plan
        self.sampling = sampling
        self.chunk = chunk
        self.memory = memory
        self.session = session
        self.outputAdapter = outputAdapter
        self.quality = quality
    }

    func validate() throws {
        let values = [plan, sampling, chunk, memory, session, outputAdapter, quality]
        guard values.allSatisfy({ $0.version > 0 }) else {
            throw TelemetryV9ValidationError.invalidVersion("identity")
        }
    }
}

public enum ModelTerminalOutcomeV9: String, Hashable, Codable, Sendable {
    case eos
    case tokenLimit
    case cancelled
    case failed
}

public enum ProductTerminalOutcomeV9: String, Hashable, Codable, Sendable {
    case completed
    case cancelled
    case failed
    case aborted
}

public struct GenerationTerminalTimelineV9: Hashable, Codable, Sendable {
    public let modelTerminalAtNS: UInt64?
    public let productTerminalAtNS: UInt64?
    public let modelOutcome: ModelTerminalOutcomeV9?
    public let productOutcome: ProductTerminalOutcomeV9?

    public init(
        modelTerminalAtNS: UInt64? = nil,
        productTerminalAtNS: UInt64? = nil,
        modelOutcome: ModelTerminalOutcomeV9? = nil,
        productOutcome: ProductTerminalOutcomeV9? = nil
    ) {
        self.modelTerminalAtNS = modelTerminalAtNS
        self.productTerminalAtNS = productTerminalAtNS
        self.modelOutcome = modelOutcome
        self.productOutcome = productOutcome
    }

    func validate() throws {
        guard (modelTerminalAtNS == nil) == (modelOutcome == nil),
              (productTerminalAtNS == nil) == (productOutcome == nil) else {
            throw TelemetryV9ValidationError.invalidOrdering("terminal-presence")
        }
        if let modelTerminalAtNS, let productTerminalAtNS,
           productTerminalAtNS < modelTerminalAtNS {
            throw TelemetryV9ValidationError.invalidOrdering("model-product-terminal")
        }
    }
}

public struct CodecFrameFlowV9: Hashable, Codable, Sendable {
    public let codecFramesGenerated: UInt64
    public let codecFramesMaterialized: UInt64
    public let audioFramesMaterialized: UInt64
    public let audioFramesWritten: UInt64
    public let audioFramesPreviewPublished: UInt64

    public init(
        codecFramesGenerated: UInt64,
        codecFramesMaterialized: UInt64,
        audioFramesMaterialized: UInt64,
        audioFramesWritten: UInt64,
        audioFramesPreviewPublished: UInt64
    ) {
        self.codecFramesGenerated = codecFramesGenerated
        self.codecFramesMaterialized = codecFramesMaterialized
        self.audioFramesMaterialized = audioFramesMaterialized
        self.audioFramesWritten = audioFramesWritten
        self.audioFramesPreviewPublished = audioFramesPreviewPublished
    }

    fileprivate func validate() throws {
        guard codecFramesGenerated >= codecFramesMaterialized,
              audioFramesMaterialized >= audioFramesWritten,
              audioFramesWritten >= audioFramesPreviewPublished else {
            throw TelemetryV9ValidationError.invalidOrdering("generation-frame-flow")
        }
    }
}

public struct AudioChannelSummaryV9: Hashable, Codable, Sendable {
    public let capacityFrames: UInt64
    public let highWaterFrames: UInt64
    public let producerSuspensionNS: UInt64
    public let producerSuspensionCount: Int
    public let cancellationWakeups: Int

    public init(
        capacityFrames: UInt64,
        highWaterFrames: UInt64,
        producerSuspensionNS: UInt64,
        producerSuspensionCount: Int,
        cancellationWakeups: Int
    ) {
        self.capacityFrames = capacityFrames
        self.highWaterFrames = highWaterFrames
        self.producerSuspensionNS = producerSuspensionNS
        self.producerSuspensionCount = producerSuspensionCount
        self.cancellationWakeups = cancellationWakeups
    }

    func validate() throws {
        guard capacityFrames > 0,
              highWaterFrames <= capacityFrames,
              producerSuspensionCount >= 0,
              cancellationWakeups >= 0 else {
            throw TelemetryV9ValidationError.invalidCapacity
        }
    }
}

/// How a chunk's MLX instants (`generatedAtNS`, `mlxEvaluationEnqueuedAtNS`,
/// `mlxEnqueueDurationNS`, `mlxMaterializationDurationNS`) were obtained
/// (audit #49/#62). No producer observes MLX events: the output adapter derives
/// them from the engine's per-chunk step durations, counted back from the
/// consumer's receipt of the chunk (`materializedAtNS`). A document without a
/// provenance predates the label (output-adapter identity version 2 or older)
/// and carries the same derived values.
public enum MLXChunkInstantProvenanceV9: String, Hashable, Codable, Sendable {
    /// Counted back from summed step durations; only `materializedAtNS` was
    /// observed, and it is the consumer's clock, not an MLX event.
    case derivedFromStepDurations = "derived-from-step-durations"
}

public struct StreamingChunkRangeV9: Hashable, Codable, Sendable {
    public let index: Int
    public let codecStartFrame: UInt64
    public let codecEndFrameExclusive: UInt64
    public let audioStartFrame: UInt64
    public let audioEndFrameExclusive: UInt64
    /// Derived, not observed: see `mlxInstantProvenance`.
    public let generatedAtNS: UInt64
    /// Derived, not observed: see `mlxInstantProvenance`.
    public let mlxEvaluationEnqueuedAtNS: UInt64
    /// When the consumer (the output adapter) received the chunk: its own
    /// clock read on arrival, not an MLX completion event.
    public let materializedAtNS: UInt64
    public let writtenAtNS: UInt64?
    public let previewPublishedAtNS: UInt64?
    public let mlxEnqueueDurationNS: UInt64
    public let mlxMaterializationDurationNS: UInt64
    /// How the four MLX fields above were obtained; nil in documents written
    /// before the label existed.
    public let mlxInstantProvenance: MLXChunkInstantProvenanceV9?

    public var codecFrameCount: UInt64 { codecEndFrameExclusive - codecStartFrame }
    public var audioFrameCount: UInt64 { audioEndFrameExclusive - audioStartFrame }

    public init(
        index: Int,
        codecStartFrame: UInt64,
        codecEndFrameExclusive: UInt64,
        audioStartFrame: UInt64,
        audioEndFrameExclusive: UInt64,
        generatedAtNS: UInt64,
        mlxEvaluationEnqueuedAtNS: UInt64,
        materializedAtNS: UInt64,
        writtenAtNS: UInt64? = nil,
        previewPublishedAtNS: UInt64? = nil,
        mlxEnqueueDurationNS: UInt64,
        mlxMaterializationDurationNS: UInt64,
        mlxInstantProvenance: MLXChunkInstantProvenanceV9? = nil
    ) {
        self.index = index
        self.codecStartFrame = codecStartFrame
        self.codecEndFrameExclusive = codecEndFrameExclusive
        self.audioStartFrame = audioStartFrame
        self.audioEndFrameExclusive = audioEndFrameExclusive
        self.generatedAtNS = generatedAtNS
        self.mlxEvaluationEnqueuedAtNS = mlxEvaluationEnqueuedAtNS
        self.materializedAtNS = materializedAtNS
        self.writtenAtNS = writtenAtNS
        self.previewPublishedAtNS = previewPublishedAtNS
        self.mlxEnqueueDurationNS = mlxEnqueueDurationNS
        self.mlxMaterializationDurationNS = mlxMaterializationDurationNS
        self.mlxInstantProvenance = mlxInstantProvenance
    }

    fileprivate func validate(
        expectedIndex: Int,
        expectedCodecStartFrame: UInt64,
        expectedAudioStartFrame: UInt64
    ) throws {
        guard index == expectedIndex else {
            throw TelemetryV9ValidationError.invalidRange("chunk-index")
        }
        guard codecStartFrame == expectedCodecStartFrame,
              codecEndFrameExclusive > codecStartFrame else {
            throw TelemetryV9ValidationError.invalidRange("chunk-codec-frames")
        }
        guard audioStartFrame == expectedAudioStartFrame,
              audioEndFrameExclusive > audioStartFrame else {
            throw TelemetryV9ValidationError.invalidRange("chunk-audio-frames")
        }
        guard generatedAtNS <= mlxEvaluationEnqueuedAtNS,
              mlxEvaluationEnqueuedAtNS <= materializedAtNS else {
            throw TelemetryV9ValidationError.invalidOrdering("chunk-materialization")
        }
        guard mlxEnqueueDurationNS == mlxEvaluationEnqueuedAtNS - generatedAtNS,
              mlxMaterializationDurationNS == materializedAtNS - mlxEvaluationEnqueuedAtNS else {
            throw TelemetryV9ValidationError.invalidOrdering("chunk-mlx-durations")
        }
        if let writtenAtNS, writtenAtNS < materializedAtNS {
            throw TelemetryV9ValidationError.invalidOrdering("chunk-write")
        }
        if let previewPublishedAtNS {
            guard let writtenAtNS, previewPublishedAtNS >= writtenAtNS else {
                throw TelemetryV9ValidationError.invalidOrdering("chunk-preview")
            }
        }
    }
}

public struct ChunkInterarrivalStatisticsV9: Hashable, Codable, Sendable {
    public let sampleCount: Int
    public let minimumNS: UInt64?
    public let medianNS: UInt64?
    public let p95NS: UInt64?
    public let maximumNS: UInt64?
    public let meanNS: UInt64?

    public init(materializationTimesNS: [UInt64]) {
        let intervals = zip(materializationTimesNS.dropFirst(), materializationTimesNS).map { later, earlier in
            later >= earlier ? later - earlier : 0
        }
        let sorted = intervals.sorted()
        sampleCount = sorted.count
        minimumNS = sorted.first
        maximumNS = sorted.last
        if sorted.isEmpty {
            medianNS = nil
            p95NS = nil
            meanNS = nil
        } else {
            medianNS = sorted[(sorted.count - 1) / 2]
            p95NS = sorted[max(0, Int(ceil(Double(sorted.count) * 0.95)) - 1)]
            let total = sorted.reduce(0.0) { partial, value in partial + Double(value) }
            meanNS = UInt64(total / Double(sorted.count))
        }
    }
}

/// Transport summary recorded by the retired XPC transport. Kept so recorded v9
/// projections still decode; in-process hosts leave `transport` nil.
public struct XPCTransportSummaryV9: Hashable, Codable, Sendable {
    public let observedSequences: [UInt64]
    public let maximumBacklog: Int
    public let clientObservedGapCount: Int
    public let duplicateSequenceCount: Int
    public let reorderedSequenceCount: Int
    public let minimumSequence: UInt64?
    public let maximumSequence: UInt64?

    public init(observedSequences: [UInt64], maximumBacklog: Int) {
        self.observedSequences = observedSequences
        self.maximumBacklog = maximumBacklog
        let unique = Set(observedSequences)
        minimumSequence = unique.min()
        maximumSequence = unique.max()
        duplicateSequenceCount = observedSequences.count - unique.count
        if let minimumSequence, let maximumSequence {
            let span = maximumSequence - minimumSequence + 1
            clientObservedGapCount = span > UInt64(unique.count) ? Int(span - UInt64(unique.count)) : 0
        } else {
            clientObservedGapCount = 0
        }
        var runningMaximum: UInt64?
        var reordered = 0
        var seen = Set<UInt64>()
        for sequence in observedSequences where seen.insert(sequence).inserted {
            if let runningMaximum, sequence < runningMaximum { reordered += 1 }
            runningMaximum = max(runningMaximum ?? sequence, sequence)
        }
        reorderedSequenceCount = reordered
    }

    public func validate() throws {
        guard maximumBacklog >= 0 else {
            throw TelemetryV9ValidationError.inconsistentTransportSummary
        }
        guard self == XPCTransportSummaryV9(
            observedSequences: observedSequences,
            maximumBacklog: maximumBacklog
        ) else {
            throw TelemetryV9ValidationError.inconsistentTransportSummary
        }
    }
}

public enum RenderObservationMethodV9: String, Hashable, Codable, Sendable {
    case playerNodeRenderCallback
    case audioUnitRenderTimestamp
    case hostClockEstimate
}

public struct FrontendMilestonesV9: Hashable, Codable, Sendable {
    public let enginePreparedAtNS: UInt64?
    public let engineStartedAtNS: UInt64?
    public let playbackScheduledAtNS: UInt64?
    public let playerStartedAtNS: UInt64?
    /// An observed or estimated render instant. It is not evidence of acoustic audibility.
    public let firstRenderObservedAtNS: UInt64?
    public let firstRenderObservationMethod: RenderObservationMethodV9?
    public let firstRenderResolutionNS: UInt64?

    public init(
        enginePreparedAtNS: UInt64? = nil,
        engineStartedAtNS: UInt64? = nil,
        playbackScheduledAtNS: UInt64? = nil,
        playerStartedAtNS: UInt64? = nil,
        firstRenderObservedAtNS: UInt64? = nil,
        firstRenderObservationMethod: RenderObservationMethodV9? = nil,
        firstRenderResolutionNS: UInt64? = nil
    ) {
        self.enginePreparedAtNS = enginePreparedAtNS
        self.engineStartedAtNS = engineStartedAtNS
        self.playbackScheduledAtNS = playbackScheduledAtNS
        self.playerStartedAtNS = playerStartedAtNS
        self.firstRenderObservedAtNS = firstRenderObservedAtNS
        self.firstRenderObservationMethod = firstRenderObservationMethod
        self.firstRenderResolutionNS = firstRenderResolutionNS
    }

    fileprivate func validate() throws {
        let ordered = [enginePreparedAtNS, engineStartedAtNS, playbackScheduledAtNS, playerStartedAtNS, firstRenderObservedAtNS]
            .compactMap { $0 }
        guard zip(ordered, ordered.dropFirst()).allSatisfy({ pair in pair.0 <= pair.1 }) else {
            throw TelemetryV9ValidationError.invalidOrdering("frontend-milestones")
        }
        let renderFieldsPresent = firstRenderObservedAtNS != nil
            || firstRenderObservationMethod != nil
            || firstRenderResolutionNS != nil
        if renderFieldsPresent {
            guard firstRenderObservedAtNS != nil,
                  firstRenderObservationMethod != nil,
                  let firstRenderResolutionNS,
                  firstRenderResolutionNS > 0 else {
                throw TelemetryV9ValidationError.incompleteRenderObservation
            }
        }
    }
}

public enum AudioRouteClassV9: String, Hashable, Codable, Sendable {
    case builtInSpeaker
    case wired
    case bluetooth
    case airPlay
    case other
}

public enum FrontendAudioEventKindV9: String, Hashable, Codable, Sendable {
    case routeChanged
    case interruptionBegan
    case interruptionEnded
}

public struct FrontendAudioEventV9: Hashable, Codable, Sendable {
    public let atNS: UInt64
    public let kind: FrontendAudioEventKindV9
    public let routeClass: AudioRouteClassV9?

    public init(atNS: UInt64, kind: FrontendAudioEventKindV9, routeClass: AudioRouteClassV9? = nil) {
        self.atNS = atNS
        self.kind = kind
        self.routeClass = routeClass
    }
}

public struct PreviewQueueDepthSampleV9: Hashable, Codable, Sendable {
    public let atNS: UInt64
    public let queuedFrames: UInt64

    public init(atNS: UInt64, queuedFrames: UInt64) {
        self.atNS = atNS
        self.queuedFrames = queuedFrames
    }
}

public struct FrontendStreamingSummaryV9: Hashable, Codable, Sendable {
    public let milestones: FrontendMilestonesV9
    public let events: [FrontendAudioEventV9]
    public let previewQueueDepth: [PreviewQueueDepthSampleV9]

    public init(
        milestones: FrontendMilestonesV9,
        events: [FrontendAudioEventV9] = [],
        previewQueueDepth: [PreviewQueueDepthSampleV9] = []
    ) {
        self.milestones = milestones
        self.events = events
        self.previewQueueDepth = previewQueueDepth
    }

    public func validate() throws {
        try milestones.validate()
        guard zip(events, events.dropFirst()).allSatisfy({ pair in pair.0.atNS <= pair.1.atNS }),
              zip(previewQueueDepth, previewQueueDepth.dropFirst()).allSatisfy({ pair in pair.0.atNS <= pair.1.atNS }) else {
            throw TelemetryV9ValidationError.invalidOrdering("frontend-events")
        }
    }
}

/// Minimal v8 reader used during the v9 transition. It projects only semantics
/// v8 actually proves and explicitly marks every v9-only domain as unavailable.
public struct GenerationTelemetryV8CompatibilityProjection: Hashable, Codable, Sendable {
    public struct LegacyFrontend: Hashable, Codable, Sendable {
        public let submitToPlaybackScheduledMS: Int?

        private enum CodingKeys: String, CodingKey {
            case submitToPlaybackScheduledMS
            case submitToFirstAudibleMS
        }

        public init(from decoder: Decoder) throws {
            let values = try decoder.container(keyedBy: CodingKeys.self)
            submitToPlaybackScheduledMS = try values.decodeIfPresent(Int.self, forKey: .submitToPlaybackScheduledMS)
                ?? values.decodeIfPresent(Int.self, forKey: .submitToFirstAudibleMS)
        }

        public func encode(to encoder: Encoder) throws {
            var values = encoder.container(keyedBy: CodingKeys.self)
            try values.encodeIfPresent(submitToPlaybackScheduledMS, forKey: .submitToPlaybackScheduledMS)
        }
    }

    public struct LegacyTransportCounters: Hashable, Codable, Sendable {
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

    public struct LegacyTransport: Hashable, Codable, Sendable {
        public let counters: LegacyTransportCounters
    }

    public let schemaVersion: Int
    public let generationID: String
    public let frontendMetrics: LegacyFrontend?
    public let transportMetrics: LegacyTransport?
    public let timingsMS: [String: Int]
    public let counters: [String: Int]

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        schemaVersion = try values.decode(Int.self, forKey: .schemaVersion)
        guard schemaVersion == 8 else {
            throw TelemetryV9ValidationError.unsupportedSchema(schemaVersion)
        }
        generationID = try values.decode(String.self, forKey: .generationID)
        guard Self.isSafeCompatibilityIdentifier(generationID) else {
            throw TelemetryV9ValidationError.invalidCompatibilityIdentifier
        }
        frontendMetrics = try values.decodeIfPresent(LegacyFrontend.self, forKey: .frontendMetrics)
        transportMetrics = try values.decodeIfPresent(LegacyTransport.self, forKey: .transportMetrics)
        timingsMS = try values.decodeIfPresent([String: Int].self, forKey: .timingsMS) ?? [:]
        counters = try values.decodeIfPresent([String: Int].self, forKey: .counters) ?? [:]
    }

    public func encode(to encoder: Encoder) throws {
        var values = encoder.container(keyedBy: CodingKeys.self)
        try values.encode(schemaVersion, forKey: .schemaVersion)
        try values.encode(generationID, forKey: .generationID)
        try values.encodeIfPresent(frontendMetrics, forKey: .frontendMetrics)
        try values.encodeIfPresent(transportMetrics, forKey: .transportMetrics)
        try values.encode(timingsMS, forKey: .timingsMS)
        try values.encode(counters, forKey: .counters)
    }

    public var playbackScheduledMS: Int? {
        frontendMetrics?.submitToPlaybackScheduledMS
            ?? timingsMS["submitToPlaybackScheduledMS"]
            ?? timingsMS["submitToFirstAudibleMS"]
    }

    public var forwardedChunkCount: Int {
        transportMetrics?.counters.chunksForwarded ?? counters["chunksForwarded"] ?? 0
    }

    public var sequenceGapCount: Int {
        transportMetrics?.counters.chunkGaps ?? counters["chunkGaps"] ?? 0
    }

    public var duplicateSequenceCount: Int {
        transportMetrics?.counters.duplicateChunks ?? counters["duplicateChunks"] ?? 0
    }

    public var reorderedSequenceCount: Int {
        transportMetrics?.counters.outOfOrderChunks ?? counters["outOfOrderChunks"] ?? 0
    }

    /// v8 cannot prove v9 plan, policy, channel, exact range, materialization,
    /// product-terminal, render-observation, or route-event semantics.
    public var isCompleteV9Evidence: Bool { false }

    private enum CodingKeys: String, CodingKey {
        case schemaVersion
        case generationID
        case frontendMetrics
        case transportMetrics
        case timingsMS
        case counters
    }

    private static func isSafeCompatibilityIdentifier(_ value: String) -> Bool {
        guard !value.isEmpty, value.utf8.count <= 128 else { return false }
        return value.utf8.allSatisfy { byte in
            (48...57).contains(byte)
                || (65...90).contains(byte)
                || (97...122).contains(byte)
                || byte == 45
                || byte == 46
                || byte == 95
        }
    }
}
