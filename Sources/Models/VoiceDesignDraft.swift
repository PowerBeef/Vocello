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

/// The designed take of the current brief that can become a saved voice; it
/// stays offered only while the brief, delivery and script still match.
struct VoiceDesignSavedVoiceCandidate: Equatable {
    let audioPath: String
    let transcript: String
    let voiceDescription: String
    let emotion: String
    let text: String
    private(set) var savedVoiceName: String?

    var isSaved: Bool { savedVoiceName != nil }

    func matches(draft: VoiceDesignDraft) -> Bool {
        voiceDescription == draft.voiceDescription && emotion == draft.emotion && text == draft.text
    }

    mutating func markSaved(as voiceName: String) {
        savedVoiceName = voiceName
    }
}
