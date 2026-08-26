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
