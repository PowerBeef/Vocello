import Foundation

/// Typed interface vocabulary for the macOS app: every user-visible literal the macOS views
/// present goes through here and `Localizable.xcstrings` (keys `vocello.mac.*`, English source,
/// French maintained alongside, translator context on every entry). Views read plain `String`s,
/// so the catalog is the one owner and `scripts/localization_contract.py` binds each key to
/// exactly one default here. Stored names, model ids, seeds, license bodies and generation text
/// never enter this vocabulary.
enum MacInterfaceText {
    private static let localization = VocelloLocalization()
    static var batchCurrentDelivery: String {
        localization.string(localized: "vocello.mac.batch.currentDelivery", defaultValue: "Current delivery",
               comment: "macOS interface: batch sheet group box title. Presentation only.")
    }
    static var batchInstructions: String {
        localization.string(localized: "vocello.mac.batch.instructions", defaultValue: "Enter one line per generation, or drag a `.txt` file onto this sheet.",
               comment: "macOS interface: batch sheet instructions. Presentation only.")
    }
    static func batchLine(_ number: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.batch.line",
            defaultValue: "Line %1$@",
            comment: "macOS interface: batch row caption. %1$@ is the 1-based line number."), number)
    }
    static var batchLineByLine: String {
        localization.string(localized: "vocello.mac.batch.lineByLine", defaultValue: "Line-by-line",
               comment: "macOS interface: batch segmentation choice. Presentation only.")
    }
    static var batchLongForm: String {
        localization.string(localized: "vocello.mac.batch.longForm", defaultValue: "Long form",
               comment: "macOS interface: batch segmentation choice. Presentation only.")
    }
    static var batchRegenerate: String {
        localization.string(localized: "vocello.mac.batch.regenerate", defaultValue: "Regenerate",
               comment: "macOS interface: batch row action. Presentation only.")
    }
    static var batchResumeMissing: String {
        localization.string(localized: "vocello.mac.batch.resumeMissing", defaultValue: "Resume Missing Segments",
               comment: "macOS interface: batch sheet action. Presentation only.")
    }
    static var batchRetryFailed: String {
        localization.string(localized: "vocello.mac.batch.retryFailed", defaultValue: "Retry Failed",
               comment: "macOS interface: batch sheet action. Presentation only.")
    }
    static var batchRetryRemaining: String {
        localization.string(localized: "vocello.mac.batch.retryRemaining", defaultValue: "Retry Remaining",
               comment: "macOS interface: batch sheet action. Presentation only.")
    }
    static var batchRevealOutputs: String {
        localization.string(localized: "vocello.mac.batch.revealOutputs", defaultValue: "Reveal Outputs",
               comment: "macOS interface: batch sheet action that reveals the output folder. Presentation only.")
    }
    static var batchSegmentation: String {
        localization.string(localized: "vocello.mac.batch.segmentation", defaultValue: "Segmentation",
               comment: "macOS interface: batch sheet picker label. Presentation only.")
    }
    static var batchTitle: String {
        localization.string(localized: "vocello.mac.batch.title", defaultValue: "Batch Generation",
               comment: "macOS interface: batch sheet title. Presentation only.")
    }
    static var brandAccessibility: String {
        localization.string(localized: "vocello.mac.sidebar.brandAccessibility", defaultValue: "Vocello, AI text to speech",
               comment: "macOS interface: VoiceOver label of the brand lockup. Presentation only.")
    }
    static var brandName: String {
        localization.string(localized: "vocello.mac.sidebar.brandName", defaultValue: "Vocello",
               comment: "macOS interface: product wordmark in the sidebar and startup diagnostics; not translated. Presentation only.")
    }
    static var brandTagline: String {
        localization.string(localized: "vocello.mac.sidebar.brandTagline", defaultValue: "AI·TTS",
               comment: "macOS interface: short tagline under the wordmark. Presentation only.")
    }
    static var briefHelper: String {
        localization.string(localized: "vocello.mac.brief.helper", defaultValue: "Combine character, age, accent, and texture.",
               comment: "macOS interface: caption of the Voice Design brief editor. Presentation only.")
    }
    static func briefStartingPointAccessibility(_ starter: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.brief.startingPointAccessibility",
            defaultValue: "Starting point: %1$@",
            comment: "macOS interface: VoiceOver label of one brief starter. %1$@ is the starter text shown as editable model content, never translated."), starter)
    }
    static var briefStartingPoints: String {
        localization.string(localized: "vocello.mac.brief.startingPoints", defaultValue: "Starting points",
               comment: "macOS interface: Voice Design brief starters menu title. Presentation only.")
    }
    static var cancel: String {
        localization.string(localized: "vocello.mac.common.cancel", defaultValue: "Cancel",
               comment: "macOS interface: generic cancel button. Presentation only.")
    }
    static var clear: String {
        localization.string(localized: "vocello.mac.common.clear", defaultValue: "Clear",
               comment: "macOS interface: clears the current selection or field. Presentation only.")
    }
    static var cloningAudioOnlySavedVoice: String {
        localization.string(localized: "vocello.mac.cloning.audioOnlySavedVoice", defaultValue: "Audio-only saved voice",
               comment: "macOS interface: Voice Cloning source status for a saved voice without a transcript. Presentation only.")
    }
    static var cloningChooseSavedVoice: String {
        localization.string(localized: "vocello.mac.cloning.chooseSavedVoice", defaultValue: "Choose a saved voice",
               comment: "macOS interface: Voice Cloning saved-voice picker empty choice. Presentation only.")
    }
    static var cloningConsentOneTime: String {
        localization.string(localized: "vocello.mac.cloning.consentOneTime", defaultValue: "One-time acknowledgment. Review it anytime in Settings.",
               comment: "macOS interface: note under the inline cloning consent. Presentation only.")
    }
    static var cloningImportedFileReady: String {
        localization.string(localized: "vocello.mac.cloning.importedFileReady", defaultValue: "Imported file ready",
               comment: "macOS interface: Voice Cloning source status for an imported clip. Presentation only.")
    }
    static var cloningNoReference: String {
        localization.string(localized: "vocello.mac.cloning.noReference", defaultValue: "No reference selected.",
               comment: "macOS interface: Voice Cloning placeholder when no reference is chosen. Presentation only.")
    }
    static var cloningSavedVoice: String {
        localization.string(localized: "vocello.mac.cloning.savedVoice", defaultValue: "Saved voice",
               comment: "macOS interface: Voice Cloning saved-voice picker label. Presentation only.")
    }
    static var cloningSourceHelp: String {
        localization.string(localized: "vocello.mac.cloning.sourceHelp", defaultValue: "Choose a saved voice, import a reference clip, or record one with your microphone. Use clips you own or have permission to clone.",
               comment: "macOS interface: tooltip of the Voice Cloning source section. Presentation only.")
    }
    static var cloningTranscriptAccessibility: String {
        localization.string(localized: "vocello.mac.cloning.transcriptAccessibility", defaultValue: "Transcript",
               comment: "macOS interface: VoiceOver label of the Voice Cloning transcript field. Presentation only.")
    }
    static var cloningTranscriptBackedSavedVoice: String {
        localization.string(localized: "vocello.mac.cloning.transcriptBackedSavedVoice", defaultValue: "Transcript-backed saved voice",
               comment: "macOS interface: Voice Cloning source status for a saved voice with a transcript. Presentation only.")
    }
    static var cloningTranscriptHelp: String {
        localization.string(localized: "vocello.mac.cloning.transcriptHelp", defaultValue: "Best quality uses reference audio plus an accurate transcript. Audio-only cloning remains available as a lower-guidance fallback.",
               comment: "macOS interface: tooltip of the Voice Cloning transcript field. Presentation only.")
    }
    static var close: String {
        localization.string(localized: "vocello.mac.common.close", defaultValue: "Close",
               comment: "macOS interface: dismiss a popover or sheet. Presentation only.")
    }
    static var customAllSpeakers: String {
        localization.string(localized: "vocello.mac.custom.allSpeakers", defaultValue: "All speakers",
               comment: "macOS interface: Built-in Voice speaker picker section. Presentation only.")
    }
    static var customSpeaker: String {
        localization.string(localized: "vocello.mac.custom.speaker", defaultValue: "Speaker",
               comment: "macOS interface: Built-in Voice speaker picker label. Presentation only.")
    }
    static var delete: String {
        localization.string(localized: "vocello.mac.common.delete", defaultValue: "Delete",
               comment: "macOS interface: destructive confirmation button. Presentation only.")
    }
    static var delivery: String {
        localization.string(localized: "vocello.mac.cloning.delivery", defaultValue: "Delivery",
               comment: "macOS interface: label and picker title for a voice bank's delivery variants. Presentation only.")
    }
    static var deliveryNeutral: String {
        localization.string(localized: "vocello.mac.cloning.deliveryNeutral", defaultValue: "Neutral",
               comment: "macOS interface: the base delivery of a voice bank persona. Presentation only.")
    }
    static var designSavedToSavedVoices: String {
        localization.string(localized: "vocello.mac.design.savedToSavedVoices", defaultValue: "Saved to Saved Voices",
               comment: "macOS interface: Voice Design confirmation after saving the designed voice. Presentation only.")
    }
    static var done: String {
        localization.string(localized: "vocello.mac.common.done", defaultValue: "Done",
               comment: "macOS interface: closes a finished sheet. Presentation only.")
    }
    static var emotionCustom: String {
        localization.string(localized: "vocello.mac.emotion.custom", defaultValue: "Custom",
               comment: "macOS interface: delivery picker choice for a free-text tone. Presentation only.")
    }
    static var emotionCustomTone: String {
        localization.string(localized: "vocello.mac.emotion.customTone", defaultValue: "Custom tone",
               comment: "macOS interface: label of the free-text delivery field. Presentation only.")
    }
    static var emotionCustomTonePlaceholder: String {
        localization.string(localized: "vocello.mac.emotion.customTonePlaceholder", defaultValue: "e.g. whispered, close-mic and breathy",
               comment: "macOS interface: placeholder of the free-text delivery field. Presentation only.")
    }
    static var emotionDirectionalHints: String {
        localization.string(localized: "vocello.mac.emotion.directionalHints", defaultValue: "Directional hints",
               comment: "macOS interface: delivery picker section. Presentation only.")
    }
    static var emotionDistinctDeliveries: String {
        localization.string(localized: "vocello.mac.emotion.distinctDeliveries", defaultValue: "Distinct deliveries",
               comment: "macOS interface: delivery picker section. Presentation only.")
    }
    static var emotionIntensity: String {
        localization.string(localized: "vocello.mac.emotion.intensity", defaultValue: "Intensity",
               comment: "macOS interface: delivery intensity label and picker title. Presentation only.")
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
    static var menuBuiltInVoice: String {
        localization.string(localized: "vocello.mac.menu.builtInVoice", defaultValue: "Built-in Voice",
               comment: "macOS interface: Navigate menu command that opens the Built-in Voice screen. Presentation only.")
    }
    static var menuHistory: String {
        localization.string(localized: "vocello.mac.menu.history", defaultValue: "History",
               comment: "macOS interface: Navigate menu command that opens History. Presentation only.")
    }
    static var menuModels: String {
        localization.string(localized: "vocello.mac.menu.models", defaultValue: "Models",
               comment: "macOS interface: Navigate menu command that opens Settings. Presentation only.")
    }
    static var menuNavigate: String {
        localization.string(localized: "vocello.mac.menu.navigate", defaultValue: "Navigate",
               comment: "macOS interface: application menu title. Presentation only.")
    }
    static var menuOpenOutputFolder: String {
        localization.string(localized: "vocello.mac.menu.openOutputFolder", defaultValue: "Open Output Folder",
               comment: "macOS interface: File menu command. Presentation only.")
    }
    static var menuPlayPause: String {
        localization.string(localized: "vocello.mac.menu.playPause", defaultValue: "Play / Pause",
               comment: "macOS interface: Playback menu command. Presentation only.")
    }
    static var menuPlayback: String {
        localization.string(localized: "vocello.mac.menu.playback", defaultValue: "Playback",
               comment: "macOS interface: application menu title. Presentation only.")
    }
    static var menuSavedVoices: String {
        localization.string(localized: "vocello.mac.menu.savedVoices", defaultValue: "Saved Voices",
               comment: "macOS interface: Navigate menu command that opens Saved Voices. Presentation only.")
    }
    static var menuStop: String {
        localization.string(localized: "vocello.mac.menu.stop", defaultValue: "Stop",
               comment: "macOS interface: Playback menu command. Presentation only.")
    }
    static var menuVoiceCloning: String {
        localization.string(localized: "vocello.mac.menu.voiceCloning", defaultValue: "Voice Cloning",
               comment: "macOS interface: Navigate menu command that opens Voice Cloning. Presentation only.")
    }
    static var menuVoiceDesign: String {
        localization.string(localized: "vocello.mac.menu.voiceDesign", defaultValue: "Voice Design",
               comment: "macOS interface: Navigate menu command that opens Voice Design. Presentation only.")
    }
    static var ok: String {
        localization.string(localized: "vocello.mac.common.ok", defaultValue: "OK",
               comment: "macOS interface: acknowledge an alert. Presentation only.")
    }
    static var playerClose: String {
        localization.string(localized: "vocello.mac.player.close", defaultValue: "Close player",
               comment: "macOS interface: VoiceOver label of the sidebar player close button. Presentation only.")
    }
    static var playerLive: String {
        localization.string(localized: "vocello.mac.player.live", defaultValue: "Live",
               comment: "macOS interface: sidebar player badge while streaming audio plays. Presentation only.")
    }
    static var playerPosition: String {
        localization.string(localized: "vocello.mac.player.position", defaultValue: "Playback position",
               comment: "macOS interface: VoiceOver label of the sidebar player scrubber. Presentation only.")
    }
    static var playerTitle: String {
        localization.string(localized: "vocello.mac.player.title", defaultValue: "Player",
               comment: "macOS interface: sidebar player title. Presentation only.")
    }
    static var recommendedForScript: String {
        localization.string(localized: "vocello.mac.common.recommendedForScript", defaultValue: "Recommended for your script",
               comment: "macOS interface: picker section of speakers or languages matching the script. Presentation only.")
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
    static var revealInFinder: String {
        localization.string(localized: "vocello.mac.common.revealInFinder", defaultValue: "Reveal in Finder",
               comment: "macOS interface: reveal a file or folder in Finder (File menu, Settings, model menu). Presentation only.")
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
    static var settingsApplicationData: String {
        localization.string(localized: "vocello.mac.settings.applicationData", defaultValue: "Application data",
               comment: "macOS interface: Settings labeled row title. Presentation only.")
    }
    static var settingsAutoPlay: String {
        localization.string(localized: "vocello.mac.settings.autoPlay", defaultValue: "Auto-play generated audio",
               comment: "macOS interface: Settings toggle. Presentation only.")
    }
    static var settingsCancelDownloadHelp: String {
        localization.string(localized: "vocello.mac.settings.cancelDownloadHelp", defaultValue: "Cancel the download (discards partial data)",
               comment: "macOS interface: tooltip of the cancel-download action. Presentation only.")
    }
    static var settingsChoose: String {
        localization.string(localized: "vocello.mac.settings.choose", defaultValue: "Choose…",
               comment: "macOS interface: Settings button that opens the folder chooser. Presentation only.")
    }
    static var settingsCloneConsent: String {
        localization.string(localized: "vocello.mac.settings.cloneConsent", defaultValue: "I own or have permission to clone the voices I use",
               comment: "macOS interface: voice cloning consent toggle title. Presentation only.")
    }
    static var settingsCloneConsentDetail: String {
        localization.string(localized: "vocello.mac.settings.cloneConsentDetail", defaultValue: "Only clone voices you own or have explicit permission to use.",
               comment: "macOS interface: voice cloning consent detail. Presentation only.")
    }
    static var settingsCloneDisclosure: String {
        localization.string(localized: "vocello.mac.settings.cloneDisclosure", defaultValue: "If you publish audio of a cloned real voice, disclose that it is AI-generated. EU law may require this.",
               comment: "macOS interface: EU AI Act Article 50 disclosure reminder under the consent toggle. Presentation only.")
    }
    static var settingsDeleteModel: String {
        localization.string(localized: "vocello.mac.settings.deleteModel", defaultValue: "Delete Model",
               comment: "macOS interface: Manage menu item that deletes an installed model. Presentation only.")
    }
    static var settingsDeleteModelTitle: String {
        localization.string(localized: "vocello.mac.settings.deleteModelTitle", defaultValue: "Delete Model?",
               comment: "macOS interface: model deletion confirmation title. Presentation only.")
    }
    static var settingsDownloadRecommended: String {
        localization.string(localized: "vocello.mac.settings.downloadRecommended", defaultValue: "Download recommended",
               comment: "macOS interface: button that installs the recommended packages. Presentation only.")
    }
    static var settingsGeneration: String {
        localization.string(localized: "vocello.mac.settings.generation", defaultValue: "Generation",
               comment: "macOS interface: Settings section header. Presentation only.")
    }
    static var settingsHeavy: String {
        localization.string(localized: "vocello.mac.settings.heavy", defaultValue: "Heavy",
               comment: "macOS interface: package badge for a variant that strains this Mac. Presentation only.")
    }
    static var settingsHeavyOnThisMac: String {
        localization.string(localized: "vocello.mac.settings.heavyOnThisMac", defaultValue: "Heavy on this Mac",
               comment: "macOS interface: tooltip and VoiceOver label of the Heavy badge. Presentation only.")
    }
    static var settingsManage: String {
        localization.string(localized: "vocello.mac.settings.manage", defaultValue: "Manage",
               comment: "macOS interface: package action that opens the Manage menu; must fit a 92-point slot. Presentation only.")
    }
    static func settingsManageHelp(_ variant: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.settings.manageHelp",
            defaultValue: "Manage %1$@ variant",
            comment: "macOS interface: tooltip of the Manage action. %1$@ is the variant display name (Speed or Quality), never translated here."), variant)
    }
    static var settingsModelDownloads: String {
        localization.string(localized: "vocello.mac.settings.modelDownloads", defaultValue: "Model downloads",
               comment: "macOS interface: Settings section header. Presentation only.")
    }
    static var settingsOutputDirectory: String {
        localization.string(localized: "vocello.mac.settings.outputDirectory", defaultValue: "Output directory",
               comment: "macOS interface: Settings labeled row title. Presentation only.")
    }
    static var settingsPerformance: String {
        localization.string(localized: "vocello.mac.settings.performance", defaultValue: "Performance",
               comment: "macOS interface: Settings section header. Presentation only.")
    }
    static var settingsPlayback: String {
        localization.string(localized: "vocello.mac.settings.playback", defaultValue: "Playback",
               comment: "macOS interface: Settings section header. Presentation only.")
    }
    static var settingsPreferLowerMemory: String {
        localization.string(localized: "vocello.mac.settings.preferLowerMemory", defaultValue: "Prefer lower-memory models",
               comment: "macOS interface: Settings toggle title. Presentation only.")
    }
    static var settingsPreferLowerMemoryDetail: String {
        localization.string(localized: "vocello.mac.settings.preferLowerMemoryDetail", defaultValue: "Pins every generation mode to the Speed package. Speed uses less memory and is safer on lower-RAM Macs, with lower fidelity than Quality. You can still switch per-generation in the mode screens; this toggle just changes the defaults.",
               comment: "macOS interface: Settings toggle detail. Speed and Quality are package tier names. Presentation only.")
    }
    static var settingsRecommended: String {
        localization.string(localized: "vocello.mac.settings.recommended", defaultValue: "Recommended",
               comment: "macOS interface: package badge for the variant that fits this Mac. Presentation only.")
    }
    static var settingsRepair: String {
        localization.string(localized: "vocello.mac.settings.repair", defaultValue: "Repair",
               comment: "macOS interface: package action that re-downloads damaged files. Presentation only.")
    }
    static var settingsReset: String {
        localization.string(localized: "vocello.mac.settings.reset", defaultValue: "Reset",
               comment: "macOS interface: Settings button that restores the default output folder. Presentation only.")
    }
    static var settingsStorage: String {
        localization.string(localized: "vocello.mac.settings.storage", defaultValue: "Storage",
               comment: "macOS interface: Settings section header. Presentation only.")
    }
    static var settingsTitle: String {
        localization.string(localized: "vocello.mac.settings.title", defaultValue: "Settings",
               comment: "macOS interface: Settings screen navigation title. Presentation only.")
    }
    static var settingsUpdate: String {
        localization.string(localized: "vocello.mac.settings.update", defaultValue: "Update",
               comment: "macOS interface: package action that downloads the re-pinned artifact. Presentation only.")
    }
    static var settingsUpdateHelp: String {
        localization.string(localized: "vocello.mac.settings.updateHelp", defaultValue: "Download the updated model package",
               comment: "macOS interface: tooltip of the update action. Presentation only.")
    }
    static var settingsVariation: String {
        localization.string(localized: "vocello.mac.settings.variation", defaultValue: "Variation",
               comment: "macOS interface: Settings picker label for sampling variation. Presentation only.")
    }
    static var settingsVariationHelp: String {
        localization.string(localized: "vocello.mac.settings.variationHelp", defaultValue: "How much takes vary when regenerating the same text. Expressive is the model's official sampling (liveliest); Balanced and Consistent trade some liveliness for steadier, more repeatable takes.",
               comment: "macOS interface: Settings footer under the Variation picker. Expressive, Balanced and Consistent are the picker's option names. Presentation only.")
    }
    static var settingsVoiceCloning: String {
        localization.string(localized: "vocello.mac.settings.voiceCloning", defaultValue: "Voice cloning",
               comment: "macOS interface: Settings section header. Presentation only.")
    }
    static var startupBundlePath: String {
        localization.string(localized: "vocello.mac.startup.bundlePath", defaultValue: "Bundle path",
               comment: "macOS interface: startup diagnostics row title. Presentation only.")
    }
    static var startupCannotContinue: String {
        localization.string(localized: "vocello.mac.startup.cannotContinue", defaultValue: "The app can't continue until its native resources are valid. You can retry the startup checks or copy the diagnostics for troubleshooting.",
               comment: "macOS interface: startup diagnostics explanation. Presentation only.")
    }
    static var startupCopyDiagnostics: String {
        localization.string(localized: "vocello.mac.startup.copyDiagnostics", defaultValue: "Copy Diagnostics",
               comment: "macOS interface: startup diagnostics button. Presentation only.")
    }
    static var startupManifestPath: String {
        localization.string(localized: "vocello.mac.startup.manifestPath", defaultValue: "Manifest path",
               comment: "macOS interface: startup diagnostics row title. Presentation only.")
    }
    static var startupResourcesPath: String {
        localization.string(localized: "vocello.mac.startup.resourcesPath", defaultValue: "Resources path",
               comment: "macOS interface: startup diagnostics row title. Presentation only.")
    }
    static var startupUnderlyingError: String {
        localization.string(localized: "vocello.mac.startup.underlyingError", defaultValue: "Underlying error",
               comment: "macOS interface: startup diagnostics heading above the raw error text. Presentation only.")
    }
    static var statusEngine: String {
        localization.string(localized: "vocello.mac.status.engine", defaultValue: "Engine",
               comment: "macOS interface: sidebar status heading. Presentation only.")
    }
    static var statusError: String {
        localization.string(localized: "vocello.mac.status.error", defaultValue: "Error",
               comment: "macOS interface: sidebar engine status. Presentation only.")
    }
    static var statusReady: String {
        localization.string(localized: "vocello.mac.status.ready", defaultValue: "Ready",
               comment: "macOS interface: sidebar engine status. Presentation only.")
    }
    static var statusStandby: String {
        localization.string(localized: "vocello.mac.status.standby", defaultValue: "Standby",
               comment: "macOS interface: sidebar engine status. Presentation only.")
    }
    static var statusStarting: String {
        localization.string(localized: "vocello.mac.status.starting", defaultValue: "Starting engine…",
               comment: "macOS interface: sidebar engine status. Presentation only.")
    }
    static var textInputBatch: String {
        localization.string(localized: "vocello.mac.textInput.batch", defaultValue: "Batch",
               comment: "macOS interface: opens the batch generation sheet. Presentation only.")
    }
    static var textInputGenerate: String {
        localization.string(localized: "vocello.mac.textInput.generate", defaultValue: "Generate",
               comment: "macOS interface: primary generate action. Presentation only.")
    }
    static func textInputSeed(_ seed: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.textInput.seed",
            defaultValue: "Seed %1$@",
            comment: "macOS interface: pinned seed chip. %1$@ is the numeric seed, never translated."), seed)
    }
    static func textInputSeedPinnedHelp(_ seed: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.textInput.seedPinnedHelp",
            defaultValue: "Takes reproduce pinned seed %1$@ with identical settings",
            comment: "macOS interface: tooltip of the pinned seed chip. %1$@ is the numeric seed, never translated."), seed)
    }
    static var textInputUnpinHelp: String {
        localization.string(localized: "vocello.mac.textInput.unpinHelp", defaultValue: "Unpin — new seed each take",
               comment: "macOS interface: tooltip of the seed unpin button. Presentation only.")
    }
    static var textInputUnpinSeed: String {
        localization.string(localized: "vocello.mac.textInput.unpinSeed", defaultValue: "Unpin seed",
               comment: "macOS interface: VoiceOver label of the seed unpin button. Presentation only.")
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
    static var workflowAllLanguages: String {
        localization.string(localized: "vocello.mac.workflow.allLanguages", defaultValue: "All languages",
               comment: "macOS interface: language picker section. Presentation only.")
    }
    static var workflowHeavyHelp: String {
        localization.string(localized: "vocello.mac.workflow.heavyHelp", defaultValue: "This package is heavy for this Mac's memory. Generation may be slow or unstable under pressure.",
               comment: "macOS interface: tooltip of the Heavy badge in the generation workflow. Presentation only.")
    }
    static var workflowModel: String {
        localization.string(localized: "vocello.mac.workflow.model", defaultValue: "Model",
               comment: "macOS interface: package picker label. Presentation only.")
    }
    static func workflowPackageHelp(_ mode: String, _ status: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.workflow.packageHelp",
            defaultValue: "Choose the Qwen3-TTS package for %1$@. Current status: %2$@.",
            comment: "macOS interface: tooltip of the package picker. %1$@ is the mode name, %2$@ the status caption; both already localized."), mode, status)
    }
}
