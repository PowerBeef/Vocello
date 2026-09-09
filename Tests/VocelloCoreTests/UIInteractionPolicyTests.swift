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
}
