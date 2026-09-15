import Foundation

enum LongTextGenerationRouter {
    /// Single-take texts up to this length generate directly; longer scripts
    /// route to the long-form v4 planner. The limit is the shared
    /// `GenerationTextLimitPolicy.singleTakeScriptLimit` (900) both apps use;
    /// macOS keeps counting the trimmed script as it always has.
    static let directGenerationCharacterLimit = GenerationTextLimitPolicy.singleTakeScriptLimit

    static func shouldRouteToLongFormBatch(_ text: String) -> Bool {
        text.trimmingCharacters(in: .whitespacesAndNewlines).count > directGenerationCharacterLimit
    }
}
