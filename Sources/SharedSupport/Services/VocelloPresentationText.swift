import Foundation

/// Typed presentation vocabulary for user-visible status and dynamic error text.
///
/// English is the source language; French catalog copy is maintained alongside it. New presentation
/// strings enter through this vocabulary and `Localizable.xcstrings`, which
/// gives translators stable semantic keys, context, substitutions, and plural
/// rules before any broad translation work begins.
enum VocelloPresentationText {
    static func playerSubtitle(_ subtitle: String, duration: String) -> String {
        String.localizedStringWithFormat(String(localized: "vocello.presentation.playerSubtitle",
            defaultValue: "%1$@ · %2$@",
            comment: "Complete user-facing playerSubtitle message. Preserve substitution identities."), subtitle, duration)
    }

    static func downloadedBytes(_ bytes: String) -> String {
        String.localizedStringWithFormat(String(localized: "vocello.presentation.downloadedBytes",
            defaultValue: "%1$@ downloaded",
            comment: "Complete user-facing downloadedBytes message. Preserve substitution identities."), bytes)
    }

    static var downloadFinishing: String {
        String(localized: "vocello.presentation.downloadFinishing", defaultValue: "Download complete — finishing setup.",
               comment: "User-facing downloadFinishing message.")
    }

    static func downloadTransfer(_ percent: Int, completed: String, total: String) -> String {
        String.localizedStringWithFormat(String(localized: "vocello.presentation.downloadTransfer",
            defaultValue: "%1$lld%% · %2$@ of %3$@",
            comment: "Complete user-facing downloadTransfer message. Preserve substitution identities."), percent, completed, total)
    }

    static func downloadAccessibility(_ percent: Int, completed: Int64, total: Int64) -> String {
        String.localizedStringWithFormat(String(localized: "vocello.presentation.downloadAccessibility",
            defaultValue: "%1$lld%% — %2$lld of %3$lld bytes",
            comment: "Complete user-facing downloadAccessibility message. Preserve substitution identities."), percent, completed, total)
    }

    static func downloadRemaining(_ seconds: Int) -> String {
        String.localizedStringWithFormat(String(localized: "vocello.presentation.downloadRemaining",
            defaultValue: "about %1$llds remaining",
            comment: "Complete user-facing downloadRemaining message. Preserve substitution identities."), seconds)
    }

    static func downloadRetry(_ count: Int) -> String {
        String.localizedStringWithFormat(String(localized: "vocello.presentation.downloadRetry",
            defaultValue: "Preparing retry %1$lld. Verified files will be reused.",
            comment: "Complete user-facing downloadRetry message. Preserve substitution identities."), count)
    }

    static func downloadRetryReason(_ count: Int, reason: String) -> String {
        String.localizedStringWithFormat(String(localized: "vocello.presentation.downloadRetryReason",
            defaultValue: "Preparing retry %1$lld: %2$@. Verified files will be reused.",
            comment: "Complete user-facing downloadRetryReason message. Preserve substitution identities."), count, reason)
    }

    static var longFormGuidance: String {
        String(localized: "vocello.presentation.longFormGuidance", defaultValue: "Long-form script — Vocello plans segments, streams each one, and joins them into a single take.",
               comment: "User-facing longFormGuidance message.")
    }

    static var longFormLimit: String {
        String(localized: "vocello.presentation.longFormLimit", defaultValue: "At the single-take limit; keep typing for a long-form project.",
               comment: "User-facing longFormLimit message.")
    }

    static func charactersRemaining(_ count: Int) -> String {
        String.localizedStringWithFormat(String(localized: "vocello.presentation.charactersRemaining",
            defaultValue: "%1$lld characters remaining for a single take.",
            comment: "Complete user-facing charactersRemaining message. Preserve substitution identities."), count)
    }

