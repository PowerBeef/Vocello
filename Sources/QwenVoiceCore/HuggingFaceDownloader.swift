import CryptoKit
@preconcurrency import Foundation
import Synchronization

/// Downloads a HuggingFace model repository using native URLSession.
public final class HuggingFaceDownloader: NSObject, URLSessionDownloadDelegate {

    public enum DownloadPhase: String, Equatable, Sendable {
        case queued
        case waitingForConnectivity
        case downloading
        case retrying
        case verifying
        case installing
        case cancelling
    }

    public struct RepositoryProgress: Equatable, Sendable {
        public let downloadedBytes: Int64
        public let totalBytes: Int64
        public let completedFiles: Int
        public let totalFiles: Int
        public let bytesPerSecond: Int64?
        public let isStalled: Bool
        public let estimatedSecondsRemaining: Double?
        public let retryCount: Int
        public let statusMessage: String?
        public let phase: DownloadPhase
    }

    public struct TransferMetrics: Codable, Equatable, Sendable {
        public let relativePath: String?
        public let protocolName: String?
        public let redirectCount: Int
        public let reusedConnection: Bool
        public let cellular: Bool
        public let constrained: Bool
        public let expensive: Bool
        public let transferredBytes: Int64
        public let durationSeconds: Double
    }

    /// How byte-range chunk downloads map onto URLSessions. HTTP/2 and HTTP/3 prefer
    /// multiplexing every task for a host onto one connection, which would leave all
    /// chunks sharing a single connection's CDN throughput shaping. `.perWorker` gives
    /// each chunk worker its own foreground URLSession so chunks ride distinct
    /// connections. Ignored on background sessions, where every chunk task must ride
    /// the one background session so it survives process death.
    public enum ChunkSessionStrategy: Sendable {
        case shared
        case perWorker
    }

    /// Tunable download-engine parameters. Defaults match the shipping macOS/CLI profile:
    /// up to 6 files in flight, per-file byte-range chunking ON (the 2026-08-08 controlled
    /// comparison measured an 87% median transfer-time improvement: the CDN shapes
    /// throughput per connection, so the multi-gigabyte long pole must not ride a single
    /// stream), and the foreground URLSession capped at `maxConnectionsPerHost`. iOS also
    /// chunks by default (2026-08-11, maintainer call recorded in model-delivery.md): the
    /// mechanism is background-capable — range-qualified schema-v2 task identities survive
    /// relaunch adoption, and chunk transfers on a background session fan out to the
    /// daemon up front with a larger per-range size set by the caller (128 MiB).
    /// Chunking parameters: files at or above `chunkedDownloadThreshold` split into
    /// `chunkTargetSize` ranges drained by `chunkWorkerCount` workers, with a shrinking
    /// tail (quarter-size ranges over the final `chunkWorkerCount x chunkTargetSize`
    /// bytes) so the last ranges never leave one throttled connection running alone.
    public struct Configuration: Sendable {
        public var maxConcurrentFiles = 6
        public var chunkLargeFiles = true
        public var chunkedDownloadThreshold: Int64 = 96 * 1024 * 1024
        public var chunkTargetSize: Int64 = 64 * 1024 * 1024
        public var chunkWorkerCount = 4
        public var maxConnectionsPerHost = 6
        public var chunkSessionStrategy: ChunkSessionStrategy = .shared
        public var maxDownloadRetries = 3
        public init() {}
    }

    public enum DownloadError: LocalizedError {
        case cancelled
        case httpError(statusCode: Int, path: String, retryAfterSeconds: Double? = nil)
        case fileDownloadFailed(path: String, underlying: Error)
        case integrityCheckFailed(path: String, reason: String)
        case rangeUnsupported(path: String)
        case chunkAssemblyFailed(path: String, reason: String)
        case invalidRemotePath(String)
        case invalidLocalDestination(String)
        case apiError(String)

        public var errorDescription: String? {
            switch self {
            case .cancelled:
                return "Download cancelled"
            case .httpError(let code, let path, _):
                return "HTTP \(code) downloading \(path)"
            case .fileDownloadFailed(let path, let underlying):
                return "Failed to download \(path): \(underlying.localizedDescription)"
            case .integrityCheckFailed(let path, let reason):
                return "Downloaded file failed integrity checks for \(path): \(reason)"
            case .rangeUnsupported(let path):
                return "Server did not honor the byte-range request for \(path); retrying as a single stream"
            case .chunkAssemblyFailed(let path, let reason):
                return "Failed to assemble byte-range chunk for \(path): \(reason)"
            case .invalidRemotePath(let path):
                return "Rejected unsafe remote path: \(path)"
            case .invalidLocalDestination(let path):
                return "Rejected unsafe local destination: \(path)"
            case .apiError(let message):
                return message
            }
        }
    }

    public struct RepoFile: Sendable, Hashable {
        public let path: String
        public let size: Int64
        public let sha256: String?
        /// If set, download this file from this absolute URL instead of resolving it from
        /// `{resolveBaseURL}/{repo}/resolve/{revision}/{path}`. iOS passes its catalog's validated
        /// per-file URLs here (host allowlist enforced by `IOSModelDeliverySupport.downloadURL`).
        public let absoluteURL: URL?

        public init(path: String, size: Int64, sha256: String?, absoluteURL: URL? = nil) {
            self.path = path
            self.size = size
            self.sha256 = sha256
            self.absoluteURL = absoluteURL
        }
    }

    struct DownloadStateManifest: Codable, Equatable {
        let schemaVersion: Int
        let repo: String
        let revision: String
        let targetFolder: String
        let updatedAtUTC: String
        let files: [FileEntry]

        enum CodingKeys: String, CodingKey {
            case schemaVersion = "schema_version"
            case repo
            case revision
            case targetFolder = "target_folder"
            case updatedAtUTC = "updated_at_utc"
            case files
        }

        struct FileEntry: Codable, Equatable {
            let path: String
            let size: Int64
            let sha256: String?
        }
    }

    struct DownloadedTemporaryFile: Sendable {
        let url: URL
        let statusCode: Int?
        let retryAfterSeconds: Double?
        let contentRange: String?
    }

    final class RepositoryProgressHandlerBox: Sendable {
        let handler: @Sendable (RepositoryProgress) -> Void

        init(_ handler: @escaping @Sendable (RepositoryProgress) -> Void) {
            self.handler = handler
        }
    }

    final class TransferMetricsHandlerBox: Sendable {
        let handler: @Sendable (TransferMetrics) -> Void

        init(_ handler: @escaping @Sendable (TransferMetrics) -> Void) {
            self.handler = handler
        }
    }

    final class VerifiedArtifactHandlerBox: Sendable {
        let handler: @Sendable (VerifiedArtifactReceipt) async -> Void

        init(_ handler: @escaping @Sendable (VerifiedArtifactReceipt) async -> Void) {
            self.handler = handler
        }
    }

    /// Foundation has not annotated FileManager as Sendable. Confine that compatibility gap to
    /// one immutable adapter instead of making the downloader broadly unchecked.
    final class FileManagerBox: @unchecked Sendable {
        let value: FileManager

        init(_ value: FileManager) {
            self.value = value
        }
    }

    final class TaskCancellationBox: @unchecked Sendable {
        private let task: URLSessionDownloadTask
        private let resumeDataURL: URL?

        init(task: URLSessionDownloadTask, resumeDataURL: URL?) {
            self.task = task
            self.resumeDataURL = resumeDataURL
        }

        func cancelAndWait() async {
            await withCheckedContinuation { continuation in
                task.cancel { [resumeDataURL] resumeData in
                    guard let resumeDataURL,
                          let resumeData,
                          !resumeData.isEmpty else {
                        continuation.resume()
                        return
                    }
                    try? FileManager.default.createDirectory(
                        at: resumeDataURL.deletingLastPathComponent(),
                        withIntermediateDirectories: true
                    )
                    try? resumeData.write(to: resumeDataURL, options: .atomic)
                    continuation.resume()
                }
            }
        }
    }

