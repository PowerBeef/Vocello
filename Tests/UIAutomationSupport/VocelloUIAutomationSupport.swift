import Foundation
@preconcurrency import XCTest
#if os(iOS)
import UIKit
#endif

#if os(iOS)
@MainActor
enum VocelloUISettingsReveal {
    static func viewport(in app: XCUIApplication) -> CGRect? {
        let dock = VocelloUIWait.element(app, id: "rootTabDock")
        guard dock.exists else { return nil }
        let statusBar = app.statusBars.firstMatch
        return VocelloUIRevealRequirement.viewport(
            window: app.windows.firstMatch.frame,
            statusBar: statusBar.exists ? statusBar.frame : nil, dock: dock.frame)
    }

    static func perform(_ target: XCUIElement, in app: XCUIApplication, swipingUp: Bool,
                        requirement: VocelloUIRevealRequirement = .fullVisibility) -> Bool {
        var search = VocelloUIRevealSearch(preferred: swipingUp ? .up : .down)
        var observations: [String] = []
        var succeeded = false
        defer {
            if !succeeded {
                // Test-target evidence only. No labels, values, user content, or app hooks.
                // Keep each sampled predicate: a later screenshot cannot explain an earlier frame.
                XCTContext.runActivity(named: "Settings reveal failure") { activity in
                    let dock = VocelloUIWait.element(app, id: "rootTabDock")
                    let statusBar = app.statusBars.firstMatch
                    let finalFrames = [
                        "requirement=\(requirement); appState=\(app.state.rawValue)",
                        "finalWindow=\(app.windows.firstMatch.frame)",
                        "finalDock=\(dock.exists ? String(describing: dock.frame) : "missing")",
                        "finalStatusBar=\(statusBar.exists ? String(describing: statusBar.frame) : "missing")",
                    ]
                    let attachment = XCTAttachment(string: (finalFrames + observations).joined(separator: "\n"))
                    attachment.name = "settings-reveal-observations"
                    attachment.lifetime = .keepAlways
                    activity.add(attachment)
                }
            }
        }
        while app.state == .runningForeground {
            guard let visible = viewport(in: app) else {
                observations.append("viewport unavailable")
                return false
            }
            let frame = target.exists ? target.frame : nil
            let hittable = frame != nil && target.isHittable
            let required = frame.map { requirement.requiredFrame($0, visible: visible) }
            let geometrySatisfied = frame.map { requirement.satisfied(by: $0, visible: visible) } ?? false
            observations.append("attempt=\(search.attempts); frame=\(String(describing: frame)); "
                + "required=\(String(describing: required)); viewport=\(visible); "
                + "hittable=\(hittable); geometrySatisfied=\(geometrySatisfied)")
            if hittable && geometrySatisfied {
                succeeded = true
                return true
            }
            guard let delta = search.nextScroll(target: required, visible: visible) else {
                observations.append("scroll stopped: no progress, impossible geometry, or exhausted budget")
                return false
            }
            guard target.exists else {
                observations.append("target absent; cannot prove containing scroll view")
                return false
            }
            // Resolve the genuine containing scroll view, never the dock or an
            // arbitrary first element. Its center must be within the safe viewport.
            let containers = app.scrollViews.allElementsBoundByIndex.filter { container in
                guard container.exists, container.isHittable,
                      VocelloUIRevealRequirement.valid(container.frame),
                      visible.contains(CGPoint(x: container.frame.midX, y: container.frame.midY)) else {
                    return false
                }
                // SwiftUI Label can propagate the same identifier to its image and
                // text. Bind containment to the already resolved element's type,
                // not every descendant carrying the presentation identifier.
                let matches = container.descendants(matching: target.elementType)
                    .matching(identifier: target.identifier)
                observations.append("containerMatches=\(matches.count); targetType=\(target.elementType.rawValue)")
                return !target.identifier.isEmpty && matches.count == 1
                    && matches.element.frame == frame
            }
            guard containers.count == 1, let container = containers.first else {
                observations.append("scroll container missing, ambiguous, or dock-obscured")
                return false
            }
            // Pointer scroll events compile for iOS but fail on touch-only iPhones.
            // Text descendants are genuine visible content, not hidden test anchors.
            // Their complete frames, not just centers/hittability, must clear the dock.
            let anchors = container.staticTexts.allElementsBoundByIndex.filter {
                $0.exists && $0.isHittable
            }
            guard let index = VocelloUITouchScrollAnchor.index(
                frames: anchors.map(\.frame), visible: visible, desiredDelta: delta) else {
                observations.append("no fully visible bounded touch anchor in owning scroll view")
                return false
            }
            let anchor = anchors[index]
            observations.append("desiredDeltaY=\(delta); touchAnchorFrame=\(anchor.frame); containerFrame=\(container.frame)")
            // Persist before the event: an Objective-C XCTest exception can bypass Swift defer.
            XCTContext.runActivity(named: "Settings bounded touch scroll") { activity in
                let attachment = XCTAttachment(string: observations.joined(separator: "\n"))
                attachment.name = "settings-touch-scroll-observations"
                attachment.lifetime = .keepAlways
                activity.add(attachment)
                if delta < 0 { anchor.swipeUp(velocity: .slow) }
                else { anchor.swipeDown(velocity: .slow) }
            }
        }
        return false
    }
}
#endif