    static func shortenScript(_ limit: Int) -> String {
        String.localizedStringWithFormat(String(localized: "vocello.presentation.shortenScript",
            defaultValue: "Shorten the script to %1$lld characters or less.",
            comment: "Complete user-facing shortenScript message. Preserve substitution identities."), limit)
    }

    static func shortenScriptTitle(_ limit: Int) -> String {
        String.localizedStringWithFormat(String(localized: "vocello.presentation.shortenScriptTitle",
            defaultValue: "Shorten script to %1$lld chars",
            comment: "Complete user-facing shortenScriptTitle message. Preserve substitution identities."), limit)
    }

    static var preparingLongForm: String {
        String(localized: "vocello.presentation.preparingLongForm", defaultValue: "Preparing long-form project…",
               comment: "User-facing preparingLongForm message.")
    }

    static func regeneratingSegment(_ number: Int, total: Int) -> String {
        String.localizedStringWithFormat(String(localized: "vocello.presentation.regeneratingSegment",
            defaultValue: "Regenerating segment %1$lld of %2$lld…",
            comment: "Complete user-facing regeneratingSegment message. Preserve substitution identities."), number, total)
    }

    static func reusingSegment(_ number: Int, total: Int) -> String {
        String.localizedStringWithFormat(String(localized: "vocello.presentation.reusingSegment",
            defaultValue: "Reusing segment %1$lld of %2$lld…",
            comment: "Complete user-facing reusingSegment message. Preserve substitution identities."), number, total)
    }

    static func generatingSegment(_ number: Int, total: Int) -> String {
        String.localizedStringWithFormat(String(localized: "vocello.presentation.generatingSegment",
            defaultValue: "Generating segment %1$lld of %2$lld…",
            comment: "Complete user-facing generatingSegment message. Preserve substitution identities."), number, total)
    }

    static func generatedSegmentPending(_ number: Int, total: Int) -> String {
        String.localizedStringWithFormat(String(localized: "vocello.presentation.generatedSegmentPending",
            defaultValue: "Generated segment %1$lld of %2$lld; project not yet saved",
            comment: "Complete user-facing generatedSegmentPending message. Preserve substitution identities."), number, total)
    }

    static func joiningSegments(_ count: Int) -> String {
        String.localizedStringWithFormat(String(localized: "vocello.presentation.joiningSegments",
            defaultValue: "Joining %1$lld segments…",
            comment: "Complete user-facing joiningSegments message. Preserve substitution identities."), count)
    }

    static var done: String {
        String(localized: "vocello.presentation.done", defaultValue: "Done",
               comment: "User-facing done message.")
    }

    static var oldSegmentQC: String {
        String(localized: "vocello.presentation.oldSegmentQC", defaultValue: "A previously generated segment no longer passes audio quality checks.",
               comment: "User-facing oldSegmentQC message.")
    }

    static func segmentQC(_ number: Int, detail: String) -> String {
        String.localizedStringWithFormat(String(localized: "vocello.presentation.segmentQC",
            defaultValue: "Segment %1$lld failed audio quality checks. %2$@",
            comment: "Complete user-facing segmentQC message. Preserve substitution identities."), number, detail)
    }

    static func joinedQC(_ detail: String) -> String {
        String.localizedStringWithFormat(String(localized: "vocello.presentation.joinedQC",
            defaultValue: "The joined long-form output failed audio quality checks: %1$@",
            comment: "Complete user-facing joinedQC message. Preserve substitution identities."), detail)
    }

    static func assemblyFailed(_ detail: String) -> String {
        String.localizedStringWithFormat(String(localized: "vocello.presentation.assemblyFailed",
            defaultValue: "Long-form assembly failed: %1$@",
            comment: "Complete user-facing assemblyFailed message. Preserve substitution identities."), detail)
    }

    static var segmentNotInProject: String {
        String(localized: "vocello.presentation.segmentNotInProject", defaultValue: "The segment to regenerate is not part of this completed project.",
               comment: "User-facing segmentNotInProject message.")
    }

