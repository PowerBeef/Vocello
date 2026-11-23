import Foundation
import QwenVoiceCore
import Synchronization
import System

/// A process hosting the engine says so with a lease: a file in one per-user
/// folder (`sharedFolder`; memory belongs to the Mac, not to a data folder) that
/// it holds locked (flock) for as long as its engine may be loaded. The lock
/// dies with the process, so a lease nobody holds is stale and is removed by the
/// next reader. The CLI (RF-27) and the Mac app (RF-61) each take a lease and
/// read the others': this file is compiled into the app and into
/// `VocelloDesktopCore`. A one-shot command holds its lease for its life; the
/// MCP server's and the app's follow their model (`EngineHostLeaseKeeper`), so
/// an app with nothing loaded holds none and the CLI still counts it by
/// `DesktopAppPresence`.
public final class EngineHostLease: Sendable {
    public struct Host: Codable, Sendable, Equatable {
        public let pid: Int32
        /// `cli` or `app`.
        public let kind: String
        public let startedAt: String

        public init(pid: Int32, kind: String, startedAt: String) {
            self.pid = pid
            self.kind = kind
            self.startedAt = startedAt
        }
    }

    public let host: Host
    private let url: URL
    private let descriptor: Mutex<FileDescriptor?>

    private init(host: Host, url: URL, descriptor: FileDescriptor) {
        self.host = host
        self.url = url
        self.descriptor = Mutex(descriptor)
    }

    deinit { release() }

    /// The per-user folder every engine host's lease lives in, whatever data
    /// folder it serves: `~/Library/Caches/com.qwenvoice.vocello/engine-hosts`.
    public static var sharedFolder: URL {
        let caches = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first
            ?? URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent("Library/Caches")
        return caches.appendingPathComponent("com.qwenvoice.vocello/engine-hosts", isDirectory: true)
    }

    /// Takes a lease for this process in `folder`. The file is written and locked
    /// under a temporary name and renamed into place, so no reader sees it unlocked.
    public static func acquire(in folder: URL = sharedFolder, kind: String) throws -> EngineHostLease {
        try FileManager.default.createDirectory(
            at: folder, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700]
        )
        let host = Host(pid: getpid(), kind: kind, startedAt: ISO8601DateFormatter().string(from: Date()))
        let name = "\(host.pid)-\(UUID().uuidString.lowercased())"
        let temporary = folder.appendingPathComponent(".\(name).tmp")
        let final = folder.appendingPathComponent("\(name).lease")
        let descriptor = try FileDescriptor.open(
            FilePath(temporary.path), .writeOnly,
            options: [.create, .exclusiveCreate, .closeOnExec], permissions: [.ownerReadWrite]
        )
        do {
            guard Self.flockRetryingEINTR(descriptor.rawValue, LOCK_EX | LOCK_NB) == 0 else {
                throw Errno(rawValue: errno)
            }
            _ = try descriptor.writeAll(try JSONEncoder().encode(host))
            guard unsafe rename(temporary.path, final.path) == 0 else { throw Errno(rawValue: errno) }
        } catch {
            try? descriptor.close()
            try? FileManager.default.removeItem(at: temporary)
            throw error
        }
        return EngineHostLease(host: host, url: final, descriptor: descriptor)
    }

    /// The hosts holding a lease in `folder`, other than `excluding`. Stale
    /// leases (their process is gone) and abandoned temporary files are removed
    /// on the way. A held lease that cannot be read still counts, as an unknown host.
    public static func liveHosts(in folder: URL = sharedFolder, excluding: EngineHostLease? = nil) -> [Host] {
        let urls = (try? FileManager.default.contentsOfDirectory(
            at: folder, includingPropertiesForKeys: [.contentModificationDateKey]
        )) ?? []
        var hosts: [Host] = []
        for url in urls {
            if url.pathExtension == "tmp" {
                // A lease whose writer died before its rename.
                let modified = (try? url.resourceValues(forKeys: [.contentModificationDateKey]))?.contentModificationDate
                if let modified, Date().timeIntervalSince(modified) > 60 { try? FileManager.default.removeItem(at: url) }
                continue
            }
            guard url.pathExtension == "lease", url.lastPathComponent != excluding?.url.lastPathComponent else { continue }
            guard let descriptor = try? FileDescriptor.open(FilePath(url.path), .readOnly, options: [.closeOnExec]) else {
                continue
            }
            if Self.flockRetryingEINTR(descriptor.rawValue, LOCK_SH | LOCK_NB) == 0 {
                // Nobody holds it: its process is gone. Close before unlinking so no
                // concurrent reader observes a locked-but-unlinked inode.
                try? descriptor.close()
                try? FileManager.default.removeItem(at: url)
                continue
            }
            // Read from the already-open descriptor rather than reopening by path
            // so a concurrent release/unlink cannot turn a live lease into pid 0 / unknown.
            let data = Self.readHostData(from: descriptor)
            try? descriptor.close()
            hosts.append(data.flatMap { try? JSONDecoder().decode(Host.self, from: $0) }
                ?? Host(pid: 0, kind: "unknown", startedAt: ""))
        }
        return hosts
    }

    /// Gives the lease up (also when the process ends). Closes the locked
    /// descriptor before unlinking the path so a concurrent reader never sees
    /// an unlinked-yet-locked inode.
    public func release() {
        guard let descriptor = self.descriptor.withLock({ held -> FileDescriptor? in
            defer { held = nil }
            return held
        }) else { return }
        try? descriptor.close()
        try? FileManager.default.removeItem(at: url)
    }

    private static func flockRetryingEINTR(_ rawValue: Int32, _ operation: Int32) -> Int32 {
        while true {
            let result = flock(rawValue, operation)
            if result == -1, Errno(rawValue: errno) == .interrupted {
                continue
            }
            return result
        }
    }

    public static func readHostData(from descriptor: FileDescriptor) -> Data? {
        let handle = FileHandle(fileDescriptor: descriptor.rawValue, closeOnDealloc: false)
        var data = Data()
        let maxBytes = 65_536
        while data.count < maxBytes {
            guard let chunk = try? handle.read(upToCount: maxBytes - data.count), !chunk.isEmpty else {
                break
            }
            data.append(chunk)
        }
        return data.isEmpty ? nil : data
    }
}

