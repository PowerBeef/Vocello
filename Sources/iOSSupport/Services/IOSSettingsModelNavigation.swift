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

    /// What Voice Models can do with the waiting request once it reads the model's state.
    enum ConfirmationReadiness: Equatable {
        /// The model's status is still being read: keep the request.
        case pending
        /// The row offers Install or Update: present the confirmation.
        case confirm
        /// The model is installed, transferring or offers Repair or Retry: show its row.
        case showRow
    }

    /// Hands the waiting request to Voice Models once it can act on it. A request made
    /// before the model's status arrived stays waiting, so the confirmation appears when
    /// the status does instead of the request being dropped (BKL-60); a request for a
    /// model whose row needs no confirmation is consumed without one.
    func takeDownloadAwaitingConfirmation(
        readiness: (ModelDescriptor) -> ConfirmationReadiness
    ) -> ModelDescriptor? {
        guard let model = downloadAwaitingConfirmation else { return nil }
        switch readiness(model) {
        case .pending:
            return nil
        case .confirm:
            downloadAwaitingConfirmation = nil
            return model
        case .showRow:
            downloadAwaitingConfirmation = nil
            return nil
        }
    }

    /// Leaving Voice Models drops a request it is still holding for the model's status.
    func dropDownloadAwaitingConfirmation() {
        downloadAwaitingConfirmation = nil
    }

    /// Leaving the Settings tab resets its stack and drops a request Voice Models never showed.
    func leaveSettings() {
        path = []
        downloadAwaitingConfirmation = nil
    }
}
