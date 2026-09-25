import Foundation

/// Domains required by the eventual complete schema-v9 streaming document.
///
/// The shipping JSONL envelope remains schema v8 while benchmark-history schema
/// v2 is authoritative. New rows carry this nested v9 transition projection so
/// evidence can be added incrementally without representing unavailable
/// observations as zeroes. Session and output-adapter identities are stamped by
/// the shipping product path when available; remaining codec-exact domains stay
/// explicitly unavailable until their producers observe them.
public enum GenerationStreamingFieldV9: String, CaseIterable, Codable, Hashable, Sendable {
    case planIdentity
    case samplingIdentity
    case chunkIdentity
    case memoryIdentity
    case outputPolicyIdentity
    case qualityPolicyIdentity
    case sessionIdentity
    case outputAdapterIdentity
    case modelTerminal
    case productTerminal
    case codecFrameFlow
    case audioFrameFlow
    case audioChannel
    case exactChunkAudioRanges
    case exactChunkCodecRanges
    case chunkInterarrival
    case transportSequenceList
    case transportAggregate
    case playbackScheduled
    case firstRenderObservation
}

public enum GenerationStreamingUnavailableReasonV9: String, Codable, Hashable, Sendable {
    case producerDidNotObserve = "producer-did-not-observe"
    case actorSessionNotShipping = "actor-session-not-shipping"
    case outputAdapterNotShipping = "output-adapter-not-shipping"
    case currentTransportStoresAggregateOnly = "current-transport-stores-aggregate-only"
    case currentFrontendStoresMillisecondsOnly = "current-frontend-stores-milliseconds-only"
    case currentPlayerHasNoRenderObservation = "current-player-has-no-render-observation"
    case malformedIdentity = "malformed-identity"
    case notApplicable = "not-applicable"
}

public struct GenerationStreamingUnavailableFieldV9: Codable, Hashable, Sendable {
    public let field: GenerationStreamingFieldV9
    public let reason: GenerationStreamingUnavailableReasonV9

    public init(
        field: GenerationStreamingFieldV9,
        reason: GenerationStreamingUnavailableReasonV9
    ) {
        self.field = field
        self.reason = reason
    }
}

public struct PartialGenerationStreamingIdentityV9: Codable, Hashable, Sendable {
    public let plan: VersionedTelemetryDigestV9?
    public let sampling: VersionedTelemetryDigestV9?
    public let chunk: VersionedTelemetryDigestV9?
    public let memory: VersionedTelemetryDigestV9?
    public let outputPolicy: VersionedTelemetryDigestV9?
    public let qualityPolicy: VersionedTelemetryDigestV9?
    public let session: VersionedTelemetryDigestV9?
    public let outputAdapter: VersionedTelemetryDigestV9?
}

public enum PreviewPublicationDispositionV9: String, Codable, Hashable, Sendable {
    /// The PCM-bearing event was synchronously handed to the product sink. This
    /// does not claim that a consumer or player rendered it.
    case publishedToProductSink = "published-to-product-sink"
    case notRequested = "not-requested"
    case unavailable
}

/// Exact observations available at the current product-owned streaming loop.
/// Codec ranges remain optional until the async actor producer owns them.
public struct ShippingChunkObservationV9: Codable, Hashable, Sendable {
    public let index: Int
    public let transportSequence: UInt64
    public let codecStartFrame: UInt64?
    public let codecEndFrameExclusive: UInt64?
    public let audioStartFrame: UInt64
    public let audioEndFrameExclusive: UInt64
    public let generatedAtNS: UInt64?
    public let mlxEvaluationEnqueuedAtNS: UInt64?
    public let mlxEnqueueDurationNS: UInt64?
    public let mlxMaterializationDurationNS: UInt64?
    public let materializedAtNS: UInt64
    public let writtenAtNS: UInt64
    public let previewPublishedAtNS: UInt64?
    public let previewDisposition: PreviewPublicationDispositionV9

