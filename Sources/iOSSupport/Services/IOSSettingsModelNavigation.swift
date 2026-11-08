import Observation
import QwenVoiceCore

/// Session-only navigation for the explicit Studio installation action.
/// Download ownership stays with the existing app-lifetime installer, not a destination task.
@MainActor
@Observable
final class IOSSettingsModelNavigation {
    enum Destination: Hashable {
        case modelsAndFiles
        case voiceModels
    }

    var path: [Destination] = []

    /// A Studio request that Voice Models presents as a download confirmation (RF-41,
    /// Guideline 4.2.3(ii)): nothing downloads until the person confirms it there.
    private(set) var downloadAwaitingConfirmation: ModelDescriptor?

    func requestInstallation(of model: ModelDescriptor, selectSettings: () -> Void) {
        path = [.modelsAndFiles, .voiceModels]
        selectSettings()
        downloadAwaitingConfirmation = model
    }

    /// Hands the waiting request to Voice Models once, so returning there never replays it.
    func takeDownloadAwaitingConfirmation() -> ModelDescriptor? {
        guard let model = downloadAwaitingConfirmation else { return nil }
        downloadAwaitingConfirmation = nil
        return model
    }

    /// Leaving the Settings tab resets its stack and drops a request Voice Models never showed.
    func leaveSettings() {
        path = []
        downloadAwaitingConfirmation = nil
    }
}
