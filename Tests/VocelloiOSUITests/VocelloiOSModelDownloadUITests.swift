import Foundation
@preconcurrency import XCTest

/// Explicit, opt-in physical-device proof for background model delivery. This method is selected
/// directly by `scripts/ui_test.sh ios model-download`; smoke, benchmarks, CI, and release never
/// execute it. All actions use genuine visible Settings controls.
@MainActor
final class VocelloiOSModelDownloadUITests: VocelloiOSUITestCase {
    private let isolatedSupportRoot = "model-download-acceptance"
    private let modelID = "pro_custom"

    func testIsolatedBackgroundDownloadAdoptionAndCleanup() {
        beginSession()
        defer { endSession() }
        select(tab: .settings)
        let canonicalSnapshot = snapshotQuiescentCanonicalDelivery()

        var environment = ["QVOICE_APP_SUPPORT_DIR": isolatedSupportRoot]
        // MD-2 A/B arm selection: `scripts/ui_test.sh ios model-download
        // --engine-profile …` forwards the registered download-engine knob through
        // the runner into the isolated app (the base case already sets
        // QWENVOICE_DEBUG). Absent, the app uses its shipping default.
        if let engineProfile = ProcessInfo.processInfo
            .environment["QVOICE_IOS_DOWNLOAD_ENGINE_PROFILE"], !engineProfile.isEmpty {
            environment["QVOICE_DOWNLOAD_ENGINE_PROFILE"] = engineProfile
        }
        launchApp(additionalEnvironment: environment)

        select(tab: .settings)
        XCTAssertFalse(
            element("iosModelDelete_\(modelID)").exists,
            "The isolated root must begin without Custom installed; refusing to delete an ambiguous model"
        )

        let install = element("iosModelDownload_\(modelID)")
        XCTAssertTrue(VocelloUIWait.exists(install, timeout: 60))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: install, timeout: 20))

        let progress = element("iosModelProgress_\(modelID)")
        XCTAssertTrue(VocelloUIWait.exists(progress, timeout: 120))
        XCTAssertTrue(VocelloUIWait.condition("model download to make measurable progress", timeout: 600) {
            self.progressFraction(progress) > 0
        })
        let beforeRelaunch = progressFraction(progress)
        VocelloUIScreenshot.attach(app, named: "ios-model-download-before-relaunch")

        XCUIDevice.shared.press(.home)
        XCTAssertTrue(VocelloUIWait.condition("Vocello to enter the background", timeout: 30) {
            self.app.state == .runningBackground || self.app.state == .runningBackgroundSuspended
        })
        app.terminate()
        launchApp(additionalEnvironment: environment)
        select(tab: .settings)

        let installed = element("iosModelDelete_\(modelID)")
        let restoredProgress = element("iosModelProgress_\(modelID)")
        XCTAssertTrue(VocelloUIWait.condition("adopted download progress or completed install", timeout: 120) {
            if installed.exists { return true }
            guard restoredProgress.exists else { return false }
            return self.progressFraction(restoredProgress) >= beforeRelaunch
        })
        XCTAssertTrue(VocelloUIWait.exists(installed, timeout: 3_600))
        VocelloUIScreenshot.attach(app, named: "ios-model-download-installed")

        // Phase 8 shared-component live coverage: with Custom still installed in the
        // isolated root, deliver the remaining Speed artifacts. Their delivery plans
        // must reuse the verified speech-tokenizer component; the pulled diagnostics
        // validator enforces the exact wire-byte accounting.
        for reusedModelID in ["pro_design", "pro_clone"] {
            let download = element("iosModelDownload_\(reusedModelID)")
            XCTAssertTrue(VocelloUIWait.exists(download, timeout: 60))
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: download, timeout: 20))
            XCTAssertTrue(
                VocelloUIWait.exists(element("iosModelDelete_\(reusedModelID)"), timeout: 3_600),
                "isolated \(reusedModelID) must reach installed through the shared-component plan"
            )
            VocelloUIScreenshot.attach(app, named: "ios-model-download-installed-\(reusedModelID)")
        }

        for cleanupModelID in ["pro_clone", "pro_design", modelID] {
            let delete = element("iosModelDelete_\(cleanupModelID)")
            XCTAssertTrue(VocelloUIWait.exists(delete, timeout: 60))
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: delete, timeout: 20))
            let confirmDelete = element("deleteModelSheet_confirm")
            XCTAssertTrue(VocelloUIWait.exists(confirmDelete, timeout: 20))
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: confirmDelete, timeout: 20))
            XCTAssertTrue(VocelloUIWait.exists(element("iosModelDownload_\(cleanupModelID)"), timeout: 120))
        }
        VocelloUIScreenshot.attach(app, named: "ios-model-download-isolated-cleanup")

        // Leave the isolated root, then prove the user's canonical installation
        // state is exactly what it was through the same genuine Settings surface.
        launchApp()
        select(tab: .settings)
        assertCanonicalDeliveryMatches(canonicalSnapshot)
        VocelloUIScreenshot.attach(app, named: "ios-model-download-canonical-preserved")
    }

    /// Switching to an isolated support root is safe only while no canonical
    /// transfer is active. Each production model must be visibly quiescent
    /// (installed, or not installed with no delivery operation); the returned
    /// snapshot records which, so the end of the lane can prove the canonical
    /// surface came back byte-for-byte untouched. Requiring full installation
    /// here was stricter than the safety needs and made the lane unrunnable on
    /// a freshly restored device.
    private func snapshotQuiescentCanonicalDelivery() -> [String: Bool] {
        var installedByModelID: [String: Bool] = [:]
        for canonicalModelID in ["pro_custom", "pro_design", "pro_clone"] {
            let installed = element("iosModelDelete_\(canonicalModelID)")
            let downloadable = element("iosModelDownload_\(canonicalModelID)")
            XCTAssertTrue(
                VocelloUIWait.condition(
                    "canonical \(canonicalModelID) to be visibly quiescent",
                    timeout: 60
                ) {
                    installed.exists || downloadable.exists
                },
                "The isolated delivery proof requires canonical \(canonicalModelID) installed or plainly downloadable"
            )
            for activeControl in ["Cancel", "Retry", "Repair"] {
                XCTAssertFalse(
                    element("iosModel\(activeControl)_\(canonicalModelID)").exists,
                    "Canonical \(canonicalModelID) must not have an active delivery operation"
                )
            }
            XCTAssertFalse(element("iosModelProgress_\(canonicalModelID)").exists)
            installedByModelID[canonicalModelID] = installed.exists
        }
        return installedByModelID
    }

    private func assertCanonicalDeliveryMatches(_ snapshot: [String: Bool]) {
        for (canonicalModelID, wasInstalled) in snapshot.sorted(by: { $0.key < $1.key }) {
            let expected = element(
                wasInstalled
                    ? "iosModelDelete_\(canonicalModelID)"
                    : "iosModelDownload_\(canonicalModelID)"
            )
            XCTAssertTrue(
                VocelloUIWait.exists(expected, timeout: 60),
                "Canonical \(canonicalModelID) must return \(wasInstalled ? "installed" : "downloadable") after the isolated run"
            )
            XCTAssertFalse(element("iosModelProgress_\(canonicalModelID)").exists)
        }
    }

    private func progressFraction(_ element: XCUIElement) -> Double {
        guard element.exists else { return 0 }
        if let number = element.value as? NSNumber {
            return number.doubleValue
        }
        guard let value = element.value as? String else { return 0 }
        let numeric = value
            .replacingOccurrences(of: "%", with: "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard let parsed = Double(numeric) else { return 0 }
        return value.contains("%") ? parsed / 100 : parsed
    }
}
