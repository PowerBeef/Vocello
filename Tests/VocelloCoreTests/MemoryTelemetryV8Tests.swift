import Foundation
@testable import QwenVoiceCore
import XCTest

final class MemoryTelemetryV8Tests: XCTestCase {
    func testBenchRunContextCurrentTakeFileRoundTripsAndClears() throws {
        BenchRunContext.clearCurrentTakeFile()
        defer { BenchRunContext.clearCurrentTakeFile() }

        try BenchRunContext.writeCurrentTakeFile(
            takeIndex: 7,
            cell: "clone/speed/medium/retained#2",
            intendedWarmState: "warm"
        )

        XCTAssertEqual(
            BenchRunContext.currentTakeFileNotes(),
            [
                "benchTakeIndex": "7",
                "benchCell": "clone/speed/medium/retained#2",
                "benchWarmState": "warm",
            ]
        )
        #if os(macOS)
        XCTAssertEqual(
            BenchRunContext.currentTakeFileURL.path,
            "/tmp/vocello-bench-current-take.json"
        )
        #endif

        BenchRunContext.clearCurrentTakeFile()
        XCTAssertNil(BenchRunContext.currentTakeFileNotes())
    }

    func testSchemaV7RowDecodesWithoutV8MemoryPayload() throws {
        let json = """
        {
          "schemaVersion": 7,
          "generationID": "legacy-v7",
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

        XCTAssertEqual(decoded.schemaVersion, 7)
        XCTAssertNil(decoded.memoryMetrics)
        XCTAssertNil(decoded.summary)
    }

    func testSummarySeparatesCaptureFamiliesAndKeepsAlignedBudgetSamples() {
        let samples = [
            sample(
                tMS: 0,
                kind: .start,
                footprint: 100,
                headroom: 500,
                gpu: 10,
                threadSucceeded: false
            ),
            sample(
                tMS: 5,
                kind: .boundary,
                boundary: "required",
                footprint: 145,
                headroom: 455,
                gpu: 40
            ),
            sample(
                tMS: 10,
                kind: .periodic,
                footprint: nil,
                headroom: nil,
                gpu: nil,
                memorySucceeded: false
            ),
            sample(
                tMS: 15,
                kind: .stop,
                footprint: 120,
                headroom: 480,
                gpu: 20
            ),
        ]
        let resource = ProcessResourceUsageDelta(
            userCPUTimeMS: 1,
            systemCPUTimeMS: 2,
            minorPageFaults: 3,
            majorPageFaults: 0,
            voluntaryContextSwitches: 4,
            involuntaryContextSwitches: 1,
            blockInputOperations: 0,
            blockOutputOperations: 0
        )

        let summary = NativeTelemetrySampler.summarize(
            samples: samples,
            stageMarks: [],
            targetIntervalNS: 5_000_000,
            processResourceUsage: resource,
            boundaryRequirements: [
                TelemetryBoundaryRequirement(name: "required-boundary", alternatives: ["required"]),
            ]
        )

        XCTAssertEqual(summary.processRole, .engine)
        XCTAssertEqual(summary.physFootprintStartMB, 100)
        XCTAssertEqual(summary.physFootprintEndMB, 120)
        XCTAssertEqual(summary.physFootprintPeakMB, 145)
        XCTAssertEqual(summary.physFootprintDeltaMB, 20)
        XCTAssertEqual(summary.headroomMinMB, 455)
        XCTAssertEqual(summary.memoryAtPeakPhysFootprint?.headroomMB, 455)
        XCTAssertEqual(summary.memoryAtMinimumHeadroom?.physFootprintMB, 145)
        XCTAssertEqual(summary.memoryAtPeakPhysFootprint?.gpuWorkingSetUsageRatio, 0.4)
        XCTAssertEqual(summary.captureCoverage?.memorySuccessfulSampleCount, 3)
        XCTAssertEqual(summary.captureCoverage?.memoryCaptureFailureCount, 1)
        XCTAssertEqual(summary.captureCoverage?.threadSuccessfulSampleCount, 3)
        XCTAssertEqual(summary.captureCoverage?.threadCaptureFailureCount, 1)
        XCTAssertEqual(summary.captureCoverage?.processResourceCaptureSucceeded, true)
        XCTAssertEqual(summary.resourceCaptureSucceeded, true)
        XCTAssertEqual(summary.boundaryCoverage?.missingBoundaryNames, [])
    }

    func testKernelLedgerCatchesAnAllocationSpikeTheSamplesMiss() async throws {
        // A cadence far longer than the test, so only the start and stop samples
        // are taken and a transient spike lives and dies between them, as a short
        // allocation does between two 500 ms ticks (audit #3, #16).
        let sampler = NativeTelemetrySampler(
            clock: NativeTelemetryClock(),
            sampleIntervalMS: 60_000
        )
        await sampler.start()
        let spikeFootprintMB = try XCTUnwrap(
            try Self.withTransientAllocation(megabytes: 96) {
                IOSMemorySnapshot.capture().physFootprintMB
            }
        )
        let (summary, samples) = await sampler.stop(stageMarks: [])

        XCTAssertEqual(samples.map(\.kind), [.start, .stop])
        let sampledPeakMB = try XCTUnwrap(summary.physFootprintPeakMB)
        let kernelPeakMB = try XCTUnwrap(summary.kernelPhysFootprintPeakMB)
        XCTAssertLessThan(sampledPeakMB, spikeFootprintMB - 48, "the samples miss the spike")
        XCTAssertGreaterThanOrEqual(kernelPeakMB, spikeFootprintMB, "the kernel ledger does not")
        XCTAssertEqual(samples.last?.kernelPhysFootprintPeakMB, kernelPeakMB)
        XCTAssertEqual(
            summary.kernelPhysFootprintPeakStartMB,
            samples.first?.kernelPhysFootprintPeakMB
        )
        for sample in samples {
            XCTAssertGreaterThanOrEqual(
                try XCTUnwrap(sample.kernelPhysFootprintPeakMB),
                try XCTUnwrap(sample.physFootprintMB)
            )
        }
        XCTAssertNotNil(summary.graphicsFootprintEndMB)
        XCTAssertEqual(summary.graphicsFootprintEndMB, samples.last?.graphicsFootprintMB)
    }

    func testKernelLedgersRoundTripThroughTheRawSampleAndSummary() throws {
        let first = TelemetrySample(
            tMS: 0,
            capturedElapsedNS: 0,
            capturedUptimeNS: 1_000_000_000,
            kind: .start,
            memoryCaptureSucceeded: true,
            residentMB: 90,
            physFootprintMB: 100,
            compressedMB: 10,
            headroomMB: nil,
            gpuAllocatedMB: 10,
            gpuRecommendedWorkingSetMB: 100,
            kernelPhysFootprintPeakMB: 150,
            graphicsFootprintMB: 8,
            threads: 4
        )
        let last = TelemetrySample(
            tMS: 5,
            capturedElapsedNS: 5_000_000,
            capturedUptimeNS: 1_005_000_000,
            kind: .stop,
            memoryCaptureSucceeded: true,
            residentMB: 95,
            physFootprintMB: 105,
            compressedMB: 10,
            headroomMB: nil,
            gpuAllocatedMB: 12,
            gpuRecommendedWorkingSetMB: 100,
            kernelPhysFootprintPeakMB: 400,
            graphicsFootprintMB: 9,
            threads: 4
        )
        let decoded = try JSONDecoder().decode(
            TelemetrySample.self,
            from: JSONEncoder().encode(last)
        )
        XCTAssertEqual(decoded.kernelPhysFootprintPeakMB, 400)
        XCTAssertEqual(decoded.graphicsFootprintMB, 9)

        let summary = NativeTelemetrySampler.summarize(
            samples: [first, last],
            stageMarks: [],
            targetIntervalNS: 500_000_000
        )
        XCTAssertEqual(summary.kernelPhysFootprintPeakStartMB, 150)
        XCTAssertEqual(summary.kernelPhysFootprintPeakMB, 400)
        XCTAssertEqual(summary.graphicsFootprintEndMB, 9)
        // The sampled peak (105 MB) missed what the ledger saw inside the window.
        XCTAssertEqual(summary.physFootprintPeakMB, 105)

        // A sampler that could not read the ledgers leaves them absent.
        let legacy = NativeTelemetrySampler.summarize(
            samples: [sample(tMS: 0, kind: .start, footprint: 100, headroom: nil, gpu: 10)],
            stageMarks: [],
            targetIntervalNS: 500_000_000
        )
        XCTAssertNil(legacy.kernelPhysFootprintPeakMB)
        XCTAssertNil(legacy.graphicsFootprintEndMB)
    }

    func testThreadCountReleasesTheThreadPortsItReceives() {
        let thread = mach_thread_self()
        defer { mach_port_deallocate(mach_task_self_, thread) }
        func sendReferences() -> mach_port_urefs_t {
            var references: mach_port_urefs_t = 0
            // mach_port_right_t(0) is MACH_PORT_RIGHT_SEND.
            XCTAssertEqual(
                mach_port_get_refs(mach_task_self_, thread, mach_port_right_t(0), &references),
                KERN_SUCCESS
            )
            return references
        }
        let before = sendReferences()
        for _ in 0..<100 {
            XCTAssertTrue(NativeTelemetrySampler.threadCount().succeeded)
        }
        XCTAssertEqual(sendReferences(), before)
    }

    func testLedgerBytesRequireAFilledNonNegativeField() {
        XCTAssertEqual(IOSMemorySnapshot.ledgerBytes(42, fieldOffset: 8, filledBytes: 16), 42)
        XCTAssertNil(IOSMemorySnapshot.ledgerBytes(42, fieldOffset: 12, filledBytes: 16))
        XCTAssertNil(IOSMemorySnapshot.ledgerBytes(42, fieldOffset: nil, filledBytes: 64))
        XCTAssertNil(IOSMemorySnapshot.ledgerBytes(-1, fieldOffset: 0, filledBytes: 64))
    }

    func testV8TypedMemoryEventsAndMLXCumulativePeaks() throws {
        let transition = MemoryBudgetTransitionMetadata(
            previousBand: .healthy,
            currentBand: .guarded,
            reason: "active_generation_sample"
        )
        let trim = MemoryTrimMetadata(
            level: .softTrim,
            reason: "post_generation_guarded",
            source: .postGeneration
        )
        let unload = MemoryUnloadMetadata(reason: "critical_memory_context")
        let marks = [
            NativeTelemetryStageMark(
                tMS: 1,
                stage: MemoryBudgetTransitionMetadata.stage,
                metadata: transition.dictionaryRepresentation
            ),
            NativeTelemetryStageMark(
                tMS: 2,
                stage: MemoryTrimMetadata.stage,
                metadata: trim.dictionaryRepresentation
            ),
            NativeTelemetryStageMark(
                tMS: 3,
                stage: MemoryUnloadMetadata.stage,
                metadata: unload.dictionaryRepresentation
            ),
        ]
        let record = GenerationTelemetryRecord(
            generationID: "memory-v8",
            layer: .engine,
            recordedAt: "2026-07-13T00:00:00Z",
            stageMarks: marks,
            mlxMemoryByStage: [
                "before_model_load": NativeMLXMemorySnapshot(activeMB: 5, cacheMB: 2, peakMB: 8),
                "after_generation": NativeMLXMemorySnapshot(activeMB: 12, cacheMB: 7, peakMB: 20),
            ]
        )

        let decoded = try JSONDecoder().decode(
            GenerationTelemetryRecord.self,
            from: JSONEncoder().encode(record)
        )

        XCTAssertEqual(decoded.schemaVersion, 8)
        XCTAssertEqual(
            decoded.memoryMetrics?.events.map(\.kind),
            [.budgetTransition, .trimAction, .unload]
        )
        XCTAssertEqual(decoded.memoryMetrics?.events.first?.previousPressureBand, .healthy)
        XCTAssertEqual(decoded.memoryMetrics?.events.first?.currentPressureBand, .guarded)
        XCTAssertEqual(decoded.memoryMetrics?.mlxCumulativePeakMB, 20)
        XCTAssertEqual(decoded.memoryMetrics?.mlxActivePeakMB, 12)
        XCTAssertEqual(decoded.memoryMetrics?.mlxCachePeakMB, 7)
        XCTAssertEqual(decoded.memoryMetrics?.mlxStageCount, 2)
    }

    func testRequiredEngineBoundariesIncludePrewarmAndFirstOutput() {
        let byName = Dictionary(
            uniqueKeysWithValues: TelemetryBoundaryRequirement.engineGeneration.map {
                ($0.name, $0.alternatives)
            }
        )

        XCTAssertEqual(byName["mode-preparation-start"], ["before_mode_preparation"])
        XCTAssertEqual(byName["mode-preparation-end"], ["after_mode_preparation"])
        XCTAssertEqual(byName["prewarm-start"], ["before_prewarm", "prewarm_skipped"])
        XCTAssertEqual(byName["prewarm-end"], ["after_prewarm", "prewarm_skipped"])
        XCTAssertEqual(byName["first-output"], ["first_chunk", "final_audio_materialized"])
        XCTAssertEqual(byName["final-audio-materialized"], ["final_audio_materialized"])
        XCTAssertEqual(
            byName["post-generation-memory-action-start"],
            ["post_generation", "before_post_generation_trim"]
        )
        XCTAssertEqual(
            byName["post-generation-memory-action-end"],
            ["post_generation", "post_generation_trim"]
        )
        XCTAssertEqual(byName["terminal"], [
            "terminal_success", "terminal_failure", "terminal_cancelled", "preparation_failed",
        ])
    }

    func testMacOSMemoryMetricsDoNotApplyIPhonePressureBands() {
        #if os(macOS)
        let samples = [
            sample(
                tMS: 0,
                kind: .start,
                footprint: 5_500,
                headroom: nil,
                gpu: 90
            ),
            sample(
                tMS: 1,
                kind: .stop,
                footprint: 5_600,
                headroom: nil,
                gpu: 95
            ),
        ]
        let summary = NativeTelemetrySampler.summarize(
            samples: samples,
            stageMarks: [],
            targetIntervalNS: 500_000_000
        )

        XCTAssertNil(GenerationMemoryMetrics.worstPressureBand(for: summary))
        XCTAssertNil(
            GenerationMemoryMetrics(
                summary: summary,
                stageMarks: [],
                mlxMemoryByStage: nil
            ).worstPressureBand
        )
        #endif
    }

    func testMetricKitMemoryExitDocumentIsTypedIdempotentAndBounded() throws {
        let foreground = MetricKitForegroundExitCounts(
            normal: 1,
            watchdog: 0,
            memoryResourceLimit: 2,
            badAccess: 0,
            illegalInstruction: 0,
            abnormal: 0
        )
        let background = MetricKitBackgroundExitCounts(
            normal: 0,
            watchdog: 0,
            memoryResourceLimit: 3,
            memoryPressure: 4,
            badAccess: 0,
            illegalInstruction: 0,
            abnormal: 0,
            taskTimeout: 0,
            cpuResourceLimit: 0,
            suspendedWithLockedFile: 0
        )
        let record = MetricKitMemoryExitSummaryRecord(
            kind: .metricPayload,
            intervalStart: "2026-07-12T00:00:00Z",
            intervalEnd: "2026-07-13T00:00:00Z",
            peakMemoryMB: 1_024,
            foregroundExitCounts: foreground,
            backgroundExitCounts: background
        )
        let initial = MetricKitMemoryExitSummaryDocument(updatedAt: "now", records: [])
        let repeated = initial.appending([record, record], updatedAt: "later", maximumRecordCount: 1)

        XCTAssertEqual(repeated.records.count, 1)
        XCTAssertEqual(repeated.records[0].memoryExitCounts?.kind, .memoryExit)
        XCTAssertEqual(repeated.records[0].memoryExitCounts?.source, .metricKit)
        XCTAssertEqual(repeated.records[0].memoryExitCounts?.total, 9)

        let encoded = try JSONEncoder().encode(repeated)
        let object = try XCTUnwrap(
            JSONSerialization.jsonObject(with: encoded) as? [String: Any]
        )
        XCTAssertNil(object["rawPayload"])
        XCTAssertNil(object["callStackTree"])
        XCTAssertLessThan(encoded.count, 8_192)
    }

    func testIOSMemoryQualificationPlanIsExactAndRejectsDrift() throws {
        let runID = "ios-memory-qualification-20260713-fixture"
        let data = try JSONEncoder().encode(IOSMemoryQualificationSpec(runID: runID))
        let raw = try XCTUnwrap(String(data: data, encoding: .utf8))
        let plan = try IOSMemoryQualificationSpec.decodeAndValidate(raw)

        XCTAssertEqual(plan.takes.count, 9)
        XCTAssertEqual(plan.takes.map(\.takeIndex), Array(1...9))
        XCTAssertEqual(
            plan.takes.map(\.cell),
            [
                "custom/speed/medium/retained#0",
                "custom/speed/medium/retained#1",
                "custom/speed/medium/retained#2",
                "design/speed/medium/retained#0",
                "design/speed/medium/retained#1",
                "design/speed/medium/retained#2",
                "clone/speed/medium/retained#0",
                "clone/speed/medium/retained#1",
                "clone/speed/medium/retained#2",
            ]
        )

        let drifted = IOSMemoryQualificationSpec(runID: runID, repetitionsPerMode: 2)
        XCTAssertThrowsError(try drifted.validate())
        XCTAssertThrowsError(try IOSMemoryQualificationSpec(runID: "bad/path").validate())
    }

    func testIOSMemoryQualificationFailureMarkerIsBoundedAndPrivacySafe() throws {
        let runID = "ios-memory-qualification-20260713-failure"
        let status = IOSMemoryQualificationFailureStatus(
            runID: runID,
            failedAt: "2026-07-13T07:00:00Z",
            failureCode: .telemetryValidationFailed,
            completedTakeCount: 4,
            failedTakeIndex: 5,
            failedCell: "design/speed/medium/retained#1"
        )
        try status.validate()

        let encoded = try JSONEncoder().encode(status)
        XCTAssertLessThanOrEqual(
            encoded.count,
            IOSMemoryQualificationFailureStatus.maximumEncodedBytes
        )
        let object = try XCTUnwrap(
            JSONSerialization.jsonObject(with: encoded) as? [String: Any]
        )
        XCTAssertEqual(
            Set(object.keys),
            Set([
                "schemaVersion", "status", "runID", "policyID", "failedAt",
                "failureCode", "completedTakeCount", "expectedTakeCount",
                "failedTakeIndex", "failedCell",
            ])
        )
        for forbidden in [
            "error", "message", "prompt", "transcript", "voiceDescription",
            "path", "deviceName", "deviceIdentifier",
        ] {
            XCTAssertNil(object[forbidden])
        }

        let invalid = IOSMemoryQualificationFailureStatus(
            runID: runID,
            failedAt: "2026-07-13T07:00:00Z",
            failureCode: .generationFailed,
            completedTakeCount: 2,
            failedTakeIndex: 3,
            failedCell: "custom/speed/medium/not-a-real-cell"
        )
        XCTAssertThrowsError(try invalid.validate())
    }

    func testIOSMemoryQualificationTelemetryFailureCodesRemainBoundedAndTyped() throws {
        let codes: [IOSMemoryQualificationFailureCode] = [
            .takeIdentityUnavailable,
            .telemetryUnavailable,
            .telemetryRowCountInvalid,
            .telemetryIdentityInvalid,
            .telemetryFinishInvalid,
            .telemetryRunIdentityInvalid,
            .telemetryOutputInvalid,
            .telemetryMemoryEvidenceIncomplete,
            .telemetrySampleSidecarUnavailable,
            .telemetrySampleSidecarInvalid,
            .telemetryBoundaryIncomplete,
        ]

        for code in codes {
            let status = IOSMemoryQualificationFailureStatus(
                runID: "ios-memory-qualification-typed-failure",
                failedAt: "2026-07-14T12:00:00Z",
                failureCode: code,
                completedTakeCount: 0,
                failedTakeIndex: 1,
                failedCell: "custom/speed/medium/retained#0"
            )
            try status.validate()
            let data = try JSONEncoder().encode(status)
            XCTAssertLessThanOrEqual(
                data.count,
                IOSMemoryQualificationFailureStatus.maximumEncodedBytes
            )
            XCTAssertTrue(String(decoding: data, as: UTF8.self).contains(code.rawValue))
        }
    }

    /// Reserve `megabytes` of anonymous memory, dirty one byte per page so all
    /// of it counts in the physical footprint, run `body`, then release it.
    private static func withTransientAllocation(
        megabytes: Int,
        _ body: () -> Double?
    ) throws -> Double? {
        var address: vm_address_t = 0
        let size = vm_size_t(megabytes * 1_048_576)
        guard vm_allocate(mach_task_self_, &address, size, VM_FLAGS_ANYWHERE) == KERN_SUCCESS,
              let pointer = UnsafeMutableRawPointer(bitPattern: UInt(address)) else {
            throw XCTSkip("could not reserve the transient allocation")
        }
        defer { vm_deallocate(mach_task_self_, address, size) }
        let pageSize = Int(getpagesize())
        for offset in stride(from: 0, to: Int(size), by: pageSize) {
            pointer.storeBytes(of: 0xA5, toByteOffset: offset, as: UInt8.self)
        }
        return body()
    }

    private func sample(
        tMS: Int,
        kind: TelemetrySampleKind,
        boundary: String? = nil,
        footprint: Double?,
        headroom: Double?,
        gpu: Double?,
        memorySucceeded: Bool = true,
        threadSucceeded: Bool = true
    ) -> TelemetrySample {
        TelemetrySample(
            tMS: tMS,
            tNS: UInt64(tMS) * 1_000_000,
            capturedElapsedNS: UInt64(tMS) * 1_000_000,
            capturedUptimeNS: 1_000_000_000 + UInt64(tMS) * 1_000_000,
            kind: kind,
            boundary: boundary,
            processRole: .engine,
            captureSucceeded: memorySucceeded,
            memoryCaptureSucceeded: memorySucceeded,
            threadCaptureSucceeded: threadSucceeded,
            headroomCaptureSucceeded: headroom != nil,
            metalCaptureSucceeded: gpu != nil,
            totalDeviceRAMMB: 8_192,
            residentMB: footprint.map { $0 - 10 },
            physFootprintMB: footprint,
            compressedMB: footprint.map { $0 / 10 },
            headroomMB: headroom,
            gpuAllocatedMB: gpu,
            gpuRecommendedWorkingSetMB: gpu == nil ? nil : 100,
            impliedProcessLimitMB: {
                guard let footprint, let headroom else { return nil }
                return footprint + headroom
            }(),
            gpuWorkingSetUsageRatio: gpu.map { $0 / 100 },
            threads: threadSucceeded ? 8 : 0,
            thermalState: "nominal"
        )
    }
}
