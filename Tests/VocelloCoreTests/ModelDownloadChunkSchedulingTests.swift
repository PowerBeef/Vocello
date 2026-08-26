import Foundation
import XCTest

@testable import QwenVoiceCore

/// The chunked-transfer scheduler (download-throughput PR 1): range generation with the
/// shrinking tail, the work-conserving chunk queue, the single-stream fallback
/// adjustments, multi-task-per-file progress aggregation, speed-sample exclusion for
/// bytes that never crossed the network this run, and out-of-order chunk assembly.
/// Everything here is model-free and network-free.
final class ModelDownloadChunkSchedulingTests: XCTestCase {
    private typealias ChunkRange = HuggingFaceDownloader.ChunkRange

    // MARK: - Range generation

    func testChunkRangesAreContiguousNonOverlappingAndFullyCovering() {
        let total: Int64 = 2_130_000_000
        let chunk: Int64 = 64 * 1024 * 1024
        let ranges = HuggingFaceDownloader.chunkRanges(total: total, chunkSize: chunk, tailWorkerCount: 4)

        XCTAssertEqual(ranges.first?.start, 0)
        XCTAssertEqual(ranges.last?.end, total - 1)
        for (previous, next) in zip(ranges, ranges.dropFirst()) {
            XCTAssertEqual(next.start, previous.end + 1, "ranges must be contiguous")
        }
        for range in ranges {
            XCTAssertLessThanOrEqual(range.end - range.start + 1, chunk)
        }
        XCTAssertEqual(ranges.reduce(Int64(0)) { $0 + ($1.end - $1.start + 1) }, total)
    }

    func testChunkRangesEmitQuarterSizeTailWindow() {
        // total 100, chunk 40, one tail worker: body [0,59] as 40+20, tail 40 bytes as 10s.
        let ranges = HuggingFaceDownloader.chunkRanges(total: 100, chunkSize: 40, tailWorkerCount: 1)
        XCTAssertEqual(ranges, [
            ChunkRange(start: 0, end: 39),
            ChunkRange(start: 40, end: 59),
            ChunkRange(start: 60, end: 69),
            ChunkRange(start: 70, end: 79),
            ChunkRange(start: 80, end: 89),
            ChunkRange(start: 90, end: 99),
        ])
    }

    func testChunkRangesSmallerThanTailWindowAreAllTailSized() {
        // total 50 <= tailWindow 80: no body, five 10-byte tail ranges.
        let ranges = HuggingFaceDownloader.chunkRanges(total: 50, chunkSize: 40, tailWorkerCount: 2)
        XCTAssertEqual(ranges.count, 5)
        XCTAssertTrue(ranges.allSatisfy { $0.end - $0.start + 1 == 10 })
        XCTAssertEqual(ranges.first?.start, 0)
        XCTAssertEqual(ranges.last?.end, 49)
    }

    func testChunkRangesRejectDegenerateInputs() {
        XCTAssertTrue(HuggingFaceDownloader.chunkRanges(total: 0, chunkSize: 64, tailWorkerCount: 4).isEmpty)
        XCTAssertTrue(HuggingFaceDownloader.chunkRanges(total: -1, chunkSize: 64, tailWorkerCount: 4).isEmpty)
        XCTAssertTrue(HuggingFaceDownloader.chunkRanges(total: 100, chunkSize: 0, tailWorkerCount: 4).isEmpty)
    }

    func testChunkRangesReplaceTheOversizedStaticSplit() {
        // The retired formula max(chunkTarget, size/6) produced ~355 MB chunks for a
        // 2.13 GB file, leaving the last chunk alone on one throttled connection for
        // minutes. The generator must never emit a range larger than chunkTargetSize.
        let total: Int64 = 2_130_000_000
        let chunk: Int64 = 64 * 1024 * 1024
        let ranges = HuggingFaceDownloader.chunkRanges(total: total, chunkSize: chunk, tailWorkerCount: 4)
        let largest = ranges.map { $0.end - $0.start + 1 }.max() ?? 0
        XCTAssertLessThanOrEqual(largest, chunk)
        // And the final ranges are quarter-size so the straggler window is bounded.
        let tail = ranges.suffix(4)
        XCTAssertTrue(tail.allSatisfy { $0.end - $0.start + 1 <= chunk / 4 })
    }

