import Foundation
import QwenVoiceCore

struct CustomVoiceDraft: Equatable {
    var selectedSpeaker = TTSModel.defaultSpeaker
    // .auto = follow the typed prompt's detected language (the selector shows
    // the effective language, e.g. "French (Auto)"). Matches the other modes;
    // generation resolves .auto through the same detector, and undetectable
    // text falls back to english in qwenLanguageHint's custom branch — so the
    // old .english default's behavior is preserved for English scripts.
    var selectedLanguage = Qwen3SupportedLanguage.auto
    var emotion = EmotionPreset.neutralPresetInstruction
    var text = ""

    var hasText: Bool {
        !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var shouldIdlePrewarm: Bool {
        hasText
    }

    var idlePrewarmDebounceKey: String? {
        guard shouldIdlePrewarm else { return nil }
        return [
            selectedSpeaker,
            selectedLanguage.rawValue,
            emotion,
            text,
        ].joined(separator: "|")
    }
}

struct VoiceDesignDraft: Equatable {
    var voiceDescription = ""
    var selectedLanguage = Qwen3SupportedLanguage.auto
    var emotion = EmotionPreset.neutralPresetInstruction
    var text = ""

    var hasVoiceDescription: Bool {
        !voiceDescription.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var hasText: Bool {
        !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var shouldIdlePrewarm: Bool {
        hasVoiceDescription && hasText
    }

    var idlePrewarmDebounceKey: String? {
        guard shouldIdlePrewarm else { return nil }
        return [
            voiceDescription,
            selectedLanguage.rawValue,
            emotion,
            text,
        ].joined(separator: "|")
    }
}

struct VoiceCloningDraft: Equatable {
    var selectedSavedVoiceID: String?
    var referenceAudioPath: String?
    var selectedLanguage = Qwen3SupportedLanguage.auto
    var referenceTranscript = ""
    var text = ""

    var hasText: Bool {
        !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var trimmedReferenceTranscript: String? {
        let trimmed = referenceTranscript.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }

    mutating func applySavedVoice(_ voice: Voice, transcript: String) {
        selectedSavedVoiceID = voice.id
        referenceAudioPath = voice.wavPath
        referenceTranscript = transcript
    }

    mutating func applySavedVoiceSelection(
        id: String,
        wavPath: String,
        transcript: String
    ) {
        selectedSavedVoiceID = id
        referenceAudioPath = wavPath
        referenceTranscript = transcript
    }

    func referencesSavedVoice(_ voice: Voice) -> Bool {
        selectedSavedVoiceID == voice.id && referenceAudioPath == voice.wavPath
    }

    mutating func clearReference() {
        selectedSavedVoiceID = nil
        referenceAudioPath = nil
        referenceTranscript = ""
    }
}

struct PendingVoiceCloningHandoff: Equatable {
    let savedVoiceID: String
    let wavPath: String
    let transcript: String
    let transcriptLoadError: String?
}

enum SavedVoiceCloneHydrationAction: Equatable {
    case none
    case acceptCurrentDraft
    case applyFromDisk
    case clearStaleSelection
}

enum SavedVoiceCloneHydration {
    static func loadTranscript(for voice: Voice, fileManager: FileManager = .default) throws -> String {
        try voice.loadTranscript(fileManager: fileManager) ?? ""
    }

    static func action(
        draft: VoiceCloningDraft,
        voice: Voice?,
        hydratedVoiceID: String?,
        transcriptLoadError: String?
    ) -> SavedVoiceCloneHydrationAction {
        guard draft.selectedSavedVoiceID != nil else { return .none }
        guard let voice else { return .clearStaleSelection }

        guard draft.referencesSavedVoice(voice) else {
            return .applyFromDisk
        }

        if hydratedVoiceID == voice.id {
            return .none
        }

        if draft.trimmedReferenceTranscript != nil || !voice.hasTranscript || transcriptLoadError != nil {
            return .acceptCurrentDraft
        }

        return .applyFromDisk
    }
}

enum VoiceCloningContextStatus: Equatable {
    case waitingForHydration
    case preparing
    case primed
    case fallback(String)
}

struct VoiceCloningReadinessDescriptor: Equatable {
    let noteIsReady: Bool
    let title: String
    let detail: String
    let trailingText: String?
}

enum VoiceCloningReadiness {
    static func describe(
        engineReady: Bool,
        isModelAvailable: Bool,
        modelDisplayName: String,
        referenceAudioPath: String?,
        hasReferenceTranscript: Bool,
        text: String,
        contextStatus: VoiceCloningContextStatus?
    ) -> VoiceCloningReadinessDescriptor {
        if !engineReady {
            return VoiceCloningReadinessDescriptor(
                noteIsReady: false,
                title: "Engine starting",
                detail: "The engine is still preparing.",
                trailingText: nil
            )
        }

        if !isModelAvailable {
            return VoiceCloningReadinessDescriptor(
                noteIsReady: false,
                title: "Install the active model",
                detail: "Install \(modelDisplayName) in Models to enable generation.",
                trailingText: nil
            )
        }

        guard referenceAudioPath != nil else {
            return VoiceCloningReadinessDescriptor(
                noteIsReady: false,
                title: "Add a reference",
                detail: "Saved voices or imported clips both work. Pick one before writing the line.",
                trailingText: nil
            )
        }

        if case .waitingForHydration = contextStatus {
            return VoiceCloningReadinessDescriptor(
                noteIsReady: false,
                title: "Preparing saved voice",
                detail: "Loading the saved transcript and voice context.",
                trailingText: nil
            )
        }

        if case .preparing = contextStatus {
            return VoiceCloningReadinessDescriptor(
                noteIsReady: false,
                title: "Preparing voice context",
                detail: "Priming this reference so final generation starts cleanly.",
                trailingText: nil
            )
        }

        if text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return VoiceCloningReadinessDescriptor(
                noteIsReady: false,
                title: "Add a script",
                detail: "Reference is ready. Add the line for the cloned voice.",
                trailingText: nil
            )
        }

        // The transcript is what unlocks in-context prosody transfer: without
        // it the engine falls back to speaker-embedding-only conditioning —
        // identity without pacing or emotion. That fallback used to be
        // silent; the 2026-08-04 delivery-control audit (F8) requires it to
        // be visible. Generation still proceeds, so this stays a ready state.
        if !hasReferenceTranscript {
            return VoiceCloningReadinessDescriptor(
                noteIsReady: true,
                title: "Ready — identity only",
                detail: "This reference has no transcript, so only the voice's identity is cloned. Add a transcript to carry its pacing and emotion into the take.",
                trailingText: "Ready"
            )
        }

        if case .fallback(let message) = contextStatus {
            return VoiceCloningReadinessDescriptor(
                noteIsReady: true,
                title: "Reference ready with slower first run",
                detail: message,
                trailingText: "Ready"
            )
        }

        return VoiceCloningReadinessDescriptor(
            noteIsReady: true,
            title: "Ready to generate",
            detail: "Ready to generate and save.",
            trailingText: "Ready"
        )
    }
}
