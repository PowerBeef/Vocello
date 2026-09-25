import Foundation
@testable import QwenVoiceCore
import XCTest

final class GenerationStreamingTelemetryV9Tests: XCTestCase {
    func testV9RoundTripPreservesTypedStreamingEvidence() throws {
        let record = try makeRecord()
        let data = try JSONEncoder().encode(record)
        let decoded = try JSONDecoder().decode(GenerationStreamingTelemetryV9.self, from: data)

        XCTAssertEqual(decoded, record)
        XCTAssertEqual(decoded.schemaVersion, 9)
        XCTAssertEqual(decoded.frameFlow.codecFramesMaterialized, 14)
        XCTAssertEqual(decoded.frameFlow.audioFramesPreviewPublished, 26_880)
        XCTAssertEqual(decoded.audioChannel.highWaterFrames, 13_440)
        XCTAssertEqual(decoded.interarrival.sampleCount, 1)
        XCTAssertEqual(decoded.transport?.maximumBacklog, 2)
        XCTAssertEqual(decoded.frontend?.milestones.firstRenderObservationMethod, .playerNodeRenderCallback)

        let json = String(decoding: data, as: UTF8.self)
        XCTAssertFalse(json.localizedCaseInsensitiveContains("audible"))
        XCTAssertFalse(json.contains("private.wav"))
    }

    func testChunkRangesAndTimestampsMustBeContiguousAndMonotonic() throws {
        let invalid = StreamingChunkRangeV9(
            index: 1,
            codecStartFrame: 8,
            codecEndFrameExclusive: 16,
            audioStartFrame: 8,
            audioEndFrameExclusive: 16,
            generatedAtNS: 50,
            mlxEvaluationEnqueuedAtNS: 40,
            materializedAtNS: 60,
            writtenAtNS: 70,
            mlxEnqueueDurationNS: 1,
            mlxMaterializationDurationNS: 10
        )

        XCTAssertThrowsError(try makeRecord(chunks: [invalid])) { error in
            XCTAssertEqual(error as? TelemetryV9ValidationError, .invalidRange("chunk-index"))
        }
    }

    func testChunkInterarrivalMustRemainMonotonic() throws {
        let chunks = [
            chunk(index: 0, start: 0, end: 7, audioStart: 0, audioEnd: 13_440, generated: 10, materialized: 50, written: 60),
            chunk(index: 1, start: 7, end: 14, audioStart: 13_440, audioEnd: 26_880, generated: 20, materialized: 40, written: 70),
        ]
        XCTAssertThrowsError(try makeRecord(chunks: chunks)) { error in
            XCTAssertEqual(error as? TelemetryV9ValidationError, .invalidOrdering("chunk-interarrival"))
        }
    }

    func testCompletedGenerationRequiresWrittenFramesAndBothTerminals() throws {
        let chunks = [chunk(index: 0, start: 0, end: 7, generated: 10, materialized: 30, written: 40)]
        XCTAssertThrowsError(
            try makeRecord(
                terminals: GenerationTerminalTimelineV9(
                    modelTerminalAtNS: 100,
                    productTerminalAtNS: 120,
                    modelOutcome: .eos,
                    productOutcome: .completed
                ),
                frameFlow: CodecFrameFlowV9(
                    codecFramesGenerated: 7,
                    codecFramesMaterialized: 7,
                    audioFramesMaterialized: 7,
                    audioFramesWritten: 6,
                    audioFramesPreviewPublished: 6
                ),
                chunks: chunks
            )
        ) { error in
            XCTAssertEqual(
                error as? TelemetryV9ValidationError,
                .inconsistentFrameCount("audioFramesWritten")
            )
        }
    }

    func testTokenLimitCannotBecomeCompletedProductEvidence() throws {
        XCTAssertThrowsError(try makeRecord(
            terminals: GenerationTerminalTimelineV9(
                modelTerminalAtNS: 100,
                productTerminalAtNS: 120,
                modelOutcome: .tokenLimit,
                productOutcome: .completed
            )
        )) { error in
            XCTAssertEqual(
                error as? TelemetryV9ValidationError,
                .incompleteCompletedGeneration
            )
        }
    }

