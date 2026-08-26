import Foundation
import Synchronization

/// HTTPS and host boundary applied to initial artifact requests and every
/// URLSession redirect. Exact initial hosts come from the signed/bundled
/// catalog configuration; redirect suffixes cover the content-distribution
/// domains explicitly owned by that provider.
public struct ModelArtifactURLPolicy: Equatable, Sendable {
    public let allowedInitialHosts: Set<String>
    public let allowedRedirectHostSuffixes: Set<String>

    public init(
        allowedInitialHosts: Set<String>,
        allowedRedirectHostSuffixes: Set<String> = []
    ) {
        self.allowedInitialHosts = Set(allowedInitialHosts.map { $0.lowercased() })
        self.allowedRedirectHostSuffixes = Set(allowedRedirectHostSuffixes.map { $0.lowercased() })
    }

    public func allowsInitialRequest(_ url: URL) -> Bool {
        guard let host = secureHost(for: url) else { return false }
        return allowedInitialHosts.contains(host)
    }

    public func allowsRedirect(from sourceURL: URL?, to destinationURL: URL) -> Bool {
        guard let sourceURL,
              let sourceHost = secureHost(for: sourceURL),
              allowsArtifactHost(sourceHost),
              let destinationHost = secureHost(for: destinationURL) else {
            return false
        }
        return allowsArtifactHost(destinationHost)
    }

    private func allowsArtifactHost(_ host: String) -> Bool {
        if allowedInitialHosts.contains(host) { return true }
        return allowedRedirectHostSuffixes.contains { suffix in
            host == suffix || host.hasSuffix(".\(suffix)")
        }
    }

    private func secureHost(for url: URL) -> String? {
        guard url.scheme?.lowercased() == "https",
              url.user == nil,
              url.password == nil,
              url.port == nil || url.port == 443,
              let host = url.host?.lowercased(),
              !host.isEmpty,
              host != "localhost",
              !host.hasSuffix(".local"),
              !Self.isIPAddress(host) else {
            return nil
        }
        return host
    }

    private static func isIPAddress(_ host: String) -> Bool {
        if host.contains(":"), host.unicodeScalars.allSatisfy({
            CharacterSet(charactersIn: "0123456789abcdefABCDEF:").contains($0)
        }) {
            return true
        }
        let components = host.split(separator: ".", omittingEmptySubsequences: false)
        return components.count == 4 && components.allSatisfy {
            guard let value = Int($0) else { return false }
            return (0...255).contains(value)
        }
    }
}

/// Stable identity encoded in `URLSessionTask.taskDescription`. It deliberately contains no URL
/// or filesystem path so it is safe to persist and use when adopting background tasks.
///
/// Schema v2 adds optional byte-range qualification so one logical file may be transferred as
/// N chunk tasks that each survive background-session relaunch adoption. A whole-file identity
/// leaves both range fields nil; a chunk identity carries the inclusive `[rangeStart, rangeEnd]`
/// it transfers while `expectedSize`/`expectedSHA256` remain the WHOLE FILE's values (chunk
/// verification happens at assembly against the full file, never per range). v1 descriptions
/// fail decode closed, so tasks from a pre-v2 build are cancelled by reconciliation and their
/// requests restart cleanly.
public struct ModelDownloadTaskIdentity: Codable, Equatable, Hashable, Sendable {
    public static let currentSchemaVersion = 2

    public let schemaVersion: Int
    public let logicalRequestID: String
    public let modelID: String
    public let artifactVersion: String
    public let relativePath: String
    public let expectedSize: Int64
    public let expectedSHA256: String?
    public let rangeStart: Int64?
    public let rangeEnd: Int64?

    public init(
        logicalRequestID: String,
        modelID: String,
        artifactVersion: String,
        relativePath: String,
        expectedSize: Int64,
        expectedSHA256: String?,
        rangeStart: Int64? = nil,
        rangeEnd: Int64? = nil
    ) {
        self.schemaVersion = Self.currentSchemaVersion
        self.logicalRequestID = logicalRequestID
        self.modelID = modelID
        self.artifactVersion = artifactVersion
        self.relativePath = relativePath
        self.expectedSize = expectedSize
        self.expectedSHA256 = expectedSHA256
        self.rangeStart = rangeStart
        self.rangeEnd = rangeEnd
    }

