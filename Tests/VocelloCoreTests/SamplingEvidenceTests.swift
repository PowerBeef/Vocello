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
