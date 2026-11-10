import Foundation

/// The source-level twin of the App Store installation capability declared in Info.plist.
///
/// Apple's device data lists `iphone-performance-gaming-tier` for iPhone 15 Pro and later, and
/// also for M1-or-later iPad Pro and iPad Air and the iPad mini (A17 Pro). The capability is the
/// install-time filter; this runtime guard then admits iPhones only, so those iPads see the
/// unsupported-device screen (maintainer decision 2026-11-10, RF-42). Keep this value, the
/// runtime predicate, and Info.plist aligned.
enum IOSDeviceEligibilityPolicy {
    static let requiredCapabilities = ["arm64", "iphone-performance-gaming-tier"]
    /// The floor's product name, substituted into the localized unsupported-device copy.
    static let minimumHardwareModel = "iPhone 15 Pro"

    static func isSupportedMachineIdentifier(_ identifier: String) -> Bool {
        if identifier == "iPhone16,1" || identifier == "iPhone16,2" {
            return true
        }
        guard identifier.hasPrefix("iPhone") else { return false }
        let majorVersion = identifier
            .dropFirst("iPhone".count)
            .split(separator: ",")
            .first
            .map(String.init)
            .flatMap(Int.init)
        return (majorVersion ?? 0) >= 17
    }
}
