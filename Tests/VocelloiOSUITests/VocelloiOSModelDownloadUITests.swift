import Foundation
@preconcurrency import XCTest

/// Explicit, opt-in physical-device proof for background model delivery. This method is selected
/// directly by `scripts/ui_test.sh ios model-download`; smoke, benchmarks, CI, and release never
/// execute it. All actions use genuine visible Settings controls.
@MainActor
final class VocelloiOSModelDownloadUITests: VocelloiOSUITestCase {
    private struct UIObservation: Codable {
        let schemaVersion: Int
        let capturedAtUTC: String
        let modelID: String
        let milestone: String
        let rawBytes: Int64?
        let totalBytes: Int64?
        let expectedFraction: Double?
        let accessibilityFraction: Double?
        let visibleText: String?
        let status: String?
        let phase: String
        let actions: [String]
        let elementFrame: Frame
        let rowFrame: Frame
        let progressScreenshot: String?
        let rowScreenshot: String
    }

    private struct Frame: Codable {
        let x: Double
        let y: Double
        let width: Double
        let height: Double

        init(_ rect: CGRect) {
            x = rect.origin.x
            y = rect.origin.y
            width = rect.size.width
            height = rect.size.height
        }
    }

    private struct ProgressSample {
        let rawBytes: Int64?
        let totalBytes: Int64?
        let fraction: Double
        let frame: CGRect
        let visibleText: String
    }
    private let isolatedSupportRoot = "model-download-acceptance"
    private let modelID = "pro_custom"
    private let modelIDs = ["pro_custom", "pro_design", "pro_clone"]
    private var capturedProgressMilestones: [String: Set<Int>] = [:]
    private var capturedPhases: [String: Set<String>] = [:]

    func testConfiguredModelManagementScenario() {
        let scenario = ProcessInfo.processInfo.environment["QVOICE_IOS_MODEL_MANAGEMENT_SCENARIO"]
            ?? "acceptance"
        switch scenario {
        case "diagnose": runDiagnosticScenario()
        case "queue": runQueueScenario()
        case "recover": runRecoveryScenario()
        case "soak":
            let raw = ProcessInfo.processInfo.environment["QVOICE_IOS_MODEL_MANAGEMENT_ITERATIONS"] ?? "3"
            let iterations = max(1, Int(raw) ?? 3)
            for iteration in 1...iterations { runDiagnosticScenario(iteration: iteration) }
        case "acceptance": runAcceptanceScenario()
        default: XCTFail("Unsupported model-management scenario: \(scenario)")
        }
    }

