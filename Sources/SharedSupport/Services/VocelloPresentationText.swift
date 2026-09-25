import Foundation
import QwenVoiceCore

/// Typed presentation vocabulary for user-visible status and dynamic error text.
///
/// English is the source language; French catalog copy is maintained alongside it. New presentation
/// strings enter through this vocabulary and `Localizable.xcstrings`, which
/// gives translators stable semantic keys, context, substitutions, and plural
/// rules before any broad translation work begins.
struct VocelloPresentationText: Sendable {
    let localization: VocelloLocalization

    init(localization: VocelloLocalization = VocelloLocalization()) {
        self.localization = localization
    }
    var settingsAudio: String {
        localization.string(localized: "vocello.settings.refinement.audio", defaultValue: "Audio",
               comment: "Settings audio; preserve product and consent meaning.")
    }
    var settingsAudioSummary: String {
        localization.string(localized: "vocello.settings.refinement.audioSummary", defaultValue: "Playback and take variation",
               comment: "Settings audioSummary; preserve product and consent meaning.")
    }
    var settingsModelsFiles: String {
        localization.string(localized: "vocello.settings.refinement.modelsFiles", defaultValue: "Models & Files",
               comment: "Settings modelsFiles; preserve product and consent meaning.")
    }
    var settingsModelsFilesSummary: String {
        localization.string(localized: "vocello.settings.refinement.modelsFilesSummary", defaultValue: "Voice models and saved outputs",
               comment: "Settings modelsFilesSummary; preserve product and consent meaning.")
    }
    var settingsPrivacyPermissions: String {
        localization.string(localized: "vocello.settings.refinement.privacyPermissions", defaultValue: "Privacy & Permissions",
               comment: "Settings privacyPermissions; preserve product and consent meaning.")
    }
    var settingsPrivacyPermissionsSummary: String {
        localization.string(localized: "vocello.settings.refinement.privacyPermissionsSummary", defaultValue: "Voice consent and permissions",
               comment: "Settings privacyPermissionsSummary; preserve product and consent meaning.")
    }
    var settingsAccessibility: String {
        localization.string(localized: "vocello.settings.refinement.accessibility", defaultValue: "Accessibility",
               comment: "Settings accessibility; preserve product and consent meaning.")
    }
    var settingsAccessibilitySummary: String {
        localization.string(localized: "vocello.settings.refinement.accessibilitySummary", defaultValue: "Motion and transparency",
               comment: "Settings accessibilitySummary; preserve product and consent meaning.")
    }
    var settingsAbout: String {
        localization.string(localized: "vocello.settings.refinement.about", defaultValue: "About",
               comment: "Settings about; preserve product and consent meaning.")
    }
    var settingsAboutSummary: String {
        localization.string(localized: "vocello.settings.refinement.aboutSummary", defaultValue: "Support and app information",
               comment: "Settings aboutSummary; preserve product and consent meaning.")
    }
    var settingsBack: String {
        localization.string(localized: "vocello.settings.refinement.back", defaultValue: "Back to Settings",
               comment: "Settings back; preserve product and consent meaning.")
    }

    // Navigation vocabulary used by both platform adapters.
    var tabVoices: String {
        localization.string(localized: "vocello.ui.tabVoices", defaultValue: "Voices",
               comment: "Bottom navigation tab for saved voices.")
    }
    var modeBuiltIn: String {
        localization.string(localized: "vocello.ui.modeBuiltIn", defaultValue: "Built-in",
               comment: "Compact Studio selector for built-in voices; presentation only.")
    }
    var modeDesign: String {
        localization.string(localized: "vocello.ui.modeDesign", defaultValue: "Design",
               comment: "Compact Studio selector for voice design; presentation only.")
    }
    var modeClone: String {
        localization.string(localized: "vocello.ui.modeClone", defaultValue: "Clone",
               comment: "Compact Studio selector for voice cloning; presentation only.")
    }

    func playerSubtitle(_ subtitle: String, duration: String) -> String {
        localization.format(localization.string(localized: "vocello.presentation.playerSubtitle",
            defaultValue: "%1$@ · %2$@",
            comment: "Complete user-facing playerSubtitle message. Preserve substitution identities."), subtitle, duration)
    }

    func downloadedBytes(_ bytes: String) -> String {
        localization.format(localization.string(localized: "vocello.presentation.downloadedBytes",
            defaultValue: "%1$@ downloaded",
            comment: "Complete user-facing downloadedBytes message. Preserve substitution identities."), bytes)
    }

    var downloadFinishing: String {
        localization.string(localized: "vocello.presentation.downloadFinishing", defaultValue: "Download complete — finishing setup.",
               comment: "User-facing downloadFinishing message.")
    }