    // MARK: - Chunk work queue

    func testChunkWorkQueueDrainsEveryRangeExactlyOnceAcrossWorkers() async {
        let ranges = (0..<37).map { ChunkRange(start: Int64($0) * 10, end: Int64($0) * 10 + 9) }
        let queue = HuggingFaceDownloader.ChunkWorkQueue(ranges: ranges)

        let drained = await withTaskGroup(of: [ChunkRange].self, returning: [ChunkRange].self) { group in
            for _ in 0..<4 {
                group.addTask {
                    var pulled: [ChunkRange] = []
                    while let range = await queue.next() {
                        pulled.append(range)
                    }
                    return pulled
                }
            }
            var all: [ChunkRange] = []
            for await pulled in group { all.append(contentsOf: pulled) }
            return all
        }

        XCTAssertEqual(drained.count, ranges.count)
        XCTAssertEqual(Set(drained.map(\.start)).count, ranges.count, "no range may be dispatched twice")
    }

    func testChunkWorkQueueAbortStopsDispatch() async {
        let queue = HuggingFaceDownloader.ChunkWorkQueue(ranges: [
            ChunkRange(start: 0, end: 9), ChunkRange(start: 10, end: 19),
        ])
        let first = await queue.next()
        XCTAssertNotNil(first)
        await queue.abort()
        let afterAbort = await queue.next()
        XCTAssertNil(afterAbort)
    }

    func testChunkWorkQueueReturnsNilForCancelledWorker() async {
        let queue = HuggingFaceDownloader.ChunkWorkQueue(ranges: [ChunkRange(start: 0, end: 9)])
        let worker = Task { () -> ChunkRange? in
            withUnsafeCurrentTask { $0?.cancel() }
            return await queue.next()
        }
        let pulled = await worker.value
        XCTAssertNil(pulled, "a cancelled worker must not start new ranges")
    }

    // MARK: - Single-stream fallback adjustments

    func testChunkFallbackAdjustmentMapsErrorClasses() {
        let range = HuggingFaceDownloader.chunkFallbackAdjustment(
            for: .rangeUnsupported(path: "p"))
        XCTAssertTrue(range.avoidChunking)
        XCTAssertTrue(range.clearPartial)

        let assembly = HuggingFaceDownloader.chunkFallbackAdjustment(
            for: .chunkAssemblyFailed(path: "p", reason: "r"))
        XCTAssertTrue(assembly.avoidChunking)
        XCTAssertTrue(assembly.clearPartial)

        let integrity = HuggingFaceDownloader.chunkFallbackAdjustment(
            for: .integrityCheckFailed(path: "p", reason: "r"))
        XCTAssertTrue(integrity.avoidChunking)
        XCTAssertFalse(integrity.clearPartial, "a size/digest mismatch partial is cleared by retryClean, not here")

        let transient = HuggingFaceDownloader.chunkFallbackAdjustment(
            for: .httpError(statusCode: 503, path: "p"))
        XCTAssertFalse(transient.avoidChunking)
        XCTAssertFalse(transient.clearPartial)
    }

    // MARK: - Registry: multi-task aggregation and speed-sample exclusion

    private final class ProgressSink: @unchecked Sendable {
        private let lock = NSLock()
        private var emissions: [HuggingFaceDownloader.RepositoryProgress] = []

        func append(_ progress: HuggingFaceDownloader.RepositoryProgress) {
            lock.lock()
            defer { lock.unlock() }
            emissions.append(progress)
        }

        var last: HuggingFaceDownloader.RepositoryProgress? {
            lock.lock()
            defer { lock.unlock() }
            return emissions.last
        }
    }

    private func makeDummyTask(session: URLSession) -> URLSessionDownloadTask {
        session.downloadTask(with: URL(string: "https://chunk-tests.invalid/blob")!)
    }

