import Foundation
import QwenVoiceCore
import Synchronization
import XCTest
@testable import VocelloCLICore

/// RF-25: the CLI's machine contract. Error codes and exit classes against the
/// canonical tables in `config/cli-contract/v1/`, the envelope's shape, the
/// failure classification and the presenter's one-object stdout.
final class CLIContractTests: XCTestCase {
    private static let contractDirectory = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        .appendingPathComponent("config/cli-contract/v1", isDirectory: true)

    private func table(_ name: String, key: String) throws -> [[String: Any]] {
        let data = try Data(contentsOf: Self.contractDirectory.appendingPathComponent(name))
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        return try XCTUnwrap(object[key] as? [[String: Any]], "\(name) lacks \(key)")
    }

    func testErrorCodesMatchTheCanonicalTable() throws {
        let rows = try table("error-codes.json", key: "errorCodes")
        let canonical = Dictionary(uniqueKeysWithValues: rows.map { ($0["code"] as? String ?? "", $0) })
        XCTAssertEqual(Set(canonical.keys), Set(VocelloErrorCode.allCases.map(\.rawValue)))
        for code in VocelloErrorCode.allCases {
            let row = try XCTUnwrap(canonical[code.rawValue], code.rawValue)
            XCTAssertEqual(row["category"] as? String, code.category.rawValue, code.rawValue)
            XCTAssertEqual((row["exitCode"] as? NSNumber)?.int32Value, code.exitCode, code.rawValue)
            XCTAssertEqual(row["retryable"] as? Bool, code.retryable, code.rawValue)
            XCTAssertEqual(code.retryable, code.category == .transient, "only the transient class is retryable")
        }
    }

    func testExitCodesAndEventTypesMatchTheCanonicalTables() throws {
        let exits = try table("exit-codes.json", key: "exitCodes")
        var byExit: [Int32: String] = [:]
        for row in exits {
            byExit[(row["exit"] as? NSNumber)?.int32Value ?? -1] = row["category"] as? String
        }
        XCTAssertEqual(byExit[0], "ok")
        for category in CLIErrorCategory.allCases {
            XCTAssertEqual(byExit[category.exitCode], category.rawValue, "\(category)")
        }
        XCTAssertEqual(byExit[143], CLIErrorCategory.cancelled.rawValue, "SIGTERM")
        let events = try table("event-types.json", key: "eventTypes").compactMap { $0["type"] as? String }
        XCTAssertEqual(events, CLIEventType.allCases.map(\.rawValue))
    }

    func testEnvelopeCarriesEveryKeyAndKeepsAPartialResultOnFailure() throws {
        struct Partial: Encodable, Sendable { let completedCount: Int }
        let envelope = CLIEnvelope(
            ok: false, command: "batch", requestID: "r", result: Partial(completedCount: 1),
            error: CLIErrorObject(code: .batchIncomplete, message: "stopped"),
            warnings: [CLIWarning(code: "voice_quality", message: "short clip")],
            meta: CLIEnvelopeMeta(vocelloVersion: "3.0.0", build: "24", contractRevision: 1, durationMs: 5, replayed: false)
        )
        let object = try XCTUnwrap(
            JSONSerialization.jsonObject(with: CLIJSONEncoding.encoder().encode(envelope)) as? [String: Any]
        )
        XCTAssertEqual(
            Set(object.keys), ["schemaVersion", "ok", "command", "requestID", "result", "error", "warnings", "meta"]
        )
        XCTAssertEqual((object["result"] as? [String: Any])?["completedCount"] as? Int, 1)
        let error = try XCTUnwrap(object["error"] as? [String: Any])
        XCTAssertEqual(
            Set(error.keys),
            ["code", "category", "exitCode", "message", "retryable", "retryAfterMs", "hint", "detail"]
        )
        XCTAssertTrue(error["hint"] is NSNull, "absent values are null, never missing")
        XCTAssertEqual(error["category"] as? String, "failure")

        let success = CLIEnvelope(
            ok: true, command: "version", requestID: "r", result: nil, error: nil, warnings: [],
            meta: CLIEnvelopeMeta(vocelloVersion: "3.0.0", build: "24", contractRevision: 1, durationMs: 0, replayed: false)
        )
        let encoded = String(decoding: try CLIJSONEncoding.encoder().encode(success), as: UTF8.self)
        XCTAssertTrue(encoded.contains("\"error\":null"))
        XCTAssertTrue(encoded.contains("\"result\":null"))
    }