    private func runAcceptanceScenario() {
        beginSession()
        defer { endSession() }
        openVoiceModels()
        let canonicalSnapshot = snapshotQuiescentCanonicalDelivery()

        var environment = modelManagementEnvironment()
        // MD-2 A/B arm selection: `scripts/ui_test.sh ios model-download
        // --engine-profile …` forwards the registered download-engine knob through
        // the runner into the isolated app (the base case already sets
        // QWENVOICE_DEBUG). Absent, the app uses its shipping default.
        if let engineProfile = ProcessInfo.processInfo
            .environment["QVOICE_IOS_DOWNLOAD_ENGINE_PROFILE"], !engineProfile.isEmpty {
            environment["QVOICE_DOWNLOAD_ENGINE_PROFILE"] = engineProfile
        }
        launchApp(additionalEnvironment: environment)

        openVoiceModels()
        resetIsolatedDeliveryForFreshLifecycle()
        assertModelActionContract(
            modelID: modelID,
            status: "Not Installed",
            expectedAction: "Download"
        )

        let install = element("iosModelDownload_\(modelID)")
        XCTAssertTrue(VocelloUIWait.exists(install, timeout: 60))
        XCTAssertTrue(revealSettingsElement(install, swipingUp: true))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: install, timeout: 20))

        let progress = element("iosModelProgress_\(modelID)")
        guard waitForMeasurableTransfer(
            modelID: modelID,
            description: "model download to make measurable progress"
        ) else { return }
        assertModelActionContract(
            modelID: modelID,
            status: "Downloading",
            expectedAction: "Cancel"
        )
        VocelloUIScreenshot.attach(app, named: "ios-model-download-cancellable")

        // The redesigned screen exposes Cancel as the sole action while a
        // transfer is active. Prove that its destructive confirmation discards
        // staging and returns the row to a fresh, installable state before the
        // background-adoption journey starts.
        cancelDownload(modelID: modelID)
        assertModelActionContract(
            modelID: modelID,
            status: "Not Installed",
            expectedAction: "Download"
        )
        VocelloUIScreenshot.attach(app, named: "ios-model-download-cancelled")

        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: install, timeout: 20))
        guard waitForMeasurableTransfer(
            modelID: modelID,
            description: "restarted model download to make measurable progress"
        ) else { return }
        let beforeRelaunch = progressFraction(progress)
        VocelloUIScreenshot.attach(app, named: "ios-model-download-before-relaunch")

        XCUIDevice.shared.press(.home)
        XCTAssertTrue(VocelloUIWait.condition("Vocello to enter the background", timeout: 30) {
            self.app.state == .runningBackground || self.app.state == .runningBackgroundSuspended
        })
        app.terminate()
        launchApp(additionalEnvironment: environment)
        openVoiceModels()

        let installed = element("iosModelDelete_\(modelID)")
        let restoredProgress = element("iosModelProgress_\(modelID)")
        XCTAssertTrue(VocelloUIWait.condition("adopted download progress or completed install", timeout: 120) {
            if installed.exists { return true }
            guard restoredProgress.exists else { return false }
            return self.progressFraction(restoredProgress) >= beforeRelaunch
        })
        if let failure = waitForInstalledModel(
            modelID: modelID,
            progress: restoredProgress,
            initialProgress: beforeRelaunch
        ) {
            XCTFail(failure)
            return
        }
        assertModelActionContract(modelID: modelID, status: "Ready", expectedAction: "Delete")
        recordObservation(modelID: modelID, milestone: "ready")
        VocelloUIScreenshot.attach(app, named: "ios-model-download-installed")

        // Phase 8 shared-component live coverage: with Custom still installed in the
        // isolated root, deliver the remaining Speed artifacts. Their delivery plans
        // must reuse the verified speech-tokenizer component; the pulled diagnostics
        // validator enforces the exact wire-byte accounting.
        for reusedModelID in ["pro_design", "pro_clone"] {
            let download = element("iosModelDownload_\(reusedModelID)")
            XCTAssertTrue(VocelloUIWait.exists(download, timeout: 60))
            XCTAssertTrue(revealSettingsElement(download, swipingUp: true))
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: download, timeout: 20))
            if let failure = waitForInstalledModel(
                modelID: reusedModelID,
                progress: element("iosModelProgress_\(reusedModelID)")
            ) {
                XCTFail(failure)
                return
            }
            assertModelActionContract(modelID: reusedModelID, status: "Ready", expectedAction: "Delete")
            recordObservation(modelID: reusedModelID, milestone: "ready")
            VocelloUIScreenshot.attach(app, named: "ios-model-download-installed-\(reusedModelID)")
        }

        for cleanupModelID in ["pro_clone", "pro_design", modelID] {
            removeModel(modelID: cleanupModelID)
            assertModelActionContract(
                modelID: cleanupModelID,
                status: "Not Installed",
                expectedAction: "Download"
            )
            recordObservation(modelID: cleanupModelID, milestone: "removed")
        }
        VocelloUIScreenshot.attach(app, named: "ios-model-download-isolated-cleanup")

        // Leave the isolated root, then prove the user's canonical installation
        // state is exactly what it was through the same genuine Settings surface.
        launchApp()
        openVoiceModels()
        assertCanonicalDeliveryMatches(canonicalSnapshot)
        VocelloUIScreenshot.attach(app, named: "ios-model-download-canonical-preserved")
    }

    private func runDiagnosticScenario(iteration: Int? = nil) {
        beginSession()
        defer { endSession() }
        openVoiceModels()
        let canonicalSnapshot = snapshotQuiescentCanonicalDelivery()
        let suffix = iteration.map { "-iteration-\($0)" } ?? ""

        launchApp(additionalEnvironment: modelManagementEnvironment())
        openVoiceModels()
        VocelloUIScreenshot.attach(app, named: "ios-model-diagnose-retained-state\(suffix)")
        resetIsolatedDeliveryForFreshLifecycle()

        startDownload(modelID: modelID)
        let progress = element("iosModelProgress_\(modelID)")
        guard waitForMeasurableTransfer(
            modelID: modelID,
            description: "diagnostic transfer to advance",
            failureMilestone: "initial-progress-timeout\(suffix)"
        ) else { return }
        cancelDownload(modelID: modelID)
        recordObservation(modelID: modelID, milestone: "cancelled\(suffix)")

        startDownload(modelID: modelID)
        guard waitForMeasurableTransfer(
            modelID: modelID,
            description: "diagnostic transfer to restart",
            failureMilestone: "restart-progress-timeout\(suffix)"
        ) else { return }
        XCUIDevice.shared.press(.home)
        XCTAssertTrue(VocelloUIWait.condition("Vocello to enter the background", timeout: 30) {
            self.app.state == .runningBackground || self.app.state == .runningBackgroundSuspended
        })
        app.terminate()
        launchApp(additionalEnvironment: modelManagementEnvironment())
        openVoiceModels()
        if let failure = waitForInstalledModel(
            modelID: modelID,
            progress: progress,
            timeout: 3_600,
            stallTimeout: 300
        ) {
            XCTFail(failure)
            return
        }
        recordObservation(modelID: modelID, milestone: "ready\(suffix)")
        removeModel(modelID: modelID)
        recordObservation(modelID: modelID, milestone: "removed\(suffix)")

        launchApp(additionalEnvironment: modelManagementEnvironment())
        openVoiceModels()
        assertModelActionContract(modelID: modelID, status: "Not Installed", expectedAction: "Download")
        launchApp()
        openVoiceModels()
        assertCanonicalDeliveryMatches(canonicalSnapshot)
    }

    private func runQueueScenario() {
        beginSession()
        defer { endSession() }
        openVoiceModels()
        let canonicalSnapshot = snapshotQuiescentCanonicalDelivery()
        launchApp(additionalEnvironment: modelManagementEnvironment())
        openVoiceModels()
        resetIsolatedDeliveryForFreshLifecycle()

        startDownload(modelID: "pro_custom")
        guard waitForMeasurableTransfer(
            modelID: "pro_custom",
            description: "Custom transfer to become active",
            failureMilestone: "queue-progress-timeout"
        ) else { return }
        startDownload(modelID: "pro_design")
        assertModelActionContract(modelID: "pro_design", status: "Queued", expectedAction: "Cancel")
        assertModelActionContract(modelID: "pro_custom", status: "Downloading", expectedAction: "Cancel")
        recordObservation(modelID: "pro_custom", milestone: "queue-active")
        recordObservation(modelID: "pro_design", milestone: "queue-waiting")
        cancelDownload(modelID: "pro_design")
        XCTAssertTrue(element("iosModelCancel_pro_custom").exists)
        cancelDownload(modelID: "pro_custom")
        launchApp()
        openVoiceModels()
        assertCanonicalDeliveryMatches(canonicalSnapshot)
    }

    private func runRecoveryScenario() {
        beginSession()
        defer { endSession() }
        openVoiceModels()
        let canonicalSnapshot = snapshotQuiescentCanonicalDelivery()
        launchApp(additionalEnvironment: modelManagementEnvironment())
        openVoiceModels()
        VocelloUIScreenshot.attach(app, named: "ios-model-recover-retained-state")
        for candidate in modelIDs.reversed() {
            recordObservation(modelID: candidate, milestone: "recover-retained")
            if element("iosModelCancel_\(candidate)").exists {
                cancelDownload(modelID: candidate)
            } else if element("iosModelDelete_\(candidate)").exists {
                removeModel(modelID: candidate)
            } else {
                XCTAssertTrue(
                    element("iosModelDownload_\(candidate)").exists,
                    "Recover refuses to start a new transfer; retained \(candidate) requires explicit diagnosis"
                )
            }
            recordObservation(modelID: candidate, milestone: "recover-terminal")
        }
        launchApp()
        openVoiceModels()
        assertCanonicalDeliveryMatches(canonicalSnapshot)
    }

    private func startDownload(modelID: String) {
        let install = element("iosModelDownload_\(modelID)")
        XCTAssertTrue(VocelloUIWait.exists(install, timeout: 60))
        XCTAssertTrue(revealSettingsElement(install, swipingUp: modelID == "pro_clone"))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: install, timeout: 20))
        XCTAssertTrue(VocelloUIWait.condition("\(modelID) to expose progress or queued state", timeout: 120) {
            self.element("iosModelProgress_\(modelID)").exists
                || self.element("iosModelPhaseActivity_\(modelID)").exists
                || self.element("iosModelCancel_\(modelID)").exists
        })
    }

    /// A transfer must expose advancing determinate bytes within the no-advance policy
    /// window. Capture a structured row observation before failing so post-test analysis can
    /// distinguish a product state divergence from an XCUITest observation gap. Returning
    /// immediately preserves the isolated root exactly at the failure boundary.
    private func waitForMeasurableTransfer(
        modelID: String,
        description: String,
        failureMilestone: String = "progress-timeout",
        timeout: TimeInterval = 300
    ) -> Bool {
        let advanced = VocelloUIWait.condition(description, timeout: timeout) {
            let fraction = self.observeProgress(modelID: modelID)
            self.observeIndeterminatePhase(modelID: modelID)
            return fraction > 0
        }
        guard advanced else {
            recordObservation(modelID: modelID, milestone: failureMilestone)
            XCTFail("Timed out after \(timeout)s waiting for \(description)")
            return false
        }
        return true
    }

    /// A failed previous run may leave only this explicitly named test root
    /// populated. Normalize it through genuine visible lifecycle controls; the
    /// canonical snapshot was already captured and is rechecked at the end.
    /// Keeping the root stable also keeps one bounded background-session
    /// namespace instead of manufacturing a new daemon session per run.
    private func resetIsolatedDeliveryForFreshLifecycle() {
        for staleModelID in modelIDs.reversed() {
            let install = element("iosModelDownload_\(staleModelID)")
            let remove = element("iosModelDelete_\(staleModelID)")
            let cancel = element("iosModelCancel_\(staleModelID)")
            let retry = element("iosModelRetry_\(staleModelID)")

            XCTAssertTrue(VocelloUIWait.condition(
                "isolated \(staleModelID) to expose a stable lifecycle action",
                timeout: 300
            ) {
                install.exists || remove.exists || cancel.exists || retry.exists
            })

            if remove.exists {
                removeModel(modelID: staleModelID)
            } else if cancel.exists {
                cancelDownload(modelID: staleModelID)
            } else if retry.exists {
                XCTAssertTrue(revealSettingsElement(retry, swipingUp: staleModelID == "pro_clone"))
                XCTAssertTrue(VocelloUIPrimaryAction.perform(on: retry, timeout: 20))
                XCTAssertTrue(VocelloUIWait.condition(
                    "retried isolated \(staleModelID) to become cancellable or installed",
                    timeout: 120
                ) {
                    cancel.exists || remove.exists
                })
                if remove.exists {
                    removeModel(modelID: staleModelID)
                } else {
                    cancelDownload(modelID: staleModelID)
                }
            }

            XCTAssertTrue(
                VocelloUIWait.exists(install, timeout: 120),
                "isolated \(staleModelID) must be freshly installable after preparation"
            )
        }
        VocelloUIScreenshot.attach(app, named: "ios-model-download-isolated-prepared")
    }

    private func cancelDownload(modelID: String) {
        let cancel = element("iosModelCancel_\(modelID)")
        XCTAssertTrue(VocelloUIWait.exists(cancel, timeout: 120))
        XCTAssertTrue(revealSettingsElement(cancel, swipingUp: modelID == "pro_clone"))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: cancel, timeout: 20))
        let confirm = element("iosModelCancelDownloadConfirmButton")
        XCTAssertTrue(VocelloUIWait.exists(confirm, timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: confirm, timeout: 20))
        XCTAssertTrue(VocelloUIWait.exists(element("iosModelDownload_\(modelID)"), timeout: 300))
        XCTAssertFalse(element("iosModelProgress_\(modelID)").exists)
    }

    private func removeModel(modelID: String) {
        let remove = element("iosModelDelete_\(modelID)")
        XCTAssertTrue(VocelloUIWait.exists(remove, timeout: 120))
        XCTAssertTrue(revealSettingsElement(remove, swipingUp: modelID == "pro_clone"))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: remove, timeout: 20))
        let confirm = element("deleteModelSheet_confirm")
        XCTAssertTrue(VocelloUIWait.exists(confirm, timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: confirm, timeout: 20))
        XCTAssertTrue(VocelloUIWait.exists(element("iosModelDownload_\(modelID)"), timeout: 300))
    }

    /// A multi-gigabyte transfer may legitimately run for a long time, but it
    /// must continue advancing. Complete logical byte accounting without an
    /// installed row is not success: the 2026-08-21 device proof reproduced
    /// that exact finalization stall after background-session adoption. End the
    /// wait after five minutes without visible progress, capture the row, and
    /// let the caller clean the isolated root through its visible controls.
    private func waitForInstalledModel(
        modelID: String,
        progress: XCUIElement,
        initialProgress: Double = 0,
        timeout: TimeInterval = 3_600,
        stallTimeout: TimeInterval = 300
    ) -> String? {
        let installed = element("iosModelDelete_\(modelID)")
        var highestProgress = max(initialProgress, progressFraction(progress))
        var lastAdvance = Date()
        var terminalFailureAction: String?

        let reachedInstalledOrStalled = VocelloUIWait.condition(
            "isolated \(modelID) to install or expose a \(Int(stallTimeout))s progress stall",
            timeout: timeout
        ) {
            if installed.exists { return true }
            // A transfer can replace its progress element with a terminal recovery action
            // between the `exists` and `value` snapshots used by `observeProgress`. Detect
            // those states first so a real downloader failure is reported as such instead
            // of producing an XCUITest query-race failure with no causal diagnosis.
            for action in ["Retry", "Repair", "Download"] {
                if self.element("iosModel\(action)_\(modelID)").exists {
                    terminalFailureAction = action
                    return true
                }
            }
            let currentProgress = self.observeProgress(modelID: modelID)
            if currentProgress > highestProgress + 0.000_1 {
                highestProgress = currentProgress
                lastAdvance = Date()
            }
            self.observeIndeterminatePhase(modelID: modelID)
            if installed.exists { return true }
            return Date().timeIntervalSince(lastAdvance) >= stallTimeout
        }
        guard reachedInstalledOrStalled else {
            return "isolated \(modelID) did not install within \(Int(timeout))s"
        }
        if let terminalFailureAction {
            VocelloUIScreenshot.attach(app, named: "ios-model-download-terminal-\(modelID)")
            return "isolated \(modelID) exposed terminal \(terminalFailureAction) before Ready "
                + "(highest progress \(highestProgress))"
        }
        guard installed.exists else {
            VocelloUIScreenshot.attach(app, named: "ios-model-download-stalled-\(modelID)")
            return "isolated \(modelID) made no visible progress for \(Int(stallTimeout))s "
                + "and never exposed Ready/Delete (highest progress \(highestProgress))"
        }
        return nil
    }

    @discardableResult
    private func observeProgress(modelID: String) -> Double {
        let progress = element("iosModelProgress_\(modelID)")
        guard let sample = progressSample(progress) else { return 0 }
        let crossedThresholds = [1, 25, 50, 75, 95].filter { threshold in
            // Catalog-byte progress can jump directly from an incomplete sample to 100% when
            // the final range lands. Capture the 95% visual checkpoint from the first honest
            // incomplete sample in its five-point band instead of inventing a determinate value
            // or missing the checkpoint when there is no callback in [0.95, 1.0).
            let target = switch threshold {
            case 1: 0.000_1
            case 95: 0.90
            default: Double(threshold) / 100
            }
            return sample.fraction >= target
                && sample.fraction < 1
                && !capturedProgressMilestones[modelID, default: []].contains(threshold)
        }
        guard !crossedThresholds.isEmpty else { return sample.fraction }
        let screenshot = app.screenshot()
        for threshold in crossedThresholds {
            capturedProgressMilestones[modelID, default: []].insert(threshold)
            recordObservation(
                modelID: modelID,
                milestone: "transfer-\(threshold)",
                progressSample: sample,
                screenshot: screenshot
            )
        }
        return sample.fraction
    }

    private func observeIndeterminatePhase(modelID: String) {
        guard element("iosModelPhaseActivity_\(modelID)").exists else { return }
        let status = accessibilityText(element("iosModelStatus_\(modelID)")) ?? "finishing"
        let phase = status.lowercased().replacingOccurrences(of: " ", with: "-")
        guard capturedPhases[modelID, default: []].insert(phase).inserted else { return }
        recordObservation(modelID: modelID, milestone: phase)
    }

    private func recordObservation(
        modelID: String,
        milestone: String,
        progressSample suppliedProgressSample: ProgressSample? = nil,
        screenshot suppliedScreenshot: XCUIScreenshot? = nil
    ) {
        let progress = element("iosModelProgress_\(modelID)")
        let sampledProgress = suppliedProgressSample ?? progressSample(progress)
        let progressExists = sampledProgress != nil
        // Finalization can replace the activity/detail elements with Ready while this
        // observation is being assembled. Take one throwable snapshot per element and
        // consume that immutable value instead of issuing an `exists` query followed by
        // a second `frame`, `value`, or `label` query against a disappearing SwiftUI node.
        let activitySnapshot = progressExists
            ? nil
            : stableSnapshot(element("iosModelPhaseActivity_\(modelID)"))
        let rowSnapshot = stableSnapshot(element("iosModelRow_\(modelID)"))
        let measuredFrame = sampledProgress?.frame
            ?? activitySnapshot?.frame
            ?? .zero
        let rowFrame = rowSnapshot?.frame ?? .zero
        // A supplied transfer sample is an immutable observation of UI state that may already
        // have advanced to finalization while screenshots are attached. Never re-query mutable
        // progress-detail, status, or action elements for each crossed milestone: a fast transfer
        // can remove those elements between otherwise identical records.
        let detail = sampledProgress?.visibleText
            ?? accessibilityText(element("iosModelProgressDetail_\(modelID)"))
        let status = sampledProgress == nil
            ? accessibilityText(element("iosModelStatus_\(modelID)"))
            : "Downloading"
        let byteValues = (
            raw: sampledProgress?.rawBytes,
            total: sampledProgress?.totalBytes
        )
        let accessibilityFraction = sampledProgress?.fraction
        let expectedFraction: Double? = {
            guard let raw = byteValues.raw, let total = byteValues.total, total > 0 else { return nil }
            return min(max(Double(raw) / Double(total), 0), 1)
        }()
        let actions: [String]
        if sampledProgress != nil {
            actions = ["Cancel"]
        } else {
            let actionNames = ["Download", "Update", "Cancel", "Repair", "Retry", "Delete"]
            actions = actionNames.filter { element("iosModel\($0)_\(modelID)").exists }
        }
        let safeMilestone = milestone.replacingOccurrences(of: " ", with: "-")
        let rowScreenshot = "ios-model-row-\(modelID)-\(safeMilestone)"
        let progressScreenshot = measuredFrame.width > 0 && measuredFrame.height > 0
            ? "ios-model-progress-\(modelID)-\(safeMilestone)"
            : nil
        let screenshot = suppliedScreenshot ?? app.screenshot()
        let appFrame = app.frame
        if rowFrame.width > 0 && rowFrame.height > 0 {
            _ = VocelloUIScreenshot.attach(
                screenshot,
                appFrame: appFrame,
                cropping: rowFrame,
                named: rowScreenshot
            )
        } else if suppliedScreenshot == nil {
            VocelloUIScreenshot.attach(app, named: rowScreenshot)
        }
        if let progressScreenshot {
            _ = VocelloUIScreenshot.attach(
                screenshot,
                appFrame: appFrame,
                cropping: measuredFrame,
                named: progressScreenshot
            )
        }
        let observation = UIObservation(
            schemaVersion: 1,
            capturedAtUTC: ISO8601DateFormatter().string(from: Date()),
            modelID: modelID,
            milestone: milestone,
            rawBytes: byteValues.raw,
            totalBytes: byteValues.total,
            expectedFraction: expectedFraction,
            accessibilityFraction: accessibilityFraction,
            visibleText: detail,
            status: status,
            phase: progressExists ? "transfer" : (status ?? "terminal").lowercased(),
            actions: actions,
            elementFrame: Frame(measuredFrame),
            rowFrame: Frame(rowFrame),
            progressScreenshot: progressScreenshot,
            rowScreenshot: rowScreenshot
        )
        guard let data = try? JSONEncoder().encode(observation) else { return }
        print("VOCELLO_MODEL_OBSERVATION=\(data.base64EncodedString())")
    }

    private func accessibilityText(_ element: XCUIElement) -> String? {
        guard let snapshot = stableSnapshot(element) else { return nil }
        if let value = snapshot.value, !value.isEmpty { return value }
        return snapshot.label.isEmpty ? nil : snapshot.label
    }

    private func parseByteAccessibilityValue(_ value: String?) -> (raw: Int64?, total: Int64?) {
        guard let value else { return (nil, nil) }
        let numbers = value.split(whereSeparator: { !$0.isNumber }).compactMap { Int64($0) }
        guard numbers.count >= 3 else { return (nil, nil) }
        return (numbers[numbers.count - 2], numbers[numbers.count - 1])
    }

    private func progressSample(_ element: XCUIElement) -> ProgressSample? {
        guard let snapshot = stableSnapshot(element), let value = snapshot.value else { return nil }
        let byteValues = parseByteAccessibilityValue(value)
        guard let rawBytes = byteValues.raw,
              let totalBytes = byteValues.total,
              totalBytes > 0 else {
            return nil
        }
        return ProgressSample(
            rawBytes: rawBytes,
            totalBytes: totalBytes,
            fraction: progressFraction(value),
            frame: snapshot.frame,
            visibleText: value
        )
    }

    private struct StableElementSnapshot {
        let value: String?
        let label: String
        let frame: CGRect
    }

    private func stableSnapshot(_ element: XCUIElement) -> StableElementSnapshot? {
        guard let snapshot = try? element.snapshot() else { return nil }
        return StableElementSnapshot(
            value: snapshot.value as? String,
            label: snapshot.label,
            frame: snapshot.frame
        )
    }

    private func modelManagementEnvironment() -> [String: String] {
        var environment = ["QVOICE_APP_SUPPORT_DIR": isolatedSupportRoot]
        let runner = ProcessInfo.processInfo.environment
        if let runID = runner["QVOICE_IOS_MODEL_MANAGEMENT_RUN_ID"], !runID.isEmpty {
            environment["QVOICE_IOS_MODEL_MANAGEMENT_RUN_ID"] = runID
        }
        return environment
    }

    /// The redesigned model row must communicate one textual status and only
    /// the action valid for that state. Stable identifiers make this assertion
    /// independent of layout, wrapping, and Dynamic Type reflow.
    private func assertModelActionContract(
        modelID: String,
        status: String,
        expectedAction: String
    ) {
        let statusElement = element("iosModelStatus_\(modelID)")
        XCTAssertTrue(VocelloUIWait.exists(statusElement, timeout: 60))
        XCTAssertTrue(VocelloUIWait.value(statusElement, contains: status, timeout: 30))

        let actions = ["Download", "Update", "Cancel", "Repair", "Retry", "Delete"]
        for action in actions {
            let control = element("iosModel\(action)_\(modelID)")
            if action == expectedAction {
                XCTAssertTrue(VocelloUIWait.exists(control, timeout: 60))
                XCTAssertTrue(revealSettingsElement(control, swipingUp: modelID == "pro_clone"))
                XCTAssertTrue(control.isHittable)
            } else {
                XCTAssertFalse(
                    control.exists,
                    "\(status) \(modelID) must not expose the \(action) action"
                )
            }
        }
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
        return progressFraction(element.value)
    }

    private func progressFraction(_ value: Any?) -> Double {
        if let number = value as? NSNumber {
            return number.doubleValue
        }
        guard let value = value as? String else { return 0 }
        let firstToken = value.split(separator: "—", maxSplits: 1).first.map(String.init) ?? value
        let numeric = firstToken
            .replacingOccurrences(of: "%", with: "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard let parsed = Double(numeric) else { return 0 }
        return firstToken.contains("%") ? parsed / 100 : parsed
    }
}
