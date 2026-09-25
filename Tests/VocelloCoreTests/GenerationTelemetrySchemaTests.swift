import Foundation
@testable import QwenVoiceCore
import VocelloQwen3Core
import XCTest

final class GenerationTelemetrySchemaTests: XCTestCase {
    func testSubmillisecondStageMarksSortByNanosecondsBeforeStageName() {
        let ended = NativeTelemetryStageMark(
            tMS: 2_915,
            tNS: 2_915_286_041,
            sequence: 2,
            stage: "streamGenerationEnded"
        )
        let completed = NativeTelemetryStageMark(
            tMS: 2_915,
            tNS: 2_915_749_416,
            sequence: 3,
            stage: "streamCompleted"
        )

        let sorted = [completed, ended].sorted(by: NativeTelemetryStageMark.chronologicallyPrecedes)

        XCTAssertEqual(sorted.map(\.stage), ["streamGenerationEnded", "streamCompleted"])
        XCTAssertEqual(sorted.map(\.sequence), [2, 3])
    }

    func testSchemaV8RoundTripCarriesTypedBackendMetrics() throws {
        let record = GenerationTelemetryRecord(
            generationID: UUID().uuidString,
            layer: .engine,
            recordedAt: "2026-07-10T00:00:00Z",
            mode: "custom",
            modelID: "pro_custom_speed",
            warmState: .warm,
            usedStreaming: true,
            finishReason: "eos",
            stageMarks: [NativeTelemetryStageMark(tMS: 4, tNS: 4_000_000, sequence: 0, stage: "firstChunk")],
            timingsMS: [
                "qwen_token_loop_total": 120,
                "qwen_stream_decoder_total": 30,
            ],
            counters: ["chunkCount": 2],
            modelRuntimeIdentity: ModelRuntimeIdentity(
                resolvedModelID: "pro_custom_speed",
                modelVariant: "speed",
                runtimeProfileSignature: "runtime-profile-fixture",
                nativeLoadCapabilityProfile: "full",
                fixtureDigest: String(repeating: "a", count: 64)
            )
        )

        let data = try JSONEncoder().encode(record)
        let decoded = try JSONDecoder().decode(GenerationTelemetryRecord.self, from: data)

        XCTAssertEqual(decoded.schemaVersion, 8)
        XCTAssertEqual(decoded.backendMetrics?.finishReason, .eos)
        XCTAssertEqual(decoded.backendMetrics?.warmState, .warm)
        XCTAssertEqual(decoded.backendMetrics?.stages.count, 1)
        XCTAssertEqual(
            decoded.backendMetrics?.timings.first(where: { $0.key == .tokenLoop })?.milliseconds,
            120
        )
        XCTAssertEqual(decoded.modelRuntimeIdentity?.resolvedModelID, "pro_custom_speed")
        XCTAssertEqual(decoded.modelRuntimeIdentity?.modelVariant, "speed")
        XCTAssertEqual(decoded.modelRuntimeIdentity?.runtimeProfileSignature, "runtime-profile-fixture")
        XCTAssertEqual(decoded.modelRuntimeIdentity?.fixtureDigest, String(repeating: "a", count: 64))
    }

    func testLegacyV5RowDecodesWithoutTypedPayloads() throws {
        let json = """
        {
          "schemaVersion": 5,
          "generationID": "legacy",
          "layer": "engine",
          "processName": "fixture",
          "processIdentifier": 1,
          "recordedAt": "2026-07-10T00:00:00Z",
          "stageMarks": [],
          "timingsMS": {"qwen_token_loop_total": 10},
          "counters": {},
          "notes": {}
        }
        """

        let decoded = try JSONDecoder().decode(
            GenerationTelemetryRecord.self,
            from: Data(json.utf8)
        )

        XCTAssertEqual(decoded.schemaVersion, 5)
        XCTAssertNil(decoded.backendMetrics)
        XCTAssertEqual(decoded.timingsMS["qwen_token_loop_total"], 10)
    }

    func testLegacyV1ThroughV5RowsRemainDecodable() throws {
        for version in 1...5 {
            let json = """
            {
              "schemaVersion": \(version),
              "generationID": "legacy-\(version)",
              "layer": "engine",
              "processName": "fixture",
              "processIdentifier": 1,
              "recordedAt": "2026-07-10T00:00:00Z",
              "stageMarks": [],
              "timingsMS": {},
              "counters": {},
              "notes": {}
            }
            """
            let decoded = try JSONDecoder().decode(
                GenerationTelemetryRecord.self,
                from: Data(json.utf8)
            )
            XCTAssertEqual(decoded.schemaVersion, version)
            XCTAssertNil(decoded.frontendMetrics)
            XCTAssertNil(decoded.transportMetrics)
            XCTAssertNil(decoded.backendMetrics)
            XCTAssertNil(decoded.outputMetrics)
            XCTAssertNil(decoded.modelRuntimeIdentity)
        }
    }

    func testSamplingTelemetryNotesExposeDeterministicRequestIdentity() {
        let request = GenerationRequest(
            mode: .custom,
            modelID: "pro_custom_speed",
            text: "Deterministic diagnostic sample.",
            outputPath: "/tmp/sample.wav",
            shouldStream: true,
            payload: .custom(speakerID: "aiden", deliveryStyle: nil),
            seed: UInt64.max,
            variation: .consistent
        )

        XCTAssertEqual(
            StreamingExecutionContext.samplingTelemetryNotes(for: request),
            [
                "samplingPlannedSeed": String(UInt64.max),
                "samplingSeed": String(UInt64.max),
                "samplingVariation": "consistent",
            ]
        )
    }

    func testSamplingTelemetryNotesNameTheImplicitExpressiveDefault() {
        let request = GenerationRequest(
            mode: .design,
            modelID: "pro_design_speed",
            text: "Default sampling diagnostic sample.",
            outputPath: "/tmp/sample.wav",
            shouldStream: true,
            payload: .design(voiceDescription: "A clear narrator.", deliveryStyle: nil)
        )

        XCTAssertEqual(
            StreamingExecutionContext.samplingTelemetryNotes(for: request),
            ["samplingVariation": "expressive"]
        )
    }

    func testTelemetryOffPlansNoSamplerSinkChunkQCOrDerivedDiagnostics() {
        let off = NativeTelemetryWorkPlan(
            mode: .off,
            recorderPresent: true,
            sampleIntervalAvailable: true
        )
        XCTAssertFalse(off.constructsSampler)
        XCTAssertFalse(off.writesSink)
        XCTAssertFalse(off.computesChunkQC)
        XCTAssertFalse(off.computesDerivedDiagnostics)

        let verbose = NativeTelemetryWorkPlan(
            mode: .verbose,
            recorderPresent: true,
            sampleIntervalAvailable: true
        )
        XCTAssertTrue(verbose.constructsSampler)
        XCTAssertTrue(verbose.writesSink)
        XCTAssertTrue(verbose.computesChunkQC)
        XCTAssertTrue(verbose.computesDerivedDiagnostics)
    }

