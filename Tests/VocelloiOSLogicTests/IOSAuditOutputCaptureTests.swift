import Foundation
import XCTest

final class IOSAuditOutputCaptureTests: XCTestCase {
    func testStartupPublishedOutputSurvivesScratchCleanup() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let source = root.appendingPathComponent("source.wav")
        let bytes = Data(repeating: 7, count: 128)
        try bytes.write(to: source)
        let id = UUID()
        let run = "ios-startup-reliability-fixture"
        let environment = ["QVOICE_IOS_DEVICE_RUN_ID": run, "QVOICE_MAC_BENCH_RUN_ID": run]
        let capture = try XCTUnwrap(IOSPullableDiagnosticsMirror.captureAuditOutput(
            from: source, generationID: id, environment: environment,
            telemetryEnabled: true, pullableRoot: root
        ))
        XCTAssertEqual(capture, root.appendingPathComponent(run)
            .appendingPathComponent("outputs").appendingPathComponent("\(id.uuidString).wav"))
        try FileManager.default.removeItem(at: source)
        XCTAssertEqual(try Data(contentsOf: capture), bytes)
    }

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
            (false, ["QVOICE_IOS_DEVICE_RUN_ID": "ios-startup-reliability-fixture"]),
            (true, ["QVOICE_IOS_DEVICE_RUN_ID": "ios-startup-reliability-fixture", "QVOICE_MAC_BENCH_RUN_ID": "other"]),
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

    func testSyncGenerationTelemetryMirrorsEngineAndAppRowsAndBothSampleSidecars() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let sourceRoot = root.appendingPathComponent("source", isDirectory: true)
        let pullableRoot = root.appendingPathComponent("pullable", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: root) }

        let targetID = UUID().uuidString
        let otherID = UUID().uuidString
        for layer in ["engine", "app"] {
            let layerDir = sourceRoot.appendingPathComponent(layer, isDirectory: true)
            try FileManager.default.createDirectory(at: layerDir, withIntermediateDirectories: true)
            let targetRow = "{\"generationID\":\"\(targetID)\",\"layer\":\"\(layer)\"}"
            let otherRow = "{\"generationID\":\"\(otherID)\",\"layer\":\"\(layer)\"}"
            try (targetRow + "\n" + otherRow + "\n").write(
                to: layerDir.appendingPathComponent("generations.jsonl"),
                atomically: true,
                encoding: .utf8
            )
            let sampleContent = "{\"boundary\":\"\(layer)_submit\",\"tMS\":0}\n"
            try sampleContent.write(
                to: layerDir.appendingPathComponent("samples-\(targetID).jsonl"),
                atomically: true,
                encoding: .utf8
            )
        }

        IOSPullableDiagnosticsMirror.syncGenerationTelemetry(
            generationID: targetID,
            from: sourceRoot,
            into: pullableRoot
        )
        // Second call must be idempotent and must not duplicate rows.
        IOSPullableDiagnosticsMirror.syncGenerationTelemetry(
            generationID: targetID,
            from: sourceRoot,
            into: pullableRoot
        )

        for layer in ["engine", "app"] {
            let rowsURL = pullableRoot
                .appendingPathComponent(layer, isDirectory: true)
                .appendingPathComponent("generations.jsonl")
            let rowsText = try String(contentsOf: rowsURL, encoding: .utf8)
            let lines = rowsText.split(separator: "\n")
            XCTAssertEqual(lines.count, 1, "expected exactly one mirrored \(layer) row")
            XCTAssertTrue(rowsText.contains(targetID))
            XCTAssertFalse(rowsText.contains(otherID))

            let sampleURL = pullableRoot
                .appendingPathComponent(layer, isDirectory: true)
                .appendingPathComponent("samples-\(targetID).jsonl")
            XCTAssertTrue(
                FileManager.default.fileExists(atPath: sampleURL.path),
                "expected mirrored \(layer) raw samples sidecar"
            )
            let sampleText = try String(contentsOf: sampleURL, encoding: .utf8)
            XCTAssertTrue(sampleText.contains("\(layer)_submit"))
        }
    }
}