    public var encodedTaskDescription: String? {
        guard isValidProductionIdentity else { return nil }
        guard let data = try? JSONEncoder().encode(self) else { return nil }
        return data.base64EncodedString()
    }

    public static func decode(taskDescription: String?) -> Self? {
        guard let taskDescription,
              let data = Data(base64Encoded: taskDescription),
              let identity = try? JSONDecoder().decode(Self.self, from: data),
              identity.schemaVersion == currentSchemaVersion,
              identity.isValidProductionIdentity else {
            return nil
        }
        return identity
    }

    /// Background adoption is a production trust boundary. A task without an
    /// immutable artifact identity, exact size, safe path, and SHA-256 may
    /// finish in its current process, but it can never be adopted after a
    /// relaunch. A chunk identity must carry a coherent in-bounds byte range;
    /// a half-specified range is invalid.
    public var isValidProductionIdentity: Bool {
        schemaVersion == Self.currentSchemaVersion
            && isSafeIdentityComponent(logicalRequestID)
            && isSafeIdentityComponent(modelID)
            && isSafeIdentityComponent(artifactVersion)
            && isSafeRelativeArtifactPath(relativePath)
            && expectedSize > 0
            && isLowercaseSHA256(expectedSHA256)
            && hasValidRangeQualification
    }

    private var hasValidRangeQualification: Bool {
        switch (rangeStart, rangeEnd) {
        case (nil, nil):
            return true
        case let (start?, end?):
            return start >= 0 && start <= end && end < expectedSize
        default:
            return false
        }
    }

    /// One reconciliation slot per transferable unit: the relative path for a
    /// whole-file task, a range-qualified form for a chunk task. Chunk keys start
    /// with `/`, which a validated relative artifact path never does, so a chunk
    /// key can never collide with any whole-file key.
    public var reconciliationKey: String {
        guard let rangeStart, let rangeEnd else { return relativePath }
        return Self.chunkReconciliationKey(relativePath: relativePath, start: rangeStart, end: rangeEnd)
    }

    public static func chunkReconciliationKey(relativePath: String, start: Int64, end: Int64) -> String {
        "/range/\(start)-\(end)/\(relativePath)"
    }
}

private func isSafeIdentityComponent(_ value: String) -> Bool {
    !value.isEmpty
        && value == value.trimmingCharacters(in: .whitespacesAndNewlines)
        && !value.contains("/")
        && !value.contains("\\")
        && !value.contains("://")
        && !value.unicodeScalars.contains(where: { CharacterSet.controlCharacters.contains($0) })
}

private func isSafeRelativeArtifactPath(_ value: String) -> Bool {
    guard !value.isEmpty,
          value == value.trimmingCharacters(in: .whitespacesAndNewlines),
          !value.hasPrefix("/"),
          !value.contains("\\"),
          value.removingPercentEncoding == value else {
        return false
    }
    let components = value.split(separator: "/", omittingEmptySubsequences: false)
    return !components.isEmpty && components.allSatisfy { !$0.isEmpty && $0 != "." && $0 != ".." }
}

private func isLowercaseSHA256(_ value: String?) -> Bool {
    guard let value, value.count == 64 else { return false }
    return value.unicodeScalars.allSatisfy {
        CharacterSet(charactersIn: "0123456789abcdef").contains($0)
    }
}

public struct ModelDownloadRequestIdentity: Equatable, Hashable, Sendable {
    public let logicalRequestID: String
    public let modelID: String
    public let artifactVersion: String

    public init(logicalRequestID: String, modelID: String, artifactVersion: String) {
        self.logicalRequestID = logicalRequestID
        self.modelID = modelID
        self.artifactVersion = artifactVersion
    }
}

public struct ModelDownloadExistingTask: Equatable, Sendable {
    public let taskID: Int
    public let identity: ModelDownloadTaskIdentity?

