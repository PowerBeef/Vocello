import CoreGraphics

/// Window and shell geometry in one place: the desktop counterpart of the
/// iOS safe-area and dock constants.
enum MacShellMetrics {
    /// Wide enough that the Studio column reaches its cap and the setup chips
    /// stay on one row for the common four-chip case. The old 720 forced the
    /// chip row to wrap and truncated the reference chip -- the one chip
    /// carrying a name the user chose -- at the width the app opened smallest.
    static let windowMinSize = CGSize(width: 880, height: 560)
    /// Opens with room for all five chips on one row, which is the case an
    /// emotion-bank voice produces; it shrinks to the minimum from here.
    static let windowDefaultSize = CGSize(width: 1040, height: 680)
    static let diagnosticsMinSize = CGSize(width: 520, height: 420)
    static let settingsWindowMinSize = CGSize(width: 600, height: 520)
    static let settingsWindowDefaultSize = CGSize(width: 680, height: 720)

    static let sidebarMinWidth: CGFloat = 220
    static let sidebarIdealWidth: CGFloat = 250
    static let sidebarMaxWidth: CGFloat = 300
    /// Horizontal inset of a row in the History and Saved Voices lists, and the
    /// app's content gutter. It is named here because two things must agree on
    /// it: the `listRowInsets` that position the row, and any row that budgets
    /// its own chrome against the width it is given. They drifted once — the
    /// insets moved to `xl` while `MacVoiceRow` went on subtracting `lg` — and
    /// a row then believed it had 8 pt more than it did.
    static let libraryRowHorizontalInset: CGFloat = VocelloTheme.Spacing.xl

    /// Content column of the History and Saved Voices lists; wider than the
    /// Studio column (`MacStudioMetrics.contentMaxWidth`) so rows keep their
    /// legacy width and do not tear apart on wide displays.
    static let libraryContentMaxWidth: CGFloat = 960
    /// Width cap of the empty, error and loading state cards on the History
    /// and Saved Voices screens (`VocelloEmptyStateCard`); the phone lets the
    /// card fill its column.
    static let emptyStateCardMaxWidth: CGFloat = 480

    static let sidebarInset: CGFloat = VocelloTheme.Spacing.md
    /// The sidebar row is the shared row step; its glyph tile the icon step.
    static let sidebarRowMinHeight: CGFloat = MacControl.row.height
    static let sidebarGlyphTile: CGFloat = MacControl.icon.height
}
