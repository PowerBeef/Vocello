import CryptoKit
import Foundation

/// Privacy-safe sampling take evidence for Phase 5 promotion gates.
///
/// Planned and observed seeds must agree when both are present. Missing either
/// side fails closed for promotion-quality evidence. The WAV digest is content
/// identity only — never a path, prompt, or transcript.
public struct SamplingTakeEvidence: Codable, Hashable, Sendable {
    public static let currentAlgorithmVersion = 2

    public enum SeedSource: String, Codable, Hashable, Sendable {
        case requested
        case generated
    }

    public enum AgreementError: Error, Equatable, Sendable {
        case unsupportedAlgorithmVersion(Int)
        case missingPlannedSeed
        case missingObservedSeed
        case seedMismatch(planned: UInt64, observed: UInt64)
        case missingWAVDigest
        case malformedWAVDigest
    }

    public let algorithmVersion: Int
    public let plannedSeed: UInt64?
    public let observedSeed: UInt64?
    public let seedSource: SeedSource
    public let wavDigest: String?

    public init(
        algorithmVersion: Int = Self.currentAlgorithmVersion,
        plannedSeed: UInt64?,
        observedSeed: UInt64?,
        seedSource: SeedSource,
        wavDigest: String?
    ) {
        self.algorithmVersion = algorithmVersion
        self.plannedSeed = plannedSeed
        self.observedSeed = observedSeed
        self.seedSource = seedSource
        self.wavDigest = wavDigest?.lowercased()
    }

    /// Fail-closed agreement check for promotion-quality fixed-seed evidence.
    public func validatedForPromotion() throws -> Self {
        guard algorithmVersion == Self.currentAlgorithmVersion else {
            throw AgreementError.unsupportedAlgorithmVersion(algorithmVersion)
        }
        guard let plannedSeed else { throw AgreementError.missingPlannedSeed }
        guard let observedSeed else { throw AgreementError.missingObservedSeed }
        guard plannedSeed == observedSeed else {
            throw AgreementError.seedMismatch(planned: plannedSeed, observed: observedSeed)
        }
        guard let wavDigest, !wavDigest.isEmpty else {
            throw AgreementError.missingWAVDigest
        }
        guard wavDigest.count == 64,
              wavDigest.unicodeScalars.allSatisfy({ CharacterSet(charactersIn: "0123456789abcdef").contains($0) })
        else {
            throw AgreementError.malformedWAVDigest
        }
        return self
    }

    /// Reconstruct evidence from privacy-safe telemetry notes.
    public init?(telemetryNotes notes: [String: String]) {
        guard let algorithmVersion = notes["samplingAlgorithmVersion"].flatMap(Int.init) else {
            return nil
        }
        guard let seedSource = notes["samplingSeedSource"].flatMap(SeedSource.init(rawValue:)) else {
            return nil
        }
        self.init(
            algorithmVersion: algorithmVersion,
            plannedSeed: notes["samplingPlannedSeed"].flatMap(UInt64.init),
            observedSeed: notes["samplingObservedSeed"].flatMap(UInt64.init)
                ?? notes["samplingSeed"].flatMap(UInt64.init),
            seedSource: seedSource,
            wavDigest: notes["samplingWAVDigest"]
        )
    }

    public var telemetryNotes: [String: String] {
        var notes: [String: String] = [
            "samplingAlgorithmVersion": String(algorithmVersion),
            "samplingSeedSource": seedSource.rawValue,
        ]
        if let plannedSeed {
            notes["samplingPlannedSeed"] = String(plannedSeed)
        }
        if let observedSeed {
            notes["samplingSeed"] = String(observedSeed)
            notes["samplingObservedSeed"] = String(observedSeed)
        }
        if let wavDigest {
            notes["samplingWAVDigest"] = wavDigest
        }
        if let plannedSeed, let observedSeed {
            notes["samplingSeedAgreement"] = plannedSeed == observedSeed ? "matched" : "mismatched"
        } else {
            notes["samplingSeedAgreement"] = "incomplete"
        }
        return notes
    }

    /// Fail-closed promotion packaging: validated seeds/WAV digest plus an explicit
    /// packaged marker for history and promotion tooling.
    public func packagedTelemetryNotes() throws -> [String: String] {
        var notes = try validatedForPromotion().telemetryNotes
        notes["samplingPromotionPackaged"] = "true"
        return notes
    }

    public static func sha256FileDigest(at url: URL) throws -> String {
        try FileStreamIO.sha256Hex(of: url)
    }
}

/// Versioned, domain-separated sub-seed derivation for later long-form and
/// candidate work. Shipping generation still uses the request effective seed
/// directly; this API defines the Phase 5 contract so Phase 11/12 can adopt it
/// without inventing a second derivation scheme.
public enum SamplingSubSeedDerivation: Sendable {
    public static let currentAlgorithmVersion = 1

    public enum Domain: String, Sendable {
        case longFormSegment = "vocello.sampling.subseed.long-form-segment.v1"
        case candidateRetry = "vocello.sampling.subseed.candidate-retry.v1"
        case characterizationControl = "vocello.sampling.subseed.characterization-control.v1"
    }

    public enum DerivationError: Error, Equatable, Sendable {
        case emptyComponent(String)
        case unsupportedAlgorithmVersion(Int)
    }

    public static func derive(
        baseSeed: UInt64,
        domain: Domain,
        components: [String],
        algorithmVersion: Int = Self.currentAlgorithmVersion
    ) throws -> UInt64 {
        guard algorithmVersion == Self.currentAlgorithmVersion else {
            throw DerivationError.unsupportedAlgorithmVersion(algorithmVersion)
        }
        for (index, component) in components.enumerated() {
            guard !component.isEmpty else {
                throw DerivationError.emptyComponent("components[\(index)]")
            }
        }
        let serialization = ([domain.rawValue, String(algorithmVersion), String(baseSeed)] + components)
            .map { "\($0.utf8.count):\($0)" }
            .joined()
        return SHA256.hash(data: Data(serialization.utf8)).prefix(8).reduce(UInt64(0)) {
            ($0 << 8) | UInt64($1)
        }
    }
}