    public init(taskID: Int, identity: ModelDownloadTaskIdentity?) {
        self.taskID = taskID
        self.identity = identity
    }
}

public struct ModelDownloadReconciliationPlan: Equatable, Sendable {
    /// Adopted live task per `ModelDownloadTaskIdentity.reconciliationKey` (the
    /// relative path for whole-file tasks; range-qualified for chunk tasks).
    public let adoptedTaskByReconciliationKey: [String: Int]
    public let cancelledTaskIDs: [Int]
    public let missingReconciliationKeys: [String]
}

/// Small production-used state machine that makes UIKit background-event completion testable
/// without creating a URLSession or launching an app. The completion is released exactly once,
/// and only after URLSession has delivered all delegate events and durable postprocessing ended.
public struct ModelDownloadBackgroundCompletionGate: Equatable, Sendable {
    public private(set) var eventsFinished = false
    public private(set) var postprocessingFinished = false
    public private(set) var completionDelivered = false

    public init() {}

    public mutating func markEventsFinished() -> Bool {
        eventsFinished = true
        return takeCompletionIfReady()
    }

    public mutating func markPostprocessingFinished() -> Bool {
        postprocessingFinished = true
        return takeCompletionIfReady()
    }

    /// Start another logical request while preserving an already-delivered session event only
    /// when UIKit has not yet received its completion. A fully delivered cycle starts cleanly.
    public mutating func resetForRequest() {
        postprocessingFinished = false
        if completionDelivered {
            eventsFinished = false
            completionDelivered = false
        }
    }

    private mutating func takeCompletionIfReady() -> Bool {
        guard eventsFinished, postprocessingFinished, !completionDelivered else { return false }
        completionDelivered = true
        return true
    }
}

/// Bounds cumulative URLSession progress ingress before it crosses into actor isolation. Native
/// download delegates can emit thousands of callbacks per second for multi-gigabyte artifacts;
/// forwarding each callback as an unstructured task can delay terminal delegate events long after
/// the final byte arrives. The next cumulative callback carries every skipped byte, and the exact
/// terminal count is always forwarded.
struct ModelDownloadDelegateProgressGate: Sendable {
    private struct Entry: Sendable {
        var bytes: Int64
        var uptime: TimeInterval
    }

    private var entries: [Int: Entry] = [:]

    mutating func shouldForward(
        taskID: Int,
        totalBytesWritten: Int64,
        totalBytesExpected: Int64,
        uptime: TimeInterval,
        minimumInterval: TimeInterval = 0.25
    ) -> Bool {
        let bytes = max(totalBytesWritten, 0)
        guard let previous = entries[taskID] else {
            entries[taskID] = Entry(bytes: bytes, uptime: uptime)
            return true
        }
        guard bytes > previous.bytes else { return false }

        let reachedExpectedTotal = totalBytesExpected > 0 && bytes >= totalBytesExpected
        guard reachedExpectedTotal || uptime - previous.uptime >= minimumInterval else {
            return false
        }
        entries[taskID] = Entry(bytes: bytes, uptime: uptime)
        return true
    }

    mutating func finish(taskID: Int) {
        entries.removeValue(forKey: taskID)
    }
}

/// Preserves URLSession's documented finish-before-completion ordering across the async actor
/// bridge. `didFinishDownloadingTo` stages the durable file first; `didCompleteWithError` awaits
/// that exact operation before it resumes or fails the caller continuation.
final class ModelDownloadDelegateTerminalSequencer: Sendable {
    private let pendingStages = Mutex<[Int: Task<Void, Never>]>([:])

    func stage(taskID: Int, operation: @escaping @Sendable () async -> Void) {
        pendingStages.withLock { stages in
            let predecessor = stages[taskID]
            stages[taskID] = Task(priority: .userInitiated) {
                await predecessor?.value
                await operation()
            }
        }
    }

    @discardableResult
    func complete(
        taskID: Int,
        operation: @escaping @Sendable () async -> Void
    ) -> Task<Void, Never> {
        let predecessor = pendingStages.withLock { stages in
            stages.removeValue(forKey: taskID)
        }
        return Task(priority: .userInitiated) {
            await predecessor?.value
            await operation()
        }
    }