    /// Audit #20: the full default matrix plans 58 verbose generations. A bench
    /// run sized to its plan keeps every sidecar publication needs, where the
    /// ad-hoc budget keeps only the newest 48.
    func testBenchRunSidecarBudgetKeepsEverySidecarOfTheDefaultMatrix() async throws {
        XCTAssertEqual(BenchMatrixSpec.plannedGenerationCount(
            modes: BenchMatrixSpec.defaultModes,
            variantCount: 2,
            lengths: BenchMatrixSpec.defaultLengths,
            warm: BenchMatrixSpec.defaultWarmReps,
            deliveryCellCount: 0,
            ttfcProbe: false
        ), 58)
        let budget = try XCTUnwrap(GenerationTelemetrySidecarBudget.benchRun(plannedSidecars: 60))
        let sample = telemetrySample(tMS: 0, capturedNS: 0, kind: .boundary, boundary: "session_start")

        let benchRoot = FileManager.default.temporaryDirectory
            .appendingPathComponent("sidecar-budget-bench-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: benchRoot) }
        let benchSink = GenerationTelemetryJSONLSink()
        await benchSink.useSidecarBudget(budget)
        for index in 0..<60 {
            await benchSink.persistRawSamples(
                [sample], generationID: "take-\(index)", appSupportDirectory: benchRoot, subdirectory: "engine"
            )
        }
        XCTAssertEqual(try sidecarCount(in: benchRoot), 60)

        let adHocRoot = FileManager.default.temporaryDirectory
            .appendingPathComponent("sidecar-budget-adhoc-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: adHocRoot) }
        let adHocSink = GenerationTelemetryJSONLSink()
        for index in 0..<60 {
            await adHocSink.persistRawSamples(
                [sample], generationID: "take-\(index)", appSupportDirectory: adHocRoot, subdirectory: "engine"
            )
        }
        XCTAssertEqual(try sidecarCount(in: adHocRoot), GenerationTelemetrySidecarBudget.adHoc.maxFiles)
    }

    /// A plan larger than one run can keep is refused before any model loads;
    /// a small plan never shrinks the ad-hoc budget; delivery cells and the
    /// TTFC probe count toward the plan.
    func testBenchRunSidecarBudgetRefusesAPlanItCannotKeep() throws {
        let ceiling = GenerationTelemetrySidecarBudget.maximumRunSidecarFiles
        XCTAssertNil(GenerationTelemetrySidecarBudget.benchRun(plannedSidecars: ceiling + 1))
        let largest = try XCTUnwrap(GenerationTelemetrySidecarBudget.benchRun(plannedSidecars: ceiling))
        XCTAssertEqual(largest.maxFiles, ceiling)
        XCTAssertGreaterThanOrEqual(
            largest.maxTotalBytes,
            ceiling * (GenerationTelemetrySidecarBudget.adHoc.maxTotalBytes / GenerationTelemetrySidecarBudget.adHoc.maxFiles)
        )
        XCTAssertEqual(
            GenerationTelemetrySidecarBudget.benchRun(plannedSidecars: 11),
            GenerationTelemetrySidecarBudget.adHoc
        )
        // Custom: cold + 3 warm + 3 delivery; Clone: 3 warm; one TTFC probe per mode.
        XCTAssertEqual(BenchMatrixSpec.plannedGenerationCount(
            modes: ["custom", "clone"],
            variantCount: 1,
            lengths: ["medium"],
            warm: 3,
            deliveryCellCount: 3,
            ttfcProbe: true
        ), 12)
        // A --no-cold delivery sweep (audit #104) plans no cold take.
        XCTAssertEqual(BenchMatrixSpec.plannedGenerationCount(
            modes: ["custom", "clone"],
            variantCount: 1,
            lengths: ["medium"],
            warm: 3,
            deliveryCellCount: 3,
            ttfcProbe: true,
            coldTakes: false
        ), 11)
    }

    private func sidecarCount(in appSupportDirectory: URL) throws -> Int {
        let directory = appSupportDirectory
            .appendingPathComponent("diagnostics", isDirectory: true)
            .appendingPathComponent("engine", isDirectory: true)
        return try FileManager.default.contentsOfDirectory(atPath: directory.path)
            .filter { $0.hasPrefix("samples-") && $0.hasSuffix(".jsonl") }
            .count
    }

    func testTransportAdapterPreservesGapAndTerminalSemantics() {
        let metrics = GenerationTelemetryCompatibilityAdapter.transport(
            finishReason: "cancelled",
            timingsMS: ["chunkForwardingSpanMS": 42],
            counters: ["chunksForwarded": 4, "chunkGaps": 1]
        )

        XCTAssertEqual(metrics.finishReason, .cancelled)
        XCTAssertEqual(metrics.cancellation, .completed)
        XCTAssertEqual(metrics.firstChunkToTerminalMS, 42)
        XCTAssertEqual(metrics.counters.chunksForwarded, 4)
        XCTAssertEqual(metrics.counters.chunkGaps, 1)
    }

    func testFrontendAdapterDoesNotRequireRawUserContent() {
        let metrics = GenerationTelemetryCompatibilityAdapter.frontend(
            timingsMS: [
                "submitToCompletedMS": 500,
                "playbackStartBufferedAudioMS": 600,
                "playbackMinimumQueuedAudioMS": 120,
            ],
            counters: [
                "uiStallCount50": 1,
                "playbackChunksReceived": 4,
                "playbackContinuityFailures": 1,
                "playbackUnderruns": 2,
                "playbackStartBufferedChunks": 3,
            ],
            playbackStartSource: .liveStream
        )

        XCTAssertEqual(metrics.submitToCompletedMS, 500)
        XCTAssertEqual(metrics.delayedHeartbeatCount50, 1)
        XCTAssertEqual(metrics.playbackChunksReceived, 4)
        XCTAssertEqual(metrics.playbackContinuityFailures, 1)
        XCTAssertEqual(metrics.playbackUnderruns, 2)
        XCTAssertEqual(metrics.playbackStartSource, .liveStream)
        XCTAssertEqual(metrics.playbackStartBufferedChunks, 3)
        XCTAssertEqual(metrics.playbackStartBufferedAudioMS, 600)
        XCTAssertEqual(metrics.playbackMinimumQueuedAudioMS, 120)
    }

    func testFrontendAdapterMarksTheCensoredHeartbeatDefinition() throws {
        let censored = GenerationTelemetryCompatibilityAdapter.frontend(
            timingsMS: [:],
            counters: ["maximumDelayedHeartbeatMS": 420, "censoredHeartbeatCount": 3]
        )
        XCTAssertEqual(censored.censoredHeartbeatCount, 3)
        XCTAssertEqual(
            censored.heartbeatDelayDefinition,
            FrontendGenerationMetrics.censoredHeartbeatDelayDefinition
        )
        let object = try XCTUnwrap(
            JSONSerialization.jsonObject(with: JSONEncoder().encode(censored)) as? [String: Any]
        )
        XCTAssertEqual(object["censoredHeartbeatCount"] as? Int, 3)
        XCTAssertEqual(object["heartbeatDelayDefinition"] as? String, "completedAndCensoredPending")

        // A legacy watchdog report (no censored count) keeps the old definition.
        let legacy = GenerationTelemetryCompatibilityAdapter.frontend(
            timingsMS: [:],
            counters: ["maximumDelayedHeartbeatMS": 120]
        )
        XCTAssertNil(legacy.censoredHeartbeatCount)
        XCTAssertNil(legacy.heartbeatDelayDefinition)
        let legacyObject = try XCTUnwrap(
            JSONSerialization.jsonObject(with: JSONEncoder().encode(legacy)) as? [String: Any]
        )
        XCTAssertNil(legacyObject["censoredHeartbeatCount"])
        XCTAssertNil(legacyObject["heartbeatDelayDefinition"])
    }

    func testPlaybackHealthTracksNormalDrainContinuityAndUnderrun() {
        var health = PlaybackHealthAccumulator()
        health.playbackScheduled(source: .liveStream, queuedChunks: 3, queuedAudioMS: 900)
        health.chunkReceived(queuedAudioMS: 1_200)
        health.queueDrained(queuedAudioMS: 600)
        health.queueDrained(queuedAudioMS: 250)
        health.continuityFailed()

        XCTAssertEqual(health.startBufferedChunks, 3)
        XCTAssertEqual(health.startBufferedAudioMS, 900)
        XCTAssertEqual(health.startSource, .liveStream)
        XCTAssertEqual(health.chunksReceived, 1)
        XCTAssertEqual(health.continuityFailures, 1)
        XCTAssertEqual(health.minimumQueuedAudioMS, 250)

        health.underrun()
        XCTAssertEqual(health.underruns, 1)
        XCTAssertEqual(health.minimumQueuedAudioMS, 0)
    }

    func testPlaybackHealthKeepsFinalFileBufferSemanticsDistinct() {
        var health = PlaybackHealthAccumulator()
        health.playbackScheduled(source: .finalFile, queuedChunks: 1, queuedAudioMS: 1_800)

        XCTAssertEqual(health.startSource, .finalFile)
        XCTAssertEqual(health.startBufferedChunks, 1)
        XCTAssertEqual(health.startBufferedAudioMS, 1_800)
        XCTAssertEqual(health.minimumQueuedAudioMS, 1_800)
    }

    func testFailurePrivacyAdapterDoesNotPersistRawMessageOrPath() {
        let sensitive = "failed for /Users/example/secret/reference.wav"
        let notes = GenerationTelemetryPrivacy.failureNotes(message: sensitive)

        XCTAssertEqual(notes["failureMessageLength"], String(sensitive.count))
        XCTAssertEqual(notes["failureMessageDigest"]?.count, 64)
        XCTAssertFalse(notes.values.contains(where: { $0.contains("secret") || $0.contains("/Users/") }))
    }

    func testSchemaV7UsesPlaybackScheduledNamesAndDecodesLegacyAudibleNames() throws {
        let legacy = """
        {
          "submitToFirstChunkMS": 10,
          "submitToFirstAudibleMS": 24,
          "firstChunkToAudibleMS": 14,
          "submitToCompletedMS": 80
        }
        """
        let decoded = try JSONDecoder().decode(FrontendGenerationMetrics.self, from: Data(legacy.utf8))
        XCTAssertEqual(decoded.submitToPlaybackScheduledMS, 24)
        XCTAssertEqual(decoded.firstChunkToPlaybackScheduledMS, 14)
        XCTAssertNil(decoded.playbackStartSource)

        let encoded = try JSONEncoder().encode(decoded)
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: encoded) as? [String: Any])
        XCTAssertEqual(object["submitToPlaybackScheduledMS"] as? Int, 24)
        XCTAssertEqual(object["firstChunkToPlaybackScheduledMS"] as? Int, 14)
        XCTAssertNil(object["submitToFirstAudibleMS"])
        XCTAssertNil(object["firstChunkToAudibleMS"])

        let sourced = FrontendGenerationMetrics(
            submitToPlaybackScheduledMS: 30,
            playbackStartSource: .finalFile,
            playbackStartBufferedChunks: 1,
            playbackStartBufferedAudioMS: 1_800
        )
        let sourcedData = try JSONEncoder().encode(sourced)
        let sourcedObject = try XCTUnwrap(
            JSONSerialization.jsonObject(with: sourcedData) as? [String: Any]
        )
        XCTAssertEqual(sourcedObject["playbackStartSource"] as? String, "finalFile")
        let sourcedRoundTrip = try JSONDecoder().decode(
            FrontendGenerationMetrics.self,
            from: sourcedData
        )
        XCTAssertEqual(sourcedRoundTrip.playbackStartSource, .finalFile)
        XCTAssertEqual(sourcedRoundTrip.playbackStartBufferedChunks, 1)
        XCTAssertEqual(sourcedRoundTrip.playbackStartBufferedAudioMS, 1_800)

        let record = GenerationTelemetryRecord(
            generationID: "v7-playback",
            layer: .app,
            recordedAt: "2026-07-12T00:00:00Z",
            timingsMS: [
                "submitToPlaybackScheduledMS": 30,
                "submitToFirstAudibleMS": 999,
                "firstChunkToPlaybackScheduledMS": 12,
            ]
        )
        XCTAssertEqual(record.frontendMetrics?.submitToPlaybackScheduledMS, 30)
        XCTAssertEqual(record.frontendMetrics?.firstChunkToPlaybackScheduledMS, 12)
    }

