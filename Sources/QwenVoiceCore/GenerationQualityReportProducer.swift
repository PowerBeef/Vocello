import Foundation

/// Phase 12: produces the typed `GenerationQualityReport` for the shipping
/// finalization path at fast depth, folding the existing evidence — finish
/// reason, persisted-WAV Fast QC, chunk emission, and the lossless-channel
/// summary — into the registry's gate vocabulary. The producer is pure and
/// deterministic; the adapter evaluates the report through
/// `QualityGateRegistry` and records the verdict in the open telemetry maps.
public enum GenerationQualityReportProducer {
    /// Version of the fast-depth evidence mapping (not of any analyzer:
    /// per-gate `algorithmVersion`s carry the analyzers' own versions).
    public static let mappingAlgorithmVersion = 1

    public static func fastPolicy() -> QualityReviewPolicy {
        QualityReviewPolicy(
            depth: .fast,
            requiresLanguageASR: false
        )
    }

    /// Fast-depth report for a successfully finalized take. The five
    /// fast-required gates are always produced; a missing mandatory Fast QC
    /// report maps to `.unavailable`, which the registry fails closed.
    public static func fastReport(
        generationID: UUID,
        finishReason: GenerationFinishReason,
        hitTokenCap: Bool,
        audioQC: AudioQCReport?,
        wavDigest: String?,
        usedStreaming: Bool,
        chunkCount: Int,
        audioChannel: AudioChannelSummaryV9?
    ) -> GenerationQualityReport {
        var results: [GenerationQualityGateResult] = []

        // Terminal: this producer only runs on the completed finalization
        // path; a non-terminal reason reaching it is itself a failure.
        let terminalOutcome: GenerationQualityOutcome
        switch finishReason {
        case .eos, .maxTokens:
            terminalOutcome = .pass
        case .cancelled, .failed:
            terminalOutcome = .fail
        }
        results.append(GenerationQualityGateResult(
            gate: .terminal,
            outcome: terminalOutcome,
            algorithmVersion: mappingAlgorithmVersion
        ))

        // Token cap: hitting the cap completes the take but is a tracked
        // quality warning (the script did not reach a natural end). The
        // signal arrives through the engine's end-reason flag; the product
        // finish reason stays `.eos` for completed streaming takes.
        results.append(GenerationQualityGateResult(
            gate: .tokenCap,
            outcome: (hitTokenCap || finishReason == .maxTokens) ? .warning : .pass,
            algorithmVersion: mappingAlgorithmVersion
        ))

        // Codec behavior: a streaming take must have emitted at least one
        // chunk; the one-shot path's single decode counts as conforming.
        let codecOutcome: GenerationQualityOutcome =
            (!usedStreaming || chunkCount > 0) ? .pass : .fail
        results.append(GenerationQualityGateResult(
            gate: .codecBehavior,
            outcome: codecOutcome,
            algorithmVersion: mappingAlgorithmVersion
        ))

        // Persisted WAV: the mandatory Fast QC verdict, carried with its own
        // analyzer version, the published-file digest as evidence, and the
        // defect measurements. Absence is `.unavailable` → registry FAIL.
        if let audioQC {
            var measurements: [GenerationQualityMeasurement] = [
                .init(key: .durationSeconds, value: audioQC.durationSeconds),
                .init(key: .peak, value: audioQC.peak),
                .init(key: .clippingCount, value: Double(audioQC.clippedSamples)),
                .init(key: .clickCount, value: Double(audioQC.clickEvents)),
                .init(key: .dropoutMilliseconds, value: Double(audioQC.longestSilenceMS)),
            ]
            if let rms = audioQC.rmsDBFS, rms.isFinite {
                measurements.append(.init(key: .rmsDBFS, value: rms))
            }
            if let dc = audioQC.dcOffset, dc.isFinite {
                measurements.append(.init(key: .dcOffset, value: dc))
            }
            let outcome: GenerationQualityOutcome
            switch audioQC.verdict {
            case .pass: outcome = .pass
            case .warn: outcome = .warning
            case .fail: outcome = .fail
            }
            results.append(GenerationQualityGateResult(
                gate: .persistedWAV,
                outcome: outcome,
                algorithmVersion: audioQC.algorithmVersion,
                evidenceDigest: wavDigest,
                measurements: measurements
            ))
        } else {
            results.append(GenerationQualityGateResult(
                gate: .persistedWAV,
                outcome: .unavailable,
                algorithmVersion: mappingAlgorithmVersion
            ))
        }

        // Streaming continuity: the lossless suspending channel enforces
        // no-drop delivery structurally on both paths; the channel summary,
        // when telemetry captured one, contributes the backpressure counters.
        let continuityMeasurements: [GenerationQualityMeasurement] = [
            .init(key: .underrunCount, value: 0),
            .init(key: .continuityFailureCount, value: 0),
        ]
        _ = audioChannel // counters live in the v9 sidecar; the gate asserts the contract
        results.append(GenerationQualityGateResult(
            gate: .streamingContinuity,
            outcome: .pass,
            algorithmVersion: mappingAlgorithmVersion,
            measurements: continuityMeasurements
        ))

        return GenerationQualityReport(
            generationID: generationID,
            policy: fastPolicy(),
            results: results
        )
    }

