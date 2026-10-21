import Foundation
import QwenVoiceCore

/// The Mac app's settings keys in its preferences domain (`com.qwenvoice.app`),
/// shared by the app and the `vocello` CLI (VocelloDesktopCore compiles this
/// file by path) so the two never read different keys.
enum MacAppSettingsKeys {
    /// Play a take when it finishes (default true).
    static let autoPlay = "autoPlay"
    /// The folder new takes are written to; empty for the default outputs folder.
    static let outputDirectory = "outputDirectory"
    /// The sampling variation (`Qwen3SamplingVariation` raw value; default expressive).
    static let generationVariation = "generationVariation"
    /// "Prefer lower-memory models" (the legacy key name is kept for existing preferences).
    static let preferSpeedEverywhere = "QwenVoice.PreferSpeedEverywhere"
    /// A mode's explicit model package choice (`speed`, `quality`); absent means automatic.
    static func variantPreference(for mode: GenerationMode) -> String {
        "QwenVoice.MacModelVariantPreference." + mode.rawValue
    }
}