    func testV7SampleCadenceSummaryAndNanosecondDecoration() throws {
        let legacy = """
        {"tMS":5,"tNS":5000000,"actualElapsedNS":5100000,"threads":2}
        """
        let legacySample = try JSONDecoder().decode(TelemetrySample.self, from: Data(legacy.utf8))
        XCTAssertEqual(legacySample.capturedElapsedNS, 5_100_000)
        let encoded = try JSONEncoder().encode(legacySample)
        let encodedObject = try XCTUnwrap(JSONSerialization.jsonObject(with: encoded) as? [String: Any])
        XCTAssertNil(encodedObject["actualElapsedNS"])

        let samples = [
            telemetrySample(tMS: 0, capturedNS: 0, kind: .start),
            telemetrySample(tMS: 110, scheduledNS: 100_000_000, capturedNS: 110_000_000, latenessNS: 10_000_000, kind: .periodic),
            telemetrySample(tMS: 150, capturedNS: 150_000_000, kind: .boundary, boundary: "first_chunk"),
            telemetrySample(tMS: 230, scheduledNS: 200_000_000, capturedNS: 230_000_000, latenessNS: 30_000_000, kind: .periodic, captureSucceeded: false),
            telemetrySample(tMS: 240, capturedNS: 240_000_000, kind: .stop),
        ]
        let summary = NativeTelemetrySampler.summarize(
            samples: samples,
            stageMarks: [],
            targetIntervalNS: 100_000_000
        )
        XCTAssertEqual(summary.effectiveIntervalNS, 115_000_000)
        XCTAssertEqual(summary.maximumIntervalNS, 120_000_000)
        XCTAssertEqual(summary.maximumDriftNS, 30_000_000)
        XCTAssertEqual(summary.maximumLatenessNS, 30_000_000)
        XCTAssertEqual(summary.periodicSampleCount, 2)
        XCTAssertEqual(summary.boundarySampleCount, 1)
        XCTAssertEqual(summary.captureFailureCount, 1)
        XCTAssertEqual(summary.missedPeriodicDeadlineCount, 0)

        let decorated = NativeTelemetrySampler.decorate(
            samples: [
                telemetrySample(tMS: 10, capturedNS: 10_900_000, kind: .periodic),
                telemetrySample(tMS: 10, capturedNS: 10_100_000, kind: .periodic),
            ],
            stageMarks: [
                NativeTelemetryStageMark(tMS: 10, tNS: 10_500_000, sequence: 1, stage: "second"),
                NativeTelemetryStageMark(tMS: 10, tNS: 10_000_000, sequence: 0, stage: "first"),
            ]
        )
        XCTAssertEqual(decorated.map(\.capturedElapsedNS), [10_100_000, 10_900_000])
        XCTAssertEqual(decorated.map(\.stage), ["first", "second"])
    }

    func testDropoutThresholdsAreDurationCalibrated() {
        // A 1.4 s interior gap: hard "dropout" fail on short-form content
        // with no punctuation budget, warning-only when it consumes one real
        // script boundary, and within natural narration pacing on long content (2026-07-23
        // calibration from a retained failed-qc long-form segment whose gaps
        // position-correlated with sentence/comma boundaries).
        var limiter = PCM16StreamLimiter()
        var destination: [Int16] = []
        let sampleRate = 1_000
        limiter.append([0.2], into: &destination)
        limiter.append([Float](repeating: 0, count: 1_400), into: &destination)
        limiter.append([0.2], into: &destination)

        let unbudgetedShortForm = StreamingExecutionContext.makeAudioQCReport(
            metrics: limiter.metrics,
            sampleRate: sampleRate,
            durationSeconds: 10,
            expectedPauseCount: 0
        )
        XCTAssertEqual(unbudgetedShortForm.verdict, .fail)
        XCTAssertTrue(unbudgetedShortForm.flags.contains(where: { $0.hasPrefix("dropout:") }))

        let punctuationBudgetedShortForm = StreamingExecutionContext.makeAudioQCReport(
            metrics: limiter.metrics,
            sampleRate: sampleRate,
            durationSeconds: 10,
            expectedPauseCount: 1
        )
        XCTAssertEqual(punctuationBudgetedShortForm.verdict, .warn)
        XCTAssertTrue(punctuationBudgetedShortForm.flags.contains("dropout:1400ms"))

        let longContent = StreamingExecutionContext.makeAudioQCReport(
            metrics: limiter.metrics,
            sampleRate: sampleRate,
            durationSeconds: 60,
            expectedPauseCount: 8
        )
        XCTAssertNotEqual(longContent.verdict, .fail, "1.4 s narration pause must not hard-fail long content")

        // The egregious line still exists for long content: a 2.2 s gap fails.
        var deadAir = PCM16StreamLimiter()
        deadAir.append([0.2], into: &destination)
        deadAir.append([Float](repeating: 0, count: 2_200), into: &destination)
        deadAir.append([0.2], into: &destination)
        let longDeadAir = StreamingExecutionContext.makeAudioQCReport(
            metrics: deadAir.metrics,
            sampleRate: sampleRate,
            durationSeconds: 60,
            expectedPauseCount: 8
        )
        XCTAssertEqual(longDeadAir.verdict, .fail)
    }

