import CryptoKit
import Foundation

/// Privacy-safe provenance for an internal runtime override set. Values are
/// never retained: the digest binds them without exposing paths, prompts, or
/// other potentially sensitive launch input.
public struct RuntimeDebugProvenance: Hashable, Codable, Sendable {
    public let internalDiagnosticsAvailable: Bool
    public let masterGateRequested: Bool
    public let activeOverrideKeys: [String]
    public let activeOverrideDigest: String?
}

/// The single process-local gate for environment variables that may alter
/// production runtime behavior. Two independent conditions are required:
/// the binary must carry the repository-owned internal diagnostics capability
/// and `QWENVOICE_DEBUG` must explicitly enable overrides for that process.
/// Distribution builds omit the compile condition, so process environment
/// alone can never activate these paths.
public enum RuntimeDebugGate {
    public static var internalDiagnosticsAvailable: Bool {
        #if VOCELLO_INTERNAL_DIAGNOSTICS
        true
        #else
        false
        #endif
    }

    public static func isEnabled(
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) -> Bool {
        isEnabled(
            environment: environment,
            internalDiagnosticsAvailable: internalDiagnosticsAvailable
        )
    }

    static func isEnabled(
        environment: [String: String],
        internalDiagnosticsAvailable: Bool
    ) -> Bool {
        guard internalDiagnosticsAvailable else { return false }
        return masterGateRequested(environment: environment)
    }

    private static func masterGateRequested(environment: [String: String]) -> Bool {
        guard let raw = environment["QWENVOICE_DEBUG"]?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased() else {
            return false
        }
        return ["1", "true", "on", "yes"].contains(raw)
    }

    public static func value(
        for key: String,
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) -> String? {
        value(
            for: key,
            environment: environment,
            internalDiagnosticsAvailable: internalDiagnosticsAvailable
        )
    }

    static func value(
        for key: String,
        environment: [String: String],
        internalDiagnosticsAvailable: Bool
    ) -> String? {
        guard isEnabled(
            environment: environment,
            internalDiagnosticsAvailable: internalDiagnosticsAvailable
        ) else { return nil }
        return environment[key]
    }

    /// Reads a contract-classified observability-only key. These values may
    /// select bounded telemetry or correlation metadata, but may never change
    /// product policy, output bytes, storage roots, or model behavior.
    public static func observabilityValue(
        for key: String,
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) -> String? {
        environment[key]
    }

    /// Captures only key names plus a digest of the exact key/value set. This
    /// is embedded in generation telemetry so any internal run that changes
    /// output remains attributable without retaining raw environment values.
    public static func provenance(
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) -> RuntimeDebugProvenance {
        provenance(
            environment: environment,
            internalDiagnosticsAvailable: internalDiagnosticsAvailable
        )
    }

    static func provenance(
        environment: [String: String],
        internalDiagnosticsAvailable: Bool
    ) -> RuntimeDebugProvenance {
        let masterRequested = masterGateRequested(environment: environment)
        let active = isEnabled(
            environment: environment,
            internalDiagnosticsAvailable: internalDiagnosticsAvailable
        )
        let keys = active
            ? environment.keys.filter {
                $0 != "QWENVOICE_DEBUG"
                    && ($0.hasPrefix("QWENVOICE_") || $0.hasPrefix("QVOICE_"))
            }.sorted()
            : []
        let digest: String? = keys.isEmpty ? nil : {
            var bytes = Data()
            for key in keys {
                let value = environment[key] ?? ""
                for component in [key, value] {
                    bytes.append(Data("\(component.utf8.count):".utf8))
                    bytes.append(Data(component.utf8))
                }
            }
            return SHA256.hash(data: bytes)
                .map { String(format: "%02x", $0) }
                .joined()
        }()
        return RuntimeDebugProvenance(
            internalDiagnosticsAvailable: internalDiagnosticsAvailable,
            masterGateRequested: masterRequested,
            activeOverrideKeys: keys,
            activeOverrideDigest: digest
        )
    }
}
