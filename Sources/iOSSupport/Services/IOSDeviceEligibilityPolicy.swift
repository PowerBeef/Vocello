import Foundation

/// The source-level twin of the App Store installation capability declared in Info.plist.
///
/// Apple's device data lists `iphone-performance-gaming-tier` for iPhone 15 Pro and later, and
/// also for 8 GB+ M-series iPad Pro / iPad Air models and iPad mini (A17 Pro). Per maintainer
/// decision 2026-11-25 (RF-42 / RF-73, Guideline 2.4.1), Vocello remains iPhone-targeted
/// (`TARGETED_DEVICE_FAMILY: "1"`) while admitting those eligible 8 GB+ iPads in portrait iPhone
/// compatibility mode instead of stranding them on an unsupported-device wall. Keep this value,
/// the runtime predicate, and Info.plist aligned.
public enum IOSDeviceEligibilityPolicy {
    public static let requiredCapabilities = ["arm64", "iphone-performance-gaming-tier"]
    /// The floor's product name, substituted into the localized unsupported-device copy.
    public static let minimumHardwareModel = "iPhone 15 Pro"

    public static func isSupportedMachineIdentifier(_ identifier: String) -> Bool {
        if identifier == "iPhone16,1" || identifier == "iPhone16,2" {
            return true
        }
        if identifier.hasPrefix("iPhone") {
            let majorVersion = parseVersionComponents(identifier, prefix: "iPhone")?.major
            return (majorVersion ?? 0) >= 17
        }
        if identifier.hasPrefix("iPad"),
           let version = parseVersionComponents(identifier, prefix: "iPad") {
            switch version.major {
            case 13:
                // M1 iPad Pro 11"/12.9" (13,4..13,11) and M1 iPad Air 5th gen (13,16..13,17).
                return (4...11).contains(version.minor) || (16...17).contains(version.minor)
            case 14:
                // M2 iPad Pro (14,3..14,6) and M2 iPad Air 11"/13" (14,8..14,11).
                return (3...6).contains(version.minor) || (8...11).contains(version.minor)
            case 15:
                // M3 iPad Air 11"/13" (15,3..15,6); excludes A16 iPad 11th gen (15,7..15,8).
                return (3...6).contains(version.minor)
            case 16...:
                // iPad mini (A17 Pro), M4/M5+ iPad Pro & iPad Air (8 GB+ gaming tier).
                return true
            default:
                return false
            }
        }
        return false
    }

    private static func parseVersionComponents(
        _ identifier: String,
        prefix: String
    ) -> (major: Int, minor: Int)? {
        let parts = identifier.dropFirst(prefix.count).split(separator: ",", omittingEmptySubsequences: false)
        guard parts.count == 2,
              let major = Int(parts[0]),
              let minor = Int(parts[1]),
              major > 0,
              minor > 0 else {
            return nil
        }
        return (major, minor)
    }
}