    func testMultipleTasksPerFileAggregateAndReconcileAtExpectedSize() async throws {
        let sink = ProgressSink()
        let registry = HuggingFaceDownloader.DownloadStateRegistry(
            repositoryProgressHandler: HuggingFaceDownloader.RepositoryProgressHandlerBox { sink.append($0) }
        )
        let session = URLSession(configuration: .ephemeral)
        defer { session.invalidateAndCancel() }
        await registry.beginRepositoryDownload(totalBytes: 1_000, totalFiles: 1)

        // Two chunk tasks of one file, in distinct task-key namespaces (as the
        // per-worker session strategy produces).
        let keys = [7, 1_000_000_007]
        var completions: [Task<Void, Never>] = []
        for (index, key) in keys.enumerated() {
            let dummy = makeDummyTask(session: session)
            dummy.taskDescription = chunkIdentity(
                start: index == 0 ? 0 : 500,
                end: index == 0 ? 499 : 999
            ).encodedTaskDescription
            let completion = Task {
                _ = try? await withCheckedThrowingContinuation { (continuation: CheckedContinuation<HuggingFaceDownloader.DownloadedTemporaryFile, Error>) in
                    Task {
                        _ = await registry.register(
                            taskKey: key,
                            task: dummy,
                            destination: URL(fileURLWithPath: "/tmp/chunk-\(key)"),
                            continuation: continuation,
                            resumeDataURL: nil,
                            fileIndex: 0
                        )
                    }
                }
            }
            completions.append(completion)
        }
        // Let both registrations land, and space the reports past the registry's 0.25 s
        // publication throttle so each asserted emission actually publishes.
        try await Task.sleep(for: .milliseconds(300))

        await registry.reportProgress(taskID: keys[0], totalBytesWritten: 300)
        var progress = try XCTUnwrap(sink.last)
        XCTAssertEqual(progress.downloadedBytes, 300)

        try await Task.sleep(for: .milliseconds(300))
        await registry.reportProgress(taskID: keys[1], totalBytesWritten: 450)
        progress = try XCTUnwrap(sink.last)
        XCTAssertEqual(progress.downloadedBytes, 750, "task bytes must sum across a file's chunk tasks")

        // A retried chunk's monotonic guard: a lower report never regresses the counter.
        try await Task.sleep(for: .milliseconds(300))
        await registry.reportProgress(taskID: keys[1], totalBytesWritten: 200)
        progress = try XCTUnwrap(sink.last)
        XCTAssertEqual(progress.downloadedBytes, 750)

        await registry.reportFileCompleted(fileIndex: 0, expectedSize: 1_000)
        progress = try XCTUnwrap(sink.last)
        XCTAssertEqual(progress.downloadedBytes, 1_000, "completion reconciles at the exact expected size")
        XCTAssertEqual(progress.completedFiles, 1)

        for key in keys {
            await registry.resumeFailure(taskID: key, error: HuggingFaceDownloader.DownloadError.cancelled)
        }
        for completion in completions { await completion.value }
    }

    func testReplacementTaskForSameRangeCannotDoubleCountLogicalBytes() async throws {
        let sink = ProgressSink()
        let registry = HuggingFaceDownloader.DownloadStateRegistry(
            repositoryProgressHandler: HuggingFaceDownloader.RepositoryProgressHandlerBox { sink.append($0) }
        )
        let session = URLSession(configuration: .ephemeral)
        defer { session.invalidateAndCancel() }
        await registry.beginRepositoryDownload(totalBytes: 1_000, totalFiles: 1)
        let identity = chunkIdentity(start: 0, end: 499)

        func register(taskID: Int) async -> Task<Void, Never> {
            let task = makeDummyTask(session: session)
            task.taskDescription = identity.encodedTaskDescription
            let registered = XCTestExpectation(description: "logical replacement task \(taskID) registered")
            let completion = Task {
                _ = try? await withCheckedThrowingContinuation {
                    (continuation: CheckedContinuation<HuggingFaceDownloader.DownloadedTemporaryFile, Error>) in
                    Task {
                        _ = await registry.register(
                            taskKey: taskID,
                            task: task,
                            destination: URL(string: "https://chunk-tests.invalid/blob")!,
                            continuation: continuation,
                            resumeDataURL: nil,
                            fileIndex: 0
                        )
                        registered.fulfill()
                    }
                }
            }
            await fulfillment(of: [registered], timeout: 1)
            return completion
        }

        let firstCompletion = await register(taskID: 71)
        // The registry intentionally coalesces UI progress publications to 4 Hz. Wait
        // past that production throttle before each assertion so this test observes a
        // newly published snapshot rather than the initial zero-byte snapshot.
        try await Task.sleep(for: .milliseconds(300))
        await registry.reportProgress(taskID: 71, totalBytesWritten: 300)
        XCTAssertEqual(try XCTUnwrap(sink.last).downloadedBytes, 300)
        await registry.resumeFailure(taskID: 71, error: HuggingFaceDownloader.DownloadError.cancelled)
        await firstCompletion.value

        let replacementCompletion = await register(taskID: 72)
        try await Task.sleep(for: .milliseconds(300))
        await registry.reportProgress(taskID: 72, totalBytesWritten: 100)
        XCTAssertEqual(
            try XCTUnwrap(sink.last).downloadedBytes,
            300,
            "replacement callbacks below the durable logical slot must not add duplicate bytes"
        )
        try await Task.sleep(for: .milliseconds(300))
        await registry.reportProgress(taskID: 72, totalBytesWritten: 400)
        XCTAssertEqual(try XCTUnwrap(sink.last).downloadedBytes, 400)

        await registry.resumeFailure(taskID: 72, error: HuggingFaceDownloader.DownloadError.cancelled)
        await replacementCompletion.value
    }

