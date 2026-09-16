import SwiftUI

/// Shape factories over the shared radii (iOS `ThemeShape` forwards here).
enum VocelloShape {
    /// A shape nested inside another by `inset` points, keeping the two
    /// corners concentric — a segmented control's selected pill inside its
    /// track, where equal radii would read as two fighting curves.
    static func chip(inset: CGFloat) -> RoundedRectangle {
        RoundedRectangle(cornerRadius: max(VocelloTheme.Radius.chip - inset, 2), style: .continuous)
    }

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
