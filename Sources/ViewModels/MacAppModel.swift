import Foundation
import Observation
import QwenVoiceCore

/// Shell state of the macOS window, the desktop twin of the iOS `AppModel`:
/// the selected destination (persisted across launches), the pending Settings
/// highlight after a disabled mode was clicked, the window-toolbar state the
/// History and Saved Voices screens read, the per-mode
/// `StudioGenerationCoordinator`s of the Studio screens (the iOS `AppModel`
/// owns the same three), and the two batch runners the batch sheet drives:
/// the desktop line batch and the shared long-form coordinator. Generation
/// drafts stay with `ContentView`.
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

    /// Per-mode generation lifecycle (attempt-scoped terminal state), one
    /// per Studio mode like the iOS `AppModel`.
    let customCoordinator = StudioGenerationCoordinator(mode: .custom)
    let designCoordinator = StudioGenerationCoordinator(mode: .design)
    let cloneCoordinator = StudioGenerationCoordinator(mode: .clone)
    /// The last designed take that can still become a saved voice; it lives
    /// beside the coordinator so leaving Voice Design keeps both or neither.
    var designSavedVoiceCandidate: VoiceDesignSavedVoiceCandidate?

    /// The line batch of the batch sheet (one ordinary take per line on the
    /// shared executor) and the long-form project coordinator (the iOS one,
    /// with the desktop platform hooks); one of each per app, like iOS, so a
    /// finished project keeps its resume and regenerate affordances while the
    /// sheet is closed.
    let lineBatch = MacLineBatchRunner()
    let longForm = IOSLongFormCoordinator(hooks: MacStudioLongFormPlatformHooks())

    func coordinator(for mode: GenerationMode) -> StudioGenerationCoordinator {
        switch mode {
        case .custom: return customCoordinator
        case .design: return designCoordinator
        case .clone: return cloneCoordinator
        }
    }

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

/// The designed take of the current brief that can become a saved voice; it
/// stays offered only while the brief, delivery and script still match.
struct VoiceDesignSavedVoiceCandidate: Equatable {
    let audioPath: String
    let transcript: String
    let voiceDescription: String
    let emotion: String
    let text: String
    private(set) var savedVoiceName: String?

    var isSaved: Bool { savedVoiceName != nil }

    func matches(draft: VoiceDesignDraft) -> Bool {
        voiceDescription == draft.voiceDescription && emotion == draft.emotion && text == draft.text
    }

    mutating func markSaved(as voiceName: String) {
        savedVoiceName = voiceName
    }
}
