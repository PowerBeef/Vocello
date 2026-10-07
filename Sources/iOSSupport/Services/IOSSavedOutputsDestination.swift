import Foundation
import QwenVoiceCore

/// The user-chosen "Saved outputs" destination for generated clips (iOS).
///
/// The app always keeps an internal copy of every clip in the App-Group `outputs/` store
/// (`AppPaths.outputsDir`) — History plays from it, so playback never depends on an external
/// location. On top of that, the user can pick a Files folder (any provider, including iCloud
/// Drive) via the document picker; each newly generated clip is then **also copied** there.
///
/// The folder is persisted as a security-scoped bookmark, so no app entitlement is required —
/// access is granted by the user through the picker. `nil` bookmark == "Keep in app (History)"
/// (internal only). A failed export never disrupts generation or History, but it is not silent
/// (IOS-25): the last failure is kept as `exportIssue` for the Settings row until a copy lands or
/// the user chooses or clears the folder.
public enum IOSSavedOutputsDestination {
    private static var defaults: UserDefaults { .standard }

    private enum Keys {
        static let bookmark = "vocello.ios.savedOutputs.bookmark"
        static let displayName = "vocello.ios.savedOutputs.displayName"
        static let exportIssue = "vocello.ios.savedOutputs.exportIssue"
        static let folderChoice = "vocello.ios.savedOutputs.folderChoice"
    }

    /// Why the last automatic copy did not reach the chosen folder.
    public enum ExportIssue: String, Sendable {
        /// The folder's bookmark no longer resolves (moved, deleted or access withdrawn).
        case folderUnavailable
        /// The folder resolved, but the clip could not be written into it.
        case copyFailed
        /// A Design or Clone clip finished while purchase access was still being checked, so it
        /// stayed in History (A4-01). A copy that lands once the check verifies access clears it.
        case accessUnverified
    }

    /// `UserDefaults` key for the chosen folder's display name — exposed so the Settings row can
    /// observe it with `@AppStorage` and refresh its value label reactively.
    public static let displayNameKey = Keys.displayName

    /// `UserDefaults` key for the last export issue's raw value (empty when there is none), so
    /// the Settings row can observe it with `@AppStorage`.
    public static let exportIssueKey = Keys.exportIssue

    /// The last automatic copy's failure, or `nil` once a copy landed or the folder changed.
    public static var exportIssue: ExportIssue? {
        defaults.string(forKey: Keys.exportIssue).flatMap(ExportIssue.init(rawValue:))
    }

    /// Which folder choice a copy belongs to (P10-09). Only choosing or clearing
    /// the folder moves it on. A stale bookmark's refresh rewrites the stored
    /// bookmark bytes for the same folder, so the bytes cannot tell a copy
    /// whether the user changed the folder meanwhile; this can.
    static var folderChoice: Int { defaults.integer(forKey: Keys.folderChoice) }

    private static func beginNewFolderChoice() {
        defaults.set(folderChoice &+ 1, forKey: Keys.folderChoice)
    }

