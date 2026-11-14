import Darwin
import Foundation
import System

/// RF-59: the modes a user of an earlier 3.0 build had installed whose current model is not
/// installed yet: their model needs an update, not a first install. The evidence is the retired
/// install folders, and the first verified current model deletes every one of them
/// (`RetiredModelReclamation`), so the plan is recorded in a ledger beside the models
/// (`ModelUpdateLedger`) before anything is deleted, and outlives the folders it was found from.
public struct ModelUpdatePlan: Equatable, Sendable {
    public struct Entry: Codable, Equatable, Sendable {
        public let mode: GenerationMode
        /// The retired folders found for this mode when it was recorded.
        public let retiredFolders: [String]
        public let detectedAtUTC: String
        /// The user stopped this mode's update; nothing restarts it on its own.
        public var paused: Bool
        /// The class of the last update attempt's failure (`ModelUpdateFailure`), never a path or a
        /// message. Nothing restarts a failed update on its own: the user's Update or Retry clears it.
        /// Absent in a ledger written before it existed.
        public var lastFailure: String?

        public init(
            mode: GenerationMode, retiredFolders: [String], detectedAtUTC: String, paused: Bool,
            lastFailure: String? = nil
        ) {
            self.mode = mode
            self.retiredFolders = retiredFolders
            self.detectedAtUTC = detectedAtUTC
            self.paused = paused
            self.lastFailure = lastFailure
        }
    }

    public private(set) var entries: [GenerationMode: Entry]

    public init(entries: [GenerationMode: Entry] = [:]) {
        self.entries = entries
    }

    public static let empty = ModelUpdatePlan()

    public var isEmpty: Bool { entries.isEmpty }

    /// Modes whose model needs an update, in the apps' mode order.
    public var modes: [GenerationMode] {
        GenerationMode.allCases.filter { entries[$0] != nil }
    }

    /// Modes whose update may start on its own: recorded and not paused.
    public var activeModes: [GenerationMode] {
        modes.filter { entries[$0]?.paused == false }
    }

    public func needsUpdate(_ mode: GenerationMode) -> Bool {
        entries[mode] != nil
    }

    public func isPaused(_ mode: GenerationMode) -> Bool {
        entries[mode]?.paused == true
    }

    /// The last update attempt failed and waits for the user's Update or Retry.
    public func hasFailed(_ mode: GenerationMode) -> Bool {
        entries[mode]?.lastFailure != nil
    }

    /// The class of the mode's last update failure, when one is recorded (a class this build does
    /// not know reads as `.other`).
    public func failure(_ mode: GenerationMode) -> ModelUpdateFailure? {
        entries[mode]?.lastFailure.map { ModelUpdateFailure(rawValue: $0) ?? .other }
    }

    /// The change the user's Update or Retry makes before the mode's download starts: a stopped or
    /// failed mode resumes; any other needs none.
    public func changeBeforeUpdating(_ mode: GenerationMode) -> ModelUpdateLedger.Change? {
        isPaused(mode) || hasFailed(mode) ? .resume(mode) : nil
    }

    /// The change a failed download of the mode's model records: its class, for a mode the plan
    /// holds; nothing otherwise.
    public func changeAfterFailure(_ mode: GenerationMode, _ failure: ModelUpdateFailure) -> ModelUpdateLedger.Change? {
        needsUpdate(mode) ? .recordFailure(mode, failure) : nil
    }

    mutating func record(_ entry: Entry) {
        entries[entry.mode] = entry
    }

    mutating func remove(_ mode: GenerationMode) {
        entries[mode] = nil
    }

    mutating func setPaused(_ paused: Bool, for mode: GenerationMode) {
        entries[mode]?.paused = paused
    }

    mutating func setFailure(_ failure: String?, for mode: GenerationMode) {
        entries[mode]?.lastFailure = failure
    }
}

/// RF-59: why an update attempt failed, as recorded in the ledger: a class, never a path or message.
public enum ModelUpdateFailure: String, Codable, Equatable, Sendable {
    /// Not enough free space for the download.
    case space
    /// A downloaded file did not match the catalog.
    case verification
    /// The transfer failed after its retries.
    case network
    case other

