import Foundation

/// Privacy-reduced, bounded diagnostics for generation failures.
///
/// The log deliberately stores an allowlisted classification rather than error text,
/// stack symbols, prompts, transcripts, paths, URLs, or arbitrary metadata. It is
/// enabled only with the normal telemetry gate and is intended for local support.
public final class GenerationFailureDiagnosticLogger: @unchecked Sendable {
    public static let shared = GenerationFailureDiagnosticLogger()

    public static let defaultMaxBytes = 256 * 1_024
    public static let defaultMaxEntries = 200

    private let lock = NSLock()
    private let encoder: JSONEncoder
    private let fixedFileURL: URL?
    private let maxBytes: Int
    private let maxEntries: Int
    private let ignoresTelemetryGate: Bool
    private let fileName = "generation-failures.jsonl"

    /// Internal configuration exists so deterministic tests can use an isolated file
    /// without enabling app telemetry or resolving a user Documents directory.
    init(
        fileURL: URL? = nil,
        maxBytes: Int = GenerationFailureDiagnosticLogger.defaultMaxBytes,
        maxEntries: Int = GenerationFailureDiagnosticLogger.defaultMaxEntries,
        ignoresTelemetryGate: Bool = false
    ) {
        let encoder = JSONEncoder()
        encoder.outputFormatting = .sortedKeys
        encoder.dateEncodingStrategy = .iso8601
        self.encoder = encoder
        self.fixedFileURL = fileURL
        self.maxBytes = max(1, maxBytes)
        self.maxEntries = max(1, maxEntries)
        self.ignoresTelemetryGate = ignoresTelemetryGate
    }

