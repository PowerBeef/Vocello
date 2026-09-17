import SwiftUI
import XCTest

/// The scale is a claim about relationships — five sizes, thirteen roles, no
/// two roles rendered identically — and that claim is otherwise enforced only
/// by reading the table. These tests hold the shape of it, so a role added
/// later has to land on a step rather than inventing one.
@MainActor
final class MacTypeScaleTests: XCTestCase {
    func testTheLadderHasFiveSteps() {
        let sizes = Set(VocelloTypeRole.allCases.map { MacType.style($0).size })
        XCTAssertEqual(
            sizes.sorted(), [11, 12, 13, 15, 17],
            "The macOS ladder is five steps; a new size means a new rung, which is how the app reached 38 styles for 13 roles."
        )
    }

    func testEveryRoleResolves() {
        for role in VocelloTypeRole.allCases {
            let style = MacType.style(role)
            XCTAssertGreaterThan(style.size, 0, "\(role) has no size")
        }
    }

    /// Roles may share a spec — `rowTitle` and `chipLabel` are both 13 pt
    /// semibold — but a role must never be the only thing distinguishing two
    /// pieces of text that then render identically *and* differ in no other
    /// way. What this guards is the opposite failure: the three macOS spellings
    /// (`.caption`, `.caption2`, `.footnote`) that all resolved to 10 pt and
    /// made the source read as a hierarchy the screen never rendered.
    func testRolesThatShareASizeDifferInWeightOrTracking() {
        var byStep: [CGFloat: [VocelloTypeRole]] = [:]
        for role in VocelloTypeRole.allCases {
            byStep[MacType.style(role).size, default: []].append(role)
        }
        for (size, roles) in byStep where roles.count > 1 {
            let fingerprints = roles.map { role -> String in
                let style = MacType.style(role)
                return "\(style.weight)-\(style.tracking)-\(style.monospacedDigit)"
            }
            XCTAssertGreaterThan(
                Set(fingerprints).count, 1,
                "Every role at \(size) pt renders identically: \(roles). Two roles that cannot be told apart are one role."
            )
        }
    }

    /// The anchor is what the iOS table will grow on. It is documentation on
    /// macOS and a constraint on the phone, and an omitted one is how the iOS
    /// History row title came to scale on `.body`'s curve while every other row
    /// title scales on `.subheadline`'s.
    func testEveryRoleDeclaresAnAnchorConsistentWithItsSize() {
        for role in VocelloTypeRole.allCases {
            let style = MacType.style(role)
            let larger = MacType.style(.script).size
            XCTAssertLessThanOrEqual(style.size, larger, "\(role) is larger than the script")
        }
        XCTAssertEqual(MacType.style(.script).relativeTo, .title)
        XCTAssertEqual(MacType.style(.rowTitle).relativeTo, .body)
        XCTAssertEqual(MacType.style(.eyebrow).relativeTo, .subheadline)
    }

    /// `.tracking(0)` replaces a face's own tracking table rather than adding
    /// to it, so a role that wants the system's metrics must carry exactly
    /// zero and the modifier must skip it. Only three roles set tracking.
    func testOnlyTheRolesThatNeedLetterSpacingCarryIt() {
        let tracked = VocelloTypeRole.allCases.filter { MacType.style($0).tracking != 0 }
        XCTAssertEqual(
            Set(tracked), [.script, .buttonLabel, .eyebrow],
            "Letter spacing belongs to a role, and a role that does not need it must carry 0 so no modifier is applied."
        )
    }

    /// Six cases, five distinct heights: `.pill` and `.row` deliberately share
    /// 40 pt, so a Studio chip and a sidebar row are the same size and the two
    /// halves of the window read at one density. They stay separate cases
    /// because they carry different glyphs and shapes, which is the same
    /// reason four type roles share 13 pt.
    func testControlLadderIsOrderedAndGlyphsFollowTheirControl() {
        let heights = MacControl.allCases.map(\.height)
        XCTAssertEqual(heights.sorted(), [24, 28, 36, 40, 40, 48])
        XCTAssertEqual(MacControl.pill.height, MacControl.row.height)
        for control in MacControl.allCases {
            let ratio = control.glyph / control.height
            XCTAssertTrue(
                (0.25...0.48).contains(ratio),
                "\(control)'s glyph is \(control.glyph) in a \(control.height) control (ratio \(ratio)); a glyph is about a third of what holds it."
            )
        }
    }

    func testStrokeAndOpacityStepsAreOrdered() {
        XCTAssertLessThan(VocelloTheme.Stroke.hairline, VocelloTheme.Stroke.standard)
        XCTAssertLessThan(VocelloTheme.Stroke.standard, VocelloTheme.Stroke.focus)
        XCTAssertLessThan(VocelloTheme.Opacity.disabled, VocelloTheme.Opacity.dimmed)
        XCTAssertLessThan(VocelloTheme.Opacity.dimmed, VocelloTheme.Opacity.placeholder)
    }
}
