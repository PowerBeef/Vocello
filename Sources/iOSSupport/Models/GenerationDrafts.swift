import Foundation
import QwenVoiceCore

private let appDisplayName = "Vocello"

enum DeliveryInputMode: String, Equatable {
    case preset
    case custom
}

struct DeliveryInputState: Equatable {
    private static let neutralPresetID = "neutral"

    var mode: DeliveryInputMode = .preset
    var selectedPresetID = DeliveryInputState.neutralPresetID
    var selectedIntensity: EmotionIntensity = .normal
    var customText = ""

    init(
        mode: DeliveryInputMode = .preset,
        selectedPresetID: String = DeliveryInputState.neutralPresetID,
        // Every new selection ships its preset's shipped tier
        // (`EmotionPreset.shippedIntensity`, written by the delivery sheet on
        // each pick): the DP-8 strong anchor -- DP-3 (2026-08-02) measured
        // `strong` at nearly double the recognisability of `normal` -- except
        // happy/angry, which ship their normal copy (DP-22 branch (a),
        // maintainer call 2026-08-15). This default only covers the fresh
        // draft (Neutral, whose shipped tier is strong). The user-facing
        // intensity control stays retired; the tier survives so the delivery
        // matrix harness can address both texts, and drafts saved before any
        // shipped-tier change keep resolving to exactly what they stored.
        selectedIntensity: EmotionIntensity = .strong,
        customText: String = ""
    ) {
        self.mode = mode
        self.selectedPresetID = selectedPresetID
        self.selectedIntensity = selectedIntensity
        self.customText = customText
    }

    init(legacyEmotion: String) {
        let trimmedEmotion = legacyEmotion.trimmingCharacters(in: .whitespacesAndNewlines)

        if DeliveryProfile.isNeutralInstruction(trimmedEmotion) {
            self.init()
            return
        }

        // Look across all intensities so a saved "strong" instruction round-trips correctly.
        for preset in EmotionPreset.all {
            for intensity in EmotionIntensity.allCases {
                if preset.instruction(for: intensity).caseInsensitiveCompare(trimmedEmotion) == .orderedSame {
                    self.init(mode: .preset, selectedPresetID: preset.id, selectedIntensity: intensity)
                    return
                }
            }
        }

        self.init(mode: .custom, customText: trimmedEmotion)
    }

    /// Always false: the intensity control was retired 2026-08-02. Kept as the
    /// single place the UI asks, so restoring the control is a one-line change
    /// if a future measurement earns it back.
    var supportsIntensity: Bool { false }

    var resolvedDeliveryProfile: DeliveryProfile {
        switch mode {
        case .preset:
            guard let preset = EmotionPreset.preset(id: selectedPresetID) else {
                return .neutral
            }
            return DeliveryProfile.preset(preset, intensity: selectedIntensity)
        case .custom:
            guard let trimmedCustomText = customText.trimmingCharacters(in: .whitespacesAndNewlines).nilIfEmpty else {
                return .neutral
            }
            return DeliveryProfile.custom(trimmedCustomText)
        }
    }

    var resolvedDeliveryInstruction: String {
        resolvedDeliveryProfile.finalInstruction
    }

    var selectedPresetLabel: String {
        guard let preset = EmotionPreset.preset(id: selectedPresetID) else {
            return DeliveryProfile.neutralInstruction
        }
        return preset.label
    }
}

struct CustomVoiceDraft: Equatable {
    var selectedSpeaker = TTSModel.defaultSpeaker
    /// A pinned effective sampling seed: when set, every generate request
    /// carries it so a liked take reproduces exactly; nil = fresh seed each
    /// take (the default stochastic-with-retry norm, DP-15).
    var pinnedSeed: UInt64?
    var selectedLanguage = Qwen3SupportedLanguage.auto
    var delivery = DeliveryInputState()
    var text = ""

    var resolvedDeliveryProfile: DeliveryProfile {
        delivery.resolvedDeliveryProfile
    }

    var resolvedDeliveryInstruction: String {
        delivery.resolvedDeliveryInstruction
    }

    var emotion: String {
        get { resolvedDeliveryInstruction }
        set { delivery = DeliveryInputState(legacyEmotion: newValue) }
    }
}

struct VoiceDesignDraft: Equatable {
    var voiceDescription = ""
    var pinnedSeed: UInt64?
    var selectedLanguage = Qwen3SupportedLanguage.auto
    var delivery = DeliveryInputState()
    var text = ""

    var resolvedDeliveryProfile: DeliveryProfile {
        delivery.resolvedDeliveryProfile
    }

    var resolvedDeliveryInstruction: String {
        delivery.resolvedDeliveryInstruction
    }

    var emotion: String {
        get { resolvedDeliveryInstruction }
        set { delivery = DeliveryInputState(legacyEmotion: newValue) }
    }
}

struct VoiceCloningDraft: Equatable {
    var selectedSavedVoiceID: String?
    var pinnedSeed: UInt64?
    var referenceAudioPath: String?
    var selectedLanguage = Qwen3SupportedLanguage.auto
    var referenceTranscript = ""
    var text = ""

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

        if !draft.referenceTranscript.isEmpty || !voice.hasTranscript || transcriptLoadError != nil {
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
        cloneConsentAcknowledged: Bool,
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

        // Mirrors macOS: the readiness note must agree with the consent gate
        // (found disagreeing on the bank's first real use, 2026-08-04).
        if !cloneConsentAcknowledged {
            return VoiceCloningReadinessDescriptor(
                noteIsReady: false,
                title: "Acknowledge voice cloning consent",
                detail: "Voice cloning needs the one-time consent in Settings: clone only voices you have permission to use.",
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

        if text.isEmpty {
            return VoiceCloningReadinessDescriptor(
                noteIsReady: false,
                title: "Add a script",
                detail: "Reference is ready. Add the line for the cloned voice.",
                trailingText: nil
            )
        }

        // The transcript is what unlocks in-context prosody transfer: without
        // it the engine falls back to speaker-embedding-only conditioning —
        // identity without pacing or emotion. Visible by requirement of the
        // 2026-08-04 delivery-control audit (F8); mirrors the macOS copy.
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

private extension String {
    var nilIfEmpty: String? {
        isEmpty ? nil : self
    }
}
