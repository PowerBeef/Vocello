import Foundation
#if canImport(UIKit)
import UIKit
#endif

/// RF-59 (review finding 5): the model update's ledger, reclaim and plan work takes file locks in
/// the models folder, and iOS ends an app suspended while holding one (0xdead10cc). Such work holds
/// a background-time grant while it runs. The grant is ended when the work finishes, or by the
/// expiration handler when iOS reclaims the time first; the work then goes on, and may yet be
/// suspended. Off iOS (the Mac test host compiles this file by path) the work runs as it is.
@MainActor
enum IOSBackgroundTime {
    static func hold<T>(_ name: String, _ body: () async -> T) async -> T {
        #if canImport(UIKit)
        let grant = Grant()
        grant.identifier = UIApplication.shared.beginBackgroundTask(withName: name) { grant.end() }
        defer { grant.end() }
        #endif
        return await body()
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
