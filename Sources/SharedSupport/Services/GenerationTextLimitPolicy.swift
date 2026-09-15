import Foundation
import QwenVoiceCore

/// Script-length policy shared by the iOS Studio (`IOSGenerationTextLimitPolicy`
/// forwards here) and the macOS long-form router. Pure counts and routing; the
/// user-facing messages live in each platform's presentation owner.
struct GenerationTextLimitPolicy {
    /// Single-take spoken-script ceiling. The delivery-validated 900-character
    /// boundary: the engine's 2,048-token cap (~170 s of audio) comfortably
    /// covers it, and the raise was gated on an on-device memory-qualified proof
    /// at this length (2026-07-24). Longer scripts route to a long-form project.
    static let singleTakeScriptLimit = 900

    /// Hard editor ceiling for long-form scripts; the planner's 100-segment cap
    /// is the authoritative project-size gate.
    static let longFormScriptLimit = 30_000

    /// Voice Design brief (the voice description) limit, from the shared catalog.
    static let descriptionLimit = VoiceDesignBriefCatalog.descriptionLimit

    /// Delivery instruction / custom tone limit (2-3 dense sentences).
    static let deliveryInstructionLimit = 500

    struct State: Equatable {
        let count: Int
        let limit: Int
        let trimmedIsEmpty: Bool

        var remainingCount: Int {
            max(limit - count, 0)
        }

        /// Scripts above the single-take limit run as a long-form project.
        var routesToLongForm: Bool {
            count > limit
        }

        /// Only the hard long-form ceiling blocks generation.
        var isOverLimit: Bool {
            count > GenerationTextLimitPolicy.longFormScriptLimit
        }

        /// The ceiling the editor counter shows: the single-take limit for
        /// ordinary scripts, the long-form ceiling once routing engages.
        var displayLimit: Int {
            routesToLongForm ? GenerationTextLimitPolicy.longFormScriptLimit : limit
        }

        var counterText: String {
            "\(count)/\(displayLimit)"
        }
    }

    static func state(for text: String, mode: GenerationMode) -> State {
        State(
            count: text.count,
            limit: limit(for: mode),
            trimmedIsEmpty: text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        )
    }

    static func clamped(_ text: String, mode: GenerationMode) -> String {
        guard text.count > longFormScriptLimit else { return text }
        return String(text.prefix(longFormScriptLimit))
    }

    static func limit(for mode: GenerationMode) -> Int {
        singleTakeScriptLimit
    }
}
