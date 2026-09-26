import Foundation
import QwenVoiceCore

/// Typed interface vocabulary for the macOS app: every user-visible literal the macOS views
/// present goes through here and `Localizable.xcstrings` (keys `vocello.mac.*`, English source,
/// all ten interface languages maintained alongside, translator context on every entry). Views read plain `String`s,
/// so the catalog is the one owner and `scripts/localization_contract.py` binds each key to
/// exactly one default here. Stored names, model ids, seeds, license bodies and generation text
/// never enter this vocabulary.
enum MacInterfaceText {
    /// The interface language selected in Settings (`MacInterfaceLanguage`).
    private static var localization: VocelloLocalization { MacInterfaceLanguage.current }
    /// Shared presentation vocabulary, resolved through the Mac language owner.
    static var presentation: VocelloPresentationText { VocelloPresentationText(localization: localization) }
    /// Shared iOS navigation vocabulary, resolved through the Mac language owner.
    static var tabVoices: String { presentation.tabVoices }
    /// Typed engine and generation failures in the interface language (PA-20);
    /// see `VocelloPresentationText.generationFailureMessage(_:)`.
    static func generationFailureMessage(_ error: Error) -> String {
        presentation.generationFailureMessage(error)
    }
    static func studioModeTitle(_ mode: GenerationMode) -> String {
        let text = VocelloPresentationText(localization: localization)
        return switch mode {
        case .custom: text.modeBuiltIn
        case .design: text.modeDesign
        case .clone: text.modeClone
        }
    }

