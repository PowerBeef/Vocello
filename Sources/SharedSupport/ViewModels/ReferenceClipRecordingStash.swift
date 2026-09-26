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
/// (`ReferenceClipStashTracker`), and the macOS app clears its own recording
/// folder, and those of processes that have ended, at launch and quit
/// (`removeLeftoverRecordings(anotherCopyIsRunning:)`), which also covers a clip
/// recorded as a one-off Voice Cloning reference: Mac drafts live only as long
/// as the process.
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
    /// earlier builds shared between every running copy.
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
    /// when no other copy of the app is running, the flat folders an earlier
    /// build shared (they name no owner, so a running copy of that build may
    /// still hold its capture there). A running process's folder, and an entry
    /// this layout did not name, are never touched. Only at app launch and quit
    /// on macOS, when nothing in this process references its own folder.
    static func removeLeftoverRecordings(
        anotherCopyIsRunning: Bool,
        root: URL = recordingsRoot,
        currentOwner: ReferenceClipRecordingOwner = .current,
        legacyDirectories: [URL] = ReferenceClipRecordingStash.legacyDirectories
    ) {
        let fileManager = FileManager.default
        let entries = (try? fileManager.contentsOfDirectory(at: root, includingPropertiesForKeys: nil)) ?? []
        for entry in entries {
            guard let owner = ReferenceClipRecordingOwner(folderName: entry.lastPathComponent) else { continue }
            if owner == currentOwner || owner.hasEnded {
                try? fileManager.removeItem(at: entry)
            }
        }
        guard !anotherCopyIsRunning else { return }
        for directory in legacyDirectories {
            try? fileManager.removeItem(at: directory)
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