    /// The class of `error` (a download or install failure), read from its type, its underlying
    /// errors and, last, its description.
    public static func classify(_ error: any Error) -> ModelUpdateFailure {
        if let download = error as? HuggingFaceDownloader.DownloadError {
            switch download {
            case .fileDownloadFailed(_, let underlying): return classify(underlying)
            case .integrityCheckFailed: return .verification
            case .httpError, .rangeUnsupported, .shortRange: return .network
            case .cancelled, .chunkAssemblyFailed, .invalidRemotePath, .invalidLocalDestination, .apiError:
                return classify(description: download.errorDescription ?? "")
            }
        }
        let nsError = error as NSError
        if nsError.domain == NSCocoaErrorDomain, nsError.code == NSFileWriteOutOfSpaceError { return .space }
        if nsError.domain == NSPOSIXErrorDomain, nsError.code == Int(ENOSPC) { return .space }
        // The cause first: a transfer that could not write its file wraps the disk's error.
        if let underlying = nsError.userInfo[NSUnderlyingErrorKey] as? NSError {
            let inner = classify(underlying)
            if inner != .other { return inner }
        }
        if nsError.domain == NSURLErrorDomain { return .network }
        return classify(description: nsError.localizedDescription)
    }

    /// The class of a failure known only by its English description (a delivery snapshot's
    /// message). Whole phrases, so a word such as "shared" never reads as a digest failure.
    public static func classify(description: String) -> ModelUpdateFailure {
        let text = description.lowercased()
        let space = ["not enough free", "not enough space", "not enough storage", "insufficient space",
                     "insufficient storage", "insufficient disk", "out of space", "no space left", "free storage",
                     "storage is full", "disk is full", "disk full"]
        if space.contains(where: { text.contains($0) }) { return .space }
        let verification = ["sha-256", "sha256", "digest", "hash mismatch", "hash does not match", "checksum",
                            "integrity", "verification", "failed to verify", "mismatch"]
        if verification.contains(where: { text.contains($0) }) { return .verification }
        return .other
    }
}

/// RF-59: the update plan's ledger, `<models>/.qwenvoice-model-update.json`, shared by every host
/// that serves the folder (the Mac app and the CLI share one; the iPhone has its own). Keyed by mode,
/// so hosts that name a mode's model differently agree. Writes take a lock beside it and replace the
/// file durably (synced before the retired folders it records are deleted); reads take none. A
/// damaged ledger is set aside and the plan rebuilt from the folders still on disk; one a newer
/// build wrote is left alone and nothing is recorded or deleted (an older app or CLI sharing the
/// Mac's folder must not erase a plan it cannot read).
public enum ModelUpdateLedger {
    public static let filename = ".qwenvoice-model-update.json"
    static let lockFilename = ".qwenvoice-model-update.lock"
    static let setAsideFilename = ".qwenvoice-model-update.unreadable.json"
    static let schemaVersion = 1

    public enum Change: Equatable, Sendable {
        case none
        case pause(GenerationMode)
        case resume(GenerationMode)
        case resumeAll
        /// An update attempt failed; `failure` is a `ModelUpdateFailure` class.
        case recordFailure(GenerationMode, ModelUpdateFailure)
    }

    public enum LedgerError: Error, Equatable, Sendable {
        case lockUnavailable(String)
        case writeFailed(String)
        /// A newer build wrote the ledger; this one records and deletes nothing.
        case newerLedger(Int)
    }

    private struct File: Codable {
        let schemaVersion: Int
        let entries: [ModelUpdatePlan.Entry]
    }

    private struct Header: Decodable {
        let schemaVersion: Int
    }

    private enum Contents {
        case absent
        case plan(ModelUpdatePlan)
        case damaged
        case newer(Int)
    }

    /// The recorded plan, without a lock and without looking for new evidence. A missing or
    /// unreadable ledger reads as empty.
    public static func read(in modelsDirectory: URL) -> ModelUpdatePlan {
        guard case .plan(let plan) = contents(at: modelsDirectory.appendingPathComponent(filename)) else {
            return .empty
        }
        return plan
    }

