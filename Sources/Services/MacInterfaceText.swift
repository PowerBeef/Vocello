import Foundation

/// Typed interface vocabulary for the macOS app: every user-visible literal the macOS views
/// present goes through here and `Localizable.xcstrings` (keys `vocello.mac.*`, English source,
/// French maintained alongside, translator context on every entry). Views read plain `String`s,
/// so the catalog is the one owner and `scripts/localization_contract.py` binds each key to
/// exactly one default here. Stored names, model ids, seeds, license bodies and generation text
/// never enter this vocabulary.
enum MacInterfaceText {
    private static let localization = VocelloLocalization()
    static var cancel: String {
        localization.string(localized: "vocello.mac.common.cancel", defaultValue: "Cancel",
               comment: "macOS interface: generic cancel button. Presentation only.")
    }
    static var close: String {
        localization.string(localized: "vocello.mac.common.close", defaultValue: "Close",
               comment: "macOS interface: dismiss a popover or sheet. Presentation only.")
    }
    static var delete: String {
        localization.string(localized: "vocello.mac.common.delete", defaultValue: "Delete",
               comment: "macOS interface: destructive confirmation button. Presentation only.")
    }
    static var historyDeleteDetail: String {
        localization.string(localized: "vocello.mac.history.deleteDetail", defaultValue: "This will permanently delete the generation and its audio file.",
               comment: "macOS interface: History delete confirmation body. Presentation only.")
    }
    static var historyDeleteTitle: String {
        localization.string(localized: "vocello.mac.history.deleteTitle", defaultValue: "Delete Generation?",
               comment: "macOS interface: History delete confirmation title. Presentation only.")
    }
    static var historyFinishedAudioWaiting: String {
        localization.string(localized: "vocello.mac.history.finishedAudioWaiting", defaultValue: "Finished audio is waiting for History",
               comment: "macOS interface: History recovery banner title for unqueued generations. Presentation only.")
    }
    static func historyPinSeed(_ seed: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.history.pinSeed",
            defaultValue: "Pin seed %1$@ for new takes",
            comment: "macOS interface: History row action. %1$@ is the numeric sampling seed, never translated."), seed)
    }
    static var historyRevealAudio: String {
        localization.string(localized: "vocello.mac.history.revealAudio", defaultValue: "Reveal Audio",
               comment: "macOS interface: History recovery banner action that reveals the retained audio in Finder. Presentation only.")
    }
    static var historyRevealInFinder: String {
        localization.string(localized: "vocello.mac.history.revealInFinder", defaultValue: "Reveal in Finder",
               comment: "macOS interface: History row action. Presentation only.")
    }
    static var historySaveToSavedVoices: String {
        localization.string(localized: "vocello.mac.history.saveToSavedVoices", defaultValue: "Save to Saved Voices",
               comment: "macOS interface: VoiceOver label of the History action that saves a generation as a voice. Presentation only.")
    }
    static var ok: String {
        localization.string(localized: "vocello.mac.common.ok", defaultValue: "OK",
               comment: "macOS interface: acknowledge an alert. Presentation only.")
    }
    static var recordMicrophoneDeniedDetail: String {
        localization.string(localized: "vocello.mac.record.microphoneDeniedDetail", defaultValue: "Vocello needs the microphone to record reference clips. Enable it in System Settings to continue.",
               comment: "macOS interface: recorder alert body when the microphone permission is denied. Presentation only.")
    }
    static var recordMicrophoneDeniedTitle: String {
        localization.string(localized: "vocello.mac.record.microphoneDeniedTitle", defaultValue: "Microphone access denied",
               comment: "macOS interface: recorder alert title when the microphone permission is denied. Presentation only.")
    }
    static var recordOpenSystemSettings: String {
        localization.string(localized: "vocello.mac.record.openSystemSettings", defaultValue: "Open System Settings",
               comment: "macOS interface: recorder alert action that opens the privacy pane. Presentation only.")
    }
    static var recordRecord: String {
        localization.string(localized: "vocello.mac.record.record", defaultValue: "Record",
               comment: "macOS interface: recorder start button. Presentation only.")
    }
    static var recordRetake: String {
        localization.string(localized: "vocello.mac.record.retake", defaultValue: "Retake",
               comment: "macOS interface: recorder button that discards the take and records again. Presentation only.")
    }
    static var recordStop: String {
        localization.string(localized: "vocello.mac.record.stop", defaultValue: "Stop",
               comment: "macOS interface: recorder stop button. Presentation only.")
    }
    static var recordTitle: String {
        localization.string(localized: "vocello.mac.record.title", defaultValue: "Record Reference Clip",
               comment: "macOS interface: recorder sheet title. Presentation only.")
    }
    static var retry: String {
        localization.string(localized: "vocello.mac.common.retry", defaultValue: "Retry",
               comment: "macOS interface: retry a failed operation. Presentation only.")
    }
    static var savedVoiceAudioPlaceholder: String {
        localization.string(localized: "vocello.mac.savedVoice.audioPlaceholder", defaultValue: "Reference audio file",
               comment: "macOS interface: Saved Voice sheet audio path field placeholder. Presentation only.")
    }
    static var savedVoiceAudioSection: String {
        localization.string(localized: "vocello.mac.savedVoice.audioSection", defaultValue: "Audio",
               comment: "macOS interface: Saved Voice sheet section header. Presentation only.")
    }
    static var savedVoiceBrowse: String {
        localization.string(localized: "vocello.mac.savedVoice.browse", defaultValue: "Browse...",
               comment: "macOS interface: Saved Voice sheet button that opens the file chooser. Presentation only.")
    }
    static var savedVoiceDiscardAndReRecord: String {
        localization.string(localized: "vocello.mac.savedVoice.discardAndReRecord", defaultValue: "Discard and re-record",
               comment: "macOS interface: Saved Voice sheet choice after a recording warning. Presentation only.")
    }
    static var savedVoiceKeepVoice: String {
        localization.string(localized: "vocello.mac.savedVoice.keepVoice", defaultValue: "Keep voice",
               comment: "macOS interface: Saved Voice sheet choice after a recording warning. Presentation only.")
    }
    static var savedVoiceNamePlaceholder: String {
        localization.string(localized: "vocello.mac.savedVoice.namePlaceholder", defaultValue: "Saved voice name",
               comment: "macOS interface: Saved Voice sheet name field placeholder. Presentation only.")
    }
    static var savedVoiceNameSection: String {
        localization.string(localized: "vocello.mac.savedVoice.nameSection", defaultValue: "Name",
               comment: "macOS interface: Saved Voice sheet section header. Presentation only.")
    }
    static var savedVoiceRecord: String {
        localization.string(localized: "vocello.mac.savedVoice.record", defaultValue: "Record...",
               comment: "macOS interface: Saved Voice sheet button that opens the recorder. Presentation only.")
    }
    static var savedVoiceTranscriptHelp: String {
        localization.string(localized: "vocello.mac.savedVoice.transcriptHelp", defaultValue: "Transcript-backed voices can reuse prepared Qwen3 clone prompts; audio-only voices remain available as a lower-guidance fallback.",
               comment: "macOS interface: Saved Voice sheet explanation under the transcript field. Presentation only.")
    }
    static var savedVoiceTranscriptSection: String {
        localization.string(localized: "vocello.mac.savedVoice.transcriptSection", defaultValue: "Transcript (recommended for reusable clones)",
               comment: "macOS interface: Saved Voice sheet section header. Presentation only.")
    }
    static var tryAgain: String {
        localization.string(localized: "vocello.mac.common.tryAgain", defaultValue: "Try Again",
               comment: "macOS interface: reload after a failed load. Presentation only.")
    }
    static var voicesAudioOnlyFallback: String {
        localization.string(localized: "vocello.mac.voices.audioOnlyFallback", defaultValue: "Audio-only fallback",
               comment: "macOS interface: Saved Voices status chip for a voice without a transcript. Presentation only.")
    }
    static func voicesDeleteDetail(_ name: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.voices.deleteDetail",
            defaultValue: "This will permanently remove “%1$@” from Saved Voices.",
            comment: "macOS interface: Saved Voices delete confirmation body. %1$@ is the saved voice name, never translated."), name)
    }
    static var voicesDeleteTitle: String {
        localization.string(localized: "vocello.mac.voices.deleteTitle", defaultValue: "Delete Saved Voice?",
               comment: "macOS interface: Saved Voices delete confirmation title. Presentation only.")
    }
    static var voicesDetailAudioOnly: String {
        localization.string(localized: "vocello.mac.voices.detailAudioOnly", defaultValue: "Add a transcript for the strongest clone.",
               comment: "macOS interface: Saved Voices row detail for an audio-only voice. Presentation only.")
    }
    static var voicesDetailTranscript: String {
        localization.string(localized: "vocello.mac.voices.detailTranscript", defaultValue: "Clone prompt prepares on first use.",
               comment: "macOS interface: Saved Voices row detail for a transcript-backed voice. Presentation only.")
    }
    static var voicesEmpty: String {
        localization.string(localized: "vocello.mac.voices.empty", defaultValue: "Add a voice sample from the toolbar, then use it in Voice Cloning.",
               comment: "macOS interface: Saved Voices empty state. Presentation only.")
    }
    static var voicesLoading: String {
        localization.string(localized: "vocello.mac.voices.loading", defaultValue: "Loading saved voices...",
               comment: "macOS interface: Saved Voices loading placeholder. Presentation only.")
    }
    static var voicesOpenInCloning: String {
        localization.string(localized: "vocello.mac.voices.openInCloning", defaultValue: "Open in Cloning",
               comment: "macOS interface: Saved Voices row action that selects the voice in Voice Cloning. Presentation only.")
    }
    static var voicesPreview: String {
        localization.string(localized: "vocello.mac.voices.preview", defaultValue: "Preview",
               comment: "macOS interface: Saved Voices row action that plays the reference clip. Presentation only.")
    }
    static var voicesQualityWarningAccessibility: String {
        localization.string(localized: "vocello.mac.voices.qualityWarningAccessibility", defaultValue: "Reference quality warning",
               comment: "macOS interface: VoiceOver label of the reference-quality warning pill. Presentation only.")
    }
    static var voicesReferenceOutsideRange: String {
        localization.string(localized: "vocello.mac.voices.referenceOutsideRange", defaultValue: "Reference outside recommended range",
               comment: "macOS interface: reference-quality popover title. Presentation only.")
    }
    static var voicesReferenceOutsideRangeShort: String {
        localization.string(localized: "vocello.mac.voices.referenceOutsideRangeShort", defaultValue: "Reference outside range",
               comment: "macOS interface: compact warning pill label when no specific warning token is known. Presentation only.")
    }
    static var voicesReplaceReference: String {
        localization.string(localized: "vocello.mac.voices.replaceReference", defaultValue: "Replace reference…",
               comment: "macOS interface: opens the sheet that replaces a saved voice's reference clip. Presentation only.")
    }
    static var voicesTranscriptBacked: String {
        localization.string(localized: "vocello.mac.voices.transcriptBacked", defaultValue: "Transcript-backed",
               comment: "macOS interface: Saved Voices status chip for a voice with a transcript. Presentation only.")
    }
    static var voicesWaitingForEngine: String {
        localization.string(localized: "vocello.mac.voices.waitingForEngine", defaultValue: "Saved voices will appear once the speech engine is ready.",
               comment: "macOS interface: Saved Voices placeholder while the engine starts. Presentation only.")
    }
}
