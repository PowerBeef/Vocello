import Foundation

/// The stores the Mac app and the `vocello` CLI share, and the distributed
/// notification a process posts after changing one (RF-28): the CLI posts them
/// (`DesktopChangeNotice`), the app observes them (`MacSharedStoreChangeObserver`)
/// and reloads that store. Names only: no payload, no paths.
enum SharedStoreChange: String, CaseIterable, Sendable {
    case history = "com.qwenvoice.shared.historyDidChange"
    case savedVoices = "com.qwenvoice.shared.savedVoicesDidChange"
    case models = "com.qwenvoice.shared.modelsDidChange"
    case settings = "com.qwenvoice.shared.settingsDidChange"

    var name: Notification.Name { Notification.Name(rawValue) }
}
