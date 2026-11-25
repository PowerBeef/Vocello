import Foundation
import QwenVoiceCore
import System

/// The contract's error object: `{code, category, exitCode, message, retryable,
/// retryAfterMs, hint, detail}`. Every key is always present; absent values are null.
public struct CLIErrorObject: Encodable, Sendable, Equatable {
    public let code: VocelloErrorCode
    public let message: String
    public let hint: String?
    public let detail: [String: CLIJSONValue]?
    public let retryAfterMs: Int?
    /// The exit status this failure ends the process with. A cancellation
    /// carries 128 plus its signal; every other code carries its category's.
    public let exitCode: Int32

    public init(
        code: VocelloErrorCode,
        message: String,
        hint: String? = nil,
        detail: [String: CLIJSONValue]? = nil,
        retryAfterMs: Int? = nil,
        exitCode: Int32? = nil
    ) {
        self.code = code
        self.message = message
        self.hint = hint
        self.detail = detail
        self.retryAfterMs = retryAfterMs
        self.exitCode = exitCode ?? code.exitCode
    }

    public var category: CLIErrorCategory { code.category }

    /// The failure a signalled command reports: the signal decides the exit
    /// status, so the report is a cancellation that keeps the failure it hid.
    public func signalled(by signal: Int32?) -> CLIErrorObject {
        guard let signal, signal == SIGINT || signal == SIGTERM, code != .cancelled else { return self }
        var report = CLIFailure.cancellation(signal: signal)
        var detail = report.detail ?? [:]
        detail["failure"] = .string(code.rawValue)
        report = CLIErrorObject(
            code: .cancelled, message: report.message, hint: nil, detail: detail, exitCode: report.exitCode
        )
        return report
    }
    public var retryable: Bool { code.retryable }

    private enum CodingKeys: String, CodingKey {
        case code, category, exitCode, message, retryable, retryAfterMs, hint, detail
    }

    public func encode(to encoder: any Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(code, forKey: .code)
        try container.encode(category, forKey: .category)
        try container.encode(exitCode, forKey: .exitCode)
        try container.encode(message, forKey: .message)
        try container.encode(retryable, forKey: .retryable)
        try encodeOrNull(retryAfterMs, forKey: .retryAfterMs, in: &container)
        try encodeOrNull(hint, forKey: .hint, in: &container)
        try encodeOrNull(detail, forKey: .detail, in: &container)
    }
}

func encodeOrNull<Value: Encodable, Key: CodingKey>(
    _ value: Value?, forKey key: Key, in container: inout KeyedEncodingContainer<Key>
) throws {
    if let value { try container.encode(value, forKey: key) } else { try container.encodeNil(forKey: key) }
}

