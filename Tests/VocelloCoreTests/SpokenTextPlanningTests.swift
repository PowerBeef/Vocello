import Foundation
@testable import QwenVoiceCore
import XCTest

final class SpokenTextPlanningTests: XCTestCase {
    func testNormalizationIsDeterministicAndConservative() throws {
        let original = "  Cafe\u{301}\u{00A0}\u{00A0}“hello”\r\n\r\n１２３．  "
        let first = try SpokenTextPlanner.plan(originalText: original)
        let second = try SpokenTextPlanner.plan(originalText: original)

        XCTAssertEqual(first.spokenText, "Café \"hello\"\n\n123.")
        XCTAssertEqual(first.spokenText, second.spokenText)
        XCTAssertEqual(first.originalTextDigest, second.originalTextDigest)
        XCTAssertEqual(first.spokenTextDigest, second.spokenTextDigest)
        XCTAssertGreaterThan(first.transformationCount, 0)
    }

    func testProtectedFormsRemainUnchangedAndReceiveTypedRanges() throws {
        let original = "See https://example.com/v1.2, email QA@example.com. Version v2.1 uses U.S.A. rules."
        let plan = try SpokenTextPlanner.plan(originalText: original)

        XCTAssertEqual(plan.spokenText, original)
        let kinds = Set(plan.risks.map(\.kind))
        XCTAssertTrue(kinds.contains(.protectedURL))
        XCTAssertTrue(kinds.contains(.protectedEmail))
        XCTAssertTrue(kinds.contains(.protectedVersion))
        XCTAssertTrue(kinds.contains(.protectedAcronym))

        for risk in plan.risks {
            let source = try plan.sourceSubstring(in: risk.sourceRange)
            let spoken = try risk.spokenRange.map { try plan.spokenSubstring(in: $0) }
            XCTAssertEqual(source, spoken)
        }
    }

    func testAmbiguousFormsAreReportedRatherThanRewritten() throws {
        let original = "Meet 03/04/2026 at 09:30 for $12.50 and 5kg."
        let plan = try SpokenTextPlanner.plan(originalText: original)

        XCTAssertEqual(plan.spokenText, original)
        XCTAssertEqual(
            Set(plan.risks.map(\.kind)),
            Set([
                SpokenTextRiskKind.ambiguousDate,
                .ambiguousTime,
                .ambiguousCurrency,
                .ambiguousUnit,
            ])
        )
    }

    func testCodeSwitchRangeIsDigestBoundAndMappedAcrossUnicode() throws {
        let original = "Hello 日本語 world"
        let digest = SpokenTextPlanner.originalTextDigest(for: original)
        let sourceRange = try utf8Range(of: "日本語", in: original)
        let input = SpokenTextCodeSwitchInput(
            languageIdentifier: "ja-JP",
            sourceRange: DigestBoundTextRange(textDigest: digest, range: sourceRange)
        )

        let plan = try SpokenTextPlanner.plan(originalText: original, codeSwitches: [input])
        let resolved = try XCTUnwrap(plan.codeSwitchRanges.first)
        XCTAssertEqual(try plan.sourceSubstring(in: resolved.sourceRange), "日本語")
        XCTAssertEqual(try plan.spokenSubstring(in: resolved.spokenRange), "日本語")
    }

    func testCodeSwitchRejectsWrongDigestAndNonBoundaryUTF8Offsets() throws {
        let original = "A😀B"
        let digest = SpokenTextPlanner.originalTextDigest(for: original)
        let wrongDigest = SpokenTextCodeSwitchInput(
            languageIdentifier: "en",
            sourceRange: DigestBoundTextRange(
                textDigest: String(repeating: "0", count: 64),
                range: TextUTF8Range(lowerBound: 0, upperBound: 1)
            )
        )
        XCTAssertThrowsError(
            try SpokenTextPlanner.plan(originalText: original, codeSwitches: [wrongDigest])
        ) { error in
            XCTAssertEqual(error as? SpokenTextPlanningError, .sourceDigestMismatch)
        }

        let splitEmoji = SpokenTextCodeSwitchInput(
            languageIdentifier: "und",
            sourceRange: DigestBoundTextRange(
                textDigest: digest,
                range: TextUTF8Range(lowerBound: 2, upperBound: 4)
            )
        )
        XCTAssertThrowsError(
            try SpokenTextPlanner.plan(originalText: original, codeSwitches: [splitEmoji])
        ) { error in
            XCTAssertEqual(error as? SpokenTextPlanningError, .invalidSourceRange)
        }
    }