    actor DownloadStateRegistry {
        private var isCancelled = false
        // Per-task handle so concurrent files can each be cancelled independently.
        private var activeCancellations: [Int: TaskCancellationBox] = [:]
        private var continuations: [Int: CheckedContinuation<DownloadedTemporaryFile, Error>] = [:]
        private var destinations: [Int: URL] = [:]
        // Maps a URLSession taskID -> the index of the file it is downloading, so the
        // delegate's per-task progress callbacks aggregate into per-file byte counters.
        private var taskFileIndex: [Int: Int] = [:]
        // Per-task bytes written (monotonic per URLSession task). A single-stream file has
        // one entry; a byte-range chunked file has one entry per in-flight chunk. The
        // repository total is the sum across all live tasks plus completed-file sizes, so
        // N chunks of one file aggregate correctly (a per-file monotonic max would not).
        private var taskBytes: [Int: Int64] = [:]
        private var completedFilesBytes: Int64 = 0
        private let repositoryProgressHandler: RepositoryProgressHandlerBox?
        private var repositoryTotalBytes: Int64 = 0
        private var repositoryTotalFiles = 0
        private var repositoryCompletedFiles = 0
        private var lastProgressAdvanceTime: TimeInterval?
        private var lastSpeedSampleTime: TimeInterval?
        private var lastSpeedSampleBytes: Int64 = 0
        private var lastMeasuredBytesPerSecond: Int64?
        private var lastProgressPublicationTime: TimeInterval?
        private var lastPublishedBytes: Int64 = -1
        private var lastPublishedPhase: DownloadPhase?
        private var phase: DownloadPhase = .downloading
        private var heartbeatTask: Task<Void, Never>?
        private var retryCount = 0
        private var statusMessage: String?
        private var verifyingFileCount = 0
        // A download file callback precedes task metrics and the terminal task callback.
        // Keep the durable file staged until didCompleteWithError so callers cannot publish
        // a success summary before URLSession has delivered its final metrics.
        private var stagedSuccessfulDownloads: [Int: (ModelDownloadTaskIdentity?, DownloadedTemporaryFile)] = [:]
        // Completion parking, expected identities, and adoption are all keyed by
        // `ModelDownloadTaskIdentity.reconciliationKey`: one slot per whole file or
        // per byte-range chunk, so N chunk tasks of one file never collide. The
        // parker's full identity travels with the file so a claim can require exact
        // identity equality — a key alone would let a newer artifact generation
        // claim a stale generation's bytes (the SHA gate would catch it, but only
        // after wasting the whole file's transfer).
        private var unclaimedCompletionsByKey:
            [String: (identity: ModelDownloadTaskIdentity, file: DownloadedTemporaryFile)] = [:]
        // Whole-file identities by URL (a chunked file's single-stream fallback and
        // resume paths look identities up by URL, which chunk identities would break).
        private var expectedTaskIdentityByURL: [URL: ModelDownloadTaskIdentity] = [:]
        // Every expected identity (whole-file and chunk) with its transfer URL.
        private var expectedEntriesByKey: [String: (url: URL, identity: ModelDownloadTaskIdentity)] = [:]
        private var adoptedTasksByKey: [String: URLSessionDownloadTask] = [:]
        private var backgroundCompletionGate = ModelDownloadBackgroundCompletionGate()
        private var verifiedReceiptsByPath: [String: VerifiedArtifactReceipt] = [:]

        /// Bytes counted so far: completed files (at their exact size) plus the live sum of
        /// in-flight task bytes (single-stream or chunk). Recomputed so retries and chunks
        /// both stay exact without a separate accumulated counter.
        private var repositoryDownloadedBytes: Int64 {
            completedFilesBytes + taskBytes.values.reduce(0, +)
        }

        init(repositoryProgressHandler: RepositoryProgressHandlerBox?) {
            self.repositoryProgressHandler = repositoryProgressHandler
        }

        func resetForNewRepositoryDownload(preserveUnclaimedCompletions: Bool) {
            isCancelled = false
            activeCancellations.removeAll()
            continuations.removeAll()
            destinations.removeAll()
            taskFileIndex.removeAll()
            taskBytes.removeAll()
            completedFilesBytes = 0
            repositoryTotalBytes = 0
            repositoryTotalFiles = 0
            repositoryCompletedFiles = 0
            lastProgressAdvanceTime = nil
            lastSpeedSampleTime = nil
            lastSpeedSampleBytes = 0
            lastMeasuredBytesPerSecond = nil
            lastProgressPublicationTime = nil
            lastPublishedBytes = -1
            lastPublishedPhase = nil
            phase = .downloading
            retryCount = 0
            statusMessage = nil
            if !preserveUnclaimedCompletions {
                for (_, staged) in stagedSuccessfulDownloads.values {
                    try? FileManager.default.removeItem(at: staged.url)
                }
                stagedSuccessfulDownloads.removeAll()
                for completion in unclaimedCompletionsByKey.values {
                    try? FileManager.default.removeItem(at: completion.file.url)
                }
                unclaimedCompletionsByKey.removeAll()
            }
            expectedTaskIdentityByURL.removeAll()
            expectedEntriesByKey.removeAll()
            // Leftover adopted-but-unconsumed tasks belong to an abandoned run; left
            // uncancelled they would keep streaming in the daemon with no consumer.
            for task in adoptedTasksByKey.values { task.cancel() }
            adoptedTasksByKey.removeAll()
            backgroundCompletionGate.resetForRequest()
            verifiedReceiptsByPath.removeAll()
            heartbeatTask?.cancel()
            heartbeatTask = nil
        }

        func beginRepositoryDownload(
            totalBytes: Int64,
            totalFiles: Int,
            preverifiedBytes: Int64 = 0,
            preverifiedFiles: Int = 0,
            phase: DownloadPhase = .downloading
        ) {
            repositoryTotalBytes = max(0, totalBytes)
            repositoryTotalFiles = max(0, totalFiles)
            repositoryCompletedFiles = max(0, min(preverifiedFiles, repositoryTotalFiles))
            completedFilesBytes = max(0, min(preverifiedBytes, repositoryTotalBytes))
            taskFileIndex.removeAll()
            taskBytes.removeAll()
            self.phase = phase
            let now = ProcessInfo.processInfo.systemUptime
            lastProgressAdvanceTime = now
            lastSpeedSampleTime = now
            // Reused verified bytes are progress, not network throughput.
            lastSpeedSampleBytes = completedFilesBytes
            lastMeasuredBytesPerSecond = nil
            emitRepositoryProgress(isStalled: false)
            startHeartbeatIfNeeded()
        }

        func register(
            taskKey: Int,
            task: URLSessionDownloadTask,
            destination: URL,
            continuation: CheckedContinuation<DownloadedTemporaryFile, Error>,
            resumeDataURL: URL?,
            fileIndex: Int,
            existingBytes: Int64 = 0
        ) -> Bool {
            let taskID = taskKey
            if isCancelled {
                task.cancel()
                continuation.resume(throwing: DownloadError.cancelled)
                return false
            }
            if let identity = ModelDownloadTaskIdentity.decode(taskDescription: task.taskDescription),
               let parked = unclaimedCompletionsByKey[identity.reconciliationKey] {
                if parked.identity == identity {
                    unclaimedCompletionsByKey.removeValue(forKey: identity.reconciliationKey)
                    task.cancel()
                    continuation.resume(returning: parked.file)
                    return false
                }
                // Same slot, different request/artifact generation: the parked bytes
                // are not this task's payload. Drop them and transfer fresh.
                unclaimedCompletionsByKey.removeValue(forKey: identity.reconciliationKey)
                try? FileManager.default.removeItem(at: parked.file.url)
            }
            // An adopted task may already be terminal: its delegate events ran before
            // this registration. A terminal success was parked above and claimed; a
            // terminal failure was dropped by `resumeFailure` (no continuation existed
            // yet), so registering the dead task would park a continuation no future
            // delegate event can ever resume — hanging the whole download. Fail fast
            // instead; the caller's retry loop re-fetches with a fresh task.
            if task.state == .completed || task.state == .canceling {
                continuation.resume(throwing: DownloadError.fileDownloadFailed(
                    path: destination.lastPathComponent,
                    underlying: task.error ?? URLError(.unknown)
                ))
                return false
            }
            activeCancellations[taskID] = TaskCancellationBox(task: task, resumeDataURL: resumeDataURL)
            continuations[taskID] = continuation
            destinations[taskID] = destination
            taskFileIndex[taskID] = fileIndex
            taskBytes[taskID] = existingBytes
            if existingBytes > 0 {
                // A resumed partial's bytes are progress, not fresh network throughput:
                // fold them into the speed baseline instead of injecting them as one
                // instantaneous sample that spikes the displayed speed.
                lastSpeedSampleBytes += existingBytes
                emitRepositoryProgress(isStalled: false)
            }
            return true
        }

        func requestCancellation() async {
            guard !isCancelled else { return }
            isCancelled = true
            phase = .cancelling
            statusMessage = nil
            emitRepositoryProgress(isStalled: false, force: true)
            let cancellations = Array(activeCancellations.values)
            await withTaskGroup(of: Void.self) { group in
                for cancellation in cancellations {
                    group.addTask {
                        await cancellation.cancelAndWait()
                    }
                }
            }
            let pendingContinuations = Array(continuations.values)
            continuations.removeAll()
            activeCancellations.removeAll()
            destinations.removeAll()
            for continuation in pendingContinuations {
                continuation.resume(throwing: DownloadError.cancelled)
            }
            for (_, staged) in stagedSuccessfulDownloads.values {
                try? FileManager.default.removeItem(at: staged.url)
            }
            stagedSuccessfulDownloads.removeAll()
            for completion in unclaimedCompletionsByKey.values {
                try? FileManager.default.removeItem(at: completion.file.url)
            }
            unclaimedCompletionsByKey.removeAll()
            // Adopted-but-unconsumed tasks are live daemon transfers with no
            // registered continuation; without this drain a user cancel would leave
            // them streaming (bandwidth and battery) until the next app launch.
            for task in adoptedTasksByKey.values { task.cancel() }
            adoptedTasksByKey.removeAll()
        }

        func cancellationRequested() -> Bool {
            isCancelled
        }

        func setPhase(_ phase: DownloadPhase) {
            self.phase = phase
            if phase != .retrying { statusMessage = nil }
            emitRepositoryProgress(isStalled: false, force: true)
        }

        func setRetry(number: Int, reason: String) {
            retryCount = number
            statusMessage = reason
            phase = .retrying
            emitRepositoryProgress(isStalled: false, force: true)
        }

        func setWaitingForConnectivity(_ waiting: Bool) {
            if waiting {
                guard phase != .waitingForConnectivity else { return }
                phase = .waitingForConnectivity
                statusMessage = "Waiting for connectivity"
            } else {
                guard phase == .waitingForConnectivity else { return }
                phase = .downloading
                statusMessage = nil
            }
            emitRepositoryProgress(isStalled: false, force: true)
        }

        /// `values` may contain both whole-file identities and chunk identities of the
        /// same file (same URL); keys are unique per reconciliation slot. Keep-first
        /// uniquing keeps a malformed plan from trapping at runtime.
        func configureExpectedTasks(_ values: [(URL, ModelDownloadTaskIdentity)]) {
            expectedTaskIdentityByURL = Dictionary(
                values.compactMap { url, identity in
                    identity.rangeStart == nil ? (url, identity) : nil
                },
                uniquingKeysWith: { first, _ in first }
            )
            expectedEntriesByKey = Dictionary(
                values.map { ($0.1.reconciliationKey, (url: $0.0, identity: $0.1)) },
                uniquingKeysWith: { first, _ in first }
            )
            for task in adoptedTasksByKey.values { task.cancel() }
            adoptedTasksByKey.removeAll()
            // Parked completions no expected slot can claim (an older artifact
            // generation, or a slot shape this run no longer uses) would otherwise
            // hold their durable temp files forever on background sessions.
            for (key, parked) in unclaimedCompletionsByKey
            where expectedEntriesByKey[key]?.identity != parked.identity {
                unclaimedCompletionsByKey.removeValue(forKey: key)
                try? FileManager.default.removeItem(at: parked.file.url)
            }
        }

        func expectedIdentity(for url: URL) -> ModelDownloadTaskIdentity? {
            expectedTaskIdentityByURL[url]
        }

        func expectedEntry(forKey key: String) -> (url: URL, identity: ModelDownloadTaskIdentity)? {
            expectedEntriesByKey[key]
        }

        func adopt(task: URLSessionDownloadTask, identity: ModelDownloadTaskIdentity) -> Bool {
            guard !isCancelled,
                  adoptedTasksByKey[identity.reconciliationKey] == nil else {
                return false
            }
            adoptedTasksByKey[identity.reconciliationKey] = task
            return true
        }

        func takeAdoptedTask(for url: URL) -> URLSessionDownloadTask? {
            guard let identity = expectedTaskIdentityByURL[url] else { return nil }
            return adoptedTasksByKey.removeValue(forKey: identity.reconciliationKey)
        }

        func takeAdoptedTask(forKey key: String) -> URLSessionDownloadTask? {
            adoptedTasksByKey.removeValue(forKey: key)
        }

        func markBackgroundEventsFinished() -> Bool {
            backgroundCompletionGate.markEventsFinished()
        }

        func markPostprocessingFinished() -> Bool {
            backgroundCompletionGate.markPostprocessingFinished()
        }

        func recordVerifiedReceipt(_ receipt: VerifiedArtifactReceipt) {
            verifiedReceiptsByPath[receipt.relativePath] = receipt
        }

        func verifiedReceipts() -> [String: VerifiedArtifactReceipt] {
            verifiedReceiptsByPath
        }

        /// Per-task progress from the URLSession delegate. Monotonic per task, so a
        /// resume->fresh fallback never moves a task's counter backward. Works for both a
        /// single-stream file (1 task) and a chunked file (N tasks) because the repository
        /// total is the sum of all task bytes.
        func reportProgress(taskID: Int, totalBytesWritten: Int64) {
            guard taskFileIndex[taskID] != nil else { return }
            let previous = taskBytes[taskID] ?? 0
            let updated = max(previous, totalBytesWritten)
            let delta = updated - previous
            guard delta != 0 else { return }
            taskBytes[taskID] = updated
            let now = ProcessInfo.processInfo.systemUptime
            applySpeedMeasurement(now: now, totalDownloaded: repositoryDownloadedBytes, advancedDelta: delta)
            emitRepositoryProgress(isStalled: false)
        }

        /// Drop any live task state for `fileIndex` (called at the start of each download
        /// attempt). Clears stale bytes from a prior failed attempt so they don't inflate
        /// the counter during a retry; the fresh attempt re-accumulates from zero.
        func resetFileProgress(fileIndex: Int) {
            let staleTaskIDs = taskFileIndex.keys.filter { taskFileIndex[$0] == fileIndex }
            for taskID in staleTaskIDs {
                taskBytes.removeValue(forKey: taskID)
                taskFileIndex.removeValue(forKey: taskID)
            }
        }

        /// Bytes of `fileIndex` already durable on disk from completed chunk ranges of a
        /// prior process (per the completed-range sidecar). Counted under a synthetic
        /// negative task key — real task keys are never negative — so the per-file
        /// accounting (`resetFileProgress`/`reportFileCompleted`) reconciles them exactly
        /// like live task bytes. Baseline-bumped, not speed-sampled: recovered bytes are
        /// progress, not fresh network throughput.
        func reportPreexistingFileBytes(fileIndex: Int, bytes: Int64) {
            guard bytes > 0 else { return }
            let syntheticKey = -(fileIndex + 1)
            taskFileIndex[syntheticKey] = fileIndex
            taskBytes[syntheticKey] = (taskBytes[syntheticKey] ?? 0) + bytes
            lastSpeedSampleBytes += bytes
            emitRepositoryProgress(isStalled: false)
        }

        /// A file finished (downloaded, or already-valid and skipped). Fold its live task
        /// bytes into the completed-files total at the exact expected size, then drop the
        /// file's task entries. Reconciliation is implicit: the live sum loses the file's
        /// task bytes and `completedFilesBytes` gains `expectedSize`. A file that was not
        /// transferred this run (already valid on disk) adjusts the speed baseline instead
        /// of injecting its whole size as one spurious "instantaneous" speed sample.
        func reportFileCompleted(fileIndex: Int, expectedSize: Int64, wasTransferred: Bool = true) {
            let fileTaskIDs = taskFileIndex.keys.filter { taskFileIndex[$0] == fileIndex }
            var liveForFile: Int64 = 0
            for taskID in fileTaskIDs {
                liveForFile += taskBytes.removeValue(forKey: taskID) ?? 0
                taskFileIndex.removeValue(forKey: taskID)
            }
            completedFilesBytes += expectedSize
            repositoryCompletedFiles += 1
            if wasTransferred {
                let now = ProcessInfo.processInfo.systemUptime
                applySpeedMeasurement(now: now, totalDownloaded: repositoryDownloadedBytes, advancedDelta: expectedSize - liveForFile)
            } else {
                lastSpeedSampleBytes += expectedSize - liveForFile
            }
            emitRepositoryProgress(isStalled: false, force: true)
        }

        /// Per-file digest verification window. The SHA-256 pass over a multi-gigabyte
        /// file produces no byte progress, so without a visible status the displayed
        /// speed freezes and the transfer reads as stalled. Counted, because several
        /// files can verify concurrently.
        func beginFileVerification() {
            verifyingFileCount += 1
            if verifyingFileCount == 1 {
                statusMessage = "Verifying downloaded files"
                emitRepositoryProgress(isStalled: false, force: true)
            }
        }

        func endFileVerification() {
            verifyingFileCount = max(0, verifyingFileCount - 1)
            if verifyingFileCount == 0, statusMessage == "Verifying downloaded files" {
                statusMessage = nil
                emitRepositoryProgress(isStalled: false, force: true)
            }
        }

        func finishRepositoryDownload() {
            heartbeatTask?.cancel()
            heartbeatTask = nil
        }

        func stageSuccess(
            taskID: Int,
            identity: ModelDownloadTaskIdentity?,
            temporaryFile: DownloadedTemporaryFile
        ) {
            if let (_, superseded) = stagedSuccessfulDownloads.updateValue(
                (identity, temporaryFile),
                forKey: taskID
            ) {
                try? FileManager.default.removeItem(at: superseded.url)
            }
        }

        func completeStagedSuccess(taskID: Int) {
            guard let (identity, temporaryFile) = stagedSuccessfulDownloads.removeValue(forKey: taskID) else {
                return
            }
            let continuation = continuations.removeValue(forKey: taskID)
            destinations.removeValue(forKey: taskID)
            activeCancellations.removeValue(forKey: taskID)
            // NOTE: taskFileIndex/taskBytes are intentionally left in place — the file's
            // live bytes stay counted until reportFileCompleted folds them in (success) or
            // resetFileProgress clears them (retry).
            if isCancelled {
                try? FileManager.default.removeItem(at: temporaryFile.url)
                continuation?.resume(throwing: DownloadError.cancelled)
            } else if let continuation {
                continuation.resume(returning: temporaryFile)
            } else if let identity {
                // Background callbacks may arrive before launch reconciliation has registered
                // the adopted task. Keep the durable temporary file until adoption completes.
                // Keyed per reconciliation slot, so chunk completions of one file park
                // side by side instead of superseding each other.
                if let superseded = unclaimedCompletionsByKey.updateValue(
                    (identity, temporaryFile),
                    forKey: identity.reconciliationKey
                ) {
                    try? FileManager.default.removeItem(at: superseded.file.url)
                }
            } else {
                try? FileManager.default.removeItem(at: temporaryFile.url)
            }
        }

        func resumeFailure(taskID: Int, error: Error) {
            if let (_, staged) = stagedSuccessfulDownloads.removeValue(forKey: taskID) {
                try? FileManager.default.removeItem(at: staged.url)
            }
            let continuation = continuations.removeValue(forKey: taskID)
            destinations.removeValue(forKey: taskID)
            activeCancellations.removeValue(forKey: taskID)
            continuation?.resume(throwing: error)
        }

        func destinationPath(taskID: Int) -> String {
            destinations[taskID]?.lastPathComponent ?? "unknown"
        }

        private func applySpeedMeasurement(now: TimeInterval, totalDownloaded: Int64, advancedDelta: Int64) {
            guard advancedDelta > 0 else { return }
            if let previousSpeedSampleTime = lastSpeedSampleTime {
                let elapsed = now - previousSpeedSampleTime
                guard elapsed >= 0.5 else {
                    lastProgressAdvanceTime = now
                    return
                }
                let deltaBytes = totalDownloaded - lastSpeedSampleBytes
                if deltaBytes > 0 {
                    let instantaneous = Double(deltaBytes) / elapsed
                    if let previous = lastMeasuredBytesPerSecond {
                        lastMeasuredBytesPerSecond = Int64(
                            (Double(previous) * 0.75) + (instantaneous * 0.25)
                        )
                    } else {
                        lastMeasuredBytesPerSecond = Int64(instantaneous)
                    }
                    lastSpeedSampleTime = now
                    lastSpeedSampleBytes = totalDownloaded
                }
            } else {
                lastSpeedSampleTime = now
                lastSpeedSampleBytes = totalDownloaded
            }
            lastProgressAdvanceTime = now
        }

        private func startHeartbeatIfNeeded() {
            guard heartbeatTask == nil else { return }
            let registry = self
            heartbeatTask = Task {
                while !Task.isCancelled {
                    try? await Task.sleep(for: .milliseconds(750))
                    await registry.emitHeartbeatIfNeeded()
                }
            }
        }

        private func emitHeartbeatIfNeeded() {
            guard repositoryProgressHandler != nil else { return }
            guard !activeCancellations.isEmpty else { return }

            let now = ProcessInfo.processInfo.systemUptime
            guard phase == .downloading,
                  let lastProgressAdvanceTime,
                  now - lastProgressAdvanceTime >= 20 else {
                return
            }
            emitRepositoryProgress(isStalled: true, force: true)
        }

        private func emitRepositoryProgress(isStalled: Bool, force: Bool = false) {
            let downloaded = min(repositoryDownloadedBytes, repositoryTotalBytes)
            let now = ProcessInfo.processInfo.systemUptime
            let phaseChanged = lastPublishedPhase != phase
            let reachedCompletion = repositoryTotalBytes > 0
                && downloaded == repositoryTotalBytes
                && lastPublishedBytes != downloaded
            if !force, !isStalled, !phaseChanged, !reachedCompletion,
               let lastProgressPublicationTime,
               now - lastProgressPublicationTime < 0.25 {
                return
            }
            let remaining = max(repositoryTotalBytes - downloaded, 0)
            let eta = lastMeasuredBytesPerSecond.flatMap { speed -> Double? in
                guard speed > 0, phase == .downloading else { return nil }
                return Double(remaining) / Double(speed)
            }
            repositoryProgressHandler?.handler(
                RepositoryProgress(
                    downloadedBytes: downloaded,
                    totalBytes: repositoryTotalBytes,
                    completedFiles: min(repositoryCompletedFiles, repositoryTotalFiles),
                    totalFiles: repositoryTotalFiles,
                    bytesPerSecond: lastMeasuredBytesPerSecond,
                    isStalled: isStalled,
                    estimatedSecondsRemaining: eta,
                    retryCount: retryCount,
                    statusMessage: statusMessage,
                    phase: phase
                )
            )
            lastProgressPublicationTime = now
            lastPublishedBytes = downloaded
            lastPublishedPhase = phase
        }
    }