/// A per-test application session. Callers own the instance and must not share it
/// across test methods.
@MainActor
public final class VocelloUIApplicationSession {
    public let app: XCUIApplication

    public init() {
        self.app = XCUIApplication()
    }

    public init(app: XCUIApplication) {
        self.app = app
    }

    /// Starts a clean host-app process using Xcode's configured UI-test target.
    public func launch(
        environment: [String: String],
        arguments: [String] = []
    ) {
        app.terminate()
        app.launchEnvironment = environment
        app.launchArguments = arguments
        app.launch()
        VocelloUIFailureEvidence.observedApp = app
    }

    public func terminate() {
        app.terminate()
    }
}

/// On-failure diagnostics shared by every wait/action helper: a full-desktop
/// screenshot (unlike `app.screenshot()`, `XCUIScreen` captures foreign windows
/// and system permission dialogs that may be obscuring the app) plus a bounded
/// dump of the app's accessibility tree. Turns "element not hittable" timeouts
/// into one-glance diagnoses inside the xcresult.
@MainActor
public enum VocelloUIFailureEvidence {
    /// The app under observation; set by `VocelloUIApplicationSession.launch`.
    public static var observedApp: XCUIApplication?

    private static let maxTreeDumpBytes = 48_000

    public static func capture(reason: String) {
        XCTContext.runActivity(named: "Failure evidence: \(reason)") { activity in
            let desktop = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
            desktop.name = "desktop-at-failure"
            desktop.lifetime = .keepAlways
            activity.add(desktop)

            if let app = observedApp {
                var tree = app.debugDescription
                if tree.utf8.count > maxTreeDumpBytes {
                    tree = String(tree.prefix(maxTreeDumpBytes)) + "\n…[truncated]"
                }
                let dump = XCTAttachment(string: tree)
                dump.name = "element-tree-at-failure"
                dump.lifetime = .keepAlways
                activity.add(dump)
            }
        }
    }
}

/// Registers a sentinel that fires only when an UNRELATED modal blocks the
/// test's interaction (Apple, "Handling UI Interruptions"): it never dismisses
/// anything — TCC dialogs stay human-answered — but it captures desktop
/// evidence and names the blocker, so the pending action fails with a
/// diagnosis instead of a bare timeout.
@MainActor
public enum VocelloUIInterruptionSentinel {
    public static func install(on testCase: XCTestCase) {
        testCase.addUIInterruptionMonitor(withDescription: "unrelated modal UI sentinel") { element in
            var summary = element.debugDescription
            if summary.count > 300 {
                summary = String(summary.prefix(300)) + "…"
            }
            VocelloUIFailureEvidence.capture(reason: "blocked by unrelated modal UI: \(summary)")
            return false
        }
    }
}

/// Predicate-backed waits used by both Apple-platform UI-test targets.
@MainActor
public enum VocelloUIWait {
    /// Resolves an element by stable accessibility identifier. Prefer passing
    /// the genuine element `type` (and, for sheet/popover flows, a narrower
    /// `scope`) — a typed, scoped query prunes the accessibility-tree walk
    /// that makes unscoped `.any` lookups slow, and keeps snapshots small
    /// enough to succeed while the UI is animating (e.g. the recording level
    /// meter invalidates the tree ~12×/s). `.any` remains correct for
    /// identifiers SwiftUI attaches to non-obvious element classes.
    public static func element(
        _ app: XCUIApplication,
        id: String,
        type: XCUIElement.ElementType = .any,
        in scope: XCUIElement? = nil
    ) -> XCUIElement {
        let root: XCUIElement = scope ?? app
        return root.descendants(matching: type)[id].firstMatch
    }