    public init(
        index: Int,
        transportSequence: UInt64,
        codecStartFrame: UInt64? = nil,
        codecEndFrameExclusive: UInt64? = nil,
        audioStartFrame: UInt64,
        audioEndFrameExclusive: UInt64,
        generatedAtNS: UInt64? = nil,
        mlxEvaluationEnqueuedAtNS: UInt64? = nil,
        mlxEnqueueDurationNS: UInt64? = nil,
        mlxMaterializationDurationNS: UInt64? = nil,
        materializedAtNS: UInt64,
        writtenAtNS: UInt64,
        previewPublishedAtNS: UInt64? = nil,
        previewDisposition: PreviewPublicationDispositionV9
    ) {
        self.index = index
        self.transportSequence = transportSequence
        self.codecStartFrame = codecStartFrame
        self.codecEndFrameExclusive = codecEndFrameExclusive
        self.audioStartFrame = audioStartFrame
        self.audioEndFrameExclusive = audioEndFrameExclusive
        self.generatedAtNS = generatedAtNS
        self.mlxEvaluationEnqueuedAtNS = mlxEvaluationEnqueuedAtNS
        self.mlxEnqueueDurationNS = mlxEnqueueDurationNS
        self.mlxMaterializationDurationNS = mlxMaterializationDurationNS
        self.materializedAtNS = materializedAtNS
        self.writtenAtNS = writtenAtNS
        self.previewPublishedAtNS = previewPublishedAtNS
        self.previewDisposition = previewDisposition
    }

    /// Whether MLX enqueue/materialization instants are present for a
    /// complete schema-v9 chunk range (no invented zeros). They are derived
    /// from step durations, not observed MLX events; `materializedAtNS` is the
    /// consumer's receipt of the chunk (audit #49/#62).
    public var hasExactMLXChunkInstants: Bool {
        generatedAtNS != nil
            && mlxEvaluationEnqueuedAtNS != nil
            && mlxEnqueueDurationNS != nil
            && mlxMaterializationDurationNS != nil
    }

    fileprivate func validate(expectedIndex: Int, expectedAudioStart: UInt64) throws {
        guard index == expectedIndex,
              transportSequence == UInt64(expectedIndex),
              audioStartFrame == expectedAudioStart,
              audioEndFrameExclusive > audioStartFrame else {
            throw TelemetryV9ValidationError.invalidRange("shipping-chunk-audio")
        }
        guard writtenAtNS >= materializedAtNS else {
            throw TelemetryV9ValidationError.invalidOrdering("shipping-chunk-write")
        }
        if let previewPublishedAtNS {
            guard previewDisposition == .publishedToProductSink,
                  previewPublishedAtNS >= writtenAtNS else {
                throw TelemetryV9ValidationError.invalidOrdering("shipping-chunk-preview")
            }
        } else if previewDisposition == .publishedToProductSink {
            throw TelemetryV9ValidationError.invalidOrdering("shipping-chunk-preview-presence")
        }
        if codecStartFrame == nil || codecEndFrameExclusive == nil {
            guard codecStartFrame == nil, codecEndFrameExclusive == nil else {
                throw TelemetryV9ValidationError.invalidRange("shipping-chunk-codec-presence")
            }
        } else if let codecStartFrame, let codecEndFrameExclusive {
            guard codecEndFrameExclusive > codecStartFrame else {
                throw TelemetryV9ValidationError.invalidRange("shipping-chunk-codec")
            }
        }
    }
}

public struct PartialCodecFrameFlowV9: Codable, Hashable, Sendable {
    public let codecFramesGenerated: UInt64?
    public let codecFramesMaterialized: UInt64?
    public let audioFramesMaterialized: UInt64?
    public let audioFramesWritten: UInt64?
    public let audioFramesPreviewPublished: UInt64?

    public init(
        codecFramesGenerated: UInt64?,
        codecFramesMaterialized: UInt64?,
        audioFramesMaterialized: UInt64?,
        audioFramesWritten: UInt64?,
        audioFramesPreviewPublished: UInt64?
    ) {
        self.codecFramesGenerated = codecFramesGenerated
        self.codecFramesMaterialized = codecFramesMaterialized
        self.audioFramesMaterialized = audioFramesMaterialized
        self.audioFramesWritten = audioFramesWritten
        self.audioFramesPreviewPublished = audioFramesPreviewPublished
    }
}

/// The transport row (written by the retired XPC transport; in-process hosts
/// leave it absent) retains exact aggregate counters and the first/last
/// sequence, but not the complete observed sequence list.
public struct PartialXPCTransportSummaryV9: Codable, Hashable, Sendable {
    public let chunksForwarded: Int
    public let clientObservedGapCount: Int
    public let duplicateSequenceCount: Int
    public let reorderedSequenceCount: Int
    public let firstSequence: UInt64?
    public let lastSequence: UInt64?
}

