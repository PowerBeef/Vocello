import QwenVoiceCore
import SwiftUI

/// The six destinations of the macOS shell. The rawValue is a stored identity
/// (the last selection persists under `MacAppModel.lastSidebarItemKey`); the
/// visible label comes from the catalog and the accessibility identifier from
/// the case name, so `sidebar_customVoice` and `screen_customVoice` never move.
enum SidebarItem: String, CaseIterable, Identifiable {
    case customVoice = "Built-in Voice"
    case voiceDesign = "Voice Design"
    case voiceCloning = "Voice Cloning"
    case history = "History"
    case voices = "Saved Voices"
    /// The Models tab merged with the Cmd+, Preferences window into one
    /// Settings surface (May 2026); the case name stays for code clarity.
    case settings = "Settings"

    var id: String { rawValue }

    /// Catalog-owned sidebar label; the rawValue stays the stored identity.
    var title: String {
        switch self {
        case .customVoice: MacInterfaceText.menuBuiltInVoice
        case .voiceDesign: MacInterfaceText.menuVoiceDesign
        case .voiceCloning: MacInterfaceText.menuVoiceCloning
        case .history: MacInterfaceText.menuHistory
        case .voices: MacInterfaceText.menuSavedVoices
        case .settings: MacInterfaceText.settingsTitle
        }
    }

    var accessibilityID: String { "sidebar_\(String(describing: self))" }

    var screenAccessibilityID: String { "screen_\(String(describing: self))" }

    var generationMode: GenerationMode? {
        switch self {
        case .customVoice: .custom
        case .voiceDesign: .design
        case .voiceCloning: .clone
        case .history, .voices, .settings: nil
        }
    }

    /// Identifier prefix the mode's screen stamps on its controls
    /// (`customVoice_readiness`), so window chrome can address them too.
    var accessibilityPrefix: String? {
        switch self {
        case .customVoice: "customVoice"
        case .voiceDesign: "voiceDesign"
        case .voiceCloning: "voiceCloning"
        case .history, .voices, .settings: nil
        }
    }

    var requiredModel: TTSModel? {
        generationMode.flatMap(TTSModel.model(for:))
    }

    /// Generation modes use the canonical per-mode glyphs so the sidebar and
    /// the Settings model rows stay matched; the other destinations use the
    /// iOS dock glyphs.
    var iconName: String {
        switch self {
        case .customVoice: MacTheme.modeGlyph(for: .custom)
        case .voiceDesign: MacTheme.modeGlyph(for: .design)
        case .voiceCloning: MacTheme.modeGlyph(for: .clone)
        case .history: "clock.arrow.circlepath"
        case .voices: "person.2.fill"
        case .settings: "gearshape"
        }
    }

    enum Section: String, CaseIterable {
        case generate = "Generate"
        case library = "Library"
        case settings = "Settings"

        var accessibilityID: String {
            "sidebarSection_\(String(describing: self))"
        }

        /// Catalog-owned section header; the rawValue stays the internal identity.
        var title: String {
            switch self {
            case .generate: MacInterfaceText.shellSectionStudio
            case .library: MacInterfaceText.sidebarSectionLibrary
            case .settings: MacInterfaceText.settingsTitle
            }
        }

        var items: [SidebarItem] {
            switch self {
            case .generate: [.customVoice, .voiceDesign, .voiceCloning]
            case .library: [.history, .voices]
            case .settings: [.settings]
            }
        }
    }

    static var generationItems: [SidebarItem] {
        [.customVoice, .voiceDesign, .voiceCloning]
    }

    @MainActor
    func isAvailable(using modelManager: ModelManagerViewModel) -> Bool {
        guard let generationMode else { return true }
        return modelManager.hasInstalledVariant(for: generationMode)
    }

    @MainActor static func defaultInitialSelection() -> SidebarItem {
        .customVoice
    }
}
