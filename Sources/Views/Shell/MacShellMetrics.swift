import CoreGraphics

/// Window and shell geometry in one place: the desktop counterpart of the
/// iOS safe-area and dock constants.
enum MacShellMetrics {
    static let windowMinSize = CGSize(width: 720, height: 560)
    static let windowDefaultSize = CGSize(width: 880, height: 640)
    static let diagnosticsMinSize = CGSize(width: 520, height: 420)
    static let settingsWindowMinSize = CGSize(width: 600, height: 520)
    static let settingsWindowDefaultSize = CGSize(width: 680, height: 720)

    static let sidebarMinWidth: CGFloat = 220
    static let sidebarIdealWidth: CGFloat = 250
    static let sidebarMaxWidth: CGFloat = 300
    /// Below this window width the composer chip rows wrap (B6 onwards).
    static let compactBreakpoint: CGFloat = 860
    /// Content column of the History and Saved Voices lists; wider than the
    /// Studio column (`MacStudioMetrics.contentMaxWidth`) so rows keep their
    /// legacy width and do not tear apart on wide displays.
    static let libraryContentMaxWidth: CGFloat = 960

    static let sidebarInset: CGFloat = 12
    static let sidebarRowMinHeight: CGFloat = 40
    static let sidebarRowRadius: CGFloat = 12
    static let sidebarGlyphTile: CGFloat = 28
    static let sidebarGlyphTileRadius: CGFloat = 8
}
