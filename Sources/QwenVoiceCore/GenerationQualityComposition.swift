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
        /// `calibrated` only when the profile carries per-flag detection evidence
        /// (audit #41); `uncalibrated` otherwise. Absent from sidecars written
        /// before 2026-09-25, which were uncalibrated too.
        public let calibrationStatus: String?

        public init(
            passed: Bool,
            flags: [String],
            analyzerAlgorithmVersion: Int,
            metrics: [String: Double],
            calibrationStatus: String? = nil
        ) {
            self.passed = passed
            self.flags = flags
            self.analyzerAlgorithmVersion = analyzerAlgorithmVersion
            self.metrics = metrics
            self.calibrationStatus = calibrationStatus
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
    /// analysis-failure flags escalate to `.unavailable`. A clean verdict is a
    /// pass only from a calibrated gate: the shipped thresholds sit outside the
    /// observed data (one flag in 902 takes) and were never shown to detect
    /// what they name, so a clean uncalibrated verdict composes as
    /// `.uncalibrated`, never `.pass` (audit #41, 2026-09-25).
    public static func prosodyEvidence(
        gate: ProsodySidecarGate,
        evidenceDigest: String? = nil
    ) -> GenerationQualityReportProducer.DeepGateEvidence {
        let outcome: GenerationQualityOutcome
        if !analysisFailureFlags.isDisjoint(with: gate.flags) {
            outcome = .unavailable
        } else if gate.passed && gate.flags.isEmpty {
            outcome = gate.calibrationStatus == "calibrated" ? .pass : .uncalibrated
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

    /// The cell-level adherence verdict of the take's cell, exactly as
    /// `scripts/bench_delivery_prosody.py` writes it (`deliveryCellGate` beside
    /// `deliveryGate`; `evaluate_delivery_cell` in
    /// `scripts/delivery_quality_gate.py`, audit #39). Since gate v3 it is the
    /// adherence verdict; the per-take flags are diagnostics.
    public struct DeliveryCellGate: Codable, Sendable {
        public let algorithm: String
        /// `pass`, `warn`, `insufficient` (too few takes of the cell to judge)
        /// or `unavailable` (no expectation covers the preset).
        public let status: String
        public let flags: [String]

        public init(algorithm: String, status: String, flags: [String]) {
            self.algorithm = algorithm
            self.status = status
            self.flags = flags
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
    /// for the `.delivery` gate. The per-take analysis-failure flags escalate to
    /// `.unavailable`. With the cell verdict (gate v3, audit #39) the outcome is
    /// the cell's: `pass`, `warn` → `.warning`, `insufficient` →
    /// `.uncalibrated` (one run rarely holds enough takes of a cell; the
    /// cross-seed report judges it), anything else `.unavailable`; the take's
    /// own adherence flags are diagnostics and never change the outcome.
    /// Without a cell verdict (a sidecar before v3) the per-take flags warn as
    /// before. A verdict may also list skipped optional features in
    /// `unavailableFeatures`; that key is informational.
    public static func deliveryEvidence(
        gate: DeliverySidecarGate,
        cellGate: DeliveryCellGate? = nil,
        evidenceDigest: String? = nil
    ) -> GenerationQualityReportProducer.DeepGateEvidence {
        let outcome: GenerationQualityOutcome
        if !deliveryAnalysisFailureFlags.isDisjoint(with: gate.flags) {
            outcome = .unavailable
        } else if let cellGate {
            switch cellGate.status {
            case "pass": outcome = .pass
            case "warn": outcome = .warning
            case "insufficient": outcome = .uncalibrated
            default: outcome = .unavailable
            }
        } else if gate.passed && gate.flags.isEmpty {
            outcome = .pass
        } else {
            outcome = .warning
        }
        var measurements: [GenerationQualityMeasurement] = []
        // The voice-quality axes are optional: a sidecar produced by analyzer
        // v2 carries no spectral block, and a missing axis must simply be
        // absent from the evidence rather than fail composition.
        for (metricKey, measurementKey) in [
            ("pitch_shift_semitones", GenerationQualityMeasurementKey.deliveryPitchShiftSemitones),
            ("arousal_score", .deliveryArousalScore),
            ("voice_tension_score", .deliveryVoiceTensionScore),
            ("voice_breathiness_score", .deliveryVoiceBreathinessScore),
        ] {
            if let value = gate.metrics[metricKey], value.isFinite {
                measurements.append(.init(key: measurementKey, value: value))
            }
        }
        return GenerationQualityReportProducer.DeepGateEvidence(
            outcome: outcome,
            algorithmVersion: gate.algorithmVersion,
            evidenceDigest: evidenceDigest,
            measurements: measurements.sorted { $0.key.rawValue < $1.key.rawValue }
        )
    }

    /// Ranks outcomes for the fast-consistency guard: a composed verdict can
    /// never be better than the fast verdict its take finalized with. An
    /// abstention blocks a claimed pass, so it ranks with `unavailable` and
    /// `fail` (audio QC audit 2026-09-25, section 3.3); the registry still
    /// reports it distinctly.
    public static func rank(of outcome: GenerationQualityOutcome) -> Int {
        switch outcome {
        case .pass: return 0
        case .uncalibrated: return 1
        case .warning: return 2
        case .abstained, .unavailable, .fail: return 3
        }
    }
}