    /// Records an allowlisted envelope for a generation failure. User-facing and
    /// underlying error strings are accepted for source compatibility but never stored.
    public func log(
        surfacedMessage _: String,
        stage: String?,
        underlyingError: Error,
        request: GenerationRequest? = nil,
        receipt: GenerationRequestReceipt? = nil,
        appSupportDirectory: URL? = nil
    ) {
        guard ignoresTelemetryGate || TelemetryGate.resolvedEnabled else { return }
        guard let url = resolvedFileURL(appSupportDirectory: appSupportDirectory) else { return }

        let metadata = Self.errorMetadata(for: underlyingError)
        let entry = GenerationFailureJournalEntry(
            schemaVersion: 3,
            timestamp: Date(),
            errorCode: metadata.code,
            classification: metadata.classification.rawValue,
            stage: Self.allowlistedStage(stage),
            requestMode: request.map { $0.mode.rawValue },
            modelID: request.flatMap { Self.allowlistedIdentifier($0.modelID) },
            textLength: request.map { $0.text.count },
            shouldStream: request?.shouldStream,
            generationID: receipt?.generationID,
            generationIdentityDigest: receipt?.generationIdentityDigest,
            requestIdentityDigest: receipt?.requestIdentityDigest,
            sessionIdentityDigest: receipt?.sessionIdentityDigest,
            prewarmIdentityDigest: receipt?.prewarmIdentityDigest,
            retryAttempt: receipt?.retryAttempt,
            operationGeneration: receipt?.operationGeneration,
            requestReceipt: receipt
        )

        lock.lock()
        defer { lock.unlock() }

        do {
            try FileManager.default.createDirectory(
                at: url.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            Self.excludeFromBackup(url.deletingLastPathComponent())
            var line = try encoder.encode(entry)
            line.append(0x0A)
            if FileManager.default.fileExists(atPath: url.path) {
                let handle = try FileHandle(forWritingTo: url)
                defer { try? handle.close() }
                try handle.seekToEnd()
                try handle.write(contentsOf: line)
            } else {
                try line.write(to: url, options: .atomic)
            }
            Self.excludeFromBackup(url)
            try pruneLocked(at: url)
            // Atomic retention rewrites replace the inode and therefore its
            // resource values. Re-apply the backup exclusion afterward.
            Self.excludeFromBackup(url)
        } catch {
            // Best-effort: diagnostics must never alter generation behavior.
        }
    }

    /// Removes the bounded local support log without requiring telemetry to be enabled.
    public func clear(appSupportDirectory: URL? = nil) {
        guard let url = resolvedFileURL(appSupportDirectory: appSupportDirectory) else { return }
        lock.lock()
        defer { lock.unlock() }
        try? FileManager.default.removeItem(at: url)
    }

    public func read(appSupportDirectory: URL? = nil) -> [GenerationFailureJournalEntry] {
        guard let url = resolvedFileURL(appSupportDirectory: appSupportDirectory) else { return [] }
        lock.lock()
        defer { lock.unlock() }
        guard let data = try? Data(contentsOf: url) else { return [] }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return data.split(separator: 0x0A).compactMap {
            try? decoder.decode(GenerationFailureJournalEntry.self, from: Data($0))
        }
    }

    private func resolvedFileURL(appSupportDirectory: URL?) -> URL? {
        if let fixedFileURL { return fixedFileURL }
        return appSupportDirectory?
            .appendingPathComponent("diagnostics", isDirectory: true)
            .appendingPathComponent("engine", isDirectory: true)
            .appendingPathComponent(fileName, isDirectory: false)
    }

    private static func excludeFromBackup(_ url: URL) {
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        var mutableURL = url
        try? mutableURL.setResourceValues(values)
    }

    private func pruneLocked(at url: URL) throws {
        let data = try Data(contentsOf: url)
        var lines = [UInt8](data)
            .split(separator: 0x0A, omittingEmptySubsequences: true)
            .map { Data($0) }
        while lines.count > maxEntries {
            lines.removeFirst()
        }
        func encodedSize(_ values: [Data]) -> Int {
            values.reduce(0) { $0 + $1.count + 1 }
        }
        while !lines.isEmpty && encodedSize(lines) > maxBytes {
            lines.removeFirst()
        }

        var bounded = Data()
        for line in lines {
            bounded.append(line)
            bounded.append(0x0A)
        }
        if bounded != data {
            try bounded.write(to: url, options: .atomic)
        }
    }

    public enum Classification: String, Codable, Sendable {
        case cancelled
        case model
        case invalidRequest = "invalid_request"
        case memory
        case audio
        case storage
        case network
        case integrity
        case runtime
        case unknown
    }

    public struct ErrorMetadata: Codable, Sendable {
        public let code: String
        public let classification: Classification
    }

    public static func errorMetadata(for error: Error) -> ErrorMetadata {
        if error is CancellationError {
            return ErrorMetadata(code: "generation.cancelled", classification: .cancelled)
        }

        if let engineError = error as? TTSEngineError {
            switch engineError {
            case .notInitialized:
                return ErrorMetadata(code: "engine.not_initialized", classification: .runtime)
            case .unknownModel:
                return ErrorMetadata(code: "model.unknown", classification: .model)
            case .modelUnavailable:
                return ErrorMetadata(code: "model.unavailable", classification: .model)
            case .unsupportedRequest:
                return ErrorMetadata(code: "request.unsupported", classification: .invalidRequest)
            case .generationFailed:
                return ErrorMetadata(code: "generation.failed", classification: .runtime)
            case .insufficientMemory:
                return ErrorMetadata(code: "memory.insufficient", classification: .memory)
            }
        }

        if let preparationError = error as? AudioPreparationError {
            switch preparationError {
            case .cancelled:
                return ErrorMetadata(code: "audio.cancelled", classification: .cancelled)
            case .missingInputFile:
                return ErrorMetadata(code: "audio.input_missing", classification: .audio)
            case .unsupportedInput:
                return ErrorMetadata(code: "audio.input_unsupported", classification: .audio)
            case .inputFileTooLarge:
                return ErrorMetadata(code: "audio.input_too_large", classification: .audio)
            case .inputDurationTooLong:
                return ErrorMetadata(code: "audio.input_too_long", classification: .audio)
            case .decodeTimedOut:
                return ErrorMetadata(code: "audio.decode_timeout", classification: .audio)
            case .missingOutputDirectory, .failedToCreateOutputDirectory, .failedToCreateOutput:
                return ErrorMetadata(code: "storage.output_unavailable", classification: .storage)
            case .failedToReadAudio, .conversionFailed:
                return ErrorMetadata(code: "audio.processing_failed", classification: .audio)
            }
        }

        if let documentError = error as? DocumentIOError {
            switch documentError {
            case .missingSource:
                return ErrorMetadata(code: "storage.source_missing", classification: .storage)
            case .failedToCreateDirectory, .failedToCopy:
                return ErrorMetadata(code: "storage.write_failed", classification: .storage)
            }
        }

        if let downloadError = error as? HuggingFaceDownloader.DownloadError {
            switch downloadError {
            case .cancelled:
                return ErrorMetadata(code: "download.cancelled", classification: .cancelled)
            case .integrityCheckFailed:
                return ErrorMetadata(code: "download.integrity_failed", classification: .integrity)
            case .invalidRemotePath, .invalidLocalDestination:
                return ErrorMetadata(code: "download.invalid_path", classification: .invalidRequest)
            case .httpError, .fileDownloadFailed, .rangeUnsupported, .apiError:
                return ErrorMetadata(code: "download.transfer_failed", classification: .network)
            case .chunkAssemblyFailed:
                return ErrorMetadata(code: "download.assembly_failed", classification: .storage)
            }
        }

        if let urlError = error as? URLError {
            if urlError.code == .cancelled {
                return ErrorMetadata(code: "network.cancelled", classification: .cancelled)
            }
            return ErrorMetadata(code: "network.request_failed", classification: .network)
        }

        if let runtimeError = error as? NativeRuntimeError {
            switch runtimeError.failureCode {
            case .audioQualityRejected:
                return ErrorMetadata(code: runtimeError.failureCode.rawValue, classification: .audio)
            case .generationIncomplete:
                return ErrorMetadata(code: runtimeError.failureCode.rawValue, classification: .model)
            case .runtimeFailed:
                return ErrorMetadata(code: runtimeError.failureCode.rawValue, classification: .runtime)
            }
        }

        let cocoaError = error as NSError
        if cocoaError.domain == NSCocoaErrorDomain {
            switch CocoaError.Code(rawValue: cocoaError.code) {
            case .fileWriteOutOfSpace:
                return ErrorMetadata(code: "storage.full", classification: .storage)
            case .fileReadNoPermission, .fileWriteNoPermission, .fileWriteVolumeReadOnly:
                return ErrorMetadata(code: "storage.permission_denied", classification: .storage)
            default:
                break
            }
        }

        return ErrorMetadata(code: "generation.unknown", classification: .unknown)
    }

    private static func allowlistedStage(_ value: String?) -> String? {
        guard let value else { return nil }
        return [
            "prepared cache validation": "prepared_cache_validation",
            "prepared cache rebuild": "prepared_cache_rebuild",
            "tokenizer preparation": "tokenizer_preparation",
            "native model load": "model_load",
            "model warm-up": "prewarm",
            "clone preparation": "clone_preparation",
            "generation startup": "stream_startup",
            "first stream chunk": "first_chunk",
            "stream generation ended": "stream_generation_ended",
            "generation completion": "stream_completed",
            "generation failure": "stream_failed",
            "runtime unload": "unload",
        ][value] ?? "unknown"
    }

    private static func allowlistedIdentifier(_ value: String) -> String? {
        guard value.range(
            of: #"^pro_(custom|design|clone)(_(speed|quality))?$"#,
            options: .regularExpression
        ) != nil else {
            return nil
        }
        return value
    }

}

public struct GenerationFailureJournalEntry: Codable, Sendable {
    public let schemaVersion: Int
    public let timestamp: Date
    public let errorCode: String
    public let classification: String
    public let stage: String?
    public let requestMode: String?
    public let modelID: String?
    public let textLength: Int?
    public let shouldStream: Bool?
    public let generationID: String?
    public let generationIdentityDigest: String?
    public let requestIdentityDigest: String?
    public let sessionIdentityDigest: String?
    public let prewarmIdentityDigest: String?
    public let retryAttempt: Int?
    public let operationGeneration: UInt64?
    /// Complete privacy-safe receipt for schema-v3 attempt reconstruction.
    /// Schema-v2 rows decode this as nil.
    public let requestReceipt: GenerationRequestReceipt?

