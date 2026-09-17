import SwiftUI

/// The macOS half of the shared type vocabulary: five sizes, thirteen roles.
///
/// | pt | role |
/// |----|------|
/// | 17 | script, sheetTitle |
/// | 15 | screenTitle |
/// | 13 | rowTitle, body, buttonLabel, chipLabel |
/// | 12 | rowMeta |
/// | 11 | caption, captionEmphasis, badge, counter, eyebrow |
///
/// The script used to have a 22 pt step to itself, inherited from the largest
/// size the app happened to use before this table existed rather than chosen.
/// Beside a 13 pt sidebar it read as a different application, so it joins
/// `sheetTitle` at 17: four points above body, still the largest thing on the
/// screen, no longer shouting. Roles sharing a size is how this table already
/// works -- thirteen roles have never needed thirteen sizes -- and what
/// separates two roles at one size is weight, tracking and their anchor.
///
/// Sizes are stated in points rather than taken from SwiftUI's semantic styles
/// because the semantic names lie on macOS: `.caption`, `.caption2` and
/// `.footnote` all resolve to 10 pt, so source that reads as a three-step
/// hierarchy renders as one. The anchors are still declared per role, for the
/// iOS table that will join this one.
enum MacType {
    static func style(_ role: VocelloTypeRole) -> VocelloTextStyle {
        switch role {
        case .script:
            // The hero, and the only role whose size is set by how the text
            // reads rather than by what it labels. The tracking is the phone's
            // -0.01em carried across: -0.22 at 22 pt, -0.17 here.
            VocelloTextStyle(size: 17, weight: .medium, tracking: -0.17, relativeTo: .title)
        case .sheetTitle:
            VocelloTextStyle(size: 17, weight: .semibold, relativeTo: .title2)
        case .screenTitle:
            VocelloTextStyle(size: 15, weight: .semibold, relativeTo: .title3)
        case .rowTitle:
            // 13 pt is the macOS system body size: every row on every screen.
            VocelloTextStyle(size: 13, weight: .semibold, relativeTo: .body)
        case .body:
            VocelloTextStyle(size: 13, relativeTo: .body)
        case .buttonLabel:
            VocelloTextStyle(size: 13, weight: .semibold, tracking: -0.17, relativeTo: .body)
        case .chipLabel:
            VocelloTextStyle(size: 13, weight: .semibold, relativeTo: .body)
        case .rowMeta:
            VocelloTextStyle(size: 12, relativeTo: .callout)
        case .caption:
            VocelloTextStyle(size: 11, relativeTo: .subheadline)
        case .captionEmphasis:
            VocelloTextStyle(size: 11, weight: .medium, relativeTo: .subheadline)
        case .badge:
            VocelloTextStyle(size: 11, weight: .semibold, relativeTo: .subheadline)
        case .counter:
            VocelloTextStyle(size: 11, weight: .medium, monospacedDigit: true, relativeTo: .subheadline)
        case .eyebrow:
            // The one token the app already had right, kept exactly: 11 pt
            // semibold at 0.88 tracking, uppercased by the caller.
            VocelloTextStyle(size: 11, weight: .semibold, tracking: 0.88, relativeTo: .subheadline)
        }
    }

    /// The resolved font, without tracking (which the modifier applies only
    /// when the role asks for it).
    static func font(_ role: VocelloTypeRole) -> Font {
        let style = style(role)
        let base = Font.system(size: style.size, weight: style.weight, design: style.design)
        return style.monospacedDigit ? base.monospacedDigit() : base
    }
}

extension View {
    /// Applies a role's font, letter spacing and digit treatment in one place.
    func macType(_ role: VocelloTypeRole) -> some View {
        modifier(MacTypeModifier(role: role))
    }
}

private struct MacTypeModifier: ViewModifier {
    let role: VocelloTypeRole

    func body(content: Content) -> some View {
        let tracking = MacType.style(role).tracking
        // `.tracking(0)` is not the same as no tracking: it replaces the face's
        // own tracking table rather than adding to it. Roles that want the
        // system's metrics get no modifier at all.
        if tracking == 0 {
            content.font(MacType.font(role))
        } else {
            content.font(MacType.font(role)).tracking(tracking)
        }
    }
}
