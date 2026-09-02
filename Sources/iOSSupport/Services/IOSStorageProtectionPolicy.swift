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
        Entry(id: "history-outbox", relativePath: "history-outbox", pathPrefix: nil, isDirectory: true, backup: .included, recursive: true),
        Entry(id: "history", relativePath: "history.sqlite", pathPrefix: "history.sqlite", isDirectory: false, backup: .included, recursive: false),
    ]

    static func apply(at root: URL, fileManager: FileManager = .default) throws {
        try fileManager.createDirectory(at: root, withIntermediateDirectories: true)

        for entry in entries {
            if let prefix = entry.pathPrefix {
                let children = try fileManager.contentsOfDirectory(
                    at: root,
                    includingPropertiesForKeys: nil,
                    options: [.skipsHiddenFiles]
                )
                for child in children where child.lastPathComponent.hasPrefix(prefix) {
                    try apply(entry, to: child, fileManager: fileManager)
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

            guard entry.recursive,
                  let enumerator = fileManager.enumerator(
                      at: url,
                      includingPropertiesForKeys: nil,
                      options: [.skipsPackageDescendants]
                  ) else {
                continue
            }
            for case let child as URL in enumerator {
                try apply(entry, to: child, fileManager: fileManager)
            }
        }
    }

    private static func apply(
        _ entry: Entry,
        to url: URL,
        fileManager: FileManager
    ) throws {
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