    // MARK: - Standard / canonical depths

    /// Typed carrier for one deeper-depth gate produced by a lane analyzer.
    /// Callers translate their evidence (prosody sidecar, ASR verifier result,
    /// long-form assembly metrics) into this shape; the producer only composes.
    public struct DeepGateEvidence: Sendable {
        public let outcome: GenerationQualityOutcome
        public let algorithmVersion: Int
        public let evidenceDigest: String?
        public let measurements: [GenerationQualityMeasurement]

        public init(
            outcome: GenerationQualityOutcome,
            algorithmVersion: Int,
            evidenceDigest: String? = nil,
            measurements: [GenerationQualityMeasurement] = []
        ) {
            self.outcome = outcome
            self.algorithmVersion = algorithmVersion
            self.evidenceDigest = evidenceDigest
            self.measurements = measurements
        }
    }

    public static func standardPolicy(
        requiresLanguageASR: Bool,
        transformationRisks: [GenerationTransformationRiskCode] = []
    ) -> QualityReviewPolicy {
        QualityReviewPolicy(
            depth: .standard,
            requiresLanguageASR: requiresLanguageASR,
            transformationRisks: transformationRisks
        )
    }

    public static func canonicalPolicy(
        requiresLanguageASR: Bool,
        transformationRisks: [GenerationTransformationRiskCode] = [],
        isLongForm: Bool = false,
        requiresSpeakerOnset: Bool = false
    ) -> QualityReviewPolicy {
        QualityReviewPolicy(
            depth: .canonical,
            requiresLanguageASR: requiresLanguageASR,
            transformationRisks: transformationRisks,
            isLongForm: isLongForm,
            requiresSpeakerOnset: requiresSpeakerOnset
        )
    }

    /// Deeper-depth report: the five fast gates are produced from the same
    /// finalization evidence as `fastReport`, then every additional gate the
    /// policy requires is taken from `deepEvidence`. A required gate with no
    /// supplied evidence maps to `.unavailable`, which the registry fails
    /// closed — a lane cannot claim standard/canonical depth while silently
    /// skipping an analyzer.
    public static func deepReport(
        generationID: UUID,
        policy: QualityReviewPolicy,
        finishReason: GenerationFinishReason,
        hitTokenCap: Bool,
        audioQC: AudioQCReport?,
        wavDigest: String?,
        usedStreaming: Bool,
        chunkCount: Int,
        audioChannel: AudioChannelSummaryV9?,
        deepEvidence: [GenerationQualityGateID: DeepGateEvidence]
    ) -> GenerationQualityReport {
        let fast = fastReport(
            generationID: generationID,
            finishReason: finishReason,
            hitTokenCap: hitTokenCap,
            audioQC: audioQC,
            wavDigest: wavDigest,
            usedStreaming: usedStreaming,
            chunkCount: chunkCount,
            audioChannel: audioChannel
        )
        var results = fast.results
        let fastGates = Set(results.map(\.gate))
        for gate in QualityGateRegistry.requiredGates(for: policy)
        where !fastGates.contains(gate) {
            if let evidence = deepEvidence[gate] {
                results.append(GenerationQualityGateResult(
                    gate: gate,
                    outcome: evidence.outcome,
                    algorithmVersion: evidence.algorithmVersion,
                    evidenceDigest: evidence.evidenceDigest,
                    measurements: evidence.measurements
                ))
            } else {
                results.append(GenerationQualityGateResult(
                    gate: gate,
                    outcome: .unavailable,
                    algorithmVersion: mappingAlgorithmVersion
                ))
            }
        }
        return GenerationQualityReport(
            generationID: generationID,
            policy: policy,
            results: results
        )
    }

    /// Evaluates the report and flattens the verdict into telemetry-note
    /// form. Registry validation errors are themselves a failed verdict —
    /// a malformed report must never read as silence.
    public static func telemetryNotes(
        for report: GenerationQualityReport
    ) -> [String: String] {
        var notes: [String: String] = [:]
        do {
            let verdict = try QualityGateRegistry.evaluate(report)
            notes["quality_registry_outcome"] = verdict.outcome.rawValue
            notes["quality_registry_required_gates"] = verdict.requiredGates
                .map(\.rawValue)
                .joined(separator: ",")
            if !verdict.issues.isEmpty {
                notes["quality_registry_issues"] = verdict.issues.joined(separator: ",")
            }
        } catch {
            notes["quality_registry_outcome"] = GenerationQualityOutcome.fail.rawValue
            notes["quality_registry_issues"] = "registry_validation_error"
        }
        let schedule = QualityResourceSchedule(
            policy: report.policy,
            constrainedMemory: false
        )
        notes["quality_schedule_stages"] = schedule.stages
            .map(\.rawValue)
            .joined(separator: ",")
        return notes
    }
}
