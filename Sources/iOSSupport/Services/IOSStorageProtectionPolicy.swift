import Foundation

/// Applies the governed iOS backup and data-protection policy to the App Group tree.
///
/// `.completeUntilFirstUserAuthentication` keeps user data encrypted before the first unlock
/// after boot while preserving background URLSession delivery once the user has unlocked the
/// device. Regenerable model, staging, cache, and diagnostic trees are excluded from backup;
/// History, generated outputs, and saved voices remain eligible for backup.
enum IOSStorageProtectionPolicy {
    enum BackupDisposition: String, Equatable, Sendable {
        case inherited
        case included
        case excluded
    }

    struct Entry: Equatable, Sendable {
        let id: String
        let relativePath: String
        let pathPrefix: String?
        let isDirectory: Bool
        let backup: BackupDisposition
        let recursive: Bool
    }

    /// What one pass left unapplied (PA-21, IOS-06). A governed directory or the root that
    /// cannot be protected fails the pass; a single descendant file that cannot be updated
    /// is counted and retried on the next launch instead of stopping startup.
    struct ApplyReport: Equatable, Sendable {
        var descendantFailureCount = 0
    }

    /// A read-only (`0444`) file was made writable for its metadata update and could not be
    /// made read-only again. Always fatal, even for a descendant: continuing would leave a
    /// digest-verified model component writable. Startup shows it with Retry.
    struct ModeRestoreFailure: Error {
        let underlying: any Error
    }

    static let protectionClass = FileProtectionType.completeUntilFirstUserAuthentication

    static let entries: [Entry] = [
        Entry(id: "application-support-root", relativePath: ".", pathPrefix: nil, isDirectory: true, backup: .inherited, recursive: false),
        Entry(id: "models", relativePath: "models", pathPrefix: nil, isDirectory: true, backup: .excluded, recursive: true),
        Entry(id: "downloads", relativePath: "downloads", pathPrefix: nil, isDirectory: true, backup: .excluded, recursive: true),
        Entry(id: "cache", relativePath: "cache", pathPrefix: nil, isDirectory: true, backup: .excluded, recursive: true),
        Entry(id: "diagnostics", relativePath: "diagnostics", pathPrefix: nil, isDirectory: true, backup: .excluded, recursive: true),
        Entry(id: "outputs", relativePath: "outputs", pathPrefix: nil, isDirectory: true, backup: .included, recursive: true),
        Entry(id: "voices", relativePath: "voices", pathPrefix: nil, isDirectory: true, backup: .included, recursive: true),
        Entry(id: "voice-candidates", relativePath: "voice-candidates", pathPrefix: nil, isDirectory: true, backup: .excluded, recursive: true),
        Entry(id: "voice-transactions", relativePath: "voice-transactions", pathPrefix: nil, isDirectory: true, backup: .excluded, recursive: true),
        // Uninterpretable journals set aside by reconciliation (F-25). Backup-eligible: a
        // quarantined journal may hold the only copy of a replaced voice.
        Entry(id: "voice-transactions-quarantine", relativePath: "voice-transactions-quarantine", pathPrefix: nil, isDirectory: true, backup: .included, recursive: true),
        Entry(id: "history-outbox", relativePath: "history-outbox", pathPrefix: nil, isDirectory: true, backup: .included, recursive: true),
        Entry(id: "history", relativePath: "history.sqlite", pathPrefix: "history.sqlite", isDirectory: false, backup: .included, recursive: false),
    ]

