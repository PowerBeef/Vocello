import Foundation
import QwenVoiceCore

/// iOS adapter of `IOSLongFormPlatformHooks`: every member calls exactly what
/// `IOSLongFormProject.swift` called inline before the seam, so the iOS
/// long-form behavior is unchanged by construction. The macOS twin is
/// `MacStudioLongFormPlatformHooks`.
@MainActor
final class IOSStudioLongFormPlatformHooks: IOSLongFormPlatformHooks {
    init() {}

    var presentation: VocelloPresentationText { IOSAppLanguage.shared.presentation }

    func requestVariation() -> Qwen3SamplingVariation? {
        IOSGenerationVariationPreference.requestValue()
    }

    func waveformSeed(for text: String) -> Int {
        IOSStableVisualHash.int(text)
    }

    // Byte-identical to the copy the runner carried inline before the seam.
    func segmentTitle(index: Int, total: Int) -> String {
        "Segment \(index + 1) of \(total)"
    }

    var longFormModeLabel: String { "Long-form" }

    var longFormProjectTitle: String { "Long-form project" }

    func segmentTelemetryFinalized(generationID: UUID, publishedAudioURL: URL?) {
        IOSPullableDiagnosticsMirror.syncGenerationTelemetryIfEnabled(
            generationID: generationID,
            publishedAudioURL: publishedAudioURL
        )
    }

    func projectAccepted(_ saved: Generation, joinedAudioPath: String) {
        NotificationCenter.default.post(name: .generationSaved, object: nil)
        IOSSavedOutputsDestination.exportIfConfigured(internalAudioPath: joinedAudioPath, generationMode: saved.mode)
    }

    func notifySuccess() {
        IOSHaptics.success()
    }

    func notifyWarning() {
        IOSHaptics.warning()
    }
}