public struct PartialFrontendStreamingSummaryV9: Codable, Hashable, Sendable {
    /// Relative to submission, quantized at the legacy one-millisecond
    /// resolution. This is scheduling evidence, not acoustic audibility.
    public let playbackScheduledAtNS: UInt64?
    public let playbackScheduledResolutionNS: UInt64?
    public let firstRenderObservedAtNS: UInt64?
    public let firstRenderObservationMethod: RenderObservationMethodV9?
    public let firstRenderResolutionNS: UInt64?
}

/// Nested bridge carried by new shipping `GenerationTelemetryRecord` rows.
///
/// A complete `GenerationStreamingTelemetryV9` remains the target contract. The
/// bridge is intentionally partial and always lists absent domains, preventing
/// a missing observation from being interpreted as a measured zero.
public struct GenerationStreamingTelemetryTransitionV9: Codable, Hashable, Sendable {
    public static let currentSchemaVersion = 9

    public let schemaVersion: Int
    public let generationID: UUID
    public let identities: PartialGenerationStreamingIdentityV9
    public let terminals: GenerationTerminalTimelineV9
    public let frameFlow: PartialCodecFrameFlowV9
    public let audioChannel: AudioChannelSummaryV9?
    public let chunks: [ShippingChunkObservationV9]
    public let interarrival: ChunkInterarrivalStatisticsV9?
    public let transport: PartialXPCTransportSummaryV9?
    public let frontend: PartialFrontendStreamingSummaryV9?
    public let unavailable: [GenerationStreamingUnavailableFieldV9]

    public init(
        generationID: UUID,
        identities: PartialGenerationStreamingIdentityV9,
        terminals: GenerationTerminalTimelineV9 = GenerationTerminalTimelineV9(),
        frameFlow: PartialCodecFrameFlowV9 = PartialCodecFrameFlowV9(
            codecFramesGenerated: nil,
            codecFramesMaterialized: nil,
            audioFramesMaterialized: nil,
            audioFramesWritten: nil,
            audioFramesPreviewPublished: nil
        ),
        audioChannel: AudioChannelSummaryV9? = nil,
        chunks: [ShippingChunkObservationV9] = [],
        transport: PartialXPCTransportSummaryV9? = nil,
        frontend: PartialFrontendStreamingSummaryV9? = nil,
        unavailable: [GenerationStreamingUnavailableFieldV9],
        schemaVersion: Int = Self.currentSchemaVersion
    ) throws {
        self.schemaVersion = schemaVersion
        self.generationID = generationID
        self.identities = identities
        self.terminals = terminals
        self.frameFlow = frameFlow
        self.audioChannel = audioChannel
        self.chunks = chunks
        self.interarrival = chunks.count > 1
            ? ChunkInterarrivalStatisticsV9(materializationTimesNS: chunks.map(\.materializedAtNS))
            : nil
        self.transport = transport
        self.frontend = frontend
        self.unavailable = unavailable.sorted { $0.field.rawValue < $1.field.rawValue }
        try validate()
    }

    public func validate() throws {
        guard schemaVersion == Self.currentSchemaVersion else {
            throw TelemetryV9ValidationError.unsupportedSchema(schemaVersion)
        }
        guard chunks.count <= GenerationStreamingTelemetryV9.maximumChunkCount else {
            throw TelemetryV9ValidationError.collectionLimitExceeded("shipping-chunks")
        }
        try terminals.validate()
        try audioChannel?.validate()

        var nextAudioFrame: UInt64 = 0
        for (index, chunk) in chunks.enumerated() {
            try chunk.validate(expectedIndex: index, expectedAudioStart: nextAudioFrame)
            nextAudioFrame = chunk.audioEndFrameExclusive
        }
        guard frameFlow.audioFramesMaterialized == nil || frameFlow.audioFramesMaterialized == nextAudioFrame,
              frameFlow.audioFramesWritten == nil || frameFlow.audioFramesWritten == nextAudioFrame else {
            throw TelemetryV9ValidationError.inconsistentFrameCount("shipping-audio-frames")
        }
        let previewFrames = chunks.reduce(UInt64(0)) { total, chunk in
            chunk.previewDisposition == .publishedToProductSink
                ? total + (chunk.audioEndFrameExclusive - chunk.audioStartFrame)
                : total
        }
        guard frameFlow.audioFramesPreviewPublished == nil
                || frameFlow.audioFramesPreviewPublished == previewFrames else {
            throw TelemetryV9ValidationError.inconsistentFrameCount("shipping-preview-frames")
        }
        if let interarrival {
            guard interarrival == ChunkInterarrivalStatisticsV9(
                materializationTimesNS: chunks.map(\.materializedAtNS)
            ) else {
                throw TelemetryV9ValidationError.inconsistentInterarrivalStatistics
            }
        }

        let unavailableFields = unavailable.map(\.field)
        guard Set(unavailableFields).count == unavailableFields.count else {
            throw TelemetryV9ValidationError.invalidOrdering("duplicate-unavailable-field")
        }
    }
}

