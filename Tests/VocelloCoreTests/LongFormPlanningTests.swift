import Foundation
@testable import QwenVoiceCore
import QwenVoiceBackendCore
import XCTest

final class LongFormPlanningTests: XCTestCase {
    func testBoundaryPrecedenceUsesParagraphBeforeLowerPriorityBoundaries() throws {
        let plan = try makePlan(
            "First paragraph.\n\nSecond sentence; clause, tail words.",
            tokenLimit: 9
        )

        XCTAssertGreaterThan(plan.segments.count, 1)
        XCTAssertEqual(plan.segments[0].spokenText, "First paragraph.")
        XCTAssertEqual(plan.segments[0].evidence.boundary, .paragraph)
    }

    func testSentenceBoundariesIncludeCJKPunctuation() throws {
        let plan = try makePlan("第一句。第二句！第三句很长很长。", tokenLimit: 5)

        XCTAssertEqual(plan.segments[0].spokenText, "第一句。")
        XCTAssertEqual(plan.segments[0].evidence.boundary, .sentence)
        XCTAssertEqual(plan.segments[1].spokenText, "第二句！")
        XCTAssertEqual(plan.segments[1].evidence.boundary, .sentence)
    }

    func testSemicolonWinsOverClauseAndWhitespaceWinsOverGrapheme() throws {
        let semicolon = try makePlan("alpha, beta; gamma delta", tokenLimit: 6)
        XCTAssertEqual(semicolon.segments[0].spokenText, "alpha, beta;")
        XCTAssertEqual(semicolon.segments[0].evidence.boundary, .semicolonOrColon)

        let whitespace = try makePlan("abcdefgh ijklmnop", tokenLimit: 4)
        XCTAssertEqual(whitespace.segments[0].spokenText, "abcdefgh")
        XCTAssertEqual(whitespace.segments[0].evidence.boundary, .whitespace)

        let grapheme = try makePlan("超長字串", tokenLimit: 2)
        XCTAssertEqual(grapheme.segments[0].spokenText, "超長")
        XCTAssertEqual(grapheme.segments[0].evidence.boundary, .grapheme)
    }

    func testProtectedVersionCannotBeSplitToSatisfyTokenLimit() throws {
        let spoken = try SpokenTextPlanner.plan(originalText: "v12.34.56")
        XCTAssertThrowsError(
            try LongFormPlanner.plan(
                spokenTextPlan: spoken,
                configuration: LongFormPlanningConfiguration(runtimeTokenLimit: 2, baseSeed: 7)
            )
        ) { error in
            XCTAssertEqual(error as? LongFormPlanningError, .protectedSpanExceedsTokenLimit)
        }
    }

    func testSegmentsNeverCutThroughProtectedForms() throws {
        let spoken = try SpokenTextPlanner.plan(
            originalText: "Dr. Smith uses v12.34 at https://example.com/a.b. Then continues."
        )
        let plan = try LongFormPlanner.plan(
            spokenTextPlan: spoken,
            configuration: LongFormPlanningConfiguration(runtimeTokenLimit: 20, baseSeed: 9)
        )
        let segmentBoundaries = Set(plan.segments.flatMap {
            [$0.evidence.spokenRange.range.lowerBound, $0.evidence.spokenRange.range.upperBound]
        })

        for risk in spoken.risks {
            let range = try XCTUnwrap(risk.spokenRange?.range)
            XCTAssertFalse(segmentBoundaries.contains { range.lowerBound < $0 && $0 < range.upperBound })
        }
    }

    func testRangesCoverEveryNonWhitespaceGraphemeAndRoundTripSegmentText() throws {
        let spoken = try SpokenTextPlanner.plan(
            originalText: "Préface.\n\n第二段包含日本語。 Final clause, done."
        )
        let plan = try LongFormPlanner.plan(
            spokenTextPlan: spoken,
            configuration: LongFormPlanningConfiguration(runtimeTokenLimit: 7, baseSeed: 11)
        )

        for segment in plan.segments {
            XCTAssertEqual(
                try spoken.spokenSubstring(in: segment.evidence.spokenRange),
                segment.spokenText
            )
            XCTAssertFalse(try spoken.sourceSubstring(in: segment.evidence.originalRange).isEmpty)
            XCTAssertLessThanOrEqual(segment.conservativeTokenEstimate, 7)
        }

        var cursor = spoken.spokenText.startIndex
        while cursor < spoken.spokenText.endIndex {
            let next = spoken.spokenText.index(after: cursor)
            let grapheme = spoken.spokenText[cursor..<next]
            if !grapheme.unicodeScalars.allSatisfy({
                CharacterSet.whitespacesAndNewlines.contains($0)
            }) {
                let offset = spoken.spokenText.utf8.distance(
                    from: spoken.spokenText.utf8.startIndex,
                    to: cursor
                )
                XCTAssertTrue(plan.segments.contains {
                    $0.evidence.spokenRange.range.contains(offset)
                })
            }
            cursor = next
        }
    }

