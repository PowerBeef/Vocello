import SwiftUI

/// A text style as a specification rather than a `Font`.
///
/// The two platforms cannot share a `Font` constant: macOS renders `.body` at
/// 13 pt where iOS renders it at 17, and only iOS scales with Dynamic Type, so
/// "15 pt semibold" is a static value on the desktop and a `@ScaledMetric` in a
/// view on the phone. What they can share is the vocabulary — the set of roles
/// and the rule that a role has exactly one style — with each platform
/// supplying its own table and its own applicator. That is the pattern
/// `VocelloSectionHeading(titleFontSize:)`, `VocelloStatusBadge`'s padding and
/// `VocelloPrimaryCTAButton.Size` already use for metrics; type joins them.
struct VocelloTextStyle: Equatable {
    let size: CGFloat
    let weight: Font.Weight
    let design: Font.Design
    /// Letter spacing in points, part of the role rather than a decision taken
    /// at each call site: the composer's −0.22 and the eyebrow's 0.88 belong to
    /// those styles as much as their size does. Zero means *no tracking
    /// modifier at all* — applying `.tracking(0)` overrides the face's own
    /// tracking table instead of adding to it, which is a visible change.
    let tracking: CGFloat
    let monospacedDigit: Bool
    /// The text style whose Dynamic Type curve this role grows on. Required,
    /// with no default, on purpose: an omitted anchor is how the iOS History
    /// row title came to grow on `.body`'s curve while every other row title
    /// grows on `.subheadline`'s, so the hierarchy inverts at larger text
    /// sizes. macOS ignores the value; it still has to be stated.
    let relativeTo: Font.TextStyle

    init(
        size: CGFloat,
        weight: Font.Weight = .regular,
        design: Font.Design = .default,
        tracking: CGFloat = 0,
        monospacedDigit: Bool = false,
        relativeTo: Font.TextStyle
    ) {
        self.size = size
        self.weight = weight
        self.design = design
        self.tracking = tracking
        self.monospacedDigit = monospacedDigit
        self.relativeTo = relativeTo
    }
}

/// Every role the apps render text in.
///
/// One role is one style. Where two roles must read differently they differ by
/// weight, colour or case — never by inventing a size between the steps, which
/// is how the macOS app arrived at 38 styles for these 13 roles, with 10 pt
/// alone carrying thirteen of them.
enum VocelloTypeRole: Equatable, CaseIterable {
    /// The script the user writes. The largest text in either app.
    case script
    /// A modal's title.
    case sheetTitle
    /// A screen's or a card's title: the brand wordmark, an empty state.
    case screenTitle
    /// The primary line of any row, on every screen.
    case rowTitle
    /// Prose: popover bodies, instructions, a paragraph of explanation.
    case body
    /// A button's label.
    case buttonLabel
    /// A chip or pill's value.
    case chipLabel
    /// The secondary line of a row.
    case rowMeta
    /// Supporting text: advisories, hints, field captions.
    case caption
    /// Supporting text that carries state and needs a little more weight.
    case captionEmphasis
    /// A status badge's label.
    case badge
    /// Numbers that must not jitter as they change.
    case counter
    /// An uppercase section header.
    case eyebrow
}
