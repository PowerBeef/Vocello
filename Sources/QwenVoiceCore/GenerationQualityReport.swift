import Foundation

public enum GenerationQualityReviewDepth: String, Codable, Hashable, Sendable {
    case fast
    case standard
    case canonical
}

public enum GenerationQualityOutcome: String, Codable, Hashable, Sendable {
    case pass
    case warning
    case fail
    case unavailable
    case notApplicable = "not_applicable"
}

public enum GenerationQualityGateID: String, CaseIterable, Codable, Hashable, Sendable {
    case terminal
    case tokenCap = "token_cap"
    case codecBehavior = "codec_behavior"
    case persistedWAV = "persisted_wav"
    case streamingContinuity = "streaming_continuity"
    case prosody
    case languageASR = "language_asr"
    case criticalTokens = "critical_tokens"
    case delivery
    case speakerOnset = "speaker_onset"
    case longFormContinuity = "long_form_continuity"
}

public enum GenerationQualityMeasurementKey: String, Codable, Hashable, Sendable {
    case durationSeconds = "duration_seconds"
    case peak
    case rmsDBFS = "rms_dbfs"
    case dcOffset = "dc_offset"
    case clippingCount = "clipping_count"
    case clickCount = "click_count"
    case dropoutMilliseconds = "dropout_milliseconds"
    case continuityFailureCount = "continuity_failure_count"
    case underrunCount = "underrun_count"
    case wordErrorRate = "word_error_rate"
    case consensusPassCount = "consensus_pass_count"
    case medianPitchSemitones = "median_pitch_semitones"
    case pitchRangeSemitones = "pitch_range_semitones"
    case boundaryDiscontinuity = "boundary_discontinuity"
    case analyzerPeakWorkingSetBytes = "analyzer_peak_working_set_bytes"
    case deliveryPitchShiftSemitones = "delivery_pitch_shift_semitones"
    case deliveryArousalScore = "delivery_arousal_score"
}

public struct GenerationQualityMeasurement: Codable, Hashable, Sendable {
    public let key: GenerationQualityMeasurementKey
    public let value: Double

    public init(key: GenerationQualityMeasurementKey, value: Double) {
        self.key = key
        self.value = value
    }
}

public struct GenerationQualityGateResult: Codable, Hashable, Sendable {
    public let gate: GenerationQualityGateID
    public let outcome: GenerationQualityOutcome
    public let algorithmVersion: Int
    public let evidenceDigest: String?
    public let measurements: [GenerationQualityMeasurement]

    public init(
        gate: GenerationQualityGateID,
        outcome: GenerationQualityOutcome,
        algorithmVersion: Int,
        evidenceDigest: String? = nil,
        measurements: [GenerationQualityMeasurement] = []
    ) {
        self.gate = gate
        self.outcome = outcome
        self.algorithmVersion = algorithmVersion
        self.evidenceDigest = evidenceDigest
        self.measurements = measurements.sorted { $0.key.rawValue < $1.key.rawValue }
    }
}

public enum GenerationTransformationRiskCode: String, Codable, Hashable, Sendable {
    case ambiguousNumber = "ambiguous_number"
    case protectedURL = "protected_url"
    case protectedEmail = "protected_email"
    case protectedVersion = "protected_version"
    case protectedAcronym = "protected_acronym"
    case codeSwitch = "code_switch"
    case criticalToken = "critical_token"
}

public struct QualityReviewPolicy: Codable, Hashable, Sendable {
    public let version: Int
    public let depth: GenerationQualityReviewDepth
    public let requiresLanguageASR: Bool
    public let transformationRisks: [GenerationTransformationRiskCode]
    public let isLongForm: Bool
    public let requiresSpeakerOnset: Bool

