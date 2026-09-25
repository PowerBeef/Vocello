import XCTest
@testable import QwenVoiceCore

final class SamplingEvidenceTests: XCTestCase {
    func testPromotionRequiresMatchingSeedsAndWAVDigest() throws {
        let evidence = SamplingTakeEvidence(
            plannedSeed: 42,
            observedSeed: 42,
            seedSource: .requested,
            wavDigest: String(repeating: "ab", count: 32)
        )
        XCTAssertNoThrow(try evidence.validatedForPromotion())
        XCTAssertEqual(evidence.telemetryNotes["samplingSeedAgreement"], "matched")
        XCTAssertEqual(evidence.telemetryNotes["samplingWAVDigest"]?.count, 64)
        let packaged = try evidence.packagedTelemetryNotes()
        XCTAssertEqual(packaged["samplingPromotionPackaged"], "true")
        let reconstructed = try XCTUnwrap(SamplingTakeEvidence(telemetryNotes: packaged))
        XCTAssertNoThrow(try reconstructed.validatedForPromotion())
    }

    func testMissingOrMismatchedSeedsFailClosed() {
        XCTAssertThrowsError(
            try SamplingTakeEvidence(
                plannedSeed: nil,
                observedSeed: 1,
                seedSource: .generated,
                wavDigest: String(repeating: "cd", count: 32)
            ).validatedForPromotion()
        ) { error in
            XCTAssertEqual(error as? SamplingTakeEvidence.AgreementError, .missingPlannedSeed)
        }

        XCTAssertThrowsError(
            try SamplingTakeEvidence(
                plannedSeed: 1,
                observedSeed: nil,
                seedSource: .requested,
                wavDigest: String(repeating: "cd", count: 32)
            ).validatedForPromotion()
        ) { error in
            XCTAssertEqual(error as? SamplingTakeEvidence.AgreementError, .missingObservedSeed)
        }

        XCTAssertThrowsError(
            try SamplingTakeEvidence(
                plannedSeed: 1,
                observedSeed: 2,
                seedSource: .requested,
                wavDigest: String(repeating: "cd", count: 32)
            ).validatedForPromotion()
        ) { error in
            XCTAssertEqual(
                error as? SamplingTakeEvidence.AgreementError,
                .seedMismatch(planned: 1, observed: 2)
            )
        }

        XCTAssertThrowsError(
            try SamplingTakeEvidence(
                plannedSeed: 1,
                observedSeed: 1,
                seedSource: .requested,
                wavDigest: nil
            ).validatedForPromotion()
        ) { error in
            XCTAssertEqual(error as? SamplingTakeEvidence.AgreementError, .missingWAVDigest)
        }
    }

    func testSubSeedDerivationIsDomainSeparatedAndDeterministic() throws {
        let base: UInt64 = 19_790_615
        let first = try SamplingSubSeedDerivation.derive(
            baseSeed: base,
            domain: .longFormSegment,
            components: ["segment-a"]
        )
        let repeatFirst = try SamplingSubSeedDerivation.derive(
            baseSeed: base,
            domain: .longFormSegment,
            components: ["segment-a"]
        )
        let otherSegment = try SamplingSubSeedDerivation.derive(
            baseSeed: base,
            domain: .longFormSegment,
            components: ["segment-b"]
        )
        let otherDomain = try SamplingSubSeedDerivation.derive(
            baseSeed: base,
            domain: .candidateRetry,
            components: ["segment-a"]
        )
        XCTAssertEqual(first, repeatFirst)
        XCTAssertNotEqual(first, otherSegment)
        XCTAssertNotEqual(first, otherDomain)
        XCTAssertThrowsError(
            try SamplingSubSeedDerivation.derive(
                baseSeed: base,
                domain: .characterizationControl,
                components: [""]
            )
        )
    }

    func testWAVDigestHashesFileContents() throws {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("sampling-evidence-\(UUID().uuidString).bin")
        let payload = Data("vocello-sampling-evidence".utf8)
        try payload.write(to: url)
        defer { try? FileManager.default.removeItem(at: url) }
        let digest = try SamplingTakeEvidence.sha256FileDigest(at: url)
        XCTAssertEqual(digest.count, 64)
        XCTAssertEqual(digest, try SamplingTakeEvidence.sha256FileDigest(at: url))
    }

    /// Audit #29: the benchmark seed policy hashes a cell exactly as
    /// `scripts/lib/bench_seed.py` does, so the lane checkers can recompute it.
    func testBenchSeedPolicyHashesTheCellLikeTheCheckers() {
        XCTAssertEqual(BenchSeedPolicy.seed(forCell: "custom/short/warm#1"), 15_229_935_581_363_691_511)
        XCTAssertEqual(BenchSeedPolicy.seed(forCell: "custom/medium/cold#0"), 5_885_590_677_941_928_857)
        XCTAssertEqual(BenchSeedPolicy.seed(forCell: "clone/long/warm#2"), 3_348_844_143_494_952_299)
    }