    func testFailuresMapToTypedCodesAndExitStatuses() {
        func classify(_ error: any Error, signal: Int32? = nil) -> CLIErrorObject {
            CLIFailure.classify(error, signal: signal)
        }
        XCTAssertEqual(classify(CLIError(.voiceNotFound, "no voice")).exitCode, 66)
        XCTAssertEqual(classify(CancellationError()).exitCode, 130)
        let terminated = classify(CancellationError(), signal: SIGTERM)
        XCTAssertEqual(terminated.code, .cancelled)
        XCTAssertEqual(terminated.exitCode, 143)
        XCTAssertEqual(terminated.detail?["signal"], .string("SIGTERM"))

        let pressure = classify(CLIEngineCancellation(reason: .memoryPressure))
        XCTAssertEqual(pressure.code, .memoryPressure)
        XCTAssertEqual(pressure.exitCode, CLIEngineCancellation.exitStatus)
        XCTAssertTrue(pressure.retryable)
        XCTAssertEqual(classify(CLIEngineCancellation(reason: .shutdown)).code, .engineBusy)

        let consent = classify(VoiceCloningConsentRequiredError(operation: .enrollment, message: "needs consent"))
        XCTAssertEqual(consent.code, .consentRequired)
        XCTAssertEqual(consent.exitCode, 77)

        XCTAssertEqual(classify(TTSEngineError.modelUnavailable("missing")).code, .modelNotInstalled)
        XCTAssertEqual(classify(TTSEngineError.modelUnavailable("missing")).exitCode, 69)
        XCTAssertEqual(classify(TTSEngineError.unknownModel("x")).code, .modelUnknown)
        XCTAssertEqual(classify(TTSEngineError.generationAdmissionRefused(.engineBusy)).code, .engineBusy)
        XCTAssertEqual(classify(TTSEngineError.savedVoiceStoreBusy).code, .storeBusy)
        XCTAssertEqual(classify(TTSEngineError.insufficientMemory("low")).code, .insufficientMemory)

        let unavailable = classify(HuggingFaceDownloader.DownloadError.httpError(statusCode: 503, path: "a/b", retryAfterSeconds: 2))
        XCTAssertEqual(unavailable.code, .networkUnavailable)
        XCTAssertEqual(unavailable.retryAfterMs, 2000)
        XCTAssertEqual(classify(HuggingFaceDownloader.DownloadError.httpError(statusCode: 404, path: "a/b")).code, .downloadFailed)
        XCTAssertEqual(
            classify(HuggingFaceDownloader.DownloadError.integrityCheckFailed(path: "a/b", reason: "digest")).code,
            .integrityFailed
        )
        XCTAssertEqual(classify(CocoaError(.fileReadNoSuchFile)).code, .inputFileNotFound)
        XCTAssertEqual(classify(CocoaError(.fileWriteOutOfSpace)).code, .storageFull)
        XCTAssertEqual(classify(AudioPreparationError.missingInputFile("x")).code, .inputFileNotFound)
        XCTAssertEqual(classify(DeliveryInstructionCellError.invalidCell("angry")).code, .invalidInput)
        XCTAssertEqual(classify(URLError(.cancelled)).code, .cancelled)
        XCTAssertEqual(classify(URLError(.notConnectedToInternet)).code, .networkUnavailable)
        XCTAssertEqual(classify(HuggingFaceDownloader.DownloadError.cancelled).code, .cancelled)

        // A signalled run exits 128 + the signal whatever else failed, and the report says so.
        let stopped = CLIErrorObject(code: .batchIncomplete, message: "stopped").signalled(by: SIGTERM)
        XCTAssertEqual(stopped.code, .cancelled)
        XCTAssertEqual(stopped.exitCode, 143)
        XCTAssertEqual(stopped.detail?["signal"], .string("SIGTERM"))
        XCTAssertEqual(stopped.detail?["failure"], .string("batch_incomplete"))
        XCTAssertEqual(CLIErrorObject(code: .qcRejected, message: "x").signalled(by: nil).code, .qcRejected)

        enum Unknown: Error { case fixture }
        XCTAssertEqual(classify(Unknown.fixture).code, .internalError)
        XCTAssertFalse(classify(Unknown.fixture).message.isEmpty)
        XCTAssertEqual(CLIFailure.rowCode(for: Unknown.fixture), .generationFailed, "a row names the take failing")
        XCTAssertEqual(CLIFailure.rowCode(for: TTSEngineError.modelUnavailable("x")), .modelNotInstalled)
    }