public enum GenerationStreamingTelemetryV9Bridge {
    /// Projects already-shipping typed evidence into the nested transition
    /// document. `chunkObservations` and `terminals` may be supplied by the
    /// engine collector when it owns exact instants; other layers remain
    /// explicit partial projections.
    public static func make(
        generationID: String,
        layer: GenerationTelemetryRecord.Layer,
        notes: [String: String],
        frontend: FrontendGenerationMetrics?,
        transport: EngineTransportMetrics?,
        terminals: GenerationTerminalTimelineV9? = nil,
        chunkObservations: [ShippingChunkObservationV9] = [],
        audioChannel: AudioChannelSummaryV9? = nil
    ) -> GenerationStreamingTelemetryTransitionV9? {
        guard let generationUUID = UUID(uuidString: generationID) else { return nil }

        var unavailable: [GenerationStreamingUnavailableFieldV9] = []
        func identity(
            digestKey: String,
            versionKey: String,
            field: GenerationStreamingFieldV9
        ) -> VersionedTelemetryDigestV9? {
            guard let rawDigest = notes[digestKey],
                  let version = notes[versionKey].flatMap(Int.init), version > 0 else {
                unavailable.append(.init(field: field, reason: .producerDidNotObserve))
                return nil
            }
            do {
                return try VersionedTelemetryDigestV9(
                    version: version,
                    digest: TelemetrySHA256Digest(rawValue: rawDigest)
                )
            } catch {
                unavailable.append(.init(field: field, reason: .malformedIdentity))
                return nil
            }
        }

        let identities = PartialGenerationStreamingIdentityV9(
            plan: identity(
                digestKey: "streamingV9PlanDigest",
                versionKey: "streamingV9PlanVersion",
                field: .planIdentity
            ),
            sampling: identity(
                digestKey: "streamingV9SamplingDigest",
                versionKey: "streamingV9SamplingVersion",
                field: .samplingIdentity
            ),
            chunk: identity(
                digestKey: "streamingV9ChunkDigest",
                versionKey: "streamingV9ChunkVersion",
                field: .chunkIdentity
            ),
            memory: identity(
                digestKey: "streamingV9MemoryDigest",
                versionKey: "streamingV9MemoryVersion",
                field: .memoryIdentity
            ),
            outputPolicy: identity(
                digestKey: "streamingV9OutputPolicyDigest",
                versionKey: "streamingV9OutputPolicyVersion",
                field: .outputPolicyIdentity
            ),
            qualityPolicy: identity(
                digestKey: "streamingV9QualityPolicyDigest",
                versionKey: "streamingV9QualityPolicyVersion",
                field: .qualityPolicyIdentity
            ),
            session: identity(
                digestKey: "streamingV9SessionDigest",
                versionKey: "streamingV9SessionVersion",
                field: .sessionIdentity
            ),
            outputAdapter: identity(
                digestKey: "streamingV9OutputAdapterDigest",
                versionKey: "streamingV9OutputAdapterVersion",
                field: .outputAdapterIdentity
            )
        )

        let terminalTimeline = terminals ?? GenerationTerminalTimelineV9()
        if terminalTimeline.modelTerminalAtNS == nil {
            unavailable.append(.init(field: .modelTerminal, reason: .producerDidNotObserve))
        }
        if terminalTimeline.productTerminalAtNS == nil {
            unavailable.append(.init(field: .productTerminal, reason: .producerDidNotObserve))
        }

        let allAudioWritten = !chunkObservations.isEmpty
            && chunkObservations.allSatisfy { $0.writtenAtNS >= $0.materializedAtNS }
        let audioFrames = chunkObservations.last?.audioEndFrameExclusive
        let previewFrames: UInt64? = chunkObservations.isEmpty ? nil : chunkObservations.reduce(0) { total, chunk in
            chunk.previewDisposition == .publishedToProductSink
                ? total + chunk.audioEndFrameExclusive - chunk.audioStartFrame
                : total
        }
        let hasExactCodecRanges = !chunkObservations.isEmpty
            && chunkObservations.allSatisfy {
                $0.codecStartFrame != nil && $0.codecEndFrameExclusive != nil
            }
        let codecFrames: UInt64? = {
            guard hasExactCodecRanges else { return nil }
            // Contiguous codec ranges start at 0 and end at the last exclusive bound.
            guard chunkObservations.first?.codecStartFrame == 0 else { return nil }
            var expectedStart: UInt64 = 0
            for chunk in chunkObservations {
                guard let start = chunk.codecStartFrame,
                      let end = chunk.codecEndFrameExclusive,
                      start == expectedStart,
                      end > start else {
                    return nil
                }
                expectedStart = end
            }
            return expectedStart
        }()
        let frameFlow = PartialCodecFrameFlowV9(
            codecFramesGenerated: codecFrames,
            codecFramesMaterialized: codecFrames,
            audioFramesMaterialized: audioFrames,
            audioFramesWritten: allAudioWritten ? audioFrames : nil,
            audioFramesPreviewPublished: previewFrames
        )
        if codecFrames == nil {
            unavailable.append(.init(field: .codecFrameFlow, reason: .producerDidNotObserve))
        }
        if chunkObservations.isEmpty {
            unavailable.append(.init(field: .audioFrameFlow, reason: .producerDidNotObserve))
            unavailable.append(.init(field: .exactChunkAudioRanges, reason: .producerDidNotObserve))
            unavailable.append(.init(field: .chunkInterarrival, reason: .producerDidNotObserve))
        }
        if !hasExactCodecRanges || codecFrames == nil {
            unavailable.append(.init(field: .exactChunkCodecRanges, reason: .producerDidNotObserve))
        }
        if audioChannel == nil {
            unavailable.append(.init(field: .audioChannel, reason: .producerDidNotObserve))
        }

        let transportProjection: PartialXPCTransportSummaryV9? = transport.map {
            PartialXPCTransportSummaryV9(
                chunksForwarded: $0.counters.chunksForwarded,
                clientObservedGapCount: $0.counters.chunkGaps,
                duplicateSequenceCount: $0.counters.duplicateChunks,
                reorderedSequenceCount: $0.counters.outOfOrderChunks,
                firstSequence: $0.firstChunkSequence,
                lastSequence: $0.lastChunkSequence
            )
        }
        if transportProjection == nil {
            unavailable.append(.init(
                field: .transportAggregate,
                reason: layer == .engineService ? .producerDidNotObserve : .notApplicable
            ))
        }
        unavailable.append(.init(
            field: .transportSequenceList,
            reason: layer == .engineService ? .currentTransportStoresAggregateOnly : .notApplicable
        ))

        let scheduledMS = frontend?.submitToPlaybackScheduledMS
        let frontendProjection: PartialFrontendStreamingSummaryV9? = frontend.map { _ in
            PartialFrontendStreamingSummaryV9(
                playbackScheduledAtNS: scheduledMS.map { UInt64(max(0, $0)) * 1_000_000 },
                playbackScheduledResolutionNS: scheduledMS == nil ? nil : 1_000_000,
                firstRenderObservedAtNS: nil,
                firstRenderObservationMethod: nil,
                firstRenderResolutionNS: nil
            )
        }
        if scheduledMS == nil {
            unavailable.append(.init(
                field: .playbackScheduled,
                reason: layer == .app ? .producerDidNotObserve : .notApplicable
            ))
        }
        unavailable.append(.init(
            field: .firstRenderObservation,
            reason: layer == .app ? .currentPlayerHasNoRenderObservation : .notApplicable
        ))

        return try? GenerationStreamingTelemetryTransitionV9(
            generationID: generationUUID,
            identities: identities,
            terminals: terminalTimeline,
            frameFlow: frameFlow,
            audioChannel: audioChannel,
            chunks: chunkObservations,
            transport: transportProjection,
            frontend: frontendProjection,
            unavailable: unavailable
        )
    }
}
