import Foundation
import Synchronization

/// The data root the app files compiled into VocelloDesktopCore resolve as
/// `AppPaths`: the CLI's configured root (`--data-dir`, the debug override or
/// `~/Library/Application Support/QwenVoice`), never the iPhone's App Group
/// container or the Mac app's own resolution. Set once before any app file
/// reads it (`DesktopDataRoot.configure`).
public enum DesktopDataRoot {
    private static let root = Mutex<URL?>(nil)

    public static func configure(_ url: URL) {
        root.withLock { $0 = url }
    }

    static var current: URL {
        root.withLock { $0 } ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("QwenVoice", isDirectory: true)
    }
}

/// The `AppPaths` the by-path app files expect, over `DesktopDataRoot`.
enum AppPaths {
    static var appSupportDir: URL { DesktopDataRoot.current }
    static var modelsDir: URL { appSupportDir.appendingPathComponent("models", isDirectory: true) }
    static var outputsDir: URL { appSupportDir.appendingPathComponent("outputs", isDirectory: true) }
    static var voicesDir: URL { appSupportDir.appendingPathComponent("voices", isDirectory: true) }
}
