import Foundation

/// The Voice Cloning readiness line on the desktop: the same decision order as
/// the shared `VoiceCloningReadiness` (whose copy is English only), read from
/// the catalog through `MacInterfaceText` so French follows the interface
/// language. It returns the shared descriptor. One deliberate difference: the
/// script check trims whitespace before deciding "Add a script".
enum MacVoiceCloningReadiness {
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
                title: MacInterfaceText.readinessEngineStarting,
                detail: MacInterfaceText.readinessEngineStartingDetail,
                trailingText: nil
            )
        }

        if !isModelAvailable {
            return VoiceCloningReadinessDescriptor(
                noteIsReady: false,
                title: MacInterfaceText.readinessInstallActiveModel,
                detail: MacInterfaceText.readinessInstallActiveModelDetail(modelDisplayName),
                trailingText: nil
            )
        }

        // The Generate button gates on the one-time cloning consent; the
        // note must never disagree with it (found on the bank's first real
        // use, 2026-08-04).
        if !cloneConsentAcknowledged {
            return VoiceCloningReadinessDescriptor(
                noteIsReady: false,
                title: MacInterfaceText.cloningConsentTitle,
                detail: MacInterfaceText.cloningConsentDetail,
                trailingText: nil
            )
        }

        guard referenceAudioPath != nil else {
            return VoiceCloningReadinessDescriptor(
                noteIsReady: false,
                title: MacInterfaceText.cloningAddReference,
                detail: MacInterfaceText.cloningAddReferenceDetail,
                trailingText: nil
            )
        }

        if case .waitingForHydration = contextStatus {
            return VoiceCloningReadinessDescriptor(
                noteIsReady: false,
                title: MacInterfaceText.cloningPreparingSavedVoice,
                detail: MacInterfaceText.cloningPreparingSavedVoiceDetail,
                trailingText: nil
            )
        }

        if case .preparing = contextStatus {
            return VoiceCloningReadinessDescriptor(
                noteIsReady: false,
                title: MacInterfaceText.cloningPreparingContext,
                detail: MacInterfaceText.cloningPreparingContextDetail,
                trailingText: nil
            )
        }

        if text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return VoiceCloningReadinessDescriptor(
                noteIsReady: false,
                title: MacInterfaceText.readinessAddScript,
                detail: MacInterfaceText.cloningAddScriptDetail,
                trailingText: nil
            )
        }

        // Without a transcript the engine falls back to speaker-embedding-only
        // conditioning (identity without pacing or emotion); the fallback is
        // visible by requirement of the 2026-08-04 delivery-control audit (F8).
        // Generation still proceeds, so this stays a ready state.
        if !hasReferenceTranscript {
            return VoiceCloningReadinessDescriptor(
                noteIsReady: true,
                title: MacInterfaceText.cloningReadyIdentityOnly,
                detail: MacInterfaceText.cloningReadyIdentityOnlyDetail,
                trailingText: MacInterfaceText.statusReady
            )
        }

        if case .fallback(let message) = contextStatus {
            return VoiceCloningReadinessDescriptor(
                noteIsReady: true,
                title: MacInterfaceText.cloningReadySlowerFirstRun,
                detail: message,
                trailingText: MacInterfaceText.statusReady
            )
        }

        return VoiceCloningReadinessDescriptor(
            noteIsReady: true,
            title: MacInterfaceText.readinessReadyToGenerate,
            detail: MacInterfaceText.readinessReadyToGenerateAndSave,
            trailingText: MacInterfaceText.statusReady
        )
    }
}