    func testSkippedFilesAndResumedPartialsNeverInflateMeasuredSpeed() async throws {
        let sink = ProgressSink()
        let registry = HuggingFaceDownloader.DownloadStateRegistry(
            repositoryProgressHandler: HuggingFaceDownloader.RepositoryProgressHandlerBox { sink.append($0) }
        )
        await registry.beginRepositoryDownload(totalBytes: 2_000, totalFiles: 3)

        // Cross the 0.5 s speed-sample window, then complete a file that was already
        // valid on disk: its 1,000 bytes must not register as network throughput.
        try await Task.sleep(for: .milliseconds(700))
        await registry.reportFileCompleted(fileIndex: 0, expectedSize: 1_000, wasTransferred: false)
        var progress = try XCTUnwrap(sink.last)
        XCTAssertNil(progress.bytesPerSecond, "a skipped file must not produce a speed sample")

        // A genuinely transferred completion afterward measures only its own bytes:
        // 500 bytes over >=0.7 s is under 750 B/s, while a leaked skip baseline would
        // fold the earlier 1,000 bytes in and more than triple that.
        try await Task.sleep(for: .milliseconds(700))
        await registry.reportFileCompleted(fileIndex: 1, expectedSize: 500, wasTransferred: true)
        progress = try XCTUnwrap(sink.last)
        let measured = try XCTUnwrap(progress.bytesPerSecond)
        XCTAssertGreaterThan(measured, 0)
        XCTAssertLessThan(measured, 750, "skipped bytes leaked into the speed sample")
    }

    func testCleanRetryPublishesLowerExactDurableTotal() async throws {
        let sink = ProgressSink()
        let registry = HuggingFaceDownloader.DownloadStateRegistry(
            repositoryProgressHandler: HuggingFaceDownloader.RepositoryProgressHandlerBox {
                sink.append($0)
            }
        )
        await registry.beginRepositoryDownload(totalBytes: 100, totalFiles: 1)
        try await Task.sleep(for: .milliseconds(300))
        await registry.reportPreexistingFileBytes(fileIndex: 0, bytes: 80)
        XCTAssertEqual(try XCTUnwrap(sink.last).downloadedBytes, 80)

        await registry.resetFileProgress(fileIndex: 0, publishReset: true)

        let reset = try XCTUnwrap(sink.last)
        let accounting = await registry.repositoryTransferAccounting()
        XCTAssertEqual(reset.downloadedBytes, 0)
        XCTAssertNil(reset.bytesPerSecond)
        XCTAssertEqual(
            accounting.reusedVerifiedBytes,
            0,
            "a clean retry must remove the discarded partial from exact reuse accounting"
        )
    }

