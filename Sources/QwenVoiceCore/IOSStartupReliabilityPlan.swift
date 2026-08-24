import CryptoKit
import Foundation

public enum IOSStartupReliabilityPreparation: String, CaseIterable, Codable, Sendable {
    case production
    case fullRuntimeUnload = "full_runtime_unload"
    case preparedCacheClear = "prepared_cache_clear"
    case prewarmDisabled = "prewarm_disabled"
}

public struct IOSStartupReliabilityTake: Codable, Hashable, Sendable {
    public let takeIndex: Int
    public let takeID: String
    public let speakerID: String
    public let deliveryID: String
    public let language: String
    public let seed: UInt64
    public let variation: String
    public let streaming: Bool
    public let predecessorTakeID: String?
    public let preparation: IOSStartupReliabilityPreparation

    public var deliveryCell: DeliveryInstructionCell {
        get throws { try DeliveryInstructionCell.resolveStrict(deliveryID) }
    }

    public var resolvedLanguage: Qwen3SupportedLanguage {
        get throws {
            guard let language = Qwen3SupportedLanguage(rawValue: language) else {
                throw IOSStartupReliabilityPlanError.invalidLanguage(self.language)
            }
            return language
        }
    }

    public var resolvedVariation: Qwen3SamplingVariation {
        get throws {
            guard let variation = Qwen3SamplingVariation(rawValue: variation) else {
                throw IOSStartupReliabilityPlanError.invalidVariation(self.variation)
            }
            return variation
        }
    }
}

public struct IOSStartupReliabilityPlan: Codable, Hashable, Sendable {
    public let schemaVersion: Int
    public let scriptSHA256: String
    public let scriptCharacters: Int
    public let takes: [IOSStartupReliabilityTake]
}

public struct IOSStartupReliabilityLaunchSpec: Codable, Hashable, Sendable {
    public static let currentSchemaVersion = 1
    public static let maximumTakes = 128
    public static let maximumScriptCharacters = 2_000

    public let schemaVersion: Int
    public let runID: String
    public let plan: IOSStartupReliabilityPlan
    public let script: String

    public static func decodeAndValidate(_ rawValue: String) throws -> Self {
        guard let data = rawValue.data(using: .utf8) else {
            throw IOSStartupReliabilityPlanError.invalidUTF8
        }
        let spec: Self
        do {
            spec = try JSONDecoder().decode(Self.self, from: data)
        } catch {
            throw IOSStartupReliabilityPlanError.invalidJSON
        }
        try spec.validate()
        return spec
    }

    public func validate() throws {
        guard schemaVersion == Self.currentSchemaVersion,
              plan.schemaVersion == Self.currentSchemaVersion else {
            throw IOSStartupReliabilityPlanError.unsupportedSchema
        }
        guard Self.isSafeIdentifier(runID) else {
            throw IOSStartupReliabilityPlanError.invalidRunID
        }
        guard (1...Self.maximumScriptCharacters).contains(plan.scriptCharacters),
              script.count == plan.scriptCharacters,
              !script.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              !script.contains("\0") else {
            throw IOSStartupReliabilityPlanError.scriptIdentityMismatch
        }
        let scriptDigest = SHA256.hash(data: Data(script.utf8))
            .map { String(format: "%02x", $0) }
            .joined()
        guard scriptDigest == plan.scriptSHA256,
              Self.isSHA256(plan.scriptSHA256) else {
            throw IOSStartupReliabilityPlanError.scriptIdentityMismatch
        }
        guard (1...Self.maximumTakes).contains(plan.takes.count) else {
            throw IOSStartupReliabilityPlanError.invalidTakeCount
        }

        var seen = Set<String>()
        var predecessor: String?
        for (offset, take) in plan.takes.enumerated() {
            guard take.takeIndex == offset + 1 else {
                throw IOSStartupReliabilityPlanError.invalidTakeOrder
            }
            guard Self.isSafeIdentifier(take.takeID), seen.insert(take.takeID).inserted else {
                throw IOSStartupReliabilityPlanError.invalidTakeID(take.takeID)
            }
            guard take.predecessorTakeID == predecessor else {
                throw IOSStartupReliabilityPlanError.invalidPredecessor(take.takeID)
            }
            guard Self.isSafeSpeakerID(take.speakerID) else {
                throw IOSStartupReliabilityPlanError.invalidSpeaker(take.speakerID)
            }
            _ = try take.deliveryCell
            _ = try take.resolvedLanguage
            _ = try take.resolvedVariation
            predecessor = take.takeID
        }
    }

    private static func isSafeIdentifier(_ value: String) -> Bool {
        guard (1...96).contains(value.count), value.first?.isLetter == true || value.first?.isNumber == true else {
            return false
        }
        return value.unicodeScalars.allSatisfy {
            CharacterSet.alphanumerics.contains($0) || $0 == "." || $0 == "_" || $0 == "-"
        }
    }

    private static func isSafeSpeakerID(_ value: String) -> Bool {
        guard (1...32).contains(value.count) else { return false }
        return value.unicodeScalars.allSatisfy {
            CharacterSet.lowercaseLetters.contains($0)
                || CharacterSet.decimalDigits.contains($0)
                || $0 == "_"
        }
    }

    private static func isSHA256(_ value: String) -> Bool {
        value.count == 64 && value.unicodeScalars.allSatisfy {
            CharacterSet(charactersIn: "0123456789abcdef").contains($0)
        }
    }
}

public enum IOSStartupReliabilityPlanError: LocalizedError, Equatable, Sendable {
    case invalidUTF8
    case invalidJSON
    case unsupportedSchema
    case invalidRunID
    case scriptIdentityMismatch
    case invalidTakeCount
    case invalidTakeOrder
    case invalidTakeID(String)
    case invalidPredecessor(String)
    case invalidSpeaker(String)
    case invalidLanguage(String)
    case invalidVariation(String)

    public var errorDescription: String? {
        switch self {
        case .invalidUTF8: "Startup reliability launch input is not UTF-8."
        case .invalidJSON: "Startup reliability launch input is not valid schema-v1 JSON."
        case .unsupportedSchema: "Startup reliability launch input uses an unsupported schema."
        case .invalidRunID: "Startup reliability run ID is invalid."
        case .scriptIdentityMismatch: "Startup reliability script identity does not match its plan."
        case .invalidTakeCount: "Startup reliability plan must contain 1 through 128 takes."
        case .invalidTakeOrder: "Startup reliability take indexes must be contiguous from one."
        case .invalidTakeID(let value): "Startup reliability take ID is invalid or duplicated: \(value)."
        case .invalidPredecessor(let value): "Startup reliability predecessor is invalid for \(value)."
        case .invalidSpeaker(let value): "Startup reliability speaker is invalid: \(value)."
        case .invalidLanguage(let value): "Startup reliability language is invalid: \(value)."
        case .invalidVariation(let value): "Startup reliability variation is invalid: \(value)."
        }
    }
}