    /// Records every mode whose retired folders hold an earlier install, drops every mode whose
    /// current model `isInstalled`, applies `change`, and writes the result (removing the ledger once
    /// empty). Returns the plan written. Throws when the ledger cannot be written or a newer build
    /// wrote it, and a caller about to delete retired folders then deletes nothing.
    ///
    /// Takes a file lock and does a little I/O: call it off the main actor where a reclamation may
    /// hold the publication lock meanwhile, and never from inside `isInstalled` (it would wait on
    /// its own lock).
    @discardableResult
    public static func reconcile(
        models: [ModelDescriptor],
        in modelsDirectory: URL,
        isInstalled: (ModelDescriptor) -> Bool,
        change: Change = .none
    ) throws -> ModelUpdatePlan {
        try withLock(in: modelsDirectory) {
            let url = modelsDirectory.appendingPathComponent(filename)
            var plan: ModelUpdatePlan
            // What the file holds now; nil when it must be written whatever the plan (set aside).
            var recorded: ModelUpdatePlan?
            switch contents(at: url) {
            case .absent:
                plan = .empty
                recorded = .empty
            case .plan(let existing):
                plan = existing
                recorded = existing
            case .damaged:
                setAside(url, in: modelsDirectory)
                plan = .empty
                recorded = nil
            case .newer(let version):
                throw LedgerError.newerLedger(version)
            }

            let byMode = Dictionary(grouping: models.filter { !$0.retiredFolders.isEmpty }, by: \.mode)
            for mode in GenerationMode.allCases {
                guard let candidates = byMode[mode] else { continue }
                if candidates.contains(where: isInstalled) {
                    plan.remove(mode)
                    continue
                }
                guard plan.entries[mode] == nil else { continue }
                let found = Set(candidates.flatMap(\.retiredFolders))
                    .filter { holdsEarlierInstall($0, in: modelsDirectory) }
                    .sorted()
                guard !found.isEmpty else { continue }
                plan.record(.init(mode: mode, retiredFolders: found, detectedAtUTC: timestamp(), paused: false))
            }

            switch change {
            case .none:
                break
            case .pause(let mode):
                plan.setPaused(true, for: mode)
            case .resume(let mode):
                // The user's Update or Retry: neither stopped nor failed any more.
                plan.setPaused(false, for: mode)
                plan.setFailure(nil, for: mode)
            case .resumeAll:
                for mode in plan.modes {
                    plan.setPaused(false, for: mode)
                    plan.setFailure(nil, for: mode)
                }
            case .recordFailure(let mode, let failure):
                plan.setFailure(failure.rawValue, for: mode)
            }

            // A pass that changes nothing writes nothing: the launch and refresh passes stay reads.
            if plan != recorded {
                try write(plan, to: url, in: modelsDirectory)
            }
            return plan
        }
    }

    /// An earlier build's completed install: a directory holding an integrity manifest that names it,
    /// or (a build before those manifests) its weights. Downloads stage outside the install folder and
    /// activate it whole, so staging or an interrupted download never counts, nor does a stray folder.
    public static func holdsEarlierInstall(_ folder: String, in modelsDirectory: URL) -> Bool {
        let folderURL = modelsDirectory.appendingPathComponent(folder, isDirectory: true)
        guard (try? folderURL.resourceValues(forKeys: [.isDirectoryKey]))?.isDirectory == true else { return false }
        let manifestURL = folderURL.appendingPathComponent(ModelAssetIntegrityManifest.filename)
        if let data = try? Data(contentsOf: manifestURL),
           let manifest = try? JSONDecoder().decode(ModelAssetIntegrityManifest.self, from: data) {
            return manifest.targetFolder == folder
        }
        let weights = folderURL.appendingPathComponent("model.safetensors")
        return ((try? weights.resourceValues(forKeys: [.fileSizeKey]))?.fileSize ?? 0) > 0
    }