    func testTransferAccountingIncludesSharedSkippedAndRecoveredBytesExactly() async throws {
        let registry = HuggingFaceDownloader.DownloadStateRegistry(
            repositoryProgressHandler: nil
        )
        await registry.beginRepositoryDownload(
            totalBytes: 1_000,
            totalFiles: 4,
            preverifiedBytes: 300,
            preverifiedFiles: 1
        )

        await registry.reportFileCompleted(
            fileIndex: 0,
            expectedSize: 200,
            wasTransferred: false
        )
        await registry.reportPreexistingFileBytes(fileIndex: 1, bytes: 80)
        await registry.reportPreexistingFileBytes(fileIndex: 1, bytes: 120)
        await registry.reportFileCompleted(fileIndex: 1, expectedSize: 400)
        await registry.reportFileCompleted(fileIndex: 2, expectedSize: 100)

        let accounting = await registry.repositoryTransferAccounting()
        XCTAssertEqual(
            accounting.reusedVerifiedBytes,
            620,
            "shared files, skipped staged files, and only the largest durable recovered range count"
        )
    }

    // MARK: - Out-of-order chunk assembly

    func testChunkAssemblyWritesOutOfOrderChunksIntoOnePartial() async throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("chunk-assembly-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }

        let partial = root.appendingPathComponent("partial.bin")
        let payload = Data((0..<64).map { UInt8($0) })
        let chunks: [(offset: Int64, bytes: Data)] = [
            (32, payload[32..<64].withUnsafeBytes { Data($0) }),
            (0, payload[0..<16].withUnsafeBytes { Data($0) }),
            (16, payload[16..<32].withUnsafeBytes { Data($0) }),
        ]

        let assembly = HuggingFaceDownloader.ChunkAssemblyCoordinator(partialURL: partial)
        try await assembly.open()
        for (index, chunk) in chunks.enumerated() {
            let temp = root.appendingPathComponent("chunk-\(index).tmp")
            try chunk.bytes.write(to: temp)
            try await assembly.writeChunk(tempURL: temp, offset: chunk.offset)
        }
        await assembly.close()

        XCTAssertEqual(try Data(contentsOf: partial), payload)
    }

    // MARK: - Range-qualified task identity (schema v2, iOS background chunking)

    private func chunkIdentity(
        path: String = "weights/model.safetensors",
        size: Int64 = 1_000,
        start: Int64? = nil,
        end: Int64? = nil
    ) -> ModelDownloadTaskIdentity {
        ModelDownloadTaskIdentity(
            logicalRequestID: "request",
            modelID: "model",
            artifactVersion: "v1",
            relativePath: path,
            expectedSize: size,
            expectedSHA256: String(repeating: "a", count: 64),
            rangeStart: start,
            rangeEnd: end
        )
    }

    func testRangeQualifiedIdentityRoundTripsThroughTaskDescription() throws {
        let identity = chunkIdentity(start: 128, end: 255)
        XCTAssertTrue(identity.isValidProductionIdentity)
        XCTAssertEqual(identity.reconciliationKey, "/range/128-255/weights/model.safetensors")

        let decoded = ModelDownloadTaskIdentity.decode(
            taskDescription: try XCTUnwrap(identity.encodedTaskDescription)
        )
        XCTAssertEqual(decoded, identity)
        XCTAssertEqual(decoded?.rangeStart, 128)
        XCTAssertEqual(decoded?.rangeEnd, 255)

        // Whole-file identities keep their v1-shaped key: the bare relative path.
        let wholeFile = chunkIdentity()
        XCTAssertEqual(wholeFile.reconciliationKey, wholeFile.relativePath)
    }

    func testChunkIdentityRejectsIncoherentRanges() {
        // Half-specified, inverted, negative, and out-of-bounds ranges all fail closed.
        XCTAssertFalse(chunkIdentity(start: 0, end: nil).isValidProductionIdentity)
        XCTAssertFalse(chunkIdentity(start: nil, end: 10).isValidProductionIdentity)
        XCTAssertFalse(chunkIdentity(start: 20, end: 10).isValidProductionIdentity)
        XCTAssertFalse(chunkIdentity(start: -1, end: 10).isValidProductionIdentity)
        XCTAssertFalse(chunkIdentity(size: 100, start: 0, end: 100).isValidProductionIdentity)
        XCTAssertNil(chunkIdentity(start: 20, end: 10).encodedTaskDescription)
        // The last in-bounds byte is valid.
        XCTAssertTrue(chunkIdentity(size: 100, start: 0, end: 99).isValidProductionIdentity)
    }