    func downloadTransfer(_ percent: Int, completed: String, total: String) -> String {
        localization.format(localization.string(localized: "vocello.presentation.downloadTransfer",
            defaultValue: "%1$lld%% · %2$@ of %3$@",
            comment: "Complete user-facing downloadTransfer message. Preserve substitution identities."), percent, completed, total)
    }

    func downloadAccessibility(_ percent: Int, completed: Int64, total: Int64) -> String {
        localization.format(localization.string(localized: "vocello.presentation.downloadAccessibility",
            defaultValue: "%1$lld%% — %2$lld of %3$lld bytes",
            comment: "Complete user-facing downloadAccessibility message. Preserve substitution identities."), percent, completed, total)
    }

    func downloadRemaining(_ seconds: Int) -> String {
        localization.format(localization.string(localized: "vocello.presentation.downloadRemaining",
            defaultValue: "about %1$llds remaining",
            comment: "Complete user-facing downloadRemaining message. Preserve substitution identities."), seconds)
    }

    func downloadRetry(_ count: Int) -> String {
        localization.format(localization.string(localized: "vocello.presentation.downloadRetry",
            defaultValue: "Preparing retry %1$lld. Verified files will be reused.",
            comment: "Complete user-facing downloadRetry message. Preserve substitution identities."), count)
    }

    func downloadRetryReason(_ count: Int, reason: String) -> String {
        localization.format(localization.string(localized: "vocello.presentation.downloadRetryReason",
            defaultValue: "Preparing retry %1$lld: %2$@. Verified files will be reused.",
            comment: "Complete user-facing downloadRetryReason message. Preserve substitution identities."), count, reason)
    }

    var longFormGuidance: String {
        localization.string(localized: "vocello.presentation.longFormGuidance", defaultValue: "Long-form script — Vocello plans segments, streams each one, and joins them into a single take.",
               comment: "User-facing longFormGuidance message.")
    }

    var longFormLimit: String {
        localization.string(localized: "vocello.presentation.longFormLimit", defaultValue: "At the single-take limit; keep typing for a long-form project.",
               comment: "User-facing longFormLimit message.")
    }

    func charactersRemaining(_ count: Int) -> String {
        localization.format(localization.string(localized: "vocello.presentation.charactersRemaining",
            defaultValue: "%1$lld characters remaining for a single take.",
            comment: "Complete user-facing charactersRemaining message. Preserve substitution identities."), count)
    }

    func shortenScript(_ limit: Int) -> String {
        localization.format(localization.string(localized: "vocello.presentation.shortenScript",
            defaultValue: "Shorten the script to %1$lld characters or less.",
            comment: "Complete user-facing shortenScript message. Preserve substitution identities."), limit)
    }

    func shortenScriptTitle(_ limit: Int) -> String {
        localization.format(localization.string(localized: "vocello.presentation.shortenScriptTitle",
            defaultValue: "Shorten script to %1$lld chars",
            comment: "Complete user-facing shortenScriptTitle message. Preserve substitution identities."), limit)
    }

    var preparingLongForm: String {
        localization.string(localized: "vocello.presentation.preparingLongForm", defaultValue: "Preparing long-form project…",
               comment: "User-facing preparingLongForm message.")
    }

    func regeneratingSegment(_ number: Int, total: Int) -> String {
        localization.format(localization.string(localized: "vocello.presentation.regeneratingSegment",
            defaultValue: "Regenerating segment %1$lld of %2$lld…",
            comment: "Complete user-facing regeneratingSegment message. Preserve substitution identities."), number, total)
    }

    func reusingSegment(_ number: Int, total: Int) -> String {
        localization.format(localization.string(localized: "vocello.presentation.reusingSegment",
            defaultValue: "Reusing segment %1$lld of %2$lld…",
            comment: "Complete user-facing reusingSegment message. Preserve substitution identities."), number, total)
    }

    func generatingSegment(_ number: Int, total: Int) -> String {
        localization.format(localization.string(localized: "vocello.presentation.generatingSegment",
            defaultValue: "Generating segment %1$lld of %2$lld…",
            comment: "Complete user-facing generatingSegment message. Preserve substitution identities."), number, total)
    }

    func generatedSegmentPending(_ number: Int, total: Int) -> String {
        localization.format(localization.string(localized: "vocello.presentation.generatedSegmentPending",
            defaultValue: "Generated segment %1$lld of %2$lld; project not yet saved",
            comment: "Complete user-facing generatedSegmentPending message. Preserve substitution identities."), number, total)
    }

    func joiningSegments(_ count: Int) -> String {
        localization.format(localization.string(localized: "vocello.presentation.joiningSegments",
            defaultValue: "Joining %1$lld segments…",
            comment: "Complete user-facing joiningSegments message. Preserve substitution identities."), count)
    }

    var done: String {
        localization.string(localized: "vocello.presentation.done", defaultValue: "Done",
               comment: "User-facing done message.")
    }