    func testCloneLeadingSilenceGateDropsOnlyTheLongLeadingEdge() {
        let sampleRate = 1_000
        var gate = PCM16LeadingSilenceGate(
            policy: .cloneEdgeV1,
            sampleRate: sampleRate
        )

        XCTAssertTrue(gate.filter([Float](repeating: 0, count: 5_000)).isEmpty)
        let voiced = gate.filter([Float](repeating: 0.2, count: 100))

        XCTAssertEqual(voiced.count, 180)
        XCTAssertEqual(voiced.prefix(80), [Float](repeating: 0, count: 80)[...])
        XCTAssertEqual(voiced.suffix(100), [Float](repeating: 0.2, count: 100)[...])
        XCTAssertTrue(gate.metrics.opened)
        XCTAssertEqual(gate.metrics.trimmedSamples, 4_920)
        XCTAssertEqual(gate.metrics.retainedPreRollSamples, 80)
        XCTAssertLessThanOrEqual(gate.metrics.maximumBufferedSamples, 140)
    }

    func testCloneLeadingSilenceGatePreservesNaturalShortPreroll() {
        var gate = PCM16LeadingSilenceGate(
            policy: .cloneEdgeV1,
            sampleRate: 1_000
        )
        let samples = [Float](repeating: 0, count: 60)
            + [Float](repeating: 0.1, count: 100)

        let filtered = gate.filter(samples)

        XCTAssertEqual(filtered, samples)
        XCTAssertEqual(gate.metrics.trimmedSamples, 0)
        XCTAssertEqual(gate.metrics.retainedPreRollSamples, 60)
    }

    func testCloneLeadingSilenceGateIsBoundedForAnAllSilentClip() {
        var gate = PCM16LeadingSilenceGate(
            policy: .cloneEdgeV1,
            sampleRate: 1_000
        )

        XCTAssertTrue(gate.filter([Float](repeating: 0, count: 60_000)).isEmpty)
        XCTAssertFalse(gate.metrics.opened)
        XCTAssertLessThanOrEqual(gate.metrics.maximumBufferedSamples, 100)
    }

    func testCloneLeadingSilenceGateDoesNotLeakAcrossScratchBufferLeases() {
        let scratch = PCM16ScratchBuffer()
        scratch.configureLeadingSilenceGate(.cloneEdgeV1, sampleRate: 1_000)
        XCTAssertTrue(
            scratch.convertLimited([Float](repeating: 0, count: 1_000)).isEmpty
        )

        scratch.reset()
        scratch.configureLeadingSilenceGate(.cloneEdgeV1, sampleRate: 1_000)
        let immediateSpeech = [Float](repeating: 0.1, count: 100)
        let converted = scratch.convertLimited(immediateSpeech)

        XCTAssertEqual(converted.count, immediateSpeech.count)
        XCTAssertEqual(scratch.leadingSilenceMetrics.trimmedSamples, 0)
    }

    func testDisabledLeadingSilenceGateIsBitExact() {
        var gate = PCM16LeadingSilenceGate(policy: .disabled, sampleRate: 24_000)
        let samples: [Float] = [0, 0.001, -0.2, .nan, 0.5]

        let filtered = gate.filter(samples)

        XCTAssertEqual(filtered.count, samples.count)
        XCTAssertEqual(filtered[0 ... 2], samples[0 ... 2])
        XCTAssertTrue(filtered[3].isNaN)
        XCTAssertEqual(filtered[4], samples[4])
        XCTAssertNil(gate.metrics.algorithmVersion)
    }

    func testCodecReplayRangesPreserveRawChunksConsumedBeforeCloneOnset() {
        let rawRanges = [
            StartupReliabilityCodecFrameRange(start: 0, endExclusive: 25),
            StartupReliabilityCodecFrameRange(start: 25, endExclusive: 50),
            StartupReliabilityCodecFrameRange(start: 50, endExclusive: 75),
        ]

        let resolved = StreamingExecutionContext.codecReplayRanges(
            traceFrameCount: 75,
            observedRanges: rawRanges
        )

        XCTAssertEqual(resolved, rawRanges)
    }

    func testCodecReplayRangesFallBackWhenRawChunksAreIncomplete() {
        let resolved = StreamingExecutionContext.codecReplayRanges(
            traceFrameCount: 60,
            observedRanges: [
                StartupReliabilityCodecFrameRange(start: 25, endExclusive: 50),
            ]
        )

        XCTAssertEqual(
            resolved,
            [
                StartupReliabilityCodecFrameRange(start: 0, endExclusive: 25),
                StartupReliabilityCodecFrameRange(start: 25, endExclusive: 50),
                StartupReliabilityCodecFrameRange(start: 50, endExclusive: 60),
            ]
        )
    }

    func testOrdinaryCrossSpeakerCadencePausesWarnInsteadOfFailing() {
        // The full 9-speaker delivery screen observed this shape in 38 complete
        // outputs: several ordinary 350-800 ms pauses, but no 1.2 s dropout.
        // Fast QC is a gross-defect tripwire, so it must retain the evidence
        // without turning a cadence classification into a failed generation.
        var limiter = PCM16StreamLimiter()
        var destination: [Int16] = []
        let sampleRate = 24_000
        for pauseMS in [420, 510, 780] {
            limiter.append([Float](repeating: 0.2, count: 6_000), into: &destination)
            limiter.append(
                [Float](repeating: 0, count: pauseMS * sampleRate / 1_000),
                into: &destination
            )
        }
        limiter.append([Float](repeating: 0.2, count: 6_000), into: &destination)

        let report = StreamingExecutionContext.makeAudioQCReport(
            metrics: limiter.metrics,
            sampleRate: sampleRate,
            durationSeconds: 10,
            expectedPauseCount: 1
        )

        XCTAssertEqual(report.writtenOutputVerdict, .warn)
        XCTAssertTrue(report.flags.contains("cadence:excess2(3/1)"))
        XCTAssertFalse(report.flags.contains(where: { $0.hasPrefix("dropout:excess") }))
        let cadence = try? XCTUnwrap(report.cadence)
        XCTAssertEqual(cadence?.classification, .unusual)
        XCTAssertEqual(cadence?.reasons, [.excessCadencePauses])
        XCTAssertEqual(cadence?.expectedPauseCount, 1)
        XCTAssertEqual(cadence?.observedCadencePauseCount, 3)
        XCTAssertEqual(cadence?.excessCadencePauseCount, 2)
        XCTAssertEqual(cadence?.recordedInteriorPausesMS, [420, 510, 780])
        XCTAssertEqual(cadence?.totalInteriorSilenceMS, 1_710)
        XCTAssertEqual(cadence?.totalCadenceSilenceMS, 1_710)
        XCTAssertEqual(cadence?.medianCadencePauseMS, 510)
        XCTAssertEqual(cadence?.p90CadencePauseMS, 780)
        XCTAssertEqual(cadence?.cadenceSilenceRatio ?? 0, 0.171, accuracy: 0.000_001)
    }

