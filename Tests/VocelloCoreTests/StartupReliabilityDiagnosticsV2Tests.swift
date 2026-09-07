import CryptoKit
import Foundation
@testable import QwenVoiceCore
import VocelloQwen3Core
import XCTest

final class StartupReliabilityDiagnosticsV2Tests: XCTestCase {
    func testDeviceTakeEncoderFeedsRealHostValidatorWithoutInventingQC() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let receipt = replayReceipt()
        let trace = VocelloQwen3CodecTrace(frames: [Array(repeating: 1, count: 16)], droppedFrameCount: 0)
        let artifact = try StartupReliabilityDiagnosticEvidence.persistCodecTrace(
            trace, codecChunkRanges: [.init(start: 0, endExclusive: 1)],
            appSupportDirectory: root, runID: "run-1", generationID: UUID(uuidString: receipt.generationID)!
        )
        let captured = root.appendingPathComponent("evidence/\(receipt.generationID)")
        try FileManager.default.createDirectory(at: captured, withIntermediateDirectories: true)
        let originalTrace = try StartupReliabilityDiagnosticEvidence.evidenceDirectory(
            appSupportDirectory: root, runID: "run-1", generationID: UUID(uuidString: receipt.generationID)!
        ).appendingPathComponent("codec-trace-v1.bin")
        try FileManager.default.copyItem(at: originalTrace, to: captured.appendingPathComponent("codec-trace-v1.bin"))
        let terminal = GenerationTerminalDiagnosticEvidence(
            requestReceipt: receipt, audioQC: nil,
            notes: artifact.telemetryNotes.merging(["nativeRuntimeFailureCode": "generation.incomplete"]) { _, new in new },
            stageNames: [GenerationStartupBoundary.firstDecodedAudioFrame.telemetryStage]
        )
        XCTAssertEqual(terminal.diagnosticArtifacts, [artifact])
        XCTAssertEqual(terminal.classification, .postGenerationFailure)
        typealias Record = IOSStartupReliabilityRecord
        let timeline: [Record.BoundaryResult] = [
            .init(boundary: "first_model_token", tMS: 1),
            .init(boundary: "first_audio_code_group", tMS: 1),
            .init(boundary: "first_decoded_audio_frame", tMS: 2)
        ]
        let take = Record.TakeResult(
            takeIndex: 1, takeID: "cap-1", generationID: receipt.generationID,
            status: "failed", preparation: "production", prePreparationStoreWarmState: "cold",
            preRequestStoreWarmState: "cold", preparationEvidence: [Record.PreparationEvidence(
                stage: "before_preparation", sequence: 0, capturedAtUptimeSeconds: 1,
                mlxActiveMB: nil, mlxCacheMB: nil, mlxPeakMB: nil, metalAllocatedMB: nil,
                physicalFootprintMB: nil, availableHeadroomMB: nil, hasActiveGeneration: false,
                memoryActionInFlight: false, modelOperationInFlight: false,
                generationReservationInFlight: false, loadedModelID: nil, engineLifecycle: "idle", violations: []
            )], requestReceipt: receipt,
            attempts: [.init(retryAttempt: 0, finishReason: "failed", requestReceipt: receipt, startupTimeline: timeline)],
            startupTimeline: timeline, failureCode: terminal.failureCode,
            classification: terminal.classification.rawValue, output: nil, audioQC: nil,
            diagnosticArtifacts: terminal.diagnosticArtifacts, codecReplay: nil
        )
        let bytes = try JSONEncoder().encode(take)
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: bytes) as? [String: Any])
        XCTAssertTrue(json["audioQC"] is NSNull)
        XCTAssertNil(json["output"])
        XCTAssertNil(json["codecReplay"])
        var historical = json
        historical.removeValue(forKey: "audioQC")
        XCTAssertNil(try JSONDecoder().decode(Record.TakeResult.self,
            from: JSONSerialization.data(withJSONObject: historical)).audioQC)
        for verdict in [AudioQCReport.Verdict.pass, .warn, .fail] {
            let report = AudioQCReport(verdict: verdict, flags: verdict == .pass ? [] : ["fixture"],
                rmsDBFS: -20, peak: 0.4, clippedSamples: 0, hotSamples: 0, nonFiniteSamples: 0,
                clickEvents: 0, longestSilenceMS: 0, durationSeconds: 1)
            var withQC = json
            withQC["audioQC"] = try JSONSerialization.jsonObject(with: JSONEncoder().encode(report))
            let decoded = try JSONDecoder().decode(Record.TakeResult.self,
                from: JSONSerialization.data(withJSONObject: withQC))
            let roundTrip = try JSONDecoder().decode(Record.TakeResult.self, from: JSONEncoder().encode(decoded))
            XCTAssertEqual(roundTrip.audioQC, report)
        }

        let takeURL = root.appendingPathComponent("swift-take.json")
        try bytes.write(to: takeURL)
        let repository = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
        let child = Process()
        child.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        child.currentDirectoryURL = repository
        // The take is the actual production Swift encoder output. Only the run
        // envelope/plan are test fixtures; Python validates rather than repairs it.
        child.arguments = ["python3", "-c", #"""
import copy, json, pathlib, sys
sys.path.insert(0, 'scripts')
import ios_startup_reliability as m
root, take_path = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
original = take_path.read_bytes()
take = json.loads(original); receipt = take['requestReceipt']
plan = {'schemaVersion':1, 'scriptSHA256':receipt['normalizedTargetTextDigest'],
        'scriptCharacters':receipt['normalizedTargetTextCharacters'], 'takes':[{
        'takeIndex':1,'takeID':'cap-1','preparation':'production',
        **{k:receipt[k] for k in ('speakerID','deliveryID','language','seed','variation','streaming')}}]}
plan_path=root/'plan.json'; plan_path.write_text(json.dumps(plan))
state={'lowPowerModeEnabled':False,'thermalState':'nominal','modelInstalled':True}
result={'schemaVersion':2,'runID':'run-1','status':'diagnosed_failure',
        'scriptSHA256':plan['scriptSHA256'],'scriptCharacters':plan['scriptCharacters'],
        'plannedTakeCount':1,'representedTakeCount':1,'startedAt':'2026-09-07T00:00:00Z',
        'finishedAt':'2026-09-07T00:01:00Z','startingDeviceState':state,'finishingDeviceState':state,
        'publishedAudioCaptureRequired':True,'takes':[take]}
terminal=root/'startup-reliability-result.json'
terminal.write_text(json.dumps(result))
assert m.validate_result(plan_path,root,'run-1')['failedTakeCount']==1
for mutation, reason in [
    (lambda t:t.pop('audioQC'), 'schema v2'),
    (lambda t:t.update(diagnosticArtifacts=[]), 'codec trace'),
    (lambda t:t.update(startupTimeline=[]), 'boundary'),
    (lambda t:t.update(status='pass'), 'generation failure'),
    (lambda t:t.update(failureCode='audio_qc_failed',classification='post_generation_qc'), 'complete failing report')]:
    invalid=copy.deepcopy(result);mutation(invalid['takes'][0]);terminal.write_text(json.dumps(invalid))
    try:m.validate_result(plan_path,root,'run-1')
    except m.ContractError as e:assert reason in str(e), str(e)
    else:raise AssertionError('invalid take accepted')
assert take_path.read_bytes()==original
"""#, root.path, takeURL.path]
        let log = Pipe()
        child.standardOutput = log
        child.standardError = log
        try child.run()
        let output = log.fileHandleForReading.readDataToEndOfFile()
        child.waitUntilExit()
        XCTAssertEqual(child.terminationStatus, 0, String(decoding: output, as: UTF8.self))
    }

    func testNoQCReplayRequiresExactReceiptBoundScriptAndTypedFailure() throws {
        let receipt = replayReceipt()
        let expected = PersistedWAVAudioQCAnalyzer.expectedPauseCount(in: "First sentence. Second sentence.")
        XCTAssertEqual(try StartupReliabilityDiagnosticEvidence.replayExpectedPauseCount(
            report: nil, failureCode: "generation.incomplete", receipt: receipt,
            script: "First sentence. Second sentence."
        ), expected)
        for script in [nil, "Different sentence.", "", "First sentence. Second sentence!"] {
            XCTAssertThrowsError(try StartupReliabilityDiagnosticEvidence.replayExpectedPauseCount(
                report: nil, failureCode: "generation.incomplete", receipt: receipt, script: script
            ))
        }
        for code in [nil, "generation.cancelled", "audio_qc_failed", "generation.failed"] {
            XCTAssertThrowsError(try StartupReliabilityDiagnosticEvidence.replayExpectedPauseCount(
                report: nil, failureCode: code, receipt: receipt, script: "First sentence. Second sentence."
            ))
        }
        XCTAssertTrue(StartupReliabilityDiagnosticEvidence.requiresCodecReplay(nil, failureCode: "generation.incomplete"))
        XCTAssertFalse(StartupReliabilityDiagnosticEvidence.requiresCodecReplay(nil, failureCode: "generation.cancelled"))
        XCTAssertFalse(StartupReliabilityDiagnosticEvidence.requiresCodecReplay(nil))
    }

    func testFailureClassificationDoesNotCallTokenCapAQCRejection() {
        let metadata = GenerationFailureDiagnosticLogger.errorMetadata(for: NativeRuntimeError.maximumTokenLimit())
        XCTAssertEqual(StartupReliabilityDiagnosticEvidence.failureClassification(
            metadata: metadata, hasDecodedAudio: true, hasStartupBoundary: true, audioQC: nil
        ), "post_generation_failure")
        XCTAssertEqual(StartupReliabilityDiagnosticEvidence.failureClassification(
            metadata: metadata, hasDecodedAudio: false, hasStartupBoundary: true, audioQC: nil
        ), "pre_audio_startup")
        XCTAssertEqual(StartupReliabilityDiagnosticEvidence.failureClassification(
            metadata: GenerationFailureDiagnosticLogger.errorMetadata(for: CancellationError()),
            hasDecodedAudio: true, hasStartupBoundary: true, audioQC: nil
        ), "cancelled")
        let qc = AudioQCReport(verdict: .fail, flags: ["silent"], rmsDBFS: nil, peak: 0,
            clippedSamples: 0, hotSamples: 0, nonFiniteSamples: 0, clickEvents: 0,
            longestSilenceMS: 0, durationSeconds: 1)
        XCTAssertEqual(StartupReliabilityDiagnosticEvidence.failureClassification(
            metadata: metadata, hasDecodedAudio: true, hasStartupBoundary: true, audioQC: qc
        ), "post_generation_qc")
    }

    func testExistingQCCadenceReplayDoesNotRequireScriptAndRejectsContradictions() throws {
        let cadence = AudioCadenceQCReport(classification: .withinFastGate, reasons: [],
            expectedPauseCount: 17, cadencePauseThresholdMS: 350, suspiciousPauseThresholdMS: 1200,
            observedCadencePauseCount: 0, excessCadencePauseCount: 0, suspiciousPauseCount: 0,
            recordedInteriorPausesMS: [], totalInteriorSilenceMS: 0, totalCadenceSilenceMS: 0,
            medianCadencePauseMS: nil, p90CadencePauseMS: nil, cadenceSilenceRatio: 0)
        let qc = AudioQCReport(verdict: .warn, flags: ["fixture"], rmsDBFS: -20, peak: 0.4,
            clippedSamples: 0, hotSamples: 0, nonFiniteSamples: 0, clickEvents: 0,
            longestSilenceMS: 0, durationSeconds: 1, cadence: cadence)
        XCTAssertEqual(try StartupReliabilityDiagnosticEvidence.replayExpectedPauseCount(
            report: qc, failureCode: nil, receipt: replayReceipt(), script: nil
        ), 17)
        XCTAssertThrowsError(try StartupReliabilityDiagnosticEvidence.replayExpectedPauseCount(
            report: qc, failureCode: nil, receipt: replayReceipt(), script: "First sentence. Second sentence."
        ))
        XCTAssertTrue(StartupReliabilityDiagnosticEvidence.requiresCodecReplay(qc))
    }

    private func replayReceipt() -> GenerationRequestReceipt {
        let id = UUID(uuidString: "11111111-2222-3333-4444-555555555555")!
        let request = GenerationRequest(mode: .custom, modelID: "pro_custom",
            text: "First sentence. Second sentence.", outputPath: "/fixture/output.wav", shouldStream: true,
            languageHint: "english", payload: .custom(speakerID: "aiden", deliveryStyle: nil),
            generationID: id, seed: UInt64.max, variation: .consistent,
            deliveryInstructionCellID: "neutral.normal")
        return GenerationRequestReceipt(request: request, generationID: id, effectiveSeed: UInt64.max,
            warmState: .cold, predecessorIdentityDigest: nil, retryAttempt: 0, operationGeneration: 1)
    }

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