/// Whether this process may host another engine beside the ones already
/// running on its data root.
public enum EngineHostAdmission: Equatable, Sendable {
    case proceed
    /// Run, but say another engine shares this Mac's memory.
    case warn(String)
    case refuse(String)

    /// On an 8 GB Mac two engines do not fit together, so a second is refused
    /// unless the caller insists; elsewhere it is allowed with a warning. The app
    /// counts whenever it runs, whatever data folder it uses: memory is the Mac's.
    public static func decide(
        otherHosts: [EngineHostLease.Host], appRunning: Bool, deviceClass: NativeDeviceMemoryClass,
        allowConcurrent: Bool
    ) -> EngineHostAdmission {
        var names = otherHosts.map { host in
            switch host.kind {
            case "app": "the Vocello app"
            case "cli": "vocello (pid \(host.pid))"
            default: "another engine host"
            }
        }
        if appRunning, !otherHosts.contains(where: { $0.kind == "app" }) { names.append("the Vocello app") }
        guard !names.isEmpty else { return .proceed }
        let others = names.joined(separator: ", ")
        if deviceClass == .floor8GBMac, !allowConcurrent {
            return .refuse("another Vocello engine is running on this 8 GB Mac (\(others)), which holds one at a time")
        }
        return .warn("another Vocello engine is running on this Mac (\(others)); they share its memory")
    }
}

/// The Mac app's side of the leases (RF-61): what it decides from the other
/// hosts' before it deletes a model, generates or warms. `otherHosts` are the
/// live hosts other than the app's own lease.
public enum EngineHostAppPolicy {
    /// A lease names no model, so any other live host may have this one loaded:
    /// its files stay until that host has unloaded or exited, as `vocello
    /// models remove` refuses while the app or another engine runs.
    public static func refusesModelDeletion(otherHosts: [EngineHostLease.Host]) -> Bool {
        !otherHosts.isEmpty
    }

