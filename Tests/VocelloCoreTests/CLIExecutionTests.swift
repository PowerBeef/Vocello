import Foundation
import Synchronization
import QwenVoiceCore
import XCTest

@MainActor
final class CLIExecutionTests: XCTestCase {
    private enum Failure: Error { case injected }

    func testProductionBatchRequestsPassRealSingleTakeSupportPolicy() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let source = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
        let runtime = try NativeRuntimeFactory.make(
            manifestURL: source.appendingPathComponent("Sources/Resources/qwenvoice_contract.json"),
            paths: .rooted(at: root), storeVersionSeed: "batch-policy-fixture"
        )
        defer { runtime.engine.stop() }
        // No initialize, model load or synthesis: exercise the real admission policy.
        let cases: [(GenerationMode, GenerationRequest.Payload)] = [
            (.custom, .custom(speakerID: "aiden", deliveryStyle: nil)),
            (.design, .design(voiceDescription: "A clear narrator.", deliveryStyle: nil)),
            (.clone, .clone(reference: CloneReference(audioPath: root.appendingPathComponent("reference.wav").path)))
        ]
        for (mode, payload) in cases {
            let requests = CLIBatchExecution.makeRequests(
                lines: ["First clip.", "Second clip."], mode: mode, modelID: "pro_\(mode.rawValue)_speed",
                outputDirectory: root, filenamePrefix: "fixed", payload: payload,
                seed: 30_000_005, variation: .consistent, deliveryInstructionCellID: nil
            )
            XCTAssertEqual(requests.count, 2)
            XCTAssertEqual(Set(requests.compactMap(\.generationID)).count, 2)
            for (index, request) in requests.enumerated() {
                XCTAssertEqual(request.text, index == 0 ? "First clip." : "Second clip.")
                XCTAssertEqual(request.mode, mode)
                XCTAssertEqual(request.modelID, "pro_\(mode.rawValue)_speed")
                XCTAssertTrue(request.outputPath.hasSuffix("_\(String(format: "%03d", index)).wav"))
                XCTAssertEqual(request.payload, payload)
                XCTAssertEqual(request.seed, 30_000_005)
                XCTAssertEqual(request.variation, .consistent)
                XCTAssertFalse(request.shouldStream)
                XCTAssertNil(request.languageHint)
                XCTAssertNil(request.batchIndex)
                XCTAssertNil(request.batchTotal)
                guard case .supported = runtime.engine.supportDecision(for: request) else {
                    XCTFail("Production batch request must use the single-take API contract: \(mode)")
                    continue
                }
            }
        }
        for fields in [(0 as Int?, nil as Int?), (nil, 2), (0, 2)] {
            let invalid = GenerationRequest(mode: .custom, modelID: "fixture", text: "test",
                outputPath: root.appendingPathComponent("invalid.wav").path, shouldStream: false,
                batchIndex: fields.0, batchTotal: fields.1,
                payload: .custom(speakerID: "aiden", deliveryStyle: nil))
            guard case .unsupported = runtime.engine.supportDecision(for: invalid) else {
                return XCTFail("Keep the single-take engine guard intact")
            }
        }
    }

    func testBatchBuilderPreservesDeliveryIdentityAndUnpinnedDefaults() {
        let root = URL(fileURLWithPath: "/fixture/batch with spaces")
        let style = "Speak gently."
        let request = CLIBatchExecution.makeRequests(
            lines: ["Exact text."], mode: .custom, modelID: "custom",
            outputDirectory: root, filenamePrefix: "run", payload: .custom(speakerID: "ryan", deliveryStyle: style),
            seed: nil, variation: nil, deliveryInstructionCellID: "custom-fixture"
        )[0]
        XCTAssertEqual(request.deliveryInstructionCellID, "custom-fixture")
        XCTAssertEqual(request.payload.deliveryInstructionText, style)
        XCTAssertNil(request.seed)
        XCTAssertNil(request.variation)
        XCTAssertEqual(request.outputPath, root.appendingPathComponent("run_custom_000.wav").path)
        XCTAssertTrue(CLIBatchExecution.makeRequests(lines: [], mode: .custom, modelID: "custom",
            outputDirectory: root, filenamePrefix: "run", payload: request.payload,
            seed: nil, variation: nil, deliveryInstructionCellID: nil).isEmpty)
    }

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
        var progress: [[Int]] = []
        let outcome = await CLIBatchExecution.run(requests, progress: { progress.append([$0, $1]) }) { request in
            try Data([1, 2, 3]).write(to: URL(fileURLWithPath: request.outputPath))
            return self.result(request)
        }
        XCTAssertTrue(outcome.passed)
        XCTAssertFalse(outcome.cancelled)
        XCTAssertEqual(outcome.results.map(\.audioPath), requests.map(\.outputPath))
        XCTAssertEqual(outcome.rows.map(\.status), [.completed, .completed, .completed])
        XCTAssertEqual(outcome.rows.map(\.generationID), requests.map(\.generationID))
        XCTAssertEqual(progress, [[0, 3], [1, 3], [2, 3]])
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
        CLIBatchExecution.makeRequests(lines: ["test"], mode: .custom, modelID: "fixture",
            outputDirectory: root, filenamePrefix: "fixture-\(index)",
            payload: .custom(speakerID: "aiden", deliveryStyle: nil), seed: UInt64(index),
            variation: nil, deliveryInstructionCellID: nil)[0]
    }
    private func result(_ request: GenerationRequest) -> GenerationResult {
        GenerationResult(audioPath: request.outputPath, durationSeconds: 1, streamSessionDirectory: nil, usedStreaming: false)
    }
}
