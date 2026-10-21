import Foundation
import QwenVoiceCore

/// The Settings → Generation "Variation" preference (GitHub #47): how much
/// takes vary when regenerating the same text. Persisted via `AppDefaults`
/// (debug-isolated like every preference) and stamped onto every
/// `GenerationRequest` by the mode coordinators and the batch runner.
enum GenerationVariationPreference {
    static let key = MacAppSettingsKeys.generationVariation
    static let defaultValue = Qwen3SamplingVariation.expressive.rawValue

    /// The variation to stamp on requests. Returns nil for `expressive`
    /// (the official checkpoint sampling) so default requests stay exactly
    /// as before — the engine treats nil and `.expressive` identically.
    static func requestValue() -> Qwen3SamplingVariation? {
        let raw = AppDefaults.store.string(forKey: key) ?? defaultValue
        let variation = Qwen3SamplingVariation(rawValue: raw) ?? .expressive
        return variation == .expressive ? nil : variation
    }
}