    func testRepeatedSuspiciousGapsStillFailFastQC() {
        var limiter = PCM16StreamLimiter()
        var destination: [Int16] = []
        let sampleRate = 24_000
        for _ in 0..<2 {
            limiter.append([Float](repeating: 0.2, count: 6_000), into: &destination)
            limiter.append([Float](repeating: 0, count: 950 * sampleRate / 1_000), into: &destination)
        }
        limiter.append([Float](repeating: 0.2, count: 6_000), into: &destination)

        let report = StreamingExecutionContext.makeAudioQCReport(
            metrics: limiter.metrics,
            sampleRate: sampleRate,
            durationSeconds: 10,
            expectedPauseCount: 0
        )

        XCTAssertEqual(report.writtenOutputVerdict, .fail)
        XCTAssertTrue(report.flags.contains("dropout:excess2(2/0)"))
        XCTAssertEqual(report.cadence?.classification, .severe)
        XCTAssertEqual(
            report.cadence?.reasons,
            [.excessCadencePauses, .repeatedSuspiciousPauses]
        )
    }

    func testCrossChunkSilenceAndMergeCompleteness() throws {
        var limiter = PCM16StreamLimiter()
        var destination: [Int16] = []
        limiter.append([0.2, 0, 0], into: &destination)
        limiter.append([0, 0, 0.2], into: &destination)
        XCTAssertEqual(limiter.metrics.longestInteriorSilentRunSamples, 4)
        XCTAssertEqual(limiter.metrics.longestInteriorSilentRunStartSample, 1)
        let report = StreamingExecutionContext.makeAudioQCReport(
            metrics: limiter.metrics,
            sampleRate: 1_000,
            durationSeconds: 0.006,
            expectedPauseCount: 0
        )
        XCTAssertEqual(report.algorithmVersion, 8)
        XCTAssertEqual(report.longestSilenceMS, 4)
        XCTAssertEqual(report.longestSilenceStartMS, 1)

        let app = GenerationTelemetryRecord(
            generationID: "merge",
            layer: .app,
            recordedAt: "2026-07-12T00:00:00Z"
        )
        let merged = MergedGenerationTelemetry(
            generationID: "merge",
            recordedAt: "2026-07-12T00:00:01Z",
            app: app,
            engineService: nil,
            engine: nil
        )
        XCTAssertFalse(merged.complete)
        // Both hosts run the engine in-process: app + engine is the complete set.
        XCTAssertEqual(merged.missingLayers, [.engine])
        let roundTrip = try JSONDecoder().decode(
            MergedGenerationTelemetry.self,
            from: JSONEncoder().encode(merged)
        )
        XCTAssertEqual(roundTrip.missingLayers, [.engine])
    }

    func testEgregiousTerminalSilenceFailsBeforePublication() {
        var limiter = PCM16StreamLimiter()
        var destination: [Int16] = []
        limiter.append([Float](repeating: 0.2, count: 500), into: &destination)
        limiter.append([Float](repeating: 0, count: 2_200), into: &destination)

        let report = StreamingExecutionContext.makeAudioQCReport(
            metrics: limiter.metrics,
            sampleRate: 1_000,
            durationSeconds: 2.7,
            expectedPauseCount: 1
        )

        XCTAssertEqual(report.writtenOutputVerdict, .fail)
        XCTAssertEqual(report.trailingSilenceMS, 2_200)
        XCTAssertEqual(report.trailingSilenceStartMS, 500)
        XCTAssertTrue(report.flags.contains("terminal_silence:2200ms"))
        XCTAssertEqual(report.cadence?.classification, .severe)
        XCTAssertEqual(report.cadence?.reasons, [.egregiousTerminalSilence])
    }

    func testOrdinaryTerminalPaddingRemainsAccepted() {
        var limiter = PCM16StreamLimiter()
        var destination: [Int16] = []
        let voiced = (0..<500).map { index in
            Float(sin(2 * Double.pi * 10 * Double(index) / 1_000) * 0.2)
        }
        limiter.append(voiced, into: &destination)
        limiter.append([Float](repeating: 0, count: 268), into: &destination)

        let report = StreamingExecutionContext.makeAudioQCReport(
            metrics: limiter.metrics,
            sampleRate: 1_000,
            durationSeconds: 0.768,
            expectedPauseCount: 0
        )

        XCTAssertEqual(report.verdict, .pass)
        XCTAssertEqual(report.trailingSilenceMS, 268)
        XCTAssertEqual(report.trailingSilenceStartMS, 500)
        XCTAssertFalse(report.flags.contains(where: { $0.hasPrefix("terminal_silence:") }))
    }

    func testExpectedPauseCountRecognizesCJKPunctuation() {
        XCTAssertEqual(
            StreamingExecutionContext.expectedPauseCount(
                in: "今日は天気がよく、赤い列車が駅を出発します。"
            ),
            1
        )
        XCTAssertEqual(
            StreamingExecutionContext.expectedPauseCount(
                in: "今天天气很好，红色的火车准时离开车站。"
            ),
            1
        )
        XCTAssertEqual(
            StreamingExecutionContext.expectedPauseCount(
                in: "最初の文です！次の文です？最後の文です。"
            ),
            2
        )
    }

    func testAudioQCSplitsInputInstabilityFromWrittenOutputDefects() throws {
        var unstableLimiter = PCM16StreamLimiter()
        var unstableDestination: [Int16] = []
        unstableLimiter.append(
            [0.2, .nan, .infinity, 1.2, -1.2, 0.2],
            into: &unstableDestination
        )
        let unstableReport = StreamingExecutionContext.makeAudioQCReport(
            metrics: unstableLimiter.metrics,
            sampleRate: 24_000,
            durationSeconds: Double(unstableDestination.count) / 24_000,
            expectedPauseCount: 0
        )
        XCTAssertEqual(unstableLimiter.metrics.nonFiniteSamples, 2)
        XCTAssertEqual(unstableLimiter.metrics.samplesOutsideUnitRange, 2)
        XCTAssertGreaterThan(unstableLimiter.metrics.slewLimitedSamples, 0)
        XCTAssertEqual(unstableReport.instabilityVerdict, .fail)
        XCTAssertEqual(unstableReport.verdict, .fail)

        var dcLimiter = PCM16StreamLimiter()
        var dcDestination: [Int16] = []
        dcLimiter.append(Array(repeating: Float(0.1), count: 1_000), into: &dcDestination)
        let dcReport = StreamingExecutionContext.makeAudioQCReport(
            metrics: dcLimiter.metrics,
            sampleRate: 1_000,
            durationSeconds: 1,
            expectedPauseCount: 0
        )
        XCTAssertEqual(dcReport.instabilityVerdict, .pass)
        XCTAssertEqual(dcReport.writtenOutputVerdict, .warn)
        XCTAssertEqual(dcReport.verdict, .warn)
        XCTAssertEqual(try XCTUnwrap(dcReport.dcOffset), 0.1, accuracy: 0.000_001)

        let legacy = """
        {
          "verdict":"warn","flags":[],"rmsDBFS":-20,"peak":0.1,
          "clippedSamples":0,"hotSamples":0,"nonFiniteSamples":0,
          "clickEvents":0,"longestSilenceMS":0,"durationSeconds":1
        }
        """
        let decoded = try JSONDecoder().decode(AudioQCReport.self, from: Data(legacy.utf8))
        XCTAssertEqual(decoded.algorithmVersion, 1)
        XCTAssertEqual(decoded.instabilityVerdict, .warn)
        XCTAssertEqual(decoded.writtenOutputVerdict, .warn)
        XCTAssertNil(decoded.cadence)
    }

    func testSamplerStopIsIdempotentAcrossTerminalCleanup() async {
        let sampler = NativeTelemetrySampler(
            clock: NativeTelemetryClock(),
            sampleIntervalMS: 60_000
        )
        await sampler.start()
        await sampler.captureBoundary("before_model_load")
        let first = await sampler.stop(stageMarks: [])
        let second = await sampler.stop(stageMarks: [])

        XCTAssertEqual(first.summary, second.summary)
        XCTAssertEqual(first.samples, second.samples)
        XCTAssertEqual(first.samples.count(where: { $0.kind == .stop }), 1)
        XCTAssertEqual(first.summary.boundarySampleCount, 1)
    }

