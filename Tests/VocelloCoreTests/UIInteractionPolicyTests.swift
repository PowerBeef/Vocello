import XCTest

final class UIInteractionPolicyTests: XCTestCase {
    private let viewport = CGRect(x: 0, y: 60, width: 400, height: 640)

    func testWholeTwoRowDockRejectsContentAboveSettingsButtonButBehindUpperRow() throws {
        let window = CGRect(x: 0, y: 0, width: 400, height: 900)
        let dock = CGRect(x: 0, y: 650, width: 400, height: 250)
        let visible = try XCTUnwrap(VocelloUIRevealRequirement.viewport(
            window: window, statusBar: CGRect(x: 0, y: 0, width: 400, height: 60), dock: dock))
        XCTAssertEqual(visible, CGRect(x: 0, y: 60, width: 400, height: 586))
        let obscured = CGRect(x: 20, y: 670, width: 360, height: 44)
        XCTAssertLessThan(obscured.maxY, 780) // The lower Settings button formerly permitted this.
        for requirement in [VocelloUIRevealRequirement.fullVisibility, .navigation] {
            XCTAssertFalse(requirement.satisfied(by: obscured, visible: visible))
            XCTAssertTrue(requirement.satisfied(by: CGRect(x: 20, y: 602, width: 360, height: 44),
                                                 visible: visible))
            XCTAssertFalse(requirement.satisfied(by: CGRect(x: 20, y: 603, width: 360, height: 44),
                                                  visible: visible))
        }
        XCTAssertNil(VocelloUIRevealRequirement.viewport(window: window, statusBar: nil, dock: .zero))
    }

    func testOversizedNavigationNeverCountsAsFullVisibility() {
        let row = CGRect(x: 20, y: -100, width: 360, height: 900)
        XCTAssertTrue(VocelloUIRevealRequirement.navigation.satisfied(by: row, visible: viewport))
        XCTAssertFalse(VocelloUIRevealRequirement.fullVisibility.satisfied(by: row, visible: viewport))
        let band = VocelloUIRevealRequirement.navigation.requiredFrame(row, visible: viewport)
        XCTAssertEqual(band, CGRect(x: 20, y: 328, width: 360, height: 44))
        var search = VocelloUIRevealSearch(preferred: .up)
        let lowRow = CGRect(x: 20, y: 270, width: 360, height: 900)
        XCTAssertFalse(VocelloUIRevealRequirement.navigation.satisfied(by: lowRow, visible: viewport))
        XCTAssertEqual(search.next(target: VocelloUIRevealRequirement.navigation.requiredFrame(lowRow, visible: viewport),
                                   visible: viewport), .up)
        let highRow = CGRect(x: 20, y: -500, width: 360, height: 900)
        XCTAssertEqual(search.next(target: VocelloUIRevealRequirement.navigation.requiredFrame(highRow, visible: viewport),
                                   visible: viewport), .down)
    }

    func testOrdinaryRowsAndInvalidFramesCannotUseOversizedException() {
        let invalid: [CGRect] = [.zero, .null, .infinite,
                                CGRect(x: -1, y: 100, width: 400, height: 44),
                                CGRect(x: 20, y: 690, width: 360, height: 44)]
        for frame in invalid {
            XCTAssertFalse(VocelloUIRevealRequirement.navigation.satisfied(by: frame, visible: viewport))
            XCTAssertFalse(VocelloUIRevealRequirement.fullVisibility.satisfied(by: frame, visible: viewport))
        }
    }

    func testRetainedBottomOfHubOverridesUpwardPreference() {
        var search = VocelloUIRevealSearch(preferred: .up)
        XCTAssertEqual(search.next(target: CGRect(x: 10, y: -200, width: 360, height: 100),
                                   visible: viewport), .down)
    }

    func testPartiallyDockObscuredRowMovesUpEvenIfHittable() {
        var search = VocelloUIRevealSearch(preferred: .down)
        XCTAssertEqual(search.next(target: CGRect(x: 10, y: 680, width: 360, height: 100),
                                   visible: viewport), .up)
    }

