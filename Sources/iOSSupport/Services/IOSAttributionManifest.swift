import Foundation

/// Decoded offline software and model attribution manifest backed by the bundled
/// `third_party_attributions.json`. Lives in `VocelloiOSPolicies` so both
/// `OpenSourceLicensesScreen` and deterministic unit tests exercise the exact
/// same decoder and hybrid-model attribution formatter (RB-11).
public struct IOSAttributionManifest: Decodable, Equatable, Sendable {
    public struct License: Decodable, Equatable, Identifiable, Sendable {
        public let id: String
        public let text: String
    }

    public struct Component: Decodable, Equatable, Identifiable, Sendable {
        public let id: String
        public let displayName: String
        public let version: String
        public let revision: String?
        public let sourceURL: String
        public let licenseID: String
        public let copyrightNotice: String?
        public let notice: String?
        public let origins: String?
        public let licenseTextOverride: String?
        public let platforms: [String]?

        public var appliesToIOS: Bool {
            guard let platforms else { return true }
            return platforms.contains("iOS")
        }
    }

    public struct AdditionalBase: Decodable, Equatable, Sendable {
        public let baseRepo: String
        public let baseRevision: String
        public let contribution: String?
    }

    public struct BuiltFromSource: Decodable, Equatable, Sendable {
        public let repo: String
        public let revision: String
    }

    public struct ModelArtifact: Decodable, Equatable, Identifiable, Sendable {
        public let id: String
        public let displayName: String
        public let variantID: String
        public let repo: String
        public let revision: String
        public let modelCardSHA256: String
        public let licenseID: String
        public let baseRepo: String
        public let baseRevision: String
        public let additionalBases: [AdditionalBase]?
        public let builtFrom: [BuiltFromSource]?
        public let copyrightNotice: String?
        public let notice: String?
        public let sourceURL: String

        /// Complete provenance notice including the 4-bit base, any 8-bit
        /// `additionalBases` (hybrid attention parents), and `builtFrom`
        /// source repositories (RB-11), or the auxiliary model's notice (RF-73 / E3).
        public var attributionNoticeText: String {
            var sections: [String] = []
            if let notice, !notice.isEmpty {
                sections.append(notice)
                sections.append("Artifact SHA-256: \(modelCardSHA256)")
                sections.append("Upstream: \(baseRepo) @ \(baseRevision)")
            } else {
                sections.append("Model card SHA-256: \(modelCardSHA256)")
                sections.append("Base: \(baseRepo) @ \(baseRevision)")
            }
            if let additionalBases, !additionalBases.isEmpty {
                let lines = additionalBases.map { extra in
                    if let contribution = extra.contribution, !contribution.isEmpty {
                        return "Additional base: \(extra.baseRepo) @ \(extra.baseRevision)\nContribution: \(contribution)"
                    }
                    return "Additional base: \(extra.baseRepo) @ \(extra.baseRevision)"
                }
                sections.append(lines.joined(separator: "\n\n"))
            }
            if let builtFrom, !builtFrom.isEmpty {
                let lines = builtFrom.map { "- \($0.repo) @ \($0.revision)" }
                sections.append("Built from:\n" + lines.joined(separator: "\n"))
            }
            return sections.joined(separator: "\n\n")
        }
    }

    public let licenses: [License]
    public let components: [Component]
    public let modelArtifacts: [ModelArtifact]

    /// Components that ship in the iOS app (omits macOS-only dependencies such as Sparkle; RF-73 / E3).
    public var iosComponents: [Component] {
        components.filter(\.appliesToIOS)
    }

    public static func load(from bundle: Bundle = .main) throws -> Self {
        guard let url = bundle.url(forResource: "third_party_attributions", withExtension: "json") else {
            throw CocoaError(.fileNoSuchFile)
        }
        return try JSONDecoder().decode(Self.self, from: Data(contentsOf: url))
    }
}