/// Maps any error a command throws to the contract's typed error, from the
/// engine's existing typed failures. A message is the error's own description
/// (SEC-11: never its raw value, which can carry staged paths and userInfo); it
/// may name a file the caller passed.
public enum CLIFailure {
    /// `signal` is the signal that cancelled the command, when one did.
    public static func classify(_ error: any Error, signal: Int32? = nil) -> CLIErrorObject {
        if let error = error as? CLIError {
            return CLIErrorObject(code: error.code, message: error.description, hint: error.hint, detail: error.detail)
        }
        if error is CancellationError {
            return cancellation(signal: signal)
        }
        if let stopped = error as? CLIEngineCancellation {
            return CLIErrorObject(
                code: stopped.contractCode,
                message: stopped.errorDescription ?? stopped.errorCode,
                hint: stopped.contractCode == .memoryPressure
                    ? "retry once memory is free (quit other apps)" : "retry shortly",
                detail: ["reason": .string(stopped.errorCode)]
            )
        }
        if let consent = error as? VoiceCloningConsentRequiredError {
            return CLIErrorObject(
                code: .consentRequired,
                message: consent.message,
                hint: "pass --confirm-consent to confirm you own or have permission to clone this voice",
                detail: ["operation": .string(consent.operation == .enrollment ? "enrollment" : "generation")]
            )
        }
        if let download = error as? HuggingFaceDownloader.DownloadError {
            return classify(download, signal: signal)
        }
        // Before the network and file classes: a transfer or a write that ran out
        // of room carries the volume's error under another one.
        if isStorageFull(error) {
            return CLIErrorObject(code: .storageFull, message: message(of: error), hint: storageFullHint)
        }
        if error is DeliveryInstructionCellError || error is SpokenTextPlanningError || error is LongFormPlanningError {
            return CLIErrorObject(code: .invalidInput, message: message(of: error))
        }
        if error is ProductionModelCatalog.Error || error is ContractBackedModelRegistry.Error {
            return CLIErrorObject(code: .configError, message: message(of: error))
        }
        if let urlError = error as? URLError {
            return urlError.code == .cancelled
                ? cancellation(signal: signal)
                : CLIErrorObject(code: .networkUnavailable, message: message(of: error))
        }
        if let engineError = error as? TTSEngineError {
            switch engineError {
            case .unknownModel:
                return CLIErrorObject(code: .modelUnknown, message: message(of: error))
            case .unsupportedRequest:
                return CLIErrorObject(code: .invalidInput, message: message(of: error))
            case .modelUnavailable:
                return CLIErrorObject(
                    code: .modelNotInstalled, message: message(of: error),
                    hint: "install it with `vocello models install <id>` (see `vocello models list`)"
                )
            default:
                break
            }
        }
        if let reason = GenerationFailurePresentationReason(error) {
            return CLIErrorObject(
                code: code(for: reason),
                message: message(of: error),
                hint: hint(for: reason),
                detail: ["reason": .string(reason.rawValue)]
            )
        }
        let cocoa = error as NSError
        if cocoa.domain == NSCocoaErrorDomain {
            switch CocoaError.Code(rawValue: cocoa.code) {
            case .fileReadNoSuchFile, .fileNoSuchFile:
                return CLIErrorObject(code: .inputFileNotFound, message: message(of: error))
            default:
                if CocoaError.Code(rawValue: cocoa.code).isFileError {
                    return CLIErrorObject(code: .ioError, message: message(of: error))
                }
            }
        }
        return CLIErrorObject(code: .internalError, message: message(of: error))
    }

    /// A failed batch row's code: the error's contract code, with an error the
    /// contract cannot name reported as the generation failing.
    public static func rowCode(for error: any Error) -> VocelloErrorCode {
        let code = classify(error).code
        return code == .internalError ? .generationFailed : code
    }

    static let storageFullHint = "free some space on the volume, then retry"

    /// Whether `error`, or an error under it, says the volume is full: Cocoa's
    /// out-of-space code, ENOSPC or EDQUOT as a POSIX error or a System `Errno`,
    /// or Carbon `dskFulErr` (-34) / POSIX ENOSPC / EDQUOT under
    /// `NSOSStatusErrorDomain` or `com.apple.coreaudio.avfaudio`.
    static func isStorageFull(_ error: any Error, depth: Int = 0) -> Bool {
        if let posix = error as? Errno {
            return posix.rawValue == ENOSPC || posix.rawValue == EDQUOT
        }
        let cocoa = error as NSError
        if cocoa.domain == NSCocoaErrorDomain, cocoa.code == NSFileWriteOutOfSpaceError { return true }
        if cocoa.domain == NSPOSIXErrorDomain, cocoa.code == Int(ENOSPC) || cocoa.code == Int(EDQUOT) { return true }
        if cocoa.domain == NSOSStatusErrorDomain || cocoa.domain == "com.apple.coreaudio.avfaudio",
           cocoa.code == -34 || cocoa.code == Int(ENOSPC) || cocoa.code == Int(EDQUOT) {
            return true
        }
        guard depth < 4, let underlying = cocoa.userInfo[NSUnderlyingErrorKey] as? NSError else { return false }
        return isStorageFull(underlying, depth: depth + 1)
    }

