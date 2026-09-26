import Darwin
import Foundation

/// The running app process a folder of reference recordings belongs to
/// (MAC-25). The Mac app is unsandboxed, so every copy of it (a development
/// build, the installed release, a UI-lane launch) shares one per-user
/// temporary directory. Each process records into its own folder, named after
/// its bundle identifier, process identifier and start time, so one copy
/// clearing leftovers never reaches another copy's live capture or stash.
struct ReferenceClipRecordingOwner: Hashable, Sendable {
    let bundleIdentifier: String
    let processIdentifier: Int32
    /// Microseconds since 1970; zero when the kernel did not report it.
    let startTime: UInt64

    /// This process.
    static let current: ReferenceClipRecordingOwner = {
        let processIdentifier = ProcessInfo.processInfo.processIdentifier
        return ReferenceClipRecordingOwner(
            bundleIdentifier: Bundle.main.bundleIdentifier ?? "vocello",
            processIdentifier: processIdentifier,
            startTime: ReferenceClipRecordingOwner.startTime(ofProcess: processIdentifier) ?? 0
        )
    }()

    init(bundleIdentifier: String, processIdentifier: Int32, startTime: UInt64) {
        // Bundle identifiers are letters, digits, hyphens and periods; anything
        // else would break the folder name apart.
        let safe = bundleIdentifier.unicodeScalars.map { scalar -> Character in
            scalar.isASCII && (CharacterSet.alphanumerics.contains(scalar) || scalar == "-" || scalar == ".")
                ? Character(scalar) : "-"
        }
        self.bundleIdentifier = safe.isEmpty ? "vocello" : String(safe)
        self.processIdentifier = processIdentifier
        self.startTime = startTime
    }

    /// `<bundle identifier>_<process identifier>_<start time>`.
    var folderName: String {
        "\(bundleIdentifier)_\(processIdentifier)_\(startTime)"
    }

    /// Reads a folder name back; `nil` for anything this layout did not name.
    init?(folderName: String) {
        let parts = folderName.split(separator: "_", omittingEmptySubsequences: false)
        guard parts.count == 3,
              let processIdentifier = Int32(parts[1]), processIdentifier > 0,
              let startTime = UInt64(parts[2]) else { return nil }
        self.init(bundleIdentifier: String(parts[0]), processIdentifier: processIdentifier, startTime: startTime)
        guard self.folderName == folderName else { return nil }
    }

    /// Whether the owning process has ended: no process has its identifier,
    /// or a later process reuses it (a different start time). When the kernel
    /// cannot say, or did not report this owner's start time, the owner counts
    /// as running, so a live folder is never removed.
    var hasEnded: Bool {
        switch Self.lookUp(processIdentifier) {
        case .notRunning:
            return true
        case .running(startTime: let runningStartTime):
            return startTime != 0 && runningStartTime != 0 && runningStartTime != startTime
        case .unknown:
            return false
        }
    }

    private enum ProcessLookup {
        case running(startTime: UInt64)
        case notRunning
        case unknown
    }

    private static func startTime(ofProcess processIdentifier: Int32) -> UInt64? {
        if case .running(startTime: let startTime) = lookUp(processIdentifier), startTime != 0 {
            return startTime
        }
        return nil
    }

    /// `sysctl(KERN_PROC_PID)`: an identifier no process holds comes back empty.
    private static func lookUp(_ processIdentifier: Int32) -> ProcessLookup {
        var mib: [Int32] = [CTL_KERN, KERN_PROC, KERN_PROC_PID, processIdentifier]
        var info = kinfo_proc()
        var size = MemoryLayout<kinfo_proc>.stride
        let status = mib.withUnsafeMutableBufferPointer { mib in
            sysctl(mib.baseAddress, u_int(mib.count), &info, &size, nil, 0)
        }
        guard status == 0 else { return .unknown }
        guard size >= MemoryLayout<kinfo_proc>.stride, info.kp_proc.p_pid == processIdentifier else {
            return .notRunning
        }
        let started = info.kp_proc.p_un.__p_starttime
        return .running(
            startTime: UInt64(clamping: started.tv_sec) * 1_000_000 + UInt64(clamping: started.tv_usec)
        )
    }
}