    func testSchemaV1TaskDescriptionsFailClosed() throws {
        // A task minted by a pre-chunking build carries schemaVersion 1; it must be
        // rejected so reconciliation cancels it and the request restarts cleanly.
        let v1JSON: [String: Any] = [
            "schemaVersion": 1,
            "logicalRequestID": "request",
            "modelID": "model",
            "artifactVersion": "v1",
            "relativePath": "weights/model.safetensors",
            "expectedSize": 1_000,
            "expectedSHA256": String(repeating: "a", count: 64),
        ]
        let data = try JSONSerialization.data(withJSONObject: v1JSON)
        XCTAssertNil(ModelDownloadTaskIdentity.decode(taskDescription: data.base64EncodedString()))
    }

    func testReconcilerAdoptsOneTaskPerChunkSlot() {
        // One file expected as a whole-file slot plus three chunk slots. Every slot
        // adopts its own live task; a duplicate for an occupied slot is cancelled.
        // Before the v2 keying, all four identities shared one relativePath key and
        // building the plan trapped on duplicate dictionary keys.
        let wholeFile = chunkIdentity()
        let chunks = [
            chunkIdentity(start: 0, end: 399),
            chunkIdentity(start: 400, end: 799),
            chunkIdentity(start: 800, end: 999),
        ]
        let plan = ModelDownloadTaskReconciler.plan(
            expected: [wholeFile] + chunks,
            existing: [
                ModelDownloadExistingTask(taskID: 11, identity: chunks[0]),
                ModelDownloadExistingTask(taskID: 12, identity: chunks[1]),
                ModelDownloadExistingTask(taskID: 13, identity: chunks[1]),
                ModelDownloadExistingTask(taskID: 14, identity: chunks[2]),
            ]
        )

        XCTAssertEqual(plan.adoptedTaskByReconciliationKey, [
            chunks[0].reconciliationKey: 11,
            chunks[1].reconciliationKey: 12,
            chunks[2].reconciliationKey: 14,
        ])
        XCTAssertEqual(plan.cancelledTaskIDs, [13])
        XCTAssertEqual(plan.missingReconciliationKeys, [wholeFile.relativePath])
    }

    // MARK: - Completed-range sidecar (crash-resumable sparse partial)

    func testMergedChunkRangesCoalesceSortAndDropInvalid() {
        let merged = HuggingFaceDownloader.mergedChunkRanges([
            ChunkRange(start: 40, end: 59),
            ChunkRange(start: 0, end: 19),
            ChunkRange(start: 20, end: 39),
            ChunkRange(start: 90, end: 80),
            ChunkRange(start: 100, end: 119),
        ])
        XCTAssertEqual(merged, [
            ChunkRange(start: 0, end: 59),
            ChunkRange(start: 100, end: 119),
        ])
    }

    func testChunkRangeCoverageIsFullContainmentOnly() {
        let completed = [ChunkRange(start: 0, end: 99)]
        XCTAssertTrue(HuggingFaceDownloader.chunkRangeCovered(ChunkRange(start: 0, end: 99), by: completed))
        XCTAssertTrue(HuggingFaceDownloader.chunkRangeCovered(ChunkRange(start: 10, end: 50), by: completed))
        XCTAssertFalse(
            HuggingFaceDownloader.chunkRangeCovered(ChunkRange(start: 50, end: 149), by: completed),
            "a partially covered range must be re-fetched whole"
        )
    }