    /// Asserts the app's window is frontmost and actually receiving hit-tests
    /// by probing a control that is always present on the platform's root
    /// screen. A failure almost always means a foreign window or a system
    /// permission dialog is covering the app; the attached desktop screenshot
    /// shows exactly what.
    @discardableResult
    public static func assertForegroundUnobstructed(
        _ app: XCUIApplication,
        probe: XCUIElement,
        timeout: TimeInterval = 10,
        file: StaticString = #filePath,
        line: UInt = #line
    ) -> Bool {
        let expectation = XCTNSPredicateExpectation(
            predicate: NSPredicate { _, _ in probe.exists && probe.isHittable },
            object: NSObject()
        )
        let unobstructed = XCTWaiter.wait(for: [expectation], timeout: timeout) == .completed
        if !unobstructed {
            VocelloUIFailureEvidence.capture(reason: "app window obscured or not frontmost")
            XCTFail(
                "App window is obscured or not receiving hit-tests — a system permission dialog "
                    + "or foreign window is likely covering it (see desktop-at-failure attachment)",
                file: file,
                line: line
            )
        }
        return unobstructed
    }

    @discardableResult
    public static func exists(
        _ element: XCUIElement,
        timeout: TimeInterval = 15,
        file: StaticString = #filePath,
        line: UInt = #line
    ) -> Bool {
        let result = element.waitForExistence(timeout: timeout)
        if !result {
            VocelloUIFailureEvidence.capture(reason: "element never existed: \(element)")
            XCTFail("Expected element to exist within \(timeout)s: \(element)", file: file, line: line)
        }
        return result
    }

    @discardableResult
    public static func disappears(
        _ element: XCUIElement,
        timeout: TimeInterval = 15,
        file: StaticString = #filePath,
        line: UInt = #line
    ) -> Bool {
        condition(
            "element to disappear: \(element)",
            timeout: timeout,
            file: file,
            line: line
        ) {
            !element.exists
        }
    }

    @discardableResult
    public static func enabled(
        _ element: XCUIElement,
        timeout: TimeInterval = 15,
        file: StaticString = #filePath,
        line: UInt = #line
    ) -> Bool {
        condition(
            "element to become enabled: \(element)",
            timeout: timeout,
            file: file,
            line: line
        ) {
            element.exists && element.isEnabled
        }
    }

    @discardableResult
    public static func value(
        _ element: XCUIElement,
        contains expected: String,
        timeout: TimeInterval = 15,
        file: StaticString = #filePath,
        line: UInt = #line
    ) -> Bool {
        condition(
            "element value to contain '\(expected)': \(element)",
            timeout: timeout,
            file: file,
            line: line
        ) {
            guard element.exists, let value = element.value as? String else { return false }
            return value.localizedCaseInsensitiveContains(expected)
        }
    }

    @discardableResult
    public static func label(
        _ element: XCUIElement,
        contains expected: String,
        timeout: TimeInterval = 15,
        file: StaticString = #filePath,
        line: UInt = #line
    ) -> Bool {
        condition(
            "element label to contain '\(expected)': \(element)",
            timeout: timeout,
            file: file,
            line: line
        ) {
            element.exists && element.label.localizedCaseInsensitiveContains(expected)
        }
    }

    /// Waits on live UI state without fixed sleeps or private test markers.
    @discardableResult
    public static func condition(
        _ description: String,
        timeout: TimeInterval,
        file: StaticString = #filePath,
        line: UInt = #line,
        evaluate: @escaping () -> Bool
    ) -> Bool {
        let anchor = NSObject()
        let predicate = NSPredicate { _, _ in evaluate() }
        let expectation = XCTNSPredicateExpectation(predicate: predicate, object: anchor)
        let result = XCTWaiter.wait(for: [expectation], timeout: timeout)
        guard result == .completed else {
            VocelloUIFailureEvidence.capture(reason: description)
            XCTFail("Timed out after \(timeout)s waiting for \(description)", file: file, line: line)
            return false
        }
        return true
    }

