import Foundation

/// The user-chosen "Saved outputs" destination for generated clips (iOS).
///
/// The app always keeps an internal copy of every clip in the App-Group `outputs/` store
/// (`AppPaths.outputsDir`) — History plays from it, so playback never depends on an external
/// location. On top of that, the user can pick a Files folder (any provider, including iCloud
/// Drive) via the document picker; each newly generated clip is then **also copied** there.
///
/// The folder is persisted as a security-scoped bookmark, so no app entitlement is required —
/// access is granted by the user through the picker. `nil` bookmark == "Keep in app (History)"
/// (internal only). All work here is best-effort: a failed export never disrupts generation or History.
public enum IOSSavedOutputsDestination {
    private static var defaults: UserDefaults { .standard }

    private enum Keys {
        static let bookmark = "vocello.ios.savedOutputs.bookmark"
        static let displayName = "vocello.ios.savedOutputs.displayName"
    }

    /// `UserDefaults` key for the chosen folder's display name — exposed so the Settings row can
    /// observe it with `@AppStorage` and refresh its value label reactively.
    public static let displayNameKey = Keys.displayName

    /// Whether an external folder is currently selected (vs. "Keep in app (History)").
    public static var hasExternalFolder: Bool { defaults.data(forKey: Keys.bookmark) != nil }

    /// The chosen folder's display name, or `nil` for the internal "Keep in app (History)" default.
    public static var folderDisplayName: String? { defaults.string(forKey: Keys.displayName) }

    /// The value shown on the Settings "Saved outputs" row.
    public static var summary: String { folderDisplayName ?? "Keep in app (History)" }

    /// Persist a user-picked folder (a security-scoped URL from the document picker) as a bookmark.
    public static func setFolder(_ url: URL) throws {
        let didAccess = url.startAccessingSecurityScopedResource()
        defer { if didAccess { url.stopAccessingSecurityScopedResource() } }
        // iOS bookmarks for picker URLs are implicitly security-scoped (no `.withSecurityScope`,
        // which is macOS-only).
        let bookmark = try url.bookmarkData(options: [], includingResourceValuesForKeys: nil, relativeTo: nil)
        defaults.set(bookmark, forKey: Keys.bookmark)
        defaults.set(url.lastPathComponent, forKey: Keys.displayName)
    }

    /// Reset to the internal "Keep in app (History)" default (stop copying clips out).
    public static func clearFolder() {
        defaults.removeObject(forKey: Keys.bookmark)
        defaults.removeObject(forKey: Keys.displayName)
    }

    /// Resolve the bookmarked folder, refreshing the bookmark if it has gone stale. Returns `nil`
    /// if no folder is set or the bookmark can no longer be resolved (folder deleted/moved).
    private static func resolveFolderURL() -> URL? {
        guard let data = defaults.data(forKey: Keys.bookmark) else { return nil }
        var isStale = false
        guard let url = try? URL(
            resolvingBookmarkData: data,
            options: [],
            relativeTo: nil,
            bookmarkDataIsStale: &isStale
        ) else {
            return nil
        }
        if isStale {
            let didAccess = url.startAccessingSecurityScopedResource()
            defer { if didAccess { url.stopAccessingSecurityScopedResource() } }
            if let refreshed = try? url.bookmarkData(options: [], includingResourceValuesForKeys: nil, relativeTo: nil) {
                defaults.set(refreshed, forKey: Keys.bookmark)
            }
        }
        return url
    }

    /// Copy a just-generated clip into the chosen folder. No-op when the destination is "On My
    /// iPhone". Best-effort + off the main actor — a failure here never propagates to the caller.
    ///
    /// `permits` is the export policy for the clip's provenance: the app passes the one verified
    /// StoreKit owner (`IOSSavedOutputsDestination+Commerce.swift`), tests pass a fixture. Returns
    /// `nil` when nothing leaves the app (no folder, or the policy refuses), otherwise the copy task,
    /// which resolves to whether the file landed in the folder.
    @MainActor @discardableResult
    static func exportIfConfigured(
        internalAudioPath: String, generationMode: String,
        permits: (IOSExportProvenance) -> Bool
    ) -> Task<Bool, Never>? {
        // Never start a purchase, change the folder, or fail generation here.
        // Unknown/checking access keeps paid output in internal History.
        guard permits(IOSExportProvenance(generationMode: generationMode)) else { return nil }
        guard let folder = resolveFolderURL() else { return nil }
        let source = URL(fileURLWithPath: internalAudioPath)
        return Task.detached(priority: .utility) {
            let didAccess = folder.startAccessingSecurityScopedResource()
            defer { if didAccess { folder.stopAccessingSecurityScopedResource() } }

            let destination = folder.appendingPathComponent(source.lastPathComponent)
            var coordinationError: NSError?
            var copied = false
            // Coordinated write so iCloud-Drive destinations sync cleanly.
            NSFileCoordinator().coordinate(
                writingItemAt: destination,
                options: .forReplacing,
                error: &coordinationError
            ) { writeURL in
                if FileManager.default.fileExists(atPath: writeURL.path) {
                    try? FileManager.default.removeItem(at: writeURL)
                }
                copied = (try? FileManager.default.copyItem(at: source, to: writeURL)) != nil
            }
            return copied && coordinationError == nil
        }
    }
}
