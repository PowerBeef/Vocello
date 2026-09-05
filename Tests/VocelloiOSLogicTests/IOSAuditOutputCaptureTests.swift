import Foundation
import XCTest

final class IOSAuditOutputCaptureTests: XCTestCase {
    func testGatedAtomicCopyPreservesSourceAndRejectsIdentityCollision() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let source = root.appendingPathComponent("source.wav")
        let bytes = Data(repeating: 7, count: 128)
        try bytes.write(to: source)
        let id = UUID()
        let environment = ["QVOICE_IOS_DEVICE_RUN_ID": "ios-xcui-control-audit-fixture"]
        let capture = try XCTUnwrap(IOSPullableDiagnosticsMirror.captureAuditOutput(
            from: source, generationID: id, environment: environment,
            telemetryEnabled: true, pullableRoot: root
        ))
        XCTAssertEqual(try Data(contentsOf: source), bytes)
        XCTAssertEqual(try Data(contentsOf: capture), bytes)
        XCTAssertEqual(try IOSPullableDiagnosticsMirror.captureAuditOutput(
            from: source, generationID: id, environment: environment,
            telemetryEnabled: true, pullableRoot: root
        ), capture)
        try Data(repeating: 8, count: 128).write(to: source)
        XCTAssertThrowsError(try IOSPullableDiagnosticsMirror.captureAuditOutput(
            from: source, generationID: id, environment: environment,
            telemetryEnabled: true, pullableRoot: root
        ))
        XCTAssertEqual(try Data(contentsOf: capture), bytes)
        XCTAssertEqual(try Data(contentsOf: source), Data(repeating: 8, count: 128))
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: capture.deletingLastPathComponent().path), [capture.lastPathComponent])
    }

    func testDisabledAnonymousOtherLaneAndConflictingRunNeverReadAudio() throws {
        let missing = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        for (enabled, environment) in [
            (false, ["QVOICE_IOS_DEVICE_RUN_ID": "ios-xcui-control-audit-fixture"]),
            (true, [:]), (true, ["QVOICE_IOS_DEVICE_RUN_ID": "ios-xcui-smoke-fixture"]),
            (true, ["QVOICE_IOS_DEVICE_RUN_ID": "ios-xcui-control-audit-../escape"]),
            (true, ["QVOICE_IOS_DEVICE_RUN_ID": "ios-xcui-control-audit-fixture", "QVOICE_MAC_BENCH_RUN_ID": "other"])
        ] {
            XCTAssertNil(try IOSPullableDiagnosticsMirror.captureAuditOutput(
                from: missing, generationID: UUID(), environment: environment,
                telemetryEnabled: enabled, pullableRoot: missing
            ))
            XCTAssertFalse(FileManager.default.fileExists(atPath: missing.path))
        }
    }

    func testCopyFailureAndInvalidFileLeaveSourceUntouched() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let source = root.appendingPathComponent("source.wav")
        let environment = ["QVOICE_IOS_DEVICE_RUN_ID": "ios-xcui-control-audit-fixture"]
        for bytes in [Data([1]), Data(repeating: 1, count: 128)] {
            try bytes.write(to: source)
            XCTAssertThrowsError(try IOSPullableDiagnosticsMirror.captureAuditOutput(
                from: source, generationID: UUID(), environment: environment,
                telemetryEnabled: true, pullableRoot: source
            ))
            XCTAssertEqual(try Data(contentsOf: source), bytes)
        }
    }
}
