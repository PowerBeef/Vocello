import CoreGraphics

/// The Studio setup-chip row's arithmetic, with no view dependency so it can be
/// unit-tested. `MacChipFlow` is a SwiftUI `Layout` whose `Subviews` cannot be
/// constructed in a test, and this is where the numbers that have twice shipped
/// a visual defect actually live: once truncating the one label the user chose,
/// once letting a chip draw past the row's right edge.
enum MacChipRowMetrics {
    /// The floor below which a chip's value stops reading after the glyph, the
    /// chevron and the padding take their share. `VocelloSetupChipPill` enforces
    /// it with `.frame(minWidth:)`, which is why the layout must respect it: a
    /// chip handed less does not shrink, it overflows.
    static let minimumChipWidth: CGFloat = 132

    /// How many chips share one row at this width. Every row uses the same
    /// count so a trailing row lines up under the row above.
    static func chipsPerRow(
        count: Int,
        width: CGFloat,
        spacing: CGFloat,
        minimumChipWidth: CGFloat = minimumChipWidth
    ) -> Int {
        guard count > 0, width.isFinite, width > 0 else { return max(count, 1) }
        let fitting = Int(((width + spacing) / (minimumChipWidth + spacing)).rounded(.down))
        return max(1, min(count, fitting))
    }

    static func rowCount(
        count: Int,
        width: CGFloat,
        spacing: CGFloat,
        minimumChipWidth: CGFloat = minimumChipWidth
    ) -> Int {
        let perRow = chipsPerRow(
            count: count, width: width, spacing: spacing, minimumChipWidth: minimumChipWidth
        )
        return Int((Double(count) / Double(perRow)).rounded(.up))
    }

    /// How a row's width is divided among its chips.
    ///
    /// Lifted out of `placeSubviews` because that is where the arithmetic that
    /// has broken twice lives, and `Subviews` cannot be constructed in a unit
    /// test. Everything here is pure, so `MacChipFlowTests` can hold the
    /// invariant that matters: the widths handed out for a row never exceed the
    /// width the row has.
    struct RowBudget: Equatable {
        /// True when every chip's natural width fits, so each keeps it and only
        /// the leftover is shared. False falls back to equal shares, which
        /// `chipsPerRow` has already guaranteed clear the minimum.
        let honorsIdealWidths: Bool
        let surplus: CGFloat
        let equalShare: CGFloat
        /// Ideal widths floored at the minimum, in the order given.
        let flooredIdeals: [CGFloat]

        init(
            ideals: [CGFloat],
            perRow: Int,
            rowWidth: CGFloat,
            spacing: CGFloat,
            minimumChipWidth: CGFloat
        ) {
            let perRow = max(perRow, 1)
            let available = rowWidth - spacing * CGFloat(perRow - 1)
            // Floored before they are budgeted, not after. A chip physically
            // cannot render narrower than `minimumChipWidth` --
            // `VocelloSetupChipPill` carries `.frame(minWidth:)` -- so a floor
            // applied after the shares were computed was width nobody had
            // accounted for. It came out of the trailing chip, whose share is
            // whatever remains to the row's edge, and that chip then drew at
            // its own minimum anyway: past the edge, unclipped.
            let floored = ideals.map { max($0, minimumChipWidth) }
            let widestRow = stride(from: 0, to: floored.count, by: perRow)
                .map { start in floored[start ..< min(start + perRow, floored.count)].reduce(0, +) }
                .max() ?? 0

            flooredIdeals = floored
            equalShare = (available / CGFloat(perRow)).rounded(.down)
            honorsIdealWidths = widestRow <= available
            surplus = honorsIdealWidths
                ? ((available - widestRow) / CGFloat(perRow)).rounded(.down)
                : 0
        }

        /// What a chip of this ideal width receives. Never below the minimum:
        /// `flooredIdeals` already cleared it and `surplus` is never negative.
        func width(forIdeal ideal: CGFloat) -> CGFloat {
            honorsIdealWidths ? ideal + surplus : equalShare
        }
    }
}