    var oldSegmentQC: String {
        localization.string(localized: "vocello.presentation.oldSegmentQC", defaultValue: "A previously generated segment no longer passes audio quality checks.",
               comment: "User-facing oldSegmentQC message.")
    }

    func segmentQC(_ number: Int, detail: String) -> String {
        localization.format(localization.string(localized: "vocello.presentation.segmentQC",
            defaultValue: "Segment %1$lld failed audio quality checks. %2$@",
            comment: "Complete user-facing segmentQC message. Preserve substitution identities."), number, detail)
    }

    func joinedQC(_ detail: String) -> String {
        localization.format(localization.string(localized: "vocello.presentation.joinedQC",
            defaultValue: "The joined long-form output failed audio quality checks: %1$@",
            comment: "Complete user-facing joinedQC message. Preserve substitution identities."), detail)
    }

    func assemblyFailed(_ detail: String) -> String {
        localization.format(localization.string(localized: "vocello.presentation.assemblyFailed",
            defaultValue: "Long-form assembly failed: %1$@",
            comment: "Complete user-facing assemblyFailed message. Preserve substitution identities."), detail)
    }

    var segmentNotInProject: String {
        localization.string(localized: "vocello.presentation.segmentNotInProject", defaultValue: "The segment to regenerate is not part of this completed project.",
               comment: "User-facing segmentNotInProject message.")
    }

    func regeneratedQC(_ detail: String) -> String {
        localization.format(localization.string(localized: "vocello.presentation.regeneratedQC",
            defaultValue: "The regenerated take failed audio quality checks; the previous take is unchanged. %1$@",
            comment: "Complete user-facing regeneratedQC message. Preserve substitution identities."), detail)
    }

    func regeneratedJoinedQC(_ detail: String) -> String {
        localization.format(localization.string(localized: "vocello.presentation.regeneratedJoinedQC",
            defaultValue: "The joined long-form output failed audio quality checks after regeneration: %1$@",
            comment: "Complete user-facing regeneratedJoinedQC message. Preserve substitution identities."), detail)
    }

    func segmentMissing(_ number: Int) -> String {
        localization.format(localization.string(localized: "vocello.presentation.segmentMissing",
            defaultValue: "Segment %1$lld has no generated audio to join.",
            comment: "Complete user-facing segmentMissing message. Preserve substitution identities."), number)
    }
    var exportRecoveryFiles: String {
        localization.string(localized: "vocello.history.export_recovery_files",
               defaultValue: "Export Recovery Files",
               comment: "User-directed export of retained audio and private recovery journals; not an upload or repair.")
    }

    var longFormRecoveryDetail: String {
        localization.string(localized: "vocello.history.long_form_recovery_detail",
               defaultValue: "Long-form recovery is incomplete. Unrelated clips remain readable; project changes are blocked. Retry a temporary storage failure, or export recovery files for repair. These private files may contain script text and local paths. Exporting does not repair or delete them.",
               comment: "Explains non-destructive recovery and the privacy implications of exporting an unresolved project journal.")
    }

    var longFormSegmentHistoryFailed: String {
        localization.string(localized: "vocello.long_form.segment_history_failed",
               defaultValue: "The segment audio was generated, but History could not finish saving it. Open History to retry storage or export the retained audio before quitting. The project has not been accepted.",
               comment: "Successful segment synthesis is distinct from History persistence and whole-project acceptance.")
    }

    func recoveryExportFailure(_ count: Int) -> String {
        localization.format(localization.string(localized: "vocello.history.recovery_export_failure",
            defaultValue: "%lld recovery files could not be exported.",
            comment: "Number of recovery files that failed a user-directed local export; originals remain retained."), count)
    }

    var historyUnqueuedTitle: String {
        localization.string(localized: "vocello.history.unqueued_title",
               defaultValue: "Audio ready — History not saved",
               comment: "Successful synthesis with a failure to durably queue its History record; not an engine failure.")
    }

    var historyUnqueuedDetail: String {
        localization.string(localized: "vocello.history.unqueued_detail",
               defaultValue: "Audio is still available. Retry saving or export it before quitting; recovery has not been safely queued.",
               comment: "Warning that unqueued History identity is held only in app-session memory, not crash-safe storage.")
    }

    var retryHistorySave: String {
        localization.string(localized: "vocello.history.retry_save",
               defaultValue: "Retry History Save",
               comment: "Retries storage only, never speech generation.")
    }

    var exportAudio: String {
        localization.string(localized: "vocello.history.export_audio",
               defaultValue: "Export Audio",
               comment: "Explicit system share/export action for finished audio.")
    }

    var dismissPlayerDetail: String {
        localization.string(localized: "vocello.player.dismiss_detail",
               defaultValue: "This closes the player without deleting the audio file. Saved takes can be replayed from History.",
               comment: "Player dismissal does not guarantee that the take's History write succeeded.")
    }

