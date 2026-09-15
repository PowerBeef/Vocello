import Foundation
import os

/// The macOS interface language. The owner is an `IOSAppLanguage` (compiled
/// by path; its iOS behavior is frozen) that the app bootstraps over
/// `AppDefaults.store`, so the selection lives beside every other macOS
/// preference and stays out of the real defaults under the debug suite (the
/// core tests bootstrap one over a fixture suite); it resolves the selection to a
/// `VocelloLocalization` and hands it to `MacInterfaceText`, whose callers
/// include nonisolated presentation values (`TTSModelVariantKind.displayName`,
/// `LocalizedError` descriptions, draft descriptions). On the main thread the
/// read goes through the observable owner, so a SwiftUI body that renders
/// catalog copy re-renders when the selection changes; elsewhere it reads the
/// snapshot published at launch and at every change.
enum MacInterfaceLanguage {
    @MainActor private(set) static var owner = IOSAppLanguage()

    private static let snapshot = OSAllocatedUnfairLock(initialState: VocelloLocalization())

    static var current: VocelloLocalization {
        // `MainActor.assumeIsolated` verifies the main thread, which is what
        // `Thread.isMainThread` just established; the guard keeps the read
        // total for the nonisolated callers that run off the main thread.
        if Thread.isMainThread {
            return MainActor.assumeIsolated { owner.localization }
        }
        return snapshot.withLock { $0 }
    }

    /// The stored selection: `IOSAppLanguage.system` or a language identifier.
    @MainActor static var selection: String { owner.selection }

    /// Languages the bundle actually carries, in the owner's order.
    @MainActor static var availableLanguages: [IOSUILanguage] { owner.availableLanguages }

    @MainActor static func select(_ identifier: String) {
        owner.select(identifier)
        publish()
    }

    /// Re-resolves System Default after the system language changed while the
    /// app ran; the app calls this whenever it becomes active.
    @MainActor static func refreshSystemLanguage() {
        owner.refreshSystemLanguage()
        publish()
    }

    /// Installs the owner (the app: over `AppDefaults.store`, before any view
    /// renders) and publishes its localization.
    @MainActor static func bootstrap(_ newOwner: IOSAppLanguage) {
        owner = newOwner
        publish()
    }

    /// Copies the owner's localization into the off-main snapshot; called at
    /// launch and after every change to the selection.
    @MainActor static func publish() {
        let localization = owner.localization
        snapshot.withLock { $0 = localization }
    }
}