    func testIdentityIsDeterministicAndSubseedsAreRequestOwned() throws {
        let spoken = try SpokenTextPlanner.plan(originalText: "One sentence. Two sentence. Three.")
        let baseline = try LongFormPlanner.plan(
            spokenTextPlan: spoken,
            configuration: LongFormPlanningConfiguration(runtimeTokenLimit: 5, baseSeed: 42)
        )
        let repeated = try LongFormPlanner.plan(
            spokenTextPlan: spoken,
            configuration: LongFormPlanningConfiguration(runtimeTokenLimit: 5, baseSeed: 42)
        )
        let otherSeed = try LongFormPlanner.plan(
            spokenTextPlan: spoken,
            configuration: LongFormPlanningConfiguration(runtimeTokenLimit: 5, baseSeed: 43)
        )

        XCTAssertEqual(baseline.evidence, repeated.evidence)
        XCTAssertEqual(
            baseline.segments.map(\.segmentID),
            otherSeed.segments.map(\.segmentID)
        )
        XCTAssertNotEqual(baseline.evidence.planDigest, otherSeed.evidence.planDigest)
        XCTAssertNotEqual(
            baseline.segments.map(\.evidence.effectiveSubseed),
            otherSeed.segments.map(\.evidence.effectiveSubseed)
        )
    }

    func testCodeSwitchRangesAreCarriedIntoOverlappingSegments() throws {
        let original = "English intro. 日本語の文章です。 English tail."
        let digest = SpokenTextPlanner.originalTextDigest(for: original)
        let languageRange = try utf8Range(of: "日本語の文章です。", in: original)
        let spoken = try SpokenTextPlanner.plan(
            originalText: original,
            codeSwitches: [
                SpokenTextCodeSwitchInput(
                    languageIdentifier: "ja-JP",
                    sourceRange: DigestBoundTextRange(textDigest: digest, range: languageRange)
                )
            ]
        )
        let plan = try LongFormPlanner.plan(
            spokenTextPlan: spoken,
            configuration: LongFormPlanningConfiguration(runtimeTokenLimit: 8, baseSeed: 5)
        )

        let annotated = plan.segments.filter { !$0.evidence.codeSwitchRanges.isEmpty }
        XCTAssertFalse(annotated.isEmpty)
        XCTAssertTrue(annotated.allSatisfy {
            $0.evidence.codeSwitchRanges.allSatisfy { $0.languageIdentifier == "ja-JP" }
        })
    }

    func testShippingBudgetKeepsWorstCaseAudioUnderCodecCap() throws {
        let budget = LongFormPlanningConfiguration.shippingRuntimeTokenLimit
        // Conservative estimate units are ~chars/3 (ASCII); codec tokens are
        // time-based at 12/s and measure ≈2.6× the estimate at canonical pace
        // (341-char bench long → ~293 codec vs ~114 estimated), ≈3.6× slow.
        XCTAssertLessThanOrEqual(
            Int(Double(budget) * 3.6),
            Qwen3GenerationConfiguration.officialQualityDefault.maxNewTokens,
            "worst-case slow-speech audio for one planned segment must stay under the codec cap"
        )
        XCTAssertGreaterThanOrEqual(budget, 256, "budget must keep long-form segments usefully large")

        // A dense multi-sentence script beyond one budget must split.
        let sentence = "The narrator kept a steady, unhurried pace through the winding chapters of the story. "
        let longScript = String(repeating: sentence, count: 40)  // ~3,480 chars
        let plan = try LongFormPlanner.plan(
            spokenTextPlan: SpokenTextPlanner.plan(originalText: longScript),
            configuration: LongFormPlanningConfiguration(
                runtimeTokenLimit: budget,
                baseSeed: 7
            )
        )
        XCTAssertGreaterThan(plan.segments.count, 1)
        for segment in plan.evidence.segments {
            XCTAssertLessThanOrEqual(segment.conservativeTokenEstimate, budget)
        }
    }