    func testChunkSidecarRoundTripsAndFailsClosed() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("chunk-sidecar-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let sidecar = root.appendingPathComponent("file.partial.ranges")

        let ranges = [ChunkRange(start: 0, end: 99), ChunkRange(start: 200, end: 299)]
        HuggingFaceDownloader.writeChunkSidecar(at: sidecar, expectedSize: 1_000, ranges: ranges)
        XCTAssertEqual(HuggingFaceDownloader.loadChunkSidecar(at: sidecar, expectedSize: 1_000), ranges)

        // A size mismatch means the record describes a different artifact revision.
        XCTAssertNil(HuggingFaceDownloader.loadChunkSidecar(at: sidecar, expectedSize: 999))

        // An out-of-bounds range or torn JSON must never validate.
        HuggingFaceDownloader.writeChunkSidecar(
            at: sidecar,
            expectedSize: 100,
            ranges: [ChunkRange(start: 0, end: 100)]
        )
        XCTAssertNil(HuggingFaceDownloader.loadChunkSidecar(at: sidecar, expectedSize: 100))
        try Data("{".utf8).write(to: sidecar)
        XCTAssertNil(HuggingFaceDownloader.loadChunkSidecar(at: sidecar, expectedSize: 1_000))
        XCTAssertNil(
            HuggingFaceDownloader.loadChunkSidecar(
                at: root.appendingPathComponent("absent.ranges"),
                expectedSize: 1_000
            )
        )
    }

    func testAssemblyRecordsCompletedRangesDurably() async throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("chunk-durable-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let partial = root.appendingPathComponent("file.partial")
        let sidecar = HuggingFaceDownloader.chunkSidecarURL(forPartial: partial)

        let assembly = HuggingFaceDownloader.ChunkAssemblyCoordinator(
            partialURL: partial,
            sidecarURL: sidecar,
            expectedSize: 64,
            initialCompletedRanges: [ChunkRange(start: 0, end: 15)]
        )
        try await assembly.open()
        let temp = root.appendingPathComponent("chunk.tmp")
        try Data(repeating: 7, count: 16).write(to: temp)
        try await assembly.writeChunk(tempURL: temp, offset: 16)
        await assembly.recordCompleted(range: ChunkRange(start: 16, end: 31))
        await assembly.close()

        // The recovered record merges the pre-existing and newly recorded ranges, so a
        // relaunch re-fetches only the genuinely missing bytes.
        XCTAssertEqual(
            HuggingFaceDownloader.loadChunkSidecar(at: sidecar, expectedSize: 64),
            [ChunkRange(start: 0, end: 31)]
        )
    }

    // MARK: - Registry: adopted-task teardown and identity-exact claims

    func testCancellationDrainsAdoptedButUnconsumedTasks() async throws {
        let registry = HuggingFaceDownloader.DownloadStateRegistry(repositoryProgressHandler: nil)
        let session = URLSession(configuration: .ephemeral)
        defer { session.invalidateAndCancel() }
        await registry.beginRepositoryDownload(totalBytes: 1_000, totalFiles: 1)

        // A relaunch-adopted task that no range slot has consumed yet is a live
        // daemon transfer with no registered continuation; user cancel must stop it.
        let adopted = makeDummyTask(session: session)
        let accepted = await registry.adopt(task: adopted, identity: chunkIdentity(start: 0, end: 499))
        XCTAssertTrue(accepted)
        XCTAssertEqual(adopted.state, .suspended)

        await registry.requestCancellation()
        let left: Bool = await {
            for _ in 0..<50 {
                if adopted.state != .suspended { return true }
                try? await Task.sleep(for: .milliseconds(20))
            }
            return adopted.state != .suspended
        }()
        XCTAssertTrue(left, "cancel must tear down adopted-but-unconsumed tasks")
        // And the slot is gone: nothing can consume the cancelled task later.
        let taken = await registry.takeAdoptedTask(forKey: chunkIdentity(start: 0, end: 499).reconciliationKey)
        XCTAssertNil(taken)
    }

