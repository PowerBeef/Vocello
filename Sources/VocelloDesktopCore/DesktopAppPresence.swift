import AppKit
import Foundation
import QwenVoiceCore

/// Whether the Vocello Mac app is running, and which data roots it may be using.
public enum DesktopAppPresence {
    public static let appBundleIdentifier = "com.qwenvoice.app"

    public static func isAppRunning() -> Bool {
        !NSRunningApplication.runningApplications(withBundleIdentifier: appBundleIdentifier).isEmpty
    }

    /// The app keeps its data in `QwenVoice` (or `QwenVoice-Debug` in a debug
    /// session) under Application Support; the CLI cannot see which one a running
    /// app chose, so both count.
    public static func isAppDataRoot(_ root: URL) -> Bool {
        let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent("Library/Application Support")
        let candidates = ["QwenVoice", "QwenVoice-Debug"].map {
            support.appendingPathComponent($0, isDirectory: true).standardizedFileURL.resolvingSymlinksInPath().path
        }
        return candidates.contains(root.standardizedFileURL.resolvingSymlinksInPath().path)
    }
}
