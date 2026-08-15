import SwiftUI
import QwenVoiceCore

enum IOSAppTab: String, CaseIterable, Identifiable {
    case studio
    case voices
    case history
    case settings

    var id: String { rawValue }
}

enum IOSGenerationSection: String, CaseIterable, Identifiable {
    case custom
    case design
    case clone

    var id: String { rawValue }

    var mode: GenerationMode {
        switch self {
        case .custom: return .custom
        case .design: return .design
        case .clone: return .clone
        }
    }

    var title: String {
        mode.displayName
    }

    var compactTitle: String {
        // Mode segmented uses the mode name (per design_references/Vocello iOS/
        // chrome.jsx ModeSegmented). The longer action-oriented labels live on
        // the setup-chip pattern; the segmented control itself stays terse.
        switch self {
        case .custom:
            return "Built-in"
        case .design:
            return "Design"
        case .clone:
            return "Clone"
        }
    }
}
