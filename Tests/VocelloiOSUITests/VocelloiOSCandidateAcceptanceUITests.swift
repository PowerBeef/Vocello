import Foundation
@preconcurrency import XCTest

/// Black-box route proof, not the full distribution-candidate acceptance matrix.
/// No production dependency, debug launch input, telemetry or container access.
@MainActor
final class VocelloiOSCandidateAcceptanceUITests: XCTestCase {
    func testPreinstalledCandidateNavigation() throws {
        continueAfterFailure = false
        let encoded = try XCTUnwrap(ProcessInfo.processInfo.environment["VOCELLO_CANDIDATE_IDENTITY"])
        let data = try XCTUnwrap(Data(base64Encoded: encoded))
        let identity = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertEqual(identity["evidenceClass"] as? String, "preinstalled-candidate-black-box")
        XCTAssertEqual(identity["bundleIdentifier"] as? String, "com.patricedery.vocello")
        let app = XCUIApplication(bundleIdentifier: "com.patricedery.vocello")
        app.launchArguments = []
        app.launchEnvironment = [:]
        app.launch()
        VocelloUIFailureEvidence.observedApp = app
        var originalTab: XCUIElement?
        defer {
            if let originalTab, app.state == .runningForeground {
                XCTAssertTrue(VocelloUIPrimaryAction.perform(on: originalTab, timeout: 20))
            }
            app.terminate()
            VocelloUIFailureEvidence.observedApp = nil
            XCUIDevice.shared.press(.home)
        }
        // This route proof is upgrade-safe. Fresh onboarding is a separate,
        // protected maintenance session, not an implicit skip or state reset.
        XCTAssertFalse(app.buttons["onboarding_skip"].exists, "Complete authorized first-launch acceptance separately")
        XCTAssertTrue(VocelloUIWait.exists(VocelloUIWait.element(app, id: "rootTab_studio"), timeout: 30))
        let selectedTabs = ["studio", "voices", "history", "settings"].map {
            VocelloUIWait.element(app, id: "rootTab_\($0)")
        }.filter(\.isSelected)
        XCTAssertEqual(selectedTabs.count, 1, "Preserve the visible original tab")
        originalTab = try XCTUnwrap(selectedTabs.first)
        for tab in ["studio", "voices", "history", "settings"] {
            let button = VocelloUIWait.element(app, id: "rootTab_\(tab)")
            XCTAssertTrue(VocelloUIWait.exists(button, timeout: 30))
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: button, timeout: 20))
            let selected = XCTNSPredicateExpectation(predicate: NSPredicate(format: "isSelected == true"), object: button)
            XCTAssertEqual(XCTWaiter.wait(for: [selected], timeout: 10), .completed)
            VocelloUIScreenshot.attach(app, named: "candidate-\(tab)")
        }
        let version = VocelloUIWait.element(app, id: "iosSettings_versionLabel")
        let scroll = app.scrollViews.firstMatch
        for _ in 0..<12 {
            if version.exists && version.isHittable { break }
            scroll.swipeUp()
        }
        XCTAssertTrue(VocelloUIWait.exists(version, timeout: 10))
        let visibleVersion = version.label + " " + (version.value as? String ?? "")
        let expectedVersion = try XCTUnwrap(identity["marketingVersion"] as? String)
        XCTAssertTrue(visibleVersion.contains(expectedVersion), "Visible version must match approved candidate")
        VocelloUIScreenshot.attach(app, named: "candidate-version")
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: VocelloUIWait.element(app, id: "rootTab_studio"), timeout: 20))
        let attachment = XCTAttachment(data: data, uniformTypeIdentifier: "public.json")
        attachment.name = "preinstalled-candidate-identity.json"
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
