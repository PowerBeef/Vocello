import Foundation

/// Phase 12 close-out: composes the deep-depth quality verdict on the
/// delivery bench lane, consolidating the persisted-WAV analyses (the Fast QC
/// verdict already folded by `fastReport`, the reference-free prosody gate,
/// and the per-preset delivery-adherence gate from the bench sidecar) into
/// one typed registry verdict. The mapping is pure and deterministic; the CLI
/// bench command supplies the finalization evidence and the sidecar entries.
/// The `.delivery` gate's promoted pass rule is the warn-first per-preset
/// expectation verdict from `scripts/delivery_quality_gate.py`, so delivery
/// takes compose at canonical depth.
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

    /// The per-take delivery-adherence verdict exactly as
    /// `scripts/bench_delivery_prosody.py` writes it (`deliveryGate` inside
    /// `bench-prosody.json`). Field names are that script's contract; keep in
    /// lockstep with `scripts/delivery_quality_gate.py`.
    public struct DeliverySidecarGate: Codable, Sendable {
        public let deliveryID: String
        public let preset: String
        public let intensity: String
        public let algorithmVersion: Int
        public let passed: Bool
        public let flags: [String]
        public let metrics: [String: Double]

        public init(
            deliveryID: String,
            preset: String,
            intensity: String,
            algorithmVersion: Int,
            passed: Bool,
            flags: [String],
            metrics: [String: Double]
        ) {
            self.deliveryID = deliveryID
            self.preset = preset
            self.intensity = intensity
            self.algorithmVersion = algorithmVersion
            self.passed = passed
            self.flags = flags
            self.metrics = metrics
        }
    }

    /// Delivery-gate flags meaning the verdict could not be computed; they map
    /// to `.unavailable`, which the registry fails closed. Mirrors
    /// `ANALYSIS_FAILURE_FLAGS` in `scripts/delivery_quality_gate.py`.
    public static let deliveryAnalysisFailureFlags: Set<String> = [
        "analysis_failed", "metrics_incomplete", "expectation_missing",
        "cohort_too_small",
    ]

    /// Maps one sidecar delivery-adherence verdict into typed deep evidence
    /// for the `.delivery` gate. Adherence flags (direction misses, weak
    /// effects, supporting misses) are warnings — the rule is deliberately
    /// warn-first until the paired calibration run promotes magnitudes — and
    /// only the analysis-failure flags escalate to `.unavailable`.
    public static func deliveryEvidence(
        gate: DeliverySidecarGate,
        evidenceDigest: String? = nil
    ) -> GenerationQualityReportProducer.DeepGateEvidence {
        let outcome: GenerationQualityOutcome
        if !deliveryAnalysisFailureFlags.isDisjoint(with: gate.flags) {
            outcome = .unavailable
        } else if gate.passed && gate.flags.isEmpty {
            outcome = .pass
        } else {
            outcome = .warning
        }
        var measurements: [GenerationQualityMeasurement] = []
        if let pitchShift = gate.metrics["pitch_shift_semitones"], pitchShift.isFinite {
            measurements.append(.init(key: .deliveryPitchShiftSemitones, value: pitchShift))
        }
        if let arousal = gate.metrics["arousal_score"], arousal.isFinite {
            measurements.append(.init(key: .deliveryArousalScore, value: arousal))
        }
        return GenerationQualityReportProducer.DeepGateEvidence(
            outcome: outcome,
            algorithmVersion: gate.algorithmVersion,
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