    static func regeneratedQC(_ detail: String) -> String {
        String.localizedStringWithFormat(String(localized: "vocello.presentation.regeneratedQC",
            defaultValue: "The regenerated take failed audio quality checks; the previous take is unchanged. %1$@",
            comment: "Complete user-facing regeneratedQC message. Preserve substitution identities."), detail)
    }

    static func regeneratedJoinedQC(_ detail: String) -> String {
        String.localizedStringWithFormat(String(localized: "vocello.presentation.regeneratedJoinedQC",
            defaultValue: "The joined long-form output failed audio quality checks after regeneration: %1$@",
            comment: "Complete user-facing regeneratedJoinedQC message. Preserve substitution identities."), detail)
    }

    static func segmentMissing(_ number: Int) -> String {
        String.localizedStringWithFormat(String(localized: "vocello.presentation.segmentMissing",
            defaultValue: "Segment %1$lld has no generated audio to join.",
            comment: "Complete user-facing segmentMissing message. Preserve substitution identities."), number)
    }
    static var exportRecoveryFiles: String {
        String(localized: "vocello.history.export_recovery_files",
               defaultValue: "Export Recovery Files",
               comment: "User-directed export of retained audio and private recovery journals; not an upload or repair.")
    }

    static var longFormRecoveryDetail: String {
        String(localized: "vocello.history.long_form_recovery_detail",
               defaultValue: "Long-form recovery is incomplete. Unrelated clips remain readable; project changes are blocked. Retry a temporary storage failure, or export recovery files for repair. These private files may contain script text and local paths. Exporting does not repair or delete them.",
               comment: "Explains non-destructive recovery and the privacy implications of exporting an unresolved project journal.")
    }

    static var longFormSegmentHistoryFailed: String {
        String(localized: "vocello.long_form.segment_history_failed",
               defaultValue: "The segment audio was generated, but History could not finish saving it. Open History to retry storage or export the retained audio before quitting. The project has not been accepted.",
               comment: "Successful segment synthesis is distinct from History persistence and whole-project acceptance.")
    }

    static func recoveryExportFailure(_ count: Int) -> String {
        String.localizedStringWithFormat(String(localized: "vocello.history.recovery_export_failure",
            defaultValue: "%lld recovery files could not be exported.",
            comment: "Number of recovery files that failed a user-directed local export; originals remain retained."), count)
    }

    static var historyUnqueuedTitle: String {
        String(localized: "vocello.history.unqueued_title",
               defaultValue: "Audio ready — History not saved",
               comment: "Successful synthesis with a failure to durably queue its History record; not an engine failure.")
    }

    static var historyUnqueuedDetail: String {
        String(localized: "vocello.history.unqueued_detail",
               defaultValue: "Audio is still available. Retry saving or export it before quitting; recovery has not been safely queued.",
               comment: "Warning that unqueued History identity is held only in app-session memory, not crash-safe storage.")
    }

    static var retryHistorySave: String {
        String(localized: "vocello.history.retry_save",
               defaultValue: "Retry History Save",
               comment: "Retries storage only, never speech generation.")
    }

    static var exportAudio: String {
        String(localized: "vocello.history.export_audio",
               defaultValue: "Export Audio",
               comment: "Explicit system share/export action for finished audio.")
    }

    static var dismissPlayerDetail: String {
        String(localized: "vocello.player.dismiss_detail",
               defaultValue: "This closes the player without deleting the audio file. Saved takes can be replayed from History.",
               comment: "Player dismissal does not guarantee that the take's History write succeeded.")
    }

    static var longFormSaveFailed: String {
        String(localized: "vocello.long_form.save_failed",
               defaultValue: "The long-form project could not be saved safely. The previous accepted project is unchanged.",
               comment: "Long-form transaction rolled back without changing the prior accepted project.")
    }

