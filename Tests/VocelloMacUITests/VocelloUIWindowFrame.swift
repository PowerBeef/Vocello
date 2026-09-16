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
        /// As wide as this display allows. The development Mac's logical screen
        /// is 1280x720 pt, so "wide" here is roughly 1220 -- the app lives in
        /// the 720-1280 band, straddling its own 860 pt compact breakpoint, and
        /// a capture names the width it actually reached.
        static let wide: CGFloat = 4000
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

    /// Asks macOS to register this runner in the Accessibility list, which is
    /// the reliable way in: the system records the calling process's exact code
    /// identity, where hand-adding the bundle records whatever identity the
    /// picker resolved and silently does nothing if the two differ.
    ///
    /// It shows a dialog, so it is opt-in through `QVOICE_AX_PROMPT=1` and
    /// never fires in an unattended run. The prompt is a no-op once trusted.
    /// Answering it does not grant anything by itself -- macOS adds the row and
    /// the toggle still has to be switched on by hand.
    @discardableResult
    static func requestTrustIfPermitted() -> Bool {
        guard ProcessInfo.processInfo.environment["QVOICE_AX_PROMPT"] == "1" else { return false }
        // The literal key, not `kAXTrustedCheckOptionPrompt`: the imported
        // constant is a global `var` and Swift 6 refuses it as shared mutable
        // state. The string is the constant's documented value.
        let options = ["AXTrustedCheckOptionPrompt": true] as CFDictionary
        return AXIsProcessTrustedWithOptions(options)
    }

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

    /// How a frame was reached, because the two mechanisms differ in precision
    /// and a reader of the evidence deserves to know which one ran.
    enum Mechanism: String {
        /// Exact, and needs the runner to hold the Accessibility grant.
        case accessibility
        /// Approximate, needs no permission, and is the only native
        /// alternative: `VocelloMacPerfUITests.test08WindowResize` proves it
        /// works and documents that an individual drag misses
        /// nondeterministically.
        case edgeDrag
    }

    /// Sizes the window as close to `width` as the machine allows and returns
    /// the frame it actually reached, never the one requested. Accessibility
    /// first because it is exact; the edge drag when the runner is untrusted,
    /// because an approximate width honestly labelled beats no evidence.
    ///
    /// Fails only when neither mechanism moved the window at all.
    @discardableResult
    static func require(
        _ app: XCUIApplication,
        width: CGFloat,
        height: CGFloat = Height.standard,
        file: StaticString = #filePath,
        line: UInt = #line
    ) -> CGRect {
        if let frame = set(app, width: width, height: height) {
            XCTAssertEqual(
                frame.width, width, accuracy: 1,
                "Window settled at \(Int(frame.width)) pt, not the \(Int(width)) pt requested.",
                file: file, line: line
            )
            print("WINDOW_FRAME mechanism=\(Mechanism.accessibility.rawValue) "
                + "requested=\(Int(width)) settled=\(Int(frame.width))x\(Int(frame.height))")
            return frame
        }

        let frame = drag(app, towardWidth: width)
        print("WINDOW_FRAME mechanism=\(Mechanism.edgeDrag.rawValue) "
            + "requested=\(Int(width)) settled=\(Int(frame.width))x\(Int(frame.height))")
        guard frame.width > 0 else {
            VocelloUIFailureEvidence.capture(reason: "window frame could not be sized")
            XCTFail(
                "Neither the accessibility API nor an edge drag could size the window.",
                file: file,
                line: line
            )
            return .zero
        }
        return frame
    }

    /// Drags the window's right edge toward a width, measuring after every
    /// attempt and stopping when it arrives or when dragging stops helping.
    ///
    /// The recipe is `VocelloMacPerfUITests.test08WindowResize`'s, including
    /// the two details that scenario needed a rewrite to find: the press goes
    /// on the right edge's midpoint, because the bottom-right corner sits
    /// inside the window's rounded corner on macOS 27 and lands on the desktop;
    /// and the cursor is parked between attempts, because a press where the
    /// previous drag released chains into a double-click that never resizes.
    ///
    /// A width beyond the display clamps at the screen edge rather than
    /// failing, which is how `Width.wide` asks for "as wide as this screen
    /// allows" without hard-coding one machine's resolution.
    static func drag(
        _ app: XCUIApplication,
        towardWidth target: CGFloat,
        maxAttempts: Int = 12,
        tolerance: CGFloat = 6
    ) -> CGRect {
        let window = app.windows.firstMatch
        guard window.exists else { return .zero }

        var stalledDrags = 0
        for _ in 0 ..< maxAttempts {
            let before = window.frame
            let delta = target - before.width
            if abs(delta) <= tolerance { return before }

            let edge = window
                .coordinate(withNormalizedOffset: CGVector(dx: 1.0, dy: 0.5))
                .withOffset(CGVector(dx: -1, dy: 0))
            edge.click(forDuration: 0.3, thenDragTo: edge.withOffset(CGVector(dx: delta, dy: 0)))

            // Wait on the window, not on the clock: the resize either lands or
            // the drag missed, and this says which as soon as it is true instead
            // of always paying for the slowest case. A miss is expected -- the
            // drag is nondeterministic -- so this uses the non-failing wait and
            // lets the loop below decide what a miss means.
            _ = VocelloUIWait.settles("window width to change", timeout: 2) {
                abs(window.frame.width - before.width) >= 1
            }
            // A press where the previous drag released chains into a
            // double-click, which never starts a resize. Parking needs no wait
            // of its own: posting the event is synchronous, and the next
            // iteration's frame query costs more latency than the cursor move.
            VocelloUICursor.park()

            // Only a width change counts; a drag that merely moved the window
            // must not read as progress.
            if abs(window.frame.width - before.width) < 1 {
                stalledDrags += 1
                // Two misses in a row while growing means the screen edge, not
                // a flaky press: that width is the widest this display has.
                if stalledDrags >= 2 { break }
            } else {
                stalledDrags = 0
            }
        }
        return window.frame
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
