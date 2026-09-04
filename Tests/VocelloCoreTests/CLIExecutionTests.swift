import Foundation
import Synchronization
import QwenVoiceCore
import XCTest

@MainActor
final class CLIExecutionTests: XCTestCase {
    private enum Failure: Error { case injected }

    /// Invoked only by the native subprocess test below; never a product route.
    func testNativeSignalWorker() async throws {
        guard let path = ProcessInfo.processInfo.environment["VOCELLO_TEST_SIGNAL_ROOT"] else { return }
        let root = URL(fileURLWithPath: path)
        let code = await CLIProcessSupervisor.run {
            do {
                try Data("ready".utf8).write(to: root.appendingPathComponent("ready"), options: .atomic)
                try await Task.sleep(for: .seconds(30))
                return 1
            } catch is CancellationError {
                do { try Data("owned cleanup".utf8).write(to: root.appendingPathComponent("cleaned"), options: .atomic) }
                catch { return 1 }
                return 0
            } catch { return 1 }
        }
        try Data(String(code).utf8).write(to: root.appendingPathComponent("status"), options: .atomic)
    }

    func testRealSignalsReachNativeSupervisorAndAwaitCleanup() async throws {
        for number in [SIGINT, SIGTERM] {
            let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
            try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
            defer { try? FileManager.default.removeItem(at: root) }
            let child = Process()
            child.executableURL = URL(fileURLWithPath: "/usr/bin/xcrun")
            child.arguments = ["xctest", "-XCTest", "VocelloCoreTests.CLIExecutionTests/testNativeSignalWorker", Bundle(for: Self.self).bundleURL.path]
            var environment = ProcessInfo.processInfo.environment
            environment["VOCELLO_TEST_SIGNAL_ROOT"] = root.path
            child.environment = environment
            child.standardOutput = FileHandle.nullDevice
            child.standardError = FileHandle.nullDevice
            try child.run()
            defer { if child.isRunning { kill(child.processIdentifier, SIGKILL); child.waitUntilExit() } }
            let deadline = ContinuousClock.now + .seconds(15)
            while !FileManager.default.fileExists(atPath: root.appendingPathComponent("ready").path),
                  child.isRunning, ContinuousClock.now < deadline {
                try await Task.sleep(for: .milliseconds(20))
            }
            XCTAssertTrue(FileManager.default.fileExists(atPath: root.appendingPathComponent("ready").path))
            XCTAssertEqual(kill(child.processIdentifier, number), 0)
            while child.isRunning, ContinuousClock.now < deadline {
                try await Task.sleep(for: .milliseconds(20))
            }
            XCTAssertFalse(child.isRunning, "Native signal cleanup exceeded its test bound")
            guard !child.isRunning else { continue }
            XCTAssertEqual(child.terminationStatus, 0)
            XCTAssertEqual(try String(contentsOf: root.appendingPathComponent("status"), encoding: .utf8), String(128 + number))
            XCTAssertEqual(try String(contentsOf: root.appendingPathComponent("cleaned"), encoding: .utf8), "owned cleanup")
        }
    }

