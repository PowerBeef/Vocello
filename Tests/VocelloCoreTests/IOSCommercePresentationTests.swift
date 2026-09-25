import Foundation
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

    /// AUD-08: the internal purchase-failure record keeps the error's typed shape, never
    /// its reflected text, which carries user-info values such as a failing URL or path.
    func testPurchaseFailureRecordKeepsTypedShapeWithoutErrorText() throws {
        let fixture = PrivateDiagnosticFixture.self
        let failure = NSError(domain: "ASDErrorDomain", code: 500, userInfo: [
            NSLocalizedDescriptionKey: "Could not buy “\(fixture.prompt)”",
            NSURLErrorFailingURLErrorKey: URL(string: "https://example.invalid/\(fixture.outputName)")!,
            NSFilePathErrorKey: fixture.path,
            NSUnderlyingErrorKey: fixture.cocoaWriteError,
        ])
        XCTAssertTrue(String(describing: failure).contains(fixture.homeFragment))

        let data = try XCTUnwrap(IOSCommerceErrorDiagnostics.purchaseFailureRecord(failure))
        let text = try XCTUnwrap(String(data: data, encoding: .utf8))
        fixture.assertNoPrivateContent(text)
        XCTAssertFalse(text.contains("example.invalid"))
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertEqual(object["schemaVersion"] as? Int, 2)
        let error = try XCTUnwrap(object["error"] as? [String: Any])
        XCTAssertEqual(error["domain"] as? String, "ASDErrorDomain")
        XCTAssertEqual(error["domainCode"] as? Int, 500)
        let underlying = try XCTUnwrap(error["underlying"] as? [[String: Any]])
        XCTAssertEqual(underlying.compactMap { $0["domain"] as? String }, [NSCocoaErrorDomain, NSPOSIXErrorDomain])
    }
}
