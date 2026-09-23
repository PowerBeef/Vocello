import Foundation

/// Bounded, privacy-safe plan accepted by the physical-iPhone retained-memory
/// runner. The shell constructs this JSON from the tracked policy; the app
/// rejects any drift before touching a model.
public struct IOSMemoryQualificationSpec: Codable, Equatable, Sendable {
    public static let currentSchemaVersion = 1
    public static let requiredPolicyID = "retained-memory-v1"
    public static let requiredModes = ["custom", "design", "clone"]
    public static let requiredVariant = "speed"
    public static let requiredLength = "medium"
    public static let requiredRepetitionsPerMode = 3
    public static let requiredSeed: UInt64 = 19_790_615

    public let schemaVersion: Int
    public let runID: String
    public let policyID: String
    public let modes: [String]
    public let variant: String
    public let length: String
    public let repetitionsPerMode: Int
    public let seed: UInt64

    public init(
        schemaVersion: Int = Self.currentSchemaVersion,
        runID: String,
        policyID: String = Self.requiredPolicyID,
        modes: [String] = Self.requiredModes,
        variant: String = Self.requiredVariant,
        length: String = Self.requiredLength,
        repetitionsPerMode: Int = Self.requiredRepetitionsPerMode,
        seed: UInt64 = Self.requiredSeed
    ) {
        self.schemaVersion = schemaVersion
        self.runID = runID
        self.policyID = policyID
        self.modes = modes
        self.variant = variant
        self.length = length
        self.repetitionsPerMode = repetitionsPerMode
        self.seed = seed
    }

    public static func decodeAndValidate(_ json: String) throws -> IOSMemoryQualificationSpec {
        guard let data = json.data(using: .utf8) else {
            throw IOSMemoryQualificationPlanError.invalidJSON
        }
        let spec: IOSMemoryQualificationSpec
        do {
            spec = try JSONDecoder().decode(IOSMemoryQualificationSpec.self, from: data)
        } catch {
            throw IOSMemoryQualificationPlanError.invalidJSON
        }
        try spec.validate()
        return spec
    }

    public func validate() throws {
        guard schemaVersion == Self.currentSchemaVersion else {
            throw IOSMemoryQualificationPlanError.contractDrift("schemaVersion")
        }
        guard Self.isSafeRunID(runID) else {
            throw IOSMemoryQualificationPlanError.invalidRunID
        }
        guard policyID == Self.requiredPolicyID else {
            throw IOSMemoryQualificationPlanError.contractDrift("policyID")
        }
        guard modes == Self.requiredModes else {
            throw IOSMemoryQualificationPlanError.contractDrift("modes")
        }
        guard variant == Self.requiredVariant else {
            throw IOSMemoryQualificationPlanError.contractDrift("variant")
        }
        guard length == Self.requiredLength else {
            throw IOSMemoryQualificationPlanError.contractDrift("length")
        }
        guard repetitionsPerMode == Self.requiredRepetitionsPerMode else {
            throw IOSMemoryQualificationPlanError.contractDrift("repetitionsPerMode")
        }
        guard seed == Self.requiredSeed else {
            throw IOSMemoryQualificationPlanError.contractDrift("seed")
        }
    }

    public var takes: [IOSMemoryQualificationTake] {
        var result: [IOSMemoryQualificationTake] = []
        for mode in modes {
            for repetition in 0..<repetitionsPerMode {
                result.append(
                    IOSMemoryQualificationTake(
                        takeIndex: result.count + 1,
                        mode: mode,
                        variant: variant,
                        length: length,
                        repetition: repetition,
                        cell: "\(mode)/\(variant)/\(length)/retained#\(repetition)"
                    )
                )
            }
        }
        return result
    }

    private static func isSafeRunID(_ value: String) -> Bool {
        guard (1...96).contains(value.count) else { return false }
        return value.unicodeScalars.allSatisfy { scalar in
            CharacterSet.alphanumerics.contains(scalar) || scalar == "-" || scalar == "_"
        }
    }
}

public struct IOSMemoryQualificationTake: Codable, Equatable, Sendable {
    public let takeIndex: Int
    public let mode: String
    public let variant: String
    public let length: String
    public let repetition: Int
    public let cell: String

    public init(
        takeIndex: Int,
        mode: String,
        variant: String,
        length: String,
        repetition: Int,
        cell: String
    ) {
        self.takeIndex = takeIndex
        self.mode = mode
        self.variant = variant
        self.length = length
        self.repetition = repetition
        self.cell = cell
    }
}

public enum IOSMemoryQualificationPlanError: LocalizedError, Equatable {
    case invalidJSON
    case invalidRunID
    case contractDrift(String)

    public var errorDescription: String? {
        switch self {
        case .invalidJSON:
            "memory qualification plan is not valid bounded JSON"
        case .invalidRunID:
            "memory qualification runID must contain only letters, numbers, '-' or '_'"
        case .contractDrift(let field):
            "memory qualification plan differs from retained-memory-v1 at \(field)"
        }
    }
}