    /// Waits for `evaluate` like `condition`, but also gives up early when the
    /// visible `progress` signature has not changed for `stallBudget` seconds.
    /// Long generations legitimately take many minutes; a run whose UI stops
    /// changing for that long is stuck, and waiting out a 10- or 15-minute
    /// ceiling only delays the diagnosis.
    public static func progressing(
        _ description: String,
        timeout: TimeInterval,
        stallBudget: TimeInterval = 120,
        pollInterval: TimeInterval = 1.0,
        file: StaticString = #filePath,
        line: UInt = #line,
        progress: @escaping () -> String,
        evaluate: @escaping () -> Bool
    ) -> Bool {
        let started = Date()
        var lastSignature = progress()
        var lastChange = started
        while true {
            if evaluate() { return true }
            let now = Date()
            if now.timeIntervalSince(started) >= timeout {
                VocelloUIFailureEvidence.capture(reason: description)
                XCTFail("Timed out after \(timeout)s waiting for \(description)", file: file, line: line)
                return false
            }
            let signature = progress()
            if signature != lastSignature {
                lastSignature = signature
                lastChange = now
            } else if now.timeIntervalSince(lastChange) >= stallBudget {
                VocelloUIFailureEvidence.capture(reason: "\(description) (stalled)")
                XCTFail(
                    "No visible progress for \(Int(stallBudget))s while waiting for \(description) "
                    + "(last signature: \(signature))",
                    file: file, line: line
                )
                return false
            }
            RunLoop.current.run(until: Date(timeIntervalSinceNow: pollInterval))
        }
    }
}

/// Normalizes the stable boolean and English values XCTest returns for genuine
/// Toggle and Switch controls. Unknown or localized strings remain unknown so
/// callers can fail closed instead of mutating a preference blindly.
@MainActor
public enum VocelloUIToggle {
    public static func state(of toggle: XCUIElement) -> Bool? {
        state(from: toggle.value)
    }

    public static func state(from rawValue: Any?) -> Bool? {
        if let value = rawValue as? Bool { return value }
        if let value = rawValue as? NSNumber { return value.boolValue }
        guard let value = rawValue as? String else { return nil }
        switch value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
        case "1", "on", "true", "selected": return true
        case "0", "off", "false", "not selected": return false
        default: return nil
        }
    }

    /// Returns whether a primary action is required, or `nil` when XCTest's
    /// value is not trustworthy enough to make a mutation decision.
    public static func mutationRequired(currentValue: Any?, desiredState: Bool) -> Bool? {
        guard let currentState = state(from: currentValue) else { return nil }
        return currentState != desiredState
    }
}

/// Scrolls until an element becomes hittable, and says so when it never does.
/// `VocelloUIPrimaryAction` requires hittability and neither platform's tap
/// auto-scrolls. A silent `false` used to let a later, unrelated assertion
/// take the blame; every miss is now reported at the reveal site.
@MainActor
public enum VocelloUIScroll {
    #if os(macOS)
    /// Wheel-scrolls a container (e.g. the Settings form whose clone-consent
    /// toggle is deliberately last) until the element is hittable.
    @discardableResult
    public static func intoView(
        _ element: XCUIElement,
        in container: XCUIElement,
        maxAttempts: Int = 8,
        file: StaticString = #filePath,
        line: UInt = #line
    ) -> Bool {
        for _ in 0 ..< maxAttempts {
            if element.exists && element.isHittable { return true }
            container.scroll(byDeltaX: 0, deltaY: -120)
        }
        let revealed = element.exists && element.isHittable
        if !revealed {
            VocelloUIFailureEvidence.capture(reason: "reveal \(element.identifier)")
            XCTFail("Could not scroll \(element.identifier) into view after \(maxAttempts) attempts",
                    file: file, line: line)
        }
        return revealed
    }
    #else
    /// Swipes up on the surface (the app by default) until the element is
    /// hittable; the single replacement for the per-class `reveal` loops.
    @discardableResult
    public static func reveal(
        _ element: XCUIElement,
        in surface: XCUIElement,
        maxAttempts: Int = 16,
        file: StaticString = #filePath,
        line: UInt = #line
    ) -> Bool {
        for _ in 0 ..< maxAttempts {
            if element.exists && element.isHittable { return true }
            surface.swipeUp()
        }
        let revealed = element.exists && element.isHittable
        if !revealed {
            VocelloUIFailureEvidence.capture(reason: "reveal \(element.identifier)")
            XCTFail("Could not reveal \(element.identifier) after \(maxAttempts) swipes",
                    file: file, line: line)
        }
        return revealed
    }
    #endif
}

