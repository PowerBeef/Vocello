import Foundation
import Observation
import Sparkle
import SwiftUI

/// The macOS app's one updater (RF-23): Sparkle's standard controller with its
/// own update window and its own permission prompt on the second launch, so the
/// app checks nothing until the user agrees. The feed and the EdDSA public key
/// are `SUFeedURL` and `SUPublicEDKey` in `Sources/Info.plist`; Sparkle sends no
/// system profile, and `SUAllowsAutomaticUpdates` is off, so a new version is
/// always offered in Sparkle's window rather than installed silently. The feed
/// must carry the release key's signature (`SURequireSignedFeed`), and an
/// update's signature is checked before its disk image is mounted
/// (`SUVerifyUpdateBeforeExtraction`); both ship in the first version with
/// Sparkle because only an installed copy's own settings protect it. Settings mirrors the automatic-check preference, which Sparkle
/// keeps in the app's defaults, and Vocello > Check for Updates… follows
/// `canCheckForUpdates`, which is false while a check runs.
@MainActor
@Observable
final class MacSoftwareUpdater {
    private let controller: SPUStandardUpdaterController
    @ObservationIgnored private var observations: [NSKeyValueObservation] = []

    private(set) var canCheckForUpdates = false
    private(set) var checksAutomatically = false

    init() {
        controller = SPUStandardUpdaterController(
            startingUpdater: true,
            updaterDelegate: nil,
            userDriverDelegate: nil
        )
        refresh()
        // Sparkle changes these on the main thread; hop rather than assume it.
        // The second-launch prompt sets the preference without touching
        // canCheckForUpdates, so both are observed.
        observations = [
            controller.updater.observe(\.canCheckForUpdates) { [weak self] _, _ in
                Task { @MainActor in self?.refresh() }
            },
            controller.updater.observe(\.automaticallyChecksForUpdates) { [weak self] _, _ in
                Task { @MainActor in self?.refresh() }
            },
        ]
    }

    /// Re-reads Sparkle's state.
    func refresh() {
        canCheckForUpdates = controller.updater.canCheckForUpdates
        checksAutomatically = controller.updater.automaticallyChecksForUpdates
    }

    func setChecksAutomatically(_ enabled: Bool) {
        controller.updater.automaticallyChecksForUpdates = enabled
        refresh()
    }

    func checkForUpdates() {
        controller.checkForUpdates(nil)
    }
}

/// Vocello > Check for Updates…, a view of its own so the menu item's enabled
/// state follows the updater.
struct MacCheckForUpdatesButton: View {
    let updater: MacSoftwareUpdater

    var body: some View {
        Button(MacInterfaceText.checkForUpdates) {
            updater.checkForUpdates()
        }
        .disabled(!updater.canCheckForUpdates)
    }
}
