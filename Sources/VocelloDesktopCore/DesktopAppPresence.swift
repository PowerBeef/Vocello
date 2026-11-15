import AppKit
import Darwin
import Foundation
import QwenVoiceCore

/// Whether the Vocello Mac app is running, and which data roots it may be using.
public enum DesktopAppPresence {
    public static let appBundleIdentifier = "com.qwenvoice.app"
    /// Where the app's executable sits, whatever folder holds its bundle.
    static let appExecutableSuffix = "/Vocello.app/Contents/MacOS/Vocello"

    /// Three signals, the strongest first (RF-61, audit finding C4):
    ///
    /// 1. A live engine lease of kind `app` (`EngineHostLease`). The app holds
    ///    one while a model is loading or loaded, and a held lock is seen from
    ///    any session. An app with nothing loaded holds none, so its absence
    ///    says nothing.
    /// 2. `NSRunningApplication`, which answers at once from the user's login
    ///    session but may see nothing from ssh, cron or launchd.
    /// 3. The process table, when the first two found nothing: a process whose
    ///    executable is `Vocello` inside a `Vocello.app` bundle.
    public static func isAppRunning() -> Bool {
        detectsRunningApp(
            leaseHosts: { EngineHostLease.liveHosts() },
            workspaceSeesApp: {
                !NSRunningApplication.runningApplications(withBundleIdentifier: appBundleIdentifier).isEmpty
            },
            executablePaths: runningExecutablePaths
        )
    }

    /// `isAppRunning` over the signals it is given; each is read only when the
    /// ones before it found no app.
    public static func detectsRunningApp(
        leaseHosts: () -> [EngineHostLease.Host],
        workspaceSeesApp: () -> Bool,
        executablePaths: () -> [String]
    ) -> Bool {
        if leaseHosts().contains(where: { $0.kind == "app" }) { return true }
        if workspaceSeesApp() { return true }
        return executablePaths().contains(where: isAppExecutable)
    }

    /// Whether `path` is the app's executable inside its bundle. The `vocello`
    /// command, a helper inside the bundle and a test runner are not: a name
    /// that merely contains "Vocello" never matches.
    public static func isAppExecutable(_ path: String) -> Bool {
        path.hasSuffix(appExecutableSuffix)
    }

    /// The executable path of every process the kernel lets this user name
    /// (`proc_listallpids` and `proc_pidpath`, which need no entitlement). The
    /// paths are compared in memory and never logged or stored.
    public static func runningExecutablePaths() -> [String] {
        // The kernel's count, with room for processes that start meanwhile.
        let expected = unsafe proc_listallpids(nil, 0)
        guard expected > 0 else { return [] }
        var processIDs = [pid_t](repeating: 0, count: Int(expected) + 64)
        let listed = processIDs.withMutableBufferPointer { buffer -> Int in
            guard let baseAddress = buffer.baseAddress else { return 0 }
            return unsafe Int(proc_listallpids(baseAddress, Int32(buffer.count * MemoryLayout<pid_t>.stride)))
        }
        guard listed > 0 else { return [] }
        var pathBytes = [UInt8](repeating: 0, count: 4 * Int(MAXPATHLEN))
        var paths: [String] = []
        for processID in processIDs.prefix(listed) where processID > 0 {
            let length = pathBytes.withMutableBufferPointer { buffer -> Int in
                guard let baseAddress = buffer.baseAddress else { return 0 }
                return unsafe Int(proc_pidpath(processID, baseAddress, UInt32(buffer.count)))
            }
            // Nothing for a process that ended meanwhile or that this user may not read.
            guard length > 0 else { continue }
            paths.append(String(decoding: pathBytes.prefix(length), as: UTF8.self))
        }
        return paths
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
