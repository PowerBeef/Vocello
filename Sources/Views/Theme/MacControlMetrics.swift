import SwiftUI

/// The control sizes of the macOS app, each carrying the glyph size and the
/// shape that belong to it.
///
/// Before this existed the app used fourteen distinct interactive heights
/// between 22 and 56 — six of them exactly once — and chose glyph sizes
/// independently of the control holding them, so an 18 pt symbol sat in a 46 pt
/// chip, a 56 pt button and a 56 pt square alike. A glyph is about a third of
/// its control; that ratio is what makes a row of different-sized controls read
/// as one family.
///
/// The ladder's top two steps were the widest heights that mess contained, kept
/// because they were already there. On a desktop they made the Studio read at a
/// different scale from the sidebar beside it: a 46 pt chip and a 56 pt button
/// against a 40 pt row, all carrying the same 13 pt label. `.pill` now sits on
/// the row step and `.primary` one step above it, which is the whole of the
/// prominence the Generate button needs when it is already full-width, tinted
/// and the only filled control on the screen.
///
/// `.pill` and `.row` share 40 pt. They stay separate cases because they are
/// separate roles with separate glyphs and shapes — the same way four type
/// roles share 13 pt and are told apart by weight and tracking.
enum MacControl: Equatable, CaseIterable {
    /// The Generate button, the error and generating bars, the Batch square.
    case primary
    /// A Studio setup chip.
    case pill
    /// A sidebar row, a list row's floor.
    case row
    /// A text field, a secondary button, a play/pause circle.
    case field
    /// An icon button, a list tile, a filter chip.
    case icon
    /// A status badge, a variant segment, a micro pill.
    case badge

    var height: CGFloat {
        switch self {
        case .primary: 48
        case .pill: 40
        case .row: 40
        case .field: 36
        case .icon: 28
        case .badge: 24
        }
    }

    /// The SF Symbol point size that belongs inside this control.
    var glyph: CGFloat {
        switch self {
        case .primary: 16
        case .pill: 14
        case .row, .field: 15
        case .icon: 13
        case .badge: 11
        }
    }

    /// Horizontal padding for a control that sizes to its label.
    var horizontalPadding: CGFloat {
        switch self {
        case .primary: 20
        case .pill: 12
        case .row: 8
        case .field: 12
        case .icon: 8
        case .badge: 9
        }
    }
}

extension View {
    /// Sizes a control to one of the six steps, keeping its own width.
    func macControlHeight(_ control: MacControl) -> some View {
        frame(height: control.height)
    }

    /// Sizes a square control — an icon button, a tile — to one of the steps.
    func macControlSquare(_ control: MacControl) -> some View {
        frame(width: control.height, height: control.height)
    }
}
