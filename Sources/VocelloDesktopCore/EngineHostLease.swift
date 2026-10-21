import Foundation
import QwenVoiceCore
import Synchronization
import System

/// A process hosting the engine says so with a lease: a file in one per-user
/// folder (`sharedFolder`; memory belongs to the Mac, not to a data folder) that
/// it holds locked (flock) for as long as its engine may be loaded. The lock
/// dies with the process, so a lease nobody holds is stale and is removed by the
/// next reader. RF-27: the CLI takes a lease and reads the others'; the Mac app
/// adopts leases with RF-30 (until then `DesktopAppPresence` stands in for it).
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
            guard flock(descriptor.rawValue, LOCK_EX | LOCK_NB) == 0 else { throw Errno(rawValue: errno) }
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
            defer { try? descriptor.close() }
            if flock(descriptor.rawValue, LOCK_SH | LOCK_NB) == 0 {
                // Nobody holds it: its process is gone.
                try? FileManager.default.removeItem(at: url)
                continue
            }
            let data = try? Data(contentsOf: url)
            hosts.append(data.flatMap { try? JSONDecoder().decode(Host.self, from: $0) }
                ?? Host(pid: 0, kind: "unknown", startedAt: ""))
        }
        return hosts
    }

    /// Gives the lease up (also when the process ends).
    public func release() {
        guard let descriptor = self.descriptor.withLock({ held -> FileDescriptor? in
            defer { held = nil }
            return held
        }) else { return }
        try? FileManager.default.removeItem(at: url)
        try? descriptor.close()
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