    func testSamplerKeepsAnchoredPhaseAndCountsSkippedDeadlines() {
        let onTime = NativeTelemetrySampler.nextPeriodicSchedule(
            after: 100,
            capturedElapsedNS: 110,
            intervalNanos: 100
        )
        XCTAssertEqual(onTime.nextScheduledElapsedNS, 200)
        XCTAssertEqual(onTime.missedDeadlines, 0)

        let late = NativeTelemetrySampler.nextPeriodicSchedule(
            after: 100,
            capturedElapsedNS: 450,
            intervalNanos: 100
        )
        XCTAssertEqual(late.nextScheduledElapsedNS, 500)
        XCTAssertEqual(late.missedDeadlines, 3)
    }

    func testSamplerStopCapturesOnlyNewestDueDeadlineAndKeepsOlderMisses() {
        let tailRace = NativeTelemetrySampler.periodicStopAdjustment(
            startElapsedNS: 0,
            stopElapsedNS: 2_001_000_000,
            intervalNanos: 500_000_000,
            periodicSampleCount: 3,
            missedDeadlineCount: 0
        )
        XCTAssertEqual(tailRace.scheduledElapsedNS, 2_000_000_000)
        XCTAssertEqual(tailRace.additionalMissedDeadlines, 0)

        let starved = NativeTelemetrySampler.periodicStopAdjustment(
            startElapsedNS: 0,
            stopElapsedNS: 3_001_000_000,
            intervalNanos: 500_000_000,
            periodicSampleCount: 1,
            missedDeadlineCount: 0
        )
        XCTAssertEqual(starved.scheduledElapsedNS, 3_000_000_000)
        XCTAssertEqual(starved.additionalMissedDeadlines, 4)

        let complete = NativeTelemetrySampler.periodicStopAdjustment(
            startElapsedNS: 0,
            stopElapsedNS: 2_001_000_000,
            intervalNanos: 500_000_000,
            periodicSampleCount: 4,
            missedDeadlineCount: 0
        )
        XCTAssertNil(complete.scheduledElapsedNS)
        XCTAssertEqual(complete.additionalMissedDeadlines, 0)
    }

    func testBoundarySampleCanOwnTheMemoryPeak() {
        let samples = [
            telemetrySample(tMS: 0, capturedNS: 0, kind: .start, residentMB: 100),
            telemetrySample(
                tMS: 20,
                capturedNS: 20_000_000,
                kind: .boundary,
                boundary: "after_model_load",
                residentMB: 350
            ),
            telemetrySample(tMS: 100, capturedNS: 100_000_000, kind: .periodic, residentMB: 180),
        ]
        let summary = NativeTelemetrySampler.summarize(
            samples: samples,
            stageMarks: [],
            targetIntervalNS: 100_000_000
        )
        XCTAssertEqual(summary.residentPeakMB, 350)
        XCTAssertEqual(summary.timeToPeakMS, 20)
        XCTAssertEqual(summary.boundarySampleCount, 1)
    }

    func testTerminalClassifierDefersOnlyFirstRetryableAllocationFailure() {
        let allocation = VocelloQwen3RuntimeFailure.allocation
        XCTAssertTrue(NativeGenerationTerminalClassifier.isRetryableAllocationFailure(allocation))
        XCTAssertFalse(
            NativeGenerationTerminalClassifier.shouldPublish(
                error: allocation,
                policy: .deferRetryableAllocationFailure
            )
        )
        XCTAssertTrue(
            NativeGenerationTerminalClassifier.shouldPublish(
                error: allocation,
                policy: .publish
            )
        )

        let cancellation = CancellationError()
        XCTAssertEqual(NativeGenerationTerminalClassifier.reason(for: cancellation), .cancelled)
        XCTAssertFalse(NativeGenerationTerminalClassifier.isRetryableAllocationFailure(cancellation))
        XCTAssertTrue(
            NativeGenerationTerminalClassifier.shouldPublish(
                error: cancellation,
                policy: .deferRetryableAllocationFailure
            )
        )
    }

    func testTerminalClassifierRecognizesEveryTypedCancellation() {
        let cancellations: [Error] = [
            CancellationError(),
            VocelloQwen3SessionError.audioChannelCancelled(.memoryPressure),
            AudioPreparationError.cancelled,
            HuggingFaceDownloader.DownloadError.cancelled,
            URLError(.cancelled),
            CocoaError(.userCancelled),
            RemoteErrorPayload.make(for: CancellationError()),
            NativeRuntimeError.wrapping(
                CancellationError(),
                stage: .clonePreparation,
                message: "The native runtime could not prepare the clone reference"
            ),
            NativeRuntimeError.wrapping(
                VocelloQwen3SessionError.audioChannelCancelled(.user),
                stage: .streamStartup,
                message: "The native runtime could not start audio generation."
            ),
        ]
        for error in cancellations {
            XCTAssertEqual(
                NativeGenerationTerminalClassifier.reason(for: error),
                .cancelled,
                "\(error)"
            )
            XCTAssertFalse(NativeGenerationTerminalClassifier.isRetryableAllocationFailure(error))
            XCTAssertEqual(NativeTelemetryTerminalBoundary.name(for: error), "terminal_cancelled")
        }
    }

    func testTerminalClassifierIgnoresErrorText() {
        // Text that the retired string matcher treated as a cancellation or as a
        // retryable Metal allocation failure is an ordinary failure unless the
        // error's type says otherwise.
        let cancelledText = NSError(
            domain: "Vocello",
            code: 1,
            userInfo: [NSLocalizedDescriptionKey: "The request was cancelled"]
        )
        let allocationText = NSError(
            domain: "MLX",
            code: 1,
            userInfo: [NSLocalizedDescriptionKey: "Metal failed to allocate GPU memory"]
        )
        let reworded = MLXTTSEngineError.generationFailed("Out of memory on the GPU (cancelled).")
        for error in [cancelledText, allocationText, reworded] as [Error] {
            XCTAssertEqual(NativeGenerationTerminalClassifier.reason(for: error), .failed, "\(error)")
            XCTAssertFalse(
                NativeGenerationTerminalClassifier.isRetryableAllocationFailure(error),
                "\(error)"
            )
        }
    }

    func testTypedAllocationFailureSurvivesWrappingAndDrivesTheSingleRetry() {
        let wrappedAllocation = NativeRuntimeError.wrapping(
            VocelloQwen3RuntimeFailure.allocation,
            stage: .upstreamModelLoad,
            message: "The native runtime could not load model 'pro_custom'"
        )
        XCTAssertEqual(wrappedAllocation.underlyingDisposition, .allocationFailure)
        XCTAssertTrue(NativeGenerationTerminalClassifier.isRetryableAllocationFailure(wrappedAllocation))
        XCTAssertEqual(NativeGenerationTerminalClassifier.reason(for: wrappedAllocation), .failed)
        XCTAssertFalse(
            NativeGenerationTerminalClassifier.shouldPublish(
                error: wrappedAllocation,
                policy: .deferRetryableAllocationFailure
            )
        )

        // A non-allocation MLX error fails the take without the retry.
        let mlxFailure = VocelloQwen3RuntimeFailure.mlx
        XCTAssertFalse(NativeGenerationTerminalClassifier.isRetryableAllocationFailure(mlxFailure))
        XCTAssertEqual(NativeGenerationTerminalClassifier.reason(for: mlxFailure), .failed)
        XCTAssertTrue(
            NativeGenerationTerminalClassifier.shouldPublish(
                error: mlxFailure,
                policy: .deferRetryableAllocationFailure
            )
        )

        // The surfaced error after the retry keeps the typed disposition too.
        let surfaced = MLXTTSEngine.surfacedGenerationError(
            VocelloQwen3RuntimeFailure.allocation,
            allocationRetryAttempted: true
        )
        XCTAssertEqual(surfaced.underlyingDisposition, .allocationFailure)
    }

