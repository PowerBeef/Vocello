import Foundation
@testable import QwenVoiceCore
import VocelloQwen3Core
import XCTest

final class StartupReliabilityDiagnosticsV2Tests: XCTestCase {
    func testCodecTraceEncodingAndPersistenceAreDeterministicAndGenerationScoped() throws {
        let trace = VocelloQwen3CodecTrace(
            frames: [[1, 2, 3], [4, 5, 6]],
            droppedFrameCount: 0
        )
        let first = StartupReliabilityDiagnosticEvidence.encode(trace)
        let second = StartupReliabilityDiagnosticEvidence.encode(trace)
        XCTAssertEqual(first, second)
        XCTAssertEqual(String(decoding: first.prefix(4), as: UTF8.self), "VQCT")

        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let generationID = UUID()
        let evidence = try StartupReliabilityDiagnosticEvidence.persistCodecTrace(
            trace,
            codecChunkRanges: [StartupReliabilityCodecFrameRange(start: 0, endExclusive: 2)],
            appSupportDirectory: root,
            runID: "run-1",
            generationID: generationID
        )
        XCTAssertEqual(evidence.kind, .codecTrace)
        XCTAssertEqual(evidence.codecFrameCount, 2)
        XCTAssertEqual(evidence.codeGroupRange?.minimum, 3)
        XCTAssertEqual(evidence.codeGroupRange?.maximum, 3)
        XCTAssertEqual(
            evidence.codecChunkRanges,
            [StartupReliabilityCodecFrameRange(start: 0, endExclusive: 2)]
        )
        XCTAssertEqual(evidence.complete, true)
        XCTAssertFalse(evidence.telemetryNotes.values.contains { $0.contains(root.path) })

        try StartupReliabilityDiagnosticEvidence.removeRun(
            appSupportDirectory: root,
            runID: "run-1"
        )
        XCTAssertFalse(FileManager.default.fileExists(
            atPath: root.appendingPathComponent(
                "diagnostics/startup-reliability-evidence/run-1",
                isDirectory: true
            ).path
        ))
    }

    func testCodecTraceRejectsOutOfBoundsAndUnsafeRunIdentity() throws {
        let root = FileManager.default.temporaryDirectory
        XCTAssertThrowsError(try StartupReliabilityDiagnosticEvidence.persistCodecTrace(
            VocelloQwen3CodecTrace(frames: [Array(repeating: 1, count: 65)], droppedFrameCount: 0),
            codecChunkRanges: [StartupReliabilityCodecFrameRange(start: 0, endExclusive: 1)],
            appSupportDirectory: root,
            runID: "run-1",
            generationID: UUID()
        ))
        XCTAssertThrowsError(try StartupReliabilityDiagnosticEvidence.evidenceDirectory(
            appSupportDirectory: root,
            runID: "../private",
            generationID: UUID()
        ))
    }

    func testCodecTraceRoundTripsSignedValuesAndRejectsCorruption() throws {
        let trace = VocelloQwen3CodecTrace(
            frames: [[Int32.min, -1, 0], [1, 255, Int32.max]],
            droppedFrameCount: 2
        )
        let encoded = StartupReliabilityDiagnosticEvidence.encode(trace)
        XCTAssertEqual(try StartupReliabilityDiagnosticEvidence.decode(encoded), trace)

        var trailing = encoded
        trailing.append(0)
        XCTAssertThrowsError(try StartupReliabilityDiagnosticEvidence.decode(trailing))

        var truncated = encoded
        truncated.removeLast()
        XCTAssertThrowsError(try StartupReliabilityDiagnosticEvidence.decode(truncated))
    }