    var longFormSaveFailed: String {
        localization.string(localized: "vocello.long_form.save_failed",
               defaultValue: "The long-form project could not be saved safely. The previous accepted project is unchanged.",
               comment: "Long-form transaction rolled back without changing the prior accepted project.")
    }

    var longFormRecoveryRequired: String {
        localization.string(localized: "vocello.long_form.recovery_required",
               defaultValue: "Long-form storage needs recovery. Open History and retry before changing this project. Its saved takes are kept.",
               comment: "A long-form transaction needs reconciliation before the project can change; the project's takes already saved in History are never deleted by it.")
    }

    var longFormAcceptanceInterrupted: String {
        localization.string(localized: "vocello.long_form.acceptance_interrupted",
               defaultValue: "Saving this project to History was interrupted. Vocello finishes saving it when the app is active again, and its audio has been kept.",
               comment: "History was suspended while a finished long-form project was being saved; it completes automatically after the app returns and its audio is never deleted.")
    }

    var historyClearPendingTitle: String {
        localization.string(localized: "vocello.history.clear_pending_title",
               defaultValue: "Clearing History did not finish",
               comment: "History recovery banner title when a clear of History was interrupted and still has to finish.")
    }

    var historyClearPendingDetail: String {
        localization.string(localized: "vocello.history.clear_pending_detail",
               defaultValue: "Retry to finish clearing History. Takes saved after the clear started are kept.",
               comment: "History recovery banner detail for an interrupted clear; Retry resumes it and never removes takes saved after it started.")
    }

    var historyUnreadableAudioRemovals: String {
        localization.string(localized: "vocello.history.unreadable_audio_removals",
               defaultValue: "Vocello could not read its list of audio files from deleted takes, so it did not delete them. Retry to dismiss this notice.",
               comment: "History recovery banner detail: a private list of audio files waiting for deletion was unreadable, so those files stay on the device; Retry dismisses the notice and deletes no audio.")
    }

    var longFormSegmentGenerated: String {
        localization.string(localized: "vocello.long_form.segment_generated",
               defaultValue: "Generated",
               comment: "Segment audio exists, but whole-project acceptance may still be pending.")
    }

    enum Status: Sendable {
        case ready
        case generationFailed
        case checkingDownloadedFiles
        case makingModelAvailableOffline
    }

    enum EnrollmentTranscriptionStatus: Sendable {
        case awaitingAudio
        case sidecarReady
        case transcribing
        case automaticReady
        case manualReady
        case permissionDenied
        case unavailable
        case empty
        case cancelled
        case audioOnlyConfirmed
    }

    func status(_ status: Status) -> String {
        switch status {
        case .ready:
            return localization.string(localized: "vocello.status.ready",
                defaultValue: "Ready",
                comment: "Terminal status for an installed on-device voice model."
            )
        case .generationFailed:
            return localization.string(localized: "vocello.status.generation_failed",
                defaultValue: "Generation failed",
                comment: "Title shown when speech generation cannot complete."
            )
        case .checkingDownloadedFiles:
            return localization.string(localized: "vocello.status.checking_downloaded_files",
                defaultValue: "Checking downloaded files",
                comment: "Indeterminate model-install phase after all transfer bytes arrive."
            )
        case .makingModelAvailableOffline:
            return localization.string(localized: "vocello.status.making_model_available_offline",
                defaultValue: "Making the model available offline",
                comment: "Indeterminate model-install publication phase."
            )
        }
    }

    func enrollmentTranscriptionStatus(
        _ status: EnrollmentTranscriptionStatus
    ) -> String {
        switch status {
        case .awaitingAudio:
            return localization.string(localized: "vocello.enrollment.transcription.awaiting_audio",
                defaultValue: "Choose or record an audio clip to begin on-device transcription.",
                comment: "Enrollment status before a reference audio clip has been selected."
            )
        case .sidecarReady:
            return localization.string(localized: "vocello.enrollment.transcription.sidecar_ready",
                defaultValue: "Transcript loaded from the matching text file.",
                comment: "Enrollment status when an imported audio file had a neighboring transcript sidecar."
            )
        case .transcribing:
            return localization.string(localized: "vocello.enrollment.transcription.in_progress",
                defaultValue: "Transcribing on this device…",
                comment: "Enrollment status while local speech recognition processes the reference clip."
            )
        case .automaticReady:
            return localization.string(localized: "vocello.enrollment.transcription.automatic_ready",
                defaultValue: "Automatic transcript ready. Review it before saving.",
                comment: "Enrollment status after on-device speech recognition supplied editable text."
            )
        case .manualReady:
            return localization.string(localized: "vocello.enrollment.transcription.manual_ready",
                defaultValue: "Your transcript is ready.",
                comment: "Enrollment status after the user edits or enters the transcript."
            )
        case .permissionDenied:
            return localization.string(localized: "vocello.enrollment.transcription.permission_denied",
                defaultValue: "Speech recognition is unavailable. Enter a transcript or use audio only.",
                comment: "Enrollment recovery when speech-recognition authorization is unavailable."
            )
        case .unavailable:
            return localization.string(localized: "vocello.enrollment.transcription.unavailable",
                defaultValue: "On-device transcription is unavailable. Enter a transcript or use audio only.",
                comment: "Enrollment recovery when on-device speech recognition cannot run."
            )
        case .empty:
            return localization.string(localized: "vocello.enrollment.transcription.empty",
                defaultValue: "No automatic transcript was found. Enter one or use audio only.",
                comment: "Enrollment recovery when recognition completes without usable text."
            )
        case .cancelled:
            return localization.string(localized: "vocello.enrollment.transcription.cancelled",
                defaultValue: "Transcription stopped. Enter a transcript or use audio only.",
                comment: "Enrollment recovery after automatic transcription is cancelled."
            )
        case .audioOnlyConfirmed:
            return localization.string(localized: "vocello.enrollment.transcription.audio_only_confirmed",
                defaultValue: "Audio-only enrollment selected. The transcript will remain empty.",
                comment: "Enrollment status after explicit confirmation to save without a transcript."
            )
        }
    }