    func testEvidenceSerializationContainsNoRawText() throws {
        let original = "Private phrase QA@example.com version v2.1"
        let plan = try SpokenTextPlanner.plan(originalText: original)
        let encoded = try plan.evidence.canonicalJSONData()
        let json = try XCTUnwrap(String(data: encoded, encoding: .utf8))

        XCTAssertFalse(json.contains("Private phrase"))
        XCTAssertFalse(json.contains("QA@example.com"))
        XCTAssertFalse(json.contains("v2.1"))
        XCTAssertTrue(json.contains(plan.originalTextDigest))
        XCTAssertTrue(json.contains(plan.spokenTextDigest))
        XCTAssertEqual(try plan.evidence.canonicalDigest().count, 64)
    }

    private func utf8Range(of needle: String, in text: String) throws -> TextUTF8Range {
        let range = try XCTUnwrap(text.range(of: needle))
        return TextUTF8Range(
            lowerBound: text.utf8.distance(from: text.utf8.startIndex, to: range.lowerBound),
            upperBound: text.utf8.distance(from: text.utf8.startIndex, to: range.upperBound)
        )
    }

    func testNormalizationIsIdempotent() throws {
        let original = "  Cafe\u{301}\u{00A0}\u{00A0}\u{201C}hello\u{201D}\r\n\r\n\u{FF11}\u{FF12}\u{FF13}\u{FF0E}  "
        let first = try SpokenTextPlanner.plan(originalText: original)
        XCTAssertGreaterThan(first.transformationCount, 0)
        let second = try SpokenTextPlanner.plan(originalText: first.spokenText)
        XCTAssertEqual(second.spokenText, first.spokenText)
        XCTAssertEqual(second.transformationCount, 0)
    }

    /// Phase 10 standing contract: the engine now normalizes every take's
    /// script, so the fixed benchmark corpus must be normalization-invariant
    /// or characterization controls across the change would stop being
    /// comparable. A failure here means either the corpus or the normalizer
    /// changed; both are promotion-grade decisions, never a silent edit.
    func testBenchmarkCorpusIsNormalizationInvariant() throws {
        var texts = BenchMatrixSpec.corpus.map(\.text)
        texts.append(BenchMatrixSpec.defaultDesignBrief)
        for text in texts {
            let plan = try SpokenTextPlanner.plan(originalText: text)
            XCTAssertEqual(plan.spokenText, text)
            XCTAssertEqual(plan.transformationCount, 0, text)
        }
    }

    func testPromptAssemblySpeaksTheSpokenTextOverride() throws {
        let request = GenerationRequest(
            mode: .custom,
            modelID: "pro_custom_speed",
            text: "\u{FF11}\u{FF12}\u{FF13}\u{FF0E} The train left.",
            outputPath: "/tmp/unused.wav",
            shouldStream: true,
            payload: .custom(speakerID: "aiden", deliveryStyle: nil),
            generationID: UUID()
        )
        let plan = try SpokenTextPlanner.plan(originalText: request.text)
        XCTAssertGreaterThan(plan.transformationCount, 0)
        let assembly = GenerationSemantics.qwen3PromptAssembly(
            for: request,
            capabilities: Qwen3TTSModelCapabilities(
                modelSize: .pro1b7,
                familyType: .customVoice,
                supportsInstructionControl: true,
                supportsVoiceClone: false,
                supportsXVectorOnlyClone: false,
                requiresSpeakerEncoder: false,
                tokenizerProfile: Qwen3TTSTokenizerProfile(
                    name: "qwen3",
                    sampleRateHz: 24_000,
                    frameRateHz: 12.5,
                    decoderQuantizers: 16,
                    encoderValidQuantizers: 8,
                    encoderConfiguredQuantizers: 8,
                    codebookSize: 2_048,
                    semanticCodebookSize: 4_096
                ),
                generationDefaults: Qwen3TTSGenerationDefaultsProfile(
                    checkpointMaxNewTokens: nil,
                    wrapperFallbackMaxNewTokens: 2_048,
                    appPolicyMaxNewTokens: 2_048,
                    temperature: 0.9,
                    topP: 1,
                    topK: 50,
                    doSample: true,
                    repetitionPenalty: 1.05,
                    source: .appPolicy
                ),
                artifactAvailability: .publicArtifact
            ),
            spokenText: plan.spokenText
        )
        XCTAssertEqual(assembly.text, plan.spokenText)
    }
}
