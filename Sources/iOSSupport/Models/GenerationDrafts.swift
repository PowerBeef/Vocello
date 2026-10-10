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
        DeliveryProfile.studioSelection(
            presetID: selectedPresetID,
            intensity: selectedIntensity,
            customTone: mode == .custom ? customText : nil
        )
    }

    /// A preset picked from the Mac delivery menu, written as the iPhone's
    /// delivery sheet writes it: the preset at its shipped tier, with the
    /// Custom tone text kept for a later switch back.
    mutating func selectPreset(_ preset: EmotionPreset) {
        mode = .preset
        selectedPresetID = preset.id
        selectedIntensity = preset.shippedIntensity
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

extension VoiceDesignSavedVoiceCandidate {
    func matches(draft: VoiceDesignDraft) -> Bool {
        matches(voiceDescription: draft.voiceDescription, emotion: draft.emotion, text: draft.text)
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

    /// A one-off clip (imported, dropped or recorded) becomes the reference
    /// (U14). A transcript describes the clip it was hydrated, recognized or
    /// typed for, and the Studio shows the transcript field only while a clip
    /// is set, so any transcript here belongs to the clip being replaced: it
    /// is cleared, and recognition runs for the new clip, unless the same
    /// one-off file is chosen again. Returns whether the transcript was
    /// cleared.
    @discardableResult
    mutating func replaceReferenceAudio(with path: String) -> Bool {
        let clearsTranscript = selectedSavedVoiceID != nil || referenceAudioPath != path
        if clearsTranscript {
            referenceTranscript = ""
        }
        referenceAudioPath = path
        selectedSavedVoiceID = nil
        return clearsTranscript
    }

    /// The saved voice was deleted: a draft that uses it drops the reference,
    /// as the iPhone Voices screen does, so a voice re-created under the same
    /// name never inherits this draft's transcript (U14).
    mutating func savedVoiceWasDeleted(id: String) {
        guard selectedSavedVoiceID == id else { return }
        clearReference()
    }

    /// The saved voice's reference was replaced in place: its audio, and with
    /// it the transcript that describes it, are new. The draft's transcript
    /// (hydrated from, or edited for, the old clip) is dropped, so the Studio
    /// hydrates the voice from disk again (U14).
    mutating func savedVoiceReferenceWasReplaced(id: String) {
        guard selectedSavedVoiceID == id else { return }
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

/// The Clone Studio's proactive prime of one reference intent (U18).
///
/// A prime no longer pins the model: the idle unload releases a primed clone
/// model like any other. Releasing it closes engine admission for a moment,
/// which re-runs the screen's priming task with the same reference; priming
/// again then would reload the weights the unload just released, and again
/// after every idle window. A reference intent the screen saw primed is not
/// primed again until it changes (another reference, transcript or model) or
/// the screen is entered again; the take still primes on demand.
struct CloneProactivePrimingIntent: Equatable {
    private(set) var primedKey: String?
    private var currentKey: String?

    mutating func shouldPrime(key: String) -> Bool {
        if currentKey != key {
            currentKey = key
            primedKey = nil
        }
        return key != primedKey
    }

    /// Records `key` once the engine publishes it primed.
    mutating func recordPrime(key: String, preparationState: ClonePreparationState) {
        guard currentKey == key, preparationState.isPrimed, preparationState.key == key else { return }
        primedKey = key
    }

    /// Leaving the screen ends the intent; returning to it primes again.
    mutating func reset() {
        currentKey = nil
        primedKey = nil
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
