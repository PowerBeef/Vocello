import Foundation

/// Phase 12 close-out: composes the standard-depth quality verdict on the
/// delivery bench lane, consolidating the persisted-WAV analyses (the Fast QC
/// verdict already folded by `fastReport` and the reference-free prosody gate
/// from the bench sidecar) into one typed registry verdict. The mapping is
/// pure and deterministic; the CLI bench command supplies the finalization
/// evidence and the sidecar entries. Canonical depth additionally requires a
/// `.delivery` gate, which has no promoted pass rule yet (the adherence
/// tooling measures signed effects without a threshold verdict), so the
/// composed lane emission is standard depth until that rule exists.
public enum GenerationQualityComposition {
    /// The per-take prosody gate verdict exactly as
    /// `scripts/bench_delivery_prosody.py` writes it (`qualityGate` inside
    /// `bench-prosody.json`). Field names are that script's contract; keep in
    /// lockstep with `scripts/prosody_quality_gate.py`.
    public struct ProsodySidecarGate: Codable, Sendable {
        public let passed: Bool
        public let flags: [String]
        public let analyzerAlgorithmVersion: Int
        public let metrics: [String: Double]

        public init(
            passed: Bool,
            flags: [String],
            analyzerAlgorithmVersion: Int,
            metrics: [String: Double]
        ) {
            self.passed = passed
            self.flags = flags
            self.analyzerAlgorithmVersion = analyzerAlgorithmVersion
            self.metrics = metrics
        }
    }

    /// Flags meaning the analysis itself produced no verdict. They map to
    /// `.unavailable`, which the registry fails closed — mirroring the history
    /// publisher, which refuses publication on the same flags.
    public static let analysisFailureFlags: Set<String> = [
        "metrics_incomplete", "analysis_failed",
    ]

    /// Maps one sidecar prosody verdict into typed deep evidence for the
    /// `.prosody` gate. Quality flags (monotone, rushed, flat, pause issues)
    /// are warnings, exactly as the history publisher folds them; only the
    /// analysis-failure flags escalate to `.unavailable`.
    public static func prosodyEvidence(
        gate: ProsodySidecarGate,
        evidenceDigest: String? = nil
    ) -> GenerationQualityReportProducer.DeepGateEvidence {
        let outcome: GenerationQualityOutcome
        if !analysisFailureFlags.isDisjoint(with: gate.flags) {
            outcome = .unavailable
        } else if gate.passed && gate.flags.isEmpty {
            outcome = .pass
        } else {
            outcome = .warning
        }
        var measurements: [GenerationQualityMeasurement] = []
        if let pitchRange = gate.metrics["pitch_range_semitones"], pitchRange.isFinite {
            measurements.append(.init(key: .pitchRangeSemitones, value: pitchRange))
        }
        if let boundary = gate.metrics["boundary_discontinuity"], boundary.isFinite {
            measurements.append(.init(key: .boundaryDiscontinuity, value: boundary))
        }
        return GenerationQualityReportProducer.DeepGateEvidence(
            outcome: outcome,
            algorithmVersion: gate.analyzerAlgorithmVersion,
            evidenceDigest: evidenceDigest,
            measurements: measurements.sorted { $0.key.rawValue < $1.key.rawValue }
        )
    }

    /// Ranks outcomes for the fast-consistency guard: a composed verdict can
    /// never be better than the fast verdict its take finalized with.
    public static func rank(of outcome: GenerationQualityOutcome) -> Int {
        switch outcome {
        case .pass: return 0
        case .warning: return 1
        case .notApplicable, .unavailable, .fail: return 2
        }
    }
}