    func testDirectionRecomputedAfterEachSnapshot() {
        var search = VocelloUIRevealSearch(preferred: .up)
        XCTAssertEqual(search.next(target: CGRect(x: 0, y: 10, width: 300, height: 80),
                                   visible: viewport), .down)
        XCTAssertEqual(search.next(target: CGRect(x: 0, y: 650, width: 300, height: 80),
                                   visible: viewport), .up)
    }

    func testMissingAndEmptyFramesSearchBothWaysAndTerminate() {
        for preferred in [VocelloUIRevealSearch.Swipe.up, .down] {
            var search = VocelloUIRevealSearch(preferred: preferred)
            for index in 0..<20 {
                XCTAssertEqual(search.next(target: index.isMultiple(of: 2) ? nil : .zero, visible: viewport),
                               index < 10 ? preferred : (preferred == .up ? .down : .up))
            }
            XCTAssertNil(search.next(target: nil, visible: viewport))
        }
    }

    func testBackgroundOrFailedRestorationCannotClaimCleanup() throws {
        var state = VocelloUIPurchaseRestoration(transactionsCleared: true, tab: .restored,
                                                historyFilter: .restored, appStopped: true)
        XCTAssertTrue(state.complete)
        for outcome in [VocelloUIPurchaseRestoration.Outcome.skippedBackground, .baselineMissing, .failed] {
            state.tab = outcome
            XCTAssertFalse(state.complete)
            state.tab = .restored
            state.historyFilter = outcome
            XCTAssertFalse(state.complete)
            state.historyFilter = .restored
        }
        let decoded = try JSONDecoder().decode(VocelloUIPurchaseRestoration.self,
                                               from: JSONEncoder().encode(state))
        XCTAssertTrue(decoded.complete)
        state.transactionsCleared = false
        XCTAssertFalse(state.complete)
        state.transactionsCleared = true
        state.appStopped = false
        XCTAssertFalse(state.complete)
    }

    func testDesiredMovementBudgetConvergesForSyntheticDisplacementGains() throws {
        let visible = CGRect(x: 0, y: 0, width: 402, height: 632)
        // Both sides of the actual oscillation, with varied platform displacement.
        for top in [343.333, -262.333] {
            for gain in [0.5, 1.0, 2.0, 3.0] {
                var row = CGRect(x: 16, y: top, width: 370, height: 514)
                var search = VocelloUIRevealSearch(preferred: .up)
                while !VocelloUIRevealRequirement.fullVisibility.satisfied(by: row, visible: visible) {
                    let delta = try XCTUnwrap(search.nextScroll(target: row, visible: visible))
                    XCTAssertLessThanOrEqual(abs(delta), 120)
                    row = row.offsetBy(dx: 0, dy: delta * gain)
                }
                XCTAssertLessThan(search.attempts, 20)
            }
        }
    }

    func testTouchAnchorExcludesDockOffscreenAndOversizedRows() {
        let frames = [
            CGRect(x: 16, y: -18, width: 370, height: 127), // retained offscreen row
            CGRect(x: 16, y: 491, width: 370, height: 242), // retained dock overlap
            CGRect(x: 16, y: 100, width: 370, height: 514), // too large for bounded swipe
            CGRect(x: 54, y: 300, width: 220, height: 50),
            CGRect(x: 54, y: 400, width: 220, height: 90),
        ]
        XCTAssertEqual(VocelloUITouchScrollAnchor.index(frames: frames, visible: viewport, desiredDelta: -120), 4)
        XCTAssertEqual(VocelloUITouchScrollAnchor.index(frames: frames, visible: viewport, desiredDelta: 30), 3)
        XCTAssertNil(VocelloUITouchScrollAnchor.index(frames: Array(frames.prefix(3)), visible: viewport, desiredDelta: -120))
    }

