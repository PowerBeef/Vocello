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

    /// A saved voice's provenance comes from its enrollment sidecar: no generated
    /// source is the user's own reference. When the sidecar cannot be read, the
    /// voice's audio decides (RF-13): Design and Clone publications embed their
    /// mode as Vocello provenance and stay locked; a recording carries none and
    /// stays free, as original references always are.
    init(savedVoiceGeneratedSourceMode mode: String?, sidecarUnreadable: Bool, audioProvenanceMode: String?) {
        if sidecarUnreadable {
            self = audioProvenanceMode.map { IOSExportProvenance(generationMode: $0) } ?? .originalReference
        } else if let mode {
            self.init(generationMode: mode)
        } else {
            self = .originalReference
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
    /// Approved App Store Connect non-consumable identifier (RF-02).
    /// No runtime override, cached paid flag, or diagnostics entitlement bypass.
    static let productID = "com.patricedery.vocello.design_clone_export"

    static func permits(_ items: [IOSExportProvenance], unlocked: Bool) -> Bool {
        !items.isEmpty && (unlocked || items.allSatisfy { !$0.requiresUnlock })
    }
}