    var importReferenceAudioTitle: String {
        localization.string(localized: "vocello.enrollment.import_audio",
            defaultValue: "Import audio file",
            comment: "Action that opens Files to choose a voice-cloning reference clip."
        )
    }

    var importReferenceAudioDetail: String {
        localization.string(localized: "vocello.enrollment.import_audio.detail",
            defaultValue: "Choose a WAV, MP3, AIFF, or M4A file from Files.",
            comment: "Supported-format description below the reference-audio import action."
        )
    }

    var referenceLanguageTitle: String {
        localization.string(localized: "vocello.enrollment.reference_language",
            defaultValue: "Reference language",
            comment: "Enrollment field describing the language spoken in the saved reference clip."
        )
    }

    var referenceLanguageConfirmation: String {
        localization.string(localized: "vocello.enrollment.reference_language.confirmation",
            defaultValue: "Confirm the language spoken in this reference.",
            comment: "Enrollment guidance when automatic reference-language detection is inconclusive."
        )
    }

    var referenceLanguageDetail: String {
        localization.string(localized: "vocello.enrollment.reference_language.detail",
            defaultValue: "Used only to describe this saved reference.",
            comment: "Enrollment guidance clarifying that reference language does not select future output language."
        )
    }

    var referenceLanguagePlaceholder: String {
        localization.string(localized: "vocello.enrollment.reference_language.placeholder",
            defaultValue: "Choose a language",
            comment: "Placeholder option for an unconfirmed reference-clip language."
        )
    }

    var useAudioOnly: String {
        localization.string(localized: "vocello.enrollment.use_audio_only",
            defaultValue: "Use audio only",
            comment: "Explicit enrollment action used when no transcript is available."
        )
    }

    var useAudioOnlyHint: String {
        localization.string(localized: "vocello.enrollment.use_audio_only.hint",
            defaultValue: "Save this reference without transcript-backed delivery.",
            comment: "VoiceOver hint for the explicit audio-only enrollment action."
        )
    }

    func installModel(named modelName: String) -> String {
        let format = localization.string(localized: "vocello.error.install_model",
            defaultValue: "Install “%1$@” in Settings to generate audio.",
            comment: "Studio error. The substitution is the display name of a missing voice model."
        )
        return localization.format(format, modelName)
    }

    func longFormPlanningFailed(details: String) -> String {
        let format = localization.string(localized: "vocello.error.long_form_planning_failed",
            defaultValue: "Long-form planning failed: %1$@",
            comment: "Studio error. The substitution is a localized, non-sensitive planning error."
        )
        return localization.format(format, details)
    }

    var cloningConsentRequired: String {
        localization.string(localized: "vocello.error.cloning_consent_required",
            defaultValue: "Enable voice-cloning consent in Settings → Privacy before generating.",
            comment: "Studio error shown when Voice Cloning consent has not been acknowledged."
        )
    }

    var cloningConsentRequiredToSaveVoice: String {
        localization.string(localized: "vocello.error.cloning_consent_required_to_save_voice",
            defaultValue: "Enable voice-cloning consent in Settings → Privacy before saving a voice.",
            comment: "Saved-voice error shown when a voice is saved before Voice Cloning consent has been acknowledged."
        )
    }

    /// PA-17: the copy the core consent policy raises when it refuses clone
    /// generation or saved-voice enrollment below the views.
    var voiceCloningConsentRefusalCopy: VoiceCloningConsentPolicy.RefusalCopy {
        VoiceCloningConsentPolicy.RefusalCopy(
            generation: cloningConsentRequired,
            enrollment: cloningConsentRequiredToSaveVoice
        )
    }