    func testTouchAnchorFailsClosedAndDoesNotConfuseSpeedWithDistance() {
        let small = CGRect(x: 20, y: 100, width: 100, height: 20)
        XCTAssertEqual(VocelloUITouchScrollAnchor.index(frames: [.null, .zero, small, small],
                                                       visible: viewport, desiredDelta: -4), 2)
        XCTAssertNil(VocelloUITouchScrollAnchor.index(frames: [small], visible: .zero, desiredDelta: 30))
        XCTAssertNil(VocelloUITouchScrollAnchor.index(frames: [small], visible: viewport, desiredDelta: .nan))
        XCTAssertNil(VocelloUITouchScrollAnchor.index(frames: [small], visible: viewport, desiredDelta: 0))
    }

    func testBoundedScrollReversalReducesMovement() throws {
        var search = VocelloUIRevealSearch(preferred: .up)
        XCTAssertEqual(search.nextScroll(target: CGRect(x: 10, y: 800, width: 300, height: 514),
                                         visible: viewport), -120)
        XCTAssertEqual(search.nextScroll(target: CGRect(x: 10, y: -300, width: 300, height: 514),
                                         visible: viewport), 60)
        XCTAssertEqual(search.nextScroll(target: CGRect(x: 10, y: 800, width: 300, height: 514),
                                         visible: viewport), -30)
    }

    func testBoundedScrollStopsOnUnchangedFramesAndImpossibleGeometry() {
        var search = VocelloUIRevealSearch(preferred: .up)
        let row = CGRect(x: 10, y: 800, width: 300, height: 514)
        for _ in 0..<3 { XCTAssertNotNil(search.nextScroll(target: row, visible: viewport)) }
        XCTAssertNil(search.nextScroll(target: row, visible: viewport))
        for invalid in [CGRect(x: 0, y: 0, width: 300, height: 900),
                        CGRect(x: -1, y: 0, width: 300, height: 100),
                        CGRect(x: 0, y: 0, width: 500, height: 100)] {
            var impossible = VocelloUIRevealSearch(preferred: .up)
            XCTAssertNil(impossible.nextScroll(target: invalid, visible: viewport))
        }
        var satisfied = VocelloUIRevealSearch(preferred: .up)
        XCTAssertNil(satisfied.nextScroll(target: CGRect(x: 10, y: 100, width: 300, height: 44),
                                           visible: viewport))
        XCTAssertNil(satisfied.nextScroll(target: row, visible: .zero))
    }

    func testBoundedScrollRetainsMissingFrameBudgetAndNavigationDistinction() throws {
        var missing = VocelloUIRevealSearch(preferred: .up)
        for _ in 0..<20 { XCTAssertNotNil(missing.nextScroll(target: nil, visible: viewport)) }
        XCTAssertNil(missing.nextScroll(target: nil, visible: viewport))
        let oversized = CGRect(x: 10, y: 500, width: 300, height: 900)
        var full = VocelloUIRevealSearch(preferred: .up)
        XCTAssertNil(full.nextScroll(target: oversized, visible: viewport))
        var navigation = VocelloUIRevealSearch(preferred: .up)
        let band = VocelloUIRevealRequirement.navigation.requiredFrame(oversized, visible: viewport)
        XCTAssertLessThan(try XCTUnwrap(navigation.nextScroll(target: band, visible: viewport)), 0)
        XCTAssertFalse(VocelloUIRevealRequirement.fullVisibility.satisfied(by: oversized, visible: viewport))
    }

    // MARK: - Layout bounds under long strings

    func testSingleLineBoundsAcceptOneLineAndRejectTheCollapsedChip() {
        let oneLine = CGRect(x: 40, y: 100, width: 120, height: 18)
        XCTAssertTrue(VocelloUILayoutBounds.singleLine(oneLine, maxHeight: 30, minWidth: 60))
        // The 2026-09-13 pseudo-localized collapse: one character per line.
        let collapsedChip = CGRect(x: 60, y: 120, width: 30, height: 340)
        XCTAssertFalse(VocelloUILayoutBounds.singleLine(collapsedChip, maxHeight: 30, minWidth: 60))
        // Two wrapped lines are also refused; a narrow single line is refused by width.
        XCTAssertFalse(VocelloUILayoutBounds.singleLine(CGRect(x: 0, y: 0, width: 200, height: 36), maxHeight: 30, minWidth: 60))
        XCTAssertFalse(VocelloUILayoutBounds.singleLine(CGRect(x: 0, y: 0, width: 12, height: 18), maxHeight: 30, minWidth: 60))
        for invalid in [CGRect.null, CGRect.infinite, CGRect(x: 0, y: 0, width: 0, height: 0),
                        CGRect(x: CGFloat.nan, y: 0, width: 10, height: 10)] {
            XCTAssertFalse(VocelloUILayoutBounds.singleLine(invalid, maxHeight: 30, minWidth: 1))
        }
    }

