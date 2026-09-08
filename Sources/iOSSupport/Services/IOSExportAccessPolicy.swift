import Foundation

/// iOS outward-export policy. Generation, playback, internal History and
/// enrollment never consult this policy. macOS/CLI do not compile this source.
enum IOSExportProvenance: Equatable, Sendable {
    case builtIn
    case generatedPremium
    case originalReference
    /// Audio and journals from an actual failed storage transaction only.
    /// Never used for ordinary History, generated-player or folder exports.
    case recoveryRecord
    case unknown

    init(generationMode: String?) {
        switch generationMode?.lowercased() {
        case "custom": self = .builtIn
        case "design", "clone": self = .generatedPremium
        default: self = .unknown
        }
    }

    var requiresUnlock: Bool {
        switch self {
        case .builtIn, .originalReference, .recoveryRecord: false
        case .generatedPremium, .unknown: true
        }
    }
}

enum IOSExportAccessPolicy {
    /// Proposed identifier; RF-02 must approve it before creating the live IAP.
    /// No runtime override, cached paid flag, or diagnostics entitlement bypass.
    static let productID = "com.patricedery.vocello.design-clone-export"

    static func permits(_ items: [IOSExportProvenance], unlocked: Bool) -> Bool {
        !items.isEmpty && (unlocked || items.allSatisfy { !$0.requiresUnlock })
    }
}
