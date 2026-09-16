import AppKit
import ApplicationServices
import XCTest

/// Pins the app's window to an exact frame, so a capture or a layout assertion
/// knows the width it ran at.
///
/// macOS XCUITest has no window-resize API. The only native mechanism is an
/// edge drag, which `VocelloMacPerfUITests.test08WindowResize` documents as the
/// flakiest surface in this suite and which targets no particular size. Every
/// lane and every marketing capture has therefore run at whatever size the
/// scene happened to restore to, which is why the narrow-window defects of this
/// plan — a chip row overflowing, "Aiden" truncating to "Aid…", a meta row
/// stacking "Clear" into single letters, a clipped toolbar — were all found by
/// eye and none by a test.
///
/// This writes `kAXPositionAttribute` and `kAXSizeAttribute` on the app's main
/// window through the public accessibility API. It drives the same window the
/// runner already drives, so it is not a second UI route: no coordinates are
/// synthesized, no control is actuated, and nothing in the shipping app knows
/// it happened. `isAvailable` answers honestly when the accessibility handle is
/// missing, rather than letting a caller believe an unpinned window was pinned.
@MainActor
enum VocelloUIWindowFrame {
    /// The widths the app is designed against. A UI test target cannot import
    /// the app module, so these restate `MacShellMetrics.windowMinSize`,
    /// `.windowDefaultSize` and `.compactBreakpoint`; `MacShellMetrics` owns
    /// them and this comment is the link.
    enum Width {
        /// `MacShellMetrics.windowMinSize.width` — below the 860 pt compact
        /// breakpoint, so the composer chip rows wrap here.
        static let minimum: CGFloat = 720
        /// `MacShellMetrics.windowDefaultSize.width` — just above the compact
        /// breakpoint, which is why the default window has never shown a
        /// compact defect.
        static let standard: CGFloat = 880
        /// A wide desktop, where the content caps (Studio 640, library 960)
        /// are the only thing still bounding the column.
        static let wide: CGFloat = 1280
    }

    enum Height {
        /// `MacShellMetrics.windowMinSize.height`.
        static let minimum: CGFloat = 560
        /// `MacShellMetrics.windowDefaultSize.height`.
        static let standard: CGFloat = 640
        static let tall: CGFloat = 800
    }

    /// True when the accessibility API can reach the app's window. False means
    /// the runner has no accessibility grant, or the app has no window yet.
    static func isAvailable() -> Bool { mainWindow() != nil }

    /// Why `isAvailable` said what it said. The three failure modes are not
    /// interchangeable -- an untrusted runner is a machine setup problem, a
    /// missing process is a launch problem, and an AX error on a found process
    /// is an API problem -- and a bare false cannot tell them apart.
    static func diagnosis() -> String {
        let trusted = AXIsProcessTrusted()
        let running = NSRunningApplication.runningApplications(
            withBundleIdentifier: VocelloPlaybackCaptureCoordinator.appBundleIdentifier
        ).filter { !$0.isTerminated }
        guard let process = running.first else {
            return "trusted=\(trusted) process=none(bundleID="
                + "\(VocelloPlaybackCaptureCoordinator.appBundleIdentifier))"
        }
        let axApp = AXUIElementCreateApplication(process.processIdentifier)
        var main: CFTypeRef?
        let mainError = AXUIElementCopyAttributeValue(axApp, kAXMainWindowAttribute as CFString, &main)
        var windows: CFTypeRef?
        let listError = AXUIElementCopyAttributeValue(axApp, kAXWindowsAttribute as CFString, &windows)
        let count = (windows as? [AXUIElement])?.count ?? -1
        return "trusted=\(trusted) pid=\(process.processIdentifier) "
            + "mainWindowError=\(mainError.rawValue) windowsError=\(listError.rawValue) windowCount=\(count)"
    }

    /// Pins the window and returns the frame it actually adopted, which is not
    /// always the frame requested: AppKit clamps a size below the scene's
    /// `minWidth`/`minHeight` rather than refusing it, and the resize lands a
    /// frame or two later. Returns nil when accessibility is unavailable.
    @discardableResult
    static func set(
        _ app: XCUIApplication,
        width: CGFloat,
        height: CGFloat = Height.standard,
        origin: CGPoint = CGPoint(x: 60, y: 60)
    ) -> CGRect? {
        guard let window = mainWindow() else { return nil }

        var position = origin
        var size = CGSize(width: width, height: height)
        guard let positionValue = AXValueCreate(.cgPoint, &position),
              let sizeValue = AXValueCreate(.cgSize, &size) else { return nil }

        // Position first: a window pinned near the top-left has room to grow to
        // the wide width without the window server clamping it to the display.
        AXUIElementSetAttributeValue(window, kAXPositionAttribute as CFString, positionValue)
        AXUIElementSetAttributeValue(window, kAXSizeAttribute as CFString, sizeValue)

        return settledFrame(of: app)
    }

    /// Pins the window, or fails the test. Use this wherever an unknown width
    /// would make the evidence meaningless — a capture that claims to be 720,
    /// or a layout assertion whose whole point is the narrow window.
    @discardableResult
    static func require(
        _ app: XCUIApplication,
        width: CGFloat,
        height: CGFloat = Height.standard,
        file: StaticString = #filePath,
        line: UInt = #line
    ) -> CGRect {
        guard let frame = set(app, width: width, height: height) else {
            VocelloUIFailureEvidence.capture(reason: "window frame could not be pinned")
            XCTFail(
                "Could not pin the window to \(Int(width)) pt: the accessibility API cannot reach it. "
                    + "Grant the test runner Accessibility in System Settings > Privacy & Security.",
                file: file,
                line: line
            )
            return .zero
        }
        // One point of tolerance: the window server rounds to backing pixels.
        XCTAssertEqual(
            frame.width, width, accuracy: 1,
            "Window settled at \(Int(frame.width)) pt, not the \(Int(width)) pt this evidence claims.",
            file: file, line: line
        )
        return frame
    }

    // MARK: - Accessibility handles

    private static func axApplication() -> AXUIElement? {
        // One copy of the app's bundle id in this target; the playback
        // capture coordinator already owns it.
        let running = NSRunningApplication.runningApplications(
            withBundleIdentifier: VocelloPlaybackCaptureCoordinator.appBundleIdentifier
        )
        guard let process = running.first(where: { !$0.isTerminated }) else { return nil }
        return AXUIElementCreateApplication(process.processIdentifier)
    }

    private static func mainWindow() -> AXUIElement? {
        guard let axApp = axApplication() else { return nil }

        var main: CFTypeRef?
        if AXUIElementCopyAttributeValue(axApp, kAXMainWindowAttribute as CFString, &main) == .success,
           let value = main,
           CFGetTypeID(value) == AXUIElementGetTypeID() {
            return (value as! AXUIElement)
        }

        // A sheet can hold main-window status while its parent is the window we
        // want to size, and a just-launched app may have no main window yet.
        var windows: CFTypeRef?
        guard AXUIElementCopyAttributeValue(axApp, kAXWindowsAttribute as CFString, &windows) == .success,
              let list = windows as? [AXUIElement] else { return nil }
        return list.first
    }

    /// Reads the frame XCUITest reports until it stops moving, because the
    /// accessibility write returns before AppKit has laid the window out.
    private static func settledFrame(of app: XCUIApplication) -> CGRect {
        let window = app.windows.firstMatch
        var previous = CGRect.null
        let deadline = Date().addingTimeInterval(3)
        while Date() < deadline {
            let current = window.frame
            if current == previous, current.width > 0 { return current }
            previous = current
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        return window.frame
    }
}