    public init(
        version: Int = 1,
        depth: GenerationQualityReviewDepth,
        requiresLanguageASR: Bool,
        transformationRisks: [GenerationTransformationRiskCode] = [],
        isLongForm: Bool = false,
        requiresSpeakerOnset: Bool = false
    ) {
        self.version = version
        self.depth = depth
        self.requiresLanguageASR = requiresLanguageASR
        self.transformationRisks = Array(Set(transformationRisks)).sorted { $0.rawValue < $1.rawValue }
        self.isLongForm = isLongForm
        self.requiresSpeakerOnset = requiresSpeakerOnset
    }
}

public enum QualityResourceStage: String, Codable, Hashable, Sendable {
    case synthesis
    case fastAnalysis = "fast_analysis"
    case releaseTTSResources = "release_tts_resources"
    case speechRecognition = "speech_recognition"
    case advancedAnalysis = "advanced_analysis"
}

public struct QualityResourceSchedule: Codable, Hashable, Sendable {
    public let stages: [QualityResourceStage]

    public init(
        policy: QualityReviewPolicy,
        constrainedMemory: Bool
    ) {
        var values: [QualityResourceStage] = [.synthesis, .fastAnalysis]
        if policy.depth != .fast {
            if constrainedMemory {
                values.append(.releaseTTSResources)
            }
            if policy.requiresLanguageASR {
                values.append(.speechRecognition)
            }
            values.append(.advancedAnalysis)
        }
        stages = values
    }

    public var permitsConcurrentHeavyReviewerAndSynthesis: Bool { false }
}

public struct GenerationQualityReport: Codable, Hashable, Sendable {
    public static let currentSchemaVersion = 1

    public let schemaVersion: Int
    public let generationID: UUID
    public let policy: QualityReviewPolicy
    public let results: [GenerationQualityGateResult]

    public init(
        generationID: UUID,
        policy: QualityReviewPolicy,
        results: [GenerationQualityGateResult]
    ) {
        self.schemaVersion = Self.currentSchemaVersion
        self.generationID = generationID
        self.policy = policy
        self.results = results.sorted { $0.gate.rawValue < $1.gate.rawValue }
    }
}

public enum QualityGateRegistryIssue: Error, Equatable, Sendable {
    case invalidPolicyVersion
    case duplicateGate(GenerationQualityGateID)
    case duplicateMeasurement(GenerationQualityGateID, GenerationQualityMeasurementKey)
    case missingRequiredGate(GenerationQualityGateID)
    case invalidAlgorithmVersion(GenerationQualityGateID)
    case invalidEvidenceDigest(GenerationQualityGateID)
    case invalidMeasurement(GenerationQualityGateID, GenerationQualityMeasurementKey)
    case insufficientASRConsensus
}

public struct QualityGateRegistryVerdict: Codable, Hashable, Sendable {
    public let outcome: GenerationQualityOutcome
    public let requiredGates: [GenerationQualityGateID]
    public let issues: [String]
}

public enum QualityGateRegistry {
    public static func requiredGates(
        for policy: QualityReviewPolicy
    ) -> [GenerationQualityGateID] {
        var gates: Set<GenerationQualityGateID> = [
            .terminal,
            .tokenCap,
            .codecBehavior,
            .persistedWAV,
            .streamingContinuity,
        ]
        if policy.depth == .standard || policy.depth == .canonical {
            gates.insert(.prosody)
            if policy.requiresLanguageASR { gates.insert(.languageASR) }
            if policy.transformationRisks.contains(.criticalToken) {
                gates.insert(.criticalTokens)
            }
        }
        if policy.depth == .canonical {
            gates.insert(.delivery)
            if policy.requiresSpeakerOnset { gates.insert(.speakerOnset) }
            if policy.isLongForm { gates.insert(.longFormContinuity) }
        }
        return gates.sorted { $0.rawValue < $1.rawValue }
    }

