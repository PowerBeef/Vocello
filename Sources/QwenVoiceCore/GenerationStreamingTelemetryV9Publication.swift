import CryptoKit
import Foundation

/// Complete schema-v9 streaming telemetry writer, validator, and privacy-safe
/// sidecar publisher.
///
/// Shipping JSONL rows remain schema v8 with a nested transition projection.
/// This type validates and publishes the complete v9 document when a producer
/// can supply every required domain, without inventing zeros for missing fields.
public enum GenerationStreamingTelemetryV9Publication: Sendable {
    public static let sidecarFileExtension = "streaming-telemetry-v9.json"
    public static let sessionIdentityVersion = 1
    /// 2 (BT-06, audit #49/#62): under `.pipelined` the derived
    /// `mlxMaterializationDurationNS`, `mlxEvaluationEnqueuedAtNS` and
    /// `generatedAtNS` count back the observed step wait (the sampled-token
    /// read) instead of a zero eval-minus-enqueue remainder. The bump marks rows
    /// and sidecars written with that meaning; version 1 predates it.
    /// 3 (BT-06, audit #49/#62): every chunk that carries those instants also
    /// labels them `mlxInstantProvenance: derived-from-step-durations`, in the
    /// nested transition and in the complete sidecar. The values are unchanged.
    public static let outputAdapterIdentityVersion = 3

    public enum PublicationError: Error, Equatable, Sendable {
        case validationFailed
        case writeFailed
        case transitionNotPublicationReady
        case incompleteChunkInstants
        case incompleteIdentities
        case incompleteFrameFlow
        case missingAudioChannel
    }

    /// Stable privacy-safe identity notes for the shipping actor session and
    /// product output adapter. Stamping these onto a generation row replaces
    /// stale "not shipping" unavailability reasons in the nested transition.
    public static var shippingIdentityNotes: [String: String] {
        [
            "streamingV9SessionDigest": identityDigest(
                namespace: "vocello.telemetry.v9.session",
                components: [
                    "VocelloQwen3ClassifiedGenerationSession",
                    String(sessionIdentityVersion),
                ]
            ),
            "streamingV9SessionVersion": String(sessionIdentityVersion),
            "streamingV9OutputAdapterDigest": identityDigest(
                namespace: "vocello.telemetry.v9.output-adapter",
                components: [
                    "GenerationOutputAdapter",
                    String(outputAdapterIdentityVersion),
                ]
            ),
            "streamingV9OutputAdapterVersion": String(outputAdapterIdentityVersion),
        ]
    }

    /// Unavailable reasons that do not block nested-v9 publication readiness.
    /// Layer-specific `notApplicable` entries and known non-shipping player /
    /// transport-list gaps must not prevent engine-domain readiness once the
    /// required producers observe their evidence.
    private static let nonBlockingUnavailableReasons: Set<GenerationStreamingUnavailableReasonV9> = [
        .notApplicable,
        .currentTransportStoresAggregateOnly,
        .currentPlayerHasNoRenderObservation,
        .currentFrontendStoresMillisecondsOnly,
    ]

    /// A transition is publication-ready when every required producer domain was
    /// observed. Non-blocking layer gaps (notApplicable / aggregate-only transport
    /// list / missing player render callback) may remain listed without inventing
    /// zeros.
    public static func isPublicationReady(
        _ transition: GenerationStreamingTelemetryTransitionV9
    ) -> Bool {
        let blockingUnavailable = transition.unavailable.filter {
            !nonBlockingUnavailableReasons.contains($0.reason)
        }
        return blockingUnavailable.isEmpty
            && transition.identities.plan != nil
            && transition.identities.sampling != nil
            && transition.identities.chunk != nil
            && transition.identities.memory != nil
            && transition.identities.outputPolicy != nil
            && transition.identities.qualityPolicy != nil
            && transition.identities.session != nil
            && transition.identities.outputAdapter != nil
            && transition.audioChannel != nil
            && transition.frameFlow.codecFramesGenerated != nil
            && transition.frameFlow.codecFramesMaterialized != nil
            && transition.frameFlow.audioFramesMaterialized != nil
            && transition.frameFlow.audioFramesWritten != nil
            && transition.frameFlow.audioFramesPreviewPublished != nil
            && transition.terminals.modelTerminalAtNS != nil
            && transition.terminals.productTerminalAtNS != nil
            && !transition.chunks.isEmpty
            && transition.chunks.allSatisfy {
                $0.codecStartFrame != nil && $0.codecEndFrameExclusive != nil
            }
    }

    public static func validate(_ document: GenerationStreamingTelemetryV9) throws {
        try document.validate()
    }

    /// Writes a complete v9 sidecar. Never embeds absolute paths, prompts, or
    /// private metadata in the document body.
    @discardableResult
    public static func publishSidecar(
        document: GenerationStreamingTelemetryV9,
        directory: URL
    ) throws -> URL {
        try validate(document)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        let data: Data
        do {
            data = try encoder.encode(document)
        } catch {
            throw PublicationError.validationFailed
        }
        let url = directory.appendingPathComponent(
            "\(document.generationID.uuidString.lowercased()).\(sidecarFileExtension)"
        )
        do {
            try FileManager.default.createDirectory(
                at: directory,
                withIntermediateDirectories: true
            )
            try data.write(to: url, options: .atomic)
        } catch {
            throw PublicationError.writeFailed
        }
        return url
    }

