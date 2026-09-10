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

    func requestInstallation(
        of model: ModelDescriptor,
        selectSettings: () -> Void,
        install: (ModelDescriptor) -> Void
    ) {
        path = [.modelsAndFiles, .voiceModels]
        selectSettings()
        install(model)
    }
}