    func testMemoryPressureTerminalOutcomeIsRetryableOnlyBeforeAudioWasEmitted() {
        let beforeAudio = GenerationOutputAdapter.productError(
            for: .failed(.memoryPressure),
            emittedAudioFrameCount: 0
        )
        XCTAssertTrue(NativeGenerationTerminalClassifier.isRetryableAllocationFailure(beforeAudio))
        XCTAssertEqual((beforeAudio as? NativeRuntimeError)?.failureCode, .memoryPressure)

        let afterAudio = GenerationOutputAdapter.productError(
            for: .failed(.memoryPressure),
            emittedAudioFrameCount: 1_920
        )
        XCTAssertFalse(NativeGenerationTerminalClassifier.isRetryableAllocationFailure(afterAudio))
        XCTAssertEqual(NativeGenerationTerminalClassifier.reason(for: afterAudio), .failed)
        XCTAssertEqual((afterAudio as? NativeRuntimeError)?.failureCode, .memoryPressure)

        let runtime = GenerationOutputAdapter.productError(
            for: .failed(.runtime),
            emittedAudioFrameCount: 0
        )
        XCTAssertFalse(NativeGenerationTerminalClassifier.isRetryableAllocationFailure(runtime))
        XCTAssertEqual(NativeGenerationTerminalClassifier.reason(for: runtime), .failed)

        let cancelled = GenerationOutputAdapter.productError(
            for: .cancelled(.superseded),
            emittedAudioFrameCount: 0
        )
        XCTAssertEqual(NativeGenerationTerminalClassifier.reason(for: cancelled), .cancelled)
    }

    func testStreamAllocationFailureRetriesOnlyBeforeAnyFrameWasPublished() {
        let beforeAudio = StreamingExecutionContext.streamFailureError(
            VocelloQwen3RuntimeFailure.allocation,
            totalFramesWritten: 0,
            isTaskCancelled: false
        )
        XCTAssertTrue(NativeGenerationTerminalClassifier.isRetryableAllocationFailure(beforeAudio))

        // A mid-stream talker allocation failure after preview audio was
        // published must not re-run the take under the same generation ID.
        let midStream = StreamingExecutionContext.streamFailureError(
            VocelloQwen3RuntimeFailure.allocation,
            totalFramesWritten: 24_000,
            isTaskCancelled: false
        )
        XCTAssertFalse(NativeGenerationTerminalClassifier.isRetryableAllocationFailure(midStream))
        XCTAssertEqual(NativeGenerationTerminalClassifier.reason(for: midStream), .failed)
        let midStreamError = midStream as? NativeRuntimeError
        XCTAssertEqual(midStreamError?.failureCode, .memoryPressure)
        XCTAssertEqual(
            midStreamError?.telemetryNotes["nativeRuntimeFailureCode"],
            "runtime.memory_pressure"
        )
        XCTAssertFalse(
            NativeGenerationTerminalClassifier.shouldPublish(
                error: beforeAudio,
                policy: .deferRetryableAllocationFailure
            )
        )
        XCTAssertTrue(
            NativeGenerationTerminalClassifier.shouldPublish(
                error: midStream,
                policy: .deferRetryableAllocationFailure
            )
        )

        let mlxFailure = StreamingExecutionContext.streamFailureError(
            VocelloQwen3RuntimeFailure.mlx,
            totalFramesWritten: 0,
            isTaskCancelled: false
        )
        XCTAssertFalse(NativeGenerationTerminalClassifier.isRetryableAllocationFailure(mlxFailure))

        // Other errors pass through untouched, cancellation included.
        let cancellation = StreamingExecutionContext.streamFailureError(
            CancellationError(),
            totalFramesWritten: 24_000,
            isTaskCancelled: false
        )
        XCTAssertTrue(cancellation is CancellationError)
    }

    func testStreamFailureOfCancelledTaskIsCancellationNeverRetried() {
        for framesWritten: Int64 in [0, 24_000] {
            let cancelled = StreamingExecutionContext.streamFailureError(
                VocelloQwen3RuntimeFailure.allocation,
                totalFramesWritten: framesWritten,
                isTaskCancelled: true
            )
            XCTAssertTrue(cancelled is CancellationError)
            XCTAssertEqual(NativeGenerationTerminalClassifier.reason(for: cancelled), .cancelled)
            XCTAssertFalse(NativeGenerationTerminalClassifier.isRetryableAllocationFailure(cancelled))
        }
    }

    func testCancellationWinsTheGenerationTerminal() {
        let allocation = VocelloQwen3RuntimeFailure.allocation
        XCTAssertTrue(
            MLXTTSEngine.isCancelledGenerationTerminal(
                allocation,
                cancellationReason: .memoryPressure,
                isTaskCancelled: false
            )
        )
        XCTAssertTrue(
            MLXTTSEngine.isCancelledGenerationTerminal(
                allocation,
                cancellationReason: nil,
                isTaskCancelled: true
            )
        )
        XCTAssertTrue(
            MLXTTSEngine.isCancelledGenerationTerminal(
                CancellationError(),
                cancellationReason: nil,
                isTaskCancelled: false
            )
        )
        XCTAssertFalse(
            MLXTTSEngine.isCancelledGenerationTerminal(
                allocation,
                cancellationReason: nil,
                isTaskCancelled: false
            )
        )
        XCTAssertFalse(
            MLXTTSEngine.isCancelledGenerationTerminal(
                MLXTTSEngineError.generationFailed("The native engine did not emit any audio chunks."),
                cancellationReason: nil,
                isTaskCancelled: false
            )
        )
    }

    func testPublicationMarkingFailureIsNeverRetried() {
        let marking = StreamingExecutionContext.publicationMarkingError(
            VocelloQwen3RuntimeFailure.allocation
        )
        XCTAssertFalse(NativeGenerationTerminalClassifier.isRetryableAllocationFailure(marking))
        XCTAssertEqual(NativeGenerationTerminalClassifier.reason(for: marking), .failed)
        XCTAssertEqual((marking as? NativeRuntimeError)?.failureCode, .memoryPressure)

        let sampleCount = MLXTTSEngineError.generationFailed("Audio marking changed the sample count.")
        let passthrough = StreamingExecutionContext.publicationMarkingError(sampleCount)
        XCTAssertEqual(passthrough as? MLXTTSEngineError, sampleCount)
        XCTAssertFalse(NativeGenerationTerminalClassifier.isRetryableAllocationFailure(passthrough))
    }

    func testCapturedRuntimeFailureHasProductCopyAndMemoryClassification() {
        for failure in [VocelloQwen3RuntimeFailure.allocation, .mlx] {
            let surfaced = MLXTTSEngine.surfacedGenerationError(
                failure,
                allocationRetryAttempted: false
            )
            let message = surfaced.localizedDescription
            XCTAssertFalse(message.contains("VocelloQwen3RuntimeFailure"), message)
            XCTAssertFalse(message.contains("error 0"), message)
            XCTAssertFalse(message.isEmpty)
        }
        let allocation = NativeRuntimeError.capturedRuntimeFailure(
            .allocation,
            stage: .streamFailed,
            audioPublished: true
        )
        let metadata = GenerationFailureDiagnosticLogger.errorMetadata(for: allocation)
        XCTAssertEqual(metadata.code, "runtime.memory_pressure")
        XCTAssertEqual(metadata.classification, .memory)
    }