/// Copies a finished reference-clip recording out of the recorder's temp dir before
/// `ReferenceClipRecorder.stopWithoutSaving()` runs on overlay dismissal.
///
/// MAC-25: the copies do not outlive their use. An enrollment surface removes the
/// ones it made once it closes and no save still reads them
/// (`ReferenceClipStashTracker`), on both platforms. The macOS app clears its own
/// recording folder, and those of processes that have ended, at launch and quit
/// (`removeLeftoverRecordings(anotherCopyIsRunning:)`), which also covers a clip
/// recorded as a one-off Voice Cloning reference: Mac drafts live only as long
/// as the process. The iPhone clears every earlier launch's folder at launch, so
/// a clip a crash or jetsam kill stranded does not wait for the system to purge
/// its temporary directory.
enum ReferenceClipRecordingStash {
    /// `tmp/vocello-reference-recordings`: one folder per recording process.
    static var recordingsRoot: URL {
        FileManager.default.temporaryDirectory.appendingPathComponent("vocello-reference-recordings", isDirectory: true)
    }

    /// This process's folder in `recordingsRoot`.
    static var processDirectory: URL {
        recordingsRoot.appendingPathComponent(ReferenceClipRecordingOwner.current.folderName, isDirectory: true)
    }

    /// `voice-enroll` in this process's folder: stable copies handed to
    /// enrollment and Voice Cloning.
    static var directory: URL {
        processDirectory.appendingPathComponent("voice-enroll", isDirectory: true)
    }

    /// `voice-clone-references` in this process's folder: the recorder's
    /// in-progress captures.
    static var captureDirectory: URL {
        processDirectory.appendingPathComponent("voice-clone-references", isDirectory: true)
    }

    /// `tmp/voice-enroll` and `tmp/voice-clone-references`: the flat folders
    /// earlier builds shared between every running copy. Their names are
    /// generic, so only the clips those builds wrote are removed from them
    /// (`removeLegacyRecordings(in:)`).
    static var legacyDirectories: [URL] {
        let temporaryDirectory = FileManager.default.temporaryDirectory
        return [
            temporaryDirectory.appendingPathComponent("voice-enroll", isDirectory: true),
            temporaryDirectory.appendingPathComponent("voice-clone-references", isDirectory: true),
        ]
    }

    /// Returns a stable temp copy, or `nil` if the copy failed (callers may fall back to `url`).
    static func copyToStableTemp(_ url: URL, in directory: URL = directory) -> URL? {
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let dest = directory.appendingPathComponent("\(UUID().uuidString).wav", isDirectory: false)
        do {
            try FileManager.default.copyItem(at: url, to: dest)
            return dest
        } catch {
            return nil
        }
    }

    /// Deletes `path` when it is a stash copy in `directory`; any other file,
    /// such as an imported reference, is never touched.
    static func discard(_ path: String, in directory: URL = directory) {
        let url = URL(fileURLWithPath: path).standardizedFileURL
        guard url.deletingLastPathComponent().standardizedFileURL.path
            == directory.standardizedFileURL.path else { return }
        try? FileManager.default.removeItem(at: url)
    }

    /// Removes the recordings no running copy of the app can use: this
    /// process's own folder, the folder of every process that has ended, and,
    /// when no other copy of the app is running, what an earlier build left in
    /// the flat folders it shared (they name no owner, so a running copy of
    /// that build may still hold its capture there). A running process's
    /// folder, and an entry this layout did not name, are never touched. Only
    /// at app launch (both apps) and quit (macOS), when nothing in this process
    /// references its own folder.
    ///
    /// `ownerHasEnded` defaults to the kernel's process table. The iPhone
    /// passes `{ _ in true }`: its temporary directory belongs to the one app
    /// process, and its sandbox need not answer for another identifier, which
    /// would otherwise keep every earlier launch's folder.
    static func removeLeftoverRecordings(
        anotherCopyIsRunning: Bool,
        root: URL = recordingsRoot,
        currentOwner: ReferenceClipRecordingOwner = .current,
        legacyDirectories: [URL] = ReferenceClipRecordingStash.legacyDirectories,
        ownerHasEnded: (ReferenceClipRecordingOwner) -> Bool = { $0.hasEnded },
        now: Date = Date()
    ) {
        let fileManager = FileManager.default
        let entries = (try? fileManager.contentsOfDirectory(at: root, includingPropertiesForKeys: nil)) ?? []
        for entry in entries {
            guard let owner = ReferenceClipRecordingOwner(folderName: entry.lastPathComponent) else { continue }
            if owner == currentOwner || ownerHasEnded(owner) {
                try? fileManager.removeItem(at: entry)
            }
        }
        guard !anotherCopyIsRunning else { return }
        for directory in legacyDirectories {
            removeLegacyRecordings(in: directory, now: now)
        }
    }

