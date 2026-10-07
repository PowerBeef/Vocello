@testable import MLXAudioTTS
import XCTest

/// P02-08 / P05-07: the process-wide conditioning-prefix cache stores the
/// instruct tokens embedded on a miss, so its key must name exactly that text.
/// A key that folded case or spacing let an edited brief reuse the earlier
/// spelling's tokens, and the same request and seed then gave a different take
/// depending on what the cache held.
final class Qwen3ConditioningPrefixCacheKeyTests: XCTestCase {
    func testCustomVoiceInstructionsThatDifferOnlyInCaseAreDistinctPrompts() {
        XCTAssertNotEqual(
            Qwen3ConditioningPrefixCacheKey.customVoice(
                language: "english", speaker: "aiden", instruction: "Speak SLOWLY"
            ),
            Qwen3ConditioningPrefixCacheKey.customVoice(
                language: "english", speaker: "aiden", instruction: "speak slowly"
            )
        )
    }

    func testVoiceDesignBriefsThatDifferOnlyInCaseOrSpacingAreDistinctPrompts() {
        let brief = "A warm narrator. Emphasise BRAND names."
        let key = Qwen3ConditioningPrefixCacheKey.voiceDesign(language: "english", voiceDescription: brief)
        for edited in [
            "A warm narrator. Emphasise brand names.",
            "A warm narrator.  Emphasise BRAND names.",
            "A warm narrator.\nEmphasise BRAND names.",
        ] {
            XCTAssertNotEqual(
                key,
                Qwen3ConditioningPrefixCacheKey.voiceDesign(language: "english", voiceDescription: edited),
                edited
            )
        }
    }

    /// The prefix embeds the instruction trimmed at its ends, so text that
    /// differs only there is the same prompt and keeps its cache hit.
    func testOuterWhitespaceIsTheSamePromptBecauseThePrefixTrimsIt() {
        XCTAssertEqual(
            Qwen3ConditioningPrefixCacheKey.voiceDesign(language: "english", voiceDescription: "  A calm voice.\n"),
            Qwen3ConditioningPrefixCacheKey.voiceDesign(language: "english", voiceDescription: "A calm voice.")
        )
        XCTAssertEqual(Qwen3ConditioningPrefixCacheKey.embeddedInstruction("  Speak softly. \n"), "Speak softly.")
        for absent in [nil, "", " \n "] as [String?] {
            XCTAssertEqual(
                Qwen3ConditioningPrefixCacheKey.customVoice(language: "english", speaker: "aiden", instruction: absent),
                Qwen3ConditioningPrefixCacheKey.customVoice(language: "english", speaker: "aiden", instruction: nil)
            )
        }
    }

    /// Language and speaker resolve case-insensitively when the prefix is
    /// built, so folding them keeps one entry per actual prompt.
    func testLanguageAndSpeakerFoldBecauseThePrefixResolvesThemCaseInsensitively() {
        XCTAssertEqual(
            Qwen3ConditioningPrefixCacheKey.customVoice(language: " English", speaker: "Aiden ", instruction: "Calm."),
            Qwen3ConditioningPrefixCacheKey.customVoice(language: "english", speaker: "aiden", instruction: "Calm.")
        )
        XCTAssertNotEqual(
            Qwen3ConditioningPrefixCacheKey.customVoice(language: "english", speaker: "aiden", instruction: "Calm."),
            Qwen3ConditioningPrefixCacheKey.voiceDesign(language: "english", voiceDescription: "Calm."),
            "Built-in Voice and Voice Design never share a prefix"
        )
    }
}
