import Foundation
import Synchronization
import XCTest
@testable import VocelloCLICore

/// RF-25: the NDJSON writer never blocks an emitter, coalesces running
/// records, keeps every terminal one, numbers what it writes and stops on a
/// closed stdout.
final class CLIEventStreamTests: XCTestCase {
    /// A stdout whose first write waits until released, so later records queue.
    private final class GatedSink: Sendable {
        let lines = Mutex<[Data]>([])
        let gate = DispatchSemaphore(value: 0)
        let firstWriteStarted = DispatchSemaphore(value: 0)
        let accept: Bool

        init(accept: Bool = true) { self.accept = accept }

        var sink: @Sendable (Data) -> Bool {
            { [self] data in
                let first = lines.withLock { lines -> Bool in
                    lines.append(data)
                    return lines.count == 1
                }
                if first {
                    firstWriteStarted.signal()
                    gate.wait()
                }
                return accept
            }
        }

        func records() throws -> [[String: Any]] {
            try lines.withLock { $0 }.map {
                try XCTUnwrap(JSONSerialization.jsonObject(with: $0) as? [String: Any])
            }
        }
    }

    private func envelope() -> CLIEnvelope {
        CLIEnvelope(
            ok: true, command: "generate", requestID: "fixture", result: nil, error: nil, warnings: [],
            meta: CLIEnvelopeMeta(vocelloVersion: "3.0.0", build: "24", contractRevision: 1, durationMs: 1, replayed: false)
        )
    }

    /// A running record coalesces only into the newest queued one, so a `progress`
    /// count never runs ahead of the take records queued after it (review 13).
    func testARunningRecordNeverOvertakesTheRecordsAfterIt() throws {
        let output = GatedSink()
        let stream = CLIEventStream(requestID: "fixture", sink: output.sink)
        stream.emit(.started, data: .object(["command": "batch"]))
        XCTAssertEqual(output.firstWriteStarted.wait(timeout: .now() + 5), .success)
        stream.emit(.progress, data: .object(["finished": .integer(1)]))
        stream.emit(.generationCompleted, generationID: "take-2")
        stream.emit(.progress, data: .object(["finished": .integer(2)]))
        output.gate.signal()
        stream.finish(result: envelope())
        let records = try output.records()
        XCTAssertEqual(
            records.compactMap { $0["type"] as? String },
            ["started", "progress", "generation_completed", "progress", "result"]
        )
        XCTAssertEqual((records[1]["data"] as? [String: Any])?["finished"] as? Int, 1)
        XCTAssertEqual((records[3]["data"] as? [String: Any])?["finished"] as? Int, 2)
    }

    func testRunningRecordsCoalesceWhileTerminalRecordsSurviveInOrder() throws {
        let output = GatedSink()
        let stream = CLIEventStream(requestID: "fixture", sink: output.sink)
        let take = "take-1"
        stream.emit(.started, data: .object(["command": "generate"]))
        XCTAssertEqual(output.firstWriteStarted.wait(timeout: .now() + 5), .success)
        // The writer is blocked on the first line: everything below queues.
        for chunk in 1 ... 50 {
            stream.emit(.chunk, generationID: take, data: .object(["chunks": .integer(chunk)]))
        }
        stream.emit(.outputPublished, generationID: take, data: .object(["audioPath": "/x.wav"]))
        stream.emit(.generationCompleted, generationID: take)
        output.gate.signal()
        stream.finish(result: envelope())

        let records = try output.records()
        XCTAssertEqual(
            records.compactMap { $0["type"] as? String },
            ["started", "chunk", "output_published", "generation_completed", "result"]
        )
        XCTAssertEqual((records[1]["data"] as? [String: Any])?["chunks"] as? Int, 50, "only the newest chunk count")
        XCTAssertEqual(records.compactMap { $0["seq"] as? Int }, [0, 1, 2, 3, 4], "from 0, no gaps")
        let times = records.compactMap { ($0["t"] as? NSNumber)?.doubleValue }
        XCTAssertEqual(times, times.sorted(), "t never decreases, a coalesced record included")
        XCTAssertTrue(records.allSatisfy { $0["requestID"] as? String == "fixture" && $0["schemaVersion"] as? Int == 1 })
        XCTAssertEqual(records[1]["generationID"] as? String, take)
        XCTAssertNil(records[0]["generationID"], "absent, not null")
        XCTAssertEqual((records[4]["data"] as? [String: Any])?["command"] as? String, "generate")
        stream.emit(.log, data: .object(["late": true]))
        XCTAssertEqual(output.lines.withLock { $0.count }, 5, "nothing is written after the result")
    }