    func testInterarrivalStatisticsRejectDrift() throws {
        let record = try makeRecord()
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(record)) as? [String: Any])
        var modified = object
        var interarrival = try XCTUnwrap(modified["interarrival"] as? [String: Any])
        interarrival["maximumNS"] = 999
        modified["interarrival"] = interarrival
        let data = try JSONSerialization.data(withJSONObject: modified, options: [.sortedKeys])
        XCTAssertThrowsError(try JSONDecoder().decode(GenerationStreamingTelemetryV9.self, from: data)) { error in
            XCTAssertEqual(error as? TelemetryV9ValidationError, .inconsistentInterarrivalStatistics)
        }
    }

    func testTransportSummaryDetectsGapsDuplicatesAndReordering() throws {
        let transport = XPCTransportSummaryV9(
            observedSequences: [10, 11, 11, 14, 13, 15],
            maximumBacklog: 4
        )
        try transport.validate()

        XCTAssertEqual(transport.minimumSequence, 10)
        XCTAssertEqual(transport.maximumSequence, 15)
        XCTAssertEqual(transport.clientObservedGapCount, 1)
        XCTAssertEqual(transport.duplicateSequenceCount, 1)
        XCTAssertEqual(transport.reorderedSequenceCount, 1)
    }

    func testDigestRejectsPathsURLsUppercaseAndNonSHAValues() {
        for value in [
            "private/fixture.wav",
            ["https", "://", "example.invalid/model"].joined(),
            String(repeating: "A", count: 64),
            String(repeating: "g", count: 64),
            "short",
        ] {
            XCTAssertThrowsError(try TelemetrySHA256Digest(rawValue: value))
        }
        XCTAssertNoThrow(try TelemetrySHA256Digest(rawValue: String(repeating: "a", count: 64)))
    }

    func testV8ProjectionRetainsOnlyProvenCompatibilityFields() throws {
        let json = #"""
        {
          "schemaVersion": 8,
          "generationID": "compatibility-v8",
          "frontendMetrics": {"submitToPlaybackScheduledMS": 42},
          "transportMetrics": {
            "counters": {
              "chunksForwarded": 3,
              "chunkGaps": 1,
              "duplicateChunks": 2,
              "outOfOrderChunks": 1
            }
          },
          "timingsMS": {},
          "counters": {},
          "notes": {"unsafeIgnoredValue": "private/fixture.wav"}
        }
        """#
        let projected = try JSONDecoder().decode(
            GenerationTelemetryV8CompatibilityProjection.self,
            from: Data(json.utf8)
        )

        XCTAssertEqual(projected.playbackScheduledMS, 42)
        XCTAssertEqual(projected.forwardedChunkCount, 3)
        XCTAssertEqual(projected.sequenceGapCount, 1)
        XCTAssertEqual(projected.duplicateSequenceCount, 2)
        XCTAssertEqual(projected.reorderedSequenceCount, 1)
        XCTAssertFalse(projected.isCompleteV9Evidence)
        let encoded = String(decoding: try JSONEncoder().encode(projected), as: UTF8.self)
        XCTAssertFalse(encoded.contains("unsafeIgnoredValue"))
        XCTAssertFalse(encoded.contains("private/fixture.wav"))
    }

    func testV8ProjectionRejectsWrongSchemaAndUnsafeIdentifier() throws {
        let wrongSchema = #"{"schemaVersion":7,"generationID":"safe","timingsMS":{},"counters":{}}"#
        XCTAssertThrowsError(
            try JSONDecoder().decode(
                GenerationTelemetryV8CompatibilityProjection.self,
                from: Data(wrongSchema.utf8)
            )
        )

        let unsafeID = #"{"schemaVersion":8,"generationID":"unsafe/id","timingsMS":{},"counters":{}}"#
        XCTAssertThrowsError(
            try JSONDecoder().decode(
                GenerationTelemetryV8CompatibilityProjection.self,
                from: Data(unsafeID.utf8)
            )
        ) { error in
            XCTAssertEqual(error as? TelemetryV9ValidationError, .invalidCompatibilityIdentifier)
        }
    }

    func testRenderObservationRequiresMethodAndResolutionAndNeverClaimsAudibility() throws {
        let incomplete = FrontendStreamingSummaryV9(
            milestones: FrontendMilestonesV9(firstRenderObservedAtNS: 100),
            events: [],
            previewQueueDepth: []
        )
        XCTAssertThrowsError(try incomplete.validate()) { error in
            XCTAssertEqual(error as? TelemetryV9ValidationError, .incompleteRenderObservation)
        }

        let encoded = String(decoding: try JSONEncoder().encode(try makeRecord()), as: UTF8.self)
        XCTAssertFalse(encoded.localizedCaseInsensitiveContains("audible"))
    }

    func testShippingV8EnvelopeCarriesExplicitV9TransitionAvailability() throws {
        let digest = String(repeating: "a", count: 64)
        let record = GenerationTelemetryRecord(
            generationID: "A57D9599-E428-4D74-A7DE-69A6BD801F54",
            layer: .engine,
            recordedAt: "2026-07-17T00:00:00Z",
            notes: [
                "streamingV9PlanDigest": digest,
                "streamingV9PlanVersion": "1",
                "streamingV9SamplingDigest": digest,
                "streamingV9SamplingVersion": "2",
                "streamingV9ChunkDigest": digest,
                "streamingV9ChunkVersion": "1",
                "streamingV9MemoryDigest": digest,
                "streamingV9MemoryVersion": "1",
                "streamingV9OutputPolicyDigest": digest,
                "streamingV9OutputPolicyVersion": "1",
                "streamingV9QualityPolicyDigest": digest,
                "streamingV9QualityPolicyVersion": "1",
            ]
        )

        XCTAssertEqual(record.schemaVersion, 8)
        let transition = try XCTUnwrap(record.streamingTelemetryV9)
        XCTAssertEqual(transition.schemaVersion, 9)
        XCTAssertEqual(transition.identities.sampling?.version, 2)
        XCTAssertTrue(transition.unavailable.contains {
            $0.field == .audioChannel && $0.reason == .producerDidNotObserve
        })
        XCTAssertTrue(transition.unavailable.contains {
            $0.field == .productTerminal && $0.reason == .producerDidNotObserve
        })
        XCTAssertNil(transition.frameFlow.audioFramesWritten)
    }

    func testShippingIdentityNotesPopulateSessionAndAdapterDigests() throws {
        var notes = GenerationStreamingTelemetryV9Publication.shippingIdentityNotes
        notes["streamingV9SamplingDigest"] = String(repeating: "b", count: 64)
        notes["streamingV9SamplingVersion"] = "2"
        let transition = try XCTUnwrap(GenerationStreamingTelemetryV9Bridge.make(
            generationID: "A57D9599-E428-4D74-A7DE-69A6BD801F54",
            layer: .engine,
            notes: notes,
            frontend: nil,
            transport: nil
        ))
        XCTAssertNotNil(transition.identities.session)
        XCTAssertNotNil(transition.identities.outputAdapter)
        XCTAssertFalse(transition.unavailable.contains { $0.field == .sessionIdentity })
        XCTAssertFalse(transition.unavailable.contains { $0.field == .outputAdapterIdentity })
        XCTAssertFalse(GenerationStreamingTelemetryV9Publication.isPublicationReady(transition))
        XCTAssertThrowsError(
            try GenerationStreamingTelemetryV9Publication.requirePublicationReady(transition)
        )
    }

    func testEngineProducerObservationsMakeNestedTransitionPublicationReady() throws {
        let digest = String(repeating: "ab", count: 32)
        var notes = GenerationStreamingTelemetryV9Publication.shippingIdentityNotes
        for key in [
            "streamingV9PlanDigest",
            "streamingV9SamplingDigest",
            "streamingV9ChunkDigest",
            "streamingV9MemoryDigest",
            "streamingV9OutputPolicyDigest",
            "streamingV9QualityPolicyDigest",
        ] {
            notes[key] = digest
        }
        notes["streamingV9PlanVersion"] = "1"
        notes["streamingV9SamplingVersion"] = "2"
        notes["streamingV9ChunkVersion"] = "1"
        notes["streamingV9MemoryVersion"] = "1"
        notes["streamingV9OutputPolicyVersion"] = "1"
        notes["streamingV9QualityPolicyVersion"] = "1"

        let observations = [
            ShippingChunkObservationV9(
                index: 0,
                transportSequence: 0,
                codecStartFrame: 0,
                codecEndFrameExclusive: 7,
                audioStartFrame: 0,
                audioEndFrameExclusive: 13_440,
                materializedAtNS: 10,
                writtenAtNS: 20,
                previewPublishedAtNS: 25,
                previewDisposition: .publishedToProductSink
            ),
            ShippingChunkObservationV9(
                index: 1,
                transportSequence: 1,
                codecStartFrame: 7,
                codecEndFrameExclusive: 14,
                audioStartFrame: 13_440,
                audioEndFrameExclusive: 26_880,
                materializedAtNS: 50,
                writtenAtNS: 60,
                previewPublishedAtNS: 65,
                previewDisposition: .publishedToProductSink
            ),
        ]
        let transition = try XCTUnwrap(GenerationStreamingTelemetryV9Bridge.make(
            generationID: "A57D9599-E428-4D74-A7DE-69A6BD801F54",
            layer: .engine,
            notes: notes,
            frontend: nil,
            transport: nil,
            terminals: GenerationTerminalTimelineV9(
                modelTerminalAtNS: 70,
                productTerminalAtNS: 80,
                modelOutcome: .eos,
                productOutcome: .completed
            ),
            chunkObservations: observations,
            audioChannel: AudioChannelSummaryV9(
                capacityFrames: 26_880,
                highWaterFrames: 13_440,
                producerSuspensionNS: 2,
                producerSuspensionCount: 1,
                cancellationWakeups: 0
            )
        ))

        XCTAssertEqual(transition.frameFlow.codecFramesGenerated, 14)
        XCTAssertEqual(transition.frameFlow.codecFramesMaterialized, 14)
        XCTAssertEqual(transition.frameFlow.audioFramesWritten, 26_880)
        XCTAssertFalse(transition.unavailable.contains { $0.field == .codecFrameFlow })
        XCTAssertFalse(transition.unavailable.contains { $0.field == .audioChannel })
        XCTAssertTrue(transition.unavailable.contains {
            $0.field == .transportSequenceList && $0.reason == .notApplicable
        })
        XCTAssertTrue(transition.unavailable.contains {
            $0.field == .firstRenderObservation && $0.reason == .notApplicable
        })
        XCTAssertTrue(GenerationStreamingTelemetryV9Publication.isPublicationReady(transition))
        XCTAssertNoThrow(
            try GenerationStreamingTelemetryV9Publication.requirePublicationReady(transition)
        )
        XCTAssertThrowsError(
            try GenerationStreamingTelemetryV9Publication.makeCompleteDocument(from: transition)
        ) { error in
            XCTAssertEqual(
                error as? GenerationStreamingTelemetryV9Publication.PublicationError,
                .incompleteChunkInstants
            )
        }
    }

    func testPublicationReadyTransitionWithMLXInstantsPublishesCompleteSidecar() throws {
        let digest = String(repeating: "ab", count: 32)
        var notes = GenerationStreamingTelemetryV9Publication.shippingIdentityNotes
        for key in [
            "streamingV9PlanDigest",
            "streamingV9SamplingDigest",
            "streamingV9ChunkDigest",
            "streamingV9MemoryDigest",
            "streamingV9OutputPolicyDigest",
            "streamingV9QualityPolicyDigest",
        ] {
            notes[key] = digest
        }
        notes["streamingV9PlanVersion"] = "1"
        notes["streamingV9SamplingVersion"] = "2"
        notes["streamingV9ChunkVersion"] = "1"
        notes["streamingV9MemoryVersion"] = "1"
        notes["streamingV9OutputPolicyVersion"] = "1"
        notes["streamingV9QualityPolicyVersion"] = "1"
        let observations = [
            ShippingChunkObservationV9(
                index: 0,
                transportSequence: 0,
                codecStartFrame: 0,
                codecEndFrameExclusive: 7,
                audioStartFrame: 0,
                audioEndFrameExclusive: 13_440,
                generatedAtNS: 10,
                mlxEvaluationEnqueuedAtNS: 11,
                mlxEnqueueDurationNS: 1,
                mlxMaterializationDurationNS: 19,
                materializedAtNS: 30,
                writtenAtNS: 40,
                previewPublishedAtNS: 45,
                previewDisposition: .publishedToProductSink
            ),
            ShippingChunkObservationV9(
                index: 1,
                transportSequence: 1,
                codecStartFrame: 7,
                codecEndFrameExclusive: 14,
                audioStartFrame: 13_440,
                audioEndFrameExclusive: 26_880,
                generatedAtNS: 50,
                mlxEvaluationEnqueuedAtNS: 51,
                mlxEnqueueDurationNS: 1,
                mlxMaterializationDurationNS: 29,
                materializedAtNS: 80,
                writtenAtNS: 90,
                previewPublishedAtNS: 95,
                previewDisposition: .publishedToProductSink
            ),
        ]
        let transition = try XCTUnwrap(GenerationStreamingTelemetryV9Bridge.make(
            generationID: "A57D9599-E428-4D74-A7DE-69A6BD801F54",
            layer: .engine,
            notes: notes,
            frontend: nil,
            transport: nil,
            terminals: GenerationTerminalTimelineV9(
                modelTerminalAtNS: 100,
                productTerminalAtNS: 120,
                modelOutcome: .eos,
                productOutcome: .completed
            ),
            chunkObservations: observations,
            audioChannel: AudioChannelSummaryV9(
                capacityFrames: 26_880,
                highWaterFrames: 13_440,
                producerSuspensionNS: 2,
                producerSuspensionCount: 1,
                cancellationWakeups: 0
            )
        ))
        XCTAssertTrue(GenerationStreamingTelemetryV9Publication.isPublicationReady(transition))
        let document = try GenerationStreamingTelemetryV9Publication.makeCompleteDocument(from: transition)
        XCTAssertEqual(document.schemaVersion, 9)
        XCTAssertEqual(document.chunks.count, 2)

        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let published = try GenerationStreamingTelemetryV9Publication.publishCompleteSidecarIfReady(
            transition: transition,
            directory: directory
        )
        XCTAssertEqual(published.digest.count, 64)
        XCTAssertTrue(FileManager.default.fileExists(atPath: published.url.path))
    }

    func testDerivedMLXInstantsCarryTheirProvenanceIntoTheCompleteSidecar() throws {
        let digest = String(repeating: "ab", count: 32)
        var notes = GenerationStreamingTelemetryV9Publication.shippingIdentityNotes
        for key in [
            "streamingV9PlanDigest",
            "streamingV9SamplingDigest",
            "streamingV9ChunkDigest",
            "streamingV9MemoryDigest",
            "streamingV9OutputPolicyDigest",
            "streamingV9QualityPolicyDigest",
        ] {
            notes[key] = digest
        }
        for key in [
            "streamingV9PlanVersion",
            "streamingV9SamplingVersion",
            "streamingV9ChunkVersion",
            "streamingV9MemoryVersion",
            "streamingV9OutputPolicyVersion",
            "streamingV9QualityPolicyVersion",
        ] {
            notes[key] = "1"
        }
        let observation = ShippingChunkObservationV9(
            index: 0,
            transportSequence: 0,
            codecStartFrame: 0,
            codecEndFrameExclusive: 7,
            audioStartFrame: 0,
            audioEndFrameExclusive: 13_440,
            generatedAtNS: 10,
            mlxEvaluationEnqueuedAtNS: 11,
            mlxEnqueueDurationNS: 1,
            mlxMaterializationDurationNS: 19,
            materializedAtNS: 30,
            writtenAtNS: 40,
            previewDisposition: .notRequested,
            mlxInstantProvenance: .derivedFromStepDurations
        )
        let transition = try XCTUnwrap(GenerationStreamingTelemetryV9Bridge.make(
            generationID: "A57D9599-E428-4D74-A7DE-69A6BD801F54",
            layer: .engine,
            notes: notes,
            frontend: nil,
            transport: nil,
            terminals: GenerationTerminalTimelineV9(
                modelTerminalAtNS: 50,
                productTerminalAtNS: 60,
                modelOutcome: .eos,
                productOutcome: .completed
            ),
            chunkObservations: [observation],
            audioChannel: AudioChannelSummaryV9(
                capacityFrames: 13_440,
                highWaterFrames: 13_440,
                producerSuspensionNS: 0,
                producerSuspensionCount: 0,
                cancellationWakeups: 0
            )
        ))
        let document = try GenerationStreamingTelemetryV9Publication.makeCompleteDocument(from: transition)
        XCTAssertEqual(document.chunks.map(\.mlxInstantProvenance), [.derivedFromStepDurations])
        let json = String(decoding: try JSONEncoder().encode(document), as: UTF8.self)
        XCTAssertTrue(json.contains("derived-from-step-durations"))

        // A document written before the label decodes with no provenance and
        // re-encodes without the key.
        let legacy = try makeRecord()
        let legacyJSON = String(decoding: try JSONEncoder().encode(legacy), as: UTF8.self)
        XCTAssertFalse(legacyJSON.contains("mlxInstantProvenance"))
        let decodedLegacy = try JSONDecoder().decode(
            GenerationStreamingTelemetryV9.self,
            from: Data(legacyJSON.utf8)
        )
        XCTAssertEqual(decodedLegacy.chunks.map(\.mlxInstantProvenance), [nil, nil])

        // A provenance label without the instants it describes is refused.
        let unlabelledInstants = ShippingChunkObservationV9(
            index: 0,
            transportSequence: 0,
            audioStartFrame: 0,
            audioEndFrameExclusive: 13_440,
            materializedAtNS: 30,
            writtenAtNS: 40,
            previewDisposition: .notRequested,
            mlxInstantProvenance: .derivedFromStepDurations
        )
        XCTAssertThrowsError(try GenerationStreamingTelemetryTransitionV9(
            generationID: UUID(),
            identities: transition.identities,
            chunks: [unlabelledInstants],
            unavailable: []
        )) { error in
            XCTAssertEqual(
                error as? TelemetryV9ValidationError,
                .invalidOrdering("shipping-chunk-instant-provenance")
            )
        }
    }

    func testCompleteV9SidecarPublicationRoundTrip() throws {
        let document = try makeRecord()
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let url = try GenerationStreamingTelemetryV9Publication.publishSidecar(
            document: document,
            directory: directory
        )
        let decoded = try JSONDecoder().decode(
            GenerationStreamingTelemetryV9.self,
            from: try Data(contentsOf: url)
        )
        XCTAssertEqual(decoded.generationID, document.generationID)
        XCTAssertEqual(decoded.schemaVersion, 9)
    }

    func testShippingTransitionRecordsExactAudioRangesWithoutInventingCodecRanges() throws {
        let observations = [
            ShippingChunkObservationV9(
                index: 0,
                transportSequence: 0,
                audioStartFrame: 0,
                audioEndFrameExclusive: 12_000,
                materializedAtNS: 10,
                writtenAtNS: 20,
                previewPublishedAtNS: 25,
                previewDisposition: .publishedToProductSink
            ),
            ShippingChunkObservationV9(
                index: 1,
                transportSequence: 1,
                audioStartFrame: 12_000,
                audioEndFrameExclusive: 24_000,
                materializedAtNS: 50,
                writtenAtNS: 60,
                previewDisposition: .notRequested
            ),
        ]
        let transition = try XCTUnwrap(GenerationStreamingTelemetryV9Bridge.make(
            generationID: "A57D9599-E428-4D74-A7DE-69A6BD801F54",
            layer: .engine,
            notes: [:],
            frontend: nil,
            transport: nil,
            terminals: GenerationTerminalTimelineV9(
                modelTerminalAtNS: 70,
                productTerminalAtNS: 80,
                modelOutcome: .eos,
                productOutcome: .completed
            ),
            chunkObservations: observations
        ))

        XCTAssertEqual(transition.frameFlow.audioFramesMaterialized, 24_000)
        XCTAssertEqual(transition.frameFlow.audioFramesWritten, 24_000)
        XCTAssertEqual(transition.frameFlow.audioFramesPreviewPublished, 12_000)
        XCTAssertNil(transition.frameFlow.codecFramesGenerated)
        XCTAssertNil(transition.chunks[0].codecStartFrame)
        XCTAssertEqual(transition.interarrival?.maximumNS, 40)
        XCTAssertTrue(transition.unavailable.contains { $0.field == .exactChunkCodecRanges })
        XCTAssertFalse(transition.unavailable.contains { $0.field == .exactChunkAudioRanges })
    }

    func testLegacyV8RowWithoutNestedTransitionRemainsDecodableAndBridgeIsPrivacySafe() throws {
        let legacy = #"{"schemaVersion":8,"generationID":"legacy","layer":"engine","processName":"fixture","processIdentifier":1,"recordedAt":"2026-07-17T00:00:00Z","stageMarks":[],"timingsMS":{},"counters":{},"notes":{}}"#
        let decoded = try JSONDecoder().decode(GenerationTelemetryRecord.self, from: Data(legacy.utf8))
        XCTAssertNil(decoded.streamingTelemetryV9)

        let record = GenerationTelemetryRecord(
            generationID: "A57D9599-E428-4D74-A7DE-69A6BD801F54",
            layer: .engine,
            recordedAt: "2026-07-17T00:00:00Z",
            notes: ["unrelatedLegacyValue": "/Users/example/private.wav"]
        )
        let transitionData = try JSONEncoder().encode(try XCTUnwrap(record.streamingTelemetryV9))
        let json = String(decoding: transitionData, as: UTF8.self)
        XCTAssertFalse(json.contains("/Users/"))
        XCTAssertFalse(json.contains("private.wav"))
        XCTAssertFalse(json.localizedCaseInsensitiveContains("audible"))
    }

    private func makeRecord(
        terminals: GenerationTerminalTimelineV9? = nil,
        frameFlow: CodecFrameFlowV9? = nil,
        chunks: [StreamingChunkRangeV9]? = nil
    ) throws -> GenerationStreamingTelemetryV9 {
        let chunks = chunks ?? [
            chunk(index: 0, start: 0, end: 7, audioStart: 0, audioEnd: 13_440, generated: 10, materialized: 30, written: 40, preview: 45),
            chunk(index: 1, start: 7, end: 14, audioStart: 13_440, audioEnd: 26_880, generated: 50, materialized: 80, written: 90, preview: 95),
        ]
        return try GenerationStreamingTelemetryV9(
            generationID: UUID(uuidString: "A57D9599-E428-4D74-A7DE-69A6BD801F54")!,
            identities: try identities(),
            terminals: terminals ?? GenerationTerminalTimelineV9(
                modelTerminalAtNS: 100,
                productTerminalAtNS: 120,
                modelOutcome: .eos,
                productOutcome: .completed
            ),
            frameFlow: frameFlow ?? CodecFrameFlowV9(
                codecFramesGenerated: 14,
                codecFramesMaterialized: 14,
                audioFramesMaterialized: 26_880,
                audioFramesWritten: 26_880,
                audioFramesPreviewPublished: 26_880
            ),
            audioChannel: AudioChannelSummaryV9(
                capacityFrames: 26_880,
                highWaterFrames: 13_440,
                producerSuspensionNS: 2,
                producerSuspensionCount: 1,
                cancellationWakeups: 0
            ),
            chunks: chunks,
            transport: XPCTransportSummaryV9(observedSequences: [4, 5], maximumBacklog: 2),
            frontend: FrontendStreamingSummaryV9(
                milestones: FrontendMilestonesV9(
                    enginePreparedAtNS: 1,
                    engineStartedAtNS: 2,
                    playbackScheduledAtNS: 40,
                    playerStartedAtNS: 41,
                    firstRenderObservedAtNS: 50,
                    firstRenderObservationMethod: .playerNodeRenderCallback,
                    firstRenderResolutionNS: 1_000_000
                ),
                events: [FrontendAudioEventV9(atNS: 60, kind: .routeChanged, routeClass: .builtInSpeaker)],
                previewQueueDepth: [PreviewQueueDepthSampleV9(atNS: 45, queuedFrames: 7)]
            )
        )
    }

    private func identities() throws -> GenerationStreamingIdentityV9 {
        let digest = try TelemetrySHA256Digest(rawValue: String(repeating: "a", count: 64))
        let versioned = try VersionedTelemetryDigestV9(version: 1, digest: digest)
        return GenerationStreamingIdentityV9(
            plan: versioned,
            sampling: versioned,
            chunk: versioned,
            memory: versioned,
            session: versioned,
            outputAdapter: versioned,
            quality: versioned
        )
    }

    private func chunk(
        index: Int,
        start: UInt64,
        end: UInt64,
        audioStart: UInt64? = nil,
        audioEnd: UInt64? = nil,
        generated: UInt64,
        materialized: UInt64,
        written: UInt64?,
        preview: UInt64? = nil
    ) -> StreamingChunkRangeV9 {
        StreamingChunkRangeV9(
            index: index,
            codecStartFrame: start,
            codecEndFrameExclusive: end,
            audioStartFrame: audioStart ?? start,
            audioEndFrameExclusive: audioEnd ?? end,
            generatedAtNS: generated,
            mlxEvaluationEnqueuedAtNS: generated + 1,
            materializedAtNS: materialized,
            writtenAtNS: written,
            previewPublishedAtNS: preview,
            mlxEnqueueDurationNS: 1,
            mlxMaterializationDurationNS: materialized - generated - 1
        )
    }
}
