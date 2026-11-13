import Foundation
import QwenVoiceCore

/// Script-length policy shared by the iOS Studio (`IOSGenerationTextLimitPolicy`
/// forwards here) and the macOS long-form router. Pure counts and routing; the
/// user-facing messages live in each platform's presentation owner.
struct GenerationTextLimitPolicy {
    /// Single-take ceiling in characters of an alphabetic script: the
    /// delivery-validated 900-character take (on-device memory-qualified proof,
    /// 2026-07-24). The routing applies it to the script's single-take length,
    /// where a Han, kana or Hangul character counts three
    /// (`SingleTakeScriptBudget`, U01): a Chinese or Japanese take stops near
    /// 300 characters, inside the engine's 2,048-token cap. Longer scripts
    /// route to a long-form project.
    static let singleTakeScriptLimit = SingleTakeScriptBudget.characterLimit

    /// Hard editor ceiling for long-form scripts; the planner's 100-segment cap
    /// is the authoritative project-size gate.
    static let longFormScriptLimit = 30_000

    /// Voice Design brief (the voice description) limit, from the shared catalog.
    static let descriptionLimit = VoiceDesignBriefCatalog.descriptionLimit

    /// Delivery instruction / custom tone limit (2-3 dense sentences).
    static let deliveryInstructionLimit = 500

    struct State: Equatable {
        /// Characters (grapheme clusters) of the script.
        let count: Int
        let limit: Int
        /// The length the single-take limit applies to (CJK counts three).
        let singleTakeLength: Int
        /// Whether Han, kana or Hangul characters are most of the script, so
        /// the counter speaks in those characters.
        let countsEastAsianCharacters: Bool
        let trimmedIsEmpty: Bool
        /// The script has a letter or a digit to speak (U29). A script of only
        /// punctuation, symbols or emoji keeps Generate disabled like an empty
        /// one, because the model ends such a take before any audio.
        let hasSpeakableText: Bool
        /// A script that runs as a long-form project and that Auto sends as
        /// Korean: both apps warn before it starts, because Korean long-form
        /// projects stop at a failed segment far more often than any other
        /// language (RF-60). Measured only for a long-form script.
        let warnsKoreanLongForm: Bool

        /// Characters left for a single take, in the script's own characters:
        /// Chinese or Japanese characters for a CJK script, letters otherwise.
        var remainingCount: Int {
            let remainingLength = max(limit - singleTakeLength, 0)
            return countsEastAsianCharacters
                ? remainingLength / SingleTakeScriptBudget.eastAsianCharacterWeight
                : remainingLength
        }

        /// Scripts above the single-take limit run as a long-form project.
        var routesToLongForm: Bool {
            singleTakeLength > limit
        }

        /// Only the hard long-form ceiling blocks generation.
        var isOverLimit: Bool {
            count > GenerationTextLimitPolicy.longFormScriptLimit
        }

        /// The ceiling the editor counter shows: the single-take limit in the
        /// script's own characters for ordinary scripts, the long-form ceiling
        /// once routing engages.
        var displayLimit: Int {
            routesToLongForm ? GenerationTextLimitPolicy.longFormScriptLimit : count + remainingCount
        }

        var counterText: String {
            "\(count)/\(displayLimit)"
        }
    }

    static func state(for text: String, mode: GenerationMode) -> State {
        let measure = SingleTakeScriptBudget.measure(text)
        return State(
            count: measure.characters,
            limit: limit(for: mode),
            singleTakeLength: measure.singleTakeLength,
            countsEastAsianCharacters: measure.eastAsianCharacters * 2 > measure.characters,
            trimmedIsEmpty: text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
            hasSpeakableText: measure.hasSpeakableContent,
            warnsKoreanLongForm: measure.exceedsSingleTake && GenerationSemantics.resolvesToKorean(text)
        )
    }

    /// Whether a single take may carry `text`; above the limit it is a
    /// long-form project. One predicate for both apps, the Mac line batch and
    /// the CLI (`SingleTakeScriptBudget`).
    static func exceedsSingleTake(_ text: String) -> Bool {
        SingleTakeScriptBudget.exceedsSingleTake(text)
    }

    /// Whether a long-form project of `text` gets the Korean caution (RF-60):
    /// Auto sends it as Korean. The caller decides that the script runs as a
    /// long-form project (the Mac batch sheet runs any length as one).
    static func warnsKoreanLongForm(_ text: String) -> Bool {
        GenerationSemantics.resolvesToKorean(text)
    }

    /// Whether a script has anything to speak (U29).
    static func hasSpeakableText(_ text: String) -> Bool {
        SingleTakeScriptBudget.hasSpeakableContent(text)
    }

    /// Whether a Voice Design brief says anything: whitespace alone is no
    /// brief on either app (P01-06).
    static func hasVoiceDescription(_ voiceDescription: String) -> Bool {
        !voiceDescription.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    static func clamped(_ text: String, mode: GenerationMode) -> String {
        guard text.count > longFormScriptLimit else { return text }
        return String(text.prefix(longFormScriptLimit))
    }

    static func limit(for mode: GenerationMode) -> Int {
        singleTakeScriptLimit
    }
}