/// The platform-native primary activation gesture, always against an exact element.
@MainActor
public enum VocelloUIPrimaryAction {
    @discardableResult
    public static func perform(
        on element: XCUIElement,
        timeout: TimeInterval = 15,
        file: StaticString = #filePath,
        line: UInt = #line
    ) -> Bool {
        guard VocelloUIWait.condition(
            "element to become hittable for its primary action: \(element)",
            timeout: timeout,
            file: file,
            line: line,
            evaluate: { element.exists && element.isEnabled && element.isHittable }
        ) else {
            return false
        }

        #if os(macOS)
        element.click()
        #else
        element.tap()
        #endif
        return true
    }
}

/// Deterministic text replacement without coordinate taps or label-based queries.
@MainActor
public enum VocelloUITextEntry {
    @discardableResult
    public static func replace(
        in element: XCUIElement,
        with text: String,
        timeout: TimeInterval = 15,
        file: StaticString = #filePath,
        line: UInt = #line
    ) -> Bool {
        guard VocelloUIPrimaryAction.perform(
            on: element,
            timeout: timeout,
            file: file,
            line: line
        ) else {
            return false
        }

        #if os(macOS)
        element.typeKey("a", modifierFlags: .command)
        element.typeKey(.delete, modifierFlags: [])
        #else
        if let currentValue = element.value as? String, !currentValue.isEmpty {
            element.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: currentValue.count))
        }
        #endif
        element.typeText(text)
        return true
    }
}

#if os(macOS)
/// Cursor parking for measurement scenarios (§K): after a positioning click
/// the pointer rests on the control it clicked and Liquid Glass hover
/// effects animate at display refresh for as long as it stays there. Parking
/// at the screen corner removes the hover surface without touching the app.
public enum VocelloUICursor {
    public static func park() {
        CGEvent(
            mouseEventSource: nil,
            mouseType: .mouseMoved,
            mouseCursorPosition: CGPoint(x: 2, y: 2),
            mouseButton: .left
        )?.post(tap: .cghidEventTap)
    }
}
#endif

/// Scenario wall-clock markers for the macOS UI-perf lane. The test process
/// prints one base64 JSON line per scenario window; the runner's log capture
/// preserves it and `scripts/check_macos_ui_perf.py` joins the windows
/// against the in-app frame probe's continuous rows (same transport as the
/// bench take manifest).
public struct VocelloUIPerfScenarioMarker: Codable {
    public let schemaVersion: Int
    public let scenario: String
    public let windowStartEpochMS: Int64
    public let windowEndEpochMS: Int64
    public let actionCount: Int

    public init(scenario: String, windowStartEpochMS: Int64, windowEndEpochMS: Int64, actionCount: Int) {
        self.schemaVersion = 1
        self.scenario = scenario
        self.windowStartEpochMS = windowStartEpochMS
        self.windowEndEpochMS = windowEndEpochMS
        self.actionCount = actionCount
    }

    public func emit() {
        guard let data = try? JSONEncoder().encode(self) else { return }
        print("VOCELLO_UIPERF_SCENARIO=\(data.base64EncodedString())")
        // stdout is fully buffered under the runner's pipe; a crash later in
        // the run must not take the markers of completed scenarios with it.
        fflush(stdout)
    }
}

/// Screenshots are retained in the xcresult; no out-of-band coordinate metadata is used.
@MainActor
public enum VocelloUIScreenshot {
    public static func attach(
        _ app: XCUIApplication,
        named name: String,
        lifetime: XCTAttachment.Lifetime = .keepAlways
    ) {
        XCTContext.runActivity(named: "Screenshot: \(name)") { activity in
            let attachment = XCTAttachment(screenshot: app.screenshot())
            attachment.name = name
            attachment.lifetime = lifetime
            activity.add(attachment)
        }
    }

    public static func attach(
        _ element: XCUIElement,
        named name: String,
        lifetime: XCTAttachment.Lifetime = .keepAlways
    ) {
        guard element.exists else { return }
        XCTContext.runActivity(named: "Screenshot: \(name)") { activity in
            let attachment = XCTAttachment(screenshot: element.screenshot())
            attachment.name = name
            attachment.lifetime = lifetime
            activity.add(attachment)
        }
    }

