import Foundation
import QwenVoiceCore

struct IOSGenerationTextLimitPolicy {
    /// Single-take spoken-script ceiling. Matches the delivery-validated 900-character
    /// boundary shared with the macOS long-form router: the engine's 2,048-token cap
    /// (~170 s of audio) comfortably covers ~900 characters, and the raise is gated on
    /// an on-device memory-qualified proof at this length (2026-07-24). Scripts beyond
    /// it route to a long-form project (sequential streaming segments) rather than
    /// being blocked.
    private static let sharedScriptLimit = 900

    /// Hard editor ceiling for long-form scripts. Generously above any validated
    /// project while still bounding the planner input; the planner's 100-segment cap
    /// is the authoritative project-size gate.
    static let longFormScriptLimit = 30_000

    /// Voice Design BRIEF (the voice DESCRIPTION) limit — deliberately decoupled from the
    /// spoken-script limit above. Sourced from the shared catalog so the iOS sheet and the
    /// macOS inline editor stay in lockstep.
    static let descriptionLimit = VoiceDesignBriefCatalog.descriptionLimit

    /// Delivery instruction / custom tone limit. The instruction is passed to the model as an
    /// emotion/delivery style string.
    ///
    /// Research (Qwen3-TTS hosted API) allows up to 1,600 tokens for `instructions`, and the
    /// open-weights examples are short phrases. 500 characters gives users 2–3 dense,
    /// multidimensional sentences (emotion + pace + pitch + timbre) while discouraging
    /// paragraph-length prompts. It also leaves room for the English diction reinforcement
    /// clause appended during prompt assembly.
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

        /// Only the hard long-form ceiling blocks generation now.
        var isOverLimit: Bool {
            count > IOSGenerationTextLimitPolicy.longFormScriptLimit
        }

        /// The ceiling the editor counter should show: the single-take limit for
        /// ordinary scripts, the long-form ceiling once routing engages.
        var displayLimit: Int {
            routesToLongForm ? IOSGenerationTextLimitPolicy.longFormScriptLimit : limit
        }

        var counterText: String {
            "\(count)/\(displayLimit)"
        }

        var helperMessage: String {
            if isOverLimit {
                return warningMessage
            }
            if routesToLongForm {
                return VocelloPresentationText.longFormGuidance
            }
            if remainingCount == 0 {
                return VocelloPresentationText.longFormLimit
            }
            return VocelloPresentationText.charactersRemaining(remainingCount)
        }

        var warningMessage: String {
            VocelloPresentationText.shortenScript(IOSGenerationTextLimitPolicy.longFormScriptLimit)
        }

        var readinessTitle: String {
            VocelloPresentationText.shortenScriptTitle(IOSGenerationTextLimitPolicy.longFormScriptLimit)
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
        sharedScriptLimit
    }
}
