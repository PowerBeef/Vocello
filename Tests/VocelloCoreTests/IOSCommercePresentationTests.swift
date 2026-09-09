import XCTest

final class IOSCommercePresentationTests: XCTestCase {
    func testProductAvailabilityNoticeUsesActualAccessWithoutChangingOtherOutcomes() {
        XCTAssertEqual(VocelloPresentationText.exportPurchaseNotice(.unavailable, access: .unlocked),
                       "Purchase information is currently unavailable. Your export unlock is still active; you can save and share audio in every mode.")
        for access in [IOSExportPurchaseState.Access.locked, .checking] {
            XCTAssertEqual(VocelloPresentationText.exportPurchaseNotice(.unavailable, access: access),
                           "The purchase is currently unavailable. Your audio stays in Vocello. You can try again or restore an existing purchase.")
        }
        for notice in [IOSExportPurchaseState.Notice.cancelled, .pending, .failed, .unverified, .restored, .notOwned] {
            XCTAssertEqual(VocelloPresentationText.exportPurchaseNotice(notice, access: .unlocked),
                           VocelloPresentationText.exportPurchaseNotice(notice, access: .locked))
        }
    }
}