    public static func evaluate(
        _ report: GenerationQualityReport
    ) throws -> QualityGateRegistryVerdict {
        guard report.policy.version > 0 else {
            throw QualityGateRegistryIssue.invalidPolicyVersion
        }
        var byGate: [GenerationQualityGateID: GenerationQualityGateResult] = [:]
        for result in report.results {
            guard byGate[result.gate] == nil else {
                throw QualityGateRegistryIssue.duplicateGate(result.gate)
            }
            guard result.algorithmVersion > 0 else {
                throw QualityGateRegistryIssue.invalidAlgorithmVersion(result.gate)
            }
            if let digest = result.evidenceDigest,
               !QualityGateRegistry.isSHA256Hex(digest) {
                throw QualityGateRegistryIssue.invalidEvidenceDigest(result.gate)
            }
            var measurementKeys = Set<GenerationQualityMeasurementKey>()
            for measurement in result.measurements where !measurement.value.isFinite {
                throw QualityGateRegistryIssue.invalidMeasurement(result.gate, measurement.key)
            }
            for measurement in result.measurements where
                !measurementKeys.insert(measurement.key).inserted {
                throw QualityGateRegistryIssue.duplicateMeasurement(
                    result.gate,
                    measurement.key
                )
            }
            byGate[result.gate] = result
        }

        let required = requiredGates(for: report.policy)
        for gate in required where byGate[gate] == nil {
            throw QualityGateRegistryIssue.missingRequiredGate(gate)
        }
        if let asr = byGate[.languageASR], asr.outcome == .pass {
            let passCount = asr.measurements.first(where: {
                $0.key == .consensusPassCount
            })?.value ?? 0
            guard passCount >= 3 else {
                throw QualityGateRegistryIssue.insufficientASRConsensus
            }
        }

        var outcome: GenerationQualityOutcome = .pass
        var issues: [String] = []
        for gate in required {
            guard let result = byGate[gate] else { continue }
            switch result.outcome {
            case .pass:
                break
            case .notApplicable:
                // A gate is added to `required` only when it is applicable to
                // this review policy. Treating it as not-applicable here would
                // allow a mandatory Fast/Standard/Canonical proof to disappear
                // while the aggregate report still claimed PASS.
                outcome = .fail
                issues.append("quality_gate_not_applicable.\(gate.rawValue)")
            case .warning:
                if outcome == .pass { outcome = .warning }
                issues.append("quality_gate_warning.\(gate.rawValue)")
            case .fail:
                outcome = .fail
                issues.append("quality_gate_failed.\(gate.rawValue)")
            case .unavailable:
                outcome = .fail
                issues.append("quality_gate_unavailable.\(gate.rawValue)")
            }
        }
        return QualityGateRegistryVerdict(
            outcome: outcome,
            requiredGates: required,
            issues: issues.sorted()
        )
    }

    private static func isSHA256Hex(_ value: String) -> Bool {
        value.utf8.count == 64 && value.unicodeScalars.allSatisfy { scalar in
            (48 ... 57).contains(scalar.value)
                || (97 ... 102).contains(scalar.value)
        }
    }
}

public struct QualityCandidateAttemptIdentity: Codable, Hashable, Sendable {
    public let attemptIndex: Int
    public let operationLeaseID: UUID
    public let derivedSeed: UInt64
    public let evidenceDigest: String

    public init(
        attemptIndex: Int,
        operationLeaseID: UUID,
        derivedSeed: UInt64,
        evidenceDigest: String
    ) {
        self.attemptIndex = attemptIndex
        self.operationLeaseID = operationLeaseID
        self.derivedSeed = derivedSeed
        self.evidenceDigest = evidenceDigest
    }
}

public enum QualityCandidateRetryPolicy {
    public static let maximumAlternativeCount = 2

    public static func validate(
        _ attempts: [QualityCandidateAttemptIdentity]
    ) -> Bool {
        guard attempts.count <= maximumAlternativeCount + 1 else { return false }
        return Set(attempts.map(\.attemptIndex)).count == attempts.count
            && Set(attempts.map(\.operationLeaseID)).count == attempts.count
            && Set(attempts.map(\.derivedSeed)).count == attempts.count
            && attempts.map(\.attemptIndex) == Array(0 ..< attempts.count)
    }
}
