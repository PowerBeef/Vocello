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

    /// U01: a CJK character weighs three in the single-take length, so Chinese
    /// and Japanese scripts past about 300 characters run as long-form projects
    /// on both apps, while 900 English (or Russian) characters stay one take.
    func testCJKScriptsRouteToLongFormByTheirSingleTakeLength() {
        let chinese = "火车在黎明时分离开了车站。"
        let japanese = "列車は夜明けに駅を出発した。"
        let english = "The narrator kept a steady, unhurried pace through the winding chapters. "
        let russian = "Рассказчик держал ровный темп. "
        let cases: [(String, Bool)] = [
            (String(repeating: "火", count: 300), false),
            (String(repeating: "火", count: 301), true),
            (String(String(repeating: chinese, count: 40).prefix(400)), true),
            (String(String(repeating: chinese, count: 70).prefix(850)), true),
            (String(String(repeating: japanese, count: 60).prefix(700)), true),
            (String(String(repeating: chinese, count: 30).prefix(300)), false),
            (String(String(repeating: english, count: 13).prefix(899)), false),
            (String(String(repeating: english, count: 13).prefix(900)), false),
            (String(String(repeating: russian, count: 30).prefix(900)), false),
            (String(String(repeating: english, count: 13).prefix(901)), true),
        ]
        for (text, expected) in cases {
            let label = "\(text.prefix(12))… (\(text.count))"
            XCTAssertEqual(GenerationTextLimitPolicy.state(for: text, mode: .custom).routesToLongForm, expected, label)
            XCTAssertEqual(GenerationTextLimitPolicy.exceedsSingleTake(text), expected, label)
            XCTAssertEqual(
                LongTextGenerationRouter.batchMode(for: text, lineByLine: false),
                expected ? .longForm : nil,
                label
            )
            XCTAssertEqual(SingleTakeScriptBudget.exceedsSingleTake(text), expected, label)
        }
    }

    /// The counter speaks in the script's own characters: 300 for a Chinese
    /// single take, 900 for an English one.
    func testCounterStateUsesTheScriptsOwnCharacters() {
        let chinese = GenerationTextLimitPolicy.state(for: String(repeating: "火", count: 100), mode: .custom)
        XCTAssertEqual(chinese.count, 100)
        XCTAssertEqual(chinese.singleTakeLength, 300)
        XCTAssertEqual(chinese.remainingCount, 200)
        XCTAssertEqual(chinese.counterText, "100/300")
        XCTAssertFalse(chinese.routesToLongForm)

        let english = GenerationTextLimitPolicy.state(for: String(repeating: "a", count: 100), mode: .custom)
        XCTAssertEqual(english.remainingCount, 800)
        XCTAssertEqual(english.counterText, "100/900")

        let fullChinese = GenerationTextLimitPolicy.state(for: String(repeating: "火", count: 300), mode: .custom)
        XCTAssertEqual(fullChinese.remainingCount, 0)
        XCTAssertEqual(fullChinese.counterText, "300/300")

        let longChinese = GenerationTextLimitPolicy.state(for: String(repeating: "火", count: 301), mode: .custom)
        XCTAssertTrue(longChinese.routesToLongForm)
        XCTAssertEqual(longChinese.displayLimit, GenerationTextLimitPolicy.longFormScriptLimit)
        XCTAssertFalse(longChinese.isOverLimit)
    }

    /// U29: a script with no letter or digit keeps Generate disabled like an
    /// empty one; P01-06: a whitespace-only brief is no brief on either app.
    func testNothingToSpeakAndBlankBriefsKeepGenerateDisabled() {
        for text in ["", " \n", "...", "…", "!!!", "— ? —", "🙂🙂", "。。。"] {
            XCTAssertFalse(GenerationTextLimitPolicy.state(for: text, mode: .custom).hasSpeakableText, text)
            XCTAssertFalse(GenerationTextLimitPolicy.hasSpeakableText(text), text)
        }
        for text in ["Hi", "42", "你好。", "ありがとう", "안녕", "Wait... what?"] {
            XCTAssertTrue(GenerationTextLimitPolicy.state(for: text, mode: .design).hasSpeakableText, text)
            XCTAssertTrue(GenerationTextLimitPolicy.hasSpeakableText(text), text)
        }
        // A punctuation-only script is not empty, only unspeakable.
        XCTAssertFalse(GenerationTextLimitPolicy.state(for: "...", mode: .clone).trimmedIsEmpty)

        XCTAssertFalse(GenerationTextLimitPolicy.hasVoiceDescription(""))
        XCTAssertFalse(GenerationTextLimitPolicy.hasVoiceDescription(" \n\t"))
        XCTAssertTrue(GenerationTextLimitPolicy.hasVoiceDescription(" A warm narrator\n"))
    }

    func testClampedCutsAtTheLongFormCeiling() {
        let text = String(repeating: "b", count: GenerationTextLimitPolicy.longFormScriptLimit + 5)
        XCTAssertEqual(GenerationTextLimitPolicy.clamped(text, mode: .clone).count, GenerationTextLimitPolicy.longFormScriptLimit)
        XCTAssertEqual(GenerationTextLimitPolicy.clamped("keep", mode: .clone), "keep")
    }
}
