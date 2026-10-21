import Foundation
import QwenVoiceCore
import Synchronization
import System

/// A process hosting the engine on a data root says so with a lease: a file
/// under `<data>/engine-hosts/` it holds locked (flock) for as long as its
/// engine may be loaded. The lock dies with the process, so a lease nobody
/// holds is stale and is removed by the next reader. RF-27: the CLI takes a
/// lease and reads the others'; the Mac app adopts leases with RF-30 (until
/// then `DesktopAppPresence` stands in for it).
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

    static func directory(in dataDirectory: URL) -> URL {
        dataDirectory.appendingPathComponent("engine-hosts", isDirectory: true)
    }

    /// Takes a lease for this process. The file is written and locked under a
    /// temporary name and renamed into place, so no reader sees it unlocked.
    public static func acquire(dataDirectory: URL, kind: String) throws -> EngineHostLease {
        let folder = directory(in: dataDirectory)
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

    /// The hosts that hold a lease on `dataDirectory`, other than `excluding`.
    /// Stale leases (their process is gone) are removed on the way.
    public static func liveHosts(dataDirectory: URL, excluding: EngineHostLease? = nil) -> [Host] {
        let folder = directory(in: dataDirectory)
        let urls = (try? FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: nil)) ?? []
        var hosts: [Host] = []
        for url in urls where url.pathExtension == "lease" && url.standardizedFileURL != excluding?.url.standardizedFileURL {
            guard let descriptor = try? FileDescriptor.open(FilePath(url.path), .readOnly, options: [.closeOnExec]) else {
                continue
            }
            defer { try? descriptor.close() }
            if flock(descriptor.rawValue, LOCK_SH | LOCK_NB) == 0 {
                // Nobody holds it: its process is gone.
                try? FileManager.default.removeItem(at: url)
                continue
            }
            if let data = try? Data(contentsOf: url), let host = try? JSONDecoder().decode(Host.self, from: data) {
                hosts.append(host)
            }
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
    /// unless the caller insists; elsewhere it is allowed with a warning.
    public static func decide(
        otherHosts: [EngineHostLease.Host], appRunning: Bool, deviceClass: NativeDeviceMemoryClass,
        allowConcurrent: Bool
    ) -> EngineHostAdmission {
        var names = otherHosts.map { $0.kind == "app" ? "the Vocello app" : "vocello (pid \($0.pid))" }
        if appRunning, !otherHosts.contains(where: { $0.kind == "app" }) { names.append("the Vocello app") }
        guard !names.isEmpty else { return .proceed }
        let others = names.joined(separator: ", ")
        if deviceClass == .floor8GBMac, !allowConcurrent {
            return .refuse("another Vocello engine is running on this 8 GB Mac (\(others)), which holds one at a time")
        }
        return .warn("another Vocello engine is running on this Mac (\(others)); they share its memory")
    }
}