/// Terminal, privacy-safe failure marker for the retained-memory qualification.
///
/// This deliberately carries no prompt, voice description, path, raw error, device
/// identity, or exception text. The shell only needs a bounded reason code and the
/// last public matrix position so it can stop polling immediately without treating a
/// failed run as publishable evidence.
public struct IOSMemoryQualificationFailureStatus: Codable, Equatable, Sendable {
    public static let currentSchemaVersion = 1
    public static let maximumEncodedBytes = 4_096

    public let schemaVersion: Int
    public let status: String
    public let runID: String
    public let policyID: String
    public let failedAt: String
    public let failureCode: IOSMemoryQualificationFailureCode
    public let completedTakeCount: Int
    public let expectedTakeCount: Int
    public let failedTakeIndex: Int?
    public let failedCell: String?

    public init(
        runID: String,
        failedAt: String,
        failureCode: IOSMemoryQualificationFailureCode,
        completedTakeCount: Int,
        failedTakeIndex: Int? = nil,
        failedCell: String? = nil
    ) {
        schemaVersion = Self.currentSchemaVersion
        status = "failed"
        self.runID = runID
        policyID = IOSMemoryQualificationSpec.requiredPolicyID
        self.failedAt = failedAt
        self.failureCode = failureCode
        self.completedTakeCount = completedTakeCount
        expectedTakeCount = IOSMemoryQualificationSpec.requiredModes.count
            * IOSMemoryQualificationSpec.requiredRepetitionsPerMode
        self.failedTakeIndex = failedTakeIndex
        self.failedCell = failedCell
    }

    public func validate() throws {
        guard schemaVersion == Self.currentSchemaVersion else {
            throw IOSMemoryQualificationPlanError.contractDrift("failure.schemaVersion")
        }
        guard status == "failed" else {
            throw IOSMemoryQualificationPlanError.contractDrift("failure.status")
        }
        guard isSafeFailureRunID(runID) else {
            throw IOSMemoryQualificationPlanError.invalidRunID
        }
        guard policyID == IOSMemoryQualificationSpec.requiredPolicyID else {
            throw IOSMemoryQualificationPlanError.contractDrift("failure.policyID")
        }
        guard (0...expectedTakeCount).contains(completedTakeCount),
              expectedTakeCount == 9 else {
            throw IOSMemoryQualificationPlanError.contractDrift("failure.takeCount")
        }
        if let failedTakeIndex {
            guard (1...expectedTakeCount).contains(failedTakeIndex) else {
                throw IOSMemoryQualificationPlanError.contractDrift("failure.failedTakeIndex")
            }
        }
        if let failedCell {
            let allowedCells = Set(
                IOSMemoryQualificationSpec(runID: runID).takes.map(\.cell)
            )
            guard allowedCells.contains(failedCell) else {
                throw IOSMemoryQualificationPlanError.contractDrift("failure.failedCell")
            }
        }
        guard (1...40).contains(failedAt.utf8.count),
              failedAt.unicodeScalars.allSatisfy({ scalar in
                  scalar.value <= 0x7f
                      && !CharacterSet.whitespacesAndNewlines.contains(scalar)
              }) else {
            throw IOSMemoryQualificationPlanError.contractDrift("failure.failedAt")
        }
    }

    private func isSafeFailureRunID(_ value: String) -> Bool {
        guard (1...96).contains(value.count) else { return false }
        return value.unicodeScalars.allSatisfy { scalar in
            CharacterSet.alphanumerics.contains(scalar) || scalar == "-" || scalar == "_"
        }
    }
}

public enum IOSMemoryQualificationFailureCode: String, Codable, Equatable, Sendable {
    case invalidPlan = "invalid_plan"
    case runIdentityMismatch = "run_identity_mismatch"
    case telemetryUnavailable = "telemetry_unavailable"
    case cloneVoiceUnavailable = "clone_voice_unavailable"
    case corpusUnavailable = "corpus_unavailable"
    case modeUnavailable = "mode_unavailable"
    case fixtureUnavailable = "fixture_unavailable"
    case takeIdentityUnavailable = "take_identity_unavailable"
    case generationFailed = "generation_failed"
    case outputValidationFailed = "output_validation_failed"
    case telemetryValidationFailed = "telemetry_validation_failed"
    case telemetryRowCountInvalid = "telemetry_row_count_invalid"
    case telemetryIdentityInvalid = "telemetry_identity_invalid"
    case telemetryFinishInvalid = "telemetry_finish_invalid"
    case telemetryRunIdentityInvalid = "telemetry_run_identity_invalid"
    case telemetryOutputInvalid = "telemetry_output_invalid"
    case telemetryMemoryEvidenceIncomplete = "telemetry_memory_evidence_incomplete"
    case telemetrySampleSidecarUnavailable = "telemetry_sample_sidecar_unavailable"
    case telemetrySampleSidecarInvalid = "telemetry_sample_sidecar_invalid"
    case telemetryBoundaryIncomplete = "telemetry_boundary_incomplete"
    case outputMirrorFailed = "output_mirror_failed"
    case interrupted
    case incompletePlan = "incomplete_plan"
    case resultWriteFailed = "result_write_failed"
    /// PA-17: the Clone takes were refused because the phone's visible Settings
    /// voice-cloning consent is not recorded (the same reason as fixture enrollment).
    case cloneConsentNotRecorded = "clone-consent-not-recorded"
}