    static func cancellation(signal: Int32?) -> CLIErrorObject {
        let signal = signal ?? SIGINT
        let name = signal == SIGTERM ? "SIGTERM" : signal == SIGINT ? "SIGINT" : "signal \(signal)"
        return CLIErrorObject(
            code: .cancelled,
            message: "cancelled by \(name); command cleanup completed",
            detail: ["signal": .string(name)],
            exitCode: 128 + signal
        )
    }

    private static func classify(_ error: HuggingFaceDownloader.DownloadError, signal: Int32?) -> CLIErrorObject {
        let text = message(of: error)
        // A full volume, read as the apps read it (the cause under a failed file, or
        // the failure's own words), is not a failed download: retrying cannot help.
        if ModelUpdateFailure.classify(error) == .space {
            return CLIErrorObject(code: .storageFull, message: text, hint: storageFullHint)
        }
        switch error {
        case .cancelled:
            return cancellation(signal: signal)
        case .integrityCheckFailed:
            return CLIErrorObject(code: .integrityFailed, message: text)
        case .httpError(let status, _, let retryAfter):
            guard status == 408 || status == 429 || status >= 500 else {
                return CLIErrorObject(code: .downloadFailed, message: text, detail: ["httpStatus": .integer(status)])
            }
            return CLIErrorObject(
                code: .networkUnavailable, message: text, detail: ["httpStatus": .integer(status)],
                retryAfterMs: retryAfter.map { Int(($0 * 1000).rounded()) }
            )
        case .fileDownloadFailed(_, let underlying):
            return underlying is URLError
                ? CLIErrorObject(code: .networkUnavailable, message: text)
                : CLIErrorObject(code: .downloadFailed, message: text)
        case .rangeUnsupported, .shortRange, .chunkAssemblyFailed, .invalidRemotePath,
             .invalidLocalDestination, .apiError:
            return CLIErrorObject(code: .downloadFailed, message: text)
        }
    }

    static func code(for reason: GenerationFailurePresentationReason) -> VocelloErrorCode {
        switch reason {
        case .memoryPressure: return .memoryPressure
        case .runtimeFailure, .preparationFailure, .generationLimit, .noAudioProduced: return .generationFailed
        case .scriptTooLongForTake: return .textTooLong
        case .disallowedVoiceImitation: return .invalidInput
        case .audioSilentGap, .audioNoSpeech, .audioUnstable, .audioQualityRejected: return .qcRejected
        case .insufficientMemory: return .insufficientMemory
        case .engineNotReady: return .internalError
        case .engineBusy, .engineReleasingMemory: return .engineBusy
        case .savedVoiceStoreBusy: return .storeBusy
        case .modelUnavailable: return .modelNotInstalled
        case .referenceAudioMissing: return .inputFileNotFound
        case .referenceAudioUnsupported, .referenceAudioTooLong, .referenceAudioUnreadable, .referenceAudioSilent:
            return .invalidInput
        case .storageFull: return .storageFull
        case .storageUnavailable: return .outputUnavailable
        }
    }

    private static func hint(for reason: GenerationFailurePresentationReason) -> String? {
        switch reason {
        case .memoryPressure, .insufficientMemory:
            return "free memory (quit other apps), then retry"
        case .engineBusy, .engineReleasingMemory:
            return "a take is running or memory is being released, in this or another Vocello process; retry shortly"
        case .savedVoiceStoreBusy:
            return "the saved voices are in use by another Vocello process; retry shortly"
        case .scriptTooLongForTake:
            return "run it as a long-form project: `vocello generate` does by default (--long-form auto)"
        case .disallowedVoiceImitation:
            return "describe vocal qualities instead of naming or imitating a real person"
        case .modelUnavailable:
            return "install it with `vocello models install <id>` (see `vocello models list`)"
        case .audioSilentGap, .audioNoSpeech, .audioUnstable, .audioQualityRejected:
            return "retry with another --seed, or rephrase the text"
        default:
            return nil
        }
    }

    private static func message(of error: any Error) -> String {
        (error as? LocalizedError)?.errorDescription ?? String(describing: type(of: error))
    }
}

private extension CocoaError.Code {
    var isFileError: Bool { (NSFileErrorMinimum ... NSFileErrorMaximum).contains(rawValue) }
}