    func testHorizontalContainmentIgnoresRowsBelowTheFoldButCatchesOverflow() {
        let window = CGRect(x: 100, y: 50, width: 720, height: 690)
        XCTAssertTrue(VocelloUILayoutBounds.horizontallyWithin(
            CGRect(x: 400, y: 900, width: 100, height: 24), window: window),
            "a row scrolled below the window is still horizontally contained")
        XCTAssertTrue(VocelloUILayoutBounds.horizontallyWithin(
            CGRect(x: 99.5, y: 60, width: 720.8, height: 24), window: window),
            "sub-point rendering slop stays inside the tolerance")
        XCTAssertFalse(VocelloUILayoutBounds.horizontallyWithin(
            CGRect(x: 700, y: 60, width: 160, height: 24), window: window),
            "an action button pushed past the right edge is the collapse signal")
        XCTAssertFalse(VocelloUILayoutBounds.horizontallyWithin(
            CGRect(x: 60, y: 60, width: 100, height: 24), window: window))
        XCTAssertFalse(VocelloUILayoutBounds.horizontallyWithin(.null, window: window))
        XCTAssertFalse(VocelloUILayoutBounds.horizontallyWithin(
            CGRect(x: 200, y: 60, width: 100, height: 24), window: .infinite))
    }

    /// Two-axis containment differs from horizontal containment in exactly one
    /// case, and that case is the whole point: a control below the fold. In a
    /// list it is fine and `horizontallyWithin` says so; under a column that
    /// does not scroll it is unreachable and this must say so.
    func testFullContainmentRefusesTheControlBelowTheFoldThatHorizontalAccepts() {
        let window = CGRect(x: 100, y: 50, width: 880, height: 560)
        let belowTheFold = CGRect(x: 140, y: 600, width: 200, height: 56)
        XCTAssertTrue(VocelloUILayoutBounds.horizontallyWithin(belowTheFold, window: window))
        XCTAssertFalse(VocelloUILayoutBounds.fullyWithin(belowTheFold, window: window),
            "a dock pushed past the window's bottom edge is unreachable, not scrolled away")

        // The measured shape of the defect: a column needing 633 pt of height
        // inside a window whose declared minimum is 560 leaves the dock 73 pt
        // past the bottom edge.
        let clippedDock = CGRect(x: 140, y: 50 + 633 - 56, width: 200, height: 56)
        XCTAssertFalse(VocelloUILayoutBounds.fullyWithin(clippedDock, window: window))

        XCTAssertTrue(VocelloUILayoutBounds.fullyWithin(
            CGRect(x: 140, y: 500, width: 200, height: 56), window: window))
        // Sub-point rendering slop stays inside the tolerance on both axes.
        XCTAssertTrue(VocelloUILayoutBounds.fullyWithin(
            CGRect(x: 99.5, y: 49.5, width: 880.8, height: 560.8), window: window))
        // A control above the top edge is out of bounds too, not just below.
        XCTAssertFalse(VocelloUILayoutBounds.fullyWithin(
            CGRect(x: 140, y: 20, width: 200, height: 56), window: window))
        XCTAssertFalse(VocelloUILayoutBounds.fullyWithin(.null, window: window))
        XCTAssertFalse(VocelloUILayoutBounds.fullyWithin(
            CGRect(x: 140, y: 100, width: 200, height: 56), window: .null))
    }
}
