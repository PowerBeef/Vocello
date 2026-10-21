import Foundation

/// The class of a failure, which fixes its exit status (`config/cli-contract/v1/exit-codes.json`).
public enum CLIErrorCategory: String, Codable, Sendable, CaseIterable {
    case failure
    case usage
    case notFound = "not_found"
    case precondition
    case output
    case io
    case transient
    case permission
    case config
    case cancelled

    /// The process exit status for the category. A cancellation exits 128 plus
    /// the signal that ended the command (130 for SIGINT, 143 for SIGTERM).
    public var exitCode: Int32 {
        switch self {
        case .failure: return 1
        case .usage: return 2
        case .notFound: return 66
        case .precondition: return 69
        case .output: return 73
        case .io: return 74
        case .transient: return 75
        case .permission: return 77
        case .config: return 78
        case .cancelled: return 130
        }
    }
}

/// Every error code the v1 machine contract can report. The table is canonical in
/// `config/cli-contract/v1/error-codes.json`; v1 only ever adds codes, never moves
/// one to another category or changes whether it is retryable.
public enum VocelloErrorCode: String, Codable, Sendable, CaseIterable {
    // failure (1)
    case generationFailed = "generation_failed"
    case qcRejected = "qc_rejected"
    case outputMissing = "output_missing"
    case assemblyFailed = "assembly_failed"
    case batchIncomplete = "batch_incomplete"
    case downloadFailed = "download_failed"
    case integrityFailed = "integrity_failed"
    case internalError = "internal_error"
    // usage (2)
    case usageError = "usage_error"
    case invalidInput = "invalid_input"
    case textTooLong = "text_too_long"
    case idempotencyConflict = "idempotency_conflict"
    case unsupportedContractVersion = "unsupported_contract_version"
    // not_found (66)
    case voiceNotFound = "voice_not_found"
    case speakerNotFound = "speaker_not_found"
    case modelUnknown = "model_unknown"
    case historyItemNotFound = "history_item_not_found"
    case inputFileNotFound = "input_file_not_found"
    // precondition (69)
    case modelNotInstalled = "model_not_installed"
    case speechUnavailable = "speech_unavailable"
    // output (73)
    case outputUnavailable = "output_unavailable"
    // io (74)
    case storageFull = "storage_full"
    case ioError = "io_error"
    // transient (75)
    case engineBusy = "engine_busy"
    case storeBusy = "store_busy"
    case memoryPressure = "memory_pressure"
    case insufficientMemory = "insufficient_memory"
    case requestInProgress = "request_in_progress"
    case networkUnavailable = "network_unavailable"
    // permission (77)
    case consentRequired = "consent_required"
    case pathNotAllowed = "path_not_allowed"
    // config (78)
    case configError = "config_error"
    case historySchemaNewer = "history_schema_newer"
    // cancelled (130/143)
    case cancelled

    public var category: CLIErrorCategory {
        switch self {
        case .generationFailed, .qcRejected, .outputMissing, .assemblyFailed, .batchIncomplete,
             .downloadFailed, .integrityFailed, .internalError:
            return .failure
        case .usageError, .invalidInput, .textTooLong, .idempotencyConflict, .unsupportedContractVersion:
            return .usage
        case .voiceNotFound, .speakerNotFound, .modelUnknown, .historyItemNotFound, .inputFileNotFound:
            return .notFound
        case .modelNotInstalled, .speechUnavailable:
            return .precondition
        case .outputUnavailable:
            return .output
        case .storageFull, .ioError:
            return .io
        case .engineBusy, .storeBusy, .memoryPressure, .insufficientMemory, .requestInProgress,
             .networkUnavailable:
            return .transient
        case .consentRequired, .pathNotAllowed:
            return .permission
        case .configError, .historySchemaNewer:
            return .config
        case .cancelled:
            return .cancelled
        }
    }

    /// A later identical request may succeed: exactly the transient class.
    public var retryable: Bool { category == .transient }

    public var exitCode: Int32 { category.exitCode }
}
