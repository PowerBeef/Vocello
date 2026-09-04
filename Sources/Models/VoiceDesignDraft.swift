import Foundation
import QwenVoiceCore

struct VoiceDesignDraft: Equatable {
    var voiceDescription = ""
    var pinnedSeed: UInt64?
    var selectedLanguage = Qwen3SupportedLanguage.auto
    var emotion = EmotionPreset.neutralPresetInstruction
    var text = ""

    var hasVoiceDescription: Bool {
        !voiceDescription.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var hasText: Bool {
        !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var shouldIdlePrewarm: Bool { hasVoiceDescription && hasText }

    var idlePrewarmDebounceKey: String? {
        guard shouldIdlePrewarm else { return nil }
        return [voiceDescription, selectedLanguage.rawValue, emotion, text].joined(separator: "|")
    }
}