    /// Fail-closed gate used by promotion tooling: refuse to treat a nested
    /// transition as a complete v9 publication when domains are still missing.
    public static func requirePublicationReady(
        _ transition: GenerationStreamingTelemetryTransitionV9
    ) throws {
        guard isPublicationReady(transition) else {
            throw PublicationError.transitionNotPublicationReady
        }
    }

    /// Build a complete schema-v9 document from a publication-ready transition.
    /// Requires MLX chunk instants on every shipping observation and never
    /// invents frame counts. Those instants are derived from the engine's
    /// per-chunk step durations counted back from the consumer's receipt
    /// (`GenerationOutputAdapter.mlxChunkInstants`), not observed MLX events
    /// (audit #49/#62).
    public static func makeCompleteDocument(
        from transition: GenerationStreamingTelemetryTransitionV9
    ) throws -> GenerationStreamingTelemetryV9 {
        try requirePublicationReady(transition)
        guard transition.chunks.allSatisfy(\.hasMLXChunkInstants) else {
            throw PublicationError.incompleteChunkInstants
        }
        guard let plan = transition.identities.plan,
              let sampling = transition.identities.sampling,
              let chunk = transition.identities.chunk,
              let memory = transition.identities.memory,
              let session = transition.identities.session,
              let outputAdapter = transition.identities.outputAdapter,
              let quality = transition.identities.qualityPolicy else {
            throw PublicationError.incompleteIdentities
        }
        // Complete identity stores the quality-policy digest; output-policy remains
        // in the nested transition and must already be present for readiness.
        guard transition.identities.outputPolicy != nil else {
            throw PublicationError.incompleteIdentities
        }
        guard let codecGenerated = transition.frameFlow.codecFramesGenerated,
              let codecMaterialized = transition.frameFlow.codecFramesMaterialized,
              let audioMaterialized = transition.frameFlow.audioFramesMaterialized,
              let audioWritten = transition.frameFlow.audioFramesWritten,
              let audioPreview = transition.frameFlow.audioFramesPreviewPublished else {
            throw PublicationError.incompleteFrameFlow
        }
        guard let audioChannel = transition.audioChannel else {
            throw PublicationError.missingAudioChannel
        }

        let chunks: [StreamingChunkRangeV9] = try transition.chunks.map { observation in
            guard let codecStart = observation.codecStartFrame,
                  let codecEnd = observation.codecEndFrameExclusive,
                  let generatedAtNS = observation.generatedAtNS,
                  let enqueuedAtNS = observation.mlxEvaluationEnqueuedAtNS,
                  let enqueueDurationNS = observation.mlxEnqueueDurationNS,
                  let materializationDurationNS = observation.mlxMaterializationDurationNS else {
                throw PublicationError.incompleteChunkInstants
            }
            return StreamingChunkRangeV9(
                index: observation.index,
                codecStartFrame: codecStart,
                codecEndFrameExclusive: codecEnd,
                audioStartFrame: observation.audioStartFrame,
                audioEndFrameExclusive: observation.audioEndFrameExclusive,
                generatedAtNS: generatedAtNS,
                mlxEvaluationEnqueuedAtNS: enqueuedAtNS,
                materializedAtNS: observation.materializedAtNS,
                writtenAtNS: observation.writtenAtNS,
                previewPublishedAtNS: observation.previewPublishedAtNS,
                mlxEnqueueDurationNS: enqueueDurationNS,
                mlxMaterializationDurationNS: materializationDurationNS,
                mlxInstantProvenance: observation.mlxInstantProvenance
            )
        }

        return try GenerationStreamingTelemetryV9(
            generationID: transition.generationID,
            identities: GenerationStreamingIdentityV9(
                plan: plan,
                sampling: sampling,
                chunk: chunk,
                memory: memory,
                session: session,
                outputAdapter: outputAdapter,
                quality: quality
            ),
            terminals: transition.terminals,
            frameFlow: CodecFrameFlowV9(
                codecFramesGenerated: codecGenerated,
                codecFramesMaterialized: codecMaterialized,
                audioFramesMaterialized: audioMaterialized,
                audioFramesWritten: audioWritten,
                audioFramesPreviewPublished: audioPreview
            ),
            audioChannel: audioChannel,
            chunks: chunks
        )
    }

    /// Publish a complete v9 sidecar when the transition is publication-ready and
    /// every chunk carries its derived MLX instants. Returns the sidecar URL and SHA-256.
    public static func publishCompleteSidecarIfReady(
        transition: GenerationStreamingTelemetryTransitionV9,
        directory: URL
    ) throws -> (url: URL, digest: String) {
        let document = try makeCompleteDocument(from: transition)
        let url = try publishSidecar(document: document, directory: directory)
        let digest = try SamplingTakeEvidence.sha256FileDigest(at: url)
        return (url, digest)
    }

    public static func identityDigest(namespace: String, components: [String]) -> String {
        let serialization = ([namespace] + components)
            .map { "\($0.utf8.count):\($0)" }
            .joined()
        return SHA256.hash(data: Data(serialization.utf8))
            .map { String(format: "%02x", $0) }.joined()
    }
}
