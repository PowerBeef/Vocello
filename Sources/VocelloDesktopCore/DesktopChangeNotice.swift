import Foundation

/// What the CLI tells a running Vocello app after it changed shared state
/// (RF-28): a distributed notification per store, which the app observes and
/// answers by reloading that store. Names only; no payload, no paths.
public enum DesktopChangeNotice: String, CaseIterable, Sendable {
    case history = "com.qwenvoice.shared.historyDidChange"
    case savedVoices = "com.qwenvoice.shared.savedVoicesDidChange"
    case models = "com.qwenvoice.shared.modelsDidChange"
    case settings = "com.qwenvoice.shared.settingsDidChange"

    public var name: Notification.Name { Notification.Name(rawValue) }

    public func post() {
        DistributedNotificationCenter.default().postNotificationName(
            name, object: nil, userInfo: nil, deliverImmediately: true
        )
    }
}
