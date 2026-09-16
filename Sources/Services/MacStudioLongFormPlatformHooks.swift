import Foundation
import QwenVoiceCore

/// macOS adapter of `IOSLongFormPlatformHooks` (the long-form twin of
/// `MacStudioSingleTakeGenerationHooks`): the Settings variation preference,
/// the desktop waveform hash, the two-layer telemetry merge instead of the
/// devicectl diagnostics mirror, the History library event instead of the
/// iOS notification and Files export, the interface language selected in
/// Settings, and no haptics.
@MainActor
final class MacStudioLongFormPlatformHooks: IOSLongFormPlatformHooks {
    init() {}

    var presentation: VocelloPresentationText {
        VocelloPresentationText(localization: MacInterfaceLanguage.current)
    }

    func requestVariation() -> Qwen3SamplingVariation? {
        GenerationVariationPreference.requestValue()
    }

    func waveformSeed(for text: String) -> Int {
        VocelloStableVisualHash.int(text)
    }

    func segmentTitle(index: Int, total: Int) -> String {
        MacInterfaceText.batchSegmentTitle(String(index + 1), String(total))
    }

    var longFormModeLabel: String { MacInterfaceText.batchLongFormMode }

    var longFormProjectTitle: String { MacInterfaceText.batchLongFormProject }

    func segmentTelemetryFinalized(generationID: UUID, publishedAudioURL: URL?) {
        GenerationTelemetryMerger.scheduleMerge(generationID: generationID)
    }

    func projectAccepted(_ saved: Generation, joinedAudioPath: String) {
        GenerationLibraryEvents.shared.announceGenerationAppended(saved)
    }

    func notifySuccess() {}

    func notifyWarning() {}
}
