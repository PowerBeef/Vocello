import Foundation
import QwenVoiceCore

/// iOS filesystem paths — the iOS counterpart to `Sources/Services/AppPaths.swift`.
///
/// Unlike macOS (which resolves a per-user `~/Library/Application Support/QwenVoice[-Debug]/`
/// directory), iOS resolves an **App Group container** (`group.com.patricedery.vocello.shared`),
/// so models, history, and saved voices live in a stable shared location. The
/// engine runs in-process (`MLXTTSEngine`); the App Group container is retained
/// so a future companion surface (widget, share extension) can read the same
/// data without migration. `QVOICE_APP_SUPPORT_DIR` may override the root only
/// when the explicit `QWENVOICE_DEBUG` runtime gate is enabled. Absolute paths
/// are accepted for diagnostics; a single safe relative component is resolved
/// beneath the app's managed Application Support root for hermetic XCUITest.
enum AppPaths {
    static let appSupportOverrideEnvironmentKey = "QVOICE_APP_SUPPORT_DIR"
    private static let defaultSharedAppGroupIdentifier = "group.com.patricedery.vocello.shared"

    static var sharedAppGroupIdentifier: String {
        guard let configured = Bundle.main.object(
            forInfoDictionaryKey: "QVoiceSharedAppGroupIdentifier"
        ) as? String else {
            return defaultSharedAppGroupIdentifier
        }
        let trimmed = configured.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !trimmed.contains("$(") else {
            return defaultSharedAppGroupIdentifier
        }
        return trimmed
    }

    static var managedAppSupportDir: URL {
        let baseDir = FileManager.default
            .urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? URL(
                fileURLWithPath: (NSHomeDirectory() as NSString)
                    .appendingPathComponent("Library/Application Support"),
                isDirectory: true
            )
        return baseDir.appendingPathComponent("Q-Voice", isDirectory: true)
    }

    static var sharedContainerDir: URL? {
        FileManager.default.containerURL(
            forSecurityApplicationGroupIdentifier: sharedAppGroupIdentifier
        )?.appendingPathComponent("Vocello", isDirectory: true)
    }

    static var isUsingSharedContainer: Bool {
        sharedContainerDir != nil
    }

    static var appSupportDir: URL {
        resolvedAppSupportDir(environment: ProcessInfo.processInfo.environment)
    }

    static func resolvedAppSupportDir(environment: [String: String]) -> URL {
        diagnosticSupportRoot(environment: environment) ?? sharedContainerDir ?? managedAppSupportDir
    }

    /// The root the registered `QVOICE_APP_SUPPORT_DIR` override selects (internal-diagnostics
    /// build under `QWENVOICE_DEBUG`): an absolute path, or one safe component beneath the managed
    /// root. Nil in distribution builds, without the gate, and for an unsafe relative value.
    static func diagnosticSupportRoot(environment: [String: String]) -> URL? {
        guard let overridePath = debugAppSupportOverride(environment: environment) else {
            return nil
        }
        if NSString(string: overridePath).isAbsolutePath {
            return URL(fileURLWithPath: overridePath, isDirectory: true)
                .standardizedFileURL
        }
        guard isSafeManagedSupportChild(overridePath) else { return nil }
        return managedAppSupportDir
            .appendingPathComponent(overridePath, isDirectory: true)
            .standardizedFileURL
    }

    /// Whether the app may open its stores. The App Group container is required, except where an
    /// isolated diagnostics root (one safe component beneath the managed root) replaces it: a
    /// device farm re-signs the app without the App Group (RF-38). An absolute diagnostics root
    /// does not, and distribution builds compile the override out, so both still need the App Group.
    static func hasUsableStorageRoot(
        environment: [String: String],
        sharedContainerAvailable: Bool
    ) -> Bool {
        sharedContainerAvailable || isolatedModelDeliverySupportRoot(environment: environment) != nil
    }

    /// Returns the only override shape that is safe to use as an isolated
    /// background-delivery namespace. Absolute diagnostic roots deliberately
    /// do not participate: their private path must never become URLSession
    /// identity, and they must not manufacture an unbounded family of sessions.
    static func isolatedModelDeliverySupportRoot(environment: [String: String]) -> String? {
        guard let overridePath = debugAppSupportOverride(environment: environment),
              !NSString(string: overridePath).isAbsolutePath,
              isSafeManagedSupportChild(overridePath) else {
            return nil
        }
        return overridePath
    }

    private static func debugAppSupportOverride(environment: [String: String]) -> String? {
        guard let value = RuntimeDebugGate.value(
            for: appSupportOverrideEnvironmentKey,
            environment: environment
        )?
            .trimmingCharacters(in: .whitespacesAndNewlines),
              !value.isEmpty else {
            return nil
        }
        return value
    }

    private static func isSafeManagedSupportChild(_ value: String) -> Bool {
        guard value != ".", value != "..", !value.isEmpty else { return false }
        let allowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "-_"))
        return value.unicodeScalars.allSatisfy { allowed.contains($0) }
    }

    static var modelsDir: URL {
        appSupportDir.appendingPathComponent("models", isDirectory: true)
    }

    static var modelDownloadRootDir: URL {
        appSupportDir.appendingPathComponent("downloads", isDirectory: true)
    }

    static var modelDownloadStagingDir: URL {
        modelDownloadRootDir.appendingPathComponent("staging", isDirectory: true)
    }

    static var modelDownloadDelegateFilesDir: URL {
        modelDownloadStagingDir.appendingPathComponent("delegate-files", isDirectory: true)
    }

    static var modelDownloadDiagnosticsDir: URL {
        appSupportDir.appendingPathComponent("diagnostics/model-downloads", isDirectory: true)
    }

    static var modelDeliveryStateFile: URL {
        modelDownloadRootDir.appendingPathComponent("ios_model_delivery_state.json", isDirectory: false)
    }

    /// Retired schema-v1 location, read only by the one-time migration.
    static var iosInFlightDownloadsFile: URL {
        modelDownloadRootDir.appendingPathComponent("ios_inflight_downloads.json", isDirectory: false)
    }

    static var outputsDir: URL {
        appSupportDir.appendingPathComponent("outputs", isDirectory: true)
    }

    static var voicesDir: URL {
        appSupportDir.appendingPathComponent("voices", isDirectory: true)
    }

    static var importedReferenceAudioDir: URL {
        appSupportDir.appendingPathComponent("cache/imported_references", isDirectory: true)
    }

    static var preparedAudioDir: URL {
        appSupportDir.appendingPathComponent("cache/prepared_audio", isDirectory: true)
    }

    static var normalizedCloneReferenceDir: URL {
        appSupportDir.appendingPathComponent("cache/normalized_clone_refs", isDirectory: true)
    }

    static var streamSessionsDir: URL {
        appSupportDir.appendingPathComponent("cache/stream_sessions", isDirectory: true)
    }

    static var nativeMLXCacheDir: URL {
        appSupportDir.appendingPathComponent("cache/native_mlx", isDirectory: true)
    }
}