    func testFinishWaitsForABlockedWriterAndKeepsLargeSeedsExact() throws {
        let output = GatedSink()
        let stream = CLIEventStream(requestID: "fixture", sink: output.sink)
        stream.emit(.started)
        XCTAssertEqual(output.firstWriteStarted.wait(timeout: .now() + 5), .success)
        struct Seeded: Encodable, Sendable { let seed: UInt64 }
        let finished = DispatchSemaphore(value: 0)
        // The envelope is not Sendable, so the finishing thread builds its own.
        Thread.detachNewThread {
            let result = CLIEnvelope(
                ok: true, command: "generate", requestID: "fixture", result: Seeded(seed: UInt64.max), error: nil,
                warnings: [],
                meta: CLIEnvelopeMeta(vocelloVersion: "3.0.0", build: "24", contractRevision: 1, durationMs: 1, replayed: false)
            )
            stream.finish(result: result)
            finished.signal()
        }
        XCTAssertEqual(finished.wait(timeout: .now() + 0.2), .timedOut, "finish waits while the writer is blocked")
        output.gate.signal()
        XCTAssertEqual(finished.wait(timeout: .now() + 5), .success)
        let last = try XCTUnwrap(output.lines.withLock { $0.last })
        XCTAssertTrue(
            String(decoding: last, as: UTF8.self).contains("\"seed\":18446744073709551615"),
            "a seed above Int.max survives the result record exactly"
        )
    }

    func testAClosedStdoutStopsTheStreamAndReportsOnce() throws {
        let output = GatedSink(accept: false)
        let reports = Mutex(0)
        let stream = CLIEventStream(
            requestID: "fixture", sink: output.sink, onBrokenOutput: { reports.withLock { $0 += 1 } }
        )
        stream.emit(.started)
        XCTAssertEqual(output.firstWriteStarted.wait(timeout: .now() + 5), .success)
        stream.emit(.progress)
        output.gate.signal()
        stream.finish(result: envelope())
        XCTAssertTrue(stream.outputBroken)
        XCTAssertEqual(reports.withLock { $0 }, 1)
        XCTAssertEqual(output.lines.withLock { $0.count }, 1, "the failed write is the last")
        stream.emit(.warning)
        XCTAssertEqual(output.lines.withLock { $0.count }, 1)
    }

    func testABoundedQueueDropsRunningRecordsFirst() throws {
        let output = GatedSink()
        let stream = CLIEventStream(requestID: "fixture", sink: output.sink)
        stream.emit(.started)
        XCTAssertEqual(output.firstWriteStarted.wait(timeout: .now() + 5), .success)
        for take in 0 ..< CLIEventStream.queueBound {
            stream.emit(.progress, generationID: "take-\(take)")
        }
        for take in 0 ..< 10 {
            stream.emit(.generationCompleted, generationID: "take-\(take)")
        }
        output.gate.signal()
        stream.finish(result: envelope())
        let types = try output.records().compactMap { $0["type"] as? String }
        XCTAssertEqual(types.filter { $0 == "generation_completed" }.count, 10, "terminal records never drop")
        XCTAssertEqual(types.last, "result")
        XCTAssertLessThanOrEqual(types.count, CLIEventStream.queueBound + 2)
    }
}
