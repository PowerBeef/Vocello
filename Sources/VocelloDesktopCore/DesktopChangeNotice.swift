import Foundation

/// What the CLI tells a running Vocello app after it changed a shared store
/// (RF-28): one distributed notification per store (`SharedStoreChange`, which
/// the app observes), names only.
public enum DesktopChangeNotice: CaseIterable, Sendable {
    case history, savedVoices, models, settings

    var change: SharedStoreChange {
        switch self {
        case .history: .history
        case .savedVoices: .savedVoices
        case .models: .models
        case .settings: .settings
        }
    }

    public var rawValue: String { change.rawValue }
    public var name: Notification.Name { change.name }

    public func post() {
        DistributedNotificationCenter.default().postNotificationName(
            name, object: nil, userInfo: nil, deliverImmediately: true
        )
    }
}
