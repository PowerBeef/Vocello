import Foundation

/// Typed presentation vocabulary for user-visible status and dynamic error text.
///
/// English remains the only shipping localization for now. New presentation
/// strings enter through this vocabulary and `Localizable.xcstrings`, which
/// gives translators stable semantic keys, context, substitutions, and plural
/// rules before any broad translation work begins.
enum VocelloPresentationText {
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