    var referenceAudioRequired: String {
        localization.string(localized: "vocello.error.reference_audio_required",
            defaultValue: "Select a reference audio file before generating.",
            comment: "Voice Cloning error shown when no reference clip is selected."
        )
    }

    var savedVoicesStoreBusy: String {
        localization.string(localized: "vocello.error.saved_voices_busy",
            defaultValue: "Another Vocello process is updating Saved Voices. Try again in a moment.",
            comment: "Saved Voices error. Another Vocello process, such as the command-line tool, holds the shared saved-voice store for a moment; retrying later succeeds and nothing was lost."
        )
    }

    /// Saved Voice failures keep the engine's typed busy state distinct from
    /// other failures, whose existing descriptions are not reverse-translated.
    func savedVoiceErrorMessage(_ error: Error) -> String {
        if (error as? TTSEngineError) == .savedVoiceStoreBusy {
            return savedVoicesStoreBusy
        }
        return error.localizedDescription
    }

    /// Interface copy for a failure the engine or a generation run surfaces
    /// (PA-20): typed failures resolve to a path-free
    /// `GenerationFailurePresentationReason`, so the memory-pressure,
    /// runtime-failure, generation-limit and audio-quality copy the engine keeps
    /// in English for the CLI and diagnostics reaches the interface language.
    /// An error without a typed reason keeps its own description (host copy such
    /// as a consent refusal is already localized); raw detail stays in the
    /// failure journal.
    func generationFailureMessage(_ error: Error) -> String {
        guard let reason = GenerationFailurePresentationReason(error) else {
            return error.localizedDescription
        }
        return generationFailureMessage(reason)
    }

    func generationFailureMessage(_ reason: GenerationFailurePresentationReason) -> String {
        switch reason {
        case .memoryPressure:
            return localization.string(localized: "vocello.error.generation_memory_pressure",
                defaultValue: "There was not enough memory to finish this take, so it was not saved. Close other apps, then retry to generate a new take.",
                comment: "Studio error after MLX or Metal ran out of memory mid-take.")
        case .runtimeFailure:
            return localization.string(localized: "vocello.error.generation_runtime_failed",
                defaultValue: "The on-device voice engine hit an internal error, so this take was not saved. Retry to generate a new take.",
                comment: "Studio error after the on-device voice engine failed while a take was generating.")
        case .preparationFailure:
            return localization.string(localized: "vocello.error.generation_preparation_failed",
                defaultValue: "The on-device voice engine couldn't prepare the voice model. Try again; if it keeps failing, repair the model in Settings.",
                comment: "Error when the voice engine failed while loading or warming a model, before any take started.")
        case .generationLimit:
            return localization.string(localized: "vocello.error.generation_incomplete",
                defaultValue: "This take reached its generation limit before it finished, so the incomplete audio was not saved. Retry to generate a new take.",
                comment: "Studio error when a take reached the model's generation limit before it finished.")
        case .audioSilentGap:
            return localization.string(localized: "vocello.error.audio_qc_silent_gap",
                defaultValue: "The generated audio contained an unusually long silent gap and was not saved. Retry to generate a new take.",
                comment: "Studio error when the audio-quality check found an unusually long silence.")
        case .audioNoSpeech:
            return localization.string(localized: "vocello.error.audio_qc_no_speech",
                defaultValue: "The generated audio did not contain usable speech and was not saved. Retry to generate a new take.",
                comment: "Studio error when the audio-quality check found no usable speech.")
        case .audioUnstable:
            return localization.string(localized: "vocello.error.audio_qc_unstable",
                defaultValue: "The generated audio was unstable or distorted and was not saved. Retry to generate a new take.",
                comment: "Studio error when the audio-quality check found unstable or distorted audio.")
        case .audioQualityRejected:
            return localization.string(localized: "vocello.error.audio_qc_rejected",
                defaultValue: "The generated audio did not pass its mandatory quality check and was not saved. Retry to generate a new take.",
                comment: "Studio error when the mandatory audio-quality check rejected a take.")
        case .insufficientMemory:
            return localization.string(localized: "vocello.error.insufficient_memory",
                defaultValue: "Vocello needs more available memory before loading this model. Close background apps and try again.",
                comment: "Error when too little memory was free to load a voice model.")
        case .engineNotReady:
            return localization.string(localized: "vocello.error.engine_not_ready",
                defaultValue: "The voice engine is still starting. Try again in a moment.",
                comment: "Error when generation was requested before the voice engine finished starting.")
        case .savedVoiceStoreBusy:
            return savedVoicesStoreBusy
        case .modelUnavailable:
            return localization.string(localized: "vocello.error.model_unavailable",
                defaultValue: "This voice model is missing or incomplete. Repair or reinstall it in Settings.",
                comment: "Error when the installed voice model files are missing or incomplete.")
        case .referenceAudioMissing:
            return localization.string(localized: "vocello.error.reference_audio_missing",
                defaultValue: "The reference audio file is no longer available. Choose it again.",
                comment: "Voice Cloning error when the reference audio file was moved or deleted.")
        case .referenceAudioUnsupported:
            return localization.string(localized: "vocello.error.reference_audio_unsupported",
                defaultValue: "This audio format can't be used as a reference. Choose another audio file.",
                comment: "Voice Cloning error when the reference audio format cannot be decoded.")
        case .referenceAudioTooLong:
            return localization.string(localized: "vocello.error.reference_audio_too_long",
                defaultValue: "This reference audio is too long or too large to prepare. Choose a shorter clip.",
                comment: "Voice Cloning error when the reference audio exceeds the preparation limits.")
        case .referenceAudioUnreadable:
            return localization.string(localized: "vocello.error.reference_audio_unreadable",
                defaultValue: "Vocello couldn't read this reference audio. Choose another audio file.",
                comment: "Voice Cloning error when the reference audio could not be read.")
        case .storageFull:
            return localization.string(localized: "vocello.error.storage_full",
                defaultValue: "There isn't enough storage space to save this take. Free up space, then try again.",
                comment: "Error when the device ran out of storage while saving a take.")
        case .storageUnavailable:
            return localization.string(localized: "vocello.error.storage_unavailable",
                defaultValue: "Vocello couldn't write the audio file. Check that the output folder is available, then try again.",
                comment: "Error when the app could not create or write an audio file.")
        }
    }