    func testSuccessfulBatchPreservesEveryResultInRequestOrder() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let requests = (0..<3).map { request($0, root: root) }
        let outcome = await CLIBatchExecution.run(requests) { request in
            try Data([1, 2, 3]).write(to: URL(fileURLWithPath: request.outputPath))
            return self.result(request)
        }
        XCTAssertTrue(outcome.passed)
        XCTAssertFalse(outcome.cancelled)
        XCTAssertEqual(outcome.results.map(\.audioPath), requests.map(\.outputPath))
        XCTAssertEqual(outcome.rows.map(\.status), [.completed, .completed, .completed])
        XCTAssertEqual(outcome.rows.map(\.generationID), requests.map(\.generationID))
    }

    func testBatchFailureRetainsCompletedRowsAndNeverAttemptsLaterRows() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let requests = (0..<4).map { request($0, root: root) }
        var attempted: [UInt64?] = []
        let result = await CLIBatchExecution.run(requests) { request in
            attempted.append(request.seed)
            if request.seed == 2 { throw Failure.injected }
            try Data([1, 2, 3]).write(to: URL(fileURLWithPath: request.outputPath))
            return self.result(request)
        }
        XCTAssertEqual(attempted, [0, 1, 2])
        XCTAssertEqual(result.rows.map(\.status), [.completed, .completed, .failed, .notAttempted])
        XCTAssertEqual(result.rows.map(\.generationID), requests.map(\.generationID))
        XCTAssertEqual(result.results.count, 2)
        XCTAssertFalse(result.passed)
        XCTAssertEqual(try Data(contentsOf: URL(fileURLWithPath: requests[0].outputPath)), Data([1, 2, 3]))
        let encoded = try JSONSerialization.jsonObject(with: JSONEncoder().encode(result.rows)) as? [[String: Any]]
        XCTAssertEqual(encoded?[3]["status"] as? String, "not_attempted")
        XCTAssertNil(encoded?[2]["audioPath"])
    }

    func testBatchMissingOutputFailsClosedAndCancellationIsDistinct() async {
        let requests = (0..<2).map { request($0, root: URL(fileURLWithPath: "/missing/\(UUID())")) }
        let missing = await CLIBatchExecution.run(requests) { self.result($0) }
        XCTAssertEqual(missing.rows.map(\.status), [.failed, .notAttempted])
        XCTAssertEqual(missing.rows[0].errorCode, "published_output_missing")
        let cancelled = await CLIBatchExecution.run(requests) { _ in throw CancellationError() }
        XCTAssertEqual(cancelled.rows.map(\.status), [.cancelled, .notAttempted])
        XCTAssertTrue(cancelled.cancelled)
    }

    func testSignalCancellationWaitsForOwnedCleanupAndPreservesSignalStatus() async {
        for number in [SIGINT, SIGTERM] {
            let forced = Mutex<[Int32]>([])
            let supervisor = CLIProcessSupervisor(forceExit: { code in forced.withLock { $0.append(code) } })
            let entered = expectation(description: "command entered")
            var release: CheckedContinuation<Void, Never>?
            var cleaned = false
            let command = Task<Int32, Never> {
                await withCheckedContinuation { release = $0; entered.fulfill() }
                XCTAssertTrue(Task.isCancelled)
                cleaned = true
                return 1
            }
            supervisor.attach(command)
            await fulfillment(of: [entered], timeout: 2)
            supervisor.receive(number)
            XCTAssertFalse(cleaned)
            XCTAssertTrue(forced.withLock { $0.isEmpty })
            release?.resume()
            let result = await command.value
            XCTAssertTrue(cleaned)
            XCTAssertEqual(supervisor.finish(code: result), 128 + number)
            supervisor.enforceDeadline()
            XCTAssertTrue(forced.withLock { $0.isEmpty })
        }
    }

    func testSecondSignalAndDeadlineAreExplicitForcedExits() {
        let forced = Mutex<[Int32]>([])
        let supervisor = CLIProcessSupervisor(forceExit: { code in forced.withLock { $0.append(code) } })
        supervisor.receive(SIGTERM)
        supervisor.receive(SIGINT)
        supervisor.enforceDeadline()
        XCTAssertEqual(forced.withLock { $0 }, [130, 143])
        XCTAssertEqual(supervisor.finish(code: 0), 143)
        supervisor.receive(SIGINT)
        XCTAssertEqual(forced.withLock { $0.count }, 2)
    }

    func testSignalBeforeAttachmentCancelsTheLateCommand() async {
        let forced = Mutex<[Int32]>([])
        let supervisor = CLIProcessSupervisor(forceExit: { code in forced.withLock { $0.append(code) } })
        supervisor.receive(SIGINT)
        let command = Task<Int32, Never> { Task.isCancelled ? 1 : 0 }
        supervisor.attach(command)
        let result = await command.value
        XCTAssertEqual(result, 1)
        XCTAssertEqual(supervisor.finish(code: result), 130)
        XCTAssertTrue(forced.withLock { $0.isEmpty })
    }

    private func request(_ index: Int, root: URL) -> GenerationRequest {
        GenerationRequest(mode: .custom, modelID: "fixture", text: "test", outputPath: root.appendingPathComponent("\(index).wav").path,
            shouldStream: false, payload: .custom(speakerID: "aiden", deliveryStyle: nil), generationID: UUID(), seed: UInt64(index))
    }
    private func result(_ request: GenerationRequest) -> GenerationResult {
        GenerationResult(audioPath: request.outputPath, durationSeconds: 1, streamSessionDirectory: nil, usedStreaming: false)
    }
}