    /// `EngineHostAdmission`'s rule read from the app's side: on an 8 GB Mac a
    /// take or a warm waits while another engine holds a lease, and a larger
    /// Mac runs beside it. The app has no way to insist.
    ///
    /// Two cases never wait. An app that holds its own lease already has its
    /// model resident: it is the incumbent, refusing its next take frees no
    /// memory, and the lease it reads may be a command line's that is only
    /// asking and is about to be refused itself (a host takes its lease before
    /// it reads the others). And a tier that is forced or emulated for a
    /// diagnostic lane describes a Mac that has the memory.
    public static func refusesEngineWork(
        otherHosts: [EngineHostLease.Host], deviceClass: NativeDeviceMemoryClass,
        holdsOwnLease: Bool = false, tierIsDiagnostic: Bool = false
    ) -> Bool {
        guard !holdsOwnLease, !tierIsDiagnostic else { return false }
        if case .refuse = EngineHostAdmission.decide(
            otherHosts: otherHosts, appRunning: false, deviceClass: deviceClass, allowConcurrent: false
        ) {
            return true
        }
        return false
    }
}

/// What a host's engine publishes about its model, as far as its lease goes.
public enum EngineHostModelPresence: Equatable, Sendable {
    /// A model is loading, loaded, generating or being primed.
    case present
    /// Nothing is loaded.
    case absent
    /// A failure is published. Weights it left resident unload after the tier's
    /// idle window, and the failure stays published past that.
    case absentAfterIdleWindow

    public static func of(
        loadState: EngineLoadState, clonePreparation: ClonePreparationPhase
    ) -> EngineHostModelPresence {
        if clonePreparation == .preparing { return .present }
        switch loadState {
        case .starting, .loaded, .running: return .present
        case .failed: return .absentAfterIdleWindow
        case .idle: return .absent
        }
    }
}

/// Keeps a long-lived host's lease in step with its engine's model (RF-61): held
/// while a model is loading or loaded, given back once the engine unloads it
/// (the idle unload, memory relief, an explicit unload) and taken again for the
/// next load. The host feeds it every state its engine publishes.
///
/// A host that admits itself before a load (the CLI's warm engine) hands the
/// admitted lease over with `adopt` and brackets each request with
/// `requestBegan` and `requestEnded`: while a request runs the lease stays,
/// whatever the engine publishes on the way to its load. A model that shows up
/// with no lease held gets one on the spot: that is the Mac app's whole use of
/// the keeper (`MacEngineHostCoordinator`), since it loads without an admission
/// step. A lease that cannot be written is skipped: it is advisory.
@MainActor
public final class EngineHostLeaseKeeper {
    private let kind: String
    private let folder: URL
    private let failureWindow: Duration
    public private(set) var lease: EngineHostLease?
    /// What the engine last published.
    public private(set) var presence = EngineHostModelPresence.absent
    private var requestsInFlight = 0
    private var provisionalHolds: [UUID: Task<Void, Never>] = [:]
    private var failureRelease: Task<Void, Never>?
    private var lastObservedUnloadEpoch: UInt64?

    /// `failureWindow` is how long a published failure keeps the lease: the
    /// tier's idle window, after which the engine has unloaded what it left.
    public init(kind: String, folder: URL = EngineHostLease.sharedFolder, failureWindow: Duration) {
        self.kind = kind
        self.folder = folder
        self.failureWindow = failureWindow
    }

    /// The idle window of `deviceClass` (the same for every mode), with room
    /// for the unload itself.
    public nonisolated static func failureWindow(for deviceClass: NativeDeviceMemoryClass) -> Duration {
        let policy = NativeMemoryPolicyResolver.policy(deviceClass: deviceClass, mode: .custom, isBatch: false)
        return .seconds((policy.unloadAfterIdleSeconds ?? 0) + 5)
    }

    public var holdsLease: Bool { lease != nil }
    private var hasActiveWork: Bool { requestsInFlight > 0 || !provisionalHolds.isEmpty }

    /// Takes over a lease its host was admitted with. A keeper that already
    /// holds one keeps it and gives the new one back.
    public func adopt(_ admitted: EngineHostLease?) {
        guard let admitted else { return }
        if let lease {
            if lease !== admitted { admitted.release() }
        } else {
            lease = admitted
        }
    }

    /// A request that may load a model starts.
    public func requestBegan() {
        requestsInFlight += 1
    }

    /// A request ended. One that loaded nothing gives its lease back at once.
    public func requestEnded() {
        requestsInFlight = max(requestsInFlight - 1, 0)
        settle(modelAppeared: false)
    }