    func cancellationCouldNotFinish(details: String) -> String {
        let format = localization.string(localized: "vocello.error.cancellation_not_finished",
            defaultValue: "Cancellation could not finish safely: %1$@",
            comment: "Studio error. The substitution explains why the engine cancellation barrier failed."
        )
        return localization.format(format, details)
    }

    /// Studio notice shown on return after leaving the foreground cancelled a
    /// short-form take (PA-15). The take is discarded, never saved to History.
    var backgroundTakeStopped: String {
        localization.string(localized: "vocello.presentation.backgroundTakeStopped",
            defaultValue: "Generation stopped when Vocello left the screen. The unfinished take was discarded.",
            comment: "Studio notice shown when the user returns after leaving the app (Home, app switch or lock) stopped a take. The unfinished audio was deleted and is not in History."
        )
    }

    /// Studio notice shown on return after leaving the foreground stopped a
    /// long-form project (PA-15). Completed segments are kept for Resume.
    var backgroundLongFormStopped: String {
        localization.string(localized: "vocello.presentation.backgroundLongFormStopped",
            defaultValue: "Long-form stopped when Vocello left the screen. Finished segments are kept; choose Resume project to continue.",
            comment: "Studio notice shown when the user returns after leaving the app stopped a long-form project. 'Resume project' must match the translated Resume project button label."
        )
    }

    // MARK: VoiceOver generation announcements (PA-20, IOS-12)

    var announceGenerationStarted: String {
        localization.string(localized: "vocello.presentation.announceGenerationStarted", defaultValue: "Generating take.",
               comment: "VoiceOver announcement when a Studio take or long-form project starts generating.")
    }

    var announceTakeReady: String {
        localization.string(localized: "vocello.presentation.announceTakeReady", defaultValue: "Take ready.",
               comment: "VoiceOver announcement when a Studio take or project is ready to play.")
    }

    func announceGenerationFailed(_ message: String) -> String {
        localization.format(localization.string(localized: "vocello.presentation.announceGenerationFailed",
            defaultValue: "Generation failed. %1$@",
            comment: "VoiceOver announcement when Studio generation failed; %1$@ is the localized error."), message)
    }

    var announceGenerationStopped: String {
        localization.string(localized: "vocello.presentation.announceGenerationStopped", defaultValue: "Generation stopped.",
               comment: "VoiceOver announcement when Studio generation was stopped.")
    }

    /// Representative plural contract. Product surfaces can adopt the same
    /// pattern without concatenating independently localized fragments.
    func readyModelCount(_ count: Int) -> String {
        let format = localization.string(localized: "vocello.models.ready_count",
            defaultValue: "%lld models ready",
            comment: "Summary count of installed on-device voice models."
        )
        return localization.format(format, count)
    }
}