    func testPresenterWritesExactlyOneEnvelopeInJSONAndNothingInText() throws {
        let captured = Mutex<[Data]>([])
        let sink: @Sendable (Data) -> Bool = { data in
            captured.withLock { $0.append(data) }
            return true
        }
        struct Rows: Encodable, Sendable { let modes: [String] }

        CLIPresenter.begin(format: .json, command: "modes.list", requestID: "fixture", stdoutSink: sink)
        CLIPresenter.warn("note", "a warning")
        CLIPresenter.succeed(Rows(modes: ["custom"]))
        CLIPresenter.succeed(Rows(modes: ["twice"]))
        CLIPresenter.finishSuccessIfUnreported()
        let lines = captured.withLock { $0 }
        XCTAssertEqual(lines.count, 1, "one envelope, however many reports")
        let envelope = try XCTUnwrap(JSONSerialization.jsonObject(with: lines[0]) as? [String: Any])
        XCTAssertEqual(envelope["requestID"] as? String, "fixture")
        XCTAssertEqual(envelope["command"] as? String, "modes.list")
        XCTAssertEqual((envelope["warnings"] as? [[String: Any]])?.first?["code"] as? String, "note")
        XCTAssertEqual(((envelope["result"] as? [String: Any])?["modes"] as? [String]), ["custom"])

        captured.withLock { $0.removeAll() }
        CLIPresenter.begin(format: .json, command: "batch", requestID: "fixture", stdoutSink: sink)
        CLIPresenter.recordPartialResult(Rows(modes: ["kept"]))
        CLIPresenter.fail(CLIErrorObject(code: .batchIncomplete, message: "stopped"))
        let failed = try XCTUnwrap(
            JSONSerialization.jsonObject(with: try XCTUnwrap(captured.withLock { $0.first })) as? [String: Any]
        )
        XCTAssertEqual(failed["ok"] as? Bool, false)
        XCTAssertEqual(((failed["result"] as? [String: Any])?["modes"] as? [String]), ["kept"])
        XCTAssertEqual((failed["error"] as? [String: Any])?["code"] as? String, "batch_incomplete")

        captured.withLock { $0.removeAll() }
        CLIPresenter.begin(format: .ndjson, command: "modes.list", requestID: "fixture", stdoutSink: sink)
        CLIPresenter.event(.log, data: ["note": "fixture"])
        CLIPresenter.succeed(Rows(modes: ["custom"]))
        let records = try captured.withLock { $0 }.map {
            try XCTUnwrap(JSONSerialization.jsonObject(with: $0) as? [String: Any])
        }
        XCTAssertEqual(records.compactMap { $0["type"] as? String }, ["started", "log", "result"])
        XCTAssertEqual((records.last?["data"] as? [String: Any])?["requestID"] as? String, "fixture")

        captured.withLock { $0.removeAll() }
        CLIPresenter.begin(format: .text, command: "modes.list", stdoutSink: sink)
        CLIPresenter.succeed(Rows(modes: ["custom"]))
        XCTAssertTrue(captured.withLock { $0.isEmpty }, "text mode prints its own output")
    }
}