    #if os(iOS)
    /// Captures a previously sampled element frame from a fresh app screenshot. Long-running
    /// model-delivery phases can transition between an `exists` check and `element.screenshot()`;
    /// cropping the stable application screenshot avoids turning that honest state transition
    /// into an XCUITest snapshot failure while preserving quantitative pixels for host analysis.
    @discardableResult
    public static func attach(
        _ app: XCUIApplication,
        cropping frame: CGRect,
        named name: String,
        lifetime: XCTAttachment.Lifetime = .keepAlways
    ) -> Bool {
        let appFrame = app.frame
        let screenshot = app.screenshot()
        return attach(
            screenshot,
            appFrame: appFrame,
            cropping: frame,
            named: name,
            lifetime: lifetime
        )
    }

    /// Crops multiple evidence attachments from one immutable application screenshot. Reusing
    /// the same pixels keeps row and progress evidence temporally aligned even when the transfer
    /// completes while XCTest is exporting attachments.
    @discardableResult
    public static func attach(
        _ screenshot: XCUIScreenshot,
        appFrame: CGRect,
        cropping frame: CGRect,
        named name: String,
        lifetime: XCTAttachment.Lifetime = .keepAlways
    ) -> Bool {
        guard frame.width > 0,
              frame.height > 0,
              appFrame.width > 0,
              appFrame.height > 0 else {
            return false
        }

        guard let source = screenshot.image.cgImage else { return false }
        let scaleX = CGFloat(source.width) / appFrame.width
        let scaleY = CGFloat(source.height) / appFrame.height
        let sourceBounds = CGRect(x: 0, y: 0, width: source.width, height: source.height)
        let requested = CGRect(
            x: (frame.minX - appFrame.minX) * scaleX,
            y: (frame.minY - appFrame.minY) * scaleY,
            width: frame.width * scaleX,
            height: frame.height * scaleY
        ).integral.intersection(sourceBounds)
        guard requested.width >= 1,
              requested.height >= 1,
              let cropped = source.cropping(to: requested) else {
            return false
        }

        let image = UIImage(
            cgImage: cropped,
            scale: screenshot.image.scale,
            orientation: screenshot.image.imageOrientation
        )
        XCTContext.runActivity(named: "Screenshot: \(name)") { activity in
            let attachment = XCTAttachment(image: image)
            attachment.name = name
            attachment.lifetime = lifetime
            activity.add(attachment)
        }
        return true
    }
    #endif
}

/// Canonical UI-driven benchmark corpus and ordering shared by Apple UI-test targets.
public enum VocelloUIBenchMatrix {
    public enum Mode: String, CaseIterable, Sendable {
        case custom
        case design
        case clone
    }

    public enum Length: String, CaseIterable, Sendable {
        case short
        case medium
        case long
    }

    public enum WarmState: String, Sendable {
        case cold
        case warm
    }

    public struct Take: Equatable, Sendable {
        public let mode: Mode
        public let length: Length
        public let warmState: WarmState
        public let repetition: Int
        public let text: String

        public var cellID: String {
            "\(mode.rawValue)/\(length.rawValue)/\(warmState.rawValue)#\(repetition)"
        }
    }

    public struct Configuration: Equatable, Sendable {
        public let modes: [Mode]
        public let lengths: [Length]
        public let warmRepetitions: Int

        public init(
            modes: [Mode] = Mode.allCases,
            lengths: [Length] = Length.allCases,
            warmRepetitions: Int = 3
        ) throws {
            guard !modes.isEmpty else { throw ConfigurationError.emptyModes }
            guard !lengths.isEmpty else { throw ConfigurationError.emptyLengths }
            guard Set(modes.map(\.rawValue)).count == modes.count else {
                throw ConfigurationError.duplicateValue("mode")
            }
            guard Set(lengths.map(\.rawValue)).count == lengths.count else {
                throw ConfigurationError.duplicateValue("length")
            }
            guard warmRepetitions >= 1 else {
                throw ConfigurationError.invalidWarmRepetitions(warmRepetitions)
            }
            self.modes = modes
            self.lengths = lengths
            self.warmRepetitions = warmRepetitions
        }