    /// Adopts a provisionally acquired lease for a fire-and-forget start and
    /// holds it until the engine publishes `.present`, `endProvisionalHold(_:)`
    /// cancels it, or `timeout` elapses without a model appearing.
    @discardableResult
    public func beginProvisionalHold(
        adopting admitted: EngineHostLease?,
        timeout: Duration
    ) -> UUID {
        adopt(admitted)
        let id = UUID()
        provisionalHolds[id] = Task { [weak self, timeout] in
            try? await Task.sleep(for: timeout)
            guard !Task.isCancelled, let self else { return }
            self.endProvisionalHold(id)
        }
        return id
    }

    /// Ends a provisional hold early (for example, when a start was refused
    /// before reaching the engine) and releases the lease if nothing else holds it.
    public func endProvisionalHold(_ id: UUID) {
        guard let task = provisionalHolds.removeValue(forKey: id) else { return }
        task.cancel()
        settle(modelAppeared: false)
    }

    /// Records an explicit engine unload (`unloadModel()`,
    /// `trimMemory(.fullUnload)`, or `stop()`), cancelling any pending
    /// post-failure release window immediately. Unlike `clearVisibleError()`
    /// (which keeps weights resident and leaves `failureRelease` running), an
    /// explicit unload proves no weights remain, so the lease releases as soon
    /// as no request or provisional hold is active.
    public func modelUnloaded() {
        failureRelease?.cancel()
        failureRelease = nil
        presence = .absent
        if !hasActiveWork {
            release()
        }
    }

    /// The engine published a state. When the engine supplies a monotonically
    /// increasing `unloadEpoch` (incremented on `unloadModel()`,
    /// `trimMemory(.fullUnload)`, and `stop()`, never on `clearVisibleError()`),
    /// an advancing epoch cancels any pending post-failure release window right
    /// away instead of leaving a zombie lease for the idle window.
    public func engineChanged(
        loadState: EngineLoadState,
        clonePreparation: ClonePreparationPhase,
        unloadEpoch: UInt64? = nil
    ) {
        let unloaded = recordUnloadEpoch(unloadEpoch)
        let previous = presence
        presence = .of(loadState: loadState, clonePreparation: clonePreparation)
        if unloaded, presence != .present {
            failureRelease?.cancel()
            failureRelease = nil
            // Even when a failure message remains visible after an unload
            // (PA-32), no weights remain resident; do not re-arm `failureRelease`.
            presence = .absent
        }
        settle(modelAppeared: presence == .present && previous != .present)
    }

    /// Gives the lease up whatever the engine holds: the host is quitting.
    public func releaseNow() {
        failureRelease?.cancel()
        failureRelease = nil
        cancelProvisionalHolds()
        release()
    }

    private func recordUnloadEpoch(_ unloadEpoch: UInt64?) -> Bool {
        guard let unloadEpoch else { return false }
        defer { lastObservedUnloadEpoch = unloadEpoch }
        guard let previous = lastObservedUnloadEpoch else { return false }
        return unloadEpoch != previous
    }

    private func cancelProvisionalHolds() {
        for task in provisionalHolds.values {
            task.cancel()
        }
        provisionalHolds.removeAll()
    }

    private func settle(modelAppeared: Bool) {
        switch presence {
        case .present:
            failureRelease?.cancel()
            failureRelease = nil
            cancelProvisionalHolds()
            if lease == nil, modelAppeared {
                lease = try? EngineHostLease.acquire(in: folder, kind: kind)
            }
        case .absent:
            // A dismissed failure leaves its window running: the weights it
            // left may still be resident.
            guard !hasActiveWork, failureRelease == nil else { return }
            release()
        case .absentAfterIdleWindow:
            guard !hasActiveWork, lease != nil, failureRelease == nil else { return }
            failureRelease = Task { [weak self, failureWindow] in
                try? await Task.sleep(for: failureWindow)
                guard !Task.isCancelled, let self else { return }
                self.failureRelease = nil
                // A request running now settles the lease when it ends.
                if self.presence != .present, !self.hasActiveWork { self.release() }
            }
        }
    }

    private func release() {
        lease?.release()
        lease = nil
    }
}