    public init(
        schemaVersion: Int,
        timestamp: Date,
        errorCode: String,
        classification: String,
        stage: String?,
        requestMode: String?,
        modelID: String?,
        textLength: Int?,
        shouldStream: Bool?,
        generationID: String? = nil,
        generationIdentityDigest: String? = nil,
        requestIdentityDigest: String? = nil,
        sessionIdentityDigest: String? = nil,
        prewarmIdentityDigest: String? = nil,
        retryAttempt: Int? = nil,
        operationGeneration: UInt64? = nil,
        requestReceipt: GenerationRequestReceipt? = nil
    ) {
        self.schemaVersion = schemaVersion
        self.timestamp = timestamp
        self.errorCode = errorCode
        self.classification = classification
        self.stage = stage
        self.requestMode = requestMode
        self.modelID = modelID
        self.textLength = textLength
        self.shouldStream = shouldStream
        self.generationID = generationID
        self.generationIdentityDigest = generationIdentityDigest
        self.requestIdentityDigest = requestIdentityDigest
        self.sessionIdentityDigest = sessionIdentityDigest
        self.prewarmIdentityDigest = prewarmIdentityDigest
        self.retryAttempt = retryAttempt
        self.operationGeneration = operationGeneration
        self.requestReceipt = requestReceipt
    }
}