    /// How long an earlier build's clip must sit untouched before it goes: a
    /// capture in progress, or a copy a running copy of that build (under
    /// another bundle identifier) is saving, is far younger.
    static let legacyRecordingMinimumAge: TimeInterval = 60 * 60

    /// Clears one flat folder an earlier build shared. On the Mac it sits in
    /// the per-user temporary directory every unsandboxed app shares, and its
    /// name is generic, so only what that build wrote goes: regular files named
    /// as its stash (`<UUID>.wav`) or its recorder
    /// (`reference-<ISO 8601 time>.wav`) named them, untouched for an hour.
    /// The folder itself goes only once empty (`rmdir`), and a symbolic link in
    /// its place is never followed.
    static func removeLegacyRecordings(
        in directory: URL,
        minimumAge: TimeInterval = legacyRecordingMinimumAge,
        now: Date = Date()
    ) {
        let fileManager = FileManager.default
        guard let folder = try? directory.resourceValues(forKeys: [.isDirectoryKey, .isSymbolicLinkKey]),
              folder.isDirectory == true, folder.isSymbolicLink != true else { return }
        let keys: [URLResourceKey] = [.isRegularFileKey, .isSymbolicLinkKey, .contentModificationDateKey]
        let entries = (try? fileManager.contentsOfDirectory(at: directory, includingPropertiesForKeys: keys)) ?? []
        for entry in entries where isLegacyRecordingName(entry.lastPathComponent) {
            guard let values = try? entry.resourceValues(forKeys: Set(keys)),
                  values.isRegularFile == true, values.isSymbolicLink != true,
                  let modified = values.contentModificationDate,
                  now.timeIntervalSince(modified) >= minimumAge else { continue }
            try? fileManager.removeItem(at: entry)
        }
        _ = directory.withUnsafeFileSystemRepresentation { path in
            path.map { Darwin.rmdir($0) }
        }
    }

    /// A clip name an earlier build's stash (`<UUID>.wav`) or recorder
    /// (`reference-2026-09-26T14-03-07Z.wav`) wrote.
    static func isLegacyRecordingName(_ name: String) -> Bool {
        guard name.hasSuffix(".wav") else { return false }
        let stem = String(name.dropLast(4))
        if UUID(uuidString: stem) != nil { return true }
        guard stem.hasPrefix("reference-") else { return false }
        let stamp = stem.dropFirst("reference-".count)
        // `ISO8601DateFormatter` in UTC, with every colon made a hyphen.
        let expected = "0000-00-00T00-00-00Z"
        guard stamp.count == expected.count else { return false }
        return zip(stamp, expected).allSatisfy { character, pattern in
            pattern == "0" ? character.isASCII && character.isNumber : character == pattern
        }
    }
}

/// The stash copies one enrollment surface made (MAC-25). They are removed when
/// the surface closes, or, while a save is still reading one, when that save
/// ends; the private candidate the save staged holds its own copy.
@MainActor
final class ReferenceClipStashTracker {
    private var paths: [String] = []
    private var activeUses = 0
    private var isClosed = false
    private let discard: (String) -> Void

    init(discard: @escaping (String) -> Void = { ReferenceClipRecordingStash.discard($0) }) {
        self.discard = discard
    }

    func record(_ path: String) {
        paths.append(path)
        removeIfFinished()
    }

    func beginUse() {
        activeUses += 1
    }

    func endUse() {
        activeUses = max(0, activeUses - 1)
        removeIfFinished()
    }

    func close() {
        isClosed = true
        removeIfFinished()
    }

    private func removeIfFinished() {
        guard isClosed, activeUses == 0, !paths.isEmpty else { return }
        let finished = paths
        paths.removeAll()
        finished.forEach(discard)
    }
}
