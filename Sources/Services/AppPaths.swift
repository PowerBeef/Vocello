import Foundation
import QwenVoiceCore
#if canImport(Darwin)
import Darwin
#endif

enum AppPaths {
    static let appSupportOverrideEnvironmentKey = "QWENVOICE_APP_SUPPORT_DIR"

    // Single package: production data lives in `QwenVoice/`. When the runtime
    // explicit process debug gate is on, dev work is isolated in `QwenVoice-Debug/` so it never
    // touches real data. (Resolved once at launch via DebugMode.isEnabled.)
    private static let defaultFolderName: String =
        DebugMode.isEnabled ? "QwenVoice-Debug" : "QwenVoice"

    static var appSupportDir: URL {
        if let overridePath = RuntimeDebugGate.value(for: appSupportOverrideEnvironmentKey)?
            .trimmingCharacters(in: .whitespacesAndNewlines),
           let validated = validatedDebugOverride(overridePath) {
            return validated
        }
        return baseApplicationSupportDir().appendingPathComponent(defaultFolderName, isDirectory: true)
    }

    /// Whether this launch writes under a registered app-support override (a UI or
    /// benchmark lane's temporary root) rather than the user's own folder.
    static var usesAppSupportOverride: Bool {
        guard let overridePath = RuntimeDebugGate.value(for: appSupportOverrideEnvironmentKey)?
            .trimmingCharacters(in: .whitespacesAndNewlines) else { return false }
        return validatedDebugOverride(overridePath) != nil
    }

    static var modelsDir: URL {
        appSupportDir.appendingPathComponent("models", isDirectory: true)
    }

    static var outputsDir: URL {
        appSupportDir.appendingPathComponent("outputs", isDirectory: true)
    }

    static var voicesDir: URL {
        appSupportDir.appendingPathComponent("voices", isDirectory: true)
    }

    static func excludeFromBackup(_ url: URL) {
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        var mutableURL = url
        try? mutableURL.setResourceValues(values)
    }

    private static func baseApplicationSupportDir() -> URL {
        FileManager.default
            .urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? URL(
                fileURLWithPath: (NSHomeDirectory() as NSString)
                    .appendingPathComponent("Library/Application Support"),
                isDirectory: true
            )
    }

    /// The shippable app is unsandboxed for MLX, so an inherited environment
    /// variable must not redirect production reads/writes to an arbitrary path.
    /// The override is available only in explicit runtime-debug sessions and
    /// must resolve to an absolute, user-owned, writable location.
    private static func validatedDebugOverride(_ rawPath: String) -> URL? {
        guard DebugMode.isEnabled,
              !rawPath.isEmpty,
              (rawPath as NSString).isAbsolutePath else {
            return nil
        }
        let candidate = URL(fileURLWithPath: rawPath, isDirectory: true)
            .standardizedFileURL
            .resolvingSymlinksInPath()
        let fileManager = FileManager.default
        let validationURL = fileManager.fileExists(atPath: candidate.path)
            ? candidate
            : candidate.deletingLastPathComponent()
        guard validationURL.path != "/",
              fileManager.isWritableFile(atPath: validationURL.path),
              let attributes = try? fileManager.attributesOfItem(atPath: validationURL.path),
              let owner = attributes[.ownerAccountID] as? NSNumber,
              owner.uint32Value == getuid() else {
            return nil
        }
        return candidate
    }
}

enum AppDefaults {
    // Mirror the data-folder isolation: when the debug toggle is on, dev
    // preferences live in a separate suite so they never pollute real prefs.
    static var store: UserDefaults {
        if DebugMode.isEnabled,
           let suite = UserDefaults(suiteName: "com.qwenvoice.app.debug") {
            return suite
        }
        return .standard
    }
}
