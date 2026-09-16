import SwiftUI

/// Shape factories over the shared radii (iOS `ThemeShape` forwards here).
enum VocelloShape {
    static func row() -> RoundedRectangle {
        RoundedRectangle(cornerRadius: VocelloTheme.Radius.row, style: .continuous)
    }

    static func card() -> RoundedRectangle {
        RoundedRectangle(cornerRadius: VocelloTheme.Radius.card, style: .continuous)
    }

    static func input() -> RoundedRectangle {
        RoundedRectangle(cornerRadius: VocelloTheme.Radius.input, style: .continuous)
    }

    static func stage() -> RoundedRectangle {
        RoundedRectangle(cornerRadius: VocelloTheme.Radius.stage, style: .continuous)
    }

    static func chip() -> RoundedRectangle {
        RoundedRectangle(cornerRadius: VocelloTheme.Radius.chip, style: .continuous)
    }

    static func pill() -> Capsule {
        Capsule(style: .continuous)
    }
}
