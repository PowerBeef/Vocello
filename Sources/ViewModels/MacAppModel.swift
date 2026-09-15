import Foundation
import Observation
import QwenVoiceCore

/// Shell state of the macOS window, the desktop twin of the iOS `AppModel`:
/// the selected destination (persisted across launches), the pending Settings
/// highlight after a disabled mode was clicked, and the window-toolbar state
/// the History and Saved Voices screens read, and the per-mode
/// `StudioGenerationCoordinator`s of the Studio screens (the iOS `AppModel`
/// owns the same three). Generation drafts stay with `ContentView`.
@MainActor
@Observable
final class MacAppModel {
    static let lastSidebarItemKey = "QwenVoice.LastSelectedSidebarItem"
    static let lastVoiceCloningSavedVoiceIDKey = "QwenVoice.LastVoiceCloningSavedVoiceID"

    var selectedItem: SidebarItem? {
        didSet {
            guard let selectedItem, selectedItem != oldValue else { return }
            defaults.set(selectedItem.rawValue, forKey: Self.lastSidebarItemKey)
        }
    }

    /// When the user clicks a disabled generation destination the shell
    /// redirects to Settings and asks the Models page to flash that mode's
    /// row. Keyed by mode because the row is mode-keyed and the missing
    /// variant might not be the active one.
    var pendingHighlightedMode: GenerationMode?

    var historySearchText = ""
    var historySortOrder: HistorySortOrder = .newest
    var historyClearRequest: HistoryClearRequest?
    var voicesEnrollRequestID: UUID?

    /// Built-in Voice generation lifecycle (attempt-scoped terminal state);
    /// Design and Cloning follow with their ports.
    let customCoordinator = StudioGenerationCoordinator(mode: .custom)

    @ObservationIgnored private let defaults: UserDefaults

    init(defaults: UserDefaults = AppDefaults.store) {
        self.defaults = defaults
        selectedItem = Self.restoredSelection(from: defaults)
    }

    static func restoredSelection(from defaults: UserDefaults) -> SidebarItem {
        defaults.string(forKey: lastSidebarItemKey).flatMap(SidebarItem.init(rawValue:))
            ?? SidebarItem.defaultInitialSelection()
    }

    /// The last Voice Cloning saved voice, restored by the cloning draft on
    /// launch and rewritten whenever the picker changes.
    var restoredVoiceCloningSavedVoiceID: String? {
        let stored = defaults.string(forKey: Self.lastVoiceCloningSavedVoiceIDKey)
        return stored?.isEmpty == false ? stored : nil
    }

    func persistVoiceCloningSavedVoiceID(_ id: String?) {
        defaults.set(id ?? "", forKey: Self.lastVoiceCloningSavedVoiceIDKey)
    }
}
