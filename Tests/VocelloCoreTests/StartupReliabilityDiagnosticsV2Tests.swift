import CryptoKit
import Foundation
@testable import QwenVoiceCore
import VocelloQwen3Core
import XCTest

final class StartupReliabilityDiagnosticsV2Tests: XCTestCase {
    func testCollectedReplayAuthenticatesExactBytesAndRanges() throws {
        let trace = VocelloQwen3CodecTrace(frames: [Array(repeating: 1, count: 16), Array(repeating: 2, count: 16)], droppedFrameCount: 0)
        let data = StartupReliabilityDiagnosticEvidence.encode(trace)
        let evidence = replayEvidence(data)
        XCTAssertEqual(try StartupReliabilityDiagnosticEvidence.verifiedReplayTrace(data: data, evidence: evidence), trace)
        var changed = data
        changed[changed.count - 4] ^= 1
        XCTAssertThrowsError(try StartupReliabilityDiagnosticEvidence.verifiedReplayTrace(data: changed, evidence: evidence))
        XCTAssertThrowsError(try StartupReliabilityDiagnosticEvidence.verifiedReplayTrace(data: data.dropLast(), evidence: evidence))
    }

    func testCollectedReplayRejectsMissingOrChangedEvidence() throws {
        let data = StartupReliabilityDiagnosticEvidence.encode(VocelloQwen3CodecTrace(
            frames: [Array(repeating: 1, count: 16), Array(repeating: 2, count: 16)], droppedFrameCount: 0
        ))
        let valid = replayEvidence(data)
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(valid)) as? [String: Any])
        for key in ["sha256", "byteCount", "codecFrameCount", "complete", "codeGroupRange", "codecChunkRanges"] {
            var missing = json
            missing.removeValue(forKey: key)
            do {
                let evidence = try JSONDecoder().decode(StartupReliabilityArtifactEvidence.self, from: JSONSerialization.data(withJSONObject: missing))
                XCTAssertThrowsError(try StartupReliabilityDiagnosticEvidence.verifiedReplayTrace(data: data, evidence: evidence), key)
            } catch { /* Required decode fields also fail closed. */ }
        }
        for (key, value) in [("schemaVersion", 2 as Any), ("kind", "rejected_audio"), ("complete", false),
                             ("codecFrameCount", 3), ("codecChunkRanges", [["start": 1, "endExclusive": 2]])] {
            var changed = json
            changed[key] = value
            let evidence = try JSONDecoder().decode(StartupReliabilityArtifactEvidence.self, from: JSONSerialization.data(withJSONObject: changed))
            XCTAssertThrowsError(try StartupReliabilityDiagnosticEvidence.verifiedReplayTrace(data: data, evidence: evidence), key)
        }
    }

    func testCollectedReplayRejectsDroppedWrongWidthAndInvalidCodes() {
        var negative = Array(repeating: Int32(1), count: 16); negative[0] = -1
        var invalidSemantic = negative; invalidSemantic[0] = 4_096
        var invalidAcoustic = Array(repeating: Int32(1), count: 16); invalidAcoustic[1] = 2_048
        for frames in [[], [[1], [2]], [negative, negative], [invalidSemantic, invalidSemantic], [invalidAcoustic, invalidAcoustic]] {
            let data = StartupReliabilityDiagnosticEvidence.encode(VocelloQwen3CodecTrace(frames: frames, droppedFrameCount: 0))
            XCTAssertThrowsError(try StartupReliabilityDiagnosticEvidence.verifiedReplayTrace(data: data, evidence: replayEvidence(data)))
        }
        let dropped = StartupReliabilityDiagnosticEvidence.encode(VocelloQwen3CodecTrace(
            frames: [Array(repeating: 1, count: 16), Array(repeating: 1, count: 16)], droppedFrameCount: 1
        ))
        XCTAssertThrowsError(try StartupReliabilityDiagnosticEvidence.verifiedReplayTrace(data: dropped, evidence: replayEvidence(dropped)))
    }

    private func replayEvidence(_ data: Data) -> StartupReliabilityArtifactEvidence {
        StartupReliabilityArtifactEvidence(
            kind: .codecTrace,
            sha256: SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined(), byteCount: data.count,
            codecFrameCount: 2, codeGroupRange: .init(minimum: 16, maximum: 16),
            codecChunkRanges: [.init(start: 0, endExclusive: 1), .init(start: 1, endExclusive: 2)], complete: true
        )
    }

    func testCaptureRunIdentitySupportsUIAndBenchmarkWithoutAnonymousFallback() {
        let ui = "QVOICE_IOS_DEVICE_RUN_ID"
        let bench = "QVOICE_MAC_BENCH_RUN_ID"
        for environment in [[ui: "run-1"], [bench: "run-1"], [ui: "run-1", bench: "run-1"]] {
            XCTAssertEqual(StartupReliabilityDiagnosticEvidence.captureRunID(
                environment: environment, telemetryEnabled: true
            ), "run-1")
            XCTAssertNil(StartupReliabilityDiagnosticEvidence.captureRunID(
                environment: environment, telemetryEnabled: false
            ))
        }
        XCTAssertEqual(StartupReliabilityDiagnosticEvidence.captureRunID(
            environment: [ui: " run-1\n", bench: "run-1"], telemetryEnabled: true
        ), "run-1")
        for environment in [[:], [ui: "run-1", bench: "run-2"], [ui: "", bench: "run-1"]] {
            XCTAssertNil(StartupReliabilityDiagnosticEvidence.captureRunID(
                environment: environment, telemetryEnabled: true
            ))
        }
        for value in ["", " ", ".", "..", "../escape", "a/b", "not-bench", String(repeating: "x", count: 97)] {
            for key in [ui, bench] {
                XCTAssertNil(StartupReliabilityDiagnosticEvidence.captureRunID(
                    environment: [key: value], telemetryEnabled: true
                ), "Invalid or unowned diagnostic identity must not be captured")
            }
        }
    }

    func testUIOnlyRejectedAudioUsesTheSameRunDirectoryAsTheCollector() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let staged = root.appendingPathComponent("staged.wav")
        try AtomicPCM16WAVWriter.write(
            pcmSamples: Array(repeating: 0, count: 240), sampleRate: 24_000, outputURL: staged
        )
        let original = try Data(contentsOf: staged)
        let generationID = UUID()
        let environment = ["QVOICE_IOS_DEVICE_RUN_ID": "ui-run-1"]
        let writerRunID = try XCTUnwrap(StartupReliabilityDiagnosticEvidence.captureRunID(
            environment: environment, telemetryEnabled: true
        ))
        let evidence = try StartupReliabilityDiagnosticEvidence.persistRejectedAudio(
            from: staged, appSupportDirectory: root, runID: writerRunID,
            generationID: generationID, durationSeconds: 0.01
        )
        let collectorRunID = try XCTUnwrap(StartupReliabilityDiagnosticEvidence.captureRunID(
            environment: environment, telemetryEnabled: true
        ))
        let directory = try StartupReliabilityDiagnosticEvidence.evidenceDirectory(
            appSupportDirectory: root, runID: collectorRunID, generationID: generationID
        )
        XCTAssertEqual(try Data(contentsOf: directory.appendingPathComponent("rejected.wav")), original)
        XCTAssertEqual(try Data(contentsOf: staged), original)
        XCTAssertEqual(evidence.byteCount, original.count)
        XCTAssertEqual(evidence.sha256, SHA256.hash(data: original).map { String(format: "%02x", $0) }.joined())
        let json = String(decoding: try JSONEncoder().encode(evidence), as: UTF8.self)
        XCTAssertFalse(json.contains(root.path))
        XCTAssertFalse(json.contains("staged.wav"))
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.appendingPathComponent(
            "diagnostics/startup-reliability-evidence/not-bench"
        ).path))
    }

    func testDotRunIdentifiersCannotAddressOrRemoveTheEvidenceRoot() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let marker = root.appendingPathComponent("diagnostics/startup-reliability-evidence/kept.bin")
        try FileManager.default.createDirectory(at: marker.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data([1, 2, 3]).write(to: marker)
        defer { try? FileManager.default.removeItem(at: root) }
        for value in [".", ".."] {
            XCTAssertThrowsError(try StartupReliabilityDiagnosticEvidence.evidenceDirectory(
                appSupportDirectory: root, runID: value, generationID: UUID()
            ))
            XCTAssertThrowsError(try StartupReliabilityDiagnosticEvidence.removeRun(
                appSupportDirectory: root, runID: value
            ))
            XCTAssertEqual(try Data(contentsOf: marker), Data([1, 2, 3]))
        }
    }

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