    var pendingStageCount: Int {
        pendingStages.withLock { $0.count }
    }
}

/// Deterministic task-inventory reconciliation used by the live URLSession bridge and fake-task
/// tests. Exactly one valid task may own a reconciliation slot (a whole file, or one byte-range
/// chunk of a file); stale, unknown, and duplicate tasks are cancelled.
public enum ModelDownloadTaskReconciler {
    public static func plan(
        expected: [ModelDownloadTaskIdentity],
        existing: [ModelDownloadExistingTask]
    ) -> ModelDownloadReconciliationPlan {
        // Keys are unique by construction (one identity per file or per chunk range);
        // keep-first uniquing keeps a malformed expected list from trapping at runtime.
        let expectedByKey = Dictionary(
            expected.map { ($0.reconciliationKey, $0) },
            uniquingKeysWith: { first, _ in first }
        )
        var adopted: [String: Int] = [:]
        var cancelled: [Int] = []

        for task in existing.sorted(by: { $0.taskID < $1.taskID }) {
            guard let identity = task.identity,
                  identity.isValidProductionIdentity,
                  expectedByKey[identity.reconciliationKey] == identity,
                  adopted[identity.reconciliationKey] == nil else {
                cancelled.append(task.taskID)
                continue
            }
            adopted[identity.reconciliationKey] = task.taskID
        }

        return ModelDownloadReconciliationPlan(
            adoptedTaskByReconciliationKey: adopted,
            cancelledTaskIDs: cancelled.sorted(),
            missingReconciliationKeys: expectedByKey.keys.filter { adopted[$0] == nil }.sorted()
        )
    }
}

public enum ModelDownloadProgressReconciler {
    /// A relaunched or retried task may report fewer bytes than the durable ledger while it is
    /// being adopted. Preserve that ledger floor unless a clean retry explicitly invalidated
    /// bytes; a retry must expose the downloader's exact durable total rather than false 100%.
    public static func visibleBytes(
        current: Int64,
        persisted: Int64,
        total: Int64?,
        persistedBytesAreValid: Bool = true
    ) -> Int64 {
        let value = max(0, persistedBytesAreValid ? max(current, persisted) : current)
        guard let total, total > 0 else { return value }
        return min(value, total)
    }
}

/// Proof that one immutable staged file was read and verified in this process generation.
/// The receipt lets final installation avoid a second multi-gigabyte hash pass while still
/// invalidating on relaunch or any metadata change.
public struct VerifiedArtifactReceipt: Codable, Equatable, Sendable {
    public static let currentSchemaVersion = 1

    public let schemaVersion: Int
    public let relativePath: String
    public let artifactVersion: String
    public let expectedSize: Int64
    public let expectedSHA256: String?
    public let fileSize: Int64
    public let modificationTimeNanoseconds: Int64
    public let fileIdentifier: UInt64?
    public let verificationProcessGeneration: String

    public init(
        relativePath: String,
        artifactVersion: String,
        expectedSize: Int64,
        expectedSHA256: String?,
        fileSize: Int64,
        modificationTimeNanoseconds: Int64,
        fileIdentifier: UInt64?,
        verificationProcessGeneration: String
    ) {
        self.schemaVersion = Self.currentSchemaVersion
        self.relativePath = relativePath
        self.artifactVersion = artifactVersion
        self.expectedSize = expectedSize
        self.expectedSHA256 = expectedSHA256
        self.fileSize = fileSize
        self.modificationTimeNanoseconds = modificationTimeNanoseconds
        self.fileIdentifier = fileIdentifier
        self.verificationProcessGeneration = verificationProcessGeneration
    }

    public func matches(
        relativePath: String,
        artifactVersion: String,
        expectedSize: Int64,
        expectedSHA256: String?,
        fileSize: Int64,
        modificationTimeNanoseconds: Int64,
        fileIdentifier: UInt64?,
        processGeneration: String
    ) -> Bool {
        self.relativePath == relativePath
            && self.artifactVersion == artifactVersion
            && self.expectedSize == expectedSize
            && self.expectedSHA256 == expectedSHA256
            && self.fileSize == fileSize
            && self.modificationTimeNanoseconds == modificationTimeNanoseconds
            && self.fileIdentifier == fileIdentifier
            && verificationProcessGeneration == processGeneration
    }
}

