import Foundation
import QwenVoiceCore

/// Shared presentation rules for the language selector across generation modes
/// (macOS `QwenLanguagePicker`, iOS Studio chips + `IOSQwenLanguagePickerSheet`).
///
/// Model: a stored selection of `.auto` means "follow detection" — the UI shows
/// the *effective* language (the detected one while following, else the pinned
/// pick). Picking a concrete language pins it; picking the Auto row resumes
/// following. Both Studios detect with `GenerationSemantics.autoDetectedLanguage`,
/// the resolver `GenerationSemantics.qwenLanguageHint` applies to `.auto` at
/// request time, so the display names the language the take is sent with
/// (U02). When it detects nothing the engine still falls back per mode.
enum LanguageSelectionPresentation {
    /// The language the generation will effectively use, for display purposes.
    static func effective(
        selected: Qwen3SupportedLanguage,
        detected: Qwen3SupportedLanguage
    ) -> Qwen3SupportedLanguage {
        selected == .auto && detected != .auto ? detected : selected
    }

    /// What the closed selector (menu button / Studio chip) reads: the plain
    /// effective name — "French" while following a detection, "Auto" while
    /// following with nothing detected, the pinned language's name otherwise.
    /// The auto-following STATE is conveyed outside the control (the macOS
    /// caption's "· Auto" suffix / the iOS sheet's Auto row), so the control
    /// never widens when detection kicks in.
    static func buttonLabel(
        selected: Qwen3SupportedLanguage,
        detected: Qwen3SupportedLanguage
    ) -> String {
        effective(selected: selected, detected: detected).displayName
    }

    /// True while the selector follows detection (stored Auto + a confident
    /// detection) — drives the caption suffix / hint at the call sites.
    static func isFollowingDetection(
        selected: Qwen3SupportedLanguage,
        detected: Qwen3SupportedLanguage
    ) -> Bool {
        selected == .auto && detected != .auto
    }
}