// Default-locale callers retain their existing interface.
extension VocelloPresentationText {
    static var downloadFinishing: String { Self().downloadFinishing }
    static var longFormGuidance: String { Self().longFormGuidance }
    static var longFormLimit: String { Self().longFormLimit }
    static var preparingLongForm: String { Self().preparingLongForm }
    static var done: String { Self().done }
    static var oldSegmentQC: String { Self().oldSegmentQC }
    static var segmentNotInProject: String { Self().segmentNotInProject }
    static var exportRecoveryFiles: String { Self().exportRecoveryFiles }
    static var longFormRecoveryDetail: String { Self().longFormRecoveryDetail }
    static var longFormSegmentHistoryFailed: String { Self().longFormSegmentHistoryFailed }
    static var historyUnqueuedTitle: String { Self().historyUnqueuedTitle }
    static var historyUnqueuedDetail: String { Self().historyUnqueuedDetail }
    static var retryHistorySave: String { Self().retryHistorySave }
    static var exportAudio: String { Self().exportAudio }
    static var dismissPlayerDetail: String { Self().dismissPlayerDetail }
    static var longFormSaveFailed: String { Self().longFormSaveFailed }
    static var longFormRecoveryRequired: String { Self().longFormRecoveryRequired }
    static var longFormAcceptanceInterrupted: String { Self().longFormAcceptanceInterrupted }
    static var longFormSegmentGenerated: String { Self().longFormSegmentGenerated }
    static var importReferenceAudioTitle: String { Self().importReferenceAudioTitle }
    static var importReferenceAudioDetail: String { Self().importReferenceAudioDetail }
    static var referenceLanguageTitle: String { Self().referenceLanguageTitle }
    static var referenceLanguageConfirmation: String { Self().referenceLanguageConfirmation }
    static var referenceLanguageDetail: String { Self().referenceLanguageDetail }
    static var referenceLanguagePlaceholder: String { Self().referenceLanguagePlaceholder }
    static var useAudioOnly: String { Self().useAudioOnly }
    static var useAudioOnlyHint: String { Self().useAudioOnlyHint }
    static var cloningConsentRequired: String { Self().cloningConsentRequired }
    static var referenceAudioRequired: String { Self().referenceAudioRequired }
    static func playerSubtitle(_ subtitle: String, duration: String) -> String { Self().playerSubtitle(subtitle, duration: duration) }
    static func downloadedBytes(_ bytes: String) -> String { Self().downloadedBytes(bytes) }
    static func downloadTransfer(_ percent: Int, completed: String, total: String) -> String { Self().downloadTransfer(percent, completed: completed, total: total) }
    static func downloadAccessibility(_ percent: Int, completed: Int64, total: Int64) -> String { Self().downloadAccessibility(percent, completed: completed, total: total) }
    static func downloadRemaining(_ seconds: Int) -> String { Self().downloadRemaining(seconds) }
    static func downloadRetry(_ count: Int) -> String { Self().downloadRetry(count) }
    static func downloadRetryReason(_ count: Int, reason: String) -> String { Self().downloadRetryReason(count, reason: reason) }
    static func charactersRemaining(_ count: Int) -> String { Self().charactersRemaining(count) }
    static func shortenScript(_ limit: Int) -> String { Self().shortenScript(limit) }
    static func shortenScriptTitle(_ limit: Int) -> String { Self().shortenScriptTitle(limit) }
    static func regeneratingSegment(_ number: Int, total: Int) -> String { Self().regeneratingSegment(number, total: total) }
    static func reusingSegment(_ number: Int, total: Int) -> String { Self().reusingSegment(number, total: total) }
    static func generatingSegment(_ number: Int, total: Int) -> String { Self().generatingSegment(number, total: total) }
    static func generatedSegmentPending(_ number: Int, total: Int) -> String { Self().generatedSegmentPending(number, total: total) }
    static func joiningSegments(_ count: Int) -> String { Self().joiningSegments(count) }
    static func segmentQC(_ number: Int, detail: String) -> String { Self().segmentQC(number, detail: detail) }
    static func joinedQC(_ detail: String) -> String { Self().joinedQC(detail) }
    static func assemblyFailed(_ detail: String) -> String { Self().assemblyFailed(detail) }
    static func regeneratedQC(_ detail: String) -> String { Self().regeneratedQC(detail) }
    static func regeneratedJoinedQC(_ detail: String) -> String { Self().regeneratedJoinedQC(detail) }
    static func segmentMissing(_ number: Int) -> String { Self().segmentMissing(number) }
    static func recoveryExportFailure(_ count: Int) -> String { Self().recoveryExportFailure(count) }
    static func status(_ status: Status) -> String { Self().status(status) }
    static func enrollmentTranscriptionStatus(
        _ status: EnrollmentTranscriptionStatus
    ) -> String { Self().enrollmentTranscriptionStatus(status) }
    static func installModel(named modelName: String) -> String { Self().installModel(named: modelName) }
    static func longFormPlanningFailed(details: String) -> String { Self().longFormPlanningFailed(details: details) }
    static func cancellationCouldNotFinish(details: String) -> String { Self().cancellationCouldNotFinish(details: details) }
    static var backgroundTakeStopped: String { Self().backgroundTakeStopped }
    static var backgroundLongFormStopped: String { Self().backgroundLongFormStopped }
    static func readyModelCount(_ count: Int) -> String { Self().readyModelCount(count) }
}