    func testParkedCompletionClaimRequiresExactIdentity() async throws {
        let registry = HuggingFaceDownloader.DownloadStateRegistry(repositoryProgressHandler: nil)
        let session = URLSession(configuration: .ephemeral)
        defer { session.invalidateAndCancel() }
        await registry.beginRepositoryDownload(totalBytes: 1_000, totalFiles: 1)

        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("chunk-claim-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }

        // Park a completion under artifact generation v1.
        let stale = chunkIdentity(start: 0, end: 499)
        let temp = root.appendingPathComponent("stale-bytes")
        try Data("stale".utf8).write(to: temp)
        await registry.stageSuccess(
            taskID: 41,
            identity: stale,
            temporaryFile: HuggingFaceDownloader.DownloadedTemporaryFile(
                url: temp, statusCode: 206, retryAfterSeconds: nil, contentRange: nil
            )
        )
        await registry.completeStagedSuccess(taskID: 41)

        // A v2-generation task shares the reconciliation slot but not the identity:
        // it must NOT be handed the stale bytes; the stale parking is discarded and
        // the fresh registration proceeds.
        let fresh = ModelDownloadTaskIdentity(
            logicalRequestID: "request",
            modelID: "model",
            artifactVersion: "v2",
            relativePath: stale.relativePath,
            expectedSize: stale.expectedSize,
            expectedSHA256: String(repeating: "a", count: 64),
            rangeStart: 0,
            rangeEnd: 499
        )
        XCTAssertEqual(fresh.reconciliationKey, stale.reconciliationKey)

        let dummy = makeDummyTask(session: session)
        dummy.taskDescription = fresh.encodedTaskDescription
        let registered: Bool = await withCheckedContinuation { outer in
            Task {
                _ = try? await withCheckedThrowingContinuation { (continuation: CheckedContinuation<HuggingFaceDownloader.DownloadedTemporaryFile, Error>) in
                    Task {
                        let shouldResume = await registry.register(
                            taskKey: 42,
                            task: dummy,
                            destination: URL(string: "https://chunk-tests.invalid/blob")!,
                            continuation: continuation,
                            resumeDataURL: nil,
                            fileIndex: 0
                        )
                        outer.resume(returning: shouldResume)
                        if shouldResume {
                            await registry.resumeFailure(
                                taskID: 42,
                                error: HuggingFaceDownloader.DownloadError.cancelled
                            )
                        }
                    }
                }
            }
        }
        XCTAssertTrue(registered, "a mismatched parked identity must not satisfy the claim")
        XCTAssertFalse(
            FileManager.default.fileExists(atPath: temp.path),
            "the unclaimable stale parking must be discarded, not leaked"
        )
    }

    // MARK: - Registry: parked chunk completions claim by range slot

    func testParkedChunkCompletionsAreClaimedPerRangeSlot() async throws {
        let registry = HuggingFaceDownloader.DownloadStateRegistry(repositoryProgressHandler: nil)
        let session = URLSession(configuration: .ephemeral)
        defer { session.invalidateAndCancel() }
        await registry.beginRepositoryDownload(totalBytes: 1_000, totalFiles: 1)

        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("chunk-park-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }

        // Two chunk completions of one file land while nothing is registered (the
        // background daemon finished them while the app was dead). Both must park
        // side by side — the old per-file keying deleted the first as superseded.
        let first = chunkIdentity(start: 0, end: 499)
        let second = chunkIdentity(start: 500, end: 999)
        for (taskID, identity) in [(21, first), (22, second)] {
            let temp = root.appendingPathComponent("parked-\(taskID)")
            try Data("chunk-\(taskID)".utf8).write(to: temp)
            await registry.stageSuccess(
                taskID: taskID,
                identity: identity,
                temporaryFile: HuggingFaceDownloader.DownloadedTemporaryFile(
                    url: temp,
                    statusCode: 206,
                    retryAfterSeconds: nil,
                    contentRange: nil
                )
            )
            await registry.completeStagedSuccess(taskID: taskID)
        }

        // A fresh task per range slot claims exactly its own parked completion.
        for (key, identity) in [(31, first), (32, second)] {
            let dummy = makeDummyTask(session: session)
            dummy.taskDescription = identity.encodedTaskDescription
            let claimed: HuggingFaceDownloader.DownloadedTemporaryFile =
                try await withCheckedThrowingContinuation { continuation in
                    Task {
                        let shouldResume = await registry.register(
                            taskKey: key,
                            task: dummy,
                            destination: URL(string: "https://chunk-tests.invalid/blob")!,
                            continuation: continuation,
                            resumeDataURL: nil,
                            fileIndex: 0
                        )
                        XCTAssertFalse(shouldResume, "a claimed completion must not start a transfer")
                    }
                }
            let expectedStart = try XCTUnwrap(identity.rangeStart)
            XCTAssertEqual(
                try String(decoding: Data(contentsOf: claimed.url), as: UTF8.self),
                "chunk-\(expectedStart == 0 ? 21 : 22)"
            )
        }
    }
}