    /// Durable record of which byte ranges of one chunked file have already been written
    /// and length-validated into its partial. A sparse partial with holes is otherwise
    /// indistinguishable from a complete one after a crash, so without this record every
    /// process death would restart the whole file. Written atomically beside the partial
    /// after each chunk lands; a missing or invalid sidecar fails closed to a clean
    /// restart of that file.
    struct ChunkCompletionSidecar: Codable, Equatable, Sendable {
        static let currentSchemaVersion = 1

        let schemaVersion: Int
        let expectedSize: Int64
        /// Sorted, merged, non-overlapping inclusive ranges as `[start, end]` pairs.
        let ranges: [[Int64]]
    }

    /// Serializes writes from concurrently downloaded byte-range chunks into one partial
    /// file. `FileHandle` is not safe for concurrent seek+write on the same descriptor, so
    /// each chunk's bytes are written under actor isolation (the network — not the local
    /// disk — is the bottleneck, so serial writes are cheap). APFS fills sparse holes as
    /// out-of-order chunks land, so no pre-allocation is needed. When a sidecar URL is
    /// provided the actor also maintains the durable completed-range record so a killed
    /// process resumes from the ranges that already landed instead of restarting the file.
    actor ChunkAssemblyCoordinator {
        private let partialURL: URL
        private let sidecarURL: URL?
        private let expectedSize: Int64
        private var completedRanges: [ChunkRange]
        private var writeHandle: FileHandle?

        init(
            partialURL: URL,
            sidecarURL: URL? = nil,
            expectedSize: Int64 = 0,
            initialCompletedRanges: [ChunkRange] = []
        ) {
            self.partialURL = partialURL
            self.sidecarURL = sidecarURL
            self.expectedSize = expectedSize
            self.completedRanges = HuggingFaceDownloader.mergedChunkRanges(initialCompletedRanges)
        }

        /// Record `range` as durably written. Ordering matters: the chunk's bytes are in
        /// the partial before the sidecar mentions them, so a crash between the two only
        /// re-fetches that range (idempotent rewrite), never trusts unwritten bytes.
        func recordCompleted(range: ChunkRange) {
            guard let sidecarURL else { return }
            completedRanges = HuggingFaceDownloader.mergedChunkRanges(completedRanges + [range])
            HuggingFaceDownloader.writeChunkSidecar(
                at: sidecarURL,
                expectedSize: expectedSize,
                ranges: completedRanges
            )
        }

        /// Open the partial for writing, creating it if necessary.
        func open() throws {
            if !FileManager.default.fileExists(atPath: partialURL.path) {
                FileManager.default.createFile(atPath: partialURL.path, contents: nil, attributes: nil)
            }
            writeHandle = try FileHandle(forWritingTo: partialURL)
        }

        /// Stream the contents of `tempURL` into the partial at absolute byte `offset`.
        /// Validates that the number of bytes written matches the temp file's size so a
        /// truncated or corrupted chunk doesn't silently leave a hole in the partial.
        func writeChunk(tempURL: URL, offset: Int64) throws {
            guard let writeHandle else { return }
            let attributes = try FileManager.default.attributesOfItem(atPath: tempURL.path)
            let expectedBytes = Int64(attributes[.size] as? Int64 ?? 0)
            try writeHandle.seek(toOffset: UInt64(offset))
            let readHandle = try FileHandle(forReadingFrom: tempURL)
            defer { try? readHandle.close() }
            var bytesWritten: Int64 = 0
            while autoreleasepool(invoking: {
                let data = readHandle.readData(ofLength: 1_048_576)
                guard !data.isEmpty else { return false }
                writeHandle.write(data)
                bytesWritten += Int64(data.count)
                return true
            }) {}
            guard bytesWritten == expectedBytes else {
                throw DownloadError.chunkAssemblyFailed(
                    path: tempURL.path,
                    reason: "expected \(expectedBytes) bytes, wrote \(bytesWritten)"
                )
            }
        }

        func close() {
            try? writeHandle?.synchronize()
            try? writeHandle?.close()
            writeHandle = nil
        }
    }

    // Foundation's delegate protocols are Sendable, while URLSession is initialized after
    // self so it can retain this delegate. The session reference is assigned once during init;
    // all mutable transfer state remains isolated by DownloadStateRegistry.
    private nonisolated(unsafe) var session: URLSession!
    /// Foreground transfer configuration retained for lazily created per-worker chunk
    /// sessions (`nil` for background sessions, where chunking is unavailable). Assigned
    /// once in init and never mutated afterward.
    private nonisolated(unsafe) let foregroundTransferConfiguration: URLSessionConfiguration?
    /// The single serial delegate queue shared by every session this downloader owns.
    /// Assigned once in init.
    private nonisolated(unsafe) let transferDelegateQueue: OperationQueue
    /// Lazily created per-worker chunk sessions (`.perWorker` strategy only). Index i is
    /// worker i's session; the main `session` carries task-key namespace 0 and these carry
    /// namespaces 1...N so task identifiers never collide across sessions.
    private let chunkSessionsBox = Mutex<[URLSession]>([])
    /// Task-key -> relativePath for in-flight chunk tasks. On runs that carry a request
    /// identity, chunk tasks encode a range-qualified `ModelDownloadTaskIdentity` in
    /// their task description (schema v2), which also attributes their metrics; this
    /// in-process map keeps attribution exact on the API path (`downloadRepo`, no
    /// request identity) so `wireBytes` — delivery-evidence input — never under-counts
    /// chunked payload as control-plane bytes. Entries are removed in
    /// `didCompleteWithError`, after the metrics callback has consumed them.
    private let chunkTaskPathsBox = Mutex<[Int: String]>([:])
    private let state: DownloadStateRegistry
    private let delegateProgressGate = Mutex(ModelDownloadDelegateProgressGate())
    private let terminalEventSequencer = ModelDownloadDelegateTerminalSequencer()
    private let apiBaseURL: URL
    private let resolveBaseURL: URL
    private let fileManagerBox: FileManagerBox
    private var fileManager: FileManager { fileManagerBox.value }
    private let engineConfiguration: Configuration
    private let isBackgroundSession: Bool
    private let durableTemporaryDirectory: URL
    private let verificationProcessGeneration = UUID().uuidString
    /// Invoked from `urlSessionDidFinishEvents(forBackgroundURLSession:)` (background sessions
    /// only) with the session's identifier so iOS can flush its app-delegate completion handler.
    /// macOS/CLI pass `nil` (foreground sessions never trigger this callback).
    private let backgroundSessionCompletionHandler: (@Sendable (String) -> Void)?
    private let transferMetricsHandler: TransferMetricsHandlerBox?
    private let verifiedArtifactHandler: VerifiedArtifactHandlerBox?
    private let artifactURLPolicy: ModelArtifactURLPolicy?

    // MARK: - Transfer sessions and task keys

    /// Keeps task identifiers from distinct URLSessions from colliding in the shared
    /// per-task registries: identifiers are small per-session integers, so one billion of
    /// namespace stride is safe headroom.
    private static let taskKeyNamespaceStride = 1_000_000_000

    /// The registry/gate key for a task: namespace 0 is the main session (so background
    /// sessions and the `.shared` strategy keep today's identifier-equals-key behavior);
    /// per-worker chunk sessions occupy namespaces 1...N.
    private nonisolated func taskKey(for task: URLSessionTask, in candidate: URLSession) -> Int {
        sessionNamespace(of: candidate) * Self.taskKeyNamespaceStride + task.taskIdentifier
    }

    private nonisolated func sessionNamespace(of candidate: URLSession) -> Int {
        if candidate === session { return 0 }
        return chunkSessionsBox.withLock { sessions in
            guard let index = sessions.firstIndex(where: { $0 === candidate }) else { return 0 }
            return index + 1
        }
    }

    /// The URLSession a chunk worker's ranges ride on. `.shared` (and any background
    /// session) returns the main session. `.perWorker` lazily creates one foreground
    /// session per worker slot: HTTP/2/3 coalesce a host's tasks onto one connection,
    /// which would leave every chunk sharing a single connection's CDN throughput
    /// shaping; distinct sessions force distinct connections.
    private func chunkTransferSession(forWorker workerIndex: Int) -> URLSession {
        guard engineConfiguration.chunkSessionStrategy == .perWorker,
              !isBackgroundSession,
              let configuration = foregroundTransferConfiguration else {
            return session
        }
        return chunkSessionsBox.withLock { sessions in
            while sessions.count <= workerIndex {
                let workerConfiguration =
                    (configuration.copy() as? URLSessionConfiguration) ?? configuration
                sessions.append(URLSession(
                    configuration: workerConfiguration,
                    delegate: self,
                    delegateQueue: transferDelegateQueue
                ))
            }
            return sessions[workerIndex]
        }
    }

    /// Tear down any lazily created per-worker chunk sessions alongside the main session.
    private func invalidateChunkSessions(cancelling: Bool) {
        let sessions = chunkSessionsBox.withLock { sessions in
            let snapshot = sessions
            sessions.removeAll()
            return snapshot
        }
        for extra in sessions {
            if cancelling {
                extra.invalidateAndCancel()
            } else {
                extra.finishTasksAndInvalidate()
            }
        }
    }

    static func validatedRelativeRepoPath(_ path: String) throws -> String {
        let trimmed = path.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            throw DownloadError.invalidRemotePath(path)
        }

        let normalized = trimmed.replacingOccurrences(of: "\\", with: "/")
        guard !normalized.hasPrefix("/") else {
            throw DownloadError.invalidRemotePath(path)
        }

        let components = normalized.split(separator: "/", omittingEmptySubsequences: false)
        guard !components.isEmpty else {
            throw DownloadError.invalidRemotePath(path)
        }

        var validatedComponents: [String] = []
        for rawComponent in components {
            let component = String(rawComponent)
            guard !component.isEmpty, component != ".", component != ".." else {
                throw DownloadError.invalidRemotePath(path)
            }
            guard !component.hasPrefix(".") else {
                throw DownloadError.invalidRemotePath(path)
            }
            validatedComponents.append(component)
        }

