import Foundation

/// The source-level twin of the App Store installation capability declared in Info.plist.
///
/// Apple defines `iphone-performance-gaming-tier` as iPhone 15 Pro / Pro Max performance or
/// later. Vocello keeps a runtime guard as defense in depth, but the App Store capability is the
/// primary install-time filter. Keep this value, the runtime predicate, and Info.plist aligned.
enum IOSDeviceEligibilityPolicy {
    static let requiredCapabilities = ["arm64", "iphone-performance-gaming-tier"]
    static let minimumHardwareDescription = "iPhone 15 Pro or newer"

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
