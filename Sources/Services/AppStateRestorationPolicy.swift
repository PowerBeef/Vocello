import AppKit
import Foundation

enum AppStateRestorationPolicy {
    static func allowsStateRestoration() -> Bool {
        true
    }
}

@MainActor
final class QwenVoiceApplicationDelegate: NSObject, NSApplicationDelegate {
    func applicationWillFinishLaunching(_ notification: Notification) {
        // Vocello is dark-only (matches iOS): pin the whole app — windows,
        // menus, alerts, panels, the Settings scene — to dark, ignoring the
        // system appearance. Runs before any window is shown, so there is
        // no light flash at launch.
        NSApp.appearance = NSAppearance(named: .darkAqua)
    }

    func applicationSupportsSecureRestorableState(_ app: NSApplication) -> Bool {
        true
    }

    func application(_ app: NSApplication, shouldRestoreApplicationState coder: NSCoder) -> Bool {
        AppStateRestorationPolicy.allowsStateRestoration()
    }

    func application(_ app: NSApplication, shouldSaveApplicationState coder: NSCoder) -> Bool {
        AppStateRestorationPolicy.allowsStateRestoration()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        // MAC-25: reference recordings a crash or force quit left behind; no
        // draft can point at them in a new process.
        ReferenceClipRecordingStash.removeLeftoverRecordings()
        // UI-perf lane hooks (both inert without QWENVOICE_DEBUG + their
        // registered knobs): seed History before any navigation can reach it,
        // then start the frame probe so its display link binds the first key
        // window.
        UIPerfHistorySeeder.seedIfConfigured()
        UIPerfFrameProbe.startIfConfigured()
    }

    func applicationWillTerminate(_ notification: Notification) {
        // MAC-25: recorded clips (enrollment copies and one-off Voice Cloning
        // references) do not outlive the session that recorded them.
        ReferenceClipRecordingStash.removeLeftoverRecordings()
    }
}