    static func activityGenerating(_ mode: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.activity.generating",
            defaultValue: "Generating %@…",
            comment: "macOS interface: sidebar activity label while a take renders; %@ is the mode name. Presentation only."), mode)
    }
    static var activityGeneratingAudio: String {
        localization.string(localized: "vocello.mac.activity.generatingAudio", defaultValue: "Generating audio…",
               comment: "macOS interface: sidebar activity label while the engine generates without a mode label. Presentation only.")
    }
    static var activityPreparingModel: String {
        localization.string(localized: "vocello.mac.activity.preparingModel", defaultValue: "Preparing model…",
               comment: "macOS interface: sidebar activity label while the engine loads a model. Presentation only.")
    }
    static var activityPreparingVoiceReference: String {
        localization.string(localized: "vocello.mac.activity.preparingVoiceReference", defaultValue: "Preparing voice reference…",
               comment: "macOS interface: sidebar activity label while a clone reference is prepared. Presentation only.")
    }
    static var audioFolderMissing: String {
        localization.string(localized: "vocello.mac.audio.folderMissing", defaultValue: "The chosen folder no longer exists — new audio saves to the default outputs folder.",
               comment: "macOS interface: Settings notice when the custom output folder disappeared. Presentation only.")
    }
    static var audioFolderNotWritable: String {
        localization.string(localized: "vocello.mac.audio.folderNotWritable", defaultValue: "The chosen folder isn't writable — new audio saves to the default outputs folder.",
               comment: "macOS interface: Settings notice when the custom output folder is read-only. Presentation only.")
    }
    static var batchBusy: String {
        localization.string(localized: "vocello.mac.batch.busy", defaultValue: "Wait for the current generation to finish.",
               comment: "macOS interface: batch sheet message when Generate All is pressed while the engine is already generating. Presentation only.")
    }
    static var batchCancelledNone: String {
        localization.string(localized: "vocello.mac.batch.cancelledNone", defaultValue: "Generation was cancelled before any clips were created.",
               comment: "macOS interface: batch cancellation message when nothing was saved. Presentation only.")
    }
    static func batchCancelledPartial(_ count: String, _ total: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.batch.cancelledPartial",
            defaultValue: "%1$@ of %2$@ clips generated before cancellation.",
            comment: "macOS interface: batch cancellation message; %1$@ saved count, %2$@ total. Presentation only."), count, total)
    }
    static var batchCancelledTitle: String {
        localization.string(localized: "vocello.mac.batch.cancelledTitle", defaultValue: "Batch Cancelled",
               comment: "macOS interface: batch cancellation title. Presentation only.")
    }
    static var batchCancelling: String {
        localization.string(localized: "vocello.mac.batch.cancelling", defaultValue: "Cancelling...",
               comment: "macOS interface: batch progress status while cancelling. Presentation only.")
    }
    static func batchClipsCompleted(_ count: String, _ total: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.batch.clipsCompleted",
            defaultValue: "%1$@ of %2$@ clips completed",
            comment: "macOS interface: batch progress count line; %1$@ completed, %2$@ total. Presentation only."), count, total)
    }
    static func batchClipsGenerated(_ count: Int) -> String {
        localization.format(localization.string(localized: "vocello.mac.batch.clipsGenerated",
            defaultValue: "%1$lld clips generated successfully.",
            comment: "macOS interface: batch completion message; %1$lld is the clip count (plural). Presentation only."), count)
    }
    static var batchComplete: String {
        localization.string(localized: "vocello.mac.batch.complete", defaultValue: "Batch Complete",
               comment: "macOS interface: batch completion title. Presentation only.")
    }
    static var batchCurrentBatch: String {
        localization.string(localized: "vocello.mac.batch.currentBatch", defaultValue: "Current batch",
               comment: "macOS interface: batch sheet heading of the item list while the batch runs. Presentation only.")
    }
    static var batchCurrentDelivery: String {
        localization.string(localized: "vocello.mac.batch.currentDelivery", defaultValue: "Current delivery",
               comment: "macOS interface: batch sheet group box title. Presentation only.")
    }
    static var batchGenerateAll: String {
        localization.string(localized: "vocello.mac.batch.generateAll", defaultValue: "Generate All",
               comment: "macOS interface: batch sheet primary button that starts the batch. Presentation only.")
    }
    static func batchGeneratingItem(_ index: String, _ total: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.batch.generatingItem",
            defaultValue: "Generating item %1$@/%2$@...",
            comment: "macOS interface: batch progress status; %1$@ item number, %2$@ total. Presentation only."), index, total)
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
    static var batchLongFormMode: String {
        localization.string(localized: "vocello.mac.batch.longFormMode", defaultValue: "Long-form",
               comment: "macOS interface: mode label of the long-form live and joined cards in the Studio dock. Presentation only.")
    }
    static var batchLongFormProject: String {
        localization.string(localized: "vocello.mac.batch.longFormProject", defaultValue: "Long-form project",
               comment: "macOS interface: voice name of the joined long-form card in the Studio dock. Presentation only.")
    }
    static var batchModelConfigurationMissing: String {
        localization.string(localized: "vocello.mac.batch.modelConfigurationMissing", defaultValue: "Model configuration not found",
               comment: "macOS interface: batch validation error when no model package is selected for the mode. Presentation only.")
    }
    static var batchNeedsReference: String {
        localization.string(localized: "vocello.mac.batch.needsReference", defaultValue: "Select a reference audio file before starting batch generation.",
               comment: "macOS interface: batch validation message for Voice Cloning. Presentation only.")
    }
    static var batchNeedsVoiceDescription: String {
        localization.string(localized: "vocello.mac.batch.needsVoiceDescription", defaultValue: "Enter a voice description before starting batch generation.",
               comment: "macOS interface: batch validation message for Voice Design. Presentation only.")
    }
    static var batchNewBatch: String {
        localization.string(localized: "vocello.mac.batch.newBatch", defaultValue: "New Batch",
               comment: "macOS interface: batch completion button that returns to the editor for another batch. Presentation only.")
    }
    static var batchOneClipGenerated: String {
        localization.string(localized: "vocello.mac.batch.oneClipGenerated", defaultValue: "1 clip generated successfully.",
               comment: "macOS interface: batch completion message for one clip. Presentation only.")
    }
    static var batchPlaceholder: String {
        localization.string(localized: "vocello.mac.batch.placeholder", defaultValue: "Enter one line per generation...",
               comment: "macOS interface: placeholder of the batch text editor. Presentation only.")
    }
    static func batchPlanningFailed(_ error: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.batch.planningFailed",
            defaultValue: "Long-form planning failed: %@",
            comment: "macOS interface: batch validation error when the long-form planner rejects the script; %@ is the error text. Presentation only."), error)
    }
    static var batchPreparedItems: String {
        localization.string(localized: "vocello.mac.batch.preparedItems", defaultValue: "Prepared items",
               comment: "macOS interface: batch sheet heading of the item list while no batch runs. Presentation only.")
    }
    static var batchPreparing: String {
        localization.string(localized: "vocello.mac.batch.preparing", defaultValue: "Preparing batch...",
               comment: "macOS interface: batch progress status before the first item starts. Presentation only.")
    }
    static var batchProcessing: String {
        localization.string(localized: "vocello.mac.batch.processing", defaultValue: "Processing…",
               comment: "macOS interface: batch sheet primary button label while the batch runs. Presentation only.")
    }
    static var batchRegenerate: String {
        localization.string(localized: "vocello.mac.batch.regenerate", defaultValue: "Regenerate",
               comment: "macOS interface: batch row action. Presentation only.")
    }
    static func batchRestartFailed(_ error: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.batch.restartFailed",
            defaultValue: "Batch generation was interrupted, but the backend could not be restarted: %@",
            comment: "macOS interface: appended to the cancelled batch message when the engine cancellation barrier failed; %@ is the error text. Presentation only."), error)
    }
    static var batchResults: String {
        localization.string(localized: "vocello.mac.batch.results", defaultValue: "Batch results",
               comment: "macOS interface: title of the batch results list. Presentation only.")
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
    static func batchSegmentTitle(_ number: String, _ total: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.batch.segmentTitle",
            defaultValue: "Segment %@ of %@",
            comment: "macOS interface: live card and streaming title of one long-form segment; the first %@ is the segment number, the second the total. Presentation only."), number, total)
    }
    static var batchSegmentation: String {
        localization.string(localized: "vocello.mac.batch.segmentation", defaultValue: "Segmentation",
               comment: "macOS interface: batch sheet picker label. Presentation only.")
    }
    static var batchStatusCancelled: String {
        localization.string(localized: "vocello.mac.batch.statusCancelled", defaultValue: "Cancelled",
               comment: "macOS interface: batch item status after cancellation. Presentation only.")
    }
    static var batchStatusFailed: String {
        localization.string(localized: "vocello.mac.batch.statusFailed", defaultValue: "Failed",
               comment: "macOS interface: batch item status after a failure. Presentation only.")
    }
    static var batchStatusPending: String {
        localization.string(localized: "vocello.mac.batch.statusPending", defaultValue: "Pending",
               comment: "macOS interface: batch item status before it starts. Presentation only.")
    }
    static var batchStatusRunning: String {
        localization.string(localized: "vocello.mac.batch.statusRunning", defaultValue: "Running",
               comment: "macOS interface: batch item status while it generates. Presentation only.")
    }
    static var batchStatusSaved: String {
        localization.string(localized: "vocello.mac.batch.statusSaved", defaultValue: "Saved",
               comment: "macOS interface: batch item status once its take is in History. Presentation only.")
    }
    static func batchStoppedNone(_ message: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.batch.stoppedNone",
            defaultValue: "Batch generation stopped before any clips were saved. %@",
            comment: "macOS interface: batch failure message when nothing was saved; %@ is the failure text. Presentation only."), message)
    }
    static func batchStoppedPartial(_ count: String, _ total: String, _ message: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.batch.stoppedPartial",
            defaultValue: "%1$@ of %2$@ clips were saved before the batch stopped. %3$@",
            comment: "macOS interface: batch failure message; %1$@ saved count, %2$@ total, %3$@ failure text. Presentation only."), count, total, message)
    }
    static var batchStoppedTitle: String {
        localization.string(localized: "vocello.mac.batch.stoppedTitle", defaultValue: "Batch Stopped",
               comment: "macOS interface: batch failure title. Presentation only.")
    }
    static var batchTitle: String {
        localization.string(localized: "vocello.mac.batch.title", defaultValue: "Batch Generation",
               comment: "macOS interface: batch sheet title. Presentation only.")
    }
    static func batchToneSummary(_ emotion: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.batch.toneSummary",
            defaultValue: "Tone: %@",
            comment: "macOS interface: batch sheet delivery summary line; %@ is the delivery instruction. Presentation only."), emotion)
    }
    static func batchTooLarge(_ count: String, _ maximum: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.batch.tooLarge",
            defaultValue: "Batch is too large: %@ segments exceeds the maximum of %@. Please split the text and try again.",
            comment: "macOS interface: batch validation error; the first %@ is the segment count, the second the maximum. Presentation only."), count, maximum)
    }
    static var batchViewHistory: String {
        localization.string(localized: "vocello.mac.batch.viewHistory", defaultValue: "View History",
               comment: "macOS interface: batch completion button that closes the sheet and opens History. Presentation only.")
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
    static var cloningAddReference: String {
        localization.string(localized: "vocello.mac.cloning.addReference", defaultValue: "Add a reference",
               comment: "macOS interface: Voice Cloning readiness title without a reference clip. Presentation only.")
    }
    static var cloningAddReferenceDetail: String {
        localization.string(localized: "vocello.mac.cloning.addReferenceDetail", defaultValue: "Saved voices or imported clips both work. Pick one before writing the line.",
               comment: "macOS interface: Voice Cloning readiness detail without a reference clip. Presentation only.")
    }
    static var cloningAddScriptDetail: String {
        localization.string(localized: "vocello.mac.cloning.addScriptDetail", defaultValue: "Reference is ready. Add the line for the cloned voice.",
               comment: "macOS interface: Voice Cloning readiness detail when the script is empty. Presentation only.")
    }
    static var cloningAudioOnlySavedVoice: String {
        localization.string(localized: "vocello.mac.cloning.audioOnlySavedVoice", defaultValue: "Audio-only saved voice",
               comment: "macOS interface: Voice Cloning source status for a saved voice without a transcript. Presentation only.")
    }
    static var cloningChooseSavedVoice: String {
        localization.string(localized: "vocello.mac.cloning.chooseSavedVoice", defaultValue: "Choose a saved voice",
               comment: "macOS interface: Voice Cloning saved-voice picker empty choice. Presentation only.")
    }
    static var cloningConsentDetail: String {
        localization.string(localized: "vocello.mac.cloning.consentDetail", defaultValue: "Confirm the one-time acknowledgment below: clone only voices you have permission to use.",
               comment: "macOS interface: Voice Cloning readiness detail before the one-time consent. Presentation only.")
    }
    static var cloningConsentOneTime: String {
        localization.string(localized: "vocello.mac.cloning.consentOneTime", defaultValue: "One-time acknowledgment. Review it anytime in Settings.",
               comment: "macOS interface: note under the inline cloning consent. Presentation only.")
    }
    static var cloningConsentTitle: String {
        localization.string(localized: "vocello.mac.cloning.consentTitle", defaultValue: "Acknowledge voice cloning consent",
               comment: "macOS interface: Voice Cloning readiness title before the one-time consent. Presentation only.")
    }
    static var cloningConsentRequiredToGenerate: String {
        localization.string(localized: "vocello.mac.cloning.consentRequiredToGenerate", defaultValue: "Enable voice-cloning consent in Settings → Voice cloning before generating.",
               comment: "macOS interface: error when a voice-cloning take is refused because consent was not acknowledged; names the macOS Settings section. Presentation only.")
    }
    static var cloningConsentRequiredToSaveVoice: String {
        localization.string(localized: "vocello.mac.cloning.consentRequiredToSaveVoice", defaultValue: "Enable voice-cloning consent in Settings → Voice cloning before saving a voice.",
               comment: "macOS interface: error when saving a voice is refused because voice-cloning consent was not acknowledged; names the macOS Settings section. Presentation only.")
    }
    /// PA-17: the copy the core consent policy raises on the Mac. The shared
    /// presentation copy names the iPhone's Settings → Privacy; the Mac toggle
    /// lives under Settings → Voice cloning.
    static var voiceCloningConsentRefusalCopy: VoiceCloningConsentPolicy.RefusalCopy {
        VoiceCloningConsentPolicy.RefusalCopy(
            generation: cloningConsentRequiredToGenerate,
            enrollment: cloningConsentRequiredToSaveVoice
        )
    }
    static func cloningEntryAudioOnly(_ name: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.cloning.entryAudioOnly",
            defaultValue: "%@ · audio only",
            comment: "macOS interface: reference menu row for a saved voice without a transcript; %@ is the voice name. Presentation only."), name)
    }
    static func cloningEntryTranscript(_ name: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.cloning.entryTranscript",
            defaultValue: "%@ · transcript",
            comment: "macOS interface: reference menu row for a transcript-backed saved voice; %@ is the voice name. Presentation only."), name)
    }
    static var cloningImport: String {
        localization.string(localized: "vocello.mac.cloning.import", defaultValue: "Import",
               comment: "macOS interface: chip that opens the file panel for a reference clip. Presentation only.")
    }
    static var cloningImportedFileReady: String {
        localization.string(localized: "vocello.mac.cloning.importedFileReady", defaultValue: "Imported file ready",
               comment: "macOS interface: Voice Cloning source status for an imported clip. Presentation only.")
    }
    static var cloningNoReference: String {
        localization.string(localized: "vocello.mac.cloning.noReference", defaultValue: "No reference selected.",
               comment: "macOS interface: Voice Cloning placeholder when no reference is chosen. Presentation only.")
    }
    static var cloningPermittedClipsOnly: String {
        localization.string(localized: "vocello.mac.cloning.permittedClipsOnly", defaultValue: "Use permitted clips only.",
               comment: "macOS interface: consent hint under the reference source row. Presentation only.")
    }
    static var cloningPreparingContext: String {
        localization.string(localized: "vocello.mac.cloning.preparingContext", defaultValue: "Preparing voice context",
               comment: "macOS interface: Voice Cloning readiness title while the reference is primed. Presentation only.")
    }
    static var cloningPreparingContextDetail: String {
        localization.string(localized: "vocello.mac.cloning.preparingContextDetail", defaultValue: "Priming this reference so final generation starts cleanly.",
               comment: "macOS interface: Voice Cloning readiness detail while the reference is primed. Presentation only.")
    }
    static var cloningPreparingSavedVoice: String {
        localization.string(localized: "vocello.mac.cloning.preparingSavedVoice", defaultValue: "Preparing saved voice",
               comment: "macOS interface: Voice Cloning readiness title while a saved voice loads. Presentation only.")
    }
    static var cloningPreparingSavedVoiceDetail: String {
        localization.string(localized: "vocello.mac.cloning.preparingSavedVoiceDetail", defaultValue: "Loading the saved transcript and voice context.",
               comment: "macOS interface: Voice Cloning readiness detail while a saved voice loads. Presentation only.")
    }
    static var cloningReadyIdentityOnly: String {
        localization.string(localized: "vocello.mac.cloning.readyIdentityOnly", defaultValue: "Ready — identity only",
               comment: "macOS interface: Voice Cloning readiness title when the reference has no transcript. Presentation only.")
    }
    static var cloningReadyIdentityOnlyDetail: String {
        localization.string(localized: "vocello.mac.cloning.readyIdentityOnlyDetail", defaultValue: "This reference has no transcript, so only the voice's identity is cloned. Add a transcript to carry its pacing and emotion into the take.",
               comment: "macOS interface: Voice Cloning readiness detail when the reference has no transcript. Presentation only.")
    }
    static var cloningReadySlowerFirstRun: String {
        localization.string(localized: "vocello.mac.cloning.readySlowerFirstRun", defaultValue: "Reference ready with slower first run",
               comment: "macOS interface: Voice Cloning readiness title when the context fell back to a slower path. Presentation only.")
    }
    static var cloningReferenceRequired: String {
        localization.string(localized: "vocello.mac.cloning.referenceRequired", defaultValue: "Select a reference audio file before generating.",
               comment: "macOS interface: Voice Cloning error when Generate runs without a reference. Presentation only.")
    }
    static var cloningReferenceSection: String {
        localization.string(localized: "vocello.mac.cloning.referenceSection", defaultValue: "Reference",
               comment: "macOS interface: title of the Voice Cloning configuration card. Presentation only.")
    }
    static var cloningReplace: String {
        localization.string(localized: "vocello.mac.cloning.replace", defaultValue: "Replace",
               comment: "macOS interface: chip that opens the file panel to replace the reference clip. Presentation only.")
    }
    static var cloningSavedVoice: String {
        localization.string(localized: "vocello.mac.cloning.savedVoice", defaultValue: "Saved voice",
               comment: "macOS interface: Voice Cloning saved-voice picker label. Presentation only.")
    }
    static func cloningSavedVoicesLoadError(_ error: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.cloning.savedVoicesLoadError",
            defaultValue: "Couldn't load saved voices right now. You can still clone from a file. %@",
            comment: "macOS interface: notice when the saved voices list failed to load; %@ is the error text. Presentation only."), error)
    }
    static var cloningScriptPlaceholder: String {
        localization.string(localized: "vocello.mac.cloning.scriptPlaceholder", defaultValue: "Type the line for the cloned voice",
               comment: "macOS interface: placeholder of the Voice Cloning script editor. Presentation only.")
    }
    static var cloningSiriRequired: String {
        localization.string(localized: "vocello.mac.cloning.siriRequired", defaultValue: "Auto-transcription needs Siri enabled (macOS requirement) — type the transcript or enable Siri in System Settings.",
               comment: "macOS interface: hint under the transcript field when speech recognition needs Siri. Presentation only.")
    }
    static var cloningSpeechRecognitionOff: String {
        localization.string(localized: "vocello.mac.cloning.speechRecognitionOff", defaultValue: "Speech recognition is off for Vocello — type the transcript or enable it in System Settings → Privacy & Security.",
               comment: "macOS interface: hint under the transcript field when speech recognition was denied. Presentation only.")
    }
    static var cloningSupportedFormats: String {
        localization.string(localized: "vocello.mac.cloning.supportedFormats", defaultValue: "WAV, MP3, AIFF, M4A, FLAC, or OGG",
               comment: "macOS interface: list of accepted reference audio formats. Presentation only.")
    }
    /// MAC-09: the list on a Mac whose AudioToolbox cannot read Ogg.
    static var cloningSupportedFormatsWithoutOgg: String {
        localization.string(localized: "vocello.mac.cloning.supportedFormatsWithoutOgg", defaultValue: "WAV, MP3, AIFF, M4A, or FLAC",
               comment: "macOS interface: list of accepted reference audio formats on a Mac that cannot read Ogg files. Presentation only.")
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
    static func cloningTranscriptLoadFailed(_ name: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.cloning.transcriptLoadFailed",
            defaultValue: "Couldn't load the saved transcript for “%@”. You can still clone from the audio file alone.",
            comment: "macOS interface: warning when a saved voice's transcript file cannot be read; %@ is the voice name. Presentation only."), name)
    }
    static var cloningSavedVoiceUnavailable: String {
        localization.string(localized: "vocello.mac.cloning.savedVoiceUnavailable", defaultValue: "That saved voice’s reference audio is no longer available. Choose another reference.",
               comment: "macOS interface: shown when a staged saved-voice reference file no longer exists by the time Voice Cloning opens. Presentation only.")
    }
    static var cloningTranscriptPlaceholder: String {
        localization.string(localized: "vocello.mac.cloning.transcriptPlaceholder", defaultValue: "What does the reference audio say? (optional)",
               comment: "macOS interface: placeholder of the reference transcript field. Presentation only.")
    }
    static func cloningUnsupportedFile(_ ext: String, _ formats: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.cloning.unsupportedFile",
            defaultValue: "Unsupported file type “.%1$@”. Drop an audio file (%2$@).",
            comment: "macOS interface: error when a dropped file is not audio; %1$@ is the extension, %2$@ the supported formats. Presentation only."), ext, formats)
    }
    static func cloningVoiceBankEntry(_ name: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.cloning.voiceBankEntry",
            defaultValue: "%@ · voice bank",
            comment: "macOS interface: source picker entry for a voice bank persona; %@ is the persona name. Presentation only."), name)
    }
    static var close: String {
        localization.string(localized: "vocello.mac.common.close", defaultValue: "Close",
               comment: "macOS interface: dismiss a popover or sheet. Presentation only.")
    }
    static var customAddScriptDetail: String {
        localization.string(localized: "vocello.mac.custom.addScriptDetail", defaultValue: "Speaker and delivery are set. Add a line to generate.",
               comment: "macOS interface: Built-in Voice readiness detail when the script is empty. Presentation only.")
    }
    static var customAllSpeakers: String {
        localization.string(localized: "vocello.mac.custom.allSpeakers", defaultValue: "All speakers",
               comment: "macOS interface: Built-in Voice speaker picker section. Presentation only.")
    }
    static var customDeliveryUnsupported: String {
        localization.string(localized: "vocello.mac.custom.deliveryUnsupported", defaultValue: "Delivery controls are available with the active 1.7B Built-in Voice models.",
               comment: "macOS interface: notice when the selected Built-in Voice model has no delivery controls. Presentation only.")
    }
    static var customEngineBusy: String {
        localization.string(localized: "vocello.mac.custom.engineBusy", defaultValue: "Engine busy",
               comment: "macOS interface: Built-in Voice readiness title while the engine serves another mode. Presentation only.")
    }
    static var customEngineBusyDetail: String {
        localization.string(localized: "vocello.mac.custom.engineBusyDetail", defaultValue: "Finishing another engine task before Built-in Voice can be ready.",
               comment: "macOS interface: Built-in Voice readiness detail while the engine serves another mode. Presentation only.")
    }
    static var customEngineNeedsAttention: String {
        localization.string(localized: "vocello.mac.custom.engineNeedsAttention", defaultValue: "Engine needs attention",
               comment: "macOS interface: Built-in Voice readiness title when the engine reported a failure. Presentation only.")
    }
    static var customGeneratingFinalAudio: String {
        localization.string(localized: "vocello.mac.custom.generatingFinalAudio", defaultValue: "Generating final audio",
               comment: "macOS interface: Built-in Voice readiness title while a take renders. Presentation only.")
    }
    static var customGeneratingFinalAudioDetail: String {
        localization.string(localized: "vocello.mac.custom.generatingFinalAudioDetail", defaultValue: "Rendering the complete take. The file lands in the player when ready.",
               comment: "macOS interface: Built-in Voice readiness detail while a take renders. Presentation only.")
    }
    static var customModelMismatchDetail: String {
        localization.string(localized: "vocello.mac.custom.modelMismatchDetail", defaultValue: "A different model is loaded. The engine switches to Built-in Voice on generate.",
               comment: "macOS interface: Built-in Voice readiness detail when another model is loaded. Presentation only.")
    }
    static var customPreparing: String {
        localization.string(localized: "vocello.mac.custom.preparing", defaultValue: "Preparing Built-in Voice",
               comment: "macOS interface: Built-in Voice readiness title while its model warms up. Presentation only.")
    }
    static var customPreparingDetail: String {
        localization.string(localized: "vocello.mac.custom.preparingDetail", defaultValue: "Loading the Built-in Voice path. You can generate now; preparation finishes in the background.",
               comment: "macOS interface: Built-in Voice readiness detail while its model warms up. Presentation only.")
    }
    static var customReadyDetail: String {
        localization.string(localized: "vocello.mac.custom.readyDetail", defaultValue: "Takes save to History automatically.",
               comment: "macOS interface: Built-in Voice readiness detail when ready. Presentation only.")
    }
    static var customSpeaker: String {
        localization.string(localized: "vocello.mac.custom.speaker", defaultValue: "Speaker",
               comment: "macOS interface: Built-in Voice speaker picker label. Presentation only.")
    }
    static func customSpeakerNativeLanguageHint(_ speaker: String, _ native: String, _ selected: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.custom.speakerNativeLanguageHint",
            defaultValue: "%1$@ is native to %2$@. %3$@ can still work, but pronunciation is usually best in the speaker's native language.",
            comment: "macOS interface: hint under the language picker; %1$@ speaker name, %2$@ native language, %3$@ selected language. Presentation only."), speaker, native, selected)
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
    static var designAddVoiceBrief: String {
        localization.string(localized: "vocello.mac.design.addVoiceBrief", defaultValue: "Add a voice brief",
               comment: "macOS interface: Voice Design readiness title without a brief. Presentation only.")
    }
    static var designBriefUsedDetail: String {
        localization.string(localized: "vocello.mac.design.briefUsedDetail", defaultValue: "The generated voice uses this brief and delivery once a line is written.",
               comment: "macOS interface: Voice Design readiness detail when the script is empty. Presentation only.")
    }
    static var designDescribeVoiceDetail: String {
        localization.string(localized: "vocello.mac.design.describeVoiceDetail", defaultValue: "Describe the voice before writing the final line.",
               comment: "macOS interface: Voice Design readiness detail without a brief. Presentation only.")
    }
    static var designPreparingDetail: String {
        localization.string(localized: "vocello.mac.design.preparingDetail", defaultValue: "Preparing Voice Design. You can generate now; preparation finishes in the background.",
               comment: "macOS interface: Voice Design readiness detail while its model warms up. Presentation only.")
    }
    static var designReviewTake: String {
        localization.string(localized: "vocello.mac.design.reviewTake", defaultValue: "Review the take",
               comment: "macOS interface: Voice Design readiness title when ready. Presentation only.")
    }
    static var designSavedToSavedVoices: String {
        localization.string(localized: "vocello.mac.design.savedToSavedVoices", defaultValue: "Saved to Saved Voices",
               comment: "macOS interface: Voice Design confirmation after saving the designed voice. Presentation only.")
    }
    static var designVoiceBriefLabel: String {
        localization.string(localized: "vocello.mac.design.voiceBriefLabel", defaultValue: "Voice brief",
               comment: "macOS interface: label of the voice brief row. Presentation only.")
    }
    static var done: String {
        localization.string(localized: "vocello.mac.common.done", defaultValue: "Done",
               comment: "macOS interface: closes a finished sheet. Presentation only.")
    }
    static var download: String {
        localization.string(localized: "vocello.mac.common.download", defaultValue: "Download",
               comment: "macOS interface: download action and model status. Presentation only.")
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
    static var engineColdStart: String {
        localization.string(localized: "vocello.mac.engine.coldStart", defaultValue: "Model is unloaded. First generate reloads it.",
               comment: "macOS interface: readiness detail when the model is unloaded. Presentation only.")
    }
    static var engineColdStartLowMemory: String {
        localization.string(localized: "vocello.mac.engine.coldStartLowMemory", defaultValue: "Model unloaded to save memory. First generate reloads it — normal on 8 GB Macs.",
               comment: "macOS interface: readiness detail on 8 GB Macs when the model is unloaded. Presentation only.")
    }
    static func historyAudioRemovalMany(_ count: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.history.audioRemovalMany",
            defaultValue: "%@ audio files from deleted takes are still in the output folder. Retry to delete them, or reveal them in Finder.",
            comment: "macOS interface: recovery banner detail; %@ is how many audio files of deleted takes could not be deleted yet (2 or more). Presentation only."), count)
    }
    static var historyAudioRemovalOne: String {
        localization.string(localized: "vocello.mac.history.audioRemovalOne", defaultValue: "1 audio file from deleted takes is still in the output folder. Retry to delete it, or reveal it in Finder.",
               comment: "macOS interface: recovery banner detail when one audio file of a deleted take could not be deleted yet. Presentation only.")
    }
    static var historyAudioRemovalTitle: String {
        localization.string(localized: "vocello.mac.history.audioRemovalTitle", defaultValue: "Audio from deleted takes remains",
               comment: "macOS interface: History recovery banner title when only audio of deleted takes waits to be deleted. Presentation only.")
    }
    static var historyAudioUnavailable: String {
        localization.string(localized: "vocello.mac.history.audioUnavailable", defaultValue: "Audio unavailable",
               comment: "macOS interface: History row play tile label when the WAV is missing. Presentation only.")
    }
    static var historyBucketEarlier: String {
        localization.string(localized: "vocello.mac.history.bucketEarlier", defaultValue: "Earlier",
               comment: "macOS interface: History date section for older takes. Presentation only.")
    }
    static var historyBucketPrevious30: String {
        localization.string(localized: "vocello.mac.history.bucketPrevious30", defaultValue: "Previous 30 days",
               comment: "macOS interface: History date section for takes from the previous month. Presentation only.")
    }
    static var historyBucketPrevious7: String {
        localization.string(localized: "vocello.mac.history.bucketPrevious7", defaultValue: "Previous 7 days",
               comment: "macOS interface: History date section for takes from the previous week. Presentation only.")
    }
    static var historyBucketToday: String {
        localization.string(localized: "vocello.mac.history.bucketToday", defaultValue: "Today",
               comment: "macOS interface: History date section for takes from today. Presentation only.")
    }
    static var historyBucketYesterday: String {
        localization.string(localized: "vocello.mac.history.bucketYesterday", defaultValue: "Yesterday",
               comment: "macOS interface: History date section for takes from yesterday. Presentation only.")
    }
    static var historyClearAccessibility: String {
        localization.string(localized: "vocello.mac.history.clearAccessibility", defaultValue: "Clear history",
               comment: "macOS interface: VoiceOver label of the History toolbar clear menu. Presentation only.")
    }
    static var historyClearConfirm: String {
        localization.string(localized: "vocello.mac.history.clearConfirm", defaultValue: "Clear History",
               comment: "macOS interface: confirmation button that clears History. Presentation only.")
    }
    static var historyClearDeleteFiles: String {
        localization.string(localized: "vocello.mac.history.clearDeleteFiles", defaultValue: "Clear History and Delete Audio…",
               comment: "macOS interface: History toolbar menu action that clears entries and deletes audio files. Presentation only.")
    }
    static func historyClearDeleteMessage(_ count: Int) -> String {
        localization.format(localization.string(localized: "vocello.mac.history.clearDeleteMessage",
            defaultValue: "This permanently deletes all %1$lld history entries and their audio files.",
            comment: "macOS interface: confirmation message for clearing History and deleting audio; %1$lld is the entry count (plural). Presentation only."), count)
    }
    static var historyClearDeleteTitle: String {
        localization.string(localized: "vocello.mac.history.clearDeleteTitle", defaultValue: "Clear History and Delete Audio?",
               comment: "macOS interface: confirmation title for clearing History and deleting audio files. Presentation only.")
    }
    static var historyClearError: String {
        localization.string(localized: "vocello.mac.history.clearError", defaultValue: "Clear History Error",
               comment: "macOS interface: alert title when clearing History fails. Presentation only.")
    }
    static var historyClearKeepFiles: String {
        localization.string(localized: "vocello.mac.history.clearKeepFiles", defaultValue: "Clear History (Keep Audio Files)…",
               comment: "macOS interface: History toolbar menu action that clears entries and keeps audio files. Presentation only.")
    }
    static func historyClearMessage(_ count: Int) -> String {
        localization.format(localization.string(localized: "vocello.mac.history.clearMessage",
            defaultValue: "This removes all %1$lld history entries. The generated audio files stay on disk in your outputs folder.",
            comment: "macOS interface: confirmation message for clearing History; %1$lld is the entry count (plural). Presentation only."), count)
    }
    static var historyClearTitle: String {
        localization.string(localized: "vocello.mac.history.clearTitle", defaultValue: "Clear History?",
               comment: "macOS interface: confirmation title for clearing History while keeping audio files. Presentation only.")
    }
    static var historyClearWarning: String {
        localization.string(localized: "vocello.mac.history.clearWarning", defaultValue: "Clear History Warning",
               comment: "macOS interface: alert title when some audio files survived a clear. Presentation only.")
    }
    static func historyClearWarningMany(_ count: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.history.clearWarningMany",
            defaultValue: "History cleared, but %@ audio files could not be deleted.",
            comment: "macOS interface: alert message when several audio files survived a clear; %@ is the count. Presentation only."), count)
    }
    static var historyClearWarningOne: String {
        localization.string(localized: "vocello.mac.history.clearWarningOne", defaultValue: "History cleared, but 1 audio file could not be deleted.",
               comment: "macOS interface: alert message when one audio file survived a clear. Presentation only.")
    }
    static var historyDeleteDetail: String {
        localization.string(localized: "vocello.mac.history.deleteDetail", defaultValue: "This will permanently delete the generation and its audio file.",
               comment: "macOS interface: History delete confirmation body. Presentation only.")
    }
    static var historyDeleteError: String {
        localization.string(localized: "vocello.mac.history.deleteError", defaultValue: "Delete Error",
               comment: "macOS interface: alert title when a take cannot be removed from History. Presentation only.")
    }
    static func historyDeleteErrorMessage(_ message: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.history.deleteErrorMessage",
            defaultValue: "The generation could not be removed from History: %@ Try again after closing anything using the file.",
            comment: "macOS interface: alert message when a take cannot be removed; %@ is the error text. Presentation only."), message)
    }
    static var historyDeleteEverything: String {
        localization.string(localized: "vocello.mac.history.deleteEverything", defaultValue: "Delete Everything",
               comment: "macOS interface: confirmation button that clears History and deletes audio files. Presentation only.")
    }
    static var historyDeleteTake: String {
        localization.string(localized: "vocello.mac.history.deleteTake", defaultValue: "Delete take",
               comment: "macOS interface: History row delete action label. Presentation only.")
    }
    static var historyDeleteTitle: String {
        localization.string(localized: "vocello.mac.history.deleteTitle", defaultValue: "Delete Generation?",
               comment: "macOS interface: History delete confirmation title. Presentation only.")
    }
    static var historyDeleteWarning: String {
        localization.string(localized: "vocello.mac.history.deleteWarning", defaultValue: "Delete Warning",
               comment: "macOS interface: alert title when the audio file of a removed take remains. Presentation only.")
    }
    static func historyDeleteWarningMessage(_ message: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.history.deleteWarningMessage",
            defaultValue: "Generation removed from history, but the audio file could not be deleted: %@",
            comment: "macOS interface: alert message when the audio file remains; %@ is the error text. Presentation only."), message)
    }
    static var historyEmptyMessage: String {
        localization.string(localized: "vocello.mac.history.emptyMessage", defaultValue: "There are no history entries to clear.",
               comment: "macOS interface: alert message when clearing an empty History. Presentation only.")
    }
    static var historyEmptyTitle: String {
        localization.string(localized: "vocello.mac.history.emptyTitle", defaultValue: "History Is Empty",
               comment: "macOS interface: alert title when clearing an empty History. Presentation only.")
    }
    static var historyExportError: String {
        localization.string(localized: "vocello.mac.history.exportError", defaultValue: "Export Error",
               comment: "macOS interface: alert title when exporting a take fails. Presentation only.")
    }
    static func historyExportErrorMessage(_ error: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.history.exportErrorMessage",
            defaultValue: "The file could not be exported: %@ Choose another destination and try again.",
            comment: "macOS interface: alert message when exporting a take fails; %@ is the error text. Presentation only."), error)
    }
    static var historyExportPrompt: String {
        localization.string(localized: "vocello.mac.history.exportPrompt", defaultValue: "Export",
               comment: "macOS interface: confirm button of the folder panel that exports pending recovery audio. Presentation only.")
    }
    static var historyExportWarning: String {
        localization.string(localized: "vocello.mac.history.exportWarning", defaultValue: "Export Warning",
               comment: "macOS interface: alert title when some recovery exports failed. Presentation only.")
    }
    static var historyFilterAccessibility: String {
        localization.string(localized: "vocello.mac.history.filterAccessibility", defaultValue: "Filter by mode",
               comment: "macOS interface: VoiceOver label of the History mode filter row. Presentation only.")
    }
    static var historyFilterAll: String {
        localization.string(localized: "vocello.mac.history.filterAll", defaultValue: "All",
               comment: "macOS interface: History mode filter chip that shows every mode. Presentation only.")
    }
    static var historyFinishedAudioWaiting: String {
        localization.string(localized: "vocello.mac.history.finishedAudioWaiting", defaultValue: "Finished audio is waiting for History",
               comment: "macOS interface: History recovery banner title for unqueued generations. Presentation only.")
    }
    static var historyLoadFailedDetail: String {
        localization.string(localized: "vocello.mac.history.loadFailedDetail", defaultValue: "Retry reopens the history database and reads it again.",
               comment: "macOS interface: History error-state detail above the Retry button. Presentation only.")
    }
    static var historyLoadFailedTitle: String {
        localization.string(localized: "vocello.mac.history.loadFailedTitle", defaultValue: "Couldn't load history",
               comment: "macOS interface: History error-state title when the database could not be read. Presentation only.")
    }
    static var historyLoading: String {
        localization.string(localized: "vocello.mac.history.loading", defaultValue: "Loading history…",
               comment: "macOS interface: History loading-state label. Presentation only.")
    }
    static var historyNoMatchesDetail: String {
        localization.string(localized: "vocello.mac.history.noMatchesDetail", defaultValue: "Try a different search term or another mode filter.",
               comment: "macOS interface: History empty-state detail when the search or mode filter matches nothing. Presentation only.")
    }
    static var historyNoMatchesTitle: String {
        localization.string(localized: "vocello.mac.history.noMatchesTitle", defaultValue: "No matches",
               comment: "macOS interface: History empty-state title when the search or mode filter matches nothing. Presentation only.")
    }
    static var historyNoTakesDetail: String {
        localization.string(localized: "vocello.mac.history.noTakesDetail", defaultValue: "Generate some audio to see it here.",
               comment: "macOS interface: History empty-state detail when nothing was generated. Presentation only.")
    }
    static var historyNoTakesTitle: String {
        localization.string(localized: "vocello.mac.history.noTakesTitle", defaultValue: "No takes yet",
               comment: "macOS interface: History empty-state title when nothing was generated. Presentation only.")
    }
    static func historyPinSeed(_ seed: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.history.pinSeed",
            defaultValue: "Pin seed %1$@ for new takes",
            comment: "macOS interface: History row action. %1$@ is the numeric sampling seed, never translated."), seed)
    }
    static var historyPlayTake: String {
        localization.string(localized: "vocello.mac.history.playTake", defaultValue: "Play take",
               comment: "macOS interface: History row play tile label. Presentation only.")
    }
    static func historyRecoveryQueuedMany(_ count: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.history.recoveryQueuedMany",
            defaultValue: "%@ takes remain safely queued. You can retry, reveal, or export the audio.",
            comment: "macOS interface: recovery banner detail; %@ is the queued take count (2 or more). Presentation only."), count)
    }
    static var historyRecoveryQueuedOne: String {
        localization.string(localized: "vocello.mac.history.recoveryQueuedOne", defaultValue: "1 take remains safely queued. You can retry, reveal, or export the audio.",
               comment: "macOS interface: recovery banner detail for one queued take. Presentation only.")
    }
    static var historyRecoveryUnverified: String {
        localization.string(localized: "vocello.mac.history.recoveryUnverified", defaultValue: "Vocello preserved the recovery record but could not verify or commit it. Retry before clearing History.",
               comment: "macOS interface: recovery banner detail when a queued take could not be verified. Presentation only.")
    }
    static var historyRefreshFailed: String {
        localization.string(localized: "vocello.mac.history.refreshFailed", defaultValue: "Couldn't refresh history",
               comment: "macOS interface: alert title when History fails to reload. Presentation only.")
    }
    static var historyReloadBeforeDelete: String {
        localization.string(localized: "vocello.mac.history.reloadBeforeDelete", defaultValue: "Reload History before deleting entries",
               comment: "macOS interface: tooltip on a disabled History delete action while the database is unavailable. Presentation only.")
    }
    static var historyRevealAudio: String {
        localization.string(localized: "vocello.mac.history.revealAudio", defaultValue: "Reveal Audio",
               comment: "macOS interface: History recovery banner action that reveals the retained audio in Finder. Presentation only.")
    }
    static var historyRevealInFinder: String {
        localization.string(localized: "vocello.mac.history.revealInFinder", defaultValue: "Reveal in Finder",
               comment: "macOS interface: History row action. Presentation only.")
    }
    static var historySaveAs: String {
        localization.string(localized: "vocello.mac.history.saveAs", defaultValue: "Save As…",
               comment: "macOS interface: History row action that copies the take's WAV where the user chooses. Presentation only.")
    }
    static var historySaveToSavedVoices: String {
        localization.string(localized: "vocello.mac.history.saveToSavedVoices", defaultValue: "Save to Saved Voices",
               comment: "macOS interface: VoiceOver label of the History action that saves a generation as a voice. Presentation only.")
    }
    static var historySegmentsCollapsed: String {
        localization.string(localized: "vocello.mac.history.segmentsCollapsed", defaultValue: "Collapsed",
               comment: "macOS interface: VoiceOver value of a closed long-form segment map. Presentation only.")
    }
    static var historySegmentsExpanded: String {
        localization.string(localized: "vocello.mac.history.segmentsExpanded", defaultValue: "Expanded",
               comment: "macOS interface: VoiceOver value of an open long-form segment map. Presentation only.")
    }
    static func historySegmentsMany(_ count: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.history.segmentsMany",
            defaultValue: "%@ segments",
            comment: "macOS interface: long-form project disclosure label; %@ is the segment count. Presentation only."), count)
    }
    static var historySegmentsOne: String {
        localization.string(localized: "vocello.mac.history.segmentsOne", defaultValue: "1 segment",
               comment: "macOS interface: long-form project disclosure label for a single segment. Presentation only.")
    }
    static var historyShowMore: String {
        localization.string(localized: "vocello.mac.history.showMore", defaultValue: "Show More",
               comment: "macOS interface: button below the History list that loads the next page of takes. Presentation only.")
    }
    static var historySortAccessibility: String {
        localization.string(localized: "vocello.mac.history.sortAccessibility", defaultValue: "Sort history",
               comment: "macOS interface: VoiceOver label of the History toolbar sort menu. Presentation only.")
    }
    static var historySortLongest: String {
        localization.string(localized: "vocello.mac.history.sortLongest", defaultValue: "Longest",
               comment: "macOS interface: History sort option by duration. Presentation only.")
    }
    static var historySortMode: String {
        localization.string(localized: "vocello.mac.history.sortMode", defaultValue: "Mode",
               comment: "macOS interface: History sort option by generation mode. Presentation only.")
    }
    static var historySortNewest: String {
        localization.string(localized: "vocello.mac.history.sortNewest", defaultValue: "Newest",
               comment: "macOS interface: History sort option. Presentation only.")
    }
    static var historySortOldest: String {
        localization.string(localized: "vocello.mac.history.sortOldest", defaultValue: "Oldest",
               comment: "macOS interface: History sort option. Presentation only.")
    }
    static var historySortPicker: String {
        localization.string(localized: "vocello.mac.history.sortPicker", defaultValue: "Sort",
               comment: "macOS interface: title of the History toolbar sort picker. Presentation only.")
    }
    static var historySortShortest: String {
        localization.string(localized: "vocello.mac.history.sortShortest", defaultValue: "Shortest",
               comment: "macOS interface: History sort option by duration. Presentation only.")
    }
    static var historyUnavailableMessage: String {
        localization.string(localized: "vocello.mac.history.unavailableMessage", defaultValue: "Retry loading History before deleting any entries. Your existing database was preserved.",
               comment: "macOS interface: alert message when the History database cannot be opened. Presentation only.")
    }
    static var historyUnavailableTitle: String {
        localization.string(localized: "vocello.mac.history.unavailableTitle", defaultValue: "History Unavailable",
               comment: "macOS interface: alert title when the History database cannot be opened. Presentation only.")
    }
    static var languageAutoDetail: String {
        localization.string(localized: "vocello.mac.section.languageAutoDetail", defaultValue: "· Auto",
               comment: "macOS interface: suffix after the Language label when the picker follows the detected language. Presentation only.")
    }
    static var menuBuiltInVoice: String {
        localization.string(localized: "vocello.mac.menu.builtInVoice", defaultValue: "Built-in Voice",
               comment: "macOS interface: Navigate menu command that opens the Built-in Voice screen. Presentation only.")
    }
    static var menuHistory: String {
        localization.string(localized: "vocello.mac.menu.history", defaultValue: "History",
               comment: "macOS interface: Navigate menu command that opens History. Presentation only.")
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
    static var menuSearchHistory: String {
        localization.string(localized: "vocello.mac.menu.searchHistory", defaultValue: "Search History",
               comment: "macOS interface: Navigate menu command (Command-F) that opens History and focuses its search field. Presentation only.")
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
    static func modelsBytesProgress(_ done: String, _ total: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.models.bytesProgress",
            defaultValue: "%1$@ of %2$@",
            comment: "macOS interface: download detail; %1$@ downloaded size, %2$@ total size. Presentation only."), done, total)
    }
    static var modelsChecking: String {
        localization.string(localized: "vocello.mac.models.checking", defaultValue: "Checking",
               comment: "macOS interface: model package status while local files are inspected. Presentation only.")
    }
    static var modelsCheckingDetail: String {
        localization.string(localized: "vocello.mac.models.checkingDetail", defaultValue: "Looking for local model files.",
               comment: "macOS interface: model package detail while local files are inspected. Presentation only.")
    }
    static func modelsEtaSeconds(_ seconds: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.models.etaSeconds",
            defaultValue: "about %@s remaining",
            comment: "macOS interface: download detail; %@ is the estimated seconds remaining. Presentation only."), seconds)
    }
    static func modelsFilesMissing(_ count: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.models.filesMissing",
            defaultValue: "%@ required files are missing.",
            comment: "macOS interface: repair detail; %@ is the missing file count. Presentation only."), count)
    }
    static func modelsFilesProgress(_ done: String, _ total: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.models.filesProgress",
            defaultValue: "%1$@ of %2$@ files",
            comment: "macOS interface: download detail; %1$@ completed files, %2$@ total files. Presentation only."), done, total)
    }
    static var modelsFolderIncomplete: String {
        localization.string(localized: "vocello.mac.models.folderIncomplete", defaultValue: "The local model folder is incomplete.",
               comment: "macOS interface: repair detail without a list of missing files. Presentation only.")
    }
    static func modelsInstallToEnable(_ model: String, _ mode: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.models.installToEnable",
            defaultValue: "Install %1$@ to enable %2$@.",
            comment: "macOS interface: recovery detail; %1$@ model display name, %2$@ mode name. Presentation only."), model, mode)
    }
    static var modelsNeedsRepair: String {
        localization.string(localized: "vocello.mac.models.needsRepair", defaultValue: "Needs repair",
               comment: "macOS interface: model package status when files are missing or damaged. Presentation only.")
    }
    static var modelsNotInstalled: String {
        localization.string(localized: "vocello.mac.models.notInstalled", defaultValue: "Not installed",
               comment: "macOS interface: model package status when nothing is on disk. Presentation only.")
    }
    static var modelsOneFileMissing: String {
        localization.string(localized: "vocello.mac.models.oneFileMissing", defaultValue: "One required file is missing.",
               comment: "macOS interface: repair detail for one missing file. Presentation only.")
    }
    static var modelsPhaseCancelling: String {
        localization.string(localized: "vocello.mac.models.phaseCancelling", defaultValue: "Cancelling",
               comment: "macOS interface: download phase label. Presentation only.")
    }
    static var modelsPhaseDownloading: String {
        localization.string(localized: "vocello.mac.models.phaseDownloading", defaultValue: "Downloading",
               comment: "macOS interface: download phase label. Presentation only.")
    }
    static var modelsPhaseInstalling: String {
        localization.string(localized: "vocello.mac.models.phaseInstalling", defaultValue: "Installing",
               comment: "macOS interface: download phase label. Presentation only.")
    }
    static var modelsPhaseQueued: String {
        localization.string(localized: "vocello.mac.models.phaseQueued", defaultValue: "Queued",
               comment: "macOS interface: download phase label. Presentation only.")
    }
    static var modelsPhaseRetrying: String {
        localization.string(localized: "vocello.mac.models.phaseRetrying", defaultValue: "Retrying",
               comment: "macOS interface: download phase label. Presentation only.")
    }
    static var modelsPhaseVerifying: String {
        localization.string(localized: "vocello.mac.models.phaseVerifying", defaultValue: "Verifying",
               comment: "macOS interface: download phase label. Presentation only.")
    }
    static var modelsPhaseWaitingForNetwork: String {
        localization.string(localized: "vocello.mac.models.phaseWaitingForNetwork", defaultValue: "Waiting for network",
               comment: "macOS interface: download phase label. Presentation only.")
    }
    static var modelsPurposeClone: String {
        localization.string(localized: "vocello.mac.models.purposeClone", defaultValue: "Use a reference clip",
               comment: "macOS interface: purpose caption of the Voice Cloning model. Presentation only.")
    }
    static var modelsPurposeCustom: String {
        localization.string(localized: "vocello.mac.models.purposeCustom", defaultValue: "Built-in speakers",
               comment: "macOS interface: purpose caption of the Built-in Voice model. Presentation only.")
    }
    static var modelsPurposeDesign: String {
        localization.string(localized: "vocello.mac.models.purposeDesign", defaultValue: "Describe a new voice",
               comment: "macOS interface: purpose caption of the Voice Design model. Presentation only.")
    }
    static func modelsRecommendedInstalled(_ count: String, _ total: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.models.recommendedInstalled",
            defaultValue: "%1$@ of %2$@ recommended models installed",
            comment: "macOS interface: setup summary; %1$@ installed count, %2$@ total. Presentation only."), count, total)
    }
    static var modelsRecommendedReady: String {
        localization.string(localized: "vocello.mac.models.recommendedReady", defaultValue: "Recommended models ready",
               comment: "macOS interface: setup summary when every recommended model is installed. Presentation only.")
    }
    static var modelsRepair: String {
        localization.string(localized: "vocello.mac.models.repair", defaultValue: "Repair",
               comment: "macOS interface: repair action and model status. Presentation only.")
    }
    static func modelsRepairToFinish(_ model: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.models.repairToFinish",
            defaultValue: "Some required files are missing. Repair %@ to finish installing it.",
            comment: "macOS interface: recovery detail; %@ is the model display name. Presentation only."), model)
    }
    static func modelsRepairToKeepUsing(_ model: String, _ mode: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.models.repairToKeepUsing",
            defaultValue: "The local model files are incomplete. Repair %1$@ to keep using %2$@.",
            comment: "macOS interface: recovery detail; %1$@ model display name, %2$@ mode name. Presentation only."), model, mode)
    }
    static func modelsRetryReuse(_ count: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.models.retryReuse",
            defaultValue: "retry %@; verified files will be reused",
            comment: "macOS interface: download detail while retrying; %@ is the retry count. Presentation only."), count)
    }
    static var modelsStalled: String {
        localization.string(localized: "vocello.mac.models.stalled", defaultValue: "No progress for 20 seconds.",
               comment: "macOS interface: download detail when no bytes arrived for 20 seconds. Presentation only.")
    }
    static var modelsUpdate: String {
        localization.string(localized: "vocello.mac.models.update", defaultValue: "Update",
               comment: "macOS interface: update action and model status. Presentation only.")
    }
    static var modelsUpdateAvailable: String {
        localization.string(localized: "vocello.mac.models.updateAvailable", defaultValue: "Update available",
               comment: "macOS interface: model package status when a newer package is pinned. Presentation only.")
    }
    static var modelsUpdateAvailableDetail: String {
        localization.string(localized: "vocello.mac.models.updateAvailableDetail", defaultValue: "A newer model package is pinned. Update to download it.",
               comment: "macOS interface: model package detail when a newer package is pinned. Presentation only.")
    }
    static var ok: String {
        localization.string(localized: "vocello.mac.common.ok", defaultValue: "OK",
               comment: "macOS interface: acknowledge an alert. Presentation only.")
    }
    static var playerClose: String {
        localization.string(localized: "vocello.mac.player.close", defaultValue: "Close player",
               comment: "macOS interface: VoiceOver label of the sidebar player close button. Presentation only.")
    }
    /// The action the control performs, not the state it is in: VoiceOver reads
    /// a button's label as what pressing it will do. Naming the current state
    /// instead ("pause" while playing) tells a blind user the opposite of what
    /// happens. These replace a pair of hardcoded English words that shipped as
    /// `accessibilityValue` on a French-localized app.
    static var playerPause: String {
        localization.string(localized: "vocello.mac.player.pause", defaultValue: "Pause",
               comment: "macOS interface: VoiceOver label of the player's play/pause button while audio is playing. Presentation only.")
    }
    static var playerPlay: String {
        localization.string(localized: "vocello.mac.player.play", defaultValue: "Play",
               comment: "macOS interface: VoiceOver label of the player's play/pause button while audio is paused or stopped. Presentation only.")
    }
    static var playerLive: String {
        localization.string(localized: "vocello.mac.player.live", defaultValue: "Live",
               comment: "macOS interface: sidebar player badge while streaming audio plays. Presentation only.")
    }
    static var playerPosition: String {
        localization.string(localized: "vocello.mac.player.position", defaultValue: "Playback position",
               comment: "macOS interface: VoiceOver label of the sidebar player scrubber. Presentation only.")
    }
    static var readinessAddScript: String {
        localization.string(localized: "vocello.mac.readiness.addScript", defaultValue: "Add a script",
               comment: "macOS interface: readiness title when the script field is empty. Presentation only.")
    }
    static var readinessEngineStarting: String {
        localization.string(localized: "vocello.mac.readiness.engineStarting", defaultValue: "Engine starting",
               comment: "macOS interface: readiness title while the engine starts. Presentation only.")
    }
    static var readinessEngineStartingDetail: String {
        localization.string(localized: "vocello.mac.readiness.engineStartingDetail", defaultValue: "The engine is still preparing.",
               comment: "macOS interface: readiness detail while the engine starts. Presentation only.")
    }
    static var readinessInstallActiveModel: String {
        localization.string(localized: "vocello.mac.readiness.installActiveModel", defaultValue: "Install the active model",
               comment: "macOS interface: readiness title when the selected model is not installed. Presentation only.")
    }
    static func readinessInstallActiveModelDetail(_ model: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.readiness.installActiveModelDetail",
            defaultValue: "Install %@ in Models to enable generation.",
            comment: "macOS interface: readiness detail when the selected model is not installed; %@ is the model name. Presentation only."), model)
    }
    static var readinessReadyToGenerate: String {
        localization.string(localized: "vocello.mac.readiness.readyToGenerate", defaultValue: "Ready to generate",
               comment: "macOS interface: readiness title when generation can start. Presentation only.")
    }
    static var readinessReadyToGenerateAndSave: String {
        localization.string(localized: "vocello.mac.readiness.readyToGenerateAndSave", defaultValue: "Ready to generate and save.",
               comment: "macOS interface: readiness detail when generation can start. Presentation only.")
    }
    static var recommendedForScript: String {
        localization.string(localized: "vocello.mac.common.recommendedForScript", defaultValue: "Recommended for your script",
               comment: "macOS interface: picker section of speakers or languages matching the script. Presentation only.")
    }
    static var recordClipTooShort: String {
        localization.string(localized: "vocello.mac.record.clipTooShort", defaultValue: "Clip is under 10 seconds. Retake a longer one.",
               comment: "macOS interface: record sheet status after a capture that is too short. Presentation only.")
    }
    static var recordFailedToStart: String {
        localization.string(localized: "vocello.mac.record.failedToStart", defaultValue: "Recording couldn't start. Check your microphone in System Settings → Sound, then try again.",
               comment: "macOS interface: record sheet status when the recorder failed to start. Presentation only.")
    }
    static var recordIdleHint: String {
        localization.string(localized: "vocello.mac.record.idleHint", defaultValue: "Click Record, then read 10–20 s of clean, natural speech. Quiet room. One voice.",
               comment: "macOS interface: record sheet instructions before recording. Presentation only.")
    }
    static var recordKeepGoing: String {
        localization.string(localized: "vocello.mac.record.keepGoing", defaultValue: "Keep recording. 10 second minimum.",
               comment: "macOS interface: record sheet status under the minimum duration. Presentation only.")
    }
    static var recordMicrophoneDenied: String {
        localization.string(localized: "vocello.mac.record.microphoneDenied", defaultValue: "Microphone access is denied. Enable it in System Settings to record.",
               comment: "macOS interface: record sheet status when microphone permission is denied. Presentation only.")
    }
    static var recordMicrophoneDeniedDetail: String {
        localization.string(localized: "vocello.mac.record.microphoneDeniedDetail", defaultValue: "Vocello needs the microphone to record reference clips. Enable it in System Settings to continue.",
               comment: "macOS interface: recorder alert body when the microphone permission is denied. Presentation only.")
    }
    static var recordMicrophoneDeniedTitle: String {
        localization.string(localized: "vocello.mac.record.microphoneDeniedTitle", defaultValue: "Microphone access denied",
               comment: "macOS interface: recorder alert title when the microphone permission is denied. Presentation only.")
    }
    static var recordNeedTenSeconds: String {
        localization.string(localized: "vocello.mac.record.needTenSeconds", defaultValue: "Need 10 s",
               comment: "macOS interface: record sheet disabled confirm label while the clip is shorter than ten seconds. Presentation only.")
    }
    static var recordNoMicrophone: String {
        localization.string(localized: "vocello.mac.record.noMicrophone", defaultValue: "No microphone detected. Connect a microphone or audio-input device to record.",
               comment: "macOS interface: record sheet status without an input device. Presentation only.")
    }
    static var recordOpenSystemSettings: String {
        localization.string(localized: "vocello.mac.record.openSystemSettings", defaultValue: "Open System Settings",
               comment: "macOS interface: recorder alert action that opens the privacy pane. Presentation only.")
    }
    static var recordOverLimit: String {
        localization.string(localized: "vocello.mac.record.overLimit", defaultValue: "Over 20 seconds. Stop now.",
               comment: "macOS interface: record sheet status over the recommended duration. Presentation only.")
    }
    static var recordPauseReview: String {
        localization.string(localized: "vocello.mac.record.pauseReview", defaultValue: "Pause review",
               comment: "macOS interface: VoiceOver label of the record sheet review pause button. Presentation only.")
    }
    static var recordPhaseCaptured: String {
        localization.string(localized: "vocello.mac.record.phaseCaptured", defaultValue: "Captured",
               comment: "macOS interface: record sheet phase caption after a clip is captured. Presentation only.")
    }
    static var recordPhaseIdle: String {
        localization.string(localized: "vocello.mac.record.phaseIdle", defaultValue: "Reference clip",
               comment: "macOS interface: record sheet phase caption before recording. Presentation only.")
    }
    static var recordPhaseRecording: String {
        localization.string(localized: "vocello.mac.record.phaseRecording", defaultValue: "Recording",
               comment: "macOS interface: record sheet phase caption while recording. Presentation only.")
    }
    static var recordPlayReview: String {
        localization.string(localized: "vocello.mac.record.playReview", defaultValue: "Play review",
               comment: "macOS interface: VoiceOver label of the record sheet review play button. Presentation only.")
    }
    static var recordRecord: String {
        localization.string(localized: "vocello.mac.record.record", defaultValue: "Record",
               comment: "macOS interface: recorder start button. Presentation only.")
    }
    static var recordRetake: String {
        localization.string(localized: "vocello.mac.record.retake", defaultValue: "Retake",
               comment: "macOS interface: recorder button that discards the take and records again. Presentation only.")
    }
    static var recordReviewClip: String {
        localization.string(localized: "vocello.mac.record.reviewClip", defaultValue: "Review the clip, then use it or retake.",
               comment: "macOS interface: record sheet status after a usable capture. Presentation only.")
    }
    static var recordSoundsGood: String {
        localization.string(localized: "vocello.mac.record.soundsGood", defaultValue: "Sounds good. Click Stop when ready.",
               comment: "macOS interface: record sheet status within the recommended duration. Presentation only.")
    }
    static var recordStop: String {
        localization.string(localized: "vocello.mac.record.stop", defaultValue: "Stop",
               comment: "macOS interface: recorder stop button. Presentation only.")
    }
    static var recordTitle: String {
        localization.string(localized: "vocello.mac.record.title", defaultValue: "Record Reference Clip",
               comment: "macOS interface: recorder sheet title. Presentation only.")
    }
    static var recordUseClip: String {
        localization.string(localized: "vocello.mac.record.useClip", defaultValue: "Use This Clip",
               comment: "macOS interface: record sheet confirm action once the clip is long enough. Presentation only.")
    }
    static var retry: String {
        localization.string(localized: "vocello.mac.common.retry", defaultValue: "Retry",
               comment: "macOS interface: retry a failed operation. Presentation only.")
    }
    static var revealInFinder: String {
        localization.string(localized: "vocello.mac.common.revealInFinder", defaultValue: "Reveal in Finder",
               comment: "macOS interface: reveal a file or folder in Finder (File menu, Settings, model menu). Presentation only.")
    }
    static var savedVoiceAddConfirm: String {
        localization.string(localized: "vocello.mac.savedVoice.addConfirm", defaultValue: "Add Saved Voice",
               comment: "macOS interface: confirm button of the manual Add Voice Sample sheet. Presentation only.")
    }
    static var savedVoiceAddSubtitle: String {
        localization.string(localized: "vocello.mac.savedVoice.addSubtitle", defaultValue: "Save a reference clip you own or have permission to use, then use it in Voice Cloning.",
               comment: "macOS interface: subtitle of the manual Add Voice Sample sheet. Presentation only.")
    }
    static var savedVoiceAddTitle: String {
        localization.string(localized: "vocello.mac.savedVoice.addTitle", defaultValue: "Add Voice Sample",
               comment: "macOS interface: title of the manual Add Voice Sample sheet. Presentation only.")
    }
    static func savedVoiceAddedMessage(_ name: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.savedVoice.addedMessage",
            defaultValue: "\"%@\" is ready in Saved Voices.",
            comment: "macOS interface: alert message after a voice is saved; %@ is the voice name. Presentation only."), name)
    }
    static var savedVoiceAddedTitle: String {
        localization.string(localized: "vocello.mac.savedVoice.addedTitle", defaultValue: "Saved Voice Added",
               comment: "macOS interface: alert title after a voice is saved to Saved Voices. Presentation only.")
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
    static var savedVoiceCloneSubtitle: String {
        localization.string(localized: "vocello.mac.savedVoice.cloneSubtitle", defaultValue: "Keep this clone as a reusable reference for Voice Cloning when you have permission to use it.",
               comment: "macOS interface: subtitle when saving a clone result to Saved Voices. Presentation only.")
    }
    static var savedVoiceDesignSubtitle: String {
        localization.string(localized: "vocello.mac.savedVoice.designSubtitle", defaultValue: "Keep this designed voice as a reusable reference for Voice Cloning when you have permission to use it.",
               comment: "macOS interface: subtitle when saving a designed voice to Saved Voices. Presentation only.")
    }
    static var savedVoiceDesignTitle: String {
        localization.string(localized: "vocello.mac.savedVoice.designTitle", defaultValue: "Save Designed Voice",
               comment: "macOS interface: title when saving a designed voice to Saved Voices. Presentation only.")
    }
    static var savedVoiceDiscardAndReRecord: String {
        localization.string(localized: "vocello.mac.savedVoice.discardAndReRecord", defaultValue: "Discard and re-record",
               comment: "macOS interface: Saved Voice sheet choice after a recording warning. Presentation only.")
    }
    static var savedVoiceKeepVoice: String {
        localization.string(localized: "vocello.mac.savedVoice.keepVoice", defaultValue: "Keep voice",
               comment: "macOS interface: Saved Voice sheet choice after a recording warning. Presentation only.")
    }
    static func savedVoiceNameExists(_ name: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.savedVoice.nameExists",
            defaultValue: "A saved voice named \"%@\" already exists. Choose a different name.",
            comment: "macOS interface: validation message for a duplicate saved voice name; %@ is the name. Presentation only."), name)
    }
    static var savedVoiceNameNeedsCharacters: String {
        localization.string(localized: "vocello.mac.savedVoice.nameNeedsCharacters", defaultValue: "Enter a name with letters or numbers.",
               comment: "macOS interface: validation message for a saved voice name without letters or digits. Presentation only.")
    }
    static var savedVoiceNamePlaceholder: String {
        localization.string(localized: "vocello.mac.savedVoice.namePlaceholder", defaultValue: "Saved voice name",
               comment: "macOS interface: Saved Voice sheet name field placeholder. Presentation only.")
    }
    static var savedVoiceNameSection: String {
        localization.string(localized: "vocello.mac.savedVoice.nameSection", defaultValue: "Name",
               comment: "macOS interface: Saved Voice sheet section header. Presentation only.")
    }
    static var savedVoiceOpenSiriSettings: String {
        localization.string(localized: "vocello.mac.savedVoice.openSiriSettings", defaultValue: "Open Siri Settings",
               comment: "macOS interface: enrollment sheet button that opens the Siri settings pane when dictation is disabled. Presentation only.")
    }
    static var savedVoiceRecord: String {
        localization.string(localized: "vocello.mac.savedVoice.record", defaultValue: "Record...",
               comment: "macOS interface: Saved Voice sheet button that opens the recorder. Presentation only.")
    }
    static var savedVoiceReplaceConfirm: String {
        localization.string(localized: "vocello.mac.savedVoice.replaceConfirm", defaultValue: "Replace Reference",
               comment: "macOS interface: confirm button of the replace-reference sheet. Presentation only.")
    }
    static var savedVoiceReplaceSubtitle: String {
        localization.string(localized: "vocello.mac.savedVoice.replaceSubtitle", defaultValue: "Pick a longer, cleaner clip (10–20 seconds works best). The existing reference will be replaced after the new one saves successfully.",
               comment: "macOS interface: subtitle of the replace-reference sheet. Presentation only.")
    }
    static var savedVoiceReplaceTitle: String {
        localization.string(localized: "vocello.mac.savedVoice.replaceTitle", defaultValue: "Replace Voice Reference",
               comment: "macOS interface: title of the replace-reference sheet. Presentation only.")
    }
    static var savedVoiceSaveFailedTitle: String {
        localization.string(localized: "vocello.mac.savedVoice.saveFailedTitle", defaultValue: "Couldn't save voice",
               comment: "macOS interface: enrollment review alert title when committing the candidate failed. Presentation only.")
    }
    static var savedVoiceSiriDisabled: String {
        localization.string(localized: "vocello.mac.savedVoice.siriDisabled", defaultValue: "Auto-transcription needs Siri enabled (macOS requirement) — the transcript won't auto-fill.",
               comment: "macOS interface: notice when Siri is disabled and dictation cannot run. Presentation only.")
    }
    static var savedVoiceSpeechDenied: String {
        localization.string(localized: "vocello.mac.savedVoice.speechDenied", defaultValue: "Speech recognition is off for Vocello — the transcript won't auto-fill.",
               comment: "macOS interface: notice when speech recognition permission is denied. Presentation only.")
    }
    static var savedVoiceTranscriptHelp: String {
        localization.string(localized: "vocello.mac.savedVoice.transcriptHelp", defaultValue: "Transcript-backed voices can reuse prepared Qwen3 clone prompts; audio-only voices remain available as a lower-guidance fallback.",
               comment: "macOS interface: Saved Voice sheet explanation under the transcript field. Presentation only.")
    }
    static var savedVoiceTranscriptSection: String {
        localization.string(localized: "vocello.mac.savedVoice.transcriptSection", defaultValue: "Transcript (recommended for reusable clones)",
               comment: "macOS interface: Saved Voice sheet section header. Presentation only.")
    }
    static var sectionLanguage: String {
        localization.string(localized: "vocello.mac.section.language", defaultValue: "Language",
               comment: "macOS interface: label of the language picker column on the generation screens. Presentation only.")
    }
    static var settingsAppLanguage: String {
        localization.string(localized: "vocello.mac.settings.appLanguage", defaultValue: "App Language",
               comment: "macOS interface: Settings row title of the interface-language picker (the interface, not generated speech). Presentation only.")
    }
    static var settingsAppLanguageDetail: String {
        localization.string(localized: "vocello.mac.settings.appLanguageDetail", defaultValue: "Changes the app interface, not the language of generated speech.",
               comment: "macOS interface: Settings row detail under the interface-language picker. Presentation only.")
    }
    static var settingsApplicationData: String {
        localization.string(localized: "vocello.mac.settings.applicationData", defaultValue: "Application data",
               comment: "macOS interface: Settings labeled row title. Presentation only.")
    }
    static var settingsAutoPlay: String {
        localization.string(localized: "vocello.mac.settings.autoPlay", defaultValue: "Auto-play generated audio",
               comment: "macOS interface: Settings toggle. Presentation only.")
    }
    static var settingsAutoPlayDetail: String {
        localization.string(localized: "vocello.mac.settings.autoPlayDetail", defaultValue: "Automatically play each finished take.",
               comment: "macOS interface: Settings row detail under the auto-play switch. Presentation only.")
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
    static func settingsDeleteModelMessage(_ mode: String, _ variant: String, _ size: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.settings.deleteModelMessage",
            defaultValue: "This will delete %1$@ %2$@%3$@ from disk. You can download it again later.",
            comment: "macOS interface: delete-model confirmation; %1$@ mode name, %2$@ variant label, %3$@ optional size in parentheses. Presentation only."), mode, variant, size)
    }
    static var settingsDeleteModelTitle: String {
        localization.string(localized: "vocello.mac.settings.deleteModelTitle", defaultValue: "Delete Model?",
               comment: "macOS interface: model deletion confirmation title. Presentation only.")
    }
    static var settingsDeleteModelBusyTitle: String {
        localization.string(localized: "vocello.mac.settings.deleteModelBusyTitle", defaultValue: "Generation in Progress",
               comment: "macOS interface: alert title when a model cannot be deleted because a generation is running. Presentation only.")
    }
    static var settingsDeleteModelBusyMessage: String {
        localization.string(localized: "vocello.mac.settings.deleteModelBusyMessage",
               defaultValue: "Wait for the current generation to finish, or cancel it, before deleting a model.",
               comment: "macOS interface: alert message when a model cannot be deleted because a generation is running. Presentation only.")
    }
    static var settingsDownloadRecommended: String {
        localization.string(localized: "vocello.mac.settings.downloadRecommended", defaultValue: "Download recommended",
               comment: "macOS interface: button that installs the recommended packages. Presentation only.")
    }
    static func settingsDownloadSize(_ size: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.settings.downloadSize",
            defaultValue: "Download %@",
            comment: "macOS interface: tooltip of the download button; %@ is the download size. Presentation only."), size)
    }
    static func settingsDownloadingProgress(_ mode: String, _ variant: String, _ count: String, _ total: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.settings.downloadingProgress",
            defaultValue: "Downloading %1$@ %2$@ · %3$@ of %4$@ complete",
            comment: "macOS interface: recommended setup progress; %1$@ mode name, %2$@ variant label, %3$@ done, %4$@ total. Presentation only."), mode, variant, count, total)
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
    static var settingsInterface: String {
        localization.string(localized: "vocello.mac.settings.interface", defaultValue: "Interface",
               comment: "macOS interface: Settings section header over the interface-language picker. Presentation only.")
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
    static var settingsOutputDefault: String {
        localization.string(localized: "vocello.mac.settings.outputDefault", defaultValue: "Default",
               comment: "macOS interface: output folder summary when no custom folder is chosen. Presentation only.")
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
    static func settingsProgressComplete(_ count: String, _ total: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.settings.progressComplete",
            defaultValue: "%1$@ of %2$@ complete",
            comment: "macOS interface: recommended setup progress; %1$@ done, %2$@ total. Presentation only."), count, total)
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
    static var settingsSystemLanguage: String {
        localization.string(localized: "vocello.mac.settings.systemLanguage", defaultValue: "System Default",
               comment: "macOS interface: interface-language picker option that follows the system language. Presentation only.")
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
    static var settingsVariationBalanced: String {
        localization.string(localized: "vocello.mac.settings.variationBalanced", defaultValue: "Balanced",
               comment: "macOS interface: Settings variation picker option between Expressive and Consistent. Presentation only.")
    }
    static var settingsVariationConsistent: String {
        localization.string(localized: "vocello.mac.settings.variationConsistent", defaultValue: "Consistent",
               comment: "macOS interface: Settings variation picker option with the steadiest takes. Presentation only.")
    }
    static var settingsVariationExpressive: String {
        localization.string(localized: "vocello.mac.settings.variationExpressive", defaultValue: "Expressive",
               comment: "macOS interface: Settings variation picker option, the model's official sampling. Presentation only.")
    }
    static var settingsVariationHelp: String {
        localization.string(localized: "vocello.mac.settings.variationHelp", defaultValue: "How much takes vary when regenerating the same text. Expressive is the model's official sampling (liveliest); Balanced and Consistent trade some liveliness for steadier, more repeatable takes.",
               comment: "macOS interface: Settings footer under the Variation picker. Expressive, Balanced and Consistent are the picker's option names. Presentation only.")
    }
    static var settingsVoiceCloning: String {
        localization.string(localized: "vocello.mac.settings.voiceCloning", defaultValue: "Voice cloning",
               comment: "macOS interface: Settings section header. Presentation only.")
    }
    static var shellEngineStopped: String {
        localization.string(localized: "vocello.mac.shell.engineStopped", defaultValue: "Engine stopped",
               comment: "macOS interface: status strip title when the engine stopped with an error. Presentation only.")
    }
    static var shellEngineUnavailable: String {
        localization.string(localized: "vocello.mac.shell.engineUnavailable", defaultValue: "Engine unavailable",
               comment: "macOS interface: status strip title when the engine reported it is unavailable. Presentation only.")
    }
    /// Status strip title for an engine that stopped with `message`: "Engine
    /// unavailable" when the message is the typed missing-or-incomplete-model
    /// copy in the interface language (PA-20), "Engine stopped" otherwise. The
    /// message is compared with that copy, never searched for a keyword.
    static func shellCrashedTitle(message: String) -> String {
        message == presentation.generationFailureMessage(GenerationFailurePresentationReason.modelUnavailable)
            ? shellEngineUnavailable
            : shellEngineStopped
    }
    static var shellInProgress: String {
        localization.string(localized: "vocello.mac.shell.inProgress", defaultValue: "In progress",
               comment: "macOS interface: VoiceOver value of a live activity without a known fraction. Presentation only.")
    }
    static var shellModelMissingHint: String {
        localization.string(localized: "vocello.mac.shell.modelMissingHint", defaultValue: "Install in Settings",
               comment: "macOS interface: caption under a dimmed sidebar mode whose model is not installed yet. Presentation only.")
    }
    static var shellRestartToContinue: String {
        localization.string(localized: "vocello.mac.shell.restartToContinue", defaultValue: "Restart the app to continue",
               comment: "macOS interface: status strip message when the engine stopped without a detail. Presentation only.")
    }
    static var shellSectionStudio: String {
        localization.string(localized: "vocello.mac.shell.sectionStudio", defaultValue: "Studio",
               comment: "macOS interface: sidebar section header above the three generation modes. Presentation only.")
    }
    static var sidebarSearchHistory: String {
        localization.string(localized: "vocello.mac.sidebar.searchHistory", defaultValue: "Search history",
               comment: "macOS interface: toolbar search field placeholder shown on the History screen. Presentation only.")
    }
    static var sidebarSectionLibrary: String {
        localization.string(localized: "vocello.mac.sidebar.sectionLibrary", defaultValue: "Library",
               comment: "macOS interface: sidebar section header above History and Saved Voices. Presentation only.")
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
    static var startupEngineBootstrapFailed: String {
        localization.string(localized: "vocello.mac.startup.engineBootstrapFailed", defaultValue: "Vocello couldn't start its speech engine.",
               comment: "macOS interface: startup diagnostics summary when the in-process engine could not be built. Presentation only.")
    }
    static var startupInvalidContract: String {
        localization.string(localized: "vocello.mac.startup.invalidContract", defaultValue: "Vocello couldn't load its native model contract.",
               comment: "macOS interface: startup diagnostics summary when the bundled contract is unreadable. Presentation only.")
    }
    static var startupManifestPath: String {
        localization.string(localized: "vocello.mac.startup.manifestPath", defaultValue: "Manifest path",
               comment: "macOS interface: startup diagnostics row title. Presentation only.")
    }
    static var startupNotFound: String {
        localization.string(localized: "vocello.mac.startup.notFound", defaultValue: "Not found",
               comment: "macOS interface: startup diagnostics value when a path could not be resolved. Presentation only.")
    }
    static var startupResourcesPath: String {
        localization.string(localized: "vocello.mac.startup.resourcesPath", defaultValue: "Resources path",
               comment: "macOS interface: startup diagnostics row title. Presentation only.")
    }
    static var startupUnderlyingError: String {
        localization.string(localized: "vocello.mac.startup.underlyingError", defaultValue: "Underlying error",
               comment: "macOS interface: startup diagnostics heading above the raw error text. Presentation only.")
    }
    static var statusError: String {
        localization.string(localized: "vocello.mac.status.error", defaultValue: "Error",
               comment: "macOS interface: sidebar engine status. Presentation only.")
    }
    static var statusGenerating: String {
        localization.string(localized: "vocello.mac.status.generating", defaultValue: "Generating",
               comment: "macOS interface: short trailing status of the script card while a take renders. Presentation only.")
    }
    static var statusPreparing: String {
        localization.string(localized: "vocello.mac.status.preparing", defaultValue: "Preparing",
               comment: "macOS interface: short trailing status of the script card while the model warms up. Presentation only.")
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
    static var studioChipSeed: String {
        localization.string(localized: "vocello.mac.studio.chipSeed", defaultValue: "Seed",
               comment: "macOS interface: eyebrow of the pinned-seed Studio chip. Presentation only.")
    }
    static var studioClearScript: String {
        localization.string(localized: "vocello.mac.studio.clearScript", defaultValue: "Clear",
               comment: "macOS interface: composer action that empties the script. Presentation only.")
    }
    static var studioCloningVoice: String {
        localization.string(localized: "vocello.mac.studio.cloningVoice", defaultValue: "Cloning voice…",
               comment: "macOS interface: generating-bar subline in Voice Cloning. Presentation only.")
    }
    static var studioDesigningVoice: String {
        localization.string(localized: "vocello.mac.studio.designingVoice", defaultValue: "Designing voice…",
               comment: "macOS interface: generating-bar subline in Voice Design. Presentation only.")
    }
    static var studioDismissTake: String {
        localization.string(localized: "vocello.mac.studio.dismissTake", defaultValue: "Dismiss this take?",
               comment: "macOS interface: title of the confirmation that closes the Studio player card. Presentation only.")
    }
    static var studioDismissTakeDetail: String {
        localization.string(localized: "vocello.mac.studio.dismissTakeDetail", defaultValue: "The take stays in History; only the player closes.",
               comment: "macOS interface: detail of the confirmation that closes the Studio player card. Presentation only.")
    }
    static var studioGenerateAgain: String {
        localization.string(localized: "vocello.mac.studio.generateAgain", defaultValue: "Generate again",
               comment: "macOS interface: VoiceOver label of the Studio player card action that generates the same script again. Presentation only.")
    }
    static var studioGenerationFailed: String {
        localization.string(localized: "vocello.mac.studio.generationFailed", defaultValue: "Generation failed",
               comment: "macOS interface: title of the Studio dock error bar. Presentation only.")
    }
    static var studioRenderingAudio: String {
        localization.string(localized: "vocello.mac.studio.renderingAudio", defaultValue: "Rendering audio…",
               comment: "macOS interface: generating-bar subline in Built-in Voice. Presentation only.")
    }
    static var studioReviewTake: String {
        localization.string(localized: "vocello.mac.studio.reviewTake", defaultValue: "Listen before you use this take; the pacing measured unusual.",
               comment: "macOS interface: detail of the cadence notice on a completed take. Presentation only.")
    }
    static var studioStopGenerating: String {
        localization.string(localized: "vocello.mac.studio.stopGenerating", defaultValue: "Stop generating",
               comment: "macOS interface: VoiceOver label of the Studio cancel control while a take renders. Presentation only.")
    }
    static var studioUnusualPacing: String {
        localization.string(localized: "vocello.mac.studio.unusualPacing", defaultValue: "Unusual pacing",
               comment: "macOS interface: title of the cadence notice on a completed take. Presentation only.")
    }
    static var textInputBatch: String {
        localization.string(localized: "vocello.mac.textInput.batch", defaultValue: "Batch",
               comment: "macOS interface: opens the batch generation sheet. Presentation only.")
    }
    static func textInputCharacterCount(_ count: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.textInput.characterCount",
            defaultValue: "%@ characters",
            comment: "macOS interface: character counter under the script editor; %@ is the count. Presentation only."), count)
    }
    static var textInputGenerate: String {
        localization.string(localized: "vocello.mac.textInput.generate", defaultValue: "Generate",
               comment: "macOS interface: primary generate action. Presentation only.")
    }
    static var textInputPlaceholder: String {
        localization.string(localized: "vocello.mac.textInput.placeholder", defaultValue: "Type or paste your script",
               comment: "macOS interface: placeholder of the script editor. Presentation only.")
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
    static var textInputUnpinSeed: String {
        localization.string(localized: "vocello.mac.textInput.unpinSeed", defaultValue: "Unpin seed",
               comment: "macOS interface: VoiceOver label of the seed unpin button. Presentation only.")
    }
    static var tryAgain: String {
        localization.string(localized: "vocello.mac.common.tryAgain", defaultValue: "Try Again",
               comment: "macOS interface: reload after a failed load. Presentation only.")
    }
    static var variantBits06B4: String {
        localization.string(localized: "vocello.mac.variant.bits06B4", defaultValue: "0.6B 4-bit",
               comment: "macOS interface: size and quantization caption of the Lite variant. Presentation only.")
    }
    static var variantBits06B8: String {
        localization.string(localized: "vocello.mac.variant.bits06B8", defaultValue: "0.6B 8-bit",
               comment: "macOS interface: size and quantization caption of the Lite+ variant. Presentation only.")
    }
    static var variantBits17B4: String {
        localization.string(localized: "vocello.mac.variant.bits17B4", defaultValue: "1.7B 4-bit",
               comment: "macOS interface: size and quantization caption of the Speed variant. Presentation only.")
    }
    static var variantBits17B8: String {
        localization.string(localized: "vocello.mac.variant.bits17B8", defaultValue: "1.7B 8-bit",
               comment: "macOS interface: size and quantization caption of the Quality variant. Presentation only.")
    }
    static var variantDepth4: String {
        localization.string(localized: "vocello.mac.variant.depth4", defaultValue: "4-bit",
               comment: "macOS interface: quantization depth shown after the variant name in Settings package rows. Presentation only.")
    }
    static var variantDepth8: String {
        localization.string(localized: "vocello.mac.variant.depth8", defaultValue: "8-bit",
               comment: "macOS interface: quantization depth shown after the variant name in Settings package rows. Presentation only.")
    }
    static var variantLite: String {
        localization.string(localized: "vocello.mac.variant.lite", defaultValue: "Lite",
               comment: "macOS interface: name of the 0.6B 4-bit model variant. Presentation only.")
    }
    static var variantLitePlus: String {
        localization.string(localized: "vocello.mac.variant.litePlus", defaultValue: "Lite+",
               comment: "macOS interface: name of the 0.6B 8-bit model variant. Presentation only.")
    }
    static var variantQuality: String {
        localization.string(localized: "vocello.mac.variant.quality", defaultValue: "Quality",
               comment: "macOS interface: name of the 1.7B 8-bit model variant. Presentation only.")
    }
    static var variantSpeed: String {
        localization.string(localized: "vocello.mac.variant.speed", defaultValue: "Speed",
               comment: "macOS interface: name of the 1.7B 4-bit model variant. Presentation only.")
    }
    static var voicesAddVoiceSampleAction: String {
        localization.string(localized: "vocello.mac.voices.addVoiceSampleAction", defaultValue: "Add Voice Sample",
               comment: "macOS interface: Saved Voices toolbar button that opens the Add Voice Sample sheet. Presentation only.")
    }
    static var voicesAudioOnlyFallback: String {
        localization.string(localized: "vocello.mac.voices.audioOnlyFallback", defaultValue: "Audio-only fallback",
               comment: "macOS interface: Saved Voices status chip for a voice without a transcript. Presentation only.")
    }
    static var voicesDeleteAction: String {
        localization.string(localized: "vocello.mac.voices.deleteAction", defaultValue: "Delete voice",
               comment: "macOS interface: Saved Voices row delete action label. Presentation only.")
    }
    static func voicesDeleteDetail(_ name: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.voices.deleteDetail",
            defaultValue: "This will permanently remove “%1$@” from Saved Voices.",
            comment: "macOS interface: Saved Voices delete confirmation body. %1$@ is the saved voice name, never translated."), name)
    }
    static var voicesDeleteFailed: String {
        localization.string(localized: "vocello.mac.voices.deleteFailed", defaultValue: "Delete Failed",
               comment: "macOS interface: alert title when a saved voice cannot be removed. Presentation only.")
    }
    static func voicesDeleteFailedMessage(_ error: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.voices.deleteFailedMessage",
            defaultValue: "Failed to remove the saved voice: %@",
            comment: "macOS interface: alert message when a saved voice cannot be removed; %@ is the error text. Presentation only."), error)
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
    static var voicesEngineStarting: String {
        localization.string(localized: "vocello.mac.voices.engineStarting", defaultValue: "Starting speech engine…",
               comment: "macOS interface: Saved Voices state title while the engine is not ready yet. Presentation only.")
    }
    static var voicesLoadFailedTitle: String {
        localization.string(localized: "vocello.mac.voices.loadFailedTitle", defaultValue: "Couldn't load saved voices",
               comment: "macOS interface: Saved Voices error-state title. Presentation only.")
    }
    static var voicesLoading: String {
        localization.string(localized: "vocello.mac.voices.loading", defaultValue: "Loading saved voices...",
               comment: "macOS interface: Saved Voices loading placeholder. Presentation only.")
    }
    static var voicesNoVoicesTitle: String {
        localization.string(localized: "vocello.mac.voices.noVoicesTitle", defaultValue: "No saved voices",
               comment: "macOS interface: Saved Voices empty-state title. Presentation only.")
    }
    static var voicesUse: String {
        localization.string(localized: "vocello.mac.voices.use", defaultValue: "Use",
               comment: "macOS interface: compact button that selects a saved voice in Voice Cloning.")
    }
    static var voicesMoreActions: String {
        localization.string(localized: "vocello.mac.voices.moreActions", defaultValue: "More actions",
               comment: "macOS interface: accessibility label for a saved voice row's secondary actions menu.")
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
    static var voicesUseHelp: String {
        localization.string(localized: "vocello.mac.voices.useHelp", defaultValue: "Open Voice Cloning with this saved voice selected.",
               comment: "macOS interface: tooltip of the Saved Voices row action that opens Voice Cloning. Presentation only.")
    }
    static var voicesUseHelpInstall: String {
        localization.string(localized: "vocello.mac.voices.useHelpInstall", defaultValue: "Open Voice Cloning with this saved voice selected. Install the Voice Cloning model in Settings to generate from it.",
               comment: "macOS interface: tooltip of the Saved Voices row action when the Voice Cloning model is not installed. Presentation only.")
    }
    static func voicesVoiceBank(_ delivery: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.voices.voiceBank",
            defaultValue: "Voice bank · %@",
            comment: "macOS interface: Saved Voices row caption for a voice-bank member; %@ is the delivery preset name. Presentation only."), delivery)
    }
    static var voicesWaitingForEngine: String {
        localization.string(localized: "vocello.mac.voices.waitingForEngine", defaultValue: "Saved voices will appear once the speech engine is ready.",
               comment: "macOS interface: Saved Voices placeholder while the engine starts. Presentation only.")
    }
    static var voicesWarningReferenceExceedsLimit: String {
        localization.string(localized: "vocello.mac.voices.warningReferenceExceedsLimit", defaultValue: "Reference exceeds 60 s",
               comment: "macOS interface: warning pill for a reference clip over the hard 60 second limit. Presentation only.")
    }
    static var voicesWarningReferenceTooLong: String {
        localization.string(localized: "vocello.mac.voices.warningReferenceTooLong", defaultValue: "Reference too long",
               comment: "macOS interface: warning pill for a reference clip over the recommended duration. Presentation only.")
    }
    static var voicesWarningReferenceTooShort: String {
        localization.string(localized: "vocello.mac.voices.warningReferenceTooShort", defaultValue: "Reference too short",
               comment: "macOS interface: warning pill for a reference clip under the recommended duration. Presentation only.")
    }
    static var voicesWarningReferenceUnreadable: String {
        localization.string(localized: "vocello.mac.voices.warningReferenceUnreadable", defaultValue: "Reference unreadable",
               comment: "macOS interface: warning pill for a reference clip that could not be decoded. Presentation only.")
    }
    static var voicesYourVoices: String {
        localization.string(localized: "vocello.mac.voices.yourVoices", defaultValue: "Your voices",
               comment: "macOS interface: Saved Voices list section heading. Presentation only.")
    }
    static var workflowAllLanguages: String {
        localization.string(localized: "vocello.mac.workflow.allLanguages", defaultValue: "All languages",
               comment: "macOS interface: language picker section. Presentation only.")
    }
    static var workflowDeliveryDisabledFamily: String {
        localization.string(localized: "vocello.mac.workflow.deliveryDisabledFamily", defaultValue: "Delivery controls are disabled for this Qwen3 family.",
               comment: "macOS interface: tooltip sentence appended for variants without delivery controls. Presentation only.")
    }
    static func workflowDetectedLanguage(_ language: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.workflow.detectedLanguage",
            defaultValue: "%@ — Detected",
            comment: "macOS interface: language menu row for the detected language; %@ is the language name. Presentation only."), language)
    }
    static var workflowHeavyHelp: String {
        localization.string(localized: "vocello.mac.workflow.heavyHelp", defaultValue: "This package is heavy for this Mac's memory. Generation may be slow or unstable under pressure.",
               comment: "macOS interface: tooltip of the Heavy badge in the generation workflow. Presentation only.")
    }
    static var workflowHeavyOnThisMac: String {
        localization.string(localized: "vocello.mac.workflow.heavyOnThisMac", defaultValue: "Heavy on this Mac",
               comment: "macOS interface: model picker caption part when the model strains this Mac's memory. Presentation only.")
    }
    static var workflowModel: String {
        localization.string(localized: "vocello.mac.workflow.model", defaultValue: "Model",
               comment: "macOS interface: package picker label. Presentation only.")
    }
    static var workflowNoDeliveryControl: String {
        localization.string(localized: "vocello.mac.workflow.noDeliveryControl", defaultValue: "No delivery control",
               comment: "macOS interface: model picker caption part for models without delivery controls. Presentation only.")
    }
    static var workflowNoModel: String {
        localization.string(localized: "vocello.mac.workflow.noModel", defaultValue: "No model",
               comment: "macOS interface: model picker caption when no model is selected. Presentation only.")
    }
    static func workflowPackageHelp(_ mode: String, _ status: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.workflow.packageHelp",
            defaultValue: "Choose the Qwen3-TTS package for %1$@. Current status: %2$@.",
            comment: "macOS interface: tooltip of the package picker. %1$@ is the mode name, %2$@ the status caption; both already localized."), mode, status)
    }
    static func workflowUseVariantHelp(_ variant: String, _ mode: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.workflow.useVariantHelp",
            defaultValue: "Use the %1$@ model for %2$@.",
            comment: "macOS interface: tooltip of a selectable variant; %1$@ variant name, %2$@ mode name. Presentation only."), variant, mode)
    }
    static func workflowVariantNeedsRepair(_ depth: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.workflow.variantNeedsRepair",
            defaultValue: "%@, needs repair",
            comment: "macOS interface: VoiceOver value of a damaged variant; %@ is its size caption. Presentation only."), depth)
    }
    static func workflowVariantNotInstalled(_ depth: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.workflow.variantNotInstalled",
            defaultValue: "%@, not installed",
            comment: "macOS interface: VoiceOver value of a missing variant; %@ is its size caption. Presentation only."), depth)
    }
    static func workflowVariantNotInstalledHelp(_ mode: String, _ variant: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.workflow.variantNotInstalledHelp",
            defaultValue: "%1$@ %2$@ is not installed. Open Settings to manage model downloads.",
            comment: "macOS interface: tooltip of a missing variant; %1$@ mode name, %2$@ variant name. Presentation only."), mode, variant)
    }
    static func workflowVariantReady(_ depth: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.workflow.variantReady",
            defaultValue: "%@, ready",
            comment: "macOS interface: VoiceOver value of an installed variant; %@ is its size caption. Presentation only."), depth)
    }
    static var workflowVariantUnavailable: String {
        localization.string(localized: "vocello.mac.workflow.variantUnavailable", defaultValue: "unavailable",
               comment: "macOS interface: VoiceOver value of a model variant that does not exist for the mode. Presentation only.")
    }
    static func workflowVariantUnavailableHelp(_ mode: String, _ variant: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.workflow.variantUnavailableHelp",
            defaultValue: "%1$@ %2$@ is unavailable.",
            comment: "macOS interface: tooltip of a variant the mode does not offer; %1$@ mode name, %2$@ variant name. Presentation only."), mode, variant)
    }
    static func workflowVariantUpdateAvailable(_ depth: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.workflow.variantUpdateAvailable",
            defaultValue: "%@, update available",
            comment: "macOS interface: VoiceOver value of an outdated variant; %@ is its size caption. Presentation only."), depth)
    }

    // MARK: - Model-driven labels

    /// Sampling variation names for the Settings picker; `Qwen3SamplingVariation.rawValue`
    /// stays the stored preference and the engine identity.
    static func settingsVariationName(_ variation: Qwen3SamplingVariation) -> String {
        switch variation {
        case .expressive: settingsVariationExpressive
        case .balanced: settingsVariationBalanced
        case .consistent: settingsVariationConsistent
        }
    }
    // Hand-maintained: each branch reads a catalog entry above, so enum cases and
    // engine activity labels reach the interface language without leaving the owner.

    // MARK: Engine display strings (PA-20, MAC-06)
    // QwenVoiceCore keeps English identities (`Qwen3SupportedLanguage.displayName`,
    // `PreparedVoiceQualityWarning`, `DeliveryInstructionAdvisor.advisoryMessage`,
    // `EmotionPreset.label`) for the engine, CLI and telemetry; the Mac interface
    // renders them through these catalog helpers.

    static var languageAuto: String {
        localization.string(localized: "vocello.mac.language.auto", defaultValue: "Auto",
               comment: "macOS interface: language menu option that follows the detected language. Presentation only.")
    }
    static var languageChinese: String {
        localization.string(localized: "vocello.mac.language.chinese", defaultValue: "Chinese",
               comment: "macOS interface: display name of a speech language. Presentation only.")
    }
    static var languageEnglish: String {
        localization.string(localized: "vocello.mac.language.english", defaultValue: "English",
               comment: "macOS interface: display name of a speech language. Presentation only.")
    }
    static var languageJapanese: String {
        localization.string(localized: "vocello.mac.language.japanese", defaultValue: "Japanese",
               comment: "macOS interface: display name of a speech language. Presentation only.")
    }
    static var languageKorean: String {
        localization.string(localized: "vocello.mac.language.korean", defaultValue: "Korean",
               comment: "macOS interface: display name of a speech language. Presentation only.")
    }
    static var languageGerman: String {
        localization.string(localized: "vocello.mac.language.german", defaultValue: "German",
               comment: "macOS interface: display name of a speech language. Presentation only.")
    }
    static var languageFrench: String {
        localization.string(localized: "vocello.mac.language.french", defaultValue: "French",
               comment: "macOS interface: display name of a speech language. Presentation only.")
    }
    static var languageRussian: String {
        localization.string(localized: "vocello.mac.language.russian", defaultValue: "Russian",
               comment: "macOS interface: display name of a speech language. Presentation only.")
    }
    static var languagePortuguese: String {
        localization.string(localized: "vocello.mac.language.portuguese", defaultValue: "Portuguese",
               comment: "macOS interface: display name of a speech language. Presentation only.")
    }
    static var languageSpanish: String {
        localization.string(localized: "vocello.mac.language.spanish", defaultValue: "Spanish",
               comment: "macOS interface: display name of a speech language. Presentation only.")
    }
    static var languageItalian: String {
        localization.string(localized: "vocello.mac.language.italian", defaultValue: "Italian",
               comment: "macOS interface: display name of a speech language. Presentation only.")
    }
    static var qualityShort: String {
        localization.string(localized: "vocello.mac.quality.short", defaultValue: "Reference is shorter than recommended (under 10 seconds).",
               comment: "macOS interface: saved-voice reference quality warning copy. Presentation only.")
    }
    static var qualityLong: String {
        localization.string(localized: "vocello.mac.quality.long", defaultValue: "Reference is longer than recommended (over 30 seconds).",
               comment: "macOS interface: saved-voice reference quality warning copy. Presentation only.")
    }
    static var qualityExcessive: String {
        localization.string(localized: "vocello.mac.quality.excessive", defaultValue: "Reference exceeds the 60 second maximum supported for cloning.",
               comment: "macOS interface: saved-voice reference quality warning copy. Presentation only.")
    }
    static var qualityUnreadable: String {
        localization.string(localized: "vocello.mac.quality.unreadable", defaultValue: "Reference audio could not be read.",
               comment: "macOS interface: saved-voice reference quality warning copy. Presentation only.")
    }
    static var qualityIntro: String {
        localization.string(localized: "vocello.mac.quality.intro", defaultValue: "Voice cloning works best with 10–20 seconds of clean speech.",
               comment: "macOS interface: saved-voice reference quality warning copy. Presentation only.")
    }
    static var qualityHard: String {
        localization.string(localized: "vocello.mac.quality.hard", defaultValue: "Pick a clip that is 60 seconds or shorter to use it for cloning.",
               comment: "macOS interface: saved-voice reference quality warning copy. Presentation only.")
    }
    static var qualitySoft: String {
        localization.string(localized: "vocello.mac.quality.soft", defaultValue: "Clones from references outside this range still work, but may sound less consistent.",
               comment: "macOS interface: saved-voice reference quality warning copy. Presentation only.")
    }
    static var deliveryDurationAdvisory: String {
        localization.string(localized: "vocello.mac.delivery.durationAdvisory", defaultValue: "Timing requests aren’t honored — the voice can’t target a duration, so this may distort pacing instead.",
               comment: "macOS interface: advisory under a custom delivery that asks for a duration. Presentation only.")
    }
    static var presetHappy: String {
        localization.string(localized: "vocello.mac.preset.happy", defaultValue: "Happy",
               comment: "macOS interface: delivery preset name in a voice-bank caption. Presentation only.")
    }
    static var presetSad: String {
        localization.string(localized: "vocello.mac.preset.sad", defaultValue: "Sad",
               comment: "macOS interface: delivery preset name in a voice-bank caption. Presentation only.")
    }
    static var presetAngry: String {
        localization.string(localized: "vocello.mac.preset.angry", defaultValue: "Angry",
               comment: "macOS interface: delivery preset name in a voice-bank caption. Presentation only.")
    }
    static var presetFearful: String {
        localization.string(localized: "vocello.mac.preset.fearful", defaultValue: "Fearful",
               comment: "macOS interface: delivery preset name in a voice-bank caption. Presentation only.")
    }
    static var presetSurprised: String {
        localization.string(localized: "vocello.mac.preset.surprised", defaultValue: "Surprised",
               comment: "macOS interface: delivery preset name in a voice-bank caption. Presentation only.")
    }
    static var presetCalm: String {
        localization.string(localized: "vocello.mac.preset.calm", defaultValue: "Calm",
               comment: "macOS interface: delivery preset name in a voice-bank caption. Presentation only.")
    }
    static var presetWhisper: String {
        localization.string(localized: "vocello.mac.preset.whisper", defaultValue: "Whisper",
               comment: "macOS interface: delivery preset name in a voice-bank caption. Presentation only.")
    }
    static var savedVoiceDesignedVoiceFallback: String {
        localization.string(localized: "vocello.mac.savedVoice.designedVoiceFallback", defaultValue: "Designed_Voice",
               comment: "macOS interface: suggested saved-voice name when a Voice Design brief gives no words. Presentation only.")
    }
    static func historySuggestedVoiceName(_ voice: String) -> String {
        localization.format(localization.string(localized: "vocello.mac.history.suggestedVoiceName",
            defaultValue: "%@ Sample",
            comment: "macOS interface: suggested name when saving a History clone result as a voice; %@ is the take's voice name. Presentation only."), voice)
    }

    /// Interface name of a speech language.
    static func languageName(_ language: Qwen3SupportedLanguage) -> String {
        switch language {
        case .auto: languageAuto
        case .chinese: languageChinese
        case .english: languageEnglish
        case .japanese: languageJapanese
        case .korean: languageKorean
        case .german: languageGerman
        case .french: languageFrench
        case .russian: languageRussian
        case .portuguese: languagePortuguese
        case .spanish: languageSpanish
        case .italian: languageItalian
        }
    }

    /// Interface name of a delivery preset by id; the base delivery reads
    /// `deliveryNeutral`, an unknown id nil.
    static func presetName(id: String) -> String? {
        switch id {
        case "neutral": deliveryNeutral
        case "happy": presetHappy
        case "sad": presetSad
        case "angry": presetAngry
        case "fearful": presetFearful
        case "surprised": presetSurprised
        case "calm": presetCalm
        case "whisper": presetWhisper
        default: nil
        }
    }

    /// Interface headline of a saved-voice quality warning token, or nil for
    /// tokens without one (`PreparedVoiceQualityWarning.headline(for:)`).
    static func qualityWarningHeadline(token: String) -> String? {
        switch token {
        case "reference_duration_short": qualityShort
        case "reference_duration_long": qualityLong
        case "reference_duration_excessive": qualityExcessive
        case "reference_quality_unreadable": qualityUnreadable
        default: nil
        }
    }

    /// Interface rendering of `PreparedVoiceQualityWarning.summary(for:)`.
    static func qualityWarningSummary(tokens: [String]) -> String {
        let lines = tokens.compactMap { qualityWarningHeadline(token: $0) }
        guard !lines.isEmpty else { return qualityIntro }
        let trailer = PreparedVoiceQualityWarning.isHardBlocking(tokens) ? qualityHard : qualitySoft
        return qualityIntro + "\n\n" + lines.map { "• \($0)" }.joined(separator: "\n") + "\n\n" + trailer
    }

    /// Interface name of a generation mode (`GenerationMode.displayName` is the
    /// English identity shared with the engine, CLI and telemetry).
    static func modeName(_ mode: GenerationMode) -> String {
        switch mode {
        case .custom: menuBuiltInVoice
        case .design: menuVoiceDesign
        case .clone: menuVoiceCloning
        }
    }

    /// Compact pill label for a saved-voice quality warning token, or nil for
    /// tokens without a short form (`PreparedVoiceQualityWarning` owns the tokens).
    static func qualityWarningShortLabel(token: String) -> String? {
        switch token {
        case "reference_duration_short": voicesWarningReferenceTooShort
        case "reference_duration_long": voicesWarningReferenceTooLong
        case "reference_duration_excessive": voicesWarningReferenceExceedsLimit
        case "reference_quality_unreadable": voicesWarningReferenceUnreadable
        default: nil
        }
    }

    /// Interface rendering of an engine activity label; the engine emits the
    /// English identities in `EngineActivityLabels`, which the store compares by
    /// value, so mapping happens only at presentation time.
    static func activityLabel(_ label: String) -> String {
        if label == EngineActivityLabels.preparingVoiceReference {
            return activityPreparingVoiceReference
        }
        for mode in GenerationMode.allCases where label == EngineActivityLabels.generating(mode: mode) {
            return activityGenerating(modeName(mode))
        }
        return label
    }
}
