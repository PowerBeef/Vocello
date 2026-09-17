import SwiftUI
import XCTest

/// The Studio setup-chip row has shipped two visual defects from this
/// arithmetic and had no test until now: chips truncating the one label a user
/// chose, and — found by an audit rather than by eye — a chip drawing past the
/// row's right edge. `placeSubviews` cannot be exercised directly because
/// `Subviews` has no public initialiser, so the arithmetic lives in
/// `MacChipRowMetrics.RowBudget`, which does.
@MainActor
final class MacChipFlowTests: XCTestCase {
    private let spacing = VocelloTheme.Spacing.sm
    private let minimum = MacChipRowMetrics.minimumChipWidth

    private func budget(_ ideals: [CGFloat], perRow: Int, rowWidth: CGFloat) -> MacChipRowMetrics.RowBudget {
        MacChipRowMetrics.RowBudget(
            ideals: ideals,
            perRow: perRow,
            rowWidth: rowWidth,
            spacing: spacing,
            minimumChipWidth: minimum
        )
    }

    /// The invariant the overflow bug broke. Whatever the ideals, the widths
    /// handed to one row plus the gaps between them must fit the row.
    func testARowNeverReceivesMoreWidthThanItHas() {
        let rowWidth: CGFloat = 740
        let cases: [[CGFloat]] = [
            [166, 134, 135, 137, 135],          // the five real Studio chips
            [166, 0, 135, 137, 135],            // an empty chip: the seed pin with no seed
            [10, 10, 10, 10, 10],               // every chip below the floor
            [400, 10, 10],                      // one long saved-voice name
            [132, 132, 132, 132, 132],          // everything exactly on the floor
        ]

        for ideals in cases {
            for perRow in 1...ideals.count {
                let budget = budget(ideals, perRow: perRow, rowWidth: rowWidth)
                for start in stride(from: 0, to: ideals.count, by: perRow) {
                    let row = Array(ideals[start ..< min(start + perRow, ideals.count)])
                    let placed = row.map { budget.width(forIdeal: max($0, minimum)) }
                    let used = placed.reduce(0, +) + spacing * CGFloat(row.count - 1)
                    XCTAssertLessThanOrEqual(
                        used, rowWidth + 0.5,
                        "ideals \(ideals) at \(perRow)/row placed \(placed) into \(rowWidth) pt"
                    )
                }
            }
        }
    }

    /// A chip that reports less than the floor still gets the floor. This is
    /// what makes the invariant above load-bearing: `VocelloSetupChipPill`
    /// carries `.frame(minWidth:)`, so a chip handed less simply renders wider
    /// than it was told and draws outside the row.
    func testNoChipIsEverPlacedBelowTheMinimum() {
        let budget = budget([0, 10, 131, 400], perRow: 4, rowWidth: 740)
        for ideal in [CGFloat(0), 10, 131, 400] {
            XCTAssertGreaterThanOrEqual(budget.width(forIdeal: max(ideal, minimum)), minimum)
        }
    }

    /// The reason the natural-width branch exists: a long label keeps its
    /// width instead of being averaged away by short neighbours.
    func testALongLabelKeepsItsWidthWhenTheRowCanAffordIt() {
        let budget = budget([300, 132, 132], perRow: 3, rowWidth: 740)
        XCTAssertTrue(budget.honorsIdealWidths)
        XCTAssertGreaterThan(budget.width(forIdeal: 300), budget.width(forIdeal: 132))
    }

    /// And the reason it has a fallback: when the naturals cannot fit, equal
    /// shares are the fair answer and every chip still clears the floor.
    func testEqualSharesTakeOverWhenNaturalWidthsDoNotFit() {
        let budget = budget([400, 400, 400], perRow: 3, rowWidth: 500)
        XCTAssertFalse(budget.honorsIdealWidths)
        XCTAssertEqual(budget.width(forIdeal: 400), budget.equalShare)
    }

    /// `chipsPerRow` is what guarantees equal shares clear the floor, so the
    /// fallback above is only ever reached at a width where it is true.
    func testEqualSharesAlwaysClearTheFloor() {
        for width in stride(from: CGFloat(200), through: 1400, by: 20) {
            for count in 1...6 {
                let perRow = MacChipRowMetrics.chipsPerRow(count: count, width: width, spacing: spacing)
                XCTAssertGreaterThanOrEqual(perRow, 1)
                guard perRow > 1 else { continue }
                let available = width - spacing * CGFloat(perRow - 1)
                XCTAssertGreaterThanOrEqual(
                    (available / CGFloat(perRow)).rounded(.down), minimum,
                    "\(perRow) chips per row at \(width) pt leaves less than the floor each"
                )
            }
        }
    }

    /// Rows are partitioned the same way in both passes, so the height
    /// `sizeThatFits` reports matches what `placeSubviews` lays out.
    func testRowCountAgreesWithChipsPerRow() {
        for width in stride(from: CGFloat(200), through: 1400, by: 20) {
            for count in 1...6 {
                let perRow = MacChipRowMetrics.chipsPerRow(count: count, width: width, spacing: spacing)
                let expected = Int((Double(count) / Double(perRow)).rounded(.up))
                XCTAssertEqual(
                    MacChipRowMetrics.rowCount(count: count, width: width, spacing: spacing), expected
                )
            }
        }
    }
}