        public init(
            environment: [String: String],
            keyPrefix: String
        ) throws {
            let modes = try Self.parseList(
                environment["\(keyPrefix)_MODES"],
                defaultValue: Mode.allCases,
                type: Mode.self,
                kind: "mode"
            )
            let lengths = try Self.parseList(
                environment["\(keyPrefix)_LENGTHS"],
                defaultValue: Length.allCases,
                type: Length.self,
                kind: "length"
            )
            let warm: Int
            if let raw = environment["\(keyPrefix)_WARM"], !raw.isEmpty {
                guard let parsed = Int(raw) else { throw ConfigurationError.invalidInteger(raw) }
                warm = parsed
            } else {
                warm = 3
            }
            try self.init(modes: modes, lengths: lengths, warmRepetitions: warm)
        }

        private static func parseList<Value: RawRepresentable>(
            _ raw: String?,
            defaultValue: [Value],
            type: Value.Type,
            kind: String
        ) throws -> [Value] where Value.RawValue == String {
            guard let raw, !raw.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                return defaultValue
            }
            return try raw.split(separator: ",").map { component in
                let value = String(component).trimmingCharacters(in: .whitespacesAndNewlines)
                guard let parsed = Value(rawValue: value) else {
                    throw ConfigurationError.unknownValue(kind: kind, value: value)
                }
                return parsed
            }
        }
    }

    public enum ConfigurationError: Error, CustomStringConvertible {
        case emptyModes
        case emptyLengths
        case duplicateValue(String)
        case invalidWarmRepetitions(Int)
        case invalidInteger(String)
        case unknownValue(kind: String, value: String)

        public var description: String {
            switch self {
            case .emptyModes:
                return "benchmark mode list is empty"
            case .emptyLengths:
                return "benchmark length list is empty"
            case .duplicateValue(let kind):
                return "benchmark \(kind) list contains a duplicate"
            case .invalidWarmRepetitions(let value):
                return "benchmark warm repetition count must be at least 1, got \(value)"
            case .invalidInteger(let value):
                return "benchmark integer is invalid: \(value)"
            case .unknownValue(let kind, let value):
                return "unknown benchmark \(kind): \(value)"
            }
        }
    }

    public static let voiceDesignBrief =
        "A warm, calm middle-aged male narrator with a clear, measured pace."
    public static let cloneVoiceID = "A_warm_elderly_woman"

    #if os(iOS)
    // This text sits exactly at 150 characters — the on-device cap in force when it
    // was chosen. The limit is 900 now (memory-qualified 2026-07-24), but the cell
    // text stays fixed so benchmark history remains comparable across the change.
    private static let longBenchmarkText =
        "The morning train slipped quietly out of the station, carrying sleepy travelers toward the coast while grey water shimmered beyond the fogged windows."
    #else
    private static let longBenchmarkText =
        "The morning train slipped quietly out of the station, carrying a handful of sleepy travelers toward the coast. Outside the fogged windows, pale fields gave way to grey water, and the rhythm of the rails settled into a steady, hypnotic hum. By the time the sun finally broke through, most of the passengers had drifted into an unhurried silence."
    #endif

    public static let corpus: [(length: Length, text: String)] = [
        (.short, "The train left the station at dawn."),
        (.medium, "The morning train slipped quietly out of the station, carrying a handful of sleepy travelers toward the coast."),
        (.long, longBenchmarkText),
    ]

    public static let defaultConfiguration = try! Configuration()

    public static let defaultTakes: [Take] = {
        let result = takes(configuration: defaultConfiguration)
        precondition(result.count == 29, "The canonical Vocello UI benchmark must contain 29 takes")
        return result
    }()

    public static func text(for length: Length) -> String {
        guard let entry = corpus.first(where: { $0.length == length }) else {
            preconditionFailure("Missing UI benchmark corpus entry for \(length.rawValue)")
        }
        return entry.text
    }

    /// Custom and Design each begin with one cold medium take. Clone has no
    /// cold take. Every selected mode then runs the configured warm length grid.
    public static func takes(configuration: Configuration) -> [Take] {
        var result: [Take] = []
        let coldLength = configuration.lengths.contains(.medium)
            ? Length.medium
            : configuration.lengths[0]

        for mode in configuration.modes {
            if mode != .clone {
                result.append(
                    Take(
                        mode: mode,
                        length: coldLength,
                        warmState: .cold,
                        repetition: 0,
                        text: text(for: coldLength)
                    )
                )
            }
            for length in configuration.lengths {
                for repetition in 0..<configuration.warmRepetitions {
                    result.append(
                        Take(
                            mode: mode,
                            length: length,
                            warmState: .warm,
                            repetition: repetition,
                            text: text(for: length)
                        )
                    )
                }
            }
        }
        return result
    }
}