    private static func contents(at url: URL) -> Contents {
        guard FileManager.default.fileExists(atPath: url.path) else { return .absent }
        guard let data = try? Data(contentsOf: url),
              let header = try? JSONDecoder().decode(Header.self, from: data) else { return .damaged }
        guard header.schemaVersion <= schemaVersion else { return .newer(header.schemaVersion) }
        guard header.schemaVersion == schemaVersion,
              let file = try? JSONDecoder().decode(File.self, from: data) else { return .damaged }
        var plan = ModelUpdatePlan()
        for entry in file.entries { plan.record(entry) }
        return .plan(plan)
    }

    /// Replaces the ledger durably: a synced temporary file renamed over it, then the folder synced,
    /// so the record survives a crash right after the retired folders it describes are deleted.
    private static func write(_ plan: ModelUpdatePlan, to url: URL, in modelsDirectory: URL) throws {
        if plan.isEmpty {
            do {
                try FileManager.default.removeItem(at: url)
            } catch CocoaError.fileNoSuchFile {
                return
            } catch {
                throw LedgerError.writeFailed(String(describing: error))
            }
            syncFolder(modelsDirectory)
            return
        }
        let file = File(schemaVersion: schemaVersion, entries: plan.modes.compactMap { plan.entries[$0] })
        let temporary = modelsDirectory.appendingPathComponent(".\(filename).\(UUID().uuidString).tmp")
        do {
            let encoder = JSONEncoder()
            encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
            let data = try encoder.encode(file)
            let descriptor = try FileDescriptor.open(
                FilePath(temporary.path), .writeOnly,
                options: [.create, .exclusiveCreate, .closeOnExec], permissions: [.ownerReadWrite, .groupRead, .otherRead]
            )
            try descriptor.closeAfter {
                _ = try descriptor.writeAll(data)
                guard fsync(descriptor.rawValue) == 0 else { throw Errno(rawValue: errno) }
            }
            guard unsafe rename(temporary.path, url.path) == 0 else { throw Errno(rawValue: errno) }
        } catch {
            try? FileManager.default.removeItem(at: temporary)
            throw LedgerError.writeFailed(String(describing: error))
        }
        syncFolder(modelsDirectory)
    }

    /// Best effort: the rename is already visible; the sync makes it survive a crash.
    private static func syncFolder(_ folder: URL) {
        guard let descriptor = try? FileDescriptor.open(FilePath(folder.path), .readOnly, options: [.closeOnExec]) else {
            return
        }
        _ = fsync(descriptor.rawValue)
        try? descriptor.close()
    }

    private static func setAside(_ url: URL, in modelsDirectory: URL) {
        let aside = modelsDirectory.appendingPathComponent(setAsideFilename)
        try? FileManager.default.removeItem(at: aside)
        try? FileManager.default.moveItem(at: url, to: aside)
    }

    private static func timestamp() -> String {
        ISO8601DateFormatter().string(from: Date())
    }

    /// Runs `body` holding an exclusive lock on the ledger's lock file. The lock is never held while
    /// the component store's publication lock is taken.
    private static func withLock<T>(in modelsDirectory: URL, _ body: () throws -> T) throws -> T {
        do {
            try FileManager.default.createDirectory(at: modelsDirectory, withIntermediateDirectories: true)
        } catch {
            throw LedgerError.lockUnavailable(String(describing: error))
        }
        let lockPath = FilePath(modelsDirectory.appendingPathComponent(lockFilename).path)
        let descriptor: FileDescriptor
        do {
            descriptor = try FileDescriptor.open(
                lockPath, .readWrite, options: [.create, .closeOnExec, .noFollow], permissions: [.ownerReadWrite]
            )
        } catch {
            throw LedgerError.lockUnavailable(String(describing: error))
        }
        defer { try? descriptor.close() }
        while flock(descriptor.rawValue, LOCK_EX) != 0 {
            let failure = Errno(rawValue: errno)
            guard failure == .interrupted else {
                throw LedgerError.lockUnavailable(String(describing: failure))
            }
        }
        defer { _ = flock(descriptor.rawValue, LOCK_UN) }
        return try body()
    }
}