public enum ModelDownloadRetryDisposition: Equatable, Sendable {
    case retry(afterSeconds: Double)
    case retryClean(afterSeconds: Double)
    case fail
    case cancelled
}

/// Pure retry classifier shared by the downloader and deterministic tests.
public enum ModelDownloadRetryPolicy {
    public static func disposition(
        error: Error,
        retryNumber: Int,
        integrityRetryAlreadyUsed: Bool,
        retryAfterSeconds: Double? = nil
    ) -> ModelDownloadRetryDisposition {
        if error is CancellationError {
            return .cancelled
        }

        if let downloadError = error as? HuggingFaceDownloader.DownloadError {
            switch downloadError {
            case .cancelled:
                return .cancelled
            case .integrityCheckFailed:
                guard !integrityRetryAlreadyUsed else { return .fail }
                return .retryClean(afterSeconds: boundedDelay(retryAfterSeconds ?? backoff(retryNumber)))
            case .httpError(let statusCode, _, let responseRetryAfter):
                if statusCode == 408 || statusCode == 429 || (500...599).contains(statusCode) {
                    return retryNumber <= 3
                        ? .retry(afterSeconds: boundedDelay(retryAfterSeconds ?? responseRetryAfter ?? backoff(retryNumber)))
                        : .fail
                }
                return .fail
            case .rangeUnsupported, .chunkAssemblyFailed:
                return retryNumber <= 3
                    ? .retryClean(afterSeconds: boundedDelay(backoff(retryNumber)))
                    : .fail
            case .fileDownloadFailed(_, let underlying):
                return dispositionForFoundationError(underlying, retryNumber: retryNumber)
            case .invalidRemotePath, .invalidLocalDestination, .apiError:
                return .fail
            }
        }

        return dispositionForFoundationError(error, retryNumber: retryNumber)
    }

    private static func dispositionForFoundationError(
        _ error: Error,
        retryNumber: Int
    ) -> ModelDownloadRetryDisposition {
        let nsError = error as NSError
        guard nsError.domain == NSURLErrorDomain else { return .fail }
        if nsError.code == NSURLErrorCancelled { return .cancelled }

        let permanentCodes: Set<Int> = [
            NSURLErrorServerCertificateUntrusted,
            NSURLErrorServerCertificateHasBadDate,
            NSURLErrorServerCertificateHasUnknownRoot,
            NSURLErrorServerCertificateNotYetValid,
            NSURLErrorSecureConnectionFailed,
            NSURLErrorClientCertificateRejected,
            NSURLErrorClientCertificateRequired,
            NSURLErrorCannotWriteToFile,
            NSURLErrorDataLengthExceedsMaximum,
            NSURLErrorFileDoesNotExist,
            NSURLErrorNoPermissionsToReadFile,
        ]
        guard !permanentCodes.contains(nsError.code), retryNumber <= 3 else { return .fail }

        let transientCodes: Set<Int> = [
            NSURLErrorTimedOut,
            NSURLErrorNetworkConnectionLost,
            NSURLErrorNotConnectedToInternet,
            NSURLErrorCannotConnectToHost,
            NSURLErrorCannotFindHost,
            NSURLErrorDNSLookupFailed,
            NSURLErrorResourceUnavailable,
            NSURLErrorInternationalRoamingOff,
            NSURLErrorCallIsActive,
            NSURLErrorDataNotAllowed,
        ]
        return transientCodes.contains(nsError.code)
            ? .retry(afterSeconds: boundedDelay(backoff(retryNumber)))
            : .fail
    }

    private static func backoff(_ retryNumber: Int) -> Double {
        min(pow(2, Double(max(0, retryNumber - 1))), 10)
    }

    private static func boundedDelay(_ seconds: Double) -> Double {
        min(max(seconds, 0), 300)
    }
}
