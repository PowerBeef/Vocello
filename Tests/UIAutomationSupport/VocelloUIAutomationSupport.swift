import Foundation
@preconcurrency import XCTest

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
