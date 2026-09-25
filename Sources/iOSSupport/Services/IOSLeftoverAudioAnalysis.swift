import Foundation

/// PA-30: audio that earlier iPhone History clears left in the app's private
/// storage. A clear could keep its audio ("Keep Audio Files", or the behavior
/// before PA-21), and once the rows are gone nothing in the app reaches those
/// files while backup keeps carrying them. This value-level analysis decides
/// what the one-time, confirmed removal may offer and remove; the app gathers
/// the references (`IOSLeftoverAudioCleanup`) and removes a file only through
/// the History guarded removal. iPhone only: the Mac outputs folder stays
/// untouched (maintainer decision 2026-09-24).
enum IOSLeftoverAudioAnalysis {
    /// What a folder entry is, from `lstat`: a link is never followed.
    enum Kind: Hashable, Sendable {
        case regularFile
        case directory
        case symbolicLink
        case other
    }

    struct Entry: Hashable, Sendable {
        let path: String
        let kind: Kind
        let byteCount: Int64
        /// When the content was last written.
        let modifiedAt: Date
    }

    /// The entries of the folders read, and whether every one could be read.
    struct Listing: Equatable, Sendable {
        var entries: [Entry]
        var isComplete: Bool
    }

    /// The audio the removal offers.
    struct Leftovers: Equatable, Sendable {
        let files: [Entry]

        var count: Int { files.count }
        var byteCount: Int64 { files.reduce(0) { $0 + $1.byteCount } }
    }

    enum RemovalResult: Equatable, Sendable {
        case removed
        /// Gone already, or no longer a regular file: nothing to remove.
        case absent
        case failed
    }

    struct RemovalOutcome: Equatable, Sendable {
        var removedCount = 0
        var removedByteCount: Int64 = 0
        var failedCount = 0
    }

    /// History takes, long-form projects included, are WAV files.
    static let audioExtensions: Set<String> = ["wav"]

    /// The audio nothing uses: regular WAV files last written before this app
    /// session started, whose file name no reference names. Matching names
    /// rather than whole paths keeps a file whose row recorded it under an
    /// earlier container location. `nil`, offering nothing, when the listing
    /// or the references could not be read fully (`referencedAudioPaths` nil).
    static func leftovers(
        in listing: Listing,
        referencedAudioPaths: Set<String>?,
        writtenBefore sessionStart: Date
    ) -> Leftovers? {
        guard listing.isComplete, let referencedAudioPaths else { return nil }
        let referencedNames = Set(referencedAudioPaths.map(fileName))
        let files = listing.entries.filter { entry in
            entry.kind == .regularFile
                && audioExtensions.contains((entry.path as NSString).pathExtension.lowercased())
                && entry.modifiedAt < sessionStart
                && !referencedNames.contains(fileName(entry.path))
        }
        return Leftovers(files: files.sorted { $0.path < $1.path })
    }

    /// The confirmed files that are still leftovers now and unchanged since
    /// the user confirmed them. A file that gained a reference, or was written
    /// or replaced since, is kept.
    static func removalPlan(confirmed: Leftovers, current: Leftovers) -> [Entry] {
        let current = Set(current.files)
        return confirmed.files.filter { current.contains($0) }
    }

    static func remove(
        _ plan: [Entry],
        using removeRegularFile: (String) -> RemovalResult
    ) -> RemovalOutcome {
        var outcome = RemovalOutcome()
        for entry in plan {
            switch removeRegularFile(entry.path) {
            case .removed:
                outcome.removedCount += 1
                outcome.removedByteCount += entry.byteCount
            case .absent:
                break
            case .failed:
                outcome.failedCount += 1
            }
        }
        return outcome
    }

    /// Each folder's own entries. A link is never followed and a subfolder is
    /// never entered, so nothing outside these folders is listed. A folder
    /// that does not exist has no entries, and one that is not a real
    /// directory is never read through. Anything else that cannot be read
    /// makes the listing incomplete.
    static func listing(ofDirectories directories: [URL]) -> Listing {
        var listing = Listing(entries: [], isComplete: true)
        for directory in directories {
            var info = stat()
            guard lstat(directory.path, &info) == 0 else {
                if errno != ENOENT { listing.isComplete = false }
                continue
            }
            guard (info.st_mode & S_IFMT) == S_IFDIR else { continue }
            let names: [String]
            do {
                names = try FileManager.default.contentsOfDirectory(atPath: directory.path)
            } catch {
                listing.isComplete = false
                continue
            }
            for name in names.sorted() {
                let path = directory.appendingPathComponent(name, isDirectory: false).path
                var info = stat()
                guard lstat(path, &info) == 0 else {
                    // Removed since the folder was read: gone, not damage.
                    if errno != ENOENT { listing.isComplete = false }
                    continue
                }
                listing.entries.append(Entry(
                    path: path,
                    kind: kind(of: info.st_mode),
                    byteCount: Int64(info.st_size),
                    modifiedAt: Date(
                        timeIntervalSince1970: TimeInterval(info.st_mtimespec.tv_sec)
                            + TimeInterval(info.st_mtimespec.tv_nsec) / 1_000_000_000
                    )
                ))
            }
        }
        return listing
    }

    private static func kind(of mode: mode_t) -> Kind {
        switch mode & S_IFMT {
        case S_IFREG: return .regularFile
        case S_IFDIR: return .directory
        case S_IFLNK: return .symbolicLink
        default: return .other
        }
    }

    private static func fileName(_ path: String) -> String {
        (path as NSString).lastPathComponent
    }
}