    func testSchemaV4RoundTripIsPrivacySafe() throws {
        let rawText = "Private long-form text with QA@example.com. Another sentence."
        let plan = try makePlan(rawText, tokenLimit: 8)
        let manifest = LongFormManifestV4(plan: plan.evidence)
        let data = try manifest.canonicalJSONData()
        let json = try XCTUnwrap(String(data: data, encoding: .utf8))

        XCTAssertFalse(json.contains("Private long-form"))
        XCTAssertFalse(json.contains("QA@example.com"))
        XCTAssertTrue(json.contains(plan.evidence.planDigest))
        XCTAssertEqual(
            try LongFormManifestDocument.decode(data),
            .version4(manifest)
        )
    }

    func testSchemaV4ExecutionAndAssemblyContractsFailClosed() throws {
        let plan = try makePlan("First sentence. Second sentence. Third sentence.", tokenLimit: 8)
        let execution = LongFormExecutionEvidence(
            generatedAtUTC: "2026-07-23T00:00:00Z",
            streamingExecution: true,
            segments: plan.evidence.segments.map { segment in
                LongFormSegmentExecutionEvidence(
                    index: segment.index,
                    segmentID: segment.segmentID,
                    generated: true,
                    audioDurationSeconds: 1.5,
                    qcPassed: true
                )
            }
        )
        let manifest = LongFormManifestV4(plan: plan.evidence, execution: execution)
        XCTAssertNoThrow(try manifest.validated())
        XCTAssertEqual(
            try LongFormManifestDocument.decode(manifest.canonicalJSONData()),
            .version4(manifest)
        )

        // Execution inventory must match the plan exactly.
        let truncated = LongFormManifestV4(
            plan: plan.evidence,
            execution: LongFormExecutionEvidence(
                generatedAtUTC: "2026-07-23T00:00:00Z",
                streamingExecution: true,
                segments: Array(execution.segments.dropLast())
            )
        )
        XCTAssertThrowsError(try truncated.validated())

        // Assembly evidence requires execution and a plan-matching inventory.
        let assembly = LongFormAssemblyEvidence(
            schemaVersion: LongFormAssemblyEvidence.currentSchemaVersion,
            algorithmVersion: LongFormAssemblyConfiguration.currentAlgorithmVersion,
            sampleRate: 24_000,
            blockFrames: 4_096,
            segmentCount: plan.evidence.segmentCount,
            outputFrameCount: 24_000,
            workingSetFrameUpperBound: 4_096,
            outputDigest: String(repeating: "0", count: 64),
            outputReadable: true,
            maximumSegmentBoundaryJump: 0,
            advisoryWarnings: nil,
            segments: plan.evidence.segments.map { segment in
                LongFormSegmentOutputFrameMap(
                    segmentID: segment.segmentID,
                    lineage: segment.lineage,
                    boundary: segment.boundary,
                    sourceFrameCount: 24_000,
                    trimmedLeadingFrames: 0,
                    trimmedTrailingFrames: 0,
                    contentOutputRange: LongFormOutputFrameRange(lowerBound: 0, upperBound: 24_000),
                    insertedPauseOutputRange: LongFormOutputFrameRange(lowerBound: 24_000, upperBound: 24_000),
                    sourceRMS: 0.1,
                    appliedGain: 1.0,
                    verifiedNonSpeechFadeInFrames: 0,
                    verifiedNonSpeechFadeOutFrames: 0
                )
            }
        )
        XCTAssertThrowsError(
            try LongFormManifestV4(plan: plan.evidence, assembly: assembly).validated()
        )
        XCTAssertNoThrow(
            try LongFormManifestV4(
                plan: plan.evidence,
                execution: execution,
                assembly: assembly
            ).validated()
        )
    }

    func testSchemaV4ReplacementHistoryContractFailsClosed() throws {
        let plan = try makePlan("First sentence. Second sentence.", tokenLimit: 8)
        let firstID = try XCTUnwrap(plan.evidence.segments.first?.segmentID)
        let valid = LongFormManifestV4(
            plan: plan.evidence,
            replacements: [
                LongFormSegmentReplacementEvidence(
                    segmentID: firstID,
                    revision: 2,
                    effectiveSeed: 7,
                    generatedAtUTC: "2026-07-23T00:00:00Z",
                    qcPassed: true
                ),
                LongFormSegmentReplacementEvidence(
                    segmentID: firstID,
                    revision: 3,
                    effectiveSeed: 8,
                    generatedAtUTC: "2026-07-23T00:01:00Z",
                    qcPassed: true
                ),
            ]
        )
        XCTAssertNoThrow(try valid.validated())
        XCTAssertEqual(
            try LongFormManifestDocument.decode(valid.canonicalJSONData()),
            .version4(valid)
        )

        let skippedRevision = LongFormManifestV4(
            plan: plan.evidence,
            replacements: [
                LongFormSegmentReplacementEvidence(
                    segmentID: firstID,
                    revision: 3,
                    effectiveSeed: 7,
                    generatedAtUTC: "2026-07-23T00:00:00Z",
                    qcPassed: true
                )
            ]
        )
        XCTAssertThrowsError(try skippedRevision.validated())

        let unknownSegment = LongFormManifestV4(
            plan: plan.evidence,
            replacements: [
                LongFormSegmentReplacementEvidence(
                    segmentID: "not-a-plan-segment",
                    revision: 2,
                    effectiveSeed: 7,
                    generatedAtUTC: "2026-07-23T00:00:00Z",
                    qcPassed: true
                )
            ]
        )
        XCTAssertThrowsError(try unknownSegment.validated())
    }