    private static func recordExportIssue(_ issue: ExportIssue?) {
        if let issue {
            defaults.set(issue.rawValue, forKey: Keys.exportIssue)
        } else {
            defaults.removeObject(forKey: Keys.exportIssue)
        }
    }

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
        beginNewFolderChoice()
        recordExportIssue(nil)
    }

    /// Reset to the internal "Keep in app (History)" default (stop copying clips out).
    public static func clearFolder() {
        defaults.removeObject(forKey: Keys.bookmark)
        defaults.removeObject(forKey: Keys.displayName)
        beginNewFolderChoice()
        recordExportIssue(nil)
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
                storeRefreshedBookmark(refreshed)
            }
        }
        return url
    }

    /// A stale bookmark's replacement for the same folder: the folder choice,
    /// and every copy waiting on it, stays as it was (P10-09).
    static func storeRefreshedBookmark(_ bookmark: Data) {
        defaults.set(bookmark, forKey: Keys.bookmark)
    }

    /// App entry over the one purchase owner. A paid-mode clip that finishes before the launch
    /// entitlement scan settles is not skipped in silence (A4-01): the Settings row reports that it
    /// stayed in History, and the copy waits for that scan, a local StoreKit read that never
    /// prompts or purchases. Verified access copies it (clearing the report); a scan that finds no
    /// unlock leaves it in History, as any locked paid-mode clip stays, and ends the report.
    @MainActor @discardableResult
    static func exportIfConfigured(
        internalAudioPath: String, generationMode: String,
        purchases: IOSExportPurchaseState
    ) -> Task<Bool, Never>? {
        guard purchases.access == .checking, hasExternalFolder,
              !purchases.permits([IOSExportProvenance(generationMode: generationMode)]) else {
            return exportIfConfigured(internalAudioPath: internalAudioPath, generationMode: generationMode) {
                purchases.permits([$0])
            }
        }
        // An earlier failure stays reported; the deferred copy below clears it only if it lands.
        if exportIssue == nil { recordExportIssue(.accessUnverified) }
        let choice = folderChoice
        return Task { @MainActor in
            await purchases.refresh()
            // A folder chosen or cleared meanwhile ended this clip's report. A
            // stale bookmark refreshed by another copy is the same folder.
            guard folderChoice == choice else { return false }
            if let copy = exportIfConfigured(
                internalAudioPath: internalAudioPath, generationMode: generationMode,
                permits: { purchases.permits([$0]) }
            ) {
                return await copy.value
            }
            if purchases.access == .locked, exportIssue == .accessUnverified { recordExportIssue(nil) }
            return false
        }
    }

    /// Copy a just-generated clip into the chosen folder. No-op when the destination is "On My
    /// iPhone". Off the main actor; a failure never propagates to the caller, and it is recorded
    /// as `exportIssue` (a landed copy clears it).
    ///
    /// `permits` is the export policy for the clip's provenance: the app reaches it through the
    /// `purchases:` entry above (`IOSSavedOutputsDestination+Commerce.swift`), tests pass a fixture. Returns
    /// `nil` when nothing leaves the app (no folder, or the policy refuses), otherwise the copy task,
    /// which resolves to whether the file landed in the folder.
    @MainActor @discardableResult
    static func exportIfConfigured(
        internalAudioPath: String, generationMode: String,
        permits: (IOSExportProvenance) -> Bool
    ) -> Task<Bool, Never>? {
        // Never start a purchase, change the folder, or fail generation here.
        // Unknown/checking access keeps paid output in internal History (the
        // `purchases:` entry reports it and copies once access is verified).
        guard permits(IOSExportProvenance(generationMode: generationMode)) else { return nil }
        guard let folder = resolveFolderURL() else {
            if hasExternalFolder { recordExportIssue(.folderUnavailable) }
            return nil
        }
        let source = URL(fileURLWithPath: internalAudioPath)
        // The copy's outcome belongs to the folder it resolved; if the user clears or re-picks
        // the folder meanwhile (which clears the issue), a late result must not land on the new
        // choice. Another copy refreshing a stale bookmark is not a new choice (P10-09).
        let choice = folderChoice
        return Task.detached(priority: .utility) {
            let didAccess = folder.startAccessingSecurityScopedResource()
            defer { if didAccess { folder.stopAccessingSecurityScopedResource() } }

            let destination = folder.appendingPathComponent(source.lastPathComponent)
            var coordinationError: NSError?
            var copied = false
            // Coordinated write so iCloud-Drive destinations sync cleanly.
            // A3-01: the bytes are staged beside a same-named file in the user's folder and replace
            // it only once complete, so a failed copy never costs the user that file.
            NSFileCoordinator().coordinate(
                writingItemAt: destination,
                options: .forReplacing,
                error: &coordinationError
            ) { writeURL in
                copied = (try? StagedFileCopy.copy(from: source, to: writeURL)) != nil
            }
            let landed = copied && coordinationError == nil
            await MainActor.run {
                if folderChoice == choice {
                    recordExportIssue(landed ? nil : .copyFailed)
                }
            }
            return landed
        }
    }
}