    func testCodecTraceRejectsGappedAndIncompleteChunkRanges() throws {
        let root = FileManager.default.temporaryDirectory
        let trace = VocelloQwen3CodecTrace(frames: [[1], [2], [3]], droppedFrameCount: 0)
        XCTAssertThrowsError(try StartupReliabilityDiagnosticEvidence.persistCodecTrace(
            trace,
            codecChunkRanges: [
                StartupReliabilityCodecFrameRange(start: 0, endExclusive: 1),
                StartupReliabilityCodecFrameRange(start: 2, endExclusive: 3),
            ],
            appSupportDirectory: root,
            runID: "run-1",
            generationID: UUID()
        ))
        XCTAssertThrowsError(try StartupReliabilityDiagnosticEvidence.persistCodecTrace(
            trace,
            codecChunkRanges: [StartupReliabilityCodecFrameRange(start: 0, endExclusive: 2)],
            appSupportDirectory: root,
            runID: "run-1",
            generationID: UUID()
        ))
    }

    func testUnloadQuiescenceRequiresThreeStableQualifiedSamples() {
        let samples = (0 ..< 4).map { sample(sequence: $0) }
        XCTAssertTrue(IOSUnloadQuiescenceEvaluator.isQuiescent(samples))
        XCTAssertFalse(IOSUnloadQuiescenceEvaluator.isQuiescent(Array(samples.prefix(3))))

        var unstable = samples
        unstable[3] = sample(sequence: 3, activeMB: 160)
        XCTAssertEqual(
            IOSUnloadQuiescenceEvaluator.violations(
                current: unstable[3],
                previous: unstable[2]
            ),
            [.mlxActiveUnstable]
        )
        XCTAssertFalse(IOSUnloadQuiescenceEvaluator.isQuiescent(unstable))
    }

    func testUnloadQuiescenceRejectsOwnershipHeadroomCacheAndFootprintFailures() {
        let previous = sample(sequence: 0)
        let current = sample(
            sequence: 1,
            cacheMB: 64,
            footprintMB: 4_600,
            headroomMB: 500,
            hasActiveGeneration: true,
            modelOperationInFlight: true,
            generationReservationInFlight: true,
            loadedModelID: "pro_custom"
        )
        let violations = IOSUnloadQuiescenceEvaluator.violations(
            current: current,
            previous: previous
        )
        XCTAssertTrue(violations.contains(.activeGeneration))
        XCTAssertTrue(violations.contains(.modelOperationInFlight))
        XCTAssertTrue(violations.contains(.generationReservationInFlight))
        XCTAssertTrue(violations.contains(.modelStillLoaded))
        XCTAssertTrue(violations.contains(.mlxCacheNotCleared))
        XCTAssertTrue(violations.contains(.insufficientHeadroom))
        XCTAssertTrue(violations.contains(.guardedFootprintExceeded))
    }

    private func sample(
        sequence: Int,
        activeMB: Double = 100,
        cacheMB: Double = 0,
        metalMB: Double = 120,
        footprintMB: Double = 1_200,
        headroomMB: Double = 2_000,
        hasActiveGeneration: Bool = false,
        modelOperationInFlight: Bool = false,
        generationReservationInFlight: Bool = false,
        loadedModelID: String? = nil
    ) -> IOSUnloadQuiescenceSample {
        IOSUnloadQuiescenceSample(
            sequence: sequence,
            capturedAtUptimeSeconds: Double(sequence),
            mlx: NativeMLXMemorySnapshot(activeMB: activeMB, cacheMB: cacheMB, peakMB: 500),
            process: IOSMemorySnapshot(
                totalDeviceRAMBytes: 8 * 1_024 * 1_024 * 1_024,
                availableHeadroomBytes: UInt64(headroomMB * 1_048_576),
                residentBytes: nil,
                physFootprintBytes: UInt64(footprintMB * 1_048_576),
                compressedBytes: nil,
                gpuAllocatedBytes: UInt64(metalMB * 1_048_576),
                gpuRecommendedWorkingSetBytes: nil,
                hasUnifiedMemory: true
            ),
            hasActiveGeneration: hasActiveGeneration,
            criticalMemoryActionInFlight: false,
            modelOperationInFlight: modelOperationInFlight,
            generationReservationInFlight: generationReservationInFlight,
            loadedModelID: loadedModelID,
            engineLifecycle: "idle"
        )
    }
}