    func testSchemaV3ReadsAsLegacySummaryWithoutFabricatedIdentity() throws {
        let json = #"""
        {
          "schemaVersion": 3,
          "modelID": "pro_custom_speed",
          "mode": "custom",
          "segmentationMode": "longForm",
          "generatedAtUTC": "2026-07-17T12:00:00Z",
          "performanceSummary": {
            "totalSegments": 2,
            "generatedSegments": 1,
            "failedSegments": 1,
            "totalAudioDurationSeconds": 4.5
          },
          "segments": [
            {"index": 1, "text": "private", "audioPath": "/private/a.wav", "failed": false},
            {"index": 2, "text": "private", "audioPath": null, "failed": true}
          ]
        }
        """#

        guard case .legacyVersion3(let summary) = try LongFormManifestDocument.decode(Data(json.utf8)) else {
            return XCTFail("Expected read-only schema-v3 summary")
        }
        XCTAssertEqual(summary.schemaVersion, 3)
        XCTAssertEqual(summary.modelID, "pro_custom_speed")
        XCTAssertEqual(summary.encodedSegmentCount, 2)
        XCTAssertEqual(summary.generatedSegments, 1)
        XCTAssertEqual(summary.failedSegments, 1)
    }

    func testUnknownManifestSchemaFailsClosed() {
        XCTAssertThrowsError(
            try LongFormManifestDocument.decode(Data(#"{"schemaVersion":5}"#.utf8))
        ) { error in
            XCTAssertEqual(error as? LongFormPlanningError, .invalidManifestSchema(5))
        }
    }

    private func makePlan(
        _ text: String,
        tokenLimit: Int,
        baseSeed: UInt64 = 42
    ) throws -> LongFormPlan {
        try LongFormPlanner.plan(
            spokenTextPlan: SpokenTextPlanner.plan(originalText: text),
            configuration: LongFormPlanningConfiguration(
                runtimeTokenLimit: tokenLimit,
                baseSeed: baseSeed
            )
        )
    }

    // MARK: - Planner v2 (R-tail orphan rebalancing)
    // docs/decisions/long-form-context-planning-v2.md — fixtures self-calibrate via
    // single-segment plans so they stay robust to conservative-estimator changes.

    private func measuredEstimate(_ text: String) throws -> Int {
        let plan = try makePlan(text, tokenLimit: 100_000)
        XCTAssertEqual(plan.segments.count, 1)
        return plan.segments[0].evidence.conservativeTokenEstimate
    }

    func testPlanEvidenceCarriesPlannerVersion2() throws {
        let plan = try makePlan("One sentence only.", tokenLimit: 50)
        XCTAssertEqual(plan.evidence.plannerAlgorithmVersion, 2)
        XCTAssertEqual(
            LongFormPlanningConfiguration.currentPlannerAlgorithmVersion, 2
        )
    }

    func testTailRebalanceAvoidsOrphanFinalSegment() throws {
        let s1 = "The northern road climbs steadily through terraced fields and past low stone walls that farmers repaired every spring for generations without complaint."
        let s2 = "Travelers usually rest beside the second bridge before the descent."
        let s3 = "Few linger."
        let text = "\(s1) \(s2) \(s3)"

        let e3 = try measuredEstimate(s3)
        let headPair = try measuredEstimate("\(s1) \(s2)")
        let tailPair = try measuredEstimate("\(s2) \(s3)")
        let whole = try measuredEstimate(text)
        // Precondition shape: greedy fits S1+S2, orphans S3, and the rebalanced
        // tail (S2+S3) fits a segment.
        let limit = headPair + 2
        XCTAssertGreaterThan(whole, limit, "fixture must not fit in one segment")
        XCTAssertLessThan(Double(e3), 0.25 * Double(limit), "fixture must present an orphan tail")
        XCTAssertLessThanOrEqual(tailPair, limit, "the rebalanced tail must fit")

        let plan = try makePlan(text, tokenLimit: limit)

        XCTAssertEqual(plan.segments.count, 2)
        // R-tail moves the boundary to the sentence end after S1, keeping S2+S3 together.
        XCTAssertEqual(plan.segments[0].spokenTextForGeneration, s1)
        XCTAssertEqual(plan.segments[0].evidence.boundary, .sentence)
        let tailEstimate = try XCTUnwrap(plan.segments.last).evidence.conservativeTokenEstimate
        XCTAssertGreaterThanOrEqual(
            Double(tailEstimate), 0.25 * Double(limit),
            "the rebalanced tail must clear the orphan fraction"
        )
        XCTAssertLessThanOrEqual(tailEstimate, limit)
    }

    func testTailRebalanceNeverTradesParagraphForSentence() throws {
        let p1a = "The archive room stayed cold in every season, and the caretakers preferred it that way for the sake of the paper."
        let p1b = "Nobody argued with the caretakers."
        let tiny = "End."
        let text = "\(p1a) \(p1b)\n\n\(tiny)"

        let eTiny = try measuredEstimate(tiny)
        let paragraphOne = try measuredEstimate("\(p1a) \(p1b)")
        let whole = try measuredEstimate(text)
        let limit = paragraphOne
        XCTAssertGreaterThan(whole, limit, "fixture must not fit in one segment")
        XCTAssertLessThan(Double(eTiny), 0.25 * Double(limit))

        let plan = try makePlan(text, tokenLimit: limit)

        // The only paragraph candidate precedes the tiny paragraph; with no earlier
        // paragraph candidate to rebalance to, the orphan stands rather than trading
        // the 500 ms paragraph pause for a sentence boundary inside paragraph one.
        XCTAssertEqual(plan.segments.count, 2)
        XCTAssertEqual(plan.segments[0].evidence.boundary, .paragraph)
        XCTAssertEqual(try XCTUnwrap(plan.segments.last).spokenTextForGeneration, tiny)
    }

    func testTailRebalancePrefersEarlierParagraphWhenAvailable() throws {
        let p1 = "The first survey of the valley took three summers and produced maps that the council still consults when the river argues with its banks."
        let p2 = "The second survey took one summer."
        let p3 = "Nobody read it."
        let text = "\(p1)\n\n\(p2)\n\n\(p3)"

        let e3 = try measuredEstimate(p3)
        let headPair = try measuredEstimate("\(p1)\n\n\(p2)")
        let tailPair = try measuredEstimate("\(p2)\n\n\(p3)")
        let whole = try measuredEstimate(text)
        let limit = headPair + 2
        XCTAssertGreaterThan(whole, limit, "fixture must not fit in one segment")
        XCTAssertLessThan(Double(e3), 0.25 * Double(limit))
        XCTAssertLessThanOrEqual(tailPair, limit, "the rebalanced tail must fit")

        let plan = try makePlan(text, tokenLimit: limit)

        // Greedy would take the last in-window paragraph break (after P2), orphaning
        // P3; R-tail rebalances to the earlier paragraph break, and both boundaries
        // keep paragraph precedence.
        XCTAssertEqual(plan.segments.count, 2)
        XCTAssertEqual(plan.segments[0].spokenTextForGeneration, p1)
        XCTAssertEqual(plan.segments[0].evidence.boundary, .paragraph)
        XCTAssertGreaterThanOrEqual(
            Double(try XCTUnwrap(plan.segments.last).evidence.conservativeTokenEstimate),
            0.25 * Double(limit)
        )
    }

    func testNonCurrentPlannerVersionStaysRejectedForNewPlans() throws {
        let spoken = try SpokenTextPlanner.plan(originalText: "Replay safety.")
        XCTAssertThrowsError(
            try LongFormPlanner.plan(
                spokenTextPlan: spoken,
                configuration: LongFormPlanningConfiguration(
                    plannerAlgorithmVersion: 1,
                    runtimeTokenLimit: 50,
                    baseSeed: 1
                )
            )
        ) { error in
            XCTAssertEqual(
                error as? LongFormPlanningError, .invalidAlgorithmVersion(1)
            )
        }
    }

    private func utf8Range(of needle: String, in text: String) throws -> TextUTF8Range {
        let range = try XCTUnwrap(text.range(of: needle))
        return TextUTF8Range(
            lowerBound: text.utf8.distance(from: text.utf8.startIndex, to: range.lowerBound),
            upperBound: text.utf8.distance(from: text.utf8.startIndex, to: range.upperBound)
        )
    }
}
