import Foundation
import QwenVoiceCore
#if canImport(UIKit)
import UIKit
#endif

/// RF-59 (review finding 5) & RB-07: the model update's ledger, reclaim, delete and plan work
/// takes file locks in the App Group models folder, and iOS ends an app suspended while holding
/// one (`0xdead10cc`). Such work holds a background-time grant while it runs. On expiration, the
/// shared `StorageBackgroundExpirationFlag` is marked before the grant is ended so multi-folder
/// loops stop before acquiring another file lock. Off iOS (the Mac test host compiles this file
/// by path) the work runs directly.
@MainActor
enum IOSBackgroundTime {
    static func hold<T>(_ name: String, _ body: () async -> T) async -> T {
        await hold(name) { _ in
            await body()
        }
    }

    static func hold<T>(
        _ name: String,
        _ body: (StorageBackgroundExpirationFlag) async -> T
    ) async -> T {
        let expirationFlag = StorageBackgroundExpirationFlag()
        #if canImport(UIKit)
        let grant = Grant()
        grant.identifier = UIApplication.shared.beginBackgroundTask(withName: name) {
            expirationFlag.markExpired()
            grant.end()
        }
        // RB-07: when iOS refuses a background task (app already suspending), the expiration
        // handler is never called; mark expired immediately so lock loops never enter `flock`.
        if grant.identifier == .invalid {
            expirationFlag.markExpired()
        }
        defer { grant.end() }
        #endif
        return await body(expirationFlag)
    }

    /// Synchronous MainActor background-time grant for short synchronous App Group
    /// lock operations (e.g. `deleteModel` / rollback inside `IOSModelDownloadCoordinator`).
    static func holdSync<T>(_ name: String, _ body: () throws -> T) rethrows -> T {
        #if canImport(UIKit)
        let grant = Grant()
        grant.identifier = UIApplication.shared.beginBackgroundTask(withName: name) {
            grant.end()
        }
        defer { grant.end() }
        #endif
        return try body()
    }

    #if canImport(UIKit)
    /// One grant, ended once: by the work's end or by the expiration handler, whichever comes first.
    @MainActor
    private final class Grant {
        var identifier: UIBackgroundTaskIdentifier = .invalid

        func end() {
            guard identifier != .invalid else { return }
            UIApplication.shared.endBackgroundTask(identifier)
            identifier = .invalid
        }
    }
    #endif
}
