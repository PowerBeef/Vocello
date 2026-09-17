import CoreGraphics

/// Window and shell geometry in one place: the desktop counterpart of the
/// iOS safe-area and dock constants.
enum MacShellMetrics {
    /// Wide enough that the setup chips stay on one row for the common
    /// four-chip case, which is the only thing this number has ever encoded:
    /// sidebar, two gutters, and four chips at their floor. The old 720 forced
    /// the row to wrap and truncated the reference chip -- the one chip
    /// carrying a name the user chose.
    ///
    /// 880 was that arithmetic when a chip reserved 132 pt and the row stretched
    /// to fill whatever it was given. Chips are sized to their content now and
    /// floored at 116, so four of them plus their gaps come to 488 rather than
    /// 552 and the same rule lands 100 pt lower.
    static let windowMinSize = CGSize(width: 780, height: 560)
    /// Opens with room for all five chips on one row, which is the case an
    /// emotion-bank voice produces, and with a working amount of canvas above
    /// them; it shrinks to the minimum from here. Wider than the chip row
    /// strictly needs, which is the point -- the minimum is the constraint, the
    /// default is a judgement about a comfortable size to start at.
    static let windowDefaultSize = CGSize(width: 1040, height: 680)
    static let diagnosticsMinSize = CGSize(width: 520, height: 420)
    static let settingsWindowMinSize = CGSize(width: 600, height: 520)
    /// 680 tall, not 720. A window's default size is its *content* size, and
    /// macOS adds a title bar above it while the menu bar takes from the screen
    /// below — so asking for 720 pt of content on a 720 pt screen cannot be
    /// satisfied for any non-zero chrome, and the system silently clamps it.
    /// The size was therefore never the size anyone saw.
    static let settingsWindowDefaultSize = CGSize(width: 680, height: 680)

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
    /// The sidebar row is the shared row step — the same step a Studio chip
    /// sits on, so the two halves of the window are one control size.
    static let sidebarRowMinHeight: CGFloat = MacControl.row.height
    /// Width of the glyph column. It is a column, not a tile: the glyphs are
    /// bare and this only aligns them, because SF Symbols have different
    /// intrinsic widths and a ragged icon edge down a sidebar is worse than
    /// any of them being a point off centre.
    static let sidebarGlyphColumn: CGFloat = MacControl.icon.height
}