    func testCapturedRuntimeFailureRequiresModelUnload() {
        XCTAssertTrue(MLXTTSEngine.requiresUnloadAfterFailure(VocelloQwen3RuntimeFailure.allocation))
        XCTAssertTrue(MLXTTSEngine.requiresUnloadAfterFailure(VocelloQwen3RuntimeFailure.mlx))
        XCTAssertTrue(
            MLXTTSEngine.requiresUnloadAfterFailure(
                StreamingExecutionContext.streamFailureError(
                    VocelloQwen3RuntimeFailure.allocation,
                    totalFramesWritten: 24_000,
                    isTaskCancelled: false
                )
            )
        )
        XCTAssertTrue(
            MLXTTSEngine.requiresUnloadAfterFailure(
                MLXTTSEngine.surfacedGenerationError(
                    VocelloQwen3RuntimeFailure.mlx,
                    allocationRetryAttempted: true
                )
            )
        )
        XCTAssertFalse(MLXTTSEngine.requiresUnloadAfterFailure(CancellationError()))
        XCTAssertFalse(MLXTTSEngine.requiresUnloadAfterFailure(NativeRuntimeError.maximumTokenLimit()))
        XCTAssertFalse(
            MLXTTSEngine.requiresUnloadAfterFailure(
                MLXTTSEngineError.generationFailed("The native engine did not emit any audio chunks.")
            )
        )
    }

    func testStreamingPostLoopClassifiesCancellationBeforeEmptyOutput() {
        let cancelledEmptyStream = StreamingExecutionContext.postStreamTerminalError(
            totalFramesWritten: 0,
            isTaskCancelled: true
        )
        XCTAssertNotNil(cancelledEmptyStream)
        XCTAssertEqual(
            cancelledEmptyStream.map(NativeGenerationTerminalClassifier.reason(for:)),
            .cancelled
        )
        let cancelledPartialStream = StreamingExecutionContext.postStreamTerminalError(
            totalFramesWritten: 1,
            isTaskCancelled: true
        )
        XCTAssertEqual(
            cancelledPartialStream.map(NativeGenerationTerminalClassifier.reason(for:)),
            .cancelled
        )

        let failedEmptyStream = StreamingExecutionContext.postStreamTerminalError(
            totalFramesWritten: 0,
            isTaskCancelled: false
        )
        XCTAssertNotNil(failedEmptyStream)
        XCTAssertEqual(
            failedEmptyStream.map(NativeGenerationTerminalClassifier.reason(for:)),
            .failed
        )
        XCTAssertEqual(
            failedEmptyStream?.localizedDescription,
            "The native engine did not emit any audio chunks."
        )

        XCTAssertNil(
            StreamingExecutionContext.postStreamTerminalError(
                totalFramesWritten: 1,
                isTaskCancelled: false
            )
        )
    }

    func testTerminalGateAllowsExactlyOneDurableRowPerAttempt() async {
        let gate = NativeTelemetryTerminalGate()
        async let first = gate.claim()
        async let second = gate.claim()
        async let third = gate.claim()
        let results = await [first, second, third]
        XCTAssertEqual(results.count(where: { $0 }), 1)
    }

    func testTerminalBoundaryCoversNonEOSCancellationAndSetupFailure() {
        XCTAssertEqual(
            NativeTelemetryTerminalBoundary.name(for: GenerationFinishReason.maxTokens),
            "terminal_failure"
        )
        XCTAssertEqual(
            NativeTelemetryTerminalBoundary.name(for: GenerationFinishReason.failed),
            "terminal_failure"
        )
        XCTAssertEqual(
            NativeTelemetryTerminalBoundary.name(for: GenerationFinishReason.cancelled),
            "terminal_cancelled"
        )
        XCTAssertEqual(
            NativeTelemetryTerminalBoundary.name(for: CancellationError()),
            "terminal_cancelled"
        )
        XCTAssertEqual(
            NativeTelemetryTerminalBoundary.name(
                for: NSError(domain: "session-directory", code: 1)
            ),
            "terminal_failure"
        )
    }

    func testModelIdentityQuantizationUsesTypedRuntimeTier() {
        XCTAssertEqual(MLXModelLoadCoordinator.telemetryQuantization(for: .fourBit), "4-bit")
        XCTAssertEqual(MLXModelLoadCoordinator.telemetryQuantization(for: .eightBit), "8-bit")
        XCTAssertEqual(MLXModelLoadCoordinator.telemetryQuantization(for: .unknown), "unquantized")
    }

    func testProcessResourceDeltaClampsCounterResets() {
        let start = processResourceSnapshot(cpu: 20, counters: 10)
        let end = processResourceSnapshot(cpu: 25, counters: 5)
        let delta = ProcessResourceUsageDelta(start: start, end: end)
        XCTAssertEqual(delta.userCPUTimeMS, 5)
        XCTAssertEqual(delta.systemCPUTimeMS, 5)
        XCTAssertEqual(delta.minorPageFaults, 0)
        XCTAssertEqual(delta.involuntaryContextSwitches, 0)

        let environment = RunEnvironmentSnapshot.capture()
        XCTAssertGreaterThan(environment.uptimeSeconds, 0)
        XCTAssertGreaterThanOrEqual(environment.loadAverage1Minute ?? 0, 0)
        XCTAssertFalse(environment.thermalState.isEmpty)
        XCTAssertNotNil(environment.runtimeDebugProvenance)
    }

    private func telemetrySample(
        tMS: Int,
        scheduledNS: UInt64? = nil,
        capturedNS: UInt64,
        latenessNS: UInt64? = nil,
        kind: TelemetrySampleKind,
        boundary: String? = nil,
        captureSucceeded: Bool = true,
        residentMB: Double = 100
    ) -> TelemetrySample {
        TelemetrySample(
            tMS: tMS,
            tNS: capturedNS,
            scheduledElapsedNS: scheduledNS,
            capturedElapsedNS: capturedNS,
            latenessNS: latenessNS,
            kind: kind,
            boundary: boundary,
            captureSucceeded: captureSucceeded,
            residentMB: residentMB,
            physFootprintMB: residentMB,
            compressedMB: 0,
            headroomMB: 500,
            gpuAllocatedMB: 25,
            gpuRecommendedWorkingSetMB: 1_000,
            threads: 4,
            thermalState: "nominal"
        )
    }

    private func processResourceSnapshot(cpu: Double, counters: Int64) -> ProcessResourceUsageSnapshot {
        ProcessResourceUsageSnapshot(
            userCPUTimeMS: cpu,
            systemCPUTimeMS: cpu,
            minorPageFaults: counters,
            majorPageFaults: counters,
            voluntaryContextSwitches: counters,
            involuntaryContextSwitches: counters,
            blockInputOperations: counters,
            blockOutputOperations: counters
        )
    }

    // MARK: - Standard real-time factor

    func testRequestWallSecondsSpansTheRequestMinusStartupStages() {
        func mark(_ stage: String, _ tMS: Int) -> NativeTelemetryStageMark {
            NativeTelemetryStageMark(tMS: tMS, stage: stage)
        }
        let marks = [
            mark("startup.request_validated", 0),
            mark("startup.model_load_started", 20),
            mark("startup.model_loaded", 1_520),
            mark("startup.prewarm_started", 1_530),
            mark("startup.prewarm_completed", 2_030),
            mark(NativeRuntimeStage.streamStartup.rawValue, 2_100),
            mark(NativeRuntimeStage.streamGenerationEnded.rawValue, 7_900),
            mark(NativeRuntimeStage.streamCompleted.rawValue, 8_030),
        ]
        // 8 030 ms total, minus 1 500 ms of model load and 500 ms of prewarm.
        XCTAssertEqual(GenerationOutputAdapter.requestWallSeconds(stageMarks: marks), 6.03)
    }

    func testRequestWallSecondsFallsBackToGenerationEndedAndRefusesEmptyTimelines() {
        let withoutCompletion = [
            NativeTelemetryStageMark(tMS: 0, stage: "startup.request_validated"),
            NativeTelemetryStageMark(tMS: 4_000, stage: NativeRuntimeStage.streamGenerationEnded.rawValue),
        ]
        XCTAssertEqual(GenerationOutputAdapter.requestWallSeconds(stageMarks: withoutCompletion), 4.0)
        XCTAssertNil(GenerationOutputAdapter.requestWallSeconds(stageMarks: []))
        XCTAssertNil(GenerationOutputAdapter.requestWallSeconds(stageMarks: [
            NativeTelemetryStageMark(tMS: 0, stage: NativeRuntimeStage.streamCompleted.rawValue),
        ]))
    }
}