    static var longFormRecoveryRequired: String {
        String(localized: "vocello.long_form.recovery_required",
               defaultValue: "Long-form storage needs recovery. Open History and retry before changing this project. Its audio has been retained.",
               comment: "An interrupted or invalid long-form transaction needs reconciliation; retained audio must not be deleted.")
    }

    static var longFormSegmentGenerated: String {
        String(localized: "vocello.long_form.segment_generated",
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

    static func status(_ status: Status) -> String {
        switch status {
        case .ready:
            return String(
                localized: "vocello.status.ready",
                defaultValue: "Ready",
                comment: "Terminal status for an installed on-device voice model."
            )
        case .generationFailed:
            return String(
                localized: "vocello.status.generation_failed",
                defaultValue: "Generation failed",
                comment: "Title shown when speech generation cannot complete."
            )
        case .checkingDownloadedFiles:
            return String(
                localized: "vocello.status.checking_downloaded_files",
                defaultValue: "Checking downloaded files",
                comment: "Indeterminate model-install phase after all transfer bytes arrive."
            )
        case .makingModelAvailableOffline:
            return String(
                localized: "vocello.status.making_model_available_offline",
                defaultValue: "Making the model available offline",
                comment: "Indeterminate model-install publication phase."
            )
        }
    }

    static func enrollmentTranscriptionStatus(
        _ status: EnrollmentTranscriptionStatus
    ) -> String {
        switch status {
        case .awaitingAudio:
            return String(
                localized: "vocello.enrollment.transcription.awaiting_audio",
                defaultValue: "Choose or record an audio clip to begin on-device transcription.",
                comment: "Enrollment status before a reference audio clip has been selected."
            )
        case .sidecarReady:
            return String(
                localized: "vocello.enrollment.transcription.sidecar_ready",
                defaultValue: "Transcript loaded from the matching text file.",
                comment: "Enrollment status when an imported audio file had a neighboring transcript sidecar."
            )
        case .transcribing:
            return String(
                localized: "vocello.enrollment.transcription.in_progress",
                defaultValue: "Transcribing on this device…",
                comment: "Enrollment status while local speech recognition processes the reference clip."
            )
        case .automaticReady:
            return String(
                localized: "vocello.enrollment.transcription.automatic_ready",
                defaultValue: "Automatic transcript ready. Review it before saving.",
                comment: "Enrollment status after on-device speech recognition supplied editable text."
            )
        case .manualReady:
            return String(
                localized: "vocello.enrollment.transcription.manual_ready",
                defaultValue: "Your transcript is ready.",
                comment: "Enrollment status after the user edits or enters the transcript."
            )
        case .permissionDenied:
            return String(
                localized: "vocello.enrollment.transcription.permission_denied",
                defaultValue: "Speech recognition is unavailable. Enter a transcript or use audio only.",
                comment: "Enrollment recovery when speech-recognition authorization is unavailable."
            )
        case .unavailable:
            return String(
                localized: "vocello.enrollment.transcription.unavailable",
                defaultValue: "On-device transcription is unavailable. Enter a transcript or use audio only.",
                comment: "Enrollment recovery when on-device speech recognition cannot run."
            )
        case .empty:
            return String(
                localized: "vocello.enrollment.transcription.empty",
                defaultValue: "No automatic transcript was found. Enter one or use audio only.",
                comment: "Enrollment recovery when recognition completes without usable text."
            )
        case .cancelled:
            return String(
                localized: "vocello.enrollment.transcription.cancelled",
                defaultValue: "Transcription stopped. Enter a transcript or use audio only.",
                comment: "Enrollment recovery after automatic transcription is cancelled."
            )
        case .audioOnlyConfirmed:
            return String(
                localized: "vocello.enrollment.transcription.audio_only_confirmed",
                defaultValue: "Audio-only enrollment selected. The transcript will remain empty.",
                comment: "Enrollment status after explicit confirmation to save without a transcript."
            )
        }
    }

    static var importReferenceAudioTitle: String {
        String(
            localized: "vocello.enrollment.import_audio",
            defaultValue: "Import audio file",
            comment: "Action that opens Files to choose a voice-cloning reference clip."
        )
    }

    static var importReferenceAudioDetail: String {
        String(
            localized: "vocello.enrollment.import_audio.detail",
            defaultValue: "Choose a WAV, MP3, AIFF, or M4A file from Files.",
            comment: "Supported-format description below the reference-audio import action."
        )
    }

    static var referenceLanguageTitle: String {
        String(
            localized: "vocello.enrollment.reference_language",
            defaultValue: "Reference language",
            comment: "Enrollment field describing the language spoken in the saved reference clip."
        )
    }

    static var referenceLanguageConfirmation: String {
        String(
            localized: "vocello.enrollment.reference_language.confirmation",
            defaultValue: "Confirm the language spoken in this reference.",
            comment: "Enrollment guidance when automatic reference-language detection is inconclusive."
        )
    }

    static var referenceLanguageDetail: String {
        String(
            localized: "vocello.enrollment.reference_language.detail",
            defaultValue: "Used only to describe this saved reference.",
            comment: "Enrollment guidance clarifying that reference language does not select future output language."
        )
    }

    static var referenceLanguagePlaceholder: String {
        String(
            localized: "vocello.enrollment.reference_language.placeholder",
            defaultValue: "Choose a language",
            comment: "Placeholder option for an unconfirmed reference-clip language."
        )
    }

    static var useAudioOnly: String {
        String(
            localized: "vocello.enrollment.use_audio_only",
            defaultValue: "Use audio only",
            comment: "Explicit enrollment action used when no transcript is available."
        )
    }

    static var useAudioOnlyHint: String {
        String(
            localized: "vocello.enrollment.use_audio_only.hint",
            defaultValue: "Save this reference without transcript-backed delivery.",
            comment: "VoiceOver hint for the explicit audio-only enrollment action."
        )
    }

    static func installModel(named modelName: String) -> String {
        let format = String(
            localized: "vocello.error.install_model",
            defaultValue: "Install “%1$@” in Settings to generate audio.",
            comment: "Studio error. The substitution is the display name of a missing voice model."
        )
        return String.localizedStringWithFormat(format, modelName)
    }

    static func longFormPlanningFailed(details: String) -> String {
        let format = String(
            localized: "vocello.error.long_form_planning_failed",
            defaultValue: "Long-form planning failed: %1$@",
            comment: "Studio error. The substitution is a localized, non-sensitive planning error."
        )
        return String.localizedStringWithFormat(format, details)
    }

    static var cloningConsentRequired: String {
        String(
            localized: "vocello.error.cloning_consent_required",
            defaultValue: "Enable voice-cloning consent in Settings → Privacy before generating.",
            comment: "Studio error shown when Voice Cloning consent has not been acknowledged."
        )
    }

    static var referenceAudioRequired: String {
        String(
            localized: "vocello.error.reference_audio_required",
            defaultValue: "Select a reference audio file before generating.",
            comment: "Voice Cloning error shown when no reference clip is selected."
        )
    }

    static func cancellationCouldNotFinish(details: String) -> String {
        let format = String(
            localized: "vocello.error.cancellation_not_finished",
            defaultValue: "Cancellation could not finish safely: %1$@",
            comment: "Studio error. The substitution explains why the engine cancellation barrier failed."
        )
        return String.localizedStringWithFormat(format, details)
    }

    /// Representative plural contract. Product surfaces can adopt the same
    /// pattern without concatenating independently localized fragments.
    static func readyModelCount(_ count: Int) -> String {
        let format = String(
            localized: "vocello.models.ready_count",
            defaultValue: "%lld models ready",
            comment: "Summary count of installed on-device voice models."
        )
        return String.localizedStringWithFormat(format, count)
    }
}
