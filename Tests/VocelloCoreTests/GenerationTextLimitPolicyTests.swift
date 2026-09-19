import QwenVoiceCore
import XCTest

final class GenerationTextLimitPolicyTests: XCTestCase {
    func testSingleTakeLimitIsTheSharedNineHundredCharacters() {
        XCTAssertEqual(GenerationTextLimitPolicy.singleTakeScriptLimit, 900)
        XCTAssertEqual(GenerationTextLimitPolicy.limit(for: .custom), 900)
        XCTAssertEqual(GenerationTextLimitPolicy.limit(for: .clone), 900)
        XCTAssertEqual(GenerationTextLimitPolicy.descriptionLimit, VoiceDesignBriefCatalog.descriptionLimit)
    }

    func testStateRoutesLongScriptsAndBlocksOnlyTheHardCeiling() {
        let short = GenerationTextLimitPolicy.state(for: String(repeating: "a", count: 900), mode: .design)
        XCTAssertFalse(short.routesToLongForm)
        XCTAssertEqual(short.remainingCount, 0)
        XCTAssertEqual(short.counterText, "900/900")

        let long = GenerationTextLimitPolicy.state(for: String(repeating: "a", count: 901), mode: .design)
        XCTAssertTrue(long.routesToLongForm)
        XCTAssertFalse(long.isOverLimit)
        XCTAssertEqual(long.displayLimit, GenerationTextLimitPolicy.longFormScriptLimit)

        let over = GenerationTextLimitPolicy.state(
            for: String(repeating: "a", count: GenerationTextLimitPolicy.longFormScriptLimit + 1),
            mode: .custom
        )
        XCTAssertTrue(over.isOverLimit)
        XCTAssertTrue(GenerationTextLimitPolicy.state(for: " \n", mode: .custom).trimmedIsEmpty)
    }

    func testMacAutomaticRoutingMatchesSharedPolicyAndLineOverrideWins() {
        for count in [0, 899, 900, 901, 30_000] {
            let text = String(repeating: "a", count: count)
            let expected: MacBatchSegmentationMode? = count > 900 ? .longForm : nil
            XCTAssertEqual(LongTextGenerationRouter.batchMode(for: text, lineByLine: false), expected)
            XCTAssertEqual(LongTextGenerationRouter.batchMode(for: text, lineByLine: true), .lineSeparated)
            // Switching off restores the automatic selection for the current text.
            XCTAssertEqual(LongTextGenerationRouter.batchMode(for: text, lineByLine: false), expected)
        }
        let padded = " " + String(repeating: "é", count: 899) + "\n"
        XCTAssertTrue(GenerationTextLimitPolicy.state(for: padded, mode: .custom).routesToLongForm)
        XCTAssertEqual(LongTextGenerationRouter.batchMode(for: padded, lineByLine: false), .longForm)
        let multiline = "First line.\nSecond line."
        XCTAssertNil(LongTextGenerationRouter.batchMode(for: multiline, lineByLine: false))
        XCTAssertEqual(LongTextGenerationRouter.batchMode(for: multiline, lineByLine: true), .lineSeparated)
    }

    func testClampedCutsAtTheLongFormCeiling() {
        let text = String(repeating: "b", count: GenerationTextLimitPolicy.longFormScriptLimit + 5)
        XCTAssertEqual(GenerationTextLimitPolicy.clamped(text, mode: .clone).count, GenerationTextLimitPolicy.longFormScriptLimit)
        XCTAssertEqual(GenerationTextLimitPolicy.clamped("keep", mode: .clone), "keep")
    }
}