    /// Applies the policy to the governed tree. Bootstrap runs this off the main actor
    /// (IOS-06) before the engine and the background delivery coordinator exist.
    @discardableResult
    static func apply(at root: URL, fileManager: FileManager = .default) throws -> ApplyReport {
        try fileManager.createDirectory(at: root, withIntermediateDirectories: true)
        var report = ApplyReport()

        for entry in entries {
            if let prefix = entry.pathPrefix {
                let children = try fileManager.contentsOfDirectory(
                    at: root,
                    includingPropertiesForKeys: nil,
                    options: [.skipsHiddenFiles]
                )
                for child in children where child.lastPathComponent.hasPrefix(prefix) {
                    try applyToDescendant(entry, at: child, fileManager: fileManager, report: &report)
                }
                continue
            }

            let url = entry.relativePath == "."
                ? root
                : root.appendingPathComponent(entry.relativePath, isDirectory: entry.isDirectory)
            if entry.isDirectory {
                try fileManager.createDirectory(at: url, withIntermediateDirectories: true)
            } else if !fileManager.fileExists(atPath: url.path) {
                continue
            }
            try apply(entry, to: url, fileManager: fileManager)

            // Without an error handler the enumerator skips an unreadable child and continues.
            guard entry.recursive,
                  let enumerator = fileManager.enumerator(
                      at: url,
                      includingPropertiesForKeys: nil,
                      options: [.skipsPackageDescendants]
                  ) else {
                continue
            }
            for case let child as URL in enumerator {
                try applyToDescendant(entry, at: child, fileManager: fileManager, report: &report)
            }
        }
        return report
    }

    /// A descendant whose attributes cannot be updated is counted and retried next launch;
    /// one whose read-only mode could not be restored stops the pass (`ModeRestoreFailure`).
    private static func applyToDescendant(
        _ entry: Entry,
        at url: URL,
        fileManager: FileManager,
        report: inout ApplyReport
    ) throws {
        do {
            try apply(entry, to: url, fileManager: fileManager)
        } catch let failure as ModeRestoreFailure {
            throw failure
        } catch {
            report.descendantFailureCount += 1
        }
    }

    private static func apply(
        _ entry: Entry,
        to url: URL,
        fileManager: FileManager
    ) throws {
        try withMetadataWriteAccess(at: url, fileManager: fileManager) {
            try fileManager.setAttributes(
                [.protectionKey: protectionClass],
                ofItemAtPath: url.path
            )

            guard entry.backup != .inherited else { return }
            var values = URLResourceValues()
            values.isExcludedFromBackup = entry.backup == .excluded
            var mutableURL = url
            try mutableURL.setResourceValues(values)
        }
    }

    /// Shared model-component files are intentionally published read-only (`0444`) after their
    /// digest is verified. Updating their data-protection or backup metadata still requires owner
    /// write permission on iOS. Bootstrap therefore opens the smallest possible metadata-only
    /// window and restores the exact original mode even when the metadata operation fails.
    ///
    /// The app has no second model-owning process, and this runs before the engine or background
    /// delivery coordinator is created (bootstrap awaits the pass before building either). Hard-linked replicas share the same inode and therefore
    /// return to the same immutable mode together.
    @discardableResult
    static func withMetadataWriteAccess<T>(
        at url: URL,
        fileManager: FileManager = .default,
        operation: () throws -> T
    ) throws -> T {
        let attributes = try fileManager.attributesOfItem(atPath: url.path)
        guard attributes[.type] as? FileAttributeType == .typeRegular,
              let mode = (attributes[.posixPermissions] as? NSNumber)?.intValue,
              mode & 0o200 == 0 else {
            return try operation()
        }

        try fileManager.setAttributes(
            [.posixPermissions: NSNumber(value: mode | 0o200)],
            ofItemAtPath: url.path
        )
        let result: Result<T, Error>
        do {
            result = .success(try operation())
        } catch {
            result = .failure(error)
        }
        // Restoration failure wins over the metadata result because leaving a verified model
        // component writable would violate the shared-store immutability contract.
        do {
            try fileManager.setAttributes(
                [.posixPermissions: NSNumber(value: mode)],
                ofItemAtPath: url.path
            )
        } catch {
            throw ModeRestoreFailure(underlying: error)
        }
        return try result.get()
    }
}