        return validatedComponents.joined(separator: "/")
    }

    static func validatedDestinationURL(for relativePath: String, in root: URL) throws -> URL {
        let validatedRelativePath = try validatedRelativeRepoPath(relativePath)
        let normalizedRoot = root.standardizedFileURL.resolvingSymlinksInPath()
        let destination = normalizedRoot
            .appendingPathComponent(validatedRelativePath, isDirectory: false)
            .standardizedFileURL
            .resolvingSymlinksInPath()
        let rootPrefix = normalizedRoot.path.hasSuffix("/") ? normalizedRoot.path : normalizedRoot.path + "/"

        guard destination.path.hasPrefix(rootPrefix) else {
            throw DownloadError.invalidLocalDestination(relativePath)
        }

        return destination
    }

    static func repoFiles(fromAPIData data: Data) throws -> [RepoFile] {
        guard let items = try JSONSerialization.jsonObject(with: data) as? [[String: Any]] else {
            throw DownloadError.apiError("Unexpected API response format")
        }

        return items.compactMap { item -> RepoFile? in
            guard let type = item["type"] as? String, type == "file",
                  let path = item["path"] as? String,
                  path != ".gitattributes" else { return nil }

            let size: Int64
            let sha256: String?
            if let lfs = item["lfs"] as? [String: Any] {
                if let lfsSize = lfs["size"] as? Int64 {
                    size = lfsSize
                } else if let lfsSize = lfs["size"] as? Int {
                    size = Int64(lfsSize)
                } else {
                    size = 0
                }
                sha256 = normalizedSHA256(lfs["oid"] as? String)
            } else if let s = item["size"] as? Int64 {
                size = s
                sha256 = nil
            } else if let s = item["size"] as? Int {
                size = Int64(s)
                sha256 = nil
            } else {
                size = 0
                sha256 = nil
            }

            return RepoFile(path: path, size: size, sha256: sha256)
        }
    }

    static func downloadRequest(for url: URL, existingBytes: Int64) -> URLRequest {
        var request = URLRequest(url: url)
        if existingBytes > 0 {
            request.setValue("bytes=\(existingBytes)-", forHTTPHeaderField: "Range")
        }
        return request
    }

    static func validateDownloadedFile(
        at url: URL,
        expectedSize: Int64,
        sha256: String?
    ) throws {
        let values = try url.resourceValues(forKeys: [.fileSizeKey])
        let actualSize = Int64(values.fileSize ?? 0)
        if expectedSize > 0, actualSize != expectedSize {
            throw DownloadError.integrityCheckFailed(
                path: url.path,
                reason: "expected \(expectedSize) bytes, found \(actualSize)"
            )
        }
        guard let expectedSHA256 = normalizedSHA256(sha256) else { return }
        let actualSHA256 = try sha256Hex(for: url)
        guard actualSHA256 == expectedSHA256 else {
            throw DownloadError.integrityCheckFailed(
                path: url.path,
                reason: "expected sha256 \(expectedSHA256), found \(actualSHA256)"
            )
        }
    }

    static func sha256Hex(for url: URL) throws -> String {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }

        var hasher = SHA256()
        while autoreleasepool(invoking: {
            let data = handle.readData(ofLength: 1_048_576)
            guard !data.isEmpty else { return false }
            hasher.update(data: data)
            return true
        }) {}

        return hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }

    static func normalizedSHA256(_ value: String?) -> String? {
        guard var value else { return nil }
        value = value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if value.hasPrefix("sha256:") {
            value.removeFirst("sha256:".count)
        }
        guard value.count == 64,
              value.unicodeScalars.allSatisfy({
                CharacterSet(charactersIn: "0123456789abcdef").contains($0)
              }) else {
            return nil
        }
        return value
    }

    convenience override init() {
        self.init(progressHandler: nil)
    }

    public init(
        progressHandler: (@Sendable (RepositoryProgress) -> Void)?,
        sessionConfiguration: URLSessionConfiguration = .default,
        engineConfiguration: Configuration = Configuration(),
        apiBaseURL: URL = URL(string: "https://huggingface.co/api/models")!,
        resolveBaseURL: URL = URL(string: "https://huggingface.co")!,
        fileManager: FileManager = .default,
        durableTemporaryDirectory: URL? = nil,
        transferMetricsHandler: (@Sendable (TransferMetrics) -> Void)? = nil,
        verifiedArtifactHandler: (@Sendable (VerifiedArtifactReceipt) async -> Void)? = nil,
        backgroundSessionCompletionHandler: (@Sendable (String) -> Void)? = nil,
        artifactURLPolicy: ModelArtifactURLPolicy? = nil
    ) {
        let progressBox = progressHandler.map(RepositoryProgressHandlerBox.init)
        state = DownloadStateRegistry(repositoryProgressHandler: progressBox)
        self.apiBaseURL = apiBaseURL
        self.resolveBaseURL = resolveBaseURL
        self.fileManagerBox = FileManagerBox(fileManager)
        self.engineConfiguration = engineConfiguration
        self.backgroundSessionCompletionHandler = backgroundSessionCompletionHandler
        self.transferMetricsHandler = transferMetricsHandler.map(TransferMetricsHandlerBox.init)
        self.verifiedArtifactHandler = verifiedArtifactHandler.map(VerifiedArtifactHandlerBox.init)
        self.artifactURLPolicy = artifactURLPolicy
        self.isBackgroundSession = sessionConfiguration.identifier != nil
        self.durableTemporaryDirectory = durableTemporaryDirectory ?? fileManager.temporaryDirectory

        let config: URLSessionConfiguration
        if sessionConfiguration.identifier != nil {
            // Background configs are effectively singletons-by-identifier; copying/mutating one
            // (e.g. httpMaximumConnectionsPerHost) is unreliable and the key is ignored anyway.
            // Concurrency is bounded by the task group's `maxConcurrentFiles` instead. Callers
            // (iOS) configure the background config fully before passing it in.
            config = sessionConfiguration
            self.foregroundTransferConfiguration = nil
        } else {
            let copy = sessionConfiguration.copy() as? URLSessionConfiguration ?? .default
            copy.timeoutIntervalForResource = 3600
            copy.httpMaximumConnectionsPerHost = engineConfiguration.maxConnectionsPerHost
            config = copy
            self.foregroundTransferConfiguration = copy
        }
        // One serial queue shared by the main session and any per-worker chunk sessions,
        // preserving the ordered-delegate invariant across every transfer.
        let delegateQueue = OperationQueue()
        delegateQueue.maxConcurrentOperationCount = 1
        delegateQueue.qualityOfService = .userInitiated
        self.transferDelegateQueue = delegateQueue
        super.init()

        session = URLSession(configuration: config, delegate: self, delegateQueue: delegateQueue)
    }

    // MARK: - Public API

    /// Download all files from a HuggingFace repo into `targetDir`.
    /// Resolve the file list from the live HuggingFace API, then download + verify + install.
    /// macOS + CLI path.
    public func downloadRepo(repo: String, revision: String = "main", to targetDir: URL) async throws {
        await state.resetForNewRepositoryDownload(preserveUnclaimedCompletions: isBackgroundSession)
        do {
            let files = try await listFiles(repo: repo, revision: revision)
            try await runDownload(
                files: files,
                repo: repo,
                revision: revision,
                targetDir: targetDir,
                persistStateManifest: true
            )
        } catch {
            if !isBackgroundSession { session.invalidateAndCancel() }
            throw error
        }
    }

    /// Download + verify + install a pre-resolved catalog file list (no API call). The caller
    /// supplies each file with an optional validated `absoluteURL` (host-allowlist-enforced by the
    /// catalog) and a request identity so task metrics remain attributable to payload files on
    /// foreground macOS/CLI runs and adoptable across iOS background-session relaunches.
    /// `repo`/`revision` seed the integrity manifest and fallback resolve URL.
    public func downloadFiles(
        _ files: [RepoFile],
        repo: String,
        revision: String,
        to targetDir: URL,
        requestIdentity: ModelDownloadRequestIdentity? = nil,
        stagingRoot explicitStagingRoot: URL? = nil,
        installedFiles: [RepoFile]? = nil,
        sharedComponentPlan: SharedComponentMigrationPlan? = nil
    ) async throws {
        await state.resetForNewRepositoryDownload(preserveUnclaimedCompletions: isBackgroundSession)
        try await runDownload(
            files: files,
            repo: repo,
            revision: revision,
            targetDir: targetDir,
            persistStateManifest: false,
            requestIdentity: requestIdentity,
            explicitStagingRoot: explicitStagingRoot,
            installedFiles: installedFiles,
            sharedComponentPlan: sharedComponentPlan
        )
    }

    /// Shared staging → parallel download → SHA-256 verify → atomic install flow used by both
    /// `downloadRepo` (API path) and `downloadFiles` (catalog path).
    private func runDownload(
        files: [RepoFile],
        repo: String,
        revision: String,
        targetDir: URL,
        persistStateManifest: Bool,
        requestIdentity: ModelDownloadRequestIdentity? = nil,
        explicitStagingRoot: URL? = nil,
        installedFiles: [RepoFile]? = nil,
        sharedComponentPlan: SharedComponentMigrationPlan? = nil
    ) async throws {
        let installedFiles = installedFiles ?? files
        let installedPaths = Set(installedFiles.map(\.path))
        let downloadPaths = Set(files.map(\.path))
        guard installedPaths.count == installedFiles.count,
              downloadPaths.count == files.count,
              downloadPaths.isSubset(of: installedPaths) else {
            throw DownloadError.apiError("Invalid authenticated installation file plan")
        }
        if let sharedComponentPlan {
            guard sharedComponentPlan.modelFolder == targetDir.lastPathComponent,
                  Set(sharedComponentPlan.manifest.contentIdentity.files.map(\.relativePath))
                    .isSubset(of: installedPaths) else {
                throw DownloadError.apiError("Shared component installation plan does not match the artifact")
            }
        }
        let reusedFiles = installedFiles.filter { !downloadPaths.contains($0.path) }
        let totalBytes = installedFiles.reduce(Int64(0)) { $0 + $1.size }
        await state.beginRepositoryDownload(
            totalBytes: totalBytes,
            totalFiles: installedFiles.count,
            preverifiedBytes: reusedFiles.reduce(Int64(0)) { $0 + $1.size },
            preverifiedFiles: reusedFiles.count
        )

        let stagingRoot = explicitStagingRoot ?? Self.stagingRoot(forTargetDirectory: targetDir)
        let filesRoot = stagingRoot.appendingPathComponent("files", isDirectory: true)
        let partialRoot = stagingRoot.appendingPathComponent("partials", isDirectory: true)
        let resumeRoot = stagingRoot.appendingPathComponent("resume-data", isDirectory: true)
        try fileManager.createDirectory(at: filesRoot, withIntermediateDirectories: true)
        try fileManager.createDirectory(at: partialRoot, withIntermediateDirectories: true)
        try fileManager.createDirectory(at: resumeRoot, withIntermediateDirectories: true)
        Self.markExcludedFromBackup(stagingRoot)
        Self.markExcludedFromBackup(filesRoot)
        Self.markExcludedFromBackup(partialRoot)
        Self.markExcludedFromBackup(resumeRoot)
        try fileManager.createDirectory(at: durableTemporaryDirectory, withIntermediateDirectories: true)
        Self.markExcludedFromBackup(durableTemporaryDirectory)

        if let requestIdentity {
            var expectedTasks: [(URL, ModelDownloadTaskIdentity)] = []
            for file in files {
                let relativePath = try Self.validatedRelativeRepoPath(file.path)
                let url = try file.absoluteURL ?? Self.fileResolveURL(
                    resolveBaseURL: resolveBaseURL,
                    repo: repo,
                    revision: revision,
                    relativePath: relativePath
                )
                // Every file keeps a whole-file identity: the single-stream path — and a
                // chunked file's Range-ignored fallback — labels and adopts by it.
                expectedTasks.append((
                    url,
                    ModelDownloadTaskIdentity(
                        logicalRequestID: requestIdentity.logicalRequestID,
                        modelID: requestIdentity.modelID,
                        artifactVersion: requestIdentity.artifactVersion,
                        relativePath: relativePath,
                        expectedSize: file.size,
                        expectedSHA256: file.sha256
                    )
                ))
                // Chunk-eligible files are additionally expected as range-qualified chunk
                // identities, so relaunch reconciliation adopts every in-flight chunk task
                // instead of reaping them as duplicates of one relative path. The range
                // partition is a pure function of size + configuration, so this plan and
                // `downloadChunkedFile` can never disagree about the expected ranges.
                guard chunkTransferPlanApplies(to: file) else { continue }
                for range in Self.chunkRanges(
                    total: file.size,
                    chunkSize: engineConfiguration.chunkTargetSize,
                    tailWorkerCount: engineConfiguration.chunkWorkerCount
                ) {
                    expectedTasks.append((
                        url,
                        ModelDownloadTaskIdentity(
                            logicalRequestID: requestIdentity.logicalRequestID,
                            modelID: requestIdentity.modelID,
                            artifactVersion: requestIdentity.artifactVersion,
                            relativePath: relativePath,
                            expectedSize: file.size,
                            expectedSHA256: file.sha256,
                            rangeStart: range.start,
                            rangeEnd: range.end
                        )
                    ))
                }
            }
            await state.configureExpectedTasks(expectedTasks)
            if isBackgroundSession {
                await reconcileBackgroundTasks(expected: Dictionary(
                    expectedTasks.map { ($0.1.reconciliationKey, $0.1) },
                    uniquingKeysWith: { first, _ in first }
                ))
            }
        }
        // The download-state manifest is the macOS resume-after-crash record; iOS keeps its own
        // lightweight in-flight list, so the catalog path skips this.
        if persistStateManifest {
            try persistDownloadState(
                repo: repo,
                revision: revision,
                targetDir: targetDir,
                files: files,
                stagingRoot: stagingRoot
            )
        }

        do {
            try await downloadAllFiles(
                files,
                repo: repo,
                revision: revision,
                artifactVersion: requestIdentity?.artifactVersion ?? revision,
                filesRoot: filesRoot,
                partialRoot: partialRoot,
                resumeRoot: resumeRoot
            )
            try await throwIfCancellationRequested()
            await state.setPhase(.verifying)
            try await throwIfCancellationRequested()
            try await verifyDownloadedFilesUsingReceipts(
                files,
                artifactVersion: requestIdentity?.artifactVersion ?? revision,
                in: filesRoot
            )
            try await throwIfCancellationRequested()
            try persistInstalledIntegrityManifest(
                repo: repo,
                revision: revision,
                targetDir: targetDir,
                files: installedFiles,
                filesRoot: filesRoot,
                sharedComponentManifest: sharedComponentPlan?.manifest
            )
            try await throwIfCancellationRequested()
            await state.setPhase(.installing)
            try await throwIfCancellationRequested()
            if let sharedComponentPlan {
                let store = SharedModelComponentStore(modelsRoot: targetDir.deletingLastPathComponent())
                _ = try store.installStagedModel(
                    sharedComponentPlan,
                    stagedModelURL: filesRoot
                ) { stagedModel in
                    try Self.validateStagedRepository(
                        at: stagedModel,
                        repo: repo,
                        revision: revision,
                        targetFolder: targetDir.lastPathComponent,
                        files: installedFiles,
                        sharedComponentManifest: sharedComponentPlan.manifest
                    )
                }
            } else {
                try installStagedRepository(filesRoot: filesRoot, targetDir: targetDir)
            }
            // Installation is synchronous, so check once more before publishing
            // success. The iOS coordinator rolls back a target created by this
            // narrow race before it durably records deletion.
            try await throwIfCancellationRequested()
            Self.markExcludedFromBackup(targetDir)
            try? fileManager.removeItem(at: stagingRoot)
            await state.finishRepositoryDownload()
            await completeBackgroundEventsAfterPostprocessing()
            if !isBackgroundSession {
                session.finishTasksAndInvalidate()
                invalidateChunkSessions(cancelling: false)
            }
        } catch {
            // A failure (or cancellation) mid-download: tear down any remaining
            // in-flight URLSession tasks so the caller doesn't wait for them.
            await state.requestCancellation()
            await state.finishRepositoryDownload()
            await completeBackgroundEventsAfterPostprocessing()
            if !isBackgroundSession {
                session.invalidateAndCancel()
                invalidateChunkSessions(cancelling: true)
            }
            throw error
        }
    }

    /// Cancel all in-flight downloads. Await before deleting staging so delegate callbacks
    /// don't race against a removed directory.
    public func cancel() async {
        await state.requestCancellation()
    }

    private func throwIfCancellationRequested() async throws {
        if Task.isCancelled {
            throw DownloadError.cancelled
        }
        if await state.cancellationRequested() {
            throw DownloadError.cancelled
        }
    }

    /// Remove orphan or stale tasks when no durable request is eligible for adoption.
    public func cancelAllSessionTasks() async {
        let tasks = await withCheckedContinuation { continuation in
            session.getAllTasks { continuation.resume(returning: $0) }
        }
        await withTaskGroup(of: Void.self) { group in
            for case let task as URLSessionDownloadTask in tasks {
                group.addTask {
                    await withCheckedContinuation { continuation in
                        task.cancel { _ in continuation.resume() }
                    }
                }
            }
        }
        await state.requestCancellation()
    }

    private func completeBackgroundEventsAfterPostprocessing() async {
        guard isBackgroundSession,
              let identifier = session.configuration.identifier,
              await state.markPostprocessingFinished() else { return }
        backgroundSessionCompletionHandler?(identifier)
    }

    /// `expected` is keyed by `ModelDownloadTaskIdentity.reconciliationKey`, so one file
    /// may legitimately appear as a whole-file slot plus N chunk slots.
    private func reconcileBackgroundTasks(expected: [String: ModelDownloadTaskIdentity]) async {
        let tasks = await withCheckedContinuation { continuation in
            session.getAllTasks { continuation.resume(returning: $0) }
        }
        var existing: [ModelDownloadExistingTask] = []
        var validIdentityByTaskID: [Int: ModelDownloadTaskIdentity] = [:]
        for task in tasks {
            var validIdentity: ModelDownloadTaskIdentity?
            if let identity = ModelDownloadTaskIdentity.decode(taskDescription: task.taskDescription),
               let expectedIdentity = expected[identity.reconciliationKey],
               identity == expectedIdentity,
               let taskURL = task.originalRequest?.url,
               await state.expectedEntry(forKey: identity.reconciliationKey)?.url == taskURL {
                validIdentity = identity
                validIdentityByTaskID[task.taskIdentifier] = identity
            }
            existing.append(ModelDownloadExistingTask(
                taskID: task.taskIdentifier,
                identity: validIdentity
            ))
        }
        let plan = ModelDownloadTaskReconciler.plan(
            expected: Array(expected.values),
            existing: existing
        )
        let cancelled = Set(plan.cancelledTaskIDs)
        for task in tasks {
            guard !cancelled.contains(task.taskIdentifier),
                  let downloadTask = task as? URLSessionDownloadTask,
                  let identity = validIdentityByTaskID[task.taskIdentifier],
                  await state.adopt(task: downloadTask, identity: identity) else {
                task.cancel()
                continue
            }
        }
    }

    // MARK: - Private: List Files

    private func listFiles(repo: String, revision: String) async throws -> [RepoFile] {
        let url = Self.repositoryTreeURL(apiBaseURL: apiBaseURL, repo: repo, revision: revision)

        let (data, response) = try await session.data(from: url)

        if let http = response as? HTTPURLResponse, http.statusCode != 200 {
            throw DownloadError.apiError("API returned HTTP \(http.statusCode)")
        }

        return try Self.repoFiles(fromAPIData: data)
    }

    static func repositoryTreeURL(apiBaseURL: URL, repo: String, revision: String) -> URL {
        apiBaseURL
            .appendingPathComponent(repo)
            .appendingPathComponent("tree")
            .appendingPathComponent(revision)
            .appending(queryItems: [URLQueryItem(name: "recursive", value: "true")])
    }

    static func fileResolveURL(
        resolveBaseURL: URL,
        repo: String,
        revision: String,
        relativePath: String
    ) throws -> URL {
        let validatedRelativePath = try validatedRelativeRepoPath(relativePath)
        return resolveBaseURL
            .appendingPathComponent(repo)
            .appendingPathComponent("resolve")
            .appendingPathComponent(revision)
            .appendingPathComponent(validatedRelativePath)
    }

    // MARK: - Private: Download Files

    /// Download every file concurrently (up to `maxConcurrentFileDownloads` at a time),
    /// staging each into `filesRoot`. Repository progress aggregates across all files
    /// that are in flight. A single file failure cancels the rest and throws.
    private func downloadAllFiles(
        _ files: [RepoFile],
        repo: String,
        revision: String,
        artifactVersion: String,
        filesRoot: URL,
        partialRoot: URL,
        resumeRoot: URL
    ) async throws {
        guard !files.isEmpty else { return }

        // The phase is already `.downloading` (from `beginRepositoryDownload`); any
        // partial files on disk are resumed silently, per-file, via Range requests in
        // `downloadTemporaryFile`. macOS has no pause/resume UI, so we never surface a
        // "Resuming" phase — that was a vestige of the discarded pause/resume feature.
        let maxConcurrent = min(max(1, engineConfiguration.maxConcurrentFiles), files.count)

        try await withThrowingTaskGroup(of: Void.self) { group in
            // Largest first: the multi-gigabyte long pole dominates total transfer time,
            // so its stream (or chunk queue) starts at t=0 instead of waiting behind a
            // catalog position; the small files fill remaining slots either way.
            var fileIterator = files.enumerated()
                .sorted { $0.element.size > $1.element.size }
                .makeIterator()

            // Prime the group with up to `maxConcurrent` file downloads.
            for _ in 0..<maxConcurrent {
                guard let (index, file) = fileIterator.next() else { break }
                group.addTask { [self] in
                    try await self.downloadOneFileCancelingPeers(
                        file,
                        fileIndex: index,
                        repo: repo,
                        revision: revision,
                        artifactVersion: artifactVersion,
                        filesRoot: filesRoot,
                        partialRoot: partialRoot,
                        resumeRoot: resumeRoot
                    )
                }
            }

            // Drain: each time a file finishes, start the next (bounded concurrency).
            while try await group.next() != nil {
                if await state.cancellationRequested() {
                    throw DownloadError.cancelled
                }
                guard let (index, file) = fileIterator.next() else { continue }
                group.addTask { [self] in
                    try await self.downloadOneFileCancelingPeers(
                        file,
                        fileIndex: index,
                        repo: repo,
                        revision: revision,
                        artifactVersion: artifactVersion,
                        filesRoot: filesRoot,
                        partialRoot: partialRoot,
                        resumeRoot: resumeRoot
                    )
                }
            }
        }
    }

    /// Stage a single file (skip if already valid, else download + validate into the
    /// staging tree), then report completion so the shared progress counter reconciles.
    private func downloadOneFile(
        _ file: RepoFile,
        fileIndex: Int,
        repo: String,
        revision: String,
        artifactVersion: String,
        filesRoot: URL,
        partialRoot: URL,
        resumeRoot: URL
    ) async throws {
        if await state.cancellationRequested() {
            throw DownloadError.cancelled
        }

        let relativePath = try Self.validatedRelativeRepoPath(file.path)
        let destURL = try Self.validatedDestinationURL(for: relativePath, in: filesRoot)
        let partialURL = try Self.partialURL(for: relativePath, in: partialRoot)
        let resumeDataURL = Self.resumeDataURL(for: relativePath, in: resumeRoot)
        try fileManager.createDirectory(at: destURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        try fileManager.createDirectory(at: partialURL.deletingLastPathComponent(), withIntermediateDirectories: true)

        if fileIsValid(at: destURL, expectedSize: file.size, sha256: file.sha256) {
            try await recordVerifiedReceipt(
                relativePath: relativePath,
                artifactVersion: artifactVersion,
                expectedSize: file.size,
                expectedSHA256: file.sha256,
                fileURL: destURL
            )
            await state.reportFileCompleted(
                fileIndex: fileIndex,
                expectedSize: file.size,
                wasTransferred: false
            )
            return
        }

        if fileManager.fileExists(atPath: destURL.path) {
            try? fileManager.removeItem(at: destURL)
        }

        let downloadURL = try file.absoluteURL ?? Self.fileResolveURL(
            resolveBaseURL: resolveBaseURL,
            repo: repo,
            revision: revision,
            relativePath: relativePath
        )
        if let artifactURLPolicy, !artifactURLPolicy.allowsInitialRequest(downloadURL) {
            throw DownloadError.apiError("Rejected untrusted artifact URL for \(relativePath)")
        }

        try await downloadFile(
            from: downloadURL,
            to: destURL,
            partialURL: partialURL,
            resumeDataURL: resumeDataURL,
            expectedSize: file.size,
            sha256: file.sha256,
            fileIndex: fileIndex,
            relativePath: relativePath
        )

        try await recordVerifiedReceipt(
            relativePath: relativePath,
            artifactVersion: artifactVersion,
            expectedSize: file.size,
            expectedSHA256: file.sha256,
            fileURL: destURL
        )

        await state.reportFileCompleted(fileIndex: fileIndex, expectedSize: file.size)
    }

    /// Wraps `downloadOneFile` so that when any file fails it immediately cancels every
    /// other in-flight download. Without this, a `ThrowingTaskGroup` failure would leave
    /// sibling URLSession tasks running until they complete naturally, stalling teardown.
    private func downloadOneFileCancelingPeers(
        _ file: RepoFile,
        fileIndex: Int,
        repo: String,
        revision: String,
        artifactVersion: String,
        filesRoot: URL,
        partialRoot: URL,
        resumeRoot: URL
    ) async throws {
        do {
            try await downloadOneFile(
                file,
                fileIndex: fileIndex,
                repo: repo,
                revision: revision,
                artifactVersion: artifactVersion,
                filesRoot: filesRoot,
                partialRoot: partialRoot,
                resumeRoot: resumeRoot
            )
        } catch {
            await state.requestCancellation()
            throw error
        }
    }

    private func downloadFile(
        from url: URL,
        to destination: URL,
        partialURL: URL,
        resumeDataURL: URL,
        expectedSize: Int64,
        sha256: String?,
        fileIndex: Int,
        relativePath: String
    ) async throws {
        if fileIsValid(at: partialURL, expectedSize: expectedSize, sha256: sha256) {
            try? fileManager.removeItem(at: Self.chunkSidecarURL(forPartial: partialURL))
            // Crash-recovered bytes are progress, not fresh network throughput:
            // baseline-fold them so the caller's completion report cannot inject
            // the whole file as one instantaneous speed sample.
            await state.reportPreexistingFileBytes(fileIndex: fileIndex, bytes: expectedSize)
            try publishDownloadedFile(partialURL, to: destination)
            return
        }

        // Retry transient failures (network drops, HTTP 5xx/429, integrity mismatches)
        // so a single hiccup no longer fails the whole repo download. The partial
        // already on disk lets each attempt resume via a Range request.
        var retryNumber = 0
        var integrityRetryUsed = false
        var avoidChunking = false
        while true {
            do {
                // Clear any stale task state for this file from a prior failed attempt so
                // its bytes don't inflate the progress counter during the retry.
                await state.resetFileProgress(fileIndex: fileIndex)
                try await attemptFileDownload(
                    from: url,
                    to: destination,
                    partialURL: partialURL,
                    resumeDataURL: resumeDataURL,
                    expectedSize: expectedSize,
                    sha256: sha256,
                    fileIndex: fileIndex,
                    relativePath: relativePath,
                    avoidChunking: avoidChunking
                )
                return
            } catch {
                if let dlError = error as? DownloadError {
                    let adjustment = Self.chunkFallbackAdjustment(for: dlError)
                    if adjustment.avoidChunking { avoidChunking = true }
                    if adjustment.clearPartial {
                        try? fileManager.removeItem(at: partialURL)
                        try? fileManager.removeItem(at: Self.chunkSidecarURL(forPartial: partialURL))
                    }
                }

                retryNumber += 1
                let disposition = ModelDownloadRetryPolicy.disposition(
                    error: error,
                    retryNumber: retryNumber,
                    integrityRetryAlreadyUsed: integrityRetryUsed
                )
                let delay: Double
                switch disposition {
                case .cancelled, .fail:
                    throw error
                case .retry(let afterSeconds):
                    delay = afterSeconds
                case .retryClean(let afterSeconds):
                    delay = afterSeconds
                    try? fileManager.removeItem(at: partialURL)
                    try? fileManager.removeItem(at: Self.chunkSidecarURL(forPartial: partialURL))
                    try? fileManager.removeItem(at: resumeDataURL)
                    if let dlError = error as? DownloadError,
                       case .integrityCheckFailed = dlError {
                        integrityRetryUsed = true
                    }
                }

                guard retryNumber <= engineConfiguration.maxDownloadRetries else { throw error }
                guard !Task.isCancelled,
                      !(await state.cancellationRequested()) else {
                    throw DownloadError.cancelled
                }
                await state.setRetry(number: retryNumber, reason: retryReason(for: error))
                do {
                    try await Task.sleep(for: .seconds(delay))
                } catch {
                    throw DownloadError.cancelled
                }
                guard !Task.isCancelled,
                      !(await state.cancellationRequested()) else {
                    throw DownloadError.cancelled
                }
                await state.setPhase(.downloading)
            }
        }
    }

    /// A single (un-retried) attempt to stage one file.
    private func attemptFileDownload(
        from url: URL,
        to destination: URL,
        partialURL: URL,
        resumeDataURL: URL,
        expectedSize: Int64,
        sha256: String?,
        fileIndex: Int,
        relativePath: String,
        avoidChunking: Bool
    ) async throws {
        // Large LFS files (known size + sha256) download as parallel byte-range chunks so
        // the biggest file is no longer a single-connection long pole. Smaller / non-LFS
        // files — or chunked attempts that already saw the server ignore Range — use the
        // single-stream path below.
        if !avoidChunking, chunkTransferPlanApplies(size: expectedSize, sha256: sha256) {
            try? fileManager.removeItem(at: resumeDataURL)
            try await downloadChunkedFile(
                from: url,
                to: destination,
                partialURL: partialURL,
                expectedSize: expectedSize,
                sha256: sha256,
                fileIndex: fileIndex,
                relativePath: relativePath
            )
            return
        }

        // A chunk-assembled partial is sparse: its logical size does not describe
        // contiguous leading bytes, so it can never be size-resumed by a single
        // stream — a Range resume would bake holes into the file, and a partial
        // whose logical size already equals the expected size would dead-end in
        // HTTP 416. If a chunk sidecar exists, drop both and start this file clean.
        let singleStreamSidecarURL = Self.chunkSidecarURL(forPartial: partialURL)
        if fileManager.fileExists(atPath: singleStreamSidecarURL.path) {
            try? fileManager.removeItem(at: partialURL)
            try? fileManager.removeItem(at: singleStreamSidecarURL)
        }
        let completedBytes = Self.fileSizeIfPresent(at: partialURL)
        let downloaded = try await downloadTemporaryFile(
            from: url,
            existingBytes: completedBytes,
            resumeDataURL: resumeDataURL,
            fileIndex: fileIndex
        )

        if await state.cancellationRequested() {
            try? fileManager.removeItem(at: downloaded.url)
            throw DownloadError.cancelled
        }

        if completedBytes > 0, downloaded.statusCode == 206,
           !Self.contentRange(downloaded.contentRange, startsAt: completedBytes) {
            try? fileManager.removeItem(at: downloaded.url)
            try? fileManager.removeItem(at: partialURL)
            throw DownloadError.rangeUnsupported(path: url.path)
        }

        try applyDownloadedTemporaryFile(
            downloaded,
            partialURL: partialURL,
            existingBytes: completedBytes
        )
        await state.beginFileVerification()
        do {
            try Self.validateDownloadedFile(
                at: partialURL,
                expectedSize: expectedSize,
                sha256: sha256
            )
        } catch {
            await state.endFileVerification()
            throw error
        }
        await state.endFileVerification()
        try? fileManager.removeItem(at: resumeDataURL)
        try publishDownloadedFile(partialURL, to: destination)
    }

    /// Single source of truth for which files transfer as parallel byte-range chunks,
    /// shared by the expected-task plan and the transfer path so the two can never
    /// disagree about a file's task shape.
    private func chunkTransferPlanApplies(size: Int64, sha256: String?) -> Bool {
        engineConfiguration.chunkLargeFiles
            && size >= engineConfiguration.chunkedDownloadThreshold
            && sha256 != nil
    }

    private func chunkTransferPlanApplies(to file: RepoFile) -> Bool {
        chunkTransferPlanApplies(size: file.size, sha256: file.sha256)
    }

    /// How a failed attempt adjusts the file-level retry: the server ignoring a
    /// byte-range request, an integrity mismatch, or a chunk-assembly error all force
    /// the remaining attempts onto the single-stream path instead of thrashing on
    /// chunks; range/assembly failures may also have left a sparse or holey partial
    /// that must be cleared before the next attempt.
    static func chunkFallbackAdjustment(
        for error: DownloadError
    ) -> (avoidChunking: Bool, clearPartial: Bool) {
        switch error {
        case .rangeUnsupported, .chunkAssemblyFailed:
            return (avoidChunking: true, clearPartial: true)
        case .integrityCheckFailed:
            return (avoidChunking: true, clearPartial: false)
        default:
            return (avoidChunking: false, clearPartial: false)
        }
    }

    private func retryReason(for error: Error) -> String {
        if let downloadError = error as? DownloadError {
            switch downloadError {
            case .httpError(let statusCode, _, _): return "HTTP \(statusCode)"
            case .integrityCheckFailed: return "Integrity verification"
            case .rangeUnsupported: return "Range response"
            case .chunkAssemblyFailed: return "Chunk assembly"
            case .fileDownloadFailed: return "Network transfer"
            case .cancelled: return "Cancelled"
            case .invalidRemotePath, .invalidLocalDestination, .apiError: return "Configuration"
            }
        }
        return "Network transfer"
    }

    /// One byte range of a chunked file, inclusive on both ends.
    struct ChunkRange: Equatable, Sendable {
        let start: Int64
        let end: Int64
    }

    /// FIFO work queue drained by a bounded pool of chunk workers. Any worker that frees
    /// up pulls the next pending range, so no range ever waits behind a slow sibling
    /// (work-conserving tail). `next()` returns nil once drained, aborted, or when the
    /// pulling task is cancelled, so a failing group never dispatches new ranges.
    actor ChunkWorkQueue {
        private var pending: [ChunkRange]
        private var nextIndex = 0
        private var isAborted = false

        init(ranges: [ChunkRange]) {
            pending = ranges
        }

        func next() -> ChunkRange? {
            guard !isAborted, !Task.isCancelled, nextIndex < pending.count else { return nil }
            defer { nextIndex += 1 }
            return pending[nextIndex]
        }

        func abort() {
            isAborted = true
        }
    }

    /// Download a large file as parallel byte-range chunks, assembling them into the
    /// partial, then validating size + SHA-256 (same gate as the single-stream path).
    /// Each chunk is its own `URLSessionDownloadTask` registered under the same
    /// `fileIndex`, so progress aggregates via the per-task counters. The completed-range
    /// sidecar makes the sparse partial resumable across process death: only ranges the
    /// sidecar does not cover are fetched, recovered bytes are folded into progress, and
    /// stale adopted tasks for recovered ranges (or a superseded whole-file task) are
    /// cancelled so they can never stream duplicate wire bytes unawaited.
    private func downloadChunkedFile(
        from url: URL,
        to destination: URL,
        partialURL: URL,
        expectedSize: Int64,
        sha256: String?,
        fileIndex: Int,
        relativePath: String
    ) async throws {
        let sidecarURL = Self.chunkSidecarURL(forPartial: partialURL)
        // The sidecar is the only trustworthy record of which ranges landed: a sparse
        // partial's holes are invisible to a size check. No valid sidecar (or an
        // implausibly large partial) fails closed to a clean restart of this file.
        var completed: [ChunkRange] = []
        if fileManager.fileExists(atPath: partialURL.path),
           Self.fileSizeIfPresent(at: partialURL) <= expectedSize,
           let recovered = Self.loadChunkSidecar(at: sidecarURL, expectedSize: expectedSize) {
            completed = recovered
        } else {
            try? fileManager.removeItem(at: partialURL)
            try? fileManager.removeItem(at: sidecarURL)
        }

        let allRanges = Self.chunkRanges(
            total: expectedSize,
            chunkSize: engineConfiguration.chunkTargetSize,
            tailWorkerCount: engineConfiguration.chunkWorkerCount
        )
        var missing: [ChunkRange] = []
        var recoveredBytes: Int64 = 0
        for range in allRanges {
            if Self.chunkRangeCovered(range, by: completed) {
                recoveredBytes += range.end - range.start + 1
                // A live adopted task for an already-recovered range would stream
                // duplicate bytes unawaited; take it out of the adoption map and stop it.
                await state.takeAdoptedTask(
                    forKey: ModelDownloadTaskIdentity.chunkReconciliationKey(
                        relativePath: relativePath,
                        start: range.start,
                        end: range.end
                    )
                )?.cancel()
            } else {
                missing.append(range)
            }
        }
        if recoveredBytes > 0 {
            await state.reportPreexistingFileBytes(fileIndex: fileIndex, bytes: recoveredBytes)
        }
        // A whole-file task for this file (an earlier single-stream fallback, or a
        // pre-chunking build's task) must not run beside chunk transfers.
        await state.takeAdoptedTask(for: url)?.cancel()

        if !missing.isEmpty {
            let assembly = ChunkAssemblyCoordinator(
                partialURL: partialURL,
                sidecarURL: sidecarURL,
                expectedSize: expectedSize,
                initialCompletedRanges: completed
            )
            try await assembly.open()
            do {
                try await runChunkTransfers(
                    missing: missing,
                    url: url,
                    fileIndex: fileIndex,
                    relativePath: relativePath,
                    assembly: assembly
                )
                await assembly.close()
            } catch {
                await assembly.close()
                throw error
            }
        }

        await state.beginFileVerification()
        do {
            try Self.validateDownloadedFile(at: partialURL, expectedSize: expectedSize, sha256: sha256)
        } catch {
            await state.endFileVerification()
            throw error
        }
        await state.endFileVerification()
        try? fileManager.removeItem(at: sidecarURL)
        try publishDownloadedFile(partialURL, to: destination)
    }

    /// Transfer the missing ranges. Foreground sessions drain a shared FIFO queue with a
    /// bounded worker pool (work-conserving tail; URLSession's per-host cap schedules the
    /// wire). Background sessions submit every range to the daemon up front instead:
    /// queued-but-unsubmitted work would die with the process, while a submitted task
    /// keeps transferring after termination and is adopted on relaunch — the OS
    /// background scheduler owns concurrency there (per-host caps are inert). In both
    /// shapes a chunk failure cancels every sibling's URLSession task via the group's
    /// cancellation handlers, so a file-level retry never overlaps stale chunk transfers.
    private func runChunkTransfers(
        missing: [ChunkRange],
        url: URL,
        fileIndex: Int,
        relativePath: String,
        assembly: ChunkAssemblyCoordinator
    ) async throws {
        if isBackgroundSession {
            try await withThrowingTaskGroup(of: Void.self) { group in
                for range in missing {
                    group.addTask { [self] in
                        try await self.downloadOneChunkWithRetry(
                            url: url,
                            range: range,
                            fileIndex: fileIndex,
                            relativePath: relativePath,
                            assembly: assembly,
                            transferSession: session
                        )
                    }
                }
                try await group.waitForAll()
            }
            return
        }

        let queue = ChunkWorkQueue(ranges: missing)
        let workerCount = max(1, min(engineConfiguration.chunkWorkerCount, missing.count))
        do {
            try await withThrowingTaskGroup(of: Void.self) { group in
                for workerIndex in 0..<workerCount {
                    let workerSession = chunkTransferSession(forWorker: workerIndex)
                    group.addTask { [self] in
                        while let range = await queue.next() {
                            try Task.checkCancellation()
                            try await self.downloadOneChunkWithRetry(
                                url: url,
                                range: range,
                                fileIndex: fileIndex,
                                relativePath: relativePath,
                                assembly: assembly,
                                transferSession: workerSession
                            )
                        }
                    }
                }
                try await group.waitForAll()
            }
        } catch {
            await queue.abort()
            throw error
        }
    }

    /// One range with a bounded transient-retry loop, so a single 5xx/429/network hiccup
    /// re-fetches 16-64 MiB instead of restarting a multi-gigabyte file. Non-transient
    /// dispositions (range ignored, integrity, assembly) throw immediately to the
    /// file-level fallback.
    private func downloadOneChunkWithRetry(
        url: URL,
        range: ChunkRange,
        fileIndex: Int,
        relativePath: String,
        assembly: ChunkAssemblyCoordinator,
        transferSession: URLSession
    ) async throws {
        var attempt = 0
        while true {
            do {
                try await downloadOneChunk(
                    url: url,
                    range: range,
                    fileIndex: fileIndex,
                    relativePath: relativePath,
                    assembly: assembly,
                    transferSession: transferSession
                )
                return
            } catch {
                attempt += 1
                guard attempt <= 2, !Task.isCancelled,
                      !(await state.cancellationRequested()) else { throw error }
                guard case .retry(let afterSeconds) = ModelDownloadRetryPolicy.disposition(
                    error: error,
                    retryNumber: attempt,
                    integrityRetryAlreadyUsed: true
                ) else { throw error }
                do {
                    try await Task.sleep(for: .seconds(afterSeconds))
                } catch {
                    throw DownloadError.cancelled
                }
            }
        }
    }

    /// Download one byte range of `url` and write it into the partial at its offset.
    /// Throws if the server ignores the Range request (200). Cancellation-aware: if the
    /// surrounding task is cancelled (group failure or caller cancellation), the
    /// in-flight URLSession task is cancelled so the delegate resumes the continuation
    /// promptly instead of letting the chunk stream to completion. On runs that carry a
    /// request identity, the chunk task's description encodes its range-qualified
    /// identity, so a background relaunch adopts the live task (consumed here) or claims
    /// its parked completion (inside `register`), and post-relaunch transfer metrics
    /// still attribute the bytes to their file.
    private func downloadOneChunk(
        url: URL,
        range: ChunkRange,
        fileIndex: Int,
        relativePath: String,
        assembly: ChunkAssemblyCoordinator,
        transferSession: URLSession
    ) async throws {
        let chunkKey = ModelDownloadTaskIdentity.chunkReconciliationKey(
            relativePath: relativePath,
            start: range.start,
            end: range.end
        )
        let task: URLSessionDownloadTask
        let existingBytes: Int64
        if let adopted = await state.takeAdoptedTask(forKey: chunkKey) {
            task = adopted
            existingBytes = max(0, adopted.countOfBytesReceived)
        } else {
            var request = URLRequest(url: url)
            request.setValue("bytes=\(range.start)-\(range.end)", forHTTPHeaderField: "Range")
            let fresh = transferSession.downloadTask(with: request)
            fresh.taskDescription = await state.expectedEntry(forKey: chunkKey)?
                .identity.encodedTaskDescription
            task = fresh
            existingBytes = 0
        }
        let key = taskKey(for: task, in: transferSession)
        chunkTaskPathsBox.withLock { $0[key] = relativePath }
        // Live-path removal happens in didCompleteWithError before the continuation
        // resumes, so this defer is a no-op there; it reaps the entry when no further
        // delegate event can arrive (adopted-already-terminal task, registration
        // fail-fast, parked-completion claim, cancellation).
        defer { chunkTaskPathsBox.withLock { $0.removeValue(forKey: key) } }
        let downloaded: DownloadedTemporaryFile = try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                Task {
                    let shouldResume = await state.register(
                        taskKey: key,
                        task: task,
                        destination: url,
                        continuation: continuation,
                        resumeDataURL: nil,
                        fileIndex: fileIndex,
                        existingBytes: existingBytes
                    )
                    if shouldResume, task.state == .suspended { task.resume() }
                }
            }
        } onCancel: {
            task.cancel()
        }

        // The delegate treats 200 and 206 as success; for a range request 200 means the
        // server ignored Range and returned the whole file — throw a dedicated error so the
        // file-level retry falls back to a single stream instead of thrashing on chunks.
        guard downloaded.statusCode == 206,
              Self.contentRange(downloaded.contentRange, matchesStart: range.start, end: range.end) else {
            try? fileManager.removeItem(at: downloaded.url)
            throw DownloadError.rangeUnsupported(path: url.path)
        }

        if await state.cancellationRequested() {
            try? fileManager.removeItem(at: downloaded.url)
            throw DownloadError.cancelled
        }

        try await assembly.writeChunk(tempURL: downloaded.url, offset: range.start)
        try? fileManager.removeItem(at: downloaded.url)
        // Bytes are in the partial before the sidecar records them; a crash between
        // the two only re-fetches this range (idempotent rewrite).
        await assembly.recordCompleted(range: range)
    }

    /// Partition `[0, total)` into uniform `chunkSize` ranges, except the final
    /// `tailWorkerCount x chunkSize` bytes, which are emitted as quarter-size ranges.
    /// The shrinking tail bounds the cost of the last-range straggler: with uniform
    /// ranges the file's completion waits on one connection finishing a full chunk at
    /// whatever rate the CDN shapes that single connection to; quarter-size tail ranges
    /// cut that worst case by 4x while adding only ~3 x tailWorkerCount extra requests.
    static func chunkRanges(
        total: Int64,
        chunkSize: Int64,
        tailWorkerCount: Int
    ) -> [ChunkRange] {
        guard total > 0, chunkSize > 0 else { return [] }
        let tailChunkSize = max(1, chunkSize / 4)
        let tailWindow = min(total, Int64(max(0, tailWorkerCount)) * chunkSize)
        let bodyTotal = total - tailWindow

        var ranges: [ChunkRange] = []
        var start: Int64 = 0
        while start < bodyTotal {
            let end = min(start + chunkSize - 1, bodyTotal - 1)
            ranges.append(ChunkRange(start: start, end: end))
            start = end + 1
        }
        start = bodyTotal
        while start < total {
            let end = min(start + tailChunkSize - 1, total - 1)
            ranges.append(ChunkRange(start: start, end: end))
            start = end + 1
        }
        return ranges
    }

    /// Sort and merge inclusive ranges into a minimal non-overlapping set (adjacent
    /// ranges coalesce). Invalid ranges (end < start) are dropped.
    static func mergedChunkRanges(_ ranges: [ChunkRange]) -> [ChunkRange] {
        let sorted = ranges.filter { $0.start <= $0.end }.sorted { $0.start < $1.start }
        var merged: [ChunkRange] = []
        for range in sorted {
            if let last = merged.last, range.start <= last.end + 1 {
                if range.end > last.end {
                    merged[merged.count - 1] = ChunkRange(start: last.start, end: range.end)
                }
            } else {
                merged.append(range)
            }
        }
        return merged
    }

    /// Whether `range` is fully covered by the merged completed set. Coverage-based
    /// (not exact-match) so a chunk-size configuration change across launches degrades
    /// to re-fetching partially covered ranges instead of corrupting resume state.
    static func chunkRangeCovered(_ range: ChunkRange, by merged: [ChunkRange]) -> Bool {
        merged.contains { $0.start <= range.start && range.end <= $0.end }
    }

    static func chunkSidecarURL(forPartial partialURL: URL) -> URL {
        partialURL.appendingPathExtension("ranges")
    }

    /// Load the completed-range record for a partial. Returns the merged ranges only
    /// when the sidecar is structurally valid and matches `expectedSize`; anything
    /// else returns nil so the caller restarts the file cleanly (fail closed).
    static func loadChunkSidecar(at url: URL, expectedSize: Int64) -> [ChunkRange]? {
        guard let data = try? Data(contentsOf: url),
              let sidecar = try? JSONDecoder().decode(ChunkCompletionSidecar.self, from: data),
              sidecar.schemaVersion == ChunkCompletionSidecar.currentSchemaVersion,
              sidecar.expectedSize == expectedSize,
              sidecar.ranges.allSatisfy({ pair in
                  pair.count == 2 && pair[0] >= 0 && pair[0] <= pair[1] && pair[1] < expectedSize
              }) else {
            return nil
        }
        return mergedChunkRanges(sidecar.ranges.map { ChunkRange(start: $0[0], end: $0[1]) })
    }

    /// Best-effort atomic write: a lost sidecar only costs a re-fetch after the next
    /// crash, and the atomic write keeps a torn file from ever validating.
    static func writeChunkSidecar(at url: URL, expectedSize: Int64, ranges: [ChunkRange]) {
        let sidecar = ChunkCompletionSidecar(
            schemaVersion: ChunkCompletionSidecar.currentSchemaVersion,
            expectedSize: expectedSize,
            ranges: ranges.map { [$0.start, $0.end] }
        )
        guard let data = try? JSONEncoder().encode(sidecar) else { return }
        try? data.write(to: url, options: .atomic)
    }

    static func contentRange(_ value: String?, startsAt expectedStart: Int64) -> Bool {
        guard let value,
              let match = value.range(
                of: #"^bytes\s+([0-9]+)-([0-9]+)/(?:[0-9]+|\*)$"#,
                options: [.regularExpression, .caseInsensitive]
              ) else { return false }
        let matched = String(value[match])
        guard let rangePart = matched.split(separator: " ").last?.split(separator: "/").first,
              let start = rangePart.split(separator: "-").first.flatMap({ Int64($0) }) else {
            return false
        }
        return start == expectedStart
    }

    static func contentRange(_ value: String?, matchesStart expectedStart: Int64, end expectedEnd: Int64) -> Bool {
        guard contentRange(value, startsAt: expectedStart),
              let value,
              let rangePart = value.split(separator: " ").last?.split(separator: "/").first else {
            return false
        }
        let bounds = rangePart.split(separator: "-")
        guard bounds.count == 2, let end = Int64(bounds[1]) else { return false }
        return end == expectedEnd
    }

    private func downloadTemporaryFile(
        from url: URL,
        existingBytes: Int64,
        resumeDataURL: URL,
        fileIndex: Int
    ) async throws -> DownloadedTemporaryFile {
        if Task.isCancelled {
            throw DownloadError.cancelled
        }
        if await state.cancellationRequested() {
            throw DownloadError.cancelled
        }

        if let adoptedTask = await state.takeAdoptedTask(for: url) {
            return try await withCheckedThrowingContinuation { continuation in
                Task {
                    let receivedBytes = max(existingBytes, adoptedTask.countOfBytesReceived)
                    let shouldResume = await state.register(
                        taskKey: self.taskKey(for: adoptedTask, in: self.session),
                        task: adoptedTask,
                        destination: url,
                        continuation: continuation,
                        resumeDataURL: resumeDataURL,
                        fileIndex: fileIndex,
                        existingBytes: receivedBytes
                    )
                    if shouldResume, adoptedTask.state == .suspended {
                        adoptedTask.resume()
                    }
                }
            }
        }

        if fileManager.fileExists(atPath: resumeDataURL.path),
           let resumeData = try? Data(contentsOf: resumeDataURL) {
            do {
                return try await withCheckedThrowingContinuation { continuation in
                    let task = session.downloadTask(withResumeData: resumeData)
                    Task {
                        task.taskDescription = await state.expectedIdentity(for: url)?.encodedTaskDescription
                        let shouldResume = await state.register(
                            taskKey: self.taskKey(for: task, in: self.session),
                            task: task,
                            destination: url,
                            continuation: continuation,
                            resumeDataURL: resumeDataURL,
                            fileIndex: fileIndex,
                            existingBytes: existingBytes
                        )
                        if shouldResume { task.resume() }
                    }
                }
            } catch {
                try? fileManager.removeItem(at: resumeDataURL)
                if Task.isCancelled {
                    throw DownloadError.cancelled
                }
                if await state.cancellationRequested() {
                    throw DownloadError.cancelled
                }
            }
        }

        if Task.isCancelled {
            throw DownloadError.cancelled
        }
        if await state.cancellationRequested() {
            throw DownloadError.cancelled
        }
        let request = Self.downloadRequest(for: url, existingBytes: existingBytes)
        return try await withCheckedThrowingContinuation { continuation in
            let task = session.downloadTask(with: request)
            Task {
                task.taskDescription = await state.expectedIdentity(for: url)?.encodedTaskDescription
                let shouldResume = await state.register(
                    taskKey: self.taskKey(for: task, in: self.session),
                    task: task,
                    destination: url,
                    continuation: continuation,
                    resumeDataURL: resumeDataURL,
                    fileIndex: fileIndex,
                    existingBytes: existingBytes
                )
                if shouldResume { task.resume() }
            }
        }
    }

    private func applyDownloadedTemporaryFile(
        _ downloaded: DownloadedTemporaryFile,
        partialURL: URL,
        existingBytes: Int64
    ) throws {
        defer { try? fileManager.removeItem(at: downloaded.url) }

        if existingBytes > 0, downloaded.statusCode == 206 {
            let readHandle = try FileHandle(forReadingFrom: downloaded.url)
            defer { try? readHandle.close() }
            let writeHandle = try FileHandle(forWritingTo: partialURL)
            defer { try? writeHandle.close() }
            try writeHandle.seekToEnd()
            while autoreleasepool(invoking: {
                let data = readHandle.readData(ofLength: 1_048_576)
                guard !data.isEmpty else { return false }
                writeHandle.write(data)
                return true
            }) {}
            try? writeHandle.synchronize()
            return
        }

        if fileManager.fileExists(atPath: partialURL.path) {
            try fileManager.removeItem(at: partialURL)
        }
        try fileManager.moveItem(at: downloaded.url, to: partialURL)
    }

    private func publishDownloadedFile(_ fileURL: URL, to destination: URL) throws {
        try fileManager.createDirectory(
            at: destination.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        if fileManager.fileExists(atPath: destination.path) {
            _ = try fileManager.replaceItemAt(
                destination,
                withItemAt: fileURL,
                backupItemName: nil,
                options: []
            )
        } else {
            try fileManager.moveItem(at: fileURL, to: destination)
        }
    }

    private func recordVerifiedReceipt(
        relativePath: String,
        artifactVersion: String,
        expectedSize: Int64,
        expectedSHA256: String?,
        fileURL: URL
    ) async throws {
        let attributes = try fileManager.attributesOfItem(atPath: fileURL.path)
        let fileSize = (attributes[.size] as? NSNumber)?.int64Value ?? 0
        let modificationDate = attributes[.modificationDate] as? Date ?? .distantPast
        let fileIdentifier = (attributes[.systemFileNumber] as? NSNumber)?.uint64Value
        let receipt = VerifiedArtifactReceipt(
            relativePath: relativePath,
            artifactVersion: artifactVersion,
            expectedSize: expectedSize,
            expectedSHA256: Self.normalizedSHA256(expectedSHA256),
            fileSize: fileSize,
            modificationTimeNanoseconds: Int64(modificationDate.timeIntervalSince1970 * 1_000_000_000),
            fileIdentifier: fileIdentifier,
            verificationProcessGeneration: verificationProcessGeneration
        )
        await state.recordVerifiedReceipt(receipt)
        await verifiedArtifactHandler?.handler(receipt)
    }

    private func verifyDownloadedFilesUsingReceipts(
        _ files: [RepoFile],
        artifactVersion: String,
        in root: URL
    ) async throws {
        let receipts = await state.verifiedReceipts()
        for file in files {
            let relativePath = try Self.validatedRelativeRepoPath(file.path)
            let destination = try Self.validatedDestinationURL(for: relativePath, in: root)
            let attributes = try fileManager.attributesOfItem(atPath: destination.path)
            let currentSize = (attributes[.size] as? NSNumber)?.int64Value ?? 0
            let currentModificationDate = attributes[.modificationDate] as? Date ?? .distantPast
            let currentModificationNanoseconds = Int64(
                currentModificationDate.timeIntervalSince1970 * 1_000_000_000
            )
            let currentFileIdentifier = (attributes[.systemFileNumber] as? NSNumber)?.uint64Value
            guard let receipt = receipts[relativePath],
                  receipt.matches(
                    relativePath: relativePath,
                    artifactVersion: artifactVersion,
                    expectedSize: file.size,
                    expectedSHA256: Self.normalizedSHA256(file.sha256),
                    fileSize: currentSize,
                    modificationTimeNanoseconds: currentModificationNanoseconds,
                    fileIdentifier: currentFileIdentifier,
                    processGeneration: verificationProcessGeneration
                  ) else {
                throw DownloadError.integrityCheckFailed(
                    path: relativePath,
                    reason: "missing or changed same-process verification receipt"
                )
            }
        }
    }

    private func installStagedRepository(filesRoot: URL, targetDir: URL) throws {
        let installParent = targetDir.deletingLastPathComponent()
        try fileManager.createDirectory(at: installParent, withIntermediateDirectories: true)

        let installingURL = installParent
            .appendingPathComponent(".\(targetDir.lastPathComponent).installing.\(UUID().uuidString)", isDirectory: true)
        if fileManager.fileExists(atPath: installingURL.path) {
            try fileManager.removeItem(at: installingURL)
        }
        try fileManager.moveItem(at: filesRoot, to: installingURL)

        if fileManager.fileExists(atPath: targetDir.path) {
            _ = try fileManager.replaceItemAt(
                targetDir,
                withItemAt: installingURL,
                backupItemName: nil,
                options: []
            )
        } else {
            try fileManager.moveItem(at: installingURL, to: targetDir)
        }
    }

    private func persistInstalledIntegrityManifest(
        repo: String,
        revision: String,
        targetDir: URL,
        files: [RepoFile],
        filesRoot: URL,
        sharedComponentManifest: SharedComponentInstalledModelManifest?
    ) throws {
        let manifest = ModelAssetIntegrityManifest(
            repo: repo,
            revision: revision,
            targetFolder: targetDir.lastPathComponent,
            createdAtUTC: ISO8601DateFormatter().string(from: Date()),
            files: files.map {
                ModelAssetIntegrityManifest.FileEntry(
                    path: $0.path,
                    size: $0.size,
                    sha256: $0.sha256
                )
            },
            sharedComponentContentIdentity: sharedComponentManifest?.contentIdentity,
            sharedComponentCompatibilityIdentity: sharedComponentManifest?.compatibilityIdentity
        )
        let data = try JSONEncoder().encode(manifest)
        try data.write(
            to: filesRoot.appendingPathComponent(ModelAssetIntegrityManifest.filename, isDirectory: false),
            options: .atomic
        )
    }

    private static func validateStagedRepository(
        at root: URL,
        repo: String,
        revision: String,
        targetFolder: String,
        files: [RepoFile],
        sharedComponentManifest: SharedComponentInstalledModelManifest
    ) throws {
        let manifestURL = root.appendingPathComponent(ModelAssetIntegrityManifest.filename)
        let manifest = try JSONDecoder().decode(
            ModelAssetIntegrityManifest.self,
            from: Data(contentsOf: manifestURL)
        )
        guard manifest.schemaVersion == ModelAssetIntegrityManifest.currentSchemaVersion,
              manifest.repo == repo,
              manifest.revision == revision,
              manifest.targetFolder == targetFolder,
              manifest.sharedComponentContentIdentity == sharedComponentManifest.contentIdentity,
              manifest.sharedComponentCompatibilityIdentity == sharedComponentManifest.compatibilityIdentity else {
            throw DownloadError.integrityCheckFailed(
                path: ModelAssetIntegrityManifest.filename,
                reason: "installed manifest identity mismatch"
            )
        }
        let expectedEntries = Dictionary(uniqueKeysWithValues: files.map {
            ($0.path, ($0.size, normalizedSHA256($0.sha256)))
        })
        let manifestEntries = Dictionary(uniqueKeysWithValues: manifest.files.map {
            ($0.path, ($0.size, normalizedSHA256($0.sha256)))
        })
        guard expectedEntries.count == files.count,
              manifestEntries.count == expectedEntries.count,
              expectedEntries.allSatisfy({ path, expected in
                  guard let actual = manifestEntries[path] else { return false }
                  return actual.0 == expected.0 && actual.1 == expected.1
              }) else {
            throw DownloadError.integrityCheckFailed(
                path: ModelAssetIntegrityManifest.filename,
                reason: "installed file identity mismatch"
            )
        }
        for file in files {
            let url = try validatedDestinationURL(for: file.path, in: root)
            let values = try url.resourceValues(
                forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey]
            )
            guard values.isRegularFile == true,
                  values.isSymbolicLink != true,
                  Int64(values.fileSize ?? -1) == file.size else {
                throw DownloadError.integrityCheckFailed(
                    path: file.path,
                    reason: "installed file is missing, linked by pathname, or has the wrong size"
                )
            }
        }
    }

    private func persistDownloadState(
        repo: String,
        revision: String,
        targetDir: URL,
        files: [RepoFile],
        stagingRoot: URL
    ) throws {
        let manifest = DownloadStateManifest(
            schemaVersion: 1,
            repo: repo,
            revision: revision,
            targetFolder: targetDir.lastPathComponent,
            updatedAtUTC: ISO8601DateFormatter().string(from: Date()),
            files: files.map {
                DownloadStateManifest.FileEntry(
                    path: $0.path,
                    size: $0.size,
                    sha256: $0.sha256
                )
            }
        )
        let data = try JSONEncoder().encode(manifest)
        try data.write(
            to: stagingRoot.appendingPathComponent("download-state.json"),
            options: .atomic
        )
    }

    private func fileIsValid(at url: URL, expectedSize: Int64, sha256: String?) -> Bool {
        do {
            try Self.validateDownloadedFile(at: url, expectedSize: expectedSize, sha256: sha256)
            return true
        } catch {
            return false
        }
    }

    private static func stagingRoot(forTargetDirectory targetDir: URL) -> URL {
        targetDir
            .deletingLastPathComponent()
            .appendingPathComponent(".qwenvoice-downloads", isDirectory: true)
            .appendingPathComponent(targetDir.lastPathComponent, isDirectory: true)
    }

    /// Remove the staging tree (partials, resume data, staged files) for a target
    /// directory. Call when a model is permanently deleted so failed/partial downloads
    /// don't orphan multi-GB under `.qwenvoice-downloads/`. Best-effort.
    public static func discardStaging(forTargetDirectory targetDir: URL) {
        try? FileManager.default.removeItem(at: stagingRoot(forTargetDirectory: targetDir))
    }

    /// Mark `url` excluded from Time Machine/backup (best-effort). Inlined here so the
    /// downloader has no app-target dependency and can live in the shared QwenVoiceCore
    /// module (used by the macOS app, the iOS app, and the `vocello` CLI alike).
    private static func markExcludedFromBackup(_ url: URL) {
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        var mutableURL = url
        try? mutableURL.setResourceValues(values)
    }

    private static func partialURL(for relativePath: String, in root: URL) throws -> URL {
        try validatedDestinationURL(for: relativePath, in: root)
            .appendingPathExtension("partial")
    }

    private static func resumeDataURL(for relativePath: String, in root: URL) -> URL {
        let safeName = relativePath
            .replacingOccurrences(of: "/", with: "__")
            .replacingOccurrences(of: ":", with: "_")
        return root.appendingPathComponent("\(safeName).resume")
    }

    private static func fileSizeIfPresent(at url: URL) -> Int64 {
        guard let values = try? url.resourceValues(forKeys: [.fileSizeKey]) else { return 0 }
        return Int64(values.fileSize ?? 0)
    }

    // MARK: - URLSessionDownloadDelegate

    /// Background sessions only: the system calls this when the session has finished delivering
    /// all enqueued events (e.g. after it relaunched the app to complete a background download).
    /// Forward the session's identifier so iOS can flush its app-delegate completion handler.
    /// Foreground sessions (macOS/CLI) never trigger this, so they're unaffected.
    public func urlSessionDidFinishEvents(forBackgroundURLSession session: URLSession) {
        guard let identifier = session.configuration.identifier else { return }
        Task {
            if await state.markBackgroundEventsFinished() {
                backgroundSessionCompletionHandler?(identifier)
            }
        }
    }

    public func urlSession(
        _ session: URLSession,
        taskIsWaitingForConnectivity task: URLSessionTask
    ) {
        Task { await state.setWaitingForConnectivity(true) }
    }

    public func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        willPerformHTTPRedirection response: HTTPURLResponse,
        newRequest request: URLRequest,
        completionHandler: @escaping (URLRequest?) -> Void
    ) {
        guard let artifactURLPolicy else {
            completionHandler(request)
            return
        }
        let sourceURL = response.url ?? task.currentRequest?.url ?? task.originalRequest?.url
        guard let destinationURL = request.url,
              artifactURLPolicy.allowsRedirect(from: sourceURL, to: destinationURL) else {
            completionHandler(nil)
            return
        }
        completionHandler(request)
    }

    public func urlSession(
        _ session: URLSession,
        downloadTask: URLSessionDownloadTask,
        didWriteData bytesWritten: Int64,
        totalBytesWritten: Int64,
        totalBytesExpectedToWrite: Int64
    ) {
        let taskID = taskKey(for: downloadTask, in: session)
        let shouldForward = delegateProgressGate.withLock { gate in
            gate.shouldForward(
                taskID: taskID,
                totalBytesWritten: totalBytesWritten,
                totalBytesExpected: totalBytesExpectedToWrite,
                uptime: ProcessInfo.processInfo.systemUptime
            )
        }
        guard shouldForward else { return }
        Task(priority: .utility) {
            await state.setWaitingForConnectivity(false)
            await state.reportProgress(taskID: taskID, totalBytesWritten: totalBytesWritten)
        }
    }

    public func urlSession(
        _ session: URLSession,
        downloadTask: URLSessionDownloadTask,
        didFinishDownloadingTo location: URL
    ) {
        let taskID = taskKey(for: downloadTask, in: session)

        let response = downloadTask.response as? HTTPURLResponse
        let statusCode = response?.statusCode
        let retryAfterSeconds = Self.retryAfterSeconds(from: response)
        let contentRange = response?.value(forHTTPHeaderField: "Content-Range")
        if let statusCode, ![200, 206].contains(statusCode) {
            terminalEventSequencer.stage(taskID: taskID) { [state] in
                let path = await state.destinationPath(taskID: taskID)
                await state.resumeFailure(
                    taskID: taskID,
                    error: DownloadError.httpError(
                        statusCode: statusCode,
                        path: path,
                        retryAfterSeconds: retryAfterSeconds
                    )
                )
            }
            return
        }

        let safeTmp = durableTemporaryDirectory
            .appendingPathComponent("task-\(taskID)-\(UUID().uuidString)")

        do {
            try fileManager.createDirectory(at: durableTemporaryDirectory, withIntermediateDirectories: true)
            try fileManager.moveItem(at: location, to: safeTmp)
            let finalBytes = downloadTask.countOfBytesReceived
            terminalEventSequencer.stage(taskID: taskID) { [state] in
                await state.setWaitingForConnectivity(false)
                await state.reportProgress(taskID: taskID, totalBytesWritten: finalBytes)
                await state.stageSuccess(
                    taskID: taskID,
                    identity: ModelDownloadTaskIdentity.decode(taskDescription: downloadTask.taskDescription),
                    temporaryFile: DownloadedTemporaryFile(
                        url: safeTmp,
                        statusCode: statusCode,
                        retryAfterSeconds: retryAfterSeconds,
                        contentRange: contentRange
                    )
                )
            }
        } catch {
            terminalEventSequencer.stage(taskID: taskID) { [state] in
                await state.resumeFailure(taskID: taskID, error: error)
            }
        }
    }

    public func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        didFinishCollecting metrics: URLSessionTaskMetrics
    ) {
        guard let transferMetricsHandler else { return }
        let transactions = metrics.transactionMetrics
        let last = transactions.last
        let identity = ModelDownloadTaskIdentity.decode(taskDescription: task.taskDescription)
        // Chunk tasks carry no task-description identity; attribute their bytes to
        // their file via the chunk-path map so wireBytes accounting stays exact.
        let chunkPath = chunkTaskPathsBox.withLock { $0[taskKey(for: task, in: session)] }
        transferMetricsHandler.handler(
            TransferMetrics(
                relativePath: identity?.relativePath ?? chunkPath,
                protocolName: last?.networkProtocolName,
                redirectCount: metrics.redirectCount,
                reusedConnection: transactions.contains(where: { $0.isReusedConnection }),
                cellular: transactions.contains(where: { $0.isCellular }),
                constrained: transactions.contains(where: { $0.isConstrained }),
                expensive: transactions.contains(where: { $0.isExpensive }),
                transferredBytes: task.countOfBytesReceived,
                durationSeconds: metrics.taskInterval.duration
            )
        )
    }

    public func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        didCompleteWithError error: Error?
    ) {
        let taskID = taskKey(for: task, in: session)
        delegateProgressGate.withLock { gate in
            gate.finish(taskID: taskID)
        }
        chunkTaskPathsBox.withLock { $0.removeValue(forKey: taskID) }
        terminalEventSequencer.complete(taskID: taskID) { [state] in
            await state.setWaitingForConnectivity(false)
            guard let error else {
                await state.completeStagedSuccess(taskID: taskID)
                return
            }
            let path = await state.destinationPath(taskID: taskID)
            if (error as NSError).code == NSURLErrorCancelled {
                await state.resumeFailure(taskID: taskID, error: DownloadError.cancelled)
            } else {
                await state.resumeFailure(
                    taskID: taskID,
                    error: DownloadError.fileDownloadFailed(path: path, underlying: error)
                )
            }
        }
    }

    private static func retryAfterSeconds(from response: HTTPURLResponse?) -> Double? {
        guard let value = response?.value(forHTTPHeaderField: "Retry-After") else { return nil }
        if let seconds = Double(value.trimmingCharacters(in: .whitespacesAndNewlines)) {
            return min(max(seconds, 0), 300)
        }
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.dateFormat = "EEE',' dd MMM yyyy HH':'mm':'ss z"
        guard let date = formatter.date(from: value) else { return nil }
        return min(max(date.timeIntervalSinceNow, 0), 300)
    }
}
