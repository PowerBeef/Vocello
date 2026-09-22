import Foundation

/// The file copy behind Save As. Choosing the take's own file as the
/// destination is a no-op rather than a delete-then-copy of the only copy, and
/// a failed copy never removes an existing destination: the bytes land in a
/// hidden staging file next to the destination first and replace it only once
/// they are complete.
enum MacFileSaveCopy {
    enum Outcome: Equatable {
        case copied
        case sameFile
    }

    static func copy(from source: URL, to destination: URL, fileManager: FileManager = .default) throws -> Outcome {
        if isSameFile(source, destination) { return .sameFile }
        let directory = destination.deletingLastPathComponent()
        let staging = directory.appendingPathComponent(".\(destination.lastPathComponent).vocello-save-\(UUID().uuidString)")
        try fileManager.copyItem(at: source, to: staging)
        do {
            if fileManager.fileExists(atPath: destination.path) {
                _ = try fileManager.replaceItemAt(destination, withItemAt: staging)
            } else {
                try fileManager.moveItem(at: staging, to: destination)
            }
        } catch {
            try? fileManager.removeItem(at: staging)
            throw error
        }
        return .copied
    }

    /// Same path after resolving symlinks and `..`, or, when the destination
    /// exists, the same file system object (hard links, case-only renames).
    static func isSameFile(_ first: URL, _ second: URL) -> Bool {
        let firstPath = first.standardizedFileURL.resolvingSymlinksInPath().path
        let secondPath = second.standardizedFileURL.resolvingSymlinksInPath().path
        if firstPath == secondPath { return true }
        guard
            let firstID = try? first.resourceValues(forKeys: [.fileResourceIdentifierKey]).fileResourceIdentifier,
            let secondID = try? second.resourceValues(forKeys: [.fileResourceIdentifierKey]).fileResourceIdentifier
        else { return false }
        return firstID.isEqual(secondID)
    }
}
