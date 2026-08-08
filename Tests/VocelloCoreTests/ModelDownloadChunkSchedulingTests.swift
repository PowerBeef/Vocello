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
        for key in keys {
            let dummy = makeDummyTask(session: session)
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
}
