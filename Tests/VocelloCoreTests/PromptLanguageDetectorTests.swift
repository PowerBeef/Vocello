import QwenVoiceCore
import XCTest

final class PromptLanguageDetectorTests: XCTestCase {
    func testTooShortTextReturnsAuto() {
        XCTAssertEqual(PromptLanguageDetector.detect(""), .auto)
        XCTAssertEqual(PromptLanguageDetector.detect("   "), .auto)
        XCTAssertEqual(PromptLanguageDetector.detect(LanguageFixtures.tooShort), .auto)
    }

    func testAmbiguousLatinReturnsAuto() {
        XCTAssertEqual(PromptLanguageDetector.detect(LanguageFixtures.ambiguousLatin), .auto)
    }

    func testUnsupportedLatinLanguageReturnsAuto() {
        XCTAssertEqual(PromptLanguageDetector.detect(LanguageFixtures.dutch), .auto)
    }

    func testDetectsLatinLanguages() {
        XCTAssertEqual(PromptLanguageDetector.detect(LanguageFixtures.english), .english)
        XCTAssertEqual(PromptLanguageDetector.detect(LanguageFixtures.french), .french)
        XCTAssertEqual(PromptLanguageDetector.detect(LanguageFixtures.german), .german)
        XCTAssertEqual(PromptLanguageDetector.detect(LanguageFixtures.spanish), .spanish)
        XCTAssertEqual(PromptLanguageDetector.detect(LanguageFixtures.italian), .italian)
        XCTAssertEqual(PromptLanguageDetector.detect(LanguageFixtures.portuguese), .portuguese)
    }

    func testDetectsScriptFastPathsViaGenerationSemantics() {
        // Unicode fast paths live in GenerationSemantics; detector is still exercised
        // for CJK when routed through qwenLanguageHint in integration tests below.
        XCTAssertEqual(PromptLanguageDetector.detect(LanguageFixtures.chinese), .chinese)
        XCTAssertEqual(PromptLanguageDetector.detect(LanguageFixtures.japanese), .japanese)
        XCTAssertEqual(PromptLanguageDetector.detect(LanguageFixtures.korean), .korean)
        XCTAssertEqual(PromptLanguageDetector.detect(LanguageFixtures.russian), .russian)
    }
}