    func testBenchSeedPolicyNeedsInternalDiagnosticsAndTheMasterGate() {
        let key = BenchSeedPolicy.policyEnvironmentKey
        let enabled = ["QWENVOICE_DEBUG": "1", key: "cell-hash-v1"]
        XCTAssertEqual(BenchSeedPolicy.policy(environment: enabled, internalDiagnosticsAvailable: true), "cell-hash-v1")
        XCTAssertNil(BenchSeedPolicy.policy(environment: enabled, internalDiagnosticsAvailable: false))
        XCTAssertNil(BenchSeedPolicy.policy(environment: [key: "cell-hash-v1"], internalDiagnosticsAvailable: true))
        XCTAssertNil(
            BenchSeedPolicy.policy(environment: ["QWENVOICE_DEBUG": "1", key: "random"], internalDiagnosticsAvailable: true)
        )
        let schedule = [
            "QWENVOICE_DEBUG": "1",
            BenchSeedPolicy.cellScheduleEnvironmentKey: "custom/medium/cold#0, custom/short/warm#0,",
        ]
        XCTAssertEqual(
            BenchSeedPolicy.scheduledCells(environment: schedule, internalDiagnosticsAvailable: true),
            ["custom/medium/cold#0", "custom/short/warm#0"]
        )
        XCTAssertNil(BenchSeedPolicy.scheduledCells(environment: schedule, internalDiagnosticsAvailable: false))
    }

    /// Audit #29: the iPhone lane's launch schedule gives one cell per applied
    /// generation, ahead of the current take, and past its end a take keeps its
    /// own seed; without the capability or the knob nothing is consumed.
    func testBenchSeedPolicyConsumesTheScheduleOneCellPerGeneration() {
        let request = GenerationRequest(
            mode: .custom, modelID: "fixture", text: "test", outputPath: "take.wav", shouldStream: true,
            payload: .custom(speakerID: "aiden", deliveryStyle: nil), generationID: UUID(), seed: 9
        )
        let scheduled = [
            "QWENVOICE_DEBUG": "1",
            BenchSeedPolicy.policyEnvironmentKey: BenchSeedPolicy.cellHashV1,
            BenchSeedPolicy.cellScheduleEnvironmentKey: "custom/medium/cold#0,custom/short/warm#0",
        ]
        var cursor = 0
        var currentTakeReads = 0
        func appliedSeed(environment: [String: String], capability: Bool = true) -> UInt64? {
            BenchSeedPolicy.applying(
                to: request,
                environment: environment,
                internalDiagnosticsAvailable: capability,
                nextSchedulePosition: {
                    defer { cursor += 1 }
                    return cursor
                },
                currentTakeCell: {
                    currentTakeReads += 1
                    return "clone/long/warm#2"
                }
            ).seed
        }

        XCTAssertEqual(appliedSeed(environment: scheduled, capability: false), 9)
        XCTAssertEqual(
            appliedSeed(environment: scheduled.filter { $0.key != BenchSeedPolicy.policyEnvironmentKey }), 9
        )
        XCTAssertEqual(cursor, 0)
        XCTAssertEqual(appliedSeed(environment: scheduled), BenchSeedPolicy.seed(forCell: "custom/medium/cold#0"))
        XCTAssertEqual(appliedSeed(environment: scheduled), BenchSeedPolicy.seed(forCell: "custom/short/warm#0"))
        XCTAssertEqual(appliedSeed(environment: scheduled), 9)
        XCTAssertEqual(cursor, 3)
        XCTAssertEqual(currentTakeReads, 0)
    }

    /// Audit #29: without a schedule (the macOS lane) the seed comes from the
    /// current-take cell, and a take without one keeps its own seed.
    func testBenchSeedPolicyFallsBackToTheCurrentTakeCell() {
        let request = GenerationRequest(
            mode: .custom, modelID: "fixture", text: "test", outputPath: "take.wav", shouldStream: true,
            payload: .custom(speakerID: "aiden", deliveryStyle: nil), generationID: UUID(), seed: 9
        )
        let environment = ["QWENVOICE_DEBUG": "1", BenchSeedPolicy.policyEnvironmentKey: BenchSeedPolicy.cellHashV1]
        func appliedSeed(currentTake: String?) -> UInt64? {
            BenchSeedPolicy.applying(
                to: request,
                environment: environment,
                internalDiagnosticsAvailable: true,
                nextSchedulePosition: {
                    XCTFail("a run without a schedule never reads its cursor")
                    return 0
                },
                currentTakeCell: { currentTake }
            ).seed
        }

        XCTAssertEqual(appliedSeed(currentTake: "custom/short/warm#1"), 15_229_935_581_363_691_511)
        XCTAssertEqual(appliedSeed(currentTake: nil), 9)
        XCTAssertEqual(appliedSeed(currentTake: ""), 9)
    }

    func testWithSeedChangesOnlyTheSeed() {
        let generationID = UUID()
        let request = GenerationRequest(
            mode: .custom, modelID: "fixture", text: "test", outputPath: "take.wav", shouldStream: true,
            payload: .custom(speakerID: "aiden", deliveryStyle: nil), generationID: generationID
        )
        let seeded = request.withSeed(42)
        XCTAssertEqual(seeded.seed, 42)
        XCTAssertEqual(seeded.withSeed(7).seed, 7)
        XCTAssertEqual(
            GenerationRequest(
                mode: .custom, modelID: "fixture", text: "test", outputPath: "take.wav", shouldStream: true,
                payload: .custom(speakerID: "aiden", deliveryStyle: nil), generationID: generationID, seed: 42
            ),
            seeded
        )
    }
}
